"""P6.1: is the REFINED space the same in three basis sets?

Section 5 establishes that the RECOMMENDATION is basis independent, and 10.7
measures it: the projection targets live in a fixed minimal reference basis, so
re-asking the question in another basis reproduces the same space. None of that
says anything about the refinement, which is a different claim and a weaker one
by construction.

The refinement solves a state-averaged CASSCF and then edits the space against
what the solve found: it checks the chosen orbital character survived, checks
the requested states are present, and prunes orbitals whose natural occupation
shows they carry no correlation. Every one of those readings comes from a
correlated wavefunction computed IN a basis, so there is no mechanism making
the answer basis independent, and an occupation near the prune threshold can
fall on either side of it in two bases that describe the molecule equally well.

Three molecules by design rather than the whole set: this is nine refinements
and uracil alone is about ten minutes each. Formaldehyde is the cheap control
whose space nothing has ever moved, pyrrole is a ring whose reference the
engine reaches only after narrowing, and uracil is the regression case for four
other steps and the one molecule whose prune is known to sit near its drift
tolerance.

Run:  PYTHONPATH=$PWD python3 scripts/casbench/refine_basis.py
"""
import sys
import time

import numpy as np
from pyscf import tdscf

from app.chemistry.cas.excited import analyse
from app.chemistry.cas.geometry import perceive
from app.chemistry.cas.narrow import add_state_narrowed_tier
from app.chemistry.cas.recommend import recommend
from app.chemistry.cas.refine import refine
from scripts.casbench import reference_data as ref
from scripts.casbench.run_bench import _mf

BASES = ["def2-svp", "def2-svpd", "cc-pvdz"]
MOLECULES = ["formaldehyde", "pyrrole", "uracil"]
N_STATES = 3


def one(name, basis):
    syms, co, chg, mult = ref.molecule(name)
    co = np.asarray(co, float)
    _mol, mf = _mf(syms, co, basis, chg, mult)
    rec = recommend(mf, syms, co, spin_2s=mult - 1, n_states=N_STATES)
    quick_pool = rec.space

    _m2, ks = _mf(syms, co, basis, chg, mult, dft_xc="camb3lyp")
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

    # The production path narrows before refining, so this has to as well or it
    # measures a starting point the product never uses.
    add_state_narrowed_tier(rec, mf.mol, an, N_STATES, per.targets,
                            perception=per, spin_2s=mult - 1)
    narrowed = rec.space

    t0 = time.time()
    res = refine(mf, syms, co, rec, n_states=N_STATES, analysis=an,
                 predicted=predicted, spin_2s=mult - 1,
                 log=lambda *a, **k: None)
    return {
        "pool": quick_pool, "narrowed": narrowed,
        "refined": (res.n_electrons, res.n_orbitals),
        "found": len([p for p in predicted if p in res.characters]),
        "wanted": len(predicted),
        "converged": res.converged,
        "rotations": [r.action for r in res.rotations],
        "occ": [round(float(x), 3) for x in res.occupations],
        "seconds": round(time.time() - t0, 1),
    }


def main():
    only = sys.argv[1:] or MOLECULES
    results = {}
    for name in only:
        print(f"\n=== {name} " + "=" * 52, flush=True)
        results[name] = {}
        for b in BASES:
            try:
                r = one(name, b)
            except Exception as exc:                            # noqa: BLE001
                print(f"  {b:11s} FAILED {type(exc).__name__}: {exc}",
                      flush=True)
                continue
            results[name][b] = r
            print(f"  {b:11s} pool {str(r['pool']):9s} -> narrowed "
                  f"{str(r['narrowed']):9s} -> refined "
                  f"{str(r['refined']):9s}  states {r['found']}/{r['wanted']} "
                  f" conv={r['converged']}  {r['seconds']:7.1f}s  "
                  f"{'+'.join(r['rotations']) or 'no change'}", flush=True)
            print(f"              occupations {r['occ']}", flush=True)

    print("\n\n########## SUMMARY: is the refined space basis independent?")
    ref_sp = ref.REFERENCE_SPACES
    for name, by_b in results.items():
        spaces = [str(by_b[b]["refined"]) for b in BASES if b in by_b]
        lit = str(tuple(ref_sp[name][0])) if name in ref_sp else "-"
        same = len(set(spaces)) == 1
        print(f"{name:14s} " + "  ".join(f"{s:9s}" for s in spaces)
              + f"   literature {lit}"
              + ("   SAME" if same else "   *** DIFFERS"))
    print("\n(the recommendation is basis independent by construction and "
          "10.7 measures it;\n this asks the separate question about the "
          "refinement, which has no such guarantee)")


if __name__ == "__main__":
    main()
