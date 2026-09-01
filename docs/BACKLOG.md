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

- **A pes_1d scan dispatches its non-initial images twice.** A 3-point water
  scan produces five sub-jobs, not three: `children.jsonl` holds five ids,
  and reading each one's `params["_scan_index"]` gives `[0, 1, 1, 2, 2]`.
  Image 0 (the initial wave) is dispatched once; every image the
  orchestrator tops up afterwards is dispatched twice.

  It is invisible in the UI, which is presumably why it has survived:
  `GET /api/jobs/{id}/children` returns three rows, so the frame slider and
  the scan plot look right. The cost is real anyway. Each duplicate is a
  genuine PySCF run occupying a scheduler slot, and a genuine job directory
  counted against the owner's quota, so a 50-point scan pays for about 99
  images' worth of compute and disk to show 50.

  Reproduced directly against `app/chemistry/jobs/scan_orchestrator.py`'s
  top-up loop with no sharing involved: submit a scan through
  `submit_scan`, wait for every child to go terminal, let the orchestrator
  settle, then read the manifest. Almost certainly the top-up dispatching
  an image that is already in flight because the in-flight test looks at
  terminal status rather than at what has been dispatched.

  Found while writing `tests/backend/share_05_master_and_plots.py`, which
  asserts a copied scan keeps its children. Nothing in the sharing code is
  implicated: `copy_job` faithfully reproduces whatever family it is given,
  and the test now asserts on the set of distinct `_scan_index` values so
  it measures the copy rather than this bug.

- **Deleting a user leaves their projects behind, and the leftovers become
  visible to everyone.** `purge_user_data` in `app/auth/storage_quota.py`
  removes the account's jobs, KB entries, uploads, threads and plots, but it
  never touches `data/projects.json`. The project rows survive, and because
  `ownership_index.owner_user_id` is `ON DELETE CASCADE`, their ownership
  rows go with the user. A project with no recorded owner is deliberately
  visible to every user (the same rule that governs unowned jobs), so
  deleting an account converts that account's private archives into
  deployment-wide public ones.

  Found while writing `tests/backend/share_03_lifecycle.py`, which deletes
  its own users at the end and left two ownerless `qatest shared study`
  projects behind the first time it ran. The script now deletes its own
  projects explicitly, so the suite is clean either way, but the underlying
  gap is in the app rather than in the test. The fix is a project sweep
  inside `purge_user_data` beside the existing plot sweep; the open question
  is whether the member jobs go too, which is the same ambiguity
  `DELETE /api/projects/{id}` resolves by asking, and an account deletion
  has nobody to ask.

- **Four people at once wait about 7s for a first token, against about 2.5s
  alone.** Worth improving, but the cause is not what this entry used to say.

  It claimed the app roughly doubles the model server's own concurrency
  penalty (app 5.04x against the server's 2.12x). That figure does not
  reproduce, and more usefully, **it cannot be measured at all on this host
  while other people are using the GPU.**

  The number is a ratio of ratios, and the denominator is a baseline
  measured against a shared card. `perf_02` now samples that baseline twice
  in the same run, before and after the app's own burst, and the two samples
  have come back as far apart as 3.05x and 0.95x. The second of those says
  four concurrent requests were *faster* than one, which is not a fact about
  the model server; it is a fact about what somebody else's job was doing at
  that moment. Across five pooled runs the app's multiplier read 1.05x,
  0.99x, 1.06x, 1.86x and 3.52x. There is no result in that.

  So the script now checks whether it can attribute before it attributes: if
  the two baseline samples disagree by more than 1.5x, the host moved
  underneath the run and the app-vs-host split is reported as unavailable
  rather than asserted. The raw seconds still stand, because those are what
  a user waits. Settling the split for real needs the GPU to itself.

  The mechanism
  that would have explained a doubling was a process-global graph lock
  serializing every conversation's turn for the full duration of its LLM
  streaming, and that was replaced by a per-conversation lock some time ago
  (see the Locking comment in `app/agent/graph.py`); two turns on different
  conversations no longer contend at all.

  Sampling was improved along the way and was worth doing regardless: both
  sides now pool three bursts, and the single-user median rests on as many
  samples as the concurrent one, since it is what the ratio divides by. At
  six samples it swung between 1.43s and 3.38s across runs while spreading
  1.34s to 4.03s within a single one, and that alone moved the app's ratio
  by a third. None of it is enough to overcome a shared GPU.

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
