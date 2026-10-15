# casbench: QUESTDB, the CAS engine against APC-2

Written by `scripts/casbench/quest_report.py --run main --write` at commit
`5de3a2f`. Do not edit by hand: the next write overwrites it. Interpretation
belongs in `docs/CAS_ENGINE_METHOD.md`, not here. The harness and its
validation are described in `docs/casbench/questdb-phase0.md`. Every
aggregate below is recomputed by a second, independent path with
`quest_report.py --check`. The M values behind the M_max split are not part
of that check: both paths read them from `quest_mdiag.py`, which validates them
against King's SI Table S12 and his quartiles before it writes them.

## What was run

- **Benchmark:** the 542 QUESTDB vertical excitations of King, Hermes,
  Truhlar and Gagliardi, JCTC 2022, 18, 6065, with their geometries, state
  averages and theoretical best estimates (TBEs). Data from Zenodo record
  14889616 (CC-BY 4.0).
- **Basis:** aug-cc-pVTZ, as in King's headline result.
- **Three modes per excitation, one harness:** `apc2` reruns King's APC-2
  selector here, eps 1e-3, capped at max(12,12) = 226,512 CSFs. `engine` is
  the NexusQC engine's own space for the state, uncapped. `engine_capped` is
  that space cut to the same CSF budget by lowest entropy.
- **Downstream, identical for every mode:** SA-CASSCF, tPBE, tPBE0
  (0.75 tPBE + 0.25 SA-CASSCF) and SC-NEVPT2. NEVPT2 is skipped above 24
  active orbitals, because a (4,40) space needed 98 GB.
- **Scoring:** King's rule. The target is the highest-tPBE root of the target
  irrep and spin. The ground state is the lowest-tPBE root of its group.
- **Good space:** |SA-CASSCF − TBE| < 1.1 eV, King's filter. King reports
  436/542 good.
- **Run:** started 2026-10-07T05:54:24+00:00 at commit `6dba233`. The last row
  finished 2026-10-15T00:59:48+00:00, 187 h of wall time. 10 workers ran at
  once, each with 6 OpenMP threads and 48 GB. The rows took
  1468 worker-hours in total. Every row ran in its own subprocess.
- **Harness changes during the run:** each row's subprocess loads the
  harness when it starts, so later rows ran on later commits. None of these
  changes alters a computed energy. Rows that hit a memory error before the
  memory fixes were reset and rerun.
  - `483eca4 QUESTDB runner: 48 GB per worker by default`
  - `ff23c3e QUESTDB harness: drop in-core ERIs after the SCF; restore cached SCFs without re-running`
  - `3457059 QUESTDB harness: count resident memory once in PySCF's CSF spin-coupling check`
  - `32e2e2b QUESTDB harness: stamp each result with its finish time, so the runner's rate and ETA mean something`
  - `f8d836d QUESTDB harness: M diagnostic reshapes CI vectors explicitly and can no longer fail a row`
  - `170326d QUESTDB harness: skip SC-NEVPT2 above 24 active orbitals and say so`
  - `1ad27e5 quest_run: a wall-capped row is recorded as not_converged instead of retried`
  - `90feeda QUESTDB harness: count M's open shells from the dominant configuration in natural orbitals`
- **Re-scored rows:** 10 excitations were carried over from the
  calibration batch, which picked the target root in CASSCF order. Their
  stored per-state energies are re-scored here by King's rule rather than
  rerun: acetone-x7, acetylene-x3, acrolein-x5, allyl-x1, ammonia-x4, aza-naphthalene-x1, benzene-x1, cn-x1, formaldehyde-x1, water-x1.

## How to read the tables

- **Denominator:** every table counts all excitations of its category. A row
  that produced no good space counts as not good, whatever the reason, as in
  King's 436/542.
- **scored:** rows that produced energies.
- **not converged:** SA-CASSCF stopped without converging. The row has
  energies and is scored.
- **wall cap:** SA-CASSCF was still running at the 48 h per-row cap. The row
  has no energies. These are 6 rows: aza-naphthalene-x11 (apc2), aza-naphthalene-x13 (apc2), aza-naphthalene-x18 (apc2), aza-naphthalene-x8 (apc2), aza-naphthalene-x9 (apc2), naphthalene-x11 (apc2).
- **unrepresentable:** the space holds no CSF of the target irrep and spin,
  so the requested state cannot exist in it. This is the engine's answer for
  that state. It is mostly a valence space asked for a Rydberg state.
- **too large:** the native engine space has more than 1e6 CSFs. The
  `engine_capped` row then runs the capped space.
- **declined:** the engine perceived no geometric targets and built no
  space. These are: beryllium-x1, con-x1, con-x2.
- **failed:** two attempts without a result, for any other reason.
- **missing:** no row was recorded.
- **Error statistics:** each is given three ways. Over each selector's own
  good rows is King's convention. Over the rows good for both selectors in a
  pair, a stricter filter cannot buy a lower error. Over every scored row,
  there is no filter at all.
- **`king`:** King et al.'s own Aug(12,12) numbers from Zenodo for the same
  excitations, scored by the same filter.
- **M_max split:** M_max is the larger of the ground- and excited-state M
  diagnostics (Tishchenko, Zheng and Truhlar, JCTC 2008). King's cut is
  0.14, the lowest M_max of any double excitation. Here M is computed by
  `quest_mdiag.py` from King's own Aug(12,12) wave functions, as King
  computed it, so the split is the same for all three modes. That script
  reproduces all 16 values in King's SI Table S12 and his quartiles over
  436 good rows (0.08 / 0.11 / 0.44) before it writes anything.
- **The run's own stored M is not used:** the harness counted the dominant
  configuration's open shells from the largest single determinant in the
  CASSCF orbitals. Those orbitals are any rotation of the active space, so
  the count was wrong for about a fifth of closed-shell ground states. The
  run did not keep its CI vectors, so its M cannot be redone. The harness
  is fixed for later runs and now stores each state's natural occupations.
- **Flagged geometries:** King's SI names cno, con, no, vinyl as possibly carrying
  a unit-conversion error. Their 10 rows are run on King's
  geometries as given, and marked in the last column below.

## Results

#### every excitation: 542 excitations

| selector | good space | scored | not converged | wall cap | unrepresentable | too large | declined | failed | missing |
|---|---|---|---|---|---|---|---|---|---|
| apc2 | 433/542 (80%) | 536 | 1 | 6 | 0 | 0 | 0 | 0 | 0 |
| engine | 322/542 (59%) | 443 | 1 | 0 | 92 | 4 | 3 | 0 | 0 |
| engine_capped | 322/542 (59%) | 447 | 1 | 0 | 92 | 0 | 3 | 0 | 0 |
| king | 436/542 (80%) | 540 | 0 | 0 | 0 | 0 | 0 | 0 | 2 |

MAE / MSE / RMSE / max |error| (eV) over each selector's own good rows:

| selector | n | casscf | tpbe | tpbe0 | nevpt2 |
|---|---|---|---|---|---|
| apc2 | 433 | 0.40 / +0.17 / 0.49 / 1.10 | 0.24 / -0.08 / 0.36 / 1.69 | 0.20 / -0.01 / 0.30 / 1.47 | 0.18 / +0.15 / 0.31 / 2.20 |
| engine | 322 | 0.35 / +0.16 / 0.45 / 1.09 | 0.21 / +0.00 / 0.31 / 1.58 | 0.16 / +0.04 / 0.26 / 1.38 | 0.19 / +0.14 / 0.29 / 1.45 |
| engine_capped | 322 | 0.35 / +0.16 / 0.45 / 1.09 | 0.21 / +0.00 / 0.31 / 1.58 | 0.16 / +0.04 / 0.26 / 1.38 | 0.19 / +0.14 / 0.29 / 1.45 |
| king | 436 | 0.40 / +0.18 / 0.50 / 1.10 | 0.24 / -0.08 / 0.35 / 1.64 | 0.19 / -0.02 / 0.29 / 1.40 | 0.18 / +0.15 / 0.30 / 1.84 |

MAE (eV) over the rows good for BOTH selectors in each pair:

| pair | n | casscf (a, b) | tpbe (a, b) | tpbe0 (a, b) | nevpt2 (a, b) |
|---|---|---|---|---|---|
| apc2 vs engine | 285 | 0.35, 0.32 | 0.21, 0.21 | 0.17, 0.16 | 0.18, 0.18 |
| apc2 vs engine_capped | 285 | 0.35, 0.32 | 0.21, 0.21 | 0.17, 0.16 | 0.18, 0.18 |
| apc2 vs king | 424 | 0.39, 0.40 | 0.24, 0.24 | 0.19, 0.19 | 0.18, 0.18 |
| engine vs engine_capped | 322 | 0.35, 0.35 | 0.21, 0.21 | 0.16, 0.16 | 0.19, 0.19 |
| engine vs king | 289 | 0.32, 0.36 | 0.20, 0.21 | 0.15, 0.16 | 0.18, 0.17 |
| engine_capped vs king | 289 | 0.32, 0.36 | 0.20, 0.21 | 0.15, 0.16 | 0.18, 0.17 |

MAE / MSE / RMSE / max |error| (eV) over every scored row, no filter:

| selector | n | casscf | tpbe | tpbe0 | nevpt2 |
|---|---|---|---|---|---|
| apc2 | 536 | 0.75 / +0.44 / 1.21 / 9.13 | 0.51 / +0.07 / 1.05 / 8.76 | 0.47 / +0.16 / 1.03 / 8.86 | 0.49 / +0.34 / 1.12 / 8.95 |
| engine | 443 | 1.19 / +0.98 / 2.29 / 12.78 | 0.80 / +0.42 / 1.78 / 11.92 | 0.77 / +0.56 / 1.84 / 11.84 | 0.82 / +0.67 / 1.88 / 12.83 |
| engine_capped | 447 | 1.23 / +1.01 / 2.33 / 12.78 | 0.80 / +0.42 / 1.77 / 11.92 | 0.78 / +0.57 / 1.84 / 11.84 | 0.83 / +0.68 / 1.88 / 12.83 |
| king | 540 | 0.75 / +0.45 / 1.22 / 9.13 | 0.49 / +0.05 / 1.02 / 8.76 | 0.45 / +0.15 / 1.01 / 8.86 | 0.48 / +0.33 / 1.09 / 8.95 |

#### singlet excitations: 295 excitations

| selector | good space | scored | not converged | wall cap | unrepresentable | too large | declined | failed | missing |
|---|---|---|---|---|---|---|---|---|---|
| apc2 | 218/295 (74%) | 291 | 1 | 4 | 0 | 0 | 0 | 0 | 0 |
| engine | 147/295 (50%) | 243 | 1 | 0 | 48 | 3 | 1 | 0 | 0 |
| engine_capped | 147/295 (50%) | 246 | 1 | 0 | 48 | 0 | 1 | 0 | 0 |
| king | 219/295 (74%) | 293 | 0 | 0 | 0 | 0 | 0 | 0 | 2 |

MAE / MSE / RMSE / max |error| (eV) over each selector's own good rows:

| selector | n | casscf | tpbe | tpbe0 | nevpt2 |
|---|---|---|---|---|---|
| apc2 | 218 | 0.48 / +0.19 / 0.56 / 1.10 | 0.31 / -0.14 / 0.44 / 1.69 | 0.25 / -0.06 / 0.35 / 1.47 | 0.22 / +0.18 / 0.36 / 2.20 |
| engine | 147 | 0.42 / +0.29 / 0.54 / 1.09 | 0.27 / -0.04 / 0.40 / 1.58 | 0.21 / +0.04 / 0.33 / 1.38 | 0.23 / +0.18 / 0.36 / 1.45 |
| engine_capped | 147 | 0.42 / +0.29 / 0.54 / 1.09 | 0.27 / -0.04 / 0.40 / 1.58 | 0.21 / +0.04 / 0.33 / 1.38 | 0.23 / +0.18 / 0.36 / 1.45 |
| king | 219 | 0.49 / +0.19 / 0.57 / 1.10 | 0.31 / -0.14 / 0.43 / 1.64 | 0.25 / -0.06 / 0.34 / 1.40 | 0.21 / +0.18 / 0.35 / 1.69 |

MAE (eV) over the rows good for BOTH selectors in each pair:

| pair | n | casscf (a, b) | tpbe (a, b) | tpbe0 (a, b) | nevpt2 (a, b) |
|---|---|---|---|---|---|
| apc2 vs engine | 123 | 0.46, 0.39 | 0.29, 0.27 | 0.22, 0.20 | 0.22, 0.21 |
| apc2 vs engine_capped | 123 | 0.46, 0.39 | 0.29, 0.27 | 0.22, 0.20 | 0.22, 0.21 |
| apc2 vs king | 212 | 0.48, 0.48 | 0.31, 0.30 | 0.25, 0.25 | 0.22, 0.21 |
| engine vs engine_capped | 147 | 0.42, 0.42 | 0.27, 0.27 | 0.21, 0.21 | 0.23, 0.23 |
| engine vs king | 125 | 0.40, 0.46 | 0.26, 0.27 | 0.20, 0.21 | 0.21, 0.21 |
| engine_capped vs king | 125 | 0.40, 0.46 | 0.26, 0.27 | 0.20, 0.21 | 0.21, 0.21 |

MAE / MSE / RMSE / max |error| (eV) over every scored row, no filter:

| selector | n | casscf | tpbe | tpbe0 | nevpt2 |
|---|---|---|---|---|---|
| apc2 | 291 | 0.87 / +0.62 / 1.21 / 4.85 | 0.58 / +0.14 / 0.98 / 4.91 | 0.54 / +0.26 / 0.96 / 4.90 | 0.57 / +0.52 / 1.09 / 5.12 |
| engine | 243 | 1.61 / +1.52 / 2.74 / 12.78 | 1.06 / +0.61 / 2.06 / 11.92 | 1.04 / +0.84 / 2.14 / 11.84 | 1.09 / +1.00 / 2.20 / 12.83 |
| engine_capped | 246 | 1.65 / +1.56 / 2.78 / 12.78 | 1.07 / +0.62 / 2.06 / 11.92 | 1.05 / +0.86 / 2.15 / 11.84 | 1.10 / +1.01 / 2.20 / 12.83 |
| king | 293 | 0.88 / +0.63 / 1.22 / 5.22 | 0.54 / +0.10 / 0.91 / 4.91 | 0.51 / +0.24 / 0.90 / 4.90 | 0.54 / +0.49 / 1.03 / 5.12 |

#### triplet excitations: 196 excitations

| selector | good space | scored | not converged | wall cap | unrepresentable | too large | declined | failed | missing |
|---|---|---|---|---|---|---|---|---|---|
| apc2 | 178/196 (91%) | 194 | 0 | 2 | 0 | 0 | 0 | 0 | 0 |
| engine | 155/196 (79%) | 172 | 0 | 0 | 23 | 1 | 0 | 0 | 0 |
| engine_capped | 155/196 (79%) | 173 | 0 | 0 | 23 | 0 | 0 | 0 | 0 |
| king | 180/196 (92%) | 196 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |

MAE / MSE / RMSE / max |error| (eV) over each selector's own good rows:

| selector | n | casscf | tpbe | tpbe0 | nevpt2 |
|---|---|---|---|---|---|
| apc2 | 178 | 0.33 / +0.17 / 0.42 / 1.08 | 0.17 / +0.01 / 0.26 / 1.41 | 0.14 / +0.05 / 0.22 / 1.27 | 0.15 / +0.13 / 0.25 / 1.68 |
| engine | 155 | 0.29 / +0.05 / 0.37 / 1.01 | 0.16 / +0.06 / 0.21 / 0.93 | 0.12 / +0.06 / 0.18 / 0.92 | 0.16 / +0.12 / 0.22 / 0.81 |
| engine_capped | 155 | 0.29 / +0.05 / 0.37 / 1.01 | 0.16 / +0.06 / 0.21 / 0.93 | 0.12 / +0.06 / 0.18 / 0.92 | 0.16 / +0.12 / 0.22 / 0.81 |
| king | 180 | 0.34 / +0.18 / 0.43 / 1.08 | 0.17 / +0.01 / 0.26 / 1.41 | 0.14 / +0.05 / 0.22 / 1.26 | 0.16 / +0.13 / 0.27 / 1.84 |

MAE (eV) over the rows good for BOTH selectors in each pair:

| pair | n | casscf (a, b) | tpbe (a, b) | tpbe0 (a, b) | nevpt2 (a, b) |
|---|---|---|---|---|---|
| apc2 vs engine | 142 | 0.27, 0.27 | 0.16, 0.16 | 0.14, 0.12 | 0.15, 0.16 |
| apc2 vs engine_capped | 142 | 0.27, 0.27 | 0.16, 0.16 | 0.14, 0.12 | 0.15, 0.16 |
| apc2 vs king | 176 | 0.32, 0.33 | 0.17, 0.17 | 0.14, 0.14 | 0.16, 0.16 |
| engine vs engine_capped | 155 | 0.29, 0.29 | 0.16, 0.16 | 0.12, 0.12 | 0.16, 0.16 |
| engine vs king | 144 | 0.27, 0.29 | 0.16, 0.16 | 0.12, 0.14 | 0.16, 0.15 |
| engine_capped vs king | 144 | 0.27, 0.29 | 0.16, 0.16 | 0.12, 0.14 | 0.16, 0.15 |

MAE / MSE / RMSE / max |error| (eV) over every scored row, no filter:

| selector | n | casscf | tpbe | tpbe0 | nevpt2 |
|---|---|---|---|---|---|
| apc2 | 194 | 0.45 / +0.31 / 0.70 / 3.76 | 0.25 / +0.07 / 0.57 / 4.42 | 0.22 / +0.13 / 0.54 / 4.25 | 0.23 / +0.21 / 0.61 / 4.81 |
| engine | 172 | 0.57 / +0.35 / 1.31 / 9.44 | 0.36 / +0.22 / 1.05 / 10.34 | 0.32 / +0.25 / 1.07 / 10.11 | 0.37 / +0.29 / 1.07 / 9.84 |
| engine_capped | 173 | 0.60 / +0.38 / 1.37 / 9.44 | 0.36 / +0.22 / 1.05 / 10.34 | 0.33 / +0.26 / 1.08 / 10.11 | 0.38 / +0.30 / 1.07 / 9.84 |
| king | 196 | 0.49 / +0.34 / 0.81 / 5.55 | 0.28 / +0.09 / 0.71 / 6.12 | 0.25 / +0.15 / 0.68 / 5.98 | 0.27 / +0.24 / 0.75 / 6.48 |

#### doublet excitations: 51 excitations

| selector | good space | scored | not converged | wall cap | unrepresentable | too large | declined | failed | missing |
|---|---|---|---|---|---|---|---|---|---|
| apc2 | 37/51 (73%) | 51 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| engine | 20/51 (39%) | 28 | 0 | 0 | 21 | 0 | 2 | 0 | 0 |
| engine_capped | 20/51 (39%) | 28 | 0 | 0 | 21 | 0 | 2 | 0 | 0 |
| king | 37/51 (73%) | 51 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |

MAE / MSE / RMSE / max |error| (eV) over each selector's own good rows:

| selector | n | casscf | tpbe | tpbe0 | nevpt2 |
|---|---|---|---|---|---|
| apc2 | 37 | 0.23 / +0.12 / 0.32 / 1.07 | 0.20 / -0.13 / 0.28 / 0.90 | 0.14 / -0.07 / 0.25 / 0.94 | 0.10 / +0.05 / 0.21 / 1.17 |
| engine | 20 | 0.24 / +0.06 / 0.32 / 0.85 | 0.15 / -0.11 / 0.20 / 0.44 | 0.13 / -0.07 / 0.16 / 0.38 | 0.11 / -0.01 / 0.14 / 0.31 |
| engine_capped | 20 | 0.24 / +0.06 / 0.32 / 0.85 | 0.15 / -0.11 / 0.20 / 0.44 | 0.13 / -0.07 / 0.16 / 0.38 | 0.11 / -0.01 / 0.14 / 0.31 |
| king | 37 | 0.21 / +0.11 / 0.28 / 0.65 | 0.16 / -0.15 / 0.22 / 0.70 | 0.11 / -0.09 / 0.18 / 0.66 | 0.07 / +0.03 / 0.10 / 0.27 |

MAE (eV) over the rows good for BOTH selectors in each pair:

| pair | n | casscf (a, b) | tpbe (a, b) | tpbe0 (a, b) | nevpt2 (a, b) |
|---|---|---|---|---|---|
| apc2 vs engine | 20 | 0.24, 0.24 | 0.12, 0.15 | 0.06, 0.13 | 0.09, 0.11 |
| apc2 vs engine_capped | 20 | 0.24, 0.24 | 0.12, 0.15 | 0.06, 0.13 | 0.09, 0.11 |
| apc2 vs king | 36 | 0.21, 0.21 | 0.18, 0.16 | 0.12, 0.11 | 0.07, 0.07 |
| engine vs engine_capped | 20 | 0.24, 0.24 | 0.15, 0.15 | 0.13, 0.13 | 0.11, 0.11 |
| engine vs king | 20 | 0.24, 0.25 | 0.15, 0.11 | 0.13, 0.06 | 0.11, 0.09 |
| engine_capped vs king | 20 | 0.24, 0.25 | 0.15, 0.11 | 0.13, 0.06 | 0.11, 0.09 |

MAE / MSE / RMSE / max |error| (eV) over every scored row, no filter:

| selector | n | casscf | tpbe | tpbe0 | nevpt2 |
|---|---|---|---|---|---|
| apc2 | 51 | 1.17 / -0.05 / 2.26 / 9.13 | 1.06 / -0.32 / 2.18 / 8.76 | 1.03 / -0.25 / 2.19 / 8.86 | 1.03 / -0.14 / 2.24 / 8.95 |
| engine | 28 | 1.36 / +0.14 / 2.76 / 9.22 | 1.21 / -0.07 / 2.50 / 8.77 | 1.22 / -0.01 / 2.55 / 8.80 | 1.24 / +0.10 / 2.67 / 8.98 |
| engine_capped | 28 | 1.36 / +0.14 / 2.76 / 9.22 | 1.21 / -0.07 / 2.50 / 8.77 | 1.22 / -0.01 / 2.55 / 8.80 | 1.24 / +0.10 / 2.67 / 8.98 |
| king | 51 | 1.07 / -0.15 / 2.13 / 9.13 | 0.96 / -0.42 / 2.06 / 8.76 | 0.93 / -0.35 / 2.07 / 8.86 | 0.93 / -0.24 / 2.10 / 8.95 |

#### valence: 360 excitations

| selector | good space | scored | not converged | wall cap | unrepresentable | too large | declined | failed | missing |
|---|---|---|---|---|---|---|---|---|---|
| apc2 | 299/360 (83%) | 355 | 1 | 5 | 0 | 0 | 0 | 0 | 0 |
| engine | 280/360 (78%) | 340 | 1 | 0 | 16 | 4 | 0 | 0 | 0 |
| engine_capped | 280/360 (78%) | 344 | 1 | 0 | 16 | 0 | 0 | 0 | 0 |
| king | 303/360 (84%) | 358 | 0 | 0 | 0 | 0 | 0 | 0 | 2 |

MAE / MSE / RMSE / max |error| (eV) over each selector's own good rows:

| selector | n | casscf | tpbe | tpbe0 | nevpt2 |
|---|---|---|---|---|---|
| apc2 | 299 | 0.40 / +0.33 / 0.50 / 1.10 | 0.25 / -0.05 / 0.38 / 1.69 | 0.18 / +0.04 / 0.29 / 1.47 | 0.19 / +0.16 / 0.33 / 2.20 |
| engine | 280 | 0.34 / +0.20 / 0.45 / 1.09 | 0.21 / +0.02 / 0.32 / 1.58 | 0.16 / +0.06 / 0.25 / 1.38 | 0.20 / +0.15 / 0.30 / 1.45 |
| engine_capped | 280 | 0.34 / +0.20 / 0.45 / 1.09 | 0.21 / +0.02 / 0.32 / 1.58 | 0.16 / +0.06 / 0.25 / 1.38 | 0.20 / +0.15 / 0.30 / 1.45 |
| king | 303 | 0.42 / +0.33 / 0.51 / 1.10 | 0.24 / -0.06 / 0.37 / 1.64 | 0.18 / +0.04 / 0.28 / 1.40 | 0.19 / +0.16 / 0.32 / 1.84 |

MAE (eV) over the rows good for BOTH selectors in each pair:

| pair | n | casscf (a, b) | tpbe (a, b) | tpbe0 (a, b) | nevpt2 (a, b) |
|---|---|---|---|---|---|
| apc2 vs engine | 244 | 0.36, 0.31 | 0.22, 0.21 | 0.17, 0.15 | 0.19, 0.19 |
| apc2 vs engine_capped | 244 | 0.36, 0.31 | 0.22, 0.21 | 0.17, 0.15 | 0.19, 0.19 |
| apc2 vs king | 292 | 0.40, 0.40 | 0.25, 0.24 | 0.18, 0.18 | 0.19, 0.19 |
| engine vs engine_capped | 280 | 0.34, 0.34 | 0.21, 0.21 | 0.16, 0.16 | 0.20, 0.20 |
| engine vs king | 248 | 0.32, 0.38 | 0.20, 0.21 | 0.15, 0.16 | 0.19, 0.18 |
| engine_capped vs king | 248 | 0.32, 0.38 | 0.20, 0.21 | 0.15, 0.16 | 0.19, 0.18 |

MAE / MSE / RMSE / max |error| (eV) over every scored row, no filter:

| selector | n | casscf | tpbe | tpbe0 | nevpt2 |
|---|---|---|---|---|---|
| apc2 | 355 | 0.61 / +0.53 / 0.87 / 3.91 | 0.40 / +0.06 / 0.79 / 4.42 | 0.32 / +0.18 / 0.72 / 4.25 | 0.35 / +0.31 / 0.81 / 4.81 |
| engine | 340 | 0.74 / +0.62 / 1.41 / 10.08 | 0.45 / +0.11 / 0.92 / 7.21 | 0.38 / +0.24 / 0.94 / 7.81 | 0.42 / +0.32 / 0.98 / 8.28 |
| engine_capped | 344 | 0.79 / +0.67 / 1.51 / 10.08 | 0.46 / +0.12 / 0.93 / 7.21 | 0.40 / +0.26 / 0.97 / 7.81 | 0.44 / +0.33 / 1.00 / 8.28 |
| king | 358 | 0.63 / +0.55 / 0.94 / 5.55 | 0.38 / +0.04 / 0.78 / 6.12 | 0.31 / +0.17 / 0.72 / 5.98 | 0.34 / +0.30 / 0.81 / 6.48 |

#### Rydberg: 130 excitations

| selector | good space | scored | not converged | wall cap | unrepresentable | too large | declined | failed | missing |
|---|---|---|---|---|---|---|---|---|---|
| apc2 | 96/130 (74%) | 129 | 0 | 1 | 0 | 0 | 0 | 0 | 0 |
| engine | 21/130 (16%) | 74 | 0 | 0 | 55 | 0 | 1 | 0 | 0 |
| engine_capped | 21/130 (16%) | 74 | 0 | 0 | 55 | 0 | 1 | 0 | 0 |
| king | 95/130 (73%) | 130 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |

MAE / MSE / RMSE / max |error| (eV) over each selector's own good rows:

| selector | n | casscf | tpbe | tpbe0 | nevpt2 |
|---|---|---|---|---|---|
| apc2 | 96 | 0.45 / -0.28 / 0.52 / 1.06 | 0.25 / -0.14 / 0.34 / 1.56 | 0.26 / -0.17 / 0.33 / 1.11 | 0.19 / +0.16 / 0.28 / 1.08 |
| engine | 21 | 0.53 / -0.23 / 0.62 / 0.89 | 0.27 / -0.08 / 0.35 / 0.86 | 0.31 / -0.12 / 0.37 / 0.85 | 0.18 / +0.17 / 0.32 / 1.07 |
| engine_capped | 21 | 0.53 / -0.23 / 0.62 / 0.89 | 0.27 / -0.08 / 0.35 / 0.86 | 0.31 / -0.12 / 0.37 / 0.85 | 0.18 / +0.17 / 0.32 / 1.07 |
| king | 95 | 0.45 / -0.29 / 0.52 / 1.04 | 0.26 / -0.13 / 0.35 / 1.56 | 0.27 / -0.17 / 0.34 / 1.11 | 0.19 / +0.15 / 0.30 / 1.10 |

MAE (eV) over the rows good for BOTH selectors in each pair:

| pair | n | casscf (a, b) | tpbe (a, b) | tpbe0 (a, b) | nevpt2 (a, b) |
|---|---|---|---|---|---|
| apc2 vs engine | 20 | 0.33, 0.51 | 0.25, 0.25 | 0.21, 0.29 | 0.13, 0.16 |
| apc2 vs engine_capped | 20 | 0.33, 0.51 | 0.25, 0.25 | 0.21, 0.29 | 0.13, 0.16 |
| apc2 vs king | 95 | 0.45, 0.45 | 0.25, 0.26 | 0.26, 0.27 | 0.19, 0.19 |
| engine vs engine_capped | 21 | 0.53, 0.53 | 0.27, 0.27 | 0.31, 0.31 | 0.18, 0.18 |
| engine vs king | 20 | 0.51, 0.31 | 0.25, 0.27 | 0.29, 0.23 | 0.16, 0.15 |
| engine_capped vs king | 20 | 0.51, 0.31 | 0.25, 0.27 | 0.29, 0.23 | 0.16, 0.15 |

MAE / MSE / RMSE / max |error| (eV) over every scored row, no filter:

| selector | n | casscf | tpbe | tpbe0 | nevpt2 |
|---|---|---|---|---|---|
| apc2 | 129 | 0.97 / +0.40 / 1.40 / 4.85 | 0.58 / +0.27 / 0.98 / 4.91 | 0.65 / +0.30 / 1.05 / 4.90 | 0.68 / +0.64 / 1.20 / 5.12 |
| engine | 74 | 3.21 / +2.96 / 4.40 / 12.78 | 2.25 / +2.01 / 3.55 / 11.92 | 2.41 / +2.25 / 3.69 / 11.84 | 2.50 / +2.50 / 3.76 / 12.83 |
| engine_capped | 74 | 3.21 / +2.96 / 4.40 / 12.78 | 2.25 / +2.01 / 3.55 / 11.92 | 2.41 / +2.25 / 3.69 / 11.84 | 2.50 / +2.50 / 3.76 / 12.83 |
| king | 130 | 0.97 / +0.41 / 1.40 / 4.85 | 0.59 / +0.27 / 0.97 / 4.91 | 0.65 / +0.31 / 1.04 / 4.90 | 0.68 / +0.64 / 1.20 / 5.12 |

#### n-pi*: 132 excitations

| selector | good space | scored | not converged | wall cap | unrepresentable | too large | declined | failed | missing |
|---|---|---|---|---|---|---|---|---|---|
| apc2 | 104/132 (79%) | 132 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| engine | 107/132 (81%) | 125 | 0 | 0 | 3 | 4 | 0 | 0 | 0 |
| engine_capped | 107/132 (81%) | 129 | 0 | 0 | 3 | 0 | 0 | 0 | 0 |
| king | 107/132 (81%) | 130 | 0 | 0 | 0 | 0 | 0 | 0 | 2 |

MAE / MSE / RMSE / max |error| (eV) over each selector's own good rows:

| selector | n | casscf | tpbe | tpbe0 | nevpt2 |
|---|---|---|---|---|---|
| apc2 | 104 | 0.47 / +0.43 / 0.56 / 1.08 | 0.25 / -0.04 / 0.44 / 1.69 | 0.16 / +0.08 / 0.35 / 1.47 | 0.20 / +0.18 / 0.42 / 2.20 |
| engine | 107 | 0.37 / +0.30 / 0.47 / 1.01 | 0.13 / -0.04 / 0.22 / 1.58 | 0.11 / +0.05 / 0.19 / 1.38 | 0.15 / +0.08 / 0.23 / 1.37 |
| engine_capped | 107 | 0.37 / +0.30 / 0.47 / 1.01 | 0.13 / -0.04 / 0.22 / 1.58 | 0.11 / +0.05 / 0.19 / 1.38 | 0.15 / +0.08 / 0.23 / 1.37 |
| king | 107 | 0.51 / +0.45 / 0.60 / 1.08 | 0.23 / -0.07 / 0.40 / 1.64 | 0.16 / +0.06 / 0.31 / 1.40 | 0.19 / +0.17 / 0.39 / 1.84 |

MAE (eV) over the rows good for BOTH selectors in each pair:

| pair | n | casscf (a, b) | tpbe (a, b) | tpbe0 (a, b) | nevpt2 (a, b) |
|---|---|---|---|---|---|
| apc2 vs engine | 84 | 0.41, 0.33 | 0.25, 0.13 | 0.17, 0.12 | 0.21, 0.15 |
| apc2 vs engine_capped | 84 | 0.41, 0.33 | 0.25, 0.13 | 0.17, 0.12 | 0.21, 0.15 |
| apc2 vs king | 101 | 0.47, 0.49 | 0.25, 0.23 | 0.17, 0.15 | 0.20, 0.19 |
| engine vs engine_capped | 107 | 0.37, 0.37 | 0.13, 0.13 | 0.11, 0.11 | 0.15, 0.15 |
| engine vs king | 86 | 0.34, 0.46 | 0.13, 0.22 | 0.12, 0.16 | 0.16, 0.20 |
| engine_capped vs king | 86 | 0.34, 0.46 | 0.13, 0.22 | 0.12, 0.16 | 0.16, 0.20 |

MAE / MSE / RMSE / max |error| (eV) over every scored row, no filter:

| selector | n | casscf | tpbe | tpbe0 | nevpt2 |
|---|---|---|---|---|---|
| apc2 | 132 | 0.77 / +0.72 / 1.07 / 3.76 | 0.53 / +0.22 / 1.11 / 4.42 | 0.43 / +0.35 / 1.02 / 4.25 | 0.48 / +0.45 / 1.16 / 4.81 |
| engine | 125 | 0.73 / +0.67 / 1.33 / 6.04 | 0.26 / -0.00 / 0.50 / 2.41 | 0.23 / +0.17 / 0.61 / 3.32 | 0.29 / +0.13 / 0.56 / 2.87 |
| engine_capped | 129 | 0.87 / +0.81 / 1.60 / 6.04 | 0.30 / +0.04 / 0.58 / 2.80 | 0.30 / +0.23 / 0.74 / 3.53 | 0.33 / +0.17 / 0.65 / 2.93 |
| king | 130 | 0.78 / +0.73 / 1.11 / 5.55 | 0.47 / +0.14 / 1.06 / 6.12 | 0.37 / +0.28 / 0.99 / 5.98 | 0.42 / +0.39 / 1.10 / 6.48 |

#### pi-pi*: 194 excitations

| selector | good space | scored | not converged | wall cap | unrepresentable | too large | declined | failed | missing |
|---|---|---|---|---|---|---|---|---|---|
| apc2 | 168/194 (87%) | 189 | 1 | 5 | 0 | 0 | 0 | 0 | 0 |
| engine | 162/194 (84%) | 194 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| engine_capped | 162/194 (84%) | 194 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| king | 171/194 (88%) | 194 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |

MAE / MSE / RMSE / max |error| (eV) over each selector's own good rows:

| selector | n | casscf | tpbe | tpbe0 | nevpt2 |
|---|---|---|---|---|---|
| apc2 | 168 | 0.37 / +0.30 / 0.48 / 1.10 | 0.23 / -0.02 / 0.33 / 1.11 | 0.19 / +0.06 / 0.25 / 0.80 | 0.20 / +0.17 / 0.28 / 1.23 |
| engine | 162 | 0.32 / +0.13 / 0.44 / 1.09 | 0.26 / +0.07 / 0.36 / 1.26 | 0.19 / +0.09 / 0.29 / 1.19 | 0.24 / +0.20 / 0.34 / 1.45 |
| engine_capped | 162 | 0.32 / +0.13 / 0.44 / 1.09 | 0.26 / +0.07 / 0.36 / 1.26 | 0.19 / +0.09 / 0.29 / 1.19 | 0.24 / +0.20 / 0.34 / 1.45 |
| king | 171 | 0.38 / +0.30 / 0.48 / 1.10 | 0.23 / -0.02 / 0.33 / 1.11 | 0.18 / +0.06 / 0.26 / 0.90 | 0.20 / +0.17 / 0.29 / 1.23 |

MAE (eV) over the rows good for BOTH selectors in each pair:

| pair | n | casscf (a, b) | tpbe (a, b) | tpbe0 (a, b) | nevpt2 (a, b) |
|---|---|---|---|---|---|
| apc2 vs engine | 150 | 0.34, 0.30 | 0.20, 0.24 | 0.17, 0.17 | 0.18, 0.21 |
| apc2 vs engine_capped | 150 | 0.34, 0.30 | 0.20, 0.24 | 0.17, 0.17 | 0.18, 0.21 |
| apc2 vs king | 166 | 0.37, 0.37 | 0.23, 0.23 | 0.18, 0.18 | 0.19, 0.20 |
| engine vs engine_capped | 162 | 0.32, 0.32 | 0.26, 0.26 | 0.19, 0.19 | 0.24, 0.24 |
| engine vs king | 153 | 0.30, 0.35 | 0.24, 0.20 | 0.16, 0.16 | 0.21, 0.17 |
| engine_capped vs king | 153 | 0.30, 0.35 | 0.24, 0.20 | 0.16, 0.16 | 0.21, 0.17 |

MAE / MSE / RMSE / max |error| (eV) over every scored row, no filter:

| selector | n | casscf | tpbe | tpbe0 | nevpt2 |
|---|---|---|---|---|---|
| apc2 | 189 | 0.51 / +0.45 / 0.73 / 3.91 | 0.31 / -0.00 / 0.51 / 3.34 | 0.25 / +0.11 / 0.45 / 3.21 | 0.28 / +0.25 / 0.51 / 3.57 |
| engine | 194 | 0.64 / +0.46 / 1.24 / 10.08 | 0.46 / +0.09 / 0.86 / 6.45 | 0.37 / +0.19 / 0.84 / 7.36 | 0.41 / +0.33 / 0.93 / 8.28 |
| engine_capped | 194 | 0.64 / +0.46 / 1.24 / 10.08 | 0.46 / +0.09 / 0.86 / 6.45 | 0.37 / +0.19 / 0.84 / 7.36 | 0.41 / +0.33 / 0.93 / 8.28 |
| king | 194 | 0.51 / +0.44 / 0.72 / 3.91 | 0.31 / -0.00 / 0.51 / 3.34 | 0.25 / +0.11 / 0.44 / 3.21 | 0.27 / +0.25 / 0.51 / 3.57 |

#### double excitations: 23 excitations

| selector | good space | scored | not converged | wall cap | unrepresentable | too large | declined | failed | missing |
|---|---|---|---|---|---|---|---|---|---|
| apc2 | 18/23 (78%) | 23 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| engine | 7/23 (30%) | 20 | 0 | 0 | 2 | 0 | 1 | 0 | 0 |
| engine_capped | 7/23 (30%) | 20 | 0 | 0 | 2 | 0 | 1 | 0 | 0 |
| king | 16/23 (70%) | 23 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |

MAE / MSE / RMSE / max |error| (eV) over each selector's own good rows:

| selector | n | casscf | tpbe | tpbe0 | nevpt2 |
|---|---|---|---|---|---|
| apc2 | 18 | 0.33 / +0.14 / 0.41 / 0.80 | 0.23 / -0.19 / 0.34 / 0.97 | 0.20 / -0.11 / 0.28 / 0.83 | 0.10 / +0.05 / 0.15 / 0.41 |
| engine | 7 | 0.25 / +0.17 / 0.37 / 0.91 | 0.22 / -0.19 / 0.35 / 0.88 | 0.14 / -0.10 / 0.20 / 0.43 | 0.05 / +0.00 / 0.08 / 0.18 |
| engine_capped | 7 | 0.25 / +0.17 / 0.37 / 0.91 | 0.22 / -0.19 / 0.35 / 0.88 | 0.14 / -0.10 / 0.20 / 0.43 | 0.05 / +0.00 / 0.08 / 0.18 |
| king | 16 | 0.27 / +0.06 / 0.34 / 0.72 | 0.22 / -0.17 / 0.33 / 0.97 | 0.20 / -0.11 / 0.29 / 0.83 | 0.13 / +0.04 / 0.18 / 0.41 |

MAE (eV) over the rows good for BOTH selectors in each pair:

| pair | n | casscf (a, b) | tpbe (a, b) | tpbe0 (a, b) | nevpt2 (a, b) |
|---|---|---|---|---|---|
| apc2 vs engine | 7 | 0.32, 0.25 | 0.15, 0.22 | 0.11, 0.14 | 0.09, 0.05 |
| apc2 vs engine_capped | 7 | 0.32, 0.25 | 0.15, 0.22 | 0.11, 0.14 | 0.09, 0.05 |
| apc2 vs king | 16 | 0.31, 0.27 | 0.22, 0.22 | 0.21, 0.20 | 0.11, 0.11 |
| engine vs engine_capped | 7 | 0.25, 0.25 | 0.22, 0.22 | 0.14, 0.14 | 0.05, 0.05 |
| engine vs king | 6 | 0.26, 0.25 | 0.23, 0.12 | 0.13, 0.12 | 0.05, 0.10 |
| engine_capped vs king | 6 | 0.26, 0.25 | 0.23, 0.12 | 0.13, 0.12 | 0.05, 0.10 |

MAE / MSE / RMSE / max |error| (eV) over every scored row, no filter:

| selector | n | casscf | tpbe | tpbe0 | nevpt2 |
|---|---|---|---|---|---|
| apc2 | 23 | 0.59 / +0.31 / 0.82 / 1.79 | 0.33 / -0.24 / 0.52 / 1.88 | 0.29 / -0.10 / 0.48 / 1.79 | 0.19 / +0.02 / 0.34 / 1.20 |
| engine | 20 | 3.03 / +3.00 / 4.58 / 11.59 | 2.83 / +2.52 / 4.44 / 11.92 | 2.81 / +2.64 / 4.44 / 11.84 | 2.87 / +2.84 / 4.62 / 12.83 |
| engine_capped | 20 | 3.03 / +3.00 / 4.58 / 11.59 | 2.83 / +2.52 / 4.44 / 11.92 | 2.81 / +2.64 / 4.44 / 11.84 | 2.87 / +2.84 / 4.62 / 12.83 |
| king | 23 | 0.87 / +0.59 / 1.46 / 5.22 | 0.45 / -0.06 / 0.86 / 3.29 | 0.48 / +0.11 / 0.94 / 3.77 | 0.44 / +0.26 / 1.00 / 4.29 |

#### M_max > 0.14 (M from King's Aug(12,12) wave functions): 264 excitations

| selector | good space | scored | not converged | wall cap | unrepresentable | too large | declined | failed | missing |
|---|---|---|---|---|---|---|---|---|---|
| apc2 | 195/264 (74%) | 259 | 1 | 5 | 0 | 0 | 0 | 0 | 0 |
| engine | 166/264 (63%) | 244 | 0 | 0 | 13 | 4 | 3 | 0 | 0 |
| engine_capped | 166/264 (63%) | 248 | 0 | 0 | 13 | 0 | 3 | 0 | 0 |
| king | 195/264 (74%) | 264 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |

MAE / MSE / RMSE / max |error| (eV) over each selector's own good rows:

| selector | n | casscf | tpbe | tpbe0 | nevpt2 |
|---|---|---|---|---|---|
| apc2 | 195 | 0.44 / +0.34 / 0.53 / 1.10 | 0.24 / -0.07 / 0.35 / 1.66 | 0.19 / +0.03 / 0.28 / 1.47 | 0.19 / +0.16 / 0.31 / 2.20 |
| engine | 166 | 0.38 / +0.24 / 0.49 / 1.08 | 0.25 / +0.05 / 0.36 / 1.58 | 0.20 / +0.10 / 0.32 / 1.38 | 0.25 / +0.20 / 0.37 / 1.45 |
| engine_capped | 166 | 0.38 / +0.24 / 0.49 / 1.08 | 0.25 / +0.05 / 0.36 / 1.58 | 0.20 / +0.10 / 0.32 / 1.38 | 0.25 / +0.20 / 0.37 / 1.45 |
| king | 195 | 0.45 / +0.35 / 0.53 / 1.10 | 0.24 / -0.08 / 0.34 / 1.64 | 0.18 / +0.03 / 0.26 / 1.00 | 0.19 / +0.15 / 0.27 / 1.11 |

MAE (eV) over the rows good for BOTH selectors in each pair:

| pair | n | casscf (a, b) | tpbe (a, b) | tpbe0 (a, b) | nevpt2 (a, b) |
|---|---|---|---|---|---|
| apc2 vs engine | 148 | 0.41, 0.36 | 0.22, 0.23 | 0.17, 0.19 | 0.19, 0.22 |
| apc2 vs engine_capped | 148 | 0.41, 0.36 | 0.22, 0.23 | 0.17, 0.19 | 0.19, 0.22 |
| apc2 vs king | 190 | 0.44, 0.44 | 0.24, 0.24 | 0.18, 0.18 | 0.19, 0.19 |
| engine vs engine_capped | 166 | 0.38, 0.38 | 0.25, 0.25 | 0.20, 0.20 | 0.25, 0.25 |
| engine vs king | 150 | 0.35, 0.41 | 0.22, 0.21 | 0.18, 0.17 | 0.22, 0.18 |
| engine_capped vs king | 150 | 0.35, 0.41 | 0.22, 0.21 | 0.18, 0.17 | 0.22, 0.18 |

MAE / MSE / RMSE / max |error| (eV) over every scored row, no filter:

| selector | n | casscf | tpbe | tpbe0 | nevpt2 |
|---|---|---|---|---|---|
| apc2 | 259 | 0.83 / +0.67 / 1.20 / 5.00 | 0.51 / +0.11 / 0.93 / 4.42 | 0.46 / +0.25 / 0.93 / 4.46 | 0.52 / +0.42 / 1.05 / 5.12 |
| engine | 244 | 1.29 / +1.18 / 2.31 / 11.59 | 0.82 / +0.51 / 1.71 / 11.92 | 0.81 / +0.68 / 1.78 / 11.84 | 0.88 / +0.79 / 1.86 / 12.83 |
| engine_capped | 248 | 1.36 / +1.25 / 2.38 / 11.59 | 0.83 / +0.52 / 1.71 / 11.92 | 0.83 / +0.70 / 1.79 / 11.84 | 0.90 / +0.80 / 1.86 / 12.83 |
| king | 264 | 0.85 / +0.70 / 1.25 / 5.55 | 0.51 / +0.11 / 0.94 / 6.12 | 0.47 / +0.25 / 0.94 / 5.98 | 0.52 / +0.42 / 1.06 / 6.48 |

#### APC-2 control against King's own Aug(12,12) rows

534 excitations scored by both; on 447 the control chose King's exact space. Over those, ours minus King's (eV):

| method | n | mean | mean abs | within 0.1 eV | max abs |
|---|---|---|---|---|---|
| casscf | 447 | -0.025 | 0.062 | 394 | 4.48 |
| tpbe | 447 | -0.019 | 0.056 | 411 | 4.35 |
| tpbe0 | 447 | -0.020 | 0.051 | 418 | 4.07 |
| nevpt2 | 447 | -0.029 | 0.055 | 423 | 4.38 |

## Every excitation

Errors are computed minus TBE, in eV. `space` is (electrons, orbitals). A dash means the row produced no number; the status column says why. NEVPT2 is not run above 24 active orbitals.

| excitation | spin | V/R | TBE | apc2 space | apc2 CASSCF | apc2 tPBE0 | apc2 NEVPT2 | apc2 status | engine space | engine CASSCF | engine tPBE0 | engine NEVPT2 | engine status | engine_capped space | engine_capped CASSCF | engine_capped tPBE0 | engine_capped NEVPT2 | engine_capped status | King CASSCF | flags |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| acetaldehyde-x1 | 1 | V | 4.31 | (12,12) | +0.39 | +0.12 | +0.12 | ok | (6,4) | +0.01 | +0.12 | +0.22 | ok | (6,4) | +0.01 | +0.12 | +0.22 | ok (alias) | +0.93 | - |
| acetaldehyde-x2 | 3 | V | 3.97 | (12,12) | +0.39 | +0.06 | +0.09 | ok | (6,4) | -0.13 | -0.05 | +0.09 | ok | (6,4) | -0.13 | -0.05 | +0.09 | ok (alias) | +0.93 | - |
| acetone-x1 | 1 | V | 4.47 | (10,12) | -0.25 | +0.00 | +0.13 | ok | (6,4) | +0.01 | +0.14 | +0.13 | ok | (6,4) | +0.01 | +0.14 | +0.13 | ok (alias) | -0.31 | - |
| acetone-x2 | 1 | R | 6.46 | (10,12) | +2.47 | +2.52 | +3.09 | ok, not good | (6,4) | +3.04 | +2.71 | +2.93 | ok, not good | (6,4) | +3.04 | +2.71 | +2.93 | ok (alias), not good | +2.47 | - |
| acetone-x3 | 1 | R | 7.47 | (10,12) | -0.44 | -0.24 | +0.06 | ok | (6,4) | +8.43 | +6.71 | +5.12 | ok, not good | (6,4) | +8.43 | +6.71 | +5.12 | ok (alias), not good | -0.44 | - |
| acetone-x4 | 1 | R | 7.51 | (10,12) | +2.14 | +1.87 | +2.60 | ok, not good | (6,4) | +2.95 | +1.20 | +1.69 | ok, not good | (6,4) | +2.95 | +1.20 | +1.69 | ok (alias), not good | +2.14 | - |
| acetone-x5 | 1 | R | 7.62 | (10,12) | +1.97 | +2.15 | +3.08 | ok, not good | (6,4) | +12.78 | +10.59 | +8.73 | ok, not good | (6,4) | +12.78 | +10.59 | +8.73 | ok (alias), not good | +2.00 | - |
| acetone-x6 | 3 | V | 4.13 | (10,12) | -0.28 | -0.06 | +0.11 | ok | (6,4) | +0.04 | +0.08 | +0.09 | ok | (6,4) | +0.04 | +0.08 | +0.09 | ok (alias) | -0.33 | - |
| acetone-x7 | 3 | V | 6.25 | (10,12) | -0.43 | -0.02 | +0.13 | ok | (2,2) | -0.55 | -0.01 | +0.26 | ok | (2,2) | -0.55 | -0.01 | +0.26 | ok (alias) | -0.43 | - |
| acetylene-x1 | 1 | V | 7.10 | (10,12) | +0.51 | -0.06 | +0.07 | ok | (4,4) | +0.52 | +0.06 | +0.16 | ok | (4,4) | +0.52 | +0.06 | +0.16 | ok (alias) | +0.41 | - |
| acetylene-x2 | 1 | V | 7.44 | (10,12) | +0.35 | -0.10 | +0.08 | ok | (4,4) | -0.10 | -0.47 | -0.24 | ok | (4,4) | -0.10 | -0.47 | -0.24 | ok (alias) | +0.28 | - |
| acetylene-x3 | 3 | V | 5.53 | (10,12) | -0.04 | +0.03 | +0.02 | ok | (4,4) | +0.21 | +0.14 | +0.09 | ok | (4,4) | +0.21 | +0.14 | +0.09 | ok (alias) | -0.04 | - |
| acetylene-x4 | 3 | V | 6.40 | (10,12) | +0.29 | -0.04 | +0.04 | ok | (4,4) | +0.31 | +0.05 | +0.13 | ok | (4,4) | +0.31 | +0.05 | +0.13 | ok (alias) | +0.29 | - |
| acetylene-x5 | 3 | V | 7.08 | (10,12) | +0.21 | -0.11 | +0.09 | ok | (4,4) | +0.41 | -0.01 | +0.23 | ok | (4,4) | +0.41 | -0.01 | +0.23 | ok (alias) | +0.22 | - |
| acrolein-x1 | 1 | V | 3.78 | (10,12) | +0.42 | +0.02 | +0.04 | ok | (8,6) | -0.08 | -0.07 | +0.03 | ok | (8,6) | -0.08 | -0.07 | +0.03 | ok (alias) | +3.51 | - |
| acrolein-x2 | 1 | V | 6.69 | (10,12) | +1.24 | +0.68 | +0.99 | ok, not good | (4,4) | +1.06 | +1.19 | +1.45 | ok | (4,4) | +1.06 | +1.19 | +1.45 | ok (alias) | +1.12 | - |
| acrolein-x3 | 1 | V | 6.72 | (10,12) | +0.81 | +1.14 | +1.28 | ok | (8,6) | +0.03 | +0.11 | +0.37 | ok | (8,6) | +0.03 | +0.11 | +0.37 | ok (alias) | +0.73 | - |
| acrolein-x4 | 1 | R | 7.08 | (10,12) | +1.06 | +0.14 | +0.46 | ok | (8,6) | +0.82 | +0.85 | +1.07 | ok | (8,6) | +0.82 | +0.85 | +1.07 | ok (alias) | +0.58 | - |
| acrolein-x5 | 1 | V | 7.87 | (10,12) | +0.21 | -0.23 | -0.05 | ok | (8,6) | +2.62 | +0.61 | +1.00 | ok, not good | (8,6) | +2.62 | +0.61 | +1.00 | ok (alias), not good | +2.79 | - |
| acrolein-x6 | 3 | V | 3.51 | (10,12) | +0.47 | -0.00 | +0.02 | ok | (8,6) | -0.06 | -0.11 | -0.01 | ok | (8,6) | -0.06 | -0.11 | -0.01 | ok (alias) | +3.68 | - |
| acrolein-x7 | 3 | V | 3.94 | (10,12) | +0.01 | +0.11 | +0.16 | ok | (4,4) | -0.08 | +0.08 | +0.15 | ok | (4,4) | -0.08 | +0.08 | +0.15 | ok (alias) | +0.15 | - |
| acrolein-x8 | 3 | V | 6.18 | (10,12) | +0.11 | +0.13 | +0.07 | ok | (4,4) | -0.30 | +0.09 | +0.23 | ok | (4,4) | -0.30 | +0.09 | +0.23 | ok (alias) | -0.21 | - |
| acrolein-x9 | 3 | V | 6.54 | (10,12) | +0.87 | +1.20 | +1.35 | ok | (8,6) | +0.10 | +0.15 | +0.38 | ok | (8,6) | +0.10 | +0.15 | +0.38 | ok (alias) | +0.89 | - |
| ammonia-x1 | 1 | R | 6.59 | (8,13) | -0.32 | -0.23 | -0.02 | ok | (8,7) | -0.88 | -0.34 | -0.03 | ok | (8,7) | -0.88 | -0.34 | -0.03 | ok (alias) | -0.32 | - |
| ammonia-x2 | 1 | R | 8.16 | (8,13) | -0.61 | -0.49 | -0.09 | ok | (8,7) | -1.34 | -0.82 | -0.12 | ok, not good | (8,7) | -1.34 | -0.82 | -0.12 | ok (alias), not good | -0.60 | - |
| ammonia-x3 | 1 | R | 9.33 | (8,13) | +0.36 | +0.22 | +0.76 | ok | (8,7) | +1.94 | +2.12 | +2.74 | ok, not good | (8,7) | +1.94 | +2.12 | +2.74 | ok (alias), not good | +0.43 | - |
| ammonia-x4 | 1 | R | 9.96 | (8,13) | -1.63 | -1.60 | -0.85 | ok, not good | (8,7) | +1.16 | +1.39 | +2.06 | ok, not good | (8,7) | +1.16 | +1.39 | +2.06 | ok (alias), not good | -1.28 | - |
| ammonia-x5 | 3 | R | 6.31 | (8,13) | -0.34 | -0.19 | -0.01 | ok | (8,7) | -0.77 | -0.29 | -0.02 | ok | (8,7) | -0.77 | -0.29 | -0.02 | ok (alias) | -0.32 | - |
| aza-naphthalene-x1 | 1 | V | 3.14 | (18,13) | +0.80 | -0.11 | -0.01 | ok | (14,12) | +5.66 | +2.99 | +2.54 | ok, not good | (14,12) | +5.66 | +2.99 | +2.54 | ok (alias), not good | +0.80 | - |
| aza-naphthalene-x2 | 1 | V | 4.28 | (18,13) | +0.87 | +0.36 | +0.25 | ok | (10,10) | +0.10 | +0.16 | +0.28 | ok | (10,10) | +0.10 | +0.16 | +0.28 | ok (alias) | +0.87 | - |
| aza-naphthalene-x3 | 1 | V | 4.34 | (18,13) | +0.70 | -0.02 | +0.12 | ok | (14,12) | +5.19 | +2.46 | +2.07 | ok, not good | (14,12) | +5.19 | +2.46 | +2.07 | ok (alias), not good | +0.71 | - |
| aza-naphthalene-x4 | 1 | V | 4.55 | (18,13) | +0.81 | +0.20 | +0.42 | ok | (14,12) | +2.89 | +0.17 | -0.52 | ok, not good | (14,12) | +2.89 | +0.17 | -0.52 | ok (alias), not good | +0.81 | - |
| aza-naphthalene-x5 | 1 | V | 4.89 | (18,13) | +0.54 | -0.16 | +0.04 | ok | (18,14) | - | - | - | too_large | (14,12) | +5.49 | +2.38 | +1.81 | ok, not good | +0.54 | - |
| aza-naphthalene-x6 | 1 | V | 5.24 | (18,13) | +1.50 | -0.30 | -0.13 | ok, not good | (18,14) | - | - | - | too_large | (14,12) | +5.74 | +3.53 | +2.93 | ok, not good | +1.50 | - |
| aza-naphthalene-x7 | 1 | V | 5.34 | (18,13) | +0.36 | -0.06 | +0.19 | ok | (14,12) | +2.65 | +0.01 | -0.67 | ok, not good | (14,12) | +2.65 | +0.01 | -0.67 | ok (alias), not good | +0.36 | - |
| aza-naphthalene-x8 | 1 | V | 5.68 | - | - | - | - | wall_cap | (10,10) | +1.59 | -0.71 | -0.63 | ok, not good | (10,10) | +1.59 | -0.71 | -0.63 | ok (alias), not good | +0.99 | - |
| aza-naphthalene-x9 | 1 | V | 5.80 | - | - | - | - | wall_cap | (10,10) | +0.12 | +0.35 | +0.49 | ok | (10,10) | +0.12 | +0.35 | +0.49 | ok (alias) | +0.89 | - |
| aza-naphthalene-x10 | 1 | V | 5.92 | (18,13) | +1.46 | +0.11 | +0.18 | ok, not good | (18,14) | - | - | - | too_large | (14,12) | +3.92 | +0.69 | +0.08 | ok, not good | +1.46 | - |
| aza-naphthalene-x11 | 1 | R | 6.50 | - | - | - | - | wall_cap | (14,12) | +0.76 | +0.61 | +0.69 | ok | (14,12) | +0.76 | +0.61 | +0.69 | ok (alias) | +1.49 | - |
| aza-naphthalene-x12 | 3 | V | 2.82 | (18,13) | +0.84 | -0.04 | +0.01 | ok | (14,12) | +6.04 | +3.32 | +2.87 | ok, not good | (14,12) | +6.04 | +3.32 | +2.87 | ok (alias), not good | +0.84 | - |
| aza-naphthalene-x13 | 3 | V | 3.67 | - | - | - | - | wall_cap | (10,10) | +0.41 | +0.09 | +0.04 | ok | (10,10) | +0.41 | +0.09 | +0.04 | ok (alias) | +0.32 | - |
| aza-naphthalene-x14 | 3 | V | 3.75 | (18,13) | +0.10 | +0.12 | +0.23 | ok | (10,10) | -0.28 | +0.18 | +0.27 | ok | (10,10) | -0.28 | +0.18 | +0.27 | ok (alias) | +0.10 | - |
| aza-naphthalene-x15 | 3 | V | 3.77 | (18,13) | +0.76 | +0.07 | +0.11 | ok | (14,12) | +5.76 | +3.00 | +2.59 | ok, not good | (14,12) | +5.76 | +3.00 | +2.59 | ok (alias), not good | +0.76 | - |
| aza-naphthalene-x16 | 3 | V | 4.34 | (18,13) | +0.71 | +0.11 | +0.25 | ok | (14,12) | +2.39 | -0.05 | -0.69 | ok, not good | (14,12) | +2.39 | -0.05 | -0.69 | ok (alias), not good | +0.71 | - |
| aza-naphthalene-x17 | 3 | V | 4.61 | (18,13) | +0.53 | -0.18 | -0.04 | ok | (18,14) | - | - | - | too_large | (14,12) | +5.58 | +2.41 | +1.86 | ok, not good | +0.53 | - |
| aza-naphthalene-x18 | 3 | V | 4.75 | - | - | - | - | wall_cap | (10,10) | +0.10 | +0.04 | +0.15 | ok | (10,10) | +0.10 | +0.04 | +0.15 | ok (alias) | +0.66 | - |
| aza-naphthalene-x19 | 3 | V | 4.87 | (18,13) | +0.55 | +0.09 | +0.27 | ok | (14,12) | +2.32 | -0.02 | -0.64 | ok, not good | (14,12) | +2.32 | -0.02 | -0.64 | ok (alias), not good | +0.55 | - |
| beryllium-x1 | 1 | R | 7.15 | (4,40) | -0.38 | -0.59 | - | ok | - | - | - | - | declined | - | - | - | - | declined | -0.38 | - |
| benzene-x1 | 1 | V | 5.06 | (14,12) | +0.85 | +0.33 | +0.12 | ok | (6,6) | -0.08 | +0.18 | +0.29 | ok | (6,6) | -0.08 | +0.18 | +0.29 | ok (alias) | +0.85 | - |
| benzene-x2 | 1 | V | 6.45 | (14,12) | +0.69 | -0.34 | +0.25 | ok | (6,6) | +1.24 | -0.70 | -0.32 | ok, not good | (6,6) | +1.24 | -0.70 | -0.32 | ok (alias), not good | +0.69 | - |
| benzene-x3 | 1 | R | 6.52 | (14,12) | -0.70 | -0.13 | +0.25 | ok | (6,6) | - | - | - | unrepresentable | (6,6) | - | - | - | unrepresentable (alias) | -0.70 | - |
| benzene-x4 | 1 | R | 7.08 | (14,12) | +2.38 | +0.98 | +1.18 | ok, not good | (6,6) | - | - | - | unrepresentable | (6,6) | - | - | - | unrepresentable (alias) | +2.38 | - |
| benzene-x5 | 1 | R | 7.15 | (14,12) | +2.44 | +1.00 | +1.11 | ok, not good | (6,6) | - | - | - | unrepresentable | (6,6) | - | - | - | unrepresentable (alias) | +2.43 | - |
| benzene-x6 | 1 | V | 8.28 | (14,12) | +0.91 | +0.25 | +0.41 | ok | (6,6) | -0.19 | +0.08 | +0.27 | ok | (6,6) | -0.19 | +0.08 | +0.27 | ok (alias) | +0.91 | - |
| benzene-x7 | 1 | V | 10.55 | (14,12) | -0.43 | -0.11 | +0.41 | ok | (6,6) | +0.91 | -0.43 | -0.18 | ok | (6,6) | +0.91 | -0.43 | -0.18 | ok (alias) | -0.43 | - |
| benzene-x8 | 3 | V | 4.16 | (14,12) | +0.49 | +0.35 | +0.26 | ok | (6,6) | -0.28 | +0.22 | +0.28 | ok | (6,6) | -0.28 | +0.22 | +0.28 | ok (alias) | +0.49 | - |
| benzene-x9 | 3 | V | 4.85 | (14,12) | +0.45 | +0.06 | +0.19 | ok | (6,6) | +0.13 | +0.09 | +0.17 | ok | (6,6) | +0.13 | +0.09 | +0.17 | ok (alias) | +0.45 | - |
| benzene-x10 | 3 | V | 5.81 | (14,12) | +0.62 | -0.47 | +0.01 | ok | (6,6) | -0.92 | -0.92 | -0.81 | ok | (6,6) | -0.92 | -0.92 | -0.81 | ok (alias) | +0.62 | - |
| benzoquinone-x1 | 1 | V | 2.82 | (14,12) | +0.54 | +0.08 | +0.16 | ok | (12,10) | +0.70 | +0.18 | +0.08 | ok | (12,10) | +0.70 | +0.18 | +0.08 | ok (alias) | +0.54 | - |
| benzoquinone-x2 | 1 | V | 2.96 | (14,12) | +0.46 | +0.06 | +0.14 | ok | (12,10) | +0.56 | +0.11 | +0.02 | ok | (12,10) | +0.56 | +0.11 | +0.02 | ok (alias) | +0.46 | - |
| benzoquinone-x3 | 1 | V | 4.57 | (14,12) | +0.08 | -0.07 | +0.21 | ok | (8,8) | +1.96 | +1.76 | +1.85 | ok, not good | (8,8) | +1.96 | +1.76 | +1.85 | ok (alias), not good | +0.08 | - |
| benzoquinone-x4 | 1 | V | 4.58 | (14,12) | +0.51 | -0.32 | +0.06 | ok | (8,8) | +1.33 | -0.19 | -0.18 | ok, not good | (8,8) | +1.33 | -0.19 | -0.18 | ok (alias), not good | +0.51 | - |
| benzoquinone-x5 | 1 | V | 5.62 | (14,12) | +1.40 | -0.73 | +0.01 | ok, not good | (8,8) | +2.02 | -0.76 | -0.35 | ok, not good | (8,8) | +2.02 | -0.76 | -0.35 | ok (alias), not good | +1.40 | - |
| benzoquinone-x6 | 1 | V | 5.79 | (14,12) | +0.97 | -0.06 | +0.08 | ok | (12,10) | +0.75 | +0.26 | +0.22 | ok | (12,10) | +0.75 | +0.26 | +0.22 | ok (alias) | +0.97 | - |
| benzoquinone-x7 | 1 | V | 5.95 | (14,12) | +0.85 | -0.08 | -0.01 | ok | (12,10) | +0.59 | +0.08 | +0.04 | ok | (12,10) | +0.59 | +0.08 | +0.04 | ok (alias) | +0.85 | - |
| benzoquinone-x8 | 1 | V | 6.35 | (14,12) | +0.31 | +0.00 | +0.25 | ok | (16,12) | +0.38 | +0.10 | +0.20 | ok | (16,12) | +0.38 | +0.10 | +0.20 | ok (alias) | +0.31 | - |
| benzoquinone-x9 | 1 | V | 6.38 | (14,12) | +0.37 | +0.13 | +0.38 | ok | (12,10) | +0.32 | +0.09 | +0.18 | ok | (12,10) | +0.32 | +0.09 | +0.18 | ok (alias) | +0.37 | - |
| benzoquinone-x10 | 1 | V | 7.22 | (14,12) | +0.93 | -1.00 | -0.44 | ok | (16,12) | -0.78 | -1.38 | -1.37 | ok | (16,12) | -0.78 | -1.38 | -1.37 | ok (alias) | +0.93 | - |
| benzoquinone-x11 | 3 | V | 2.58 | (14,12) | +0.58 | +0.07 | +0.15 | ok | (12,10) | +0.76 | +0.14 | +0.05 | ok | (12,10) | +0.76 | +0.14 | +0.05 | ok (alias) | +0.58 | - |
| benzoquinone-x12 | 3 | V | 2.72 | (14,12) | +0.53 | +0.07 | +0.15 | ok | (12,10) | +0.63 | +0.10 | +0.03 | ok | (12,10) | +0.63 | +0.10 | +0.03 | ok (alias) | +0.53 | - |
| benzoquinone-x13 | 3 | V | 3.12 | (14,12) | +0.20 | +0.04 | +0.16 | ok | (8,8) | +0.16 | +0.10 | +0.11 | ok | (8,8) | +0.16 | +0.10 | +0.11 | ok (alias) | +0.20 | - |
| benzoquinone-x14 | 3 | V | 3.46 | (14,12) | +0.17 | -0.03 | +0.09 | ok | (8,8) | +0.32 | +0.19 | +0.19 | ok | (8,8) | +0.32 | +0.19 | +0.19 | ok (alias) | +0.17 | - |
| butadiene-x1 | 1 | V | 6.22 | (18,13) | +0.49 | -0.05 | +0.48 | ok | (4,4) | +1.42 | -1.16 | -0.42 | ok, not good | (4,4) | +1.42 | -1.16 | -0.42 | ok (alias), not good | +0.49 | - |
| butadiene-x2 | 1 | R | 6.33 | (18,13) | +3.34 | +2.28 | +2.57 | ok, not good | (4,4) | - | - | - | unrepresentable | (4,4) | - | - | - | unrepresentable (alias) | +3.34 | - |
| butadiene-x3 | 1 | V | 6.50 | (18,13) | +0.15 | +0.29 | +0.40 | ok | (4,4) | +0.14 | +0.28 | +0.38 | ok | (4,4) | +0.14 | +0.28 | +0.38 | ok (alias) | +0.15 | - |
| butadiene-x4 | 1 | R | 6.64 | (18,13) | +1.79 | +0.89 | +1.17 | ok, not good | (4,4) | - | - | - | unrepresentable | (4,4) | - | - | - | unrepresentable (alias) | +1.79 | - |
| butadiene-x5 | 1 | R | 6.80 | (18,13) | +2.89 | +1.86 | +2.02 | ok, not good | (4,4) | - | - | - | unrepresentable | (4,4) | - | - | - | unrepresentable (alias) | +2.89 | - |
| butadiene-x6 | 1 | R | 7.68 | (18,13) | +0.23 | -1.11 | -0.26 | ok | (4,4) | +1.90 | +1.99 | +2.54 | ok, not good | (4,4) | +1.90 | +1.99 | +2.54 | ok (alias), not good | +0.23 | - |
| butadiene-x7 | 3 | V | 3.36 | (18,13) | -0.01 | +0.11 | +0.12 | ok | (4,4) | -0.02 | +0.10 | +0.10 | ok | (4,4) | -0.02 | +0.10 | +0.10 | ok (alias) | -0.01 | - |
| butadiene-x8 | 3 | V | 5.20 | (18,13) | -0.09 | +0.18 | +0.25 | ok | (4,4) | -0.11 | +0.16 | +0.22 | ok | (4,4) | -0.11 | +0.16 | +0.22 | ok (alias) | -0.09 | - |
| butadiene-x9 | 3 | R | 6.29 | (18,13) | +3.04 | +2.03 | +2.33 | ok, not good | (4,4) | - | - | - | unrepresentable | (4,4) | - | - | - | unrepresentable (alias) | +3.04 | - |
| carbon_dimer-x1 | 1 | R | 2.09 | (8,13) | +0.46 | +0.09 | +0.21 | ok | (4,4) | +10.59 | +10.95 | +11.33 | ok, not good | (4,4) | +10.59 | +10.95 | +11.33 | ok (alias), not good | +0.46 | - |
| carbon_dimer-x2 | 1 | R | 2.42 | (8,13) | +0.08 | -0.19 | -0.03 | ok | (4,4) | +11.59 | +11.84 | +12.83 | ok, not good | (4,4) | +11.59 | +11.84 | +12.83 | ok (alias), not good | +0.08 | - |
| carbon_monoxide-x1 | 1 | V | 8.49 | (10,12) | +0.34 | -0.53 | +0.10 | ok | (4,4) | - | - | - | unrepresentable | (4,4) | - | - | - | unrepresentable (alias) | +0.34 | - |
| carbon_monoxide-x2 | 1 | V | 9.92 | (10,12) | +0.39 | +0.14 | +0.19 | ok | (4,4) | +0.18 | +0.01 | +0.20 | ok | (4,4) | +0.18 | +0.01 | +0.20 | ok (alias) | +0.39 | - |
| carbon_monoxide-x3 | 1 | V | 10.06 | (10,12) | +0.39 | +0.27 | +0.16 | ok | (4,4) | +0.11 | +0.10 | +0.33 | ok | (4,4) | +0.11 | +0.10 | +0.33 | ok (alias) | +0.39 | - |
| carbon_monoxide-x4 | 1 | R | 10.95 | (10,12) | -0.31 | -0.17 | +0.06 | ok | (4,4) | +6.13 | +1.70 | +2.88 | ok, not good | (4,4) | +6.13 | +1.70 | +2.88 | ok (alias), not good | -0.31 | - |
| carbon_monoxide-x5 | 1 | R | 11.52 | (10,12) | +3.42 | +1.97 | +3.12 | ok, not good | (4,4) | +9.35 | +9.05 | +8.60 | ok, not good | (4,4) | +9.35 | +9.05 | +8.60 | ok (alias), not good | +3.42 | - |
| carbon_monoxide-x6 | 1 | R | 11.72 | (10,12) | -0.37 | -0.72 | -0.15 | ok | (4,4) | - | - | - | unrepresentable | (4,4) | - | - | - | unrepresentable (alias) | -0.37 | - |
| carbon_monoxide-x7 | 3 | V | 6.28 | (10,12) | +0.11 | -0.03 | +0.05 | ok | (4,4) | - | - | - | unrepresentable | (4,4) | - | - | - | unrepresentable (alias) | +0.11 | - |
| carbon_monoxide-x8 | 3 | V | 8.45 | (10,12) | +0.29 | +0.28 | +0.12 | ok | (4,4) | +0.01 | +0.11 | +0.00 | ok | (4,4) | +0.01 | +0.11 | +0.00 | ok (alias) | +0.29 | - |
| carbon_monoxide-x9 | 3 | V | 9.27 | (10,12) | +0.37 | +0.13 | +0.11 | ok | (4,4) | -0.11 | -0.11 | +0.02 | ok | (4,4) | -0.11 | -0.11 | +0.02 | ok (alias) | +0.37 | - |
| carbon_monoxide-x10 | 3 | V | 9.80 | (10,12) | +0.22 | +0.04 | +0.08 | ok | (4,4) | +0.04 | -0.03 | +0.26 | ok | (4,4) | +0.04 | -0.03 | +0.26 | ok (alias) | +0.22 | - |
| carbon_monoxide-x11 | 3 | R | 10.47 | (10,12) | -0.20 | +0.03 | +0.14 | ok | (4,4) | +9.44 | +10.11 | +9.84 | ok, not good | (4,4) | +9.44 | +10.11 | +9.84 | ok (alias), not good | -0.20 | - |
| carbon_trimer-x1 | 1 | R | 5.22 | (12,12) | -0.04 | +0.14 | +0.12 | ok | (4,6) | +2.86 | +2.87 | +2.69 | ok, not good | (4,6) | +2.86 | +2.87 | +2.69 | ok (alias), not good | -0.04 | - |
| carbon_trimer-x2 | 1 | R | 5.91 | (12,12) | -0.25 | -0.03 | +0.05 | ok | (4,6) | +3.03 | +2.91 | +3.10 | ok, not good | (4,6) | +3.03 | +2.91 | +3.10 | ok (alias), not good | -0.25 | - |
| carbonylfluoride-x1 | 1 | V | 7.31 | (14,12) | +0.28 | -0.04 | +0.12 | ok | (10,6) | -0.45 | -0.14 | +0.21 | ok | (10,6) | -0.45 | -0.14 | +0.21 | ok (alias) | +0.28 | - |
| carbonylfluoride-x2 | 3 | V | 7.06 | (14,12) | +0.32 | -0.08 | +0.10 | ok | (10,6) | -0.48 | -0.19 | +0.17 | ok | (10,6) | -0.48 | -0.19 | +0.17 | ok (alias) | +0.28 | - |
| ccl2-x1 | 1 | V | 2.59 | (14,12) | -0.26 | -0.50 | -0.12 | ok | (4,3) | - | - | - | unrepresentable | (4,3) | - | - | - | unrepresentable (alias) | -0.12 | - |
| ccl2-x2 | 1 | V | 4.40 | (14,12) | -0.13 | -0.38 | -0.22 | ok | (8,5) | +0.47 | +0.04 | +0.15 | ok | (8,5) | +0.47 | +0.04 | +0.15 | ok (alias) | +0.02 | - |
| ccl2-x3 | 3 | V | 1.22 | (14,12) | -0.60 | -0.19 | -0.25 | ok | (4,3) | - | - | - | unrepresentable | (4,3) | - | - | - | unrepresentable (alias) | -0.51 | - |
| ccl2-x4 | 3 | V | 4.31 | (12,12) | -0.06 | -0.33 | -0.13 | ok | (8,5) | +0.44 | +0.04 | +0.20 | ok | (8,5) | +0.44 | +0.04 | +0.20 | ok (alias) | +0.05 | - |
| cclf-x1 | 1 | V | 3.57 | (14,12) | +0.04 | -0.44 | -0.01 | ok | (4,3) | - | - | - | unrepresentable | (4,3) | - | - | - | unrepresentable (alias) | +0.04 | - |
| cf2-x1 | 1 | V | 5.09 | (16,12) | +0.28 | -0.70 | -0.02 | ok | (4,3) | - | - | - | unrepresentable | (4,3) | - | - | - | unrepresentable (alias) | +0.27 | - |
| cf2-x2 | 3 | V | 2.77 | (16,12) | -0.17 | +0.01 | -0.09 | ok | (4,3) | - | - | - | unrepresentable | (4,3) | - | - | - | unrepresentable (alias) | -0.17 | - |
| cyanoacetylene-x1 | 1 | V | 5.80 | (12,12) | +0.85 | -0.02 | +0.11 | ok | (8,8) | +0.74 | -0.06 | +0.03 | ok | (8,8) | +0.74 | -0.06 | +0.03 | ok (alias) | +0.87 | - |
| cyanoacetylene-x2 | 1 | V | 6.07 | (12,12) | +0.87 | -0.05 | +0.09 | ok | (8,8) | +0.87 | -0.12 | +0.09 | ok | (8,8) | +0.87 | -0.12 | +0.09 | ok (alias) | +0.81 | - |
| cyanoacetylene-x3 | 3 | V | 4.44 | (12,12) | +0.51 | +0.19 | +0.13 | ok | (8,8) | +0.42 | +0.12 | +0.04 | ok | (8,8) | +0.42 | +0.12 | +0.04 | ok (alias) | +0.43 | - |
| cyanoacetylene-x4 | 3 | V | 5.21 | (12,12) | +0.59 | +0.01 | +0.10 | ok | (8,8) | +0.45 | -0.07 | +0.02 | ok | (8,8) | +0.45 | -0.07 | +0.02 | ok (alias) | +0.55 | - |
| cyanoformaldehyde-x1 | 1 | V | 3.81 | (18,13) | -0.01 | +0.01 | +0.14 | ok | (10,8) | +0.02 | +0.06 | +0.18 | ok | (10,8) | +0.02 | +0.06 | +0.18 | ok (alias) | -0.01 | - |
| cyanoformaldehyde-x2 | 1 | V | 6.46 | (18,13) | +1.04 | +0.06 | +0.07 | ok | (10,8) | +1.03 | +0.09 | -0.03 | ok | (10,8) | +1.03 | +0.09 | -0.03 | ok (alias) | +1.04 | - |
| cyanoformaldehyde-x3 | 3 | V | 3.44 | (18,13) | +0.03 | -0.01 | +0.10 | ok | (10,8) | +0.09 | +0.02 | +0.14 | ok | (10,8) | +0.09 | +0.02 | +0.14 | ok (alias) | +0.03 | - |
| cyanoformaldehyde-x4 | 3 | V | 5.01 | (18,13) | +0.07 | +0.29 | +0.45 | ok | (6,6) | -0.03 | +0.20 | +0.36 | ok | (6,6) | -0.03 | +0.20 | +0.36 | ok (alias) | +0.07 | - |
| cyanogen-x1 | 1 | V | 6.39 | (14,12) | +0.74 | -0.06 | +0.07 | ok | (8,8) | +0.75 | -0.12 | -0.02 | ok | (8,8) | +0.75 | -0.12 | -0.02 | ok (alias) | +0.72 | - |
| cyanogen-x2 | 1 | V | 6.66 | (14,12) | +0.75 | -0.08 | +0.13 | ok | (8,8) | +0.84 | -0.15 | +0.06 | ok | (8,8) | +0.84 | -0.15 | +0.06 | ok (alias) | +0.75 | - |
| cyanogen-x3 | 3 | V | 4.91 | (14,12) | +0.26 | +0.11 | +0.03 | ok | (8,8) | +0.37 | +0.10 | +0.01 | ok | (8,8) | +0.37 | +0.10 | +0.01 | ok (alias) | +0.26 | - |
| cyclopentadiene-x1 | 1 | V | 5.54 | (8,13) | +1.00 | -0.58 | -0.05 | ok | (4,4) | +1.47 | -0.81 | -0.47 | ok, not good | (4,4) | +1.47 | -0.81 | -0.47 | ok (alias), not good | +0.64 | - |
| cyclopentadiene-x2 | 1 | R | 5.78 | (10,12) | -0.51 | -0.27 | +0.15 | ok | (4,4) | - | - | - | unrepresentable | (4,4) | - | - | - | unrepresentable (alias) | -0.30 | - |
| cyclopentadiene-x3 | 1 | R | 6.41 | (10,12) | -0.41 | -0.40 | +0.11 | ok | (4,4) | - | - | - | unrepresentable | (4,4) | - | - | - | unrepresentable (alias) | -0.51 | - |
| cyclopentadiene-x4 | 1 | R | 6.46 | (8,12) | -0.74 | -0.65 | +0.12 | ok | (4,4) | - | - | - | unrepresentable | (4,4) | - | - | - | unrepresentable (alias) | -0.74 | - |
| cyclopentadiene-x5 | 1 | R | 6.56 | (10,12) | -0.54 | -0.27 | +0.16 | ok | (4,4) | +3.17 | +3.34 | +3.94 | ok, not good | (4,4) | +3.17 | +3.34 | +3.94 | ok (alias), not good | -0.42 | - |
| cyclopentadiene-x6 | 1 | V | 6.52 | (8,13) | +0.13 | +0.12 | +0.26 | ok | (4,4) | +0.09 | +0.17 | +0.32 | ok | (4,4) | +0.09 | +0.17 | +0.32 | ok (alias) | +0.16 | - |
| cyclopentadiene-x7 | 3 | V | 3.31 | (10,12) | +0.02 | +0.10 | +0.12 | ok | (4,4) | -0.05 | +0.08 | +0.11 | ok | (4,4) | -0.05 | +0.08 | +0.11 | ok (alias) | -0.03 | - |
| cyclopentadiene-x8 | 3 | V | 5.11 | (8,12) | -0.04 | +0.13 | +0.20 | ok | (4,4) | -0.11 | +0.16 | +0.26 | ok | (4,4) | -0.11 | +0.16 | +0.26 | ok (alias) | -0.04 | - |
| cyclopentadiene-x9 | 3 | R | 5.73 | (8,12) | -0.30 | -0.28 | +0.13 | ok | (4,4) | - | - | - | unrepresentable | (4,4) | - | - | - | unrepresentable (alias) | -0.30 | - |
| cyclopentadiene-x10 | 3 | R | 6.36 | (10,12) | -0.43 | -0.41 | +0.13 | ok | (4,4) | - | - | - | unrepresentable | (4,4) | - | - | - | unrepresentable (alias) | -0.49 | - |
| cyclopentadienone-x1 | 1 | V | 2.94 | (8,13) | +1.11 | +0.35 | +0.20 | ok, not good | (10,8) | +0.49 | +0.17 | +0.16 | ok | (10,8) | +0.49 | +0.17 | +0.16 | ok (alias) | +1.11 | - |
| cyclopentadienone-x2 | 1 | V | 3.58 | (8,13) | +1.05 | -0.42 | -0.32 | ok | (6,6) | +1.17 | -0.18 | -0.21 | ok, not good | (6,6) | +1.17 | -0.18 | -0.21 | ok (alias), not good | +0.83 | - |
| cyclopentadienone-x3 | 1 | V | 5.02 | (8,13) | +0.72 | +0.12 | +0.02 | ok | (6,6) | - | - | - | unrepresentable | (6,6) | - | - | - | unrepresentable (alias) | +0.72 | - |
| cyclopentadienone-x4 | 1 | V | 6.00 | (8,13) | -0.02 | -0.12 | +0.03 | ok | (6,6) | +0.15 | -0.02 | +0.05 | ok | (6,6) | +0.15 | -0.02 | +0.05 | ok (alias) | -0.02 | - |
| cyclopentadienone-x5 | 1 | V | 6.09 | (10,12) | -0.08 | -0.24 | -0.10 | ok | (10,8) | +2.40 | +1.55 | +1.56 | ok, not good | (10,8) | +2.40 | +1.55 | +1.56 | ok (alias), not good | +2.10 | - |
| cyclopentadienone-x6 | 3 | V | 2.29 | (8,13) | +0.19 | +0.09 | +0.09 | ok | (6,6) | +0.28 | +0.12 | +0.07 | ok | (6,6) | +0.28 | +0.12 | +0.07 | ok (alias) | +0.19 | - |
| cyclopentadienone-x7 | 3 | V | 2.65 | (8,13) | +1.13 | +0.31 | +0.17 | ok, not good | (10,8) | +0.54 | +0.12 | +0.07 | ok | (10,8) | +0.54 | +0.12 | +0.07 | ok (alias) | +1.13 | - |
| cyclopentadienone-x8 | 3 | V | 4.19 | (8,13) | +0.25 | +0.21 | +0.24 | ok | (6,6) | +0.05 | +0.09 | +0.12 | ok | (6,6) | +0.05 | +0.09 | +0.12 | ok (alias) | +0.25 | - |
| cyclopentadienone-x9 | 3 | V | 4.91 | (8,12) | +0.80 | +0.19 | +0.05 | ok | (6,6) | - | - | - | unrepresentable | (6,6) | - | - | - | unrepresentable (alias) | +0.21 | - |
| cyclopentadienethione-x1 | 1 | V | 1.70 | (10,12) | +0.27 | +0.07 | +0.02 | ok | (10,8) | +0.22 | +0.11 | +0.02 | ok | (10,8) | +0.22 | +0.11 | +0.02 | ok (alias) | +0.27 | - |
| cyclopentadienethione-x2 | 1 | V | 2.63 | (8,12) | +0.52 | -0.14 | -0.20 | ok | (6,6) | +0.41 | -0.03 | -0.06 | ok | (6,6) | +0.41 | -0.03 | -0.06 | ok (alias) | +0.14 | - |
| cyclopentadienethione-x3 | 1 | V | 3.16 | (10,12) | +0.11 | +0.07 | +0.06 | ok | (10,8) | +0.11 | +0.06 | +0.01 | ok | (10,8) | +0.11 | +0.06 | +0.01 | ok (alias) | +0.11 | - |
| cyclopentadienethione-x4 | 1 | V | 4.96 | (10,12) | +0.49 | +0.31 | +0.48 | ok | (6,6) | +0.61 | +0.44 | +0.50 | ok | (6,6) | +0.61 | +0.44 | +0.50 | ok (alias) | +0.52 | - |
| cyclopentadienethione-x5 | 1 | V | 5.43 | (10,12) | +0.04 | -0.15 | +0.02 | ok | (10,8) | +0.19 | -0.01 | +0.03 | ok | (10,8) | +0.19 | -0.01 | +0.03 | ok (alias) | +0.04 | - |
| cyclopentadienethione-x6 | 3 | V | 1.47 | (10,12) | +0.28 | +0.06 | -0.00 | ok | (10,8) | +0.26 | +0.09 | -0.02 | ok | (10,8) | +0.26 | +0.09 | -0.02 | ok (alias) | +0.28 | - |
| cyclopentadienethione-x7 | 3 | V | 1.88 | (10,12) | +0.23 | +0.02 | +0.04 | ok | (6,6) | +0.22 | +0.01 | -0.03 | ok | (6,6) | +0.22 | +0.01 | -0.03 | ok (alias) | +0.11 | - |
| cyclopentadienethione-x8 | 3 | V | 2.51 | (10,12) | -0.05 | +0.07 | +0.04 | ok | (6,6) | -0.05 | +0.09 | +0.08 | ok | (6,6) | -0.05 | +0.09 | +0.08 | ok (alias) | +0.17 | - |
| cyclopentadienethione-x9 | 3 | V | 3.13 | (8,12) | +0.51 | +0.18 | +0.03 | ok | (10,8) | +0.12 | +0.08 | +0.01 | ok | (10,8) | +0.12 | +0.08 | +0.01 | ok (alias) | +0.51 | - |
| cyclopropene-x1 | 1 | V | 6.68 | (12,12) | -0.28 | +0.01 | +0.31 | ok | (2,2) | - | - | - | unrepresentable | (2,2) | - | - | - | unrepresentable (alias) | -0.24 | - |
| cyclopropene-x2 | 1 | V | 6.79 | (12,12) | +0.40 | -0.42 | +0.13 | ok | (2,2) | +0.44 | -0.45 | +0.21 | ok | (2,2) | +0.44 | -0.45 | +0.21 | ok (alias) | +0.64 | - |
| cyclopropene-x3 | 3 | V | 4.38 | (12,12) | +0.07 | -0.01 | +0.01 | ok | (2,2) | -0.23 | +0.06 | +0.24 | ok | (2,2) | -0.23 | +0.06 | +0.24 | ok (alias) | +0.15 | - |
| cyclopropene-x4 | 3 | V | 6.45 | (12,12) | -0.11 | +0.15 | +0.46 | ok | (2,2) | - | - | - | unrepresentable | (2,2) | - | - | - | unrepresentable (alias) | -0.07 | - |
| cyclopropenone-x1 | 1 | V | 4.26 | (12,12) | +0.40 | -0.06 | +0.05 | ok | (8,6) | +0.52 | -0.15 | -0.23 | ok | (8,6) | +0.52 | -0.15 | -0.23 | ok (alias) | +0.40 | - |
| cyclopropenone-x2 | 1 | V | 5.55 | (12,12) | +0.12 | +0.14 | +0.29 | ok | (8,6) | +0.13 | +0.19 | +0.33 | ok | (8,6) | +0.13 | +0.19 | +0.33 | ok (alias) | +0.12 | - |
| cyclopropenone-x3 | 1 | R | 6.34 | (12,12) | +0.13 | +0.21 | +0.47 | ok | (8,6) | +0.22 | +0.25 | +0.48 | ok | (8,6) | +0.22 | +0.25 | +0.48 | ok (alias) | +0.13 | - |
| cyclopropenone-x4 | 1 | V | 6.54 | (12,12) | -0.64 | -0.14 | -0.03 | ok | (8,6) | +4.42 | +2.64 | +3.32 | ok, not good | (8,6) | +4.42 | +2.64 | +3.32 | ok (alias), not good | -0.64 | - |
| cyclopropenone-x5 | 1 | R | 6.98 | (12,12) | -0.72 | -0.36 | +0.08 | ok | (8,6) | +9.11 | +6.80 | +7.32 | ok, not good | (8,6) | +9.11 | +6.80 | +7.32 | ok (alias), not good | -0.72 | - |
| cyclopropenone-x6 | 1 | R | 7.02 | (12,12) | +1.90 | +1.31 | +1.66 | ok, not good | (8,6) | +2.52 | +1.14 | +1.43 | ok, not good | (8,6) | +2.52 | +1.14 | +1.43 | ok (alias), not good | +2.06 | - |
| cyclopropenone-x7 | 1 | V | 8.28 | (12,12) | +1.52 | +0.22 | +0.63 | ok, not good | (8,6) | +4.82 | +3.08 | +3.66 | ok, not good | (8,6) | +4.82 | +3.08 | +3.66 | ok (alias), not good | +1.52 | - |
| cyclopropenone-x8 | 3 | V | 3.93 | (12,12) | +0.29 | -0.00 | +0.09 | ok | (8,6) | +0.72 | -0.10 | -0.36 | ok | (8,6) | +0.72 | -0.10 | -0.36 | ok (alias) | +0.29 | - |
| cyclopropenone-x9 | 3 | V | 4.88 | (12,12) | -0.07 | +0.02 | +0.08 | ok | (4,4) | -0.34 | +0.01 | +0.22 | ok | (4,4) | -0.34 | +0.01 | +0.22 | ok (alias) | -0.02 | - |
| cyclopropenone-x10 | 3 | V | 5.35 | (12,12) | +0.22 | +0.11 | +0.27 | ok | (8,6) | +0.07 | +0.05 | +0.24 | ok | (8,6) | +0.07 | +0.05 | +0.24 | ok (alias) | +0.22 | - |
| cyclopropenone-x11 | 3 | V | 6.79 | (12,12) | -0.04 | +0.09 | +0.30 | ok | (4,4) | -0.23 | +0.05 | +0.34 | ok | (4,4) | -0.23 | +0.05 | +0.34 | ok (alias) | -0.04 | - |
| cyclopropenethione-x1 | 1 | V | 3.41 | (12,12) | -0.08 | +0.12 | -0.04 | ok | (8,6) | +0.07 | +0.19 | +0.10 | ok | (8,6) | +0.07 | +0.19 | +0.10 | ok (alias) | -0.17 | - |
| cyclopropenethione-x2 | 1 | V | 3.45 | (12,12) | +0.06 | +0.09 | +0.04 | ok | (8,6) | +0.13 | +0.09 | +0.00 | ok | (8,6) | +0.13 | +0.09 | +0.00 | ok (alias) | -0.07 | - |
| cyclopropenethione-x3 | 1 | V | 4.60 | (12,12) | +0.30 | +0.13 | +0.09 | ok | (4,4) | -0.06 | +0.18 | +0.20 | ok | (4,4) | -0.06 | +0.18 | +0.20 | ok (alias) | +0.30 | - |
| cyclopropenethione-x4 | 1 | R | 5.34 | (12,12) | -0.62 | -0.16 | -0.07 | ok | (8,6) | +5.34 | +3.42 | +3.91 | ok, not good | (8,6) | +5.34 | +3.42 | +3.91 | ok (alias), not good | -0.62 | - |
| cyclopropenethione-x5 | 1 | V | 5.46 | (12,12) | +0.49 | -0.05 | +0.30 | ok | (4,4) | +1.00 | -0.05 | +0.25 | ok | (4,4) | +1.00 | -0.05 | +0.25 | ok (alias) | +0.44 | - |
| cyclopropenethione-x6 | 1 | R | 5.92 | (12,12) | -0.66 | -0.32 | -0.06 | ok | (8,6) | +4.70 | +2.80 | +3.15 | ok, not good | (8,6) | +4.70 | +2.80 | +3.15 | ok (alias), not good | -0.67 | - |
| cyclopropenethione-x7 | 3 | V | 3.28 | (12,12) | -0.12 | +0.07 | -0.05 | ok | (8,6) | +0.02 | +0.12 | +0.08 | ok | (8,6) | +0.02 | +0.12 | +0.08 | ok (alias) | -0.15 | - |
| cyclopropenethione-x8 | 3 | V | 3.32 | (12,12) | +0.10 | +0.14 | +0.08 | ok | (8,6) | +0.21 | +0.14 | +0.03 | ok | (8,6) | +0.21 | +0.14 | +0.03 | ok (alias) | -0.03 | - |
| cyclopropenethione-x9 | 3 | V | 4.01 | (12,12) | +0.05 | +0.15 | +0.18 | ok | (4,4) | -0.17 | +0.14 | +0.19 | ok | (4,4) | -0.17 | +0.14 | +0.19 | ok (alias) | +0.05 | - |
| cyclopropenethione-x10 | 3 | V | 4.01 | (12,12) | -0.04 | +0.04 | -0.02 | ok | (4,4) | -0.18 | +0.08 | +0.12 | ok | (4,4) | -0.18 | +0.08 | +0.12 | ok (alias) | -0.04 | - |
| diacetylene-x1 | 1 | V | 5.33 | (8,12) | +0.44 | -0.18 | +0.06 | ok | (8,8) | +0.80 | -0.02 | +0.05 | ok | (8,8) | +0.80 | -0.02 | +0.05 | ok (alias) | +0.44 | - |
| diacetylene-x2 | 1 | V | 5.61 | (8,12) | +0.46 | -0.18 | +0.09 | ok | (8,8) | +0.80 | -0.12 | +0.06 | ok | (8,8) | +0.80 | -0.12 | +0.06 | ok (alias) | +0.46 | - |
| diacetylene-x3 | 3 | V | 4.10 | (8,12) | +0.22 | -0.01 | +0.02 | ok | (8,8) | +0.44 | +0.10 | +0.02 | ok | (8,8) | +0.44 | +0.10 | +0.02 | ok (alias) | +0.22 | - |
| diacetylene-x4 | 3 | V | 4.78 | (8,12) | +0.30 | -0.13 | +0.05 | ok | (8,8) | +0.58 | +0.01 | +0.06 | ok | (8,8) | +0.58 | +0.01 | +0.06 | ok (alias) | +0.30 | - |
| diazirine-x1 | 1 | V | 4.09 | (16,12) | +0.18 | +0.06 | +0.05 | ok | (6,4) | +0.11 | +0.07 | -0.15 | ok | (6,4) | +0.11 | +0.07 | -0.15 | ok (alias) | +0.18 | - |
| diazirine-x2 | 1 | V | 7.27 | (16,12) | +1.33 | +0.30 | +0.60 | ok, not good | (6,4) | +1.93 | -0.15 | +0.30 | ok, not good | (6,4) | +1.93 | -0.15 | +0.30 | ok (alias), not good | +1.33 | - |
| diazirine-x3 | 1 | R | 7.44 | (16,12) | -0.09 | -0.31 | -0.04 | ok | (6,4) | +0.00 | -0.30 | -0.01 | ok | (6,4) | +0.00 | -0.30 | -0.01 | ok (alias) | -0.09 | - |
| diazirine-x4 | 1 | R | 8.03 | (14,12) | +1.74 | +1.42 | +1.67 | ok, not good | (6,4) | +1.26 | +1.24 | +1.42 | ok, not good | (6,4) | +1.26 | +1.24 | +1.42 | ok (alias), not good | +1.13 | - |
| diazirine-x5 | 3 | V | 3.49 | (14,12) | +0.11 | +0.11 | +0.04 | ok | (6,4) | +0.10 | +0.09 | -0.21 | ok | (6,4) | +0.10 | +0.09 | -0.21 | ok (alias) | +0.15 | - |
| diazirine-x6 | 3 | V | 5.06 | (14,12) | -0.13 | +0.04 | +0.06 | ok | (2,2) | -0.34 | +0.17 | +0.43 | ok | (2,2) | -0.34 | +0.17 | +0.43 | ok (alias) | -0.09 | - |
| diazirine-x7 | 3 | V | 6.12 | (16,12) | +0.06 | +0.03 | +0.10 | ok | (6,4) | +0.34 | +0.09 | +0.08 | ok | (6,4) | +0.34 | +0.09 | +0.08 | ok (alias) | +0.39 | - |
| diazirine-x8 | 3 | R | 6.81 | (16,12) | +0.22 | +0.28 | +0.28 | ok | (6,4) | - | - | - | unrepresentable | (6,4) | - | - | - | unrepresentable (alias) | +0.22 | - |
| diazomethane-x1 | 1 | V | 3.14 | (14,12) | +0.36 | +0.19 | +0.06 | ok | (6,5) | -0.14 | +0.10 | +0.05 | ok | (6,5) | -0.14 | +0.10 | +0.05 | ok (alias) | +0.36 | - |
| diazomethane-x2 | 1 | R | 5.54 | (14,12) | -0.99 | -0.05 | +0.08 | ok | (6,5) | - | - | - | unrepresentable | (6,5) | - | - | - | unrepresentable (alias) | -0.99 | - |
| diazomethane-x3 | 1 | V | 5.90 | (14,12) | -0.56 | -0.15 | +0.17 | ok | (6,5) | +1.14 | +0.27 | +0.53 | ok, not good | (6,5) | +1.14 | +0.27 | +0.53 | ok (alias), not good | -0.56 | - |
| diazomethane-x4 | 3 | V | 2.79 | (14,12) | +0.45 | +0.23 | +0.14 | ok | (6,5) | -0.09 | +0.15 | +0.15 | ok | (6,5) | -0.09 | +0.15 | +0.15 | ok (alias) | +0.45 | - |
| diazomethane-x5 | 3 | V | 4.05 | (14,12) | +0.02 | +0.17 | +0.08 | ok | (6,5) | -0.17 | +0.11 | +0.12 | ok | (6,5) | -0.17 | +0.11 | +0.12 | ok (alias) | -0.04 | - |
| diazomethane-x6 | 3 | R | 5.35 | (14,12) | -0.94 | -0.03 | +0.11 | ok | (6,5) | - | - | - | unrepresentable | (6,5) | - | - | - | unrepresentable (alias) | -0.94 | - |
| diazomethane-x7 | 3 | R | 6.82 | (14,12) | +0.56 | +0.25 | +0.21 | ok | (6,5) | +0.38 | +0.32 | +0.28 | ok | (6,5) | +0.38 | +0.32 | +0.28 | ok (alias) | +0.61 | - |
| difluorodiazirine-x1 | 1 | V | 3.74 | (12,12) | +1.43 | +0.24 | +0.07 | ok, not good | (14,8) | +0.44 | +0.12 | -0.05 | ok | (14,8) | +0.44 | +0.12 | -0.05 | ok (alias) | +0.99 | - |
| difluorodiazirine-x2 | 1 | V | 7.00 | (12,12) | +0.52 | -0.16 | +0.06 | ok | (14,8) | +0.10 | -0.19 | +0.01 | ok | (14,8) | +0.10 | -0.19 | +0.01 | ok (alias) | +0.52 | - |
| difluorodiazirine-x3 | 1 | V | 8.52 | (12,12) | +0.61 | +0.16 | +0.23 | ok | (14,8) | +3.50 | -0.53 | -0.14 | ok, not good | (14,8) | +3.50 | -0.53 | -0.14 | ok (alias), not good | +0.61 | - |
| difluorodiazirine-x4 | 3 | V | 3.03 | (12,12) | +1.15 | +0.21 | -0.03 | ok, not good | (14,8) | +0.43 | +0.19 | -0.43 | ok | (14,8) | +0.43 | +0.19 | -0.43 | ok (alias) | +0.93 | - |
| difluorodiazirine-x5 | 3 | V | 5.44 | (12,12) | +0.06 | +0.13 | +0.12 | ok | (10,6) | -0.41 | +0.08 | +0.24 | ok | (10,6) | -0.41 | +0.08 | +0.24 | ok (alias) | +0.06 | - |
| difluorodiazirine-x6 | 3 | V | 5.80 | (12,12) | +0.72 | +0.12 | +0.15 | ok | (14,8) | +0.28 | +0.09 | +0.11 | ok | (14,8) | +0.28 | +0.09 | +0.11 | ok (alias) | +0.73 | - |
| dinitrogen-x1 | 1 | V | 9.34 | (10,12) | +0.35 | -0.24 | +0.05 | ok | (8,6) | +0.32 | -0.24 | +0.13 | ok | (8,6) | +0.32 | -0.24 | +0.13 | ok (alias) | +0.35 | - |
| dinitrogen-x2 | 1 | V | 9.88 | (10,12) | +0.52 | +0.14 | +0.23 | ok | (4,4) | +0.46 | -0.05 | +0.03 | ok | (4,4) | +0.46 | -0.05 | +0.03 | ok (alias) | +0.52 | - |
| dinitrogen-x3 | 1 | V | 10.29 | (10,12) | +0.34 | +0.03 | +0.08 | ok | (4,4) | -0.12 | -0.58 | -0.40 | ok | (4,4) | -0.12 | -0.58 | -0.40 | ok (alias) | +0.34 | - |
| dinitrogen-x4 | 1 | R | 12.98 | (10,12) | +4.85 | +4.90 | +4.57 | ok, not good | (8,6) | +4.32 | +4.91 | +4.69 | ok, not good | (8,6) | +4.32 | +4.91 | +4.69 | ok (alias), not good | +4.85 | - |
| dinitrogen-x5 | 1 | R | 13.03 | (10,12) | +0.74 | -0.23 | +0.35 | ok | (8,6) | +0.81 | -0.22 | +0.38 | ok | (8,6) | +0.81 | -0.22 | +0.38 | ok (alias) | +0.74 | - |
| dinitrogen-x6 | 1 | R | 13.09 | (10,12) | +1.82 | +0.71 | +1.83 | ok, not good | (8,6) | +5.71 | +0.50 | +2.32 | ok, not good | (8,6) | +5.71 | +0.50 | +2.32 | ok (alias), not good | +1.82 | - |
| dinitrogen-x7 | 1 | R | 13.46 | (10,12) | +4.65 | +4.26 | +5.12 | ok, not good | (8,6) | +6.31 | +4.19 | +5.26 | ok, not good | (8,6) | +6.31 | +4.19 | +5.26 | ok (alias), not good | +4.65 | - |
| dinitrogen-x8 | 3 | V | 7.70 | (10,12) | +0.27 | +0.24 | +0.11 | ok | (4,4) | -0.00 | +0.14 | +0.04 | ok | (4,4) | -0.00 | +0.14 | +0.04 | ok (alias) | +0.27 | - |
| dinitrogen-x9 | 3 | V | 8.01 | (10,12) | +0.21 | -0.06 | +0.08 | ok | (8,6) | +0.26 | +0.00 | +0.10 | ok | (8,6) | +0.26 | +0.00 | +0.10 | ok (alias) | +0.21 | - |
| dinitrogen-x10 | 3 | V | 8.87 | (10,12) | +0.48 | +0.13 | +0.12 | ok | (4,4) | +0.17 | +0.00 | +0.03 | ok | (4,4) | +0.17 | +0.00 | +0.03 | ok (alias) | +0.48 | - |
| dinitrogen-x11 | 3 | V | 9.66 | (10,12) | +0.25 | +0.10 | +0.11 | ok | (4,4) | +0.60 | +0.12 | +0.34 | ok | (4,4) | +0.60 | +0.12 | +0.34 | ok (alias) | +0.25 | - |
| ethylene-x1 | 1 | R | 7.39 | (10,12) | -0.43 | -0.23 | +0.05 | ok | (2,2) | - | - | - | unrepresentable | (2,2) | - | - | - | unrepresentable (alias) | -0.43 | - |
| ethylene-x2 | 1 | V | 7.93 | (10,12) | +0.31 | -0.56 | +0.21 | ok | (2,2) | -0.18 | -0.58 | +0.26 | ok | (2,2) | -0.18 | -0.58 | +0.26 | ok (alias) | +0.31 | - |
| ethylene-x3 | 1 | R | 8.08 | (10,12) | +0.90 | +0.18 | +0.50 | ok | (2,2) | - | - | - | unrepresentable | (2,2) | - | - | - | unrepresentable (alias) | +0.90 | - |
| ethylene-x4 | 1 | V | 12.92 | (10,12) | -1.53 | -1.79 | -1.20 | ok, not good | (2,2) | +1.61 | -0.82 | -0.12 | ok, not good | (2,2) | +1.61 | -0.82 | -0.12 | ok (alias), not good | -1.53 | - |
| ethylene-x5 | 3 | V | 4.54 | (10,12) | +0.09 | +0.08 | +0.03 | ok | (2,2) | -0.28 | +0.05 | +0.13 | ok | (2,2) | -0.28 | +0.05 | +0.13 | ok (alias) | +0.09 | - |
| ethylene-x6 | 3 | R | 7.23 | (10,12) | -0.37 | -0.19 | +0.10 | ok | (2,2) | - | - | - | unrepresentable | (2,2) | - | - | - | unrepresentable (alias) | -0.37 | - |
| ethylene-x7 | 3 | R | 7.98 | (10,12) | +0.54 | -0.08 | +0.25 | ok | (2,2) | - | - | - | unrepresentable | (2,2) | - | - | - | unrepresentable (alias) | +0.54 | - |
| formaldehyde-x1 | 1 | V | 3.98 | (10,12) | -0.11 | -0.04 | -0.03 | ok | (6,4) | +0.03 | +0.09 | +0.24 | ok | (6,4) | +0.03 | +0.09 | +0.24 | ok (alias) | -0.11 | - |
| formaldehyde-x2 | 1 | R | 7.23 | (10,12) | -0.70 | -0.38 | -0.08 | ok | (6,4) | +8.85 | +7.56 | +8.32 | ok, not good | (6,4) | +8.85 | +7.56 | +8.32 | ok (alias), not good | -0.70 | - |
| formaldehyde-x3 | 1 | R | 8.13 | (10,12) | -0.94 | -0.69 | -0.13 | ok | (6,4) | - | - | - | unrepresentable | (6,4) | - | - | - | unrepresentable (alias) | -0.94 | - |
| formaldehyde-x4 | 1 | R | 8.23 | (10,12) | -0.97 | -0.48 | -0.03 | ok | (6,4) | +2.48 | +0.96 | +1.51 | ok, not good | (6,4) | +2.48 | +0.96 | +1.51 | ok (alias), not good | -0.97 | - |
| formaldehyde-x5 | 1 | R | 8.67 | (10,12) | +1.61 | +1.27 | +1.48 | ok, not good | (6,4) | +6.25 | +4.64 | +3.51 | ok, not good | (6,4) | +6.25 | +4.64 | +3.51 | ok (alias), not good | +1.61 | - |
| formaldehyde-x6 | 1 | V | 9.22 | (10,12) | +1.26 | +1.35 | +1.63 | ok, not good | (6,4) | -0.02 | -0.25 | +0.06 | not_converged | (6,4) | -0.02 | -0.25 | +0.06 | not_converged (alias) | +1.26 | - |
| formaldehyde-x7 | 1 | V | 9.43 | (10,12) | +0.42 | +0.16 | +0.68 | ok | (6,4) | +2.55 | +0.71 | +0.93 | ok, not good | (6,4) | +2.55 | +0.71 | +0.93 | ok (alias), not good | +0.42 | - |
| formaldehyde-x8 | 1 | V | 10.35 | (10,12) | -0.42 | -0.83 | -0.28 | ok | (6,4) | +9.61 | +7.81 | +7.27 | ok, not good | (6,4) | +9.61 | +7.81 | +7.27 | ok (alias), not good | -0.42 | - |
| formaldehyde-x9 | 3 | V | 3.58 | (10,12) | +0.00 | -0.05 | -0.00 | ok | (6,4) | +0.08 | +0.03 | +0.15 | ok | (6,4) | +0.08 | +0.03 | +0.15 | ok (alias) | +0.23 | - |
| formaldehyde-x10 | 3 | V | 6.06 | (10,12) | +0.05 | +0.10 | -0.02 | ok | (2,2) | -0.66 | -0.06 | +0.17 | ok | (2,2) | -0.66 | -0.06 | +0.17 | ok (alias) | +0.02 | - |
| formaldehyde-x11 | 3 | R | 7.06 | (10,12) | -0.62 | -0.36 | -0.04 | ok | (6,4) | +7.39 | +6.30 | +6.65 | ok, not good | (6,4) | +7.39 | +6.30 | +6.65 | ok (alias), not good | -0.62 | - |
| formaldehyde-x12 | 3 | R | 7.94 | (10,12) | -0.53 | -0.49 | -0.03 | ok | (6,4) | - | - | - | unrepresentable | (6,4) | - | - | - | unrepresentable (alias) | -0.84 | - |
| formaldehyde-x13 | 3 | R | 8.10 | (10,12) | -0.48 | -0.26 | +0.16 | ok | (6,4) | - | - | - | unrepresentable | (6,4) | - | - | - | unrepresentable (alias) | -0.48 | - |
| formaldehyde-x14 | 3 | R | 8.42 | (10,12) | +0.42 | +0.07 | +0.18 | ok | (6,4) | +0.00 | -0.08 | +0.13 | ok | (6,4) | +0.00 | -0.08 | +0.13 | ok (alias) | +0.42 | - |
| formamide-x1 | 1 | V | 5.65 | (10,12) | +0.20 | +0.02 | +0.12 | ok | (8,5) | -0.32 | -0.02 | +0.25 | ok | (8,5) | -0.32 | -0.02 | +0.25 | ok (alias) | +0.61 | - |
| formamide-x2 | 1 | R | 6.77 | (10,12) | -0.04 | -0.06 | +0.26 | ok | (8,5) | +1.67 | +0.55 | +0.78 | ok, not good | (8,5) | +1.67 | +0.55 | +0.78 | ok (alias), not good | -0.29 | - |
| formamide-x3 | 1 | R | 7.38 | (10,12) | -0.55 | -0.47 | +0.17 | ok | (8,5) | +4.32 | +2.83 | +3.51 | ok, not good | (8,5) | +4.32 | +2.83 | +3.51 | ok (alias), not good | +1.22 | - |
| formamide-x4 | 1 | V | 7.63 | (10,12) | +1.22 | +0.10 | +0.51 | ok, not good | (8,5) | +10.08 | +7.36 | +8.28 | ok, not good | (8,5) | +10.08 | +7.36 | +8.28 | ok (alias), not good | +1.19 | - |
| formamide-x5 | 3 | V | 5.38 | (10,12) | +0.62 | +0.07 | +0.11 | ok | (8,5) | -0.38 | -0.10 | +0.20 | ok | (8,5) | -0.38 | -0.10 | +0.20 | ok (alias) | +0.65 | - |
| formamide-x6 | 3 | V | 5.81 | (10,12) | +0.24 | +0.05 | +0.17 | ok | (4,3) | -0.06 | +0.13 | +0.38 | ok | (4,3) | -0.06 | +0.13 | +0.38 | ok (alias) | +0.46 | - |
| formylfluoride-x1 | 1 | V | 5.96 | (12,12) | +0.53 | +0.02 | +0.07 | ok | (8,5) | -0.31 | -0.07 | +0.21 | ok | (8,5) | -0.31 | -0.07 | +0.21 | ok (alias) | +0.19 | - |
| formylfluoride-x2 | 3 | V | 5.63 | (12,12) | +0.59 | +0.01 | +0.06 | ok | (8,5) | -0.37 | -0.16 | +0.15 | ok | (8,5) | -0.37 | -0.16 | +0.15 | ok (alias) | +0.30 | - |
| furan-x1 | 1 | R | 6.09 | (10,12) | -0.44 | -0.18 | +0.13 | ok | (6,5) | - | - | - | unrepresentable | (6,5) | - | - | - | unrepresentable (alias) | -0.49 | - |
| furan-x2 | 1 | V | 6.37 | (16,12) | -0.16 | +0.07 | +0.53 | ok | (6,5) | +1.01 | -0.69 | -0.23 | ok | (6,5) | +1.01 | -0.69 | -0.23 | ok (alias) | -0.16 | - |
| furan-x3 | 1 | V | 6.56 | (12,12) | +0.32 | +0.17 | +0.30 | ok | (6,5) | +0.20 | +0.18 | +0.32 | ok | (6,5) | +0.20 | +0.18 | +0.32 | ok (alias) | +0.22 | - |
| furan-x4 | 1 | R | 6.64 | (10,12) | +0.35 | +0.58 | +1.04 | ok | (6,5) | - | - | - | unrepresentable | (6,5) | - | - | - | unrepresentable (alias) | +0.30 | - |
| furan-x5 | 1 | R | 6.81 | (12,12) | -0.92 | -0.58 | +0.16 | ok | (6,5) | - | - | - | unrepresentable | (6,5) | - | - | - | unrepresentable (alias) | -0.94 | - |
| furan-x6 | 1 | R | 7.24 | (12,12) | -0.75 | -0.47 | -0.09 | ok | (6,5) | +2.88 | +1.11 | +1.46 | ok, not good | (6,5) | +2.88 | +1.11 | +1.46 | ok (alias), not good | -0.77 | - |
| furan-x7 | 3 | V | 4.20 | (12,12) | -0.02 | +0.14 | +0.11 | ok | (6,5) | -0.26 | +0.10 | +0.23 | ok | (6,5) | -0.26 | +0.10 | +0.23 | ok (alias) | -0.08 | - |
| furan-x8 | 3 | V | 5.46 | (12,12) | +0.01 | +0.14 | +0.24 | ok | (6,5) | -0.06 | +0.16 | +0.27 | ok | (6,5) | -0.06 | +0.16 | +0.27 | ok (alias) | +0.00 | - |
| furan-x9 | 3 | R | 6.02 | (12,12) | -0.44 | -0.17 | +0.14 | ok | (6,5) | - | - | - | unrepresentable | (6,5) | - | - | - | unrepresentable (alias) | -0.44 | - |
| furan-x10 | 3 | R | 6.59 | (18,13) | +0.24 | +0.53 | +0.93 | ok | (6,5) | - | - | - | unrepresentable | (6,5) | - | - | - | unrepresentable (alias) | +0.30 | - |
| glyoxal-x1 | 1 | V | 2.88 | (12,12) | +0.27 | -0.12 | +0.04 | ok | (8,6) | +0.73 | +0.15 | +0.06 | ok | (8,6) | +0.73 | +0.15 | +0.06 | ok (alias) | +0.27 | - |
| glyoxal-x2 | 1 | V | 4.24 | (12,12) | +0.11 | +0.04 | +0.13 | ok | (8,6) | +0.20 | +0.15 | +0.18 | ok | (8,6) | +0.20 | +0.15 | +0.18 | ok (alias) | +0.11 | - |
| glyoxal-x3 | 1 | V | 5.61 | (12,12) | -0.18 | -0.31 | -0.05 | ok | (8,6) | +3.45 | +3.64 | +3.99 | ok, not good | (8,6) | +3.45 | +3.64 | +3.99 | ok (alias), not good | -0.18 | - |
| glyoxal-x4 | 1 | V | 6.57 | (12,12) | +0.68 | -0.19 | +0.21 | ok | (12,8) | +0.94 | +0.65 | +0.91 | ok | (12,8) | +0.94 | +0.65 | +0.91 | ok (alias) | +0.68 | - |
| glyoxal-x5 | 1 | R | 7.71 | (12,12) | +1.90 | +0.17 | +0.94 | ok, not good | (8,6) | +2.48 | -0.26 | +0.25 | ok, not good | (8,6) | +2.48 | -0.26 | +0.25 | ok (alias), not good | +1.90 | - |
| glyoxal-x6 | 3 | V | 2.49 | (12,12) | +0.31 | -0.14 | +0.02 | ok | (8,6) | +0.74 | +0.03 | -0.05 | ok | (8,6) | +0.74 | +0.03 | -0.05 | ok (alias) | +0.31 | - |
| glyoxal-x7 | 3 | V | 3.89 | (12,12) | +0.22 | -0.02 | +0.11 | ok | (8,6) | +0.29 | +0.13 | +0.18 | ok | (8,6) | +0.29 | +0.13 | +0.18 | ok (alias) | +0.23 | - |
| glyoxal-x8 | 3 | V | 5.15 | (12,12) | +0.17 | +0.03 | +0.00 | ok | (4,4) | -0.23 | +0.03 | +0.18 | ok | (4,4) | -0.23 | +0.03 | +0.18 | ok (alias) | +0.17 | - |
| glyoxal-x9 | 3 | V | 6.30 | (12,12) | +0.07 | +0.03 | +0.03 | ok | (4,4) | -0.21 | +0.10 | +0.26 | ok | (4,4) | -0.21 | +0.10 | +0.26 | ok (alias) | +0.07 | - |
| hccl-x1 | 1 | V | 1.98 | (12,12) | +0.18 | -0.28 | -0.02 | ok | (2,2) | - | - | - | unrepresentable | (2,2) | - | - | - | unrepresentable (alias) | +0.18 | - |
| hcf-x1 | 1 | V | 2.49 | (12,12) | +0.34 | -0.27 | +0.01 | ok | (2,2) | - | - | - | unrepresentable | (2,2) | - | - | - | unrepresentable (alias) | +0.53 | - |
| hcp-x1 | 1 | V | 4.84 | (10,12) | +0.53 | +0.15 | +0.25 | ok | (4,4) | +0.49 | +0.05 | +0.05 | ok | (4,4) | +0.49 | +0.05 | +0.05 | ok (alias) | +0.42 | - |
| hcp-x2 | 1 | V | 5.15 | (10,12) | +0.50 | +0.15 | +0.20 | ok | (4,4) | +0.61 | -0.24 | +0.17 | ok | (4,4) | +0.61 | -0.24 | +0.17 | ok (alias) | +0.62 | - |
| hcp-x3 | 3 | V | 3.47 | (10,12) | +0.18 | +0.19 | +0.11 | ok | (4,4) | +0.03 | +0.12 | +0.05 | ok | (4,4) | +0.03 | +0.12 | +0.05 | ok (alias) | +0.23 | - |
| hcp-x4 | 3 | V | 4.22 | (10,12) | +0.42 | +0.11 | +0.11 | ok | (4,4) | +0.16 | +0.00 | +0.04 | ok | (4,4) | +0.16 | +0.00 | +0.04 | ok (alias) | +0.27 | - |
| hexatriene-x1 | 1 | V | 5.37 | (8,13) | +1.18 | -0.46 | +0.24 | ok, not good | (6,6) | +1.37 | +1.44 | +1.47 | ok, not good | (6,6) | +1.37 | +1.44 | +1.47 | ok (alias), not good | +1.18 | - |
| hexatriene-x2 | 1 | V | 5.62 | (8,13) | +0.15 | +0.00 | +0.04 | ok | (6,6) | -0.00 | +0.01 | +0.04 | ok | (6,6) | -0.00 | +0.01 | +0.04 | ok (alias) | +0.16 | - |
| hexatriene-x3 | 1 | R | 5.79 | (8,13) | -0.22 | -0.27 | +0.11 | ok | (6,6) | - | - | - | unrepresentable | (6,6) | - | - | - | unrepresentable (alias) | -0.22 | - |
| hexatriene-x4 | 1 | R | 5.94 | (8,13) | -0.13 | -0.36 | +0.16 | ok | (6,6) | - | - | - | unrepresentable | (6,6) | - | - | - | unrepresentable (alias) | -0.13 | - |
| hexatriene-x5 | 3 | V | 2.73 | (8,13) | +0.25 | +0.14 | +0.09 | ok | (6,6) | +0.09 | +0.12 | +0.10 | ok | (6,6) | +0.09 | +0.12 | +0.10 | ok (alias) | +0.25 | - |
| hexatriene-x6 | 3 | V | 4.36 | (8,13) | +0.01 | +0.16 | +0.19 | ok | (6,6) | -0.00 | +0.16 | +0.17 | ok | (6,6) | -0.00 | +0.16 | +0.17 | ok (alias) | +0.01 | - |
| hpo-x1 | 1 | V | 2.47 | (12,12) | +0.48 | +0.02 | +0.10 | ok | (6,4) | -0.07 | +0.02 | +0.24 | ok | (6,4) | -0.07 | +0.02 | +0.24 | ok (alias) | +0.39 | - |
| hps-x1 | 1 | V | 1.59 | (12,12) | +0.09 | +0.01 | +0.03 | ok | (6,4) | -0.01 | +0.02 | +0.07 | ok | (6,4) | -0.01 | +0.02 | +0.07 | ok (alias) | +0.09 | - |
| hsif-x1 | 1 | V | 3.05 | (10,12) | -0.05 | -0.16 | -0.00 | ok | (2,2) | - | - | - | unrepresentable | (2,2) | - | - | - | unrepresentable (alias) | -0.02 | - |
| hydrogen_chloride-x1 | 1 | CT | 7.84 | (8,13) | +0.03 | -0.12 | +0.07 | ok | (8,5) | -0.16 | -0.06 | +0.04 | ok | (8,5) | -0.16 | -0.06 | +0.04 | ok (alias) | -0.05 | - |
| hydrogen_sulfide-x1 | 1 | R | 6.18 | (8,13) | +0.38 | +0.01 | +0.10 | ok | (8,6) | +0.02 | -0.05 | +0.05 | ok | (8,6) | +0.02 | -0.05 | +0.05 | ok (alias) | +0.38 | - |
| hydrogen_sulfide-x2 | 1 | R | 6.24 | (8,13) | -0.17 | -0.17 | -0.00 | ok | (8,6) | -0.37 | -0.16 | -0.09 | ok | (8,6) | -0.37 | -0.16 | -0.09 | ok (alias) | -0.17 | - |
| hydrogen_sulfide-x3 | 3 | R | 5.81 | (8,13) | +0.39 | +0.00 | +0.11 | ok | (8,6) | -0.08 | -0.02 | +0.03 | ok | (8,6) | -0.08 | -0.02 | +0.03 | ok (alias) | +0.39 | - |
| hydrogen_sulfide-x4 | 3 | R | 5.88 | (8,13) | -0.13 | -0.15 | +0.01 | ok | (8,6) | -0.26 | -0.14 | -0.03 | ok | (8,6) | -0.26 | -0.14 | -0.03 | ok (alias) | -0.13 | - |
| imidazole-x1 | 1 | R | 5.71 | (8,12) | -0.67 | -0.12 | +0.18 | ok | (6,5) | - | - | - | unrepresentable | (6,5) | - | - | - | unrepresentable (alias) | -0.67 | - |
| imidazole-x2 | 1 | V | 6.41 | (8,12) | +0.39 | +0.12 | +0.34 | ok | (6,5) | +0.45 | +0.34 | +0.52 | ok | (6,5) | +0.45 | +0.34 | +0.52 | ok (alias) | +0.51 | - |
| imidazole-x3 | 1 | V | 6.50 | (8,12) | -1.16 | -0.44 | +0.31 | ok, not good | (6,5) | - | - | - | unrepresentable | (6,5) | - | - | - | unrepresentable (alias) | -1.05 | - |
| imidazole-x4 | 1 | R | 6.83 | (8,12) | +0.26 | +0.04 | +0.28 | ok | (8,6) | +0.12 | -0.04 | +0.08 | ok | (8,6) | +0.12 | -0.04 | +0.08 | ok (alias) | +0.26 | - |
| imidazole-x5 | 3 | V | 4.73 | (8,12) | -0.22 | +0.07 | +0.16 | ok | (6,5) | -0.24 | +0.09 | +0.26 | ok | (6,5) | -0.24 | +0.09 | +0.26 | ok (alias) | -0.22 | - |
| imidazole-x6 | 3 | R | 5.66 | (8,12) | -0.65 | -0.12 | +0.20 | ok | (6,5) | - | - | - | unrepresentable | (6,5) | - | - | - | unrepresentable (alias) | -0.65 | - |
| imidazole-x7 | 3 | V | 5.74 | (8,12) | -0.00 | +0.06 | +0.18 | ok | (6,5) | +0.05 | +0.22 | +0.39 | ok | (6,5) | +0.05 | +0.22 | +0.39 | ok (alias) | +0.17 | - |
| imidazole-x8 | 3 | V | 6.31 | (8,12) | -1.00 | -0.31 | +0.46 | ok | (8,6) | +1.35 | +0.99 | +1.12 | ok, not good | (8,6) | +1.35 | +0.99 | +1.12 | ok (alias), not good | -0.90 | - |
| isobutene-x1 | 1 | R | 6.46 | (10,12) | +2.54 | +2.16 | +2.66 | ok, not good | (2,2) | - | - | - | unrepresentable | (2,2) | - | - | - | unrepresentable (alias) | +2.54 | - |
| isobutene-x2 | 1 | R | 7.01 | (10,12) | -0.23 | -0.38 | +0.17 | ok | (2,2) | -0.76 | -0.20 | +0.29 | ok | (2,2) | -0.76 | -0.20 | +0.29 | ok (alias) | -0.23 | - |
| isobutene-x3 | 3 | V | 4.53 | (10,12) | -0.11 | +0.05 | +0.11 | ok | (2,2) | -0.19 | +0.08 | +0.21 | ok | (2,2) | -0.19 | +0.08 | +0.21 | ok (alias) | -0.11 | - |
| ketene-x1 | 1 | V | 3.85 | (12,12) | +0.35 | +0.13 | +0.10 | ok | (6,5) | -0.08 | +0.16 | +0.18 | ok | (6,5) | -0.08 | +0.16 | +0.18 | ok (alias) | +0.35 | - |
| ketene-x2 | 1 | R | 6.01 | (12,12) | -0.43 | -0.13 | +0.06 | ok | (6,5) | - | - | - | unrepresentable | (6,5) | - | - | - | unrepresentable (alias) | -0.43 | - |
| ketene-x3 | 1 | V | 7.25 | (12,12) | -0.51 | -0.24 | +0.23 | ok | (6,5) | +1.48 | +0.41 | +0.78 | ok, not good | (6,5) | +1.48 | +0.41 | +0.78 | ok (alias), not good | -0.51 | - |
| ketene-x4 | 1 | R | 7.18 | (12,12) | +2.13 | +1.90 | +2.00 | ok, not good | (6,5) | +1.69 | +1.86 | +2.09 | ok, not good | (6,5) | +1.69 | +1.86 | +2.09 | ok (alias), not good | +2.00 | - |
| ketene-x5 | 3 | V | 3.77 | (12,12) | +0.38 | +0.04 | +0.07 | ok | (6,5) | -0.14 | +0.05 | +0.15 | ok | (6,5) | -0.14 | +0.05 | +0.15 | ok (alias) | +0.38 | - |
| ketene-x6 | 3 | V | 5.61 | (12,12) | +0.19 | +0.07 | +0.10 | ok | (6,5) | -0.13 | +0.03 | +0.15 | ok | (6,5) | -0.13 | +0.03 | +0.15 | ok (alias) | +0.15 | - |
| ketene-x7 | 3 | R | 5.79 | (12,12) | -0.44 | -0.11 | +0.06 | ok | (6,5) | - | - | - | unrepresentable | (6,5) | - | - | - | unrepresentable (alias) | -0.38 | - |
| ketene-x8 | 3 | R | 7.12 | (12,12) | +1.54 | +1.42 | +1.57 | ok, not good | (6,5) | +1.19 | +1.41 | +1.64 | ok, not good | (6,5) | +1.19 | +1.41 | +1.64 | ok (alias), not good | +1.44 | - |
| maleimide-x1 | 1 | V | 3.80 | (12,12) | +3.17 | +3.71 | +4.05 | ok, not good | (12,9) | +0.80 | +0.11 | +0.08 | ok | (12,9) | +0.80 | +0.11 | +0.08 | ok (alias) | +3.08 | - |
| maleimide-x2 | 1 | V | 4.52 | (12,12) | +3.57 | +4.07 | +4.63 | ok, not good | (12,9) | +0.54 | +0.08 | +0.12 | ok | (12,9) | +0.54 | +0.08 | +0.12 | ok (alias) | +0.75 | - |
| maleimide-x3 | 1 | V | 4.89 | (12,12) | +0.94 | -0.23 | -0.11 | ok | (8,7) | +0.82 | -0.14 | -0.08 | ok | (8,7) | +0.82 | -0.14 | -0.08 | ok (alias) | +0.94 | - |
| maleimide-x4 | 1 | V | 6.21 | (12,12) | +1.37 | -0.77 | -0.03 | ok, not good | (8,7) | +1.55 | -0.78 | -0.10 | ok, not good | (8,7) | +1.55 | -0.78 | -0.10 | ok (alias), not good | +1.37 | - |
| maleimide-x5 | 1 | R | 7.20 | (12,12) | +2.74 | +2.15 | +2.44 | ok, not good | (12,9) | +2.75 | +2.07 | +2.34 | ok, not good | (12,9) | +2.75 | +2.07 | +2.34 | ok (alias), not good | +2.74 | - |
| maleimide-x6 | 3 | V | 3.57 | (12,12) | +3.27 | +3.85 | +4.21 | ok, not good | (12,9) | +0.82 | +0.07 | +0.06 | ok | (12,9) | +0.82 | +0.07 | +0.06 | ok (alias) | +3.31 | - |
| maleimide-x7 | 3 | V | 3.74 | (12,12) | +0.06 | +0.14 | +0.23 | ok | (8,7) | +0.04 | +0.11 | +0.18 | ok | (8,7) | +0.04 | +0.11 | +0.18 | ok (alias) | +0.02 | - |
| maleimide-x8 | 3 | V | 4.24 | (12,12) | +0.72 | +0.01 | +0.02 | ok | (8,7) | +0.81 | +0.14 | -0.03 | ok | (8,7) | +0.81 | +0.14 | -0.03 | ok (alias) | +0.87 | - |
| maleimide-x9 | 3 | V | 4.32 | (12,12) | +3.76 | +4.25 | +4.81 | ok, not good | (12,9) | +0.57 | +0.04 | +0.12 | ok | (12,9) | +0.57 | +0.04 | +0.12 | ok (alias) | +5.55 | - |
| methanimine-x1 | 1 | V | 5.23 | (12,12) | +0.75 | +0.05 | +0.10 | ok | (4,3) | +0.14 | -0.04 | +0.11 | ok | (4,3) | +0.14 | -0.04 | +0.11 | ok (alias) | +0.75 | - |
| methanimine-x2 | 3 | V | 4.65 | (12,12) | +0.75 | +0.11 | +0.11 | ok | (4,3) | +0.12 | -0.04 | +0.02 | ok | (4,3) | +0.12 | -0.04 | +0.02 | ok (alias) | +0.75 | - |
| methylenecyclopropene-x1 | 1 | V | 4.28 | (12,12) | -0.03 | +0.12 | +0.22 | ok | (4,4) | +0.19 | +0.12 | +0.12 | ok | (4,4) | +0.19 | +0.12 | +0.12 | ok (alias) | -0.03 | - |
| methylenecyclopropene-x2 | 1 | R | 5.44 | (12,12) | -0.84 | -0.07 | +0.19 | ok | (4,4) | - | - | - | unrepresentable | (4,4) | - | - | - | unrepresentable (alias) | -0.85 | - |
| methylenecyclopropene-x3 | 1 | R | 5.96 | (12,12) | -0.62 | -0.20 | +0.13 | ok | (4,4) | - | - | - | unrepresentable | (4,4) | - | - | - | unrepresentable (alias) | -0.77 | - |
| methylenecyclopropene-x4 | 1 | V | 6.12 | (12,12) | -0.48 | -0.13 | +0.20 | ok | (4,4) | -0.49 | -0.14 | +0.13 | ok | (4,4) | -0.49 | -0.14 | +0.13 | ok (alias) | -0.66 | - |
| methylenecyclopropene-x5 | 3 | V | 3.49 | (12,12) | -0.03 | +0.11 | +0.12 | ok | (4,4) | -0.05 | +0.15 | +0.18 | ok | (4,4) | -0.05 | +0.15 | +0.18 | ok (alias) | -0.11 | - |
| methylenecyclopropene-x6 | 3 | V | 4.74 | (12,12) | -0.05 | +0.13 | +0.19 | ok | (4,4) | -0.06 | +0.11 | +0.17 | ok | (4,4) | -0.06 | +0.11 | +0.17 | ok (alias) | -0.05 | - |
| naphthalene-x1 | 1 | V | 4.27 | (12,12) | +0.76 | +0.43 | +0.30 | ok | (10,10) | +0.00 | +0.15 | +0.24 | ok | (10,10) | +0.00 | +0.15 | +0.24 | ok (alias) | +0.76 | - |
| naphthalene-x2 | 1 | V | 4.90 | (12,12) | +0.95 | -0.52 | -0.13 | ok | (10,10) | +1.36 | -0.75 | -0.55 | ok, not good | (10,10) | +1.36 | -0.75 | -0.55 | ok (alias), not good | +0.95 | - |
| naphthalene-x3 | 1 | R | 5.65 | (12,12) | -0.41 | -0.16 | +0.26 | ok | (10,10) | - | - | - | unrepresentable | (10,10) | - | - | - | unrepresentable (alias) | -0.41 | - |
| naphthalene-x4 | 1 | V | 5.84 | (12,12) | +0.72 | -0.08 | +0.13 | ok | (10,10) | +0.64 | +0.27 | +0.38 | ok | (10,10) | +0.64 | +0.27 | +0.38 | ok (alias) | +0.72 | - |
| naphthalene-x5 | 1 | V | 5.89 | (12,12) | +1.10 | +0.62 | +0.50 | ok | (10,10) | +0.01 | +0.33 | +0.44 | ok | (10,10) | +0.01 | +0.33 | +0.44 | ok (alias) | +1.10 | - |
| naphthalene-x6 | 1 | R | 6.07 | (12,12) | +3.31 | +1.14 | +0.95 | ok, not good | (10,10) | - | - | - | unrepresentable | (10,10) | - | - | - | unrepresentable (alias) | +3.31 | - |
| naphthalene-x7 | 1 | R | 6.09 | (12,12) | +2.78 | +1.16 | +1.19 | ok, not good | (10,10) | - | - | - | unrepresentable | (10,10) | - | - | - | unrepresentable (alias) | +2.78 | - |
| naphthalene-x8 | 1 | V | 6.19 | (12,12) | +0.61 | +0.51 | +1.02 | ok | (10,10) | +1.76 | +1.72 | +1.84 | ok, not good | (10,10) | +1.76 | +1.72 | +1.84 | ok (alias), not good | +0.61 | - |
| naphthalene-x9 | 1 | R | 6.33 | (12,12) | -0.34 | -0.02 | +0.28 | ok | (10,10) | - | - | - | unrepresentable | (10,10) | - | - | - | unrepresentable (alias) | -0.34 | - |
| naphthalene-x10 | 1 | V | 6.42 | (12,12) | +0.69 | +0.68 | +1.23 | ok | (10,10) | +1.41 | -0.69 | -0.34 | ok, not good | (10,10) | +1.41 | -0.69 | -0.34 | ok (alias), not good | +0.69 | - |
| naphthalene-x11 | 1 | V | 6.48 | - | - | - | - | wall_cap | (10,10) | +1.08 | +1.15 | +1.32 | ok | (10,10) | +1.08 | +1.15 | +1.32 | ok (alias) | +1.29 | - |
| naphthalene-x12 | 1 | V | 6.87 | (12,12) | +1.23 | +0.16 | +0.23 | ok, not good | (10,10) | +0.03 | -0.02 | +0.08 | ok | (10,10) | +0.03 | -0.02 | +0.08 | ok (alias) | +1.23 | - |
| naphthalene-x13 | 3 | V | 3.17 | (12,12) | +0.17 | +0.09 | +0.14 | ok | (10,10) | -0.09 | +0.16 | +0.20 | ok | (10,10) | -0.09 | +0.16 | +0.20 | ok (alias) | +0.17 | - |
| naphthalene-x14 | 3 | V | 4.16 | (12,12) | +0.64 | +0.09 | +0.14 | ok | (10,10) | +0.17 | +0.08 | +0.14 | ok | (10,10) | +0.17 | +0.08 | +0.14 | ok (alias) | +0.64 | - |
| naphthalene-x15 | 3 | V | 4.48 | (12,12) | +0.07 | +0.09 | +0.11 | ok | (10,10) | -0.04 | +0.17 | +0.23 | ok | (10,10) | -0.04 | +0.17 | +0.23 | ok (alias) | +0.07 | - |
| naphthalene-x16 | 3 | V | 4.64 | (12,12) | +0.69 | +0.34 | +0.28 | ok | (10,10) | +0.02 | +0.03 | +0.13 | ok | (10,10) | +0.02 | +0.03 | +0.13 | ok (alias) | +0.69 | - |
| naphthalene-x17 | 3 | V | 4.95 | (12,12) | -0.19 | -0.72 | -0.66 | ok | (10,10) | -0.69 | -0.76 | -0.67 | ok | (10,10) | -0.69 | -0.76 | -0.67 | ok (alias) | -0.19 | - |
| naphthalene-x18 | 3 | V | 5.49 | (12,12) | +0.83 | +0.21 | +0.30 | ok | (10,10) | +0.13 | +0.21 | +0.28 | ok | (10,10) | +0.13 | +0.21 | +0.28 | ok (alias) | +0.83 | - |
| naphthalene-x19 | 3 | V | 6.17 | (12,12) | +1.29 | -0.41 | -0.04 | ok, not good | (10,10) | +0.48 | +0.69 | +0.79 | ok | (10,10) | +0.48 | +0.69 | +0.79 | ok (alias) | +1.29 | - |
| naphthalene-x20 | 3 | V | 6.39 | (12,12) | +1.18 | -0.09 | +0.19 | ok, not good | (10,10) | +0.07 | +0.20 | +0.31 | ok | (10,10) | +0.07 | +0.20 | +0.31 | ok (alias) | +1.17 | - |
| nitrosomethane-x1 | 1 | V | 1.96 | (10,12) | +0.75 | +0.27 | +0.20 | ok | (6,4) | +0.02 | -0.01 | -0.02 | ok | (6,4) | +0.02 | -0.01 | -0.02 | ok (alias) | +0.77 | - |
| nitrosomethane-x2 | 1 | V | 4.76 | (10,12) | +0.75 | -0.07 | +0.01 | ok | (6,4) | -0.22 | -0.19 | +0.05 | ok | (6,4) | -0.22 | -0.19 | +0.05 | ok (alias) | +5.22 | - |
| nitrosomethane-x3 | 1 | R | 6.29 | (10,12) | -0.07 | -0.08 | +0.15 | ok | (8,5) | +5.62 | +3.03 | +2.87 | ok, not good | (8,5) | +5.62 | +3.03 | +2.87 | ok (alias), not good | -0.08 | - |
| nitrosomethane-x4 | 3 | V | 1.16 | (10,12) | +1.26 | +0.25 | +0.12 | ok, not good | (6,4) | +0.12 | +0.06 | -0.11 | ok | (6,4) | +0.12 | +0.06 | -0.11 | ok (alias) | +0.84 | - |
| nitrosomethane-x5 | 3 | V | 5.60 | (10,12) | -0.06 | -0.01 | -0.08 | ok | (2,2) | -0.70 | -0.06 | +0.15 | ok | (2,2) | -0.70 | -0.06 | +0.15 | ok (alias) | -0.06 | - |
| nitroxyl-x1 | 1 | V | 1.74 | (12,12) | +0.31 | +0.06 | +0.06 | ok | (6,4) | +0.08 | -0.02 | -0.03 | ok | (6,4) | +0.08 | -0.02 | -0.03 | ok (alias) | +0.31 | - |
| nitroxyl-x2 | 1 | V | 4.33 | (12,12) | +0.41 | -0.09 | +0.05 | ok | (6,4) | -0.06 | -0.18 | +0.04 | ok | (6,4) | -0.06 | -0.18 | +0.04 | ok (alias) | +0.41 | - |
| nitroxyl-x3 | 1 | R | 6.27 | (12,12) | -0.61 | -0.24 | -0.06 | ok | (8,5) | +6.51 | +3.87 | +3.65 | ok, not good | (8,5) | +6.51 | +3.87 | +3.65 | ok (alias), not good | -0.56 | - |
| nitroxyl-x4 | 3 | V | 0.88 | (12,12) | +0.24 | +0.14 | +0.05 | ok | (6,4) | +0.22 | +0.09 | -0.09 | ok | (6,4) | +0.22 | +0.09 | -0.09 | ok (alias) | +0.24 | - |
| nitroxyl-x5 | 3 | V | 5.61 | (12,12) | +0.12 | +0.19 | +0.05 | ok | (2,2) | -0.73 | -0.07 | +0.12 | ok | (2,2) | -0.73 | -0.07 | +0.12 | ok (alias) | +0.12 | - |
| octatetraene-x1 | 1 | V | 4.78 | (10,12) | +1.11 | +0.17 | +0.54 | ok, not good | (8,8) | +1.29 | +1.27 | +1.27 | ok, not good | (8,8) | +1.29 | +1.27 | +1.27 | ok (alias), not good | +1.11 | - |
| octatetraene-x2 | 1 | V | 4.90 | (10,12) | +0.00 | -0.11 | -0.07 | ok | (8,8) | -0.02 | -0.09 | -0.09 | ok | (8,8) | -0.02 | -0.09 | -0.09 | ok (alias) | +0.00 | - |
| octatetraene-x3 | 3 | V | 2.36 | (10,12) | +0.14 | +0.10 | +0.09 | ok | (8,8) | +0.12 | +0.10 | +0.06 | ok | (8,8) | +0.12 | +0.10 | +0.06 | ok (alias) | +0.14 | - |
| octatetraene-x4 | 3 | V | 3.73 | (10,12) | +0.07 | +0.12 | +0.12 | ok | (8,8) | +0.06 | +0.13 | +0.11 | ok | (8,8) | +0.06 | +0.13 | +0.11 | ok (alias) | +0.07 | - |
| propynal-x1 | 1 | V | 3.80 | (12,12) | -0.22 | -0.01 | +0.10 | ok | (10,8) | -0.05 | -0.01 | +0.14 | ok | (10,8) | -0.05 | -0.01 | +0.14 | ok (alias) | -0.17 | - |
| propynal-x2 | 1 | V | 5.54 | (12,12) | +2.52 | +1.82 | +2.06 | ok, not good | (10,8) | +0.98 | +0.08 | -0.04 | ok | (10,8) | +0.98 | +0.08 | -0.04 | ok (alias) | +0.50 | - |
| propynal-x3 | 3 | V | 3.47 | (12,12) | -0.16 | -0.04 | +0.10 | ok | (10,8) | -0.03 | -0.04 | +0.10 | ok | (10,8) | -0.03 | -0.04 | +0.10 | ok (alias) | -0.19 | - |
| propynal-x4 | 3 | V | 4.47 | (12,12) | +0.20 | +0.17 | +0.28 | ok | (6,6) | +0.22 | +0.09 | +0.18 | ok | (6,6) | +0.22 | +0.09 | +0.18 | ok (alias) | +0.39 | - |
| pyrazine-x1 | 1 | V | 4.15 | (18,13) | +0.69 | -0.10 | +0.02 | ok | (10,8) | +0.61 | +0.02 | +0.07 | ok | (10,8) | +0.61 | +0.02 | +0.07 | ok (alias) | +0.69 | - |
| pyrazine-x2 | 1 | V | 4.98 | (18,13) | +1.06 | -0.01 | +0.01 | ok | (10,8) | +0.92 | -0.11 | -0.17 | ok | (10,8) | +0.92 | -0.11 | -0.17 | ok (alias) | +1.06 | - |
| pyrazine-x3 | 1 | V | 5.02 | (18,13) | +0.84 | +0.34 | +0.14 | ok | (6,6) | -0.05 | +0.20 | +0.34 | ok | (6,6) | -0.05 | +0.20 | +0.34 | ok (alias) | +0.84 | - |
| pyrazine-x4 | 1 | V | 5.71 | (18,13) | +0.36 | -0.14 | +0.08 | ok | (10,8) | +0.09 | +0.02 | +0.20 | ok | (10,8) | +0.09 | +0.02 | +0.20 | ok (alias) | +0.36 | - |
| pyrazine-x5 | 1 | R | 6.65 | (18,13) | +2.66 | +2.12 | +2.24 | ok, not good | (10,8) | +1.83 | +2.17 | +2.36 | ok, not good | (10,8) | +1.83 | +2.17 | +2.36 | ok (alias), not good | +2.66 | - |
| pyrazine-x6 | 1 | V | 6.74 | (18,13) | +0.80 | -0.05 | +0.12 | ok | (10,8) | +0.42 | -0.07 | +0.05 | ok | (10,8) | +0.42 | -0.07 | +0.05 | ok (alias) | +0.80 | - |
| pyrazine-x7 | 1 | V | 6.88 | (18,13) | +0.82 | -0.52 | +0.13 | ok | (6,6) | +1.40 | -0.87 | -0.39 | ok, not good | (6,6) | +1.40 | -0.87 | -0.39 | ok (alias), not good | +0.82 | - |
| pyrazine-x8 | 1 | R | 7.21 | (18,13) | +3.18 | +1.71 | +1.56 | ok, not good | (10,8) | +3.13 | +1.31 | +1.33 | ok, not good | (10,8) | +3.13 | +1.31 | +1.33 | ok (alias), not good | +3.18 | - |
| pyrazine-x9 | 1 | R | 7.24 | (18,13) | +0.48 | +0.77 | +1.04 | ok | (10,8) | +2.71 | -0.09 | +0.30 | ok, not good | (10,8) | +2.71 | -0.09 | +0.30 | ok (alias), not good | +0.48 | - |
| pyrazine-x10 | 1 | R | 7.44 | (18,13) | +1.71 | +1.97 | +2.44 | ok, not good | (10,8) | +2.62 | -0.31 | +0.25 | ok, not good | (10,8) | +2.62 | -0.31 | +0.25 | ok (alias), not good | +1.71 | - |
| pyrazine-x11 | 1 | V | 7.98 | (18,13) | +1.24 | +1.59 | +1.95 | ok, not good | (10,8) | +4.63 | +4.84 | +5.31 | ok, not good | (10,8) | +4.63 | +4.84 | +5.31 | ok (alias), not good | +1.24 | - |
| pyrazine-x12 | 1 | V | 8.04 | (18,13) | +1.25 | +0.80 | +0.83 | ok, not good | (10,8) | +3.74 | +2.44 | +2.45 | ok, not good | (10,8) | +3.74 | +2.44 | +2.45 | ok (alias), not good | +1.25 | - |
| pyrazine-x13 | 1 | V | 8.69 | (18,13) | +2.81 | +3.21 | +3.57 | ok, not good | (10,8) | +3.25 | +1.94 | +1.68 | ok, not good | (10,8) | +3.25 | +1.94 | +1.68 | ok (alias), not good | +2.81 | - |
| pyrazine-x14 | 3 | V | 3.59 | (18,13) | +0.90 | +0.08 | +0.08 | ok | (10,8) | +0.57 | +0.02 | +0.01 | ok | (10,8) | +0.57 | +0.02 | +0.01 | ok (alias) | +0.90 | - |
| pyrazine-x15 | 3 | V | 4.35 | (18,13) | +0.39 | +0.31 | +0.26 | ok | (6,6) | -0.35 | +0.21 | +0.32 | ok | (6,6) | -0.35 | +0.21 | +0.32 | ok (alias) | +0.39 | - |
| pyrazine-x16 | 3 | V | 4.39 | (18,13) | +0.19 | +0.04 | +0.17 | ok | (6,6) | +0.23 | +0.08 | +0.06 | ok | (6,6) | +0.23 | +0.08 | +0.06 | ok (alias) | +0.19 | - |
| pyrazine-x17 | 3 | V | 4.93 | (18,13) | +0.99 | -0.06 | +0.00 | ok | (10,8) | +0.92 | -0.11 | -0.14 | ok | (10,8) | +0.92 | -0.11 | -0.14 | ok (alias) | +0.99 | - |
| pyrazine-x18 | 3 | V | 5.08 | (18,13) | +0.72 | +0.14 | +0.25 | ok | (10,8) | +0.17 | +0.05 | +0.16 | ok | (10,8) | +0.17 | +0.05 | +0.16 | ok (alias) | +0.72 | - |
| pyrazine-x19 | 3 | V | 5.28 | (18,13) | +0.29 | +0.01 | +0.16 | ok | (6,6) | -0.04 | +0.05 | +0.18 | ok | (6,6) | -0.04 | +0.05 | +0.18 | ok (alias) | +0.29 | - |
| pyridazine-x1 | 1 | V | 3.83 | (12,12) | +3.00 | +3.98 | +4.43 | ok, not good | (10,8) | +0.46 | -0.04 | +0.00 | ok | (10,8) | +0.46 | -0.04 | +0.00 | ok (alias) | - | - |
| pyridazine-x2 | 1 | V | 4.37 | (10,12) | +2.60 | +3.11 | +3.46 | ok, not good | (10,8) | +0.46 | +0.05 | +0.06 | ok | (10,8) | +0.46 | +0.05 | +0.06 | ok (alias) | - | - |
| pyridazine-x3 | 1 | V | 5.26 | (10,12) | +0.90 | +0.80 | +0.78 | ok | (6,6) | -0.14 | +0.19 | +0.34 | ok | (6,6) | -0.14 | +0.19 | +0.34 | ok (alias) | +0.91 | - |
| pyridazine-x4 | 1 | V | 5.72 | (10,12) | +1.75 | +2.37 | +3.11 | ok, not good | (10,8) | +0.54 | +0.10 | +0.22 | ok | (10,8) | +0.54 | +0.10 | +0.22 | ok (alias) | +0.88 | - |
| pyridazine-x5 | 1 | R | 6.17 | (28,17) | +1.22 | +0.55 | +0.88 | ok, not good | (10,8) | +1.73 | +1.56 | +1.73 | ok, not good | (10,8) | +1.73 | +1.56 | +1.73 | ok (alias), not good | +1.21 | - |
| pyridazine-x6 | 1 | V | 6.37 | (10,12) | +0.93 | +1.47 | +2.20 | ok | (10,8) | +0.79 | +0.21 | +0.33 | ok | (10,8) | +0.79 | +0.21 | +0.33 | ok (alias) | +0.70 | - |
| pyridazine-x7 | 1 | V | 6.75 | (10,12) | +1.99 | +0.34 | +1.09 | ok, not good | (10,8) | +1.16 | +0.79 | +0.91 | ok, not good | (10,8) | +1.16 | +0.79 | +0.91 | ok (alias), not good | +1.32 | - |
| pyridazine-x8 | 3 | V | 3.19 | (26,16) | +0.52 | +0.24 | +0.24 | ok | (10,8) | +0.41 | +0.05 | -0.03 | ok | (10,8) | +0.41 | +0.05 | -0.03 | ok (alias) | +1.73 | - |
| pyridazine-x9 | 3 | V | 4.11 | (26,16) | +0.27 | +0.00 | +0.14 | ok | (10,8) | +0.38 | +0.06 | +0.06 | ok | (10,8) | +0.38 | +0.06 | +0.06 | ok (alias) | +0.27 | - |
| pyridazine-x10 | 3 | V | 4.34 | (10,12) | +0.27 | +0.54 | +0.63 | ok | (6,6) | -0.41 | +0.19 | +0.32 | ok | (6,6) | -0.41 | +0.19 | +0.32 | ok (alias) | +0.25 | - |
| pyridazine-x11 | 3 | V | 4.82 | (10,12) | +0.53 | +0.27 | +0.32 | ok | (6,6) | +0.11 | +0.09 | +0.15 | ok | (6,6) | +0.11 | +0.09 | +0.15 | ok (alias) | +0.53 | - |
| pyridine-x1 | 1 | V | 4.95 | (8,13) | +2.10 | +2.40 | +2.83 | ok, not good | (8,7) | +0.25 | +0.09 | +0.24 | ok | (8,7) | +0.25 | +0.09 | +0.24 | ok (alias) | +2.05 | - |
| pyridine-x2 | 1 | V | 5.14 | (10,12) | +0.09 | +0.16 | +0.23 | ok | (6,6) | -0.07 | +0.20 | +0.33 | ok | (6,6) | -0.07 | +0.20 | +0.33 | ok (alias) | +0.09 | - |
| pyridine-x3 | 1 | V | 5.40 | (8,13) | +0.85 | +1.29 | +1.70 | ok | (8,7) | +0.56 | -0.02 | -0.04 | ok | (8,7) | +0.56 | -0.02 | -0.04 | ok (alias) | +0.82 | - |
| pyridine-x4 | 1 | V | 6.62 | (10,12) | +1.18 | -0.18 | +0.11 | ok, not good | (6,6) | +1.28 | +0.03 | +0.18 | ok, not good | (6,6) | +1.28 | +0.03 | +0.18 | ok (alias), not good | +1.18 | - |
| pyridine-x5 | 1 | R | 6.76 | (8,13) | +1.92 | +1.69 | +1.82 | ok, not good | (8,7) | +1.72 | +1.45 | +1.61 | ok, not good | (8,7) | +1.72 | +1.45 | +1.61 | ok (alias), not good | +1.97 | - |
| pyridine-x6 | 1 | R | 6.82 | (10,12) | -0.19 | +0.31 | +1.08 | ok | (8,7) | +3.68 | +2.67 | +3.03 | ok, not good | (8,7) | +3.68 | +2.67 | +3.03 | ok (alias), not good | -0.19 | - |
| pyridine-x7 | 1 | R | 7.38 | (10,12) | -0.62 | -0.26 | +0.44 | ok | (8,7) | +1.80 | +1.72 | +2.01 | ok, not good | (8,7) | +1.80 | +1.72 | +2.01 | ok (alias), not good | -0.62 | - |
| pyridine-x8 | 1 | V | 7.39 | (8,13) | +1.29 | +1.11 | +1.24 | ok, not good | (8,7) | +1.08 | +1.03 | +1.19 | ok | (8,7) | +1.08 | +1.03 | +1.19 | ok (alias) | +1.36 | - |
| pyridine-x9 | 1 | V | 7.40 | (10,12) | +0.93 | +0.76 | +0.99 | ok | (8,7) | +0.86 | +1.06 | +1.27 | ok | (8,7) | +0.86 | +1.06 | +1.27 | ok (alias) | +0.94 | - |
| pyridine-x10 | 3 | V | 4.30 | (10,12) | -0.14 | +0.19 | +0.20 | ok | (6,6) | -0.32 | +0.21 | +0.31 | ok | (6,6) | -0.32 | +0.21 | +0.31 | ok (alias) | -0.14 | - |
| pyridine-x11 | 3 | V | 4.46 | (8,13) | +2.53 | +2.82 | +3.26 | ok, not good | (8,7) | +0.19 | +0.05 | +0.13 | ok | (8,7) | +0.19 | +0.05 | +0.13 | ok (alias) | +2.49 | - |
| pyridine-x12 | 3 | V | 4.79 | (10,12) | +0.19 | +0.02 | +0.09 | ok | (6,6) | +0.17 | +0.08 | +0.14 | ok | (6,6) | +0.17 | +0.08 | +0.14 | ok (alias) | +0.21 | - |
| pyridine-x13 | 3 | V | 5.04 | (8,13) | +0.22 | +0.09 | +0.16 | ok | (6,6) | +0.07 | +0.08 | +0.18 | ok | (6,6) | +0.07 | +0.08 | +0.18 | ok (alias) | +0.21 | - |
| pyridine-x14 | 3 | V | 5.36 | (8,13) | +0.84 | +1.27 | +1.68 | ok | (8,7) | +0.58 | +0.01 | +0.00 | ok | (8,7) | +0.58 | +0.01 | +0.00 | ok (alias) | +0.82 | - |
| pyridine-x15 | 3 | V | 6.24 | (8,13) | +0.99 | +0.07 | +0.20 | ok | (6,6) | +0.99 | +0.73 | +0.81 | ok | (6,6) | +0.99 | +0.73 | +0.81 | ok (alias) | +0.93 | - |
| pyrimidine-x1 | 1 | V | 4.44 | (10,12) | +2.17 | +3.03 | +3.38 | ok, not good | (10,8) | +0.41 | +0.09 | +0.15 | ok | (10,8) | +0.41 | +0.09 | +0.15 | ok (alias) | +1.48 | - |
| pyrimidine-x2 | 1 | V | 4.85 | (10,12) | +2.01 | +0.17 | +0.08 | ok, not good | (10,8) | +0.67 | +0.02 | +0.04 | ok | (10,8) | +0.67 | +0.02 | +0.04 | ok (alias) | +2.01 | - |
| pyrimidine-x3 | 1 | V | 5.38 | (10,12) | +1.04 | +0.51 | +0.47 | ok | (6,6) | -0.13 | +0.19 | +0.35 | ok | (6,6) | -0.13 | +0.19 | +0.35 | ok (alias) | +0.93 | - |
| pyrimidine-x4 | 1 | V | 5.92 | (10,12) | +1.73 | +2.53 | +2.85 | ok, not good | (10,8) | +0.78 | +0.09 | +0.17 | ok | (10,8) | +0.78 | +0.09 | +0.17 | ok (alias) | +1.73 | - |
| pyrimidine-x5 | 1 | V | 6.26 | (10,12) | +0.60 | +1.42 | +1.49 | ok | (10,8) | +0.94 | +0.17 | +0.22 | ok | (10,8) | +0.94 | +0.17 | +0.22 | ok (alias) | +0.66 | - |
| pyrimidine-x6 | 1 | R | 6.70 | (10,12) | +2.49 | +1.72 | +2.15 | ok, not good | (10,8) | +1.89 | +2.29 | +2.54 | ok, not good | (10,8) | +1.89 | +2.29 | +2.54 | ok (alias), not good | +2.40 | - |
| pyrimidine-x7 | 1 | V | 6.88 | (10,12) | +0.93 | -0.14 | +0.22 | ok | (6,6) | +1.05 | +0.46 | +0.68 | ok | (6,6) | +1.05 | +0.46 | +0.68 | ok (alias) | +0.88 | - |
| pyrimidine-x8 | 3 | V | 4.09 | (10,12) | +1.58 | +0.09 | -0.30 | ok, not good | (10,8) | +0.36 | +0.07 | +0.11 | ok | (10,8) | +0.36 | +0.07 | +0.11 | ok (alias) | +1.58 | - |
| pyrimidine-x9 | 3 | V | 4.51 | (10,12) | +0.51 | +0.65 | +0.76 | ok | (6,6) | -0.38 | +0.20 | +0.34 | ok | (6,6) | -0.38 | +0.20 | +0.34 | ok (alias) | +0.49 | - |
| pyrimidine-x10 | 3 | V | 4.66 | (10,12) | +1.97 | +0.27 | +0.17 | ok, not good | (10,8) | +0.54 | +0.06 | +0.09 | ok | (10,8) | +0.54 | +0.06 | +0.09 | ok (alias) | +1.97 | - |
| pyrimidine-x11 | 3 | V | 4.96 | (10,12) | +0.26 | +0.01 | +0.12 | ok | (6,6) | +0.14 | +0.08 | +0.15 | ok | (6,6) | +0.14 | +0.08 | +0.15 | ok (alias) | +0.36 | - |
| pyrrole-x1 | 1 | R | 5.24 | (8,13) | -0.62 | -0.12 | +0.19 | ok | (6,5) | - | - | - | unrepresentable | (6,5) | - | - | - | unrepresentable (alias) | -0.62 | - |
| pyrrole-x2 | 1 | R | 6.00 | (8,13) | -0.67 | -0.23 | +0.26 | ok | (6,5) | - | - | - | unrepresentable | (6,5) | - | - | - | unrepresentable (alias) | -0.67 | - |
| pyrrole-x3 | 1 | R | 6.00 | (8,13) | -0.94 | -0.44 | +0.22 | ok | (6,5) | - | - | - | unrepresentable | (6,5) | - | - | - | unrepresentable (alias) | -0.94 | - |
| pyrrole-x4 | 1 | V | 6.26 | (8,13) | -0.59 | -0.14 | +0.37 | ok | (6,5) | -0.66 | -0.13 | +0.31 | ok | (6,5) | -0.66 | -0.13 | +0.31 | ok (alias) | -0.59 | - |
| pyrrole-x5 | 1 | V | 6.30 | (8,13) | +0.20 | +0.08 | +0.18 | ok | (6,5) | +0.21 | +0.18 | +0.32 | ok | (6,5) | +0.21 | +0.18 | +0.32 | ok (alias) | +0.19 | - |
| pyrrole-x6 | 1 | R | 6.83 | (8,13) | -0.91 | -0.52 | -0.17 | ok | (6,5) | +2.43 | +0.98 | +1.27 | ok, not good | (6,5) | +2.43 | +0.98 | +1.27 | ok (alias), not good | -1.04 | - |
| pyrrole-x7 | 3 | V | 4.51 | (8,13) | -0.05 | +0.12 | +0.11 | ok | (6,5) | -0.27 | +0.09 | +0.24 | ok | (6,5) | -0.27 | +0.09 | +0.24 | ok (alias) | -0.20 | - |
| pyrrole-x8 | 3 | R | 5.21 | (8,13) | -0.61 | -0.14 | +0.19 | ok | (6,5) | - | - | - | unrepresentable | (6,5) | - | - | - | unrepresentable (alias) | -0.61 | - |
| pyrrole-x9 | 3 | V | 5.45 | (8,13) | +0.14 | +0.14 | +0.20 | ok | (6,5) | +0.05 | +0.15 | +0.26 | ok | (6,5) | +0.05 | +0.15 | +0.26 | ok (alias) | +0.15 | - |
| pyrrole-x10 | 3 | R | 5.91 | (8,13) | -0.62 | -0.23 | +0.24 | ok | (6,5) | - | - | - | unrepresentable | (6,5) | - | - | - | unrepresentable (alias) | -0.54 | - |
| sicl2-x1 | 1 | V | 3.91 | (12,12) | +0.40 | -0.44 | -0.01 | ok | (8,5) | +0.29 | -0.56 | -0.16 | ok | (8,5) | +0.29 | -0.56 | -0.16 | ok (alias) | +0.38 | - |
| sicl2-x2 | 3 | V | 2.48 | (12,12) | -0.28 | -0.06 | -0.13 | ok | (4,3) | - | - | - | unrepresentable | (4,3) | - | - | - | unrepresentable (alias) | -0.28 | - |
| silylidene-x1 | 1 | R | 2.11 | (8,13) | +0.09 | +0.05 | +0.01 | ok | (2,2) | - | - | - | unrepresentable | (2,2) | - | - | - | unrepresentable (alias) | +0.09 | - |
| silylidene-x2 | 1 | R | 3.78 | (8,13) | +0.16 | -0.21 | +0.08 | ok | (2,2) | - | - | - | unrepresentable | (2,2) | - | - | - | unrepresentable (alias) | +0.16 | - |
| streptocyanine-c1-x1 | 1 | V | 7.13 | (10,12) | +0.22 | -0.26 | +0.19 | ok | (4,3) | +0.75 | -0.29 | -0.00 | ok | (4,3) | +0.75 | -0.29 | -0.00 | ok (alias) | +0.23 | - |
| streptocyanine-c1-x2 | 3 | V | 5.52 | (10,12) | +0.12 | +0.06 | +0.14 | ok | (4,3) | +0.14 | -0.06 | -0.04 | ok | (4,3) | +0.14 | -0.06 | -0.04 | ok (alias) | +0.05 | - |
| streptocyanine-c3-x1 | 1 | V | 4.82 | (10,12) | +0.52 | -0.41 | +0.03 | ok | (6,5) | +0.41 | -0.32 | +0.14 | ok | (6,5) | +0.41 | -0.32 | +0.14 | ok (alias) | +0.33 | - |
| streptocyanine-c3-x2 | 3 | V | 3.44 | (10,12) | +0.26 | -0.06 | +0.03 | ok | (6,5) | +0.19 | -0.06 | +0.02 | ok | (6,5) | +0.19 | -0.06 | +0.02 | ok (alias) | +0.19 | - |
| streptocyanine-c5-x1 | 1 | V | 3.64 | (8,13) | +0.10 | -0.25 | +0.28 | ok | (8,7) | +0.15 | -0.25 | +0.23 | ok | (8,7) | +0.15 | -0.25 | +0.23 | ok (alias) | +0.11 | - |
| streptocyanine-c5-x2 | 3 | V | 2.47 | (8,13) | +0.13 | -0.03 | +0.03 | ok | (8,7) | +0.19 | -0.03 | +0.02 | ok | (8,7) | +0.19 | -0.03 | +0.02 | ok (alias) | +0.12 | - |
| tetrazine-x1 | 1 | V | 2.47 | (20,13) | +0.89 | -0.07 | -0.12 | ok | (10,8) | +1.51 | -0.17 | -0.73 | ok, not good | (10,8) | +1.51 | -0.17 | -0.73 | ok (alias), not good | +0.89 | - |
| tetrazine-x2 | 1 | V | 3.69 | (20,13) | +1.12 | -0.00 | -0.02 | ok, not good | (10,8) | +1.76 | -0.19 | -0.79 | ok, not good | (10,8) | +1.76 | -0.19 | -0.79 | ok (alias), not good | +1.12 | - |
| tetrazine-x3 | 1 | V | 4.61 | (20,13) | +1.65 | +0.23 | +0.04 | ok, not good | (10,8) | +4.10 | +4.60 | +4.86 | ok, not good | (10,8) | +4.10 | +4.60 | +4.86 | ok (alias), not good | +1.65 | - |
| tetrazine-x4 | 1 | V | 4.93 | (20,13) | +0.91 | -0.23 | -0.15 | ok | (10,8) | +3.18 | +1.57 | +1.00 | ok, not good | (10,8) | +3.18 | +1.57 | +1.00 | ok (alias), not good | +0.91 | - |
| tetrazine-x5 | 1 | V | 5.21 | (20,13) | +1.09 | +0.38 | -0.01 | ok | (6,6) | -0.17 | +0.20 | +0.38 | ok | (6,6) | -0.17 | +0.20 | +0.38 | ok (alias) | +1.09 | - |
| tetrazine-x6 | 1 | V | 5.45 | (20,13) | +0.80 | +0.02 | -0.09 | ok | (10,8) | +1.41 | -0.04 | -0.61 | ok, not good | (10,8) | +1.41 | -0.04 | -0.61 | ok (alias), not good | +0.80 | - |
| tetrazine-x7 | 1 | V | 5.53 | (20,13) | +1.16 | -0.08 | -0.08 | ok, not good | (14,10) | +0.84 | +0.08 | +0.16 | ok | (14,10) | +0.84 | +0.08 | +0.16 | ok (alias) | +1.16 | - |
| tetrazine-x8 | 1 | V | 6.15 | (20,13) | +1.60 | +0.12 | -0.20 | ok, not good | (10,8) | +1.91 | +2.51 | +2.77 | ok, not good | (10,8) | +1.91 | +2.51 | +2.77 | ok (alias), not good | +1.60 | - |
| tetrazine-x9 | 1 | V | 6.12 | (20,13) | +1.45 | -0.15 | -0.23 | ok, not good | (14,10) | +0.67 | +0.01 | +0.07 | ok | (14,10) | +0.67 | +0.01 | +0.07 | ok (alias) | +1.43 | - |
| tetrazine-x10 | 1 | V | 6.91 | (20,13) | +1.38 | +0.01 | -0.03 | ok, not good | (14,10) | +0.27 | -0.14 | -0.09 | ok | (14,10) | +0.27 | -0.14 | -0.09 | ok (alias) | +1.38 | - |
| tetrazine-x11 | 3 | V | 1.85 | (20,13) | +1.08 | +0.15 | -0.03 | ok | (10,8) | +1.57 | -0.07 | -0.74 | ok, not good | (10,8) | +1.57 | -0.07 | -0.74 | ok (alias), not good | +1.08 | - |
| tetrazine-x12 | 3 | V | 3.45 | (20,13) | +1.07 | +0.02 | +0.01 | ok | (10,8) | +1.68 | -0.18 | -0.66 | ok, not good | (10,8) | +1.68 | -0.18 | -0.66 | ok (alias), not good | +1.06 | - |
| tetrazine-x13 | 3 | V | 4.20 | (20,13) | +1.29 | +0.15 | +0.11 | ok, not good | (10,8) | +3.67 | +1.95 | +1.37 | ok, not good | (10,8) | +3.67 | +1.95 | +1.37 | ok (alias), not good | +1.29 | - |
| tetrazine-x14 | 1 | V | 4.49 | (20,13) | +3.91 | +2.39 | +3.01 | ok, not good | (6,6) | +4.60 | +1.95 | +2.42 | ok, not good | (6,6) | +4.60 | +1.95 | +2.42 | ok (alias), not good | +3.91 | - |
| tetrazine-x15 | 3 | V | 4.52 | (20,13) | +0.14 | -0.04 | +0.07 | ok | (6,6) | +0.16 | +0.09 | +0.08 | ok | (6,6) | +0.16 | +0.09 | +0.08 | ok (alias) | +0.14 | - |
| tetrazine-x16 | 3 | V | 5.04 | (20,13) | +0.97 | +0.15 | +0.04 | ok | (10,8) | +1.71 | +0.11 | -0.43 | ok, not good | (10,8) | +1.71 | +0.11 | -0.43 | ok (alias), not good | +0.97 | - |
| tetrazine-x17 | 3 | V | 5.11 | (20,13) | +1.32 | +0.03 | -0.00 | ok, not good | (14,10) | +1.01 | +0.06 | +0.10 | ok | (14,10) | +1.01 | +0.06 | +0.10 | ok (alias) | +1.30 | - |
| tetrazine-x18 | 3 | V | 5.51 | (20,13) | +1.79 | +0.24 | +0.15 | ok, not good | (10,8) | +1.76 | +2.42 | +2.69 | ok, not good | (10,8) | +1.76 | +2.42 | +2.69 | ok (alias), not good | +1.79 | - |
| tetrazine-x19 | 3 | V | 5.42 | (20,13) | -0.61 | -0.54 | -0.69 | ok | (6,6) | -1.52 | -0.78 | -0.60 | ok, not good | (6,6) | -1.52 | -0.78 | -0.60 | ok (alias), not good | -0.61 | - |
| thioacetone-x1 | 1 | V | 2.53 | (10,12) | +0.06 | +0.19 | +0.05 | ok | (6,4) | +0.03 | +0.14 | +0.01 | ok | (6,4) | +0.03 | +0.14 | +0.01 | ok (alias) | +0.06 | - |
| thioacetone-x2 | 1 | R | 5.56 | (8,12) | -0.18 | -0.09 | +0.10 | ok | (6,4) | +5.56 | +4.59 | +4.85 | ok, not good | (6,4) | +5.56 | +4.59 | +4.85 | ok (alias), not good | -0.16 | - |
| thioacetone-x3 | 1 | V | 5.88 | (8,12) | +0.99 | -0.19 | +0.37 | ok | (2,2) | +1.16 | -0.34 | +0.12 | ok, not good | (2,2) | +1.16 | -0.34 | +0.12 | ok (alias), not good | +0.96 | - |
| thioacetone-x4 | 1 | R | 6.51 | (10,12) | -0.75 | -0.45 | +0.02 | ok | (6,4) | - | - | - | unrepresentable | (6,4) | - | - | - | unrepresentable (alias) | -0.91 | - |
| thioacetone-x5 | 1 | R | 6.61 | (10,12) | +1.70 | +1.46 | +1.89 | ok, not good | (6,4) | +2.54 | +1.42 | +0.93 | ok, not good | (6,4) | +2.54 | +1.42 | +0.93 | ok (alias), not good | +1.57 | - |
| thioacetone-x6 | 3 | V | 2.33 | (8,12) | +0.02 | +0.10 | +0.04 | ok | (6,4) | +0.02 | +0.10 | -0.04 | ok | (6,4) | +0.02 | +0.10 | -0.04 | ok (alias) | +0.04 | - |
| thioacetone-x7 | 3 | V | 3.45 | (10,12) | +0.02 | +0.12 | +0.07 | ok | (2,2) | -0.29 | +0.04 | +0.15 | ok | (2,2) | -0.29 | +0.04 | +0.15 | ok (alias) | -0.18 | - |
| thioacrolein-x1 | 1 | V | 2.11 | (12,12) | +0.33 | +0.10 | +0.06 | ok | (8,6) | +0.06 | +0.09 | +0.02 | ok | (8,6) | +0.06 | +0.09 | +0.02 | ok (alias) | +0.44 | - |
| thioacrolein-x2 | 3 | V | 1.91 | (12,12) | +0.36 | +0.09 | +0.06 | ok | (8,6) | +0.08 | +0.07 | -0.01 | ok | (8,6) | +0.08 | +0.07 | -0.01 | ok (alias) | +0.48 | - |
| thioformaldehyde-x1 | 1 | V | 2.22 | (10,12) | +0.11 | +0.16 | +0.05 | ok | (6,4) | +0.09 | +0.11 | +0.04 | ok | (6,4) | +0.09 | +0.11 | +0.04 | ok (alias) | +0.17 | - |
| thioformaldehyde-x2 | 1 | R | 5.96 | (10,12) | -0.57 | -0.18 | -0.03 | ok | (6,4) | +4.89 | +4.06 | +4.36 | ok, not good | (6,4) | +4.89 | +4.06 | +4.36 | ok (alias), not good | -0.42 | - |
| thioformaldehyde-x3 | 1 | V | 6.38 | (10,12) | +0.69 | -0.41 | +0.18 | ok | (6,4) | +1.37 | -0.20 | +0.37 | ok, not good | (6,4) | +1.37 | -0.20 | +0.37 | ok (alias), not good | +0.66 | - |
| thioformaldehyde-x4 | 3 | V | 1.94 | (10,12) | +0.13 | +0.16 | +0.05 | ok | (6,4) | +0.12 | +0.08 | -0.01 | ok | (6,4) | +0.12 | +0.08 | -0.01 | ok (alias) | +0.18 | - |
| thioformaldehyde-x5 | 3 | V | 3.43 | (10,12) | +0.12 | +0.08 | -0.00 | ok | (2,2) | -0.37 | -0.01 | +0.06 | ok | (2,2) | -0.37 | -0.01 | +0.06 | ok (alias) | +0.03 | - |
| thioformaldehyde-x6 | 3 | R | 5.72 | (10,12) | -0.43 | -0.14 | +0.04 | ok | (6,4) | +3.91 | +3.44 | +3.55 | ok, not good | (6,4) | +3.91 | +3.44 | +3.55 | ok (alias), not good | -0.27 | - |
| thiophene-x1 | 1 | V | 5.64 | (18,13) | +1.44 | +0.31 | +0.49 | ok, not good | (6,5) | +0.50 | +0.25 | +0.33 | ok | (6,5) | +0.50 | +0.25 | +0.33 | ok (alias) | +1.38 | - |
| thiophene-x2 | 1 | V | 5.98 | (18,13) | +0.60 | -0.45 | +0.07 | ok | (6,5) | +1.09 | -0.45 | -0.19 | ok | (6,5) | +1.09 | -0.45 | -0.19 | ok (alias) | +0.60 | - |
| thiophene-x3 | 1 | R | 6.14 | (18,13) | +0.14 | +0.12 | +0.26 | ok | (6,5) | - | - | - | unrepresentable | (6,5) | - | - | - | unrepresentable (alias) | +0.13 | - |
| thiophene-x4 | 1 | R | 6.14 | (18,13) | -0.44 | -0.12 | +0.22 | ok | (6,5) | - | - | - | unrepresentable | (6,5) | - | - | - | unrepresentable (alias) | -0.44 | - |
| thiophene-x5 | 1 | R | 6.21 | (18,13) | -0.06 | +0.16 | +0.42 | ok | (6,5) | - | - | - | unrepresentable | (6,5) | - | - | - | unrepresentable (alias) | -0.06 | - |
| thiophene-x6 | 1 | R | 6.49 | (18,13) | -0.68 | -0.11 | +0.14 | ok | (6,5) | - | - | - | unrepresentable | (6,5) | - | - | - | unrepresentable (alias) | -0.67 | - |
| thiophene-x7 | 1 | R | 7.29 | (18,13) | +4.17 | +2.84 | +3.33 | ok, not good | (6,5) | +1.65 | +0.35 | +0.38 | ok, not good | (6,5) | +1.65 | +0.35 | +0.38 | ok (alias), not good | +4.16 | - |
| thiophene-x8 | 1 | V | 7.31 | (18,13) | +1.65 | +1.09 | +1.24 | ok, not good | (6,5) | +0.98 | +0.17 | +0.27 | ok | (6,5) | +0.98 | +0.17 | +0.27 | ok (alias) | +1.63 | - |
| thiophene-x9 | 3 | V | 3.97 | (18,13) | +0.07 | +0.05 | +0.12 | ok | (6,5) | -0.29 | +0.03 | +0.18 | ok | (6,5) | -0.29 | +0.03 | +0.18 | ok (alias) | +0.09 | - |
| thiophene-x10 | 3 | V | 4.76 | (18,13) | +0.48 | +0.06 | +0.22 | ok | (6,5) | +0.26 | +0.20 | +0.23 | ok | (6,5) | +0.26 | +0.20 | +0.23 | ok (alias) | +0.49 | - |
| thiophene-x11 | 3 | R | 5.93 | (18,13) | -0.29 | -0.15 | +0.13 | ok | (6,5) | - | - | - | unrepresentable | (6,5) | - | - | - | unrepresentable (alias) | -0.29 | - |
| thiophene-x12 | 3 | R | 6.08 | (18,13) | -0.00 | +0.01 | +0.05 | ok | (6,5) | - | - | - | unrepresentable | (6,5) | - | - | - | unrepresentable (alias) | +0.01 | - |
| thiopropynal-x1 | 1 | V | 2.03 | (14,12) | +0.20 | +0.09 | -0.00 | ok | (10,8) | +0.08 | +0.08 | +0.03 | ok | (10,8) | +0.08 | +0.08 | +0.03 | ok (alias) | +0.20 | - |
| thiopropynal-x2 | 3 | V | 1.80 | (14,12) | +0.21 | +0.08 | -0.00 | ok | (10,8) | +0.10 | +0.06 | -0.01 | ok | (10,8) | +0.10 | +0.06 | -0.01 | ok (alias) | +0.21 | - |
| triazine-x1 | 1 | V | 4.72 | (18,13) | +0.42 | -0.06 | +0.05 | ok | (10,8) | +0.68 | +0.05 | +0.04 | ok | (10,8) | +0.68 | +0.05 | +0.04 | ok (alias) | +0.52 | - |
| triazine-x2 | 1 | V | 4.75 | (18,13) | +0.22 | -0.00 | +0.16 | ok | (10,8) | +0.67 | +0.35 | +0.42 | ok | (10,8) | +0.67 | +0.35 | +0.42 | ok (alias) | +0.33 | - |
| triazine-x3 | 1 | V | 4.78 | (18,13) | +0.61 | +0.07 | +0.13 | ok | (12,9) | +0.76 | +0.09 | +0.17 | ok | (12,9) | +0.76 | +0.09 | +0.17 | ok (alias) | +0.67 | - |
| triazine-x4 | 1 | V | 5.75 | (18,13) | -0.10 | +0.18 | +0.29 | ok | (6,6) | -0.23 | +0.18 | +0.37 | ok | (6,6) | -0.23 | +0.18 | +0.37 | ok (alias) | -0.08 | - |
| triazine-x5 | 1 | V | 7.24 | (18,13) | +1.16 | -0.16 | +0.09 | not_converged, not good | (6,6) | +1.19 | -0.17 | -0.04 | ok, not good | (6,6) | +1.19 | -0.17 | -0.04 | ok (alias), not good | +1.14 | - |
| triazine-x6 | 1 | R | 7.32 | (18,13) | +1.62 | +1.35 | +1.63 | ok, not good | (10,8) | +1.50 | +1.49 | +1.79 | ok, not good | (10,8) | +1.50 | +1.49 | +1.79 | ok (alias), not good | +1.69 | - |
| triazine-x7 | 1 | V | 7.78 | (18,13) | +0.52 | -0.03 | +0.25 | ok | (12,9) | +0.53 | +0.03 | +0.28 | ok | (12,9) | +0.53 | +0.03 | +0.28 | ok (alias) | +0.55 | - |
| triazine-x8 | 1 | V | 7.94 | (18,13) | +1.00 | +0.77 | +1.05 | ok | (12,9) | +0.92 | +1.01 | +1.28 | ok | (12,9) | +0.92 | +1.01 | +1.28 | ok (alias) | +1.11 | - |
| triazine-x9 | 3 | V | 4.33 | (18,13) | +0.26 | +0.06 | +0.19 | ok | (10,8) | +0.61 | +0.38 | +0.42 | ok | (10,8) | +0.61 | +0.38 | +0.42 | ok (alias) | +0.35 | - |
| triazine-x10 | 3 | V | 4.51 | (18,13) | +0.51 | +0.03 | +0.11 | ok | (10,8) | +0.65 | +0.15 | +0.17 | ok | (10,8) | +0.65 | +0.15 | +0.17 | ok (alias) | +0.61 | - |
| triazine-x11 | 3 | V | 4.73 | (18,13) | +0.93 | +0.00 | +0.13 | ok | (12,9) | +1.19 | +0.07 | +0.05 | ok, not good | (12,9) | +1.19 | +0.07 | +0.05 | ok (alias), not good | +0.97 | - |
| triazine-x12 | 3 | V | 4.85 | (18,13) | -0.34 | +0.18 | +0.28 | ok | (6,6) | -0.49 | +0.16 | +0.36 | ok | (6,6) | -0.49 | +0.16 | +0.36 | ok (alias) | -0.33 | - |
| triazine-x13 | 3 | V | 5.59 | (18,13) | +0.12 | +0.09 | +0.21 | ok | (6,6) | +0.02 | +0.09 | +0.26 | ok | (6,6) | +0.02 | +0.09 | +0.26 | ok (alias) | +0.11 | - |
| triazine-x14 | 3 | V | 6.62 | (18,13) | +1.31 | +0.13 | +0.30 | ok, not good | (6,6) | +1.21 | +1.83 | +2.13 | ok, not good | (6,6) | +1.21 | +1.83 | +2.13 | ok (alias), not good | +1.24 | - |
| water-x1 | 1 | R | 7.62 | (8,13) | -0.23 | -0.22 | +0.02 | ok | (8,6) | -0.81 | -0.35 | +0.01 | ok | (8,6) | -0.81 | -0.35 | +0.01 | ok (alias) | -0.23 | - |
| water-x2 | 1 | R | 9.41 | (8,13) | -0.33 | -0.49 | -0.04 | ok | (8,6) | -0.89 | -0.59 | -0.00 | ok | (8,6) | -0.89 | -0.59 | -0.00 | ok (alias) | -0.33 | - |
| water-x3 | 1 | R | 9.99 | (8,13) | -0.18 | -0.24 | +0.05 | ok | (8,6) | -0.84 | -0.47 | +0.05 | ok | (8,6) | -0.84 | -0.47 | +0.05 | ok (alias) | -0.18 | - |
| water-x4 | 3 | R | 7.25 | (8,13) | -0.24 | -0.19 | +0.01 | ok | (8,6) | -0.73 | -0.28 | +0.04 | ok | (8,6) | -0.73 | -0.28 | +0.04 | ok (alias) | -0.24 | - |
| water-x5 | 3 | R | 9.24 | (8,13) | -0.29 | -0.51 | -0.02 | ok | (8,6) | -0.78 | -0.58 | +0.03 | ok | (8,6) | -0.78 | -0.58 | +0.03 | ok (alias) | -0.29 | - |
| water-x6 | 3 | R | 9.54 | (8,13) | -0.21 | -0.22 | +0.02 | ok | (8,6) | -0.75 | -0.37 | +0.04 | ok | (8,6) | -0.75 | -0.37 | +0.04 | ok (alias) | -0.21 | - |
| allyl-x1 | 2 | - | 3.39 | (11,11) | +0.04 | +0.07 | +0.07 | ok | (3,3) | -0.02 | +0.10 | +0.16 | ok | (3,3) | -0.02 | +0.10 | +0.16 | ok (alias) | +0.07 | - |
| allyl-x2 | 2 | - | 4.99 | (11,11) | -0.45 | -0.41 | +0.00 | ok | (3,3) | - | - | - | unrepresentable | (3,3) | - | - | - | unrepresentable (alias) | -0.57 | - |
| bef-x1 | 2 | - | 4.14 | (9,12) | +0.12 | -0.26 | +0.06 | ok | (5,3) | +3.58 | +4.06 | +4.62 | ok, not good | (5,3) | +3.58 | +4.06 | +4.62 | ok (alias), not good | +0.12 | - |
| bef-x2 | 2 | - | 6.21 | (9,12) | -0.02 | -0.06 | +0.06 | ok | (5,3) | - | - | - | unrepresentable | (5,3) | - | - | - | unrepresentable (alias) | -0.02 | - |
| beh-x1 | 2 | - | 2.49 | (5,22) | -0.00 | -0.13 | -0.00 | ok | (3,2) | - | - | - | unrepresentable | (3,2) | - | - | - | unrepresentable (alias) | +0.01 | - |
| beh-x2 | 2 | - | 6.46 | (5,22) | -0.03 | -0.28 | -0.00 | ok | (3,2) | - | - | - | unrepresentable | (3,2) | - | - | - | unrepresentable (alias) | -0.02 | - |
| bh2-x1 | 2 | - | 1.18 | (5,15) | +0.21 | -0.02 | +0.05 | ok | (1,2) | +0.22 | +0.02 | +0.05 | ok | (1,2) | +0.22 | +0.02 | +0.05 | ok (alias) | +0.21 | - |
| ch-x1 | 2 | - | 2.91 | (5,18) | +0.01 | +0.05 | -0.00 | ok | (1,2) | - | - | - | unrepresentable | (1,2) | - | - | - | unrepresentable (alias) | +0.01 | - |
| ch-x2 | 2 | - | 3.29 | (5,18) | +0.03 | -0.04 | +0.00 | ok | (1,2) | - | - | - | unrepresentable | (1,2) | - | - | - | unrepresentable (alias) | +0.03 | - |
| ch-x3 | 2 | - | 3.98 | (5,18) | +0.09 | -0.01 | +0.03 | ok | (1,2) | - | - | - | unrepresentable | (1,2) | - | - | - | unrepresentable (alias) | +0.09 | - |
| ch3-x1 | 2 | - | 5.85 | (7,14) | +1.07 | +0.94 | +1.17 | ok | (1,1) | - | - | - | unrepresentable | (1,1) | - | - | - | unrepresentable (alias) | +1.20 | - |
| ch3-x2 | 2 | - | 6.96 | (7,14) | +0.00 | -0.17 | +0.06 | ok | (1,1) | - | - | - | unrepresentable | (1,1) | - | - | - | unrepresentable (alias) | +0.13 | - |
| ch3-x3 | 2 | - | 7.18 | (7,14) | -0.14 | -0.43 | -0.13 | ok | (1,1) | - | - | - | unrepresentable | (1,1) | - | - | - | unrepresentable (alias) | +0.02 | - |
| ch3-x4 | 2 | - | 7.65 | (7,14) | -0.47 | -0.73 | -0.06 | ok | (1,1) | - | - | - | unrepresentable | (1,1) | - | - | - | unrepresentable (alias) | -0.51 | - |
| cn-x1 | 2 | - | 1.34 | (9,12) | +0.09 | -0.01 | +0.00 | ok | (5,5) | -0.21 | -0.38 | -0.31 | ok | (5,5) | -0.21 | -0.38 | -0.31 | ok (alias) | +0.09 | - |
| cn-x2 | 2 | - | 3.22 | (9,12) | +0.27 | -0.01 | +0.06 | ok | (7,6) | +0.22 | -0.05 | +0.03 | ok | (7,6) | +0.22 | -0.05 | +0.03 | ok (alias) | +0.27 | - |
| cno-x1 | 2 | - | 1.61 | (15,12) | +5.00 | +4.46 | +4.59 | ok, not good | (7,6) | - | - | - | unrepresentable | (7,6) | - | - | - | unrepresentable (alias) | +5.00 | geometry_suspect_unit_conversion |
| cno-x2 | 2 | - | 5.49 | (15,12) | -7.01 | -7.11 | -7.09 | ok, not good | (7,6) | - | - | - | unrepresentable | (7,6) | - | - | - | unrepresentable (alias) | -7.01 | geometry_suspect_unit_conversion |
| con-x1 | 2 | - | 3.53 | (11,11) | -3.17 | -2.92 | -3.03 | ok, not good | - | - | - | - | declined | - | - | - | - | declined | -3.17 | geometry_suspect_unit_conversion |
| con-x2 | 2 | - | 3.86 | (11,11) | -3.49 | -3.72 | -3.76 | ok, not good | - | - | - | - | declined | - | - | - | - | declined | -3.49 | geometry_suspect_unit_conversion |
| co+-x1 | 2 | - | 3.28 | (9,12) | +0.17 | -0.03 | +0.05 | ok | (5,5) | -0.07 | -0.22 | -0.17 | ok | (5,5) | -0.07 | -0.22 | -0.17 | ok (alias) | +0.26 | - |
| co+-x2 | 2 | - | 5.81 | (9,12) | +0.31 | +0.04 | +0.11 | ok | (7,6) | +0.21 | -0.06 | +0.01 | ok | (7,6) | +0.21 | -0.06 | +0.01 | ok (alias) | +0.34 | - |
| f2bo-x1 | 2 | - | 0.73 | (11,11) | +0.20 | -0.03 | -0.03 | ok | (7,5) | -0.13 | -0.06 | -0.08 | ok | (7,5) | -0.13 | -0.06 | -0.08 | ok (alias) | +0.20 | - |
| f2bo-x2 | 2 | - | 2.80 | (11,11) | +0.20 | +0.03 | +0.08 | ok | (11,7) | +0.21 | +0.04 | +0.04 | ok | (11,7) | +0.21 | +0.04 | +0.04 | ok (alias) | +0.20 | - |
| f2bs-x1 | 2 | - | 0.51 | (9,12) | -0.09 | -0.06 | -0.06 | ok | (7,5) | -0.07 | -0.05 | -0.06 | ok | (7,5) | -0.07 | -0.05 | -0.06 | ok (alias) | -0.08 | - |
| f2bs-x2 | 2 | - | 2.99 | (9,12) | +5.27 | +5.20 | +5.47 | ok, not good | (7,5) | +9.22 | +7.50 | +8.09 | ok, not good | (7,5) | +9.22 | +7.50 | +8.09 | ok (alias), not good | +0.14 | - |
| h2bo-x1 | 2 | - | 2.15 | (9,11) | +0.29 | -0.09 | -0.16 | ok | (5,4) | -0.26 | -0.19 | -0.17 | ok | (5,4) | -0.26 | -0.19 | -0.17 | ok (alias) | +0.29 | - |
| h2bo-x2 | 2 | - | 3.49 | (9,11) | +0.58 | +0.07 | +0.06 | ok | (3,3) | - | - | - | unrepresentable | (3,3) | - | - | - | unrepresentable (alias) | +0.58 | - |
| h2po-x1 | 2 | - | 2.80 | (13,11) | +0.36 | -0.04 | +0.16 | ok | (3,2) | -1.12 | -0.49 | -0.07 | ok, not good | (3,2) | -1.12 | -0.49 | -0.07 | ok (alias), not good | +0.36 | - |
| h2po-x2 | 2 | - | 4.21 | (13,11) | +0.49 | -0.02 | +0.26 | ok | (5,3) | -0.10 | -0.09 | +0.20 | ok | (5,3) | -0.10 | -0.09 | +0.20 | ok (alias) | +0.49 | - |
| h2ps-x1 | 2 | - | 1.16 | (11,11) | -0.11 | +0.04 | -0.01 | ok | (3,2) | -0.34 | -0.11 | -0.09 | ok | (3,2) | -0.34 | -0.11 | -0.09 | ok (alias) | -0.07 | - |
| h2ps-x2 | 2 | - | 2.72 | (11,11) | +0.21 | -0.02 | +0.09 | ok | (5,3) | +0.33 | +0.12 | +0.18 | ok | (5,3) | +0.33 | +0.12 | +0.18 | ok (alias) | +0.15 | - |
| hco-x1 | 2 | - | 2.09 | (11,11) | +0.56 | +0.00 | +0.09 | ok | (3,3) | +0.85 | +0.21 | -0.01 | ok | (3,3) | +0.85 | +0.21 | -0.01 | ok (alias) | +0.56 | - |
| hco-x2 | 2 | - | 5.45 | (11,11) | +1.31 | +0.97 | +0.99 | ok, not good | (3,3) | +1.86 | +2.11 | +2.62 | ok, not good | (3,3) | +1.86 | +2.11 | +2.62 | ok (alias), not good | +1.31 | - |
| hoc-x1 | 2 | - | 0.92 | (11,11) | +0.26 | +0.04 | +0.04 | ok | (3,3) | +0.05 | +0.10 | +0.14 | ok | (3,3) | +0.05 | +0.10 | +0.14 | ok (alias) | +0.26 | - |
| nco-x1 | 2 | - | 2.89 | (15,12) | +0.10 | -0.02 | -0.02 | ok | (7,6) | - | - | - | unrepresentable | (7,6) | - | - | - | unrepresentable (alias) | +0.10 | - |
| nco-x2 | 2 | - | 4.73 | (15,12) | +0.16 | +0.01 | +0.04 | ok | (11,8) | -0.03 | +0.02 | +0.11 | ok | (11,8) | -0.03 | +0.02 | +0.11 | ok (alias) | +0.16 | - |
| nh2-x1 | 2 | - | 2.12 | (7,14) | -0.30 | -0.34 | -0.27 | ok | (3,2) | -0.18 | -0.34 | -0.28 | ok | (3,2) | -0.18 | -0.34 | -0.28 | ok (alias) | -0.30 | - |
| nitromethyl-x1 | 2 | - | 2.05 | (11,11) | +1.48 | +0.04 | -0.23 | ok, not good | (5,4) | - | - | - | unrepresentable | (5,4) | - | - | - | unrepresentable (alias) | +1.48 | - |
| nitromethyl-x2 | 2 | - | 2.38 | (11,11) | -0.18 | -0.21 | -0.05 | ok | (9,6) | -0.36 | -0.20 | +0.02 | ok | (9,6) | -0.36 | -0.20 | +0.02 | ok (alias) | -0.18 | - |
| nitromethyl-x3 | 2 | - | 2.56 | (11,11) | +3.80 | +4.25 | +4.60 | ok, not good | (5,4) | - | - | - | unrepresentable | (5,4) | - | - | - | unrepresentable (alias) | +3.80 | - |
| nitromethyl-x4 | 2 | - | 5.35 | (11,11) | +0.65 | -0.03 | +0.22 | ok | (9,6) | +0.74 | -0.14 | -0.05 | ok | (9,6) | +0.74 | -0.14 | -0.05 | ok (alias) | +0.65 | - |
| no-x1 | 2 | - | 6.13 | (11,11) | +2.67 | +2.21 | +2.49 | ok, not good | (5,4) | - | - | - | unrepresentable | (5,4) | - | - | - | unrepresentable (alias) | +2.67 | geometry_suspect_unit_conversion |
| no-x2 | 2 | - | 7.29 | (11,11) | +2.43 | +1.42 | +1.71 | ok, not good | (5,4) | - | - | - | unrepresentable | (5,4) | - | - | - | unrepresentable (alias) | +1.97 | geometry_suspect_unit_conversion |
| oh-x1 | 2 | - | 4.10 | (7,14) | +0.01 | -0.09 | +0.03 | ok | (3,2) | - | - | - | unrepresentable | (3,2) | - | - | - | unrepresentable (alias) | +0.01 | - |
| oh-x2 | 2 | - | 8.02 | (7,14) | -0.20 | -0.24 | -0.04 | ok | (3,2) | - | - | - | unrepresentable | (3,2) | - | - | - | unrepresentable (alias) | -0.20 | - |
| ph2-x1 | 2 | - | 2.77 | (7,14) | +0.11 | -0.08 | +0.04 | ok | (3,2) | +0.20 | -0.06 | +0.01 | ok | (3,2) | +0.20 | -0.06 | +0.01 | ok (alias) | +0.11 | - |
| vinyl-x1 | 2 | - | 3.26 | (11,11) | -1.39 | -1.81 | -1.74 | ok, not good | (3,3) | -1.14 | -1.99 | -1.83 | ok, not good | (3,3) | -1.14 | -1.99 | -1.83 | ok (alias), not good | -1.39 | geometry_suspect_unit_conversion |
| vinyl-x2 | 2 | - | 4.69 | (11,11) | -1.18 | -0.57 | -0.47 | ok, not good | (3,3) | +3.34 | +2.62 | +2.54 | ok, not good | (3,3) | +3.34 | +2.62 | +2.54 | ok (alias), not good | -1.18 | geometry_suspect_unit_conversion |
| vinyl-x3 | 2 | - | 5.60 | (11,11) | -9.13 | -8.86 | -8.95 | ok, not good | (3,3) | -8.91 | -8.80 | -8.98 | ok, not good | (3,3) | -8.91 | -8.80 | -8.98 | ok (alias), not good | -9.13 | geometry_suspect_unit_conversion |
| vinyl-x4 | 2 | - | 6.20 | (11,11) | -3.76 | -3.84 | -3.85 | ok, not good | (3,3) | -4.05 | -4.01 | -3.88 | ok, not good | (3,3) | -4.05 | -4.01 | -3.88 | ok (alias), not good | -3.76 | geometry_suspect_unit_conversion |
