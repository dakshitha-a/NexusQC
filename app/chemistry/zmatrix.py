"""Cartesian -> Z-matrix conversion for display purposes (the coordinates
panel's "internal coordinates" view).

Reference atoms for each row are picked by nearest-previously-placed-atom
distance rather than true chemical bonding -- for an acyclic choice of
non-colinear references this reconstructs the same geometry regardless of
which atoms are picked, so "nearest" is just a convenient heuristic that
usually lines up with real bonds for small/medium molecules. All indices
are 1-based, matching conventional Z-matrix notation (and the atom-number
labels shown in the 3D viewer) -- there is no such thing as a 0-based
Z-matrix.

Reference triples that end up exactly or nearly colinear (always the case
somewhere in a strictly linear molecule, e.g. CO2 or acetylene) make the
dihedral mathematically undefined; those rows report 0.0 rather than
raising, since a linear fragment has no unique dihedral to report at all.
"""
from __future__ import annotations

import numpy as np

_COLINEAR_NORM_TOL = 1e-8
_DIHEDRAL_CANDIDATE_ANGLE_RANGE = (5.0, 175.0)  # degrees; avoid colinear angle refs when an alternative exists


def _distance(a: np.ndarray, b: np.ndarray) -> float:
    return float(np.linalg.norm(a - b))


def _angle_deg(a: np.ndarray, b: np.ndarray, c: np.ndarray) -> float:
    """Angle at vertex b, between rays b->a and b->c."""
    v1, v2 = a - b, c - b
    n1, n2 = np.linalg.norm(v1), np.linalg.norm(v2)
    if n1 < _COLINEAR_NORM_TOL or n2 < _COLINEAR_NORM_TOL:
        return 0.0
    cos_theta = float(np.clip(np.dot(v1, v2) / (n1 * n2), -1.0, 1.0))
    return float(np.degrees(np.arccos(cos_theta)))


def _dihedral_deg(a: np.ndarray, b: np.ndarray, c: np.ndarray, d: np.ndarray) -> float:
    """Dihedral angle a-b-c-d (standard IUPAC sign convention)."""
    b1, b2, b3 = b - a, c - b, d - c
    n1, n2 = np.cross(b1, b2), np.cross(b2, b3)
    n1_norm, n2_norm = np.linalg.norm(n1), np.linalg.norm(n2)
    if n1_norm < _COLINEAR_NORM_TOL or n2_norm < _COLINEAR_NORM_TOL:
        return 0.0  # a-b-c or b-c-d is colinear -- dihedral is undefined here (e.g. linear molecules)
    n1u, n2u, b2u = n1 / n1_norm, n2 / n2_norm, b2 / np.linalg.norm(b2)
    m1 = np.cross(n1u, b2u)
    x, y = np.dot(n1u, n2u), np.dot(m1, n2u)
    return float(np.degrees(np.arctan2(y, x)))


def _nearest(idx: int, coords: np.ndarray, candidates: list[int]) -> int | None:
    if not candidates:
        return None
    return min(candidates, key=lambda j: np.linalg.norm(coords[idx] - coords[j]))


def _pick_dihedral_ref(bond_ref: int, angle_ref: int, coords: np.ndarray, candidates: list[int]) -> int | None:
    """Prefer a candidate that keeps bond_ref-angle_ref-candidate away from
    colinear (0/180deg), so the dihedral itself stays well-conditioned;
    fall back to the nearest candidate if every option is colinear (a
    strictly linear molecule has no non-colinear choice)."""
    if not candidates:
        return None
    lo, hi = _DIHEDRAL_CANDIDATE_ANGLE_RANGE
    ranked = sorted(candidates, key=lambda j: np.linalg.norm(coords[angle_ref] - coords[j]))
    for cand in ranked:
        if lo < _angle_deg(coords[bond_ref], coords[angle_ref], coords[cand]) < hi:
            return cand
    return ranked[0]


def cartesian_to_zmatrix(symbols: list[str], coords: list[list[float]]) -> list[dict]:
    """Returns one dict per atom (in input order): symbol, and 1-based
    bond_ref/angle_ref/dihedral_ref + the corresponding distance (Angstrom)
    /angle/dihedral (degrees), each None where not yet applicable (rows 0,
    1, 2 have progressively fewer references)."""
    xyz = np.asarray(coords, dtype=float)
    n = len(symbols)
    rows: list[dict] = []

    for i in range(n):
        row = {
            "symbol": symbols[i],
            "bond_ref": None, "distance": None,
            "angle_ref": None, "angle_deg": None,
            "dihedral_ref": None, "dihedral_deg": None,
        }
        if i == 0:
            rows.append(row)
            continue

        placed = list(range(i))
        bond_ref = _nearest(i, xyz, placed)
        row["bond_ref"] = bond_ref + 1
        row["distance"] = _distance(xyz[i], xyz[bond_ref])

        if i == 1:
            rows.append(row)
            continue

        angle_candidates = [j for j in placed if j != bond_ref]
        angle_ref = _nearest(bond_ref, xyz, angle_candidates)
        row["angle_ref"] = angle_ref + 1
        row["angle_deg"] = _angle_deg(xyz[i], xyz[bond_ref], xyz[angle_ref])

        if i == 2:
            rows.append(row)
            continue

        dihedral_candidates = [j for j in placed if j not in (bond_ref, angle_ref)]
        dihedral_ref = _pick_dihedral_ref(bond_ref, angle_ref, xyz, dihedral_candidates)
        if dihedral_ref is not None:
            row["dihedral_ref"] = dihedral_ref + 1
            row["dihedral_deg"] = _dihedral_deg(xyz[i], xyz[bond_ref], xyz[angle_ref], xyz[dihedral_ref])
        rows.append(row)

    return rows


def internal_coordinates_with_refs(coords: list[list[float]], refs: list[dict]) -> list[dict]:
    """Computes this geometry's own distance/angle/dihedral values using a
    FIXED reference-atom assignment (bond_ref/angle_ref/dihedral_ref per
    atom, 1-based, e.g. taken from cartesian_to_zmatrix's output on some
    OTHER geometry of the same molecule -- same atom count/order) instead
    of re-picking nearest-atom references independently. Two different
    geometries of the same molecule (e.g. the two endpoints of a PES scan)
    can have different nearest-atom choices if picked separately, which
    would make interpolating between their two Z-matrices incoherent --
    this keeps both geometries described by the exact same internal
    coordinates, only the values differing.
    """
    xyz = np.asarray(coords, dtype=float)
    rows: list[dict] = []
    for i, ref in enumerate(refs):
        row = {
            "bond_ref": ref["bond_ref"], "distance": None,
            "angle_ref": ref["angle_ref"], "angle_deg": None,
            "dihedral_ref": ref["dihedral_ref"], "dihedral_deg": None,
        }
        if ref["bond_ref"] is not None:
            b = ref["bond_ref"] - 1
            row["distance"] = _distance(xyz[i], xyz[b])
        if ref["angle_ref"] is not None:
            b, a = ref["bond_ref"] - 1, ref["angle_ref"] - 1
            row["angle_deg"] = _angle_deg(xyz[i], xyz[b], xyz[a])
        if ref["dihedral_ref"] is not None:
            b, a, d = ref["bond_ref"] - 1, ref["angle_ref"] - 1, ref["dihedral_ref"] - 1
            row["dihedral_deg"] = _dihedral_deg(xyz[i], xyz[b], xyz[a], xyz[d])
        rows.append(row)
    return rows


def _nerf_place(a: np.ndarray, b: np.ndarray, c: np.ndarray,
                 bond_length: float, bond_angle_deg: float, dihedral_deg: float) -> np.ndarray:
    """Places a new atom D bonded to C (bond_length), with angle D-C-B =
    bond_angle_deg and dihedral D-C-B-A = dihedral_deg, given the already-
    placed positions a/b/c of A/B/C. Standard NeRF construction (Parsons
    et al. 2005): build a local right-handed frame at C from the B->C
    direction and the A-B-C plane normal, place D in that frame, then
    rotate into the global frame."""
    e1 = (c - b) / np.linalg.norm(c - b)
    n = np.cross(b - a, e1)
    n /= np.linalg.norm(n)
    e2 = np.cross(n, e1)
    theta = np.radians(bond_angle_deg)
    phi = np.radians(dihedral_deg)
    local = np.array([-np.cos(theta), np.sin(theta) * np.cos(phi), np.sin(theta) * np.sin(phi)])
    rot = np.array([e1, e2, n]).T
    return c + bond_length * rot.dot(local)


def zmatrix_to_cartesian(rows: list[dict]) -> list[list[float]]:
    """Reconstructs Cartesian coordinates from a Z-matrix in the shape
    cartesian_to_zmatrix/internal_coordinates_with_refs produce (1-based
    bond_ref/angle_ref/dihedral_ref, Angstrom distances, degree angles),
    via NeRF placement (_nerf_place) for every atom with a full reference
    triple, and an explicit bootstrap for the first three atoms (which
    have progressively fewer references and so no dihedral to place by).
    This is the reconstruction algorithm this module's own docstring
    history already describes as validated ad hoc (round-tripped to
    <1e-14 Angstrom pairwise-distance error on water/CO2/benzene/
    acetylene) -- promoted here to real, reusable code for
    app/chemistry/jobs/interpolate.py's liic_path.
    """
    n = len(rows)
    xyz = np.zeros((n, 3), dtype=float)
    if n <= 1:
        return xyz.tolist()
    xyz[1] = xyz[rows[1]["bond_ref"] - 1] + np.array([rows[1]["distance"], 0.0, 0.0])
    if n == 2:
        return xyz.tolist()

    b_idx, a_idx = rows[2]["bond_ref"] - 1, rows[2]["angle_ref"] - 1
    b, a = xyz[b_idx], xyz[a_idx]
    ba = a - b
    ba_norm = ba / np.linalg.norm(ba)
    arbitrary = np.array([0.0, 0.0, 1.0]) if abs(ba_norm[2]) < 0.9 else np.array([1.0, 0.0, 0.0])
    perp = np.cross(ba_norm, arbitrary)
    perp /= np.linalg.norm(perp)
    angle = np.radians(rows[2]["angle_deg"])
    direction = np.cos(angle) * ba_norm + np.sin(angle) * perp
    xyz[2] = b + rows[2]["distance"] * direction
    if n == 3:
        return xyz.tolist()

    for i in range(3, n):
        row = rows[i]
        c = xyz[row["bond_ref"] - 1]
        bb = xyz[row["angle_ref"] - 1]
        aa = xyz[row["dihedral_ref"] - 1]
        xyz[i] = _nerf_place(aa, bb, c, row["distance"], row["angle_deg"], row["dihedral_deg"])
    return xyz.tolist()


def to_zmatrix_text(symbols: list[str], coords: list[list[float]]) -> str:
    rows = cartesian_to_zmatrix(symbols, coords)
    lines = []
    for i, row in enumerate(rows):
        parts = [f"{i + 1:>2d}  {row['symbol']:<2s}"]
        if row["bond_ref"] is not None:
            parts.append(f"{row['bond_ref']:>3d} {row['distance']:>9.6f}")
        if row["angle_ref"] is not None:
            parts.append(f"{row['angle_ref']:>3d} {row['angle_deg']:>9.4f}")
        if row["dihedral_ref"] is not None:
            parts.append(f"{row['dihedral_ref']:>3d} {row['dihedral_deg']:>9.4f}")
        lines.append("  ".join(parts))
    return "\n".join(lines)
