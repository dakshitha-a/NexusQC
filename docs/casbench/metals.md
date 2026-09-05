# Transition metals: measured, and why they are out of scope

Measured 2026-09-05 with `scripts/casbench/metal_probe.py` and one run of
`--set spaces` and `--set stability` with the metals temporarily in the
benchmark. The systems live in the probe script rather than in
`reference_data.py`, so the evidence can be reproduced without them being
scored.

The backlog carried "no transition metal has been through the CAS engine" as an
untested axis. They have now been through it. The conclusion is that the engine
should not be used for them, and this file is the reason.

## What was tried

Three systems, chosen for what each tests rather than for coverage. Cr$_2$ at
1.68 Å, two metal centres and no ligands, whose conventional space is the
twelve electrons in twelve orbitals of the formal sextuple bond. TiO, a metal
against one strongly bound ligand. Octahedral [Fe(H$_2$O)$_6$]$^{2+}$ high
spin, a d$^6$ ion whose classical ligand-field space is the d shell alone,
(6e,5o).

Nothing failed. The perception emits a `metal_d` target for all twenty-nine
transition metals, the projection admits it as one column per component, and
all three produce a space at ordinary cost: 0.2 s for the diatomics and 5.0 s
for the nineteen-atom ion.

| system | perceived targets | recommended | conventional |
|---|---|---|---|
| Cr$_2$ | two d shells, nothing else | (10e,10o) | (12e,12o) |
| TiO | d shell, 2 $\pi$, 3 lone pairs | (8e,9o) | no single convention |
| [Fe(H$_2$O)$_6$]$^{2+}$ | d shell, 6 $\pi$ | (14e,11o) | (6e,5o) |

## Why that is not good enough

**The basis independence does not hold.** This is the decisive result, because
basis independence is the property the whole method is built to have: targets
live in a fixed minimal basis so that a space means the same thing in STO-3G and
in aug-cc-pVQZ. Of the five bases `--set stability` sweeps, two are not defined
for Cr or Fe at all. Across the three that are:

| molecule | STO-3G | def2-SVP | def2-TZVP |
|---|---|---|---|
| benzene | (6e,6o) | (6e,6o) | (6e,6o) |
| uracil | (18e,12o) | (18e,12o) | (18e,12o) |
| Cr$_2$ | (8e,10o) | (10e,10o) | (10e,10o) |
| **[Fe(H$_2$O)$_6$]$^{2+}$** | **(18e,12o)** | **(18e,11o)** | **(16e,11o)** |

The iron complex returns a different space in every basis that can represent it.
All thirty organic molecules return the same space in all five. Whatever the
metal answers are, they are not the basis-independent quantity this method
claims to compute.

**The target set has no notion of metal bonding.** `perceive` emits the d shell
and then moves to the next atom, so a metal never emits a $\sigma$ axis or a
lone pair. On Cr$_2$, where both atoms are metals, the entire target set is two
d shells: the 4s orbitals that the conventional (12e,12o) contains have nothing
to select them, and the engine returns the 3d manifold alone. That is not a
tuning error, it is an absence.

**Three of the five pipeline stages are blind to d character.** The narrowing
sorts a pool into $\pi$ and lone-pair, and a d orbital is neither, so it is
dropped by any narrowing. The refinement's character audit, its re-seed and its
root labelling are all built from $\pi$ and lone-pair targets. So even where a
recommendation looks reasonable, nothing downstream of it can check itself.

**And the conventional spaces are not reproduced.** 0 of 2, on the two systems
where a convention exists to compare against.

## What is kept

The covalent radii. Twenty of the twenty-nine transition metals fell back to a
default 1.20 Å, including every 4d metal outside the platinum group and all of
the 5d row, and a radius decides the neighbour list that every target around the
metal is built from. That fix is correct whether or not metals are in scope, and
it costs nothing.

The `metal_d` target and the projector's axis-free case also stay. Removing them
would make a metal molecule fail confusingly rather than return something, and
returning something is the right behaviour as long as it is labelled. A
recommendation on a molecule containing a transition metal now carries a note
saying the engine is validated for organic molecules only, that a metal
contributes its d shell and nothing else, and that the space is basis dependent
in a way the organic benchmark is not.

Reported rather than refused, on the same principle that governs cost: the user
may know exactly what they are doing. Reported rather than left silent, because
a confidently wrong space is the worst of the three available outcomes.
