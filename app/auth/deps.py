"""FastAPI dependencies for authenticated routes, plus the cookie helpers
used by the login/logout routes themselves.
"""
from __future__ import annotations

from typing import Optional

from fastapi import Depends, HTTPException, Request, Response

from app.auth import models
from app.auth.redis_session import is_active_session
from app.auth.security import decode_token

SESSION_COOKIE_NAME = "qc_agent_session"


def set_session_cookie(response: Response, token: str, max_age_seconds: int) -> None:
    response.set_cookie(
        SESSION_COOKIE_NAME,
        token,
        max_age=max_age_seconds,
        httponly=True,
        secure=True,
        samesite="lax",
        path="/",
    )


def clear_session_cookie(response: Response) -> None:
    response.delete_cookie(SESSION_COOKIE_NAME, path="/")


def get_current_user(request: Request) -> dict:
    """Raises 401 for any failure mode (missing cookie, invalid/expired
    JWT, a session superseded by a newer login elsewhere, a deactivated
    account, a user row that's since been deleted) -- deliberately
    undifferentiated, since every one of these means the same thing to the
    frontend: redirect to the login screen."""
    token = request.cookies.get(SESSION_COOKIE_NAME)
    if not token:
        raise HTTPException(status_code=401, detail="not authenticated")
    payload = decode_token(token)
    if payload is None:
        raise HTTPException(status_code=401, detail="invalid or expired session")
    user_id = payload["sub"]
    session_id = payload["sid"]
    if not is_active_session(user_id, session_id):
        # A newer login elsewhere overwrote the active-session key (see
        # app/auth/redis_session.py), or Redis was flushed -- either way,
        # this token no longer represents the current session.
        raise HTTPException(status_code=401, detail="session superseded or expired")
    user = models.get_user_by_id(user_id)
    if user is None or not user["is_active"]:
        raise HTTPException(status_code=401, detail="account no longer active")
    return user


def require_admin(user: dict = Depends(get_current_user)) -> dict:
    if user["role"] != "admin":
        raise HTTPException(status_code=403, detail="admin role required")
    return user


def get_current_user_optional(request: Request) -> Optional[dict]:
    """Same checks as get_current_user, but returns None instead of raising
    -- for routes that behave differently for logged-in vs anonymous
    callers rather than requiring auth outright (none currently use this,
    kept for the KB retrieval-scoping work in the ownership retrofit, where
    a route may want to filter by owner if authenticated without hard-
    requiring a session)."""
    try:
        return get_current_user(request)
    except HTTPException:
        return None
