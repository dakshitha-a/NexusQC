#!/usr/bin/env bash
# Restores a database backup written by scripts/backup.sh.
#
# This exists so that the restore path is a tested, checked-in procedure
# rather than something improvised during an outage. Run it at least once
# against a throwaway target before you need it for real -- an untested
# backup is an assumption, not a backup.
#
# Usage:
#     ./scripts/restore.sh /data/qcuser/nexusqc-backups/20260817-030000
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
# Job artifacts under data/jobs are not in the backup at all (see backup.sh).
# Restoring a database whose ownership_index references jobs that are no
# longer on disk is harmless -- those rows simply point at nothing -- but the
# reverse is not: jobs on disk with no ownership row become unowned, and this
# app treats unowned as readable by everyone. If you restore an OLDER
# database over a NEWER data/ directory, audit for jobs created in the gap.
set -euo pipefail

cd "$(dirname "$0")/.."

SRC="${1:-}"
if [ -z "$SRC" ]; then
    echo "Usage: $0 <backup-directory>" >&2
    echo "Available:" >&2
    ls -1 "${QC_AGENT_BACKUP_DIR:-/data/qcuser/nexusqc-backups}" 2>/dev/null | sed 's/^/  /' >&2
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

PGUSER_VAL="${QC_AGENT_POSTGRES_USER:-qc_agent}"
PGDB_VAL="${QC_AGENT_POSTGRES_DB:-qc_agent}"

cat >&2 <<EOF
About to restore into database '${PGDB_VAL}' as user '${PGUSER_VAL}'.

This DROPS AND REPLACES every table the dump contains -- all current
accounts, ownership records, audit log entries and chat history will be
replaced by the backup's versions. There is no undo.
EOF
printf 'Type the database name (%s) to proceed: ' "$PGDB_VAL" >&2
read -r reply
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
echo "Restoring..."
docker compose exec -T postgres \
    pg_restore -U "$PGUSER_VAL" -d "$PGDB_VAL" --clean --if-exists --no-owner \
    < "$DUMP" || echo "(pg_restore reported errors -- review the output above; DROP-on-missing-object errors are expected)"

echo "Restarting api..."
docker compose up -d api

echo
echo "Restore finished. Verify before telling anyone it worked:"
echo "  docker compose exec -T postgres psql -U ${PGUSER_VAL} -d ${PGDB_VAL} -c 'SELECT count(*) FROM users;'"
echo "  docker compose logs --tail 30 api"
echo "  then log in through the browser."
