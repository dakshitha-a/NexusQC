"""Uploaded geometry (.xyz) and blind engine-input (.inp/.input/.json)
file management -- list/upload/delete/clear-all, ownership-scoped.
Mirrors server/routes/kb.py's shape (plain `def` handlers, same
UploadFile/quota/ownership pattern), against its own store
(app/uploads/store.py) and its own quota (app/uploads/quota.py) rather
than reusing KB's -- see app/config.py's GEOMETRY_UPLOADS_DIR docstring for
why the two must not share a directory.

Attach semantics (injecting an uploaded geometry into a thread's molecule
state, or materializing a 3+-frame upload as a geometry_set job) are NOT
here -- they belong on the chat-route side, which alone is allowed to touch
graph state under its lock (see server/routes/chat.py and CLAUDE.md's
"server/routes/jobs.py is deliberately lock-free" rule, which applies here
identically: this router must never call read_state()/take the graph lock).
"""
from __future__ import annotations

import io

from fastapi import APIRouter, File, HTTPException, Request, UploadFile
from fastapi.responses import StreamingResponse

from app.auth.ownership import check_owner_or_admin, current_user_or_none, record as record_ownership
from app.uploads.quota import QUOTA_BYTES as UPLOADS_QUOTA_BYTES
from app.uploads.quota import current_usage_bytes as uploads_storage_usage_bytes
from app.uploads.quota import enforce_quota
from app.uploads.store import add_upload, clear_uploads, delete_upload, get_upload, list_uploads, read_upload_content

router = APIRouter()


def _owner_key(request: Request) -> str | None:
    """The id to WRITE a new upload under -- the caller's own id, or None
    for a no-auth deployment. Mirrors kb.py's own _owner_key exactly."""
    user = current_user_or_none(request)
    return str(user["id"]) if user is not None else None


def _owner_filter(request: Request) -> str | None:
    """The filter to READ/DELETE with -- None for admin or no-auth (see/
    touch everything), else the caller's own id."""
    user = current_user_or_none(request)
    if user is None or user["role"] == "admin":
        return None
    return str(user["id"])


@router.get("/api/uploads")
def get_uploads(request: Request):
    return list_uploads(owner_filter=_owner_filter(request))


@router.get("/api/uploads/quota")
def get_uploads_quota(request: Request):
    """Storage usage for the Files panel's usage display. With no auth
    configured: the flat app/uploads/quota.py cap shared by everyone. With
    auth configured: the CALLER'S OWN uploads usage against their own
    per-user quota (see app/auth/storage_quota.py)."""
    user = current_user_or_none(request)
    if user is not None:
        from app.auth.storage_quota import usage_report
        report = usage_report()
        row = next((r for r in report["per_user"] if r["user_id"] == str(user["id"])), None)
        if row is not None:
            return {
                "used_bytes": row["upload_bytes"], "quota_bytes": row["upload_quota_bytes"],
                "category": "per_user_uploads",
            }
    return {"used_bytes": uploads_storage_usage_bytes(), "quota_bytes": UPLOADS_QUOTA_BYTES, "category": "global"}


@router.post("/api/uploads", status_code=201)
def upload_file(request: Request, file: UploadFile = File(...)):
    owner = _owner_key(request)
    content = file.file.read()
    try:
        record = add_upload(owner, file.filename or "upload", content)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    user = current_user_or_none(request)
    record_ownership("upload", record["id"], user)
    enforce_quota()
    return record


@router.delete("/api/uploads/{upload_id}")
def remove_upload(upload_id: str, request: Request):
    check_owner_or_admin("upload", upload_id, current_user_or_none(request))
    owner_filter = _owner_filter(request)
    # A non-admin caller's owner_filter is their own id; get_upload(owner,
    # id) only finds a record actually stored under that owner's own
    # directory, so this can never delete another user's upload even
    # though check_owner_or_admin above is the primary gate.
    record = get_upload(owner_filter, upload_id) if owner_filter is not None else _find_any_owner(upload_id)
    if record is None:
        raise HTTPException(status_code=404, detail=f"No such upload: {upload_id}")
    delete_upload(record["owner"], upload_id)
    return {"deleted": upload_id}


def _find_any_owner(upload_id: str) -> dict | None:
    """Admin/no-auth delete: the id alone doesn't say which owner's
    directory it lives under, so resolve it from the full listing first."""
    return next((r for r in list_uploads(owner_filter=None) if r["id"] == upload_id), None)


@router.delete("/api/uploads")
def clear_all_uploads(request: Request):
    """Clears the CALLER'S OWN uploads only -- never another user's, even
    for an admin, matching KB's clear-all being scoped to whoever asked
    for it. There is no cross-user "clear everyone's uploads" surface
    here; that lives in the admin console via
    app/auth/storage_quota.py's purge_all_uploads, same split as KB's."""
    owner = _owner_key(request)
    deleted = clear_uploads(owner)
    return {"deleted": deleted}


@router.get("/api/uploads/{upload_id}/content")
def get_upload_content(upload_id: str, request: Request):
    check_owner_or_admin("upload", upload_id, current_user_or_none(request))
    owner_filter = _owner_filter(request)
    record = get_upload(owner_filter, upload_id) if owner_filter is not None else _find_any_owner(upload_id)
    if record is None:
        raise HTTPException(status_code=404, detail=f"No such upload: {upload_id}")
    result = read_upload_content(record["owner"], upload_id)
    if result is None:
        raise HTTPException(status_code=404, detail=f"No such upload: {upload_id}")
    content, _ = result
    return StreamingResponse(io.BytesIO(content), media_type="text/plain")
