"""Graph state for the computational-chemistry agent.

Kept deliberately small: `messages` drives the ReAct tool-calling loop,
while `molecule` and `active_job_ids` are side-channel state that tools
update via `Command(update=...)` so the Streamlit UI can render the current
structure / poll running jobs without re-parsing the conversation.
"""
from __future__ import annotations

from typing import Annotated, Optional

from typing_extensions import NotRequired, TypedDict

from langgraph.graph.message import add_messages


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
    return new if new is not None else current


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
    active_job_ids: NotRequired[Annotated[list[str], _append_job_ids]]
