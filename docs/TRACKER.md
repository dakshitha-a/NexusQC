# Tracker: a rebuilt CAS active-space recommendation engine

<!-- artifact: (recorded on first publish) -->

**In motion, opened 2026-09-02.** Ten phases. Replaces the two legacy
`cas_reco` runners with one basis-agnostic, uncapped, state-aware engine.

It stays here rather than moving to [`trackers/`](trackers/) until the next
plan starts, which is when it gets archived and a fresh tracker takes its
place. **Exactly one tracker is active at a time.**

## How tracking works here

Development is linear, so there is never a reason to have two trackers open at
once. Each plan, feature or non-trivial request gets its own tracker, this file
is whichever one is currently in motion, and when its plan is finished the file
is closed out and moved to [`trackers/`](trackers/), then a fresh one starts
here for whatever comes next.

Closed trackers are kept, never deleted. They are the audit trail for why the
code looks the way it does, and code comments cite them by path. The one this
replaces is
[`trackers/2026-09-atom-number-switch.md`](trackers/2026-09-atom-number-switch.md)
-- 7 steps across three phases, closed 2026-09-02.

## Rules (enforced by `scripts/check_tracker.py`)

- Step status is exactly one of `todo` | `in-progress` | `done`.
- A step may be marked `done` **only with an evidence field**: the
  verification script/command path plus a one-line observed result.
- The tracker edit ships **in the same commit** as the step's final code
  change, so `git log --follow docs/TRACKER.md` is the audit trail.
- A phase's `merged` row records the commit hash the stage landed as.

Format for a step row:

```
- [status] P<phase>.<step>: <short name>
  evidence: <script/command> → "<observed result>"   (required when done)
```

---

## Why this plan exists

The two runners in `app/chemistry/jobs/pyscf_runner.py` --
`run_recommend_active_space` ("autocas") and `run_avas_active_space` ("avas")
-- work, but four properties of their design are in the way of what the
feature is for.

**They cap the active space at 12 orbitals.** `_PILOT_CAS_CEILING = 12` is
overloaded: it is both the exact-FCI pilot pool ceiling and the validation
ceiling for a user-supplied `max_active_orbitals`, and both runners *refuse*
above it rather than clamp. The cap is there because every recommendation ends
in a full state-averaged CASSCF, which is the expensive part of the job.

**The recommendation depends on the basis set.** `basis` is required, and the
parameter's own warning text says so: it "governs the whole recommendation,
not just the CASSCF at the end of it." The same molecule can get a different
space from a different basis.

**The excited-state path is chemically blind.** When more states are requested
than the space can host, the runner widens it by whichever orbital maximises
the *configuration count*, with entropy as a tiebreak. It never asks which
orbitals the requested states actually need. A dark n->pi* state needs the
heteroatom lone pair; nothing in that rule can know it.

**Open-shell molecules are refused outright.**

### What the spikes established, before any code was written

Five spikes on this host settled the architecture. Each is reproduced as a
test in the phases below.

1. An **orientation-aware AO projector** -- target p-orbitals built along a
   geometrically derived local pi normal, then AVAS's own occupied/virtual
   projection and eigendecomposition -- gives pyrrole CAS(6,5) and
   formaldehyde CAS(2,2) pi-only / CAS(4,3) pi+n, **identical across STO-3G,
   def2-SVP, cc-pVDZ, def2-TZVP and aug-cc-pVDZ, and identical under arbitrary
   random rotations.**
2. **Stock `pyscf.mcscf.avas` cannot do this.** It takes only axis-aligned AO
   labels, so it is not rotation invariant: pyrrole's CAS(6,5) becomes
   CAS(10,7) once the molecule is randomly rotated. Real user geometries are
   arbitrarily oriented, so the custom projector is required, not a nicety.
3. **APC ranking is effectively free** (~0.1 s; it needs only `mf.get_fock()`
   and `mf.get_k()`), but it is not basis-agnostic alone -- pyrrole gives
   CAS(18e,12o) in def2-SVP against CAS(22e,13o) in def2-TZVP -- so it ranks
   *within* the projector's pool and never selects from the whole MO space.
4. **<r^2> separates Rydberg from valence with a 5x margin.** On formaldehyde
   in aug-cc-pVDZ the dark n->pi* state sits at ratio 0.86 (3.94 eV against a
   reference 3.98) while Rydberg states sit at 4.6-8.7.
5. **The basis limit on Rydberg states is real and detectable.** In cc-pVDZ,
   with no diffuse functions, no state is flagged Rydberg -- which is
   physically correct. That is the one place basis-agnosticism genuinely ends,
   so the engine reports it rather than hiding it.

Timings that set the budget: SCF + APC ~0.3 s; TDA for 8 roots on pyrrole 3 s
in def2-SVP, 21 s in def2-TZVP.

### Two traps already documented in the existing code

`_pilot_entropies_dmrg` records both, found the hard way, and the new
verification tier must respect them:

- **block2 0.5.3 segfaults** on `get_orbital_entropies()` over a multi-root
  MPS. A segfault kills the worker outright, so no result is written and the
  job never reaches a terminal status -- the one job-lifecycle failure this
  project counts as a real defect. The verification tier may take energies and
  RDMs from a multi-root DMRG, never entropies.
- **`SymmetryTypes.SZ`, not `SU2`** -- SU2 hits a pybind11 cast bug in this
  build for single-orbital entropies, and its fallback returns
  `NotImplemented`.

### A gap the design review caught, before any code was written

The spikes proved the projector on pi systems and lone pairs. **Water has
neither.** A projector emitting only those targets gives water a pool of two
oxygen lone pairs -- completely full, one configuration -- which is precisely
the degenerate `(6e,3o)` defect the legacy runner grew a hydrogen-reseed rule
and a terminal guard to work around, reintroduced by a different route. `geometry.py` must therefore also emit
**sigma-bond targets**: per bond, a bond-axis-oriented hybrid pair on the two
bonded atoms, putting sigma and sigma* into the pool. This is not a
refinement, it is what makes the engine correct for hydrides and saturated
systems, so it gets its own step (P1.3) with water as its evidence.

### Decisions taken before starting

- **Legacy goes harness-only**, not deleted yet: it is the control in the
  head-to-head that justifies deleting it. It stays live until the replacement
  exists (P6.5), because this project commits only what it would deploy.
- **`basis` becomes optional.** Analysis always runs in def2-SVP, or def2-SVPD
  when excited states are wanted. A user-supplied basis is *inspected only*,
  to decide whether Rydberg states can be described at all.
- **Verification is a cheap CASCI**, skippable -- not the legacy full
  SA-CASSCF, which is what forced the cap.
- **The TaskDef keeps `methods=("casscf",)` and `requires=("energy",
  "excited")`,** which is load-bearing rather than cosmetic:
  `elicitation._derive_root_count` adds the ground-state root only when the
  draft's method is in `MULTIREF_METHODS`, so dropping `casscf` here would
  silently cost the recommendation a root. `method` now means the *downstream
  target*, and a comment at both ends says so.
- **The handoff is an artifact plus a job-id reference**, not a dict parameter
  -- `active_space_spec.json` in the job directory, read through
  `active_space_source_job_id`, mirroring `initial_orbitals_job_id`. Every
  vector in it is expressed in the **minao reference basis**, which is what
  makes it re-expandable in any later basis and is the whole reason the
  handoff is portable.
- **`app/chemistry/cas/` is a library over a converged `mf`.** It never builds
  a `Mole`, never imports `registry2` or `pyscf_runner`. That is what keeps it
  importable from the worker, the harness and a bare test script alike.
- Bugs and performance problems found while implementing are **fixed as they
  are found**, each carrying its own step and evidence.

---

## Phase 1: The perception and projection core

The basis-agnostic, rotation-invariant heart, built and proven before anything
depends on it.

- [done] P1.0: Archive the finished tracker and open this one
  evidence: docs/trackers/2026-09-atom-number-switch.md → "closed tracker archived; check_tracker.py PASS on the new file, 34 steps, 0 merged"
- [done] P1.1: Chemical perception from geometry alone
  evidence: tests/backend/cas_01_geometry_axes.py → "16/16; pi normals rotate exactly with the molecule, sp3 centres correctly get none, N2 gets axial lone pairs"
- [done] P1.2: The orientation-aware projector
  evidence: tests/backend/cas_02_projector_invariance.py → "12/12; benzene (6,6), butadiene (4,4), pyrrole (8,6) identical over 5 basis sets and 5 rotations, against stock AVAS moving (6,5)->(10,7)"
- [done] P1.3: Lone pairs and sigma bonds, so a hydride gets a pool with virtuals in it
  evidence: tests/backend/cas_03_lone_pairs_and_sigma.py → "17/17; water is full (4e,2o) without sigma targets and (8e,6o) with them, in every basis"
- [done] P1.4: Invariance is a test, not a claim
  evidence: tests/backend/cas_02_projector_invariance.py → "the stock-AVAS contrast is asserted, not just described: CAS(6,5) aligned vs CAS(10,7) rotated"
- [done] P1.5: Open shells reach the projector
  evidence: tests/backend/cas_04_open_shell.py → "13/13; O2, NO, CH3, CH2 all give spaces with the right unpaired count; ROHF basis-stable where UHF is not"
- merged: 41aba52

## Phase 2: Legacy relocation and the evaluation harness

Built early, because it is what produces the evidence for deleting legacy.

- [done] P2.1: A harness entry point onto the legacy runners
  evidence: scripts/casbench/run_bench.py → "recommend_legacy() calls _avas_pilot_space and _truncate_avas_space in place; legacy still owns cas_reco until P6"
- [done] P2.2: A curated reference table of best estimates
  evidence: scripts/casbench/reference_data.py → "15 geometries, 24 QUEST/Thiel best estimates and 14 literature active spaces, each with a citation; offline by design"
- [done] P2.3: The head-to-head harness
  evidence: scripts/casbench/run_bench.py → "four sets: spaces, stability, excited, nevpt2; runs in process so it creates no jobs or conversations to purge"
- [done] P2.4: A recorded legacy baseline
  evidence: scripts/casbench/run_bench.py → "legacy matches the literature space on 1 of 14 molecules against the new engine's 8, refuses O2 outright, and changes its answer with the basis on 2"
- merged: 43007fd

## Phase 3: Ranking, balancing and sizing

- [done] P3.1: APC ranking within the candidate pool
  evidence: app/chemistry/cas/ranking.py → "APC entropies from Fock and exchange only, ~0.1s; ranks inside the pool because raw APC gives pyrrole (18e,12o) in def2-SVP vs (22e,13o) in def2-TZVP"
- [done] P3.2: Chemical completion and balance
  evidence: tests/backend/cas_05_tiers.py → "38/38; every tier holds electrons and is not full, including the O2 triplet that the closed-shell occupation bug turned into (2e,3o)"
- [done] P3.3: Cost tiers instead of a cap
  evidence: app/chemistry/cas/feasibility.py → "Weyl-Paldus CSF counts; CAS(6,6) singlet = 175 CSFs / 400 determinants; (80e,80o) reports a cost instead of raising"
- [done] P3.4: The orchestrator, ground-state path end to end
  evidence: tests/backend/cas_05_tiers.py → "benzene (6,6), butadiene (4,4), formaldehyde (6,4), water (8,6) via the sigma fallback; identical in cc-pVDZ and def2-TZVP; 0.1-1.0s"
- merged: f95df13

## Phase 4: The excited-state branch

- [done] P4.1: TDA, NTOs and state character
  evidence: tests/backend/cas_06_excited_character.py → "17/17; formaldehyde n->pi* 3.94 eV vs QUESTDB 3.98, acrolein 3.58 vs 3.74 and pi->pi* 6.50 vs 6.68"
- [done] P4.2: Rydberg detection and the honest basis limit
  evidence: tests/backend/cas_06_excited_character.py → "valence 0.86 vs Rydberg 4.59 second-moment ratio, a 5.3x separation; cc-pVDZ flags none and says the basis could not look"
- [done] P4.3: States drive which orbitals enter the space
  evidence: scripts/casbench/run_bench.py → "augment() is called from the refinement loop when a predicted state is missing and its character has NOT left; exercised on valence states only, since no benchmark molecule has a Rydberg reference below its valence pi->pi*, so the Rydberg skip is structurally right but unmeasured"
- [done] P4.4: Bright, dark and mixed-character states
  evidence: tests/backend/cas_06_excited_character.py → "acrolein's dark n->pi* and bright pi->pi* both identified, dark below bright as the reference has it"
- merged: -

## Phase 5: The verification tier

- [done] P5.1: Confirm the states are really there
  evidence: tests/backend/cas_07_verification.py → "12/12; formaldehyde's predicted n->pi* is found, a mutilated space fails by name, and an oversized space reports 'not verified' rather than passing"
- merged: 7f208aa

## Phase 2B: A gap the benchmark found

- [done] P2B.1: A sigma bond is an sp hybrid, so target the valence s as well
  evidence: scripts/casbench/run_bench.py → "N2 and O2 reached their literature full valence spaces (10e,8o) and (12e,8o); literature match rose from 8/14 to 10/14"
- [done] P2B.2: Reference states are matched to roots by character, not by index
  evidence: scripts/casbench/run_bench.py → "SC-NEVPT2 MAE over the same states fell from 1.36 eV to 0.43 eV; the difference was mis-assignment, not the spaces"
- merged: 0dd377e

## Phase 6: Wire the engine into the app

- [done] P6.1: The new runner
  evidence: app/chemistry/jobs/pyscf_runner.py → "run_cas_recommendation: water (8,6), formaldehyde (6,4) with states, O2 triplet (10,7) which legacy refused; artifacts and a JSON-serialisable summary"
- [done] P6.2: Registry, params and retirements
  evidence: scripts/check_capability_matrix.py → "755 assertions across 19 rows and 19 tasks pass; basis optional for cas_reco only; six params retired via RETIRED_PARAMS"
- [done] P6.3: Dispatch and worker
  evidence: app/chemistry/jobs/dispatch.py → "one row, ('cas_reco',''): 'cas_recommendation'; autocas and avas both resolve to it as synonyms"
- [done] P6.4: Loose ends the rebuild leaves behind
  evidence: app/agent/tools.py → "plot(kind=entropy) keeps working on old and new jobs alike: the summary emits pilot_orbital_entropies and active_space_orbital_indices under their existing names"
- [done] P6.5: Legacy leaves pyscf_runner.py
  evidence: scripts/casbench/legacy_cas_reco.py → "14 symbols and 1026 lines moved out of app/; nothing under app/ imports them, and the harness still runs both sides"
- [done] P6.6: The prompt names tools that do not exist
  evidence: tests/backend/cas_08_prompt_names_real_tools.py → "11/11; five stale tool names removed from prompts.py and a guard added so any name written as a call must be a bound tool"
- merged: 3a42b08

## Phase 7: The portable handoff

Without this, basis-agnosticism is only a claim in a summary table.

- [done] P7.1: An active space that survives a change of basis
  evidence: tests/backend/cas_09_portable_spec.py → "14/14; pyrrole's spec rebuilds to CAS(8,6) in four bases, where an MO-index handoff gives principal cosine 0.999 into cc-pVDZ and 0.000 into aug-cc-pVDZ"
- [done] P7.2: The follow-up draft carries the specification
  evidence: tests/backend/p8_02_cas_reco_followup.py → "15/15; the operative handoff was MEASURED rather than assumed -- _seed_mo_from_source projects coefficients via project_init_guess(prev_mol=...), and pyrrole's pi subspace weight is preserved at 4.972 into def2-SVP, cc-pVDZ and aug-cc-pVDZ alike, so the spec is the portable artifact and the projection is the operative one"
- [done] P7.3: ORCA and BAGEL get the counts and an honest note
  evidence: app/chemistry/jobs/pyscf_runner.py → "summary carries a handoff block saying the counts apply on any engine and the orbital identity transfers only to PySCF; the molden-to-ORCA route is not claimed because it was never validated"
- [done] P7.4: The same space, three basis sets, one job chain
  evidence: tests/backend/cas_09_portable_spec.py → "14/14 across four basis sets, with the MO-index handoff measured alongside as the contrast"
- merged: -

## Phase 8: Tests, frontend and docs

- [done] P8.1: Retire the legacy test scripts
  evidence: tests/backend/casreco_01_capability_axis.py → "four scripts testing removed internals deleted; casreco_01/04/05, active_01, tax_01, elic_01 and reg2_01 rewritten and green"
- [todo] P8.2: The drawer shows what the new engine reports
  evidence: -
- [done] P8.3: Docs follow the code
  evidence: scripts/check_capability_matrix.py → "docs in sync after regeneration; CAS_RECO_REDESIGN.md carries a superseded banner, README and CHANGELOG rewritten, no stale autoCAS/entropy-pilot prose left"
- merged: -

## Phase 9: Evaluate, then decide

- [done] P9.1: The full head-to-head
  evidence: scripts/casbench/run_bench.py → "new matches the literature space 10/14 vs legacy 1/14; 0/14 vs 2/14 basis-dependent; SC-NEVPT2 MAE 0.43 eV over 18 states, 11/11 CASSCF converged"
- [done] P9.2: The verdict, and legacy's fate
  evidence: docs/CAS_ENGINE_METHOD.md → "section 8.9: no axis on which legacy is ahead; deletion recommended but kept one release so the benchmark stays runnable"
- merged: d430c18

## Phase 11: A CASSCF-based refinement pass

The recommendation is chosen a priori and nothing measures what it predicted.
This runs the CASSCF, looks at what happened, and corrects the space --
opt-in, after the quick recommendation, on approval.

- [done] P11.1: The refinement loop and its audits
  evidence: app/chemistry/cas/refine.py → "pyrrole CAS(8,6)->(6,5) in 2 cycles, its classical pi space; formaldehyde unchanged; O2 triplet (10,7)->(8,6)"
- [done] P11.2: Which tier to start from, settled by measurement
  evidence: docs/CAS_ENGINE_METHOD.md → "section 9.4: maximal unreachable for 3 of 4 molecules by 6-13 orders of magnitude, 400x slower and unconverged where it runs; recommended is the default"
- [done] P11.3: The runner, registry and follow-up offer
  evidence: scripts/check_capability_matrix.py → "791 assertions across 19 rows and 20 tasks pass; cas_reco/refine dispatches to cas_refinement"
- [done] P11.4: Tests, including the negative control
  evidence: tests/backend/cas_10_refinement.py → "16/16; an occupation cut takes uracil's lone pairs at four AND six roots, so the state audit is what protects them; the subspace measure is invariant to a random unitary where per-orbital labels flip"
- merged: -

Three bugs were found by running this loop rather than by reading it, and all
three changed the design.

**Character loss is the wrong trigger for a re-seed on its own.** Uracil's
recommended CAS(22e,14o) hands back 4.26 orbitals' worth of lone-pair character
when asked for three states, because three states do not need six lone pairs.
Forcing them back fights the correct answer. Character leaving has two
meanings: with a predicted state *missing* the space lost something it needed
and should be re-seeded; with every state *present* the optimisation has handed
back orbitals those states do not use, which argues for pruning. The state
audit now decides and the character measure is the diagnostic.

**Re-seeding from the original projected orbitals is not a different starting
guess**, so the loop converged to the same place and stopped without ever
pruning. `reseed_lost_character` now does what the manual fix does: keep the
converged orbitals, drop the ones that no longer carry the character they were
chosen for, rotate the projected ones back into their place. That changes the
answer -- four then five orbitals swapped on successive uracil cycles.

**A linear-response pass and a CASSCF do not order states the same way.** TDA
puts uracil's n->pi* at S1; the two lowest CASSCF excited roots of that space
are both pi->pi*, and the n->pi* appears only around root 3. Solving for
exactly the requested number of roots means such a state is reported missing
forever, and the loop re-seeds and augments chasing it instead of pruning.
There is now a margin of three extra roots, and the result says which root each
predicted state actually landed on -- so asking for three states and being told
the n->pi* is root 3 is information the user gets rather than a silent wrong
answer.

## Phase 12: The benchmark, re-run whole

- [done] P12.1: Uracil and o-nitrophenol join the reference set
  evidence: scripts/casbench/reference_data.py → "17 molecules; uracil with QUEST energies and its (14,10) space, o-nitrophenol with neither, listed in MOLECULES_WITHOUT_REFERENCE_ENERGIES"
- [done] P12.2: The refinement benchmark, all 17 molecules
  evidence: docs/CAS_ENGINE_METHOD.md → "section 9.7: 17/17 inside a 10-minute cap, 11 unchanged, pyrrole and p-benzoquinone reach their literature spaces, two ground-state-only cases move away from it"
- [done] P12.3: The other four sets re-run and section 8 restated
  evidence: docs/CAS_ENGINE_METHOD.md → "17 molecules: 10/15 literature spaces, 0/15 basis-dependent against legacy 2/15, 23/24 states located at 0.23 eV, SC-NEVPT2 0.29 eV over 20 states with 12/12 CASSCF converged"
- merged: -

## Phase 10: The method, written up

- [done] P10.1: A scientific description of what was built
  evidence: docs/CAS_ENGINE_METHOD.md → "616 lines: projector formalism, APC entropy, NTO decomposition and the <r^2> criterion, what is AVAS/APC/AEGISS and what is not, 18 references"
- [done] P10.2: The benchmarks, in the writeup
  evidence: docs/CAS_ENGINE_METHOD.md → "section 8, every number from the harness including the formaldehyde V-state failure and a section on what is not established"
- merged: ec7c134

---

## Found along the way, not fixed here

**Uracil and o-nitrophenol show the unwired `augment()` costing something
real.** Asked for uracil (3 states, cc-pVDZ) the engine recommends CAS(22e,14o):
the whole pi system plus *all six* lone-pair-derived orbitals, because with no
augmentation step the valence pool is returned whole rather than narrowed to
what the requested states use. Restricting by hand to the orbitals those states'
NTOs actually occupy gives CAS(14e,10o) = 5pi + 2n + 3pi*, which is the usable
answer. o-nitrophenol (5 states) behaves the same way: CAS(24e,18o) recommended,
CAS(16e,12o) once narrowed.

The flat-entropy path makes this worse rather than better here: for both
molecules the minimal tier equals the recommended one, so the engine offers no
smaller alternative at all. Wiring `augment()` would fix both symptoms, and
these two molecules are the regression cases to fix it against.

A second finding from the same run, worth keeping: **uracil needs both carbonyl
lone pairs, not one.** With 5pi + 1n + 3pi* an SA-CASSCF over six roots
converges and produces no n->pi* state at all; with 5pi + 2n + 3pi* they appear
immediately, the cleanest at 5.17 eV after SC-NEVPT2 against a literature 4.80.
Uracil has two carbonyls and the n->pi* hole is a combination of both oxygens'
lone pairs, so including one breaks the description.

**Two pieces are written and tested in isolation but not wired into the running
pipeline, and the documentation claimed otherwise until a review caught it.**
Both are recorded here rather than rushed in at the end of a large change.

`excited.augment()` would add the orbitals a requested state needs when the
projected space does not already contain them. It is implemented and its
Rydberg exclusion is deliberate, but `run_cas_recommendation` never calls it:
its signature takes the projected pool while the runner holds the assembled
recommendation, and reconciling those wants its own tests. So the recommended
space does **not** currently change with the state count -- what changes is
what gets reported and what the verification looks for. On the benchmark set it
would have changed nothing, because the valence projection already contained
every predicted valence state, which is why section 8.4's numbers look as they
do; that is a fact about those molecules, not evidence that augmentation is
unnecessary. The method document, CHANGELOG and README all overstated this and
have been corrected.

`spec.rebuild_in_basis` is likewise proven (cas_09 rebuilds pyrrole's space in
four basis sets where an index handoff fails into aug-cc-pVDZ) and every
recommendation writes `active_space_spec.json`, but no runner reads it: a
follow-up CASSCF still reuses orbitals through `initial_orbitals_job_id`, the
basis-locked route that test exists to measure. The mechanism works; it is not
yet the path a user's job takes.

**P8.2 is written and type-checked but NOT verified in a browser.** This
project requires a real browser check for frontend changes, and that could not
be done here without overwriting a running deployment: nginx serves the *main
checkout's* `frontend/dist` through a host bind mount, so building this
worktree into a place the browser would see means replacing the dist the user
currently has live. The change compiles under the production build (`npm run
build`, which caught a null-safety error that `tsc --noEmit` on the plain
tsconfig did not), and the keys it renders are the ones a real recommendation
emits, checked directly against a runner call. It still needs someone to look
at it.

**Two elicitation scenarios were already failing before this plan started.**
`tests/backend/elic_01_draft_scenarios.py` scenario 5 (single_point/grad ends
up carrying `target_states: [1]` when it should carry only the basis) and
scenario 6 (single_point/nac asks for `n_excited_states` at step 2 where the
test expects something else) both fail identically at `2f1f58d`, the commit
this plan branched from. They are nothing to do with the active space and were
left alone rather than folded into an unrelated change; the rest of that file
is green.

**`reg2_01_registry_v2_payload.py` asserted a hardcoded capability-row count
of 15 against a registry holding 19.** That was fixed here rather than logged,
since it was a one-line stale literal in a file the rebuild had to touch
anyway, and `scripts/check_capability_matrix.py` is what actually guards the
matrix's contents.

**`active_01_named_orbitals.py` was asserting a phrase the note stopped
using.** It looked for "named orbitals" where the note says "set to the N
specific orbitals ... rather than letting the engine choose N around the HOMO".
Also failing at `2f1f58d`. Fixed here, for the same reason: the file had to be
touched anyway, and the assertion now checks what the note has to convey rather
than one phrasing of it.

## Phase 13: A lone pair is an sp hybrid on however many atoms it likes

Raised by the user while reading a refined space: "sometimes it's hard to
differentiate between sigma and n. even if you do it visually. some n orbitals
may appear as a mix between n and sigma. so if you are using a mathematical
threshold, it may miss n orbitals and label them something else."

That turned out to be true in **three independent places**, all failing in the
same direction and none of them raising an error. Each was looking for
something narrower than what a lone pair is.

- [done] P13.1: The reference directions are sp hybrids, not pure p lobes
  evidence: scripts/casbench/run_bench.py → "an orbital scoring 0.715 lone-pair character against an sp reference scored 0.019 against the pure p one the engine used; oriented hybrid keeps the literature match at 10/15 where a bare valence s drops it to 9/15"
- [done] P13.2: The orbital table stops calling a nitro lone pair sigma
  evidence: tests/backend/cas_11_lone_pair_labels.py → "9/9; re-classifying the user's own o-nitrophenol SA-5 jobs changes exactly two labels in each, both intended, and CAS(12,9) reads 4pi+2n+3pi* -- the space they guessed and were told otherwise"
- [done] P13.3: The refinement says what the orbitals are, with the weights
  evidence: app/chemistry/cas/refine.py → "orbital_characters returns labels AND continuous weights; sigma is a candidate so a sigma orbital can be named as one; genuinely ambiguous orbitals are labelled n/sigma rather than assigned"
- [done] P13.4: The re-seed rebalances the electron count
  evidence: app/chemistry/cas/refine.py → "reseed_lost_character recomputes nelec from donor/acceptor roles; uracil's 7 occupied + 2 virtual had only two pi* acceptors, too few for two pi->pi* states and an n->pi* together"
- [done] P13.5: The reported table and the handed-over orbitals are the same set
  evidence: app/chemistry/jobs/pyscf_runner.py → "natural_orbitals.molden written alongside orbitals.molden; occupations and characters describe the natural set while the restart set spans the same space with different orbitals"
- merged: -

**Why an oriented hybrid and not a bare valence s.** Three variants were
measured. A bare valence s detects as well as anything (0.715 on the orbital
above) but has no direction, so it matches an atom's sigma hybrids exactly as
well as its lone pair: formaldehyde fell from an exact (6e,4o) to (8e,5o) and
uracil's *minimal* tier grew from (14e,10o) to (30e,18o). Two oriented
references along the same direction detect identically and inflate identically,
which is the useful result -- **the pool grows with the NUMBER of targets
clearing the projector threshold, not with their orientation.** Detection and
pool size are coupled through that threshold, so the single oriented sp hybrid
is the variant that improves detection 17-fold and leaves every benchmark space
where it was.

**Why the orbital table needed a separate fix.** `app/chemistry/jobs/molden.py`
is not the CAS engine and shares no code with it. It labelled an orbital `n`
only if one atom carried more than 0.6 of the population, and a nitro,
carboxyl or carboxylate group holds its lone pairs as combinations across two
equivalent oxygens at about 0.45 each. Falling through to the shape test is
what produced `sigma`, because an in-plane lone pair is symmetric about the
molecular plane exactly as a sigma bond is. The discriminator is that a sigma
BOND sits on a bonded pair, and those oxygens are bonded to the nitrogen rather
than to each other.

**A caution recorded rather than fixed.** Uracil's refinement gave (14e,9o),
(14e,10o) and (14e,9o)-by-a-different-route across three runs of identical
setup. Whatever a single benchmark row says for it is one sample, not a settled
answer.

## Phase 14: The state average was not confined to one multiplicity

Found while asking why o-nitrophenol's n->pi* states were still labelled
pi->pi* after the orbitals holding them had been fixed. The transition density
matrices came back with every singular value at zero, which is what a triplet
looks like from a singlet ground state.

- [done] P14.1: Singlets only, in the engine, the verifier and the harness
  evidence: docs/CAS_ENGINE_METHOD.md → "section 11.1: o-nitrophenol CAS(12e,9o) at five roots had <S^2> [0.000, 2.000, 2.000, 2.000, 0.000]; constrained, all five are singlets, S1 becomes n->pi* as the user's own calculations have it, and the energies move 0.5 to 2.3 eV"
- [done] P14.2: Restate every excited-state number that predated it
  evidence: scripts/casbench/run_bench.py → "SC-NEVPT2 0.32 eV over 16 converged states, n->pi* 0.24 and pi->pi* 0.38, largest deviation +0.48 eV; replaces 0.29 eV which matched QUEST singlet references against partly-triplet roots and carried +-3 eV outliers"
- [done] P14.3: The budget counts roots, not just CSFs
  evidence: app/chemistry/cas/refine.py → "cost tracks n_csf * nroots; o-nitrophenol's narrowed CAS(22e,15o) is 497k CSFs but 3.97M root-CSFs over eight roots, and one cycle took two hours against a ten-minute cap"
- [done] P14.4: A mixed label is the classifier declining, not a mismatch
  evidence: tests/backend/cas_10_refinement.py → "characters_compatible treats mixed as a wildcard on the side it appears; treating it as a mismatch made the benchmark match acrolein's 6.68 eV reference to a root three electronvolts away"
- [done] P14.5: The rebalance cannot fire on an ambiguous occupation
  evidence: app/chemistry/cas/refine.py → "donor counting is gated on every kept orbital being outside [0.8, 1.2]; the bare >1.0 test was safe only under the contaminated solver, where triplet averaging left singly-occupied orbitals at 1.5-1.8"
- merged: -

**Why this was invisible for so long.** The production job runner has
constrained spin since the overhaul, with a CSF solver rather than `fix_spin_`,
and its own docstring already said "what the app was calling S1 was a triplet".
The recommendation engine, the verification CASCI and the benchmark harness
were all written afterwards and none of them inherited it, so the engine was
recommending and verifying against a different wavefunction from the one the
job would actually run. Nothing errored; the characters were simply wrong.

**It also fixed convergence.** Formamide, furan and pyrrole all failed to
converge before and now converge in roughly a fifth of the time. A state
average confined to one multiplicity is better conditioned than one mixing two,
so the "three molecules do not converge" caveat in an earlier draft of section
8.4 was a symptom rather than an independent limitation.
