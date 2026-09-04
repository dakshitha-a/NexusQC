# casbench: spaces

Produced at commit `8ef8abf` on 2026-09-04 01:31, in 9s.

Written by `scripts/casbench/run_bench.py`. Do not edit by hand: the
next run overwrites it. Interpretation belongs in
`docs/CAS_ENGINE_METHOD.md`, not here.

| molecule | reference | reference_note | reference_source | recommended | tiers | match | seconds | legacy | legacy_seconds | legacy_error |
|---|---|---|---|---|---|---|---|---|---|---|
| N2 | 10 8 | the full valence space | Roos | 10 8 | {'recommended': [10, 8], 'minimal': [2, 4], 'maximal': [10, 8]} | exact | 0.26 | 8 7 | 0.05 | - |
| O2 | 12 8 | the full valence space | Roos | 12 8 | {'recommended': [12, 8], 'minimal': [6, 5], 'maximal': [12, 8]} | exact | 0.07 | - | 0 | refuses open-shell molecules |
| acetone | 6 4 | the carbonyl pi system and the oxygen lone pairs | Thiel | 6 4 | {'recommended': [6, 4], 'minimal': [6, 4], 'maximal': [24, 22]} | exact | 0.24 | 18 12 | 0.2 | - |
| acrolein | 8 7 | the four pi orbitals plus the oxygen lone pair and the carbonyl pi system | Thiel | 8 6 | {'recommended': [8, 6], 'minimal': [8, 6], 'maximal': [22, 20]} | differs | 0.2 | 14 12 | 0.19 | - |
| benzene | 6 6 | the six pi orbitals | Roos | 6 6 | {'recommended': [6, 6], 'minimal': [6, 6], 'maximal': [30, 30]} | exact | 0.42 | 12 12 | 0.34 | - |
| butadiene | 4 4 | the four pi orbitals | Roos | 4 4 | {'recommended': [4, 4], 'minimal': [4, 4], 'maximal': [22, 22]} | exact | 0.22 | 16 12 | 0.18 | - |
| ethylene | 2 2 | the pi/pi* pair | Roos | 2 2 | {'recommended': [2, 2], 'minimal': [2, 2], 'maximal': [12, 12]} | exact | 0.09 | 10 7 | 0.08 | - |
| formaldehyde | 6 4 | pi, pi* and the two oxygen lone pairs; the smaller (4,3) n/pi/pi* space is also standard | Roos | 6 4 | {'recommended': [6, 4], 'minimal': [6, 4], 'maximal': [12, 10]} | exact | 0.1 | 10 7 | 0.1 | - |
| formamide | 8 7 | the amide pi system plus the oxygen lone pairs; the description names five orbitals and the count is seven -- see the note above | Thiel | 10 6 | {'recommended': [10, 6], 'minimal': [10, 6], 'maximal': [18, 15]} | differs | 0.15 | 16 11 | 0.14 | - |
| furan | 6 5 | the five pi orbitals of the ring | Thiel | 8 6 | {'recommended': [8, 6], 'minimal': [8, 6], 'maximal': [26, 24]} | differs | 0.29 | 14 12 | 0.24 | - |
| p-benzoquinone | 12 10 | the ring and carbonyl pi systems plus the oxygen lone pairs | Thiel | 16 12 | {'recommended': [16, 12], 'minimal': [16, 12], 'maximal': [40, 36]} | differs | 0.83 | 12 12 | 0.66 | - |
| pyridine | 8 7 | the six ring pi orbitals plus the nitrogen lone pair | Thiel | 8 7 | {'recommended': [8, 7], 'minimal': [8, 7], 'maximal': [30, 29]} | exact | 0.48 | 12 12 | 0.38 | - |
| pyrrole | 6 5 | the five pi orbitals of the ring | Thiel | 8 6 | {'recommended': [8, 6], 'minimal': [6, 5], 'maximal': [26, 25]} | tier | 0.3 | 14 12 | 0.24 | - |
| uracil | 14 10 | five pi, both carbonyl lone pairs and three pi*. One lone pair is not enough: with 5pi+1n+3pi* an SA-CASSCF over six roots produces no n->pi* state at all, because the n->pi* hole is a combination of both oxygens' lone pairs | Thiel | 22 14 | {'recommended': [22, 14], 'minimal': [22, 14], 'maximal': [42, 36]} | differs | 0.91 | 12 12 | 0.69 | - |
| water | 8 6 | the valence space; there is no pi system | Roos | 8 6 | {'recommended': [8, 6], 'minimal': [8, 6], 'maximal': [8, 6]} | exact | 0.07 | 8 6 | 0.06 | - |
