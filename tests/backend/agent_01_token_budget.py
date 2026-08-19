#!/usr/bin/env python3
"""P2.2/P2.4 -- the agent's fixed prompt surface must stay inside its budget.

Every ReAct iteration of every turn pays for the system prompt and the
whole tool-schema block, whether or not the conversation touches any of it.
Phase 0 measured that surface end to end at **14,468 tokens** -- 44% of the
window as it stood then -- and set the Phase 2 target at *materially under
10,000*. See docs/MODEL_CONTEXT_BUDGET.md.

The measurement here is the same one Phase 0 used, and deliberately not a
local estimate: `usage.prompt_tokens` reported by the served model for a
request carrying the real system prompt and the real bound tools. Phase 0
recorded why -- a tiktoken count over a hand-serialized JSON dump of the
tool schemas disagreed with the truth by thousands of tokens, because
neither the tokenizer nor the serialization matches what the API actually
sends. A budget asserted against the wrong number is not a budget.

Needs the configured Ollama endpoint to be up. If it is not, this reports
SKIPPED rather than failing: an unreachable model is not a regression in
the prompt surface, and a red result that means "the server is down"
teaches people to ignore red results.

Run:  PYTHONPATH=$PWD python3 tests/backend/agent_01_token_budget.py
"""
from __future__ import annotations

import sys

from app.agent.prompts import SYSTEM_PROMPT
from app.agent.tools import get_all_tools
from app.config import LLM_BASE_URL, LLM_MODEL

# The Phase 0 baseline and the Phase 2 target, both from
# docs/MODEL_CONTEXT_BUDGET.md.
BASELINE_TOKENS = 14_468
BUDGET_TOKENS = 10_000

# The prompt's own ceiling, from the plan's P2.4. Checked separately from
# the combined surface because the two can regress independently: a prompt
# creeping back toward a job catalog is worth catching even in a month
# where the tool schemas happened to shrink.
PROMPT_BUDGET_BYTES = 6 * 1024

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


def measure_prompt_tokens() -> int | None:
    """`prompt_tokens` for one minimal request carrying the real surface."""
    try:
        from langchain_core.messages import HumanMessage, SystemMessage
        from langchain_openai import ChatOpenAI
    except Exception as exc:
        print(f"  [SKIPPED] langchain_openai unavailable: {exc}")
        return None

    llm = ChatOpenAI(model=LLM_MODEL, base_url=LLM_BASE_URL, api_key="ollama",
                     temperature=0.0, max_tokens=8, extra_body={"think": False},
                     timeout=300, max_retries=0)
    bound = llm.bind_tools(get_all_tools())
    try:
        reply = bound.invoke([SystemMessage(SYSTEM_PROMPT), HumanMessage("hi")])
    except Exception as exc:
        print(f"  [SKIPPED] the model at {LLM_BASE_URL} is not reachable: "
              f"{type(exc).__name__}: {str(exc)[:120]}")
        return None
    usage = reply.response_metadata.get("token_usage") or {}
    return usage.get("prompt_tokens")


def main() -> int:
    print("== the system prompt itself ==")
    print(f"  SYSTEM_PROMPT is {len(SYSTEM_PROMPT):,} bytes")
    check(f"system prompt is under {PROMPT_BUDGET_BYTES:,} bytes",
          len(SYSTEM_PROMPT) <= PROMPT_BUDGET_BYTES,
          f"it is {len(SYSTEM_PROMPT):,}")
    # The catalog the prompt used to carry is the specific thing that must
    # not come back: it duplicated registry2 and went stale silently.
    for banned in ("job_type", "REQUIRED", "active_electrons", "generate_job_input",
                   "submit_job"):
        check(f"the prompt no longer spells out {banned!r}",
              banned not in SYSTEM_PROMPT,
              "the job catalog belongs in registry2, reached via lookup_capabilities")

    print("\n== the tool surface ==")
    tools = get_all_tools()
    names = [t.name for t in tools]
    print(f"  {len(tools)} tools: {', '.join(names)}")
    check("the 38-parameter submit_job schema is gone", "submit_job" not in names)
    check("the four plot tools are consolidated into one",
          len([n for n in names if n.startswith("plot")]) == 1,
          f"plot-ish tools: {[n for n in names if 'plot' in n]}")
    check("the draft trio is bound",
          {"start_job_draft", "update_job_draft", "submit_draft"} <= set(names))
    check("capabilities are lookup-able", "lookup_capabilities" in names)
    widest = max(
        (len((t.args_schema.model_json_schema().get("properties") or {})) if t.args_schema else 0)
        for t in tools)
    print(f"  widest tool schema: {widest} parameters")
    check("no tool takes more than 8 parameters", widest <= 8,
          f"the widest takes {widest}; submit_job used to take 38")

    print(f"\n== the fixed surface, as {LLM_MODEL} counts it ==")
    tokens = measure_prompt_tokens()
    if tokens is None:
        print(f"\n{PASS}/{PASS + FAIL} checks passed (token measurement skipped)")
        return 1 if FAIL else 0
    saved = BASELINE_TOKENS - tokens
    print(f"  prompt_tokens = {tokens:,}  (Phase 0 baseline {BASELINE_TOKENS:,}, "
          f"saved {saved:,} = {100 * saved / BASELINE_TOKENS:.0f}%)")
    check(f"the fixed surface is under {BUDGET_TOKENS:,} tokens",
          tokens < BUDGET_TOKENS, f"it is {tokens:,}")
    check("and is smaller than the Phase 0 baseline", tokens < BASELINE_TOKENS,
          f"{tokens:,} vs {BASELINE_TOKENS:,}")

    total = PASS + FAIL
    print(f"\n{PASS}/{total} checks passed")
    if FAIL:
        print(f"[FAIL] {FAIL} check(s) failed")
        return 1
    print("[PASS] ALL CHECKS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
