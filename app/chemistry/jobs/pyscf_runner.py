"""PySCF calculation backends: single-point, optimization, frequencies,
CASSCF, TDDFT, MO cube generation, and internal-coordinate PES scans.

Every `run_*` function takes plain-dict `molecule`/`params` (JSON-safe, as
they arrive from the agent/worker subprocess) and returns a dict with
`summary` (engine-agnostic key results) and `artifacts` (named file paths),
matching `JobResult`. Results come straight from PySCF's own Python
objects/attributes rather than parsing text output.
"""
from __future__ import annotations

import copy
import os

import numpy as np
from pyscf import gto, scf, dft, mcscf, tdscf
from pyscf.tools import cubegen
from pyscf.hessian import thermo as pyscf_thermo

from app.config import MAX_MEMORY_MB, N_CORES

os.environ.setdefault("OMP_NUM_THREADS", str(N_CORES))


def build_mole(molecule: dict, basis: str) -> gto.Mole:
    atom = [(sym, tuple(xyz)) for sym, xyz in zip(molecule["symbols"], molecule["coords"])]
    mol = gto.Mole()
    mol.atom = atom
    mol.unit = "Angstrom"
    mol.basis = basis
    mol.charge = molecule["charge"]
    mol.spin = molecule["multiplicity"] - 1  # pyscf wants 2S, i.e. n_alpha - n_beta
    mol.max_memory = MAX_MEMORY_MB
    mol.verbose = 3  # per-job log; 4+ is very chatty (prints every SCF cycle) and bloats worker.log fast
    mol.build()
    return mol


def build_mf(mol: gto.Mole, method: str, functional: str | None):
    restricted = mol.spin == 0
    if method.lower() == "hf":
        mf = scf.RHF(mol) if restricted else scf.ROHF(mol)
    elif method.lower() == "dft":
        if not functional:
            raise ValueError("DFT requires a 'functional' parameter, e.g. 'b3lyp'")
        mf = dft.RKS(mol) if restricted else dft.ROKS(mol)
        mf.xc = functional
    else:
        raise ValueError(f"Unsupported method '{method}' for PySCF (use 'hf' or 'dft')")
    return mf


def molecule_from_mol(mol: gto.Mole, template: dict) -> dict:
    coords_bohr = mol.atom_coords()
    coords_ang = (coords_bohr * 0.52917721067).tolist()
    out = dict(template)
    out["symbols"] = [mol.atom_symbol(i) for i in range(mol.natm)]
    out["coords"] = coords_ang
    return out


def run_single_point(molecule: dict, params: dict) -> dict:
    mol = build_mole(molecule, params["basis"])
    mf = build_mf(mol, params["method"], params.get("functional"))
    energy = mf.kernel()
    if not mf.converged:
        raise RuntimeError("SCF did not converge; try a different initial guess or check the input")

    summary = {
        "energy_hartree": float(energy),
        "converged": bool(mf.converged),
        "method": params["method"],
        "functional": params.get("functional"),
        "basis": params["basis"],
        "homo_lumo_gap_eV": _homo_lumo_gap(mf),
        "dipole_debye": list(mf.dip_moment(unit="Debye", verbose=0)),
    }
    return {"summary": summary, "artifacts": {}}


def run_geometry_optimization(molecule: dict, params: dict) -> dict:
    from pyscf.geomopt.geometric_solver import optimize

    mol = build_mole(molecule, params["basis"])
    mf = build_mf(mol, params["method"], params.get("functional"))
    mol_eq = optimize(mf, maxsteps=params.get("max_steps", 100))

    mf_final = build_mf(mol_eq, params["method"], params.get("functional"))
    energy = mf_final.kernel()

    optimized_molecule = molecule_from_mol(mol_eq, molecule)
    summary = {
        "final_energy_hartree": float(energy),
        "converged": bool(mf_final.converged),
        "optimized_molecule": optimized_molecule,
    }
    return {"summary": summary, "artifacts": {}}


def run_frequency(molecule: dict, params: dict) -> dict:
    mol = build_mole(molecule, params["basis"])
    mf = build_mf(mol, params["method"], params.get("functional"))
    mf.kernel()
    if not mf.converged:
        raise RuntimeError("SCF did not converge before frequency analysis")

    hess = mf.Hessian().kernel()
    freq_info = pyscf_thermo.harmonic_analysis(mol, hess)
    thermo_info = pyscf_thermo.thermo(mf, freq_info["freq_au"], params.get("temperature_K", 298.15))

    freqs_cm1 = np.real(freq_info["freq_wavenumber"]).tolist()
    n_imaginary = int(np.sum(np.array(freqs_cm1) < 0))

    summary = {
        "frequencies_cm-1": freqs_cm1,
        "n_imaginary_frequencies": n_imaginary,
        "zero_point_energy_hartree": float(thermo_info["ZPE"][0]),
        "enthalpy_hartree": float(thermo_info["H_tot"][0]),
        "gibbs_free_energy_hartree": float(thermo_info["G_tot"][0]),
        "entropy_hartree_per_K": float(thermo_info["S_tot"][0]),
        "temperature_K": params.get("temperature_K", 298.15),
        "normal_modes": freq_info["norm_mode"].tolist(),
    }
    return {"summary": summary, "artifacts": {}}


def run_casscf(molecule: dict, params: dict) -> dict:
    mol = build_mole(molecule, params["basis"])
    restricted = mol.spin == 0
    mf = scf.RHF(mol) if restricted else scf.ROHF(mol)
    mf.kernel()

    n_orb = params["active_orbitals"]
    n_elec = params["active_electrons"]
    n_states = params.get("n_states", 1)

    mc = mcscf.CASSCF(mf, n_orb, n_elec)
    if n_states > 1:
        weights = params.get("weights") or [1.0 / n_states] * n_states
        mc = mc.state_average_(weights)
    mc.kernel()

    energies = np.atleast_1d(mc.e_states if hasattr(mc, "e_states") and n_states > 1 else mc.e_tot).tolist()
    summary = {
        "casscf_energy_hartree": float(mc.e_tot) if n_states == 1 else None,
        "state_energies_hartree": energies if n_states > 1 else [float(mc.e_tot)],
        "active_electrons": n_elec,
        "active_orbitals": n_orb,
        "n_states": n_states,
        "converged": bool(mc.converged),
        "reference_hf_energy_hartree": float(mf.e_tot),
    }
    return {"summary": summary, "artifacts": {}}


def run_tddft(molecule: dict, params: dict) -> dict:
    mol = build_mole(molecule, params["basis"])
    functional = params.get("functional", "b3lyp")
    mf = build_mf(mol, "dft", functional)
    mf.kernel()
    if not mf.converged:
        raise RuntimeError("Ground-state SCF did not converge before TDDFT")

    n_states = params["n_states"]
    td = tdscf.TDA(mf) if params.get("use_tda", True) else tdscf.TDDFT(mf)
    td.singlet = params.get("singlet_only", True)
    td.nstates = n_states
    excitation_energies = td.kernel()[0]

    ev = (np.array(excitation_energies) * 27.211386245988).tolist()
    nm = [1239.841984 / e if e > 0 else None for e in ev]
    try:
        osc = td.oscillator_strength().tolist()
    except Exception:
        osc = [None] * len(ev)

    summary = {
        "ground_state_energy_hartree": float(mf.e_tot),
        "excitation_energies_eV": ev,
        "excitation_wavelengths_nm": nm,
        "oscillator_strengths": osc,
        "n_states": n_states,
        "functional": functional,
    }
    return {"summary": summary, "artifacts": {}}


def run_mo_visualization(molecule: dict, params: dict) -> dict:
    mol = build_mole(molecule, params["basis"])
    mf = build_mf(mol, params["method"], params.get("functional"))
    mf.kernel()
    if not mf.converged:
        raise RuntimeError("SCF did not converge before MO generation")

    homo_idx = int(np.sum(mf.mo_occ > 0)) - 1  # 0-based
    indices = _resolve_orbital_indices(params["orbital_indices"], homo_idx, mf.mo_coeff.shape[1])

    job_dir = params["_job_dir"]
    cube_paths = {}
    for label, idx in indices.items():
        path = os.path.join(job_dir, f"mo_{label}.cube")
        cubegen.orbital(mol, path, mf.mo_coeff[:, idx])
        cube_paths[label] = path

    summary = {
        "homo_index_1based": homo_idx + 1,
        "orbitals_rendered": {label: idx + 1 for label, idx in indices.items()},
        "mo_energies_eV": {label: float(mf.mo_energy[idx] * 27.211386245988) for label, idx in indices.items()},
    }
    return {"summary": summary, "artifacts": {"cubes": cube_paths}}


def run_pes_scan(molecule: dict, params: dict) -> dict:
    coordinate = params["coordinate"]
    n_points = params["n_points"]
    scan_range = params.get("scan_range")

    if "end_molecule" in params and params["end_molecule"]:
        geometries = _liic_cartesian(molecule, params["end_molecule"], n_points)
        coord_values = list(np.linspace(0.0, 1.0, n_points))
        coord_label = "interpolation_fraction"
    else:
        if scan_range is None:
            raise ValueError("pes_scan needs either 'end_molecule' or a 'scan_range' [start, stop]")
        geometries, coord_values = _internal_coordinate_scan(molecule, coordinate, scan_range, n_points)
        coord_label = f"{coordinate['type']}({','.join(str(a) for a in coordinate['atoms'])})"

    energies = []
    for geom in geometries:
        mol = build_mole(geom, params["basis"])
        mf = build_mf(mol, params["method"], params.get("functional"))
        e = mf.kernel()
        energies.append(float(e) if mf.converged else None)

    summary = {
        "coordinate": coord_label,
        "coordinate_values": [float(v) for v in coord_values],
        "energies_hartree": energies,
        "n_points": n_points,
        "relative_energies_kcal_mol": [
            (e - min(x for x in energies if x is not None)) * 627.5094740631 if e is not None else None
            for e in energies
        ],
    }
    return {"summary": summary, "artifacts": {"geometries": geometries}}


# --- helpers -----------------------------------------------------------

def _homo_lumo_gap(mf) -> float | None:
    occ = np.asarray(mf.mo_occ)
    energies = np.asarray(mf.mo_energy)
    occupied = energies[occ > 0]
    virtual = energies[occ == 0]
    if len(occupied) == 0 or len(virtual) == 0:
        return None
    return float((virtual.min() - occupied.max()) * 27.211386245988)


def _resolve_orbital_indices(spec, homo_idx: int, n_mo: int) -> dict[str, int]:
    if isinstance(spec, str):
        spec = [spec]
    out = {}
    for item in spec:
        item_str = str(item).strip().upper()
        if item_str == "HOMO":
            out["HOMO"] = homo_idx
        elif item_str == "LUMO":
            out["LUMO"] = homo_idx + 1
        elif item_str.startswith("HOMO-"):
            k = int(item_str.split("-")[1])
            out[item_str] = homo_idx - k
        elif item_str.startswith("LUMO+"):
            k = int(item_str.split("+")[1])
            out[item_str] = homo_idx + 1 + k
        else:
            idx = int(item_str) - 1  # user gives 1-based
            out[str(idx + 1)] = idx
    for label, idx in out.items():
        if idx < 0 or idx >= n_mo:
            raise ValueError(f"Orbital '{label}' (index {idx + 1}) is out of range for this system (1..{n_mo})")
    return out


def _rwmol_with_perceived_bonds(molecule: dict):
    """Build an RDKit RWMol with a conformer from raw symbols/coords and
    infer connectivity from interatomic distances (rdMolTransforms needs an
    actual bond graph to know which fragment moves for a bond/angle/dihedral
    change)."""
    from rdkit import Chem
    from rdkit.Chem import rdDetermineBonds

    rw = Chem.RWMol()
    for sym in molecule["symbols"]:
        rw.AddAtom(Chem.Atom(sym))
    conf = Chem.Conformer(len(molecule["symbols"]))
    for i, xyz in enumerate(molecule["coords"]):
        conf.SetAtomPosition(i, tuple(xyz))
    rw.AddConformer(conf)
    mol_rw = rw.GetMol()
    rdDetermineBonds.DetermineConnectivity(mol_rw)
    Chem.GetSSSR(mol_rw)  # rdMolTransforms needs ring info even without bond orders assigned
    return Chem.RWMol(mol_rw)


def _internal_coordinate_scan(molecule: dict, coordinate: dict, scan_range: list[float], n_points: int):
    from rdkit.Chem import rdMolTransforms

    coord_type = coordinate["type"]
    atoms = coordinate["atoms"]
    values = np.linspace(scan_range[0], scan_range[1], n_points)

    geometries = []
    for val in values:
        mol_rw = _rwmol_with_perceived_bonds(molecule)
        conf = mol_rw.GetConformer()

        if coord_type == "bond":
            rdMolTransforms.SetBondLength(conf, atoms[0], atoms[1], float(val))
        elif coord_type == "angle":
            rdMolTransforms.SetAngleDeg(conf, atoms[0], atoms[1], atoms[2], float(val))
        elif coord_type == "dihedral":
            rdMolTransforms.SetDihedralDeg(conf, atoms[0], atoms[1], atoms[2], atoms[3], float(val))
        else:
            raise ValueError(f"Unsupported coordinate type '{coord_type}' (use bond/angle/dihedral)")

        new_coords = [list(conf.GetAtomPosition(i)) for i in range(mol_rw.GetNumAtoms())]
        geom = dict(molecule)
        geom["coords"] = new_coords
        geometries.append(geom)

    return geometries, values


def _liic_cartesian(start: dict, end: dict, n_points: int):
    """Linear interpolation of Cartesian coordinates between two endpoint
    geometries (a practical approximation to full internal-coordinate LIIC,
    valid for connected scans between structurally similar endpoints)."""
    start_c = np.array(start["coords"])
    end_c = np.array(end["coords"])
    if start_c.shape != end_c.shape:
        raise ValueError("Start and end geometries must have the same atoms in the same order")

    geometries = []
    for frac in np.linspace(0.0, 1.0, n_points):
        interp = (1 - frac) * start_c + frac * end_c
        geom = dict(start)
        geom["coords"] = interp.tolist()
        geometries.append(geom)
    return geometries
