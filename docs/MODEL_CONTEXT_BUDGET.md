# Model context budget — measured end to end

Phase 0 finding for the agent rebuild. Reproduce with
`scripts/spikes/spike_model_context.py --models --truncation`.

> **Correction notice.** An earlier draft of this document claimed the fixed
> prompt surface was 23,931 tokens against a hard 16,384-token window, and
> concluded that the system prompt was being silently discarded on every call.
> **That was wrong**, and it is recorded here rather than quietly deleted
> because the way it was wrong is instructive. Two separate measurement errors
> pointed the same direction, which is exactly when a wrong conclusion feels
> most convincing. See *How the earlier claim went wrong* below.

## What is actually true

Measured by driving the app's own `ChatOpenAI` construction with its real
`SYSTEM_PROMPT` and all 14 bound tools, and reading `usage.prompt_tokens` back
from the server — not by estimating either half separately.

| Quantity | Value |
|---|---:|
| Fixed surface: system prompt + 14 tool schemas, as the API actually counts it | **14,468 tokens** |
| Effective context window (saturation point, `qwen3.8:27b` via `/v1`) | **~32,692 tokens** |
| Headroom left for conversation history | **~18,200 tokens** |

And the behaviour when the window *is* exceeded:

| History size | prompt_tokens | Needle placed at the top of the system prompt |
|---|---:|---|
| none | 14,468 | survived |
| ~6 turns | 17,222 | survived |
| ~14 turns | 20,894 | survived |
| ~30 turns | 28,238 | survived |
| ~60 turns | 32,697 (saturated) | **lost** |
| ~100 turns | 32,697 (saturated) | **lost** |

**Below saturation the system prompt is intact; at saturation it can be
dropped.** So the instructions do survive a normal short conversation — the
original alarm was wrong about *every call* — but a long session that fills
the window genuinely can lose them.

Treat the saturation row as a boundary rather than a clean rule. Two runs of
this probe differing only in filler text saturated at 32,692 and 32,697
tokens and disagreed about whether the needle survived. That is what a
truncation edge looks like: whether the system prompt is cut depends on
exactly where the boundary lands in it, which is not something application
code should be relying on either way.

## How the earlier claim went wrong

Worth reading before trusting any similar measurement in this repo.

1. **The 16,384 figure was an artifact of model-load state.** Raw HTTP probes
   with a single oversized user message reported `prompt_tokens` pinned at
   exactly 16,386, repeatably, across two models and two prompt sizes — which
   looked exactly like a hard server cap. It was not: the same endpoint later
   accepted 32,692 tokens from the same models. Ollama sizes a model's context
   when it loads it and reuses that resident instance, so a probe can measure
   whichever window the currently-loaded instance happens to have. A number
   that reproduces is not automatically a number that generalises.
2. **The 23,931 figure over-counted the tools by 65%.** It came from
   tiktoken's `cl100k_base` over a hand-serialized JSON dump of each tool's
   name, description and parameter schema. The real payload is counted by
   Qwen's tokenizer, in the API's own `tools` field, with different
   serialization. Estimating a token count with the wrong tokenizer over the
   wrong serialization of the right content is a compounding error.

Both errors exaggerated the problem in the same direction, and the resulting
story — "the model never sees its instructions" — was a tidy explanation for
observed misbehaviour. It was a false one. The lesson is the one this repo
already applies to engine output parsers: **measure the real thing end to
end, not two halves you then add together.**

## What is still worth acting on

The corrected numbers are undramatic but not benign:

- **44% of the window is spent before the conversation starts.** 14,468
  tokens of every single ReAct iteration is fixed overhead, and a turn can
  involve several iterations.
- `submit_job` and `generate_job_input` dominate that surface. Their ~220-line
  docstrings and 35 flat optional parameters are a second system prompt in all
  but name, and per-parameter prose is paid on every iteration whether or not
  any parameter is being discussed.
- **~18,200 tokens for history is roughly 30–60 turns**, and the app has no
  trimming at all today. A session that reaches the window loses its oldest
  content silently, with no digest left behind — and, as the saturation rows
  show, can lose the system prompt itself at the boundary. Mechanical
  trimming in Phase 2 is what makes that degradation deliberate and legible
  instead of an accident of where the cut falls.
- Phase 2's budget target: keep the fixed surface **materially under 10,000
  tokens** (moving per-parameter help into `ParamSpec.ask`, paid only when a
  question is actually asked), with
  `tests/backend/agent_01_token_budget.py` asserting it so it cannot regress.

## One thing the earlier draft got right

`num_ctx` **cannot be set from the client** through the `/v1` endpoint —
neither as `options={"num_ctx": …}` nor as a top-level field, and a Modelfile
`PARAMETER num_ctx` did not visibly change the resident instance's behaviour
either. This is the same silent-drop already documented for `keep_alive`,
which is why `app/agent/model_warmer.py` exists. Any future attempt to control
the window from application code should be verified by observation rather than
assumed from a successful response.

The Ollama systemd unit sets no `OLLAMA_CONTEXT_LENGTH`. Raising it would mean
editing a root-owned service shared with every other tenant on this host —
per `CLAUDE.local.md`, not a unilateral decision, and not one this overhaul
needs to make: fitting comfortably inside the window is better engineering
than depending on a larger one.

*(A probe model created during this investigation was removed afterwards; the
shared service is unchanged.)*
