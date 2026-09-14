# Does the recommended space depend on how the molecule is oriented?

Supporting material for §3.6 and §4.4 of
[`../CAS_ENGINE_METHOD.md`](../CAS_ENGINE_METHOD.md). The method document tells
the story; this carries the per-molecule numbers, the derivation of the
mechanism, and the checks that the repair moved nothing else.

Measured 2026-09-06 at commit `09e13f5`.

## What "orientation independence" means here, and how it is measured

An active space is a claim about a molecule. The same molecule written into a
file with its atoms rotated is the same molecule, so the recommendation must not
change. This is the same property as basis independence in a different
coordinate, and it is the property the geometric perception of §2.2 exists to
provide: stock AVAS reads axis-aligned atomic-orbital labels such as `C 2px` and
is orientation dependent by construction, which is the defect the whole approach
was chosen to avoid.

The measurement is the rotation half of `run_bench.py --set stability`, whose
per-molecule rows are committed as [`stability.md`](stability.md). It can be run
on its own, which takes a few minutes rather than the full set's hour:

```bash
PYTHONPATH=$PWD python3 -u scripts/casbench/rotation_invariance.py
```

Precisely what it does, for each of the 30 molecules that carry a literature
reference space:

1. Draw five rotation matrices from `numpy.random.default_rng(20260902)`, the
   same seed `--set stability` uses, so every molecule sees the same five
   orientations and a re-run sees them again. Each is the QR factorisation of a
   Gaussian matrix, sign-corrected to have determinant $+1$, which samples
   SO(3) uniformly.
2. Multiply the molecule's coordinates by each, and ask for a ground-state
   recommendation in def2-SVP at each of the five.
3. Collect the five recommended spaces into a set. Two runs agree when the
   electron count and the orbital count agree, written $(ne,no)$. Orbital
   indices are deliberately not compared: the claim is about the space, and a
   rotated calculation may number its orbitals differently while describing the
   same one.
4. Report the molecule as changing when that set has more than one member.

The denominator is 30 rather than the 36 geometries in `reference_data.py`
because the six without a published reference space are carried for cost and
convergence measurements and are not scored here. They are, however, included in
the fallback enumeration below, which is a property of perception alone and
needs no reference.

A second and stricter check is applied when validating a repair rather than
claiming a property: each molecule's five rotated answers are compared against
the space its **unrotated** geometry returns, which is the value committed in
[`spaces.md`](spaces.md). Self-consistency across orientations is not enough,
because a change that made every orientation agree on a new wrong answer would
pass it.

## The result

**Before the repair, 6 of 30 molecules returned two distinct spaces across the
five orientations. After it, 0 of 30, and all 30 agree with the unrotated
answer already committed in `spaces.md`.**

The six, with the two spaces each returned and the literature reference for
comparison:

| molecule | reference | before, across 5 orientations | after |
|---|---|---|---|
| formaldehyde | $(6e,4o)$ | $(6e,4o)$ on 3, $(8e,5o)$ on 2 | $(6e,4o)$ on all 5 |
| acetone | $(6e,4o)$ | two spaces | $(6e,4o)$ on all 5 |
| acrolein | $(8e,7o)$ | two spaces | $(8e,6o)$ on all 5 |
| formamide | $(8e,7o)$ | two spaces | $(8e,5o)$ on all 5 |
| p-benzoquinone | $(12e,10o)$ | two spaces | $(16e,12o)$ on all 5 |
| uracil | $(14e,10o)$ | two spaces | $(18e,12o)$ on all 5 |

Every one of the six carries a carbonyl, which is what located the mechanism.

Formaldehyde is the molecule the diagnosis was done on, because it is the one of
the six whose reference space is both unambiguous and reproduced exactly. Its
alternation is therefore not merely instability: $(6e,4o)$ is the right answer
and $(8e,5o)$ is a wrong one, so two of five orientations were returning a space
that is wrong by an orbital and an electron pair. The "after" column for
acrolein, formamide, p-benzoquinone and uracil differs from the reference for
reasons that predate this and are unrelated to orientation; §3.1 and §3.2 of the
method document account for each.

## The mechanism

Run the diagnosis directly, which prints the perceived directions rotated back
into the molecular frame alongside the space:

```bash
PYTHONPATH=$PWD python3 -u scripts/casbench/rotation_invariance.py \
    --molecule formaldehyde --targets
```

Before the repair, with formaldehyde's C=O axis along $z$ in the molecular
frame:

```
rot 0: space=(6e,4o)  axes: [1,0,0]  [0,-1,0]  [0,0,1]
rot 1: space=(8e,5o)  axes: [-0.7181,-0.6960,0]  [-0.6960,0.7181,0]  [0,0,1]
rot 2: space=(6e,4o)  axes: [-0.9442,-0.3295,0]  [-0.3295,0.9442,0]  [0,0,1]
rot 3: space=(6e,4o)  axes: [0.9925,-0.1225,0]  [-0.1225,-0.9925,0]  [0,0,1]
rot 4: space=(8e,5o)  axes: [0.7202,-0.6938,0]  [-0.6938,-0.7202,0]  [0,0,1]
```

The third direction, the axial lone pair pointing away from the bond, is
$[0,0,1]$ in every row: it is built as $-\hat v$ from the bond vector itself and
so rotates with the molecule. The first two are a different basis of the same
perpendicular plane in every row. They come from `perpendicular_pair`, which
before the repair projected a **fixed vector in the laboratory frame** onto the
plane perpendicular to the bond. Rotating the molecule moves the plane relative
to that fixed vector, so the pair is arbitrary and orientation dependent.

Two separate things go wrong, and only the second moves the spaces.

**The span argument, which fails as soon as the targets are hybridised.** The
docstring's original defence was that only the *span* of the pair is consumed,
since a projection onto a subspace does not care which basis of it was handed
over. That is true for a pure $p$ target. It is false for the oriented $sp$
hybrid of §2.3, $|t\rangle = c_s|ns\rangle + \sqrt{1-c_s^2}\,(\hat d \cdot
|np\rangle)$ with $c_s = 0.20$. For two perpendicular directions $\hat a$ and
$\hat b$, the span of $\{|t_a\rangle, |t_b\rangle\}$ contains their difference,
$\sqrt{1-c_s^2}\,((\hat a - \hat b)\cdot|np\rangle)$, which is a pure $p$
function along one specific in-plane direction, and their sum, which carries
$2c_s|ns\rangle$. Rotate the pair within the plane by $\theta$ and the
difference points somewhere else, while the sum's ratio of $s$ to $p$ weight
changes with $\theta$. The new pair's difference is not in the old span, because
the only pure-$p$ member of the old span is the old difference. So the span is
not invariant once $c_s \neq 0$. The lone-pair amplitude that §3.5 shows is
necessary for reachability is the same thing that removes the span guarantee.

**The duplicate, which is what actually changed the answers.** An $sp^2$
heteroatom's out-of-plane lone pair *is* its $\pi$ orbital, so `perceive`
discards a lone-pair direction whose absolute cosine with the atom's $\pi$
normal exceeds 0.9, rather than putting the same direction into the pool twice.
An arbitrary basis of a plane is generally parallel to nothing, so that test
fired only when a random orientation happened to align one member with the
normal. Read the rows above: in rotation 0 the second direction is $[0,-1,0]$
and formaldehyde's inherited $\pi$ normal is along $y$, so it is discarded and
the pool is right. In rotations 1 and 4 neither member is near the normal,
nothing is discarded, and the $\pi$ direction enters the pool a second time as a
lone pair. The space gains one orbital and two electrons, which is exactly
$(6e,4o) \rightarrow (8e,5o)$.

## Why the unrotated benchmark never showed this

This is the part worth keeping, because it is how the defect survived a full
benchmark campaign with every committed number correct.

The benchmark geometries are written with their molecular planes lying in
coordinate planes. Checking the inherited plane normal for every carbonyl oxygen
in the set returns a unit vector along a coordinate axis to five decimals in all
eight cases: formaldehyde and acetone along $x$, acrolein, formamide and both of
uracil's along $z$, both of p-benzoquinone's along $x$.

When the molecular plane is a coordinate plane, the old lab-frame seed,
projected perpendicular to the C=O axis, lands *exactly in that plane*. The
perpendicular-to-the-axis direction within a plane is unique up to sign, so the
old construction returned the same in-plane direction the normal-seeded one now
returns, and the out-of-plane member was then exactly parallel to the $\pi$
normal and correctly discarded. Reproducing both constructions side by side on
the unrotated geometries and comparing the directions that survive the discard,
up to sign, gives `SAME` for all eight carbonyl oxygens, bit-identical to six
decimal places.

So on the unrotated benchmark the two constructions are indistinguishable, and
every committed measurement taken on those geometries is unaffected by the
repair. The defect is invisible until a random orientation destroys the
coincidence. A benchmark whose inputs are all tidily aligned cannot detect an
orientation dependence, which is the argument for measuring rotations
explicitly rather than trusting that a geometry-derived construction is
covariant because it was meant to be.

## The repair

A terminal atom has no plane of its own, but its neighbour usually does: a
carbonyl oxygen sits on an $sp^2$ carbon whose plane is the molecule's.
`perceive` already inherits that plane for the atom's $\pi$ target, and for
exactly this reason. The same normal now also seeds `perpendicular_pair`, so the
pair comes out as one direction lying in the plane and one exactly perpendicular
to it. Both are built from molecular vectors, so the *lines* rotate with the
molecule, and the perpendicular one is now parallel to the $\pi$ normal by
construction, so the discard fires on every orientation rather than by luck.
Their signs are a separate matter and are dealt with in the next section.

After the repair, the same command gives:

```
rot 0: space=(6e,4o)  pi [1,-0,-0]   lone pair 1 [-0,-1,-0]   lone pair 3 [0,0,1]
rot 1: space=(6e,4o)  pi [1,-0,-0]   lone pair 1 [0,-1,-0]    lone pair 3 [-0,0,1]
rot 2: space=(6e,4o)  pi [1,-0,0]    lone pair 1 [-0,-1,0]    lone pair 3 [0,0,1]
rot 3: space=(6e,4o)  pi [-1,-0,0]   lone pair 1 [0,1,0]      lone pair 3 [0,0,1]
rot 4: space=(6e,4o)  pi [1,-0,0]    lone pair 1 [-0,-1,0]    lone pair 3 [0,0,1]
```

Three directions rather than four, the same three in every orientation up to
sign, and the space is the reference $(6e,4o)$ throughout. "Lone pair 2", the
out-of-plane one, is absent from every row because it is now discarded every
time.

## The sign, which the repair above does not fix

This section exists because the repair above looked complete and was not. The
count went to 0 of 30, the class-by-class figures held, and the regression test
passed. What did not hold was a single number somewhere downstream, and chasing
it rather than rounding it away is the only reason the rest of this section
exists.

### The number that did not reproduce

The lone-pair amplitude study, [`hole-capture.md`](hole-capture.md), records
formamide's $n \rightarrow \pi^*$ hole capture as 0.806. Re-measured after the
repair it read 0.802. Two things had to be ruled out before the difference
could be attributed to anything.

It is not scatter. Four consecutive runs on the unrotated geometry all return
0.802, to three decimals, with no variation.

It is not something else that changed between the two commits. Replacing
`perpendicular_pair` with its pre-repair definition by monkeypatch, leaving
every other line in the tree alone, returns 0.806. So the repair itself moves
the number.

That was surprising, because comparing the two constructions' surviving
directions on the unrotated geometry reports them bit-identical to six decimal
places for all eight carbonyl oxygens. Identical directions and a different
answer is a contradiction, and the resolution is that the comparison had thrown
away the thing that differed: it canonicalised the sign before comparing.

### Why a sign is not a phase here

A $\pi$ target is a pure $p$ function, $\hat d \cdot |np\rangle$. Negating
$\hat d$ negates the whole function, which is the same orbital with the
opposite phase and spans the same space. Comparing $\pi$ directions up to sign
is correct.

A lone-pair target is the oriented hybrid
$|t\rangle = c_s|ns\rangle + \sqrt{1-c_s^2}\,(\hat d \cdot |np\rangle)$
with $c_s = 0.20$. Negating $\hat d$ gives
$c_s|ns\rangle - \sqrt{1-c_s^2}\,(\hat d \cdot |np\rangle)$, which is not
$-|t\rangle$: the $s$ lobe stays where it is while the $p$ lobe flips, so the
two are hybrids pointing in opposite directions, with the large lobe on
opposite sides of the atom. They overlap different orbitals. Comparing these up
to sign is comparing the wrong object.

### Where the arbitrary sign came from

The in-plane direction is built as $\hat a = \hat n_{\text{axis}} \times
\hat n_{\text{plane}}$, so it inherits the sign of the plane normal.
`local_pi_normal` returns a cross product of two bond vectors at a
two-neighbour centre and the smallest right-singular vector at a larger one.
Neither fixes a sign: the cross product's depends on the order the neighbours
happen to be listed in, and a singular vector is defined only up to sign by the
decomposition. Under rotation the normal comes back reversed on some
orientations, and the in-plane lone pair reverses with it.

Measured over the same five orientations, keeping the sign this time, every one
of the six carbonyl molecules had its in-plane lone pair reverse on at least one
of the five. The axial lone pair, built directly as $-\hat v$ from the bond
vector, and the two- and three-neighbour branches, built from bisectors and
sums of bond vectors, all held their sign on all five. So this is specific to
the one construction that goes through a plane normal.

### The convention, and why it is a convention

The in-plane direction is now oriented away from the centroid of the
substituents on the neighbouring atom. For a carbonyl oxygen those are the two
groups on the carbonyl carbon, and away from them is where a lone pair is. The
rule uses only interatomic vectors, so it rotates with the molecule and does not
depend on the order atoms appear in the input file.

It has to be a convention rather than a derivation, and the reason is chemical.
A real carbonyl oxygen carries two in-plane lone pairs arranged symmetrically
about the C=O axis. The model spans them with two targets, this one and the
axial one, and the sign chosen here tilts that two-dimensional span toward one
of the real pair or the other. Neither is *the* answer. The alternative is to
emit both, which doubles the targets on every heteroatom and is the variant the
amplitude study measured and rejected.

### What the convention is worth, measured

Running the hole capture at each sign in turn, with nothing else changed:

| carbonyl and state | outward projection | capture, outward | capture, flipped |
|---|---|---|---|
| formaldehyde, 3.97 eV | 0.0 | 0.660 | 0.660 |
| acetone, 4.45 eV | 0.0 | 0.681 | 0.681 |
| p-benzoquinone, 2.75 eV | 0.0 | 0.617 | 0.617 |
| p-benzoquinone, 2.84 eV | 0.0 | 0.708 | 0.708 |
| acrolein, 3.60 eV | 0.068 Å | **0.668** | 0.667 |
| acrolein, 7.12 eV | 0.068 Å | **0.572** | 0.570 |
| formamide, 5.45 eV | 0.105 Å | **0.806** | 0.802 |
| uracil, 5.03 eV | 0.0046 Å | **0.760** | 0.756 |
| uracil, 6.19 eV | 0.061 Å | **0.818** | 0.817 |

Two claims come out of this table and both were things that had to be checked
rather than assumed.

The four rows whose outward projection is exactly zero give the *same* capture
to three decimals either way. Those are the carbonyls whose neighbouring carbon
carries two identical substituents, symmetric about the C=O axis: formaldehyde's
two hydrogens, acetone's two methyls, and p-benzoquinone's two ring carbons.
There the two signs are related by the molecule's own mirror plane, so they must
give equal projection weights, and they do. The sign those molecules are left
free to flip under rotation is therefore genuinely free, and the test asserts no
sign for them.

The five rows where a sign is defined all capture more with the outward choice,
by between 0.001 and 0.004. That is a small margin, and it is one-sided in all
five, so the convention is the better of the two options rather than a toss-up.

### Choosing the tolerance from the data

`_SIGN_TOLERANCE` decides when the projection is small enough that no sign is
imposed. It is set from the measured distribution rather than guessed. Over the
twelve terminal heteroatoms in the benchmark that have any substituent behind
them:

| projection | atoms |
|---|---|
| exactly 0.0 | formaldehyde O1, acetone O1, p-benzoquinone O6 and O7 |
| 0.0046 Å | uracil O4 |
| 0.061 Å | uracil O7 |
| 0.068 Å | acrolein O3 |
| 0.105 Å | formamide O2 |
| 0.133, 0.139 Å | o-nitrophenol O8, O7 |
| 1.14 Å | ozone O1 and O2 |

The two populations are separated by everything between floating-point noise
and about $4 \times 10^{-3}$ Å, so the exact value in that range cannot matter.
`1e-6` is used. A first draft of the comment in the source claimed the smallest
non-zero projection was 0.31 Å on acrolein; that was a guess, and it was wrong
in both the value and the molecule, which is why the table above is measured
output rather than recollection.

### The test that would have caught it

`cas_20_rotation_invariance.py` originally compared all target directions up to
sign, which is why it passed while the sign was flipping. It now keeps the sign
for `lone_pair` targets and drops it for `pi` targets, and asserts sign
stability only on acrolein, formamide and uracil, the three where a sign is
defined.

The assertion was checked against the defect it is meant to catch rather than
assumed to work: with `_orient_outward` replaced by the identity, which is
exactly the pre-convention behaviour, the test fails on all three of those
molecules and passes with it in place.

## What stays arbitrary

The seed can only be replaced where the molecule supplies a direction. Where the
terminal atom's neighbour has no plane either, there is nothing to seed from and
the lab-frame vector is still used. Enumerate exactly which atoms those are:

```bash
PYTHONPATH=$PWD python3 scripts/casbench/rotation_invariance.py --fallback
```

It asks `local_pi_normal` for each terminal heteroatom and for its neighbour,
and reports the atoms where both return nothing. Over all 36 geometries it
returns three molecules, both atoms in each: N$_2$, stretched N$_2$ and O$_2$.

The condition is structural rather than a property of this particular benchmark.
A neighbour fails to supply a plane only when it is itself terminal, which makes
the molecule a diatomic, or when its own neighbours are collinear, which makes
it a linear centre. Both are axially symmetric about the bond, and an axially
symmetric centre has no perpendicular direction to prefer, so **no** choice of
pair there is covariant. This is a limit of the problem, not of the
implementation.

It is also where it matters least. The perpendicular plane at such a centre is
degenerate by symmetry, and all three molecules return one space across the five
rotations. The guarantee elsewhere is a property of the construction; here it is
a property of the measurement, and §4.4 states it that way.

One thing this rules out. Emitting those two directions as pure $p$ functions,
with $c_s = 0$, would restore span invariance by construction and is the obvious
suggestion. It is the wrong move here, and the target dump printed by
`--fallback` shows why: on a linear centre the degenerate $\pi$ pair and the
perpendicular lone-pair pair come from the same `perpendicular_pair` call and so
lie along *identical* axes, the $\pi$ targets at $c_s = 0$ and the lone pairs at
$c_s = 0.20$. The pure-$p$ function along those directions is therefore already
in the pool, and the $s$ content is the only thing the lone-pair targets
contribute. Setting $c_s = 0$ would make them exact duplicates, which is the
"second reference along the same direction" variant the amplitude study measured
and rejected at a cost of one molecule in the literature-space match.

## What was re-measured, and what moved

A change to perception is a change to everything downstream of it, so the
standing rule is that it is validated against every `cas_*` script plus the
`spaces`, `narrowed`, `stability`, `refine` and `nevpt2` sets rather than
against the blast radius it appears to have.

**Recommended spaces, `--set spaces`.** 25 of 30 molecules reproduce the
literature space exactly, with the per-class breakdown unchanged: core 8 of 13,
non-planar 3 of 3, diradical 5 of 5, conjugated 4 of 4, charged 5 of 5. These
are the same figures as the ledger produced before the repair, which follows
from the coincidence described above.

**Hole capture, `scripts/casbench/hole_capture.py`.** The lone-pair amplitude
study of §3.5 rests on projecting each state's hole natural transition orbital
onto the recommended space, and it was measured before the repair, on directions
the repair might have changed. All nine $n \rightarrow \pi^*$ states in the
benchmark were re-measured in def2-SVPD with three states requested:

| molecule | space | state, eV | recorded in `hole-capture.md` | now |
|---|---|---|---|---|
| formaldehyde | $(6e,4o)$ | 3.97 | 0.660 | 0.660 |
| acetone | $(6e,4o)$ | 4.45 | 0.681 | 0.681 |
| p-benzoquinone | $(16e,12o)$ | 2.75 | 0.617 | 0.617 |
| p-benzoquinone | $(16e,12o)$ | 2.84 | 0.708 | 0.708 |
| acrolein | $(8e,6o)$ | 3.60 | 0.667 | 0.668 |
| acrolein | $(8e,6o)$ | 7.12 | 0.570 | 0.572 |
| formamide | $(8e,5o)$ | 5.45 | 0.806 | 0.806 |
| uracil | $(14e,10o)$ | 5.03 | 0.759 | 0.760 |
| uracil | $(14e,10o)$ | 6.19 | 0.819 | 0.818 |

The table is ordered by the two populations of the previous section, not
alphabetically, because that is what explains it. The four states on a
symmetric carbonyl reproduce exactly, which they must: no sign was ever imposed
there and none was needed. The five on an asymmetric one move in the third
decimal, by at most 0.002.

The reason is that the earlier study was measured with each carbonyl's sign
chosen independently by the laboratory frame, so what it recorded is whichever
combination that particular input orientation happened to produce. Uracil, which
has two carbonyls and therefore four combinations, shows this directly.
Enumerating all four while changing nothing else:

| O4 | O7 | 5.03 eV | 6.19 eV |
|---|---|---|---|
| outward | outward | **0.760** | **0.818** |
| outward | flipped | 0.757 | 0.817 |
| flipped | outward | 0.759 | 0.819 |
| flipped | flipped | 0.756 | 0.817 |

The third row reproduces the committed 0.759 and 0.819 exactly. So the numbers
in `hole-capture.md` were never wrong: they were one draw from a set of four,
and nothing in the file said which draw, because the choice was made by the
orientation the geometry happened to be written in.

The convention fixes uracil to the first row, and that row is worth reading
carefully because it does not say quite what the pairwise table above says. The
convention beats its own exact negation, the last row, on both states. It is
**not** the maximum over all four combinations for both: the mixed third row
takes the 6.19 eV state by a thousandth, 0.819 against 0.818, while losing the
5.03 eV state by rather more, 0.759 against 0.760. So the honest claim is the
narrow one. The outward rule is better than reversing it, on every state where
a sign is defined, and it is a rule fixed by the molecule rather than a search
for the per-state maximum, which is not something a selection scheme could do
before it knows the answer anyway.

The range, 0.570 to 0.819, and the finding the study exists to record, that
every $n \rightarrow \pi^*$ state is reachable at $c_s = 0.20$ where none was
at $c_s = 1/\sqrt{3}$, are both unchanged. What has changed is that repeating
the measurement now gives the same answer.

**Regression test.** `tests/backend/cas_20_rotation_invariance.py` is the
standing check, and it uses seed 20260906 rather than the benchmark's so that it
is independent evidence rather than the same five orientations again. It asserts
in order: that the perceived directions on formaldehyde, acetone, formamide,
acrolein and uracil are identical when rotated back into the molecular frame
across three orientations; that each of the four benchmark carbonyls emits two
lone-pair targets on its carbonyl oxygen rather than three, with the largest
absolute cosine against the $\pi$ normal below 0.1; that N$_2$ still emits four
$\pi$ targets, a degenerate pair on each atom, since the fallback path must keep
working; and that formaldehyde and acetone each return one space across three
orientations and that it is the literature $(6e,4o)$. All 19 checks pass.

N$_2$ is asserted differently from the rest, on target count rather than on
per-vector equality, because it is the case that cannot be made covariant. A
test that demanded covariance there would be asserting something false.
