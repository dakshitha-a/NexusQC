"""Admin-only routes -- every handler here depends on require_admin, so a
non-admin caller gets a 403 before any handler body runs. See
server/admin_cli.py for the filesystem-local counterparts (bootstrap-admin,
reset-all) that deliberately do NOT go through this router, since they must
keep working even when no admin account can log in at all.
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.auth import models
from app.auth.deps import require_admin

router = APIRouter(prefix="/api/admin", tags=["admin"])


# --- Config (quotas, public-access toggle) ---------------------------


@router.get("/config")
def get_config(_admin: dict = Depends(require_admin)):
    keys = [
        "max_concurrent_jobs",
        "global_job_quota_bytes",
        "per_user_job_quota_bytes",
        "global_kb_quota_bytes",
        "per_user_kb_quota_bytes",
        "public_access_enabled",
    ]
    return {k: models.get_app_config(k) for k in keys}


class ConfigPatchIn(BaseModel):
    key: str
    value: object


@router.patch("/config")
def patch_config(body: ConfigPatchIn, admin: dict = Depends(require_admin)):
    models.set_app_config(body.key, body.value, updated_by=str(admin["id"]))
    models.audit(str(admin["id"]), "config_update", target=body.key, details={"value": body.value})
    return {"key": body.key, "value": body.value}


@router.post("/toggle-public-access")
def toggle_public_access(admin: dict = Depends(require_admin)):
    current = bool(models.get_app_config("public_access_enabled", default=True))
    new_value = not current
    models.set_app_config("public_access_enabled", new_value, updated_by=str(admin["id"]))
    models.audit(str(admin["id"]), "toggle_public_access", details={"enabled": new_value})
    return {"public_access_enabled": new_value}


# --- Users -------------------------------------------------------------


@router.get("/users")
def list_users(_admin: dict = Depends(require_admin)):
    return [
        {**{k: v for k, v in u.items()}, "id": str(u["id"])}
        for u in models.list_users()
    ]


@router.delete("/users/{user_id}")
def delete_user(user_id: str, admin: dict = Depends(require_admin)):
    if user_id == str(admin["id"]):
        raise HTTPException(status_code=400, detail="cannot delete your own account through this route")
    target = models.get_user_by_id(user_id)
    if target is None:
        raise HTTPException(status_code=404, detail="user not found")
    # Job/thread/KB file cleanup for this user is wired in during the
    # per-user storage retrofit (ownership_index-driven) -- this deletes
    # the identity row and, via ON DELETE CASCADE, their sessions and
    # ownership_index entries; it does not yet reach into data/jobs/ or
    # data/uploads/ to remove the underlying files themselves.
    owned_jobs = models.list_owned("job", user_id)
    owned_threads = models.list_owned("thread", user_id)
    models.delete_user(user_id)
    models.audit(str(admin["id"]), "delete_user", target=user_id, details={
        "username": target["username"], "owned_jobs": len(owned_jobs), "owned_threads": len(owned_threads),
    })
    return {"deleted": True, "owned_jobs": len(owned_jobs), "owned_threads": len(owned_threads)}


# --- Invite tokens -------------------------------------------------------


class InviteCreateIn(BaseModel):
    role: str = "user"
    email_hint: Optional[str] = None
    ttl_hours: int = 72


@router.post("/invites")
def create_invite(body: InviteCreateIn, admin: dict = Depends(require_admin)):
    if body.role not in ("user", "admin"):
        raise HTTPException(status_code=400, detail="role must be 'user' or 'admin'")
    row = models.create_invite_token(str(admin["id"]), body.role, body.email_hint, body.ttl_hours)
    models.audit(str(admin["id"]), "create_invite", target=row["token"], details={"role": body.role})
    return row


@router.get("/invites")
def list_invites(_admin: dict = Depends(require_admin)):
    return models.list_invite_tokens()


# --- Bug reports -----------------------------------------------------------


@router.get("/bug-reports")
def list_bug_reports(_admin: dict = Depends(require_admin)):
    return models.list_bug_reports()


class BugReportPatchIn(BaseModel):
    status: str


@router.patch("/bug-reports/{report_id}")
def set_bug_report_status(report_id: str, body: BugReportPatchIn, admin: dict = Depends(require_admin)):
    if body.status not in ("open", "closed"):
        raise HTTPException(status_code=400, detail="status must be 'open' or 'closed'")
    models.set_bug_report_status(report_id, body.status)
    models.audit(str(admin["id"]), "bug_report_status", target=report_id, details={"status": body.status})
    return {"id": report_id, "status": body.status}
