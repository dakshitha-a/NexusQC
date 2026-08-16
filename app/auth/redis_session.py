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

import threading
from typing import Optional

import redis

from app.config import REDIS_URL, SESSION_TTL_SECONDS

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
                _client = redis.Redis.from_url(REDIS_URL, decode_responses=True)
    return _client


def _key(user_id: str) -> str:
    return f"qc_agent:session:active:{user_id}"


def set_active_session(user_id: str, session_id: str) -> None:
    """Called on successful login -- overwrites whatever session id was
    previously active for this user, which is the actual kick mechanism
    for every other device/tab that was logged in as this user."""
    get_client().set(_key(user_id), session_id, ex=SESSION_TTL_SECONDS)


def is_active_session(user_id: str, session_id: str) -> bool:
    return get_client().get(_key(user_id)) == session_id


def clear_active_session(user_id: str) -> None:
    """Called on explicit logout -- removes the key entirely rather than
    leaving a value nothing will ever match again, tidier for anyone
    inspecting Redis directly and avoids the key lingering until its TTL
    expires for no reason."""
    get_client().delete(_key(user_id))
