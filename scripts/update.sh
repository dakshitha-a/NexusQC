#!/usr/bin/env bash
# Updates a STANDALONE NexusQC deployment (one produced by scripts/install.sh)
# to a newer commit from the git remote it was cloned from.
#
# WHICH REMOTE THIS PULLS FROM
# -----------------------------
# This script always fetches and resolves refs against this checkout's own
# `origin` -- whatever that is. For a deployment created by scripts/install.sh,
# that is the PUBLIC NexusQC release repository (the same one `git clone` was
# pointed at during install), not this project's own private development
# remote. There is no second "public" remote to disambiguate here, unlike the
# maintainers' own dev/production checkouts -- a standalone install has one
# remote, and it is the release stream.
#
# HOW THIS DIFFERS FROM scripts/promote.sh
# ------------------------------------------
# promote.sh is the maintainers' own tool: it moves their PRODUCTION checkout
# to a commit their separate DEV checkout has already run the standing test
# suite against, gated on a row in docs/deployment-ledger.md. That gate only
# makes sense when a second, verifying checkout exists. A standalone install
# has no second checkout -- it IS the deployment -- so this script skips the
# ledger check entirely and relies instead on: the same destructive-change
# report promote.sh uses, an unconditional FULL backup (not promote.sh's
# lighter default, since there is no separate dev stack to fall back to if
# something about data/ goes wrong), and the same in-flight-job drain/force
# choice. If this checkout has a .deployment-role file, it is one of the
# maintainers' own dev/production checkouts and this script refuses to run --
# use dev_stack.sh or promote.sh there instead.
#
# WHAT IT DOES, IN ORDER
#   1. refuses if this looks like one of the maintainers' own dev/production
#      checkouts, or the tree is dirty
#   2. fetches origin
#   3. reports what the change will do to the running deployment, and refuses
#      to continue past anything destructive without an explicit decision
#   4. takes a FULL backup (database + all of data/)
#   5. optionally drains jobs, by stopping admission and waiting
#   6. fast-forwards to the target commit, rebuilds the frontend and image,
#      brings the stack up
#   7. waits for health, restores job admission, records what it did
#
# Usage:
#     scripts/update.sh                    # update to origin/main
#     scripts/update.sh <ref>              # update to a specific commit or tag
#     scripts/update.sh --dry-run          # run every gate, change nothing
#     scripts/update.sh --drain            # wait for running jobs to finish
#     scripts/update.sh --force            # accept killing in-flight jobs
#     scripts/update.sh --yes              # accept the destructive report
#     scripts/update.sh --rollback         # go back to the previous commit
set -euo pipefail

RED=$'\033[31m'; GRN=$'\033[32m'; YEL=$'\033[33m'; DIM=$'\033[2m'; RST=$'\033[0m'

SELF_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SELF_DIR/.." && pwd)"
cd "$REPO_ROOT"

die()  { echo "${RED}update: $*${RST}" >&2; exit 1; }
ok()   { echo "${GRN}  ok${RST}  $*"; }
info() { echo "${DIM}  ..${RST}  $*"; }
warn() { echo "${YEL}  !!${RST}  $*"; }
step() { echo; echo "${DIM}--- $* ---------------------------------------${RST}"; }

ROLE_FILE=".deployment-role"
UPDATE_LOG=".update-log"

TARGET_REF=""
DRY_RUN=0; ASSUME_YES=0; DRAIN=0; FORCE=0; ROLLBACK=0
DRAIN_TIMEOUT="${QC_AGENT_DRAIN_TIMEOUT:-14400}"   # 4h: a CASSCF run is not an outlier here

while [ $# -gt 0 ]; do
    case "$1" in
        --dry-run)  DRY_RUN=1; shift ;;
        --yes|-y)   ASSUME_YES=1; shift ;;
        --drain)    DRAIN=1; shift ;;
        --force)    FORCE=1; shift ;;
        --rollback) ROLLBACK=1; shift ;;
        -h|--help)  sed -n '2,45p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'; exit 0 ;;
        -*)         die "unknown option: $1" ;;
        *)          [ -z "$TARGET_REF" ] || die "more than one ref given"; TARGET_REF="$1"; shift ;;
    esac
done

[ "$DRAIN" -eq 1 ] && [ "$FORCE" -eq 1 ] && die "--drain and --force contradict each other."

envget() {
    local file="$1" key="$2"
    [ -f "$file" ] || return 0
    sed -nE "s/^[[:space:]]*${key}=(.*)$/\1/p" "$file" | tail -n1 | sed -E 's/^"(.*)"$/\1/'
}

step "checking this is a standalone deployment"

if [ -f "$ROLE_FILE" ]; then
    die "this checkout has a ${ROLE_FILE} file (\"$(tr -d '[:space:]' < "$ROLE_FILE")\").
  That marks it as one of the maintainers' own dev/production checkouts, which
  have their own dedicated update path: scripts/dev_stack.sh (dev) or
  scripts/promote.sh (production). scripts/update.sh is for a standalone
  deployment created by scripts/install.sh, with no second checkout to verify
  against."
fi
ok "no ${ROLE_FILE} here -- standalone deployment"

[ -z "$(git status --porcelain)" ] || die "this checkout has local modifications:
$(git status --short | sed 's/^/    /')
  An update needs a clean, identifiable commit -- otherwise a rollback has
  nothing to return to. Commit or discard these first."
ok "clean tree"

[ -f .env ] || die "no .env -- run scripts/install.sh first, or see docs/DEPLOYMENT.md."

COMPOSE=(docker compose -f docker-compose.yml)
if [ -f docker-compose.override.yml ]; then
    COMPOSE+=(-f docker-compose.override.yml)
else
    warn "no docker-compose.override.yml: ORCA and BAGEL will NOT be mounted."
    warn "If this deployment is supposed to run them, stop and restore it first."
fi

PGUSER_VAL="$(envget .env QC_AGENT_POSTGRES_USER)"; PGUSER_VAL="${PGUSER_VAL:-qc_agent}"
PGDB_VAL="$(envget .env QC_AGENT_POSTGRES_DB)";     PGDB_VAL="${PGDB_VAL:-qc_agent}"
BASE_URL="${QC_AGENT_UPDATE_HEALTH_URL:-https://127.0.0.1:8443}"

CURRENT_SHA="$(git rev-parse HEAD)"

step "resolving what to update to"

if [ "$ROLLBACK" -eq 1 ]; then
    [ -z "$TARGET_REF" ] || die "--rollback takes no ref."
    [ -f "$UPDATE_LOG" ] || die "no ${UPDATE_LOG} -- nothing to roll back to.
  This file is written by this script on every successful update; without it
  there is no record of what was deployed before."
    PREV="$(awk '$1=="updated"{print $4}' "$UPDATE_LOG" | tail -n1)"
    [ -n "$PREV" ] || die "${UPDATE_LOG} has no previous commit recorded."
    TARGET_SHA="$(git rev-parse --verify --quiet "${PREV}^{commit}" || true)"
    [ -n "$TARGET_SHA" ] || die "the previous commit ${PREV} is not in this checkout's object store."
    warn "rolling back to ${TARGET_SHA:0:12} -- code only."
    warn "Database columns added by the update you are undoing STAY. The schema"
    warn "is forward-only and idempotent; the pre-update backup is the only way"
    warn "to undo it, and restoring it also rewinds every account, session and"
    warn "conversation created since. Almost never what you want -- see"
    warn "scripts/restore.sh if you really mean to go that far."
else
    info "fetching origin"
    git fetch --quiet --tags origin || die "git fetch failed."
    TARGET_REF="${TARGET_REF:-origin/main}"
    TARGET_SHA="$(git rev-parse --verify --quiet "${TARGET_REF}^{commit}" || true)"
    [ -n "$TARGET_SHA" ] || die "cannot resolve ref: ${TARGET_REF}"
fi

echo "  currently running: ${CURRENT_SHA:0:12}  $(git log -1 --format=%s "$CURRENT_SHA" 2>/dev/null || echo '(unknown)')"
echo "  updating to:        ${TARGET_SHA:0:12}  $(git log -1 --format=%s "$TARGET_SHA")"

if [ "$CURRENT_SHA" = "$TARGET_SHA" ]; then
    ok "already up to date -- nothing to do."
    exit 0
fi

if [ "$ROLLBACK" -eq 0 ]; then
    git merge-base --is-ancestor "$CURRENT_SHA" "$TARGET_SHA" \
        || die "the current commit is not an ancestor of ${TARGET_REF} -- this is not a
  straightforward fast-forward (local history has diverged from the release
  stream). Resolve that by hand before re-running -- an update script should
  not guess how to reconcile diverged history."
fi

# --- the destructive-change report ----------------------------------------
step "what this will do to the running deployment"

set +e
bash scripts/check_destructive.sh --from "$CURRENT_SHA" --to "$TARGET_SHA" --stack-dir "$REPO_ROOT"
IMPACT_RC=$?
set -e

if [ "$IMPACT_RC" -eq 2 ]; then
    die "the impact report could not run. Not updating blind."
fi

if [ "$IMPACT_RC" -eq 1 ]; then
    if [ "$DRY_RUN" -eq 1 ]; then
        warn "destructive changes found (see above). This is a dry run; stopping here."
        exit 1
    fi
    if [ "$ASSUME_YES" -eq 0 ]; then
        echo "${RED}The report above found changes that lose work or fail silently.${RST}"
        echo "Read it, then decide. Nothing has been changed yet."
        echo
        printf 'Type UPDATE to go ahead anyway: '
        read -r reply
        [ "$reply" = "UPDATE" ] || die "aborted -- nothing was touched."
    else
        warn "destructive changes accepted via --yes"
    fi
fi

# Same allow-list promote.sh uses: does anything in this change affect what
# is actually RUNNING, or is it documentation the operator can pull in
# without disturbing in-flight jobs?
RUNTIME_IRRELEVANT_RE='^(docs/|CHANGELOG\.md$|README\.md$|NOTICE\.md$|CLAUDE\.md$|LICENSE$|CITATION\.cff$|\.gitignore$)'
CHANGED_FILES="$(git diff --name-only "$CURRENT_SHA" "$TARGET_SHA")"
NEEDS_RESTART=1
if [ -n "$CHANGED_FILES" ] && ! printf '%s\n' "$CHANGED_FILES" | grep -qvE "$RUNTIME_IRRELEVANT_RE"; then
    NEEDS_RESTART=0
    ok "documentation-only change: the running containers will be left alone"
fi

count_inflight() {
    [ -d data/jobs ] || { echo 0; return; }
    python3 - data/jobs <<'PY'
import json, os, sys
root = sys.argv[1]
n = 0
for name in os.listdir(root):
    p = os.path.join(root, name, "status.json")
    if not os.path.isfile(p):
        continue
    try:
        with open(p) as fh:
            if json.load(fh).get("status") in ("running", "pending"):
                n += 1
    except Exception:
        pass
print(n)
PY
}

INFLIGHT="$(count_inflight)"
if [ "$INFLIGHT" -gt 0 ] && [ "$NEEDS_RESTART" -eq 0 ]; then
    ok "${INFLIGHT} job(s) in flight, and they are safe: nothing will be restarted"
elif [ "$INFLIGHT" -gt 0 ] && [ "$DRAIN" -eq 0 ] && [ "$FORCE" -eq 0 ]; then
    die "${INFLIGHT} job(s) are running or pending, and they will be killed.
  Choose explicitly:
      --drain   stop admitting new jobs, wait for these to finish, then update
                (up to ${DRAIN_TIMEOUT}s; a CASSCF run taking hours is normal here)
      --force   update now and accept losing them
  Nothing has been changed."
fi

if [ "$DRY_RUN" -eq 1 ]; then
    echo
    ok "dry run: every gate passed. Re-run without --dry-run to update."
    exit 0
fi

# --- from here on the deployment is being changed --------------------------
step "backing up before changing anything (full: database + all of data/)"
if bash scripts/backup.sh --full; then
    ok "full backup taken"
else
    die "backup failed -- refusing to update without one.
  This is the only thing that can undo a schema change or a lost job."
fi

psql_stack() { "${COMPOSE[@]}" exec -T postgres psql -At -U "$PGUSER_VAL" -d "$PGDB_VAL" "$@"; }

DRAINED=0
PRIOR_CAP=""
restore_admission() {
    [ "$DRAINED" -eq 1 ] || return 0
    if [ -n "$PRIOR_CAP" ]; then
        psql_stack -c "UPDATE app_config SET value='${PRIOR_CAP}'::jsonb, updated_at=now() WHERE key='max_concurrent_jobs_total'" >/dev/null 2>&1 || true
    else
        psql_stack -c "DELETE FROM app_config WHERE key='max_concurrent_jobs_total'" >/dev/null 2>&1 || true
    fi
    DRAINED=0
    ok "job admission restored"
}
trap 'restore_admission' EXIT

if [ "$DRAIN" -eq 1 ] && [ "$INFLIGHT" -gt 0 ] && [ "$NEEDS_RESTART" -eq 1 ]; then
    step "draining"
    PRIOR_CAP="$(psql_stack -c "SELECT value FROM app_config WHERE key='max_concurrent_jobs_total'" 2>/dev/null | tail -n1 || true)"
    psql_stack -c "INSERT INTO app_config (key, value) VALUES ('max_concurrent_jobs_total', '0'::jsonb)
                   ON CONFLICT (key) DO UPDATE SET value='0'::jsonb, updated_at=now()" >/dev/null \
        || die "could not stop job admission -- not draining blind."
    DRAINED=1
    ok "new jobs are no longer admitted (they queue as pending)"
    info "waiting for ${INFLIGHT} in-flight job(s); Ctrl-C is safe, admission is restored on exit"
    WAITED=0
    while [ "$WAITED" -lt "$DRAIN_TIMEOUT" ]; do
        RUNNING="$(python3 - data/jobs <<'PY'
import json, os, sys
root = sys.argv[1]
n = 0
for name in (os.listdir(root) if os.path.isdir(root) else []):
    p = os.path.join(root, name, "status.json")
    if not os.path.isfile(p):
        continue
    try:
        with open(p) as fh:
            if json.load(fh).get("status") == "running":
                n += 1
    except Exception:
        pass
print(n)
PY
)"
        [ "$RUNNING" -eq 0 ] && break
        printf '\r  .. %s job(s) still running, waited %ss   ' "$RUNNING" "$WAITED"
        sleep 30
        WAITED=$((WAITED + 30))
    done
    echo
    if [ "${RUNNING:-0}" -ne 0 ]; then
        restore_admission
        die "still ${RUNNING} job(s) running after ${DRAIN_TIMEOUT}s. Admission restored;
  nothing was updated. Wait longer (QC_AGENT_DRAIN_TIMEOUT=<seconds>), or use
  --force if you have decided to lose them."
    fi
    ok "drained"
fi

step "moving the checkout to ${TARGET_SHA:0:12}"
CURRENT_BRANCH="$(git rev-parse --abbrev-ref HEAD)"
if [ "$CURRENT_BRANCH" = "HEAD" ]; then
    git checkout --detach --quiet "$TARGET_SHA"
else
    git merge --ff-only --quiet "$TARGET_SHA"
fi
ok "checked out $(git rev-parse --short HEAD)"

if [ "$NEEDS_RESTART" -eq 0 ]; then
    step "not restarting anything"
    ok "this change touches only documentation, so the running stack is already correct"
    restore_admission
    trap - EXIT
    printf 'updated %s %s %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$TARGET_SHA" "$CURRENT_SHA" >> "$UPDATE_LOG"
    echo
    echo "${GRN}updated${RST} ${CURRENT_SHA:0:12} -> ${TARGET_SHA:0:12} (documentation only, no restart)"
    echo "  recorded in ${UPDATE_LOG}; roll back with: scripts/update.sh --rollback"
    exit 0
fi

step "rebuilding"
if command -v npm >/dev/null 2>&1; then
    (cd frontend && npm ci --silent && npm run build)
    ok "frontend/dist rebuilt"
else
    warn "npm is not on PATH, so frontend/dist was NOT rebuilt."
    warn "nginx serves it from a bind mount, so you will keep seeing the OLD"
    warn "frontend against the NEW api. Install Node and run:"
    warn "    (cd frontend && npm ci && npm run build)"
fi

"${COMPOSE[@]}" up -d --build || die "compose up failed. The stack may be partly down --
  check: ${COMPOSE[*]} ps    and consider: scripts/update.sh --rollback"

step "verifying"
HEALTHY=0
for _ in $(seq 60); do
    if curl -fsS -k --max-time 5 "${BASE_URL}/api/health" >/dev/null 2>&1; then HEALTHY=1; break; fi
    sleep 5
done
if [ "$HEALTHY" -eq 1 ]; then
    ok "healthy at ${BASE_URL}"
else
    warn "not healthy after 300s."
    warn "Check ${COMPOSE[*]} logs api -- and note the api healthcheck allows a"
    warn "90s start_period, so a slow first import is not automatically a failure."
    warn "If it is genuinely broken: scripts/update.sh --rollback"
fi

restore_admission
trap - EXIT

printf 'updated %s %s %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$TARGET_SHA" "$CURRENT_SHA" >> "$UPDATE_LOG"

echo
if [ "$HEALTHY" -eq 1 ]; then
    echo "${GRN}updated${RST} ${CURRENT_SHA:0:12} -> ${TARGET_SHA:0:12}"
else
    echo "${YEL}updated with a failing health check${RST} ${CURRENT_SHA:0:12} -> ${TARGET_SHA:0:12}"
fi
echo "  recorded in ${UPDATE_LOG}; roll back with: scripts/update.sh --rollback"
echo "  hard-reload your browser tab if the frontend changed."
