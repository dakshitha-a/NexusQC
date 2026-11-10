"""A job drafted after a converged optimisation runs on the optimised geometry.

Found on 2026-11-09 while taking the thesis screenshots: furan was optimised
at B3LYP/def2-SVP, the agent then drafted a frequency job, and the card's
coordinates were the PubChem input, not the optimised ones. Nothing moves the
active molecule when an optimisation finishes, so every follow-up silently
ran on the starting structure. start_job_draft now defaults
source_geometry_job_id to the conversation's most recent converged
minimisation whose input is exactly the structure on screen, and the draft
says so.

In-process, no stack and no model. Writes two fixture jobs (real spec,
status and result files) and deletes them by id at the end:

    PYTHONPATH=$PWD python3 tests/backend/draft_06_followup_geometry.py
"""
from __future__ import annotations

import copy
import json
import shutil
import sys
import uuid

from app.agent.tools import start_job_draft, update_job_draft
from app.chemistry.jobs.base import JobResult, JobSpec, write_result, write_status
from app.chemistry.registry2.params import DEFAULTED_KEY
from app.config import JOBS_DIR

PASS = FAIL = 0
CREATED: list[JobSpec] = []


def check(label: str, ok: bool, detail: str = "") -> None:
    global PASS, FAIL
    PASS += ok
    FAIL += not ok
    print(f"  [{'PASS' if ok else 'FAIL'}] {label}" + ("" if ok or not detail else f"\n         {detail}"))


START = {"name": "water", "symbols": ["O", "H", "H"], "charge": 0, "multiplicity": 1,
         "coords": [[0.0, 0.0, 0.0], [0.0, 0.0, 0.96], [0.93, 0.0, -0.24]]}
OPTIMISED = {**START, "coords": [[0.0, 0.0, 0.1], [0.0, 0.75, -0.45], [0.0, -0.75, -0.45]]}


def opt_fixture(converged: bool) -> str:
    job_id = uuid.uuid4().hex[:12]
    spec = JobSpec(task="opt", subtype="min", method="hf", engine="pyscf", molecule=START,
                   params={"basis": "sto-3g"}, job_id=job_id)
    spec.job_dir().mkdir(parents=True, exist_ok=True)
    (spec.job_dir() / "spec.json").write_text(json.dumps(spec.to_dict(), indent=2))
    write_status(job_id, "completed", "fixture")
    write_result(JobResult(job_id, "completed", summary={
        "converged": converged, "optimized_geometry": OPTIMISED, "energy": -74.96,
    }, artifacts={}))
    CREATED.append(spec)
    return job_id


def draft(state: dict, task: str = "frequencies") -> dict:
    up = start_job_draft.func(task=task, method="hf", preview_only=True, state=state,
                              tool_call_id="t").update
    return up


def main() -> int:
    try:
        good = opt_fixture(converged=True)
        state = {"molecule": copy.deepcopy(START), "messages": [], "active_job_ids": [good]}

        print("== a follow-up on the opt's own input takes the optimised geometry ==")
        up = draft(state)
        d = up.get("job_draft") or {}
        check("source_geometry_job_id is the opt", (d.get("params") or {}).get("source_geometry_job_id") == good, str(d))
        check("and it is labelled a default", "source_geometry_job_id" in (d.get(DEFAULTED_KEY) or []), str(d))
        msg = up["messages"][0].content
        check("the reply names the job and the way out",
              f"optimised geometry from job {good}" in msg and "clear source_geometry_job_id" in msg, msg[:400])

        print("\n== clearing it sticks ==")
        up2 = update_job_draft.func(updates={"source_geometry_job_id": None, "basis": "sto-3g"},
                                    preview_only=True, state={**state, "job_draft": d},
                                    tool_call_id="t").update
        d2 = up2.get("job_draft") or {}
        check("no source job after the user clears it",
              not (d2.get("params") or {}).get("source_geometry_job_id"), str(d2))

        print("\n== a structure changed since is left alone ==")
        moved = copy.deepcopy(START)
        moved["coords"][1][2] = 1.10
        d3 = draft({**state, "molecule": moved}).get("job_draft") or {}
        check("no default on an edited structure", not (d3.get("params") or {}).get("source_geometry_job_id"), str(d3))

        print("\n== an unconverged optimisation is not a minimum ==")
        bad = opt_fixture(converged=False)
        d4 = draft({**state, "active_job_ids": [bad]}).get("job_draft") or {}
        check("no default from an unconverged opt", not (d4.get("params") or {}).get("source_geometry_job_id"), str(d4))

        print("\n== an ensemble takes its geometry from a frequency job, not this ==")
        d5 = draft(state, task="nuclear ensemble spectrum").get("job_draft") or {}
        check("no default on wigner_spectra", not (d5.get("params") or {}).get("source_geometry_job_id"), str(d5))
    finally:
        for spec in CREATED:
            shutil.rmtree(spec.job_dir(), ignore_errors=True)
        # Not spec.job_dir(): that creates the directory it names.
        check("fixture jobs deleted", all(not (JOBS_DIR / s.job_id).exists() for s in CREATED))

    print(f"\n{PASS}/{PASS + FAIL} checks passed")
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
