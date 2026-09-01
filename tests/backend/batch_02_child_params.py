#!/usr/bin/env python3
"""A batch draft must ACCEPT the child parameters it ASKS for.

These are two different code paths and only one of them was checked when
batch's child tasks were widened. `validate_draft` decides what to ask;
`update_job_draft` decides what may be written. Testing the first by
poking values straight into the draft dict passes happily while the second
refuses every one of them, which is exactly what shipped: a real session
was asked "How many electrons should the active space contain?" and then
told active_electrons "is not a parameter of batch". The user reasonably
concluded a batch could not express a CASSCF calculation at all and went
back to submitting one job per geometry by hand.

So this script drives BOTH halves, and asserts they agree: every
parameter elicitation asks for must be one update_job_draft accepts, for
every child task a batch can run.

Run:  PYTHONPATH=$PWD python3 tests/backend/batch_02_child_params.py
"""
from __future__ import annotations

import sys

from app.agent.tools import _draft_param_names, _param_applies, _unknown_param_message
from app.chemistry.registry2.elicitation import validate_draft
from app.chemistry.registry2.tasks import BATCH_CHILD_TASKS

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


WATER = {"name": "water", "symbols": ["O", "H", "H"],
         "coords": [[0.0, 0.0, 0.117], [0.0, 0.757, -0.467], [0.0, -0.757, -0.467]],
         "charge": 0, "multiplicity": 1}

# Answers a user would give, for whichever of these each child task asks.
ANSWERS = {
    "basis": "cc-pvdz", "child_task": None, "active_electrons": 2,
    "active_orbitals": 2, "n_excited_states": 2, "state_pairs": [[1, 2]],
    "target_state": 1, "target_state_2": 2, "n_samples": 5,
    "constraints": [{"type": "dihedral", "atoms": [1, 2, 3, 1]}],
}


def main() -> int:
    print("== every parameter a batch ASKS for is one it ACCEPTS ==")
    state = {"molecule": WATER, "molecule_frames": []}
    for child in sorted(BATCH_CHILD_TASKS):
        draft = {"task": "batch", "subtype": "", "method": "casscf", "engine": "pyscf",
                 "params": {"source_job_id": "somejob", "child_task": child}}
        asked, refused = [], []
        for _ in range(15):
            verdict = validate_draft(draft, state, check_external=False)
            if verdict.status != "incomplete":
                break
            key = verdict.asking_for
            if key is None or key not in ANSWERS or ANSWERS[key] is None:
                break
            asked.append(key)
            # The question was asked. Would the tool let the answer be written?
            if not _param_applies(draft, key, {key: ANSWERS[key]}):
                refused.append(key)
            draft["params"][key] = ANSWERS[key]
        check(f"{child}: every asked parameter is writable", not refused,
              f"asked {asked}, refused {refused}")

    print("\n== child parameters are accepted for each child task ==")
    expected = {
        "nac": ["active_electrons", "active_orbitals", "n_excited_states", "state_pairs"],
        "excited_states": ["active_electrons", "n_excited_states"],
        "gradient": ["active_electrons", "target_states"],
        "opt_ci": ["target_state", "target_state_2"],
        "opt_constrained": ["constraints"],
        "single_point": ["active_electrons", "active_orbitals"],
    }
    for child, keys in expected.items():
        draft = {"task": "batch", "subtype": "",
                 "params": {"child_task": child, "source_job_id": "somejob"}}
        missing = [k for k in keys if not _param_applies(draft, k)]
        check(f"{child} accepts {', '.join(keys)}", not missing, f"refused {missing}")

    print("\n== child_task in the SAME update licenses the child's parameters ==")
    # The model writes the whole draft in one call, and update_job_draft
    # applies an update atomically -- so a check that reads child_task only
    # from the stored params rejects the entire call for keys that the very
    # same call makes valid.
    empty = {"task": "batch", "subtype": "", "params": {}}
    combined = {"child_task": "nac", "basis": "cc-pvdz", "active_electrons": 2,
                "active_orbitals": 2, "n_excited_states": 2, "state_pairs": [[1, 2]]}
    rejected = [k for k in combined if not _param_applies(empty, k, combined)]
    check("a single call setting child_task and the whole active space is accepted",
          not rejected, f"refused {rejected}")

    print("\n== batch's own parameters still work, and nonsense is still refused ==")
    draft = {"task": "batch", "subtype": "", "params": {"child_task": "nac"}}
    for key in ("source_job_id", "child_task", "chain_orbitals", "basis"):
        check(f"batch's own '{key}' is accepted", _param_applies(draft, key))
    check("a parameter of no task is still refused",
          not _param_applies(draft, "coordinate"), "coordinate belongs to pes_1d")

    print("\n== the refusal message lists the set actually accepted ==")
    message = _unknown_param_message(draft, [], ["coordinate"])
    names = _draft_param_names(draft) or set()
    check("every field the message offers is one the draft accepts",
          all(n in names for n in message.split("This draft takes: ")[1].split(".")[0].split(", ")),
          message[:200])
    check("the message offers the child's parameters too",
          "active_electrons" in message and "state_pairs" in message, message[:200])

    print(f"\n{PASS}/{PASS + FAIL} checks passed")
    if FAIL:
        print("[FAIL] some checks failed")
        return 1
    print("[PASS] ALL CHECKS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
