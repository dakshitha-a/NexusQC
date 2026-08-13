"""Conversation (chat thread) CRUD, backed by app/agent/threads.py's flat
JSON registry -- see that module's docstring for why it's separate from
the LangGraph checkpoint sqlite db."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException

from app.agent import threads as thread_registry
from server.schemas import CreateThreadIn, RenameThreadIn

router = APIRouter()


@router.get("/api/threads")
def list_threads():
    return thread_registry.list_threads()


@router.post("/api/threads", status_code=201)
def create_thread(body: CreateThreadIn):
    return thread_registry.create_thread(body.label or "")


@router.patch("/api/threads/{thread_id}")
def rename_thread(thread_id: str, body: RenameThreadIn):
    ok = thread_registry.rename_thread(thread_id, body.label)
    if not ok:
        raise HTTPException(status_code=404, detail=f"No such conversation: {thread_id}")
    return thread_registry.get_thread(thread_id)


@router.delete("/api/threads/{thread_id}")
def delete_thread(thread_id: str):
    ok = thread_registry.delete_thread(thread_id)
    if not ok:
        raise HTTPException(status_code=404, detail=f"No such conversation: {thread_id}")
    return {"deleted": True}
