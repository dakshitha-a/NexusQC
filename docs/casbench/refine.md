# casbench: refine

Produced at commit `18c84e8` on 2026-09-05 21:58, in 6181s, with omp=8, mkl=12.

Written by `scripts/casbench/run_bench.py`. Do not edit by hand: the
next run overwrites it. Interpretation belongs in
`docs/CAS_ENGINE_METHOD.md`, not here.

| molecule | basis | n_states | quick | quick_seconds | refined | refine_seconds | started_from | cycles | converged | rotations | states_found | states_wanted | stopped | error |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| N2 | def2-svpd | 1 | 10 8 | 0.06 | 10 8 | 3 | recommended | 1 | True | - | 0 | 0 | the prune was rejected and undone: the ground state rose 55.6 mHartree (1.51 eV) | - |
| N2_stretched | def2-svpd | 1 | 10 8 | 0.05 | 10 8 | 0.9 | recommended | 1 | True | - | 0 | 0 | the prune was rejected and undone: the ground state rose 12.3 mHartree (0.34 eV) | - |
| O2 | def2-svpd | 1 | 12 8 | 0.07 | 12 8 | 2.2 | recommended | 1 | True | - | 0 | 0 | the prune was rejected and undone: the ground state rose 5.3 mHartree (0.14 eV), | - |
| acetone | def2-svpd | 3 | 6 4 | 0.31 | 6 4 | 20.4 | recommended | 1 | True | - | 1 | 1 | reached a fixed point: every orbital carries correlation | - |
| acrolein | def2-svpd | 3 | 8 6 | 0.26 | 8 6 | 9.7 | recommended | 1 | True | - | 2 | 2 | reached a fixed point: every orbital carries correlation | - |
| allyl_anion | def2-svpd | 1 | 4 3 | 0.16 | 4 3 | 3.3 | recommended | 1 | True | - | 0 | 0 | the prune was rejected and undone: the cut cost 25.2% of the correlation energy  | - |
| allyl_cation | def2-svpd | 1 | 2 3 | 0.17 | 2 3 | 3.9 | recommended | 1 | True | - | 0 | 0 | the prune was rejected and undone: the ground state rose 8.3 mHartree (0.23 eV), | - |
| ammonia | def2-svpd | 1 | 8 7 | 0.08 | 6 6 | 8 | recommended | 2 | True | prune | 0 | 0 | the prune was rejected and undone: the ground state rose 53.5 mHartree (1.45 eV) | - |
| anthracene | - | - | 14 14 | - | - | - | - | - | - | - | - | - | - | ValueError: This space is too large to refine. Its only tier is CAS(14e,14o) at 2,760,615  |
| benzene | def2-svpd | 3 | 6 6 | 0.51 | 6 6 | 15.2 | recommended | 1 | True | - | 2 | 2 | reached a fixed point: every orbital carries correlation | - |
| butadiene | def2-svpd | 3 | 4 4 | 0.28 | 4 4 | 26.3 | recommended | 1 | True | - | 1 | 1 | reached a fixed point: every orbital carries correlation | - |
| cyclobutadiene_square | def2-svpd | 1 | 4 4 | 0.27 | 4 4 | 3.1 | recommended | 1 | True | - | 0 | 0 | reached a fixed point: every orbital carries correlation | - |
| cyclopentadienyl_anion | def2-svpd | 1 | 6 5 | 0.34 | 6 5 | 5.1 | recommended | 1 | True | - | 0 | 0 | reached a fixed point: every orbital carries correlation | - |
| dimethyl_sulfide | - | - | 20 18 | - | - | - | - | - | - | - | - | - | - | ValueError: This space is too large to refine. Its only tier is CAS(20e,18o) at 367,479,68 |
| ethylene | def2-svpd | 2 | 2 2 | 0.09 | 2 2 | 1.8 | recommended | 1 | True | - | 0 | 0 | reached a fixed point: every orbital carries correlation | - |
| ethylene_twisted | def2-svpd | 1 | 2 2 | 0.12 | 2 2 | 1.5 | recommended | 1 | True | - | 0 | 0 | reached a fixed point: every orbital carries correlation | - |
| formaldehyde | def2-svpd | 3 | 6 4 | 0.1 | 6 4 | 1.5 | recommended | 1 | True | - | 1 | 1 | reached a fixed point: every orbital carries correlation | - |
| formamide | def2-svpd | 3 | 8 5 | 0.2 | 8 5 | 3.3 | recommended | 1 | True | - | 1 | 1 | reached a fixed point: every orbital carries correlation | - |
| furan | def2-svpd | 3 | 8 6 | 0.36 | 6 5 | 7.7 | narrowed | 1 | True | narrow | 1 | 1 | reached a fixed point: every orbital carries correlation | - |
| hexatriene | def2-svpd | 1 | 6 6 | 0.77 | 6 6 | 13.2 | recommended | 1 | True | - | 0 | 0 | reached a fixed point: every orbital carries correlation | - |
| hydrogen_sulfide | def2-svpd | 1 | 8 6 | 0.07 | 4 4 | 5.5 | recommended | 2 | True | prune prune | 0 | 0 | the prune was rejected and undone: the ground state rose 18.9 mHartree (0.51 eV) | - |
| methane | def2-svpd | 1 | 8 8 | 0.08 | 8 8 | 1.1 | recommended | 1 | True | - | 0 | 0 | pruning would leave no correlated pair, so the space is left as it is | - |
| methanethiol | def2-svpd | 1 | 14 12 | 0.14 | 14 12 | 118.4 | recommended | 1 | True | - | 0 | 0 | the prune was rejected and undone: the ground state rose 36.8 mHartree (1.00 eV) | - |
| methylamine | def2-svpd | 1 | 14 13 | 0.13 | 14 13 | 200.6 | recommended | 1 | True | - | 0 | 0 | the prune was rejected and undone: the ground state rose 41.3 mHartree (1.12 eV) | - |
| naphthalene | def2-svpd | 1 | 10 10 | 2.62 | 10 10 | 70 | recommended | 1 | True | - | 0 | 0 | reached a fixed point: every orbital carries correlation | - |
| o-nitrophenol | def2-svpd | 5 | 22 15 | 2.5 | 16 12 | 452.1 | narrowed | 1 | True | narrow | 4 | 4 | the prune was rejected and undone: the ground state rose 11.2 mHartree (0.31 eV) | - |
| octatetraene | def2-svpd | 1 | 8 8 | 1.66 | 8 8 | 40.4 | recommended | 1 | True | - | 0 | 0 | reached a fixed point: every orbital carries correlation | - |
| ozone | def2-svpd | 1 | 14 10 | 0.1 | 14 10 | 19.7 | recommended | 1 | True | - | 0 | 0 | the prune was rejected and undone: the ground state rose 16.4 mHartree (0.45 eV) | - |
| p-benzoquinone | def2-svpd | 3 | 16 12 | 1.07 | 16 12 | 3600 | recommended | 1 | False | - | 2 | 2 | the CASSCF did not converge, and no earlier cycle did either, so this result is  | - |
| pyridine | def2-svpd | 3 | 8 7 | 0.59 | 8 7 | 23.9 | recommended | 1 | True | - | 2 | 2 | reached a fixed point: every orbital carries correlation | - |
| pyridinium | def2-svpd | 1 | 6 6 | 0.6 | 6 6 | 14 | recommended | 1 | True | - | 0 | 0 | reached a fixed point: every orbital carries correlation | - |
| pyrrole | def2-svpd | 3 | 6 5 | 0.39 | 6 5 | 8.8 | recommended | 1 | True | - | 0 | 0 | reached a fixed point: every orbital carries correlation | - |
| trimethylenemethane | def2-svpd | 1 | 4 4 | 0.5 | 4 4 | 4.6 | recommended | 1 | True | - | 0 | 0 | reached a fixed point: every orbital carries correlation | - |
| tropylium | def2-svpd | 1 | 6 7 | 0.8 | 6 7 | 21.6 | recommended | 1 | True | - | 0 | 0 | reached a fixed point: every orbital carries correlation | - |
| uracil | def2-svpd | 3 | 18 12 | 1.14 | 12 9 | 537.5 | narrowed | 2 | True | narrow prune | 2 | 2 | reached a fixed point: every orbital carries correlation | - |
| water | def2-svpd | 1 | 8 6 | 0.07 | 4 4 | 2.8 | recommended | 2 | True | prune prune | 0 | 0 | reached a fixed point: every orbital carries correlation | - |
