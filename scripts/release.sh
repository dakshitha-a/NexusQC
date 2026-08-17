#!/usr/bin/env bash
# Publish a release to the PUBLIC remote.
#
# WHY THIS IS A SCRIPT AND NOT A HABIT
# ------------------------------------
# Development pushes go to a private remote continuously. This is the one
# command that makes work permanently public, and a public push cannot be taken
# back: deleting a commit later does not unpublish it, because anyone may
# already have cloned or cached it, and GitHub keeps unreferenced objects
# reachable by SHA for a while afterwards.
#
# Everything below is therefore a refusal, not a warning. The script does no
# guessing: if a precondition is not met it stops and says which one, because
# the failure mode it exists to prevent is a half-checked release at 2am.
#
# The invariant it relies on: every tracked file in this repository is
# publishable (see docs/DEVELOPMENT.md). This script does not sanitise anything
# -- it verifies that the invariant still holds, then pushes the same commits
# the private remote already has.
#
# Usage:
#     ./scripts/release.sh 1.1.0
#     ./scripts/release.sh 1.1.0 --dry-run     # run every gate, push nothing
set -euo pipefail

RED=$'\033[31m'; GRN=$'\033[32m'; YEL=$'\033[33m'; DIM=$'\033[2m'; RST=$'\033[0m'
if [ ! -t 1 ]; then RED=''; GRN=''; YEL=''; DIM=''; RST=''; fi

die() { echo "${RED}release: $*${RST}" >&2; exit 1; }
ok()  { echo "${GRN}  ok${RST}  $*"; }

cd "$(git rev-parse --show-toplevel)" || die "not inside a git repository"

VERSION="${1:-}"
DRY_RUN=0
[ "${2:-}" = "--dry-run" ] && DRY_RUN=1
[ "${1:-}" = "--dry-run" ] && die "give the version first: release.sh <version> [--dry-run]"

[ -n "$VERSION" ] || die "usage: $0 <version> [--dry-run]"
# Semver, no leading "v" -- the tag gets the v, the CHANGELOG heading does not.
[[ "$VERSION" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]] \
    || die "version must be MAJOR.MINOR.PATCH (got '$VERSION')"

TAG="v${VERSION}"
PRIVATE_REMOTE="${QC_AGENT_PRIVATE_REMOTE:-origin}"
PUBLIC_REMOTE="${QC_AGENT_PUBLIC_REMOTE:-public}"

echo "${DIM}checking preconditions for ${TAG}${RST}"

# --- 1. Branch and tree state ----------------------------------------------
BRANCH="$(git rev-parse --abbrev-ref HEAD)"
[ "$BRANCH" = "main" ] || die "on branch '$BRANCH'; releases are cut from main only"
ok "on main"

git diff --quiet && git diff --cached --quiet \
    || die "working tree or index is dirty; commit or stash first"
ok "working tree clean"

# --- 2. Remotes exist -------------------------------------------------------
git remote get-url "$PRIVATE_REMOTE" >/dev/null 2>&1 \
    || die "no '$PRIVATE_REMOTE' remote (the private one). See docs/DEVELOPMENT.md"
git remote get-url "$PUBLIC_REMOTE" >/dev/null 2>&1 \
    || die "no '$PUBLIC_REMOTE' remote (the public one). See docs/DEVELOPMENT.md"
ok "both remotes configured"

# --- 3. The safety scan -----------------------------------------------------
# The whole-tree scan, not --staged: this is about what the public repository
# will contain, not about one commit.
if ! ./scripts/check_public_safe.sh >/dev/null 2>&1; then
    echo >&2
    ./scripts/check_public_safe.sh >&2 || true
    die "public-safety scan failed (output above); nothing was pushed"
fi
ok "public-safety scan passes"

# --- 4. Private remote is up to date ---------------------------------------
# Publishing something the private remote has never seen means it was never
# reviewed in the ordinary flow.
git fetch --quiet "$PRIVATE_REMOTE" main || die "could not fetch $PRIVATE_REMOTE"
LOCAL="$(git rev-parse main)"
REMOTE="$(git rev-parse "$PRIVATE_REMOTE/main")"
[ "$LOCAL" = "$REMOTE" ] \
    || die "main differs from $PRIVATE_REMOTE/main; push there first (this is the reviewed state)"
ok "main matches $PRIVATE_REMOTE/main"

# --- 5. Tag is free ---------------------------------------------------------
git rev-parse -q --verify "refs/tags/$TAG" >/dev/null \
    && die "tag $TAG already exists; releases are never re-cut under the same version"
ok "tag $TAG is free"

# --- 6. CHANGELOG has a section for this version ---------------------------
grep -qE "^## \[${VERSION//./\\.}\]" CHANGELOG.md \
    || die "CHANGELOG.md has no '## [$VERSION]' section; write what changed first"
ok "CHANGELOG.md documents $VERSION"

# --- 6b. The public remote can be advanced without discarding real history --
# The public repository was created with a placeholder commit holding README.md
# and nothing else, deliberately sharing no history with main, so the name and a
# readable landing page existed before any code was published. That makes the
# first release a non-fast-forward, which git rejects -- and without this gate it
# would be rejected at the very END of this script, after the release commit, the
# tag, and the push to the private remote had all already happened. A release is
# a sequence of refusals precisely so it cannot fail halfway.
PUBLIC_FORCE=()
if git fetch --quiet "$PUBLIC_REMOTE" main 2>/dev/null; then
    PUB="$(git rev-parse FETCH_HEAD)"
    if git merge-base --is-ancestor "$PUB" main 2>/dev/null; then
        ok "$PUBLIC_REMOTE/main is an ancestor of main (ordinary fast-forward)"
    # "Has no parent" is tested by asking for the first parent and expecting
    # that to fail. The obvious alternative -- taking the parent list from
    # rev-list --parents and checking it is empty -- silently does not work:
    # cut prints the whole line when the delimiter is absent, so a root commit
    # (one field, no space) yields its own sha rather than an empty string and
    # the test is never true. That version refused the legitimate first release.
    elif ! git rev-parse -q --verify "${PUB}^" >/dev/null 2>&1 \
         && [ "$(git ls-tree -r --name-only "$PUB")" = "README.md" ]; then
        # Exactly the placeholder and nothing else: a single commit with no
        # parent whose whole tree is one file. Replacing that discards nothing
        # anyone could have cloned and depended on. --force-with-lease rather
        # than --force, so it still refuses if the remote has moved since.
        PUBLIC_FORCE=(--force-with-lease="main:$PUB")
        ok "$PUBLIC_REMOTE/main is the README placeholder; it will be replaced"
    else
        die "$PUBLIC_REMOTE/main is neither an ancestor of main nor the README placeholder. Something real is published there; reconcile it by hand rather than force-pushing over published history."
    fi
else
    ok "$PUBLIC_REMOTE has no main yet (first publication)"
fi

# --- 6c. Nothing intended for this release is stranded on a branch ----------
# Development here is linear: a session works on its own branch and merges into
# main before pushing (docs/WORKFLOW.md). So a branch that is NOT merged into
# main at release time is one of two things -- work in progress that is
# deliberately being left out, or work somebody believed had shipped. The second
# is the expensive one, and it is invisible unless something looks for it.
#
# This lists rather than refuses. Unmerged work is legitimate; publishing
# without having been told about it is what is not. A public release cannot be
# amended afterwards, so the report belongs before the push, not in a postmortem.
UNMERGED_LOCAL="$(git branch --no-merged main --format='%(refname:short)' | grep -v '^main$' || true)"
UNMERGED_REMOTE="$(git branch -r --no-merged main --format='%(refname:short)' \
    | grep -vE "^${PRIVATE_REMOTE}/(main|HEAD)$|^${PUBLIC_REMOTE}/" || true)"

if [ -n "$UNMERGED_LOCAL$UNMERGED_REMOTE" ]; then
    echo
    echo "${YEL}Unmerged branches -- their work is NOT in this release:${RST}"
    for b in $UNMERGED_LOCAL $UNMERGED_REMOTE; do
        AHEAD="$(git rev-list --count "main..$b" 2>/dev/null || echo '?')"
        LAST="$(git log -1 --format='%ar, %s' "$b" 2>/dev/null || true)"
        printf '  %-46s %3s commit(s) ahead   %s\n' "$b" "$AHEAD" "$LAST"
    done
    echo
    echo "  Merge anything that belongs in ${VERSION} first, or confirm it is meant to wait."
    if [ "$DRY_RUN" -eq 0 ]; then
        printf 'Type RELEASE to publish without them: '
        read -r reply
        [ "$reply" = "RELEASE" ] || die "aborted -- nothing was published."
    fi
else
    ok "no unmerged branches; everything is in main"
fi

if [ "$DRY_RUN" -eq 1 ]; then
    echo
    echo "${YEL}--dry-run: every gate passed. Would publish:${RST}"
    echo "  commit  $(git rev-parse --short main)"
    echo "  tag     $TAG"
    echo "  to      $(git remote get-url "$PUBLIC_REMOTE")"
    [ ${#PUBLIC_FORCE[@]} -gt 0 ] \
        && echo "  note    replaces the README placeholder commit on the public remote"
    exit 0
fi

# --- 7. Stamp the citation metadata ---------------------------------------
# CITATION.cff without a version cannot cite a specific release, which is the
# point of tagging one. Updated in place rather than by hand so the tag, the
# CHANGELOG and the citation can never disagree.
TODAY="$(date -u +%Y-%m-%d)"
if grep -q '^version:' CITATION.cff; then
    sed -i -E "s/^version:.*/version: \"${VERSION}\"/" CITATION.cff
else
    printf 'version: "%s"\n' "$VERSION" >> CITATION.cff
fi
if grep -q '^date-released:' CITATION.cff; then
    sed -i -E "s/^date-released:.*/date-released: \"${TODAY}\"/" CITATION.cff
else
    printf 'date-released: "%s"\n' "$TODAY" >> CITATION.cff
fi
ok "CITATION.cff stamped $VERSION ($TODAY)"

# --- 8. Commit, tag, push --------------------------------------------------
git add CITATION.cff
git commit -q -m "Release ${TAG}" || die "nothing to commit for the release stamp"
git tag -a "$TAG" -m "NexusQC ${VERSION}"
ok "committed and tagged $TAG"

git push --quiet "$PRIVATE_REMOTE" main --follow-tags || die "push to $PRIVATE_REMOTE failed"
ok "pushed to $PRIVATE_REMOTE"

git push --quiet ${PUBLIC_FORCE[@]+"${PUBLIC_FORCE[@]}"} \
    "$PUBLIC_REMOTE" main --follow-tags || die "push to $PUBLIC_REMOTE failed"
ok "pushed to $PUBLIC_REMOTE"

echo
echo "${GRN}published ${TAG}${RST} -> $(git remote get-url "$PUBLIC_REMOTE")"
echo "${DIM}Start a new '## [Unreleased]' section in CHANGELOG.md for the next one.${RST}"
