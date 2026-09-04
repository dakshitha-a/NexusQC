# casbench: narrowed

Produced at commit `9254f4f` on 2026-09-04 09:58, in 921s.

Written by `scripts/casbench/run_bench.py`. Do not edit by hand: the
next run overwrites it. Interpretation belongs in
`docs/CAS_ENGINE_METHOD.md`, not here.

| molecule | n_states | reference | pool | recommended | narrowed | match | basis | n_csf | seconds |
|---|---|---|---|---|---|---|---|---|---|
| N2 | 1 | 10 8 | 10 8 | 10 8 | False | exact | def2-svp | 1176 | 0.76 |
| N2_stretched | 1 | 10 8 | 10 8 | 10 8 | False | exact | def2-svp | 1176 | 0.35 |
| O2 | 1 | 12 8 | 12 8 | 12 8 | False | exact | def2-svp | 378 | 0.37 |
| acetone | 3 | 6 4 | 6 4 | 6 4 | False | exact | def2-svpd | 10 | 64.04 |
| acrolein | 3 | 8 7 | 8 6 | 8 6 | False | differs | def2-svpd | 105 | 44.62 |
| ammonia | 1 | 8 7 | 8 7 | 8 7 | False | exact | def2-svp | 490 | 0.35 |
| benzene | 3 | 6 6 | 6 6 | 6 6 | False | exact | def2-svpd | 175 | 80.37 |
| butadiene | 3 | 4 4 | 4 4 | 4 4 | False | exact | def2-svpd | 20 | 59.54 |
| cyclobutadiene_square | 1 | 4 4 | 4 4 | 4 4 | False | exact | def2-svp | 20 | 0.61 |
| ethylene | 2 | 2 2 | 2 2 | 2 2 | False | exact | def2-svpd | 3 | 7.92 |
| ethylene_twisted | 1 | 2 2 | 2 2 | 2 2 | False | exact | def2-svp | 3 | 0.4 |
| formaldehyde | 3 | 6 4 | 6 4 | 6 4 | False | exact | def2-svpd | 10 | 4.66 |
| formamide | 3 | 8 7 | 10 6 | 10 6 | False | differs | def2-svpd | 21 | 14.78 |
| furan | 3 | 6 5 | 8 6 | 6 5 | True | exact | def2-svpd | 50 | 74.16 |
| hydrogen_sulfide | 1 | 8 6 | 8 6 | 8 6 | False | exact | def2-svp | 105 | 0.41 |
| p-benzoquinone | 3 | 12 10 | 16 12 | 16 12 | False | differs | def2-svpd | 70785 | 200.6 |
| pyridine | 3 | 8 7 | 8 7 | 8 7 | False | exact | def2-svpd | 490 | 124.4 |
| pyrrole | 3 | 6 5 | 8 6 | 6 5 | True | exact | def2-svpd | 50 | 50.67 |
| trimethylenemethane | 1 | 4 4 | 4 4 | 4 4 | False | exact | def2-svp | 15 | 0.75 |
| uracil | 3 | 14 10 | 22 14 | 14 10 | True | exact | def2-svpd | 4950 | 190.9 |
| water | 1 | 8 6 | 8 6 | 8 6 | False | exact | def2-svp | 105 | 0.35 |
