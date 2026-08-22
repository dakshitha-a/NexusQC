# Model context budget, measured end to end

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
from the server, not by estimating either half separately.

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
dropped.** So the instructions do survive a normal short conversation, the
original alarm was wrong about *every call*, but a long session that fills
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
   exactly 16,386, repeatably, across two models and two prompt sizes, which
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
story, "the model never sees its instructions", was a tidy explanation for
observed misbehaviour. It was a false one. The lesson is the one this repo
already applies to engine output parsers: **measure the real thing end to
end, not two halves you then add together.**

## Where this landed. Phase 2, done

The overhaul that this finding motivated is now complete, and the diet
worked. Re-run live on 2026-08-20 (`tests/backend/agent_01_token_budget.py`,
same measurement method as Phase 0, real `usage.prompt_tokens` from the
served model, not an estimate):

| Quantity | Phase 0 | Now |
|---|---:|---:|
| Fixed surface (system prompt + tool schemas) | 14,468 tokens | **5,941 tokens** |
| Tool count | `submit_job`/`generate_job_input` plus others | **13**, none over 7 parameters |
| System prompt size | (folded into the above) | 5,067 bytes |

That's a 59% cut, and it came from replacing the thing that was actually
expensive rather than trimming prose around the edges: `submit_job`'s
~220-line docstring and 35 flat optional parameters are gone entirely,
replaced by `start_job_draft`/`update_job_draft`/`submit_draft`, whose
per-parameter help lives in `ParamSpec.ask` and is paid only when a question
is actually asked. Not on every single ReAct iteration regardless of
whether anyone's discussing that parameter. The four separate plotting
tools also collapsed into one `plot(kind=...)`.

5,941 is comfortably under the Phase 2 target of "materially under 10,000,"
and the budget test above asserts it directly so a future change can't drift
back without the test going red first.

None of this touches the history-window math below, **~18,200 tokens of
headroom is still roughly 30–60 turns** at the un-widened context length.
There is now a mechanical cap (`QC_AGENT_LLM_HISTORY_WINDOW`, default 40
messages, plus a one-line digest of what got trimmed away, see
CONFIGURATION.md), which bounds runaway growth in message *count*. It
doesn't bound token count directly, though, so a session with unusually
long tool outputs in its recent history could still approach the token
ceiling and, at the very edge, lose the system prompt itself, same as the
saturation table shows. What Phase 2 fixed is how much of the window a turn
burns before the conversation even starts, not how the window fills up once
it does.

## One thing the earlier draft got right

`num_ctx` **cannot be set from the client** through the `/v1` endpoint.
Neither as `options={"num_ctx": …}` nor as a top-level field, and a Modelfile
`PARAMETER num_ctx` did not visibly change the resident instance's behaviour
either. This is the same silent-drop already documented for `keep_alive`,
which is why `app/agent/model_warmer.py` exists. Any future attempt to control
the window from application code should be verified by observation rather than
assumed from a successful response.

The Ollama systemd unit sets no `OLLAMA_CONTEXT_LENGTH`, so 32,768 is this
build's default. `ollama ps` reports `CONTEXT 32768` for the resident model,
matching the measured saturation.

*(A probe model created during this investigation was removed afterwards; the
shared service is unchanged.)*

## Raising the window, done, 2026-08-18

`OLLAMA_CONTEXT_LENGTH=65536` is in effect on this host. Verified after the
operator applied it:

| Check | Result |
|---|---|
| `systemctl show ollama.service -p Environment` | `OLLAMA_CONTEXT_LENGTH=65536` |
| `ollama ps` | `CONTEXT 65536`, `PROCESSOR 100% GPU`, no CPU spill |
| GPU 0 memory | 22,284 MiB used of 32,760, **9,973 MiB free** (predicted ~24 GB) |
| Truncation probe, 60 turns | 42,008 prompt tokens (was 32,697, previously saturated) |
| Truncation probe, 100 turns | 60,368 prompt tokens, system prompt **survived**; no saturation reached |
| Production stack after restart | healthy; a real request through `nexusqc_prod-api-1` returns cleanly |

So the fixed surface is now 14,468 of 65,536 tokens, **22% rather than 44%**,
with roughly 51,000 tokens for conversation history, and the truncation edge
that could cut the system prompt is out of reach of any realistic session.

This does not retire the Phase 2 diet. A 14,468-token preamble is still paid on
every ReAct iteration, and several iterations make one turn; the point of the
diet is that the agent fits on any host, not only on one that has been tuned
for it.

### How it was applied (for another host, or to undo)

It cannot be done from the application account, `sudo` requires a password
there, so these are run directly:

```bash
sudo mkdir -p /etc/systemd/system/ollama.service.d
printf '[Service]\nEnvironment="OLLAMA_CONTEXT_LENGTH=65536"\n' \
  | sudo tee /etc/systemd/system/ollama.service.d/context.conf
sudo systemctl daemon-reload && sudo systemctl restart ollama
```

Confirm afterwards, once one request has loaded the model:

```bash
ollama ps          # CONTEXT should read 65536, PROCESSOR still 100% GPU
PYTHONPATH=$PWD python3 scripts/spikes/spike_model_context.py --truncation
```

**Headroom.** Before the change the GPU holding the model (the service is
pinned to `CUDA_VISIBLE_DEVICES=0`) showed 20,356 MiB of 32,760 in use at a
32,768-token context. Roughly 17 GB of weights plus ~3.3 GB of KV cache and
overhead. Doubling the context was predicted to land near 24 GB; it landed at
22,284 MiB, leaving 9,973 MiB free.

Watch `PROCESSOR` in `ollama ps` after any further increase. A split such as
`70%/30% CPU/GPU` instead of `100% GPU` means the KV cache no longer fits and
the model is spilling into host memory, which is far worse than a smaller
window, drop to 49152 in that case.

**What the restart costs.** It drops in-flight LLM requests: a lab user
mid-turn on the production stack sees that turn fail. It does **not** touch
running calculations, jobs are detached subprocesses that never talk to
Ollama, and it deletes nothing. The model unloads, so the next request pays a
cold load (~11 s) unless `model_warmer.py` gets there first. Pick a quiet
moment: `docker logs --since 15m nexusqc_prod-api-1` showing only
`/api/health` lines means nobody is mid-conversation.

To undo: `sudo rm /etc/systemd/system/ollama.service.d/context.conf`, then
reload and restart the same way.

Raising the window does not retire the Phase 2 diet. Fitting comfortably
inside the context is what keeps the agent working on any host; a larger
window is headroom, not a substitute.
