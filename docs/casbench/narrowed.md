# casbench: narrowed

Produced at commit `c6d1c4f` on 2026-09-04 09:38, in 943s.

Written by `scripts/casbench/run_bench.py`. Do not edit by hand: the
next run overwrites it. Interpretation belongs in
`docs/CAS_ENGINE_METHOD.md`, not here.

| molecule | n_states | reference | pool | recommended | narrowed | match | basis | n_csf | seconds |
|---|---|---|---|---|---|---|---|---|---|
| N2 | 1 | 10 8 | 10 8 | 10 8 | False | exact | def2-svp | 1176 | 0.72 |
| O2 | 1 | 12 8 | 12 8 | 12 8 | False | exact | def2-svp | 378 | 0.36 |
| acetone | 3 | 6 4 | 6 4 | 6 4 | False | exact | def2-svpd | 10 | 64.06 |
| acrolein | 3 | 8 7 | 8 6 | 8 6 | False | differs | def2-svpd | 105 | 45.55 |
| benzene | 3 | 6 6 | 6 6 | 6 6 | False | exact | def2-svpd | 175 | 82.45 |
| butadiene | 3 | 4 4 | 4 4 | 4 4 | False | exact | def2-svpd | 20 | 59.67 |
| ethylene | 2 | 2 2 | 2 2 | 2 2 | False | exact | def2-svpd | 3 | 7.82 |
| formaldehyde | 3 | 6 4 | 6 4 | 6 4 | False | exact | def2-svpd | 10 | 4.66 |
| formamide | 3 | 8 7 | 10 6 | 10 6 | False | differs | def2-svpd | 21 | 14.73 |
| furan | 3 | 6 5 | 8 6 | 6 5 | True | exact | def2-svpd | 50 | 73.18 |
| p-benzoquinone | 3 | 12 10 | 16 12 | 16 12 | False | differs | def2-svpd | 70785 | 198.6 |
| pyridine | 3 | 8 7 | 8 7 | 8 7 | False | exact | def2-svpd | 490 | 126 |
| pyrrole | 3 | 6 5 | 8 6 | 6 5 | True | exact | def2-svpd | 50 | 53.94 |
| uracil | 3 | 14 10 | 22 14 | 14 10 | True | exact | def2-svpd | 4950 | 210 |
| water | 1 | 8 6 | 8 6 | 8 6 | False | exact | def2-svp | 105 | 0.35 |
