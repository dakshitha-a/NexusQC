# casbench: narrowed

Produced at commit `83e1565` on 2026-09-05 19:14, in 1997s, with omp=8, mkl=12.

Written by `scripts/casbench/run_bench.py`. Do not edit by hand: the
next run overwrites it. Interpretation belongs in
`docs/CAS_ENGINE_METHOD.md`, not here.

| molecule | n_states | reference | pool | recommended | narrowed | match | basis | n_csf | seconds |
|---|---|---|---|---|---|---|---|---|---|
| N2 | 1 | 10 8 | 10 8 | 10 8 | False | exact | def2-svp | 1176 | 0.82 |
| N2_stretched | 1 | 10 8 | 10 8 | 10 8 | False | exact | def2-svp | 1176 | 0.5 |
| O2 | 1 | 12 8 | 12 8 | 12 8 | False | exact | def2-svp | 378 | 0.71 |
| acetone | 3 | 6 4 | 6 4 | 6 4 | False | exact | aug-cc-pvdz | 10 | 98.94 |
| acrolein | 3 | 8 7 | 8 6 | 8 6 | False | differs | aug-cc-pvdz | 105 | 67.36 |
| allyl_anion | 1 | 4 3 | 4 3 | 4 3 | False | exact | def2-svp | 6 | 1.37 |
| allyl_cation | 1 | 2 3 | 2 3 | 2 3 | False | exact | def2-svp | 6 | 1.24 |
| ammonia | 1 | 8 7 | 8 7 | 8 7 | False | exact | def2-svp | 490 | 0.43 |
| anthracene | 1 | 14 14 | 14 14 | 14 14 | False | exact | def2-svp | 2760615 | 216 |
| benzene | 3 | 6 6 | 6 6 | 6 6 | False | exact | aug-cc-pvdz | 175 | 173.7 |
| butadiene | 3 | 4 4 | 4 4 | 4 4 | False | exact | aug-cc-pvdz | 20 | 83.19 |
| cyclobutadiene_square | 1 | 4 4 | 4 4 | 4 4 | False | exact | def2-svp | 20 | 4.1 |
| cyclopentadienyl_anion | 1 | 6 5 | 6 5 | 6 5 | False | exact | def2-svp | 50 | 5.07 |
| ethylene | 2 | 2 2 | 2 2 | 2 2 | False | exact | aug-cc-pvdz | 3 | 12.9 |
| ethylene_twisted | 1 | 2 2 | 2 2 | 2 2 | False | exact | def2-svp | 3 | 0.68 |
| formaldehyde | 3 | 6 4 | 6 4 | 6 4 | False | exact | aug-cc-pvdz | 10 | 6.23 |
| formamide | 3 | 8 7 | 8 5 | 8 5 | False | differs | aug-cc-pvdz | 15 | 20.2 |
| furan | 3 | 6 5 | 8 6 | 6 5 | True | exact | aug-cc-pvdz | 50 | 97.91 |
| hexatriene | 1 | 6 6 | 6 6 | 6 6 | False | exact | def2-svp | 175 | 12.63 |
| hydrogen_sulfide | 1 | 8 6 | 8 6 | 8 6 | False | exact | def2-svp | 105 | 0.46 |
| naphthalene | 1 | 10 10 | 10 10 | 10 10 | False | exact | def2-svp | 19404 | 53.51 |
| octatetraene | 1 | 8 8 | 8 8 | 8 8 | False | exact | def2-svp | 1764 | 34.53 |
| p-benzoquinone | 3 | 12 10 | 16 12 | 16 12 | False | differs | aug-cc-pvdz | 70785 | 336.1 |
| pyridine | 3 | 8 7 | 8 7 | 8 7 | False | exact | aug-cc-pvdz | 490 | 184.1 |
| pyridinium | 1 | 6 6 | 6 6 | 6 6 | False | exact | def2-svp | 175 | 8.43 |
| pyrrole | 3 | 6 5 | 6 5 | 6 5 | False | exact | aug-cc-pvdz | 50 | 99.09 |
| trimethylenemethane | 1 | 4 4 | 4 4 | 4 4 | False | exact | def2-svp | 15 | 4.21 |
| tropylium | 1 | 6 7 | 6 7 | 6 7 | False | exact | def2-svp | 490 | 15.02 |
| uracil | 3 | 14 10 | 18 12 | 14 10 | True | exact | aug-cc-pvdz | 4950 | 456.6 |
| water | 1 | 8 6 | 8 6 | 8 6 | False | exact | def2-svp | 105 | 0.39 |
