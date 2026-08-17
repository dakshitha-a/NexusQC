"""Ground-state Wigner (nuclear-ensemble) sampling of geometries from a
completed frequency job's harmonic normal modes.

Pure functions, no engine imports, no I/O -- takes plain dicts/lists so it
works identically regardless of which engine (pyscf/orca/bagel) produced
the source frequency job. See app/chemistry/jobs/vibrations.py for the
reduced-mass convention this module consumes.

Physics: a mode k with (real, non-imaginary) frequency omega_k and reduced
mass mu_k is treated as an independent 1D quantum harmonic oscillator along
the UNIT Cartesian direction normal_modes[k]/|normal_modes[k]|. The
ground-state (and, at temperature_K > 0, thermally populated) Wigner
distribution for that oscillator's position is Gaussian with standard
deviation sigma_q = sqrt(hbar / (2 * mu_k * omega_k)) *
sqrt(coth(hbar * omega_k / (2 * k_B * T))) -- the coth factor is exactly 1
at T=0 (pure ground-state sampling, this module's default) and grows for a
thermally populated ensemble. All internal arithmetic is done in atomic
units (hbar = 1, mass in m_e, energy in hartree, length in bohr) using the
same pyscf.data.nist constants pyscf.hessian.thermo already uses
internally, converting back to Angstrom (this app's molecule-dict
convention) only for the final Cartesian displacement. Momentum is not
sampled -- there is no dynamics/trajectory capability in this app for a
momentum to feed into (see CLAUDE.md's known-limitations note on this).

**The mode vector MUST be normalized to unit length before sigma_q is
applied to it, and getting this wrong was a real, shipped bug.** The
sigma_q formula above carries a 1/sqrt(mu_k), which pairs it with a
dimensionless unit direction: in mass-weighted normal coordinates the
effective mass is exactly 1, so the mass dependence of the physical
displacement is carried once, by mu_k, and once only. An earlier version of
this module multiplied sigma_q straight into pyscf's raw `norm_mode` array,
whose own norm is itself 1/sqrt(mu_k) (it is the mass-DEweighted
eigenvector, `l/sqrt(m)`) -- so the 1/sqrt(mu_k) was applied twice and every
displacement came out too small by a factor of sqrt(mu_k). That is ~4% for a
hydrogen-dominated mode (mu ~ 1 amu, which is why a water test looked
almost right) but a factor of 2.2 for formaldehyde's mu = 5.05 amu C=O
stretch and 3.4 for the mu = 11.5 amu modes of a real 12-atom molecule --
i.e. wrong precisely on the heavy-atom modes that shape a real
chromophore's absorption band. It was caught by evaluating the CARTESIAN
Hessian quadratic form on the sampled geometries (see
scripts/validate_wigner_sampling.py), which is the only check that actually
tests this mapping; the mean harmonic potential energy came out 24% below
the analytic sum(hbar*omega/4) for formaldehyde, and 1.2% within it after
the fix.

REQUIRED before this module is trusted after any change: run
scripts/validate_wigner_sampling.py. See that script's own docstring for
why its Cartesian-Hessian check is the load-bearing one and why an
apparently equivalent check expressed in this module's own normal
coordinates is worthless (it is an algebraic identity that holds whether
the Cartesian mapping is right or wrong).
"""
from __future__ import annotations

import copy
import math

import numpy as np
from pyscf.data import nist

from app.chemistry.jobs.vibrations import is_imaginary, reduced_masses_from_normal_modes

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
    low_freq_cutoff_cm1 (translational/rotational residue), any
    imaginary-frequency mode, and any mode whose displacement vector is
    all zeros (ORCA prints exactly-zero vectors for its projected
    translational/rotational modes) are dropped before sampling and never
    raise -- all three are counted in diagnostics and surfaced by the
    caller as a param_notes-style warning, matching this app's established
    "corrections are surfaced, not silent" convention
    (param_normalize.py)."""
    n_modes_total = len(frequencies_cm1)
    modes_array = np.asarray(normal_modes, dtype=float)
    mode_norms = np.sqrt(np.einsum("kax,kax->k", modes_array, modes_array)) if n_modes_total else np.zeros(0)

    # Imaginary detection goes through vibrations.is_imaginary rather than a
    # bare `f < 0`: that is the app-wide rule (threshold, not sign -- see
    # that module's F-026 docstring), and a bare sign test also misclassifies
    # pyscf's own output, where freq_wavenumber is genuinely complex and an
    # imaginary root's REAL part is 0.0, so it would silently land in the
    # low-frequency bucket and report zero imaginary modes.
    imaginary = [is_imaginary(f) for f in frequencies_cm1]
    retained_idx = [
        i for i, f in enumerate(frequencies_cm1)
        if not imaginary[i] and f >= low_freq_cutoff_cm1 and mode_norms[i] > 0
    ]
    n_imaginary_dropped = sum(imaginary)
    n_zero_norm_dropped = sum(
        1 for i, f in enumerate(frequencies_cm1)
        if not imaginary[i] and f >= low_freq_cutoff_cm1 and mode_norms[i] <= 0
    )
    n_low_freq_dropped = n_modes_total - len(retained_idx) - n_imaginary_dropped - n_zero_norm_dropped

    rng = np.random.default_rng(random_seed)
    equilibrium_coords = np.array(equilibrium_molecule["coords"], dtype=float)  # (n_atoms, 3), angstrom

    diagnostics = {
        "n_modes_total": n_modes_total, "n_modes_retained": len(retained_idx),
        "n_modes_dropped_low_freq": n_low_freq_dropped, "n_modes_imaginary_dropped": n_imaginary_dropped,
        "n_modes_dropped_zero_norm": n_zero_norm_dropped,
        "low_freq_cutoff_cm1": low_freq_cutoff_cm1, "temperature_K": temperature_K,
        "per_sample_harmonic_potential_hartree": [0.0] * n_samples,
    }
    if not retained_idx:
        samples = [copy.deepcopy(equilibrium_molecule) for _ in range(n_samples)]
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

    # UNIT direction vectors, not the engine's own raw array -- see this
    # module's docstring for the shipped bug that came of skipping this, and
    # note that the two engines genuinely differ here (pyscf's vectors have
    # norm 1/sqrt(mu), ORCA's are already unit-length), so normalizing is
    # also what makes the two engines agree on the same molecule.
    retained_modes = modes_array[retained_idx] / mode_norms[retained_idx][:, None, None]
    # displacement[s, atom, xyz] = sum_k Q[s, k] * retained_modes[k, atom, xyz]
    displacements = np.einsum("sk,kax->sax", Q, retained_modes)
    displaced_coords = equilibrium_coords[None, :, :] + displacements  # (n_samples, n_atoms, 3)

    # Harmonic potential energy of each sample, in the SAME normal-coordinate
    # basis Q was drawn in: V = 0.5 * sum_k mu_k * omega_k^2 * q_k^2 (atomic
    # units), q_k = Q[s, k] converted back to bohr. Exposed for
    # scripts/validate_wigner_sampling.py's convergence check -- not used
    # anywhere else. NOTE this is NOT an independent check of the Cartesian
    # mapping above (it is an algebraic identity in these coordinates); the
    # validation script's Cartesian-Hessian check is the real one.
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

    diagnostics["per_sample_harmonic_potential_hartree"] = potential_hartree.tolist()
    return samples, diagnostics


def sample_from_source_job(
    source_molecule: dict, source_summary: dict, n_samples: int, random_seed: int,
    low_freq_cutoff_cm1: float = DEFAULT_LOW_FREQ_CUTOFF_CM1, temperature_K: float = 0.0,
) -> tuple[list[dict], dict]:
    """Thin wrapper around sample_wigner_ensemble that pulls what it needs
    straight out of a completed frequency job's own summary dict, plus its
    own molecule as the equilibrium geometry -- the one piece of extraction
    logic shared by both app/agent/tools.py's _build_ensemble_spec_or_error
    (the initial submit, and its post-approval re-derivation) and
    app/chemistry/jobs/ensemble_orchestrator.py (each wave-dispatch tick),
    so both regenerate the identical sample set from the identical inputs
    rather than two independent extraction code paths risking drift.

    Reduced masses are always RECOMPUTED here from the normal modes and the
    molecule's element symbols, never read from the summary's own
    `reduced_mass_amu`, for two reasons. First, correctness has to be
    self-contained: mu and the mode vectors must be a matched pair (see
    vibrations.py), and recomputing both from the one array guarantees that
    regardless of which engine wrote the summary or which version of this
    app wrote it -- a frequency job whose stored `reduced_mass_amu` predates
    the vibrations.py fix carries fabricated 1.0-amu values for every ORCA
    mode, and trusting it would silently reintroduce the bug. Second, it
    means any completed frequency job with a `normal_modes` array can be
    sampled, including every job run before `reduced_mass_amu` existed at
    all, so a user is not asked to re-run a finished (possibly hours-long)
    frequency calculation just to obtain a number derivable from what it
    already recorded.

    Raises a plain, actionable ValueError (not a bare KeyError) if the
    source job's summary is missing what's needed -- callers are expected to
    have already confirmed the source job is a completed frequency job
    before calling this."""
    frequencies_cm1 = source_summary.get("frequencies_cm-1")
    normal_modes = source_summary.get("normal_modes")
    if not frequencies_cm1 or not normal_modes:
        raise ValueError(
            "the source frequency job's summary has no frequencies_cm-1/normal_modes to sample from"
        )
    symbols = source_molecule.get("symbols")
    if not symbols:
        raise ValueError("the source frequency job's molecule has no element symbols to derive masses from")
    reduced_mass_amu = reduced_masses_from_normal_modes(normal_modes, symbols)
    return sample_wigner_ensemble(
        source_molecule, frequencies_cm1, normal_modes, reduced_mass_amu,
        n_samples=n_samples, random_seed=random_seed,
        low_freq_cutoff_cm1=low_freq_cutoff_cm1, temperature_K=temperature_K,
    )
