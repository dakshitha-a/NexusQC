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

- **The system prompt is over its own byte cap.**
  `tests/backend/agent_01_token_budget.py` asserts `SYSTEM_PROMPT` under 6,144
  bytes and it is 6,242, so that script reports 12/13 rather than passing.
  Pre-existing, not caused by anything on the derivative-energies branch
  (`app/agent/prompts.py` is unchanged there and fails identically on `main`).
  The tool surface it is checked alongside is comfortably inside its own
  budget at 8,841 of 10,000 tokens. Either trim ~100 bytes of prompt or
  decide the cap has moved and say so in the script.

- ~~**The lone-pair target aims at the wrong lone pair of the two.**~~ Closed
  2026-09-04. `geometry.LONE_PAIR_S_AMPLITUDE` is 0.20 rather than an sp2
  hybrid's 0.577, so the target is now the p-like in-plane lone pair that an
  n->pi\* excitation actually uses. Every n-type state's capture improves,
  uracil 0.363 to 0.759, and uracil's n->pi\* is found at root 2 and 9.03 eV
  where it was absent from eight roots, and the refinement now lands uracil on
  the literature CAS(14e,10o) with both requested states present. The cost is
  that pyrrole's ground-state reference is no longer offered as a tier.
  `docs/casbench/hole-capture.md` has the sweep and says why that verdict, which
  flips twice across it, was not used to pick the value.

- ***p*-benzoquinone's n->pi\* is still not found**, at any lone-pair target
  amplitude tested, even though its capture improves to 0.617 and 0.708. It is
  the one molecule the target correction does not fix, so the cause is
  something else. `scripts/casbench/irrep_gate.py p-benzoquinone` reproduces
  it.

- **The state audit's "state missing" verdict is unreliable on large planar
  spaces.** A Davidson reaches only what its initial guess spans, and in a
  planar molecule the a'/a'' coupling is identically zero, so configurations
  above the guess window stay unreachable however many roots are requested.
  Small spaces are fine, since the guess spans them; formaldehyde's (6e,4o)
  finds its A2 n->pi\* at root 1. Uracil's (14e,10o) does not. Correcting the
  lone-pair target above is enough to fix the cases seen so far, so this needs
  no separate change, but the audit should say when a verdict rests on a guess
  much smaller than the space.

- ~~**`hole_capture.py` fails on open-shell molecules.**~~ Closed 2026-09-04,
  and the entry was wrong about whose gap it was. The `TypeError` came from
  `app/chemistry/cas/excited.py`, not from the script: on an ROHF/ROKS
  reference pyscf's `get_nto` returns one NTO set per spin, with a different
  occupied count in each channel, and `analyse` indexed that tuple as an array.
  So asking for excited states on **any** open-shell molecule took the whole
  path down, in `run_cas_recommendation` and `run_cas_refinement` alike, and
  nothing covered it. Fixed by taking the spin channel carrying the leading NTO
  weight, with `tests/backend/cas_04_open_shell.py` now asserting it (15/15).

- ~~**The CAS refinement drawer has never been opened in a browser.**~~ Closed
  2026-09-04, and the entry was wrong about what was missing. The drawer did
  not render the refinement's occupation table, orbital characters or rotation
  trail: the dedicated section drew the recommendation's fields only, and the
  refinement's output fell through to the generic key/value dump. It has now
  been written and checked in a browser
  (`tests/frontend/cas_14_refinement_drawer.spec.mjs`, 17/17). The lesson worth
  keeping is that "it type-checks and its keys were checked against a real
  runner call" was not true, and two separate key-name mismatches survived a
  clean type-check and rendered nothing.

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
