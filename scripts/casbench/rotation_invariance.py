#!/usr/bin/env python3
"""Does the recommended space depend on the molecule's orientation?

The rotation half of ``run_bench.py --set stability``, on its own. That set
also sweeps five basis sets and runs the legacy recommender alongside, which
makes it an hour; this is the same rotations at the same seed in def2-SVP and
takes a few minutes, so a perception change can be iterated against it before
the full set is spent.

    python3 -u scripts/casbench/rotation_invariance.py
    python3 -u scripts/casbench/rotation_invariance.py --molecule formaldehyde --targets

``--targets`` additionally prints the perceived lone-pair and pi directions,
rotated back into the molecular frame, which is what tells a *span* difference
apart from a genuinely different pool. Two runs that agree on the space but
disagree on the directions are still a defect waiting to surface elsewhere.
"""
import argparse
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))))

from scripts.casbench import reference_data as ref          # noqa: E402
from scripts.casbench.run_bench import _rot, recommend_new  # noqa: E402

SEED = 20260902          # the seed set_stability uses, so rows are comparable
N_ROT = 5


def targets_in_molecular_frame(syms, coords, R):
    """Perceived target axes for the rotated geometry, rotated back."""
    from app.chemistry.cas.geometry import perceive
    per = perceive(syms, coords @ R.T)
    out = []
    for t in per.targets:
        if t.kind not in ("lone_pair", "pi") or t.axis is None:
            continue
        v = np.asarray(t.axis, float) @ R      # back into the molecular frame
        out.append((t.atom_index, t.element, t.kind, t.note, np.round(v, 4)))
    return out


def report_fallback():
    """Which atoms reach `perpendicular_pair`'s arbitrary lab-frame seed?

    Only a terminal heteroatom whose neighbour supplies no plane, which means
    the neighbour is itself terminal or its own neighbours are collinear. That
    is a diatomic or a linear centre, and both are axially symmetric, so there
    genuinely is no molecular direction to seed from. The enumeration is here
    to show the fallback is reached by that structural class and not by
    anything else.
    """
    from app.chemistry.cas.geometry import (_LONE_PAIR_ELEMENTS, local_pi_normal,
                                            perceive, perceive_bonds)
    hits = {}
    for name in sorted(ref.GEOMETRIES):
        syms, co, _c, _m = ref.molecule(name)
        co = np.asarray(co, float)
        nb = perceive_bonds(syms, co)
        for i, el in enumerate(syms):
            if el not in _LONE_PAIR_ELEMENTS or len(nb[i]) != 1:
                continue
            if (local_pi_normal(i, co, nb) is None
                    and local_pi_normal(nb[i][0], co, nb) is None):
                hits.setdefault(name, []).append(f"{el}{i}")

    print("molecules reaching the arbitrary lab-frame seed:")
    for k, v in hits.items():
        print(f"  {k:18s} {', '.join(v)}")
    print(f"  ({len(hits)} of {len(ref.GEOMETRIES)} geometries)")

    for name in list(hits):
        syms, co, _c, _m = ref.molecule(name)
        per = perceive(syms, np.asarray(co, float))
        print(f"\n  {name} pi and lone-pair targets:")
        for t in per.targets:
            if t.kind in ("pi", "lone_pair") and t.axis is not None:
                print(f"    {t.atom_index:2d} {t.element:2s} {t.kind:10s} "
                      f"s_amp={t.s_amplitude!s:5s} "
                      f"{np.round(t.axis, 4)}  {t.note}")
    return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--molecule", default=None,
                    help="one molecule instead of the whole reference set")
    ap.add_argument("--targets", action="store_true",
                    help="also print perceived axes in the molecular frame")
    ap.add_argument("--basis", default="def2-svp")
    ap.add_argument("--fallback", action="store_true",
                    help="enumerate the atoms that reach the arbitrary seed")
    args = ap.parse_args()

    if args.fallback:
        return report_fallback()

    names = ([args.molecule] if args.molecule
             else [n for n in sorted(ref.REFERENCE_SPACES) if n in ref.GEOMETRIES])

    changed = []
    for name in names:
        syms, co, _chg, _mult = ref.molecule(name)
        co = np.asarray(co, float)
        rng = np.random.default_rng(SEED)
        spaces = []
        for k in range(N_ROT):
            R = _rot(rng)
            try:
                rec, _dt, _m, _mfo = recommend_new(name, basis=args.basis,
                                                   coords=co @ R.T)
                spaces.append(rec.space)
            except Exception as exc:                        # noqa: BLE001
                spaces.append(f"ERR {type(exc).__name__}: {exc}")
            if args.targets:
                print(f"  rot {k}: {spaces[-1]}")
                for idx, el, kind, note, v in targets_in_molecular_frame(syms, co, R):
                    print(f"        {idx:2d} {el:2s} {kind:10s} {str(v):28s} {note}")
        distinct = sorted({str(s) for s in spaces})
        flag = "CHANGES" if len(distinct) > 1 else "stable "
        if len(distinct) > 1:
            changed.append(name)
        print(f"  {name:18s} {flag}  {len(distinct)} distinct over {N_ROT}"
              f"   {' '.join(distinct)}")

    print(f"\n  molecules whose space CHANGES under rotation: "
          f"{len(changed)} of {len(names)}")
    if changed:
        print("  " + ", ".join(changed))
    return 1 if changed else 0


if __name__ == "__main__":
    sys.exit(main())
