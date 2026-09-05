#!/usr/bin/env python3
"""Which references are bistable, and what following the instability costs.

Twisted ethylene's recommendation is not reproducible because its RHF reference
is not: plain RHF lands on one of two converged solutions 31.5 mHa apart, the
projector eigenvalues follow, and one of them sits close enough to the 0.2
admission threshold that which side it falls on decides the space. Following
the internal instability to a well-defined solution collapses that to one
answer.

Before that becomes the fix, three things have to be known, and this script
measures all three:

  * **How many molecules are affected.** If stabilisation moves any molecule
    that currently matches its literature space, this stops being a one-molecule
    repair and becomes a change to the reference every downstream number is
    taken from.
  * **Whether it works on an open-shell reference at all.** O2, trimethylene-
    methane and CH3 go through ROHF, and a fix that assumes the RHF signature
    would take those paths down.
  * **What it costs.** The recommendation is interactive at 0.23 s median and
    6.2 s at its worst, so a stability analysis that doubles that is a number
    the method document has to carry.

An external instability is reported and never followed. Following one means a
broken-symmetry reference, and `projector.project` takes the alpha set alone for
UHF, so that is a design change rather than a bug fix.

    python3 scripts/casbench/scf_stability.py --repeats 20
"""
from __future__ import annotations

import argparse
import collections
import os
import sys
import time

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(
    os.path.dirname(__file__)))))

from scripts.casbench import reference_data as ref          # noqa: E402

# Everything with a degenerate or near-degenerate reference, plus the molecule
# whose state average is known to be bistable, plus two controls that should be
# boringly single-valued.
DEFAULT = ["ethylene_twisted", "cyclobutadiene_square", "trimethylenemethane",
           "ozone", "N2_stretched", "O2", "acrolein", "ethylene", "water"]

MAX_FOLLOW = 5


def _mol(name, basis):
    from pyscf import gto
    syms, co, chg, mult = ref.molecule(name)
    co = np.asarray(co, float)
    geom = "\n".join(f"{s} {c[0]:.8f} {c[1]:.8f} {c[2]:.8f}"
                     for s, c in zip(syms, co))
    return gto.M(atom=geom, basis=basis, charge=chg, spin=mult - 1, verbose=0)


def _scf(mol):
    from pyscf import scf
    m = scf.RHF(mol) if mol.spin == 0 else scf.ROHF(mol)
    return m.density_fit()


def stabilise(mf):
    """Re-converge until the reference is internally stable.

    Returns the number of times the instability had to be followed, and whether
    an external instability remains. `stability()` returns a two-tuple on some
    reference classes and a four-tuple with `return_status=True`, so the shape
    is normalised here rather than assumed.
    """
    followed, external_ok = 0, None
    for _ in range(MAX_FOLLOW):
        out = mf.stability(return_status=True)
        if len(out) == 4:
            mo_i, _mo_e, stable_i, stable_e = out
        else:                                               # pragma: no cover
            mo_i, _mo_e = out[0], out[1]
            stable_i = stable_e = None
        external_ok = stable_e
        if stable_i is not False:
            break
        mf.kernel(dm0=mf.make_rdm1(mo_i, mf.mo_occ))
        followed += 1
    return followed, external_ok


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--molecules", nargs="*", default=DEFAULT)
    ap.add_argument("--basis", default="def2-svp")
    ap.add_argument("--repeats", type=int, default=20)
    args = ap.parse_args()

    print(f"# SCF reference stability, {args.basis}, {args.repeats} repeats\n")
    print(f"{'molecule':24s} {'ref':5s} {'plain solutions':34s} "
          f"{'stabilised':18s} {'ext':4s} {'cost':>9s}")
    print("-" * 104)

    for name in args.molecules:
        if name not in ref.GEOMETRIES:
            print(f"{name:24s} not in GEOMETRIES")
            continue
        plain, fixed = collections.Counter(), collections.Counter()
        ext_bad, err, t_plain, t_stab = 0, None, 0.0, 0.0
        kind = "RHF"
        for _ in range(args.repeats):
            try:
                mol = _mol(name, args.basis)
                kind = "RHF" if mol.spin == 0 else "ROHF"
                mf = _scf(mol)
                t0 = time.time()
                mf.kernel()
                t_plain += time.time() - t0
                plain[round(float(mf.e_tot), 6)] += 1
                t0 = time.time()
                _followed, ext_ok = stabilise(mf)
                t_stab += time.time() - t0
                fixed[round(float(mf.e_tot), 6)] += 1
                if ext_ok is False:
                    ext_bad += 1
            except Exception as exc:                        # noqa: BLE001
                err = f"{type(exc).__name__}: {exc}"
                break
        if err:
            print(f"{name:24s} {kind:5s} FAILED {err[:70]}")
            continue

        def show(counter):
            return " ".join(f"{e}x{n}" for e, n in
                            sorted(counter.items(), key=lambda kv: kv[0]))

        flag = "  <-- BISTABLE" if len(plain) > 1 else ""
        moved = ("  <-- MOVED" if plain and fixed
                 and min(plain) != min(fixed) else "")
        print(f"{name:24s} {kind:5s} {show(plain):34s} "
              f"{show(fixed):18s} {ext_bad:>2d}/{args.repeats} "
              f"{t_stab / max(t_plain, 1e-9):>7.2f}x{flag}{moved}")

    print("\n'ext' counts runs whose closed-shell reference is unstable toward "
          "an open-shell one.\n'cost' is the stability analysis as a multiple "
          "of the plain SCF it follows.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
