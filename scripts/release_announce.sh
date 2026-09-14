#!/usr/bin/env bash
# Tell the public repository that a release happened.
#
# WHY THIS IS SEPARATE FROM release.sh
# ------------------------------------
# release.sh is a sequence of refusals ending in one irreversible push. This
# script is what comes after that push, and nothing here may be allowed to
# turn a successful publication into a reported failure: the tag is public
# whether or not GitHub accepted a release note, and a reporter's issue stays
# open, not lost, if a comment could not be posted. So release.sh calls this
# and continues regardless, this script continues past any single failure,
# and every failure ends with the one line that repairs it: re-run this script
# with the same version. Every step is idempotent for exactly that reason.
#
# WHAT IT DOES
# ------------
# 1. Creates the GitHub release for the tag, with the CHANGELOG section as
#    its notes. GitHub caps release notes at 125,000 characters and this
#    project's first section was longer than that, so notes over the cap are
#    cut at a paragraph boundary with a link to the full section at the tag.
# 2. Finds every public issue and pull request the released commits
#    reference. The reference is the `Refs: owner/repo#n` trailer that
#    .claude/skills/issue/SKILL.md has every fix carry, matched against the
#    public repository's own owner/repo, so a `NexusQC-dev#n` can never be
#    mistaken for a public one.
# 3. Comments "Released in vX.Y.Z" on each, removes `fixed-on-main`, and
#    closes it. This is where a public issue is closed, and nowhere else:
#    CONTRIBUTING.md defines "closed" as "you can install the fix", and this
#    is the moment that becomes true.
#
# It also warns about a closing keyword (Fixes #n, Closes owner/repo#n) in
# any released commit, because the public push replays every commit message
# and GitHub would close that issue itself, without the comment that names
# the version. release.sh --dry-run shows the warning before anything is
# pushed.
#
# Usage:
#   scripts/release_announce.sh <version>              after release.sh pushed
#   scripts/release_announce.sh <version> --dry-run    print the plan, change nothing
#
# The functions are at column zero and `main` runs only when the file is
# executed, so tests/backend/deploy_08_release_announce.py can source them.
set -uo pipefail

RED=$'\033[31m'; GRN=$'\033[32m'; YEL=$'\033[33m'; DIM=$'\033[2m'; RST=$'\033[0m'
if [ ! -t 1 ]; then RED=''; GRN=''; YEL=''; DIM=''; RST=''; fi
ok()   { echo "${GRN}  ok${RST}  $*"; }
warn() { echo "${YEL}  !!${RST}  $*"; }
note() { echo "${DIM}  ..${RST}  $*"; }

PUBLIC_REMOTE="${QC_AGENT_PUBLIC_REMOTE:-public}"
# GitHub's documented limit on a release body; the cut is below it so the
# link that replaces the tail fits too.
NOTES_LIMIT_BYTES=125000
NOTES_KEEP_BYTES=100000

# owner/name of the public repository, from the remote's URL.
public_slug() {
    git remote get-url "$PUBLIC_REMOTE" 2>/dev/null \
        | sed -E 's#^.*github\.com[:/]##; s#\.git$##; s#/$##'
}

# The release tag before <tag>, or nothing when this is the first.
#
# `--exclude "$TAG"` is what makes this right both before and after the live
# release: during --dry-run the tag does not exist yet and the exclude is
# inert; after release.sh has tagged HEAD, describe would otherwise answer
# with the new tag itself, the range would be empty, and no issue would be
# closed. A tag that is not shaped like a release (--match) is never the
# previous one either.
previous_version_tag() {
    local tag="$1"
    git describe --tags --abbrev=0 --match 'v[0-9]*' --exclude "$tag" HEAD 2>/dev/null || true
}

# The commits this release carries: everything since the previous release
# tag, or all of HEAD for the first. Always relative to HEAD, never to the
# new tag, so dry-run (before the tag) and live (after) compute the same set.
release_range() {
    local prev="$1"
    if [ -n "$prev" ]; then echo "${prev}..HEAD"; else echo "HEAD"; fi
}

# Issue and pull-request numbers referenced as owner/repo#n in the range's
# commit messages, one per line, ascending, deduplicated. The slug is the
# public repository's own, escaped for grep, so only public references count.
referenced_issues() {
    local slug="$1" range="$2" slug_re
    slug_re="$(printf '%s' "$slug" | sed -E 's/[.\/]/\\&/g')"
    git log --format=%B "$range" 2>/dev/null \
        | grep -oE "${slug_re}#[0-9]+" \
        | grep -oE '[0-9]+$' \
        | sort -un
}

# Commit subjects in the range that carry a GitHub closing keyword. Warn-only:
# these cannot be fixed after the fact, but a dry run shows them before the
# push, and a session can reword the commit.
closing_keywords_in_range() {
    local range="$1"
    git log --format='%h %s%n%b' "$range" 2>/dev/null \
        | grep -iE '\b(close|closes|closed|fix|fixes|fixed|resolve|resolves|resolved)[[:space:]:]+([A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+)?#[0-9]+' \
        || true
}

# The CHANGELOG section for <version>: from its heading to the next version
# heading, heading included. Empty when there is no such section.
changelog_section() {
    local version="$1"
    awk -v ver="$version" '
        $0 ~ "^## \\[" ver "\\]" { on = 1; print; next }
        on && /^## \[/ { exit }
        on { print }
    ' CHANGELOG.md
}

# Release notes that fit: the section, or its head cut at a blank line before
# NOTES_KEEP_BYTES plus a link to the whole thing at the tag. Prints the
# notes on stdout and the byte count on stderr, so a dry run can say what it
# would send.
release_notes() {
    local version="$1" slug="$2" tag="v$1" section size
    section="$(changelog_section "$version")"
    size="$(printf '%s' "$section" | wc -c)"
    if [ "$size" -le "$NOTES_LIMIT_BYTES" ]; then
        printf '%s\n' "$section"
        echo "$size" >&2
        return 0
    fi
    # Keep whole paragraphs: cut at the last blank line inside the budget.
    printf '%s\n' "$section" | head -c "$NOTES_KEEP_BYTES" | awk '
        { lines[NR] = $0; if ($0 == "") last = NR }
        END { for (i = 1; i < (last ? last : NR); i++) print lines[i] }'
    printf '\n---\n\nThese notes are cut at %d KB; the full section is in [CHANGELOG.md at %s](https://github.com/%s/blob/%s/CHANGELOG.md).\n' \
        $((NOTES_KEEP_BYTES / 1000)) "$tag" "$slug" "$tag"
    echo "$size" >&2
}

# Whether <n> on the public repository is a pull request rather than an
# issue: the same number space, different commands to comment on and close.
is_pull_request() {
    local slug="$1" n="$2" url
    url="$(gh api "repos/$slug/issues/$n" --jq '.pull_request.html_url // empty' 2>/dev/null)" || return 1
    [ -n "$url" ]
}

# --- main ------------------------------------------------------------------
main() {
    local version="${1:-}" dry_run=0
    [ "${2:-}" = "--dry-run" ] && dry_run=1
    [ -n "$version" ] || { echo "usage: $0 <version> [--dry-run]" >&2; return 2; }
    [[ "$version" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]] \
        || { echo "version must be MAJOR.MINOR.PATCH (got '$version')" >&2; return 2; }
    local tag="v$version" slug prev range issues keywords notes size failed=0
    cd "$(git rev-parse --show-toplevel)" || return 2
    slug="$(public_slug)"
    [ -n "$slug" ] || { echo "no '$PUBLIC_REMOTE' remote; nothing to announce to" >&2; return 2; }
    command -v gh >/dev/null 2>&1 || { echo "the gh CLI is not installed; re-run this once it is: $0 $version" >&2; return 2; }

    prev="$(previous_version_tag "$tag")"
    range="$(release_range "$prev")"
    issues="$(referenced_issues "$slug" "$range")"
    keywords="$(closing_keywords_in_range "$range")"
    notes="$(release_notes "$version" "$slug" 2>/tmp/release_notes_size.$$)"
    size="$(cat /tmp/release_notes_size.$$ 2>/dev/null || echo 0)"; rm -f /tmp/release_notes_size.$$

    echo "${DIM}announcing ${tag} on ${slug}${RST}"
    if [ -n "$prev" ]; then
        note "commits since $prev ($(git rev-list --count "$range") of them)"
    else
        note "first release: every commit on main ($(git rev-list --count HEAD))"
    fi
    if [ "$size" -eq 0 ]; then
        warn "CHANGELOG.md has no '## [$version]' section; the release would have no notes"
    elif [ "$size" -gt "$NOTES_LIMIT_BYTES" ]; then
        note "release notes: CHANGELOG section is ${size} bytes, over GitHub's ${NOTES_LIMIT_BYTES}; sending the first ${NOTES_KEEP_BYTES} with a link to the rest"
    else
        note "release notes: the CHANGELOG section, ${size} bytes"
    fi
    if [ -n "$issues" ]; then
        note "issues and pull requests to close: $(printf '#%s ' $issues)"
    else
        note "no public issues referenced in these commits"
    fi
    if [ -n "$keywords" ]; then
        warn "closing keywords in released commits; GitHub will act on these itself when the public push lands:"
        printf '%s\n' "$keywords" | sed 's/^/        /'
    fi

    if [ "$dry_run" -eq 1 ]; then
        echo "${YEL}--dry-run: nothing announced.${RST}"
        return 0
    fi

    # 0. The labels the steps below remove must exist to be removable.
    ./scripts/issues.sh ensure-labels >/dev/null 2>&1 || warn "could not ensure labels on $slug (continuing)"

    # 1. The release object. Skipped when it already exists, so a re-run
    #    after a partial failure does not try to create it twice.
    if gh release view "$tag" -R "$slug" >/dev/null 2>&1; then
        ok "release $tag already exists on $slug"
    else
        local notes_file
        notes_file="$(mktemp)"
        printf '%s\n' "$notes" > "$notes_file"
        if gh release create "$tag" -R "$slug" --verify-tag --title "NexusQC $version" --notes-file "$notes_file" >/dev/null; then
            ok "created release $tag"
        else
            warn "could not create release $tag"; failed=1
        fi
        rm -f "$notes_file"
    fi
    local release_url="https://github.com/$slug/releases/tag/$tag"
    local phrase="Released in $tag"

    # 2. Each referenced issue or pull request: comment once, drop the label,
    #    close. Every step checks before it acts, so a re-run repeats nothing.
    local n kind
    for n in $issues; do
        if is_pull_request "$slug" "$n"; then kind=pr; else kind=issue; fi
        if gh api "repos/$slug/issues/$n/comments" --paginate --jq '.[].body' 2>/dev/null | grep -qF "$phrase"; then
            note "#$n: already has the release comment"
        elif gh "$kind" comment "$n" -R "$slug" --body "$phrase: $release_url" >/dev/null; then
            ok "#$n: commented"
        else
            warn "#$n: could not comment"; failed=1; continue
        fi
        gh "$kind" edit "$n" -R "$slug" --remove-label fixed-on-main >/dev/null 2>&1 || true
        if [ "$(gh api "repos/$slug/issues/$n" --jq .state 2>/dev/null)" = "closed" ]; then
            note "#$n: already closed"
        elif gh "$kind" close "$n" -R "$slug" >/dev/null; then
            ok "#$n: closed"
        else
            warn "#$n: could not close"; failed=1
        fi
    done

    if [ "$failed" -ne 0 ]; then
        echo "${RED}some announcements failed; publication itself is done. Re-run: scripts/release_announce.sh $version${RST}" >&2
        return 1
    fi
    ok "announced $tag on $slug"
}

if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
    main "$@"
fi
