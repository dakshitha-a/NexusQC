"""Background thread that wave-dispatches a `batch` "master" job's
per-geometry sub-jobs and rolls their status up into the master's own
result.json (P7.4).

A batch master (see app/chemistry/jobs/base.py's JobManager.submit_batch)
is never itself a dispatched subprocess -- it does no compute of its own,
only spawns one ordinary JobSpec per geometry in the source geometry_set,
all children the same task/subtype: the master's own `child_task` param
(single_point/opt/freq/opt_freq -- job types 1-4, see params.py and
tasks.BATCH_CHILD_TASKS) chosen once for the whole batch, not decided
per-child. Structurally this mirrors scan_orchestrator.py
closely (same daemon-thread/fixed-poll-interval shape, same wave-dispatch-
then-aggregate role, same dispatch_lock double-dispatch guard, same
"re-read the master's own path_xyz rather than persist the geometry list a
second time" sourcing), with one real simplification: a batch's children
are independent, unordered jobs -- there is no energy series, no PES plot,
no pooled spectrum to build once they are all terminal, only a completion
count. See that module's own docstring for the fuller reasoning this one
does not repeat.
"""
from __future__ import annotations

import threading
from pathlib import Path
from typing import Optional

from app.chemistry.geometry_upload import parse_multi_frame_xyz
from app.chemistry.jobs.base import (
    BATCH_ONLY_PARAM_KEYS, JobResult, JobSpec, read_result, read_spec, read_status, sub_job_ids_of, write_result,
    write_status,
)
from app.chemistry.registry2.tasks import BATCH_CHILD_TASKS
from app.config import JOBS_DIR, MASTER_MAX_IN_FLIGHT

_POLL_INTERVAL_SECONDS = 3.0
_TERMINAL_STATUSES = {"completed", "failed", "cancelled"}

# Guards `_dispatch_more`'s whole decide-then-dispatch section -- same
# double-dispatch-prevention role as scan_orchestrator.py's own
# dispatch_lock.
dispatch_lock = threading.Lock()


def _iter_running_batch_masters():
    # Duplicated (not imported) from base.py's private _iter_job_ids_on_disk,
    # same convention scan_orchestrator.py's own _iter_running_scan_masters
    # already follows.
    for d in JOBS_DIR.iterdir():
        if not d.is_dir() or d.name == "_seen" or not (d / "spec.json").exists():
            continue
        spec = read_spec(d.name)
        if spec and spec.get("task") == "batch" and (read_status(d.name) or {}).get("status") == "running":
            yield d.name


class BatchOrchestrator:
    def __init__(self):
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None

    def start(self) -> None:
        if self._thread is not None:
            return
        self._thread = threading.Thread(target=self._loop, daemon=True, name="batch-orchestrator")
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=5)
            self._thread = None

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                self._poll_once()
            except Exception:
                pass  # a single bad tick must never kill the orchestrator thread
            self._stop.wait(_POLL_INTERVAL_SECONDS)

    def _poll_once(self) -> None:
        for master_id in _iter_running_batch_masters():
            self._update_one(master_id)

    def _dispatch_more(self, master_id: str, master_spec: dict, n: int) -> None:
        """Tops up the in-flight wave of per-geometry children, if there's
        room and geometries left to dispatch. Re-reads the master's own
        artifacts['path_xyz'] (written in full by submit_batch, one frame
        per geometry, in source order) rather than persisting the geometry
        list a second time anywhere -- same reasoning
        scan_orchestrator.py's own _dispatch_more gives.

        Dispatches the actual MISSING `_batch_index` values, not a count --
        same reasoning submit_scan/submit_ensemble's own docstrings give:
        quota eviction can reap the batch's own earliest children before
        the rest finish, leaving a hole a count-based range would never
        revisit."""
        with dispatch_lock:
            from app.chemistry.jobs.base import get_job_manager
            sub_ids = sub_job_ids_of(master_id)
            existing_indices: set[int] = set()
            for sid in sub_ids:
                sub_spec = read_spec(sid)
                idx = (sub_spec or {}).get("params", {}).get("_batch_index")
                if idx is not None:
                    existing_indices.add(idx)
            if len(existing_indices) >= n:
                return
            non_terminal = sum(1 for sid in sub_ids if read_status(sid)["status"] not in _TERMINAL_STATUSES)
            available = MASTER_MAX_IN_FLIGHT - non_terminal
            if available <= 0:
                return
            missing = sorted(set(range(n)) - existing_indices)
            to_dispatch = missing[:available]
            if not to_dispatch:
                return

            master_result = read_result(master_id)
            path_xyz = (master_result or {}).get("artifacts", {}).get("path_xyz")
            if not path_xyz:
                return  # master's own result not written yet -- try again next tick
            frames = parse_multi_frame_xyz(Path(path_xyz).read_text())

            # path_xyz (plain xmol XYZ) carries only symbols/coords/name --
            # every geometry dict submit_batch's own initial-wave dispatch
            # used was instead a shallow copy of the FIRST geometry's own
            # dict (constant fields: charge/multiplicity/identifier/smiles/
            # source) with just symbols/coords/name overwritten, so
            # re-applying that same template here reconstructs an
            # identical molecule dict, not just a same-looking one.
            molecule_template = master_spec["molecule"]

            sub_params = {
                k: v for k, v in master_spec["params"].items()
                if k not in BATCH_ONLY_PARAM_KEYS and not k.startswith("_")
            }
            # child_task (params.py's ParamSpec, required with no default --
            # see its own docstring) picks which of job types 1-4 every
            # child runs; tasks.BATCH_CHILD_TASKS is the one place that
            # mapping lives (elicitation.py's capability checks and
            # app/agent/tools.py's preview builder use the same one).
            child_task, child_subtype = BATCH_CHILD_TASKS[master_spec["params"]["child_task"]]
            image0_raw_input = master_spec["params"].get("_image0_raw_input")
            mgr = get_job_manager()
            for i in to_dispatch:
                child_params = {**sub_params, "_batch_index": i}
                if i == 0 and image0_raw_input is not None:
                    # A hand-edited approval-card input only ever applies to
                    # whichever child was actually shown on the card (index
                    # 0) -- same single-job-only semantics as pes_1d's own
                    # image0_raw_input (see app/agent/tools.py's
                    # _finish_submission).
                    child_params["_raw_input"] = image0_raw_input
                child_molecule = {
                    **molecule_template,
                    "symbols": list(frames[i].symbols), "coords": frames[i].coords, "name": frames[i].name,
                }
                sub_spec = JobSpec(
                    task=child_task, subtype=child_subtype, method=master_spec.get("method") or "",
                    engine=master_spec["engine"], molecule=child_molecule,
                    params=child_params, parent_job_id=master_id,
                )
                mgr.submit(sub_spec)

    def _update_one(self, master_id: str) -> None:
        result = read_result(master_id)
        if result is None or result.get("status") != "running":
            return
        master_spec = read_spec(master_id)
        if master_spec is None:
            return

        summary = dict(result["summary"])
        n = summary["n_children"]

        sub_ids = sub_job_ids_of(master_id)
        if len(sub_ids) < n:
            self._dispatch_more(master_id, master_spec, n)
            sub_ids = sub_job_ids_of(master_id)  # re-read: may have grown just now

        n_terminal = sum(1 for sid in sub_ids if read_status(sid)["status"] in _TERMINAL_STATUSES)
        summary["n_dispatched"] = len(sub_ids)
        summary["n_complete"] = n_terminal

        if len(sub_ids) < n or n_terminal < len(sub_ids):
            write_result(JobResult(master_id, "running", summary=summary, artifacts=result.get("artifacts", {})))
            write_status(master_id, "running", f"{len(sub_ids)} of {n} jobs dispatched, {n_terminal} complete")
            return

        n_failed = sum(1 for sid in sub_ids if read_status(sid)["status"] == "failed")
        summary["n_failed"] = n_failed
        write_result(JobResult(master_id, "completed", summary=summary, artifacts=result.get("artifacts", {})))
        write_status(master_id, "completed", f"batch complete ({n_terminal - n_failed} of {len(sub_ids)} jobs succeeded)")


_orchestrator: Optional[BatchOrchestrator] = None


def get_batch_orchestrator() -> BatchOrchestrator:
    global _orchestrator
    if _orchestrator is None:
        _orchestrator = BatchOrchestrator()
    return _orchestrator
