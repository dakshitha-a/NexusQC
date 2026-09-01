"""User-to-user sharing of a job or a project archive.

A separate module from server/routes/jobs.py and server/routes/projects.py
for the reason projects.py gives in its own docstring: jobs.py carries a
contract that it never calls read_state() or takes the graph lock, so job
polling cannot stall behind a chat turn, and a reviewer should not have to
re-verify that file every time sharing changes. Everything here reads the
same lock-free disk functions plus Postgres, so the property holds, but it
holds separately.

Every handler is a plain `def`, never `async def`: a sync handler runs in
the worker threadpool, while an `async def` that blocks stalls the single
event loop and with it SSE delivery to every open tab. Accepting a share
copies a job directory, which for a Wigner master can be tens of
megabytes across fifty directories, so that matters here.

This router is only mounted when auth is configured (see server/main.py).
Without a database there are no other users to share with, so every route
would be answering a question that cannot be asked.
"""
from __future__ import annotations

import uuid
from typing import Optional

from fastapi import APIRouter, HTTPException, Query, Request
from psycopg import errors as pg_errors

from app.auth import models as auth_models, storage_quota
from app.auth.ownership import check_owner_or_admin, current_user_or_none, record
from app.chemistry.jobs.base import job_is_terminal, read_meta, read_spec
from app.chemistry.jobs.copy import copy_job, job_family_size_bytes
from app.chemistry.jobs.naming import resolve_job_label
from app.projects import registry as project_registry
from server.schemas import CreateShareIn

router = APIRouter()

VALID_KINDS = ("job", "project")


def _require_user(request: Request) -> dict:
    """Sharing has no meaning for an unauthenticated caller, and unlike the
    rest of the app there is no single-user fallback to degrade to: with no
    accounts there is nobody to share with. current_user_or_none returns
    None only when DATABASE_URL is unset, which cannot happen here because
    the router is not mounted in that case -- so this is a guard against
    misconfiguration, not a reachable user-facing path."""
    user = current_user_or_none(request)
    if user is None:
        raise HTTPException(status_code=404, detail="Sharing requires a multi-user deployment")
    return user


@router.get("/api/users/search")
def search_users(request: Request, q: str = Query(default="")) -> list[dict]:
    """Prefix lookup for the share picker.

    Returns id, username and first/last name and nothing else. See
    models.search_users for why this does not reuse _user_public (which
    carries email and role) or get_user_by_login (whose projection includes
    password_hash).

    A query shorter than models.USER_SEARCH_MIN_CHARS returns an empty list
    rather than an error: the picker calls this on every keystroke, and a
    400 on the first character would mean rendering an error state during
    normal typing.
    """
    user = _require_user(request)
    return auth_models.search_users(q, exclude_user_id=str(user["id"]))


def _job_label(job_id: str) -> str:
    """The job's name as the sender sees it, snapshotted onto the offer so
    the recipient's inbox row is readable rather than a bare id."""
    return resolve_job_label(read_spec(job_id), read_meta(job_id))


def _lookup_user(user_id: str) -> Optional[dict]:
    """None for a user id that is not a well-formed UUID as well as for one
    that simply is not there. Without the parse, a hand-crafted request with
    a junk id reaches Postgres and raises InvalidTextRepresentation, which
    surfaces as a 500 -- an error shape that tells a prober their input got
    further than a well-formed miss would."""
    try:
        uuid.UUID(str(user_id))
    except (ValueError, AttributeError, TypeError):
        return None
    return auth_models.get_user_by_id(str(user_id))


def _require_shareable_job(job_id: str, user: dict) -> None:
    """A job must exist, belong to the caller, and be finished.

    Terminality is not a nicety. A running job's directory is still being
    written, so a copy taken mid-flight is a torn snapshot of files the
    engine has not finished with, and the copy would carry a `running`
    status.json that nothing will ever advance -- a job stuck non-terminal
    forever, which is exactly the failure the whole status.json design
    exists to prevent.
    """
    if read_spec(job_id) is None:
        raise HTTPException(status_code=404, detail=f"No such job: {job_id}")
    check_owner_or_admin("job", job_id, user)
    if not job_is_terminal(job_id):
        raise HTTPException(
            status_code=409,
            detail="Only a finished job can be shared. Wait for it to complete and try again.",
        )


@router.post("/api/shares")
def create_share(body: CreateShareIn, request: Request):
    """Offer a job or a project to another user. Copies nothing: the offer
    is a row, and the files are copied only if the recipient accepts."""
    user = _require_user(request)
    if body.kind not in VALID_KINDS:
        raise HTTPException(status_code=400, detail=f"kind must be one of {VALID_KINDS}")
    if str(body.to_user_id) == str(user["id"]):
        raise HTTPException(status_code=400, detail="You cannot share with yourself.")

    recipient = _lookup_user(body.to_user_id)
    if recipient is None or not recipient["is_active"]:
        # 404 rather than 403, matching check_owner_or_admin: a share dialog
        # must not become a way to test which user ids exist.
        raise HTTPException(status_code=404, detail="No such user")

    if body.kind == "job":
        _require_shareable_job(body.resource_id, user)
        label = _job_label(body.resource_id)
        size = job_family_size_bytes(body.resource_id)
    else:
        project = project_registry.get_project(body.resource_id)
        if project is None:
            raise HTTPException(status_code=404, detail=f"No such project: {body.resource_id}")
        check_owner_or_admin("project", body.resource_id, user)
        for job_id in project["job_ids"]:
            _require_shareable_job(job_id, user)
        label = project["name"]
        size = sum(job_family_size_bytes(j) for j in project["job_ids"])

    try:
        share = auth_models.create_share(
            body.kind, body.resource_id, str(user["id"]), str(body.to_user_id),
            note=body.note, source_label=label, size_bytes=size,
        )
    except pg_errors.UniqueViolation:
        raise HTTPException(
            status_code=409,
            detail=f"You have already offered this to {recipient['username']}, and they have not answered yet.",
        )
    auth_models.audit(str(user["id"]), "share.offer", body.resource_id,
                      {"kind": body.kind, "to": str(body.to_user_id), "size_bytes": size})
    return share


@router.get("/api/shares/inbox")
def share_inbox(request: Request):
    user = _require_user(request)
    return auth_models.list_inbox(str(user["id"]))


@router.get("/api/shares/outbox")
def share_outbox(request: Request):
    user = _require_user(request)
    return auth_models.list_outbox(str(user["id"]))


def _load_pending(share_id: str, user: dict, side: str) -> dict:
    """Fetch an offer the caller is entitled to act on, or 404.

    `side` is "to" for accept/decline and "from" for withdraw. A caller who
    is neither party gets the same 404 as one naming an id that does not
    exist, so share ids cannot be probed.
    """
    # Parsed here for the same reason _lookup_user parses: a junk id would
    # otherwise reach Postgres and 500 rather than 404, which tells a prober
    # their input was handled differently from a well-formed miss.
    try:
        uuid.UUID(str(share_id))
    except (ValueError, AttributeError, TypeError):
        raise HTTPException(status_code=404, detail="No such share")
    share = auth_models.get_share(share_id)
    if share is None:
        raise HTTPException(status_code=404, detail="No such share")
    party = share["to_user_id"] if side == "to" else share["from_user_id"]
    if party != str(user["id"]):
        raise HTTPException(status_code=404, detail="No such share")
    if share["status"] != "pending":
        raise HTTPException(status_code=409, detail=f"This share was already {share['status']}.")
    return share


@router.post("/api/shares/{share_id}/accept")
def accept_share(share_id: str, request: Request):
    """Copy the offered job (or project) into the caller's own ownership.

    The order here matters. Everything that can refuse the share is checked
    BEFORE any bytes are written, and the offer row is only marked accepted
    AFTER the copy succeeded, so a failure part-way leaves the offer
    pending and retryable rather than consumed. set_share_status is a
    compare-and-set on 'pending', so two accept clicks cannot both copy.
    """
    user = _require_user(request)
    share = _load_pending(share_id, user, "to")
    me = str(user["id"])

    if share["kind"] == "job":
        job_ids = [share["resource_id"]]
    else:
        project = project_registry.get_project(share["resource_id"])
        if project is None:
            raise HTTPException(status_code=410, detail="The sender has deleted this project.")
        job_ids = list(project["job_ids"])

    # Re-checked at accept, not trusted from the offer. An offer made on a
    # completed job can be accepted long after the sender deleted it or a
    # quota eviction reaped it; read_spec fails open and returns None, so
    # this is an assertion rather than an assumption.
    live = [j for j in job_ids if read_spec(j) is not None]
    if not live:
        raise HTTPException(status_code=410, detail="The sender has deleted what they shared.")

    # Size is recomputed rather than read from share["size_bytes"], which is
    # a display snapshot taken at offer time. A stale figure that
    # under-reports would let a share past the cap it exists to enforce.
    incoming = sum(job_family_size_bytes(j) for j in live)
    ok, why = storage_quota.fits_for_user(me, incoming)
    if not ok:
        raise HTTPException(status_code=409, detail=why)

    sender = share.get("from_username") or share["from_user_id"]
    copied: list[str] = []
    for job_id in live:
        new_id = copy_job(job_id, me, shared_from=sender)
        if new_id:
            copied.append(new_id)
    if not copied:
        raise HTTPException(status_code=500, detail="Nothing could be copied. Nothing was changed.")

    new_resource = copied[0]
    if share["kind"] == "project":
        source = project_registry.get_project(share["resource_id"]) or {}
        name = source.get("name") or share["source_label"] or "Shared project"
        new_project = project_registry.create_project(name, source.get("description", ""))
        record("project", new_project["project_id"], user)
        project_registry.add_jobs(new_project["project_id"], copied)
        new_resource = new_project["project_id"]

    resolved = auth_models.set_share_status(share_id, "accepted", copied_resource_id=new_resource)
    if resolved is None:
        # Another accept won the race between _load_pending and here, and it
        # has its own copy. Remove this one rather than leave the recipient
        # with two of everything.
        from app.chemistry.jobs.base import delete_job_dir
        for job_id in copied:
            delete_job_dir(job_id)
            auth_models.forget_ownership("job", job_id)
        raise HTTPException(status_code=409, detail="This share was already answered.")

    auth_models.audit(me, "share.accept", share["resource_id"],
                      {"kind": share["kind"], "from": share["from_user_id"],
                       "copied": new_resource, "size_bytes": incoming})
    return resolved


@router.post("/api/shares/{share_id}/decline")
def decline_share(share_id: str, request: Request):
    user = _require_user(request)
    _load_pending(share_id, user, "to")
    resolved = auth_models.set_share_status(share_id, "declined")
    if resolved is None:
        raise HTTPException(status_code=409, detail="This share was already answered.")
    auth_models.audit(str(user["id"]), "share.decline", resolved["resource_id"],
                      {"kind": resolved["kind"], "from": resolved["from_user_id"]})
    return resolved


@router.post("/api/shares/{share_id}/withdraw")
def withdraw_share(share_id: str, request: Request):
    """The sender takes back an offer the recipient has not answered. Only
    possible while pending, which is the whole reason the copy happens at
    accept rather than at offer."""
    user = _require_user(request)
    _load_pending(share_id, user, "from")
    resolved = auth_models.set_share_status(share_id, "withdrawn")
    if resolved is None:
        raise HTTPException(status_code=409, detail="This share was already answered.")
    auth_models.audit(str(user["id"]), "share.withdraw", resolved["resource_id"],
                      {"kind": resolved["kind"], "to": resolved["to_user_id"]})
    return resolved
