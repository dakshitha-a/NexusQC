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
the degenerate `(6e,3o)` defect that
`tests/backend/casreco_02_avas_seed_and_guard.py` exists to prevent,
reintroduced by a different route. `geometry.py` must therefore also emit
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

- [todo] P2.1: A harness entry point onto the legacy runners
- [todo] P2.2: A curated reference table of best estimates
- [todo] P2.3: The head-to-head harness
- [todo] P2.4: A recorded legacy baseline
- merged: -

## Phase 3: Ranking, balancing and sizing

- [done] P3.1: APC ranking within the candidate pool
  evidence: app/chemistry/cas/ranking.py → "APC entropies from Fock and exchange only, ~0.1s; ranks inside the pool because raw APC gives pyrrole (18e,12o) in def2-SVP vs (22e,13o) in def2-TZVP"
- [done] P3.2: Chemical completion and balance
  evidence: tests/backend/cas_05_tiers.py → "38/38; every tier holds electrons and is not full, including the O2 triplet that the closed-shell occupation bug turned into (2e,3o)"
- [done] P3.3: Cost tiers instead of a cap
  evidence: app/chemistry/cas/feasibility.py → "Weyl-Paldus CSF counts; CAS(6,6) singlet = 175 CSFs / 400 determinants; (80e,80o) reports a cost instead of raising"
- [done] P3.4: The orchestrator, ground-state path end to end
  evidence: tests/backend/cas_05_tiers.py → "benzene (6,6), butadiene (4,4), formaldehyde (6,4), water (8,6) via the sigma fallback; identical in cc-pVDZ and def2-TZVP; 0.1-1.0s"
- merged: -

## Phase 4: The excited-state branch

- [todo] P4.1: TDA, NTOs and state character
- [todo] P4.2: Rydberg detection and the honest basis limit
- [todo] P4.3: States drive which orbitals enter the space
- [todo] P4.4: Bright, dark and mixed-character states
- merged: -

## Phase 5: The verification tier

- [todo] P5.1: Confirm the states are really there
- merged: -

## Phase 6: Wire the engine into the app

- [todo] P6.1: The new runner
- [todo] P6.2: Registry, params and retirements
- [todo] P6.3: Dispatch and worker
- [todo] P6.4: Loose ends the rebuild leaves behind
- [todo] P6.5: Legacy leaves pyscf_runner.py
- [todo] P6.6: The prompt names tools that do not exist
- merged: -

## Phase 7: The portable handoff

Without this, basis-agnosticism is only a claim in a summary table.

- [todo] P7.1: An active space that survives a change of basis
- [todo] P7.2: The follow-up draft carries the specification
- [todo] P7.3: ORCA and BAGEL rebuild the space in the target basis
- [todo] P7.4: The same space, three basis sets, one job chain
- merged: -

## Phase 8: Tests, frontend and docs

- [todo] P8.1: Retire the legacy test scripts
- [todo] P8.2: The drawer shows what the new engine reports
- [todo] P8.3: Docs follow the code
- merged: -

## Phase 9: Evaluate, then decide

- [todo] P9.1: The full head-to-head
- [todo] P9.2: The verdict, and legacy's fate
- merged: -

## Phase 10: The method, written up

- [todo] P10.1: A scientific description of what was built
- [todo] P10.2: The benchmarks, in the writeup
- merged: -

---

## Found along the way, not fixed here

Nothing yet.
