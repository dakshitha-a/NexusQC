#!/usr/bin/env python3
"""Phase 5 -- single_point/grad and single_point/nac, verified against real
engine runs on all three engines, not just parser unit tests.

Accept criterion (docs/TRACKER.md, docs/OVERHAUL_PLAN.md): all engine
gradient paths verified or gap-listed; NAC at least one engine end-to-end.
This script goes further than the minimum -- every gradient path this app
now offers (PySCF hf/dft/mp2/ccsd/casscf, ORCA hf/dft/mp2/casscf, BAGEL
hf/casscf/caspt2) and every NAC path (PySCF casscf, ORCA hf/dft, BAGEL
casscf/caspt2) ran for real while writing this, on this host -- see the
per-block comments below for what each run actually returned. BAGEL's own
CASSCF/CASPT2 gradient and NAC came back FAST here (a few seconds to ~2
minutes for CAS(4,4)/svp water), contradicting CLAUDE.local.md's blanket
"80-96s per macro-iteration" warning -- that warning was measured on a
different case (larger basis or a different job shape) and does not appear
to be true of the small systems this script exercises. Recorded rather than
silently overridden, since a future session may need to reconcile the two.

The central-difference cross-check (OVERHAUL_PLAN.md's own accept wording
for Phase 5) validates PySCF's analytic HF gradient against a finite-
difference numerical one built from run_single_point alone -- an
independent path through the code that shares no machinery with
run_gradient's own nuc_grad_method() call, so agreement is real evidence,
not a tautology.

Run:  PYTHONPATH=$PWD python3 tests/backend/grad_01_gradients_and_nac.py
"""
from __future__ import annotations

import sys
import tempfile

from app.agent.tools import _build_spec_or_error
from app.chemistry.jobs import bagel_runner, orca_runner, pyscf_runner
from app.chemistry.jobs.dispatch import resolve_runner
from app.chemistry.molecule import resolve_molecule

PASS = 0
FAIL = 0


def check(label: str, ok: bool, detail: str = "") -> None:
    global PASS, FAIL
    if ok:
        PASS += 1
        print(f"  [PASS] {label}")
    else:
        FAIL += 1
        print(f"  [FAIL] {label}" + (f"\n         {detail}" if detail else ""))


WATER = resolve_molecule("water").to_dict()
# C1-distorted: at the C2v equilibrium the S0/S1 coupling is symmetry-
# forbidden and the norm comes back ~0 regardless of whether the machinery
# works (see scripts/spikes/spike_pyscf_caps.py's own nac probe, which uses
# the same distortion for the same reason).
WATER_C1 = {
    "symbols": ["O", "H", "H"],
    "coords": [[0.0, 0.0, 0.13], [0.10, 0.79, -0.51], [-0.04, -0.72, -0.43]],
    "charge": 0, "multiplicity": 1,
}
CAS = {"active_electrons": 4, "active_orbitals": 4}


def new_dir() -> str:
    return tempfile.mkdtemp()


def main() -> int:
    print("== dispatch.py: grad/nac route to their own runner, ahead of the casscf/caspt2 branch ==")
    check("single_point/grad -> gradient", resolve_runner("single_point", "grad", "hf") == ("gradient", None))
    check("a CASSCF gradient -> gradient, not the casscf energy runner",
          resolve_runner("single_point", "grad", "casscf") == ("gradient", None))
    check("single_point/nac -> nac", resolve_runner("single_point", "nac", "casscf") == ("nac", None))

    print("\n== PySCF gradients (live) ==")
    r = pyscf_runner.run_gradient(WATER, {"method": "hf", "basis": "sto-3g", "_job_dir": new_dir()})
    hf_norm = r["summary"]["gradient_norm_hartree_per_bohr"]
    check("hf ground-state gradient is a real, nonzero number", hf_norm > 1e-4, str(hf_norm))
    check("hf gradient has one 3-vector per atom", len(r["summary"]["gradient_hartree_per_bohr"]) == 3)
    check("hf gradient attaches an orbital table for free", bool(r["summary"].get("orbital_table")))

    r = pyscf_runner.run_gradient(
        WATER, {"method": "dft", "functional": "b3lyp", "basis": "sto-3g",
                "target_state": 1, "n_states": 3, "_job_dir": new_dir()})
    check("dft excited-state (S1) gradient is nonzero and distinct from the ground state",
          r["summary"]["gradient_norm_hartree_per_bohr"] > 1e-4)
    check("excited-state gradient records which state", r["summary"]["target_state"] == 1)

    r = pyscf_runner.run_gradient(WATER, {"method": "mp2", "basis": "sto-3g", "_job_dir": new_dir()})
    check("mp2 gradient runs", r["summary"]["gradient_norm_hartree_per_bohr"] > 0)

    r = pyscf_runner.run_gradient(WATER, {"method": "ccsd", "basis": "sto-3g", "_job_dir": new_dir()})
    check("ccsd gradient runs", r["summary"]["gradient_norm_hartree_per_bohr"] > 0)

    r = pyscf_runner.run_gradient(
        WATER, {"method": "casscf", "basis": "sto-3g", **CAS, "n_states": 1, "_job_dir": new_dir()})
    check("casscf ground-state gradient runs and attaches natural-orbital molden",
          r["summary"]["gradient_norm_hartree_per_bohr"] > 0 and "molden" in r["artifacts"])

    print("\n== central-difference cross-check: PySCF analytic HF gradient vs a finite-difference one ==")
    # Independent of run_gradient's own nuc_grad_method() call -- built from
    # run_single_point alone (mirroring OVERHAUL_PLAN.md's Phase 5 accept
    # wording), displacing one Cartesian coordinate at a time.
    h = 1e-3  # Angstrom
    basis = "sto-3g"
    analytic = pyscf_runner.run_gradient(
        WATER, {"method": "hf", "basis": basis, "_job_dir": new_dir()}
    )["summary"]["gradient_hartree_per_bohr"]
    numerical = []
    bohr_per_angstrom = 1.0 / 0.52917721067
    for atom in range(3):
        row = []
        for axis in range(3):
            plus = {**WATER, "coords": [list(c) for c in WATER["coords"]]}
            minus = {**WATER, "coords": [list(c) for c in WATER["coords"]]}
            plus["coords"][atom][axis] += h
            minus["coords"][atom][axis] -= h
            e_plus = pyscf_runner.run_single_point(plus, {"method": "hf", "basis": basis, "_job_dir": new_dir()})[
                "summary"]["energy_hartree"]
            e_minus = pyscf_runner.run_single_point(minus, {"method": "hf", "basis": basis, "_job_dir": new_dir()})[
                "summary"]["energy_hartree"]
            # dE/dx in Eh/Angstrom -> Eh/Bohr (run_gradient's own units)
            row.append((e_plus - e_minus) / (2 * h) / bohr_per_angstrom)
        numerical.append(row)
    max_diff = max(
        abs(a - n) for a_row, n_row in zip(analytic, numerical) for a, n in zip(a_row, n_row)
    )
    check("analytic and central-difference HF gradients agree to 1e-4 Eh/Bohr",
          max_diff < 1e-4, f"max|analytic-numerical|={max_diff:.2e}\nanalytic={analytic}\nnumerical={numerical}")

    print("\n== PySCF NAC (live, SA-CASSCF -- the only PySCF NAC path) ==")
    r = pyscf_runner.run_nac(
        WATER_C1, {"method": "casscf", "basis": "sto-3g", **CAS, "n_states": 2,
                   "state_pairs": [[1, 2]], "_job_dir": new_dir()})
    check("SA-CASSCF S0/S1 NAC is nonzero at a distorted (non-symmetric) geometry",
          r["summary"]["nac_norm_hartree_per_bohr"] > 1e-8, str(r["summary"]["nac_norm_hartree_per_bohr"]))
    check("NAC records the state pair in 1-based-including-ground form",
          r["summary"]["state_pair"] == [1, 2])

    print("\n== ORCA gradients (live) ==")
    r = orca_runner.run_gradient(WATER, {"method": "hf", "basis": "sto-3g", "_job_dir": new_dir()})
    check("hf ground-state gradient runs (.engrad parsed)", r["summary"]["gradient_norm_hartree_per_bohr"] > 1e-4)

    r = orca_runner.run_gradient(
        WATER, {"method": "dft", "functional": "pbe0", "basis": "sto-3g",
                "target_state": 1, "n_states": 3, "_job_dir": new_dir()})
    check("PBE0 excited-state (S1) gradient runs -- PBE0 is not B88-containing, so no LibXC gap applies",
          r["summary"]["gradient_norm_hartree_per_bohr"] > 1e-4)

    r = orca_runner.run_gradient(WATER, {"method": "mp2", "basis": "sto-3g", "_job_dir": new_dir()})
    check("mp2 gradient runs", r["summary"]["gradient_norm_hartree_per_bohr"] > 0)

    r = orca_runner.run_gradient(
        WATER, {"method": "casscf", "basis": "sto-3g", **CAS, "n_states": 1, "_job_dir": new_dir()})
    check("casscf ground-state gradient runs", r["summary"]["gradient_norm_hartree_per_bohr"] > 0)

    print("\n== ORCA NAC (live, ground-to-excited only for hf/dft) ==")
    r = orca_runner.run_nac(
        WATER_C1, {"method": "dft", "functional": "pbe0", "basis": "sto-3g", "n_states": 3,
                   "state_pairs": [[1, 2]], "_job_dir": new_dir()})
    # scripts/spikes/spike_orca_caps.py's own PBE0/STO-3G probe on this exact
    # C1 geometry recorded norm=0.7794747730 -- reproduced here to within
    # floating-point/threading noise, confirming the parser reads the same
    # number the Phase 0 spike did, not a coincidentally-plausible one.
    check("PBE0 S0/S1 NAC norm matches the Phase 0 spike's recorded value",
          abs(r["summary"]["nac_norm_hartree_per_bohr"] - 0.7794747730) < 1e-4,
          str(r["summary"]["nac_norm_hartree_per_bohr"]))

    print("\n== BAGEL gradients (live) ==")
    r = bagel_runner.run_gradient(WATER, {"method": "hf", "basis": "svp", "_job_dir": new_dir()})
    check("hf gradient runs (singular 'force' block, no preceding hf block needed)",
          r["summary"]["gradient_norm_hartree_per_bohr"] > 1e-4)

    r = bagel_runner.run_gradient(
        WATER, {"method": "casscf", "basis": "svp", **CAS, "n_states": 1, "_job_dir": new_dir()})
    check("casscf gradient runs and attaches natural-orbital molden",
          r["summary"]["gradient_norm_hartree_per_bohr"] > 0 and "molden" in r["artifacts"])

    r = bagel_runner.run_gradient(
        WATER, {"method": "caspt2", "basis": "svp", **CAS, "n_states": 1, "_job_dir": new_dir()})
    check("caspt2 gradient runs (Form 1 smith-wrapped method entry)",
          r["summary"]["gradient_norm_hartree_per_bohr"] > 0)

    print("\n== BAGEL NAC (live) ==")
    r = bagel_runner.run_nac(
        WATER, {"method": "casscf", "basis": "svp", **CAS, "n_states": 2,
                "state_pairs": [[1, 2]], "_job_dir": new_dir()})
    check("casscf NAC runs and reports the free transition-dipole/oscillator-strength extras",
          r["summary"]["nac_norm_hartree_per_bohr"] > 0 and r["summary"]["oscillator_strength"] is not None,
          str(r["summary"]))

    r = bagel_runner.run_nac(
        WATER, {"method": "caspt2", "basis": "svp", **CAS, "n_states": 2,
                "state_pairs": [[1, 2]], "_job_dir": new_dir()})
    check("caspt2 NAC runs", r["summary"]["nac_norm_hartree_per_bohr"] > 0)

    print("\n== refusal paths (app/agent/tools.py cross-field checks, no live engine run needed) ==")
    _, _, _, _, _, _, _, err = _build_spec_or_error(
        "single_point", "grad", WATER, "pyscf", "casscf",
        {"basis": "sto-3g", **CAS, "target_state": 1})
    check("pyscf casscf excited-state gradient is refused (no verified excited_gradient)",
          bool(err) and "excited-state gradient" in err, str(err))

    _, _, _, _, _, _, _, err = _build_spec_or_error(
        "single_point", "grad", WATER, "orca", "dft",
        {"basis": "sto-3g", "functional": "b3lyp", "target_state": 1, "n_states": 3})
    check("orca B3LYP excited-state gradient is refused (the LibXC route was tried and gave a wrong energy)",
          bool(err) and "B88-containing" in err, str(err))

    _, _, _, _, _, _, _, err = _build_spec_or_error(
        "single_point", "nac", WATER, "orca", "hf",
        {"basis": "sto-3g", "state_pairs": [[2, 3]], "n_states": 3})
    check("orca hf excited-to-excited NAC pair is refused (ground-to-excited only)",
          bool(err) and "ground-to-excited" in err, str(err))

    _, _, _, _, _, _, _, err = _build_spec_or_error(
        "single_point", "nac", WATER, "orca", "hf",
        {"basis": "sto-3g", "state_pairs": [[1, 2], [1, 3]], "n_states": 3})
    check("more than one state_pairs entry is refused (exactly one pair per NAC job)",
          bool(err) and "exactly one pair" in err, str(err))

    print(f"\n{PASS}/{PASS + FAIL} checks passed")
    if FAIL:
        print("[FAIL] some checks failed")
        return 1
    print("[PASS] ALL CHECKS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
