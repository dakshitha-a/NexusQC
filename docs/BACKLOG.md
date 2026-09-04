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

- **Deleting a user makes every invite token they redeemed usable again.**
  `invite_tokens.redeemed_by` is a real foreign key to `users(id)` and goes
  NULL when the user row is deleted, but `register_with_invite_token` in
  `app/auth/models.py` decides "already used" by testing `redeemed_by is not
  None` rather than `redeemed_at`. So `DELETE /api/admin/users/{id}` silently
  resurrects that user's invite, and an admin invite resurrected this way
  mints another admin until it expires. Found on 2026-09-04 while recreating
  an account: two admin invites belonging to deleted accounts came back live
  and had to be revoked by hand. Checking `redeemed_at` instead is the fix;
  `redeemed_by` should stay for the audit trail.

- **The CAS refinement drawer has never been opened in a browser.**
  `frontend/src/jobs/JobDetailDrawer.tsx` renders the refinement's occupation
  table, orbital characters and rotation trail. It type-checks and its keys were
  checked against a real runner call, but this project requires a Playwright
  check for frontend changes and it has not had one. Was P8.2 of the CAS engine
  tracker; moved here rather than marked done.

- **o-Nitrophenol and p-benzoquinone exceed the ten-minute refinement cap.**
  Both causes are deliberate (a root-aware CSF budget, and a singlet-only state
  average, which each cost time), and both molecules are the kind users ask
  about. Either the cap is wrong for the product, since long runtimes are the
  design premise, or the narrowing needs to be more aggressive for large
  conjugated systems.

- **Acrolein's refined space is one orbital short of its literature (8e,7o).**
  It comes back (8e,6o). Unexplained; every other finished molecule with a
  literature space either matches or has a recorded reason.

- **The n/sigma labelling thresholds rest on two molecules.** The 0.50
  lone-pair-over-sigma preference and the 0.25 ambiguity band
  (`app/chemistry/cas/refine.py`) were set on uracil and o-nitrophenol, both
  planar with carbonyl or nitro oxygens. A thiol, or an amine with a pyramidal
  nitrogen, would exercise them differently and has not been tried.

- **No transition metal has been through the CAS engine.** `geometry.perceive`
  emits a d-shell target for them and `build_target_matrix` handles the
  axis-free case, but nothing in the 17-molecule benchmark exercises it.

- **The Rydberg augmentation path is unexercised.** `excited.augment` skips
  Rydberg particles by design, but no benchmark molecule has a Rydberg
  reference state below its valence pi->pi\*, so only the valence path has
  been measured.

- **SA-CASSCF results are not reproducible to better than about 0.3 eV per
  state on this host.** Three identical repeats of acrolein gave three energies
  and one non-convergence, with the root nearest its 6.68 eV reference moving
  0.29 eV. This bounds every per-state benchmark number and is why
  `run_bench.py` prints its own noise floor. Worth understanding rather than
  living with, since it also means a user can rerun the same job and get a
  visibly different answer.

- **`elic_01_draft_scenarios.py` scenarios 5 and 6 fail, and predate the CAS
  work.** Scenario 5: `single_point/grad` ends up carrying `target_states: [1]`
  when it should carry only the basis. Scenario 6: `single_point/nac` asks for
  `n_excited_states` at step 2 where the test expects something else. Both fail
  identically at `2f1f58d`, and the branch that touched `elicitation.py` only
  removed dead cas_reco DMRG rules, so they are unrelated. 196/198 otherwise.

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
