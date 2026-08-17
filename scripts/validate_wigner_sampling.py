"""Gating numerical validation for app/chemistry/jobs/wigner.py. Run this
after ANY change to wigner.py or vibrations.py:

    PYTHONPATH=$PWD python3 scripts/validate_wigner_sampling.py

WHY THIS SCRIPT LOOKS THE WAY IT DOES -- read before editing it.

An earlier version of this script checked the sampled ensemble's mean
harmonic potential energy against sum_k hbar*omega_k/4, computing <V> from
wigner.py's own `per_sample_harmonic_potential_hartree` diagnostic. That
check passed while wigner.py contained a real, serious bug, and it could
never have failed: that diagnostic is V = 0.5*mu*omega^2*q^2 evaluated on
the very q the sampler drew from a distribution of width
sqrt(hbar/(2*mu*omega)), so <V> = hbar*omega/4 is an algebraic IDENTITY in
those coordinates, for any mu, whether or not the normal-coordinate ->
Cartesian mapping is correct. It validated the 1D oscillator arithmetic and
was structurally blind to the only step that can actually go wrong.

The bug it missed: sigma_q carries a 1/sqrt(mu), so it must multiply a UNIT
direction vector, but it was being multiplied into pyscf's raw `norm_mode`
array, whose own norm is also 1/sqrt(mu). Every displacement was too small
by sqrt(mu) -- invisible for hydrogen-dominated modes (mu ~ 1 amu) and a
factor of 2.2+ for heavy-atom modes.

So the load-bearing check here evaluates the CARTESIAN Hessian quadratic
form, V = 0.5 * dx^T H dx, on the actual displaced geometries the sampler
hands to sub-jobs, using a Hessian this script obtains independently. That
shares no arithmetic with the sampler and is the only formulation that tests
the Cartesian mapping. Both molecules are optimized to a stationary point
first, so V has no linear term and the quadratic form is the whole energy.

FORMALDEHYDE IS NOT OPTIONAL. Water's modes all have mu ~ 1.05 amu, so the
sqrt(mu) error is only ~4% there and a loose tolerance can absorb it.
Formaldehyde has a mu = 5.05 amu mode, where the same bug shows up as a 24%
deficit. Keep a molecule with a genuinely heavy-atom mode in this list.

Also checked: that vibrations.reduced_masses_from_normal_modes reproduces
pyscf's own authoritative `reduced_mass` (it is used by ORCA and BAGEL but
NOT by pyscf, so pyscf is the only available ground truth for it), and that
the ensemble's center of mass does not drift (confirms the
translational/rotational modes really were excluded).
"""
from __future__ import annotations

import sys

import numpy as np
from pyscf import gto, scf
from pyscf.data import nist
from pyscf.geomopt.geometric_solver import optimize
from pyscf.hessian import thermo

from app.chemistry.jobs.vibrations import reduced_masses_from_normal_modes
from app.chemistry.jobs.wigner import sample_wigner_ensemble

N_SAMPLES = 6000
SEED = 20260817
# MC noise on <V> for N=6000 over a handful of modes is well under 1%.
CONVERGENCE_TOL_RELATIVE = 0.03
REDUCED_MASS_TOL_RELATIVE = 1e-6
CUTOFF_CM1 = 100.0

CASES = [
    ("water", "O 0 0 0.117; H 0 0.757 -0.467; H 0 -0.757 -0.467"),
    # Carries a mu = 5.05 amu mode -- the case that discriminates. See the
    # module docstring: do not drop this one.
    ("formaldehyde", "C 0 0 -0.53; O 0 0 0.68; H 0 0.93 -1.08; H 0 -0.93 -1.08"),
]


def check(label: str, ok: bool, detail: str = "") -> bool:
    print(f"  [{'PASS' if ok else 'FAIL'}] {label}" + (f" -- {detail}" if detail else ""))
    return ok


def run_case(name: str, atom: str) -> bool:
    print(f"\n=== {name} (HF/STO-3G, optimized to a stationary point) ===")
    mol = gto.M(atom=atom, basis="sto-3g", verbose=0)
    mf = scf.RHF(mol)
    mf.kernel()
    mol_eq = optimize(mf, maxsteps=80)
    mf = scf.RHF(mol_eq)
    mf.kernel()
    hess = mf.Hessian().kernel()  # (natm, natm, 3, 3), hartree/bohr^2

    natm = mol_eq.natm
    H = hess.transpose(0, 2, 1, 3).reshape(natm * 3, natm * 3)
    H = 0.5 * (H + H.T)  # symmetrize away numerical asymmetry

    info = thermo.harmonic_analysis(mol_eq, hess)
    # freq_wavenumber is genuinely complex-valued in pyscf; an imaginary
    # root's real part is 0.0, which is exactly why wigner.py must not use a
    # bare `f < 0` to detect imaginary modes.
    freqs = np.real(info["freq_wavenumber"]).tolist()
    modes = info["norm_mode"].tolist()
    mu_pyscf = info["reduced_mass"].tolist()
    symbols = [mol_eq.atom_symbol(i) for i in range(natm)]

    ok = True

    mu_helper = reduced_masses_from_normal_modes(modes, symbols)
    worst = max(abs(a - b) / b for a, b in zip(mu_helper, mu_pyscf))
    ok &= check(
        "reduced_masses_from_normal_modes reproduces pyscf's own reduced_mass",
        worst < REDUCED_MASS_TOL_RELATIVE,
        f"worst relative deviation {worst:.2e} over {len(mu_pyscf)} modes",
    )

    coords_ang = mol_eq.atom_coords() * nist.BOHR
    molecule = {
        "name": name, "symbols": symbols, "coords": coords_ang.tolist(),
        "charge": 0, "multiplicity": 1,
    }
    samples, diag = sample_wigner_ensemble(
        molecule, freqs, modes, mu_pyscf, n_samples=N_SAMPLES, random_seed=SEED,
        low_freq_cutoff_cm1=CUTOFF_CM1, temperature_K=0.0,
    )
    retained = [i for i, f in enumerate(freqs) if f >= CUTOFF_CM1]
    print(f"  modes retained: {diag['n_modes_retained']} of {diag['n_modes_total']} "
          f"(mu_amu = {[round(mu_pyscf[i], 3) for i in retained]})")

    omega_au = np.array([freqs[i] / nist.HARTREE2WAVENUMBER for i in retained])
    analytic = float(np.sum(0.25 * omega_au))

    # THE load-bearing check: the true Cartesian harmonic energy of the
    # geometries the sampler actually produced, against an analytic value it
    # shares no arithmetic with.
    dx = (np.array([s["coords"] for s in samples]) - coords_ang[None, :, :]) / nist.BOHR
    dx_flat = dx.reshape(N_SAMPLES, -1)
    V_cart = float(np.mean(0.5 * np.einsum("sa,ab,sb->s", dx_flat, H, dx_flat)))
    rel = abs(V_cart - analytic) / analytic
    print(f"  analytic <V> = sum hbar*omega/4      : {analytic:.8f} Ha")
    print(f"  Cartesian <V> = <0.5 dx^T H dx>      : {V_cart:.8f} Ha  (ratio {V_cart / analytic:.4f})")
    ok &= check(
        "sampled ensemble's TRUE Cartesian <V> matches the analytic harmonic value",
        rel < CONVERGENCE_TOL_RELATIVE,
        f"relative difference {rel:.2%} (tolerance {CONVERGENCE_TOL_RELATIVE:.0%}); "
        f"a deficit tracking sqrt(mu) means sigma_q is being applied to a non-unit mode vector",
    )

    # Kept only as a consistency check on the sampler's own bookkeeping, and
    # explicitly NOT evidence the Cartesian mapping is right -- see the
    # module docstring for why this one cannot fail on that account.
    V_normal = float(np.mean(diag["per_sample_harmonic_potential_hartree"]))
    ok &= check(
        "sampler's own normal-coordinate <V> is self-consistent (NOT a mapping check)",
        abs(V_normal - analytic) / analytic < CONVERGENCE_TOL_RELATIVE,
        f"{V_normal:.8f} Ha",
    )

    masses = np.array([gto.mole.atom_mass_list(mol_eq, isotope_avg=True)]).reshape(-1, 1)
    eq_com = (coords_ang * masses).sum(axis=0) / masses.sum()
    sample_coms = np.einsum("sax,a->sx", np.array([s["coords"] for s in samples]), masses[:, 0]) / masses.sum()
    drift = float(np.linalg.norm(sample_coms.mean(axis=0) - eq_com))
    ok &= check(
        "no meaningful center-of-mass drift (translational modes excluded)",
        drift < 0.01, f"{drift:.6f} Angstrom",
    )
    return ok


def main() -> int:
    all_ok = True
    for name, atom in CASES:
        all_ok &= run_case(name, atom)
    print("\n" + ("ALL CHECKS PASSED" if all_ok else "SOME CHECKS FAILED"))
    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())
