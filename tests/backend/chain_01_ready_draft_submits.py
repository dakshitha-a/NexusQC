#!/usr/bin/env python3
"""A ready draft goes straight to the approval card when the user asked to run it.

    PYTHONPATH=$PWD python3 tests/backend/chain_01_ready_draft_submits.py

A draft coming back READY used to end with "NEXT STEP: if the user asked
for this calculation to be run, call submit_draft now", and the model spent
a whole agent turn doing what that sentence said. It was not only a turn
spent on a decided outcome: the comment on `_draft_input_preview` records
roughly one job matrix cell in five stopping there with a ready draft and
no approval card ever appearing, so it was a reliability defect too.

The judgment itself cannot move into the app. "The user asked for this to
be run" is a fact about what they said, not one the backend holds. So the
model still makes it, once, up front, and the app acts on it when the draft
completes.

**The default flipped on 2026-09-13, and this script was rewritten for it.**
It used to be that the model had to opt IN with `run_when_ready=True`, and
this file checked that a draft with the flag unset stopped at READY. R-101
measured what that cost on real conversations: on fresh threads the agent
reached no approval card at all in the whole nuclear-ensemble family and
intermittently in four others, ending the turn normally with a description of
a job and no way to approve it. So running is the default now and
`preview_only=True` is the opt-out, for the one case where a card is wrong:
the user asked to SEE an input rather than run one. `run_when_ready=True` is
still accepted and still means what it said, which is why the scenarios below
keep passing it.

Which way round the default sits is a judgement about the cost of being
wrong in each direction. A card nobody wanted costs one click on Reject. No
card when one was wanted costs a calculation that never happens, with nothing
on screen saying why.

What this script pins:

- a draft that is ready immediately reaches the approval interrupt in the
  SAME tool call, with no submit_draft in between;
- the intent is sticky, so a draft that becomes ready three updates later
  still chains;
- `preview_only` still gets the old behaviour exactly, which is what
  "show me the input without running it" depends on;
- the approval gate is untouched. Nothing runs without a card, and the card
  still carries the real spec and input preview;
- declining a chained card leaves the draft as the card showed it, not as
  it stood before the call that produced the card. That one is a genuine
  hazard rather than a nicety: `interrupt()` aborts the tool node without
  committing its writes, so the freshly built draft has to be carried back
  out through the resumed call or it is silently lost;
- the intent does not survive the episode, so a later unrelated draft does
  not put an approval card in front of someone who asked only to look;
- and the boundary condition the `job_submitted` node depends on still
  holds now that `_finish_submission` has a second caller: an approved
  chained job still ends its turn with no model call.

Most of it runs against a tools-only graph, for the reason
agent_02_draft_flow.py gives: with the real agent node in place, a live
model cheerfully calls draft tools on its own initiative mid-assertion. The
last scenario needs the full graph, because what it checks is the routing.
"""
from __future__ import annotations

import shutil
import sys
import time
import uuid
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO))

from langchain_core.messages import AIMessage, HumanMessage  # noqa: E402
from langgraph.types import Command  # noqa: E402

from app.agent import graph as ag  # noqa: E402
from app.agent import threads as thread_registry  # noqa: E402
from app.agent.graph import get_graph, pending_approval, read_state  # noqa: E402
from app.chemistry.jobs.base import delete_job_dir  # noqa: E402
from app.chemistry.molecule import resolve_molecule  # noqa: E402
from app.config import JOBS_DIR  # noqa: E402

failures: list[str] = []
checks = 0

# A real resolved molecule, not a hand-written dict: the input builders read
# the exact shape Molecule.to_dict() produces, and a plausible stand-in
# fails deep in the preview builder with a bare KeyError.
WATER = resolve_molecule("water").to_dict()

created_jobs: list[str] = []
created_threads: list[str] = []


def check(label: str, ok: bool, detail: str = "") -> None:
    global checks
    checks += 1
    if ok:
        print(f"  [PASS] {label}")
    else:
        print(f"  [FAIL] {label}" + (f" -- {detail}" if detail else ""))
        failures.append(label)


class Harness:
    """One throwaway thread running the tool node and nothing else, the same
    shape agent_02_draft_flow.py uses. Real state schema, real reducers, real
    checkpointer, real interrupt(); only the model is absent."""

    def __init__(self, tmpdir: Path):
        import sqlite3

        from langgraph.checkpoint.sqlite import SqliteSaver
        from langgraph.graph import END, START, StateGraph
        from langgraph.prebuilt import ToolNode

        from app.agent.state import AgentState
        from app.agent.tools import get_all_tools

        conn = sqlite3.connect(str(tmpdir / f"{uuid.uuid4().hex}.sqlite"),
                               check_same_thread=False)
        builder = StateGraph(AgentState)
        builder.add_node("tools", ToolNode(get_all_tools()))
        builder.add_edge(START, "tools")
        builder.add_edge("tools", END)
        self.g = builder.compile(checkpointer=SqliteSaver(conn))
        self.config = {"configurable": {"thread_id": f"chain-{uuid.uuid4().hex[:8]}"}}
        self.n = 0

    def seed(self, **state) -> None:
        self.g.update_state(self.config, {
            "messages": [HumanMessage(content="(scripted)")], **state})

    def call(self, name: str, args: dict) -> str:
        self.n += 1
        call_id = f"call_{self.n}"
        self.g.invoke({"messages": [
            AIMessage(content="", tool_calls=[{"name": name, "args": args, "id": call_id}])
        ]}, self.config)
        return self._tool_message(call_id)

    def _tool_message(self, call_id: str) -> str:
        messages = self.g.get_state(self.config).values.get("messages") or []
        for m in reversed(messages):
            if getattr(m, "type", "") == "tool" and getattr(m, "tool_call_id", None) == call_id:
                return m.content
        return f"<no ToolMessage produced for {call_id}>"

    def values(self) -> dict:
        return self.g.get_state(self.config).values

    def draft(self) -> dict:
        return self.values().get("job_draft") or {}

    def pending(self):
        snapshot = self.g.get_state(self.config)
        return snapshot.interrupts[0].value if snapshot.interrupts else None

    def resume(self, value) -> str:
        call_id = f"call_{self.n}"
        self.g.invoke(Command(resume=value), self.config)
        return self._tool_message(call_id)


class StubLLM:
    def __init__(self, counter: list[int]) -> None:
        self._counter = counter

    def invoke(self, messages):
        self._counter[0] += 1
        return AIMessage(content="(stubbed model turn)")


def run_tools_only(tmp: Path) -> None:
    print("\n== the call that completes a draft opens the card itself ==")
    h = Harness(tmp)
    h.seed(molecule=WATER)
    # start_job_draft carries only task/method/engine, so a single point is
    # always at least one answer short of ready. That last answer is where
    # the old flow spent its extra turn: the reply came back READY and the
    # model's next turn existed only to call submit_draft.
    out = h.call("start_job_draft", {"task": "single point", "method": "hf"})
    check("the draft starts one answer short", "DRAFT INCOMPLETE" in out, out[:160])
    out = h.call("update_job_draft", {"updates": {"basis": "sto-3g"},
                                      "run_when_ready": True})
    pending = h.pending()
    check("the approval card is open on that same call", pending is not None, out[:160])
    check("no NEXT STEP sentence was returned instead",
          "NEXT STEP" not in out, out[:160])
    if pending is not None:
        check("the card carries a real spec", bool(pending.get("spec")), str(pending)[:160])
        check("and the engine input to be approved",
              bool(pending.get("input_preview")), "input_preview was empty")

    print("\n== declining leaves the draft as the card showed it ==")
    if pending is not None:
        h.resume({"approved": False})
        draft = h.draft()
        # The hazard this covers: interrupt() aborts the tool node without
        # committing its writes, so the draft built in the aborted call has
        # to be carried back out through the resumed one.
        check("the freshly built draft survived the interrupt",
              draft.get("task") == "single_point", f"draft={draft}")
        check("the run-it intent did not survive the episode",
              not h.values().get("draft_run_when_ready"),
              str(h.values().get("draft_run_when_ready")))

    print("\n== the intent is sticky across elicitation ==")
    h = Harness(tmp)
    h.seed(molecule=WATER)
    out = h.call("start_job_draft", {"task": "geometry optimization", "method": "hf",
                                     "run_when_ready": True})
    check("an incomplete draft still asks its question", "DRAFT INCOMPLETE" in out, out[:160])
    check("and does not open a card early", h.pending() is None, str(h.pending())[:120])
    # Deliberately does NOT repeat run_when_ready: the point is that stating
    # it once is enough.
    out = h.call("update_job_draft", {"updates": {"basis": "sto-3g"}})
    check("answering the last question opens the card by itself",
          h.pending() is not None, out[:160])

    print("\n== preview_only still answers \"show me the input\" ==")
    # The narrow case the default has to leave room for. Stated once on the
    # first call and sticky from there, the same way the run intent is, so a
    # user who said "just show me the input" does not have to say it again at
    # every elicitation step.
    h = Harness(tmp)
    h.seed(molecule=WATER)
    out = h.call("start_job_draft", {"task": "single point", "method": "hf",
                                     "preview_only": True})
    check("an incomplete preview draft still asks its question",
          "DRAFT INCOMPLETE" in out, out[:160])
    out = h.call("update_job_draft", {"updates": {"basis": "sto-3g"}})
    check("a ready preview draft stops at READY", "DRAFT READY" in out, out[:160])
    check("no card is opened", h.pending() is None, str(h.pending())[:120])
    check("and the model is still told it may submit",
          "NEXT STEP" in out and "submit_draft" in out, out[:200])
    check("the input it would run is there to show",
          "input this job would use" in out, out[:400])
    check("the preview intent is sticky, so it did not have to be repeated",
          h.values().get("draft_preview_only") is True,
          str(h.values().get("draft_preview_only")))

    print("\n== with nothing stated at all, the card opens ==")
    # The R-101 default. Same draft as above with no flag either way.
    h = Harness(tmp)
    h.seed(molecule=WATER)
    h.call("start_job_draft", {"task": "single point", "method": "hf"})
    h.call("update_job_draft", {"updates": {"basis": "sto-3g"}})
    check("a ready draft opens the card without being asked twice",
          h.pending() is not None, str(h.pending())[:120])


def run_full_graph() -> int:
    """The routing half, which needs the real agent -> tools -> nodes graph.

    The boundary condition `_job_submitted_node` documents is that a
    successful submission is always the last thing its turn does. That held
    trivially while `_finish_submission` had exactly one caller. It now has
    two, so it is re-checked here rather than assumed.
    """
    print("\n== an approved chained job still ends its turn, with no model call ==")
    counter = [0]
    real_build = ag._build_llm
    ag._build_llm = lambda: StubLLM(counter)
    try:
        thread = thread_registry.create_thread(label="qatest_chain_submit")
        created_threads.append(thread["thread_id"])
        config = {"configurable": {"thread_id": thread["thread_id"]}}
        graph = get_graph()
        graph.update_state(config, {
            "molecule": WATER,
            "messages": [HumanMessage(content="run a single point on water at hf/sto-3g")],
            # Parked where the elicitation would have left it, so the single
            # tool call below is the one that completes the draft. Stamped
            # with draft_status for the reason submit_01_confirmation.py's
            # fixture documents.
            "job_draft": {"task": "single_point", "subtype": "gs", "method": "hf",
                          "engine": "pyscf", "params": {}},
            "draft_status": {"stage": "drafting", "at": time.time()},
        })
        graph.update_state(config, {"messages": [AIMessage(content="", tool_calls=[{
            "name": "update_job_draft",
            "args": {"updates": {"basis": "sto-3g"}, "run_when_ready": True},
            "id": f"c{time.time_ns()}",
        }])]}, as_node="agent")
        counter[0] = 0
        graph.invoke(None, config)

        pending = pending_approval(config)
        check("the card is open, having gone through no model turn", pending is not None,
              str(pending)[:160])
        check("no model turn was needed to reach it", counter[0] == 0, f"{counter[0]} call(s)")
        if pending is None:
            return 1

        counter[0] = 0
        graph.invoke(Command(resume={"approved": True, "spec": pending["spec"]}), config)
        state = read_state(config)
        for job_id in state.get("active_job_ids") or []:
            if job_id not in created_jobs:
                created_jobs.append(job_id)

        check("the job really was submitted", bool(state.get("active_job_ids")),
              str(state.get("active_job_ids")))
        check("and confirming it needed no model turn", counter[0] == 0, f"{counter[0]} call(s)")
        notice = next((n for n in (
            (getattr(m, "additional_kwargs", None) or {}).get("nexus_notice")
            for m in state["messages"]) if n), None)
        check("the app wrote the confirmation",
              (notice or {}).get("kind") == "job_submitted", str(notice))
        snapshot = graph.get_state(config)
        check("the turn is really over", snapshot.next == (), str(snapshot.next))
        check("the run-it intent was cleared with the episode",
              not state.get("draft_run_when_ready"), str(state.get("draft_run_when_ready")))

        # `_submissions_this_step` requires every call in the batch to carry
        # a receipt. update_job_draft can now produce one, so the mixed-batch
        # fall-through has to be re-checked against a draft tool rather than
        # only against submit_draft.
        print("\n== a mixed batch containing a chained submission still reaches the model ==")
        thread = thread_registry.create_thread(label="qatest_chain_mixed")
        created_threads.append(thread["thread_id"])
        config = {"configurable": {"thread_id": thread["thread_id"]}}
        graph.update_state(config, {
            "molecule": WATER,
            "messages": [HumanMessage(content="how is that job doing, and run the single point")],
            "job_draft": {"task": "single_point", "subtype": "gs", "method": "hf",
                          "engine": "pyscf", "params": {}},
            "draft_status": {"stage": "drafting", "at": time.time()},
        })
        graph.update_state(config, {"messages": [AIMessage(content="", tool_calls=[
            {"name": "check_job_status", "args": {"job_id": "nosuchjob"},
             "id": f"x{time.time_ns()}"},
            {"name": "update_job_draft",
             "args": {"updates": {"basis": "sto-3g"}, "run_when_ready": True},
             "id": f"c{time.time_ns()}"},
        ])]}, as_node="agent")
        graph.invoke(None, config)
        pending = pending_approval(config)
        check("the card still opens from inside the mixed batch", pending is not None,
              str(pending)[:120])
        if pending is not None:
            counter[0] = 0
            graph.invoke(Command(resume={"approved": True, "spec": pending["spec"]}), config)
            state = read_state(config)
            for job_id in state.get("active_job_ids") or []:
                if job_id not in created_jobs:
                    created_jobs.append(job_id)
            check("the model relayed the batch rather than the node ending it",
                  counter[0] == 1, f"{counter[0]} call(s)")
            check("no app-written confirmation was published",
                  not any((getattr(m, "additional_kwargs", None) or {}).get("nexus_notice")
                          for m in state["messages"]),
                  "a notice was written for a mixed batch")
    finally:
        ag._build_llm = real_build
    return 0


def main() -> int:
    tmp = JOBS_DIR.parent / f"_chain_test_{uuid.uuid4().hex[:8]}"
    tmp.mkdir(parents=True, exist_ok=True)
    try:
        run_tools_only(tmp)
        run_full_graph()
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
        for job_id in created_jobs:
            try:
                delete_job_dir(job_id)
            except Exception as exc:  # noqa: BLE001
                print(f"  (cleanup) could not remove job {job_id}: {exc}")
        for thread_id in created_threads:
            try:
                thread_registry.delete_thread(thread_id)
            except Exception as exc:  # noqa: BLE001
                print(f"  (cleanup) could not remove thread {thread_id}: {exc}")

    print(f"\n{checks - len(failures)}/{checks} checks passed")
    if failures:
        print("FAILED:")
        for label in failures:
            print(f"  - {label}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
