# Rydberg states: what was tried, and why the engine declines

Measured 2026-09-05 with `scripts/casbench/rydberg_probe.py` and
`scripts/casbench/rydberg_serve.py`, aug-cc-pVDZ unless stated.

The question was whether the engine should build an active space that describes
a requested Rydberg state, rather than reporting that it will not. It was worth
asking rather than assuming: `excited.augment` already carries the machinery to
add the orbital, and it refuses by a default whose justification was an argument
rather than a measurement.

## The basis has to be able to see the state at all

`rydberg_representable` measures the mean field rather than the basis set's
name. Asked of both candidate analysis bases:

| molecule | aug-cc-pVDZ | def2-SVPD |
|---|---|---|
| methylamine | S1 `n->Rydberg` 5.55 eV | gate closed, `n->mixed` |
| ammonia | S1 `n->Rydberg` 6.20 eV | gate closed, `n->mixed` |
| pyrrole | S1, S2 `pi->Rydberg` | gate open, both `pi->mixed` |
| furan | S1 `pi->Rydberg` | gate open, `pi->mixed` |
| ethylene | S1, S2 `pi->Rydberg` | S2 becomes `mixed->pi*` |
| formaldehyde | S2 `n->Rydberg` 6.85 eV | S2 `n->Rydberg` 7.49 eV |
| water | S1, S2 `pi->Rydberg` | S1, S2 `pi->Rydberg` |

def2-SVPD, which the engine used to move to whenever states were requested,
fails on four of seven, and in two different ways: the gate closes outright on
the amines, and pyrrole and furan pass the gate and then label a plainly Rydberg
particle "mixed". Since a character containing "mixed" was dropped from the
predicted list, those states were neither served, refused, nor mentioned.

The analysis basis is now aug-cc-pVDZ. Being right costs between nothing and a
factor of two on the linear-response pass: 0.99x on formaldehyde, 1.38x on
methylamine, 1.44x on pyrrole, 1.97x on uracil and 1.38x on p-benzoquinone.

## What happens if the state is served anyway

`excited.augment` gained an `allow_rydberg` switch so both branches could be run
on the same molecules and compared on whether the state comes out right, rather
than on whether the space comes out the right size.

| molecule | refused | served |
|---|---|---|
| formaldehyde | CAS(6e,4o), `n->pi*` 3.87 eV and `n->pi*` 9.23 eV | CAS(6e,5o), `n->pi*` 3.84 eV and the added state at 5.93 eV |
| ammonia | CAS(8e,7o), `n->Rydberg` 5.35 and 6.81 eV | CAS(8e,9o), `n->Rydberg` 4.70 and 5.24 eV |

Both converge, and serving is affordable. It is still the wrong answer, for
three measured reasons.

**The orbital does not survive the optimisation it is handed to.** The orbital
`augment` adds to formaldehyde carries a diffuse fraction of **0.648**, well
above the 0.5 that marks an orbital as diffuse at all. After the state-averaged
CASSCF has optimised it, the most diffuse orbital in the active space measures
**0.471**, below that mark. The space stops describing a Rydberg state during
the very step meant to improve it, and what remains is a contracted orbital that
is neither valence nor Rydberg.

**The energies move the wrong way.** Formaldehyde's Rydberg state has a
reference value of 7.30 eV and the linear-response pass puts it at 6.85. Served,
the CASSCF returns 5.93 eV, 1.4 eV low, which is what a collapse onto a more
compact orbital looks like. Ammonia's two roots move from 5.35 and 6.81 eV to
4.70 and 5.24 against a linear-response S1 of 6.20 eV: further away, not closer.

**It is not reproducible.** Two runs of the identical ammonia protocol returned
4.70 and 5.24 eV once and 5.04 and 6.07 eV the other time.

## The decision

The engine declines to build a valence space around a Rydberg state, and says
so. That was the existing default, and it is now a measured position rather than
an argument: the reasoning in `augment`'s docstring, that a diffuse orbital does
not mix appreciably with a valence set and degrades the calculation without
improving it, is what the numbers above show happening.

Three things changed so that the refusal is honest rather than silent.

The analysis basis can now see the state, so the refusal is made knowingly.
A state whose character cannot be assigned is reported instead of being dropped
without a word, and the note says when a missing diffuse basis is the likely
cause. And the refinement's list of states it deliberately did not look for now
reaches the user: the runner used to strip Rydberg states before `refine()` saw
them, so `states_not_looked_for` was always empty and every refinement reported
that all predicted states were present, whether or not the state the user cared
about had been dropped on the way in.

`allow_rydberg` stays in the code, defaulted off, because it is the switch these
measurements were made with and the next person to ask this question should not
have to rebuild it.

## A labelling defect found on the way

Root characters used to test diffuseness by comparing an orbital's extent
against the largest extent among the core and active orbitals. That works for a
linear-response particle, which is a virtual outside the reference. It cannot
work once the diffuse orbital is inside the active space, because the
denominator then contains the orbital being tested: the ratio collapses toward
one and no root can be called Rydberg.

Ammonia showed it plainly. Its roots were reported `n->mixed` in both branches
until the measure was changed, and are correctly `n->Rydberg` in both
afterwards. Diffuseness is now measured absolutely, as the fraction of an
orbital's density lying outside 1.5 van der Waals radii, which does not depend
on what else is in the space. The two implementations of root labelling, one in
`refine.py` and a near-copy in `verify.py`, were also a way for one audit to get
a fix the other did not; `verify.py` now delegates.
