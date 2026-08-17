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
#   scripts/check_public_safe.sh          # scan tracked files
#   scripts/check_public_safe.sh --staged # scan only staged changes
#
# Exit status: 0 clean, 1 findings, 2 usage/environment error.

set -uo pipefail

RED=$'\033[31m'; YEL=$'\033[33m'; GRN=$'\033[32m'; DIM=$'\033[2m'; RST=$'\033[0m'
if [ ! -t 1 ]; then RED=''; YEL=''; GRN=''; DIM=''; RST=''; fi

cd "$(git rev-parse --show-toplevel)" || {
    echo "not inside a git repository" >&2; exit 2; }

MODE="tracked"
case "${1:-}" in
    --staged) MODE="staged" ;;
    "")       ;;
    *)        echo "usage: $0 [--staged]" >&2; exit 2 ;;
esac

# Files this scanner must not flag itself on: it necessarily contains the
# very patterns it looks for, as does the example env file and the docs that
# explain the policy.
SELF_EXCLUDE_RE='^(scripts/check_public_safe\.sh|scripts/hooks/pre-push)$'

if [ "$MODE" = "staged" ]; then
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
    echo "${GRN}nothing to scan${RST}"; exit 0
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
    hits="$(grep -nEI "$3" "${SCAN[@]}" 2>/dev/null | head -25)"
    report "$1" "$2" "$hits"
}

echo "${DIM}scanning ${#SCAN[@]} files (${MODE})${RST}"
echo

# --- 1. Home/user-scoped absolute paths -------------------------------------
# /home/<user> and /data/<user> identify both the machine and the operator.
# /root is included because it is equally host-specific.
scan fail "home- or user-scoped absolute path" \
    '(/home/[a-z_][a-z0-9_-]*|/root/|/Users/[A-Za-z])'

# --- 2. Site-specific software trees ----------------------------------------
# This project was developed against engines installed under /software. Any
# such path is meaningless to anyone else and identifies the lab host.
scan fail "site-specific install path" \
    '/opt/'

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
    USER_HITS="$(grep -nEI "(${TERMS})" "${SCAN[@]}" 2>/dev/null \
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
IP_SAFE_RE='(127\.|0\.0\.0\.0|10\.|192\.168\.|169\.254\.|172\.(1[6-9]|2[0-9]|3[01])\.|22[4-9]\.|23[0-9]\.|255\.255)'
IP_HITS="$(grep -nEI '(^|[^0-9.])((25[0-5]|2[0-4][0-9]|1?[0-9]{1,2})\.){3}(25[0-5]|2[0-4][0-9]|1?[0-9]{1,2})([^0-9.]|$)' \
    "${SCAN[@]}" 2>/dev/null | grep -vE "$IP_SAFE_RE" | head -25)"
report warn "possible routable IP literal" "$IP_HITS"

# --- 5. Files that must never be tracked ------------------------------------
FORBIDDEN="$(printf '%s\n' "${SCAN[@]}" | grep -E \
    '(^|/)(\.env|\.env\.[a-z]+|CLAUDE\.local\.md|docker-compose\.override\.yml|\.admin_creds|.*\.pem|.*\.key|.*\.p12|.*\.pfx|id_rsa.*)$' \
    | grep -v '\.env\.example$')"
report fail "file that must not be committed" "$FORBIDDEN"

# --- 6. Raw machine output --------------------------------------------------
RESULTS="$(printf '%s\n' "${SCAN[@]}" | grep -E '^tests/e2e/results/.*\.jsonl$')"
report fail "raw test-run data (regenerated; not source)" "$RESULTS"

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
