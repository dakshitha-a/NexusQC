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
import math
import os

import numpy as np
from pyscf import gto, scf, dft, mcscf, tdscf
from pyscf.tools import cubegen, molden
from pyscf.hessian import thermo as pyscf_thermo
from pyscf.mcscf import avas

from app.chemistry.jobs.ci_transitions import aggregate_by_configuration, format_dominant, leading_single_excitations
from app.chemistry.jobs.molden import classify_orbital_character
from app.chemistry.jobs.vibrations import summarize_frequencies
from app.config import (
    CASSCF_CONV_TOL_ENERGY, CASSCF_CONV_TOL_OPT_FREQ, CASSCF_MAX_CYCLE_MACRO, MAX_MEMORY_MB, N_CORES,
)

os.environ.setdefault("OMP_NUM_THREADS", str(N_CORES))


def build_mole(molecule: dict, basis: str) -> gto.Mole:
    atom = [(sym, tuple(xyz)) for sym, xyz in zip(molecule["symbols"], molecule["coords"])]
    mol = gto.Mole()
    mol.atom = atom
    mol.unit = "Angstrom"
    from app.chemistry.jobs.bse_basis import is_bse_ref, bse_name, pyscf_basis_dict

    mol.basis = pyscf_basis_dict(bse_name(basis), molecule["symbols"]) if is_bse_ref(basis) else basis
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
    from app.chemistry.jobs.bse_basis import is_bse_ref, bse_name, pyscf_basis_dict

    if is_bse_ref(basis):
        name = bse_name(basis)
        resolved = pyscf_basis_dict(name, molecule["symbols"])
        basis_line = f"mol.basis = {resolved!r}  # resolved from Basis Set Exchange: '{name}'"
    else:
        basis_line = f"mol.basis = {basis!r}"
    return [
        "mol = gto.Mole()",
        f"mol.atom = '''\n{atom_lines}\n'''",
        basis_line,
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


def _casscf_preview_lines(params: dict, conv_tol: float) -> list[str]:
    """Shared driver-script lines for constructing a CASSCF object in the
    approval-card preview -- used by the casscf job_type and the
    CASSCF-driven geometry_optimization/frequency branches below, so the
    preview always shows the same explicit convergence policy the real
    run applies (app/config.py's CASSCF_CONV_TOL_*/CASSCF_MAX_CYCLE_MACRO,
    via pyscf_runner._build_casscf)."""
    n_states = params.get("n_states", 1)
    lines = [
        "mf = scf.RHF(mol) if mol.spin == 0 else scf.ROHF(mol)",
        f"mc = mcscf.CASSCF(mf, {params['active_orbitals']}, {params['active_electrons']})",
        f"mc.conv_tol = {conv_tol}",
        f"mc.max_cycle_macro = {CASSCF_MAX_CYCLE_MACRO}",
    ]
    if n_states > 1:
        weights = params.get("weights") or [1.0 / n_states] * n_states
        lines.append(f"mc = mc.state_average_({weights})")
    return lines


def build_input_preview(job_type: str, molecule: dict, params: dict) -> str:
    """A PySCF driver script equivalent to what run_<job_type> below will
    actually execute -- PySCF has no literal input-file format (it's a
    Python API), so this is the closest honest equivalent of "the input"
    for approval purposes."""
    if job_type == "opt_freq":
        # run_opt_freq's own input IS genuinely the geometry_optimization
        # input -- see orca_runner.build_input_text's identical alias for
        # the full reasoning.
        job_type = "geometry_optimization"
    basis = params.get("basis")
    method = params.get("method", "hf")
    functional = params.get("functional")
    lines = ["from pyscf import gto, scf, dft, mcscf, tdscf", ""]
    lines += _mole_lines(molecule, basis)
    lines.append("")

    if job_type == "single_point":
        if method == "mp2":
            lines.append("mf = scf.RHF(mol) if mol.spin == 0 else scf.ROHF(mol)")
            lines.append("mf.kernel()")
            lines.append("from pyscf import mp")
            lines.append("energy = mp.MP2(mf).run().e_tot")
        elif method == "ccsd":
            lines.append("mf = scf.RHF(mol) if mol.spin == 0 else scf.ROHF(mol)")
            lines.append("mf.kernel()")
            lines.append("from pyscf import cc")
            lines.append("energy = cc.CCSD(mf).run().e_tot")
        else:
            lines += _mf_lines(method, functional)
            lines.append("energy = mf.kernel()")
    elif job_type == "geometry_optimization":
        lines.append("from pyscf.geomopt.geometric_solver import optimize")
        if method == "casscf":
            lines += _casscf_preview_lines(params, CASSCF_CONV_TOL_OPT_FREQ)
            lines.append(f"mol_eq = optimize(mc, maxsteps={params.get('max_steps', 200)})")
        else:
            lines += _mf_lines(method, functional)
            lines.append(f"mol_eq = optimize(mf, maxsteps={params.get('max_steps', 200)})")
    elif job_type == "frequency":
        if method == "casscf":
            lines += _casscf_preview_lines(params, CASSCF_CONV_TOL_OPT_FREQ)
            lines.append("mc.kernel()")
            lines.append("from app.chemistry.jobs.pyscf_runner import _numerical_casscf_hessian")
            lines.append("hess = _numerical_casscf_hessian(mc)  # no analytic CASSCF Hessian in pyscf")
            lines.append("from pyscf.hessian import thermo")
            lines.append("freq_info = thermo.harmonic_analysis(mol, hess)")
            lines.append(f"thermo_info = thermo.thermo(mc, freq_info['freq_au'], {params.get('temperature_K', 298.15)})")
        else:
            lines += _mf_lines(method, functional)
            lines.append("mf.kernel()")
            lines.append("hess = mf.Hessian().kernel()")
            lines.append("from pyscf.hessian import thermo")
            lines.append("freq_info = thermo.harmonic_analysis(mol, hess)")
            lines.append(
                f"thermo_info = thermo.thermo(mf, freq_info['freq_au'], {params.get('temperature_K', 298.15)})"
            )
    elif job_type == "casscf":
        lines += _casscf_preview_lines(params, CASSCF_CONV_TOL_ENERGY)
        lines.append("mc.kernel()")
        if params.get("want_oscillator_strengths"):
            lines.append("# NOTE: PySCF's CASSCF path here does not compute oscillator strengths;")
            lines.append("# use engine='orca' (adds DoDipoleLength) for UV/Vis intensities")
    elif job_type == "tddft":
        td_method = params.get("method", "dft")
        td_functional = functional or "b3lyp" if td_method == "dft" else None
        lines += _mf_lines(td_method, td_functional)
        lines.append("mf.kernel()")
        use_tda = params.get("use_tda", False)
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
    elif job_type == "gradient":
        target_state = params.get("target_state")
        if method == "casscf":
            lines += _casscf_preview_lines(params, CASSCF_CONV_TOL_ENERGY)
            lines.append("mc.kernel()")
            lines.append("grad = mc.nuc_grad_method().kernel()  # ground state only")
        elif method == "mp2":
            lines.append("mf = scf.RHF(mol) if mol.spin == 0 else scf.ROHF(mol)")
            lines.append("mf.kernel()")
            lines.append("from pyscf import mp")
            lines.append("grad = mp.MP2(mf).run().nuc_grad_method().kernel()")
        elif method == "ccsd":
            lines.append("mf = scf.RHF(mol) if mol.spin == 0 else scf.ROHF(mol)")
            lines.append("mf.kernel()")
            lines.append("from pyscf import cc")
            lines.append("grad = cc.CCSD(mf).run().nuc_grad_method().kernel()")
        else:
            lines += _mf_lines(method, functional)
            lines.append("mf.kernel()")
            if target_state:
                td_cls = "TDA" if params.get("use_tda", False) else "TDDFT"
                lines.append(f"td = tdscf.{td_cls}(mf)")
                lines.append(f"td.nstates = {max(params.get('n_states') or 0, target_state)}")
                lines.append("td.kernel()")
                lines.append(f"grad = td.nuc_grad_method().kernel(state={target_state})  # 1-based excited state")
            else:
                lines.append("grad = mf.nuc_grad_method().kernel()  # ground state")
    elif job_type == "nac":
        lines += _casscf_preview_lines(params, CASSCF_CONV_TOL_ENERGY)
        lines.append("mc.kernel()")
        lines.append("from pyscf.nac import sacasscf as nac_sacasscf")
        pair = (params.get("state_pairs") or [[1, 2]])[0]
        s1, s2 = int(pair[0]) - 1, int(pair[1]) - 1
        lines.append(f"nac = nac_sacasscf.NonAdiabaticCouplings(mc).kernel(state=({s1}, {s2}))  "
                     f"# 0-based CASSCF state-average roots, state_pairs {pair} converted")
    elif job_type == "mo_visualization":
        lines += _mf_lines(method, functional)
        lines.append("mf.kernel()")
        lines.append("from pyscf.tools import cubegen")
        lines.append(f"# orbitals to render: {params.get('orbital_indices')} (isoval={params.get('isoval', 0.04)})")
        lines.append("cubegen.orbital(mol, 'mo_<label>.cube', mf.mo_coeff[:, <index>])")
    elif job_type == "recommend_active_space":
        # No literal driver-script equivalent -- this is a multi-stage
        # pipeline with data-dependent steps, not a single calculation, so
        # the "preview" the approval card shows is the step plan itself
        # (see the recommend_active_space plan's approval-card design).
        max_orb = params.get("max_active_orbitals", 12)
        aolabels = params.get("avas_aolabels") or "default valence AOs of every non-hydrogen atom"
        entropy_method = params.get("entropy_method") or "exact_fci"
        if entropy_method == "dmrg":
            pilot_line = (
                f"   capped at {_DMRG_PILOT_CAS_CEILING} orbitals (DMRG pilot ceiling)\n"
                f"3. DMRG pilot (block2, bond_dim={params.get('dmrg_bond_dim') or 250}, low-sweep, "
                f"unconverged) within the pilot space -> single-orbital entropies per orbital\n"
            )
        else:
            pilot_line = (
                f"   capped at {_PILOT_CAS_CEILING} orbitals (exact-FCI feasibility limit)\n"
                "3. Exact CASCI within the pilot space -> single-orbital entropies per orbital\n"
            )
        return (
            "This job runs a Single-Orbital-Entropy (autoCAS-style) active-space\n"
            "recommendation as one pipeline, then a final CASSCF with the result:\n\n"
            f"1. RHF on {molecule.get('name', 'the molecule')} in {basis}\n"
            f"2. Select a valence pilot active space via AVAS ({aolabels}),\n"
            + pilot_line +
            f"4. Sweep the entropy threshold to find a stable (plateau) active-space size,\n"
            f"   capped at {max_orb} orbitals\n"
            f"5. State-averaged CASSCF for {params.get('n_states', 1)} state(s) with the recommended active space\n"
            "6. Classify each orbital's character (sigma/pi/n/sigma*/pi*) and dominant atom(s)"
        )
    else:
        raise ValueError(f"Unsupported job_type '{job_type}' for PySCF")

    return "\n".join(lines)


def _excitation_energies_eV(state_energies_hartree: list[float]) -> list[float] | None:
    """Gaps (eV) of every excited state relative to state 0, matching the
    convention orca_runner.py's own excitation_energies_eV already uses for
    CASSCF/CASPT2 (length n_states-1, not one entry per state) -- so
    PySCF/BAGEL CASSCF/CASPT2 jobs, which otherwise only ever report
    absolute state_energies_hartree, get the same eV field ORCA CASSCF
    already has, and every caller downstream (job_context_summary's
    markdown table shown to the LLM, ExcitedStateTable's fallback
    computation, plot_excited_state_spectrum) sees eV without needing to
    convert Hartree itself. None (not an empty list) for a single-state
    job, where there's no excitation to report."""
    if len(state_energies_hartree) < 2:
        return None
    e0 = state_energies_hartree[0]
    return [(e - e0) * 27.211386245988 for e in state_energies_hartree[1:]]


def _casscf_molden_and_table(mc, job_dir: str) -> tuple[str, list[dict]]:
    """Writes a natural-orbital molden export for a converged CASSCF object
    and returns (molden_path, orbital_table) with character/localized_atom
    merged in via classify_orbital_character -- shared by every CASSCF
    call site (run_casscf, geometry_optimization, run_recommend_active_space)
    so they all get the same natural-orbital character table instead of
    each reimplementing the reload-then-classify pattern.

    cas_natorb=True canonicalizes the MOLDEN FILE to natural orbitals with
    real fractional active-space occupations, but does not mutate
    mc.mo_coeff/mc.mo_occ in place (those stay canonical, integer 0/2) --
    so classify_orbital_character must use coefficients/occupations
    reloaded from the molden file, not mc's own attributes, to get
    bonding/antibonding character right from the occupation number.
    Classification failures (e.g. an unusual point group SVD edge case)
    degrade to plain energy/occupancy rows rather than failing an
    otherwise-successful CASSCF job."""
    molden_path = os.path.join(job_dir, "orbitals.molden")
    molden.from_mcscf(mc, molden_path, cas_natorb=True)
    from app.chemistry.jobs.molden import orbital_table as _molden_orbital_table
    table = _molden_orbital_table(molden_path)
    try:
        nat_mol, _e, nat_mo_coeff, nat_mo_occ, _irrep, _spins = molden.load(molden_path)
        for row, char_row in zip(table, classify_orbital_character(nat_mol, nat_mo_coeff, nat_mo_occ)):
            row.update(char_row)
    except Exception:
        pass
    return molden_path, table


def _write_molden_and_table(job_dir: str, mf) -> tuple[str, list[dict]]:
    """Writes an orbitals.molden export and the flat {index, spin, energy_eV,
    occupancy} table OrbitalTable.tsx renders (frontend/src/jobs/
    JobDetailDrawer.tsx gates the orbital table + MoCubeViewer purely on
    summary["orbital_table"] being present, not on job_type -- so any job
    type that calls this becomes lazily orbital-visualizable for free via
    the existing POST /orbitals/{index}/cube endpoint, no frontend change
    needed). Originally only run_mo_visualization did this; every other
    run_* below that ends with a converged `mf` now calls it too, since
    the marginal cost is negligible (mf.mo_coeff is already in memory) and
    a user shouldn't have to know in advance that they'll want to look at
    orbitals before submitting a calculation. build_mf only ever returns
    RHF/ROHF/RKS/ROKS (see build_mf's own docstring), so mf.mo_energy/
    mo_occ are always flat arrays here, never the alpha/beta tuple
    molden.from_scf's other branch would produce for a genuine UHF mf.
    Also merges in character/localized_atom via classify_orbital_character,
    using mf's own already-in-memory mol/mo_coeff/mo_occ directly (no
    molden reload needed here, unlike the CASSCF case -- these are the
    actual canonical HF/DFT orbitals, not natural orbitals requiring a
    cas_natorb round-trip) -- degrades to plain rows on any classification
    failure rather than failing the whole job."""
    molden_path = os.path.join(job_dir, "orbitals.molden")
    molden.from_scf(mf, molden_path)
    orbital_table = [
        {"index": i + 1, "spin": None, "energy_eV": float(e) * 27.211386245988, "occupancy": float(o)}
        for i, (e, o) in enumerate(zip(mf.mo_energy, mf.mo_occ))
    ]
    try:
        for row, char_row in zip(orbital_table, classify_orbital_character(mf.mol, mf.mo_coeff, mf.mo_occ)):
            row.update(char_row)
    except Exception:
        pass
    return molden_path, orbital_table


def run_single_point(molecule: dict, params: dict) -> dict:
    """single_point/gs. method in (hf, dft, mp2, ccsd) -- mp2/ccsd build the
    same RHF/ROHF reference run_gradient's own mp2/ccsd branches do and
    report the correlated energy without asking for a gradient, since a
    plain energy request has no use for one and computing it would just be
    wasted work on top of an already-converged CC/MP2 object."""
    method = params["method"]
    mol = build_mole(molecule, params["basis"])

    if method in ("mp2", "ccsd"):
        mf = scf.RHF(mol) if mol.spin == 0 else scf.ROHF(mol)
        mf.kernel()
        if not mf.converged:
            raise RuntimeError("SCF did not converge; try a different initial guess or check the input")
        if method == "mp2":
            from pyscf import mp
            corr = mp.MP2(mf)
        else:
            from pyscf import cc
            corr = cc.CCSD(mf)
        corr.kernel()
        energy = float(corr.e_tot)
        converged = bool(getattr(corr, "converged", True))
        summary = {
            "energy_hartree": energy,
            "converged": converged,
            "method": method,
            "functional": None,
            "basis": params["basis"],
            "reference_energy_hartree": float(mf.e_tot),
            "correlation_energy_hartree": energy - float(mf.e_tot),
            "homo_lumo_gap_eV": _homo_lumo_gap(mf),
            "dipole_debye": list(mf.dip_moment(unit="Debye", verbose=0)),
        }
        molden_path, summary["orbital_table"] = _write_molden_and_table(params["_job_dir"], mf)
        return {"summary": summary, "artifacts": {"molden": molden_path}}

    mf = build_mf(mol, method, params.get("functional"))
    energy = mf.kernel()
    if not mf.converged:
        raise RuntimeError("SCF did not converge; try a different initial guess or check the input")

    summary = {
        "energy_hartree": float(energy),
        "converged": bool(mf.converged),
        "method": method,
        "functional": params.get("functional"),
        "basis": params["basis"],
        "homo_lumo_gap_eV": _homo_lumo_gap(mf),
        "dipole_debye": list(mf.dip_moment(unit="Debye", verbose=0)),
    }
    molden_path, summary["orbital_table"] = _write_molden_and_table(params["_job_dir"], mf)
    return {"summary": summary, "artifacts": {"molden": molden_path}}


def run_gradient(molecule: dict, params: dict) -> dict:
    """single_point/grad. method in (hf, dft, mp2, ccsd, casscf); an
    excited-state gradient (target_state set) is only reachable for hf/dft
    -- app/agent/tools.py's _build_spec_or_error refuses target_state for
    any (engine, method) whose capability row doesn't claim
    excited_gradient before a spec ever reaches here, so casscf/mp2/ccsd
    below are always ground-state.

    Every method branch ends with an already-converged mean-field/CC/CASSCF
    object, so an orbital table is attached "for free" the same way every
    other run_* here does (see _write_molden_and_table's own docstring)."""
    method = params["method"]
    target_state = params.get("target_state")
    mol = build_mole(molecule, params["basis"])

    if method == "casscf":
        restricted = mol.spin == 0
        mf = scf.RHF(mol) if restricted else scf.ROHF(mol)
        mf.kernel()
        mc = _build_casscf(mf, params["active_orbitals"], params["active_electrons"],
                            params.get("n_states", 1), params.get("weights"), CASSCF_CONV_TOL_ENERGY)
        _apply_initial_orbitals(mc, params)
        mc.kernel()
        grad = mc.nuc_grad_method().kernel()
        energy = float(mc.e_tot)
        molden_path, orbital_table = _casscf_molden_and_table(mc, params["_job_dir"])
    elif method == "mp2":
        from pyscf import mp
        mf = scf.RHF(mol) if mol.spin == 0 else scf.ROHF(mol)
        mf.kernel()
        mp2 = mp.MP2(mf)
        mp2.kernel()
        grad = mp2.nuc_grad_method().kernel()
        energy = float(mp2.e_tot)
        molden_path, orbital_table = _write_molden_and_table(params["_job_dir"], mf)
    elif method == "ccsd":
        from pyscf import cc
        mf = scf.RHF(mol) if mol.spin == 0 else scf.ROHF(mol)
        mf.kernel()
        ccobj = cc.CCSD(mf)
        ccobj.kernel()
        grad = ccobj.nuc_grad_method().kernel()
        energy = float(ccobj.e_tot)
        molden_path, orbital_table = _write_molden_and_table(params["_job_dir"], mf)
    elif method in ("hf", "dft"):
        mf = build_mf(mol, method, params.get("functional"))
        mf.kernel()
        if not mf.converged:
            raise RuntimeError("SCF did not converge; try a different initial guess or check the input")
        if target_state:
            td = tdscf.TDA(mf) if params.get("use_tda", False) else tdscf.TDDFT(mf)
            td.nstates = max(params.get("n_states") or 0, target_state)
            excitation_energies = td.kernel()[0]
            grad = td.nuc_grad_method().kernel(state=target_state)
            energy = float(mf.e_tot + excitation_energies[target_state - 1])
        else:
            grad = mf.nuc_grad_method().kernel()
            energy = float(mf.e_tot)
        molden_path, orbital_table = _write_molden_and_table(params["_job_dir"], mf)
    else:
        raise ValueError(f"Unsupported method '{method}' for a PySCF gradient")

    grad_arr = np.asarray(grad)
    summary = {
        "gradient_hartree_per_bohr": grad_arr.tolist(),
        "gradient_norm_hartree_per_bohr": float(np.linalg.norm(grad_arr)),
        "energy_hartree": energy,
        "method": method,
        "functional": params.get("functional"),
        "basis": params["basis"],
        "target_state": target_state,
        "orbital_table": orbital_table,
        "initial_orbitals_source_job_id": params.get("initial_orbitals_job_id"),
    }
    return {"summary": summary, "artifacts": {"molden": molden_path}}


def run_nac(molecule: dict, params: dict) -> dict:
    """single_point/nac. PySCF's only NAC path is SA-CASSCF
    (pyscf.nac.sacasscf) -- no TDDFT NAC module exists in this pyscf
    version (see registry2/capabilities.py's pyscf/dft row), so
    tasks.supports() never routes a single-reference NAC request here in
    the first place; this function only ever runs for method='casscf'.

    state_pairs (registry2/params.py) is 1-based INCLUDING the ground
    state (state_pairs=[[1, 2]] means the S0/S1 coupling), matching every
    other engine's runner here; pyscf.nac.sacasscf's own `state=` kwarg is
    0-based within the state average (verified live: scripts/spikes/
    spike_pyscf_caps.py's state=(0, 1) probe), so the -1 conversion happens
    here, at the input-building boundary, and nowhere else."""
    method = params["method"]
    if method != "casscf":
        raise ValueError(f"PySCF NAC in this app is only available for method='casscf' (SA-CASSCF), got '{method}'")
    from pyscf.nac import sacasscf as nac_sacasscf

    pair = params["state_pairs"][0]
    s1, s2 = int(pair[0]) - 1, int(pair[1]) - 1

    mol = build_mole(molecule, params["basis"])
    restricted = mol.spin == 0
    mf = scf.RHF(mol) if restricted else scf.ROHF(mol)
    mf.kernel()
    n_orb, n_elec, n_states = params["active_orbitals"], params["active_electrons"], params.get("n_states", 1)
    mc = _build_casscf(mf, n_orb, n_elec, n_states, params.get("weights"), CASSCF_CONV_TOL_ENERGY)
    _apply_initial_orbitals(mc, params)
    mc.kernel()

    nac = nac_sacasscf.NonAdiabaticCouplings(mc)
    vec = np.asarray(nac.kernel(state=(s1, s2)))
    molden_path, orbital_table = _casscf_molden_and_table(mc, params["_job_dir"])

    summary = {
        "nac_hartree_per_bohr": vec.tolist(),
        "nac_norm_hartree_per_bohr": float(np.linalg.norm(vec)),
        "state_pair": [s1 + 1, s2 + 1],
        "active_electrons": n_elec,
        "active_orbitals": n_orb,
        "n_states": n_states,
        "orbital_table": orbital_table,
        "initial_orbitals_source_job_id": params.get("initial_orbitals_job_id"),
    }
    return {"summary": summary, "artifacts": {"molden": molden_path}}


# app/agent/tools.py's _build_spec_or_error validates each entry's shape
# before a spec is ever built (type/atom-count/1-based-in-range), so this
# module only has to translate a shape it can already trust.
_GEOMETRIC_CONSTRAINT_KEY = {"bond": "distance", "angle": "angle", "dihedral": "dihedral"}


def _geometric_constraints_file(constraints: list[dict], job_dir: str) -> str:
    """Translates this app's `constraints` ParamSpec shape
    ([{'type': 'bond'|'angle'|'dihedral', 'atoms': [1-based...], 'value': ...}])
    into geomeTRIC's own constraints-file format. Confirmed by reading
    geometric/prepare.py::parse_constraints directly on this host (not from
    memory): a '$set' block, atom indices read as `int(i) - 1` (i.e.
    1-based, matching this app's own numbering with no conversion needed),
    and the constrained value read in Angstrom for 'distance' / degrees for
    'angle'/'dihedral' -- also this app's own units already."""
    lines = ["$set"]
    for c in constraints:
        key = _GEOMETRIC_CONSTRAINT_KEY[c["type"]]
        atoms = " ".join(str(a) for a in c["atoms"])
        lines.append(f"{key} {atoms} {c['value']}")
    path = os.path.join(job_dir, "constraints.txt")
    with open(path, "w") as f:
        f.write("\n".join(lines) + "\n")
    return path


def run_geometry_optimization(molecule: dict, params: dict) -> dict:
    from pyscf.geomopt.geometric_solver import optimize

    method = params["method"]
    if method == "caspt2":
        raise ValueError(
            "CASPT2 geometry optimization is BAGEL-only in this app (ORCA has no CASPT2; pyscf has no "
            "CASPT2 gradient here) -- use engine='bagel'."
        )

    mol = build_mole(molecule, params["basis"])
    constraints = params.get("constraints")
    constraints_file = _geometric_constraints_file(constraints, params["_job_dir"]) if constraints else None

    # geomeTRIC's PySCFEngine calls callback(locals()) once per optimization
    # cycle from inside calc_new(), with an 'energy' key already computed
    # for that step's geometry (verified by reading geometric_solver.py's
    # PySCFEngine.calc_new -- no public API exposes this after the fact,
    # so it must be captured live during optimize() or not at all).
    energies_per_step: list[float] = []

    def _capture_energy(local_vars: dict) -> None:
        energies_per_step.append(float(local_vars["energy"]))

    if method == "casscf":
        # No pre-optimize mc.kernel() call, mirroring the HF/DFT path below
        # (which also passes an un-run mf straight to optimize()) --
        # geomeTRIC's engine runs the wavefunction itself at each step,
        # confirmed live to converge correctly from a completely fresh
        # (unconverged) mc object, same as the existing HF/DFT path.
        restricted = mol.spin == 0
        mf = scf.RHF(mol) if restricted else scf.ROHF(mol)
        n_orb, n_elec = params["active_orbitals"], params["active_electrons"]
        n_states = params.get("n_states", 1)
        mc = _build_casscf(mf, n_orb, n_elec, n_states, params.get("weights"), CASSCF_CONV_TOL_OPT_FREQ)
        _apply_initial_orbitals(mc, params)
        mol_eq = optimize(
            mc, maxsteps=params.get("max_steps", 200), callback=_capture_energy, constraints=constraints_file,
        )

        # Fresh converged CASSCF at the optimized geometry -- mirrors the
        # HF/DFT path's own mf_final re-evaluation below, rather than
        # trusting whatever transient state the scanner left `mc` in. Still
        # seeded from the same initial_orbitals_job_id source (a nearby
        # geometry's converged orbitals remain a better guess than mf_final's
        # plain HF ones) rather than from `mc`'s own end-of-optimization state.
        mf_final = scf.RHF(mol_eq) if restricted else scf.ROHF(mol_eq)
        mf_final.kernel()
        mc_final = _build_casscf(mf_final, n_orb, n_elec, n_states, params.get("weights"), CASSCF_CONV_TOL_OPT_FREQ)
        _apply_initial_orbitals(mc_final, params)
        mc_final.kernel()
        if not mc_final.converged:
            raise RuntimeError("CASSCF at the optimized geometry did not (re-)converge")

        energies = np.atleast_1d(
            mc_final.e_states if hasattr(mc_final, "e_states") and n_states > 1 else mc_final.e_tot
        ).tolist()
        optimized_molecule = molecule_from_mol(mol_eq, molecule)
        state_energies = energies if n_states > 1 else [float(mc_final.e_tot)]
        summary = {
            "final_energy_hartree": float(mc_final.e_tot) if n_states == 1 else None,
            "state_energies_hartree": state_energies,
            "excitation_energies_eV": _excitation_energies_eV(state_energies),
            "converged": bool(mc_final.converged),
            "optimized_molecule": optimized_molecule,
            "optimization_energies_hartree": energies_per_step,
            "active_electrons": n_elec,
            "active_orbitals": n_orb,
            "n_states": n_states,
            "initial_orbitals_source_job_id": params.get("initial_orbitals_job_id"),
        }
        if constraints:
            summary["constraints"] = constraints
        molden_path, summary["orbital_table"] = _casscf_molden_and_table(mc_final, params["_job_dir"])
        summary["orbital_table_note"] = (
            "Natural orbitals of the OPTIMIZED geometry's CASSCF wavefunction, with active-space "
            "occupation numbers (not integer HF-style occupancies), plus character (sigma/pi/n/sigma*/pi*, "
            "best-effort from point-sampling) and dominant localized atom(s) where classifiable."
        )
        return {"summary": summary, "artifacts": {"molden": molden_path}}

    target_state = params.get("target_state")
    if target_state:
        # Excited-state optimization: the TDDFT/TD-HF/CIS gradient scanner
        # IS the "method" geomeTRIC drives, not mf -- confirmed live on this
        # host that Gradients_Scanner.as_scanner(state=target_state) tracks
        # the same root across displaced geometries and converges a real
        # excited-state minimum (TD-HF/water: norm(grad) 0.55 -> 4.2e-6 over
        # 20 cycles). Reuses the exact tdscf construction run_gradient's own
        # ES path already uses and has verified against a real run.
        mf = build_mf(mol, method, params.get("functional"))
        mf.kernel()
        n_states = max(params.get("n_states") or 0, target_state)
        td = tdscf.TDA(mf) if params.get("use_tda", False) else tdscf.TDDFT(mf)
        td.nstates = n_states
        g_scanner = td.nuc_grad_method().as_scanner(state=target_state)
        mol_eq = optimize(
            g_scanner, maxsteps=params.get("max_steps", 200), callback=_capture_energy,
            constraints=constraints_file,
        )

        mf_final = build_mf(mol_eq, method, params.get("functional"))
        gs_energy = mf_final.kernel()
        td_final = tdscf.TDA(mf_final) if params.get("use_tda", False) else tdscf.TDDFT(mf_final)
        td_final.nstates = n_states
        excitation_energies_hartree = td_final.kernel()[0]
        final_energy = float(gs_energy + excitation_energies_hartree[target_state - 1])

        optimized_molecule = molecule_from_mol(mol_eq, molecule)
        summary = {
            "final_energy_hartree": final_energy,
            "ground_state_energy_hartree": float(gs_energy),
            "target_state": target_state,
            "converged": True,
            "optimized_molecule": optimized_molecule,
            "optimization_energies_hartree": energies_per_step,
        }
        if constraints:
            summary["constraints"] = constraints
        return {"summary": summary, "artifacts": {}}

    mf = build_mf(mol, method, params.get("functional"))
    mol_eq = optimize(
        mf, maxsteps=params.get("max_steps", 200), callback=_capture_energy, constraints=constraints_file,
    )

    mf_final = build_mf(mol_eq, method, params.get("functional"))
    energy = mf_final.kernel()

    optimized_molecule = molecule_from_mol(mol_eq, molecule)
    summary = {
        "final_energy_hartree": float(energy),
        "converged": bool(mf_final.converged),
        "optimized_molecule": optimized_molecule,
        "optimization_energies_hartree": energies_per_step,
    }
    if constraints:
        summary["constraints"] = constraints
    return {"summary": summary, "artifacts": {}}


def _numerical_casscf_hessian(mc, delta: float = 0.005) -> np.ndarray:
    """Central-difference numerical CASSCF Hessian, in the exact
    (natm, natm, 3, 3) shape pyscf's own analytic mf.Hessian().kernel()
    produces (confirmed by inspecting a real one) -- pyscf has NO analytic
    CASSCF Hessian at all (pyscf.hessian.casscf does not exist, confirmed
    by import), but DOES have a real analytic CASSCF gradient
    (pyscf.grad.casscf, mc.nuc_grad_method()), so this drives that gradient
    through 6*natm displaced-geometry evaluations via .as_scanner()
    (verified live: the scanner reuses each converged point's own MOs as
    the next displacement's initial guess, avoiding orbital-swap
    discontinuities across the loop -- a real, documented pitfall for
    numerical CASSCF properties). delta is in Bohr, a standard finite-
    difference step size chosen independently of ORCA/BAGEL's own internal
    numerical-Hessian defaults, since this is this app's own from-scratch
    implementation, not calling into either engine's numerics. This is
    O(6*natm) full CASSCF gradient evaluations -- noticeably slower than
    an analytic Hessian, and slower still than ORCA's/BAGEL's own native
    numerical Hessians (which don't need a Python-level re-optimization of
    the wavefunction at every displaced point the way this from-scratch
    version does)."""
    mol = mc.mol
    natm = mol.natm
    gs = mc.nuc_grad_method().as_scanner()
    coords0 = mol.atom_coords()  # Bohr
    hess = np.zeros((natm, natm, 3, 3))
    for p in range(natm):
        for x in range(3):
            mol_plus = mol.copy()
            coords_plus = coords0.copy()
            coords_plus[p, x] += delta
            mol_plus.set_geom_(coords_plus, unit="Bohr")
            _, grad_plus = gs(mol_plus)

            mol_minus = mol.copy()
            coords_minus = coords0.copy()
            coords_minus[p, x] -= delta
            mol_minus.set_geom_(coords_minus, unit="Bohr")
            _, grad_minus = gs(mol_minus)

            hess[p, :, x, :] = (grad_plus - grad_minus) / (2 * delta)
    gs(mol)  # leave the scanner (and mc, which it wraps) re-converged at equilibrium, not the last displacement
    return 0.5 * (hess + hess.transpose(1, 0, 3, 2))  # symmetrize away finite-difference noise


def run_frequency(molecule: dict, params: dict) -> dict:
    method = params["method"]
    if method == "caspt2":
        raise ValueError(
            "CASPT2 frequency calculations are BAGEL-only in this app (ORCA has no CASPT2; pyscf has no "
            "CASPT2 gradient/Hessian here) -- use engine='bagel'."
        )

    mol = build_mole(molecule, params["basis"])

    if method == "casscf":
        restricted = mol.spin == 0
        mf = scf.RHF(mol) if restricted else scf.ROHF(mol)
        mf.kernel()
        n_orb, n_elec = params["active_orbitals"], params["active_electrons"]
        n_states = params.get("n_states", 1)
        mc = _build_casscf(mf, n_orb, n_elec, n_states, params.get("weights"), CASSCF_CONV_TOL_OPT_FREQ)
        _apply_initial_orbitals(mc, params)
        mc.kernel()
        if not mc.converged:
            raise RuntimeError("CASSCF did not converge before frequency analysis")

        hess = _numerical_casscf_hessian(mc)
        freq_info = pyscf_thermo.harmonic_analysis(mol, hess)
        thermo_info = pyscf_thermo.thermo(mc, freq_info["freq_au"], params.get("temperature_K", 298.15))

        freqs_cm1 = np.real(freq_info["freq_wavenumber"]).tolist()
        # F-026: shared threshold rule, see app/chemistry/jobs/vibrations.py.
        summary = {
            **summarize_frequencies(freqs_cm1),
            "zero_point_energy_hartree": float(thermo_info["ZPE"][0]),
            "enthalpy_hartree": float(thermo_info["H_tot"][0]),
            "gibbs_free_energy_hartree": float(thermo_info["G_tot"][0]),
            "entropy_hartree_per_K": float(thermo_info["S_tot"][0]),
            "temperature_K": params.get("temperature_K", 298.15),
            "normal_modes": freq_info["norm_mode"].tolist(),
            # Already computed internally by harmonic_analysis (reduced_mass
            # = 1/sum(norm_mode**2) per mode, amu) -- just not previously
            # copied into the summary. Needed by wigner-ensemble sampling
            # (app/chemistry/jobs/wigner.py); ORCA/BAGEL derive the same
            # value from their own normal_modes arrays via the identical
            # formula, using this pyscf value as the cross-check ground
            # truth (see app/chemistry/jobs/vibrations.py).
            "reduced_mass_amu": freq_info["reduced_mass"].tolist(),
            "active_electrons": n_elec,
            "active_orbitals": n_orb,
            "n_states": n_states,
            "initial_orbitals_source_job_id": params.get("initial_orbitals_job_id"),
            "hessian_method_note": (
                "Numerical Hessian (central differences of the analytic CASSCF gradient) -- pyscf has no "
                "analytic CASSCF Hessian. See known limitations for the cost/accuracy tradeoff."
            ),
        }
        molden_path, summary["orbital_table"] = _casscf_molden_and_table(mc, params["_job_dir"])
        summary["orbital_table_note"] = (
            "Natural orbitals with active-space occupation numbers (not integer HF-style occupancies), plus "
            "character (sigma/pi/n/sigma*/pi*) and dominant localized atom(s) where classifiable."
        )
        return {"summary": summary, "artifacts": {"molden": molden_path}}

    mf = build_mf(mol, method, params.get("functional"))
    mf.kernel()
    if not mf.converged:
        raise RuntimeError("SCF did not converge before frequency analysis")

    hess = mf.Hessian().kernel()
    freq_info = pyscf_thermo.harmonic_analysis(mol, hess)
    thermo_info = pyscf_thermo.thermo(mf, freq_info["freq_au"], params.get("temperature_K", 298.15))

    freqs_cm1 = np.real(freq_info["freq_wavenumber"]).tolist()
    # F-026: shared threshold rule, see app/chemistry/jobs/vibrations.py.
    summary = {
        **summarize_frequencies(freqs_cm1),
        "zero_point_energy_hartree": float(thermo_info["ZPE"][0]),
        "enthalpy_hartree": float(thermo_info["H_tot"][0]),
        "gibbs_free_energy_hartree": float(thermo_info["G_tot"][0]),
        "entropy_hartree_per_K": float(thermo_info["S_tot"][0]),
        "temperature_K": params.get("temperature_K", 298.15),
        "normal_modes": freq_info["norm_mode"].tolist(),
        "reduced_mass_amu": freq_info["reduced_mass"].tolist(),
    }
    return {"summary": summary, "artifacts": {}}


def run_opt_freq(molecule: dict, params: dict) -> dict:
    """Geometry optimization followed by a frequency (Hessian) calculation
    at the optimized geometry -- calls run_geometry_optimization then
    run_frequency sequentially, reusing both fully rather than a fused
    single-process implementation (which would need its own bespoke
    "reuse the converged mf/mc object across both stages" code, separately
    verified). The tradeoff: the wavefunction reconverges from scratch for
    the frequency stage instead of continuing from the optimization's own
    already-converged one -- a modest efficiency cost in exchange for
    reusing two already-tested, already-verified per-stage runners as-is.

    The optimization stage's own artifacts (e.g. a CASSCF molden export)
    are written under a nested "_opt_stage" subdirectory of the job's own
    _job_dir, so they survive rather than being silently overwritten by
    the frequency stage's own artifacts of the same name -- kept in the
    result under "optimization_"-prefixed artifact keys, distinct from the
    frequency stage's own (unprefixed, canonical) ones."""
    import os

    opt_params = dict(params)
    opt_job_dir = os.path.join(params["_job_dir"], "_opt_stage")
    os.makedirs(opt_job_dir, exist_ok=True)
    opt_params["_job_dir"] = opt_job_dir

    opt_result = run_geometry_optimization(molecule, opt_params)
    optimized_molecule = opt_result["summary"].get("optimized_molecule")
    if not optimized_molecule:
        raise RuntimeError("geometry optimization did not converge to a usable optimized geometry")

    freq_result = run_frequency(optimized_molecule, params)

    summary = dict(freq_result["summary"])
    summary["optimized_molecule"] = optimized_molecule
    summary["optimization_final_energy_hartree"] = opt_result["summary"].get("final_energy_hartree")
    summary["optimization_converged"] = opt_result["summary"].get("converged")
    summary["optimization_energies_hartree"] = opt_result["summary"].get("optimization_energies_hartree")

    artifacts = dict(freq_result.get("artifacts", {}))
    for key, path in opt_result.get("artifacts", {}).items():
        artifacts[f"optimization_{key}"] = path

    return {"summary": summary, "artifacts": artifacts}


def _dominant_transitions_casscf(mc, n_states: int) -> list[str | None]:
    """pyscf.fci.addons.large_ci(..., return_strs=False) returns, per
    leading Slater determinant, (coefficient, occupied_alpha_orbital_idx,
    occupied_beta_orbital_idx) -- both index lists 0-based within the
    active space (verified empirically: not bit-strings, which
    return_strs=True would give instead). Converted to a per-orbital
    occupation-count vector and fed through aggregate_by_configuration,
    since large_ci's determinants for an open-shell CSF split into
    separate alpha/beta-swapped lines with the same |coefficient| (e.g.
    two determinants both ~0.70 for one true ~0.99-weight spatial
    configuration -- confirmed on a real water/STO-3G CAS(4,4) run) that
    would otherwise show the same orbital pair twice."""
    from pyscf import fci as pyscf_fci

    ncas = mc.ncas
    nelecas = mc.nelecas
    ncore = mc.ncore
    civecs = mc.ci if isinstance(mc.ci, list) else [mc.ci]

    per_state: list[list[tuple[float, list[int]]]] = []
    all_configs: list[tuple[float, list[int]]] = []
    for civec in civecs:
        raw = pyscf_fci.addons.large_ci(civec, ncas, nelecas, tol=0.01, return_strs=False)
        determinants: list[tuple[float, list[int]]] = []
        for weight, occ_a, occ_b in raw:
            counts = [0] * ncas
            for i in occ_a:
                counts[int(i)] += 1
            for i in occ_b:
                counts[int(i)] += 1
            determinants.append((float(weight), counts))
        configs = aggregate_by_configuration(determinants)
        per_state.append(configs)
        all_configs.extend(configs)

    if not all_configs:
        return [None] * n_states
    _, reference_counts = max(all_configs, key=lambda c: c[0])

    result: list[str | None] = [None] * n_states
    for i, configs in enumerate(per_state):
        if i >= n_states:
            break
        transitions = leading_single_excitations(configs, reference_counts, ncore)
        result[i] = format_dominant(transitions)
    return result


def _apply_initial_orbitals(mc, params: dict) -> None:
    """Seeds mc.mo_coeff from params['initial_orbitals_job_id'] (Phase 8
    orbital reuse), if set -- a no-op otherwise, leaving mc's own default
    (mcscf.CASSCF.__init__ already sets mo_coeff from the underlying mf).
    Every downstream mc.kernel()/geometric_solver.optimize(mc, ...) call in
    this module defaults an omitted mo_coeff argument to mc.mo_coeff
    itself, so seeding it here is picked up with no change at any call
    site -- callers just call this once, right after _build_casscf.

    Reads the source job's own orbitals.molden -- written by every
    CASSCF-family run in this module already (see _casscf_molden_and_table)
    -- for the actual mo_coeff, rather than a dedicated chkfile: every
    completed CASSCF job already carries one, so no new persistence is
    needed. `prev_mol` (mcscf.project_init_guess's basis-association
    argument, mandatory whenever the source used a different basis --
    scripts/spikes/spike_pyscf_caps.py's own verified finding) is instead
    rebuilt from the source job's own recorded molecule/basis via
    build_mole -- the same function every mol in this module goes through
    -- rather than trusted from pyscf.tools.molden.load()'s own returned
    `mol`. That first design was tried and is WRONG: a molden-round-tripped
    mol's internal `_basis`/atom-label representation does not match one
    build_mole constructs directly, so pyscf.gto.same_mol/same_basis_set
    (which project_init_guess uses internally to decide whether prev_mol
    even applies) spuriously disagree even for the identical basis,
    surfacing as 'Project initial guess from different system' on a plain
    geometry-only change -- caught by this feature's own test script
    (tests/backend/p8_01_orbital_reuse.py) reusing across a stretched
    geometry, not by inspection.

    Source-job validity (existence, completed, casscf/caspt2 method, same
    engine) is checked pre-interrupt in registry2/elicitation.py; this
    performs the actual read, deferred to dispatch time per this app's
    cross-job-artifact precedent (app/agent/tools.py's own
    _resolve_batch_geometries)."""
    source_job_id = params.get("initial_orbitals_job_id")
    if not source_job_id:
        return
    from app.config import JOBS_DIR
    from app.chemistry.jobs.base import read_spec
    source_molden = os.path.join(str(JOBS_DIR), source_job_id, "orbitals.molden")
    if not os.path.exists(source_molden):
        raise RuntimeError(f"Initial-orbitals source job '{source_job_id}' has no orbitals.molden on disk.")
    _molden_mol, _e, source_mo_coeff, _occ, _irrep, _spins = molden.load(source_molden)
    source_spec = read_spec(source_job_id) or {}
    source_molecule = source_spec.get("molecule")
    source_basis = (source_spec.get("params") or {}).get("basis")
    prev_mol = build_mole(source_molecule, source_basis) if source_molecule and source_basis else None
    mc.mo_coeff = mcscf.project_init_guess(mc, source_mo_coeff, prev_mol=prev_mol)


def _build_casscf(mf, n_orb: int, n_elec: int, n_states: int, weights, conv_tol: float) -> "mcscf.CASSCF":
    """Shared CASSCF constructor for run_casscf, run_recommend_active_space's
    final CASSCF, and the CASSCF-driven geometry_optimization/frequency
    branches below -- applies this app's explicit convergence policy
    (app/config.py's CASSCF_CONV_TOL_*/CASSCF_MAX_CYCLE_MACRO) so every
    CASSCF macro-iteration loop in this app uses the same explicit values
    instead of pyscf's own defaults (conv_tol=1e-7, max_cycle_macro=50)."""
    mc = mcscf.CASSCF(mf, n_orb, n_elec)
    mc.conv_tol = conv_tol
    mc.max_cycle_macro = CASSCF_MAX_CYCLE_MACRO
    if n_states > 1:
        weights = weights or [1.0 / n_states] * n_states
        mc = mc.state_average_(weights)
    return mc


def run_casscf(molecule: dict, params: dict) -> dict:
    mol = build_mole(molecule, params["basis"])
    restricted = mol.spin == 0
    mf = scf.RHF(mol) if restricted else scf.ROHF(mol)
    mf.kernel()

    n_orb = params["active_orbitals"]
    n_elec = params["active_electrons"]
    n_states = params.get("n_states", 1)

    mc = _build_casscf(mf, n_orb, n_elec, n_states, params.get("weights"), CASSCF_CONV_TOL_ENERGY)
    _apply_initial_orbitals(mc, params)
    mc.kernel()

    energies = np.atleast_1d(mc.e_states if hasattr(mc, "e_states") and n_states > 1 else mc.e_tot).tolist()
    state_energies = energies if n_states > 1 else [float(mc.e_tot)]
    summary = {
        "casscf_energy_hartree": float(mc.e_tot) if n_states == 1 else None,
        "state_energies_hartree": state_energies,
        "excitation_energies_eV": _excitation_energies_eV(state_energies),
        "active_electrons": n_elec,
        "active_orbitals": n_orb,
        "n_states": n_states,
        "converged": bool(mc.converged),
        "reference_hf_energy_hartree": float(mf.e_tot),
        "dominant_transitions": _dominant_transitions_casscf(mc, n_states),
        "initial_orbitals_source_job_id": params.get("initial_orbitals_job_id"),
    }

    # cas_natorb=True canonicalizes to natural orbitals with real fractional
    # active-space occupations (via mc.make_rdm1(), state-averaged across
    # all roots for n_states > 1 -- the standard, expected thing to
    # visualize for SA-CASSCF since the whole point of state-averaging is
    # one shared orbital set). Verified by point-sampling AO values at
    # several off-axis points against mc.canonicalize()'s own output
    # directly (not just "it parses"): the molden round-trip reproduces
    # the native active-space natural orbitals exactly (ratio 1.0), and
    # occupations correctly come out fractional in the active space
    # (e.g. ~1.98/1.98/0.02/0.02 for a closed-shell CAS(4,4), summing to
    # the right active-space electron count) rather than the plain 0/2
    # integer occupations mc.mo_occ carries without natorb canonicalization.
    molden_path, summary["orbital_table"] = _casscf_molden_and_table(mc, params["_job_dir"])
    summary["orbital_table_note"] = (
        "Natural orbitals with active-space occupation numbers (not integer HF-style occupancies) -- "
        "core orbitals show occ=2, active orbitals show their natural-orbital occupation, virtuals show occ=0. "
        "Character (sigma/pi/n/sigma*/pi*) and dominant localized atom(s) are best-effort from point-sampling."
    )
    return {"summary": summary, "artifacts": {"molden": molden_path}}


# Default AVAS valence-shell seed per element, keyed by symbol -- covers
# periods 2-4 main group plus first-row transition metals (the systems
# this app's CASSCF/CASPT2 job types are actually exercised against).
# avas_aolabels lets a caller override/extend this per molecule; an
# element outside this table with no explicit avas_aolabels raises a
# clear, actionable error rather than silently guessing a valence shell.
_AVAS_DEFAULT_SHELL = {
    **{s: "2p" for s in ["Li", "Be", "B", "C", "N", "O", "F", "Ne"]},
    **{s: "3p" for s in ["Na", "Mg", "Al", "Si", "P", "S", "Cl", "Ar"]},
    **{s: "3d" for s in ["Sc", "Ti", "V", "Cr", "Mn", "Fe", "Co", "Ni", "Cu", "Zn"]},
    **{s: "4p" for s in ["Ga", "Ge", "As", "Se", "Br", "Kr"]},
}

# Hard ceiling on the exact-FCI pilot CASCI's active space size -- benchmarked
# directly on this host: CAS(12,12) ~2s, CAS(14,14) ~41s, CAS(16,16) is
# infeasible (~165M determinants; CAS(20,20)-scale AVAS output was observed
# to still be running after 19 minutes of CPU time in ad hoc testing before
# being killed). This is a machine-cost limit, not a chemistry choice, so
# it is NOT exposed as a user-configurable parameter the way
# max_active_orbitals (the cap on the RECOMMENDED final space) is.
_PILOT_CAS_CEILING = 12

# Hard ceiling on the DMRG pilot's active space size, for entropy_method="dmrg"
# -- see run_recommend_active_space/_pilot_entropies_dmrg. Set from a real
# benchmark on this host at the actual "cheap unconverged pilot" settings
# _pilot_entropies_dmrg uses (bond_dim=250, 8 sweeps, SZ symmetry), using
# uracil's real 28-orbital AVAS pilot pool truncated to each size (the same
# molecule/aolabels that motivated this feature): CAS(12,12) 23s,
# CAS(16,16) 59s, CAS(24,20) 118s, CAS(32,24) 195s, CAS(40,28) 292s (~5
# min) -- growth is superlinear (roughly the expected polynomial DMRG
# scaling) but the full 28-orbital pool (uracil's own AVAS output at
# STO-3G, no truncation at all) is comfortably tractable at ~5 min, a
# reasonable bound for a background job on this shared host. 30 leaves a
# small buffer above the largest size actually measured (28) without
# extrapolating far past it.
_DMRG_PILOT_CAS_CEILING = 30


def _default_avas_aolabels(mol) -> list[str]:
    symbols = {mol.atom_symbol(i) for i in range(mol.natm) if mol.atom_symbol(i) != "H"}
    missing = symbols - set(_AVAS_DEFAULT_SHELL)
    if missing:
        raise ValueError(
            f"No default AVAS valence-shell seed for element(s) {sorted(missing)} -- "
            f"pass avas_aolabels explicitly, e.g. ['{sorted(missing)[0]} 3d']."
        )
    return [f"{sym} {_AVAS_DEFAULT_SHELL[sym]}" for sym in sorted(symbols)]


def _single_orbital_entropies(mc) -> tuple[list[float], list[float]]:
    """Exact single-orbital entanglement entropy AND occupation (na+nb, the
    diagonal of the active-space 1-RDM -- not a true natural-orbital
    occupation number unless the pilot's own MO basis happens to diagonalize
    it, but a perfectly good "how occupied is basis orbital i" proxy for
    electron-counting the recommended active space, and correctly indexed
    in the pilot's own active-space-local order, unlike
    pyscf.mcscf.addons.make_natural_orbitals's globally-sorted output)
    per pilot-space orbital, from the pilot CASCI's own converged FCI
    wavefunction -- the same entropy quantity autoCAS computes
    approximately from a cheap DMRG-CI pilot (no DMRG package is
    available/installed here, and none is needed: the entropy definition
    is identical, DMRG is only the scalable approximation for pilot spaces
    too large for exact FCI -- see the recommend_active_space plan).
    s(1)_i = -sum_a w_a ln(w_a), w_a the eigenvalues of orbital i's local
    (empty/up/down/doubly-occupied) reduced density matrix, built from the
    spin-resolved 1-/2-particle RDMs (w1=1-na-nb+Pii, w2=na-Pii, w3=nb-Pii,
    w4=Pii). Validated numerically before being wired in here: equilibrium
    H2 CAS(2,2) gives s~0.068 (near-single-determinant), stretched H2
    (3.0 Ang) gives s~0.690, matching the closed-form diradical limit
    ln(2)=0.693 almost exactly."""
    ncas = mc.ncas
    (dm1a, dm1b), (_dm2aa, dm2ab, _dm2bb) = mc.fcisolver.make_rdm12s(mc.ci, ncas, mc.nelecas)
    entropies, occupations = [], []
    for i in range(ncas):
        na, nb, pii = dm1a[i, i], dm1b[i, i], dm2ab[i, i, i, i]
        omegas = np.clip([1 - na - nb + pii, na - pii, nb - pii, pii], 0.0, 1.0)
        total = float(omegas.sum())
        if abs(total - 1.0) > 1e-4:
            raise RuntimeError(
                f"single-orbital entropy sanity check failed for pilot orbital {i}: "
                f"sum(omega)={total:.6f}, expected 1.0 -- this indicates an RDM convention bug, not a normal failure."
            )
        entropies.append(float(-sum(w * np.log(w) for w in omegas if w > 1e-12)))
        occupations.append(float(na + nb))
    return entropies, occupations


def _pilot_entropies_dmrg(
    mf, pilot_mo: np.ndarray, ncore: int, pilot_ncas: int, pilot_nelecas: int, bond_dim: int, job_dir: str,
) -> tuple[list[float], list[float]]:
    """Real DMRG-based single-orbital entropies (block2/pyblock2), for
    entropy_method='dmrg' -- the actual autoCAS mechanism (a cheap, low-
    bond-dimension, low-sweep-count DMRG-CI pilot pass), as opposed to
    _single_orbital_entropies's exact-FCI substitute. Exists specifically to
    let the pilot screen a much larger AVAS candidate pool than exact FCI's
    12-orbital ceiling allows (DMRG cost is polynomial, not combinatorial,
    in active-space size), at the cost of an approximate (not exact) entropy
    estimate and a slower job. Returns entropies/occupations in the SAME
    shape/convention as _single_orbital_entropies (pilot-active-block-local
    0-based index) so run_recommend_active_space's downstream code (plateau
    sweep, electron counting, mc.sort_mo final-CASSCF seeding) doesn't need
    to know which backend produced them.

    API calls below were verified directly against the installed block2
    package via inspect.signature/direct testing before being wired in
    here (see the plan for this feature): get_rhf_integrals reads
    mf.mo_coeff directly (hence the shallow mf copy with pilot_mo swapped
    in, so the caller's real mf is never mutated). SymmetryTypes.SZ
    (non-spin-adapted), not SU2, is used deliberately: get_orbital_entropies
    with SU2 hit a real, reproducible bug in this installed block2 version
    (0.5.3, built from source) for orb_type=1 -- its npdm-based fast path
    raises a pybind11 vector-cast error internally (an empty index mask
    that SU2's spin-adapted single-orbital-entropy expression produces
    doesn't cast cleanly to C++ VectorUInt16), and its slower MPO-based
    fallback (use_npdm=False) explicitly `return NotImplemented` for SU2
    at orb_type=1 in the installed source -- confirmed by reading both
    code paths directly. SZ mode hits neither: get_orbital_entropies
    worked immediately and its value matched _single_orbital_entropies's
    exact-FCI H2 equilibrium result (0.06792165) to 8 significant figures
    in a direct side-by-side test. The one consequence: get_1pdm returns
    a [alpha, beta] list of separate (n,n) matrices in SZ mode (confirmed
    directly), not SU2's single spin-summed matrix, so occupations are
    reconstructed as pdm_a[i,i]+pdm_b[i,i] -- the same na+nb quantity
    _single_orbital_entropies already returns, just combined explicitly
    here instead of coming pre-summed.
    """
    from pyblock2._pyscf.ao2mo import integrals as itg
    from pyblock2.driver.core import DMRGDriver, SymmetryTypes

    mf_pilot = copy.copy(mf)
    mf_pilot.mo_coeff = pilot_mo
    _ncas, n_elec, spin, ecore, h1e, g2e, orb_sym = itg.get_rhf_integrals(
        mf_pilot, ncore=ncore, ncas=pilot_ncas, g2e_symm=8,
    )

    scratch = os.path.join(job_dir, "dmrg_pilot_scratch")
    os.makedirs(scratch, exist_ok=True)
    driver = DMRGDriver(scratch=scratch, symm_type=SymmetryTypes.SZ, n_threads=N_CORES)
    driver.initialize_system(n_sites=pilot_ncas, n_elec=n_elec, spin=spin, orb_sym=orb_sym)
    mpo = driver.get_qc_mpo(h1e=h1e, g2e=g2e, ecore=ecore, iprint=0)
    ket = driver.get_random_mps(tag="PILOT", bond_dim=min(100, bond_dim), nroots=1)
    # Deliberately a cheap, UNCONVERGED pilot sweep schedule (few sweeps,
    # ramping to bond_dim) -- matching autoCAS's own stated design ("an
    # unconverged DMRG wavefunction with low bond dimension"), not a
    # tightly-converged production DMRG calculation.
    # Noise/threshold schedule tuned empirically, not guessed: a first draft
    # (noise dropping to 1e-5 after 2 sweeps then 0 after 4, thrds=1e-6) gave
    # a WRONG entropy (0.986 vs the correct ~0.690, a ~43% error) on a
    # deliberately hard test case (stretched H2, a genuine diradical -- the
    # same case validated in _single_orbital_entropies's own docstring) --
    # the DMRG optimization was landing in a poor local solution, not
    # actually converging, despite running without error. Holding noise at
    # 1e-4 for a full 4 sweeps (half the schedule) and tightening the
    # Davidson threshold to 1e-8 fixed it, confirmed correct (0.6903,
    # matching the exact-FCI reference) across 3 repeated trials with fresh
    # random MPS initializations -- not a one-off fluke.
    n_sweeps = 8
    bond_dims = [min(100, bond_dim)] * 2 + [bond_dim] * (n_sweeps - 2)
    noises = [1e-4] * 4 + [0.0] * (n_sweeps - 4)
    driver.dmrg(mpo, ket, n_sweeps=n_sweeps, bond_dims=bond_dims, noises=noises, thrds=[1e-8] * n_sweeps, iprint=0)

    entropies = [float(s) for s in driver.get_orbital_entropies(ket, orb_type=1)]
    pdm_a, pdm_b = driver.get_1pdm(ket)
    occupations = [float(pdm_a[i, i] + pdm_b[i, i]) for i in range(pilot_ncas)]
    return entropies, occupations


def _find_entropy_plateau(entropies: list[float], max_orbitals: int) -> tuple[list[int], float | None, bool]:
    """Sweeps a threshold down from just below the max entropy, recording
    how many orbitals would be selected (entropy > threshold) at each
    step, and looks for a plateau -- a threshold range where the selected
    count stays constant -- per autoCAS's own selection protocol (the
    0.14 value from the literature is a different, unrelated
    multiconfigurational-character diagnostic, not the selection cut
    itself; the real autoCAS selection is this threshold/plateau sweep).
    Returns (selected_orbital_indices, threshold_used, plateau_found).
    A plateau whose orbital count exceeds max_orbitals is skipped in favor
    of the next (smaller) one, so the recommendation always respects the
    user-facing cap; if no plateau survives this filter, returns
    (approx-cut-at-max_orbitals, None, False) -- a real, reported
    "no clear plateau" outcome rather than a silently fabricated cut.
    """
    order = np.argsort(-np.array(entropies))  # most-entangled first
    sorted_entropies = [entropies[i] for i in order]
    n = len(sorted_entropies)
    if n <= 1:
        return (list(order[:n]), None, False)
    # thresholds strictly between consecutive sorted entropy values -- the
    # selected count is constant (=k+1) across each such interval by
    # construction, so "plateau" reduces to: the biggest gap in the sorted
    # entropy values IS the widest stable-count threshold range. Rank gaps
    # descending and take the first one whose selected count respects the
    # user-facing cap.
    candidate_thresholds = [(sorted_entropies[k] + sorted_entropies[k + 1]) / 2 for k in range(n - 1)]
    gaps = [sorted_entropies[k] - sorted_entropies[k + 1] for k in range(n - 1)]
    ranked_gap_positions = sorted(range(n - 1), key=lambda k: -gaps[k])
    # count >= 2: a single-orbital "active space" is degenerate (it can host
    # only one many-electron configuration at most, never enough for a real
    # active space, let alone multiple state-averaged states) -- confirmed
    # as a real failure mode, not a hypothetical one: a real uracil/cc-pVDZ
    # run picked count=1 here (a lone high-entropy outlier orbital made the
    # single widest gap the very first one), producing a (0e,1o) "active
    # space" that crashed deep inside pyscf's CASSCF _finalize() with an
    # opaque IndexError once n_states=3 couldn't be satisfied. Skipping any
    # candidate gap with count < 2 rules this out at the source, rather
    # than only catching its downstream symptom.
    for k in ranked_gap_positions:
        count = k + 1
        if 2 <= count <= max_orbitals and gaps[k] > 1e-3:
            threshold = candidate_thresholds[k]
            selected = [int(order[j]) for j in range(count)]
            return (selected, threshold, True)
    count = min(max_orbitals, n)
    count = max(count, min(2, n))  # same floor for the no-plateau-found fallback
    selected = [int(order[j]) for j in range(count)]
    return (selected, None, False)


def run_recommend_active_space(molecule: dict, params: dict) -> dict:
    """AutoCAS-style Single-Orbital-Entropy active-space recommendation,
    run as one sequential in-process pipeline (same "one job_id, several
    stages" shape as run_neb_ts, not pes_scan's master/sub-job fan-out --
    every stage here depends on the previous one's in-memory result, there
    is no independent parallel work to fan out). See the
    recommend_active_space plan for the full algorithm derivation.
    print(..., flush=True) at each stage lands directly in worker.log,
    which the job panel's live log tail already reads -- no new
    "sub-calculation visible in the panel" machinery needed."""
    mol = build_mole(molecule, params["basis"])
    if mol.spin != 0:
        raise ValueError(
            "recommend_active_space currently only supports closed-shell molecules "
            "(this pilot's electron-counting/truncation math assumes a closed-shell reference)."
        )

    print(f"[recommend_active_space] RHF on {mol.natm} atoms, basis={params['basis']}", flush=True)
    mf = scf.RHF(mol)
    mf.kernel()
    if not mf.converged:
        raise RuntimeError("SCF did not converge; try a different initial guess or check the input")

    # entropy_method picks the pilot screening backend only -- the FINAL
    # recommended active space and its CASSCF are identical either way, so
    # max_active_orbitals is validated against _PILOT_CAS_CEILING
    # unconditionally (that's the final-CASSCF ceiling, not the pilot's).
    entropy_method = params.get("entropy_method") or "exact_fci"
    if entropy_method not in ("exact_fci", "dmrg"):
        raise ValueError(f"Unknown entropy_method '{entropy_method}' -- must be 'exact_fci' or 'dmrg'.")
    dmrg_bond_dim = int(params.get("dmrg_bond_dim") or 250)
    pilot_ceiling = _DMRG_PILOT_CAS_CEILING if entropy_method == "dmrg" else _PILOT_CAS_CEILING

    max_active_orbitals = int(params.get("max_active_orbitals") or 12)
    if max_active_orbitals > _PILOT_CAS_CEILING:
        raise ValueError(
            f"max_active_orbitals={max_active_orbitals} exceeds the {_PILOT_CAS_CEILING}-orbital final-CASSCF "
            f"ceiling on this host -- this is a user-supplied number, not something AVAS produced, so "
            f"it's refused outright rather than silently capped. Ask for {_PILOT_CAS_CEILING} or fewer. "
            f"(This ceiling applies regardless of entropy_method -- DMRG only widens the pilot SCREENING "
            f"pool, not the final recommended space.)"
        )
    aolabels = params.get("avas_aolabels") or _default_avas_aolabels(mol)
    print(f"[recommend_active_space] AVAS pilot space, aolabels={aolabels}", flush=True)
    avas_ncas, avas_nelecas, avas_mo = avas.avas(mf, aolabels)
    if avas_ncas == 0:
        raise RuntimeError(f"AVAS found no orbitals matching {aolabels} -- try different avas_aolabels.")

    ncore = (mol.nelectron - avas_nelecas) // 2
    n_occ_active = avas_nelecas // 2
    n_virt_active = avas_ncas - n_occ_active
    pilot_space_truncated = False
    if avas_ncas > pilot_ceiling:
        keep_virt = min(pilot_ceiling - pilot_ceiling // 2, n_virt_active)
        keep_occ = min(pilot_ceiling - keep_virt, n_occ_active)
        keep_virt = min(pilot_ceiling - keep_occ, n_virt_active)
        # boundary = column where occupied-active ends / virtual-active begins.
        # The KEPT (near-Fermi) orbitals become the pilot's active block; every
        # DESELECTED occupied-active orbital must fold into the pilot's own
        # core block (not just the original ncore -- pilot CASCI's own ncore
        # is (mol.nelectron - pilot_nelecas)//2, which is larger than the
        # original ncore whenever keep_occ < n_occ_active, so the column
        # layout must supply exactly that many core columns or CASCI's own
        # check_sanity() rejects the mo_coeff outright -- confirmed on a real
        # uracil/STO-3G run, where an earlier version of this reordering
        # undercounted the core block and hit "assert nvir >= 0").
        # Deselected virtual-active orbitals fold into the pilot's virtual
        # block the same way.
        boundary = ncore + n_occ_active
        col_start, col_end = boundary - keep_occ, boundary + keep_virt
        pilot_mo = np.hstack([
            avas_mo[:, :ncore],                              # original core, untouched
            avas_mo[:, ncore:col_start],                     # deselected occ-active -> pilot's core
            avas_mo[:, col_start:col_end],                   # SELECTED near-Fermi orbitals -> pilot's active space
            avas_mo[:, col_end:boundary + n_virt_active],    # deselected virt-active -> pilot's virtual
            avas_mo[:, boundary + n_virt_active:],           # original AVAS virtuals beyond the active block, untouched
        ])
        pilot_ncas, pilot_nelecas = keep_occ + keep_virt, 2 * keep_occ
        pilot_space_truncated = True
        print(
            f"[recommend_active_space] AVAS pilot space ({avas_ncas} orbitals) exceeds the "
            f"{pilot_ceiling}-orbital {entropy_method} pilot ceiling -- truncating to the {pilot_ncas} orbitals "
            f"nearest the Fermi level.", flush=True,
        )
    else:
        pilot_mo, pilot_ncas, pilot_nelecas = avas_mo, avas_ncas, avas_nelecas

    # F-020, the fail-fast half. The selected space is a SUBSET of the
    # pilot space, so if the whole pilot space cannot host n_states then no
    # selection drawn from it can either -- and that is knowable right
    # here, before the pilot CASCI/DMRG, the entropy computation, the
    # plateau search and the plot. That ordering is the actual complaint
    # behind F-020: a request that was never satisfiable spent the entire
    # expensive pipeline before saying so.
    #
    # Real case: water/STO-3G with the default `O 2p` AVAS labels gives a
    # 3-orbital, 6-electron pilot space -- completely full, exactly one
    # configuration, so even 2 states is impossible. Widening within the
    # pilot space (below) cannot help; only a larger pilot space can, and
    # that is a decision for the caller, so this says which knob to turn.
    # avas.avas returns nelecas as a scalar (a numpy int64, which is NOT an
    # instance of int -- checking that was this line's first mistake), but
    # pyscf's CAS APIs also accept an (nalpha, nbeta) tuple, so accept both.
    _pilot_nelec = int(sum(pilot_nelecas)) if isinstance(pilot_nelecas, (tuple, list)) else int(pilot_nelecas)
    _pilot_alpha = _pilot_beta = _pilot_nelec // 2
    _pilot_configs = math.comb(int(pilot_ncas), _pilot_alpha) * math.comb(int(pilot_ncas), _pilot_beta)
    _n_states_req = params.get("n_states", 1)
    if _pilot_configs < _n_states_req:
        raise RuntimeError(
            f"The AVAS pilot space for this molecule ({_pilot_nelec}e,{int(pilot_ncas)}o) can host at "
            f"most {_pilot_configs} many-electron configuration(s), fewer than the {_n_states_req} "
            f"states requested -- and the recommended space is always a subset of it, so no "
            f"selection could satisfy this. Widen the pilot space with avas_aolabels (e.g. add "
            f"'O 2s' or the virtual shells for your system), use a larger basis set, or request "
            f"fewer states. Stopping before the pilot calculation rather than after it."
        )

    if entropy_method == "dmrg":
        print(
            f"[recommend_active_space] pilot DMRG({pilot_nelecas},{pilot_ncas}), "
            f"bond_dim={dmrg_bond_dim} (block2, low-sweep pilot)", flush=True,
        )
        # ncore for the pilot's own active-block offset within pilot_mo -- the
        # same value mc.sort_mo below needs (same formula pilot_mc.ncore
        # would give in the exact-FCI branch, computed directly here since
        # there's no mcscf.CASCI object in the DMRG branch to read it from).
        pilot_ncore = (mol.nelectron - pilot_nelecas) // 2
        entropies, occupations = _pilot_entropies_dmrg(
            mf, pilot_mo, pilot_ncore, pilot_ncas, pilot_nelecas, dmrg_bond_dim, params["_job_dir"],
        )
    else:
        print(f"[recommend_active_space] pilot CASCI({pilot_nelecas},{pilot_ncas}) (exact FCI)", flush=True)
        pilot_mc = mcscf.CASCI(mf, pilot_ncas, pilot_nelecas)
        pilot_mc.kernel(pilot_mo)
        if not pilot_mc.converged:
            raise RuntimeError("Pilot CASCI did not converge.")
        print("[recommend_active_space] computing single-orbital entropies", flush=True)
        entropies, occupations = _single_orbital_entropies(pilot_mc)
        pilot_ncore = pilot_mc.ncore

    selected, threshold, plateau_found = _find_entropy_plateau(entropies, max_active_orbitals)
    selected_sorted = sorted(selected)

    def _space_for(indices: list[int]) -> tuple[int, int]:
        """(n_elec, n_orb) for a given set of pilot-local orbital indices.

        Electron count: sum of each selected orbital's active-space
        occupation (na+nb from the pilot CASCI's own 1-RDM diagonal, in
        the pilot's own basis -- see _single_orbital_entropies), rounded
        to the nearest even integer for a closed-shell active space.
        """
        occ_sum = float(sum(occupations[i] for i in indices))
        n_e = int(round(occ_sum))
        if n_e % 2 != 0:
            n_e += 1 if (occ_sum - n_e) > 0 else -1
        return max(0, min(n_e, 2 * len(indices))), len(indices)

    # F-020: make the recommendation satisfy the request instead of
    # selecting a space and then rejecting it.
    #
    # n_states is known before selection ever runs, but the sanity check
    # below used to be the ONLY place it was consulted -- so a perfectly
    # reasonable request (3 states of water/STO-3G) could run the whole
    # expensive pilot pipeline, land on a two-orbital plateau, and fail
    # after the fact on a constraint that was knowable up front. Entropy
    # ordering already ranks every pilot orbital, so the space is now
    # widened along that same ranking -- the next-most-entangled orbitals,
    # not arbitrary ones -- until it can host the states asked for.
    #
    # Bounds are unchanged: max_active_orbitals (the user's own cap) and
    # the pilot space itself. If widening to those limits still isn't
    # enough, the original error stands, which is the right last-resort
    # answer and its text is genuinely good.
    n_states_wanted = params.get("n_states", 1)

    def _n_configurations(indices: list[int]) -> int:
        n_e, n_o = _space_for(indices)
        n_a = n_b = n_e // 2
        return math.comb(n_o, n_a) * math.comb(n_o, n_b)

    def _can_host(indices: list[int]) -> bool:
        return _n_configurations(indices) >= n_states_wanted

    widened_from = None
    if not _can_host(selected_sorted):
        widened_from = len(selected_sorted)
        remaining = set(range(len(entropies))) - set(selected_sorted)
        # Greedy on the quantity actually being satisfied -- the number of
        # many-electron configurations the space can host -- with entropy
        # as the tie-break.
        #
        # Adding the next-most-entangled orbital is NOT sufficient on its
        # own, confirmed by running exactly the case the plan names (3
        # states of water/STO-3G): entropy ranks the strongly-occupied
        # orbitals first, and each one brings ~2 electrons with it, so the
        # space grows while staying completely full -- (4e,2o) widened to
        # (6e,3o), still exactly ONE configuration, and the job failed on
        # the same error it was widened to avoid. What actually creates
        # room for excited states is adding orbitals that are NOT fully
        # occupied, and ranking candidates by the resulting configuration
        # count selects those without having to special-case occupancy.
        while remaining and len(selected_sorted) < max_active_orbitals:
            best = max(
                remaining,
                key=lambda i: (_n_configurations(sorted(selected_sorted + [i])), entropies[i]),
            )
            remaining.discard(best)
            selected_sorted = sorted(selected_sorted + [best])
            if _can_host(selected_sorted):
                break
        if _can_host(selected_sorted):
            print(
                f"[recommend_active_space] widened the recommended space from "
                f"{widened_from} to {len(selected_sorted)} orbitals so it can host the "
                f"{n_states_wanted} requested states", flush=True,
            )
        else:
            widened_from = None  # nothing usable found; fall through to the error below

    n_elec, n_orb = _space_for(selected_sorted)

    plateau_png = os.path.join(params["_job_dir"], "entropy_plateau.png")
    from app.chemistry.spectrum import render_entropy_plateau_plot
    render_entropy_plateau_plot(entropies, threshold, selected_sorted, plateau_png)

    findings_summary = (
        f"Pilot valence space of {pilot_ncas} orbitals ({'AVAS-seeded, truncated to the ' + str(pilot_ncas) + ' nearest the Fermi level' if pilot_space_truncated else 'AVAS-seeded'}); "
        + (
            f"a plateau was found selecting {n_orb} orbitals at threshold {threshold:.4f}"
            if plateau_found else
            f"no clear entropy plateau was found -- reporting the {n_orb} highest-entropy orbitals "
            f"(capped at max_active_orbitals={max_active_orbitals}) as a best-effort recommendation"
        )
        + (
            f"; widened from {widened_from} to {n_orb} orbitals along the same entropy "
            f"ranking so the space can host the {params.get('n_states', 1)} requested states"
            if widened_from is not None else ""
        )
        + f"; recommended active space: ({n_elec}e, {n_orb}o)."
    )
    print(f"[recommend_active_space] {findings_summary}", flush=True)

    weights = params.get("weights")
    n_states = params.get("n_states", 1)

    # Pre-flight sanity check: the recommended (n_elec, n_orb) active space
    # must be able to host at least n_states distinct many-electron
    # configurations, or state-averaged CASSCF has nothing to average over.
    # An upper bound on that count (C(n_orb, n_alpha) * C(n_orb, n_beta),
    # ignoring symmetry/spin-coupling reductions that could only shrink it
    # further) catches an unusably small recommended space HERE, with a
    # clear, actionable message -- rather than letting mc.kernel() silently
    # produce fewer CI roots than requested and crash deep inside pyscf's
    # own CASSCF _finalize()/spin_square() with an opaque IndexError, which
    # is exactly what happened on a real uracil/cc-pVDZ run before this
    # check existed (see _find_entropy_plateau's count>=2 floor for the
    # other half of this fix).
    #
    # F-020: this is now the LAST resort rather than the first response.
    # The selection step above already widens the space along the entropy
    # ranking to satisfy n_states where it can, so reaching this error means
    # even the full pilot space under the user's own max_active_orbitals cap
    # genuinely cannot host the request -- which is worth failing on, and
    # this message says the right thing about it.
    n_alpha = n_beta = n_elec // 2
    max_possible_states = math.comb(n_orb, n_alpha) * math.comb(n_orb, n_beta)
    if max_possible_states < n_states:
        raise RuntimeError(
            f"The recommended active space ({n_elec}e,{n_orb}o) can host at most "
            f"{max_possible_states} many-electron configuration(s), fewer than the "
            f"{n_states} states requested -- and widening it along the entropy ranking "
            f"up to max_active_orbitals={max_active_orbitals} was not enough. Try "
            f"requesting fewer states, or raising max_active_orbitals if there's room "
            f"under the current cap."
        )

    print(f"[recommend_active_space] final state-averaged CASSCF({n_elec},{n_orb}) for {n_states} state(s)", flush=True)

    mc = _build_casscf(mf, n_orb, n_elec, n_states, weights, CASSCF_CONV_TOL_ENERGY)
    # Seed the final CASSCF's active space with EXACTLY the entropy-selected
    # pilot orbitals (not just "some orbitals near the Fermi level", which is
    # all a plain mf.mo_coeff guess would give): mc.sort_mo(caslst, ...) is
    # pyscf's own mechanism for this -- it correctly recomputes the
    # core/active/virtual column split for a target CASSCF object's own
    # (n_elec-derived) ncore, which a hand-rolled column reorder got wrong in
    # an earlier draft of this function whenever the final n_elec didn't
    # happen to match the pilot's own occupied/virtual split exactly.
    # selected_sorted indices are local to the pilot's active block
    # (pilot_mo columns [pilot_ncore : pilot_ncore+pilot_ncas]) -- use
    # pilot_ncore, NOT the original ncore, to shift to 0-based global column
    # indices into pilot_mo: these differ whenever the pilot space was
    # truncated (pilot_ncore then also absorbs the deselected occupied-active
    # orbitals folded into the pilot's own core block, see the truncation
    # block above). pilot_ncore is set identically by both entropy_method
    # branches above (from pilot_mc.ncore in the exact-FCI branch, computed
    # directly -- same formula -- in the DMRG branch, which has no CASCI
    # object to read it from).
    caslst = [pilot_ncore + i for i in selected_sorted]
    seed_mo = mc.sort_mo(caslst, mo_coeff=pilot_mo, base=0)
    mc.kernel(seed_mo)
    if not mc.converged:
        # pyscf's default CASSCF solver (a first-order, CI-then-orbital-
        # rotation macro/micro-iteration scheme) can fail to converge for a
        # genuinely hard state-averaged case even though the active space
        # itself is perfectly reasonable -- confirmed as a real, reproducible
        # failure mode on a live uracil/cc-pVDZ/(8e,7o)/3-states run, not a
        # hypothetical: the default solver stalled from the DMRG-pilot-
        # derived starting orbitals every time, on two separate retries with
        # different max_active_orbitals caps that both landed on the same
        # active space. mcscf.newton() (augmented-Hessian second-order
        # Newton-Raphson) is pyscf's own documented, standard answer for
        # exactly this -- more expensive per iteration but converges more
        # reliably from a difficult starting point. Tried automatically as a
        # fallback (not the default, since it's slower) rather than just
        # giving up after one attempt.
        print("[recommend_active_space] default CASSCF solver did not converge -- "
              "retrying with the more robust Newton-Raphson solver", flush=True)
        mc = mcscf.newton(mc)
        mc.kernel(seed_mo)
        if not mc.converged:
            raise RuntimeError(
                "Final state-averaged CASSCF did not converge, even with the Newton-Raphson "
                "fallback solver. This active space/state combination may need a different "
                "starting guess or fewer states -- consider asking the user before retrying blindly."
            )

    active_space_orbital_indices = list(range(mc.ncore + 1, mc.ncore + mc.ncas + 1))

    molden_path, orbital_table = _casscf_molden_and_table(mc, params["_job_dir"])

    energies = np.atleast_1d(mc.e_states if hasattr(mc, "e_states") and n_states > 1 else mc.e_tot).tolist()
    summary = {
        "literature_notes": params.get("literature_notes"),
        "findings_summary": findings_summary,
        "recommended_active_electrons": n_elec,
        "recommended_active_orbitals": n_orb,
        "active_space_orbital_indices": active_space_orbital_indices,
        "entropy_method": entropy_method,
        "dmrg_bond_dim": dmrg_bond_dim if entropy_method == "dmrg" else None,
        "pilot_space_orbitals": pilot_ncas,
        "pilot_space_truncated": pilot_space_truncated,
        "entropy_threshold_used": threshold,
        "plateau_found": plateau_found,
        "pilot_orbital_entropies": entropies,
        "state_energies_hartree": energies if n_states > 1 else [float(mc.e_tot)],
        "n_states": n_states,
        "converged": bool(mc.converged),
        "reference_hf_energy_hartree": float(mf.e_tot),
        "dominant_transitions": _dominant_transitions_casscf(mc, n_states),
        "orbital_table": orbital_table,
        "orbital_table_note": (
            "Natural orbitals with active-space occupation numbers, plus character (sigma/pi/n/sigma*/pi*, "
            "best-effort from point-sampling -- see classify_orbital_character) and dominant localized atom(s). "
            "Rows active_space_orbital_indices are the recommended active space."
        ),
        "method_note": (
            (
                "Single-orbital entropies are exact-FCI (pyscf CASCI), not literal DMRG -- the identical "
                "quantity autoCAS approximates via DMRG, computed exactly here because the AVAS-seeded pilot "
                f"space was small enough for exact FCI (capped at {_PILOT_CAS_CEILING} orbitals)."
                if entropy_method == "exact_fci" else
                f"Single-orbital entropies are from a real DMRG pilot (block2, bond_dim={dmrg_bond_dim}, "
                f"low-sweep/unconverged pilot pass per autoCAS's own 'cheap pilot' design), letting the "
                f"AVAS-seeded pilot space grow up to {_DMRG_PILOT_CAS_CEILING} orbitals instead of the "
                f"{_PILOT_CAS_CEILING}-orbital exact-FCI ceiling -- a more basis-faithful screening pool, "
                f"at the cost of an approximate (not exact) entropy estimate."
            )
            + (
                " The pilot space was truncated relative to the full AVAS-selected valence space -- "
                "treat this recommendation as an approximation." if pilot_space_truncated else ""
            )
        ),
    }
    return {"summary": summary, "artifacts": {"molden": molden_path, "entropy_plateau": plateau_png}}


def _rank_amplitudes(xarr: np.ndarray, occ_offset: int, virt_offset: int, max_results: int) -> list[tuple[int, int, float]]:
    """Top `max_results` (source_orbital_1based, target_orbital_1based,
    weight) triples from a (nocc, nvirt) amplitude array, weight = X^2 --
    argpartition-based so this stays cheap even for a large active space,
    unlike a full sort of every (occ, virt) pair."""
    flat = xarr.ravel()
    if flat.size == 0:
        return []
    k = min(max_results, flat.size)
    top_idx = np.argpartition(np.abs(flat), -k)[-k:]
    top_idx = top_idx[np.argsort(-np.abs(flat[top_idx]))]
    results = []
    for idx in top_idx:
        occ_i, virt_i = np.unravel_index(int(idx), xarr.shape)
        results.append((int(occ_i) + occ_offset, int(virt_i) + virt_offset, float(flat[idx]) ** 2))
    return results


def _dominant_transition(x, nelec: tuple[int, int]) -> str | None:
    """Top-2 (by |amplitude|) orbital-number transitions from a
    td.xy[state][0] (X) amplitude array, weight = X^2 -- Y (de-excitation
    amplitudes) is ignored, exact for TDA (where Y=0) and a standard
    approximation for full TDDFT/RPA where X dominates. `x` is a plain
    (nocc, nvirt) array for a restricted reference, or a (alpha, beta)
    tuple of such arrays for ROHF/ROKS (verified empirically: tdscf.TDA on
    an ROHF reference returns per-spin X arrays with different occ/virt
    counts per channel, not one combined array) -- candidates from both
    spins are ranked together, so an open-shell reference's top-2 may mix
    spin channels."""
    candidates: list[tuple[int, int, float]] = []
    if isinstance(x, tuple):
        for spin, xs in enumerate(x):
            xarr = np.asarray(xs)
            if xarr.size == 0:
                continue
            nocc = nelec[spin]
            candidates.extend(_rank_amplitudes(xarr, 1, nocc + 1, 2))
    else:
        xarr = np.asarray(x)
        if xarr.size == 0:
            return None
        nocc = xarr.shape[0]
        candidates.extend(_rank_amplitudes(xarr, 1, nocc + 1, 2))
    if not candidates:
        return None
    ranked = sorted(candidates, key=lambda c: c[2], reverse=True)[:2]
    return format_dominant(ranked)


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
    use_tda = params.get("use_tda", False)
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
    molden_path, summary["orbital_table"] = _write_molden_and_table(params["_job_dir"], mf)
    # The table is the ground-state reference SCF orbitals TDA/TDDFT builds
    # its excitations from (the same orbitals dominant_transitions' orbital
    # numbers refer to), not correlated/relaxed excited-state natural
    # orbitals -- worth saying explicitly rather than leaving the user to
    # guess which orbitals they're looking at.
    summary["orbital_table_note"] = (
        "These are the ground-state reference orbitals used to build the excitations above, "
        "not excited-state-relaxed natural orbitals."
    )
    return {"summary": summary, "artifacts": {"molden": molden_path}}


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
    molden_path, summary["orbital_table"] = _write_molden_and_table(params["_job_dir"], mf)
    summary["orbital_table_note"] = (
        "These are the ground-state HF reference orbitals CCSD/EOM-CCSD was built from, "
        "not correlated natural orbitals."
    )
    return {"summary": summary, "artifacts": {"molden": molden_path}}


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

    # Also export a molden file, even though PySCF's own cube generation
    # above doesn't need one -- this lets the lazy per-orbital cube
    # endpoint (any orbital, not just the ones requested at submit time)
    # use the same app.chemistry.jobs.molden path for all three engines
    # instead of PySCF needing its own separate re-generation branch.
    molden_path, orbital_table = _write_molden_and_table(job_dir, mf)

    summary = {
        "homo_index_1based": homo_idx + 1,
        "orbitals_rendered": {label: idx + 1 for label, idx in indices.items()},
        "mo_energies_eV": {label: float(mf.mo_energy[idx] * 27.211386245988) for label, idx in indices.items()},
        "orbital_table": orbital_table,
    }
    return {"summary": summary, "artifacts": {"cubes": cube_paths, "molden": molden_path}}


# pes_scan is no longer a directly-dispatched job_type (see
# app/chemistry/jobs/base.py's JobManager.submit_scan and
# app/chemistry/jobs/scan_orchestrator.py) -- a scan runs as one "master"
# job that spawns a real single_point/tddft/casscf/... sub-job per image
# instead of computing every point sequentially in-process the way the old
# run_pes_scan did. build_coordinate_scan_images below is the one piece of
# that old code path still reused, for the single-molecule bond/angle/
# dihedral scan mode -- app/chemistry/jobs/interpolate.py covers the
# two-endpoint interpolation modes (linear/liic/idpp) that replace the old
# _liic_cartesian Cartesian-only path.


def build_coordinate_scan_images(
    molecule: dict, coordinate: dict, scan_range: list[float], n_points: int,
) -> tuple[list[dict], list[float]]:
    """Public wrapper around _internal_coordinate_scan, for
    app/agent/tools.py's _build_scan_images -- kept as its own function
    (rather than making the underscore-prefixed helper itself public) so
    every other module still reaching for RDKit-based scan geometry
    generation goes through one clearly-intentional entry point."""
    return _internal_coordinate_scan(molecule, coordinate, scan_range, n_points)


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
        geom["symbols"] = list(molecule["symbols"])  # independent list, not shared across images -- see interpolate.py's _image
        geom["coords"] = new_coords
        geometries.append(geom)

    return geometries, values
