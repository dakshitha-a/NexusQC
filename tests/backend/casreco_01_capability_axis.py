#!/usr/bin/env python3
"""A capability question asked on the wrong axis, and one asked without a
method, both get real answers instead of dead ends.

Both failures were found in one real conversation (thread
823202f316ba46a2b000a076bd3b892e). Asked whether this app had an
active-space recommendation tool, the agent said no -- and `cas_reco` had
been shipped for weeks. Two independent causes, both checked here:

1. `avas` and `autocas` are SUBTYPES of cas_reco, not levels of theory. A
   model that writes method="avas" used to get "not a method this app
   runs. Closest matches: none", which is a flat no about a feature that
   exists. `method_is_really_a_task` moves the word to the axis it belongs
   on, in `lookup_capabilities` and in draft elicitation alike.

2. `capability_answer(task, subtype)` with no method used to report
   `supported: false` with the reason "No engine in this deployment can run
   a cas_reco/autocas job", while its own per_engine block said the real
   problem was the missing method. `supports()` refuses a None method by
   design (tasks.py), so `engines_supporting` found nothing. A missing
   method is missing information, not a refusal.

Pure registry/elicitation functions -- no live stack needed.

Run:  PYTHONPATH=$PWD python3 tests/backend/casreco_01_capability_axis.py
"""
from __future__ import annotations

import json
import sys

from app.chemistry.registry2.elicitation import validate_draft
from app.chemistry.registry2.lookup import capability_answer, method_is_really_a_task
from app.chemistry.registry2.tasks import TASKS

PASS = 0
FAIL = 0

WATER = {
    "name": "water", "symbols": ["O", "H", "H"],
    "coords": [[0, 0, 0.117], [0, 0.757, -0.469], [0, -0.757, -0.469]],
    "charge": 0, "multiplicity": 1,
}


def check(label: str, ok: bool, detail: str = "") -> None:
    global PASS, FAIL
    if ok:
        PASS += 1
        print(f"  [PASS] {label}")
    else:
        FAIL += 1
        print(f"  [FAIL] {label}" + (f"\n         {detail}" if detail else ""))


def run_axis() -> None:
    print("\n== a subtype offered as a method is moved, not refused ==")
    # Both names now route to the one cas_reco task. They are kept as synonyms
    # because they are what users and the model learned to say, but there is no
    # longer a subtype for them to select: the rebuilt engine always does both
    # the geometric projection and the entropy ranking that used to distinguish
    # them.
    for word in ("avas", "autocas"):
        check(f"'{word}' is still recognized, and routes to cas_reco",
              method_is_really_a_task(word) == ("cas_reco", ""),
              f"got {method_is_really_a_task(word)!r}")

    # The guard that keeps this narrow: a real method must never be
    # reinterpreted as a task, however it fuzzy-matches.
    for word in ("casscf", "b3lyp", "dft", "ccsd", "caspt2"):
        check(f"'{word}' stays a method", method_is_really_a_task(word) is None,
              f"got {method_is_really_a_task(word)!r}")


def run_no_method() -> None:
    print("\n== a task asked about without a method answers about the task ==")
    # cas_reco has one subtype now, not the autocas/avas pair. The old names
    # still resolve to it as synonyms, but the TaskDef itself is keyed on the
    # empty subtype.
    a = capability_answer("cas_reco", "")
    check("cas_reco is reported as supported", a["supported"] is True,
          json.dumps(a)[:300])
    check("...on pyscf", a.get("engines") == ["pyscf"], repr(a.get("engines")))
    check("...flagged as still needing a method", a.get("needs_method") is True)
    check("...naming casscf as the method", a.get("methods") == ["casscf"],
          repr(a.get("methods")))
    check("...and the reason does not claim no engine can run it",
          "No engine" not in a["reason"], a["reason"])

    # The bug was general, not cas_reco-specific: every task refused when
    # asked without a method. Nothing in the registry should now.
    print("\n== no task answers 'nothing can run this' merely for lack of a method ==")
    for (task, subtype) in TASKS:
        ans = capability_answer(task, subtype)
        name = f"{task}/{subtype}" if subtype else task
        check(f"{name} is answerable without a method", ans["supported"] is True,
              f"reason: {ans.get('reason')}")

    print("\n== naming the method still narrows to a routed answer ==")
    b = capability_answer("cas_reco", "", "casscf")
    check("a method-qualified answer is unchanged in shape",
          b["supported"] is True and b.get("needs_method") is None
          and b.get("recommended_engine") == "pyscf",
          json.dumps(b)[:300])


def run_elicitation() -> None:
    print("\n== a draft carrying a subtype in its method field is rerouted ==")
    state = {"molecule": WATER}
    v = validate_draft({"task": "cas_reco", "subtype": "", "method": "autocas"},
                       state, check_external=False)
    check("the draft is not stalled on 'which method did you mean'",
          v.asking_for != "method", f"asking_for={v.asking_for}")
    # It no longer asks for the basis: the recommendation does not depend on
    # one, so that question was retired. The state count is what it needs.
    check("...it asks how many states instead", v.asking_for == "n_excited_states",
          f"asking_for={v.asking_for}")
    check("...and says how the word was read",
          any("not a level of theory" in n for n in v.notes), repr(v.notes))

    v2 = validate_draft({"task": "cas_reco", "method": "avas"}, state,
                        check_external=False)
    check("method='avas' routes to cas_reco rather than being taken as a "
          "level of theory",
          v2.draft["task"] == "cas_reco" and v2.draft["subtype"] == "",
          f"task={v2.draft.get('task')!r} subtype={v2.draft.get('subtype')!r}")

    print("\n== a single-method task does not ask which method ==")
    v3 = validate_draft({"task": "active space recommendation"}, state,
                        check_external=False)
    check("cas_reco adopts casscf without asking", v3.asking_for != "method",
          f"asking_for={v3.asking_for}")
    check("...and records that it did",
          any("only runs at casscf" in n for n in v3.notes), repr(v3.notes))

    print("\n== a genuinely unknown method is still queried, never guessed ==")
    v4 = validate_draft({"task": "single_point", "subtype": "gs", "method": "bogusdft"},
                        state, check_external=False)
    check("an unknown method still asks", v4.asking_for == "method",
          f"asking_for={v4.asking_for}")


def main() -> int:
    run_axis()
    run_no_method()
    run_elicitation()
    total = PASS + FAIL
    print(f"\n{PASS}/{total} checks passed")
    if FAIL:
        print(f"[FAIL] {FAIL} check(s) failed")
        return 1
    print("[PASS] ALL CHECKS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
