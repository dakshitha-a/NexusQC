"""Thin helpers wiring the ownership_index table (app/auth/db.py's schema)
into route handlers, used by server/routes/{threads,jobs}.py. Deliberately
NOT a change to JobSpec/threads.json's own schema -- ownership is tracked
entirely in Postgres, recorded at creation time and consulted at read/write
time, so the file-based job/thread storage this app already has (and the
delicate submit_draft interrupt()/resume_turn round-trip documented in
docs/ARCHITECTURE.md's "The approval gate", which reconstructs a JobSpec
from exactly the dict shown on the approval card) stays completely
unchanged.

Every function here degrades to "no filtering, no restriction" when
QC_AGENT_DATABASE_URL is unset -- the local-dev, auth-not-configured case --
so these can be called unconditionally from route handlers without an
`if DATABASE_URL:` guard at every call site.
"""
from __future__ import annotations

from typing import Optional

from fastapi import HTTPException, Request

from app.auth import models
from app.auth.deps import get_current_user
from app.config import DATABASE_URL


def current_user_or_none(request: Request) -> Optional[dict]:
    """None if auth isn't configured for this deployment at all (local
    dev). Otherwise defers to get_current_user, which raises 401 if the
    caller has no valid session -- callers use this rather than a bare
    try/except specifically so "auth configured but not logged in" still
    401s instead of silently falling through to unscoped, single-user-era
    behavior."""
    if not DATABASE_URL:
        return None
    return get_current_user(request)


def record(kind: str, resource_id: str, user: Optional[dict]) -> None:
    """No-ops if user is None (auth not configured). Call right after
    creating a thread/job so it has a recorded owner from the start."""
    if user is not None:
        models.record_ownership(kind, resource_id, str(user["id"]))


def effective_owner(kind: str, resource_id: str) -> Optional[str]:
    """Who a resource belongs to, following a job's parent chain when the
    job itself has no row of its own.

    The chain is the whole point, and R-001 is why. A batch, scan,
    ensemble or geometry-set master is submitted with an owner and its
    children are submitted with `owner_user_id=None`, deliberately: only
    the master was ever meant to be individually reachable. But
    `GET /api/jobs/{id}` reaches any job id, so a child was individually
    reachable and had no owner, and `check_owner_or_admin` treats an
    absent owner as legacy-unowned and lets it through. On the live
    deployment that meant a user who owned nothing was refused a master
    with 404 and handed its child with 200, one request apart, including
    the full artifact download.

    The scheduler already knew the answer. `JobManager.submit` enqueues
    with `owner_user_id or _queue_owner(...)`, and `_queue_owner` walks
    `parent_job_id` for exactly this reason, so the fair queue has always
    bucketed a child under the user who submitted its master. The access
    check simply never asked the same question. It asks now, through the
    same walk.

    Ownership rows for children are recorded at submit as well (see
    `JobManager.submit`), so on a deployment created after that change
    this walk is a fallback rather than the main path. It stays because
    it is what makes existing children safe the moment the code lands,
    without waiting for a backfill, and because a row that fails to write
    should degrade to "as private as the parent" rather than to "public".

    Returns None only when nothing in the chain has an owner, which is
    the genuine legacy/unowned case the module docstring describes and
    which stays visible to everyone by design.
    """
    owner = models.get_owner(kind, resource_id)
    if owner is not None or kind != "job":
        return owner
    # Deferred: app.chemistry.jobs.base imports app.auth.models at call
    # time, so importing it at this module's scope would cycle.
    from app.chemistry.jobs.base import read_spec
    seen = {resource_id}
    current = resource_id
    # Bounded rather than while-True. A malformed spec.json that points at
    # its own ancestor must not spin a request thread, and no legitimate
    # nesting in this app is deeper than master -> child.
    for _ in range(_MAX_PARENT_HOPS):
        spec = read_spec(current)
        parent = (spec or {}).get("parent_job_id")
        if not parent or parent in seen:
            return None
        owner = models.get_owner("job", parent)
        if owner is not None:
            return owner
        seen.add(parent)
        current = parent
    return None


# master -> child is one hop; the allowance is for a nested orchestrator
# that does not exist today rather than for anything currently shipped.
_MAX_PARENT_HOPS = 4


def check_owner_or_admin(kind: str, resource_id: str, user: Optional[dict]) -> None:
    """No-ops if user is None (auth not configured -- today's single-user
    behavior, unrestricted) or the caller is an admin. Raises 404 (not
    403) if the resource has an effective owner that isn't this user --
    404 rather than 403 so a probing request can't distinguish "exists but
    belongs to someone else" from "doesn't exist" for another user's
    private resource. A resource with NO owner anywhere in its parent
    chain (created before auth was configured on this deployment) is left
    accessible, treated as legacy/unowned rather than inaccessible to
    everyone.

    "Effective" rather than "recorded" is R-001's fix; see
    `effective_owner` for what a child job's chain looks like and why the
    distinction let one user download another's results."""
    if user is None or user["role"] == "admin":
        return
    owner = effective_owner(kind, resource_id)
    if owner is not None and owner != str(user["id"]):
        raise HTTPException(status_code=404, detail=f"No such {kind}: {resource_id}")


def owned_ids_filter(kind: str, user: Optional[dict]) -> Optional[set[str]]:
    """Returns the caller's own resource ids as a set (for list-route
    filtering), or None meaning "don't filter, return everything" -- when
    auth isn't configured, or the caller is an admin (admins see every
    user's resources in the global/cross-user views, e.g. GET /api/admin/
    jobs; ordinary per-user list routes should still call this and treat
    an admin's None as "show me my own view unfiltered too", which for an
    admin's OWN thread/job list is the same resources plus everyone
    else's -- acceptable since admins are trusted operators, and the
    dedicated admin-only cross-user routes are the deliberate place to
    browse other users' resources, not a side effect of this filter)."""
    if user is None or user["role"] == "admin":
        return None
    return set(models.list_owned(kind, str(user["id"])))
