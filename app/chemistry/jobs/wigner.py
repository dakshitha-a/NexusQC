"""Ground-state Wigner (nuclear-ensemble) sampling of geometries from a
completed frequency job's harmonic normal modes.

Pure functions, no engine imports, no I/O -- takes plain dicts/lists so it
works identically regardless of which engine (pyscf/orca/bagel) produced
the source frequency job. See app/chemistry/jobs/vibrations.py for the
reduced-mass convention this module consumes.

Physics: a mode k with (real, non-imaginary) frequency omega_k and reduced
mass mu_k (both derived from normal_modes -- see vibrations.py) is treated
as an independent 1D quantum harmonic oscillator along the Cartesian
displacement direction normal_modes[k] (already mass-deweighted, so a
displacement of q along that direction needs no further mass scaling --
Cartesian displacement contribution = q * normal_modes[k], directly). The
ground-state (and, at temperature_K > 0, thermally populated) Wigner
distribution for that oscillator's position is Gaussian with standard
deviation sigma_q = sqrt(hbar / (2 * mu_k * omega_k)) * sqrt(coth(hbar *
omega_k / (2 * k_B * T))) -- the coth factor is exactly 1 at T=0 (pure
ground-state sampling, this module's default) and grows for a thermally
populated ensemble. All internal arithmetic is done in atomic units (hbar
= 1, mass in m_e, energy in hartree, length in bohr) using the same
pyscf.data.nist constants pyscf.hessian.thermo already uses internally,
converting back to Angstrom (this app's molecule-dict convention) only for
the final Cartesian displacement. Momentum is not sampled -- there is no
dynamics/trajectory capability in this app for a momentum to feed into
(see CLAUDE.md's known-limitations note on this).

REQUIRED before this module is trusted for real jobs: run
scripts/validate_wigner_sampling.py (a real frequency job, thousands of
samples, confirms the sampled ensemble's mean harmonic potential energy
converges to the analytic ground-state expectation value). See that
script's own docstring.
"""
from __future__ import annotations

import copy
import math

import numpy as np
from pyscf.data import nist

# Distinct from render_ir_spectrum_plot's _TRANS_ROT_FREQ_CUTOFF_CM1 (10.0
# cm-1, a purely cosmetic plot-axis cutoff) -- here a retained soft mode
# directly inflates the sampling amplitude (sigma_q ~ 1/sqrt(omega)), so a
# much higher, physically-motivated default is used: comfortably above
# translational/rotational residue and generic low-frequency numerical
# noise, comfortably below any real vibrational mode worth sampling.
DEFAULT_LOW_FREQ_CUTOFF_CM1 = 100.0


def _sigma_q_bohr(freq_cm1: float, reduced_mass_amu: float, temperature_K: float) -> float:
    omega_au = freq_cm1 / nist.HARTREE2WAVENUMBER  # hbar=1 in a.u., so energy == angular frequency
    mu_au = reduced_mass_amu * nist.AMU2AU
    sigma_t0 = math.sqrt(1.0 / (2.0 * mu_au * omega_au))
    if temperature_K <= 0:
        return sigma_t0
    kT_au = temperature_K * nist.BOLTZMANN / nist.HARTREE2J
    x = omega_au / (2.0 * kT_au)
    coth_x = 1.0 / math.tanh(x) if x < 700 else 1.0  # tanh saturates to 1 well before overflow
    return sigma_t0 * math.sqrt(coth_x)


def sample_wigner_ensemble(
    equilibrium_molecule: dict,
    frequencies_cm1: list,
    normal_modes: list,
    reduced_mass_amu: list,
    n_samples: int,
    random_seed: int,
    low_freq_cutoff_cm1: float = DEFAULT_LOW_FREQ_CUTOFF_CM1,
    temperature_K: float = 0.0,
) -> tuple[list[dict], dict]:
    """Returns (sampled molecule dicts, diagnostics). Modes below
    low_freq_cutoff_cm1 (translational/rotational residue) and any
    imaginary-frequency mode are dropped before sampling and never raise --
    both are counted in diagnostics and surfaced by the caller as a
    param_notes-style warning, matching this app's established "corrections
    are surfaced, not silent" convention (param_normalize.py)."""
    n_modes_total = len(frequencies_cm1)
    retained_idx = [
        i for i, f in enumerate(frequencies_cm1)
        if f >= low_freq_cutoff_cm1
    ]
    n_imaginary_dropped = sum(1 for f in frequencies_cm1 if f < 0)
    n_low_freq_dropped = n_modes_total - len(retained_idx) - n_imaginary_dropped
    # (a mode can only be dropped for exactly one reason: f < 0 is disjoint
    # from 0 <= f < cutoff, so the two dropped-counts above never overlap)

    rng = np.random.default_rng(random_seed)
    equilibrium_coords = np.array(equilibrium_molecule["coords"], dtype=float)  # (n_atoms, 3), angstrom

    if not retained_idx:
        samples = [copy.deepcopy(equilibrium_molecule) for _ in range(n_samples)]
        diagnostics = {
            "n_modes_total": n_modes_total, "n_modes_retained": 0,
            "n_modes_dropped_low_freq": n_low_freq_dropped, "n_modes_imaginary_dropped": n_imaginary_dropped,
            "low_freq_cutoff_cm1": low_freq_cutoff_cm1, "temperature_K": temperature_K,
            "per_sample_harmonic_potential_hartree": [0.0] * n_samples,
        }
        return samples, diagnostics

    sigmas_bohr = np.array([
        _sigma_q_bohr(frequencies_cm1[i], reduced_mass_amu[i], temperature_K) for i in retained_idx
    ])
    sigmas_angstrom = sigmas_bohr * nist.BOHR
    # Q[:, k] ~ Normal(0, sigmas_angstrom[k]), one full (n_samples, n_retained) draw at once --
    # deterministic given (random_seed, n_samples), which is what lets a
    # wave-dispatching orchestrator regenerate the same array on demand
    # (see the wigner_ensemble architecture plan) without persisting it a
    # second time beyond the ensemble.xyz artifact written once at submit.
    Q = rng.normal(loc=0.0, scale=sigmas_angstrom, size=(n_samples, len(retained_idx)))

    retained_modes = np.array([normal_modes[i] for i in retained_idx])  # (n_retained, n_atoms, 3), angstrom
    # displacement[s, atom, xyz] = sum_k Q[s, k] * retained_modes[k, atom, xyz]
    displacements = np.einsum("sk,kax->sax", Q, retained_modes)
    displaced_coords = equilibrium_coords[None, :, :] + displacements  # (n_samples, n_atoms, 3)

    # Harmonic potential energy of each sample, in the SAME normal-coordinate
    # basis Q was drawn in: V = 0.5 * sum_k mu_k * omega_k^2 * q_k^2 (atomic
    # units), q_k = Q[s, k] converted back to bohr. Exposed for
    # scripts/validate_wigner_sampling.py's convergence check -- not used
    # anywhere else.
    omega_au = np.array([frequencies_cm1[i] / nist.HARTREE2WAVENUMBER for i in retained_idx])
    mu_au = np.array([reduced_mass_amu[i] * nist.AMU2AU for i in retained_idx])
    Q_bohr = Q / nist.BOHR
    potential_hartree = 0.5 * np.sum(mu_au[None, :] * omega_au[None, :] ** 2 * Q_bohr ** 2, axis=1)

    samples = []
    for s in range(n_samples):
        mol = copy.deepcopy(equilibrium_molecule)
        mol["coords"] = displaced_coords[s].tolist()
        mol["name"] = f"{equilibrium_molecule.get('name', 'molecule')} (Wigner sample {s})"
        samples.append(mol)

    diagnostics = {
        "n_modes_total": n_modes_total, "n_modes_retained": len(retained_idx),
        "n_modes_dropped_low_freq": n_low_freq_dropped, "n_modes_imaginary_dropped": n_imaginary_dropped,
        "low_freq_cutoff_cm1": low_freq_cutoff_cm1, "temperature_K": temperature_K,
        "per_sample_harmonic_potential_hartree": potential_hartree.tolist(),
    }
    return samples, diagnostics
