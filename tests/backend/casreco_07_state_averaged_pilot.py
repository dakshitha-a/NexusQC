#!/usr/bin/env python3
"""The entropy pilot can screen over several states, not just the ground
state -- and refuses cleanly where it cannot.

Single-orbital entropy measures ground-state static correlation. An orbital
that only matters once you excite out of it is invisible to it: a
doubly-occupied lone pair is weakly correlated in S0 and carries almost no
entanglement, however much the n->pi* states depend on it. On uracil/cc-pVDZ
this is not hypothetical -- both pilots, exact-FCI on a truncated pool and
DMRG on the full 29-orbital pool, recommended the same (8e,7o) of pure
pi/pi*, with the carbonyl lone pairs sitting in the pool unselected, while
the published spaces for the same molecule are larger and include them.

`entropy_pilot_states` averages the density matrices over that many roots
before computing the entropies. The definition is unchanged; only which
wavefunction it is evaluated on. Verified end to end on uracil: at 1 the
space is 7 orbitals with no n character, at 3 an n orbital on O8 enters it.
That run is minutes long, so what is checked here is the mechanism -- the
averaging itself, and the refusal -- on a system that takes seconds.

The DMRG backend cannot do this. block2 0.5.3 solves for several roots
happily and then **segfaults** inside get_orbital_entropies on the
multi-root MPS. A segfault takes the worker down, so no result is written
and the job never reaches a terminal status, which is the one job-lifecycle
failure this project treats as a real defect -- hence a refusal at
validation, before a draft can reach READY, rather than a runtime error.

Run:  PYTHONPATH=$PWD python3 tests/backend/casreco_07_state_averaged_pilot.py
"""
from __future__ import annotations

import sys

import numpy as np
from pyscf import gto, mcscf, scf

from app.chemistry.jobs.pyscf_runner import _single_orbital_entropies
from app.chemistry.registry2.elicitation import validate_draft

PASS = 0
FAIL = 0

STATE = {"molecule": {"name": "uracil", "symbols": ["O"], "coords": [[0, 0, 0]],
                      "charge": 0, "multiplicity": 1}}


def check(label: str, ok: bool, detail: str = "") -> None:
    global PASS, FAIL
    if ok:
        PASS += 1
        print(f"  [PASS] {label}")
    else:
        FAIL += 1
        print(f"  [FAIL] {label}" + (f"\n         {detail}" if detail else ""))


def _pilot(nroots: int):
    mol = gto.M(atom="O 0 0 0.117; H 0 0.757 -0.469; H 0 -0.757 -0.469",
                basis="sto-3g", verbose=0)
    mf = scf.RHF(mol)
    mf.kernel()
    mc = mcscf.CASCI(mf, 4, 4)
    if nroots > 1:
        mc.fcisolver.nroots = nroots
    mc.kernel()
    return _single_orbital_entropies(mc)


def run_averaging() -> None:
    print("\n== the averaging itself, on water/STO-3G CAS(4,4) ==")
    e1, o1 = _pilot(1)
    e3, o3 = _pilot(3)
    check("a single-root pilot still returns one entropy per orbital", len(e1) == 4,
          repr(e1))
    check("a three-root pilot returns the same shape", len(e3) == 4, repr(e3))
    check("electron count is preserved by the averaging",
          abs(sum(o3) - 4.0) < 1e-6, f"sum(occupations)={sum(o3)}")
    check("every entropy is non-negative", all(e >= 0 for e in e3), repr(e3))
    # The point of the exercise: averaging over excited roots changes the
    # ranking. If it did not, the parameter would buy nothing.
    check("state-averaged entropies differ from ground-state ones",
          not np.allclose(e1, e3, atol=1e-6), f"{e1} vs {e3}")
    check("...and are larger, the excited roots bringing real correlation",
          sum(e3) > sum(e1), f"sum {sum(e1):.4f} -> {sum(e3):.4f}")


def run_refusal() -> None:
    print("\n== DMRG cannot state-average, and says so before running ==")
    base = {"task": "cas_reco", "subtype": "autocas", "method": "casscf",
            "params": {"basis": "cc-pvdz", "n_excited_states": 2}}

    def verdict(**extra):
        d = {**base, "params": {**base["params"], **extra}}
        return validate_draft(d, STATE, check_external=False)

    v = verdict(entropy_pilot_states=3, entropy_method="dmrg")
    check("a state-averaged DMRG draft never reaches READY", v.status != "ready",
          v.status)
    check("...and asks which backend to use instead", v.asking_for == "entropy_method",
          v.asking_for)
    check("...explaining that only the exact-FCI pilot can do it",
          "exact-FCI" in (v.ask_user_exactly or ""), v.ask_user_exactly)

    check("state-averaged with the exact-FCI pilot is fine",
          verdict(entropy_pilot_states=3, entropy_method="exact_fci").status == "ready")
    check("DMRG screening the ground state alone is fine",
          verdict(entropy_method="dmrg").status == "ready")
    check("DMRG with an explicit single pilot state is fine",
          verdict(entropy_pilot_states=1, entropy_method="dmrg").status == "ready")


def run_optional_backend() -> None:
    """block2 is optional, and an install without it must say so rather than
    offering a screening backend it cannot run.

    It is a 379 MB MKL-linked wheel bought for a pool of 30 orbitals against
    exact FCI's 12, so it is not in requirements.txt -- see
    requirements-optional.txt and install.sh's prompt. The rule this checks
    is the same one the rest of this audit turns on: the registry may only
    offer what is actually here.
    """
    print("\n== an install without block2 declines DMRG instead of failing on it ==")
    import app.chemistry.registry2.elicitation as el

    base = {"task": "cas_reco", "subtype": "autocas", "method": "casscf",
            "params": {"basis": "cc-pvdz", "n_excited_states": 2}}

    def verdict(**extra):
        d = {**base, "params": {**base["params"], **extra}}
        return validate_draft(d, STATE, check_external=False)

    real = el.has_dmrg_backend
    el.has_dmrg_backend = lambda: False
    try:
        v = verdict(entropy_method="dmrg")
        check("a DMRG draft never reaches READY when block2 is absent",
              v.status != "ready", v.status)
        check("...and says the backend is not installed",
              "not installed" in (v.ask_user_exactly or ""), v.ask_user_exactly)
        check("...offering only the backend that is actually here",
              v.options == ("exact_fci",), repr(v.options))
        check("exact FCI is unaffected by block2 being absent",
              verdict(entropy_method="exact_fci").status == "ready")
        check("and so is a draft that never mentioned a backend",
              verdict().status == "ready")
    finally:
        el.has_dmrg_backend = real

    # With it present nothing changes -- the refusal must be conditional, not
    # a blanket removal of the option.
    el.has_dmrg_backend = lambda: True
    try:
        check("with block2 present the DMRG option works as before",
              verdict(entropy_method="dmrg").status == "ready")
    finally:
        el.has_dmrg_backend = real


def main() -> int:
    run_averaging()
    run_refusal()
    run_optional_backend()
    total = PASS + FAIL
    print(f"\n{PASS}/{total} checks passed")
    if FAIL:
        print(f"[FAIL] {FAIL} check(s) failed")
        return 1
    print("[PASS] ALL CHECKS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
