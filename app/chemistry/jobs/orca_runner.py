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
    text = "\n".join([
        _method_line(params),
        "",
        f"%pal nprocs {N_CORES} end",
        "",
        _geometry_block(molecule, params),
    ])
    output = _write_and_run(job_dir, text)
    energies = _FINAL_ENERGY.findall(output)

    summary = {
        "energy_hartree": float(energies[-1]),
        "method": params["method"],
        "functional": params.get("functional"),
        "basis": params["basis"],
        "homo_lumo_gap_eV": _homo_lumo_gap(output),
    }
    return {"summary": summary, "artifacts": {"raw_output": os.path.join(job_dir, "output.out")}}


def run_geometry_optimization(molecule: dict, params: dict) -> dict:
    job_dir = params["_job_dir"]
    method_line = _method_line(params) + " Opt"
    text = "\n".join([
        method_line, "", f"%pal nprocs {N_CORES} end", "", _geometry_block(molecule, params),
    ])
    output = _write_and_run(job_dir, text)
    if "HURRAY" not in output:
        raise RuntimeError("ORCA geometry optimization did not converge (no HURRAY marker found)")

    energies = _FINAL_ENERGY.findall(output)
    optimized_molecule = _extract_final_geometry(output, molecule)

    summary = {
        "final_energy_hartree": float(energies[-1]),
        "converged": True,
        "optimized_molecule": optimized_molecule,
    }
    return {"summary": summary, "artifacts": {"raw_output": os.path.join(job_dir, "output.out")}}


def run_frequency(molecule: dict, params: dict) -> dict:
    job_dir = params["_job_dir"]
    method_line = _method_line(params) + " Freq"
    text = "\n".join([
        method_line, "", f"%pal nprocs {N_CORES} end", "", _geometry_block(molecule, params),
    ])
    output = _write_and_run(job_dir, text)

    freqs = [float(x) for x in _FREQ_LINE.findall(output)]
    n_imaginary = sum(1 for f in freqs if f < 0)

    def _grab(label: str) -> float | None:
        m = re.search(rf"{re.escape(label)}\s*\.*\s+(-?\d+\.\d+)\s*Eh", output)
        return float(m.group(1)) if m else None

    summary = {
        "frequencies_cm-1": freqs,
        "n_imaginary_frequencies": n_imaginary,
        "zero_point_energy_hartree": _grab("Zero point energy"),
        "enthalpy_hartree": _grab("Total Enthalpy"),
        "gibbs_free_energy_hartree": _grab("Final Gibbs free energy"),
        "electronic_energy_hartree": _grab("Electronic energy"),
    }
    return {"summary": summary, "artifacts": {"raw_output": os.path.join(job_dir, "output.out")}}


def run_tddft(molecule: dict, params: dict) -> dict:
    job_dir = params["_job_dir"]
    functional = params.get("functional", "b3lyp")
    n_states = params["n_states"]
    tddft_block = "\n".join([
        "%tddft", f"  nroots {n_states}", f"  tda {'true' if params.get('use_tda', True) else 'false'}", "end",
    ])
    text = "\n".join([
        f"! {functional.upper()} {params['basis']} TightSCF", "", f"%pal nprocs {N_CORES} end", "",
        tddft_block, "", _geometry_block(molecule, params),
    ])
    output = _write_and_run(job_dir, text)

    states = _TDDFT_STATE.findall(output)  # [(state_idx, energy_eV, energy_cm-1), ...]
    section_match = _ELECTRIC_DIPOLE_SECTION.search(output)
    section_text = section_match.group(1) if section_match else ""
    osc = [float(x) for x in _ABSORPTION_ROW.findall(section_text)]

    ev = [float(e) for _, e, _ in states]
    nm = [1239.841984 / e if e > 0 else None for e in ev]

    summary = {
        "excitation_energies_eV": ev,
        "excitation_wavelengths_nm": nm,
        "oscillator_strengths": osc if len(osc) == len(ev) else osc + [None] * (len(ev) - len(osc)),
        "n_states": n_states,
        "functional": functional,
    }
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
