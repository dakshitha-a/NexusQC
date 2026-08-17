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

ORDER=(
  e2e_00_preflight.py
  e2e_01_install_admin.py
  e2e_02_user_lifecycle.py
  e2e_03_route_auth_sweep.py
  e2e_04_harness_gate.py
  e2e_05_molecule_resolution.py
  e2e_06_agent_tools.py
  e2e_07_approval_flow.py
  e2e_08_job_matrix.py
  e2e_09_plot_tools.py
  e2e_10_knowledge_tools.py
  e2e_11_param_correction.py
  e2e_12_failure_retry.py
  e2e_13_concurrency_quota.py
  e2e_14_cancel_orphan.py
  e2e_15_sse_stream.py
)
DESTRUCTIVE=(
  e2e_16_admin_destructive.py
)

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
    echo "--- SKIP $name (not present)"; skipped=$((skipped+1)); continue
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
