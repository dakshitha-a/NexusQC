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

from app.chemistry.jobs.ci_transitions import aggregate_by_configuration, format_dominant, leading_single_excitations
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


def _resolve_orbital_indices_bagel(spec, homo_1based: int, n_mo: int) -> dict[str, int]:
    """1-based orbital indices from a HOMO/LUMO/HOMO-k/LUMO+k/1-based-int
    spec -- matches the 1-based indexing app.chemistry.jobs.molden already
    uses (both orbital_table() and cube_for_orbital())."""
    if isinstance(spec, str):
        spec = [spec]
    out: dict[str, int] = {}
    for item in spec:
        item_str = str(item).strip().upper()
        if item_str == "HOMO":
            out["HOMO"] = homo_1based
        elif item_str == "LUMO":
            out["LUMO"] = homo_1based + 1
        elif item_str.startswith("HOMO-"):
            out[item_str] = homo_1based - int(item_str.split("-")[1])
        elif item_str.startswith("LUMO+"):
            out[item_str] = homo_1based + 1 + int(item_str.split("+")[1])
        else:
            out[str(int(item_str))] = int(item_str)  # already 1-based
    for label, idx in out.items():
        if idx < 1 or idx > n_mo:
            raise ValueError(f"orbital '{label}' (index {idx}) is out of range for {n_mo} molecular orbitals")
    return out


def _molecule_block(molecule: dict, basis: str, df_basis: str) -> dict:
    return {
        "title": "molecule",
        "basis": basis,
        "df_basis": df_basis,
        "angstrom": True,
        "geometry": [{"atom": sym, "xyz": list(xyz)} for sym, xyz in zip(molecule["symbols"], molecule["coords"])],
    }


def _build_input(molecule: dict, params: dict, job_type: str) -> tuple[dict, dict]:
    basis = params["basis"]
    df_basis, df_exact_match = _df_basis_for(basis, params.get("df_basis"))

    charge = molecule["charge"]
    nopen = molecule["multiplicity"] - 1  # 2S, same convention as pyscf's mol.spin

    if job_type == "frequency":
        # HF-reference only -- parity with pyscf/orca's frequency job type
        # (also HF/DFT, no CASSCF), not BAGEL's general CASSCF/CASPT2-
        # Hessian capability. The "hessian" block is top-level (alongside
        # "molecule"), with the wavefunction spec nested inside its own
        # "method" array rather than as separate preceding blocks --
        # confirmed against the BAGEL manual's worked example (a CASPT2
        # Hessian for benzene uses the same nested-method-array shape).
        method = params.get("method", "hf")
        if method != "hf":
            raise ValueError("BAGEL frequency in this app only supports method='hf' (no DFT reference)")
        dx = params.get("dx") or 1.0e-3
        blocks = [
            _molecule_block(molecule, basis, df_basis),
            {
                "title": "hessian",
                "method": [{"title": "hf", "charge": charge, "nopen": nopen}],
                "dx": dx,
            },
        ]
        bagel_input = {"bagel": blocks}
        meta = {"df_basis": df_basis, "df_basis_exact_match": df_exact_match, "dx": dx}
        return bagel_input, meta

    if job_type == "mo_visualization":
        # HF-reference only, same scope restriction as "frequency" above.
        #
        # Cube generation goes through a molden export + app.chemistry.
        # jobs.molden (pyscf.tools.molden/cubegen), NOT BAGEL's own native
        # "moprint" block -- moprint was tried first and rejected after
        # real verification: its cube files turned out to be per-orbital
        # electron DENSITY (|psi|^2 -- confirmed by the output values being
        # non-negative everywhere and, along a line through the atoms,
        # forming a symmetric double lobe with a node at the center rather
        # than the antisymmetric +/- shape a real p-orbital amplitude
        # must have), not the signed wavefunction amplitude this app's
        # two-isosurface (blue/red lobe) MO viewer needs -- and its output
        # includes no per-orbital energy table at all. BAGEL's molden
        # export instead round-tripped perfectly (AO evaluation matrices
        # matched a native PySCF calculation on the same geometry/basis to
        # an exact ratio of 1.0 at every sampled point, unlike ORCA's
        # molden export -- see orca_runner.render_orbital_cube's docstring for
        # that story) and also carries real per-orbital energies/
        # occupancies molden.orbital_table() can read directly, solving
        # both problems moprint had at once.
        method = params.get("method", "hf")
        if method != "hf":
            raise ValueError("BAGEL mo_visualization in this app only supports method='hf' (no DFT reference)")
        if nopen != 0:
            raise ValueError("BAGEL mo_visualization in this app only supports closed-shell (restricted) systems")
        blocks = [
            _molecule_block(molecule, basis, df_basis),
            {"title": "hf", "charge": charge, "nopen": nopen},
            {"title": "print", "file": "orbitals.molden", "orbitals": True},
        ]
        bagel_input = {"bagel": blocks}
        meta = {"df_basis": df_basis, "df_basis_exact_match": df_exact_match}
        return bagel_input, meta

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
        _molecule_block(molecule, basis, df_basis),
        {"title": "hf", "charge": charge, "nopen": nopen},
        {
            "title": "casscf",
            "nstate": n_states,
            "nact": n_act_orb,
            "nclosed": n_closed,
            "charge": charge,
            "nspin": nopen,
        },
        # Same "print"/molden block as mo_visualization, placed immediately
        # after "casscf" -- NOT after "smith"/caspt2 below. This placement
        # was not a guess: an earlier version put it last in the pipeline
        # (after smith too, reasoning that CASPT2 doesn't reoptimize
        # orbitals so it shouldn't matter), and a real run caught this
        # being wrong -- exporting after "smith" gives a molden file with
        # every occupation flattened to integer 0/2 and every energy at
        # 0.0, i.e. BAGEL's "current wavefunction" the print block reads
        # from is no longer the CASSCF natural-orbital state once smith
        # has run. Exporting right after "casscf" instead gives genuinely
        # fractional active-space occupations (confirmed on a real
        # CAS(4,4)/cc-pVDZ water run), which is also the semantically
        # correct choice regardless: CASPT2 is a perturbative energy
        # correction on top of the fixed CASSCF reference orbitals, so the
        # orbitals to visualize are the same whether or not a caspt2 step
        # follows.
        {"title": "print", "file": "orbitals.molden", "orbitals": True},
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

# CI-vector blocks, e.g.:
#   * ci vector, state   1, <S^2> = 0.0000
#     22222ab..     0.6579076241
#     22222ba..     0.6579076241
# One char per active orbital (ascending left to right, starting at
# orbital n_closed+1): '2' doubly occupied, 'a'/'b' singly occupied
# alpha/beta, '.' empty. A CASPT2 run prints this block TWICE (once for
# the CASSCF reference, again for the CASPT2-perturbed step reusing the
# same natural orbitals) -- _dominant_transitions_bagel always uses the
# LAST such block, which also happens to be correct for a plain CASSCF
# run (exactly one block there).
_CI_VECTOR_STATE = re.compile(r"\*\s*ci vector,\s*state\s+(\d+),")
_CI_VECTOR_LINE = re.compile(r"^\s*([0-9ab.]+)\s+(-?\d+\.\d+)\s*$", re.MULTILINE)
_OCC_CHAR_COUNTS = {"2": 2, "1": 1, "0": 0, "a": 1, "b": 1, ".": 0}

# BAGEL prints frequencies (and separately, IR intensities) in blocks of up
# to 6 mode columns each, one "Freq (cm-1)"/"IR Int. (km/mol)" row per
# block -- derived from a real water/HF/STO-3G numerical-Hessian run, not
# the manual alone (which only documents the JSON input keywords, not the
# stdout format). Modes are listed in ascending index order across blocks,
# and (for a nonlinear molecule) always include the 6 near-zero
# translational/rotational modes BAGEL projects out but still prints --
# kept in the result rather than dropped, matching orca_runner's
# _FREQ_LINE, which likewise keeps every mode ORCA prints without
# filtering; the two text-parsed engines stay consistent with each other.
_HESSIAN_FREQ_ROW = re.compile(r"^\s*Freq \(cm-1\)\s+(.+)$", re.MULTILINE)
_HESSIAN_IR_ROW = re.compile(r"^\s*IR Int\. \(km/mol\)\s+(.+)$", re.MULTILINE)


def _parse_row_values(rows: list[str]) -> list[float]:
    values: list[float] = []
    for row in rows:
        values.extend(float(x) for x in row.split())
    return values


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


def _dominant_transitions_bagel(output: str, n_states: int, n_closed: int | None) -> list[str | None]:
    """Leading CI configurations from the LAST 'ci vector, state N' block in
    the output -- a block boundary is detected by the state index resetting
    back to 0, which correctly picks out the CASPT2-refined block for a
    caspt2 job (two blocks total) and the only block for a plain casscf job
    (one block), matching _CI_VECTOR_STATE's docstring."""
    result: list[str | None] = [None] * n_states
    if n_closed is None:
        return result
    headers = list(_CI_VECTOR_STATE.finditer(output))
    if not headers:
        return result
    blocks: list[list[re.Match]] = []
    for h in headers:
        if int(h.group(1)) == 0 or not blocks:
            blocks.append([])
        blocks[-1].append(h)
    last_block = blocks[-1]

    per_state: dict[int, list[tuple[float, list[int]]]] = {}
    all_configs: list[tuple[float, list[int]]] = []
    for h in last_block:
        state_idx = int(h.group(1))
        pos = headers.index(h)
        start = h.end()
        end = headers[pos + 1].start() if pos + 1 < len(headers) else len(output)
        window = output[start:end]
        raw: list[tuple[float, list[int]]] = []
        for occ, coef_str in _CI_VECTOR_LINE.findall(window):
            try:
                counts = [_OCC_CHAR_COUNTS[ch] for ch in occ]
            except KeyError:
                continue
            raw.append((float(coef_str), counts))
        configs = aggregate_by_configuration(raw)
        per_state[state_idx] = configs
        all_configs.extend(configs)

    if not all_configs:
        return result
    _, reference_counts = max(all_configs, key=lambda c: c[0])

    for state_idx, configs in per_state.items():
        if not (0 <= state_idx < n_states):
            continue
        transitions = leading_single_excitations(configs, reference_counts, n_closed)
        result[state_idx] = format_dominant(transitions)
    return result


def _add_orbital_table(summary: dict, job_dir: str) -> str | None:
    """Reads the orbitals.molden the "print" block appended to every
    casscf/caspt2 input (see _build_input) writes, and adds the {index,
    spin, energy_eV, occupancy} table OrbitalTable.tsx renders to
    `summary` in place -- same shape as PySCF's/ORCA's CASSCF orbital
    tables, so the frontend doesn't special-case BAGEL. Returns the
    molden path for the caller's artifacts dict, or None if the print
    block didn't produce one (e.g. a hand-edited input removed it) --
    best-effort, not a hard requirement, since orbital visualization is a
    bonus on top of the actual energies this job exists to compute."""
    molden_path = os.path.join(job_dir, "orbitals.molden")
    if not os.path.exists(molden_path):
        return None
    from app.chemistry.jobs import molden as molden_tools

    summary["orbital_table"] = molden_tools.orbital_table(molden_path)
    summary["orbital_table_note"] = (
        "Natural orbitals with active-space occupation numbers (not integer HF-style occupancies) -- "
        "core orbitals show occ=2, active orbitals show their natural-orbital occupation, virtuals show occ=0. "
        "BAGEL's own molden export also writes energy_eV=0.0 for every active-space orbital (confirmed in the "
        "raw .molden file, not a parsing gap here) -- it has no single-particle Fock eigenvalue for a "
        "multi-configurational active orbital the way core/virtual orbitals do, unlike ORCA/PySCF's CASSCF "
        "exports, which report a generalized-Fock-based energy there instead."
    )
    return molden_path


def run_casscf(molecule: dict, params: dict) -> dict:
    job_dir = params["_job_dir"]
    input_text, meta = _effective_input_text(molecule, params, "casscf")
    output = _run_bagel(job_dir, input_text)

    n_states = params.get("n_states", 1)

    def build_summary():
        state_energies = _parse_casscf_energies(output, n_states)
        if len(state_energies) < n_states:
            raise RuntimeError(f"found converged energies for {len(state_energies)} of {n_states} state(s)")
        n_closed = meta["n_closed"] if meta else None
        summary = {
            "state_energies_hartree": [state_energies[i] for i in range(n_states)],
            "casscf_energy_hartree": state_energies[0] if n_states == 1 else None,
            "active_electrons": params.get("active_electrons"),
            "active_orbitals": params.get("active_orbitals"),
            "n_closed_orbitals": n_closed,
            "n_states": n_states,
            "dominant_transitions": _dominant_transitions_bagel(output, n_states, n_closed),
            "df_basis_used": meta["df_basis"] if meta else None,
            "df_basis_exact_match": meta["df_basis_exact_match"] if meta else None,
        }
        return summary, _add_orbital_table(summary, job_dir)

    summary, molden_path = _safe_parse(build_summary, output, job_dir, "casscf")
    artifacts = {"raw_output": os.path.join(job_dir, "bagel.out")}
    if molden_path:
        artifacts["molden"] = molden_path
    return {"summary": summary, "artifacts": artifacts}


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
        n_closed = meta["n_closed"] if meta else None
        summary = {
            "state_energies_hartree": [caspt2_energies[i] for i in range(n_states)],
            "caspt2_energy_hartree": caspt2_energies[0] if n_states == 1 else None,
            "casscf_reference_energies_hartree": [casscf_energies.get(i) for i in range(n_states)],
            "active_electrons": params.get("active_electrons"),
            "active_orbitals": params.get("active_orbitals"),
            "n_closed_orbitals": n_closed,
            "n_states": n_states,
            # The last ci-vector block in the output is the CASPT2-refined
            # one (see _dominant_transitions_bagel), consistent with these
            # being CASPT2-perturbed states, not the CASSCF reference.
            "dominant_transitions": _dominant_transitions_bagel(output, n_states, n_closed),
            "ms_caspt2": params.get("ms_caspt2", True),
            "shift": params.get("shift", 0.2),
            "frozen_core": params.get("frozen_core", True),
            "df_basis_used": meta["df_basis"] if meta else None,
            "df_basis_exact_match": meta["df_basis_exact_match"] if meta else None,
        }
        return summary, _add_orbital_table(summary, job_dir)

    summary, molden_path = _safe_parse(build_summary, output, job_dir, "caspt2")
    artifacts = {"raw_output": os.path.join(job_dir, "bagel.out")}
    if molden_path:
        artifacts["molden"] = molden_path
    return {"summary": summary, "artifacts": artifacts}


# Below this magnitude, a negative "frequency" is numerical noise in one
# of the 6 (nonlinear molecule) translational/rotational modes BAGEL
# projects out but still prints, not a genuine imaginary mode -- confirmed
# on a real water/HF/STO-3G run, which printed -5.88 cm-1 for one such
# projected mode purely from the numerical Hessian's finite-difference
# noise (BAGEL's central-difference Hessian is inherently less exact here
# than PySCF/ORCA's analytic ones, which print a clean 0.00 for the same
# modes). 50 cm-1 is a conventional low-frequency cutoff in this
# situation -- comfortably above observed projection noise, comfortably
# below any real vibrational or soft transition-state mode.
_IMAGINARY_THRESHOLD_CM1 = 50.0


def run_frequency(molecule: dict, params: dict) -> dict:
    """Numerical Hessian via central gradient differences (HF reference
    only in this app -- see _build_input). Real water/HF/STO-3G run
    verified the frequencies land in the same ballpark as PySCF/ORCA's
    analytic Hessian for the same system (~2000-4800 cm-1 range), as
    expected for a different but comparable numerical method.

    Unlike PySCF/ORCA, BAGEL's Hessian module does not print
    zero-point-energy/enthalpy/Gibbs/entropy thermochemistry -- omitted
    from the summary (via thermochemistry_note) rather than fabricated.
    Cartesian normal-mode eigenvectors ARE printed but are not parsed
    here: extracting them requires reassembling per-atom-component rows
    across multiple 6-column blocks, and the only consumer
    (ModeAnimationViewer) is PySCF-only for now -- a real, stated gap
    against the original Phase 3 plan, not an oversight."""
    job_dir = params["_job_dir"]
    input_text, meta = _effective_input_text(molecule, params, "frequency")
    output = _run_bagel(job_dir, input_text)

    def build_summary():
        freqs = _parse_row_values(_HESSIAN_FREQ_ROW.findall(output))
        if not freqs:
            raise RuntimeError("could not find any 'Freq (cm-1)' rows in the output")
        ir = _parse_row_values(_HESSIAN_IR_ROW.findall(output))
        n_imaginary = sum(1 for f in freqs if f < -_IMAGINARY_THRESHOLD_CM1)
        return {
            "frequencies_cm-1": freqs,
            "n_imaginary_frequencies": n_imaginary,
            "ir_intensities_km_mol": ir if len(ir) == len(freqs) else None,
            "thermochemistry_note": (
                "BAGEL's Hessian module does not compute zero-point energy/enthalpy/Gibbs free "
                "energy/entropy in this app -- frequencies and IR intensities only."
            ),
            "dx_bohr": meta["dx"] if meta else None,
            "df_basis_used": meta["df_basis"] if meta else None,
            "df_basis_exact_match": meta["df_basis_exact_match"] if meta else None,
        }

    summary = _safe_parse(build_summary, output, job_dir, "frequency")
    return {"summary": summary, "artifacts": {"raw_output": os.path.join(job_dir, "bagel.out")}}


def run_mo_visualization(molecule: dict, params: dict) -> dict:
    """Cube generation via a molden export (see _build_input's
    "mo_visualization" branch for why this app's own molden.py module is
    the right tool here, unlike for ORCA) -- BAGEL's molden export was
    verified to round-trip exactly through pyscf.tools.molden (AO
    evaluation matrices matched a native PySCF calculation on the same
    geometry/basis at an exact 1.0 ratio, at several off-axis points),
    and it carries real per-orbital energies/occupancies, unlike the
    "moprint" alternative this function used before that verification."""
    job_dir = params["_job_dir"]
    input_text, meta = _effective_input_text(molecule, params, "mo_visualization")
    output = _run_bagel(job_dir, input_text)

    def build_summary():
        from app.chemistry.jobs import molden as molden_tools

        molden_path = os.path.join(job_dir, "orbitals.molden")
        if not os.path.exists(molden_path):
            raise RuntimeError("BAGEL did not produce the expected orbitals.molden file")

        table = molden_tools.orbital_table(molden_path)
        occupied = [row["index"] for row in table if row["occupancy"] > 0]
        if not occupied:
            raise RuntimeError("no occupied orbitals found in orbitals.molden")
        homo_1based = max(occupied)
        indices_1based = _resolve_orbital_indices_bagel(params["orbital_indices"], homo_1based, len(table))

        cube_paths = {}
        for label, idx in indices_1based.items():
            cube_path = os.path.join(job_dir, f"mo_{label}.cube")
            molden_tools.cube_for_orbital(molden_path, idx, cube_path)
            cube_paths[label] = cube_path

        energy_by_index = {row["index"]: row["energy_eV"] for row in table}
        return {
            "homo_index_1based": homo_1based,
            "orbitals_rendered": dict(indices_1based),
            "mo_energies_eV": {label: energy_by_index[idx] for label, idx in indices_1based.items()},
            "orbital_table": table,
            "df_basis_used": meta["df_basis"] if meta else None,
            "df_basis_exact_match": meta["df_basis_exact_match"] if meta else None,
        }, cube_paths, molden_path

    summary, cube_paths, molden_path = _safe_parse(build_summary, output, job_dir, "mo_visualization")
    return {
        "summary": summary,
        "artifacts": {"cubes": cube_paths, "molden": molden_path, "raw_output": os.path.join(job_dir, "bagel.out")},
    }
