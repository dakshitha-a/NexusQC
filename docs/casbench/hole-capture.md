# Can the recommended space hold the state it was sized for?

Measured 2026-09-04 with `scripts/casbench/hole_capture.py`, def2-SVPD, three
states requested, on the commit that added the script.

Every count in section 10.1 of the method document counts orbitals. This counts
something the orbital count cannot see: whether the state a user asked about is
reachable inside the space they were handed. The measurement is a projection.
Take the hole natural transition orbital of a predicted state, project it onto
the recommended space, and report the fraction captured. A state whose hole is
spanned can be described in that space. One whose hole is not spanned cannot be,
at any root count, and no amount of reseeding or augmenting recovers it.

## The result in one line

**Every pi->pi\* state in the benchmark is spanned at 0.984 or better. Every
n->pi\* state in the benchmark is unspanned, nine out of nine, between 0.363 and
0.651.** Nothing about that is uracil-specific and nothing about it is marginal.

| molecule | space | state | eV | hole in space |
|---|---|---|---|---|
| uracil | (14e,10o) | n->pi\* | 5.03 | **0.363** |
| uracil | (14e,10o) | n->pi\* | 6.19 | **0.381** |
| acrolein | (8e,6o) | n->pi\* | 7.12 | **0.445** |
| *p*-benzoquinone | (16e,12o) | n->pi\* | 2.75 | **0.488** |
| formaldehyde | (6e,4o) | n->pi\* | 3.97 | **0.520** |
| acrolein | (8e,6o) | n->pi\* | 3.60 | **0.521** |
| acetone | (6e,4o) | n->pi\* | 4.45 | **0.537** |
| *p*-benzoquinone | (16e,12o) | n->pi\* | 2.84 | **0.559** |
| formamide | (10e,6o) | n->pi\* | 5.45 | **0.651** |
| uracil, benzene, pyrrole, furan, pyridine, butadiene, ethylene | | pi->pi\* | | 0.998 to 0.999 |

A `sigma->` state reading 0.000 in a pi valence space is not in this list and is
not a defect. Those states are correctly absent from a space that was never
meant to describe them, which is the distinction P3.3 exists to draw.

Two controls make the number mean what it says. Every Kohn-Sham hole projects
onto the RHF occupied space at 0.998 or better, so the difference between the
two orbital sets is not what is being measured. And ethylene's sigma->pi\*
correctly reports 0.000 in a pi-only space, so the projection is not simply
generous.

Two rows are not trustworthy and the controls are what caught them: square
cyclobutadiene and twisted ethylene report a KS hole lying at 0.000 and 0.030
inside the RHF occupied space, because RHF is a qualitatively wrong reference
for a singlet diradical, which the plan anticipated. Their capture numbers say
nothing. O2 and trimethylenemethane fail outright with a `TypeError` on the
open-shell path, which is a gap in the script rather than in the engine.

## What follows from it, on uracil

Uracil is the case where the consequence is total rather than merely
quantitative. In its narrowed $(14e,10o)$:

- no n->pi\* root appears at three roots, at six, or at ten
- none appears in a singlet-constrained CASCI in the seeded space either, which
  removes orbital optimisation from the question entirely
- both orbitals labelled `n` sit at occupation 2.000 in every root, moving by
  less than 0.0005

The mechanism is complete and each step is measured. Configurations built on a
38% hole land near 16 eV instead of near 5: solving the A'' block explicitly puts
its lowest singlet at **15.854 eV**. The state average therefore never contains
the state. And the orbital optimisation cannot repair it, because a rotation
between two doubly occupied orbitals has no gradient to follow, so the run can
never acquire the state that would drive the rotation toward the right lone
pairs. `ROOT_MARGIN`, which exists because uracil's n->pi\* "appears around root
3", was tuned against a state this space does not contain.

**A planar molecule's root list cannot be used to test for an n->pi\* state.**
This is worth its own line because it invalidates the obvious check. Uracil is
Cs, so the Hamiltonian is exactly block diagonal in a' and a''; the reference is
A' and every n->pi\* is A''. Davidson started from a totally symmetric guess
acquires no A'' component at any root count, because the coupling is identically
zero. Asking for more roots returns more A' states forever. Only solving the
irrep explicitly answers the question.

## The cause, and a constant that turns out to be load-bearing

The lone pair is not missing from the molecule, it is missing from the columns.
Uracil's n->pi\* hole spreads over lone-pair columns the narrowing cut (13.7%
and 6.4%, both inside the recommended pool) and over columns the classifier
calls `sigma` (11.2% and 5.3%). Formaldehyde puts 36.2% of its hole on a single
column labelled `sigma`. That is not a classifier fault. A carbonyl lone pair
has genuine sigma character, which is exactly why section 8.2 reports weights
instead of a hard label.

Sweeping `geometry.SP2_S_AMPLITUDE`, the s fraction of the lone-pair target,
against capture rather than against the literature count:

| molecule | state | 0.000 | 0.350 | 0.577 (shipped) | 0.750 | 0.950 |
|---|---|---|---|---|---|---|
| uracil | n->pi\* 5.03 | **0.796** | 0.653 | 0.363 | 0.139 | 0.000 |
| uracil | n->pi\* 6.19 | **0.841** | 0.677 | 0.381 | 0.153 | 0.001 |
| acetone | n->pi\* 4.45 | **0.708** | 0.632 | 0.538 | 0.465 | 0.387 |
| acrolein | n->pi\* 3.60 | **0.694** | 0.618 | 0.521 | 0.445 | 0.366 |
| formaldehyde | n->pi\* 3.97 | **0.686** | 0.613 | 0.521 | 0.449 | 0.374 |

Monotonic, and steeply so on uracil. The shipped $1/\sqrt{3}$ is the worst
usable end of the range for this metric.

**And it moves the state, not just the number.** Solving uracil's A'' block
explicitly at both amplitudes, same molecule, same basis, same everything else:

| lone-pair target | lowest A'' singlet | lowest A' excited singlet |
|---|---|---|
| sp2 hybrid, s amplitude 0.577 (shipped) | 15.854 eV | 8.103 eV |
| pure p, s amplitude 0.000 | **8.150 eV** | 8.100 eV |

7.7 eV, from one constant. The n->pi\* manifold goes from far above everything
the calculation would ever look at to sitting alongside the lowest pi->pi\*,
which is where uracil's n->pi\* belongs at this level of theory. Once it is
there a state average reaches it, and once the average contains it the orbital
optimisation finally has a gradient to improve the lone pairs further.

**The chemistry says the same thing, which is why this is not curve fitting.**
The n orbital of a carbonyl is predominantly an oxygen 2p lying in the molecular
plane, perpendicular to the C=O axis. It is the p-like lone pair that does
n->pi\*, not the s-rich hybrid pointing away along the bond. The engine emits one
sp2 hybrid target per lone pair and so aims at the wrong one of the two.

**Which is also why the fix is not simply setting the constant to zero.** P4.0
swept the same constant against the literature match and found the pure-p end
*worse*, 9 of 17 against 11 of 17, and that measurement was not wrong, it was
measuring the other lone pair. A full valence space wants the s-rich hybrid; an
excited-state space wants the p. The two metrics pull in opposite directions
because they are asking about different orbitals, and a single amplitude cannot
serve both. The change that satisfies both is to emit two distinct lone-pair
targets per sp2 heteroatom, one p-like perpendicular to the bond axis and one
s-rich along it, instead of two copies of one hybrid.

That is a change to perception, so it touches every molecule and needs the whole
benchmark re-run behind it rather than a constant edit at the end of a session.
It is the first item of the next tracker, with the mechanism established, the
gate written, and the number it has to beat recorded here.
