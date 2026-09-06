#!/usr/bin/env python3
"""The recommended space does not depend on how the molecule is oriented.

Basis independence is the property the whole method is built to have, and
orientation independence is the same property in a different coordinate: a
space is a statement about the molecule, so rotating the input must not change
it. `run_bench.py --set stability` measured six of thirty molecules failing
this, all six carrying a carbonyl.

**The mechanism, because the test is shaped by it.** A terminal heteroatom's
non-bonding directions come from `perpendicular_pair`, which returns two vectors
spanning the plane perpendicular to the bond. Seeded from a fixed lab-frame
vector it returns an *arbitrary* basis of that plane, different for every
orientation. `perceive` drops whichever of those is parallel to the atom's pi
normal, because an sp2 heteroatom's out-of-plane lone pair IS its pi orbital and
emitting both double-counts one direction. An arbitrary basis is generally
parallel to nothing, so that test fired only by luck: on the orientations where
it missed, the pi direction entered the pool a second time as a lone pair and
formaldehyde came out at (8e,5o) instead of its reference (6e,4o).

So this asserts three things, and the first two are what make the third hold:

- the perceived directions are **covariant** -- rotate the molecule, rotate the
  axes back, and get the same directions;
- a carbonyl oxygen emits exactly two lone-pair targets, the in-plane one and
  the axial one, never the out-of-plane one that duplicates pi;
- the recommended space is identical across orientations.

N2 is here as the case that cannot be fixed and must not be broken. A
homonuclear diatomic has no molecular direction perpendicular to its axis, so
its pair keeps the arbitrary seed; the perpendicular plane is exactly
degenerate there, which is why the space does not move anyway.

    PYTHONPATH=$PWD python3 tests/backend/cas_20_rotation_invariance.py
"""
from __future__ import annotations

import sys

import numpy as np

FAILURES = []
SEED = 20260906
N_ROT = 3


def check(label, ok, detail=""):
    print(f"  [{'PASS' if ok else 'FAIL'}] {label}"
          + (f" -- {detail}" if detail else ""))
    if not ok:
        FAILURES.append(label)


def geometry(name):
    from scripts.casbench import reference_data as ref
    syms, co, chg, mult = ref.molecule(name)
    return syms, np.asarray(co, float), chg, mult


def random_rotation(rng):
    """A uniformly distributed rotation, via the QR of a Gaussian matrix."""
    q, r = np.linalg.qr(rng.normal(size=(3, 3)))
    q = q * np.sign(np.diag(r))
    if np.linalg.det(q) < 0:
        q[:, 0] = -q[:, 0]
    return q


def axes_in_molecular_frame(syms, co, R):
    """Perceived pi and lone-pair directions, rotated back to the input frame.

    Directions are compared up to sign, since a target axis and its negation
    describe the same orbital.
    """
    from app.chemistry.cas.geometry import perceive
    per = perceive(syms, co @ R.T)
    out = []
    for t in per.targets:
        if t.kind not in ("pi", "lone_pair") or t.axis is None:
            continue
        v = np.asarray(t.axis, float) @ R
        if v[np.argmax(np.abs(v))] < 0:      # fix the sign for comparison
            v = -v
        out.append((t.atom_index, t.kind, tuple(np.round(v, 6))))
    return sorted(out)


def recommend_at(name, R, basis="def2-svp"):
    from pyscf import gto, scf

    from app.chemistry.cas.recommend import recommend
    syms, co, chg, mult = geometry(name)
    co = co @ R.T
    atom = "\n".join(f"{s} {c[0]:.8f} {c[1]:.8f} {c[2]:.8f}"
                     for s, c in zip(syms, co))
    mol = gto.M(atom=atom, basis=basis, charge=chg, spin=mult - 1, verbose=0)
    mf = (scf.RHF(mol) if mult == 1 else scf.ROHF(mol)).density_fit()
    mf.kernel()
    rec = recommend(mf, syms, co, spin_2s=mult - 1)
    tier = rec.tiers[rec.recommended]
    return (tier.n_electrons, tier.n_orbitals)


def main():
    from app.chemistry.cas.geometry import perceive

    print("Perceived directions are covariant under rotation")
    for name in ("formaldehyde", "acetone", "formamide", "acrolein",
                 "uracil", "N2"):
        syms, co, _c, _m = geometry(name)
        rng = np.random.default_rng(SEED)
        sets = [axes_in_molecular_frame(syms, co, random_rotation(rng))
                for _ in range(N_ROT)]
        if name == "N2":
            # No molecular direction to seed from, so per-vector covariance is
            # not available and only the count can be asserted.
            check(f"{name}: same number of targets over {N_ROT} rotations",
                  len({len(s) for s in sets}) == 1,
                  f"counts {[len(s) for s in sets]}")
            continue
        ok = all(s == sets[0] for s in sets[1:])
        differing = "" if ok else f"{len(set(map(str, sets)))} distinct sets"
        check(f"{name}: identical directions over {N_ROT} rotations", ok,
              differing)

    print("\nA carbonyl oxygen emits the in-plane and axial lone pairs, not "
          "the out-of-plane one")
    for name, oxygen in (("formaldehyde", 1), ("acetone", 1),
                         ("acrolein", 3), ("formamide", 2)):
        syms, co, _c, _m = geometry(name)
        assert syms[oxygen] == "O", f"{name} atom {oxygen} is {syms[oxygen]}"
        per = perceive(syms, co)
        lps = [t for t in per.targets
               if t.kind == "lone_pair" and t.atom_index == oxygen]
        pis = [t for t in per.targets
               if t.kind == "pi" and t.atom_index == oxygen]
        check(f"{name}: two lone-pair targets on the carbonyl oxygen",
              len(lps) == 2, f"got {len(lps)}: {[t.note for t in lps]}")
        if pis and len(lps) == 2:
            n = np.asarray(pis[0].axis, float)
            worst = max(abs(float(np.dot(np.asarray(t.axis, float), n)))
                        for t in lps)
            check(f"{name}: neither duplicates the pi direction", worst < 0.1,
                  f"largest |cos| with the pi normal is {worst:.4f}")

    print("\nN2 keeps its degenerate pi pair")
    syms, co, _c, _m = geometry("N2")
    per = perceive(syms, co)
    pis = [t for t in per.targets if t.kind == "pi"]
    check("N2 emits four pi targets, a degenerate pair on each atom",
          len(pis) == 4, f"got {len(pis)}")

    print("\nThe recommended space is the same in every orientation")
    for name, expected in (("formaldehyde", (6, 4)), ("acetone", (6, 4))):
        rng = np.random.default_rng(SEED)
        spaces = [recommend_at(name, random_rotation(rng))
                  for _ in range(N_ROT)]
        check(f"{name}: one space over {N_ROT} rotations",
              len(set(spaces)) == 1, f"got {sorted(set(spaces))}")
        check(f"{name}: and it is the literature {expected}",
              spaces[0] == expected, f"got {spaces[0]}")

    print(f"\n{len(FAILURES)} failure(s)"
          + (": " + "; ".join(FAILURES) if FAILURES else ""))
    return 1 if FAILURES else 0


if __name__ == "__main__":
    sys.exit(main())
