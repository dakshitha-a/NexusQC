# casbench: the lone-pair s-amplitude

The evidence behind step P4.0 of `docs/TRACKER.md`. The first of the engine's
constants to be given a plateau measurement rather than a justification.

The constant is `geometry.SP2_S_AMPLITUDE`, the amount of valence s mixed into
the oriented lone-pair reference. Section 4.3 of the method document set it to
sp2, `1/sqrt(3) = 0.577`, by measuring three variants on uracil, whose lone
pairs sit on a first-row carbonyl oxygen. This asks what happens across the
range, on molecules uracil could not speak for.

## Detection: the best lone-pair weight found anywhere in the projected pool

| molecule | 0.000 | 0.350 | 0.577 | 0.700 | 0.850 |
|---|---|---|---|---|---|
| hydrogen sulfide | 0.686 | 0.543 | 0.782 | 0.896 | **0.990** |
| methanethiol | 0.487 | 0.455 | 0.702 | 0.832 | **0.960** |
| dimethyl sulfide | 0.604 | 0.401 | 0.618 | 0.762 | **0.923** |
| ammonia | 0.654 | 0.923 | **0.990** | 0.967 | 0.844 |
| methylamine | 0.613 | 0.864 | **0.927** | 0.905 | 0.790 |
| water | 0.695 | 0.589 | 0.819 | 0.922 | **0.995** |
| formaldehyde | 0.976 | 0.980 | 0.988 | 0.993 | **0.997** |

The optimum is element-dependent. The value in use is best for nitrogen and
for nothing else; sulfur and water both want about 0.85; formaldehyde is flat
across the whole range, which is why the molecule the constant was set on could
not have revealed any of this.

## Selection: the literature match over every molecule with a reference space

Detection is not the question. The pool grows with the number of targets
clearing the projector threshold, so an amplitude that finds more lone-pair
character can also drag in the sigma framework, which is the coupling section
4.3 measured when it rejected a bare valence s.

| | 0.000 | 0.350 | 0.577 | 0.700 | 0.850 |
|---|---|---|---|---|---|
| exact match | 9/17 | **11/17** | **11/17** | **11/17** | **11/17** |
| any tier | 12/17 | 11/17 | 12/17 | 12/17 | 13/17 |

Per molecule, every space is identical from 0.35 to 0.85. The only movement in
the whole table is at the pure-p end, where N2 falls from (10e,8o) to (8e,7o)
and O2 from (12e,8o) to (10e,7o), which is precisely the result that made the
valence s part of the sigma target in the first place.

## What follows

**Leave the constant alone.** It sits in the middle of a plateau half the width
of its own range, and the threefold differences in detected weight never reach
the selection because the projector cut sits far below where they move things.
This is what a constant that is not delicate looks like, and it is worth having
measured rather than assumed.

**The reported label is a different matter.** The 0.50 lone-pair-over-sigma
threshold is applied to a weight whose scale is element-dependent, so at the
amplitude in use a thiol's lone pair scores 0.78 where an amine's scores 0.99,
and a sulfur lone pair can come back `n/sigma` where the same chemistry on
nitrogen comes back `n`. The space is right either way, and section 8.2 already
publishes the continuous weights beside every label, which is the mitigation.
Whether the threshold itself should be element-aware is open and recorded in
the tracker rather than guessed at.
