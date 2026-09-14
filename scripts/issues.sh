#!/usr/bin/env bash
# The public issue tracker, from a session in the development repository.
#
# WHY THIS EXISTS
# ---------------
# Users report bugs and ask for features on the PUBLIC repository, and the
# work happens on the PRIVATE one, which they cannot see. What they can see is
# the issue: its labels and its comments are the whole of the state visible
# to a reporter, so they are kept current mechanically rather than from
# memory. This script is the one place that vocabulary is written down --
# which label means what, what the comment at each step says -- so a session
# runs `issues.sh fixed 12` and the reporter reads the same sentence every
# time. `.claude/skills/issue/SKILL.md` drives it; CONTRIBUTING.md explains
# it to the reporter.
#
# The public repository is whichever one the `public` remote points at
# (docs/DEVELOPMENT.md), so a fork with its own remotes works unchanged. Every
# gh call names the repository explicitly: with two remotes gh cannot infer
# it, and guessing wrong would file comments on the private repository, which
# no reporter can read.
#
# Nothing here closes an issue. Closing happens at release, from
# scripts/release_announce.sh, because "closed" is defined to mean "you can
# install the fix" (CONTRIBUTING.md), and a fix on the development branch is
# not that yet.
#
# Usage:
#   scripts/issues.sh list [--all] [--label <name>]   open issues, triage first
#   scripts/issues.sh show <n>                        the issue and its comments
#   scripts/issues.sh new "<title>" [--feature]       file a maintainer-originated issue
#   scripts/issues.sh fixed <n>                       comment + triage -> fixed-on-main
#   scripts/issues.sh needs-info <n> "<question>"     comment + triage -> needs-info
#   scripts/issues.sh ensure-labels                   create the project labels (idempotent)
set -euo pipefail

RED=$'\033[31m'; GRN=$'\033[32m'; DIM=$'\033[2m'; RST=$'\033[0m'
if [ ! -t 1 ]; then RED=''; GRN=''; DIM=''; RST=''; fi
die() { echo "${RED}issues: $*${RST}" >&2; exit 1; }
ok()  { echo "${GRN}  ok${RST}  $*"; }

cd "$(git rev-parse --show-toplevel)" || die "not inside a git repository"
command -v gh >/dev/null 2>&1 || die "the gh CLI is not installed (https://cli.github.com)"

PUBLIC_REMOTE="${QC_AGENT_PUBLIC_REMOTE:-public}"
# owner/name from the remote URL, whichever way it was written.
public_slug() {
    local url
    url="$(git remote get-url "$PUBLIC_REMOTE" 2>/dev/null)" \
        || die "no '$PUBLIC_REMOTE' remote; see docs/DEVELOPMENT.md"
    printf '%s\n' "$url" | sed -E 's#^.*github\.com[:/]##; s#\.git$##; s#/$##'
}
SLUG="$(public_slug)"

# The label vocabulary. Colours are GitHub's six-hex form without the '#'.
# --force makes create idempotent: an existing label is updated in place, so
# running this twice is safe and a description edited here reaches GitHub on
# the next run.
ensure_labels() {
    gh label create triage -R "$SLUG" --force \
        --color e4c441 --description "Filed, not yet looked at" >/dev/null
    gh label create needs-info -R "$SLUG" --force \
        --color bfbfbf --description "Could not be reproduced from what is here; the question is in the comments" >/dev/null
    gh label create fixed-on-main -R "$SLUG" --force \
        --color 0e8a16 --description "Fixed on the development branch; ships in the next release" >/dev/null
    ok "labels triage, needs-info, fixed-on-main exist on $SLUG"
}

# A number that is a number, so a typo cannot address the wrong issue.
require_number() {
    [[ "${1:-}" =~ ^[0-9]+$ ]] || die "expected an issue number, got '${1:-}'"
}

cmd="${1:-}"; shift || true
case "$cmd" in
    list)
        state=open; label=""
        while [ $# -gt 0 ]; do
            case "$1" in
                --all) state=all ;;
                --label) label="${2:-}"; shift ;;
                *) die "unknown option '$1'" ;;
            esac
            shift
        done
        args=(-R "$SLUG" --state "$state" --limit 200
              --json number,title,labels,createdAt,author)
        [ -n "$label" ] && args+=(--label "$label")
        # triage first, then the rest, each oldest first: the queue reads top
        # to bottom. `gh --jq` rather than jq, which is not installed here.
        gh issue list "${args[@]}" --jq '
            def line: "#\(.number)\t\(.createdAt[:10])\t\(.author.login)\t[\([.labels[].name] | join(","))]\t\(.title)";
            (map(select(any(.labels[]; .name == "triage"))) | sort_by(.createdAt) | .[] | line),
            (map(select(all(.labels[]; .name != "triage"))) | sort_by(.createdAt) | .[] | line)' \
        | column -t -s $'\t'
        ;;
    show)
        require_number "${1:-}"
        gh issue view "$1" -R "$SLUG" --comments
        ;;
    new)
        title="${1:-}"; [ -n "$title" ] || die "usage: issues.sh new \"<title>\" [--feature]"
        label=bug; [ "${2:-}" = "--feature" ] && label=enhancement
        # Filed by the maintainer, so it is not acknowledged by the intake
        # workflow (which skips the repository owner) and gets `triage` here
        # instead, so the queue still shows it.
        url="$(gh issue create -R "$SLUG" --title "$title" --label "$label,triage" \
            --body "Filed from a development session so the planned work is visible here. Details and the fix follow in this thread.")"
        ok "filed $url"
        ;;
    fixed)
        require_number "${1:-}"
        gh issue comment "$1" -R "$SLUG" --body "Fixed on the development branch. It ships in the next release, and this issue is closed with the version number when it does, so \"closed\" means the fix is installable."
        gh issue edit "$1" -R "$SLUG" --remove-label triage --remove-label needs-info --add-label fixed-on-main >/dev/null
        ok "#$1: commented; labels now fixed-on-main"
        ;;
    needs-info)
        require_number "${1:-}"
        [ -n "${2:-}" ] || die "usage: issues.sh needs-info <n> \"<question>\""
        gh issue comment "$1" -R "$SLUG" --body "$2"
        gh issue edit "$1" -R "$SLUG" --remove-label triage --add-label needs-info >/dev/null
        ok "#$1: asked; labels now needs-info"
        ;;
    ensure-labels)
        ensure_labels
        ;;
    *)
        sed -n '/^# Usage:/,/^set -euo/p' "$0" | sed '$d' | sed 's/^# \{0,1\}//'
        exit 2
        ;;
esac
