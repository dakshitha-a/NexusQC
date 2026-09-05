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
from types import SimpleNamespace

import numpy as np
from pyscf import gto, scf, dft, lib, mcscf, tdscf
from pyscf.tools import cubegen, molden
from pyscf.hessian import thermo as pyscf_thermo
from pyscf.mcscf import avas

from app.chemistry.jobs import derivatives
from app.chemistry.jobs.ci_transitions import (
    aggregate_by_configuration, format_dominant, leading_single_excitations, reference_configuration,
)
from app.chemistry.jobs.molden import classify_orbital_character
from app.chemistry.jobs.vibrations import summarize_frequencies
from app.config import (
    CASSCF_CONV_TOL_ENERGY, CASSCF_CONV_TOL_OPT_FREQ, CASSCF_MAX_CYCLE_MACRO, MAX_MEMORY_MB, N_CORES,
)

# The real cap comes from the environment JobManager creates the worker
# subprocess with (see engine_thread_env in app/config.py); by the time this
# module runs, libgomp and OpenBLAS have already read their variables and an
# assignment here would do nothing. This line used to be a setdefault of
# OMP_NUM_THREADS, placed after the pyscf import, and it never had any effect:
# `lib.num_threads()` reported 255 inside the container.
#
# lib.num_threads() calls omp_set_num_threads, which does work at runtime, so
# it stays as a second line of defence for a run_* function invoked directly
# rather than through a worker -- the testing snippet in CLAUDE.md, say.
lib.num_threads(N_CORES)


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
        "from pyscf.csf_fci import csf_solver",
        "mf = scf.RHF(mol) if mol.spin == 0 else scf.ROHF(mol)",
        f"mc = mcscf.CASSCF(mf, {params['active_orbitals']}, {params['active_electrons']})",
        f"mc.conv_tol = {conv_tol}",
        f"mc.max_cycle_macro = {CASSCF_MAX_CYCLE_MACRO}",
        # Part of what the calculation IS, not how it is set up: without it
        # a state average returns the lowest roots of any multiplicity.
        "mc.fcisolver = csf_solver(mol, smult=mol.spin + 1)"
        "  # every root has the molecule's own multiplicity",
    ]
    if n_states > 1:
        weights = params.get("weights") or [1.0 / n_states] * n_states
        lines.append(f"mc = mc.state_average_({weights})")
    # The named active space, if the user gave one. Shown on the approval
    # card because it changes which calculation this is, not just how it
    # is set up -- a card that hid it would look identical to one for the
    # engine's own default space.
    named = params.get("active_space_orbital_indices")
    if named:
        lines.append(f"mc.mo_coeff = mc.sort_mo({[int(i) for i in named]}, base=1)")
    return lines


def _pdft_preview_lines(params: dict, method: str, conv_tol: float) -> list[str]:
    """The pair-density analogue of `_casscf_preview_lines`.

    Kept separate rather than folded in with a flag, because these build
    genuinely different objects: the constructor takes the on-top
    functional as its second argument, and the two multi-state variants
    then wrap the result in a multi_state call that is what makes them
    L-PDFT or CMS-PDFT at all."""
    n_states = params.get("n_states", 1)
    ot = params.get("ot_functional")
    lines = [
        "from pyscf import mcpdft",
        "mf = scf.RHF(mol) if mol.spin == 0 else scf.ROHF(mol)",
        f"mc = mcpdft.CASSCF(mf, '{ot}', {params.get('active_orbitals')}, "
        f"{params.get('active_electrons')})",
        f"mc.conv_tol = {conv_tol}",
        f"mc.max_cycle_macro = {CASSCF_MAX_CYCLE_MACRO}",
    ]
    weights = params.get("weights") or ([1.0 / n_states] * n_states if n_states > 1 else None)
    # Without this the state average returns the lowest roots of ANY
    # multiplicity, which for a closed-shell molecule silently mixes
    # triplets in and zeroes every transition dipole. It must be the CSF
    # solver rather than fix_spin_'s penalty: for CMS-PDFT the penalty
    # leaks into the stored MCSCF energies and the method aborts on its
    # own consistency check. Showing fix_spin_ here would hand the reader
    # a script that cannot run.
    lines.insert(0, "from pyscf.csf_fci import csf_solver")
    lines.append("mc.fcisolver = csf_solver(mol, smult=mol.spin + 1)"
                 "  # same multiplicity as the ground state")
    if method in ("lpdft", "cmspdft"):
        arg = "'LIN'" if method == "lpdft" else "'cms'"
        label = "L-PDFT" if method == "lpdft" else "CMS-PDFT"
        lines.append(f"mc = mc.multi_state({weights}, {arg})  # {label}")
    elif n_states > 1:
        lines.append(f"mc = mc.state_average_({weights})")
    named = params.get("active_space_orbital_indices")
    if named:
        lines.append(f"mc.mo_coeff = mc.sort_mo({[int(i) for i in named]}, base=1)")
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
            if params.get("n_states", 1) > 1:
                st = int(params.get("target_state") or 0)
                lines.append("mc.kernel()")
                lines.append(f"scanner = mc.nuc_grad_method().as_scanner(state={st})  "
                             f"# a state average's own energy is the mean over roots")
                lines.append(f"mol_eq = optimize(scanner, maxsteps={params.get('max_steps', 200)})")
            else:
                lines.append(f"mol_eq = optimize(mc, maxsteps={params.get('max_steps', 200)})")
        elif method in PDFT_METHODS:
            state_index = int(params.get("target_state") or 0)
            lines += _pdft_preview_lines(params, method, CASSCF_CONV_TOL_OPT_FREQ)
            lines.append("mc.kernel()  # must be converged before the scanner is built")
            lines.append(
                f"scanner = mc.nuc_grad_method().as_scanner(state={state_index})  "
                f"# the state-average energy has no gradient; only the states do")
            lines.append(f"mol_eq = optimize(scanner, maxsteps={params.get('max_steps', 200)})")
        else:
            lines += _mf_lines(method, functional)
            lines.append(f"mol_eq = optimize(mf, maxsteps={params.get('max_steps', 200)})")
    elif job_type == "frequency":
        if method == "casscf":
            multi = params.get("n_states", 1) > 1
            st = int(params.get("target_state") or 0)
            lines += _casscf_preview_lines(params, CASSCF_CONV_TOL_OPT_FREQ)
            lines.append("mc.kernel()")
            lines.append("from app.chemistry.jobs.pyscf_runner import _numerical_casscf_hessian")
            lines.append(
                f"hess = _numerical_casscf_hessian(mc{f', state={st}' if multi else ''})  "
                f"# no analytic CASSCF Hessian in pyscf")
            lines.append("from pyscf.hessian import thermo")
            lines.append("freq_info = thermo.harmonic_analysis(mol, hess)")
            if multi:
                lines.append("from types import SimpleNamespace")
                lines.append(f"state_model = SimpleNamespace(mol=mol, e_tot=mc.e_states[{st}])  "
                             f"# state {st}'s own energy, not the state average")
                lines.append(f"thermo_info = thermo.thermo(state_model, freq_info['freq_au'], "
                             f"{params.get('temperature_K', 298.15)})")
            else:
                lines.append(f"thermo_info = thermo.thermo(mc, freq_info['freq_au'], "
                             f"{params.get('temperature_K', 298.15)})")
        elif method in PDFT_METHODS:
            state_index = int(params.get("target_state") or 0)
            lines += _pdft_preview_lines(params, method, CASSCF_CONV_TOL_OPT_FREQ)
            lines.append("mc.kernel()")
            lines.append("from app.chemistry.jobs.pyscf_runner import _numerical_casscf_hessian")
            lines.append(
                f"hess = _numerical_casscf_hessian(mc, state={state_index})  "
                f"# no analytic Hessian for either pair-density method")
            lines.append("from pyscf.hessian import thermo")
            lines.append("freq_info = thermo.harmonic_analysis(mol, hess)")
            # thermo() reads only `mol` and `e_tot` off what it is given, and
            # on a state-averaged object `e_tot` is the mean over roots
            # rather than this state's energy. The shim is emitted in full
            # rather than referred to, because this preview is meant to be a
            # script a reader can actually run.
            lines.append("from types import SimpleNamespace")
            state_energy = (f"mc.e_states[{state_index}]" if params.get("n_states", 1) > 1
                            else "mc.e_tot")
            lines.append(
                f"state_model = SimpleNamespace(mol=mol, e_tot={state_energy})  "
                f"# state {state_index}'s own energy, not the state average")
            lines.append(
                f"thermo_info = thermo.thermo(state_model, freq_info['freq_au'], "
                f"{params.get('temperature_K', 298.15)})")
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
            lines.append("# use engine='orca' (adds DoDipoleLength) or engine='bagel' (a forces")
            lines.append("# block with dipole set) for UV/Vis intensities")
    elif job_type == "nevpt2":
        n_states = params.get("n_states", 1)
        lines += _casscf_preview_lines(params, CASSCF_CONV_TOL_ENERGY)
        lines.append("mc.kernel()")
        lines.append("from pyscf import mrpt")
        if n_states > 1:
            lines.append("# NEVPT2 refuses a state-averaged solver, so the roots are rebuilt")
            lines.append("# as a multi-root CASCI in the state-averaged orbitals:")
            lines.append(f"ci = mcscf.CASCI(mf, {params.get('active_orbitals')}, "
                         f"{params.get('active_electrons')})")
            lines.append(f"ci.fcisolver.nroots = {n_states}")
            lines.append("ci.kernel(mc.mo_coeff)")
            lines.append(f"corrections = [mrpt.NEVPT(ci, root=r).kernel() for r in range({n_states})]")
            lines.append("state_energies = [e + c for e, c in zip(ci.e_tot, corrections)]")
        else:
            lines.append("e_corr = mrpt.NEVPT(mc).kernel()")
            lines.append("energy = mc.e_tot + e_corr")
        lines.append("# energies only -- pyscf.mrpt exposes no NEVPT2 gradient,")
        lines.append("# so there is no optimization or frequency path for this method")
    elif job_type in PDFT_METHODS:
        lines += _pdft_preview_lines(params, job_type, CASSCF_CONV_TOL_ENERGY)
        lines.append("mc.kernel()")
        if params.get("n_states", 1) > 1:
            lines.append("state_energies = mc.e_states")
        else:
            lines.append("energy = mc.e_tot")
        if job_type == "cmspdft":
            lines.append("# f = (2/3) dE |mu|^2, in atomic units throughout:")
            lines.append("mu = mc.trans_moment(unit='AU', origin='mass_center', state=[1, 0])")
            lines.append("f = 2/3 * abs(state_energies[1] - state_energies[0]) * mu.dot(mu)")
        else:
            lines.append("# no transition dipoles on this object, so no oscillator")
            lines.append("# strengths -- pyscf implements those for CMS-PDFT only")
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
        # 1-based including the ground state, matching run_gradient. The
        # preview shows one kernel call per requested state so the approval
        # card makes the cost of asking for several visible.
        targets = [int(s) for s in (params.get("target_states") or [1])]
        if method == "casscf":
            lines += _casscf_preview_lines(params, CASSCF_CONV_TOL_ENERGY)
            lines.append("mc.kernel()")
            lines.append("grad = mc.nuc_grad_method().kernel()  # ground state only")
        elif method in PDFT_METHODS:
            lines += _pdft_preview_lines(params, method, CASSCF_CONV_TOL_ENERGY)
            lines.append("mc.kernel()")
            if params.get("n_states", 1) > 1:
                lines.append("grad_method = mc.nuc_grad_method()")
                for state in targets:
                    lines.append(f"grad_S{state - 1} = grad_method.kernel(state={state - 1})  "
                                 f"# 0-based, counting the ground state")
            else:
                lines.append("grad = mc.nuc_grad_method().kernel()  # ground state")
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
            excited = [s for s in targets if s > 1]
            if excited:
                td_cls = "TDA" if params.get("use_tda", False) else "TDDFT"
                lines.append(f"td = tdscf.{td_cls}(mf)")
                lines.append(f"td.nstates = {max(params.get('n_states') or 0, max(excited) - 1)}")
                lines.append("td.kernel()")
                lines.append("td_grad = td.nuc_grad_method()")
            for state in targets:
                if state == 1:
                    lines.append("grad_S0 = mf.nuc_grad_method().kernel()  # ground state")
                else:
                    lines.append(f"grad_S{state - 1} = td_grad.kernel(state={state - 1})  "
                                 f"# 1-based excited root")
    elif job_type == "nac":
        # Every requested pair, one kernel call each against the single
        # converged state-averaged object -- the preview shows the loop
        # rather than the first pair alone, so the approval card says how
        # many couplings the job will actually produce.
        pairs = params.get("state_pairs") or [[1, 2]]
        if method in PDFT_METHODS:
            lines += _pdft_preview_lines(params, method, CASSCF_CONV_TOL_ENERGY)
            lines.append("mc.kernel()")
            lines.append("nac_method = mc.nac_method()")
        else:
            lines += _casscf_preview_lines(params, CASSCF_CONV_TOL_ENERGY)
            lines.append("mc.kernel()")
            lines.append("from pyscf.nac import sacasscf as nac_sacasscf")
            lines.append("nac_method = nac_sacasscf.NonAdiabaticCouplings(mc)")
        for pair in pairs:
            s1, s2 = int(pair[0]) - 1, int(pair[1]) - 1
            lines.append(f"nac_S{s1}_S{s2} = nac_method.kernel(state=({s1}, {s2}))  "
                         f"# 0-based state-average roots, state_pairs {list(pair)} converted")
    elif job_type == "mo_visualization":
        lines += _mf_lines(method, functional)
        lines.append("mf.kernel()")
        lines.append("from pyscf.tools import cubegen")
        lines.append(f"# orbitals to render: {params.get('orbital_indices')} (isoval={params.get('isoval', 0.04)})")
        lines.append("cubegen.orbital(mol, 'mo_<label>.cube', mf.mo_coeff[:, <index>])")
    elif job_type == "cas_recommendation":
        # A step plan rather than a driver script, for the same reason the two
        # runners this replaces used one: the active space is data-dependent,
        # so there is no literal input to show before the job has run. What the
        # card can honestly promise is the sequence.
        n_states = int(params.get("n_states") or 1)
        n_excited = max(0, n_states - 1)
        verify = params.get("verify_active_space", True)

        if params.get("basis"):
            basis_line = (f"1. RHF/ROHF on {molecule.get('name', 'the molecule')} "
                          f"in {basis}, as requested")
        else:
            chosen = (CAS_RECO_DEFAULT_BASIS_DIFFUSE if n_excited
                      else CAS_RECO_DEFAULT_BASIS)
            basis_line = (
                f"1. RHF/ROHF on {molecule.get('name', 'the molecule')} in "
                f"{chosen}, chosen by the engine\n"
                f"   (the recommendation does not depend on the basis set, so this\n"
                f"   does not constrain the basis of the calculation that follows)")

        steps = [
            "This job recommends a CASSCF active space. It does not run a CASSCF:",
            "the recommended space, its cost, and one size either side of it are the",
            "result.",
            "",
            basis_line,
            "2. Derive the projection directions from the geometry -- the pi normal at",
            "   each planar centre, the lone-pair directions on each heteroatom, and",
            "   the axis of every bond",
            "3. Project the orbitals onto those directions to get the candidate space,",
            "   then rank them by approximate pair-coefficient entropy",
        ]
        n = 4
        if n_excited:
            steps.append(
                f"{n}. TDA on CAM-B3LYP to see what the {n_excited} requested excited "
                f"state(s)\n"
                f"   are made of -- energy, bright or dark, and character (n->pi*,\n"
                f"   pi->pi* or Rydberg) -- and add the orbitals those states need")
            n += 1
        steps.append(
            f"{n}. Report the space at three sizes, with the determinant and CSF count\n"
            f"   of each and which engines can run them")
        n += 1
        if verify:
            steps.append(
                f"{n}. Verify: a CASCI in the recommended space, confirming the "
                f"requested\n   states are present with the predicted character")
            n += 1
        steps.append(
            f"{n}. Classify each orbital's character (sigma/pi/n/sigma*/pi*) and "
            f"dominant atom(s)")
        return "\n".join(steps)

    elif job_type == "cas_refinement":
        # Like the recommendation's card, a step plan rather than a driver
        # script. Unlike it, the cost is worth stating plainly on the card:
        # this runs several CASSCF solves where the recommendation runs none,
        # and that is the whole reason it is a separate job the user approves.
        n_states = int(params.get("n_states") or 1)
        cycles = int(params.get("refine_max_cycles") or 4)
        tier = params.get("refine_start_tier") or "recommended"
        src = params.get("active_space_source_job_id") or "the recommendation"
        return (
            f"This job refines an active space that job {src} already\n"
            f"recommended, by running CASSCF and correcting the space against\n"
            f"what it finds. It is minutes rather than the second the\n"
            f"recommendation took, because it solves where that one predicted.\n"
            f"\n"
            f"1. RHF/ROHF on {molecule.get('name', 'the molecule')} in {basis},\n"
            f"   and rebuild the recommendation in it\n"
            f"2. Start from its {tier} space\n"
            f"3. Each cycle, up to {cycles}:\n"
            f"   - state-averaged CASSCF over {n_states} state(s), plus a margin\n"
            f"     of extra roots, since a CASSCF need not order states the way\n"
            f"     the linear-response pass did\n"
            f"   - check the chosen pi and lone-pair character survived the\n"
            f"     orbital optimisation; if a requested state went missing with\n"
            f"     it, rotate the lost orbitals back in and re-solve\n"
            f"   - drop orbitals whose state-averaged natural occupation shows\n"
            f"     they carry no correlation, then re-solve and confirm nothing\n"
            f"     was lost and no energy moved more than 0.2 eV -- and undo the\n"
            f"     cut if either happened\n"
            f"4. Report the refined space, every orbital's occupation, and an\n"
            f"   ordered record of each rotation, so the space can be rebuilt\n"
            f"5. Write the converged orbitals, so a production CASSCF starts\n"
            f"   exactly where this finished"
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
    call site (run_casscf, geometry_optimization, run_cas_recommendation)
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
        {"index": i + 1, "spin": None, "energy_eV": float(e) * 27.211386245988,
         "occupancy": 0.0 if abs(float(o)) < 1e-9 else float(o)}
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
    _record_named_active_space(summary, params)
    return {"summary": summary, "artifacts": {"molden": molden_path}}


def run_gradient(molecule: dict, params: dict) -> dict:
    """single_point/grad. method in (hf, dft, mp2, ccsd, casscf, mcpdft,
    lpdft); an excited-state gradient (target_state set) is reachable for
    hf/dft and for the two pair-density methods -- app/agent/tools.py's
    _build_spec_or_error refuses target_state for any (engine, method)
    whose capability row doesn't claim excited_gradient before a spec ever
    reaches here, so casscf/mp2/ccsd below are always ground-state.

    Every method branch ends with an already-converged mean-field/CC/CASSCF
    object, so an orbital table is attached "for free" the same way every
    other run_* here does (see _write_molden_and_table's own docstring)."""
    method = params["method"]
    # 1-based INCLUDING the ground state, so [1] is the ground-state
    # gradient and [1, 2, 3] the lowest three surfaces. Note this is a
    # different convention from the older scalar `target_state` still used
    # by opt/freq/neb_ts, where 0 or absent means the ground state; the
    # conversion to whatever index each PySCF driver wants happens per
    # branch below and nowhere else.
    targets = [int(s) for s in (params.get("target_states") or [1])]
    gradients: list[dict] = []
    # Every branch below converges a wavefunction that knows the energy of
    # every state it solved for, not only the ones a gradient was asked
    # for. That ladder is collected here and reported (derivatives.py's
    # `state_energies_hartree`), because "the gradient on S1" and "what S0,
    # S1 and S2 cost here" are one calculation and used to be two jobs.
    ladder: Optional[list] = None

    def record(state: int, vector, energy: Optional[float]) -> None:
        gradients.append(derivatives.gradient_entry(state, np.asarray(vector).tolist(), energy))

    def ground_state_only() -> None:
        """Refuse a several-state request on a method with no excited-state
        gradient, rather than quietly returning the ground state N times."""
        if targets != [1]:
            raise ValueError(
                f"PySCF has no excited-state gradient for method='{method}' in this app, so it "
                f"cannot compute gradients for states {targets}. Ask for the ground state ([1]), "
                f"or use a method whose capability row claims excited_gradient."
            )

    mol = build_mole(molecule, params["basis"])

    if method == "casscf":
        restricted = mol.spin == 0
        mf = scf.RHF(mol) if restricted else scf.ROHF(mol)
        mf.kernel()
        mc = _build_casscf(mf, params["active_orbitals"], params["active_electrons"],
                            params.get("n_states", 1), params.get("weights"), CASSCF_CONV_TOL_ENERGY)
        _apply_orbital_choices(mc, params)
        mc.kernel()
        # pyscf/casscf declares excited_gradient=False (capabilities.py), so
        # this branch is ground-state by construction.
        ground_state_only()
        ladder = _state_energies_from(mc, params.get("n_states", 1))
        record(1, mc.nuc_grad_method().kernel(), float(mc.e_tot))
        molden_path, orbital_table = _casscf_molden_and_table(mc, params["_job_dir"])
    elif method in PDFT_METHODS:
        # Unlike the casscf branch above, an excited-state gradient IS
        # reachable here: both capability rows claim excited_gradient on
        # verified runs, so target_state can legitimately be set. The state
        # index pyscf wants is 0-based and counts the ground state, which is
        # exactly what `target_state` already means for a multireference job
        # in this app (0/absent = ground state, 1 = the first excited
        # state), so it passes through with no conversion -- the same
        # convention bagel_runner uses for BAGEL's own `target`.
        mf = scf.RHF(mol) if mol.spin == 0 else scf.ROHF(mol)
        mf.kernel()
        n_states = params.get("n_states", 1)
        build = _PDFT_BUILDERS[method]
        mc = build(mf, params["ot_functional"], params["active_orbitals"],
                   params["active_electrons"], n_states, params.get("weights"),
                   CASSCF_CONV_TOL_ENERGY)
        _apply_orbital_choices(mc, params)
        mc.kernel()
        state_energies = _state_energies_from(mc, n_states)
        ladder = list(state_energies)
        # A single-state MC-PDFT object's gradient driver takes no `state`
        # kwarg at all, so it is passed only when there is a state average
        # to index into. One driver over the ONE converged object above,
        # called once per requested state.
        grad_method = mc.nuc_grad_method()
        for state in targets:
            state_index = state - 1
            if state_index >= len(state_energies):
                raise ValueError(
                    f"State {state} was requested but only {len(state_energies)} state(s) were "
                    f"computed. Ask for at least {state_index} excited state(s)."
                )
            vector = grad_method.kernel(state=state_index) if n_states > 1 else grad_method.kernel()
            record(state, vector, state_energies[state_index])
        molden_path, orbital_table = _casscf_molden_and_table(mc, params["_job_dir"])
    elif method == "mp2":
        from pyscf import mp
        mf = scf.RHF(mol) if mol.spin == 0 else scf.ROHF(mol)
        mf.kernel()
        mp2 = mp.MP2(mf)
        mp2.kernel()
        ground_state_only()
        ladder = [float(mp2.e_tot)]
        record(1, mp2.nuc_grad_method().kernel(), float(mp2.e_tot))
        molden_path, orbital_table = _write_molden_and_table(params["_job_dir"], mf)
    elif method == "ccsd":
        from pyscf import cc
        mf = scf.RHF(mol) if mol.spin == 0 else scf.ROHF(mol)
        mf.kernel()
        ccobj = cc.CCSD(mf)
        ccobj.kernel()
        ground_state_only()
        ladder = [float(ccobj.e_tot)]
        record(1, ccobj.nuc_grad_method().kernel(), float(ccobj.e_tot))
        molden_path, orbital_table = _write_molden_and_table(params["_job_dir"], mf)
    elif method in ("hf", "dft"):
        mf = build_mf(mol, method, params.get("functional"))
        mf.kernel()
        if not mf.converged:
            raise RuntimeError("SCF did not converge; try a different initial guess or check the input")
        # `targets` is 1-based with the ground state as 1, while tdscf's own
        # `state=` counts excited roots from 1, so state s maps to root
        # s - 1 and state 1 has no root at all -- it is the reference itself.
        excited = [s for s in targets if s > 1]
        if excited:
            td = tdscf.TDA(mf) if params.get("use_tda", False) else tdscf.TDDFT(mf)
            # One TDDFT solve covering the highest root asked for, then a
            # gradient per root against it.
            td.nstates = max(params.get("n_states") or 0, max(excited) - 1)
            excitation_energies = td.kernel()[0]
            td_grad = td.nuc_grad_method()
            # TDDFT excitation energies come back in hartree, so the ladder
            # is the reference energy followed by every root that was
            # solved for -- not merely the roots a gradient was asked for.
            ladder = [float(mf.e_tot)] + [float(mf.e_tot + e) for e in excitation_energies]
        else:
            ladder = [float(mf.e_tot)]
        for state in targets:
            if state == 1:
                record(1, mf.nuc_grad_method().kernel(), float(mf.e_tot))
            else:
                root = state - 1
                record(state, td_grad.kernel(state=root),
                       float(mf.e_tot + excitation_energies[root - 1]))
        molden_path, orbital_table = _write_molden_and_table(params["_job_dir"], mf)
    else:
        raise ValueError(f"Unsupported method '{method}' for a PySCF gradient")

    summary = derivatives.gradient_result(
        gradients, targets,
        state_energies_hartree=ladder,
        method=method,
        functional=params.get("functional"),
        basis=params["basis"],
        orbital_table=orbital_table,
        initial_orbitals_source_job_id=params.get("initial_orbitals_job_id"),
    )
    _record_named_active_space(summary, params)
    return {"summary": summary, "artifacts": {"molden": molden_path}}


def run_nac(molecule: dict, params: dict) -> dict:
    """single_point/nac. PySCF's NAC paths here are SA-CASSCF
    (pyscf.nac.sacasscf) and the two pair-density methods' own
    `nac_method()` -- no TDDFT NAC module exists in this pyscf version (see
    registry2/capabilities.py's pyscf/dft row), so tasks.supports() never
    routes a single-reference NAC request here in the first place.

    state_pairs (registry2/params.py) is 1-based INCLUDING the ground
    state (state_pairs=[[1, 2]] means the S0/S1 coupling), matching every
    other engine's runner here; pyscf.nac.sacasscf's own `state=` kwarg is
    0-based within the state average (verified live: scripts/spikes/
    spike_pyscf_caps.py's state=(0, 1) probe), so the -1 conversion happens
    here, at the input-building boundary, and nowhere else."""
    method = params["method"]
    if method != "casscf" and method not in PDFT_METHODS:
        raise ValueError(
            f"PySCF NAC in this app is available for method='casscf' (SA-CASSCF) or any of the "
            f"pair-density methods ({', '.join(PDFT_METHODS)}), got '{method}'"
        )

    pairs = params.get("state_pairs")
    if not pairs:
        raise ValueError("single_point/nac needs at least one entry in state_pairs")

    mol = build_mole(molecule, params["basis"])
    restricted = mol.spin == 0
    mf = scf.RHF(mol) if restricted else scf.ROHF(mol)
    mf.kernel()
    n_orb, n_elec, n_states = params["active_orbitals"], params["active_electrons"], params.get("n_states", 1)
    if method == "casscf":
        mc = _build_casscf(mf, n_orb, n_elec, n_states, params.get("weights"), CASSCF_CONV_TOL_ENERGY)
    else:
        build = _PDFT_BUILDERS[method]
        mc = build(mf, params["ot_functional"], n_orb, n_elec, n_states,
                   params.get("weights"), CASSCF_CONV_TOL_ENERGY)
    _apply_orbital_choices(mc, params)
    mc.kernel()

    if method == "casscf":
        # The dedicated SA-CASSCF coupling module. The pair-density methods
        # carry their own `nac_method()` instead, which is why the two are
        # built differently here rather than sharing one driver.
        from pyscf.nac import sacasscf as nac_sacasscf
        nac = nac_sacasscf.NonAdiabaticCouplings(mc)
    else:
        nac = mc.nac_method()

    # The state-averaged solve above IS the coupling calculation's first
    # half, so every state's energy is already in hand. Reported rather
    # than discarded: a coupling with no energies beside it cannot answer
    # where the states were, and the gap that scales it is derived from
    # these in derivatives.coupling_result.
    ladder = _state_energies_from(mc, n_states)

    # One coupling object over the ONE converged state-averaged wavefunction
    # above, called once per requested pair. PySCF has no multi-target input
    # the way BAGEL does, but the expensive half -- the state-averaged solve
    # -- is already done, so N pairs cost N cheap response-equation solves
    # rather than N CASSCF runs. That is why capabilities.py records
    # nac_multi_pair for these methods even though the mechanism is a loop.
    couplings = []
    for pair in pairs:
        s1, s2 = int(pair[0]) - 1, int(pair[1]) - 1
        vec = np.asarray(nac.kernel(state=(s1, s2)))
        # PySCF's coupling driver returns the vector alone; the energy gap,
        # transition dipole and oscillator strength BAGEL prints beside its
        # own are left at their None defaults.
        couplings.append(derivatives.coupling_entry([s1 + 1, s2 + 1], vec.tolist()))
    molden_path, orbital_table = _casscf_molden_and_table(mc, params["_job_dir"])

    summary = derivatives.coupling_result(
        couplings, pairs,
        state_energies_hartree=ladder,
        active_electrons=n_elec,
        active_orbitals=n_orb,
        n_states=n_states,
        orbital_table=orbital_table,
        initial_orbitals_source_job_id=params.get("initial_orbitals_job_id"),
    )
    _record_named_active_space(summary, params)
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
    if method == "nevpt2":
        raise ValueError(
            "NEVPT2 geometry optimization is not available: pyscf.mrpt exposes no NEVPT2 gradient "
            "('NEVPT' object has no attribute 'nuc_grad_method'), so there is nothing for the "
            "optimizer to follow. Optimize at CASSCF, MC-PDFT or L-PDFT instead, or take NEVPT2 "
            "energies at a geometry from one of those."
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

    if method in PDFT_METHODS:
        # Two things differ from every other branch in this function, both
        # verified live rather than assumed.
        #
        # First, geomeTRIC is handed a state-selected GRADIENT SCANNER, not
        # the wavefunction object. Passing the object itself raises
        # NotImplementedError('Gradient of PDFT state-average energy' /
        # '... LPDFT state-average energy'): the state-average energy has no
        # gradient, only the individual states do. The scanner's energy was
        # confirmed to track the requested state rather than the average.
        #
        # Second, the object must already be converged before the scanner is
        # built. The CASSCF branch below deliberately passes an un-run `mc`
        # and lets geomeTRIC run the wavefunction itself; doing that here
        # fails with "'NoneType' object has no attribute 'shape'", because
        # the on-top step reads MCSCF quantities that do not exist yet.
        #
        # The callback still receives `energy` through the scanner-driven
        # engine, so the per-step energy trace is captured the same way.
        restricted = mol.spin == 0
        mf = scf.RHF(mol) if restricted else scf.ROHF(mol)
        mf.kernel()
        n_orb, n_elec = params["active_orbitals"], params["active_electrons"]
        n_states = params.get("n_states", 1)
        ot = params["ot_functional"]
        build = _PDFT_BUILDERS[method]
        state_index = int(params.get("target_state") or 0)
        if state_index >= max(n_states, 1):
            raise ValueError(
                f"State {state_index} was requested but only {max(n_states, 1)} state(s) are being "
                f"computed. Ask for at least {state_index} excited state(s)."
            )

        mc = build(mf, ot, n_orb, n_elec, n_states, params.get("weights"), CASSCF_CONV_TOL_OPT_FREQ)
        _apply_orbital_choices(mc, params)
        mc.kernel()
        mol_eq = optimize(
            mc.nuc_grad_method().as_scanner(state=state_index),
            maxsteps=params.get("max_steps", 200), callback=_capture_energy,
            constraints=constraints_file,
        )

        # Fresh, converged wavefunction at the optimized geometry, for the
        # same reason the CASSCF branch below re-evaluates: the scanner
        # leaves the object at whatever point the optimizer last probed.
        mf_final = scf.RHF(mol_eq) if restricted else scf.ROHF(mol_eq)
        mf_final.kernel()
        mc_final = build(mf_final, ot, n_orb, n_elec, n_states, params.get("weights"),
                         CASSCF_CONV_TOL_OPT_FREQ)
        _apply_orbital_choices(mc_final, params)
        mc_final.kernel()

        state_energies = _state_energies_from(mc_final, n_states)
        summary = {
            "final_energy_hartree": state_energies[state_index],
            "state_energies_hartree": state_energies,
            "excitation_energies_eV": _excitation_energies_eV(state_energies),
            "ot_functional": ot,
            "target_state": state_index,
            "converged": bool(getattr(mc_final, "converged", True)),
            "optimized_geometry": molecule_from_mol(mol_eq, molecule),
            "optimization_energies_hartree": energies_per_step,
            "active_electrons": n_elec,
            "active_orbitals": n_orb,
            "n_states": n_states,
            "initial_orbitals_source_job_id": params.get("initial_orbitals_job_id"),
        }
        if constraints:
            summary["constraints"] = constraints
        artifacts = _multireference_orbitals(mc_final, params, summary)
        if summary.get("orbital_table_note"):
            summary["orbital_table_note"] = (
                "Natural orbitals of the OPTIMIZED geometry's wavefunction. "
                + summary["orbital_table_note"]
            )
        _record_named_active_space(summary, params)
        return {"summary": summary, "artifacts": artifacts}

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
        # With a state average, geomeTRIC handed the object itself
        # optimizes the AVERAGE energy -- the weighted mean of the roots,
        # which is not a surface any state moves on. Confirmed directly:
        # `mc.nuc_grad_method().as_scanner()` on a 3-root average returns
        # E = -74.70017640 (the mean) with |grad| = 0.427, while
        # `as_scanner(state=0)` returns the ground state's own
        # E = -74.97549539, |grad| = 0.176. So a state average follows the
        # state that was asked for, defaulting to the ground state; a
        # single-root CASSCF keeps passing the object straight through,
        # exactly as before.
        state_index = int(params.get("target_state") or 0)
        if state_index >= max(n_states, 1):
            raise ValueError(
                f"State {state_index} was requested but only {max(n_states, 1)} state(s) are being "
                f"computed. Ask for at least {state_index} excited state(s)."
            )
        if n_states > 1:
            # The SCF is solved BEFORE the CASSCF is constructed, because
            # `mcscf.CASSCF` copies `mo_coeff` off the reference at
            # construction time. Building a state-selected gradient from an
            # object whose `mo_coeff` is still None fails with "'NoneType'
            # object has no attribute 'shape'", and running the SCF
            # afterwards does not repair it -- the None was already copied.
            mf.kernel()
        mc = _build_casscf(mf, n_orb, n_elec, n_states, params.get("weights"), CASSCF_CONV_TOL_OPT_FREQ)
        _apply_orbital_choices(mc, params)
        driver = mc if n_states == 1 else mc.nuc_grad_method().as_scanner(state=state_index)
        mol_eq = optimize(
            driver, maxsteps=params.get("max_steps", 200), callback=_capture_energy,
            constraints=constraints_file,
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
        _apply_orbital_choices(mc_final, params)
        mc_final.kernel()
        if not mc_final.converged:
            raise RuntimeError("CASSCF at the optimized geometry did not (re-)converge")

        energies = np.atleast_1d(
            mc_final.e_states if hasattr(mc_final, "e_states") and n_states > 1 else mc_final.e_tot
        ).tolist()
        optimized_geometry = molecule_from_mol(mol_eq, molecule)
        state_energies = energies if n_states > 1 else [float(mc_final.e_tot)]
        summary = {
            # The energy of the state that was actually optimized. This
            # used to be None for a state average, because `mc.e_tot` there
            # is the mean over roots and reporting a mean as "the final
            # energy" would have been worse than reporting nothing. Now
            # that the optimization follows one state, that state's own
            # energy is the answer.
            "final_energy_hartree": (float(mc_final.e_tot) if n_states == 1
                                     else state_energies[state_index]),
            "target_state": state_index,
            "state_energies_hartree": state_energies,
            "excitation_energies_eV": _excitation_energies_eV(state_energies),
            "converged": bool(mc_final.converged),
            "optimized_geometry": optimized_geometry,
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
            "best-effort from plane symmetry and Mulliken populations) and dominant localized atom(s) "
            "where classifiable."
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

        optimized_geometry = molecule_from_mol(mol_eq, molecule)
        summary = {
            "final_energy_hartree": final_energy,
            "ground_state_energy_hartree": float(gs_energy),
            "target_state": target_state,
            "converged": True,
            "optimized_geometry": optimized_geometry,
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

    optimized_geometry = molecule_from_mol(mol_eq, molecule)
    summary = {
        "final_energy_hartree": float(energy),
        "converged": bool(mf_final.converged),
        "optimized_geometry": optimized_geometry,
        "optimization_energies_hartree": energies_per_step,
    }
    if constraints:
        summary["constraints"] = constraints
    _record_named_active_space(summary, params)
    return {"summary": summary, "artifacts": {}}


def _numerical_casscf_hessian(mc, delta: float = 0.005, state: int | None = None) -> np.ndarray:
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
    # `state` is for the pair-density methods, whose state-average energy
    # has no gradient at all -- the scanner has to be told which state's
    # surface it is differencing. CASSCF callers pass nothing and get the
    # original, unchanged single-scanner behaviour.
    gs = mc.nuc_grad_method().as_scanner(**({} if state is None else {"state": state}))
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
    if method == "nevpt2":
        raise ValueError(
            "NEVPT2 frequencies are not available: pyscf.mrpt exposes no NEVPT2 gradient, and the "
            "numerical Hessian this app builds for the other multireference methods differences that "
            "gradient. Use CASSCF, MC-PDFT or L-PDFT for frequencies."
        )

    mol = build_mole(molecule, params["basis"])

    if method in PDFT_METHODS:
        restricted = mol.spin == 0
        mf = scf.RHF(mol) if restricted else scf.ROHF(mol)
        mf.kernel()
        n_orb, n_elec = params["active_orbitals"], params["active_electrons"]
        n_states = params.get("n_states", 1)
        ot = params["ot_functional"]
        build = _PDFT_BUILDERS[method]
        state_index = int(params.get("target_state") or 0)
        if state_index >= max(n_states, 1):
            raise ValueError(
                f"State {state_index} was requested but only {max(n_states, 1)} state(s) are being "
                f"computed. Ask for at least {state_index} excited state(s)."
            )
        mc = build(mf, ot, n_orb, n_elec, n_states, params.get("weights"), CASSCF_CONV_TOL_OPT_FREQ)
        _apply_orbital_choices(mc, params)
        mc.kernel()

        hess = _numerical_casscf_hessian(mc, state=state_index)
        freq_info = pyscf_thermo.harmonic_analysis(mol, hess)
        # `thermo` reads exactly two things off the model: `mol` and
        # `e_tot`. On a state-averaged object `e_tot` is the average over
        # roots, not the energy of the state whose Hessian this is, so
        # handing `mc` over directly would report a thermochemistry built
        # on a weighted mean. The shim supplies the tracked state's own
        # energy instead.
        state_energies = _state_energies_from(mc, n_states)
        thermo_model = SimpleNamespace(mol=mol, e_tot=state_energies[state_index])
        thermo_info = pyscf_thermo.thermo(
            thermo_model, freq_info["freq_au"], params.get("temperature_K", 298.15))

        freqs_cm1 = np.real(freq_info["freq_wavenumber"]).tolist()
        summary = {
            **summarize_frequencies(freqs_cm1),
            # The TRACKED state's own energy, which is what `thermo_model`
            # above was handed and therefore what the enthalpy and Gibbs
            # energy here are built on. Deliberately not `mc.e_tot`: on a
            # state-averaged object that is the mean over roots, and a
            # breakdown starting from the average of states nobody asked
            # about would not add up to the numbers beside it.
            "electronic_energy_hartree": float(state_energies[state_index]),
            "zero_point_energy_hartree": float(thermo_info["ZPE"][0]),
            "enthalpy_hartree": float(thermo_info["H_tot"][0]),
            "gibbs_free_energy_hartree": float(thermo_info["G_tot"][0]),
            "entropy_hartree_per_K": float(thermo_info["S_tot"][0]),
            "temperature_K": params.get("temperature_K", 298.15),
            "normal_modes": freq_info["norm_mode"].tolist(),
            "reduced_mass_amu": freq_info["reduced_mass"].tolist(),
            "state_energies_hartree": state_energies,
            "ot_functional": ot,
            "target_state": state_index,
            "active_electrons": n_elec,
            "active_orbitals": n_orb,
            "n_states": n_states,
            "initial_orbitals_source_job_id": params.get("initial_orbitals_job_id"),
            "hessian_method_note": (
                f"Numerical Hessian (central differences of the analytic "
                f"{'L-PDFT' if method == 'lpdft' else 'MC-PDFT'} gradient for state "
                f"{state_index}) -- pyscf has no analytic Hessian for either pair-density "
                f"method. See known limitations for the cost/accuracy tradeoff."
            ),
        }
        artifacts = _multireference_orbitals(mc, params, summary)
        _record_named_active_space(summary, params)
        return {"summary": summary, "artifacts": artifacts}

    if method == "casscf":
        restricted = mol.spin == 0
        mf = scf.RHF(mol) if restricted else scf.ROHF(mol)
        mf.kernel()
        n_orb, n_elec = params["active_orbitals"], params["active_electrons"]
        n_states = params.get("n_states", 1)
        mc = _build_casscf(mf, n_orb, n_elec, n_states, params.get("weights"), CASSCF_CONV_TOL_OPT_FREQ)
        _apply_orbital_choices(mc, params)
        mc.kernel()
        if not mc.converged:
            raise RuntimeError("CASSCF did not converge before frequency analysis")

        # With a state average, both the Hessian and the thermochemistry
        # used to be taken on the AVERAGE energy rather than on any state.
        # Neither is a physical surface. On water/STO-3G/CAS(4,4) with three
        # roots the state-average Hessian gives frequencies
        # [0.0, 0.0, 5001.0] cm-1 -- two spurious zero modes -- against
        # [0.0, 2151.3, 4819.6] for the ground state's own. The scanner
        # `_numerical_casscf_hessian` drives returns the mean energy and the
        # mean gradient unless it is told which state to follow.
        state_index = int(params.get("target_state") or 0)
        if state_index >= max(n_states, 1):
            raise ValueError(
                f"State {state_index} was requested but only {max(n_states, 1)} state(s) are being "
                f"computed. Ask for at least {state_index} excited state(s)."
            )
        hessian_state = state_index if n_states > 1 else None
        hess = _numerical_casscf_hessian(mc, state=hessian_state)
        freq_info = pyscf_thermo.harmonic_analysis(mol, hess)
        # `thermo` reads `mol` and `e_tot` only, and on a state-averaged
        # object `e_tot` is the mean over roots -- so the enthalpy and Gibbs
        # energy were being built on a weighted mean of several electronic
        # states. The shim supplies the tracked state's own energy.
        casscf_state_energies = _state_energies_from(mc, n_states)
        thermo_model = (mc if n_states == 1
                        else SimpleNamespace(mol=mol, e_tot=casscf_state_energies[state_index]))
        thermo_info = pyscf_thermo.thermo(
            thermo_model, freq_info["freq_au"], params.get("temperature_K", 298.15))

        freqs_cm1 = np.real(freq_info["freq_wavenumber"]).tolist()
        # F-026: shared threshold rule, see app/chemistry/jobs/vibrations.py.
        summary = {
            **summarize_frequencies(freqs_cm1),
            # Whatever `thermo_model` above was built on, so the breakdown
            # and the numbers beside it agree: `mc.e_tot` for a single root,
            # the tracked state's own energy for a state average (where
            # `e_tot` is the mean over roots).
            "electronic_energy_hartree": float(
                mc.e_tot if n_states == 1 else casscf_state_energies[state_index]),
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
            "target_state": state_index,
            "state_energies_hartree": casscf_state_energies,
            "initial_orbitals_source_job_id": params.get("initial_orbitals_job_id"),
            "hessian_method_note": (
                "Numerical Hessian (central differences of the analytic CASSCF gradient) -- pyscf has no "
                "analytic CASSCF Hessian. See known limitations for the cost/accuracy tradeoff."
                + (f" Taken on state {state_index} of the {n_states}-root state average, along with the "
                   f"thermochemistry." if n_states > 1 else "")
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
        # The energy every other number in this block is measured from.
        # `pyscf_thermo.thermo` reads `mol` and `e_tot` and nothing else, so
        # the enthalpy and the Gibbs energy below are already built on it --
        # it was computed, used, and then not written down. ORCA has recorded
        # its own as `electronic_energy_hartree` all along, which is why a
        # thermochemistry breakdown looked impossible on PySCF and was only
        # ever a missing key.
        "electronic_energy_hartree": float(mf.e_tot),
        "zero_point_energy_hartree": float(thermo_info["ZPE"][0]),
        "enthalpy_hartree": float(thermo_info["H_tot"][0]),
        "gibbs_free_energy_hartree": float(thermo_info["G_tot"][0]),
        "entropy_hartree_per_K": float(thermo_info["S_tot"][0]),
        "temperature_K": params.get("temperature_K", 298.15),
        "normal_modes": freq_info["norm_mode"].tolist(),
        "reduced_mass_amu": freq_info["reduced_mass"].tolist(),
    }
    _record_named_active_space(summary, params)
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
    optimized_geometry = opt_result["summary"].get("optimized_geometry")
    if not optimized_geometry:
        raise RuntimeError("geometry optimization did not converge to a usable optimized geometry")

    freq_result = run_frequency(optimized_geometry, params)

    summary = dict(freq_result["summary"])
    summary["optimized_geometry"] = optimized_geometry
    summary["optimization_final_energy_hartree"] = opt_result["summary"].get("final_energy_hartree")
    summary["optimization_converged"] = opt_result["summary"].get("converged")
    summary["optimization_energies_hartree"] = opt_result["summary"].get("optimization_energies_hartree")

    artifacts = dict(freq_result.get("artifacts", {}))
    for key, path in opt_result.get("artifacts", {}).items():
        artifacts[f"optimization_{key}"] = path

    _record_named_active_space(summary, params)
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
    # Raw determinant rows, for the reference -- see
    # ci_transitions.reference_configuration and bagel_runner's identical
    # note: ranking aggregated weights compares an open-shell singlet's
    # two summed spin partners against a closed-shell determinant's one
    # term, and systematically picks the wrong reference.
    all_rows: list[tuple[float, list[int]]] = []
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
        per_state.append(aggregate_by_configuration(determinants))
        all_rows.extend(determinants)

    reference_counts = reference_configuration(all_rows)
    if reference_counts is None:
        return [None] * n_states

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

    Source-job validity (existence, completed, a method built on a CASSCF
    wavefunction, same engine) is checked pre-interrupt in
    registry2/elicitation.py; this
    performs the actual read, deferred to dispatch time per this app's
    cross-job-artifact precedent (app/agent/tools.py's own
    _resolve_batch_geometries)."""
    source_job_id = params.get("initial_orbitals_job_id")
    if not source_job_id:
        return
    from app.config import JOBS_DIR
    from app.chemistry.jobs.base import read_result, read_spec
    source_molden = os.path.join(str(JOBS_DIR), source_job_id, "orbitals.molden")
    if not os.path.exists(source_molden):
        raise RuntimeError(f"Initial-orbitals source job '{source_job_id}' has no orbitals.molden on disk.")
    _molden_mol, _e, source_mo_coeff, _occ, _irrep, _spins = molden.load(source_molden)
    source_spec = read_spec(source_job_id) or {}
    # prev_mol has to be the geometry the SOURCE ORBITALS were written at,
    # which is not always spec.molecule. Any job that moved the nuclei --
    # an optimization, or the opt half of an opt_freq -- records its input
    # geometry in spec.molecule while writing orbitals.molden at the
    # structure it finished on. Projecting through AOs centred on the
    # starting nuclei is silently wrong: project_init_guess still returns
    # a guess, the CASSCF still converges, and nothing anywhere says the
    # guess was built against the wrong frame.
    #
    # It matters most where it is least visible. A nuclear-ensemble
    # spectrum seeds every one of its samples from the frequency job it was
    # built around, so an opt_freq source makes this wrong on every sample
    # of every ensemble rather than once. Same rule, and the same reason,
    # as geometry_resolve.equilibrium_geometry_of_source; expressed here as
    # "the optimized structure if there is one" so it also covers a plain
    # opt source, which that function does not handle.
    #
    # PySCF-only. BAGEL's save_ref archive and ORCA's .gbw each carry their
    # own geometry and do the projection internally, so neither has a
    # prev_mol to get wrong.
    source_summary = (read_result(source_job_id) or {}).get("summary") or {}
    source_molecule = source_summary.get("optimized_geometry") or source_spec.get("molecule")
    source_basis = (source_spec.get("params") or {}).get("basis")
    prev_mol = build_mole(source_molecule, source_basis) if source_molecule and source_basis else None
    mc.mo_coeff = mcscf.project_init_guess(mc, source_mo_coeff, prev_mol=prev_mol)


def _record_named_active_space(summary: dict, params: dict) -> None:
    """Records the orbitals a user named, so the finished job says which
    space actually ran rather than looking identical to one on the
    engine's own default. A no-op when there was none, which keeps the
    key out of the summary of every ordinary CASSCF job -- carrying it as
    a null would put an empty row in the drawer's summary table for the
    common case. Mirrors bagel_runner's function of the same name."""
    named = params.get("active_space_orbital_indices")
    if named:
        summary["active_space_orbital_indices"] = [int(i) for i in named]


def _apply_named_active_space(mc, params: dict) -> None:
    """Rotates the orbitals named in params['active_space_orbital_indices']
    into the active space, so the CAS is the orbitals the user picked
    rather than the n_orb the engine would take around the HOMO. A no-op
    when the parameter is absent, which is the ordinary case -- it is set
    only when the user named the orbitals (see the ParamSpec).

    mcscf.sort_mo is pyscf's own mechanism for this and takes exactly the
    list this app carries: 1-based by default, which is the convention
    everywhere a user sees an orbital index here, so nothing is converted.
    `base=1` is passed explicitly anyway, matching this module's other
    sort_mo call site, because the meaning of the whole list turns on it.
    The length is checked against active_orbitals during elicitation,
    since sort_mo requires len(caslst) == ncas.

    Called after _apply_initial_orbitals, and the order is deliberate:
    when both are set, the indices refer to the orbitals of the job being
    reused, which is the reading a user wants -- those numbers were read
    off that job's own orbital table.

    Sorting needs orbitals to sort. The geometry-optimization path builds
    its CASSCF on a deliberately un-run SCF (geomeTRIC runs the
    wavefunction itself at each step), which leaves mc.mo_coeff as None
    and makes an orbital index meaningless, so the SCF is converged here
    first. That costs one extra SCF on a job that is about to run many,
    and it is what makes the numbers refer to anything at all."""
    named = params.get("active_space_orbital_indices")
    if not named:
        return
    if getattr(mc, "mo_coeff", None) is None:
        mc._scf.kernel()
        mc.mo_coeff = mc._scf.mo_coeff
    mc.mo_coeff = mc.sort_mo([int(i) for i in named], base=1)


def _apply_orbital_choices(mc, params: dict) -> None:
    """Everything that decides which orbitals this CASSCF starts from and
    which of them are active, in the one order that composes correctly.
    Every CASSCF-family runner in this module calls this instead of the
    two halves separately, so a new one cannot pick up the reuse and miss
    the named active space."""
    _apply_initial_orbitals(mc, params)
    _apply_named_active_space(mc, params)


def _build_casscf(mf, n_orb: int, n_elec: int, n_states: int, weights, conv_tol: float) -> "mcscf.CASSCF":
    """Shared CASSCF constructor for run_casscf, the verification CASCI's
    final CASSCF, and the CASSCF-driven geometry_optimization/frequency
    branches below -- applies this app's explicit convergence policy
    (app/config.py's CASSCF_CONV_TOL_*/CASSCF_MAX_CYCLE_MACRO) so every
    CASSCF macro-iteration loop in this app uses the same explicit values
    instead of pyscf's own defaults (conv_tol=1e-7, max_cycle_macro=50)."""
    mc = mcscf.CASSCF(mf, n_orb, n_elec)
    mc.conv_tol = conv_tol
    mc.max_cycle_macro = CASSCF_MAX_CYCLE_MACRO
    # Every root has the molecule's declared multiplicity. Without this a
    # state-averaged CASSCF returns the lowest roots of ANY multiplicity, so
    # a closed-shell molecule's "S1" could be, and on water/STO-3G/CAS(4,4)
    # was, a triplet. See _apply_spin_constraint for what it costs.
    _apply_spin_constraint(mc, mf.mol)
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
    _apply_orbital_choices(mc, params)
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
        "Character (sigma/pi/n/sigma*/pi*) and dominant localized atom(s) are best-effort from plane "
        "symmetry and Mulliken populations."
    )
    _record_named_active_space(summary, params)
    return {"summary": summary, "artifacts": {"molden": molden_path}}


def _state_energies_from(mc, n_states: int) -> list[float]:
    """The per-root energies of a converged multireference object, as a
    plain list, whether it state-averaged or not.

    `e_states` exists only on a state-averaged object, and on a single-root
    one `e_tot` is the state energy; on a state-averaged one `e_tot` is the
    AVERAGE over roots and is not a state energy at all. Reading the wrong
    one puts a weighted mean on an approval card labelled as the ground
    state, which is why every multireference runner here goes through this
    rather than reaching for `e_tot`."""
    if n_states > 1 and hasattr(mc, "e_states"):
        return [float(e) for e in np.atleast_1d(mc.e_states)]
    return [float(mc.e_tot)]


def _multireference_orbitals(mc, params: dict, summary: dict) -> dict:
    """Natural-orbital molden export and table for any CASSCF-derived
    object, degrading to no table rather than failing the job.

    MC-PDFT and L-PDFT objects are MCSCF objects (the orbitals are
    optimized for the ordinary MCSCF energy, which is what makes the export
    meaningful for them at all -- see the convention note in
    capabilities.py), so `molden.from_mcscf` applies unchanged. It is
    wrapped because the L-PDFT object holds its CI vectors in a rotated
    intermediate basis, and a future pyscf could reasonably decline the
    export rather than write orbitals that do not match the reported
    states."""
    try:
        molden_path, summary["orbital_table"] = _casscf_molden_and_table(mc, params["_job_dir"])
    except Exception:
        return {}
    summary["orbital_table_note"] = (
        "Natural orbitals of the underlying MCSCF wavefunction, with active-space occupation "
        "numbers (not integer HF-style occupancies). Character (sigma/pi/n/sigma*/pi*) and "
        "dominant localized atom(s) are best-effort from plane symmetry and Mulliken populations."
    )
    return {"molden": molden_path}


def _dominant_transitions_safe(mc, n_states: int) -> list[str | None] | None:
    """`_dominant_transitions_casscf` reads CI vectors in the CASSCF
    determinant basis. L-PDFT rotates those into an intermediate basis, so
    the reading can be meaningless or can raise; either way an absent
    transition list is far better than a confidently wrong one."""
    try:
        return _dominant_transitions_casscf(mc, n_states)
    except Exception:
        return None


def run_nevpt2(molecule: dict, params: dict) -> dict:
    """single_point/gs and single_point/ee at strongly contracted SC-NEVPT2.

    Energies only. `pyscf.mrpt` exposes no gradient (verified: 'NEVPT'
    object has no attribute 'nuc_grad_method'), so capabilities.py records
    gradient/hessian as gaps and no optimization or frequency request ever
    reaches this module for this method.

    The excited-state path is not the obvious one. NEVPT2 refuses a
    state-averaged FCI solver outright ('State-average FCI solver object
    cannot be used in NEVPT2 calculation'), so several roots cannot be
    corrected on the SA-CASSCF object that produced them. What works, and
    what the PySCF manual describes, is to keep the state-averaged
    ORBITALS, rebuild the wavefunction as a multi-root CASCI in them, and
    correct each root separately. The orbitals are therefore still shared
    across states, exactly as a state average intends; only the CI step is
    redone in a form NEVPT2 will accept."""
    from pyscf import mrpt

    mol = build_mole(molecule, params["basis"])
    mf = scf.RHF(mol) if mol.spin == 0 else scf.ROHF(mol)
    mf.kernel()
    if not mf.converged:
        raise RuntimeError("SCF did not converge; try a different initial guess or check the input")

    n_orb, n_elec = params["active_orbitals"], params["active_electrons"]
    n_states = params.get("n_states", 1)

    mc = _build_casscf(mf, n_orb, n_elec, n_states, params.get("weights"), CASSCF_CONV_TOL_ENERGY)
    _apply_orbital_choices(mc, params)
    mc.kernel()
    if not mc.converged:
        raise RuntimeError("The CASSCF reference for NEVPT2 did not converge")

    reference_energies = _state_energies_from(mc, n_states)
    if n_states > 1:
        ci = mcscf.CASCI(mf, n_orb, n_elec)
        # The same constraint the state-averaged CASSCF above carries.
        # Without it the roots this rebuilds could differ in multiplicity
        # from the ones whose orbitals it is using, which is not a
        # correction of those states at all.
        _apply_spin_constraint(ci, mol)
        ci.fcisolver.nroots = n_states
        ci.kernel(mc.mo_coeff)
        reference_energies = [float(e) for e in np.atleast_1d(ci.e_tot)]
        corrections = [float(mrpt.NEVPT(ci, root=r).kernel()) for r in range(n_states)]
    else:
        corrections = [float(mrpt.NEVPT(mc).kernel())]

    state_energies = [ref + corr for ref, corr in zip(reference_energies, corrections)]
    summary = {
        "nevpt2_energy_hartree": state_energies[0] if n_states == 1 else None,
        "state_energies_hartree": state_energies,
        "excitation_energies_eV": _excitation_energies_eV(state_energies),
        "nevpt2_correlation_hartree": corrections,
        "reference_casscf_energies_hartree": reference_energies,
        "active_electrons": n_elec,
        "active_orbitals": n_orb,
        "n_states": n_states,
        "converged": bool(mc.converged),
        "reference_hf_energy_hartree": float(mf.e_tot),
        "dominant_transitions": _dominant_transitions_safe(mc, n_states),
        "initial_orbitals_source_job_id": params.get("initial_orbitals_job_id"),
    }
    if n_states > 1:
        summary["nevpt2_note"] = (
            "Each root was corrected separately on a multi-root CASCI built in the "
            "state-averaged CASSCF orbitals, because NEVPT2 does not accept a "
            "state-averaged solver directly."
        )
    artifacts = _multireference_orbitals(mc, params, summary)
    _record_named_active_space(summary, params)
    return {"summary": summary, "artifacts": artifacts}


def _apply_spin_constraint(mc, mol) -> None:
    """Constrain a state average to the molecule's own spin multiplicity.

    Without this an FCI solver asked for several roots returns the lowest
    ones of ANY multiplicity, so a closed-shell molecule's "excited states"
    silently come back as a mixture of singlets and triplets. Two things go
    wrong then, and the second is what made this load-bearing rather than a
    refinement:

    1. The excitation energies are not what was asked for. Fixing the spin
       moves them by around 2 eV on water/STO-3G/CAS(4,4), because the
       triplets that were occupying roots of the average lie below the
       singlets that replace them.
    2. **A singlet-to-triplet transition dipole is identically zero.** On
       furan/STO-3G/CAS(6,5) the CMS-PDFT oscillator strengths came out at
       1e-15 without this and at 0.027 and 0.254 with it. A nuclear-ensemble
       spectrum built from the former has nothing to broaden.

    This matches what the app already does on the single-reference side,
    where `td.singlet` defaults to True (see run_tddft): "excited states"
    has always meant same-multiplicity excited states here. It also matches
    what the other two engines already did without being asked: ORCA writes
    `mult` into its `%casscf` block and BAGEL writes `nspin` into its casscf
    block, so both have always state-averaged within one multiplicity.
    PySCF was the outlier.

    **A CSF solver, not `fix_spin_`.** The obvious implementation is
    `fix_spin_`, which adds a penalty `shift * (<S^2> - ss)` to push
    unwanted multiplicities up. It works for MC-PDFT and L-PDFT and is
    actively broken for CMS-PDFT: the penalty leaks into the stored MCSCF
    energies, so when CMS-PDFT recomputes them it finds a mismatch of
    exactly the shift and aborts with "Sanity fault: e_mcscf != self
    .e_mcscf". Reproduced on furan/STO-3G/CAS(6,5) with three roots.
    `csf_solver` instead builds the CI space out of spin-adapted
    configuration state functions, so every root is a pure singlet by
    construction with no penalty to leak. It reproduces the intensities the
    penalty route gives wherever the penalty route survives, and it does not
    fall over where it doesn't.

    **What this costs.** A single-root calculation is unaffected: water/
    STO-3G/CAS(4,4) gives -74.97575060 either way, agreeing to eight
    decimals, because its lowest Ms=0 root is already the singlet. A state
    average is a different matter and this is the whole point -- the plain
    solver returns multiplicities [1.0, 3.0] for two roots and
    [1.0, 3.0, 1.0] for three, so what the app was calling S1 was a triplet.
    Constrained, they come back [1.0, 1.0] and [1.0, 1.0, 1.0], and the
    excitation energies move by roughly 1.8 eV. Applied to single-root
    calculations too even though it changes nothing there, because it is
    only a no-op for systems whose lowest root happens to have the declared
    multiplicity, and the user declared one either way.
    """
    from pyscf.csf_fci import csf_solver

    # `smult` is the spin multiplicity (2S + 1), where mol.spin is 2S.
    mc.fcisolver = csf_solver(mol, smult=mol.spin + 1)


def _build_mcpdft(mf, ot_functional: str, n_orb: int, n_elec: int, n_states: int,
                  weights, conv_tol: float):
    """Shared MC-PDFT constructor, the on-top analogue of `_build_casscf`.

    Applies the same explicit convergence policy, because the orbital
    optimization underneath is an ordinary CASSCF one: the MC-PDFT energy
    is evaluated after the fact and never drives the orbitals."""
    from pyscf import mcpdft

    mc = mcpdft.CASSCF(mf, ot_functional, n_orb, n_elec)
    mc.conv_tol = conv_tol
    mc.max_cycle_macro = CASSCF_MAX_CYCLE_MACRO
    # Before any state average, so the constraint is on the solver the
    # average will use. Applied unconditionally rather than only for
    # n_states > 1, so a single-state MC-PDFT energy and the first root of
    # a state-averaged one are the same kind of quantity.
    _apply_spin_constraint(mc, mf.mol)
    if n_states > 1:
        mc = mc.state_average_(weights or [1.0 / n_states] * n_states)
    return mc


# The two multi-state pair-density flavours, and what `multi_state`'s
# second argument has to be for each. L-PDFT is "LIN" (a `method=` kwarg);
# CMS-PDFT is "cms" and travels as the `diabatization=` argument -- the same
# parameter position, dispatched differently inside pyscf, which is why this
# maps to a string rather than branching on the flavour at each call site.
_MULTI_STATE_PDFT = {"lpdft": "LIN", "cmspdft": "cms"}


def _build_multi_state_pdft(mf, ot_functional: str, n_orb: int, n_elec: int, n_states: int,
                            weights, conv_tol: float, flavour: str):
    """L-PDFT and CMS-PDFT: `multi_state(...)` over the same MC-PDFT object.

    The state count is checked here rather than trusted from the draft
    because a one-root multi-state PDFT is not a cheaper calculation, it is
    not one: the whole content of both methods is the diagonalization of an
    effective Hamiltonian across the model space.

    Note the spin constraint is applied here rather than being inherited
    from `_build_mcpdft`, which only applies it when it does the state
    average itself. These two do their own, so passing n_states=1 down
    would build an unconstrained solver and then average over it -- the
    exact bug that made CMS-PDFT's transition dipoles vanish.
    """
    label = "L-PDFT" if flavour == "lpdft" else "CMS-PDFT"
    if n_states < 2:
        raise ValueError(
            f"{label} needs at least two states, since it diagonalizes an effective Hamiltonian "
            f"over a state average. Ask for at least one excited state, or use MC-PDFT for a "
            f"single state."
        )
    mc = _build_mcpdft(mf, ot_functional, n_orb, n_elec, 1, None, conv_tol)
    _apply_spin_constraint(mc, mf.mol)
    return mc.multi_state(weights or [1.0 / n_states] * n_states, _MULTI_STATE_PDFT[flavour])


def _build_lpdft(mf, ot_functional: str, n_orb: int, n_elec: int, n_states: int,
                 weights, conv_tol: float):
    return _build_multi_state_pdft(mf, ot_functional, n_orb, n_elec, n_states,
                                   weights, conv_tol, "lpdft")


def _build_cmspdft(mf, ot_functional: str, n_orb: int, n_elec: int, n_states: int,
                   weights, conv_tol: float):
    return _build_multi_state_pdft(mf, ot_functional, n_orb, n_elec, n_states,
                                   weights, conv_tol, "cmspdft")


# Which constructor each pair-density flavour uses. One table rather than a
# conditional at every call site, because the gradient, NAC, optimization
# and frequency branches all have to make the same choice and a missed one
# silently runs a different method.
_PDFT_BUILDERS = {
    "mcpdft": _build_mcpdft,
    "lpdft": _build_lpdft,
    "cmspdft": _build_cmspdft,
}
# Every method built on the pair-density machinery, for the branches that
# treat them identically.
PDFT_METHODS = ("mcpdft", "lpdft", "cmspdft")


def _cmspdft_oscillator_strengths(mc, state_energies: list[float]) -> list[float] | None:
    """Oscillator strengths from CMS-PDFT's transition dipole moments.

    This is the whole reason CMS-PDFT is offered alongside L-PDFT. PySCF
    implements `TransitionDipole` (pyscf.prop.trans_dip_moment.mspdft) for
    this variant and no other, so it is the only multireference route to a
    UV/Vis intensity in this deployment that does not go through ORCA.

    f = (2/3) dE |mu|^2, in atomic units throughout -- `unit="AU"` is
    passed for exactly that reason, since `trans_moment` otherwise returns
    Debye and the formula would be silently wrong by AU2DEBYE^2 (about 6.4).
    The origin is irrelevant for a transition between orthogonal states and
    is pinned to the mass centre only to match the reference values pyscf's
    own test asserts against.

    Returns one entry per EXCITED state, so index i describes state i+1 --
    the same length-(n_states - 1) convention `_excitation_energies_eV`
    uses and that ensemble_spectrum.py's pooling step and the frontend's
    excited-state table both assume.
    """
    out: list[float] = []
    for j in range(1, len(state_energies)):
        try:
            mu = np.asarray(mc.trans_moment(unit="AU", origin="mass_center", state=[j, 0]))
        except Exception:
            return None
        dE = abs(float(state_energies[j] - state_energies[0]))
        out.append(float(2.0 / 3.0 * dE * float(np.dot(mu, mu))))
    return out


def _run_pdft(molecule: dict, params: dict, flavour: str) -> dict:
    """The shared body of `run_mcpdft` and `run_lpdft`.

    They differ only in how the object is built and in which energy names
    the summary carries; everything from the SCF reference to the orbital
    export is identical, and the two were not worth duplicating."""
    mol = build_mole(molecule, params["basis"])
    mf = scf.RHF(mol) if mol.spin == 0 else scf.ROHF(mol)
    mf.kernel()
    if not mf.converged:
        raise RuntimeError("SCF did not converge; try a different initial guess or check the input")

    ot = params["ot_functional"]
    n_orb, n_elec = params["active_orbitals"], params["active_electrons"]
    n_states = params.get("n_states", 1)
    build = _PDFT_BUILDERS[flavour]
    mc = build(mf, ot, n_orb, n_elec, n_states, params.get("weights"), CASSCF_CONV_TOL_ENERGY)
    _apply_orbital_choices(mc, params)
    mc.kernel()

    state_energies = _state_energies_from(mc, n_states)
    summary = {
        f"{flavour}_energy_hartree": state_energies[0] if n_states == 1 else None,
        "state_energies_hartree": state_energies,
        "excitation_energies_eV": _excitation_energies_eV(state_energies),
        "ot_functional": ot,
        "active_electrons": n_elec,
        "active_orbitals": n_orb,
        "n_states": n_states,
        "converged": bool(getattr(mc, "converged", True)),
        "reference_hf_energy_hartree": float(mf.e_tot),
        "dominant_transitions": _dominant_transitions_safe(mc, n_states),
        "initial_orbitals_source_job_id": params.get("initial_orbitals_job_id"),
    }

    # The MCSCF and on-top pieces the total is built from. Reported because
    # the split is the interpretable part of an MC-PDFT result: e_ot is the
    # direct analogue of the exchange-correlation energy in Kohn-Sham DFT,
    # and a user comparing on-top functionals is comparing these.
    for key, attr in (("mcscf_energy_hartree", "e_mcscf"), ("on_top_energy_hartree", "e_ot")):
        value = getattr(mc, attr, None)
        if value is None:
            continue
        as_list = [float(v) for v in np.atleast_1d(value)]
        summary[key] = as_list[0] if len(as_list) == 1 else as_list

    # The one thing CMS-PDFT is here for. Every other multireference method
    # in this deployment reports excitation energies with no intensities.
    if flavour == "cmspdft" and n_states > 1:
        osc = _cmspdft_oscillator_strengths(mc, state_energies)
        if osc is not None:
            summary["oscillator_strengths"] = osc

    if n_states > 1 and flavour == "mcpdft":
        summary["mcpdft_state_order_note"] = (
            "Each state's MC-PDFT energy is evaluated separately and the states keep the "
            "ordinal labels the underlying CASSCF gave them, so they are not guaranteed to "
            "come out in ascending MC-PDFT energy order."
        )
    artifacts = _multireference_orbitals(mc, params, summary)
    _record_named_active_space(summary, params)
    return {"summary": summary, "artifacts": artifacts}


def run_mcpdft(molecule: dict, params: dict) -> dict:
    """single_point/gs and single_point/ee at MC-PDFT."""
    return _run_pdft(molecule, params, "mcpdft")


def run_lpdft(molecule: dict, params: dict) -> dict:
    """single_point/gs and single_point/ee at L-PDFT."""
    return _run_pdft(molecule, params, "lpdft")


def run_cmspdft(molecule: dict, params: dict) -> dict:
    """single_point/gs and single_point/ee at CMS-PDFT.

    The same shape as the other two pair-density runners, plus the
    oscillator strengths only this variant can produce -- which is what
    makes it the one multireference method here that a nuclear-ensemble
    spectrum can be built from without going to ORCA."""
    return _run_pdft(molecule, params, "cmspdft")


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
    _record_named_active_space(summary, params)
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
    _record_named_active_space(summary, params)
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
    _record_named_active_space(summary, params)
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


# --------------------------------------------------------------------------
# Active-space recommendation, v2
#
# The engine itself lives in app/chemistry/cas/ and knows nothing about jobs,
# the registry or this module: it takes a converged mean field and returns a
# recommendation. Everything below is the job-shaped wrapper -- build the Mole,
# choose the reference, write the artifacts, shape the summary.
#
# See docs/CAS_ENGINE_METHOD.md for the method and its benchmarks.
# --------------------------------------------------------------------------

# The basis the analysis runs in when the user did not name one, which is now
# the common case: the recommendation is basis independent, so asking for a
# basis before making it was asking a question whose answer changed nothing.
# def2-SVP is large enough for the projection to be meaningful and small enough
# to keep the whole recommendation inside a second or so.
CAS_RECO_DEFAULT_BASIS = "def2-svp"

# When excited states are wanted, diffuse functions are added. Rydberg states
# cannot be represented without them, and whether the states a user asked for
# are Rydberg is not knowable before looking.
#
# aug-cc-pVDZ rather than def2-SVPD, on measurement. def2-SVPD carries diffuse
# functions by name and still cannot resolve a diffuse particle orbital on four
# of the seven molecules tested: methylamine and ammonia fail the diffuseness
# gate outright, and pyrrole and furan pass it and then label a plainly Rydberg
# particle "mixed". aug-cc-pVDZ resolves every one of them. That is not a
# cosmetic difference, because a character containing "mixed" is dropped from
# the predicted list, so the state was neither served, refused, nor mentioned.
#
# The cost of being right is small and was the thing worth checking: over
# formaldehyde, methylamine, pyrrole, uracil and p-benzoquinone the linear
# response takes 0.99x, 1.38x, 1.44x, 1.97x and 1.38x what it takes in
# def2-SVPD. A factor of two at the worst, against a class of state the smaller
# basis reports wrongly rather than slowly.
CAS_RECO_DEFAULT_BASIS_DIFFUSE = "aug-cc-pvdz"

# aug-cc-pVDZ is not defined for every element, and the gaps are not exotic:
# pyscf has it for the 3d metals but not for Mo, W, Pd, Au or iodine, all of
# which def2-SVPD covers except the last two. A hard switch would therefore
# have taken excited-state recommendations on those elements from working to
# failing at build time, which is the sort of regression that surfaces on
# somebody's molybdenum complex rather than in a benchmark of organics.
#
# So the diffuse choice is a chain, tried in order, and the job says which link
# it landed on. def2-SVPD is a worse analysis basis, not a broken one; it
# resolves Rydberg character on three of the seven molecules measured rather
# than all seven.
CAS_RECO_DIFFUSE_FALLBACKS = ("aug-cc-pvdz", "def2-svpd")


def _build_with_diffuse(molecule, preferred=None):
    """Build the molecule in the best diffuse basis its elements support.

    Returns ``(mol, basis, note)``, where `note` is None when the first choice
    worked and explains the substitution otherwise.
    """
    chain = [preferred] if preferred else list(CAS_RECO_DIFFUSE_FALLBACKS)
    if preferred and preferred not in chain:
        chain += [b for b in CAS_RECO_DIFFUSE_FALLBACKS if b != preferred]
    first, last_error = chain[0], None
    for basis in chain:
        try:
            return build_mole(molecule, basis), basis, (
                None if basis == first else
                f"{first} is not defined for every element in this molecule, so "
                f"the excited-state analysis ran in {basis} instead. That basis "
                f"resolves diffuse orbitals less reliably, so a state reported "
                f"here without Rydberg character may still be one."
            )
        except Exception as exc:                            # noqa: BLE001
            last_error = exc
    raise RuntimeError(
        f"None of {', '.join(chain)} is defined for every element in this "
        f"molecule, so the excited-state analysis has no basis to run in. "
        f"Supply one explicitly. (Last error: {last_error})")


def _refinement_cost(rec, n_states: int) -> dict:
    """What a refinement of this recommendation would cost, tier by tier.

    Answerable at the moment the recommendation is reported, which is the
    moment the user decides whether to ask for a refinement, so there is no
    reason to make them submit one to find out.

    The figure that governs is `n_csf * nroots` rather than the CSF count. A
    state average over R roots solves R CI problems per macro-iteration, so a
    bare CSF count lets a large state average through as though it were a
    ground-state calculation: o-nitrophenol's narrowed space is 497k CSFs,
    comfortably inside a flat budget of a million, and 3.97M root-CSFs over
    eight roots, where a single cycle took about two hours.

    `would_start_from` mirrors what `refine` would actually pick, which is the
    first of the recommended and minimal tiers whose root-CSF count fits the
    budget. It is a statement of what would happen, not a limit being imposed:
    the budget is a parameter and a user who wants a larger space raises it.
    Long runtimes are the design premise here and nothing is refused on the
    engine's own judgement of what is too expensive.
    """
    from app.chemistry.cas.refine import CSF_BUDGET, ROOT_MARGIN

    roots = max(1, n_states) + (ROOT_MARGIN if n_states > 1 else 0)
    per_tier = {}
    for name, tier in rec.tiers.items():
        n_csf = int(getattr(tier.feasibility, "n_csf", 0) or 0)
        per_tier[name] = {
            "n_csf": n_csf,
            "root_csf": n_csf * roots,
            "within_default_budget": bool(n_csf * roots <= CSF_BUDGET),
        }
    would_start = None
    for name in (rec.recommended, "recommended", "minimal"):
        if name in per_tier and per_tier[name]["within_default_budget"]:
            would_start = name
            break
    return {
        "requested_states": int(n_states),
        "roots_a_refinement_would_solve": roots,
        "default_budget_root_csf": CSF_BUDGET,
        "per_tier": per_tier,
        "would_start_from": would_start,
        "note": (
            "Cost is reported, not enforced. A refinement solves "
            f"{roots} roots, so what it spends against is CSFs times roots "
            "rather than CSFs. If no tier fits, the refinement narrows to the "
            "orbitals the requested states use rather than refusing, and the "
            "budget itself is a parameter."
        ),
    }


def run_cas_recommendation(molecule: dict, params: dict) -> dict:
    """Recommend a CASSCF active space for `molecule`.

    Runs as one sequential in-process pipeline, the same "one job_id, several
    stages" shape as run_neb_ts: each stage depends on the previous one's
    in-memory result, so there is no fan-out. print(..., flush=True) at each
    stage lands in worker.log, which the job panel tails live.

    Unlike the two runners this replaces, it does not end in a state-averaged
    CASSCF. That CASSCF was the expensive part of the old job and the reason
    it capped the active space at twelve orbitals; without it there is no cap,
    and a recommendation costs about a second. What confirms the answer instead
    is an optional CASCI in the recommended space (`verify_active_space`,
    default on), which checks the requested states are actually present.
    """
    import numpy as _np

    from app.chemistry.cas.excited import analyse as _analyse_states
    from app.chemistry.cas.diffuse import rydberg_representable
    from app.chemistry.cas.geometry import perceive as _perceive
    from app.chemistry.cas.narrow import (
        add_state_narrowed_tier as _add_state_narrowed_tier)
    from app.chemistry.cas.recommend import recommend as _recommend
    from app.chemistry.cas.reference import stabilise as _stabilise
    from app.chemistry.cas.verify import verify as _verify
    from app.chemistry.cas import spec as _spec

    job_dir = params.get("_job_dir") or "."
    n_states = int(params.get("n_states") or 1)
    n_excited = max(0, n_states - 1)
    want_verify = params.get("verify_active_space", True)

    # Basis: optional, and only used for the analysis. A basis the user names
    # is honoured -- they may want the recommendation computed in the basis
    # they intend to run -- but it does not change the answer, which is what
    # `basis_governs_recommendation: false` in the summary records.
    user_basis = params.get("basis")
    basis_defaulted = not user_basis
    if user_basis:
        basis = user_basis
    else:
        basis = (CAS_RECO_DEFAULT_BASIS_DIFFUSE if n_excited > 0
                 else CAS_RECO_DEFAULT_BASIS)

    basis_note = None
    if basis_defaulted and n_excited > 0:
        mol, basis, basis_note = _build_with_diffuse(molecule)
    else:
        mol = build_mole(molecule, basis)
    print(f"[cas_reco] building {molecule.get('name') or 'molecule'} in {basis}"
          + (" (chosen by the engine; the recommendation does not depend on it)"
             if basis_defaulted else " (as requested)"), flush=True)
    if basis_note:
        print(f"[cas_reco] {basis_note}", flush=True)
    symbols = [mol.atom_symbol(i) for i in range(mol.natm)]
    coords = mol.atom_coords() * 0.52917721067
    spin_2s = mol.spin

    print(f"[cas_reco] SCF reference: "
          f"{'RHF' if spin_2s == 0 else 'ROHF'} on {mol.natm} atoms, "
          f"{mol.nao} basis functions", flush=True)
    mf = (scf.RHF(mol) if spin_2s == 0 else scf.ROHF(mol)).density_fit()
    mf.kernel()
    if not mf.converged:
        raise RuntimeError(
            "The SCF reference did not converge, so there are no orbitals to "
            "project onto. An active space cannot be recommended from an "
            "unconverged reference.")

    # Converged is not the same as stable, and the difference decides the
    # answer. See `app/chemistry/cas/reference.py`: an unstable solution is a
    # stationary point that is not a minimum, so it passes the convergence test
    # exactly, and twisted ethylene's two solutions 31.5 mHa apart moved a
    # projector eigenvalue across the admission threshold and returned a
    # different space on nine runs in sixty.
    stability = _stabilise(mf, log=lambda m: print(f"[cas_reco] {m}",
                                                   flush=True))
    scf_notes = list(stability.notes)
    if basis_note:
        scf_notes.append(basis_note)

    print("[cas_reco] perceiving pi normals, lone pairs and sigma axes from the "
          "geometry", flush=True)
    rec = _recommend(mf, symbols, coords, spin_2s=spin_2s, n_states=n_states)
    ne, no = rec.space
    print(f"[cas_reco] recommended CAS({ne},{no}); tiers "
          + ", ".join(f"{k}=({t.n_electrons},{t.n_orbitals})"
                      for k, t in rec.tiers.items()), flush=True)

    # Excited-state branch.
    state_table, excited_notes = [], []
    diffuse = rydberg_representable(mf)
    rydberg_detectable = diffuse
    predicted = []
    if n_excited > 0:
        # At least twice the requested roots, and never fewer than six: with
        # diffuse functions a small molecule's low-lying states are largely
        # Rydberg, so a tight window can fill up with them before reaching the
        # valence states the user is usually after.
        nroots = max(6, 2 * n_excited + 2)
        print(f"[cas_reco] {n_excited} excited state(s) requested: running TDA "
              f"on CAM-B3LYP for {nroots} roots to see what they are made of",
              flush=True)
        ks = dft.RKS(mol) if spin_2s == 0 else dft.ROKS(mol)
        ks.xc = "camb3lyp"
        ks = ks.density_fit()
        ks.kernel()
        td = tdscf.TDA(ks)
        td.nstates = nroots
        td.kernel()
        perception = _perceive(symbols, coords, include_sigma=False)
        targets = perception.targets
        analysis = _analyse_states(ks, td, targets, n_states=n_excited,
                                   rydberg_detectable=diffuse)
        state_table = [s.to_dict() for s in analysis.states]
        excited_notes = list(analysis.notes)
        rydberg_detectable = analysis.rydberg_detectable
        # Only valence states are handed to the verification. A Rydberg state
        # cannot be represented in a valence active space *by construction* --
        # its orbital is diffuse and is deliberately excluded -- so asking the
        # CASCI for one and reporting its absence as a miss would be reporting
        # the design as a failure. They are surfaced in their own note instead.
        wanted = analysis.states[:n_excited]
        predicted = [s.character for s in wanted
                     if s.particle_kind != "Rydberg" and "mixed" not in s.character]
        # A state the classifier could not label sharply used to be dropped
        # here without a word. That is the worst of the three outcomes
        # available: it is not served, not refused, and not mentioned, so a
        # user asking for two states can be told about one and never learn why.
        # It happens for a reason worth telling them, too -- in a basis that
        # cannot resolve a diffuse particle, a genuinely Rydberg state comes
        # back as "mixed" rather than as Rydberg, which is precisely when the
        # note below would otherwise have covered it.
        unlabelled = [s for s in wanted
                      if s.particle_kind != "Rydberg" and "mixed" in s.character]
        if unlabelled:
            excited_notes.append(
                f"{len(unlabelled)} of the {n_excited} state(s) requested "
                f"({', '.join(f'S{s.index} at {s.energy_ev:.2f} eV' for s in unlabelled)}) "
                f"could not be assigned a definite character: their orbitals "
                f"are a mixture rather than a clean pair. They were left out "
                f"of the check below, which compares predicted characters "
                f"against the ones a CI produces, so nothing about them is "
                f"confirmed either way. "
                + ("A basis carrying diffuse functions often resolves this, "
                   "and this one does not carry them, so a mixed label here "
                   "may be a Rydberg state the basis cannot see."
                   if not rydberg_detectable else
                   "This usually means the state genuinely has mixed "
                   "character rather than that anything went wrong."))
        ryd = [s for s in wanted if s.particle_kind == "Rydberg"]
        if ryd:
            excited_notes.append(
                f"{len(ryd)} of the {n_excited} state(s) requested "
                f"({', '.join(f'S{s.index} at {s.energy_ev:.2f} eV' for s in ryd)}) "
                f"are Rydberg. A valence active space cannot describe them, so "
                f"they are reported rather than built into the space; a CASSCF "
                f"in this space will give you the valence states only.")
        for s in analysis.states[:n_excited]:
            print(f"[cas_reco]   S{s.index}: {s.energy_ev:6.2f} eV  "
                  f"{s.character:16s} "
                  f"{'bright' if s.bright else 'dark'} (f={s.oscillator_strength:.4f})",
                  flush=True)

        # Narrow to what the requested states actually use.
        #
        # This needs no CASSCF: a geometry, the projection and the
        # linear-response analysis are enough, and all three exist by this
        # point. It lived inside the refinement loop and so was reachable only
        # from the expensive tier, which is why a user asking for three states
        # on uracil was quoted CAS(22e,14o) while the space those states use is
        # ten orbitals. Carrying lone pairs no state touches is not a harmless
        # surplus either: it dilutes the state average a missing state has to
        # be found in, and it is the difference between 248,430 root-CSFs and
        # 29,700.
        #
        # Offered as a FOURTH tier rather than by redefining the recommended
        # one. `Tier` and `Recommendation.to_dict` feed the job summary, the
        # frontend, `active_space_spec.json` and the capability matrix, so the
        # projector's own pool keeps its name and only the pointer moves.
        #
        # The budget passed is infinite deliberately. Inside `narrow_to_states`
        # it is a backstop that trims lone pairs further when a space does not
        # fit, and a recommendation should be chosen on chemistry and then
        # costed, never silently shrunk to fit a number the user never chose.
        # The feasibility block reports what it costs.
        if _add_state_narrowed_tier(
                rec, mol, analysis, n_states, targets,
                perception=perception, spin_2s=spin_2s,
                log=lambda m: print(f"[cas_reco] {m}", flush=True)):
            # The headline follows the pointer. `ne, no` were read off
            # `rec.space` before the states were analysed, which is the only
            # reading available then, and leaving them there reported the
            # pool's size under the narrowed tier's name.
            ne, no = rec.space

    # Verification.
    verification = {"ran": False, "method": "not requested", "notes": []}
    if want_verify:
        print("[cas_reco] verifying: CASCI in the recommended space", flush=True)
        v = _verify(mf, rec, symbols, coords, n_states=max(n_states, 1),
                    predicted=predicted, spin_2s=spin_2s,
                    rydberg_detectable=rydberg_detectable)
        verification = v.to_dict()
        for note in v.notes:
            print(f"[cas_reco]   {note}", flush=True)

    # Artifacts. The molden is what makes the orbitals viewable in the drawer
    # and what a follow-up job reuses, so it is written whether or not the
    # verification ran.
    molden_path, orbital_table = _write_molden_and_table(job_dir, mf)

    # The portable handoff. Molecular-orbital indices identify "the n-th
    # orbital of one particular calculation", so they name different orbitals
    # in a different basis -- measured on pyrrole, the def2-SVP indices span
    # the same space in cc-pVDZ (principal cosine 0.999) and a completely
    # different one in aug-cc-pVDZ (0.000), because diffuse functions reshuffle
    # the virtual manifold. The specification records the target directions in
    # the fixed minimal reference basis instead, so a later CASSCF re-asks the
    # question rather than re-using an index.
    spec_path = os.path.join(job_dir, "active_space_spec.json")
    try:
        sp = _spec.build(
            rec, symbols, coords,
            # The targets the recommendation was ACTUALLY projected onto. This
            # was the valence perception unconditionally, which is wrong for
            # every molecule whose recommendation falls back to the sigma
            # framework: water's specification recorded two targets rebuilding
            # to CAS(4e,2o) beside a tier table recording the CAS(8e,6o) it
            # recommended. The `or` is a floor for a Recommendation built by
            # older code, not a case that arises here.
            rec.targets or _perceive(symbols, coords, include_sigma=False).targets,
            charge=mol.charge, multiplicity=mol.spin + 1,
            # The tier this job actually selected, not the literal string
            # "recommended". `build`'s default was being taken at both call
            # sites, so every specification ever written claimed the pool tier
            # even when the pointer had moved to `state-narrowed` -- which is
            # the whole point of the narrowing, and which `spec.space()` and
            # any consumer of `selected_tier` then read wrongly.
            tier=rec.recommended,
            diagnostics={"analysis_basis": basis,
                         "basis_defaulted": basis_defaulted,
                         "diffuse_functions_present": diffuse},
        )
        with open(spec_path, "w") as fh:
            fh.write(sp.to_json())
    except Exception as exc:                                    # noqa: BLE001
        print(f"[cas_reco] active-space spec not written: {exc}", flush=True)
        spec_path = None

    ranking_path = None
    try:
        from app.chemistry.spectrum import render_entropy_plateau_plot
        ranking_path = os.path.join(job_dir, "orbital_ranking.png")
        # threshold=None: the tiers come from a gap search over the profile,
        # not from a single absolute cut, so there is no one line to draw. The
        # plot's own docstring calls this the refuse-don't-fabricate case.
        render_entropy_plateau_plot(
            list(rec.entropies), None,
            list(range(len(rec.entropies))), ranking_path)
    except Exception as exc:                                    # noqa: BLE001
        print(f"[cas_reco] orbital-ranking plot skipped: {exc}", flush=True)
        ranking_path = None

    tiers = {k: t.to_dict() for k, t in rec.tiers.items()}
    findings = _cas_reco_findings(rec, state_table, verification,
                                  basis, basis_defaulted, diffuse, n_excited)

    summary = {
        "findings_summary": findings,
        "recommended_active_electrons": ne,
        "recommended_active_orbitals": no,
        "recommended_tier": rec.recommended,
        "active_space_tiers": tiers,
        "feasibility": rec.tiers[rec.recommended].feasibility.to_dict(),
        # What a refinement of this recommendation would cost, computed here
        # because it is knowable here and because the user is about to decide
        # whether to ask for one.
        #
        # The number that governs is not the CSF count. A state average over R
        # roots solves R CI problems per macro-iteration, so cost tracks
        # n_csf * nroots, and testing the bare count lets a large state average
        # through as though it were a ground-state calculation: o-nitrophenol's
        # narrowed space is 497k CSFs, which passes a flat million comfortably,
        # and 3.97M root-CSFs over eight roots, where one cycle took two hours.
        #
        # Reported rather than enforced. The engine says what each tier costs
        # and which one a refinement would start from at the default budget,
        # and a user who wants a bigger space raises the budget. Long runtimes
        # are the design premise here, so nothing is refused on the engine's
        # own judgement of what is too expensive.
        "refinement_cost": _refinement_cost(rec, n_states),
        "state_table": state_table,
        "verification": verification,
        "orbital_table": orbital_table,
        # The APC entropies, under the key the existing plot tool and every
        # already-completed job already use, so plot(kind="entropy") keeps
        # working with no special case for old jobs against new. The selected
        # indices go with them: without those the plot renders the ranking but
        # marks nothing as chosen.
        "pilot_orbital_entropies": list(rec.entropies),
        "active_space_orbital_indices": [
            i + 1 for i in rec.tiers[rec.recommended].orbital_indices],
        "projection_targets": rec.target_labels,
        # The specification rebuilds an active space from target directions
        # against a PySCF mean field. ORCA and BAGEL reuse orbitals through
        # their own binaries -- a .gbw copy and a `ref` archive respectively --
        # so neither can consume it, and a follow-up on those engines gets the
        # electron and orbital counts but chooses its own orbitals. Saying so
        # is the honest position: the counts transfer, the orbital identity
        # does not, and claiming otherwise would be claiming a transfer that
        # was never validated on either engine.
        "handoff": {
            "portable_spec": bool(spec_path),
            "engines_that_can_reuse_the_orbitals": ["pyscf"],
            "note": (
                "The recommended (ne, no) applies on any engine. The orbital "
                "identity transfers only to PySCF, through "
                "active_space_spec.json; a CASSCF on ORCA or BAGEL will use "
                "the same counts but pick its own orbitals."
            ),
        },
        "analysis_basis": basis,
        "basis_defaulted": basis_defaulted,
        "basis_governs_recommendation": False,
        "diffuse_functions_present": diffuse,
        "rydberg_detectable": rydberg_detectable,
        "n_states": n_states,
        "reference_scf_energy_hartree": float(mf.e_tot),
        "notes": list(dict.fromkeys(list(rec.notes) + excited_notes
                                   + scf_notes)),
        "method_note": (
            "Active space chosen by geometry-oriented valence projection, "
            "ranked by approximate pair-coefficient entropy. The recommendation "
            "does not depend on the basis set or on the orientation of the "
            "input geometry. See docs/CAS_ENGINE_METHOD.md."
        ),
    }
    if params.get("literature_notes"):
        summary["literature_notes"] = params["literature_notes"]

    artifacts = {"molden": molden_path}
    if ranking_path:
        artifacts["orbital_ranking"] = ranking_path
    if spec_path:
        artifacts["active_space_spec"] = spec_path
    return {"summary": summary, "artifacts": artifacts}


def _cas_reco_findings(rec, state_table, verification, basis, basis_defaulted,
                       diffuse, n_excited) -> str:
    """The one-paragraph summary the agent relays to the user."""
    ne, no = rec.space
    t = rec.tiers[rec.recommended]
    parts = [
        f"Recommended active space: CAS({ne}e, {no}o) -- {t.rationale}. "
        f"{t.feasibility.summary_line()}."
    ]
    mn, mx = rec.tiers["minimal"], rec.tiers["maximal"]
    if (mn.n_electrons, mn.n_orbitals) != (ne, no):
        parts.append(f"A smaller CAS({mn.n_electrons}e, {mn.n_orbitals}o) is "
                     f"available: {mn.rationale}.")
    if (mx.n_electrons, mx.n_orbitals) != (ne, no):
        parts.append(f"A larger CAS({mx.n_electrons}e, {mx.n_orbitals}o) is "
                     f"available: {mx.rationale}.")
    if basis_defaulted:
        parts.append(
            f"The analysis ran in {basis}. The recommendation is independent of "
            f"the basis set, so this does not constrain the basis of the "
            f"calculation that follows.")
    if n_excited and not diffuse:
        parts.append(
            "The analysis basis has no diffuse functions, so Rydberg states "
            "could not be looked for. If any of the states of interest are "
            "Rydberg, they are not represented in this answer.")
    if state_table:
        got = ", ".join(f"S{s['state']} {s['energy_ev']:.2f} eV {s['character']}"
                        f" ({'bright' if s['bright'] else 'dark'})"
                        for s in state_table[:max(1, n_excited)])
        parts.append(f"States found: {got}.")
    if verification.get("ran"):
        parts.append(" ".join(verification.get("notes") or []))
    return " ".join(p for p in parts if p)


# --------------------------------------------------------------------------
# Active-space refinement, the second tier
#
# Takes a finished recommendation and refines it against real CASSCF evidence:
# solve, audit the character and the states, correct, prune, re-verify. Slower
# than the recommendation by design -- it runs several CASSCF solves where the
# recommendation runs none -- so it is a separate job the user approves rather
# than something folded into the first one.
#
# See docs/CAS_ENGINE_METHOD.md.
# --------------------------------------------------------------------------


def _load_source_active_space_spec(params: dict):
    """The `active_space_spec.json` of the job this refinement was pointed at.

    Returns `(spec, note)`. Exactly one of the two is meaningful: a parsed
    `ActiveSpaceSpec` and no note, or `None` and a note saying why, which the
    caller puts on the result.

    Every cas_reco job writes this artifact and, until now, nothing read it --
    `spec.rebuild_in_basis` had no caller anywhere under `app/`. So the
    portable handoff existed in one direction only: the recommendation wrote
    down the question it had asked, and the refinement, which is the one job
    whose entire premise is "refine THAT space", re-derived the question from
    scratch. Anything that had changed in between -- a perception constant, the
    projection threshold, the molecule itself -- was silently re-applied.

    A missing artifact is not an error. Recommendations written before the spec
    existed have none, and a refinement can legitimately be run with no source
    job at all; both fall back to re-deriving, which is what has always
    happened. What is NOT allowed to be silent is that the fallback occurred,
    because a job that reports refining a recommendation while quietly refining
    its own re-derivation of one is the class of failure P3.3 fixed.
    """
    from app.chemistry.cas.spec import ActiveSpaceSpec

    source_job_id = params.get("active_space_source_job_id")
    if not source_job_id:
        return None, (
            "No source recommendation was named, so the space to refine was "
            "re-derived here rather than read from a recommendation's "
            "specification.")
    # Same resolution as `_seed_initial_orbitals` uses for a sibling job's
    # orbitals.molden. One path convention for cross-job artifacts, not two.
    from app.config import JOBS_DIR
    path = os.path.join(str(JOBS_DIR), str(source_job_id),
                        "active_space_spec.json")
    if not os.path.exists(path):
        return None, (
            f"The source recommendation {source_job_id} has no "
            f"active_space_spec.json on disk, so the space to refine was "
            f"re-derived here rather than read from it.")
    try:
        with open(path) as fh:
            return ActiveSpaceSpec.from_json(fh.read()), None
    except Exception as exc:                                    # noqa: BLE001
        return None, (
            f"The source recommendation {source_job_id} has an "
            f"active_space_spec.json that could not be read "
            f"({type(exc).__name__}: {exc}), so the space to refine was "
            f"re-derived here rather than read from it.")


def run_cas_refinement(molecule: dict, params: dict) -> dict:
    """Refine the active space recommended by an earlier cas_reco job."""
    import numpy as _np

    from app.chemistry.cas import spec as _spec
    from app.chemistry.cas.excited import analyse as _analyse
    from app.chemistry.cas.diffuse import rydberg_representable
    from app.chemistry.cas.geometry import perceive as _perceive
    from app.chemistry.cas.narrow import (
        add_state_narrowed_tier as _add_state_narrowed_tier)
    from app.chemistry.cas.recommend import recommend as _recommend
    from app.chemistry.cas.reference import stabilise as _stabilise
    from app.chemistry.cas.refine import refine as _refine

    job_dir = params.get("_job_dir") or "."
    n_states = int(params.get("n_states") or 1)
    n_excited = max(0, n_states - 1)
    start_tier = params.get("refine_start_tier") or "recommended"
    max_cycles = int(params.get("refine_max_cycles") or 4)
    # The same rule the recommendation uses, and for the same reason. This used
    # to be CAS_RECO_DEFAULT_BASIS unconditionally, so a refinement asked for
    # excited states ran its own TDA pre-pass in a basis with nothing diffuse
    # in it while the recommendation that produced its starting space had run
    # in def2-svpd. The two tiers were answering the same question about the
    # same molecule in different bases, and only the cheaper one could see a
    # Rydberg state.
    basis = params.get("basis") or (CAS_RECO_DEFAULT_BASIS_DIFFUSE if n_excited > 0
                                    else CAS_RECO_DEFAULT_BASIS)

    print(f"[cas_refine] building {molecule.get('name') or 'molecule'} in {basis}",
          flush=True)
    mol = build_mole(molecule, basis)
    symbols = [mol.atom_symbol(i) for i in range(mol.natm)]
    coords = mol.atom_coords() * 0.52917721067
    spin_2s = mol.spin

    # The specification the source recommendation wrote down. Read BEFORE the
    # SCF, so a refinement pointed at the wrong recommendation fails in a
    # second rather than after a mean field and a TDA pass.
    source_spec, spec_note = _load_source_active_space_spec(params)
    spec_notes = [spec_note] if spec_note else []
    if source_spec is not None:
        # A geometry or molecule mismatch RAISES rather than falling back. The
        # other fallbacks above are missing artifacts; this one is a positive
        # statement that the space being refined describes a different
        # structure from the one this job was given, which is precisely the
        # failure `app/chemistry/cas/spec.py` was written to stop, and its
        # message already says what to do about it. Falling back here would
        # produce a job reporting that it refined a recommendation it does not
        # in fact derive from.
        _spec.check_applies_to(source_spec, symbols, coords)
        print(f"[cas_refine] reading the specification written by "
              f"{params.get('active_space_source_job_id')}: selected tier "
              f"'{source_spec.selected_tier}', "
              f"CAS({source_spec.space()[0]}e, {source_spec.space()[1]}o)",
              flush=True)

    mf = (scf.RHF(mol) if spin_2s == 0 else scf.ROHF(mol)).density_fit()
    mf.kernel()
    if not mf.converged:
        raise RuntimeError(
            "The SCF reference did not converge, so there is nothing to refine "
            "from.")

    # Stabilised for the same reason as the recommendation, and for one more
    # that belongs to this job alone: the specification written by the source
    # recommendation is rebuilt against this reference. If the two jobs landed
    # in different SCF solutions, the rebuild would be compared against a
    # different mean field from the one the space was chosen in, and the
    # disagreement would be reported as a drift in the space rather than as
    # what it is.
    refine_stability = _stabilise(
        mf, log=lambda m: print(f"[cas_refine] {m}", flush=True))

    # The projection threshold is part of the question the source job asked, so
    # it comes from the specification when there is one. Re-deriving with
    # today's module default would mean a recommendation made under one
    # threshold could be "refined" under another without anything saying so.
    threshold = (float(source_spec.thresholds.get("projection", 0.2))
                 if source_spec is not None else 0.2)
    print("[cas_refine] rebuilding the quick recommendation in this basis",
          flush=True)
    rec = _recommend(mf, symbols, coords, spin_2s=spin_2s, n_states=n_states,
                     threshold=threshold)

    # The cross-check, and the first production caller `rebuild_in_basis` has
    # ever had. It re-asks the recorded question against THIS basis's mean
    # field and says so when the answer differs from what the source job
    # recorded, which is the basis-independence claim of section 5 being tested
    # on real jobs rather than only in cas_09's three basis sets.
    if source_spec is not None:
        try:
            _rb_ncas, _rb_nelec, _mo, _cas, rebuild_notes = _spec.rebuild_in_basis(
                mf, source_spec)
            spec_notes.extend(rebuild_notes)
        except Exception as exc:                                # noqa: BLE001
            spec_notes.append(
                f"The source specification could not be rebuilt in {basis} "
                f"({type(exc).__name__}: {exc}), so it was not cross-checked "
                f"against this basis. The refinement below is unaffected.")

    analysis, predicted = None, []
    diffuse = rydberg_representable(mf)
    if n_excited > 0:
        nroots = max(6, 2 * n_excited + 2)
        print(f"[cas_refine] TDA for {nroots} roots, to know what the "
              f"{n_excited} requested state(s) are made of", flush=True)
        ks = dft.RKS(mol) if spin_2s == 0 else dft.ROKS(mol)
        ks.xc = "camb3lyp"
        ks = ks.density_fit()
        ks.kernel()
        td = tdscf.TDA(ks)
        td.nstates = nroots
        td.kernel()
        targets = _perceive(symbols, coords, include_sigma=False).targets
        analysis = _analyse(ks, td, targets, n_states=n_excited,
                            rydberg_detectable=diffuse)
        # Rydberg states are passed through rather than filtered out here.
        # `refine()` excludes them itself and reports what it excluded, and
        # that report is the only place a user is told a requested state was
        # deliberately not looked for. Filtering here made the report
        # unreachable: `rydberg_excluded` was always empty, so every refinement
        # said "all predicted states present" whether or not the one the user
        # cared about had been quietly dropped on the way in.
        #
        # A character that could not be assigned is still filtered, because the
        # audit compares characters and an unassignable one matches nothing;
        # the recommendation says so in its own note.
        predicted = [s.character for s in analysis.states[:n_excited]
                     if "mixed" not in s.character]

    # The same narrowing the recommendation publishes, computed once and here
    # rather than a second time inside the refinement loop. Before this the
    # loop derived its own from its own analysis, with a different root count
    # and a finite budget, so a refinement could start from a space the
    # recommendation never offered; `narrowing_agreement.py` measured 34
    # molecules and found the two agree, which is what made unifying them safe
    # rather than a gamble.
    if analysis is not None:
        _add_state_narrowed_tier(
            rec, mol, analysis, n_states,
            _perceive(symbols, coords, include_sigma=False).targets,
            perception=_perceive(symbols, coords, include_sigma=False),
            spin_2s=spin_2s,
            log=lambda m: print(f"[cas_refine] {m}", flush=True))

    print(f"[cas_refine] refining from the {start_tier} tier", flush=True)
    res = _refine(mf, symbols, coords, rec, n_states=n_states,
                  analysis=analysis, predicted=predicted,
                  start_tier=start_tier, max_cycles=max_cycles,
                  log=lambda *a: print(*a, flush=True))

    # Did this refinement start from the space the user was actually shown?
    #
    # The reason this used to differ is gone: the refinement defers to the
    # narrowed tier the recommendation published rather than re-deriving one
    # from its own analysis, so the two no longer disagree about the narrowing.
    # The comparison stays because it can still fire for two reasons that are
    # not the narrowing at all. A tier over the CSF budget sends the start-tier
    # search down the ladder, and an explicit `refine_start_tier` overrides the
    # choice outright. Both change what was refined relative to what was shown,
    # and both are worth a sentence to a user comparing two job cards.
    source_tier, source_space, start_drift = None, None, None
    if source_spec is not None:
        source_tier = source_spec.selected_tier
        source_space = list(source_spec.space())
        got = list(res.start_space) if res.start_space else None
        if got and got != source_space:
            start_drift = (
                f"The source recommendation selected its {source_tier} tier, "
                f"CAS({source_space[0]}e, {source_space[1]}o), and this "
                f"refinement started from CAS({got[0]}e, {got[1]}o) "
                f"({res.started_from}). A refinement starts from the tier it "
                f"was asked for, or from the largest one that fits its CSF "
                f"budget when that tier does not, so the two can differ; the "
                f"space this job reports is the one it actually refined.")
            spec_notes.append(start_drift)
            print(f"[cas_refine] {start_drift}", flush=True)

    # Artifacts. The molden is the point of the whole exercise: it is the
    # converged orbital set a production CASSCF starts from, so the refined
    # space is reproducible rather than merely reported.
    molden_path = os.path.join(job_dir, "orbitals.molden")
    try:
        molden.from_mo(mol, molden_path, res.mo_coeff)
    except Exception as exc:                                    # noqa: BLE001
        print(f"[cas_refine] molden not written: {exc}", flush=True)
        molden_path = None

    # A SECOND molden, in the natural-orbital basis. The one above is the
    # restart set and is what a production CASSCF should be seeded from; it is
    # not the set `natural_occupations` and `orbital_characters` describe.
    # Handing over only the restart set invites reading the reported table
    # against the wrong orbitals -- they span the same space but are not the
    # same orbitals, so "orbital 9 is sigma" does not survive the swap.
    natorb_path = os.path.join(job_dir, "natural_orbitals.molden")
    try:
        if res.natural_orbitals is None:
            raise ValueError("no natural orbital set was returned")
        molden.from_mo(mol, natorb_path, res.natural_orbitals,
                       occ=_natural_occ_vector(res, mol))
    except Exception as exc:                                    # noqa: BLE001
        print(f"[cas_refine] natural-orbital molden not written: {exc}",
              flush=True)
        natorb_path = None

    spec_path = os.path.join(job_dir, "active_space_spec.json")
    try:
        sp = _spec.build(
            rec, symbols, coords,
            rec.targets or _perceive(symbols, coords, include_sigma=False).targets,
            charge=mol.charge, multiplicity=mol.spin + 1,
            tier=rec.recommended,
            diagnostics={"refined": True,
                         "refined_active_electrons": res.n_electrons,
                         "refined_active_orbitals": res.n_orbitals,
                         "rotations": [r.to_dict() for r in res.rotations],
                         "source_job_id": params.get(
                             "active_space_source_job_id"),
                         "source_selected_tier": source_tier,
                         "analysis_basis": basis})
        with open(spec_path, "w") as fh:
            fh.write(sp.to_json())
    except Exception as exc:                                    # noqa: BLE001
        print(f"[cas_refine] spec not written: {exc}", flush=True)
        spec_path = None

    summary = {
        "findings_summary": _cas_refine_findings(rec, res, start_tier, n_states),
        "recommended_active_electrons": res.n_electrons,
        "recommended_active_orbitals": res.n_orbitals,
        "quick_active_electrons": rec.space[0],
        "quick_active_orbitals": rec.space[1],
        "started_from_tier": start_tier,
        "natural_occupations": [round(float(x), 4) for x in res.occupations],
        "state_characters": list(res.characters),
        "orbital_characters": list(res.orbital_labels),
        "active_space_composition": _cas_composition(res.orbital_labels),
        "orbital_character_weights": list(res.orbital_weights),
        "excitation_energies_ev": [round(float(x), 3) for x in res.energies_ev],
        "rotations": [r.to_dict() for r in res.rotations],
        "refinement_cycles": res.cycles,
        "converged": res.converged,
        "stopped_because": res.stopped_because,
        # What the space is conditioned on. `n_states` is what was asked for;
        # this is what the state average actually solved, which carries
        # ROOT_MARGIN extras and is clamped when the space holds fewer CSFs. A
        # refined space depends on it, so a result quoting only the request
        # cannot be compared against another one or against a reference space.
        "n_roots_solved": res.n_roots_solved,
        "spin_adapted": res.spin_adapted,
        "analysis_basis": basis,
        "diffuse_functions_present": diffuse,
        "n_states": n_states,
        # Where the space being refined came from. `spec_used` is the load
        # bearing one: false means this job re-derived the recommendation
        # instead of reading the one it was pointed at, and `notes` says why.
        # Reporting the source job id without it would let a fallback read as a
        # successful handoff.
        "active_space_source_job_id": params.get("active_space_source_job_id"),
        "spec_used": source_spec is not None,
        "notes": list(res.notes) + spec_notes + list(refine_stability.notes),
        "method_note": (
            "Active space refined against state-averaged CASSCF: character and "
            "state audits, then a natural-occupation prune, each re-verified. "
            "See docs/CAS_ENGINE_METHOD.md."),
    }
    # Only when there was a specification to read them from. Carrying them as
    # nulls on a fallback would put empty rows in the drawer's summary table
    # for a case that has nothing to say, which is the rule
    # `_record_named_active_space` already follows for a named active space.
    if source_spec is not None:
        summary["source_selected_tier"] = source_tier
        summary["source_selected_space"] = source_space

    artifacts = {}
    if molden_path:
        artifacts["molden"] = molden_path
    if natorb_path:
        artifacts["natural_orbitals_molden"] = natorb_path
    if spec_path:
        artifacts["active_space_spec"] = spec_path
    return {"summary": summary, "artifacts": artifacts}


def _natural_occ_vector(res, mol):
    """2 for core, the reported natural occupation for active, 0 for virtual."""
    import numpy as _np
    full = _np.zeros(_np.asarray(res.natural_orbitals).shape[1])
    full[:res.ncore] = 2.0
    full[res.ncore:res.ncore + res.n_orbitals] = _np.asarray(
        res.occupations, float)
    return full


def _cas_composition(labels) -> str:
    """Thin pass-through so the summary and the refiner cannot drift apart."""
    from app.chemistry.cas.refine import composition
    return composition(labels)


def _cas_refine_findings(rec, res, start_tier, n_states) -> str:
    parts = [
        f"Refined active space: CAS({res.n_electrons}e, {res.n_orbitals}o), "
        f"starting from the {start_tier} tier CAS{rec.space} and taking "
        f"{res.cycles} cycle(s)."
    ]
    if (res.n_electrons, res.n_orbitals) == rec.space:
        parts.append("The CASSCF evidence did not change it.")
    else:
        parts.append(f"The quick recommendation was CAS{rec.space}.")
    if res.rotations:
        kinds = {}
        for r in res.rotations:
            kinds[r.action] = kinds.get(r.action, 0) + 1
        parts.append(
            "Changes made: "
            + ", ".join(f"{v} {k}" for k, v in sorted(kinds.items()))
            + ". Each is listed with the orbital and the reason, so the space "
              "can be reproduced.")
    if not res.converged:
        parts.append("The final CASSCF did not converge, so treat this as "
                     "provisional.")
    parts.append(f"Stopped because {res.stopped_because}")
    return " ".join(parts)
