#!/usr/bin/env bash
# Put the frontend bundle from the built api image onto the host, where nginx
# serves it from.
#
# WHY THIS EXISTS
# ---------------
# The bundle is built inside the image (Dockerfile's frontend-build stage, on
# node:24-slim, which is the only Node version Ketcher supports). nginx does
# not serve that copy: it bind-mounts the host's ./frontend/dist. Until this
# script existed the host built the bundle a second time with its own npm, so
# the same source produced two artefacts and only one of them was deployed.
# That cost a host Node 24 (the one prerequisite an install cannot fetch for
# itself), and where the host had no npm the fallback ran a node:24 container
# as root and left root-owned files under frontend/.
#
# Copying the image's own bundle out instead means one build, one artefact, and
# no Node on the host at all. `docker cp`-style extraction writes as the
# invoking user, so nothing lands root-owned.
#
# CONTRACT
#   Exits 0 having replaced frontend/dist, or non-zero having touched nothing.
#
# Usage:
#     scripts/extract_frontend.sh [FALLBACK_SHA]
#
# FALLBACK_SHA stamps frontend/dist/.build-commit when the image itself does
# not know what it was built from. The image is asked first and preferred: a
# stamp taken from the image cannot disagree with the image, which is the whole
# point of having one.
set -euo pipefail

SELF_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SELF_DIR/.." && pwd)"
cd "$REPO_ROOT"

RED=$'\033[31m'; GRN=$'\033[32m'; DIM=$'\033[2m'; RST=$'\033[0m'
if [ ! -t 1 ]; then RED=''; GRN=''; DIM=''; RST=''; fi

die()  { echo "${RED}extract_frontend: $*${RST}" >&2; exit 1; }
ok()   { echo "${GRN}  ok${RST}  $*"; }
info() { echo "${DIM}  ..${RST}  $*"; }

FALLBACK_SHA="${1:-}"

COMPOSE=(docker compose)
docker compose version >/dev/null 2>&1 || die "docker compose (v2) is required."

INCOMING="frontend/dist.incoming"

# A run that died part-way leaves this behind. Clearing it rather than trusting
# it is absent keeps the script re-runnable. `dist.previous` is also cleared:
# an earlier version of this script staged through it, and a deployment that
# ran that version still has one sitting there.
rm -rf "$INCOMING" frontend/dist.previous
mkdir -p "$INCOMING"
# Only the staging directory is cleaned up on failure. frontend/dist itself is
# never touched until the swap, which is what makes "or non-zero having touched
# nothing" true.
trap 'rm -rf "$INCOMING" 2>/dev/null || true' EXIT

# `compose run` rather than resolving an image name and `docker create`:
# the api service has no `image:` key, so its name is inferred from the compose
# project, and hardcoding or guessing that breaks the moment two checkouts of
# this repository exist on one host -- which is the normal case here. Asking
# compose avoids the question entirely.
#
# --no-deps so this does not start postgres and redis to copy a directory,
# -T because a TTY would corrupt the tar stream, and --entrypoint '' to skip
# docker/entrypoint.sh, which exists to launch the server.
info "reading the bundle out of the api image"
if ! "${COMPOSE[@]}" run --rm --no-deps -T --entrypoint sh api \
        -c 'cd /app/frontend/dist 2>/dev/null && tar cf - . 2>/dev/null' \
        | tar xf - -C "$INCOMING" 2>/dev/null; then
    die "could not read /app/frontend/dist out of the api image.
  Has the image been built? Try: docker compose build api"
fi

# Assert the copy is a real bundle before it replaces a working one. An empty
# or half-written directory swapped into place is a white screen for every
# user, and the tar pipeline above cannot distinguish "no such directory" from
# "an empty one" on its own.
[ -f "$INCOMING/index.html" ] \
    || die "the extracted bundle has no index.html -- refusing to install it."
compgen -G "$INCOMING/assets/index-*.js" >/dev/null \
    || die "the extracted bundle has no assets/index-*.js -- refusing to install it."

# The commit the image was built from, straight from the image. Falls back to
# the argument, then to "unknown", which update.sh reads as "assume stale".
IMAGE_SHA="$("${COMPOSE[@]}" run --rm --no-deps -T --entrypoint sh api \
    -c 'printf %s "${QC_AGENT_BUILD_COMMIT:-}"' 2>/dev/null | tr -d '[:space:]' || true)"
STAMP="$IMAGE_SHA"
if [ -z "$STAMP" ] || [ "$STAMP" = "unknown" ]; then
    STAMP="${FALLBACK_SHA:-unknown}"
fi

# The contents are replaced in place. frontend/dist itself is never moved,
# renamed or recreated, and that is not a stylistic choice.
#
# docker-compose.yml bind-mounts ./frontend/dist into nginx. A bind mount
# resolves to an inode at mount time and follows that inode forever, not the
# path -- so `mv frontend/dist dist.previous && mv dist.incoming frontend/dist`
# leaves a running nginx mounted on the directory that was just moved aside,
# and serving 404 for everything from a directory nobody can see any more.
# The first version of this script did exactly that. It looked correct on a
# fresh install, because there nginx starts *after* the copy, and only showed
# up on the second run against a stack that was already up -- which is the
# case that matters, since that is what every update is.
#
# The order below is what keeps a live deployment serving throughout:
#
#   1. new assets land alongside the old ones. Vite content-hashes their
#      names, so nothing collides and the old index.html keeps working.
#   2. index.html is replaced by an atomic rename within the same directory,
#      which is the single instant the deployment changes version.
#   3. only then are the old assets pruned, so no tab is ever handed an
#      index.html referring to a file that has already been deleted.
mkdir -p frontend/dist

# 1. everything except index.html
( cd "$INCOMING" && find . -type f ! -name index.html -print0 ) \
    | while IFS= read -r -d '' rel; do
        mkdir -p "frontend/dist/$(dirname "$rel")"
        cp -f "$INCOMING/$rel" "frontend/dist/$rel.tmp.$$"
        mv -f "frontend/dist/$rel.tmp.$$" "frontend/dist/$rel"
    done

# 2. the version flip
cp -f "$INCOMING/index.html" "frontend/dist/.index.html.tmp.$$"
mv -f "frontend/dist/.index.html.tmp.$$" frontend/dist/index.html

# 3. prune what the new bundle no longer has. .build-commit is ours, not the
#    bundle's, so it is never a candidate for removal.
( cd frontend/dist && find . -type f -print ) | while IFS= read -r rel; do
    case "$rel" in ./.build-commit) continue ;; esac
    [ -f "$INCOMING/$rel" ] || rm -f "frontend/dist/$rel"
done
find frontend/dist -type d -empty -delete 2>/dev/null || true

# Written last, so a run that failed earlier leaves the previous (accurate)
# stamp rather than a claim about a bundle that was never installed.
printf '%s\n' "$STAMP" > frontend/dist/.build-commit

rm -rf "$INCOMING"
trap - EXIT
ok "frontend/dist installed from the api image, stamped ${STAMP:0:12}"
