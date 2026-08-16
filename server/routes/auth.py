"""Login/register/logout/change-password/me. Plain `def` handlers, same
convention as every other route in this app -- see server/main.py's module
docstring for why (sync handlers run in FastAPI's threadpool; none of the
work here is async-friendly I/O anyway, it's all short psycopg/redis calls).

Deliberately NO web-based first-admin bootstrap: /register always requires
a valid, unredeemed invite token. The first token is minted only by
server/admin_cli.py's `bootstrap-admin` command, run locally on the host --
closing the "first visitor self-registers as admin" hole a web route could
never fully close.
"""
from __future__ import annotations

import re

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel, field_validator

from app.auth import models
from app.auth.deps import clear_session_cookie, get_current_user, set_session_cookie
from app.auth.redis_session import clear_active_session, set_active_session
from app.auth.security import issue_token, new_session_id, verify_password
from app.config import SESSION_TTL_SECONDS

router = APIRouter(prefix="/api/auth", tags=["auth"])

_USERNAME_RE = re.compile(r"^[a-zA-Z0-9_.-]{3,32}$")
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class RegisterIn(BaseModel):
    invite_token: str
    email: str
    username: str
    password: str

    @field_validator("email")
    @classmethod
    def _valid_email(cls, v: str) -> str:
        if not _EMAIL_RE.match(v):
            raise ValueError("invalid email address")
        return v

    @field_validator("username")
    @classmethod
    def _valid_username(cls, v: str) -> str:
        if not _USERNAME_RE.match(v):
            raise ValueError("username must be 3-32 characters: letters, digits, _ . -")
        return v

    @field_validator("password")
    @classmethod
    def _valid_password(cls, v: str) -> str:
        if len(v) < 8:
            raise ValueError("password must be at least 8 characters")
        return v


class LoginIn(BaseModel):
    email_or_username: str
    password: str


class ChangePasswordIn(BaseModel):
    current_password: str
    new_password: str

    @field_validator("new_password")
    @classmethod
    def _valid_password(cls, v: str) -> str:
        if len(v) < 8:
            raise ValueError("password must be at least 8 characters")
        return v


def _user_public(user: dict) -> dict:
    return {
        "id": str(user["id"]),
        "email": user["email"],
        "username": user["username"],
        "role": user["role"],
    }


def _start_session(response: Response, user: dict) -> None:
    session_id = new_session_id()
    models.create_session(str(user["id"]), session_id, user_agent=None)
    set_active_session(str(user["id"]), session_id)
    token = issue_token(str(user["id"]), session_id, user["role"])
    set_session_cookie(response, token, SESSION_TTL_SECONDS)
    models.touch_last_login(str(user["id"]))


@router.post("/register")
def register(body: RegisterIn, response: Response):
    try:
        user = models.register_with_invite_token(body.invite_token, body.email, body.username, body.password)
    except models.InviteTokenError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    _start_session(response, user)
    return _user_public(user)


@router.post("/login")
def login(body: LoginIn, response: Response):
    user = models.verify_login(body.email_or_username, body.password)
    if user is None:
        raise HTTPException(status_code=401, detail="invalid credentials")
    _start_session(response, user)
    return _user_public(user)


@router.post("/logout")
def logout(request: Request, response: Response):
    user = get_current_user(request)
    clear_active_session(str(user["id"]))
    clear_session_cookie(response)
    return {"logged_out": True}


@router.post("/change-password")
def change_password(body: ChangePasswordIn, request: Request):
    user = get_current_user(request)
    if not verify_password(body.current_password, user["password_hash"]):
        raise HTTPException(status_code=401, detail="current password is incorrect")
    models.set_password(str(user["id"]), body.new_password)
    return {"changed": True}


@router.get("/me")
def me(request: Request):
    user = get_current_user(request)
    return _user_public(user)
