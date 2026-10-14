# casbench: spaces

Produced at commit `c5a8fbc` on 2026-10-14 16:21, in 189s, with omp=8, mkl=12.

Written by `scripts/casbench/run_bench.py`. Do not edit by hand: the
next run overwrites it. Interpretation belongs in
`docs/CAS_ENGINE_METHOD.md`, not here.

| molecule | class | reference | reference_note | reference_source | recommended | tiers | match | seconds | legacy | legacy_seconds | legacy_error |
|---|---|---|---|---|---|---|---|---|---|---|---|
| N2 | core | 10 8 | the full valence space | Roos | 10 8 | {'recommended': [10, 8], 'minimal': [2, 4], 'maximal': [10, 8]} | exact | 0.34 | 8 7 | 0.05 | - |
| N2_stretched | diradical | 10 8 | the full valence space, which at a stretched geometry is the only defensible answer: every bonding and antibonding pair of a breaking triple bond is strongly correlated | convention | 10 8 | {'recommended': [10, 8], 'minimal': [2, 4], 'maximal': [10, 8]} | exact | 0.13 | 8 7 | 0.05 | - |
| O2 | diradical | 12 8 | the full valence space | Roos | 12 8 | {'recommended': [12, 8], 'minimal': [6, 5], 'maximal': [12, 8]} | exact | 0.19 | - | 0 | refuses open-shell molecules |
| acetone | core | 6 4 | the carbonyl pi system and the oxygen lone pairs | Thiel | 6 4 | {'recommended': [6, 4], 'minimal': [6, 4], 'maximal': [24, 22]} | exact | 1.2 | 18 12 | 0.2 | - |
| acrolein | core | 8 7 | the four pi orbitals plus the oxygen lone pair and the carbonyl pi system | Thiel | 8 6 | {'recommended': [8, 6], 'minimal': [8, 6], 'maximal': [22, 20]} | differs | 0.77 | 14 12 | 0.16 | - |
| allyl_anion | charged | 4 3 | the same three pi orbitals as the cation, with two more electrons | convention | 4 3 | {'recommended': [4, 3], 'minimal': [2, 2], 'maximal': [18, 17]} | exact | 0.47 | 16 11 | 0.11 | - |
| allyl_cation | charged | 2 3 | the three-centre pi system, two electrons in three orbitals | convention | 2 3 | {'recommended': [2, 3], 'minimal': [2, 3], 'maximal': [16, 17]} | exact | 0.41 | 14 10 | 0.11 | - |
| ammonia | non-planar | 8 7 | the full valence space: three N-H sigma, the nitrogen lone pair and three sigma* | convention | 8 7 | {'recommended': [8, 7], 'minimal': [6, 6], 'maximal': [8, 7]} | exact | 0.09 | 8 7 | 0.06 | - |
| anthracene | conjugated | 14 14 | the fourteen pi orbitals | convention | 14 14 | {'recommended': [14, 14], 'minimal': [14, 14], 'maximal': [66, 66]} | exact | 89.36 | 12 12 | 4.14 | - |
| benzene | core | 6 6 | the six pi orbitals | Roos | 6 6 | {'recommended': [6, 6], 'minimal': [6, 6], 'maximal': [30, 30]} | exact | 4.07 | 12 12 | 0.3 | - |
| butadiene | core | 4 4 | the four pi orbitals | Roos | 4 4 | {'recommended': [4, 4], 'minimal': [4, 4], 'maximal': [22, 22]} | exact | 1.17 | 16 12 | 0.16 | - |
| cyclobutadiene_square | diradical | 4 4 | the four pi orbitals; the square geometry's degeneracy is the reason the molecule distorts | convention | 4 4 | {'recommended': [4, 4], 'minimal': [2, 3], 'maximal': [20, 20]} | exact | 1.59 | 14 12 | 0.17 | - |
| cyclopentadienyl_anion | charged | 6 5 | the five ring pi orbitals of the aromatic six-pi anion | convention | 6 5 | {'recommended': [6, 5], 'minimal': [4, 4], 'maximal': [26, 25]} | exact | 2.08 | 14 12 | 0.2 | - |
| ethylene | core | 2 2 | the pi/pi* pair | Roos | 2 2 | {'recommended': [2, 2], 'minimal': [2, 2], 'maximal': [12, 12]} | exact | 0.18 | 10 7 | 0.07 | - |
| ethylene_twisted | diradical | 2 2 | the broken pi bond, the textbook two-electron two-orbital biradicaloid | convention | 2 2 | {'recommended': [2, 2], 'minimal': [2, 2], 'maximal': [12, 12]} | exact | 0.24 | 10 7 | 0.09 | - |
| formaldehyde | core | 6 4 | pi, pi* and the two oxygen lone pairs; the smaller (4,3) n/pi/pi* space is also standard | Roos | 6 4 | {'recommended': [6, 4], 'minimal': [6, 4], 'maximal': [12, 10]} | exact | 0.14 | 10 7 | 0.09 | - |
| formamide | core | 8 7 | the amide pi system plus the oxygen lone pairs; the description names five orbitals and the count is seven -- see the note above | Thiel | 8 5 | {'recommended': [8, 5], 'minimal': [8, 5], 'maximal': [18, 15]} | differs | 0.36 | 16 11 | 0.13 | - |
| furan | core | 6 5 | the five pi orbitals of the ring | Thiel | 8 6 | {'recommended': [8, 6], 'minimal': [8, 6], 'maximal': [26, 24]} | differs | 1.35 | 14 12 | 0.26 | - |
| hexatriene | conjugated | 6 6 | the six pi orbitals of the all-trans chain | Thiel | 6 6 | {'recommended': [6, 6], 'minimal': [6, 6], 'maximal': [32, 32]} | exact | 5.03 | 12 12 | 0.44 | - |
| hydrogen_sulfide | non-planar | 8 6 | the full valence space: two S-H sigma, two sulfur lone pairs and two sigma*, the same shape as water's | convention | 8 6 | {'recommended': [8, 6], 'minimal': [2, 3], 'maximal': [8, 6]} | exact | 0.1 | 6 4 | 0.07 | - |
| naphthalene | conjugated | 10 10 | the ten pi orbitals | Thiel | 10 10 | {'recommended': [10, 10], 'minimal': [10, 10], 'maximal': [48, 48]} | exact | 20.05 | 12 12 | 1.39 | - |
| octatetraene | conjugated | 8 8 | the eight pi orbitals of the all-trans chain | Thiel | 8 8 | {'recommended': [8, 8], 'minimal': [8, 8], 'maximal': [42, 42]} | exact | 16.47 | 12 12 | 0.94 | - |
| p-benzoquinone | core | 12 10 | the ring and carbonyl pi systems plus the oxygen lone pairs | Thiel | 16 12 | {'recommended': [16, 12], 'minimal': [16, 12], 'maximal': [40, 36]} | differs | 6.66 | 12 12 | 0.66 | - |
| pyridine | core | 8 7 | the six ring pi orbitals plus the nitrogen lone pair | Thiel | 8 7 | {'recommended': [8, 7], 'minimal': [8, 7], 'maximal': [30, 29]} | exact | 3.15 | 12 12 | 0.38 | - |
| pyridinium | charged | 6 6 | the six ring pi orbitals; unlike pyridine there is no nitrogen lone pair to add, because the protonated nitrogen has no lone pair left | convention | 6 6 | {'recommended': [6, 6], 'minimal': [6, 6], 'maximal': [30, 30]} | exact | 3.74 | 12 12 | 0.4 | - |
| pyrrole | core | 6 5 | the five pi orbitals of the ring | Thiel | 6 5 | {'recommended': [6, 5], 'minimal': [6, 5], 'maximal': [26, 25]} | exact | 1.73 | 14 12 | 0.25 | - |
| trimethylenemethane | diradical | 4 4 | the four pi orbitals, two of them exactly degenerate, which is why the ground state is a triplet | convention | 4 4 | {'recommended': [4, 4], 'minimal': [4, 4], 'maximal': [22, 22]} | exact | 2.01 | - | 0 | refuses open-shell molecules |
| tropylium | charged | 6 7 | the seven ring pi orbitals of the aromatic six-pi cation | convention | 6 7 | {'recommended': [6, 7], 'minimal': [6, 7], 'maximal': [34, 35]} | exact | 5.88 | 12 12 | 0.47 | - |
| uracil | core | 14 10 | five pi, both carbonyl lone pairs and three pi*. One lone pair is not enough: with 5pi+1n+3pi* an SA-CASSCF over six roots produces no n->pi* state at all, because the n->pi* hole is a combination of both oxygens' lone pairs | Thiel | 18 12 | {'recommended': [18, 12], 'minimal': [18, 12], 'maximal': [42, 36]} | differs | 7.7 | 12 12 | 0.75 | - |
| water | non-planar | 8 6 | the valence space; there is no pi system | Roos | 8 6 | {'recommended': [8, 6], 'minimal': [8, 6], 'maximal': [8, 6]} | exact | 0.09 | 8 6 | 0.06 | - |
