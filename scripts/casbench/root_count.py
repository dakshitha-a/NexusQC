"""P6.2: how much does a refined space depend on the root count it was solved at?

And P5.2 for free. P5.2 proposes reordering the loop so that ADDING ROOTS is
the first response to a missing state, ahead of reseeding. That is only worth
doing if adding roots ever finds a state that was absent at fewer roots. This
run answers both questions from one sweep: refine each molecule at
ROOT_MARGIN 0, 3 and 6, and record the space, the states found, and the
excitation energies each time.

ROOT_MARGIN's own comment says uracil is the molecule it was set for -- its
n->pi* "only appears once about six roots are solved for". P4.4 and 10.9 later
showed that state was not in the space at all at the shipped lone-pair
amplitude, so the justification was written against a state the space did not
contain. The amplitude is corrected now, so the question is live again and can
be asked properly.
"""
import sys
import time

import numpy as np
from pyscf import tdscf

from app.chemistry.cas import refine as refine_mod
from app.chemistry.cas.excited import analyse
from app.chemistry.cas.geometry import perceive
from app.chemistry.cas.recommend import recommend
from scripts.casbench import reference_data as ref
from scripts.casbench.run_bench import _mf

MARGINS = [0, 3, 6]
MOLECULES = ["formaldehyde", "acetone", "formamide", "pyrrole", "furan",
             "uracil"]
BASIS = "def2-svpd"
N_STATES = 3


def one(name, margin):
    syms, co, chg, mult = ref.molecule(name)
    co = np.asarray(co, float)
    _mol, mf = _mf(syms, co, BASIS, chg, mult)
    rec = recommend(mf, syms, co, spin_2s=mult - 1, n_states=N_STATES)

    _m2, ks = _mf(syms, co, BASIS, chg, mult, dft_xc="camb3lyp")
    td = tdscf.TDA(ks)
    td.nstates = max(6, 2 * (N_STATES - 1))
    td.kernel()
    per = perceive(syms, co, include_sigma=False)
    an = analyse(ks, td, per.targets, n_states=N_STATES - 1)
    predicted = [s.character for s in an.states[:N_STATES - 1]
                 if s.particle_kind != "Rydberg" and "mixed" not in s.character]
    known = getattr(ref, "REFERENCE_STATE_CHARACTERS", {}).get(name)
    if known:
        predicted = list(known[:N_STATES - 1])

    old = refine_mod.ROOT_MARGIN
    refine_mod.ROOT_MARGIN = margin
    t0 = time.time()
    try:
        res = refine_mod.refine(mf, syms, co, rec, n_states=N_STATES,
                                analysis=an, predicted=predicted,
                                spin_2s=mult - 1, log=lambda *a, **k: None)
    finally:
        refine_mod.ROOT_MARGIN = old
    dt = time.time() - t0
    found = [p for p in predicted if p in res.characters]
    return {
        "space": (res.n_electrons, res.n_orbitals),
        "roots": res.n_roots_solved,
        "found": len(found), "wanted": len(predicted),
        "predicted": predicted,
        "chars": list(res.characters),
        "energies": [round(float(x), 3) for x in res.energies_ev],
        "converged": res.converged, "seconds": round(dt, 1),
    }


def main():
    only = sys.argv[1:] or MOLECULES
    results = {}
    for name in only:
        print(f"\n=== {name} " + "=" * 50, flush=True)
        results[name] = {}
        for m in MARGINS:
            try:
                r = one(name, m)
            except Exception as exc:                            # noqa: BLE001
                print(f"  margin {m}: FAILED {type(exc).__name__}: {exc}",
                      flush=True)
                continue
            results[name][m] = r
            print(f"  margin {m}: CAS{str(r['space']):12s} "
                  f"{r['roots']} roots  states {r['found']}/{r['wanted']}  "
                  f"conv={r['converged']}  {r['seconds']:6.1f}s", flush=True)
            print(f"            chars {r['chars']}", flush=True)
            print(f"            eV    {r['energies']}", flush=True)

    print("\n\n########## SUMMARY")
    print(f"{'molecule':14s} " + "  ".join(f"margin{m}" for m in MARGINS))
    for name, by_m in results.items():
        spaces = [str(by_m[m]["space"]) if m in by_m else "ERR" for m in MARGINS]
        same = len(set(spaces)) == 1
        print(f"{name:14s} " + "  ".join(f"{s:9s}" for s in spaces)
              + ("   SAME" if same else "   *** DIFFERS"))

    print("\n########## P5.2: does adding roots ever find a missing state?")
    for name, by_m in results.items():
        seq = [(m, by_m[m]["found"], by_m[m]["wanted"])
               for m in MARGINS if m in by_m]
        gained = [f"margin {m}: {f}/{w}" for m, f, w in seq]
        base = seq[0][1] if seq else None
        better = any(f > base for _m, f, _w in seq[1:]) if seq else False
        print(f"{name:14s} " + ", ".join(gained)
              + ("   *** MORE ROOTS FOUND MORE" if better else "   no gain"))


if __name__ == "__main__":
    main()
