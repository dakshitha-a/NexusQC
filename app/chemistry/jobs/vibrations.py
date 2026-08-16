"""Shared vibrational-mode math used across engines' frequency-job output.

Reduced mass per normal mode is needed for Wigner-ensemble sampling (see
wigner.py) but wasn't previously stored anywhere in this app. pyscf's own
`pyscf.hessian.thermo.harmonic_analysis` already computes it internally as
`reduced_mass = 1./numpy.einsum('izr,izr->i', norm_mode, norm_mode)` --
i.e. `1.0 / sum(norm_mode[mode][atom][xyz]**2)` -- confirmed by reading
that function's source directly. This uses *only* the normal_modes array
itself (no atomic-mass table needed) and applies uniformly to any engine's
normal_modes array, because normal_modes[mode][atom] = [dx, dy, dz] is
confirmed identical in shape and physical meaning (mass-deweighted
real-space Cartesian displacement, not mass-weighted) across pyscf/orca/
bagel's frequency-job summaries -- see each runner's own normal_modes
docstring. pyscf keeps using its own authoritative value directly (see
pyscf_runner.run_frequency) rather than this helper; it's the cross-check
ground truth this helper's formula was validated against.
"""
from __future__ import annotations


def reduced_masses_from_normal_modes(normal_modes: list) -> list[float]:
    """normal_modes[mode][atom] = [dx, dy, dz] -> one reduced mass (amu)
    per mode. Same formula pyscf.hessian.thermo.harmonic_analysis uses
    internally on its own norm_mode array."""
    reduced_masses = []
    for mode in normal_modes:
        sum_sq = sum(dx * dx + dy * dy + dz * dz for dx, dy, dz in mode)
        reduced_masses.append(1.0 / sum_sq if sum_sq else float("inf"))
    return reduced_masses
