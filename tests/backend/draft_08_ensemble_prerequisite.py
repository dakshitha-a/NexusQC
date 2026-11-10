"""An ensemble asked for with no frequency job drafts the frequency job.

Found on 2026-11-10 by e2e_21: "Compute a nuclear ensemble absorption
spectrum for water ... I already know it needs a frequency job first" carded
0 of 3. The draft asked "attach a frequency job, or say so and I'll set one
up", which is the right question when one might exist and a wasted round trip
when none does. The user decided that, with no finished frequency job on the
molecule, the agent drafts the prerequisite instead. It still goes to an
approval card. With no minimum on record that is an optimisation followed by
frequencies, because frequencies off a minimum give wrong normal modes.

In-process, no stack and no model. Writes fixture jobs (real spec, status and
result files) and deletes them by id at the end:

    PYTHONPATH=$PWD python3 tests/backend/draft_08_ensemble_prerequisite.py
"""
from __future__ import annotations

import copy
import json
import shutil
import sys
import uuid

from app.agent.tools import start_job_draft
from app.chemistry.jobs.base import JobResult, JobSpec, write_result, write_status
from app.config import JOBS_DIR

PASS = FAIL = 0
CREATED: list[JobSpec] = []


def check(label: str, ok: bool, detail: str = "") -> None:
    global PASS, FAIL
    PASS += ok
    FAIL += not ok
    print(f"  [{'PASS' if ok else 'FAIL'}] {label}" + ("" if ok or not detail else f"\n         {detail}"))


WATER = {"name": "water", "symbols": ["O", "H", "H"], "charge": 0, "multiplicity": 1,
         "coords": [[0.0, 0.0, 0.117], [0.0, 0.757, -0.467], [0.0, -0.757, -0.467]]}
AMMONIA = {"name": "ammonia", "symbols": ["N", "H", "H", "H"], "charge": 0, "multiplicity": 1,
           "coords": [[0, 0, 0.1], [0, 0.94, -0.27], [0.81, -0.47, -0.27], [-0.81, -0.47, -0.27]]}


def fixture(task: str, subtype: str, molecule: dict, summary: dict) -> str:
    job_id = uuid.uuid4().hex[:12]
    spec = JobSpec(task=task, subtype=subtype, method="hf", engine="pyscf", molecule=molecule,
                   params={"basis": "sto-3g"}, job_id=job_id)
    spec.job_dir().mkdir(parents=True, exist_ok=True)
    (spec.job_dir() / "spec.json").write_text(json.dumps(spec.to_dict(), indent=2))
    write_status(job_id, "completed", "fixture")
    write_result(JobResult(job_id, "completed", summary=summary, artifacts={}))
    CREATED.append(spec)
    return job_id


def ask(state: dict) -> str:
    up = start_job_draft.func(task="nuclear ensemble spectrum", method="hf", engine="pyscf",
                              preview_only=True, state=state, tool_call_id="t").update
    return up["messages"][0].content


def main() -> int:
    try:
        base = {"molecule": copy.deepcopy(WATER), "messages": [], "active_job_ids": []}

        print("== no frequency job anywhere: draft optimisation plus frequencies ==")
        msg = ask(base)
        check("told to draft the prerequisite", "PREREQUISITE NEEDED" in msg, msg[:300])
        check("as opt_freq, because there is no minimum", 'task="opt_freq"' in msg, msg[:500])
        check("not told to ask the user", "Do not ask the user" in msg, msg[:300])

        print("\n== nothing on screen and no frequency job: set the structure, then draft ==")
        msg = ask({"messages": [], "active_job_ids": []})
        check("drafts the prerequisite with no molecule on screen", "PREREQUISITE NEEDED" in msg, msg[:300])
        check("and says to set the structure first", "set_geometry" in msg, msg[:500])

        print("\n== a finished frequency job on the same molecule: ask as before ==")
        freq = fixture("freq", "", WATER, {"frequencies_cm-1": [1700.0, 3800.0, 3900.0]})
        msg = ask({**base, "active_job_ids": [freq]})
        check("the usual question", "PREREQUISITE" not in msg and "Attach to prompt" in msg, msg[:300])

        msg = ask({"messages": [], "active_job_ids": [freq]})
        check("nothing on screen but a frequency job exists: ask which", "PREREQUISITE" not in msg, msg[:300])

        print("\n== a frequency job on another molecule does not count ==")
        other = fixture("freq", "", AMMONIA, {"frequencies_cm-1": [1000.0]})
        msg = ask({**base, "active_job_ids": [other]})
        check("still drafts the prerequisite", "PREREQUISITE NEEDED" in msg, msg[:300])

        print("\n== a converged optimisation of this structure: frequencies on it ==")
        opt = fixture("opt", "min", WATER, {"converged": True, "optimized_geometry": WATER,
                                            "energy": -74.96})
        msg = ask({**base, "active_job_ids": [other, opt]})
        check("drafts frequencies, not another optimisation", 'task="frequencies"' in msg, msg[:500])
    finally:
        for spec in CREATED:
            shutil.rmtree(spec.job_dir(), ignore_errors=True)
        check("fixture jobs deleted", all(not (JOBS_DIR / s.job_id).exists() for s in CREATED))

    print(f"\n{PASS}/{PASS + FAIL} checks passed")
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
