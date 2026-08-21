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
from app.chemistry.jobs.orca_runner import _parse_column_block_matrix
from app.chemistry.jobs.vibrations import summarize_frequencies
from app.config import (
    BAGEL_BIN, BAGEL_EXTRA_LIB_DIRS, BAGEL_ONEAPI_SETVARS, CASSCF_CONV_TOL_ENERGY, CASSCF_CONV_TOL_OPT_FREQ,
    CASSCF_MAX_CYCLE_MACRO, N_CORES,
)

# BAGEL ships its own basis-set library (app/../share); exact matches to
# common basis names exist for the cc-pVXZ / (def2-)SVP / def2-TZVPP
# families. Anything else is now resolved via basis_set_exchange's own
# lookup_basis_by_role(name, "jkfit") instead of guessing -- see
# app/chemistry/jobs/bse_basis.py's resolve_bagel_df_basis, which this map
# and _DEFAULT_DF_BASIS both feed (fast/known-family path first, BSE lookup
# second, this constant only as the final last-resort fallback).
_DF_BASIS_MAP = {
    "cc-pvdz": "cc-pvdz-jkfit", "cc-pvtz": "cc-pvtz-jkfit",
    "cc-pvqz": "cc-pvqz-jkfit", "cc-pv5z": "cc-pv5z-jkfit",
    "svp": "svp-jkfit", "def2-svp": "svp-jkfit",
    "tzvpp": "tzvpp-jkfit", "def2-tzvpp": "tzvpp-jkfit",
    "qzvpp": "qzvpp-jkfit", "def2-qzvpp": "qzvpp-jkfit",
}
_DEFAULT_DF_BASIS = "svp-jkfit"


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
    from app.chemistry.jobs.bse_basis import is_bse_ref, bse_name, bagel_bse_basis_path, resolve_bagel_df_basis

    basis_raw = params["basis"]  # original name/"bse:<name>" sentinel -- df matching needs this BEFORE translation
    df_basis, df_exact_match = resolve_bagel_df_basis(basis_raw, params.get("df_basis"), molecule["symbols"])
    basis = bagel_bse_basis_path(bse_name(basis_raw), molecule["symbols"]) if is_bse_ref(basis_raw) else basis_raw

    charge = molecule["charge"]
    nopen = molecule["multiplicity"] - 1  # 2S, same convention as pyscf's mol.spin

    if job_type == "frequency" and params.get("method", "hf") not in ("casscf", "caspt2"):
        # HF-reference only in THIS branch -- CASSCF/CASPT2 frequency
        # falls through to the nested-method-array path further down
        # instead (same shape as the real BAGEL benzene CASPT2 Hessian
        # example this docstring already cites). DFT is still rejected --
        # BAGEL has no DFT reference in this app's frequency job type.
        method = params.get("method", "hf")
        if method != "hf":
            raise ValueError(
                "BAGEL frequency in this app only supports method='hf', 'casscf', or 'caspt2' (no DFT reference)"
            )
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

    if job_type == "gradient" and params.get("method", "hf") == "hf":
        # HF-reference only in this branch -- CASSCF/CASPT2 gradients fall
        # through to the nested-method-array path further down (same shape
        # as the "geometry_optimization"/"frequency" wrapper below). The
        # singular "force" title (not "forces"+"grads", which the manual
        # documents as the multi-state CASSCF/CASPT2-only mechanism) takes
        # target/method directly -- verified live: a plain molecule ->
        # "force" input (no preceding top-level "hf" block) ran and
        # produced a "Nuclear energy gradient" block.
        target_state = params.get("target_state") or 0
        blocks = [
            _molecule_block(molecule, basis, df_basis),
            {"title": "force", "target": target_state,
             "method": [{"title": "hf", "charge": charge, "nopen": nopen}]},
        ]
        bagel_input = {"bagel": blocks}
        meta = {"df_basis": df_basis, "df_basis_exact_match": df_exact_match}
        return bagel_input, meta

    if job_type == "single_point":
        # A plain HF energy calculation -- dispatch.py's resolve_runner only
        # ever routes here when method is NOT casscf/caspt2 (those get their
        # own "casscf"/"caspt2" job_type and fall through to the active-
        # space-building code below), and capabilities.py declares no other
        # method for BAGEL at all, so method is "hf" by construction; the
        # explicit check below is the same defensive pattern the
        # mo_visualization branch above already uses, not a real branch
        # this app can reach any other way.
        #
        # Found by a live regression run (P9.8): before this branch existed,
        # job_type="single_point" fell straight through into the CASSCF
        # code below, which unconditionally reads params["active_electrons"]
        # -- so a plain BAGEL HF single-point energy request (declared
        # supported in capabilities.py, energy=True) crashed with a bare
        # KeyError the moment anyone actually ran one through the full
        # agent pipeline, which nothing had done until this regression pass.
        method = params.get("method", "hf")
        if method != "hf":
            raise ValueError("BAGEL single-point energy in this app only supports method='hf' outside "
                              "casscf/caspt2 (no DFT reference) -- capabilities.py declares no other method.")
        blocks = [
            _molecule_block(molecule, basis, df_basis),
            {"title": "hf", "charge": charge, "nopen": nopen},
        ]
        bagel_input = {"bagel": blocks}
        meta = {"df_basis": df_basis, "df_basis_exact_match": df_exact_match}
        return bagel_input, meta

    if job_type in ("geometry_optimization", "opt_freq") and params.get("method") not in ("casscf", "caspt2"):
        raise ValueError(
            "BAGEL geometry optimization in this app only supports method='casscf' or 'caspt2' -- plain "
            "HF/DFT geometry optimization on BAGEL isn't implemented here (use engine='pyscf' or 'orca')."
        )

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
    # Explicit CASSCF convergence policy (app/config.py's CASSCF_CONV_TOL_*/
    # CASSCF_MAX_CYCLE_MACRO) -- energy-only jobs (casscf/caspt2) use the
    # looser tolerance; geometry_optimization/frequency use the tighter one.
    casscf_conv_tol = (
        CASSCF_CONV_TOL_OPT_FREQ if job_type in ("geometry_optimization", "frequency", "opt_freq")
        else CASSCF_CONV_TOL_ENERGY
    )

    casscf_block = {
        "title": "casscf",
        "nstate": n_states,
        "nact": n_act_orb,
        "nclosed": n_closed,
        "charge": charge,
        "nspin": nopen,
        "thresh": casscf_conv_tol,
        "maxiter": CASSCF_MAX_CYCLE_MACRO,
    }

    # Phase 8 orbital reuse: load_ref REPLACES the "hf" preamble entirely
    # rather than following it -- verified against scripts/spikes/
    # spike_bagel_caps.py's p_ref_archive probe, whose working load_ref
    # input has no preceding hf block at all. "initial_orbitals" is the
    # fixed basename _copy_initial_orbitals_archive actually copies this
    # job's source archive to (BAGEL appends ".archive" itself, matching
    # save_ref's own "orbitals" -> "orbitals.archive" naming, confirmed by
    # the same probe).
    orbital_preamble = (
        [{"title": "load_ref", "file": "initial_orbitals"}] if params.get("initial_orbitals_job_id")
        else [{"title": "hf", "charge": charge, "nopen": nopen}]
    )
    # Always saved (not conditional on initial_orbitals_job_id): every
    # completed CASSCF/CASPT2 job becomes a valid future orbital-reuse
    # source this way, matching PySCF's orbitals.molden and ORCA's
    # input.gbw, both of which are unconditional job outputs already.
    save_ref_block = {"title": "save_ref", "file": "orbitals"}

    smith_block = None
    # For the standalone "caspt2" job_type, job_type=="caspt2" alone
    # already unambiguously means "run CASPT2" -- the worker dispatch
    # (bagel_worker.py's DISPATCH) only ever calls run_caspt2 for
    # spec.method=="caspt2" in the first place, so gating this on
    # params.get("method") too was a bug: "method" is not a required or
    # optional param for the standalone caspt2 job_type in registry.py
    # (REQUIRED_PARAMS["caspt2"]/OPTIONAL_PARAMS["caspt2"] have no "method"
    # key), so nothing in the normal submission path ever sets it, and a
    # plain caspt2 submission without a redundant method="caspt2" argument
    # silently built a CASSCF-only input with no CASPT2 correction at all
    # (confirmed empirically: reproduced this exact case building an input
    # via _build_input directly). geometry_optimization/frequency/gradient/
    # nac genuinely DO need the params.get("method") check below (method
    # there can be 'hf'/'casscf'/'caspt2', except nac which is never 'hf'
    # -- see run_nac's own docstring), so that half of the condition is
    # unchanged.
    if job_type == "caspt2" or (
        job_type in ("geometry_optimization", "frequency", "opt_freq", "gradient", "nac")
        and params.get("method") == "caspt2"
    ):
        ms = params.get("ms_caspt2", True)
        smith_block = {
            "title": "smith",
            "method": "caspt2",
            "ms": ms,
            "xms": ms,
            "sssr": True,
            "shift": params.get("shift", 0.2),
            "frozen": params.get("frozen_core", True),
        }

    if job_type in ("geometry_optimization", "frequency", "opt_freq"):
        # Real worked BAGEL example confirmed (grad/hess.html's benzene
        # CASPT2 Hessian, already cited in this module's own docstring as
        # verified precedent): a standalone "hf" -> "casscf" pair precedes
        # the "optimize"/"hessian" block(s) (establishing/storing reference
        # orbitals, same shape this app's plain casscf/caspt2 job already
        # builds and re-exports via the "print" block right after
        # "casscf" -- same placement rule as above, same reasoning), and
        # each "optimize"/"hessian" block's own nested "method" array
        # re-states the CASSCF (Form 2: casscf entry [+ a following smith
        # entry for CASPT2]) or CASPT2 (Form 1: single "caspt2"-titled
        # entry with a nested "smith" dict) block BAGEL actually
        # differentiates at each displaced geometry -- both forms
        # confirmed equivalent in grad/methods.html's own worked examples;
        # Form 1 is used here for CASPT2 to match the real benzene example
        # verbatim rather than the untested (for gradients) Form 2.
        #
        # opt_freq (Phase 6, single-input): the Phase 0 spike (p_opt_hess,
        # HF reference) confirmed BAGEL runs an "optimize" block followed
        # by a "hessian" block in ONE input, with the Hessian genuinely
        # computed at the OPTIMIZED geometry, not the starting one --
        # BAGEL carries the geometry forward between blocks in one file
        # the same way ORCA's combined "! Opt Freq" does. Two SEPARATE
        # wrapper blocks (not a fused shape) is exactly what worked there;
        # this app's own CASSCF/CASPT2 preamble is unaffected by chaining
        # two wrappers instead of one.
        target_state = params.get("target_state") or 0
        if smith_block is not None:
            smith_inner = {k: v for k, v in smith_block.items() if k != "title"}
            gradient_entries = [{
                "title": "caspt2", "smith": smith_inner,
                "nstate": n_states, "nact": n_act_orb, "nclosed": n_closed,
            }]
        else:
            gradient_entries = [dict(casscf_block)]

        def _wrapper(title: str) -> dict:
            wb: dict = {"title": title, "target": target_state, "method": gradient_entries}
            if title == "optimize":
                wb["maxiter"] = params.get("max_steps", 200)
                if params.get("optimization_type") == "conical_intersection":
                    wb["opttype"] = "conical"
                    wb["target2"] = params.get("target_state_2") or (target_state + 1)
            else:
                wb["dx"] = params.get("dx") or 1.0e-3
            return wb

        if job_type == "opt_freq":
            wrapper_blocks = [_wrapper("optimize"), _wrapper("hessian")]
        else:
            wrapper_blocks = [_wrapper("optimize" if job_type == "geometry_optimization" else "hessian")]

        blocks = [
            _molecule_block(molecule, basis, df_basis),
            *orbital_preamble,
            dict(casscf_block),
            {"title": "print", "file": "orbitals.molden", "orbitals": True},
            save_ref_block,
            *wrapper_blocks,
        ]
        bagel_input = {"bagel": blocks}
        meta = {
            "n_closed": n_closed, "n_electrons": n_electrons,
            "df_basis": df_basis, "df_basis_exact_match": df_exact_match,
            "dx": wrapper_blocks[-1].get("dx"),
        }
        return bagel_input, meta

    if job_type in ("gradient", "nac"):
        # CASSCF/CASPT2 from here (plain HF gradient already returned
        # above). Same "hf" -> "casscf" -> "print" preamble as the
        # "geometry_optimization"/"frequency" wrapper above -- not required
        # for the force/nacme output itself (verified live: a bare
        # molecule + force/nacme block with no preamble also produces one),
        # but IS required to get orbitals.molden written for
        # _add_orbital_table, matching every other CASSCF/CASPT2 job_type
        # here. The force/nacme block's own nested "method" entry restates
        # the CASSCF (Form 2) or CASPT2 (Form 1) spec at the same
        # reference geometry, same convention as gradient_entries above.
        if smith_block is not None:
            smith_inner = {k: v for k, v in smith_block.items() if k != "title"}
            method_entries = [{
                "title": "caspt2", "smith": smith_inner,
                "nstate": n_states, "nact": n_act_orb, "nclosed": n_closed,
            }]
        else:
            method_entries = [dict(casscf_block)]

        if job_type == "gradient":
            target_state = params.get("target_state") or 0
            force_block: dict = {"title": "force", "target": target_state, "method": method_entries}
        else:
            pair = params["state_pairs"][0]
            s1, s2 = int(pair[0]) - 1, int(pair[1]) - 1
            force_block = {"title": "nacme", "target": s1, "target2": s2, "method": method_entries}

        blocks = [
            _molecule_block(molecule, basis, df_basis),
            *orbital_preamble,
            dict(casscf_block),
            {"title": "print", "file": "orbitals.molden", "orbitals": True},
            save_ref_block,
            force_block,
        ]
        bagel_input = {"bagel": blocks}
        meta = {
            "n_closed": n_closed, "n_electrons": n_electrons,
            "df_basis": df_basis, "df_basis_exact_match": df_exact_match,
        }
        return bagel_input, meta

    blocks = [
        _molecule_block(molecule, basis, df_basis),
        *orbital_preamble,
        casscf_block,
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
        save_ref_block,
    ]
    if job_type == "caspt2" and smith_block is not None:
        if params.get("want_oscillator_strengths"):
            # A plain "smith"-titled caspt2 block (above) never prints
            # transition dipoles/oscillator strengths -- BAGEL only
            # computes those as a side effect of a "forces" block (which
            # needs one gradient target per state, "dipole": "true", and
            # its own nested "method" entry restating the caspt2/smith
            # config). Verified against a real water/CAS(4,4)/cc-pVDZ
            # BAGEL 1.2.2 run: this produces a single, once-only "* CASPT2
            # dipole moments" section printing every state's own dipole
            # plus every pairwise transition (e.g. "Transition 2 - 1", not
            # just ground-state-relative ones) each followed by its own
            # "Oscillator strength" line -- see
            # _parse_caspt2_oscillator_strengths, which deliberately keeps
            # only the ground-state-relative subset ("Transition i - 0")
            # to match this app's existing excitation_energies_eV
            # convention (ground-state-relative only, shared by every
            # engine/method here). The per-state gradients this block also
            # computes are a required side effect of BAGEL's algorithm for
            # getting transition dipoles at all, not something this app
            # parses or exposes. Confirmed the existing _CASPT2_ROW/
            # _dominant_transitions_bagel parsers still find the right
            # (last-occurrence) converged energies/CI vectors unchanged
            # against this block shape -- no changes needed there.
            smith_inner = {k: v for k, v in smith_block.items() if k != "title"}
            forces_block = {
                "title": "forces",
                "dipole": "true",
                "grads": [{"title": "force", "target": i, "ciderivative": "false"} for i in range(n_states)],
                "method": [{
                    "title": "caspt2", "smith": smith_inner,
                    "nstate": n_states, "nact": n_act_orb, "nclosed": n_closed,
                }],
            }
            blocks.append(forces_block)
        else:
            blocks.append(smith_block)

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
    card edit path set one (see submit_draft in tools.py) -- writing the
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


def _copy_initial_orbitals_archive(job_dir: str, params: dict) -> None:
    """Copies a completed CASSCF/CASPT2-family BAGEL job's save_ref archive
    (orbitals.archive, written by every such job's own _build_input
    preamble via save_ref_block) into THIS job's own directory as
    initial_orbitals.archive -- the fixed basename _build_input's
    load_ref step (orbital_preamble) references when
    params['initial_orbitals_job_id'] is set. No-op otherwise.

    Source-job validity (existence, completed, casscf/caspt2 method, same
    engine) is checked pre-interrupt in registry2/elicitation.py; this
    performs the actual copy, deferred to dispatch time (called from
    _run_bagel, the one execution chokepoint every run_* function here
    shares) per this app's cross-job-artifact precedent
    (app/agent/tools.py's own _resolve_batch_geometries)."""
    source_job_id = params.get("initial_orbitals_job_id")
    if not source_job_id:
        return
    import shutil
    from app.config import JOBS_DIR
    source = os.path.join(str(JOBS_DIR), source_job_id, "orbitals.archive")
    if not os.path.exists(source):
        raise RuntimeError(
            f"Initial-orbitals source job '{source_job_id}' has no orbitals.archive on disk "
            f"(BAGEL's save_ref output) -- it may not be a completed CASSCF/CASPT2 job."
        )
    shutil.copy(source, os.path.join(job_dir, "initial_orbitals.archive"))


def _run_bagel(job_dir: str, input_text: str, params: dict) -> str:
    _copy_initial_orbitals_archive(job_dir, params)
    input_path = os.path.join(job_dir, "input.json")
    out_path = os.path.join(job_dir, "bagel.out")
    with open(input_path, "w") as f:
        f.write(input_text)

    cmd = (
        f'source {BAGEL_ONEAPI_SETVARS} > /dev/null 2>&1; '
        f'export OMP_NUM_THREADS={N_CORES} MKL_NUM_THREADS={N_CORES}; '
        # BAGEL_EXTRA_LIB_DIRS (Boost/ScaLAPACK/OpenBLAS -- see its own
        # config.py docstring) prepended ahead of whatever LD_LIBRARY_PATH
        # oneAPI's setvars.sh just set, not replacing it -- BAGEL needs
        # both sets of libraries at once.
        f'export LD_LIBRARY_PATH="{BAGEL_EXTRA_LIB_DIRS}:$LD_LIBRARY_PATH"; '
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

# "* CASPT2 dipole moments" section a want_oscillator_strengths=True run's
# "forces"+dipole=true block prints (see _build_input) -- once per run,
# confirmed on a real water/CAS(4,4)/cc-pVDZ BAGEL 1.2.2 run. Each
# ground-state-relative transition line ("Transition N - 0 :") is
# immediately followed (next line, no blank line between them) by its own
# "Oscillator strength :" line; BAGEL also prints every OTHER pairwise
# transition (e.g. "Transition 2 - 1") in the same section, which
# _CASPT2_GS_TRANSITION_OSC's literal "- 0" deliberately excludes.
_CASPT2_DIPOLE_HEADER = re.compile(r"\*\s*CASPT2 dipole moments\b")
_CASPT2_GS_TRANSITION_OSC = re.compile(
    r"Transition\s+(\d+)\s*-\s*0\s*:[^\n]*\n\s*\*\s*Oscillator strength\s*:\s*(-?\d+\.\d+)"
)

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

# The section titled "Vibrational frequencies, IR intensities, and
# corresponding cartesian eigenvectors" -- NOT the earlier "Mass Weighted
# Hessian Eigenvectors ++" section, which has an identically-shaped
# 'row_idx val val ...' block layout but prints the mass-weighted
# eigenvectors themselves (would give lighter/heavier atoms displacement
# magnitudes scaled by 1/sqrt(mass) relative to each other, not a
# physically real animation) rather than mass-deweighted real-space
# Cartesian displacements. Verified against a real BAGEL 1.2.2 water/HF/
# STO-3G Hessian run: each block is "header row of mode indices" ->
# "Freq (cm-1)" row -> blank -> "IR Int. (km/mol)" row -> "Rel. IR Int."
# row -> blank -> 3*n_atoms displacement rows -> blank, then either the
# next block's header directly or (after the last block) a
# "** CAUTION **" line -- reusing orca_runner's _parse_column_block_matrix
# (identical header/row shape on both engines) rather than duplicating
# the block-scanning logic, since it only needs the bare 'row_idx val
# val ...' pattern and tolerates the intervening Freq/IR/blank lines by
# skipping anything that isn't itself a header or a data row.
_CARTESIAN_EIGENVECTOR_HEADER = re.compile(
    r"Vibrational frequencies, IR intensities, and corresponding cartesian eigenvectors\s*\n"
)

# "* Nuclear energy gradient" / "o Atom N / x .../y .../z ..." -- the SAME
# block shape a "force" block and a "nacme" block both print (verified
# live: BAGEL treats a derivative coupling as gradient-shaped output, one
# vector per atom, under this identical header), 0-based atom indices.
# Bounded by "* METHOD:", which every one of these blocks prints right
# after it regardless of reference (HF/CASSCF/CASPT2) -- an earlier version
# bounded on "* Gradient computed with" instead, which turned out to be
# HF/CASSCF-only; a live CASPT2 gradient run printed "- Gradient integral
# contraction" there instead, silently breaking the parser for CASPT2 only.
_BAGEL_GRADIENT_SECTION = re.compile(r"Nuclear energy gradient\s*\n(.*?)\*\s*METHOD:", re.DOTALL)
_BAGEL_ATOM_VEC = re.compile(
    r"o Atom\s+(\d+)\s*\n\s*x\s+(-?\d+\.\d+)\s*\n\s*y\s+(-?\d+\.\d+)\s*\n\s*z\s+(-?\d+\.\d+)"
)
# NACME-only extras BAGEL prints for free (capabilities.py: "BAGEL's NAC
# output is richer than ORCA's -- it carries the transition dipole and
# oscillator strength alongside the coupling"), verified against a real
# CAS(4,4)/svp water 2-state run.
_BAGEL_ENERGY_GAP_EV = re.compile(r"Energy gap is:\s*(-?\d+\.\d+)\s*eV")
_BAGEL_TRANSITION_DIPOLE = re.compile(
    r"Transition dipole moment between \d+ - \d+\s*\n\s*\(\s*(-?\d+\.\d+),\s*(-?\d+\.\d+),\s*(-?\d+\.\d+)\)"
)
_BAGEL_OSC_STRENGTH = re.compile(r"Oscillator strength for transition between \d+ - \d+\s+(-?\d+\.\d+)\s*a\.u\.")

# Plain "hf" block output (single_point/gs, method=hf -- see _build_input's
# single_point branch and run_single_point below), verified against a real
# water/STO-3G run: numbered SCF iteration lines ("      6        -74.96..."
# energy, gradient norm, elapsed) and a two-line "Permanent dipole moment:"
# block, distinct from the excited-state-only NACME extras above.
_BAGEL_RHF_ITERATION_ENERGY = re.compile(r"^\s*\d+\s+(-?\d+\.\d+)\s+[\d.]+\s+[\d.]+\s*$", re.MULTILINE)
_BAGEL_PERMANENT_DIPOLE_AU = re.compile(
    r"Permanent dipole moment:\s*\n\s*\(\s*(-?\d+\.\d+),\s*(-?\d+\.\d+),\s*(-?\d+\.\d+)\s*\)\s*a\.u\."
)
_AU_DIPOLE_TO_DEBYE = 2.5417464519


def _parse_row_values(rows: list[str]) -> list[float]:
    values: list[float] = []
    for row in rows:
        values.extend(float(x) for x in row.split())
    return values


def _parse_gradient_block(output: str) -> list[list[float]] | None:
    """The per-atom vector under the LAST '* Nuclear energy gradient'
    header -- shared by run_gradient and run_nac (see _BAGEL_ATOM_VEC's own
    docstring for why the same block shape serves both). None if the
    section or any atom row is missing."""
    sections = _BAGEL_GRADIENT_SECTION.findall(output)
    if not sections:
        return None
    rows = _BAGEL_ATOM_VEC.findall(sections[-1])
    if not rows:
        return None
    by_index = {int(idx): [float(x), float(y), float(z)] for idx, x, y, z in rows}
    return [by_index[i] for i in sorted(by_index)]


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


def _excitation_energies_eV(state_energies_hartree: list) -> list | None:
    """Gaps (eV) of every excited state relative to state 0, matching
    orca_runner.py's own excitation_energies_eV convention (length
    n_states-1) -- BAGEL CASSCF/CASPT2 otherwise only ever report absolute
    state_energies_hartree, unlike ORCA CASSCF, which already has this
    field. None entries in the input (a state whose energy failed to
    parse) propagate as None rather than raising, since _safe_parse's
    caller may still want the other states' summary; a single-state list
    (or one with fewer than 2 non-None entries) returns None -- there's no
    excitation to report."""
    if len(state_energies_hartree) < 2 or state_energies_hartree[0] is None:
        return None
    e0 = state_energies_hartree[0]
    return [None if e is None else (e - e0) * 27.211386245988 for e in state_energies_hartree[1:]]


def _parse_caspt2_oscillator_strengths(output: str, n_states: int) -> list | None:
    """Ground-state-relative CASPT2 oscillator strengths (State i vs State
    0), parsed from the once-only '* CASPT2 dipole moments' section a
    want_oscillator_strengths=True run's "forces"+dipole block prints (see
    _build_input and _CASPT2_GS_TRANSITION_OSC's own docstring). Returns a
    list of length n_states-1 (index 0 = S1, matching
    _excitation_energies_eV's own ground-state-relative indexing), with
    None entries for any state whose transition line wasn't found -- or
    None outright if the dipole section never printed at all (e.g. BAGEL
    didn't reach that stage, or this run didn't actually request it)."""
    if not _CASPT2_DIPOLE_HEADER.search(output):
        return None
    found: dict[int, float] = {}
    for m in _CASPT2_GS_TRANSITION_OSC.finditer(output):
        found[int(m.group(1))] = float(m.group(2))
    return [found.get(i) for i in range(1, n_states)]


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

    table = molden_tools.orbital_table(molden_path)
    # BAGEL's molden export round-trips exactly through pyscf's own AO
    # convention (point-sampling verified elsewhere in this app -- see
    # CLAUDE.md's MO-visualization architecture note), unlike ORCA's, so
    # classify_orbital_character's Mulliken-population-based character/
    # localization is trustworthy here. Best-effort: a classification
    # failure degrades to plain energy/occupancy rows.
    try:
        for row, char_row in zip(table, molden_tools.orbital_character(molden_path)):
            row.update(char_row)
    except Exception:
        pass
    summary["orbital_table"] = table
    summary["orbital_table_note"] = (
        "Natural orbitals with active-space occupation numbers (not integer HF-style occupancies) -- "
        "core orbitals show occ=2, active orbitals show their natural-orbital occupation, virtuals show occ=0. "
        "Character (sigma/pi/n/sigma*/pi*) and dominant localized atom(s) are best-effort from point-sampling. "
        "BAGEL's own molden export also writes energy_eV=0.0 for every active-space orbital (confirmed in the "
        "raw .molden file, not a parsing gap here) -- it has no single-particle Fock eigenvalue for a "
        "multi-configurational active orbital the way core/virtual orbitals do, unlike ORCA/PySCF's CASSCF "
        "exports, which report a generalized-Fock-based energy there instead."
    )
    return molden_path


def run_custom(molecule: dict, params: dict) -> dict:
    """Runs an arbitrary, agent-composed BAGEL input verbatim -- mirrors
    orca_runner.run_custom. _run_bagel already checks only the process
    returncode, no job-type-specific content marker, so it's reused
    directly with no generic variant needed (unlike ORCA's
    _write_and_run, which does check for a content marker)."""
    job_dir = params["_job_dir"]
    text = params.get("_raw_input")
    if not text:
        raise RuntimeError("custom BAGEL job has no input text to run")
    output = _run_bagel(job_dir, text, params)
    return {
        "summary": {
            "note": (
                "Raw custom BAGEL input -- no structured result parsing was attempted for this job type. "
                "The tail of the raw output below is what's available programmatically; the full raw "
                "input/output are also available to the user as job artifacts in the UI."
            ),
            "raw_output_tail": output[-2000:],
        },
        "artifacts": {"raw_output": os.path.join(job_dir, "bagel.out")},
    }


def run_casscf(molecule: dict, params: dict) -> dict:
    job_dir = params["_job_dir"]
    input_text, meta = _effective_input_text(molecule, params, "casscf")
    output = _run_bagel(job_dir, input_text, params)

    n_states = params.get("n_states", 1)

    def build_summary():
        state_energies = _parse_casscf_energies(output, n_states)
        if len(state_energies) < n_states:
            raise RuntimeError(f"found converged energies for {len(state_energies)} of {n_states} state(s)")
        n_closed = meta["n_closed"] if meta else None
        state_energies_list = [state_energies[i] for i in range(n_states)]
        summary = {
            "state_energies_hartree": state_energies_list,
            "excitation_energies_eV": _excitation_energies_eV(state_energies_list),
            "casscf_energy_hartree": state_energies[0] if n_states == 1 else None,
            "active_electrons": params.get("active_electrons"),
            "active_orbitals": params.get("active_orbitals"),
            "n_closed_orbitals": n_closed,
            "n_states": n_states,
            "dominant_transitions": _dominant_transitions_bagel(output, n_states, n_closed),
            "df_basis_used": meta["df_basis"] if meta else None,
            "df_basis_exact_match": meta["df_basis_exact_match"] if meta else None,
            "initial_orbitals_source_job_id": params.get("initial_orbitals_job_id"),
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
    output = _run_bagel(job_dir, input_text, params)

    n_states = params.get("n_states", 1)
    want_osc = bool(params.get("want_oscillator_strengths"))

    def build_summary():
        casscf_energies = _parse_casscf_energies(output, n_states)
        caspt2_energies = _parse_caspt2_energies(output)
        if len(caspt2_energies) < n_states:
            raise RuntimeError(f"found converged CASPT2 energies for {len(caspt2_energies)} of {n_states} state(s)")
        n_closed = meta["n_closed"] if meta else None
        caspt2_energies_list = [caspt2_energies[i] for i in range(n_states)]
        summary = {
            "state_energies_hartree": caspt2_energies_list,
            "excitation_energies_eV": _excitation_energies_eV(caspt2_energies_list),
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
            "initial_orbitals_source_job_id": params.get("initial_orbitals_job_id"),
        }
        if want_osc:
            osc = _parse_caspt2_oscillator_strengths(output, n_states)
            summary["oscillator_strengths"] = osc
            if osc is None:
                summary["oscillator_strengths_note"] = (
                    "want_oscillator_strengths was requested but the 'CASPT2 dipole moments' section "
                    "never appeared in BAGEL's output -- oscillator strengths are unavailable for this run."
                )
        return summary, _add_orbital_table(summary, job_dir)

    summary, molden_path = _safe_parse(build_summary, output, job_dir, "caspt2")
    artifacts = {"raw_output": os.path.join(job_dir, "bagel.out")}
    if molden_path:
        artifacts["molden"] = molden_path
    return {"summary": summary, "artifacts": artifacts}


def run_gradient(molecule: dict, params: dict) -> dict:
    """single_point/grad. method in (hf, casscf, caspt2) -- capabilities.py
    claims analytic gradient for all three on BAGEL. target_state=None/0
    means the ground state (BAGEL's own target=0 default), matching every
    other engine's runner here."""
    job_dir = params["_job_dir"]
    input_text, meta = _effective_input_text(molecule, params, "gradient")
    output = _run_bagel(job_dir, input_text, params)

    def build_summary():
        gradient = _parse_gradient_block(output)
        if gradient is None:
            raise RuntimeError("could not find the 'Nuclear energy gradient' block")
        norm = sum(v * v for row in gradient for v in row) ** 0.5
        summary = {
            "gradient_hartree_per_bohr": gradient,
            "gradient_norm_hartree_per_bohr": norm,
            "method": params.get("method"),
            "target_state": params.get("target_state"),
            "active_electrons": params.get("active_electrons"),
            "active_orbitals": params.get("active_orbitals"),
            "df_basis_used": meta["df_basis"] if meta else None,
            "df_basis_exact_match": meta["df_basis_exact_match"] if meta else None,
        }
        molden_path = _add_orbital_table(summary, job_dir) if params.get("method") != "hf" else None
        return summary, molden_path

    summary, molden_path = _safe_parse(build_summary, output, job_dir, "gradient")
    artifacts = {"raw_output": os.path.join(job_dir, "bagel.out")}
    if molden_path:
        artifacts["molden"] = molden_path
    return {"summary": summary, "artifacts": artifacts}


def run_single_point(molecule: dict, params: dict) -> dict:
    """single_point/gs, method=hf -- dispatch.py's resolve_runner only ever
    routes here for BAGEL when method is NOT casscf/caspt2 (those get their
    own "casscf"/"caspt2" runner), and capabilities.py declares no other
    method for BAGEL, so method="hf" by construction (see _build_input's
    own single_point branch for the same reasoning).

    Deliberately minimal -- energy and dipole only, no orbital_table: a
    plain "hf" block prints neither a molden export nor a per-orbital
    energy table (verified against real output; see this function's own
    regressions test), and reusing _add_orbital_table's CASSCF-authored
    note ("natural orbitals with active-space occupation", the BAGEL
    energy_eV=0.0-for-active-orbitals quirk) here would misdescribe plain
    canonical HF orbitals, which have neither property. Someone who wants
    BAGEL HF orbitals specifically already has that: the separate,
    already-verified mo_visualization/orbital_indices path.

    Found missing by a live regression run (P9.8): job_type="single_point"
    had no entry in bagel_worker.py's DISPATCH at all, despite
    capabilities.py declaring energy=True for bagel/hf -- an untested
    "manual"-tier claim that nothing had actually run through the full
    agent pipeline until this pass did, surfacing that no runner exists.
    """
    job_dir = params["_job_dir"]
    input_text, meta = _effective_input_text(molecule, params, "single_point")
    output = _run_bagel(job_dir, input_text, params)

    def build_summary():
        energies = _BAGEL_RHF_ITERATION_ENERGY.findall(output)
        if not energies:
            raise RuntimeError("could not find a converged RHF iteration energy in BAGEL's output")
        converged = "SCF iteration converged" in output
        dip = _BAGEL_PERMANENT_DIPOLE_AU.search(output)
        summary = {
            "energy_hartree": float(energies[-1]),
            "converged": converged,
            "method": "hf",
            "basis": params.get("basis"),
            "dipole_debye": [float(x) * _AU_DIPOLE_TO_DEBYE for x in dip.groups()] if dip else None,
            "df_basis_used": meta["df_basis"] if meta else None,
            "df_basis_exact_match": meta["df_basis_exact_match"] if meta else None,
        }
        return summary, None

    summary, _molden_path = _safe_parse(build_summary, output, job_dir, "single_point")
    artifacts = {"raw_output": os.path.join(job_dir, "bagel.out")}
    return {"summary": summary, "artifacts": artifacts}


def run_nac(molecule: dict, params: dict) -> dict:
    """single_point/nac. Only method in (casscf, caspt2) reaches here --
    BAGEL has no HF-reference NAC (capabilities.py: bagel/hf carries no nac
    claim at all). state_pairs (registry2/params.py) is 1-based INCLUDING
    the ground state ([[1, 2]] means the S0/S1 coupling), matching every
    other engine's runner here; BAGEL's own target/target2 are 0-based
    from the ground state (target=0 default, per the scraped manual), so
    the -1 conversion happens here, at the input-building boundary."""
    job_dir = params["_job_dir"]
    input_text, meta = _effective_input_text(molecule, params, "nac")
    output = _run_bagel(job_dir, input_text, params)

    def build_summary():
        nac = _parse_gradient_block(output)
        if nac is None:
            raise RuntimeError("could not find the 'Nuclear energy gradient' block for the NAC vector")
        norm = sum(v * v for row in nac for v in row) ** 0.5
        pair = params["state_pairs"][0]
        gap = _BAGEL_ENERGY_GAP_EV.search(output)
        dip = _BAGEL_TRANSITION_DIPOLE.search(output)
        osc = _BAGEL_OSC_STRENGTH.search(output)
        summary = {
            "nac_hartree_per_bohr": nac,
            "nac_norm_hartree_per_bohr": norm,
            "state_pair": [int(pair[0]), int(pair[1])],
            "energy_gap_eV": float(gap.group(1)) if gap else None,
            "transition_dipole_au": [float(x) for x in dip.groups()] if dip else None,
            "oscillator_strength": float(osc.group(1)) if osc else None,
            "method": params.get("method"),
            "active_electrons": params.get("active_electrons"),
            "active_orbitals": params.get("active_orbitals"),
            "df_basis_used": meta["df_basis"] if meta else None,
            "df_basis_exact_match": meta["df_basis_exact_match"] if meta else None,
        }
        molden_path = _add_orbital_table(summary, job_dir)
        return summary, molden_path

    summary, molden_path = _safe_parse(build_summary, output, job_dir, "nac")
    artifacts = {"raw_output": os.path.join(job_dir, "bagel.out")}
    if molden_path:
        artifacts["molden"] = molden_path
    return {"summary": summary, "artifacts": artifacts}


def _geometry_optimization_summary(output: str, job_dir: str, molecule: dict, params: dict, meta: dict | None):
    """The `geometry_optimization` half of a build_summary -- factored out
    so a combined opt_freq single-input run (see run_opt_freq) can build
    both this AND `_frequency_summary` below from the SAME `output`/
    `job_dir`, rather than duplicating either. The optimized geometry is
    read back from BAGEL's own "opt.molden" export via pyscf.tools.molden
    (the same reader app/chemistry/jobs/molden.py already uses elsewhere)
    rather than parsed from stdout, since the manual states the per-step
    optimization detail is written to opt.log/opt.molden, not fully
    printed to stdout -- confirmed live (Phase 6) that this file still
    exists when a "hessian" block follows the "optimize" block in the
    same input. `_parse_casscf_energies`/`_parse_caspt2_energies`'s
    existing last-occurrence-wins convention (see their docstrings) picks
    up the FINAL geometry's converged energies, since BAGEL re-prints the
    same macro-iteration table shape at every displaced geometry the
    optimizer evaluates -- and, confirmed live for the combined case,
    still resolves correctly with a Hessian's own displaced-geometry
    macro-iterations appended after the optimization's in the same text,
    because those come from re-evaluating the SAME (already optimized,
    undisplaced) reference point printed last within the Hessian's own
    block, not a different geometry."""
    n_states = params.get("n_states", 1)
    method = params["method"]
    casscf_energies = _parse_casscf_energies(output, n_states)
    energies = _parse_caspt2_energies(output) if method == "caspt2" else casscf_energies
    if len(energies) < n_states:
        raise RuntimeError(
            f"found converged {'CASPT2 ' if method == 'caspt2' else ''}energies for "
            f"{len(energies)} of {n_states} state(s)"
        )
    n_closed = meta["n_closed"] if meta else None

    optimized_molecule = None
    opt_molden = os.path.join(job_dir, "opt.molden")
    if os.path.exists(opt_molden):
        from pyscf.tools import molden as pyscf_molden

        mol_opt = pyscf_molden.load(opt_molden)[0]
        optimized_molecule = dict(molecule)
        optimized_molecule["symbols"] = [mol_opt.atom_symbol(i) for i in range(mol_opt.natm)]
        optimized_molecule["coords"] = (mol_opt.atom_coords() * 0.52917721067).tolist()

    opt_state_energies = [energies[i] for i in range(n_states)]
    summary = {
        "state_energies_hartree": opt_state_energies,
        "excitation_energies_eV": _excitation_energies_eV(opt_state_energies),
        "final_energy_hartree": energies[0] if n_states == 1 else None,
        "optimized_molecule": optimized_molecule,
        "active_electrons": params.get("active_electrons"),
        "active_orbitals": params.get("active_orbitals"),
        "n_closed_orbitals": n_closed,
        "n_states": n_states,
        "method": method,
        "dominant_transitions": _dominant_transitions_bagel(output, n_states, n_closed),
        "df_basis_used": meta["df_basis"] if meta else None,
        "df_basis_exact_match": meta["df_basis_exact_match"] if meta else None,
    }
    if method == "caspt2":
        summary["casscf_reference_energies_hartree"] = [casscf_energies.get(i) for i in range(n_states)]
    if params.get("optimization_type") == "conical_intersection":
        summary["optimization_type"] = "conical_intersection"
        summary["target_state"] = params.get("target_state") or 0
        summary["target_state_2"] = params.get("target_state_2")
    return summary


def run_geometry_optimization(molecule: dict, params: dict) -> dict:
    """CASSCF/CASPT2 geometry optimization via BAGEL's "optimize" title
    (see _build_input) -- BAGEL-only in this app; plain HF/DFT geometry
    optimization on BAGEL isn't implemented (use engine='pyscf'/'orca')."""
    job_dir = params["_job_dir"]
    input_text, meta = _effective_input_text(molecule, params, "geometry_optimization")
    output = _run_bagel(job_dir, input_text, params)

    def build_summary():
        summary = _geometry_optimization_summary(output, job_dir, molecule, params, meta)
        return summary, _add_orbital_table(summary, job_dir)

    summary, molden_path = _safe_parse(build_summary, output, job_dir, "geometry_optimization")
    artifacts = {"raw_output": os.path.join(job_dir, "bagel.out")}
    if molden_path:
        artifacts["molden"] = molden_path
    if os.path.exists(os.path.join(job_dir, "opt.molden")):
        artifacts["optimized_geometry_molden"] = os.path.join(job_dir, "opt.molden")
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
# F-026: the value itself now lives in app/config.py as
# IMAGINARY_FREQ_THRESHOLD_CM1 and is applied by
# app/chemistry/jobs/vibrations.summarize_frequencies for all three
# engines, not just this one. The reasoning above is why 50 cm-1 was
# the right number to standardise on rather than replace.


def _normal_modes_bagel(output: str, n_atoms: int, n_modes: int) -> list[list[list[float]]] | None:
    """normal_modes[mode][atom] = [dx, dy, dz], same shape as
    pyscf_runner.run_frequency's/orca_runner's normal_modes -- reads the
    mass-deweighted "...cartesian eigenvectors" section, not the earlier
    mass-weighted one (see _CARTESIAN_EIGENVECTOR_HEADER's comment)."""
    header = _CARTESIAN_EIGENVECTOR_HEADER.search(output)
    if not header:
        return None
    text = output[header.end():]
    matrix = _parse_column_block_matrix(text, 3 * n_atoms)
    if matrix is None or len(matrix) != 3 * n_atoms or any(len(v) != n_modes for v in matrix.values()):
        return None
    return [
        [[matrix[3 * atom][mode], matrix[3 * atom + 1][mode], matrix[3 * atom + 2][mode]] for atom in range(n_atoms)]
        for mode in range(n_modes)
    ]


def run_frequency(molecule: dict, params: dict) -> dict:
    """Numerical Hessian via central gradient differences. HF reference:
    real water/HF/STO-3G run verified the frequencies land in the same
    ballpark as PySCF/ORCA's analytic Hessian for the same system
    (~2000-4800 cm-1 range), as expected for a different but comparable
    numerical method. CASSCF/CASPT2 reference (method='casscf'/'caspt2',
    see _build_input's nested-method-array "hessian" branch): the same
    _HESSIAN_FREQ_ROW/_HESSIAN_IR_ROW/_normal_modes_bagel parsers apply
    unchanged, since BAGEL's Hessian output format doesn't depend on the
    underlying wavefunction method, only on the numerical-Hessian module
    itself.

    Unlike PySCF/ORCA, BAGEL's Hessian module does not print
    zero-point-energy/enthalpy/Gibbs/entropy thermochemistry -- omitted
    from the summary (via thermochemistry_note) rather than fabricated."""
    job_dir = params["_job_dir"]
    input_text, meta = _effective_input_text(molecule, params, "frequency")
    output = _run_bagel(job_dir, input_text, params)
    method = params.get("method", "hf")
    n_states = params.get("n_states", 1)

def _frequency_summary(output: str, molecule: dict, params: dict, meta: dict | None) -> dict:
    """The `frequency` half of a build_summary -- factored out for the
    same reason as `_geometry_optimization_summary` above: a combined
    opt_freq single-input run needs both parsers over the SAME output
    text."""
    method = params.get("method", "hf")
    n_states = params.get("n_states", 1)
    freqs = _parse_row_values(_HESSIAN_FREQ_ROW.findall(output))
    if not freqs:
        raise RuntimeError("could not find any 'Freq (cm-1)' rows in the output")
    ir = _parse_row_values(_HESSIAN_IR_ROW.findall(output))
    # F-026: the threshold rule this engine already had, now shared with
    # the other two (app/chemistry/jobs/vibrations.py) instead of being
    # a private constant only BAGEL applied.
    freq_summary = summarize_frequencies(freqs)
    # Same defensive-degrade reasoning as orca_runner.run_frequency: a
    # malformed eigenvector block shouldn't fail an otherwise-successful
    # frequency job, since frequencies/IR intensities already parsed fine.
    try:
        normal_modes = _normal_modes_bagel(output, len(molecule["symbols"]), len(freqs))
    except Exception:
        normal_modes = None
    reduced_mass_amu = None
    if normal_modes:
        try:
            from app.chemistry.jobs.vibrations import reduced_masses_from_normal_modes
            reduced_mass_amu = reduced_masses_from_normal_modes(normal_modes, molecule["symbols"])
        except Exception:
            reduced_mass_amu = None
    summary = {
        **freq_summary,
        "ir_intensities_km_mol": ir if len(ir) == len(freqs) else None,
        "normal_modes": normal_modes,
        "reduced_mass_amu": reduced_mass_amu,
        "thermochemistry_note": (
            "BAGEL's Hessian module does not compute zero-point energy/enthalpy/Gibbs free "
            "energy/entropy in this app -- frequencies and IR intensities only."
        ),
        "dx_bohr": meta["dx"] if meta else None,
        "df_basis_used": meta["df_basis"] if meta else None,
        "df_basis_exact_match": meta["df_basis_exact_match"] if meta else None,
    }
    if method in ("casscf", "caspt2"):
        state_energies = _parse_caspt2_energies(output) if method == "caspt2" else _parse_casscf_energies(
            output, n_states,
        )
        summary["method"] = method
        summary["active_electrons"] = params.get("active_electrons")
        summary["active_orbitals"] = params.get("active_orbitals")
        summary["n_states"] = n_states
        freq_state_energies = [state_energies.get(i) for i in range(n_states)]
        summary["state_energies_hartree"] = freq_state_energies
        summary["excitation_energies_eV"] = _excitation_energies_eV(freq_state_energies)
    return summary


def run_frequency(molecule: dict, params: dict) -> dict:
    """Numerical Hessian via central gradient differences. HF reference:
    real water/HF/STO-3G run verified the frequencies land in the same
    ballpark as PySCF/ORCA's analytic Hessian for the same system
    (~2000-4800 cm-1 range), as expected for a different but comparable
    numerical method. CASSCF/CASPT2 reference (method='casscf'/'caspt2',
    see _build_input's nested-method-array "hessian" branch): the same
    _HESSIAN_FREQ_ROW/_HESSIAN_IR_ROW/_normal_modes_bagel parsers apply
    unchanged, since BAGEL's Hessian output format doesn't depend on the
    underlying wavefunction method, only on the numerical-Hessian module
    itself.

    Unlike PySCF/ORCA, BAGEL's Hessian module does not print
    zero-point-energy/enthalpy/Gibbs/entropy thermochemistry -- omitted
    from the summary (via thermochemistry_note) rather than fabricated."""
    job_dir = params["_job_dir"]
    input_text, meta = _effective_input_text(molecule, params, "frequency")
    output = _run_bagel(job_dir, input_text, params)

    def build_summary():
        summary = _frequency_summary(output, molecule, params, meta)
        if params.get("method", "hf") in ("casscf", "caspt2"):
            return summary, _add_orbital_table(summary, job_dir)
        return summary, None

    summary, molden_path = _safe_parse(build_summary, output, job_dir, "frequency")
    artifacts = {"raw_output": os.path.join(job_dir, "bagel.out")}
    if molden_path:
        artifacts["molden"] = molden_path
    return {"summary": summary, "artifacts": artifacts}


def run_opt_freq(molecule: dict, params: dict) -> dict:
    """Genuine single-input optimize+hessian (Phase 6) -- ONE BAGEL process
    runs the "optimize" block, then the "hessian" block on its result, in
    the same input (see _build_input's opt_freq branch). Live-verified on
    water/svp for BOTH casscf and caspt2 (not casscf alone -- CASPT2 goes
    through a structurally different branch, the smith-wrapped Form 1
    entries, and a first attempt at this DID silently run CASSCF instead
    of the requested CASPT2, because `_build_input`'s own smith_block
    condition -- which decides whether the shared `gradient_entries` gets
    the CASPT2 smith-wrapped form at all -- listed "geometry_optimization"/
    "frequency"/"gradient"/"nac" but not the new "opt_freq", so a
    method='caspt2' opt_freq request silently built a plain CASSCF
    optimize+hessian input with no error. Caught because the CASPT2 run's
    frequencies came back numerically IDENTICAL to a separate CASSCF run
    on the same system, and because `_parse_caspt2_energies` then found
    nothing to parse (there was no CASPT2 output to find) -- not caught by
    "it ran without error", which is exactly why this app verifies against
    real output rather than exit status. Fixed by adding "opt_freq" to
    that condition; re-verified after the fix that CASPT2's own frequencies
    are genuinely distinct from CASSCF's on the same system.

    Also confirmed live: opt.molden (the optimized-geometry file
    `_geometry_optimization_summary` reads) is still written when a
    "hessian" block follows "optimize" in the same input; the Hessian's
    own numerical-displacement macro-iterations, appended after the
    optimization's in the same output text, do not disturb
    `_parse_casscf_energies`/`_parse_caspt2_energies`'s last-occurrence-
    wins convention, since that still resolves to the Hessian's own final
    (undisplaced, reference) point -- confirmed by the optimization and
    frequency stages' independently-parsed energies matching exactly, for
    both methods; and each frequency-specific block (Freq (cm-1) rows, the
    cartesian eigenvector section) appears in exactly the shape
    `_frequency_summary` already expects.

    Previously two sequential BAGEL processes -- replaced outright rather
    than kept as a fallback, per this project's no-parallel-mechanisms
    principle: reusing the same two parsers against one real combined run
    is not a new mechanism, just a new caller. BAGEL's own opt_freq still
    requires method='casscf'/'caspt2' (see _build_input's guard, same as
    plain geometry_optimization) -- no plain HF/DFT opt+freq on BAGEL in
    this app."""
    job_dir = params["_job_dir"]
    input_text, meta = _effective_input_text(molecule, params, "opt_freq")
    output = _run_bagel(job_dir, input_text, params)

    def build_summary():
        opt_summary = _geometry_optimization_summary(output, job_dir, molecule, params, meta)
        optimized_molecule = opt_summary.get("optimized_molecule")
        if not optimized_molecule:
            raise RuntimeError("geometry optimization did not converge to a usable optimized geometry")
        freq_summary = _frequency_summary(output, optimized_molecule, params, meta)
        summary = dict(freq_summary)
        summary["optimized_molecule"] = optimized_molecule
        summary["optimization_final_energy_hartree"] = opt_summary.get("final_energy_hartree")
        summary["dominant_transitions"] = opt_summary.get("dominant_transitions")
        return summary, _add_orbital_table(summary, job_dir)

    summary, molden_path = _safe_parse(build_summary, output, job_dir, "opt_freq")
    artifacts = {"raw_output": os.path.join(job_dir, "bagel.out")}
    if molden_path:
        artifacts["molden"] = molden_path
    if os.path.exists(os.path.join(job_dir, "opt.molden")):
        artifacts["optimized_geometry_molden"] = os.path.join(job_dir, "opt.molden")
    return {"summary": summary, "artifacts": artifacts}


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
    output = _run_bagel(job_dir, input_text, params)

    def build_summary():
        from app.chemistry.jobs import molden as molden_tools

        molden_path = os.path.join(job_dir, "orbitals.molden")
        if not os.path.exists(molden_path):
            raise RuntimeError("BAGEL did not produce the expected orbitals.molden file")

        table = molden_tools.orbital_table(molden_path)
        try:
            for row, char_row in zip(table, molden_tools.orbital_character(molden_path)):
                row.update(char_row)
        except Exception:
            pass
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
