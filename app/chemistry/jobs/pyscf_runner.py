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
from pyscf.tools import cubegen, molden
from pyscf.hessian import thermo as pyscf_thermo
from pyscf.mcscf import avas
from pyscf.dft import numint

from app.chemistry.jobs.ci_transitions import aggregate_by_configuration, format_dominant, leading_single_excitations
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
    elif job_type == "recommend_active_space":
        # No literal driver-script equivalent -- this is a multi-stage
        # pipeline with data-dependent steps, not a single calculation, so
        # the "preview" the approval card shows is the step plan itself
        # (see the recommend_active_space plan's approval-card design).
        max_orb = params.get("max_active_orbitals", 12)
        aolabels = params.get("avas_aolabels") or "default valence AOs of every non-hydrogen atom"
        return (
            "This job runs a Single-Orbital-Entropy (autoCAS-style) active-space\n"
            "recommendation as one pipeline, then a final CASSCF with the result:\n\n"
            f"1. RHF on {molecule.get('name', 'the molecule')} in {basis}\n"
            f"2. Select a valence pilot active space via AVAS ({aolabels}),\n"
            f"   capped at {_PILOT_CAS_CEILING} orbitals (exact-FCI feasibility limit)\n"
            "3. Exact CASCI within the pilot space -> single-orbital entropies per orbital\n"
            f"4. Sweep the entropy threshold to find a stable (plateau) active-space size,\n"
            f"   capped at {max_orb} orbitals\n"
            f"5. State-averaged CASSCF for {params.get('n_states', 1)} state(s) with the recommended active space\n"
            "6. Classify each orbital's character (sigma/pi/n/sigma*/pi*) and dominant atom(s)"
        )
    else:
        raise ValueError(f"Unsupported job_type '{job_type}' for PySCF")

    return "\n".join(lines)


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
    molden.from_scf's other branch would produce for a genuine UHF mf."""
    molden_path = os.path.join(job_dir, "orbitals.molden")
    molden.from_scf(mf, molden_path)
    orbital_table = [
        {"index": i + 1, "spin": None, "energy_eV": float(e) * 27.211386245988, "occupancy": float(o)}
        for i, (e, o) in enumerate(zip(mf.mo_energy, mf.mo_occ))
    ]
    return molden_path, orbital_table


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
    molden_path, summary["orbital_table"] = _write_molden_and_table(params["_job_dir"], mf)
    return {"summary": summary, "artifacts": {"molden": molden_path}}


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
        "dominant_transitions": _dominant_transitions_casscf(mc, n_states),
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
    molden_path = os.path.join(params["_job_dir"], "orbitals.molden")
    molden.from_mcscf(mc, molden_path, cas_natorb=True)
    from app.chemistry.jobs.molden import orbital_table as _molden_orbital_table
    summary["orbital_table"] = _molden_orbital_table(molden_path)
    summary["orbital_table_note"] = (
        "Natural orbitals with active-space occupation numbers (not integer HF-style occupancies) -- "
        "core orbitals show occ=2, active orbitals show their natural-orbital occupation, virtuals show occ=0."
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


def _default_avas_aolabels(mol) -> list[str]:
    symbols = {mol.atom_symbol(i) for i in range(mol.natm) if mol.atom_symbol(i) != "H"}
    missing = symbols - set(_AVAS_DEFAULT_SHELL)
    if missing:
        raise ValueError(
            f"No default AVAS valence-shell seed for element(s) {sorted(missing)} -- "
            f"pass avas_aolabels explicitly, e.g. ['{sorted(missing)[0]} 3d']."
        )
    return [f"{sym} {_AVAS_DEFAULT_SHELL[sym]}" for sym in sorted(symbols)]


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


def classify_orbital_character(mol, mo_coeff: np.ndarray, mo_occ: np.ndarray) -> list[dict]:
    """Per-orbital {"character": "sigma"/"pi"/"n"/"sigma*"/"pi*"/None,
    "localized_atom": str} for every orbital in mo_coeff, using only
    already-in-memory data (no new QM calculation). Validated ad hoc
    against water (core O 1s and an O lone pair combination both come out
    single-atom-localized, "n") and ethylene (HOMO -> pi bonding, LUMO ->
    pi* antibonding via point-sampling that gave an exact -1.000 symmetry
    ratio, matching textbook ethylene) before being wired in here.

    Atom localization: per-orbital Mulliken population. A dominant 1-2
    atoms (>15% each, together >60%) get named directly; otherwise the
    orbital is honestly reported as delocalized rather than forced into a
    false single-bond label -- canonical/natural CASSCF orbitals of a
    symmetric or conjugated system genuinely aren't 2-center bonds (that's
    what Boys/Pipek-Mezey localization is for, and this function
    deliberately does not apply one, since the table needs to describe the
    ACTUAL displayed natural orbitals, not a separately-localized set).

    Shape (sigma/pi/n): for a planar molecule, point-sample the orbital
    amplitude at +/-delta along the molecular-plane normal at the
    population-weighted centroid of the dominant atom(s) -- antisymmetric
    means pi, symmetric means sigma (or n if localized on a single atom
    with no bonding partner). Falls back to a two-center ring-sampling
    test (_ring_sample_character) for a non-planar molecule with exactly 2
    dominant atoms; anything else is left unclassified (None) rather than
    guessed.

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
    normal = None
    if natm >= 3:
        centered = coords - centroid
        _, sv, vt = np.linalg.svd(centered)
        if sv[0] > 1e-6:
            is_planar = sv[-1] < 0.05 * sv[0]
            normal = vt[-1]

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

    results = []
    for idx in range(mo_coeff.shape[1]):
        C = mo_coeff[:, idx]
        pops = _mulliken_atom_populations(mol, C, S)
        order = np.argsort(-pops)
        top_atoms = [(int(ia), float(pops[ia])) for ia in order if pops[ia] > 0.10][:4]
        dominant = [(ia, p) for ia, p in top_atoms if p > 0.15]

        if not dominant:
            localized_atom = "delocalized" + (
                f" over {', '.join(atom_label(ia) for ia, _ in top_atoms)}" if top_atoms else ""
            )
        elif len(dominant) <= 2 and sum(p for _, p in dominant) > 0.6:
            localized_atom = "-".join(atom_label(ia) for ia, _ in dominant)
        else:
            localized_atom = "delocalized over " + ", ".join(atom_label(ia) for ia, _ in top_atoms)

        shape = None
        if is_planar:
            center_pt = centroid
            if dominant:
                pts = np.array([coords[ia] for ia, _ in dominant])
                wts = np.array([p for _, p in dominant])
                center_pt = (pts * wts[:, None]).sum(axis=0) / wts.sum()
            for shift in (0.5, 1.0, 1.5):
                sample_pts = np.array([center_pt + shift * normal, center_pt - shift * normal])
                v_plus, v_minus = numint.eval_ao(mol, sample_pts) @ C
                if abs(v_plus) > 1e-4 or abs(v_minus) > 1e-4:
                    shape = "pi" if v_plus * v_minus < 0 else "sigma"
                    break
        elif len(dominant) == 2:
            shape = _ring_sample_character(mol, C, coords[dominant[0][0]], coords[dominant[1][0]])

        occ = float(mo_occ[idx])
        if len(dominant) <= 1:
            character = "n" if dominant else None
        elif shape is not None:
            character = f"{shape}{'*' if occ < 1.0 else ''}"
        else:
            character = None

        results.append({"character": character, "localized_atom": localized_atom})
    return results


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
    for k in ranked_gap_positions:
        count = k + 1
        if count <= max_orbitals and gaps[k] > 1e-3:
            threshold = candidate_thresholds[k]
            selected = [int(order[j]) for j in range(count)]
            return (selected, threshold, True)
    count = min(max_orbitals, n)
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

    max_active_orbitals = int(params.get("max_active_orbitals") or 12)
    if max_active_orbitals > _PILOT_CAS_CEILING:
        raise ValueError(
            f"max_active_orbitals={max_active_orbitals} exceeds the {_PILOT_CAS_CEILING}-orbital exact-FCI "
            f"pilot ceiling on this host -- this is a user-supplied number, not something AVAS produced, so "
            f"it's refused outright rather than silently capped. Ask for {_PILOT_CAS_CEILING} or fewer."
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
    if avas_ncas > _PILOT_CAS_CEILING:
        keep_virt = min(_PILOT_CAS_CEILING - _PILOT_CAS_CEILING // 2, n_virt_active)
        keep_occ = min(_PILOT_CAS_CEILING - keep_virt, n_occ_active)
        keep_virt = min(_PILOT_CAS_CEILING - keep_occ, n_virt_active)
        boundary = ncore + n_occ_active
        col_start, col_end = boundary - keep_occ, boundary + keep_virt
        pilot_mo = avas_mo[:, :ncore + keep_occ].copy()
        pilot_mo = np.hstack([pilot_mo, avas_mo[:, col_start:col_end], avas_mo[:, boundary + n_virt_active:]])
        pilot_ncas, pilot_nelecas = keep_occ + keep_virt, 2 * keep_occ
        pilot_space_truncated = True
        print(
            f"[recommend_active_space] AVAS pilot space ({avas_ncas} orbitals) exceeds the "
            f"{_PILOT_CAS_CEILING}-orbital exact-FCI ceiling -- truncating to the {pilot_ncas} orbitals "
            f"nearest the Fermi level.", flush=True,
        )
    else:
        pilot_mo, pilot_ncas, pilot_nelecas = avas_mo, avas_ncas, avas_nelecas

    print(f"[recommend_active_space] pilot CASCI({pilot_nelecas},{pilot_ncas}) (exact FCI)", flush=True)
    pilot_mc = mcscf.CASCI(mf, pilot_ncas, pilot_nelecas)
    pilot_mc.kernel(pilot_mo)
    if not pilot_mc.converged:
        raise RuntimeError("Pilot CASCI did not converge.")

    print("[recommend_active_space] computing single-orbital entropies", flush=True)
    entropies, occupations = _single_orbital_entropies(pilot_mc)

    selected, threshold, plateau_found = _find_entropy_plateau(entropies, max_active_orbitals)
    selected_sorted = sorted(selected)
    n_orb = len(selected_sorted)
    # Electron count: sum of each selected orbital's active-space occupation
    # (na+nb from the pilot CASCI's own 1-RDM diagonal, in the pilot's own
    # basis -- see _single_orbital_entropies), rounded to the nearest even
    # integer for a closed-shell active space.
    selected_occ_sum = float(sum(occupations[i] for i in selected_sorted))
    n_elec = int(round(selected_occ_sum))
    if n_elec % 2 != 0:
        n_elec += 1 if (selected_occ_sum - n_elec) > 0 else -1
    n_elec = max(0, min(n_elec, 2 * n_orb))

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
        + f"; recommended active space: ({n_elec}e, {n_orb}o)."
    )
    print(f"[recommend_active_space] {findings_summary}", flush=True)

    weights = params.get("weights")
    n_states = params.get("n_states", 1)
    print(f"[recommend_active_space] final state-averaged CASSCF({n_elec},{n_orb}) for {n_states} state(s)", flush=True)

    mc = mcscf.CASSCF(mf, n_orb, n_elec)
    if n_states > 1:
        weights = weights or [1.0 / n_states] * n_states
        mc = mc.state_average_(weights)
    # Seed the final CASSCF's active space with EXACTLY the entropy-selected
    # pilot orbitals (not just "some orbitals near the Fermi level", which is
    # all a plain mf.mo_coeff guess would give): mc.sort_mo(caslst, ...) is
    # pyscf's own mechanism for this -- it correctly recomputes the
    # core/active/virtual column split for a target CASSCF object's own
    # (n_elec-derived) ncore, which a hand-rolled column reorder got wrong in
    # an earlier draft of this function whenever the final n_elec didn't
    # happen to match the pilot's own occupied/virtual split exactly.
    # selected_sorted indices are local to the pilot's active block
    # (pilot_mo columns [ncore : ncore+pilot_ncas]), so shift by ncore to get
    # 0-based global column indices into pilot_mo.
    caslst = [ncore + i for i in selected_sorted]
    seed_mo = mc.sort_mo(caslst, mo_coeff=pilot_mo, base=0)
    mc.kernel(seed_mo)
    if not mc.converged:
        raise RuntimeError("Final state-averaged CASSCF did not converge.")

    active_space_orbital_indices = list(range(mc.ncore + 1, mc.ncore + mc.ncas + 1))

    molden_path = os.path.join(params["_job_dir"], "orbitals.molden")
    # cas_natorb=True canonicalizes to natural orbitals with real fractional
    # active-space occupations, but (as in run_casscf above) this mutates
    # only the molden FILE, not mc.mo_coeff/mc.mo_occ in place (those stay
    # canonical, integer 0/2) -- so classify_orbital_character must use the
    # natural-orbital coefficients reloaded from the molden file, not mc's
    # own attributes, to get bonding/antibonding character right from
    # occupation number.
    molden.from_mcscf(mc, molden_path, cas_natorb=True)
    from app.chemistry.jobs.molden import orbital_table as _molden_orbital_table
    orbital_table = _molden_orbital_table(molden_path)
    nat_mol, _nat_energy, nat_mo_coeff, nat_mo_occ, _irrep, _spins = molden.load(molden_path)
    character_rows = classify_orbital_character(nat_mol, nat_mo_coeff, nat_mo_occ)
    for row, char_row in zip(orbital_table, character_rows):
        row.update(char_row)

    energies = np.atleast_1d(mc.e_states if hasattr(mc, "e_states") and n_states > 1 else mc.e_tot).tolist()
    summary = {
        "literature_notes": params.get("literature_notes"),
        "findings_summary": findings_summary,
        "recommended_active_electrons": n_elec,
        "recommended_active_orbitals": n_orb,
        "active_space_orbital_indices": active_space_orbital_indices,
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
            "Single-orbital entropies are exact-FCI (pyscf CASCI), not literal DMRG -- the identical "
            "quantity autoCAS approximates via DMRG, computed exactly here because the AVAS-seeded pilot "
            "space was small enough for exact FCI (capped at "
            f"{_PILOT_CAS_CEILING} orbitals). {'The pilot space was truncated relative to the full AVAS-selected valence space -- treat this recommendation as an approximation.' if pilot_space_truncated else ''}"
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
