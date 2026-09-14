"""R-098: an owner who queues during the dispatcher's CPU sample loses a turn.

    PYTHONPATH=$PWD python3 tests/backend/sched_01_owner_snapshot_window.py

Entirely in-process. No container, no stack, no engine: it builds a
`JobScheduler` with three stub callables and calls `_dispatch_tick()` by hand,
so it runs in milliseconds and its result does not depend on host load, which
matters because the thing under test IS a host-load measurement.

WHAT THE DEFECT WAS
-------------------
`_dispatch_tick` asks the host whether there is room to admit anything by
calling `resources_available()`, which in the real deployment is
`app/chemistry/jobs/base._resources_available` and samples CPU with
`psutil.cpu_percent(interval=1.0)`. That call BLOCKS for a full second.

The tick used to read the round-robin owner list once, before that call, and
then walk the copy it had taken. So every tick decided who could be admitted
using a list of owners that was up to a second out of date. An owner whose
first job was queued during that second was not in the list, could not be
reached by the rotation, and lost their turn, even when `_rr_pos` was already
pointing at the position they would have occupied. One admission per
occurrence rather than indefinite starvation, but the window is a full second
wide and it is open on every single tick.

Measured live on the deployment before the fix, by
`tests/backend/perf_09_scheduler_fairness_trace.py`, which timestamps every
enqueue as well as every admission: user B queued at t=9.785 s, the tick
admitted user A a second time at t=10.614 s, and B went third in a rotation
that should have given it second. That run also shows why a live test is a poor
regression test for this: the same script came back fair on its other two runs,
because whether B's enqueue lands inside the window is a coin toss.

WHAT THIS SCRIPT DOES INSTEAD
-----------------------------
It makes the coin land the same way every time. The stub
`resources_available()` enqueues user B's job from inside itself, before
returning, which is exactly "B arrived while the dispatcher was sampling the
CPU" with the timing removed. Then:

    tick 1  A has one job queued, B has none yet.
            The sample enqueues B. A1 is admitted (correctly: A was the only
            owner when the tick began, and _rr_pos moves to 1).
    release A1, so the cap is free again.
    tick 2  A and B both have a job queued and _rr_pos points at B.

On the fixed code tick 2 admits B, because the owner list is read after the
sample. On the code as it was, tick 2 walks a list that was captured before the
sample of tick 1 and still contains only A, so it admits A a second time and B
waits.

The stub `block_reason` enforces a global cap of one, the way the real one
does, so that the two ticks cannot both admit and the ordering is forced to be
a choice rather than a coincidence.

Both admissions are recorded, and the assertion is on the order.
"""
from __future__ import annotations

import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from fixtures import check, summary  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
from app.chemistry.jobs import base as jobs_base  # noqa: E402
from app.chemistry.jobs.scheduler import JobScheduler  # noqa: E402
from app.config import N_CORES  # noqa: E402

# A refused job gets `write_status(job_id, "pending", reason)` written to its
# directory, which is the one thing here that touches the filesystem. Point it
# at a scratch tree rather than the deployment's own data/jobs: this script
# invents three job ids that do not exist, and it must not leave three
# directories behind for the cleanup diff to find or for the job list to show.
_TMP_JOBS = Path(tempfile.mkdtemp(prefix="sched_01_jobs_"))
jobs_base.JOBS_DIR = _TMP_JOBS
for _jid in ("a1", "a2", "b1"):
    (_TMP_JOBS / _jid).mkdir()


def main() -> None:
    admitted: list[str] = []
    sampled = {"n": 0}

    sched: JobScheduler

    def on_admit(job_id: str) -> None:
        admitted.append(job_id)

    def resources_available():
        # Stands in for psutil.cpu_percent(interval=1.0). The real one blocks
        # for a second; this one does the one thing that can happen during
        # that second and matters here, which is that another owner queues a
        # job. It does that on the SECOND tick, which is the tick whose
        # rotation pointer is already sitting on the position user B is about
        # to take. That is the whole defect: not that a late owner is invisible
        # for a moment, but that the tick which is about to admit somebody
        # decides who on a list that predates them.
        sampled["n"] += 1
        if sampled["n"] == 2:
            sched.enqueue("b1", "userB")
        # Plenty of idle cores, so the budget is never what refuses anything.
        return True, N_CORES * 8, ""

    def block_reason(job_id: str, in_flight):
        # A global cap of one, which is what makes the tick a choice: with two
        # owners queued and one slot, somebody is admitted and somebody is not.
        if len(in_flight) >= 1:
            return "waiting for a free job slot (1/1 running total)"
        return None

    sched = JobScheduler(on_admit=on_admit,
                         resources_available=resources_available,
                         block_reason=block_reason)

    # No start(): the dispatcher thread is not wanted here. Ticks are called by
    # hand so the sequence is exact.
    sched.enqueue("a1", "userA")
    sched.enqueue("a2", "userA")

    sched._dispatch_tick()
    first = list(admitted)
    check("the first tick admits user A, the only owner with anything queued",
          first == ["a1"], f"admitted {first}")
    check("and the rotation pointer has moved past user A, so the next turn is not theirs",
          sched._rr_pos == 1, f"_rr_pos is {sched._rr_pos}")
    check("user B has queued nothing yet, so there is nothing for the pointer to reach",
          "b1" not in sched._queued_ids, f"queued ids are {sorted(sched._queued_ids)}")

    sched.release("a1")
    sched._dispatch_tick()

    check("user B's job was queued during the second tick's sample, which is the setup",
          "b1" in sched._queued_ids or "b1" in admitted,
          f"queued ids are {sorted(sched._queued_ids)}, admitted {admitted}")

    order = list(admitted)
    check(
        "the second tick admits user B, not user A a second time: an owner who queued while "
        "the dispatcher was sampling the host is visible to the tick that admits, and the "
        "rotation pointer was already on them",
        order == ["a1", "b1"],
        f"admission order was {order}, which means the tick decided who to admit from an "
        f"owner list captured before the sample and never saw user B",
    )
    check(
        "and user A's second job is still waiting its turn rather than having taken B's",
        "a2" in sched._queued_ids,
        f"still queued: {sorted(sched._queued_ids)}",
    )

    summary()


if __name__ == "__main__":
    try:
        main()
    finally:
        shutil.rmtree(_TMP_JOBS, ignore_errors=True)
