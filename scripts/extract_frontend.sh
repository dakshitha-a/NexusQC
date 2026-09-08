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
PREVIOUS="frontend/dist.previous"

# A previous run that died between the two moves leaves these behind. Clearing
# them here rather than trusting they are absent keeps the script re-runnable.
rm -rf "$INCOMING" "$PREVIOUS"
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

# Swapped, not emptied and refilled. nginx is serving out of frontend/dist
# while this runs, and removing it first would 404 every asset in every open
# tab for as long as the copy takes.
if [ -d frontend/dist ]; then
    mv frontend/dist "$PREVIOUS"
fi
mv "$INCOMING" frontend/dist
rm -rf "$PREVIOUS"

# Written after the swap, so a run that failed earlier leaves the previous
# (accurate) stamp rather than a claim about a bundle that was never installed.
printf '%s\n' "$STAMP" > frontend/dist/.build-commit

trap - EXIT
ok "frontend/dist installed from the api image, stamped ${STAMP:0:12}"
