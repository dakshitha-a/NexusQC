# Can the recommended space hold the state it was sized for?

Measured 2026-09-04 with `scripts/casbench/hole_capture.py`, def2-SVPD, three
states requested, on the commit that added the script.

Every count in section 10.1 of the method document counts orbitals. This counts
something the orbital count cannot see: whether the state a user asked about is
reachable inside the space they were handed. The measurement is a projection.
Take the hole natural transition orbital of a predicted state, project it onto
the recommended space, and report the fraction captured. A state whose hole is
spanned can be described in that space. One whose hole lies largely outside it
is described badly at best, and once the space is large enough that the solver's
initial guess misses the configurations, not at all.

## The result in one line

**Every pi->pi\* state in the benchmark was spanned at 0.984 or better. Every
n->pi\* state was not, nine out of nine, between 0.363 and 0.651.** Nothing
about that was uracil-specific and nothing about it was marginal.

That measurement is what this document was written to record. The cause turned
out to be one constant and it has since been corrected, so the table below is
the **before**; "What changed, and what it cost" at the end carries the after.
The diagnosis is kept in place rather than rewritten away, because the reasoning
is what would catch this again.

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
nothing. O2 and trimethylenemethane failed outright with a `TypeError` when
this was first run, and that was NOT a gap in the script: `excited.analyse`
indexed pyscf's per-spin NTO tuple as an array, so asking for excited states on
any open-shell molecule took the whole path down. Fixed, covered by `cas_04`,
and both molecules measure now.

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
its lowest singlet at **15.675 eV** here, and at 15.854 eV in cc-pVDZ, so this
is not an artefact of the analysis basis. The state average therefore never
contains the state. And the orbital optimisation cannot repair it, because a rotation
between two doubly occupied orbitals has no gradient to follow, so the run can
never acquire the state that would drive the rotation toward the right lone
pairs. `ROOT_MARGIN`, which exists because uracil's n->pi\* "appears around root
3", was tuned against a state this space does not contain.

**Planar symmetry is what makes a mis-aimed target invisible, and it is an
amplifier rather than a separate barrier.** A Davidson reaches only what its
initial guess spans, and PySCF builds that guess from the lowest-diagonal
determinants. Once the n->pi\* configurations fall outside that window, exact
planar symmetry guarantees no iteration pulls them back, because the coupling
between the a' and a'' blocks is identically zero, and asking for more roots
then returns more A' states forever. Where the space is small enough that the
guess spans everything the state is found anyway: formaldehyde is planar C2v,
its n->pi\* is A2 against an A1 reference, and an unsymmetrised solve in its
16-determinant $(6e,4o)$ finds it at root 1 with a depletion of 0.96. Uracil's
$(14e,10o)$ is not that space. So a root list is a reliable test only when the
guess is large relative to the space, which is exactly when it is least needed.

## The cause, and a constant that turns out to be load-bearing

The lone pair is not missing from the molecule, it is missing from the columns.
Uracil's n->pi\* hole spreads over lone-pair columns the narrowing cut (13.7%
and 6.4%, both inside the recommended pool) and over columns the classifier
calls `sigma` (11.2% and 5.3%). Formaldehyde puts 36.2% of its hole on a single
column labelled `sigma`. That is not a classifier fault. A carbonyl lone pair
has genuine sigma character, which is exactly why section 8.2 reports weights
instead of a hard label.

Sweeping `geometry.LONE_PAIR_S_AMPLITUDE`, the s fraction of the lone-pair target,
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

**And it moves the state, not just the number.** `irrep_gate.py` on uracil in
def2-SVPD, same SCF and same recommendation at both amplitudes, solving the A''
block explicitly and then repeating with the ordinary unsymmetrised solver the
engine actually uses:

| lone-pair target | lowest A'' singlet | does an unsymmetrised 6-root solve find it? |
|---|---|---|
| sp2 hybrid, s amplitude 0.577 (shipped) | 15.675 eV | no, zero n depletion in five excited roots |
| pure p, s amplitude 0.000 | **8.272 eV** | **yes, state 2 at 8.272 eV, depletion 0.861** |

7.4 eV from one constant, against a lowest excited A' of 8.10 eV. The same run
in cc-pVDZ agrees, 15.854 eV against 8.150 eV.

The second column is the one that settles scope. With the target corrected the
state is not merely present in principle, it is found by the ordinary solver
with no irrep handling and no change to the initial guess, which says the target
is the whole defect rather than half of it. And once a state average contains
the state, the orbital optimisation finally has a gradient to improve the lone
pairs further.

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


---

## What changed, and what it cost

`geometry.LONE_PAIR_S_AMPLITUDE` (renamed from `SP2_S_AMPLITUDE`, since sp2 is
no longer what it describes) went from $1/\sqrt{3} = 0.577$ to **0.20** on
2026-09-04.

### Every n-type state improved, and nothing else moved

| molecule | state | before | after |
|---|---|---|---|
| uracil | n->pi\* 5.03 | 0.363 | **0.759** |
| uracil | n->pi\* 6.19 | 0.381 | **0.792** |
| acrolein | n->pi\* 7.12 | 0.445 | **0.570** |
| *p*-benzoquinone | n->pi\* 2.75 | 0.488 | **0.617** |
| formaldehyde | n->pi\* 3.97 | 0.520 | **0.660** |
| acrolein | n->pi\* 3.60 | 0.521 | **0.667** |
| acetone | n->pi\* 4.45 | 0.537 | **0.681** |
| *p*-benzoquinone | n->pi\* 2.84 | 0.559 | **0.708** |
| formamide | n->pi\* 5.45 | 0.651 | **0.833** |

Eleven of the fourteen n-type states sat below 0.55 before. None does now, the
lowest being acrolein's second at 0.570. Every
pi->pi\* state stays at 0.998 or better, and every sigma-> state stays at 0.000,
which is correct rather than a regression: those states are genuinely outside a
pi valence space and P3.3 is where that distinction belongs.

### The states come back, which is the test that matters

`irrep_gate.py`, def2-SVPD, lowest root carrying a real n hole in the
unsymmetrised solve the engine actually runs:

| molecule | before | after |
|---|---|---|
| formaldehyde | 11.28 eV (root 1) | **7.41 eV** (root 1) |
| acetone | 11.84 eV (root 1) | **8.13 eV** (root 1) |
| acrolein | 10.67 eV (root 3) | **6.98 eV** (root 1) |
| formamide | 11.94 eV (root 2) | **8.67 eV** (root 1) |
| uracil | **not found in 8 roots** | **9.03 eV** (root 2) |
| *p*-benzoquinone | not found in 8 roots | **still not found** |

Uracil is recovered outright. The four that already found their state find it 3
to 4 eV lower and at a lower root, which is movement toward the true values
rather than away: formaldehyde's n->pi\* is near 4.0 eV experimentally, so 7.41
is a considerable improvement on 11.28 even though a CASCI without dynamic
correlation is still high.

### The price, and why it is accepted rather than unavoidable

**Pyrrole's ground-state reference space is no longer offered as one of its
tiers.** That is the whole cost. Ground-state exact stays 15/21 and
states-requested exact stays 18/21, and no other molecule changes verdict
anywhere in the range.

The full sweep, both metrics, whole benchmark:

| amplitude | 0.00 | 0.05 | 0.10 | 0.15 | 0.20 | 0.25 | 0.30 | 0.35 | 0.50 | 0.577 | 0.75 |
|---|---|---|---|---|---|---|---|---|---|---|---|
| ground state exact | 12/21 | 15 | 15 | 15 | 15 | 15 | 15 | 15 | 15 | 15 | 15 |
| ground state +tier | 16/21 | 16 | 16 | 15 | 15 | 15 | 15 | 16 | 16 | 16 | 17 |
| states exact | 15/21 | 18 | 18 | 18 | 18 | 18 | 18 | 18 | 18 | 18 | 18 |
| uracil's n->pi\* found | | | yes | yes | yes | yes | yes | **no** | no | no | no |

**An earlier version of this document said the cost could not be avoided at any
amplitude. That was wrong, and it was wrong because the sweep stopped at 0.20.**
At 0.05 and 0.10 pyrrole's tier is kept AND uracil's state is recovered. The
claim came from sampling 0.20, 0.25 and 0.30, finding the tier lost at all
three, and inferring a hard boundary from three points inside a dip.

What the wider sweep actually shows is that the tier verdict flips twice: kept
at 0.05 and 0.10, lost from 0.15 to 0.30, kept again from 0.35. A verdict that
oscillates across a smooth parameter is a near-degeneracy in how pyrrole's tiers
come out, not a quality difference, and choosing the constant to land in one of
its lobes would be fitting to noise. So it is not used to choose.

The metrics that do not oscillate are the two exact counts, flat at 15/21 and
18/21 everywhere from 0.05 up, and state reachability, which holds to 0.30 and
is gone by 0.35. **0.20 is chosen as the middle of that range**: comfortably
above the collapse below 0.05, comfortably below the loss of reachability at
0.35, and the value at which the whole suite and the refinement benchmark were
run. Gating all six carbonyls at 0.10 finds exactly the same states as 0.20, so
moving closer to the collapse buys nothing.

Lower is not free. At a pure p target the diatomics break, ground state falling
to 12/21 and states to 15/21, and `cas_11` asserts that a lone-pair target
carries an s admixture at all, which pure p fails outright.

One space changed size and it is worth naming rather than leaving to be
noticed. Water's narrowed space for an excited-state request goes from
$(2e,1o)$ to $(4e,2o)$. Neither is its conventional full valence $(8e,6o)$ and
its verdict changes in no count, but it is a real difference in what a user
would be handed, and it follows directly from the lone-pair columns moving.

### What is still not fixed

***p*-benzoquinone, as measured by the gate, and the gate is what is wrong.**
Its capture improves to 0.617 and 0.708 and `irrep_gate.py` finds no n->pi\* in
eight roots at any amplitude, which was written up here as the one molecule the
correction does not fix. The downstream benchmark then found its n->pi\* states
at 2.62 and 2.65 eV, converged.

The difference is that the gate runs a **CASCI** and the benchmark runs a
state-averaged **CASSCF**. A CASCI is stuck with the orbitals it is handed,
which is exactly what makes it a clean test of whether a space as seeded can
describe a state. A CASSCF rotates them, and for *p*-benzoquinone that rotation
is what brings the state down. So the gate is a conservative test: a negative
from it means the seeded space cannot describe the state without relaxation, not
that the production path will fail. Uracil's negative at the shipped amplitude
was of the stronger kind, absent from the full CASSCF too, which is why that one
held up.

**The threshold in this script was wrong and is now graded rather than binary.**
It began as a single 0.80 cutoff labelled "spanned", which was a guess. It does
not survive its own calibration: uracil recovers its state at 0.759 while
*p*-benzoquinone does not at 0.708. Capture reliably says how much of a state a
space is missing and does not, on its own, decide reachability, so the verdict
belongs to `irrep_gate.py` and this script now reports a grade.
