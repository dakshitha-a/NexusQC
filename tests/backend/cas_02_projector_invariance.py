#!/usr/bin/env python3
"""The recommended space does not depend on the basis set or on the orientation.

These are the two properties the rebuilt engine exists to have, and both are
things the legacy AVAS/autocas path does not have.

**Orientation.** Stock ``pyscf.mcscf.avas`` selects its reference orbitals by
laboratory-frame AO label (``'C 2px'``). Rotate the molecule and the label
names a different physical orbital, so the space changes. This script measures
that directly: pyrrole's correct pi space CAS(6,5) becomes CAS(10,7) under an
arbitrary rotation of the same molecule. That contrast is the reason the
oriented projector exists, so it is asserted here rather than merely described
-- if a future pyscf makes AVAS rotation invariant, this assertion fires and
the docstring gets rewritten instead of quietly becoming false.

**Basis.** The oriented targets live in a fixed minimal reference basis, so the
question they ask of the wavefunction does not change when the calculation
basis does. Checked from STO-3G to aug-cc-pVDZ, a factor of five in basis size
and the addition of diffuse functions.

Both are checked on the pi-only target set, because that is where a textbook
answer exists to compare against: benzene (6,6) and butadiene (4,4) are the
canonical pi spaces, and getting them exactly is what says the projector is
selecting the right orbitals and not merely a reproducible number of them.

Needs pyscf but no live stack. Nine small RHF calculations per molecule.

Run:  PYTHONPATH=$PWD python3 tests/backend/cas_02_projector_invariance.py
"""
import math

import numpy as np
from pyscf import gto, scf
from pyscf.mcscf import avas

from app.chemistry.cas.geometry import perceive
from app.chemistry.cas.projector import project

PASS = 0
FAIL = 0

BASES = ["sto-3g", "def2-svp", "cc-pvdz", "def2-tzvp", "aug-cc-pvdz"]


def check(label: str, ok: bool, detail: str = "") -> None:
    global PASS, FAIL
    if ok:
        PASS += 1
        print(f"  [PASS] {label}")
    else:
        FAIL += 1
        print(f"  [FAIL] {label}" + (f"\n         {detail}" if detail else ""))


def _benzene():
    s, c = [], []
    for i in range(6):
        a = math.radians(60 * i)
        s.append("C"); c.append([1.397 * math.cos(a), 1.397 * math.sin(a), 0.0])
        s.append("H"); c.append([2.480 * math.cos(a), 2.480 * math.sin(a), 0.0])
    return s, np.asarray(c, float)


PYRROLE = (["N", "C", "C", "C", "C", "H", "H", "H", "H", "H"],
           np.asarray([[0, 0, 1.140], [0, 1.121, 0.339], [0, -1.121, 0.339],
                       [0, 0.713, -0.966], [0, -0.713, -0.966], [0, 0, 2.149],
                       [0, 2.125, 0.737], [0, -2.125, 0.737], [0, 1.356, -1.833],
                       [0, -1.356, -1.833]], float))
BUTADIENE = (["C", "C", "C", "C", "H", "H", "H", "H", "H", "H"],
             np.asarray([[-1.830, -0.360, 0], [-0.610, 0.180, 0], [0.610, -0.180, 0],
                         [1.830, 0.360, 0], [-2.710, 0.270, 0], [-2.000, -1.430, 0],
                         [-0.440, 1.250, 0], [0.440, -1.250, 0], [2.000, 1.430, 0],
                         [2.710, -0.270, 0]], float))
BENZENE = _benzene()
# Textbook valence pi spaces.
#
# Pyrrole was recorded here as (8e,6o) until 2026-09-04, and that was never the
# textbook answer. Pyrrole's pi space is the five ring pi orbitals holding six
# pi electrons, which is what `reference_data.REFERENCE_SPACES` carries and
# what Thiel's benchmark uses. The sixth orbital and the extra two electrons
# were a lone-pair target emitted on the ring nitrogen, which is planar and
# three-coordinate and therefore has no in-plane lone pair to find: its
# non-bonding density is the p orbital perpendicular to the ring, already
# counted among the five. See `geometry.lone_pair_axes`.
#
# So this line was the engine's own output written down as if it were the
# reference, which makes the assertion agree with whatever the engine does and
# tests nothing. Both other entries were checked against the literature at the
# same time and are right: benzene's six pi and butadiene's four.
EXPECTED = {"benzene": (6, 6), "butadiene": (4, 4), "pyrrole": (6, 5)}


def _rot(rng):
    A = rng.standard_normal((3, 3))
    Q, R = np.linalg.qr(A)
    Q *= np.sign(np.diag(R))
    if np.linalg.det(Q) < 0:
        Q[:, 0] *= -1
    return Q


def _geom(syms, co):
    return "\n".join(f"{s} {c[0]:.8f} {c[1]:.8f} {c[2]:.8f}" for s, c in zip(syms, co))


def _space(syms, co, basis):
    mol = gto.M(atom=_geom(syms, co), basis=basis, verbose=0)
    mf = scf.RHF(mol).density_fit().run()
    per = perceive(syms, co, include_sigma=False)
    ps = project(mf, per.targets)
    return sum(ps.nelecas), ps.ncas


def main() -> int:
    rng = np.random.default_rng(20260902)
    mols = {"benzene": BENZENE, "butadiene": BUTADIENE, "pyrrole": PYRROLE}

    print("The pi space matches the textbook answer, in every basis")
    for name, (syms, co) in mols.items():
        spaces = {b: _space(syms, co, b) for b in BASES}
        uniq = set(spaces.values())
        check(f"{name}: identical across {len(BASES)} basis sets "
              f"(STO-3G to aug-cc-pVDZ)",
              len(uniq) == 1,
              "  ".join(f"{b}:{s}" for b, s in spaces.items()))
        got = spaces["def2-svp"]
        check(f"{name}: CAS{got} matches the expected valence pi space "
              f"CAS{EXPECTED[name]}",
              got == EXPECTED[name], f"got {got}, expected {EXPECTED[name]}")

    print("\nThe space is unchanged by an arbitrary rotation of the molecule")
    for name, (syms, co) in mols.items():
        ref = _space(syms, co, "def2-svp")
        got = {_space(syms, co @ _rot(rng).T, "def2-svp") for _ in range(5)}
        check(f"{name}: 5 random rotations all give CAS{ref}",
              got == {ref}, f"got {sorted(got)}, expected {{{ref}}}")

    print("\nThe contrast: stock AVAS with axis-aligned labels is NOT rotation "
          "invariant, which is why the oriented projector exists")
    syms, co = PYRROLE

    def _avas_space(coords):
        mol = gto.M(atom=_geom(syms, coords), basis="def2-svp", verbose=0)
        mf = scf.RHF(mol).density_fit().run()
        # The pyrrole reference geometry lies in the x=0 plane, so 2px is its
        # pi direction -- the label a careful user would pick by hand.
        ncas, nelecas, _mo = avas.avas(mf, ["C 2px", "N 2px"],
                                       canonicalize=False, verbose=0)
        return nelecas, ncas

    aligned = _avas_space(co)
    check(f"stock AVAS in the aligned frame finds the right pi space "
          f"CAS{aligned}",
          aligned == (6, 5), f"got {aligned}")

    rotated = {_avas_space(co @ _rot(rng).T) for _ in range(3)}
    check("stock AVAS gives a DIFFERENT space once the molecule is rotated -- "
          "if this passes, the oriented projector is still necessary",
          rotated != {aligned},
          f"rotated results {sorted(rotated)} unexpectedly match the aligned "
          f"{aligned}; pyscf may have gained orientation handling, in which "
          f"case revisit projector.py's rationale")

    ours = _space(syms, co, "def2-svp")
    check(f"the oriented projector is stable over the same rotations "
          f"(CAS{ours} throughout) where AVAS moved to {sorted(rotated)}",
          {_space(syms, co @ _rot(rng).T, "def2-svp") for _ in range(3)} == {ours})

    print(f"\n{PASS} passed, {FAIL} failed")
    return 1 if FAIL else 0


if __name__ == "__main__":
    raise SystemExit(main())
