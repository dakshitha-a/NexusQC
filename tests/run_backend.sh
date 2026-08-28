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

# Without this, a host where the scripts are not already being run from an
# activated environment reports most of the suite as failing with
# `ModuleNotFoundError: No module named 'app'` before a single check executes.
# Only the scripts that happen to do their own sys.path.insert survive, so the
# result looks like a broad regression rather than a missing variable. Set here
# rather than left to the caller, because the runner is the thing that knows
# where the repository root is.
#
# PREPENDED, not defaulted. This was written as "${PYTHONPATH:-$PWD}" first,
# which does nothing whenever the variable already holds something else -- and
# on the development host it does: the shell profile exports Gaussian's
# /opt/app/g16 paths, so the repository root was never added and the fix
# appeared to change nothing. Any existing entries are kept, because whatever
# put them there had a reason to.
export PYTHONPATH="$PWD${PYTHONPATH:+:$PYTHONPATH}"

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
    # This blurb used to say a FAIL was "expected for several sec_* scripts,
    # which PASS when they confirm a real gap exists". That was true while
    # those scripts existed to PROVE unfixed gaps -- it stopped being true
    # once every one of them was fixed and rewritten as a regression test,
    # and tests/README.md ("What FAIL means here") was updated then while
    # this message was not. Two different answers to "is this run OK?", and
    # this is the one an operator reads first (F-012).
    echo "Scripts with at least one FAIL. Every sec_* script is now a"
    echo "regression test for a FIXED finding, so a FAIL here is a real"
    echo "regression, not a confirmed-gap report -- see tests/README.md,"
    echo "'What FAIL means here':"
    for name in "${failed_names[@]}"; do
        echo "  - $name"
    done
    exit 1
fi
exit 0
