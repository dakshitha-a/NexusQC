"""Resolve a user-supplied molecule (name or SMILES) into a 3D structure."""
from __future__ import annotations

import hashlib
import json
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


def _resolve_name_to_smiles(name: str) -> tuple[str, str]:
    """Try PubChem first (common/IUPAC names), then OPSIN (systematic IUPAC names).

    Returns (smiles, resolved_name).
    """
    try:
        import pubchempy as pcp
        hits = pcp.get_compounds(name, "name")
        if hits:
            c = hits[0]
            resolved_name = (c.iupac_name or name)
            return c.canonical_smiles, resolved_name
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

    raise ValueError(
        f"Could not resolve '{name}' to a structure via PubChem or OPSIN. "
        "Please supply a SMILES string instead."
    )


def molecule_from_name(name: str, charge: int | None = None, multiplicity: int | None = None) -> Molecule:
    smiles, _resolved_name = _resolve_name_to_smiles(name)
    m = molecule_from_smiles(smiles, name=name, charge=charge, multiplicity=multiplicity)
    m.identifier = name
    m.source = "pubchem"
    m.save()
    return m


def looks_like_smiles(text: str) -> bool:
    """Heuristic: SMILES uses a small, specific character set and no spaces."""
    text = text.strip()
    if not text or " " in text:
        return False
    allowed = set("BCNOPSFIHKcnosp0123456789()[]=#@+-\\/.%")
    if not all(ch in allowed for ch in text):
        return False
    return Chem.MolFromSmiles(text) is not None


def resolve_molecule(text: str, charge: int | None = None, multiplicity: int | None = None) -> Molecule:
    text = text.strip()
    if looks_like_smiles(text):
        return molecule_from_smiles(text, charge=charge, multiplicity=multiplicity)
    return molecule_from_name(text, charge=charge, multiplicity=multiplicity)


_BOND_TYPE = {1: Chem.BondType.SINGLE, 2: Chem.BondType.DOUBLE, 3: Chem.BondType.TRIPLE}


def _rwmol_from_builder(symbols: list[str], bonds: list[tuple[int, int, int]]) -> Chem.RWMol:
    rw = Chem.RWMol()
    for sym in symbols:
        rw.AddAtom(Chem.Atom(sym))
    for i, j, order in bonds:
        rw.AddBond(i, j, _BOND_TYPE.get(order, Chem.BondType.SINGLE))
    return rw


def cleanup_geometry(symbols: list[str], coords: list[list[float]],
                      bonds: list[tuple[int, int, int]], charge: int = 0) -> list[list[float]]:
    """MM-idealizes a molecule-builder structure: the builder UI already
    knows the explicit bonds (and their orders) from the user's add/delete
    actions, so this skips bond *perception* entirely (unlike
    _rwmol_with_perceived_bonds in pyscf_runner.py, which infers bonds from
    distances because it has no explicit bond list to work with) and goes
    straight to sanitization + the same MMFF->UFF fallback chain _embed_3d
    uses, just starting from existing coordinates instead of a fresh SMILES
    embed. Raises ValueError (with a message safe to show the user) if the
    structure's valences don't sanitize -- e.g. an atom the user hasn't
    finished bonding yet -- rather than silently returning something wrong.
    """
    rw = _rwmol_from_builder(symbols, bonds)
    conf = Chem.Conformer(len(symbols))
    for i, xyz in enumerate(coords):
        conf.SetAtomPosition(i, tuple(xyz))
    rw.AddConformer(conf)
    mol = rw.GetMol()
    try:
        Chem.SanitizeMol(mol)
    except Exception as e:
        raise ValueError(
            f"Couldn't clean up this structure -- it has an invalid valence somewhere "
            f"(finish bonding every atom first): {e}"
        )
    try:
        AllChem.MMFFOptimizeMolecule(mol, maxIters=2000)
    except Exception:
        try:
            AllChem.UFFOptimizeMolecule(mol, maxIters=2000)
        except Exception:
            pass  # keep the sanitized-but-unoptimized geometry rather than failing outright
    conf = mol.GetConformer()
    return [[conf.GetAtomPosition(i).x, conf.GetAtomPosition(i).y, conf.GetAtomPosition(i).z]
            for i in range(mol.GetNumAtoms())]


def molecule_from_builder(symbols: list[str], coords: list[list[float]],
                           bonds: list[tuple[int, int, int]],
                           charge: int = 0, multiplicity: int = 1,
                           name: str = "built molecule") -> Molecule:
    """Turns a molecule-builder structure into a Molecule. SMILES is
    derived via sanitization + Chem.MolToSmiles when the structure's
    valences are coherent; falls back to a clear placeholder (rather than
    leaving the field empty/absent) when they aren't -- render_molecule_panel
    and cache_key() both assume `smiles` is always a usable string, and a
    partially-built structure (e.g. an atom with an unsatisfied valence the
    user hasn't finished bonding) is a normal, expected state here, not an
    error worth raising over.
    """
    smiles = "<no SMILES: structure has unfinished/invalid valences>"
    try:
        mol = _rwmol_from_builder(symbols, bonds).GetMol()
        Chem.SanitizeMol(mol)
        smiles = Chem.MolToSmiles(mol)
    except Exception:
        pass
    m = Molecule(
        identifier=name, name=name, smiles=smiles, charge=charge, multiplicity=multiplicity,
        symbols=symbols, coords=coords, source="builder",
    )
    m.save()
    return m
