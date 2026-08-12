"""ORCA backend: single-point, geometry optimization, frequency, and TDDFT.

ORCA has no structured (JSON) output mode, so results are regex-parsed
from its plain-text log. The patterns below were derived from real ORCA
6.1.1 runs on this machine (water/HF/STO-3G and B3LYP/STO-3G), not just
the manual, to make sure the exact formatting matches this installed
version.
"""
from __future__ import annotations

import os
import re
import subprocess

from app.config import ORCA_BIN, N_CORES

_FINAL_ENERGY = re.compile(r"FINAL SINGLE POINT ENERGY\s+(-?\d+\.\d+)")
_CARTESIAN_BLOCK = re.compile(
    r"CARTESIAN COORDINATES \(ANGSTROEM\)\n-+\n((?:\s*[A-Za-z]+\s+-?\d+\.\d+\s+-?\d+\.\d+\s+-?\d+\.\d+\n)+)"
)
_FREQ_LINE = re.compile(r"^\s*\d+:\s+(-?\d+\.\d+)\s+cm\*\*-1", re.MULTILINE)
_ORBITAL_ROW = re.compile(r"^\s*\d+\s+(-?\d+\.\d+)\s+(-?\d+\.\d+)\s+(-?\d+\.\d+)\s*$", re.MULTILINE)
_TDDFT_STATE = re.compile(
    r"STATE\s+(\d+):\s+E=\s+-?\d+\.\d+\s+au\s+(-?\d+\.\d+)\s+eV\s+(-?\d+\.\d+)\s+cm\*\*-1"
)
# ORCA prints FOUR "ABSORPTION SPECTRUM ..." tables after TDDFT (electric
# dipole, velocity dipole, and two combined electric+magnetic dipole
# variants for CD); only the first (electric dipole, fosc(D2)) has the
# conventional oscillator strength, so the section must be bounded rather
# than matched globally or the parser picks up unrelated columns from the
# other three tables.
_ELECTRIC_DIPOLE_SECTION = re.compile(
    r"ABSORPTION SPECTRUM VIA TRANSITION ELECTRIC DIPOLE MOMENTS\s*\n-+\n(?:.*\n){2}((?:.*\n)+?)\n"
)
_ABSORPTION_ROW = re.compile(
    r"0-1A\s*->\s*\d+-1A\s+-?\d+\.\d+\s+-?\d+\.\d+\s+-?\d+\.\d+\s+(-?\d+\.\d+)"
)
# EOM-CCSD's energies live in the "EOM-CCSD RESULTS (RHS)" block; the
# right-hand-side (R) vectors are the canonical excitation energies. A
# near-identical "Excited State LHS" block follows later purely to compute
# transition moments (approximate left vectors, same eigenvalues) -- if
# this section weren't bounded, a global IROOT search would double-count
# every state.
_EOM_RHS_SECTION = re.compile(r"EOM-CCSD RESULTS \(RHS\)\s*\n-+\s*\n(.*?)(?=\n\n\n\*{5,})", re.DOTALL)
_EOM_IROOT = re.compile(r"IROOT=\s*(\d+):\s+-?\d+\.\d+\s+au\s+(-?\d+\.\d+)\s+eV\s+(-?\d+\.\d+)\s+cm\*\*-1")
# Oscillator strengths are printed three times (right-, left-, and
# left-right transition moments -- the CC Hamiltonian is non-Hermitian, so
# right-only or left-only alone are each one-sided approximations);
# left-right is the balanced/standard choice in the EOM-CC literature.
_EOM_LEFT_RIGHT_SECTION = re.compile(
    r"SPECTRUM FOR LEFT-RIGHT TRANSITION MOMENTS\s*\n-+\s*\n\s*\n"
    r"-+\s*\n\s*ABSORPTION SPECTRUM VIA TRANSITION ELECTRIC DIPOLE MOMENTS\s*\n-+\s*\n(?:.*\n){2}((?:.*\n)+?)\n"
)
# The post-convergence "CAS-SCF STATES FOR BLOCK" table (final, converged
# energies) -- NOT the near-identical "INITIAL CI STATE CHECK" block earlier
# in the output, which has the same "ROOT N: E=..." line shape but
# pre-convergence energies; anchoring on the unique block header avoids
# silently parsing the wrong (initial-guess) numbers.
_CASSCF_BLOCK = re.compile(
    r"CAS-SCF STATES FOR BLOCK\s+\d+\s+MULT=\s*\d+\s+NROOTS=\s*\d+\s*\n-+\s*\n(.*?)\n\n\n", re.DOTALL
)
_CASSCF_ROOT = re.compile(r"ROOT\s+(\d+):\s+E=\s+(-?\d+\.\d+)\s+Eh")


def _method_line(params: dict) -> str:
    method = params["method"].lower()
    basis = params["basis"]
    if method == "hf":
        keyword = "HF"
    elif method == "dft":
        functional = params.get("functional")
        if not functional:
            raise ValueError("DFT requires a 'functional' parameter, e.g. 'b3lyp'")
        keyword = functional.upper()
    else:
        raise ValueError(f"Unsupported method '{method}' for ORCA (use 'hf' or 'dft')")
    return f"! {keyword} {basis} TightSCF"


def _geometry_block(molecule: dict, params: dict) -> str:
    lines = [f"* xyz {molecule['charge']} {molecule['multiplicity']}"]
    for sym, (x, y, z) in zip(molecule["symbols"], molecule["coords"]):
        lines.append(f"{sym:2s} {x: .8f} {y: .8f} {z: .8f}")
    lines.append("*")
    return "\n".join(lines)


def _tddft_block(params: dict) -> str:
    n_states = params["n_states"]
    return "\n".join([
        "%tddft", f"  nroots {n_states}", f"  tda {'true' if params.get('use_tda', True) else 'false'}", "end",
    ])


def _mdci_eom_block(params: dict) -> str:
    n_states = params.get("n_states", 1)
    return "\n".join(["%mdci", f"  nroots {n_states}", "end"])


def _casscf_block(molecule: dict, params: dict) -> str:
    lines = [
        "%casscf",
        f"  nel {params['active_electrons']}",
        f"  norb {params['active_orbitals']}",
        f"  nroots {params.get('n_states', 1)}",
        f"  mult {molecule['multiplicity']}",
    ]
    if params.get("want_oscillator_strengths"):
        lines.append("  DoDipoleLength true")
    lines.append("end")
    return "\n".join(lines)


def build_input_text(job_type: str, molecule: dict, params: dict) -> str:
    """Builds the exact .inp text a job would run with -- shared by the
    approval-preview path and the actual run_* functions below, so the
    preview the user approves can never drift from what actually runs."""
    if job_type == "single_point":
        return "\n".join([
            _method_line(params), "", f"%pal nprocs {N_CORES} end", "", _geometry_block(molecule, params),
        ])
    if job_type == "geometry_optimization":
        return "\n".join([
            _method_line(params) + " Opt", "", f"%pal nprocs {N_CORES} end", "", _geometry_block(molecule, params),
        ])
    if job_type == "frequency":
        return "\n".join([
            _method_line(params) + " Freq", "", f"%pal nprocs {N_CORES} end", "", _geometry_block(molecule, params),
        ])
    if job_type == "tddft":
        # _method_line already picks "HF" or the DFT functional from
        # params["method"]/["functional"] -- an HF reference here makes
        # this CIS (tda true) or TD-HF/RPA (tda false), not DFT-based
        # TDA/TDDFT; ORCA's TD-DFT/CIS module auto-selects based on the
        # reference wavefunction (confirmed against a real ORCA run).
        return "\n".join([
            _method_line(params), "", f"%pal nprocs {N_CORES} end", "",
            _tddft_block(params), "", _geometry_block(molecule, params),
        ])
    if job_type == "eom_ccsd":
        # EOM-CCSD is inherently post-HF -- no method/functional choice.
        return "\n".join([
            f"! HF EOM-CCSD {params['basis']} TightSCF", "", f"%pal nprocs {N_CORES} end", "",
            _mdci_eom_block(params), "", _geometry_block(molecule, params),
        ])
    if job_type == "casscf":
        return "\n".join([
            f"! {params['basis']} TightSCF", "", f"%pal nprocs {N_CORES} end", "",
            _casscf_block(molecule, params), "", _geometry_block(molecule, params),
        ])
    raise ValueError(f"Unsupported ORCA job_type '{job_type}'")


def _effective_input_text(job_type: str, molecule: dict, params: dict) -> str:
    """Uses the user-approved edited text verbatim if the approval-card
    edit path set one (see submit_job in tools.py), else regenerates it
    from structured params exactly as before -- keeping any direct
    JobSpec submission (e.g. via the Python testing snippet in CLAUDE.md)
    working unchanged."""
    raw = params.get("_raw_input")
    return raw if raw is not None else build_input_text(job_type, molecule, params)


def _safe_parse(build_summary, output: str, job_dir: str, job_type: str) -> dict:
    """Runs the output-parsing closure, converting a parse failure into a
    clear, actionable error instead of a raw Python traceback -- expected
    to matter mainly after a hand-edited input changes what ORCA actually
    prints (e.g. a different method keyword), so the job_type-specific
    parser built for the original request may find nothing. The compute
    already happened, so point at the raw output rather than losing it."""
    try:
        return build_summary()
    except Exception as e:
        raw_path = os.path.join(job_dir, "output.out")
        raise RuntimeError(
            f"ORCA ran to completion but the '{job_type}' output parser could not find the expected "
            f"results ({type(e).__name__}: {e}). If the input was hand-edited, it may no longer match "
            f"what this job type expects to see. Raw output saved at {raw_path}. Last part of output:\n"
            f"{output[-2000:]}"
        ) from e


def _write_and_run(job_dir: str, input_text: str) -> str:
    input_path = os.path.join(job_dir, "input.inp")
    out_path = os.path.join(job_dir, "output.out")
    with open(input_path, "w") as f:
        f.write(input_text)

    env = dict(os.environ)
    env.setdefault("PATH", "/usr/bin:/bin")
    with open(out_path, "w") as out_f:
        proc = subprocess.run(
            [ORCA_BIN, input_path], stdout=out_f, stderr=subprocess.STDOUT,
            cwd=job_dir, env=env, timeout=6 * 3600,
        )
    with open(out_path) as f:
        output = f.read()
    if proc.returncode != 0 or "FINAL SINGLE POINT ENERGY" not in output:
        raise RuntimeError(f"ORCA exited with code {proc.returncode}. Last 3000 chars of output:\n{output[-3000:]}")
    return output


def run_single_point(molecule: dict, params: dict) -> dict:
    job_dir = params["_job_dir"]
    text = _effective_input_text("single_point", molecule, params)
    output = _write_and_run(job_dir, text)

    def build_summary():
        energies = _FINAL_ENERGY.findall(output)
        return {
            "energy_hartree": float(energies[-1]),
            "method": params.get("method"),
            "functional": params.get("functional"),
            "basis": params.get("basis"),
            "homo_lumo_gap_eV": _homo_lumo_gap(output),
        }

    summary = _safe_parse(build_summary, output, job_dir, "single_point")
    return {"summary": summary, "artifacts": {"raw_output": os.path.join(job_dir, "output.out")}}


def run_geometry_optimization(molecule: dict, params: dict) -> dict:
    job_dir = params["_job_dir"]
    text = _effective_input_text("geometry_optimization", molecule, params)
    output = _write_and_run(job_dir, text)
    if "HURRAY" not in output:
        raise RuntimeError("ORCA geometry optimization did not converge (no HURRAY marker found)")

    def build_summary():
        energies = _FINAL_ENERGY.findall(output)
        return {
            "final_energy_hartree": float(energies[-1]),
            "converged": True,
            "optimized_molecule": _extract_final_geometry(output, molecule),
        }

    summary = _safe_parse(build_summary, output, job_dir, "geometry_optimization")
    return {"summary": summary, "artifacts": {"raw_output": os.path.join(job_dir, "output.out")}}


def run_frequency(molecule: dict, params: dict) -> dict:
    job_dir = params["_job_dir"]
    text = _effective_input_text("frequency", molecule, params)
    output = _write_and_run(job_dir, text)

    def _grab(label: str) -> float | None:
        m = re.search(rf"{re.escape(label)}\s*\.*\s+(-?\d+\.\d+)\s*Eh", output)
        return float(m.group(1)) if m else None

    def build_summary():
        freqs = [float(x) for x in _FREQ_LINE.findall(output)]
        n_imaginary = sum(1 for f in freqs if f < 0)
        return {
            "frequencies_cm-1": freqs,
            "n_imaginary_frequencies": n_imaginary,
            "zero_point_energy_hartree": _grab("Zero point energy"),
            "enthalpy_hartree": _grab("Total Enthalpy"),
            "gibbs_free_energy_hartree": _grab("Final Gibbs free energy"),
            "electronic_energy_hartree": _grab("Electronic energy"),
        }

    summary = _safe_parse(build_summary, output, job_dir, "frequency")
    return {"summary": summary, "artifacts": {"raw_output": os.path.join(job_dir, "output.out")}}


def run_tddft(molecule: dict, params: dict) -> dict:
    """method='hf' makes ORCA's TD-DFT/CIS module auto-select CIS (tda
    true) or TD-HF/RPA (tda false) instead of DFT-based TDA/TDDFT -- same
    output format either way (verified against a real ORCA CIS run), so
    the parsing below is unchanged; only the summary's labeling differs."""
    job_dir = params["_job_dir"]
    method = params.get("method", "dft")
    functional = params.get("functional") if method == "dft" else None
    use_tda = params.get("use_tda", True)
    n_states = params.get("n_states")
    text = _effective_input_text("tddft", molecule, params)
    output = _write_and_run(job_dir, text)

    def build_summary():
        states = _TDDFT_STATE.findall(output)  # [(state_idx, energy_eV, energy_cm-1), ...]
        section_match = _ELECTRIC_DIPOLE_SECTION.search(output)
        section_text = section_match.group(1) if section_match else ""
        osc = [float(x) for x in _ABSORPTION_ROW.findall(section_text)]

        ev = [float(e) for _, e, _ in states]
        nm = [1239.841984 / e if e > 0 else None for e in ev]

        return {
            "excitation_energies_eV": ev,
            "excitation_wavelengths_nm": nm,
            "oscillator_strengths": osc if len(osc) == len(ev) else osc + [None] * (len(ev) - len(osc)),
            "n_states": n_states,
            "method": method,
            "functional": functional,
            "level_of_theory": ("CIS" if (method == "hf" and use_tda) else
                                 "TD-HF/RPA" if method == "hf" else
                                 "TDA-DFT" if use_tda else "TDDFT"),
        }

    summary = _safe_parse(build_summary, output, job_dir, "tddft")
    return {"summary": summary, "artifacts": {"raw_output": os.path.join(job_dir, "output.out")}}


def run_eom_ccsd(molecule: dict, params: dict) -> dict:
    """Oscillator strengths come from the 'left-right' transition-moment
    table (the balanced choice between the non-Hermitian CC Hamiltonian's
    right- and left-eigenvector-only estimates) -- both energies and
    intensities verified against a real ORCA 6.1.1 EOM-CCSD run."""
    job_dir = params["_job_dir"]
    n_states = params.get("n_states")
    text = _effective_input_text("eom_ccsd", molecule, params)
    output = _write_and_run(job_dir, text)

    def build_summary():
        section = _EOM_RHS_SECTION.search(output)
        if not section:
            raise RuntimeError("could not find the 'EOM-CCSD RESULTS (RHS)' section in the output")
        states = _EOM_IROOT.findall(section.group(1))  # [(iroot, energy_eV, energy_cm-1), ...]
        ev = [float(e) for _, e, _ in states]
        nm = [1239.841984 / e if e > 0 else None for e in ev]

        lr_section = _EOM_LEFT_RIGHT_SECTION.search(output)
        osc = [float(x) for x in _ABSORPTION_ROW.findall(lr_section.group(1))] if lr_section else []
        osc = osc if len(osc) == len(ev) else osc + [None] * (len(ev) - len(osc))

        return {
            "excitation_energies_eV": ev,
            "excitation_wavelengths_nm": nm,
            "oscillator_strengths": osc,
            "n_states": n_states,
            "level_of_theory": "EOM-CCSD",
        }

    summary = _safe_parse(build_summary, output, job_dir, "eom_ccsd")
    return {"summary": summary, "artifacts": {"raw_output": os.path.join(job_dir, "output.out")}}


def run_casscf(molecule: dict, params: dict) -> dict:
    """State-averaged CASSCF via ORCA's %casscf block. Oscillator
    strengths are only computed (DoDipoleLength) when
    params['want_oscillator_strengths'] is set -- see registry.py's
    default_engine() for how that routes here automatically instead of to
    PySCF/BAGEL, which don't compute them for CASSCF in this app."""
    job_dir = params["_job_dir"]
    n_states = params.get("n_states", 1)
    text = _effective_input_text("casscf", molecule, params)
    output = _write_and_run(job_dir, text)

    def build_summary():
        block = _CASSCF_BLOCK.search(output)
        if not block:
            raise RuntimeError("could not find the final 'CAS-SCF STATES FOR BLOCK' section in the output")
        state_energies = {int(i): float(e) for i, e in _CASSCF_ROOT.findall(block.group(1))}
        if len(state_energies) < n_states:
            raise RuntimeError(f"found converged energies for {len(state_energies)} of {n_states} state(s)")
        energies_hartree = [state_energies[i] for i in range(n_states)]
        excitation_ev = [(energies_hartree[i] - energies_hartree[0]) * 27.211386245988 for i in range(1, n_states)]

        osc = None
        if params.get("want_oscillator_strengths"):
            sec = _ELECTRIC_DIPOLE_SECTION.search(output)
            n_transitions = n_states - 1
            osc = [float(x) for x in _ABSORPTION_ROW.findall(sec.group(1))] if sec else []
            osc = osc if len(osc) == n_transitions else osc + [None] * (n_transitions - len(osc))

        return {
            "casscf_energy_hartree": energies_hartree[0] if n_states == 1 else None,
            "state_energies_hartree": energies_hartree,
            "excitation_energies_eV": excitation_ev,
            "oscillator_strengths": osc,
            "active_electrons": params.get("active_electrons"),
            "active_orbitals": params.get("active_orbitals"),
            "n_states": n_states,
        }

    summary = _safe_parse(build_summary, output, job_dir, "casscf")
    return {"summary": summary, "artifacts": {"raw_output": os.path.join(job_dir, "output.out")}}


def _homo_lumo_gap(output: str) -> float | None:
    m = re.search(r"ORBITAL ENERGIES\n-+\n\n\s*NO\s+OCC.*?\n((?:.+\n)+?)\n", output)
    if not m:
        return None
    rows = []
    for line in m.group(1).splitlines():
        parts = line.split()
        if len(parts) == 4:
            rows.append((float(parts[1]), float(parts[3])))  # (occ, E_eV)
    occupied = [e for occ, e in rows if occ > 0]
    virtual = [e for occ, e in rows if occ == 0]
    if not occupied or not virtual:
        return None
    return min(virtual) - max(occupied)


def _extract_final_geometry(output: str, template: dict) -> dict:
    blocks = _CARTESIAN_BLOCK.findall(output)
    if not blocks:
        raise RuntimeError("Could not find final Cartesian coordinates in ORCA output")
    last_block = blocks[-1]
    symbols, coords = [], []
    for line in last_block.strip().splitlines():
        sym, x, y, z = line.split()
        symbols.append(sym)
        coords.append([float(x), float(y), float(z)])
    out = dict(template)
    out["symbols"] = symbols
    out["coords"] = coords
    return out
