"""Server-owned background service that detects newly-terminal jobs per
conversation and injects the appropriate system notice into that
conversation's next agent turn -- completed / needs-retry-under-budget /
retry-exhausted / cancelled. This is the server-owned replacement for
Streamlit's browser-driven `_jobs_fragment` (app/main.py) that the React
frontend needs: a browser tab closing must not silently stop auto-retry
working, and two open tabs on the same conversation must not both inject
the same retry (Streamlit's per-session `st.session_state["_seen_terminal_jobs"]`
had neither property). One thread, started once at server startup, walks
every conversation in the registry (app/agent/threads.py) rather than being
tied to any particular request/connection.

Deliberately reads job status via the lock-free `read_status`/`read_spec`/
`read_result` functions in app/chemistry/jobs/base.py, and learns which job
ids belong to which conversation via the registry's `active_job_ids` field
(kept in sync by every invoke_turn()/resume_turn() caller -- see
threads.set_active_job_ids's docstring) rather than calling
graph.read_state() on a timer. graph.py's `_graph_lock` is held for the
entire duration of a chat turn; polling job status through it would stall
every open conversation's job updates behind whichever turn is slowest,
which defeats the point of a background watcher (see CLAUDE.md's UI
architecture notes on why the polling fragment reads job status off disk
directly, same reasoning here).
"""
from __future__ import annotations

import json
import os
import threading
from pathlib import Path
from typing import Callable, Optional

from langchain_core.messages import HumanMessage

from app.agent import threads as thread_registry
from app.agent.graph import invoke_turn, pending_approval, read_state
from app.agent.serialize import serialize_message
from app.chemistry.jobs.base import MAX_AUTO_RETRIES, count_failed_in_chain, get_job_manager
from app.config import JOBS_DIR

_SEEN_DIR = JOBS_DIR / "_seen"
_SEEN_DIR.mkdir(parents=True, exist_ok=True)

_POLL_INTERVAL_SECONDS = 2.0
_TERMINAL_STATUSES = {"completed", "failed", "cancelled"}

# (thread_id, event_dict) -> None; wired up by server/sse.py to fan events
# out to open SSE connections. None (the default) means "no one's
# listening yet" -- job_watcher must work correctly with no server
# attached at all (e.g. under a direct-script test).
EventCallback = Callable[[str, dict], None]


def _seen_path(thread_id: str) -> Path:
    return _SEEN_DIR / f"{thread_id}.json"


def _read_seen(thread_id: str) -> set:
    p = _seen_path(thread_id)
    if not p.exists():
        return set()
    try:
        return set(json.loads(p.read_text()))
    except json.JSONDecodeError:
        return set()


def _write_seen(thread_id: str, seen: set) -> None:
    p = _seen_path(thread_id)
    tmp = p.with_suffix(p.suffix + f".tmp{os.getpid()}")
    tmp.write_text(json.dumps(sorted(seen)))
    os.replace(tmp, p)


def _config_for(thread_id: str) -> dict:
    return {"configurable": {"thread_id": thread_id}}


def _retry_notice(completed_ids, retry_ids, exhausted_ids, cancelled_ids) -> str:
    """Identical branching/wording to app/main.py's _jobs_fragment (the
    Streamlit implementation this replaces), plus a new cancelled branch
    that CLAUDE.md's original design didn't need -- see
    app/chemistry/jobs/base.py's JobManager.cancel() docstring."""
    notice_parts = []
    if completed_ids:
        notice_parts.append(
            f"Job(s) {', '.join(completed_ids)} finished. Check their status and give the "
            f"user a concise summary of the results."
        )
    if retry_ids:
        notice_parts.append(
            f"Job(s) {', '.join(retry_ids)} FAILED. For each: investigate with "
            f"check_job_status, consult search_knowledge_base and (if that's not enough) "
            f"web_search for the specific error, then call submit_job again with corrected "
            f"parameters and retry_of_job_id set to the failed job's id so the user can "
            f"review and approve the retry. Do not ask permission first -- the approval "
            f"card handles that."
        )
    if exhausted_ids:
        notice_parts.append(
            f"Job(s) {', '.join(exhausted_ids)} FAILED, and this troubleshooting chain has "
            f"already been auto-retried {MAX_AUTO_RETRIES} times without success. Do NOT "
            f"submit another automatic retry for these -- summarize what was tried and why "
            f"it kept failing (use check_job_status), and ask the user how they'd like to "
            f"proceed."
        )
    if cancelled_ids:
        notice_parts.append(
            f"Job(s) {', '.join(cancelled_ids)} were CANCELLED by the user. Do not retry "
            f"them and do not report them as failures -- just acknowledge the cancellation "
            f"briefly if it's relevant to what you say next."
        )
    return "(system notice, not from the user) " + " ".join(notice_parts)


class JobWatcher:
    def __init__(self, on_event: Optional[EventCallback] = None):
        self._on_event = on_event
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._last_status: dict[str, str] = {}  # job_id -> last-emitted status, dedups job_update events

    def start(self) -> None:
        if self._thread is not None:
            return
        self._thread = threading.Thread(target=self._loop, daemon=True, name="job-watcher")
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=5)
            self._thread = None

    def _emit(self, thread_id: str, event: dict) -> None:
        if self._on_event is not None:
            self._on_event(thread_id, event)

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                self._poll_once()
            except Exception:
                pass  # a single bad tick must never kill the watcher thread
            self._stop.wait(_POLL_INTERVAL_SECONDS)

    def _poll_once(self) -> None:
        mgr = get_job_manager()
        for entry in thread_registry.list_threads():
            thread_id = entry["thread_id"]
            active_job_ids = entry.get("active_job_ids", [])
            if not active_job_ids:
                continue

            seen = _read_seen(thread_id)
            newly_done = []
            for job_id in active_job_ids:
                status = mgr.status(job_id)
                status_str = status["status"]
                if self._last_status.get(job_id) != status_str:
                    self._last_status[job_id] = status_str
                    self._emit(thread_id, {
                        "type": "job_update", "job_id": job_id,
                        "status": status_str, "message": status.get("message", ""),
                    })
                if status_str in _TERMINAL_STATUSES and job_id not in seen:
                    newly_done.append(job_id)

            if not newly_done:
                continue

            # The graph is paused mid-tool-call (not at the agent node)
            # while a job/tool approval is pending, so a new HumanMessage
            # can't be responded to until it resolves -- same constraint
            # documented on render_jobs_panel in app/ui/components.py.
            # Leave these ids out of `seen` so the next tick after the
            # approval resolves picks them up and notifies as normal.
            if pending_approval(_config_for(thread_id)) is not None:
                continue

            completed_ids, retry_ids, exhausted_ids, cancelled_ids = [], [], [], []
            for job_id in newly_done:
                result = mgr.result(job_id)
                status_str = (result or {}).get("status")
                if status_str == "cancelled":
                    cancelled_ids.append(job_id)
                elif status_str == "failed":
                    if count_failed_in_chain(job_id) < MAX_AUTO_RETRIES:
                        retry_ids.append(job_id)
                    else:
                        exhausted_ids.append(job_id)
                else:
                    completed_ids.append(job_id)

            notice = _retry_notice(completed_ids, retry_ids, exhausted_ids, cancelled_ids)
            config = _config_for(thread_id)
            # Same reasoning as server/routes/chat.py's _publish_new_messages:
            # invoke_turn() is a single blocking call with no incremental
            # "updates" to stream from, so the investigation/retry messages
            # this synthetic turn produces (check_job_status, search_
            # knowledge_base, the eventual retry approval card) would
            # otherwise never reach an open SSE connection -- a user
            # watching the chat live would see the jobs table update but
            # not a single word of the agent's investigation, until they
            # reloaded the page.
            before_ids = {getattr(m, "id", None) for m in read_state(config).get("messages", [])}
            try:
                result_state = invoke_turn({"messages": [HumanMessage(content=notice)]}, config)
            except Exception:
                continue  # leave these ids unseen -- the next tick retries the notice

            for m in result_state.get("messages", []):
                if getattr(m, "id", None) not in before_ids:
                    self._emit(thread_id, {"type": "message", "message": serialize_message(m)})

            seen |= set(newly_done)
            _write_seen(thread_id, seen)
            thread_registry.touch_thread(thread_id)
            thread_registry.set_active_job_ids(thread_id, result_state.get("active_job_ids", []))
            pending = pending_approval(config)
            if pending is not None:
                self._emit(thread_id, {"type": "interrupt", "interrupt": pending})
            self._emit(thread_id, {"type": "turn_complete"})


_watcher: Optional[JobWatcher] = None


def get_job_watcher(on_event: Optional[EventCallback] = None) -> JobWatcher:
    """Singleton accessor, same pattern as get_job_manager(). `on_event`
    is only honored the first time this is called (server startup) --
    later calls just return the existing instance."""
    global _watcher
    if _watcher is None:
        _watcher = JobWatcher(on_event=on_event)
    return _watcher
