"""Per-user and global storage quotas + oldest-first purging across the
three growth categories a user's own activity creates -- knowledge-base
uploads, job artifact directories, and chat/checkpoint history -- plus the
admin console's live usage readout and manually-triggered bulk purges.

This is a multi-user-deployment-only concept: everything here is a no-op
(or returns empty/zero) when QC_AGENT_DATABASE_URL is unset, the same
degrade-to-no-op convention app/auth/ownership.py already establishes --
a real "user" requires the ownership_index table, so a local-dev/no-auth
deployment keeps app/chemistry/jobs/quota.py's and app/rag/quota.py's own
original flat, single-tenant caps entirely unchanged.

Quota VALUES are admin-tunable at runtime via the generic app_config table
(server/routes/admin.py's GET/PATCH /api/admin/config) -- this module only
supplies the fallback defaults (app/config.py's DEFAULT_* constants) used
the first time a key is read before any admin has set one.

Deliberately does its own disk/Postgres scanning rather than sharing state
with app/chemistry/jobs/quota.py's or app/rag/quota.py's independent
global-only eviction loops -- those two keep enforcing their own original
flat caps for the local-dev path, and this module layers the per-user/
combined-global scheme on top for the auth-configured path (see
enforce_all_quotas' own docstring for exactly how the two interact).
"""
from __future__ import annotations

from typing import Optional

from app.agent import threads as thread_registry
from app.auth import models
from app.config import (
    DATABASE_URL,
    DEFAULT_GLOBAL_STORAGE_QUOTA_BYTES,
    DEFAULT_MAX_CONCURRENT_JOBS_PER_USER,
    DEFAULT_PER_USER_JOBS_AND_CHAT_QUOTA_BYTES,
    DEFAULT_PER_USER_KB_QUOTA_BYTES,
    MAX_CONCURRENT_JOBS,
    UPLOADS_DIR,
)

_TERMINAL_JOB_STATUSES = {"completed", "failed", "cancelled"}


def get_quota_config() -> dict:
    """Resolved (admin-set-or-default) quota/concurrency values. Caller's
    responsibility to only call this when DATABASE_URL is set (every
    caller in this module already is)."""
    return {
        "per_user_kb_quota_bytes": int(models.get_app_config("per_user_kb_quota_bytes", DEFAULT_PER_USER_KB_QUOTA_BYTES)),
        "per_user_jobs_and_chat_quota_bytes": int(
            models.get_app_config("per_user_jobs_and_chat_quota_bytes", DEFAULT_PER_USER_JOBS_AND_CHAT_QUOTA_BYTES)
        ),
        "global_storage_quota_bytes": int(
            models.get_app_config("global_storage_quota_bytes", DEFAULT_GLOBAL_STORAGE_QUOTA_BYTES)
        ),
        # Clamped for display, not just at write time (PATCH /api/admin/config
        # in server/routes/admin.py refuses to store a value above
        # MAX_CONCURRENT_JOBS in the first place) -- belt-and-suspenders in
        # case MAX_CONCURRENT_JOBS itself was lowered by an env-var change
        # since an admin last set this.
        "max_concurrent_jobs_total": min(
            int(models.get_app_config("max_concurrent_jobs_total", MAX_CONCURRENT_JOBS)), MAX_CONCURRENT_JOBS
        ),
        "max_concurrent_jobs_per_user": int(
            models.get_app_config("max_concurrent_jobs_per_user", DEFAULT_MAX_CONCURRENT_JOBS_PER_USER)
        ),
    }


# --- Usage accounting --------------------------------------------------


def _job_usage_by_owner() -> tuple[dict[str, int], int]:
    """(owner_user_id -> bytes, unowned_bytes) across every job directory
    on disk right now, regardless of status -- a running job's still-
    growing directory counts too, it's just never evicted (see
    _job_candidates)."""
    from app.chemistry.jobs.base import read_result
    from app.chemistry.jobs.quota import _cached_dir_size, _dir_size, _iter_job_ids
    from app.config import JOBS_DIR

    owners = models.all_owners("job")
    by_owner: dict[str, int] = {}
    unowned = 0
    for job_id in _iter_job_ids():
        try:
            result = read_result(job_id)
            status = (result or {}).get("status")
            size = _cached_dir_size(job_id) if status in _TERMINAL_JOB_STATUSES else _dir_size(JOBS_DIR / job_id)
        except OSError:
            continue
        owner = owners.get(job_id)
        if owner:
            by_owner[owner] = by_owner.get(owner, 0) + size
        else:
            unowned += size
    return by_owner, unowned


def _kb_usage_by_owner() -> tuple[dict[str, int], int]:
    """(owner_user_id -> bytes, shared_bytes). Measures only each source's
    own raw uploaded file on disk -- the persistent Chroma vector store's
    own file (KB_DIR, shared across every user's embeddings in one store)
    isn't attributable per-user, so it's left out of the per-user figures
    here entirely (a close proxy, since embedding storage scales with
    source text size) but is still included in app/rag/quota.py's
    existing flat current_usage_bytes(), which the global total below
    also folds in -- so per-user numbers slightly undercount each user's
    true share of the shared store's overhead, while the global total
    stays accurate."""
    from app.rag.store import SHARED_OWNER, list_sources

    by_owner: dict[str, int] = {}
    shared = 0
    for s in list_sources():
        path = UPLOADS_DIR / s["source"] if s["owner"] == SHARED_OWNER else UPLOADS_DIR / s["owner"] / s["source"]
        try:
            size = path.stat().st_size
        except OSError:
            size = 0
        if s["owner"] == SHARED_OWNER:
            shared += size
        else:
            by_owner[s["owner"]] = by_owner.get(s["owner"], 0) + size
    return by_owner, shared


def _chat_usage_by_owner() -> tuple[dict[str, int], int]:
    """(owner_user_id -> bytes, unowned_bytes) from every thread_id with
    checkpoint rows on disk -- see graph.py's all_thread_checkpoint_bytes
    for what "bytes" means here (a pg_column_size estimate, not literal
    disk usage)."""
    from app.agent.graph import all_thread_checkpoint_bytes

    owners = models.all_owners("thread")
    by_owner: dict[str, int] = {}
    unowned = 0
    for thread_id, size in all_thread_checkpoint_bytes().items():
        owner = owners.get(thread_id)
        if owner:
            by_owner[owner] = by_owner.get(owner, 0) + size
        else:
            unowned += size
    return by_owner, unowned


def usage_report() -> dict:
    """Live storage snapshot for the admin console: per-user kb/job/chat/
    total bytes against that user's own quotas, plus one global combined
    total against the single global cap. Rebuilds from disk/Postgres on
    every call (no caching) -- this backs a manually-refreshed/polled
    admin view, not a hot path any regular request touches."""
    cfg = get_quota_config()
    kb_by_owner, kb_shared = _kb_usage_by_owner()
    job_by_owner, job_unowned = _job_usage_by_owner()
    chat_by_owner, chat_unowned = _chat_usage_by_owner()

    per_user = []
    for u in models.list_users():
        uid = str(u["id"])
        kb = kb_by_owner.get(uid, 0)
        job = job_by_owner.get(uid, 0)
        chat = chat_by_owner.get(uid, 0)
        per_user.append({
            "user_id": uid,
            "username": u["username"],
            "email": u["email"],
            "kb_bytes": kb,
            "kb_quota_bytes": cfg["per_user_kb_quota_bytes"],
            "job_bytes": job,
            "chat_bytes": chat,
            "jobs_and_chat_bytes": job + chat,
            "jobs_and_chat_quota_bytes": cfg["per_user_jobs_and_chat_quota_bytes"],
            "total_bytes": kb + job + chat,
        })
    per_user.sort(key=lambda r: r["total_bytes"], reverse=True)

    global_kb = sum(kb_by_owner.values()) + kb_shared
    global_job = sum(job_by_owner.values()) + job_unowned
    global_chat = sum(chat_by_owner.values()) + chat_unowned
    return {
        "per_user": per_user,
        "global": {
            "kb_bytes": global_kb,
            "job_bytes": global_job,
            "chat_bytes": global_chat,
            "total_bytes": global_kb + global_job + global_chat,
            "quota_bytes": cfg["global_storage_quota_bytes"],
        },
        "quota_config": cfg,
    }


# --- Eviction candidates & execution -------------------------------------


def _job_candidates(owner_filter: Optional[str] = None) -> list[dict]:
    """Terminal jobs only -- pending/running jobs are never eviction-
    eligible no matter how large the total gets, mirroring
    app/chemistry/jobs/quota.py's own long-standing rule."""
    from app.chemistry.jobs.base import read_result, read_spec, spec_created_at
    from app.chemistry.jobs.quota import _cached_dir_size, _iter_job_ids

    owners = models.all_owners("job")
    out = []
    for job_id in _iter_job_ids():
        owner = owners.get(job_id)
        if owner_filter is not None and owner != owner_filter:
            continue
        try:
            result = read_result(job_id)
            if (result or {}).get("status") not in _TERMINAL_JOB_STATUSES:
                continue
            spec = read_spec(job_id) or {}
            size = _cached_dir_size(job_id)
        except OSError:
            continue
        out.append({"kind": "job", "key": job_id, "owner": owner, "size": size, "created_at": spec_created_at(job_id, spec)})
    return out


def _kb_candidates(owner_filter: Optional[str] = None) -> list[dict]:
    """Owned (non-shared) sources only -- the pre-seeded manuals/curated
    baseline corpus (SHARED_OWNER) is never eviction-eligible, mirroring
    app/rag/quota.py's own rule."""
    from app.rag.store import SHARED_OWNER, list_sources

    out = []
    for s in list_sources():
        if s["owner"] == SHARED_OWNER:
            continue
        if owner_filter is not None and s["owner"] != owner_filter:
            continue
        path = UPLOADS_DIR / s["owner"] / s["source"]
        try:
            size = path.stat().st_size
        except OSError:
            size = 0
        out.append({
            "kind": "kb", "key": s["source"], "owner": s["owner"], "size": size,
            "created_at": s.get("ingested_at", 0.0),
        })
    return out


def _thread_candidates(owner_filter: Optional[str] = None, include_pinned: bool = False) -> list[dict]:
    """Non-pinned threads by default -- a pinned conversation is an
    explicit "keep this" signal from its owner, so both the automatic
    quota purge and the admin console's manual purge button leave it
    alone unless include_pinned is explicitly set."""
    from app.agent.graph import all_thread_checkpoint_bytes

    owners = models.all_owners("thread")
    checkpoint_bytes = all_thread_checkpoint_bytes()
    out = []
    for t in thread_registry.list_threads():
        if t.get("pinned") and not include_pinned:
            continue
        owner = owners.get(t["thread_id"])
        if owner_filter is not None and owner != owner_filter:
            continue
        out.append({
            "kind": "thread", "key": t["thread_id"], "owner": owner,
            "size": checkpoint_bytes.get(t["thread_id"], 0), "created_at": t["created_at"],
        })
    return out


def _evict(candidate: dict) -> None:
    kind, key = candidate["kind"], candidate["key"]
    if kind == "job":
        from app.chemistry.jobs.base import delete_job_dir
        delete_job_dir(key)
        models.forget_ownership("job", key)
    elif kind == "kb":
        from app.rag.store import delete_source
        delete_source(key, owner_filter=candidate["owner"])
        try:
            (UPLOADS_DIR / candidate["owner"] / key).unlink()
        except OSError:
            pass
    elif kind == "thread":
        from app.agent.graph import delete_thread_checkpoints
        thread_registry.delete_thread(key)
        delete_thread_checkpoints(key)
        models.forget_ownership("thread", key)
    else:
        raise ValueError(f"unknown eviction candidate kind: {kind}")


_EVICTED_KEY = {"job": "evicted_jobs", "kb": "evicted_kb_sources", "thread": "evicted_threads"}


def _evict_oldest_first(candidates: list[dict], cap_bytes: int, current_total: int, sink: dict) -> int:
    """Evicts from `candidates` (mutated in place: consumed oldest-first)
    until current_total <= cap_bytes or candidates run out. Returns the
    resulting total. Appends each evicted item's key into `sink` under the
    bucket matching its kind."""
    candidates.sort(key=lambda c: c["created_at"])
    i = 0
    while current_total > cap_bytes and i < len(candidates):
        c = candidates[i]
        _evict(c)
        sink[_EVICTED_KEY[c["kind"]]].append(c["key"])
        current_total -= c["size"]
        i += 1
    return current_total


def enforce_all_quotas() -> dict:
    """Oldest-first purge across jobs/KB/chat-history, run after any
    operation that grows storage (job submit, KB ingest) and periodically
    from job_watcher's background loop (the only natural trigger point for
    chat-only growth, which has no per-message hook of its own). Silent
    no-op returning empty lists when DATABASE_URL is unset.

    Three passes, each strictly oldest-first within its own scope:
      1. Per-user KB: for every user over their own KB cap, evict their
         own oldest KB sources until under it.
      2. Per-user jobs+chat: for every user over their own COMBINED jobs+
         chat cap, evict their own oldest terminal jobs and non-pinned
         threads -- merged into one oldest-first queue by created_at,
         regardless of which of the two categories each item belongs to
         -- until under it.
      3. Global: if KB+jobs+chat combined, across every user plus shared/
         unowned content, still exceeds the global cap after both passes
         above, evict the globally oldest eligible item across all three
         categories and all owners until under it.

    Ownership is recorded asynchronously (a job/thread's owner is written
    to ownership_index only after its approval/creation request returns --
    see server/routes/chat.py's approve_job), so a just-created resource
    can briefly appear unowned to this function and escape per-user
    enforcement for one cycle; per-user enforcement is therefore
    eventually consistent, not exact to the second. It self-corrects on
    the next call, and an unowned resource still counts toward (and is
    still evictable under) the global pass regardless."""
    evicted = {"evicted_jobs": [], "evicted_kb_sources": [], "evicted_threads": []}
    if not DATABASE_URL:
        return evicted

    cfg = get_quota_config()

    for u in models.list_users():
        uid = str(u["id"])
        kb_candidates = _kb_candidates(owner_filter=uid)
        _evict_oldest_first(kb_candidates, cfg["per_user_kb_quota_bytes"], sum(c["size"] for c in kb_candidates), evicted)

    for u in models.list_users():
        uid = str(u["id"])
        combined = _job_candidates(owner_filter=uid) + _thread_candidates(owner_filter=uid)
        _evict_oldest_first(
            combined, cfg["per_user_jobs_and_chat_quota_bytes"], sum(c["size"] for c in combined), evicted
        )

    report = usage_report()
    if report["global"]["total_bytes"] > cfg["global_storage_quota_bytes"]:
        everything = _job_candidates() + _kb_candidates() + _thread_candidates()
        _evict_oldest_first(everything, cfg["global_storage_quota_bytes"], report["global"]["total_bytes"], evicted)

    return evicted


# --- Manual bulk purges (admin console "Purge all ... history" buttons) ----


def purge_all_jobs(actor_user_id: Optional[str]) -> list[str]:
    """Deletes every TERMINAL job for every user, across the whole
    deployment -- never a pending/running one, the same safety rule the
    automatic eviction above and app/chemistry/jobs/quota.py's own
    eviction already follow. Audit-logged (append-only, see db.py's
    admin_audit_log triggers)."""
    candidates = _job_candidates()
    for c in candidates:
        _evict(c)
    models.audit(actor_user_id, "purge_all_jobs", details={"count": len(candidates), "job_ids": [c["key"] for c in candidates]})
    return [c["key"] for c in candidates]


def purge_all_kb(actor_user_id: Optional[str]) -> list[str]:
    """Deletes every user-uploaded KB source for every user -- never the
    pre-seeded/shared manual corpus, matching app/rag/quota.py's own
    exclusion. Audit-logged."""
    candidates = _kb_candidates()
    for c in candidates:
        _evict(c)
    models.audit(actor_user_id, "purge_all_kb", details={"count": len(candidates), "sources": [c["key"] for c in candidates]})
    return [c["key"] for c in candidates]


def purge_all_threads(actor_user_id: Optional[str], include_pinned: bool = False) -> list[str]:
    """Deletes every conversation (and its underlying checkpoint storage)
    for every user -- pinned conversations are left alone unless
    include_pinned=True is explicitly passed (a separate, more destructive
    confirmation step in the admin console, not the default button).
    Audit-logged."""
    candidates = _thread_candidates(include_pinned=include_pinned)
    for c in candidates:
        _evict(c)
    models.audit(
        actor_user_id, "purge_all_threads",
        details={"count": len(candidates), "thread_ids": [c["key"] for c in candidates], "include_pinned": include_pinned},
    )
    return [c["key"] for c in candidates]
