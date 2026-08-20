"""P9.3: source_geometry_job_id -- a job draft reusing a specific prior
job's own geometry (its optimized geometry if it produced one, else its
input geometry) instead of whatever is in the molecule panel.

Checked via tools_requested()/tools_executed() rather than GET
/api/threads/{id}/state: job_draft is intentionally NOT one of the fields
serialize_state() exposes (app/agent/serialize.py only whitelists
messages/molecule/molecule_frames/active_job_ids for the frontend), so a
draft's contents can only be observed through what the model actually
wrote (tools_requested's update_job_draft calls) and what the backend said
back (tools_executed's ToolMessage text) -- which is also the more
faithful check anyway, since it is what the model itself saw and acted on.

G1's very first tool response can still legitimately ask "which molecule" --
elicitation.py answers one question at a time, and the model cannot supply
source_geometry_job_id before it has been told a molecule is needed. What
G1 actually checks is that the model never falls back to set_geometry (the
panel path) and reaches READY once it supplies the tag.

G1/G2 cover the two backend-verified paths directly (elicitation.py's
_source_geometry_problem, app/agent/tools.py's _resolve_draft_molecule) --
those were already exercised with synthetic drafts against real jobs
before this file existed (see docs/TRACKER.md's P9.3 evidence), so what
this file adds is proof the MODEL reaches for the parameter correctly from
ordinary conversation, not proof the resolution logic itself is correct.

G3 is a full submit-approve-run round trip: real but cheap (HF/STO-3G),
matching e2e_08's own precedent for letting a real single-point complete
rather than mocking the job manager.

G4 is the two-turn "repeat that" case the whole feature exists for, and is
inherently a question about model judgement (recalling a job id from
earlier in its own conversation), not backend code -- a G4 failure is
model-quality signal, not evidence of a code bug, and is recorded as such
rather than treated as a blocking regression.

Run this AFTER e2e_08_job_matrix.py -- every case here works from a job
that already exists in the account.
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from fixtures import admin_client, check, summary  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _agent import AgentSession, record  # noqa: E402


def find_completed_job(client, method: str = "hf", engine: str = "pyscf"):
    r = client.get("/api/jobs")
    r.raise_for_status()
    for j in r.json():
        if j.get("status") == "completed" and j.get("method") == method and j.get("engine") == engine \
                and j.get("task") == "single_point":
            return j["job_id"]
    return None


def draft_update_calls(turn) -> list[dict]:
    """Every update_job_draft `updates` dict the model wrote this turn."""
    return [args.get("updates") or {} for name, args in turn.tools_requested()
            if name == "update_job_draft"]


def main() -> None:
    admin = admin_client()
    job_id = find_completed_job(admin)
    if not job_id:
        check("a completed hf/pyscf single-point job exists to tag (run e2e_08_job_matrix.py first)", False)
        summary(exit_on_failure=False)
        return
    print(f"Using job {job_id} as the geometry source.\n")

    # ------------------------------------------------------------ G1: explicit tag, no panel molecule
    s1 = AgentSession.new(admin, label="e2e source-geometry explicit tag")
    turn1 = s1.say(
        f"Set up (but do not submit) a single-point HF/STO-3G calculation using the exact same "
        f"geometry as job {job_id}. Do not ask me to pick a molecule -- use that job's geometry.",
        timeout=240,
    )
    updates1 = draft_update_calls(turn1)
    tagged = any(u.get("source_geometry_job_id") == job_id for u in updates1)
    exec_texts1 = [t for _n, t in turn1.tools_executed()]
    # "Which molecule..." on the FIRST call (before source_geometry_job_id
    # has been written yet) is correct, expected behaviour -- elicitation.py
    # asks one question at a time, and the model cannot answer a question
    # in the same call that triggers it. What matters is the model never
    # calls set_geometry (the panel-molecule path) and the draft reaches
    # READY once source_geometry_job_id is supplied.
    never_called_set_geometry = "set_geometry" not in [n for n, _ in turn1.tools_requested()]
    reached_ready1 = bool(exec_texts1) and "DRAFT READY" in exec_texts1[-1]
    ok1 = tagged and never_called_set_geometry and reached_ready1
    check("an explicit 'use job X's geometry' request writes source_geometry_job_id into the draft "
          "and reaches READY without ever calling set_geometry", ok1,
          f"updates={updates1}, never_called_set_geometry={never_called_set_geometry}, "
          f"reached_ready={reached_ready1}")
    record("G1-explicit-tag", "PASS" if ok1 else "FAIL", job_id=job_id, updates=updates1)
    s1.close()

    # ------------------------------------------------------------ G2: bad tag refuses, not fabricates
    s2 = AgentSession.new(admin, label="e2e source-geometry bad tag")
    turn2 = s2.say(
        "Set up (but do not submit) a single-point HF/STO-3G calculation using the exact same "
        "geometry as job zzz-does-not-exist. Do not pick any other molecule.",
        timeout=240,
    )
    exec_texts2 = "\n".join(t for _n, t in turn2.tools_executed())
    refused = "No such job" in exec_texts2
    reached_ready = "DRAFT READY" in exec_texts2
    check("a nonexistent tagged job is refused by name (the backend's own 'No such job' text), not "
          "silently substituted with something else", refused and not reached_ready,
          f"refused={refused}, reached_ready={reached_ready}, tool_texts={exec_texts2[:250]}")
    record("G2-bad-tag", "PASS" if (refused and not reached_ready) else "FAIL", text=exec_texts2[:300])
    s2.close()

    # ------------------------------------------------------------ G3: full round trip
    s3 = AgentSession.new(admin, label="e2e source-geometry round trip")
    s3.say(
        f"Start a single-point HF/STO-3G calculation using the exact same geometry as job {job_id}. "
        f"Do not ask me to pick a molecule.",
        timeout=240,
    )
    approval = s3.wait_for_approval(timeout=240)
    ok3 = False
    detail3 = "no approval reached"
    if approval:
        turn3 = s3.approve(timeout=420)
        # The submitted job id is easiest to pull from the tool message text
        # (submit_draft's own "id=..." wording) rather than assuming which
        # tool reports it next.
        texts = [t for _n, t in turn3.tools_executed()]
        joined = "\n".join(texts) + "\n" + (turn3.assistant_text() or "")
        m = re.search(r"id=([0-9a-f]{6,})", joined)
        if m:
            new_job = m.group(1)
            result = s3.await_job(new_job, timeout=300)
            code = f"""
from app.chemistry.jobs.base import read_spec
import json
src = (read_spec('{job_id}') or {{}}).get('molecule') or {{}}
new = (read_spec('{new_job}') or {{}}).get('molecule') or {{}}
print(json.dumps({{'src_symbols': src.get('symbols'), 'new_symbols': new.get('symbols'),
                    'src_coords': src.get('coords'), 'new_coords': new.get('coords')}}))
"""
            proc = subprocess.run(
                ["docker", "compose", "exec", "-T", "api", "python", "-c", code],
                cwd=str(Path(__file__).resolve().parent.parent.parent),
                capture_output=True, text=True, timeout=30,
            )
            geoms = None
            for line in proc.stdout.splitlines():
                if line.strip().startswith("{"):
                    geoms = json.loads(line)
            ok3 = (result.get("status") == "completed" and geoms is not None
                   and geoms["new_symbols"] == geoms["src_symbols"] and geoms["new_symbols"] is not None
                   and geoms["new_coords"] == geoms["src_coords"])
            detail3 = f"new_job={new_job}, geoms={geoms}"
        else:
            detail3 = f"could not find a submitted job id in: {joined[:300]}"
    check("approving a source_geometry_job_id draft runs a real job whose spec.molecule matches "
          "the tagged source job's own geometry", ok3, detail3)
    record("G3-round-trip", "PASS" if ok3 else "FAIL", detail=detail3[:400])
    s3.close()

    # ------------------------------------------------------------ G4: conversational reuse (two turns)
    s4 = AgentSession.new(admin, label="e2e source-geometry conversational reuse")
    s4.say(f"What's the HOMO-LUMO gap for job {job_id}?", timeout=240)
    turn4b = s4.say(
        "Now set up (but do not submit) that same calculation again, but with a cc-pVDZ basis "
        "instead. Use the same geometry as before -- don't ask me to pick a molecule.",
        timeout=240,
    )
    updates4 = draft_update_calls(turn4b)
    reused = any(u.get("source_geometry_job_id") == job_id for u in updates4)
    # Model-judgement case: report the outcome, but do not fail the whole
    # file over it -- see this file's own module docstring.
    print(f"[INFO] G4 (model-judgement, non-blocking): source_geometry_job_id reused = {reused}, "
          f"update calls = {updates4}")
    record("G4-conversational-reuse", "PASS" if reused else "INFO", job_id=job_id, updates=updates4)
    s4.close()

    summary(exit_on_failure=False)


if __name__ == "__main__":
    main()
