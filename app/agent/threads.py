"""Conversation (chat thread) registry.

LangGraph's SqliteSaver checkpoints conversation state keyed by thread_id,
but has no notion of "list all conversations" or a human-readable label --
that's this module's job, backing the React frontend's conversation-history
sidebar. Deliberately a separate flat JSON file (data/threads.json) rather
than a table inside the checkpoint sqlite db, so it needs no coordination
with graph.py's _graph_lock/SqliteSaver at all.
"""
from __future__ import annotations

import json
import os
import threading
import time
import uuid
from typing import Optional

from app.config import THREADS_FILE

_lock = threading.Lock()


def _atomic_write_text(text: str) -> None:
    """Write via a temp file + rename so a concurrent reader never observes
    a truncated/partial file -- same pattern as
    app/chemistry/jobs/base.py's _atomic_write_text."""
    tmp = THREADS_FILE.with_suffix(THREADS_FILE.suffix + f".tmp{os.getpid()}")
    tmp.write_text(text)
    os.replace(tmp, THREADS_FILE)


def _read_all() -> list[dict]:
    if not THREADS_FILE.exists():
        return []
    try:
        return json.loads(THREADS_FILE.read_text())
    except json.JSONDecodeError:
        return []


def _write_all(threads: list[dict]) -> None:
    _atomic_write_text(json.dumps(threads, indent=2))


def list_threads() -> list[dict]:
    """Returns every conversation, most-recently-active first."""
    with _lock:
        threads = _read_all()
    return sorted(threads, key=lambda t: t["last_active_at"], reverse=True)


def get_thread(thread_id: str) -> Optional[dict]:
    with _lock:
        for t in _read_all():
            if t["thread_id"] == thread_id:
                return t
    return None


def create_thread(label: str = "") -> dict:
    now = time.time()
    entry = {
        "thread_id": uuid.uuid4().hex,
        "label": label or "New conversation",
        "created_at": now,
        "last_active_at": now,
        "active_job_ids": [],
    }
    with _lock:
        threads = _read_all()
        threads.append(entry)
        _write_all(threads)
    return entry


def set_active_job_ids(thread_id: str, active_job_ids: list[str]) -> None:
    """Mirrors AgentState.active_job_ids (see app/agent/state.py) into the
    registry so job_watcher.py can learn which jobs belong to which
    conversation via a plain disk read, never through
    graph.py's read_state()/_graph_lock -- job-status polling must not
    share a lock with in-flight chat turns, or a job-stats update for any
    open conversation would stall behind the slowest LLM call happening
    anywhere in the process. MUST be called by every code path that calls
    invoke_turn()/resume_turn() and gets back a state dict with a
    (possibly changed) active_job_ids -- i.e. server/routes/chat.py's
    message and approval handlers, and job_watcher's own retry-notice
    injection. Silently a no-op if thread_id isn't registered, matching
    touch_thread's behavior."""
    with _lock:
        threads = _read_all()
        for t in threads:
            if t["thread_id"] == thread_id:
                t["active_job_ids"] = list(active_job_ids)
                _write_all(threads)
                return


def rename_thread(thread_id: str, label: str) -> bool:
    """Returns True if the thread existed and was renamed, False if no
    such thread_id is in the registry."""
    with _lock:
        threads = _read_all()
        for t in threads:
            if t["thread_id"] == thread_id:
                t["label"] = label
                _write_all(threads)
                return True
        return False


def touch_thread(thread_id: str) -> None:
    """Bumps last_active_at to now, e.g. on a new chat message or
    job/approval activity for this thread, so the conversation list can
    sort by recency. Silently a no-op if thread_id isn't registered --
    callers (job_watcher, chat routes) shouldn't have to special-case a
    thread that predates this registry or was already deleted."""
    with _lock:
        threads = _read_all()
        for t in threads:
            if t["thread_id"] == thread_id:
                t["last_active_at"] = time.time()
                _write_all(threads)
                return


def delete_thread(thread_id: str) -> bool:
    """Removes a conversation from the registry (i.e. from the visible
    conversation list). Does NOT purge the underlying LangGraph checkpoint
    rows for that thread_id -- whether that's even possible depends on
    whether the installed langgraph version's SqliteSaver exposes a
    thread-delete method, which this module doesn't assume. Removing it
    from the registry is sufficient for it to disappear from the sidebar;
    actual checkpoint-row cleanup is a documented follow-up, not done here.
    Returns True if a thread was actually removed, False if thread_id
    wasn't in the registry."""
    with _lock:
        threads = _read_all()
        remaining = [t for t in threads if t["thread_id"] != thread_id]
        if len(remaining) == len(threads):
            return False
        _write_all(remaining)
        return True
