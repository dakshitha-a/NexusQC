<!-- artifact: https://claude.ai/artifact/KBBsDm9Mz8jbZZMegquMeL -- re-render with scripts/render_tracker_html.py and re-publish to THIS url -->
# Tracker: plots can be annotated, and a turn never ends in silence

**Opened 2026-09-24.** Four phases. The tracker this replaces is
[`2026-09-named-active-space.md`](trackers/2026-09-named-active-space.md),
which closed on 2026-09-20. **Exactly one tracker is active at a time.**

## Rules (enforced by `scripts/check_tracker.py`)

- Step status is exactly one of `todo` | `in-progress` | `done`.
- A step may be marked `done` **only with an evidence field**: one path that
  exists on disk plus a one-line observed result.
- The tracker edit ships **in the same commit** as the step's final change.
- A phase's `merged` row records the commit hash the stage landed as.

Format for a step row:

```
- [status] P<phase>.<step>: <short name>
  evidence: <path> → "<observed result>"   (required when done)
```

---

## Why this plan exists

In the uracil conversation of 2026-09-24 the user asked the agent to
"annotate the plot with the energies for each method", then said "I don't
see the annotations". The plot tool had no annotation support, and nothing
checked the top-level keys of a plot spec. So the agent's `annotations` list
was stored and silently left out of the image. The agent then worked around
it by putting the numbers into the x-axis labels.

In the same conversation a request for an S1/S2 table sat for 106 seconds.
The model then returned an empty reply, and the graph ended the turn on it.
No log line appeared and no message showed in the chat. The user had to type
"hello?" to get the answer. Underneath that: `extra_body={"think": False}`
is ignored by Ollama 0.32.13's OpenAI endpoint for `qwen3.8:27b`. So every
turn has been paying for hidden reasoning that LangChain drops.

---

## Phase 1: the model call

- [done] P1.1: switch hidden reasoning off at every call site
  evidence: tests/backend/agent_11_reasoning_is_off.py → "LLM_EXTRA_BODY: 0 reasoning chars, 80 completion tokens for a 151-char reply; think:false alone still leaks 238 reasoning chars (176 tokens)"
- [done] P1.2: an empty reply is retried once, then answered visibly
  evidence: tests/backend/agent_10_empty_reply_retry.py → "8/8: empty then real = 2 calls and the real reply; empty twice = the fallback sentence; length-cut and tool-only replies not retried"
- [done] P1.3: every model call logs how long it took
  evidence: app/agent/graph.py → "_timed_invoke logs through uvicorn.error at INFO, WARNING above 60 s; the live line is read back in P4.3"
- merged: -

## Phase 2: annotations on every plot

- [todo] P2.1: `annotations` drawn by `PlotStyle.apply` for every kind
- [todo] P2.2: `value_labels` for custom and comparison plots
- [todo] P2.3: unknown top-level plot spec keys are refused
- [todo] P2.4: tool docstring, context summary and token budget
- merged: -

## Phase 3: the wait indicator

- [todo] P3.1: "Thinking..." shows elapsed seconds
- merged: -

## Phase 4: land it

- [todo] P4.1: README and docs updated
- [todo] P4.2: agent tests pass with reasoning off
- [todo] P4.3: dev stack rebuilt, live turn and browser check
- merged: -
