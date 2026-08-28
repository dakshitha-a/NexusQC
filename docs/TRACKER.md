# Active Tracker: a concurrency cap that holds between ticks, not just within one

Opened 2026-08-28, straight out of the previous plan. `perf_04_fair_scheduling`
has been failing reproducibly for several sessions, with the identical
admission order `A, A, B` on separate runs, and was carried forward each time
as "a genuine failure of the scheduler against its own stated contract" without
anyone working out what it was actually failing at.

It is not a fairness bug. `JobScheduler._dispatch_tick` counts its own
admissions in `admitted_total` / `admitted_per_owner` and passes them to
`block_reason`, which is what turns a per-tick cap back into a real cap. That
was the fix for the within-a-tick case, and its own comment explains why it is
needed: `block_reason` counts running jobs by reading `status.json` off disk,
and `_on_admit` returns immediately without writing anything, so the disk
cannot see what this walk has already let through.

The same sentence is true across ticks, and there the counters do not help,
because they are local to `_dispatch_tick` and reset every pass. So:

- user A's burst calls `enqueue`, and every `enqueue` sets `_wake`, so ticks
  fire back-to-back during the submission loop
- tick 1 admits A1. `_on_admit` returns immediately; nothing is on disk yet
- tick 2 reads the same pre-admission disk state, sees zero running, and
  admits A2 under a global cap of 1

The `A, A, B` the test reports is the symptom, and user B is incidental to it:
both of A's admissions happen before B has enqueued at all. The defect is that
**the cap is exceeded**, which matters well beyond the test, because the cap is
what a deployment sets to stop this shared host being oversubscribed.

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

## How tracking works here

Development is linear, so there is never a reason to have two trackers open
at once. Each plan, feature or non-trivial request gets its own tracker, this
file is whichever one is currently in motion, and when its plan is finished
the file is closed out and moved to [`trackers/`](trackers/), then a fresh one
starts here for whatever comes next.

Closed trackers are kept, never deleted. They are the audit trail for why the
code looks the way it does, and code comments cite them by path. The two most
recent closures:

- [`trackers/2026-08-update-knows-what-it-runs.md`](trackers/2026-08-update-knows-what-it-runs.md)
  `scripts/update.sh` now asks the deployment what it is running rather than
  the checkout, and its recovery advice matches what the update actually did.
  10 steps across four phases, closed 2026-08-28 with one live-build
  verification carried to the backlog.
- [`trackers/2026-08-job-names-and-search.md`](trackers/2026-08-job-names-and-search.md)
  a job's generated name now identifies the calculation rather than colliding
  across methods, and the Job Manager has a fuzzy search bar. 12 steps across
  four phases, closed 2026-08-28.

The rest of `trackers/` follows the same shape; each names its own scope in
its first paragraph.

---

## Phase 1: The over-admission, demonstrated without a stack

- [done] P1.1: A failing test that admits more than the cap allows
  evidence: tests/backend/perf_05_admission_cap_arithmetic.py → "the gap every existing section left open is that each of them handed the disk the admitted job before ticking again, and real submission does not. Two ticks with no disk update admitted ['a0', 'a1'] against a cap of 1, and four ticks admitted four. The per-user cap failed the same way"
- [done] P1.2: The same test shows the round-robin order is a consequence, not the cause
  evidence: tests/backend/perf_05_admission_cap_arithmetic.py → "the rotation checks passed both before and after the fix. The order perf_04 reports is what a cap that admits one job per tick looks like from outside: both of user A's admissions land before user B has enqueued, so the fairness assertion fails downstream of the cap being exceeded rather than because the rotation is wrong"

Written into `perf_05` rather than a new script. It already drives
`_dispatch_tick` by hand with stand-in callables for exactly this purpose,
and a second harness alongside it would have been a near-copy that could
drift.

## Phase 2: The cap counts what has been admitted, not only what is on disk

- [done] P2.1: Admitted-but-not-yet-running jobs are tracked across ticks
  evidence: app/chemistry/jobs/scheduler.py → "`_in_flight`, added under the same lock that takes a job off its queue, since leaving the queue IS admission. Replaces the two counters local to `_dispatch_tick`, which were the same idea with the wrong lifetime: they turned the cap back into a cap within one tick and left it broken across ticks, because every enqueue sets `_wake` and a burst fires ticks back to back"
- [done] P2.2: They are released on the terminal transition that already wakes the dispatcher
  evidence: app/chemistry/jobs/base.py → "`JobManager._run`'s `finally` already called `_scheduler.wake()` there and is the one path every outcome passes through, cancellation mid-run included; it now calls `release()`, which wakes. `_on_admit` releases on its two paths where `_run` never happens at all: a spec that vanished between admission and dispatch, and a pool that refuses the submit during shutdown"
- [done] P2.3: Nothing leaks the set when a job is cancelled between admission and running
  evidence: tests/backend/perf_05_admission_cap_arithmetic.py → "18/18. A slot released without the job ever reaching disk is reusable on the next tick, and releasing an unknown or already-released job changes nothing. This is the failure worth being careful about: an over-admission is transient, a leaked slot is held for the life of the process"

The count is a **union** rather than an addition, which is what makes the
release forgiving. `block_reason` unions the scheduler's in-flight set with
what it reads off disk, so a job that has since written "running" is counted
once whether or not it is still in the set. A count would have double-counted
it and tightened the cap at random depending on how quickly the pool thread
got there, and would have needed release to be timed precisely rather than
eventually.

## Phase 3: Confirmed on the real thing

- [todo] P3.1: `perf_04_fair_scheduling` passes against the live stack
