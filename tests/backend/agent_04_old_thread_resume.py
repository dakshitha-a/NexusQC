#!/usr/bin/env python3
"""P2.7 -- a conversation paused mid-approval survives the rebuild.

`submit_draft` replaced `submit_job`, but a thread that was sitting on the
old approval card still has that tool call pending in its checkpoint. The
tool name now resolves to nothing, and what LangGraph does with an unknown
tool is return `Error: submit_job is not a valid tool, try one of [...]` --
so the user clicks Approve and is shown a list of internal tool names.

The fixture this runs against is a real checkpoint written by the
pre-rebuild toolset (`scripts/capture_approval_fixture.py`, captured at the
start of the phase precisely because it could not be produced afterwards).
Nothing here is reconstructed or hand-written: the pending interrupt, its
twelve-key payload and its v1 spec are exactly what the old code left
behind.

The job genuinely cannot be run -- its spec was built by a tool that no
longer exists, in a taxonomy the runners are moving off -- so the fix is
not to run it but to say so in a sentence the model can relay. Both the
approve and the reject path land there, which is right: neither can
produce the calculation, and the difference between them stopped meaning
anything the moment the tool went away.

Run:  PYTHONPATH=$PWD python3 tests/backend/agent_04_old_thread_resume.py
"""
from __future__ import annotations

import json
import shutil
import sqlite3
import sys
from pathlib import Path

from langgraph.types import Command

PASS = 0
FAIL = 0

FIXTURE_DIR = Path(__file__).resolve().parent.parent / "data"
FIXTURE_DB = FIXTURE_DIR / "pre_rebuild_approval.sqlite"
FIXTURE_JSON = FIXTURE_DIR / "pre_rebuild_approval.json"


def check(label: str, ok: bool, detail: str = "") -> None:
    global PASS, FAIL
    if ok:
        PASS += 1
        print(f"  [PASS] {label}")
    else:
        FAIL += 1
        print(f"  [FAIL] {label}" + (f"\n         {detail}" if detail else ""))


# Kept alive for the lifetime of the run: SqliteSaver wraps this connection
# and closing it out from under a live graph would fail mid-resume.
_probe_conns: list = []


def open_fixture(tag: str):
    """A private copy of the fixture, so the committed one stays pending
    and each path below starts from the same state.

    The checkpointer is pinned to that copy by replacing
    `_get_checkpointer`, not by pointing `CHECKPOINT_DB` at it. Setting
    `CHECKPOINT_DB` was enough when SqliteSaver was the only backend, and
    silently stopped being enough once the deployment set
    `QC_AGENT_DATABASE_URL`: `_get_checkpointer` tests that first and
    returns a PostgresSaver, so the assignment did nothing, the fixture's
    thread was looked up in Postgres, and every path below resumed an
    empty conversation instead. The visible symptom was
    `500 no user query found in messages` from the model, because an empty
    conversation sends a system prompt and nothing else -- three checks
    failing for a reason that had nothing to do with what they test.

    This ran green on a developer's host (no DATABASE_URL, so SqliteSaver)
    and red in the container the suite is meant to run in, which is the
    worst way for a test to be wrong.
    """
    from langgraph.checkpoint.sqlite import SqliteSaver

    from app.agent import graph as graph_mod

    probe = FIXTURE_DIR / f"_resume_{tag}.sqlite"
    for stale in FIXTURE_DIR.glob(f"_resume_{tag}.sqlite*"):
        stale.unlink()
    shutil.copyfile(FIXTURE_DB, probe)
    conn = sqlite3.connect(str(probe), check_same_thread=False)
    _probe_conns.append(conn)
    graph_mod.CHECKPOINT_DB = probe
    graph_mod._checkpoint_conn = conn
    graph_mod._get_checkpointer = lambda: SqliteSaver(conn)
    graph_mod.invalidate_graph_cache()
    meta = json.loads(FIXTURE_JSON.read_text())
    config = {"configurable": {"thread_id": meta["thread_id"]}}
    return graph_mod, graph_mod.get_graph(), config, meta, probe


def tool_texts(g, config) -> list[str]:
    messages = g.get_state(config).values.get("messages") or []
    return [m.content for m in messages if getattr(m, "type", "") == "tool"]


def resume(g, config, value) -> str:
    """Resume, stopping as soon as the tool has answered -- the follow-up
    agent node would need a live model and is not what this tests."""
    try:
        for _ in g.stream(Command(resume=value), config, stream_mode="updates"):
            if tool_texts(g, config):
                break
    except Exception as exc:
        return f"<raised {type(exc).__name__}: {exc}>"
    texts = tool_texts(g, config)
    return texts[-1] if texts else "<no ToolMessage>"


def main() -> int:
    if not FIXTURE_DB.exists():
        print(f"[FAIL] the fixture is missing: {FIXTURE_DB}")
        return 1

    print("== the fixture is a genuine pre-rebuild checkpoint ==")
    _, g, config, meta, probe = open_fixture("shape")
    snapshot = g.get_state(config)
    # Checked first and explicitly: every other check below reads as a
    # failure of the app when the fixture simply did not load, which is how
    # this file spent time asserting things about an empty conversation.
    loaded = snapshot.values.get("messages") or []
    check("the fixture's own conversation is what got loaded", len(loaded) > 0,
          f"{len(loaded)} message(s); 0 means the checkpointer is not reading the probe file")
    check("it still has a pending approval", bool(snapshot.interrupts))
    payload = snapshot.interrupts[0].value if snapshot.interrupts else {}
    check("of the v1 shape", payload.get("kind") == "job_approval"
          and "task" not in payload,
          f"keys={sorted(payload.keys())}")
    check("carrying a v1 spec, with no task/subtype",
          "task" not in (payload.get("spec") or {}),
          f"spec keys={sorted((payload.get('spec') or {}).keys())}")
    check("recorded against the tool that no longer exists",
          meta["tool_name"] == "submit_job")
    for stale in FIXTURE_DIR.glob("_resume_shape.sqlite*"):
        stale.unlink()

    print("\n== the tool that would run it is gone from the model's surface ==")
    from app.agent.tools import get_all_tools, get_executable_tools

    offered = [t.name for t in get_all_tools()]
    executable = [t.name for t in get_executable_tools()]
    check("submit_job is not offered to the model", "submit_job" not in offered,
          f"offered={offered}")
    check("but the executor can still answer it", "submit_job" in executable)
    check("and it costs nothing in the prompt -- it is not bound",
          len(executable) == len(offered) + 1,
          f"{len(executable)} executable vs {len(offered)} offered")

    print("\n== rejecting an old card ==")
    _, g, config, _, probe = open_fixture("reject")
    text = resume(g, config, {"approved": False})
    check("does not surface an internal tool-name error",
          "is not a valid tool" not in text, text[:200])
    check("and explains what happened, in a sentence the model can relay",
          "earlier version of the agent" in text and "nothing was submitted" in text,
          text[:250])
    for stale in FIXTURE_DIR.glob("_resume_reject.sqlite*"):
        stale.unlink()

    print("\n== approving an old card ==")
    _, g, config, _, probe = open_fixture("approve")
    text = resume(g, config, {"approved": True, "spec": {}})
    check("does not crash the thread", not text.startswith("<raised"), text[:200])
    check("does not surface an internal tool-name error",
          "is not a valid tool" not in text, text[:200])
    check("says plainly that nothing was submitted",
          "nothing was submitted" in text, text[:250])
    check("and offers to set the job up again",
          "again" in text, text[:250])
    for stale in FIXTURE_DIR.glob("_resume_approve.sqlite*"):
        stale.unlink()

    print("\n== the committed fixture is untouched ==")
    _, g, config, _, _ = open_fixture("verify")
    check("it is still pending, for the next run",
          bool(g.get_state(config).interrupts))
    for stale in FIXTURE_DIR.glob("_resume_verify.sqlite*"):
        stale.unlink()

    total = PASS + FAIL
    print(f"\n{PASS}/{total} checks passed")
    if FAIL:
        print(f"[FAIL] {FAIL} check(s) failed")
        return 1
    print("[PASS] ALL CHECKS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
