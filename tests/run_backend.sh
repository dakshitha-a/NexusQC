#!/usr/bin/env bash
# Runs every tests/backend/*.py script in sequence against a LIVE stack
# (see tests/README.md for bring-up steps), aggregating PASS/FAIL and
# exiting non-zero if any script reports a failure.
#
# Four scripts are deliberately EXCLUDED from this default run and must be
# invoked explicitly:
#
#   python3 tests/backend/sec_10_bootstrap_reactivation_bypass.py
#   python3 tests/backend/p1_07_purge_status_source.py
#   python3 tests/backend/p1_03_admin_config_purge_audit.py
#   python3 tests/backend/perf_02_admin_storage_latency.py
#
# sec_10 is isolated/opt-in; see its own docstring for why.
#
# The other three call POST /api/admin/purge/jobs, which is purge_all_jobs: it
# destroys EVERY job on the stack, not only the ones the suite created. On
# 2026-08-28 a full suite run took out the job artifacts behind three live
# conversations with it. The conversations survived, a job purge not touching
# the Postgres checkpoints, but the results on disk were gone. A test suite
# that is not safe to run against a stack somebody is using is not much of a
# test suite, and the standing rule here is that a full job or conversation
# purge happens only when the maintainer asks for one, in those words.
# Running one of these is now how you ask.
#
# Only p1_07 was excluded when that rule was written, and the exclusion was
# therefore incomplete: p1_03 and perf_02 make the same call and were left in
# the default set, so a full run still wiped the stack. Confirmed on
# 2026-09-06, when a run took the job count from 275 to 25 and the log shows
# both of them reporting "purge/jobs succeeds -- 200" with the audit entry
# recording `purge_all_jobs`. The lesson is that the quarantine has to be
# derived from what a script CALLS, not from remembering which script it was:
#
#   grep -l "admin/purge/jobs" tests/backend/*.py
#
# returns conf_01 as well, and that one is safe because it only asserts a
# non-admin gets 403, but any new name in that list needs checking before it
# joins the default run.
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

SCRIPTS=$(find tests/backend -maxdepth 1 -name '*.py' \
    ! -name 'sec_10_*' ! -name 'p1_07_*' \
    ! -name 'p1_03_*' ! -name 'perf_02_admin_storage_latency.py' | sort)

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
