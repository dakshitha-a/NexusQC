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
# 100.64/10 is RFC6598 shared address space -- the CGNAT range tailnets use.
# Not publicly routable, and this repo's nginx allowlist legitimately names it.
IP_SAFE_RE='(127\.|0\.0\.0\.0|10\.|192\.168\.|169\.254\.|100\.(6[4-9]|[7-9][0-9]|1[01][0-9]|12[0-7])\.|172\.(1[6-9]|2[0-9]|3[01])\.|22[4-9]\.|23[0-9]\.|255\.255)'
# Match and filter each ADDRESS, not each line. Filtering whole lines through
# IP_SAFE_RE was a real false negative: one comment here read
# "...the tailnet (100.x.x.x), and a public address (129.x.x.x) -- binding
# 0.0.0.0 would..." and the literal 0.0.0.0 later in the same line marked the
# whole line safe, hiding a genuine institution-routable address from the scan.
# grep -o emits "file:line:address", so the address is the last field.
IP_HITS="$(grep -onEI '((25[0-5]|2[0-4][0-9]|1?[0-9]{1,2})\.){3}(25[0-5]|2[0-4][0-9]|1?[0-9]{1,2})' \
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
FQDN_HITS="$(grep -nEI '(^|[^@/.[:alnum:]-])[a-z0-9][a-z0-9-]*(\.[a-z0-9-]+)*\.(edu|ac\.[a-z]{2})\b' \
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
