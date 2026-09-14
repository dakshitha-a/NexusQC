# P4.1, R-098: the fair scheduler, settled

R-098 was recorded with its cause deliberately open. The review ran
`tests/backend/perf_04_fair_scheduling.py` against a stack it had confirmed
idle and got the admission order `A, A, B, A, A, A, A` twice, byte-identical,
where the fair scheduler is supposed to give user B's single job the rotation
slot right after user A's first. An admission order on its own cannot say
whether that is a scheduler that admitted A twice while B waited, or a test
whose B was not yet queued when the second admission happened. Both produce the
same seven letters.

Two things turned out to be true, and the finding closes as **fixed** rather
than as a harness repair, because one of them is a real defect in the
scheduler.

## The experiment

`tests/backend/perf_09_scheduler_fairness_trace.py` (`perf_09-run.log`) repeats
perf_04's submission shape and adds the fact perf_04 never recorded: a
timestamp for every `enqueue`, alongside a timestamp and the scheduler's own
state for every admission. Both spies are installed on the live scheduler
inside the api container and removed afterwards. The verdict is then read off
the interleaved timeline mechanically rather than eyeballed:

- B enqueued **after** A's second admission, order `A, A, B`: the harness race.
- B enqueued **before** A's second admission and still admitted third: a real
  round-robin defect.

Three runs, then a fourth as a positive control which holds B's submission
until A has been admitted twice, so that "a late enqueue produces the review's
order" is measured rather than assumed.

## What the four runs said

| run | B enqueued at | A's 2nd admission at | order | verdict |
|---|---|---|---|---|
| 1 | 19.117 s | 22.664 s | `A, B, A, A, A, A, A` | fair |
| 2 | 13.500 s | 17.729 s | `A, B, A, A, A, A, A` | fair |
| 3 | 9.785 s | 10.614 s | `A, A, B, A, A, A, A` | **code defect** |
| control | 11.597 s | 11.352 s | `A, A, B, A, A, A, A` | harness race |

The control did what it was built to do: with B submitted 0.245 s after A's
second admission, the review's exact order comes back and the timeline says
plainly why. So perf_04's shape can produce that order with nothing wrong
anywhere, which is one honest reading of the review's two observations. The
review had no enqueue timestamps, so it cannot be said which of the two causes
its own runs hit.

Run 3 is the one that matters. B was queued 0.83 s **before** A's second
admission and still went third.

## The defect run 3 found

`_dispatch_tick` asked the host for headroom by calling
`_resources_available()`, which samples CPU with
`psutil.cpu_percent(interval=1.0)` and therefore blocks for a full second. The
tick read its round-robin owner list once, **before** that call, and then
decided who to admit by walking the copy. Every tick was therefore choosing
from a list of owners up to a second out of date, and an owner whose first job
arrived during that second could not be reached by the rotation even when
`_rr_pos` was already pointing at the slot they would have taken. That is
exactly run 3: the tick began at about t=9.6 s with only A in the list, spent a
second sampling while B queued at t=9.785 s, and admitted A at t=10.614 s.

It costs one admission per occurrence rather than indefinite starvation, but
the window is a second wide and it is open on every tick, which is the shape of
unfairness this module exists to remove.

The fix is three lines: keep the cheap "is anything queued at all" check before
the sample, so an idle scheduler still costs nothing, and take the owner
snapshot **after** the sample returns.

## The regression test

A live test is a poor regression test for this, because whether an enqueue
lands inside the window is a coin toss: perf_09's own first three runs came
back fair twice. `tests/backend/sched_01_owner_snapshot_window.py` makes the
coin land the same way every time. It is entirely in-process, builds a
`JobScheduler` with three stub callables and calls `_dispatch_tick()` by hand,
and its stub `resources_available()` enqueues user B from inside itself on the
second tick, which is "B arrived while the dispatcher was sampling" with the
timing taken out. The stub `block_reason` holds a global cap of one, so the
tick has to choose rather than admit both.

- `sched_01-before.log`, run from a worktree at `f6d12c5`: **4 of 6**. The
  second tick admits `a2`, user A's second job, and B waits.
- `sched_01-after.log`, the same script against the fixed tick: **6 of 6**. The
  second tick admits `b1`.

It runs in milliseconds and does not depend on host load, which matters
because the thing under test is a host-load measurement.

## perf_04, and the note in tests/README.md

`perf_04_fair_scheduling.py` now holds admission until both users' jobs are
queued, by swapping the scheduler's block-reason callback for one that refuses
everything while the seven submissions are made and restoring it afterwards.
That is not a way of avoiding a failure; it is what makes the script measure
the thing its name claims, an admission order between two users who are both
actually waiting. The cap is not lowered instead, because the cap is read
through Postgres with its own caching and "the cap is now zero" is not a
synchronous fact, while restoring a callback is.

`tests/README.md` carried the claim that perf_04 passes "against an otherwise
idle stack (5/5)" and told the reader to confirm that before treating a failure
as a regression. The review did exactly that and still got the failing order,
which this note would have had it dismiss. The note now records what actually
happened and points at perf_09 for the diagnosis, because an admission order on
its own cannot tell an unfair scheduler from a test that lost a race.
