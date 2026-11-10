"""A declined draft can be amended, replaced or dropped, and never leaks.

Found on 2026-11-09 while taking the thesis screenshots: after a Reject,
every later request, even one for a different task, was applied with
update_job_draft to the declined single point, and "Drop that draft." called
start_job_draft and rebuilt it. Now the rejection marks the draft declined;
an update that changes its task starts clean; discard_job_draft drops it;
and the mark never becomes a job parameter.

In-process, no stack and no model needed:

    PYTHONPATH=$PWD python3 tests/backend/draft_05_declined_drafts.py
"""
from __future__ import annotations

import sys

from app.agent.state import CLEAR_DRAFT, DECLINED_KEY
from app.agent.tools import discard_job_draft, update_job_draft
from app.chemistry.molecule import resolve_molecule
from app.chemistry.registry2.elicitation import normalize_draft

PASS = FAIL = 0


def check(label: str, ok: bool, detail: str = "") -> None:
    global PASS, FAIL
    PASS += ok
    FAIL += not ok
    print(f"  [{'PASS' if ok else 'FAIL'}] {label}" + ("" if ok or not detail else f"\n         {detail}"))


WATER = resolve_molecule("water").to_dict()
DECLINED = {"task": "single_point", "subtype": "gs", "method": "hf", "engine": None,
            "params": {"basis": "sto-3g"}, DECLINED_KEY: True}


def run(tool, **kw):
    return tool.func(state={"molecule": WATER, "messages": [], "job_draft": dict(DECLINED)},
                     tool_call_id="t", **kw).update


def main() -> int:
    print("== an amendment keeps the declined draft's parameters ==")
    up = run(update_job_draft, updates={"method": "dft", "functional": "pbe0"}, preview_only=True)
    d = up.get("job_draft") or {}
    check("same task", d.get("task") == "single_point", str(d))
    check("basis carried over", (d.get("params") or {}).get("basis") == "sto-3g", str(d))
    check("the declined mark is gone", DECLINED_KEY not in d and DECLINED_KEY not in (d.get("params") or {}), str(d))

    print("\n== a different task starts clean ==")
    up = run(update_job_draft, updates={"task": "freq"}, preview_only=True)
    d = up.get("job_draft") or {}
    check("the task is the new one", d.get("task") == "freq", str(d))
    check("the declined basis did not ride along", "basis" not in (d.get("params") or {}), str(d))

    print("\n== discard drops it ==")
    up = run(discard_job_draft)
    check("job_draft is cleared", up.get("job_draft") == CLEAR_DRAFT, str(up.get("job_draft")))
    check("the reply says nothing ran", "Nothing was run" in up["messages"][0].content, up["messages"][0].content)

    print("\n== the mark is never a parameter ==")
    n = normalize_draft(dict(DECLINED))
    check("normalize_draft drops it", DECLINED_KEY not in n["params"], str(n["params"]))

    print(f"\n{PASS}/{PASS + FAIL} checks passed")
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
