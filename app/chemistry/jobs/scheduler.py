"""Fair per-user job admission scheduler (Phase 4 of the overhaul).

The problem this replaces: JobManager used to hand every submitted job
straight to a bounded `ThreadPoolExecutor.submit()`, and the worker thread
that eventually ran it would itself block in a polling loop
(`_wait_for_resources`) until host headroom and the admin-configured
concurrency caps allowed it to actually spawn a subprocess. That meant a
job occupied a full worker-pool slot for as long as it was merely WAITING
to be allowed to run, not just while it was actually running. A single
burst submission -- a pes_1d scan's 40 per-image sub-jobs, all
`self.submit()`-ed in one tight loop -- could occupy every slot in the
pool in pure submission order, each one parked in its own resource-wait
loop; a second user's single job, submitted a moment later, queued behind
all 40 in the executor's own FIFO and could not get a worker thread (and
therefore could not even begin ASKING whether it was allowed to run) until
enough of the first user's jobs vacated a slot. This is the "verified
starvation vector" the overhaul plan names.

The fix is to separate "a job exists and wants to run" from "a job has
been admitted to actually run": a job now sits in its owner's own FIFO
queue -- an in-memory deque entry, nothing more -- until this scheduler's
single dispatcher thread decides to admit it. Only that decision (never a
worker thread's own polling) ever spawns a subprocess. The dispatcher
round-robins across owners' queues, so one user's large batch of sub-jobs
never gets more than one turn ahead of any other user's queued job.

`JobManager` supplies three callables at construction (kept as plain
functions/methods rather than making this module import JobManager
directly, both to avoid a circular import back into base.py and because
the scheduler has no business knowing anything about JobSpec/subprocess
mechanics -- its whole job is FIFO-per-owner plus admission arithmetic):

  - `on_admit(job_id)`: called the instant a job is admitted. Must return
    immediately -- see `_dispatch_tick`'s own note on why nothing slow may
    run on the dispatcher thread.
  - `resources_available() -> (bool, n_idle, message)`: one host-headroom
    snapshot (`app.chemistry.jobs.base._resources_available`).
  - `block_reason(job_id) -> Optional[str]`: the admin-configured
    concurrent-jobs cap check (`app.chemistry.jobs.base.
    _concurrent_jobs_block_reason`).
"""
from __future__ import annotations

import threading
from collections import deque
from typing import Callable, Optional

from app.chemistry.jobs.base import write_status
from app.config import N_CORES


class JobScheduler:
    def __init__(
        self,
        on_admit: Callable[[str], None],
        resources_available: Callable[[], tuple[bool, int, str]],
        block_reason: Callable[[str], Optional[str]],
    ):
        self._on_admit = on_admit
        self._resources_available = resources_available
        self._block_reason = block_reason

        self._lock = threading.Lock()
        self._queues: dict[Optional[str], deque[str]] = {}
        # Round-robin rotation order: owners with a currently non-empty
        # queue, in the order they most recently became non-empty. Not a
        # stable long-term ordering -- an owner is appended to the END
        # when their queue goes from empty to non-empty, so a user who
        # drains their queue and later submits again rejoins at the back,
        # same as any other newcomer. That's deliberate: fairness here
        # means "no one skips the line," not "submission order is
        # preserved across an empty spell."
        self._order: list[Optional[str]] = []
        self._rr_pos = 0
        self._queued_ids: set[str] = set()  # membership, for O(1) enqueue/dequeue checks

        self._stop = threading.Event()
        self._wake = threading.Event()
        self._thread: Optional[threading.Thread] = None

    def start(self) -> None:
        if self._thread is not None:
            return
        self._thread = threading.Thread(target=self._loop, daemon=True, name="job-scheduler")
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._wake.set()
        if self._thread is not None:
            self._thread.join(timeout=5)
            self._thread = None

    def enqueue(self, job_id: str, owner: Optional[str]) -> None:
        """Adds a job to its owner's FIFO queue. Idempotent -- a job_id
        already queued (or already popped and mid-dispatch) is left alone,
        so a caller never needs to check membership first."""
        with self._lock:
            if job_id in self._queued_ids:
                return
            q = self._queues.setdefault(owner, deque())
            if not q:
                self._order.append(owner)
            q.append(job_id)
            self._queued_ids.add(job_id)
        self.wake()

    def dequeue(self, job_id: str) -> bool:
        """Best-effort removal of a not-yet-admitted job. Returns False
        (not an error) if the job was never queued or has already been
        popped by the dispatcher -- JobManager.cancel()'s own
        `self._cancelled` set is what guards that race (a job popped a
        moment before this runs is caught at the top of `_run_inner`
        instead), so this is a tidiness operation, not the correctness
        mechanism."""
        with self._lock:
            if job_id not in self._queued_ids:
                return False
            for owner, q in list(self._queues.items()):
                if job_id in q:
                    q.remove(job_id)
                    if not q:
                        del self._queues[owner]
                        if owner in self._order:
                            self._order.remove(owner)
                    break
            self._queued_ids.discard(job_id)
            return True

    def wake(self) -> None:
        """Nudges the dispatcher to run a tick now rather than waiting out
        its own up-to-1s idle poll -- called after enqueue (new work
        arrived) and after a job goes terminal (a cap/headroom slot may
        have just freed up)."""
        self._wake.set()

    def _loop(self) -> None:
        while not self._stop.is_set():
            self._wake.wait(timeout=1.0)
            self._wake.clear()
            if self._stop.is_set():
                return
            try:
                self._dispatch_tick()
            except Exception:
                pass  # a single bad tick must never kill the dispatcher thread

    def _peek(self, owner: Optional[str]) -> Optional[str]:
        with self._lock:
            q = self._queues.get(owner)
            return q[0] if q else None

    def _peek_all(self, owner: Optional[str]) -> list[str]:
        with self._lock:
            q = self._queues.get(owner)
            return list(q) if q else []

    def _pop_if_head(self, owner: Optional[str], job_id: str) -> bool:
        """Pops job_id only if it is still genuinely at the head of
        owner's queue -- guards against a concurrent dequeue() (cancel())
        having removed it (or reordered things) between this tick's peek
        and this call."""
        with self._lock:
            q = self._queues.get(owner)
            if not q or q[0] != job_id:
                return False
            q.popleft()
            self._queued_ids.discard(job_id)
            if not q:
                del self._queues[owner]
                if owner in self._order:
                    self._order.remove(owner)
            return True

    def _dispatch_tick(self) -> None:
        """One dispatcher pass. Takes a single host-headroom snapshot --
        its own ~1s block is this tick's pacing, the same role it always
        played inline in the old per-worker-thread polling loop -- and
        skips even taking it when nothing is queued, so an idle scheduler
        stays quiescent rather than burning a CPU sample every second for
        no reason.

        Walks the round-robin order once, giving each owner with a queued
        job exactly one admission ATTEMPT per tick (not one admission --
        an owner whose head job is blocked by their own per-user cap
        loses their turn for this tick, same as everyone else, rather
        than being retried in a way that starves the next owner in line).
        Spends one snapshot's idle-core budget across as many admissions
        as it allows within that single walk, decrementing a local
        counter rather than re-snapshotting per admission -- consistent
        with this admission machinery's existing soft/eventually-
        consistent posture (the caps are the hard bound; a headroom read
        that's stale by a few hundred milliseconds is not).

        Never spawns anything itself: `self._on_admit(job_id)` is
        required to return immediately (see JobManager._on_admit's own
        docstring) -- the actual subprocess spawn-and-block happens on a
        separate worker-pool thread. A slow on_admit here would stall
        admission for every other queued job, across every owner, for as
        long as it took.
        """
        with self._lock:
            owners_snapshot = list(self._order)
        if not owners_snapshot:
            return

        has_headroom, n_idle, message = self._resources_available()
        if not has_headroom:
            for owner in owners_snapshot:
                for job_id in self._peek_all(owner):
                    write_status(job_id, "pending", message)
            return

        idle_budget = n_idle
        n = len(owners_snapshot)
        start = self._rr_pos % n
        for i in range(n):
            idx = (start + i) % n
            owner = owners_snapshot[idx]
            self._rr_pos = idx + 1  # next tick resumes just past here, admitted or not
            if idle_budget < N_CORES:
                continue  # out of this tick's budget, but still let later owners take their turn in rotation next time
            job_id = self._peek(owner)
            if job_id is None:
                continue
            reason = self._block_reason(job_id)
            if reason is not None:
                write_status(job_id, "pending", reason)
                continue
            if self._pop_if_head(owner, job_id):
                idle_budget -= N_CORES
                self._on_admit(job_id)
