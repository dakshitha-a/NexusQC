# Perception and pool constants, swept

Measured 2026-09-04 with `scripts/casbench/constant_sweep.py`, def2-SVP,
ground-state request, every benchmark molecule with a reference space.

The engine has roughly twenty-five tunable constants and before this month
exactly one had been swept. The point of these tables is not to find better
values. It is to know which constants the answer turns on at all, because a flat
row is a real result: it says the number can be moved without consequence, and
that is worth knowing before anyone spends a day tuning it.

Read them with the lesson from `hole-capture.md` firmly in mind. **A constant
that is flat here can still be the defect.** `LONE_PAIR_S_AMPLITUDE` was flat on
exactly this metric across its whole usable range and was simultaneously the
reason no n->pi\* state in the benchmark was reachable. Flat here means "does not
move the literature space count", nothing more.

## Three constants are flat, one is not

| constant | shipped | range tried | exact | inclusive |
|---|---|---|---|---|
| `projector.THRESHOLD` | 0.20 | 0.05 to 0.40 | 15/21 throughout | 15/21 throughout |
| `geometry.PLANARITY_COS` | 0.25 | 0.10 to 0.50 | 15/21 throughout | 15/21 throughout |
| `geometry.BOND_TOLERANCE` | 1.30 | 1.15 to 1.50 | 15/21 throughout | 15/21 throughout |
| `recommend.MINIMAL_ENTROPY_GAP` | 0.15 | 0.05 to 0.40 | 15/21 throughout | **17/21 at 0.05 and 0.10** |

The projector threshold being flat across a factor of eight is the most
surprising of these, since it decides which orbitals enter the pool at all and
was inherited from AVAS without ever being examined here. Bond tolerance being
flat from 1.15 to 1.50 says the connectivity perception everything else is built
on is not living near a cliff, which is reassuring for a molecule set this
small.

## `MINIMAL_ENTROPY_GAP` is worth a change, and is not made here

At 0.05 and 0.10 the inclusive count is **17 of 21** against 15 at the shipped
0.15, replicated across runs, with the exact count unmoved at 15. Two more
molecules have their literature space offered as one of the tiers.

That is very likely the lever that restores what the lone-pair target correction
of `hole-capture.md` cost, which was pyrrole's ground-state tier, without
touching the lone-pair target at all.

It is deliberately not applied yet. The constant decides which tier counts as
minimal, and the minimal tier is not only a label: it is offered to the user as
a smaller alternative, it is a valid `start_tier` for a refinement, and it
appears in the cost report. So it needs its own validation pass, including the
refinement benchmark, which the change would invalidate. Stacking a second
unvalidated constant change on top of the first is exactly the failure this
plan has been correcting elsewhere.

## The count itself carries plus or minus one molecule

Three identical runs of the same scoring gave 15, 15 and 14 of 21, which sent
this looking for a defect in the metric. There is one, and it is confined:

**Twisted ethylene, and only twisted ethylene, is not reproducible.** Across
four identical runs its recommendation came back $(2e,2o)$ three times, matching
its reference exactly, and $(4e,3o)$ once, matching only as a tier. The SCF
converged every time, so this is not a convergence failure.

It is the case the plan predicted. Twisted ethylene is a singlet diradical, RHF
is a qualitatively wrong reference for one, and the APC ranking is taken from
the RHF Fock and exchange matrices, so a near-degeneracy there propagates
straight into which orbitals rank highest. The other twenty molecules gave
identical answers every time.

Two things follow. Any count in section 10 should be read as carrying $\pm 1$
molecule, and a difference of one molecule between two configurations is not by
itself a result. And a difference of two, such as `MINIMAL_ENTROPY_GAP`'s, is
outside that and was separately replicated.

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
