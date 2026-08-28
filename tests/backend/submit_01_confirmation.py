#!/usr/bin/env python3
"""An approved job confirms itself, with no LLM turn in between.

    PYTHONPATH=$PWD python3 tests/backend/submit_01_confirmation.py

Clicking Approve used to be followed by a full agent turn whose entire
output was narration: "the job is now running, I'll report results when it
finishes". It decided nothing. The user had already reviewed the exact
input, the job either runs or fails, and both endings already have their
own paths (the watcher's summary, the failed-job notice). On this host a
turn like that costs 53 to 77 seconds of dead time between the click and
any sign the job started, and it is a hallucination surface for a message
the backend could write exactly.

So `tools` now routes to a `job_submitted` node that writes the
confirmation itself and ends the turn. The headline assertion here is
therefore a *negative* one, and it is why this script stubs the model
rather than mocking the graph: with the LLM replaced by a counter, a
successful submission must leave that counter at zero.

The other three scenarios exist because "end the turn" is only correct for
a batch that was nothing but successful submissions:

- a mixed batch (the model emitted check_job_status alongside submit_draft,
  which real conversations do) must still reach the model, or the other
  tool's result is never relayed;
- a rejection must still reach the model, because "what would you like to
  change?" is the whole point of declining;
- and a submission the model flagged as having follow-up work must hand
  back to it, so that "run a single point and a frequency calculation"
  still chains into the second card by itself.

Runs in-process against the real graph, the real checkpointer, the real
state reducers and a real JobManager. No server. The graph is parked at an
interrupt by writing an assistant tool call into state with
`as_node="agent"` and resuming, which is what the model would have
produced -- the same harness draft_01_summary_defer.py uses.
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO))

from langchain_core.messages import AIMessage, ToolMessage  # noqa: E402
from langgraph.types import Command  # noqa: E402

from app.agent import graph as ag  # noqa: E402
from app.agent import threads as thread_registry  # noqa: E402
from app.agent.graph import get_graph, pending_approval, read_state  # noqa: E402
from app.chemistry.jobs.base import delete_job_dir  # noqa: E402

failures: list[str] = []
checks = 0

WATER = {
    "name": "water",
    "symbols": ["O", "H", "H"],
    "coords": [[0.0, 0.0, 0.117], [0.0, 0.757, -0.467], [0.0, -0.757, -0.467]],
    "charge": 0,
    "multiplicity": 1,
}

# The cheapest thing this app can actually run, so the assertions are about
# routing rather than about chemistry. `method` is the level of theory and
# `task`/`subtype` is what the job is: separate axes in the v2 taxonomy.
READY_DRAFT = {
    "task": "single_point", "subtype": "gs", "method": "hf",
    "engine": "pyscf", "params": {"basis": "sto-3g"},
}

created_jobs: list[str] = []


def check(label: str, ok: bool, detail: str = "") -> None:
    global checks
    checks += 1
    if ok:
        print(f"  [PASS] {label}")
    else:
        print(f"  [FAIL] {label}" + (f" -- {detail}" if detail else ""))
        failures.append(label)


class StubLLM:
    """Stands in for the served model, and counts.

    Deliberately returns a benign message rather than raising: a sentinel
    that blew up would prove only that the model was reached, and two of
    the four scenarios below REQUIRE it to be reached and to answer.
    """

    def __init__(self, counter: list[int]) -> None:
        self._counter = counter

    def invoke(self, messages):
        self._counter[0] += 1
        return AIMessage(content="(stubbed model turn)")


def new_thread(label: str) -> dict:
    """A thread parked where a real drafting exchange would have left one.

    `draft_status` is stamped here as well as `job_draft`, because that is
    what `_draft_command` does and a submission can only ever follow a
    draft. Seeding only `job_draft` looks equivalent and is not: LangGraph
    stores the FIRST write to a reducer channel raw, bypassing the reducer,
    so a `draft_status` that was never set reads back as the raw
    CLEAR_DRAFT_STATUS sentinel instead of None after
    `_finish_submission` clears it. That is an artefact of an unrealistic
    fixture, not of the code under test.
    """
    thread = thread_registry.create_thread(label=label)
    config = {"configurable": {"thread_id": thread["thread_id"]}}
    get_graph().update_state(config, {
        "molecule": WATER,
        "job_draft": dict(READY_DRAFT),
        "draft_status": {"stage": "drafting", "at": time.time()},
    })
    return config


def park_at_card(config: dict, tool_calls: list[dict]) -> None:
    """Drive the real graph to a pending submit_draft interrupt, no LLM.

    Writing the assistant's tool call as `as_node="agent"` leaves the tools
    node queued exactly as a real turn would; resuming with `None` runs it
    and hits `interrupt()`.
    """
    get_graph().update_state(config, {"messages": [AIMessage(
        content="", tool_calls=tool_calls,
    )]}, as_node="agent")
    get_graph().invoke(None, config)


def submit_call(follow_up: bool = False) -> dict:
    args = {"follow_up_work": True} if follow_up else {}
    return {"name": "submit_draft", "args": args, "id": f"c{time.time_ns()}"}


def notices(state: dict) -> list[dict]:
    out = []
    for m in state.get("messages", []):
        notice = (getattr(m, "additional_kwargs", None) or {}).get("nexus_notice")
        if notice:
            out.append(notice)
    return out


def record_jobs(state: dict) -> None:
    for job_id in state.get("active_job_ids") or []:
        if job_id not in created_jobs:
            created_jobs.append(job_id)


def main() -> int:
    counter = [0]
    real_build = ag._build_llm
    ag._build_llm = lambda: StubLLM(counter)
    try:
        return run(counter)
    finally:
        ag._build_llm = real_build
        for job_id in created_jobs:
            try:
                delete_job_dir(job_id)
            except Exception as exc:  # noqa: BLE001
                print(f"  (cleanup) could not remove job {job_id}: {exc}")


def run(counter: list[int]) -> int:
    graph = get_graph()

    print("\n== an approved job confirms itself, with no model turn ==")
    config = new_thread("qatest_submit_confirm")
    park_at_card(config, [submit_call()])
    pending = pending_approval(config)
    # Asserted before anything else: without a card there is no interrupt to
    # resume, and every assertion below would pass against nothing.
    check("the approval card is open", pending is not None, str(pending))
    if pending is None:
        return 1

    counter[0] = 0
    graph.invoke(Command(resume={"approved": True, "spec": pending["spec"]}), config)
    state = read_state(config)
    record_jobs(state)

    check("no model turn ran", counter[0] == 0, f"{counter[0]} call(s)")

    messages = state["messages"]
    last = messages[-1]
    check("the turn ends on an assistant message",
          isinstance(last, AIMessage) and bool(last.content), type(last).__name__)
    check("it comes after the tool result",
          isinstance(messages[-2], ToolMessage), type(messages[-2]).__name__)

    found = notices(state)
    job_ids = state.get("active_job_ids") or []
    check("it carries the job_submitted notice",
          len(found) == 1 and found[0].get("kind") == "job_submitted", str(found))
    check("the notice names the job that started",
          bool(job_ids) and found and found[0].get("job_ids") == job_ids, str(found))

    text = last.content
    check("it names the job the way the Job Manager does",
          "water" in text and "sto-3g" in text.lower(), text[:120])
    check("it does not leak an internal task identifier",
          "single_point" not in text and "subtype" not in text, text[:120])
    check("it gives the user the job id", bool(job_ids) and job_ids[0] in text, text[:120])

    snapshot = graph.get_state(config)
    check("the turn is really over", snapshot.next == (), str(snapshot.next))
    check("the drafting episode is closed", state.get("draft_status") is None,
          str(state.get("draft_status")))
    check("the receipt was consumed", (state.get("pending_submissions") or []) == [],
          str(state.get("pending_submissions")))

    tool_msg = messages[-2].content
    check("the tool record still carries id=<job_id> for e2e_12's grep",
          bool(job_ids) and f"id={job_ids[0]}" in tool_msg, tool_msg[:160])
    check("the tool record tells the next turn not to re-announce",
          "do not announce it again" in tool_msg, tool_msg[:160])

    print("\n== declared follow-up work still hands back to the model ==")
    config = new_thread("qatest_submit_followup")
    park_at_card(config, [submit_call(follow_up=True)])
    pending = pending_approval(config)
    check("the approval card is open", pending is not None, str(pending))
    if pending is not None:
        counter[0] = 0
        graph.invoke(Command(resume={"approved": True, "spec": pending["spec"]}), config)
        state = read_state(config)
        record_jobs(state)
        check("the model got the turn back", counter[0] == 1, f"{counter[0]} call(s)")
        found = notices(state)
        check("the confirmation was still written", len(found) == 1, str(found))
        types = [type(m).__name__ for m in state["messages"]]
        confirm_at = next((i for i, m in enumerate(state["messages"])
                           if (getattr(m, "additional_kwargs", None) or {}).get("nexus_notice")), -1)
        check("the user saw the confirmation before the chained turn ran",
              confirm_at != -1 and confirm_at < len(state["messages"]) - 1, str(types[-4:]))

    print("\n== a mixed batch still goes to the model ==")
    config = new_thread("qatest_submit_mixed")
    park_at_card(config, [
        {"name": "check_job_status", "args": {"job_id": "nosuchjob"}, "id": f"x{time.time_ns()}"},
        submit_call(),
    ])
    pending = pending_approval(config)
    check("the approval card is open", pending is not None, str(pending))
    if pending is not None:
        counter[0] = 0
        graph.invoke(Command(resume={"approved": True, "spec": pending["spec"]}), config)
        state = read_state(config)
        record_jobs(state)
        check("the model relayed the batch", counter[0] == 1, f"{counter[0]} call(s)")
        check("no confirmation was written", notices(state) == [], str(notices(state)))
        check("the other tool's result survived in history",
              any(isinstance(m, ToolMessage) and "nosuchjob" in m.content
                  for m in state["messages"]),
              "check_job_status result missing")

    print("\n== a rejection still goes to the model ==")
    config = new_thread("qatest_submit_reject")
    park_at_card(config, [submit_call()])
    pending = pending_approval(config)
    check("the approval card is open", pending is not None, str(pending))
    if pending is not None:
        counter[0] = 0
        graph.invoke(Command(resume={"approved": False}), config)
        state = read_state(config)
        check("the model was asked to reply", counter[0] == 1, f"{counter[0]} call(s)")
        check("no confirmation was written", notices(state) == [], str(notices(state)))
        check("the drafting episode is closed", state.get("draft_status") is None,
              str(state.get("draft_status")))

    print(f"\n{checks - len(failures)}/{checks} checks passed")
    if failures:
        print("FAILED:")
        for label in failures:
            print(f"  - {label}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
