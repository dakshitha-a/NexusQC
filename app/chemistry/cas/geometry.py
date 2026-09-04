"""Chemical perception from a geometry alone -- no pyscf, no RDKit, pure numpy.

This module answers one question: *which directions in space matter for this
molecule's active space?* Everything downstream is a projection onto the
orbitals those directions pick out.

The reason it exists is that stock AVAS takes axis-aligned AO labels
(``'C 2px'``), which makes it depend on how the molecule happens to be
oriented in its input file. Measured on rotated pyrrole, that turns a correct
CAS(6,5) into CAS(10,7) -- see
``tests/backend/cas_04_projector_invariance.py``. Real user geometries arrive
in arbitrary orientations, from PubChem or a sketcher or an optimisation, so
an orientation-dependent selector is not usable here. Deriving the axes from
the geometry itself is what buys rotation invariance, and, because the axes
are then expressed in a minimal reference basis, basis invariance with it.

Three kinds of target come out of here, and all three are needed:

- **pi**: the local normal to the plane of an atom's neighbours. This is the
  pi system, and it is what a conjugated organic molecule's active space is
  mostly made of.
- **lone_pair**: a direction on a heteroatom carrying non-bonding density.
  Without these, a dark n->pi* state has no hole orbital to be excited from,
  which is the single most common way an automatically chosen space silently
  fails for carbonyls and azines.
- **sigma**: a bond axis, giving sigma and sigma* into the pool. These are not
  a refinement. Water has no pi system and no useful pi normal, so a projector
  emitting only the first two kinds hands it a pool of two oxygen lone pairs
  -- completely full, one configuration, no virtual orbitals at all. That is
  exactly the degenerate ``(6e,3o)`` failure the legacy runner grew a
  hydrogen-reseed rule and a terminal guard to work around
  (``tests/backend/casreco_02_avas_seed_and_guard.py``). Emitting sigma
  targets is what makes hydrides and saturated systems work at all.

Numbering note: ``atom_index`` is 0-based here, matching pyscf and numpy.
This module is internal; per the project convention, the 1-based conversion
happens at the boundary where a user or the model sees an orbital, not here.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Optional

import numpy as np

# Cordero et al., Dalton Trans. 2008, 2832 -- the same consensus radii most
# perception codes use. Only elements this app is likely to meet are listed;
# `_radius` falls back for anything else rather than raising, because a
# missing radius should degrade bond perception, not fail a whole job.
COVALENT_RADII = {
    "H": 0.31, "He": 0.28, "Li": 1.28, "Be": 0.96, "B": 0.84, "C": 0.76,
    "N": 0.71, "O": 0.66, "F": 0.57, "Ne": 0.58, "Na": 1.66, "Mg": 1.41,
    "Al": 1.21, "Si": 1.11, "P": 1.07, "S": 1.05, "Cl": 1.02, "Ar": 1.06,
    "K": 2.03, "Ca": 1.76, "Sc": 1.70, "Ti": 1.60, "V": 1.53, "Cr": 1.39,
    "Mn": 1.39, "Fe": 1.32, "Co": 1.26, "Ni": 1.24, "Cu": 1.32, "Zn": 1.22,
    "Ga": 1.22, "Ge": 1.20, "As": 1.19, "Se": 1.20, "Br": 1.20, "Kr": 1.16,
    "Ru": 1.46, "Rh": 1.42, "Pd": 1.39, "Ag": 1.45, "I": 1.39,
}
_DEFAULT_RADIUS = 1.20

# Which shell carries the valence p (or d) density, by row. Matches the
# legacy runner's `_AVAS_DEFAULT_SHELL` so the two agree about what "valence"
# means, which keeps the head-to-head comparison honest.
VALENCE_P_SHELL = {
    "B": "2p", "C": "2p", "N": "2p", "O": "2p", "F": "2p", "Ne": "2p",
    "Al": "3p", "Si": "3p", "P": "3p", "S": "3p", "Cl": "3p", "Ar": "3p",
    "Ga": "4p", "Ge": "4p", "As": "4p", "Se": "4p", "Br": "4p", "Kr": "4p",
    "In": "5p", "Sn": "5p", "Sb": "5p", "Te": "5p", "I": "5p",
}
TRANSITION_METALS = {
    "Sc", "Ti", "V", "Cr", "Mn", "Fe", "Co", "Ni", "Cu", "Zn",
    "Y", "Zr", "Nb", "Mo", "Tc", "Ru", "Rh", "Pd", "Ag", "Cd",
    "Hf", "Ta", "W", "Re", "Os", "Ir", "Pt", "Au", "Hg",
}
VALENCE_D_SHELL = {
    el: f"{n}d"
    for els, n in (
        ({"Sc", "Ti", "V", "Cr", "Mn", "Fe", "Co", "Ni", "Cu", "Zn"}, 3),
        ({"Y", "Zr", "Nb", "Mo", "Tc", "Ru", "Rh", "Pd", "Ag", "Cd"}, 4),
        ({"Hf", "Ta", "W", "Re", "Os", "Ir", "Pt", "Au", "Hg"}, 5),
    )
    for el in els
}

# Nominal valence electron count, used only to decide which atoms should carry
# lone pairs at all. Deliberately crude: the projection itself decides whether
# a direction actually holds density, so an over-generous guess here costs a
# near-zero eigenvalue, not a wrong answer.
_LONE_PAIR_ELEMENTS = {
    "N": 5, "P": 5, "As": 5,
    "O": 6, "S": 6, "Se": 6, "Te": 6,
    "F": 7, "Cl": 7, "Br": 7, "I": 7,
}

BOND_TOLERANCE = 1.30

# Two directions closer than this in absolute cosine are treated as the same
# direction. Used to stop an sp2 heteroatom's out-of-plane "lone pair" being
# emitted a second time as its pi orbital.
_PARALLEL_COS = 0.9

# Largest |cos| between a bond and the fitted plane normal that still counts as
# a planar (sp2) centre. 0 is perfectly planar, ~0.37 pyramidal ammonia, ~0.577
# tetrahedral, so this admits a slightly-pyramidalised amide nitrogen and
# rejects a genuine sp3 centre. See `local_pi_normal`.
PLANARITY_COS = 0.25
# Amplitude of s in the oriented hybrid used as a lone-pair target. Lone pairs
# are hybrids rather than pure p lobes on every heteroatom that carries one, so
# the amplitude is not zero, but it is much smaller than an sp2 hybrid's
# 1/sqrt(3) = 0.577, which is what this was until 2026-09-04.
#
# It has to be an ORIENTED hybrid and not a bare valence s. A bare s has no
# direction, so it overlaps an atom's sigma-bonding hybrids exactly as well as
# its lone pair, and adding one to the target set pulled the deep sigma
# framework into the pool: the literature-space match fell from 10/15 to 9/15,
# formaldehyde went from an exact match to (8e,5o), and uracil's MINIMAL tier
# grew from (14e,10o) to (30e,18o). An oriented hybrid discriminates because
# the sigma hybrids on the same atom point along its bonds and the lone pair
# does not, which is the only thing separating them. That still holds, and it
# is why this is not simply zero.
#
# WHY 0.20 AND NOT 0.577. A carbonyl oxygen carries two lone pairs, not one:
# an s-rich hybrid pointing away along the C=O axis, and a much more p-like one
# perpendicular to it in the molecular plane. The n->pi* excitation comes out of
# the p-like one. Aimed at 0.577 the projector selects the s-rich lone pair, and
# the space it builds then cannot describe the state it was chosen for. Measured
# over the benchmark, EVERY n->pi* state was unreachable: the hole of the state
# the space was narrowed for lay only 0.36 to 0.65 inside it, against 0.98 and
# better for every pi->pi* state. On uracil the consequence is total, with no
# n->pi* root appearing at three, six or ten roots.
#
# The value is chosen at a boundary rather than fitted to an optimum, and the
# two metrics that could choose it disagree in a way that leaves no free lunch:
#
#   amplitude    <=0.30                  >=0.35
#   n->pi* states  reachable             unreachable on uracil
#   pyrrole        reference not offered  offered as a tier (ground state only)
#
# It is the same boundary in both rows, so pyrrole's ground-state tier match and
# uracil's n->pi* cannot both be had. 0.20, 0.25 and 0.30 score identically on
# every count (15/21 exact ground state, 18/21 exact with states requested,
# unchanged from 0.577 except that one pyrrole tier), so the choice among them
# rests on reachability alone and 0.20 is the best of the three: uracil's state
# lands at root 2 and 9.03 eV against root 4 and 10.11 eV at 0.30.
#
# Going lower is worse, which is why this is not a slope to keep sliding down.
# At a pure p target the diatomics break, taking the ground-state match from
# 15/21 to 12/21 and the states match from 18/21 to 15/21, and a lone-pair
# target with no s at all stops being oriented in the sense the paragraph above
# describes. 0.20 sits inside the verified plateau rather than on its edge.
#
# Evidence: docs/casbench/hole-capture.md, scripts/casbench/amplitude_tradeoff.py
# for the counts and scripts/casbench/irrep_gate.py for whether the solver
# actually returns the state.
LONE_PAIR_S_AMPLITUDE = 0.20


def _radius(symbol: str) -> float:
    return COVALENT_RADII.get(symbol, _DEFAULT_RADIUS)


def _unit(v) -> Optional[np.ndarray]:
    v = np.asarray(v, dtype=float)
    n = float(np.linalg.norm(v))
    return None if n < 1e-8 else v / n


@dataclass
class Target:
    """One orientation-resolved direction to project onto.

    `axis` is a unit vector in the molecule's own frame. Because it is derived
    from the geometry, it rotates with the molecule, which is the whole point:
    the space it selects is the same whichever way the input happens to be
    oriented. `axis=None` means "the whole shell", used for a metal d shell
    where the ligand field rather than the geometry decides which components
    matter.
    """

    kind: str                             # "pi" | "lone_pair" | "sigma" | "metal_d"
    atom_index: int
    element: str
    shell: str                            # "2p", "3d", "1s", ...
    axis: Optional[list]
    partner_index: Optional[int] = None   # the other atom, for sigma
    # Amplitude of the valence s mixed into this oriented p, making the column
    # an sp hybrid rather than a pure p lobe. Zero leaves the target a pure p.
    s_amplitude: float = 0.0
    note: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class Perception:
    symbols: list
    coords: np.ndarray                    # angstrom, (natm, 3)
    neighbours: list                      # list[list[int]]
    pi_normals: dict = field(default_factory=dict)   # atom_index -> unit vector
    targets: list = field(default_factory=list)      # list[Target]
    notes: list = field(default_factory=list)

    def targets_of(self, kind: str) -> list:
        return [t for t in self.targets if t.kind == kind]


def perceive_bonds(symbols, coords, tolerance: float = BOND_TOLERANCE) -> list:
    """Neighbour lists from covalent radii.

    O(n^2), which is the right complexity here: this runs once per job on
    molecules of tens of atoms, and a neighbour grid would be more code than
    the cost it saves.
    """
    coords = np.asarray(coords, dtype=float)
    n = len(symbols)
    nb = [[] for _ in range(n)]
    if n < 2:
        return nb
    delta = coords[:, None, :] - coords[None, :, :]
    dist = np.sqrt((delta ** 2).sum(-1))
    radii = np.array([_radius(s) for s in symbols])
    cutoff = tolerance * (radii[:, None] + radii[None, :])
    np.fill_diagonal(cutoff, -1.0)
    for i, j in zip(*np.where(dist < cutoff)):
        if i < j:
            nb[int(i)].append(int(j))
            nb[int(j)].append(int(i))
    return nb


def local_pi_normal(i: int, coords, neighbours: list) -> Optional[np.ndarray]:
    """The local pi axis at atom `i`: the normal to the plane of its neighbours.

    Two neighbours give the plane directly by cross product. Three or more are
    fitted: the smallest right-singular vector of the centred neighbour
    displacements is the best-fit plane normal, which stays well defined when
    the atom is slightly pyramidal, as a real (non-idealised) geometry always
    is.

    Returns None when the atom has fewer than two neighbours, when the
    neighbours are collinear so no plane exists, or -- for three or more
    neighbours -- when they are **not actually coplanar**. That last check is
    what distinguishes an sp2 centre from an sp3 one. An SVD always returns a
    least-variance direction, so without it every saturated carbon in the
    molecule acquires a spurious "pi normal" and the pool fills with orbitals
    that have no pi character to project onto; ethane is the smallest case, and
    `tests/backend/cas_01_geometry_axes.py` asserts it stays empty.

    Planarity is measured as the largest absolute cosine between a bond
    direction and the candidate normal. It is zero for a perfectly planar
    centre, about 0.577 for a tetrahedral one and about 0.37 for pyramidal
    ammonia, so the cutoff sits between: a nearly-planar amide nitrogen keeps
    its pi orbital, while an amine's does not and is described by its lone
    pair instead.

    Returning None rather than an arbitrary perpendicular matters: a terminal
    or linear-centre atom has no single pi direction, and inventing one would
    put a meaningless orbital in the pool. Those atoms get the degenerate pair
    from `perpendicular_pair` instead.
    """
    coords = np.asarray(coords, dtype=float)
    nbrs = neighbours[i]
    if len(nbrs) < 2:
        return None
    v = np.asarray([coords[j] - coords[i] for j in nbrs], dtype=float)
    if len(nbrs) == 2:
        return _unit(np.cross(v[0], v[1]))
    centred = v - v.mean(axis=0)
    # vh[-1] is the direction of least variance: the best-fit plane normal.
    _u, _s, vh = np.linalg.svd(centred)
    normal = _unit(vh[-1])
    if normal is None:
        return None
    directions = np.asarray([d for d in (_unit(x) for x in v) if d is not None])
    if directions.size == 0:
        return None
    if float(np.abs(directions @ normal).max()) > PLANARITY_COS:
        return None      # pyramidal or tetrahedral: no pi system here
    return normal


def perpendicular_pair(axis) -> tuple:
    """Two unit vectors spanning the plane perpendicular to `axis`.

    Used for linear centres, where the pi system is a degenerate pair rather
    than a single direction -- N2 and acetylene both need this or they lose
    half their pi space.

    The seed is a fixed lab-frame vector, so the two returned vectors are
    **not** individually covariant under rotation of the molecule: rotate the
    input and you get a different pair spanning the same plane. That is not a
    defect and it cannot be fixed in general -- for an axially symmetric centre
    like N2 there is no molecular direction perpendicular to the axis to seed
    from, so no choice can be covariant. What is invariant, and what the
    projector actually consumes, is the *span*: both members are always
    emitted together, and a projection onto a subspace does not care which
    basis of that subspace it was handed. Tests must therefore assert span
    invariance (the projected space, or the (ne,no) that comes out of it) and
    never per-vector equality.
    """
    axis = _unit(axis)
    if axis is None:
        raise ValueError("perpendicular_pair needs a non-zero axis")
    seed = np.array([1.0, 0.0, 0.0])
    if abs(float(np.dot(seed, axis))) > _PARALLEL_COS:
        seed = np.array([0.0, 1.0, 0.0])
    a = _unit(seed - float(np.dot(seed, axis)) * axis)
    b = _unit(np.cross(axis, a))
    return a, b


def lone_pair_axes(i: int, symbols, coords, neighbours) -> list:
    """Directions on atom `i` that carry non-bonding density.

    The construction is geometric rather than hybridisation-theoretic, because
    the projection that follows discards a direction that turns out to hold no
    density anyway. What matters is only that the true lone pair lies *inside
    the span* of what is emitted here.

    - One neighbour: emits all three non-bonding directions -- the two
      perpendicular to the bond, and the one pointing away along it. Which of
      them is the real lone pair depends on the bond order, which is not
      available here: a carbonyl oxygen's lone pairs are the perpendicular
      pair, while a nitrile or dinitrogen nitrogen's single lone pair lies
      *along* the axis pointing outward. Emitting all three and letting the
      projection discard whichever holds no density is both cheaper and more
      robust than perceiving bond orders. The perpendicular pair is what puts
      the carbonyl oxygen's in-plane n orbital in the pool, and it is why
      formaldehyde's dark n->pi* state is describable at all; the axial
      direction is what gives N2 and the nitriles their lone pairs.
    - Two neighbours (water, ether, sp3 sulfur): one lone pair opposite the
      bonds in the bisector direction, one perpendicular to the plane.
    - Three neighbours (amine): one lone pair, opposite the sum of the bonds.

    Returns [] for carbon and hydrogen, which carry none, and for a heteroatom
    whose coordination shell is full.
    """
    coords = np.asarray(coords, dtype=float)
    el = symbols[i]
    if el not in _LONE_PAIR_ELEMENTS:
        return []
    nbrs = neighbours[i]
    n_bonds = len(nbrs)
    if n_bonds == 0 or n_bonds > 3:
        return []
    v = [_unit(coords[j] - coords[i]) for j in nbrs]
    if any(x is None for x in v):
        return []

    if n_bonds == 1:
        a, b = perpendicular_pair(v[0])
        return [a, b, -v[0]]
    if n_bonds == 2:
        out = []
        bisector = _unit(v[0] + v[1])
        normal = _unit(np.cross(v[0], v[1]))
        if bisector is not None:
            out.append(-bisector)      # opposite the two bonds
        if normal is not None:
            out.append(normal)         # perpendicular to the plane
        return out
    total = _unit(v[0] + v[1] + v[2])
    return [] if total is None else [-total]


def perceive(symbols, coords, *, include_sigma: bool = True,
             include_lone_pairs: bool = True) -> Perception:
    """Full perception pass: bonds, pi normals, and the target list.

    `include_sigma` exists so a large conjugated system can leave sigma targets
    out, where dozens of C-H bonds would swamp the pool with nothing
    chemically interesting. The caller decides. The default is to include
    them, because a missing sigma target is a wrong answer for a hydride,
    whereas an extra one is only a slightly larger pool that ranking prunes.
    """
    coords = np.asarray(coords, dtype=float)
    symbols = list(symbols)
    nb = perceive_bonds(symbols, coords)
    per = Perception(symbols=symbols, coords=coords, neighbours=nb)

    for i, el in enumerate(symbols):
        if el == "H":
            continue

        if el in TRANSITION_METALS:
            # A metal's whole valence d shell goes in, unoriented: the ligand
            # field, not the geometry, decides which components matter, and
            # splitting them here would prejudge that.
            per.targets.append(Target(
                kind="metal_d", atom_index=i, element=el,
                shell=VALENCE_D_SHELL.get(el, "3d"), axis=None,
                note="full valence d shell",
            ))
            continue

        shell = VALENCE_P_SHELL.get(el)
        if shell is None:
            continue

        normal = local_pi_normal(i, coords, nb)
        if normal is None and len(nb[i]) == 1:
            # A terminal heavy atom has no plane of its own, but if the atom it
            # is bonded to has one -- a carbonyl oxygen on an sp2 carbon, say --
            # then that plane is the molecule's, and the terminal atom's pi
            # orbital is perpendicular to it.
            #
            # Inheriting it is not cosmetic. Without it the terminal atom's pi
            # direction comes from `perpendicular_pair`, whose two vectors
            # together with the axial lone pair span the atom's *entire* p
            # shell. The pi target set and the lone-pair target set then cover
            # the same space, and character analysis cannot tell an n orbital
            # from a pi one: formaldehyde's n->pi* hole measured 0.67 on both.
            # Inheriting the neighbour's normal makes pi one specific direction
            # and leaves the lone pairs the two that remain.
            partner = nb[i][0]
            inherited = local_pi_normal(partner, coords, nb)
            if inherited is not None:
                normal = inherited

        if normal is not None:
            per.pi_normals[i] = normal
            per.targets.append(Target(
                kind="pi", atom_index=i, element=el, shell=shell,
                axis=normal.tolist(), note="local pi normal",
            ))
        elif len(nb[i]) == 1:
            # A terminal atom whose neighbour has no plane either -- a linear
            # fragment such as N2 or acetylene. Here the pi system really is a
            # degenerate pair, so both directions are emitted.
            axis = _unit(coords[nb[i][0]] - coords[i])
            if axis is not None:
                for k, vec in enumerate(perpendicular_pair(axis)):
                    per.targets.append(Target(
                        kind="pi", atom_index=i, element=el, shell=shell,
                        axis=vec.tolist(),
                        note=f"degenerate pi of a linear centre ({k + 1} of 2)",
                    ))

        if include_lone_pairs:
            for k, vec in enumerate(lone_pair_axes(i, symbols, coords, nb)):
                # An sp2 heteroatom's out-of-plane "lone pair" IS its pi
                # orbital. Emitting both would double-count one direction and
                # inflate the pool with a duplicate.
                if normal is not None and abs(float(np.dot(vec, normal))) > _PARALLEL_COS:
                    continue
                # ONE oriented sp hybrid per direction, not two and not a
                # bare valence s. All three were measured. A second reference
                # along the same direction (pure p alongside the hybrid) does
                # detect more -- uracil's first carbonyl lone pair scores 0.72
                # against it rather than 0.33 -- but it costs exactly what the
                # bare s cost, because the pool grows with the NUMBER of
                # targets that clear the projector threshold, not with their
                # orientation: both variants drop the literature-space match
                # from 10/15 to 9/15 and push uracil's minimal tier to
                # (30e,18o). Detection and pool size are coupled through that
                # threshold, so this takes the variant that improves detection
                # 17-fold over a pure p lobe (0.019 -> 0.327 on that same
                # orbital) while leaving the target count, and every space in
                # the benchmark, where they were.
                per.targets.append(Target(
                    kind="lone_pair", atom_index=i, element=el, shell=shell,
                    axis=vec.tolist(), s_amplitude=LONE_PAIR_S_AMPLITUDE,
                    note=f"lone pair {k + 1}",
                ))

    if include_sigma:
        seen = set()
        for i in range(len(symbols)):
            for j in nb[i]:
                pair = (min(i, j), max(i, j))
                if pair in seen:
                    continue
                seen.add(pair)
                a, b = pair
                axis = _unit(coords[b] - coords[a])
                if axis is None:
                    continue
                # A sigma bond needs a target on BOTH atoms: the bonding and
                # antibonding combinations are what the projection separates
                # into an occupied and a virtual orbital. Emitting only one end
                # gives a pool with no virtual partner, which is the water
                # failure this branch exists to prevent.
                for at, other, sign in ((a, b, 1.0), (b, a, -1.0)):
                    el = symbols[at]
                    if el == "H":
                        per.targets.append(Target(
                            kind="sigma", atom_index=at, element=el, shell="1s",
                            axis=(sign * axis).tolist(), partner_index=other,
                            note=f"sigma to atom {other}",
                        ))
                        continue
                    shell = VALENCE_P_SHELL.get(el)
                    if shell is None:
                        continue
                    per.targets.append(Target(
                        kind="sigma", atom_index=at, element=el, shell=shell,
                        axis=(sign * axis).tolist(), partner_index=other,
                        note=f"sigma to atom {other}",
                    ))
                    # The valence s as well. A heavy-atom sigma bond is an sp
                    # hybrid, not a pure p lobe, so a p-only target set misses
                    # the s-derived sigma and sigma*. On N2 that is the
                    # difference between the (8e,7o) a p-only set finds and the
                    # (10e,8o) full valence space the literature uses; the same
                    # orbital is missing from O2. Hydrogen is already handled
                    # above, and an s function has no orientation, so the axis
                    # is carried entirely by the partner's p.
                    per.targets.append(Target(
                        kind="sigma", atom_index=at, element=el,
                        shell=f"{shell[0]}s", axis=(sign * axis).tolist(),
                        partner_index=other,
                        note=f"sigma (valence s) to atom {other}",
                    ))

    if not per.targets:
        per.notes.append(
            "No projection targets could be derived from this geometry. That "
            "happens for a lone atom or a bare ion, which has no active space "
            "to recommend in the usual sense."
        )
    return per
