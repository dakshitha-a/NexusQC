#!/usr/bin/env python3
"""Declining an approval card answers immediately, with no LLM turn.

    PYTHONPATH=$PWD python3 tests/backend/reject_01_decline_message.py

The sibling of submit_01_confirmation.py, and the same argument. Clicking
Reject used to be followed by a full agent turn whose entire output was a
paraphrase of a sentence the tool had just handed it: "The user did NOT
approve running this job. Ask what they'd like to change." Nothing about
that is a decision. The user had the exact input in front of them and chose
not to run it.

It was in fact worse than the submission case. The approval card is
dismissed the instant the button is clicked (JobApprovalCard's onMutate
does not wait for the server), so the user was left looking at an empty
pane for the length of that turn, having just acted themselves.

So `tools` now routes a rejection to a `job_rejected` node that writes the
message itself. The headline assertion is the same negative one, and is
why the model is stubbed and counted rather than the graph mocked: a
decline must leave that counter at zero.

The rest of the file is about the boundaries, which is where this kind of
routing goes wrong:

- the message must name the draft, so someone who declined one of several
  knows which one this was, and must not leak an internal task identifier;
- the draft must SURVIVE, because the message invites the user to change
  something and update_job_draft needs a draft to amend. This is the one
  place a rejection deliberately differs from a submission;
- declared follow-up work must still hand back to the model, or declining
  one job silently drops the rest of a multi-part request;
- a batch mixing a rejection with any other tool must reach the model, and
  so must a batch mixing a rejection with a submission, since the two write
  different receipt slots and neither can then cover the whole batch.

Runs in-process against the real graph, the real checkpointer and the real
state reducers. No server, and nothing is ever submitted, so unlike
submit_01 this script creates no job directories to clean up. It does
create threads, which it removes at the end.
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

failures: list[str] = []
checks = 0

WATER = {
    "name": "water",
    "symbols": ["O", "H", "H"],
    "coords": [[0.0, 0.0, 0.117], [0.0, 0.757, -0.467], [0.0, -0.757, -0.467]],
    "charge": 0,
    "multiplicity": 1,
}

READY_DRAFT = {
    "task": "single_point", "subtype": "gs", "method": "hf",
    "engine": "pyscf", "params": {"basis": "sto-3g"},
}

created_threads: list[str] = []


def check(label: str, ok: bool, detail: str = "") -> None:
    global checks
    checks += 1
    if ok:
        print(f"  [PASS] {label}")
    else:
        print(f"  [FAIL] {label}" + (f" -- {detail}" if detail else ""))
        failures.append(label)


class StubLLM:
    """Stands in for the served model, and counts. Answers benignly rather
    than raising, because two scenarios here require it to be reached."""

    def __init__(self, counter: list[int]) -> None:
        self._counter = counter

    def invoke(self, messages):
        self._counter[0] += 1
        return AIMessage(content="(stubbed model turn)")


def new_thread(label: str) -> dict:
    """A thread parked where a real drafting exchange would have left one.

    `draft_status` is stamped alongside `job_draft` for the reason
    submit_01_confirmation.py's own fixture documents: LangGraph stores the
    first write to a reducer channel raw, so a status that was never set
    reads back as the raw clear sentinel rather than None once
    `_finish_submission` clears it.
    """
    thread = thread_registry.create_thread(label=label)
    created_threads.append(thread["thread_id"])
    config = {"configurable": {"thread_id": thread["thread_id"]}}
    get_graph().update_state(config, {
        "molecule": WATER,
        "job_draft": dict(READY_DRAFT),
        "draft_status": {"stage": "drafting", "at": time.time()},
    })
    return config


def park_at_card(config: dict, tool_calls: list[dict]) -> None:
    """Drive the real graph to a pending submit_draft interrupt, no LLM."""
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


def main() -> int:
    counter = [0]
    real_build = ag._build_llm
    ag._build_llm = lambda: StubLLM(counter)
    try:
        return run(counter)
    finally:
        ag._build_llm = real_build
        for thread_id in created_threads:
            try:
                thread_registry.delete_thread(thread_id)
            except Exception as exc:  # noqa: BLE001
                print(f"  (cleanup) could not remove thread {thread_id}: {exc}")


def run(counter: list[int]) -> int:
    graph = get_graph()

    print("\n== a declined card answers itself, with no model turn ==")
    config = new_thread("qatest_reject_message")
    park_at_card(config, [submit_call()])
    pending = pending_approval(config)
    # Asserted first: with no card there is no interrupt to decline, and
    # every assertion below would pass against nothing.
    check("the approval card is open", pending is not None, str(pending))
    if pending is None:
        return 1

    counter[0] = 0
    graph.invoke(Command(resume={"approved": False}), config)
    state = read_state(config)

    check("no model turn ran", counter[0] == 0, f"{counter[0]} call(s)")

    messages = state["messages"]
    last = messages[-1]
    check("the turn ends on an assistant message",
          isinstance(last, AIMessage) and bool(last.content), type(last).__name__)
    check("it comes after the tool result",
          isinstance(messages[-2], ToolMessage), type(messages[-2]).__name__)

    found = notices(state)
    check("it carries the job_rejected notice",
          len(found) == 1 and found[0].get("kind") == "job_rejected", str(found))

    text = last.content
    check("it says plainly that nothing ran", "nothing was run" in text.lower(), text[:160])
    check("it names the draft that was declined",
          "water" in text and "sto-3g" in text.lower(), text[:160])
    check("it does not leak an internal task identifier",
          "single_point" not in text and "subtype" not in text, text[:160])
    check("it invites a change rather than closing the exchange",
          "change" in text.lower(), text[:160])

    snapshot = graph.get_state(config)
    check("the turn is really over", snapshot.next == (), str(snapshot.next))
    check("nothing was submitted", not (state.get("active_job_ids") or []),
          str(state.get("active_job_ids")))
    check("the drafting episode is closed", state.get("draft_status") is None,
          str(state.get("draft_status")))
    check("the receipt was consumed", (state.get("pending_rejections") or []) == [],
          str(state.get("pending_rejections")))

    # The one place a rejection deliberately differs from a submission. The
    # message asks the user what to change, and update_job_draft has nothing
    # to amend if the draft went with the decline.
    draft = state.get("job_draft") or {}
    check("the draft survives so it can be amended",
          draft.get("task") == "single_point" and draft.get("method") == "hf", str(draft))

    tool_msg = messages[-2].content
    check("the tool record tells the next turn not to ask again",
          "do not ask again" in tool_msg.lower(), tool_msg[:200])
    check("the tool record forbids resubmitting",
          "do not resubmit" in tool_msg.lower(), tool_msg[:200])

    print("\n== declared follow-up work still hands back to the model ==")
    config = new_thread("qatest_reject_followup")
    park_at_card(config, [submit_call(follow_up=True)])
    pending = pending_approval(config)
    check("the approval card is open", pending is not None, str(pending))
    if pending is not None:
        counter[0] = 0
        graph.invoke(Command(resume={"approved": False}), config)
        state = read_state(config)
        check("the model got the turn back", counter[0] == 1, f"{counter[0]} call(s)")
        found = notices(state)
        check("the decline was still written first", len(found) == 1, str(found))
        decline_at = next((i for i, m in enumerate(state["messages"])
                           if (getattr(m, "additional_kwargs", None) or {}).get("nexus_notice")), -1)
        check("the user saw it before the chained turn ran",
              decline_at != -1 and decline_at < len(state["messages"]) - 1,
              str([type(m).__name__ for m in state["messages"][-4:]]))

    print("\n== a batch mixing a rejection with another tool goes to the model ==")
    config = new_thread("qatest_reject_mixed")
    park_at_card(config, [
        {"name": "check_job_status", "args": {"job_id": "nosuchjob"}, "id": f"x{time.time_ns()}"},
        submit_call(),
    ])
    pending = pending_approval(config)
    check("the approval card is open", pending is not None, str(pending))
    if pending is not None:
        counter[0] = 0
        graph.invoke(Command(resume={"approved": False}), config)
        state = read_state(config)
        check("the model relayed the batch", counter[0] == 1, f"{counter[0]} call(s)")
        check("no app-written decline was published", notices(state) == [], str(notices(state)))
        check("the other tool's result survived in history",
              any(isinstance(m, ToolMessage) and "nosuchjob" in m.content
                  for m in state["messages"]),
              "check_job_status result missing")

    print(f"\n{checks - len(failures)}/{checks} checks passed")
    if failures:
        print("FAILED:")
        for label in failures:
            print(f"  - {label}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
