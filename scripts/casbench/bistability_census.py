#!/usr/bin/env python3
"""How many molecules have more than one converged state-averaged solution?

Acrolein does. Twenty identical SA-CASSCF runs in its recommended CAS(8e,6o)
land on E0 = -190.823527 Ha sixteen times and -190.824866 four times, 36.4 meV
apart, disagreeing about the character of two roots, and every one of them
reports convergence. Within a solution the reproducibility is exact.

That is on record. What is not is whether acrolein is unusual or ordinary, and
the difference decides what the product should say. A defect one molecule in
thirty has is a caveat on that molecule; one that half of them have is a
property of the method and belongs in the headline. Acrolein was the only
molecule ever measured at repeat, so the honest answer was that nobody knew.

The measurement is deliberately narrow: the same space, the same protocol, N
identical runs, count the distinct converged ground-state energies. Anything
that separates by more than the within-solution spread is a second solution.
Root characters are recorded alongside, because two solutions that agree on E0
to a few microhartree and disagree about which root is which are still two
answers to a user.

    python3 scripts/casbench/bistability_census.py --repeats 6
    python3 scripts/casbench/bistability_census.py --molecules acrolein --repeats 20
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
from scripts.casbench.run_bench import recommend_new        # noqa: E402

# Two runs are the same solution when their ground-state energies agree to
# better than this. The within-solution spread measured on acrolein over
# sixteen runs is 0.0007 meV, and the gap between its two solutions is 36.4
# meV, so anything between those separates them; 1 meV sits well inside the
# gap and far above the noise.
SAME_SOLUTION_EV = 1e-3

# Above this the CI is too large to repeat several times over for a census.
MAX_CSF = 200_000


def one_run(name, basis, n_states):
    from pyscf import mcscf

    from app.chemistry.cas import feasibility
    from app.chemistry.cas.geometry import perceive
    from app.chemistry.cas.refine import (_as_nelec, _root_characters,
                                          _spin_adapt)

    rec, _dt, mol, mf = recommend_new(name, basis=basis)
    tier = rec.tiers[rec.recommended]
    ne, no = tier.n_electrons, tier.n_orbitals
    syms, co, _chg, mult = ref.molecule(name)
    co = np.asarray(co, float)
    spin_2s = mult - 1

    f = feasibility.assess(no, ne, spin_2s)
    if not f.n_csf or f.n_csf > MAX_CSF:
        return None, f.n_csf, (ne, no)

    nroots = max(1, min(n_states, int(f.n_csf)))
    mc = mcscf.CASSCF(mf, no, _as_nelec(ne, spin_2s))
    _spin_adapt(mc, mol)
    mc.fcisolver.nroots = nroots
    if nroots > 1:
        mc.state_average_([1.0 / nroots] * nroots)
    mc.max_cycle_macro = 100
    mc.conv_tol, mc.conv_tol_grad = 1e-8, 1e-5
    mc.kernel(np.asarray(rec.mo_coeff))

    e = np.atleast_1d(np.asarray(getattr(mc, "e_states", mc.e_tot), float))
    per = perceive(syms, co, include_sigma=False)
    pi_t = [t for t in per.targets if t.kind == "pi"]
    lp_t = [t for t in per.targets if t.kind == "lone_pair"]
    chars = tuple(_root_characters(mc, mol, pi_t, lp_t)) if nroots > 1 else ()
    return {
        "e0": float(e[0]),
        "converged": bool(mc.converged),
        "characters": chars,
    }, f.n_csf, (ne, no)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--molecules", nargs="*")
    ap.add_argument("--basis", default="cc-pvdz")
    ap.add_argument("--states", type=int, default=4)
    ap.add_argument("--repeats", type=int, default=6)
    args = ap.parse_args()

    names = args.molecules or [n for n in sorted(ref.EXCITATIONS)
                               if n in ref.GEOMETRIES
                               and ref.molecule(n)[3] == 1]

    print(f"# Bistability census, {args.basis}, {args.states} roots, "
          f"{args.repeats} identical runs each\n")
    print(f"{'molecule':18s} {'space':10s} {'solutions':>9s} {'spread/meV':>11s} "
          f"{'conv':>6s}  characters differ")
    print("-" * 78)

    bistable = []
    for name in names:
        t0 = time.time()
        runs, n_csf, space = [], None, None
        try:
            for _ in range(args.repeats):
                got, n_csf, space = one_run(name, args.basis, args.states)
                if got is None:
                    break
                runs.append(got)
        except Exception as exc:                            # noqa: BLE001
            print(f"{name:18s} FAILED {type(exc).__name__}: {str(exc)[:44]}")
            continue
        if not runs:
            print(f"{name:18s} {str(space):10s} skipped, {n_csf:,} CSFs")
            continue

        # Cluster the ground-state energies. A solution is a group whose
        # members agree to better than SAME_SOLUTION_EV.
        ev = sorted(r["e0"] * 27.211386245988 for r in runs)
        groups = [[ev[0]]]
        for x in ev[1:]:
            if x - groups[-1][-1] <= SAME_SOLUTION_EV:
                groups[-1].append(x)
            else:
                groups.append([x])
        spread = (max(ev) - min(ev)) * 1000.0
        n_conv = sum(1 for r in runs if r["converged"])
        char_sets = {r["characters"] for r in runs}
        flag = "  <-- BISTABLE" if len(groups) > 1 else ""
        print(f"{name:18s} {f'({space[0]}e,{space[1]}o)':10s} "
              f"{len(groups):>9d} {spread:>11.3f} "
              f"{n_conv:>3d}/{len(runs):<2d} {len(char_sets) > 1!s:>5s}"
              f"{flag}   {time.time() - t0:.0f}s")
        if len(groups) > 1:
            bistable.append(name)
            for g in groups:
                print(f"    {len(g)} run(s) at E0 = {g[0] / 27.211386245988:.6f} Ha")

    print(f"\n{len(bistable)} of {len(names)} molecules have more than one "
          f"converged solution"
          + (": " + ", ".join(bistable) if bistable else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
