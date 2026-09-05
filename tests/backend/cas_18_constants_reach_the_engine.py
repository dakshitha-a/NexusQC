#!/usr/bin/env python3
"""A constant the benchmark sweeps has to be a constant the engine reads.

`scripts/casbench/constant_sweep.py` measures which constants the recommendation
turns on by setting a module attribute and re-scoring the benchmark. That only
works for a constant read inside a function body. A constant written as a
default argument is bound once, when the function is defined, and setting the
attribute afterwards changes nothing at all.

Two of the four constants in that sweep were of the second kind, and the two
reported flat in `docs/casbench/constants.md` were exactly those two. The sweep
had been measuring nothing and the flat rows were read as evidence that the
answer did not depend on the constant. `projector.THRESHOLD` was inert twice
over, since `recommend()` also passed its own hard-coded 0.2 over the top.

This is the same shape as the assertion the audit found in `cas_02`, which had
the engine's own output written down as its reference and so agreed with
whatever the engine did. A measurement that cannot fail is not a measurement,
and neither is a sweep that cannot move what it sweeps.

The test is deliberately about the plumbing rather than about any particular
value: it asserts that changing each constant changes an answer somewhere, which
is the property the sweep depends on.

    PYTHONPATH=$PWD python3 tests/backend/cas_18_constants_reach_the_engine.py
"""
from __future__ import annotations

import sys

import numpy as np

FAILURES = []


def check(label, ok, detail=""):
    # The detail explains a failure, so it is printed only on one. Printing it
    # beside a PASS reads as though the failure text were the result.
    print(f"  [{'PASS' if ok else 'FAIL'}] {label}"
          + (f" -- {detail}" if detail and not ok else ""))
    if not ok:
        FAILURES.append(label)


def space_at(mf, syms, co, spin_2s):
    from app.chemistry.cas.recommend import recommend
    rec = recommend(mf, syms, co, spin_2s=spin_2s)
    t = rec.tiers[rec.recommended]
    return (t.n_electrons, t.n_orbitals)


def main() -> int:
    from app.chemistry.cas import geometry, projector
    from scripts.casbench import reference_data as ref
    from scripts.casbench.run_bench import _mf

    print("cas_18: a swept constant reaches the engine")

    # Twisted ethylene has a projector eigenvalue about 0.02 below the shipped
    # 0.2 threshold, so it is the molecule where lowering the cut admits one
    # more occupied orbital and the answer moves. Any molecule with an
    # eigenvalue near the cut would do; this one is in the benchmark and its
    # sensitivity is measured.
    syms, co, chg, mult = ref.molecule("ethylene_twisted")
    co = np.asarray(co, float)
    _mol, mf = _mf(syms, co, "def2-svp", chg, mult)
    # Stabilised, or this molecule answers from whichever of its two SCF
    # solutions the run happened to land in and the printed table changes
    # between identical runs.
    from app.chemistry.cas.reference import stabilise
    stabilise(mf, check_external=False)

    shipped = projector.THRESHOLD
    try:
        seen = {}
        for value in (0.05, 0.15, shipped, 0.40):
            projector.THRESHOLD = value
            seen[value] = space_at(mf, syms, co, mult - 1)
    finally:
        projector.THRESHOLD = shipped

    print(f"    projector.THRESHOLD: "
          + ", ".join(f"{v}->{s}" for v, s in seen.items()))
    check("setting projector.THRESHOLD changes the recommended space",
          len(set(seen.values())) > 1,
          f"every value returned {next(iter(set(seen.values())))}, so the "
          f"sweep is measuring nothing")

    # The same property for the bond tolerance, on a molecule whose bonding is
    # near the cutoff. Stretched N2 sits at 1.60 A with the bonding cliff at
    # 1.85, so a tolerance low enough breaks the bond and changes perception.
    syms2, co2, chg2, mult2 = ref.molecule("N2_stretched")
    co2 = np.asarray(co2, float)
    shipped_tol = geometry.BOND_TOLERANCE
    try:
        bonds = {}
        for value in (0.80, shipped_tol, 1.50):
            geometry.BOND_TOLERANCE = value
            nb = geometry.perceive_bonds(syms2, co2)
            bonds[value] = tuple(len(n) for n in nb)
    finally:
        geometry.BOND_TOLERANCE = shipped_tol

    print(f"    geometry.BOND_TOLERANCE: "
          + ", ".join(f"{v}->{b}" for v, b in bonds.items()))
    check("setting geometry.BOND_TOLERANCE changes the perceived bonding",
          len(set(bonds.values())) > 1,
          "every tolerance perceived the same neighbours, so the sweep is "
          "measuring nothing")

    # The one that was always live, as a control. It needs a molecule with
    # enough orbitals for a cut to have somewhere to fall: twisted ethylene's
    # pool is two orbitals, so no gap setting can move its minimal tier and the
    # control would pass on a broken engine.
    from app.chemistry.cas import recommend as recommend_module
    syms3, co3, chg3, mult3 = ref.molecule("pyrrole")
    co3 = np.asarray(co3, float)
    _m3, mf3 = _mf(syms3, co3, "def2-svp", chg3, mult3)
    shipped_gap = recommend_module.MINIMAL_ENTROPY_GAP
    try:
        gaps = {}
        for value in (0.01, 0.95):
            recommend_module.MINIMAL_ENTROPY_GAP = value
            rec = recommend_module.recommend(mf3, syms3, co3,
                                             spin_2s=mult3 - 1)
            mn = rec.tiers["minimal"]
            gaps[value] = (mn.n_electrons, mn.n_orbitals)
    finally:
        recommend_module.MINIMAL_ENTROPY_GAP = shipped_gap

    print(f"    recommend.MINIMAL_ENTROPY_GAP on pyrrole: "
          + ", ".join(f"{v}->{g}" for v, g in gaps.items()))
    check("setting MINIMAL_ENTROPY_GAP changes the minimal tier",
          len(set(gaps.values())) > 1,
          f"every gap gave {next(iter(set(gaps.values())))}; this constant was "
          f"the one already reaching the engine, so a failure here means the "
          f"control molecule is wrong rather than the plumbing")

    print(f"\n{len(FAILURES)} failure(s)"
          + (": " + "; ".join(FAILURES) if FAILURES else ""))
    return 1 if FAILURES else 0


if __name__ == "__main__":
    sys.exit(main())
