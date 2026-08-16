#!/usr/bin/env bash
# Runs every tests/backend/*.py script in sequence against a LIVE stack
# (see tests/README.md for bring-up steps), aggregating PASS/FAIL and
# exiting non-zero if any script reports a failure.
#
# sec_10_bootstrap_reactivation_bypass.py is deliberately EXCLUDED from
# this default run -- it's isolated/opt-in (see its own docstring for why)
# and must be invoked explicitly:
#   python3 tests/backend/sec_10_bootstrap_reactivation_bypass.py
set -uo pipefail
cd "$(dirname "$0")/.."

SCRIPTS=$(find tests/backend -maxdepth 1 -name '*.py' ! -name 'sec_10_*' | sort)

n_total=0
n_failed=0
failed_names=()

for script in $SCRIPTS; do
    n_total=$((n_total + 1))
    echo ""
    echo "=================================================================="
    echo "  $script"
    echo "=================================================================="
    if ! python3 "$script"; then
        n_failed=$((n_failed + 1))
        failed_names+=("$script")
    fi
done

echo ""
echo "=================================================================="
echo "  SUMMARY: $((n_total - n_failed))/$n_total scripts reported all checks passing"
echo "=================================================================="
if [ "$n_failed" -gt 0 ]; then
    echo "Scripts with at least one FAIL (this is expected for several sec_*"
    echo "scripts, which PASS when they confirm a real gap exists -- read"
    echo "each script's own summary() call to see whether exit_on_failure"
    echo "was set, i.e. whether FAIL there means 'bug confirmed' or"
    echo "'unexpected breakage'):"
    for name in "${failed_names[@]}"; do
        echo "  - $name"
    done
    exit 1
fi
exit 0
