"""Streamlit rendering helpers: chat history, molecule viewer, job status
panel, and knowledge-base management panel.
"""
from __future__ import annotations

from pathlib import Path

import streamlit as st
import streamlit.components.v1 as components
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from app.chemistry.jobs.base import get_job_manager
from app.chemistry.molecule import Molecule
from app.chemistry.viz import render_cube_html, render_molecule_html, render_vibration_html
from app.config import UPLOADS_DIR
from app.rag.ingest import ingest_file
from app.rag.store import delete_source, list_sources


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
    html = render_molecule_html(m, width=380, height=320)
    components.html(html, height=340)


def render_jobs_panel(active_job_ids: list[str]) -> set[str]:
    """Renders job statuses; returns the set of job_ids that are newly
    completed/failed since last render (caller decides whether to notify
    the agent about them).

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
