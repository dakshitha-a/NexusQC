#!/usr/bin/env python3
"""Phase 6 -- opt/constrained, opt/ci, opt/min's excited-state polish, and
opt_freq single-input consolidation, verified against real engine runs, not
just parser unit tests.

Accept criterion (docs/trackers/2026-08-job-system-overhaul.md, docs/OVERHAUL_PLAN.md): every subtype
runs end-to-end or produces its designed denial; capability doc regenerated.

The one real correction this phase made, not just an addition: ORCA's
opt/ci was previously hardcoded to refuse every engine but 'bagel', on a
comment claiming ORCA's route (%mecp) was "a separate, unimplemented
module" -- but capabilities.py already gave orca/hf and orca/dft ci_opt=True
at 'run' evidence from a Phase 0 spike that used '! Opt', not the ORCA
manual's own '! CI-OPT' keyword. A live rerun of that exact spike input
showed '! Opt' with the same %TDDFT/%CONICAL blocks present ran in 0.013s
of "Geometry relaxation" -- i.e. did nothing; the manual's real keyword
('! CI-OPT') genuinely drives E diff.(CI) to zero. Both engine rows'
evidence text and the refusal logic in app/agent/tools.py were corrected
here rather than trusted, per this app's own standing rule that "ran
without error" is not evidence (see the BAGEL fix_atom row this project
already treats the same way).

opt_freq (single-input, ORCA/BAGEL): a SECOND instance of the same
"ran without error" trap, caught before shipping this time rather than
after. A first attempt at BAGEL's combined optimize+hessian for CASPT2
silently ran CASSCF instead -- `_build_input`'s smith_block condition
listed every job_type that needs the CASPT2 smith-wrapped form except
the new "opt_freq", so the request built a valid-looking, error-free
CASSCF input. Caught by cross-checking the resulting frequencies against
an independent CASSCF run on the same system (numerically identical --
the tell) and by `_parse_caspt2_energies` finding nothing to parse
against a CASSCF-only output. Fixed in `_build_input`; both engines'
opt_freq runners are otherwise a real refactor, not a new mechanism
alongside the old one -- the same two summary-building functions each
standalone run_geometry_optimization/run_frequency already used are
factored out and now called twice against ONE real combined run.

Run:  PYTHONPATH=$PWD python3 tests/backend/opt_01_optimization_family.py
"""
from __future__ import annotations

import math
import sys
import tempfile

from app.agent.tools import _build_spec_or_error
from app.chemistry.jobs import bagel_runner, orca_runner, pyscf_runner
from app.chemistry.jobs.dispatch import resolve_runner
from app.chemistry.registry2.tasks import supports

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


WATER = {
    "symbols": ["O", "H", "H"],
    "coords": [[0.0, 0.0, 0.13], [0.10, 0.79, -0.51], [-0.04, -0.72, -0.43]],
    "charge": 0, "multiplicity": 1,
}
# Twisted, close to the manual's own worked S0/S1 conical-intersection
# example (data/scraped/orca/.../conicalintersections.html.txt) -- a real
# photochemistry benchmark, unlike water/STO-3G, which this app's own probe
# found genuinely hard to converge to a true crossing in default cycles.
ETHYLENE = {
    "symbols": ["C", "C", "H", "H", "H", "H"],
    "coords": [
        [0.595560237, -0.010483480, -0.000284187],
        [-0.831313750, 0.167231832, 0.001482505],
        [-1.381857976, 0.227877089, 0.963419721],
        [1.265119434, 0.874806815, 0.006897459],
        [-1.382258208, 0.243775568, -0.959090898],
        [1.027489724, -1.032962768, -0.008829646],
    ],
    "charge": 0, "multiplicity": 1,
}
CAS = {"active_electrons": 4, "active_orbitals": 4}


def new_dir() -> str:
    return tempfile.mkdtemp()


def main() -> int:
    print("== dispatch.py: opt/min, opt/constrained, opt/ci all route to geometry_optimization ==")
    check("opt/min -> geometry_optimization", resolve_runner("opt", "min", "hf") == ("geometry_optimization", None))
    check("opt/constrained -> geometry_optimization",
          resolve_runner("opt", "constrained", "hf") == ("geometry_optimization", None))
    check("opt/ci -> geometry_optimization", resolve_runner("opt", "ci", "casscf") == ("geometry_optimization", None))

    print("\n== registry2.tasks.supports(): capability-derived, not hand-enumerated ==")
    check("bagel/casscf opt/constrained is mechanically denied (fix_atom silently ignored)",
          not supports("bagel", "casscf", "opt", "constrained").supported)
    check("pyscf/hf opt/constrained is supported", supports("pyscf", "hf", "opt", "constrained").supported)
    check("orca/hf opt/constrained is supported", supports("orca", "hf", "opt", "constrained").supported)
    check("bagel/casscf opt/ci is supported (gradient-projection MECP)",
          supports("bagel", "casscf", "opt", "ci").supported)
    check("bagel/caspt2 opt/ci is supported (same MECP driver)", supports("bagel", "caspt2", "opt", "ci").supported)
    check("orca/hf opt/ci is supported (CI-OPT via CIS)", supports("orca", "hf", "opt", "ci").supported)
    check("orca/dft opt/ci is supported (CI-OPT via TDDFT)", supports("orca", "dft", "opt", "ci").supported)
    check("orca/casscf opt/ci is NOT supported (unverified -- %CONICAL proven with a TDDFT reference only)",
          not supports("orca", "casscf", "opt", "ci").supported)
    check("pyscf/casscf opt/ci is NOT supported (no pyscf.geomopt.meci)",
          not supports("pyscf", "casscf", "opt", "ci").supported)

    print("\n== app/agent/tools.py: opt/ci refusal derives from caps.has('ci_opt'), not a hardcoded engine ==")
    _, _, _, _, _, _, _, err = _build_spec_or_error(
        "opt", "ci", WATER, "orca", "hf", {"basis": "sto-3g", "target_state_2": 1})
    check("orca hf opt/ci is no longer refused outright", err is None, str(err))

    _, _, _, _, _, _, _, err = _build_spec_or_error(
        "opt", "ci", WATER, "orca", "casscf",
        {"basis": "sto-3g", **CAS, "target_state_2": 1})
    check("orca casscf opt/ci is refused (ci_opt evidence is 'unverified', untrusted)",
          bool(err) and "conical-intersection optimizer" in err, str(err))

    _, _, _, _, _, _, _, err = _build_spec_or_error(
        "opt", "ci", WATER, "pyscf", "casscf",
        {"basis": "sto-3g", **CAS, "target_state_2": 1})
    check("pyscf opt/ci is refused (no pyscf.geomopt.meci)",
          bool(err) and "conical-intersection optimizer" in err, str(err))

    _, _, _, _, _, _, _, err = _build_spec_or_error(
        "opt", "ci", WATER, "bagel", "casscf",
        {"basis": "svp", **CAS, "target_state_2": 1})
    check("bagel casscf opt/ci still works (regression, unchanged mechanism)", err is None, str(err))

    _, _, _, _, _, _, _, err = _build_spec_or_error(
        "opt", "ci", WATER, "orca", "dft",
        {"basis": "sto-3g", "functional": "pbe0", "target_state": 2, "target_state_2": 3})
    check("orca opt/ci with a non-ground first state is refused (ground-inclusive only, like sp/nac)",
          bool(err) and "includes the ground state" in err, str(err))

    _, _, _, _, _, _, _, err = _build_spec_or_error(
        "opt", "ci", WATER, "orca", "dft",
        {"basis": "sto-3g", "functional": "b3lyp", "target_state_2": 1})
    check("orca B3LYP opt/ci is refused (same B88 excited-gradient limitation as single_point/grad)",
          bool(err) and "B88-containing" in err, str(err))

    print("\n== app/agent/tools.py: opt/min's B88/excited_gradient guard now also covers ES optimization ==")
    _, _, _, _, _, _, _, err = _build_spec_or_error(
        "opt", "min", WATER, "orca", "dft",
        {"basis": "sto-3g", "functional": "b3lyp", "target_state": 1, "n_states": 3})
    check("orca B3LYP opt/min excited-state optimization is refused (was previously unguarded)",
          bool(err) and "B88-containing" in err, str(err))

    _, _, _, _, _, _, _, err = _build_spec_or_error(
        "opt", "min", WATER, "pyscf", "casscf",
        {"basis": "sto-3g", **CAS, "target_state": 1})
    check("pyscf casscf opt/min excited-state optimization is refused (no verified excited_gradient)",
          bool(err) and "excited-state gradient" in err, str(err))

    _, _, _, _, _, _, _, err = _build_spec_or_error(
        "opt", "min", WATER, "orca", "dft",
        {"basis": "sto-3g", "functional": "pbe0", "target_state": 1, "n_states": 3})
    check("orca PBE0 opt/min excited-state optimization is NOT refused (not B88-containing)", err is None, str(err))

    print("\n== app/agent/tools.py: constraints shape validated before any builder indexes it ==")
    _, _, _, _, _, _, _, err = _build_spec_or_error(
        "opt", "constrained", WATER, "pyscf", "hf",
        {"basis": "sto-3g", "constraints": [{"type": "bond", "atoms": [1, 2, 3], "value": 0.98}]})
    check("a bond constraint with the wrong atom count is refused", bool(err) and "2 1-based" in err, str(err))

    _, _, _, _, _, _, _, err = _build_spec_or_error(
        "opt", "constrained", WATER, "pyscf", "hf",
        {"basis": "sto-3g", "constraints": [{"type": "bond", "atoms": [1, 9], "value": 0.98}]})
    check("an out-of-range atom index is refused", bool(err) and "between 1 and 3" in err, str(err))

    _, _, _, _, _, _, _, err = _build_spec_or_error(
        "opt", "constrained", WATER, "pyscf", "hf",
        {"basis": "sto-3g", "constraints": [{"type": "torsion", "atoms": [1, 2], "value": 0.98}]})
    check("an unknown constraint type is refused", bool(err) and "bond" in err and "angle" in err, str(err))

    _, _, _, _, _, _, _, err = _build_spec_or_error(
        "opt", "constrained", WATER, "pyscf", "hf",
        {"basis": "sto-3g", "constraints": [{"type": "bond", "atoms": [1, 2], "value": "long"}]})
    check("a non-numeric value is refused", bool(err) and "must be a number" in err, str(err))

    _, _, _, _, _, _, _, err = _build_spec_or_error(
        "opt", "constrained", WATER, "pyscf", "hf",
        {"basis": "sto-3g", "constraints": [{"type": "bond", "atoms": [1, 2], "value": 0.98}]})
    check("a well-formed constraint passes validation", err is None, str(err))

    print("\n== PySCF opt/constrained (live) ==")
    r = pyscf_runner.run_geometry_optimization(
        WATER, {"method": "hf", "basis": "sto-3g",
                "constraints": [{"type": "bond", "atoms": [1, 2], "value": 0.98}], "_job_dir": new_dir()})
    c = r["summary"]["optimized_geometry"]["coords"]
    oh1 = math.dist(c[0], c[1])
    check("the constrained O-H bond converges to the target value (geomeTRIC $set, 1-based atoms)",
          abs(oh1 - 0.98) < 1e-4, f"O-H1={oh1}")

    print("\n== PySCF opt/min excited-state (live, TD-HF S1) ==")
    r = pyscf_runner.run_geometry_optimization(
        WATER, {"method": "dft", "functional": "pbe0", "basis": "sto-3g", "target_state": 1, "n_states": 3,
                "_job_dir": new_dir()})
    check("the excited-state optimization converges and records which state",
          r["summary"]["converged"] and r["summary"]["target_state"] == 1, str(r["summary"]))
    check("the excited-state total energy is above the ground-state one at the same (relaxed) geometry",
          r["summary"]["final_energy_hartree"] > r["summary"]["ground_state_energy_hartree"])

    print("\n== ORCA opt/constrained (live) ==")
    r = orca_runner.run_geometry_optimization(
        WATER, {"method": "hf", "basis": "sto-3g",
                "constraints": [{"type": "bond", "atoms": [1, 2], "value": 0.98}], "_job_dir": new_dir()})
    c = r["summary"]["optimized_geometry"]["coords"]
    oh1 = math.dist(c[0], c[1])
    check("the constrained O-H bond converges to the target value (%geom Constraints, 0-based atoms internally)",
          abs(oh1 - 0.98) < 1e-4, f"O-H1={oh1}")

    print("\n== ORCA opt/min excited-state (live, PBE0 TDDFT S1) ==")
    r = orca_runner.run_geometry_optimization(
        WATER, {"method": "dft", "functional": "pbe0", "basis": "sto-3g", "target_state": 1, "n_states": 3,
                "_job_dir": new_dir()})
    check("the excited-state optimization converges (HURRAY) and records the target state",
          r["summary"]["converged"] and r["summary"]["target_state"] == 1, str(r["summary"]))

    print("\n== ORCA opt/ci (live, twisted ethylene S0/S1 -- the real correction this phase makes) ==")
    r = orca_runner.run_geometry_optimization(
        ETHYLENE, {"method": "hf", "basis": "sto-3g", "optimization_type": "conical_intersection",
                   "target_state_2": 1, "n_states": 2, "max_steps": 300, "_job_dir": new_dir()})
    check("HF/CIS CI-OPT converges to a near-degenerate S0/S1 crossing",
          r["summary"]["converged"] and abs(r["summary"]["ci_energy_diff_hartree"]) < 1e-3, str(r["summary"]))

    r = orca_runner.run_geometry_optimization(
        ETHYLENE, {"method": "dft", "functional": "pbe0", "basis": "sto-3g",
                   "optimization_type": "conical_intersection", "target_state_2": 1, "n_states": 2,
                   "max_steps": 300, "_job_dir": new_dir()})
    check("PBE0/TDDFT CI-OPT converges to a near-degenerate S0/S1 crossing",
          r["summary"]["converged"] and abs(r["summary"]["ci_energy_diff_hartree"]) < 1e-3, str(r["summary"]))

    print("\n== BAGEL opt/ci (live, regression -- pre-existing mechanism, unchanged this phase) ==")
    r = bagel_runner.run_geometry_optimization(
        WATER, {"method": "casscf", "basis": "svp", **CAS, "n_states": 2,
                "optimization_type": "conical_intersection", "target_state": 0, "target_state_2": 1,
                "max_steps": 100, "_job_dir": new_dir()})
    check("bagel gradient-projection MECP still runs and records optimization_type",
          r["summary"]["optimization_type"] == "conical_intersection", str(r["summary"]))

    print("\n== ORCA opt_freq single-input (live, hf -- one process, not two) ==")
    r = orca_runner.run_opt_freq(WATER, {"method": "hf", "basis": "sto-3g", "_job_dir": new_dir()})
    s = r["summary"]
    check("real, nonzero vibrational frequencies come back",
          len([f for f in s["frequencies_cm-1"] if abs(f) > 50]) == 3, str(s.get("frequencies_cm-1")))
    check("the optimization and frequency stages agree on the energy (same combined run)",
          abs(s["optimization_final_energy_hartree"] - s["electronic_energy_hartree"]) < 1e-6, str(s))
    check("optimized_geometry is populated", bool(s.get("optimized_geometry")))

    print("\n== ORCA opt_freq single-input (live, casscf -- Opt NumFreq keyword) ==")
    r = orca_runner.run_opt_freq(
        WATER, {"method": "casscf", "basis": "sto-3g", **CAS, "n_states": 1, "_job_dir": new_dir()})
    s = r["summary"]
    check("casscf opt_freq produces real frequencies too",
          len([f for f in s["frequencies_cm-1"] if abs(f) > 50]) == 3, str(s.get("frequencies_cm-1")))

    print("\n== BAGEL opt_freq single-input (live, casscf -- optimize+hessian, one process) ==")
    r = bagel_runner.run_opt_freq(
        WATER, {"method": "casscf", "basis": "svp", **CAS, "n_states": 1, "max_steps": 100, "_job_dir": new_dir()})
    s = r["summary"]
    check("real, nonzero vibrational frequencies come back",
          len([f for f in s["frequencies_cm-1"] if abs(f) > 50]) == 3, str(s.get("frequencies_cm-1")))
    check("the optimization and frequency stages agree on the energy (same combined run)",
          abs(s["optimization_final_energy_hartree"] - s["state_energies_hartree"][0]) < 1e-6, str(s))

    print("\n== BAGEL opt_freq single-input (live, caspt2 -- the smith_block fix this found) ==")
    r_casscf_energy = s["optimization_final_energy_hartree"]
    r = bagel_runner.run_opt_freq(
        WATER, {"method": "caspt2", "basis": "svp", **CAS, "n_states": 1, "max_steps": 100, "_job_dir": new_dir()})
    s2 = r["summary"]
    check("caspt2 opt_freq reports method='caspt2', not a silently-substituted casscf",
          s2["method"] == "caspt2", str(s2.get("method")))
    check("caspt2's energy is genuinely different from casscf's on the same system (lower, dynamic correlation)",
          s2["optimization_final_energy_hartree"] < r_casscf_energy - 0.01,
          f"caspt2={s2['optimization_final_energy_hartree']} casscf={r_casscf_energy}")
    check("caspt2's frequencies are genuinely different from casscf's (not the silent-substitution bug)",
          s2["frequencies_cm-1"] != s["frequencies_cm-1"], str(s2.get("frequencies_cm-1")))

    print(f"\n{PASS}/{PASS + FAIL} checks passed")
    if FAIL:
        print("[FAIL] some checks failed")
        return 1
    print("[PASS] ALL CHECKS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
