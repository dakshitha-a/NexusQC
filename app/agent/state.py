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
    if more than one Command in the same step writes to it (observed under
    the pre-rebuild design: two submit_job calls in one turn, both resolving
    the same unset molecule and each returning it in their own Command's
    update -- the same batched-write shape is possible today via two
    set_geometry calls in one turn). molecule is a wholesale replacement,
    not something to merge, so when multiple writes land in one step, just
    keep the most recent one (they're normally identical anyway -- same
    molecule resolved twice).
    """
    if new is None:
        return current
    if new is CLEAR_MOLECULE or new == CLEAR_MOLECULE:
        return None
    return new


def _molecule_frames_reducer(current: list, new) -> list:
    """Reducer for molecule_frames: an append-only log of every molecule
    the user has explicitly set (via the set_geometry tool, or a direct
    state write for a sketched/uploaded molecule -- see graph.py), each a
    small {"id", "molecule", "description"} dict -- the molecule panel's
    frame slider reads this list directly.
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
"""Sentinel that would discard the `job_draft` outright. Same reason
`molecule` needs CLEAR_MOLECULE rather than a plain None: None is the
reducer's "nothing written this step" signal, so it cannot also mean
"clear".

**Nothing currently writes it.** This docstring used to claim submit_draft
and start_job_draft did; they never have. `_finish_submission` leaves
`job_draft` untouched on both the approval and the rejection branch, and
`_draft_command` only ever overwrites it, so a draft outlives its own
submission and is replaced rather than cleared by the next
start_job_draft. That is deliberate and worth keeping: a draft that
survives a rejection is what lets the user say "use cc-pvdz instead" and
have update_job_draft amend the thing they just declined.

The consequence matters elsewhere, which is why it is spelled out here. A
non-empty `job_draft` does NOT mean a draft is currently being assembled;
it is true forever after a conversation's first draft. Anything that needs
to know whether a drafting exchange is live must read `draft_status`
below, never this field."""


CLEAR_DRAFT_STATUS = {"__cleared__": True}
"""Sentinel passed as the `draft_status` update to end a drafting episode
-- written by `_finish_submission` on both of its branches, since a
submission and a rejection are the two ways a draft ends. Same
None-already-means-no-write reasoning as CLEAR_MOLECULE and CLEAR_DRAFT."""


def _last_draft_status(current: Optional[dict], new) -> Optional[dict]:
    """Reducer for draft_status.

    Needed for exactly the reason `_last_draft` documents: an un-Annotated
    key uses LangGraph's default LastValue channel, which *errors* when
    more than one Command in the same step writes it, and this field is
    written by the same tools `job_draft` is -- so a model emitting two
    update_job_draft calls in one batch would raise here too.
    """
    if new is None:
        return current
    if new is CLEAR_DRAFT_STATUS or new == CLEAR_DRAFT_STATUS:
        return None
    return new


def _last_draft(current: Optional[dict], new) -> Optional[dict]:
    """Reducer for job_draft.

    Exists for the reason `_last_molecule` documents at length: a plain,
    un-Annotated key uses LangGraph's default LastValue channel, which
    *errors* rather than overwriting when more than one Command in the
    same step writes it (that's the same pre-rebuild submit_job observation
    `_last_molecule` cites), and two draft mutations in one turn is more
    likely than that, not
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
    If the model issues two submit_draft calls in the same turn (e.g. two
    already-built drafts for "run a single point and a frequency calc on
    water"), both tool calls read the same pre-batch state and each returns
    its own [*existing, new_id] list;
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


def _append_submissions(current: list[dict], new) -> list[dict]:
    """Reducer for pending_submissions, and for pending_rejections, which
    is the same shape of one-step handoff and wants the same behaviour.

    Appending rather than LastValue for exactly the reason
    `_append_job_ids` documents: an un-Annotated key *errors* when two
    Commands write it in the same step, and two submit_draft calls landing
    in one batch is the case that reducer already exists to survive.

    Clearing goes through the `{"__replace__": [...]}` escape hatch that
    `_molecule_frames_reducer` established for list-valued slots, rather
    than a new CLEAR_* sentinel: those exist for single-value slots where
    None is ambiguous, and a list already has the idiom.
    """
    if new is None:
        return current or []
    if isinstance(new, dict) and "__replace__" in new:
        return new["__replace__"]
    return [*(current or []), *new]


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
    # The second ("end") geometry for a two-molecule pes_scan, set via
    # set_geometry(role="end") -- the same tool that writes `molecule`
    # above, just a different role argument, same reducer, same
    # CLEAR_MOLECULE-sentinel semantics -- kept as its own state slot
    # rather than overloading `molecule`, since a scan needs both endpoints
    # live in state at once (submit_draft never does its own network-backed
    # molecule resolution; both endpoints must already be resolved before
    # it's ever called -- see docs/ARCHITECTURE.md's "The approval gate").
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
    # Whether a drafting exchange is live right now, as
    # {"stage": "drafting", "at": <epoch seconds>} or absent. Written by
    # `_draft_command` (the one funnel start_job_draft and update_job_draft
    # both go through) and cleared by `_finish_submission` on both its
    # branches, so it spans exactly the period between "the user asked for a
    # calculation" and "they approved or declined it".
    #
    # This exists because a finished job's summary must not interrupt that
    # period. The watcher starts a real agent turn to write a summary, and
    # invoking the graph with new input while it sits at submit_draft's
    # interrupt() discards the pending approval task: the card vanishes, the
    # submit_draft tool call is left permanently unanswered, and a later
    # resume is a silent no-op. Measured, not inferred -- see
    # tests/backend/draft_01_summary_defer.py.
    #
    # `job_draft` cannot answer this question (see CLEAR_DRAFT above), and
    # the timestamp lives in here rather than being read off the thread
    # registry's `last_active_at` because the watcher bumps that itself when
    # it writes a failed-job notice, which would restart the abandoned-draft
    # timer on a draft nobody was working on any more.
    draft_status: NotRequired[Annotated[Optional[dict], _last_draft_status]]
    # Receipts for jobs that started in the tool step that just finished, as
    # [{"tool_call_id", "job_id", "label", "engine", "edited", "follow_up"}].
    # A ONE-STEP HANDOFF, not durable state: written only by
    # `_finish_submission`'s success branch, read only by graph.py's
    # `job_submitted` node, and cleared by that same node in the step it is
    # consumed. It is not a second `active_job_ids` -- that field is the
    # conversation's durable record of what it submitted, this one exists
    # solely so the confirmation message can be written without the model.
    #
    # Deliberately carries no spec or params. Everything here is
    # checkpointed on every later step of the conversation, and the label is
    # the only part the message needs.
    #
    # A mixed batch (a submission alongside some other tool) routes to the
    # model instead and leaves its receipt behind uncleared. That residue is
    # inert by construction, because the router keys on this step's
    # tool_call_ids and those are unique -- see `_submissions_this_step` in
    # graph.py. Chasing it would mean teaching `_agent_node` about this
    # field, and its empty-history early return would skip the cleanup
    # anyway.
    pending_submissions: NotRequired[Annotated[list[dict], _append_submissions]]
    # Whether the submission just confirmed should hand back to the model
    # rather than ending the turn -- true when the user asked for further
    # calculations that have not been drafted yet, which is a thing only the
    # model knows (it arrives as submit_draft's `follow_up_work` argument).
    #
    # Written by the `job_submitted` node, read by `_after_job_submitted` on
    # the very next hop, and read nowhere else. A stale value is inert by
    # construction: the only reader runs immediately after the only writer,
    # which always writes it fresh. That is why there is no clear path for
    # it, unlike `pending_submissions` above.
    submission_follow_up: NotRequired[bool]
    # Receipts for approval cards the user DECLINED in the tool step that
    # just finished, as [{"tool_call_id", "label", "follow_up"}]. The exact
    # mirror of `pending_submissions` above, written only by
    # `_finish_submission`'s rejection branch, read and cleared by graph.py's
    # `job_rejected` node in the step it is consumed, and keyed on
    # tool_call_id for the same reason: the router has to be able to tell
    # that THIS step's tool results were all rejections. A batch mixing a
    # rejection with anything else -- including with a submission, since the
    # two receipts live in different slots -- leaves both lists short of the
    # trailing ids and so falls through to the model, which is correct.
    #
    # No job id, because a declined job was never submitted and has none.
    # The label is built from the spec the card showed rather than resolved
    # from disk, since nothing was ever written there.
    pending_rejections: NotRequired[Annotated[list[dict], _append_submissions]]
    # The rejection-side twin of `submission_follow_up`, with the same
    # one-writer-one-reader lifetime and the same reason for having no clear
    # path. A rejection can land in the middle of a multi-part request just
    # as a submission can, so declining one job must not truncate the answer
    # to whatever else the user asked in the same breath.
    rejection_follow_up: NotRequired[bool]
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
    # What search_active_space_literature found, kept so the active-space
    # job that follows can carry it into `literature_notes` and so the
    # result report can be reconciled against it. In state rather than left
    # in the transcript for the same reason job_draft is: a claim the model
    # would otherwise have to remember forty messages later is exactly the
    # claim it forgot in the conversation this was built from, where an
    # (8e,8o) literature argument and a (4e,4o) computed result coexisted
    # in one thread with nothing connecting them.
    active_space_literature: NotRequired[Optional[dict]]
