#!/usr/bin/env python3
"""Does the engine survive a transition metal, and what does it choose?

`geometry.perceive` emits a `metal_d` target for all twenty-nine transition
metals and `projector.build_target_matrix` handles the axis-free case by giving
the shell one column per component, so the machinery exists. Nothing in the
benchmark has ever exercised it, which is the open item this probes.

The scope is the recommendation, deliberately. Narrowing sorts a pool into pi
and lone-pair and drops a d orbital into neither, and the refinement's character
audit is built from pi and lone-pair targets alone, so those stages are blind to
d character by construction. Measuring them would be measuring a gap that is
already known. What is worth knowing is whether perception, projection and
ranking produce a defensible space on a metal at all.

Three systems, chosen for what each one tests rather than for coverage:

  * **Cr2**, the standard hard case. Both atoms contribute a full 3d and 4s, so
    the conventional space is the twelve electrons in twelve orbitals of the
    formal sextuple bond, and it tests two metal centres and no ligands.
  * **[Fe(H2O)6]2+** high spin, an octahedral d6 ion. Tests a metal against
    ligands: the perception has to find six water lone pairs and a d shell, and
    get the charge and the multiplicity through the selection.
  * **TiO**, a metal against a single strongly bound ligand, where the d shell
    and the oxygen 2p manifold overlap.

    python3 scripts/casbench/metal_probe.py
"""
from __future__ import annotations

import argparse
import os
import sys
import time

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(
    os.path.dirname(__file__)))))

# Geometries are constructed rather than optimised, in the same spirit as the
# benchmark's diradicals: for an octahedral ion the symmetry is the chemistry,
# and an idealised bond length is a cleaner test of perception than a
# particular optimisation's answer would be.
CR2_R = 1.68           # Angstrom, the short multiple bond commonly studied
FE_O = 2.10            # high-spin Fe(II)-O, octahedral
TI_O = 1.62
O_H = 0.96
HOH = 104.5


def _water_ligand(direction, distance):
    """One water oxygen at `distance` along `direction`, hydrogens splayed off
    the metal-oxygen axis so the molecule is a real water and not a bare O."""
    d = np.asarray(direction, float)
    d /= np.linalg.norm(d)
    o = d * distance
    # Any two directions perpendicular to the bond will do; the lone pairs the
    # projector finds do not depend on the rotation about it.
    tmp = np.array([1.0, 0.0, 0.0])
    if abs(np.dot(tmp, d)) > 0.9:
        tmp = np.array([0.0, 1.0, 0.0])
    perp = np.cross(d, tmp)
    perp /= np.linalg.norm(perp)
    half = np.radians(HOH / 2.0)
    atoms = [("O", o)]
    for sign in (+1.0, -1.0):
        h = d * np.cos(half) + perp * (sign * np.sin(half))
        atoms.append(("H", o + h * O_H))
    return atoms


def systems():
    out = {}

    out["Cr2"] = (["Cr", "Cr"],
                  np.array([[0.0, 0.0, -CR2_R / 2], [0.0, 0.0, CR2_R / 2]]),
                  0, 1, "(12e,12o): the 3d and 4s shells on both atoms")

    out["TiO"] = (["Ti", "O"],
                  np.array([[0.0, 0.0, 0.0], [0.0, 0.0, TI_O]]),
                  0, 3, "the Ti 3d/4s shell against the O 2p manifold")

    syms, coords = ["Fe"], [np.zeros(3)]
    for direction in ([1, 0, 0], [-1, 0, 0], [0, 1, 0],
                      [0, -1, 0], [0, 0, 1], [0, 0, -1]):
        for sym, pos in _water_ligand(direction, FE_O):
            syms.append(sym)
            coords.append(pos)
    out["Fe(H2O)6_2+"] = (syms, np.asarray(coords), 2, 5,
                          "(6e,5o): the d shell of a high-spin d6 ion")
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--basis", default="def2-svp")
    ap.add_argument("--only", nargs="*")
    args = ap.parse_args()

    from pyscf import gto, scf

    from app.chemistry.cas.geometry import perceive
    from app.chemistry.cas.recommend import recommend

    print(f"# Transition metals through the recommendation, {args.basis}\n")

    for name, (syms, coords, charge, mult, expect) in systems().items():
        if args.only and name not in args.only:
            continue
        print(f"=== {name} (charge {charge:+d}, multiplicity {mult}) ===")
        print(f"    conventional: {expect}")
        per = perceive(syms, coords, include_sigma=False)
        kinds = {}
        for t in per.targets:
            kinds[t.kind] = kinds.get(t.kind, 0) + 1
        print(f"    perceived targets: {kinds}")

        atom = "\n".join(f"{s} {c[0]:.8f} {c[1]:.8f} {c[2]:.8f}"
                         for s, c in zip(syms, coords))
        t0 = time.time()
        try:
            mol = gto.M(atom=atom, basis=args.basis, charge=charge,
                        spin=mult - 1, verbose=0)
            mf = (scf.RHF(mol) if mol.spin == 0 else scf.ROHF(mol)).density_fit()
            mf.kernel()
            if not mf.converged:
                print("    SCF did not converge\n")
                continue
            rec = recommend(mf, syms, coords, spin_2s=mult - 1)
        except Exception as exc:                            # noqa: BLE001
            print(f"    FAILED {type(exc).__name__}: {exc}\n")
            continue
        dt = time.time() - t0
        tiers = {k: (t.n_electrons, t.n_orbitals)
                 for k, t in sorted(rec.tiers.items())}
        print(f"    recommended {rec.space}  tiers {tiers}  in {dt:.1f}s")
        for note in rec.notes or []:
            print(f"    note: {note[:110]}")
        print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
