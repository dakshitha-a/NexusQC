#!/usr/bin/env python3
"""A job's recorded state survives cancellation, a restart and concurrency.
Regression test for R-029, R-031, R-071 and R-073.

    PYTHONPATH=$PWD python3 tests/backend/jobs_05_state_integrity.py

Four ways a job's own record could be lost or corrupted, all in
app/chemistry/jobs/base.py, all reachable without an engine.

R-071 is measured rather than argued. `_atomic_write_text` named its temp
file after the pid alone, so two THREADS of one process computed the same
temp path: one truncates the file the other is mid-write into, whichever
`os.replace` wins publishes torn content, and the winner unlinks the temp
file out from under the loser, whose own replace then raises
FileNotFoundError -- from inside a `finally`, in `_run_inner`'s terminal
write. The old implementation is reproduced below and run against the same
stress as the new one, so the numbers are comparable.

R-029: cancelling a master carried its summary into the cancelled result and
not its artifacts, and `JobResult.artifacts` defaults to `{}`, so `path_xyz`
and `ensemble_xyz` were erased. Every reader resolves the frame slider, the
path download and "start a job from image 3" through that dict, so a
cancelled 40-image scan kept 39 finished geometries on disk with nothing able
to reach them.

R-073: the same cancel wrote the master's terminal status AFTER cancelling
the children it had snapshotted, holding no dispatch guard, so an
orchestrator tick already inside `_dispatch_more` submitted a wave
afterwards. Those children are not in the snapshot and their master is
terminal, so no later tick reconciles them: they run, bill the owner's quota,
and nothing ever reads them.

R-031: startup reconciliation read `result.json`, then did four more file and
process lookups, and only then wrote a `failed` result -- overwriting
whatever the worker landed in between. Case 1 of that same function exists to
say a worker's own result is authoritative.
"""
from __future__ import annotations

import inspect
import json
import os
import tempfile
import threading
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO))

from tests.fixtures import check, summary  # noqa: E402

from app.chemistry.jobs import base as jobs_base  # noqa: E402

print("R-071: two threads writing one status.json\n")


def _old_atomic_write_text(path: Path, text: str) -> None:
    """The implementation this replaced, for the comparison below."""
    tmp = path.with_suffix(path.suffix + f".tmp{os.getpid()}")
    tmp.write_text(text)
    os.replace(tmp, path)


def stress(writer, n_writers: int = 8, n_writes: int = 300) -> tuple[int, int]:
    """(writer errors, torn reads) for `writer` under concurrent writers and
    readers on one file."""
    d = Path(tempfile.mkdtemp(prefix="r071-"))
    f = d / "status.json"
    errs: list[str] = []
    torn: list[str] = []

    def w(i: int) -> None:
        for _ in range(n_writes):
            try:
                writer(f, json.dumps({"status": "running", "n": i, "pad": "x" * 200}))
            except Exception as exc:                            # noqa: BLE001
                errs.append(type(exc).__name__)

    def r() -> None:
        for _ in range(n_writes * 10):
            try:
                if f.exists():
                    json.loads(f.read_text())
            except FileNotFoundError:
                pass
            except Exception as exc:                            # noqa: BLE001
                torn.append(type(exc).__name__)

    threads = [threading.Thread(target=w, args=(i,)) for i in range(n_writers)]
    threads += [threading.Thread(target=r) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    leftover = [p.name for p in d.iterdir() if ".tmp" in p.name]
    return len(errs), len(torn), leftover


old_errs, old_torn, _ = stress(_old_atomic_write_text)
new_errs, new_torn, leftover = stress(jobs_base._atomic_write_text)

print(f"  old (pid-only temp name): {old_errs} writer error(s), {old_torn} torn read(s)")
print(f"  now:                      {new_errs} writer error(s), {new_torn} torn read(s)")
check("no writer raises", new_errs == 0, f"{new_errs}",
      f"{new_errs} of them, against {old_errs} for the implementation this replaced")
check("no reader ever sees a truncated file", new_torn == 0, f"{new_torn}",
      f"{new_torn} torn reads, against {old_torn} before")
check("and no temp file is left behind", not leftover, "", f"{leftover}")
check("the comparison is meaningful: the old one really does fail this",
      old_errs > 0 or old_torn > 0, f"{old_errs} errors, {old_torn} torn",
      "the stress did not reproduce the race, so the numbers above prove nothing")

print("\nR-029 and R-073: cancelling a master")
src = inspect.getsource(jobs_base.JobManager.cancel)
check("the cancelled result carries the master's artifacts, not just its summary",
      'artifacts=previous.get("artifacts", {})' in src, "",
      "path_xyz and ensemble_xyz are still erased, so a cancelled scan's "
      "geometries become unreachable")
check("the cancel runs inside the same dispatch guard the orchestrators take",
      "with master_dispatch_guard(job_id):" in src, "",
      "a tick already inside _dispatch_more can still submit a wave of "
      "children nothing will cancel or aggregate")
guard_at = src.index("master_dispatch_guard") if "master_dispatch_guard" in src else -1
status_at = src.index('write_status(job_id, "cancelled"') if 'write_status(job_id, "cancelled"' in src else -1
sweep_at = src.index("for sub_id in sub_job_ids_of(job_id):") if "sub_job_ids_of" in src else -1
check("and writes the master's terminal status before sweeping the children",
      0 < status_at < sweep_at, f"status at {status_at}, sweep at {sweep_at}",
      "a tick starting between the two still sees a running master")

print("\nR-031: reconciliation does not overwrite a result that landed late")
rsrc = inspect.getsource(jobs_base.JobManager._reconcile_orphaned_jobs)
check("the failed branch re-reads result.json at the point of decision",
      "landed = read_result(job_id)" in rsrc, "",
      "the read is still several file and process lookups earlier, so a "
      "worker that finished in that window has its result overwritten")
after_reread = rsrc.split("landed = read_result")[1][:400] if "landed = read_result" in rsrc else ""
check("and treats a terminal result as a recovery rather than a failure",
      "recovered after a server restart" in after_reread, "",
      "there is no re-read, so nothing can treat it as one")

summary()
