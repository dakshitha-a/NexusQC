"""A recommended active space, written down so it survives a change of basis.

Basis independence is only worth anything if the *handoff* has it too. The
recommendation is computed in one basis and the CASSCF that follows is usually
run in another, so whatever passes between them decides whether the property
holds end to end.

The obvious handoff -- a list of molecular-orbital indices -- does not have it.
An index names the n-th orbital of one particular calculation; run the same
molecule in a larger basis and the n-th orbital is a different function. The
previous engine handed off exactly that (`active_space_orbital_indices`), which
was consistent with a recommendation that already depended on the basis, and is
not consistent with one that does not.

What is written down instead is the *question*, not the answer: the target
directions the space was selected by, expressed in the minimal reference basis,
plus the thresholds used. Given any later mean field, re-asking that question
reproduces the same space. The minimal basis is the load-bearing part -- it is
fixed, so a target expressed in it means the same thing in def2-SVP and in
aug-cc-pVQZ, and the overlap machinery that re-expands it is the same code that
built it.

The geometry is recorded and checked. A specification is a statement about a
particular structure, and silently applying one to a different geometry would
reproduce the class of failure this project has met before, where a space
recommended for one molecule was reported for another.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field

import numpy as np

SCHEMA = "nexusqc.active_space_spec/1"

# Angstrom. Two geometries further apart than this are not the same structure,
# and a space selected for one does not describe the other. Loose enough to
# tolerate a re-optimisation or a coordinate round trip, tight enough to catch
# a different conformer or a different molecule.
GEOMETRY_TOLERANCE = 0.05


@dataclass
class ActiveSpaceSpec:
    schema: str
    reference: dict          # basis_of_record, geometry, charge, multiplicity
    targets: list            # the oriented directions, in the minimal basis
    thresholds: dict
    tiers: dict              # name -> {n_electrons, n_orbitals}
    selected_tier: str
    diagnostics: dict = field(default_factory=dict)

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(asdict(self), indent=indent)

    @classmethod
    def from_json(cls, text: str) -> "ActiveSpaceSpec":
        raw = json.loads(text)
        got = raw.get("schema")
        if got != SCHEMA:
            raise ValueError(
                f"This active-space specification is version {got!r}, and this "
                f"code reads {SCHEMA!r}. Rather than guess at the difference, "
                f"re-run the recommendation.")
        return cls(**raw)

    def space(self) -> tuple:
        t = self.tiers[self.selected_tier]
        return t["n_electrons"], t["n_orbitals"]


def build(recommendation, symbols, coords, targets, *, charge: int = 0,
          multiplicity: int = 1, tier: str = "recommended",
          diagnostics: dict = None) -> ActiveSpaceSpec:
    """Write a recommendation down in a form another basis can read."""
    coords = np.asarray(coords, dtype=float)
    return ActiveSpaceSpec(
        schema=SCHEMA,
        reference={
            "basis_of_record": "minao",
            "geometry": {"symbols": list(symbols),
                         "coords": [[float(x) for x in row] for row in coords]},
            "charge": int(charge),
            "multiplicity": int(multiplicity),
        },
        targets=[t.to_dict() for t in targets],
        thresholds={"projection": 0.2},
        tiers={k: {"n_electrons": v.n_electrons, "n_orbitals": v.n_orbitals}
               for k, v in recommendation.tiers.items()},
        selected_tier=tier,
        diagnostics=dict(diagnostics or {}),
    )


def _check_geometry(spec: ActiveSpaceSpec, symbols, coords) -> None:
    ref = spec.reference["geometry"]
    want_s, want_c = list(ref["symbols"]), np.asarray(ref["coords"], dtype=float)
    got_c = np.asarray(coords, dtype=float)
    if list(symbols) != want_s:
        raise ValueError(
            f"This specification was built for {''.join(want_s)} and is being "
            f"applied to {''.join(symbols)}. An active space is a statement "
            f"about one structure; it does not transfer to another molecule.")
    if got_c.shape != want_c.shape:
        raise ValueError("The geometry has a different number of atoms than "
                         "the specification was built for.")
    drift = float(np.abs(got_c - want_c).max())
    if drift > GEOMETRY_TOLERANCE:
        raise ValueError(
            f"The geometry has moved {drift:.3f} A from the one this "
            f"specification was built for, past the {GEOMETRY_TOLERANCE} A "
            f"tolerance. The targets are directions derived from a structure, "
            f"so they do not describe this one. Re-run the recommendation at "
            f"this geometry.")


def rebuild_in_basis(mf, spec: ActiveSpaceSpec, *, tier: str = None):
    """Reproduce the recommended space against a mean field in any basis.

    Returns ``(ncas, nelecas, mo_coeff, caslst, notes)``, the same shape the
    runner's other orbital-choice helpers use, so a CASSCF can be seeded from
    it directly.
    """
    from app.chemistry.cas.geometry import Target
    from app.chemistry.cas.projector import project

    mol = mf.mol
    symbols = [mol.atom_symbol(i) for i in range(mol.natm)]
    coords = mol.atom_coords() * 0.52917721067
    _check_geometry(spec, symbols, coords)

    targets = [Target(**t) for t in spec.targets]
    pool = project(mf, targets,
                   threshold=float(spec.thresholds.get("projection", 0.2)))

    want = spec.tiers[tier or spec.selected_tier]
    caslst = list(range(pool.ncore, pool.ncore + pool.ncas))
    notes = []
    got = (sum(pool.nelecas), pool.ncas)
    if got != (want["n_electrons"], want["n_orbitals"]):
        # Not an error. The specification records what the space was in the
        # basis it was built in, and a rebuild is the authority on what it is
        # here; a difference is worth saying out loud rather than hiding or
        # raising on, since it is exactly the basis dependence the method
        # claims not to have.
        notes.append(
            f"Rebuilding this specification gives CAS({got[0]}e, {got[1]}o) "
            f"where it recorded CAS({want['n_electrons']}e, "
            f"{want['n_orbitals']}o). The rebuild is what will run.")
    return pool.ncas, pool.nelecas, pool.mo_coeff, caslst, notes
