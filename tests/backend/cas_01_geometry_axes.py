#!/usr/bin/env python3
"""The projection axes are derived from the geometry, so they rotate with it.

This is the property the whole engine rests on. Stock AVAS names its reference
orbitals in the laboratory frame (``'C 2px'``), so the space it picks depends
on how the molecule happened to be oriented in its input file --
``cas_02_projector_invariance.py`` measures that failure directly. Deriving the
axes from the neighbour geometry is what removes the dependence.

Two things are asserted, and the difference between them matters:

- Axes built from a *cross product* or a *best-fit plane* are individually
  covariant: rotate the molecule and each axis rotates with it exactly.
- Axes built by ``perpendicular_pair`` are **not** individually covariant, and
  cannot be. For an axially symmetric centre such as N2 there is no molecular
  direction perpendicular to the bond to seed from, so no deterministic choice
  can rotate correctly. What is invariant is the *span* of the pair, and the
  span is all the projector consumes. Asserting per-vector equality there would
  be asserting something false; this script asserts span equality instead, via
  the projector onto the column space.

Also covers the chemistry that a naive one-neighbour rule gets wrong: a
carbonyl oxygen's lone pairs are perpendicular to the bond, while dinitrogen's
lie *along* it. Both must appear or N2 loses its lone pairs and formaldehyde
loses the hole orbital of its dark n->pi* state.

Needs numpy only -- no pyscf, no live stack, milliseconds.

Run:  PYTHONPATH=$PWD python3 tests/backend/cas_01_geometry_axes.py
"""
import math

import numpy as np

from app.chemistry.cas.geometry import (
    local_pi_normal,
    perceive,
    perceive_bonds,
    perpendicular_pair,
)

PASS = 0
FAIL = 0


def check(label: str, ok: bool, detail: str = "") -> None:
    global PASS, FAIL
    if ok:
        PASS += 1
        print(f"  [PASS] {label}")
    else:
        FAIL += 1
        print(f"  [FAIL] {label}" + (f"\n         {detail}" if detail else ""))


WATER = (["O", "H", "H"], [[0, 0, 0.117], [0, 0.757, -0.469], [0, -0.757, -0.469]])
CH2O = (["C", "O", "H", "H"],
        [[0, 0, -0.5295], [0, 0, 0.6755], [0, 0.94, -1.10], [0, -0.94, -1.10]])
N2 = (["N", "N"], [[0, 0, 0], [0, 0, 1.1]])
ETHANE = (["C", "C", "H", "H", "H", "H", "H", "H"],
          [[0, 0, 0.7655], [0, 0, -0.7655],
           [0, 1.0192, 1.1573], [0.8825, -0.5096, 1.1573], [-0.8825, -0.5096, 1.1573],
           [0, -1.0192, -1.1573], [0.8825, 0.5096, -1.1573], [-0.8825, 0.5096, -1.1573]])


def _benzene():
    s, c = [], []
    for i in range(6):
        a = math.radians(60 * i)
        s.append("C"); c.append([1.397 * math.cos(a), 1.397 * math.sin(a), 0.0])
        s.append("H"); c.append([2.480 * math.cos(a), 2.480 * math.sin(a), 0.0])
    return s, c


BENZENE = _benzene()


def _rot(rng):
    A = rng.standard_normal((3, 3))
    Q, R = np.linalg.qr(A)
    Q *= np.sign(np.diag(R))
    if np.linalg.det(Q) < 0:
        Q[:, 0] *= -1
    return Q


def _span_projector(per, natm):
    """Projector onto the column space of the per-atom target axes."""
    cols = []
    for t in per.targets:
        if t.axis is None:
            continue
        col = np.zeros(natm * 3)
        col[t.atom_index * 3:(t.atom_index + 1) * 3] = t.axis
        cols.append(col)
    M = np.asarray(cols).T
    return M @ np.linalg.pinv(M)


def main() -> int:
    print("Bond perception")
    nb = perceive_bonds(*BENZENE)
    ring = [i for i, s in enumerate(BENZENE[0]) if s == "C"]
    check("benzene: every carbon has three neighbours (two C, one H)",
          all(len(nb[i]) == 3 for i in ring),
          f"neighbour counts {[len(nb[i]) for i in ring]}")
    check("water: oxygen is bonded to both hydrogens",
          len(perceive_bonds(*WATER)[0]) == 2)

    print("\nLocal pi normals")
    bs, bc = BENZENE
    bc = np.asarray(bc, float)
    nbb = perceive_bonds(bs, bc)
    normals = [local_pi_normal(i, bc, nbb) for i in ring]
    check("benzene: all six ring normals are mutually parallel",
          all(abs(abs(float(np.dot(normals[0], n))) - 1.0) < 1e-8 for n in normals))
    check("benzene: the ring normal is perpendicular to the molecular plane",
          abs(abs(float(normals[0][2])) - 1.0) < 1e-8,
          f"normal {np.round(normals[0], 6)}")

    es, ec = ETHANE
    ec = np.asarray(ec, float)
    nbe = perceive_bonds(es, ec)
    # An sp3 carbon's four neighbours have no plane; the best-fit normal is
    # meaningless there, but it must not be a *pi* target -- checked below via
    # perceive(), which is what decides.
    check("ethane: an sp3 carbon has four neighbours, so no pi system",
          len(nbe[0]) == 4)
    per_eth = perceive(es, ec, include_sigma=False)
    check("ethane: perceive() emits no pi target for a saturated molecule",
          len(per_eth.targets_of("pi")) == 0,
          f"got {[t.note for t in per_eth.targets_of('pi')]}")

    print("\nLone-pair chemistry")
    per_ch2o = perceive(*CH2O, include_sigma=False)
    o_lps = [np.asarray(t.axis) for t in per_ch2o.targets_of("lone_pair")
             if t.atom_index == 1]
    co_axis = np.asarray(CH2O[1][1], float) - np.asarray(CH2O[1][0], float)
    co_axis /= np.linalg.norm(co_axis)
    check("formaldehyde: the carbonyl oxygen carries a lone pair perpendicular "
          "to C=O (the n orbital of the dark n->pi* state)",
          any(abs(float(np.dot(v, co_axis))) < 0.2 for v in o_lps),
          f"cosines to the C=O axis {[round(float(np.dot(v, co_axis)), 3) for v in o_lps]}")

    per_n2 = perceive(*N2, include_sigma=False)
    n2_lps = [np.asarray(t.axis) for t in per_n2.targets_of("lone_pair")]
    axial = [v for v in n2_lps if abs(abs(float(v[2])) - 1.0) < 1e-6]
    check("N2: each nitrogen carries an axial lone pair pointing outward -- the "
          "case a carbonyl-shaped rule gets wrong",
          len(axial) == 2, f"axial lone pairs found: {len(axial)}")
    check("N2: the linear centres still get a degenerate pi pair each",
          len(per_n2.targets_of("pi")) == 4,
          f"pi targets {len(per_n2.targets_of('pi'))}")

    print("\nSigma targets exist, and both ends of every bond are covered")
    per_w = perceive(*WATER)
    sig = per_w.targets_of("sigma")
    check("water: two O-H bonds give four sigma targets, one per bond end",
          len(sig) == 4, f"got {len(sig)}")
    check("water: every sigma target names its partner atom",
          all(t.partner_index is not None for t in sig))

    print("\nRotation covariance")
    rng = np.random.default_rng(20260902)
    # Cross-product and best-fit normals are individually covariant.
    worst_pi = 0.0
    for _ in range(20):
        R = _rot(rng)
        n0 = local_pi_normal(0, bc, nbb)
        n1 = local_pi_normal(0, bc @ R.T, perceive_bonds(bs, bc @ R.T))
        worst_pi = max(worst_pi, abs(abs(float(np.dot(R @ n0, n1))) - 1.0))
    check("a pi normal rotates exactly with the molecule (20 random rotations)",
          worst_pi < 1e-9, f"worst deviation {worst_pi:.2e}")

    # The full target set is covariant only as a span, and that is enough.
    for name, (syms, co) in (("water", WATER), ("formaldehyde", CH2O), ("N2", N2)):
        co = np.asarray(co, float)
        natm = len(syms)
        P0 = _span_projector(perceive(syms, co), natm)
        worst = 0.0
        for _ in range(20):
            R = _rot(rng)
            P1 = _span_projector(perceive(syms, co @ R.T), natm)
            Rb = np.kron(np.eye(natm), R)
            worst = max(worst, float(np.abs(Rb @ P0 @ Rb.T - P1).max()))
        check(f"{name}: the span of the target set is rotation invariant "
              f"(20 random rotations)", worst < 1e-8, f"worst deviation {worst:.2e}")

    # And the documented non-property, asserted so nobody "fixes" it later.
    a0, b0 = perpendicular_pair(np.array([0.0, 0.0, 1.0]))
    R = _rot(rng)
    a1, b1 = perpendicular_pair(R @ np.array([0.0, 0.0, 1.0]))
    rotated = np.abs(np.array([np.dot(R @ a0, a1), np.dot(R @ b0, b1)]))
    check("perpendicular_pair is deliberately NOT per-vector covariant -- only "
          "its span is, which is what the projector uses",
          not np.allclose(rotated, 1.0, atol=1e-6),
          f"cosines {np.round(rotated, 4)} -- if these are 1.0 the docstring is "
          f"stale, not the code")

    print(f"\n{PASS} passed, {FAIL} failed")
    return 1 if FAIL else 0


if __name__ == "__main__":
    raise SystemExit(main())
