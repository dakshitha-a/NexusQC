#!/usr/bin/env python3
"""Nothing blocks the event loop, and an unreachable Redis is a 401.
Regression test for R-007, R-032, R-050 and R-033/R-097.

    PYTHONPATH=$PWD python3 tests/backend/sec_15_middleware_and_redis.py

R-007. `AccessControlMiddleware.dispatch` is the one `async def` on the
request path, and it called `_maintenance_mode()`, which did a synchronous
psycopg round trip whenever its two-second cache was cold. That is a blocking
call on the single event loop, which is exactly what this codebase's
plain-`def` rule for route handlers exists to prevent -- CLAUDE.md says an
`async def` that blocks stalls SSE delivery to every open tab. The TTL made
it a few tens of round trips a minute rather than one per request, which is
why it was S2 and not worse; it did not make any of them safe, and a
deployment mid-restart is exactly when the cache is cold AND the database is
slow to answer.

R-032. The Redis client had no socket timeout, and redis-py's default is to
block forever. It is on the authentication path of every request, so a
black-holed connection (a paused container, a partition) parks one of anyio's
40 threadpool tokens per request until, after forty, the api answers nothing
at all -- including /api/health.

R-050. An unreachable Redis then turned every authenticated request into a
500, where the rate limiter beside it deliberately degrades instead, and this
module's own docstring describes the worst case as users "treated as already
superseded" -- which is a 401 and a bounce to the login screen, the thing the
frontend's global auth handler already knows how to do.

R-033. An SSE stream held a threadpool token continuously, and those are the
same forty tokens every plain-`def` route handler in this app runs on.

Runs in process: no server, no Redis, no database.
"""
from __future__ import annotations

import asyncio
import inspect
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO))

from tests.fixtures import check, summary  # noqa: E402

print("R-007: the maintenance check never blocks the caller\n")

from app.auth import middleware  # noqa: E402

src = inspect.getsource(middleware._maintenance_mode)
check("_maintenance_mode does no database work of its own",
      "get_app_config" not in src, "",
      "it still calls into models on the caller's thread, which for "
      "dispatch() is the event loop")
check("the refresh is a separate function, run off the loop",
      "threading.Thread(target=_refresh_maintenance_cache" in src, "")

# A cold cache must return immediately even when the refresh is slow, which
# is the property that matters. The refresh is stubbed to take a second; a
# blocking implementation would take a second to answer.
real = middleware.models.get_app_config
middleware._maint_cache.update({"value": False, "checked_at": 0.0, "refreshing": False})


def _slow(*_a, **_k):
    time.sleep(1.0)
    return False


middleware.models.get_app_config = _slow
try:
    t0 = time.perf_counter()
    middleware._maintenance_mode()
    elapsed = time.perf_counter() - t0
    check("a cold cache answers immediately even when the database is slow",
          elapsed < 0.1, f"{elapsed * 1000:.1f} ms",
          f"{elapsed:.2f} s -- the query is still on the caller's thread")
    time.sleep(1.3)   # let the background refresh land
    check("and the refresh does land, so the answer is not stale for ever",
          middleware._maint_cache["checked_at"] > 0, "")
finally:
    middleware.models.get_app_config = real
    middleware._maint_cache.update({"value": False, "checked_at": 0.0, "refreshing": False})

print("\nR-032 and R-050: the Redis client")
from app.auth import redis_session  # noqa: E402

gsrc = inspect.getsource(redis_session.get_client)
check("the client is built with a socket timeout", "socket_timeout=" in gsrc, "",
      "redis-py's default is to block forever, on the authentication path of "
      "every request")
check("and a connect timeout", "socket_connect_timeout=" in gsrc)
timeout_s = getattr(redis_session, "_SOCKET_TIMEOUT_SECONDS", None)
check("the timeout is short, because Redis is a local container answering a GET",
      timeout_s is not None and 0 < timeout_s <= 5, f"{timeout_s}s")


class _Dead:
    def get(self, *_a, **_k):
        from redis.exceptions import ConnectionError as RedisConnectionError
        raise RedisConnectionError("nobody home")

    def delete(self, *_a, **_k):
        from redis.exceptions import ConnectionError as RedisConnectionError
        raise RedisConnectionError("nobody home")


real_client = redis_session.get_client
redis_session.get_client = lambda: _Dead()
try:
    try:
        answered = redis_session.is_active_session("u", "s")
        check("an unreachable Redis answers 'not the active session' rather than raising",
              answered is False, f"returned {answered!r}")
    except Exception as exc:                                    # noqa: BLE001
        check("an unreachable Redis answers 'not the active session' rather than raising",
              False, "",
              f"{type(exc).__name__} propagates and becomes a 500, where the rate "
              f"limiter beside it degrades instead")
    try:
        redis_session.clear_active_session("u")
        check("and logging out does not raise either", True, "no exception")
    except Exception as exc:                                    # noqa: BLE001
        check("and logging out does not raise either", False, "", f"{type(exc).__name__}")
finally:
    redis_session.get_client = real_client

print("\nR-033: an SSE stream costs no threadpool token")
from server import sse  # noqa: E402

check("there is an async generator for the route to use",
      hasattr(sse, "async_event_stream"), "")
from server.routes import chat as chat_route  # noqa: E402

esrc = inspect.getsource(chat_route.get_events)
check("the route hands back the async one", "async_event_stream" in esrc, "")
check("and the handler is still a plain def, per CLAUDE.md's absolute rule",
      not inspect.iscoroutinefunction(chat_route.get_events), "")


HAS_ASYNC = hasattr(sse, "async_event_stream")


async def _drain(thread_id: str, n: int) -> list[str]:
    out = []
    agen = sse.async_event_stream(thread_id)
    try:
        for _ in range(n):
            out.append(await asyncio.wait_for(agen.__anext__(), timeout=5))
    finally:
        await agen.aclose()
    return out


async def _exercise() -> list[str]:
    task = asyncio.ensure_future(_drain("t1", 2))
    await asyncio.sleep(0.2)
    sse.hub.publish("t1", {"type": "turn_complete"})
    return await task


if HAS_ASYNC:
    chunks = asyncio.run(_exercise())
    check("the async stream yields its opening comment and then a real event",
          len(chunks) == 2 and chunks[0].startswith(": connected") and "turn_complete" in chunks[1],
          f"{[c[:30] for c in chunks]}")
else:
    check("the async stream yields its opening comment and then a real event", False, "",
          "there is no async generator, so every open stream still holds one "
          "of anyio's 40 threadpool tokens")

print("\nR-097: the Stop button is disarmed only by its own turn")
import threading  # noqa: E402

psrc = inspect.getsource(chat_route._pop_cancel_event)
check("_pop_cancel_event takes the event it is removing", "ev" in psrc and "is ev" in psrc, "",
      "it still pops by thread id alone, so one turn's cleanup disarms another's")

first = chat_route._register_cancel_event("thread-x")
second = chat_route._register_cancel_event("thread-x")
try:
    chat_route._pop_cancel_event("thread-x", first)
    check("a finished turn does not deregister the turn that replaced it",
          chat_route._cancel_events.get("thread-x") is second, "",
          "the second turn's Stop button is now a silent no-op")
    chat_route._pop_cancel_event("thread-x", second)
    check("and its own turn does deregister it",
          "thread-x" not in chat_route._cancel_events, "")
except TypeError as exc:
    check("a finished turn does not deregister the turn that replaced it", False, "",
          f"{exc} -- it pops by thread id alone, so one turn's cleanup disarms "
          f"another turn's Stop button")
    chat_route._cancel_events.pop("thread-x", None)

summary()
