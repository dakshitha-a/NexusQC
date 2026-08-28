#!/usr/bin/env python3
"""The prompt's front stays put, so the served model can reuse its cache.

    PYTHONPATH=$PWD python3 tests/backend/trim_01_stable_prefix.py

An inference server reuses the KV cache for however much of a prompt
matches the previous one from the front. So a prompt that only grew is
nearly free to process, while one whose start moved by a single message is
reprocessed in full. Measured on this host against the real system prompt
and all sixteen tool schemas, at 31,727 prompt tokens:

    identical prompt again          0.31s
    messages appended to the end    0.57s
    window slid by one exchange    14.85s
    digest added to system prompt  16.12s

The old `_trim_history` took `messages[-40:]`, so every conversation past
forty messages moved its start by one on every append, and every agent step
paid the full reprocess. The digest line was appended to the system message,
which is worse still: it changes whenever a draft gains a parameter, and a
change that early invalidates the tool schemas too.

None of this is visible from the outside. The answers were correct, just
slow, and slow in a way that looked like the shared GPU. So it is pinned
here rather than left to be rediscovered.

What this checks:

- appending messages does not move the window start, for a run of turns;
- when the start does move, it moves by a whole block, and forward;
- the token budget is still respected, which is the property that was
  protecting the context window before any of this;
- the digest is not in the system message and is last;
- and, the one that matters most, a `submit_draft` tool call and its result
  still survive a trim. `_trim_history` has a documented history of eating
  those: two turns in a row were cut off before they could emit the call,
  so the approval card simply never appeared and nothing logged a thing.

Pure functions over synthetic messages. No model, no graph, no server.
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO))

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage  # noqa: E402

from app.agent.graph import (  # noqa: E402
    _digest_line, _history_token_budget, _message_tokens, _trim_history, build_prompt_messages,
)
from app.config import LLM_HISTORY_FLOOR, LLM_HISTORY_STEP, LLM_HISTORY_WINDOW  # noqa: E402

failures: list[str] = []
checks = 0


def check(label: str, ok: bool, detail: str = "") -> None:
    global checks
    checks += 1
    if ok:
        print(f"  [PASS] {label}")
    else:
        print(f"  [FAIL] {label}" + (f" -- {detail}" if detail else ""))
        failures.append(label)


def conversation(n: int, big: bool = False) -> list:
    """n alternating messages, each tagged with its index so the window's
    start can be identified by content rather than by object identity."""
    body = ("x" * 4000) if big else "short"
    out = []
    for i in range(n):
        if i % 2 == 0:
            out.append(HumanMessage(content=f"m{i} {body}"))
        else:
            out.append(AIMessage(content=f"m{i} {body}"))
    return out


def first_index(window: list) -> int:
    return int(str(window[0].content).split()[0][1:])


def main() -> int:
    print("\n== appending does not move the window's start ==")
    # Deliberately started past the window, which is the only regime where
    # any of this applies. Below it nothing is trimmed and the prompt grows
    # by appending anyway.
    # Aligned to a block boundary, so the run of appends below sits inside
    # one block. The guarantee is that the start moves at most once per
    # LLM_HISTORY_STEP appends, not that it never moves in an arbitrary run.
    base = LLM_HISTORY_WINDOW + LLM_HISTORY_STEP
    starts = []
    for extra in range(LLM_HISTORY_STEP):
        window = _trim_history(conversation(base + extra))
        starts.append(first_index(window))
    check(f"the start held still across {LLM_HISTORY_STEP} appends",
          len(set(starts)) == 1, f"starts={starts}")

    print("\n== and when it moves, it moves by a whole block, forwards ==")
    moved = _trim_history(conversation(base + LLM_HISTORY_STEP))
    check("the start advanced by exactly one step",
          first_index(moved) - starts[0] == LLM_HISTORY_STEP,
          f"{starts[0]} -> {first_index(moved)}")
    walk = [first_index(_trim_history(conversation(base + k)))
            for k in range(0, LLM_HISTORY_STEP * 4)]
    check("it never goes backwards", all(b >= a for a, b in zip(walk, walk[1:])),
          f"walk={walk}")

    print("\n== a short conversation is not trimmed at all ==")
    short = conversation(LLM_HISTORY_WINDOW - 4)
    check("every message survives", len(_trim_history(short)) == len(short),
          f"{len(_trim_history(short))} of {len(short)}")

    print("\n== the token budget is still what bounds the size ==")
    # Messages large enough that the count-based window blows the budget,
    # which is the case the block cut must not be able to leave over.
    heavy = conversation(LLM_HISTORY_WINDOW * 3, big=True)
    window = _trim_history(heavy)
    used = sum(_message_tokens(m) for m in window)
    budget = _history_token_budget()
    check("the trimmed window fits the budget",
          used <= budget or len(window) <= LLM_HISTORY_FLOOR,
          f"{used} tokens vs budget {budget}, {len(window)} messages")
    check("and it did not trim below the floor", len(window) >= min(LLM_HISTORY_FLOOR, len(heavy)),
          f"{len(window)} messages")

    print("\n== a tool round trip survives a trim ==")
    # The failure this guards against is specific and was real: a cut that
    # lands mid-round-trip leaves a ToolMessage whose originating call is
    # gone, which an OpenAI-compatible endpoint rejects with a 400 rather
    # than a shorter conversation.
    messages = conversation(LLM_HISTORY_WINDOW * 2)
    messages += [
        AIMessage(content="", tool_calls=[{"name": "submit_draft", "args": {}, "id": "tc1"}]),
        ToolMessage(content="Submitted (user-approved): id=abc123abc123", tool_call_id="tc1"),
    ]
    window = _trim_history(messages)
    has_call = any(getattr(m, "tool_calls", None) for m in window)
    has_result = any(isinstance(m, ToolMessage) for m in window)
    check("the submit_draft call survived", has_call, "the call was trimmed away")
    check("so did its result", has_result, "the result was trimmed away")
    check("and no result is left orphaned at the front",
          not isinstance(window[0], ToolMessage), type(window[0]).__name__)

    print("\n== the digest is last, and not in the system prompt ==")
    state = {
        "messages": conversation(base),
        "molecule": {"name": "water", "formula": "H2O"},
        "job_draft": {"task": "single_point", "method": "hf"},
        "active_job_ids": ["abc123abc123"],
    }
    prompt = build_prompt_messages(state)
    digest = _digest_line(state)
    check("a digest is produced for a trimmed conversation", bool(digest), str(digest))
    check("the system message is the bare system prompt",
          isinstance(prompt[0], SystemMessage) and "still holds" not in prompt[0].content,
          prompt[0].content[-80:])
    check("the digest is the last message", prompt[-1].content == digest,
          str(prompt[-1].content)[:80])
    check("it is a user-role message, since a second system message is rejected",
          isinstance(prompt[-1], HumanMessage), type(prompt[-1]).__name__)
    check("it says it is not from the user",
          "not from the user" in (digest or ""), str(digest)[:80])

    print("\n== an untrimmed conversation carries no digest ==")
    prompt = build_prompt_messages({**state, "messages": conversation(6)})
    check("nothing is appended", not isinstance(prompt[-1], HumanMessage)
          or "still holds" not in prompt[-1].content, str(prompt[-1].content)[:80])

    print(f"\n{checks - len(failures)}/{checks} checks passed")
    if failures:
        print("FAILED:")
        for label in failures:
            print(f"  - {label}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
