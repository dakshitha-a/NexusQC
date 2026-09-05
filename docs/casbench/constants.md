# Perception and pool constants, swept

Measured 2026-09-05 with `scripts/casbench/constant_sweep.py`, def2-SVP,
ground-state request, every molecule with a reference space. 32 molecules.

**These tables replace an earlier set that measured nothing.** The sweep sets a
module attribute and re-scores the benchmark, which works only for a constant
read inside a function body. Two of the four were written as default arguments,
which bind once when the function is defined, so setting the attribute
afterwards changed nothing and every value returned an identical score. Both
were duly recorded as flat, and the flatness was read as the answer not
depending on the constant. `projector.THRESHOLD` was inert twice over, because
`recommend()` also passed its own hard-coded 0.2 over the top of it.

`tests/backend/cas_18_constants_reach_the_engine.py` now asserts that setting
each constant moves an answer, which is the property this whole file depends on.

## The projection threshold is not flat, and 0.20 is the lowest value that is best

| value | exact match | literature space offered as some tier |
|---|---|---|
| 0.05 | 21/32 | 23/32 |
| 0.10 | 23/32 | 24/32 |
| 0.15 | 24/32 | 25/32 |
| **0.20 (shipped)** | **25/32** | **25/32** |
| 0.30 | 25/32 | 25/32 |
| 0.40 | 25/32 | 25/32 |

Monotone up to the shipped value and flat above it. The previous version of this
file recorded the row as flat from 0.05 to 0.40, "a factor of eight", and four of
those six values are now known to be worse. The value does not change; what
changes is what can be said about it. It sits at the bottom edge of a plateau,
which is the right place for a threshold to sit: high enough to have reached the
best answer, low enough not to have started discarding orbitals for margin.

## The planarity cut and the bond tolerance are flat, and now measurably so

| `PLANARITY_COS` | exact | | `BOND_TOLERANCE` | exact |
|---|---|---|---|---|
| 0.10 | 25/32 | | 1.15 | 25/32 |
| 0.20 | 25/32 | | 1.25 | 25/32 |
| **0.25 (shipped)** | **25/32** | | **1.30 (shipped)** | **25/32** |
| 0.35 | 25/32 | | 1.40 | 25/32 |
| 0.50 | 25/32 | | 1.50 | 25/32 |

The planarity cut was live all along and its flatness stands. The bond tolerance
was one of the two inert ones, so this is its first real measurement, and it
happens to agree with what the broken sweep reported. That is worth stating
plainly rather than quietly: an answer that turns out to be right for a reason
nobody had is not the same as an answer that was known.

Neither result licenses widening the range further. The bond tolerance decides
the whole connectivity perception, and the benchmark's stretched N2 sits at
1.60 A against a bonding cliff at 1.85, deliberately on the near side; a
molecule placed past the cliff emits no targets at all, which section 4.3 of the
method document records as a limitation.

## `MINIMAL_ENTROPY_GAP` stays at 0.15

| value | exact | literature space offered as some tier |
|---|---|---|
| 0.05 | 25/32 | 26/32 |
| 0.10 | 24/32 | 26/32 |
| **0.15 (shipped)** | **25/32** | **25/32** |
| 0.25 | 25/32 | 25/32 |
| 0.40 | 24/32 | 24/32 |

The backlog carried this as a change worth making, on a measurement over a
21-molecule set which found 0.05 and 0.10 offering the literature space for two
more molecules than 0.15 did. On the current set the gain is one molecule rather
than two, and at 0.10 it is paid for with an exact match: 24 against 25.

The profile is also non-monotone, 25, 24, 25, 25, 24, which is the signature the
drift tolerance was refused for. A constant whose score dips on one side of its
shipped value and again two steps further out is describing knife-edge molecules
rather than a better setting. 0.15 and 0.25 are equal, and 0.15 is the lower
edge of that pair.

So the constant does not move, and the reason is recorded here rather than left
as an open item. What would reopen it is a molecule where the minimal tier is
the one a user wants and 0.15 declines to offer it, since the minimal tier is
user-facing, is a valid refinement start tier and appears in the cost report.

## The count itself no longer carries plus or minus one molecule

Earlier versions of this file warned that every count here should be read as
plus or minus one, because twisted ethylene returned a different recommendation
between identical runs and could land on either side of a comparison.

That is fixed rather than caveated. Its RHF reference had two converged
solutions 31.5 mHa apart and the projector followed them across the admission
threshold; the reference is now stabilised before it is projected and the
molecule returns one answer. `docs/casbench/reference-stability.md` has the
measurement. The counts above are reproducible.

---

# The n/sigma threshold, and whether it should be element-aware

Measured 2026-09-04 with `scripts/casbench/lone_pair_scale.py`, def2-SVP, every
benchmark molecule. For each heteroatom, the highest lone-pair weight found on
any occupied orbital.

`refine.LONE_PAIR_OVER_SIGMA` is one number, 0.50, deciding whether an orbital
is reported `n`, `n/sigma` or `sigma`. The open question on record was whether
it should be element-aware, on the observation that a thiol's lone pair scored
0.78 where an amine's scored 0.99, which would make one threshold strict on one
element and lax on another for no chemical reason.

**It should not be element-aware, and the observation that prompted the question
was not about elements.**

| element | samples | lowest | highest | median |
|---|---|---|---|---|
| N | 9 | 0.234 | 0.977 | 0.582 |
| O | 8 | 0.287 | 0.953 | 0.573 |
| S | 3 | 0.636 | 0.913 | 0.728 |

Nitrogen and oxygen are on the same scale: their medians differ by 0.009 and
their ranges are nearly identical. Sulfur's median is *higher* than both, which
is the opposite direction from the suspicion. And the spread **within** nitrogen,
0.234 to 0.977, is wider than any difference between elements, so element
identity cannot be what drives it.

What drives it is delocalisation, and the pairs show it cleanly:

| pair | weight | what changed |
|---|---|---|
| H2S 0.913 against methanethiol 0.728 | -0.185 | one methyl |
| ammonia 0.977 against methylamine 0.728 | -0.249 | one methyl |

Same shift, two different elements, from substitution rather than from the atom.
The original 0.78-against-0.99 comparison was a methylated species against an
unmethylated one.

**The lowest scorers are the ones that should score low.** Every orbital that
comes back `n/sigma` is an aromatic heteroatom whose lone pair is conjugated
into the pi system: furan's oxygen at 0.287, uracil's amide nitrogen at 0.330,
pyrrole's nitrogen at 0.441. For those atoms a small in-plane lone-pair weight
is the physically correct answer, because the lone pair is not in the plane at
all. An element-aware threshold would raise them to `n` and be wrong about all
three.

So the conclusion is that the weight is reporting chemistry rather than an
element-dependent scale artefact, the ambiguous band is doing exactly the job
8.2 describes, and the honest fix is nothing. The reason to keep publishing the
continuous weights beside every label is unchanged and is stronger for having
been measured.
