"""The agent's LangGraph: a standard tool-calling ReAct loop (agent node ->
tools node -> back to agent, until the model stops requesting tools) with
a SQLite checkpointer so per-conversation state (message history, active
molecule, running job ids) survives page reloads and process restarts.
"""
from __future__ import annotations

import logging
import re
import sqlite3
import threading
import uuid
from typing import Any, Optional

from langchain_core.messages import HumanMessage, RemoveMessage, SystemMessage
from langgraph.graph.message import REMOVE_ALL_MESSAGES
from langchain_openai import ChatOpenAI
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.graph import END, START, StateGraph
from langgraph.prebuilt import ToolNode
from langgraph.types import Command

from app.agent.prompts import SYSTEM_PROMPT
from app.agent.state import CLEAR_MOLECULE, AgentState
from app.agent.tools import get_all_tools
from app.config import DATA_DIR, LLM_BASE_URL, LLM_API_KEY, LLM_MODEL, LLM_TEMPERATURE

CHECKPOINT_DB = DATA_DIR / "agent_checkpoints.sqlite"

logger = logging.getLogger(__name__)

# Real job ids are uuid4().hex[:12] (see JobSpec.job_id in
# app/chemistry/jobs/base.py) -- a 12-char lowercase hex token in a
# tool-call-free response that was never actually mentioned anywhere
# earlier in this conversation is a precise, low-false-positive signal
# that the model fabricated a job-submission claim in prose instead of
# actually calling submit_job (a real, observed failure mode of the local
# qwen3:30b model under load-bearing in-context instructions -- see the
# "sure. do it" incident this check was added for). Checking against every
# id mentioned anywhere in prior message content -- not just this thread's
# active_job_ids -- matters because job_context_summary() (used by both
# job_watcher.py's notices and the Job Manager's "attach to prompt"
# feature) always includes "Job {job_id}" literally in an injected
# HumanMessage, and that job may well have been submitted from a
# different thread and so never appear in this thread's own
# active_job_ids; scanning message content catches that legitimate case
# too, not just genuinely-new-to-this-conversation ids. Keyword-matching
# phrases like "submitted"/"Tool Execution" instead was considered and
# rejected -- it risks both false positives (a normal report of a real,
# already-completed job) and false negatives (a differently-worded
# fabrication), whereas this is anchored to actual ground truth.
_JOB_ID_RE = re.compile(r"\b[0-9a-f]{12}\b")

_FABRICATION_NUDGE = (
    "Your previous draft referenced a job ID that was never actually submitted -- no "
    "submit_job tool call was made, so nothing is really running. Do not report job "
    "results, ids, or ETAs that don't come from a real tool call. Either call submit_job "
    "now if you actually intend to run it, or correct your previous statement in plain "
    "text without inventing a job ID or result."
)


def _looks_fabricated(response, active_job_ids: list[str], prior_messages: list) -> bool:
    if getattr(response, "tool_calls", None):
        return False
    content = response.content if isinstance(response.content, str) else ""
    candidates = _JOB_ID_RE.findall(content.lower())
    if not candidates:
        return False
    known_ids = set(active_job_ids)
    for m in prior_messages:
        text = getattr(m, "content", None)
        if isinstance(text, str):
            known_ids.update(_JOB_ID_RE.findall(text.lower()))
    return any(c not in known_ids for c in candidates)


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

    active_job_ids = state.get("active_job_ids") or []
    if _looks_fabricated(response, active_job_ids, messages):
        # Bounded to exactly one retry -- this is a best-effort backstop for
        # an unreliable local model, not a hard guarantee; looping further
        # on a model that keeps fabricating would just add latency without
        # a real chance of a different outcome. The discarded draft and the
        # corrective nudge below are never appended to permanent state --
        # only the retry's response becomes this node's actual output.
        logger.warning("Discarding a likely-fabricated job-submission response, retrying once: %r", response.content)
        response = llm.invoke([*messages, response, HumanMessage(content=_FABRICATION_NUDGE)])
        if _looks_fabricated(response, active_job_ids, messages):
            logger.warning("Fabrication check still tripped after retry; returning it as-is: %r", response.content)

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

# The FastAPI server has several independent threads that can touch the
# graph concurrently: job_watcher.py's background thread, each chat turn's
# own background thread (server/routes/chat.py's _run_turn, since
# POST /messages returns 202 immediately rather than blocking), and every
# sync `def` route handler running in uvicorn's thread pool (e.g. a
# concurrent GET /state poll). Both share one sqlite3.Connection (via
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
# graph object itself; server/routes/tools.py's tool-approval endpoint
# calls invalidate_graph_cache() from the request-handling thread,
# strictly after resume_turn() has already returned and released this
# lock.
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


def stream_turn_tokens(input_dict: dict, config: dict):
    """Same call as invoke_turn, but yields (mode, chunk) tuples as the
    turn progresses instead of blocking until the whole ReAct loop
    finishes -- requesting "updates" (tool-call progress) and "messages"
    (per-token deltas of the assistant's own text) simultaneously; LangGraph
    yields (mode, chunk) tuples whenever stream_mode is a list, instead of
    bare chunks for a single mode. Used by server/routes/chat.py for the
    React frontend's token-by-token streaming over SSE. Confirmed
    empirically (not assumed from docs -- see
    scratchpad/verify_token_streaming.py from the session that added this)
    that "messages" mode yields real incremental token deltas through
    qwen3:30b via Ollama's OpenAI-compatible endpoint, with no change
    needed to _build_llm()'s ChatOpenAI construction (no explicit
    streaming=True) -- LangGraph's "messages" stream mode drives real
    streaming on its own. Holds _graph_lock for the entire iteration
    (acquired on the caller's first next() call, released when the
    generator is exhausted), exactly like invoke_turn holds it for the
    whole call -- a chat turn was already single-threaded through this
    lock before streaming existed, so this isn't a new contention
    source."""
    with _graph_lock:
        yield from get_graph().stream(input_dict, config, stream_mode=["updates", "messages"])


def resume_turn(resume_value: Any, config: dict) -> dict:
    """Resumes a graph paused on `interrupt()` -- used for the job-approval
    gate in submit_job (see tools.py). resume_value becomes that tool's
    interrupt() return value."""
    with _graph_lock:
        return get_graph().invoke(Command(resume=resume_value), config)


def clear_molecule(config: dict) -> dict:
    """Clears the active molecule AND the whole frame history for a
    conversation -- the molecule panel's reset button ("reset the whole
    panel"). Deliberately bypasses the LLM entirely (update_state()
    directly, not a chat turn) since this is a mechanical UI action with no
    ambiguity for a model to resolve, the same reasoning behind keeping the
    KB-lookup and retry-budget logic elsewhere in this app out of LLM
    control. update_state() applies AgentState's channel reducers exactly
    like a node's Command(update=...) would, so `molecule` goes through
    _last_molecule's CLEAR_MOLECULE branch (see state.py) rather than
    writing a plain `None` that reducer would silently ignore, and
    `molecule_frames` goes through _molecule_frames_reducer's
    "__replace__" escape hatch to empty the list instead of appending to
    it."""
    with _graph_lock:
        get_graph().update_state(config, {"molecule": CLEAR_MOLECULE, "molecule_frames": {"__replace__": []}})
        snapshot = get_graph().get_state(config)
    return snapshot.values if snapshot else {}


def remove_frame(config: dict, frame_id: str) -> dict:
    """Deletes a single molecule frame by its stable id (see molecule_frames
    in state.py) -- the molecule panel's per-frame delete button. Uses the
    same reset-and-replace approach as remove_messages above and for the
    same reason: a filtered list built from a fresh get_state() read is
    simpler and safer than trusting a reducer to reconcile a targeted
    removal against whatever it thinks is already there. Does not touch
    `molecule` (the currently active geometry) even if the deleted frame
    happens to be the one it was set from -- deleting a frame from the
    browsing history is a distinct action from clearing the active
    molecule (clear_molecule above)."""
    with _graph_lock:
        snapshot = get_graph().get_state(config)
        current = (snapshot.values if snapshot else {}).get("molecule_frames", [])
        kept = [f for f in current if f.get("id") != frame_id]
        get_graph().update_state(config, {"molecule_frames": {"__replace__": kept}})
        snapshot = get_graph().get_state(config)
    return snapshot.values if snapshot else {}


def set_active_frame(config: dict, frame_id: str) -> tuple[dict, Optional[dict]]:
    """Sets the active molecule to a previously-captured frame's already-
    resolved geometry -- the molecule panel's "attach to prompt" action.
    Called from _run_turn (server/routes/chat.py) synchronously before that
    turn's messages are built, so the frame becomes the active molecule
    before the agent ever sees the user's message, the same effective
    result an explicit set_molecule call would have had. Deliberately a
    direct update_state() write, not a tool call: the frame's molecule dict
    was already fully resolved when the frame was created (by set_molecule
    or generate_job_input), so there's no network lookup to redo and no
    ambiguity for an LLM to resolve here -- consistent with clear_molecule
    above bypassing the LLM for the same reason. Returns (state, frame) --
    frame is None if frame_id no longer exists (e.g. deleted from another
    tab between the click and the send), in which case the active molecule
    is left untouched rather than erroring the whole turn."""
    with _graph_lock:
        snapshot = get_graph().get_state(config)
        frames = (snapshot.values if snapshot else {}).get("molecule_frames", [])
        frame = next((f for f in frames if f.get("id") == frame_id), None)
        if frame is not None:
            get_graph().update_state(config, {"molecule": frame["molecule"]})
            snapshot = get_graph().get_state(config)
    return (snapshot.values if snapshot else {}), frame


def add_built_frame(config: dict, molecule: dict) -> tuple[dict, dict]:
    """Appends a freshly-generated conformer (from the 2D-sketcher builder,
    see molecule.molecule_from_molblock) as a new molecule_frames entry and
    makes it the active molecule -- the molecule panel's "use this
    structure" action. Deliberately a direct update_state() write, not a
    tool call, for the same reason as set_active_frame above: the geometry
    is already fully resolved (RDKit's ETKDG+MMFF94 conformer generation
    already ran server-side before this is called), so there's nothing left
    for an LLM turn to do or decide. Builds its own frame id/description
    here rather than reusing tools.py's _make_frame, since that helper is
    keyed to a user-typed `identifier` string (a tool argument) that has no
    equivalent for a sketch -- a distinct-enough shape that duplicating the
    small dict-building logic was clearer than stretching _make_frame's
    signature to cover a case it wasn't written for."""
    name = molecule.get("name") or f"{len(molecule.get('symbols', []))}-atom sketch"
    frame = {
        "id": uuid.uuid4().hex,
        "molecule": molecule,
        "description": f"Sketched: {name}",
    }
    with _graph_lock:
        get_graph().update_state(config, {"molecule": molecule, "molecule_frames": [frame]})
        snapshot = get_graph().get_state(config)
    return (snapshot.values if snapshot else {}), frame


def read_state(config: dict) -> dict:
    with _graph_lock:
        snapshot = get_graph().get_state(config)
    return snapshot.values if snapshot else {}


def remove_messages(config: dict, message_ids: list) -> dict:
    """Strips specific messages from a thread's checkpointed state by id.
    Used by server/routes/chat.py's _run_turn to erase assistant/tool
    output that a stopped turn's underlying LLM call kept generating and
    committing in the background after the user clicked Stop, which was
    never shown to the user and would otherwise silently become part of
    the next turn's context -- see that function's inline comment for the
    empirical confirmation (GPU utilization staying pinned well past when
    the SSE stream stopped forwarding tokens) that this genuinely happens,
    not just a theoretical race.

    Deliberately NOT `update_state(config, {"messages": [RemoveMessage(id=mid) for mid in message_ids]}})`
    -- that targeted-removal form was tried first and empirically fails
    here: `add_messages`'s deletion path raises "Attempting to delete a
    message with an ID that doesn't exist" even for an id `read_state`
    just returned moments earlier, i.e. the reducer's own notion of
    "existing" ids doesn't line up with what get_state() reports (not
    fully root-caused -- this project's own practice is to trust what's
    empirically verified over what "should" work per the library's
    contract). The reset-and-replace form below sidesteps that bookkeeping
    entirely: REMOVE_ALL_MESSAGES clears the whole channel and the
    filtered list repopulates it in the same update, which was verified
    to work cleanly against a real checkpoint before being wired in here."""
    if not message_ids:
        return read_state(config)
    with _graph_lock:
        snapshot = get_graph().get_state(config)
        current = (snapshot.values if snapshot else {}).get("messages", [])
        keep = [m for m in current if getattr(m, "id", None) not in message_ids]
        get_graph().update_state(config, {"messages": [RemoveMessage(id=REMOVE_ALL_MESSAGES)] + keep})
        snapshot = get_graph().get_state(config)
    return snapshot.values if snapshot else {}


def pending_approval(config: dict) -> Optional[dict]:
    """Returns the interrupt() payload if the graph is currently paused
    awaiting job-approval (see submit_job in tools.py), else None. Reading
    this from `get_state` rather than an invoke() return value means it
    survives across page reloads -- e.g. the user reloading the browser
    while a job is pending approval still sees the approval card."""
    with _graph_lock:
        snapshot = get_graph().get_state(config)
    if snapshot and snapshot.interrupts:
        return snapshot.interrupts[0].value
    return None
