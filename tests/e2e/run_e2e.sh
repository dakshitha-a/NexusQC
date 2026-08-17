#!/usr/bin/env bash
# Ordered runner for the end-to-end pre-deployment suite.
#
# Deliberately an EXPLICIT ORDERED ARRAY rather than `find | sort` (which
# is what tests/run_backend.sh uses): phase order is load-bearing here.
# The preflight gates must pass before anything else runs, the harness
# gate must pass before any agent-driven scenario is trusted, and the
# destructive scripts must run last because they delete the users and job
# history every earlier script's evidence lives in.
#
# Usage:
#   bash tests/e2e/run_e2e.sh                 # everything except destructive
#   bash tests/e2e/run_e2e.sh --with-destructive
#   bash tests/e2e/run_e2e.sh e2e_04          # one script by prefix
#
# Requires the full docker-compose stack up (see tests/README.md) and
# tests/backend/_00_bootstrap.py already run.
set -uo pipefail
cd "$(dirname "$0")/../.."

# The suite is DISCOVERED from disk, not enumerated by hand.
#
# This used to be a hardcoded ORDER=() list, and it had drifted badly: it
# named six scripts that no longer exist (e2e_01, e2e_02,
# e2e_10_knowledge_tools, e2e_13_concurrency_quota, e2e_14_cancel_orphan,
# e2e_15_sse_stream) and omitted three that do (e2e_10_kb_lifecycle,
# e2e_13_stability, e2e_17_logout_and_return). A missing entry printed a
# quiet "SKIP (not present)", and -- far worse -- a script present on disk
# but absent from the list was never run at all and never mentioned. The
# runner would report "SUMMARY: N passed, 0 failed" while silently
# skipping a third of the suite.
#
# The numeric prefixes already encode the intended order, so a sorted glob
# is both the ordering and the inventory. A newly added script is picked
# up automatically; a renamed one cannot vanish.
mapfile -t ORDER < <(cd "$(dirname "$0")" && ls e2e_*.py 2>/dev/null | sort)

DESTRUCTIVE=(
  e2e_16_admin_destructive.py
)

# Drop the destructive ones out of the discovered default set -- they only
# run with --with-destructive, same as before.
_filtered=()
for _n in "${ORDER[@]}"; do
  _skip=0
  for _d in "${DESTRUCTIVE[@]}"; do [ "$_n" = "$_d" ] && _skip=1; done
  [ "$_skip" -eq 0 ] && _filtered+=("$_n")
done
ORDER=("${_filtered[@]}")

WITH_DESTRUCTIVE=0
FILTER=""
for arg in "$@"; do
  case "$arg" in
    --with-destructive) WITH_DESTRUCTIVE=1 ;;
    *) FILTER="$arg" ;;
  esac
done

SCRIPTS=("${ORDER[@]}")
if [ "$WITH_DESTRUCTIVE" = "1" ]; then
  SCRIPTS+=("${DESTRUCTIVE[@]}")
fi

pass=0; fail=0; skipped=0; failed_names=()
for name in "${SCRIPTS[@]}"; do
  path="tests/e2e/$name"
  if [ -n "$FILTER" ] && [[ "$name" != "$FILTER"* ]]; then continue; fi
  if [ ! -f "$path" ]; then
    # Should be unreachable now that the list is globbed from disk -- if
    # it ever fires, something removed a file mid-run, which is worth
    # shouting about rather than quietly skipping.
    echo "!!! MISSING $name -- expected on disk, not found"; fail=$((fail+1))
    failed_names+=("$name (missing)"); continue
  fi
  echo ""
  echo "============================================================"
  echo "=== $name"
  echo "============================================================"
  if python3 "$path"; then
    pass=$((pass+1))
  else
    fail=$((fail+1)); failed_names+=("$name")
  fi
done

echo ""
echo "============================================================"
echo "SUMMARY: $pass script(s) passed, $fail failed, $skipped skipped"
if [ "$fail" -gt 0 ]; then
  printf '  failed: %s\n' "${failed_names[@]}"
  echo ""
  echo "A [FAIL] here is a real regression. Unlike tests/backend/, no script"
  echo "in this suite is expected to fail -- every expected-negative is"
  echo "asserted positively through _expected.py's expect_by_design()."
  exit 1
fi
echo ""
echo "Raw results (what the report is assembled from): tests/e2e/results/*.jsonl"
