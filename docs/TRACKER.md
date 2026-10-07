<!-- artifact: https://claude.ai/artifact/Q2ufG63Tvp8HYUrpQ2GN7q -- re-render with scripts/render_tracker_html.py and re-publish to THIS url -->
# Tracker: a QUESTDB benchmark for the CAS engine, comparable to King et al. 2022

**Opened 2026-10-06.** Seven phases. The tracker before this one is
[`trackers/2026-09-shared-stack-and-update-notices.md`](trackers/2026-09-shared-stack-and-update-notices.md).
**Exactly one tracker is active at a time.**

## Rules (enforced by `scripts/check_tracker.py`)

- Step status is exactly one of `todo` | `in-progress` | `done`.
- A step may be marked `done` **only with an evidence field**: one path that
  exists on disk plus a one-line observed result.
- The tracker edit ships **in the same commit** as the step's final change.
- A phase's `merged` row records the commit hash the stage landed as.

Format for a step row:

```
- [status] P<phase>.<step>: <short name>
  evidence: <path> → "<observed result>"   (required when done)
```

---

## Why this plan exists

On 2026-10-05 the user asked for a benchmark of the CAS recommendation engine
that can be compared with the one in Wardzala et al., *Chem. Rev.* 2026,
126, 4592. That review's main benchmark is King, Hermes, Truhlar and
Gagliardi, *JCTC* 2022, 18, 6065.

- **What King et al. did:** they chose active spaces with APC-2 for all 542
  QUESTDB vertical excitations in aug-cc-pVTZ.
- **What they scored:** SA-CASSCF, tPBE, tPBE0 and SC-NEVPT2, each against
  the theoretical best estimates.
- **What counts as a good space:** one whose SA-CASSCF error is below 1.1 eV.
  APC-2 managed this for about 80% of excitations.
- **Why it suits us:** our engine also ranks orbitals by APC entropy, so the
  comparison is close to like for like.

The user chose to run the full 542 in batches of about ten parallel
calculations. Every category is scored and reported separately: Rydberg,
doublet and double excitations included.

Mid-plan, the user also asked for two things. The runner must survive a Claude
restart. Its status must be watched by monitors, about once an hour.

The plan of record is `.claude/plans/federated-percolating-stream.md`.

## Phase 0: validate the harness before spending compute

- [done] P0.1: King's three shipped Zenodo tests reproduce their energies on our PySCF 2.14 + pyscf-forge stack to about 0.01 eV
  evidence: scripts/casbench/quest_reproduce_king.py → "water-x1, water-x6, cn-x1: largest component difference 2.6e-6 Eh, excitation energies within 0.0001 eV (docs/casbench/questdb-phase0.md)"
- [done] P0.2: symmetry probe on water, ethylene, pyrazine says whether the engine's active space is irrep-closed, and how to fix it if not
  evidence: scripts/casbench/quest_symprobe.py → "closed for 7 of 8 molecules; formaldehyde's oxygen lone-pair hybrid is 98% B2 / 20% A1, so symmetrisation is a pipeline stage (questdb-phase0.md)"
- [done] P0.3: the engine can be asked for "the j-th state of irrep Γ", and accepts a doublet ROHF reference
  evidence: docs/casbench/questdb-phase0.md → "irrep-restricted and triplet TDA feed analyse/narrow unmodified on singlets and doublets; BeH (1,1) and CH (1,2) are unrepresentable, a separate failure class"

## Phase 1: inputs

- [done] P1.1: quest_fetch.py builds a 542-row manifest in a gitignored cache, every row with a geometry and an irrep that resolves in PySCF
  evidence: scripts/casbench/quest_fetch.py → "manifest: 542 rows; 0 problem(s). 94 targets (17%) carry a different irrep label under PySCF 2.14 than King's 2.0 labels; re-derived from King's own CI vectors"

## Phase 2: the harness

- [done] P2.1: quest_bench.py runs APC-2, engine-native and engine-capped through one SA-CASSCF / NEVPT2 / MC-PDFT path
  evidence: scripts/casbench/quest_bench.py → "water-x1 and formaldehyde-x1 run in all three modes; APC-2 picks King's exact space on 435/540 rows (quest_apc_sizes.py)"
- [todo] P2.2: the APC-2 control is within about 0.1 eV of King's Aug(12,12) rows on 10 stratified excitations

## Phase 3: a runner that survives a Claude restart (raised mid-run by the user)

- [done] P3.1: quest_ctl.sh start/status/stop/resume; detached runner, pidfile, heartbeat, one subprocess per calculation
  evidence: scripts/casbench/quest_ctl.sh → "runner killed with -9 mid-run: 7 workers kept computing; resume adopted the 6 still alive and relaunched none (calib run, 2026-10-06 19:22)"
- [todo] P3.2: restart test — kill a worker and the runner mid-run; resume loses and duplicates no rows

## Phase 3A: fix the two engine defects calibration found (raised mid-run by the user, 2026-10-06)

- [todo] P3A.1: interior linear centres (acetylene, diacetylene, cyanoacetylene, cyanogen, ketene, diazomethane) get a degenerate pi pair in perceive()
- [todo] P3A.2: state narrowing keeps every singly occupied orbital and counts electrons from occupations (CN, allyl, BeF)
- [todo] P3A.3: run_bench spaces/narrowed/stability re-run; improved/flat/regressed reported; method doc, CHANGELOG updated
- [todo] P3A.4: QUESTDB calibration engine rows re-run on the fixed engine

## Phase 4: calibration and the full run

- [todo] P4.1: a calibration batch of 10 excitations gives the full run's cost, reported to the user
- [todo] P4.2: full run launched; hourly status cron and an event monitor armed (raised mid-run by the user); HANDOFF entry added
- [todo] P4.3: all 542 × 3 modes complete, or each missing row named with its cause

## Phase 5: analysis

- [todo] P5.1: quest_report.py writes docs/casbench/questdb.md, and its --check recomputes every aggregate independently

## Phase 6: write-up and close

- [todo] P6.1: CAS_ENGINE_METHOD.md abstract, §3.3 and §4.1 rewritten around the new numbers; README checked
- [todo] P6.2: HANDOFF entry removed, monitors stopped, tracker closed, pushed

## Findings raised by the benchmark (not fixed mid-run; each needs a decision)

Fixing the engine while the benchmark runs would leave rows measured on two
different engines, so defects it exposes are recorded here and raised with
the user instead.

- **State narrowing drops the singly occupied orbital of a radical.** CN
  (doublet, aug-cc-pVTZ): the engine's pool is (7e,6o); its state-narrowed
  tier for the first ²B₁ state is (4e,4o), with the SOMO outside the space,
  so the unpaired electron would sit in a closed core. The harness records
  the row as `inconsistent_space` (calib run, cn-x1|engine, 2026-10-06).
- **A valence space cannot hold a high Rydberg state.** Ammonia's third ¹A'
  (n→3p, TBE 9.96 eV): the engine keeps its (8e,7o) valence space although
  its own TDA labels all three requested states Rydberg; SA-CASSCF error
  +1.16 eV. Expected from the engine's scope, recorded so the Rydberg split
  is read with it in mind.
- **Perception finds no π system in a linear molecule.** Acetylene, run
  the way the product runs it (no symmetry, density fitting, cc-pVDZ or
  aug-cc-pVTZ): `perceive(..., include_sigma=False)` returns no targets at
  all, so the recommendation falls back to the σ framework, (6e,6o) of
  Ag/B1u σ orbitals with no π or π\*. Its ³Σu⁺ (ππ\*) row comes out at
  13.7 eV against a TBE of 5.53 (calib run, acetylene-x3|engine).
