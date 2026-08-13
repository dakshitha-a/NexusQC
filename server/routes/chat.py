"""Chat: conversation state, message submission, SSE progress stream, and
job/tool approval resumption.

POST /messages returns 202 immediately and runs the turn on its own
background thread -- mirroring why stream_turn/stream_mode="updates" exists
over invoke_turn in the first place (app/main.py's chat-input handler), just
pushed one level further: instead of a Streamlit script blocking on the
generator, an HTTP client gets an immediate response and watches progress
arrive over GET /events. All graph-touching handlers are plain `def`, not
`async def` -- see server/main.py's module docstring for why.
"""
from __future__ import annotations

import threading

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from langchain_core.messages import HumanMessage

from app.agent import threads as thread_registry
from app.agent.graph import (
    invalidate_graph_cache, invoke_turn, pending_approval, read_state, resume_turn, stream_turn_tokens,
)
from app.agent.serialize import serialize_message, serialize_state
from server.schemas import JobApprovalIn, MessageIn, ToolApprovalIn
from server.sse import event_stream, hub

router = APIRouter()


def _config(thread_id: str) -> dict:
    return {"configurable": {"thread_id": thread_id}}


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


def _run_turn(thread_id: str, text: str) -> None:
    """Runs on its own background thread (see module docstring). Any
    exception here must not propagate anywhere -- there is no request
    context left to catch it -- so it's reported as an `error` SSE event
    instead, and the turn is simply left incomplete (the user can just
    send another message; nothing here corrupts persisted state, since
    LangGraph's checkpointer only commits state as of each completed node)."""
    config = _config(thread_id)
    try:
        for mode, payload in stream_turn_tokens({"messages": [HumanMessage(content=text)]}, config):
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
            # every normal node -- see app/main.py's identical guard.
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

        pending = pending_approval(config)
        if pending is not None:
            hub.publish(thread_id, {"type": "interrupt", "interrupt": pending})
    except Exception as e:
        hub.publish(thread_id, {"type": "error", "message": str(e)})
    finally:
        hub.publish(thread_id, {"type": "turn_complete"})


@router.post("/api/threads/{thread_id}/messages", status_code=202)
def post_message(thread_id: str, body: MessageIn):
    _require_thread(thread_id)
    threading.Thread(target=_run_turn, args=(thread_id, body.text), daemon=True).start()
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
