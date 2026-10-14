# casbench: refine

Produced at commit `c5a8fbc` on 2026-10-14 16:18, in 3578s, with omp=8, mkl=12.

Written by `scripts/casbench/run_bench.py`. Do not edit by hand: the
next run overwrites it. Interpretation belongs in
`docs/CAS_ENGINE_METHOD.md`, not here.

| molecule | basis | n_states | quick | quick_seconds | refined | refine_seconds | started_from | cycles | converged | rotations | states_found | states_wanted | stopped | error |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| N2 | def2-svpd | 1 | 10 8 | 0.07 | 10 8 | 2.7 | recommended | 1 | True | - | 0 | 0 | the prune was rejected and undone: the ground state rose 55.6 mHartree (1.51 eV) | - |
| N2_stretched | def2-svpd | 1 | 10 8 | 0.05 | 10 8 | 1 | recommended | 1 | True | - | 0 | 0 | the prune was rejected and undone: the ground state rose 12.3 mHartree (0.34 eV) | - |
| O2 | def2-svpd | 1 | 12 8 | 0.08 | 12 8 | 2.3 | recommended | 1 | True | - | 0 | 0 | the prune was rejected and undone: the ground state rose 5.3 mHartree (0.14 eV), | - |
| acetone | def2-svpd | 3 | 6 4 | 0.32 | 6 4 | 17.9 | recommended | 1 | True | - | 1 | 1 | reached a fixed point: every orbital carries correlation | - |
| acrolein | def2-svpd | 3 | 8 6 | 0.26 | 8 6 | 9.6 | recommended | 1 | True | - | 2 | 2 | reached a fixed point: every orbital carries correlation | - |
| allyl_anion | def2-svpd | 1 | 4 3 | 0.15 | 4 3 | 3.2 | recommended | 1 | True | - | 0 | 0 | the prune was rejected and undone: the cut cost 25.2% of the correlation energy  | - |
| allyl_cation | def2-svpd | 1 | 2 3 | 0.15 | 2 3 | 3 | recommended | 1 | True | - | 0 | 0 | the prune was rejected and undone: the ground state rose 8.3 mHartree (0.23 eV), | - |
| ammonia | def2-svpd | 1 | 8 7 | 0.07 | 6 6 | 6.9 | recommended | 2 | True | prune | 0 | 0 | the prune was rejected and undone: the ground state rose 53.5 mHartree (1.45 eV) | - |
| anthracene | - | - | 14 14 | - | - | - | - | - | - | - | - | - | - | ValueError: This space is too large to refine. Its only tier is CAS(14e,14o) at 2,760,615  |
| benzene | def2-svpd | 3 | 6 6 | 0.53 | 6 6 | 15 | recommended | 1 | True | - | 2 | 2 | reached a fixed point: every orbital carries correlation | - |
| butadiene | def2-svpd | 3 | 4 4 | 0.29 | 4 4 | 24.6 | recommended | 1 | True | - | 1 | 1 | reached a fixed point: every orbital carries correlation | - |
| cyclobutadiene_square | def2-svpd | 1 | 4 4 | 0.27 | 4 4 | 3.2 | recommended | 1 | True | - | 0 | 0 | reached a fixed point: every orbital carries correlation | - |
| cyclopentadienyl_anion | def2-svpd | 1 | 6 5 | 0.3 | 6 5 | 4.8 | recommended | 1 | True | - | 0 | 0 | reached a fixed point: every orbital carries correlation | - |
| dimethyl_sulfide | - | - | 20 18 | - | - | - | - | - | - | - | - | - | - | ValueError: This space is too large to refine. Its only tier is CAS(20e,18o) at 367,479,68 |
| ethylene | def2-svpd | 2 | 2 2 | 0.09 | 2 2 | 1.3 | recommended | 1 | True | - | 0 | 0 | reached a fixed point: every orbital carries correlation | - |
| ethylene_twisted | def2-svpd | 1 | 2 2 | 0.11 | 2 2 | 1.1 | recommended | 1 | True | - | 0 | 0 | reached a fixed point: every orbital carries correlation | - |
| formaldehyde | def2-svpd | 3 | 6 4 | 0.1 | 6 4 | 1.6 | recommended | 1 | True | - | 1 | 1 | reached a fixed point: every orbital carries correlation | - |
| formamide | def2-svpd | 3 | 8 5 | 0.18 | 8 5 | 3.6 | recommended | 1 | True | - | 1 | 1 | reached a fixed point: every orbital carries correlation | - |
| furan | def2-svpd | 3 | 8 6 | 0.37 | 6 5 | 9 | narrowed | 1 | True | narrow | 1 | 1 | reached a fixed point: every orbital carries correlation | - |
| hexatriene | def2-svpd | 1 | 6 6 | 0.66 | 6 6 | 15.1 | recommended | 1 | True | - | 0 | 0 | reached a fixed point: every orbital carries correlation | - |
| hydrogen_sulfide | def2-svpd | 1 | 8 6 | 0.08 | 4 4 | 4.2 | recommended | 2 | True | prune prune | 0 | 0 | the prune was rejected and undone: the ground state rose 18.9 mHartree (0.51 eV) | - |
| methane | def2-svpd | 1 | 8 8 | 0.08 | 8 8 | 1.2 | recommended | 1 | True | - | 0 | 0 | pruning would leave no correlated pair, so the space is left as it is | - |
| methanethiol | def2-svpd | 1 | 14 12 | 0.13 | 14 12 | 108.8 | recommended | 1 | True | - | 0 | 0 | the prune was rejected and undone: the ground state rose 36.8 mHartree (1.00 eV) | - |
| methylamine | def2-svpd | 1 | 14 13 | 0.12 | 14 13 | 188.6 | recommended | 1 | True | - | 0 | 0 | the prune was rejected and undone: the ground state rose 41.3 mHartree (1.12 eV) | - |
| naphthalene | def2-svpd | 1 | 10 10 | 2.35 | 10 10 | 66.4 | recommended | 1 | True | - | 0 | 0 | reached a fixed point: every orbital carries correlation | - |
| o-nitrophenol | def2-svpd | 5 | 22 15 | 2.2 | 16 12 | 437 | narrowed | 1 | True | narrow | 4 | 4 | the prune was rejected and undone: the ground state rose 11.2 mHartree (0.31 eV) | - |
| octatetraene | def2-svpd | 1 | 8 8 | 1.52 | 8 8 | 37.1 | recommended | 1 | True | - | 0 | 0 | reached a fixed point: every orbital carries correlation | - |
| ozone | def2-svpd | 1 | 14 10 | 0.09 | 14 10 | 16.4 | recommended | 1 | True | - | 0 | 0 | the prune was rejected and undone: the ground state rose 16.4 mHartree (0.45 eV) | - |
| p-benzoquinone | def2-svpd | 3 | 16 12 | 0.99 | 12 10 | 1182 | recommended | 2 | True | prune prune | 2 | 2 | reached a fixed point: every orbital carries correlation | - |
| pyridine | def2-svpd | 3 | 8 7 | 0.49 | 8 7 | 26.1 | recommended | 1 | True | - | 2 | 2 | reached a fixed point: every orbital carries correlation | - |
| pyridinium | def2-svpd | 1 | 6 6 | 0.53 | 6 6 | 12.8 | recommended | 1 | True | - | 0 | 0 | reached a fixed point: every orbital carries correlation | - |
| pyrrole | def2-svpd | 3 | 6 5 | 0.32 | 6 5 | 7.7 | recommended | 1 | True | - | 0 | 0 | reached a fixed point: every orbital carries correlation | - |
| trimethylenemethane | def2-svpd | 1 | 4 4 | 0.44 | 4 4 | 5.1 | recommended | 1 | True | - | 0 | 0 | reached a fixed point: every orbital carries correlation | - |
| tropylium | def2-svpd | 1 | 6 7 | 0.69 | 6 7 | 20.1 | recommended | 1 | True | - | 0 | 0 | reached a fixed point: every orbital carries correlation | - |
| uracil | def2-svpd | 3 | 18 12 | 0.99 | 12 9 | 470.1 | narrowed | 2 | True | narrow prune | 2 | 2 | reached a fixed point: every orbital carries correlation | - |
| water | def2-svpd | 1 | 8 6 | 0.08 | 4 4 | 3.1 | recommended | 2 | True | prune prune | 0 | 0 | reached a fixed point: every orbital carries correlation | - |
