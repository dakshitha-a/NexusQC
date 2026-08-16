"""Pools a wigner_ensemble master's per-sample sub-job excited-state
results into one flat set of (energy, oscillator_strength, state_index)
triples, ready for Gaussian broadening (see app/chemistry/spectrum.py's
render_wigner_ensemble_spectrum).

Shared by app/chemistry/jobs/ensemble_orchestrator.py (on-completion,
default-fwhm auto-render) and app/agent/tools.py's
plot_wigner_ensemble_spectrum tool (on-demand re-plot, always re-pools
live from disk rather than trusting a cached pool, so a different fwhm_eV
reflects the ensemble's true current state) -- one pooling implementation,
not two independently-maintained ones.
"""
from __future__ import annotations

from app.chemistry.jobs.base import read_result, read_status


def pool_ensemble_transitions(sub_job_ids: list) -> tuple[dict, dict]:
    """Returns (pooled, diagnostics).

    pooled = {"energies_eV": [...], "oscillator_strengths": [...],
    "state_indices": [...], "sub_job_ids": [...]} -- four parallel lists,
    one entry per (sub_job, excited_state) pair that had both a real
    energy and a real (non-None) oscillator strength. state_indices are
    1-based (1 = S1), matching excitation_energies_eV's own convention.
    sub_job_ids (unused by render_wigner_ensemble_spectrum, which only
    needs the first three) is for list_ensemble_geometries_in_window,
    which needs to report which sample each transition came from.

    diagnostics = {"n_sub_jobs": ..., "n_completed": ..., "n_no_intensity": ...,
    "n_failed_or_pending": ..., "n_transitions_pooled": ...} -- every
    sub-job is accounted for in exactly one category, so a caller can
    always explain to the user what happened to every sample, never just
    silently drop some. "n_no_intensity" covers a completed sub-job whose
    method/engine combination genuinely reports no oscillator strengths at
    all (e.g. BAGEL casscf, PySCF eom_ccsd) -- not a failure, just no
    usable intensity data; refuse-don't-fabricate, same convention
    plot_excited_state_spectrum already established for a single job.
    """
    energies: list = []
    oscillator_strengths: list = []
    state_indices: list = []
    pooled_sub_job_ids: list = []
    n_completed = 0
    n_no_intensity = 0
    n_failed_or_pending = 0

    for sub_id in sub_job_ids:
        status = read_status(sub_id)["status"]
        if status != "completed":
            n_failed_or_pending += 1
            continue
        result = read_result(sub_id)
        summary = (result or {}).get("summary") or {}
        sub_energies = summary.get("excitation_energies_eV")
        sub_osc = summary.get("oscillator_strengths")
        if not sub_energies or not sub_osc:
            n_no_intensity += 1
            continue
        n_completed += 1
        contributed = False
        for idx, (e, o) in enumerate(zip(sub_energies, sub_osc)):
            if e is None or o is None:
                continue
            energies.append(e)
            oscillator_strengths.append(o)
            state_indices.append(idx + 1)
            pooled_sub_job_ids.append(sub_id)
            contributed = True
        if not contributed:
            # Every entry was None (e.g. ORCA printed fewer transitions
            # than requested) -- counted separately from a job that never
            # had an oscillator_strengths key at all, but functionally the
            # same "no usable intensity" outcome for this sub-job.
            n_no_intensity += 1
            n_completed -= 1

    diagnostics = {
        "n_sub_jobs": len(sub_job_ids), "n_completed": n_completed, "n_no_intensity": n_no_intensity,
        "n_failed_or_pending": n_failed_or_pending, "n_transitions_pooled": len(energies),
    }
    pooled = {
        "energies_eV": energies, "oscillator_strengths": oscillator_strengths, "state_indices": state_indices,
        "sub_job_ids": pooled_sub_job_ids,
    }
    return pooled, diagnostics
