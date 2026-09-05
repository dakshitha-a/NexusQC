#!/usr/bin/env python3
"""Does every molecule return the same space on every run?

Until the reference was stabilised, one did not. Twisted ethylene's RHF
converged to either of two solutions 31.5 mHa apart, a projector eigenvalue
followed it across the 0.2 admission threshold, and the recommendation came back
CAS(2e,2o) on 51 runs in 60 and CAS(4e,3o) on the other 9. Every count in the
method document therefore carried a plus-or-minus-one caveat, and a difference
of one molecule between two configurations was not by itself a result.

This is what retires that caveat, or fails and keeps it. The whole
reference-space set, N identical runs each, compared on the selected orbital
indices rather than on the size, because two runs can select the same number of
orbitals without selecting the same ones.

    python3 scripts/casbench/spaces_reproducible.py --repeats 4
"""
from __future__ import annotations

import argparse
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(
    os.path.dirname(__file__)))))

from scripts.casbench import reference_data as ref          # noqa: E402
from scripts.casbench.run_bench import recommend_new        # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repeats", type=int, default=4)
    ap.add_argument("--basis", default="def2-svp")
    ap.add_argument("--molecules", nargs="*")
    args = ap.parse_args()

    names = args.molecules or [n for n in sorted(ref.REFERENCE_SPACES)
                               if n in ref.GEOMETRIES]
    print(f"# Space reproducibility, {args.basis}, {args.repeats} identical "
          f"runs of each of {len(names)} molecules\n")

    unstable, failed = [], []
    t_all = time.time()
    for name in names:
        seen_space, seen_orbitals = set(), set()
        try:
            for _ in range(args.repeats):
                rec, _dt, _mol, _mf = recommend_new(name, basis=args.basis)
                tier = rec.tiers[rec.recommended]
                seen_space.add((tier.n_electrons, tier.n_orbitals))
                seen_orbitals.add(tuple(sorted(int(i)
                                               for i in tier.orbital_indices)))
        except Exception as exc:                            # noqa: BLE001
            print(f"  {name:24s} FAILED {type(exc).__name__}: {str(exc)[:50]}")
            failed.append(name)
            continue
        ok = len(seen_space) == 1 and len(seen_orbitals) == 1
        if not ok:
            unstable.append(name)
            print(f"  {name:24s} NOT REPRODUCIBLE: {sorted(seen_space)}")
        else:
            (ne, no), = seen_space
            print(f"  {name:24s} ({ne}e,{no}o) on all {args.repeats}")

    print(f"\n{len(names) - len(unstable) - len(failed)} of {len(names)} "
          f"reproducible, {len(unstable)} not, {len(failed)} failed, "
          f"in {time.time() - t_all:.0f}s")
    if unstable:
        print("not reproducible: " + ", ".join(unstable))
    return 1 if unstable else 0


if __name__ == "__main__":
    sys.exit(main())
