"""Admin-only routes -- every handler here depends on require_admin, so a
non-admin caller gets a 403 before any handler body runs. See
server/admin_cli.py for the filesystem-local counterparts (bootstrap-admin,
reset-all) that deliberately do NOT go through this router, since they must
keep working even when no admin account can log in at all.
"""
from __future__ import annotations

import json
import os
import time
import uuid
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
from app.auth.deploy_signing import sign_deploy_request
from app.config import BUG_REPORTS_DIR, DEPLOY_DIR, MAX_CONCURRENT_JOBS

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
        # R-088: and mark the durable rows revoked, not just the Redis key.
        # The Redis key is what actually stops the token working; the sessions
        # table is the record of who was signed in, and leaving a suspended
        # account's rows marked live makes that record say the opposite of
        # what just happened.
        models.revoke_sessions_for_user(user_id)
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
    # R-089: the same bound the password-reset route below has carried all
    # along. An invite can mint another admin, and an unbounded ttl_hours let
    # one sit redeemable for years, which is a credential with no expiry
    # rather than an invitation. 72 hours is the reset route's ceiling and
    # there is no reason for the two to differ.
    if body.ttl_hours < 1 or body.ttl_hours > 72:
        raise HTTPException(status_code=400, detail="ttl_hours must be between 1 and 72")
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
    # R-082: look the report up first. Without this the handler answered 200
    # for a report that does not exist, because an UPDATE matching no rows is
    # not an error, and it answered 500 for a malformed id, because a junk
    # string reaches Postgres as a uuid literal. Both matter more than they
    # look: each wrote an audit row claiming a report had been changed, and
    # the audit log is documented as append-only and therefore has to be
    # true. get_bug_report parses the id, so both cases arrive here as None.
    if models.get_bug_report(report_id) is None:
        raise HTTPException(status_code=404, detail="bug report not found")
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


# --- Deployment: what is running, and who would an update interrupt --------
#
# Both routes here are read-only and exist to answer the two questions an
# admin has to answer before deciding to update: what is this deployment
# actually running, and is anybody in the middle of something. Neither can
# change anything, so they are safe to poll from an open panel.


@router.get("/deployment")
def get_deployment(_admin: dict = Depends(require_admin)):
    """What this deployment is running, as far as the api process can tell.

    The api commit is baked into the image as QC_AGENT_BUILD_COMMIT (see the
    Dockerfile), because the OCI revision label it mirrors is only legible to
    `docker inspect` from the host -- a process cannot read its own image's
    labels.

    The *frontend* commit is deliberately absent. nginx serves the bundle from
    a host bind mount that this container does not have, and the copy at
    /app/frontend/dist inside the image is the image's own, which says nothing
    about what is being served. The browser knows its own build sha (baked in
    by vite.config.ts as __BUILD_SHA__) and compares it against /api/version
    itself. Reporting a number from in here that we cannot actually observe is
    exactly the sort of confident wrong answer the update stamps exist to
    avoid.
    """
    commit = os.environ.get("QC_AGENT_BUILD_COMMIT") or "unknown"
    runner = _runner_state()
    return {
        "api_commit": commit,
        # `unknown` means a hand-run `docker compose build` with no stamp
        # passed. Every reader treats it as "cannot tell, assume stale",
        # never as up to date.
        "api_commit_known": commit != "unknown",
        "runner": runner,
        "history": _update_history(),
    }


# --- The host-side runner -----------------------------------------------
#
# The api cannot update its own deployment and is deliberately not given the
# means to: it has no checkout, no docker socket and no npm, and `compose up
# -d` would destroy the container serving the request anyway. Mounting the
# docker socket in here would fix all of that and turn any RCE in a
# multi-user web app into host root, which is not a trade worth making.
#
# So a request is written into data/deploy -- the one directory the container
# and the host share -- and scripts/deploy_runner.sh, running on the host as
# the operator, picks it up. Nothing written here is ever executed: the runner
# accepts an action from a fixed set and resolves the ref itself.

# How stale the runner's heartbeat may be before the panel stops offering to
# run anything. The runner refreshes it on every trigger and every watch tick;
# 90s is generous enough not to flap and short enough that a dead runner is
# reported as dead rather than as slow.
_RUNNER_STALE_SECONDS = 90


def _runner_state() -> dict:
    """Whether anything is actually listening.

    Installed-but-dead and installed-and-working look identical from in here
    otherwise, and an Apply button that silently does nothing is worse than no
    button -- so the panel shows the host command instead when this says the
    runner is not alive.
    """
    path = DEPLOY_DIR / "runner.json"
    try:
        doc = json.loads(path.read_text())
        alive_at = float(doc.get("alive_at") or 0)
    except (OSError, ValueError, TypeError):
        return {"installed": False, "alive": False, "last_seen": None}
    age = time.time() - alive_at
    return {
        "installed": True,
        "alive": age < _RUNNER_STALE_SECONDS,
        "last_seen": alive_at,
        "age_seconds": round(age, 1),
    }


def _update_history(limit: int = 20) -> list[dict]:
    """Past updates, newest first.

    Read from the mirror the runner writes, because .update-log lives at the
    repo root and only ./data is shared with this container. A deployment that
    has never been updated has no log, which is not an error.
    """
    path = DEPLOY_DIR / "update-log.txt"
    try:
        lines = path.read_text().strip().splitlines()
    except OSError:
        return []
    out = []
    for line in reversed(lines[-limit:]):
        parts = line.split()
        if len(parts) < 4:
            continue
        out.append({"verb": parts[0], "at": parts[1], "to": parts[2], "from": parts[3]})
    return out


class DeployRequest(BaseModel):
    # Constrained to what the runner will honour. Anything else is refused
    # here rather than written out and refused there, so the caller gets a
    # 400 instead of a request that quietly fails later.
    action: str
    ref: Optional[str] = None
    drain: bool = True
    force: bool = False


_DEPLOY_ACTIONS = {"ping", "report", "update", "rollback"}


@router.post("/deploy")
def post_deploy(req: DeployRequest, admin: dict = Depends(require_admin)):
    """Ask the host-side runner to do one thing, and return the id to watch.

    The id is also the path segment the browser polls through nginx while the
    api is being recreated, which is why it is generated here (a uuid) rather
    than taken from the caller.
    """
    if req.action not in _DEPLOY_ACTIONS:
        raise HTTPException(status_code=400, detail=f"unknown action: {req.action}")

    state = _runner_state()
    # Gated on `installed`, not on `alive`, and the difference matters. The
    # runner is triggered by a systemd .path unit watching for the request
    # file, so on its own it only runs -- and only refreshes its heartbeat --
    # when there is work. Requiring a FRESH heartbeat to accept a request
    # therefore deadlocks: no heartbeat, so no request, so no run, so no
    # heartbeat, and the Apply button works exactly once. A timer keeps the
    # heartbeat current (see scripts/install_updater.sh), but the gate must
    # not depend on that timer having fired recently.
    #
    # A truly dead runner is still caught, just one step later: the request is
    # written, nothing claims it, and the panel shows the run sitting at
    # "queued" rather than pretending it succeeded.
    if not state["installed"] and req.action != "ping":
        # A ping is allowed through precisely so the panel can find out that
        # there is no runner; anything else would sit unclaimed forever.
        raise HTTPException(
            status_code=503,
            detail="the deployment runner is not running on the host; "
                   "run scripts/update.sh there instead",
        )

    pending = DEPLOY_DIR / "request.json"
    if pending.exists():
        raise HTTPException(status_code=409, detail="a deployment request is already queued")

    deploy_id = uuid.uuid4().hex[:12]
    DEPLOY_DIR.mkdir(parents=True, exist_ok=True)
    payload = {
        "id": deploy_id,
        "action": req.action,
        "ref": req.ref or "",
        "drain": bool(req.drain),
        "force": bool(req.force),
        "requested_by": str(admin["id"]),
        "requested_at": time.time(),
    }
    # Signed, because until now the file WAS the authority. data/ is
    # bind-mounted into this container, the runner polls
    # data/deploy/request.json at that fixed name and runs update.sh or
    # --rollback on the host from what it finds, and it never read
    # requested_by. So anything that could write a file into data/ could ask
    # the host to redeploy, and a knowledge-base upload could (R-002). The
    # secret lives in .env, which is not in the bind mount.
    payload["signature"] = sign_deploy_request(payload)
    # Written then renamed: a systemd .path unit fires on the file existing,
    # and it must never see a half-written one.
    tmp = DEPLOY_DIR / f".request.{deploy_id}.tmp"
    tmp.write_text(json.dumps(payload, indent=2))
    tmp.replace(pending)

    models.audit(str(admin["id"]), f"deploy_{req.action}", target=deploy_id,
                 details={"ref": req.ref or "", "drain": req.drain, "force": req.force})
    return {"id": deploy_id, "action": req.action}


@router.get("/deploy/{deploy_id}")
def get_deploy(deploy_id: str, _admin: dict = Depends(require_admin)):
    """Status, log tail and impact report for one run.

    The same status.json is served unauthenticated by nginx at
    /deploy-status/<id>/, which is what the browser falls back to while this
    route is unreachable. This one adds the log and the report, which are only
    useful to an admin and only readable while the api is up.
    """
    if not deploy_id.replace("-", "").replace("_", "").isalnum():
        raise HTTPException(status_code=400, detail="bad id")
    d = DEPLOY_DIR / deploy_id
    if not d.is_dir():
        raise HTTPException(status_code=404, detail="no such deployment run")

    def _read_json(name):
        try:
            return json.loads((d / name).read_text())
        except (OSError, ValueError):
            return None

    log = ""
    try:
        # Tail rather than the whole thing: a build log is large and the panel
        # only ever shows the end of it.
        log = (d / "log.txt").read_text()[-20000:]
    except OSError:
        pass

    changes: list[str] = []
    try:
        changes = [ln for ln in (d / "changes.txt").read_text().splitlines() if ln.strip()]
    except OSError:
        pass

    return {
        "id": deploy_id,
        "status": _read_json("status.json") or {"state": "unknown"},
        "request": _read_json("request.json"),
        "report": _read_json("report.json"),
        # What the update brings in, as one line per commit. The impact report
        # answers "what would break"; this answers "what would change", which
        # is the other half of the decision and otherwise means reading the
        # repository on the host.
        "changes": changes,
        "log": log,
    }


@router.get("/activity")
def get_activity(admin: dict = Depends(require_admin)):
    """Who is mid-calculation, and who has a live stream open.

    Assembled from state that already exists rather than from new bookkeeping:
    the job status files on disk, the ownership index, and the SSE hub's
    subscriber table. Nothing here is written down anywhere, so it cannot go
    stale or need cleaning up.

    Note what "active" does and does not mean. `users.last_login_at` is when
    somebody logged in, not when they last did anything -- the sessions table
    records no last-seen -- so a running job or an open stream is the real
    signal, and last_login_at is context rather than evidence.
    """
    from app.chemistry.jobs.base import is_master_spec, job_index
    from server.sse import hub

    job_owners = models.all_owners("job")
    thread_owners = models.all_owners("thread")

    # One walk, both counts. Master jobs (a scan, an ensemble) are excluded
    # for the same reason the scheduler's admission gate excludes them: a
    # master is marked running for its whole lifetime as bookkeeping and is
    # never itself a dispatched subprocess, so counting it would claim work
    # that nothing is doing.
    # R-051: this used to walk JOBS_DIR and read two JSON files per job on
    # every call, uncached, while the admin console polled it. It now reads
    # base.py's shared ~1 s index, the same one the three orchestrators and
    # the scheduler's admission gate read, so an open console costs one walk
    # per second across the whole process rather than one per poll on top of
    # everything else. The neighbouring GET /api/admin/storage was given a
    # 20 s cache for exactly this reason; this answers a question that moves
    # faster, so it gets the short index rather than a long cache.
    #
    # What that costs, stated plainly because a caller could reasonably assume
    # otherwise: this answer can be up to a second old. A job that started
    # half a second ago in another process may not be in it yet. That is
    # acceptable for the two things this route is for. The admin console polls
    # it every few seconds and a second of lag is invisible there; and
    # update.sh's "is anything running" question is a snapshot whatever it
    # reads, since a job can start in the moment between the answer and the
    # decision, so a second of staleness does not change the shape of that
    # race, only its width. A caller that genuinely needs a current answer
    # should invalidate the index first rather than have this route pay for a
    # walk on every poll for everyone else's benefit.
    running: dict[str, int] = {}
    pending: dict[str, int] = {}
    unowned_running = unowned_pending = 0
    for job_id, (task, parent_job_id, state) in job_index().items():
        if state not in ("running", "pending"):
            continue
        if is_master_spec({"task": task, "parent_job_id": parent_job_id}):
            continue
        bucket = running if state == "running" else pending
        owner = job_owners.get(job_id)
        if owner is None:
            # A job submitted outside any conversation carries no owner at
            # all. It still occupies the machine, so it is counted -- just
            # not against a person.
            if state == "running":
                unowned_running += 1
            else:
                unowned_pending += 1
            continue
        bucket[owner] = bucket.get(owner, 0) + 1

    streams: dict[str, int] = {}
    orphan_streams = 0
    for thread_id, n in hub.open_threads().items():
        owner = thread_owners.get(thread_id)
        if owner is None:
            orphan_streams += n
        else:
            streams[owner] = streams.get(owner, 0) + n

    me = str(admin["id"])
    users = []
    for u in models.list_users():
        uid = str(u["id"])
        r, pnd, st = running.get(uid, 0), pending.get(uid, 0), streams.get(uid, 0)
        users.append({
            "id": uid,
            "username": u.get("username"),
            "email": u.get("email"),
            "role": u.get("role"),
            "is_active": u.get("is_active"),
            "last_login_at": u.get("last_login_at"),
            "running_jobs": r,
            "pending_jobs": pnd,
            "open_streams": st,
            # The single question the confirm dialog actually asks.
            "would_be_interrupted": bool(r or st),
            # Whoever is reading this page has the app open, which means they
            # have an event stream open, which would otherwise make every
            # deployment permanently look like it has someone working on it.
            # An admin deciding to restart has already accounted for
            # interrupting themselves; the number that should give them pause
            # is everybody else.
            "is_you": uid == me,
        })
    users.sort(key=lambda x: (-x["running_jobs"], -x["open_streams"], x["username"] or ""))

    others_interrupted = sum(1 for u in users if u["would_be_interrupted"] and not u["is_you"])
    return {
        "users": users,
        "unowned": {"running_jobs": unowned_running, "pending_jobs": unowned_pending,
                    "open_streams": orphan_streams},
        "totals": {
            "running_jobs": sum(running.values()) + unowned_running,
            "pending_jobs": sum(pending.values()) + unowned_pending,
            "open_streams": sum(streams.values()) + orphan_streams,
            "users_interrupted": sum(1 for u in users if u["would_be_interrupted"]),
            # The one to put in front of an admin. A job of your own still
            # counts here if it is running -- restarting kills it whoever
            # started it -- but merely having the page open does not.
            "others_interrupted": others_interrupted,
        },
    }
