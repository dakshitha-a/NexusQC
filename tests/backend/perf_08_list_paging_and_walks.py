#!/usr/bin/env python3
"""P5.1: the polled paths stop re-walking the archive, and the list routes
can be paged.

    PYTHONPATH=$PWD python3 tests/backend/perf_08_list_paging_and_walks.py

Six findings from the 2026-09 review, all of the same shape: a cost that
grows with everything the deployment has ever done, paid on a fixed timer or
on every poll.

R-080, opt-in paging. `GET /api/jobs` walks every job directory and returns
one row per job, and every open tab polls it every four seconds. Measured in
the review at 5.5 ms median with 8 jobs and 20.9 ms with 58, so roughly
linear, which is about 100 ms per poll at a few hundred jobs. Five more list
routes had the same unbounded shape. The fix is opt-in, and the checks below
pin the "opt-in" half as hard as the paging half: a request with no `limit`
must return the plain array it always returned, because the two-sided cleanup
diff this project's testing rests on reads the full list, and a truncating
default would have made every one of those comparisons quietly incomplete
instead of loudly wrong.

R-051 and R-075, the shared index. Five loops each answered "what is on disk
and what state is it in" by walking JOBS_DIR and parsing two JSON files per
job: three orchestrators every three seconds, the job watcher every two, and
`_running_job_ids` once per queued owner per dispatch tick, plus
`GET /api/admin/activity` on every poll of the admin console. They read one
shared, one-second index now.

R-039, the watcher. A job that has reached a terminal state and has already
been reported cannot change again, and its status.json was re-read every two
seconds for the life of the process anyway, for every job of every
conversation, for ever.

R-081, the NEB trailing window. The live-path route read and split the whole
trajectory file on every poll to keep the last few frames, while the file
grows by one full path's worth of frames every NEB iteration.

R-075's last part, the scheduler. While the host has no headroom, the
dispatch tick rewrote status.json for every queued job of every owner about
once a second, almost always with the identical message.

Everything here is in-process except the route-shape checks, which are marked
and which need the stack.
"""
from __future__ import annotations

import inspect
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "tests"))

from fixtures import check, summary  # noqa: E402


def section(title: str):
    """Run one section, turning anything it cannot import or find into a
    reported FAIL rather than a traceback.

    Every check in this file compares the code against a fix, so the "before"
    run of it is expected to be missing names. A traceback there would end the
    run at the first one and hide every other check; a FAIL says what was
    missing and lets the rest of the file speak.
    """
    def wrap(fn):
        def run():
            print(f"\n== {title} ==")
            try:
                fn()
            except Exception as exc:  # noqa: BLE001
                check(title, False, f"{type(exc).__name__}: {exc}")
        run.__name__ = fn.__name__
        return run
    return wrap


@section('a list route with no limit returns exactly what it always did')
def _section_1() -> None:
    from server.routes._paging import LIST_PAGE_LIMIT_MAX, paged

    rows = [{"i": i} for i in range(250)]
    same = paged(rows, 0, None)
    check("no limit returns the list itself, not a page object",
          isinstance(same, list) and same == rows, type(same).__name__)

    page = paged(rows, 0, 10)
    check("a limit returns a page object with the total",
          isinstance(page, dict) and page["total"] == 250 and len(page["rows"]) == 10,
          "" if isinstance(page, dict) else type(page).__name__)
    check("the page starts where the offset says",
          paged(rows, 40, 5)["rows"] == rows[40:45])
    check("an offset past the end is an empty page, not an error",
          paged(rows, 9999, 5)["rows"] == [])
    check("a limit past the ceiling is clamped rather than honoured",
          len(paged(rows, 0, 100000)["rows"]) == min(len(rows), LIST_PAGE_LIMIT_MAX),
          f"ceiling={LIST_PAGE_LIMIT_MAX}")
    check("a negative offset is treated as the start",
          paged(rows, -5, 3)["rows"] == rows[0:3])


@section('a conversation is windowed from its end, not its front')
def _section_2() -> None:
    from server.routes._paging import tail_window
    msgs = list(range(100))
    window, total = tail_window(msgs, 10)
    check("the window holds the LAST n messages", window == msgs[-10:], str(window))
    check("the true total comes back with it", total == 100, str(total))
    check("no limit returns everything and the real total",
          tail_window(msgs, None) == (msgs, 100))

    # ---- R-051 / R-075: the shared index ------------------------------


@section('one shared index answers what five loops used to walk for')
def _section_3() -> None:
    from app.chemistry.jobs import base as jobs_base

    jobs_base.invalidate_job_index()
    t0 = time.perf_counter()
    first = jobs_base.job_index()
    cold_ms = (time.perf_counter() - t0) * 1000
    t1 = time.perf_counter()
    second = jobs_base.job_index()
    warm_ms = (time.perf_counter() - t1) * 1000
    print(f"  {len(first)} jobs on disk: cold build {cold_ms:.2f} ms, cached read {warm_ms:.4f} ms")
    check("the index is a dict of job_id -> (task, parent, status)",
          all(isinstance(v, tuple) and len(v) == 3 for v in first.values()),
          "")
    check("a second read inside the TTL is served from the cache, not rebuilt",
          second is first, "" if second is first else "a fresh dict came back")
    check("the cached read is at least ten times cheaper than the walk",
          warm_ms * 10 < max(cold_ms, 0.01),
          f"cold {cold_ms:.3f} ms vs cached {warm_ms:.4f} ms")

    jobs_base.invalidate_job_index()
    check("invalidating drops it, so the next read rebuilds",
          jobs_base.job_index() is not first)


@section('the orchestrators and the admission gate read that index')
def _section_4() -> None:
    from app.chemistry.jobs import base as jobs_base
    from app.chemistry.jobs import batch_orchestrator, ensemble_orchestrator, scan_orchestrator

    for name, fn in (
        ("scan", scan_orchestrator._iter_running_scan_masters),
        ("ensemble", ensemble_orchestrator._iter_running_ensemble_masters),
        ("batch", batch_orchestrator._iter_running_batch_masters),
        ("the admission gate", jobs_base._running_job_ids),
    ):
        src = inspect.getsource(fn)
        check(f"{name} reads job_index() rather than walking JOBS_DIR",
              "job_index()" in src and "JOBS_DIR.iterdir()" not in src,
              "")

    src = inspect.getsource(jobs_base.write_status)
    check("write_status invalidates the index, so a change here is visible at once",
          "invalidate_job_index()" in src, "")

    # ---- R-039: the watcher skips settled jobs ------------------------


@section('the watcher stops re-reading jobs that can never change')
def _section_5() -> None:
    from app.agent.job_watcher import JobWatcher
    from app.agent.job_watcher import JobWatcher
    src = inspect.getsource(JobWatcher._poll_once)
    check("a terminal, already-reported job is skipped before the status read",
          "_last_status.get(job_id)" in src and "continue" in src.split("_last_status.get(job_id)")[1][:200],
          "")

    # ---- R-040: the quota pass is off the watcher thread ---------------


@section("quota enforcement no longer runs on the watcher's own thread")
def _section_6() -> None:
    from app.agent.job_watcher import JobWatcher
    loop_src = inspect.getsource(JobWatcher._loop)
    check("the loop starts the pass rather than calling it inline",
          "_start_quota_pass()" in loop_src and "enforce_all_quotas()" not in loop_src,
          "")
    pass_src = inspect.getsource(JobWatcher._start_quota_pass)
    check("the pass runs on its own thread", "threading.Thread(" in pass_src)
    check("a pass still running skips the next tick rather than stacking threads",
          "_quota_pass_running" in pass_src)

    # ---- R-075: the scheduler stops rewriting identical messages -------


@section("a queued job's status is rewritten only when it changes")
def _section_7() -> None:
    from app.chemistry.jobs.scheduler import JobScheduler
    sched_src = inspect.getsource(JobScheduler._dispatch_tick)
    check("the no-headroom branch compares against the last message written",
          "_last_pending_message" in sched_src, "")
    for fn_name in ("dequeue", "_pop_if_head"):
        fn = getattr(JobScheduler, fn_name, None)
        if fn is None:
            continue
        check(f"{fn_name} forgets the remembered message, so the cache cannot grow",
              "_last_pending_message.pop" in inspect.getsource(fn), "")

    # ---- R-043 / R-075: one quota sweep per wave, not per child --------


@section('a wave of sub-jobs runs one quota sweep, not one per child')
def _section_8() -> None:
    from app.chemistry.jobs import base as jobs_base
    from app.chemistry.jobs import batch_orchestrator, ensemble_orchestrator, scan_orchestrator
    submit_src = inspect.getsource(jobs_base.JobManager.submit)
    check("submit() skips the sweep for a sub-job",
          "if not spec.parent_job_id:" in submit_src, "")
    for name, cls in (("scan", scan_orchestrator.ScanOrchestrator),
                      ("ensemble", ensemble_orchestrator.EnsembleOrchestrator),
                      ("batch", batch_orchestrator.BatchOrchestrator)):
        src = inspect.getsource(cls._dispatch_more)
        check(f"the {name} orchestrator runs it once for the wave, outside the dispatch lock",
              "enforce_quota()" in src and src.index("with dispatch_lock") < src.index("enforce_quota()"),
              "")

    # ---- R-081: the NEB route reads a trailing window ------------------


@section('the live NEB path is read from the end of the file')
def _section_9() -> None:
    from server.routes import jobs as jobs_routes
    neb_src = inspect.getsource(jobs_routes.get_neb_frames_live)
    check("it seeks rather than reading the whole trajectory",
          "f.seek(" in neb_src, "")
    check("a window read is realigned to a frame boundary",
          "isdigit()" in neb_src,
          "a mid-frame start would be handed to split_xyz_frames")


def main() -> None:
    _section_1()
    _section_2()
    _section_3()
    _section_4()
    _section_5()
    _section_6()
    _section_7()
    _section_8()
    _section_9()
    summary()




if __name__ == "__main__":
    main()
