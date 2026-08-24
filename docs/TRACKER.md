# Active Tracker: the suite cleans up the jobs it creates

Test scripts submit real jobs and left every one of them behind, permanently,
in everybody's job list. Opened and completed 2026-08-23.

## Why they were visible to everyone in the first place

Ownership is recorded by the API **route**, not by `JobManager`. Most test
scripts submit by calling `JobManager.submit`/`submit_scan` in-process, which
takes an optional `owner_user_id` that nothing supplies, so their jobs have no
recorded owner at all.

An unowned job is deliberately shown to every user
(`server/routes/jobs.py`'s `list_all_jobs` keeps a row when the caller owns it
**or** when nobody does). That is a feature and stays: anyone can see such a
job, so anyone can clear it, which is what stops orphaned jobs accumulating
with nobody empowered to remove them. Narrowing that rule was considered and
explicitly rejected. The fix belongs in the tests, not in the visibility rule.

Sub-jobs of a scan, batch or ensemble are unowned too, but they are excluded
from every list by `_iter_all_job_specs` and are only reachable nested under a
master whose ownership has already been checked, so the rule applies to
top-level jobs only.

## How tracking works here

Development is linear, so there is never a reason to have two trackers open at
once. Each plan, feature or non-trivial request gets its own tracker, this file
is whichever one is currently in motion, and when its plan is finished the file
is closed out and moved to [`trackers/`](trackers/), then a fresh one starts
here for whatever comes next.

Closed trackers are kept, never deleted. They are the audit trail for why the
code looks the way it does, and code comments cite them by path:

- [`trackers/2026-08-job-system-overhaul.md`](trackers/2026-08-job-system-overhaul.md)
  the 10-phase job-type/toolchain/agent overhaul. Closed 2026-08-22, 72 steps
  across 5 merged phases.
- [`trackers/2026-08-plots-as-objects.md`](trackers/2026-08-plots-as-objects.md)
  plots as first-class objects. Closed 2026-08-22, 20 steps across 4 phases.
- [`trackers/2026-08-excited-state-scans.md`](trackers/2026-08-excited-state-scans.md)
  excited states at every point of a scan or interpolated path. Closed
  2026-08-23, 9 steps across 2 merged phases.
- [`trackers/2026-08-scheduler-fairness.md`](trackers/2026-08-scheduler-fairness.md)
  the concurrency cap that bounded admissions per tick rather than in total,
  and the rotation pointer that advanced on refused attempts. Closed
  2026-08-23, 5 steps across 2 merged phases.

Closing one out means: every step `done` with evidence, a `merged:` row on each
phase, `scripts/check_tracker.py` passing, then `git mv` into `trackers/` and a
new file here. Only the active tracker is machine-checked; an archived one
records what was true when it closed and is not re-verified, since the scripts
its evidence names may legitimately have been deleted since.

## Rules (enforced by `scripts/check_tracker.py`)

- Step status is exactly one of `todo` | `in-progress` | `done`.
- A step may be marked `done` **only with an evidence field**: the
  verification script/command path plus a one-line observed result.
- The tracker edit ships **in the same commit** as the step's final code
  change, so `git log --follow docs/TRACKER.md` is the audit trail.
- A phase's `merged` row records the commit hash the stage landed as, and it
  must be a bare hash; the checker rejects anything else.

Format for a step row:

```
- [status] P<phase>.<step>: <short name>
  evidence: <script/command> → "<observed result>"   (required when done)
```

---

## Phase 1: A run leaves the job list as it found it

The sweep is scoped to a baseline rather than "delete every unowned job", and
that is the whole safety argument. An unowned job is a legitimate, deliberately
shared thing on a real deployment, so a test run has no business removing one
it did not create. With no baseline file the sweep skips rather than guessing:
an over-eager sweep here would delete somebody's work, which is far worse than
leaving clutter behind.

- [done] P1.1: A reusable cleanup helper that cancels before deleting
  evidence: tests/fixtures.py → "clearing the 16 jobs that had accumulated on the dev stack deleted all 16 and left the list empty, including several non-terminal ones -- DELETE /api/jobs/{id} answers 409 for those, correctly, so the helper cancels first and retries once since cancellation is not instantaneous"
- [done] P1.2: The run records what already existed before it started
  evidence: tests/backend/_00_bootstrap.py → "writes tests/.jobs_before_run on both paths, the fresh-bootstrap one and the already-provisioned one that returns early -- without the second, every run after the first would have had no baseline"
- [done] P1.3: A sweep that removes only what the run added
  evidence: tests/backend/zz_99_job_cleanup.py → "2/2 end to end: with one job pre-existing and one created after the baseline, it deleted exactly the created one and the pre-existing job survived; sorts last under run_backend.sh's own find|sort, and verifies against GET /api/jobs rather than trusting the delete responses"
- [done] P1.4: With no baseline it refuses rather than guessing
  evidence: tests/backend/zz_99_job_cleanup.py → "run with no tests/.jobs_before_run present it reported [SKIP] and deleted nothing, which is the behaviour that makes the sweep safe to ship at all"

## Note for whoever writes the next test script

This covers the SUITE. A script run on its own still leaves its jobs behind
unless it cleans up after itself — `fixtures.cleanup_jobs` exists for exactly
that, and a new script under `tests/backend/` that submits anything should wire
it up at the same time rather than leaving it for a later pass.

## Queued: the public-safety scan

Not started, and deliberately not an active tracker yet.
`scripts/check_public_safe.sh` currently fails with two blocking findings: host
paths (`/data/qcuser/nexusqc-prod`) inside
`docs/trackers/2026-08-job-system-overhaul.md`, and `/opt/Orca-6.1.1/orca`
inside `data/verified/orca_functionals.txt`. Deferred deliberately on
2026-08-23. Nothing about it blocks day-to-day work, because `origin` is
private and ordinary pushes are not scanned. It does block the first public
release: `scripts/release.sh` runs the scan itself and refuses to publish while
it fails. Both findings sit in files that are not code — one an archived
planning document, which by this project's convention is never edited after it
closes, the other generated reference data — so the likely shape of the fix is
narrowing the scan's patterns rather than rewriting either file, but that is a
starting point rather than a decision anyone has made.
