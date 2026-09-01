"""Turning a finished batch's children into one answer.

A batch used to report completion counts and nothing else -- "7 of 7 jobs
succeeded" -- which is true and useless. The scientific question behind
running a calculation at every point of a path is almost always how some
quantity VARIES along it, and answering that meant opening seven job
drawers and copying numbers out by hand.

So each child's headline numbers are collected here, indexed by the
child's own `_batch_index` (never by position in the child list -- quota
eviction can reap an early child and dispatch is trickled, so the two are
not the same), and joined to the source job's own scan coordinate where it
has one. A pes_1d or interp_pes source carries `coordinate_values`, which
is what makes "|NAC| against the torsion angle" possible rather than
"|NAC| against image number"; a geometry_set or Wigner ensemble has no
such coordinate and falls back to a 1-based image index, which is honest
rather than invented.

What gets collected depends on the child task, and only the tasks with an
obvious single headline number are collected at all. A batch of
optimizations is deliberately left with its counts: "the optimized
energy" is a reasonable series, but an optimization that converged to a
different minimum at each geometry is not one curve, and drawing it as
one would assert a continuity the calculation does not have.
"""
from __future__ import annotations

import os
from typing import Any, Optional

from app.chemistry.jobs.base import read_result, read_spec
from app.chemistry.spectrum import render_line_plot

# What each child task contributes to the master's aggregate, as
# (summary key holding the per-entry list, key naming each entry, label).
# Only these three are aggregated -- see the module docstring on why the
# optimization families are not.
_SERIES_LABEL = {
    "nac": "|NAC| (Eh/Bohr)",
    "gradient": "|gradient| (Eh/Bohr)",
    "excited_states": "Excitation energy (eV)",
}


def _coordinate_axis(master_spec: dict, n: int) -> tuple[list[float], str]:
    """(x values, axis label) for the batch's own children.

    The source job's scan coordinate when it has one, so a batch over a
    torsion scan is plotted against the torsion angle the user actually
    chose. Otherwise a plain 1-based image index.
    """
    source_job_id = (master_spec.get("params") or {}).get("source_job_id")
    if source_job_id:
        source = read_result(str(source_job_id)) or {}
        summary = source.get("summary") or {}
        values = summary.get("coordinate_values")
        if isinstance(values, list) and len(values) == n:
            return [float(v) for v in values], str(summary.get("coordinate") or "coordinate")
    return [float(i + 1) for i in range(n)], "Image"


def _child_index(sub_id: str) -> Optional[int]:
    spec = read_spec(sub_id)
    return ((spec or {}).get("params") or {}).get("_batch_index")


def _series_for_nac(summary: dict) -> dict[str, float]:
    """{"S0/S1": |NAC|, ...} for one coupling job."""
    out = {}
    for coupling in summary.get("couplings") or []:
        pair = coupling.get("state_pair") or []
        if len(pair) == 2:
            out[f"S{pair[0] - 1}/S{pair[1] - 1}"] = coupling.get("nac_norm_hartree_per_bohr")
    return out


def _series_for_gradient(summary: dict) -> dict[str, float]:
    out = {}
    for gradient in summary.get("gradients") or []:
        state = gradient.get("target_state")
        if state is not None:
            out[f"S{state - 1}"] = gradient.get("gradient_norm_hartree_per_bohr")
    return out


def _series_for_excited(summary: dict) -> dict[str, float]:
    energies = summary.get("excitation_energies_eV") or []
    return {f"S{i + 1}": e for i, e in enumerate(energies) if e is not None}


_SERIES_BUILDER = {
    "nac": _series_for_nac,
    "gradient": _series_for_gradient,
    "excited_states": _series_for_excited,
}


def aggregate(master_id: str, master_spec: dict, sub_ids: list[str], n: int,
              job_dir: str) -> tuple[dict[str, Any], dict[str, str]]:
    """(summary additions, artifact additions) for a completed batch.

    Never raises: a batch whose children all succeeded must not be reported
    as failed because a plot could not be drawn, so a failure here is
    recorded as `aggregate_error` beside whatever was collected. That is
    the same bargain scan_orchestrator makes for its own `plot_error`.
    """
    child_task = (master_spec.get("params") or {}).get("child_task")
    builder = _SERIES_BUILDER.get(child_task or "")
    if builder is None:
        return {}, {}

    try:
        x, xlabel = _coordinate_axis(master_spec, n)
        # {series label: [value per image]}, holes left as None so a failed
        # or evicted child is a gap in the curve rather than a silent shift
        # of every later point onto the wrong coordinate.
        series: dict[str, list[Optional[float]]] = {}
        for sub_id in sub_ids:
            index = _child_index(sub_id)
            if index is None or not (0 <= index < n):
                continue
            result = read_result(sub_id) or {}
            if result.get("status") != "completed":
                continue
            for label, value in builder(result.get("summary") or {}).items():
                series.setdefault(label, [None] * n)[index] = value

        if not series:
            return {}, {}

        # Sorted so the legend reads S0/S1, S0/S2, S1/S2 rather than in
        # whichever order children happened to finish.
        series = {label: series[label] for label in sorted(series)}
        summary: dict[str, Any] = {
            "aggregate_kind": child_task,
            "coordinate_values": x,
            "coordinate": xlabel,
            "series": series,
        }

        artifacts: dict[str, str] = {}
        ylabel = _SERIES_LABEL[child_task]
        plot_path = os.path.join(job_dir, "batch_plot.png")
        render_line_plot(x, series, xlabel, ylabel,
                         f"{ylabel.split(' (')[0]} along the path", plot_path)
        artifacts["batch_plot"] = plot_path
        return summary, artifacts
    except Exception as e:  # noqa: BLE001 -- see the docstring's bargain
        return {"aggregate_error": f"{type(e).__name__}: {e}"}, {}
