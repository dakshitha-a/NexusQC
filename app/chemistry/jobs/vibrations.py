"""Shared vibrational-mode math: one rule for what counts as an imaginary
frequency, and one rule for a mode's reduced mass.

Both halves exist for the same reason -- each was previously re-derived at
several call sites that quietly disagreed with each other.

F-026 (imaginary frequencies). This rule used to be reimplemented at every
site that needed it, and the implementations disagreed: bagel_runner.py
thresholded at 50 cm^-1, orca_runner.py and pyscf_runner.py used a bare
`f < 0`, and the frontend's VibrationTable.tsx re-derived it from the sign a
fourth time to decide which rows to paint red. The visible consequences were
real -- the same molecule at the same geometry could be reported as a
minimum by one engine and a saddle point by another, and a -5.9 cm^-1 noise
mode was rendered in "imaginary" red directly above a summary reading
`n_imaginary_frequencies: 0`.

For a number whose entire job is telling a chemist whether they have a
minimum or a transition state, that is not a cosmetic inconsistency.

Every engine's `run_frequency` now calls `summarize_frequencies` here, so
the count, the threshold and the per-mode flags all come from one place.
The per-mode `imaginary_flags` list is the part the frontend needs: it
consumes the backend's decision instead of re-deriving one, which is what
let the table and the summary disagree in the first place.

Reduced masses (needed by wigner.py's Wigner sampling) are the second half,
and they carry a sharper trap. An earlier version of this module inferred
the reduced mass purely from the mode vector's own norm, as
`mu = 1/sum(v**2)`. That identity holds *only* for a mass-deweighted mode
vector (`eigenvector / sqrt(mass)`, i.e. `sum(v**2) == 1/mu`), which is what
pyscf's `harmonic_analysis` produces in its `norm_mode` array -- and the
assumption was that ORCA and BAGEL used the same convention, since all
three do agree on printing real-space *mass-deweighted* Cartesian
displacements rather than mass-weighted Hessian eigenvectors.

That assumption is false, and it was confirmed false against a real ORCA
6.1.1 water/HF/STO-3G frequency run on this machine, not reasoned about:
**ORCA's printed NORMAL MODES are additionally unit-normalized**, giving
`sum(v**2) == 1.0000` exactly for every real mode. The old formula therefore
returned `mu = 1.0 amu` for every mode of every ORCA job -- a fabricated
number that looked plausible only for hydrogen-dominated modes (water's
true values are 1.05-1.08) and was wildly wrong wherever it mattered, e.g.
5.05 amu for formaldehyde's C=O stretch. Since the helper is used by ORCA
and BAGEL and *not* by pyscf (which passes its own authoritative
`reduced_mass` straight through), the one engine it had been validated
against was the one engine that never called it.

The formula below is instead invariant under any per-mode rescaling of the
mode vector, so it is correct for all three engines regardless of each
one's normalization convention, and needs no per-engine special case:

    mu_k = sum_a m_a |v_ak|^2 / sum_a |v_ak|^2

Verified on a real run of each: it reproduces pyscf's own `reduced_mass`
exactly (1.0787/1.0493/1.0775 for water/HF/STO-3G) and recovers ORCA's true
reduced masses (1.0811/1.047/1.0815 on the same system) where the old
formula returned 1.0/1.0/1.0.
"""
from __future__ import annotations

from pyscf.data import elements

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


def reduced_masses_from_normal_modes(normal_modes: list, symbols: list) -> list[float]:
    """normal_modes[mode][atom] = [dx, dy, dz] plus the molecule's element
    symbols -> one reduced mass (amu) per mode.

    Uses `mu_k = sum_a m_a |v_ak|^2 / sum_a |v_ak|^2`, which is invariant
    under rescaling of each mode vector and therefore correct whether the
    engine printed mass-deweighted (pyscf) or additionally unit-normalized
    (ORCA) displacement vectors -- see this module's own docstring for the
    real ORCA run that made this distinction necessary.

    A mode whose vector is all zeros (ORCA prints exactly-zero vectors for
    the projected translational/rotational modes) has no defined reduced
    mass and reports `inf`. Callers must exclude those modes rather than
    sample along them; wigner.py's low-frequency cutoff already does, since
    such a mode's frequency is also reported as 0.0.
    """
    masses = [elements.MASSES[elements.charge(s)] for s in symbols]
    reduced_masses = []
    for mode in normal_modes:
        numerator = 0.0
        denominator = 0.0
        for m, (dx, dy, dz) in zip(masses, mode):
            norm_sq = dx * dx + dy * dy + dz * dz
            numerator += m * norm_sq
            denominator += norm_sq
        reduced_masses.append(numerator / denominator if denominator else float("inf"))
    return reduced_masses
