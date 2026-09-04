# casbench: refine

Produced at commit `0d1f937` on 2026-09-04 15:20, in 3295s.

Written by `scripts/casbench/run_bench.py`. Do not edit by hand: the
next run overwrites it. Interpretation belongs in
`docs/CAS_ENGINE_METHOD.md`, not here.

| molecule | basis | n_states | quick | quick_seconds | refined | refine_seconds | started_from | cycles | converged | rotations | states_found | states_wanted | stopped | timed_out |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| N2 | def2-svpd | 1 | 10 8 | 0.06 | 10 8 | 2.6 | recommended | 1 | True | - | 0 | 0 | the prune was rejected and undone: the ground state rose 55.6 mHartree (1.51 eV) | - |
| N2_stretched | def2-svpd | 1 | 10 8 | 0.05 | 10 8 | 0.9 | recommended | 1 | True | - | 0 | 0 | the prune was rejected and undone: the ground state rose 12.3 mHartree (0.34 eV) | - |
| O2 | def2-svpd | 1 | 12 8 | 0.07 | 12 8 | 2.2 | recommended | 1 | True | - | 0 | 0 | the prune was rejected and undone: the ground state rose 5.3 mHartree (0.14 eV), | - |
| acetone | def2-svpd | 3 | 6 4 | 0.28 | 6 4 | 22.1 | recommended | 1 | True | - | 1 | 1 | reached a fixed point: every orbital carries correlation | - |
| acrolein | def2-svpd | 3 | 8 6 | 0.23 | 8 6 | 8.6 | recommended | 1 | True | - | 2 | 2 | reached a fixed point: every orbital carries correlation | - |
| ammonia | def2-svpd | 1 | 8 7 | 0.08 | 6 6 | 6.7 | recommended | 2 | True | prune | 0 | 0 | the prune was rejected and undone: the ground state rose 53.5 mHartree (1.45 eV) | - |
| benzene | def2-svpd | 3 | 6 6 | 0.54 | 6 6 | 13.6 | recommended | 1 | True | - | 2 | 2 | reached a fixed point: every orbital carries correlation | - |
| butadiene | def2-svpd | 3 | 4 4 | 0.26 | 4 4 | 17.8 | recommended | 1 | True | - | 1 | 1 | reached a fixed point: every orbital carries correlation | - |
| cyclobutadiene_square | def2-svpd | 1 | 4 4 | 0.27 | 4 4 | 3.4 | recommended | 1 | True | - | 0 | 0 | reached a fixed point: every orbital carries correlation | - |
| dimethyl_sulfide | def2-svpd | 1 | 20 18 | 0.24 | 4 3 | 206.3 | narrowed | 1 | False | narrow | 0 | 0 | the CASSCF did not converge, and no earlier cycle did either, so this result is  | - |
| ethylene | def2-svpd | 2 | 2 2 | 0.09 | 2 2 | 1.7 | recommended | 1 | True | - | 0 | 0 | reached a fixed point: every orbital carries correlation | - |
| ethylene_twisted | def2-svpd | 1 | 2 2 | 0.11 | 2 2 | 1.4 | recommended | 1 | True | - | 0 | 0 | reached a fixed point: every orbital carries correlation | - |
| formaldehyde | def2-svpd | 3 | 6 4 | 0.1 | 6 4 | 1.6 | recommended | 1 | True | - | 1 | 1 | reached a fixed point: every orbital carries correlation | - |
| formamide | def2-svpd | 3 | 10 6 | 0.17 | 10 6 | 12.4 | recommended | 1 | True | - | 1 | 1 | reached a fixed point: every orbital carries correlation | - |
| furan | def2-svpd | 3 | 8 6 | 0.34 | 6 5 | 7.8 | narrowed | 1 | True | narrow | 1 | 1 | reached a fixed point: every orbital carries correlation | - |
| hydrogen_sulfide | def2-svpd | 1 | 8 6 | 0.07 | 4 4 | 4.8 | recommended | 2 | True | prune prune | 0 | 0 | the prune was rejected and undone: the ground state rose 18.9 mHartree (0.51 eV) | - |
| methane | def2-svpd | 1 | 8 8 | 0.07 | 8 8 | 0.9 | recommended | 1 | True | - | 0 | 0 | pruning would leave no correlated pair, so the space is left as it is | - |
| methanethiol | def2-svpd | 1 | 14 12 | 0.12 | 14 12 | 110.3 | recommended | 1 | True | - | 0 | 0 | the prune was rejected and undone: the ground state rose 36.8 mHartree (1.00 eV) | - |
| methylamine | def2-svpd | 1 | 14 13 | 0.12 | 14 13 | 195.8 | recommended | 1 | True | - | 0 | 0 | the prune was rejected and undone: the ground state rose 41.3 mHartree (1.12 eV) | - |
| o-nitrophenol | - | - | 24 17 | - | - | 600 | - | - | - | - | - | - | - | True |
| ozone | def2-svpd | 1 | 14 10 | 0.09 | 14 10 | 11.2 | recommended | 1 | True | - | 0 | 0 | the prune was rejected and undone: the ground state rose 16.4 mHartree (0.45 eV) | - |
| p-benzoquinone | - | - | 16 12 | - | - | 600 | - | - | - | - | - | - | - | True |
| pyridine | def2-svpd | 3 | 8 7 | 0.55 | 8 7 | 24.1 | recommended | 1 | True | - | 2 | 2 | reached a fixed point: every orbital carries correlation | - |
| pyrrole | def2-svpd | 3 | 8 6 | 0.34 | 6 5 | 7.7 | narrowed | 1 | True | narrow | 0 | 0 | reached a fixed point: every orbital carries correlation | - |
| trimethylenemethane | def2-svpd | 1 | 4 4 | 0.48 | 4 4 | 3.4 | recommended | 1 | True | - | 0 | 0 | reached a fixed point: every orbital carries correlation | - |
| uracil | def2-svpd | 3 | 22 14 | 1.09 | 14 10 | 558.1 | narrowed | 1 | True | narrow | 2 | 2 | the prune was rejected and undone: the ground state rose 11.1 mHartree (0.30 eV) | - |
| water | def2-svpd | 1 | 8 6 | 0.07 | 4 4 | 2.7 | recommended | 2 | True | prune prune | 0 | 0 | reached a fixed point: every orbital carries correlation | - |
