#!/usr/bin/env python3
"""Phase 0 verification spike: the context budget the agent rebuild designs to.

    PYTHONPATH=$PWD python3 scripts/spikes/spike_model_context.py [--models]

Answers three questions Phase 2 cannot be designed without:

1. How large is the prompt surface today? The system prompt and the bound
   tool schemas are re-sent on EVERY ReAct iteration, so their combined size
   is a per-step tax, not a one-off. Phase 2's budget test asserts against
   the numbers printed here.
2. Does `num_ctx` actually take effect through Ollama's OpenAI-compatible
   endpoint? This repo has already been bitten once by that layer silently
   dropping an option (`keep_alive`, which is why model_warmer.py exists), so
   the setting is confirmed by observation rather than assumed.
3. Can the target small models reliably emit a tool call whose argument is a
   nested dict? The planned `update_job_draft(fields={...})` depends on it;
   the fallback is flattening to single-field calls.

Token counts use tiktoken when available and fall back to a chars/4
estimate, which is close enough for budgeting. Model probes need Ollama up
and are skipped unless --models is passed.
"""
from __future__ import annotations

import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO))

from app.config import LLM_BASE_URL, LLM_MODEL  # noqa: E402


def count_tokens(text: str) -> tuple[int, str]:
    try:
        import tiktoken
        return len(tiktoken.get_encoding("cl100k_base").encode(text)), "tiktoken/cl100k"
    except Exception:
        return len(text) // 4, "estimate(chars/4)"


def prompt_surface() -> None:
    from app.agent.prompts import SYSTEM_PROMPT
    from app.agent.tools import get_all_tools

    sys_tok, how = count_tokens(SYSTEM_PROMPT)
    print(f"token counter: {how}\n")
    print(f"SYSTEM_PROMPT           {len(SYSTEM_PROMPT):>7,} chars  {sys_tok:>6,} tokens")

    tools = get_all_tools()
    rows = []
    total = 0
    for t in tools:
        # The schema the model actually sees: name, description (docstring)
        # and the JSON parameter schema.
        try:
            schema = {
                "name": t.name,
                "description": t.description,
                "parameters": t.args_schema.model_json_schema() if t.args_schema else {},
            }
            blob = json.dumps(schema)
        except Exception as e:  # a tool that cannot be serialized is itself a finding
            blob = f"{t.name}: UNSERIALIZABLE {e}"
        n, _ = count_tokens(blob)
        total += n
        rows.append((t.name, len(blob), n))

    rows.sort(key=lambda r: -r[2])
    print(f"\n{len(tools)} tools bound on every iteration:")
    for name, chars, n in rows:
        print(f"  {name:<34} {chars:>7,} chars  {n:>6,} tokens")
    print(f"  {'TOTAL':<34} {'':>7}        {total:>6,} tokens")

    per_step = sys_tok + total
    print(f"\nFIXED PER-ITERATION SURFACE: {per_step:,} tokens "
          f"(system prompt + tool schemas, before any conversation history)")
    print(f"  at a 8192-token context that is {100 * per_step / 8192:.0f}% of the window")
    print(f"  at 16384: {100 * per_step / 16384:.0f}%   at 32768: {100 * per_step / 32768:.0f}%")
    print("\nPhase 2 targets: system prompt <= 6 KB, and this total materially lower "
          "(per-param prose moves into ParamSpec.ask, paid only when asked).")


def ollama_get(path: str) -> dict | None:
    root = LLM_BASE_URL.rstrip("/")
    if root.endswith("/v1"):
        root = root[:-3]
    try:
        with urllib.request.urlopen(root + path, timeout=10) as r:
            return json.loads(r.read())
    except Exception:
        return None


def probe_models() -> None:
    print("\n" + "=" * 70)
    print("MODEL PROBES")
    print("=" * 70)
    tags = ollama_get("/api/tags")
    if tags is None:
        print(f"Ollama not reachable at {LLM_BASE_URL} -- skipping model probes.")
        return
    names = sorted(m["name"] for m in tags.get("models", []))
    print(f"models available ({len(names)}):")
    for n in names:
        print(f"  {n}")
    wanted = [LLM_MODEL, "qwen3-coder:30b", "qwen3.8:27b"]
    print("\ntarget models present:")
    for w in wanted:
        print(f"  {w:<22} {'yes' if any(n.startswith(w.split(':')[0]) for n in names) else 'NOT PULLED'}")

    print("\nnum_ctx honored through /v1? (compare reported context length)")
    for w in [n for n in names if any(n.startswith(x.split(':')[0]) for x in wanted)][:2]:
        info = ollama_show(w)
        if info:
            ctx = {k: v for k, v in (info.get("model_info") or {}).items() if "context_length" in k}
            print(f"  {w:<22} model_info context: {ctx or '(not reported)'}")


def ollama_show(model: str) -> dict | None:
    root = LLM_BASE_URL.rstrip("/")
    if root.endswith("/v1"):
        root = root[:-3]
    try:
        req = urllib.request.Request(
            root + "/api/show", data=json.dumps({"name": model}).encode(),
            headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=20) as r:
            return json.loads(r.read())
    except Exception:
        return None


def main() -> int:
    print("=" * 70)
    print("PROMPT SURFACE (paid on every ReAct iteration)")
    print("=" * 70)
    prompt_surface()
    if "--models" in sys.argv:
        probe_models()
    else:
        print("\n(pass --models to probe Ollama for context-length handling)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
