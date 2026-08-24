"""Tools exposed to the LLM. Each tool either mutates graph state via
`Command(update=...)` (molecule/job tracking) or just returns a string the
LLM incorporates into its reply (status/result lookups).

Job submission is a three-tool sequence, not one call: `start_job_draft` and
`update_job_draft` build a draft incrementally in `state["job_draft"]`, and
`submit_draft` calls `JobManager.submit`, which hands the work to a
background subprocess and returns a job_id immediately. The agent's job is
to gather correct parameters and dispatch; polling for completion is the
frontend's/job_watcher's responsibility, not the graph's -- a node that
awaited `status == completed` would freeze the whole chat turn for the
entire calculation.

`submit_draft` additionally pauses via `interrupt()` after building the job
spec and before actually running anything, so the user can see the exact
input and approve or reject it -- see its docstring and the module-level
note below for why the pre-interrupt code path has to stay free of
side effects that aren't safe to repeat.
"""
from __future__ import annotations

import json
import math
import random
import re
import uuid
from collections import Counter
from pathlib import Path
from typing import Annotated, Callable, Optional

import numpy as np
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
    capability_answer, describe_engine, method_is_really_a_task, resolve_method,
    resolve_task,
)
from app.agent import active_space_lit, reported_jobs
from app.chemistry import geometry_upload
from app.chemistry.jobs import geometry_resolve, interpolate
from app.chemistry.jobs.dispatch import NOT_YET_IMPLEMENTED, resolve_runner
from app.chemistry.jobs.base import (
    BATCH_ONLY_PARAM_KEYS, ENSEMBLE_ONLY_PARAM_KEYS, JobSpec, SCAN_ONLY_PARAM_KEYS, get_job_manager, read_meta,
    read_spec, result_artifact_transaction, scan_child_subtype, sub_job_ids_of, write_meta,
)
from app.chemistry.jobs.ensemble_spectrum import pool_ensemble_transitions
from app.chemistry.jobs.keyword_suggest import suggest_basis_options, suggest_functional_options
from app.chemistry.jobs.param_normalize import normalize_basis, normalize_functional, normalize_method
from app.chemistry.jobs.preview import build_input_preview
from app.chemistry.jobs.scan_template import substitute_geometry
from app.chemistry.registry2.params import DEFAULT_ENSEMBLE_FWHM_EV, PARAMS_BY_NAME, params_for
from app.chemistry import units
from app.chemistry.registry2.tasks import BATCH_CHILD_TASKS, BATCH_GEOMETRY_SOURCE_ARTIFACT_KEY, supports
from app.chemistry.jobs.naming import auto_job_name, resolve_job_label
from app.chemistry.jobs import spectrum_source
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
from app.chemistry.zmatrix import _angle_deg, _dihedral_deg, _distance
from app.chemistry.spectrum import (
    SERIES_PLOT_STYLES, render_histogram_plot, render_ir_spectrum_plot, render_line_plot, render_pes_plot,
    render_series_plot, render_uvvis_plot, render_wigner_ensemble_spectrum,
)
from app.config import JOBS_DIR
from app.plots import store as plot_store
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
        coordinate_values = [float(i + 1) for i in range(n_points)]
        coordinate_label = f"image number ({method})"
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
                              params: dict, param_notes: list[str], task: str = "pes_1d",
                              subtype: str = ""):
    """pes_1d/interp_pes-specific half of _build_spec_or_error: builds the
    full image list and returns a "master" JobSpec (molecule=images[0] as a
    sane single-geometry fallback for generic molecule viewers -- task/
    subtype stamped by the caller, _spec_from_draft) whose preview is image
    0's own sub-job input -- per the approval-card design, only the first
    image's input is shown, since every other image uses identical
    parameters against a different geometry. Every image runs the same
    thing: a `single_point` job at the master's own method, ground state
    (`gs`) or excited state (`ee`) according to the master's own subtype --
    `scan_child_subtype` (base.py) makes that call, and the orchestrator
    that dispatches the real sub-jobs calls the same function, so the input
    previewed here cannot disagree with what actually runs.

    Required-param validation is registry2's job (validate_draft gates
    submit_draft's call into this builder), not this function's -- see
    docs/trackers/2026-08-job-system-overhaul.md's P2B.1 note."""
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

    # The sub-job every image runs: single_point at the master's own method,
    # gs or ee per the master's subtype -- see this function's docstring.
    # `method` is injected
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
        preview_spec = JobSpec(task="single_point", subtype=scan_child_subtype(subtype), method=method or "",
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


def _resolve_batch_geometries(source_job_id: str) -> tuple[Optional[list[dict]], Optional[str]]:
    """(geometries, None) or (None, error). Re-reads the source job's own
    multi-frame geometry artifact fresh from disk rather than carrying a
    copy across the interrupt/resume boundary -- same "rebuild from a
    persisted reference" pattern pes_1d/interp_pes use for
    _scan_start_molecule/_end_molecule and wigner_spectra uses for its
    whole regenerate-from-seed approach, so this one function serves both
    the draft-preview call (build time) and the post-approval call (submit
    time) identically.

    Accepts any task in tasks.BATCH_GEOMETRY_SOURCE_ARTIFACT_KEY --
    geometry_set, pes_1d, interp_pes, wigner_spectra, neb_ts -- reading
    whichever artifact key that task actually writes its geometries under
    (path_xyz / ensemble_xyz / neb_frames; all plain multi-frame xmol
    text, see that mapping's own comment for why one parser reads all of
    them). No separate "is it done yet" check is needed: geometry_set/
    pes_1d/interp_pes/wigner_spectra all render their geometry artifact in
    full before any child job of their own is dispatched, so sourcing from
    one still in flight works the same as from a completed one; neb_ts's
    neb_frames is written only once its single run has finished, so an
    in-flight or failed NEB source simply has no artifact yet and falls
    through to the "no geometries on disk" branch below, with no special
    case required.

    Each geometry is defaulted to charge=0/multiplicity=1 -- a
    GeometryFrame (app/chemistry/geometry_upload.py) carries only
    symbols/coords/name, xmol XYZ has no field for either, and every
    other master task that copies one "template" molecule across several
    images (pes_1d/interp_pes's own scan images) already has this same
    limitation, so a batch inheriting it is consistent rather than a new
    gap. A charged/open-shell system needs charge/multiplicity params on
    the batch draft, not built in this pass."""
    source_spec = read_spec(source_job_id)
    source_task = (source_spec or {}).get("task")
    artifact_key = BATCH_GEOMETRY_SOURCE_ARTIFACT_KEY.get(source_task or "")
    if source_spec is None or artifact_key is None:
        accepted = ", ".join(sorted(BATCH_GEOMETRY_SOURCE_ARTIFACT_KEY))
        return None, (
            f"'{source_job_id}' is not a job this batch can pull geometries from (accepted: {accepted}). "
            f"Ask which of those the batch should run over."
        )
    source_result = get_job_manager().result(source_job_id)
    geometry_file = ((source_result or {}).get("artifacts") or {}).get(artifact_key)
    if not geometry_file:
        return None, f"'{source_job_id}' has no geometries on disk yet."
    try:
        frames = geometry_upload.parse_multi_frame_xyz(Path(geometry_file).read_text())
    except Exception as e:
        return None, f"Could not read geometries from '{source_job_id}': {type(e).__name__}: {e}"
    if not frames:
        return None, f"'{source_job_id}' has no geometries."
    return [
        {"charge": 0, "multiplicity": 1, "symbols": list(f.symbols), "coords": f.coords, "name": f.name}
        for f in frames
    ], None


def _build_batch_spec_or_error(molecule: dict, engine: Optional[str], method: Optional[str],
                               params: dict, param_notes: list[str]):
    """batch-specific half of _build_spec_or_error (P7.4): fans a job at
    (method, engine, params) out over every geometry from EITHER another
    job (params['source_job_id'] -- geometry_set, pes_1d, interp_pes,
    wigner_spectra or neb_ts, see _resolve_batch_geometries) OR 3+
    individually-tagged molecule-panel frames
    (params['_frame_geometries'], resolved by elicitation.py's own
    special-case step -- see that module's comment for why this is never
    a declared ParamSpec), one child per geometry -- the same "master
    JobSpec whose preview is the first child's own input" shape
    _build_scan_spec_or_error already established for pes_1d/interp_pes.
    The child task/subtype every job runs is params['child_task']
    (single_point/opt/freq/opt_freq -- job types 1-4, see
    registry2/params.py's ParamSpec and tasks.BATCH_CHILD_TASKS), chosen
    once for the whole batch, not per-child.

    Required-param validation for method/basis/source_job_id/child_task is
    registry2's job (validate_draft gates submit_draft's call into this
    builder), not this function's -- see docs/trackers/2026-08-job-system-overhaul.md's P2B.1 note."""
    frame_geometries = params.get("_frame_geometries")
    if frame_geometries:
        geometries, error = frame_geometries, None
        source_note = f"the {len(frame_geometries)} structures tagged in the molecule panel"
    else:
        geometries, error = _resolve_batch_geometries(params["source_job_id"])
        source_note = f"geometries from '{params['source_job_id']}'"
    if error:
        return None, None, None, None, None, None, [], error

    child_task, child_subtype = BATCH_CHILD_TASKS[params["child_task"]]

    sub_params = {k: v for k, v in params.items() if k not in BATCH_ONLY_PARAM_KEYS and not k.startswith("_")}
    sub_params["method"] = method

    resolved_engine = engine
    spec = JobSpec(method=method or "", engine=resolved_engine, molecule=geometries[0], params=params)
    try:
        preview_spec = JobSpec(task=child_task, subtype=child_subtype, method=method or "",
                               engine=resolved_engine, molecule=geometries[0], params=sub_params)
        preview = build_input_preview(preview_spec)
    except Exception as e:
        return None, None, None, None, None, None, [], f"Could not build the input for this batch's first job: {e}"

    batch_note = (
        f"Preview of job 1 of {len(geometries)} in this batch ({source_note}) -- every other "
        f"job runs this exact same "
        f"{params['child_task']} calculation with these exact same parameters against a different "
        f"geometry. If you edit this input, the edit applies to job 1 ONLY -- every other job still "
        f"uses the generated input for its own geometry."
    )

    runner_key, _ = resolve_runner(child_task, child_subtype, method)
    kb_context = _kb_context_for_job(resolved_engine, runner_key or child_task, sub_params)
    keyword_options = _keyword_options_for_job(runner_key or child_task, sub_params, resolved_engine)
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
    see docs/trackers/2026-08-job-system-overhaul.md's P2B.1 note."""
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
    # preview_spec (a single_point child template), not the real
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


# Ceiling on wigner_ensemble's n_samples -- enforced here rather than as a
# static registry2/params.py check (ParamSpec has no concept of "present
# but out of range"), same reason the CASSCF/CASPT2 active_electrons/
# active_orbitals cross-field check below also lives in this module
# instead of registry2. Sub-jobs are wave-dispatched (see
# JobManager.submit_ensemble), not submitted all at once, so raising this
# doesn't change how many run concurrently -- MASTER_MAX_IN_FLIGHT (P4)
# already governs that independently. Raised 250->500 in Phase 8 (P8.3,
# the plan's own recorded decision); registry2/params.py's n_samples
# ParamSpec help/ask text already said "the maximum is 500" before this
# constant was updated to match -- the card was quietly promising a cap
# the code didn't honor.
_MAX_ENSEMBLE_SAMPLES = 500



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
    see docs/trackers/2026-08-job-system-overhaul.md's P2B.1 note."""
    n_samples = params["n_samples"]
    if not isinstance(n_samples, int) or n_samples < 1 or n_samples > _MAX_ENSEMBLE_SAMPLES:
        return None, None, None, None, None, None, [], (
            f"n_samples must be an integer between 1 and {_MAX_ENSEMBLE_SAMPLES} (got {n_samples!r})."
        )

    # The sub-job every sample runs: single_point/ee at the master's own
    # method (see dispatch.py's module docstring -- tddft for a hf/dft
    # reference, eom_ccsd/casscf/caspt2 for those methods directly).
    scan_job_type, _ = resolve_runner("single_point", "ee", method)
    # Asked of registry2 rather than of a runner-name allow-list kept here.
    # This used to be `scan_job_type not in {"tddft", "casscf", "eom_ccsd",
    # "caspt2"}`, which is the per-job-type engine table CLAUDE.md says not
    # to keep outside the registry: it could only speak about the METHOD,
    # so it happily passed a CASSCF ensemble routed to PySCF, which cannot
    # produce the intensities the pooling step needs. The task's own
    # `requires=("excited", "osc_strengths")` covers both axes at once, and
    # its refusal names the engine and the specific gap.
    if engine:
        verdict = supports(engine, method, "wigner_spectra")
        if not verdict.supported:
            return None, None, None, None, None, None, [], (
                f"A nuclear-ensemble spectrum needs excitation energies AND oscillator strengths "
                f"at every sampled geometry, because the spectrum is a Gaussian convolution "
                f"weighted by the intensities. {' '.join(verdict.reasons)}"
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

    # Forced on for every method, not only the two that need the flag to
    # change what the engine is asked for. Intensities are structural to
    # this job type (registry2/tasks.py's wigner_spectra `requires`), so
    # there is no ensemble for which "energies only" is a coherent answer,
    # and a card reading "Oscillator strengths: no" beside a spectrum that
    # cannot be drawn without them was simply wrong. tddft already reports
    # them regardless of the flag, so this is a no-op for a hf/dft ensemble
    # beyond making the card say what is actually happening.
    #
    # A belt-and-braces backstop, not the primary enforcement point: draft
    # elicitation (registry2/elicitation.py's validate_draft, "-- 6. Ready")
    # now forces the same flag before this function ever runs, since that
    # is what builds the DRAFT READY preview the model reads and decides
    # whether to ask the user about -- forcing it only here left that
    # preview showing the untouched `False` default, and the model,
    # reading a real discrepancy, asked a question that was already
    # settled either way. So `params` arriving here should already carry
    # `True`, and this block is dead in the ordinary path.
    if not params.get("want_oscillator_strengths"):
        params["want_oscillator_strengths"] = True
        param_notes.append(
            f"Oscillator strengths are always computed for a nuclear-ensemble spectrum: the "
            f"spectrum is a Gaussian convolution weighted by the transition intensities, so "
            f"without them there is nothing to broaden. The per-sample {scan_job_type} sub-jobs "
            f"run on {(engine or '').upper()}, which reports them for {method}."
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


# {type: atom count} for a bond/angle/dihedral -- the one taxonomy both
# opt/constrained's `constraints` and geometry_parameters' queries (P9.2)
# share; see _validate_atom_indices below for why it's one function too.
_N_ATOMS_FOR_GEOMETRY_TYPE = {"bond": 2, "angle": 3, "dihedral": 4}


def _validate_atom_indices(ctype, atoms, n_atoms: int, subject: str = "constraint") -> Optional[str]:
    """Shared 1-based atom-index shape/bounds validation -- one atom-index
    convention, one validation path, for both opt/constrained's
    `constraints` (validated where it's used, above) and
    geometry_parameters' queries (P9.2), each of which hands a small
    model's free-form {'type', 'atoms'} dict straight to this before
    anything indexes into it. This is the P2.9 scan-draft-shape precedent
    (TypeError/KeyError escaping a tool with no card) extracted rather
    than re-derived for the second caller -- the two differ only in what
    ELSE they check (a constraint also needs a numeric 'value'; a query
    doesn't), so only the shared shape/bounds check moved here; each
    caller keeps its own extra checks at its own call site.
    `subject` customizes the noun in the message ("constraint"/"query
    parameter") without duplicating the check itself; with the default,
    every message below matches this function's original constrained-opt-
    only wording exactly."""
    if ctype not in _N_ATOMS_FOR_GEOMETRY_TYPE:
        return f"{subject.capitalize()} type must be one of 'bond', 'angle', 'dihedral' -- got {ctype!r}."
    want = _N_ATOMS_FOR_GEOMETRY_TYPE[ctype]
    if not (isinstance(atoms, list) and len(atoms) == want and all(isinstance(a, int) for a in atoms)):
        return f"A '{ctype}' {subject} needs exactly {want} 1-based atom indices in 'atoms' -- got {atoms!r}."
    if any(a < 1 or a > n_atoms for a in atoms):
        return (f"{subject.capitalize()} atom indices must be between 1 and {n_atoms} (this molecule's "
                f"atom count) -- got {atoms!r}.")
    return None


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
    # `engine` is already registry2's resolved engine by the time a ready
    # draft reaches here (see _build_scan_spec_or_error's own note), which
    # is what lets this be per-engine at all -- the same request resolves to
    # m06-2x on PySCF and M062X on ORCA, and ORCA rejects the hyphenated
    # spelling outright.
    #
    # Gated on method, unlike the basis rewrite above: every method has a
    # basis, but only DFT has a functional, and a stray `functional` key
    # left on a CASSCF draft by an earlier turn must not be rewritten as
    # though it were being used.
    #
    # The resolver's menu options are deliberately not carried from here.
    # `_keyword_options_for_job` runs later in this same call and re-resolves
    # whatever `params["functional"]` now holds -- which is the rewritten
    # name after a confident resolution (so no menu, correctly) and the
    # untouched original after an ambiguous one (so the same options,
    # correctly). Threading them through as well would be a second path to
    # the same list.
    if method == "dft" and params.get("functional"):
        params["functional"], note, _ = normalize_functional(params["functional"], engine)
        if note:
            param_notes.append(note)

    if task in ("pes_1d", "interp_pes"):
        return _build_scan_spec_or_error(molecule, engine, method, params, param_notes,
                                         task=task, subtype=subtype)

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
        for c in params.get("constraints") or []:
            if not isinstance(c, dict):
                return None, None, None, None, None, None, [], (
                    f"Each constraint must be an object like "
                    f"{{'type': 'bond', 'atoms': [1, 2], 'value': 0.98}} -- got {c!r}."
                )
            ctype, atoms, value = c.get("type"), c.get("atoms"), c.get("value")
            err = _validate_atom_indices(ctype, atoms, n_atoms)
            if err:
                return None, None, None, None, None, None, [], err
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
    # `method` is an argument here, not a key in `params`, and
    # _keyword_options_for_job reads it from the dict -- so passing `params`
    # bare made it see method=None and suppress the functional menu for
    # every plain single_point/opt/freq draft. The scan and neb_ts builders
    # above already fold it in explicitly (see the `{**params, "method":
    # method}` at the neb_ts call); this path never did, which is why a
    # misspelled functional on an ordinary job silently got no menu at all.
    keyword_options = _keyword_options_for_job(runner_key or task, {**params, "method": method}, spec.engine)
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


def _plot_owner(state) -> Optional[str]:
    """Who a plot belongs to. Set once per turn on AgentState by
    server/routes/chat.py, the same value job submission records ownership
    with, and None on a no-auth deployment (where the store falls back to a
    flat, unowned layout, exactly as app/uploads/store.py does)."""
    return (state or {}).get("owner_user_id")


def _save_plot(
    state, kind: str, label: str, spec: dict, job_ids: list[str],
    render: Callable[[str], None], data: Optional[dict] = None,
    plot_id: Optional[str] = None, origin: str = "agent",
) -> tuple[Optional[dict], Optional[str], Optional[str]]:
    """Render a plot and store it as a saved record, returning
    (record, version, error).

    Every plot the app draws goes through here, so every plot has an identity,
    a spec that can be patched and re-rendered, and the numbers it drew. Pass
    `plot_id` to add a version to an existing record instead of creating one,
    which is what an edit does.

    An edit pins a NEW version rather than overwriting the current image. A
    chat message cites the version it actually drew, so scrollback keeps
    showing what it described, while the panel shows the latest. That also
    retires a real bug in the artifact-key scheme this replaces: uvvis,
    ir and ensemble spectra used a fixed key, so re-plotting one at a
    different broadening silently changed the image in every older message
    that had ever shown it."""
    owner = _plot_owner(state)
    if plot_id is None and kind != "custom" and len(job_ids) == 1:
        # A job has one UV/Vis spectrum, not a new one per broadening. Re-plot
        # it and the existing record gains a version; only composed charts get
        # a fresh record each time. See find_by_job_and_kind.
        existing = plot_store.find_by_job_and_kind(owner, job_ids[0], kind)
        if existing is not None:
            plot_id = existing["plot_id"]
    created_here = plot_id is None
    if plot_id is None:
        record = plot_store.create_plot(
            owner, kind=kind, label=label, spec=spec, job_ids=job_ids, data=data, origin=origin)
        plot_id = record["plot_id"]
    elif data is not None or spec:
        plot_store.update_plot(owner, plot_id, spec=spec, label=label, job_ids=job_ids,
                               **({"data": data} if data is not None else {}))
    try:
        record = plot_store.add_version(owner, plot_id, render)
    except Exception as e:
        # A renderer that raises must not leave a record behind with no image
        # in it, which the panel would list as a permanently blank row nobody
        # can explain. An edit keeps its record, since that one already has
        # earlier versions and is still perfectly good.
        if created_here:
            plot_store.delete_plot(owner, plot_id)
        return None, None, f"Could not render the plot: {e}"
    if record is None:
        return None, None, f"Plot {plot_id} could not be saved."
    return record, plot_store.latest_version(record), None


def _plot_marker(record: dict, version: str) -> str:
    """The first line of a plot tool's return value. MessageBubble.tsx parses
    exactly this shape to render the image inline, deterministically, rather
    than relying on the model to relay a URL in its own reply."""
    return f"PLOT_ARTIFACT plot_id={record['plot_id']} version={version}"


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

    width = fwhm_eV or 0.4
    record, version, error = _save_plot(
        state, kind="uvvis", label=f"UV/Vis spectrum, {resolve_job_label(read_spec(target) or {}, read_meta(target))}",
        spec={"kind": "uvvis", "width": width}, job_ids=[target],
        data={"excitation_energies_eV": list(energies), "oscillator_strengths": list(osc)},
        render=lambda path: render_uvvis_plot(energies, osc, width, path),
    )
    if error:
        return error
    out_path = str(plot_store.version_path(_plot_owner(state), record["plot_id"], version))

    # Also registered as a job artifact, because the job drawer's own UV/Vis
    # panel fetches it by that key. The file itself lives once, in the plot
    # store; this is a second name for it, not a second copy.
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

    return (f"Generated a UV/Vis spectrum plot for job {target}; it is now shown to the user. "
            f"Its plot id is {record['plot_id']}.")


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

    width = fwhm_cm1 or 20.0
    record, version, error = _save_plot(
        state, kind="ir", label=f"IR spectrum, {resolve_job_label(read_spec(target) or {}, read_meta(target))}",
        spec={"kind": "ir", "width": width}, job_ids=[target],
        data={"frequencies_cm1": list(freqs), "ir_intensities": list(ir)},
        render=lambda path: render_ir_spectrum_plot(freqs, ir, width, path),
    )
    if error:
        return error
    # A second name for the plot store's file, so the drawer's IR panel can
    # keep fetching it by artifact key. See plot_excited_state_spectrum.
    out_path = str(plot_store.version_path(_plot_owner(state), record["plot_id"], version))

    with result_artifact_transaction(target) as artifacts:
        if artifacts is None:
            # See plot_excited_state_spectrum's identical comment above --
            # the job's result.json was deleted out from under this call.
            return f"Job {target} was deleted while this plot was being generated; nothing to show."
        artifacts["ir_spectrum"] = out_path

    return (f"Generated an IR spectrum plot for job {target}; it is now shown to the user. "
            f"Its plot id is {record['plot_id']}.")


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
    """kind="comparison": one named scalar across several jobs, as a bar chart.

    This is a thin front door onto the same pipeline kind="custom" uses, not a
    second plotting mechanism. What it adds, and the only reason it still
    exists as its own kind, is `_COMPARISON_FIELD_ALIASES`: "energy" means
    `final_energy_hartree` in one job and `casscf_energy_hartree` in another,
    so a single raw field path cannot express it across a heterogeneous set of
    jobs. It resolves that friendly name to a literal key PER JOB and then
    hands off.

    The alias lookup deliberately stays out here rather than moving inside
    _resolve_field_path. That function's contract, restated in
    docs/ARCHITECTURE.md, is that there is no schema of known field names
    checked ahead of the job's real summary; a table consulted inside it would
    make that false. Out here it only ever picks which literal path to ask for,
    and the resolver's own behaviour is untouched.
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

    # Resolve the alias to a concrete summary key for each job, and build the
    # per-job x_labels map the unified pipeline wants. A job with no value for
    # this field keeps its column (empty) rather than disappearing, matching
    # every other style; it used to be dropped silently.
    aliases = _COMPARISON_FIELD_ALIASES[field]
    usable: list[str] = []
    per_job_field: dict[str, str] = {}
    for job_id in targets:
        result = mgr.result(job_id)
        if result is None or result.get("status") != "completed":
            continue
        summary = result.get("summary") or {}
        key = next((k for k in aliases if summary.get(k) is not None), None)
        usable.append(job_id)
        if key:
            per_job_field[job_id] = key

    if len(per_job_field) < 2:
        return (
            f"Not enough jobs with a usable '{field}' value to compare (found "
            f"{len(per_job_field)}, need at least 2)."
        )

    # Each job is asked for its own resolved key, via the pipeline's
    # y_field_by_job hook. `y_field` is only the fallback for a job that had no
    # value at all, and it resolves to a gap for exactly those jobs, which is
    # what should happen.
    label = _COMPARISON_FIELD_LABELS[field]
    return _plot_custom({
        "job_ids": usable,
        "style": "bar",
        "series": [{"y_field": aliases[0], "y_field_by_job": per_job_field, "label": label}],
        "ylabel": label,
        "title": title or f"{label} comparison",
    }, state)


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


def plot_wigner_ensemble_spectrum(job_id: str, fwhm_eV: Optional[float] = None,
                                  state: Annotated[AgentState, InjectedState] = None) -> str:
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
    fwhm = fwhm_eV if fwhm_eV is not None else (
        spec.get("params", {}).get("fwhm_eV") or DEFAULT_ENSEMBLE_FWHM_EV
    )
    # The .dat stays in the job directory: it is the pooled data, which
    # belongs to the job, not a view of it. Only the PNG becomes a plot.
    out_data_path = str(JOBS_DIR / job_id / "ensemble_spectrum.dat")
    record, version, error = _save_plot(
        state, kind="ensemble",
        label=f"Ensemble spectrum, {resolve_job_label(read_spec(job_id) or {}, read_meta(job_id))}",
        spec={"kind": "ensemble", "width": fwhm}, job_ids=[job_id],
        data={"n_transitions": len(pooled["energies_eV"]), "fwhm_eV": fwhm},
        render=lambda path: render_wigner_ensemble_spectrum(
            pooled["energies_eV"], pooled["oscillator_strengths"], pooled["state_indices"],
            fwhm, path, out_data_path=out_data_path),
    )
    if error:
        return error
    out_path = str(plot_store.version_path(_plot_owner(state), record["plot_id"], version))

    with result_artifact_transaction(job_id) as artifacts:
        if artifacts is None:
            return f"Job {job_id} was deleted while this plot was being generated; nothing to show."
        artifacts["ensemble_spectrum"] = out_path
        artifacts["ensemble_spectrum_data"] = out_data_path

    note = ""
    if diagnostics["n_no_intensity"] or diagnostics["n_failed_or_pending"]:
        note = (
            f" ({diagnostics['n_no_intensity']} sample(s) had no usable intensity data, "
            f"{diagnostics['n_failed_or_pending']} failed/incomplete -- excluded from the plot.)"
        )
    return (
        f"{_plot_marker(record, version)}\n"
        f"Generated the nuclear-ensemble absorption spectrum from {diagnostics['n_completed']} sample(s) "
        f"({len(pooled['energies_eV'])} pooled transitions, FWHM = {fwhm:.2f} eV); it is now shown to the "
        f"user.{note}"
    )


def plot_pes_scan(job_id: str, state: Annotated[AgentState, InjectedState] = None) -> str:
    """Generate and display a potential-energy-surface plot for a
    completed pes_1d or interp_pes scan master -- one line per electronic
    state, relative energy (eV) against the scan's own coordinate (image
    number for interp_pes, the scanned bond/angle/dihedral value for
    pes_1d). Call this whenever the user asks to plot/show/see the PES,
    scan, or path plot for a pes_1d/interp_pes job, or wants to re-plot
    one after more images have finished.

    Always re-reads every sub-job's energies live from the master's own
    summary (never a cached image), so calling this again after more
    images complete reflects the scan's current state exactly. Refuses
    (no plot) if the job isn't a pes_1d/interp_pes master, or no image has
    a usable energy yet. The plot is already shown to the user
    automatically once this tool returns -- do not also try to paste an
    image URL into your reply."""
    spec = read_spec(job_id)
    if spec is None:
        return f"No such job: {job_id}."
    task = spec.get("task") or ""
    if task not in ("pes_1d", "interp_pes"):
        return (f"Job {job_id} is a '{task or 'unknown'}' job, not a PES scan -- it has no "
                f"potential-energy-surface plot to draw.")
    result = get_job_manager().result(job_id)
    if result is None:
        return f"No such job: {job_id}."
    summary = result.get("summary") or {}
    coordinate_values = summary.get("coordinate_values")
    per_image = summary.get("state_energies_per_image")
    if not coordinate_values or not per_image or not any(per_image):
        return f"Job {job_id} has no per-image energies yet to plot a PES from."
    coordinate_label = summary.get("coordinate", "coordinate")
    n_states = max((len(s) for s in per_image if s), default=0)
    state_series = {
        ("Ground state" if i == 0 else f"State {i}"): [s[i] if s and i < len(s) else None for s in per_image]
        for i in range(n_states)
    }

    record, version, error = _save_plot(
        state, kind="pes_scan", label=f"PES scan, {resolve_job_label(spec, read_meta(job_id))}",
        spec={"kind": "pes_scan"}, job_ids=[job_id],
        data={"n_images": len(coordinate_values)},
        render=lambda path: render_pes_plot(coordinate_values, state_series, coordinate_label, path),
    )
    if error:
        return error
    out_path = str(plot_store.version_path(_plot_owner(state), record["plot_id"], version))

    with result_artifact_transaction(job_id) as artifacts:
        if artifacts is None:
            return f"Job {job_id} was deleted while this plot was being generated; nothing to show."
        artifacts["pes_plot"] = out_path

    n_ok = sum(1 for s in per_image if s)
    return (
        f"{_plot_marker(record, version)}\n"
        f"Generated the potential-energy-surface plot from {n_ok} of {len(coordinate_values)} image(s); "
        f"it is now shown to the user."
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
        # source_job_id sourced batches re-read the source job's own
        # geometries fresh from disk rather than the same in-memory list
        # the draft-preview call built (see _resolve_batch_geometries's
        # own docstring) -- mirrors is_scan_master's own
        # _build_scan_images(approved_spec.params) re-call above.
        # _frame_geometries sourced batches have no disk artifact to
        # re-read -- the approved_spec round-tripped verbatim through the
        # approval card (see submit_draft's own docstring) already carries
        # the exact geometries it was approved with, so those are used
        # as-is rather than re-reading state['molecule_frames'] a second
        # time, which could disagree with what the card actually showed.
        frame_geometries = approved_spec.params.get("_frame_geometries")
        if frame_geometries:
            geometries, error = frame_geometries, None
        else:
            geometries, error = _resolve_batch_geometries(approved_spec.params["source_job_id"])
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
    _BLOB_KEYS = {"_scan_start_molecule", "_end_molecule", "_raw_input", "_image0_raw_input", "_input_template",
                  "_frame_geometries"}
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
    summary = job_context_summary(target)
    # Recording that the agent has now SEEN this job's final result is what
    # stops JobWatcher summarizing it a second time a moment later -- see
    # app/agent/reported_jobs.py. Keyed on the status actually returned, so
    # polling a still-running job (the common case in a turn that submits
    # one) does not suppress the notice that job legitimately needs later.
    status = get_job_manager().status(target)
    if status.get("status") in ("completed", "failed", "cancelled"):
        reported_jobs.mark_reported(target)
    return summary


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


def _resolve_draft_molecule(draft: dict, state: Optional[dict]) -> tuple[Optional[dict], Optional[str]]:
    """The molecule a draft actually runs on: a tagged source_geometry_job_id
    (P9.3) takes priority over state["molecule"] (the active instrument-
    panel frame) when present. validate_draft has already confirmed a
    tagged id resolves (or refused the draft before this is ever reached),
    but this re-resolves rather than trusting a value carried on the
    draft, for the same reason submit_draft's own docstring gives for not
    reading anything else outside the draft/state pair: the two
    validate_draft passes (card render, then post-approval resume) must
    agree, and re-resolving from the same (draft, state) inputs both times
    is what makes them agree by construction."""
    params = draft.get("params") or {}
    source_job_id = params.get("source_geometry_job_id")
    if source_job_id:
        return geometry_resolve.resolve_job_geometry(
            str(source_job_id), params.get("source_geometry_image"))
    return (state or {}).get("molecule"), None


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
    # An active-space job carries the literature search that preceded it, so
    # its own result report can be held against what was published rather
    # than against whatever the model remembers saying. Injected here, from
    # state, rather than asked for as a parameter: it is a finding, not a
    # user choice, and nothing should be able to type a different one onto
    # the approval card. Only when the search was actually run for THIS
    # molecule -- carrying cyclooctadiene's findings into a job on water
    # would recreate the wrong-molecule substitution one level up.
    if task == "cas_reco" and not params.get("literature_notes"):
        found = (state or {}).get("active_space_literature") or {}
        molecule_name = (molecule or {}).get("name") or (molecule or {}).get("identifier")
        if found.get("notes") and found.get("molecule") == molecule_name:
            params["literature_notes"] = found["notes"]
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
def _draft_task_pair(draft: dict) -> Optional[tuple[str, str]]:
    """The draft's (task, subtype) as the registry names them, or None if
    the task has not resolved to anything yet."""
    task, subtype = draft.get("task") or "", draft.get("subtype") or ""
    if not task:
        return None
    resolved, _ = resolve_task(f"{task}/{subtype}" if subtype else task)
    if resolved is None:
        resolved, _ = resolve_task(task)
    return resolved


def _param_applies(draft: dict, key: str) -> bool:
    """Is `key` a parameter of the draft's own task?

    True when the task has not resolved yet -- an unresolved task cannot
    justify refusing anything, and the ordinary elicitation path will ask
    about the task next anyway.
    """
    pair = _draft_task_pair(draft)
    if pair is None:
        return True
    return any(spec.name == key for spec in params_for(*pair))


def _unknown_param_message(draft: dict, unknown: list[str], inapplicable: list[str]) -> str:
    pair = _draft_task_pair(draft)
    valid = sorted(spec.name for spec in params_for(*pair)) if pair else []
    parts = []
    if unknown:
        parts.append(f"{', '.join(unknown)} is not a parameter this app has"
                     if len(unknown) == 1 else
                     f"{', '.join(unknown)} are not parameters this app has")
    if inapplicable:
        name = f"{pair[0]}/{pair[1]}" if pair and pair[1] else (pair[0] if pair else "this task")
        parts.append(f"{', '.join(inapplicable)} is not a parameter of {name}"
                     if len(inapplicable) == 1 else
                     f"{', '.join(inapplicable)} are not parameters of {name}")
    tail = (f" This draft takes: {', '.join(valid)}." if valid else "")
    return (
        f"{'; '.join(parts)}, so nothing was recorded -- not even the keys in the same "
        f"call, since a half-applied update is harder to reason about than none.{tail} "
        f"Use the exact key the previous reply named, and if the user asked for "
        f"something none of these express, tell them so rather than inventing a field "
        f"for it."
    )


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
            "submit_draft now. The job has not been requested until you do, and a "
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
        molecule, mol_error = _resolve_draft_molecule(verdict.draft, state)
        if mol_error:
            return ""
        built, error = _spec_from_draft(verdict.draft, molecule, state)
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

    When `task` resolves, the answer also includes `plottable_fields` --
    commonly-present summary field names for that task, useful as a
    starting guess for plot(kind="custom")'s `spec`. These are
    illustrative, not a guarantee: the field a specific completed job
    actually has can differ (an mp2/ccsd single-point reports extra
    fields a plain HF one doesn't, say), and plot(kind="custom") always
    validates against that job's real summary and refuses cleanly,
    listing the real fields, if a guess turns out wrong -- so treat this
    list as a first guess to try, not as the final word.
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
            # Before refusing: the word may be real and simply on the wrong
            # axis. `avas` and `autocas` are subtypes of cas_reco, not levels
            # of theory, and answering "not a method, closest matches: none"
            # sent a capability question about a feature this app HAS into a
            # dead end -- the agent then told the user the feature did not
            # exist. Answer the question the word actually asks.
            as_task = method_is_really_a_task(method)
            if as_task is not None:
                if not task_name:
                    task_name, subtype = as_task
                    method = None
                elif as_task[0] == task_name:
                    subtype = as_task[1]
                    method = None
                else:
                    return (f"'{method}' is not a level of theory -- it names the task "
                            f"{as_task[0]}/{as_task[1]}, which does not belong to "
                            f"{task_name}. Ask about one or the other.")
            else:
                return (f"'{method}' is not a method this app runs. Closest matches: "
                        f"{', '.join(suggestions) or 'none'}.")
        else:
            method = canonical
    if not task_name:
        if engine:
            return json.dumps(describe_engine(engine))
        return ("Name a task (and a method, if the question is about one) so this can "
                "be looked up -- for example task='conical intersection', method='casscf'.")
    return json.dumps(capability_answer(task_name, subtype, method, engine))


@tool
def search_active_space_literature(
    n_states: int,
    basis: str,
    molecule: Optional[str] = None,
    state: Annotated[AgentState, InjectedState] = None,
    tool_call_id: Annotated[str, InjectedToolCallId] = None,
) -> Command:
    """What the literature says about an active space for THIS molecule --
    call this before drafting any active-space recommendation job.

    The order matters and is the point of the tool. Ask the user for the
    number of state-averaged roots and the basis set they are targeting
    FIRST, then call this with their answers, because those two values are
    what the search is narrowed by. Only pass values the user actually
    gave; a guessed state count silently narrows the search to conditions
    nobody asked for.

    `n_states` is state-averaged ROOTS, and for CASSCF that count includes
    the ground state -- so someone asking for "two excited states" wants
    n_states=3, and passing 2 would search for, and later run, a job with
    one excited state in it. Convert before calling, and say that you did.

    The match hierarchy is molecule, then state count, then basis, relaxing
    from the end. **The molecule never relaxes.** A result for a different
    system is not a weaker match, it is not a match -- and "nothing
    published for this molecule" is a real answer this tool can return, not
    a prompt to scale an active space from a similar-looking compound. That
    substitution is exactly what went wrong before this tool existed: a
    (6e,6o) space for cyclotetrasilene became an (8e,8o) recommendation for
    cyclooctadiene, attributed to a paper that never gave a number.

    Relay the summary this returns, then the capability line, then ask the
    user which of the two methods to use. Do not pick for them: AVAS and
    AutoCAS answer different questions and neither is a default.
    """
    active = (state or {}).get("molecule") or {}
    name = molecule or active.get("name") or active.get("identifier")
    if not name:
        return Command(update={"messages": [ToolMessage(
            content="No molecule is set, so there is nothing to search the literature "
                    "for. Resolve the molecule first with set_geometry.",
            tool_call_id=tool_call_id)]})

    findings = active_space_lit.search(str(name), n_states=n_states, basis=basis)
    notes = findings.as_notes()

    # Read out of the registry rather than composed, for the same reason
    # every other capability statement is: this is the exact question the
    # agent answered from memory, and got wrong, in the conversation this
    # tool comes from.
    options = []
    for subtype in ("autocas", "avas"):
        answer = capability_answer("cas_reco", subtype)
        if answer.get("supported"):
            options.append(f"- {answer['label']}: {answer['description']} "
                           f"(runs on {', '.join(e.upper() for e in answer['engines'])})")
    capability_line = (
        "This deployment can build an active space in two ways:\n" + "\n".join(options)
        if options else
        "This deployment cannot run an active-space recommendation job."
    )

    return Command(update={
        "active_space_literature": {
            "molecule": findings.molecule,
            "matched_at": findings.matched_at,
            "n_states": n_states,
            "basis": basis,
            "notes": notes,
        },
        "messages": [ToolMessage(content=(
            f"{notes}\n\n{capability_line}\n\n"
            f"NEXT STEP: give the user the search result above in your own words -- "
            f"including, plainly, if nothing was found for this molecule -- then state "
            f"the two options and ask which they want. Once they choose, call "
            f"start_job_draft(task='active space recommendation', engine='pyscf') and "
            f"set subtype to their choice, then write the basis ({basis}) and n_states "
            f"({n_states}) they already gave. Do not ask for either again."
        ), tool_call_id=tool_call_id)],
    })


@tool
def explain_active_space(
    active_electrons: int,
    active_orbitals: int,
    n_states: Optional[int] = None,
    basis: Optional[str] = None,
    state: Annotated[AgentState, InjectedState] = None,
) -> str:
    """Explain an active space the user has ALREADY chosen, against the
    literature for their molecule. Runs no calculation.

    Use this when someone asks whether their own (ne, no) choice is
    reasonable, or what a space they read in a paper corresponds to. To
    have the app CHOOSE a space instead, that is a job:
    search_active_space_literature first, then a cas_reco draft.

    This was a job type once (`cas_reco/explain`) and should never have
    been. It runs no engine calculation, so a background subprocess with a
    core budget was machinery around a literature lookup -- and, because
    every cas_reco subtype shared one runner, asking for it actually ran a
    full entropy pilot instead of explaining anything.

    The same rule as the search tool: what comes back may be nothing for
    this molecule, and nothing is the answer. Do not explain the user's
    space by reference to a space published for a different compound.
    """
    active = (state or {}).get("molecule") or {}
    name = active.get("name") or active.get("identifier")
    if not name:
        return ("No molecule is set, so there is nothing to explain this active space "
                "against. Resolve the molecule first with set_geometry.")
    if active_orbitals <= 0 or active_electrons < 0:
        return (f"({active_electrons}e, {active_orbitals}o) is not a well-formed active "
                f"space. Ask the user for the electron and orbital counts again.")

    findings = active_space_lit.search(str(name), n_states=n_states, basis=basis)
    n_alpha = n_beta = active_electrons // 2
    max_configs = math.comb(active_orbitals, n_alpha) * math.comb(active_orbitals, n_beta)
    # The one check worth making mechanically rather than leaving to the
    # model: a completely full space holds a single configuration and can
    # describe no correlation at all, which is easy to state and easy to
    # miss. It is the same degenerate case the AVAS seed guard catches one
    # level down (pyscf_runner._avas_pilot_space).
    if active_electrons == 2 * active_orbitals:
        shape = (f"({active_electrons}e, {active_orbitals}o) is completely full -- every "
                 f"orbital doubly occupied, exactly one configuration, so it can describe "
                 f"no correlation whatsoever. Tell the user this outright: whatever the "
                 f"literature says, this particular space cannot do anything a "
                 f"single-reference method would not.")
    else:
        shape = (f"({active_electrons}e, {active_orbitals}o) holds at most {max_configs} "
                 f"many-electron configurations"
                 + (f", enough for the {n_states} state-averaged root(s) asked about."
                    if n_states and max_configs >= n_states else
                    f" -- fewer than the {n_states} root(s) asked about, so a "
                    f"state-averaged CASSCF of that size cannot be run in it."
                    if n_states else "."))

    return (
        f"{findings.as_notes()}\n\n{shape}\n\n"
        f"NEXT STEP: explain the user's ({active_electrons}e, {active_orbitals}o) choice "
        f"for {name} against the search result above. If the search found nothing for "
        f"this molecule, say so plainly and make clear that what follows is your own "
        f"reasoning rather than a literature value -- do not borrow a space published "
        f"for a different compound to fill the gap. No calculation has been run here; if "
        f"the user wants the app to choose a space, offer the recommendation job."
    )


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

    A scan or an interpolated path can compute excited states at every
    point, not only the ground state. You do not select that with a
    separate task: start the scan as usual and write `n_states` through
    update_job_draft when the user asks for excited states. The backend
    reads the root count and switches the scan to its excited-state form
    itself, saying so in its reply. Say nothing about states and the scan
    stays ground state, which is what a user who did not mention them
    wants.

    If the user has attached a raw ORCA/BAGEL input (their own pasted
    text, or a file attached from the Files panel -- its content already
    sits in this conversation verbatim) and asks to run it as-is,
    verbatim, or "blind", use task="blind" and set the attached text as
    raw_input_text via update_job_draft. Do NOT decompose it into
    method/basis/geometry and build a structured job instead -- that
    silently changes what actually runs (default keywords/settings this
    app would add are not what they attached) and defeats the reason
    blind mode exists. Building the structured equivalent is only right
    when they asked to see what it WOULD look like, not asked to run
    their own input.
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
    field to null to clear it. `task`, `subtype`, `method` and `engine`
    are accepted here too, for when the user changes their mind.

    Only ever write what the user actually said. If they have not answered
    the question yet, ask it again rather than filling in a plausible
    value: a guessed parameter reaches the approval card looking exactly
    like one they chose.

    If the user wants this job to run on the SAME geometry as a specific
    prior job instead of whatever is in the molecule panel -- "same
    geometry as before", "repeat that with a bigger basis" -- set
    {"source_geometry_job_id": "<that job's id>"} rather than calling
    set_geometry; you already have that id from earlier in this
    conversation (a job you submitted or reported on), so there is no
    need to ask for one. A job that cannot supply its geometry (still
    running, or a scan/batch with more than one) is refused with the
    reason rather than silently substituted.
    """
    draft = dict((state or {}).get("job_draft") or {})
    if not draft:
        return Command(update={"messages": [ToolMessage(
            content="There is no draft in progress -- call start_job_draft first.",
            tool_call_id=tool_call_id)]})
    params = dict(draft.get("params") or {})
    misrouted = []
    # Structural keys first, so the applicability check below reads the
    # task/subtype this call is *setting*, not the one it is replacing.
    for key in ("task", "subtype", "method", "engine"):
        if key in (updates or {}):
            draft[key] = updates[key]
    unknown, inapplicable = [], []
    for key, value in (updates or {}).items():
        if key in ("task", "subtype", "method", "engine"):
            continue
        if key in _STATE_OWNED_FIELDS:
            # Refused rather than absorbed. The draft shape is deliberately
            # tolerant of a model that puts a parameter at the top level,
            # but a *geometry* written as a parameter is not a formatting
            # slip -- it produces a spec carrying a stray key like
            # {"molecule": "water"} that no runner reads and that shows up
            # on the approval card as though the user chose it.
            misrouted.append(key)
        elif key.startswith("_"):
            # Internal plumbing written by other tools (_end_molecule,
            # _frame_geometries); never model-authored, never on the card.
            params[key] = value
        elif key not in PARAMS_BY_NAME:
            unknown.append(key)
        elif not _param_applies(draft, key):
            inapplicable.append(key)
        else:
            params[key] = value
    if unknown or inapplicable:
        # Absorbing an unrecognized key was the hole here. The comment on
        # _STATE_OWNED_FIELDS above says the harm being guarded against is
        # "a stray key that no runner reads and that shows up on the
        # approval card as though the user chose it" -- and every key the
        # registry had never heard of got exactly that treatment. A real
        # case: a model invented `constraint` for a PES scan; it rode into
        # the submitted spec and onto the card. It happened to be inert,
        # since the scan ran off scan_range and n_points.
        return Command(update={"messages": [ToolMessage(
            content=_unknown_param_message(draft, unknown, inapplicable),
            tool_call_id=tool_call_id)]})
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

    molecule, mol_error = _resolve_draft_molecule(verdict.draft, state)
    if mol_error:
        return Command(update={"messages": [ToolMessage(
            content=f"This draft cannot be submitted: {mol_error}", tool_call_id=tool_call_id)]})
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


class _FieldPathError(Exception):
    """A custom-plot field path didn't resolve against a job's real
    summary. Always carries enough to build a refuse-don't-fabricate
    message -- the path itself plus the keys that actually were there."""


_FIELD_PATH_SEGMENT_RE = re.compile(r"^([^.\[\]]+)((?:\[\d+\])*)$")


def _resolve_field_path(summary: dict, path: str):
    """Resolve a dotted/bracket field path against one job's summary dict
    -- e.g. 'excitation_energies_eV[0]' or 'constraints[0].value' (a
    constrained-opt job's held bond/angle/dihedral target, see
    registry2/params.py's `constraints` ParamSpec). This is the one and
    only validation path for plot(kind="custom"): there is no separate
    schema of "known" field names checked first, because the runners in
    app/chemistry/jobs/*.py build summary dicts as literal string keys
    with no schema of their own to check against (see TaskDef's
    `plottable_fields` docstring) -- a path either exists in this specific
    job's real summary or it doesn't, and "doesn't" is the refusal,
    listing what actually is there instead of guessing or fabricating."""
    node = summary
    for segment in path.split("."):
        m = _FIELD_PATH_SEGMENT_RE.match(segment)
        if not m:
            raise _FieldPathError(f"'{path}' isn't a valid field path (malformed segment '{segment}').")
        key, indices = m.group(1), m.group(2)
        if not isinstance(node, dict) or key not in node:
            available = ", ".join(sorted(summary.keys())) if isinstance(summary, dict) else "(none)"
            raise _FieldPathError(f"'{path}' isn't in this job's summary. Available fields: {available}.")
        node = node[key]
        for idx_str in re.findall(r"\[(\d+)\]", indices):
            idx = int(idx_str)
            if not isinstance(node, list) or idx >= len(node):
                raise _FieldPathError(
                    f"'{path}': index [{idx}] is out of range or '{key}' isn't a list in this job's summary."
                )
            node = node[idx]
    return node


def _as_float(value, path: str) -> float:
    """Coerce one resolved field value to a plottable number, refusing
    cleanly (not crashing the tool call) when a path resolves to something
    with no numeric meaning -- e.g. `orbital_table[0]`, a per-orbital
    dict, rather than a scalar result field."""
    try:
        return float(value)
    except (TypeError, ValueError):
        raise _FieldPathError(f"'{path}' isn't a plottable number (got {type(value).__name__}: {value!r}).")


def _format_tick(value: Optional[float]) -> str:
    """A numeric x value rendered as a category label, for the styles that use
    evenly spaced slots ("bar", "levels") even when a real numeric x_field was
    given. %g rather than str() so 1.2000000000000002 shows as 1.2."""
    return "" if value is None else f"{value:g}"


def _column_labels(
    x_labels, kept_job_ids: list[str], default_labels: list[str], rows_are_jobs: bool,
) -> tuple[Optional[list[str]], Optional[str]]:
    """Resolve spec['x_labels'] against the columns that actually survived.

    When rows are jobs this MUST be a mapping keyed by job id, never a
    positional list, and that is a correctness requirement rather than a
    preference. A job that isn't finished has no column and is dropped, so with
    a positional list every label from that position on would slide one column
    to the left: the chart still renders, the legend is still right, and the
    method names sit over the wrong bars. Keying by job id makes that
    unrepresentable. For a single job's own arrays there is nothing to drop, so
    a positional list is unambiguous and is what's accepted there."""
    if x_labels is None:
        return default_labels, None
    if rows_are_jobs:
        if not isinstance(x_labels, dict):
            return None, ("spec['x_labels'] must be a mapping of job id to label when several jobs "
                          "are plotted, e.g. {\"37eafc65723d\": \"TD-HF\"}. A plain list is refused "
                          "because a job that can't be plotted is dropped, which would shift every "
                          "later label onto the wrong column.")
        return [x_labels.get(jid, default) for jid, default in zip(kept_job_ids, default_labels)], None
    if not isinstance(x_labels, list):
        return None, "spec['x_labels'] must be a list of labels, one per point, when plotting a single job."
    if len(x_labels) != len(default_labels):
        return None, (f"spec['x_labels'] has {len(x_labels)} label(s) but this plot has "
                      f"{len(default_labels)} point(s).")
    return [str(label) for label in x_labels], None
def _default_column_labels(job_ids: list[str]) -> list[str]:
    """One display name per job column, via resolve_job_label -- the single
    canonical definition of "the job's name", shared with the job list, the
    drawer heading and every download filename.

    Names that collide get their short id appended, and they get it on EVERY
    member of the colliding group rather than only the later ones. Two jobs in
    the same comparison genuinely can auto-name identically (a TDDFT and a TDA
    run of the same functional and basis differ in a parameter the auto-name
    doesn't carry), and disambiguating only the second leaves the reader unable
    to tell which of the two the bare one is."""
    labels = [resolve_job_label(read_spec(jid) or {}, read_meta(jid)) or jid for jid in job_ids]
    collisions = {label for label, n in Counter(labels).items() if n > 1}
    return [
        f"{label} ({jid[:8]})" if label in collisions else label
        for label, jid in zip(labels, job_ids)
    ]


def _resolve_cell(summary: dict, path: str, job_id: str) -> float:
    """One scalar out of one job's summary, for the one-row-per-job case.
    Raises _FieldPathError (which the caller turns into a gap, not a dropped
    column) when the path is missing, non-numeric, or resolves to a whole list
    with no index."""
    value = _resolve_field_path(summary, path)
    if isinstance(value, list):
        raise _FieldPathError(
            f"'{path}' is a list in job {job_id} -- add an index, e.g. '{path}[0]', "
            f"to use one job per column."
        )
    return _as_float(value, path)


def _nothing_resolved_message(notes) -> str:
    """The refusal when not one requested field resolved in any job.

    Reports the distinct reasons rather than one reason per job. Seven jobs of
    the same task fail the same way, and "excitation_energies_eV is a list, add
    an index" repeated seven times says no more than saying it once, while
    burying the correction the caller has to make. Distinct reasons are all
    kept, because a field that is absent and a field that needs an index are
    different mistakes and a spec can make both at once."""
    reasons: list[str] = []
    for _, reason in notes:
        if reason not in reasons:
            reasons.append(reason)
    return ("Nothing could be drawn: not one of the requested fields resolved to a number "
            "in any of these jobs. " + " ".join(reasons))


def _rows_from_jobs(
    job_ids: list[str], x_field: Optional[str], series_specs: list[dict],
) -> tuple[list[str], list[Optional[float]], list[list[Optional[float]]], list[str], list[str]]:
    """Rows are jobs: one column per job, in the order given.

    A job is dropped only when it has no column to draw -- it isn't finished,
    or an x_field was asked for and doesn't resolve for it. A y_field that
    doesn't resolve leaves that ONE cell empty and keeps the column, which is
    the whole point: a job with no oscillator strengths should appear as a
    labelled column with nothing in it, not vanish from the comparison as
    though it had never been run.

    Returns (kept_job_ids, x_values, per-series value lists, skipped, notes)."""
    mgr = get_job_manager()
    kept: list[str] = []
    x_values: list[Optional[float]] = []
    columns: list[list[Optional[float]]] = [[] for _ in series_specs]
    skipped: list[str] = []
    notes: list[tuple[str, str]] = []

    for job_id in job_ids:
        result = mgr.result(job_id)
        if result is None or result.get("status") != "completed":
            skipped.append(f"{job_id} (not completed)")
            continue
        summary = result.get("summary") or {}

        x_value: Optional[float] = None
        if x_field:
            try:
                x_value = _resolve_cell(summary, x_field, job_id)
            except _FieldPathError as e:
                skipped.append(f"{job_id} ({e})")
                continue

        cells: list[Optional[float]] = []
        for s in series_specs:
            # y_field_by_job is the hook plot_job_comparison uses to ask a
            # different literal key of each job for what is conceptually one
            # quantity ("energy" being final_energy_hartree here and
            # casscf_energy_hartree there). Internal to that builder, not part
            # of the spec the model writes -- one series still means one line
            # in the legend either way, so this is a resolution detail rather
            # than a second kind of series.
            path = (s.get("y_field_by_job") or {}).get(job_id) or s["y_field"]
            try:
                cells.append(_resolve_cell(summary, path, job_id))
            except _FieldPathError as e:
                # Both halves are kept. When the plot draws, all the reply needs
                # is which job lost which value, and repeating the resolver's
                # full "available fields" listing once per job would bury it.
                # When NOTHING resolves anywhere, the refusal needs the real
                # reason instead, and the reasons genuinely differ: a field
                # that is absent and a field that is present but needs an index
                # are not the same mistake to correct.
                cells.append(None)
                notes.append((f"{path} in {job_id}", str(e)))

        kept.append(job_id)
        x_values.append(x_value)
        for i, cell in enumerate(cells):
            columns[i].append(cell)

    return kept, x_values, columns, skipped, notes


def _rows_from_one_job(
    job_id: str, x_field: Optional[str], series_specs: list[dict],
) -> tuple[Optional[tuple[list[Optional[float]], list[list[Optional[float]]], list[str]]], Optional[str]]:
    """Rows are array positions inside a single job's summary -- a pes_1d
    master's coordinate_values against its energies, or one job's own stick
    spectrum. Returns ((x_values, per-series value lists, notes), None) or
    (None, error).

    This is not a third branch dodging the rules above, and the reason is worth
    recording because someone will otherwise "simplify" it away: a scalar
    promotes to a one-element list, so asking a single job for
    excitation_energies_eV[0] and [1] yields exactly one row here, which is the
    same plot the rows-are-jobs reading would give. The two readings coincide
    BECAUSE of scalar promotion."""
    result = get_job_manager().result(job_id)
    if result is None or result.get("status") != "completed":
        return None, f"Job {job_id} is not a completed job -- cannot plot from it."
    summary = result.get("summary") or {}
    notes: list[tuple[str, str]] = []

    def as_list(path: str) -> list:
        raw = _resolve_field_path(summary, path)
        return list(raw) if isinstance(raw, list) else [raw]

    x_values: Optional[list[Optional[float]]] = None
    if x_field:
        try:
            x_values = [_as_float(v, x_field) for v in as_list(x_field)]
        except _FieldPathError as e:
            return None, str(e)

    resolved: list[Optional[list[Optional[float]]]] = []
    for s in series_specs:
        try:
            resolved.append([_as_float(v, s["y_field"]) for v in as_list(s["y_field"])])
        except _FieldPathError as e:
            resolved.append(None)
            notes.append((s["y_field"], str(e)))

    lengths = {len(v) for v in resolved if v is not None}
    if x_values is not None:
        lengths.add(len(x_values))
    if not lengths:
        return None, _nothing_resolved_message(notes)
    if len(lengths) > 1:
        return None, ("The requested fields have different lengths in job "
                      f"{job_id} ({sorted(lengths)}), so they can't be paired into points.")
    n_rows = lengths.pop()

    columns = [v if v is not None else [None] * n_rows for v in resolved]
    if x_values is None:
        x_values = [None] * n_rows
    return (x_values, columns, notes), None


def _apply_plot_units(spec: dict, series_specs: list, labels: list, columns: list):
    """(columns, ylabel, error) after any requested unit conversion.

    Three spec fields, all optional:

      y_units            what to draw the y values IN
      y_units_from       what they are already in, when the field name
                         does not say (this project names fields with their
                         unit -- energies_hartree, excitation_energies_eV --
                         so this is rarely needed, and guessing on the
                         caller's behalf when the name is silent would be
                         the one mistake with no symptom)
      y_reference_hartree  an ABSOLUTE energy to measure from, so the axis
                         becomes "how far above this", not "what is this"

    A reference implies eV unless something else is asked for, because
    "relative to -76.412 hartree" is a request for a scale a human can read
    and hartree differences are 0.00x. It also restricts the target to
    hartree or eV: a difference between two energies has no wavelength and
    no wavenumber. The same units module backs `convert_energy_units`, so
    an axis and a number in the reply cannot drift apart.
    """
    reference = spec.get("y_reference_hartree")
    target = spec.get("y_units") or ("eV" if reference is not None else None)
    if target is None:
        return columns, None, None
    dst = units.canonical_unit(target)
    if dst is None:
        return None, None, (f"{target!r} is not an energy unit this converts. "
                            f"Use one of {', '.join(units.ENERGY_UNITS)}.")
    if reference is not None:
        try:
            reference = float(reference)
        except (TypeError, ValueError):
            return None, None, f"y_reference_hartree must be a number in hartree; got {reference!r}."

    declared = spec.get("y_units_from")
    out = []
    for series_spec, column in zip(series_specs, columns):
        source = declared or units.unit_of_field(series_spec.get("y_field") or "")
        if source is None:
            return None, None, (
                f"Nothing says what unit {series_spec.get('y_field')!r} is in -- its name does not "
                f"carry one. Give y_units_from ({', '.join(units.ENERGY_UNITS)}) as well, rather "
                f"than have the axis relabelled without the numbers changing."
            )
        converted, error = units.convert_values(column, source, dst, reference)
        if error:
            return None, None, error
        out.append(converted)

    if reference is not None:
        ylabel = f"Energy relative to {reference:.6g} hartree ({dst})"
    else:
        ylabel = f"{labels[0]} ({dst})" if len(labels) == 1 else f"Energy ({dst})"
    return out, ylabel, None


def _plot_custom(spec: Optional[dict], state: Annotated[AgentState, InjectedState],
                 plot_id: Optional[str] = None) -> str:
    """kind="custom": one declarative chart spec, drawn in three ordered
    stages, each with exactly one rule:

        rows       what one x slot IS      data-determined by len(job_ids)
        placement  where that slot SITS    x_field present ? numeric : index
        marks      how a value is DRAWN    style

    Every chart this tool can make is a combination of those three, which is
    why there is no per-chart-kind branch here and why a new request usually
    lands as a different `style` rather than new code. See plot()'s docstring
    for the spec's shape."""
    if not isinstance(spec, dict):
        return ("A custom plot needs `spec` -- a dict with at least 'series' "
                "(a list of {'y_field': ..., 'label': ...}).")

    job_ids = spec.get("job_ids") or (state.get("active_job_ids", []) if state else [])
    if not job_ids:
        return "No jobs are attached or active in this conversation to plot from."

    series_specs = spec.get("series")
    if not isinstance(series_specs, list) or not series_specs:
        return "A custom plot needs spec['series'] -- a non-empty list of {'y_field': ..., 'label': ...}."
    for s in series_specs:
        if not isinstance(s, dict) or not s.get("y_field"):
            return "Every entry in spec['series'] needs a 'y_field'."

    style = spec.get("style") or "line"
    if style not in SERIES_PLOT_STYLES:
        return (f"'{style}' is not a plot style this app draws. Use "
                f"{', '.join(SERIES_PLOT_STYLES)}.")

    x_field = spec.get("x_field")
    labels = [s.get("label") or s["y_field"] for s in series_specs]

    # --- rows -------------------------------------------------------------
    rows_are_jobs = len(job_ids) > 1
    skipped: list[str] = []
    if rows_are_jobs:
        kept_job_ids, x_values, columns, skipped, notes = _rows_from_jobs(job_ids, x_field, series_specs)
        if not kept_job_ids:
            detail = f" Skipped: {'; '.join(skipped)}." if skipped else ""
            return f"No job had a usable column for this plot.{detail}"
        default_labels = _default_column_labels(kept_job_ids)
        primary_job_id = kept_job_ids[0]
    else:
        built, error = _rows_from_one_job(job_ids[0], x_field, series_specs)
        if error:
            return error
        x_values, columns, notes = built
        kept_job_ids = job_ids
        default_labels = (
            [_format_tick(v) for v in x_values] if x_field
            else [str(i + 1) for i in range(len(x_values))]
        )
        primary_job_id = job_ids[0]

    if all(v is None for column in columns for v in column):
        # Nothing resolved anywhere, so this is the refusal rather than a plot
        # with gaps, and the caller needs the real reason to correct the guess.
        return _nothing_resolved_message(notes)

    tick_labels, label_error = _column_labels(spec.get("x_labels"), kept_job_ids, default_labels, rows_are_jobs)
    if label_error:
        return label_error

    # --- placement --------------------------------------------------------
    # Sort by x in exactly one case: a numeric axis whose rows are unrelated
    # jobs, where the trend along that axis is the point. Never for categories
    # (the caller's order is the meaningful one) and never for a single job's
    # own arrays (the array order already is the coordinate order).
    if rows_are_jobs and x_field:
        order = sorted(range(len(x_values)), key=lambda i: x_values[i])
        x_values = [x_values[i] for i in order]
        tick_labels = [tick_labels[i] for i in order]
        columns = [[column[i] for i in order] for column in columns]

    numeric_axis = bool(x_field) and style in ("line", "scatter")
    if numeric_axis:
        positions: list[float] = [float(v) for v in x_values]
        tick_labels = None
    else:
        positions = [float(i) for i in range(len(columns[0]))]

    # --- units ------------------------------------------------------------
    # Between placement and marks: the values being drawn are settled, and
    # nothing downstream (log_y's positivity check, the cached copy, the
    # renderer) should ever see the pre-conversion numbers.
    converted, unit_ylabel, unit_error = _apply_plot_units(spec, series_specs, labels, columns)
    if unit_error:
        return unit_error
    columns = converted

    # --- marks ------------------------------------------------------------
    log_y = bool(spec.get("log_y", False))
    if log_y and any(v is not None and v <= 0 for column in columns for v in column):
        return "log_y was requested but at least one y value is <= 0, which can't be shown on a log axis."

    series = [
        {"label": label, "values": column, "color": s.get("color")}
        for label, column, s in zip(labels, columns, series_specs)
    ]
    xlabel = spec.get("xlabel") or (x_field if x_field else "")
    ylabel = spec.get("ylabel") or unit_ylabel or (labels[0] if len(labels) == 1 else "Value")
    title = spec.get("title") or "Custom plot"

    # The numbers as drawn are cached on the record alongside the spec. They
    # are what answers a question about the plot once it is attached to a
    # prompt (the model cannot see the PNG), and what keeps the plot readable
    # after some of its source jobs have been evicted.
    cached = {
        "columns": tick_labels if tick_labels is not None else [f"{p:g}" for p in positions],
        "series": {label: list(column) for label, column in zip(labels, columns)},
    }
    record, version, error = _save_plot(
        state, kind="custom", label=title, spec=dict(spec, job_ids=kept_job_ids),
        job_ids=kept_job_ids, data=cached, plot_id=plot_id,
        render=lambda path: render_series_plot(
            positions, tick_labels, series, xlabel, ylabel, title, path, style=style, log_y=log_y),
    )
    if error:
        return error

    detail = ""
    if skipped:
        detail += f" Left out: {'; '.join(skipped)}."
    if notes:
        detail += f" Drawn as gaps, no value found for: {'; '.join(n for n, _ in notes)}."
    return (
        f"{_plot_marker(record, version)}\n"
        f"Drew a {style} plot of {', '.join(labels)} across {len(positions)} "
        f"{'job' if rows_are_jobs else 'point'}(s); it is now shown to the user.{detail} "
        f"Its plot id is {record['plot_id']}, so it can be edited or asked about later. "
        f"Present the underlying values as a markdown table in your reply as well."
    )


def _plot_spectra(spec: Optional[dict], state: Annotated[AgentState, InjectedState],
                  plot_id: Optional[str] = None) -> str:
    """kind="spectra": several jobs' total spectra on one axis.

    The one shape the existing plots could not make. `uvvis`/`ir`/`ensemble`
    each draw a single job, and a custom plot resolves ONE value per job
    across several jobs -- neither can put N curves on one x axis, which is
    what comparing methods means.

    Two things make the comparison honest rather than decorative. Every
    curve is resampled onto ONE shared grid spanning the union of their
    ranges, because each source builds its own grid from its own data and
    two methods' curves are otherwise not comparable point-for-point. And
    every curve is normalized to its own peak, so shapes and peak positions
    compare directly and each curve still matches how that same spectrum
    looks on its own -- the user chose this over a shared divisor, which
    would keep relative intensity but make every curve disagree with its
    own single-job view.

    An IR spectrum and a UV/Vis spectrum are refused as a pair rather than
    converted onto one scale: cm-1 and eV are both energy, but a vibrational
    band and an electronic transition on one axis is a picture of nothing.
    """
    spec = spec or {}
    job_ids = spec.get("job_ids") or (state.get("active_job_ids", []) if state else [])
    if not job_ids:
        return "No jobs are attached or active in this conversation to plot spectra from."

    curves, skipped = [], []
    for jid in job_ids:
        x, y, meta, error = spectrum_source.total_spectrum_for_job(jid, spec.get("fwhm"))
        if error:
            skipped.append(error)
            continue
        curves.append((jid, x, y, meta))

    if not curves:
        return "No job here has a spectrum to draw. " + " ".join(skipped)

    axes = {meta["axis_units"] for _, _, _, meta in curves}
    if len(axes) > 1:
        named = ", ".join(f"{jid[:8]} ({meta['label']}, {meta['axis_units']})"
                          for jid, _, _, meta in curves)
        return (
            f"These spectra are not on the same axis, so they cannot share a plot: {named}. "
            f"An IR spectrum is in cm-1 and an electronic spectrum in eV; plot them separately."
        )
    axis_units = axes.pop()

    labels = _default_column_labels([jid for jid, _, _, _ in curves])
    override = spec.get("labels") or {}
    labels = [override.get(jid, label) for (jid, _, _, _), label in zip(curves, labels)]

    lo = min(float(x.min()) for _, x, _, _ in curves)
    hi = max(float(x.max()) for _, x, _, _ in curves)
    grid = np.linspace(lo, hi, 2000)
    # Outside a curve's own range its intensity really is zero -- the
    # broadening has died off -- so extending with 0 is the physical answer,
    # not padding.
    def _onto_grid(x, y):
        # Renormalized after resampling, not before: the shared grid does
        # not land exactly on each curve's own maximum, so an already-
        # normalized curve comes off it peaking at 0.99996. Every drawn
        # curve topping out at exactly 1 is the invariant this plot is
        # read against, and it should be true of what is drawn rather than
        # of what was drawn from.
        resampled = np.interp(grid, x, y, left=0.0, right=0.0)
        peak = float(np.max(resampled))
        return resampled / peak if peak > 0 else resampled

    series = {label: _onto_grid(x, y) for label, (_, x, y, _) in zip(labels, curves)}

    x_units = spec.get("x_units")
    xlabel = f"Energy ({axis_units})" if axis_units == "eV" else f"Wavenumber ({axis_units})"
    if x_units:
        converted, error = units.convert_values(list(grid), axis_units, x_units)
        if error:
            return error
        grid = np.asarray(converted, dtype=float)
        # nm runs the other way from eV, so re-sort rather than hand
        # matplotlib a decreasing x and a backwards axis.
        order = np.argsort(grid)
        grid = grid[order]
        series = {label: values[order] for label, values in series.items()}
        dst = units.canonical_unit(x_units)
        xlabel = f"Wavelength ({dst})" if dst == "nm" else f"Energy ({dst})"

    title = spec.get("title") or ("Spectra" if len(curves) > 1 else curves[0][3]["label"].capitalize())
    ylabel = spec.get("ylabel") or "Normalized intensity"

    # Cached at the sampled resolution the tagged-job context uses: this is
    # what answers a question about the plot later (the model cannot see the
    # PNG), and 2000 points per series would be unreadable. Every curve's
    # own peak index joins the evenly spaced ones, so each series still
    # reaches exactly 1.0 in the cached table -- a curve documented as
    # normalized to its own peak and topping out at 0.996 reads as a result
    # rather than as sampling.
    idx = np.unique(np.concatenate(
        [np.linspace(0, grid.size - 1, 64).round().astype(int)]
        + [[int(np.argmax(values))] for values in series.values()]
    ))
    cached = {
        "columns": [f"{v:.4g}" for v in grid[idx]],
        "series": {label: [float(v) for v in values[idx]] for label, values in series.items()},
    }
    record, version, error = _save_plot(
        state, kind="spectra", label=title,
        spec=dict(spec, job_ids=[jid for jid, _, _, _ in curves]),
        job_ids=[jid for jid, _, _, _ in curves], data=cached, plot_id=plot_id,
        render=lambda path: render_line_plot(
            [float(v) for v in grid],
            {label: [float(v) for v in values] for label, values in series.items()},
            xlabel, ylabel, title, path),
    )
    if error:
        return error

    detail = f" Left out: {' '.join(skipped)}" if skipped else ""
    return (
        f"{_plot_marker(record, version)}\n"
        f"Drew {len(series)} spectra on one shared {xlabel} axis, each normalized to its own "
        f"peak: {', '.join(series)}.{detail} Its plot id is {record['plot_id']}, so it can be "
        f"edited or asked about later. Say in your reply that each curve is normalized to its "
        f"own peak, so heights compare shape and position rather than absolute intensity."
    )


def _merge_plot_spec(current: dict, patch: dict) -> dict:
    """Apply an edit patch to a stored spec.

    Everything merges shallowly except `series`, which merges BY LABEL. That
    is what lets "make S2 red" be `{"series": [{"label": "S2", "color":
    "red"}]}` rather than a restatement of every series with its field paths,
    which the model gets wrong far more often than it gets right. A patch
    series whose label is not already present is appended, so adding a state
    to an existing diagram works the same way.

    A null value removes a key, which is the only way to say "stop using a log
    axis" or "drop the title" in a merge that otherwise only ever adds."""
    merged = dict(current)
    for key, value in patch.items():
        if key == "series" and isinstance(value, list):
            by_label = {s.get("label") or s.get("y_field"): dict(s) for s in current.get("series", [])}
            order = list(by_label)
            for entry in value:
                label = entry.get("label") or entry.get("y_field")
                if label in by_label:
                    by_label[label].update(entry)
                else:
                    by_label[label] = dict(entry)
                    order.append(label)
            merged["series"] = [by_label[label] for label in order]
        elif value is None:
            merged.pop(key, None)
        else:
            merged[key] = value
    return merged


def _plot_edit(plot_id: Optional[str], patch: Optional[dict], state) -> str:
    """kind="edit": patch a saved plot's spec and draw it again.

    Custom plots and overlaid spectra are editable through the spec, because
    those are the two that HAVE one a patch can address: an overlay carries
    its job ids, broadening, axis units and labels, so "add that job too" or
    "show it in nm" is a patch rather than a new plot. A SINGLE-job spectrum
    (uvvis/ir/ensemble) has no spec beyond its width, and changing that is
    re-plotting it, which is the same one-line request from the user's side,
    so the refusal below says so rather than just declining."""
    if not plot_id:
        return "An edit needs `plot_id` -- the id of the plot to change, which each plot reports when drawn."
    owner = _plot_owner(state)
    record = plot_store.get_plot(owner, plot_id)
    if record is None:
        return (f"No saved plot with id {plot_id}. It may have been deleted, or its source jobs may all "
                f"be gone, which reclaims the plot with them.")
    if record.get("kind") not in ("custom", "spectra"):
        return (f"Plot {plot_id} is a {record.get('kind')} spectrum, which has no editable spec. "
                f"Re-plot it with a different width instead.")
    if not isinstance(patch, dict) or not patch:
        return ("An edit needs `spec` -- the parts to change, e.g. {\"log_y\": true} or "
                "{\"series\": [{\"label\": \"S2\", \"color\": \"red\"}]}. Only the keys given change.")

    merged = _merge_plot_spec(record.get("spec") or {}, patch)
    if record.get("kind") == "spectra":
        return _plot_spectra(merged, state, plot_id=plot_id)
    return _plot_custom(merged, state, plot_id=plot_id)


@tool
def plot(
    kind: str,
    job_id: Optional[str] = None,
    job_ids: Optional[list[str]] = None,
    spec: Optional[dict] = None,
    plot_id: Optional[str] = None,
    state: Annotated[AgentState, InjectedState] = None,
) -> str:
    """Draw a plot from data a completed job actually produced.

    `kind` is one of:
      "uvvis"      -- broadened UV/Vis absorption from an excited-state job
      "ir"         -- broadened IR spectrum from a frequency job
      "ensemble"   -- nuclear-ensemble spectrum from a Wigner job (needs job_id)
      "pes_scan"   -- potential-energy-surface plot from a pes_1d/interp_pes
                      scan master (needs job_id)
      "comparison" -- one named scalar across several jobs, as bars
      "spectra"    -- several jobs' whole spectra on one axis, for comparing
                      methods (needs job_ids)
      "custom"     -- any other chart, described in `spec`
      "edit"       -- change a plot already drawn (needs plot_id)

    `spec` configures whichever kind was asked for.

    For "uvvis"/"ir"/"ensemble", only spec["width"] applies: the broadening,
    in eV for uvvis/ensemble (default 0.4) and cm-1 for ir (default 20).

    For "comparison", only spec["field"] applies, and it must be one of
    energy, homo_lumo_gap, zero_point_energy, enthalpy, gibbs_free_energy,
    ts_energy. No other name is accepted and none is guessed at. Use this
    when the quantity is one of those six, since it knows that "energy"
    lives under a different key in a CASSCF job than in an HF one.

    For "spectra", spec is {"job_ids": [...], and optionally "fwhm" (in the
    spectrum's own units: eV for UV/Vis, cm-1 for IR), "x_units" to draw an
    electronic spectrum against wavelength in nm instead of eV, "labels"
    keyed by job id, "title" and "ylabel"}. Each job's total spectrum is
    taken from what that job produced -- a pooled nuclear ensemble's own
    curve, or an excited-state or frequency job's sticks broadened the same
    way its single-job plot broadens them -- resampled onto one shared grid
    and normalized to its own peak, so shapes and peak positions compare
    across methods. UV/Vis and IR spectra are refused as a pair, since cm-1
    and eV are not one axis. Use this whenever the user asks to compare,
    overlay or combine spectra; the single-job kinds above draw one.

    For "custom", spec is the chart itself:
      {"job_ids": [...],        # optional, defaults to the jobs attached here
       "style": "line",         # line (default) | scatter | bar | levels
       "series": [{"y_field": "excitation_energies_eV[0]",
                   "label": "S1", "color": "#0072B2"}, ...],
       "x_field": "coordinate_values",           # OPTIONAL, see below
       "x_labels": {"<job id>": "TD-HF", ...},   # optional column names
       "y_units": "eV",                          # optional, see Units below
       "y_units_from": "hartree",                # optional
       "y_reference_hartree": -76.412,           # optional
       "xlabel": ..., "ylabel": ..., "title": ..., "log_y": false}

    The x axis:
      - OMIT x_field for a categorical axis: one column per job, in the order
        given, labelled with each job's name. This is what "compare these
        methods" or "put the method names on the x axis" means. Override the
        names with x_labels, a mapping keyed by job id.
      - GIVE x_field for a numeric axis, e.g. a bond length each job recorded
        in its own `constraints`. Points are then ordered by x value.

    Rows: several job_ids means one row per job, so every field path must
    resolve to ONE value per job (add an index, like
    "excitation_energies_eV[0]"). One job_id means one row per array position
    inside that job's summary, e.g. a pes_1d master's coordinate_values
    against its energies.

    Units: give y_units to draw the y values in hartree, eV, nm or cm-1
    whatever they are stored in -- the field's own name says what that is
    (energies_hartree, excitation_energies_eV), so y_units_from is needed
    only for a field whose name does not. Give y_reference_hartree to plot
    energies as distances above one absolute energy in hartree, which is
    what "relative to the ground state" or "relative to -76.412 hartree"
    means; that implies eV unless you ask for hartree, and cannot be nm or
    cm-1, since a difference between two energies has no wavelength. Do not
    convert numbers yourself and pass them in -- convert_energy_units and
    this share one implementation, so an axis and a reply agree by
    construction.

    Styles: "line" connects the points, "scatter" does not, "bar" is one bar
    per series per column, and "levels" is a short horizontal tick per value,
    which is what draws an energy-level diagram.

    Each series gets its own colour and its own legend entry. A field path
    missing from one job leaves a gap there and keeps that job's column; the
    missing paths are named in the reply. A path missing everywhere is
    refused, listing the fields that really are there, never fabricated.

    Example, excitation energies of several methods as a level diagram:
      kind="custom", spec={"style": "levels",
        "job_ids": ["37eafc65723d", "baf608e6306e", "ca321aaefd97"],
        "series": [{"y_field": "excitation_energies_eV[0]", "label": "S1"},
                   {"y_field": "excitation_energies_eV[1]", "label": "S2"}],
        "x_labels": {"37eafc65723d": "TD-HF", "baf608e6306e": "B3LYP",
                     "ca321aaefd97": "XMS-CASPT2"},
        "ylabel": "Excitation energy (eV)"}

    Every plot is saved and reports its `plot_id`. To change one, call
    kind="edit" with that plot_id and a `spec` holding ONLY the parts that
    change: {"log_y": true}, or {"title": "..."}, or {"series": [{"label":
    "S2", "color": "red"}]}, which finds the existing S2 series by its label
    and recolours it. Everything not mentioned stays as it was, and a value of
    null removes a setting. Prefer this over redrawing from scratch when the
    user asks to adjust a plot they can already see.

    If the data a plot needs is missing -- excitation energies with no
    oscillator strengths, say -- this refuses and explains why. Relay that
    explanation. Never describe a spectrum that was not drawn.
    """
    spec = spec or {}
    width = spec.get("width")
    if kind == "uvvis":
        return plot_excited_state_spectrum(job_id=job_id, fwhm_eV=width, state=state)
    if kind == "ir":
        return plot_ir_spectrum(job_id=job_id, fwhm_cm1=width, state=state)
    if kind == "ensemble":
        if not job_id:
            return "A nuclear-ensemble plot needs the wigner_ensemble job's id."
        return plot_wigner_ensemble_spectrum(job_id=job_id, fwhm_eV=width, state=state)
    if kind == "pes_scan":
        if not job_id:
            return "A PES scan plot needs the pes_1d/interp_pes job's id."
        return plot_pes_scan(job_id=job_id, state=state)
    if kind == "comparison":
        field = spec.get("field")
        if not field:
            return ("A comparison plot needs spec['field'] -- one of energy, homo_lumo_gap, "
                    "zero_point_energy, enthalpy, gibbs_free_energy, ts_energy.")
        return plot_job_comparison(field=field, job_ids=job_ids or spec.get("job_ids"), state=state)
    if kind == "spectra":
        return _plot_spectra(spec, state)
    if kind == "custom":
        if job_ids and not spec.get("job_ids"):
            spec = {**spec, "job_ids": job_ids}
        return _plot_custom(spec, state)
    if kind == "edit":
        return _plot_edit(plot_id, spec, state)
    return (f"'{kind}' is not a plot this app draws. Use uvvis, ir, ensemble, comparison, "
            f"custom or edit.")


# P9.2: geometric-parameter queries (bond/angle/dihedral) against a
# tagged job or instrument-panel molecule frame.

_ORDERED_TABLE_TASKS = geometry_resolve.ORDERED_TABLE_TASKS
_HISTOGRAM_TASKS = geometry_resolve.HISTOGRAM_TASKS


def _geometry_parameter_unit(ptype: str) -> str:
    return "Å" if ptype == "bond" else "°"


def _geometry_parameter_label(param: dict) -> str:
    return f"{param['type']}({','.join(str(a) for a in param['atoms'])})"


def _compute_geometry_parameter(ptype: str, atoms: list[int], coords: np.ndarray) -> float:
    idx = [a - 1 for a in atoms]  # 1-based (matches the 3D viewer) -> 0-based
    if ptype == "bond":
        return _distance(coords[idx[0]], coords[idx[1]])
    if ptype == "angle":
        return _angle_deg(coords[idx[0]], coords[idx[1]], coords[idx[2]])
    return _dihedral_deg(coords[idx[0]], coords[idx[1]], coords[idx[2]], coords[idx[3]])


def _validate_parameters_list(parameters) -> tuple[Optional[list[dict]], Optional[str]]:
    if not isinstance(parameters, list) or not parameters:
        return None, ("`parameters` must be a non-empty list of {'type': 'bond'|'angle'|'dihedral', "
                       "'atoms': [...]}.")
    cleaned = []
    for p in parameters:
        if not isinstance(p, dict):
            return None, f"Each parameter must be an object like {{'type': 'bond', 'atoms': [1, 2]}} -- got {p!r}."
        cleaned.append({"type": p.get("type"), "atoms": p.get("atoms")})
    return cleaned, None


def _geometry_params_for_molecule(parameters: list[dict], molecule: dict) -> tuple[Optional[list[float]], Optional[str]]:
    """Validates every parameter's atom indices against THIS ONE
    molecule's atom count (query parameters share the same
    _validate_atom_indices path opt/constrained's own constraints use --
    see that function's docstring) and computes each, once. Used both for
    a single tagged geometry and, per-frame, for an ordered master's
    table."""
    symbols = molecule.get("symbols") or []
    n_atoms = len(symbols)
    coords = np.array(molecule.get("coords") or [], dtype=float)
    values = []
    for p in parameters:
        err = _validate_atom_indices(p["type"], p["atoms"], n_atoms, subject="query parameter")
        if err:
            return None, err
        values.append(_compute_geometry_parameter(p["type"], p["atoms"], coords))
    return values, None


# Tasks with no single well-defined geometry, and the (molecule, error)
# resolver for those that do have one -- moved to
# app/chemistry/jobs/geometry_resolve.py so P9.3's
# app/chemistry/registry2/elicitation.py can reuse the exact same function
# for source_geometry_job_id, without elicitation.py (deliberately
# independent of the agent layer) importing from here.
_NO_SINGLE_GEOMETRY_TASKS = geometry_resolve.NO_SINGLE_GEOMETRY_TASKS
_resolve_single_completed_geometry = geometry_resolve.resolve_single_completed_geometry


def _resolve_frame_geometry(frame_id: str, state) -> tuple[Optional[dict], Optional[str]]:
    frames = (state.get("molecule_frames") or []) if state else []
    for f in frames:
        if f.get("id") == frame_id:
            return f.get("molecule"), None
    return None, f"No such molecule frame: {frame_id}."


def _resolve_batch_children(job_id: str) -> tuple[list[tuple[str, dict]], list[str]]:
    """(child_id, molecule) pairs for a batch master's COMPLETED children
    only (a pending/running/failed child is named in the returned skip
    list, not silently dropped). batch is the one master
    BATCH_GEOMETRY_SOURCE_ARTIFACT_KEY deliberately excludes -- its
    children can be a heterogeneous mix of starting geometries (see that
    map's own comment in registry2/tasks.py) -- so each child's own
    geometry is read individually here and its own atom count is
    validated per child at the call site, rather than assumed uniform
    the way an ordered scan's frames are."""
    mgr = get_job_manager()
    out: list[tuple[str, dict]] = []
    skipped: list[str] = []
    for child_id in sub_job_ids_of(job_id):
        result = mgr.result(child_id)
        if result is None or result.get("status") != "completed":
            skipped.append(f"{child_id} (not completed)")
            continue
        summary = result.get("summary") or {}
        molecule = summary.get("optimized_molecule")
        if not molecule:
            child_spec = read_spec(child_id)
            molecule = (child_spec or {}).get("molecule")
        if not molecule:
            skipped.append(f"{child_id} (no geometry available)")
            continue
        out.append((child_id, molecule))
    return out, skipped


def _geometry_parameters_table(job_id: str, spec: dict, parameters: list[dict]) -> str:
    frames, row_labels, coordinate_label, err = geometry_resolve.resolve_ordered_master_frames(job_id, spec)
    if err:
        return err
    header = f"| # | {coordinate_label} | " + " | ".join(_geometry_parameter_label(p) for p in parameters) + " |"
    sep = "|" + "---|" * (2 + len(parameters))
    rows = []
    for i, (frame, label) in enumerate(zip(frames, row_labels)):
        n_atoms = len(frame.symbols)
        coords = np.array(frame.coords, dtype=float)
        row_values = []
        for p in parameters:
            # Every frame of one scan/path/set shares one starting
            # molecule's atom count -- an out-of-range index here is a
            # bad request, not a per-frame data-quality issue, so this
            # fails fast on the first bad frame rather than accumulating
            # what would just be N identical complaints.
            err2 = _validate_atom_indices(p["type"], p["atoms"], n_atoms, subject="query parameter")
            if err2:
                return err2
            row_values.append(f"{_compute_geometry_parameter(p['type'], p['atoms'], coords):.4f}")
        rows.append(f"| {i + 1} | {label} | " + " | ".join(row_values) + " |")
    return header + "\n" + sep + "\n" + "\n".join(rows)


_MIN_HISTOGRAM_SAMPLES = 2


def _geometry_parameters_histogram(job_id: str, task: str, parameters: list[dict], state=None) -> str:
    skipped: list[str] = []
    if task == "batch":
        pairs, skipped = _resolve_batch_children(job_id)
        geometries = [
            (cid, np.array(m.get("coords") or [], dtype=float), len(m.get("symbols") or []))
            for cid, m in pairs
        ]
    else:  # wigner_spectra -- one shared ensemble_xyz artifact, same read as the ordered-table path
        result = get_job_manager().result(job_id)
        if result is None:
            return f"No such job: {job_id}."
        artifact_key = BATCH_GEOMETRY_SOURCE_ARTIFACT_KEY.get(task)
        path = (result.get("artifacts") or {}).get(artifact_key) if artifact_key else None
        if not path:
            return f"Job {job_id} has no geometries recorded yet."
        try:
            frames = geometry_upload.parse_multi_frame_xyz(Path(path).read_text())
        except (OSError, ValueError) as e:
            return f"Could not read job {job_id}'s geometries: {e}"
        geometries = [
            (f"sample {i + 1}", np.array(f.coords, dtype=float), len(f.symbols)) for i, f in enumerate(frames)
        ]

    data_by_label: dict[str, list[float]] = {_geometry_parameter_label(p): [] for p in parameters}
    for cid, coords, n_atoms in geometries:
        for p in parameters:
            err = _validate_atom_indices(p["type"], p["atoms"], n_atoms, subject="query parameter")
            if err:
                skipped.append(f"{cid} ({err})")
                continue
            data_by_label[_geometry_parameter_label(p)].append(_compute_geometry_parameter(p["type"], p["atoms"], coords))

    thin = [f"{label} ({len(vals)})" for label, vals in data_by_label.items() if len(vals) < _MIN_HISTOGRAM_SAMPLES]
    if thin:
        detail = f" Skipped: {'; '.join(skipped[:10])}." if skipped else ""
        return (f"Not enough usable geometries to histogram {', '.join(thin)} (need at least "
                f"{_MIN_HISTOGRAM_SAMPLES}).{detail}")

    units_by_label = {_geometry_parameter_label(p): _geometry_parameter_unit(p["type"]) for p in parameters}
    label = f"{', '.join(data_by_label)} distribution, {resolve_job_label(read_spec(job_id) or {}, read_meta(job_id))}"
    record, version, error = _save_plot(
        state, kind="histogram", label=label,
        spec={"kind": "histogram", "parameters": parameters}, job_ids=[job_id],
        data={lbl: list(vals) for lbl, vals in data_by_label.items()},
        render=lambda path: render_histogram_plot(data_by_label, units_by_label, path),
    )
    if error:
        return error

    # Per-parameter counts, not one shared "n used" -- a geometry skipped
    # for one parameter (e.g. too few atoms for a dihedral) can still
    # contribute to another, so there is no single "geometries used"
    # figure that's accurate across every panel; each panel's own title
    # already carries its own count (see render_histogram_plot).
    counts_text = ", ".join(f"{label} (n={len(vals)})" for label, vals in data_by_label.items())
    note = f" (skipped: {'; '.join(skipped[:10])})" if skipped else ""
    return (
        f"{_plot_marker(record, version)}\n"
        f"Generated a histogram across {len(geometries)} geometries: {counts_text}; it is now shown to "
        f"the user.{note}"
    )


@tool
def geometry_parameters(
    parameters: list[dict],
    job_id: Optional[str] = None,
    frame_id: Optional[str] = None,
    state: Annotated[AgentState, InjectedState] = None,
) -> str:
    """Compute a bond length, angle, or dihedral against a tagged job or
    instrument-panel molecule frame -- "what's the O-H1 bond length",
    "the angle between atoms 2, 1 and 3", several such requests in one call.

    `parameters` is a list of {"type": "bond"|"angle"|"dihedral", "atoms":
    [...]} -- exactly opt/constrained's own `constraints` shape minus
    'value' (2/3/4 1-based atom indices, matching the numbers shown in the
    3D viewer). An out-of-range or malformed index is refused, naming the
    problem -- never crashed on or silently clamped.

    Give either `job_id` (a completed job -- its optimized_molecule if it
    produced one, else its input molecule) or `frame_id` (a molecule frame
    from the instrument panel). With neither, this falls back to whatever
    molecule is currently displayed (the full explicit-tag > conversation-
    context > active-frame default hierarchy is P9.3, not yet built).

    A tagged pes_1d/interp_pes master or multi-frame geometry_set returns
    a TABLE -- one row per scan point/image, ordered, one column per
    requested parameter, because the trend along the path is the whole
    reason to tag a scan. A tagged batch or wigner_spectra master instead
    returns one HISTOGRAM per requested parameter (one image, one panel
    per parameter) -- an unordered collection or a statistical ensemble,
    where the distribution is the point, not any single member.
    """
    cleaned, err = _validate_parameters_list(parameters)
    if err:
        return err

    if job_id:
        spec = read_spec(job_id)
        if spec is None:
            return f"No such job: {job_id}."
        task = spec.get("task") or ""
        if task in _ORDERED_TABLE_TASKS:
            return _geometry_parameters_table(job_id, spec, cleaned)
        if task in _HISTOGRAM_TASKS:
            return _geometry_parameters_histogram(job_id, task, cleaned, state)
        molecule, err = _resolve_single_completed_geometry(job_id)
    elif frame_id:
        molecule, err = _resolve_frame_geometry(frame_id, state)
    else:
        molecule = state.get("molecule") if state else None
        err = None if molecule else "No job or molecule frame was tagged, and no molecule is currently displayed."

    if err:
        return err

    values, err = _geometry_params_for_molecule(cleaned, molecule)
    if err:
        return err

    rows = "\n".join(
        f"| {_geometry_parameter_label(p)} | {','.join(str(a) for a in p['atoms'])} | {v:.4f} | "
        f"{_geometry_parameter_unit(p['type'])} |"
        for p, v in zip(cleaned, values)
    )
    return "| Parameter | Atoms | Value | Unit |\n|---|---|---|---|\n" + rows


@tool
def convert_energy_units(
    values: list[float],
    from_units: str,
    to_units: str,
    reference_hartree: Optional[float] = None,
) -> str:
    """Convert energies between hartree, eV, nm and cm-1.

    All four are units of energy, so any of them converts to any other --
    "what is 0.15 hartree in nm", "give those excitation energies in
    wavenumbers", "that absorption is at 480 nm, what is that in eV".
    Wavelength is inversely proportional to the other three, so a value in
    nm must be positive and an energy of exactly zero has no wavelength.

    `reference_hartree` re-expresses each value as its distance ABOVE that
    absolute energy, which is what "relative to the ground state" or
    "relative to -76.412 hartree" means. A difference between two energies
    has no wavelength or wavenumber, so with a reference the answer can
    only be in hartree or eV -- ask for the absolute values instead if you
    want nm or cm-1.

    Use this rather than doing the arithmetic yourself: it is the same
    conversion the plots use, so a number in a reply and a number on an
    axis cannot disagree.
    """
    if not isinstance(values, list) or not values:
        return "Give `values` as a non-empty list of numbers."
    converted, error = units.convert_values(values, from_units, to_units, reference_hartree)
    if error:
        return error
    src, dst = units.canonical_unit(from_units), units.canonical_unit(to_units)
    rows = "\n".join(
        f"| {v:.6g} | {c:.6g} |" for v, c in zip(values, converted) if c is not None
    )
    note = (f" relative to {reference_hartree:.6g} hartree" if reference_hartree is not None else "")
    return (f"{src} to {dst}{note}:\n\n| {src} | {dst} |\n|---|---|\n{rows}\n\n"
            f"Present these to the user as a table too, and keep the unit on every number.")


STATIC_TOOLS = [
    set_geometry, lookup_capabilities,
    search_active_space_literature, explain_active_space,
    start_job_draft, update_job_draft, submit_draft,
    check_job_status, plot, geometry_parameters, list_ensemble_geometries_in_window,
    convert_energy_units,
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
