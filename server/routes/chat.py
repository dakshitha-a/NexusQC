"""Chat: conversation state, message submission, SSE progress stream, and
job/tool approval resumption.

POST /messages returns 202 immediately and runs the turn on its own
background thread -- an HTTP client gets an immediate response and watches
progress arrive over GET /events instead of the request blocking until the
whole ReAct tool-calling loop finishes. All graph-touching handlers are
plain `def`, not `async def` -- see server/main.py's module docstring for
why.
"""
from __future__ import annotations

import threading

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from langchain_core.messages import HumanMessage

from app.agent import threads as thread_registry
from app.agent.graph import (
    clear_molecule, invalidate_graph_cache, invoke_turn, pending_approval, read_state, resume_turn,
    stream_turn_tokens,
)
from app.agent.serialize import serialize_message, serialize_state
from app.chemistry.jobs.summarize import job_context_summary
from server.schemas import JobApprovalIn, MessageIn, ToolApprovalIn
from server.sse import event_stream, hub

router = APIRouter()

# One threading.Event per in-flight turn, keyed by thread_id -- set by the
# "stop" endpoint below, polled by _run_turn's streaming loop. A plain dict
# (not per-request state) because the SSE-publishing turn runner and the
# stop request arrive on two different threads/requests with no other
# shared handle between them. Only one turn can be in flight per thread at
# a time (the composer disables sending while turnInProgress), so a fresh
# Event per turn (overwriting any stale entry) is sufficient -- no need to
# reference-count concurrent turns on the same thread_id.
_cancel_events: dict[str, threading.Event] = {}
_cancel_lock = threading.Lock()


def _register_cancel_event(thread_id: str) -> threading.Event:
    ev = threading.Event()
    with _cancel_lock:
        _cancel_events[thread_id] = ev
    return ev


def _pop_cancel_event(thread_id: str) -> None:
    with _cancel_lock:
        _cancel_events.pop(thread_id, None)


def _config(thread_id: str) -> dict:
    return {"configurable": {"thread_id": thread_id}}


_MAX_TITLE_LEN = 60


def _derive_title(text: str, state: dict) -> str:
    """Cheap, instant title derivation for a fresh conversation -- no LLM
    call (which would need its own llm.invoke() and can't safely run
    inside _run_turn's streaming loop, which already holds _graph_lock for
    the whole turn). A pasted XYZ/coordinate block makes an unreadable
    numeric title, so if the text doesn't read like ordinary prose
    (multi-line, or mostly digits) and this turn resolved a molecule with
    a real name, title on that instead."""
    cleaned = " ".join(text.split())
    looks_like_prose = "\n" not in text and sum(c.isdigit() for c in cleaned) < len(cleaned) * 0.3
    molecule = state.get("molecule") or {}
    if not looks_like_prose and molecule.get("name"):
        cleaned = molecule["name"]
    if len(cleaned) > _MAX_TITLE_LEN:
        cleaned = cleaned[:_MAX_TITLE_LEN].rsplit(" ", 1)[0] + "…"
    return cleaned or "New conversation"


def _require_thread(thread_id: str) -> None:
    if thread_registry.get_thread(thread_id) is None:
        raise HTTPException(status_code=404, detail=f"No such conversation: {thread_id}")


@router.get("/api/threads/{thread_id}/state")
def get_state(thread_id: str):
    _require_thread(thread_id)
    config = _config(thread_id)
    state = read_state(config)
    payload = serialize_state(state)
    payload["pending_approval"] = pending_approval(config)
    return payload


@router.post("/api/threads/{thread_id}/molecule/reset")
def reset_molecule(thread_id: str):
    """Clears the active molecule -- the molecule preview panel's reset
    button. Bypasses the chat/LLM turn machinery entirely (see
    clear_molecule()'s docstring in graph.py); still touches the thread
    registry so the sidebar's last-active ordering isn't stale."""
    _require_thread(thread_id)
    config = _config(thread_id)
    state = clear_molecule(config)
    thread_registry.touch_thread(thread_id)
    return serialize_state(state)


def _run_turn(thread_id: str, text: str, job_ids: list[str] | None = None) -> None:
    """Runs on its own background thread (see module docstring). Any
    exception here must not propagate anywhere -- there is no request
    context left to catch it -- so it's reported as an `error` SSE event
    instead, and the turn is simply left incomplete (the user can just
    send another message; nothing here corrupts persisted state, since
    LangGraph's checkpointer only commits state as of each completed node).

    job_ids come from the Job Manager's "Attach to prompt" action -- each
    is turned into its own preceding HumanMessage carrying that job's
    job_context_summary(), so the LLM sees the actual results without the
    frontend having to splice them into the user's own typed text (which
    would make the chat bubble show words the user never wrote). This is
    the same "synthetic HumanMessage with an explanatory prefix" pattern
    job_watcher.py already uses for its own injected retry notices."""
    config = _config(thread_id)
    messages = [
        HumanMessage(content=f"(attached job context, not typed by the user) {job_context_summary(jid)}")
        for jid in (job_ids or [])
    ]
    messages.append(HumanMessage(content=text))
    cancel_event = _register_cancel_event(thread_id)
    stopped = False
    try:
        for mode, payload in stream_turn_tokens({"messages": messages}, config):
            if cancel_event.is_set():
                # Breaking here drops the only reference to the generator
                # stream_turn_tokens returns, which (in CPython, immediately
                # and synchronously) closes it -- throwing GeneratorExit at
                # its suspended `yield from` and running that function's
                # `with _graph_lock:` __exit__, releasing the lock before
                # this loop's caller does anything else. We're always inside
                # the loop body here precisely because the generator just
                # yielded, i.e. it IS suspended at that point, so this is
                # always safe to do, not a race. This only takes effect at
                # the next yielded chunk though -- LangGraph's "messages"
                # stream mode yields per-token (confirmed empirically, see
                # stream_turn_tokens' docstring), so in practice this stops
                # within a token or two of the click during text generation,
                # but if the graph is mid-tool-call (e.g. an ORCA/BAGEL
                # subprocess actually running), that call still runs to
                # completion -- there's no way to hard-kill a synchronous
                # tool body from here, only to stop the turn from
                # continuing past it.
                stopped = True
                break
            if mode == "messages":
                # Per-token delta of the assistant's own text (see
                # stream_turn_tokens' docstring for the empirical
                # confirmation this yields real incremental content, not
                # one big chunk). Tool-call-only chunks have empty
                # content (tool_call_chunks instead) -- skip those, they
                # add nothing for the chat pane to render and the
                # corresponding tool call is already covered by the
                # agent_step/message events below once that node's
                # "updates" chunk arrives.
                msg_chunk, _metadata = payload
                if msg_chunk.content:
                    hub.publish(thread_id, {
                        "type": "token", "message_id": msg_chunk.id, "delta": msg_chunk.content,
                    })
                continue

            # mode == "updates": payload is {node_name: node_update}. A
            # node that calls interrupt() (submit_job, create_tool)
            # reports its update under "__interrupt__" as a tuple of
            # Interrupt objects, not a {"messages": [...]} dict like
            # every normal node -- guarded against below.
            # The interrupt itself is surfaced below via
            # pending_approval() once the stream ends. This "updates"
            # chunk still carries the FULL final AIMessage once the
            # agent node completes (shortly after its token deltas
            # finished streaming above) -- the frontend uses that to
            # reconcile/replace its progressively-built text with the
            # authoritative final message (correct id/tool_calls/etc.),
            # per the `message` event's role in the SSE contract.
            for node_name, node_update in payload.items():
                if node_name == "__interrupt__" or not isinstance(node_update, dict):
                    continue
                for m in node_update.get("messages", []):
                    if node_name == "agent" and getattr(m, "tool_calls", None):
                        for tc in m.tool_calls:
                            hub.publish(thread_id, {
                                "type": "agent_step", "node": "agent",
                                "tool_name": tc["name"], "phase": "started",
                            })
                    elif node_name == "tools":
                        hub.publish(thread_id, {
                            "type": "agent_step", "node": "tools",
                            "tool_name": getattr(m, "name", "?"), "phase": "finished",
                        })
                    hub.publish(thread_id, {"type": "message", "message": serialize_message(m)})

        state = read_state(config)
        thread_registry.set_active_job_ids(thread_id, state.get("active_job_ids", []))
        thread_registry.touch_thread(thread_id)

        entry = thread_registry.get_thread(thread_id)
        if entry is not None and entry.get("label") == "New conversation":
            thread_registry.rename_thread(thread_id, _derive_title(text, state))

        pending = pending_approval(config)
        if pending is not None:
            hub.publish(thread_id, {"type": "interrupt", "interrupt": pending})
    except Exception as e:
        hub.publish(thread_id, {"type": "error", "message": str(e)})
    finally:
        _pop_cancel_event(thread_id)
        hub.publish(thread_id, {"type": "turn_complete", "stopped": stopped})


@router.post("/api/threads/{thread_id}/messages", status_code=202)
def post_message(thread_id: str, body: MessageIn):
    _require_thread(thread_id)
    threading.Thread(target=_run_turn, args=(thread_id, body.text, body.job_ids), daemon=True).start()
    return {"accepted": True}


@router.post("/api/threads/{thread_id}/stop", status_code=202)
def stop_turn(thread_id: str):
    """Best-effort interrupt for a turn stuck in a tool-calling loop (e.g.
    the model repeatedly retrying submit_job with incomplete params) --
    lets the user regain the composer without waiting for the model to
    talk itself out of it. Sets a flag _run_turn polls at each streamed
    chunk rather than killing its thread outright (Python has no safe way
    to do that): this stops the turn from continuing past whatever
    node/token is currently in flight, it does not abort an in-progress
    tool call (e.g. a QC job submission already past its interrupt()) --
    see _run_turn's inline comment for why that's an acceptable trade-off
    here. A no-op (still 202) if no turn is currently running for this
    thread, so a doubled click or a late click racing turn_complete is
    harmless."""
    _require_thread(thread_id)
    with _cancel_lock:
        ev = _cancel_events.get(thread_id)
    if ev is not None:
        ev.set()
    return {"accepted": True}


@router.get("/api/threads/{thread_id}/events")
def get_events(thread_id: str):
    _require_thread(thread_id)
    return StreamingResponse(event_stream(thread_id), media_type="text/event-stream")


def _message_ids(state: dict) -> set:
    return {getattr(m, "id", None) for m in state.get("messages", [])}


def _publish_new_messages(thread_id: str, before_ids: set, after_state: dict) -> None:
    """resume_turn() is a single blocking .invoke() call (see graph.py's
    docstring on why resume stays non-streaming), so unlike _run_turn there
    are no incremental "updates" chunks to publish messages from as they
    happen -- the whole post-resume tail of the turn (the tool's own
    ToolMessage confirming the job/tool was created, plus any follow-up
    AIMessage commentary) only exists once resume_turn returns. Without
    this, a client whose approval action came from elsewhere (a different
    tab, or -- as this function's docstring's motivating case -- curl)
    would see the jobs table update via job_update but the chat transcript
    itself would silently miss those messages until the next full reload."""
    for m in after_state.get("messages", []):
        if getattr(m, "id", None) not in before_ids:
            hub.publish(thread_id, {"type": "message", "message": serialize_message(m)})


@router.post("/api/threads/{thread_id}/approvals/job")
def approve_job(thread_id: str, body: JobApprovalIn):
    _require_thread(thread_id)
    config = _config(thread_id)
    pending = pending_approval(config)
    if pending is None or pending.get("kind") != "job_approval":
        raise HTTPException(status_code=409, detail="No job approval is pending on this conversation.")

    before_ids = _message_ids(read_state(config))
    resume_value = (
        {"approved": True, "spec": pending["spec"], "input_text": body.input_text}
        if body.approved else {"approved": False}
    )
    try:
        state = resume_turn(resume_value, config)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    thread_registry.set_active_job_ids(thread_id, state.get("active_job_ids", []))
    thread_registry.touch_thread(thread_id)
    _publish_new_messages(thread_id, before_ids, state)
    still_pending = pending_approval(config)
    hub.publish(thread_id, {"type": "interrupt", "interrupt": still_pending})
    hub.publish(thread_id, {"type": "turn_complete"})
    return {"resumed": True}


@router.post("/api/threads/{thread_id}/approvals/tool")
def approve_tool(thread_id: str, body: ToolApprovalIn):
    _require_thread(thread_id)
    config = _config(thread_id)
    pending = pending_approval(config)
    if pending is None or pending.get("kind") != "tool_approval":
        raise HTTPException(status_code=409, detail="No tool approval is pending on this conversation.")

    before_ids = _message_ids(read_state(config))
    resume_value = {"approved": True, "code": body.code} if body.approved else {"approved": False}
    try:
        state = resume_turn(resume_value, config)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    # Must run strictly after resume_turn() returns (releasing _graph_lock),
    # from this request-handling thread, not from inside the tool itself --
    # see the long comment on _graph_lock in app/agent/graph.py for why
    # calling this from within create_tool deadlocks for real.
    if body.approved:
        invalidate_graph_cache()

    _publish_new_messages(thread_id, before_ids, state)
    thread_registry.touch_thread(thread_id)
    still_pending = pending_approval(config)
    hub.publish(thread_id, {"type": "interrupt", "interrupt": still_pending})
    hub.publish(thread_id, {"type": "turn_complete"})
    return {"resumed": True}
