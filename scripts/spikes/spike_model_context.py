#!/usr/bin/env python3
"""Phase 0 verification spike: the context budget the agent rebuild designs to.

    PYTHONPATH=$PWD python3 scripts/spikes/spike_model_context.py [--models] [--truncation] [--draftshape]

`--truncation` is the one that matters and the one to trust: it drives the
app's OWN ChatOpenAI construction with the real system prompt and all bound
tools, plants a needle at the top of the system prompt, grows the
conversation until `prompt_tokens` saturates, and reports whether the needle
survived. An earlier version of this spike estimated the two halves
separately -- tiktoken over a hand-serialized tool schema, plus a raw-HTTP
probe of the window -- and both estimates were wrong in the same direction,
producing a confident and false conclusion. See docs/MODEL_CONTEXT_BUDGET.md's
correction notice. Measure the real thing end to end.

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
    print(f"\nESTIMATED fixed per-iteration surface: {per_step:,} tokens")
    print("  NOTE: this estimate runs ~65% HIGH against what the server actually "
          "counts (measured 14,468 via --truncation). It uses tiktoken's cl100k "
          "encoding over a hand-serialized schema, where the real request is "
          "counted by Qwen's tokenizer over the API's own tools field. Use it to "
          "compare tools against each other, never as the budget number.")
    print("\nPhase 2 targets: system prompt <= 6 KB, and the MEASURED surface "
          "materially under 10,000 tokens (per-param prose moves into "
          "ParamSpec.ask, paid only when asked).")


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


NEEDLE = ("\n\nIMPORTANT OPERATIONAL CODEWORD: TANGERINE-47. "
          "If asked for the codeword, reply with it exactly.\n\n")


def endpoint_for_host() -> str:
    """LLM_BASE_URL points at host.docker.internal for the compose
    deployment, which does not resolve when running on the host itself.
    Fall back to localhost so this spike is runnable from a shell."""
    url = LLM_BASE_URL
    if "host.docker.internal" in url:
        return url.replace("host.docker.internal", "localhost")
    return url


def truncation_probe(model: str | None = None) -> None:
    """The load-bearing measurement: the app's real prompt surface, the real
    window, and what actually gets dropped when the window is exceeded."""
    from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
    from langchain_openai import ChatOpenAI

    from app.agent.prompts import SYSTEM_PROMPT
    from app.agent.tools import get_all_tools

    model = model or LLM_MODEL
    base = endpoint_for_host()
    print("=" * 70)
    print(f"END-TO-END TRUNCATION PROBE  (model={model}, endpoint={base})")
    print("=" * 70)

    llm = ChatOpenAI(model=model, base_url=base, api_key="ollama", temperature=0.1,
                     max_tokens=256, extra_body={"think": False}, timeout=1800, max_retries=0)
    bound = llm.bind_tools(get_all_tools())
    turn = ("Please run a CASSCF calculation on benzene with cc-pVDZ and "
            "explain the orbital character. ")
    ask = ("What is the operational codeword stated in your instructions? "
           "Reply with just the codeword, no tool calls.")

    saturated_at = None
    for n in (0, 6, 14, 30, 60, 100):
        msgs = [SystemMessage(NEEDLE + SYSTEM_PROMPT)]
        for _ in range(n):
            msgs.append(HumanMessage(turn * 6))
            msgs.append(AIMessage("Acknowledged; preparing that calculation. " * 40))
        msgs.append(HumanMessage(ask))
        try:
            r = bound.invoke(msgs)
        except Exception as e:
            print(f"  {n:>3} turns  ERROR {type(e).__name__}: {str(e)[:70]}")
            continue
        used = (r.response_metadata.get("token_usage") or {}).get("prompt_tokens")
        survived = "TANGERINE" in (r.content or "").upper()
        if saturated_at is None and used is not None:
            saturated_at = used
        elif used == saturated_at and n >= 60:
            pass
        print(f"  {n:>3} turns of history  prompt_tokens={used:>6}  "
              f"system-prompt needle {'SURVIVED' if survived else 'LOST'}")
    print("\nRead this as: the fixed surface is the 0-turn number; the window is "
          "where prompt_tokens stops growing; and if the needle survives at "
          "saturation, truncation is dropping history rather than instructions.")


def draft_shape_probe() -> None:
    """Can the target models emit a tool call whose single argument is a
    nested dict? Phase 2's `update_job_draft(fields={...})` depends on it;
    the documented fallback was flattening to one call per field. Both
    shapes are tried against both models on the same three requests."""
    from langchain_core.messages import HumanMessage, SystemMessage
    from langchain_core.tools import tool
    from langchain_openai import ChatOpenAI

    @tool
    def update_job_draft_dict(fields: dict) -> str:
        """Set one or more parameters on the current job draft.
        fields: a mapping of parameter name to value,
        e.g. {"basis": "cc-pVDZ", "method": "casscf"}."""
        return "ok"

    @tool
    def update_job_draft_flat(name: str, value: str) -> str:
        """Set ONE parameter on the current job draft.
        name: the parameter name, e.g. "basis". value: its value, e.g. "cc-pVDZ"."""
        return "ok"

    sys_msg = ("You are preparing a quantum chemistry job. When the user supplies "
               "parameters, record them with the tool. Do not ask questions.")
    cases = ["Use the cc-pVDZ basis set.",
             "Use CASSCF with the cc-pVDZ basis and 6 electrons in 6 orbitals.",
             "Set the charge to -1 and multiplicity to 2."]

    print("=" * 70)
    print("DRAFT TOOL-CALL SHAPE PROBE")
    print("=" * 70)
    base = endpoint_for_host()
    for model in ("qwen3.8:27b", "qwen3-coder:30b"):
        llm = ChatOpenAI(model=model, base_url=base, api_key="ollama", temperature=0.1,
                         max_tokens=400, extra_body={"think": False}, timeout=600, max_retries=0)
        for shape, t in (("dict-arg", update_job_draft_dict), ("flat-arg", update_job_draft_flat)):
            ok, detail = 0, []
            for msg in cases:
                try:
                    r = llm.bind_tools([t]).invoke([SystemMessage(sys_msg), HumanMessage(msg)])
                    calls = r.tool_calls or []
                    ok += bool(calls) and all(isinstance(c.get("args"), dict) and c["args"] for c in calls)
                    detail.append(f"{len(calls)} call(s)" if calls else "NO CALL")
                except Exception as e:
                    detail.append(f"ERR {type(e).__name__}")
            print(f"  {model:17s} {shape:9s} {ok}/{len(cases)} well-formed   [{', '.join(detail)}]")
    print("\nCall COUNT is the tiebreak, not just well-formedness: the flat shape needs "
          "one round trip per field, and each ReAct iteration costs tens of seconds.")


def main() -> int:
    print("=" * 70)
    print("PROMPT SURFACE ESTIMATE (tiktoken -- indicative only, see --truncation)")
    print("=" * 70)
    prompt_surface()
    if "--models" in sys.argv:
        probe_models()
    if "--truncation" in sys.argv:
        print()
        truncation_probe()
    if "--draftshape" in sys.argv:
        print()
        draft_shape_probe()
    if not {"--models", "--truncation", "--draftshape"} & set(sys.argv):
        print("\n(pass --models to list Ollama models, --truncation for the "
              "end-to-end measurement that supersedes the estimate above, "
              "--draftshape for the Phase 2 tool-argument-shape decision)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
