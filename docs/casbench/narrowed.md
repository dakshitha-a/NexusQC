# casbench: narrowed

Produced at commit `11b7d4f+dirty` on 2026-10-06 22:06, in 3199s, with omp=8, mkl=12.

Written by `scripts/casbench/run_bench.py`. Do not edit by hand: the
next run overwrites it. Interpretation belongs in
`docs/CAS_ENGINE_METHOD.md`, not here.

| molecule | n_states | reference | pool | recommended | narrowed | match | basis | n_csf | seconds |
|---|---|---|---|---|---|---|---|---|---|
| N2 | 1 | 10 8 | 10 8 | 10 8 | False | exact | def2-svp | 1176 | 1.14 |
| N2_stretched | 1 | 10 8 | 10 8 | 10 8 | False | exact | def2-svp | 1176 | 0.7 |
| O2 | 1 | 12 8 | 12 8 | 12 8 | False | exact | def2-svp | 378 | 0.84 |
| acetone | 3 | 6 4 | 6 4 | 6 4 | False | exact | aug-cc-pvdz | 10 | 166 |
| acrolein | 3 | 8 7 | 8 6 | 8 6 | False | differs | aug-cc-pvdz | 105 | 103.2 |
| allyl_anion | 1 | 4 3 | 4 3 | 4 3 | False | exact | def2-svp | 6 | 1.68 |
| allyl_cation | 1 | 2 3 | 2 3 | 2 3 | False | exact | def2-svp | 6 | 1.66 |
| ammonia | 1 | 8 7 | 8 7 | 8 7 | False | exact | def2-svp | 490 | 0.51 |
| anthracene | 1 | 14 14 | 14 14 | 14 14 | False | exact | def2-svp | 2760615 | 318.9 |
| benzene | 3 | 6 6 | 6 6 | 6 6 | False | exact | aug-cc-pvdz | 175 | 272.5 |
| butadiene | 3 | 4 4 | 4 4 | 4 4 | False | exact | aug-cc-pvdz | 20 | 137.7 |
| cyclobutadiene_square | 1 | 4 4 | 4 4 | 4 4 | False | exact | def2-svp | 20 | 5.61 |
| cyclopentadienyl_anion | 1 | 6 5 | 6 5 | 6 5 | False | exact | def2-svp | 50 | 6.61 |
| ethylene | 2 | 2 2 | 2 2 | 2 2 | False | exact | aug-cc-pvdz | 3 | 18.28 |
| ethylene_twisted | 1 | 2 2 | 2 2 | 2 2 | False | exact | def2-svp | 3 | 0.91 |
| formaldehyde | 3 | 6 4 | 6 4 | 6 4 | False | exact | aug-cc-pvdz | 10 | 7.87 |
| formamide | 3 | 8 7 | 8 5 | 8 5 | False | differs | aug-cc-pvdz | 15 | 36.61 |
| furan | 3 | 6 5 | 8 6 | 6 5 | True | exact | aug-cc-pvdz | 50 | 164.3 |
| hexatriene | 1 | 6 6 | 6 6 | 6 6 | False | exact | def2-svp | 175 | 17.77 |
| hydrogen_sulfide | 1 | 8 6 | 8 6 | 8 6 | False | exact | def2-svp | 105 | 0.62 |
| naphthalene | 1 | 10 10 | 10 10 | 10 10 | False | exact | def2-svp | 19404 | 73.76 |
| octatetraene | 1 | 8 8 | 8 8 | 8 8 | False | exact | def2-svp | 1764 | 53.24 |
| p-benzoquinone | 3 | 12 10 | 16 12 | 16 12 | False | differs | aug-cc-pvdz | 70785 | 590.3 |
| pyridine | 3 | 8 7 | 8 7 | 8 7 | False | exact | aug-cc-pvdz | 490 | 318.3 |
| pyridinium | 1 | 6 6 | 6 6 | 6 6 | False | exact | def2-svp | 175 | 15.35 |
| pyrrole | 3 | 6 5 | 6 5 | 6 5 | False | exact | aug-cc-pvdz | 50 | 154.6 |
| trimethylenemethane | 1 | 4 4 | 4 4 | 4 4 | False | exact | def2-svp | 15 | 5.88 |
| tropylium | 1 | 6 7 | 6 7 | 6 7 | False | exact | def2-svp | 490 | 22.42 |
| uracil | 3 | 14 10 | 18 12 | 14 10 | True | exact | aug-cc-pvdz | 4950 | 701.1 |
| water | 1 | 8 6 | 8 6 | 8 6 | False | exact | def2-svp | 105 | 0.52 |
