#!/usr/bin/env bash
# Advance the production deployment to a commit that has already been verified
# on the development stack.
#
# THE ONE RULE THIS ENFORCES
# --------------------------
# Production only ever moves to a commit that the dev stack has run the standing
# suite against and passed. That claim is not taken on trust: `dev_stack.sh
# verify` writes a row naming the exact sha into docs/deployment-ledger.md, and
# the gate below refuses any commit that has no such row. A commit whose only
# difference from a verified one is documentation is allowed through, and nothing
# else is.
#
# This is the whole point. Without it, "we test on dev first" is a habit, and
# habits lapse exactly when someone is in a hurry to fix something for a user who
# is waiting -- which is the moment production can least afford an untested push.
#
# WHERE THIS RUNS
# ---------------
# In the PRODUCTION checkout, not the development one. It is the production
# checkout's own git that moves, so the script has to be standing in it. That
# checkout:
#   - holds .deployment-role containing "production";
#   - is never edited by hand and never on a branch. It sits on a detached HEAD
#     at whatever commit is deployed, so `git status` there is a truthful answer
#     to "what is the lab running";
#   - has its own .env, its own certs, and its own COMPOSE_PROJECT_NAME.
#
# WHAT IT DOES, IN ORDER
#   1. refuses if this is not a production checkout, or the tree is dirty
#   2. fetches origin
#   3. refuses a commit with no passing dev-verification row
#   4. reports what the change will do to the running deployment, and refuses to
#      continue past anything destructive without an explicit decision
#   5. takes a backup
#   6. optionally drains jobs, by stopping admission and waiting
#   7. checks out the commit, rebuilds the frontend and image, brings the stack up
#   8. waits for health, restores job admission, records what it did
#
# Usage:
#     scripts/promote.sh                    # promote to origin/main
#     scripts/promote.sh <ref>              # promote to a specific commit or tag
#     scripts/promote.sh --dry-run          # run every gate, change nothing
#     scripts/promote.sh --drain            # wait for running jobs to finish
#     scripts/promote.sh --force            # accept killing in-flight jobs
#     scripts/promote.sh --yes              # accept the destructive report
#     scripts/promote.sh --rollback         # go back to the previous commit
#
# --drain and --force are opposites and deliberately both explicit: one waits for
# users' calculations, the other throws them away. There is no default, because
# guessing either way on someone else's multi-hour CASPT2 run is not a decision a
# script should make.
set -euo pipefail

RED=$'\033[31m'; GRN=$'\033[32m'; YEL=$'\033[33m'; DIM=$'\033[2m'; RST=$'\033[0m'

SELF_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SELF_DIR/.." && pwd)"
cd "$REPO_ROOT"

die()  { echo "${RED}promote: $*${RST}" >&2; exit 1; }
ok()   { echo "${GRN}  ok${RST}  $*"; }
info() { echo "${DIM}  ..${RST}  $*"; }
warn() { echo "${YEL}  !!${RST}  $*"; }
step() { echo; echo "${DIM}--- $* ---------------------------------------${RST}"; }

LEDGER="docs/deployment-ledger.md"
PROMOTION_LOG=".promotion-log"
ROLE_FILE=".deployment-role"

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
        -h|--help)  sed -n '2,60p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'; exit 0 ;;
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

step "checking this is the production checkout"

[ -f "$ROLE_FILE" ] || die "no ${ROLE_FILE} here.
  This script moves a live deployment, so it will not guess whether that is what
  this directory is. Mark it:
      echo production > ${REPO_ROOT}/${ROLE_FILE}"
ROLE="$(tr -d '[:space:]' < "$ROLE_FILE")"
[ "$ROLE" = "production" ] || die "${ROLE_FILE} says \"${ROLE}\".
  Promotion runs in the production checkout. To change the dev stack, just
  git checkout there and run scripts/dev_stack.sh up."
ok "production checkout at ${REPO_ROOT}"

[ -z "$(git status --porcelain)" ] || die "the production checkout has local modifications:
$(git status --short | sed 's/^/    /')
  Production must be a clean, identifiable commit -- otherwise nobody can say
  what the lab is actually running, and a rollback has nothing to return to.
  Undo these (git checkout -- .) or, if they matter, take them to the dev
  checkout and put them through the normal route."
ok "clean tree"

[ -f .env ] || die "no .env -- see docs/DEPLOYMENT.md step 2."
PROJECT="$(envget .env COMPOSE_PROJECT_NAME)"
[ -n "$PROJECT" ] || die "COMPOSE_PROJECT_NAME is not set in .env."
PGUSER_VAL="$(envget .env QC_AGENT_POSTGRES_USER)"; PGUSER_VAL="${PGUSER_VAL:-qc_agent}"
PGDB_VAL="$(envget .env QC_AGENT_POSTGRES_DB)";     PGDB_VAL="${PGDB_VAL:-qc_agent}"
PORT_VAL="$(envget .env QC_AGENT_PROD_PORT)";       PORT_VAL="${PORT_VAL:-8443}"
BASE_URL="https://127.0.0.1:${PORT_VAL}"

COMPOSE=(docker compose -f docker-compose.yml)
if [ -f docker-compose.override.yml ]; then
    COMPOSE+=(-f docker-compose.override.yml)
else
    warn "no docker-compose.override.yml: ORCA and BAGEL will NOT be mounted."
    warn "If this deployment is supposed to run them, stop and restore it first."
fi

CURRENT_SHA="$(git rev-parse HEAD)"

step "resolving what to promote to"

if [ "$ROLLBACK" -eq 1 ]; then
    [ -z "$TARGET_REF" ] || die "--rollback takes no ref."
    [ -f "$PROMOTION_LOG" ] || die "no ${PROMOTION_LOG} -- nothing to roll back to.
  This file is written by this script on every successful promotion; without it
  there is no record of what was deployed before."
    PREV="$(awk '$1=="promoted"{print $4}' "$PROMOTION_LOG" | tail -n1)"
    [ -n "$PREV" ] || die "${PROMOTION_LOG} has no previous commit recorded."
    TARGET_SHA="$(git rev-parse --verify --quiet "${PREV}^{commit}" || true)"
    [ -n "$TARGET_SHA" ] || die "the previous commit ${PREV} is not in this checkout's object store.
  Run: git fetch origin --tags   and try again."
    warn "rolling back to ${TARGET_SHA:0:12} -- code only."
    warn "Database columns added by the promotion you are undoing STAY. The"
    warn "schema is forward-only and idempotent; the pre-promotion backup is the"
    warn "only way to undo it, and restoring it also rewinds every account,"
    warn "session and conversation created since. Almost never what you want."
else
    info "fetching origin"
    git fetch --quiet --tags origin || die "git fetch failed."
    TARGET_REF="${TARGET_REF:-origin/main}"
    TARGET_SHA="$(git rev-parse --verify --quiet "${TARGET_REF}^{commit}" || true)"
    [ -n "$TARGET_SHA" ] || die "cannot resolve ref: ${TARGET_REF}"
fi

echo "  currently deployed: ${CURRENT_SHA:0:12}  $(git log -1 --format=%s "$CURRENT_SHA" 2>/dev/null || echo '(unknown)')"
echo "  promoting to:       ${TARGET_SHA:0:12}  $(git log -1 --format=%s "$TARGET_SHA")"

if [ "$CURRENT_SHA" = "$TARGET_SHA" ]; then
    ok "already deployed -- nothing to do."
    exit 0
fi

# --- the dev-verification gate ---------------------------------------------
step "checking the dev stack verified this commit"

if [ "$ROLLBACK" -eq 1 ]; then
    ok "rollback to a previously deployed commit -- verification already established"
else
    [ -f "$LEDGER" ] || die "no ${LEDGER} in this commit."
    # Rows are appended by dev_stack.sh verify and look like:
    #   | verified | <iso8601> | <sha> | backend | pass |
    VERIFIED_SHAS="$(git show "${TARGET_SHA}:${LEDGER}" 2>/dev/null \
        | awk -F'|' '$2 ~ /verified/ && $6 ~ /pass/ {gsub(/ /,"",$4); print $4}' || true)"

    GATE_OK=0
    GATE_VIA=""
    if printf '%s\n' "$VERIFIED_SHAS" | grep -qx "$TARGET_SHA"; then
        GATE_OK=1; GATE_VIA="its own sha"
    else
        # A commit that only adds documentation, a changelog entry or the ledger
        # row itself on top of a verified commit is the normal shape of a
        # release: you cannot record a verification inside the commit being
        # verified. Anything touching code is not covered by that.
        ALLOWED_RE="^(docs/|CHANGELOG\.md$|README\.md$|CLAUDE\.md$)"
        while read -r v; do
            [ -z "$v" ] && continue
            git cat-file -e "${v}^{commit}" 2>/dev/null || continue
            git merge-base --is-ancestor "$v" "$TARGET_SHA" 2>/dev/null || continue
            DIFF="$(git diff --name-only "$v" "$TARGET_SHA")"
            [ -z "$DIFF" ] && { GATE_OK=1; GATE_VIA="identical tree to ${v:0:12}"; break; }
            if ! printf '%s\n' "$DIFF" | grep -qvE "$ALLOWED_RE"; then
                GATE_OK=1; GATE_VIA="documentation-only changes on top of verified ${v:0:12}"; break
            fi
        done <<< "$VERIFIED_SHAS"
    fi

    if [ "$GATE_OK" -eq 0 ]; then
        echo
        echo "${RED}promote: this commit has not been verified on the dev stack.${RST}" >&2
        echo >&2
        echo "  ${TARGET_SHA:0:12} has no passing row in ${LEDGER}, and it is not a" >&2
        echo "  documentation-only change on top of one." >&2
        echo >&2
        echo "  Do this instead, in the DEVELOPMENT checkout:" >&2
        echo "      git checkout main && git pull origin main" >&2
        echo "      scripts/dev_stack.sh up" >&2
        echo "      scripts/dev_stack.sh verify" >&2
        echo "      git add ${LEDGER} && git commit -m 'Record a verified dev run'" >&2
        echo "      git push origin main" >&2
        echo >&2
        echo "  Then re-run this. If production is broken RIGHT NOW and the fix" >&2
        echo "  cannot wait for a full suite run, that is a real situation -- but it" >&2
        echo "  is a decision to make out loud, not by bypassing this. Verify the" >&2
        echo "  fix on dev with a short run and record it." >&2
        exit 1
    fi
    ok "verified on dev (${GATE_VIA})"
fi

# --- the destructive-change report ----------------------------------------
step "what this will do to the running deployment"

set +e
bash scripts/check_destructive.sh --from "$CURRENT_SHA" --to "$TARGET_SHA" --stack-dir "$REPO_ROOT"
IMPACT_RC=$?
set -e

if [ "$IMPACT_RC" -eq 2 ]; then
    die "the impact report could not run. Not promoting blind."
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
        printf 'Type PROMOTE to go ahead anyway: '
        read -r reply
        [ "$reply" = "PROMOTE" ] || die "aborted -- nothing was touched."
    else
        warn "destructive changes accepted via --yes"
    fi
fi

# In-flight jobs need their own decision even when nothing else is destructive.
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
if [ "$INFLIGHT" -gt 0 ] && [ "$DRAIN" -eq 0 ] && [ "$FORCE" -eq 0 ]; then
    die "${INFLIGHT} job(s) are running or pending, and they will be killed.
  Choose explicitly:
      --drain   stop admitting new jobs, wait for these to finish, then promote
                (up to ${DRAIN_TIMEOUT}s; a CASSCF run taking hours is normal here)
      --force   promote now and accept losing them
  Nothing has been changed."
fi

if [ "$DRY_RUN" -eq 1 ]; then
    echo
    ok "dry run: every gate passed. Re-run without --dry-run to promote."
    exit 0
fi

# --- from here on the deployment is being changed --------------------------
step "backing up before changing anything"
if bash scripts/backup.sh; then
    ok "backup taken"
else
    die "backup failed -- refusing to promote without one.
  This is the only thing that can undo a schema change."
fi

psql_prod() { "${COMPOSE[@]}" exec -T postgres psql -At -U "$PGUSER_VAL" -d "$PGDB_VAL" "$@"; }

DRAINED=0
PRIOR_CAP=""
restore_admission() {
    [ "$DRAINED" -eq 1 ] || return 0
    if [ -n "$PRIOR_CAP" ]; then
        psql_prod -c "UPDATE app_config SET value='${PRIOR_CAP}'::jsonb, updated_at=now() WHERE key='max_concurrent_jobs_total'" >/dev/null 2>&1 || true
    else
        psql_prod -c "DELETE FROM app_config WHERE key='max_concurrent_jobs_total'" >/dev/null 2>&1 || true
    fi
    DRAINED=0
    ok "job admission restored"
}
# Any exit from here on must put admission back. Leaving the cap at 0 would look
# exactly like a working deployment whose jobs mysteriously never start.
trap 'restore_admission' EXIT

if [ "$DRAIN" -eq 1 ] && [ "$INFLIGHT" -gt 0 ]; then
    step "draining"
    # Stop admission FIRST, then wait. Waiting without stopping admission is a
    # race you can lose indefinitely: every job that finishes frees a slot for
    # the next queued one, so "wait until nothing is running" may never come
    # true on a busy deployment. Setting the admin cap to 0 makes
    # _concurrent_jobs_block_reason() block every new job with a clear
    # "waiting for a free job slot (n/0 running total)" message.
    PRIOR_CAP="$(psql_prod -c "SELECT value FROM app_config WHERE key='max_concurrent_jobs_total'" 2>/dev/null | tail -n1 || true)"
    psql_prod -c "INSERT INTO app_config (key, value) VALUES ('max_concurrent_jobs_total', '0'::jsonb)
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
  nothing was promoted. Wait longer (QC_AGENT_DRAIN_TIMEOUT=<seconds>), or use
  --force if you have decided to lose them."
    fi
    ok "drained"
fi

step "moving the checkout to ${TARGET_SHA:0:12}"
git -c advice.detachedHead=false checkout --detach --quiet "$TARGET_SHA"
ok "checked out $(git rev-parse --short HEAD) (detached, as production should be)"

step "rebuilding"
if command -v npm >/dev/null 2>&1; then
    (cd frontend && npm ci --silent && npm run build)
    ok "frontend/dist rebuilt"
else
    warn "npm is not on PATH, so frontend/dist was NOT rebuilt."
    warn "nginx serves it from a bind mount, so the lab will keep seeing the OLD"
    warn "frontend against the NEW api. Activate the node environment and run:"
    warn "    (cd frontend && npm ci && npm run build)"
fi

# --build here rather than a separate `down`/`up`: compose builds the image while
# the old containers are still serving, so the outage is the recreate, not the
# build.
"${COMPOSE[@]}" up -d --build || die "compose up failed. The stack may be partly down --
  check: ${COMPOSE[*]} ps    and consider: scripts/promote.sh --rollback"

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
    warn "If it is genuinely broken: scripts/promote.sh --rollback"
fi

restore_admission
trap - EXIT

printf 'promoted %s %s %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$TARGET_SHA" "$CURRENT_SHA" >> "$PROMOTION_LOG"

echo
if [ "$HEALTHY" -eq 1 ]; then
    echo "${GRN}promoted${RST} ${CURRENT_SHA:0:12} -> ${TARGET_SHA:0:12}"
else
    echo "${YEL}promoted with a failing health check${RST} ${CURRENT_SHA:0:12} -> ${TARGET_SHA:0:12}"
fi
echo "  recorded in ${PROMOTION_LOG}; roll back with: scripts/promote.sh --rollback"
echo "  tell the lab to hard-reload their browser tab if the frontend changed."
