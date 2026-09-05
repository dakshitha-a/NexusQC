# casbench: refine

Produced at commit `77b692d` on 2026-09-04 23:36, in 3373s.

Written by `scripts/casbench/run_bench.py`. Do not edit by hand: the
next run overwrites it. Interpretation belongs in
`docs/CAS_ENGINE_METHOD.md`, not here.

| molecule | basis | n_states | quick | quick_seconds | refined | refine_seconds | started_from | cycles | converged | rotations | states_found | states_wanted | stopped | error | timed_out |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| N2 | def2-svpd | 1 | 10 8 | 0.06 | 10 8 | 2.8 | recommended | 1 | True | - | 0 | 0 | the prune was rejected and undone: the ground state rose 55.6 mHartree (1.51 eV) | - | - |
| N2_stretched | def2-svpd | 1 | 10 8 | 0.05 | 10 8 | 0.9 | recommended | 1 | True | - | 0 | 0 | the prune was rejected and undone: the ground state rose 12.3 mHartree (0.34 eV) | - | - |
| O2 | def2-svpd | 1 | 12 8 | 0.07 | 12 8 | 2.1 | recommended | 1 | True | - | 0 | 0 | the prune was rejected and undone: the ground state rose 5.3 mHartree (0.14 eV), | - | - |
| acetone | def2-svpd | 3 | 6 4 | 0.31 | 6 4 | 22 | recommended | 1 | True | - | 1 | 1 | reached a fixed point: every orbital carries correlation | - | - |
| acrolein | def2-svpd | 3 | 8 6 | 0.25 | 8 6 | 8.3 | recommended | 1 | True | - | 2 | 2 | reached a fixed point: every orbital carries correlation | - | - |
| allyl_anion | def2-svpd | 1 | 4 3 | 0.14 | 4 3 | 3.4 | recommended | 1 | True | - | 0 | 0 | the prune was rejected and undone: the cut cost 25.2% of the correlation energy  | - | - |
| allyl_cation | def2-svpd | 1 | 2 3 | 0.15 | 2 3 | 3.1 | recommended | 1 | True | - | 0 | 0 | the prune was rejected and undone: the ground state rose 8.3 mHartree (0.23 eV), | - | - |
| ammonia | def2-svpd | 1 | 8 7 | 0.07 | 6 6 | 6.4 | recommended | 2 | True | prune | 0 | 0 | the prune was rejected and undone: the ground state rose 53.5 mHartree (1.45 eV) | - | - |
| anthracene | - | - | 14 14 | - | - | - | - | - | - | - | - | - | - | MemoryError: hdiag_csf of 14 orbitals, (7,7) electrons and smult=1 with 2 doubly-occupied  | - |
| benzene | def2-svpd | 3 | 6 6 | 0.48 | 6 6 | 29.5 | recommended | 1 | True | - | 2 | 2 | reached a fixed point: every orbital carries correlation | - | - |
| butadiene | def2-svpd | 3 | 4 4 | 0.27 | 4 4 | 22.1 | recommended | 1 | True | - | 1 | 1 | reached a fixed point: every orbital carries correlation | - | - |
| cyclobutadiene_square | def2-svpd | 1 | 4 4 | 0.27 | 4 4 | 3.2 | recommended | 1 | True | - | 0 | 0 | reached a fixed point: every orbital carries correlation | - | - |
| cyclopentadienyl_anion | def2-svpd | 1 | 6 5 | 0.31 | 6 5 | 4.8 | recommended | 1 | True | - | 0 | 0 | reached a fixed point: every orbital carries correlation | - | - |
| dimethyl_sulfide | def2-svpd | 1 | 20 18 | 0.24 | 4 3 | 224.6 | narrowed | 1 | False | narrow | 0 | 0 | the CASSCF did not converge, and no earlier cycle did either, so this result is  | - | - |
| ethylene | def2-svpd | 2 | 2 2 | 0.09 | 2 2 | 1.3 | recommended | 1 | True | - | 0 | 0 | reached a fixed point: every orbital carries correlation | - | - |
| ethylene_twisted | def2-svpd | 1 | 2 2 | 0.11 | 2 2 | 1.3 | recommended | 1 | True | - | 0 | 0 | reached a fixed point: every orbital carries correlation | - | - |
| formaldehyde | def2-svpd | 3 | 6 4 | 0.1 | 6 4 | 1.4 | recommended | 1 | True | - | 1 | 1 | reached a fixed point: every orbital carries correlation | - | - |
| formamide | def2-svpd | 3 | 8 5 | 0.17 | 8 5 | 3.3 | recommended | 1 | True | - | 1 | 1 | reached a fixed point: every orbital carries correlation | - | - |
| furan | def2-svpd | 3 | 8 6 | 0.35 | 6 5 | 8.5 | narrowed | 1 | True | narrow | 1 | 1 | reached a fixed point: every orbital carries correlation | - | - |
| hexatriene | def2-svpd | 1 | 6 6 | 0.63 | 6 6 | 14.5 | recommended | 1 | True | - | 0 | 0 | reached a fixed point: every orbital carries correlation | - | - |
| hydrogen_sulfide | def2-svpd | 1 | 8 6 | 0.07 | 4 4 | 5.2 | recommended | 2 | True | prune prune | 0 | 0 | the prune was rejected and undone: the ground state rose 18.9 mHartree (0.51 eV) | - | - |
| methane | def2-svpd | 1 | 8 8 | 0.07 | 8 8 | 0.9 | recommended | 1 | True | - | 0 | 0 | pruning would leave no correlated pair, so the space is left as it is | - | - |
| methanethiol | def2-svpd | 1 | 14 12 | 0.13 | 14 12 | 111.5 | recommended | 1 | True | - | 0 | 0 | the prune was rejected and undone: the ground state rose 36.8 mHartree (1.00 eV) | - | - |
| methylamine | def2-svpd | 1 | 14 13 | 0.14 | 14 13 | 190.3 | recommended | 1 | True | - | 0 | 0 | the prune was rejected and undone: the ground state rose 41.3 mHartree (1.12 eV) | - | - |
| naphthalene | def2-svpd | 1 | 10 10 | 2.35 | 10 10 | 72.3 | recommended | 1 | True | - | 0 | 0 | reached a fixed point: every orbital carries correlation | - | - |
| o-nitrophenol | def2-svpd | 5 | 22 15 | 2.34 | 16 12 | 454.6 | narrowed | 1 | True | narrow | 4 | 4 | the prune was rejected and undone: the ground state rose 11.2 mHartree (0.31 eV) | - | - |
| octatetraene | def2-svpd | 1 | 8 8 | 1.44 | 8 8 | 39.2 | recommended | 1 | True | - | 0 | 0 | reached a fixed point: every orbital carries correlation | - | - |
| ozone | def2-svpd | 1 | 14 10 | 0.08 | 14 10 | 12.8 | recommended | 1 | True | - | 0 | 0 | the prune was rejected and undone: the ground state rose 16.4 mHartree (0.45 eV) | - | - |
| p-benzoquinone | - | - | 16 12 | - | - | 600 | - | - | - | - | - | - | - | - | True |
| pyridine | def2-svpd | 3 | 8 7 | 0.56 | 8 7 | 27.6 | recommended | 1 | True | - | 2 | 2 | reached a fixed point: every orbital carries correlation | - | - |
| pyridinium | def2-svpd | 1 | 6 6 | 0.65 | 6 6 | 14 | recommended | 1 | True | - | 0 | 0 | reached a fixed point: every orbital carries correlation | - | - |
| pyrrole | def2-svpd | 3 | 6 5 | 0.38 | 6 5 | 8.5 | recommended | 1 | True | - | 0 | 0 | reached a fixed point: every orbital carries correlation | - | - |
| trimethylenemethane | def2-svpd | 1 | 4 4 | 0.51 | 4 4 | 4.5 | recommended | 1 | True | - | 0 | 0 | reached a fixed point: every orbital carries correlation | - | - |
| tropylium | def2-svpd | 1 | 6 7 | 0.83 | 6 7 | 19.4 | recommended | 1 | True | - | 0 | 0 | reached a fixed point: every orbital carries correlation | - | - |
| uracil | def2-svpd | 3 | 18 12 | 1.16 | 12 9 | 555.3 | narrowed | 2 | True | narrow prune | 2 | 2 | reached a fixed point: every orbital carries correlation | - | - |
| water | def2-svpd | 1 | 8 6 | 0.07 | 4 4 | 2.8 | recommended | 2 | True | prune prune | 0 | 0 | reached a fixed point: every orbital carries correlation | - | - |
