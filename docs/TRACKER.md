# Tracker: cores per calculation, set from the admin console

**Opened 2026-09-24.** One phase. The tracker this replaces is
[`2026-09-plot-text-and-silent-turns.md`](trackers/2026-09-plot-text-and-silent-turns.md),
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

- [in-progress] P1.1: `cores_per_job()` and every read site use it; the worker gets it in its environment
- [in-progress] P1.2: admin route and console field
- [in-progress] P1.3: docs, changelog and tests README
- [todo] P1.4: stack rebuilt, backend and browser checks pass
- merged: -
