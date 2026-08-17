"""One shared rule for what counts as an imaginary vibrational frequency.

F-026. This rule used to be reimplemented at every site that needed it,
and the implementations disagreed: bagel_runner.py thresholded at
50 cm^-1, orca_runner.py and pyscf_runner.py used a bare `f < 0`, and the
frontend's VibrationTable.tsx re-derived it from the sign a fourth time to
decide which rows to paint red. The visible consequences were real -- the
same molecule at the same geometry could be reported as a minimum by one
engine and a saddle point by another, and a -5.9 cm^-1 noise mode was
rendered in "imaginary" red directly above a summary reading
`n_imaginary_frequencies: 0`.

For a number whose entire job is telling a chemist whether they have a
minimum or a transition state, that is not a cosmetic inconsistency.

Every engine's `run_frequency` now calls `summarize_frequencies` here, so
the count, the threshold and the per-mode flags all come from one place.
The per-mode `imaginary_flags` list is the part the frontend needs: it
consumes the backend's decision instead of re-deriving one, which is what
let the table and the summary disagree in the first place.
"""
from __future__ import annotations

from app.config import IMAGINARY_FREQ_THRESHOLD_CM1


def is_imaginary(freq_cm1: float, threshold: float | None = None) -> bool:
    """A mode is imaginary when it is more negative than the threshold.

    Engines report imaginary modes as negative wavenumbers. The threshold
    exists because a converged minimum's five or six translational and
    rotational modes come out at small values of either sign, and every
    runner here deliberately keeps them in the frequency list rather than
    projecting them out (so the two text-parsed engines stay index-aligned
    with each other). Without a threshold those modes make a genuine
    minimum look like a high-order saddle point at random.
    """
    limit = IMAGINARY_FREQ_THRESHOLD_CM1 if threshold is None else threshold
    return freq_cm1 < -limit


def summarize_frequencies(freqs_cm1: list[float], threshold: float | None = None) -> dict:
    """The frequency-related part of a `frequency` job's summary, built
    identically for PySCF, ORCA and BAGEL.

    `imaginary_flags` is parallel to `frequencies_cm-1`, so a UI can style
    a row from the same decision that produced the count without having to
    know the rule.
    """
    limit = IMAGINARY_FREQ_THRESHOLD_CM1 if threshold is None else threshold
    flags = [is_imaginary(f, limit) for f in freqs_cm1]
    return {
        "frequencies_cm-1": list(freqs_cm1),
        "n_imaginary_frequencies": sum(flags),
        "imaginary_flags": flags,
        "imaginary_threshold_cm-1": limit,
        "imaginary_frequency_note": (
            f"A mode counts as imaginary below -{limit:g} cm^-1. Modes between "
            f"-{limit:g} and +{limit:g} cm^-1 are the near-zero translational/"
            f"rotational modes, which are kept in this list rather than projected "
            f"out, and are not evidence of a transition state."
        ),
    }
