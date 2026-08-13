"""Streamlit rendering helpers: chat history, molecule viewer, job status
panel, and knowledge-base management panel.
"""
from __future__ import annotations

from pathlib import Path

import streamlit as st
import streamlit.components.v1 as components
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from app.agent.dynamic_tools import delete_tool, list_tools, validate_tool_code
from app.chemistry.jobs.base import get_job_manager
from app.chemistry.jobs.validate import validate_input
from app.chemistry.molecule import Molecule
from app.chemistry.viz import render_cube_html, render_vibration_html
from app.config import UPLOADS_DIR
from app.rag.ingest import ingest_file
from app.rag.store import delete_source, list_sources
from app.ui.mol_component import mol_component

# ORCA/BAGEL inputs are genuine text/JSON formats the respective engine
# parses itself, so hand-editing them changes nothing about the trust
# model -- the engine binary was always going to interpret arbitrary text
# in its own grammar. PySCF has no such input file (the preview is a
# synthetic driver script standing in for direct API calls executed in a
# different way entirely), so it's read-only here; see CLAUDE.md.
_EDITABLE_ENGINES = {"orca", "bagel"}


def render_chat_history(messages: list) -> None:
    for msg in messages:
        if isinstance(msg, HumanMessage):
            with st.chat_message("user"):
                st.markdown(msg.content)
        elif isinstance(msg, AIMessage) and msg.content:
            with st.chat_message("assistant"):
                st.markdown(msg.content)
        elif isinstance(msg, ToolMessage):
            with st.expander(f"tool result: {msg.name}", expanded=False):
                st.text(str(msg.content)[:2000])


def render_molecule_panel(molecule_dict: dict | None) -> None:
    st.subheader("Molecule")
    if not molecule_dict:
        st.caption("No molecule set yet -- mention one by name or SMILES in the chat.")
        return
    m = Molecule.from_dict(molecule_dict)
    st.caption(f"{m.name}  ·  {m.smiles}  ·  charge {m.charge}, mult {m.multiplicity}  ·  {len(m.symbols)} atoms")
    # Keyed on cache_key() so a genuinely different molecule gets a fresh
    # component instance (fresh camera/zoom), while reruns showing the same
    # molecule (e.g. an unrelated chat turn) reuse the mounted iframe --
    # the component's own args-diffing (see frontend/index.html) makes that
    # safe against click state getting reset by an unrelated rerun.
    mol_component(
        {"symbols": m.symbols, "coords": m.coords}, height=320,
        key=f"_mol_viewer_{m.cache_key()}",
    )
    st.caption(
        "Atom numbers are 1-based, matching the coordinate references used for scans and "
        "Z-matrices below. Click 1/2/3/4 atoms in the 3D view to see element / bond length / "
        "angle / dihedral; click empty space to reset the selection."
    )

    show_coords = st.toggle("Show coordinates", key="_show_coords")
    if show_coords:
        fmt = st.radio("Format", ["XYZ (xmol)", "Z-matrix (internal)"], horizontal=True, key="_coord_format")
        text = m.to_xyz_block() if fmt.startswith("XYZ") else m.to_zmatrix_block()
        st.code(text, language="text")


def render_approval_panel(pending: dict) -> dict | None:
    """Renders the job-approval card for a submit_job call currently paused
    on interrupt(). Returns {"approved": bool, "input_text": str | None} if
    the user just took an action this render, else None -- the caller
    (main.py) is responsible for actually resuming the graph with that
    decision. `input_text` is the (possibly hand-edited) engine input for
    ORCA/BAGEL, carried back through the resume value so submit_job runs
    exactly what was validated here rather than trusting anything rebuilt
    after resume -- see submit_job's comments for why that distinction
    matters. Validation runs here, before ever calling resume_turn, so a
    typo gets fixed in place with no LLM round-trip; submit_job re-checks
    server-side as a backstop, not the primary gate.

    The text_area is keyed on the pending job's job_id specifically (not a
    fixed key) -- Streamlit widget state persists across reruns by key, so
    a fixed key would leak one job's edits into the next unrelated
    approval card shown later in the same session.
    """
    engine = pending["engine"]
    job_id = pending["spec"]["job_id"]
    editable = engine in _EDITABLE_ENGINES
    text_key = f"_approval_input_{job_id}"

    with st.container(border=True):
        st.markdown(
            f"**Approval needed** -- run a `{pending['job_type']}` job via **{engine}** "
            f"on *{pending.get('molecule_name', 'the active molecule')}*?"
        )
        st.caption(f"Parameters: {pending['params']}")

        if editable:
            if text_key not in st.session_state:
                st.session_state[text_key] = pending["input_preview"]
            current_text = st.text_area(
                "Input (editable)", key=text_key, height=280, label_visibility="collapsed",
            )
            edited = current_text != pending["input_preview"]
            if edited:
                st.caption("✏️ Edited from the generated input.")
        else:
            current_text = pending["input_preview"]
            edited = False
            st.code(current_text, language="text")
            st.caption("PySCF has no editable input file -- it's called directly as a Python API, "
                       "not run from a text input. Use ORCA if you need to hand-edit this job's input.")

        if edited:
            col1, col2, col3 = st.columns(3)
            run_clicked = col1.button("▶️ Run edited", use_container_width=True, key=f"_run_edited_{job_id}")
            reject = col2.button("❌ Reject", use_container_width=True, key=f"_reject_{job_id}")
            if col3.button("↺ Reset to generated", use_container_width=True, key=f"_reset_{job_id}"):
                st.session_state[text_key] = pending["input_preview"]
                st.rerun()
            approve = False
        else:
            col1, col2 = st.columns(2)
            approve = col1.button("✅ Approve & run", use_container_width=True, key=f"_approve_{job_id}")
            reject = col2.button("❌ Reject", use_container_width=True, key=f"_reject_{job_id}")
            run_clicked = False

    if reject:
        return {"approved": False, "input_text": None}

    if approve or run_clicked:
        if editable:
            errors = validate_input(engine, current_text)
            if errors:
                for e in errors:
                    st.error(e)
                return None
            return {"approved": True, "input_text": current_text}
        return {"approved": True, "input_text": None}

    return None


def render_tool_approval_panel(pending: dict) -> dict | None:
    """Renders the review card for a create_tool call currently paused on
    interrupt() -- same shape as render_approval_panel (editable text,
    validate-before-resume, Reset to generated) but for Python source
    instead of an engine input file. Returns {"approved": bool, "code":
    str} on an action this render, else None. See create_tool's docstring
    in tools.py for what the code is allowed to do."""
    tool_name = pending["tool_name"]
    text_key = f"_tool_code_{tool_name}"

    with st.container(border=True):
        st.markdown(f"**New tool proposed: `{tool_name}`**")
        st.caption(pending.get("description", ""))
        if pending.get("param_description"):
            st.caption(f"Expected params: {pending['param_description']}")

        if text_key not in st.session_state:
            st.session_state[text_key] = pending["code"]
        current_code = st.text_area(
            "Code (editable)", key=text_key, height=280, label_visibility="collapsed",
        )
        edited = current_code != pending["code"]
        if edited:
            st.caption("✏️ Edited from the generated code.")
        st.caption(
            "Runs in its own subprocess with the same filesystem access as the rest of this app -- "
            "review it like you would any code you're about to run locally, not just skim it."
        )

        if edited:
            col1, col2, col3 = st.columns(3)
            run_clicked = col1.button("✅ Approve & register", use_container_width=True, key=f"_approve_edited_tool_{tool_name}")
            reject = col2.button("❌ Reject", use_container_width=True, key=f"_reject_tool_{tool_name}")
            if col3.button("↺ Reset to generated", use_container_width=True, key=f"_reset_tool_{tool_name}"):
                st.session_state[text_key] = pending["code"]
                st.rerun()
            approve = False
        else:
            col1, col2 = st.columns(2)
            approve = col1.button("✅ Approve & register", use_container_width=True, key=f"_approve_tool_{tool_name}")
            reject = col2.button("❌ Reject", use_container_width=True, key=f"_reject_tool_{tool_name}")
            run_clicked = False

    if reject:
        return {"approved": False, "code": None}

    if approve or run_clicked:
        errors = validate_tool_code(current_code)
        if errors:
            for e in errors:
                st.error(e)
            return None
        return {"approved": True, "code": current_code}

    return None


def render_jobs_panel(active_job_ids: list[str], mark_seen: bool = True) -> set[str]:
    """Renders job statuses; returns the set of job_ids that are newly
    completed/failed since last render (caller decides whether to notify
    the agent about them).

    `mark_seen=False` renders normally but leaves newly-finished ids out of
    `_seen_terminal_jobs` -- used while a job-approval is pending, since
    sending the agent a "job finished" notice then would just get silently
    swallowed (the graph is paused mid-tool-call, not at the agent node,
    so a new HumanMessage can't be responded to until the pending approval
    resolves). Leaving them unmarked means the very next poll tick after
    the approval resolves picks them up and notifies as normal, instead of
    losing the notification permanently.

    Intentionally does NOT render the MO cube viewer -- this panel lives
    inside a `st.fragment(run_every=...)` for status polling, and the cube
    viewer is an expensive (multi-MB) iframe that would rebuild and reload
    from scratch on every poll tick, discarding any in-browser rotation/zoom
    the user was mid-interaction with. Use `render_mo_viewer_panel` from the
    main (non-polling) script body instead.
    """
    st.subheader("Jobs")
    if not active_job_ids:
        st.caption("No jobs submitted yet in this conversation.")
        return set()

    mgr = get_job_manager()
    newly_done = set()
    seen = st.session_state.setdefault("_seen_terminal_jobs", set())

    for job_id in reversed(active_job_ids):
        status = mgr.status(job_id)
        icon = {"pending": "⏳", "running": "⚙️", "completed": "✅", "failed": "❌"}.get(status["status"], "?")
        with st.container(border=True):
            st.markdown(f"**{icon} `{job_id}`** — {status['status']}")
            if status["status"] in ("completed", "failed"):
                if job_id not in seen:
                    newly_done.add(job_id)
                    if mark_seen:
                        seen.add(job_id)
                result = mgr.result(job_id)
                if result:
                    if result["status"] == "completed":
                        st.json(result["summary"], expanded=False)
                    else:
                        st.error(str(result.get("error", ""))[:1500])
            else:
                st.caption(status.get("message", ""))
    return newly_done


def render_mo_viewer_panel(active_job_ids: list[str], molecule_dict: dict | None) -> None:
    """Renders an orbital picker + isosurface viewer for the most recent
    completed mo_visualization job, if any. Called from the main script
    body (not a polling fragment) so the viewer only rebuilds when the
    user actually does something, not every few seconds."""
    if not active_job_ids or not molecule_dict:
        return
    mgr = get_job_manager()
    for job_id in reversed(active_job_ids):
        result = mgr.result(job_id)
        if not result or result["status"] != "completed":
            continue
        cubes = result.get("artifacts", {}).get("cubes")
        if not cubes:
            continue

        st.divider()
        st.subheader("Molecular orbitals")
        m = Molecule.from_dict(molecule_dict)
        labels = list(cubes.keys())
        choice = st.selectbox("Orbital", labels, key=f"mo_choice_{job_id}")
        cube_path = cubes[choice]
        if not Path(cube_path).exists():
            st.caption(f"Cube file for {choice} is no longer on disk.")
            return
        html = render_cube_html(m.to_xyz_block(), cube_path, width=380, height=320)
        components.html(html, height=340)
        return  # only show the most recent MO job's cubes


def render_vibration_viewer_panel(active_job_ids: list[str], molecule_dict: dict | None) -> None:
    """Renders a mode picker + displacement-arrow viewer for the most recent
    completed frequency job, if any. Kept outside the polling fragment for
    the same reason as render_mo_viewer_panel."""
    if not active_job_ids or not molecule_dict:
        return
    mgr = get_job_manager()
    for job_id in reversed(active_job_ids):
        result = mgr.result(job_id)
        if not result or result["status"] != "completed":
            continue
        modes = result["summary"].get("normal_modes")
        freqs = result["summary"].get("frequencies_cm-1")
        if not modes:
            continue

        st.divider()
        st.subheader("Vibrational modes")
        m = Molecule.from_dict(molecule_dict)
        labels = [f"{i + 1}: {f:.1f} cm⁻¹" for i, f in enumerate(freqs)] if freqs else [str(i) for i in range(len(modes))]
        idx = st.selectbox("Mode", range(len(modes)), format_func=lambda i: labels[i], key=f"vib_choice_{job_id}")
        html = render_vibration_html(m, modes[idx], width=380, height=320)
        components.html(html, height=340)
        return  # only show the most recent frequency job's modes


def render_uvvis_panel(active_job_ids: list[str]) -> None:
    """Renders the most recently plotted UV/Vis spectrum, if any. The
    image is a job artifact written by the plot_excited_state_spectrum
    tool (see tools.py) after the job already completed, so this just
    displays whatever's on disk -- same non-polling-fragment placement as
    the MO/vibration viewers, since re-reading and re-displaying a static
    PNG on every 4s poll tick would be wasted work, not a correctness
    issue, but there's no reason to pay it."""
    if not active_job_ids:
        return
    mgr = get_job_manager()
    for job_id in reversed(active_job_ids):
        result = mgr.result(job_id)
        if not result or result["status"] != "completed":
            continue
        path = result.get("artifacts", {}).get("uvvis_spectrum")
        if not path or not Path(path).exists():
            continue

        st.divider()
        st.subheader("UV/Vis absorption spectrum")
        st.image(path, use_container_width=True)
        return  # only show the most recent plotted spectrum


def render_dynamic_tool_artifacts_panel(dynamic_tool_artifacts: list[str]) -> None:
    """Renders the most recent image a dynamic tool (see dynamic_tools.py)
    reported via its result dict's "image_path" key. Same non-polling-
    fragment placement as render_uvvis_panel/render_mo_viewer_panel."""
    if not dynamic_tool_artifacts:
        return
    for path in reversed(dynamic_tool_artifacts):
        if not Path(path).exists():
            continue
        st.divider()
        st.subheader("Dynamic tool output")
        st.image(path, use_container_width=True)
        return  # only show the most recent one


def render_kb_panel() -> None:
    st.subheader("Knowledge base")
    with st.form("kb_upload_form", clear_on_submit=True):
        uploaded = st.file_uploader("Add a manual or paper (PDF or text)", type=["pdf", "txt", "md"])
        doc_type = st.radio("Document type", ["manual", "paper"], horizontal=True)
        submitted = st.form_submit_button("Add to knowledge base")
    if submitted and uploaded is not None:
        dest = UPLOADS_DIR / uploaded.name
        dest.write_bytes(uploaded.getvalue())
        try:
            n = ingest_file(dest, doc_type)
            st.success(f"Added {uploaded.name} ({n} chunks)")
        except Exception as e:
            st.error(f"Failed to ingest {uploaded.name}: {e}")

    sources = list_sources()
    if not sources:
        st.caption("Knowledge base is empty.")
        return
    for s in sources:
        col1, col2 = st.columns([4, 1])
        col1.caption(f"{s['source']} ({s['doc_type']}, {s['n_chunks']} chunks)")
        if col2.button("Remove", key=f"del_{s['source']}"):
            delete_source(s["source"])
            st.rerun()


def render_dynamic_tools_panel() -> None:
    """Lists agent-created tools (see create_tool in tools.py), each
    approved by a human before it was ever registered, with a Remove
    button -- same list+remove shape as render_kb_panel. Deleting here
    runs on the main script thread (a plain button click, not inside a
    tool call), so it's safe to invalidate the graph cache directly."""
    st.subheader("Agent-created tools")
    tools = list_tools()
    if not tools:
        st.caption("No dynamic tools created yet.")
        return
    for t in tools:
        col1, col2 = st.columns([4, 1])
        col1.caption(f"**{t['name']}** -- {t['description']}")
        if col2.button("Remove", key=f"del_tool_{t['name']}"):
            delete_tool(t["name"])
            from app.agent.graph import invalidate_graph_cache
            invalidate_graph_cache()
            st.rerun()
