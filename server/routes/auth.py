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

import io
import re
import zipfile

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel, field_validator

from app.auth import models
from app.auth.deps import clear_session_cookie, get_current_user, set_session_cookie
from app.auth.rate_limit import enforce_login, enforce_register
from app.auth.redis_session import clear_active_session, set_active_session
from app.auth.security import issue_token, new_session_id, verify_password
from app.auth.storage_quota import purge_own_data
from app.chemistry.jobs.naming import job_filename_stem
from app.config import JOBS_DIR, SESSION_TTL_SECONDS, UPLOADS_DIR

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
def register(body: RegisterIn, request: Request, response: Response):
    enforce_register(request)
    try:
        user = models.register_with_invite_token(body.invite_token, body.email, body.username, body.password)
    except models.InviteTokenError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    _start_session(response, user)
    return _user_public(user)


@router.post("/login")
def login(body: LoginIn, request: Request, response: Response):
    enforce_login(request)
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
def change_password(body: ChangePasswordIn, request: Request, response: Response):
    user = get_current_user(request)
    if not verify_password(body.current_password, user["password_hash"]):
        # 400, deliberately NOT 401. The caller IS authenticated -- it is the
        # request body that is wrong -- and frontend/src/lib/api.ts's request()
        # fires the global auth-error handler on any non-/api/auth/me 401,
        # which invalidates the ["auth","me"] query and bounces the user to the
        # login screen. Returning 401 here meant a simple typo in the
        # change-password form logged the user out instead of showing an error.
        # The alternative (exempting this path in request()) was rejected: it
        # would also swallow a genuine session-superseded 401 arriving on this
        # same call, reintroducing FE-SEC-01's blind spot on one route.
        raise HTTPException(status_code=400, detail="current password is incorrect")
    models.set_password(str(user["id"]), body.new_password)
    # Rotates the session (same mechanism _start_session already uses on
    # login: a fresh JWT/cookie for THIS caller, which overwrites the
    # Redis active-session key and so invalidates every other still-valid
    # cookie for this user). Without this, a password change didn't
    # invalidate anything -- a stolen-but-still-valid JWT for the same
    # session id (this device's own old token, or a copied-out one) kept
    # working until its natural 7-day TTL expired, confirmed empirically
    # by replaying the pre-change cookie against /api/auth/me afterward.
    _start_session(response, user)
    return {"changed": True}


@router.get("/me")
def me(request: Request):
    user = get_current_user(request)
    return _user_public(user)


@router.post("/purge-my-data")
def purge_my_data(request: Request):
    """The self-scoped "danger zone" purge (P9.4): deletes every job, KB
    upload and geometry/blind-input upload this signed-in user owns.
    Chat threads are deliberately untouched -- see purge_own_data's own
    docstring for why that is a different scope than admin-driven account
    deletion. No admin role required: owner_filter=user_id on every
    candidate builder inside purge_own_data means this can only ever act
    on the caller's own resources, the same way change-password above
    only ever acts on the caller's own row."""
    user = get_current_user(request)
    purged = purge_own_data(str(user["id"]))
    models.audit(str(user["id"]), "purge_own_data", target=str(user["id"]), details={
        "purged_jobs": len(purged["job_ids"]), "purged_kb_sources": len(purged["kb_sources"]),
        "purged_uploads": len(purged["upload_ids"]),
    })
    return {
        "purged": True,
        "purged_jobs": len(purged["job_ids"]),
        "purged_kb_sources": len(purged["kb_sources"]),
        "purged_uploads": len(purged["upload_ids"]),
    }


@router.get("/download-my-data")
def download_my_data(request: Request):
    """P9.4's "download all my data" button: one zip of every job, KB
    upload and geometry/blind-input upload this signed-in user owns, built
    entirely in memory -- same reasoning as GET /api/jobs/{id}/download
    (server/routes/jobs.py): /data is already close to full, so nothing
    here is ever written to disk.

    Each job gets the same per-job export /api/jobs/{id}/download would
    give it (a generated text summary for PySCF, the literal job directory
    for ORCA/BAGEL) rather than a second, different format -- reusing
    _pyscf_text_summary directly instead of re-deriving it."""
    from app.auth.models import all_owners
    from app.chemistry.jobs.base import get_job_manager, read_meta, read_spec, spec_created_at
    from app.rag.store import SHARED_OWNER, list_sources
    from app.uploads.store import list_uploads, read_upload_content
    from server.routes.jobs import _pyscf_text_summary

    user = get_current_user(request)
    user_id = str(user["id"])

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        owned_job_ids = [jid for jid, owner in all_owners("job").items() if owner == user_id]
        for job_id in owned_job_ids:
            spec = read_spec(job_id)
            if spec is None:
                continue
            stem = job_filename_stem(job_id, spec, read_meta(job_id), spec_created_at(job_id, spec))
            if spec.get("engine") == "pyscf":
                result = get_job_manager().result(job_id)
                zf.writestr(f"jobs/{stem}_summary.txt", _pyscf_text_summary(job_id, spec, result))
                continue
            job_dir = JOBS_DIR / job_id
            if not job_dir.is_dir():
                continue
            for f in job_dir.iterdir():
                if f.is_file():
                    zf.write(f, arcname=f"jobs/{stem}/{f.name}")

        for record in list_uploads(owner_filter=user_id):
            content = read_upload_content(user_id, record["id"])
            if content is None:
                continue
            data, _meta = content
            zf.writestr(f"uploads/{record['id']}_{record['original_name']}", data)

        for source in list_sources(owner_filter=user_id):
            if source["owner"] == SHARED_OWNER:
                continue
            path = UPLOADS_DIR / source["owner"] / source["source"]
            if path.is_file():
                zf.write(path, arcname=f"kb/{source['source']}")

    return Response(
        content=buffer.getvalue(), media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{user["username"]}_nexusqc_data.zip"'},
    )
