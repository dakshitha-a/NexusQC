"""A targeted excited state brings enough states with it.

Found on 2026-11-10 while checking e2e_21's BAGEL conical-intersection case,
which stopped on "how many excited states?" 2 of 3 times although the user
had said "between S0 and S1". Looking at why, a worse case turned up: a
CASSCF optimisation drafted with target_state=1 and no count reached the
runner single-state, and the runner follows target_state only when there is
more than one state, so a user asking for S1 got the ground state.

The count now defaults to the highest targeted state, is marked as a default,
and the draft says so; a count the user gave is kept.

In-process, no stack and no model needed:

    PYTHONPATH=$PWD python3 tests/backend/draft_09_target_state_count.py
"""
from __future__ import annotations

import sys

from app.chemistry.registry2.elicitation import validate_draft
from app.chemistry.registry2.params import DEFAULTED_KEY

PASS = FAIL = 0


def check(label: str, ok: bool, detail: str = "") -> None:
    global PASS, FAIL
    PASS += ok
    FAIL += not ok
    print(f"  [{'PASS' if ok else 'FAIL'}] {label}" + ("" if ok or not detail else f"\n         {detail}"))


ETHYLENE = {"name": "ethylene", "symbols": ["C", "C", "H", "H", "H", "H"], "charge": 0,
            "multiplicity": 1,
            "coords": [[0, 0, 0.667], [0, 0, -0.667], [0, 0.923, 1.237], [0, -0.923, 1.237],
                       [0, 0.923, -1.237], [0, -0.923, -1.237]]}
CAS = {"basis": "sto-3g", "active_electrons": 2, "active_orbitals": 2}


def run(task: str, engine: str, method: str = "casscf", **params):
    return validate_draft({"task": task, "method": method, "engine": engine,
                           "params": {**CAS, **params}}, {"molecule": ETHYLENE})


def main() -> int:
    print("== a conical intersection between S0 and S1 needs no question ==")
    v = run("conical intersection", "bagel", target_state=0, target_state_2=1)
    p = v.draft["params"]
    check("ready, not asking for a state count", v.status == "ready", f"{v.status} {v.asking_for}")
    check("one excited state, two CASSCF roots", (p.get("n_excited_states"), p.get("n_states")) == (1, 2), str(p))
    check("marked as a default", "n_excited_states" in (v.draft.get(DEFAULTED_KEY) or []), str(v.draft))
    check("and the draft says so", any("excited state(s)" in n for n in v.notes), str(v.notes))

    print("\n== an S1 optimisation is really on S1 ==")
    for engine in ("pyscf", "orca", "bagel"):
        p = run("geometry optimization", engine, target_state=1).draft["params"]
        check(f"{engine}: two roots, so the runner follows state 1", p.get("n_states") == 2, str(p))

    print("\n== the higher of two targets wins, and a TDDFT target works the same way ==")
    p = run("conical intersection", "bagel", target_state=1, target_state_2=2).draft["params"]
    check("S1/S2: two excited states", p.get("n_excited_states") == 2, str(p))
    v = validate_draft({"task": "geometry optimization", "method": "dft", "engine": "pyscf",
                        "params": {"basis": "sto-3g", "functional": "b3lyp", "target_state": 1}},
                       {"molecule": ETHYLENE})
    check("TDDFT S1 optimisation: one excited state", v.draft["params"].get("n_excited_states") == 1,
          str(v.draft["params"]))

    print("\n== nothing changes where nothing is targeted, or the user gave a count ==")
    p = run("conical intersection", "bagel", target_state=0, target_state_2=1, n_excited_states=3).draft["params"]
    check("a count the user gave is kept", p.get("n_excited_states") == 3, str(p))
    p = run("geometry optimization", "pyscf", target_state=0).draft["params"]
    check("a ground-state target adds no count", "n_excited_states" not in p, str(p))
    p = run("geometry optimization", "pyscf").draft["params"]
    check("no target adds no count", "n_excited_states" not in p, str(p))

    print(f"\n{PASS}/{PASS + FAIL} checks passed")
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
