# Acrolein's state average has two solutions, not one noisy one

Produced by `scripts/casbench/repeat_scatter.py --molecule acrolein --mode casscf --repeats 20 --protocol harness`, on the commit that added this file.

This replaces the reading in `phase0-measurement-floor.md`, which concluded from five trials that the `harness` tolerances removed acrolein's run-to-run scatter. They do not. The scatter is not tolerance noise and no tolerance can remove it.

Twenty identical SA-CASSCF runs in the recommended (8e,6o), cc-pVDZ, 6 roots. **All 20 converged.**

| solution | E0 / Ha | trials | median s | root characters |
|---|---|---|---|---|
| A | -190.824866 | 4/20 | 29.9 | n->pi*, n->pi*, pi->pi*, pi->pi*, mixed->pi* |
| B | -190.823527 | 16/20 | 3.7 | n->pi*, n->pi*, pi->pi*, n->pi*, pi->pi* |

The two differ by **36.4 meV** in E0 and by the character of roots 4 and 5.

**Within a solution the reproducibility is exact.** Taking the larger group alone:

- E0 spread 0.0007 meV over 16 trials
- root 1: spread 0.0000 eV
- root 2: spread 0.0000 eV
- root 3: spread 0.0000 eV
- root 4: spread 0.0000 eV
- root 5: spread 0.0000 eV

So the 0.459 eV that `phase0-measurement-floor.md` reported as a measurement floor is not a floor at all. It is the gap between two states in two different solutions, and it appears whenever a run set happens to contain both. The clean `harness` row in that table was one sample of five that happened to contain only one, not a property of the tolerances.

Two things follow for how results here are read. A per-state difference below about 0.3 eV still should not be trusted from single runs, so the practical advice in the earlier table survives even though its explanation does not. And a converged flag on this molecule says nothing about which solution was reached, so anything comparing acrolein excitation energies has to report the E0 it got them from.

**The split is not fixed.** A five-trial run of the identical protocol an hour earlier put 4 of 5 in the LOWER solution, where this twenty-trial run puts 4 of 20 there. The two solutions, their energies, the universal convergence and the timing signature are stable across both; the frequency is not. That points at machine load rather than at the molecule, and is consistent with the single-thread result: a deterministic reduction order follows one trajectory every time, so what varies with threading is which basin a run falls into.

The timing is the one reliable tell from inside a single run. The higher solution is reached in about 4 s and the lower takes 13 to 43 s, so a run that finished quickly is probably in the higher one. That is a heuristic, not an identification.

