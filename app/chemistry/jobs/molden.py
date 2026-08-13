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
            "occupancy": float(occ),
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
