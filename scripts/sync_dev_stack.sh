#!/usr/bin/env bash
# Bring the dev stack onto the current `main`, in one command.
#
# This exists because doing it by hand has three traps, and we hit all
# three inside one evening:
#
#   1. `git pull` with no upstream on `main` reports "Already up to date"
#      and fetches nothing. The branch sat two phases behind while two
#      separate pull attempts looked like they had worked.
#   2. `dev_stack.sh frontend` shells out to npm, which is not on PATH
#      until the node environment is activated. Which environment is a
#      property of the host, recorded in CLAUDE.local.md, not of the repo.
#   3. `frontend/dist` is served by nginx from a HOST bind mount, so
#      `docker compose build` does not refresh it. Rebuilding the image
#      without rebuilding dist leaves the browser on the previous UI while
#      the API serves the new one -- a split that looks like a frontend bug
#      and is not. CLAUDE.md flags this; the ordering here enforces it.
#
# So: fetch explicitly, fast-forward only, rebuild dist, then the image.
# Refuses rather than guesses at every step.
#
#   scripts/sync_dev_stack.sh            pull, rebuild dist, rebuild + restart
#   scripts/sync_dev_stack.sh --no-pull  skip the pull (already on the commit)
set -euo pipefail

RED=$'\033[31m'; GRN=$'\033[32m'; YEL=$'\033[33m'; RST=$'\033[0m'
die() { printf '%s\n' "${RED}error:${RST} $*" >&2; exit 1; }
ok()  { printf '%s\n' "${GRN}ok:${RST} $*"; }
note(){ printf '%s\n' "${YEL}note:${RST} $*"; }

SELF_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SELF_DIR/.." && pwd)"
cd "$REPO_ROOT"

[ -f .deployment-role ] || die "no .deployment-role here -- refusing to touch a checkout that does not say which stack it is."
ROLE="$(tr -d '[:space:]' < .deployment-role)"
[ "$ROLE" = "dev" ] || die "this checkout is '$ROLE', not 'dev'. Production is advanced only by scripts/promote.sh."

# --------------------------------------------------------------- 1. pull
if [ "${1:-}" != "--no-pull" ]; then
  BRANCH="$(git rev-parse --abbrev-ref HEAD)"
  [ "$BRANCH" = "main" ] || die "on branch '$BRANCH', not main. The dev stack tracks main."

  git diff --quiet || die "the working tree has uncommitted changes; commit or stash them first."

  # Explicit remote and branch, never a bare `git pull`: without an
  # upstream configured, that silently does nothing (trap 1).
  git fetch origin main
  BEFORE="$(git rev-parse --short HEAD)"
  AFTER="$(git rev-parse --short FETCH_HEAD)"
  if [ "$BEFORE" = "$AFTER" ]; then
    ok "already at $BEFORE"
  else
    git merge --ff-only FETCH_HEAD \
      || die "main cannot fast-forward onto origin/main -- it has diverged. Resolve by hand."
    ok "main $BEFORE -> $AFTER"
  fi
fi

# ----------------------------------------------------------- 2. frontend
# Before the image, always: nginx serves dist from a bind mount, so a
# rebuilt image with a stale dist is a split deployment (trap 3).
if ! command -v npm >/dev/null 2>&1; then
  note "npm is not on PATH; trying the node environment named in CLAUDE.local.md"
  CONDA_SH="${CONDA_SH:-$HOME/apps/miniconda3/etc/profile.d/conda.sh}"
  # shellcheck disable=SC1090
  [ -f "$CONDA_SH" ] && . "$CONDA_SH" && conda activate "${NODE_ENV_NAME:-node24}" 2>/dev/null || true
fi
command -v npm >/dev/null 2>&1 \
  || die "npm still not on PATH. Activate the node environment first (see CLAUDE.local.md), or set CONDA_SH / NODE_ENV_NAME."

scripts/dev_stack.sh frontend
ok "frontend/dist rebuilt"

# --------------------------------------------------------------- 3. stack
scripts/dev_stack.sh up
ok "stack is up at $(git rev-parse --short HEAD)"
