"""Graph state for the computational-chemistry agent.

Kept deliberately small: `messages` drives the ReAct tool-calling loop,
while `molecule` and `active_job_ids` are side-channel state that tools
update via `Command(update=...)` so the frontend can render the current
structure / poll running jobs without re-parsing the conversation.
"""
from __future__ import annotations

from typing import Annotated, Optional

from typing_extensions import NotRequired, TypedDict

from langgraph.graph.message import add_messages


CLEAR_MOLECULE = {"__cleared__": True}
"""Sentinel passed as the `molecule` update to explicitly clear the active
molecule (see clear_molecule() in graph.py, used by the UI's reset
button). Plain `None` can't serve this purpose: it's the reducer's own
"nothing written this step" signal below, so an explicit `None` write
would be indistinguishable from no write at all and silently no-op."""


def _last_molecule(current: Optional[dict], new: Optional[dict]) -> Optional[dict]:
    """Reducer for molecule. A plain (un-Annotated) key uses LangGraph's
    default LastValue channel, which *errors* -- not silently overwrites --
    if more than one Command in the same step writes to it (observed: two
    submit_job calls in one turn, both resolving the same unset molecule
    and each returning it in their own Command's update). molecule is a
    wholesale replacement, not something to merge, so when multiple writes
    land in one step, just keep the most recent one (they're normally
    identical anyway -- same molecule resolved twice).
    """
    if new is None:
        return current
    if new is CLEAR_MOLECULE or new == CLEAR_MOLECULE:
        return None
    return new


def _molecule_frames_reducer(current: list, new) -> list:
    """Reducer for molecule_frames: an append-only log of every molecule
    the user has explicitly set (via set_molecule or generate_job_input's
    inline resolution), each a small {"id", "molecule", "description"}
    dict -- the molecule panel's frame slider reads this list directly.
    `new is None` keeps the current list (same "no write this step"
    convention as `_last_molecule`). A plain list of new frame dicts is
    appended (a tool only ever returns the frame(s) it just created, not
    the reconstructed full list -- same idea as `_append_job_ids`).
    Deleting a frame or resetting the whole panel can't be expressed as an
    append, though, so `new` may instead be `{"__replace__": [...]}` --
    an explicit escape hatch that wholesale-replaces the list (see
    remove_frame/clear_molecule in graph.py) rather than trying to encode
    "remove frame at id X" as something this reducer would have to
    interpret."""
    if new is None:
        return current or []
    if isinstance(new, dict) and "__replace__" in new:
        return new["__replace__"]
    return [*(current or []), *new]


CLEAR_DRAFT = {"__cleared__": True}
"""Sentinel passed as the `job_draft` update to discard the draft outright
-- written by submit_draft once a job has actually been submitted, and by
start_job_draft when a new draft replaces an abandoned one. Same reason
`molecule` needs CLEAR_MOLECULE rather than a plain None: None is the
reducer's "nothing written this step" signal, so it cannot also mean
"clear"."""


def _last_draft(current: Optional[dict], new) -> Optional[dict]:
    """Reducer for job_draft.

    Exists for the reason `_last_molecule` documents at length: a plain,
    un-Annotated key uses LangGraph's default LastValue channel, which
    *errors* rather than overwriting when more than one Command in the
    same step writes it. That was observed with two submit_job calls in one
    turn, and two draft mutations in one turn is more likely than that, not
    less -- a model answering "b3lyp with 6-31g*" in one breath can easily
    emit two update_job_draft calls in the same batch.

    A draft is a wholesale replacement rather than something to merge here:
    the tool that writes it has already merged its update into the draft it
    read, so the reducer's only job is to keep the most recent write when
    several land at once.
    """
    if new is None:
        return current
    if new is CLEAR_DRAFT or new == CLEAR_DRAFT:
        return None
    return new


def _append_job_ids(current: list[str], new: list[str]) -> list[str]:
    """Reducer for active_job_ids: without one, a key with no Annotated
    reducer is simply overwritten by whatever a Command's update contains.
    If the model issues two submit_job calls in the same turn (e.g. "run a
    single point and a frequency calc on water"), both tool calls read the
    same pre-batch state and each returns its own [*existing, new_id] list;
    the second Command to land would silently clobber the first's addition
    instead of both accumulating. This reducer concatenates instead, same
    idea as `add_messages` above -- tools only need to return the newly
    submitted id(s), not the full list.
    """
    current = current or []
    for job_id in new or []:
        if job_id not in current:
            current = [*current, job_id]
    return current


class AgentState(TypedDict):
    messages: Annotated[list, add_messages]
    # NotRequired, not just Optional[...]: on a brand-new thread these keys
    # are genuinely absent from state (nothing has set them yet), and
    # ToolNode validates injected `state` against a pydantic model derived
    # from this TypedDict before calling any tool -- plain Optional still
    # marks the key as required-but-nullable, so a first-ever turn on a
    # fresh conversation would fail that validation for every tool call
    # before the tool body ever runs. Code reads both via `.get(key, default)`
    # regardless, so this only affects the schema, not runtime behavior.
    molecule: NotRequired[Annotated[Optional[dict], _last_molecule]]
    # The second ("end") geometry for a two-molecule pes_scan, set via the
    # set_pes_scan_endpoint tool (a straight mirror of set_molecule/
    # `molecule` above, same reducer, same CLEAR_MOLECULE-sentinel
    # semantics) -- kept as its own state slot rather than overloading
    # `molecule`, since a scan needs both endpoints live in state at once
    # (submit_job never does its own network-backed molecule resolution;
    # both endpoints must already be resolved before it's ever called --
    # see its docstring).
    pes_scan_end_molecule: NotRequired[Annotated[Optional[dict], _last_molecule]]
    # Every molecule the user has explicitly set, in order -- backs the
    # molecule panel's frame slider/attach-to-prompt UI. Kept separate from
    # `molecule` (the current active geometry, unaffected by browsing older
    # frames) rather than derived from it, since `molecule` is a single
    # wholesale-replace slot with no history once overwritten.
    molecule_frames: NotRequired[Annotated[list[dict], _molecule_frames_reducer]]
    active_job_ids: NotRequired[Annotated[list[str], _append_job_ids]]
    # The job being assembled, in the v2 shape
    # {"task", "subtype", "method", "engine", "params"} -- written by
    # start_job_draft/update_job_draft and read back by submit_draft. It
    # lives in state rather than in the message history so that
    # `registry2.elicitation.validate_draft()` has something authoritative
    # to check: a draft reconstructed by re-reading the conversation would
    # be the model's account of what was agreed, which is exactly the
    # judgement this design takes away from it.
    job_draft: NotRequired[Annotated[Optional[dict], _last_draft]]
    # The conversation owner's user id (see app/auth/ownership.py), or
    # absent entirely on a deployment where auth isn't configured -- set
    # once by server/routes/chat.py's _run_turn on every turn (a plain,
    # unreducered field: only the route handler ever writes it, never a
    # tool via Command(update=...), so there's no multi-writer-in-one-step
    # concern the reducers above exist to solve). Read by
    # search_knowledge_base (app/rag/query_tool.py) to scope retrieval to
    # this user's own uploads plus shared content, so one user's chat can
    # never surface another user's private KB uploads.
    owner_user_id: NotRequired[str]
