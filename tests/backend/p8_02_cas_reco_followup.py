#!/usr/bin/env python3
"""Phase 8 P8.2 -- a completed cas_reco/autocas or cas_reco/avas job is
followed by an auto-composed CASSCF-ee draft, per docs/TRACKER.md's P8.2
note: "the auto-composed CASSCF-ee draft always asks the user for its own
n_states and basis, never inherits them from the recommendation step".

Two things are tested, deliberately kept separate:

1. **The notice** (app/agent/job_watcher.py's `_agent_notice` and
   `_poll_once`'s classification) -- mechanical, no LLM, using the exact
   `jw.invoke_turn` monkeypatch tests/backend/fail_01_notice_flow.py
   already established for testing job_watcher without a live model.
2. **The mechanical backstop**: this project's own standing position is
   that a prompt-only rule gets violated (see docs/ARCHITECTURE.md's
   reasoning for why registry2/elicitation.py exists at all) -- so the
   notice's instruction not to set n_states/basis is not trusted on its
   own. Instead, the draft the notice describes is built directly and
   validate_draft is asked to check it: if the model ignored the notice's
   wording anyway (or a future edit reworded it into something weaker),
   elicitation.py still refuses to reach READY without n_states and
   basis, because ParamSpec's required_when for both is unconditional on
   how the draft got assembled.

The cas_reco job itself is a hand-built fixture (real spec.json/
status.json/result.json under its own job_id, same pattern
tests/backend/p7_04_batch_master.py's own _write_fixture_source_job
uses) rather than a live autocas run -- what's under test here is the
job_watcher/elicitation wiring, not autocas's own entropy-pilot chemistry
(P0.5/P2.1 already cover that).

Run:  PYTHONPATH=$PWD python3 tests/backend/p8_02_cas_reco_followup.py
"""
from __future__ import annotations

import json
import sys
import uuid

from app.agent import job_watcher as jw
from app.agent import threads as thread_registry
from app.chemistry.jobs.base import JobResult, JobSpec, write_result, write_status
from app.chemistry.molecule import resolve_molecule
from app.chemistry.registry2.elicitation import validate_draft

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


WATER = resolve_molecule("water").to_dict()


def _write_cas_reco_fixture(subtype: str) -> str:
    job_id = uuid.uuid4().hex[:12]
    spec = JobSpec(method="casscf", engine="pyscf", molecule=WATER,
                   task="cas_reco", subtype=subtype, job_id=job_id)
    (spec.job_dir() / "spec.json").write_text(json.dumps(spec.to_dict(), indent=2))
    write_status(job_id, "completed", "fixture")
    write_result(JobResult(job_id, "completed", summary={
        "recommended_active_electrons": 6, "recommended_active_orbitals": 6,
        "n_states": 1, "converged": True,
    }, artifacts={}))
    return job_id


def main() -> int:
    print("== _agent_notice: content, not just presence ==")
    notice = jw._agent_notice([], [], (), ["cas-job-1"])
    check("names start_job_draft with method=casscf, engine=pyscf",
          "start_job_draft(task='single_point', method='casscf', engine='pyscf')" in notice, notice)
    check("instructs subtype='ee'", "subtype='ee'" in notice, notice)
    check("points at the recommendation summary's own field names",
          "recommended_active_electrons" in notice and "recommended_active_orbitals" in notice, notice)
    check("instructs carrying initial_orbitals_job_id forward",
          "initial_orbitals_job_id" in notice, notice)
    check("explicitly forbids setting n_states", "do NOT set n_states" in notice, notice)
    check("explicitly forbids setting basis", "or basis" in notice, notice)

    # cas_reco/explain used to be checked here as the one subtype excluded
    # from the follow-up bucket. It is no longer a job at all -- it ran no
    # engine calculation and is the explain_active_space tool now -- so what
    # is worth holding is the general property it stood for: a job outside
    # the bucket gets the plain wording, with no auto-draft instruction.
    plain_notice = jw._agent_notice(["ordinary-job-1"], [], (), ())
    check("a job outside the follow-up bucket gets the plain completed-job wording",
          "Job(s) ordinary-job-1 finished" in plain_notice and "start_job_draft" not in plain_notice,
          plain_notice)

    print("\n== _poll_once: classification, end to end, no LLM ==")
    autocas_id = _write_cas_reco_fixture("autocas")
    thread = thread_registry.create_thread(label="qatest_cas_reco_followup")
    thread_id = thread["thread_id"]
    config = {"configurable": {"thread_id": thread_id}}
    thread_registry.set_active_job_ids(thread_id, [autocas_id])

    captured_notices: list[str] = []

    def _capturing_invoke_turn(state_update, cfg):
        content = state_update["messages"][0].content
        captured_notices.append(content)
        from langchain_core.messages import AIMessage
        return {"messages": [AIMessage(content="ok")], "active_job_ids": []}

    real_invoke_turn = jw.invoke_turn
    jw.invoke_turn = _capturing_invoke_turn
    try:
        watcher = jw.JobWatcher(on_event=lambda tid, ev: None)
        watcher._poll_once()
    finally:
        jw.invoke_turn = real_invoke_turn

    check("a completed cas_reco/autocas job triggers exactly one agent turn",
          len(captured_notices) == 1, str(captured_notices))
    check("...carrying the cas_reco-specific notice, not the generic 'finished' wording",
          bool(captured_notices) and "start_job_draft" in captured_notices[0],
          captured_notices[0] if captured_notices else "")
    check("...naming the actual completed job id",
          bool(captured_notices) and autocas_id in captured_notices[0],
          captured_notices[0] if captured_notices else "")
    thread_registry.delete_thread(thread_id)

    print("\n== _poll_once: cas_reco/avas DOES reach the follow-up bucket ==")
    explain_id = _write_cas_reco_fixture("avas")
    thread2 = thread_registry.create_thread(label="qatest_cas_reco_avas")
    thread2_id = thread2["thread_id"]
    thread_registry.set_active_job_ids(thread2_id, [explain_id])
    captured2: list[str] = []

    def _capturing_invoke_turn2(state_update, cfg):
        captured2.append(state_update["messages"][0].content)
        from langchain_core.messages import AIMessage
        return {"messages": [AIMessage(content="ok")], "active_job_ids": []}

    jw.invoke_turn = _capturing_invoke_turn2
    try:
        watcher2 = jw.JobWatcher(on_event=lambda tid, ev: None)
        watcher2._poll_once()
    finally:
        jw.invoke_turn = real_invoke_turn
    # avas recommends a space exactly as autocas does, so it belongs in the
    # bucket that follows a recommendation with a draft the user approves.
    # It was already listed in _poll_once's subtype check; this pins it now
    # that avas is a real, separate pipeline rather than autocas renamed.
    check("cas_reco/avas gets the auto-draft follow-up notice, like autocas",
          bool(captured2) and "start_job_draft" in captured2[0] and explain_id in captured2[0],
          captured2[0] if captured2 else "")
    thread_registry.delete_thread(thread2_id)

    print("\n== mechanical backstop: validate_draft still gates n_states/basis regardless of the notice's wording ==")
    draft_missing_both = {
        "task": "single_point", "subtype": "ee", "method": "casscf", "engine": "pyscf",
        "params": {"active_electrons": 6, "active_orbitals": 6, "initial_orbitals_job_id": autocas_id},
    }
    verdict = validate_draft(draft_missing_both, state={"molecule": WATER}, check_external=False)
    check("a draft with no n_states/basis is NOT ready even with everything else pre-filled",
          verdict.status == "incomplete", f"status={verdict.status}")
    check("...and specifically asks for n_states or basis (not something else)",
          verdict.asking_for in ("n_states", "basis"), f"asking_for={verdict.asking_for}")

    draft_with_basis_only = {
        "task": "single_point", "subtype": "ee", "method": "casscf", "engine": "pyscf",
        "params": {"active_electrons": 6, "active_orbitals": 6, "basis": "sto-3g"},
    }
    verdict2 = validate_draft(draft_with_basis_only, state={"molecule": WATER}, check_external=False)
    check("basis alone still isn't enough -- n_states is independently required for subtype=ee",
          verdict2.status == "incomplete" and verdict2.asking_for == "n_states",
          f"status={verdict2.status} asking_for={verdict2.asking_for}")

    print(f"\n{PASS} passed, {FAIL} failed")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
