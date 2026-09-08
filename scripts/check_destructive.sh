#!/usr/bin/env bash
# What updating a given deployment to a given commit would do, reported
# BEFORE anything is touched.
#
# WHY THIS EXISTS
# ---------------
# Most of what this project deploys is safe to replace: new Python, new frontend
# assets, new prompts. A handful of changes are not, and they share a property
# that makes them dangerous rather than merely inconvenient -- they FAIL
# SILENTLY, or they destroy something a user cannot get back. Reading a diff does
# not reliably surface them, because the damage is not in the diff; it is in the
# interaction between the diff and the state the running deployment is already
# in.
#
# The four that motivated this script, each of which has a check below:
#
#   1. Restarting the api container kills every running job. Workers are
#      subprocess.Popen children inside that container's PID namespace.
#      start_new_session=True gives them their own process group -- which is
#      about signal delivery, not about surviving container teardown -- so
#      `compose up -d` on a changed image takes them with it. In this project a
#      job that dies is not a retry-and-forget: CASSCF and CASPT2 runs here take
#      tens of minutes to hours (CLAUDE.md's standing framing note), so killing
#      one can throw away most of a day's compute that a user is waiting on.
#
#   2. app/auth/db.py's schema is `CREATE TABLE IF NOT EXISTS` with hand-written
#      `ALTER TABLE ... ADD COLUMN IF NOT EXISTS` for anything added later. The
#      module says so itself. That means adding a column to a CREATE TABLE body
#      and nothing else works perfectly on a fresh database and is a SILENT
#      NO-OP against the deployed one -- the column never appears, and the
#      failure surfaces later as a query error in whatever route uses it.
#
#   3. docker-compose.yml uses `${VAR:?}` for values with no safe default. A
#      commit that introduces a new one turns the next `compose up` into a hard
#      failure, at the point where the old containers are already gone.
#
#   4. docker-compose.override.yml is untracked, host-specific, and the only
#      thing that bind-mounts the licensed engines. A deployment can be running
#      happily with ORCA and BAGEL mounted while the file that mounts them no
#      longer exists on disk -- the container keeps the mounts it was created
#      with. The next recreate quietly produces a PySCF-only stack. This has
#      actually happened on this host, which is why it is checked rather than
#      assumed.
#
# Verdicts:
#   [destructive]  will lose data/work, or will fail in a way that leaves the
#                  deployment down or subtly wrong. update.sh refuses unless the
#                  operator explicitly accepts it.
#   [warn]         a real consequence worth knowing about (an outage window, a
#                  forced reload for open browser tabs). Does not block.
#   [ok]           checked, nothing found.
#
# Usage:
#     scripts/check_destructive.sh                       # HEAD -> origin/main
#     scripts/check_destructive.sh --to <ref>            # HEAD -> <ref>
#     scripts/check_destructive.sh --from <ref> --to <ref>
#     scripts/check_destructive.sh --no-live             # diff checks only
#     scripts/check_destructive.sh --stack-dir <path>    # deployment to inspect
#
# Exit status: 0 = nothing destructive found, 1 = at least one [destructive],
# 2 = could not run the checks (bad arguments, unresolvable ref). Note that 1
# does not mean "do not deploy" -- it means "do not deploy without deciding".
set -euo pipefail

RED=$'\033[31m'; GRN=$'\033[32m'; YEL=$'\033[33m'; DIM=$'\033[2m'; RST=$'\033[0m'

SELF_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SELF_DIR/.." && pwd)"

FROM=""
TO=""
STACK_DIR="$REPO_ROOT"
LIVE=1

while [ $# -gt 0 ]; do
    case "$1" in
        --from)      FROM="${2:?--from needs a ref}"; shift 2 ;;
        --to)        TO="${2:?--to needs a ref}"; shift 2 ;;
        --stack-dir) STACK_DIR="${2:?--stack-dir needs a path}"; shift 2 ;;
        --no-live)   LIVE=0; shift ;;
        -h|--help)   sed -n '2,60p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'; exit 0 ;;
        *)           echo "check_destructive: unknown argument: $1" >&2; exit 2 ;;
    esac
done

cd "$REPO_ROOT"

FROM="${FROM:-HEAD}"
TO="${TO:-origin/main}"

FROM_SHA="$(git rev-parse --verify --quiet "${FROM}^{commit}" || true)"
TO_SHA="$(git rev-parse --verify --quiet "${TO}^{commit}" || true)"
[ -n "$FROM_SHA" ] || { echo "${RED}check_destructive: cannot resolve --from ref: $FROM${RST}" >&2; exit 2; }
[ -n "$TO_SHA" ]   || { echo "${RED}check_destructive: cannot resolve --to ref: $TO${RST}" >&2; exit 2; }

DESTRUCTIVE=0
WARNINGS=0

# Detail arguments are frequently multi-line -- a $(...) that lists several
# offending files, say -- so indent every LINE rather than every argument.
# Indenting per-argument left the second and subsequent lines of such a list
# flush with the margin, where they read as separate findings rather than as
# part of the one above them.
detail() { for l in "$@"; do printf '%s\n' "$l" | sed 's/^/               /'; done; }
dest() { DESTRUCTIVE=$((DESTRUCTIVE + 1)); echo "${RED}[destructive]${RST} $1"; shift; detail "$@"; }
warn() { WARNINGS=$((WARNINGS + 1));      echo "${YEL}[warn]${RST}        $1"; shift; detail "$@"; }
ok()   { echo "${GRN}[ok]${RST}          $1"; }
skip() { echo "${DIM}[skipped]${RST}     $1"; }

# Read one key out of a .env-style file without sourcing it. Sourcing would
# execute whatever is in there, and this script is run by an operator who is
# about to trust its output -- it should not also be running the file's content.
envget() {
    local file="$1" key="$2"
    [ -f "$file" ] || return 0
    sed -nE "s/^[[:space:]]*${key}=(.*)$/\1/p" "$file" | tail -n1 | sed -E 's/^"(.*)"$/\1/; s/^'"'"'(.*)'"'"'$/\1/'
}

echo
echo "Update impact report"
echo "  from  ${FROM}  $(git log -1 --format='%h %s' "$FROM_SHA")"
echo "  to    ${TO}  $(git log -1 --format='%h %s' "$TO_SHA")"
echo "  stack ${STACK_DIR}"
echo

if [ "$FROM_SHA" = "$TO_SHA" ]; then
    ok "nothing to update -- the deployment is already at this commit"
    echo
    echo "${GRN}no destructive changes${RST} (0 warnings)"
    exit 0
fi

CHANGED="$(git diff --name-only "$FROM_SHA" "$TO_SHA")"
DELETED="$(git diff --diff-filter=D --name-only "$FROM_SHA" "$TO_SHA")"

changed_any() { printf '%s\n' "$CHANGED" | grep -qE "$1"; }

echo "--- changes between the two commits ------------------------------------"

# The dependency lines of a requirements file at one commit, as
# "name<TAB>specifier" pairs: comments and blank lines dropped, the package
# name lower-cased and its extras/underscores normalised so `pyscf_forge`,
# `pyscf-forge` and `pyscf-forge[extra]` are recognised as the same package
# across a rename of spelling. Anything after a `#` on a line goes too, so a
# trailing comment cannot read as part of a version specifier.
req_pairs() {
    git show "$1:requirements.txt" 2>/dev/null \
    | sed 's/#.*//' \
    | sed 's/[[:space:]]*$//' \
    | grep -vE '^[[:space:]]*$' \
    | awk '{
        line = $0
        sub(/^[[:space:]]+/, "", line)
        # Split the package name off whatever specifier follows it.
        name = line; spec = ""
        if (match(line, /[<>=!~[]/)) {
            name = substr(line, 1, RSTART - 1)
            spec = substr(line, RSTART)
        }
        sub(/\[.*/, "", name)
        gsub(/_/, "-", name)
        print tolower(name) "\t" spec
      }' \
    | sort -u
}

# 1. Image rebuild. Not destructive in itself; it lengthens the window in which
#    the api container is down, which is the window that matters for check 8.
#
#    Reporting WHICH dependencies moved, not merely that the file did. The
#    reason is a real failure: an unpinned pyscf-forge resolved to a version
#    with no wheel, pip compiled it, and the build died on a missing BLAS
#    several minutes in. "requirements.txt changed" would not have let anyone
#    predict that; "pyscf-forge (unpinned)" or "pyscf 2.14.0 -> 2.15.0" does.
if changed_any '^(Dockerfile|requirements\.txt)$'; then
    DEP_LINES=""
    if changed_any '^requirements\.txt$'; then
        REQ_FROM="$(req_pairs "$FROM_SHA")"
        REQ_TO="$(req_pairs "$TO_SHA")"
        if [ "$REQ_FROM" = "$REQ_TO" ]; then
            DEP_LINES="  no dependency lines changed -- comments only, so the rebuild
  reinstalls exactly the same versions"
        else
            NAMES_FROM="$(printf '%s\n' "$REQ_FROM" | cut -f1)"
            NAMES_TO="$(printf '%s\n' "$REQ_TO" | cut -f1)"
            ADDED_PKGS="$(comm -13 <(printf '%s\n' "$NAMES_FROM") <(printf '%s\n' "$NAMES_TO") || true)"
            REMOVED_PKGS="$(comm -23 <(printf '%s\n' "$NAMES_FROM") <(printf '%s\n' "$NAMES_TO") || true)"
            DEP_LINES="  dependency changes:"
            for n in $REMOVED_PKGS; do
                DEP_LINES="${DEP_LINES}
    - ${n}  (removed)"
            done
            for n in $ADDED_PKGS; do
                sp="$(printf '%s\n' "$REQ_TO" | awk -F'\t' -v k="$n" '$1==k{print $2}')"
                if [ -n "$sp" ]; then
                    DEP_LINES="${DEP_LINES}
    + ${n}${sp}  (new)"
                else
                    DEP_LINES="${DEP_LINES}
    + ${n}  (new, UNPINNED -- resolves to whatever is latest at build time)"
                fi
            done
            # Same package, different specifier.
            for n in $(printf '%s\n' "$NAMES_TO"); do
                printf '%s\n' "$NAMES_FROM" | grep -qxF "$n" || continue
                a="$(printf '%s\n' "$REQ_FROM" | awk -F'\t' -v k="$n" '$1==k{print $2}')"
                b="$(printf '%s\n' "$REQ_TO"   | awk -F'\t' -v k="$n" '$1==k{print $2}')"
                [ "$a" = "$b" ] && continue
                DEP_LINES="${DEP_LINES}
    ~ ${n}  ${a:-unpinned} -> ${b:-unpinned}"
            done
            # A new package is where a missing SYSTEM dependency shows up, and
            # it shows up as a build failure rather than as anything this
            # script can see in advance. Worth saying so next to the list.
            if [ -n "$ADDED_PKGS" ]; then
                DEP_LINES="${DEP_LINES}

  A new dependency may need a system package the Dockerfile does not install
  (a source-only wheel needing a compiler, BLAS, or headers). That surfaces as
  a failed build, which happens BEFORE the running stack is touched -- so the
  deployment stays up and the fix is an apt line in the Dockerfile."
            fi
        fi
    fi
    # $DEP_LINES is omitted rather than passed empty when only the Dockerfile
    # moved, so the report does not end on a blank detail line.
    REBUILD_DETAIL=(
        "The outage is a build, not a restart: minutes rather than seconds,"
        "and pip may reach the network. Build BEFORE stopping the old stack."
        "$(printf '%s\n' "$CHANGED" | grep -E '^(Dockerfile|requirements\.txt)$' | sed 's/^/  /')"
    )
    [ -n "$DEP_LINES" ] && REBUILD_DETAIL+=("$DEP_LINES")
    warn "the api image must be rebuilt (Dockerfile or requirements.txt changed)" \
         "${REBUILD_DETAIL[@]}"
else
    ok "no image rebuild needed"
fi

# 2. New REQUIRED compose variables. `${VAR:?}` aborts `compose up`, and it
#    aborts it after the old containers have already been removed.
NEW_REQUIRED=""
for f in docker-compose.yml; do
    git cat-file -e "${TO_SHA}:${f}" 2>/dev/null || continue
    TO_VARS="$(git show "${TO_SHA}:${f}" | grep -oE '\$\{[A-Za-z_][A-Za-z0-9_]*:\?' | tr -d '${:?' | sort -u)"
    FROM_VARS="$(git show "${FROM_SHA}:${f}" 2>/dev/null | grep -oE '\$\{[A-Za-z_][A-Za-z0-9_]*:\?' | tr -d '${:?' | sort -u || true)"
    ADDED="$(comm -13 <(printf '%s\n' "$FROM_VARS") <(printf '%s\n' "$TO_VARS") || true)"
    [ -n "$ADDED" ] && NEW_REQUIRED="${NEW_REQUIRED}${ADDED}"$'\n'
done
NEW_REQUIRED="$(printf '%s\n' "$NEW_REQUIRED" | grep -v '^$' | sort -u || true)"

if [ -n "$NEW_REQUIRED" ]; then
    MISSING=""
    while read -r v; do
        [ -z "$v" ] && continue
        if [ -z "$(envget "${STACK_DIR}/.env" "$v")" ]; then
            MISSING="${MISSING}${v}"$'\n'
        fi
    done <<< "$NEW_REQUIRED"
    MISSING="$(printf '%s\n' "$MISSING" | grep -v '^$' || true)"
    if [ -n "$MISSING" ]; then
        dest "new required configuration is missing from this deployment's .env" \
             "compose substitutes \${VAR:?} at up-time and aborts if unset -- after" \
             "the old containers are gone. Add these to ${STACK_DIR}/.env first:" \
             "$(printf '%s\n' "$MISSING" | sed 's/^/  /')"
    else
        ok "new required configuration is already present in .env"
    fi
else
    ok "no new required configuration variables"
fi

# 3. Schema. Two separate questions: did the author remember the ALTER, and does
#    the deployed database actually have every column the new code expects.
schema_cols() {  # <ref> -> lines "C table.col" / "A table.col"
    git show "${1}:app/auth/db.py" 2>/dev/null | python3 -c '
import re, sys
src = sys.stdin.read()
m = re.search(r"_SCHEMA\s*=\s*\"\"\"(.*?)\"\"\"", src, re.S)
if not m:
    sys.exit(3)
sql = re.sub(r"--[^\n]*", "", m.group(1))
out = []
for tm in re.finditer(r"CREATE\s+TABLE\s+IF\s+NOT\s+EXISTS\s+(\w+)\s*\((.*?)\n\)\s*;", sql, re.S | re.I):
    table, body, depth, cur, parts = tm.group(1), tm.group(2), 0, "", []
    for ch in body:
        if ch == "," and depth == 0:
            parts.append(cur); cur = ""
            continue
        if ch == "(": depth += 1
        elif ch == ")": depth -= 1
        cur += ch
    parts.append(cur)
    for p in parts:
        p = p.strip()
        if not p:
            continue
        head = p.split()[0]
        if head.upper() in ("PRIMARY", "FOREIGN", "UNIQUE", "CHECK", "CONSTRAINT", "EXCLUDE", "LIKE"):
            continue
        out.append("C %s.%s" % (table, head))
for am in re.finditer(r"ALTER\s+TABLE\s+(\w+)\s+ADD\s+COLUMN\s+IF\s+NOT\s+EXISTS\s+(\w+)", sql, re.I):
    out.append("A %s.%s" % (am.group(1), am.group(2)))
print("\n".join(sorted(set(out))))
'
}

if changed_any '^app/auth/db\.py$'; then
    if TO_SCHEMA="$(schema_cols "$TO_SHA")" && FROM_SCHEMA="$(schema_cols "$FROM_SHA")"; then
        TO_ALL="$(printf '%s\n' "$TO_SCHEMA"   | awk '{print $2}' | sort -u)"
        FROM_ALL="$(printf '%s\n' "$FROM_SCHEMA" | awk '{print $2}' | sort -u)"
        TO_ALTERED="$(printf '%s\n' "$TO_SCHEMA" | awk '$1=="A"{print $2}' | sort -u)"
        ADDED_COLS="$(comm -13 <(printf '%s\n' "$FROM_ALL") <(printf '%s\n' "$TO_ALL") || true)"
        # Only a column added to a table that ALREADY EXISTED at FROM needs
        # its own ALTER TABLE -- CREATE TABLE IF NOT EXISTS is a no-op only
        # once the table exists; for a table that is itself new in this
        # diff, that same statement creates it, every column included, on
        # an old database exactly as it does on a fresh install. Confirmed
        # empirically (not just reasoned about) against a real dev-stack
        # Postgres: dropping a whole new table and forcing a fresh
        # connection pool recreated it correctly via CREATE TABLE IF NOT
        # EXISTS alone. Excluding those columns here is the fix for a real
        # false positive this script raised at the Phase 3 gate (see
        # docs/trackers/2026-08-job-system-overhaul.md's Phase 4 entry) -- flagging bug_report_attachments'
        # seven columns as unmigrated even though the whole table (added in
        # 885abfb) needs no ALTER at all.
        FROM_TABLES="$(printf '%s\n' "$FROM_SCHEMA" | awk '$1=="C"{split($2,a,"."); print a[1]}' | sort -u)"
        ADDED_COLS_ON_EXISTING_TABLES="$(printf '%s\n' "$ADDED_COLS" | grep -v '^$' | while read -r col; do
            tbl="${col%%.*}"
            if printf '%s\n' "$FROM_TABLES" | grep -qx "$tbl"; then
                printf '%s\n' "$col"
            fi
        done || true)"
        UNMIGRATED="$(comm -23 <(printf '%s\n' "$ADDED_COLS_ON_EXISTING_TABLES" | grep -v '^$' || true) \
                               <(printf '%s\n' "$TO_ALTERED") || true)"
        if [ -n "$(printf '%s\n' "$UNMIGRATED" | grep -v '^$' || true)" ]; then
            dest "new columns have no ALTER TABLE, so the deployed database will not get them" \
                 "CREATE TABLE IF NOT EXISTS is a no-op where the table exists. These" \
                 "columns will appear on a fresh install and be absent here, and the" \
                 "failure will surface later as a query error, not now:" \
                 "$(printf '%s\n' "$UNMIGRATED" | grep -v '^$' | sed 's/^/  /')" \
                 "Fix by adding a matching ALTER TABLE ... ADD COLUMN IF NOT EXISTS" \
                 "to _SCHEMA in app/auth/db.py."
        else
            ok "schema changes carry matching ALTER TABLE statements"
        fi
        DROPPED_COLS="$(comm -23 <(printf '%s\n' "$FROM_ALL") <(printf '%s\n' "$TO_ALL") || true)"
        if [ -n "$(printf '%s\n' "$DROPPED_COLS" | grep -v '^$' || true)" ]; then
            warn "columns were removed from the schema source" \
                 "Nothing drops them from the deployed database -- they will linger" \
                 "with their data. That is the safe direction, but it means the" \
                 "deployment and a fresh install no longer have the same shape:" \
                 "$(printf '%s\n' "$DROPPED_COLS" | grep -v '^$' | sed 's/^/  /')"
        fi
    else
        warn "could not parse app/auth/db.py's schema at one of the two commits" \
             "Check the schema by hand; this check has not run."
    fi
else
    ok "no schema source changes"
fi

# 4. The deployed frontend and what is already in people's browsers.
if changed_any '^frontend/'; then
    ROUTES_FROM="$(git grep -h -E '@(app|router)\.(get|post|put|patch|delete)\(' "$FROM_SHA" -- server 2>/dev/null | sed -E 's/.*\("([^"]*)".*/\1/' | sort -u || true)"
    ROUTES_TO="$(git grep -h -E '@(app|router)\.(get|post|put|patch|delete)\(' "$TO_SHA" -- server 2>/dev/null | sed -E 's/.*\("([^"]*)".*/\1/' | sort -u || true)"
    GONE="$(comm -23 <(printf '%s\n' "$ROUTES_FROM") <(printf '%s\n' "$ROUTES_TO") || true)"
    if [ -n "$(printf '%s\n' "$GONE" | grep -v '^$' || true)" ]; then
        dest "API routes disappear while old frontend assets are still in browsers" \
             "A tab open across the update keeps its already-loaded JS and will" \
             "call these until it is reloaded. Removed or renamed:" \
             "$(printf '%s\n' "$GONE" | grep -v '^$' | sed 's/^/  /')" \
             "Users must hard-reload. Say so when you announce the update."
    else
        warn "the frontend changed and must be reinstalled on the host" \
             "nginx serves frontend/dist through a bind mount, so \`docker compose" \
             "build\` does NOT refresh it -- scripts/extract_frontend.sh does," \
             "and both install.sh and update.sh call it after building." \
             "Open tabs keep the old bundle until reloaded; no route was removed," \
             "so they keep working in the meantime."
    fi
else
    ok "no frontend changes"
fi

# 5. Anything that changes how the deployment is reachable, or who may reach it.
if changed_any '^nginx/'; then
    warn "the nginx configuration changed -- reachability or TLS may change" \
         "Re-read the CIDR allowlist and the bind addresses before updating;" \
         "this is the layer that decides who can see the deployment at all." \
         "$(printf '%s\n' "$CHANGED" | grep -E '^nginx/' | sed 's/^/  /')"
fi
if changed_any '^docker-compose\.yml$'; then
    warn "docker-compose.yml changed -- containers will be recreated, not restarted" \
         "Recreation is what makes check 8 below matter. Diff the ports and" \
         "volumes sections specifically."
fi

# 6. On-disk layout. There is no migration path for data/ at all: these modules
#    define where job artifacts, the thread registry and the vector store live,
#    and a rename here orphans everything already written under the old name.
LAYOUT_RE='^app/chemistry/jobs/(base|storage)\.py$|^app/(kb|rag)/|^app/chemistry/kb/'
if changed_any "$LAYOUT_RE"; then
    warn "modules that define on-disk layout under data/ changed" \
         "data/ has no migration mechanism. If a path or filename changed," \
         "existing jobs, threads or the vector store are orphaned rather than" \
         "upgraded -- and orphaned job artifacts with no ownership row are" \
         "readable by everyone (app/auth/ownership.py's unowned-means-shared" \
         "policy). Read the diff before updating:" \
         "$(printf '%s\n' "$CHANGED" | grep -E "$LAYOUT_RE" | sed 's/^/  /')"
fi
if [ -n "$DELETED" ]; then
    warn "files were deleted between these commits" \
         "$(printf '%s\n' "$DELETED" | sed 's/^/  /')"
fi

# 7. The scripts an operator relies on to recover.
if changed_any '^scripts/(backup|restore|update)\.sh$'; then
    warn "the backup/restore/update tooling itself changed" \
         "Take a backup with the CURRENT script before updating, so the" \
         "recovery path you already trust is the one that produced it."
fi

if [ "$LIVE" -eq 0 ]; then
    echo
    skip "live deployment checks (--no-live)"
else
    echo
    echo "--- the running deployment ---------------------------------------------"

    COMPOSE_RUNNING=0
    if [ -f "${STACK_DIR}/docker-compose.yml" ] \
       && docker compose --project-directory "$STACK_DIR" ps --status running --services 2>/dev/null | grep -q .; then
        COMPOSE_RUNNING=1
    fi

    if [ "$COMPOSE_RUNNING" -eq 0 ]; then
        skip "no running stack at ${STACK_DIR} -- nothing to disturb"
    else
        # 8. THE important one. Anything not in a terminal state dies with the
        #    container, and pending counts: a job admitted during the restart
        #    window is killed just as dead as one that has been running for an
        #    hour. Sub-jobs of ensembles and scans each have their own directory,
        #    so scanning every status.json covers them without special-casing.
        JOBS_DIR="${STACK_DIR}/data/jobs"
        if [ -d "$JOBS_DIR" ]; then
            INFLIGHT="$(python3 - "$JOBS_DIR" <<'PY'
import json, os, sys, time
root = sys.argv[1]
rows = []
for name in sorted(os.listdir(root)):
    p = os.path.join(root, name, "status.json")
    if not os.path.isfile(p):
        continue
    try:
        with open(p) as fh:
            d = json.load(fh)
    except Exception:
        continue
    st = d.get("status")
    if st not in ("running", "pending"):
        continue
    updated = d.get("updated_at") or 0
    try:
        age = max(0.0, time.time() - float(updated)) / 60.0
    except (TypeError, ValueError):
        age = 0.0
    rows.append("%s  %-8s %s  (last update %.0f min ago)"
                % (name, st, (d.get("message") or "")[:48], age))
print("\n".join(rows))
PY
)"
            if [ -n "$INFLIGHT" ]; then
                dest "jobs are in flight and WILL BE KILLED by the restart" \
                     "$(printf '%s\n' "$INFLIGHT" | sed 's/^/  /')" \
                     "Workers live inside the api container's PID namespace, so" \
                     "recreating it takes them with it. A CASSCF/CASPT2 run here can" \
                     "be hours of compute a user is waiting on; there is no resume." \
                     "Use update.sh --drain to stop admitting new jobs and wait for" \
                     "these to finish, or --force to accept killing them."
            else
                ok "no jobs running or pending"
            fi
        else
            skip "no data/jobs directory at ${STACK_DIR}"
        fi

        # 9. What the database actually has, rather than what the source says it
        #    should have. Catches drift from any cause, including a column added
        #    to a CREATE TABLE body several updates ago and never ALTERed in.
        PGUSER_VAL="$(envget "${STACK_DIR}/.env" QC_AGENT_POSTGRES_USER)"; PGUSER_VAL="${PGUSER_VAL:-qc_agent}"
        PGDB_VAL="$(envget "${STACK_DIR}/.env" QC_AGENT_POSTGRES_DB)";     PGDB_VAL="${PGDB_VAL:-qc_agent}"
        if docker compose --project-directory "$STACK_DIR" ps --status running --services 2>/dev/null | grep -qx postgres; then
            ACTUAL="$(docker compose --project-directory "$STACK_DIR" exec -T postgres \
                        psql -At -U "$PGUSER_VAL" -d "$PGDB_VAL" \
                        -c "select table_name||'.'||column_name from information_schema.columns where table_schema='public'" \
                        2>/dev/null | sort -u || true)"
            EXPECTED="$(schema_cols "$TO_SHA" | awk '{print $2}' | sort -u || true)"
            if [ -n "$ACTUAL" ] && [ -n "$EXPECTED" ]; then
                ABSENT="$(comm -23 <(printf '%s\n' "$EXPECTED") <(printf '%s\n' "$ACTUAL") | grep -v '^$' || true)"
                # Split the absentees by whether their TABLE exists at all.
                #
                # A column missing from a table that IS deployed is the
                # dangerous case this check was written for: CREATE TABLE IF
                # NOT EXISTS is a silent no-op against an existing table, so
                # without a matching ALTER the column never appears and the
                # first query touching it fails in production.
                #
                # A column belonging to a table that is not deployed at all is
                # the opposite: CREATE TABLE IF NOT EXISTS creates the whole
                # table, columns included, the next time get_pool() runs the
                # schema. Reporting a brand-new feature table as "destructive"
                # said the update would lose something when it adds something,
                # and every new table would have hit it.
                LIVE_TABLES="$(printf '%s\n' "$ACTUAL" | cut -d. -f1 | sort -u)"
                MISSING_COLS=""; NEW_TABLE_COLS=""
                while IFS= read -r qualified; do
                    [ -n "$qualified" ] || continue
                    if printf '%s\n' "$LIVE_TABLES" | grep -qx "${qualified%%.*}"; then
                        MISSING_COLS="${MISSING_COLS}${qualified}\n"
                    else
                        NEW_TABLE_COLS="${NEW_TABLE_COLS}${qualified}\n"
                    fi
                done <<< "$ABSENT"
                if [ -n "$MISSING_COLS" ]; then
                    dest "the deployed database is missing columns the new code expects" \
                         "$(printf '%b' "$MISSING_COLS" | grep -v '^$' | sed 's/^/  /')" \
                         "These belong to tables that ARE deployed, so CREATE TABLE IF NOT" \
                         "EXISTS will not add them. get_pool()'s idempotent ALTERs will add" \
                         "any that have one; any that do not need an ALTER written before" \
                         "updating."
                fi
                if [ -n "$NEW_TABLE_COLS" ]; then
                    warn "new tables the update will create" \
                         "$(printf '%b' "$NEW_TABLE_COLS" | grep -v '^$' | cut -d. -f1 | sort -u | sed 's/^/  /')" \
                         "Absent from the deployed database entirely, so the schema block's" \
                         "CREATE TABLE IF NOT EXISTS creates them on the next start. Additive."
                fi
                if [ -z "$MISSING_COLS" ] && [ -z "$NEW_TABLE_COLS" ]; then
                    ok "the deployed database has every column the new code expects"
                fi
            else
                skip "could not compare the live schema (psql or parse returned nothing)"
            fi
        else
            skip "postgres is not running -- live schema not compared"
        fi

        # 10. Mounts the running containers have but the files on disk no longer
        #     grant. See the header: this has happened here.
        API_CID="$(docker compose --project-directory "$STACK_DIR" ps -q api 2>/dev/null | head -n1 || true)"
        if [ -n "$API_CID" ]; then
            LIVE_MOUNTS="$(docker inspect "$API_CID" --format '{{range .Mounts}}{{.Source}}{{"\n"}}{{end}}' 2>/dev/null | grep -v '^$' || true)"
            ENGINE_MOUNTED=0
            printf '%s\n' "$LIVE_MOUNTS" | grep -qvE "^${STACK_DIR}(/|$)" && ENGINE_MOUNTED=1
            if [ "$ENGINE_MOUNTED" -eq 1 ] && [ ! -f "${STACK_DIR}/docker-compose.override.yml" ]; then
                dest "the running api container has bind mounts that no file on disk would recreate" \
                     "$(printf '%s\n' "$LIVE_MOUNTS" | grep -vE "^${STACK_DIR}(/|$)" | sed 's/^/  /')" \
                     "docker-compose.override.yml is absent, and it is the only thing" \
                     "that mounts the licensed engines. The container kept the mounts it" \
                     "was CREATED with; recreating it produces a PySCF-only stack, and" \
                     "every ORCA/BAGEL job then fails at launch. Restore the override" \
                     "file (see docker-compose.override.yml.example and CLAUDE.local.md)" \
                     "before updating."
            elif [ -f "${STACK_DIR}/docker-compose.override.yml" ]; then
                ok "docker-compose.override.yml is present, so engine mounts survive a recreate"
            else
                ok "no host bind mounts beyond the deployment directory itself"
            fi
        fi
    fi
fi

echo
echo "--- what a rollback can and cannot undo --------------------------------"
echo "  Code and frontend assets: fully reversible, update.sh --rollback."
echo "  Database schema:          NOT reversible. The ALTERs are forward-only and"
echo "                            idempotent, so re-checking-out the old commit"
echo "                            leaves every added column in place. The"
echo "                            pre-update backup is the only way back."
echo "  Killed jobs:              not recoverable. There is no resume."
echo

if [ "$DESTRUCTIVE" -gt 0 ]; then
    echo "${RED}${DESTRUCTIVE} destructive change(s)${RST}, ${WARNINGS} warning(s)"
    exit 1
fi
echo "${GRN}no destructive changes${RST} (${WARNINGS} warning(s))"
exit 0
