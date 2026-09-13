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
    job_index,
    TERMINAL_STATUSES as _TERMINAL_STATUSES,
    master_dispatch_guard,
    BATCH_ONLY_PARAM_KEYS, JobResult, JobSpec, read_result, read_spec, read_status, sub_job_ids_of, write_result,
    write_status,
)
from app.chemistry.jobs import batch_aggregate
from app.chemistry.jobs.geometry_resolve import constraints_for_geometry
from app.chemistry.registry2.tasks import BATCH_CHILD_TASKS
from app.config import JOBS_DIR, MASTER_MAX_IN_FLIGHT

_POLL_INTERVAL_SECONDS = 3.0

# Guards `_dispatch_more`'s whole decide-then-dispatch section -- same
# double-dispatch-prevention role as scan_orchestrator.py's own
# dispatch_lock.
dispatch_lock = threading.Lock()


def _iter_running_batch_masters():
    # R-075: reads the shared, ~1 s index in base.py instead of walking
    # JOBS_DIR and parsing two JSON files per job every three seconds. This loop ran
    # whether or not anything was running, so its cost grew with every job
    # ever run rather than with the work in front of it, and three
    # orchestrators plus the job watcher were each paying it separately.
    for job_id, (task, _parent, status) in job_index().items():
        if task == "batch" and status == "running":
            yield job_id


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
        # Per-master, not just per-tick -- see scan_orchestrator.py's own
        # _poll_once for why an unguarded loop here lets one bad master
        # (raising on every tick) silently starve every other running
        # master indefinitely, not just itself. Found live in that module;
        # fixed identically here since this loop has the same shape.
        for master_id in _iter_running_batch_masters():
            try:
                self._update_one(master_id)
            except Exception:
                pass

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
        # dispatch_lock guards this process's threads; the guard beside it
        # guards other PROCESSES sharing data/jobs/ -- see
        # base.master_dispatch_guard for the race and its signature.
        dispatched_here = False
        with dispatch_lock, master_dispatch_guard(master_id):
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
            # Chaining orbitals makes each child depend on the one before
            # it, so the wave has to be exactly one deep: child i+1 cannot
            # be built until child i has finished and produced the orbitals
            # it starts from. This is the cost the approval card warns
            # about -- a chained batch is serial where an ordinary one is
            # not.
            chain_orbitals = bool(master_spec["params"].get("chain_orbitals"))
            in_flight_cap = 1 if chain_orbitals else MASTER_MAX_IN_FLIGHT
            available = in_flight_cap - non_terminal
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

            # With chaining on, each child starts from the orbitals of the
            # child before it, so the active space is carried along the path
            # instead of being re-guessed at every geometry. That is what
            # keeps a CASSCF active space from flipping character as a scan
            # passes through a crossing. Index 0 has no predecessor and
            # starts from a fresh guess as usual.
            previous_child_id = None
            if chain_orbitals and to_dispatch and to_dispatch[0] > 0:
                for sid in sub_ids:
                    sub_spec = read_spec(sid)
                    if (sub_spec or {}).get("params", {}).get("_batch_index") == to_dispatch[0] - 1:
                        previous_child_id = sid
                        break
                if previous_child_id is None:
                    return  # predecessor not on disk yet -- try again next tick

            mgr = get_job_manager()
            for i in to_dispatch:
                child_params = {**sub_params, "_batch_index": i}
                if chain_orbitals and previous_child_id is not None:
                    child_params["initial_orbitals_job_id"] = previous_child_id
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
                # A constraint that names a coordinate but no value is held
                # at whatever value THIS geometry already has -- the relaxed
                # scan shape. Measured per child, on the child's own
                # structure, by the same helper the preview builder used for
                # child 0 (app/agent/tools.constraints_for_geometry), so the
                # approved card and the dispatched job agree.
                if child_params.get("constraints"):
                    child_params["constraints"] = constraints_for_geometry(
                        child_params["constraints"], child_molecule)
                sub_spec = JobSpec(
                    task=child_task, subtype=child_subtype, method=master_spec.get("method") or "",
                    engine=master_spec["engine"], molecule=child_molecule,
                    params=child_params, parent_job_id=master_id,
                )
                mgr.submit(sub_spec)
                dispatched_here = True

        # R-043/R-075: the wave's one quota sweep, run once here rather than
        # once inside every child's submit(). enforce_quota() walks every
        # non-terminal job's directory with rglob, so a forty-child wave used
        # to run forty full sweeps back to back, each of them rglob-ing up to
        # twenty live engine scratch directories. Deliberately outside
        # dispatch_lock: the sweep is slow disk I/O and the lock exists to
        # keep two dispatch decisions apart, not to serialise disk work. Also
        # deliberately after the whole wave rather than before it, so what it
        # measures includes what was just placed.
        if dispatched_here:
            from app.chemistry.jobs.quota import enforce_quota
            enforce_quota()

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
        # Counts alone answer "did it finish", not "what does it show". For
        # the child tasks with one headline number per state or pair, the
        # children's results are collected into a curve against the source
        # scan's own coordinate -- see batch_aggregate's docstring for which
        # tasks and why the optimization families are left out.
        artifacts = dict(result.get("artifacts", {}))
        extra_summary, extra_artifacts = batch_aggregate.aggregate(
            master_id, master_spec, sub_ids, n, str(JOBS_DIR / master_id))
        summary.update(extra_summary)
        artifacts.update(extra_artifacts)
        write_result(JobResult(master_id, "completed", summary=summary, artifacts=artifacts))
        write_status(master_id, "completed", f"batch complete ({n_terminal - n_failed} of {len(sub_ids)} jobs succeeded)")


_orchestrator: Optional[BatchOrchestrator] = None


def get_batch_orchestrator() -> BatchOrchestrator:
    global _orchestrator
    if _orchestrator is None:
        _orchestrator = BatchOrchestrator()
    return _orchestrator
