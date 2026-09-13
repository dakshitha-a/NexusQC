#!/usr/bin/env python3
"""A long job is not a broken job, and a bad spec does not eat a slot.
Regression test for R-011 and R-012, with R-072 and R-056 alongside them.

    PYTHONPATH=$PWD python3 tests/backend/jobs_04_job_timeout_and_dispatch.py

R-011. Every job was hard-killed after six hours. The value was written as
`6 * 3600` in four files, appeared in no documentation, and could be
overridden by nothing, while every other threshold in this subsystem is a
QC_AGENT_* variable. README line 613 said the opposite in as many words: "A
CASSCF job can run for hours. Close the tab and come back." Multi-hour CASSCF
and CASPT2 runs are this application's design premise, so the cap destroyed
real compute and reported it as a failure.

The user's decision, on 2026-09-13, was that the replacement
`QC_AGENT_JOB_TIMEOUT_HOURS` defaults to disabled: a hung engine is stopped by
the kill and cancel buttons, which exist, and a cap that fires on a legitimate
calculation is the worse failure.

R-012. `_watch_orphan_worker` waited on a re-attached worker with
`wait(timeout=6 * 3600)` inside `except Exception: pass`, so giving up waiting
and the process exiting were the same event. Six hours after a server restart
a still-computing worker was marked `failed`, its pid was dropped so `cancel()`
could no longer reach the live process, and the eventual `completed`
result.json disagreed with the status until the next restart. The orphan
machinery exists so a status always reaches terminal; a WRONG terminal status
on a job that is still running is the same defect wearing the other face.

R-072. `JobSpec(**spec_dict)` sat one line outside `_on_admit`'s try, so a
spec.json that parses as JSON but is not valid JobSpec kwargs raised a
TypeError that leaked the scheduler's admission slot for the life of the
process, against both the total cap and that user's per-user cap, and left the
job at `pending` for ever with no log line, because the dispatcher loop
swallowed the exception with a bare `pass`.

R-056: `update.sh` and `check_destructive.sh` both told the operator that
PENDING jobs would be killed by a restart. They are re-enqueued.

Runs in process against a stubbed scheduler and executor: no engines, no
subprocesses, no six-hour wait.
"""
from __future__ import annotations

import inspect
import json
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO))

from tests.fixtures import check, summary  # noqa: E402

print("R-011: the job timeout is a setting, and it is off\n")

import app.config as cfg  # noqa: E402
from app.chemistry.jobs import base as jobs_base  # noqa: E402

print("1. the setting")
# Guarded rather than assumed, so this script reports the finding instead of
# a traceback when run against the code as it was.
has_setting = hasattr(cfg, "JOB_TIMEOUT_HOURS") and hasattr(cfg, "job_timeout_seconds")
check("app/config.py has a job-timeout setting at all", has_setting, "",
      "the six-hour cap is a literal in four files and overridable by nothing")
if has_setting:
    check("QC_AGENT_JOB_TIMEOUT_HOURS defaults to disabled",
          cfg.JOB_TIMEOUT_HOURS == 0 and cfg.job_timeout_seconds() is None,
          f"hours={cfg.JOB_TIMEOUT_HOURS}, seconds={cfg.job_timeout_seconds()}")
    _real = cfg.JOB_TIMEOUT_HOURS
    for hours, want in ((2, 7200.0), (0.5, 1800.0), (0, None), (-1, None)):
        cfg.JOB_TIMEOUT_HOURS = hours
        check(f"{hours} h -> {want}", cfg.job_timeout_seconds() == want,
              f"{cfg.job_timeout_seconds()}")
    cfg.JOB_TIMEOUT_HOURS = _real

print("\n2. no six-hour literal survives anywhere that runs a job")
# `timeout=6 * 3600` is the shape that mattered; the bare arithmetic also
# appears inside docstrings explaining what was removed, which is not a
# regression and should not read as one.
offenders = []
for path in sorted((REPO / "app").rglob("*.py")) + sorted((REPO / "scripts").glob("*.sh")):
    for i, line in enumerate(path.read_text().splitlines(), 1):
        if "timeout=6 * 3600" in line:
            offenders.append(f"{path.relative_to(REPO)}:{i}")
check("no hard-coded six-hour timeout anywhere that runs a job",
      not offenders, "", "; ".join(offenders))

for mod, n in (("app/chemistry/jobs/base.py", 1),
               ("app/chemistry/jobs/orca_runner.py", 2),
               ("app/chemistry/jobs/bagel_runner.py", 1)):
    src = (REPO / mod).read_text()
    got = src.count("timeout=job_timeout_seconds()")
    check(f"{mod} takes its timeout from the setting ({n} site(s))", got == n, f"{got} site(s)")

print("\n3. R-012: giving up waiting is not the process exiting")
src = inspect.getsource(jobs_base.JobManager._watch_orphan_worker)
check("the orphan watcher polls in a loop rather than waiting once",
      "while True:" in src and "_ORPHAN_POLL_SECONDS" in src, "",
      "a single bounded wait still finalises a live job when it expires")
check("and a TimeoutExpired continues rather than falling through",
      "except psutil.TimeoutExpired:" in src and "continue" in src, "",
      "TimeoutExpired is still swallowed with every other exception")
poll = getattr(jobs_base, "_ORPHAN_POLL_SECONDS", None)
check("the poll interval is short enough to finalise promptly",
      poll is not None and 0 < poll <= 120, f"{poll}s")

print("\n4. R-072: a spec that will not load releases its slot and says so")


class _Scheduler:
    def __init__(self):
        self.released = []

    def release(self, job_id):
        self.released.append(job_id)


class _Executor:
    def submit(self, fn, spec):
        raise AssertionError("a job with an unloadable spec must never reach the executor")


tmp = Path(tempfile.mkdtemp(prefix="r072-"))
real_jobs_dir = jobs_base.JOBS_DIR
jobs_base.JOBS_DIR = tmp
try:
    bad = tmp / "badspec"
    bad.mkdir()
    (bad / "spec.json").write_text(json.dumps({"job_id": "badspec", "unexpected_key": 1}))
    (bad / "status.json").write_text(json.dumps({"status": "pending", "message": "queued"}))

    mgr = object.__new__(jobs_base.JobManager)
    mgr._scheduler = _Scheduler()
    mgr._executor = _Executor()
    mgr._futures = {}
    import threading
    mgr._lock = threading.RLock()

    # The finding itself is that this raises out of _on_admit, into the
    # dispatcher thread, which swallows it. Caught here so the log reads as a
    # failed check rather than a traceback.
    try:
        jobs_base.JobManager._on_admit(mgr, "badspec")
        check("_on_admit handles a spec it cannot load", True, "no exception")
    except Exception as exc:
        check("_on_admit handles a spec it cannot load", False, "",
              f"{type(exc).__name__}: {exc}")
    check("the admission slot is handed back", mgr._scheduler.released == ["badspec"],
          f"released={mgr._scheduler.released}",
          "the slot counts against the total and per-user caps for the life of the process")
    status = json.loads((bad / "status.json").read_text())
    check("the job reaches a terminal status instead of sitting at pending",
          status.get("status") == "failed", f"status={status.get('status')!r}",
          f"status={status.get('status')!r}: a job stuck at pending with no explanation "
          f"is the hardest state here to diagnose")
    result = json.loads((bad / "result.json").read_text()) if (bad / "result.json").exists() else {}

    check("and says what to do about it",
          "spec.json" in str(result.get("error") or ""), f"{str(result.get('error'))[:70]}...")

    # A vanished job dir still releases, which is the branch that always worked.
    mgr._scheduler.released.clear()
    jobs_base.JobManager._on_admit(mgr, "no-such-job")
    check("a vanished job directory still releases its slot",
          mgr._scheduler.released == ["no-such-job"], f"{mgr._scheduler.released}")
finally:
    jobs_base.JOBS_DIR = real_jobs_dir

from app.chemistry.jobs import scheduler as sched_mod  # noqa: E402

loop_src = inspect.getsource(sched_mod.JobScheduler._loop)
check("and the dispatcher logs a failed tick rather than passing silently",
      "logger.exception" in loop_src, "",
      "a bare pass here is what made the leaked slot invisible")

print("\n5. R-056: a queued job is not a lost job")
up = (REPO / "scripts" / "update.sh").read_text()
cd = (REPO / "scripts" / "check_destructive.sh").read_text()
check("update.sh counts running and pending separately",
      "RUNNING_JOBS" in up and "PENDING_JOBS" in up, "")
check("update.sh no longer says pending jobs will be killed",
      "running or pending, and they will be killed" not in up, "")
check("update.sh says queued jobs are re-queued",
      "re-queues them" in up, "")
check("check_destructive.sh reports only running jobs as destroyed",
      "jobs are RUNNING and will be killed" in cd, "")
check("and tells the operator queued jobs are safe",
      "re-queued on the next start" in cd, "")

print("\n6. the setting is documented where an operator would look")
for path, needle in (("README.md", "QC_AGENT_JOB_TIMEOUT_HOURS"),
                     ("docs/CONFIGURATION.md", "QC_AGENT_JOB_TIMEOUT_HOURS"),
                     (".env.example", "QC_AGENT_JOB_TIMEOUT_HOURS")):
    check(f"{path} mentions it", needle in (REPO / path).read_text(), "")

summary()
