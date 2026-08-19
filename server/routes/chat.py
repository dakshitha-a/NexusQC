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

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from langchain_core.messages import AIMessageChunk, HumanMessage

from app.agent import threads as thread_registry
from app.agent.graph import (
    add_built_frame, clear_molecule, invoke_turn, pending_approval, read_state, remove_frame,
    remove_messages, set_active_frame, stream_resume_tokens, stream_turn_tokens,
)
from app.auth.ownership import check_owner_or_admin, current_user_or_none, record
from app.agent.serialize import serialize_message, serialize_state
from app.agent.troubleshoot import compose_troubleshoot_message
from app.chemistry.jobs.summarize import job_context_summary
from app.chemistry.jobs.validate import VALIDATED_ENGINES, validate_input
from app.chemistry.molecule import molecule_from_molblock
from server.schemas import JobApprovalIn, MessageIn, MoleculeBuildIn
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


def _require_thread(thread_id: str, request: Request) -> None:
    if thread_registry.get_thread(thread_id) is None:
        raise HTTPException(status_code=404, detail=f"No such conversation: {thread_id}")
    check_owner_or_admin("thread", thread_id, current_user_or_none(request))


@router.get("/api/threads/{thread_id}/state")
def get_state(thread_id: str, request: Request):
    _require_thread(thread_id, request)
    config = _config(thread_id)
    state = read_state(config)
    payload = serialize_state(state)
    payload["pending_approval"] = pending_approval(config)
    return payload


@router.post("/api/threads/{thread_id}/molecule/reset")
def reset_molecule(thread_id: str, request: Request):
    """Clears the active molecule AND the whole frame history -- the
    molecule preview panel's reset button. Bypasses the chat/LLM turn
    machinery entirely (see clear_molecule()'s docstring in graph.py);
    still touches the thread registry so the sidebar's last-active
    ordering isn't stale."""
    _require_thread(thread_id, request)
    config = _config(thread_id)
    state = clear_molecule(config)
    thread_registry.touch_thread(thread_id)
    return serialize_state(state)


@router.delete("/api/threads/{thread_id}/molecule/frames/{frame_id}")
def delete_molecule_frame(thread_id: str, frame_id: str, request: Request):
    """Deletes a single molecule frame -- the molecule panel's per-frame
    delete button. See remove_frame()'s docstring in graph.py; leaves the
    active molecule untouched even if the deleted frame was the one it was
    last set from."""
    _require_thread(thread_id, request)
    config = _config(thread_id)
    state = remove_frame(config, frame_id)
    thread_registry.touch_thread(thread_id)
    return serialize_state(state)


@router.post("/api/threads/{thread_id}/molecule/build")
def build_molecule(thread_id: str, body: MoleculeBuildIn, request: Request):
    """The molecule-builder's "use this structure" action: turns a 2D
    sketch (an exported molfile) into a relaxed 3D conformer and adds it as
    a new frame, active immediately -- see molecule_from_molblock (RDKit
    topology parsing + ETKDG/MMFF94) and add_built_frame (state write) for
    the actual work. Bypasses the chat/LLM turn machinery entirely, same as
    the other molecule-panel actions above: there's no ambiguity here for a
    model to resolve, the conformer is already fully generated by the time
    this returns. A malformed/empty sketch (molecule_from_molblock raises
    ValueError) comes back as a 400 the modal can show inline, rather than
    a raw 500."""
    _require_thread(thread_id, request)
    try:
        molecule = molecule_from_molblock(
            body.molblock, charge=body.charge, multiplicity=body.multiplicity,
        ).to_dict()
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    config = _config(thread_id)
    state, _frame = add_built_frame(config, molecule)
    thread_registry.touch_thread(thread_id)
    return serialize_state(state)


def _run_turn(
    thread_id: str, text: str, cancel_event: threading.Event,
    job_ids: list[str] | None = None, frame_id: str | None = None, owner_user_id: str | None = None,
) -> None:
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
    job_watcher.py already uses for its own injected retry notices.

    frame_id is the molecule panel's own "Attach to prompt" action -- see
    set_active_frame()'s docstring in graph.py for why activating it here
    (a direct state write, before this turn's messages are even built)
    rather than as a tool call is the right place: it must be deterministic
    and side-effect-free to redo, same constraint that keeps submit_job
    from resolving molecule_identifier itself.

    cancel_event is created and registered by post_message BEFORE it spawns
    this thread (not in here) -- registering it as this function's first
    line left a real race: post_message's HTTP response (and the
    optimistic UI update that makes the Stop button clickable) can reach
    the browser before the OS has even scheduled this new thread to run,
    so a fast Send-then-Stop could hit stop_turn's "no turn is running for
    this thread" no-op branch and silently do nothing. Registering
    synchronously in the request-handling thread closes that window."""
    config = _config(thread_id)
    frame_description = None
    if frame_id:
        _, frame = set_active_frame(config, frame_id)
        if frame is not None:
            frame_description = frame["description"]
    messages = [
        HumanMessage(content=f"(attached job context, not typed by the user) {job_context_summary(jid)}")
        for jid in (job_ids or [])
    ]
    if frame_description:
        messages.append(HumanMessage(
            content=f"(attached molecule frame, not typed by the user) The active molecule for this "
                    f"message has been set to: {frame_description}."
        ))
    messages.append(HumanMessage(content=text))
    before_ids = _message_ids(read_state(config))
    published_ids: set = set()
    stopped = False
    turn_input: dict = {"messages": messages}
    if owner_user_id is not None:
        # Written on every turn, not just the thread's first one -- a
        # plain (unreducered) AgentState field is only ever written once
        # per graph step by this one call site, never by a tool via
        # Command(update=...), so there's no multiple-writers-in-one-step
        # conflict the reducers in state.py exist to solve for other
        # fields. See AgentState.owner_user_id's docstring.
        turn_input["owner_user_id"] = owner_user_id
    try:
        for mode, payload in stream_turn_tokens(turn_input, config):
            if stopped or cancel_event.is_set():
                # Cancelled -- drain toward a safe stopping point instead
                # of breaking immediately. An earlier version broke here
                # right away (dropping the generator reference so
                # GeneratorExit would unwind stream_turn_tokens' `with
                # _graph_lock:`), which turned out to be unsafe. Confirmed
                # empirically: closing the generator does not actually
                # abort the node that's currently in flight once the turn
                # is past a tool-call boundary -- LangGraph keeps running
                # it to completion in the background regardless of whether
                # we're still consuming its output (GPU utilization stayed
                # pinned at ~95% for several seconds after the old
                # `break`), and the checkpoint ended up holding a complete
                # final AIMessage that was never published to the
                # frontend. Racing a "strip whatever's new" cleanup
                # against that still-writing background execution is what
                # caused a real "Attempting to delete a message with an ID
                # that doesn't exist" crash during this fix's own testing
                # -- the id we'd read had already been superseded by the
                # time the removal request reached the checkpoint.
                #
                # An "updates" chunk means the node that was already in
                # flight at the moment of cancellation has now fully
                # completed and had its checkpoint written -- that's the
                # safe point to actually stop at, before the graph would
                # otherwise start a NEW node (e.g. deciding to call a
                # second tool). Nothing from here on is published -- the
                # whole point of stopping is that the user never sees it
                # -- and the phantom-message cleanup below only ever runs
                # once we've reached this point, so it's never racing a
                # still-in-progress write.
                stopped = True
                if mode == "updates":
                    break
                continue
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
                #
                # "messages" mode yields a chunk for EVERY message any node
                # produces, not just the agent's own incremental text --
                # confirmed empirically that a completed ToolMessage (e.g.
                # search_knowledge_base's full result text) also comes
                # through here as a single non-incremental chunk with
                # `.content` set. Without the isinstance guard, that whole
                # blob got published as one giant "token" delta and briefly
                # rendered in the assistant's own streaming bubble as if it
                # had just typed the raw tool output -- restricting to
                # AIMessageChunk is what "the assistant's own text" above
                # actually requires.
                msg_chunk, _metadata = payload
                if isinstance(msg_chunk, AIMessageChunk) and msg_chunk.content:
                    hub.publish(thread_id, {
                        "type": "token", "message_id": msg_chunk.id, "delta": msg_chunk.content,
                    })
                continue

            # mode == "updates": payload is {node_name: node_update}. A
            # node that calls interrupt() (submit_job)
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
                    published_ids.add(getattr(m, "id", None))

        state = read_state(config)

        # A stopped turn's `break` above only stops US from consuming
        # further chunks -- it does NOT reliably abort the underlying
        # graph execution once it's past a tool-call boundary. Confirmed
        # empirically (not just inferred): with a search_knowledge_base
        # call in the turn, GPU utilization stayed pinned at ~95% for
        # several seconds AFTER stop() was called and turn_complete had
        # NOT yet fired, and the checkpoint ended up holding a complete,
        # well-formed final AIMessage that was never published over SSE
        # -- the frontend showed "Stopped." with a truncated bubble while
        # the full answer silently sat in state. Left alone, that hidden
        # message becomes part of the context for the user's NEXT turn,
        # which is what produced the "it uses both the new and the old
        # prompt" symptom this was written to fix: not the old, unanswered
        # HumanMessage remaining (that's normal, expected chat-app
        # behavior and stays untouched below), but an old, unseen
        # AIMessage/ToolMessage the user never approved of seeing.
        # Skipped when a real interrupt is now pending (rare -- would mean
        # the hidden continuation itself called submit_job):
        # that needs to surface normally like any other approval, not be
        # silently erased along with its triggering messages.
        pending = pending_approval(config)
        if stopped and pending is None:
            phantom_ids = [
                m.id for m in state.get("messages", [])
                if getattr(m, "id", None) not in before_ids
                and getattr(m, "id", None) not in published_ids
                and type(m).__name__ != "HumanMessage"
            ]
            if phantom_ids:
                state = remove_messages(config, phantom_ids)

        thread_registry.set_active_job_ids(thread_id, state.get("active_job_ids", []))
        thread_registry.touch_thread(thread_id)

        entry = thread_registry.get_thread(thread_id)
        if entry is not None and entry.get("label") == "New conversation":
            thread_registry.rename_thread(thread_id, _derive_title(text, state))

        if pending is not None:
            hub.publish(thread_id, {"type": "interrupt", "interrupt": pending})
    except Exception as e:
        hub.publish(thread_id, {"type": "error", "message": str(e)})
    finally:
        _pop_cancel_event(thread_id)
        hub.publish(thread_id, {"type": "turn_complete", "stopped": stopped})


@router.post("/api/threads/{thread_id}/messages", status_code=202)
def post_message(thread_id: str, body: MessageIn, request: Request):
    _require_thread(thread_id, request)
    # Resolved here (in the request-handling thread, where `request` is
    # available) and passed into _run_turn rather than re-resolved there --
    # _run_turn runs on its own background thread, started after this
    # handler has already returned a 202, with no request context left.
    owner_user_id = None
    user = current_user_or_none(request)
    if user is not None:
        owner_user_id = str(user["id"])
    # Registered here, synchronously, before the background thread is even
    # started -- see _run_turn's docstring for the race this closes.
    cancel_event = _register_cancel_event(thread_id)
    threading.Thread(
        target=_run_turn,
        args=(thread_id, body.text, cancel_event, body.job_ids, body.frame_id, owner_user_id),
        daemon=True,
    ).start()
    return {"accepted": True}


@router.post("/api/threads/{thread_id}/troubleshoot/{job_id}", status_code=202)
def troubleshoot_job(thread_id: str, job_id: str, request: Request):
    """Start an investigation of a failed job, at the user's request.

    This is the whole of what replaced auto-retry. A failed job writes a
    notice into the conversation and stops (see app/agent/job_watcher.py);
    nothing investigates anything until someone presses Troubleshoot, which
    lands here.

    Deliberately routed through `_run_turn` -- the same path a typed
    message takes -- rather than a bespoke turn runner. That is what gives
    it the thread lock, the turn_start/turn_complete SSE bracketing, the
    stop button, and interrupt handling for the approval card the
    investigation may end in, none of which would exist in a second
    implementation. It is also deliberately NOT in server/routes/jobs.py,
    which must stay lock-free so job polling never stalls behind a chat
    turn.

    The message itself is composed mechanically from the job's own output
    (see app/agent/troubleshoot.py), so the evidence the model reasons
    about is gathered by code rather than chosen by the model.
    """
    _require_thread(thread_id, request)
    text = compose_troubleshoot_message(job_id)
    if text is None:
        # Not a failed job -- a completed one, a cancelled one, or an id
        # that no longer exists. A 409 rather than a 404 because the job
        # may well exist and simply not be in a state to troubleshoot,
        # and the frontend should say so rather than silently doing
        # nothing.
        raise HTTPException(
            status_code=409,
            detail="That job did not fail, so there is nothing to troubleshoot.",
        )
    owner_user_id = None
    user = current_user_or_none(request)
    if user is not None:
        owner_user_id = str(user["id"])
    cancel_event = _register_cancel_event(thread_id)
    threading.Thread(
        target=_run_turn,
        args=(thread_id, text, cancel_event, None, None, owner_user_id),
        daemon=True,
    ).start()
    return {"accepted": True}


@router.post("/api/threads/{thread_id}/stop", status_code=202)
def stop_turn(thread_id: str, request: Request):
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
    _require_thread(thread_id, request)
    with _cancel_lock:
        ev = _cancel_events.get(thread_id)
    if ev is not None:
        ev.set()
    return {"accepted": True}


@router.get("/api/threads/{thread_id}/events")
def get_events(thread_id: str, request: Request):
    _require_thread(thread_id, request)
    return StreamingResponse(event_stream(thread_id), media_type="text/event-stream")


def _message_ids(state: dict) -> set:
    return {getattr(m, "id", None) for m in state.get("messages", [])}


def _publish_new_messages(thread_id: str, before_ids: set, after_state: dict) -> None:
    """Publishes any message in `after_state` the client hasn't seen.

    A backstop, since F-008: the resume path now streams and publishes
    messages as they arrive (see _stream_resume), so in the normal case
    this finds nothing left to send. It still runs because the streaming
    loop can miss a message if the generator raises partway, and because a
    client whose approval action came from somewhere else entirely (a
    different tab, or curl) would otherwise see the jobs table update via
    job_update while the chat transcript silently missed those messages
    until the next full reload. `published_ids` is folded into
    `before_ids` by the caller so nothing is published twice.
    """
    for m in after_state.get("messages", []):
        if getattr(m, "id", None) not in before_ids:
            hub.publish(thread_id, {"type": "message", "message": serialize_message(m)})


def _stream_resume(thread_id: str, resume_value: dict, config: dict) -> tuple[dict, set]:
    """Resumes an interrupted turn, publishing tool progress and token
    deltas as they happen. Returns (final state, ids already published).

    F-008: this replaces a single blocking `resume_turn()` on the approval
    path. Everything after the click -- submit_job's own resumed tool call,
    then the follow-up LLM turn that summarises the submission -- used to
    run with the UI showing nothing at all, for several seconds, on a click
    the user had just made. The publishing rules are deliberately identical
    to _run_turn's, so an approval-resumed turn and an ordinary typed turn
    render the same way rather than being two subtly different streams.
    """
    published_ids: set = set()
    for mode, payload in stream_resume_tokens(resume_value, config):
        if mode == "messages":
            # Only the assistant's own incremental text -- a completed
            # ToolMessage also arrives here as one non-incremental chunk,
            # and publishing that as a "token" delta renders the raw tool
            # output inside the assistant's bubble. Same guard, same
            # reason, as _run_turn's own "messages" branch.
            msg_chunk, _metadata = payload
            if isinstance(msg_chunk, AIMessageChunk) and msg_chunk.content:
                hub.publish(thread_id, {
                    "type": "token", "message_id": msg_chunk.id, "delta": msg_chunk.content,
                })
            continue
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
                published_ids.add(getattr(m, "id", None))
    return read_state(config), published_ids


@router.post("/api/threads/{thread_id}/approvals/job")
def approve_job(thread_id: str, body: JobApprovalIn, request: Request):
    _require_thread(thread_id, request)
    config = _config(thread_id)
    pending = pending_approval(config)
    if pending is None or pending.get("kind") != "job_approval":
        raise HTTPException(status_code=409, detail="No job approval is pending on this conversation.")

    # F-023: validate a hand-edited input BEFORE resuming, not inside
    # submit_job after the graph has already restarted.
    #
    # The interrupt is a single-use resource: once resume_turn() runs, the
    # pause is spent. Validating inside the tool therefore rejected the bad
    # text but ALSO consumed the approval, so the user's corrected retry hit
    # a 409 ("No job approval is pending") and the whole turn had to be
    # redone. Checking here leaves the interrupt pending, so the card stays
    # up, the user fixes the typo in place and clicks again -- which is the
    # behavior CLAUDE.md has always described. It also gives scripted
    # clients a 400 with the actual errors instead of a 200 whose failure is
    # buried in a ToolMessage.
    #
    # method == "custom" is exempt for the same reason it is exempt inside
    # submit_job: that job_type exists to carry ORCA/BAGEL syntax this
    # validator was never built to recognize, so its findings are advisory
    # (see _build_custom_spec_or_error). The in-tool check stays as defense
    # in depth for any resume that does not come through this route.
    #
    # Gated on the ENGINE having a validator at all, not only on
    # method != "custom": validate_input raises ValueError for anything
    # outside {orca, bagel}, and PySCF is exactly that. The browser never
    # sends input_text for a PySCF approval (the card renders a read-only
    # <pre>), but a scripted client can -- and this route already treats
    # hand-crafted approval bodies as in scope. Unguarded, that raised
    # straight out of the handler as a 500. Post-interrupt it had been
    # harmless, since ToolNode catches a tool exception into a ToolMessage.
    if body.approved and body.input_text is not None:
        spec = pending.get("spec") or {}
        # Keyed on the v2 task, not on the runner key: `blind` is the
        # task whose whole purpose is carrying engine syntax this
        # validator was never built to read, so its findings are
        # advisory there. The `custom` runner-key check remains as the
        # fallback for a spec written before the taxonomy switch.
        is_blind = (spec.get("task") or "") == "blind" or spec.get("method") == "custom"
        if not is_blind and spec.get("engine") in VALIDATED_ENGINES:
            errors = validate_input(spec.get("engine", ""), body.input_text)
            if errors:
                # A plain string, not a nested object: lib/api.ts's request()
                # does `detail = body.detail ?? detail` and hands the result
                # straight to `new ApiError(status, detail)`, whose Error
                # superclass would stringify an object to "[object Object]".
                raise HTTPException(
                    status_code=400,
                    detail=(
                        f"The edited {spec.get('engine')} input was not run: "
                        f"{'; '.join(errors)}"
                    ),
                )

    before_state = read_state(config)
    before_ids = _message_ids(before_state)
    before_job_ids = set(before_state.get("active_job_ids", []))
    resume_value = (
        {"approved": True, "spec": pending["spec"], "input_text": body.input_text}
        if body.approved else {"approved": False}
    )
    try:
        # F-008: streams tool progress and token deltas while the resume
        # runs, instead of a blocking invoke() that left the UI silent for
        # the whole submit-plus-follow-up-turn.
        state, published_ids = _stream_resume(thread_id, resume_value, config)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    # SEC-07 defense-in-depth backstop, not the primary mechanism anymore:
    # JobManager.submit()/submit_scan() (app/chemistry/jobs/base.py) now
    # record ownership themselves, the instant each job's spec/status
    # become visible on disk -- before their own quota-enforcement pass,
    # before returning to submit_job (tools.py), and long before control
    # ever gets back up to this HTTP handler. owner_user_id is threaded
    # through from AgentState (set once per turn by _run_turn), which
    # survives the resume boundary intact. This loop still runs too
    # (record_ownership()'s ON CONFLICT DO NOTHING makes the redundant
    # write harmless) purely as a safety net for an edge case where
    # owner_user_id was somehow absent from state at tool-call time -- see
    # JobManager.submit()'s own docstring for the full reasoning, including
    # why "record it right after submit_job's own call returns" (an
    # earlier, less complete version of this fix) still wasn't early
    # enough.
    new_job_ids = set(state.get("active_job_ids", [])) - before_job_ids
    approver = current_user_or_none(request)
    for job_id in new_job_ids:
        record("job", job_id, approver)

    thread_registry.set_active_job_ids(thread_id, state.get("active_job_ids", []))
    thread_registry.touch_thread(thread_id)
    _publish_new_messages(thread_id, before_ids | published_ids, state)
    still_pending = pending_approval(config)
    hub.publish(thread_id, {"type": "interrupt", "interrupt": still_pending})
    hub.publish(thread_id, {"type": "turn_complete"})
    return {"resumed": True}
