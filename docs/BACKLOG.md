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

The CAS recommendation engine's entries were closed out together in September
2026 (`docs/trackers/2026-09-cas-engine-closeout.md`). Ten of them left this
file at once, which is worth explaining rather than leaving as a gap in the
history. Each left through one of three doors: fixed and validated across the
benchmark, settled as a deliberate decision, or measured and written into
`docs/CAS_ENGINE_METHOD.md` as a stated limitation with its number attached. A
limitation reported with a measurement behind it is not an open item, and
`docs/casbench/` holds the measurements.

Two of those entries turned out to be wrong about their own subject, which is
the argument for closing a set of related items together rather than one at a
time. The irreproducible recommendation was blamed on the orbital ranking and
was caused by an unstable SCF reference two stages earlier. And the molecule
said to exceed the refinement cap was not the one that did.

## Open

- **The app-vs-host split in `perf_02_ttft_and_concurrency.py` cannot be
  measured on this host while other people are using the GPU.** The absolute
  figures stand and are what a user waits: about 7s to a first token with four
  people at once, against about 2.5s alone. The ratio that would say how much
  of that is this app's fault does not, because its denominator is a baseline
  measured against a shared card; sampled twice in one run it has come back as
  far apart as 3.05x and 0.95x, and the script now reports the split as
  unavailable rather than asserting one when the two samples disagree by more
  than 1.5x.

  The one systematic flaw that WAS in this repository is fixed: the baseline
  used to fire a synthetic filler string while the app path carried the whole
  tool schema, so the quotient conflated app overhead with prompt size. It now
  sends `app.agent.prompts.SYSTEM_PROMPT` and the real
  `app.agent.tools.get_all_tools()` schema, read from the same source the
  graph binds, so both sides pay for the same payload.

  What is left is the model server's own behaviour and is not addressable
  here. Each concurrent slot needs its own KV cache, and at
  `OLLAMA_CONTEXT_LENGTH=65536` that is roughly 17 GB per slot against a 32 GB
  card already holding 16 GB of weights. The levers are the context length,
  the card, or an inference server that pages the KV cache instead of
  reserving it per slot. Ollama here is a root-owned systemd service shared
  with other tenants, so changing it is the operator's call. Settling the
  split for real needs the GPU to itself.
