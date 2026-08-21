"""Universal molden-file -> orbital-table/cube conversion, shared by any
engine that can write a standard .molden file (ORCA, BAGEL) so their
orbitals can be visualized the same way PySCF's own run_mo_visualization
already does -- PySCF needs no round-trip since cubegen.orbital works
directly off its own in-memory mo_coeff.

pyscf.tools.molden.load()'s return shape depends on whether the file has
one MO section (restricted/ROHF -- a single mo_energy/mo_coeff/mo_occ
array) or two (genuinely unrestricted -- alpha/beta as a 2-tuple of
arrays). Every function here normalizes to a flat, 1-based, optionally
spin-labeled orbital list so callers never need to know which case they're
in.
"""
from __future__ import annotations

import numpy as np
from pyscf.dft import numint
from pyscf.tools import cubegen, molden

_HARTREE_TO_EV = 27.211386245988


def _flatten_spins(mo_energy, mo_occ) -> list[tuple[str | None, object, object]]:
    """Returns [(spin_label, energy, occ), ...] in orbital order --
    spin_label is None for a restricted/ROHF molden (single MO section),
    or "alpha"/"beta" for a genuinely unrestricted one (two MO sections,
    confirmed via pyscf_runner._dominant_transition hitting the same
    tuple-vs-array split for ROHF's td.xy amplitudes)."""
    if isinstance(mo_energy, tuple):
        out = []
        for spin_label, e, occ in (("alpha", mo_energy[0], mo_occ[0]), ("beta", mo_energy[1], mo_occ[1])):
            out.extend((spin_label, e[i], occ[i]) for i in range(len(e)))
        return out
    return [(None, mo_energy[i], mo_occ[i]) for i in range(len(mo_energy))]


def orbital_table(molden_path: str) -> list[dict]:
    """1-based index (per spin channel, if unrestricted), energy (eV), and
    occupancy for every orbital in a molden file -- feeds
    OrbitalTable.tsx's row list."""
    _mol, mo_energy, _mo_coeff, mo_occ, _irrep, _spins = molden.load(molden_path)
    rows = []
    counters: dict[str | None, int] = {}
    for spin_label, energy, occ in _flatten_spins(mo_energy, mo_occ):
        counters[spin_label] = counters.get(spin_label, 0) + 1
        rows.append({
            "index": counters[spin_label],
            "spin": spin_label,
            "energy_eV": float(energy) * _HARTREE_TO_EV,
            # Natural-orbital occupations come back as tiny negative
            # numbers for empty orbitals, which format as "-0.0" and
            # read as a measured quantity with a sign. Same clamp the
            # single-orbital entropies get in pyscf_runner.
            "occupancy": 0.0 if abs(float(occ)) < 1e-9 else float(occ),
        })
    return rows


def cube_for_orbital(molden_path: str, index_1based: int, cube_path: str, spin: str | None = None) -> None:
    """Writes a cube file for one orbital, selected the same way
    orbital_table numbers it (1-based, per spin channel)."""
    mol, mo_energy, mo_coeff, mo_occ, _irrep, _spins = molden.load(molden_path)
    if isinstance(mo_energy, tuple):
        channel = 0 if spin == "alpha" else 1 if spin == "beta" else None
        if channel is None:
            raise ValueError("this molden file has separate alpha/beta orbitals -- 'spin' must be specified")
        coeff = mo_coeff[channel]
        n = coeff.shape[1]
    else:
        coeff = mo_coeff
        n = coeff.shape[1]

    idx = index_1based - 1
    if idx < 0 or idx >= n:
        raise ValueError(f"orbital index {index_1based} out of range (1..{n})")
    cubegen.orbital(mol, cube_path, coeff[:, idx])


def _mulliken_atom_populations(mol, C: np.ndarray, S: np.ndarray) -> np.ndarray:
    """Per-atom Mulliken population for one MO coefficient vector C,
    normalized to sum to 1 (a genuinely normalized MO already sums to ~1;
    the explicit normalization just guards against small numerical
    drift)."""
    PS = np.outer(C, C) * S
    ao_slices = mol.aoslice_by_atom()
    pops = np.array([PS[ao_slices[ia, 2]:ao_slices[ia, 3], :].sum() for ia in range(mol.natm)])
    total = pops.sum()
    return pops / total if abs(total) > 1e-8 else pops


def _ring_sample_character(
    mol, C: np.ndarray, pos_a: np.ndarray, pos_b: np.ndarray, n_samples: int = 8, radius: float = 0.6,
) -> str | None:
    """Fallback shape classification (sigma/pi, by sign-change count around
    a ring perpendicular to the A-B axis at its midpoint) for a
    2-atom-localized orbital in a non-planar molecule, where
    classify_orbital_character's plane-reflection test isn't applicable.
    Returns None (unclassified) rather than guessing at delta/higher-order
    nodal patterns, which are rare and not worth a false label."""
    axis = pos_b - pos_a
    norm = np.linalg.norm(axis)
    if norm < 1e-6:
        return None
    axis = axis / norm
    arbitrary = np.array([1.0, 0.0, 0.0]) if abs(axis[0]) < 0.9 else np.array([0.0, 1.0, 0.0])
    u = np.cross(axis, arbitrary)
    u /= np.linalg.norm(u)
    v = np.cross(axis, u)
    midpoint = (pos_a + pos_b) / 2
    points = np.array([
        midpoint + radius * (np.cos(2 * np.pi * k / n_samples) * u + np.sin(2 * np.pi * k / n_samples) * v)
        for k in range(n_samples)
    ])
    vals = numint.eval_ao(mol, points) @ C
    if np.max(np.abs(vals)) < 1e-4:
        return None
    signs = np.sign(vals)
    changes = sum(1 for i in range(n_samples) if signs[i] != signs[(i + 1) % n_samples])
    if changes <= 1:
        return "sigma"
    if changes in (2, 3):
        return "pi"
    return None  # delta or higher -- rare, don't guess


def classify_orbital_character(mol, mo_coeff: np.ndarray, mo_occ: np.ndarray) -> list[dict]:
    """Per-orbital {"character": "sigma"/"pi"/"n"/"sigma*"/"pi*"/None,
    "localized_atom": str} for every orbital in mo_coeff, using only
    already-in-memory data (no new QM calculation). Validated ad hoc
    against water (core O 1s and an O lone pair combination both come out
    single-atom-localized, "n") and ethylene (HOMO -> pi bonding, LUMO ->
    pi* antibonding via point-sampling that gave an exact -1.000 symmetry
    ratio, matching textbook ethylene) before being wired in here.

    Atom localization: per-orbital Mulliken population. A dominant 1-2
    atoms (>15% each, together >60%) get named directly; otherwise the
    orbital is honestly reported as delocalized rather than forced into a
    false single-bond label -- canonical/natural CASSCF orbitals of a
    symmetric or conjugated system genuinely aren't 2-center bonds (that's
    what Boys/Pipek-Mezey localization is for, and this function
    deliberately does not apply one, since the table needs to describe the
    ACTUAL displayed natural orbitals, not a separately-localized set).

    Shape (sigma/pi/n): for a planar molecule, point-sample the orbital
    amplitude at +/-delta along the molecular-plane normal at the
    population-weighted centroid of the dominant atom(s) -- antisymmetric
    means pi, symmetric means sigma (or n if localized on a single atom
    with no bonding partner). Falls back to a two-center ring-sampling
    test (_ring_sample_character) for a non-planar molecule with exactly 2
    dominant atoms; anything else is left unclassified (None) rather than
    guessed.

    Bonding vs antibonding: the orbital's own natural occupation number
    (already computed for every table row) -- occ >= 1.0 is bonding-type,
    < 1.0 is antibonding-type ("*" suffix). This reuses data already in
    the table instead of a second, more fragile nodal-counting pass.
    """
    S = mol.intor("int1e_ovlp")
    coords = mol.atom_coords()  # bohr, matches eval_ao's expected units
    natm = mol.natm
    centroid = coords.mean(axis=0)

    is_planar = False
    normal = None
    if natm >= 3:
        centered = coords - centroid
        _, sv, vt = np.linalg.svd(centered)
        if sv[0] > 1e-6:
            is_planar = sv[-1] < 0.05 * sv[0]
            normal = vt[-1]

    def atom_label(ia: int) -> str:
        # mol.atom_symbol(ia) already embeds the 1-based atom index (e.g.
        # "O2", not "O") when mol was reloaded from a molden file (molden's
        # own atom-labeling convention) -- confirmed directly against a real
        # molden round-trip, where a naive f"{symbol}{ia+1}" doubled up into
        # "O22". Strip any trailing digits before appending our own index so
        # this works the same whether mol came from a molden reload or a
        # fresh gto.Mole (whose atom_symbol has no embedded index).
        element = mol.atom_symbol(ia).rstrip("0123456789")
        return f"{element}{ia + 1}"

    results = []
    for idx in range(mo_coeff.shape[1]):
        C = mo_coeff[:, idx]
        pops = _mulliken_atom_populations(mol, C, S)
        order = np.argsort(-pops)
        top_atoms = [(int(ia), float(pops[ia])) for ia in order if pops[ia] > 0.10][:4]
        dominant = [(ia, p) for ia, p in top_atoms if p > 0.15]

        if not dominant:
            localized_atom = "delocalized" + (
                f" over {', '.join(atom_label(ia) for ia, _ in top_atoms)}" if top_atoms else ""
            )
        elif len(dominant) <= 2 and sum(p for _, p in dominant) > 0.6:
            localized_atom = "-".join(atom_label(ia) for ia, _ in dominant)
        else:
            localized_atom = "delocalized over " + ", ".join(atom_label(ia) for ia, _ in top_atoms)

        shape = None
        if is_planar:
            center_pt = centroid
            if dominant:
                pts = np.array([coords[ia] for ia, _ in dominant])
                wts = np.array([p for _, p in dominant])
                center_pt = (pts * wts[:, None]).sum(axis=0) / wts.sum()
            for shift in (0.5, 1.0, 1.5):
                sample_pts = np.array([center_pt + shift * normal, center_pt - shift * normal])
                v_plus, v_minus = numint.eval_ao(mol, sample_pts) @ C
                if abs(v_plus) > 1e-4 or abs(v_minus) > 1e-4:
                    shape = "pi" if v_plus * v_minus < 0 else "sigma"
                    break
        elif len(dominant) == 2:
            shape = _ring_sample_character(mol, C, coords[dominant[0][0]], coords[dominant[1][0]])

        occ = float(mo_occ[idx])
        if len(dominant) <= 1:
            character = "n" if dominant else None
        elif shape is not None:
            character = f"{shape}{'*' if occ < 1.0 else ''}"
        else:
            character = None

        results.append({"character": character, "localized_atom": localized_atom})
    return results


def orbital_character(molden_path: str) -> list[dict]:
    """Per-orbital {"character", "localized_atom"} for every orbital in a
    molden file, in the same order/numbering orbital_table() uses --
    reloads the file itself (a second molden.load() beyond orbital_table's
    own) since callers (bagel_runner.py) only have the file path, not an
    in-memory mol/mo_coeff/mo_occ the way pyscf_runner.py's own HF/CASSCF
    paths do (those call classify_orbital_character directly). Only valid
    for a molden export whose AO coefficients round-trip faithfully into
    pyscf's own basis-function normalization convention -- confirmed true
    for PySCF's own exports (no round-trip needed, generated by this same
    library) and BAGEL's (point-sampling verified elsewhere in this app),
    but NOT for ORCA's (its molden export's AO columns come back scaled by
    a shell-dependent constant relative to pyscf's convention, which would
    silently distort which atom this function considers dominant -- see
    CLAUDE.md's MO-visualization architecture note). Callers must not use
    this on an ORCA molden file."""
    mol, mo_energy, mo_coeff, mo_occ, _irrep, _spins = molden.load(molden_path)
    if isinstance(mo_energy, tuple):
        return (
            classify_orbital_character(mol, mo_coeff[0], mo_occ[0])
            + classify_orbital_character(mol, mo_coeff[1], mo_occ[1])
        )
    return classify_orbital_character(mol, mo_coeff, mo_occ)
