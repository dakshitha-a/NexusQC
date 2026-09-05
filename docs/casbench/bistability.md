# More than one converged answer: how common is it?

Measured 2026-09-05 with `scripts/casbench/bistability_census.py`, cc-pVDZ, in
each molecule's recommended space, at the root count the refinement uses (its
protocol states plus `ROOT_MARGIN`), eight identical runs each. Host at
`omp=8, mkl=12`.

## The question

A state-averaged CASSCF can converge to more than one solution, and a converged
flag does not say which one was reached. Acrolein was on record doing it: two
answers 36.4 meV apart, disagreeing about the character of two roots, every run
reporting success. What was not known is whether acrolein is unusual, because
acrolein was the only molecule anyone had ever run at repeat. A defect one
molecule in thirty has is a caveat on that molecule; one that a quarter of them
have is a property of the method.

## The answer, on seven molecules

| molecule | space | solutions | spread | converged | characters differ |
|---|---|---|---|---|---|
| acetone | (6e,4o) | 1 | 0.001 meV | 8/8 | no |
| **acrolein** | (8e,6o) | **2** | **36.4 meV** | 8/8 | **yes** |
| benzene | (6e,6o) | 1 | 0.000 meV | 8/8 | no |
| **butadiene** | (4e,4o) | **2** | **872.8 meV** | 8/8 | **yes** |
| ethylene | (2e,2o) | 1 | 0.001 meV | 8/8 | no |
| formaldehyde | (6e,4o) | 1 | 0.001 meV | 8/8 | no |
| formamide | (8e,5o) | 1 | 0.000 meV | 8/8 | no |

**Two of seven, and the second one is much worse than the first.** Acrolein
reproduces its recorded behaviour exactly: six runs at $E_0 = -190.823527$ Ha
and two at $-190.824866$, the same pair of energies and the same 36.4 meV gap
reported before. Butadiene, which nothing had flagged, splits seven to one at
$-154.899243$ and $-154.867167$ Ha, **872.8 meV apart**. Both molecules converge
on all eight runs, and in both the root characters differ between the solutions,
so this is not a difference confined to a total energy that nobody quotes.

The run was stopped after formamide rather than completing all twelve
molecules, so the denominator is seven and not twelve. That does not weaken the
finding it was run to settle, which is whether acrolein is alone. It is not.

## The root count is part of the protocol, not a detail

A first attempt at this census used a flat four roots for every molecule and
reported all six molecules it reached as single-solution, including acrolein.
That is a real measurement of a protocol nobody uses. Acrolein's two solutions
appear at six roots, which is what its two reference states plus the
refinement's root margin come to, and the refinement is what a user runs.

The lesson generalises past this file: a state average is a different
calculation at a different number of averaged states, and a reproducibility
measurement taken at the wrong one can report stability that the shipped
protocol does not have.

## What the engine does about it

It cannot make an SA-CASSCF have one solution, and pretending otherwise would be
worse than saying so. What it can do is make the two distinguishable from
outside, which they were not: two runs of one job returned different numbers
with nothing in either result to say they were different answers rather than the
same answer measured twice.

Every refinement now reports the state-averaged ground-state energy its
excitation energies are differences against, and says in words that a converged
flag does not identify which solution was reached. Comparing two runs starts
with that number.

## What is not known

Whether the split between solutions is stable. Acrolein's was four in twenty in
one earlier run set and four in five in another an hour apart, which is what one
expects if the basin is selected by reduction order in threaded linear algebra
rather than by the problem; the six-to-two here is a third figure and consistent
with the same picture. Nothing here measures how the frequency moves, only that
more than one solution exists and that two molecules in seven have one.
