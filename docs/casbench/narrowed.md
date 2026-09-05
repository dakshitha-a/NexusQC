# casbench: narrowed

Produced at commit `86b8dc3` on 2026-09-04 21:18, in 940s.

Written by `scripts/casbench/run_bench.py`. Do not edit by hand: the
next run overwrites it. Interpretation belongs in
`docs/CAS_ENGINE_METHOD.md`, not here.

| molecule | n_states | reference | pool | recommended | narrowed | match | basis | n_csf | seconds |
|---|---|---|---|---|---|---|---|---|---|
| N2 | 1 | 10 8 | 10 8 | 10 8 | False | exact | def2-svp | 1176 | 0.72 |
| N2_stretched | 1 | 10 8 | 10 8 | 10 8 | False | exact | def2-svp | 1176 | 0.34 |
| O2 | 1 | 12 8 | 12 8 | 12 8 | False | exact | def2-svp | 378 | 0.35 |
| acetone | 3 | 6 4 | 6 4 | 6 4 | False | exact | def2-svpd | 10 | 63.79 |
| acrolein | 3 | 8 7 | 8 6 | 8 6 | False | differs | def2-svpd | 105 | 45.28 |
| allyl_anion | 1 | 4 3 | 4 3 | 4 3 | False | exact | def2-svp | 6 | 0.5 |
| allyl_cation | 1 | 2 3 | 2 3 | 2 3 | False | exact | def2-svp | 6 | 0.49 |
| ammonia | 1 | 8 7 | 8 7 | 8 7 | False | exact | def2-svp | 490 | 0.35 |
| anthracene | 1 | 14 14 | 14 14 | 14 14 | False | exact | def2-svp | 2760615 | 7.71 |
| benzene | 3 | 6 6 | 6 6 | 6 6 | False | exact | def2-svpd | 175 | 82.43 |
| butadiene | 3 | 4 4 | 4 4 | 4 4 | False | exact | def2-svpd | 20 | 58.48 |
| cyclobutadiene_square | 1 | 4 4 | 4 4 | 4 4 | False | exact | def2-svp | 20 | 0.6 |
| cyclopentadienyl_anion | 1 | 6 5 | 6 5 | 6 5 | False | exact | def2-svp | 50 | 0.73 |
| ethylene | 2 | 2 2 | 2 2 | 2 2 | False | exact | def2-svpd | 3 | 7.78 |
| ethylene_twisted | 1 | 2 2 | 2 2 | 2 2 | False | exact | def2-svp | 3 | 0.4 |
| formaldehyde | 3 | 6 4 | 6 4 | 6 4 | False | exact | def2-svpd | 10 | 4.64 |
| formamide | 3 | 8 7 | 8 5 | 8 5 | False | differs | def2-svpd | 15 | 14.75 |
| furan | 3 | 6 5 | 8 6 | 6 5 | True | exact | def2-svpd | 50 | 73.03 |
| hexatriene | 1 | 6 6 | 6 6 | 6 6 | False | exact | def2-svp | 175 | 1.08 |
| hydrogen_sulfide | 1 | 8 6 | 8 6 | 8 6 | False | exact | def2-svp | 105 | 0.35 |
| naphthalene | 1 | 10 10 | 10 10 | 10 10 | False | exact | def2-svp | 19404 | 2.83 |
| octatetraene | 1 | 8 8 | 8 8 | 8 8 | False | exact | def2-svp | 1764 | 2.12 |
| p-benzoquinone | 3 | 12 10 | 16 12 | 16 12 | False | differs | def2-svpd | 70785 | 197.6 |
| pyridine | 3 | 8 7 | 8 7 | 8 7 | False | exact | def2-svpd | 490 | 126.3 |
| pyridinium | 1 | 6 6 | 6 6 | 6 6 | False | exact | def2-svp | 175 | 0.98 |
| pyrrole | 3 | 6 5 | 6 5 | 6 5 | False | exact | def2-svpd | 50 | 50.59 |
| trimethylenemethane | 1 | 4 4 | 4 4 | 4 4 | False | exact | def2-svp | 15 | 0.74 |
| tropylium | 1 | 6 7 | 6 7 | 6 7 | False | exact | def2-svp | 490 | 1.18 |
| uracil | 3 | 14 10 | 18 12 | 14 10 | True | exact | def2-svpd | 4950 | 192.9 |
| water | 1 | 8 6 | 8 6 | 8 6 | False | exact | def2-svp | 105 | 0.34 |
