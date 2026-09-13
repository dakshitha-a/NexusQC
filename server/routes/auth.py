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

import json
import logging
import re

from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, field_validator

from app.auth import models
from app.auth.deps import SESSION_COOKIE_NAME, clear_session_cookie, get_current_user, set_session_cookie
from app.auth.rate_limit import enforce_login, enforce_password_reset, enforce_register
from app.auth.redis_session import clear_active_session, set_active_session
from app.auth.security import decode_token, issue_token, new_session_id, verify_password
from app.auth.storage_quota import purge_own_data
from app.chemistry.jobs.naming import job_filename_stem
from app.config import JOBS_DIR, SESSION_TTL_SECONDS, UPLOADS_DIR

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/auth", tags=["auth"])


_UNSAFE_ARCNAME_RE = re.compile(r"[^A-Za-z0-9._-]+")


def _safe_arcname(text: str, limit: int = 60) -> str:
    """A label reduced to something safe to use as one path segment inside the
    zip. Labels are user-written free text, and a zip entry name is a path:
    a conversation called "../../etc/passwd" must not become one. Everything
    outside a small safe set collapses to an underscore, and the result is
    trimmed, so the id appended by the caller stays the part that makes the
    name unique."""
    cleaned = _UNSAFE_ARCNAME_RE.sub("_", text).strip("._-")
    return (cleaned[:limit] or "untitled")


def _session_id_from_request(request: Request) -> str | None:
    """The `sid` inside the caller's own session token, or None.

    Only ever called after get_current_user has accepted the request, so the
    token is present and decodable; the belt-and-braces None handling is for
    the case where that stops being true."""
    token = request.cookies.get(SESSION_COOKIE_NAME)
    if not token:
        return None
    payload = decode_token(token)
    return (payload or {}).get("sid")

_USERNAME_RE = re.compile(r"^[a-zA-Z0-9_.-]{3,32}$")
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class RegisterIn(BaseModel):
    invite_token: str
    email: str
    username: str
    password: str
    first_name: str
    last_name: str

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

    @field_validator("first_name", "last_name")
    @classmethod
    def _valid_name(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("first and last name are required")
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
        user = models.register_with_invite_token(
            body.invite_token, body.email, body.username, body.password,
            body.first_name, body.last_name,
        )
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
    """Ends the session in all three places it is recorded.

    R-088: this used to clear the Redis key and the cookie and leave the
    Postgres row exactly as it was, marked live, for ever. `revoke_session`
    existed and had no caller at all; `revoked` and `expires_at` were columns
    nothing ever wrote or acted on. Nothing was insecure about it, because
    what actually decides whether a token still works is the Redis key, but
    the sessions table is the only durable record of who was signed in when,
    and a table that says every session ever opened is still open is not a
    record of anything.

    The session id comes from the caller's own token rather than from a
    lookup, so this revokes the session that is logging out and no other. A
    token that cannot be decoded never reaches here: get_current_user above
    has already refused it."""
    user = get_current_user(request)
    session_id = _session_id_from_request(request)
    if session_id:
        try:
            models.revoke_session(session_id)
        except Exception:
            # Logging out is not worth a 500, for the same reason clearing
            # the Redis key is not: the cookie is going regardless and the
            # Redis key is what actually gates the token.
            logger.warning("could not mark the session revoked on logout", exc_info=True)
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
    # A password change is the one write to users.password_hash a person can
    # make for themselves, and it used to leave no trace at all: every admin
    # action lands in admin_audit_log, but this did not, so an account whose
    # password stopped working could not be investigated -- there was no way
    # to tell whether it had been changed, from which session, or when. The
    # actor and the target are the same id by construction; the row is worth
    # writing anyway, because its absence is what could not be reasoned about.
    models.audit(str(user["id"]), "change_password", target=str(user["id"]),
                 details={"username": user["username"]})
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


class ResetPasswordIn(BaseModel):
    token: str
    new_password: str

    @field_validator("new_password")
    @classmethod
    def _valid_password(cls, v: str) -> str:
        if len(v) < 8:
            raise ValueError("password must be at least 8 characters")
        return v


@router.post("/reset-password")
def reset_password(body: ResetPasswordIn, request: Request, response: Response):
    """Redeems an admin-issued reset token and signs the caller in.

    Unauthenticated by design: the whole point is that the person cannot
    get in. The token IS the authentication, which is why it is single-use,
    short-lived, and why every rejection below returns the same message --
    an attacker holding a guess must not be able to learn whether a token
    exists, has been used, or belongs to a suspended account.
    """
    enforce_password_reset(request)
    try:
        user = models.redeem_password_reset_token(body.token, body.new_password)
    except models.PasswordResetError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    models.audit(str(user["id"]), "reset_password", target=str(user["id"]),
                 details={"username": user["username"], "via": "admin_issued_token"})
    # Signs THIS caller in and, by overwriting the Redis active-session key,
    # invalidates every other outstanding cookie for the account -- the same
    # mechanism change_password relies on. That matters more here than there:
    # the usual reason someone needs a reset is that they no longer control
    # what else might be holding a session for them.
    _start_session(response, user)
    return _user_public(user)


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
        # R-087: plots and project archives are deleted by this call and were
        # missing from its counts, so the response read as complete while two
        # categories went unmentioned.
        "purged_plots": len(purged.get("plot_ids") or []),
        "purged_projects": len(purged.get("project_ids") or []),
    }


@router.get("/download-my-data")
def download_my_data(request: Request):
    """P9.4's "download all my data" button: one zip of every job, KB
    upload and geometry/blind-input upload this signed-in user owns.

    Streamed, never assembled in memory. This used to build the whole thing
    in an io.BytesIO, on the same reasoning GET /api/jobs/{id}/download
    still gives for doing so: /data is close to full, so writing the zip
    out to disk is not an option either. That trade is defensible for one
    job and indefensible here, because this is by definition the largest
    archive the app can produce -- every job a person owns, and one orbital
    cube alone runs to several megabytes. A real account was hundreds of
    megabytes resident in a threadpool worker for the length of the
    download, once per concurrent download. app/projects/zipstream.py does
    the same job as a generator, holding one file chunk at a time.

    Each job gets the same export /api/jobs/{id}/download would give it (a
    generated text summary for PySCF, the literal job directory for
    ORCA/BAGEL) rather than a second, different format, reusing
    _pyscf_text_summary directly.

    R-046: conversations, plots and project archives are in the zip too.
    They were not, and their absence was not arbitrary, it was just never
    revisited: the button was written when jobs and uploads were most of what
    an account held. The same account's quota bills it for chat history, and
    the danger-zone purge beside this button deletes conversations when an
    admin removes the account, so "all my data" that silently meant "my jobs
    and my uploads" was the one description of the three that was wrong.

    Conversations go in as JSON, one file per thread, holding what the app
    itself reads back: the message list, the active molecule, the job ids.
    That is a faithful export rather than a rendered transcript, because a
    rendered transcript throws away the tool calls and the job links, which
    are most of what makes a NexusQC conversation worth keeping.

    Plots go in as their record plus every rendered version, since a plot is
    versioned on purpose (an older message cites the version it drew, see
    app/plots/store.py) and exporting only the latest would lose exactly what
    the versioning is for. Projects go in as JSON: an archive is a membership
    list, and the jobs it names are already in the zip.

    Scan and ensemble frames needed no work here and are worth saying so
    about: they are sub-jobs, and sub-jobs record their owner as of R-001, so
    they arrive through the ordinary owned-jobs pass."""
    from app.agent import threads as thread_registry
    from app.agent.graph import read_state
    from app.agent.serialize import serialize_state
    from app.auth.models import all_owners, list_owned
    from app.chemistry.jobs.base import get_job_manager, read_meta, read_spec, spec_created_at
    from app.plots import store as plot_store
    from app.projects import registry as project_registry
    from app.projects.zipstream import stream_zip
    from app.rag.store import SHARED_OWNER, list_sources
    from app.uploads.store import list_uploads, read_upload_content
    from server.routes.jobs import _pyscf_text_summary

    user = get_current_user(request)
    user_id = str(user["id"])

    def entries():
        """(arcname, bytes-or-path) pairs, yielded lazily so an account
        with a thousand jobs never has its file list, let alone its file
        contents, enumerated up front."""
        owned_job_ids = [jid for jid, owner in all_owners("job").items() if owner == user_id]
        for job_id in owned_job_ids:
            spec = read_spec(job_id)
            if spec is None:
                continue
            stem = job_filename_stem(job_id, spec, read_meta(job_id), spec_created_at(job_id, spec))
            if spec.get("engine") == "pyscf":
                result = get_job_manager().result(job_id)
                yield f"jobs/{stem}_summary.txt", _pyscf_text_summary(job_id, spec, result).encode("utf-8")
                continue
            job_dir = JOBS_DIR / job_id
            if not job_dir.is_dir():
                continue
            for f in sorted(job_dir.iterdir()):
                if f.is_file():
                    yield f"jobs/{stem}/{f.name}", f

        for record in list_uploads(owner_filter=user_id):
            content = read_upload_content(user_id, record["id"])
            if content is None:
                continue
            data, _meta = content
            yield f"uploads/{record['id']}_{record['original_name']}", data

        for source in list_sources(owner_filter=user_id):
            if source["owner"] == SHARED_OWNER:
                continue
            path = UPLOADS_DIR / source["owner"] / source["source"]
            if path.is_file():
                yield f"kb/{source['source']}", path

        # R-046: conversations. One file per thread, named by the label the
        # user gave it so the archive is browsable, with the id kept in the
        # filename because labels are neither unique nor required.
        owned_thread_ids = set(list_owned("thread", user_id))
        for entry in thread_registry.list_threads():
            thread_id = entry["thread_id"]
            if thread_id not in owned_thread_ids:
                continue
            try:
                state = serialize_state(read_state({"configurable": {"thread_id": thread_id}}))
            except Exception:
                # One unreadable checkpoint must not cost the user the rest of
                # their archive. The registry entry still goes in, so the
                # conversation is at least named.
                logger.warning("could not export thread %s", thread_id, exc_info=True)
                state = {"messages": [], "export_error": "this conversation could not be read"}
            payload = {"thread": entry, "state": state}
            yield (f"conversations/{_safe_arcname(entry.get('label') or 'conversation')}"
                   f"_{thread_id}.json",
                   json.dumps(payload, indent=2, default=str).encode("utf-8"))

        # R-046: plots, record plus every rendered version.
        for record in plot_store.list_plots(owner_filter=user_id):
            plot_id = record["plot_id"]
            stem = f"plots/{_safe_arcname(record.get('label') or 'plot')}_{plot_id}"
            yield f"{stem}/record.json", json.dumps(record, indent=2, default=str).encode("utf-8")
            for version in record.get("versions") or []:
                path = plot_store.version_path(user_id, plot_id, version)
                if path is not None and path.is_file():
                    yield f"{stem}/{version}.png", path

        # R-046: project archives. A membership list; the jobs it names are
        # already in the zip under jobs/.
        for project_id in list_owned("project", user_id):
            project = project_registry.get_project(project_id)
            if project is None:
                continue
            name = _safe_arcname(project.get("name") or "project")
            yield (f"projects/{name}_{project_id}.json",
                   json.dumps(project, indent=2, default=str).encode("utf-8"))

    return StreamingResponse(
        stream_zip(entries()),
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{user["username"]}_nexusqc_data.zip"'},
    )
