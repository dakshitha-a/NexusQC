"""Resolve a user-supplied molecule (name, SMILES, or pasted XYZ/xmol
coordinates) into a 3D structure."""
from __future__ import annotations

import hashlib
import json
import re
from collections import Counter
from dataclasses import dataclass, field, asdict

from rdkit import Chem
from rdkit.Chem import AllChem

from app.config import MOLECULES_DIR


@dataclass
class Molecule:
    identifier: str  # what the user typed
    name: str  # best-known common/IUPAC name, falls back to identifier
    smiles: str
    charge: int
    multiplicity: int  # 2S+1
    symbols: list[str]
    coords: list[list[float]]  # angstrom, same order as symbols
    source: str  # "smiles", "pubchem", "opsin"

    def to_xyz_block(self) -> str:
        lines = [str(len(self.symbols)), self.name]
        for sym, (x, y, z) in zip(self.symbols, self.coords):
            lines.append(f"{sym:2s} {x: .8f} {y: .8f} {z: .8f}")
        return "\n".join(lines)

    def to_zmatrix_block(self) -> str:
        from app.chemistry.zmatrix import to_zmatrix_text
        return to_zmatrix_text(self.symbols, self.coords)

    def pyscf_atom_spec(self) -> list[tuple]:
        return [(sym, tuple(xyz)) for sym, xyz in zip(self.symbols, self.coords)]

    def cache_key(self) -> str:
        return hashlib.sha1(f"{self.smiles}|{self.charge}|{self.multiplicity}".encode()).hexdigest()[:16]

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "Molecule":
        return cls(**d)

    def save(self) -> None:
        path = MOLECULES_DIR / f"{self.cache_key()}.json"
        path.write_text(json.dumps(self.to_dict(), indent=2))


def _embed_3d(mol: Chem.Mol) -> Chem.Mol:
    mol = Chem.AddHs(mol)
    params = AllChem.ETKDGv3()
    params.randomSeed = 0xC0FFEE
    cid = AllChem.EmbedMolecule(mol, params)
    if cid < 0:
        # Fallback for tricky cases (e.g. metal complexes): random coords + more tries.
        params.useRandomCoords = True
        cid = AllChem.EmbedMolecule(mol, params)
    if cid < 0:
        raise ValueError("RDKit could not generate 3D coordinates for this structure")
    try:
        AllChem.MMFFOptimizeMolecule(mol, maxIters=2000)
    except Exception:
        try:
            AllChem.UFFOptimizeMolecule(mol, maxIters=2000)
        except Exception:
            pass  # keep the raw embedded geometry; a QC geometry optimization will clean it up anyway
    return mol


def _default_multiplicity(mol: Chem.Mol) -> int:
    n_radical_electrons = sum(a.GetNumRadicalElectrons() for a in mol.GetAtoms())
    return n_radical_electrons + 1


def molecule_from_smiles(smiles: str, name: str | None = None, charge: int | None = None,
                          multiplicity: int | None = None) -> Molecule:
    mol = Chem.MolFromSmiles(smiles)
    if mol is None:
        raise ValueError(f"'{smiles}' is not a valid SMILES string")
    formal_charge = charge if charge is not None else Chem.GetFormalCharge(mol)
    mult = multiplicity if multiplicity is not None else _default_multiplicity(mol)

    mol3d = _embed_3d(mol)
    conf = mol3d.GetConformer()
    symbols, coords = [], []
    for atom in mol3d.GetAtoms():
        pos = conf.GetAtomPosition(atom.GetIdx())
        symbols.append(atom.GetSymbol())
        coords.append([pos.x, pos.y, pos.z])

    canonical_smiles = Chem.MolToSmiles(mol)
    m = Molecule(
        identifier=name or smiles,
        name=name or canonical_smiles,
        smiles=canonical_smiles,
        charge=formal_charge,
        multiplicity=mult,
        symbols=symbols,
        coords=coords,
        source="smiles",
    )
    m.save()
    return m


def molecule_from_molblock(molblock: str, charge: int | None = None, multiplicity: int | None = None) -> Molecule:
    """Builds a Molecule from a 2D-sketcher-exported MDL molfile (the
    molecule-builder UI's "use this structure" action) -- RDKit reads the
    drawn topology (atoms, bonds, formal charges, wedge/hash stereo) from
    the file's connection table, ignoring its 2D coordinates entirely, then
    runs it through the same _embed_3d pipeline (AddHs, ETKDG distance
    geometry, MMFF94/UFF optimization) already used for SMILES-resolved
    molecules -- a sketch and a typed SMILES string produce a conformer via
    the identical code path, so there is nothing sketch-specific about the
    3D generation itself."""
    try:
        mol = Chem.MolFromMolBlock(molblock, sanitize=True)
    except Exception as e:
        raise ValueError(f"Could not parse the sketched structure: {e}")
    if mol is None or mol.GetNumAtoms() == 0:
        raise ValueError("Could not parse the sketched structure -- draw a structure first")

    formal_charge = charge if charge is not None else Chem.GetFormalCharge(mol)
    mult = multiplicity if multiplicity is not None else _default_multiplicity(mol)

    mol3d = _embed_3d(mol)
    conf = mol3d.GetConformer()
    symbols, coords = [], []
    for atom in mol3d.GetAtoms():
        pos = conf.GetAtomPosition(atom.GetIdx())
        symbols.append(atom.GetSymbol())
        coords.append([pos.x, pos.y, pos.z])

    try:
        canonical_smiles = Chem.MolToSmiles(mol)
    except Exception:
        canonical_smiles = ""
    name = canonical_smiles or _molecular_formula(symbols)

    m = Molecule(
        identifier="(sketched)",
        name=name,
        smiles=canonical_smiles,
        charge=formal_charge,
        multiplicity=mult,
        symbols=symbols,
        coords=coords,
        source="sketch",
    )
    m.save()
    return m


def _resolve_name_to_smiles(name: str) -> tuple[str, str]:
    """Try PubChem first (common/IUPAC names), then OPSIN (systematic IUPAC names).

    Returns (smiles, resolved_name).
    """
    try:
        import socket

        import pubchempy as pcp
        # pubchempy's request() calls urllib.request.urlopen() with no
        # timeout argument at all (confirmed by reading its source) -- it
        # offers no way to pass one in, so this scopes Python's process-wide
        # socket default timeout around just this call and always restores
        # it afterward, even on an exception. Without this, a stalled/
        # unreachable PubChem endpoint blocks forever, and since this runs
        # inside a tool call holding _graph_lock (see MOLECULE_LOOKUP_TIMEOUT's
        # comment in config.py), that hang is not just this lookup -- it's
        # every open conversation's chat turns and job approvals until the
        # backend is restarted.
        #
        # socket.setdefaulttimeout() is process-wide state, not scoped to
        # this thread or call -- a real, if narrow, side effect to be aware
        # of. It only affects sockets *created* while it's set (already-open
        # connections are unaffected), and every other outbound client in
        # this app already passes its own explicit timeout (requests'
        # `timeout=` for OPSIN/Semantic Scholar/web scraping, httpx's for
        # Ollama), so in practice nothing else in this process is exposed to
        # this override. Confirmed this is also sufficient, not just
        # narrow: pubchempy's get() has a separate unbounded
        # `while "Waiting" in status: time.sleep(2)` polling loop for
        # asynchronous searches, but it's only reached when
        # `(searchtype and searchtype != "xref") or namespace == "formula"`
        # -- get_compounds(name, "name") passes searchtype=None, so it always
        # takes the single-request branch; one socket, one timeout, the
        # whole call is bounded. (A future caller switching this to a
        # formula/similarity search would need to re-check that.)
        from app.config import MOLECULE_LOOKUP_TIMEOUT
        previous_timeout = socket.getdefaulttimeout()
        socket.setdefaulttimeout(MOLECULE_LOOKUP_TIMEOUT)
        try:
            hits = pcp.get_compounds(name, "name")
        finally:
            socket.setdefaulttimeout(previous_timeout)
        if hits:
            c = hits[0]
            resolved_name = (c.iupac_name or name)
            # pubchempy's `canonical_smiles` is deprecated (PubChem renamed
            # the underlying property) and emits a DeprecationWarning on
            # every molecule resolution -- which is the first tool call of
            # almost every conversation. `connectivity_smiles` is its
            # replacement; getattr keeps an older pubchempy working rather
            # than pinning a floor version for one attribute rename.
            smiles = getattr(c, "connectivity_smiles", None) or c.canonical_smiles
            return smiles, resolved_name
    except Exception:
        pass

    try:
        import requests
        resp = requests.get(
            f"https://opsin.ch.cam.ac.uk/opsin/{name}.smi", timeout=10
        )
        if resp.status_code == 200 and resp.text.strip():
            return resp.text.strip(), name
    except Exception:
        pass

    # F-003: this used to end with "Please supply a SMILES string instead."
    # unconditionally, which was actively misleading in the case that
    # brought users here most often -- a SMILES string that the old
    # charset gate in looks_like_smiles had wrongly rejected, sending it
    # down the name-lookup path. The user was told to supply the exact
    # thing they had just supplied. The gate is fixed, but the advice is
    # now conditioned on what was actually received either way: RDKit is
    # the authority on whether this text is parseable as a structure, so
    # ask it rather than guessing from the message we happen to be in.
    looks_structural = " " not in name.strip()
    if looks_structural and Chem.MolFromSmiles(name.strip()) is None:
        hint = (
            f"'{name}' contains no spaces, so it may have been intended as a SMILES "
            "string, but RDKit cannot parse it as one either. Check it for a typo, or "
            "supply the geometry directly as an XYZ block."
        )
    else:
        hint = (
            "Supply a SMILES string (e.g. 'CCO' for ethanol) or paste the geometry "
            "directly as an XYZ block instead."
        )
    raise ValueError(
        f"Could not resolve '{name}' to a structure via PubChem or OPSIN. {hint}"
    )


def molecule_from_name(name: str, charge: int | None = None, multiplicity: int | None = None) -> Molecule:
    smiles, _resolved_name = _resolve_name_to_smiles(name)
    m = molecule_from_smiles(smiles, name=name, charge=charge, multiplicity=multiplicity)
    m.identifier = name
    m.source = "pubchem"
    m.save()
    return m


_ATOM_LINE_RE = re.compile(
    r"^\s*([A-Za-z]{1,3})\s+(-?\d+\.?\d*(?:[eE][+-]?\d+)?)\s+"
    r"(-?\d+\.?\d*(?:[eE][+-]?\d+)?)\s+(-?\d+\.?\d*(?:[eE][+-]?\d+)?)\s*$"
)


def _looks_like_xyz_block(text: str) -> bool:
    """True for a pasted XYZ/xmol-format coordinate block: either a proper
    xmol file (an atom-count line, a comment line, then one "Symbol x y z"
    line per atom) or a bare block of just the atom lines with no header.
    Checked in resolve_molecule() before the SMILES/name-lookup branches,
    since a multi-line coordinate block would otherwise fail SMILES's
    single-token heuristic and then fail (or worse, spuriously succeed
    against) a PubChem/OPSIN name lookup of the literal pasted text."""
    lines = [ln for ln in text.splitlines() if ln.strip()]
    if len(lines) < 2:
        return False
    body = lines
    if lines[0].strip().isdigit():
        # A real xmol header's second line is a free-text comment, which
        # must NOT itself look like an atom line -- otherwise a genuine
        # 1-atom body ("1\nFe\nFe 0 0 0") would be misread as "count=1,
        # comment=<the only atom line>, zero atoms follow".
        has_comment = not _ATOM_LINE_RE.match(lines[1])
        body = lines[2:] if has_comment else lines[1:]
    matching = sum(1 for ln in body if _ATOM_LINE_RE.match(ln))
    return matching >= 2 and matching == len(body)


def _molecular_formula(symbols: list[str]) -> str:
    """Hill order: Carbon first, then Hydrogen, then everything else
    alphabetically -- used as a fallback display name for a pasted geometry
    with no usable comment line to name it after."""
    counts = Counter(symbols)
    order = [s for s in ("C", "H") if s in counts] + sorted(s for s in counts if s not in ("C", "H"))
    return "".join(f"{s}{counts[s] if counts[s] > 1 else ''}" for s in order)


def molecule_from_xyz_block(text: str, charge: int | None = None, multiplicity: int | None = None) -> Molecule:
    """Parses a pasted XYZ/xmol-format coordinate block directly -- no name
    or SMILES lookup involved, since the geometry is already fully
    specified by the user. Accepts both a proper xmol file (count + comment
    + atom lines) and a bare block of just atom lines, synthesizing the
    header Chem.MolFromXYZBlock expects in the latter case. Bond/SMILES
    perception is best-effort: a geometry RDKit can't confidently assign
    bonds to (e.g. an unusual transition-metal complex) is still fully
    usable for a QC job on its coordinates alone, so failure there doesn't
    block resolution -- it just leaves `smiles` empty.
    """
    lines = [ln for ln in text.splitlines() if ln.strip()]
    comment = ""
    if lines[0].strip().isdigit():
        has_comment = len(lines) >= 2 and not _ATOM_LINE_RE.match(lines[1])
        comment = lines[1].strip() if has_comment else ""
        body = lines[2:] if has_comment else lines[1:]
    else:
        body = lines
    xmol_text = "\n".join([str(len(body)), comment, *body])

    mol = Chem.MolFromXYZBlock(xmol_text)
    if mol is None:
        raise ValueError("Could not parse this as an XYZ/xmol coordinate block")

    formal_charge = charge if charge is not None else 0
    smiles = ""
    try:
        from rdkit.Chem import rdDetermineBonds
        mol_with_bonds = Chem.Mol(mol)
        rdDetermineBonds.DetermineBonds(mol_with_bonds, charge=formal_charge)
        smiles = Chem.MolToSmiles(mol_with_bonds)
    except Exception:
        pass

    conf = mol.GetConformer()
    symbols = [atom.GetSymbol() for atom in mol.GetAtoms()]
    coords = [
        [conf.GetAtomPosition(i).x, conf.GetAtomPosition(i).y, conf.GetAtomPosition(i).z]
        for i in range(mol.GetNumAtoms())
    ]

    is_numeric_comment = bool(comment) and comment.replace(".", "", 1).replace("-", "", 1).isdigit()
    name = comment if comment and not is_numeric_comment else _molecular_formula(symbols)
    mult = multiplicity if multiplicity is not None else 1

    m = Molecule(
        identifier=text,
        name=name,
        smiles=smiles,
        charge=formal_charge,
        multiplicity=mult,
        symbols=symbols,
        coords=coords,
        source="xyz_paste",
    )
    m.save()
    return m


def looks_like_smiles(text: str) -> bool:
    """Is `text` a SMILES string? Decided by RDKit's own parser, not by a
    character-set guess.

    F-003 fix. This used to pre-filter on a hardcoded `allowed` set built
    from the organic subset -- "BCNOPSFIHKcnosp" plus punctuation -- and
    return False on any character outside it. That set contains only the
    FIRST letter of a two-letter element symbol, so it rejected the second
    letter of every one of them: Cl, Br, Si, Na, Fe, Mg, Zn and so on. No
    halogen or metal SMILES could pass the gate at all, and since the gate
    ran BEFORE the `Chem.MolFromSmiles` call on the very next line, the
    parser that would have accepted them was never reached. `CCl` was
    treated as a compound name and shipped to PubChem; `[Na+].[Cl-]` too.

    RDKit is the authority on what it can parse, so it decides. The
    whitespace guard stays -- it cheaply rejects prose ("water", "acetic
    acid") before a parse attempt, and no valid SMILES contains a space.
    Anything else is handed straight to the parser: a name RDKit happens
    to parse (a bare "C" is methane either way) resolves identically
    through both paths, and a name it rejects falls through to the
    PubChem lookup exactly as before.
    """
    text = text.strip()
    if not text or " " in text:
        return False
    return Chem.MolFromSmiles(text) is not None


def resolve_molecule(text: str, charge: int | None = None, multiplicity: int | None = None) -> Molecule:
    text = text.strip()
    if _looks_like_xyz_block(text):
        return molecule_from_xyz_block(text, charge=charge, multiplicity=multiplicity)
    if looks_like_smiles(text):
        return molecule_from_smiles(text, charge=charge, multiplicity=multiplicity)
    return molecule_from_name(text, charge=charge, multiplicity=multiplicity)


