<!-- artifact: https://claude.ai/artifact/PaSPgMq8ureJYWF8BXgvbh -- re-render with scripts/render_tracker_html.py and re-publish to THIS url -->
# Closed Tracker: cores per calculation, set from the admin console

**Closed 2026-09-24. Four steps in one phase, all done.**
No tracker is active until the next plan begins.

**Opened 2026-09-24.** One phase. The tracker this replaces is
[`2026-09-plot-text-and-silent-turns.md`](2026-09-plot-text-and-silent-turns.md),
which closed the same day. **Exactly one tracker is active at a time.**

## Rules (enforced by `scripts/check_tracker.py`)

- Step status is exactly one of `todo` | `in-progress` | `done`.
- A step may be marked `done` **only with an evidence field**: one path that
  exists on disk plus a one-line observed result.
- The tracker edit ships **in the same commit** as the step's final change.
- A phase's `merged` row records the commit hash the stage landed as.

Format for a step row:

```
- [status] P<phase>.<step>: <short name>
  evidence: <path> → "<observed result>"   (required when done)
```

---

## Why this plan exists

The user asked for the number of threads each calculation uses to be
changeable in the admin panel. It was `QC_AGENT_N_CORES`, read once at
process start: PySCF and BAGEL threads, ORCA MPI ranks with one thread each.
Changing it needed an edit to `.env` and a restart. And because every module
imported the value, and each job's worker read it again at its own import,
there was no single place a live setting could have gone.

---

## Phase 1: one live value

- [done] P1.1: `cores_per_job()` and every read site use it; the worker gets it in its environment
  evidence: tests/backend/conf_06_cores_per_job.py → "15/15 on the stack at a383154: set to 2, a benzene HF job recorded cores=2, its running worker carried QC_AGENT_N_CORES=2 and OMP_NUM_THREADS=2, PySCF ran 2 threads after its own import, ORCA wrote and capped %pal nprocs 2"
- [done] P1.2: admin route and console field
  evidence: tests/frontend/admin_02_cores_per_job.spec.mjs → "9/9: field renders with the live value and a per-engine note, Save disabled above 64 and for 2.5, saved 3 survives a reload, note says Set here (screenshot looked at); restored to the .env default"
- [done] P1.3: docs, changelog and tests README
  evidence: docs/CONFIGURATION.md → "QC_AGENT_N_CORES is the default the console overrides, with what applies when; README, CHANGELOG Unreleased and tests/README.md updated"
- [done] P1.4: stack rebuilt, backend and browser checks pass
  evidence: tests/backend/perf_04_fair_scheduling.py → "stack on a383154 healthy; perf_03 7/7, perf_04 6/6, p1_03 10/10, perf_05 19/19, sched_01 6/6; no job or thread left behind"
- merged: 05d08d2
