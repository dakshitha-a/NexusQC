"""Background thread that wave-dispatches a wigner_ensemble "master" job's
per-sample sub-jobs and, once they're all terminal, pools their results
into the master's own result.json.

Structurally mirrors app/chemistry/jobs/scan_orchestrator.py closely (same
daemon-thread/fixed-poll-interval shape, same "master has no worker of its
own" role), but with one real difference in responsibility: ScanOrchestrator
only ever aggregates -- JobManager.submit_scan already dispatches every
sub-job up front. A wigner_ensemble master (up to 250 samples -- see
registry.py's PARAM_HELP) only gets its INITIAL wave dispatched by
JobManager.submit_ensemble; this orchestrator is what dispatches the rest,
topping up the in-flight count each tick as earlier samples go terminal,
before eventually aggregating the same way ScanOrchestrator does. See
JobManager.submit_ensemble's own docstring for why wave dispatch exists at
all (submitting 250 sub-job directories inside one blocking call would
stress the quota/concurrency-scanning code at a scale it wasn't built for).
"""
from __future__ import annotations

import threading
from typing import Optional

from app.chemistry.jobs.base import (
    JobResult, JobSpec, read_result, read_spec, read_status, sub_job_ids_of, write_result, write_status,
)
from app.chemistry.jobs.ensemble_spectrum import pool_ensemble_transitions
from app.chemistry.jobs.wigner import sample_from_source_job
from app.chemistry.spectrum import render_wigner_ensemble_spectrum
from app.config import ENSEMBLE_MAX_IN_FLIGHT, JOBS_DIR

_POLL_INTERVAL_SECONDS = 3.0
_TERMINAL_STATUSES = {"completed", "failed", "cancelled"}
_ENSEMBLE_ONLY_PARAM_KEYS = {
    "source_frequency_job_id", "scan_job_type", "n_samples", "random_seed",
    "temperature_K", "low_freq_cutoff_cm1", "fwhm_eV",
}


def _iter_running_ensemble_masters():
    # Duplicated (not imported) from base.py's private _iter_job_ids_on_disk,
    # same convention scan_orchestrator.py's own _iter_running_scan_masters
    # already follows.
    for d in JOBS_DIR.iterdir():
        if not d.is_dir() or d.name == "_seen" or not (d / "spec.json").exists():
            continue
        spec = read_spec(d.name)
        if spec and spec.get("method") == "wigner_ensemble" and read_status(d.name)["status"] == "running":
            yield d.name


class EnsembleOrchestrator:
    def __init__(self):
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None

    def start(self) -> None:
        if self._thread is not None:
            return
        self._thread = threading.Thread(target=self._loop, daemon=True, name="ensemble-orchestrator")
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
        for master_id in _iter_running_ensemble_masters():
            self._update_one(master_id)

    def _dispatch_more(self, master_id: str, master_spec: dict, sub_ids: list, summary: dict) -> None:
        """Tops up the in-flight wave, if there's room and more samples
        left to dispatch. Regenerates the FULL deterministic sample set
        from (random_seed, n_samples) -- cheap, pure numpy, no I/O beyond
        the one read_result(source_frequency_job_id) call below -- and
        slices out just the newly-needed range, rather than re-reading
        ensemble_xyz back off disk (a second, redundant representation of
        the same data submit_ensemble already wrote once)."""
        n_samples = summary["n_samples"]
        n_dispatched = len(sub_ids)
        if n_dispatched >= n_samples:
            return
        non_terminal = sum(1 for sid in sub_ids if read_status(sid)["status"] not in _TERMINAL_STATUSES)
        available = ENSEMBLE_MAX_IN_FLIGHT - non_terminal
        if available <= 0:
            return
        wave = min(available, n_samples - n_dispatched)

        source_id = master_spec["params"]["source_frequency_job_id"]
        source_spec = read_spec(source_id)
        source_result = read_result(source_id)
        if source_spec is None or source_result is None:
            return  # source job vanished -- nothing to regenerate from; try again next tick
        samples, _diagnostics = sample_from_source_job(
            source_spec["molecule"], source_result["summary"],
            n_samples=n_samples, random_seed=master_spec["params"]["random_seed"],
            low_freq_cutoff_cm1=master_spec["params"].get("low_freq_cutoff_cm1", 100.0),
            temperature_K=master_spec["params"].get("temperature_K", 0.0),
        )

        sub_params = {
            k: v for k, v in master_spec["params"].items()
            if k not in _ENSEMBLE_ONLY_PARAM_KEYS and not k.startswith("_")
        }
        from app.chemistry.jobs.base import get_job_manager
        mgr = get_job_manager()
        for i in range(n_dispatched, n_dispatched + wave):
            sub_spec = JobSpec(
                method=master_spec["params"]["scan_job_type"], engine=master_spec["engine"], molecule=samples[i],
                params={**sub_params, "_ensemble_index": i}, parent_job_id=master_id,
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
        n_samples = summary["n_samples"]

        sub_ids = sub_job_ids_of(master_id)
        if len(sub_ids) < n_samples:
            self._dispatch_more(master_id, master_spec, sub_ids, summary)
            sub_ids = sub_job_ids_of(master_id)  # re-read: may have grown just now

        n_terminal = sum(1 for sid in sub_ids if read_status(sid)["status"] in _TERMINAL_STATUSES)
        summary["n_dispatched"] = len(sub_ids)
        summary["n_complete"] = n_terminal

        if len(sub_ids) < n_samples or n_terminal < len(sub_ids):
            write_result(JobResult(master_id, "running", summary=summary, artifacts=result.get("artifacts", {})))
            write_status(
                master_id, "running",
                f"{len(sub_ids)} of {n_samples} samples dispatched, {n_terminal} complete",
            )
            return

        # Every sample dispatched AND every dispatched sub-job terminal --
        # pool and render, unconditionally marking the master "completed"
        # regardless of how many individual samples failed or reported no
        # usable intensity (same posture ScanOrchestrator already has for
        # a partially-failed scan; failure/skip counts affect the status
        # message text and summary diagnostics, not the terminal state).
        pooled, pool_diagnostics = pool_ensemble_transitions(sub_ids)
        summary.update(pool_diagnostics)

        artifacts = dict(result.get("artifacts", {}))
        if pooled["energies_eV"]:
            try:
                fwhm_eV = master_spec["params"].get("fwhm_eV", 0.4)
                plot_path = str(JOBS_DIR / master_id / "ensemble_spectrum.png")
                data_path = str(JOBS_DIR / master_id / "ensemble_spectrum.dat")
                render_wigner_ensemble_spectrum(
                    pooled["energies_eV"], pooled["oscillator_strengths"], pooled["state_indices"],
                    fwhm_eV, plot_path, out_data_path=data_path,
                )
                artifacts["ensemble_spectrum"] = plot_path
                artifacts["ensemble_spectrum_data"] = data_path
            except Exception as e:
                summary["plot_error"] = str(e)
        else:
            summary["plot_error"] = "No sample contributed a usable (energy, oscillator strength) pair to pool."

        write_result(JobResult(master_id, "completed", summary=summary, artifacts=artifacts))
        write_status(
            master_id, "completed",
            f"ensemble complete ({pool_diagnostics['n_completed']} of {len(sub_ids)} samples usable)",
        )


_orchestrator: Optional[EnsembleOrchestrator] = None


def get_ensemble_orchestrator() -> EnsembleOrchestrator:
    global _orchestrator
    if _orchestrator is None:
        _orchestrator = EnsembleOrchestrator()
    return _orchestrator
