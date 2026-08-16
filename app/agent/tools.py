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

import uuid
from typing import Annotated, Optional

from langchain_core.messages import ToolMessage
from langchain_core.tools import InjectedToolCallId, tool
from langgraph.prebuilt import InjectedState
from langgraph.types import Command, interrupt

from app.agent.scholar_search import search_academic_literature
from app.agent.state import AgentState
from app.agent.web_search import web_search
from app.chemistry.jobs import interpolate
from app.chemistry.jobs.base import (
    JobSpec, MAX_AUTO_RETRIES, SCAN_ONLY_PARAM_KEYS, get_job_manager, read_meta, read_spec,
    result_artifact_transaction, write_meta,
)
from app.chemistry.jobs.keyword_suggest import suggest_basis_options, suggest_functional_options
from app.chemistry.jobs.param_normalize import normalize_basis, normalize_method
from app.chemistry.jobs.preview import build_input_preview
from app.chemistry.jobs.registry import (
    METHODS, PARAM_HELP, default_engine, missing_required_params,
)
from app.chemistry.jobs.naming import auto_job_name
from app.chemistry.jobs.summarize import job_context_summary
from app.chemistry.jobs.validate import validate_input
from app.chemistry.molecule import resolve_molecule
from app.chemistry.spectrum import render_ir_spectrum_plot, render_job_comparison_plot, render_uvvis_plot
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


def _keyword_options_for_job(job_type: str, params: dict) -> Optional[dict]:
    """Mechanical basis/method-keyword disambiguation menu (see
    app/chemistry/jobs/keyword_suggest.py) -- computed on every job-prep
    call, same "structural, not LLM-discretionary" pattern as
    _kb_context_for_job above. A basis menu is offered whenever a basis
    was given; a functional menu is offered only when there's a genuine
    spelling choice to disambiguate (method='dft', or job_type='tddft' --
    where the functional is the real choice even though tddft's own
    'method' just means hf-vs-dft) -- plain 'hf'/'casscf'/'caspt2' have no
    keyword ambiguity (those names aren't spelled differently across
    engines), so no numbered menu is shown for them. Returns None (not an
    empty dict) when there's nothing worth showing, so callers can skip
    the whole section cleanly."""
    basis_options = suggest_basis_options(params.get("basis"))
    functional_options: list[str] = []
    if job_type == "tddft" or params.get("method") == "dft":
        functional_options = suggest_functional_options(params.get("functional"))
    if not basis_options and not functional_options:
        return None
    return {"basis_options": basis_options, "functional_options": functional_options}


_BASIS_LETTERS = "abcdefghijklmnopqrstuvwxyz"


def _format_keyword_options_block(keyword_options: Optional[dict]) -> str:
    """Renders _keyword_options_for_job's result as the numbered
    (method/functional)/lettered (basis) menu text appended to
    generate_job_input's ToolMessage and submit_job's interrupt() payload
    -- see app/agent/prompts.py for the instruction to actually present
    this to the user and interpret a shorthand reply like '1b' against it."""
    if not keyword_options:
        return ""
    lines = ["\n\nClosest-matching exact syntax keywords found (present these to the user before finalizing --"]
    lines.append("a reply like '1b' picks functional/method option 1 and basis option b):")
    functional_options = keyword_options.get("functional_options") or []
    if functional_options:
        lines.append("Functional/method options:")
        for i, opt in enumerate(functional_options, start=1):
            lines.append(f"  {i}) {opt}")
    basis_options = keyword_options.get("basis_options") or []
    if basis_options:
        lines.append("Basis set options:")
        for letter, opt in zip(_BASIS_LETTERS, basis_options):
            lines.append(f"  {letter}) {opt}")
    return "\n" + "\n".join(lines)


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
    keyword_options = _keyword_options_for_job(scan_job_type, sub_params)
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
    keyword_options = _keyword_options_for_job("neb_ts", params)
    return spec, preview, kb_context, param_notes, None, keyword_options, [], None


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
    if job_type in ("geometry_optimization", "frequency") and params.get("method") in ("casscf", "caspt2"):
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
    keyword_options = _keyword_options_for_job(job_type, params)
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
    warnings = validate_input(engine, raw_text)
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


@tool
def set_molecule(
    identifier: str,
    charge: Optional[int] = None,
    multiplicity: Optional[int] = None,
    state: Annotated[AgentState, InjectedState] = None,
    tool_call_id: Annotated[str, InjectedToolCallId] = None,
) -> Command:
    """Resolve a molecule from its common/IUPAC name, a SMILES string, or a
    pasted XYZ/xmol-format coordinate block, and make it the active
    molecule for this conversation. Call this whenever the user names,
    draws (via SMILES), or pastes the coordinates of a molecule, even if
    they haven't asked for a specific calculation yet -- the UI will show a
    3D visualization of it. If the user pastes raw coordinates, pass that
    block through as `identifier` verbatim (do not summarize, rename, or
    otherwise rewrite it first) -- it's detected and parsed directly. If
    the user mentions a non-default charge or spin multiplicity, pass
    them; otherwise leave them unset and sensible defaults (neutral,
    lowest-spin) are used.
    """
    molecule, desc = _resolve_or_error(identifier, charge, multiplicity)
    if molecule is None:
        return Command(update={"messages": [ToolMessage(content=desc, tool_call_id=tool_call_id)]})
    msg = desc + " A 3D visualization is now shown to the user."
    frame = _make_frame(molecule, identifier)
    return Command(update={
        "molecule": molecule, "molecule_frames": [frame],
        "messages": [ToolMessage(content=msg, tool_call_id=tool_call_id)],
    })


@tool
def set_pes_scan_endpoint(
    identifier: str,
    charge: Optional[int] = None,
    multiplicity: Optional[int] = None,
    state: Annotated[AgentState, InjectedState] = None,
    tool_call_id: Annotated[str, InjectedToolCallId] = None,
) -> Command:
    """Resolve the SECOND ("end") geometry for a two-molecule pes_scan --
    a straight mirror of set_molecule, but stored in its own slot so both
    endpoints are available together. Call this (in addition to, not
    instead of, set_molecule for the "start" structure) whenever the user
    describes a potential-energy scan or interpolated path between two
    named/drawn/pasted structures -- e.g. if they paste two XYZ/xmol
    blocks in one message, pass the first to set_molecule and the second
    to this tool, both within your handling of that one message. Accepts
    the same identifier forms as set_molecule (common/IUPAC name, SMILES,
    or a pasted XYZ/xmol coordinate block). The two geometries must have
    the same atoms in the same order (same molecule, different
    conformation/orientation) -- submit_job/generate_job_input report a
    clear error if they don't match, so don't try to reconcile a mismatch
    yourself.
    """
    molecule, desc = _resolve_or_error(identifier, charge, multiplicity)
    if molecule is None:
        return Command(update={"messages": [ToolMessage(content=desc, tool_call_id=tool_call_id)]})
    msg = f"Resolved pes_scan end geometry: {desc}"
    return Command(update={
        "pes_scan_end_molecule": molecule, "messages": [ToolMessage(content=msg, tool_call_id=tool_call_id)],
    })


@tool
def generate_job_input(
    job_type: str,
    molecule_identifier: Optional[str] = None,
    engine: Optional[str] = None,
    qc_method: Optional[str] = None,
    basis: Optional[str] = None,
    functional: Optional[str] = None,
    active_electrons: Optional[int] = None,
    active_orbitals: Optional[int] = None,
    n_states: Optional[int] = None,
    weights: Optional[list[float]] = None,
    orbital_indices: Optional[list[str]] = None,
    coordinate_type: Optional[str] = None,
    coordinate_atoms: Optional[list[int]] = None,
    scan_range: Optional[list[float]] = None,
    n_points: Optional[int] = None,
    ms_caspt2: Optional[bool] = None,
    shift: Optional[float] = None,
    frozen_core: Optional[bool] = None,
    df_basis: Optional[str] = None,
    max_steps: Optional[int] = None,
    temperature_K: Optional[float] = None,
    use_tda: Optional[bool] = None,
    want_oscillator_strengths: Optional[bool] = None,
    scan_job_type: Optional[str] = None,
    interpolation_method: Optional[str] = None,
    raw_input_text: Optional[str] = None,
    calculation_description: Optional[str] = None,
    preopt: Optional[bool] = None,
    n_images: Optional[int] = None,
    target_state: Optional[int] = None,
    max_active_orbitals: Optional[int] = None,
    avas_aolabels: Optional[list[str]] = None,
    literature_notes: Optional[str] = None,
    entropy_method: Optional[str] = None,
    dmrg_bond_dim: Optional[int] = None,
    optimization_type: Optional[str] = None,
    target_state_2: Optional[int] = None,
    state: Annotated[AgentState, InjectedState] = None,
    tool_call_id: Annotated[str, InjectedToolCallId] = None,
) -> Command:
    """Build and return an engine input file/script WITHOUT running it.
    Use this when the user asks you to "write", "prepare", "generate", or
    "show" an input -- anything short of asking you to actually run/submit
    it. Show the returned text to the user verbatim in a code block (see
    the system prompt for when it's appropriate to follow up with
    submit_job).

    Takes the same job_type/parameters as submit_job (see its docstring for
    the parameter contract and required-parameter rules per job_type,
    including pes_scan's scan_job_type/interpolation_method, and
    job_type='custom''s raw_input_text/calculation_description for a
    calculation that doesn't map onto any of this app's other job_types).
    If the user named a molecule in the same message, pass it as
    molecule_identifier; it's resolved inline here since this tool never
    pauses or re-executes. For a pes_scan, the second ("end") geometry
    still comes from a separate set_pes_scan_endpoint call (like
    submit_job, this tool never resolves it itself), not from
    molecule_identifier.
    """
    extra_state_update = {}
    molecule = state.get("molecule") if state else None
    if not molecule and molecule_identifier:
        molecule, desc = _resolve_or_error(molecule_identifier, None, None)
        if molecule is None:
            return Command(update={"messages": [ToolMessage(content=desc, tool_call_id=tool_call_id)]})
        extra_state_update["molecule"] = molecule
        extra_state_update["molecule_frames"] = [_make_frame(molecule, molecule_identifier)]
    if not molecule:
        return Command(update={"messages": [ToolMessage(
            content="No molecule is set yet. Call set_molecule first (or pass molecule_identifier here directly).",
            tool_call_id=tool_call_id,
        )]})
    end_molecule = state.get("pes_scan_end_molecule") if state else None

    raw_params = _collect_params(
        qc_method, basis, functional, active_electrons, active_orbitals, n_states, weights,
        orbital_indices, coordinate_type, coordinate_atoms, scan_range, n_points, ms_caspt2,
        shift, frozen_core, df_basis, max_steps, temperature_K, use_tda, want_oscillator_strengths,
        scan_job_type, interpolation_method, raw_input_text, calculation_description,
        preopt, n_images, target_state, max_active_orbitals, avas_aolabels, literature_notes,
        entropy_method, dmrg_bond_dim, optimization_type, target_state_2,
    )
    spec, preview, kb_context, param_notes, scan_note, keyword_options, warnings, error = _build_spec_or_error(
        job_type, molecule, engine, raw_params, end_molecule=end_molecule,
    )
    if error:
        return Command(update={**extra_state_update, "messages": [ToolMessage(content=error, tool_call_id=tool_call_id)]})

    notes_block = (
        "\n\nNote: automatically corrected the following before generating this input -- "
        "mention this to the user so they know what was assumed:\n" + "\n".join(f"- {n}" for n in param_notes)
    ) if param_notes else ""
    kb_block = (
        f"\n\nRelevant manual/reference excerpts for this engine and job type -- check your "
        f"parameters (especially basis set / keyword names) against these before showing the "
        f"input, and correct them if they conflict:\n{kb_context}"
    ) if kb_context else ""
    scan_block = f"\n\n({scan_note})" if scan_note else ""
    warnings_block = (
        "\n\nStructural check found possible issues in this input (NOT blocking -- use your own "
        "judgment on whether to fix them before showing this to the user, since a custom job's "
        "syntax may legitimately not match what this check expects):\n" + "\n".join(f"- {w}" for w in warnings)
    ) if warnings else ""
    keyword_block = _format_keyword_options_block(keyword_options)
    content = (
        f"Generated {spec.engine} input for a '{job_type}' job (NOT run). Show this to the user "
        f"verbatim in a code block.\n\n{preview}{scan_block}{notes_block}{warnings_block}{kb_block}{keyword_block}"
    )
    return Command(update={**extra_state_update, "messages": [ToolMessage(content=content, tool_call_id=tool_call_id)]})


@tool
def submit_job(
    job_type: str,
    engine: Optional[str] = None,
    qc_method: Optional[str] = None,
    basis: Optional[str] = None,
    functional: Optional[str] = None,
    active_electrons: Optional[int] = None,
    active_orbitals: Optional[int] = None,
    n_states: Optional[int] = None,
    weights: Optional[list[float]] = None,
    orbital_indices: Optional[list[str]] = None,
    coordinate_type: Optional[str] = None,
    coordinate_atoms: Optional[list[int]] = None,
    scan_range: Optional[list[float]] = None,
    n_points: Optional[int] = None,
    ms_caspt2: Optional[bool] = None,
    shift: Optional[float] = None,
    frozen_core: Optional[bool] = None,
    df_basis: Optional[str] = None,
    max_steps: Optional[int] = None,
    temperature_K: Optional[float] = None,
    use_tda: Optional[bool] = None,
    want_oscillator_strengths: Optional[bool] = None,
    scan_job_type: Optional[str] = None,
    interpolation_method: Optional[str] = None,
    raw_input_text: Optional[str] = None,
    calculation_description: Optional[str] = None,
    preopt: Optional[bool] = None,
    n_images: Optional[int] = None,
    target_state: Optional[int] = None,
    max_active_orbitals: Optional[int] = None,
    avas_aolabels: Optional[list[str]] = None,
    literature_notes: Optional[str] = None,
    entropy_method: Optional[str] = None,
    dmrg_bond_dim: Optional[int] = None,
    optimization_type: Optional[str] = None,
    target_state_2: Optional[int] = None,
    retry_of_job_id: Optional[str] = None,
    state: Annotated[AgentState, InjectedState] = None,
    tool_call_id: Annotated[str, InjectedToolCallId] = None,
) -> Command:
    """Run a computational chemistry job on the active molecule in the
    background. Call this when the user asks you to run/submit/perform a
    calculation (not just generate its input -- use generate_job_input for
    that). `job_type` must be one of: single_point, geometry_optimization,
    frequency, casscf, caspt2, tddft, eom_ccsd, mo_visualization, pes_scan,
    neb_ts, custom, recommend_active_space.

    geometry_optimization/frequency also accept qc_method='casscf' or
    'caspt2' (caspt2 is BAGEL-only) -- these need active_electrons/
    active_orbitals/n_states/weights, same as the standalone casscf/caspt2
    job types. PySCF has no analytic CASSCF Hessian, so its CASSCF
    frequency path uses a slower numerical Hessian -- warn the user this
    may take noticeably longer than an HF/DFT frequency job. `target_state`
    (omit for the ground state) picks which state's PES is optimized/
    differentiated, meaningful on engine='bagel' only. For a BAGEL CASSCF
    geometry_optimization only, `optimization_type='conical_intersection'`
    finds the minimum-energy crossing point between `target_state` and
    `target_state_2` (which defaults to target_state + 1) instead of a
    single state's minimum -- requesting this on any other engine raises
    an error, since ORCA's equivalent module (%mecp) and pyscf/geomeTRIC
    have no matching capability here.

    recommend_active_space runs an autoCAS-style Single-Orbital-Entropy
    active-space recommendation as ONE job: RHF -> an AVAS-seeded valence
    "pilot" space -> an entropy pilot pass -> single-orbital-entropy
    threshold/plateau analysis -> a final state-averaged CASSCF built on
    the recommended active space, with the completed job's orbital table
    additionally showing each orbital's character (sigma/pi/n/sigma*/pi*)
    and dominant localized atom(s). PySCF-only (engine is always 'pyscf').
    Required params are just basis and n_states -- do NOT ask the user for
    active_electrons/active_orbitals for this job_type, that's what it
    produces. Before offering this job_type, first search precedent
    literature the normal way (search_knowledge_base(doc_type='paper'),
    then search_academic_literature if needed -- see this app's knowledge-
    source hierarchy) and summarize it for the user; pass a short version
    of that summary as `literature_notes` so it's captured on the job
    itself, not just in the chat transcript. Then ask in plain chat
    whether they want to run the Single-Orbital-Entropy method -- this is
    a conversational check, not a substitute for the approval card (which
    still pauses before anything actually runs, same as every other job_
    type, and is the real safety gate).

    `entropy_method` picks the pilot screening backend: 'exact_fci'
    (default) computes entropies exactly via CASCI, capped at a 12-orbital
    pilot space (an exact-FCI machine-cost ceiling, not user-configurable)
    -- fast, no extra dependency. 'dmrg' uses a real DMRG pilot (block2)
    instead, capped much higher (tens of orbitals) -- lets a much larger,
    more basis-faithful AVAS candidate pool be screened at the cost of an
    approximate (not exact) entropy estimate and a slower job. Default to
    'exact_fci'; offer 'dmrg' when the user wants a more basis-accurate
    recommendation (especially at a non-minimal basis, where AVAS's
    candidate pool tends to exceed the exact-FCI ceiling and gets
    truncated) or explicitly asks about DMRG. `dmrg_bond_dim` (default
    250) only affects the DMRG pilot's cost/accuracy, never the final
    CASSCF -- leave it unset unless there's a specific reason to change it.

    Only pass avas_aolabels/max_active_orbitals if the user has a specific
    reason to narrow the pilot screen or the recommended space's size (e.g.
    they name a specific conjugated fragment or metal center) -- otherwise
    leave them unset and let the defaults apply. Treat the recommendation
    as a starting point for the user to confirm, not a final answer to act
    on silently -- same "don't guess chemically significant choices on the
    user's behalf" rule as everywhere else in this app.

    neb_ts runs a Nudged Elastic Band transition-state search (ORCA's
    native !NEB-TS) between the active molecule (the reactant -- via
    set_molecule, as usual) and a product structure the user must also
    supply via set_pes_scan_endpoint (the same "second endpoint geometry"
    tool pes_scan's two-molecule mode uses -- call it in addition to, not
    instead of, set_molecule, both within your handling of the one message
    that describes the reaction). ALWAYS ask the user explicitly whether to
    pre-optimize the reactant/product endpoints first (`preopt`) if they
    haven't already said -- there is no default for this, unlike every
    other neb_ts parameter. `n_images` (movable images between the fixed
    endpoints) defaults to 6 if not specified. The search runs on the
    ground-state PES by default; pass `target_state` (1 = first excited
    state, 2 = second, ...) to run it directly on an excited-state PES
    instead (via ORCA's TD-DFT/TD-HF gradients) -- explain to the user that
    this is a genuinely different, more expensive calculation than a
    ground-state search, not just an extra readout. This is a single ORCA
    job (ORCA parallelizes the path images itself), unlike pes_scan's
    master/sub-job architecture. Once complete, the UI shows a frame-by-
    frame geometry slider (the converged path, with the refined TS
    structure as its own distinguished frame), a reaction-path energy
    plot, and per-image molecular orbitals -- you don't need to do
    anything extra to enable any of that. PySCF has no NEB implementation
    in this app; engine is always 'orca' for this job_type.

    custom is for an ORCA/BAGEL calculation that doesn't map onto any of
    the other job_types above (e.g. an IRC path search, a relaxed
    surface scan, a property calculation this app has no dedicated parser
    for) -- pass the complete literal input text you've composed yourself
    as raw_input_text, and an explicit engine of 'orca' or 'bagel' (PySCF
    has no literal input-file format for a raw job). Build its geometry
    block from the currently active molecule's own coordinates, not a
    re-derived/re-typed copy, so the geometry shown in the UI can never
    drift from what actually ran. This still goes through the same
    approval-card + background-execution pipeline as any other job -- the
    user can review and further hand-edit your text before it runs -- but
    there is no job-type-specific result parsing afterward, since there's
    no registered job_type to parse against; report results from
    check_job_status's returned summary (which includes a tail of the raw
    output) rather than assuming any particular structured field is
    present. Pass calculation_description (a short label, e.g. "NEB
    transition-state search") so the job gets a meaningful name in the Job
    Manager and the manual/reference-doc lookup on the approval card is
    actually relevant to what you're running (a custom job has no
    method/basis of its own to build that query from otherwise). A
    structural syntax check still runs on your composed text, but only as
    a non-blocking warning shown on the approval card -- it is not a hard
    gate for this job_type, since custom's entire purpose is carrying
    ORCA/BAGEL syntax this app's other job_types never see.

    pes_scan runs a whole scan as one "master" job that spawns one real
    sub-job per image, in parallel, under the same resource-gated job
    manager as everything else: `scan_job_type` picks which job_type runs
    at each image (default 'single_point' for a ground-state-only curve;
    tddft/casscf/caspt2/eom_ccsd for one energy curve per electronic
    state -- takes that job_type's own required params too, e.g.
    n_states/active_electrons/active_orbitals for casscf). There are two
    ways to describe the scan itself: (1) two endpoint geometries -- call
    set_molecule for the "start" structure and set_pes_scan_endpoint for
    the "end" structure (both before calling submit_job, same reasoning as
    below), then this interpolates a path between them via
    `interpolation_method` ('idpp' default -- Image Dependent Pair
    Potential, aligns the two structures then iteratively avoids atom
    clashes across the whole path; 'liic' -- true Linear Interpolation in
    Internal Coordinates, bond/angle/dihedral values interpolated
    linearly; or 'linear' -- naive Cartesian interpolation, cheapest but
    can produce unphysical intermediate geometries for anything but a
    small displacement). If asked, explain that IDPP is the default
    because it's generally the best-behaved of the three without any
    chemistry-specific tuning, and that it and LIIC are both meaningfully
    better than plain linear/Cartesian interpolation. (2) a single
    molecule's own bond/angle/dihedral scanned over `coordinate` +
    `scan_range` (same as before). Either way, `n_points` sets how many
    images (including both endpoints). The approval card previews only
    the first image's input -- every other image uses identical
    parameters against a different geometry, so a parameter edit there
    (e.g. CAS iterations, convergence thresholds) propagates to every
    image automatically; a raw hand-edited ORCA/BAGEL input *text* edit
    only ever applies to that first image's own file, not the rest of the
    scan. Once approved, check_job_status/the Job Manager panel show the
    master job's aggregate progress and (once complete) its PES plot;
    each image's own sub-job is separately viewable (molecule/output/log)
    nested under the master.

    Excited-state methods all go through existing job_types, not separate
    ones -- CIS is tddft with qc_method='hf' and use_tda=True (default);
    TD-HF/RPA is qc_method='hf' with use_tda=False; TDA-DFT/full TDDFT are
    qc_method='dft' with use_tda True/False. EOM-CCSD is its own job_type
    (always post-HF-CCSD, no qc_method choice) and defaults to ORCA, since
    only ORCA computes oscillator strengths for it here -- PySCF is
    available if explicitly requested but reports energies only.
    State-averaged casscf (n_states > 1) also gives excited states; pass
    want_oscillator_strengths=True to get UV/Vis intensities for it too --
    this automatically routes to ORCA (the only engine of the three that
    computes them for CASSCF here) unless a different engine was
    explicitly requested, in which case oscillator strengths come back
    unavailable rather than fabricated. caspt2 (BAGEL only -- ORCA doesn't
    implement CASPT2) is energies-only in this app.

    Unlike generate_job_input, this tool does NOT accept a
    molecule_identifier -- the active molecule must already be set (call
    set_molecule by itself first, as its own step, if the user named a new
    one in this message; both calls still happen within your handling of
    this one message, no extra round-trip needed). This is because
    submit_job PAUSES after building the job spec to show the user the
    exact input and get their explicit approval before anything actually
    runs, and that pause internally re-runs this tool's setup logic -- so
    it must not depend on anything that could give a different answer the
    second time around, like a fresh molecule lookup.

    You do not need to ask for confirmation yourself before calling this --
    the approval pause is automatic and handled by the UI. If you are
    missing information this tool needs (e.g. basis set, active space
    size, which internal coordinate to scan), DO NOT guess -- call this
    tool anyway with what you have; it will tell you exactly which
    parameters are still missing so you can ask the user. If the requested
    engine can't run this job_type/method at all, the tool reports that
    clearly (with which engines can) -- relay that to the user rather than
    silently retrying with a different engine yourself. If the user
    rejects the approval, the job is not run; ask what they'd like to
    change or whether to cancel. For ORCA and BAGEL, the user can also
    hand-edit the shown input text before running it -- the UI validates
    that edited text (structural/keyword sanity checks, not a full run)
    before it's ever submitted here, and if the edit changes the input
    enough that the job_type-specific parser can't find expected results
    after a real run, the job fails with the raw engine output preserved
    rather than silently returning wrong numbers.

    qc_method is 'hf' or 'dft' (single_point/geometry_optimization/
    frequency/tddft; not used for eom_ccsd). engine picks the backend
    explicitly (pyscf/orca/bagel); if omitted a sensible default is chosen
    automatically (BAGEL for caspt2, ORCA for eom_ccsd, PySCF for
    everything else unless want_oscillator_strengths routes casscf to
    ORCA).

    When a job you submitted FAILS, you should investigate and retry
    automatically rather than just reporting the failure and stopping --
    call check_job_status for the error detail, consult
    search_knowledge_base(doc_type='manual') for correct keywords/syntax,
    and web_search for the specific error message if that isn't enough --
    not search_academic_literature, which covers published papers, not
    software error messages. Then call submit_job again with corrected
    parameters and retry_of_job_id set to
    the job_id that failed. You only need to pass the parameter(s) you're
    actually correcting -- anything you omit is automatically carried
    forward from the failed job, so don't re-specify the whole original
    call from memory. This still pauses for the user's approval like any
    other submit_job call (they see exactly what changed before it runs),
    it just links the new job to the failed one for tracking
    and shows "retry N of M" on the approval card. Do not ask the user's
    permission before attempting a retry; the approval card is that
    permission step. There is a hard cap on automatic retries per
    failure chain (enforced by the app, not by you) -- if a job-finished
    notice tells you the chain has already exhausted its retry budget,
    do NOT call submit_job again for it; explain what was tried and why
    it kept failing, and ask the user how they'd like to proceed instead.
    """
    molecule = state.get("molecule") if state else None
    if not molecule:
        return Command(update={"messages": [ToolMessage(
            content="No molecule is set yet. Call set_molecule first, then call submit_job again.",
            tool_call_id=tool_call_id,
        )]})
    # Read (never resolve) fresh on every call, including on interrupt-
    # resume -- a plain state read, not a network call, so it's safe to
    # reread every time (same reasoning as `molecule` above). Only
    # consulted for job_type == 'pes_scan'.
    end_molecule = state.get("pes_scan_end_molecule") if state else None

    raw_params = _collect_params(
        qc_method, basis, functional, active_electrons, active_orbitals, n_states, weights,
        orbital_indices, coordinate_type, coordinate_atoms, scan_range, n_points, ms_caspt2,
        shift, frozen_core, df_basis, max_steps, temperature_K, use_tda, want_oscillator_strengths,
        scan_job_type, interpolation_method, raw_input_text, calculation_description,
        preopt, n_images, target_state, max_active_orbitals, avas_aolabels, literature_notes,
        entropy_method, dmrg_bond_dim, optimization_type, target_state_2,
    )
    retry_note = None
    if retry_of_job_id:
        # Provenance/display only -- see read_spec's docstring for why this
        # must degrade to "treat as retry 1" rather than raise if the prior
        # job's spec.json is gone, and count_failed_in_chain in base.py
        # (called from app/agent/job_watcher.py, not here) for the actual
        # retry-budget enforcement. Recomputing this identically on every resume is safe
        # the same way the rest of this function's pre-interrupt state is:
        # deterministic given retry_of_job_id and a spec.json this function
        # never itself mutates.
        prev_spec = read_spec(retry_of_job_id)
        prev_params = (prev_spec or {}).get("params", {})

        # A retry call only re-specifies the field(s) actually being
        # corrected -- _collect_params fills everything else with None,
        # which would otherwise silently drop unrelated params (e.g. a
        # retry that only corrects `basis` would lose `qc_method`) and the
        # job would fail missing_required_params instead of ever reaching
        # another approval card. Confirmed empirically via job_watcher.py's
        # end-to-end verification: a real retry call from the model
        # corrected 'basis' but omitted 'qc_method', which without this
        # fallback stalled the whole auto-retry chain on a "still missing:
        # method" error the model then just apologized for instead of
        # resubmitting. Any field this call DID specify still overrides
        # the original value -- this only fills in what was left unsaid.
        for key, value in raw_params.items():
            if value is None and key in prev_params and not key.startswith("_"):
                raw_params[key] = prev_params[key]
        if "coordinate" not in raw_params and "coordinate" in prev_params:
            raw_params["coordinate"] = prev_params["coordinate"]
        # raw_input_text (custom job_type) is popped out of spec.params and
        # re-stored as _raw_input before a spec is ever built (see
        # _build_custom_spec_or_error), so it's never present as
        # prev_params["raw_input_text"] the way an ordinary param would be
        # -- the generic carry-forward loop above can never find it there.
        # Without this, a retry that doesn't re-supply corrected text
        # itself would hit "still missing: raw_input_text" instead of ever
        # reaching another approval card.
        if raw_params.get("raw_input_text") is None and prev_params.get("_raw_input"):
            raw_params["raw_input_text"] = prev_params["_raw_input"]

        prev_retry_count = prev_params.get("_retry_count", 0)
        raw_params["_retry_count"] = prev_retry_count + 1
        raw_params["_retried_from"] = retry_of_job_id
        retry_note = f"Retry attempt {prev_retry_count + 1} of {MAX_AUTO_RETRIES} (previous attempt: job {retry_of_job_id})."

    spec, preview, kb_context, param_notes, scan_note, keyword_options, warnings, error = _build_spec_or_error(
        job_type, molecule, engine, raw_params, end_molecule=end_molecule,
    )
    if error:
        return Command(update={"messages": [ToolMessage(content=error, tool_call_id=tool_call_id)]})

    # Pauses the graph here (raises GraphInterrupt) until the UI resumes it
    # with Command(resume={"approved": bool, "spec": <dict>, "input_text":
    # <str, only for orca/bagel -- see render_approval_panel>}). On that
    # resume, LangGraph re-executes this ENTIRE function from the top --
    # everything above this line (molecule lookup from state, param
    # validation, spec/preview building) reruns and is discarded. That's
    # fine because none of it has side effects and `molecule`/`params` are
    # deterministic given the same state/args. What would NOT be fine is
    # relying on the freshly-rebuilt `spec` after resume: its job_id is
    # randomly regenerated each rebuild (JobSpec's default_factory), and a
    # network-backed molecule lookup (which submit_job deliberately doesn't
    # do -- see the docstring) could return a different structure the
    # second time. So the UI round-trips the *exact* spec dict it showed
    # the user back through the resume value, and we submit that verbatim
    # rather than the locally-rebuilt one.
    decision = interrupt({
        "kind": "job_approval",
        "job_type": job_type,
        "engine": spec.engine,
        "molecule_name": molecule.get("name"),
        "params": spec.params,
        "input_preview": preview,
        "scan_note": scan_note,
        "kb_context": kb_context,
        "param_corrections": param_notes,
        "input_warnings": warnings,
        "keyword_options": keyword_options,
        "retry_note": retry_note,
        "spec": spec.to_dict(),
    })

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
    if input_text is not None:
        if approved_spec.method != "custom":
            errors = validate_input(approved_spec.engine, input_text)
            if errors:
                content = (
                    f"The edited {approved_spec.engine} input has problems and was NOT run: "
                    f"{'; '.join(errors)}. Ask the user to fix these or revert to the generated input."
                )
                return Command(update={"messages": [ToolMessage(content=content, tool_call_id=tool_call_id)]})
        if approved_spec.method != "pes_scan":
            approved_spec.params["_raw_input"] = input_text
        # For pes_scan, a hand-edited input applies to image 0's own
        # sub-job only (see below) -- it's a fixed block of text with one
        # specific geometry baked in, so broadcasting it unchanged to
        # every image via approved_spec.params (shared by all of them)
        # would silently give every image the same, wrong geometry.

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

    if approved_spec.method == "pes_scan":
        images, coordinate_values, coordinate_label = _build_scan_images(approved_spec.params)
        job_id = get_job_manager().submit_scan(
            approved_spec, images, coordinate_values, coordinate_label,
            image0_raw_input=input_text if input_text is not None else None,
            owner_user_id=owner_user_id,
        )
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


@tool
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


@tool
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


STATIC_TOOLS = [
    set_molecule, set_pes_scan_endpoint, generate_job_input, submit_job, check_job_status,
    plot_excited_state_spectrum, plot_ir_spectrum, plot_job_comparison, search_knowledge_base,
    search_academic_literature, web_search,
]


def get_all_tools() -> list:
    return STATIC_TOOLS
