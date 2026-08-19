"""Background thread that wave-dispatches a wigner_ensemble "master" job's
per-sample sub-jobs and, once they're all terminal, pools their results
into the master's own result.json.

Structurally mirrors app/chemistry/jobs/scan_orchestrator.py closely (same
daemon-thread/fixed-poll-interval shape, same "master has no worker of its
own" role), but with one real difference in responsibility: ScanOrchestrator
only ever aggregates -- JobManager.submit_scan already dispatches every
sub-job up front. A wigner_ensemble master (up to 250 samples -- see
registry.py's PARAM_HELP) is dispatched wave by wave instead: an initial
wave, then top-ups each tick as earlier samples go terminal, then
aggregation once every sample is terminal, the same way ScanOrchestrator
aggregates. See JobManager.submit_ensemble's own docstring for why wave
dispatch exists at all (submitting 250 sub-job directories inside one
blocking call would stress the quota/concurrency-scanning code at a scale
it wasn't built for).

JobManager.submit_ensemble calls straight into this module's own
`_dispatch_more` for the initial wave (via `get_ensemble_orchestrator()`)
rather than running a second, separate dispatch loop of its own -- see
`dispatch_lock`'s comment below for why that used to be able to
double-dispatch a sample.
"""
from __future__ import annotations

import threading
from typing import Optional

from app.chemistry.jobs.base import (
    ENSEMBLE_ONLY_PARAM_KEYS, JobResult, JobSpec, read_result, read_spec, read_status, sub_job_ids_of,
    write_result, write_status,
)
from app.chemistry.jobs.ensemble_spectrum import pool_ensemble_transitions
from app.chemistry.jobs.wigner import sample_from_source_job
from app.chemistry.spectrum import render_wigner_ensemble_spectrum
from app.config import JOBS_DIR, MASTER_MAX_IN_FLIGHT

_POLL_INTERVAL_SECONDS = 3.0
_TERMINAL_STATUSES = {"completed", "failed", "cancelled"}

# Guards `_dispatch_more`'s whole decide-then-dispatch section. Needed
# because JobManager.submit_ensemble writes the master's status/result as
# "running" (so the card/job list shows something immediately) BEFORE any
# sub-job exists -- which means _iter_running_ensemble_masters can already
# see and poll a master whose initial wave hasn't been dispatched yet.
#
# This used to be two independent dispatch loops -- submit_ensemble's own
# `for i in range(wave_size): ...` and this module's `_dispatch_more` --
# each deciding "how many are dispatched, dispatch the rest" from its own
# read of sub_job_ids_of. A poll tick landing in the window between
# submit_ensemble marking the master "running" and its own loop actually
# starting would see zero sub-jobs, dispatch a full wave itself, and then
# submit_ensemble's loop would dispatch that same range again -- confirmed
# empirically: a real 5-sample run submitted through a live conversation
# came back with n_dispatched=6, one duplicate. A lock around each side's
# existing loop would only have narrowed that window, not closed it, since
# submit_ensemble's own loop never checked what already existed before
# dispatching `range(wave_size)`. The actual fix is that there is now only
# ONE piece of code that decides and dispatches -- `_dispatch_more` itself,
# always re-reading sub_job_ids_of fresh under this lock -- and
# submit_ensemble calls into it for its own initial wave instead of
# duplicating the logic.
dispatch_lock = threading.Lock()


def _iter_running_ensemble_masters():
    # Duplicated (not imported) from base.py's private _iter_job_ids_on_disk,
    # same convention scan_orchestrator.py's own _iter_running_scan_masters
    # already follows.
    for d in JOBS_DIR.iterdir():
        if not d.is_dir() or d.name == "_seen" or not (d / "spec.json").exists():
            continue
        spec = read_spec(d.name)
        if spec and spec.get("task") == "wigner_spectra" and read_status(d.name)["status"] == "running":
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

    def _dispatch_more(self, master_id: str, master_spec: dict, summary: dict) -> None:
        """Tops up the in-flight wave, if there's room and more samples
        left to dispatch. Regenerates the FULL deterministic sample set
        from (random_seed, n_samples) -- cheap, pure numpy, no I/O beyond
        the one read_result(source_frequency_job_id) call below -- and
        slices out just the newly-needed range, rather than re-reading
        ensemble_xyz back off disk (a second, redundant representation of
        the same data submit_ensemble already wrote once).

        Holds `dispatch_lock` (shared with JobManager.submit_ensemble's own
        initial-wave loop -- see this module's docstring comment above the
        lock) for the whole decide-then-dispatch section, and reads
        sub_job_ids_of fresh under the lock rather than accepting a
        snapshot from the caller -- a snapshot taken before the lock was
        granted can already be stale by the time it's used.

        Dispatches the actual MISSING `_ensemble_index` values, not a count
        -- `range(n_dispatched, n_dispatched + wave)` looks equivalent while
        indices occupy a contiguous 0..n_dispatched-1 block, but submit_
        ensemble's own docstring names the case that breaks it: quota
        eviction can reap the ensemble's own earliest sub-jobs before the
        rest finish, leaving a hole a count-based range would never revisit
        (and, without noticing the hole, would dispatch a duplicate at the
        far end instead)."""
        with dispatch_lock:
            from app.chemistry.jobs.base import get_job_manager
            sub_ids = sub_job_ids_of(master_id)
            n_samples = summary["n_samples"]
            existing_indices: set[int] = set()
            for sid in sub_ids:
                sub_spec = read_spec(sid)
                idx = (sub_spec or {}).get("params", {}).get("_ensemble_index")
                if idx is not None:
                    existing_indices.add(idx)
            if len(existing_indices) >= n_samples:
                return
            non_terminal = sum(1 for sid in sub_ids if read_status(sid)["status"] not in _TERMINAL_STATUSES)
            available = MASTER_MAX_IN_FLIGHT - non_terminal
            if available <= 0:
                return
            missing = sorted(set(range(n_samples)) - existing_indices)
            to_dispatch = missing[:available]
            if not to_dispatch:
                return

            source_id = master_spec["params"]["source_frequency_job_id"]
            source_spec = read_spec(source_id)
            source_result = read_result(source_id)
            if source_spec is None or source_result is None:
                return  # source job vanished -- nothing to regenerate from; try again next tick
            # Mirrors app/agent/tools.py's own equilibrium-geometry choice
            # (both _build_ensemble_spec_or_error's preview and submit_job's
            # post-approval re-derivation) exactly, and must keep doing so:
            # an opt_freq source's own spec.molecule is the PRE-optimization
            # input geometry, not the minimum the normal modes were computed
            # at -- summary['optimized_molecule'] is the equilibrium geometry
            # there. Sampling around the wrong one here would silently run
            # every sample at input-geometry-centered displacements while
            # ensemble_xyz (written from submit_ensemble's own, correctly-
            # sourced samples) shows something else entirely.
            equilibrium_molecule = (
                (source_result.get("summary") or {}).get("optimized_molecule")
                if source_spec.get("task") == "opt_freq" else source_spec["molecule"]
            )
            if not equilibrium_molecule:
                return  # opt_freq source has no optimized_molecule yet -- try again next tick
            samples, _diagnostics = sample_from_source_job(
                equilibrium_molecule, source_result["summary"],
                n_samples=n_samples, random_seed=master_spec["params"]["random_seed"],
                low_freq_cutoff_cm1=master_spec["params"].get("low_freq_cutoff_cm1", 100.0),
                temperature_K=master_spec["params"].get("temperature_K", 0.0),
            )

            sub_params = {
                k: v for k, v in master_spec["params"].items()
                if k not in ENSEMBLE_ONLY_PARAM_KEYS and not k.startswith("_")
            }
            mgr = get_job_manager()
            for i in to_dispatch:
                sub_spec = JobSpec(
                    task="single_point", subtype="ee", method=master_spec.get("method") or "",
                    engine=master_spec["engine"], molecule=samples[i],
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
            self._dispatch_more(master_id, master_spec, summary)
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
