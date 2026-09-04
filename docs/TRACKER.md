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
- [todo] P0.6: The harness refuses to score a non-converged row

## Phase 1: Wire what is written, and fix what the audit found

- [todo] P1.1: Narrowing moves into the quick recommendation
  design settled, not yet built: `_narrow_to_states` needs the TDA analysis,
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
- [todo] P1.3: Augmentation is wired into the quick tier or withdrawn from the docs
- [todo] P1.4: run_cas_refinement reads the spec it was pointed at
- [done] P1.5: Record the solved root count, and stop swallowing a spin-adaption failure
  evidence: scripts/casbench/repeat_scatter.py → "a pyrrole refinement now reports n_states_requested 3 alongside n_roots_solved 6, where the summary previously carried only the request; _spin_adapt returns whether the constraint was applied and a failure becomes a note on the result rather than silence"
- [todo] P1.8: A prune cannot lose a state the space never had
- [todo] P1.9: Augmentation reads the wrong orbitals after a narrowing
- [done] P1.6: The orbital-identity audit, asserted by projection not by position
  evidence: tests/backend/cas_12_orbital_identity.py → "6/6; pyscf's default HOMO-centred window spans the recommended space exactly (overlap 6.0000 of 6) because the projector puts the active block at the occupied/virtual boundary and its ncore agrees, a window shifted by one orbital scores 5.000 so the test can fail, and the restart and natural-orbital sets span the same space while not being the same orbitals one by one"
- [todo] P1.7: The two orbital classifiers are checked against each other

## Phase 2: The benchmark the edge cases need

- [todo] P2.1: Non-planar heteroatoms
- [todo] P2.2: Diradicals and bond breaking
- [todo] P2.3: Larger conjugated systems and charged species
- [todo] P2.4: Scoring that fits the new classes

## Phase 3: The benchmark runs the product's protocol

- [todo] P3.1: Recommend and analyse in def2-svpd, leave the CASSCF in cc-pvdz
- [done] P3.2: Ask the calculation, not the basis set's name, whether a Rydberg state can be described
  evidence: tests/backend/cas_06_excited_character.py → "19/19; def2-svpd is now recognised as able to describe a Rydberg state and one is actually found in it, where the exponent rule called the engine's own default analysis basis non-diffuse"
- [todo] P3.3: Rydberg states that are correctly absent from a valence space

## Phase 4: Threshold sensitivity

- [todo] P4.1: Perception and pool constants, swept on the quick tier
- [todo] P4.2: Refinement constants, swept on a named subset
- [todo] P4.3: The n/sigma pair, on the molecules it was never set against

## Phase 5: Cost reported, not enforced

- [todo] P5.1: The root-CSF estimate and its tier reach the user before the job runs
- [todo] P5.2: Adding roots becomes the first response to a missing state

## Phase 6: Two sensitivities never measured

- [todo] P6.1: Is the refined space the same in three basis sets
- [todo] P6.2: Root-count sensitivity, recorded with every reference

## Phase 7: Acrolein

- [todo] P7.1: Is the missing orbital a defect or a gap in the reference

## Phase 8: The refinement drawer

- [todo] P8.1: Drive the drawer in a real browser

## Phase 9: Re-run whole and close out

- [todo] P9.1: Every set re-run on the final code, into the ledger
- [todo] P9.2: Sections 10 and 11 restated, BACKLOG.md updated

---

## Found along the way

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
