"""Tools exposed to the LLM. Each tool either mutates graph state via
`Command(update=...)` (molecule/job tracking) or just returns a string the
LLM incorporates into its reply (status/result lookups).

Job submission never blocks: `submit_job` calls `JobManager.submit`, which
hands the work to a background subprocess and returns a job_id
immediately. The agent's job is to gather correct parameters and dispatch;
polling for completion is the Streamlit UI's responsibility, not the
graph's -- a node that awaited `status == completed` would freeze the UI
for the entire calculation.
"""
from __future__ import annotations

from typing import Annotated, Optional

from langchain_core.messages import ToolMessage
from langchain_core.tools import InjectedToolCallId, tool
from langgraph.prebuilt import InjectedState
from langgraph.types import Command

from app.agent.state import AgentState
from app.chemistry.jobs.base import JobSpec, get_job_manager
from app.chemistry.jobs.registry import (
    METHODS, PARAM_HELP, default_engine, missing_required_params,
)
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
def submit_job(
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
    """Submit a computational chemistry job on the active molecule and run
    it in the background. `job_type` must be one of: single_point,
    geometry_optimization, frequency, casscf, caspt2, tddft,
    mo_visualization, pes_scan.

    If the user named a molecule in the SAME message as the job request,
    pass its name/SMILES as `molecule_identifier` here directly rather than
    (or in addition to) calling `set_molecule` separately -- tool calls
    issued together in one turn don't see each other's state updates yet,
    so a separate set_molecule call in the same turn is not guaranteed to
    be visible here. If a molecule was already established in an earlier
    turn, molecule_identifier can be omitted.

    If you are missing information this tool needs (e.g. basis set, active
    space size, which internal coordinate to scan), DO NOT guess -- call
    this tool anyway with what you have; it will tell you exactly which
    parameters are still missing so you can ask the user.

    qc_method is 'hf' or 'dft' (only for single_point/geometry_optimization/
    frequency; tddft is always dft). engine picks the backend explicitly
    (pyscf/orca/bagel); if omitted a sensible default is chosen
    automatically (BAGEL for caspt2, PySCF for everything else).
    """
    if job_type not in METHODS:
        return Command(update={"messages": [ToolMessage(
            content=f"Unknown job_type '{job_type}'. Valid options: {', '.join(METHODS)}", tool_call_id=tool_call_id,
        )]})

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
    params = {k: v for k, v in params.items() if v is not None}

    missing = missing_required_params(job_type, params)
    if missing:
        needs = "; ".join(f"{p} ({PARAM_HELP.get(p, 'no description')})" for p in missing)
        content = (
            f"Cannot submit this '{job_type}' job yet -- still missing: {needs}. "
            f"Ask the user for these specifically; do not assume default values for them."
        )
        return Command(update={**extra_state_update, "messages": [ToolMessage(content=content, tool_call_id=tool_call_id)]})

    try:
        resolved_engine = default_engine(job_type, engine)
    except ValueError as e:
        return Command(update={**extra_state_update, "messages": [ToolMessage(content=str(e), tool_call_id=tool_call_id)]})

    spec = JobSpec(method=job_type, engine=resolved_engine, molecule=molecule, params=params)
    job_id = get_job_manager().submit(spec)

    content = (
        f"Job submitted: id={job_id}, type={job_type}, engine={resolved_engine}, params={params}. "
        f"It is running in the background; tell the user it has started and that you'll report results "
        f"once it finishes (they can also ask you to check on it)."
    )
    # Just the newly submitted id -- active_job_ids' reducer (_append_job_ids
    # in state.py) concatenates it with whatever's already there, including
    # any other submit_job call landing in the same batch. Returning a
    # locally-computed full list here would race with that -- see the
    # reducer's docstring for why.
    return Command(update={
        **extra_state_update, "active_job_ids": [job_id],
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


ALL_TOOLS = [set_molecule, submit_job, check_job_status, search_knowledge_base]
