"""The agent's LangGraph: a standard tool-calling ReAct loop (agent node ->
tools node -> back to agent, until the model stops requesting tools) with
a checkpointer so per-conversation state (message history, active
molecule, running job ids) survives page reloads and process restarts.

Checkpointer backend is chosen by DATABASE_URL (app/config.py,
QC_AGENT_DATABASE_URL): unset means SqliteSaver against a single local file
(the original, zero-config local-dev behavior); set means PostgresSaver
against a connection pool (the containerized deployment -- see
docker-compose.yml). See _get_checkpointer() below for why this distinction
also changes the locking story, not just the storage backend.
"""
from __future__ import annotations

import logging
import re
import sqlite3
import threading
import time
import uuid
from typing import Any, Optional

from langchain_core.messages import AIMessage, HumanMessage, RemoveMessage, SystemMessage, ToolMessage
from langgraph.graph.message import REMOVE_ALL_MESSAGES
from langchain_openai import ChatOpenAI
from langgraph.checkpoint.postgres import PostgresSaver
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.graph import END, START, StateGraph
from langgraph.prebuilt import ToolNode
from langgraph.types import Command
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from app.agent.prompts import SYSTEM_PROMPT
from app.agent.state import CLEAR_MOLECULE, AgentState
from app.agent.tools import get_all_tools, get_executable_tools
from app.config import (
    DATA_DIR,
    DATABASE_POOL_MAX_SIZE,
    DATABASE_URL,
    DRAFT_HOLD_SECONDS,
    LLM_BASE_URL,
    LLM_API_KEY,
    LLM_FIXED_PROMPT_TOKENS,
    LLM_HISTORY_FLOOR,
    LLM_HISTORY_WINDOW,
    LLM_MAX_TOKENS,
    LLM_MODEL,
    LLM_NUM_CTX,
    LLM_OUTPUT_RESERVE_TOKENS,
    LLM_TEMPERATURE,
)

CHECKPOINT_DB = DATA_DIR / "agent_checkpoints.sqlite"

logger = logging.getLogger(__name__)

# Real job ids are uuid4().hex[:12] (see JobSpec.job_id in
# app/chemistry/jobs/base.py) -- a 12-char lowercase hex token in a
# tool-call-free response that was never actually mentioned anywhere
# earlier in this conversation is a precise, low-false-positive signal
# that the model fabricated a job-submission claim in prose instead of
# actually calling submit_draft (a real, observed failure mode of the local
# model then in use, qwen3:30b, under load-bearing in-context instructions
# -- see the "sure. do it" incident this check was added for; the served
# model has since changed, the failure mode has not). Checking against every
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
    "submit_draft tool call was made, so nothing is really running. Do not report job "
    "results, ids, or ETAs that don't come from a real tool call. Either call submit_draft "
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
        #
        # `num_ctx` is deliberately NOT sent here. It used to be, with a
        # comment claiming it made the window explicit rather than inherited
        # from however the Ollama service was started. That claim was false:
        # the /v1 endpoint accepts the option and ignores it. Verified by
        # sending num_ctx=2048 with a 4,018-token prompt and watching it go
        # through untruncated, identical to num_ctx=32768. Sending it bought
        # nothing and cost a great deal, because it read like a guarantee --
        # the app believed it had a 32k window while the server had 64k, and
        # nothing budgeted against the real number until a prompt reached
        # 65,433 tokens of a 65,536 window and replies started being cut off
        # mid-sentence. The window is now declared in config (LLM_NUM_CTX)
        # and respected by _trim_history below. Do not re-add this option
        # without measuring that it does something; see
        # docs/MODEL_CONTEXT_BUDGET.md, which has caught this twice.
        #
        # `think` is a different case and is kept: it IS honored. Measured
        # the same day, 250 characters of visible content cost 93 completion
        # tokens, so no hidden reasoning is being billed to the reply.
        extra_body={"think": False},
        timeout=150,
        max_retries=0,
        max_tokens=LLM_MAX_TOKENS,
    )
    return llm.bind_tools(get_all_tools())


def _digest_line(state: AgentState) -> Optional[str]:
    """A one-line, mechanically-built statement of what the conversation
    has established, to stand in front of a trimmed history.

    Built from AgentState, never by asking the model to summarize. A
    summarization call costs a whole extra round trip per turn, and a
    written summary is one more place a job id or a result can be invented
    -- exactly what `_looks_fabricated` below exists to catch. Everything
    here is a fact the app already holds.
    """
    parts: list[str] = []
    molecule = state.get("molecule") or {}
    if molecule.get("name"):
        formula = molecule.get("formula")
        parts.append(f"active molecule: {molecule['name']}"
                     + (f" ({formula})" if formula else ""))
    if state.get("pes_scan_end_molecule"):
        parts.append("an end geometry is also set")
    draft = state.get("job_draft") or {}
    if draft.get("task"):
        name = draft["task"] + (f"/{draft['subtype']}" if draft.get("subtype") else "")
        described = f"draft in progress: {name}"
        if draft.get("method"):
            described += f" at {draft['method']}"
        parts.append(described)
    job_ids = state.get("active_job_ids") or []
    if job_ids:
        shown = ", ".join(job_ids[-5:])
        more = f" (and {len(job_ids) - 5} earlier)" if len(job_ids) > 5 else ""
        parts.append(f"jobs submitted in this conversation: {shown}{more}")
    if not parts:
        return None
    return ("Earlier turns in this conversation have been trimmed for length. "
            "What still holds -- " + "; ".join(parts) + ".")


# Token estimation, for sizing history against the context window.
#
# There is no single characters-per-token ratio that works here, because
# what this app sends spans an enormous range. Measured against the served
# model's own tokenizer (`usage.prompt_tokens`, not an estimate):
#
#   content                      chars/token
#   -----------------------------------------
#   table of floats                  1.16
#   markdown results table           1.17
#   job summary, mixed               1.60
#   ordinary prose                   5.31
#
# A flat ratio has to pick a point in that range and is then wrong by up to
# 4.6x at the other end. Picking the prose end silently overruns the window
# on job results, which is the bug this whole mechanism exists to stop.
# Picking the numeric end throws away most of a prose conversation's memory
# for nothing.
#
# What actually separates them is digits. Numbers tokenize close to one
# token per character; letters tokenize about four times better. So count
# the two separately. Two estimators that seemed obvious were both tried
# and rejected on measurement:
#
#   tiktoken cl100k -- wrong tokenizer for Qwen, under-counted a real
#       conversation by 39% (47,142 against an actual 65,433). An
#       under-count is not a safety margin, it is the bug in disguise.
#   the usual ~4 chars/token -- true only of the prose row above.
#
# The coefficients are set so every measured sample comes out at or above
# its true cost (1.12x to 1.70x, prose being the most over-counted). This
# is deliberately asymmetric. Over-counting trims history sooner than
# strictly necessary, which loses old context the digest line partly covers
# and the user can work around. Under-counting truncates the reply
# mid-sentence with no error anywhere, and if the cut lands before a tool
# call the user just sees the app fail to do what it said it would.
_TOKENS_PER_DIGIT = 1.45
_TOKENS_PER_OTHER_CHAR = 0.32
_DIGITS = "0123456789"


def _estimate_tokens(text: str) -> int:
    if not text:
        return 0
    # str.count runs in C; a Python-level scan over the ~100,000 characters
    # a single turn can carry costs real time on every agent step.
    digits = sum(map(text.count, _DIGITS))
    others = len(text) - digits
    return int(digits * _TOKENS_PER_DIGIT + others * _TOKENS_PER_OTHER_CHAR) + 1


def _message_tokens(message) -> int:
    """A message's cost, including serialized tool-call arguments.

    An assistant message that calls a tool often has empty `.content` and
    carries everything in `.tool_calls`, so sizing on content alone reports
    a large message as free.
    """
    total = _estimate_tokens(str(message.content or ""))
    for call in getattr(message, "tool_calls", None) or []:
        total += _estimate_tokens(repr(call.get("args", "")))
    return total


def _history_token_budget() -> int:
    """What is left of the context window for conversation history."""
    return LLM_NUM_CTX - LLM_FIXED_PROMPT_TOKENS - LLM_OUTPUT_RESERVE_TOKENS


def _drop_orphan_tool_messages(window: list) -> list:
    """An OpenAI-compatible endpoint rejects a ToolMessage whose originating
    assistant tool_call is not in the same request, so a window that happens
    to begin mid-tool-round produces a 400 rather than a shorter
    conversation. Any leading ToolMessage orphaned by a cut is dropped."""
    while window and getattr(window[0], "type", "") == "tool":
        window.pop(0)
    return window


def _trim_history(messages: list) -> list:
    """The most recent messages that fit both caps, cut safely.

    Two caps, because they bound different things. LLM_HISTORY_WINDOW bounds
    message COUNT, which stops a conversation of many small turns from
    growing without limit. The token budget bounds SIZE, which is the one
    that actually protects the context window -- and the one this function
    used to be missing. Forty messages sounds modest until three of them are
    20,000-character job results; measured on a real conversation here, the
    forty-message window was 65,433 tokens against a 65,536-token server,
    leaving about 100 tokens to answer in. Two turns in a row were cut off
    mid-sentence before they could emit a submit_draft call, so the approval
    card simply never appeared and nothing anywhere logged a problem.

    Order matters: drop for budget FIRST, then drop orphaned leading
    ToolMessages. Doing it the other way lets the budget loop re-expose an
    orphan that the tool-message pass has already gone past, which is the
    400 this is supposed to prevent.

    LLM_HISTORY_FLOOR messages are kept whatever they cost. A single message
    can exceed the whole budget on its own, and answering with nothing at
    all is worse than answering over budget -- but it is logged, because an
    over-budget prompt is precisely the failure that is otherwise invisible.
    """
    window = list(messages[-LLM_HISTORY_WINDOW:])
    budget = _history_token_budget()
    floor = max(1, LLM_HISTORY_FLOOR)

    used = sum(_message_tokens(m) for m in window)
    while used > budget and len(window) > floor:
        used -= _message_tokens(window.pop(0))

    if used > budget:
        logger.warning(
            "Conversation history is over its token budget and cannot be trimmed further: "
            "~%d tokens vs a budget of %d (context %d, fixed prompt %d, output reserve %d). "
            "Holding the %d most recent messages (LLM_HISTORY_FLOOR). The reply may be "
            "truncated -- raise QC_AGENT_LLM_NUM_CTX if the server really has a larger window.",
            used, budget, LLM_NUM_CTX, LLM_FIXED_PROMPT_TOKENS, LLM_OUTPUT_RESERVE_TOKENS,
            len(window),
        )

    return _drop_orphan_tool_messages(window)


def _warn_if_truncated(response, sent_messages: list) -> None:
    """Say so when the model ran out of room mid-reply.

    `finish_reason: "length"` is not an error anywhere in the stack. The
    HTTP call is a clean 200, the graph node returns normally, the turn
    completes, and the checkpoint stores a perfectly well-formed message
    that happens to stop mid-word. Nothing raises and nothing logs, so the
    only evidence is a user noticing the assistant trailed off -- and when
    the cut lands before a tool call, not even that: the reply just quietly
    fails to do the thing it was about to do. That is how this went
    unnoticed until someone reported "the approval card took a couple of
    tries to appear".

    Logged with the prompt size when the server reports it, since the usual
    cause is a prompt that left no room to generate in rather than a reply
    that genuinely wanted to be long.
    """
    metadata = getattr(response, "response_metadata", None) or {}
    if metadata.get("finish_reason") != "length":
        return
    usage = metadata.get("token_usage") or {}
    # Streamed replies carry no usage unless stream_options asks for it, so
    # fall back to the same estimate the budget is built on.
    prompt_tokens = usage.get("prompt_tokens")
    measured = prompt_tokens is not None
    if not measured:
        prompt_tokens = sum(_message_tokens(m) for m in sent_messages)
    logger.warning(
        "Model reply hit finish_reason=length and was cut off. Prompt was %s%d tokens "
        "against a declared context of %d (output reserve %d, max_tokens %d). If the reply "
        "was about to make a tool call, that call was lost. Content ends: %r",
        "" if measured else "~", prompt_tokens, LLM_NUM_CTX, LLM_OUTPUT_RESERVE_TOKENS,
        LLM_MAX_TOKENS, str(response.content or "")[-120:],
    )


def _agent_node(state: AgentState):
    llm = _build_llm()
    history = _trim_history(state["messages"])
    # Appended to the one system message rather than sent as a second one.
    # Ollama's OpenAI-compatible endpoint rejects the latter outright --
    # `system message must be at the beginning`, HTTP 500 -- which would
    # have broken every turn long enough to be trimmed, and only those.
    system = SYSTEM_PROMPT
    if len(history) < len(state["messages"]):
        digest = _digest_line(state)
        if digest:
            system = f"{SYSTEM_PROMPT}\n\n{digest}"
    messages = [SystemMessage(content=system), *history]

    # A system prompt with nothing after it is not a request the served
    # model will answer: Qwen's template looks for a user turn and Ollama
    # returns `500 no user query found in messages`, which surfaces as a
    # raw OpenAIAPIError rather than anything a user can act on. Reachable
    # whenever a turn runs against a conversation whose stored state is
    # missing or empty, the clearest case being an approval card still open
    # in a tab after its thread is gone: clicking Approve resumes a graph
    # whose history is not there any more.
    #
    # Answering plainly beats a 500. There is genuinely nothing to say
    # about a conversation with no messages in it, so say that.
    if not history:
        logger.warning(
            "Agent turn on a conversation with no history; refusing to call the model "
            "with a system prompt alone (thread state is missing or empty)."
        )
        return {"messages": [AIMessage(content=(
            "I don't have any history for this conversation, so there's nothing here "
            "for me to pick up. Its saved state is missing or was cleared. Send a new "
            "message and I'll start from that."
        ))]}

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

    _warn_if_truncated(response, messages)
    return {"messages": [response]}


def _should_continue(state: AgentState) -> str:
    last = state["messages"][-1]
    if getattr(last, "tool_calls", None):
        return "tools"
    return END


def _submissions_this_step(state: AgentState) -> list[dict]:
    """The submission receipts for the tool batch that just finished, or an
    empty list if that batch was anything other than submissions only.

    The invariant that makes this safe: it keys on *this step's*
    tool_call_ids, never on "pending_submissions is non-empty". Tool call
    ids are unique, so a receipt left behind by an earlier mixed batch can
    never match a later one, which is why nothing has to clean that residue
    up (see the field's docstring in state.py).

    ToolMessages always immediately follow the AIMessage that requested
    them, so walking back over the trailing run of them cannot bleed into an
    older batch. Requiring every call in the batch to be answered makes that
    structural rather than assumed.

    A mixed batch -- say the model emitted check_job_status AND submit_draft
    together, which real conversations do -- has a trailing id with no
    receipt, so it returns [] and the turn goes to the model as before. That
    is deliberate: the other tool's result still needs relaying.
    """
    trailing: list[str] = []
    caller = None
    for m in reversed(state["messages"]):
        if isinstance(m, ToolMessage):
            trailing.append(m.tool_call_id)
            continue
        caller = m
        break
    if not trailing:
        return []
    requested = getattr(caller, "tool_calls", None) or []
    if len(requested) != len(trailing):
        return []
    receipts = {r.get("tool_call_id"): r for r in (state.get("pending_submissions") or [])}
    if not all(tcid in receipts for tcid in trailing):
        return []
    return [receipts[tcid] for tcid in reversed(trailing)]


def _after_tools(state: AgentState) -> str:
    return "job_submitted" if _submissions_this_step(state) else "agent"


def _submission_text(receipts: list[dict]) -> str:
    """The confirmation itself. Names each job with the label
    `_finish_submission` resolved through `resolve_job_label`, so this
    agrees with the job list, the drawer heading and the download
    filenames."""
    if len(receipts) == 1:
        r = receipts[0]
        edited = " using your edited input" if r.get("edited") else ""
        return (
            f"Started {r['label']}{edited}. Job id {r['job_id']}.\n\n"
            f"It's running in the background and I'll report the results here when it "
            f"finishes. You can close the tab and come back to them, or ask me at any "
            f"time how it's going."
        )
    listed = "\n".join(f"- {r['label']} (job id {r['job_id']})" for r in receipts)
    return (
        f"Started these calculations:\n{listed}\n\n"
        f"They're running in the background and I'll report each one's results here as "
        f"it finishes."
    )


def _job_submitted_node(state: AgentState):
    """The confirmation shown after an approved job starts, written by the
    app rather than by the model.

    This replaces a full LLM turn (53 to 77 seconds on this host, measured
    in docs/trackers/2026-08-drafting-outranks-summaries.md) whose entire
    output was narrating a fact the backend already held. The user approved
    the exact input, so the job either runs or fails, and both of those
    already have their own paths: the watcher's summary and the failed-job
    notice.

    Unlike `append_notice`, which writes the other app-authored messages,
    this runs INSIDE the graph. That distinction is the whole reason this
    node exists rather than a call bolted onto the approval route:
    `update_state` discards a pending interrupt and destroys an open
    approval card (see append_notice's own docstring), while a node cannot.
    `_stream_resume` publishes each node's messages as the graph streams, so
    the confirmation reaches the browser the moment this node completes,
    before anything downstream of it runs.

    Boundary condition worth stating because this node can END the turn: it
    is only correct while a successful submission is always the last thing a
    turn does. Today `_finish_submission` is reached from exactly one place
    (submit_draft), always after an interrupt(), so that holds. A future
    tool that submitted a job mid-turn without an interrupt would have its
    turn truncated here before the model answered whatever else was asked.
    """
    receipts = _submissions_this_step(state)
    if not receipts:
        # Unreachable: the router read the same state one hop ago.
        logger.error("job_submitted node reached with no submission receipts")
        return {"pending_submissions": {"__replace__": []}}
    return {
        "messages": [AIMessage(
            content=_submission_text(receipts),
            additional_kwargs={"nexus_notice": {
                "kind": "job_submitted",
                "job_ids": [r["job_id"] for r in receipts],
            }},
        )],
        "submission_follow_up": any(r.get("follow_up") for r in receipts),
        "pending_submissions": {"__replace__": []},
    }


def _after_job_submitted(state: AgentState) -> str:
    """Hand back to the model only when the user asked for further
    calculations that still need drafting. Routing on a state field rather
    than on the message's own notice payload keeps an internal routing bit
    out of what the client receives."""
    return "agent" if state.get("submission_follow_up") else END


_checkpoint_conn: Optional[sqlite3.Connection] = None
_pg_pool: Optional[ConnectionPool] = None


def _get_checkpointer():
    # Two backends, chosen once at process start by whether DATABASE_URL is
    # set (see app/config.py) -- not something that changes at runtime.
    #
    # SqliteSaver path (DATABASE_URL unset, local dev default): a dedicated,
    # persistent connection reused across every build_graph() call (including
    # rebuilds triggered by invalidate_graph_cache() below) -- rather than
    # opening a fresh sqlite3.connect() per rebuild, which would leak a
    # connection every time a dynamic tool gets registered. SqliteSaver
    # itself is a thin wrapper with no problematic per-instance state, so
    # constructing a new one around the same connection on each rebuild is
    # safe (verified: state written via one instance is visible through a
    # freshly-constructed SqliteSaver wrapping the same conn).
    #
    # PostgresSaver path (DATABASE_URL set, containerized deployment): built
    # around a psycopg_pool.ConnectionPool, NOT PostgresSaver.from_conn_string
    # -- that classmethod returns a context-manager-wrapped single Connection
    # (confirmed by inspecting its signature: `Iterator[PostgresSaver]`),
    # which isn't a shape that survives being stashed in a module global the
    # way this app's single long-lived checkpointer needs to. A pool is also
    # what actually fixes the old single-sqlite-connection bottleneck this
    # module used to have: each checkpoint read/write checks a connection out
    # of the pool and back in per call (confirmed by reading
    # langgraph.checkpoint.postgres._internal.get_connection), so concurrent
    # turns on different conversations no longer contend for one connection
    # the way they did under SqliteSaver's check_same_thread=False single
    # connection. `.setup()` (one-time checkpoint-table creation) is
    # confirmed idempotent -- safe to call unconditionally on first use
    # rather than needing a separate migration step.
    global _checkpoint_conn, _pg_pool
    if DATABASE_URL:
        if _pg_pool is None:
            _pg_pool = ConnectionPool(
                DATABASE_URL,
                min_size=1,
                max_size=DATABASE_POOL_MAX_SIZE,
                kwargs={"autocommit": True, "row_factory": dict_row},
            )
            PostgresSaver(_pg_pool).setup()
        return PostgresSaver(_pg_pool)
    if _checkpoint_conn is None:
        _checkpoint_conn = sqlite3.connect(str(CHECKPOINT_DB), check_same_thread=False)
    return SqliteSaver(_checkpoint_conn)


def build_graph():
    graph = StateGraph(AgentState)
    graph.add_node("agent", _agent_node)
    # get_executable_tools(), not get_all_tools(): the executor must also
    # be able to complete tool calls recorded by an earlier version of the
    # agent and still pending in some conversation's checkpoint. Those are
    # never offered to the model -- see tools.py.
    graph.add_node("tools", ToolNode(get_executable_tools()))

    # Writes the confirmation for a job that just started, in place of an
    # LLM turn that only narrated it. Reached only when every tool result in
    # the step was a successful submission -- see _submissions_this_step.
    graph.add_node("job_submitted", _job_submitted_node)

    graph.add_edge(START, "agent")
    graph.add_conditional_edges("agent", _should_continue, {"tools": "tools", END: END})
    graph.add_conditional_edges("tools", _after_tools,
                                {"job_submitted": "job_submitted", "agent": "agent"})
    graph.add_conditional_edges("job_submitted", _after_job_submitted,
                                {"agent": "agent", END: END})

    return graph.compile(checkpointer=_get_checkpointer())


_compiled_graph = None

# --- Locking -----------------------------------------------------------
#
# This module used to serialize EVERY graph-touching call (from every
# conversation at once) behind one process-global `_graph_lock`, because the
# old SqliteSaver backend was one sqlite3.Connection (check_same_thread=False,
# not safe for concurrent multi-thread use) shared by every thread that could
# touch the graph: job_watcher.py's background thread, each chat turn's own
# background thread (server/routes/chat.py's _run_turn, since POST /messages
# returns 202 immediately rather than blocking), and every sync `def` route
# handler running in uvicorn's thread pool (e.g. a concurrent GET /state
# poll). That meant ten different users' chat turns queued behind each other
# one at a time, for the FULL DURATION of each turn's LLM streaming -- by far
# the biggest scaling defect in a multi-user deployment, not just brief
# in-process bookkeeping.
#
# Fix: lock per conversation (thread_id), not globally. Two turns on
# DIFFERENT thread_ids never contend; two operations on the SAME thread_id
# still serialize, which is correct -- a single conversation's state can't be
# meaningfully written to by two overlapping operations anyway (this was
# never the part of the old behavior that needed loosening). This works for
# both checkpointer backends: PostgresSaver's connection pool makes true
# concurrent access across threads/connections safe on its own, but a
# per-thread-id lock is still needed here to preserve the read-then-write
# consistency several functions below rely on (get_state() followed by
# update_state() must not interleave with another write to the same
# thread_id in between) -- that's an application-level invariant, not
# something either checkpointer backend guarantees for free.
_thread_locks: dict[str, threading.Lock] = {}
# Guards *dict mutation only* (inserting a new thread_id's lock) -- held
# briefly, never across a graph call. Once a thread_id's lock exists it's
# never removed (a conversation lives for the process's lifetime; the
# per-thread_id Lock objects are cheap enough that this unbounded-but-tiny
# growth isn't worth adding eviction machinery for).
_thread_locks_guard = threading.Lock()


def _lock_for_thread(config: dict) -> threading.Lock:
    thread_id = config["configurable"]["thread_id"]
    with _thread_locks_guard:
        lock = _thread_locks.get(thread_id)
        if lock is None:
            lock = threading.Lock()
            _thread_locks[thread_id] = lock
        return lock


# Separate from the per-thread locks above: this one protects the single
# global `_compiled_graph` object (and the checkpointer it wraps), which
# every thread_id's graph calls share. get_graph() below acquires this
# briefly just to read/build that one object, then releases it BEFORE the
# caller's own per-thread lock is held across the actual (potentially
# long-running) .invoke()/.stream() call -- so this is never held for the
# duration of a turn, only for the instant it takes to fetch or rebuild the
# compiled graph.
_compiled_graph_lock = threading.Lock()

# IMPORTANT: never call invalidate_graph_cache(), or any of invoke_turn/
# stream_turn_tokens/resume_turn/read_state/clear_molecule/remove_frame/
# set_active_frame/add_built_frame/remove_messages/pending_approval below,
# from *inside* a tool function for that SAME thread_id. LangGraph's
# ToolNode runs tool calls on its own ThreadPoolExecutor worker thread, not
# the thread that called .invoke() -- confirmed empirically, not assumed. A
# tool that tried to acquire the per-thread lock for its own conversation
# would deadlock for real: the calling thread blocks inside .invoke()
# (holding that thread_id's lock) waiting for the tool to finish, while the
# tool's worker thread blocks trying to acquire the very lock the calling
# thread is holding. Switching to an RLock does NOT fix this (RLock
# reentrancy only helps the *same* thread reacquire it; this is two
# different threads). Calling any of these for a DIFFERENT thread_id from
# inside a tool is fine (no shared lock), but there's no legitimate reason a
# tool would need to.


def get_graph():
    global _compiled_graph
    with _compiled_graph_lock:
        if _compiled_graph is None:
            _compiled_graph = build_graph()
        return _compiled_graph


def invalidate_graph_cache() -> None:
    """Forces the next get_graph() call to rebuild the compiled graph (a
    fresh StateGraph + ToolNode picking up get_all_tools()'s current
    contents, but the SAME underlying checkpointer via _get_checkpointer()
    -- so no state is lost and no connection/pool leaks). Takes
    _compiled_graph_lock, same as get_graph() itself, so this can't race a
    concurrent rebuild. No current caller (the dynamic-tool-creation feature
    that used to call this after approving a new tool has been removed);
    kept as generic graph-rebuild infrastructure for any future case that
    needs to swap the tool list at runtime. See the per-thread-lock deadlock
    warning above -- still applies to this function specifically when called
    from inside a tool, even though it no longer shares a lock object with
    invoke_turn: get_graph() (called internally by invoke_turn) still
    acquires this same _compiled_graph_lock, briefly, so a tool's worker
    thread calling this while the calling thread is mid-.invoke() and about
    to call get_graph() again (e.g. on a later ReAct loop iteration) can
    still contend for it -- avoid this call from inside a tool entirely,
    it has no legitimate use case there."""
    global _compiled_graph
    with _compiled_graph_lock:
        _compiled_graph = None


def invoke_turn(input_dict: dict, config: dict) -> dict:
    with _lock_for_thread(config):
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
    that "messages" mode yields real incremental token deltas through a
    local Ollama model (qwen3:30b at the time of that verification; the
    served model is set by QC_AGENT_LLM_MODEL) via its OpenAI-compatible
    endpoint, with no change
    needed to _build_llm()'s ChatOpenAI construction (no explicit
    streaming=True) -- LangGraph's "messages" stream mode drives real
    streaming on its own. Holds this thread_id's lock (see _lock_for_thread
    above) for the entire iteration (acquired on the caller's first next()
    call, released when the generator is exhausted), exactly like
    invoke_turn holds it for the whole call -- a turn on this conversation
    was already single-threaded through some lock before streaming existed,
    so this isn't a new contention source; it just no longer blocks turns on
    OTHER conversations the way the old process-global lock did."""
    with _lock_for_thread(config):
        yield from get_graph().stream(input_dict, config, stream_mode=["updates", "messages"])


def resume_turn(resume_value: Any, config: dict) -> dict:
    """Resumes a graph paused on `interrupt()` -- used for the job-approval
    gate in submit_draft (see tools.py). resume_value becomes that tool's
    interrupt() return value."""
    with _lock_for_thread(config):
        return get_graph().invoke(Command(resume=resume_value), config)


def stream_resume_tokens(resume_value: Any, config: dict):
    """resume_turn, but streaming -- yields the same (mode, chunk) tuples
    as stream_turn_tokens.

    F-008. Clicking Approve resumed the graph with a single blocking
    invoke(), so the UI went silent for the whole resume: the tool call
    that actually submits the job, plus the follow-up LLM turn that
    summarises it, could easily run for several seconds with nothing on
    screen. Every other turn in the app streams its tool progress. The
    original reasoning for leaving this one blocking -- "a one-click
    resume has no user-authored message to render early" -- was right
    about the user's own message and wrong about everything after it.

    Same lock discipline as stream_turn_tokens: this thread_id's lock is
    held for the whole iteration, acquired on the first next() and
    released when the generator is exhausted.
    """
    with _lock_for_thread(config):
        yield from get_graph().stream(
            Command(resume=resume_value), config, stream_mode=["updates", "messages"],
        )


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
    with _lock_for_thread(config):
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
    with _lock_for_thread(config):
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
    result an explicit set_geometry call would have had. Deliberately a
    direct update_state() write, not a tool call: the frame's molecule dict
    was already fully resolved when the frame was created (by set_geometry),
    so there's no network lookup to redo and no
    ambiguity for an LLM to resolve here -- consistent with clear_molecule
    above bypassing the LLM for the same reason. Returns (state, frame) --
    frame is None if frame_id no longer exists (e.g. deleted from another
    tab between the click and the send), in which case the active molecule
    is left untouched rather than erroring the whole turn."""
    with _lock_for_thread(config):
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
    with _lock_for_thread(config):
        get_graph().update_state(config, {"molecule": molecule, "molecule_frames": [frame]})
        snapshot = get_graph().get_state(config)
    return (snapshot.values if snapshot else {}), frame


def add_geometry_frames(config: dict, molecules: list[dict]) -> tuple[dict, list[dict]]:
    """Appends one or more already-resolved molecules as new molecule_frames
    entries in a single state write, making the FIRST one the active
    molecule -- Phase 3's upload-attach action for a 1- or 2-geometry xyz
    file (a 3+-geometry upload instead becomes a `geometry_set` job; see
    `JobManager.submit_geometry_set`, which never touches thread state at
    all). Generalizes `add_built_frame` to more than one molecule at once
    (`molecule_frames`' own reducer already accepts a list to append -- see
    `app/agent/state.py::_molecule_frames_reducer`) rather than calling
    `add_built_frame` once per molecule, which would leave the LAST
    molecule active instead of the first (each call's own `"molecule"` key
    would overwrite the previous). For a 2-geometry upload the first frame
    is the more natural default active molecule -- interpolation/NEB
    endpoints are usually read as "start" and "end", and only the first
    needs to be immediately usable in the next message; the second is still
    fully present in molecule_frames for the scrubber/panel to reach.
    Deliberately a direct update_state() write, not a tool call, for the
    same reason add_built_frame is: every molecule here was already fully
    resolved (parsed from the uploaded file) before this is called."""
    def _frame(molecule: dict) -> dict:
        n_atoms = len(molecule.get("symbols", []))
        name = molecule.get("name") or f"{n_atoms}-atom geometry"
        return {"id": uuid.uuid4().hex, "molecule": molecule, "description": f"Uploaded: {name}"}

    frames = [_frame(molecule) for molecule in molecules]
    with _lock_for_thread(config):
        get_graph().update_state(config, {"molecule": molecules[0], "molecule_frames": frames})
        snapshot = get_graph().get_state(config)
    return (snapshot.values if snapshot else {}), frames


# --- pure reads: deliberately NOT under the per-thread turn lock ----------
#
# The two functions below only ever call get_state(). They take no lock, and
# that is the point: the per-thread lock is held for the whole of a ReAct
# turn, measured at 53-77 seconds for an ordinary one and longer for a
# troubleshooting turn, so a read that waited for it waited that long.
# Opening a conversation whose turn is running blocked on exactly this, and
# the frontend polls /state, so the UI dragged whenever a background
# job-summary turn was in flight.
#
# Safe on both checkpointer backends, for different reasons, and both were
# checked rather than assumed. PostgresSaver checks a connection out of the
# pool per call, which is what makes concurrent access across threads safe
# (see _get_checkpointer). SqliteSaver shares one connection with
# check_same_thread=False, which would not be enough on its own -- but
# sqlite3.threadsafety is 3 (serialized), so the module serializes concurrent
# use of that connection itself. If that ever stops holding, these need a
# short lock around get_state alone, never the turn lock.
#
# No atomicity is lost. The lock exists to stop a get_state/update_state pair
# interleaving with another write, and a standalone read is not half of such
# a pair -- every caller that reads and then writes re-acquires for the
# write, so those two calls were never atomic with each other anyway.
#
# What changes is what a read sees DURING a turn: the last committed
# checkpoint, rather than the finished turn it used to wait for. That is the
# better answer as well as the faster one, because the rest of the turn then
# arrives over SSE as it happens, instead of appearing all at once after a
# stall that looks like the app has hung.


def read_state(config: dict) -> dict:
    snapshot = get_graph().get_state(config)
    return snapshot.values if snapshot else {}


def append_notice(config: dict, text: str, notice: Optional[dict] = None) -> Any:
    """Appends a message to a conversation WITHOUT running the LLM.

    The failed-job notice needs this. A job that dies must tell the user so
    in the conversation itself, and that statement has to survive a reload,
    a logout and a different browser -- the leave-and-return workflow is
    the whole reason jobs run detached in the first place. An SSE event
    alone would be gone the moment the tab closed, which is precisely the
    case a user hitting a failure is most likely to be in.

    A direct `update_state()` write, for the same reason clear_molecule and
    add_built_frame are: this is mechanical, there is nothing here for a
    model to decide, and invoking the agent just to have it say "your job
    failed" would spend an LLM round trip to restate something already
    known -- which is the auto-retry mistake in miniature.

    `notice` is structured data the frontend renders as a card (a job id, a
    kind, whether an action is offered). It rides in additional_kwargs
    rather than being parsed back out of the text, so the UI never has to
    pattern-match on prose.

    **This is not safe against a graph paused at an approval.** It reads as
    a harmless append, and against an idle conversation it is, but
    `update_state` discards a pending `interrupt()` -- the approval card
    disappears, the submit_draft call is orphaned and the user's later
    Approve does nothing. Anything on a path that can run while a card is
    open wants `append_notice_unless_card_pending` below instead. The
    remaining plain callers are user-initiated (attaching a file), where
    the user is looking at the app rather than at a card.
    """
    message = _notice_message(text, notice)
    with _lock_for_thread(config):
        get_graph().update_state(config, {"messages": [message]})
    return message


def _notice_message(text: str, notice: Optional[dict]) -> AIMessage:
    return AIMessage(
        content=text,
        additional_kwargs={"nexus_notice": notice} if notice else {},
    )


def append_notice_unless_card_pending(
    config: dict, text: str, notice: Optional[dict] = None,
) -> Optional[Any]:
    """append_notice, but it declines while an approval card is open.

    A plain `update_state` looks harmless next to starting a whole agent
    turn, and for the drafting back-and-forth it is: it appends a message
    and touches nothing else. Against a graph paused at submit_draft's
    `interrupt()` it is not. Measured on the real topology, `update_state`
    discards the pending approval task exactly as thoroughly as invoking
    with new input does -- interrupts one to zero, `next` emptied, the
    submit_draft call orphaned, the user's later Approve a silent no-op.

    So a failed job's notice, which is otherwise deliberately allowed
    through during drafting (the user should hear that a calculation died
    without waiting for the draft to finish), has to wait out the narrow
    window where a card is actually on screen. Returns None when it
    declined, so the caller leaves the job unseen and retries on its next
    tick rather than losing the notice.
    """
    with _lock_for_thread(config):
        if pending_approval(config) is not None:
            return None
        message = _notice_message(text, notice)
        get_graph().update_state(config, {"messages": [message]})
        return message


def append_attached_file(config: dict, text: str) -> Any:
    """Injects an uploaded blind-input file's raw text into the
    conversation as a synthetic HumanMessage, without running the LLM --
    the same "direct update_state() write, nothing here for a model to
    decide" mechanism append_notice (above) uses, and the same
    "(attached ..., not typed by the user)" HumanMessage convention
    server/routes/chat.py's _run_turn already uses for job_ids/frame_id
    attachment (job_context_summary()/frame descriptions), so this reads
    the same way in the transcript rather than inventing a second
    attachment shape. Called by POST /api/threads/{id}/attach_upload's
    .inp/.input/.json branch (P9.6): unlike a .xyz upload, a blind input
    file has no geometry for add_geometry_frames to act on, so the file's
    CONTENT is what has to reach the model -- put here, in the message
    history, it's available on this and every later turn to fill a
    `blind` draft's raw_input_text without the user re-pasting it by hand.

    A plain HumanMessage, not an AIMessage-with-notice-card: the file's
    content needs to be real, readable conversation context the LLM
    attends to like anything else the user provided, not a UI-only
    notice card whose structured payload the model never sees as text.
    """
    message = HumanMessage(content=text)
    with _lock_for_thread(config):
        get_graph().update_state(config, {"messages": [message]})
    return message


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
    with _lock_for_thread(config):
        snapshot = get_graph().get_state(config)
        current = (snapshot.values if snapshot else {}).get("messages", [])
        keep = [m for m in current if getattr(m, "id", None) not in message_ids]
        get_graph().update_state(config, {"messages": [RemoveMessage(id=REMOVE_ALL_MESSAGES)] + keep})
        snapshot = get_graph().get_state(config)
    return snapshot.values if snapshot else {}


def pending_approval(config: dict) -> Optional[dict]:
    """Returns the interrupt() payload if the graph is currently paused
    awaiting job-approval (see submit_draft in tools.py), else None. Reading
    this from `get_state` rather than an invoke() return value means it
    survives across page reloads -- e.g. the user reloading the browser
    while a job is pending approval still sees the approval card.

    Lock-free, like read_state above and for the same reasons -- and it
    matters most here: job_watcher calls this once per thread on every poll
    tick, so under the old lock one conversation's long turn stalled the
    entire watcher, delaying job-finished notices on every OTHER conversation
    too."""
    snapshot = get_graph().get_state(config)
    if snapshot and snapshot.interrupts:
        return snapshot.interrupts[0].value
    return None


def draft_hold_reason(config: dict) -> Optional[str]:
    """Why the job watcher must not speak into this conversation right now,
    or None if it may.

    Returns `"approval"` when an approval card is open and `"draft"` when a
    drafting exchange is live, which are the two halves of "the user is in
    the middle of assembling a calculation". The distinction is only for the
    log line; both hold.

    **Why a summary must wait rather than just being badly timed.** The
    watcher does not append a message, it starts a real agent turn. Invoking
    the graph with new input while it sits at submit_draft's `interrupt()`
    discards the pending approval task: `snapshot.interrupts` goes from one
    to zero, `next` goes from `("tools",)` to `()`, the submit_draft tool
    call is left permanently unanswered in the transcript, and a later
    resume with the user's approval is a silent no-op. So the card does not
    reappear afterwards -- it is gone, and the only evidence is the user
    asking where it went. That is measured behaviour, not a reading of the
    library's contract; see tests/backend/draft_01_summary_defer.py.

    The `"draft"` half covers the elicitation back-and-forth *before* any
    card exists ("which basis set?" and the answer), which has no interrupt
    to detect and was completely unguarded. `job_draft` cannot be used for
    this: nothing ever clears it, so it is set forever after a
    conversation's first draft (see CLEAR_DRAFT in app/agent/state.py).

    An approval hold has no expiry -- a card stays a card until someone
    answers it. A drafting hold expires after DRAFT_HOLD_SECONDS measured
    from the last draft mutation, so a draft that is simply abandoned does
    not suppress every summary in that conversation for good. `0` disables
    that escape and holds strictly.

    Lock-free, like read_state and pending_approval above and for the same
    reason: the watcher calls this once per conversation every two seconds,
    and taking the graph lock here would stall every other conversation's
    notices behind whichever turn is slowest. Being lock-free is also what
    makes it safe to call from *inside* the lock, which invoke_turn_if_idle
    below does.
    """
    snapshot = get_graph().get_state(config)
    if snapshot is None:
        return None
    if snapshot.interrupts:
        return "approval"
    status = (snapshot.values or {}).get("draft_status") or {}
    if status.get("stage") != "drafting":
        return None
    started_at = status.get("at")
    if DRAFT_HOLD_SECONDS <= 0 or not isinstance(started_at, (int, float)):
        return "draft"
    return "draft" if time.time() - started_at < DRAFT_HOLD_SECONDS else None


def invoke_turn_if_idle(input_dict: dict, config: dict, on_start=None) -> Optional[dict]:
    """invoke_turn, but it re-checks draft_hold_reason **while holding the
    thread lock** and declines to run rather than interrupting a draft.

    Checking before taking the lock is not enough, and that is the whole
    reason this function exists rather than an `if` in the caller. A
    drafting turn takes 53 to 77 seconds (measured, see _trim_history), the
    watcher polls every two seconds, so it takes roughly thirty snapshots
    *inside* that turn. Every one of them reads a state where the draft and
    the interrupt are not committed yet, sees nothing to hold for, blocks
    here on the lock, and is released the instant the user's turn commits
    its approval card -- at which point it invokes and destroys it. That is
    not a narrow race; it is the ordinary path, and it fired four or five
    times in the conversation that prompted this.

    Returns None when it declined, so the caller can leave the job unseen
    and try again on its next tick. `on_start` (optional) is called once the
    lock is held and the check has passed, i.e. only when a turn is really
    about to run -- the watcher uses it to announce the turn without
    announcing turns that never happen.
    """
    with _lock_for_thread(config):
        if draft_hold_reason(config) is not None:
            return None
        if on_start is not None:
            on_start()
        return get_graph().invoke(input_dict, config)


# --- Chat-history storage accounting/purging (app/auth/storage_quota.py) ---
#
# Both functions below are Postgres-backend-only (silent no-op/{} under the
# local-dev SqliteSaver backend, matching every other DATABASE_URL-gated
# degrade-to-no-op elsewhere in the auth layer -- see e.g.
# app/auth/ownership.py's module docstring) -- "chat history storage" as a
# quota concept only exists once a real multi-user Postgres checkpointer is
# in play; SqliteSaver's single local file has no per-thread accounting to
# do and nothing in this app currently needs one.
_CHECKPOINT_TABLES = ("checkpoints", "checkpoint_blobs", "checkpoint_writes")


def _require_pg_pool() -> Optional[ConnectionPool]:
    if not DATABASE_URL:
        return None
    _get_checkpointer()  # ensures _pg_pool is built and .setup() has run
    return _pg_pool


def all_thread_checkpoint_bytes() -> dict[str, int]:
    """thread_id -> approximate on-disk bytes of its checkpoint rows, summed
    across all three checkpoint tables. pg_column_size() is an estimate (it
    doesn't account for TOAST compression/storage overhead the way `du`
    would), but consistent enough to rank threads oldest-heaviest for quota
    purposes -- the same estimate-not-ground-truth tradeoff
    app/chemistry/jobs/quota.py already accepts for job directory sizes.
    A plain unlocked read (Postgres MVCC hands back one consistent
    snapshot across the three queries) -- deliberately not run inside any
    per-thread lock, since it spans every thread_id at once and is read-
    only. Covers every thread_id with checkpoint rows on disk, including
    one with no matching app/agent/threads.py registry entry (e.g. from a
    thread deleted before delete_thread_checkpoints existed), so nothing
    durably escapes the global storage total app/auth/storage_quota.py
    computes from this."""
    pool = _require_pg_pool()
    if pool is None:
        return {}
    totals: dict[str, int] = {}
    with pool.connection() as conn:
        for table in _CHECKPOINT_TABLES:
            rows = conn.execute(
                f"SELECT thread_id, SUM(pg_column_size(t.*)) AS bytes FROM {table} t GROUP BY thread_id"
            ).fetchall()
            for r in rows:
                totals[r["thread_id"]] = totals.get(r["thread_id"], 0) + int(r["bytes"] or 0)
    return totals


def delete_thread_checkpoints(thread_id: str) -> None:
    """Actually frees a thread's checkpoint storage -- closes a
    pre-existing, documented gap: app/agent/threads.py's own
    delete_thread() only ever removed a conversation from the visible
    registry, never the underlying checkpoint rows, so "deleting" a
    conversation never freed any storage at all. Takes this thread_id's
    own per-thread lock (the same one invoke_turn/resume_turn use) so this
    can't race an in-flight turn on the same conversation into leaving a
    half-written checkpoint behind. Table names are a fixed constant
    tuple, never caller-supplied, so the f-string below carries no
    injection risk despite not being a parameterized value."""
    pool = _require_pg_pool()
    if pool is None:
        return
    config = {"configurable": {"thread_id": thread_id}}
    with _lock_for_thread(config):
        with pool.connection() as conn:
            for table in _CHECKPOINT_TABLES:
                conn.execute(f"DELETE FROM {table} WHERE thread_id = %s", (thread_id,))
