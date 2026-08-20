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
from pathlib import Path
from typing import Annotated, Optional

from langchain_core.messages import ToolMessage
from langchain_core.tools import InjectedToolCallId, StructuredTool, tool
from pydantic import BaseModel, ConfigDict
from langgraph.prebuilt import InjectedState
from langgraph.types import Command, interrupt

from app.agent.scholar_search import search_academic_literature
from app.agent.state import AgentState
from app.agent.web_search import web_search
from app.chemistry.registry2.capabilities import get_caps
from app.chemistry.registry2.elicitation import (
    format_keyword_options, keyword_options_for, validate_draft,
)
from app.chemistry.registry2.lookup import (
    capability_answer, describe_engine, resolve_method, resolve_task,
)
from app.chemistry import geometry_upload
from app.chemistry.jobs import interpolate
from app.chemistry.jobs.dispatch import NOT_YET_IMPLEMENTED, resolve_runner
from app.chemistry.jobs.base import (
    BATCH_ONLY_PARAM_KEYS, ENSEMBLE_ONLY_PARAM_KEYS, JobSpec, SCAN_ONLY_PARAM_KEYS, get_job_manager, read_meta,
    read_spec, result_artifact_transaction, sub_job_ids_of, write_meta,
)
from app.chemistry.jobs.ensemble_spectrum import pool_ensemble_transitions
from app.chemistry.jobs.keyword_suggest import suggest_basis_options, suggest_functional_options
from app.chemistry.jobs.param_normalize import normalize_basis, normalize_method
from app.chemistry.jobs.preview import build_input_preview
from app.chemistry.jobs.scan_template import substitute_geometry
from app.chemistry.registry2.params import PARAMS_BY_NAME
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

_COORDINATE_ATOM_COUNT = {"bond": 2, "angle": 3, "dihedral": 4}


def _scan_shape_error(params: dict, molecule: dict) -> Optional[str]:
    """Why this scan's coordinate/range cannot be read, in a sentence the
    model can act on. None when they are fine.

    Exists because the alternative is an exception thrown from inside the
    geometry builder, which escapes submit_draft and leaves the user with
    no approval card and no explanation. Every shape checked here is one a
    model actually produced or plausibly would: atom numbers as strings, a
    coordinate written as free text, a range given as {"start": ..,
    "stop": ..}, and -- the one worth catching by name -- 0-based atom
    indices, which this app never uses anywhere a model or a user can see
    (CLAUDE.md; RDKit's 0-based numbering is converted at that boundary and
    never leaks outward).
    """
    # A two-geometry interpolation carries no coordinate at all.
    if params.get("_end_molecule") is not None:
        return None

    coordinate = params.get("coordinate")
    if not isinstance(coordinate, dict):
        return (f"`coordinate` must be an object like "
                f"{{'type': 'bond', 'atoms': [1, 2]}}, not {type(coordinate).__name__}. "
                f"Ask the user which coordinate to scan and over which atoms.")

    kind = str(coordinate.get("type", "")).lower()
    if kind not in _COORDINATE_ATOM_COUNT:
        return (f"`coordinate.type` must be one of bond, angle or dihedral -- got "
                f"{coordinate.get('type')!r}.")

    atoms = coordinate.get("atoms")
    if not isinstance(atoms, (list, tuple)):
        return (f"`coordinate.atoms` must be a list of atom numbers, e.g. [1, 2] for a "
                f"bond. Got {type(atoms).__name__}.")
    try:
        atoms = [int(a) for a in atoms]
    except (TypeError, ValueError):
        return f"`coordinate.atoms` must be whole numbers; got {list(atoms)!r}."

    expected = _COORDINATE_ATOM_COUNT[kind]
    if len(atoms) != expected:
        return (f"A {kind} scan needs exactly {expected} atom numbers; "
                f"got {len(atoms)}: {atoms}.")

    n_atoms = len(molecule.get("symbols") or [])
    if any(a < 1 for a in atoms):
        return (f"Atom numbers are 1-based here -- the same numbers shown in the 3D "
                f"viewer -- and {atoms} contains one below 1. The first atom is 1, "
                f"not 0.")
    if n_atoms and any(a > n_atoms for a in atoms):
        return (f"This molecule has {n_atoms} atoms, so {atoms} refers to one that does "
                f"not exist. Atom numbers are 1-based and match the 3D viewer.")
    # Write the coerced numbers back. `["1", "2"]` is a formatting slip of
    # exactly the kind the draft shape absorbs elsewhere, and refusing it
    # here while accepting it two lines above would be arbitrary -- the
    # geometry builder does arithmetic on these and only wants them to be
    # numbers.
    coordinate["atoms"] = atoms

    scan_range = params.get("scan_range")
    if not isinstance(scan_range, (list, tuple)) or len(scan_range) != 2:
        return (f"`scan_range` must be [start, stop] -- two numbers -- not "
                f"{scan_range!r}.")
    try:
        float(scan_range[0]), float(scan_range[1])
    except (TypeError, ValueError):
        return f"`scan_range` must be two numbers; got {list(scan_range)!r}."
    return None


def _build_scan_images(params: dict) -> tuple[list[dict], list[float], str, list[str]]:
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
    warnings: list[str] = []
    if end_molecule:
        method = params.get("interpolation_method") or "idpp"
        images, warnings = interpolate.build_path(molecule, end_molecule, n_points, method)
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
    return images, [float(v) for v in coordinate_values], coordinate_label, warnings


def _build_scan_spec_or_error(molecule: dict, engine: Optional[str], method: Optional[str],
                              params: dict, param_notes: list[str], task: str = "pes_1d"):
    """pes_1d/interp_pes-specific half of _build_spec_or_error: builds the
    full image list and returns a "master" JobSpec (molecule=images[0] as a
    sane single-geometry fallback for generic molecule viewers -- task/
    subtype stamped by the caller, _spec_from_draft) whose preview is image
    0's own sub-job input -- per the approval-card design, only the first
    image's input is shown, since every other image uses identical
    parameters against a different geometry. Every image runs the same
    thing: a single_point/gs job at the master's own method (see
    dispatch.py's module docstring for why a scan's sub-jobs are always
    single_point/gs, never a separate choice).

    Required-param validation is registry2's job (validate_draft gates
    submit_draft's call into this builder), not this function's -- see
    docs/TRACKER.md's P2B.1 note."""
    params["_scan_start_molecule"] = molecule

    # Checked before the scan shape is built below: which of the two scan
    # modes (two endpoints vs. one coordinate) is even being requested has
    # to be settled before anything about the resulting geometries can be.
    has_endpoint = bool(params.get("_end_molecule"))
    has_coordinate = bool(params.get("coordinate") and params.get("scan_range"))
    if not has_endpoint and not has_coordinate:
        return None, None, None, None, None, None, [], (
            "This scan needs either a second endpoint geometry (call set_pes_scan_endpoint for the 'end' "
            "structure, in addition to set_molecule for the 'start' structure) or both 'coordinate' and "
            "'scan_range' for a single-molecule bond/angle/dihedral scan. Ask the user which they want."
        )

    # The sub-job every image runs: single_point/gs at the master's own
    # method, always -- see this function's docstring. `method` is injected
    # here (not persisted on the master's own `params`) so
    # _kb_context_for_job/_keyword_options_for_job below see it the same
    # way they always have; preview.py injects it again for `preview_spec`
    # from `preview_spec.method` regardless (see its own module docstring).
    sub_params = {k: v for k, v in params.items() if k not in SCAN_ONLY_PARAM_KEYS and not k.startswith("_")}
    sub_params["method"] = method

    shape_error = _scan_shape_error(params, molecule)
    if shape_error:
        return None, None, None, None, None, None, [], shape_error

    try:
        images, coordinate_values, coordinate_label, scan_warnings = _build_scan_images(params)
    except Exception as e:
        # Deliberately broad. `_build_scan_images` indexes and arithmetics
        # its way through model-supplied structures, so a shape it did not
        # expect surfaces as TypeError, KeyError or OverflowError rather
        # than the ValueError this used to catch -- and an uncaught
        # exception here escapes submit_draft entirely: no approval card,
        # and a raw traceback where the model expected an answer. That is
        # what two job-matrix scan cells were doing. `_scan_shape_error`
        # above catches the shapes worth explaining; this catches whatever
        # is left, as a message rather than a crash.
        return None, None, None, None, None, None, [], (
            f"Could not build this scan's geometries: {type(e).__name__}: {e}. "
            f"Check the scanned coordinate and its range."
        )

    # `engine` is already registry2's resolved_engine by the time a ready
    # draft reaches this builder (see _spec_from_draft) -- routing is
    # decided once, in validate_draft, not re-derived per builder.
    resolved_engine = engine

    spec = JobSpec(method=method or "", engine=resolved_engine, molecule=images[0], params=params)
    try:
        preview_spec = JobSpec(task="single_point", subtype="gs", method=method or "",
                               engine=resolved_engine, molecule=images[0], params=sub_params)
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
    if task == "interp_pes":
        # P7.2: names the pipeline explicitly (alignment/reconciliation of
        # the two endpoints, interpolation, then one single-point per
        # image) and states the cascade rule -- an edit here is a TEMPLATE
        # applied to every image via geometry substitution, unlike
        # pes_1d's edit-applies-to-image-1-only rule below. Both rules are
        # stated on both notes so a user who has seen the other scan type
        # is not left assuming this one behaves the same way.
        scan_note = (
            f"This path has three steps: align the two endpoint geometries (best-effort atom "
            f"reorder if needed, always flagged above when it happens), interpolate "
            f"{len(images)} images between them, then run this single-point calculation at each "
            f"image. Preview of image 1 of {len(images)}. If you edit this input, your edit "
            f"becomes a TEMPLATE applied to every image -- only the geometry block is substituted "
            f"per image, everything else you changed carries through to all of them."
        )
    else:
        scan_note = (
            f"Preview of image 1 of {len(images)} along the scan -- every other image uses these "
            f"exact same parameters against a different geometry. If you edit this input, the edit "
            f"applies to image 1 ONLY -- every other image still uses the generated input for its "
            f"own geometry."
        )

    runner_key, _ = resolve_runner("single_point", "gs", method)
    kb_context = _kb_context_for_job(resolved_engine, runner_key or "single_point", sub_params)
    keyword_options = _keyword_options_for_job(runner_key or "single_point", sub_params, resolved_engine)
    return spec, preview, kb_context, param_notes, scan_note, keyword_options, scan_warnings, None


def _resolve_batch_geometries(source_geometry_set_job_id: str) -> tuple[Optional[list[dict]], Optional[str]]:
    """(geometries, None) or (None, error). Re-reads a geometry_set job's
    own path_xyz fresh from disk rather than carrying a copy across the
    interrupt/resume boundary -- same "rebuild from a persisted reference"
    pattern pes_1d/interp_pes use for _scan_start_molecule/_end_molecule
    and wigner_spectra uses for its whole regenerate-from-seed approach,
    so this one function serves both the draft-preview call (build time)
    and the post-approval call (submit time) identically.

    Each geometry is defaulted to charge=0/multiplicity=1 -- a
    GeometryFrame (app/chemistry/geometry_upload.py) carries only
    symbols/coords/name, xmol XYZ has no field for either, and every
    other master task that copies one "template" molecule across several
    images (pes_1d/interp_pes's own scan images) already has this same
    limitation, so a batch inheriting it is consistent rather than a new
    gap. A charged/open-shell system needs charge/multiplicity params on
    the batch draft, not built in this pass."""
    source_spec = read_spec(source_geometry_set_job_id)
    if source_spec is None or source_spec.get("task") != "geometry_set":
        return None, (
            f"'{source_geometry_set_job_id}' is not a geometry_set job. Ask which geometry set "
            f"(3+ tagged geometries held together) the batch should run over."
        )
    source_result = get_job_manager().result(source_geometry_set_job_id)
    path_xyz = ((source_result or {}).get("artifacts") or {}).get("path_xyz")
    if not path_xyz:
        return None, f"Geometry set '{source_geometry_set_job_id}' has no geometries on disk."
    try:
        frames = geometry_upload.parse_multi_frame_xyz(Path(path_xyz).read_text())
    except Exception as e:
        return None, f"Could not read geometry set '{source_geometry_set_job_id}': {type(e).__name__}: {e}"
    if not frames:
        return None, f"Geometry set '{source_geometry_set_job_id}' has no geometries."
    return [
        {"charge": 0, "multiplicity": 1, "symbols": list(f.symbols), "coords": f.coords, "name": f.name}
        for f in frames
    ], None


def _build_batch_spec_or_error(molecule: dict, engine: Optional[str], method: Optional[str],
                               params: dict, param_notes: list[str]):
    """batch-specific half of _build_spec_or_error (P7.4): fans a
    single_point/gs job at (method, engine, params) out over every
    geometry in an existing geometry_set job
    (params['source_geometry_set_job_id']), one child per geometry -- the
    same "master JobSpec whose preview is the first child's own input"
    shape _build_scan_spec_or_error already established for pes_1d/
    interp_pes. Scoped to single_point/gs children in this pass (see
    docs/TRACKER.md's P7.4 note) -- a future phase can widen this the same
    way wigner_spectra's own children are currently fixed at
    single_point/ee.

    Required-param validation for method/basis/source_geometry_set_job_id
    is registry2's job (validate_draft gates submit_draft's call into this
    builder), not this function's -- see docs/TRACKER.md's P2B.1 note."""
    geometries, error = _resolve_batch_geometries(params["source_geometry_set_job_id"])
    if error:
        return None, None, None, None, None, None, [], error

    sub_params = {k: v for k, v in params.items() if k not in BATCH_ONLY_PARAM_KEYS and not k.startswith("_")}
    sub_params["method"] = method

    resolved_engine = engine
    spec = JobSpec(method=method or "", engine=resolved_engine, molecule=geometries[0], params=params)
    try:
        preview_spec = JobSpec(task="single_point", subtype="gs", method=method or "",
                               engine=resolved_engine, molecule=geometries[0], params=sub_params)
        preview = build_input_preview(preview_spec)
    except Exception as e:
        return None, None, None, None, None, None, [], f"Could not build the input for this batch's first job: {e}"

    batch_note = (
        f"Preview of job 1 of {len(geometries)} in this batch (geometry set "
        f"'{params['source_geometry_set_job_id']}') -- every other job uses these exact same "
        f"parameters against a different geometry. If you edit this input, the edit applies to "
        f"job 1 ONLY -- every other job still uses the generated input for its own geometry."
    )

    runner_key, _ = resolve_runner("single_point", "gs", method)
    kb_context = _kb_context_for_job(resolved_engine, runner_key or "single_point", sub_params)
    keyword_options = _keyword_options_for_job(runner_key or "single_point", sub_params, resolved_engine)
    return spec, preview, kb_context, param_notes, batch_note, keyword_options, [], None


def _build_neb_ts_spec_or_error(molecule: dict, engine: Optional[str], method: Optional[str],
                                params: dict, param_notes: list[str]):
    """neb_ts-specific half of _build_spec_or_error: reactant is the
    active `molecule` (same as every other job_type), product comes from
    params['_end_molecule'] (set by _build_spec_or_error from `end_molecule`,
    which both generate_job_input/submit_job source from
    state['pes_scan_end_molecule'] -- same second-endpoint-geometry slot
    pes_scan's two-molecule mode uses, via the same set_pes_scan_endpoint
    tool call; there is no NEB-specific endpoint tool). Unlike pes_scan,
    NEB-TS is a single ORCA job (ORCA parallelizes the path images itself
    via %pal), so this returns one ordinary JobSpec, not a "master" one.

    Required-param validation is registry2's job, not this function's --
    see docs/TRACKER.md's P2B.1 note."""
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

    resolved_engine = engine

    # task/subtype stamped here, not left for _spec_from_draft's caller to
    # add after this function returns (see that function's own comment) --
    # build_input_preview below needs dispatch.resolve_runner(spec.task,
    # spec.subtype, spec.method) to resolve a runner key at all, unlike
    # the other bespoke builders (_build_scan_spec_or_error et al.), whose
    # own internal preview call is against a SEPARATE, already-stamped
    # preview_spec (a "single_point/gs" child template), not the real
    # spec this one builds directly. Confirmed as a real, reachable defect
    # through the actual validate_draft/_spec_from_draft path (P7.5's own
    # NEB regression check), not a hypothetical: a bare
    # JobSpec(method=..., ...) with no task ever set resolves
    # dispatch.resolve_runner("", "", method) -> "No runner is wired up
    # for / yet.", breaking every neb_ts approval card unconditionally.
    spec = JobSpec(task="neb_ts", subtype="", method=method or "", engine=resolved_engine,
                   molecule=molecule, params=params)
    try:
        preview = build_input_preview(spec)
    except Exception as e:
        return None, None, None, None, None, None, [], f"Could not build the input for this job: {e}"

    # A throwaway copy, not persisted on spec.params -- see dispatch.py's
    # module docstring for why `method` lives only on `spec.method` now.
    kb_context = _kb_context_for_job(resolved_engine, "neb_ts", {**params, "method": method})
    keyword_options = _keyword_options_for_job("neb_ts", {**params, "method": method}, resolved_engine)
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


def _build_ensemble_spec_or_error(molecule: dict, engine: Optional[str], method: Optional[str],
                                  params: dict, param_notes: list[str]):
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
    actually runs after approval.

    Required-param validation is registry2's job, not this function's --
    see docs/TRACKER.md's P2B.1 note."""
    n_samples = params["n_samples"]
    if not isinstance(n_samples, int) or n_samples < 1 or n_samples > _MAX_ENSEMBLE_SAMPLES:
        return None, None, None, None, None, None, [], (
            f"n_samples must be an integer between 1 and {_MAX_ENSEMBLE_SAMPLES} (got {n_samples!r})."
        )

    # The sub-job every sample runs: single_point/ee at the master's own
    # method (see dispatch.py's module docstring -- tddft for a hf/dft
    # reference, eom_ccsd/casscf/caspt2 for those methods directly).
    scan_job_type, _ = resolve_runner("single_point", "ee", method)
    if scan_job_type not in _ALLOWED_ENSEMBLE_JOB_TYPES:
        return None, None, None, None, None, None, [], (
            f"wigner_ensemble needs a method that reports excitation energies -- got a runner of "
            f"'{scan_job_type}' for method='{method}' (allowed: {sorted(_ALLOWED_ENSEMBLE_JOB_TYPES)}, the "
            f"job types that can report per-transition oscillator strengths for this feature to pool)."
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
    if source_spec.get("task") not in ("freq", "opt_freq"):
        return None, None, None, None, None, None, [], (
            f"source_frequency_job_id='{source_id}' is a '{source_spec.get('task') or 'unknown'}' job, not "
            f"a 'freq' or 'opt_freq' job -- wigner_ensemble needs a completed frequency calculation's "
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
    if source_spec.get("task") == "opt_freq":
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
    sub_params["method"] = method
    resolved_engine = engine

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

    spec = JobSpec(method=method or "", engine=resolved_engine, molecule=equilibrium_molecule, params=params)
    try:
        preview_spec = JobSpec(task="single_point", subtype="ee", method=method or "",
                               engine=resolved_engine, molecule=samples[0], params=sub_params)
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
    task: str, subtype: str, molecule: dict, engine: Optional[str], method: Optional[str],
    raw_params: dict, end_molecule: Optional[dict] = None,
):
    """Shared by every draft that reaches READY: normalizes the method/basis
    parameters, builds the JobSpec, renders its input preview, and looks up
    manual/reference-doc context for it, and computes the basis/method-
    keyword disambiguation menu (see keyword_suggest.py). Returns
    (spec, preview_text, kb_context, param_notes, scan_note, keyword_options, warnings, error_str) --
    exactly one of (spec, preview_text, kb_context, param_notes, keyword_options, warnings) / error_str
    is populated (param_notes/warnings are always lists, possibly empty; keyword_options is
    a dict or None). scan_note
    is only ever populated for a pes_1d/interp_pes job (display-only context
    about which image the preview shows) -- kept OUT of preview_text itself
    since that string doubles as the literal raw-input text an editable-
    engine approval card round-trips back verbatim (see submit_draft's
    docstring). warnings is populated for a task='blind' job (non-blocking
    structural-validation complaints about the agent-composed
    raw_input_text -- see _build_custom_spec_or_error) and for an
    interp_pes job whose two endpoints needed a best-effort atom reorder
    (see interpolate._reconcile_endpoints, surfaced via _build_scan_images).

    `task`/`subtype`/`method` are what registry2.elicitation.validate_draft
    already decided this draft means; nothing here re-derives what a task
    requires or where it runs (see P2B.1's tracker note). The one thing
    still derived here is which run_*/build_input_preview function family a
    (task, subtype, method) maps to -- dispatch.resolve_runner, the same
    derivation each worker's main() and preview.py use, called here only to
    label the KB-grounding query and the basis/functional keyword menu the
    way they always have (see _kb_context_for_job/_keyword_options_for_job).
    """
    params = {k: v for k, v in raw_params.items() if v is not None}
    if end_molecule is not None:
        params["_end_molecule"] = end_molecule
    # Not a real registry param for any task -- only ever consumed by
    # _build_custom_spec_or_error below -- so it's popped here rather than
    # left to show up as a stray key in spec.params/the approval card's
    # flat params line for every other task.
    calculation_description = params.pop("calculation_description", None)

    # Mechanical typo/formatting correction -- see param_normalize.py's
    # module docstring. Runs before the spec/preview are built so a
    # corrected value is what actually gets used.
    param_notes: list[str] = []
    if method:
        method, note = normalize_method(method)
        if note:
            param_notes.append(note)
    if "basis" in params:
        params["basis"], note = normalize_basis(params["basis"])
        if note:
            param_notes.append(note)

    if task in ("pes_1d", "interp_pes"):
        return _build_scan_spec_or_error(molecule, engine, method, params, param_notes, task=task)

    if task == "neb_ts":
        return _build_neb_ts_spec_or_error(molecule, engine, method, params, param_notes)

    if task == "wigner_spectra":
        return _build_ensemble_spec_or_error(molecule, engine, method, params, param_notes)

    if task == "batch":
        return _build_batch_spec_or_error(molecule, engine, method, params, param_notes)

    if task == "blind":
        return _build_custom_spec_or_error(engine, molecule, params, param_notes, calculation_description)

    # registry2's ParamSpec table can't express "present but out of range" --
    # this is exactly the CAS active_electrons/active_orbitals cross-field
    # requirement, already required_when method in the multireference set
    # (see registry2/params.py); kept here as the belt to registry2's
    # braces, same status as the n_samples range check in
    # _build_ensemble_spec_or_error -- not one of P2B.1's six/four removed
    # call sites.
    if task in ("opt", "freq", "opt_freq") and method in ("casscf", "caspt2"):
        cas_missing = [p for p in ("active_electrons", "active_orbitals") if params.get(p) is None]
        if cas_missing:
            needs = "; ".join(
                f"{p} ({PARAMS_BY_NAME[p].help if p in PARAMS_BY_NAME else 'no description'})"
                for p in cas_missing
            )
            return None, None, None, None, None, None, [], (
                f"Cannot prepare this '{task}' job with method='{method}' yet -- still "
                f"missing: {needs}. Ask the user for these specifically; do not assume default values."
            )

    resolved_engine = engine

    # Whether this engine/method combination can run a conical-intersection
    # search is exactly what capabilities.py's ci_opt evidence records --
    # BAGEL's gradient-projection MECP (opttype='conical') and ORCA's
    # %CONICAL block (hf/dft with a TDDFT reference) both genuinely work,
    # verified live; pyscf/geomeTRIC has no multi-state crossing-point mode
    # at all (capabilities: pyscf/casscf ci_opt is a documented gap). This
    # used to be a hardcoded "only engine=='bagel'" refusal that quoted
    # ORCA's SEPARATE %mecp module (a general same-or-different-spin-state
    # crossing search, not what this app's opt/ci task models) as evidence
    # ORCA couldn't do it -- caps.has("ci_opt") is the one source of truth
    # for this now, matching what QM_CAPABILITIES.md and the derived task
    # table already publish, so a draft that validates to READY can't then
    # be refused here on a fact the registry disagrees with.
    if subtype == "ci":
        caps = get_caps(resolved_engine, method or "")
        if caps is None or not caps.has("ci_opt"):
            return None, None, None, None, None, None, [], (
                f"{(resolved_engine or '?').upper()} has no verified conical-intersection optimizer for "
                f"method='{method}' in this app -- ask for a different engine/method, or BAGEL casscf/"
                f"caspt2 (gradient-projection MECP) / ORCA hf or dft (via TD-DFT, ground-state-inclusive "
                f"only)."
            )
        # ORCA's %CONICAL is verified only for a crossing that includes the
        # ground state (the manual's own worked example, and every
        # verification run here, is IROOT vs. the implicit ground state) --
        # the same "must include state 1" restriction sp/nac already
        # enforces for a single-reference method's NAC module, for the same
        # underlying reason (see tools.py's own state_pairs check below).
        if resolved_engine == "orca" and params.get("target_state") not in (None, 0):
            return None, None, None, None, None, None, [], (
                "ORCA's conical-intersection search (%CONICAL, via TD-DFT) is verified only for a "
                "crossing that includes the ground state -- omit target_state (or set it to 0) and give "
                "the excited partner as target_state_2."
            )
        # %CONICAL's gradient is built from the same native excited-state
        # gradient single_point/grad's own B88 refusal already guards --
        # ORCA refuses B3LYP/BLYP there for the same underlying reason
        # ('Third functional derivative of a B88 exchange-containing
        # functional'), so an opt/ci draft with such a functional would
        # crash at the first geometry cycle rather than search anything.
        if resolved_engine == "orca" and (params.get("functional") or "").strip().lower() in ("b3lyp", "blyp"):
            return None, None, None, None, None, None, [], (
                f"ORCA refuses a native excited-state gradient for functional="
                f"'{params.get('functional')}' (B88-containing) -- the same limitation that blocks an "
                f"excited-state single-point gradient blocks a conical-intersection search too (see "
                f"docs/PARSER_GAPS.md) -- ask for a different functional (e.g. PBE0) or a different engine."
            )
        # target_state_2 auto-defaults to a ground/first-excited seam
        # (BAGEL's own target=0/target2=1 convention, which ORCA's IROOT
        # numbering shares -- 0/omitted is the ground state, 1 is S1, ...)
        # but is always surfaced back into params so it shows on the
        # approval-card preview -- the human should see exactly which two
        # states before approving, per registry2's own description of this
        # param (ParamSpec.help).
        if params.get("target_state_2") is None:
            params["target_state_2"] = (params.get("target_state") or 0) + 1

    # registry2's ParamSpec table can't express "present but conditionally
    # unsupported" any more than the CAS active_electrons/active_orbitals
    # check above can -- tasks.TaskDef.requires("gradient") is static and
    # can't say "needs 'excited_gradient' only when target_state is set".
    # Every (engine, method) that claims gradient=True at all also has an
    # excited_gradient field (True, False, or resting on untrusted/no
    # evidence), so caps.has() alone decides this correctly without a
    # separate None check.
    #
    # Also covers opt/min: target_state's ParamSpec applies_to includes
    # "opt" (an excited-state geometry optimization needs the gradient at
    # every step, not just once), so the same hole existed there --
    # unguarded, an ORCA+B3LYP+opt/min+target_state draft would reach
    # READY and then build an input ORCA refuses at runtime. opt/ci is
    # deliberately excluded: it has its own ci_opt-gated check above,
    # which is the right capability for a crossing search, not this one.
    if (
        (task == "single_point" and subtype == "grad") or (task == "opt" and subtype == "min")
    ) and params.get("target_state"):
        caps = get_caps(resolved_engine, method or "")
        if caps is None or not caps.has("excited_gradient"):
            return None, None, None, None, None, None, [], (
                f"{(resolved_engine or '?').upper()} has no verified excited-state gradient for "
                f"method='{method}' in this app -- ask for the ground-state gradient (omit "
                f"target_state) or a different engine/method."
            )
        # ORCA refuses a native excited-state gradient for B88-containing functionals
        # (B3LYP, BLYP); a %method LibXC rewrite was tried here and produced a ground-
        # state energy ~1.2 Hartree off from native B3LYP (docs/PARSER_GAPS.md), so this
        # app refuses the combination outright instead of running a wrong functional.
        if resolved_engine == "orca" and (params.get("functional") or "").strip().lower() in ("b3lyp", "blyp"):
            return None, None, None, None, None, None, [], (
                f"ORCA refuses a native excited-state gradient for functional="
                f"'{params.get('functional')}' (B88-containing), and this app has no working LibXC "
                f"substitute for it (see docs/PARSER_GAPS.md) -- ask for a different functional "
                f"(e.g. PBE0) or a different engine."
            )

    # opt/constrained's `constraints` is free-form list-of-dicts from a
    # small model -- exactly the shape that broke five of seven plausible
    # scan-draft shapes at P2.9 (TypeError/KeyError escaping the tool with
    # no card). Validated here, once, before either runner's builder ever
    # indexes into it -- neither pyscf_runner nor orca_runner re-checks
    # this (P2B.1: registry2/tools.py decides, builders construct).
    if task == "opt" and subtype == "constrained":
        n_atoms = len(molecule.get("symbols") or [])
        n_atoms_for = {"bond": 2, "angle": 3, "dihedral": 4}
        for c in params.get("constraints") or []:
            if not isinstance(c, dict):
                return None, None, None, None, None, None, [], (
                    f"Each constraint must be an object like "
                    f"{{'type': 'bond', 'atoms': [1, 2], 'value': 0.98}} -- got {c!r}."
                )
            ctype, atoms, value = c.get("type"), c.get("atoms"), c.get("value")
            if ctype not in n_atoms_for:
                return None, None, None, None, None, None, [], (
                    f"Constraint type must be one of 'bond', 'angle', 'dihedral' -- got {ctype!r}."
                )
            want = n_atoms_for[ctype]
            if not (isinstance(atoms, list) and len(atoms) == want and all(isinstance(a, int) for a in atoms)):
                return None, None, None, None, None, None, [], (
                    f"A '{ctype}' constraint needs exactly {want} 1-based atom indices in 'atoms' -- "
                    f"got {atoms!r}."
                )
            if any(a < 1 or a > n_atoms for a in atoms):
                return None, None, None, None, None, None, [], (
                    f"Constraint atom indices must be between 1 and {n_atoms} (this molecule's atom "
                    f"count) -- got {atoms!r}."
                )
            if not isinstance(value, (int, float)):
                return None, None, None, None, None, None, [], (
                    f"Constraint 'value' must be a number (Angstrom for a bond, degrees for an angle or "
                    f"dihedral) -- got {value!r}."
                )

    # sp/nac's state_pairs is always exactly one pair -- see its ParamSpec
    # ("Between which pair of electronic states...", singular) and every
    # elicitation scenario that fills it. A single-reference method's NAC
    # module (ORCA's CIS/TDDFT here; PySCF has none) computes only the
    # ground-to-excited coupling (tasks._warn_nac_pairing already tells the
    # user this as a warning) -- an excited-to-excited pair on such a method
    # is not a caveat, it is not expressible in the input at all, so it is
    # refused here rather than silently building a job that can't run what
    # was asked.
    if task == "single_point" and subtype == "nac":
        pairs = params.get("state_pairs")
        if not isinstance(pairs, list) or len(pairs) != 1 or not (
            isinstance(pairs[0], (list, tuple)) and len(pairs[0]) == 2
        ):
            return None, None, None, None, None, None, [], (
                "state_pairs must be exactly one pair of 1-based state indices (including the ground "
                "state as 1), e.g. [[1, 2]] for the S0/S1 coupling."
            )
        s1, s2 = int(pairs[0][0]), int(pairs[0][1])
        if method in ("hf", "dft") and 1 not in (s1, s2):
            return None, None, None, None, None, None, [], (
                f"{(resolved_engine or '?').upper()}'s CIS/TDDFT module computes the ground-to-excited "
                f"coupling only for method='{method}' -- it has no excited-to-excited pair. Ask for a "
                f"state pair that includes the ground state (index 1)."
            )

    spec = JobSpec(task=task, subtype=subtype, method=method or "", engine=resolved_engine,
                   molecule=molecule, params=params)
    try:
        preview = build_input_preview(spec)
    except Exception as e:
        return None, None, None, None, None, None, [], f"Could not build the input for this job: {e}"

    runner_key, _ = resolve_runner(task, subtype, method)
    kb_context = _kb_context_for_job(spec.engine, runner_key or task, params)
    keyword_options = _keyword_options_for_job(runner_key or task, params, spec.engine)
    return spec, preview, kb_context, param_notes, None, keyword_options, [], None


def _build_custom_spec_or_error(
    engine: Optional[str], molecule: dict, params: dict, param_notes: list[str],
    calculation_description: Optional[str],
):
    """task == 'blind' half of _build_spec_or_error: for an ORCA/BAGEL
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

    # No level of theory -- a blind job carries only raw engine text (see
    # this function's own docstring). "" here, not "custom": that was the
    # v1 runner key, and dispatch.resolve_runner derives it fresh from
    # (task, subtype, method) at dispatch time instead of storing it.
    spec = JobSpec(
        method="", engine=engine, molecule=molecule, params=params,
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
    if (spec.get("task") or "") != "wigner_spectra":
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
    # the primary gate. Skipped for task == "blind": that task's whole
    # reason to exist is carrying ORCA/BAGEL syntax this validator was
    # never built to recognize (see _build_custom_spec_or_error's
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
    approved_task = approved_spec.task or ""
    is_scan_master = approved_task in ("pes_1d", "interp_pes")
    is_ensemble_master = approved_task == "wigner_spectra"
    is_batch_master = approved_task == "batch"
    if input_text is not None:
        if approved_task != "blind":
            errors = validate_input(approved_spec.engine, input_text)
            if errors:
                content = (
                    f"The edited {approved_spec.engine} input has problems and was NOT run: "
                    f"{'; '.join(errors)}. Ask the user to fix these or revert to the generated input."
                )
                return Command(update={"messages": [ToolMessage(content=content, tool_call_id=tool_call_id)]})
        if not is_scan_master and not is_ensemble_master and not is_batch_master:
            approved_spec.params["_raw_input"] = input_text
        elif is_batch_master:
            # Same single-job-only semantics as pes_1d (below), not
            # interp_pes's cascade template: a batch's children are
            # heterogeneous geometries from a tagged geometry_set, with no
            # "this is definitely the same path" framing the cascade
            # design leans on. Reuses submit_scan's own
            # "_image0_raw_input" key/convention (applies to whichever
            # child carries _batch_index == 0 -- see
            # batch_orchestrator.py's _dispatch_more) rather than
            # inventing a parallel one.
            approved_spec.params["_image0_raw_input"] = input_text
        elif approved_task == "interp_pes":
            # P7.2 cascade: unlike pes_1d (below), an interp_pes edit is a
            # TEMPLATE applied to every image via geometry substitution
            # (app/chemistry/jobs/scan_template.py), not image 0 alone --
            # every image is the same molecule at a different geometry, so
            # whatever the user changed (an extra keyword, a tightened
            # setting) is meant for all of them. Proven against this
            # spec's own starting geometry HERE, at approval time, rather
            # than discovered mid-scan when some later image's dispatch
            # would otherwise be the first thing to call substitute_geometry.
            try:
                substitute_geometry(approved_spec.engine, input_text, approved_spec.molecule)
            except ValueError as e:
                content = (
                    f"The edited {approved_spec.engine} input cannot be used as a template for every "
                    f"image: {e} Ask the user to fix the geometry block or revert to the generated input."
                )
                return Command(update={"messages": [ToolMessage(content=content, tool_call_id=tool_call_id)]})
        # For a pes_1d/wigner_spectra master, a hand-edited input applies
        # to sample/image 0's own sub-job only (see below, and see
        # submit_scan's image0_raw_input) -- it's a fixed block of text
        # with one specific geometry baked in, so broadcasting it
        # unchanged to every sample/image via approved_spec.params (shared
        # by all of them) would silently give every one the same, wrong
        # geometry. wigner_spectra doesn't currently expose an editable
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

    if is_scan_master:
        # Warnings (e.g. an endpoint atom reorder) were already shown once
        # on the approval card at draft time -- this rebuild only needs the
        # images/coordinate metadata, not a second copy of the same text.
        images, coordinate_values, coordinate_label, _warnings = _build_scan_images(approved_spec.params)
        job_id = get_job_manager().submit_scan(
            approved_spec, images, coordinate_values, coordinate_label,
            image0_raw_input=input_text if (input_text is not None and approved_task == "pes_1d") else None,
            input_template=input_text if (input_text is not None and approved_task == "interp_pes") else None,
            owner_user_id=owner_user_id,
        )
    elif is_ensemble_master:
        # Regenerates the full sample set fresh from the round-tripped
        # random_seed (see _build_ensemble_spec_or_error's docstring for
        # why this must be deterministic, not the same in-memory list
        # built before interrupt()) -- mirrors pes_1d/interp_pes's own
        # _build_scan_images(approved_spec.params) re-call above exactly.
        source_id = approved_spec.params["source_frequency_job_id"]
        source_spec = read_spec(source_id)
        source_result = get_job_manager().result(source_id)
        equilibrium_molecule = (
            (source_result["summary"] or {}).get("optimized_molecule")
            if source_spec.get("task") == "opt_freq" else source_spec["molecule"]
        )
        samples, diagnostics = sample_from_source_job(
            equilibrium_molecule, source_result["summary"], n_samples=approved_spec.params["n_samples"],
            random_seed=approved_spec.params["random_seed"],
            low_freq_cutoff_cm1=approved_spec.params.get("low_freq_cutoff_cm1", 100.0),
            temperature_K=approved_spec.params.get("temperature_K", 0.0),
        )
        job_id = get_job_manager().submit_ensemble(approved_spec, samples, diagnostics, owner_user_id=owner_user_id)
    elif is_batch_master:
        # Re-reads the source geometry_set's own geometries fresh from
        # disk rather than the same in-memory list the draft-preview call
        # built (see _resolve_batch_geometries's own docstring) -- mirrors
        # is_scan_master's own _build_scan_images(approved_spec.params)
        # re-call above.
        geometries, error = _resolve_batch_geometries(approved_spec.params["source_geometry_set_job_id"])
        if error:
            content = f"This batch cannot be submitted: {error}"
            return Command(update={"messages": [ToolMessage(content=content, tool_call_id=tool_call_id)]})
        job_id = get_job_manager().submit_batch(
            approved_spec, geometries,
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
        if approved_task == "blind" and approved_spec.label:
            write_meta(job_id, {"label": approved_spec.label})

    edit_note = " (user-edited input)" if input_text is not None else ""
    # Drop the large embedded-geometry/raw-input blobs a pes_scan's params
    # can carry (_scan_start_molecule, _end_molecule, _raw_input,
    # _image0_raw_input, _input_template) -- these exist for JobSpec
    # round-tripping/reconstruction, not for dumping into a chat message
    # the LLM has to read and relay.
    _BLOB_KEYS = {"_scan_start_molecule", "_end_molecule", "_raw_input", "_image0_raw_input", "_input_template"}
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


def _spec_from_draft(draft: dict, molecule: Optional[dict], state: Optional[dict]):
    """Build the JobSpec, preview and grounding context for a ready draft.

    Deterministic given (draft, molecule): this runs once when the approval
    card is rendered and again, identically, when the user clicks Approve
    -- see submit_draft's docstring for why that matters.

    Passes `task`/`subtype`/`method` straight through to `_build_spec_or_error`
    rather than deriving a v1 job_type here -- registry2 already decided
    this draft is ready (validate_draft), and the only remaining derivation
    (which run_*/build_input_preview function a task maps to) belongs where
    it's actually needed: worker dispatch and preview.py, both of which
    call `dispatch.resolve_runner` themselves. See dispatch.py's module
    docstring for why that is now the only place this decision is made.
    """
    task, subtype = draft["task"], draft.get("subtype", "")
    method = draft.get("method")
    if (task, subtype) in NOT_YET_IMPLEMENTED:
        return None, NOT_YET_IMPLEMENTED[(task, subtype)]

    params = dict(draft.get("params") or {})
    if task == "opt" and subtype == "ci":
        params["optimization_type"] = "conical_intersection"
    if task == "blind":
        params["raw_input_text"] = params.get("raw_input_text")
    params = {k: v for k, v in params.items() if v is not None}

    end_molecule = params.pop("_end_molecule", None)
    try:
        built = _build_spec_or_error(
            task, subtype, molecule or {}, draft.get("resolved_engine") or draft.get("engine"), method,
            params, end_molecule=end_molecule,
        )
    except Exception as exc:
        # A builder that raises instead of returning its error escapes
        # submit_draft: no approval card, and a traceback where an answer
        # belonged. The individual builders are being hardened as such
        # shapes are found, but this is the backstop -- every path into a
        # submitted job comes through here, so nothing below can take the
        # conversation down with it.
        return None, (f"Could not prepare this job: {type(exc).__name__}: {exc}. "
                      f"Check the parameters against what the user actually asked for.")
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
        # Both branches stated at the decision point, rather than leaving
        # the model to infer which case it is in. The draft being ready is
        # not the end of the task: for anyone who asked for a calculation,
        # the job is not requested until submit_draft has run.
        lines.append(
            "NEXT STEP: if the user asked for this calculation to be run, call "
            "submit_draft now — the job has not been requested until you do, and a "
            "ready draft on its own runs nothing. It only pauses for their approval, "
            "so do not tell them it has started. Skip submit_draft only if they "
            "explicitly asked to see the input without running it."
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

    # The "already told you" clause is load-bearing. Without it, a request
    # that specifies everything up front -- "run a CASSCF with 4 electrons
    # in 4 orbitals, STO-3G, using ORCA, submit it" -- still comes back
    # INCOMPLETE, because start_job_draft only carries task/method/engine
    # and the parameters have not been written yet. The model then relayed
    # a question the user had already answered, and the conversation stalled
    # one step short of a card. Asking is right when the answer is unknown;
    # here it is sitting in the message the model just read.
    lines = ["DRAFT INCOMPLETE.",
             "If the user has ALREADY told you this, do not ask -- call "
             "update_job_draft now and write what they said. Only ask when you genuinely "
             "do not have it.",
             "When you do need to ask, put this question to the user word for word, "
             "without rephrasing it or answering it yourself:",
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
        # Deliberately not phrased as "nothing has run yet". That reads as a
        # closing remark, and it sits between the parameters and the
        # instruction to submit -- which is exactly where a model looking
        # for a stopping point will find one. Roughly one job matrix cell in
        # five stopped here with a ready draft and no submission.
        return (f"The {spec.engine.upper()} input this job would use (show it only if "
                f"they asked to see the input):\n{preview}")
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
