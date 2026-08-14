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

from app.chemistry.jobs.ci_transitions import format_dominant, leading_single_excitations
from app.config import ORCA_BIN, ORCA_PLOT_BIN, N_CORES

_FINAL_ENERGY = re.compile(r"FINAL SINGLE POINT ENERGY\s+(-?\d+\.\d+)")
_CARTESIAN_BLOCK = re.compile(
    r"CARTESIAN COORDINATES \(ANGSTROEM\)\n-+\n((?:\s*[A-Za-z]+\s+-?\d+\.\d+\s+-?\d+\.\d+\s+-?\d+\.\d+\n)+)"
)
_FREQ_LINE = re.compile(r"^\s*\d+:\s+(-?\d+\.\d+)\s+cm\*\*-1", re.MULTILINE)
_ORBITAL_ROW = re.compile(r"^\s*\d+\s+(-?\d+\.\d+)\s+(-?\d+\.\d+)\s+(-?\d+\.\d+)\s*$", re.MULTILINE)
_TDDFT_STATE = re.compile(
    r"STATE\s+(\d+):\s+E=\s+-?\d+\.\d+\s+au\s+(-?\d+\.\d+)\s+eV\s+(-?\d+\.\d+)\s+cm\*\*-1"
)
# Per-transition contribution lines directly under each "STATE N: E=..."
# header, e.g. "     4a ->   5a  :     1.000000 (c=  1.00000000)" -- 0-based
# spin-orbital indices, weight (not the CI coefficient in parens). Only
# matches the restricted ("a"-only) case; ORCA prints separate "a"/"b"
# columns for unrestricted references, which this app doesn't attempt to
# disambiguate here (dominant transition is left unavailable instead).
_TDDFT_CONTRIB_LINE = re.compile(r"^\s*(\d+)a\s*->\s*(\d+)a\s*:\s*(-?\d+\.\d+)", re.MULTILINE)
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
# Per-transition amplitude lines under each "IROOT=" header's "Amplitude
# Excitation" sub-table, e.g. "  -0.576722    26 ->  29" -- unlike TDDFT's
# contribution lines, these carry no trailing spin letter and no separate
# "(c=...)" value: the printed number IS the signed CI-like amplitude
# directly (not a squared weight), so it's used as-is rather than needing
# any weight/coefficient distinction.
_EOM_AMP_LINE = re.compile(r"^\s*(-?\d+\.\d+)\s+(\d+)\s*->\s*(\d+)\s*$", re.MULTILINE)
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
# CI-configuration lines directly under each "ROOT N: E=..." header, e.g.
# "      0.89903 [  1552]: 222221100" -- one digit (0/1/2 occupation) per
# active orbital, ascending left to right starting at the lowest active
# orbital. The determinant index in brackets is not needed for anything
# here.
_CASSCF_CONFIG_LINE = re.compile(r"^\s*(\d+\.\d+)\s*\[\s*\d+\]:\s*([0-9]+)\s*$", re.MULTILINE)


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
        # LargePrint (same reasoning as mo_visualization below) so the full
        # ORBITAL ENERGIES table -- not just the first 10 virtuals -- is
        # always available for lazy orbital visualization, without the
        # user having to know in advance they'll want it.
        return "\n".join([
            _method_line(params) + " LargePrint", "", f"%pal nprocs {N_CORES} end", "",
            _geometry_block(molecule, params),
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
            _method_line(params) + " LargePrint", "", f"%pal nprocs {N_CORES} end", "",
            _tddft_block(params), "", _geometry_block(molecule, params),
        ])
    if job_type == "eom_ccsd":
        # EOM-CCSD is inherently post-HF -- no method/functional choice.
        return "\n".join([
            f"! HF EOM-CCSD {params['basis']} TightSCF LargePrint", "", f"%pal nprocs {N_CORES} end", "",
            _mdci_eom_block(params), "", _geometry_block(molecule, params),
        ])
    if job_type == "casscf":
        # LargePrint (same reasoning as single_point/tddft/eom_ccsd above)
        # -- confirmed on a real run that ORCA prints exactly one "ORBITAL
        # ENERGIES" table for a %casscf job, appearing right after "CASSCF
        # RESULTS"/"Final CASSCF energy" (the *converged* natural-orbital
        # occupations -- active orbitals come out genuinely fractional,
        # e.g. 1.998/1.987/0.013/0.001 for a CAS(4,4), not the integer 0/2
        # of the pre-CASSCF HF guess), so the shared _orbital_table() below
        # needs no CASSCF-specific handling; it just happens to find the
        # right block since there's only one.
        return "\n".join([
            f"! {params['basis']} TightSCF LargePrint", "", f"%pal nprocs {N_CORES} end", "",
            _casscf_block(molecule, params), "", _geometry_block(molecule, params),
        ])
    if job_type == "mo_visualization":
        # Orbitals themselves are rendered afterward straight from the
        # resulting .gbw via orca_plot (see render_orbital_cube), not from this
        # text output at all -- but the ORBITAL ENERGIES table (used for
        # HOMO/LUMO detection and _orbital_table's energy/occupancy
        # columns) is truncated to the first 10 virtuals by default
        # (confirmed on a real def2-SVP water run: only 16 of 24 MOs were
        # printed, with a literal "*Only the first 10 virtual orbitals
        # were printed." line). !LargePrint forces the full table.
        # (An earlier attempt used "%output Print[P_MOs] 1 end" instead --
        # that also prints every orbital's full coefficient matrix right
        # after the (still-truncated) ORBITAL ENERGIES table with no blank
        # line separating them, which broke _orbital_energy_rows' regex by
        # feeding it "MOLECULAR ORBITALS" section text. !LargePrint prints
        # the untruncated energies table alone, with the same format as
        # the default output, so no parser change is needed.)
        return "\n".join([
            f"{_method_line(params)} LargePrint", "", f"%pal nprocs {N_CORES} end", "",
            _geometry_block(molecule, params),
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
        return {
            "energy_hartree": float(_FINAL_ENERGY.findall(output)[-1]),
            "method": params.get("method"),
            "functional": params.get("functional"),
            "basis": params.get("basis"),
            "homo_lumo_gap_eV": _homo_lumo_gap(output),
            "orbital_table": _orbital_table(output),
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
        # ORCA prints "FINAL SINGLE POINT ENERGY" once per optimization
        # cycle plus one more after the final single-point re-evaluation at
        # the converged geometry -- the same values geomeTRIC's per-step
        # callback captures for the PySCF path (both real-run-verified
        # against water/HF/STO-3G: monotonically decreasing to the last
        # entry, which matches final_energy_hartree exactly).
        energies = [float(e) for e in _FINAL_ENERGY.findall(output)]
        return {
            "final_energy_hartree": energies[-1],
            "converged": True,
            "optimized_molecule": _extract_final_geometry(output, molecule),
            "optimization_energies_hartree": energies,
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


def _rank_transitions(contribs: list[tuple[int, int, float]], max_results: int = 2) -> list[tuple[int, int, float]]:
    """contribs: (source_orbital_1based, target_orbital_1based, weight)
    triples for one state, weight = |CI coefficient|^2 (non-negative) --
    returns up to max_results, ranked by descending weight."""
    return sorted(contribs, key=lambda t: t[2], reverse=True)[:max_results]


def _dominant_transitions_orca(output: str, n_states: int, restricted: bool) -> list[str | None]:
    """TDDFT/CIS dominant transitions, as the two largest-|weight|
    orbital-number pairs (weight = |CI coefficient|^2 for both TDA/TDDFT
    and CIS -- ORCA prints the same unlabeled "weight" column for both;
    CIS additionally prints a signed "(c=...)" coefficient this app doesn't
    use, so the same column/logic covers both methods identically).
    Restricted references only -- ORCA prints separate a/b spin-orbital
    columns for unrestricted references, which _TDDFT_CONTRIB_LINE's
    "Na -> Ma" pattern doesn't disambiguate; left unavailable there rather
    than risking a wrong/partial read."""
    result: list[str | None] = [None] * n_states
    if not restricted:
        return result
    matches = list(_TDDFT_STATE.finditer(output))
    for i, m in enumerate(matches):
        state_idx = int(m.group(1))
        if not (1 <= state_idx <= n_states):
            continue
        start = m.end()
        # Bound tightly: contribution lines for a state end at the first
        # blank line (verified against a real run -- ORCA always emits
        # exactly one blank line after the last contribution before moving
        # on), or at the next STATE header if that comes first. An
        # unbounded/fixed-width window would risk bleeding into the
        # following ABSORPTION SPECTRUM table on a larger job, the same
        # class of mistake _ELECTRIC_DIPOLE_SECTION/_CASSCF_BLOCK are
        # already careful to avoid.
        next_state_start = matches[i + 1].start() if i + 1 < len(matches) else len(output)
        blank_line = output.find("\n\n", start)
        end = min(next_state_start, blank_line) if blank_line != -1 else next_state_start
        contribs = [
            (int(a) + 1, int(b) + 1, float(w))
            for a, b, w in _TDDFT_CONTRIB_LINE.findall(output[start:end])
        ]
        if not contribs:
            continue
        result[state_idx - 1] = format_dominant(_rank_transitions(contribs))
    return result


def _dominant_transitions_eom_orca(rhs_section_text: str, n_states: int, restricted: bool) -> list[str | None]:
    """EOM-CCSD amplitude lines ('  -0.576722    26 ->  29') are the actual
    signed CI-like amplitudes (unlike TDDFT/CIS's unsigned "weight" column)
    -- squared here so every method displays the same "weight (c^2)"
    quantity. Bounded to each IROOT's own amplitude sub-table."""
    result: list[str | None] = [None] * n_states
    if not restricted:
        return result
    headers = list(_EOM_IROOT.finditer(rhs_section_text))
    for i, m in enumerate(headers):
        iroot = int(m.group(1))
        if not (1 <= iroot <= n_states):
            continue
        start = m.end()
        end = headers[i + 1].start() if i + 1 < len(headers) else len(rhs_section_text)
        window = rhs_section_text[start:end]
        gs_amp = window.find("Ground state amplitude")
        if gs_amp != -1:
            window = window[:gs_amp]
        contribs = [(int(a) + 1, int(b) + 1, float(w) ** 2) for w, a, b in _EOM_AMP_LINE.findall(window)]
        if not contribs:
            continue
        result[iroot - 1] = format_dominant(_rank_transitions(contribs))
    return result


def _n_electrons(molecule: dict) -> int:
    from pyscf.data.elements import charge as elem_charge

    return sum(elem_charge(s) for s in molecule["symbols"]) - molecule["charge"]


def _dominant_transitions_casscf_orca(block_text: str, n_states: int, n_closed: int) -> list[str | None]:
    """Leading CI configurations for each ROOT, e.g.:
        ROOT   1:  E=...
              0.89903 [  1552]: 222221100
              0.02565 [  1540]: 222211200
    Each digit is the occupation (0/1/2) of one active orbital, ascending
    left to right starting at orbital n_closed+1. The reference determinant
    a config is diffed against (to find source/target orbitals) is the
    single highest-|weight| config across ALL roots, not root 0's -- CASSCF
    roots aren't guaranteed to come out in an order where root 0 is the
    reference/ground-like configuration (see ci_transitions.py's docstring
    for why)."""
    root_headers = list(_CASSCF_ROOT.finditer(block_text))
    if not root_headers:
        return [None] * n_states
    per_root: dict[int, list[tuple[float, list[int]]]] = {}
    all_configs: list[tuple[float, list[int]]] = []
    for i, m in enumerate(root_headers):
        root_idx = int(m.group(1))
        start = m.end()
        end = root_headers[i + 1].start() if i + 1 < len(root_headers) else len(block_text)
        configs = [
            (float(w), [int(ch) for ch in occ])
            for w, occ in _CASSCF_CONFIG_LINE.findall(block_text[start:end])
        ]
        configs.sort(key=lambda c: abs(c[0]), reverse=True)  # defensive; ORCA already prints descending
        per_root[root_idx] = configs
        all_configs.extend(configs)
    if not all_configs:
        return [None] * n_states

    _, reference_counts = max(all_configs, key=lambda c: abs(c[0]))
    result: list[str | None] = [None] * n_states
    for root_idx, configs in per_root.items():
        if not (0 <= root_idx < n_states):
            continue
        transitions = leading_single_excitations(configs, reference_counts, n_closed)
        result[root_idx] = format_dominant(transitions)
    return result


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
        dominant = _dominant_transitions_orca(output, len(ev), molecule["multiplicity"] == 1)

        return {
            "excitation_energies_eV": ev,
            "excitation_wavelengths_nm": nm,
            "oscillator_strengths": osc if len(osc) == len(ev) else osc + [None] * (len(ev) - len(osc)),
            "dominant_transitions": dominant,
            "n_states": n_states,
            "method": method,
            "functional": functional,
            "level_of_theory": ("CIS" if (method == "hf" and use_tda) else
                                 "TD-HF/RPA" if method == "hf" else
                                 "TDA-DFT" if use_tda else "TDDFT"),
            "orbital_table": _orbital_table(output),
            "orbital_table_note": (
                "These are the ground-state reference orbitals used to build the excitations above, "
                "not excited-state-relaxed natural orbitals."
            ),
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
        dominant = _dominant_transitions_eom_orca(section.group(1), len(ev), molecule["multiplicity"] == 1)

        return {
            "excitation_energies_eV": ev,
            "excitation_wavelengths_nm": nm,
            "oscillator_strengths": osc,
            "dominant_transitions": dominant,
            "n_states": n_states,
            "level_of_theory": "EOM-CCSD",
            "orbital_table": _orbital_table(output),
            "orbital_table_note": (
                "These are the ground-state HF reference orbitals CCSD/EOM-CCSD was built from, "
                "not correlated natural orbitals."
            ),
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

        n_closed = (_n_electrons(molecule) - params["active_electrons"]) // 2
        dominant = _dominant_transitions_casscf_orca(block.group(1), n_states, n_closed)

        return {
            "casscf_energy_hartree": energies_hartree[0] if n_states == 1 else None,
            "state_energies_hartree": energies_hartree,
            "excitation_energies_eV": excitation_ev,
            "oscillator_strengths": osc,
            "dominant_transitions": dominant,
            "active_electrons": params.get("active_electrons"),
            "active_orbitals": params.get("active_orbitals"),
            "n_states": n_states,
            "orbital_table": _orbital_table(output),
            "orbital_table_note": (
                "Natural orbitals with active-space occupation numbers (not integer HF-style occupancies) -- "
                "core orbitals show occ=2, active orbitals show their natural-orbital occupation, virtuals show occ=0."
            ),
        }

    summary = _safe_parse(build_summary, output, job_dir, "casscf")
    return {"summary": summary, "artifacts": {"raw_output": os.path.join(job_dir, "output.out")}}


def _resolve_orbital_indices(spec, homo_idx: int, n_mo: int) -> dict[str, int]:
    """0-based orbital indices from a HOMO/LUMO/HOMO-k/LUMO+k/1-based-int
    spec -- same convention as pyscf_runner._resolve_orbital_indices,
    duplicated here rather than imported since each engine runner is
    otherwise self-contained (see the "each engine's runner + worker pair
    follows the same shape" pattern the other runner modules already
    follow)."""
    if isinstance(spec, str):
        spec = [spec]
    out: dict[str, int] = {}
    for item in spec:
        item_str = str(item).strip().upper()
        if item_str == "HOMO":
            out["HOMO"] = homo_idx
        elif item_str == "LUMO":
            out["LUMO"] = homo_idx + 1
        elif item_str.startswith("HOMO-"):
            out[item_str] = homo_idx - int(item_str.split("-")[1])
        elif item_str.startswith("LUMO+"):
            out[item_str] = homo_idx + 1 + int(item_str.split("+")[1])
        else:
            idx = int(item_str) - 1  # user gives 1-based
            out[str(idx + 1)] = idx
    for label, idx in out.items():
        if idx < 0 or idx >= n_mo:
            raise ValueError(f"orbital '{label}' (index {idx + 1}) is out of range for {n_mo} molecular orbitals")
    return out


def _orbital_table(output: str) -> list[dict]:
    """Same {index, spin, energy_eV, occupancy} shape as
    pyscf_runner.run_mo_visualization's orbital_table and
    molden.orbital_table() -- lets OrbitalTable.tsx render any engine's
    mo_visualization job identically. ORCA's "ORBITAL ENERGIES" table
    already carries everything needed; no molden round-trip required."""
    return [
        {"index": i + 1, "spin": None, "energy_eV": e, "occupancy": occ}
        for i, (occ, e) in enumerate(_orbital_energy_rows(output))
    ]


def render_orbital_cube(job_dir: str, orbital_index_0based: int, ngrid: int = 80) -> str:
    """Renders one MO to a cube file directly from ORCA's own input.gbw
    via orca_plot's interactive stdin interface -- NOT via a molden
    export + pyscf.tools.molden/cubegen round-trip.

    That alternative was tried first and rejected after real verification:
    a molden file exported from this same ORCA install (via orca_2mkl
    input -molden) parses without error in pyscf.tools.molden.load() --
    AO self-overlaps and the target MO's self-overlap all come out exactly
    1.0, so a naive "is it normalized" check passes -- but evaluating both
    the native PySCF basis and the ORCA-molden-parsed basis at the same
    off-axis points showed each AO column scaled by a different,
    shell-dependent constant (~0.35x for the O 1s-type shell, ~1.1x for
    the 2s-type, ~0.5-0.6x for the 2p-type) rather than a uniform +-1 (a
    sign/ordering-only difference would show ratios of exactly +-1, and a
    real radial-shape difference wouldn't show a single constant ratio per
    shell at all). A per-shell constant ratio is consistent with a
    contraction-coefficient normalization mismatch between the two
    programs' molden conventions -- each AO individually still passes a
    unit-norm check (that's why self-overlap = 1.0 above), but an MO built
    as a linear combination across shells with mismatched relative
    weights comes out wrong regardless. BAGEL's own molden export (see
    bagel_runner.py) was point-sampled the same way and came back with
    per-column ratios of exactly 1.0, confirming this is an ORCA/orca_2mkl
    export quirk, not a bug in the point-sampling method or in
    pyscf.tools.molden itself. orca_plot instead reads ORCA's own converged orbitals straight
    from the .gbw file it wrote, and its cubes were cross-checked
    point-by-point against PySCF's own evaluation of the same water/HF/
    STO-3G HOMO to within a few percent (attributable to the cube's own
    finite grid spacing, not a real discrepancy).

    orbital_index_0based matches ORCA's own numbering -- the same
    convention _dominant_transitions_orca's contribution-line indices and
    _orbital_table's rows already use, so callers never need a second
    0-based/1-based mapping."""
    commands = "\n".join(["2", str(orbital_index_0based), "4", str(ngrid), "11", "12", ""])
    proc = subprocess.run(
        [ORCA_PLOT_BIN, "input.gbw", "-i"], input=commands,
        cwd=job_dir, capture_output=True, text=True, timeout=300,
    )
    # orca_plot names its own output after the raw index (e.g. "input.mo4a.cube");
    # negative cube-file atom counts (its own convention for an
    # orbital/MO cube, signalling one extra header line before the data)
    # are handled by the frontend's cube reader, not here -- this function
    # only needs the path.
    cube_path = os.path.join(job_dir, f"input.mo{orbital_index_0based}a.cube")
    if not os.path.exists(cube_path):
        raise RuntimeError(
            f"orca_plot did not produce a cube for orbital {orbital_index_0based}. "
            f"stdout:\n{proc.stdout[-2000:]}\nstderr:\n{proc.stderr[-1000:]}"
        )
    return cube_path


def run_mo_visualization(molecule: dict, params: dict) -> dict:
    job_dir = params["_job_dir"]
    text = _effective_input_text("mo_visualization", molecule, params)
    output = _write_and_run(job_dir, text)

    rows = _orbital_energy_rows(output)
    if not rows:
        raise RuntimeError("could not find an 'ORBITAL ENERGIES' table in the output")
    occupied_idx = [i for i, (occ, _e) in enumerate(rows) if occ > 0]
    if not occupied_idx:
        raise RuntimeError("no occupied orbitals found in the 'ORBITAL ENERGIES' table")
    homo_idx = max(occupied_idx)
    indices = _resolve_orbital_indices(params["orbital_indices"], homo_idx, len(rows))

    def build_summary():
        ngrid = params.get("cube_grid_points", 80)
        cube_paths = {}
        for label, idx in indices.items():
            raw_cube = render_orbital_cube(job_dir, idx, ngrid)
            final_path = os.path.join(job_dir, f"mo_{label}.cube")
            os.replace(raw_cube, final_path)
            cube_paths[label] = final_path
        return {
            "homo_index_1based": homo_idx + 1,
            "orbitals_rendered": {label: idx + 1 for label, idx in indices.items()},
            "mo_energies_eV": {label: rows[idx][1] for label, idx in indices.items()},
            "orbital_table": _orbital_table(output),
        }, cube_paths

    summary, cube_paths = _safe_parse(build_summary, output, job_dir, "mo_visualization")
    return {
        "summary": summary,
        "artifacts": {"cubes": cube_paths, "raw_output": os.path.join(job_dir, "output.out")},
    }


_ORBITAL_ROW_RE = re.compile(r"^\s*\d+\s+([\d.]+)\s+(-?[\d.]+)\s+(-?[\d.]+)\s*$")


def _orbital_energy_rows(output: str) -> list[tuple[float, float]]:
    """(occ, E_eV) for every orbital, in ORCA's own 0-based orbital order
    -- shared by _homo_lumo_gap and run_mo_visualization's orbital table,
    both of which need the same "ORBITAL ENERGIES" block.

    Scans row-by-row (rather than capturing everything up to the next
    blank line in one regex) because that block isn't reliably followed
    by a blank line -- with !LargePrint (needed to defeat the default
    10-virtual-orbital truncation, see build_input_text's mo_visualization
    branch), a "MOLECULAR ORBITALS (RHF, ROHF)" coefficient dump follows
    immediately, sometimes with a truncation notice line ("*Only the
    first N virtual orbitals were printed.") in between -- both of which
    a row-shape check (exactly "index occ E(Eh) E(eV)") naturally skips
    without needing to special-case either."""
    m = re.search(r"ORBITAL ENERGIES\n-+\n\n\s*NO\s+OCC\s+E\(Eh\)\s+E\(eV\)\s*\n", output)
    if not m:
        return []
    rows = []
    for line in output[m.end():].splitlines():
        row = _ORBITAL_ROW_RE.match(line)
        if row is None:
            if rows:
                break
            continue
        rows.append((float(row.group(1)), float(row.group(3))))  # (occ, E_eV)
    return rows


def _homo_lumo_gap(output: str) -> float | None:
    rows = _orbital_energy_rows(output)
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
