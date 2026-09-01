# Tracker: several states and state pairs per job, and batching them over a path

**Complete as of 2026-09-01.** Eight phases, 19 steps, all done.
The `merged:` rows record the commits each phase landed as.

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
[`trackers/2026-09-tracker-merged-hash-reachability.md`](trackers/2026-09-tracker-merged-hash-reachability.md)
-- 1 step in one phase, closed 2026-09-01.

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

A user tagged a 1-D PES scan of ethylene and asked for the non-adiabatic
couplings between all state pairs at every geometry. What came back was a
ground-state single point on image 1 of 7, after four turns in which the agent
told them the coupling job type was misconfigured in this deployment, guessed
an active space from a HOMO/LUMO lookup, and finally offered to compute
something else instead.

Three defects, each independently sufficient to produce that.

**Every multireference derivative job was unsubmittable, on all three
engines.** `active_electrons` and `active_orbitals` were scoped to a tuple
that omitted `single_point/grad` and `single_point/nac`, on the strength of a
comment claiming those two "get their CAS-space params some other way". They
do not. All three runners read the keys unconditionally, so the draft dropped
them as inapplicable and the input builder then died on `KeyError`. Confirmed
by direct measurement before anything was changed: six of six
engine × job-type combinations failed, the one exception being ORCA's
CASSCF NAC, which is a documented engine gap and refused correctly. The right
tuple, `_CAS_TASKS`, already existed one line below and was already used by
the parameter directly beneath.

**A coupling job took exactly one state pair, and a gradient job exactly one
state.** BAGEL computes any number of either from a single `forces` block --
the shape the user supplied from their own working input -- and PySCF gets
them from one converged state-averaged wavefunction. The one-pair rule's
recorded rationale was about single-reference methods, where ORCA genuinely
offers nothing but the ground-to-excited coupling; it had been applied to
every method, so a state-averaged CASSCF could not ask for the S1/S2 coupling
it is perfectly capable of computing.

**Batching existed but was locked to four child types.** `batch` with
`source_job_id` already accepted `pes_1d`, `interp_pes`, `wigner_spectra`,
`geometry_set` and `neb_ts` -- the whole "any multi-geometry job" half of the
request was already built. Its children could only be ground-state energies,
optimizations, frequencies, or optimization-then-frequencies.

One trap governed the order of the work. Lifting the one-pair rule without
fixing the parser first would have returned confident wrong numbers rather
than an error: `_parse_gradient_block` took `sections[-1]`, the LAST gradient
block, while the energy gap and oscillator strength used `.search()`, the
FIRST match. Three pairs would have reported pair 3's vector beside pair 1's
gap, with nothing anywhere to say so. That is why the parser has a phase of
its own, ahead of the input builders.

## Phase 1: The blocker, and the message that hid it

- [done] P1.1: Scope the active-space parameters to grad and nac
  evidence: tests/backend/grad_01_gradients_and_nac.py → "Before: all six engine x job-type combinations failed -- bagel grad/nac and orca grad on KeyError 'active_electrons', pyscf grad/nac on KeyError 'active_orbitals', orca nac correctly refused as a documented engine gap. After: five build, orca casscf nac still correctly refused. Elicitation now walks active_electrons -> active_orbitals -> n_excited_states -> state_pairs and reaches ready"

- [done] P1.2: A missing required parameter says so, instead of naming a key
  evidence: tests/backend/grad_02_multi_target_parsing.py → "A KeyError's str() is bare, so the session saw 'Could not build the input for this job: active_electrons'. Now: 'it needs a active_electrons parameter and the draft has none. If that is not a parameter this job type accepts, the job type and the requested calculation do not match -- say so rather than guessing a value for it.' Deliberate errors still render as themselves. Applied at all five build sites"

- [done] P1.3: A named active space reads as something to check
  evidence: app/chemistry/registry2/elicitation.py → "The approval note was a statement of fact ('the active space is the 2 named orbitals [8, 9]'), which gave a reader no reason to look twice at a list the model had inferred from an orbital table. Now phrased as a check, naming the consequence: 'Check this if you did not name them yourself ... Different orbitals are a different calculation'"

- merged: da6c2d0

## Phase 2: Several states and several pairs

- [done] P2.1: N pairs and N states in the spec, validated per entry
  evidence: tests/backend/grad_02_multi_target_parsing.py → "20/20 cases. Accepts three pairs on a 3-root CASSCF, including S1/S2. Refuses a state above the state average, a reversed duplicate ([1,2] and [2,1]), a state coupled to itself, a non-pair, a float index, and an excited-to-excited pair on hf/dft. The multireference/single-reference ceiling is derived once in params.n_states_total: state 4 is refused on both families with the right total, where a naive check would have rejected the legal S1/S2 pair"

- [done] P2.2: target_states for gradients, kept apart from target_state
  evidence: tests/backend/grad_01_gradients_and_nac.py → "single_point/grad takes target_states (a list, 1-based INCLUDING the ground state); opt/freq/opt_freq/neb_ts keep the scalar target_state (0/absent means ground). Two conventions in one app, so the excited-state capability guard now asks _excited_state_requested rather than testing one key -- reading target_state alone would have silently stopped guarding the job type the guard was written for. target_states=[1] is a ground-state request and correctly does NOT trip it"

- [done] P2.3: nacmtype, and a multiplicity axis on the capability matrix
  evidence: scripts/check_capability_matrix.py → "nacmtype (full/interstate/etf, default full) existed nowhere in the repo and is now emitted in BAGEL's grads entries; scoped to BAGEL, since ORCA hardcodes ETF TRUE and PySCF exposes no equivalent. MethodCaps gains multi_state_gradient and nac_multi_pair -- the matrix had no dimension for 'how many at once' at all"

- merged: da6c2d0

## Phase 3: The parser, before anything plural is emitted

- [done] P3.1: Segment BAGEL's output per NACME pair
  evidence: tests/backend/grad_02_multi_target_parsing.py → "A synthetic 3-pair output with a different vector, gap and oscillator strength per section. Each is now read from its own section and keyed by the targets BAGEL itself announces, converted 0-based to 1-based, rather than by position in the request -- so a mismatch between what was asked and what ran is detectable at all. The test asserts the old behaviour would have paired section 3's vector with section 1's gap, so it cannot pass against the bug it exists for"

- [done] P3.2: The last-block helper is gone rather than left as a trap
  evidence: git grep _parse_gradient_block → "No callers anywhere after run_gradient and run_nac moved to _gradient_sections, which answered the blast-radius question this raised: nothing else parsed a gradient out of a multi-block output, so the CASPT2 oscillator-strength path was never silently returning the highest state's gradient. Deleted rather than kept, since a helper that quietly picks one of several is what the phase exists to remove"

- merged: da6c2d0

## Phase 4: Plural inputs, per engine

- [done] P4.1: BAGEL emits one forces block with an entry per target
  evidence: tests/backend/grad_01_gradients_and_nac.py → "Real CAS(2,2)/cc-pvdz ethylene, three pairs in one input. |NAC| 0.405655 / 0.258235 / 0.332823 with gaps -9.9373 / -15.0748 / -5.1375 eV. The gaps are internally consistent -- 9.9373 + 5.1375 = 15.0748 exactly -- which cannot hold if the sections were matched to the wrong pairs, so it is asserted rather than merely observed. Generated input matches the shape the user supplied byte for byte, including nstate 3 / nact 2 / nclosed 7"

- [done] P4.2: PySCF loops the kernel over one converged wavefunction
  evidence: tests/backend/grad_01_gradients_and_nac.py → "SA-CASSCF(2,2)/cc-pvdz gave three distinct couplings from a single solve. TDDFT/PBE0 gave ground plus two excited gradients (0.035333 / 0.073204 / 0.367147 Eh/Bohr) from one SCF and one TDDFT solve"

- [done] P4.3: ORCA runs one process per target, in its own subdirectory
  evidence: tests/backend/grad_01_gradients_and_nac.py → "ORCA takes one IROOT per run, so two pairs meant two processes in pair_1_2/ and pair_1_3/ with a combined raw output at the top level; a single pair still runs in the job directory itself, unchanged. Threading a subdirectory needed no refactor -- _write_and_run was already parameterized by directory, so the plan's documented fallback (refusing multi-pair on ORCA) was not needed. Ground and first-excited gradient norms agree with PySCF to four digits on the same functional and basis: 0.035289 / 0.073287 against 0.035333 / 0.073204"

- [done] P4.4: One result shape, built once
  evidence: app/chemistry/jobs/derivatives.py → "Three runners were assembling the same result dict separately, which is what let the parser bug live undetected -- nothing stated what a coupling result was supposed to look like. Now one module builds both shapes; every key is present from every engine, None where an engine does not report it, so .get returning None means 'this engine does not report it' and never 'this result came from the other engine'"

- merged: da6c2d0

## Phase 5: What a batch can run

- [done] P5.1: The missing child tasks, and constraints held at each geometry's own value
  evidence: tests/backend/batch_01_multi_geometry.py → "BATCH_CHILD_TASKS gains excited_states, gradient, nac, opt_constrained and opt_ci. All five build against a real scan job. The excluded-subtypes comment was answered rather than deleted: opt/ci generalizes (the same state pair means the same thing at every geometry) and opt/constrained does not, so a constraint may now omit its value. Checked against the user's own ethylene scan: the seven images come back at 0, -30, -60, -90, -120, -150 and 180 degrees, reproducing the scan's own coordinate values, so the measurement agrees with the generator that produced them. The input constraint dict is not mutated, and a stated value passes through untouched"

- [done] P5.2: A batch elicits and validates its child's parameters, not only its own
  evidence: tests/backend/batch_01_multi_geometry.py → "A batch of couplings now asks for state_pairs, one of excited states asks for n_excited_states, one of CI optimizations asks for both states, and all reach ready. This is why the original child set was exactly the four needing nothing beyond method and basis. _build_spec_or_error returns early for a batch, so _validate_task_params is also called explicitly against the child's task -- an unvalidated model-written parameter becomes N bad jobs in a batch rather than one. A constrained batch on BAGEL is correctly refused, since bagel/casscf has no working constrained optimization"

- merged: d6340b8

## Phase 6: Carrying orbitals along a path

- [done] P6.1: chain_orbitals, off by default and serial when on
  evidence: tests/backend/batch_01_multi_geometry.py → "Off by default and never asked, because turning it on caps the in-flight wave at one and trades the batch's whole concurrency for accuracy nobody requested; the card carries a warning saying so. Child i+1 takes child i's job id as initial_orbitals_job_id. The end-to-end run asserts children.jsonl holds exactly one child per geometry with no duplicates, which is the failure that would corrupt a chain rather than merely waste cores"

- merged: d6340b8

## Phase 7: What a finished batch shows

- [done] P7.1: Collect the children into a curve against the scan coordinate
  evidence: tests/backend/batch_01_multi_geometry.py → "11/11 end to end: the batch completes, one child per geometry with no duplicates, every child computes all three pairs in its own job, and the master aggregates into one series per state pair with a value at every geometry, the three genuinely different from one another, plotted against a recorded coordinate axis. Indexed by each child's own _batch_index rather than by position, since dispatch is trickled and quota eviction can reap an early child. Optimization children are deliberately not aggregated -- runs that converged to different minima are not one curve"

- [done] P7.2: The drawer renders every coupling and every gradient
  evidence: tests/frontend/grad_02_gradient_nac_drawer.spec.mjs → "24/24 in chromium against the live stack. A three-pair coupling job shows all three pairs with three DISTINCT norms (0.505944 / 0.289755 / 9.025484), and a two-state gradient job both states (0.140508 / 0.595391), each against its own label -- asserting only that 'a coupling rendered' would have passed against the bug this work exists for. Two defects surfaced here that a code read passed: the generic summary table repeated the structured fields as 'gradients [object Object]' beside a state index formatted '1.0000', and &Vert; -- a valid HTML entity this build's JSX transform does not decode -- rendered to users as the literal text '&Vert;NAC&Vert; = 0.123456'. The latter was pre-existing and had survived because the spec's own assertion carried an || fallback that passed on any six-decimal number anywhere in the drawer"

- merged: 60f5448

## Phase 8: Docs and capability tables

- [done] P8.1: Regenerate the capability documentation and record the new axis
  evidence: scripts/check_capability_matrix.py → "791 assertions across 19 rows and 20 tasks pass. The check refused every multiplicity claim until it carried evidence, which is the guardrail working: the cells now carry per-cell provenance, run where this session executed it and manual where the mechanism is shared with a row that was. The doc generator needed headings for the two new fields or it died on a KeyError"

- [done] P8.2: Architecture and README
  evidence: docs/ARCHITECTURE.md → "A section on why the request shape is uniform across engines while the mechanism is not, why both result shapes are built in one module, and the two state-numbering conventions that differ by one. The batch narrative answers the excluded-subtypes reasoning rather than dropping it. README and the in-app help say a job can cover several states or pairs and what a batch can now run"

- merged: d6340b8

