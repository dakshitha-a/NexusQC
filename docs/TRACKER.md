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
- [todo] P1.4: run_cas_refinement reads the spec it was pointed at
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
- [todo] P2.3: Larger conjugated systems and charged species
- [todo] P2.4: Scoring that fits the new classes

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
- [todo] P4.1: The remaining perception and pool constants, swept on the quick tier
- [todo] P4.2: Refinement constants, swept on a named subset
- [todo] P4.3: The n/sigma pair, on the molecules it was never set against

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

- [todo] P6.1: Is the refined space the same in three basis sets
- [todo] P6.2: Root-count sensitivity, recorded with every reference

## Phase 7: Acrolein

- [done] P7.1: Is acrolein's missing orbital a defect or a gap in the reference
  evidence: docs/CAS_ENGINE_METHOD.md → "section 10.1: the reference's description names five orbitals, its recorded count is seven, and the engine returns six, so no two of the three agree; the engine matches the recorded ELECTRON count exactly and is one VIRTUAL short, and acrolein's four-orbital pi system has no third pi* to supply it, which is formamide's situation exactly"

## Phase 8: The refinement drawer

- [done] P8.1: Build the refinement drawer, then drive it in a real browser
  evidence: tests/frontend/cas_14_refinement_drawer.spec.mjs → "17/17 against the live stack; a real water refinement renders its refined space, a natural-orbital table carrying occupations, characters AND the continuous weights, and a rotation trail naming the orbital, its occupation and the reason, with both orbital-set conventions stated and nothing drawn twice"

## Phase 9: Re-run whole and close out

- [todo] P9.1: Every set re-run on the final code, into the ledger
- [todo] P9.2: Sections 10 and 11 restated, BACKLOG.md updated

---

## Found along the way

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
