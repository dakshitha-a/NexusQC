"""Gating numerical validation for app/chemistry/jobs/wigner.py, run once
before anything else in the wigner_ensemble feature is built on top of it.

The exact scaling convention of normal_modes (mass-deweighted Cartesian
displacement, sum(disp**2) = 1/reduced_mass) is confirmed from source, but
whether sigma_q = sqrt(hbar/(2*mu*omega)) applied directly against that
array's own scaling produces the PHYSICALLY correct sampling width is not
obvious from inspection alone -- a subtle unit/normalization mismatch here
would produce a plausible-looking-but-wrong spectrum, a much worse failure
mode than a crash. This script runs a real frequency job, draws a large
Wigner ensemble, and checks the sampled ensemble's mean harmonic potential
energy against TWO independent analytic references:

  1. A direct sum over the same retained modes: <V> = sum_k (1/4) hbar*omega_k
     (the standard ground-state harmonic-oscillator virial-theorem result,
     <V> = <T> = E/4 per mode).
  2. Half of the SAME frequency job's own zero_point_energy_hartree, which
     pyscf.hessian.thermo.thermo() computes via a completely different code
     path (its own ZPE = sum_k (1/2) hbar*omega_k formula) -- so reference
     (1) and (2) agreeing with each other is itself a check that this
     script's own arithmetic is right, independent of wigner.py.

Also checks the sampled ensemble's center of mass doesn't drift from the
equilibrium geometry's (confirms translational modes were correctly
excluded by the low-frequency cutoff).

Run directly: PYTHONPATH=$PWD python3 scripts/validate_wigner_sampling.py
"""
from __future__ import annotations

import sys
import tempfile

import numpy as np
from pyscf.data import nist

from app.chemistry.jobs.pyscf_runner import run_frequency
from app.chemistry.jobs.wigner import sample_wigner_ensemble
from app.chemistry.molecule import resolve_molecule

N_SAMPLES = 5000
SEED = 20260816
CONVERGENCE_TOL_RELATIVE = 0.05  # 5% -- generous for a finite (if large) MC sample


def main() -> int:
    print(f"Running a real water/HF/STO-3G frequency job...")
    m = resolve_molecule("water")
    job_dir = tempfile.mkdtemp()
    result = run_frequency(m.to_dict(), {"method": "hf", "basis": "sto-3g", "_job_dir": job_dir})
    summary = result["summary"]

    freqs = summary["frequencies_cm-1"]
    normal_modes = summary["normal_modes"]
    reduced_mass = summary["reduced_mass_amu"]
    zpe_hartree = summary["zero_point_energy_hartree"]
    print(f"frequencies_cm-1: {freqs}")
    print(f"reduced_mass_amu: {reduced_mass}")
    print(f"zero_point_energy_hartree (from thermo()): {zpe_hartree}")

    equilibrium_molecule = m.to_dict()
    samples, diagnostics = sample_wigner_ensemble(
        equilibrium_molecule, freqs, normal_modes, reduced_mass,
        n_samples=N_SAMPLES, random_seed=SEED, low_freq_cutoff_cm1=100.0, temperature_K=0.0,
    )
    print(f"diagnostics (excl. per-sample potentials): "
          f"{ {k: v for k, v in diagnostics.items() if k != 'per_sample_harmonic_potential_hartree'} }")

    retained_idx = [i for i, f in enumerate(freqs) if f >= 100.0]
    if not retained_idx:
        print("FAIL: no modes retained -- cannot validate")
        return 1

    omega_au = np.array([freqs[i] / nist.HARTREE2WAVENUMBER for i in retained_idx])
    analytic_V_direct = float(np.sum(0.25 * omega_au))  # sum_k (1/4) hbar*omega_k, hbar=1 a.u.
    analytic_V_from_zpe = 0.5 * zpe_hartree

    print(f"analytic <V> (direct sum over retained modes): {analytic_V_direct:.8f} hartree")
    print(f"analytic <V> (0.5 * thermo ZPE, cross-check):   {analytic_V_from_zpe:.8f} hartree")
    cross_check_rel_diff = abs(analytic_V_direct - analytic_V_from_zpe) / analytic_V_from_zpe
    print(f"  -> relative difference between the two analytic references: {cross_check_rel_diff:.4%}")
    if cross_check_rel_diff > 0.01:
        print("FAIL: the two analytic references disagree by >1% -- retained-mode set likely doesn't "
              "match ZPE's own mode set (e.g. a near-zero mode above the cutoff), fix before trusting "
              "the sampled-ensemble comparison below")
        return 1

    sampled_V_mean = float(np.mean(diagnostics["per_sample_harmonic_potential_hartree"]))
    print(f"sampled ensemble mean <V> ({N_SAMPLES} samples): {sampled_V_mean:.8f} hartree")
    rel_diff = abs(sampled_V_mean - analytic_V_direct) / analytic_V_direct
    print(f"  -> relative difference from analytic: {rel_diff:.4%}")

    equilibrium_coords = np.array(equilibrium_molecule["coords"])
    eq_com = equilibrium_coords.mean(axis=0)
    sample_coords = np.array([s["coords"] for s in samples])
    sample_coms = sample_coords.mean(axis=1)  # (n_samples, 3)
    mean_com_drift = float(np.linalg.norm(sample_coms.mean(axis=0) - eq_com))
    print(f"mean sampled center-of-mass drift from equilibrium: {mean_com_drift:.6f} Angstrom")

    ok = True
    if rel_diff > CONVERGENCE_TOL_RELATIVE:
        print(f"FAIL: sampled <V> does not converge to the analytic value within "
              f"{CONVERGENCE_TOL_RELATIVE:.0%} -- the sigma_q formula/scaling is likely wrong")
        ok = False
    else:
        print(f"PASS: sampled <V> converges to the analytic value within {CONVERGENCE_TOL_RELATIVE:.0%}")

    if mean_com_drift > 0.01:
        print("FAIL: sampled ensemble's center of mass drifted >0.01 Angstrom from equilibrium -- "
              "translational modes were not correctly excluded")
        ok = False
    else:
        print("PASS: no meaningful center-of-mass drift (translational modes correctly excluded)")

    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
