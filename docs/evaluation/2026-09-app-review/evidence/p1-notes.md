# P1 baseline: notes to fold into baseline.md

## perf_04_fair_scheduling.py: 2 FAIL, and they are the documented full-suite artifact

Observed at the frozen commit during the full `run_backend.sh`:

    [FAIL] user A's own burst does not occupy every admission ahead of user B
           order=['A', 'A', 'B', 'A', 'A', 'A', 'A']
    [FAIL] admission interleaves both users rather than draining user A's queue first
           order=['A', 'A', 'B', 'A', 'A', 'A', 'A']

`tests/README.md` documents exactly this: perf_04 asserts admission ORDER
under a global concurrency cap of 1, and "jobs left running by earlier scripts
in the same suite run occupy that cap, so it sees a partial, skewed order."
The fix the fair scheduler exists to make is that B's single job is admitted
in the rotation right after A's first; the observed order has B third because
the cap was already partly occupied when perf_04 started observing.

**To confirm it is the artifact and not a regression** (per the README's own
instruction, and the standing rule not to round a discrepancy away): re-run
perf_04 alone against an otherwise-idle stack at P1.5. Expected 5/5.
Command:
    QC_AGENT_TEST_BASE_URL=https://127.0.0.1:8444 PYTHONPATH=$PWD \
      QC_AGENT_LLM_BASE_URL=http://localhost:11434/v1 \
      python3 tests/backend/perf_04_fair_scheduling.py

This mirrors the 2026-09-06 pass, whose one full-suite failure (batch_01) was
also an artifact of where the script ran rather than a defect.
