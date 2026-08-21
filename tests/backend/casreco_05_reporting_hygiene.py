#!/usr/bin/env python3
"""Four small defects from the same conversation. None of them produces a
wrong scientific answer, which is why they are grouped and why they came
last -- but each one either misinforms or wastes a turn.

1. `job_type` reported the level of theory. summarize.py printed
   `job_type=spec["method"]`, so a pes_1d scan read back as "job_type=dft",
   an opt as "dft", a freq as "dft" and a cas_reco as "casscf" -- each
   contradicting what submit_draft had printed seconds earlier. The two
   axes have been separate since registry v2; this line had not caught up.

2. Unknown draft keys were absorbed. Anything not in _STATE_OWNED_FIELDS
   went straight into params, so a model that invented `constraint` for a
   PES scan put it in the submitted spec and on the approval card -- the
   exact harm the comment above that code says it is guarding against.

3. Every finished job was summarized twice: once by the agent polling to
   completion in its own turn, then again by the watcher's notice telling
   it to check the status and summarize.

4. A scan asked how many points to sample before asking what was being
   scanned.

Pure functions and a stubbed job manager; no live stack.

Run:  PYTHONPATH=$PWD python3 tests/backend/casreco_05_reporting_hygiene.py
"""
from __future__ import annotations

import sys

from app.agent import reported_jobs
from app.agent.tools import update_job_draft
from app.chemistry.registry2.params import missing_required

PASS = 0
FAIL = 0

ETHYLENE = {
    "name": "ethylene", "symbols": ["C", "C"], "coords": [[0, 0, 0], [0, 0, 1.33]],
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


def run_spec_line() -> None:
    print("\n== a job's own line names its task, not its method ==")
    import app.chemistry.jobs.summarize as sm

    real = sm.read_spec
    cases = [
        ({"task": "pes_1d", "subtype": "", "method": "dft", "engine": "pyscf", "params": {}},
         "task=pes_1d", "dft"),
        ({"task": "opt", "subtype": "min", "method": "dft", "engine": "pyscf", "params": {}},
         "task=opt/min", "dft"),
        ({"task": "cas_reco", "subtype": "autocas", "method": "casscf", "engine": "pyscf",
          "params": {}}, "task=cas_reco/autocas", "casscf"),
    ]
    try:
        for spec, expected_task, expected_method in cases:
            sm.read_spec = lambda _jid, _s=spec: _s
            line = sm._spec_line("job-1")
            check(f"{expected_task} is reported as the task", expected_task in line, line)
            check(f"...with method={expected_method} on its own axis",
                  f"method={expected_method}" in line, line)
            check("...and 'job_type' is gone entirely", "job_type" not in line, line)
    finally:
        sm.read_spec = real


def run_unknown_keys() -> None:
    print("\n== an invented parameter is refused, not absorbed ==")
    state = {"molecule": ETHYLENE,
             "job_draft": {"task": "pes_1d", "subtype": "", "method": "dft", "params": {}}}
    cmd = update_job_draft.func(
        updates={"basis": "cc-pvdz", "functional": "b3lyp",
                 "constraint": {"type": "dihedral", "atoms": [5, 2, 1, 3]}},
        state=state, tool_call_id="t")
    text = cmd.update["messages"][0].content
    check("the invented key is named", "constraint" in text, text[:200])
    check("...and identified as not being a parameter",
          "is not a parameter this app has" in text, text[:200])
    check("...with the draft's real parameters listed", "This draft takes:" in text,
          text[:300])
    check("nothing at all was recorded -- not even the valid keys alongside it",
          "job_draft" not in (cmd.update or {}),
          repr(list((cmd.update or {}).keys())))

    print("\n== a real parameter belonging to another task is refused too ==")
    cmd2 = update_job_draft.func(updates={"avas_aolabels": ["C 2p"]}, state=state,
                                 tool_call_id="t")
    text2 = cmd2.update["messages"][0].content
    check("a known-but-inapplicable key is caught",
          "is not a parameter of pes_1d" in text2, text2[:200])

    print("\n== valid keys still go in ==")
    cmd3 = update_job_draft.func(updates={"basis": "cc-pvdz", "functional": "b3lyp"},
                                 state=state, tool_call_id="t")
    check("an ordinary update is recorded", "job_draft" in (cmd3.update or {}),
          repr(list((cmd3.update or {}).keys())))
    check("...with both values",
          (cmd3.update.get("job_draft") or {}).get("params", {}).get("basis") == "cc-pvdz"
          and (cmd3.update["job_draft"]["params"]).get("functional") == "b3lyp",
          repr(cmd3.update.get("job_draft")))


def run_scan_order() -> None:
    print("\n== a scan is asked what it scans before how finely ==")
    order = [s.name for s in missing_required("pes_1d", "", "dft", "pyscf", {})]
    check("coordinate is asked before scan_range",
          order.index("coordinate") < order.index("scan_range"), repr(order))
    check("scan_range is asked before n_points",
          order.index("scan_range") < order.index("n_points"), repr(order))


def run_report_suppression() -> None:
    print("\n== a job the agent already reported is not re-announced ==")
    import app.agent.job_watcher as jw

    reported_jobs.forget("job-A")
    reported_jobs.forget("job-B")
    check("nothing is marked to begin with", not reported_jobs.was_reported("job-A"))
    reported_jobs.mark_reported("job-A")
    check("marking one records it", reported_jobs.was_reported("job-A"))
    check("...and does not record its neighbour", not reported_jobs.was_reported("job-B"))
    reported_jobs.forget("job-A")
    check("forgetting clears it", not reported_jobs.was_reported("job-A"))

    # The buckets that ask for something the agent has NOT already done must
    # keep firing regardless -- suppression is only ever about the plain
    # "go and summarize this" wording.
    notice = jw._agent_notice([], [], (), ["cas-1"])
    check("the active-space follow-up is not a summarize-this notice",
          "start_job_draft" in notice and "concise summary of the results" not in notice,
          notice[:200])
    ensemble = jw._agent_notice([], [], ["wig-1"], ())
    check("the ensemble branch likewise stands on its own",
          "plot(kind='ensemble'" in ensemble, ensemble[:200])


def main() -> int:
    run_spec_line()
    run_unknown_keys()
    run_scan_order()
    run_report_suppression()
    total = PASS + FAIL
    print(f"\n{PASS}/{total} checks passed")
    if FAIL:
        print(f"[FAIL] {FAIL} check(s) failed")
        return 1
    print("[PASS] ALL CHECKS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
