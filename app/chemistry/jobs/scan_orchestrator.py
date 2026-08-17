"""Background thread that aggregates a pes_scan "master" job's per-image
sub-jobs back into the master's own result.json.

A pes_scan master (see app/chemistry/jobs/base.py's JobManager.submit_scan)
is never itself a dispatched subprocess -- it does no compute of its own,
only spawns N ordinary sub-JobSpecs (one per interpolated/scanned image)
through the normal submit() path. Something still has to notice when those
sub-jobs finish and roll their results back up into the master's own
status/summary so the frontend has one place to look. This mirrors
app/agent/job_watcher.py's shape (a daemon thread, started once at server
startup, polling on a fixed interval) but is a genuinely different,
unrelated responsibility -- job_watcher.py's whole design is "per-
conversation active_job_ids -> chat notices," and a scan's sub-jobs are
deliberately never added to any thread's active_job_ids (only the master
is), so folding this into that watcher would conflate two unrelated
polling loops.
"""
from __future__ import annotations

import threading
from typing import Optional

from app.chemistry.jobs.base import (
    JobResult, read_result, read_spec, read_status, sub_job_ids_of, write_result, write_status,
)
from app.chemistry.spectrum import render_pes_plot
from app.config import JOBS_DIR

_POLL_INTERVAL_SECONDS = 3.0
_TERMINAL_STATUSES = {"completed", "failed", "cancelled"}
_HARTREE_PER_EV = 1.0 / 27.211386245988


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
        if spec and spec.get("method") == "pes_scan" and (read_status(d.name) or {}).get("status") == "running":
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

    def _update_one(self, master_id: str) -> None:
        result = read_result(master_id)
        if result is None or result.get("status") != "running":
            return
        sub_ids = sub_job_ids_of(master_id)
        if not sub_ids:
            return

        summary = dict(result["summary"])
        n = summary["n_points"]
        energies = list(summary.get("energies_hartree") or [None] * n)
        state_energies_per_image = list(summary.get("state_energies_per_image") or [None] * n)
        failed_images = set(summary.get("failed_images") or [])

        n_terminal = 0
        for i, sub_id in enumerate(sub_ids):
            sub_status = (read_status(sub_id) or {}).get("status")
            if sub_status not in _TERMINAL_STATUSES:
                continue
            n_terminal += 1
            sub_result = read_result(sub_id) if sub_status == "completed" else None
            states = _state_energies_hartree((sub_result or {}).get("summary") or {}) if sub_result else None
            if states:
                energies[i] = states[0]
                state_energies_per_image[i] = states
            else:
                failed_images.add(i)

        summary["energies_hartree"] = energies
        summary["state_energies_per_image"] = state_energies_per_image
        summary["failed_images"] = sorted(failed_images)
        summary["images_complete"] = n_terminal

        if n_terminal < len(sub_ids):
            write_result(JobResult(master_id, "running", summary=summary, artifacts=result.get("artifacts", {})))
            write_status(master_id, "running", f"{n_terminal} of {len(sub_ids)} images complete")
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
