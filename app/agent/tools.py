"""Tools exposed to the LLM. Each tool either mutates graph state via
`Command(update=...)` (molecule/job tracking) or just returns a string the
LLM incorporates into its reply (status/result lookups).

Job submission never blocks: `submit_job` calls `JobManager.submit`, which
hands the work to a background subprocess and returns a job_id
immediately. The agent's job is to gather correct parameters and dispatch;
polling for completion is the frontend's/job_watcher's responsibility, not
the graph's -- a node that awaited `status == completed` would freeze the
whole chat turn for the entire calculation.

`submit_job` additionally pauses via `interrupt()` after building the job
spec and before actually running anything, so the user can see the exact
input and approve or reject it -- see its docstring and the module-level
note below for why the pre-interrupt code path has to stay free of
side effects that aren't safe to repeat.
"""
from __future__ import annotations

import json
import random
import uuid
from typing import Annotated, Optional

from langchain_core.messages import ToolMessage
from langchain_core.tools import InjectedToolCallId, StructuredTool, tool
from pydantic import BaseModel, ConfigDict
from langgraph.prebuilt import InjectedState
from langgraph.types import Command, interrupt

from app.agent.scholar_search import search_academic_literature
from app.agent.state import AgentState
from app.agent.web_search import web_search
from app.chemistry.registry2.elicitation import (
    format_keyword_options, keyword_options_for, validate_draft,
)
from app.chemistry.registry2.lookup import (
    capability_answer, describe_engine, resolve_method, resolve_task,
)
from app.chemistry.jobs import interpolate
from app.chemistry.jobs.base import (
    ENSEMBLE_ONLY_PARAM_KEYS, JobSpec, SCAN_ONLY_PARAM_KEYS, get_job_manager, read_meta,
    read_spec, result_artifact_transaction, sub_job_ids_of, write_meta,
)
from app.chemistry.jobs.ensemble_spectrum import pool_ensemble_transitions
from app.chemistry.jobs.keyword_suggest import suggest_basis_options, suggest_functional_options
from app.chemistry.jobs.param_normalize import normalize_basis, normalize_method
from app.chemistry.jobs.preview import build_input_preview
from app.chemistry.jobs.registry import (
    METHODS, PARAM_HELP, default_engine, missing_required_params,
)
from app.chemistry.jobs.naming import auto_job_name
from app.chemistry.jobs.summarize import job_context_summary
from app.chemistry.jobs.validate import (
    SEVERITY_ERROR,
    SEVERITY_WARNING,
    VALIDATED_ENGINES,
    classify_findings,
    validate_input,
)
from app.chemistry.jobs.wigner import sample_from_source_job
from app.chemistry.molecule import resolve_molecule
from app.chemistry.spectrum import (
    render_ir_spectrum_plot, render_job_comparison_plot, render_uvvis_plot, render_wigner_ensemble_spectrum,
)
from app.config import JOBS_DIR
from app.rag.query_tool import search_knowledge_base
from app.rag.store import get_store


def _resolve_or_error(identifier: str, charge: Optional[int], multiplicity: Optional[int]):
    """Returns (molecule_dict, description) on success or (None, error_str) on failure."""
    try:
        m = resolve_molecule(identifier, charge=charge, multiplicity=multiplicity)
    except Exception as e:
        return None, f"Could not resolve '{identifier}': {e}"
    desc = (
        f"Resolved '{identifier}' to {m.name} (SMILES: {m.smiles}), "
        f"charge={m.charge}, multiplicity={m.multiplicity}, {len(m.symbols)} atoms."
    )
    return m.to_dict(), desc


def _make_frame(molecule: dict, identifier: str) -> dict:
    """Builds one molecule_frames entry (see state.py) for a molecule that
    was just resolved via set_molecule or generate_job_input's inline
    resolution -- the only two call sites that ever put a user-provided
    molecule into state (submit_job deliberately never resolves one
    itself, and set_pes_scan_endpoint writes to a separate slot for a
    scan's second geometry, not the frame history). The description is a
    short label for the panel's frame chip/slider, not the longer sentence
    _resolve_or_error already built for the chat transcript -- in
    particular a pasted XYZ block's `identifier` is the whole verbatim
    coordinate text, which would make an unreadable chip label, so that
    case is summarized by atom count instead of quoted.
    """
    source = molecule.get("source")
    if source == "xyz_paste":
        description = f"Pasted XYZ ({len(molecule.get('symbols', []))} atoms)"
    elif source == "smiles":
        label = identifier if len(identifier) <= 40 else identifier[:37] + "..."
        description = f"SMILES: {label}"
    else:
        name = molecule.get("name") or identifier
        description = name if len(name) <= 60 else name[:57] + "..."
    return {"id": uuid.uuid4().hex, "molecule": molecule, "description": description}


def _kb_context_for_job(engine: str, job_type: str, params: dict, k: int = 3) -> str:
    """Mechanically queries the manuals/reference-docs knowledge base for
    the engine + job_type + method/functional/basis being prepared, so
    grounding excerpts are retrieved on every input-prep call rather than
    only when the LLM happens to decide to call search_knowledge_base
    itself. This was previously 100% LLM-discretionary (a soft prompt
    instruction, nothing structural), and a malformed PySCF basis string
    ("6-31gd" instead of "6-31g(d)"/"6-31g*") slipped through uncaught as
    a direct result -- see CLAUDE.md. Filtered to doc_type='manual' since
    the goal is software keyword/syntax grounding, not the molecular
    background uploaded papers cover. Best-effort: returns "" (not an
    error) on an empty/unreachable store, since a KB miss shouldn't block
    job preparation, only leave it ungrounded.
    """
    terms = [engine, job_type, params.get("method"), params.get("functional"), params.get("basis")]
    query = " ".join(str(t) for t in terms if t)
    try:
        results = get_store().similarity_search(query, k=k, filter={"doc_type": "manual"})
    except Exception:
        return ""
    if not results:
        return ""
    return "\n\n".join(f"[{doc.metadata.get('source', 'unknown')}] {doc.page_content[:400]}" for doc in results)



def _keyword_options_for_job(job_type: str, params: dict, engine: str) -> Optional[dict]:
    """v1-shaped wrapper over `registry2.elicitation.keyword_options_for`.

    The menu itself now lives in registry2, because the draft flow needs it
    and having two implementations of "which basis names look like this
    one" is how they drift apart. This wrapper survives only for the
    builders below, which still speak the v1 taxonomy until P2.6 retires
    them: `job_type == "tddft"` was the legacy way of saying "the
    functional is the real choice here", which in v2 is simply
    `method == "dft"`.
    """
    method = "dft" if (job_type == "tddft" or params.get("method") == "dft") else params.get("method")
    return keyword_options_for(engine, method, params)

def _build_scan_images(params: dict) -> tuple[list[dict], list[float], str]:
    """Builds the full list of per-image geometries for a pes_scan, from
    whichever mode params describes -- a second endpoint geometry
    (params['_end_molecule'], two-molecule interpolation via
    interpolate.build_path) or a single-molecule bond/angle/dihedral scan
    (params['coordinate']/['scan_range'], via pyscf_runner's existing
    RDKit-based _internal_coordinate_scan). Reads the scan's true starting
    geometry from params['_scan_start_molecule'] (stashed there by
    whichever caller built this params dict) rather than taking a separate
    molecule argument, specifically so this same function works
    identically both before submit_job's interrupt() (building the
    preview) and after approval (rebuilding the exact same images to
    actually submit) -- both call sites pass the SAME params dict shape,
    the second one having round-tripped through the interrupt/resume
    boundary intact (see submit_job's docstring on why nothing here must
    depend on anything besides state/args that are identical both times).
    """
    molecule = params["_scan_start_molecule"]
    n_points = params["n_points"]
    end_molecule = params.get("_end_molecule")
    if end_molecule:
        method = params.get("interpolation_method") or "idpp"
        images = interpolate.build_path(molecule, end_molecule, n_points, method)
        coordinate_values = [i / (n_points - 1) for i in range(n_points)] if n_points > 1 else [0.0]
        coordinate_label = f"interpolation_fraction ({method})"
    elif params.get("coordinate") and params.get("scan_range"):
        # Deferred import: pyscf_runner pulls in pyscf/rdkit at module
        # load, so it's only imported when actually needed -- same
        # convention app/chemistry/jobs/preview.py already follows for the
        # same reason.
        from app.chemistry.jobs.pyscf_runner import build_coordinate_scan_images
        images, coordinate_values = build_coordinate_scan_images(
            molecule, params["coordinate"], params["scan_range"], n_points,
        )
        coord = params["coordinate"]
        coordinate_label = f"{coord['type']}({','.join(str(a) for a in coord['atoms'])})"
    else:
        raise ValueError(
            "pes_scan needs either a second endpoint geometry (call set_pes_scan_endpoint for the 'end' "
            "structure, in addition to set_molecule for the 'start' structure) or both 'coordinate' and "
            "'scan_range' for a single-molecule bond/angle/dihedral scan"
        )
    return images, [float(v) for v in coordinate_values], coordinate_label


def _build_scan_spec_or_error(molecule: dict, engine: Optional[str], params: dict, param_notes: list[str]):
    """pes_scan-specific half of _build_spec_or_error: validates both
    pes_scan's own required params and its scan_job_type's own required
    params (reusing missing_required_params for each rather than
    duplicating either contract), builds the full image list, and returns
    a "master" JobSpec (method='pes_scan', molecule=images[0] as a sane
    single-geometry fallback for generic molecule viewers) whose preview
    is image 0's own sub-job input -- per the approval-card design, only
    the first image's input is shown, since every other image uses
    identical parameters against a different geometry."""
    params["_scan_start_molecule"] = molecule
    missing = missing_required_params("pes_scan", params)
    if missing:
        needs = "; ".join(f"{p} ({PARAM_HELP.get(p, 'no description')})" for p in missing)
        return None, None, None, None, None, None, [], (
            f"Cannot prepare this 'pes_scan' job yet -- still missing: {needs}. "
            f"Ask the user for these specifically; do not assume default values for them."
        )

    scan_job_type = params["scan_job_type"]
    if scan_job_type not in METHODS or scan_job_type == "pes_scan":
        valid = [m for m in METHODS if m != "pes_scan"]
        return None, None, None, None, None, None, [], f"scan_job_type must be one of {valid} (not 'pes_scan' itself)"

    # Checked before scan_job_type's own required params below, since
    # neither of those params matters at all until it's clear which of
    # the two scan modes (two endpoints vs. one coordinate) is even being
    # requested -- surfacing "still missing: method, basis" first would be
    # a confusing thing to ask the user when the more fundamental problem
    # is that no scan path has been described at all yet.
    has_endpoint = bool(params.get("_end_molecule"))
    has_coordinate = bool(params.get("coordinate") and params.get("scan_range"))
    if not has_endpoint and not has_coordinate:
        return None, None, None, None, None, None, [], (
            "pes_scan needs either a second endpoint geometry (call set_pes_scan_endpoint for the 'end' "
            "structure, in addition to set_molecule for the 'start' structure) or both 'coordinate' and "
            "'scan_range' for a single-molecule bond/angle/dihedral scan. Ask the user which they want."
        )

    sub_params = {k: v for k, v in params.items() if k not in SCAN_ONLY_PARAM_KEYS and not k.startswith("_")}
    sub_missing = missing_required_params(scan_job_type, sub_params)
    if sub_missing:
        needs = "; ".join(f"{p} ({PARAM_HELP.get(p, 'no description')})" for p in sub_missing)
        return None, None, None, None, None, None, [], (
            f"Cannot prepare this pes_scan (scan_job_type='{scan_job_type}') yet -- still missing: {needs}. "
            f"Ask the user for these specifically; do not assume default values for them."
        )

    try:
        images, coordinate_values, coordinate_label = _build_scan_images(params)
    except ValueError as e:
        return None, None, None, None, None, None, [], str(e)

    try:
        resolved_engine = default_engine(scan_job_type, engine, sub_params)
    except ValueError as e:
        return None, None, None, None, None, None, [], str(e)

    spec = JobSpec(method="pes_scan", engine=resolved_engine, molecule=images[0], params=params)
    try:
        preview_spec = JobSpec(method=scan_job_type, engine=resolved_engine, molecule=images[0], params=sub_params)
        preview = build_input_preview(preview_spec)
    except Exception as e:
        return None, None, None, None, None, None, [], f"Could not build the input for this scan's first image: {e}"
    # Kept OUT of `preview` itself -- `preview` doubles as the literal
    # editable/raw-input text on the approval card for orca/bagel (see
    # submit_job's docstring: an edit is written verbatim to _raw_input
    # and used byte-identical by the worker). A bracketed English
    # annotation prepended there would have been valid neither ORCA nor
    # BAGEL syntax, and previously WAS being submitted verbatim as image
    # 0's actual input whenever the approval card's own "editable text
    # defaults to the shown preview" bug (now fixed, see JobApprovalCard)
    # sent that text back unedited -- confirmed via a real failed ORCA
    # CASSCF scan job whose input.inp literally began with "[Preview of
    # image 1 of 6 ...]" as line 1. Surfaced separately as `scan_note`
    # instead, for display only.
    scan_note = (
        f"Preview of image 1 of {len(images)} along the scan -- every other image uses these exact same "
        f"parameters against a different geometry."
    )

    kb_context = _kb_context_for_job(resolved_engine, scan_job_type, sub_params)
    keyword_options = _keyword_options_for_job(scan_job_type, sub_params, resolved_engine)
    return spec, preview, kb_context, param_notes, scan_note, keyword_options, [], None


def _build_neb_ts_spec_or_error(molecule: dict, engine: Optional[str], params: dict, param_notes: list[str]):
    """neb_ts-specific half of _build_spec_or_error: reactant is the
    active `molecule` (same as every other job_type), product comes from
    params['_end_molecule'] (set by _build_spec_or_error from `end_molecule`,
    which both generate_job_input/submit_job source from
    state['pes_scan_end_molecule'] -- same second-endpoint-geometry slot
    pes_scan's two-molecule mode uses, via the same set_pes_scan_endpoint
    tool call; there is no NEB-specific endpoint tool). Unlike pes_scan,
    NEB-TS is a single ORCA job (ORCA parallelizes the path images itself
    via %pal), so this returns one ordinary JobSpec, not a "master" one."""
    missing = missing_required_params("neb_ts", params)
    if missing:
        needs = "; ".join(f"{p} ({PARAM_HELP.get(p, 'no description')})" for p in missing)
        return None, None, None, None, None, None, [], (
            f"Cannot prepare this 'neb_ts' job yet -- still missing: {needs}. "
            f"Ask the user for these specifically; do not assume default values for them."
        )

    end_molecule = params.get("_end_molecule")
    if not end_molecule:
        return None, None, None, None, None, None, [], (
            "neb_ts needs a product (end) geometry -- call set_pes_scan_endpoint for it (in addition to "
            "set_molecule for the reactant), then call this again."
        )
    if len(end_molecule.get("symbols", [])) != len(molecule.get("symbols", [])):
        return None, None, None, None, None, None, [], (
            "The reactant and product geometries have different atom counts -- they must be the same "
            "molecule (same atoms, same order), just different conformations. Ask the user to check "
            "the product structure."
        )

    target_state = params.get("target_state")
    if target_state:
        params["n_states"] = max(params.get("n_states") or 0, target_state)

    try:
        resolved_engine = default_engine("neb_ts", engine, params)
    except ValueError as e:
        return None, None, None, None, None, None, [], str(e)

    spec = JobSpec(method="neb_ts", engine=resolved_engine, molecule=molecule, params=params)
    try:
        preview = build_input_preview(spec)
    except Exception as e:
        return None, None, None, None, None, None, [], f"Could not build the input for this job: {e}"

    kb_context = _kb_context_for_job(resolved_engine, "neb_ts", params)
    keyword_options = _keyword_options_for_job("neb_ts", params, resolved_engine)
    return spec, preview, kb_context, param_notes, None, keyword_options, [], None


# Hard v1 ceiling on wigner_ensemble's n_samples -- enforced here rather
# than as a static registry.py check (missing_required_params has no
# concept of "present but out of range"), same reason the CASSCF/CASPT2
# active_electrons/active_orbitals cross-field check below also lives in
# this module instead of registry.py. Sub-jobs are wave-dispatched (see
# JobManager.submit_ensemble), not submitted all at once, but a single
# ensemble still shouldn't grow past what this app's quota/concurrency
# machinery was designed around.
_MAX_ENSEMBLE_SAMPLES = 250

# tddft/eom_ccsd always report oscillator strengths by default (or, for
# eom_ccsd, default to engine='orca', which does); casscf/caspt2 do not,
# on any engine, unless want_oscillator_strengths is explicitly set --
# see _build_ensemble_spec_or_error's auto-forcing of that flag for these
# two methods specifically.
_ENSEMBLE_JOB_TYPES_NEEDING_OSC_FORCE = {"casscf", "caspt2"}
_ALLOWED_ENSEMBLE_JOB_TYPES = {"tddft", "casscf", "eom_ccsd", "caspt2"}


def _build_ensemble_spec_or_error(molecule: dict, engine: Optional[str], params: dict, param_notes: list[str]):
    """wigner_ensemble-specific half of _build_spec_or_error: validates
    wigner_ensemble's own required params and n_samples' hard ceiling,
    reads the tagged source_frequency_job_id job directly off disk (a
    genuinely new kind of cross-reference for this app -- every other
    job_type reads its input molecule from AgentState, but this refers to
    a DIFFERENT, already-completed job, so it must be read via read_spec/
    mgr.result rather than state), Wigner-samples the full n_samples set
    from it (used here only to build a representative preview -- sample 0
    -- mirroring _build_scan_spec_or_error's "preview is image 0" design;
    the actual submission-time sample set is regenerated fresh, from the
    same round-tripped random_seed, inside submit_job's post-approval
    dispatch, exactly as pes_scan's own _build_scan_images is), validates
    scan_job_type's own required params, auto-forces
    want_oscillator_strengths for casscf/caspt2 scan_job_type (mirroring
    default_engine's existing CASSCF-to-ORCA auto-route -- without this, a
    casscf/caspt2-based ensemble would silently pool zero usable
    intensity), and returns a "master" JobSpec whose own `molecule` is the
    source frequency job's EQUILIBRIUM geometry (not any sampled/displaced
    one) -- unlike pes_scan's images[0] convention, so the molecule
    viewer/geometry button shows the actual structure the normal modes
    were computed from, which is the only geometry with an unambiguous
    claim to being "the" molecule for this master job.

    random_seed is generated here (if the caller didn't supply one) and
    written into `params` BEFORE this function returns -- i.e. before
    submit_job's interrupt() call -- so it round-trips through
    approved_spec.params intact. This is the one place this function
    cannot safely mirror _build_scan_spec_or_error's shape verbatim:
    submit_job's post-approval code re-executes everything before
    interrupt() on resume (existing, documented LangGraph behavior this
    codebase already works around elsewhere -- see CLAUDE.md's submit_job
    architecture note), and _build_scan_images is safe to call twice
    because it's purely deterministic geometry math, but Wigner sampling
    draws random numbers -- without a fixed, round-tripped seed, the
    ensemble a human approves on the card would not be the ensemble that
    actually runs after approval."""
    missing = missing_required_params("wigner_ensemble", params)
    if missing:
        needs = "; ".join(f"{p} ({PARAM_HELP.get(p, 'no description')})" for p in missing)
        return None, None, None, None, None, None, [], (
            f"Cannot prepare this 'wigner_ensemble' job yet -- still missing: {needs}. "
            f"Ask the user for these specifically; do not assume default values for them."
        )

    n_samples = params["n_samples"]
    if not isinstance(n_samples, int) or n_samples < 1 or n_samples > _MAX_ENSEMBLE_SAMPLES:
        return None, None, None, None, None, None, [], (
            f"n_samples must be an integer between 1 and {_MAX_ENSEMBLE_SAMPLES} (got {n_samples!r})."
        )

    scan_job_type = params["scan_job_type"]
    if scan_job_type not in _ALLOWED_ENSEMBLE_JOB_TYPES:
        return None, None, None, None, None, None, [], (
            f"scan_job_type must be one of {sorted(_ALLOWED_ENSEMBLE_JOB_TYPES)} for wigner_ensemble "
            f"(these are the job types that can report per-transition oscillator strengths -- other job "
            f"types have no excitation data for this feature to pool)."
        )

    source_id = params.get("source_frequency_job_id")
    source_spec = read_spec(source_id) if source_id else None
    if source_spec is None:
        return None, None, None, None, None, None, [], f"No such job: source_frequency_job_id='{source_id}'."
    # A plain "frequency" job's own molecule IS the equilibrium geometry
    # (it computes a Hessian at whatever geometry it was given, assumed
    # already a minimum) -- but "opt_freq" (geometry optimization followed
    # by frequency at the optimized geometry, see pyscf/orca/bagel_runner's
    # run_opt_freq) starts from a possibly-far-from-equilibrium input
    # geometry, so its own spec.molecule would be the WRONG starting point
    # to Wigner-sample around; the actual equilibrium geometry there is
    # summary['optimized_molecule'] instead.
    if source_spec.get("method") not in ("frequency", "opt_freq"):
        return None, None, None, None, None, None, [], (
            f"source_frequency_job_id='{source_id}' is a '{source_spec.get('method')}' job, not a "
            f"'frequency' or 'opt_freq' job -- wigner_ensemble needs a completed frequency calculation's "
            f"normal modes to sample from."
        )
    mgr = get_job_manager()
    source_result = mgr.result(source_id)
    if source_result is None or source_result.get("status") != "completed":
        return None, None, None, None, None, None, [], (
            f"source_frequency_job_id='{source_id}' is not a completed job yet -- check its status "
            f"before requesting an ensemble from it."
        )
    source_summary = source_result.get("summary") or {}
    # Gated on normal_modes, NOT on the summary's own reduced_mass_amu:
    # sample_from_source_job recomputes reduced masses from the modes and the
    # molecule's symbols every time (see its docstring for why trusting a
    # stored value is actively unsafe), so the modes are the only thing that
    # genuinely has to be there. This deliberately lets a frequency job that
    # predates the reduced_mass_amu field be used as an ensemble source
    # rather than making the user re-run a finished, possibly hours-long
    # calculation for a number derivable from what it already recorded.
    if not source_summary.get("normal_modes"):
        return None, None, None, None, None, None, [], (
            f"source_frequency_job_id='{source_id}' has no normal_modes in its summary, so there are no "
            f"vibrational modes to Wigner-sample along. This happens when the engine's normal-mode "
            f"output could not be parsed for that job; re-running the frequency calculation is the fix."
        )
    if source_spec.get("method") == "opt_freq":
        equilibrium_molecule = source_summary.get("optimized_molecule")
        if not equilibrium_molecule:
            return None, None, None, None, None, None, [], (
                f"source_frequency_job_id='{source_id}' (an opt_freq job) has no optimized_molecule in "
                f"its summary -- cannot determine the equilibrium geometry to sample around."
            )
    else:
        equilibrium_molecule = source_spec["molecule"]

    if not params.get("random_seed"):
        params["random_seed"] = random.SystemRandom().randint(0, 2**31 - 1)

    if scan_job_type in _ENSEMBLE_JOB_TYPES_NEEDING_OSC_FORCE and not params.get("want_oscillator_strengths"):
        params["want_oscillator_strengths"] = True
        param_notes.append(
            f"want_oscillator_strengths was automatically set True for the per-sample {scan_job_type} "
            f"sub-jobs -- otherwise none of them would report any oscillator strength for the ensemble "
            f"spectrum to pool (only ORCA computes this for casscf; only BAGEL's forces+dipole mechanism "
            f"computes it for caspt2)."
        )

    sub_params = {k: v for k, v in params.items() if k not in ENSEMBLE_ONLY_PARAM_KEYS and not k.startswith("_")}
    sub_missing = missing_required_params(scan_job_type, sub_params)
    if sub_missing:
        needs = "; ".join(f"{p} ({PARAM_HELP.get(p, 'no description')})" for p in sub_missing)
        return None, None, None, None, None, None, [], (
            f"Cannot prepare this wigner_ensemble (scan_job_type='{scan_job_type}') yet -- still missing: "
            f"{needs}. Ask the user for these specifically; do not assume default values for them."
        )

    try:
        resolved_engine = default_engine(scan_job_type, engine, sub_params)
    except ValueError as e:
        return None, None, None, None, None, None, [], str(e)

    try:
        samples, diagnostics = sample_from_source_job(
            equilibrium_molecule, source_summary, n_samples=n_samples,
            random_seed=params["random_seed"], low_freq_cutoff_cm1=params.get("low_freq_cutoff_cm1", 100.0),
            temperature_K=params.get("temperature_K", 0.0),
        )
    except ValueError as e:
        return None, None, None, None, None, None, [], str(e)

    if diagnostics["n_modes_imaginary_dropped"] or diagnostics["n_modes_dropped_low_freq"]:
        param_notes.append(
            f"{diagnostics['n_modes_imaginary_dropped']} imaginary and "
            f"{diagnostics['n_modes_dropped_low_freq']} low-frequency (<{diagnostics['low_freq_cutoff_cm1']} "
            f"cm-1) mode(s) were excluded from Wigner sampling ({diagnostics['n_modes_retained']} of "
            f"{diagnostics['n_modes_total']} modes retained)."
        )

    spec = JobSpec(method="wigner_ensemble", engine=resolved_engine, molecule=equilibrium_molecule, params=params)
    try:
        preview_spec = JobSpec(method=scan_job_type, engine=resolved_engine, molecule=samples[0], params=sub_params)
        preview = build_input_preview(preview_spec)
    except Exception as e:
        return None, None, None, None, None, None, [], f"Could not build the input for a representative sample: {e}"

    scan_note = (
        f"Preview of a representative Wigner-sampled geometry (sample 1 of {n_samples}, drawn from "
        f"'{source_id}''s normal modes) -- every other sample uses these exact same calculation "
        f"parameters against a different displaced geometry."
    )

    kb_context = _kb_context_for_job(resolved_engine, scan_job_type, sub_params)
    keyword_options = _keyword_options_for_job(scan_job_type, sub_params, resolved_engine)
    return spec, preview, kb_context, param_notes, scan_note, keyword_options, [], None


def _build_spec_or_error(
    job_type: str, molecule: dict, engine: Optional[str], raw_params: dict, end_molecule: Optional[dict] = None,
):
    """Shared by generate_job_input and submit_job: normalizes the qc_method/
    basis parameters, validates required params, resolves the engine,
    builds the JobSpec, renders its input preview, and looks up manual/
    reference-doc context for it, and computes the basis/method-keyword
    disambiguation menu (see keyword_suggest.py). Returns
    (spec, preview_text, kb_context, param_notes, scan_note, keyword_options, warnings, error_str) --
    exactly one of (spec, preview_text, kb_context, param_notes, keyword_options, warnings) / error_str
    is populated (param_notes/warnings are always lists, possibly empty; keyword_options is
    a dict or None). scan_note
    is only ever populated for a pes_scan job (display-only context about
    which image the preview shows) -- kept OUT of preview_text itself since
    that string doubles as the literal raw-input text an editable-engine
    approval card round-trips back verbatim (see submit_job's docstring).
    warnings is only ever populated for a job_type='custom' job (non-blocking
    structural-validation complaints about the agent-composed raw_input_text --
    see _build_custom_spec_or_error).
    """
    if job_type not in METHODS:
        return None, None, None, None, None, None, [], f"Unknown job_type '{job_type}'. Valid options: {', '.join(METHODS)}"

    params = {k: v for k, v in raw_params.items() if v is not None}
    if end_molecule is not None:
        params["_end_molecule"] = end_molecule
    # Not a real registry param for any job_type -- only ever consumed by
    # _build_custom_spec_or_error below -- so it's popped here rather than
    # left to show up as a stray key in spec.params/the approval card's
    # flat params line for every other job_type.
    calculation_description = params.pop("calculation_description", None)

    # Mechanical typo/formatting correction -- see param_normalize.py's
    # module docstring. Runs before missing_required_params so a corrected
    # value is what actually gets validated as present/absent below.
    param_notes: list[str] = []
    if "method" in params:
        params["method"], note = normalize_method(params["method"])
        if note:
            param_notes.append(note)
    if "basis" in params:
        params["basis"], note = normalize_basis(params["basis"])
        if note:
            param_notes.append(note)

    if job_type == "pes_scan":
        return _build_scan_spec_or_error(molecule, engine, params, param_notes)

    if job_type == "neb_ts":
        return _build_neb_ts_spec_or_error(molecule, engine, params, param_notes)

    if job_type == "wigner_ensemble":
        return _build_ensemble_spec_or_error(molecule, engine, params, param_notes)

    if job_type == "custom":
        return _build_custom_spec_or_error(engine, molecule, params, param_notes, calculation_description)

    missing = missing_required_params(job_type, params)
    if missing:
        needs = "; ".join(f"{p} ({PARAM_HELP.get(p, 'no description')})" for p in missing)
        return None, None, None, None, None, None, [], (
            f"Cannot prepare this '{job_type}' job yet -- still missing: {needs}. "
            f"Ask the user for these specifically; do not assume default values for them."
        )

    # registry.py's static REQUIRED_PARAMS can't express "active_electrons/
    # active_orbitals are required, but only when method is casscf/caspt2"
    # -- geometry_optimization/frequency are otherwise HF/DFT-only (no CAS
    # params at all). Mirrors the exact "ask, don't guess" pattern
    # _build_scan_spec_or_error/_build_neb_ts_spec_or_error already use for
    # their own cross-field requirements.
    if job_type in ("geometry_optimization", "frequency", "opt_freq") and params.get("method") in ("casscf", "caspt2"):
        cas_missing = [p for p in ("active_electrons", "active_orbitals") if params.get(p) is None]
        if cas_missing:
            needs = "; ".join(f"{p} ({PARAM_HELP.get(p, 'no description')})" for p in cas_missing)
            return None, None, None, None, None, None, [], (
                f"Cannot prepare this '{job_type}' job with method='{params['method']}' yet -- still "
                f"missing: {needs}. Ask the user for these specifically; do not assume default values."
            )

    try:
        resolved_engine = default_engine(job_type, engine, params)
    except ValueError as e:
        return None, None, None, None, None, None, [], str(e)

    # optimization_type='conical_intersection' is a real BAGEL-only
    # mechanism (opttype='conical' on the same 'optimize' title) -- ORCA's
    # equivalent (%mecp) is a separate, unimplemented module and pyscf/
    # geomeTRIC has no native multi-state crossing-point mode at all, so
    # this is rejected explicitly rather than silently ignored on those
    # engines. target_state_2 auto-defaults to a ground/first-excited seam
    # (BAGEL's own target=0/target2=1 defaults) but is always surfaced
    # back into params so it shows on the approval-card preview -- the
    # human should see exactly which two states before approving, per
    # PARAM_HELP's own description of this param.
    if job_type == "geometry_optimization" and params.get("optimization_type") == "conical_intersection":
        if resolved_engine != "bagel":
            return None, None, None, None, None, None, [], (
                "optimization_type='conical_intersection' is only available with engine='bagel' -- "
                "ORCA's conical-intersection search (%mecp) and pyscf/geomeTRIC's optimizer have no "
                "equivalent capability in this app."
            )
        if params.get("target_state_2") is None:
            params["target_state_2"] = (params.get("target_state") or 0) + 1

    spec = JobSpec(method=job_type, engine=resolved_engine, molecule=molecule, params=params)
    try:
        preview = build_input_preview(spec)
    except Exception as e:
        return None, None, None, None, None, None, [], f"Could not build the input for this job: {e}"

    kb_context = _kb_context_for_job(spec.engine, job_type, params)
    keyword_options = _keyword_options_for_job(job_type, params, spec.engine)
    return spec, preview, kb_context, param_notes, None, keyword_options, [], None


def _build_custom_spec_or_error(
    engine: Optional[str], molecule: dict, params: dict, param_notes: list[str],
    calculation_description: Optional[str],
):
    """job_type == 'custom' half of _build_spec_or_error: for an ORCA/BAGEL
    calculation that doesn't map onto any of this app's other registered
    job_types (e.g. an IRC path search, a relaxed surface scan, a
    property calculation this app has no dedicated parser for). The agent
    composes the complete literal input text itself (raw_input_text)
    rather than this app building it from structured params -- there is no
    job-type-specific output parser either, so the result summary is just
    a tail of the raw output (see orca_runner.run_custom/
    bagel_runner.run_custom), and the approval card / JobDetailDrawer show
    only geometry + raw input/output, same as any other job whose summary
    happens to come back minimal.

    Structural validation (validate_input) is run but never blocks here --
    unlike the hand-edit path for a KNOWN job_type (which started from a
    generated, standard-geometry input, so a validation failure there means
    something broke a previously-valid file), a custom job's whole reason
    to exist is to carry ORCA/BAGEL syntax this app's validator was never
    built to recognize (e.g. '* xyzfile' instead of '* xyz', a '%coords'
    block, a multi-job '$new_job' stack). Any validator complaints are
    surfaced as non-blocking warnings instead, on the same card the human
    already has to review before anything runs -- see the `warnings`
    element of the return tuple.
    """
    if engine not in ("orca", "bagel"):
        return None, None, None, None, None, None, [], (
            "A 'custom' job needs an explicit engine of 'orca' or 'bagel' (PySCF has no literal "
            "input-file format for a raw/custom job -- use generate_job_input/submit_job with a specific "
            "job_type for PySCF instead)."
        )

    missing = missing_required_params("custom", params)
    if missing:
        needs = "; ".join(f"{p} ({PARAM_HELP.get(p, 'no description')})" for p in missing)
        return None, None, None, None, None, None, [], f"Cannot prepare this custom job yet -- still missing: {needs}."

    raw_text = params.pop("raw_input_text")
    # F-018: findings are split by what the validator can actually claim --
    # "I didn't find a construct I look for" (weak on a custom input, since
    # the construct may just be one this validator doesn't model) versus
    # "I found this construct and it's malformed" (a positive claim, as
    # true here as on a generated input). See classify_findings' own block
    # comment. Both stay non-blocking, per this function's docstring, but
    # the approval card renders them very differently so a definite defect
    # can no longer be mistaken for routine advisory noise.
    val_errors, val_warnings = classify_findings(engine, raw_text)
    warnings = (
        [{"severity": SEVERITY_ERROR, "message": m} for m in val_errors]
        + [{"severity": SEVERITY_WARNING, "message": m} for m in val_warnings]
    )
    params["_raw_input"] = raw_text

    spec = JobSpec(
        method="custom", engine=engine, molecule=molecule, params=params,
        label=calculation_description or "",
    )
    preview = raw_text

    # A custom job has no method/basis/functional of its own to build a KB
    # query from the way _kb_context_for_job does -- reusing it unmodified
    # would just query "orca custom"/"bagel custom" and surface
    # semantically random manual chunks labeled as grounding. Uses
    # calculation_description instead when the agent supplied one.
    query = f"{engine} {calculation_description}" if calculation_description else engine
    try:
        results = get_store().similarity_search(query, k=3, filter={"doc_type": "manual"})
        kb_context = (
            "\n\n".join(f"[{doc.metadata.get('source', 'unknown')}] {doc.page_content[:400]}" for doc in results)
            if results else ""
        )
    except Exception:
        kb_context = ""

    # No method/basis params on a custom job (see this function's own
    # docstring) -- nothing for _keyword_options_for_job to disambiguate.
    return spec, preview, kb_context, param_notes, None, None, warnings, None


def _collect_params(
    qc_method, basis, functional, active_electrons, active_orbitals, n_states, weights,
    orbital_indices, coordinate_type, coordinate_atoms, scan_range, n_points, ms_caspt2,
    shift, frozen_core, df_basis, max_steps, temperature_K, use_tda, want_oscillator_strengths,
    scan_job_type, interpolation_method, raw_input_text, calculation_description,
    preopt, n_images, target_state, max_active_orbitals, avas_aolabels, literature_notes,
    entropy_method, dmrg_bond_dim, optimization_type, target_state_2,
) -> dict:
    params = {
        "method": qc_method, "basis": basis, "functional": functional,
        "active_electrons": active_electrons, "active_orbitals": active_orbitals,
        "n_states": n_states, "weights": weights, "orbital_indices": orbital_indices,
        "scan_range": scan_range, "n_points": n_points, "ms_caspt2": ms_caspt2,
        "shift": shift, "frozen_core": frozen_core, "df_basis": df_basis,
        "max_steps": max_steps, "temperature_K": temperature_K, "use_tda": use_tda,
        "want_oscillator_strengths": want_oscillator_strengths,
        "scan_job_type": scan_job_type, "interpolation_method": interpolation_method,
        "raw_input_text": raw_input_text, "calculation_description": calculation_description,
        "preopt": preopt, "n_images": n_images, "target_state": target_state,
        "max_active_orbitals": max_active_orbitals, "avas_aolabels": avas_aolabels,
        "literature_notes": literature_notes,
        "entropy_method": entropy_method, "dmrg_bond_dim": dmrg_bond_dim,
        "optimization_type": optimization_type, "target_state_2": target_state_2,
    }
    if coordinate_type and coordinate_atoms:
        params["coordinate"] = {"type": coordinate_type, "atoms": coordinate_atoms}
    return params


def plot_excited_state_spectrum(
    job_id: Optional[str] = None,
    fwhm_eV: Optional[float] = None,
    state: Annotated[AgentState, InjectedState] = None,
) -> str:
    """Generate and display a Gaussian-broadened UV/Vis absorption
    spectrum from a completed excited-state job's excitation energies and
    oscillator strengths (tddft/CIS, eom_ccsd, or a casscf job run with
    want_oscillator_strengths=True). Call this when the user asks to plot,
    graph, or visualize a UV/Vis absorption spectrum. If job_id is
    omitted, uses the most recently submitted job. fwhm_eV controls the
    broadening width (default 0.4 eV, a common convention).

    This refuses (returns an explanatory message, does not fabricate a
    plot) if the job has no usable oscillator strengths -- e.g. an
    eom_ccsd or casscf job run on PySCF, or a caspt2 job, none of which
    compute intensities in this app. Tell the user why in that case (they
    may want to re-run via engine='orca' if that's available for their
    job_type) rather than retrying the plot.
    """
    mgr = get_job_manager()
    active = state.get("active_job_ids", []) if state else []
    target = job_id or (active[-1] if active else None)
    if not target:
        return "No jobs have been submitted yet in this conversation."

    result = mgr.result(target)
    if result is None or result["status"] != "completed":
        return f"Job {target} is not a completed job -- cannot plot a spectrum from it."

    summary = result["summary"]
    energies = summary.get("excitation_energies_eV")
    if not energies:
        return f"Job {target}'s summary has no excitation energies to plot a spectrum from."

    osc = summary.get("oscillator_strengths")
    if not osc or any(o is None for o in osc) or all(o == 0 for o in osc):
        note = summary.get("oscillator_strengths_note", "")
        return (
            f"Job {target} has excitation energies but no usable oscillator strengths -- intensities "
            f"aren't available at this level of theory/engine. {note} Explain this to the user rather "
            f"than plotting a flat/fabricated spectrum."
        )

    out_path = str(JOBS_DIR / target / "uvvis_spectrum.png")
    render_uvvis_plot(energies, osc, fwhm_eV or 0.4, out_path)

    with result_artifact_transaction(target) as artifacts:
        if artifacts is None:
            # Narrow race: the job's result.json existed at the `mgr.result`
            # check above but is gone now (e.g. a concurrent DELETE
            # /api/jobs/{id}). The PNG was still rendered to disk, but with
            # no result.json left to record it in, it's orphaned -- say so
            # rather than claiming success for a plot that was never
            # actually attached to the (now-deleted) job.
            return f"Job {target} was deleted while this plot was being generated; nothing to show."
        artifacts["uvvis_spectrum"] = out_path

    return f"Generated a UV/Vis spectrum plot for job {target}; it is now shown to the user."


def plot_ir_spectrum(
    job_id: Optional[str] = None,
    fwhm_cm1: Optional[float] = None,
    state: Annotated[AgentState, InjectedState] = None,
) -> str:
    """Generate and display a Gaussian-broadened IR (infrared) spectrum
    from a completed frequency job's vibrational frequencies and IR
    intensities. Call this when the user asks to plot, graph, or visualize
    an IR spectrum. If job_id is omitted, uses the most recently submitted
    job. fwhm_cm1 controls the broadening width (default 20 cm-1, a common
    convention for a simulated IR spectrum).

    This refuses (returns an explanatory message, does not fabricate a
    plot) if the job has no usable IR intensities -- PySCF's frequency job
    type computes frequencies/normal modes only, no IR intensities, in
    this app (only ORCA/BAGEL do). Tell the user why in that case (they
    may want to re-run via engine='orca' or engine='bagel') rather than
    retrying the plot.
    """
    mgr = get_job_manager()
    active = state.get("active_job_ids", []) if state else []
    target = job_id or (active[-1] if active else None)
    if not target:
        return "No jobs have been submitted yet in this conversation."

    result = mgr.result(target)
    if result is None or result["status"] != "completed":
        return f"Job {target} is not a completed job -- cannot plot a spectrum from it."

    summary = result["summary"]
    freqs = summary.get("frequencies_cm-1")
    if not freqs:
        return f"Job {target}'s summary has no vibrational frequencies to plot a spectrum from."

    ir = summary.get("ir_intensities_km_mol")
    if not ir or any(i is None for i in ir):
        return (
            f"Job {target} has vibrational frequencies but no usable IR intensities -- PySCF's frequency "
            f"job type doesn't compute them in this app. Explain this to the user rather than plotting a "
            f"flat/fabricated spectrum; re-running with engine='orca' or engine='bagel' would provide them."
        )

    out_path = str(JOBS_DIR / target / "ir_spectrum.png")
    render_ir_spectrum_plot(freqs, ir, fwhm_cm1 or 20.0, out_path)

    with result_artifact_transaction(target) as artifacts:
        if artifacts is None:
            # See plot_excited_state_spectrum's identical comment above --
            # the job's result.json was deleted out from under this call.
            return f"Job {target} was deleted while this plot was being generated; nothing to show."
        artifacts["ir_spectrum"] = out_path

    return f"Generated an IR spectrum plot for job {target}; it is now shown to the user."


# Maps a caller-facing field name to the ordered list of literal summary
# keys that could hold it -- different job types/engines use different
# exact key names for what's conceptually the same quantity (e.g. a
# single_point's "energy_hartree" vs. a geometry_optimization's
# "final_energy_hartree" vs. a casscf job's "casscf_energy_hartree"), so
# each job is checked against every alias in order and the first present,
# non-None value is used. This is still a fixed, enumerated set of known
# keys (verified against the runners in app/chemistry/jobs/*.py) -- not
# free-form fuzzy matching against whatever happens to be in a summary
# dict.
_COMPARISON_FIELD_ALIASES: dict[str, tuple[str, ...]] = {
    "energy": (
        "final_energy_hartree", "energy_hartree", "casscf_energy_hartree", "caspt2_energy_hartree",
        "electronic_energy_hartree",
    ),
    "homo_lumo_gap": ("homo_lumo_gap_eV",),
    "zero_point_energy": ("zero_point_energy_hartree",),
    "enthalpy": ("enthalpy_hartree",),
    "gibbs_free_energy": ("gibbs_free_energy_hartree",),
    "ts_energy": ("ts_energy_hartree",),
}

_COMPARISON_FIELD_LABELS: dict[str, str] = {
    "energy": "Energy (Hartree)",
    "homo_lumo_gap": "HOMO-LUMO gap (eV)",
    "zero_point_energy": "Zero-point energy (Hartree)",
    "enthalpy": "Enthalpy (Hartree)",
    "gibbs_free_energy": "Gibbs free energy (Hartree)",
    "ts_energy": "Transition-state energy (Hartree)",
}


def plot_job_comparison(
    field: str,
    job_ids: Optional[list[str]] = None,
    title: Optional[str] = None,
    state: Annotated[AgentState, InjectedState] = None,
) -> str:
    """Generate and display a bar chart comparing one scalar result field
    across several completed jobs -- e.g. "plot the energies of these
    jobs" or "compare the HOMO-LUMO gaps". Call this whenever the user
    asks to plot/graph/compare/visualize a result across two or more jobs
    they've attached to the conversation (via the Job Manager panel's
    "Attach to prompt" action) or that have otherwise been discussed/run
    in this conversation.

    `field` must be one of: "energy" (final/single-point/CASSCF/CASPT2
    energy, whichever this job type reports), "homo_lumo_gap",
    "zero_point_energy", "enthalpy", "gibbs_free_energy", "ts_energy"
    (a neb_ts job's transition-state energy). This tool does not accept
    arbitrary field names or attempt to guess at a field outside this
    list -- if the user asks for something else, tell them what's
    available instead of calling this tool.

    If job_ids is omitted, compares every job attached/active in this
    conversation (state["active_job_ids"]). Jobs that are missing,
    incomplete, or lack the requested field are skipped and named in the
    reply rather than silently dropped or making up a value for them;
    this refuses outright (no plot) if fewer than 2 jobs have usable data.
    The plot is already shown to the user automatically once this tool
    returns -- do not also try to paste an image URL into your reply.
    """
    if field not in _COMPARISON_FIELD_ALIASES:
        return (
            f"'{field}' isn't a supported comparison field. Available fields: "
            f"{', '.join(_COMPARISON_FIELD_ALIASES)}."
        )

    mgr = get_job_manager()
    targets = job_ids or (state.get("active_job_ids", []) if state else [])
    if not targets:
        return "No jobs are attached or active in this conversation to compare."

    aliases = _COMPARISON_FIELD_ALIASES[field]
    labels: list[str] = []
    values: list[float] = []
    used_job_ids: list[str] = []
    skipped: list[str] = []
    for job_id in targets:
        result = mgr.result(job_id)
        if result is None or result["status"] != "completed":
            skipped.append(f"{job_id} (not completed)")
            continue
        summary = result["summary"] or {}
        value = next((summary[k] for k in aliases if summary.get(k) is not None), None)
        if value is None:
            skipped.append(f"{job_id} (no {field} in its summary)")
            continue
        spec = read_spec(job_id) or {}
        meta = read_meta(job_id)
        labels.append(meta.get("label") or (auto_job_name(spec) if spec else job_id))
        values.append(float(value))
        used_job_ids.append(job_id)

    if len(values) < 2:
        detail = f" Skipped: {'; '.join(skipped)}." if skipped else ""
        return (
            f"Not enough jobs with a usable '{field}' value to compare (found {len(values)}, need at "
            f"least 2).{detail}"
        )

    # The plot is stored as an artifact of whichever referenced job actually
    # has usable data first (targets[0] may itself have been skipped above).
    primary_job_id = used_job_ids[0]
    out_path = str(JOBS_DIR / primary_job_id / f"comparison_{field}_{uuid.uuid4().hex[:8]}.png")
    ylabel = _COMPARISON_FIELD_LABELS[field]
    render_job_comparison_plot(labels, values, ylabel, title or f"{ylabel} comparison", out_path)

    artifact_key = f"comparison_{field}"
    with result_artifact_transaction(primary_job_id) as artifacts:
        if artifacts is None:
            # See plot_excited_state_spectrum's identical comment above --
            # primary_job_id's result.json was deleted out from under this
            # call. No PLOT_ARTIFACT marker below in that case: the
            # frontend would try to fetch an artifact key that was never
            # actually recorded.
            return f"Job {primary_job_id} was deleted while this plot was being generated; nothing to show."
        artifacts[artifact_key] = out_path

    note = f" (skipped: {'; '.join(skipped)})" if skipped else ""
    # First line is a machine-parseable marker the frontend's ToolResultChip
    # detects (message.name == "plot_job_comparison") to render the image
    # inline + a download link, deterministically -- not dependent on the
    # LLM correctly relaying a URL in its own reply (see MessageBubble.tsx).
    return (
        f"PLOT_ARTIFACT job_id={primary_job_id} key={artifact_key}\n"
        f"Generated a comparison plot of {field} across {len(values)} job(s); it is now shown to the "
        f"user.{note} Present the underlying values as a markdown table in your reply as well."
    )


def _ensemble_master_or_error(job_id: str) -> tuple[Optional[dict], Optional[str]]:
    """Shared validation for plot_wigner_ensemble_spectrum/
    list_ensemble_geometries_in_window: confirms job_id is a completed
    wigner_ensemble master, returning (result_dict, None) or (None,
    error_string). A master only ever reaches status='completed' once
    every sample is both dispatched and terminal (see
    EnsembleOrchestrator._update_one), so "completed" here already means
    "fully finished," not partially so."""
    spec = read_spec(job_id)
    if spec is None:
        return None, f"No such job: {job_id}."
    # Keyed on the v2 task. The runner key is checked too, so a job
    # submitted between the agent rebuild and the taxonomy switch -- which
    # can only exist on a dev stack -- still resolves.
    if (spec.get("task") or "") not in ("wigner_spectra", "") or (
            not spec.get("task") and spec.get("method") != "wigner_ensemble"):
        return None, (f"Job {job_id} is not a nuclear-ensemble job, so it has no "
                      f"pooled spectrum to draw.")
    result = get_job_manager().result(job_id)
    if result is None or result.get("status") != "completed":
        status = (result or {}).get("status", "unknown")
        return None, f"wigner_ensemble job {job_id} is not finished yet (status: {status})."
    return result, None


def plot_wigner_ensemble_spectrum(job_id: str, fwhm_eV: Optional[float] = None) -> str:
    """Generate and display a nuclear-ensemble (Wigner) absorption
    spectrum for a completed wigner_ensemble job -- the Gaussian-broadened
    total spectrum (plus a per-excited-state-index breakdown) pooled
    across every one of its sampled geometries' excited-state
    calculations. Call this whenever the user asks to plot/show/see the
    (ensemble/nuclear-ensemble/Wigner) spectrum for a wigner_ensemble job,
    or wants to re-plot one with a different broadening width.

    Always re-pools every sub-job's data live from disk (never a cached
    result), so calling this again with a different fwhm_eV reflects the
    ensemble's current state exactly. Refuses (no plot) if the job isn't
    a completed wigner_ensemble, or if no sample contributed a usable
    (energy, oscillator strength) pair -- e.g. every sample used an
    engine/method with no oscillator-strength support. The plot is
    already shown to the user automatically once this tool returns -- do
    not also try to paste an image URL into your reply."""
    result, error = _ensemble_master_or_error(job_id)
    if error:
        return error

    sub_ids = sub_job_ids_of(job_id)
    pooled, diagnostics = pool_ensemble_transitions(sub_ids)
    if not pooled["energies_eV"]:
        return (
            f"No sample in wigner_ensemble job {job_id} contributed a usable (energy, oscillator "
            f"strength) pair to plot ({diagnostics['n_no_intensity']} of {diagnostics['n_sub_jobs']} "
            f"samples had no intensity data, {diagnostics['n_failed_or_pending']} failed/incomplete)."
        )

    spec = read_spec(job_id) or {}
    fwhm = fwhm_eV if fwhm_eV is not None else spec.get("params", {}).get("fwhm_eV", 0.4)
    out_path = str(JOBS_DIR / job_id / "ensemble_spectrum.png")
    out_data_path = str(JOBS_DIR / job_id / "ensemble_spectrum.dat")
    try:
        render_wigner_ensemble_spectrum(
            pooled["energies_eV"], pooled["oscillator_strengths"], pooled["state_indices"],
            fwhm, out_path, out_data_path=out_data_path,
        )
    except ValueError as e:
        return f"Could not render the ensemble spectrum: {e}"

    artifact_key = "ensemble_spectrum"
    with result_artifact_transaction(job_id) as artifacts:
        if artifacts is None:
            return f"Job {job_id} was deleted while this plot was being generated; nothing to show."
        artifacts[artifact_key] = out_path
        artifacts["ensemble_spectrum_data"] = out_data_path

    note = ""
    if diagnostics["n_no_intensity"] or diagnostics["n_failed_or_pending"]:
        note = (
            f" ({diagnostics['n_no_intensity']} sample(s) had no usable intensity data, "
            f"{diagnostics['n_failed_or_pending']} failed/incomplete -- excluded from the plot.)"
        )
    return (
        f"PLOT_ARTIFACT job_id={job_id} key={artifact_key}\n"
        f"Generated the nuclear-ensemble absorption spectrum from {diagnostics['n_completed']} sample(s) "
        f"({len(pooled['energies_eV'])} pooled transitions, FWHM = {fwhm:.2f} eV); it is now shown to the "
        f"user.{note}"
    )




def _finish_submission(decision, job_type: str, state, tool_call_id) -> Command:
    """Everything after the approval gate: the branch that runs the job.

    Lifted verbatim out of the pre-rebuild `submit_job`, which is the point
    -- the interrupt mechanics, the "submit the spec the card showed rather
    than the one just rebuilt" rule, and the pes_scan/wigner_ensemble
    re-derivation are all load-bearing and were left alone by the rewrite.
    Only the code that *reaches* this gate changed.
    """
    if not isinstance(decision, dict) or not decision.get("approved"):
        content = (
            f"The user did NOT approve running this '{job_type}' job -- it was not executed. "
            f"Ask what they'd like to change, or confirm they want to cancel it."
        )
        return Command(update={"messages": [ToolMessage(content=content, tool_call_id=tool_call_id)]})

    approved_spec = JobSpec(**decision["spec"])

    # The UI already validated this text before ever resuming (so a typo
    # gets fixed in place with no LLM round-trip) -- this is a defense-in-
    # depth re-check for any resume that didn't go through that path, not
    # the primary gate. Skipped for method == "custom": that job_type's
    # whole reason to exist is carrying ORCA/BAGEL syntax this validator
    # was never built to recognize (see _build_custom_spec_or_error's
    # docstring) -- the same non-blocking-warning treatment already applied
    # at generation time applies to a hand-edit of it too.
    input_text = decision.get("input_text")
    # An engine with no editable input format has nothing a hand-edit could
    # apply to -- PySCF's "input" is a synthetic driver script standing in
    # for direct API calls, so `_raw_input` is never read on that path. The
    # approval card renders read-only for it and the browser never sends
    # input_text, but a scripted client can, and it used to reach
    # validate_input, which raises for any engine outside {orca, bagel} --
    # surfacing as a bare 500 from the approval route. Dropped explicitly
    # here instead, so the approval still runs the job that was approved
    # rather than failing on text that could never have had an effect.
    if input_text is not None and approved_spec.engine not in VALIDATED_ENGINES:
        input_text = None
    if input_text is not None:
        if approved_spec.method != "custom":
            errors = validate_input(approved_spec.engine, input_text)
            if errors:
                content = (
                    f"The edited {approved_spec.engine} input has problems and was NOT run: "
                    f"{'; '.join(errors)}. Ask the user to fix these or revert to the generated input."
                )
                return Command(update={"messages": [ToolMessage(content=content, tool_call_id=tool_call_id)]})
        if approved_spec.method not in ("pes_scan", "wigner_ensemble"):
            approved_spec.params["_raw_input"] = input_text
        # For pes_scan/wigner_ensemble, a hand-edited input applies to
        # sample/image 0's own sub-job only (see below, and see
        # submit_scan's image0_raw_input) -- it's a fixed block of text
        # with one specific geometry baked in, so broadcasting it
        # unchanged to every sample/image via approved_spec.params (shared
        # by all of them) would silently give every one the same, wrong
        # geometry. wigner_ensemble doesn't currently expose an editable
        # approval-card text area at all (no per-sample hand-edit support
        # yet), so input_text is never actually set for it in practice --
        # this exclusion is defense in depth, not a currently-reachable path.

    # SEC-07: ownership is recorded INSIDE JobManager.submit()/submit_scan()
    # itself now, not after either call returns -- see those methods' own
    # docstrings in app/chemistry/jobs/base.py for why "right after this
    # call" is still too late (their own quota-enforcement pass runs AFTER
    # the job is already visible and can itself take real, multi-second
    # time on a populated deployment, confirmed empirically while fixing
    # this). owner_user_id comes from AgentState (set once per turn by
    # _run_turn, same field search_knowledge_base already reads to scope
    # KB retrieval -- see its own docstring in state.py) and survives the
    # resume/re-execution boundary intact, since it was already committed
    # to this turn's checkpoint before the interrupt ever paused.
    owner_user_id = (state or {}).get("owner_user_id")

    approved_task = approved_spec.task or ""
    if approved_spec.method == "pes_scan":
        images, coordinate_values, coordinate_label = _build_scan_images(approved_spec.params)
        job_id = get_job_manager().submit_scan(
            approved_spec, images, coordinate_values, coordinate_label,
            image0_raw_input=input_text if input_text is not None else None,
            owner_user_id=owner_user_id,
        )
    elif approved_spec.method == "wigner_ensemble":
        # Regenerates the full sample set fresh from the round-tripped
        # random_seed (see _build_ensemble_spec_or_error's docstring for
        # why this must be deterministic, not the same in-memory list
        # built before interrupt()) -- mirrors pes_scan's own
        # _build_scan_images(approved_spec.params) re-call above exactly.
        source_id = approved_spec.params["source_frequency_job_id"]
        source_spec = read_spec(source_id)
        source_result = get_job_manager().result(source_id)
        equilibrium_molecule = (
            (source_result["summary"] or {}).get("optimized_molecule")
            if source_spec.get("method") == "opt_freq" else source_spec["molecule"]
        )
        samples, diagnostics = sample_from_source_job(
            equilibrium_molecule, source_result["summary"], n_samples=approved_spec.params["n_samples"],
            random_seed=approved_spec.params["random_seed"],
            low_freq_cutoff_cm1=approved_spec.params.get("low_freq_cutoff_cm1", 100.0),
            temperature_K=approved_spec.params.get("temperature_K", 0.0),
        )
        job_id = get_job_manager().submit_ensemble(approved_spec, samples, diagnostics, owner_user_id=owner_user_id)
    else:
        job_id = get_job_manager().submit(approved_spec, owner_user_id=owner_user_id)
        # spec.label (set from calculation_description in
        # _build_custom_spec_or_error) round-trips through the interrupt/
        # resume boundary intact, but _job_row's display label is read
        # from meta.json's mutable "label" (meta.get("label") or
        # auto_job_name(spec)), never from spec.json's write-once "label"
        # field -- so it has to be copied over explicitly here, using the
        # real, final job_id (not the provisional one from before resume),
        # for it to actually show up in the Job Manager.
        if approved_spec.method == "custom" and approved_spec.label:
            write_meta(job_id, {"label": approved_spec.label})

    edit_note = " (user-edited input)" if input_text is not None else ""
    # Drop the large embedded-geometry/raw-input blobs a pes_scan's params
    # can carry (_scan_start_molecule, _end_molecule, _raw_input) -- these
    # exist for JobSpec round-tripping/reconstruction, not for dumping
    # into a chat message the LLM has to read and relay.
    _BLOB_KEYS = {"_scan_start_molecule", "_end_molecule", "_raw_input"}
    display_params = {k: v for k, v in approved_spec.params.items() if k not in _BLOB_KEYS}
    content = (
        f"Job submitted (user-approved{edit_note}): id={job_id}, type={job_type}, engine={approved_spec.engine}, "
        f"params={display_params}. It is running in the background; tell the user it has started "
        f"and that you'll report results once it finishes (they can also ask you to check on it)."
    )
    # Just the newly submitted id -- active_job_ids' reducer (_append_job_ids
    # in state.py) concatenates it with whatever's already there, including
    # any other submit_job call landing in the same batch. Returning a
    # locally-computed full list here would race with that -- see the
    # reducer's docstring for why.
    return Command(update={
        "active_job_ids": [job_id],
        "messages": [ToolMessage(content=content, tool_call_id=tool_call_id)],
    })


@tool
def list_ensemble_geometries_in_window(
    job_id: str, energy_min_eV: Optional[float] = None, energy_max_eV: Optional[float] = None,
    min_oscillator_strength: Optional[float] = None, target_state: Optional[int] = None,
) -> str:
    """Reports which sampled geometries of a completed wigner_ensemble job
    have a transition inside a given energy window and/or above a given
    oscillator-strength cutoff -- e.g. "which samples absorb around 5.5
    eV?" or "show me the strongest transitions near the peak". Purely a
    read-only report over already-completed sub-job data: no geometry
    export, no new job submitted, nothing runs. This does NOT prepare
    excited-state dynamics/trajectory input of any kind -- this app has no
    molecular-dynamics capability, and this tool's job ends at reporting
    which samples/transitions matched.

    All filter arguments are optional and combine with AND; omit any of
    them to not filter on that criterion. target_state (1 = S1, 2 = S2,
    ...) restricts to one excited state's transitions specifically."""
    result, error = _ensemble_master_or_error(job_id)
    if error:
        return error

    sub_ids = sub_job_ids_of(job_id)
    pooled, diagnostics = pool_ensemble_transitions(sub_ids)
    if not pooled["energies_eV"]:
        return f"No usable (energy, oscillator strength) data in wigner_ensemble job {job_id} to report on."

    sample_index_by_sub_id: dict[str, int] = {}
    rows = []
    for e, o, state_idx, sub_id in zip(
        pooled["energies_eV"], pooled["oscillator_strengths"], pooled["state_indices"], pooled["sub_job_ids"],
    ):
        if energy_min_eV is not None and e < energy_min_eV:
            continue
        if energy_max_eV is not None and e > energy_max_eV:
            continue
        if min_oscillator_strength is not None and o < min_oscillator_strength:
            continue
        if target_state is not None and state_idx != target_state:
            continue
        if sub_id not in sample_index_by_sub_id:
            sub_spec = read_spec(sub_id) or {}
            raw_idx = sub_spec.get("params", {}).get("_ensemble_index")
            sample_index_by_sub_id[sub_id] = raw_idx + 1 if isinstance(raw_idx, int) else "?"  # 1-based, matching
            # the "sample 1 of N" phrasing used elsewhere for this feature (e.g. _build_ensemble_spec_or_error's
            # scan_note) -- _ensemble_index itself is 0-based internal bookkeeping, not user-facing.
        rows.append((sample_index_by_sub_id[sub_id], state_idx, e, o))

    if not rows:
        return (
            f"No transitions in wigner_ensemble job {job_id} matched the given filter "
            f"(searched {len(pooled['energies_eV'])} pooled transitions from {diagnostics['n_completed']} samples)."
        )

    rows.sort(key=lambda r: -r[3])  # descending oscillator strength, matching the source workflow's own report
    lines = [
        f"{len(rows)} of {len(pooled['energies_eV'])} pooled transitions matched, from {diagnostics['n_completed']} "
        f"usable samples:",
        "", "| Sample | State | Energy (eV) | Oscillator strength |", "|---|---|---|---|",
    ]
    for sample_idx, state_idx, e, o in rows:
        lines.append(f"| {sample_idx} | S{state_idx} | {e:.4f} | {o:.4f} |")
    return "\n".join(lines)


@tool
def check_job_status(
    job_id: Optional[str] = None,
    state: Annotated[AgentState, InjectedState] = None,
) -> str:
    """Check the status of a submitted job and get its results if
    finished. If job_id is omitted, checks the most recently submitted job.
    Use this whenever the user asks about job progress, or asks a question
    about results (e.g. "what was the HOMO-LUMO gap", "is it done yet",
    "what did the frequency calculation find") -- the summary dict returned
    contains all the engine-computed values, so answer from it directly
    rather than guessing.
    """
    active = state.get("active_job_ids", []) if state else []
    target = job_id or (active[-1] if active else None)
    if not target:
        return "No jobs have been submitted yet in this conversation."
    return job_context_summary(target)


@tool
def resolve_basis_from_bse(
    basis_query: str,
    state: Annotated[Optional[AgentState], InjectedState] = None,
) -> str:
    """Search Basis Set Exchange (the basis_set_exchange package -- a
    fully offline, locally-bundled database of published basis sets, not a
    network call) for an exact basis-set definition. Use this when the
    user picks the basis menu's "(search Basis Set Exchange for the exact
    basis set)" option, asks for "the exact/official" basis set, or names
    an exotic/relativistic/ECP basis this app's own engine-native
    suggestions don't recognize. Confirms the basis actually covers every
    element in the current molecule before telling you it's usable --
    matches this app's existing "never offer a candidate that doesn't
    actually validate" discipline (see keyword_suggest.py).
    """
    molecule = (state or {}).get("molecule")
    if not molecule:
        return "No molecule is set yet -- call set_molecule first, then retry, so element coverage can be checked."
    from app.chemistry.jobs import bse_basis
    import basis_set_exchange as bse

    elements = sorted(set(molecule["symbols"]))
    canonical = bse_basis.resolve_bse_name(basis_query)
    if not canonical:
        matches = bse_basis.search_bse_basis_names(basis_query)
        if not matches:
            return f"No Basis Set Exchange basis found matching '{basis_query}'."
        return (
            f"No exact Basis Set Exchange match for '{basis_query}'. Closest names: {', '.join(matches)}. "
            f"Ask the user which one they mean, then call this tool again with the exact name."
        )
    try:
        bse.get_basis(canonical, elements=elements)
    except Exception as e:
        return (
            f"Basis Set Exchange has '{canonical}' but it doesn't cover every element in the current "
            f"molecule ({', '.join(elements)}): {e}. Ask the user for an alternative basis."
        )
    return (
        f"Found exact Basis Set Exchange basis '{canonical}', confirmed to cover all elements in the "
        f"current molecule ({', '.join(elements)}). Use it by setting params['basis'] = 'bse:{canonical}' "
        f"on your next generate_job_input/submit_job call -- works on any engine, no other params change."
    )



# =========================================================================
#  The model-facing surface
# =========================================================================
#
# Eleven tools, where there were fourteen -- and, more to the point, one
# 38-parameter `submit_job` schema that was a second system prompt in all
# but name (see docs/MODEL_CONTEXT_BUDGET.md). What replaced it is three
# small tools over a `job_draft` in state, with
# `registry2.elicitation.validate_draft()` deciding after every mutation
# what is still missing and what to ask.
#
# The division of labour is the point. The model transcribes the user's
# answers into the draft and relays the backend's question verbatim; it
# does not decide what a job type requires, which engine can run it, or
# whether the draft is complete. Those were the decisions it used to make
# from prompt prose, and the ones it got wrong.


# Which runner handles each v2 (task, subtype, method).
#
# This is `runner_key()` -- the derivation OVERHAUL_PLAN.md always expected
# a v2 spec to carry ("+ legacy runner key"). It is **not** the
# `registry2/adapter.py` that was deliberately removed: that one ran at
# *read* time, mapping old on-disk specs into the v2 taxonomy so historical
# jobs stayed renderable, and it went because the jobs it existed for were
# wiped. This runs at *write* time, in the opposite direction, and answers a
# question that does not go away: three engines dispatch on a job_type
# string, and something has to say which one a task needs.
#
# An earlier note in docs/TRACKER.md said P2.6 would delete this. That was
# wrong, and is corrected there: deleting it means rewriting all three
# engines' `if job_type == ...` dispatch onto the v2 fields, which is what
# Phases 5-8 do one job family at a time as each is rebuilt. What P2.6 did
# remove is every *reader* that used the runner key to decide what a job
# means -- masters, ensemble sources, input validation -- which is the part
# that was genuinely conflated.
_LEGACY_JOB_TYPE: dict[tuple[str, str], str] = {
    ("opt", "min"): "geometry_optimization",
    ("opt", "constrained"): "geometry_optimization",
    ("opt", "ci"): "geometry_optimization",
    ("freq", ""): "frequency",
    ("opt_freq", ""): "opt_freq",
    ("pes_1d", ""): "pes_scan",
    ("interp_pes", ""): "pes_scan",
    ("neb_ts", ""): "neb_ts",
    ("wigner_spectra", ""): "wigner_ensemble",
    ("cas_reco", "explain"): "recommend_active_space",
    ("cas_reco", "autocas"): "recommend_active_space",
    ("cas_reco", "avas"): "recommend_active_space",
    ("blind", ""): "custom",
}

# Tasks with a v2 entry and no runner behind them yet -- the registry can
# describe them because Phase 0 verified the engines can do them, but the
# implementation lands in a later phase. Named explicitly so the refusal
# says which phase, rather than surfacing as "unknown job_type".
_NOT_YET_IMPLEMENTED = {
    ("single_point", "grad"): "Energy gradients as a standalone job land in Phase 5.",
    ("single_point", "nac"): "Non-adiabatic couplings land in Phase 5.",
}


# Which runner computes excited states at each level of theory -- for the
# per-geometry sub-job of a nuclear-ensemble spectrum. The same kind of
# derivation as the map above, and it lasts as long.
_EXCITED_STATE_JOB_TYPE = {
    "hf": "tddft", "dft": "tddft",
    "casscf": "casscf", "caspt2": "caspt2", "eom_ccsd": "eom_ccsd",
}


def _legacy_job_type(task: str, subtype: str, method: Optional[str]) -> tuple[Optional[str], Optional[str]]:
    """(legacy job_type, error). See _LEGACY_JOB_TYPE's note -- interim."""
    if (task, subtype) in _NOT_YET_IMPLEMENTED:
        return None, _NOT_YET_IMPLEMENTED[(task, subtype)]
    if task == "single_point":
        # The one place the v1 taxonomy conflated task with level of
        # theory: a CASSCF single point and a CASSCF optimization were
        # unrelated job_type strings.
        if method in ("casscf", "caspt2"):
            return method, None
        if subtype == "ee":
            return ("eom_ccsd" if method == "eom_ccsd" else "tddft"), None
        return "single_point", None
    job_type = _LEGACY_JOB_TYPE.get((task, subtype))
    if job_type is None:
        return None, f"No runner is wired up for {task}/{subtype} yet."
    return job_type, None


def _spec_from_draft(draft: dict, molecule: Optional[dict], state: Optional[dict]):
    """Build the JobSpec, preview and grounding context for a ready draft.

    Deterministic given (draft, molecule): this runs once when the approval
    card is rendered and again, identically, when the user clicks Approve
    -- see submit_draft's docstring for why that matters.
    """
    task, subtype = draft["task"], draft.get("subtype", "")
    job_type, error = _legacy_job_type(task, subtype, draft.get("method"))
    if error:
        return None, error

    params = dict(draft.get("params") or {})
    params["method"] = draft.get("method")
    if task == "opt" and subtype == "ci":
        params["optimization_type"] = "conical_intersection"
    if task in ("interp_pes", "pes_1d"):
        params.setdefault("scan_job_type", "single_point")
    if task == "wigner_spectra":
        # A nuclear-ensemble spectrum runs one excited-state calculation
        # per sampled geometry, and the v1 taxonomy needs that sub-job
        # named as a job_type. It is not a separate choice for the user to
        # make -- it follows from the method they already picked, which is
        # exactly the derivation the v2 taxonomy expresses by keeping task
        # and method apart in the first place.
        params.setdefault("scan_job_type", _EXCITED_STATE_JOB_TYPE.get(
            draft.get("method"), "tddft"))
    if task == "blind":
        params["raw_input_text"] = params.get("raw_input_text")
    params = {k: v for k, v in params.items() if v is not None}

    end_molecule = params.pop("_end_molecule", None)
    built = _build_spec_or_error(
        job_type, molecule or {}, draft.get("resolved_engine") or draft.get("engine"),
        params, end_molecule=end_molecule,
    )
    # Stamp the v2 taxonomy onto whatever the builders produced. Done here,
    # once, rather than threaded through five builders: every path into a
    # submitted job goes through this function, so this is the single point
    # where "what the user asked for" is attached to "what will run it".
    spec = built[0]
    if spec is not None:
        spec.task, spec.subtype = task, subtype
    return built, None


# Draft fields that are really conversation state, and the tool that
# actually sets each. A model told to answer these with update_job_draft
# writes a plausible-looking key that is not a parameter of anything.
_STATE_OWNED_FIELDS = {
    "molecule": 'set_geometry(identifier=...)',
    "_end_molecule": 'set_geometry(identifier=..., role="end")',
}


# ------------------------------------------------------------ draft replies

def _draft_message(verdict, extra: str = "") -> str:
    """Render a DraftVerdict as the ToolMessage the model reads.

    `asking_for` is spelled out as the key to write next, in the text and
    not only in a returned dict. Collapsing `submit_job`'s 38 named
    parameters into one `updates` dict is where the token saving comes
    from, but it also removed every schema-level hint about field names --
    so the question and the key it answers have to travel together, or the
    model invents a name and `normalize_draft` tolerantly absorbs it.
    """
    if verdict.status == "ready":
        lines = [f"DRAFT READY -- {verdict.preview['summary']}"]
        if verdict.routing_reason:
            lines.append(f"Engine: {verdict.routing_reason}")
        lines.append(f"Parameters: {verdict.preview['params']}")
        if verdict.preview.get("applied_defaults"):
            lines.append(f"Defaults applied: {verdict.preview['applied_defaults']}")
        for warning in verdict.warnings:
            lines.append(f"Caveat (tell the user before they approve): {warning}")
        for note in verdict.notes:
            lines.append(f"Note: {note}")
        if extra:
            lines.append(extra)
        lines.append(
            "Call submit_draft to put the approval card in front of the user. Nothing "
            "runs until they approve it, so do not say the job has started."
        )
        return "\n".join(lines)

    if verdict.status == "unavailable":
        lines = ["THIS COMBINATION CANNOT RUN HERE. Tell the user exactly this:",
                 verdict.ask_user_exactly]
        if verdict.alternatives:
            lines.append(
                f"If they pick one, call update_job_draft with "
                f'{{"engine": "{verdict.alternatives[0]}"}}.')
        return "\n".join(lines)

    lines = ["DRAFT INCOMPLETE. Put this question to the user word for word, without "
             "rephrasing it or answering it yourself:",
             verdict.ask_user_exactly]
    if verdict.options:
        lines.append("Offer these options: " + ", ".join(str(o) for o in verdict.options))
    menu = format_keyword_options(verdict.keyword_options)
    if menu:
        lines.append(menu)
    for note in verdict.notes:
        lines.append(f"Note: {note}")
    # A geometry is not a parameter -- it lives in conversation state and
    # is put there by set_geometry. Saying "call update_job_draft" here
    # sent the model to write {"molecule": "water"}, which the tolerant
    # draft shape absorbed as a parameter named `molecule` and carried all
    # the way into the submitted spec.
    if verdict.asking_for in _STATE_OWNED_FIELDS:
        lines.append(f"When they answer, call "
                     f"{_STATE_OWNED_FIELDS[verdict.asking_for]} -- a structure is set "
                     f"that way, not written into the draft.")
    else:
        lines.append(
            f'When they answer, call update_job_draft with {{"{verdict.asking_for}": '
            f"<their answer>}}.")
    return "\n".join(lines)


def _draft_input_preview(verdict, state: Optional[dict]) -> str:
    """The engine input a ready draft would run, rendered into the reply.

    This is what replaced `generate_job_input`. Removing that tool was
    right -- it duplicated the whole build path to answer a question the
    draft already knows the answer to -- but "show me the input without
    running it" is a real request, and for a while the draft did not
    actually carry the input, so the agent had nothing to show. An e2e
    scenario caught it: asked to show an ORCA input and not run it, the
    model set the geometry and stopped, because nothing downstream offered
    it a way to comply.

    Best-effort. A draft that is ready but whose builder objects (a task
    with no runner yet, say) still gets its parameter summary; the input is
    an addition to the reply, not a precondition for it.
    """
    try:
        built, error = _spec_from_draft(verdict.draft, (state or {}).get("molecule"), state)
        if error:
            return ""
        spec, preview, _kb, _notes, _scan, _kw, _warn, build_error = built
        if build_error or not preview:
            return ""
        return (f"The {spec.engine.upper()} input this would run — show it to the user if "
                f"they asked to see it, and note that nothing has run yet:\n{preview}")
    except Exception:
        return ""


def _draft_command(draft: dict, state: Optional[dict], tool_call_id: str) -> Command:
    """Validate a draft, store it, and reply. The single funnel every draft
    mutation goes through, so there is exactly one place where a draft is
    checked and exactly one wording for the reply."""
    verdict = validate_draft(draft, state or {})
    extra = _draft_input_preview(verdict, state) if verdict.status == "ready" else ""
    return Command(update={
        "job_draft": verdict.draft,
        "messages": [ToolMessage(content=_draft_message(verdict, extra),
                                 tool_call_id=tool_call_id)],
    })


# ------------------------------------------------------------------- tools

@tool
def set_geometry(
    identifier: str,
    role: str = "active",
    charge: Optional[int] = None,
    multiplicity: Optional[int] = None,
    state: Annotated[AgentState, InjectedState] = None,
    tool_call_id: Annotated[str, InjectedToolCallId] = None,
) -> Command:
    """Resolve a structure and make it available to this conversation.

    `identifier` is a common/IUPAC name, a SMILES string, or a pasted
    XYZ/xmol coordinate block -- pass a pasted block through verbatim, do
    not rewrite it. Call this whenever the user names, draws or pastes a
    molecule, even before they ask for a calculation; the UI shows it in 3D.

    `role="active"` (the default) sets the structure everything runs on.
    `role="end"` sets the second geometry for a path between two structures
    (an interpolated scan, or an NEB reactant/product pair): call it once
    with each role, and give the same atoms in the same order both times.

    Pass charge/multiplicity only if the user mentions them; otherwise
    neutral and lowest-spin are used.
    """
    molecule, desc = _resolve_or_error(identifier, charge, multiplicity)
    if molecule is None:
        return Command(update={"messages": [ToolMessage(content=desc, tool_call_id=tool_call_id)]})
    if role == "end":
        return Command(update={
            "pes_scan_end_molecule": molecule,
            "messages": [ToolMessage(content=f"Set as the end geometry. {desc}",
                                     tool_call_id=tool_call_id)],
        })
    frame = _make_frame(molecule, identifier)
    return Command(update={
        "molecule": molecule, "molecule_frames": [frame],
        "messages": [ToolMessage(content=desc + " It is now shown to the user in 3D.",
                                 tool_call_id=tool_call_id)],
    })


@tool
def lookup_capabilities(
    task: Optional[str] = None,
    method: Optional[str] = None,
    engine: Optional[str] = None,
) -> str:
    """Answer a question about what this deployment can actually compute.

    **Use this for every capability question rather than answering from
    memory.** What a program supports in general and what it supports here,
    at these versions, with these builds, are different questions, and the
    published answer is sometimes wrong for this host -- BAGEL accepts a
    constrained-optimization keyword and silently ignores it, for one. The
    table this reads was built from real runs.

    Give whichever of task/method/engine the user's question mentions. With
    no engine, it reports every engine that can run the combination and
    which one would be chosen.
    """
    if task:
        resolved, suggestions = resolve_task(task)
        if resolved is None:
            return (f"'{task}' is not a task this app runs. Closest matches: "
                    f"{', '.join(suggestions) or 'none'}. Ask the user which they meant.")
        task_name, subtype = resolved
    else:
        task_name, subtype = "", ""
    if method:
        canonical, suggestions = resolve_method(method)
        if canonical is None:
            return (f"'{method}' is not a method this app runs. Closest matches: "
                    f"{', '.join(suggestions) or 'none'}.")
        method = canonical
    if not task_name:
        if engine:
            return json.dumps(describe_engine(engine))
        return ("Name a task (and a method, if the question is about one) so this can "
                "be looked up -- for example task='conical intersection', method='casscf'.")
    return json.dumps(capability_answer(task_name, subtype, method, engine))


@tool
def start_job_draft(
    task: str,
    method: Optional[str] = None,
    engine: Optional[str] = None,
    state: Annotated[AgentState, InjectedState] = None,
    tool_call_id: Annotated[str, InjectedToolCallId] = None,
) -> Command:
    """Begin assembling a calculation, discarding any draft in progress.

    Call this as soon as the user asks for a calculation, with whatever
    they have already said -- `task` alone is enough. The reply tells you
    the one thing to ask next; keep answering it with update_job_draft
    until the draft comes back READY.

    `task` may be a plain phrase ("geometry optimization", "uv-vis",
    "frequencies"); it is resolved for you. Pass `engine` only when the
    user named one -- otherwise the backend picks it and explains why.
    """
    draft = {"task": task, "method": method, "engine": engine, "params": {}}
    return _draft_command(draft, state, tool_call_id)


@tool
def update_job_draft(
    updates: dict,
    state: Annotated[AgentState, InjectedState] = None,
    tool_call_id: Annotated[str, InjectedToolCallId] = None,
) -> Command:
    """Record the user's answers into the draft and re-check it.

    `updates` is a flat dict of field name to value, using the exact key
    the previous reply told you to write -- e.g. {"basis": "cc-pvdz"},
    {"n_states": 3}, {"active_electrons": 6, "active_orbitals": 6}. Set a
    field to null to clear it. `task`, `method` and `engine` are accepted
    here too, for when the user changes their mind.

    Only ever write what the user actually said. If they have not answered
    the question yet, ask it again rather than filling in a plausible
    value: a guessed parameter reaches the approval card looking exactly
    like one they chose.
    """
    draft = dict((state or {}).get("job_draft") or {})
    if not draft:
        return Command(update={"messages": [ToolMessage(
            content="There is no draft in progress -- call start_job_draft first.",
            tool_call_id=tool_call_id)]})
    params = dict(draft.get("params") or {})
    misrouted = []
    for key, value in (updates or {}).items():
        if key in ("task", "subtype", "method", "engine"):
            draft[key] = value
        elif key in _STATE_OWNED_FIELDS:
            # Refused rather than absorbed. The draft shape is deliberately
            # tolerant of a model that puts a parameter at the top level,
            # but a *geometry* written as a parameter is not a formatting
            # slip -- it produces a spec carrying a stray key like
            # {"molecule": "water"} that no runner reads and that shows up
            # on the approval card as though the user chose it.
            misrouted.append(key)
        else:
            params[key] = value
    draft["params"] = params
    if misrouted:
        how = "; ".join(_STATE_OWNED_FIELDS[k] for k in misrouted)
        return Command(update={"messages": [ToolMessage(
            content=(f"A structure is not a job parameter, so {', '.join(misrouted)} "
                     f"was not recorded in the draft. Call {how} instead, then carry "
                     f"on answering the draft's questions."),
            tool_call_id=tool_call_id)]})
    return _draft_command(draft, state, tool_call_id)


@tool
def submit_draft(
    state: Annotated[AgentState, InjectedState] = None,
    tool_call_id: Annotated[str, InjectedToolCallId] = None,
) -> Command:
    """Put the finished draft in front of the user as an approval card.

    Call this only once the draft has come back READY. It pauses and shows
    the user the exact input that would run; nothing is executed unless
    they approve it. Do not tell the user the job has started before that.

    Everything before the pause re-runs when the user clicks Approve, so
    this deliberately re-checks the draft **without** re-reading anything
    outside it: a verdict that changed in between would return a question
    instead of resuming, and the approval would vanish with no error. The
    spec that actually runs is the one the card showed, round-tripped back
    verbatim rather than rebuilt.
    """
    draft = (state or {}).get("job_draft") or {}
    if not draft:
        return Command(update={"messages": [ToolMessage(
            content="There is no draft to submit -- call start_job_draft first.",
            tool_call_id=tool_call_id)]})

    verdict = validate_draft(draft, state or {}, check_external=False)
    if verdict.status != "ready":
        return Command(update={"messages": [ToolMessage(
            content=_draft_message(verdict), tool_call_id=tool_call_id)]})

    molecule = (state or {}).get("molecule")
    built, error = _spec_from_draft(verdict.draft, molecule, state)
    if error:
        return Command(update={"messages": [ToolMessage(
            content=f"This draft cannot be submitted: {error}", tool_call_id=tool_call_id)]})
    spec, preview, kb_context, param_notes, scan_note, keyword_options, warnings, build_error = built
    if build_error:
        return Command(update={"messages": [ToolMessage(
            content=f"This draft cannot be submitted: {build_error}",
            tool_call_id=tool_call_id)]})

    decision = interrupt({
        "kind": "job_approval",
        "task": verdict.draft["task"],
        "subtype": verdict.draft.get("subtype", ""),
        "job_type": spec.method,
        "engine": spec.engine,
        "molecule_name": (molecule or {}).get("name"),
        "params": spec.params,
        "input_preview": preview,
        "scan_note": scan_note,
        "kb_context": kb_context,
        "param_corrections": list(param_notes or []) + list(verdict.notes),
        "input_warnings": list(warnings or []) + list(verdict.warnings),
        "keyword_options": keyword_options,
        "capability_note": verdict.routing_reason,
        "spec": spec.to_dict(),
    })

    return _finish_submission(decision, verdict.draft["task"], state, tool_call_id)


@tool
def plot(
    kind: str,
    job_id: Optional[str] = None,
    job_ids: Optional[list[str]] = None,
    field: Optional[str] = None,
    width: Optional[float] = None,
    state: Annotated[AgentState, InjectedState] = None,
) -> str:
    """Draw a plot from data a completed job actually produced.

    `kind` is one of:
      "uvvis"      -- broadened UV/Vis absorption from an excited-state job
      "ir"         -- broadened IR spectrum from a frequency job
      "ensemble"   -- nuclear-ensemble spectrum from a Wigner job (needs job_id)
      "comparison" -- one scalar across several jobs (needs `field`)

    `field`, for "comparison", is one of energy, homo_lumo_gap,
    zero_point_energy, enthalpy, gibbs_free_energy, ts_energy -- no other
    name is accepted and none is guessed at.

    `width` is the broadening: eV for "uvvis"/"ensemble" (default 0.4),
    cm-1 for "ir" (default 20).

    If the data a plot needs is missing -- excitation energies with no
    oscillator strengths, say -- this refuses and explains why. Relay that
    explanation. Never describe a spectrum that was not drawn.
    """
    if kind == "uvvis":
        return plot_excited_state_spectrum(job_id=job_id, fwhm_eV=width, state=state)
    if kind == "ir":
        return plot_ir_spectrum(job_id=job_id, fwhm_cm1=width, state=state)
    if kind == "ensemble":
        if not job_id:
            return "A nuclear-ensemble plot needs the wigner_ensemble job's id."
        return plot_wigner_ensemble_spectrum(job_id=job_id, fwhm_eV=width)
    if kind == "comparison":
        if not field:
            return ("A comparison plot needs `field` -- one of energy, homo_lumo_gap, "
                    "zero_point_energy, enthalpy, gibbs_free_energy, ts_energy.")
        return plot_job_comparison(field=field, job_ids=job_ids, state=state)
    return (f"'{kind}' is not a plot this app draws. Use uvvis, ir, ensemble or "
            f"comparison.")


STATIC_TOOLS = [
    set_geometry, lookup_capabilities,
    start_job_draft, update_job_draft, submit_draft,
    check_job_status, plot, list_ensemble_geometries_in_window,
    search_knowledge_base, search_academic_literature, web_search,
    resolve_basis_from_bse,
]


class _LegacyApprovalArgs(BaseModel):
    """Accepts whatever the pre-rebuild call recorded, without naming it.

    `extra="allow"` rather than the old 38 fields spelled out again: the
    point is to accept an argument list written by a tool that no longer
    exists, and enumerating it would resurrect the schema this phase
    deleted.
    """
    model_config = ConfigDict(extra="allow")


def _legacy_submit_job(**_kwargs) -> str:
    """Answer an approval that was already on screen when the agent changed.

    A conversation paused on the old `submit_job` approval card keeps its
    pending tool call in the checkpoint. After the rewrite that name
    resolves to nothing, so clicking Approve produced `Error: submit_job is
    not a valid tool, try one of [...]` -- an internal message about tool
    names, shown to someone who just clicked a button.

    The job genuinely cannot be run: the spec on that card was built by a
    tool that no longer exists, in a taxonomy the runners are being moved
    off. So this says so in a sentence the model can relay, and the
    conversation carries on rather than wedging.
    """
    return (
        "This approval card was created by an earlier version of the agent and can no "
        "longer be run as it stands -- nothing was submitted. Tell the user that, and "
        "offer to set the job up again from scratch; everything they asked for is still "
        "in the conversation above."
    )


# Bound to the tool executor but deliberately NOT offered to the model --
# see get_all_tools() below.
LEGACY_RESUME_TOOLS = [
    StructuredTool.from_function(
        func=_legacy_submit_job, name="submit_job",
        description="Compatibility shim for approvals pending across the Phase 2 rebuild.",
        args_schema=_LegacyApprovalArgs,
    ),
]


def get_all_tools() -> list:
    """The tools the model is offered, and pays for in every prompt."""
    return STATIC_TOOLS


def get_executable_tools() -> list:
    """What the tool node can actually run.

    A superset of `get_all_tools()`: it also answers tool calls recorded by
    a previous version of the agent and still pending in some conversation's
    checkpoint. Those are never advertised to the model -- they cost nothing
    in the prompt and there is no reason for it to call one -- but the
    executor has to be able to complete them, or a thread paused on an old
    approval card is stuck forever.
    """
    return [*STATIC_TOOLS, *LEGACY_RESUME_TOOLS]
