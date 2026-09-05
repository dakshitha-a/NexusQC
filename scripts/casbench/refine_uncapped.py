#!/usr/bin/env python3
"""What the two molecules that never finish actually need.

`run_bench.set_refine` bounds each molecule at ten minutes, and two never
finish inside it. The backlog recorded that as "o-nitrophenol and
p-benzoquinone exceed the ten-minute refinement cap", which names the wrong
molecule: o-nitrophenol refines in 454.6 s. The two are **anthracene**, which
dies with a MemoryError building its CI diagonal, and **p-benzoquinone**, which
reaches the cap.

Those are different failures and only one of them is about time. A cap is a
property of the benchmark harness and not of the product, which has no
wall-clock bound at all and for which long runtimes are the design premise, so
"it takes longer than ten minutes" is a fact about this script rather than a
defect. "It cannot be built at any length of time" is a real limitation and
needs a number attached.

Run without a cap and record what each one does.

    python3 scripts/casbench/refine_uncapped.py
"""
from __future__ import annotations

import argparse
import os
import resource
import sys
import time

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(
    os.path.dirname(__file__)))))

from scripts.casbench import reference_data as ref          # noqa: E402
from scripts.casbench.run_bench import (_protocol_states,        # noqa: E402
                                        recommend_with_states)

DEFAULT = ["p-benzoquinone", "anthracene"]


def _peak_gb():
    return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / (1024.0 ** 2)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--molecules", nargs="*", default=DEFAULT)
    ap.add_argument("--basis", default="def2-svpd")
    args = ap.parse_args()

    from app.chemistry.cas import feasibility
    from app.chemistry.cas.refine import refine

    print(f"# Refinement without a time cap, {args.basis}\n")
    for name in args.molecules:
        if name not in ref.GEOMETRIES:
            print(f"{name}: not in GEOMETRIES")
            continue
        syms, co, _chg, mult = ref.molecule(name)
        co = np.asarray(co, float)
        n_states = _protocol_states(name)
        print(f"=== {name} ===")
        t0 = time.time()
        try:
            rec, _dt, _mol, mf = recommend_with_states(
                name, basis=args.basis, n_states=n_states)
            tier = rec.tiers[rec.recommended]
            f = feasibility.assess(tier.n_orbitals, tier.n_electrons, mult - 1)
            print(f"    starting space CAS({tier.n_electrons}e,"
                  f"{tier.n_orbitals}o), {f.n_csf:,} CSFs, "
                  f"{n_states} state(s) requested")
            res = refine(mf, syms, co, rec, n_states=n_states,
                         spin_2s=mult - 1,
                         log=lambda m: print(f"    {m}", flush=True))
            print(f"    FINISHED CAS({res.n_electrons}e,{res.n_orbitals}o) "
                  f"converged={res.converged} in {time.time() - t0:.0f}s, "
                  f"peak RSS {_peak_gb():.1f} GB")
            print(f"    stopped because: {res.stopped_because}")
        except MemoryError as exc:
            print(f"    MemoryError after {time.time() - t0:.0f}s at "
                  f"{_peak_gb():.1f} GB peak RSS: {str(exc)[:90]}")
            print("    This is not a time limit. No cap length reaches it.")
        except Exception as exc:                            # noqa: BLE001
            print(f"    {type(exc).__name__} after {time.time() - t0:.0f}s: "
                  f"{str(exc)[:120]}")
        print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
