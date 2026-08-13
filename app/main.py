"""Streamlit entry point: `streamlit run app/main.py`."""
from __future__ import annotations

import uuid

import streamlit as st
from langchain_core.messages import HumanMessage

from app.agent.graph import (
    invalidate_graph_cache, invoke_turn, pending_approval, read_state, resume_turn, update_molecule_state,
)
from app.config import LLM_MODEL
from app.ui.components import (
    render_approval_panel, render_chat_history, render_dynamic_tool_artifacts_panel,
    render_dynamic_tools_panel, render_jobs_panel, render_kb_panel, render_molecule_builder,
    render_molecule_panel, render_mo_viewer_panel, render_tool_approval_panel, render_uvvis_panel,
    render_vibration_viewer_panel,
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


def resolve_job_approval(decision: dict, pending: dict) -> bool:
    """Resumes a submit_job call paused on interrupt() with the user's
    decision (as returned by render_approval_panel: {"approved": bool,
    "input_text": str | None}). On approval, round-trips the exact spec
    dict shown in the approval card back to submit_job rather than letting
    it rebuild one, and forwards input_text (the possibly hand-edited
    ORCA/BAGEL input, already validated by render_approval_panel) so
    submit_job runs exactly what was shown -- see submit_job's docstring/
    comments for why that matters. Returns True on success."""
    if decision["approved"]:
        resume_value = {"approved": True, "spec": pending["spec"], "input_text": decision["input_text"]}
    else:
        resume_value = {"approved": False}
    try:
        resume_turn(resume_value, config)
        st.session_state.pop(f"_approval_input_{pending['spec']['job_id']}", None)
        return True
    except Exception as e:
        st.error(f"Could not process that decision ({e}). Please try again.")
        return False


@st.dialog("Molecule Builder", width="large")
def _molecule_builder_dialog():
    """Thin wrapper around render_molecule_builder -- Streamlit dialogs
    re-invoke the *decorated* function itself on every rerun while open, so
    the actual rendering has to live in the function this decorator wraps,
    not in something it calls out to and returns from. Handles the decision
    render_molecule_builder returns (attach vs. preview) here, since that's
    where graph/state access (update_molecule_state, needing `config`)
    belongs -- render_molecule_builder itself only builds the Molecule and
    reports the user's choice, same division of labor as
    resolve_job_approval/resolve_tool_approval below for the job- and
    tool-approval cards.

    IMPORTANT: st.rerun() does NOT keep a dialog open by itself -- a dialog
    only reappears on a rerun if your script calls the decorated function
    again on that run (confirmed empirically: the Clean Up round trip,
    which calls st.rerun() from inside render_molecule_builder to push the
    cleaned-up geometry back into the component, closed the dialog outright
    until the open/closed state was tracked explicitly below). The
    "_builder_dialog_open" flag is what makes the call below happen again
    on every subsequent rerun, not just the one where the opening button
    was clicked.
    """
    decision = render_molecule_builder(current_state().get("molecule"))
    if decision is not None:
        m = decision["molecule"]
        update_molecule_state(m.to_dict(), config)
        if decision["action"] == "attach_to_chat":
            st.session_state["_pending_attachment"] = {"name": m.name, "xyz": m.to_xyz_block()}
        st.session_state["_builder_dialog_open"] = False
        st.rerun()


def resolve_tool_approval(decision: dict, pending: dict) -> bool:
    """Resumes a create_tool call paused on interrupt() with the user's
    decision (as returned by render_tool_approval_panel: {"approved":
    bool, "code": str | None}). Deliberately calls invalidate_graph_cache()
    here -- on the main script thread, strictly after resume_turn()
    returns and releases the graph lock -- rather than inside create_tool
    itself, which runs on a ToolNode worker thread and would deadlock
    trying to acquire that same lock (see the long comment on _graph_lock
    in graph.py). Returns True on success."""
    resume_value = {"approved": True, "code": decision["code"]} if decision["approved"] else {"approved": False}
    try:
        resume_turn(resume_value, config)
        st.session_state.pop(f"_tool_code_{pending['tool_name']}", None)
        if decision["approved"]:
            invalidate_graph_cache()
        return True
    except Exception as e:
        st.error(f"Could not process that decision ({e}). Please try again.")
        return False


with st.sidebar:
    st.markdown(f"**Model:** `{LLM_MODEL}`  \n**Session:** `{st.session_state.thread_id[:8]}`")
    if st.button("New conversation"):
        st.session_state.thread_id = uuid.uuid4().hex
        st.session_state.pop("_seen_terminal_jobs", None)
        st.rerun()
    st.divider()
    render_kb_panel()
    st.divider()
    render_dynamic_tools_panel()

state = current_state()

chat_col, side_col = st.columns([2, 1])

pending = pending_approval(config)

with chat_col:
    st.title("Computational Chemistry Agent")
    st.caption("Name a molecule (or give a SMILES) to visualize it, or ask for a calculation directly.")
    render_chat_history(state.get("messages", []))

    if pending and pending.get("kind") == "tool_approval":
        decision = render_tool_approval_panel(pending)
        if decision is not None:
            if resolve_tool_approval(decision, pending):
                st.rerun()
    elif pending:
        decision = render_approval_panel(pending)
        if decision is not None:
            if resolve_job_approval(decision, pending):
                st.rerun()

    pending_attachment = st.session_state.get("_pending_attachment")
    if pending_attachment:
        col_a, col_b = st.columns([6, 1])
        col_a.caption(
            f"📎 **{pending_attachment['name']}** attached -- its XYZ structure will be "
            f"included with your next message."
        )
        if col_b.button("✕", key="_clear_attachment"):
            st.session_state.pop("_pending_attachment", None)
            st.rerun()

    user_text = st.chat_input(
        "e.g. 'water' or 'run a CASSCF(4,4)/cc-pVDZ on formaldehyde'",
        disabled=bool(pending),
    )
    if user_text:
        full_text = user_text
        if pending_attachment:
            # Prepended (not silently substituted) so the attachment is
            # visible in the chat history exactly like anything else the
            # agent acts on -- same transparency principle as the job/tool
            # approval cards showing the exact text that will run.
            full_text = (
                f"{user_text}\n\n(attached molecule: {pending_attachment['name']})\n"
                f"```\n{pending_attachment['xyz']}\n```"
            )
            st.session_state.pop("_pending_attachment", None)
        with st.spinner("Thinking..."):
            ok = run_turn(full_text)
        if ok:
            st.rerun()

with side_col:
    if st.button("🧩 Build a molecule"):
        st.session_state["_builder_dialog_open"] = True
        st.rerun()
    if st.session_state.get("_builder_dialog_open"):
        _molecule_builder_dialog()
    render_molecule_panel(state.get("molecule"))
    st.divider()


    @st.fragment(run_every="4s")
    def _jobs_fragment():
        s = current_state()
        # While a job-approval is pending, the graph is paused mid-tool-call
        # (not at the agent node), so a "job finished" notice sent now would
        # just be silently swallowed -- see render_jobs_panel's docstring.
        # mark_seen=False leaves those ids unmarked so the next poll tick
        # after the approval resolves picks them up and notifies normally.
        is_pending = pending_approval(config) is not None
        newly_done = render_jobs_panel(s.get("active_job_ids", []), mark_seen=not is_pending)
        if newly_done and not is_pending:
            ids = ", ".join(newly_done)
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
    render_uvvis_panel(state.get("active_job_ids", []))
    render_dynamic_tool_artifacts_panel(state.get("dynamic_tool_artifacts", []))
