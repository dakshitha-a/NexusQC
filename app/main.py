"""Streamlit entry point: `streamlit run app/main.py`."""
from __future__ import annotations

import uuid

import streamlit as st
from langchain_core.messages import HumanMessage

from app.agent.graph import invoke_turn, read_state
from app.config import LLM_MODEL
from app.ui.components import (
    render_chat_history, render_jobs_panel, render_kb_panel, render_molecule_panel,
    render_mo_viewer_panel, render_vibration_viewer_panel,
)

st.set_page_config(page_title="Computational Chemistry Agent", layout="wide")

if "thread_id" not in st.session_state:
    st.session_state.thread_id = uuid.uuid4().hex

config = {"configurable": {"thread_id": st.session_state.thread_id}}


def current_state() -> dict:
    return read_state(config)


def run_turn(user_text: str) -> bool:
    """Returns True on success. `_build_llm`'s timeout/max_retries bound how
    long a single LLM call can take, turning a pathologically slow response
    into an exception here rather than an indefinite hang, so the UI can
    surface a retryable error instead of a frozen spinner."""
    try:
        # Only "messages" belongs in the per-turn input. "molecule" and
        # "active_job_ids" have no custom reducer, so LangGraph overwrites
        # (not merges) them with whatever is in the input dict on every
        # invoke -- including them here with placeholder values would
        # silently wipe the persisted molecule/job state on every turn.
        invoke_turn({"messages": [HumanMessage(content=user_text)]}, config)
        return True
    except Exception as e:
        st.error(f"The model didn't respond in time ({e}). Please try again.")
        return False


with st.sidebar:
    st.markdown(f"**Model:** `{LLM_MODEL}`  \n**Session:** `{st.session_state.thread_id[:8]}`")
    if st.button("New conversation"):
        st.session_state.thread_id = uuid.uuid4().hex
        st.session_state.pop("_seen_terminal_jobs", None)
        st.rerun()
    st.divider()
    render_kb_panel()

state = current_state()

chat_col, side_col = st.columns([2, 1])

with chat_col:
    st.title("Computational Chemistry Agent")
    st.caption("Name a molecule (or give a SMILES) to visualize it, or ask for a calculation directly.")
    render_chat_history(state.get("messages", []))

    user_text = st.chat_input("e.g. 'water' or 'run a CASSCF(4,4)/cc-pVDZ on formaldehyde'")
    if user_text:
        with st.spinner("Thinking..."):
            ok = run_turn(user_text)
        if ok:
            st.rerun()

with side_col:
    render_molecule_panel(state.get("molecule"))
    st.divider()


    @st.fragment(run_every="4s")
    def _jobs_fragment():
        s = current_state()
        newly_done = render_jobs_panel(s.get("active_job_ids", []))
        if newly_done:
            ids = ", ".join(newly_done)
            # render_jobs_panel already marked these ids as seen, so a failed
            # run_turn here won't retry the notice forever -- the raw result
            # is visible in the jobs panel above either way.
            if run_turn(
                f"(system notice, not from the user) The following job(s) just finished: {ids}. "
                f"Check their status and give the user a concise summary of the results."
            ):
                st.rerun()

    _jobs_fragment()

    # Outside the polling fragment on purpose (see render_mo_viewer_panel's
    # docstring) -- only rebuilds on a real rerun (new message, button
    # click), not every 4s.
    render_mo_viewer_panel(state.get("active_job_ids", []), state.get("molecule"))
    render_vibration_viewer_panel(state.get("active_job_ids", []), state.get("molecule"))
