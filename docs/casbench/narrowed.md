# casbench: narrowed

Produced at commit `09e13f5` on 2026-09-06 07:09, in 2041s, with omp=8, mkl=12.

Written by `scripts/casbench/run_bench.py`. Do not edit by hand: the
next run overwrites it. Interpretation belongs in
`docs/CAS_ENGINE_METHOD.md`, not here.

| molecule | n_states | reference | pool | recommended | narrowed | match | basis | n_csf | seconds |
|---|---|---|---|---|---|---|---|---|---|
| N2 | 1 | 10 8 | 10 8 | 10 8 | False | exact | def2-svp | 1176 | 0.55 |
| N2_stretched | 1 | 10 8 | 10 8 | 10 8 | False | exact | def2-svp | 1176 | 0.55 |
| O2 | 1 | 12 8 | 12 8 | 12 8 | False | exact | def2-svp | 378 | 0.74 |
| acetone | 3 | 6 4 | 6 4 | 6 4 | False | exact | aug-cc-pvdz | 10 | 99.28 |
| acrolein | 3 | 8 7 | 8 6 | 8 6 | False | differs | aug-cc-pvdz | 105 | 69.04 |
| allyl_anion | 1 | 4 3 | 4 3 | 4 3 | False | exact | def2-svp | 6 | 1.37 |
| allyl_cation | 1 | 2 3 | 2 3 | 2 3 | False | exact | def2-svp | 6 | 1.26 |
| ammonia | 1 | 8 7 | 8 7 | 8 7 | False | exact | def2-svp | 490 | 0.43 |
| anthracene | 1 | 14 14 | 14 14 | 14 14 | False | exact | def2-svp | 2760615 | 213.8 |
| benzene | 3 | 6 6 | 6 6 | 6 6 | False | exact | aug-cc-pvdz | 175 | 171.7 |
| butadiene | 3 | 4 4 | 4 4 | 4 4 | False | exact | aug-cc-pvdz | 20 | 79 |
| cyclobutadiene_square | 1 | 4 4 | 4 4 | 4 4 | False | exact | def2-svp | 20 | 3.69 |
| cyclopentadienyl_anion | 1 | 6 5 | 6 5 | 6 5 | False | exact | def2-svp | 50 | 4.6 |
| ethylene | 2 | 2 2 | 2 2 | 2 2 | False | exact | aug-cc-pvdz | 3 | 12.69 |
| ethylene_twisted | 1 | 2 2 | 2 2 | 2 2 | False | exact | def2-svp | 3 | 0.77 |
| formaldehyde | 3 | 6 4 | 6 4 | 6 4 | False | exact | aug-cc-pvdz | 10 | 6.08 |
| formamide | 3 | 8 7 | 8 5 | 8 5 | False | differs | aug-cc-pvdz | 15 | 20.97 |
| furan | 3 | 6 5 | 8 6 | 6 5 | True | exact | aug-cc-pvdz | 50 | 93.99 |
| hexatriene | 1 | 6 6 | 6 6 | 6 6 | False | exact | def2-svp | 175 | 11.58 |
| hydrogen_sulfide | 1 | 8 6 | 8 6 | 8 6 | False | exact | def2-svp | 105 | 0.42 |
| naphthalene | 1 | 10 10 | 10 10 | 10 10 | False | exact | def2-svp | 19404 | 50.39 |
| octatetraene | 1 | 8 8 | 8 8 | 8 8 | False | exact | def2-svp | 1764 | 41.62 |
| p-benzoquinone | 3 | 12 10 | 16 12 | 16 12 | False | differs | aug-cc-pvdz | 70785 | 357 |
| pyridine | 3 | 8 7 | 8 7 | 8 7 | False | exact | aug-cc-pvdz | 490 | 193.4 |
| pyridinium | 1 | 6 6 | 6 6 | 6 6 | False | exact | def2-svp | 175 | 8.8 |
| pyrrole | 3 | 6 5 | 6 5 | 6 5 | False | exact | aug-cc-pvdz | 50 | 102.1 |
| trimethylenemethane | 1 | 4 4 | 4 4 | 4 4 | False | exact | def2-svp | 15 | 4.46 |
| tropylium | 1 | 6 7 | 6 7 | 6 7 | False | exact | def2-svp | 490 | 15.84 |
| uracil | 3 | 14 10 | 18 12 | 14 10 | True | exact | aug-cc-pvdz | 4950 | 474.9 |
| water | 1 | 8 6 | 8 6 | 8 6 | False | exact | def2-svp | 105 | 0.4 |
