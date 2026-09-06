# Tracker: rotation invariance of the recommended active space

The CAS closeout
([`trackers/2026-09-cas-engine-closeout.md`](trackers/2026-09-cas-engine-closeout.md))
ended by committing a `stability` ledger for the first time, and that ledger
reported the engine's sharpest remaining limitation: **six of thirty molecules
return more than one active space across five random rotations of the same
geometry.** Basis independence is the property the whole method is built to
have, and orientation independence is the same property in a different
coordinate. The method document states the failure at §3.6 and §4.4.

This plan closes it. It is a change to what the engine *perceives*, so it
carries the full validation rule the audit established: every `cas_*` test plus
`--set spaces`, `--set narrowed`, `--set refine` and `--set nevpt2`, not the
blast radius the change looks like it has.

The six: acetone, acrolein, formaldehyde, formamide, p-benzoquinone, uracil.
Every one of them carries a carbonyl.

## Phase 1: The mechanism, measured before anything is changed
- [done] P1.1: Confirm the failure is a perceived-direction problem and not a
  convergence one, by printing the perceived axes in the molecular frame
  alongside the space
  evidence: scripts/casbench/rotation_invariance.py --molecule formaldehyde --targets → before the fix, the C=O axial direction is covariant at [0,0,1] on all five rotations while the two perpendicular lone-pair directions are a different basis of the same plane each time, and the space alternates (6e,4o) on rotations 0/2/3 against (8e,5o) on 1/4
- [done] P1.2: Establish that the alternation is a wrong answer and not merely
  an inconsistent one
  evidence: scripts/casbench/reference_data.py → formaldehyde's reference space is (6e,4o), so two of the five rotations are simply wrong rather than a defensible second choice
- [done] P1.3: Identify the mechanism in the code rather than inferring it from
  the symptom
  evidence: app/chemistry/cas/geometry.py → `perceive` drops a lone-pair direction parallel to the atom's pi normal, because an sp2 heteroatom's out-of-plane lone pair IS its pi orbital. `perpendicular_pair` seeded from a fixed lab-frame vector returns an arbitrary basis of the perpendicular plane, and an arbitrary basis is generally parallel to nothing, so that test fired only by luck. On the rotations where it missed, the pi direction entered the pool a second time as a lone pair, which is the extra orbital and the extra electron pair
- merged: -

## Phase 2: A covariant pair, seeded from the molecule
- [done] P2.1: Give `perpendicular_pair` an optional molecular direction to
  seed from, so the returned pair is one direction in that plane and one
  perpendicular to it, and have `lone_pair_axes` pass the plane the atom
  belongs to
  evidence: scripts/casbench/rotation_invariance.py --molecule formaldehyde --targets → all five rotations now return (6e,4o), the reference space. The pi normal is covariant at +/-[1,0,0], the in-plane lone pair at +/-[0,1,0] and the axial one at [0,0,1], and the out-of-plane direction is dropped as duplicating pi on every rotation rather than on three of five
- [done] P2.2: The terminal atom's plane is its neighbour's. `perceive` already
  inherits it for the pi target and the comment there explains why; the same
  normal now feeds the lone pairs, so there is one definition of the plane per
  atom rather than two
  evidence: tests/backend/cas_20_rotation_invariance.py → the four carbonyls in the benchmark each emit exactly two lone-pair targets on the carbonyl oxygen, the in-plane one and the axial one, and the largest absolute cosine between either of them and the pi normal is 0.0000. Before the fix the out-of-plane direction survived on the rotations where the arbitrary basis happened to miss the parallel test
- [done] P2.3: Sweep all thirty molecules and show the count goes to zero
  evidence: scripts/casbench/rotation_invariance.py → 0 of 30 molecules change under five random rotations, against six before the fix. Every one of the thirty returns exactly the space the committed `spaces.md` records for the unrotated geometry, so the fix removed the spurious branch and moved no correct answer: acetone (6,4), acrolein (8,6), formaldehyde (6,4), formamide (8,5), p-benzoquinone (16,12) and uracil (18,12) are the six that used to alternate
- merged: -

## Phase 3: The seed that stays arbitrary
An axially symmetric centre -- N2, acetylene, a nitrile -- has no molecular
direction perpendicular to its axis, so no choice of pair there can be
covariant. None of those molecules failed rotation invariance, and the reason
is worth writing down rather than re-deriving: at an exactly degenerate centre
every basis of the perpendicular plane is equivalent, so the projected pool
does not depend on which one was handed over.

That is an argument about the pool, not about the targets, and the targets are
oriented sp hybrids sharing a common s amplitude. Two such hybrids do not span
the same space as the same construction on a rotated pair. So the question is
whether the fallback is safe because the degeneracy really is exact, or safe
only on the molecules that happen to be in the benchmark.

The answer is the first, and it is structural rather than a property of the
benchmark: the fallback is reached only where the neighbour supplies no plane,
which is exactly a diatomic or a linear centre, which is exactly where the
perpendicular plane is degenerate by symmetry.

- [done] P3.1: Establish which molecules reach the fallback, and whether it can
  move a space
  evidence: scripts/casbench/rotation_invariance.py --fallback → three of 36 geometries reach the arbitrary seed, N2, N2_stretched and O2, and they are reached because the fallback triggers only for a terminal heteroatom whose neighbour supplies no plane, which means the neighbour is itself terminal or its own neighbours are collinear. That is the diatomic and linear-centre class and nothing else. All three are stable over five rotations
- [done] P3.2: Decide between leaving the hybrid and emitting pure p on the
  fallback path
  evidence: scripts/casbench/rotation_invariance.py --fallback → the hybrid stays. Pure p would make the two perpendicular lone-pair targets exact duplicates of the pi targets, because on a linear centre both come from the same `perpendicular_pair` call and so lie along the same two directions: the dump shows the pi pair at s_amp=0.0 and the lone-pair pair at s_amp=0.2 along identical axes. The pure-p function is therefore already in the pool, and the s content is the only thing those targets add. Emitting a second reference along a direction already covered is the variant the amplitude study measured and rejected, at a cost of one molecule in the literature-space match
- merged: -

## Phase 4: Validation, at the width a perception change requires
- [ ] P4.1: Every `cas_*` test in `tests/backend/`
- [ ] P4.2: `--set spaces`, against the committed ledger row by row
- [ ] P4.3: `--set narrowed`, likewise
- [ ] P4.4: `--set stability`, which is the set that found this, with both
  halves rather than the rotation half this plan iterates against
- [ ] P4.5: `--set refine` and `--set nevpt2`. Five of the twelve molecules
  carrying reference excitation energies are carbonyls, so these are not
  skippable on the argument that the change is small
- [done] P4.6: A regression test asserting orientation independence, so this
  cannot silently return
  evidence: tests/backend/cas_20_rotation_invariance.py → 19 of 19 checks pass on a seed independent of the benchmark's. It asserts the three things in order: the perceived directions are covariant on all five carbonyls, a carbonyl oxygen emits two lone-pair targets rather than three with neither within 0.1 of the pi normal, and the recommended space is one space over three orientations and is the literature one. N2 is included as the case that cannot be made covariant and must not be broken
- merged: -

## Phase 5: The measurements taken under the defect
§3.5's lone-pair amplitude study measured hole capture on nine n->pi* states,
with the in-plane direction chosen by the arbitrary basis. If that direction is
now canonical the captures may move, and the shipped amplitude was chosen from
them.

- [ ] P5.1: Re-run `hole_capture.py` on the nine states and compare
- [ ] P5.2: If the numbers hold, say so: it is evidence the amplitude study was
  robust to the defect. If they move, §3.5 carries the new ones
- merged: -

## Phase 6: The document
- [ ] P6.1: §3.6 and §4.4, which currently state the failure as the method's
  sharpest open limitation, rewritten to what the final sweep measures
- [ ] P6.2: Every number that moved, re-derived from ledgers produced at the
  closing commit. No number reaches the document from a mid-flight run
- [ ] P6.3: `CHANGELOG.md`
- merged: -
