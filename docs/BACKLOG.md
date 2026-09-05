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

- **The state-narrowing does not exclude Rydberg states, and on a molecule
  whose requested states are all Rydberg the narrowed space is not
  reproducible.** Found on 2026-09-05 by chasing an unexplained difference
  between two runs of `scripts/casbench/narrowing_agreement.py`, where water
  narrowed to $(4e,2o)$ in one and $(2e,1o)$ in the next with no code between
  them touching the narrowing. Reproduced directly: three identical runs give
  (4,2), (2,1), (2,1), with both TDA states labelled `pi->Rydberg` every time.

  `narrow_to_states` reads `analysis.states[:n_states - 1]` and filters on
  character alone. Everywhere else in the loop a Rydberg state is excluded by
  `particle_kind`: `refine()` drops them from `predicted` and says so, `augment`
  skips them by construction, and P3.3 made "correctly not looked for" a
  distinct reported outcome. The narrowing never got that treatment, so it
  trims a valence space toward states a valence space cannot hold, and when
  every requested state is Rydberg there is nothing valence left to aim at.
  What decides the answer is then which near-degenerate lone pair happens to
  score highest, which is not stable.

  Water at three states is an odd request and this is a narrow case, but it is
  user-reachable and the symptom is a recommendation that changes between
  identical runs. The fix is to filter on `particle_kind != "Rydberg"` where
  the states are consumed, matching the rest of the loop, and then to decide
  what a narrowing with no valence states left to narrow for should do: almost
  certainly decline to narrow, the way a ground-state request already does,
  rather than narrow toward nothing. Related to the twisted-ethylene entry
  below; both are reproducibility rather than accuracy.

- **The system prompt is over its own byte cap.**
  `tests/backend/agent_01_token_budget.py` asserts `SYSTEM_PROMPT` under 6,144
  bytes and it is 6,242, so that script reports 12/13 rather than passing.
  Pre-existing, not caused by anything on the derivative-energies branch
  (`app/agent/prompts.py` is unchanged there and fails identically on `main`).
  The tool surface it is checked alongside is comfortably inside its own
  budget at 8,841 of 10,000 tokens. Either trim ~100 bytes of prompt or
  decide the cap has moved and say so in the script.

- **`recommend.MINIMAL_ENTROPY_GAP` should probably be 0.10, not 0.15.** At
  0.05 and 0.10 two more benchmark molecules have their literature space offered
  as one of the tiers, 17 of 21 against 15, with the exact count unmoved and the
  result replicated. It is very likely what restores pyrrole's ground-state tier
  that the lone-pair target correction cost. Not applied because the constant
  decides which tier counts as minimal, and the minimal tier is offered to the
  user, is a valid refinement start tier and appears in the cost report, so it
  needs its own validation pass including the refinement benchmark.
  `docs/casbench/constants.md` has the sweep.

- **Twisted ethylene's recommendation is not reproducible.** Four identical runs
  gave (2e,2o) three times and (4e,3o) once, with the SCF converged every time.
  It is a singlet diradical, so RHF is a qualitatively wrong reference and the
  APC ranking taken from the RHF Fock and exchange matrices inherits the
  near-degeneracy. Every other benchmark molecule is bit-for-bit reproducible.
  Until it is fixed or the entry is scored differently, every count in section
  10 of the method document carries plus or minus one molecule.

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

- ~~***p*-benzoquinone's n->pi\* is still not found**.~~ Withdrawn 2026-09-04:
  the gate that said so runs a CASCI, which cannot relax orbitals, and the
  downstream benchmark finds its n->pi\* states at 2.62 and 2.65 eV from a
  state-averaged CASSCF, converged. `irrep_gate.py` gives a conservative
  negative, meaning "not reachable without orbital relaxation" rather than
  "broken", and its docstring now says so.

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

- ~~**The n/sigma labelling thresholds rest on two molecules.**~~ Closed
  2026-09-04. They now rest on the whole benchmark, including the thiols and
  the pyramidal amines this entry asked for, and the answer is that the
  shipped 0.50 is right and should not become element-aware. Nitrogen and
  oxygen sit on the same scale (medians 0.582 and 0.573) and sulfur's is
  higher, not lower, which is the opposite of the suspicion. The spread within
  nitrogen alone, 0.234 to 0.977, is wider than any gap between elements, and
  what drives it is delocalisation rather than the atom: one methyl costs
  0.185 on sulfur and 0.249 on nitrogen. `docs/casbench/constants.md` has the
  measurement.

- **No transition metal has been through the CAS engine.** `geometry.perceive`
  emits a d-shell target for them and `build_target_matrix` handles the
  axis-free case, but nothing in the 17-molecule benchmark exercises it.

- **The Rydberg path is now half exercised, and the remaining half is
  deliberate.** This entry used to say none of it was, on the belief that no
  benchmark molecule carries a Rydberg reference below its valence pi->pi\*.
  That was wrong: pyrrole and furan both do, in this repository's own
  reference data. With the refinement analysing in a diffuse basis, the
  exclusion path is exercised and a predicted Rydberg state is now reported as
  deliberately not looked for rather than silently chased
  (`docs/casbench/refine.md`). What stays unexercised is *augmenting* a space
  with a Rydberg orbital, because `excited.augment` skips Rydberg particles on
  purpose: a valence space is not meant to grow one. Closing this properly
  means deciding whether a Rydberg state should ever be served at all, which
  is a product question rather than a gap.

- **A state-averaged CASSCF can have more than one converged solution, and
  which one a run finds is decided by BLAS reduction order.** Twenty identical
  acrolein runs in the recommended CAS(8e,6o) land in two answers, 16 at
  E0 = -190.823527 Ha and 4 at -190.824866 Ha, 36.4 meV apart and disagreeing
  about the character of roots 4 and 5. All twenty converge. Within either
  solution the reproducibility is exact, to 0.0007 meV. Pinning BLAS to one
  thread makes the choice deterministic, which is what identifies the
  mechanism.

  This supersedes the entry that used to sit here calling the same effect a
  0.3 eV reproducibility floor and attributing it to solver tolerance. It is
  not a floor and no tolerance touches it; see
  `docs/casbench/acrolein-bistability.md`. The practical consequence for users
  is unchanged and is the reason this is still open: someone can rerun the
  same job and get a visibly different answer, with a converged flag both
  times. What is not yet known is how many molecules do this, since acrolein
  is the only one measured at twenty repeats. Closing it properly means
  deciding whether the app should detect the case and say so, which it
  currently cannot, since one run cannot tell it is in the higher solution.

- **`ROOT_MARGIN` may be reorderable, but the experiment that would say so
  needs a molecule other than uracil.** Carried out of the CAS engine audit as
  its one step deliberately not taken (P5.2 there). The idea was to make
  adding roots the first response to a missing state, and it was blocked by
  the span finding: uracil, the molecule `ROOT_MARGIN` was set for, does not
  contain its own n->pi* state at any root count, so the reordering would have
  been tuned against a state that is not there. The lone-pair correction has
  since put that state in the space, and P6.2 then found that across six
  molecules at three root counts, adding roots never recovers a state fewer
  roots missed. So the original motivation is gone and the reordering has no
  measured benefit to chase. It stays here rather than in the tracker because
  reopening it needs a molecule where extra roots demonstrably find something,
  and no such molecule is currently known.

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
