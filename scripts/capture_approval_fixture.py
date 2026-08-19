#!/usr/bin/env python3
"""Capture a checkpoint fixture holding a *pending* job approval.

Phase 2 rewrites `app/agent/tools.py` wholesale, and with it the payload
`submit_job` passes to `interrupt()`. Threads that were paused on the old
payload have to keep resuming afterwards -- both the approve and the
reject path -- which is what step P2.7 tests. That test needs a real
checkpoint written by the *pre-rebuild* toolset, and once the rewrite
lands there is no way to produce one again. So this script runs once, at
the start of Phase 2, and its output is committed.

The fixture is deliberately captured without going through the LLM. The
graph is a plain ReAct loop (agent -> tools -> agent), so writing an
AIMessage that already carries the `submit_job` tool call, `as_node=
"agent"`, puts the thread exactly where a model's tool call would have
left it; `invoke(None, ...)` then runs the tools node and pauses on the
approval interrupt. That keeps the fixture reproducible and independent
of whatever the served model happens to answer, and it is the same
technique P2.7's test uses to drive the resume.

Writes two files under tests/data/:

  pre_rebuild_approval.sqlite -- the checkpoint database itself, the
      thing a resume actually needs.
  pre_rebuild_approval.json   -- the interrupt payload and the thread id,
      in readable form, so a reviewer can see what shape is being pinned
      without opening a sqlite file, and so a drift in the payload keys
      is visible in a diff.

Usage:  PYTHONPATH=$PWD python3 scripts/capture_approval_fixture.py
"""
from __future__ import annotations

import json
import shutil
import sqlite3
import sys
import uuid
from pathlib import Path

from langchain_core.messages import AIMessage, HumanMessage

PROJECT_ROOT = Path(__file__).resolve().parents[1]
FIXTURE_DIR = PROJECT_ROOT / "tests" / "data"
FIXTURE_DB = FIXTURE_DIR / "pre_rebuild_approval.sqlite"
FIXTURE_JSON = FIXTURE_DIR / "pre_rebuild_approval.json"

# A deliberately trivial job: the point of the fixture is the interrupt
# payload and the resume, not the chemistry. Water/STO-3G/HF on PySCF also
# means P2.7's approve path can actually run to completion in seconds on a
# machine with no licensed engine installed.
TOOL_CALL_ARGS = {
    "job_type": "single_point",
    "engine": "pyscf",
    "qc_method": "hf",
    "basis": "sto-3g",
}

WATER = {
    "name": "water",
    "formula": "H2O",
    "charge": 0,
    "multiplicity": 1,
    "atoms": [
        {"element": "O", "x": 0.0000, "y": 0.0000, "z": 0.1173},
        {"element": "H", "x": 0.0000, "y": 0.7572, "z": -0.4692},
        {"element": "H", "x": 0.0000, "y": -0.7572, "z": -0.4692},
    ],
    "smiles": "O",
    "source": "fixture",
}


def main() -> int:
    # Imported here rather than at module scope so this file can be read
    # (and its docstring shown) without paying the import cost of the whole
    # chemistry stack.
    from app.agent import graph as graph_mod

    FIXTURE_DIR.mkdir(parents=True, exist_ok=True)

    # Capture into a scratch database rather than the live data/ one, so
    # running this never disturbs a working checkout's conversations.
    scratch = FIXTURE_DIR / "_capture_scratch.sqlite"
    for stale in scratch.parent.glob("_capture_scratch.sqlite*"):
        stale.unlink()
    graph_mod.CHECKPOINT_DB = scratch
    graph_mod._checkpoint_conn = None
    graph_mod.invalidate_graph_cache()

    thread_id = f"fixture-{uuid.uuid4().hex[:12]}"
    config = {"configurable": {"thread_id": thread_id}}
    g = graph_mod.get_graph()

    tool_call_id = "call_fixture_submit_job"
    g.update_state(
        config,
        {
            "molecule": WATER,
            "messages": [
                HumanMessage(content="Run a Hartree-Fock single point on water with STO-3G."),
                AIMessage(
                    content="",
                    tool_calls=[{
                        "name": "submit_job",
                        "args": dict(TOOL_CALL_ARGS),
                        "id": tool_call_id,
                    }],
                ),
            ],
        },
        as_node="agent",
    )

    g.invoke(None, config)

    snapshot = g.get_state(config)
    if not snapshot.interrupts:
        print("FAIL: the graph did not pause on an interrupt -- nothing to capture.")
        return 1
    payload = snapshot.interrupts[0].value
    if not isinstance(payload, dict) or payload.get("kind") != "job_approval":
        print(f"FAIL: unexpected interrupt payload: {payload!r}")
        return 1

    # Flush the sqlite write-ahead state into the main file before copying,
    # otherwise the fixture can land mid-transaction.
    conn: sqlite3.Connection = graph_mod._checkpoint_conn
    conn.commit()
    conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    conn.commit()

    shutil.copyfile(scratch, FIXTURE_DB)
    for leftover in scratch.parent.glob("_capture_scratch.sqlite*"):
        leftover.unlink()

    # Only the keys and a few scalar values are pinned in the JSON. The
    # full spec and input preview live in the sqlite file; duplicating
    # them here would make every unrelated preview tweak a diff in a
    # fixture that is supposed to pin the *shape*.
    readable = {
        "captured_for": "P2.7 -- old-thread compatibility across the Phase 2 toolset rewrite",
        "thread_id": thread_id,
        "tool_call_id": tool_call_id,
        "tool_name": "submit_job",
        "tool_call_args": TOOL_CALL_ARGS,
        "interrupt_payload_keys": sorted(payload.keys()),
        "interrupt_kind": payload.get("kind"),
        "job_type": payload.get("job_type"),
        "engine": payload.get("engine"),
        "molecule_name": payload.get("molecule_name"),
        "spec_keys": sorted((payload.get("spec") or {}).keys()),
        "spec_method": (payload.get("spec") or {}).get("method"),
        "spec_params": (payload.get("spec") or {}).get("params"),
    }
    FIXTURE_JSON.write_text(json.dumps(readable, indent=2, sort_keys=True) + "\n")

    print(f"captured thread {thread_id}")
    print(f"  interrupt keys: {', '.join(readable['interrupt_payload_keys'])}")
    print(f"  {FIXTURE_DB.relative_to(PROJECT_ROOT)} ({FIXTURE_DB.stat().st_size} bytes)")
    print(f"  {FIXTURE_JSON.relative_to(PROJECT_ROOT)}")

    return _self_check(graph_mod, thread_id)


def _self_check(graph_mod, thread_id: str) -> int:
    """Prove the captured fixture is actually resumable, here and now.

    A fixture that cannot be resumed by the toolset that wrote it would be
    useless for testing a *later* toolset against, and the failure would
    only surface at P2.7 -- by which point the pre-rebuild code is gone and
    it can no longer be recaptured. So the check runs at capture time.

    It resumes a throwaway copy along the *reject* path only. Rejecting is
    the side-effect-free branch: it returns a ToolMessage and submits
    nothing, so the check leaves no job behind. It also cannot consume the
    fixture, because the copy is deleted afterwards and the committed file
    is never opened for writing.
    """
    from langgraph.types import Command

    probe = FIXTURE_DIR / "_selfcheck_scratch.sqlite"
    shutil.copyfile(FIXTURE_DB, probe)
    graph_mod.CHECKPOINT_DB = probe
    graph_mod._checkpoint_conn = None
    graph_mod.invalidate_graph_cache()

    config = {"configurable": {"thread_id": thread_id}}
    g = graph_mod.get_graph()
    pending = g.get_state(config)
    if not pending.interrupts:
        print("FAIL self-check: the copied fixture has no pending interrupt.")
        return 1

    # Resuming would normally run the agent node (and therefore the LLM)
    # once the tool returns. The tool's own ToolMessage is the whole
    # subject of the check, so read it off the state and stop rather than
    # requiring a served model to be up.
    try:
        for _ in g.stream(Command(resume={"approved": False}), config, stream_mode="updates"):
            state = g.get_state(config)
            messages = state.values.get("messages") or []
            if messages and getattr(messages[-1], "type", "") == "tool":
                break
    except Exception as exc:  # the follow-up agent node needs a live model
        if "Connection" not in type(exc).__name__ and "connect" not in str(exc).lower():
            print(f"FAIL self-check: resume raised {type(exc).__name__}: {exc}")
            return 1

    messages = g.get_state(config).values.get("messages") or []
    tool_messages = [m for m in messages if getattr(m, "type", "") == "tool"]
    if not tool_messages:
        print("FAIL self-check: resume produced no ToolMessage.")
        return 1
    content = tool_messages[-1].content
    if "did NOT approve" not in content:
        print(f"FAIL self-check: unexpected reject ToolMessage: {content!r}")
        return 1

    for leftover in probe.parent.glob("_selfcheck_scratch.sqlite*"):
        leftover.unlink()
    print("  self-check: reject resume on a copy returned the not-approved ToolMessage")
    return 0


if __name__ == "__main__":
    sys.exit(main())
