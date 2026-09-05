# Tracker

**In motion, opened 2026-09-05.** Fifteen phases.

Closing out the CAS recommendation engine. Every entry `docs/BACKLOG.md` carries
about this engine leaves during this plan, and none of them comes back. When it
finishes, `docs/CAS_ENGINE_METHOD.md` is rewritten from the final benchmark run
to describe the implementation as it then stands.

It follows [`trackers/2026-09-cas-engine-audit.md`](trackers/2026-09-cas-engine-audit.md),
which closed on 2026-09-04 at 43 steps across eleven phases, and that follows
[`trackers/2026-09-cas-engine-rebuild.md`](trackers/2026-09-cas-engine-rebuild.md).

## Rules (enforced by scripts/check_tracker.py)

Format for a step row:

    - [status] P<phase>.<step>: <short name>
      evidence: <script/command> -> "<observed result>"   (required when done)

Status is `todo`, `in-progress` or `done`. A `done` step carries an evidence
line whose first token is a path that exists. A phase records `merged:` only
when every step in it is done, and the hash has to be reachable from `HEAD`.
The tracker edit ships in the same commit as the step's final code change, so
`git log --follow docs/TRACKER.md` is the audit trail.

## The three doors

Every backlog entry leaves through exactly one, and the step that closes it says
which:

1. **Fixed.** A code change, validated across the benchmark, with a named
   regression molecule.
2. **Decided.** A product or design question settled deliberately and recorded
   in the method document.
3. **Measured and stated.** A real limitation, quantified, written into the
   method document with the measurement behind it.

A limitation reported with its number attached is not an open item. That is what
makes emptying the backlog honest rather than cosmetic.

## A change to perception is a change to everything downstream of it

Inherited from the audit, and it applies to the measurements and not only to the
results. A change under `app/chemistry/cas/geometry.py` or `projector.py` is
validated against every `cas_*` test plus `--set spaces`, `--set narrowed`,
`--set refine` and `--set nevpt2`. The last two are hours. That is the cost of
changing perception, not a reason to skip them.

The corollary governs this plan's shape: every engine change lands before the
final sweep, the sweep runs once at the final commit, and no number reaches the
method document from a mid-flight run.

## Why this plan exists

Three things made a third round necessary rather than optional.

**No committed ledger measures the shipped engine.** `spaces.md` is stamped
`86b8dc3`, `narrowed.md` `ad4a86e`, `refine.md` and `nevpt2.md` `77b692d`,
against a `HEAD` of `2049bc5`; `stability` and `excited` have never had one
committed at all. So every quantitative claim in the method document is
provisional.

**Four defects surfaced during planning that no backlog entry names**, one of
them a latent crash on a corrective path that has therefore never run.

**Two backlog entries are wrong about their own subject.** o-Nitrophenol does
finish inside the benchmark cap; the molecules that do not are anthracene and
p-benzoquinone. Acrolein's missing orbital was explained by the audit's P7.1 and
the entry was written as though it were not.

### Decisions taken with the user before starting

Transition metals go to the depth of fixing the covalent radii and measuring the
recommendation path, with the document stating exactly which stages are
exercised. Rydberg states are explored as a capability to ship rather than
settled by refusal, with methylamine at SA(2)/aug-cc-pVDZ CAS(8e,9o) as the
worked case and a pivot to refusal only if the valence path breaks. Bistability
is censused across the benchmark and then reported, so that every excitation
energy carries the reference energy it was taken from.

## Phase 0: A baseline that can be trusted

- [done] P0.1: Ledger records a dirty working tree
  evidence: scripts/casbench/ledger.py -> "stamp reads 2049bc5+dirty with the source edited and 2049bc5 clean; the first attempt reported clean either way, because a pathspec resolves against the cwd it is run in and that is this file's own directory"
- [done] P0.3: Ledger records the thread counts in force
  evidence: scripts/casbench/ledger.py -> "header now reads `in 1s, with omp=8, mkl=12`; this host sets the two to different values in its shell profile, which nothing recorded before"
- [done] P0.2: A baseline at a known commit, for the sets a baseline helps
  evidence: docs/casbench/spaces.md -> "spaces 31s, stability 406s and excited 1787s all stamped d524f08 with omp=8, mkl=12; stability and excited had never had a committed ledger at all"
- [done] P0.4: Decide which sets a baseline is worth waiting for
  evidence: docs/TRACKER.md -> "nevpt2 abandoned mid-run because P10 changes its protocol, so a before under the old one compares against nothing; refine and narrowed are measured immediately either side of the change that could move them instead"
- merged: -

## Phase 1: The latent defects in the refinement's narrowing

- [done] P1.1: The in-loop narrowing raises TypeError and has never run
  evidence: tests/backend/cas_17_refine_narrowing_call.py -> "forced with an n->pi* state on ethylene, which has no lone pair; TypeError before the fix, 2/2 after, and the branch executes for the first time"
- [done] P1.2: The budget fallback narrows a ground-state request
  evidence: app/chemistry/cas/refine.py -> "dimethyl sulfide now declines with its CAS(20e,18o) and 367,479,684 CSFs named, instead of collapsing to (4e,3o) and failing to converge"
  design as built: the plan said report the cost and refine anyway, on the engine's rule that cost is reported and never enforced. That rule belongs to the recommendation, which names a space and leaves running it to the user. This loop has to solve the CI several times and 367 million CSFs does not finish, so there is no slow-but-possible reading and declining is the honest answer.
- [done] P1.3: Correct the drift detection that describes behaviour it no longer has
  evidence: app/chemistry/jobs/pyscf_runner.py -> "comment and user-facing message rewritten; cas_15_spec_handoff 19/19"
  design as built: the plan said remove it. Its explanation is stale, since the refinement defers to the published narrowed tier rather than re-deriving one, but the comparison itself still fires when the CSF budget sends the start-tier search down the ladder or an explicit refine_start_tier overrides it. Deleting a live check because its comment had rotted would have been the wrong repair.
- merged: -

## Phase 2: Narrowing that is reproducible and never degenerate

- [done] P2.1: A deterministic pool classification
  evidence: app/chemistry/cas/narrow.py -> "an orbital with neither character is classified before the two weights are compared; water's second pool orbital carries wpi 1e-26 against wlp 1e-28 and the comparison decided its membership. cas_16 5/5 identical, cas_13 9/9"
- [done] P2.2: A narrowed tier that is a full space is not published
  evidence: app/chemistry/cas/narrow.py -> "the completion guard recommend() applies to its minimal tier now applies here; water at 3 states declines to narrow and the pool stands, where it used to publish CAS(4e,2o), which is one configuration"
- [done] P2.3: Narrowing stability becomes a standing test
  evidence: tests/backend/cas_16_narrowing_stability.py -> "failed 4 of 4 when written, passes 3 of 3 now; water returns its pool identically across five runs"
- merged: -

## Phase 3: Twisted ethylene, diagnosed before it is fixed

- [done] P3.1: Separate the three candidate mechanisms
  evidence: scripts/casbench/recommend_repro.py --repeats 60 -> "9 of 60 runs return (4e,3o) against 51 of (2e,2o); the first stage to vary is proj_space, not the ranking; the SCF energy spread is 3.148e-02 Ha, which is 857 meV and not noise"
- [done] P3.5: Establish what stabilising the reference would cost elsewhere
  evidence: scripts/casbench/scf_stability.py --repeats 20 -> "twisted ethylene collapses from 17-and-3 across two solutions to 20 of 20 on one; square cyclobutadiene, stretched N2 and O2 move to lower solutions; no molecule changes its recommended space except twisted ethylene, which changes to its reference (2e,2o). Anthracene costs 3.3s to 48.2s"
- [done] P3.2: A reference that is stable, not merely converged
  evidence: app/chemistry/cas/reference.py -> "helper exercised on twisted ethylene, O2 and water; O2 follows one internal instability 0.2 mHa lower and reports external stability as unavailable rather than raising, since pyscf has no rohf_external"
- [done] P3.4: Wire the stabilised reference into all three callers
  evidence: app/chemistry/jobs/pyscf_runner.py -> "both SCF sites stabilised and their notes surfaced in the job result; water end to end reports stable internally and externally and returns CAS(8e,6o) unchanged"
- [done] P3.3: Every molecule bit-identical across four runs
  evidence: scripts/casbench/spaces_reproducible.py --repeats 4 -> "32 of 32 reproducible in 485s, compared on selected orbital indices rather than size; twisted ethylene returns (2e,2o) on all four where it used to return two different spaces"
- merged: -

## Phase 4: Rydberg states, explored as a capability

- [done] P4.1: Separate what the method cannot do from what the basis cannot
  evidence: docs/casbench/rydberg.md -> "def2-SVPD fails on four of seven molecules in two different ways, and aug-cc-pVDZ resolves all seven; the analysis basis is now aug-cc-pVDZ, at 0.99x to 1.97x the cost"
- [done] P4.2: Assemble the Rydberg reference cases
  evidence: scripts/casbench/rydberg_probe.py -> "seven molecules with a known low-lying Rydberg state measured in both bases; formaldehyde's n->Rydberg 3s was already in EXCITATIONS and needed no new reference data"
- [done] P4.3: Serve a Rydberg state, and measure what that produces
  evidence: scripts/casbench/rydberg_serve.py -> "both branches converge; the added orbital's diffuse fraction falls from 0.648 to 0.471 across the CASSCF, formaldehyde's state lands 1.4 eV below its reference, and ammonia's roots move away from it and differ between identical runs"
- [done] P4.4: The decision gate, and the branch it selects
  evidence: docs/casbench/rydberg.md -> "refuse, on the measurement rather than on the prior argument: the orbital does not survive the optimisation it is handed to, so the space stops describing a Rydberg state during the step meant to improve it"
- [done] P4.5: The states-not-looked-for report reaches a user
  evidence: app/chemistry/jobs/pyscf_runner.py -> "the refinement path no longer strips Rydberg states before refine() sees them, so rydberg_excluded stops being permanently empty and a refinement can no longer report all states present when the one that mattered was dropped on the way in"
- merged: -

## Phase 5: Transition metals, to the depth chosen

- [done] P5.1: Covalent radii for the rows that had none
  evidence: app/chemistry/cas/geometry.py -> "all 29 transition metals now carry a Cordero radius; twenty of them fell back to 1.20 A before, including every 4d metal outside the platinum group and the whole 5d row"
- [done] P5.2: Metal complexes in the benchmark
  evidence: scripts/casbench/reference_data.py -> "Cr2, TiO and octahedral [Fe(H2O)6]2+ added as a 'metal' class of their own, so they cannot silently move the organic headline; 39 geometries, 32 reference spaces. TiO carries no reference space on purpose, since published choices range from the d shell alone to the d shell plus the whole O 2p manifold"
- [done] P5.3: The recommendation path measured, and its boundary stated
  evidence: scripts/casbench/metal_probe.py -> "Cr2, TiO and [Fe(H2O)6]2+ pass through perception, projection and ranking at 0.2s to 5.0s; the two differences from convention are that a metal contributes its d shell and nothing else, and that a ligand keeps its own orbitals"
- merged: -

## Phase 6A: The constants the sweep could not reach

- [done] P6A.1: A swept constant is read where it can be swept
  evidence: app/chemistry/cas/recommend.py -> "projector.THRESHOLD and geometry.BOND_TOLERANCE resolved in the function body instead of bound as default arguments; recommend()'s own hard-coded 0.2 removed, which was overriding the module constant a second time"
- [done] P6A.2: A test that a sweep can move what it sweeps
  evidence: tests/backend/cas_18_constants_reach_the_engine.py -> "3/3; twisted ethylene now answers (4e,3o) at 0.05 and 0.15 against (2e,2o) at 0.20 and 0.40, deterministically on a stabilised reference, where every value used to return the same space"
- merged: -

## Phase 6: MINIMAL_ENTROPY_GAP, given the validation pass it was denied

- [done] P6.1: Sweep over the final molecule set
  evidence: docs/casbench/constants.md -> "all four constants measured over 32 molecules; the threshold is monotone to 25/32 at the shipped 0.20 and the entropy gap is non-monotone at 25, 24, 25, 25, 24"
- [done] P6.2: The effect on the refinement start tier and the cost report
  evidence: docs/casbench/constants.md -> "not measured through --set refine, because the sweep removed the reason to: 0.10 loses an exact match rather than gaining two, so the change the backlog proposed is not on the table and there is nothing to validate downstream"
- [done] P6.3: Apply it or do not, and record why
  evidence: docs/casbench/constants.md -> "0.15 stays. The backlog's premise was measured on 21 molecules and does not survive the current 32: the gain is one tier offer rather than two, and 0.10 pays for it with an exact match"
- merged: -

## Phase 7: The audits that claim more than they measured

- [done] P7.1: A verdict says when it rests on a guess smaller than the space
  evidence: app/chemistry/cas/verify.py -> "a missing-state verdict now reports the space's CSF count against the 400 determinants pyscf builds its initial guess from, and says 'not found' rather than 'not there' above it; the old text asserted the orbitals were probably outside the space, which the guess window cannot distinguish"
- [done] P7.2: The two state audits agree about the same state
  evidence: app/chemistry/cas/verify.py -> "the CASCI audit now uses characters_compatible, the same comparison refine() uses, instead of exact string equality; mixed->pi* matches pi->pi* in both, where before one audit found the state and the other reported it missing"
- merged: -

## Phase 8: Bistability, a census and then honest reporting

- [done] P8.1: How many molecules have more than one converged solution
  evidence: docs/casbench/bistability.md -> "two of seven, and the one nothing had flagged is the worse: butadiene splits 872.8 meV where acrolein splits 36.4, both converging on all eight runs and both disagreeing about root characters"
- [done] P8.2: Every excitation energy carries the reference energy it came from
  evidence: app/chemistry/cas/refine.py -> "ground_state_energy_ha added to the result, and a multi-root refinement now says in words that a converged flag does not identify which solution was reached; cas_17 2/2 shows the note"
- merged: -

## Phase 9: Cost, caps, and the two molecules that do not finish

- [done] P9.1: Correct the record about which molecules exceed the cap
  evidence: docs/casbench/refine.md -> "o-nitrophenol refines in 454.6s, converged, inside the cap the backlog says it exceeds; the two that do not finish are anthracene, which dies with MemoryError in hdiag_csf, and p-benzoquinone at the 600s cap. The cap is scripts/casbench/run_bench.py's, not the product's, which has no wall-clock bound at all"
- [done] P9.2: Anthracene and p-benzoquinone, uncapped
  evidence: scripts/casbench/refine_uncapped.py --molecules anthracene -> "anthracene no longer reaches a MemoryError at all: it declines in 97s naming its 2,760,615 CSFs, because the budget fallback that used to substitute a narrowed space now only does so when there are states to narrow against. The benchmark cap is raised to an hour so p-benzoquinone's real cost is recorded rather than truncated"
- [done] P9.3: A space that cannot be built is reported, not enforced
  evidence: app/chemistry/cas/refine.py -> "no pre-flight memory estimate is added, because the CSF budget already prevents the case it would have guarded: anthracene's crash was the budget being bypassed by the silent narrowing, not the budget being absent"
- [done] P9.4: Acrolein's "unexplained" missing orbital, explained
  evidence: scripts/casbench/reference_data.py -> "the Thiel entry names four pi orbitals plus the oxygen lone pair, which is five, against a recorded count of seven; the engine returns (8e,6o), matching the electron count exactly and sitting one virtual short of the count. The same disagreement is already recorded for formamide in this file"
- merged: -

## Phase 10: Measure NEVPT2 in the space a user actually receives

- [done] P10.1: The set requests the states it reports on
  evidence: scripts/casbench/run_bench.py -> "recommend_with_states mirrors the runner's analyse-and-narrow path, so set_nevpt2 now measures the space a user asking for those states receives rather than a ground-state pool"
- merged: -

## Phase 11: ROOT_MARGIN, formally withdrawn

- [done] P11.1: Recorded as settled, removed from the backlog
  evidence: docs/TRACKER.md -> "withdrawn on the measurement rather than deferred again; the state the reordering would have chased is now in the space and adding roots was measured never to recover one fewer roots missed, so there is nothing left to tune against. ROOT_MARGIN itself stays, because it buys convergence"
- merged: -

## Phase 12: The final sweep

- [todo] P12.1: All six sets at the final commit, refinement uncapped
- merged: -

## Phase 13: Rewrite the method document

- [todo] P13.1: Rewritten from the final ledgers
- [done] P13.2: Settle the hand-written measurement write-ups
  evidence: docs/casbench/acrolein-bistability.md -> "all six write-ups stay as dated measurement records rather than folding into the paper, because each is the evidence a tracker step cites and a reader should reach it without rerunning hours of CASSCF; the two carrying a superseded banner keep it, and acrolein-bistability now points forward to the census that generalises it"
- merged: -

## Phase 14: Every surface, then the backlog

- [todo] P14.1: Every surface that describes the engine
- [todo] P14.2: The backlog carries no CAS entry
- merged: -

## Found along the way

### Twisted ethylene is an unstable SCF, not an unstable ranking

`docs/BACKLOG.md` attributes it to "the APC ranking taken from the RHF Fock and
exchange matrices" inheriting a near-degeneracy. That is the wrong stage. The
ranking never gets a chance to matter, because the *pool* already differs:
P3.1 finds `proj_space` is the first quantity to vary, and the two answers
differ in their electron count, which the ranking cannot change.

The real cause is one level further down. Plain RHF on this molecule converges
to two different solutions, -77.801586 Ha on 17 of 20 runs and -77.770110 Ha on
3, 31.5 mHa apart, and reports `converged` on every one of them. The projector
eigenvalues follow, moving by 3.4e-02 across runs, and one of them sits within
about 0.02 of the 0.2 admission threshold; measured at 0.177762 in one run set
and 0.212131 in another. Which side of the cut it lands on decides whether an
occupied orbital joins the pool, and admitting one occupied orbital turns
(2e,2o) into exactly (4e,3o).

Following the internal instability to a well-defined RHF solution collapses this
to one answer, -77.801586 Ha on 20 of 20.

**Correction, and it is the reason this paragraph is worth reading twice.** An
earlier run of this measurement reported that every run also found an external
RHF-to-UHF instability. It did not measure that. `stability(return_status=True)`
returns a four-tuple whose external entries are `None` unless `external=True` is
passed, and `not None` is true, so a test written as `if not stable_e` counted
twenty instabilities out of twenty from a quantity that had never been computed.
A second script reading the same tuple as `if stable_e is False` counted zero,
and neither number was a measurement.

Asked properly, with `external=True`, the answer is that twisted ethylene,
square cyclobutadiene, ozone and stretched N2 are all internally stable and
externally **unstable**, which is the diradical fact the backlog entry was
reaching for and is chemically what one expects. It is worth reporting to a user
rather than acting on, because acting on it means a broken-symmetry reference
and `projector.project` takes the alpha set alone for UHF, so that is a design
change and not a bug fix.

One guard is required rather than optional: pyscf's `rohf_external` raises
`NotImplementedError`, so asking an open-shell reference for its external
stability takes the path down. O2 is the case in this benchmark.

This is acrolein's bistability one level down, at the SCF rather than the state
average, which is worth saying in the method document because it makes a single
story out of two entries that read as unrelated.

### Two of the four swept constants never reached the engine

`scripts/casbench/constant_sweep.py` mutates a module attribute and then calls
`recommend()`. That works for a constant read inside a function body and does
nothing at all for one bound as a default argument, and two of the four are
bound as defaults:

| constant | how it is read | swept? |
|---|---|---|
| `projector.THRESHOLD` | `project(..., threshold=THRESHOLD)`, and `recommend` passes its own literal `0.2` over the top | **inert, twice over** |
| `geometry.BOND_TOLERANCE` | `perceive_bonds(..., tolerance=BOND_TOLERANCE)` | **inert** |
| `geometry.PLANARITY_COS` | read in the body of `local_pi_normal` | live |
| `recommend.MINIMAL_ENTROPY_GAP` | read in the body of `recommend` | live |

The two reported flat in `docs/casbench/constants.md` are exactly the two that
were never applied, and the two that were applied gave one flat result and one
that moved. So the flatness was the sweep measuring nothing, and
`CAS_ENGINE_METHOD.md` section 3.8's claims that "the projection threshold is
flat from 0.05 to 0.40" and "the bond tolerance from 1.15 to 1.50" are not
supported by the measurement cited for them.

The threshold claim is also false as stated. Passing `threshold=` explicitly,
twisted ethylene returns (4e,3o) at 0.05, 0.10 and 0.15 and (2e,2o) from 0.1778
up, so the constant does move an answer.

This is the same shape as the assertion the audit found in `cas_02`, which had
the engine's own output written down as its reference and therefore agreed with
whatever the engine did. A sweep that cannot move the thing it sweeps reports a
flat row, and a flat row is read as a real result.

### The product's own analysis basis is blind to the amine Rydberg states

`rydberg_representable` measures the mean field rather than the basis set's
name, which the audit established is the right way round. Measured across the
Rydberg cases, it returns True for methylamine and ammonia in aug-cc-pVDZ and
**False for both in def2-SVPD**, which is the basis the product moves to when
states are requested. Water returns True in both, so this is a property of the
molecule and the basis together and not of def2-SVPD alone.

The consequence is worse than a missing label. With the gate closed, those
states come back as `n->mixed` rather than `n->Rydberg`, and
`pyscf_runner.py:2609` filters any character containing "mixed" out of
`predicted`. So the state is neither served nor reported as deliberately not
looked for. It is silently dropped, and the run says nothing about it.

That splits the Rydberg question in two, and they have different answers:

  * **The analysis basis.** methylamine's S1 is found at 5.55 eV in aug-cc-pVDZ
    and is invisible as a Rydberg state in def2-SVPD. Nothing about serving
    Rydberg states fixes that, and nothing about refusing them does either.
  * **Serving the state.** Only worth deciding once the analysis is done in a
    basis that can see it.

### def2-SVPD cannot resolve Rydberg character, and the states are dropped silently

Measured over seven molecules in both bases. aug-cc-pVDZ resolves a Rydberg
particle in every case where one is expected. def2-SVPD, which is what the
product moves to when states are requested, fails in two different ways:

| molecule | aug-cc-pVDZ | def2-SVPD |
|---|---|---|
| methylamine | S1 `n->Rydberg` 5.55 eV | gate closed, `n->mixed` |
| ammonia | S1 `n->Rydberg` 6.20 eV | gate closed, `n->mixed` |
| pyrrole | S1, S2 `pi->Rydberg` | gate open, both `pi->mixed` |
| furan | S1 `pi->Rydberg` | gate open, `pi->mixed` |
| ethylene | S1, S2 `pi->Rydberg` | S2 becomes `mixed->pi*` |
| formaldehyde | S2 `n->Rydberg` 6.85 eV | S2 `n->Rydberg` 7.49 eV |
| water | S1, S2 `pi->Rydberg` | S1, S2 `pi->Rydberg` |

So the gate closing is not the only failure. Pyrrole and furan pass the gate and
still come back `mixed`, which means an adequate-looking basis can still fail to
tell a diffuse particle from a valence one.

What makes this user-facing rather than cosmetic is the next line of the
pipeline. `pyscf_runner.py:2609` builds `predicted` by dropping any character
containing "mixed", so on the shipped path those states are not served, not
refused, and not reported. They are silently absent. Pyrrole and furan are
benchmark molecules whose Rydberg references sit below their valence pi->pi*,
so this is reachable today without asking for anything unusual.

### What a transition metal actually gets, measured

`scripts/casbench/metal_probe.py`, def2-SVP, recommendation path only.

| system | perceived targets | recommended | conventional |
|---|---|---|---|
| Cr2 | `metal_d` x2 and nothing else | (10e,10o) | (12e,12o) |
| TiO | `metal_d`, 2 `pi`, 3 `lone_pair` | (8e,9o) | d shell against the O 2p manifold |
| [Fe(H2O)6]2+, high spin | `metal_d`, 6 `pi` | (14e,11o) | (6e,5o), the d shell alone |

Nothing fails, and the cost is ordinary: 0.2 s for the diatomics and 5.0 s for
the hexaaqua ion. The maximal tier of the last is reported at
335,247,780,644,570,136,576 CSFs with a note that only a DMRG treatment could
reach it, which is the cost machinery behaving correctly on a space far outside
what it was tuned on.

Two boundaries are visible in that table and both are properties of the target
set rather than bugs.

**A metal contributes its valence d shell and nothing else.** `perceive` emits
`metal_d` and then `continue`s, so a metal atom never emits a sigma axis or a
lone pair. On Cr2, where both atoms are metals, the whole target set is two d
shells: the 4s orbitals that the conventional (12e,12o) includes have no target
to be selected by, and the engine returns the 3d manifold alone. That is a
defensible space and a different one from the convention, and the difference is
exactly one s orbital per metal.

**A ligand keeps its own orbitals.** The hexaaqua ion returns the d shell plus
six ligand orbitals rather than the ligand-field d-only space, because the
water oxygens are perceived and projected like any other heteroatom. A chemist
asking for the classical (6e,5o) would have to narrow to it.

Extending the metal target to d-plus-s was considered and not done. It is a
perception change, and the scope agreed for this round is the radii and the
measurement, with the boundary written down rather than pushed outward.

### ROOT_MARGIN, and why the reordering is closed rather than deferred again

The backlog carried this as an experiment still worth running, blocked on
finding a molecule to run it on. It is closed here without code, because both
halves of its motivation are gone.

The idea was to make adding roots the first response to a missing state. It was
set aside during the audit because uracil, the molecule `ROOT_MARGIN` was tuned
for, did not contain its own n->pi* state at any root count, so the reordering
would have been tuned against something that was not there. The lone-pair
correction has since put that state in the space, which removes the blocker,
and the audit's own P6.2 then measured six molecules at three root counts and
found that adding roots never recovers a state that fewer roots missed. So the
blocker lifted and the benefit vanished at the same time.

What survives is the margin itself, which is not the same proposal and is well
supported: formamide takes 103.6 s and does not converge at margin 0 against
3.2 s converged at margin 3, and uracil goes from 1843 s unconverged to 544 s
converged. The margin buys convergence rather than costing time, and nothing
here licenses removing it.

Reopening this needs a molecule where extra roots demonstrably find something.
None is known, and the method document says so in its limitations rather than
the backlog carrying it as work.

### The Rydberg decision, and the labelling defect underneath it

Recorded in full in `docs/casbench/rydberg.md`. The short form is that serving a
Rydberg state was tried properly and does not work, for a reason that is a
property of the physics rather than of this implementation: the diffuse orbital
`augment` adds is contracted by the orbital optimisation it is then handed to.
Formaldehyde's goes in at a diffuse fraction of 0.648 and comes out at 0.471,
below the mark that makes an orbital diffuse at all, and its state lands 1.4 eV
below the reference.

Finding that took fixing a labelling defect first, and the defect is the more
transferable result. Diffuseness was tested as a ratio of an orbital's extent
against the largest extent among the core and active orbitals. Once the diffuse
orbital is IN the active space, that denominator contains the orbital being
tested, the ratio collapses toward one, and no root can ever be called Rydberg.
Every served root came back "mixed", which reads as "this did not work" and is
in fact "this cannot be seen". Diffuseness is now measured absolutely.

The same defect had a second life: `verify.py` carried a near-copy of the root
labelling that would not have received the fix, which is precisely how two
audits of one space come to disagree. It now delegates to the one
implementation.

### The projection threshold is not flat, and the shipped value is the right one

The first honest measurement of `projector.THRESHOLD`, now that setting it
reaches the engine. Ground-state request, def2-SVP, all 32 molecules with a
reference space:

| value | exact match |
|---|---|
| 0.05 | 21/32 |
| 0.10 | 23/32 |
| 0.15 | 24/32 |
| **0.20 (shipped)** | **25/32** |
| 0.30 | 25/32 |
| 0.40 | 25/32 |

Monotone up to the shipped value and flat above it, so 0.20 sits at the start of
a plateau rather than in the middle of a flat line. `CAS_ENGINE_METHOD.md`
section 3.8 says this constant "is flat from 0.05 to 0.40, a factor of eight",
which was the sweep failing to arrive rather than the answer failing to move.
Four of the six rows in that range are now known to be worse.

The practical consequence is small and the methodological one is not. The value
does not change, but it goes from being reported as arbitrary-within-a-plateau
to being the lowest value that reaches the best score, and the document has to
say the second thing because the first is false.

### Acrolein is one orbital short of a reference that disagrees with itself

The backlog carried this as unexplained, and noted that every other finished
molecule with a literature space either matches or has a recorded reason.

The reason exists and is the same one already written down for formamide two
entries above it in `reference_data.py`. Acrolein's Thiel entry describes "the
four pi orbitals plus the oxygen lone pair and the carbonyl pi system", which
names five orbitals, against a recorded count of seven. No two of the three
available numbers agree: the description says five, the record says seven, the
engine returns six. What the engine does match is the electron count, exactly,
and it is one **virtual** short, which acrolein's four-orbital pi system has no
third pi* to supply.

This is closed as a property of the reference rather than of the engine.
Nothing here says the engine is right and the reference wrong; it says the
comparison cannot be made cleanly, which is a different and more useful thing
to know. It is recorded the way the benchmark records every other reference
disagreement, in the entry itself, rather than carried as work.

### Acrolein is not alone, and the root count is part of the protocol

The census found butadiene splitting by 872.8 meV, which is twenty times
acrolein's gap and which nothing had flagged. Two of seven molecules, both
converging on every run, both disagreeing about root characters between their
solutions. So the two-solution problem is a property of the method rather than a
curiosity of one molecule, and the method document says so in its own section
rather than as a footnote to acrolein.

The measurement also produced a methodological trap worth keeping. A first pass
used a flat four roots and reported every molecule it reached as
single-solution, acrolein included. Acrolein's two solutions appear at six
roots, which is its two reference states plus the refinement's root margin, and
the refinement is the thing a user runs. A reproducibility measurement taken at
a root count nobody uses can report a stability the shipped protocol does not
have.

### Six carbonyl molecules are not rotation invariant, and never were

`--set stability` reports 6 of 32 molecules returning more than one space across
five random rotations: acetone, acrolein, formaldehyde, formamide,
p-benzoquinone and uracil. The legacy AVAS pilot returns 0 of 32.

**This is pre-existing, and the Phase 0 baseline is what proves it.** The
ledger taken at `d524f08`, before any change in this plan, lists exactly the
same six molecules at exactly the same counts, with uracil the only movement
since, from 2 to 3. It was never caught because `--set stability` had never had
a committed ledger; the set existed and its output went to a terminal.

It is also not the run-to-run irreproducibility Phase 3 fixed.
`spaces_reproducible.py` returns all six identical across four identical runs.
Rotation is a different perturbation: it leaves the span of a target set alone
while changing the individual vectors in it.

Every one of the six contains a carbonyl, which points at the mechanism. A
terminal heteroatom emits three non-bonding directions, two of them from
`perpendicular_pair`, whose docstring and `cas_01` both record that it is not
covariant per vector and that only its span is. A span-only guarantee is enough
for a pure p target, because the projector depends on the span alone. It is not
enough once each direction becomes an sp hybrid: adding the same s component to
two arbitrary in-plane directions produces a pair whose span does depend on
which two were chosen. So the lone-pair amplitude, which §2.3 needs to be
non-zero to separate a lone pair from the sigma frame, is what turns a
span-invariant construction into a vector-dependent one.

That is a hypothesis with a strong pattern behind it rather than a measurement,
and it is written down as such. Closing it properly means changing perception
and re-measuring everything downstream, which is a plan of its own; it is
recorded in the method document as a stated limitation with its number, which
is where a measured limitation belongs.
