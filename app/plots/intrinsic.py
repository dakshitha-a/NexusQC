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

Only kinds with a real server-side renderer and an unambiguous set of
parameters are registered. The interactive charts in the job drawer
(optimization energy, NEB path, and a pes_1d scan's own physical coordinate)
are drawn client-side from job data and are deliberately left where they are;
they have no stored parameters that an edit could patch, and inventing some
to make them look like plots would be worse than leaving them as the live
views they already are.

An interp_pes scan is the one exception: its server-rendered PES plot
(render_pes_plot, already produced automatically by ScanOrchestrator once
every image is terminal) is registered here like uvvis/ir/ensemble, so it
shows up in the Plots panel and posts to chat unprompted the same way a
finished Wigner spectrum does. pes_1d keeps the client-side-only treatment
described above -- only the interpolated-path plot was asked to behave like
the other intrinsic plots.
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
        plot_excited_state_spectrum, plot_ir_spectrum, plot_pes_scan, plot_wigner_ensemble_spectrum,
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
    if (spec.get("task") or "") == "interp_pes":
        attempts.append(("pes_scan", lambda: plot_pes_scan(job_id=job_id, state=state)))

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
