"""The agent's LangGraph: a standard tool-calling ReAct loop (agent node ->
tools node -> back to agent, until the model stops requesting tools) with
a SQLite checkpointer so per-conversation state (message history, active
molecule, running job ids) survives Streamlit reruns and process restarts.
"""
from __future__ import annotations

import sqlite3
import threading
from typing import Any, Optional

from langchain_core.messages import SystemMessage
from langchain_openai import ChatOpenAI
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.graph import END, START, StateGraph
from langgraph.prebuilt import ToolNode
from langgraph.types import Command

from app.agent.prompts import SYSTEM_PROMPT
from app.agent.state import AgentState
from app.agent.tools import get_all_tools
from app.config import DATA_DIR, LLM_BASE_URL, LLM_API_KEY, LLM_MODEL, LLM_TEMPERATURE

CHECKPOINT_DB = DATA_DIR / "agent_checkpoints.sqlite"


def _build_llm():
    llm = ChatOpenAI(
        base_url=LLM_BASE_URL, api_key=LLM_API_KEY, model=LLM_MODEL, temperature=LLM_TEMPERATURE,
        # Defensive settings for a locally-hosted model, not fixes for a
        # specific observed bug (an earlier multi-minute stall turned out to
        # be a pydantic validation error causing the model to loop retrying
        # a tool call that kept failing silently -- see AgentState.
        # NotRequired in state.py for the real fix). Kept anyway as cheap
        # insurance: suppress hybrid-model "thinking" traces where supported,
        # cap worst-case wait, and don't waste time retrying a model that's
        # just being slow rather than transiently failing.
        extra_body={"think": False},
        timeout=150,
        max_retries=0,
        max_tokens=1024,
    )
    # get_all_tools() re-scans data/dynamic_tools/ every call (not cached)
    # so a tool approved via create_tool is bound on the very next turn --
    # _agent_node already rebuilds the LLM fresh on every turn, so this
    # needs no extra invalidation of its own (unlike the compiled graph's
    # ToolNode below, which IS cached and needs invalidate_graph_cache()).
    return llm.bind_tools(get_all_tools())


def _agent_node(state: AgentState):
    llm = _build_llm()
    messages = [SystemMessage(content=SYSTEM_PROMPT), *state["messages"]]
    response = llm.invoke(messages)
    return {"messages": [response]}


def _should_continue(state: AgentState) -> str:
    last = state["messages"][-1]
    if getattr(last, "tool_calls", None):
        return "tools"
    return END


_checkpoint_conn: Optional[sqlite3.Connection] = None


def _get_checkpointer() -> SqliteSaver:
    # A dedicated, persistent connection reused across every build_graph()
    # call (including rebuilds triggered by invalidate_graph_cache() below)
    # -- rather than opening a fresh sqlite3.connect() per rebuild, which
    # would leak a connection every time a dynamic tool gets registered.
    # SqliteSaver itself is a thin wrapper with no problematic per-instance
    # state, so constructing a new one around the same connection on each
    # rebuild is safe (verified: state written via one instance is visible
    # through a freshly-constructed SqliteSaver wrapping the same conn).
    global _checkpoint_conn
    if _checkpoint_conn is None:
        _checkpoint_conn = sqlite3.connect(str(CHECKPOINT_DB), check_same_thread=False)
    return SqliteSaver(_checkpoint_conn)


def build_graph():
    graph = StateGraph(AgentState)
    graph.add_node("agent", _agent_node)
    graph.add_node("tools", ToolNode(get_all_tools()))

    graph.add_edge(START, "agent")
    graph.add_conditional_edges("agent", _should_continue, {"tools": "tools", END: END})
    graph.add_edge("tools", "agent")

    return graph.compile(checkpointer=_get_checkpointer())


_compiled_graph = None

# The Streamlit UI polls job status from a `st.fragment(run_every=...)`,
# which runs on its own timer thread independent of the main script thread
# -- so a background poll's `get_state` can fire concurrently with a
# chat turn's `invoke`. Both share one sqlite3.Connection (via
# check_same_thread=False), and raw sqlite3 connections are not safe for
# concurrent use from multiple threads; without serializing access here,
# that races into a hang. All graph access from the app should go through
# invoke_turn/read_state below rather than calling the compiled graph
# directly, so this lock actually protects every caller.
#
# IMPORTANT: never call invalidate_graph_cache() (or anything else that
# acquires this lock) from *inside* a tool function. LangGraph's ToolNode
# runs tool calls on its own ThreadPoolExecutor worker thread, not the
# thread that called .invoke() -- confirmed empirically, not assumed. A
# tool that acquired this lock would deadlock for real: the calling thread
# blocks inside .invoke() (holding the lock) waiting for the tool to
# finish, while the worker thread blocks trying to acquire the very lock
# the calling thread is holding. Switching this to an RLock does NOT fix
# that (RLock reentrancy only helps the *same* thread reacquire it; this
# is two different threads) -- the actual fix is architectural: create_tool
# (see tools.py) only persists the new tool to disk and never touches the
# graph object itself; main.py calls invalidate_graph_cache() from the
# main script thread, strictly after resume_turn() has already returned
# and released this lock.
_graph_lock = threading.Lock()


def get_graph():
    global _compiled_graph
    if _compiled_graph is None:
        _compiled_graph = build_graph()
    return _compiled_graph


def invalidate_graph_cache() -> None:
    """Forces the next get_graph() call to rebuild the compiled graph (a
    fresh StateGraph + ToolNode picking up get_all_tools()'s current
    contents, but the SAME underlying sqlite connection/checkpointer via
    _get_checkpointer() -- so no state is lost and no connection leaks).
    Called by create_tool (see tools.py) after a new dynamic tool is
    approved and persisted, so it becomes callable immediately without
    restarting the process. Takes the same lock as every other graph
    access so this can't race the 4s polling fragment's concurrent reads."""
    global _compiled_graph
    with _graph_lock:
        _compiled_graph = None


def invoke_turn(input_dict: dict, config: dict) -> dict:
    with _graph_lock:
        return get_graph().invoke(input_dict, config)


def resume_turn(resume_value: Any, config: dict) -> dict:
    """Resumes a graph paused on `interrupt()` -- used for the job-approval
    gate in submit_job (see tools.py). resume_value becomes that tool's
    interrupt() return value."""
    with _graph_lock:
        return get_graph().invoke(Command(resume=resume_value), config)


def read_state(config: dict) -> dict:
    with _graph_lock:
        snapshot = get_graph().get_state(config)
    return snapshot.values if snapshot else {}


def pending_approval(config: dict) -> Optional[dict]:
    """Returns the interrupt() payload if the graph is currently paused
    awaiting job-approval (see submit_job in tools.py), else None. Reading
    this from `get_state` rather than an invoke() return value means it
    survives across Streamlit reruns -- e.g. the user reloading the page
    while a job is pending approval still sees the approval card."""
    with _graph_lock:
        snapshot = get_graph().get_state(config)
    if snapshot and snapshot.interrupts:
        return snapshot.interrupts[0].value
    return None
