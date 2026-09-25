<!-- artifact: https://claude.ai/artifact/KBBsDm9Mz8jbZZMegquMeL -- re-render with scripts/render_tracker_html.py and re-publish to THIS url -->
# Closed Tracker: plots can be annotated, and a turn never ends in silence

**Closed 2026-09-24. Eleven steps in four phases, all done.**
No tracker is active until the next plan begins.

**Opened 2026-09-24.** Four phases. The tracker this replaces is
[`2026-09-named-active-space.md`](2026-09-named-active-space.md),
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
- merged: 50f96f9

## Phase 2: annotations on every plot

- [done] P2.1: `annotations` drawn by `PlotStyle.apply` for every kind
  evidence: tests/backend/plot_07_annotations.py → "25/25: a column resolves by label, first line, number-valued label or slot; a refused note leaves no figure open (it left one before); several histogram panels get it once; the user's stored 10-note plot redraws with every note placed (looked at)"
- [done] P2.2: `value_labels` for custom and comparison plots
  evidence: tests/backend/plot_07_annotations.py → "10 levels labels equal the 10 drawn uracil values at .2f, each at its tick's right end; bar gaps get none; real-job plot through the tool reads correctly (looked at)"
- [done] P2.3: unknown top-level plot spec keys are refused
  evidence: tests/backend/plot_07_annotations.py → "'annotation' refused naming the valid keys; plot_02..06 (103 checks), agent_02 (37) and agent_08 (15) still pass"
- [done] P2.4: tool docstring, context summary and token budget
  evidence: tests/backend/agent_01_token_budget.py → "fixed surface 9,267 tokens (was 9,151) against the 10,000 budget; context_summary lists labels and notes; edit with null removes them"
- merged: d1336ab

## Phase 3: the wait indicator

- [done] P3.1: "Thinking..." shows elapsed seconds
  evidence: tests/frontend/plots_03_annotations_live.spec.mjs → "with the message POST held 7 s the indicator read 'Thinking... 5 s' (screenshot looked at); a sub-3 s wait shows no count"
- merged: e460e5a

## Phase 4: land it

- [done] P4.1: README and docs updated
  evidence: README.md → "plot text paragraph and a slow/empty reply paragraph; ARCHITECTURE.md and MODEL_CONTEXT_BUDGET.md carry the reasoning measurement and the empty-reply rule"
- [done] P4.2: agent tests pass with reasoning off
  evidence: tests/backend/agent_02_draft_flow.py → "37/37 against the served model; chain_01 27, reject_01 24, submit_01 27, agent_08 15 all pass; agent_11 shows 0 reasoning chars"
- [done] P4.3: dev stack rebuilt, live turn and browser check
  evidence: tests/frontend/plots_03_annotations_live.spec.mjs → "stack on e460e5a; a real turn chose value_labels, the plot loaded inline (2400 px) with values on the levels; 7/7; container log shows 'agent: model call took 11.6s for a 13-message prompt'"
- merged: f54fd9e
