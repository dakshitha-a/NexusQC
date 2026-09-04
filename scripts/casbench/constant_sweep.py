"""Sweep any perception or pool constant against the literature space match.

The engine has roughly twenty-five tunable constants and until 2026-09 exactly
one of them had been swept. That is the wrong ratio for numbers that decide
which orbitals a user gets, and the sweep that was done taught the lesson this
script exists to make cheap: `LONE_PAIR_S_AMPLITUDE` looked completely flat when
scored on the literature match and turned out to be the difference between a
space that can describe an n->pi* state and one that cannot.

So the point here is not to find better values. It is to know which constants
are load-bearing at all, and a flat row is a real result: it says the answer
does not turn on that number, which is worth having written down.

This sweeps the GROUND-STATE recommendation only, which is what makes it cheap
enough to run over every constant: no TDA, no excited states, about a tenth of a
second per molecule. Constants that only matter when states are requested are
listed below but not swept here, because the states-requested column drives the
production runner and costs about a thousand times more per point; use
`amplitude_tradeoff.py` for those.

Usage:
    python3 scripts/casbench/constant_sweep.py                       # all
    python3 scripts/casbench/constant_sweep.py projector.THRESHOLD
"""
import importlib
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))))

from app.chemistry.cas.recommend import recommend                # noqa: E402
from scripts.casbench import reference_data as ref               # noqa: E402
from scripts.casbench.run_bench import _mf                       # noqa: E402

BASIS = "def2-svp"

# module path -> (constant, values to try, one line on what it decides)
SWEEPS = {
    "app.chemistry.cas.projector.THRESHOLD": (
        [0.05, 0.10, 0.15, 0.20, 0.30, 0.40],
        "eigenvalue above which a projected orbital joins the pool; inherited "
        "from AVAS and decides pool size for everything downstream"),
    "app.chemistry.cas.geometry.PLANARITY_COS": (
        [0.10, 0.20, 0.25, 0.35, 0.50],
        "largest |cos| between a bond and the fitted normal that still counts "
        "as a planar centre, so it decides which atoms get a pi target"),
    "app.chemistry.cas.geometry.BOND_TOLERANCE": (
        [1.15, 1.25, 1.30, 1.40, 1.50],
        "covalent-radius multiplier for deciding a bond exists, which decides "
        "the whole connectivity perception is built on"),
    "app.chemistry.cas.recommend.MINIMAL_ENTROPY_GAP": (
        [0.05, 0.10, 0.15, 0.25, 0.40],
        "entropy gap that separates the minimal tier from the recommended one"),
}


def _set(path, value):
    mod_name, attr = path.rsplit(".", 1)
    mod = importlib.import_module(mod_name)
    old = getattr(mod, attr)
    setattr(mod, attr, value)
    return mod, attr, old


def names():
    return [n for n in sorted(ref.REFERENCE_SPACES) if n in ref.GEOMETRIES]


def score():
    """Ground-state literature match over the benchmark: (exact, +tier, n)."""
    exact = tier = total = 0
    for name in names():
        expected = tuple(ref.REFERENCE_SPACES[name][0])
        syms, co, chg, mult = ref.molecule(name)
        co = np.asarray(co, float)
        try:
            _mol, mf = _mf(syms, co, BASIS, chg, mult)
            rec = recommend(mf, syms, co, spin_2s=mult - 1)
        except Exception:                                        # noqa: BLE001
            total += 1
            continue
        tiers = {(t.n_electrons, t.n_orbitals) for t in rec.tiers.values()}
        total += 1
        if rec.space == expected:
            exact += 1
            tier += 1
        elif expected in tiers:
            tier += 1
    return exact, tier, total


def main(which):
    print("# Perception and pool constants against the literature space match")
    print("")
    print(f"Ground-state request, {BASIS}, every molecule with a reference "
          f"space. A FLAT row means the answer does not turn on that constant, "
          f"which is the useful result more often than a peak is.")
    for path in which:
        values, what = SWEEPS[path]
        mod_name, attr = path.rsplit(".", 1)
        mod = importlib.import_module(mod_name)
        shipped = getattr(mod, attr)
        print("")
        print(f"## `{attr}` (shipped {shipped})")
        print("")
        print(f"{what}.")
        print("")
        print("| value | exact | +tier |")
        print("|---|---|---|")
        for v in values:
            _m, _a, old = _set(path, v)
            try:
                e, t, n = score()
                mark = " (shipped)" if v == shipped else ""
                print(f"| {v}{mark} | {e}/{n} | {t}/{n} |")
            finally:
                setattr(mod, attr, old)
            sys.stdout.flush()


if __name__ == "__main__":
    args = sys.argv[1:]
    chosen = []
    for a in args:
        hit = [k for k in SWEEPS if k.endswith(a) or k == a]
        if not hit:
            sys.exit(f"unknown constant {a}; known: {sorted(SWEEPS)}")
        chosen.extend(hit)
    main(chosen or list(SWEEPS))
