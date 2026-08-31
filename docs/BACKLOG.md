# Backlog

The living record of unimplemented bugs and features. Kept short deliberately.
This is a list to work from, not an investigation report. When an item needs
more explanation than a line or two, that reasoning belongs in the commit that
closes it, not here.

## History

This replaces `docs/ROADMAP.md` and the four `docs/e2e-*-2026-08-16*.md` /
`docs/e2e-*-2026-08-17.md` documents, retired once the last two items they
tracked (FR-2's higher-resolution viewer capture, and the Ketcher chunk-weight
reduction) were implemented and verified live. Their full investigation,
findings, the ranked fix plan, and what was checked live versus by inspection
only, is preserved in git history rather than carried forward. To recover one:

```
git log --all --full-history -- docs/ROADMAP.md   # find the last commit that has it
git show <that-commit-sha>:docs/ROADMAP.md          # print its content
```

A fresh testing pass is expected to populate this file going forward, superseding
the 2026-08-16/17 pass's results.

The 10-phase registry v2/agent-rebuild overhaul (`docs/trackers/2026-08-job-system-overhaul.md`, all 72
steps done as of 2026-08-20) retired the `submit_job` tool this file's own
"Open" section used to name. Replaced by `start_job_draft`/
`update_job_draft`/`submit_draft`, whose ready-draft response now always
carries an explicit "NEXT STEP: ... call submit_draft now" instruction,
resolving the skipped-submission problem that item described. Recovered the
same way as `docs/ROADMAP.md` above if the original wording is ever wanted.

## Open

- **Four people at once wait about 7s for a first token, against about 2.5s
  alone.** Worth improving, but the cause is not what this entry used to say.

  It claimed the app roughly doubles the model server's own concurrency
  penalty (app 5.04x against the server's 2.12x). That specific figure does
  not reproduce. Pooled over three bursts of four, four consecutive runs put
  the app's multiplier on the server's penalty at 1.05x, 0.99x, 1.06x and
  1.86x -- so the honest reading is "somewhere between nothing and a bit
  under twice", not "double", and the fourth of those is a reminder not to
  call three agreeing runs a result. The mechanism
  that would have explained a doubling was a process-global graph lock
  serializing every conversation's turn for the full duration of its LLM
  streaming, and that was replaced by a per-conversation lock some time ago
  (see the Locking comment in `app/agent/graph.py`); two turns on different
  conversations no longer contend at all.

  The old figure came from a measurement that could not support it: a ratio of
  ratios over four medians of three to six samples each, on a machine shared
  with other tenants. Across six runs inside one hour the server alone
  measured 1.63x to 2.80x and the app 1.82x to 5.87x, which swung their
  quotient from 1.08x to 2.84x against a 1.5x threshold. `perf_02` now pools
  three bursts on both sides and samples the baseline before and after the
  app's own, which is what makes its verdict repeatable.

  What is left is the model server's own behaviour, and it is the dominant
  term. Four concurrent requests straight at it show partial batching that
  degrades: first tokens at 1.54s, 2.08s, 3.17s and 4.35s against 1.52s for
  one request alone.

  README.md already explains why, and the explanation holds up: each
  concurrent slot needs its own key/value cache, and at this model's shape a
  64k-token context is roughly 17 GB of it, so a 32 GB card carrying 16 GB of
  weights has room for about one such slot. This host does set
  `OLLAMA_CONTEXT_LENGTH=65536`, which is what makes each slot that large.
  So the lever is the context length, the card, or an inference server that
  pages the KV cache rather than reserving it per slot -- not anything in
  this repository. Ollama here is also a root-owned systemd service shared
  with other tenants, so changing it is the operator's call.

  One caveat on the ratio itself: the baseline fires a synthetic filler
  prompt, while the app path runs a real agent turn carrying a
  66k-character tool schema. Prompt size measurably moves the server's own
  ratio (1.50x at 48k characters, 2.33x at 103k), so the quotient conflates
  app overhead with prompt size and should be read as an estimate. Making the
  two workloads comparable would sharpen it, and is the next thing to do here.
