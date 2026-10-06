# QUESTDB benchmark, Phase 0: can King et al.'s protocol be applied here at all?

Measured 2026-10-06 at commit `b4d21e0`, PySCF 2.14.0, pyscf-forge 1.1.1,
numpy 2.3.5, `OMP_NUM_THREADS=8`. This ledger is the gate before any
benchmark compute is spent. The benchmark it gates is the one in
`docs/TRACKER.md`: the NexusQC engine and APC-2 run through one harness
over King, Hermes, Truhlar and Gagliardi's 542 QUESTDB excitations
(*JCTC* 2022, 18, 6065).

Three questions are asked here.

1. **P0.1:** does our software give King's energies when handed King's own
   wavefunctions?
2. **P0.2:** does the engine's active space keep the molecule's symmetry? King's
   state averages target symmetry labels, so it has to.
3. **P0.3:** can the engine be asked for "the j-th state of symmetry Γ"? Can it
   do that for triplets, and from a doublet radical?

## Inputs

- **Source:** Zenodo record 14889616, CC-BY 4.0. That is King et al.'s
  `compiled_data.tar.gz`, 7,246,269,119 bytes. It holds one Python pickle per
  excitation and basis/size combination.
- **What each pickle holds:** the final SA-CASSCF orbitals, one CI vector per
  averaged state, and a per-state energy table. The table has the MC-PDFT
  energy decomposition, SC-NEVPT2, symmetry label, ⟨S²⟩, weight and
  convergence flag. Each pickle also holds the solver settings used.
- **Where it lives:** the archive is downloaded into the gitignored
  `.cache/casbench_quest/` and is never committed.
- **Why the pickles need converting:** they were written with pandas 1.3.5 and
  PySCF 2.0. Neither pandas 2 nor PySCF 2.14 can unpickle them: pandas 2 fails
  inside its block manager. So `scripts/casbench/quest_unpickle.py` reads them
  once, in a side environment with those versions. It rewrites each one as
  JSON (metadata and energy table) plus `.npz` (orbitals and CI vectors).
- **How the side environment was built** (what worked, in order):
  1. `conda create -p .cache/casbench_quest/env_pd13 -c conda-forge
     python=3.9 pandas=1.3.5 numpy=1.21`
  2. `pip install pyscf==2.0.1`. The pickles reference PySCF classes.
  3. `pip install numpy==1.21.6 "scipy<1.9"`. Step 2 upgrades numpy, which
     breaks pandas 1.3's compiled extensions with "numpy.dtype size
     changed".

## P0.1: King's energies, reproduced from King's wavefunctions

- **Script:** `scripts/casbench/quest_reproduce_king.py`. It is King's three
  shipped test scripts rewritten for this environment. The originals import
  `mrh`, which is not installed here, and call `DataFrame.append`, which pandas
  2 removed.
- **What it does, per averaged state:**
  1. Rebuilds the molecule from the stored geometry (bohr), basis, charge and
     spin, with symmetry on.
  2. Sets the active electrons to the highest Ms the state's ⟨S²⟩ allows, as
     King did. So (5,3) for the water triplet.
  3. Evaluates the tPBE energy decomposition with pyscf-forge's
     `mcpdft.CASCI` on the stored orbitals and CI vector, at the stored grid
     level.
  4. Evaluates the SC-NEVPT2 correction with `mrpt.NEVPT`.
- **Not done here:** no SCF, no CASSCF and no orbital optimisation. Identical
  wavefunctions go in, so any difference is in the downstream code.
- **Rows:** the three systems King chose to ship tests for, all
  jun-cc-pVTZ with a max(8,8) space:
  - water-x1: ¹B₁ Rydberg, a singlet;
  - water-x6: ³A₁, a triplet, averaged with a singlet ground state;
  - cn-x1: a doublet radical.

| row | basis functions | space | states | largest component difference | tPBE excitation, ours / King's | NEVPT2 excitation, ours / King's |
|---|---|---|---|---|---|---|
| water-x1 | 67 | (8,8) | A₁, B₂ | 2.6 × 10⁻⁶ Eh (e_otx, B₂ state) | 7.8079 / 7.8078 eV | 8.1036 / 8.1036 eV |
| water-x6 | 67 | (8,8) | A₁ singlet, A₁ triplet | 2 × 10⁻⁸ Eh | 10.1787 / 10.1787 eV | 10.5343 / 10.5343 eV |
| cn-x1 | 78 | (5,7) | A₁, B₁ doublets | 2.3 × 10⁻⁷ Eh | 0.9236 / 0.9235 eV | 1.0289 / 1.0289 eV |

- **Result: pass.** The largest difference in any energy component of any
  state is 2.6 × 10⁻⁶ Eh, which is 7 × 10⁻⁵ eV. King's own scripts assert
  agreement to 1 × 10⁻⁵ Eh.
- **Where the differences are:** every non-zero difference sits in the
  on-top exchange or correlation term. Those are the grid-integrated parts,
  which is where a different PySCF version would be expected to differ.
- **NEVPT2 and the wavefunction terms:** they agree to round-off, about
  10⁻¹⁴ Eh.
- **Conclusion:** our MC-PDFT and NEVPT2 give King's numbers. A later
  difference between our results and King's cannot be blamed on downstream
  code.
- **Excitation energy definition:** in this table it is the highest-energy
  state minus the ground state, King's rule. It is shown for both methods.
- **Settings from the files, not the paper:** the stored metadata, not the
  paper text, is the source of truth for solver settings. This Jun88 pickle
  records `grid_level` 9, where the paper's text discusses level 3. The
  benchmark reads every setting from each row's own metadata for that reason.
- **Output reproduces with:**

```
python3 scripts/casbench/quest_reproduce_king.py Jun88 water-x1 water-x6 cn-x1
```

## P0.2: does the engine's space keep the molecule's symmetry?

- **Script:** `scripts/casbench/quest_symprobe.py cc-pvdz`. Its log is kept
  at `.cache/casbench_quest/phase0_symprobe.log`.
- **Setup:** each molecule is built with symmetry on, at King's geometry.
  The engine's `recommend` is run on a stabilised density-fitted RHF/ROHF.
- **The measurement, per tier:**
  1. The active orbitals are projected onto each irrep's S-orthonormal
     symmetry orbitals.
  2. The singular values of each projection are taken.
  3. A singular value of 1 is a symmetry direction lying wholly inside the
     active space. A value of 0 lies wholly outside it.
- **What "closed" means:** the space keeps symmetry, or is irrep-closed, when
  every singular value is 0 or 1 and the 1s add up to the number of active
  orbitals.
- **Why it matters:** King's state average asks the CI solver for states of
  one irrep. That is only well defined if every active orbital belongs to one
  irrep.

| molecule | point group | recommended space | closed? | what breaks it |
|---|---|---|---|---|
| water | C₂v | (8,6) | yes | |
| formaldehyde | C₂v | (6,4) | **no** | one active direction is 98% B₂ and 20% A₁ |
| ethylene | D₂h | (2,2) | yes | |
| pyrazine | D₂h | (10,8) | yes | |
| allyl radical | C₂v | (3,3) | yes | |
| BeH radical | C₂v | (1,1) | yes, but see P0.3 | |
| CH radical | C₂v | (1,2) | yes, but see P0.3 | |
| BeF radical | C₂v | (7,4) | yes | |

- **The formaldehyde break:**
  - **What breaks it:** an oxygen lone-pair target. The engine's targets
    are oriented hybrids, and this one is aimed off the C₂ axis. So the
    selected orbital mixes the in-plane lone pair (B₂) with the σ lone pair
    (A₁).
  - **Expect more of these:** carbonyls are common in QUESTDB. Acetaldehyde,
    acetone, acrolein, formamide, ketene, benzoquinone and cyclopropenone all
    have one. So this is expected on a large fraction of rows, not as a rare
    exception.
- **The maximal tiers:** they add the oriented σ framework. They are not closed
  for any polyatomic molecule here, but the benchmark does not use them.
- **Consequence for the benchmark:** symmetrising the space is a pipeline
  stage, applied to every row.
  - **The rule:** pool every (irrep, singular value) pair across irreps, sort
    them in descending order, and keep the top `ncas` directions.
  - **Electrons:** recount the active electrons from the symmetrised
    orbitals' overlap with the occupied orbitals. Swapping a hybrid for a pure
    direction can change the count.
  - **What each row records:** the smallest singular value kept, the largest
    dropped, and whether the electron count changed.

## P0.3: asking the engine for a state of a given symmetry and spin

- **What the product does:** `run_cas_recommendation` takes a number of
  states. It runs a CAM-B3LYP TDA for the lowest roots of any symmetry and
  narrows the space to the states requested.
- **What King's protocol asks for:** a particular state, "the j-th ¹A₂" or
  "the first ³B₁".
- **What the probe checked:**
  - that a TDA restricted to one irrep (`td.wfnsym`) runs and hands its roots
    to the engine's `analyse` and `add_state_narrowed_tier` without
    modification;
  - that the same works for a triplet TDA (`td.singlet = False`);
  - that it works on a ROKS reference for doublets.
- **Result:** all three work on every molecule in the table above.
- **The harness's request:** the irrep-restricted TDA's lowest j roots are
  the j states of the target irrep that King's state average contains. The
  engine is handed exactly those.
- **The off-by-one rule:**
  - **When the target irrep is the ground state's irrep:** QUESTDB's
    numbering counts the ground state. So "2 ¹A₁" is the first A₁ excitation,
    and the engine is given j − 1 excited states.
  - **Otherwise:** it is given j.
- **This goes beyond the product:** the product cannot request a triplet or a
  symmetry label. The benchmark ledger reports that as a gap, not as
  something the engine did.
- **Two unrepresentable spaces:**
  - **BeH (1,1):** it holds one configuration, so it has no excited state at
    all.
  - **CH (1,2):** it has no A₁ excited configuration.

  The benchmark therefore checks each space before any CASSCF. A space with no
  configuration of the target symmetry and spin is recorded as
  **unrepresentable**, with its size and the reason. It counts as a failure in
  the good-space fraction, kept separate from convergence failures and from
  errors above 1.1 eV. These two radicals are main-group but not organic,
  which is outside the scope the engine claims.

## Decisions this phase fixes for the harness

These follow from the measurements above.

- **One SCF per row, shared by both selectors:** each row gets one
  conventional, non-density-fitted RHF/ROHF reference, with symmetry on and
  stabilised. The engine and APC-2 both start from it. CASSCF, NEVPT2 and
  MC-PDFT are all run without density fitting.
  - **Why:** this matches King, and P0.1 reproduced him that way. It also
    avoids a missing fitting basis for beryllium, which stopped the
    density-fitted probe outright.
  - **Sensitivity check:** the product's own density-fitted reference is
    tried once, on the calibration batch.
- **State composition comes from King's files:** each row's state average
  (irreps, spins and weights) is read from its Aug1212 record, not derived.
  - **Different irreps need two CI solvers:** when the target irrep differs
    from the ground state's, the average mixes two solvers via
    `state_average_mix`. A single solver can target only one irrep. In P0.1
    this was water-x1, whose two states are A₁ and B₂.
- **Solver settings come from each row's own record:** convergence
  thresholds, level shift, iteration caps and grid level are all read per
  row.
- **Geometries are King's:** this keeps the comparison like for like. King's SI
  names four systems whose geometries may carry a unit-conversion error:
  vinyl, CON, CNO and NO. The ledger flags them rather than correcting them.
