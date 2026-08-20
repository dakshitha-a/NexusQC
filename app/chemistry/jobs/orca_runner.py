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
from pathlib import Path

from app.chemistry.jobs.ci_transitions import format_dominant, leading_single_excitations
from app.chemistry.jobs.vibrations import summarize_frequencies
from app.config import (
    CASSCF_CONV_TOL_ENERGY, CASSCF_CONV_TOL_OPT_FREQ, CASSCF_MAX_CYCLE_MACRO, ORCA_BIN, ORCA_PLOT_BIN, N_CORES,
)

_FINAL_ENERGY = re.compile(r"FINAL SINGLE POINT ENERGY\s+(-?\d+\.\d+)")
# One "E diff. (CI) <value> <tolerance> <YES/NO>" convergence-table row per
# geometry cycle of a '! CI-OPT' run -- confirmed live (water/PBE0/STO-3G),
# where the value drove from -0.406 Ha toward 0 across dozens of cycles.
_CI_ENERGY_DIFF = re.compile(r"E diff\.\s*\(CI\)\s+(-?\d+\.\d+)")
_CARTESIAN_BLOCK = re.compile(
    r"CARTESIAN COORDINATES \(ANGSTROEM\)\n-+\n((?:\s*[A-Za-z]+\s+-?\d+\.\d+\s+-?\d+\.\d+\s+-?\d+\.\d+\n)+)"
)
_FREQ_LINE = re.compile(r"^\s*\d+:\s+(-?\d+\.\d+)\s+cm\*\*-1", re.MULTILINE)
# NORMAL MODES prints the full 3N x 3N mass-deweighted Cartesian-
# displacement matrix (rows = the 3N Cartesian components in atom-major
# order -- atom0 x,y,z, then atom1 x,y,z, ... -- columns = mode index, same
# order as _FREQ_LINE's 0-based indices) in blocks of up to 6 mode-columns
# each; verified against a real ORCA 6.1.1 water/HF/STO-3G run that there is
# NO blank line between consecutive blocks (only between the last block and
# the following IR SPECTRUM section), so blocks are detected structurally
# (a bare row of integer column indices) rather than by counting a fixed
# 6 modes/block or splitting on blank lines. The section's own header text
# ("weighted by the diagonal matrix M(i,i)=1/sqrt(m[i])... Thus, these
# vectors are normalized but *not* orthogonal") confirms these are already
# real-space Cartesian displacements (the 1/sqrt(mass) factor undoes the
# Hessian's own mass-weighting), i.e. the same physical quantity as
# pyscf_runner.run_frequency's normal_modes -- not the mass-weighted
# eigenvectors themselves.
_NORMAL_MODES_SECTION = re.compile(r"NORMAL MODES\s*\n-+\s*\n(.*?)\n-+\s*\nIR SPECTRUM", re.DOTALL)
# IR SPECTRUM only lists genuine vibrations (never the 5-6 near-zero
# translational/rotational modes NORMAL MODES still prints columns for), so
# _ir_intensities_orca below fills those un-listed indices with 0.0 rather
# than leaving gaps -- verified against the same real run: modes 0-5 (all
# 0.00 cm**-1) are absent from this table entirely, only modes 6-8 appear.
_IR_SPECTRUM_SECTION = re.compile(r"IR SPECTRUM\s*\n-+\s*\n(.*?)\n\* The epsilon", re.DOTALL)
_IR_SPECTRUM_ROW = re.compile(r"^\s*(\d+):\s+-?\d+\.\d+\s+-?\d+\.\d+\s+(-?\d+\.\d+)\s+", re.MULTILINE)
_MATRIX_BLOCK_HEADER = re.compile(r"^\s*(?:\d+\s+)*\d+\s*$")
_MATRIX_BLOCK_ROW = re.compile(r"^\s*(\d+)\s+((?:-?\d+\.\d+\s*)+)$")
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
# NEB-TS's final "PATH SUMMARY FOR NEB-TS" table (5 numeric columns, one
# row per numbered path image plus a distinguished "TS" row near the
# climbing image) -- and the plainer "PATH SUMMARY" table NEB/CI-NEB
# itself prints on its own convergence (6 columns incl. Dist.(Ang.), no TS
# row), used as a fallback when the TS-refinement step never reached its
# own convergence message. Both verified against a real ORCA 6.1.1
# HF/STO-3G NEB-TS run on this machine (see CLAUDE.md) -- row shape example:
#   0     -55.45449     0.00       0.01796   0.00956
#   3     -55.43767    10.56       0.00053   0.00022 <= CI
#  TS     -55.43767    10.56       0.00022   0.00009 <= TS
_NEB_TS_TABLE_HEADER = re.compile(r"Image\s+E\(Eh\)\s+dE\(kcal/mol\)\s+max\(\|Fp\|\)\s+RMS\(Fp\)\s*\n")
_NEB_PLAIN_TABLE_HEADER = re.compile(
    r"Image\s+Dist\.\(Ang\.\)\s+E\(Eh\)\s+dE\(kcal/mol\)\s+max\(\|Fp\|\)\s+RMS\(Fp\)\s*\n"
)
_NEB_TS_ROW = re.compile(
    r"^\s*(\d+|TS)\s+(-?\d+\.\d+)\s+(-?\d+\.\d+)\s+(-?\d+\.\d+)\s+(-?\d+\.\d+)\s*(?:<=\s*(\S+))?\s*$"
)
_NEB_PLAIN_ROW = re.compile(
    r"^\s*(\d+)\s+(-?\d+\.\d+)\s+(-?\d+\.\d+)\s+(-?\d+\.\d+)\s+(-?\d+\.\d+)\s+(-?\d+\.\d+)\s*(?:<=\s*(\S+))?\s*$"
)
# The .engrad file's "# The current total energy in Eh"/"# The current
# gradient in Eh/bohr" sections -- verified live against a real HF/STO-3G
# EnGrad run and a PBE0+%tddft IROOT 1 excited-state EnGrad run (the latter
# confirms .engrad carries the EXCITED-state gradient, not the ground
# state, when a target IROOT is requested -- input.engrad's own energy
# field matched the excited-state total exactly in both cases). Reading
# this structured file is simpler and more robust than regexing the
# "CARTESIAN GRADIENT" stdout block, which this app does not otherwise
# parse.
_ENGRAD_ENERGY = re.compile(r"total energy in Eh\s*\n#\n\s*([-\d.]+)")
_ENGRAD_GRADIENT = re.compile(r"current gradient in Eh/bohr\s*\n#\n(.*?)\n#\n", re.DOTALL)
# "CARTESIAN NON-ADIABATIC COUPLINGS" block, e.g.:
#    1   O   :    0.610677834   -0.055169051    0.027433579
# verified live against a real PBE0/STO-3G %TDDFT NACME TRUE run (a
# C1-distorted geometry, so the coupling is nonzero) -- same per-atom row
# shape as "CARTESIAN GRADIENT", but ORCA does not also write it to a
# structured file, so it is regex-parsed from stdout.
_NAC_BLOCK = re.compile(
    r"CARTESIAN NON-ADIABATIC COUPLINGS\s*\n(?:.*\n)*?-+\s*\n\s*\n((?:\s*\d+\s+[A-Za-z]+\s*:.*\n)+)"
)
_NAC_ROW = re.compile(r"^\s*\d+\s+[A-Za-z]+\s*:\s*(-?\d+\.\d+)\s+(-?\d+\.\d+)\s+(-?\d+\.\d+)\s*$", re.MULTILINE)
_NAC_NORM = re.compile(r"Norm of the NACs\s*\.\.\.\s*(-?\d+\.\d+)")


def _resolve_basis_directive(params: dict, molecule: dict) -> tuple[str, str]:
    """Returns (basis_token, basis_block). Normally basis_token is
    params["basis"] unchanged and basis_block is "". For a "bse:<name>"
    sentinel, basis_token is "" (verified live: a real ORCA 6.1.1 run
    accepts a "!" line with the basis keyword omitted entirely, as long as
    a %basis NewGTO...end block supplies it -- FINAL SINGLE POINT ENERGY
    and ORCA TERMINATED NORMALLY both came back clean on a real HF/water
    run built exactly this way) and basis_block is the translated %basis
    text from bse_basis.orca_basis_block."""
    from app.chemistry.jobs.bse_basis import is_bse_ref, bse_name, orca_basis_block

    basis = params["basis"]
    if is_bse_ref(basis):
        return "", orca_basis_block(bse_name(basis), molecule["symbols"])
    return basis, ""


def _bang_line(*keywords: str) -> str:
    """Joins '!' with non-empty keyword tokens -- shared by every '!' line
    builder so a blank basis_token (BSE-resolved, see
    _resolve_basis_directive above) never leaves a stray double space."""
    return "! " + " ".join(k for k in keywords if k)


def _pal_block(basis_block: str) -> list[str]:
    """The '%pal nprocs N end' line plus a blank line every build_input_text
    branch already emits, now also splicing in a translated '%basis...end'
    block (if any) right after it -- the one place a BSE-resolved basis is
    injected per branch."""
    lines = [f"%pal nprocs {N_CORES} end", ""]
    if basis_block:
        lines += [basis_block, ""]
    return lines


def _method_line(params: dict, basis_token: str | None = None) -> str:
    method = params["method"].lower()
    basis = params["basis"] if basis_token is None else basis_token
    if method == "hf":
        keyword = "HF"
    elif method == "dft":
        functional = params.get("functional")
        if not functional:
            raise ValueError("DFT requires a 'functional' parameter, e.g. 'b3lyp'")
        keyword = functional.upper()
    else:
        raise ValueError(f"Unsupported method '{method}' for ORCA (use 'hf' or 'dft')")
    return _bang_line(keyword, basis, "TightSCF")


def _geometry_block(molecule: dict, params: dict) -> str:
    lines = [f"* xyz {molecule['charge']} {molecule['multiplicity']}"]
    for sym, (x, y, z) in zip(molecule["symbols"], molecule["coords"]):
        lines.append(f"{sym:2s} {x: .8f} {y: .8f} {z: .8f}")
    lines.append("*")
    return "\n".join(lines)


def _tddft_block(params: dict) -> str:
    n_states = params["n_states"]
    return "\n".join([
        "%tddft", f"  nroots {n_states}", f"  tda {'true' if params.get('use_tda', False) else 'false'}", "end",
    ])


def _mdci_eom_block(params: dict) -> str:
    n_states = params.get("n_states", 1)
    return "\n".join(["%mdci", f"  nroots {n_states}", "end"])


def _casscf_block(molecule: dict, params: dict, etol: float) -> str:
    """etol is the explicit CASSCF energy-convergence policy this app
    applies everywhere (app/config.py's CASSCF_CONV_TOL_ENERGY for a plain
    energy job, CASSCF_CONV_TOL_OPT_FREQ for geometry_optimization/
    frequency) -- overriding ORCA's own default (ETol 1e-8) explicitly
    rather than leaving it engine-default. GTol is left at ORCA's own
    default (not part of this app's convergence policy). MaxIter is always
    CASSCF_MAX_CYCLE_MACRO (200), also overriding ORCA's own default of 75."""
    lines = [
        "%casscf",
        f"  nel {params['active_electrons']}",
        f"  norb {params['active_orbitals']}",
        f"  nroots {params.get('n_states', 1)}",
        f"  mult {molecule['multiplicity']}",
        f"  ETol {etol}",
        f"  MaxIter {CASSCF_MAX_CYCLE_MACRO}",
    ]
    if params.get("want_oscillator_strengths"):
        lines.append("  DoDipoleLength true")
    lines.append("end")
    return "\n".join(lines)


_ORCA_CONSTRAINT_KEY = {"bond": "B", "angle": "A", "dihedral": "D"}


def _constraints_lines(params: dict) -> list[str]:
    """0-based atom indices inside the '{ ... }' constraint entries --
    confirmed live (scripts/spikes/spike_orca_caps.py's own '{B 0 1 0.98 C}'
    on water) and against the real ORCA manual (data/scraped/orca/
    .../optimizations.html.txt: '{ B N1 N2 value C }'/'{ A N1 N2 N3 value C
    }'/'{ D N1 N2 N3 N4 value C }'), where this app's own `constraints`
    ParamSpec is 1-based -- the '-1' below is the one conversion point.
    Bond values are Angstrom, angle/dihedral degrees, both the units the
    manual's own worked example uses and this app's ParamSpec already
    documents."""
    lines = ["  Constraints"]
    for c in params["constraints"]:
        key = _ORCA_CONSTRAINT_KEY[c["type"]]
        atoms = " ".join(str(a - 1) for a in c["atoms"])
        lines.append(f"    {{ {key} {atoms} {c['value']} C }}")
    lines.append("  end")
    return lines


def _neb_block(params: dict) -> str:
    """Product is always written to 'product.xyz' in the job's own
    directory (see run_neb_ts, which writes that file from
    params['_end_molecule'] right before invoking ORCA) -- the preview
    text just references that fixed filename, since the actual endpoint
    geometry doesn't need to exist on disk yet for the .inp text itself to
    be generated/shown."""
    lines = ["%neb", '  Product "product.xyz"', f"  NImages {params.get('n_images', 6)}"]
    if params.get("preopt"):
        lines.append("  PreOpt true")
    lines.append("end")
    return "\n".join(lines)


def _nac_block(params: dict) -> str:
    """%TDDFT NROOTS/IROOT/NACME TRUE/ETF TRUE -- verified against a real
    PBE0/STO-3G run (see this module's own _NAC_BLOCK/_NAC_NORM comments).
    ORCA's CIS/TDDFT NAC module computes only the ground-to-excited
    coupling for one IROOT (registry2/tasks.py's _warn_nac_pairing), so
    only single-reference (hf/dft) methods ever reach this -- casscf/
    caspt2 NAC is not available on ORCA at all (capabilities.py: orca/
    casscf nac=False, a documented gap). app/agent/tools.py's
    _build_spec_or_error already refused any pair that doesn't include the
    ground state (index 1) before a spec reaches here, so exactly one of
    the pair's two entries is not 1."""
    pair = params["state_pairs"][0]
    iroot = next(int(s) for s in pair if int(s) != 1) - 1
    n_states = max(params.get("n_states") or 0, iroot)
    return "\n".join(["%TDDFT", f"  NROOTS {n_states}", f"  IROOT {iroot}", "  NACME TRUE", "  ETF TRUE", "end"])


def _neb_tddft_block(params: dict) -> str:
    """Requesting the NEB search on an excited-state PES (params
    ['target_state']) -- verified against a real ORCA run/the manual that
    this is the same %tddft block a plain tddft job_type would use, with
    IRoot picking which state's gradient the whole NEB path is actually
    optimized against, not just a post-hoc energy readout."""
    target_state = params["target_state"]
    n_states = max(params.get("n_states") or 0, target_state)
    return "\n".join(["%tddft", f"  NRoots {n_states}", f"  IRoot {target_state}", "end"])


def build_input_text(job_type: str, molecule: dict, params: dict) -> str:
    """Builds the exact .inp text a job would run with -- shared by the
    approval-preview path and the actual run_* functions below, so the
    preview the user approves can never drift from what actually runs."""
    if job_type == "opt_freq":
        # run_opt_freq's own input IS genuinely the geometry_optimization
        # input -- that's the stage that actually runs first, on the
        # exact molecule/params given here; the frequency stage that
        # follows automatically runs on whatever geometry that produces,
        # which isn't known yet at preview time (same "preview is what
        # actually runs first" reasoning pes_scan's own image-0 preview
        # already uses).
        job_type = "geometry_optimization"
    basis_token, basis_block = _resolve_basis_directive(params, molecule)
    if job_type == "single_point":
        # LargePrint (same reasoning as mo_visualization below) so the full
        # ORBITAL ENERGIES table -- not just the first 10 virtuals -- is
        # always available for lazy orbital visualization, without the
        # user having to know in advance they'll want it.
        return "\n".join([
            _method_line(params, basis_token) + " LargePrint", "", *_pal_block(basis_block),
            _geometry_block(molecule, params),
        ])
    if job_type == "geometry_optimization":
        # %geom MaxIter, not %casscf's own MaxIter (that's the CASSCF
        # wavefunction's macro-iteration cap, set separately inside
        # _casscf_block below when method='casscf') -- this is the outer
        # geometry-step cap. Previously absent entirely on ORCA (confirmed
        # by inspection -- max_steps only ever reached pyscf's optimizer),
        # so ORCA optimizations silently ran under ORCA's own internal
        # default cycle count regardless of max_steps. A live water/PBE0/
        # STO-3G CI-OPT run needed noticeably more cycles than a plain
        # minimization to drive E diff.(CI) to zero (see below) -- the
        # existing max_steps=200 default is generous enough that this
        # needed no separate cap, but it is why one is worth keeping.
        geom_lines = ["%geom", f"  MaxIter {params.get('max_steps', 200)}"]
        if params.get("constraints"):
            geom_lines += _constraints_lines(params)
        geom_lines.append("end")
        geom_block = "\n".join(geom_lines)
        if params.get("method") == "caspt2":
            raise ValueError(
                "CASPT2 geometry optimization is BAGEL-only (ORCA has no CASPT2 implementation at all) "
                "-- use engine='bagel'."
            )
        if params.get("method") == "casscf":
            return "\n".join([
                _bang_line(basis_token, "TightSCF", "LargePrint", "Opt"), "", *_pal_block(basis_block),
                _casscf_block(molecule, params, CASSCF_CONV_TOL_OPT_FREQ), "", geom_block, "",
                _geometry_block(molecule, params),
            ])
        # Conical-intersection optimization needs ORCA's dedicated '!
        # CI-OPT' keyword, NOT '! Opt' -- verified live on this host: '!
        # Opt' with the exact same %TDDFT/%CONICAL blocks present ran in
        # 0.013s of "Geometry relaxation" (i.e. did nothing -- the blocks
        # were silently inert), while '! CI-OPT' genuinely drove E diff.
        # (CI) from -0.406 Ha down through zero over dozens of cycles. The
        # Phase 0 spike's "%CONICAL METHOD UBP accepted and terminated
        # normally" verdict used '! Opt' and is the same "ran without
        # error" evidence class this app's own docs call worthless for
        # BAGEL's fix_atom -- corrected here rather than trusted.
        is_ci_opt = params.get("optimization_type") == "conical_intersection"
        target_state = params.get("target_state")
        lines = [
            _method_line(params, basis_token) + (" CI-OPT" if is_ci_opt else " Opt"), "",
            *_pal_block(basis_block),
        ]
        if is_ci_opt:
            iroot = params["target_state_2"]
            n_states = max(params.get("n_states") or 0, iroot)
            lines += ["\n".join(["%TDDFT", f"  NROOTS {n_states}", f"  IROOT {iroot}", "end"]), ""]
            lines += ["\n".join(["%CONICAL", "  METHOD UBP", "end"]), ""]
        elif target_state:
            n_states = max(params.get("n_states") or 0, target_state)
            lines += ["\n".join(["%tddft", f"  NRoots {n_states}", f"  IRoot {target_state}", "end"]), ""]
        lines += [geom_block, "", _geometry_block(molecule, params)]
        return "\n".join(lines)
    if job_type == "frequency":
        if params.get("method") == "caspt2":
            raise ValueError(
                "CASPT2 frequency calculations are BAGEL-only (ORCA has no CASPT2 implementation at all) "
                "-- use engine='bagel'."
            )
        if params.get("method") == "casscf":
            # CASSCF has no analytic Hessian in ORCA either -- the real
            # ORCA manual states directly that CASSCF "may be used for
            # geometry optimizations and numerical frequency
            # calculations" (analytic gradient, numerical Hessian only),
            # so NumFreq here, not Freq.
            return "\n".join([
                _bang_line(basis_token, "TightSCF", "LargePrint", "NumFreq"), "", *_pal_block(basis_block),
                _casscf_block(molecule, params, CASSCF_CONV_TOL_OPT_FREQ), "", _geometry_block(molecule, params),
            ])
        return "\n".join([
            _method_line(params, basis_token) + " Freq", "", *_pal_block(basis_block),
            _geometry_block(molecule, params),
        ])
    if job_type == "tddft":
        # _method_line already picks "HF" or the DFT functional from
        # params["method"]/["functional"] -- an HF reference here makes
        # this CIS (tda true) or TD-HF/RPA (tda false), not DFT-based
        # TDA/TDDFT; ORCA's TD-DFT/CIS module auto-selects based on the
        # reference wavefunction (confirmed against a real ORCA run).
        return "\n".join([
            _method_line(params, basis_token) + " LargePrint", "", *_pal_block(basis_block),
            _tddft_block(params), "", _geometry_block(molecule, params),
        ])
    if job_type == "eom_ccsd":
        # EOM-CCSD is inherently post-HF -- no method/functional choice.
        return "\n".join([
            _bang_line("HF", "EOM-CCSD", basis_token, "TightSCF", "LargePrint"), "", *_pal_block(basis_block),
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
            _bang_line(basis_token, "TightSCF", "LargePrint"), "", *_pal_block(basis_block),
            _casscf_block(molecule, params, CASSCF_CONV_TOL_ENERGY), "", _geometry_block(molecule, params),
        ])
    if job_type == "gradient":
        method = params.get("method")
        if method == "mp2":
            # MP2 has no keyword in _method_line (hf/dft only) -- ORCA's own
            # bang-line keyword for it, no functional involved.
            return "\n".join([
                _bang_line("MP2", basis_token, "TightSCF", "EnGrad"), "", *_pal_block(basis_block),
                _geometry_block(molecule, params),
            ])
        if method == "casscf":
            return "\n".join([
                _bang_line(basis_token, "TightSCF", "EnGrad", "LargePrint"), "", *_pal_block(basis_block),
                _casscf_block(molecule, params, CASSCF_CONV_TOL_ENERGY), "", _geometry_block(molecule, params),
            ])
        # hf/dft, ground or excited state. The B88/LibXC caveat
        # (registry2/params.py's functional ParamSpec) is enforced as a
        # refusal in app/agent/tools.py's _build_spec_or_error before a spec
        # carrying target_state + functional in (b3lyp, blyp) ever reaches
        # here -- see docs/PARSER_GAPS.md for why that combination has no
        # working rewrite in this app.
        lines = [_method_line(params, basis_token) + " EnGrad LargePrint", "", *_pal_block(basis_block)]
        target_state = params.get("target_state")
        if target_state:
            n_states = max(params.get("n_states") or 0, target_state)
            lines += ["\n".join(["%tddft", f"  NRoots {n_states}", f"  IRoot {target_state}", "end"]), ""]
        lines += [_geometry_block(molecule, params)]
        return "\n".join(lines)
    if job_type == "nac":
        # Only hf/dft ever reaches here -- see _nac_block's own docstring.
        return "\n".join([
            _method_line(params, basis_token) + " LargePrint", "", *_pal_block(basis_block),
            _nac_block(params), "", _geometry_block(molecule, params),
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
            f"{_method_line(params, basis_token)} LargePrint", "", *_pal_block(basis_block),
            _geometry_block(molecule, params),
        ])
    if job_type == "neb_ts":
        # LargePrint gives a real (post-TS-optimization) ORBITAL ENERGIES
        # table for the reference-orbital viewer -- see _orbital_energy_rows'
        # last=True handling, which picks the FINAL such block rather than
        # an early NEB image's own SCF (confirmed two blocks appear in a
        # real run's output).
        lines = [
            f"{_method_line(params, basis_token)} NEB-TS LargePrint", "", *_pal_block(basis_block),
            _neb_block(params),
        ]
        if params.get("target_state"):
            lines += ["", _neb_tddft_block(params)]
        lines += ["", _geometry_block(molecule, params)]
        return "\n".join(lines)
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


def _write_and_run_generic(job_dir: str, input_text: str) -> str:
    """Same as _write_and_run, but with no "FINAL SINGLE POINT ENERGY"
    content check -- that marker is specific to the SCF-based job_types
    this app otherwise knows about, and run_custom's whole point is
    running a calculation type this app has no job_type-specific
    expectations for at all (e.g. an NEB/IRC run, whose stdout doesn't
    necessarily look like a single-point job's). "ORCA TERMINATED
    NORMALLY" is calculation-type-agnostic -- confirmed present in every
    genuinely successful job's output.out under data/jobs/ on this
    machine (30 of 32; the other 2 are real failures, one aborted SCF and
    one malformed input, neither printing it either), so it's the best
    generic success signal ORCA gives across arbitrary calculation types."""
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
    if proc.returncode != 0 or "ORCA TERMINATED NORMALLY" not in output:
        raise RuntimeError(f"ORCA exited with code {proc.returncode}. Last 3000 chars of output:\n{output[-3000:]}")
    return output


def run_custom(molecule: dict, params: dict) -> dict:
    """Runs an arbitrary, agent-composed ORCA input verbatim -- no
    structured-parameter input building (there is no job_type to build
    from) and no output parsing (there is no job_type-specific parser to
    parse it with). The last part of the raw output is embedded directly
    in the summary so check_job_status has something to answer from
    without a separate tool; the full raw input/output are also available
    to the human user as job artifacts (see server/routes/jobs.py's
    raw_input route and the generic artifacts route) -- the approval card
    and JobDetailDrawer degrade to "geometry + raw input/output only" for
    this job_type, same as any other job whose summary happens to come
    back minimal (see CLAUDE.md)."""
    job_dir = params["_job_dir"]
    text = params.get("_raw_input")
    if not text:
        raise RuntimeError("custom ORCA job has no input text to run")
    output = _write_and_run_generic(job_dir, text)
    return {
        "summary": {
            "note": (
                "Raw custom ORCA input -- no structured result parsing was attempted for this job type. "
                "The tail of the raw output below is what's available programmatically; the full raw "
                "input/output are also available to the user as job artifacts in the UI."
            ),
            "raw_output_tail": output[-2000:],
        },
        "artifacts": {"raw_output": os.path.join(job_dir, "output.out")},
    }


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


def run_gradient(molecule: dict, params: dict) -> dict:
    """single_point/grad. Reads the gradient from the .engrad file ORCA
    writes alongside output.out (see _ENGRAD_ENERGY/_ENGRAD_GRADIENT's own
    comments) rather than regexing the CARTESIAN GRADIENT stdout block --
    verified live to carry the excited-state gradient, not the ground
    state, when target_state/IRoot is set."""
    job_dir = params["_job_dir"]
    text = _effective_input_text("gradient", molecule, params)
    output = _write_and_run(job_dir, text)

    def build_summary():
        engrad_path = os.path.join(job_dir, "input.engrad")
        with open(engrad_path) as f:
            engrad_text = f.read()
        energy = float(_ENGRAD_ENERGY.search(engrad_text).group(1))
        grad_values = [float(v) for v in _ENGRAD_GRADIENT.search(engrad_text).group(1).split()]
        gradient = [grad_values[i:i + 3] for i in range(0, len(grad_values), 3)]
        return {
            "gradient_hartree_per_bohr": gradient,
            "gradient_norm_hartree_per_bohr": sum(v * v for row in gradient for v in row) ** 0.5,
            "energy_hartree": energy,
            "method": params.get("method"),
            "functional": params.get("functional"),
            "basis": params.get("basis"),
            "target_state": params.get("target_state"),
            "orbital_table": _orbital_table(output),
        }

    summary = _safe_parse(build_summary, output, job_dir, "gradient")
    return {"summary": summary, "artifacts": {"raw_output": os.path.join(job_dir, "output.out")}}


def run_nac(molecule: dict, params: dict) -> dict:
    """single_point/nac. Only hf/dft reaches here (see _nac_block's own
    docstring) -- ORCA's %TDDFT NACME TRUE module, ground-to-excited only."""
    job_dir = params["_job_dir"]
    text = _effective_input_text("nac", molecule, params)
    output = _write_and_run(job_dir, text)

    def build_summary():
        block = _NAC_BLOCK.search(output)
        norm = _NAC_NORM.search(output)
        if block is None or norm is None:
            raise RuntimeError("could not find the 'CARTESIAN NON-ADIABATIC COUPLINGS' block/norm")
        nac = [[float(x), float(y), float(z)] for x, y, z in _NAC_ROW.findall(block.group(1))]
        pair = params["state_pairs"][0]
        return {
            "nac_hartree_per_bohr": nac,
            "nac_norm_hartree_per_bohr": float(norm.group(1)),
            "state_pair": [int(pair[0]), int(pair[1])],
            "method": params.get("method"),
            "functional": params.get("functional"),
            "basis": params.get("basis"),
            "orbital_table": _orbital_table(output),
        }

    summary = _safe_parse(build_summary, output, job_dir, "nac")
    return {"summary": summary, "artifacts": {"raw_output": os.path.join(job_dir, "output.out")}}


def run_geometry_optimization(molecule: dict, params: dict) -> dict:
    job_dir = params["_job_dir"]
    text = _effective_input_text("geometry_optimization", molecule, params)
    output = _write_and_run(job_dir, text)
    is_ci_opt = params.get("optimization_type") == "conical_intersection"
    if "HURRAY" not in output:
        # A conical-intersection search can genuinely need more cycles than
        # a plain minimization to drive E diff.(CI) to zero (see
        # build_input_text's own note) -- this app's own standing framing
        # is that a long-running job is expected, not a fault (CLAUDE.md),
        # so this is reported distinctly from an ordinary non-convergence
        # rather than folded into the same generic message.
        if is_ci_opt:
            raise RuntimeError(
                "ORCA conical-intersection optimization did not converge within max_steps -- the "
                "E diff.(CI) seam search can need substantially more cycles than a plain minimization; "
                "ask for a larger max_steps or a starting geometry closer to the expected crossing."
            )
        raise RuntimeError("ORCA geometry optimization did not converge (no HURRAY marker found)")

    def build_summary():
        # ORCA prints "FINAL SINGLE POINT ENERGY" once per optimization
        # cycle plus one more after the final single-point re-evaluation at
        # the converged geometry -- the same values geomeTRIC's per-step
        # callback captures for the PySCF path (both real-run-verified
        # against water/HF/STO-3G: monotonically decreasing to the last
        # entry, which matches final_energy_hartree exactly).
        energies = [float(e) for e in _FINAL_ENERGY.findall(output)]
        summary = {
            "final_energy_hartree": energies[-1],
            "converged": True,
            "optimized_molecule": _extract_final_geometry(output, molecule),
            "optimization_energies_hartree": energies,
        }
        if params.get("method") == "casscf":
            summary["active_electrons"] = params.get("active_electrons")
            summary["active_orbitals"] = params.get("active_orbitals")
            summary["n_states"] = params.get("n_states", 1)
            summary["orbital_table"] = _orbital_table(output)
            summary["orbital_table_note"] = (
                "Natural orbitals of the OPTIMIZED geometry's CASSCF wavefunction, with active-space "
                "occupation numbers (not integer HF-style occupancies)."
            )
        if is_ci_opt:
            summary["optimization_type"] = "conical_intersection"
            summary["target_state"] = params.get("target_state") or 0
            summary["target_state_2"] = params.get("target_state_2")
            diffs = [float(x) for x in _CI_ENERGY_DIFF.findall(output)]
            summary["ci_energy_diff_hartree"] = diffs[-1] if diffs else None
        elif params.get("target_state"):
            summary["target_state"] = params["target_state"]
        if params.get("constraints"):
            summary["constraints"] = params["constraints"]
        return summary

    summary = _safe_parse(build_summary, output, job_dir, "geometry_optimization")
    return {"summary": summary, "artifacts": {"raw_output": os.path.join(job_dir, "output.out")}}


def _parse_column_block_matrix(text: str, n_rows: int) -> dict[int, list[float]] | None:
    """Generic parser for ORCA/BAGEL's shared convention of printing a wide
    matrix in blocks of a handful of columns each, every block introduced
    by a bare header line of that block's 0-based column indices, followed
    (with any amount of intervening non-matching text -- explanatory
    paragraphs, other labelled rows, blank lines) by exactly n_rows data
    rows shaped 'row_idx val val ...'. Returns {row_idx: [col0, col1, ...]}
    with values ordered by increasing column index across blocks, or None
    if no header line is found at all."""
    lines = text.splitlines()
    matrix: dict[int, list[float]] = {}
    i = 0
    found_any = False
    while i < len(lines):
        if _MATRIX_BLOCK_HEADER.match(lines[i]) and lines[i].strip():
            found_any = True
            i += 1
            collected = 0
            while collected < n_rows and i < len(lines):
                m = _MATRIX_BLOCK_ROW.match(lines[i])
                if m is None:
                    if _MATRIX_BLOCK_HEADER.match(lines[i]) and lines[i].strip():
                        break  # next block started before this one finished -- malformed
                    i += 1
                    continue
                row_idx = int(m.group(1))
                matrix.setdefault(row_idx, []).extend(float(v) for v in m.group(2).split())
                i += 1
                collected += 1
            if collected < n_rows:
                return None
        else:
            i += 1
    return matrix if found_any else None


def _normal_modes_orca(output: str, n_atoms: int, n_modes: int) -> list[list[list[float]]] | None:
    """normal_modes[mode][atom] = [dx, dy, dz], same shape as
    pyscf_runner.run_frequency's normal_modes -- lets ModeAnimationViewer
    treat any engine's frequency job identically."""
    section = _NORMAL_MODES_SECTION.search(output)
    if not section:
        return None
    matrix = _parse_column_block_matrix(section.group(1), 3 * n_atoms)
    if matrix is None or len(matrix) != 3 * n_atoms or any(len(v) != n_modes for v in matrix.values()):
        return None
    return [
        [[matrix[3 * atom][mode], matrix[3 * atom + 1][mode], matrix[3 * atom + 2][mode]] for atom in range(n_atoms)]
        for mode in range(n_modes)
    ]


def _ir_intensities_orca(output: str, n_modes: int) -> list[float] | None:
    section = _IR_SPECTRUM_SECTION.search(output)
    if not section:
        return None
    ir = [0.0] * n_modes
    for idx_str, val_str in _IR_SPECTRUM_ROW.findall(section.group(1)):
        idx = int(idx_str)
        if 0 <= idx < n_modes:
            ir[idx] = float(val_str)
    return ir


def run_frequency(molecule: dict, params: dict) -> dict:
    job_dir = params["_job_dir"]
    text = _effective_input_text("frequency", molecule, params)
    output = _write_and_run(job_dir, text)

    def _grab(label: str) -> float | None:
        m = re.search(rf"{re.escape(label)}\s*\.*\s+(-?\d+\.\d+)\s*Eh", output)
        return float(m.group(1)) if m else None

    def build_summary():
        freqs = [float(x) for x in _FREQ_LINE.findall(output)]
        # F-026: one shared rule across all three engines -- see
        # app/chemistry/jobs/vibrations.py. This used to be a bare `f < 0`,
        # which counted every near-zero translational/rotational mode of a
        # converged minimum as a transition state.
        freq_summary = summarize_frequencies(freqs)
        # Normal-mode/IR-intensity parsing is a bonus on top of the core
        # frequency/thermochemistry result -- a malformed or unexpectedly
        # shaped NORMAL MODES/IR SPECTRUM section (e.g. after a hand-edited
        # input) degrades to None rather than failing the whole job, since
        # everything else above already parsed successfully.
        try:
            normal_modes = _normal_modes_orca(output, len(molecule["symbols"]), len(freqs))
        except Exception:
            normal_modes = None
        try:
            ir_intensities = _ir_intensities_orca(output, len(freqs))
        except Exception:
            ir_intensities = None
        reduced_mass_amu = None
        if normal_modes:
            try:
                from app.chemistry.jobs.vibrations import reduced_masses_from_normal_modes
                reduced_mass_amu = reduced_masses_from_normal_modes(normal_modes, molecule["symbols"])
            except Exception:
                reduced_mass_amu = None
        summary = {
            **freq_summary,
            "zero_point_energy_hartree": _grab("Zero point energy"),
            "enthalpy_hartree": _grab("Total Enthalpy"),
            "gibbs_free_energy_hartree": _grab("Final Gibbs free energy"),
            "electronic_energy_hartree": _grab("Electronic energy"),
            "normal_modes": normal_modes,
            "reduced_mass_amu": reduced_mass_amu,
            "ir_intensities_km_mol": ir_intensities,
        }
        if params.get("method") == "casscf":
            summary["active_electrons"] = params.get("active_electrons")
            summary["active_orbitals"] = params.get("active_orbitals")
            summary["n_states"] = params.get("n_states", 1)
            summary["orbital_table"] = _orbital_table(output)
            summary["orbital_table_note"] = (
                "Natural orbitals with active-space occupation numbers (not integer HF-style occupancies)."
            )
            summary["hessian_method_note"] = (
                "Numerical Hessian (ORCA's NumFreq) -- ORCA has no analytic CASSCF Hessian either."
            )
        return summary

    summary = _safe_parse(build_summary, output, job_dir, "frequency")
    return {"summary": summary, "artifacts": {"raw_output": os.path.join(job_dir, "output.out")}}


def run_opt_freq(molecule: dict, params: dict) -> dict:
    """Geometry optimization followed by a frequency calculation at the
    optimized geometry -- see pyscf_runner.run_opt_freq's docstring for the
    full "two sequential calls, not a fused single-process job" rationale
    (ORCA's own `! Opt Freq` combined keyword could in principle do both
    in one process, but that would need its own separately-verified output
    parsing -- deliberately not attempted here in favor of reusing the
    already-verified per-stage run_geometry_optimization/run_frequency
    exactly as they are). The optimization stage's own raw ORCA output is
    written to a nested "_opt_stage" subdirectory of the job's _job_dir so
    it isn't overwritten by the frequency stage's own output.out, and is
    kept in the result under "optimization_raw_output"."""
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
    use_tda = params.get("use_tda", False)
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


def _orbital_table(output: str, last: bool = False) -> list[dict]:
    """Same {index, spin, energy_eV, occupancy} shape as
    pyscf_runner.run_mo_visualization's orbital_table and
    molden.orbital_table() -- lets OrbitalTable.tsx render any engine's
    mo_visualization job identically. ORCA's "ORBITAL ENERGIES" table
    already carries everything needed; no molden round-trip required."""
    return [
        {"index": i + 1, "spin": None, "energy_eV": e, "occupancy": occ}
        for i, (occ, e) in enumerate(_orbital_energy_rows(output, last=last))
    ]


def render_orbital_cube(
    job_dir: str, orbital_index_0based: int, ngrid: int = 80, gbw_filename: str = "input.gbw",
) -> str:
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
    0-based/1-based mapping.

    gbw_filename defaults to "input.gbw" (the job's own converged
    wavefunction) but can name any other .gbw in job_dir -- used by
    neb_ts to render orbitals from a specific path image's own wavefunction
    (input_im{N}.gbw). orca_plot names its cube output after the GBW
    file's own stem, not always "input" -- verified directly (orca_plot
    input_im3.gbw -i produced input_im3.mo0a.cube, not input.mo0a.cube),
    so the expected cube path is derived from gbw_filename's stem rather
    than hardcoded."""
    stem = os.path.splitext(gbw_filename)[0]
    commands = "\n".join(["2", str(orbital_index_0based), "4", str(ngrid), "11", "12", ""])
    proc = subprocess.run(
        [ORCA_PLOT_BIN, gbw_filename, "-i"], input=commands,
        cwd=job_dir, capture_output=True, text=True, timeout=300,
    )
    # orca_plot names its own output after the raw index (e.g. "input.mo4a.cube");
    # negative cube-file atom counts (its own convention for an
    # orbital/MO cube, signalling one extra header line before the data)
    # are handled by the frontend's cube reader, not here -- this function
    # only needs the path.
    cube_path = os.path.join(job_dir, f"{stem}.mo{orbital_index_0based}a.cube")
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


def _orbital_energy_rows(output: str, last: bool = False) -> list[tuple[float, float]]:
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
    without needing to special-case either.

    `last=True` picks the FINAL such block in the output instead of the
    first -- needed for neb_ts, whose output prints one "ORBITAL ENERGIES"
    block per per-image SCF along the path plus a final one for the
    TS-optimized wavefunction (confirmed on a real run: two occurrences,
    the second matching the TS-refined structure written to input.gbw);
    every other job_type in this app only ever has one such block, so the
    default (first match) is unchanged for them."""
    header = r"ORBITAL ENERGIES\n-+\n\n\s*NO\s+OCC\s+E\(Eh\)\s+E\(eV\)\s*\n"
    matches = list(re.finditer(header, output))
    if not matches:
        return []
    m = matches[-1] if last else matches[0]
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


def _neb_path_summary(output: str) -> tuple[list[dict], bool]:
    """Rows from whichever PATH SUMMARY table is present, in ORCA's own
    print order (a TS row, when present, appears near the CI image, not
    necessarily first or last -- see _NEB_TS_TABLE_HEADER's docstring).
    Prefers the NEB-TS-specific table (has_ts=True, includes the refined
    TS row) but falls back to the plain NEB/CI-NEB-only table if the TS
    refinement step was never reached/never converged -- so a partially-
    successful run still yields a usable path instead of nothing. Uses the
    LAST occurrence of whichever header is found (mirrors
    _orbital_energy_rows' last=True reasoning: ORCA can print the plain
    table once on NEB/CI-NEB convergence and then the FOR NEB-TS table
    again afterward)."""
    for header_re, row_re, has_ts in (
        (_NEB_TS_TABLE_HEADER, _NEB_TS_ROW, True),
        (_NEB_PLAIN_TABLE_HEADER, _NEB_PLAIN_ROW, False),
    ):
        matches = list(header_re.finditer(output))
        if not matches:
            continue
        rows = []
        for line in output[matches[-1].end():].splitlines():
            m = row_re.match(line)
            if m is None:
                if rows:
                    break
                continue
            if has_ts:
                image, e_eh, de_kcal, max_fp, rms_fp, marker = m.groups()
            else:
                image, _dist, e_eh, de_kcal, max_fp, rms_fp, marker = m.groups()
            rows.append({
                "image": image, "energy_hartree": float(e_eh), "relative_kcal_mol": float(de_kcal),
                "max_force_eh_bohr": float(max_fp), "rms_force_eh_bohr": float(rms_fp), "marker": marker,
            })
        if rows:
            return rows, has_ts
    return [], False


def split_xyz_frames(text: str) -> list[str]:
    """Splits a multi-frame xmol-format xyz trajectory (no blank-line
    separator -- each frame's own atom-count line is the delimiter, same
    convention as app/chemistry/jobs/base.py's _write_path_xyz and
    frontend/src/molecule/xyz.ts's parseMultiFrameXyz) into a list of raw
    per-frame text blocks (including their own trailing newline), without
    parsing symbols/coordinates -- callers that only need to slice/
    reassemble frames (neb live-progress chunking) don't need a full
    structured parse."""
    lines = text.splitlines(keepends=True)
    frames: list[str] = []
    i = 0
    while i < len(lines):
        count_line = lines[i].strip()
        if not count_line:
            i += 1
            continue
        try:
            n = int(count_line)
        except ValueError:
            break
        if n <= 0 or i + 2 + n > len(lines):
            break
        frames.append("".join(lines[i : i + 2 + n]))
        i += 2 + n
    return frames


def _find_neb_ts_geometry(job_dir: str) -> str | None:
    """Best available "TS-like" structure, in descending order of how
    refined it is -- the NEB-TS-specific converged file (present once the
    TS-optimization step itself converges), falling back to the climbing-
    image/highest-energy-image files NEB/CI-NEB alone would have produced
    if the TS refinement step never got there."""
    for name in ("input_NEB-TS_converged.xyz", "input_NEB-CI_converged.xyz", "input_NEB-HEI_converged.xyz"):
        path = os.path.join(job_dir, name)
        if os.path.exists(path):
            return path
    return None


def run_neb_ts(molecule: dict, params: dict) -> dict:
    """Nudged Elastic Band transition-state search (ORCA's native
    !NEB-TS). Unlike pes_scan, this is a SINGLE ORCA job -- ORCA
    parallelizes the per-image energy/gradient evaluations itself via
    %pal, so there is no master/sub-job architecture here, just one
    subprocess run like single_point/casscf/etc.

    File-naming/behavior below was verified against real ORCA 6.1.1 runs
    on this machine (a tiny HF/STO-3G NEB-TS test), not the manual alone:
    input_im{N}.gbw (N = 0..n_images_total-1) is each path image's own
    converged wavefunction, in the same order as the PATH SUMMARY table's
    numbered rows; input.gbw ends up holding the FINAL calculation's own
    wavefunction, which for a converged NEB-TS run is the TS-optimized
    structure (confirmed: its mtime matches input_NEB-TS_converged.xyz's,
    both written well after every input_im*.gbw). input_MEP_trj.xyz is
    written exactly ONCE, when the NEB/CI-NEB part itself converges (its
    mtime did not change again once the subsequent TS-optimization step
    ran further) -- it is NOT continuously updated with the TS-refined
    geometry, despite its name suggesting "the current/final path";
    input_MEP_ALL_trj.xyz is the one file that genuinely grows every NEB
    iteration (confirmed: size increased between two polls of a still-
    running job), so that -- not input_MEP_trj.xyz -- is what a live
    "current iteration" viewer must read (see split_xyz_frames and
    server/routes/jobs.py's neb live-frames route).
    """
    job_dir = params["_job_dir"]
    product = params.get("_end_molecule")
    if not product:
        raise RuntimeError("neb_ts job has no product/end molecule (params['_end_molecule'])")
    product_path = os.path.join(job_dir, "product.xyz")
    with open(product_path, "w") as f:
        f.write(f"{len(product['symbols'])}\nproduct\n")
        for sym, (x, y, z) in zip(product["symbols"], product["coords"]):
            f.write(f"{sym:2s} {x: .8f} {y: .8f} {z: .8f}\n")

    text = _effective_input_text("neb_ts", molecule, params)
    output = _write_and_run_generic(job_dir, text)

    def build_summary():
        neb_converged = "THE NEB OPTIMIZATION HAS CONVERGED" in output
        ts_converged = "THE TS OPTIMIZATION HAS CONVERGED" in output
        path_rows, has_ts_row = _neb_path_summary(output)

        ts_energy = next((r["energy_hartree"] for r in path_rows if r["image"] == "TS"), None)

        artifacts: dict = {"raw_output": os.path.join(job_dir, "output.out")}

        mep_path = os.path.join(job_dir, "input_MEP_trj.xyz")
        ts_geom_path = _find_neb_ts_geometry(job_dir)
        if os.path.exists(mep_path):
            artifacts["mep_trajectory"] = mep_path
            # Combined viewer frames: TS structure first (per the app's own
            # UI convention -- see JobDetailDrawer/NebFrameViewer), then the
            # converged path in ORCA's own numbered order. Built from
            # already-written files via plain text concatenation (both are
            # already valid standalone xmol multi-frame blocks) rather than
            # a structured parse -- nothing here needs the coordinates
            # themselves, only to combine two files.
            with open(mep_path) as f:
                mep_text = f.read()
            frames_text = mep_text
            if ts_geom_path:
                with open(ts_geom_path) as f:
                    frames_text = f.read() + mep_text
            combined_path = os.path.join(job_dir, "neb_frames.xyz")
            with open(combined_path, "w") as f:
                f.write(frames_text)
            artifacts["neb_frames"] = combined_path
        if ts_geom_path:
            artifacts["ts_geometry"] = ts_geom_path

        image_gbw = {}
        for gbw_file in sorted(Path(job_dir).glob("input_im*.gbw")):
            m = re.match(r"input_im(\d+)\.gbw$", gbw_file.name)
            if m:
                image_gbw[m.group(1)] = str(gbw_file)
        if image_gbw:
            artifacts["image_gbw"] = image_gbw

        note_parts = []
        if ts_converged:
            note_parts.append("The NEB-TS search converged; the TS row/geometry is the refined transition state.")
        elif neb_converged:
            note_parts.append(
                "The NEB/CI-NEB path converged, but the subsequent TS-optimization refinement step did not "
                "-- the reported path has no refined TS point; the highest-energy image (marked <= CI, if "
                "present) is the best available saddle-point estimate."
            )
        else:
            note_parts.append(
                "Neither the NEB path nor a TS refinement converged within this run -- the reported path "
                "is the best available intermediate state, not a converged minimum energy path."
            )
        if not path_rows:
            note_parts.append("No PATH SUMMARY table was found in the output at all.")

        summary = {
            "neb_converged": neb_converged,
            "ts_converged": ts_converged,
            "path_summary": path_rows,
            "ts_energy_hartree": ts_energy,
            # Counted by name (excluding any "TS" row), not by has_ts_row --
            # that flag means "matched the FOR NEB-TS table shape", which
            # isn't strictly the same claim as "a TS row is present".
            "n_images_total": len([r for r in path_rows if r["image"] != "TS"]),
            "note": " ".join(note_parts),
        }
        if params.get("target_state"):
            summary["target_state"] = params["target_state"]

        # Reference orbitals from the FINAL wavefunction in input.gbw (the
        # TS-optimized structure on a converged run) -- last=True skips the
        # earlier per-image ORBITAL ENERGIES blocks NEB itself prints along
        # the way (confirmed two such blocks in a real run's output).
        orbital_rows = _orbital_table(output, last=True)
        if orbital_rows:
            summary["orbital_table"] = orbital_rows
            summary["orbital_table_note"] = (
                "Reference orbitals from the final wavefunction (input.gbw) -- the TS-optimized structure "
                "on a converged run, or the last calculation ORCA ran otherwise."
            )

        if path_rows:
            try:
                from app.chemistry.spectrum import render_neb_plot
                plot_path = os.path.join(job_dir, "neb_plot.png")
                render_neb_plot(path_rows, plot_path)
                artifacts["neb_plot"] = plot_path
            except Exception:
                pass  # best-effort -- a plot failure shouldn't fail an otherwise-usable job

        return summary, artifacts

    summary, artifacts = _safe_parse(build_summary, output, job_dir, "neb_ts")
    return {"summary": summary, "artifacts": artifacts}
