# casbench: narrowed

Produced at commit `ad4a86e` on 2026-09-05 01:46, in 972s.

Written by `scripts/casbench/run_bench.py`. Do not edit by hand: the
next run overwrites it. Interpretation belongs in
`docs/CAS_ENGINE_METHOD.md`, not here.

| molecule | n_states | reference | pool | recommended | narrowed | match | basis | n_csf | seconds |
|---|---|---|---|---|---|---|---|---|---|
| N2 | 1 | 10 8 | 10 8 | 10 8 | False | exact | def2-svp | 1176 | 0.74 |
| N2_stretched | 1 | 10 8 | 10 8 | 10 8 | False | exact | def2-svp | 1176 | 0.35 |
| O2 | 1 | 12 8 | 12 8 | 12 8 | False | exact | def2-svp | 378 | 0.37 |
| acetone | 3 | 6 4 | 6 4 | 6 4 | False | exact | def2-svpd | 10 | 65.55 |
| acrolein | 3 | 8 7 | 8 6 | 8 6 | False | differs | def2-svpd | 105 | 46.8 |
| allyl_anion | 1 | 4 3 | 4 3 | 4 3 | False | exact | def2-svp | 6 | 0.52 |
| allyl_cation | 1 | 2 3 | 2 3 | 2 3 | False | exact | def2-svp | 6 | 0.5 |
| ammonia | 1 | 8 7 | 8 7 | 8 7 | False | exact | def2-svp | 490 | 0.37 |
| anthracene | 1 | 14 14 | 14 14 | 14 14 | False | exact | def2-svp | 2760615 | 7.5 |
| benzene | 3 | 6 6 | 6 6 | 6 6 | False | exact | def2-svpd | 175 | 84.62 |
| butadiene | 3 | 4 4 | 4 4 | 4 4 | False | exact | def2-svpd | 20 | 61.14 |
| cyclobutadiene_square | 1 | 4 4 | 4 4 | 4 4 | False | exact | def2-svp | 20 | 0.61 |
| cyclopentadienyl_anion | 1 | 6 5 | 6 5 | 6 5 | False | exact | def2-svp | 50 | 0.76 |
| ethylene | 2 | 2 2 | 2 2 | 2 2 | False | exact | def2-svpd | 3 | 8.14 |
| ethylene_twisted | 1 | 2 2 | 2 2 | 2 2 | False | exact | def2-svp | 3 | 0.42 |
| formaldehyde | 3 | 6 4 | 6 4 | 6 4 | False | exact | def2-svpd | 10 | 4.8 |
| formamide | 3 | 8 7 | 8 5 | 8 5 | False | differs | def2-svpd | 15 | 15.06 |
| furan | 3 | 6 5 | 8 6 | 6 5 | True | exact | def2-svpd | 50 | 75.55 |
| hexatriene | 1 | 6 6 | 6 6 | 6 6 | False | exact | def2-svp | 175 | 1.13 |
| hydrogen_sulfide | 1 | 8 6 | 8 6 | 8 6 | False | exact | def2-svp | 105 | 0.37 |
| naphthalene | 1 | 10 10 | 10 10 | 10 10 | False | exact | def2-svp | 19404 | 2.85 |
| octatetraene | 1 | 8 8 | 8 8 | 8 8 | False | exact | def2-svp | 1764 | 2.14 |
| p-benzoquinone | 3 | 12 10 | 16 12 | 16 12 | False | differs | def2-svpd | 70785 | 205.3 |
| pyridine | 3 | 8 7 | 8 7 | 8 7 | False | exact | def2-svpd | 490 | 132.2 |
| pyridinium | 1 | 6 6 | 6 6 | 6 6 | False | exact | def2-svp | 175 | 1 |
| pyrrole | 3 | 6 5 | 6 5 | 6 5 | False | exact | def2-svpd | 50 | 51.65 |
| trimethylenemethane | 1 | 4 4 | 4 4 | 4 4 | False | exact | def2-svp | 15 | 0.76 |
| tropylium | 1 | 6 7 | 6 7 | 6 7 | False | exact | def2-svp | 490 | 1.21 |
| uracil | 3 | 14 10 | 18 12 | 14 10 | True | exact | def2-svpd | 4950 | 199.2 |
| water | 1 | 8 6 | 8 6 | 8 6 | False | exact | def2-svp | 105 | 0.35 |
