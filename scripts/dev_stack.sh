#!/usr/bin/env bash
# The development stack: a full copy of the deployment that nobody depends on.
#
# WHY A SECOND STACK RATHER THAN JUST RUNNING THE DEV SERVERS
# ----------------------------------------------------------
# `python -m server.main` plus `npm run dev` is still the fastest way to work on
# most code, and nothing here replaces it. But a large class of real bugs in this
# project only exists in the containerised, nginx-fronted, Postgres-backed
# deployment: the whole tests/ suite is about that layer (CLAUDE.md says so
# outright), the auth layer is inert without QC_AGENT_DATABASE_URL, and nginx
# serves the built frontend from a bind mount rather than from Vite. Testing
# those against the deployment the lab is using means testing against the thing
# people are trying to get work done on.
#
# So: two stacks, same host, same repository, deliberately unequal.
#
#   development (this)   destructible by design. `reset` throws away its
#                        database and every job it has ever run, and that is a
#                        normal thing to do rather than an emergency.
#   production           the lab's deployment. Only ever advanced by
#                        scripts/promote.sh, only to a commit that this stack
#                        has verified.
#
# How they are kept apart, since sharing one host means the separation has to be
# deliberate at every layer:
#
#   directory      separate checkouts, so ./data and ./frontend/dist -- both
#                  relative bind mounts -- cannot collide.
#   compose project COMPOSE_PROJECT_NAME in each .env, so the postgres and redis
#                  volumes are per-stack. Same volume NAME, different project
#                  prefix, no shared bytes.
#   listener       production publishes on the LAN address; this stack never
#                  does. See docker-compose.dev.yml.
#   secrets        different Postgres password and JWT secret, checked below --
#                  a copied .env would otherwise give dev sessions authority
#                  over production's database.
#   role marker    .deployment-role, untracked, one word. This script refuses to
#                  touch a checkout that does not say "dev".
#
# Usage:
#     scripts/dev_stack.sh up          bring it up (builds the image if needed)
#     scripts/dev_stack.sh down        stop it, keep the database and data/
#     scripts/dev_stack.sh reset       destroy the database, the volumes and all
#                                      dev job/thread/upload state, then bring it
#                                      back up empty. Keeps the knowledge base.
#     scripts/dev_stack.sh reset --all same, but also wipes the knowledge base
#                                      and the scraped corpus (slow to rebuild)
#     scripts/dev_stack.sh status      what is running, at which commit
#     scripts/dev_stack.sh logs [svc]  follow logs
#     scripts/dev_stack.sh frontend    rebuild frontend/dist (needs node)
#     scripts/dev_stack.sh verify      run the standing suite and, if it passes,
#                                      record this commit as promotable
set -euo pipefail

RED=$'\033[31m'; GRN=$'\033[32m'; YEL=$'\033[33m'; DIM=$'\033[2m'; RST=$'\033[0m'

SELF_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SELF_DIR/.." && pwd)"
cd "$REPO_ROOT"

die()  { echo "${RED}dev_stack: $*${RST}" >&2; exit 1; }
ok()   { echo "${GRN}  ok${RST}  $*"; }
info() { echo "${DIM}  ..${RST}  $*"; }
warn() { echo "${YEL}  !!${RST}  $*"; }

LEDGER="docs/deployment-ledger.md"
ROLE_FILE=".deployment-role"

# --- guard: this must be a development checkout ----------------------------
# The failure this prevents is not hypothetical: the two checkouts hold the same
# repository, the same scripts and nearly the same .env, so the only thing that
# distinguishes them at a glance is which directory you are standing in. `reset`
# in the wrong one destroys the lab's database.
if [ ! -f "$ROLE_FILE" ]; then
    die "no ${ROLE_FILE} here.
  This checkout is not marked, so this script will not run in it. Create it with
  exactly one word -- dev or production -- to say what this checkout is:
      echo dev > ${REPO_ROOT}/${ROLE_FILE}
  It is untracked on purpose: it describes this directory, not the project."
fi
ROLE="$(tr -d '[:space:]' < "$ROLE_FILE")"
[ "$ROLE" = "dev" ] || die "${ROLE_FILE} says \"${ROLE}\", not \"dev\".
  Refusing to run the development stack against a ${ROLE} checkout. If you meant
  to change what production is running, that is scripts/promote.sh."

[ -f .env ] || die "no .env in ${REPO_ROOT} -- see docs/DEPLOYMENT.md step 2."

envget() {
    local file="$1" key="$2"
    [ -f "$file" ] || return 0
    sed -nE "s/^[[:space:]]*${key}=(.*)$/\1/p" "$file" | tail -n1 | sed -E 's/^"(.*)"$/\1/'
}

PROJECT="$(envget .env COMPOSE_PROJECT_NAME)"
[ -n "$PROJECT" ] || die "COMPOSE_PROJECT_NAME is not set in ${REPO_ROOT}/.env.
  Without it compose derives the project name from the directory name, and the
  two stacks can end up sharing volumes. Set it to something obviously dev, e.g.
      COMPOSE_PROJECT_NAME=nexusqc_dev"
case "$PROJECT" in
    *dev*) : ;;
    *) die "COMPOSE_PROJECT_NAME is \"${PROJECT}\", which does not look like a dev
  project. Refusing, because this name is what keeps the two stacks' database
  volumes apart." ;;
esac

DEV_PORT="$(envget .env QC_AGENT_DEV_PORT)"; DEV_PORT="${DEV_PORT:-8444}"
BASE_URL="https://127.0.0.1:${DEV_PORT}"

# --- guard: dev must not be holding production's secrets -------------------
# Copying production's .env across is the obvious way to get a working dev
# config, and it is the one thing that would undo the separation: the same JWT
# secret means a session minted here is valid there, and the same Postgres
# password plus a `docker compose` typo reaches the wrong database.
PROD_DIR="$(envget .env QC_AGENT_PROD_DIR)"
if [ -n "$PROD_DIR" ] && [ -f "${PROD_DIR}/.env" ]; then
    for k in QC_AGENT_JWT_SECRET QC_AGENT_POSTGRES_PASSWORD; do
        a="$(envget .env "$k")"; b="$(envget "${PROD_DIR}/.env" "$k")"
        if [ -n "$a" ] && [ "$a" = "$b" ]; then
            die "${k} here is identical to production's.
  Generate a separate one for dev; a shared JWT secret makes a dev session valid
  against the lab's deployment. See docs/DEPLOYMENT.md step 2 for the openssl
  one-liners."
        fi
    done
    DEV_MODEL="$(envget .env QC_AGENT_LLM_MODEL)"
    PROD_MODEL="$(envget "${PROD_DIR}/.env" QC_AGENT_LLM_MODEL)"
    if [ -n "$DEV_MODEL" ] && [ -n "$PROD_MODEL" ] && [ "$DEV_MODEL" != "$PROD_MODEL" ]; then
        warn "dev is pinned to ${DEV_MODEL}, production to ${PROD_MODEL}."
        warn "Two models means two resident copies in the host-wide Ollama, which"
        warn "other tenants of this machine pay for. Fine if deliberate."
    fi
fi

# Compose file order matters: the host-specific override supplies the licensed
# engine mounts, and the dev overlay must come last because it uses !override to
# REPLACE the published ports rather than add to them.
COMPOSE=(docker compose -f docker-compose.yml)
if [ -f docker-compose.override.yml ]; then
    COMPOSE+=(-f docker-compose.override.yml)
else
    warn "no docker-compose.override.yml -- ORCA and BAGEL will not be mounted,"
    warn "so this stack can only run PySCF jobs. Copy the .example to enable them."
fi
COMPOSE+=(-f docker-compose.dev.yml)

health() {
    curl -fsS -k --max-time 5 "${BASE_URL}/api/health" 2>/dev/null
}

wait_healthy() {
    local tries="${1:-60}"
    info "waiting for ${BASE_URL}/api/health"
    for _ in $(seq "$tries"); do
        if health >/dev/null; then ok "healthy at ${BASE_URL}"; return 0; fi
        sleep 5
    done
    warn "not healthy after $((tries * 5))s -- check: $0 logs api"
    return 1
}

CMD="${1:-}"; shift || true

case "$CMD" in

up)
    info "project ${PROJECT}, commit $(git rev-parse --short HEAD) on $(git rev-parse --abbrev-ref HEAD)"
    [ -f frontend/dist/index.html ] || warn "frontend/dist is empty -- run: $0 frontend"
    "${COMPOSE[@]}" up -d --build
    wait_healthy || true
    echo
    echo "  dev stack:  ${BASE_URL}"
    echo "  ${DIM}not published on the LAN address -- lab users cannot reach it${RST}"
    ;;

down)
    "${COMPOSE[@]}" down
    ok "stopped; database volume and data/ left intact"
    ;;

reset)
    # Two scopes, because "everything under data/" is not one kind of thing.
    #
    # User state -- jobs, threads, uploads -- is what a dev stack accumulates
    # while being tested, and throwing it away is the entire point of `reset`.
    #
    # The knowledge base is not that. data/kb is a Chroma vector store built from
    # data/scraped by scripts/seed_knowledge_base.py, and rebuilding it is slow.
    # It is seeded content, not test residue: wiping it on every reset would make
    # `reset` a command you avoid, and a destructible stack you avoid destroying
    # is just production with fewer users. So it is preserved by default and
    # `reset --all` is there for when the KB itself is what changed.
    KEEP=(kb scraped molecules bse_basis_cache)
    WIPE_ALL=0
    [ "${1:-}" = "--all" ] && WIPE_ALL=1

    echo "${YEL}This destroys the development stack:${RST}"
    echo "  - the ${PROJECT} Postgres volume (every dev account, session, chat)"
    echo "  - the ${PROJECT} Redis volume"
    if [ "$WIPE_ALL" -eq 1 ]; then
        echo "  - ALL of ${REPO_ROOT}/data, including the knowledge base and the"
        echo "    scraped corpus it is built from (slow to rebuild:"
        echo "    scripts/seed_knowledge_base.py)"
    else
        echo "  - dev jobs, threads and uploads under ${REPO_ROOT}/data"
        echo "  ${DIM}kept: ${KEEP[*]} -- seeded content, not test residue.${RST}"
        echo "  ${DIM}Use 'reset --all' to wipe those too.${RST}"
    fi
    echo
    echo "Production is a different checkout and a different compose project and"
    echo "is not touched. Nothing here is backed up, by design."
    echo
    printf 'Type DESTROY to continue: '
    read -r reply
    [ "$reply" = "DESTROY" ] || die "aborted."
    "${COMPOSE[@]}" down -v
    # Keep data/ itself: the api container runs as a non-root user and expects to
    # find it already present and owned by the host operator (docker-compose.yml's
    # APP_UID note). Removing and letting the container recreate it as root is
    # exactly the PermissionError the README warns about.
    if [ -d data ]; then
        # One regex built from the same array the message above printed, so the
        # two can never disagree about what is kept.
        KEEP_RE="^($(IFS='|'; echo "${KEEP[*]}"))$"
        for entry in data/* data/.[!.]*; do
            [ -e "$entry" ] || continue
            base="$(basename "$entry")"
            if [ "$WIPE_ALL" -eq 0 ] && printf '%s' "$base" | grep -qE "$KEEP_RE"; then
                info "keeping data/${base}"
                continue
            fi
            rm -rf "$entry"
        done
        ok "data/ cleared, directory and ownership preserved"
    fi
    "${COMPOSE[@]}" up -d --build
    wait_healthy || true
    echo
    echo "  a clean dev stack: ${BASE_URL}"
    echo "  create the first admin with: server/admin_cli.py (docs/DEPLOYMENT.md step 7)"
    [ "$WIPE_ALL" -eq 1 ] && echo "  the knowledge base is gone -- reseed it: scripts/seed_knowledge_base.py"
    ;;

status)
    echo "commit:  $(git rev-parse --short HEAD)  $(git log -1 --format=%s)"
    echo "branch:  $(git rev-parse --abbrev-ref HEAD)"
    echo "project: ${PROJECT}"
    echo
    "${COMPOSE[@]}" ps
    echo
    if health >/dev/null; then ok "healthy at ${BASE_URL}"; else warn "not answering at ${BASE_URL}"; fi
    ;;

logs)
    "${COMPOSE[@]}" logs -f --tail=100 ${1:+"$1"}
    ;;

frontend)
    # nginx serves frontend/dist through a bind mount, so this is not something
    # `docker compose build` can do for you -- CLAUDE.md flags it as a trap
    # precisely because the container looks freshly built either way.
    command -v npm >/dev/null || die "npm not on PATH -- activate the node environment first
  (CLAUDE.local.md records which one on this host)."
    (cd frontend && npm run build)
    ok "frontend/dist rebuilt -- nginx picks it up with no restart"
    ;;

verify)
    # The gate that makes "test on dev first" mean something. promote.sh will not
    # advance production to a commit that has no passing row here.
    health >/dev/null || die "the dev stack is not answering at ${BASE_URL} -- start it with: $0 up"
    if [ -n "$(git status --porcelain)" ]; then
        die "the working tree is dirty.
  A verification row names a commit, so the thing verified has to BE that commit.
  Commit or stash first, then re-run."
    fi
    SHA="$(git rev-parse HEAD)"
    info "running tests/run_backend.sh against ${BASE_URL}"
    set +e
    QC_AGENT_TEST_BASE_URL="$BASE_URL" bash tests/run_backend.sh
    RC=$?
    set -e
    STAMP="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
    if [ "$RC" -ne 0 ]; then
        echo
        die "the suite exited ${RC}. Nothing recorded, so this commit is not promotable.
  Note that a sec_* script printing [FAIL] can be the expected outcome -- see
  tests/README.md -- so read the output before assuming the code is at fault."
    fi
    printf '| verified | %s | %s | backend | pass |\n' "$STAMP" "$SHA" >> "$LEDGER"
    ok "suite passed; recorded ${SHA:0:12} as promotable in ${LEDGER}"
    echo
    echo "  Commit the ledger row, push it, and production can be advanced to it:"
    echo "    git add ${LEDGER} && git commit -m 'Record a verified dev run' && git push origin main"
    ;;

*)
    sed -n '/^# Usage:/,/verify /p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'
    exit 2
    ;;
esac
