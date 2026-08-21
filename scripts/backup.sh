#!/usr/bin/env bash
# Nightly backup of everything that cannot be regenerated from the git
# repository.
#
# WHY THIS IS NOT OPTIONAL
# ------------------------
# Postgres here is not just an account store. It holds:
#   - users / sessions / invite_tokens          (identity)
#   - ownership_index                           (who owns which job/thread)
#   - admin_audit_log                           (append-only, trigger-enforced)
#   - checkpoints / checkpoint_blobs / checkpoint_writes
#         (every conversation's full chat history -- app/agent/graph.py
#          switches to PostgresSaver whenever QC_AGENT_DATABASE_URL is set)
#
# Losing it therefore loses all chat history outright, and does something
# worse than losing accounts: dropping ownership_index makes every existing
# job UNOWNED, and app/auth/ownership.py's documented policy is that an
# unowned resource is accessible to everyone. A database loss silently
# converts every user's private results into shared ones.
#
# The dump is taken with pg_dump against the WHOLE database, deliberately
# not scoped to the auth tables -- an earlier comment in docker-compose.yml
# claimed chat content lived outside Postgres, which was true before the
# checkpointer swap and is not true now. Do not re-narrow this.
#
# WHAT IS DELIBERATELY NOT BACKED UP HERE, BY DEFAULT
# ----------------------------------------------------
# data/jobs (job artifacts) and data/kb (the Chroma vector store) are not
# copied by default. They are bulk data on /data with its own redundancy, they
# dwarf everything else, and a nightly full copy of them would be the reason
# this script gets disabled. data/kb is in any case reproducible from
# data/scraped via scripts/seed_knowledge_base.py. If you want them on every
# run, snapshot /data at the filesystem level instead of here, or pass --full
# (see below) for an explicit, occasional, everything-included backup -- e.g.
# before running scripts/update.sh on a standalone deployment, where there is
# no separate dev stack to fall back to if something goes wrong.
#
# --full additionally archives data/jobs, data/kb, data/uploads,
# data/geometry_uploads, data/bug_reports and data/molecules into one
# full_data.tar.gz alongside the database dump. This is slower and produces a
# much larger backup, proportional to however much computational work is
# sitting in data/jobs -- deliberately not the default for the same reason
# these directories are excluded above, but restore.sh can put it all back
# when it's what you asked for.
#
# Usage:
#     ./scripts/backup.sh              # write one timestamped backup
#     ./scripts/backup.sh --full       # also archive data/jobs, data/kb, etc.
#     ./scripts/backup.sh --list       # show what is currently retained
#
# Installed as a user crontab (no root needed) -- see docs/DEPLOYMENT.md.
set -euo pipefail

FULL=0
ARGS=()
for arg in "$@"; do
    case "$arg" in
        --full) FULL=1 ;;
        *) ARGS+=("$arg") ;;
    esac
done
set -- "${ARGS[@]+"${ARGS[@]}"}"

cd "$(dirname "$0")/.."
REPO_ROOT="$(pwd)"

# Configuration comes from the environment first and this deployment's own .env
# second, in that order, so an explicit variable still wins.
#
# Reading .env matters more than it looks. This script's two callers both have
# nearly-empty environments: cron (the documented install, see docs/DEPLOYMENT.md)
# and scripts/update.sh, which takes a backup before every update. Neither
# exports .env. Without this the default below applied instead, and the default
# writes INSIDE the repository -- which for update.sh would mean the first
# backup left the checkout dirty and every subsequent update refused by its own
# clean-tree gate.
#
# Values are read rather than sourced: .env holds the Postgres password and the
# JWT secret, and a backup script should not be executing the contents of the
# file it is backing up.
envget() {
    [ -f "$REPO_ROOT/.env" ] || return 0
    sed -nE "s/^[[:space:]]*$1=(.*)$/\1/p" "$REPO_ROOT/.env" | tail -n1 | sed -E 's/^"(.*)"$/\1/'
}

# Point this at a filesystem with real room -- NOT the root filesystem, where
# /var/lib/docker already sits and which is usually the tighter of the two.
BACKUP_ROOT="${QC_AGENT_BACKUP_DIR:-$(envget QC_AGENT_BACKUP_DIR)}"
BACKUP_ROOT="${BACKUP_ROOT:-$REPO_ROOT/backups}"
RETAIN_DAYS="${QC_AGENT_BACKUP_RETAIN_DAYS:-30}"

# A backup written inside the repository is a backup that shows up in
# `git status`, and a dirty production tree blocks the next promotion. It is also
# on whichever filesystem the checkout happens to sit on, which is not a choice
# anyone made deliberately. Warn rather than refuse: on a machine where the
# checkout genuinely is the roomy filesystem this is merely untidy.
case "$BACKUP_ROOT" in
    "$REPO_ROOT"|"$REPO_ROOT"/*)
        echo "[backup] WARNING: writing backups inside the repository ($BACKUP_ROOT)."
        echo "[backup] Set QC_AGENT_BACKUP_DIR in .env to somewhere outside it."
        ;;
esac

if [ "${1:-}" = "--list" ]; then
    if [ -d "$BACKUP_ROOT" ]; then
        du -sh "$BACKUP_ROOT" 2>/dev/null
        ls -lh "$BACKUP_ROOT" | tail -n +2
    else
        echo "No backups yet at $BACKUP_ROOT"
    fi
    exit 0
fi

STAMP="$(date +%Y%m%d-%H%M%S)"
DEST="${BACKUP_ROOT}/${STAMP}"
mkdir -p "$DEST"
# Contains a database dump and the JWT secret. Not group- or world-readable
# on a host shared with other tenants.
chmod 700 "$BACKUP_ROOT" "$DEST"

log() { echo "[backup ${STAMP}] $*"; }

# --- Postgres -------------------------------------------------------------
# Run inside the running postgres container rather than needing a psql
# client on the host. `docker compose exec -T` (no TTY) is required for the
# redirect to behave under cron.
#
# If the stack is down there is nothing to dump and no safe way to fake one:
# fail loudly rather than writing an empty file that looks like a backup.
if ! docker compose ps --status running --services 2>/dev/null | grep -qx postgres; then
    log "ERROR: the postgres service is not running -- no dump taken."
    log "Start the stack (docker compose up -d) and re-run."
    rmdir "$DEST" 2>/dev/null || true
    exit 1
fi

# Same environment-then-.env order, and for the same reason: a deployment that
# renamed its database in .env would otherwise have cron dumping a database that
# does not exist, and pg_dump's failure would be the first anyone heard of it.
PGUSER_VAL="${QC_AGENT_POSTGRES_USER:-$(envget QC_AGENT_POSTGRES_USER)}"
PGUSER_VAL="${PGUSER_VAL:-qc_agent}"
PGDB_VAL="${QC_AGENT_POSTGRES_DB:-$(envget QC_AGENT_POSTGRES_DB)}"
PGDB_VAL="${PGDB_VAL:-qc_agent}"

log "dumping database ${PGDB_VAL}"
# --clean --if-exists makes the dump restorable over an existing database
# without hand-dropping objects first. Custom format (-Fc) so pg_restore can
# do a parallel/selective restore and so the dump is compressed on the way
# out rather than needing a separate gzip pass.
docker compose exec -T postgres \
    pg_dump -U "$PGUSER_VAL" -d "$PGDB_VAL" --clean --if-exists -Fc \
    > "${DEST}/postgres.dump"

# A truncated dump is worse than no dump, because it looks like one. Verify
# the archive's table of contents is readable before declaring success.
# pg_restore reads the archive from stdin when given no file argument,
# which avoids needing the dump to be visible inside the container.
if ! docker compose exec -T postgres pg_restore --list \
        < "${DEST}/postgres.dump" > "${DEST}/postgres.toc" 2>/dev/null; then
    log "ERROR: the dump just written is not a readable pg_restore archive."
    log "Keeping ${DEST} for inspection. Treat this run as FAILED."
    exit 1
fi
log "dump verified ($(du -h "${DEST}/postgres.dump" | cut -f1))"

# --- Secrets and config ---------------------------------------------------
# .env holds QC_AGENT_JWT_SECRET and the Postgres password. Without the
# password the dump above cannot be restored; without the JWT secret every
# issued session cookie becomes invalid on restore. Backing up the database
# without these is backing up something you cannot fully use.
#
# docker-compose.override.yml is here for a related reason, learned the hard
# way: it is untracked, host-specific, and the ONLY thing that bind-mounts the
# licensed QC engines into the api container. A running container keeps the
# mounts it was created with, so this file can disappear from disk while the
# deployment carries on working perfectly -- and the loss only surfaces at the
# next `compose up`, as a stack that silently has no ORCA or BAGEL. That
# happened on this host with no copy anywhere, because this loop did not include
# it. Nothing else in the project would notice its absence either.
#
# .update-log is small and untracked for the same "true of this directory,
# not of the project" reason: it's the only record of which commit
# scripts/update.sh --rollback should go back to.
for f in .env docker-compose.override.yml .update-log \
         nginx/certs/intranet.crt nginx/certs/intranet.key \
         nginx/certs/public.crt nginx/certs/public.key; do
    if [ -f "${REPO_ROOT}/${f}" ]; then
        mkdir -p "${DEST}/$(dirname "$f")"
        cp -p "${REPO_ROOT}/${f}" "${DEST}/${f}"
    fi
done

# Small, high-value, and genuinely lost if the disk goes: the thread
# registry and the molecule cache. Both are tiny.
for f in data/threads.json; do
    [ -f "${REPO_ROOT}/${f}" ] && { mkdir -p "${DEST}/$(dirname "$f")"; cp -p "${REPO_ROOT}/${f}" "${DEST}/${f}"; }
done

# --- Full data/ archive (opt-in via --full) --------------------------------
if [ "$FULL" -eq 1 ]; then
    log "archiving data/jobs, data/kb, data/uploads, data/geometry_uploads, "
    log "data/bug_reports, data/molecules (--full was passed -- this can be slow)"
    FULL_DATA_DIRS=(jobs kb uploads geometry_uploads bug_reports molecules)
    EXISTING_DIRS=()
    for d in "${FULL_DATA_DIRS[@]}"; do
        [ -d "${REPO_ROOT}/data/${d}" ] && EXISTING_DIRS+=("data/${d}")
    done
    if [ "${#EXISTING_DIRS[@]}" -gt 0 ]; then
        tar -C "$REPO_ROOT" -czf "${DEST}/full_data.tar.gz" "${EXISTING_DIRS[@]}"
        log "full data archive written ($(du -h "${DEST}/full_data.tar.gz" | cut -f1))"
    else
        log "no data/ subdirectories to archive"
    fi
fi

# Record what produced this, so a restore years later is not guesswork.
{
    echo "created:     $(date -Is)"
    echo "host:        $(hostname -f)"
    echo "repo:        ${REPO_ROOT}"
    echo "git commit:  $(git -C "${REPO_ROOT}" rev-parse HEAD 2>/dev/null || echo unknown)"
    echo "git branch:  $(git -C "${REPO_ROOT}" rev-parse --abbrev-ref HEAD 2>/dev/null || echo unknown)"
    echo "pg database: ${PGDB_VAL}"
    echo "pg user:     ${PGUSER_VAL}"
    echo "full data:   $([ "$FULL" -eq 1 ] && echo yes || echo no)"
} > "${DEST}/MANIFEST.txt"

chmod -R go-rwx "$DEST"
log "wrote ${DEST}"

# --- Retention ------------------------------------------------------------
# Prune by directory mtime. -maxdepth 1 -mindepth 1 so the root itself is
# never a candidate.
if [ -d "$BACKUP_ROOT" ]; then
    pruned="$(find "$BACKUP_ROOT" -mindepth 1 -maxdepth 1 -type d -mtime "+${RETAIN_DAYS}" -print -exec rm -rf {} + 2>/dev/null | wc -l)"
    [ "$pruned" -gt 0 ] && log "pruned ${pruned} backup(s) older than ${RETAIN_DAYS} days"
fi

log "done"
