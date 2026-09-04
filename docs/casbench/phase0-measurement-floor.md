# casbench: the phase 0 measurement floor

The evidence behind steps P0.1 to P0.4 of `docs/TRACKER.md`, produced by
`scripts/casbench/repeat_scatter.py`. Committed because the tracker cites
these numbers and a reader should be able to reach them without rerunning
twenty minutes of CASSCF.

## Acrolein, a bare SA-CASSCF in the recommended space

Five repeats per row, cc-pVDZ, CAS(8,6), six roots. `chars moved` is
whether any root changed character between identical runs, and it is the
column that matters: the refinement loop branches on those.

| protocol | conv_tol | grad | max_macro | threads | E0 spread | worst root spread | chars moved | converged |
|---|---|---|---|---|---|---|---|---|
| loose | 1e-06 | 0.0001 | 50 | 8 | 36.458 meV | 0.459 eV | YES | 5/5 |
| tight | 1e-10 | 1e-07 | 300 | 8 | 35.943 meV | 0.459 eV | YES | 0/5 |
| harness | 1e-08 | 1e-05 | 100 | 8 | 0.001 meV | 0.000 eV | no | 5/5 |
| loose (1 thread) | 1e-06 | 0.0001 | 50 | 1 | 0.000 meV | 0.000 eV | no | 5/5 |

The reading. The settings the refinement shipped are the `loose` row: they
move root 5 by nearly half an electronvolt and change the character of two
roots, while pyscf reports all five runs as converged. Pinning to one BLAS
thread fixes it, so the cause is reduction order in the linear algebra
rather than anything chemical, and pinning is the wrong fix at three times
the wall clock. The `tight` row is the one that stops anyone tightening
further: at 1e-10 nothing converges and the whole scatter comes back.

## Uracil, the whole shipped refinement loop

Three repeats at the new tolerances, cc-pVDZ, three states requested.
The previous tracker recorded this molecule returning (14e,9o),
(14e,10o) and (14e,9o) by a different route across three runs of
identical setup.

| trial | quick | refined | converged | cycles | seconds | root characters |
|---|---|---|---|---|---|---|
| 1 | (22,14) | **(14,10)** | True | 1 | 282.0 | pi->pi* pi->pi* pi->pi* pi->pi* pi->pi* |
| 2 | (22,14) | **(14,10)** | False | 1 | 925.9 | pi->pi* pi->pi* pi->pi* pi->pi* pi->pi* |
| 3 | (22,14) | **(14,10)** | False | 1 | 973.7 | pi->pi* pi->pi* pi->pi* pi->pi* pi->pi* |

The space, the rotation trail, the orbital labels and the root
characters are identical across all three, and the excitation energies
agree to 0.6 meV. What does not settle is convergence and cost. Note
also that no root comes back n->pi* in any trial, in a space holding
two orbitals labelled n; that is the open question recorded in the
tracker rather than a result.
