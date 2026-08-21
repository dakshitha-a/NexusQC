"""Geometry-path generation between two endpoint molecule dicts, for the
two-endpoint mode of the `pes_scan` job type (app/chemistry/jobs/base.py's
JobManager.submit_scan runs one sub-job per returned image).

Three interpolation methods, in increasing physical quality (and roughly
increasing cost):
  - "linear": naive Cartesian linear interpolation. Cheap, but can produce
    unphysical intermediate geometries (e.g. atoms passing through each
    other) whenever the two endpoints differ by more than a small
    displacement.
  - "liic": genuine Linear Interpolation in Internal Coordinates -- bond
    lengths/angles/dihedrals interpolated linearly instead of Cartesian
    coordinates, reconstructed via app/chemistry/zmatrix.py's NeRF-based
    zmatrix_to_cartesian. Better-behaved than plain Cartesian interpolation
    for a rigid substructure that mostly rotates/translates between
    endpoints, but only as good as the single fixed reference-atom
    assignment picked from `start` -- a poor choice there (e.g. a very
    different local environment near one atom) can still produce a
    distorted intermediate path.
  - "idpp" (default): Image Dependent Pair Potential (Smidstrup et al.
    2014), via ASE's NEB.interpolate(method='idpp') -- iteratively adjusts
    every image to minimize a pairwise-distance penalty across the whole
    path, which empirically avoids both plain Cartesian interpolation's
    atom-clash problem and LIIC's single-fixed-reference-frame limitation.
    This is what the user's own reference script does, and is offered here
    as the default for the same reason: it is generally the best-behaved
    of the three without needing any chemistry-specific tuning.

All three are pure functions of the two endpoint molecule dicts and are
safe to recompute on submit_draft's interrupt-resume re-execution (no
network calls, no randomness).
"""
from __future__ import annotations

import numpy as np

from app.chemistry.zmatrix import cartesian_to_zmatrix, internal_coordinates_with_refs, zmatrix_to_cartesian

INTERPOLATION_METHODS = ("idpp", "liic", "linear")


_REORDER_TIE_TOLERANCE_ANGSTROM = 1e-6


def _best_atom_correspondence(start: dict, end: dict) -> list[int]:
    """The minimum-total-distance one-to-one correspondence between
    `end`'s atoms and `start`'s, PER ELEMENT (never across elements -- a
    carbon can never stand in for a hydrogen), via
    `scipy.optimize.linear_sum_assignment` (the Hungarian algorithm) --
    not a greedy nearest-available pick, which can lock in an early wrong
    pair and cascade.

    `end` is only translated (its centroid shifted onto `start`'s), never
    rotated, before matching -- rotating first would need a correspondence
    to compute, which is exactly what this is trying to find, and
    endpoints for the same molecule (two tagged frames, an uploaded
    reactant/product pair) are rarely wildly misoriented relative to each
    other in practice.

    Returns a permutation `p` such that `end`'s atom `p[i]` corresponds to
    `start`'s atom `i` -- computed from GEOMETRY alone, never from the
    `symbols` list's literal order, because two same-element atoms already
    read identically in that list regardless of which physical atom is
    which (e.g. water's two hydrogens): a molecule can have its atoms
    genuinely swapped between two endpoints while `end["symbols"] ==
    start["symbols"]` stays trivially true, which a string comparison
    alone can never catch."""
    from scipy.optimize import linear_sum_assignment

    start_c = np.asarray(start["coords"], dtype=float)
    end_c = np.asarray(end["coords"], dtype=float)
    end_c_shifted = end_c - end_c.mean(axis=0) + start_c.mean(axis=0)
    start_symbols = list(start["symbols"])
    end_symbols = list(end["symbols"])

    permutation = [-1] * len(start_symbols)
    for element in set(start_symbols):
        start_idx = [i for i, s in enumerate(start_symbols) if s == element]
        end_idx = [i for i, s in enumerate(end_symbols) if s == element]
        cost = np.linalg.norm(
            start_c[start_idx][:, None, :] - end_c_shifted[end_idx][None, :, :], axis=2,
        )
        row_ind, col_ind = linear_sum_assignment(cost)
        for r, c in zip(row_ind, col_ind):
            permutation[start_idx[r]] = end_idx[c]
    return permutation


def _reconcile_endpoints(start: dict, end: dict) -> tuple[dict, list[str]]:
    """(possibly reordered `end`, warnings). Raises ValueError only when
    `start`/`end` cannot possibly be the same molecule (different element
    counts).

    The minimum-cost correspondence (`_best_atom_correspondence`) is
    always computed, never gated on whether `end["symbols"]` merely LOOKS
    reordered as a string list -- a molecule with repeated elements (any
    molecule with 2+ atoms of the same element) can have its atoms
    genuinely swapped while that list stays identical (see
    _best_atom_correspondence's own docstring), so a string-order check
    alone would silently miss exactly the case P7.2 exists to catch.

    A reorder is only APPLIED when it is a strictly cheaper correspondence
    than the endpoint's given order by more than
    `_REORDER_TIE_TOLERANCE_ANGSTROM` total distance -- not merely
    whenever the optimal assignment happens to differ from identity by an
    floating-point-noise-scale margin. This keeps a genuinely correctly-
    ordered pair (including one that has moved a lot, e.g. a real reaction
    path) from being spuriously relabeled by an equally-costed tie, while
    still catching an atom order that is actually wrong."""
    start_symbols = list(start["symbols"])
    end_symbols = list(end["symbols"])
    if sorted(start_symbols) != sorted(end_symbols):
        raise ValueError(
            "Start and end geometries do not have the same atoms -- "
            f"got {len(start_symbols)} vs {len(end_symbols)} atoms, or different elements "
            f"altogether. These cannot be a start/end pair for the same path."
        )

    permutation = _best_atom_correspondence(start, end)
    identity = list(range(len(start_symbols)))
    if permutation == identity:
        return end, []

    start_c = np.asarray(start["coords"], dtype=float)
    end_c = np.asarray(end["coords"], dtype=float)
    end_c_shifted = end_c - end_c.mean(axis=0) + start_c.mean(axis=0)
    identity_cost = float(np.linalg.norm(start_c - end_c_shifted, axis=1).sum())
    permuted_cost = float(np.linalg.norm(start_c - end_c_shifted[permutation], axis=1).sum())
    if identity_cost - permuted_cost < _REORDER_TIE_TOLERANCE_ANGSTROM:
        return end, []

    reordered = dict(end)
    reordered["symbols"] = [end_symbols[p] for p in permutation]
    reordered["coords"] = [list(map(float, end["coords"][p])) for p in permutation]
    warning = (
        "The end geometry's atoms were not in the same order as the start geometry "
        "(same elements, different order) -- they were reordered automatically by "
        "matching each atom to the nearest same-element atom after aligning the two "
        "structures' centers of mass. Double-check the interpolated path makes "
        "chemical sense: this heuristic can mismatch atoms of the same element in a "
        "highly symmetric molecule."
    )
    return reordered, [warning]


def _image(template: dict, coords, name_suffix: str) -> dict:
    # dict(template) is a SHALLOW copy -- geom["symbols"] would otherwise
    # be the exact same list object as template["symbols"], shared by
    # every image built from this template. Harmless as long as nothing
    # ever mutates a symbols list in place, but that's a fragile
    # assumption to lean on silently -- copying it here means every
    # image is a genuinely independent dict, matching what a caller
    # holding a list of "separate" geometries would reasonably expect.
    geom = dict(template)
    geom["symbols"] = list(template["symbols"])
    geom["coords"] = [list(map(float, xyz)) for xyz in coords]
    geom["name"] = f"{template.get('name', 'molecule')} {name_suffix}"
    return geom


def _kabsch_rotation(coords_a: np.ndarray, coords_b: np.ndarray) -> np.ndarray:
    """Rotation matrix R (applied as `centered_b @ R`) that best aligns
    (centroid-centered) coords_b onto (centroid-centered) coords_a."""
    a_centered = coords_a - coords_a.mean(axis=0)
    b_centered = coords_b - coords_b.mean(axis=0)
    h = b_centered.T @ a_centered
    u, _s, vt = np.linalg.svd(h)
    d = np.sign(np.linalg.det(u @ vt))
    e = np.eye(3)
    e[2, 2] = d
    return u @ e @ vt


def kabsch_align(coords_a: np.ndarray, coords_b: np.ndarray) -> np.ndarray:
    """Aligns coords_b onto coords_a via the Kabsch algorithm (rotation +
    translation only, no reflection/scaling) -- direct port of the
    reference script's align_structures, generalized to any atom count."""
    rot = _kabsch_rotation(coords_a, coords_b)
    return (coords_b - coords_b.mean(axis=0)) @ rot + coords_a.mean(axis=0)


def linear_path(start: dict, end: dict, n_points: int) -> list[dict]:
    """Naive Cartesian linear interpolation between the two endpoints.
    `start`/`end` must already be reconciled (same atom order) -- see
    build_path, the only caller."""
    start_c = np.asarray(start["coords"], dtype=float)
    end_c = np.asarray(end["coords"], dtype=float)
    images = []
    for i, frac in enumerate(np.linspace(0.0, 1.0, n_points)):
        coords = (1 - frac) * start_c + frac * end_c
        images.append(_image(start, coords, f"(linear frame {i + 1}/{n_points})"))
    return images


def liic_path(start: dict, end: dict, n_points: int) -> list[dict]:
    """True internal-coordinate LIIC: bond/angle/dihedral values are
    interpolated linearly (dihedral via the shortest angular path), using
    a single fixed reference-atom assignment taken from `start` so both
    endpoints -- and every intermediate frame -- describe the same
    internal coordinates. `start`/`end` must already be reconciled (same
    atom order) -- see build_path, the only caller."""
    start_rows = cartesian_to_zmatrix(start["symbols"], start["coords"])
    end_rows = internal_coordinates_with_refs(end["coords"], start_rows)
    start_c = np.asarray(start["coords"], dtype=float)

    images = []
    rot = centroid_frame0 = None
    for i, frac in enumerate(np.linspace(0.0, 1.0, n_points)):
        frame_rows = []
        for s_row, e_row in zip(start_rows, end_rows):
            row = dict(s_row)
            if s_row["distance"] is not None:
                row["distance"] = (1 - frac) * s_row["distance"] + frac * e_row["distance"]
            if s_row["angle_deg"] is not None:
                row["angle_deg"] = (1 - frac) * s_row["angle_deg"] + frac * e_row["angle_deg"]
            if s_row["dihedral_deg"] is not None:
                # Shortest angular path -- interpolating raw degree values
                # would take the long way around whenever the two endpoints
                # straddle the +-180 wraparound.
                delta = ((e_row["dihedral_deg"] - s_row["dihedral_deg"]) + 180.0) % 360.0 - 180.0
                row["dihedral_deg"] = s_row["dihedral_deg"] + frac * delta
            frame_rows.append(row)
        coords = np.asarray(zmatrix_to_cartesian(frame_rows))
        if i == 0:
            # NeRF reconstructs in its own bootstrap frame (atom 0 at the
            # origin, atom 1 along +x, ...), unrelated to start's actual
            # orientation -- but that bootstrap frame is deterministic
            # given the same reference-atom assignment, so every frame is
            # already mutually consistent with every other. Computing the
            # rigid transform that aligns frame 0 back onto `start`'s real
            # coordinates once, then reusing that same transform for every
            # frame, keeps the whole path visually anchored to the
            # orientation the user actually set, without re-aligning each
            # frame independently (energies/internal geometry are
            # unaffected either way -- this is purely for display).
            rot = _kabsch_rotation(start_c, coords)
            centroid_frame0 = coords.mean(axis=0)
        coords = (coords - centroid_frame0) @ rot + start_c.mean(axis=0)
        images.append(_image(start, coords, f"(LIIC frame {i + 1}/{n_points})"))
    return images


def idpp_path(start: dict, end: dict, n_points: int) -> list[dict]:
    """Kabsch-align `end` onto `start`, then interpolate via ASE's
    Image Dependent Pair Potential (NEB.interpolate(method='idpp')) --
    the same approach as the reference script this feature was modeled
    on. Requires `ase` (see requirements.txt). `start`/`end` must already
    be reconciled (same atom order) -- see build_path, the only caller."""
    from ase import Atoms
    from ase.mep import NEB

    start_c = np.asarray(start["coords"], dtype=float)
    end_c = np.asarray(end["coords"], dtype=float)
    aligned_end_c = kabsch_align(start_c, end_c)

    symbols = start["symbols"]
    initial = Atoms(symbols=symbols, positions=start_c)
    final = Atoms(symbols=symbols, positions=aligned_end_c)

    images = [initial] + [initial.copy() for _ in range(n_points - 2)] + [final]
    neb = NEB(images, method="improvedtangent")
    neb.interpolate(method="idpp")

    return [
        _image(start, atoms.get_positions(), f"(IDPP frame {i + 1}/{n_points})")
        for i, atoms in enumerate(images)
    ]


_PATH_BUILDERS = {"linear": linear_path, "liic": liic_path, "idpp": idpp_path}


def build_path(start: dict, end: dict, n_points: int, method: str = "idpp") -> tuple[list[dict], list[str]]:
    """(images, warnings). Reconciles `start`/`end` (see
    _reconcile_endpoints) exactly once here, before handing them to
    whichever method actually builds the path -- so a reorder is applied
    identically regardless of which of the three interpolation methods is
    used, and is never (re-)computed inside them."""
    if n_points < 2:
        raise ValueError("pes_scan needs at least 2 points (n_points >= 2) to interpolate between two geometries")
    if method not in _PATH_BUILDERS:
        raise ValueError(f"Unknown interpolation_method '{method}' -- use one of {sorted(_PATH_BUILDERS)}")
    end, warnings = _reconcile_endpoints(start, end)
    return _PATH_BUILDERS[method](start, end, n_points), warnings
