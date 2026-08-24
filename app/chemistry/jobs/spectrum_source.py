"""What is this job's spectrum?

Three job types produce one and they arrive by different routes. A
`wigner_spectra` master has already pooled every sample's transitions and
written a broadened, normalized curve to disk. A `single_point/ee` job has
excitation energies and oscillator strengths, which imply a curve but are
not one. A `freq` job has vibrational frequencies and IR intensities, the
same way.

Every caller wants the same answer -- the total spectrum, as x and y --
so the resolution lives here rather than at each call site.
`job_context_summary` uses it to hand a tagged job's curve to the model,
and `plot` uses it to put several jobs' curves on one axis. Two
implementations of "broaden this job's sticks" would drift, and the
symptom would be a number in a reply disagreeing with a peak on a figure.

**Everything returned here is normalized to a peak of 1.** The ensemble
file already is (by the total's own peak, so its per-state overlays stay
honest); the two stick paths are normalized here to match. Without that,
an overlay of a Wigner spectrum and a TDDFT one would show the first at
1.0 and the second at raw oscillator-strength scale, which looks like a
result rather than a units mistake.
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

import numpy as np

from app.chemistry.jobs.base import get_job_manager, read_spec
from app.chemistry.spectrum import _broadened_spectrum

# The conventions the single-job spectrum plots already use, so a curve
# taken from here and one drawn by plot(kind="uvvis"/"ir") are the same
# curve rather than two broadenings of the same sticks.
DEFAULT_UVVIS_FWHM_EV = 0.4
DEFAULT_IR_FWHM_CM1 = 20.0

# Which axis a kind lives on. Two spectra can only share a plot if they
# agree here: an IR spectrum in cm-1 and a UV/Vis spectrum in eV are not
# the same axis, and converting one to the other would put a vibrational
# band and an electronic transition on one scale where nothing means
# anything.
AXIS_BY_KIND = {"uvvis": "eV", "ensemble": "eV", "ir": "cm-1"}

SPECTRUM_KIND_LABEL = {
    "uvvis": "UV/Vis absorption",
    "ensemble": "nuclear-ensemble absorption",
    "ir": "IR absorption",
}


def spectrum_kind_for_job(job_id: str, spec: Optional[dict] = None) -> Optional[str]:
    """"uvvis" | "ensemble" | "ir", or None for a job with no spectrum.

    Keyed on the task, not on which fields happen to be present: an
    opt/ci job on BAGEL carries excitation energies too, and it is not a
    spectrum.
    """
    spec = spec if spec is not None else (read_spec(job_id) or {})
    task, subtype = spec.get("task") or "", spec.get("subtype") or ""
    if task == "wigner_spectra":
        return "ensemble"
    if task == "single_point" and subtype == "ee":
        return "uvvis"
    if task in ("freq", "opt_freq"):
        return "ir"
    return None


def _normalized(y: np.ndarray) -> np.ndarray:
    peak = float(np.max(y)) if y.size else 0.0
    return y / peak if peak > 0 else y


def _from_ensemble_file(job_id: str, result: dict):
    """The pooled curve a finished ensemble already wrote.

    Read rather than recomputed: the file is what the ensemble's own PNG
    was drawn from, and pooling every sub-job's transitions again here
    would be a second implementation of the same aggregation.
    """
    path = (result.get("artifacts") or {}).get("ensemble_spectrum_data")
    if not path:
        return None, None, f"Job {job_id} has no pooled ensemble spectrum yet."
    try:
        rows = [
            [float(v) for v in line.split()]
            for line in Path(path).read_text().splitlines()
            if line.strip() and not line.lstrip().startswith("#")
        ]
    except (OSError, ValueError) as e:
        return None, None, f"Could not read job {job_id}'s spectrum data: {e}"
    if not rows:
        return None, None, f"Job {job_id}'s spectrum data file is empty."
    # Column 0 is energy, column 1 the total; the rest are per-state
    # overlays, which are not this function's business.
    x = np.array([r[0] for r in rows], dtype=float)
    y = np.array([r[1] for r in rows], dtype=float)
    return x, _normalized(y), None


def total_spectrum_for_job(job_id: str, fwhm: Optional[float] = None):
    """(x, y, meta, error) for one job's total spectrum, y normalized to 1.

    `fwhm` is in the units of that spectrum's own axis (eV for UV/Vis,
    cm-1 for IR) and is ignored for an ensemble, whose curve was broadened
    when it was pooled. `meta` carries the kind, the axis units, the
    broadening actually used, and a human label for a legend entry.

    Refuses rather than fabricates: a job whose engine computed no
    oscillator strengths or no IR intensities has sticks with no heights,
    and a spectrum drawn from those would be a picture of nothing.
    """
    spec = read_spec(job_id) or {}
    kind = spectrum_kind_for_job(job_id, spec)
    if kind is None:
        task = spec.get("task") or "unknown"
        return None, None, None, (
            f"Job {job_id} (task={task}) produces no spectrum. Spectra come from an excited-state "
            f"job, a frequency job, or a nuclear-ensemble job."
        )
    result = get_job_manager().result(job_id)
    if result is None:
        return None, None, None, f"No such job: {job_id}."
    if result.get("status") != "completed":
        return None, None, None, (
            f"Job {job_id} is not completed yet (status: {result.get('status')}) -- it has no "
            f"finished spectrum."
        )
    summary = result.get("summary") or {}

    if kind == "ensemble":
        x, y, error = _from_ensemble_file(job_id, result)
        if error:
            return None, None, None, error
        used_fwhm = (spec.get("params") or {}).get("fwhm_eV")
    elif kind == "uvvis":
        positions = summary.get("excitation_energies_eV")
        heights = summary.get("oscillator_strengths")
        if not positions:
            return None, None, None, f"Job {job_id} has no excitation energies to build a spectrum from."
        if not heights or all(h is None for h in heights):
            return None, None, None, (
                f"Job {job_id} has excitation energies but no oscillator strengths, so there is "
                f"nothing to give the peaks their heights. Re-run on an engine that computes "
                f"intensities to get a spectrum."
            )
        used_fwhm = float(fwhm or DEFAULT_UVVIS_FWHM_EV)
        pairs = [(p, h) for p, h in zip(positions, heights) if h is not None]
        gx, gy = _broadened_spectrum([p for p, _ in pairs], [h for _, h in pairs], used_fwhm)
        x, y = gx, _normalized(gy)
    else:
        positions = summary.get("frequencies_cm-1")
        heights = summary.get("ir_intensities_km_mol")
        if not positions:
            return None, None, None, f"Job {job_id} has no vibrational frequencies to build a spectrum from."
        if not heights or all(h is None for h in heights):
            return None, None, None, (
                f"Job {job_id} has frequencies but no IR intensities, so there is nothing to give "
                f"the bands their heights. PySCF computes no IR intensities in this app; ORCA and "
                f"BAGEL do."
            )
        used_fwhm = float(fwhm or DEFAULT_IR_FWHM_CM1)
        # Imaginary modes are recorded as negative frequencies and are not
        # part of an IR spectrum -- a band at -1200 cm-1 is a saddle point,
        # not an absorption.
        pairs = [(p, h) for p, h in zip(positions, heights) if h is not None and p > 0]
        if not pairs:
            return None, None, None, f"Job {job_id} has no real vibrational modes with intensities."
        gx, gy = _broadened_spectrum([p for p, _ in pairs], [h for _, h in pairs], used_fwhm)
        x, y = gx, _normalized(gy)

    meta = {
        "kind": kind,
        "axis_units": AXIS_BY_KIND[kind],
        "fwhm": used_fwhm,
        "label": SPECTRUM_KIND_LABEL[kind],
        "method": spec.get("method"),
        "engine": spec.get("engine"),
        "n_points": int(len(x)),
    }
    return np.asarray(x, dtype=float), np.asarray(y, dtype=float), meta, None


def sample_curve(x, y, n: int):
    """`n` evenly spaced points across the curve's own range.

    Nearest-sample rather than interpolated, so every y returned is a
    value the curve really takes -- a quoted peak height stays a real one.
    The peak's own index is forced in: a coarse even sample can step over
    a narrow band entirely, and a spectrum summary that misses the tallest
    peak is worse than useless.
    """
    x = np.asarray(x, dtype=float)
    y = np.asarray(y, dtype=float)
    if x.size <= n:
        idx = np.arange(x.size)
    else:
        idx = np.unique(np.concatenate([
            np.linspace(0, x.size - 1, n).round().astype(int),
            [int(np.argmax(y))],
        ]))
    return x[idx], y[idx]
