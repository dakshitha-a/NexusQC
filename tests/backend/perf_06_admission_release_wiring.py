#!/usr/bin/env python3
"""Every path out of an admitted job hands its cap slot back.

`perf_05` proves the arithmetic: the scheduler counts what it has admitted
and not yet released, so the concurrency cap holds between dispatch ticks
and not only within one. That arithmetic is only as good as the release, and
the release is JobManager's job, on the other side of a callable the
scheduler knows nothing about. This covers that half.

Why it is worth its own script. The two failures are not symmetric. An
over-admission is transient: the extra job runs, finishes, and the cap
recovers on its own. A slot that is never released is permanent for the life
of the backend process, and it silently shrinks the cap by one every time it
happens, so a deployment configured for four concurrent jobs quietly becomes
one configured for three, then two. Nothing surfaces that. Every job simply
waits a little longer, forever.

`JobManager._run`'s `finally` is deliberately the single place that
releases, because it is the one path every outcome passes through --
completed, failed, and cancelled mid-run alike. `_on_admit` covers the two
cases where `_run` never happens at all: the job directory vanished between
admission and dispatch, and the executor refused the submit because the pool
is shutting down.

Calls the real `_run` and `_on_admit` against a stand-in `self` rather than
constructing a JobManager, which would reconcile orphans and start a
dispatcher thread against the real data directory. Needs no stack.

Run:  PYTHONPATH=$PWD python3 tests/backend/perf_06_admission_release_wiring.py
"""
from __future__ import annotations

import sys
import threading
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from fixtures import check, summary  # noqa: E402

from app.chemistry.jobs import base as base_mod  # noqa: E402
from app.chemistry.jobs.base import JobManager  # noqa: E402

JOB_ID = "fictional-job-0000"


class FakeScheduler:
    def __init__(self) -> None:
        self.released: list[str] = []

    def release(self, job_id: str) -> None:
        self.released.append(job_id)

    def wake(self) -> None:
        pass


class FakeSpec:
    job_id = JOB_ID
    engine = "pyscf"
    task = "single_point"

    def to_dict(self) -> dict:
        return {}


class Stub:
    """Just the attributes _run and _on_admit actually touch."""

    def __init__(self, run_inner: Any = None, submit: Any = None) -> None:
        self._lock = threading.Lock()
        self._futures: dict[str, Any] = {JOB_ID: object()}
        self._scheduler = FakeScheduler()
        self._run_inner = run_inner or (lambda spec: None)
        self._run = lambda spec: None  # _on_admit hands this to the executor
        self._executor = type("E", (), {"submit": staticmethod(submit or (lambda *a: object()))})()


def main() -> None:
    # _run's finally cleans up the job's scratch directory. These job ids back
    # no real job, so the cleanup is stubbed rather than pointed at data/.
    import app.chemistry.jobs.scratch as scratch_mod
    scratch_mod.cleanup_scratch_files = lambda *a, **k: None

    # --- _run: the path every outcome passes through ----------------------
    s = Stub()
    JobManager._run(s, FakeSpec())
    check(
        "a job that finishes normally releases its slot",
        s._scheduler.released == [JOB_ID],
        str(s._scheduler.released),
    )
    check(
        "and its Future is dropped, which is what that finally already did",
        JOB_ID not in s._futures,
        str(list(s._futures)),
    )

    def boom(spec):
        raise RuntimeError("the worker died")

    s = Stub(run_inner=boom)
    try:
        JobManager._run(s, FakeSpec())
    except RuntimeError:
        pass
    check(
        "a job that raises releases its slot on the way out",
        s._scheduler.released == [JOB_ID],
        f"{s._scheduler.released} -- an exception here would hold the slot for the "
        "life of the process, and the cap would silently shrink by one",
    )

    # --- _on_admit: the two paths where _run never happens ----------------
    original_read_spec = base_mod.read_spec
    try:
        base_mod.read_spec = lambda job_id: None
        s = Stub()
        JobManager._on_admit(s, JOB_ID)
        check(
            "a job whose directory vanished between admission and dispatch releases its slot",
            s._scheduler.released == [JOB_ID],
            f"{s._scheduler.released} -- nothing will ever call _run's finally for this job",
        )

        base_mod.read_spec = lambda job_id: {}
        original_jobspec = base_mod.JobSpec
        base_mod.JobSpec = lambda **kw: FakeSpec()
        try:
            def refuse(*a, **k):
                raise RuntimeError("cannot schedule new futures after shutdown")

            s = Stub(submit=refuse)
            try:
                JobManager._on_admit(s, JOB_ID)
            except RuntimeError:
                pass
            check(
                "a job the executor refuses releases its slot before the error propagates",
                s._scheduler.released == [JOB_ID],
                str(s._scheduler.released),
            )

            # The ordinary path must NOT release: the job is about to run, and
            # its slot is legitimately occupied until _run's finally says
            # otherwise. Releasing here would put the cap back where it was.
            s = Stub()
            JobManager._on_admit(s, JOB_ID)
            check(
                "an ordinary admission does not release, since the job is about to run",
                s._scheduler.released == [],
                f"{s._scheduler.released} -- releasing on the happy path would undo the cap",
            )
            check(
                "and its Future is recorded",
                JOB_ID in s._futures,
                str(list(s._futures)),
            )
        finally:
            base_mod.JobSpec = original_jobspec
    finally:
        base_mod.read_spec = original_read_spec

    summary()


if __name__ == "__main__":
    main()
