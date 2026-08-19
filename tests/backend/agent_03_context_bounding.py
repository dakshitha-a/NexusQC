#!/usr/bin/env python3
"""P2.5 -- a long conversation stays inside the context window.

The app had no history bound at all: every turn sent the whole thread, so a
long enough conversation eventually exceeded the window, and what Ollama
drops when that happens is the *front* of the request -- the system prompt
(measured in docs/MODEL_CONTEXT_BUDGET.md). The agent would go on
answering, without its instructions, and nothing would report an error.

Bounding is mechanical: the most recent `LLM_HISTORY_WINDOW` messages, plus
a digest line built from AgentState. Not an LLM-written summary -- that
costs an extra model call per turn and is one more place a job id can be
invented, which is the failure `_looks_fabricated` already exists to catch.

Two things are checked that a naive implementation gets wrong:

- **The cut cannot fall mid-tool-round.** An OpenAI-compatible endpoint
  rejects a ToolMessage whose originating assistant tool_call is absent
  from the same request, so a window starting just after an AIMessage's
  tool_calls is a 400, not a shorter conversation.
- **The digest only appears when something was actually dropped**, so a
  short conversation is not told its history was trimmed.

The token measurement runs against the served model when it is reachable
and is skipped, not failed, when it is not.

Run:  PYTHONPATH=$PWD python3 tests/backend/agent_03_context_bounding.py
"""
from __future__ import annotations

import sys

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from app.agent.graph import _digest_line, _trim_history
from app.config import LLM_HISTORY_WINDOW, LLM_NUM_CTX

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


def build_thread(turns: int) -> list:
    """A conversation shaped like a real one: every turn a user message, an
    assistant tool call, its result, and an assistant reply."""
    messages: list = []
    for i in range(turns):
        messages.append(HumanMessage(content=f"Turn {i}: please run something. " * 12))
        call_id = f"call_{i}"
        messages.append(AIMessage(content="", tool_calls=[
            {"name": "check_job_status", "args": {}, "id": call_id}]))
        messages.append(ToolMessage(content=f"Result for turn {i}. " * 30,
                                    tool_call_id=call_id))
        messages.append(AIMessage(content=f"Here is what turn {i} found. " * 20))
    return messages


def orphaned_tool_messages(messages: list) -> list[str]:
    """Tool results in `messages` with no matching tool_call in the same
    list -- the shape an OpenAI-compatible endpoint rejects outright."""
    offered = set()
    orphans = []
    for m in messages:
        for tc in getattr(m, "tool_calls", None) or []:
            offered.add(tc["id"])
        if getattr(m, "type", "") == "tool" and m.tool_call_id not in offered:
            orphans.append(m.tool_call_id)
    return orphans


def main() -> int:
    print("== the window is bounded ==")
    short = build_thread(3)
    check("a short conversation is passed through whole",
          _trim_history(short) == short,
          f"{len(_trim_history(short))} of {len(short)} kept")

    long_thread = build_thread(60)          # 240 messages
    trimmed = _trim_history(long_thread)
    check(f"a long one is cut to at most {LLM_HISTORY_WINDOW} messages",
          len(trimmed) <= LLM_HISTORY_WINDOW,
          f"{len(trimmed)} kept from {len(long_thread)}")
    check("keeping the most recent, not the oldest",
          trimmed[-1] is long_thread[-1], "the last message was not preserved")

    print("\n== the cut never orphans a tool result ==")
    # Every possible cut point, not just the one this thread happens to
    # produce: the window lands wherever the conversation's shape puts it.
    bad = []
    for n in range(1, 120):
        window = _trim_history(build_thread(n))
        orphans = orphaned_tool_messages(window)
        if orphans:
            bad.append((n, orphans))
    check("no thread length produces an orphaned tool result",
          not bad, f"orphans at thread lengths: {[n for n, _ in bad[:5]]}")

    print("\n== the digest states only what the app already knows ==")
    state = {
        "molecule": {"name": "water", "formula": "H2O"},
        "job_draft": {"task": "opt", "subtype": "min", "method": "hf"},
        "active_job_ids": ["aaaaaaaaaaaa", "bbbbbbbbbbbb"],
    }
    digest = _digest_line(state)
    check("it names the active molecule", "water" in digest, digest or "")
    check("the draft in progress", "opt/min" in digest, digest or "")
    check("and the real job ids", "bbbbbbbbbbbb" in digest, digest or "")
    check("an empty conversation gets no digest at all",
          _digest_line({}) is None, f"got {_digest_line({})!r}")
    many = _digest_line({"active_job_ids": [f"job{i:09d}" for i in range(12)]})
    check("a long job list is summarized rather than dumped",
          "and 7 earlier" in many, many or "")

    print(f"\n== measured against the served model (num_ctx={LLM_NUM_CTX:,}) ==")
    # Driven through `_agent_node` itself, not through a hand-assembled
    # message list. Assembling one here would have hidden the bug this
    # check actually found: the digest was originally sent as a *second*
    # SystemMessage, which Ollama rejects with `system message must be at
    # the beginning` -- so every conversation long enough to be trimmed,
    # and only those, would have failed in production.
    try:
        from app.agent.graph import _agent_node

        long_state = {**state, "messages": build_thread(60)}
        out = _agent_node(long_state)
        check("a 240-message conversation completes a real turn",
              bool(out.get("messages")), f"got {out!r}")
        reply = out["messages"][0]
        used = (reply.response_metadata.get("token_usage") or {}).get("prompt_tokens")
        print(f"  it sends {used:,} prompt tokens")
        check("which fits inside the requested window",
              used is not None and used < LLM_NUM_CTX,
              f"{used} vs num_ctx {LLM_NUM_CTX}")
        check("with real room left for the reply",
              used is not None and used < LLM_NUM_CTX * 0.75,
              f"{used} is more than three quarters of {LLM_NUM_CTX}")
    except Exception as exc:
        # Only an unreachable server is a skip. Anything else -- a rejected
        # message shape, a bad parameter -- is the failure this exists for,
        # and reporting it as "skipped" would hide it exactly when it
        # matters.
        text = str(exc).lower()
        if "connect" in text or "refused" in text or "timed out" in text:
            print(f"  [SKIPPED] the served model is not reachable: "
                  f"{type(exc).__name__}: {str(exc)[:120]}")
        else:
            check("a 240-message conversation completes a real turn", False,
                  f"{type(exc).__name__}: {str(exc)[:200]}")

    total = PASS + FAIL
    print(f"\n{PASS}/{total} checks passed")
    if FAIL:
        print(f"[FAIL] {FAIL} check(s) failed")
        return 1
    print("[PASS] ALL CHECKS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
