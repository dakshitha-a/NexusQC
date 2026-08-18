# Model context budget — measured, not assumed

Phase 0 finding that reorders the overhaul's priorities. Reproduce with
`scripts/spikes/spike_model_context.py --models`.

## The headline

**The agent's fixed per-iteration prompt surface is 23,931 tokens. The
effective context window through the endpoint it uses is 16,384. The system
prompt is silently discarded on every single call.**

That is not a hypothesis. Each half was measured separately.

## Half one: what the app sends every iteration

Measured with tiktoken `cl100k_base` against the live `SYSTEM_PROMPT` and the
serialized schemas of all 14 bound tools. Both are re-sent on *every* ReAct
loop iteration, so this is a per-step tax, not a one-off:

| Component | Tokens |
|---|---:|
| `SYSTEM_PROMPT` (22,142 chars) | 4,968 |
| `submit_job` schema alone | 8,391 |
| `generate_job_input` schema | 2,093 |
| remaining 12 tool schemas | 8,479 |
| **Fixed surface, before any conversation history** | **23,931** |

`submit_job` and `generate_job_input` together are 10,484 tokens — 44% of the
whole surface — because their ~220-line docstrings and 35 flat optional
parameters are a second system prompt in all but name.

## Half two: what the endpoint actually accepts

Needle-in-a-haystack probes against `http://localhost:11434/v1/chat/completions`
(the endpoint `app/agent/graph.py` uses), with a distinctive codeword planted
in the prompt and the model asked to repeat it:

| Probe | prompt_tokens reported | Codeword recalled |
|---|---:|---|
| ~11k-token prompt | 10,962 | yes |
| ~26k-token prompt | **16,386** | no |
| ~52k-token prompt | **16,386** | no |
| ~26k, codeword at **start** | 16,386 | **no** |
| ~26k, codeword at **end** | 16,386 | yes |

Two conclusions, both load-bearing:

1. **The window is hard-capped at 16,384 tokens** (16,386 with the chat
   wrapper). Feeding 52k changes nothing — the excess is discarded before the
   model sees it, with no error and no warning.
2. **Truncation drops the front.** Content at the start of the prompt is what
   disappears; content at the end survives. The system prompt is at the front.

Both target models behave identically (`qwen3.8:27b`, `qwen3-coder:30b`), and
both are 262,144-token-capable models — the limit is the deployment, not the
weights.

## The cap cannot be lifted from the client

| Attempt | Result |
|---|---|
| `options={"num_ctx": 32768}` in the `/v1` body | silently ignored, still 16,386 |
| `num_ctx` as a top-level `/v1` field | silently ignored, still 16,386 |
| A Modelfile variant with `PARAMETER num_ctx 32768` | still 16,386 |
| `num_ctx` via the **native** `/api/generate` endpoint | accepted (but the app does not and should not use this endpoint — it would mean giving up the OpenAI-compatible client) |

This is the same failure mode this repo already documented for `keep_alive`,
which the `/v1` layer also drops and which is the entire reason
`app/agent/model_warmer.py` exists. Assuming an option took effect because the
request succeeded is exactly the mistake to avoid here.

The Ollama systemd unit sets no `OLLAMA_CONTEXT_LENGTH`, so 16,384 is this
build's default. Raising it means editing a **root-owned service shared with
every other tenant on this host**, which per `CLAUDE.local.md` is not a
unilateral decision — and it would raise KV-cache memory for everyone.

*(A probe model created during this investigation was removed afterwards; the
shared service is unchanged.)*

## What this means for the overhaul

The context diet in Phase 2 was planned as an optimization. It is not — it is
a correctness fix, and it is the highest-value change in the whole overhaul:

- Right now the model is being handed roughly the last 16,384 tokens of a
  23,931-token preamble. **It never sees its system prompt**, and it sees only
  a truncated tail of its own tool definitions. Behaviour that looks like the
  model ignoring instructions, inventing job types, or fabricating a job id is
  the expected consequence of instructions that were never delivered.
- Every token of docstring prose is displacing something. Moving per-parameter
  help out of `submit_job`'s docstring and into `ParamSpec.ask` — paid only at
  the moment a question is actually asked — is what buys the room back.
- **Budget for Phase 2: the fixed surface must fit in well under 16,384
  tokens**, leaving real room for conversation history. A working target is
  ≤ 6,000 tokens of system prompt plus tool schemas combined, i.e. roughly a
  4× reduction, with `tests/backend/agent_01_token_budget.py` asserting it so
  it cannot regress.
- Mechanical history trimming stays necessary regardless: without it, a long
  conversation pushes the *rest* of the surface out of the window too.

## Open item for the user

Raising `OLLAMA_CONTEXT_LENGTH` on the shared Ollama service (to, say, 32768)
would give immediate headroom and is a one-line systemd override. It affects
every tenant's memory use and requires a service restart that interrupts
in-flight requests, so it is the user's call, not the overhaul's. The Phase 2
diet is worth doing either way — it is what keeps the agent inside a budget
rather than dependent on one.
