"""Tools exposed to the LLM. Each tool either mutates graph state via
`Command(update=...)` (molecule/job tracking) or just returns a string the
LLM incorporates into its reply (status/result lookups).

Job submission never blocks: `submit_job` calls `JobManager.submit`, which
hands the work to a background subprocess and returns a job_id
immediately. The agent's job is to gather correct parameters and dispatch;
polling for completion is the Streamlit UI's responsibility, not the
graph's -- a node that awaited `status == completed` would freeze the UI
for the entire calculation.

`submit_job` additionally pauses via `interrupt()` after building the job
spec and before actually running anything, so the user can see the exact
input and approve or reject it -- see its docstring and the module-level
note below for why the pre-interrupt code path has to stay free of
side effects that aren't safe to repeat.
"""
from __future__ import annotations

from typing import Annotated, Optional

from langchain_core.messages import ToolMessage
from langchain_core.tools import InjectedToolCallId, tool
from langgraph.prebuilt import InjectedState
from langgraph.types import Command, interrupt

from app.agent.state import AgentState
from app.chemistry.jobs.base import JobSpec, get_job_manager
from app.chemistry.jobs.preview import build_input_preview
from app.chemistry.jobs.registry import (
    METHODS, PARAM_HELP, default_engine, missing_required_params,
)
from app.chemistry.jobs.validate import validate_input
from app.chemistry.molecule import resolve_molecule
from app.rag.query_tool import search_knowledge_base


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


def _build_spec_or_error(job_type: str, molecule: dict, engine: Optional[str], raw_params: dict):
    """Shared by generate_job_input and submit_job: validates required
    params, resolves the engine, builds the JobSpec, and renders its input
    preview. Returns (spec, preview_text, error_str) -- exactly one of
    (spec, preview_text) / error_str is populated.
    """
    if job_type not in METHODS:
        return None, None, f"Unknown job_type '{job_type}'. Valid options: {', '.join(METHODS)}"

    params = {k: v for k, v in raw_params.items() if v is not None}

    missing = missing_required_params(job_type, params)
    if missing:
        needs = "; ".join(f"{p} ({PARAM_HELP.get(p, 'no description')})" for p in missing)
        return None, None, (
            f"Cannot prepare this '{job_type}' job yet -- still missing: {needs}. "
            f"Ask the user for these specifically; do not assume default values for them."
        )

    try:
        resolved_engine = default_engine(job_type, engine)
    except ValueError as e:
        return None, None, str(e)

    spec = JobSpec(method=job_type, engine=resolved_engine, molecule=molecule, params=params)
    try:
        preview = build_input_preview(spec)
    except Exception as e:
        return None, None, f"Could not build the input for this job: {e}"

    return spec, preview, None


def _collect_params(
    qc_method, basis, functional, active_electrons, active_orbitals, n_states, weights,
    orbital_indices, coordinate_type, coordinate_atoms, scan_range, n_points, ms_caspt2,
    shift, frozen_core, df_basis, max_steps, temperature_K,
) -> dict:
    params = {
        "method": qc_method, "basis": basis, "functional": functional,
        "active_electrons": active_electrons, "active_orbitals": active_orbitals,
        "n_states": n_states, "weights": weights, "orbital_indices": orbital_indices,
        "scan_range": scan_range, "n_points": n_points, "ms_caspt2": ms_caspt2,
        "shift": shift, "frozen_core": frozen_core, "df_basis": df_basis,
        "max_steps": max_steps, "temperature_K": temperature_K,
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
    """Resolve a molecule from its common/IUPAC name or a SMILES string and
    make it the active molecule for this conversation. Call this whenever
    the user names or draws (via SMILES) a molecule, even if they haven't
    asked for a specific calculation yet -- the UI will show a 3D
    visualization of it. If the user mentions a non-default charge or spin
    multiplicity, pass them; otherwise leave them unset and sensible
    defaults (neutral, lowest-spin) are used.
    """
    molecule, desc = _resolve_or_error(identifier, charge, multiplicity)
    if molecule is None:
        return Command(update={"messages": [ToolMessage(content=desc, tool_call_id=tool_call_id)]})
    msg = desc + " A 3D visualization is now shown to the user."
    return Command(update={"molecule": molecule, "messages": [ToolMessage(content=msg, tool_call_id=tool_call_id)]})


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
    state: Annotated[AgentState, InjectedState] = None,
    tool_call_id: Annotated[str, InjectedToolCallId] = None,
) -> Command:
    """Build and return an engine input file/script WITHOUT running it.
    Use this when the user asks you to "write", "prepare", "generate", or
    "show" an input -- anything short of asking you to actually run/submit
    it. Show the returned text to the user verbatim in a code block, then
    STOP: do not call submit_job afterward unless the user separately and
    explicitly asks you to run it.

    Takes the same job_type/parameters as submit_job (see its docstring for
    the parameter contract and required-parameter rules per job_type). If
    the user named a molecule in the same message, pass it as
    molecule_identifier; it's resolved inline here since this tool never
    pauses or re-executes.
    """
    extra_state_update = {}
    molecule = state.get("molecule") if state else None
    if not molecule and molecule_identifier:
        molecule, desc = _resolve_or_error(molecule_identifier, None, None)
        if molecule is None:
            return Command(update={"messages": [ToolMessage(content=desc, tool_call_id=tool_call_id)]})
        extra_state_update["molecule"] = molecule
    if not molecule:
        return Command(update={"messages": [ToolMessage(
            content="No molecule is set yet. Call set_molecule first (or pass molecule_identifier here directly).",
            tool_call_id=tool_call_id,
        )]})

    raw_params = _collect_params(
        qc_method, basis, functional, active_electrons, active_orbitals, n_states, weights,
        orbital_indices, coordinate_type, coordinate_atoms, scan_range, n_points, ms_caspt2,
        shift, frozen_core, df_basis, max_steps, temperature_K,
    )
    spec, preview, error = _build_spec_or_error(job_type, molecule, engine, raw_params)
    if error:
        return Command(update={**extra_state_update, "messages": [ToolMessage(content=error, tool_call_id=tool_call_id)]})

    content = (
        f"Generated {spec.engine} input for a '{job_type}' job (NOT run). Show this to the user "
        f"verbatim in a code block, then stop -- do not call submit_job unless they explicitly ask "
        f"you to run/submit it.\n\n{preview}"
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
    state: Annotated[AgentState, InjectedState] = None,
    tool_call_id: Annotated[str, InjectedToolCallId] = None,
) -> Command:
    """Run a computational chemistry job on the active molecule in the
    background. Call this when the user asks you to run/submit/perform a
    calculation (not just generate its input -- use generate_job_input for
    that). `job_type` must be one of: single_point, geometry_optimization,
    frequency, casscf, caspt2, tddft, mo_visualization, pes_scan.

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
    parameters are still missing so you can ask the user. If the user
    rejects the approval, the job is not run; ask what they'd like to
    change or whether to cancel. For ORCA and BAGEL, the user can also
    hand-edit the shown input text before running it -- the UI validates
    that edited text (structural/keyword sanity checks, not a full run)
    before it's ever submitted here, and if the edit changes the input
    enough that the job_type-specific parser can't find expected results
    after a real run, the job fails with the raw engine output preserved
    rather than silently returning wrong numbers.

    qc_method is 'hf' or 'dft' (only for single_point/geometry_optimization/
    frequency; tddft is always dft). engine picks the backend explicitly
    (pyscf/orca/bagel); if omitted a sensible default is chosen
    automatically (BAGEL for caspt2, PySCF for everything else).
    """
    molecule = state.get("molecule") if state else None
    if not molecule:
        return Command(update={"messages": [ToolMessage(
            content="No molecule is set yet. Call set_molecule first, then call submit_job again.",
            tool_call_id=tool_call_id,
        )]})

    raw_params = _collect_params(
        qc_method, basis, functional, active_electrons, active_orbitals, n_states, weights,
        orbital_indices, coordinate_type, coordinate_atoms, scan_range, n_points, ms_caspt2,
        shift, frozen_core, df_basis, max_steps, temperature_K,
    )
    spec, preview, error = _build_spec_or_error(job_type, molecule, engine, raw_params)
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
    # the primary gate.
    input_text = decision.get("input_text")
    if input_text is not None:
        errors = validate_input(approved_spec.engine, input_text)
        if errors:
            content = (
                f"The edited {approved_spec.engine} input has problems and was NOT run: "
                f"{'; '.join(errors)}. Ask the user to fix these or revert to the generated input."
            )
            return Command(update={"messages": [ToolMessage(content=content, tool_call_id=tool_call_id)]})
        approved_spec.params["_raw_input"] = input_text

    job_id = get_job_manager().submit(approved_spec)

    edit_note = " (user-edited input)" if input_text is not None else ""
    content = (
        f"Job submitted (user-approved{edit_note}): id={job_id}, type={job_type}, engine={approved_spec.engine}, "
        f"params={approved_spec.params}. It is running in the background; tell the user it has started "
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
    mgr = get_job_manager()
    active = state.get("active_job_ids", []) if state else []
    target = job_id or (active[-1] if active else None)
    if not target:
        return "No jobs have been submitted yet in this conversation."

    status = mgr.status(target)
    if status["status"] in ("pending", "running"):
        return f"Job {target} is still {status['status']} ({status.get('message', '')})."

    result = mgr.result(target)
    if result is None:
        return f"Job {target} finished but no result was recorded; status={status}."
    if result["status"] == "failed":
        return f"Job {target} FAILED. Error detail (share the relevant part with the user, don't dump all of it):\n{result['error'][:2000]}"

    return f"Job {target} completed. Results:\n{result['summary']}"


ALL_TOOLS = [set_molecule, generate_job_input, submit_job, check_job_status, search_knowledge_base]
