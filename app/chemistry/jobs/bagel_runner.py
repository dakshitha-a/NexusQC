"""BAGEL backend: CASSCF and CASPT2 (via the SMITH module).

BAGEL takes a JSON input (a pipeline of sequential blocks: molecule -> hf ->
casscf -> [smith/caspt2]) and writes plain-text output to stdout. There is
no structured output mode, so results are regex-parsed from that text;
the parsing patterns below were derived from an actual BAGEL 1.2.2 run on
this machine (water, CASSCF(4,4)/cc-pVDZ + CASPT2), not from the manual
alone, since BAGEL's manual doesn't document exact stdout formatting.

Molecule-block keywords (charge/spin do NOT live here) vs. method-block
keywords (charge/nopen on "hf", charge/nspin on "casscf") were both
verified against the official BAGEL manual (nubakery.org).
"""
from __future__ import annotations

import json
import os
import re
import subprocess

from app.config import BAGEL_BIN, BAGEL_ONEAPI_SETVARS, N_CORES

# BAGEL ships its own basis-set library (app/../share); exact matches to
# common basis names exist for the cc-pVXZ / (def2-)SVP / def2-TZVPP
# families. Anything else falls back to svp-jkfit, which is imperfect but
# keeps the job running; the summary flags this so the user can override.
_DF_BASIS_MAP = {
    "cc-pvdz": "cc-pvdz-jkfit", "cc-pvtz": "cc-pvtz-jkfit",
    "cc-pvqz": "cc-pvqz-jkfit", "cc-pv5z": "cc-pv5z-jkfit",
    "svp": "svp-jkfit", "def2-svp": "svp-jkfit",
    "tzvpp": "tzvpp-jkfit", "def2-tzvpp": "tzvpp-jkfit",
    "qzvpp": "qzvpp-jkfit", "def2-qzvpp": "qzvpp-jkfit",
}


def _df_basis_for(basis: str, explicit: str | None) -> tuple[str, bool]:
    if explicit:
        return explicit, True
    key = basis.lower()
    if key in _DF_BASIS_MAP:
        return _DF_BASIS_MAP[key], True
    return "svp-jkfit", False


def _atomic_number(symbol: str) -> int:
    from pyscf.data.elements import charge as elem_charge
    return elem_charge(symbol)


def _build_input(molecule: dict, params: dict, job_type: str) -> tuple[dict, dict]:
    basis = params["basis"]
    df_basis, df_exact_match = _df_basis_for(basis, params.get("df_basis"))

    charge = molecule["charge"]
    nopen = molecule["multiplicity"] - 1  # 2S, same convention as pyscf's mol.spin

    n_electrons = sum(_atomic_number(s) for s in molecule["symbols"]) - charge
    n_act_elec = params["active_electrons"]
    n_act_orb = params["active_orbitals"]
    if (n_electrons - n_act_elec) % 2 != 0:
        raise ValueError(
            f"active_electrons={n_act_elec} is incompatible with the system's {n_electrons} electrons "
            f"and charge={charge}/multiplicity={molecule['multiplicity']}: "
            f"(total - active) must be even so the closed-shell core has an integer number of orbital pairs"
        )
    n_closed = (n_electrons - n_act_elec) // 2
    n_states = params.get("n_states", 1)

    blocks = [
        {
            "title": "molecule",
            "basis": basis,
            "df_basis": df_basis,
            "angstrom": True,
            "geometry": [
                {"atom": sym, "xyz": list(xyz)} for sym, xyz in zip(molecule["symbols"], molecule["coords"])
            ],
        },
        {"title": "hf", "charge": charge, "nopen": nopen},
        {
            "title": "casscf",
            "nstate": n_states,
            "nact": n_act_orb,
            "nclosed": n_closed,
            "charge": charge,
            "nspin": nopen,
        },
    ]
    if job_type == "caspt2":
        ms = params.get("ms_caspt2", True)
        blocks.append({
            "title": "smith",
            "method": "caspt2",
            "ms": ms,
            "xms": ms,
            "sssr": True,
            "shift": params.get("shift", 0.2),
            "frozen": params.get("frozen_core", True),
        })

    bagel_input = {"bagel": blocks}
    meta = {
        "n_closed": n_closed, "n_electrons": n_electrons,
        "df_basis": df_basis, "df_basis_exact_match": df_exact_match,
    }
    return bagel_input, meta


def build_input_preview(job_type: str, molecule: dict, params: dict) -> str:
    """The exact JSON input a job would run with -- shared by the
    approval-preview path and run_casscf/run_caspt2 below."""
    bagel_input, _meta = _build_input(molecule, params, job_type)
    return json.dumps(bagel_input, indent=2)


def _effective_input_text(molecule: dict, params: dict, job_type: str) -> tuple[str, dict | None]:
    """Uses the user-approved edited JSON text verbatim if the approval-
    card edit path set one (see submit_job in tools.py) -- writing the
    exact bytes that were shown/approved rather than round-tripping
    through json.dump, so there's no risk of a re-serialization surprise.
    `meta` (n_closed/df_basis, computed as a side effect of building the
    structured input) is unavailable when running from raw text and comes
    back None; callers report those summary fields as unknown rather than
    guessing at values that may no longer match the edited input."""
    raw = params.get("_raw_input")
    if raw is not None:
        return raw, None
    bagel_input, meta = _build_input(molecule, params, job_type)
    return json.dumps(bagel_input, indent=2), meta


def _safe_parse(build_summary, output: str, job_dir: str, job_type: str) -> dict:
    """Mirrors orca_runner._safe_parse: converts a parse failure into a
    clear, actionable error (pointing at the preserved raw output) rather
    than losing context in a bare traceback -- expected to matter mainly
    after a hand-edited input changes what BAGEL actually prints."""
    try:
        return build_summary()
    except Exception as e:
        raw_path = os.path.join(job_dir, "bagel.out")
        raise RuntimeError(
            f"BAGEL ran to completion but the '{job_type}' output parser could not find the expected "
            f"results ({type(e).__name__}: {e}). If the input was hand-edited, it may no longer match "
            f"what this job type expects to see (e.g. a different 'nstate'). Raw output saved at "
            f"{raw_path}. Last part of output:\n{output[-2000:]}"
        ) from e


def _run_bagel(job_dir: str, input_text: str) -> str:
    input_path = os.path.join(job_dir, "input.json")
    out_path = os.path.join(job_dir, "bagel.out")
    with open(input_path, "w") as f:
        f.write(input_text)

    cmd = (
        f'source {BAGEL_ONEAPI_SETVARS} > /dev/null 2>&1; '
        f'export OMP_NUM_THREADS={N_CORES} MKL_NUM_THREADS={N_CORES}; '
        f'cd "{job_dir}" && "{BAGEL_BIN}" input.json > bagel.out 2>&1'
    )
    proc = subprocess.run(["bash", "-c", cmd], timeout=6 * 3600)
    with open(out_path) as f:
        output = f.read()
    if proc.returncode != 0:
        raise RuntimeError(f"BAGEL exited with code {proc.returncode}. Last 3000 chars of output:\n{output[-3000:]}")
    return output


# Matches the per-iteration "iter  state  energy  residual  time" rows that
# appear in BOTH the CASSCF macro-iteration table and the nested FCI-solve
# table; taking the *last* row per state index across the whole file gives
# the fully converged CASSCF energy for that state.
_CASSCF_ROW = re.compile(r"^\s*\d+\s+(\d+)\s+(-?\d+\.\d{6,})\s", re.MULTILINE)
_CASPT2_ROW = re.compile(r"CASPT2 energy\s*:\s*state\s+(\d+)\s+(-?\d+\.\d+)")


def _parse_casscf_energies(output: str, n_states: int) -> dict[int, float]:
    energies: dict[int, float] = {}
    for m in _CASSCF_ROW.finditer(output):
        state, energy = int(m.group(1)), float(m.group(2))
        if state < n_states:
            energies[state] = energy  # keep overwriting -> last occurrence wins
    return energies


def _parse_caspt2_energies(output: str) -> dict[int, float]:
    energies: dict[int, float] = {}
    for m in _CASPT2_ROW.finditer(output):
        energies[int(m.group(1))] = float(m.group(2))
    return energies


def run_casscf(molecule: dict, params: dict) -> dict:
    job_dir = params["_job_dir"]
    input_text, meta = _effective_input_text(molecule, params, "casscf")
    output = _run_bagel(job_dir, input_text)

    n_states = params.get("n_states", 1)

    def build_summary():
        state_energies = _parse_casscf_energies(output, n_states)
        if len(state_energies) < n_states:
            raise RuntimeError(f"found converged energies for {len(state_energies)} of {n_states} state(s)")
        return {
            "state_energies_hartree": [state_energies[i] for i in range(n_states)],
            "casscf_energy_hartree": state_energies[0] if n_states == 1 else None,
            "active_electrons": params.get("active_electrons"),
            "active_orbitals": params.get("active_orbitals"),
            "n_closed_orbitals": meta["n_closed"] if meta else None,
            "n_states": n_states,
            "df_basis_used": meta["df_basis"] if meta else None,
            "df_basis_exact_match": meta["df_basis_exact_match"] if meta else None,
        }

    summary = _safe_parse(build_summary, output, job_dir, "casscf")
    return {"summary": summary, "artifacts": {"raw_output": os.path.join(job_dir, "bagel.out")}}


def run_caspt2(molecule: dict, params: dict) -> dict:
    job_dir = params["_job_dir"]
    input_text, meta = _effective_input_text(molecule, params, "caspt2")
    output = _run_bagel(job_dir, input_text)

    n_states = params.get("n_states", 1)

    def build_summary():
        casscf_energies = _parse_casscf_energies(output, n_states)
        caspt2_energies = _parse_caspt2_energies(output)
        if len(caspt2_energies) < n_states:
            raise RuntimeError(f"found converged CASPT2 energies for {len(caspt2_energies)} of {n_states} state(s)")
        return {
            "state_energies_hartree": [caspt2_energies[i] for i in range(n_states)],
            "caspt2_energy_hartree": caspt2_energies[0] if n_states == 1 else None,
            "casscf_reference_energies_hartree": [casscf_energies.get(i) for i in range(n_states)],
            "active_electrons": params.get("active_electrons"),
            "active_orbitals": params.get("active_orbitals"),
            "n_closed_orbitals": meta["n_closed"] if meta else None,
            "n_states": n_states,
            "ms_caspt2": params.get("ms_caspt2", True),
            "shift": params.get("shift", 0.2),
            "frozen_core": params.get("frozen_core", True),
            "df_basis_used": meta["df_basis"] if meta else None,
            "df_basis_exact_match": meta["df_basis_exact_match"] if meta else None,
        }

    summary = _safe_parse(build_summary, output, job_dir, "caspt2")
    return {"summary": summary, "artifacts": {"raw_output": os.path.join(job_dir, "bagel.out")}}
