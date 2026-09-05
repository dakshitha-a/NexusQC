# Tracker: auditing and hardening the CAS recommendation engine

**In motion, opened 2026-09-04.** Ten phases. The engine built by the previous
plan works; this one measures it, fixes what the measurement finds, and widens
the evidence under it.

It stays here rather than moving to [`trackers/`](trackers/) until the next
plan starts, which is when it gets archived and a fresh tracker takes its
place. **Exactly one tracker is active at a time.**

The one this replaces is
[`trackers/2026-09-cas-engine-rebuild.md`](trackers/2026-09-cas-engine-rebuild.md),
72 steps across fifteen phases, closed 2026-09-04.

## Rules (enforced by `scripts/check_tracker.py`)

- Step status is exactly one of `todo` | `in-progress` | `done`.
- A step may be marked `done` **only with an evidence field**: the
  verification script or command plus a one-line observed result.
- The tracker edit ships **in the same commit** as the step's final code
  change, so `git log --follow docs/TRACKER.md` is the audit trail.
- A phase's `merged` row records the commit hash the stage landed as.

### A change to perception is a change to everything downstream of it

Written after P2.5 was validated twice with the wrong set. It changed
`geometry.lone_pair_axes`, was checked against `--set spaces` and
`--set narrowed`, and both came back better, so it was called done. Neither of
those runs the refinement loop. `--set refine` showed uracil moving off its
literature space, and `cas_10`, which had not been run since before the change,
showed two assertions resting on a space that no longer existed.

Nothing about that was subtle. The regression set was chosen from the files the
diff touched rather than from what depends on the thing being changed, and
perception feeds the pool, which feeds every tier, which feeds the narrowing,
the refinement, the prune and every downstream energy.

So: **a change under `app/chemistry/cas/geometry.py` or `projector.py` is
validated against every `cas_*` test plus `--set spaces`, `--set narrowed`,
`--set refine` and `--set nevpt2`,** and the last two are hours, which is the
cost of changing perception and not a reason to skip them.

The same trap in miniature: `narrowing_agreement.py` first compared
`(n_electrons, n_orbitals)` and reported 34 of 34 agreeing. Two calls can
select the same NUMBER of orbitals and not the same orbitals. Compare the
thing you mean, not a summary of it.

---

## Why this plan exists

`docs/CAS_ENGINE_METHOD.md` is the method of record and its numbers are good:
10 of 15 literature spaces matched against the previous engine's 1 of 15, zero
basis dependence, open shells supported, 0.14 s for a full ground-state
recommendation, SC-NEVPT2 at 0.32 eV. None of that is in question here.

What is in question is what a seventeen-molecule benchmark of small, planar,
organic closed-shell molecules cannot see, and what reading the code against
its own documentation turns up.

**The measurement floor.** Section 11.4 records repeat runs of acrolein
differing by 0.29 eV on one root and tells the reader to treat anything below
0.3 eV as not measured. Every accuracy change worth making is smaller than
that, so the floor comes first.

**Code that is written, tested and not wired in.** `refine._narrow_to_states`
and `excited.augment` are reachable only from the refinement loop.
`spec.rebuild_in_basis` has no caller under `app/` at all, so
`active_space_spec.json` is written by every job and read by none.

**A basis asymmetry that costs the refinement its Rydberg states.**
`run_cas_recommendation` moves to `def2-svpd` when excited states are wanted;
`run_cas_refinement` runs the same TDA pre-pass and stays on `def2-svp`.

**Results that do not record what conditions them.** The refinement solves
`n_states + ROOT_MARGIN` roots and records only `n_states`.
`refine._spin_adapt` swallows an import failure, and an unconstrained state
average silently invalidates every character downstream of it.

**Calibration resting on two molecules**, both planar with carbonyl or nitro
oxygens, for the two constants that decide whether an orbital is a lone pair or
sigma.

### Decisions taken with the user before starting

- **Transition metals are out of scope** for this round and stay recorded as an
  untested axis in section 11.2. The edge-case work is organic.
- **Cost is reported, not enforced.** The engine shows the root-CSF estimate
  and the tier it implies and lets the user raise the budget, because long
  runtimes are the design premise here.
- **SC-NEVPT2 in process stays the only downstream metric**, which keeps the
  expanded benchmark to hours and keeps every number comparable with those
  already in the method document.

---

## Phase 0: The measurement floor

- [done] P0.1: Find out what the 0.3 eV floor actually is
  evidence: scripts/casbench/repeat_scatter.py → "at the harness protocol acrolein reproduces exactly over 5 repeats (E0 spread 0.001 meV, every root 0.000 eV, 5/5 converged); at refine._solve's shipped tolerances the same molecule moves 36 meV on E0 and 0.459 eV on root 5 and TWO roots change character, while pyscf reports converged=True on all five"
- [done] P0.2: Establish the mechanism rather than guessing at it
  evidence: scripts/casbench/repeat_scatter.py → "the identical loose protocol pinned to OMP_NUM_THREADS=1 reproduces exactly, so the cause is BLAS reduction order and a tolerance loose enough to let it survive; conv_tol 1e-10 converges 0/5 and returns the full scatter back, so tightness is not monotone and the criterion has to be reachable"
- [done] P0.3: Tighten the shipped refinement solver
  evidence: app/chemistry/cas/refine.py → "_solve moves from conv_tol=1e-6 with no gradient tolerance and 50 macro-iterations to 1e-8 / 1e-5 / 100; measured cost is 4.1 s mean against 3.3 s median on the same eight threads, so it is not a speed against accuracy trade"
- [done] P0.4: Confirm the refinement loop itself now reproduces
  evidence: scripts/casbench/repeat_scatter.py --molecule uracil --mode refine --repeats 3 → "the refined space is (14e,10o) all three times, with an identical rotation trail, identical orbital labels, identical root characters and excitation energies agreeing to 0.6 meV, against the (14e,9o)/(14e,10o)/(14e,9o) the previous tracker recorded for three runs of identical setup; convergence still flips at 1 of 3 and cost varies 282/926/974 s, reported rather than fixed"
- [done] P0.5: A committed results ledger under docs/casbench/
  evidence: scripts/casbench/ledger.py → "run_bench.py --set spaces writes docs/casbench/spaces.md at the commit that produced it; markdown rather than a JSON dump because check_public_safe.sh scans tracked files for machine-generated data and a table diffs readably where a re-serialised blob does not"
- [done] P0.6: The harness refuses to score a non-converged row
  evidence: scripts/casbench/run_bench.py → "the headline SA-CASSCF and SC-NEVPT2 MAE are now taken over converged rows only, where they used to average every row and mention the non-converged ones afterwards, which put the unreliable number where everyone quotes it and the reliable one in a footnote. Excluded molecules are named WITH the number of states dropped, so a shrinking denominator cannot pass for an improving mean, and a set where nothing converged prints NOTHING SCORED rather than a mean of an empty list. The character split and the worst-deviation list inherit the same rule"

## Phase 1: Wire what is written, and fix what the audit found

- [done] P1.1: Narrowing moves into the quick recommendation
  evidence: tests/backend/cas_13_narrowing.py → "9/9; uracil's quick tier goes from CAS(22e,14o) to CAS(14e,10o), its literature space, at 4,950 CSFs against 41,405, and pyrrole reaches (6,5) as the recommendation rather than only as a tier; formaldehyde does not move and a ground-state request narrows nothing"
  design as built: `_narrow_to_states` needs the TDA analysis,
  and `recommend()` runs before the TDA does (`pyscf_runner.py:2489` against
  2500 onward), so the integration point is the RUNNER and not `recommend()`.
  After `analysis` exists, call the narrowing and, when it strictly shrinks the
  space, add a FOURTH tier named `state-narrowed` and repoint
  `Recommendation.recommended` at it. Do not redefine what the existing
  `recommended` tier contains: `Tier` and `Recommendation.to_dict` feed the job
  summary, the frontend, `active_space_spec.json` and
  `check_capability_matrix`, and `cas_05_tiers.py` asserts
  `minimal <= recommended <= maximal` by name, which stays true when the pool
  keeps its name and only the pointer moves. Extract the function into its own
  module so `refine` and the runner share one copy. Regression cases are uracil
  and o-nitrophenol. While in there, `_narrow_to_states`'s docstring says "one
  lone-pair orbital per centre" where the constant is
  `LONE_PAIRS_PER_STATE = 2` and section 9.5 says two per state.
- [done] P1.2: The refinement analyses in a basis that can see Rydberg states
  evidence: app/chemistry/jobs/pyscf_runner.py → "run_cas_refinement took basis from CAS_RECO_DEFAULT_BASIS unconditionally, so its own TDA pre-pass ran in def2-svp while the recommendation that produced its starting space ran in def2-svpd; it now follows the same rule the recommendation does"
- [done] P1.3: Augmentation is wired into the quick tier or withdrawn from the docs
  evidence: docs/CAS_ENGINE_METHOD.md → "withdrawn. The pipeline diagram in section 4 showed character -> augmentation in the QUICK path, which was never true: augment needs natural transition orbitals against a solved space and is reachable only from the refinement loop. The quick path gained narrowing instead, which is a priori and shrinks rather than grows. Wiring augmentation there was not the missing lever either, since 10.9 shows the states were unreachable because the lone-pair target aimed at the wrong orbital, which no amount of adding orbitals afterwards would have repaired"
- [done] P1.4: run_cas_refinement reads the spec it was pointed at
  evidence: tests/backend/cas_15_spec_handoff.py → "19/19. A refinement now resolves `active_space_source_job_id` to that job's active_space_spec.json, checks the geometry against it BEFORE building a mean field, takes the projection threshold from it, and calls `rebuild_in_basis` as its first caller anywhere under app/. It reports `spec_used`, `source_selected_tier` and `source_selected_space`, so a fallback can no longer read as a handoff. A moved geometry (0.5 A, ten times the tolerance) and a different molecule are both refused with the spec module's own message; a missing artifact or no source job falls back to re-deriving, with a named note saying so"
  design as built: three things had to be fixed underneath it before reading
  the spec meant anything.
  **`selected_tier` was always the literal string `"recommended"`.**
  `spec.build` takes `tier="recommended"` as a default and NEITHER runner
  overrode it, so every specification ever written claimed the pool tier even
  when `rec.recommended` had moved to `state-narrowed`. Both call sites now
  pass `tier=rec.recommended`.
  **That fix creates a trap, and `rebuild_in_basis` had to be fixed with it.**
  The rebuild reproduces the POOL: it projects the recorded targets, and that
  is the whole of what a specification can carry. `minimal` is a cut through an
  entropy ranking and `state-narrowed` needs a linear-response analysis of the
  requested states, which is a property of a calculation rather than of a
  geometry. So comparing the rebuild against an honest `selected_tier` would
  report "gives CAS(22e,14o) where it recorded CAS(14e,10o)" on every narrowed
  specification, forever, describing the narrowing working as a basis
  dependence. The comparison is against the pool tier and the difference is
  explained in a note instead.
  **The specification recorded the wrong targets for every molecule with no pi
  system.** Found by writing the test on water rather than on cas_09's pyrrole.
  See the entry under "Found along the way"; `Recommendation` now carries the
  targets it was actually projected onto and both runners write those.
  The start tier is deliberately NOT taken from `spec.selected_tier`. The
  refinement's own `rec` has no `state-narrowed` tier -- only
  `run_cas_recommendation` builds one -- so feeding the name in would index a
  tier that is not there. The drift is measured and reported instead, which is
  what P1.10 exists to remove.
- [done] P1.10: One narrowing, not two
  evidence: scripts/casbench/narrowing_agreement.py → "34 molecules, 34 agree, 0 differ, compared on the sorted ORBITAL INDICES rather than on the space size. The first version of the script compared (n_electrons, n_orbitals) and reported the same 34 of 34, which was true and did not mean what it was used for: two calls can select the same NUMBER of orbitals and not the same orbitals, and a refinement started from a different set of ten columns is a different refinement. Re-measured at index level it still agrees everywhere, so the unification is a simplification rather than a behaviour change. The measurement also showed WHY they could not disagree in practice: `nroots` is read in exactly one place inside `narrow_to_states`, the `fits` backstop `c * max(nroots,1) <= csf_budget`, so under the recommendation's infinite budget it cannot affect the result at all and the two call sites' disagreement about it was never reachable. The recommendation runner's inline block moves to `narrow.add_state_narrowed_tier`, both runners call it, and `refine()` now defers to a published `state-narrowed` tier instead of deriving its own from its own TDA analysis in its own basis. cas_13 9/9 unchanged"
  design as built: the two arguments that differed had to be chosen, not
  measured, because the measurement only proves they do not currently matter.
  `csf_budget` is the recommendation's infinite one, on the principle the
  recommendation runner already states: a space is chosen on chemistry and
  then costed, never silently shrunk to fit a number the user never chose.
  `refine()` keeps its own finite budget for TIER SELECTION, which is where a
  space that cannot actually be run has to be caught; what it no longer does is
  let that budget quietly change which orbitals the chemistry picked. With the
  budget infinite, `nroots` is unreachable, so it needed no decision at all.
  The recompute path stays for a library caller and for a ground-state request,
  neither of which has a published tier to inherit.
  The refinement narrows to the requested states itself, inside `refine()`,
  from its own TDA analysis in its own basis with `nroots=expected_roots` and a
  finite `csf_budget`. The recommendation narrowed separately, in the runner,
  from a different analysis with `nroots=n_states` and an infinite budget. Two
  independent computations of one quantity, and nothing makes them agree; P1.4
  added the note that fires when they do not. Unifying them forces a choice on
  both the root count and the budget, so one side's behaviour changes and the
  change has to be measured rather than assumed: uracil and o-nitrophenol are
  the regression cases, `--set refine` is the measurement, and the note P1.4
  added is how to tell whether the disagreement was ever real in practice.
  Deliberately not bundled into P1.4, on the precedent of the prune guard.
- [done] P1.5: Record the solved root count, and stop swallowing a spin-adaption failure
  evidence: scripts/casbench/repeat_scatter.py → "a pyrrole refinement now reports n_states_requested 3 alongside n_roots_solved 6, where the summary previously carried only the request; _spin_adapt returns whether the constraint was applied and a failure becomes a note on the result rather than silence"
- [done] P1.8: A prune cannot lose a state the space never had
  evidence: tests/backend/cas_10_refinement.py → "19/19 with the guard now comparing against chars_before, which it already received and already used for the drift test; uracil's occupation-cut negative control still passes at four and six roots with occupations [1.981, 1.954] and [1.976, 1.936]"
- [done] P1.9: Augmentation reads the wrong orbitals after a narrowing
  evidence: app/chemistry/cas/refine.py → "the call site sorts the named orbitals into the active window before augment reads it, so the slice it takes and the caslst rebuilt after it both name the active space; cas_10 19/19 and cas_12 6/6"
- [done] P1.6: The orbital-identity audit, asserted by projection not by position
  evidence: tests/backend/cas_12_orbital_identity.py → "6/6; pyscf's default HOMO-centred window spans the recommended space exactly (overlap 6.0000 of 6) because the projector puts the active block at the occupied/virtual boundary and its ncore agrees, a window shifted by one orbital scores 5.000 so the test can fail, and the restart and natural-orbital sets span the same space while not being the same orbitals one by one"
- [done] P1.7: The two orbital classifiers are checked against each other
  evidence: scripts/casbench/classifier_agreement.py → "103 of 126 comparable orbitals agree, 82%, and all 23 disagreements are structural. 20 are the projection saying n where the reflection test says sigma, which it must: an in-plane lone pair and a sigma bond are both a' under reflection in the molecular plane, so that test cannot separate them and its `sigma` means 'a', not pi'. The other 3, water, H2S and furan, are the projection saying pi where the reflection says n, which is the same orbital twice: an out-of-plane lone pair IS the pi orbital and geometry.perceive deliberately declines to emit it as both. Neither classifier needs changing; docs/casbench/classifiers.md records what each can and cannot see"

## Phase 2: The benchmark the edge cases need

- [done] P2.1: Non-planar heteroatoms
  evidence: scripts/casbench/reference_data.py → "five molecules added, geometries optimised at RHF/def2-SVP from an RDKit start; the planarity test reads 0.373 at ammonia's nitrogen and 0.451 at methylamine's, both past the 0.25 cut, so neither emits a pi target and the pool is lone pairs and sigma alone; hydrogen sulfide reaches its conventional (8e,6o) and ammonia its (8e,7o)"
- [done] P2.2: Diradicals and bond breaking
  evidence: scripts/casbench/reference_data.py → "square cyclobutadiene (4e,4o), trimethylenemethane (4e,4o) as a triplet through the ROHF path, twisted ethylene (2e,2o) and N2 stretched to 1.60 A at (10e,8o) all match their spaces exactly, 4 of 4; ozone is carried with no reference space because the published choices run from (12e,9o) to (18e,12o) and picking one would score the engine against a preference"
- [done] P2.3: Larger conjugated systems and charged species
  evidence: scripts/casbench/run_bench.py --set spaces → "nine molecules added, 8 of 9 exact. The large conjugated systems all match their full pi space: naphthalene (10,10), hexatriene (6,6), octatetraene (8,8) and anthracene (14,14), the last in 6.1 s, so selection does not degrade on the large planar systems section 11 flags as the weak axis. The benchmark's first charged species all match too: allyl cation (2,3), allyl anion (4,3), cyclopentadienyl anion (6,5) and tropylium (6,7). The allyl pair is the real check and it passes as a RELATION rather than as two separate rows: same geometry, same three orbitals, anion exactly two electrons above cation, so the charge is carried through the selection rather than dropped. Legacy returns (16,11) and (14,10) for the same two. The one miss is pyridinium, and it is the molecule that was added to look for exactly that miss; see the entry under Found along the way"
- [done] P2.4: Scoring that fits the new classes
  evidence: scripts/casbench/run_bench.py --set spaces → "one table with a class column and per-class subtotals rather than separate ledgers, because the set has now grown three times mid-plan and an overall fraction alone cannot tell a reader whether a change came from the engine or from the denominator. Overall 23/30 exact, 24/30 exact or as a tier; core 7/13, non-planar 3/3, diradical 5/5, conjugated 4/4, charged 4/5. The charged class additionally carries a relational check the exact/tier verdict cannot express, since an engine that drops the charge scores one of the allyl pair right by accident"
  the subtotals immediately raised a question they had to be made to answer.
  Core scores 7/13 while every newer class is near-perfect, which reads as the
  engine being better on the molecules it was NOT built against. It is a
  protocol artefact and the run now says so in its own output. `--set spaces`
  runs the ground-state recommendation, `recommend_new` passes no `n_states`,
  so the state-narrowing never fires; several core references are excited-state
  spaces that are only reached once states are requested, which is uracil's
  (14,10) and pyrrole's (6,5), exactly what `cas_13` asserts. The conjugated and
  charged references are plain pi spaces needing no narrowing. A per-class
  number without that caveat beside it would be read as a claim about
  chemistry.
- [done] P2.5: A planar three-coordinate heteroatom emits a lone pair it does not have
  evidence: scripts/casbench/run_bench.py --set spaces and --set narrowed → "measured on the same 30 molecules before and after: 23/30 exact becomes 25/30, core 7/13 -> 8/13 and charged 4/5 -> 5/5, with non-planar, diradical and conjugated all unmoved. Two molecules move and both move TO exact: pyridinium (8,7) -> (6,6), which is the case it was found on, and pyrrole (8,6) -> (6,5) unprompted, so pyrrole now reaches its literature space in the ground-state protocol where it previously needed states requested. The regression case holds: uracil still lands on (14,10) in --set narrowed, narrowing from an (18,12) pool rather than (22,14), so it is the same answer from a cheaper start; furan is unchanged at (6,5). Formamide goes (10,6) -> (8,5), still scored 'differs' against the recorded (8,7), but its electron count is now exactly right where it was two over, and reference_data's own note on this molecule says the reference's description names five orbitals against a recorded count of seven and that (8e,5o) reproduces the chemistry as stated. The condition delegates planarity to local_pi_normal rather than re-deriving it, so a centre cannot be planar enough to emit a pi target and pyramidal enough to emit an in-plane lone pair at once"
  **correction, and the evidence line above is narrower than it reads.** It
  says the regression case holds, on `--set spaces` and `--set narrowed`.
  Neither of those runs the refinement loop, so neither could see a change to
  the REFINED space, and there is one: `--set refine` at the ledger protocol
  gives uracil $(18,12) \to (12,9)$ where the committed ledger had
  $(22,14) \to (14,10)$. Uracil is the only molecule in 30 that loses an exact
  match, and no molecule gains one on this path, so on the refinement path P2.5
  costs one where on the quick path it gains two. The claim as written was
  true of what was measured and should not have been stated about the
  refinement without running it; validating a perception change on the quick
  tier alone is not sufficient, because the prune is downstream of it.
  The mechanism is in "Found along the way" and the decision belongs to P4.2.
  found while running it: `cas_02_projector_invariance` carried pyrrole as
  (8e,6o) under the heading "textbook valence pi spaces", and that was never
  the textbook answer. Pyrrole's pi space is the five ring orbitals holding six
  electrons, which is what `REFERENCE_SPACES` carries and what Thiel uses; the
  sixth orbital was the spurious lone pair. The line was the engine's own
  output written down as the reference, so the assertion agreed with whatever
  the engine did and tested nothing. Benzene's and butadiene's entries were
  checked against the literature at the same time and are correct.

## Phase 3: The benchmark runs the product's protocol

- [done] P3.1: The refinement benchmark runs the basis the product runs
  evidence: scripts/casbench/run_bench.py → "set_refine moves from cc-pvdz to def2-svpd, matching what run_cas_refinement picks whenever excited states are requested; cas_06 confirms def2-svpd is Rydberg-capable, so pyrrole's 5.24 eV and furan's 6.00 eV Rydberg references become visible to the measurement for the first time. set_nevpt2 deliberately stays in cc-pvdz: it scores energies against published references and moving its basis would make section 10.4 incomparable"
  the recommendation and the refinement CASSCF cannot be decoupled into two
  bases, which is worth recording because it looks like the obvious fix and is
  not one. The excited-state analysis hands the refinement natural transition
  orbitals as coefficient vectors and `augment` projects those against the
  active orbitals; in two different bases they do not have the same length.
- [done] P3.2: Ask the calculation, not the basis set's name, whether a Rydberg state can be described
  evidence: tests/backend/cas_06_excited_character.py → "19/19; def2-svpd is now recognised as able to describe a Rydberg state and one is actually found in it, where the exponent rule called the engine's own default analysis basis non-diffuse"
- [done] P3.3: Rydberg states that are correctly absent from a valence space
  evidence: tests/backend/cas_10_refinement.py → "a predicted Rydberg state was filtered out of the state audit in silence, which is the right thing to do with it and the wrong way to report it: the loop must not chase a state augment skips by design, but 'all predicted present' then meant either that everything asked about is described or that the one state that mattered was dropped before anything was checked. It is now a distinct outcome, logged, carried on the result as states_not_looked_for and explained in a user-facing note. Formaldehyde in def2-SVPD predicts n->Rydberg and reports exactly that; 22 passed, 0 failed"

## Phase 4: Threshold sensitivity

- [done] P4.0: The lone-pair s-amplitude, the first constant with a measured plateau
  evidence: docs/casbench/phase4-sp-amplitude.md → "the literature match is flat at 11/17 exact for every amplitude from 0.35 to 0.85 and only the pure-p end is worse at 9/17, so the 0.577 in use sits mid-plateau and is not delicate; the threefold differences in detected lone-pair weight never reach the selection"
- [done] P4.4: The lone-pair target aims at the lone pair the state uses
  evidence: scripts/casbench/amplitude_tradeoff.py and scripts/casbench/irrep_gate.py → "LONE_PAIR_S_AMPLITUDE 0.577 -> 0.20 (renamed from SP2_S_AMPLITUDE). Every n-type state's hole capture improves, uracil 0.363 -> 0.759 and formamide 0.651 -> 0.833, with every pi->pi* unchanged at 0.998+. Uracil's n->pi* is found at root 2 and 9.03 eV where it was absent from eight roots, and formaldehyde, acetone, acrolein and formamide find theirs 3 to 4 eV lower. Counts hold at 15/21 ground state and 18/21 states-requested; the whole cost is pyrrole's ground-state tier match, which 0.05 and 0.10 would keep but which flips twice across the sweep and so is not used to choose. p-benzoquinone is not recovered"
- [done] P4.1: The remaining perception and pool constants, swept on the quick tier
  evidence: scripts/casbench/constant_sweep.py → "projector.THRESHOLD is flat at 15/21 from 0.05 to 0.40, a factor of eight, and it decides pool size for everything downstream; geometry.PLANARITY_COS flat 0.10 to 0.50; geometry.BOND_TOLERANCE flat 1.15 to 1.50. recommend.MINIMAL_ENTROPY_GAP is NOT flat, giving 17/21 inclusive at 0.05 and 0.10 against 15/21 at the shipped 0.15 with the exact count unmoved, replicated, and very likely the lever that restores the pyrrole tier the lone-pair correction cost. Not applied: it decides which tier is minimal, which feeds the refinement start tier and the cost report, so it needs its own validation pass. Also found that the count metric carries +/-1 molecule, entirely from twisted ethylene, whose RHF reference is qualitatively wrong for a singlet diradical"
- [done] P4.2: Refinement constants, swept on a named subset and then on the whole set
  evidence: scripts/casbench/refine_constants.py and scripts/casbench/drift_full_set.py → "MAX_ENERGY_DRIFT_EV stays at 0.20 eV. The six-molecule grid over drift {0.10, 0.20, 0.30, 0.50} eV and occupation window {1.95, 1.98, 1.99} is flat for four of six, and uracil is not flat but NON-MONOTONE: (14,10) at both 1.95 and 1.99 and (12,9) only at the shipped 1.98, which places the pruned orbital's occupation between 1.98 and 1.99. Because five of those six cannot move at any setting, the grid was really an experiment on one molecule, so the drift tolerance was re-run over the entire refinement set at 0.10 eV. Of the 34 molecules that refine, EXACTLY ONE changes: uracil (12,9) -> (14,10), the literature space. Every other space, rotation trail and convergence flag is identical, and the two that do not refine (anthracene exhausts memory on its CI diagonal, p-benzoquinone reaches the 600 s cap) fail identically at both tolerances. So 0.10 would damage nothing, but the constant is unconstrained by 33 of 34 molecules and the whole case for moving it is the one molecule already shown to be non-monotone in this very parameter and, by P6.1, reproducible in three basis sets rather than noisy. Moving it would be fitting a global constant to one knife-edge reference, which is what P4.0 and P4.4 refused for the lone-pair amplitude. Reported in CAS_ENGINE_METHOD 3.8 rather than tuned away. ROOT_MARGIN is not swept here; cite P6.2"
- [done] P4.3: The n/sigma pair, on the molecules it was never set against
  evidence: scripts/casbench/lone_pair_scale.py → "the threshold should NOT be element-aware and the observation that prompted the question was not about elements. N and O medians are 0.582 and 0.573, nearly identical, S is HIGHER at 0.728 rather than lower, and the spread within nitrogen (0.234 to 0.977) is wider than any between-element difference. The driver is delocalisation: H2S 0.913 -> methanethiol 0.728 and ammonia 0.977 -> methylamine 0.728, the same shift on two elements from one methyl. Every orbital labelled n/sigma is an aromatic heteroatom whose lone pair is conjugated into pi (furan O 0.287, uracil amide N 0.330, pyrrole N 0.441), where a low in-plane weight is the correct answer and an element-aware threshold would be wrong about all three"

## Phase 5: Cost reported, not enforced

- [done] P5.1: The root-CSF estimate and its tier reach the user before the job runs
  evidence: app/chemistry/jobs/pyscf_runner.py → "every recommendation now carries a refinement_cost block: roots a refinement would solve, root-CSF per tier, whether each fits the default budget, and which tier a refinement would start from. Uracil at three states reports its narrowed tier at 29,700 root-CSFs against the pool's 248,430, so the saving is visible before anyone submits anything"
- [todo] P5.2: Adding roots becomes the first response to a missing state
  Blocked by the span finding above, and the blocking is the point: uracil, the
  molecule ROOT_MARGIN was set for, does not contain its own n->pi* state at
  any root count, so a reordering measured against it would have been tuned on
  a state that is not there. It waits on the hole-seeded rotation.
- [done] P5.3: Why uracil reports no n->pi* root, settled rather than filed
  evidence: scripts/casbench/hole_capture.py → "the hole of the very state the
  narrowing was performed for is 0.376 inside uracil's narrowed space against
  0.999 for its pi->pi*, and formaldehyde, the control, is 0.520 with 36% of
  its n->pi* hole on a column labelled sigma; a singlet-constrained CASCI in
  the seeded space confirms it, holding both n orbitals at occupation 2.000 in
  every root while the explicit A'' block sits at 15.85 eV"

## Phase 6: Two sensitivities never measured

- [done] P6.1: Is the refined space the same in three basis sets
  evidence: scripts/casbench/refine_basis.py → "yes, on all three molecules. formaldehyde (6,4), pyrrole (6,5) and uracil (12,9) come back identical in def2-svp, def2-svpd and cc-pvdz, with natural occupations agreeing to about 0.005 -- uracil's nine are [1.974, 1.938, 1.835, 1.811, 1.668, 1.665, 0.638, 0.366, 0.105] against [1.975, 1.940, 1.835, 1.813, 1.671, 1.665, 0.643, 0.360, 0.099] and [1.974, 1.939, 1.835, 1.811, 1.672, 1.665, 0.639, 0.363, 0.102]. Uracil takes the same narrow+prune route in every basis, 213.9 s, 474.0 s and 180.0 s"
  why this was a real question and not a formality: section 5 makes the
  RECOMMENDATION basis independent by construction, because the targets live in
  a fixed minimal basis, and 10.7 measures it. Nothing extends that to the
  refinement. Every reading the refinement edits the space on -- orbital
  character, state presence, natural occupation -- comes from a correlated
  wavefunction computed IN a basis, so an occupation sitting near the prune
  threshold could fall either side of it in two bases that describe the
  molecule equally well. It does not.
  what it settles for P4.2: uracil's prune is not a knife edge in the basis.
  The same orbital is dropped in all three, and the highest occupation left is
  1.974 against the 1.98 cut. So the disagreement with the literature (14,10)
  is a reproducible property of the engine's own criteria rather than numerical
  noise, and a drift tolerance moved to recover (14,10) would be fitting to the
  reference rather than to the physics.
- [done] P6.2: Root-count sensitivity, recorded with every reference
  evidence: scripts/casbench/root_count.py (ROOT_MARGIN 0/3/6, six molecules, def2-svpd, three states) → "five of six are identical at every root count: formaldehyde (6,4), acetone (6,4), formamide (8,5), pyrrole (6,5) and furan (6,5). Uracil is the exception and its exception is not scorable: (14,10) at margin 0 but conv=False after 1843 s, (12,9) at margins 3 and 6, both converged in 544 s and 445 s. P0.6's rule is that a non-converged row is not scored, so among converged runs uracil is root-count stable too. The surprise is the direction of the cost: MORE roots ran FASTER and converged where fewer did not. Formamide takes 103.6 s and fails to converge at margin 0 against 3.2 s converged at margin 3; acetone goes 86.0 -> 21.0 -> 14.5 s; uracil 1843 s non-converged -> 544 s converged. ROOT_MARGIN's own comment presents the margin purely as a cost to be justified, and on this evidence it is buying convergence rather than spending time"
- [done] P5.2: Adding roots becomes the first response to a missing state
  evidence: scripts/casbench/root_count.py → "WITHDRAWN, on the measurement, the way P1.3 was. Reordering the loop to add roots before reseeding is only worth doing if adding roots ever recovers a state that fewer roots missed, and across six molecules at three root counts it never does: every molecule finds exactly the same states at margin 0, 3 and 6. Uracil is the decisive case because ROOT_MARGIN exists for it -- its comment says the n->pi* 'only appears once about six roots are solved for' -- and uracil now finds BOTH requested states at margin 0, with the n->pi* at 5.021 eV in the first excited root. That justification was written before P4.4 corrected the lone-pair amplitude, when 10.9 shows the state was not in the space at any root count, so it was measured against a state the space did not contain. It is now the lowest excited root and there is no missing state for extra roots to find. This does NOT license removing ROOT_MARGIN: P6.2 shows the margin buys convergence and speed, which is a separate question and belongs to P4.2"

## Phase 7: Acrolein

- [done] P7.1: Is acrolein's missing orbital a defect or a gap in the reference
  evidence: docs/CAS_ENGINE_METHOD.md → "section 10.1: the reference's description names five orbitals, its recorded count is seven, and the engine returns six, so no two of the three agree; the engine matches the recorded ELECTRON count exactly and is one VIRTUAL short, and acrolein's four-orbital pi system has no third pi* to supply it, which is formamide's situation exactly"

## Phase 8: The refinement drawer

- [done] P8.1: Build the refinement drawer, then drive it in a real browser
  evidence: tests/frontend/cas_14_refinement_drawer.spec.mjs → "17/17 against the live stack; a real water refinement renders its refined space, a natural-orbital table carrying occupations, characters AND the continuous weights, and a rotation trail naming the orbital, its occupation and the reason, with both orbital-set conventions stated and nothing drawn twice"

## Phase 9: Re-run whole and close out

- [done] P9.1: Every set re-run on the final code, into the ledger
  evidence: scripts/casbench/run_bench.py --set refine and --set nevpt2 → "both re-run on the corrected constant and both wrote their first ledger, docs/casbench/refine.md and nevpt2.md. Refinement: 25/27 inside the cap, uracil (22,14) -> the literature (14,10) with 2/2 states found and converged. Downstream: SC-NEVPT2 MAE 0.30 eV over 18 converged states against a 0.32 eV baseline over 16, and on the 16 states the baseline itself scored the figure is 0.32 both times, identical rather than merely flat within the floor. The whole change is coverage: 11 of 12 molecules converged against 10, n->pi* states scored 5 -> 7 with both additions being p-benzoquinone's at errors 0.14 and 0.23 eV, and uracil's n->pi* scored against its TBE for the first time at +0.36 eV. spaces/narrowed/stability not re-run"
- [done] P9.2: Sections 10 and 11 restated, BACKLOG.md updated
  evidence: docs/CAS_ENGINE_METHOD.md → "10.1 carries the +/-1 from twisted ethylene and the pyrrole tier loss, 10.4 the new downstream numbers and the coverage table behind them, 10.6 is now a refinement result at the production protocol, 10.9 is new and carries the span finding and its fix, and 11.2 no longer claims the constants are unswept or the n/sigma band untested, both of which were measured. BACKLOG.md closed the lone-pair target and p-benzoquinone entries and opened three: MINIMAL_ENTROPY_GAP, twisted ethylene's irreproducibility, and the state audit on large planar spaces"
  restated after P2.3 and P2.5, which moved the denominator and one of the
  claims. 10.1 now reads 25/30 exact for a ground-state request with per-class
  subtotals and the protocol caveat attached, and 27/30 with states requested;
  the arm's-length caution is extended to the fifteen molecules added during
  2026-09 and says what each new class actually tests rather than counting
  them. The paragraph recording pyrrole's tier match as the cost of the
  lone-pair correction is corrected: the cost was recovered, and not by the
  amplitude route 10.9 expected, so that section's warning against tuning the
  amplitude to it still stands untouched. 4.2 carries the pyramidal condition
  and why the planar case is ill-posed rather than merely imprecise.

## Phase 10: The surfaces around the engine

Added mid-plan at the user's request: "check the elicitation path for it too,
make sure the capability matrix is updated and basically everything related to
cas reco is audited and updated to fit the new method." The engine was rebuilt
and its runner and tests were kept honest throughout; what nobody had walked
was everything that *describes* the engine to a user or to the model. Three of
those surfaces were still describing the engine that was replaced.

- [done] P10.1: The agent stops telling users the deployment cannot recommend a space
  evidence: tests/backend/casreco_04_literature_step.py → "search_active_space_literature built its capability line by asking the registry about the autocas and avas subtypes, both retired with the legacy engine. capability_answer returned unsupported for each, the options list came back empty, and the tool emitted 'This deployment cannot run an active-space recommendation job' on EVERY call while cas_reco and cas_reco/refine were both supported and running; its docstring and NEXT STEP text then told the model to offer a choice between the two dead subtypes. casreco_04 passed throughout because it read only that a ToolMessage carrying the findings came back and never looked at the capability line in the same message. Now asserted on substance rather than wording, verified to fail on the old code at 34/36 and pass at 36/36. check_capability_matrix cannot catch this class: it checks the matrix against its golden table, not that a caller names subtypes that still exist"
- [done] P10.2: The elicitation path describes narrowing, not the widening it replaced
  evidence: app/chemistry/registry2/params.py and tasks.py → "the n_states warning told users that if the selected space cannot host the requested roots it is 'widened along the entropy ranking until it can', which is AutoCAS's F-020 behaviour and the exact opposite of what runs: the rebuilt engine analyses the requested states and NARROWS to the orbitals they are built from, which is how uracil at three states reaches CAS(14e,10o) from CAS(22e,14o). The cas_reco task description did not mention the narrowing at all, though it is what changes the answer whenever states are requested. A stale reference to the same two retired subtypes in job_watcher's docstring went with them"
- [done] P10.3: The literature search keeps its guardrail and loses its cost
  evidence: tests/backend/casreco_04_literature_step.py → "42/42, six new assertions. The user asked whether to drop the step, since it usually comes up empty; it stays, because the empty outcome IS the guardrail against the cyclooctadiene substitution this module was written for, and the cost was paid down instead. Every tier ran against every backend, so one recommendation issued up to nine searches. The open web is no longer built (its own tier comment records it as the noise source: it answers almost any string); a hit in the user's uploaded papers at the NARROWEST tier now skips the network entirely, while a hit only at a broader tier still runs it, since matching after the basis and state count were dropped carries less information; and the roughly seventy-word not-found disclaimer no longer rides into the job summary and back out at report time, where job_watcher's notice already says what to do with an empty result. The full text still reaches the model at search time, when it is about to propose a space, and a FOUND note is not shortened"

---

## Found along the way

**Uracil reached its literature space because a prune failed, and once the
prune succeeds it does not.** The single cost of P2.5, found by running
`--set refine` after the fact rather than by the two sets P2.5 was validated
on.

The committed ledger had uracil at $(22,14) \to (14,10)$, stopping with "the
prune was rejected and undone: the ground state rose 11.1 mHartree (0.30 eV)".
So the literature space was where the loop *stopped*, not where it decided to
stay. After P2.5 the same molecule runs $(18,12) \to (12,9)$ and stops with
"reached a fixed point: every orbital carries correlation": the narrowing still
produces a ten-orbital space, `narrowing_agreement.py` confirms that, but two of
its orbitals are now inert enough that removing them costs less than the 0.2 eV
drift tolerance, and the prune is accepted.

The orbitals changed even though the count did not. Before, the ten were
selected out of a fourteen-orbital pool containing two columns built on
spurious amide lone-pair targets; now they are selected out of twelve honest
ones. A prune that cost 0.30 eV against the first set costs less than 0.2 eV
against the second.

**Both readings are defensible and the measurement does not settle it.** On the
engine's own criteria $(12,9)$ is correct: both requested states are still
found, the solve converges, and the energy drift is inside tolerance. On the
literature's, $(14,10)$ is the answer. What is NOT a defence of $(14,10)$ is how
it used to be reached, and P1.8 wrote that down in advance: "a space that
reaches the literature answer by way of a guard misfiring is not evidence the
guard is right." That note was about the state-loss guard rather than the drift
test, but it applies unchanged here.

Two things made this a P4.2 question rather than something to fix on the spot.
The rejection that used to preserve $(14,10)$ was at 0.30 eV, which is the value
section 11.4 documented as the measurement floor before P0.3 tightened the
solver, so the old rejection may itself have been noise. And the fix available
is to move the drift tolerance, which would be fitting a constant to one
molecule -- the thing P4.4 explicitly refused when uracil alone would have
chosen an amplitude of 0.35.

**P4.2 has now settled it: the tolerance stays at 0.20 eV and $(12,9)$ stands.**
Re-running the whole refinement set at 0.10 eV moves exactly one of the 34
molecules that refine, and that molecule is uracil. Nothing else in the set
constrains the constant at all, so the only evidence for changing it is the
molecule the change is meant to fix, which is the definition of fitting to the
reference. P6.1 independently removed the noise explanation by reproducing the
same prune in three basis sets. The disagreement is therefore recorded in
`CAS_ENGINE_METHOD` 3.8 as a real property of the engine's criteria rather than
tuned out of existence.

**A planar three-coordinate heteroatom is given a lone-pair target it does not
have, and the direction it is given is numerically arbitrary.** Found by
pyridinium, which was added to P2.3 for precisely this reason and is the only
one of the nine new molecules that misses.

The engine returns CAS(8e,7o) for pyridinium, which is pyridine's space exactly,
against a reference of the six ring pi orbitals CAS(6e,6o). Protonating the
nitrogen gives it a third sigma bond and leaves it no in-plane lone pair, so the
two molecules should not get the same answer, and the extra orbital is a lone
pair that is not there. The reference space is available as the minimal tier, so
this scores as a tier match rather than a miss, which is the counts being
generous rather than the engine being right.

`geometry.lone_pair_axes` is where it happens, and its docstring names the
assumption without noticing it is one: "Three neighbours (amine): one lone pair,
opposite the sum of the bonds." That construction is correct for a *pyramidal*
amine, where $-\widehat{\sum_i \hat v_i}$ points at the real lone pair. For a
*planar* three-coordinate centre the three bond unit vectors are coplanar and
very nearly cancel, so the sum is a small residual whose direction is set by the
deviation from exact trigonal symmetry rather than by any chemistry. Pyridinium's
ring angles differ by a few degrees, the residual points roughly opposite the
N-H bond and into the ring, and the projector then finds real density along it
because an in-plane direction inside an aromatic ring overlaps the sigma
framework.

The chemistry says the same thing more simply: a planar three-coordinate
nitrogen's non-bonding density is in the p orbital perpendicular to the plane,
and that orbital is already emitted, as the pi target. The in-plane direction is
a second bite at the same electrons.

**It is not confined to cations, which is why the fix is not free.** Every
planar three-coordinate nitrogen in the benchmark has been getting this target:
pyrrole's, formamide's, and both of uracil's amide nitrogens. P4.3 already
measured those and recorded the symptom without identifying the cause -- "every
orbital labelled n/sigma is an aromatic heteroatom whose lone pair is conjugated
into pi (furan O 0.287, uracil amide N 0.330, pyrrole N 0.441), where a low
in-plane weight is the correct answer". A low in-plane weight is what a target
aimed at nothing in particular returns. So the mitigation P4.3 settled on,
reporting continuous weights beside the label, is right and stays right, but the
target should not have been emitted in the first place.

The condition to add is one line and the measurement is the entire cost, since
it moves the regression cases for four other steps. It is P2.5 rather than part
of P2.3, on the same precedent as the prune guard and `MINIMAL_ENTROPY_GAP`:
measured here, applied only against the whole benchmark.

**Selection does not degrade on large planar systems, which was the other thing
P2.3 was for.** Section 11.2 records the state audit as unreliable on large
planar spaces, so the expectation was that the count metric would soften as the
pi system grew. It does not: naphthalene, hexatriene, octatetraene and
anthracene all match their full pi space exactly, anthracene's fourteen orbitals
in 6.1 s. Whatever is wrong on large planar spaces is in the state audit and not
in the selection.

**The portable specification recorded the wrong question for every molecule
with no pi system, and the handoff it exists to make portable could not have
worked for any of them.** Found by writing P1.4's test against water instead of
against the pyrrole `cas_09` uses.

`recommend()` builds its pool from the pi and lone-pair targets normally, but
when that space comes out completely full it says so in a note and falls back
to the sigma framework, because a full space describes no correlation. Water is
that case: two valence targets project to CAS(4e,2o), which is full, so the
recommendation is built from the eight extended targets and is CAS(8e,6o).

Both runners passed `perceive(..., include_sigma=False).targets` to
`spec.build` unconditionally. So water's `active_space_spec.json` recorded two
targets, which rebuild to the CAS(4e,2o) the recommendation had just rejected
in a note, sitting beside a tier table recording the CAS(8e,6o) it actually
recommended. The specification's own docstring says it writes down "the
*question*, not the answer". For these molecules it wrote down a different
question from the one that was asked.

Nothing raised and nothing disagreed, because until P1.4 nothing read the file.
`cas_09` could not see it either, and the reason is worth keeping: pyrrole has
a pi system, so its two perceptions give the same pool and the bug is invisible
on it. The molecules it does bite are exactly the ones Phase 2 added --
ammonia, methylamine, hydrogen sulfide, methanethiol, dimethyl sulfide -- plus
water and methane.

`Recommendation` now carries a `targets` field holding what it was actually
projected onto, and both runners write that. The fix is small; the lesson is
that a round-trip test whose molecule is chosen for convenience tests the
convenient path, and section 5's basis-independence claim rested on one
molecule's worth of round trip.

**A space can be the right size and still be unable to hold the state it was
sized for, and uracil is that case.** This is the largest finding of the plan
and it was reached by taking one open question seriously rather than filing it.

Uracil's narrowed $(14e,10o)$ is the literature space by count, contains two
orbitals the classifier labels `n` with lone-pair weights of 0.99, and produces
**no n->pi\* root at all**: not at three roots, not at six, not at ten, and not
in a singlet-constrained CASCI in the seeded space, which removes orbital
optimisation from the picture entirely. In every one of those roots both `n`
orbitals sit at occupation 2.000, changing by less than 0.0005. The CI is not
putting a hole in them.

The cause is the span, not the count and not the labels. Taking the hole
natural transition orbital of the very state the narrowing was performed for,
and projecting it onto the ten selected columns, captures **0.376** of it. The
same measurement on the pi->pi\* state of the same molecule in the same space
gives 0.999. The rest of the n hole is spread over lone-pair columns the
narrowing left behind (13.7% and 6.4% on two that are in the recommended pool
but cut by the narrowing) and over columns the classifier calls `sigma` (11.2%
and 5.3%). That is not a bug in the classifier: a carbonyl lone pair is an sp
hybrid and genuinely has sigma character, which is the whole reason 8.2 reports
weights instead of a hard label.

Everything else follows from that one number. Configurations built on a 38%
hole land near 16 eV rather than near 5, so they sit far above the pi->pi\*
manifold and no root count reaches them; solving the A'' block explicitly puts
its lowest singlet at 15.85 eV. The orbital optimisation cannot repair it
either, because a rotation between two doubly occupied orbitals has no gradient
to follow, so the state average can never acquire the state that would drive
the rotation toward the right lone pairs. And `ROOT_MARGIN`, which exists
because uracil's n->pi\* "appears around root 3", was tuned against a state
this space does not contain.

**It is not uracil-shaped.** Formaldehyde, the cleanest possible control,
captures **0.520**, with 36.2% of its n->pi\* hole sitting on a single canonical
column the classifier labels `sigma`. Formaldehyde does still produce the state,
at root 1 with an n depletion of 0.96, because a four-orbital CI reaches
everything; it produces it at 11.28 eV against a true 4 eV. So the defect is
general to selecting canonical columns by a per-orbital lone-pair label, and its
visible consequence ranges from a badly placed state to no state at all
depending on how much room the CI has.

**What this does to the counts in section 10.** Nothing, directly, and that is
the uncomfortable part. Uracil still matches its literature space exactly on
electrons and orbitals, so it is still a match in 10.1 and 10.6. The counts
measure size and were never measuring whether the requested state is reachable,
and until now nothing did. `scripts/casbench/hole_capture.py` is that
measurement, and 10.9 carries the table.

**The cause is one constant, and it is the one P4.0 cleared.**
`geometry.LONE_PAIR_S_AMPLITUDE` sets the s fraction of the lone-pair target.
Sweeping it against capture instead of against the literature count gives a
monotonic curve with the shipped $1/\sqrt{3}$ at the worst usable end: uracil
goes from 0.363 to **0.796**, and its second n->pi\* from 0.381 to **0.841**, at
a pure-p target. It moves the state and not only the number. Solving uracil's
A'' block explicitly at both amplitudes puts the lowest n->pi\* singlet at
**15.675 eV** as shipped and at **8.272 eV** at pure p, against a lowest
pi->pi\* of 8.10 eV, and cc-pVDZ agrees at 15.854 and 8.150. That is 7.7 eV from one constant, and it is where uracil's
n->pi\* belongs at this level of theory.

The chemistry agrees, which is why this is not curve fitting. A carbonyl's n
orbital is predominantly an oxygen 2p in the molecular plane, perpendicular to
the C=O axis, and it is that p-like lone pair which does n->pi\*, not the s-rich
hybrid pointing away along the bond. The engine emits one sp2 hybrid per lone
pair and therefore aims at the wrong one of the two.

**P4.0 was not wrong, it was measuring the other lone pair.** It found the
pure-p end worse on the literature match, 9 of 17 against 11 of 17, and that
still holds: a full valence space wants the s-rich hybrid and an excited-state
space wants the p. One amplitude cannot serve both, so setting the constant to
zero trades one failure for another. The change that serves both is to emit two
distinct lone-pair targets per sp2 heteroatom, one p-like perpendicular to the
bond axis and one s-rich along it, rather than two copies of a single hybrid.

That was written as a handover and then done in the same session, once the
benchmark evidence existed to do it honestly. **The change that landed is
simpler than the one proposed here.** Two targets per heteroatom was already
measured and rejected by earlier work, in a comment in `geometry.perceive`: it
detects more and inflates the pool, because the pool grows with the number of
targets clearing the projector threshold, taking uracil's minimal tier to
(30e,18o). Changing the amplitude instead leaves the target count alone, so the
pool cannot inflate, and the two in-plane lone-pair targets span the same plane
either way. What the s content changes is how much deep 2s-bearing character the
projector's eigenvectors absorb.

`LONE_PAIR_S_AMPLITUDE` is 0.20, P4.4 records the measurement, and
`docs/casbench/hole-capture.md` carries the before and after. The one thing the
handover got right to insist on was the whole benchmark: uracil alone would have
chosen 0.35, which improves capture by 79% and recovers nothing.

**Planar symmetry is why this went unseen, and it is an amplifier rather than a
second defect.** A Davidson reaches only what its initial guess spans. Once the
n->pi\* configurations sit above that window, exact planar symmetry guarantees
that no iteration pulls them back, since the a'/a'' coupling is identically
zero, and asking for more roots returns more A' states forever. Where the space
is small enough for the guess to span it the state is found regardless:
formaldehyde is planar C2v, its n->pi\* is A2 against an A1 reference, and an
unsymmetrised solve in its 16-determinant (6e,4o) finds it at root 1 with a
depletion of 0.96. So a root list tests reliably on small spaces and quietly
fails on large ones, which is the wrong way round, and the state audit of 9.2
asks exactly this question of exactly these molecules.

**The target correction is sufficient by itself**, which settles the scope of
the handover. At the pure-p target the ordinary unsymmetrised solver finds the
state without help, at root 2 of six with a depletion of 0.86, where at the
shipped target it finds no n hole in five excited roots. The initial guess needs
no change.

**The floor was not where the documentation put it, and it is not a property
of CASSCF.** Section 11.4 presents the 0.29 eV scatter as a measurement floor
to live with, and the harness was hardened in response. That hardening worked:
at `conv_tol=1e-8`, `conv_tol_grad=1e-5` and 100 macro-iterations the benchmark
reproduces acrolein exactly, five times out of five, energies and root
characters alike.

The refinement tier never inherited it. `refine._solve` shipped `conv_tol=1e-6`
with no gradient tolerance at all, on a documented argument that a refinement
starts close and is compared at the 0.01 eV scale so a tighter convergence
"buys nothing and costs macro-iterations". Measured, it moves root 5 by
0.459 eV, which is 45 times that scale, and changes the character of two roots
between identical runs. The loop's state audit compares characters, so this is
not a reporting inaccuracy: it changes which branch the loop takes.

Two further things worth keeping. `mc.converged` was `True` in all five of
those runs, so convergence at 1e-6 is not evidence of reproducibility and
cannot be used as one. And tightness is not monotone: at `conv_tol=1e-10`
acrolein converged 0 times out of 5 and the full scatter returned, because a
criterion the optimiser cannot reach leaves it stopping at an arbitrary point
in a shallow region exactly as an over-loose one does. The next session must
not "just tighten further"; 1e-8 with a 1e-5 gradient is the setting because it
is reachable, not because it is tight.

**The mechanism is threading.** The same loose protocol pinned to one BLAS
thread reproduces exactly. So the run to run difference is reduction order in
the linear algebra, and a loose tolerance is what lets that perturbation
survive into the answer. Pinning threads fixes it too and is the wrong fix, at
a factor of three in wall time.

**The Rydberg path was dead in the shipped default, and worse than dead.**
`excited.basis_has_diffuse` decided whether Rydberg states could be described
by testing the smallest primitive exponent in the molecule against 0.05.
`def2-svpd` is the engine's own analysis basis whenever excited states are
requested, and its smallest exponent on carbon is 0.067, so the answer was
always no. Every production excited-state recommendation has been telling the
user Rydberg states were not looked for.

It is worse than a suppressed note, because `excited._label` only assigns the
Rydberg label when that flag is set. Measured on formaldehyde in def2-svpd, the
n->Rydberg 3s state comes out at 7.50 eV against a QUEST reference of 7.30 with
a second-moment ratio of 3.24, well over the 3.0 Rydberg cut. So the state was
being found and labelled valence at the same moment the user was told it could
not be looked for, and a state not labelled Rydberg escapes `excited.augment`'s
Rydberg exclusion and can be pulled into a valence active space. The method
document calls that a reliable way to make a CASSCF hard to converge for no
gain.

The exponent rule also fails the other way, and not rarely: aug-cc-pVDZ is
reported as carrying no diffuse functions on N2 (smallest 0.056) and on F2
(0.085), because those elements' augmenting shells are less diffuse in absolute
terms than carbon's ordinary valence ones. No single cut can work, and
`app/chemistry/jobs/molden.py` had already written that down: "no threshold
separates the bases cleanly ... any cut between them would be luck rather than
physics." That module measured the orbitals instead. The engine did not, so the
two modules contradicted each other and the one that was right was not the one
being used as the gate.

**The refinement drawer was never written, and the backlog said it only needed
checking.** The entry read that `JobDetailDrawer.tsx` "renders the refinement's
occupation table, orbital characters and rotation trail", that it type-checks,
and that all it lacked was the Playwright pass this project requires. None of
that was true of the code. The dedicated section draws the RECOMMENDATION's
fields, the refinement's outputs were not in its exclusion list either, so
`rotations`, `natural_occupations`, `state_characters` and `orbital_characters`
fell through to the generic key/value dump, where a rotation trail is a list of
objects and an occupation list is a bare row of numbers with nothing saying
which orbital each belongs to. Searching every branch for that rendering finds
nothing.

So P8.1 became building it rather than checking it, and the browser pass earned
its keep twice over on code that type-checked cleanly both times:

- The section was keyed on `refined_active_orbitals`, which is what
  `RefineResult.to_dict` calls it. The runner publishes the refined size under
  `recommended_active_*`, the same key the recommendation uses, so there is no
  `refined_` anything in a real summary and the whole section rendered nothing
  at all. It is now keyed on `quick_active_orbitals`, which only a refinement
  writes.
- The trail was drawn from `mo_out`, `mo_in` and `why`, the dataclass's field
  names. `Rotation.to_dict` publishes `orbital_removed`, `orbital_added` and
  `reason`, so every row drew an empty Orbital and an empty Why.

Both are exactly the failure this project's frontend rule exists for: a
silently empty section looks identical to a working one in a code read.

**A dissociation curve hits a cliff before it finishes dissociating.** Found by
adding a stretched N2 point. The engine returns a correct $(10e,8o)$ at every
separation out to 1.80 A and then, at 1.85 A, fails outright.

The cause is not in the projector but one layer earlier.
`geometry.perceive_bonds` calls a pair bonded within `BOND_TOLERANCE = 1.30`
times the sum of covalent radii, and for N-N that product is 1.85 A. Past it
the two atoms are not bonded, so no bond emits a sigma axis; and a two-atom
molecule has no atom with two neighbours, so no pi normal is emitted either.
The target list is empty and there is nothing to project onto.

Two things follow. The **error message was wrong**, and is fixed here: it
blamed the minimal basis for not carrying the shells the targets named, which
is a real failure but a different one, and it sent a reader looking in
completely the wrong place. Being handed no targets at all is a perception
result, and it now says so.

The **underlying limitation is real and is not fixed**. A bond-breaking scan is
one of the places an active space matters most, and the engine can describe the
interesting part of the curve but not the dissociation limit. The honest fix is
not to raise the tolerance, which would make every other molecule's perception
looser for the sake of this one, but to notice that separating atoms still have
atomic valence shells and to fall back to those when no bond survives. That is
a design change and it is recorded rather than rushed. The benchmark entry sits
at 1.60 A, on the near side of the cliff, so that what it measures is the space
rather than the cliff.

**The lone-pair reference's s-amplitude is element-dependent, and one value
serves nitrogen.** The first measurement off the new non-planar molecules.
Section 4.3 chose a single oriented sp hybrid with $c_s = 1/\sqrt{3}$ by
measuring three variants on uracil, whose lone pairs sit on a first-row
carbonyl oxygen. Sweeping that amplitude and recording the best lone-pair
weight found anywhere in the projected pool:

| | 0.000 | 0.350 | 0.577 | 0.700 | 0.850 |
|---|---|---|---|---|---|
| hydrogen sulfide | 0.686 | 0.543 | 0.782 | 0.896 | **0.990** |
| methanethiol | 0.487 | 0.455 | 0.702 | 0.832 | **0.960** |
| dimethyl sulfide | 0.604 | 0.401 | 0.618 | 0.762 | **0.923** |
| ammonia | 0.654 | 0.923 | **0.990** | 0.967 | 0.844 |
| methylamine | 0.613 | 0.864 | **0.927** | 0.905 | 0.790 |
| water | 0.695 | 0.589 | 0.819 | 0.922 | **0.995** |
| formaldehyde | 0.976 | 0.980 | 0.988 | 0.993 | **0.997** |

The current 0.577 is the optimum for nitrogen and for nothing else. Sulfur and
water both want about 0.85, and formaldehyde is insensitive across the whole
range, which is why uracil could not have revealed this. Note that it is not
simply a first-row against second-row split: water prefers the same amplitude
as the sulfides.

**And the experiment that decides it says: leave it alone.** Detection is not
the question, because the pool grows with the number of targets clearing the
projector threshold, so an amplitude that finds more lone-pair character may
also drag in the sigma framework. Running the same sweep against the literature
match over all seventeen molecules that have a reference space:

| c_s | 0.000 | 0.350 | 0.577 | 0.700 | 0.850 |
|---|---|---|---|---|---|
| exact match | 9/17 | **11/17** | **11/17** | **11/17** | **11/17** |
| any tier | 12/17 | 11/17 | 12/17 | 12/17 | 13/17 |

**Flat from 0.35 to 0.85.** Not one molecule's selected space differs anywhere
in that range; only the pure-p end is worse, losing N2 and O2, which is the
result 2B.1 recorded when the valence s was added in the first place. The
threefold differences in detected lone-pair weight do not reach the selection
at all, because the projector cut sits far below where they move things.

So this is a genuine plateau and the value in use is in the middle of it, which
is exactly what P4 was meant to establish and the first constant for which it
has been established. It is not delicate and it should not be tuned.

What the amplitude does still change is the **reported label**, because the
0.50 lone-pair-over-sigma threshold is applied to a weight whose scale turns
out to be element-dependent: sulfur's lone pair scores 0.78 where nitrogen's
scores 0.99, so a thiol comes back `n/sigma` where an amine comes back `n`. The
space is right either way. The honest fix is therefore not to move the
amplitude, which would risk the pool for no gain in selection, but to recognise
that a single label threshold is being applied across elements whose weights do
not share a scale. Section 8.2 already publishes the continuous weights beside
every label, which is the mitigation; whether the threshold itself should be
element-aware is a separate question and is now recorded rather than guessed
at.

**An open question, not a bug: uracil's refinement finds no n->pi\* state at
all.** All three repeats return a $(14e,10o)$ space containing two orbitals
labelled `n`, and five excited roots every one of which is `pi->pi*`. Section
10.6 and the previous tracker both say that with 5pi + 2n + 3pi\* the n->pi\*
states "appear immediately", and the tracker records that a space with only one
carbonyl lone pair produced no n->pi\* at all while two produced them at once.
Two lone pairs are present here and the state is still absent.

Three readings, and nothing so far distinguishes them. The state may sit above
root 6, which is all that `n_states=3` plus `ROOT_MARGIN=3` solves for. The
character labelling may be misassigning it. Or the claim may be conditional on
the basis in a way nobody wrote down, since this is the cc-pVDZ refinement
protocol.

It bears directly on two planned steps. P5.2 reorders the loop to add roots
first when a state is missing, which is exactly the move that would find a
late-lying n->pi\*, and P3.1 changes the basis this protocol runs in. Whichever
of the three readings is right should fall out of one of those rather than
being chased on its own.

**Augmentation reads a block that is not the active space, whenever a
narrowing has happened first.** Confirmed by following the call path rather
than by running it, because the branch fires rarely.

`augment(mo, ncore, ncas, ...)` takes the active orbitals as the contiguous
slice `mo[:, ncore:ncore + ncas]` (`excited.py`). Everywhere else in the loop
the active orbitals are named by `caslst` against `mo`, and the two agree only
while `caslst` happens to be `range(ncore, ncore + ncas)`. The missing-state
narrowing breaks exactly that: it sets

```
mo = np.asarray(recommendation.mo_coeff).copy()
caslst, nelec, ncas = new_cas, new_nelec, len(new_cas)
```

so `mo` goes back to the recommendation's original column order while `caslst`
becomes a SUBSET of the tier's indices, which is non-contiguous as soon as the
subset skips anything in the middle, and `ncore` is not reassigned at all. From
that point `mo[:, ncore:ncore + ncas]` is a contiguous window that is not the
active space. Augmentation then measures which requested NTOs are already
spanned against the wrong orbitals and appends residuals accordingly, and
`_drop_columns` discards virtuals chosen by overlap with those.

Nothing errors, and the result is a space assembled from the wrong premise. It
needs a test that forces a narrowing and then a missing state in the same run,
which is why it is its own step rather than a line in this one.

**The prune guard rejects a prune for losing a state that was never there.**
Found by reading uracil's own output rather than by reading the code.
`_prune_is_free` reports `n->pi* disappeared from the pruned space`, while the
same run's reported root characters are five `pi->pi*` and no `n->pi*` at all.
Those cannot both describe a loss, and the reported characters are not the
suspect: after a rejected prune `mc` is restored from `best`, so they describe
the correct pre-prune wavefunction.

The guard is what is wrong. It computes

```
lost = [p for p in predicted
        if not any(characters_compatible(c, p) for c in chars)]
```

purely from the pruned space, never consulting `chars_before`, which it already
receives and already uses for the energy-drift test two blocks further down. So
any predicted state that the space could not describe in the first place is
counted as lost by every prune, forever, and the loop stops one step early with
a message asserting a causal claim it has not checked.

The correct rule is that a prune costs a state only when that state was present
before and is absent after. A state absent both times is a different problem,
belonging to the state audit, and the prune is not what lost it.

Deliberately not fixed in the same commit as the tolerance change, because
uracil is the regression case for both and its refinement was still running
against the tolerance fix when this was found. Fixing the guard may well move
uracil off the (14e,10o) it currently lands on, since the spurious rejection is
what stops it pruning further, and that has to be measured rather than assumed:
a space that reaches the literature answer by way of a guard misfiring is not
evidence the guard is right. That measurement is P1.8.

The replacement asks the calculation rather than the basis: does this mean
field offer a virtual orbital with more than half its density outside 1.5 van
der Waals radii of every atom. That is the measure `molden.py` already reports
its orbital table against, so the table and the gate can no longer disagree
about what diffuse means, and it now lives in `app/chemistry/cas/diffuse.py`
where both can import it. Two consequences are honest rather than convenient:
N2 in def2-svpd reaches only 0.347 and F2 in aug-cc-pVDZ only 0.429, and for
those the answer really is that no Rydberg state can be described there. A
per-calculation statement is more useful than a claim about a basis that may
not hold for the atoms in it.
