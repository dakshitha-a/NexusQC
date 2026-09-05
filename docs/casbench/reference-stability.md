# The SCF reference, and what "converged" does not tell you

Measured 2026-09-05 with `scripts/casbench/recommend_repro.py` and
`scripts/casbench/scf_stability.py`, def2-SVP, on this host at `omp=8, mkl=12`.

## The finding

`docs/BACKLOG.md` recorded that twisted ethylene's recommendation was not
reproducible, returning CAS(2e,2o) three times in four and CAS(4e,3o) once, and
attributed it to the APC ranking inheriting a near-degeneracy from an RHF
reference that is qualitatively wrong for a singlet diradical.

The attribution is to the wrong stage. Walking the pipeline and comparing every
intermediate across sixty identical runs, the first quantity to differ is the
**projected pool**, which is decided before the ranking runs at all. The two
answers also differ in their electron count, which no reordering of a fixed pool
can produce.

| stage | across 60 identical runs |
|---|---|
| SCF energy | spread 3.148e-02 Ha (857 meV) |
| projector eigenvalues | spread 3.437e-02 |
| **projected space** | **(2e,2o) x51, (4e,3o) x9** |
| recommended tier | follows the pool exactly |

The cause is one level below the ranking. Plain RHF on this molecule converges
to two different solutions and reports success on both:

| solution | energy | frequency |
|---|---|---|
| lower | -77.801586 Ha | 17 of 20 |
| upper | -77.770110 Ha | 3 of 20 |

They are 31.5 mHa apart. One of the projector's occupied eigenvalues sits within
about 0.02 of the 0.2 admission threshold, measured at 0.177762 under one
solution and 0.212131 under the other, so which solution the SCF found decides
which side of the cut that eigenvalue lands on. Admitting one occupied orbital
adds two electrons and one orbital, which is exactly the difference between
(2e,2o) and (4e,3o).

Twisted ethylene is the only molecule in the benchmark whose recommendation
moves, but it is not the only one whose reference is wrong.

## Stability is a different question from convergence

`converged` means the iterations stopped moving. An unstable SCF solution is a
stationary point that is not a minimum, so it satisfies that test exactly. Asked
separately, four references in this benchmark are not stable:

| molecule | plain | after following the instability | change |
|---|---|---|---|
| twisted ethylene | -77.801586 x17, -77.770110 x3 | -77.801586 x20 | ambiguity removed |
| square cyclobutadiene | -153.466493 | -153.477884 | 11.4 mHa lower |
| stretched N2 | -108.482483 | -108.501553 | 19.1 mHa lower |
| O2 (ROHF) | -149.470245 | -149.470494 | 0.25 mHa lower |
| ozone, acrolein, ethylene, water, trimethylenemethane | unchanged | unchanged | none |

Three of those were never ambiguous. They converged to the same wrong stationary
point every time, which is the failure mode a repeat measurement cannot see: a
reproducible answer and a defensible-looking convergence flag, from a reference
that is not a minimum.

**No molecule's recommended space changes except twisted ethylene's**, which
changes to the CAS(2e,2o) its reference reports. That is the evidence that
stabilising is a repair and not a perturbation: it fixes the one molecule that
was wrong and leaves the other twenty-nine alone.

## Internal and external are not the same instability

An **internal** instability means a better solution exists of the same kind, and
following it is unambiguous. An **external** instability means the closed-shell
reference is unstable toward an open-shell one. Asked properly, with
`external=True`:

| molecule | internally stable | externally stable |
|---|---|---|
| twisted ethylene | yes | **no** |
| square cyclobutadiene | yes | **no** |
| ozone | yes | **no** |
| stretched N2 | yes | **no** |
| ethylene, water | yes | yes |
| O2 (ROHF) | yes | cannot be asked |

Every diradical in the set is externally unstable, which is the correct
description of one and is worth telling a user. It is reported rather than
followed: acting on it means a broken-symmetry reference, and
`projector.project` takes the alpha set alone when handed a UHF solution, so
following it would change what the projection means without saying so.

Two traps are worth recording because both produced a wrong answer here first.
`stability(return_status=True)` returns its external entries as `None` unless
`external=True` was asked for, and `not None` is true, so a test written as
`if not stable_e` counts an instability on every molecule from a quantity that
was never computed. And pyscf's `rohf_external` raises `NotImplementedError`, so
an open-shell reference cannot answer the external question at all.

## Cost

The stability analysis as a multiple of the plain SCF it follows, and the effect
on the whole recommendation:

| molecule | recommendation, plain | stabilised | stability alone |
|---|---|---|---|
| water | 0.05 s | 0.06 s | 0.29x the SCF |
| stretched N2 | 0.05 s | 0.11 s | 1.90x |
| twisted ethylene | 0.08 s | 0.15 s | 1.16x |
| O2 | 0.05 s | 0.18 s | 3.19x |
| square cyclobutadiene | 0.15 s | 1.16 s | 7.08x |
| benzene | 0.29 s | 2.18 s | 7.5x |
| anthracene | 3.34 s | 48.20 s | 13x |

The median barely moves and the maximum moves a great deal, because the analysis
is an iterative eigenproblem over the same integrals the SCF used and so scales
with the molecule rather than with the difficulty. Anthracene is the worst case
in this set at 48 s.

That is a cost worth paying rather than a reason to make the check conditional.
The alternative is a second code path that fires on a minority of molecules and
is therefore rarely exercised, which is the shape of every defect this engine
has had; and a recommendation is a background job preceding a refinement
measured in minutes, so 48 s at the extreme is not the constraint it would be in
an interactive path.
