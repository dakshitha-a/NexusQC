#!/usr/bin/env python3
"""The concurrency cap bounds admissions in total, not per dispatcher tick.

`perf_04_fair_scheduling.py` proves the symptom against a live stack, with
real ORCA CASSCF jobs, and takes minutes. This proves the CAUSE in about a
second, with no engine, no container and no database: it drives
`JobScheduler._dispatch_tick` directly with stand-in callables.

The bug it pins down. `_dispatch_tick` walks the round-robin order once and
asks `block_reason` per owner whether the cap allows another job.
`block_reason` counts running jobs by reading status.json off disk -- and
admission does not write status.json. `_on_admit` hands the job to the
executor and returns immediately (it must; a slow on_admit stalls admission
for every owner), and "running" is written later on a pool thread inside
`_run_inner`. So every call within one walk saw the same pre-walk disk
state, and a cap of N admitted N jobs PER TICK instead of N in total.

The stand-in `block_reason` below reproduces exactly that lag: it counts a
`visible_running` set that the test controls and which admission
deliberately does NOT update, which is what disk does. If the scheduler
stops counting its own in-flight admissions, this goes back to admitting one
job per owner per tick and these checks fail.

Kept as a sibling of perf_04 rather than folded into it because the two
answer different questions and have wildly different costs: perf_04 says
"the deployed system starves a second user", this says "here is the
arithmetic that made it do so". Losing the fast one to the slow one's
runtime is how a cause-level regression check stops being run.

Run:  PYTHONPATH=$PWD python3 tests/backend/perf_05_admission_cap_arithmetic.py
"""
from __future__ import annotations

import sys
from typing import Optional

from app.chemistry.jobs import scheduler as scheduler_mod
from app.chemistry.jobs.scheduler import JobScheduler
from app.config import N_CORES

# The blocked branch of _dispatch_tick calls write_status to tell a queued
# job why it is waiting, which wants a real job directory on disk. These job
# ids are fictional, and creating directories for them would litter
# data/jobs with entries no job ever backed -- exactly what
# "a job directory is only a job if it holds a spec" (1baf140) had to clean
# up after. So the write is captured instead, which also makes the reason
# text assertable.
PENDING_MESSAGES: list[tuple[str, str]] = []
scheduler_mod.write_status = lambda job_id, status, message="": PENDING_MESSAGES.append((job_id, message))

PASS = 0
FAIL = 0


def check(label: str, ok: bool, detail: str = "") -> None:
    global PASS, FAIL
    if ok:
        PASS += 1
        print(f"  [PASS] {label}")
    else:
        FAIL += 1
        print(f"  [FAIL] {label}" + (f"\n         {detail}" if detail else ""))


class Harness:
    """A JobScheduler wired to stand-ins, with one tick driven by hand.

    `visible_running` is the disk's view: it changes only when this test
    says so, never as a side effect of admission. That is the whole point --
    it is what makes the lag the real system has reproducible here.
    """

    def __init__(self, cap_total: int, cap_per_user: int = 99, n_idle: int = 10_000):
        self.cap_total = cap_total
        self.cap_per_user = cap_per_user
        self.n_idle = n_idle
        self.visible_running: set[str] = set()
        self.admitted: list[str] = []
        self.pending: list[tuple[str, str]] = []
        self.owner_of: dict[str, str] = {}
        self.scheduler = JobScheduler(
            on_admit=self._on_admit,
            resources_available=lambda: (True, self.n_idle, ""),
            block_reason=self._block_reason,
        )

    def _on_admit(self, job_id: str) -> None:
        # Deliberately does NOT touch visible_running: the real _on_admit
        # does not write status.json either.
        self.admitted.append(job_id)

    def _block_reason(self, job_id: str, already_admitted: int = 0,
                      already_admitted_for_owner: int = 0) -> Optional[str]:
        running = set(self.visible_running)
        running.discard(job_id)
        if len(running) + already_admitted >= self.cap_total:
            return "cap: total"
        owner = self.owner_of.get(job_id)
        mine = sum(1 for j in running if self.owner_of.get(j) == owner)
        if mine + already_admitted_for_owner >= self.cap_per_user:
            return "cap: per user"
        return None

    def enqueue(self, job_id: str, owner: str) -> None:
        self.owner_of[job_id] = owner
        self.scheduler.enqueue(job_id, owner)

    def tick(self) -> None:
        PENDING_MESSAGES.clear()
        self.scheduler._dispatch_tick()


def main() -> int:
    print("== A cap of 1 admits one job, however many owners are waiting ==")
    h = Harness(cap_total=1)
    for i in range(3):
        h.enqueue(f"a{i}", "A")
    h.enqueue("b0", "B")
    h.enqueue("c0", "C")
    h.tick()
    check("one tick admits exactly 1 job under a cap of 1",
          len(h.admitted) == 1, f"admitted {h.admitted}")
    check("the admitted job is the first owner's, not one per owner",
          h.admitted == ["a0"], str(h.admitted))
    check("the owners who lost their turn are told the cap is why",
          all(m == "cap: total" for _, m in PENDING_MESSAGES) and PENDING_MESSAGES,
          str(PENDING_MESSAGES))

    print("\n== A cap of 2 admits two, and the third owner is told why ==")
    h = Harness(cap_total=2)
    for owner in ("A", "B", "C", "D"):
        h.enqueue(f"{owner}0", owner)
    h.tick()
    check("one tick admits exactly 2 jobs under a cap of 2",
          len(h.admitted) == 2, f"admitted {h.admitted}")
    check("they come from two DIFFERENT owners (round-robin, not one queue drained)",
          len({h.owner_of[j] for j in h.admitted}) == 2, str(h.admitted))

    print("\n== Admissions carry across ticks once the disk catches up ==")
    h = Harness(cap_total=1)
    for i in range(3):
        h.enqueue(f"a{i}", "A")
    h.tick()
    check("tick 1 admits 1", len(h.admitted) == 1, str(h.admitted))
    # The pool thread has now written "running" for the admitted job, which
    # is what the real _run_inner does a moment after admission.
    h.visible_running.add(h.admitted[0])
    h.tick()
    check("tick 2 admits nothing while that job is still running",
          len(h.admitted) == 1, str(h.admitted))
    h.visible_running.clear()   # it finished
    h.tick()
    check("tick 3 admits the next one once the slot is free",
          len(h.admitted) == 2, str(h.admitted))

    print("\n== The per-user cap has the same blind spot, and the same fix ==")
    h = Harness(cap_total=99, cap_per_user=1)
    for i in range(3):
        h.enqueue(f"a{i}", "A")
    h.enqueue("b0", "B")
    h.tick()
    check("one tick admits at most 1 job per owner under a per-user cap of 1",
          sorted(h.admitted) == ["a0", "b0"], str(h.admitted))

    print("\n== A freed slot goes to the next owner in rotation, not the first ==")
    # The shape perf_04 sees against a live stack: user A bursts several
    # jobs, user B submits one, and the cap allows one at a time. Each tick
    # blocks everyone once the slot is taken, so if the rotation pointer
    # advances on blocked attempts it ends up past the end and the next tick
    # restarts at index 0 -- handing every freed slot back to A forever.
    h = Harness(cap_total=1)
    for i in range(4):
        h.enqueue(f"a{i}", "A")
    h.enqueue("b0", "B")
    order: list[str] = []
    for _ in range(10):
        h.tick()
        if len(h.admitted) > len(order):
            order.append(h.owner_of[h.admitted[-1]])
            h.visible_running = {h.admitted[-1]}   # it starts running
            h.tick()                               # a tick while it runs: nothing may be admitted
            h.visible_running.clear()              # it finishes, freeing the slot
    check("B is admitted in the very next rotation after A's first, not behind A's whole burst",
          order[:2] == ["A", "B"], f"admission order by owner: {order}")
    check("A never takes two slots in a row while B is still waiting",
          "B" in order[:2], f"admission order by owner: {order}")

    print("\n== The host-headroom budget still bounds a tick independently ==")
    # Two owners, but only enough idle cores for one job. The cap is wide
    # open, so anything admitted beyond one is the headroom budget failing,
    # not the cap.
    h = Harness(cap_total=99, n_idle=N_CORES)
    h.enqueue("a0", "A")
    h.enqueue("b0", "B")
    h.tick()
    check("a one-job idle budget admits one job even with the cap wide open",
          len(h.admitted) == 1, f"admitted {h.admitted} with n_idle={N_CORES}")

    total = PASS + FAIL
    print(f"\n{PASS}/{total} checks passed")
    if FAIL:
        print(f"[FAIL] {FAIL} check(s) failed")
        return 1
    print("[PASS] ALL CHECKS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
