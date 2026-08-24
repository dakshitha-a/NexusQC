# Active Tracker: the concurrency cap is not a cap

`tests/backend/perf_04_fair_scheduling.py` failed: with the admin-configured
`max_concurrent_jobs_total` set to 1, submitting 7 jobs left 2 holding a
thread-pool Future rather than 1, and one user's burst took every admission
ahead of another user's single job. Opened and fixed 2026-08-23; two separate
defects, one per phase.

It is not a new regression. The admission gate and `_running_job_ids` have not
changed since `fb96f3e`, the commit that introduced both the fair scheduler and
this test. What changed is that the dev stack's `api` container had been up 21
hours on a stale image, so this was the first suite run against current `main`
in some time.

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

## The mechanism

`JobScheduler._dispatch_tick` walks the round-robin order once and, for each
owner, asks `_concurrent_jobs_block_reason(job_id)` whether the cap allows
another job. That function counts running jobs with `_running_job_ids()`, which
reads **`status.json` on disk**.

Admission does not write that file. `_on_admit` hands the job to the
`ThreadPoolExecutor` and returns immediately, exactly as `scheduler.py`'s
docstring requires; `write_status(job_id, "running", ...)` happens later, on a
pool thread inside `_run_inner`. So within one tick, the second owner's cap
check runs before the first owner's admission is visible on disk, and the cap
is read as having room it does not have.

The bound is therefore the number of admissions *per tick*, not the configured
cap. One extra job per tick is what the test observes.

This is squarely a within-tick problem, not an across-tick one: the executor is
constructed with `max_workers=MAX_CONCURRENT_JOBS` (20 by default) against an
admin cap the test sets to 1, so an admitted task always finds a free pool
thread and reaches `write_status` in milliseconds, well inside the dispatcher's
~1s idle poll.

`_dispatch_tick` already solves the identical problem for host headroom: it
takes one snapshot and decrements a local `idle_budget` across the walk rather
than re-snapshotting per admission, and says so in its own docstring. The
concurrency cap was simply never given the same treatment.

## Phase 1: Make the cap a cap

- [done] P1.1: The dispatcher accounts for admissions it has already made this tick
  evidence: tests/backend/perf_04_fair_scheduling.py → "futures_at_submit_time=1 against the live stack, where it was 2; the dispatcher now passes its own running total and per-owner count into the cap check, the same local-counter treatment idle_budget already had"
- [done] P1.2: A regression check on the mechanism, not only the symptom
  evidence: tests/backend/perf_05_admission_cap_arithmetic.py → "12/12 in about a second with no engine, container or database, driving _dispatch_tick with stand-in callables; re-run with the two in-flight counts forced back to zero it drops to 5/12, so it genuinely catches the pre-fix behaviour rather than passing either way"
- [done] P1.3: `_futures` stops growing without bound
  evidence: app/chemistry/jobs/base.py → "nothing in app/ or server/ ever read _futures -- it was written in _on_admit and never removed, so a long-lived backend accumulated one completed Future per job forever; now dropped in _run's finally, the one path every outcome including cancellation passes through"
- merged: 17042e2

## Phase 2: Make the rotation rotate

Found by fixing Phase 1 and re-running, exactly as this tracker said it would
be: with the cap corrected the Future-count assertion passed and both ORDER
assertions still failed, identically, which is what marks it as a second defect
rather than an incomplete first fix.

`_rr_pos` advanced on every admission ATTEMPT, commented "admitted or not".
That reads as fair and is not. Once the global cap is reached -- the normal
state of a busy deployment -- every owner in the walk is refused, so `_rr_pos`
runs past the end of the rotation and the next tick restarts at index 0. The
owner who happens to sit first then receives every slot that frees, which is
the same starvation this module was written to remove, one level up from where
it was removed.

The walk itself already gives every owner one attempt per tick regardless of
where it starts, so `_rr_pos` only ever decided the ORDER within a tick, never
whether someone got a turn. Advancing it only on a real admission therefore
costs nothing and does not reinstate what the old comment was guarding against:
an owner blocked by their own per-user cap is skipped on every tick while the
owners behind them are admitted and carry the pointer forward.

- [done] P2.1: The rotation pointer advances only past an owner who was admitted
  evidence: tests/backend/perf_04_fair_scheduling.py → "5/5 against the live stack, admission order A,B,A,A,A,A,A where it was A,A,B,A,A,A,A -- user B's single job is now admitted in the rotation immediately after user A's first, not behind A's whole burst"
- [done] P2.2: The fast test covers ordering too, not only the cap arithmetic
  evidence: tests/backend/perf_05_admission_cap_arithmetic.py → "12/12, including a burst-plus-latecomer case that reproduces perf_04's shape in memory: B is admitted second, and A never takes two consecutive slots while B is still queued"
- merged: 17042e2
