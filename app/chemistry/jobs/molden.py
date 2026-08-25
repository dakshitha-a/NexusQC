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
from pyscf.dft import gen_grid, numint
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


def _plane_reflection_symmetry(mol, normal: np.ndarray, origin: np.ndarray, mo_coeff: np.ndarray) -> np.ndarray:
    """<psi|sigma_h|psi> for every orbital in mo_coeff, for a planar
    molecule whose plane passes through `origin` with unit `normal`.

    Returns +1 for an orbital symmetric under reflection through the
    molecular plane (a', i.e. sigma-type) and -1 for an antisymmetric one
    (a'', i.e. part of the pi system). This replaced point-sampling the
    amplitude at +/-delta along the normal, which asked the same question
    but answered it from a single probe point and so was only as good as
    that point's choice. Two ways that failed on real orbitals of the
    uracil CASSCF job a4a45e5403df:

    - Probing above the midpoint of a bond is a near-node for the
      antibonding partner. The pi* orbital 30 came back with an amplitude
      of 0.0025 there, a factor of 100 below its actual scale, which is
      noise dressed as a measurement.
    - Probing above a nucleus is an exact node for an in-plane p-type lone
      pair. Orbitals 23 and 28, both genuine oxygen lone pairs, came back
      at 0.001 and 0.003, and their sigma label was decided by which way
      that noise happened to point.

    Integrating the overlap of each orbital with its own mirror image asks
    the whole orbital rather than one point, so there is no probe point to
    choose and no amplitude floor to tune. On uracil/cc-pVDZ every orbital
    comes back at exactly +/-1.00000 (verified against all 132), where the
    point samples spanned three orders of magnitude.

    The grid is Becke level 0, the coarsest pyscf offers, and the
    accumulation is blocked so a large molecule never materializes a full
    npoints x nao AO matrix. Level 0 reproduced level 1 to machine
    precision on uracil and costs about 0.04 s there, which is why the
    cheaper grid is the one wired in.
    """
    grids = gen_grid.Grids(mol)
    grids.level = 0
    grids.build()
    nao = mo_coeff.shape[0]
    mirror_ovlp = np.zeros((nao, nao))
    grid_ovlp = np.zeros((nao, nao))
    for start in range(0, len(grids.coords), 8000):
        pts = grids.coords[start:start + 8000]
        wts = grids.weights[start:start + 8000]
        # Reflect each point through the plane, then evaluate the same AOs
        # there: ao_mirror[:, nu] is chi_nu(sigma_h r).
        offset = (pts - origin) @ normal
        ao = numint.eval_ao(mol, pts)
        ao_mirror = numint.eval_ao(mol, pts - 2 * np.outer(offset, normal))
        mirror_ovlp += ao.T @ (wts[:, None] * ao_mirror)
        grid_ovlp += ao.T @ (wts[:, None] * ao)
    out = np.zeros(mo_coeff.shape[1])
    for idx in range(mo_coeff.shape[1]):
        C = mo_coeff[:, idx]
        # Normalize against the grid's own overlap rather than the analytic
        # one, so the quadrature error cancels between numerator and
        # denominator instead of pulling a clean +/-1 off the mark.
        denom = float(C @ grid_ovlp @ C)
        out[idx] = float(C @ mirror_ovlp @ C) / denom if abs(denom) > 1e-12 else 0.0
    return out


def classify_orbital_character(mol, mo_coeff: np.ndarray, mo_occ: np.ndarray) -> list[dict]:
    """Per-orbital {"character": "sigma"/"pi"/"n"/"sigma*"/"pi*"/None,
    "localized_atom": str} for every orbital in mo_coeff, using only
    already-in-memory data (no new QM calculation).

    scripts/validate_orbital_character.py is the standing check on this,
    and should be run after any change here. It covers water, ethylene,
    formaldehyde, uracil and ammonia, chosen so that every expectation is
    a symmetry statement rather than a judgement call.

    Atom localization: per-orbital Mulliken population. A dominant 1-2
    atoms (>15% each, together >60%) get named directly; otherwise the
    orbital is honestly reported as delocalized rather than forced into a
    false single-bond label -- canonical/natural CASSCF orbitals of a
    symmetric or conjugated system genuinely aren't 2-center bonds (that's
    what Boys/Pipek-Mezey localization is for, and this function
    deliberately does not apply one, since the table needs to describe the
    ACTUAL displayed natural orbitals, not a separately-localized set).

    Shape (sigma/pi/n): for a planar molecule, integrate each orbital
    against its own mirror image in the molecular plane
    (_plane_reflection_symmetry) -- antisymmetric (a'') means pi,
    symmetric (a') means sigma, or n when the orbital also sits on a
    single atom. This replaced a point-sample of the amplitude just above
    and below the plane, which asked the same question from one probe
    point and got it wrong wherever that point happened to be a node; see
    _plane_reflection_symmetry for the two orbital types it failed on.
    Falls back to a two-center ring-sampling test
    (_ring_sample_character) for a non-planar molecule with exactly 2
    dominant atoms; anything else is left unclassified (None) rather than
    guessed.

    Symmetry alone does not separate pi from a lone pair, because an
    out-of-plane lone pair is antisymmetric too. What separates them is
    whether the orbital has a bonding partner, so an a'' orbital is
    reported as pi unless a single atom carries more than 60% of it.
    Water's HOMO (100% oxygen) stays a lone pair on that test, while
    formaldehyde's C=O pi (0.658/0.342) and the nitrogen p that conjugates
    into uracil's ring come out as pi, which is what they chemically are.

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

    # One grid pass for the whole set of orbitals rather than one per
    # orbital -- the two AO matrices it accumulates are shared by every
    # column of mo_coeff.
    plane_symmetry = _plane_reflection_symmetry(mol, normal, centroid, mo_coeff) if is_planar else None

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
        if plane_symmetry is not None:
            s = plane_symmetry[idx]
            # A planar molecule's orbitals are a' or a'' exactly, so these
            # come back at +/-1 with room to spare. The 0.8 window only
            # catches a molecule that passed the planarity test while being
            # slightly buckled, where neither label is honest.
            shape = "pi" if s < -0.8 else "sigma" if s > 0.8 else None
        elif len(dominant) == 2:
            shape = _ring_sample_character(mol, C, coords[dominant[0][0]], coords[dominant[1][0]])

        occ = float(mo_occ[idx])
        # "n" means the orbital really does sit on one atom, which is the
        # same >0.6 test that decides whether localized_atom can name it.
        # The old test only asked whether one atom cleared the 0.15 floor
        # while no second one did, and that mislabeled uracil's orbital 25
        # (job a4a45e5403df): a pi orbital carrying 37% on N2 with the rest
        # spread over N1, O8 and C3 was called a lone pair, in a row whose
        # own localized_atom said "delocalized over" those four atoms.
        # Nothing else on that orbital was ambiguous. It is antisymmetric
        # about the molecular plane, which no lone pair spread across four
        # atoms can be.
        #
        # The threshold has to stay, rather than letting the shape test
        # decide on its own, because a genuinely isolated out-of-plane lone
        # pair is antisymmetric too: water's HOMO is 100% oxygen and is a
        # lone pair, not a pi bond. What separates it from a real pi
        # orbital is a bonding partner, and that is what the population
        # test measures. Water's HOMO puts 1.000 on O, while formaldehyde's
        # C=O pi splits 0.658/0.342 and pyrrole's nitrogen-derived pi
        # splits 0.502/0.167/0.167, so 0.6 sits in open space between them.
        single_atom = len(dominant) == 1 and dominant[0][1] > 0.6
        if single_atom:
            character = "n"
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
