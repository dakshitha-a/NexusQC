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
