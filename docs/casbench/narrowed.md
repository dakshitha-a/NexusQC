# casbench: narrowed

Produced at commit `c5a8fbc` on 2026-10-14 16:54, in 1970s, with omp=8, mkl=12.

Written by `scripts/casbench/run_bench.py`. Do not edit by hand: the
next run overwrites it. Interpretation belongs in
`docs/CAS_ENGINE_METHOD.md`, not here.

| molecule | n_states | reference | pool | recommended | narrowed | match | basis | n_csf | seconds |
|---|---|---|---|---|---|---|---|---|---|
| N2 | 1 | 10 8 | 10 8 | 10 8 | False | exact | def2-svp | 1176 | 0.83 |
| N2_stretched | 1 | 10 8 | 10 8 | 10 8 | False | exact | def2-svp | 1176 | 0.5 |
| O2 | 1 | 12 8 | 12 8 | 12 8 | False | exact | def2-svp | 378 | 0.61 |
| acetone | 3 | 6 4 | 6 4 | 6 4 | False | exact | aug-cc-pvdz | 10 | 92.69 |
| acrolein | 3 | 8 7 | 8 6 | 8 6 | False | differs | aug-cc-pvdz | 105 | 63.49 |
| allyl_anion | 1 | 4 3 | 4 3 | 4 3 | False | exact | def2-svp | 6 | 1.32 |
| allyl_cation | 1 | 2 3 | 2 3 | 2 3 | False | exact | def2-svp | 6 | 1.2 |
| ammonia | 1 | 8 7 | 8 7 | 8 7 | False | exact | def2-svp | 490 | 0.41 |
| anthracene | 1 | 14 14 | 14 14 | 14 14 | False | exact | def2-svp | 2760615 | 212.8 |
| benzene | 3 | 6 6 | 6 6 | 6 6 | False | exact | aug-cc-pvdz | 175 | 170.6 |
| butadiene | 3 | 4 4 | 4 4 | 4 4 | False | exact | aug-cc-pvdz | 20 | 79.07 |
| cyclobutadiene_square | 1 | 4 4 | 4 4 | 4 4 | False | exact | def2-svp | 20 | 3.93 |
| cyclopentadienyl_anion | 1 | 6 5 | 6 5 | 6 5 | False | exact | def2-svp | 50 | 4.74 |
| ethylene | 2 | 2 2 | 2 2 | 2 2 | False | exact | aug-cc-pvdz | 3 | 12.4 |
| ethylene_twisted | 1 | 2 2 | 2 2 | 2 2 | False | exact | def2-svp | 3 | 0.68 |
| formaldehyde | 3 | 6 4 | 6 4 | 6 4 | False | exact | aug-cc-pvdz | 10 | 5.94 |
| formamide | 3 | 8 7 | 8 5 | 8 5 | False | differs | aug-cc-pvdz | 15 | 19.42 |
| furan | 3 | 6 5 | 8 6 | 6 5 | True | exact | aug-cc-pvdz | 50 | 89.41 |
| hexatriene | 1 | 6 6 | 6 6 | 6 6 | False | exact | def2-svp | 175 | 11.49 |
| hydrogen_sulfide | 1 | 8 6 | 8 6 | 8 6 | False | exact | def2-svp | 105 | 0.41 |
| naphthalene | 1 | 10 10 | 10 10 | 10 10 | False | exact | def2-svp | 19404 | 49.8 |
| octatetraene | 1 | 8 8 | 8 8 | 8 8 | False | exact | def2-svp | 1764 | 35.27 |
| p-benzoquinone | 3 | 12 10 | 16 12 | 16 12 | False | differs | aug-cc-pvdz | 70785 | 353.5 |
| pyridine | 3 | 8 7 | 8 7 | 8 7 | False | exact | aug-cc-pvdz | 490 | 180.2 |
| pyridinium | 1 | 6 6 | 6 6 | 6 6 | False | exact | def2-svp | 175 | 8.34 |
| pyrrole | 3 | 6 5 | 6 5 | 6 5 | False | exact | aug-cc-pvdz | 50 | 95.26 |
| trimethylenemethane | 1 | 4 4 | 4 4 | 4 4 | False | exact | def2-svp | 15 | 4.1 |
| tropylium | 1 | 6 7 | 6 7 | 6 7 | False | exact | def2-svp | 490 | 14.56 |
| uracil | 3 | 14 10 | 18 12 | 14 10 | True | exact | aug-cc-pvdz | 4950 | 456.2 |
| water | 1 | 8 6 | 8 6 | 8 6 | False | exact | def2-svp | 105 | 0.38 |
