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

from typing import Annotated, Optional

from langchain_core.messages import ToolMessage
from langchain_core.tools import InjectedToolCallId, tool
from langgraph.prebuilt import InjectedState
from langgraph.types import Command, interrupt

from app.agent.dynamic_tools import (
    RESERVED_TOOL_NAMES, is_valid_tool_name, load_dynamic_tools, save_tool, tool_exists, validate_tool_code,
)
from app.agent.scholar_search import search_academic_literature
from app.agent.state import AgentState
from app.agent.web_search import web_search
from app.chemistry.jobs.base import (
    JobResult, JobSpec, MAX_AUTO_RETRIES, get_job_manager, read_spec, write_result,
)
from app.chemistry.jobs.preview import build_input_preview
from app.chemistry.jobs.registry import (
    METHODS, PARAM_HELP, default_engine, missing_required_params,
)
from app.chemistry.jobs.summarize import job_context_summary
from app.chemistry.jobs.validate import validate_input
from app.chemistry.molecule import resolve_molecule
from app.chemistry.spectrum import render_uvvis_plot
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


def _build_spec_or_error(job_type: str, molecule: dict, engine: Optional[str], raw_params: dict):
    """Shared by generate_job_input and submit_job: validates required
    params, resolves the engine, builds the JobSpec, renders its input
    preview, and looks up manual/reference-doc context for it. Returns
    (spec, preview_text, kb_context, error_str) -- exactly one of
    (spec, preview_text, kb_context) / error_str is populated.
    """
    if job_type not in METHODS:
        return None, None, None, f"Unknown job_type '{job_type}'. Valid options: {', '.join(METHODS)}"

    params = {k: v for k, v in raw_params.items() if v is not None}

    missing = missing_required_params(job_type, params)
    if missing:
        needs = "; ".join(f"{p} ({PARAM_HELP.get(p, 'no description')})" for p in missing)
        return None, None, None, (
            f"Cannot prepare this '{job_type}' job yet -- still missing: {needs}. "
            f"Ask the user for these specifically; do not assume default values for them."
        )

    try:
        resolved_engine = default_engine(job_type, engine, params)
    except ValueError as e:
        return None, None, None, str(e)

    spec = JobSpec(method=job_type, engine=resolved_engine, molecule=molecule, params=params)
    try:
        preview = build_input_preview(spec)
    except Exception as e:
        return None, None, None, f"Could not build the input for this job: {e}"

    kb_context = _kb_context_for_job(spec.engine, job_type, params)
    return spec, preview, kb_context, None


def _collect_params(
    qc_method, basis, functional, active_electrons, active_orbitals, n_states, weights,
    orbital_indices, coordinate_type, coordinate_atoms, scan_range, n_points, ms_caspt2,
    shift, frozen_core, df_basis, max_steps, temperature_K, use_tda, want_oscillator_strengths,
) -> dict:
    params = {
        "method": qc_method, "basis": basis, "functional": functional,
        "active_electrons": active_electrons, "active_orbitals": active_orbitals,
        "n_states": n_states, "weights": weights, "orbital_indices": orbital_indices,
        "scan_range": scan_range, "n_points": n_points, "ms_caspt2": ms_caspt2,
        "shift": shift, "frozen_core": frozen_core, "df_basis": df_basis,
        "max_steps": max_steps, "temperature_K": temperature_K, "use_tda": use_tda,
        "want_oscillator_strengths": want_oscillator_strengths,
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
    use_tda: Optional[bool] = None,
    want_oscillator_strengths: Optional[bool] = None,
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
        shift, frozen_core, df_basis, max_steps, temperature_K, use_tda, want_oscillator_strengths,
    )
    spec, preview, kb_context, error = _build_spec_or_error(job_type, molecule, engine, raw_params)
    if error:
        return Command(update={**extra_state_update, "messages": [ToolMessage(content=error, tool_call_id=tool_call_id)]})

    kb_block = (
        f"\n\nRelevant manual/reference excerpts for this engine and job type -- check your "
        f"parameters (especially basis set / keyword names) against these before showing the "
        f"input, and correct them if they conflict:\n{kb_context}"
    ) if kb_context else ""
    content = (
        f"Generated {spec.engine} input for a '{job_type}' job (NOT run). Show this to the user "
        f"verbatim in a code block.\n\n{preview}{kb_block}"
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
    retry_of_job_id: Optional[str] = None,
    state: Annotated[AgentState, InjectedState] = None,
    tool_call_id: Annotated[str, InjectedToolCallId] = None,
) -> Command:
    """Run a computational chemistry job on the active molecule in the
    background. Call this when the user asks you to run/submit/perform a
    calculation (not just generate its input -- use generate_job_input for
    that). `job_type` must be one of: single_point, geometry_optimization,
    frequency, casscf, caspt2, tddft, eom_ccsd, mo_visualization, pes_scan.

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

    raw_params = _collect_params(
        qc_method, basis, functional, active_electrons, active_orbitals, n_states, weights,
        orbital_indices, coordinate_type, coordinate_atoms, scan_range, n_points, ms_caspt2,
        shift, frozen_core, df_basis, max_steps, temperature_K, use_tda, want_oscillator_strengths,
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

        prev_retry_count = prev_params.get("_retry_count", 0)
        raw_params["_retry_count"] = prev_retry_count + 1
        raw_params["_retried_from"] = retry_of_job_id
        retry_note = f"Retry attempt {prev_retry_count + 1} of {MAX_AUTO_RETRIES} (previous attempt: job {retry_of_job_id})."

    spec, preview, kb_context, error = _build_spec_or_error(job_type, molecule, engine, raw_params)
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
        "kb_context": kb_context,
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

    result["artifacts"]["uvvis_spectrum"] = out_path
    write_result(JobResult(
        job_id=result["job_id"], status=result["status"],
        summary=result["summary"], artifacts=result["artifacts"], error=result.get("error"),
    ))

    return f"Generated a UV/Vis spectrum plot for job {target}; it is now shown to the user."


@tool
def create_tool(
    tool_name: str,
    description: str,
    code: str,
    param_description: str,
    overwrite: Optional[bool] = None,
    tool_call_id: Annotated[str, InjectedToolCallId] = None,
) -> Command:
    """Create a new tool for a task none of the existing tools cover --
    ONLY for a new output parser, a custom plot type not covered by
    plot_excited_state_spectrum, or another QM-calculation-related helper.
    Do NOT use this as a substitute for set_molecule/generate_job_input/
    submit_job/check_job_status/plot_excited_state_spectrum/
    search_knowledge_base/search_academic_literature/web_search -- always
    prefer an existing tool when one covers the request, and don't create
    near-duplicates of one that already exists (check what's available
    first). While writing a new tool's code, do not use
    search_knowledge_base or search_academic_literature -- those cover
    chemistry manuals/papers, not Python/library/file-format reference;
    use web_search for that instead.

    `code` must be a single Python module defining exactly one top-level
    function, `def run(params: dict) -> dict:` -- no other executable
    code at module level (imports, constants, and helper function/class
    definitions are fine; nothing that runs immediately on import). The
    returned dict should include a "text" key summarizing the result for
    the user, and optionally an "image_path" key (an absolute path it
    wrote a plot/figure to) if it produced one. Only these modules may be
    imported: re, json, math, statistics, itertools, collections,
    functools, dataclasses, typing, datetime, numpy, scipy, matplotlib,
    pyscf, rdkit, and os.path (not the rest of os) -- no subprocess,
    socket, shutil, sys, requests/urllib, or pickle, and no eval/exec/
    compile/__import__/globals/locals. This runs in a fresh subprocess
    each call (like a QC job worker) with the same filesystem access as
    the rest of this app, not a hard security sandbox -- construct any
    output path yourself (e.g. from params); there is no per-call working
    directory provided.

    This PAUSES (like submit_job) to show the user the exact code and get
    their explicit approval -- and they may edit it -- before it's ever
    registered or run; you do not need to ask for confirmation yourself
    first. If the code fails validation (wrong structure, disallowed
    import/call), you'll get a specific list of problems back before it's
    ever shown for approval -- fix and retry. If the user rejects it, the
    tool is not created; ask what they'd like to change. Once approved,
    the tool is usable immediately in this conversation and persists for
    future ones -- call it like any other tool, passing whatever
    `params` dict its description says it expects.
    """
    if not is_valid_tool_name(tool_name):
        return Command(update={"messages": [ToolMessage(
            content=f"'{tool_name}' is not a valid tool name (must be a valid Python identifier, not starting with '_').",
            tool_call_id=tool_call_id,
        )]})
    if tool_name in RESERVED_TOOL_NAMES:
        return Command(update={"messages": [ToolMessage(
            content=f"'{tool_name}' is a built-in tool name and can't be overridden. Pick a different name.",
            tool_call_id=tool_call_id,
        )]})
    if tool_exists(tool_name) and not overwrite:
        return Command(update={"messages": [ToolMessage(
            content=(f"A dynamic tool named '{tool_name}' already exists. Pick a different name, "
                     f"or call again with overwrite=True to replace it."),
            tool_call_id=tool_call_id,
        )]})

    errors = validate_tool_code(code)
    if errors:
        content = f"This code has problems and can't be proposed for approval: {'; '.join(errors)}"
        return Command(update={"messages": [ToolMessage(content=content, tool_call_id=tool_call_id)]})

    decision = interrupt({
        "kind": "tool_approval",
        "tool_name": tool_name,
        "description": description,
        "param_description": param_description,
        "code": code,
    })

    if not isinstance(decision, dict) or not decision.get("approved"):
        content = f"The user did NOT approve creating the '{tool_name}' tool -- it was not registered."
        return Command(update={"messages": [ToolMessage(content=content, tool_call_id=tool_call_id)]})

    final_code = decision.get("code", code)
    final_errors = validate_tool_code(final_code)
    if final_errors:
        content = f"The approved code has problems and was NOT registered: {'; '.join(final_errors)}"
        return Command(update={"messages": [ToolMessage(content=content, tool_call_id=tool_call_id)]})

    save_tool(tool_name, description, final_code, param_description)

    # Deliberately does NOT call invalidate_graph_cache() here -- this tool
    # body runs on a ToolNode worker thread (not the thread that called
    # invoke_turn/resume_turn), and that call acquires app.agent.graph's
    # _graph_lock, which the calling thread is holding for the *entire*
    # duration of this invoke. Calling it from here deadlocks for real
    # (confirmed empirically, not just reasoned about) -- see the long
    # comment on _graph_lock in graph.py. server/routes/tools.py's tool-
    # approval endpoint calls it instead, from the request-handling
    # thread, strictly after resume_turn() returns.
    content = (
        f"Tool '{tool_name}' created and registered (user-approved). It is now available to call, "
        f"in this conversation and future ones."
    )
    return Command(update={"messages": [ToolMessage(content=content, tool_call_id=tool_call_id)]})


STATIC_TOOLS = [
    set_molecule, generate_job_input, submit_job, check_job_status,
    plot_excited_state_spectrum, search_knowledge_base, search_academic_literature,
    web_search, create_tool,
]


def get_all_tools() -> list:
    """Re-scans data/dynamic_tools/ on every call (not cached) so a tool
    approved via create_tool -- in this session or a prior one -- is
    picked up on the very next graph rebuild / LLM bind_tools call."""
    return [*STATIC_TOOLS, *load_dynamic_tools()]
