"""A molecule written into a draft that already has one does not stall it.

Found on 2026-11-10 while retaking the thesis screenshots: asked for a water
HF/STO-3G single point, the model wrote {"molecule": "water"} with
update_job_draft. The refusal ("call set_geometry instead") returned before
the draft was re-checked, so after set_geometry the model still believed the
molecule question was open and wrote the key again, about 170 times in one
turn. With a molecule already set the key is now dropped and the draft goes
on to its real next step; with none set it is still refused.

In-process, no stack and no model needed:

    PYTHONPATH=$PWD python3 tests/backend/draft_07_redundant_molecule.py
"""
from __future__ import annotations

import sys

from app.agent.tools import update_job_draft

PASS = FAIL = 0


def check(label: str, ok: bool, detail: str = "") -> None:
    global PASS, FAIL
    PASS += ok
    FAIL += not ok
    print(f"  [{'PASS' if ok else 'FAIL'}] {label}" + ("" if ok or not detail else f"\n         {detail}"))


WATER = {"name": "water", "symbols": ["O", "H", "H"], "charge": 0, "multiplicity": 1,
         "coords": [[0.0, 0.0, 0.0], [0.0, 0.0, 0.96], [0.93, 0.0, -0.24]]}
DRAFT = {"task": "single_point", "subtype": "gs", "method": "hf", "engine": "pyscf", "params": {}}


def run(state: dict, updates: dict) -> dict:
    return update_job_draft.func(updates=updates, preview_only=True, state=state,
                                 tool_call_id="t").update


def main() -> int:
    print("== a molecule is already set: the key is dropped and the draft moves on ==")
    up = run({"molecule": WATER, "messages": [], "job_draft": dict(DRAFT)},
             {"molecule": "water", "basis": "sto-3g"})
    msg = up["messages"][0].content
    check("not refused", "not a job parameter" not in msg, msg[:300])
    d = up.get("job_draft") or {}
    check("the basis in the same call is recorded", (d.get("params") or {}).get("basis") == "sto-3g", str(d))
    check("molecule did not become a parameter", "molecule" not in (d.get("params") or {}), str(d))

    print("\n== no molecule yet: still refused, pointing at set_geometry ==")
    up = run({"messages": [], "job_draft": dict(DRAFT)}, {"molecule": "water"})
    msg = up["messages"][0].content
    check("refused with the set_geometry route", "set_geometry" in msg and "not a job parameter" in msg, msg[:300])

    print("\n== an end geometry written as a parameter is still refused ==")
    up = run({"molecule": WATER, "messages": [], "job_draft": dict(DRAFT)}, {"_end_molecule": "water"})
    check("_end_molecule is not silently absorbed",
          "job_draft" not in up or "_end_molecule" not in str((up.get("job_draft") or {}).get("params")),
          str(up)[:300])

    print(f"\n{PASS}/{PASS + FAIL} checks passed")
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
