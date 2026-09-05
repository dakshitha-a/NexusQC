"""P4.2: the refinement's own constants, swept on a named subset.

Phase 4 swept the perception and pool constants, which decide what goes INTO
the space. These are the ones that decide what the refinement takes back out:

  INERT_OCCUPIED / INERT_VIRTUAL  the natural-occupation window outside which
                                  an orbital is judged to carry nothing
  MAX_ENERGY_DRIFT_EV             how far a requested excitation may move
                                  under a prune before the prune is refused

`ROOT_MARGIN` is the third refinement constant and is NOT swept here. P6.2
already measured it at 0, 3 and 6 across six molecules and found the refined
space unchanged wherever the solve converged; re-running it would be repeating
that experiment at three times the cost. Cite P6.2 instead.

The subset is named rather than the whole benchmark, and named for a reason.
Nine of the thirty molecules reach a fixed point with no prune at all, so they
can carry no information about a prune threshold no matter what it is set to.
What is here is every molecule whose refinement actually prunes or whose prune
was refused, plus formaldehyde as a control that should move nowhere.

The question this is really being asked to settle is uracil's. Three separate
observations now point at MAX_ENERGY_DRIFT_EV: the (14,10) in the committed
ledger was preserved by a prune refused at 0.30 eV; after the perception fix
the same prune costs less than the tolerance and the answer is (12,9); and P6.1
showed that outcome is identical in three basis sets, so it is not noise. The
honest test is whether any OTHER molecule moves anywhere in this grid. If none
does, the constants are flat and uracil sits on a knife edge that a tolerance
cannot fix, and moving one to recover its literature space would be fitting to
the reference rather than to the physics -- exactly what P4.0 and P4.4 refused
to do with the lone-pair amplitude.

Run:  PYTHONPATH=$PWD python3 scripts/casbench/refine_constants.py
"""
import sys
import time

import numpy as np
from pyscf import tdscf

from app.chemistry.cas import refine as refine_mod
from app.chemistry.cas.excited import analyse
from app.chemistry.cas.geometry import perceive
from app.chemistry.cas.narrow import add_state_narrowed_tier
from app.chemistry.cas.recommend import recommend
from scripts.casbench import reference_data as ref
from scripts.casbench.run_bench import _mf

BASIS = "def2-svpd"

# molecule -> n_states. Every one either prunes, has a prune refused, or is a
# control that must not move.
SUBSET = {
    "formaldehyde": 3,     # control: fixed point, no prune, must not move
    "acetone": 3,          # control
    "water": 1,            # prunes twice, the clearest prune in the set
    "N2": 1,               # prune refused on the absolute-energy guard
    "pyrrole": 3,          # reaches its reference without pruning
    "uracil": 3,           # narrow+prune, the molecule this exists for
}

DRIFTS = [0.10, 0.20, 0.30, 0.50]
INERTS = [1.95, 1.98, 1.99]


def build(name, n_states):
    syms, co, chg, mult = ref.molecule(name)
    co = np.asarray(co, float)
    _mol, mf = _mf(syms, co, BASIS, chg, mult)
    rec = recommend(mf, syms, co, spin_2s=mult - 1, n_states=n_states)
    an, predicted = None, []
    if mult == 1 and n_states > 1:
        _m2, ks = _mf(syms, co, BASIS, chg, mult, dft_xc="camb3lyp")
        td = tdscf.TDA(ks)
        td.nstates = max(6, 2 * (n_states - 1))
        td.kernel()
        per = perceive(syms, co, include_sigma=False)
        an = analyse(ks, td, per.targets, n_states=n_states - 1)
        predicted = [s.character for s in an.states[:n_states - 1]
                     if s.particle_kind != "Rydberg"
                     and "mixed" not in s.character]
        known = getattr(ref, "REFERENCE_STATE_CHARACTERS", {}).get(name)
        if known:
            predicted = list(known[:n_states - 1])
        add_state_narrowed_tier(rec, mf.mol, an, n_states, per.targets,
                                perception=per, spin_2s=mult - 1)
    return syms, co, mf, rec, an, predicted, mult - 1


def run(name, n_states, *, drift, inert):
    syms, co, mf, rec, an, predicted, spin = build(name, n_states)
    old_d, old_i, old_v = (refine_mod.MAX_ENERGY_DRIFT_EV,
                           refine_mod.INERT_OCCUPIED, refine_mod.INERT_VIRTUAL)
    refine_mod.MAX_ENERGY_DRIFT_EV = drift
    refine_mod.INERT_OCCUPIED = inert
    refine_mod.INERT_VIRTUAL = round(2.0 - inert, 3)
    t0 = time.time()
    try:
        res = refine_mod.refine(mf, syms, co, rec, n_states=n_states,
                                analysis=an, predicted=predicted,
                                spin_2s=spin, log=lambda *a, **k: None)
    finally:
        (refine_mod.MAX_ENERGY_DRIFT_EV, refine_mod.INERT_OCCUPIED,
         refine_mod.INERT_VIRTUAL) = old_d, old_i, old_v
    return ((res.n_electrons, res.n_orbitals), res.converged,
            round(time.time() - t0, 1), res.stopped_because[:60])


def main():
    only = sys.argv[1:] or list(SUBSET)
    shipped = (refine_mod.MAX_ENERGY_DRIFT_EV, refine_mod.INERT_OCCUPIED)
    print(f"shipped: MAX_ENERGY_DRIFT_EV={shipped[0]}  "
          f"INERT_OCCUPIED={shipped[1]}\n")

    moved = {}
    for name in only:
        n_states = SUBSET[name]
        print(f"=== {name} (SA-{n_states}) " + "=" * 40, flush=True)
        seen = {}

        print("  MAX_ENERGY_DRIFT_EV, at the shipped occupation window")
        for d in DRIFTS:
            sp, conv, dt, why = run(name, n_states, drift=d,
                                    inert=shipped[1])
            seen[("drift", d)] = sp
            mark = "  <-- shipped" if d == shipped[0] else ""
            print(f"    {d:.2f} eV -> CAS{str(sp):9s} conv={conv} "
                  f"{dt:7.1f}s  {why}{mark}", flush=True)

        print("  INERT_OCCUPIED, at the shipped drift tolerance")
        for i in INERTS:
            sp, conv, dt, why = run(name, n_states, drift=shipped[0], inert=i)
            seen[("inert", i)] = sp
            mark = "  <-- shipped" if i == shipped[1] else ""
            print(f"    {i:.2f}    -> CAS{str(sp):9s} conv={conv} "
                  f"{dt:7.1f}s  {why}{mark}", flush=True)

        distinct = {str(v) for v in seen.values()}
        moved[name] = distinct
        print(f"  => {len(distinct)} distinct space(s) over the whole grid: "
              f"{sorted(distinct)}\n", flush=True)

    print("\n########## SUMMARY")
    flat = [n for n, d in moved.items() if len(d) == 1]
    varies = [n for n, d in moved.items() if len(d) > 1]
    for name in only:
        d = moved[name]
        print(f"{name:14s} {'FLAT' if len(d) == 1 else '*** VARIES':10s} "
              f"{sorted(d)}")
    print(f"\n{len(flat)} of {len(only)} molecules are flat across the entire "
          f"grid.")
    if varies:
        print(f"Varies: {', '.join(varies)}")
    if len(varies) <= 1:
        print("\nWith at most one molecule moving anywhere in the grid, these "
              "constants are\nflat in the sense P4.0 established for the "
              "lone-pair amplitude: not delicate,\nand not to be tuned to one "
              "molecule's answer.")


if __name__ == "__main__":
    main()
