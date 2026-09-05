#!/usr/bin/env python3
"""What the engine sees when a requested state is Rydberg, and in which basis.

The engine currently declines to build a space around a Rydberg state:
`excited.augment` skips a Rydberg particle by construction, on the reasoning
that a valence space is not meant to grow one. The question this script exists
to answer is whether that refusal is a limitation worth keeping or one worth
lifting, and the worked case is methylamine, whose S1 carries Rydberg character
and which is reported to behave well at SA(2)-CASSCF/aug-cc-pVDZ in CAS(8e,9o).

Two things have to be separated before anything is built, because they call for
completely different responses:

  * **The method cannot describe the state.** Then serving it is a real feature
    with real design consequences, and refusing is defensible.
  * **The basis cannot describe the state.** The product analyses in def2-SVPD
    when states are requested, while the reference case is aug-cc-pVDZ. If the
    state is reachable in one and not the other, the answer is the choice of
    analysis basis, and nothing about Rydberg support needs to change.

So every molecule is run in both bases and the two are printed side by side.
`rydberg_representable` is reported alongside, since that gate is what decides
whether a root is allowed to be labelled Rydberg at all: a basis the gate calls
blind will report no Rydberg state even when the root is plainly one.

    python3 scripts/casbench/rydberg_probe.py
    python3 scripts/casbench/rydberg_probe.py --molecules methylamine ammonia
"""
from __future__ import annotations

import argparse
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(
    os.path.dirname(__file__)))))

from scripts.casbench import reference_data as ref          # noqa: E402
from scripts.casbench.run_bench import _mf                  # noqa: E402

# Molecules whose low-lying states are, or are reported to be, Rydberg. The
# first is the user's worked case; formaldehyde already carries an n->Rydberg
# 3s reference in EXCITATIONS, and pyrrole and furan both have a Rydberg
# reference below their valence pi->pi*.
DEFAULT = ["methylamine", "ammonia", "water", "formaldehyde", "ethylene",
           "pyrrole", "furan"]

BASES = ["aug-cc-pvdz", "def2-svpd"]


def probe(name, basis, n_states):
    from pyscf import tdscf

    from app.chemistry.cas.diffuse import rydberg_representable
    from app.chemistry.cas.excited import analyse
    from app.chemistry.cas.geometry import perceive
    from app.chemistry.cas.recommend import recommend

    syms, co, chg, mult = ref.molecule(name)
    co = np.asarray(co, float)
    mol, mf = _mf(syms, co, basis, chg, mult, dft_xc="camb3lyp")
    detectable = bool(rydberg_representable(mf))

    td = tdscf.TDA(mf)
    td.nstates = max(2 * n_states, 6)
    td.kernel()
    per = perceive(syms, co, include_sigma=False)
    an = analyse(mf, td, per.targets, n_states=n_states,
                 rydberg_detectable=detectable)

    # The recommendation needs a Hartree-Fock reference, not the Kohn-Sham one
    # the linear response was run on, so it is built separately.
    _mol2, mfhf = _mf(syms, co, basis, chg, mult)
    rec = recommend(mfhf, syms, co, spin_2s=mult - 1)
    tier = rec.tiers[rec.recommended]

    return {
        "detectable": detectable,
        "states": an.states[:n_states],
        "space": f"({tier.n_electrons}e,{tier.n_orbitals}o)",
        "analysis": an,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--molecules", nargs="*", default=DEFAULT)
    ap.add_argument("--states", type=int, default=2)
    args = ap.parse_args()

    print(f"# Rydberg character by basis, {args.states} states requested\n")

    for name in args.molecules:
        if name not in ref.GEOMETRIES:
            print(f"{name}: not in GEOMETRIES\n")
            continue
        print(f"=== {name} ===")
        for basis in BASES:
            try:
                got = probe(name, basis, args.states)
            except Exception as exc:                        # noqa: BLE001
                print(f"  {basis:14s} FAILED {type(exc).__name__}: {exc}")
                continue
            ryd = sum(1 for s in got["states"]
                      if s.particle_kind == "Rydberg")
            print(f"  {basis:14s} diffuse-gate={str(got['detectable']):5s} "
                  f"ground-state pool {got['space']}  "
                  f"{ryd} of {len(got['states'])} requested states Rydberg")
            for s in got["states"]:
                print(f"      S{s.index}  {s.energy_ev:6.2f} eV  "
                      f"{(s.character or '?'):18s} "
                      f"hole={s.hole_kind or '?':10s} "
                      f"particle={s.particle_kind or '?':10s}")
        print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
