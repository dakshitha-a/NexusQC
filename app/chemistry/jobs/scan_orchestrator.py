"""Background thread that wave-dispatches a pes_1d/interp_pes "master"
job's per-image sub-jobs and aggregates their results back into the
master's own result.json.

A pes_scan master (see app/chemistry/jobs/base.py's JobManager.submit_scan)
is never itself a dispatched subprocess -- it does no compute of its own,
only spawns one ordinary JobSpec per interpolated/scanned image. Something
still has to dispatch those sub-jobs in throttled waves (P4.3 -- see
submit_scan's own docstring for why submitting all of them up front is a
fair-scheduler starvation vector) and notice when they finish, rolling
their results back up into the master's own status/summary so the
frontend has one place to look. This mirrors app/agent/job_watcher.py's
shape (a daemon thread, started once at server startup, polling on a
fixed interval) but is a genuinely different, unrelated responsibility --
job_watcher.py's whole design is "per-conversation active_job_ids -> chat
notices," and a scan's sub-jobs are deliberately never added to any
thread's active_job_ids (only the master is), so folding this into that
watcher would conflate two unrelated polling loops.

Structurally mirrors app/chemistry/jobs/ensemble_orchestrator.py closely
(same daemon-thread/fixed-poll-interval shape, same wave-dispatch-then-
aggregate role, same dispatch_lock double-dispatch guard), with one real
difference in how a wave's sources are found: EnsembleOrchestrator
regenerates its samples deterministically from (random_seed, n_samples);
a pes_scan/interp_pes master has no equivalent cheap regeneration
function, so this module instead re-reads and re-parses the master's own
artifacts['path_xyz'] (already written in full by submit_scan) with the
same app.chemistry.geometry_upload.parse_multi_frame_xyz P3.2 built for
validating uploaded multi-frame geometry files.
"""
from __future__ import annotations

import threading
from pathlib import Path
from typing import Optional

from app.chemistry.geometry_upload import parse_multi_frame_xyz
from app.chemistry.jobs.base import (
    SCAN_ONLY_PARAM_KEYS, JobResult, JobSpec, read_result, read_spec, read_status, sub_job_ids_of, write_result,
    write_status,
)
from app.chemistry.spectrum import render_pes_plot
from app.config import JOBS_DIR, MASTER_MAX_IN_FLIGHT

_POLL_INTERVAL_SECONDS = 3.0
_TERMINAL_STATUSES = {"completed", "failed", "cancelled"}
_HARTREE_PER_EV = 1.0 / 27.211386245988

# Guards `_dispatch_more`'s whole decide-then-dispatch section -- same
# double-dispatch-prevention role as ensemble_orchestrator.py's own
# dispatch_lock (see that module's docstring for the concrete bug this
# closes): submit_scan's own initial-wave call and this orchestrator's own
# poll tick could otherwise both read "zero sub-jobs dispatched so far"
# and each send a full wave.
dispatch_lock = threading.Lock()


def _state_energies_hartree(summary: dict) -> Optional[list[float]]:
    """Absolute per-state energies (Hartree), ground state first,
    regardless of which job_type/engine produced the sub-job: casscf/
    caspt2 already report this shape directly as state_energies_hartree
    (all three engines -- see pyscf/orca/bagel_runner.py); single_point/
    tddft/eom_ccsd report a ground-state energy_hartree plus (for the
    excited-state job types) excitation_energies_eV relative to it."""
    if summary.get("state_energies_hartree"):
        return list(summary["state_energies_hartree"])
    ground = summary.get("energy_hartree")
    if ground is None:
        return None
    excitations_eV = summary.get("excitation_energies_eV") or []
    return [ground] + [ground + e * _HARTREE_PER_EV for e in excitations_eV]


def _build_state_series(state_energies_per_image: list) -> dict[str, list[Optional[float]]]:
    n_states = max((len(s) for s in state_energies_per_image if s), default=0)
    series: dict[str, list[Optional[float]]] = {}
    for state_i in range(n_states):
        label = "Ground state" if state_i == 0 else f"State {state_i}"
        series[label] = [s[state_i] if s and state_i < len(s) else None for s in state_energies_per_image]
    return series


def _iter_running_scan_masters():
    # Duplicated (not imported) from base.py's private _iter_job_ids_on_disk,
    # same convention server/routes/jobs.py's _iter_all_job_ids already
    # follows for the same reason (see that function's own comment).
    for d in JOBS_DIR.iterdir():
        if not d.is_dir() or d.name == "_seen" or not (d / "spec.json").exists():
            continue
        spec = read_spec(d.name)
        if (spec and spec.get("task") in ("pes_1d", "interp_pes")
                and (read_status(d.name) or {}).get("status") == "running"):
            yield d.name


class ScanOrchestrator:
    def __init__(self):
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None

    def start(self) -> None:
        if self._thread is not None:
            return
        self._thread = threading.Thread(target=self._loop, daemon=True, name="scan-orchestrator")
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
        for master_id in _iter_running_scan_masters():
            self._update_one(master_id)

    def _dispatch_more(self, master_id: str, master_spec: dict, n_points: int) -> None:
        """Tops up the in-flight wave of per-image sub-jobs, if there's
        room and more images left to dispatch. Re-reads the master's own
        artifacts['path_xyz'] (written in full by submit_scan, one frame
        per image, in scan order) rather than persisting the images list a
        second time anywhere -- see this module's own docstring for why
        that's the right source here (no cheap deterministic regeneration
        exists for a scan the way it does for a Wigner ensemble).

        Dispatches the actual MISSING `_scan_index` values, not a count --
        same reasoning submit_ensemble's own docstring gives: quota
        eviction can reap the scan's own earliest sub-jobs before the rest
        finish, leaving a hole a count-based range would never revisit
        (and, without noticing the hole, would dispatch a duplicate at the
        far end instead)."""
        with dispatch_lock:
            from app.chemistry.jobs.base import get_job_manager
            sub_ids = sub_job_ids_of(master_id)
            existing_indices: set[int] = set()
            for sid in sub_ids:
                sub_spec = read_spec(sid)
                idx = (sub_spec or {}).get("params", {}).get("_scan_index")
                if idx is not None:
                    existing_indices.add(idx)
            if len(existing_indices) >= n_points:
                return
            non_terminal = sum(1 for sid in sub_ids if read_status(sid)["status"] not in _TERMINAL_STATUSES)
            available = MASTER_MAX_IN_FLIGHT - non_terminal
            if available <= 0:
                return
            missing = sorted(set(range(n_points)) - existing_indices)
            to_dispatch = missing[:available]
            if not to_dispatch:
                return

            master_result = read_result(master_id)
            path_xyz = (master_result or {}).get("artifacts", {}).get("path_xyz")
            if not path_xyz:
                return  # master's own result not written yet -- try again next tick
            frames = parse_multi_frame_xyz(Path(path_xyz).read_text())

            # path_xyz (plain xmol XYZ) carries only symbols/coords/name --
            # no charge/multiplicity/identifier/smiles/source, none of
            # which XYZ has any field for. Every image dict
            # interpolate.build_path/build_coordinate_scan_images produced
            # for submit_scan's own initial-wave dispatch was instead a
            # shallow copy of the SCAN'S START molecule (constant across
            # every image -- only geometry varies along a scan) with just
            # symbols/coords/name overwritten (see interpolate.py's own
            # _image() helper) -- master_spec["molecule"] is that same
            # start molecule dict (params["_scan_start_molecule"], see
            # app/agent/tools.py's _build_scan_images), so re-applying that
            # template here reconstructs an identical molecule dict to
            # what the initial wave used, not just a same-looking one.
            molecule_template = master_spec["molecule"]

            # Also drops underscore-prefixed bookkeeping keys (including
            # _image0_raw_input, handled explicitly below rather than
            # leaking into every image's own params -- see submit_scan's
            # docstring).
            sub_params = {
                k: v for k, v in master_spec["params"].items() if k not in SCAN_ONLY_PARAM_KEYS and not k.startswith("_")
            }
            image0_raw_input = master_spec["params"].get("_image0_raw_input")
            mgr = get_job_manager()
            for i in to_dispatch:
                image_params = {**sub_params, "_scan_index": i}
                if i == 0 and image0_raw_input is not None:
                    # A hand-edited approval-card input only ever applies
                    # to this one image's own literal file -- every other
                    # image needs its own geometry baked into its input,
                    # which a single fixed edited text can't provide (see
                    # submit_job's docstring in app/agent/tools.py).
                    image_params["_raw_input"] = image0_raw_input
                image_molecule = {
                    **molecule_template,
                    "symbols": list(frames[i].symbols), "coords": frames[i].coords, "name": frames[i].name,
                }
                sub_spec = JobSpec(
                    task="single_point", subtype="gs", method=master_spec.get("method") or "",
                    engine=master_spec["engine"], molecule=image_molecule,
                    params=image_params, parent_job_id=master_id,
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
        n = summary["n_points"]

        sub_ids = sub_job_ids_of(master_id)
        if len(sub_ids) < n:
            self._dispatch_more(master_id, master_spec, n)
            sub_ids = sub_job_ids_of(master_id)  # re-read: may have grown just now

        energies = list(summary.get("energies_hartree") or [None] * n)
        state_energies_per_image = list(summary.get("state_energies_per_image") or [None] * n)
        failed_images = set(summary.get("failed_images") or [])

        # Keyed on each sub-job's own `_scan_index`, not its position in
        # `sub_ids` -- with dispatch now trickled (P4.3), sub_ids can be a
        # non-contiguous subset of 0..n-1 at any given snapshot (quota
        # eviction can also reap and later re-dispatch a hole out of
        # order), so `enumerate(sub_ids)` would misalign an image's result
        # with the wrong position along the scan coordinate.
        n_terminal = 0
        for sub_id in sub_ids:
            sub_spec = read_spec(sub_id)
            idx = (sub_spec or {}).get("params", {}).get("_scan_index")
            if idx is None:
                continue
            sub_status = (read_status(sub_id) or {}).get("status")
            if sub_status not in _TERMINAL_STATUSES:
                continue
            n_terminal += 1
            sub_result = read_result(sub_id) if sub_status == "completed" else None
            states = _state_energies_hartree((sub_result or {}).get("summary") or {}) if sub_result else None
            if states:
                energies[idx] = states[0]
                state_energies_per_image[idx] = states
            else:
                failed_images.add(idx)

        summary["energies_hartree"] = energies
        summary["state_energies_per_image"] = state_energies_per_image
        summary["failed_images"] = sorted(failed_images)
        summary["images_complete"] = n_terminal
        summary["images_dispatched"] = len(sub_ids)

        if len(sub_ids) < n or n_terminal < len(sub_ids):
            write_result(JobResult(master_id, "running", summary=summary, artifacts=result.get("artifacts", {})))
            write_status(master_id, "running", f"{len(sub_ids)} of {n} images dispatched, {n_terminal} complete")
            return

        known = [e for e in energies if e is not None]
        if known:
            zero = min(known)
            summary["relative_energies_kcal_mol"] = [
                (e - zero) * 627.5094740631 if e is not None else None for e in energies
            ]

        artifacts = dict(result.get("artifacts", {}))
        state_series = _build_state_series(state_energies_per_image)
        if state_series:
            try:
                plot_path = str(JOBS_DIR / master_id / "pes_plot.png")
                render_pes_plot(summary["coordinate_values"], state_series, summary.get("coordinate", "coordinate"), plot_path)
                artifacts["pes_plot"] = plot_path
            except Exception as e:
                summary["plot_error"] = str(e)

        n_ok = len(sub_ids) - len(failed_images)
        write_result(JobResult(master_id, "completed", summary=summary, artifacts=artifacts))
        write_status(master_id, "completed", f"scan complete ({n_ok} of {len(sub_ids)} images succeeded)")


_orchestrator: Optional[ScanOrchestrator] = None


def get_scan_orchestrator() -> ScanOrchestrator:
    global _orchestrator
    if _orchestrator is None:
        _orchestrator = ScanOrchestrator()
    return _orchestrator
