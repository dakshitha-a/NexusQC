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
from pyscf import lib
from pyscf.data import radii
from pyscf.dft import gen_grid, numint
from pyscf.tools import cubegen, molden

from app.config import N_CORES

# Same per-job core budget the engine workers run under (see engine_thread_env
# in app/config.py), applied here because this module is the one piece of PySCF
# that also runs INSIDE the API process: cube_for_orbital renders an orbital on
# demand when someone clicks a row in the orbital table, on a request thread
# rather than in a job worker. That work never passes the admission gate, so
# left uncapped it would evaluate its grid on every core of the host and, worse
# than being rude, would drive the idle-core count below N_CORES and hold every
# queued job at pending while it ran. Set here rather than through the
# environment because this process is already running: lib.num_threads calls
# omp_set_num_threads, which takes effect at once.
lib.num_threads(N_CORES)

_HARTREE_TO_EV = 27.211386245988

# Appended to every engine's orbital_table_note, so the model reading a table
# knows what the diffuseness column means and, just as importantly, what it
# means when nothing is flagged. That case is ambiguous on its own: either the
# molecule has no diffuse orbital, or the basis has no function able to
# describe one. Reference exponents rather than a rule, because no threshold
# separates the bases cleanly -- cc-pVTZ's smallest is 0.1027 and ma-def2-SVP's
# is 0.0851, so any cut between them would be luck rather than physics.
DIFFUSENESS_NOTE = (
    "diffuse_fraction is how much of an orbital's density lies outside 1.5 van der Waals radii "
    "of every atom; above 0.5 it is flagged diffuse and reported without an atom localization, "
    "since a population analysis of a function centred nowhere describes nothing. Occupied "
    "orbitals sit below 0.01 in practice and non-augmented bases produce nothing above 0.3, so "
    "if nothing here is flagged, check whether the basis could have shown one at all: cc-pVDZ's "
    "smallest primitive exponent is 0.12 and aug-cc-pVDZ's is 0.03. This is a measure of spatial "
    "extent, not a Rydberg assignment, which would need a principal quantum number and a quantum "
    "defect."
)


def annotate_diffuseness_note(summary: dict) -> None:
    """Appends DIFFUSENESS_NOTE to a job summary's orbital_table_note, if
    and only if the table it describes actually carries the column.

    Called from the PySCF and BAGEL workers rather than from each place a
    note is written, because those are two call sites instead of fifteen
    and, more to the point, they cannot be missed. Several job types
    (a plain single point among them) produce an orbital table without
    setting any note at all, so a per-note edit would have left exactly
    the simplest jobs showing an unexplained column. ORCA's worker does
    not call this: its tables carry neither character nor diffuseness,
    for the reason given in orca_runner.render_orbital_cube.
    """
    table = summary.get("orbital_table")
    if not table or "diffuse_fraction" not in (table[0] or {}):
        return
    existing = (summary.get("orbital_table_note") or "").strip()
    summary["orbital_table_note"] = f"{existing} {DIFFUSENESS_NOTE}" if existing else DIFFUSENESS_NOTE


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


_GRID_BLOCK = 8000


def _becke_grid(mol):
    """(coords, weights) for one Becke grid, built once and shared by every
    measurement below rather than rebuilt per orbital or per property.

    Level 1 rather than the cheaper level 0, and the reason is the diffuse
    fraction rather than the symmetry test. Level 0 reproduces level 1 to
    machine precision on uracil's symmetry expectations, but a diffuse
    orbital keeps most of its norm in the grid's sparse outer shells: on
    water/aug-cc-pVDZ, level 0 recovered 1.019 of the analytic norm for
    the lowest Rydberg-like virtual, where level 1 gives 1.0004. A 2%
    error on the integral a fraction is taken from is not worth the
    saving, and level 1 still costs about 0.13 s on uracil."""
    grids = gen_grid.Grids(mol)
    grids.level = 1
    grids.build()
    return grids.coords, grids.weights


def _diffuse_fractions(mol, mo_coeff: np.ndarray, grid) -> np.ndarray:
    """For each orbital, the fraction of its own density lying outside the
    molecule, where outside means further than 1.5 van der Waals radii
    from every atom.

    This exists because every other measurement here assumes the orbital
    sits on the atoms. Mulliken populations do, and so does the sigma/pi
    test. An orbital that lies mostly outside the framework gets a label
    anyway, and on a set of diffuse functions that label describes
    nothing: water/aug-cc-pVDZ has five such orbitals, and before this
    they were reported with atom localizations taken from populations on
    functions whose density is mostly not on any atom.

    Note this is NOT what fixed uracil's orbital 34, reported as a lone
    pair on a hydrogen. That job was cc-pVDZ, whose virtuals top out at a
    fraction of 0.23, so nothing there is flagged. What retired that label
    was tightening "n" to require 60% on one atom. The related complaint
    that orbital 33 named two hydrogens on opposite sides of the ring is
    still open: the A-B label does not check that A and B are bonded.

    The measure is a fraction rather than a radius so that it does not
    scale with the molecule. Across water, formaldehyde, ethylene, benzene
    and uracil, every occupied orbital comes in below 0.010 and every
    cc-pVDZ virtual below 0.29, while aug-cc-pVDZ virtuals reach 0.98. The
    1.5 multiplier is what puts valence antibonding orbitals inside: at a
    bare van der Waals radius, water's cc-pVDZ sigma* orbitals read 0.55
    and 0.61, which would be indistinguishable from a genuinely diffuse
    one.

    Deliberately not called a Rydberg test. Separating a true Rydberg
    series member from a diffuse virtual needs a principal quantum number
    and a quantum defect, not a spatial extent. This reports what it
    measured.
    """
    coords, weights = grid
    atom_coords = mol.atom_coords()
    vdw = np.array([radii.VDW[mol.atom_charge(ia)] for ia in range(mol.natm)])  # bohr
    out = np.zeros(mo_coeff.shape[1])
    total = np.zeros(mo_coeff.shape[1])
    for start in range(0, len(coords), _GRID_BLOCK):
        pts = coords[start:start + _GRID_BLOCK]
        wts = weights[start:start + _GRID_BLOCK]
        outside = (np.linalg.norm(pts[:, None, :] - atom_coords[None, :, :], axis=2)
                   > 1.5 * vdw[None, :]).all(axis=1)
        density = (numint.eval_ao(mol, pts) @ mo_coeff) ** 2
        total += wts @ density
        out += (wts * outside) @ density
    return np.divide(out, total, out=np.zeros_like(out), where=total > 1e-12)


def _symmetry_expectation(mol, mo_coeff: np.ndarray, transform, grid) -> np.ndarray:
    """<psi|R|psi> for every orbital in mo_coeff, where `transform` maps an
    (npoints, 3) array of coordinates to their images under the symmetry
    operation R. Since every orbital here is normalized, the result is +1
    when R leaves the orbital alone, -1 when it flips its sign, and
    something in between when R mixes it with a partner.

    The accumulation is blocked so a large molecule never materializes a
    full npoints x nao AO matrix."""
    coords, weights = grid
    nao = mo_coeff.shape[0]
    image_ovlp = np.zeros((nao, nao))
    grid_ovlp = np.zeros((nao, nao))
    for start in range(0, len(coords), _GRID_BLOCK):
        pts = coords[start:start + _GRID_BLOCK]
        wts = weights[start:start + _GRID_BLOCK]
        ao = numint.eval_ao(mol, pts)
        # ao_image[:, nu] is chi_nu(R r), so the accumulated matrix is
        # <chi_mu | R chi_nu>.
        ao_image = numint.eval_ao(mol, transform(pts))
        image_ovlp += ao.T @ (wts[:, None] * ao_image)
        grid_ovlp += ao.T @ (wts[:, None] * ao)
    out = np.zeros(mo_coeff.shape[1])
    for idx in range(mo_coeff.shape[1]):
        C = mo_coeff[:, idx]
        # Normalize against the grid's own overlap rather than the analytic
        # one, so the quadrature error cancels between numerator and
        # denominator instead of pulling a clean answer off the mark.
        denom = float(C @ grid_ovlp @ C)
        out[idx] = float(C @ image_ovlp @ C) / denom if abs(denom) > 1e-12 else 0.0
    return out


def _plane_reflection_symmetry(mol, normal: np.ndarray, origin: np.ndarray, mo_coeff: np.ndarray, grid) -> np.ndarray:
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
    comes back at +/-1 to five decimals, across all 132 orbitals, where
    the point samples spanned three orders of magnitude.
    """
    def reflect(pts):
        return pts - 2 * np.outer((pts - origin) @ normal, normal)

    return _symmetry_expectation(mol, mo_coeff, reflect, grid)


def _axis_quarter_turn_symmetry(mol, axis: np.ndarray, origin: np.ndarray, mo_coeff: np.ndarray, grid) -> np.ndarray:
    """<psi|C4|psi> for every orbital of a LINEAR molecule, rotating by 90
    degrees about the molecular axis. Separates all three of the labels
    that matter at once, because an orbital with angular momentum lambda
    about the axis picks up cos(lambda * 90 degrees): +1 for sigma, 0 for
    pi, -1 for delta.

    A rotation is used here rather than the reflection that serves planar
    molecules, and the reason is degeneracy. A linear molecule's pi
    orbitals come in degenerate pairs, and an SCF is free to return any
    rotation of a pair within itself. Reflecting through one arbitrary
    plane containing the axis therefore reports whatever mixture it was
    handed: on CO2/6-31G* it returned +1 for one member of each pair and
    -1 for the other, so half of every pi pair was labeled sigma. A
    rotation about the axis has the whole degenerate pair as an
    eigenspace, so its diagonal element is the same no matter which
    mixture arrives. Verified on CO2, acetylene and HCN, where both
    members of every pi pair now agree.
    """
    def rotate(pts):
        # Rodrigues, specialized to 90 degrees: cos term vanishes.
        rel = pts - origin
        return origin + np.cross(axis, rel) + np.outer(rel @ axis, axis)

    return _symmetry_expectation(mol, mo_coeff, rotate, grid)


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
    is_linear = False
    normal = None
    axis = None
    if natm >= 3:
        centered = coords - centroid
        _, sv, vt = np.linalg.svd(centered)
        if sv[0] > 1e-6:
            # A linear molecule passes the planarity test below -- CO2 and
            # acetylene both give sv = [a, 0, 0] -- but it has no unique
            # plane, so vt[-1] is an arbitrary direction perpendicular to
            # the axis. Reflecting through the plane it defines splits each
            # degenerate pi pair, and on CO2/6-31G* that labeled one member
            # of every pair sigma. Rule linear geometries out first and let
            # them fall through to _ring_sample_character, which counts
            # sign changes around the bond axis and so does not depend on
            # which of the degenerate partners the SCF happened to return.
            #
            # The test is the largest distance of any atom from the
            # best-fit line, in bohr, not a ratio against the molecule's
            # length. A ratio would call a long planar chain linear: an
            # all-trans C40 polyene sits at 0.02 on the same scale where
            # CO2 sits at 0, and a C80 at 0.01.
            axis = vt[0]
            off_axis = centered - np.outer(centered @ axis, axis)
            is_linear = float(np.abs(off_axis).max()) < 0.1
            is_planar = not is_linear and sv[-1] < 0.05 * sv[0]
            normal = vt[-1]
    elif natm == 2:
        # A diatomic is linear by definition and never reaches the SVD.
        is_linear = True
        axis = coords[1] - coords[0]
        axis = axis / np.linalg.norm(axis)

    # One grid, built once and shared, and one pass over it per measurement
    # rather than one per orbital -- everything accumulated here is shared
    # by every column of mo_coeff.
    grid = _becke_grid(mol)
    diffuse_fraction = _diffuse_fractions(mol, mo_coeff, grid)
    plane_symmetry = _plane_reflection_symmetry(mol, normal, centroid, mo_coeff, grid) if is_planar else None
    axis_symmetry = _axis_quarter_turn_symmetry(mol, axis, centroid, mo_coeff, grid) if is_linear else None

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

    def bonded(ia: int, ib: int) -> bool:
        """Whether two atoms are close enough to be bonded, so that an
        "A-B" label can be read as the bond it looks like.

        Without this the two-atom label was applied on population weight
        alone, and in uracil 24 of the 33 orbitals that got one named a
        pair that is not bonded. The worst read "O8-O7", the two carbonyl
        oxygens on opposite sides of the ring, 4.53 A apart, reported once
        as sigma* and once as pi*. Taken literally that is a peroxide
        linkage in uracil.

        It is almost entirely a virtuals problem (3 of 3 occupied pair
        labels were real bonds, 6 of 30 virtual ones), because a virtual is
        typically the out-of-phase combination of two equivalent groups
        rather than a two-centre bond. Virtuals are also exactly what a
        user reads off this table when naming an active space, and the
        model answering questions about an orbital sees this string and no
        picture, so a label that invents a bond becomes an answer that
        invents one.

        The measurement was never wrong. An orbital with 37% on O7 and 33%
        on O8 really does sit there. Only the hyphen overclaims, so a
        non-bonded pair now falls through to the "delocalized over" wording
        the three-atom case already used.

        1.30 is not tuned. Across water, ethylene, acetylene, CO2, benzene
        and uracil the widest genuine bond is 1.044 of the summed covalent
        radii and the closest non-bonded pair is 1.626, so the cutoff sits
        24% above the first and 25% below the second. Radii are pyscf's own
        COVALENT table, in bohr, matching atom_coords and the VDW table
        _diffuse_fractions already uses.
        """
        separation = float(np.linalg.norm(coords[ia] - coords[ib]))
        reach = radii.COVALENT[mol.atom_charge(ia)] + radii.COVALENT[mol.atom_charge(ib)]
        return separation < 1.30 * reach

    results = []
    for idx in range(mo_coeff.shape[1]):
        C = mo_coeff[:, idx]
        pops = _mulliken_atom_populations(mol, C, S)
        order = np.argsort(-pops)
        top_atoms = [(int(ia), float(pops[ia])) for ia in order if pops[ia] > 0.10][:4]
        dominant = [(ia, p) for ia, p in top_atoms if p > 0.15]

        diffuse = float(diffuse_fraction[idx]) > 0.5
        if diffuse:
            # Naming an atom here would be a fabrication. The populations
            # below are computed on functions whose density is mostly not
            # on any atom, so they report which atom the diffuse tail
            # happens to be centered on rather than where the orbital is.
            # This is what put a lone pair on a hydrogen in uracil's
            # orbital 34.
            localized_atom = "diffuse, mostly outside the molecule"
        elif not dominant:
            localized_atom = "delocalized" + (
                f" over {', '.join(atom_label(ia) for ia, _ in top_atoms)}" if top_atoms else ""
            )
        elif (sum(p for _, p in dominant) > 0.6
              and (len(dominant) == 1
                   or (len(dominant) == 2 and bonded(dominant[0][0], dominant[1][0])))):
            localized_atom = "-".join(atom_label(ia) for ia, _ in dominant)
        else:
            localized_atom = "delocalized over " + ", ".join(atom_label(ia) for ia, _ in top_atoms)

        shape = None
        if axis_symmetry is not None:
            # +1 sigma, 0 pi, -1 delta. Delta is left unclassified rather
            # than guessed, the same choice _ring_sample_character makes.
            a = axis_symmetry[idx]
            shape = "sigma" if a > 0.7 else "pi" if abs(a) < 0.3 else None
        elif plane_symmetry is not None:
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
        #
        # A diffuse orbital is excluded from the lone-pair branch for the
        # same reason it gets no atom label: the population test it rests
        # on is measuring nothing there. Its shape survives, because plane
        # symmetry is a real property of the orbital however far out it
        # reaches.
        single_atom = not diffuse and len(dominant) == 1 and dominant[0][1] > 0.6

        # A lone pair does not have to sit on one atom. On a nitro, carboxyl
        # or carboxylate group the lone pairs are the symmetric and
        # antisymmetric combinations across two equivalent oxygens, so each
        # oxygen carries about 0.45 and neither clears the single-atom bar.
        # The orbital then falls through to the shape test, and an IN-PLANE
        # lone pair is symmetric about the molecular plane exactly as a sigma
        # bond is, so it comes back "sigma". Measured on o-nitrophenol
        # (job cf7d658c7e76, SA-5 CASSCF(14,10)): the two orbitals at
        # occupancies 1.805 and 1.794, both "delocalized over O9, O8", were
        # labelled sigma. They are the nitro lone pairs, and they are what
        # the S1 and S2 n->pi* states are built from -- so the table said
        # sigma about the very orbitals that gave those states their
        # character.
        #
        # What separates the two is that a sigma BOND has to sit on a bonded
        # pair. These oxygens are both bonded to the nitrogen and not to each
        # other, and the orbital carries almost nothing on the nitrogen. So a
        # group of mutually non-bonded heteroatoms holding the orbital
        # between them is a lone-pair combination, not a bond.
        #
        # Deliberately narrow. It requires heteroatoms (carbon skeletons are
        # not lone-pair territory), an occupied orbital, and the same 0.6
        # total population the single-atom branch demands, so a thin orbital
        # spread over many centres is not swept in. o-Nitrophenol's orbital
        # 11, "delocalized over N7, O8, O9", keeps its sigma label because
        # N7 is bonded to both oxygens.
        hetero = [ia for ia, _p in dominant
                  if int(mol.atom_charge(ia)) not in (1, 6)]
        lone_pair_combination = (
            not diffuse
            and shape != "pi"
            and occ >= 1.0
            and len(dominant) >= 2
            and len(hetero) == len(dominant)
            and sum(p for _, p in dominant) > 0.6
            and not any(bonded(a, b)
                        for i, a in enumerate(hetero)
                        for b in hetero[i + 1:])
        )
        if single_atom or lone_pair_combination:
            character = "n"
        elif shape is not None:
            character = f"{shape}{'*' if occ < 1.0 else ''}"
        else:
            character = None

        results.append({
            "character": character,
            "localized_atom": localized_atom,
            # Rounded because the third decimal is grid noise, not signal.
            "diffuse_fraction": round(float(diffuse_fraction[idx]), 2),
            "diffuse": diffuse,
        })
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
