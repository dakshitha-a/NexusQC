#!/usr/bin/env bash
# Restores a database backup written by scripts/backup.sh.
#
# This exists so that the restore path is a tested, checked-in procedure
# rather than something improvised during an outage. Run it at least once
# against a throwaway target before you need it for real -- an untested
# backup is an assumption, not a backup.
#
# Usage:
#     ./scripts/restore.sh backups/20260817-030000
#
# No separate flag for a --full backup -- if the chosen directory has a
# full_data.tar.gz (see backup.sh), this script notices and offers to
# restore it, with its own confirmation prompt.
#
# WHAT THIS DOES NOT RESTORE, AND WHY IT MATTERS
# ----------------------------------------------
# Only the database. It does NOT put back .env or the certificates, even
# though backup.sh saves them, because overwriting live secrets is not
# something a restore script should do unprompted -- copy them by hand if
# that is what you need.
#
# The JWT secret in particular must match the one in use when the dump was
# taken, or every session in the restored `sessions` table is unverifiable
# and all users are silently logged out. If you are restoring onto a host
# with a different .env, expect exactly that, and say so to your users
# rather than letting them discover it.
#
# Job artifacts under data/jobs are not in the backup at all UNLESS it was
# taken with `scripts/backup.sh --full`, in which case a full_data.tar.gz
# sits alongside postgres.dump and this script offers to extract it too (with
# its own separate confirmation -- restoring the database and overwriting
# data/ are different amounts of destructive, and a caller who only wants the
# accounts back should not lose today's job results to get them).
#
# Restoring a database whose ownership_index references jobs that are no
# longer on disk is harmless -- those rows simply point at nothing -- but the
# reverse is not: jobs on disk with no ownership row become unowned, and this
# app treats unowned as readable by everyone. If you restore an OLDER
# database over a NEWER data/ directory (or skip restoring a --full archive's
# data/ while still restoring its database), audit for jobs created in the gap.
set -euo pipefail

cd "$(dirname "$0")/.."

SRC="${1:-}"
if [ -z "$SRC" ]; then
    echo "Usage: $0 <backup-directory>" >&2
    echo "Available:" >&2
    ls -1 "${QC_AGENT_BACKUP_DIR:-$(dirname "$0")/../backups}" 2>/dev/null | sed 's/^/  /' >&2
    exit 1
fi

DUMP="${SRC%/}/postgres.dump"
[ -f "$DUMP" ] || { echo "No postgres.dump in ${SRC}" >&2; exit 1; }

if [ -f "${SRC%/}/MANIFEST.txt" ]; then
    echo "Backup manifest:"
    sed 's/^/    /' "${SRC%/}/MANIFEST.txt"
    echo
fi

docker compose ps --status running --services 2>/dev/null | grep -qx postgres || {
    echo "The postgres service is not running. Start it first:" >&2
    echo "    docker compose up -d postgres" >&2
    exit 1
}

# Environment, then the backup's own manifest, then .env, then the default.
# Environment only was R-022's first half: backup.sh reads the same two values
# out of .env when the environment is empty and its comment spells out why
# ("cron and scripts/update.sh ... Neither exports .env"), and this script runs
# in exactly those conditions. On a deployment whose .env sets
# QC_AGENT_POSTGRES_DB=nexusqc, a restore from a plain shell asked the operator
# to type `qc_agent` and then restored into a database of that name.
#
# The manifest comes first among the file sources because it records the
# database this dump was TAKEN from, and restoring a dump into a differently
# named database is the mistake being guarded against.
#
# Values are read rather than sourced, same as backup.sh: .env holds the
# Postgres password and the JWT secret, and a restore script should not
# execute the file it is restoring around.
envget() {
    [ -f ".env" ] || return 0
    sed -nE "s/^[[:space:]]*$1=(.*)$/\1/p" ".env" | tail -n1 | sed -E 's/^"(.*)"$/\1/'
}
manifestget() {
    [ -f "${SRC%/}/MANIFEST.txt" ] || return 0
    sed -nE "s/^$1:[[:space:]]*(.*)$/\1/p" "${SRC%/}/MANIFEST.txt" | tail -n1
}

PGUSER_VAL="${QC_AGENT_POSTGRES_USER:-$(manifestget 'pg user')}"
PGUSER_VAL="${PGUSER_VAL:-$(envget QC_AGENT_POSTGRES_USER)}"
PGUSER_VAL="${PGUSER_VAL:-qc_agent}"
PGDB_VAL="${QC_AGENT_POSTGRES_DB:-$(manifestget 'pg database')}"
PGDB_VAL="${PGDB_VAL:-$(envget QC_AGENT_POSTGRES_DB)}"
PGDB_VAL="${PGDB_VAL:-qc_agent}"

cat >&2 <<EOF
About to restore into database '${PGDB_VAL}' as user '${PGUSER_VAL}'.

This DROPS AND REPLACES every table the dump contains -- all current
accounts, ownership records, audit log entries and chat history will be
replaced by the backup's versions. There is no undo.
EOF
# A bare `read` returns non-zero at end of input, and under `set -e` that ends
# the script mid-question with nothing printed -- during an outage, which is
# the only time this script runs (R-091). `|| true` keeps the question
# answerable and the empty answer then fails the comparison below, which is
# the safe direction.
printf 'Type the database name (%s) to proceed: ' "$PGDB_VAL" >&2
reply=""
read -r reply || { echo >&2; echo "No more input. Aborted -- nothing changed." >&2; exit 1; }
[ "$reply" = "$PGDB_VAL" ] || { echo "Aborted -- nothing changed." >&2; exit 0; }

# Stop the api container first. Restoring underneath a live PostgresSaver
# connection pool means in-flight checkpoint writes racing a table drop, and
# `pg_restore --clean` cannot drop a table another session holds open.
echo "Stopping api so nothing writes during the restore..."
docker compose stop api

# --clean --if-exists matches how the dump was taken. --exit-on-error is
# deliberately NOT set: --clean emits DROP statements for objects that may
# legitimately not exist yet on a fresh database, and those errors are
# expected noise rather than failure. Real failures still surface in the
# output, so read it.
# --clean --if-exists matches how the dump was taken, and --exit-on-error stays
# off for the documented reason: --clean emits DROPs for objects that may
# legitimately not exist yet, and those errors are expected noise.
#
# What is NOT expected noise is pg_restore's own exit status, and swallowing it
# was R-022's second half. Every failure went into one reassuring sentence,
# including "database does not exist", an authentication failure, and a restore
# that aborted half way -- and the script then printed "Restore finished." The
# two halves compose: a wrong database name gives pg_restore a target that is
# not there, the error reads as expected noise, and the operator is told the
# restore worked. During an outage.
#
# So the status is captured and the run stops on a non-zero one. The
# DROP-on-missing-object case does not set it: pg_restore exits 0 with warnings
# for those, and non-zero only when it could not do what it was asked.
echo "Restoring..."
set +e
docker compose exec -T postgres \
    pg_restore -U "$PGUSER_VAL" -d "$PGDB_VAL" --clean --if-exists --no-owner \
    < "$DUMP"
PG_RC=$?
set -e
if [ "$PG_RC" -ne 0 ]; then
    echo >&2
    echo "pg_restore exited ${PG_RC}. The database has NOT been fully restored." >&2
    echo "  Check the output above. The usual causes are a database name that does" >&2
    echo "  not exist on this deployment (this run targeted '${PGDB_VAL}' as user" >&2
    echo "  '${PGUSER_VAL}'), wrong credentials, or a dump taken from a different" >&2
    echo "  deployment. Nothing further has been done; data/ has not been touched." >&2
    exit "$PG_RC"
fi
echo "(any DROP-on-missing-object warnings above are expected -- pg_restore exited 0)"

FULL_ARCHIVE="${SRC%/}/full_data.tar.gz"
if [ -f "$FULL_ARCHIVE" ]; then
    echo
    # Listed from the archive rather than restated. backup.sh's --full set is
    # derived from data/'s actual children now (R-021), so a hard-coded list
    # here would drift the same way that one did.
    echo "This backup also has a FULL data/ archive, holding:"
    tar -tzf "$FULL_ARCHIVE" 2>/dev/null | cut -d/ -f1-2 | sort -u | sed 's/^/  /'
    echo "Extracting it OVERWRITES the current contents of those directories."
    printf 'Type FULL to also restore data/ from this archive, or press enter to skip it: '
    full_reply=""
    read -r full_reply || { echo >&2; echo "No more input; skipping the data/ archive." >&2; full_reply=""; }
    if [ "$full_reply" = "FULL" ]; then
        echo "Extracting full data archive..."
        tar -xzf "$FULL_ARCHIVE" -C "$(pwd)"
        echo "data/ restored from archive."
    else
        echo "Skipped restoring data/ from the archive -- database only."
    fi
fi

echo "Restarting api..."
docker compose up -d api

echo
echo "Restore finished. Verify before telling anyone it worked:"
echo "  docker compose exec -T postgres psql -U ${PGUSER_VAL} -d ${PGDB_VAL} -c 'SELECT count(*) FROM users;'"
echo "  docker compose logs --tail 30 api"
echo "  then log in through the browser."
