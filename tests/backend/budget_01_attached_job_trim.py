#!/usr/bin/env python3
"""P5.4: the context budget can shrink an attached job, and says where its
results went.

    PYTHONPATH=$PWD python3 tests/backend/budget_01_attached_job_trim.py

Two findings from the 2026-09 review, both about the same message.

R-037. `_shed_pinned_results` is the last thing the history trim tries: with
everything else already given up, it blanks the current turn's results in
place, leaving a marker that tells the model to re-fetch rather than a hole it
would fill with an invented number. It could only shrink `ToolMessage`s. An
attached job's results do not arrive as a ToolMessage; they arrive as a
synthetic `HumanMessage` built by server/routes/chat.py, carrying a
`job_context_summary` of roughly 20,000 characters. Attach three jobs to one
message and that is three such blocks in one pinned message that nothing could
touch, so the window stayed over budget with nothing left to give and the trim
ended by logging that it could not help. This is the answer to the question
docs/MODEL_CONTEXT_BUDGET.md leaves open, "can the budget be exceeded anyway by
one message": it was yes, by this path.

R-036. The pointer that replaces an already-attached job's results said flatly
that they were "in this conversation above". `_already_attached_job_ids` scans
the full checkpointed history, while the prompt the model sees has been trimmed
to a budget, so on a long conversation the summary being pointed at can have
been trimmed away. The model has no way to check that claim and every reason to
believe it, so it answers from what it can see instead of saying it cannot see
it. The pointer now names the tool that fetches the results back.

Everything here runs in process. No stack, no model.
"""
from __future__ import annotations

import inspect
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "tests"))

from fixtures import check, summary  # noqa: E402


def section(title: str):
    def wrap(fn):
        def run():
            print(f"\n== {title} ==")
            try:
                fn()
            except Exception as exc:  # noqa: BLE001
                check(title, False, f"{type(exc).__name__}: {exc}")
        run.__name__ = fn.__name__
        return run
    return wrap


# One attached job's summary is about 20,000 characters in the conversation
# that motivated the original dedup. Three of them is the case R-037 is about.
FAKE_SUMMARY = "total_energy_hartree -76.0267 " * 700
N_ATTACHED = 3


@section("R-037: an attached job's results can be shrunk like any other result")
def _shed_attachments() -> None:
    from langchain_core.messages import HumanMessage
    from app.agent.graph import _message_tokens, _shed_pinned_results
    from app.agent.state import JOB_ATTACH_PREFIX

    window = [
        HumanMessage(content=f"{JOB_ATTACH_PREFIX.format(jid=f'job{i:02d}')} {FAKE_SUMMARY}")
        for i in range(N_ATTACHED)
    ]
    before = sum(_message_tokens(m) for m in window)
    # Chosen to be comfortably above what the replacement markers themselves
    # cost (about a hundred tokens each) and far below what the summaries
    # cost. A budget below the markers' own total would be asking the trim to
    # do something impossible, and failing that is correct behaviour rather
    # than the defect this checks for.
    budget = 500
    print(f"  {N_ATTACHED} attached jobs in one turn: about {before} tokens, budget {budget}")

    out, used = _shed_pinned_results(list(window), before, budget)
    print(f"  after the trim: about {used} tokens")
    check("the trim gets the window under budget",
          used <= budget, f"{used} tokens against a budget of {budget}")
    check("it did not simply delete the messages",
          len(out) == N_ATTACHED, f"{len(out)} messages left of {N_ATTACHED}")

    blanked = [m for m in out if "were omitted because the conversation is over" in str(m.content)]
    check("every shrunk message says its results were omitted",
          len(blanked) >= N_ATTACHED - 1, f"{len(blanked)} of {N_ATTACHED} carry the marker")
    check("and each marker names the job it lost, so the model can fetch it back",
          all(f"job{i:02d}" in str(out[i].content) for i in range(len(blanked))),
          "; ".join(str(m.content)[:80] for m in out))
    check("the marker names the tool to call, not just the fact of the loss",
          all("check_job_status" in str(m.content) for m in blanked), "")

    # The ToolMessage path must be untouched by this.
    from langchain_core.messages import ToolMessage
    tm = ToolMessage(content=FAKE_SUMMARY, tool_call_id="call_1", name="check_job_status")
    out2, used2 = _shed_pinned_results([tm], _message_tokens(tm), 500)
    check("a plain tool result is still blanked the way it always was",
          used2 <= budget and "omitted because the conversation" in str(out2[0].content), "")


@section("R-036: the pointer says what to do when the results are gone")
def _pointer_wording() -> None:
    from server.routes import chat as chat_routes
    src = inspect.getsource(chat_routes._attached_job_messages)
    check("it no longer asserts the results are visible",
          "already in this conversation above" not in src, "")
    check("it names the tool that fetches them back",
          "check_job_status" in src, "")
    check("and it says why they might be missing",
          "trimmed" in src, "")

    # Built for real, so the wording checked above is the wording produced.
    state = {"messages": [type("M", (), {"content":
             chat_routes._JOB_ATTACH_PREFIX.format(jid="abc123") + " earlier results"})()]}
    msgs = chat_routes._attached_job_messages(state, ["abc123"])
    check("a job already in the history produces exactly one pointer message",
          len(msgs) == 1, str(len(msgs)))
    if msgs:
        content = str(msgs[0].content)
        print(f"  the pointer, as built: {content}")
        check("the pointer is short, not another copy of the summary",
              len(content) < 600, f"{len(content)} characters")
        check("it names the job id it points at", "abc123" in content, content[:120])


@section("the marker is one definition, shared by the route and the graph")
def _shared_marker() -> None:
    from app.agent.state import JOB_ATTACH_MARKER, JOB_ATTACH_PREFIX
    from server.routes import chat as chat_routes
    check("app/agent/state.py owns the marker",
          JOB_ATTACH_PREFIX.startswith(JOB_ATTACH_MARKER), "")
    check("the route uses that definition rather than its own copy",
          chat_routes._JOB_ATTACH_PREFIX == JOB_ATTACH_PREFIX, "")
    graph_src = inspect.getsource(sys.modules["app.agent.graph"])
    check("the graph recognises it through the same name, not a literal",
          "JOB_ATTACH_MARKER" in graph_src, "")


def main() -> None:
    _shed_attachments()
    _pointer_wording()
    _shared_marker()
    summary()


if __name__ == "__main__":
    main()
