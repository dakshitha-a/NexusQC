#!/usr/bin/env bash
#
# Refuse to let host-specific or secret material reach the public repository.
#
# This exists because "remember to sanitise before pushing" is not a mechanism.
# It is a wish. The same reasoning this project applies elsewhere -- gate the
# thing that matters in code, not in a prompt or a checklist -- applies here:
# a leaked absolute path or credential cannot be un-published, so the check
# runs mechanically on every push via scripts/hooks/pre-push.
#
# Usage:
#   scripts/check_public_safe.sh                  # scan tracked files
#   scripts/check_public_safe.sh --staged         # scan only staged changes
#   scripts/check_public_safe.sh --range A..B     # scan content introduced by
#                                                 # the commits in a range
#
# Exit status: 0 clean, 1 findings, 2 usage/environment error.

set -uo pipefail

RED=$'\033[31m'; YEL=$'\033[33m'; GRN=$'\033[32m'; DIM=$'\033[2m'; RST=$'\033[0m'
if [ ! -t 1 ]; then RED=''; YEL=''; GRN=''; DIM=''; RST=''; fi

cd "$(git rev-parse --show-toplevel)" || {
    echo "not inside a git repository" >&2; exit 2; }

MODE="tracked"
RANGE=""
case "${1:-}" in
    --staged) MODE="staged" ;;
    --range)  MODE="range"; RANGE="${2:-}"
              [ -n "$RANGE" ] || { echo "usage: $0 --range <base>..<head>" >&2; exit 2; } ;;
    "")       ;;
    *)        echo "usage: $0 [--staged | --range <base>..<head>]" >&2; exit 2 ;;
esac

# Files this scanner must not flag itself on: it necessarily contains the
# very patterns it looks for, as does the example env file and the docs that
# explain the policy.
SELF_EXCLUDE_RE='(^|/)(scripts/check_public_safe\.sh|scripts/hooks/pre-push)$'

# --- Range mode -------------------------------------------------------------
# Why this exists at all: a working-tree scan cannot see a leak that was
# committed and then removed in a later commit. The tree is clean, the scan
# passes, and the secret sits in history forever -- which is precisely the
# situation this repository had to spend a history rewrite to fix once.
#
# So for a push, scan the CONTENT INTRODUCED BY THE COMMITS BEING PUSHED, not
# the checkout. Each touched path is materialised at the version that commit
# introduced, under <short-sha>/<path> in a temp tree, so a finding names the
# commit that carries it and not just the file.
if [ "$MODE" = "range" ]; then
    # $RANGE reaches git UNQUOTED, deliberately. The hook passes a two-dot
    # "<base>..<head>" for an ordinary push, but a multi-word revision list
    # ("<head> --not --remotes") for a first push to a remote that has never
    # seen this branch. Quoting it makes git read the whole string as a single
    # revision name, which cannot resolve.
    #
    # Both of the following used to end here as "nothing to scan" and exit 0 --
    # the scan announcing success having examined no content at all:
    #   - the multi-word form, quoted (git exits 128)
    #   - a base sha absent from the local object store, which is the normal
    #     case for a force-push after a history rewrite, because every sha
    #     changed and the old objects were repacked away
    # Those are the two pushes that matter most: publishing to a fresh remote,
    # and replacing a rewritten history. So resolve the range FIRST and treat an
    # unresolvable one as a hard error. A range that resolves to no commits is a
    # different thing and is genuinely fine.
    # shellcheck disable=SC2086
    if ! git rev-list --max-count=1 $RANGE >/dev/null 2>&1; then
        echo "${RED}cannot resolve commit range:${RST} $RANGE" >&2
        echo "Refusing to report a pass on an unscanned range. If the base sha" >&2
        echo "is unknown locally (force-push after a rewrite), scan the pushed" >&2
        echo "commits instead:  $0 --range '<head> --not --remotes'" >&2
        exit 2
    fi
    SCAN_ROOT="$(mktemp -d)"
    trap 'rm -rf "$SCAN_ROOT"' EXIT
    while read -r commit; do
        [ -n "$commit" ] || continue
        short="$(git rev-parse --short "$commit")"
        while read -r path; do
            [ -n "$path" ] || continue
            dest="$SCAN_ROOT/$short/$path"
            mkdir -p "$(dirname "$dest")"
            # Deleted paths simply produce nothing; that is correct, there is
            # no introduced content to scan.
            git show "$commit:$path" > "$dest" 2>/dev/null || rm -f "$dest"
        done < <(git diff-tree --no-commit-id --name-only -r --diff-filter=AM "$commit")
    # shellcheck disable=SC2086
    done < <(git rev-list $RANGE)
    cd "$SCAN_ROOT" || { echo "could not enter scan tree" >&2; exit 2; }
    mapfile -t FILES < <(find . -type f -printf '%P\n' 2>/dev/null)
elif [ "$MODE" = "staged" ]; then
    mapfile -t FILES < <(git diff --cached --name-only --diff-filter=ACM)
else
    mapfile -t FILES < <(git ls-files)
fi

# Drop deleted/absent files and this script itself.
SCAN=()
for f in "${FILES[@]:-}"; do
    [ -n "$f" ] || continue
    [ -f "$f" ] || continue
    [[ "$f" =~ $SELF_EXCLUDE_RE ]] && continue
    SCAN+=("$f")
done

if [ ${#SCAN[@]} -eq 0 ]; then
    # Reachable in range mode only once the range has been proven resolvable
    # above, so this is the honest "these commits introduced no scannable file"
    # case (a merge, or deletions only) rather than a range that failed to parse.
    if [ "$MODE" = "range" ]; then
        echo "${GRN}nothing to scan${RST} ${DIM}(range resolved; no files introduced)${RST}"
    else
        echo "${GRN}nothing to scan${RST}"
    fi
    exit 0
fi

FINDINGS=0

# report <severity> <label> <grep-output>
report() {
    local sev="$1" label="$2" hits="$3" colour="$RED"
    [ "$sev" = "warn" ] && colour="$YEL"
    [ -z "$hits" ] && return 0
    echo "${colour}[${sev}]${RST} ${label}"
    printf '%s\n' "$hits" | sed 's/^/    /'
    echo
    [ "$sev" = "warn" ] || FINDINGS=$((FINDINGS + 1))
    return 0
}

scan() {  # scan <severity> <label> <extended-regex>
    local hits
    hits="$(grep -HnEI "$3" "${SCAN[@]}" 2>/dev/null | head -25)"
    report "$1" "$2" "$hits"
}

echo "${DIM}scanning ${#SCAN[@]} files (${MODE})${RST}"
echo

# --- 1. Home/user-scoped absolute paths -------------------------------------
# /home/<user> and /data/<user> identify both the machine and the operator.
# /root is included because it is equally host-specific.
#
# REDACTION_PLACEHOLDERS is load-bearing in the same way the bracket in pattern
# 2 is, and for a related reason. This repository's history was rewritten once
# to replace the operator's real home and data paths with a fictional account
# name, so historical commits legitimately contain /home/<placeholder> and
# /data/<placeholder>. That is the OUTPUT of the scrub, not a leak: the real
# name is gone and the placeholder describes no machine. Exempting it is what
# keeps --range mode usable against the rewritten history at all. Do not remove
# this as a stray special case, and do not widen it -- every other username,
# including any real one, still fails.
REDACTION_PLACEHOLDERS='/(home|data)/qcuser([^a-z0-9_-]|$)'
HOME_HITS="$(grep -HnEI '(/home/[a-z_][a-z0-9_-]*|/root/|/Users/[A-Za-z])' \
    "${SCAN[@]}" 2>/dev/null \
    | grep -vE "$REDACTION_PLACEHOLDERS" | head -25)"
report fail "home- or user-scoped absolute path" "$HOME_HITS"

# --- 2. Site-specific software trees ----------------------------------------
# This project was developed against engines installed under /software. Any
# such path is meaningless to anyone else and identifies the lab host.
# The bracket around the first letter is deliberate and load-bearing. This
# pattern is the literal string it hunts for, so a history-redaction pass over
# this repository rewrites the DETECTOR itself -- which is exactly what happened
# the first time: the pattern itself was rewritten to '/opt/' here and the
# check silently stopped catching anything. A one-character class matches identically and cannot be
# rewritten by a literal find-and-replace. Same reasoning applies to any future
# pattern here that names a real path or host.
scan fail "site-specific install path" \
    '/[s]oftware/'

# --- 2b. The operator's username, in prose ----------------------------------
# Pattern 1 only catches a username inside a path. It sails straight past the
# same name written in a sentence -- "appears as <user> on the host" -- which
# is exactly how it tends to end up in documentation. Derive the name rather
# than hardcoding it, so this keeps working for anyone who forks this.
#
# The repository URL legitimately contains the owner's account name, so lines
# that are just a github.com reference are not findings. Set
# NEXUSQC_SCAN_EXTRA_TERMS to a |-separated list to add site-specific words
# (a group name, a cluster name).
WHOAMI="$(id -un 2>/dev/null || true)"
TERMS=""
# Skip generic account names that would match half the repo.
case "$WHOAMI" in
    ""|root|ubuntu|admin|user|app|runner|node) ;;
    *) TERMS="$WHOAMI" ;;
esac
if [ -n "${NEXUSQC_SCAN_EXTRA_TERMS:-}" ]; then
    TERMS="${TERMS:+$TERMS|}${NEXUSQC_SCAN_EXTRA_TERMS}"
fi
if [ -n "$TERMS" ]; then
    USER_HITS="$(grep -HnEI "(${TERMS})" "${SCAN[@]}" 2>/dev/null \
        | grep -vE 'github\.com/' | head -25)"
    report fail "operator username in file content" "$USER_HITS"
fi

# --- 3. Credentials and key material ----------------------------------------
scan fail "private key material" \
    '(BEGIN (RSA |EC |OPENSSH |DSA |PGP )?PRIVATE KEY|BEGIN CERTIFICATE)'

# A real secret assigned inline, as opposed to read from the environment or
# left as a placeholder. Deliberately narrow: this must not fire on
# os.environ.get(...), ${VAR:?...} interpolation, or `change-me` examples.
scan fail "hardcoded credential" \
    '^[^#]*(password|passwd|secret|api[_-]?key|token)[[:space:]]*[:=][[:space:]]*["'"'"'][A-Za-z0-9/+_-]{12,}["'"'"']'

# --- 4. Network identifiers -------------------------------------------------
# Loopback, wildcard, private (RFC1918), link-local, multicast and broadcast
# addresses are all fine and appear legitimately throughout this repo -- a
# check that flags them is noise nobody reads. Only a routable literal is
# worth a look.
# 100.64/10 is RFC6598 shared address space -- the CGNAT range tailnets use.
# Not publicly routable, and this repo's nginx allowlist legitimately names it.
# 192.0.2/24, 198.51.100/24 and 203.0.113/24 are the RFC5737 documentation
# ranges. They are reserved specifically so they can never resolve to a real
# host, which is why the one-time history scrub used them as the replacements
# for this host's real addresses. A hit on one of them is a placeholder.
IP_SAFE_RE='(127\.|0\.0\.0\.0|10\.|192\.168\.|192\.0\.2\.|198\.51\.100\.|203\.0\.113\.|169\.254\.|100\.(6[4-9]|[7-9][0-9]|1[01][0-9]|12[0-7])\.|172\.(1[6-9]|2[0-9]|3[01])\.|22[4-9]\.|23[0-9]\.|255\.255)'
# Match and filter each ADDRESS, not each line. Filtering whole lines through
# IP_SAFE_RE was a real false negative: one comment here read
# "...the tailnet (100.x.x.x), and a public address (129.x.x.x) -- binding
# 0.0.0.0 would..." and the literal 0.0.0.0 later in the same line marked the
# whole line safe, hiding a genuine institution-routable address from the scan.
# grep -o emits "file:line:address", so the address is the last field.
IP_HITS="$(grep -HonEI '((25[0-5]|2[0-4][0-9]|1?[0-9]{1,2})\.){3}(25[0-5]|2[0-4][0-9]|1?[0-9]{1,2})' \
    "${SCAN[@]}" 2>/dev/null | grep -vE ":${IP_SAFE_RE}" | head -25)"
report warn "possible routable IP literal" "$IP_HITS"

# --- 4b. Institutional hostnames --------------------------------------------
# A host FQDN identifies the machine as precisely as an IP does, and pattern 1
# never sees it because it is not a path. This project's own leak was a bare
# `server_name <machine>.<institution>.edu` in nginx.conf and a matching
# default in the certificate script.
#
# Deliberately narrow, in three ways, because the obvious broad version was
# tried first and was pure noise:
#   - academic domains only, not a general hostname pattern (this repo
#     legitimately cites github.com, pyscf.org, basissetexchange.org, ...)
#   - never an email address. The authors' own contact addresses in
#     CITATION.cff and README.md are deliberately published, not leaked.
#   - never inside a URL. Third-party endpoints the code really calls
#     (OPSIN at cam.ac.uk) and credits (3Dmol at pitt.edu) are legitimate.
# What survives all three is a bare institutional hostname sitting in a
# config or a script, which is the thing worth blocking.
FQDN_HITS="$(grep -HnEI '(^|[^@/.[:alnum:]-])[a-z0-9][a-z0-9-]*(\.[a-z0-9-]+)*\.(edu|ac\.[a-z]{2})\b' \
    "${SCAN[@]}" 2>/dev/null \
    | grep -vE '@[a-z0-9.-]*\.(edu|ac\.[a-z]{2})' \
    | grep -vE '://' \
    | grep -vE '(yourlab\.edu|example|your-?institution|<[^>]*>)' | head -25)"
report fail "bare institutional hostname (identifies the host as precisely as an IP)" "$FQDN_HITS"

# --- 5. Files that must never be tracked ------------------------------------
FORBIDDEN="$(printf '%s\n' "${SCAN[@]}" | grep -E \
    '(^|/)(\.env|\.env\.[a-z]+|CLAUDE\.local\.md|docker-compose\.override\.yml|\.admin_creds|.*\.pem|.*\.key|.*\.p12|.*\.pfx|id_rsa.*)$' \
    | grep -v '\.env\.example$')"
report fail "file that must not be committed" "$FORBIDDEN"

# --- 6. Raw machine output --------------------------------------------------
# (^|/) rather than ^: in --range mode paths are prefixed with the short sha
# of the commit that introduced them, so an anchored ^ would match nothing.
#
# This one blocks the working tree but only warns about history, and the
# distinction is deliberate. The rules above it catch permanent leaks -- a host
# identifier or a key, once pushed, is public forever no matter what a later
# commit does, so they must stay blocking in --range mode. This rule is
# hygiene: it is about what the repository SHIPS, and it is satisfied by not
# tracking the files now. Applied to immutable history it becomes a gate that
# no amount of work can pass, because the only remedy is another full rewrite.
# An unsatisfiable gate does not get satisfied, it gets --no-verify'd, and then
# the rules that do matter stop running too. Warn, so it stays visible.
RESULTS="$(printf '%s\n' "${SCAN[@]}" | grep -E '(^|/)tests/e2e/results/.*\.jsonl$')"
if [ "$MODE" = "range" ]; then
    report warn "raw test-run data in history (regenerable; not a leak)" "$RESULTS"
else
    report fail "raw test-run data (regenerated; not source)" "$RESULTS"
fi

echo
if [ "$FINDINGS" -eq 0 ]; then
    echo "${GRN}PASS${RST} - nothing blocking found in ${#SCAN[@]} files."
    echo "${DIM}Warnings above, if any, are advisory: check them, then push.${RST}"
    exit 0
fi

echo "${RED}FAIL${RST} - ${FINDINGS} blocking category/categories above."
cat <<'EOF'

This repository is public. Anything pushed is public permanently, including
in the commit history, even if a later commit removes it.

If a finding is a false positive, narrow the pattern in
scripts/check_public_safe.sh rather than skipping the check. To bypass once
(you had better be sure):

    git push --no-verify
EOF
exit 1
