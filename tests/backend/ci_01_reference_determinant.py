#!/usr/bin/env python3
"""The reference determinant a dominant transition is measured from --
see docs/trackers/2026-08-ci-reference-determinant.md.

A transition is a difference between two occupation patterns, so it is
only as meaningful as the reference it is measured from. That reference
is deliberately NOT state 0's leading configuration: state-averaged
CASSCF roots can come out of energy order relative to which one is the
closed-shell-like reference, so it is taken from whichever row carries
the largest magnitude across the whole CI block.

The bug this file pins is in the word "row". BAGEL and PySCF print raw
Slater determinants, so an open-shell singlet arrives as two lines
sharing one occupation pattern, which aggregate_by_configuration
correctly sums into one configuration weight. A closed-shell determinant
has no partner to sum with. Ranking the AGGREGATED weights therefore
compares a sum of two terms against a single term, and prefers the
open-shell configuration every time the two are close -- which on a real
run made an excited root's own leading configuration the reference for
every state, including itself.

The first section is that real run: the CI vectors below are quoted
verbatim from job 51a14d838f5b, a uracil CAS(12,9)/cc-pVDZ state average
over three roots, kept here rather than read from the job store so this
regression survives the job being deleted.

Run:  PYTHONPATH=$PWD python3 tests/backend/ci_01_reference_determinant.py
"""
from __future__ import annotations

import sys

from app.chemistry.jobs.bagel_runner import _dominant_transitions_bagel
from app.chemistry.jobs.ci_transitions import (
    aggregate_by_configuration, leading_single_excitations, reference_configuration,
)

PASS = 0
FAIL = 0


def check(label: str, ok: bool, detail: str = "") -> None:
    global PASS, FAIL
    if ok:
        PASS += 1
        print(f"  [PASS] {label}")
    else:
        FAIL += 1
        print(f"  [FAIL] {label}" + (f"\n         {detail}" if detail else ""))


# n_closed = 23, so the nine active orbitals are 24 through 32 and
# position N of each string is orbital 23 + N.
URACIL_CI_VECTORS = """
     * ci vector, state   0, <S^2> = -0.0000
       222222...     0.8581409497
       22222ab..     0.2965951212
       22222ba..     0.2965951212
       222.222..    -0.0841530659
       22222b.a.     0.0767141954
       22222a.b.     0.0767141954
       222a2bba.     0.0755153013
       222b2aab.     0.0755153013
       22a222b..     0.0625227377
       22b222a..     0.0625227377
       22222..2.    -0.0582740543
       222a22b..     0.0535230375
       222b22a..     0.0535230375

     * ci vector, state   1, <S^2> = 0.0000
       2222a2b..    -0.6589508453
       2222b2a..    -0.6589508453
       2222a2.b.    -0.1262406967
       2222b2.a.    -0.1262406967
       2222bbaa.    -0.0947663974
       2222aabb.    -0.0947663974
       222ba2ab.    -0.0858750081
       222ab2ba.    -0.0858750081

     * ci vector, state   2, <S^2> = -0.0000
       22222ab..     0.5824758465
       22222ba..     0.5824758465
       222222...    -0.3701015406
       22222a.b.    -0.1726957296
       22222b.a.    -0.1726957296
       22222..2.     0.1081094980
       222.222..     0.1012231252
       22a22b2..    -0.0882201625
       22b22a2..    -0.0882201625
"""


def main() -> int:
    print("== the run that reported it ==")
    got = _dominant_transitions_bagel(URACIL_CI_VECTORS, n_states=3, n_closed=23)
    # S0 is dominated by the closed-shell 222222... -- it IS the
    # reference, so it has no single-excitation character to report, and
    # saying so is the point rather than a gap.
    check("the ground state reports no transition, because it is the reference",
          got[0] is None, f"got {got[0]!r}")
    # 2222a2b.. : position 5 loses an electron, position 7 gains one, and
    # 23 + 5 = 28, 23 + 7 = 30. The two spin partners sum to 2 x 0.659^2.
    check("S1 is 28->30, the transition its leading determinants describe",
          got[1] == "28->30 (0.87)", f"got {got[1]!r}")
    # 22222ab.. : position 6 to position 7, i.e. 29 -> 30, at 2 x 0.582^2.
    # Its runner-up is a clean 29->31 at 0.06, below format_dominant's
    # 0.1 threshold, so one transition is all that should show.
    check("S2 is 29->30, and its sub-threshold runner-up stays hidden",
          got[2] == "29->30 (0.68)", f"got {got[2]!r}")
    # Every wrong answer this produced before pointed INTO orbital 28,
    # which is doubly occupied in the real reference and can accept
    # nothing. That is the signature of the reference having moved.
    check("nothing is described as an excitation into a doubly-occupied orbital",
          not any("->28" in (t or "") for t in got), f"got {got}")

    print("\n== the mechanism, in isolation ==")
    # The closed-shell determinant is the larger of the two rows, and the
    # open-shell one is the larger of the two configurations. Those
    # disagree, which is the entire bug.
    closed = [2, 2, 2, 2, 2, 2, 0, 0, 0]
    open_shell = [2, 2, 2, 2, 1, 2, 1, 0, 0]
    rows = [(0.858, closed), (0.659, open_shell), (-0.659, open_shell)]
    check("the closed-shell determinant is the largest single row",
          reference_configuration(rows) == closed,
          f"got {reference_configuration(rows)}")
    configs = aggregate_by_configuration(rows)
    check("...while the open-shell configuration is the heaviest once summed",
          configs[0][1] == open_shell and configs[0][0] > 0.858 ** 2,
          f"top config {configs[0]}")
    check("so ranking configurations would pick the wrong one, and rows do not",
          configs[0][1] != reference_configuration(rows))

    # Sign is irrelevant: BAGEL prints signed coefficients and a
    # reference determinant is as often negative as positive.
    flipped = [(-0.858, closed), (0.659, open_shell), (-0.659, open_shell)]
    check("a negative coefficient is ranked by magnitude, not by value",
          reference_configuration(flipped) == closed,
          f"got {reference_configuration(flipped)}")

    check("no rows at all gives no reference, rather than raising",
          reference_configuration([]) is None)

    print("\n== ORCA's rows are its configurations, and are unaffected ==")
    # ORCA's CASSCF table is already spin-adapted: one row per
    # configuration, carrying the weight directly. Passing those rows
    # through is the same selection it always made.
    orca_rows = [(0.74, closed), (0.20, open_shell), (0.04, [2, 2, 2, 2, 2, 1, 0, 1, 0])]
    check("the heaviest printed configuration is still the reference",
          reference_configuration(orca_rows) == closed,
          f"got {reference_configuration(orca_rows)}")

    print("\n== a state whose top configuration is the reference ==")
    # The early return in leading_single_excitations is what makes the
    # ground state come back empty rather than reaching down its list for
    # a near-noise contributor and calling it dominant.
    ranked = aggregate_by_configuration([(0.858, closed), (0.297, open_shell), (-0.297, open_shell)])
    check("reports nothing, rather than a small contributor further down",
          leading_single_excitations(ranked, closed, 23) == [])
    # ...and one that is not the reference reports the pair it differs by.
    ranked = aggregate_by_configuration([(0.659, open_shell), (-0.659, open_shell)])
    got_pairs = leading_single_excitations(ranked, closed, 23)
    check("a state that differs by one orbital pair reports exactly that pair",
          [(s, t) for s, t, _ in got_pairs] == [(28, 30)], f"got {got_pairs}")

    print(f"\n{PASS}/{PASS + FAIL} checks passed")
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    code = main()
    print("[PASS] ALL CHECKS PASSED" if code == 0 else "[FAIL] see above")
    sys.exit(code)
