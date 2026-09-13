"""Conversation (chat thread) CRUD, backed by app/agent/threads.py's flat
JSON registry -- see that module's docstring for why it's separate from
the LangGraph checkpoint sqlite db.

Ownership (app/auth/ownership.py) is layered on top without touching that
registry's own schema: every handler resolves the caller (None if auth
isn't configured for this deployment, in which case every function below
no-ops back to today's unrestricted single-user behavior), records
ownership on create, checks it before mutating/deleting a specific thread,
and filters the list route to the caller's own threads."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

from app.agent import threads as thread_registry
from app.agent.graph import delete_thread_checkpoints
from app.auth import models as auth_models
from app.auth.ownership import check_owner_or_admin, current_user_or_none, owned_ids_filter, record
from server.schemas import CreateThreadIn, RenameThreadIn, SetPinnedIn

from server.routes._paging import paged

router = APIRouter()


@router.get("/api/threads")
def list_threads(request: Request, offset: int = 0, limit: int | None = None):
    """Opt-in paging; see server/routes/_paging.py for why the default is
    still the whole list."""
    user = current_user_or_none(request)
    all_threads = thread_registry.list_threads()
    owned = owned_ids_filter("thread", user)
    if owned is not None:
        all_threads = [t for t in all_threads if t["thread_id"] in owned]
    return paged(all_threads, offset, limit)


@router.post("/api/threads", status_code=201)
def create_thread(body: CreateThreadIn, request: Request):
    user = current_user_or_none(request)
    thread = thread_registry.create_thread(body.label or "")
    record("thread", thread["thread_id"], user)
    return thread


@router.patch("/api/threads/{thread_id}")
def rename_thread(thread_id: str, body: RenameThreadIn, request: Request):
    user = current_user_or_none(request)
    check_owner_or_admin("thread", thread_id, user)
    ok = thread_registry.rename_thread(thread_id, body.label)
    if not ok:
        raise HTTPException(status_code=404, detail=f"No such conversation: {thread_id}")
    return thread_registry.get_thread(thread_id)


@router.patch("/api/threads/{thread_id}/pin")
def set_thread_pinned(thread_id: str, body: SetPinnedIn, request: Request):
    user = current_user_or_none(request)
    check_owner_or_admin("thread", thread_id, user)
    ok = thread_registry.set_pinned(thread_id, body.pinned)
    if not ok:
        raise HTTPException(status_code=404, detail=f"No such conversation: {thread_id}")
    return thread_registry.get_thread(thread_id)


@router.delete("/api/threads/{thread_id}")
def delete_thread(thread_id: str, request: Request):
    user = current_user_or_none(request)
    check_owner_or_admin("thread", thread_id, user)
    ok = thread_registry.delete_thread(thread_id)
    if not ok:
        raise HTTPException(status_code=404, detail=f"No such conversation: {thread_id}")
    # Actually frees the underlying chat-history storage (Postgres backend
    # only -- a no-op under local-dev SqliteSaver) and drops the ownership
    # row so it stops counting toward this user's storage quota -- see
    # graph.py's delete_thread_checkpoints docstring for the gap this
    # closes (thread_registry.delete_thread alone never freed anything).
    delete_thread_checkpoints(thread_id)
    if user is not None:
        auth_models.forget_ownership("thread", thread_id)
    return {"deleted": True}
