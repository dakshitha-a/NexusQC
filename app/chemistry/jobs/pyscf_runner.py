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


def _mole_lines(molecule: dict, basis: str) -> list[str]:
    atom_lines = "\n".join(
        f"{sym:2s} {x: .8f} {y: .8f} {z: .8f}" for sym, (x, y, z) in zip(molecule["symbols"], molecule["coords"])
    )
    return [
        "mol = gto.Mole()",
        f"mol.atom = '''\n{atom_lines}\n'''",
        f"mol.basis = {basis!r}",
        f"mol.charge = {molecule['charge']}",
        f"mol.spin = {molecule['multiplicity'] - 1}  # 2S = n_alpha - n_beta",
        "mol.build()",
    ]


def _mf_lines(method: str, functional: str | None) -> list[str]:
    if method.lower() == "hf":
        return ["mf = scf.RHF(mol) if mol.spin == 0 else scf.ROHF(mol)"]
    if method.lower() == "dft":
        return [
            "mf = dft.RKS(mol) if mol.spin == 0 else dft.ROKS(mol)",
            f"mf.xc = {functional!r}",
        ]
    raise ValueError(f"Unsupported method '{method}' for PySCF (use 'hf' or 'dft')")


def build_input_preview(job_type: str, molecule: dict, params: dict) -> str:
    """A PySCF driver script equivalent to what run_<job_type> below will
    actually execute -- PySCF has no literal input-file format (it's a
    Python API), so this is the closest honest equivalent of "the input"
    for approval purposes."""
    basis = params.get("basis")
    method = params.get("method", "hf")
    functional = params.get("functional")
    lines = ["from pyscf import gto, scf, dft, mcscf, tdscf", ""]
    lines += _mole_lines(molecule, basis)
    lines.append("")

    if job_type == "single_point":
        lines += _mf_lines(method, functional)
        lines.append("energy = mf.kernel()")
    elif job_type == "geometry_optimization":
        lines += _mf_lines(method, functional)
        lines.append("from pyscf.geomopt.geometric_solver import optimize")
        lines.append(f"mol_eq = optimize(mf, maxsteps={params.get('max_steps', 100)})")
    elif job_type == "frequency":
        lines += _mf_lines(method, functional)
        lines.append("mf.kernel()")
        lines.append("hess = mf.Hessian().kernel()")
        lines.append("from pyscf.hessian import thermo")
        lines.append("freq_info = thermo.harmonic_analysis(mol, hess)")
        lines.append(f"thermo_info = thermo.thermo(mf, freq_info['freq_au'], {params.get('temperature_K', 298.15)})")
    elif job_type == "casscf":
        n_states = params.get("n_states", 1)
        lines.append("mf = scf.RHF(mol) if mol.spin == 0 else scf.ROHF(mol)")
        lines.append("mf.kernel()")
        lines.append(f"mc = mcscf.CASSCF(mf, {params['active_orbitals']}, {params['active_electrons']})")
        if n_states > 1:
            weights = params.get("weights") or [1.0 / n_states] * n_states
            lines.append(f"mc = mc.state_average_({weights})")
        lines.append("mc.kernel()")
        if params.get("want_oscillator_strengths"):
            lines.append("# NOTE: PySCF's CASSCF path here does not compute oscillator strengths;")
            lines.append("# use engine='orca' (adds DoDipoleLength) for UV/Vis intensities")
    elif job_type == "tddft":
        td_method = params.get("method", "dft")
        td_functional = functional or "b3lyp" if td_method == "dft" else None
        lines += _mf_lines(td_method, td_functional)
        lines.append("mf.kernel()")
        use_tda = params.get("use_tda", True)
        note = "CIS" if (td_method == "hf" and use_tda) else "TD-HF/RPA" if td_method == "hf" else None
        if note:
            lines.append(f"# an HF reference here makes this {note}, not DFT-based TDA/TDDFT")
        lines.append("td = tdscf.TDA(mf)" if use_tda else "td = tdscf.TDDFT(mf)")
        lines.append(f"td.singlet = {params.get('singlet_only', True)}")
        lines.append(f"td.nstates = {params['n_states']}")
        lines.append("excitation_energies = td.kernel()[0]")
    elif job_type == "eom_ccsd":
        lines.append("mf = scf.RHF(mol)")
        lines.append("mf.kernel()")
        lines.append("from pyscf import cc")
        lines.append("from pyscf.cc.eom_rccsd import EOMEESinglet")
        lines.append("mycc = cc.CCSD(mf)")
        lines.append("mycc.kernel()")
        lines.append("eom = EOMEESinglet(mycc)")
        lines.append(f"e, c = eom.kernel(nroots={params.get('n_states', 1)})")
        lines.append("# energies only -- PySCF's EOM-CCSD has no built-in oscillator strengths;")
        lines.append("# use engine='orca' for intensities at this level of theory")
    elif job_type == "mo_visualization":
        lines += _mf_lines(method, functional)
        lines.append("mf.kernel()")
        lines.append("from pyscf.tools import cubegen")
        lines.append(f"# orbitals to render: {params.get('orbital_indices')} (isoval={params.get('isoval', 0.04)})")
        lines.append("cubegen.orbital(mol, 'mo_<label>.cube', mf.mo_coeff[:, <index>])")
    elif job_type == "pes_scan":
        coordinate = params.get("coordinate")
        n_points = params.get("n_points")
        if coordinate:
            lines.append(
                f"# scan {coordinate['type']}(atoms={coordinate['atoms']}) over "
                f"{params.get('scan_range')}, {n_points} points"
            )
        else:
            lines.append(f"# linear interpolation between the given endpoint geometries, {n_points} points")
        lines += _mf_lines(method, functional)
        lines.append("# mf.kernel() evaluated at each scan point above")
    else:
        raise ValueError(f"Unsupported job_type '{job_type}' for PySCF")

    return "\n".join(lines)


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

    # geomeTRIC's PySCFEngine calls callback(locals()) once per optimization
    # cycle from inside calc_new(), with an 'energy' key already computed
    # for that step's geometry (verified by reading geometric_solver.py's
    # PySCFEngine.calc_new -- no public API exposes this after the fact,
    # so it must be captured live during optimize() or not at all).
    energies_per_step: list[float] = []

    def _capture_energy(local_vars: dict) -> None:
        energies_per_step.append(float(local_vars["energy"]))

    mol_eq = optimize(mf, maxsteps=params.get("max_steps", 100), callback=_capture_energy)

    mf_final = build_mf(mol_eq, params["method"], params.get("functional"))
    energy = mf_final.kernel()

    optimized_molecule = molecule_from_mol(mol_eq, molecule)
    summary = {
        "final_energy_hartree": float(energy),
        "converged": bool(mf_final.converged),
        "optimized_molecule": optimized_molecule,
        "optimization_energies_hartree": energies_per_step,
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


def _homo_lumo_label(occ_idx: int, virt_idx: int, nocc: int) -> str:
    """occ_idx/virt_idx are 0-based absolute MO indices spanning the same
    per-spin window td.xy reports amplitudes over (occ_idx in [0, nocc),
    virt_idx in [nocc, nmo)) -- converts to the HOMO/LUMO-relative labels
    already used elsewhere in this app (PARAM_HELP's orbital_indices)."""
    n_below_homo = nocc - 1 - occ_idx
    occ_label = "HOMO" if n_below_homo == 0 else f"HOMO-{n_below_homo}"
    n_above_lumo = virt_idx - nocc
    virt_label = "LUMO" if n_above_lumo == 0 else f"LUMO+{n_above_lumo}"
    return f"{occ_label} -> {virt_label}"


def _dominant_transition(x, nelec: tuple[int, int]) -> str | None:
    """Largest-|amplitude| (occ, virt) pair from a td.xy[state][0] (X)
    amplitude array -- Y (de-excitation amplitudes) is ignored, exact for
    TDA (where Y=0) and a standard approximation for full TDDFT/RPA where
    X dominates. `x` is a plain (nocc, nvirt) array for a restricted
    reference, or a (alpha, beta) tuple of such arrays for ROHF/ROKS
    (verified empirically: tdscf.TDA on an ROHF reference returns per-spin
    X arrays with different occ/virt counts per channel, not one combined
    array)."""
    if isinstance(x, tuple):
        candidates = []
        for spin, xs in enumerate(x):
            xarr = np.asarray(xs)
            if xarr.size == 0:
                continue
            idx = np.unravel_index(np.argmax(np.abs(xarr)), xarr.shape)
            candidates.append((abs(xarr[idx]), spin, idx))
        if not candidates:
            return None
        _amp, spin, (occ_i, virt_i) = max(candidates, key=lambda c: c[0])
        nocc = nelec[spin]
        label = _homo_lumo_label(occ_i, virt_i + nocc, nocc)
        return f"{label} ({'α' if spin == 0 else 'β'})"

    xarr = np.asarray(x)
    if xarr.size == 0:
        return None
    nocc = xarr.shape[0]
    occ_i, virt_i = np.unravel_index(np.argmax(np.abs(xarr)), xarr.shape)
    return _homo_lumo_label(int(occ_i), int(virt_i) + nocc, nocc)


def run_tddft(molecule: dict, params: dict) -> dict:
    """method='dft' (the common case) gives TDA/TDDFT on a KS reference;
    method='hf' gives CIS (TDA on an HF reference) or TD-HF/RPA (TDDFT on
    an HF reference) instead -- tdscf.TDA/TDDFT are dispatchers that pick
    the right concrete implementation from the reference type, and an HF
    reference has no XC kernel, so TDA-on-HF *is* CIS (verified against a
    real ORCA CIS run on water/STO-3G: energies and oscillator strengths
    agree to 5 decimal places)."""
    mol = build_mole(molecule, params["basis"])
    method = params.get("method", "dft")
    functional = params.get("functional", "b3lyp") if method == "dft" else None
    mf = build_mf(mol, method, functional)
    mf.kernel()
    if not mf.converged:
        raise RuntimeError("Ground-state SCF did not converge before TDDFT/CIS")

    n_states = params["n_states"]
    use_tda = params.get("use_tda", True)
    td = tdscf.TDA(mf) if use_tda else tdscf.TDDFT(mf)
    td.singlet = params.get("singlet_only", True)
    td.nstates = n_states
    excitation_energies = td.kernel()[0]

    ev = (np.array(excitation_energies) * 27.211386245988).tolist()
    nm = [1239.841984 / e if e > 0 else None for e in ev]
    try:
        osc = td.oscillator_strength().tolist()
    except Exception:
        osc = [None] * len(ev)
    dominant = [_dominant_transition(xy[0], mol.nelec) for xy in td.xy]

    summary = {
        "ground_state_energy_hartree": float(mf.e_tot),
        "excitation_energies_eV": ev,
        "excitation_wavelengths_nm": nm,
        "oscillator_strengths": osc,
        "dominant_transitions": dominant,
        "n_states": n_states,
        "method": method,
        "functional": functional,
        "level_of_theory": ("CIS" if (method == "hf" and use_tda) else
                             "TD-HF/RPA" if method == "hf" else
                             "TDA-DFT" if use_tda else "TDDFT"),
    }
    return {"summary": summary, "artifacts": {}}


def run_eom_ccsd(molecule: dict, params: dict) -> dict:
    """Energies only -- PySCF's EOMEESinglet has no transition-dipole/
    oscillator-strength support (verified: no such method on the class),
    unlike its TDDFT module where td.oscillator_strength() is built in.
    Route to engine='orca' (its MDCI module computes them natively) for
    UV/Vis intensities at this level of theory."""
    from pyscf import cc
    from pyscf.cc.eom_rccsd import EOMEESinglet

    mol = build_mole(molecule, params["basis"])
    if mol.spin != 0:
        raise ValueError(
            "PySCF EOM-CCSD in this app only supports closed-shell (restricted) references; "
            "use engine='orca' for open-shell systems"
        )
    mf = scf.RHF(mol)
    mf.kernel()
    if not mf.converged:
        raise RuntimeError("SCF did not converge before EOM-CCSD")

    mycc = cc.CCSD(mf)
    mycc.kernel()
    if not mycc.converged:
        raise RuntimeError("CCSD did not converge before EOM-CCSD")

    n_states = params["n_states"]
    eom = EOMEESinglet(mycc)
    excitation_energies = np.atleast_1d(np.asarray(eom.kernel(nroots=n_states)[0], dtype=float))

    ev = (excitation_energies * 27.211386245988).tolist()
    nm = [1239.841984 / e if e > 0 else None for e in ev]

    summary = {
        "ground_state_ccsd_energy_hartree": float(mycc.e_tot),
        "excitation_energies_eV": ev,
        "excitation_wavelengths_nm": nm,
        "oscillator_strengths": [None] * len(ev),
        "oscillator_strengths_note": (
            "PySCF's EOM-CCSD does not compute transition dipole moments/oscillator strengths -- "
            "energies only. Re-run with engine='orca' for intensities at this level of theory."
        ),
        "n_states": n_states,
        "level_of_theory": "EOM-CCSD",
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
    # coordinate["atoms"] is 1-based (matches the atom-number labels shown
    # in the 3D viewer and the Z-matrix panel); RDKit's rdMolTransforms API
    # is 0-based.
    atoms = [a - 1 for a in coordinate["atoms"]]
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
