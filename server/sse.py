"""In-process pub/sub hub for per-conversation Server-Sent Events.

Deliberately built on plain `queue.Queue` (thread-safe, blocking), not
`asyncio.Queue`: every publisher is a plain OS thread, not an asyncio task --
job_watcher.py runs its own background thread, and the chat-turn runner
(server/routes/chat.py) also runs each turn on its own background thread so
POST /messages can return immediately (see that module). A synchronous
generator handed to Starlette's StreamingResponse is executed in FastAPI's
threadpool, so blocking on `queue.Queue.get()` there is the correct,
simplest way to bridge those threads into an HTTP stream -- no asyncio loop
needs to be involved anywhere in this module.
"""
from __future__ import annotations

import json
import queue
import threading
from typing import Iterator

_KEEPALIVE_SECONDS = 15.0


class SSEHub:
    def __init__(self):
        self._lock = threading.Lock()
        self._subscribers: dict[str, list[queue.Queue]] = {}

    def subscribe(self, thread_id: str) -> queue.Queue:
        q: queue.Queue = queue.Queue()
        with self._lock:
            self._subscribers.setdefault(thread_id, []).append(q)
        return q

    def unsubscribe(self, thread_id: str, q: queue.Queue) -> None:
        with self._lock:
            subs = self._subscribers.get(thread_id)
            if not subs:
                return
            if q in subs:
                subs.remove(q)
            if not subs:
                self._subscribers.pop(thread_id, None)

    def publish(self, thread_id: str, event: dict) -> None:
        """Fire-and-forget: if nobody is subscribed to this thread_id right
        now, the event is simply dropped (e.g. no browser tab has it open).
        Safe to call from any thread -- this is the callback job_watcher.py
        and the chat-turn runner both hold a reference to."""
        with self._lock:
            subs = list(self._subscribers.get(thread_id, ()))
        for q in subs:
            q.put(event)


hub = SSEHub()


def _format(event: dict) -> str:
    event_type = event.get("type", "message")
    return f"event: {event_type}\ndata: {json.dumps(event)}\n\n"


def event_stream(thread_id: str) -> Iterator[str]:
    q = hub.subscribe(thread_id)
    try:
        yield ": connected\n\n"
        while True:
            try:
                event = q.get(timeout=_KEEPALIVE_SECONDS)
            except queue.Empty:
                # Keeps the connection alive through idle proxies/browsers
                # and gives the generator a chance to notice a client
                # disconnect (Starlette stops iterating once the client
                # goes away, which surfaces as a GeneratorExit on the next
                # yield either way -- this just bounds how long that takes).
                yield ": keepalive\n\n"
                continue
            yield _format(event)
    finally:
        hub.unsubscribe(thread_id, q)
