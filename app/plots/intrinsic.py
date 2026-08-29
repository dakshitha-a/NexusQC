"""Plots a job produces on its own, registered as saved records.

The Plots panel is meant to hold every chart the app has drawn, not only the
ones a user composed by asking. A UV/Vis spectrum, an IR spectrum and a
nuclear-ensemble spectrum are properties of the job that produced them, and
they should be findable, downloadable, attachable and deletable in the same
place as everything else.

Registered when a job reaches a terminal state, from job_watcher's poll loop.
That is the one place that already knows a job has just finished and has not
been seen before, so it needs no completion hook of its own.

Deleting one of these is meaningful rather than destructive: it removes the
saved view, and the job's own data is untouched, so asking for the spectrum
again brings it back.

Only kinds with a real server-side renderer are registered. The genuinely
client-side chart -- the optimization-energy sparkline in the job drawer -- is
deliberately left where it is: it is computed in the browser from job data,
has no rendered file behind it, and turning it into a saved record would mean
inventing parameters it does not have.

Two paragraphs used to stand here arguing that the NEB path and a pes_1d scan
belonged in that same client-side category, and that these kinds "have no
stored parameters that an edit could patch". Both halves have since stopped
being true, so the exclusions went with them. `render_neb_plot`,
`render_entropy_plateau_plot` and `render_pes_plot` all write real PNGs to
disk as job artifacts -- `NebEnergyPlot` and `ScanPlot` display those files
rather than drawing their own -- and every plot kind became patchable when the
style vocabulary landed (`app/chemistry/plot_style.py`), so a title or an axis
label on any of them is now an ordinary edit. Leaving three server-rendered
charts unversioned and unattachable was the last gap in "every plot is a saved
object you can restyle".
"""
from __future__ import annotations

from app.plots import store as plot_store


def _owner_of_job(job_id: str) -> str | None:
    """The job's owner, so its plots land in the same place the user's own
    plots do. None on a no-auth deployment, where the store's flat layout is
    the only layout there is."""
    try:
        from app.auth.models import get_owner
        return get_owner("job", job_id)
    except Exception:
        return None


def register_for_job(job_id: str) -> list[str]:
    """Register whatever intrinsic plots this finished job supports, and
    return the kinds registered.

    Idempotent by construction: each plot function routes through
    `_save_plot`, which reuses an existing record for the same job and kind
    rather than creating a second, so a re-run of this costs a version at
    worst and usually nothing at all. Failures are swallowed per kind. This
    runs inside the watcher's poll loop, and a job that finished successfully
    must never look failed because a convenience plot could not be drawn.
    """
    from app.agent.tools import (
        plot_entropy_plateau, plot_excited_state_spectrum, plot_ir_spectrum, plot_neb_path,
        plot_pes_scan, plot_wigner_ensemble_spectrum,
    )
    from app.chemistry.jobs.base import get_job_manager, read_spec

    result = get_job_manager().result(job_id)
    if result is None or result.get("status") != "completed":
        return []
    summary = result.get("summary") or {}
    state = {"owner_user_id": _owner_of_job(job_id), "active_job_ids": []}
    spec = read_spec(job_id) or {}
    registered = []

    attempts: list[tuple[str, object]] = []
    if summary.get("excitation_energies_eV") and summary.get("oscillator_strengths"):
        attempts.append(("uvvis", lambda: plot_excited_state_spectrum(job_id=job_id, state=state)))
    if summary.get("frequencies_cm1") and summary.get("ir_intensities"):
        attempts.append(("ir", lambda: plot_ir_spectrum(job_id=job_id, state=state)))
    if (spec.get("task") or "") == "wigner_spectra":
        attempts.append(("ensemble", lambda: plot_wigner_ensemble_spectrum(job_id=job_id, state=state)))
    if (spec.get("task") or "") in ("interp_pes", "pes_1d"):
        attempts.append(("pes_scan", lambda: plot_pes_scan(job_id=job_id, state=state)))
    if summary.get("path_summary"):
        attempts.append(("neb", lambda: plot_neb_path(job_id=job_id, state=state)))
    if summary.get("pilot_orbital_entropies"):
        attempts.append(("entropy", lambda: plot_entropy_plateau(job_id=job_id, state=state)))

    owner = state["owner_user_id"]
    for kind, draw in attempts:
        # Already registered. Drawing again would only add an identical
        # version, since nothing about a finished job's data changes.
        if plot_store.find_by_job_and_kind(owner, job_id, kind) is not None:
            continue
        try:
            out = draw()
        except Exception:
            continue
        # Every one of these refuses in prose rather than raising when the
        # data will not support a plot (no usable oscillator strengths, for
        # one), so a returned refusal is an ordinary outcome to skip past,
        # not an error to report.
        # Python reads `a and b or c` as `(a and b) or c`, so the previous
        # form here fell back to a substring test on `str(out)` for any
        # non-string return, and only worked at all because uvvis/ir happened
        # to say "plot id is" while every other kind happened to emit a
        # marker. Rewording either return string would have silently stopped
        # intrinsic registration, with no error anywhere. Now that every kind
        # emits the marker, that is the one thing to test for.
        if isinstance(out, str) and "PLOT_ARTIFACT" in out:
            registered.append(kind)
    return registered
