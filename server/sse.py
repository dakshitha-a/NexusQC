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

import asyncio
import json
import queue
import threading
from typing import AsyncIterator, Iterator

_KEEPALIVE_SECONDS = 15.0
# A dead-but-not-yet-disconnected subscriber (e.g. a backgrounded browser
# tab whose fetch reader has stalled without the underlying connection
# actually closing) would otherwise let publish() below grow this queue
# without bound for as long as that connection stays technically open --
# unlike a clean disconnect, which is already handled by event_stream's
# `finally: hub.unsubscribe(...)`. Bounded with a drop-oldest policy: a
# backlog of unread events is stale progress a reconnecting/resuming client
# doesn't need replayed anyway (the frontend always reconciles against
# GET /state or a job's own GET .../jobs on reconnect), so dropping the
# oldest queued event to make room for a new one is safe -- unlike dropping
# the newest, which would go stale itself.
_MAX_QUEUE_SIZE = 500


class SSEHub:
    def __init__(self):
        self._lock = threading.Lock()
        self._subscribers: dict[str, list[queue.Queue]] = {}

    def subscribe(self, thread_id: str) -> queue.Queue:
        q: queue.Queue = queue.Queue(maxsize=_MAX_QUEUE_SIZE)
        with self._lock:
            self._subscribers.setdefault(thread_id, []).append(q)
        return q

    def open_threads(self) -> dict[str, int]:
        """thread_id -> how many live streams are attached to it.

        For the admin activity view: "is anyone actually watching this
        deployment right now", which is a different question from "who has an
        account". Accurate the instant a browser disconnects cleanly, since
        event_stream()'s finally: unsubscribes; a client that vanishes without
        closing is noticed within _KEEPALIVE_SECONDS, when the write to its
        socket fails. That is a bounded lag, not an unbounded one, and it errs
        toward reporting somebody is present -- which is the safe direction for
        a caller deciding whether to interrupt them.
        """
        with self._lock:
            return {tid: len(subs) for tid, subs in self._subscribers.items() if subs}

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
        and the chat-turn runner both hold a reference to.

        Each subscriber's queue is bounded (_MAX_QUEUE_SIZE) -- if a
        subscriber isn't draining it fast enough to have filled it, drop
        its single oldest queued event to make room rather than blocking
        this publisher (which could be the chat-turn thread or the job
        watcher; blocking either on a slow/stalled reader would stall
        everyone else's events too, not just this one subscriber's)."""
        with self._lock:
            subs = list(self._subscribers.get(thread_id, ()))
        for q in subs:
            try:
                q.put_nowait(event)
            except queue.Full:
                try:
                    q.get_nowait()
                except queue.Empty:
                    pass
                try:
                    q.put_nowait(event)
                except queue.Full:
                    pass  # another publisher raced us to the freed slot; drop this event


hub = SSEHub()

# How often async_event_stream looks for an event. See its docstring.
_POLL_SECONDS = 0.05


def _format(event: dict) -> str:
    event_type = event.get("type", "message")
    return f"event: {event_type}\ndata: {json.dumps(event)}\n\n"


def event_stream(thread_id: str) -> Iterator[str]:
    """The synchronous generator. Kept for tests and for any caller that
    wants to drive the hub directly; the ROUTE uses `async_event_stream`
    below, and R-033 is why."""
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


async def async_event_stream(thread_id: str) -> AsyncIterator[str]:
    """The same stream, costing no threadpool token while it waits.

    R-033. Starlette drives a SYNCHRONOUS generator handed to
    StreamingResponse with one `anyio.to_thread.run_sync(next, iterator)` per
    yielded item, on the process-wide default limiter of 40 tokens. Each
    `next()` here blocks in `q.get(timeout=15)`, so an open stream held a
    token essentially continuously -- and those are the same 40 tokens
    FastAPI uses to run every plain `def` route handler in this app, which is
    all of them. Forty open tabs and the api answered nothing, including
    /api/health. Measured as a code read; the arithmetic is Starlette's.

    The queue stays a `queue.Queue`. That choice is deliberate and documented
    at the top of this module: the PUBLISHERS are worker threads and a job
    watcher, none of which has an event loop to put to. What changes is the
    CONSUMER: instead of blocking a thread on `q.get`, this polls the queue
    without blocking and awaits `asyncio.sleep` in between, so the wait
    happens on the event loop where waiting is free.

    The poll interval is the latency an event can sit unsent, so it is short.
    50 ms against a keepalive measured in seconds is not a meaningful delay
    to a browser, and an idle stream costs one timer wakeup per interval and
    no thread at all.
    """
    q = hub.subscribe(thread_id)
    try:
        yield ": connected\n\n"
        idle = 0.0
        while True:
            try:
                event = q.get_nowait()
            except queue.Empty:
                await asyncio.sleep(_POLL_SECONDS)
                idle += _POLL_SECONDS
                if idle >= _KEEPALIVE_SECONDS:
                    idle = 0.0
                    yield ": keepalive\n\n"
                continue
            idle = 0.0
            yield _format(event)
    finally:
        hub.unsubscribe(thread_id, q)
