# The two orbital classifiers, checked against each other

Measured 2026-09-04 with `scripts/casbench/classifier_agreement.py`, def2-SVP,
the recommended tier of every benchmark molecule.

The engine labels orbitals twice, by different routes, and which one a user sees
depends on which job they ran:

- **projection**, `cas.refine.orbital_characters`. Projects each orbital onto
  the oriented minao targets perception emits and reports pi, lone-pair and
  sigma weights alongside a label. A `cas_reco` refinement reports this.
- **reflection**, `jobs.molden.classify_orbital_character`. Takes the atom from
  a Mulliken population and, for a planar molecule, the shape from the orbital's
  symmetry under reflection in the molecular plane. The orbital viewer reports
  this.

Nothing had ever compared them. This does, normalising both to pi / n / sigma
first, because one marks virtuals with a star and the other does not and the
star is a statement about occupation rather than shape.

## Result

**They agree on 103 of 126 comparable orbitals, 82%.** Every one of the 23
disagreements falls into one of two classes, and neither is a defect.

| disagreement | count | molecules |
|---|---|---|
| projection `n`, reflection `sigma` | 20 | formaldehyde, acetone, acrolein, formamide, uracil, pyrrole, water, H2S, N2, O2, stretched N2 |
| projection `pi`, reflection `n` | 3 | water, H2S, furan |

### The reflection test cannot separate n from sigma, by construction

This is 20 of the 23. In a planar molecule the pi orbitals are the ones
antisymmetric under reflection in the molecular plane, a''. Everything else is
a': the sigma framework, and **also every in-plane lone pair**. So the
reflection test can say pi or not-pi exactly, and cannot tell a lone pair from a
sigma bond, because there is no symmetry difference between them to find. It
calls the ones it cannot place `sigma`.

The projection can, because it is not working from symmetry: perception emits a
direction for each lone pair, and an orbital either has amplitude along that
direction or does not. That is the whole reason the engine has its own
classifier rather than reusing the viewer's.

So on these orbitals the projection is right and the reflection label should be
read as "a', shape not further determined" rather than as a positive claim of
sigma.

### An out-of-plane lone pair IS the pi orbital

This is the other 3, water, hydrogen sulfide and furan, and here the two are
describing the same orbital rather than disagreeing about it. A heteroatom's
out-of-plane lone pair is exactly what the pi normal points along.
`geometry.perceive` knows this and deliberately declines to emit it twice: the
lone-pair loop skips any direction parallel to the pi normal, with the comment
that emitting both "would double-count one direction and inflate the pool with a
duplicate". So the projection labels the orbital pi, correctly, and the
reflection labels it n from its localisation on the heteroatom, also correctly.

Water is the clearest case: it has no pi system in the conjugation sense at all,
and the orbital in question is its out-of-plane oxygen lone pair.

## What follows

Neither classifier needs changing. What needed changing is that a reader of
either label had no way to know these limits, so:

- the projection stays the one the CAS engine reasons with, which it already was
- a `sigma` from the reflection classifier means "a', not pi" and does not
  exclude a lone pair, which the viewer's own docstring should not overstate
- the honest summary is that they agree wherever both can see the answer, and
  the 18% is where one of them is structurally blind rather than wrong

The one thing this does NOT establish is that either is right in absolute terms.
Both were compared against each other, not against a reference; the standing
external check on the reflection classifier remains
`scripts/validate_orbital_character.py`, whose expectations are symmetry
statements rather than judgement calls.
