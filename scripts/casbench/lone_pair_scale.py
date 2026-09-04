"""Is the lone-pair weight on the same scale for every element?

`refine.LONE_PAIR_OVER_SIGMA` is a single number, 0.50, applied to a weight that
may not mean the same thing on oxygen as on sulfur. The threshold decides
whether an orbital is reported as `n`, as `n/sigma`, or as `sigma`, and the
suspicion on record is that it is element-dependent: a thiol's lone pair scoring
0.78 where an amine's scores 0.99 would make one threshold strict on one element
and lax on another, for no chemical reason.

This measures the scale rather than the labels. For every heteroatom in the
benchmark it finds the occupied orbital with the highest lone-pair weight on
that atom, which for a heteroatom carrying lone pairs is one, and reports the
weight. If the distributions per element overlap the threshold differently, a
single number cannot serve them all and the threshold should be element-aware.

No CASSCF, no excited states: an SCF and a projection per molecule.

Usage:
    python3 scripts/casbench/lone_pair_scale.py
"""
import os
import sys
from collections import defaultdict

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))))

from pyscf import gto, scf                                       # noqa: E402

from app.chemistry.cas.excited import _target_weights            # noqa: E402
from app.chemistry.cas.geometry import perceive                  # noqa: E402
from app.chemistry.cas.refine import (LONE_PAIR_AMBIGUOUS,       # noqa: E402
                                      LONE_PAIR_OVER_SIGMA)
from scripts.casbench import reference_data as ref               # noqa: E402

BASIS = os.environ.get("QC_LP_BASIS", "def2-svp")


def main(names):
    print("# Is the lone-pair weight on the same scale for every element?")
    print("")
    print(f"{BASIS}. For each heteroatom, the highest lone-pair weight found "
          f"on any occupied orbital, which for an atom that carries lone pairs "
          f"is one of them. Thresholds in force: n beats sigma at "
          f"{LONE_PAIR_OVER_SIGMA}, ambiguous band down to {LONE_PAIR_AMBIGUOUS}.")
    print("")
    print("| molecule | atom | element | best lone-pair weight | sigma weight there | label it gets |")
    print("|---|---|---|---|---|---|")
    by_element = defaultdict(list)
    for name in names:
        try:
            syms, co, chg, mult = ref.molecule(name)
            co = np.asarray(co, float)
            atom = "\n".join(f"{s} {c[0]:.8f} {c[1]:.8f} {c[2]:.8f}"
                             for s, c in zip(syms, co))
            mol = gto.M(atom=atom, basis=BASIS, charge=int(chg),
                        spin=int(mult) - 1, verbose=0)
            mf = (scf.RHF(mol) if mult == 1 else scf.ROHF(mol)).density_fit()
            mf.kernel()
            per = perceive(syms, co, include_sigma=True)
        except Exception as exc:                                 # noqa: BLE001
            print(f"| {name} | | | | | failed: {type(exc).__name__} |")
            continue

        occ_idx = np.where(np.asarray(mf.mo_occ, float) > 0)[0]
        for t in per.targets:
            if t.kind != "lone_pair":
                continue
            here = [x for x in per.targets
                    if x.kind == "lone_pair" and x.atom_index == t.atom_index]
            sig = [x for x in per.targets if x.kind == "sigma"]
            best, best_sig = 0.0, 0.0
            for j in occ_idx:
                v = mf.mo_coeff[:, j]
                w = _target_weights(mol, v, here).get("lone_pair", 0.0)
                if w > best:
                    best = w
                    best_sig = _target_weights(mol, v, sig).get("sigma", 0.0)
            el = syms[t.atom_index]
            if best >= LONE_PAIR_OVER_SIGMA or best > best_sig:
                label = "n"
            elif best >= LONE_PAIR_AMBIGUOUS:
                label = "n/sigma"
            else:
                label = "sigma"
            by_element[el].append(best)
            print(f"| {name} | {t.atom_index} | {el} | {best:.3f} | "
                  f"{best_sig:.3f} | {label} |")
            break        # one row per molecule per atom is enough
        sys.stdout.flush()

    print("")
    print("## By element")
    print("")
    print("| element | n | lowest | highest | median |")
    print("|---|---|---|---|---|")
    for el in sorted(by_element):
        v = sorted(by_element[el])
        med = v[len(v) // 2]
        print(f"| {el} | {len(v)} | {v[0]:.3f} | {v[-1]:.3f} | {med:.3f} |")
    print("")
    spread = {el: (min(v), max(v)) for el, v in by_element.items()}
    straddle = [el for el, (lo, hi) in spread.items()
                if lo < LONE_PAIR_OVER_SIGMA <= hi]
    print(f"Elements whose range straddles the {LONE_PAIR_OVER_SIGMA} "
          f"threshold: {straddle or 'none'}")


if __name__ == "__main__":
    args = sys.argv[1:]
    main(args or [n for n in sorted(ref.GEOMETRIES)])
