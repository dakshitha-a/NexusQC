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

So the 0.459 eV that `phase0-measurement-floor.md` reported as a measurement floor is not a floor at all. It is the gap between two states in two different solutions, and it appears whenever a run set happens to contain both. Five trials drawn from an 80/20 split land in one basin about a third of the time, which is the most likely explanation of the clean `harness` row in that table: it was one sample of five, not a property of the tolerances.

Two things follow for how results here are read. A per-state difference below about 0.3 eV still should not be trusted from single runs, so the practical advice in the earlier table survives even though its explanation does not. And a converged flag on this molecule says nothing about which solution was reached, so anything comparing acrolein excitation energies has to report the E0 it got them from.

The lower solution is the one found less often: 4/20 trials at -190.824866 Ha against 16/20 at -190.823527 Ha. It is also the slower one to reach. A run that stops early is more likely to be sitting in the higher solution.

