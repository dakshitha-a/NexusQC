"""One-session-per-user enforcement. This is a fast, TTL'd cache, not the
durable session record (that's the `sessions` Postgres table via
app/auth/models.py) -- if Redis is restarted/flushed, the worst case is
every logged-in user gets treated as "already superseded" on their next
request and has to log in again, not silent data loss.

The mechanism: a single Redis key per user holding the CURRENT session id.
Logging in again overwrites it -- that overwrite *is* the enforcement; the
old session's next request presents a session id that no longer matches the
key's value and gets a 401. This is deliberately not a push/kick (no
websocket telling the old tab it's been logged out mid-session) -- the old
tab's *next* request or its EventSource's next auto-reconnect (already how
frontend/src/lib/sse.ts behaves on any dropped connection) discovers it. An
honest, bounded-latency guarantee, not an instant one; a push-based kick
would be real added complexity for a threat model (a user's own second
login) that doesn't need instant revocation.
"""
from __future__ import annotations

import logging
import threading
from typing import Optional

import redis
from redis.exceptions import RedisError

from app.config import REDIS_URL, SESSION_TTL_SECONDS

logger = logging.getLogger(__name__)

# Seconds. See get_client for why it is short.
_SOCKET_TIMEOUT_SECONDS = 2.0

_client: Optional["redis.Redis"] = None
_client_lock = threading.Lock()


def get_client() -> "redis.Redis":
    global _client
    if _client is None:
        with _client_lock:
            if _client is None:
                if not REDIS_URL:
                    raise RuntimeError(
                        "app.auth.redis_session.get_client() called with QC_AGENT_REDIS_URL unset"
                    )
                # Timeouts, and R-032 is why they are not optional here.
                # redis-py's default socket_timeout is None, i.e. block
                # forever, and this client is on the authentication path of
                # every request: get_current_user -> is_active_session ->
                # here. A REFUSED connection fails fast and is fine; a
                # black-holed one (a paused container, a network partition,
                # a firewall drop) does not. Each such request then occupies
                # one of anyio's 40 threadpool tokens indefinitely, and after
                # forty the api answers nothing at all, including
                # /api/health.
                #
                # ARCHITECTURE.md's "Three outbound calls needed explicit
                # timeouts" states the principle for the graph's own tools.
                # This is a fourth, worse placed: it gates every request
                # rather than one tool.
                #
                # Two seconds, not the tens of seconds an engine call gets:
                # Redis is a local container answering a single GET, so any
                # honest answer arrives in single-digit milliseconds, and
                # what the timeout has to bound is the pathological case.
                # health_check_interval makes the client notice a connection
                # that died while pooled rather than handing it out and
                # failing on first use.
                _client = redis.Redis.from_url(
                    REDIS_URL,
                    decode_responses=True,
                    socket_timeout=_SOCKET_TIMEOUT_SECONDS,
                    socket_connect_timeout=_SOCKET_TIMEOUT_SECONDS,
                    health_check_interval=30,
                )
    return _client


def _key(user_id: str) -> str:
    return f"qc_agent:session:active:{user_id}"


def set_active_session(user_id: str, session_id: str) -> None:
    """Called on successful login -- overwrites whatever session id was
    previously active for this user, which is the actual kick mechanism
    for every other device/tab that was logged in as this user.

    Deliberately NOT caught, unlike the two readers below. If this write does
    not land, one-session-per-user is not being enforced for the session
    being handed out, and the honest answer to "log me in" is then an error
    rather than a session the app cannot police. The socket timeout above
    bounds how long the caller waits to find that out."""
    get_client().set(_key(user_id), session_id, ex=SESSION_TTL_SECONDS)


def is_active_session(user_id: str, session_id: str) -> bool:
    """Whether this session is the one currently active for this user.

    An unreachable Redis answers False, which is a 401 and a bounce to the
    login screen, rather than propagating and becoming a 500 (R-050). Three
    reasons that is the right direction. This module's own docstring already
    describes the worst case of a flushed Redis as "every logged-in user gets
    treated as 'already superseded' on their next request and has to log in
    again", which is exactly a 401. The frontend has a global auth-error
    handler that turns a 401 into a login redirect and nothing that turns a
    500 into anything. And `app/auth/rate_limit.py` takes the same posture for
    the same dependency, in as many words: "a Redis blip must degrade to 'no
    rate limiting' for a few seconds, not 'no one can log in'".

    It fails CLOSED rather than open, unlike the rate limiter, and that
    asymmetry is deliberate: this function's answer decides whether a session
    is valid, so the safe direction is to disbelieve it.
    """
    try:
        return get_client().get(_key(user_id)) == session_id
    except RedisError:
        logger.warning("redis unreachable while checking the active session; "
                       "treating the session as superseded (the caller sees a 401)")
        return False


def clear_active_session(user_id: str) -> None:
    """Called on explicit logout -- removes the key entirely rather than
    leaving a value nothing will ever match again, tidier for anyone
    inspecting Redis directly and avoids the key lingering until its TTL
    expires for no reason."""
    try:
        get_client().delete(_key(user_id))
    except RedisError:
        # Logging out is not worth a 500 either: the session cookie is being
        # cleared regardless, and the key expires on its own TTL.
        logger.warning("redis unreachable while clearing the active session")
