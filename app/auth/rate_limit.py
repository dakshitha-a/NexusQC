"""Fixed-window rate limiting for /api/auth/login and /api/auth/register,
keyed on the client's real IP -- confirmed necessary, not just theoretical:
SEC-03 in the auth test suite found 100/100 sequential wrong-password
attempts against /api/auth/login went through with zero throttling before
this module existed.

Keyed on nginx's X-Real-IP (proxy_common.conf sets this from
$remote_addr), never request.client.host -- every request arrives at the
FastAPI process from the nginx container's own bridge IP, so keying on the
socket peer would put every real client behind nginx into one shared
bucket (one attacker locks out everyone, or the limit never usefully
trips). Falls back to request.client.host only for the no-nginx local-dev
case (QC_AGENT_DATABASE_URL unset, this module never gets called at all
since server/main.py's route wiring is auth-gated -- but keeping the
fallback sane costs nothing).

Deliberately a 429 sliding-ish window, not account lockout: this app has
no password-reset flow and no admin "unlock account" UI/route, so a
lockout would strand a legitimate user with no recovery path. Fails open
on any Redis error (connection refused, timeout) -- a Redis blip must
degrade to "no rate limiting" for a few seconds, not "no one can log in,"
the same fail-open posture already implicit in redis_session.py's use of
Redis as an enforcement cache rather than a durable record.
"""
from __future__ import annotations

import logging

from fastapi import HTTPException, Request

from app.auth.redis_session import get_client
from app.config import (
    LOGIN_RATE_LIMIT_MAX_ATTEMPTS,
    LOGIN_RATE_LIMIT_WINDOW_SECONDS,
    REGISTER_RATE_LIMIT_MAX_ATTEMPTS,
    REGISTER_RATE_LIMIT_WINDOW_SECONDS,
)

logger = logging.getLogger(__name__)


def _client_ip(request: Request) -> str:
    real_ip = request.headers.get("x-real-ip")
    if real_ip:
        return real_ip.strip()
    # Falls back to X-Forwarded-For (client-controlled -- $proxy_add_x_forwarded_for
    # APPENDS to whatever the client sent, so the leftmost entry here isn't
    # nginx's own value the way X-Real-IP is) only if X-Real-IP is somehow
    # absent, which requires reaching this process without going through
    # nginx at all. That's the exact same trust boundary
    # tests/backend/conf_03_access_channel_spoof.py already documents for
    # X-Access-Channel: docker-compose.yml exposes the api container's port
    # via `expose:`, not `ports:`, so it is not reachable from outside the
    # compose network in the first place -- nginx is the only path in, and
    # this fallback existing at all is defense in depth, not a real gap.
    forwarded_for = request.headers.get("x-forwarded-for")
    if forwarded_for:
        return forwarded_for.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def _key(bucket: str, request: Request) -> str:
    return f"qc_agent:ratelimit:{bucket}:{_client_ip(request)}"


def enforce(bucket: str, request: Request, max_attempts: int, window_seconds: int) -> None:
    """Raises HTTPException(429) once `max_attempts` calls for this
    (bucket, client IP) land within the current `window_seconds` window.
    A plain INCR+EXPIRE fixed window, not a true sliding log -- cheap (one
    round trip), and the boundary-burst imprecision a fixed window allows
    (up to 2x the nominal rate right at a window edge) doesn't matter here:
    the goal is closing a 100-attempts-with-zero-throttling gap, not
    precisely metering traffic."""
    key = _key(bucket, request)
    try:
        client = get_client()
        count = client.incr(key)
        if count == 1:
            client.expire(key, window_seconds)
    except Exception:
        logger.warning("rate_limit: Redis unavailable, failing open for bucket=%s", bucket, exc_info=True)
        return
    if count > max_attempts:
        raise HTTPException(
            status_code=429,
            detail="too many attempts, please wait before trying again",
        )


def enforce_login(request: Request) -> None:
    enforce("login", request, LOGIN_RATE_LIMIT_MAX_ATTEMPTS, LOGIN_RATE_LIMIT_WINDOW_SECONDS)


def enforce_register(request: Request) -> None:
    enforce("register", request, REGISTER_RATE_LIMIT_MAX_ATTEMPTS, REGISTER_RATE_LIMIT_WINDOW_SECONDS)
