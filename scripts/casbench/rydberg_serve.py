#!/usr/bin/env python3
"""Can a space that contains the Rydberg orbital actually be solved?

`excited.augment` refuses to add a Rydberg particle orbital, and its reasoning
is sound as far as it goes: a diffuse orbital does not mix appreciably with the
valence set, and dropping one into a valence active space is a known way to make
a CASSCF hard to converge without improving the valence states it was built for.

That reasoning is about a valence space acquiring a diffuse orbital as a side
effect. It does not answer the different question of what to do when the Rydberg
state is the one the user asked about, and the reported case is concrete:
methylamine at SA(2)-CASSCF/aug-cc-pVDZ in CAS(8e,9o), where S1 carries Rydberg
character.

So this runs both branches on the same molecules and compares them on what
actually matters, which is not the size of the space:

  * does the state-averaged CASSCF **converge**;
  * is the requested state **present**, with Rydberg character;
  * is its excitation energy **defensible** against the linear-response value
    the space was built from.

A space that comes out the right size and does not converge, or converges
without the state in it, is a worse answer than an honest refusal.

    python3 scripts/casbench/rydberg_serve.py
    python3 scripts/casbench/rydberg_serve.py --molecules methylamine
"""
from __future__ import annotations

import argparse
import os
import sys
import time

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(
    os.path.dirname(__file__)))))

from scripts.casbench import reference_data as ref          # noqa: E402
from scripts.casbench.run_bench import _mf                  # noqa: E402

DEFAULT = ["methylamine", "ammonia", "formaldehyde", "pyrrole"]


def build(name, basis, n_states):
    from pyscf import tdscf

    from app.chemistry.cas.diffuse import rydberg_representable
    from app.chemistry.cas.excited import analyse
    from app.chemistry.cas.geometry import perceive
    from app.chemistry.cas.recommend import recommend
    from app.chemistry.cas.reference import stabilise

    syms, co, chg, mult = ref.molecule(name)
    co = np.asarray(co, float)

    _mol, mfhf = _mf(syms, co, basis, chg, mult)
    stabilise(mfhf, check_external=False)
    rec = recommend(mfhf, syms, co, spin_2s=mult - 1)

    _m2, ks = _mf(syms, co, basis, chg, mult, dft_xc="camb3lyp")
    td = tdscf.TDA(ks)
    td.nstates = max(2 * n_states, 6)
    td.kernel()
    per = perceive(syms, co, include_sigma=False)
    an = analyse(ks, td, per.targets, n_states=n_states,
                 rydberg_detectable=bool(rydberg_representable(ks)))
    return mfhf, rec, an, syms, co, mult


def solve(mf, mo, ncore, ncas, nelec, nroots, spin_2s):
    """One state-averaged CASSCF, spin-adapted the way the refinement does it."""
    from pyscf import mcscf

    from app.chemistry.cas.refine import _as_nelec, _spin_adapt

    mc = mcscf.CASSCF(mf, ncas, _as_nelec(nelec, spin_2s))
    _spin_adapt(mc, mf.mol)
    mc.fcisolver.nroots = nroots
    mc.state_average_([1.0 / nroots] * nroots)
    mc.max_cycle_macro = 100
    mc.conv_tol, mc.conv_tol_grad = 1e-8, 1e-5
    mc.mo_coeff = mo
    mc.kernel(mo)
    return mc


def characters(mc, mol, targets, nroots, detectable):
    from app.chemistry.cas.verify import _root_characters
    return _root_characters(mc, mol, targets, nroots, detectable)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--molecules", nargs="*", default=DEFAULT)
    ap.add_argument("--basis", default="aug-cc-pvdz")
    ap.add_argument("--states", type=int, default=2)
    args = ap.parse_args()

    from app.chemistry.cas.diffuse import rydberg_representable
    from app.chemistry.cas.excited import augment
    from app.chemistry.cas.geometry import perceive

    print(f"# Serving a Rydberg state, {args.basis}, "
          f"{args.states} states requested\n")

    for name in args.molecules:
        if name not in ref.GEOMETRIES:
            print(f"{name}: not in GEOMETRIES\n")
            continue
        print(f"=== {name} ===")
        try:
            mf, rec, an, syms, co, mult = build(name, args.basis, args.states)
        except Exception as exc:                            # noqa: BLE001
            print(f"    setup FAILED {type(exc).__name__}: {exc}\n")
            continue

        wanted = an.states[:args.states]
        for s in wanted:
            print(f"    TDA S{s.index} {s.energy_ev:6.2f} eV  {s.character}")
        if not any(s.particle_kind == "Rydberg" for s in wanted):
            print("    no Rydberg state among the requested ones; skipped\n")
            continue

        tier = rec.tiers[rec.recommended]
        detectable = bool(rydberg_representable(mf))
        targets = perceive(syms, co, include_sigma=False).targets
        nroots = args.states

        for label, allow in (("refuse", False), ("serve", True)):
            mo0 = np.asarray(rec.mo_coeff).copy()
            ncore, ncas = rec.ncore, tier.n_orbitals
            nelec = tier.n_electrons
            mo, n_added, _notes = augment(
                mo0, ncore, ncas, an, mf.mol, args.states,
                allow_rydberg=allow)
            ncas2 = ncas + n_added
            t0 = time.time()
            try:
                mc = solve(mf, mo, ncore, ncas2, nelec, nroots, mult - 1)
                chars = characters(mc, mf.mol, targets, nroots, detectable)
                ev = (np.atleast_1d(mc.e_tot) - np.atleast_1d(mc.e_tot)[0])
                ev = ev * 27.211386245988
                got = ", ".join(f"{c} {e:.2f} eV"
                                for c, e in zip(chars, ev[1:]))
                print(f"    {label:7s} CAS({nelec}e,{ncas2}o) "
                      f"+{n_added} orbital(s)  converged={mc.converged}  "
                      f"{time.time() - t0:5.1f}s  roots: {got or 'none'}")
            except Exception as exc:                        # noqa: BLE001
                print(f"    {label:7s} CAS({nelec}e,{ncas2}o) "
                      f"+{n_added}  FAILED {type(exc).__name__}: "
                      f"{str(exc)[:70]}")
        print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
