"""Admin-only routes -- every handler here depends on require_admin, so a
non-admin caller gets a 403 before any handler body runs. See
server/admin_cli.py for the filesystem-local counterparts (bootstrap-admin,
reset-all) that deliberately do NOT go through this router, since they must
keep working even when no admin account can log in at all.
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Response
from fastapi.responses import FileResponse
from pydantic import BaseModel

from app.auth import models
from app.auth.deps import require_admin
from app.auth.redis_session import clear_active_session
from app.auth.storage_quota import (
    get_quota_config,
    invalidate_usage_report_cache,
    purge_all_jobs,
    purge_orphaned_jobs,
    purge_all_kb,
    purge_all_threads,
    purge_user_data,
    usage_report,
)
from app.config import BUG_REPORTS_DIR, MAX_CONCURRENT_JOBS

router = APIRouter(prefix="/api/admin", tags=["admin"])


# --- Config (quotas, concurrency, public-access toggle) ---------------------
#
# Quota/concurrency keys are resolved through app/auth/storage_quota.py's
# get_quota_config() (admin-set app_config value, falling back to
# app/config.py's DEFAULT_* constants) rather than a raw models.get_app_config
# per key -- this is the fix for "can quotas be set from the admin console?":
# app_config already stored whatever an admin PATCHed here, but nothing
# outside this route ever actually read it back until storage_quota.py's
# enforcement functions were wired up to consult it.


@router.get("/config")
def get_config(_admin: dict = Depends(require_admin)):
    cfg = get_quota_config()
    # Read-only context alongside max_concurrent_jobs_total -- see that
    # key's own clamping note in PATCH below: this is the hard ceiling a
    # PATCH can never exceed, since it's also JobManager's fixed
    # ThreadPoolExecutor size (not resizable at runtime).
    cfg["max_concurrent_jobs_pool_size"] = MAX_CONCURRENT_JOBS
    return cfg


_EDITABLE_CONFIG_KEYS = {
    "per_user_kb_quota_bytes",
    "per_user_uploads_quota_bytes",
    "per_user_jobs_and_chat_quota_bytes",
    "global_storage_quota_bytes",
    "max_concurrent_jobs_total",
    "max_concurrent_jobs_per_user",
}


class ConfigPatchIn(BaseModel):
    key: str
    value: object


@router.patch("/config")
def patch_config(body: ConfigPatchIn, admin: dict = Depends(require_admin)):
    if body.key not in _EDITABLE_CONFIG_KEYS:
        raise HTTPException(status_code=400, detail=f"Unknown or non-editable config key: {body.key}")
    if body.key == "max_concurrent_jobs_total":
        # This figure gates JobManager._wait_for_resources' concurrent-jobs
        # admission check, but JobManager's own ThreadPoolExecutor is sized
        # once, at process start, from QC_AGENT_MAX_CONCURRENT_JOBS -- it
        # cannot be resized at runtime. A value above that pool size would
        # silently do nothing once the pool itself became the binding
        # constraint, so this refuses rather than accepting a number that
        # would quietly never take effect; raising the real ceiling needs
        # QC_AGENT_MAX_CONCURRENT_JOBS plus a process restart.
        if not isinstance(body.value, (int, float)) or int(body.value) > MAX_CONCURRENT_JOBS:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"max_concurrent_jobs_total cannot exceed {MAX_CONCURRENT_JOBS} (the process's own "
                    f"QC_AGENT_MAX_CONCURRENT_JOBS-sized worker pool, fixed at startup) -- raising it further "
                    f"requires setting QC_AGENT_MAX_CONCURRENT_JOBS and restarting the server."
                ),
            )
    if body.key in {
        "per_user_kb_quota_bytes", "per_user_uploads_quota_bytes", "per_user_jobs_and_chat_quota_bytes",
        "global_storage_quota_bytes", "max_concurrent_jobs_total", "max_concurrent_jobs_per_user",
    } and (not isinstance(body.value, (int, float)) or body.value <= 0):
        raise HTTPException(status_code=400, detail=f"{body.key} must be a positive number")
    models.set_app_config(body.key, body.value, updated_by=str(admin["id"]))
    models.audit(str(admin["id"]), "config_update", target=body.key, details={"value": body.value})
    # A quota edit changes what usage_report() should show alongside the
    # current usage figures (the quota_bytes fields embedded in its
    # response) -- invalidate the cache below so that shows up on the very
    # next GET /api/admin/storage rather than waiting out its TTL.
    invalidate_usage_report_cache()
    return {"key": body.key, "value": body.value}


# --- Storage (live usage readout + manual purges) ---------------------------


@router.get("/storage")
def get_storage(_admin: dict = Depends(require_admin)):
    """Per-user and global storage usage against current quotas -- backed
    by a short-TTL cache (see usage_report's own docstring for why, and
    invalidate_usage_report_cache for what forces an early refresh) rather
    than a fresh disk/Postgres walk on every call."""
    return usage_report()


@router.post("/purge/jobs")
def purge_jobs(admin: dict = Depends(require_admin)):
    """Deletes every TERMINAL job (never pending/running) for every user
    in this deployment. Audit-logged by purge_all_jobs itself."""
    purged = purge_all_jobs(str(admin["id"]))
    return {"purged_job_ids": purged, "count": len(purged)}


@router.post("/purge/orphaned-jobs")
def purge_orphaned(admin: dict = Depends(require_admin)):
    """Deletes job directories that carry no spec.json -- disk that no
    part of the app can see, since _iter_job_ids() skips them, so nothing
    lists them, purges them, or counts them against a quota. Destroys no
    user's data, which is why it is its own action rather than something
    an admin can only get at by purging every job in the deployment.
    Audit-logged by purge_orphaned_jobs itself."""
    return purge_orphaned_jobs(str(admin["id"]))


@router.post("/purge/kb")
def purge_kb(admin: dict = Depends(require_admin)):
    """Deletes every user-uploaded KB source (never the pre-seeded/shared
    manual corpus) for every user in this deployment. Audit-logged by
    purge_all_kb itself."""
    purged = purge_all_kb(str(admin["id"]))
    return {"purged_sources": purged, "count": len(purged)}


class PurgeThreadsIn(BaseModel):
    # Defaults to leaving pinned conversations alone -- see
    # purge_all_threads' own docstring for why that's a separate,
    # explicit opt-in rather than the default of this button.
    include_pinned: bool = False


@router.post("/purge/threads")
def purge_threads(body: PurgeThreadsIn, admin: dict = Depends(require_admin)):
    """Deletes every conversation (and its underlying chat-history
    storage) for every user in this deployment. Audit-logged by
    purge_all_threads itself."""
    purged = purge_all_threads(str(admin["id"]), include_pinned=body.include_pinned)
    return {"purged_thread_ids": purged, "count": len(purged)}


# --- Audit log ---------------------------------------------------------


@router.get("/audit-log")
def get_audit_log(_admin: dict = Depends(require_admin)):
    """The immutable admin-action history (db.py's admin_audit_log table,
    protected at the database level from update/delete/truncate -- see its
    schema comment) -- viewable by every admin, records every config
    change and every storage purge this router performs, plus anything
    else that calls models.audit()."""
    rows = models.list_audit_log()
    return [{**r, "id": str(r["id"]), "actor_user_id": str(r["actor_user_id"]) if r["actor_user_id"] else None} for r in rows]


# POST /toggle-public-access was removed on 2026-08-25 along with the public
# nginx listener it governed. Nothing can reach this deployment over a public
# channel any more, so a switch for it was a control with nothing behind it.


# --- Users -------------------------------------------------------------


def _refuse_if_last_active_admin(target: dict, verb: str) -> None:
    """Blocks an action that would leave the deployment with no admin who
    can still log in.

    Reachability, stated honestly: for DELETE this is defence in depth
    rather than a live hole, since that route already refuses self-delete
    and the caller passed require_admin, so at least the caller survives
    any successful delete. For the deactivate route it is genuinely
    load-bearing -- without it an admin can deactivate every other admin
    and then, because deactivation is not self-blocked the way deletion
    is, deactivate themselves and lock the deployment out entirely. The
    only recovery from that is server/admin_cli.py's reset-all, which
    destroys every account.

    Kept on both routes deliberately: the invariant is "there is always a
    usable admin", and pinning it to one route would leave the other free
    to break it if either guard is ever relaxed."""
    if target["role"] != "admin" or not target["is_active"]:
        return
    if models.count_active_admins() <= 1:
        raise HTTPException(
            status_code=409,
            detail=(
                f"refusing: this is the last active admin account, and it cannot be {verb} "
                "without locking every administrator out of the deployment. Promote or "
                "activate another admin first."
            ),
        )


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
    _refuse_if_last_active_admin(target, "deleted")
    # Deletes this user's jobs/KB uploads/threads from disk BEFORE the
    # users row goes away -- previously this only deleted the identity row
    # (sessions/ownership_index cascade via FK, but nothing ever reached
    # data/jobs/ or data/uploads/), leaving every file they'd ever created
    # as a permanently "unowned" orphan that app/auth/ownership.py's
    # check_owner_or_admin treats as accessible to EVERYONE, not to no
    # one -- confirmed empirically: a deleted user's completed job stayed
    # fully readable by a totally unrelated user. purge_user_data() also
    # cancels (and waits for) any of this user's still-pending/running
    # jobs before purging, closing the same bug for a job that was
    # mid-flight at delete time -- see its own docstring.
    purged = purge_user_data(user_id)
    models.delete_user(user_id)
    models.audit(str(admin["id"]), "delete_user", target=user_id, details={
        "username": target["username"],
        "purged_jobs": len(purged["job_ids"]), "purged_kb_sources": len(purged["kb_sources"]),
        "purged_threads": len(purged["thread_ids"]),
    })
    return {
        "deleted": True,
        "purged_jobs": len(purged["job_ids"]),
        "purged_kb_sources": len(purged["kb_sources"]),
        "purged_threads": len(purged["thread_ids"]),
    }


class UserActiveIn(BaseModel):
    is_active: bool


@router.patch("/users/{user_id}")
def set_user_active(user_id: str, body: UserActiveIn, admin: dict = Depends(require_admin)):
    """Suspends or restores an account -- the non-destructive counterpart to
    DELETE /users/{user_id}, which also purges everything the user owns.

    Self-deactivation is refused for the same reason self-deletion is: it
    is never what an admin means to do, and it is unrecoverable from the
    UI (a deactivated admin cannot log back in to undo it).

    Deactivation also clears the Redis active-session key, so an already
    open session stops working immediately rather than at its next
    request. That is belt-and-braces -- get_current_user re-reads the user
    row and would reject the inactive user anyway -- but leaving a live
    session key behind for a suspended account is untidy."""
    if user_id == str(admin["id"]) and not body.is_active:
        raise HTTPException(
            status_code=400, detail="cannot deactivate your own account through this route"
        )
    target = models.get_user_by_id(user_id)
    if target is None:
        raise HTTPException(status_code=404, detail="user not found")
    if not body.is_active:
        _refuse_if_last_active_admin(target, "deactivated")
    updated = models.set_user_active(user_id, body.is_active)
    if not body.is_active:
        clear_active_session(user_id)
    models.audit(
        str(admin["id"]),
        "set_user_active",
        target=user_id,
        details={"username": target["username"], "is_active": body.is_active},
    )
    return {**updated, "id": str(updated["id"])}


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


@router.post("/invites/{token}/revoke")
def revoke_invite(token: str, admin: dict = Depends(require_admin)):
    """Soft-revokes an unredeemed invite so it can no longer register an
    account.

    POST .../revoke rather than DELETE /invites/{token}: the row is
    deliberately kept (it stays in the admin list marked Revoked, and the
    audit log already holds a permanent create_invite entry for it), and
    DELETE would imply it was actually removed.

    Revoking an already-revoked token is a 200 no-op rather than a
    conflict: the console's two-click confirm plus its ["admin"] query
    invalidation makes a double submit an ordinary race, not something
    worth surfacing as an error. Revoking a *redeemed* token IS an error,
    though -- that account already exists, so revocation would imply an
    undo it cannot deliver.

    Invite tokens are 32 chars of ascii_letters + digits (see
    models._generate_token), so the value is path-safe as-is."""
    row = models.revoke_invite_token(token)
    if row is None:
        existing = models.get_invite_token(token)
        if existing is None:
            raise HTTPException(status_code=404, detail="invite token not found")
        raise HTTPException(
            status_code=400,
            detail="this invite has already been redeemed; revoking it would not remove the account",
        )
    models.audit(str(admin["id"]), "revoke_invite", target=token, details={"role": row["role"]})
    return row


# --- Password reset tokens -----------------------------------------------
#
# There is no mail server in this deployment, so there is no self-service
# "email me a reset link". An admin issues a single-use token and hands it
# over out of band; the person redeems it at /?reset=<token> on the login
# screen. The admin never learns the new password, which is the reason this
# is preferable to setting a temporary one for them.


class PasswordResetCreateIn(BaseModel):
    ttl_hours: int = 2


@router.post("/users/{user_id}/password-reset")
def create_password_reset(user_id: str, body: PasswordResetCreateIn,
                          admin: dict = Depends(require_admin)):
    """Issues a reset token for any account, including another admin's and
    the caller's own.

    Both of those are deliberate. Recovering a locked-out colleague is the
    case this exists for, and an admin who still holds a session but has
    forgotten their password is in exactly the same position as anyone
    else. There is no last-admin guard here of the kind delete and suspend
    carry: a reset does not remove anyone's access, it restores it.

    The token is returned once, in this response, and never appears in the
    audit log -- an audit row an admin can read is not a place to put a
    credential that lets its reader take over an account."""
    if body.ttl_hours < 1 or body.ttl_hours > 72:
        raise HTTPException(status_code=400, detail="ttl_hours must be between 1 and 72")
    target = models.get_user_by_id(user_id)
    if target is None:
        raise HTTPException(status_code=404, detail="user not found")
    if not target["is_active"]:
        raise HTTPException(
            status_code=400,
            detail="this account is suspended; restore it before issuing a reset",
        )
    row = models.create_password_reset_token(str(admin["id"]), user_id, body.ttl_hours)
    models.audit(str(admin["id"]), "create_password_reset", target=user_id, details={
        "username": target["username"],
        "expires_at": row["expires_at"].isoformat(),
    })
    return {**row, "user_id": str(row["user_id"]), "username": target["username"]}


@router.get("/password-resets")
def list_password_resets(_admin: dict = Depends(require_admin)):
    return [{**r, "user_id": str(r["user_id"]),
             "created_by": str(r["created_by"]) if r["created_by"] else None}
            for r in models.list_password_reset_tokens()]


@router.post("/password-resets/{token}/revoke")
def revoke_password_reset(token: str, admin: dict = Depends(require_admin)):
    """Cancels a reset token that has not been used yet -- the answer to
    "I sent that to the wrong person".

    Revoking an already-revoked token is a 200 no-op, matching revoke_invite.
    Revoking a USED one is a 400: the password has already been changed, and
    revocation cannot undo that. Issue another reset instead."""
    row = models.revoke_password_reset_token(token)
    if row is None:
        existing = models.get_password_reset_token(token)
        if existing is None:
            raise HTTPException(status_code=404, detail="reset token not found")
        raise HTTPException(
            status_code=400,
            detail="this reset token has already been used; issue a new one instead",
        )
    models.audit(str(admin["id"]), "revoke_password_reset", target=token)
    return {**row, "user_id": str(row["user_id"])}


# --- Bug reports -----------------------------------------------------------


@router.get("/bug-reports")
def list_bug_reports(_admin: dict = Depends(require_admin)):
    return models.list_bug_reports()


class BugReportPatchIn(BaseModel):
    # Both optional, at least one required. `status` used to be mandatory,
    # which would force every archive call to restate the report's current
    # status -- and race it, since the value would come from whatever the
    # admin's list was showing rather than from the database.
    status: Optional[str] = None
    archived: Optional[bool] = None


@router.patch("/bug-reports/{report_id}")
def patch_bug_report(report_id: str, body: BugReportPatchIn, admin: dict = Depends(require_admin)):
    if body.status is None and body.archived is None:
        raise HTTPException(status_code=400, detail="provide 'status', 'archived', or both")
    if body.status is not None:
        if body.status not in ("open", "closed"):
            raise HTTPException(status_code=400, detail="status must be 'open' or 'closed'")
        models.set_bug_report_status(report_id, body.status)
        models.audit(
            str(admin["id"]), "bug_report_status", target=report_id, details={"status": body.status}
        )
    if body.archived is not None:
        models.set_bug_report_archived(report_id, body.archived)
        models.audit(
            str(admin["id"]),
            "bug_report_archived",
            target=report_id,
            details={"archived": body.archived},
        )
    return {"id": report_id, "status": body.status, "archived": body.archived}


@router.delete("/bug-reports/{report_id}", status_code=204)
def delete_bug_report(report_id: str, admin: dict = Depends(require_admin)):
    """Destroys a report and its screenshots. Archiving is the reversible
    option; this one is not, which is why the UI puts it behind a confirm."""
    models.audit(str(admin["id"]), "bug_report_delete", target=report_id)
    models.delete_bug_report(report_id)
    return Response(status_code=204)


@router.get("/bug-reports/attachments/{attachment_id}")
def get_bug_report_attachment(attachment_id: str, admin: dict = Depends(require_admin)):
    """Serves one screenshot.

    Admin-only and checked explicitly, via require_admin on this handler,
    rather than through the generic ownership helper. That is deliberate: a
    resource with no row in ownership_index is readable by EVERYONE under
    check_owner_or_admin, not by no-one -- exactly the shape of a bug this
    codebase has already been bitten by once (see purge_user_data's docstring
    and the delete_user route's comment). Bug-report attachments have no
    ownership_index row and are never going to, so they must never be routed
    through it.
    """
    row = models.get_bug_report_attachment(attachment_id)
    if row is None:
        raise HTTPException(status_code=404, detail="attachment not found")
    path = (BUG_REPORTS_DIR / str(row["report_id"]) / str(row["stored_name"])).resolve()
    # stored_name is server-generated, but this is cheap and means a bad row
    # (hand-edited, or written by some future code path) cannot read outside
    # the tree.
    if BUG_REPORTS_DIR.resolve() not in path.parents:
        raise HTTPException(status_code=403, detail="attachment path escapes the bug-reports directory")
    if not path.is_file():
        raise HTTPException(status_code=404, detail="attachment file is missing from disk")
    return FileResponse(path, media_type=str(row["content_type"]))
