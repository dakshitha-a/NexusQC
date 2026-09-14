"""Per-user and global storage quotas + oldest-first purging across the
four growth categories a user's own activity creates -- knowledge-base
uploads, geometry/blind-input uploads, job artifact directories, and
chat/checkpoint history -- plus the admin console's live usage readout and
manually-triggered bulk purges.

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

import logging
import threading
import time
from typing import Optional

from app.agent import threads as thread_registry
from app.auth import models
from app.config import (
    ADMIN_STORAGE_CACHE_TTL_SECONDS,
    DATABASE_URL,
    DEFAULT_GLOBAL_STORAGE_QUOTA_BYTES,
    DEFAULT_MAX_CONCURRENT_JOBS_PER_USER,
    DEFAULT_PER_USER_JOBS_AND_CHAT_QUOTA_BYTES,
    DEFAULT_PER_USER_KB_QUOTA_BYTES,
    DEFAULT_PER_USER_UPLOADS_QUOTA_BYTES,
    MAX_CONCURRENT_JOBS,
    PLOTS_DIR,
    UPLOADS_DIR,
)


logger = logging.getLogger(__name__)


def get_quota_config() -> dict:
    """Resolved (admin-set-or-default) quota/concurrency values. Caller's
    responsibility to only call this when DATABASE_URL is set (every
    caller in this module already is)."""
    return {
        "per_user_kb_quota_bytes": int(models.get_app_config("per_user_kb_quota_bytes", DEFAULT_PER_USER_KB_QUOTA_BYTES)),
        "per_user_jobs_and_chat_quota_bytes": int(
            models.get_app_config("per_user_jobs_and_chat_quota_bytes", DEFAULT_PER_USER_JOBS_AND_CHAT_QUOTA_BYTES)
        ),
        "per_user_uploads_quota_bytes": int(
            models.get_app_config("per_user_uploads_quota_bytes", DEFAULT_PER_USER_UPLOADS_QUOTA_BYTES)
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
    from app.chemistry.jobs.base import job_is_terminal
    from app.chemistry.jobs.quota import _cached_dir_size, _dir_size, _iter_job_ids
    from app.config import JOBS_DIR

    owners = models.all_owners("job")
    by_owner: dict[str, int] = {}
    unowned = 0
    for job_id in _iter_job_ids():
        try:
            size = _cached_dir_size(job_id) if job_is_terminal(job_id) else _dir_size(JOBS_DIR / job_id)
        except OSError:
            continue
        owner = owners.get(job_id)
        if owner:
            by_owner[owner] = by_owner.get(owner, 0) + size
        else:
            unowned += size

    # Saved plots (app/plots/store.py) are counted here, in the job category,
    # rather than as a fifth category of their own. They are derived from
    # jobs, they are small, and the last-source-job rule already garbage-
    # collects them, so they need honest accounting but not an eviction pass
    # of their own -- and a fifth category would mean touching every usage
    # report, candidate list, purge path and admin section for something that
    # cleans up after itself.
    from app.plots.store import usage_bytes_by_owner as plot_usage
    plot_by_owner, plot_total = plot_usage()
    for owner, size in plot_by_owner.items():
        by_owner[owner] = by_owner.get(owner, 0) + size
    unowned += plot_total - sum(plot_by_owner.values())
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


def _upload_usage_by_owner() -> tuple[dict[str, int], int]:
    """(owner_user_id -> bytes, unowned_bytes) across the geometry/blind-
    input uploads store. `app.uploads.store.list_uploads` already reports
    each record's own `owner` (None for a no-auth/legacy upload) and
    `size_bytes`, so no separate ownership_index lookup is needed here --
    unlike `_kb_usage_by_owner`, which has to cross-reference Chroma
    metadata against `models.all_owners`."""
    from app.uploads.store import list_uploads

    by_owner: dict[str, int] = {}
    unowned = 0
    for r in list_uploads(owner_filter=None):
        size = r.get("size_bytes", 0)
        if r["owner"]:
            by_owner[r["owner"]] = by_owner.get(r["owner"], 0) + size
        else:
            unowned += size
    return by_owner, unowned


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


_usage_report_cache: Optional[dict] = None
_usage_report_cache_at: float = 0.0
_usage_report_cache_lock = threading.Lock()


def invalidate_usage_report_cache() -> None:
    """Forces the next usage_report() call to recompute from disk/Postgres
    instead of serving a cached value. Called from every mutation path
    that changes what usage_report() would report -- _evict() (so every
    purge/eviction, automatic or manual, routes through here) and the
    admin config PATCH route (server/routes/admin.py) -- so an admin who
    just clicked "purge" or changed a quota sees the effect on their very
    next read instead of waiting out the TTL below."""
    global _usage_report_cache, _usage_report_cache_at
    with _usage_report_cache_lock:
        _usage_report_cache = None
        _usage_report_cache_at = 0.0


def usage_report() -> dict:
    """Live-ish storage snapshot for the admin console: per-user kb/job/
    chat/total bytes against that user's own quotas, plus one global
    combined total against the single global cap.

    Cached for up to ADMIN_STORAGE_CACHE_TTL_SECONDS rather than rebuilt
    from disk/Postgres on every call -- confirmed to matter, not assumed:
    the underlying walk scales roughly linearly with job count (measured
    directly on a seeded test stack: ~174ms near-empty, ~343ms median at
    1,000 jobs, ~819ms median / up to ~2s at 5,000), and this route is hit
    repeatedly on every admin-console page load (alongside several other
    KB-touching requests firing at once, per the Chroma race-condition
    note elsewhere in this codebase) rather than once. A short TTL trades
    a bounded staleness window for cutting that off the hot path -- the
    same "eventually consistent, not a hard guarantee" character this
    module's own quota enforcement already has elsewhere -- but is
    explicitly invalidated (not just left to expire) on every purge and
    config change via invalidate_usage_report_cache(), so a deliberate
    admin action is never masked by a stale read."""
    global _usage_report_cache, _usage_report_cache_at
    with _usage_report_cache_lock:
        if _usage_report_cache is not None and (time.monotonic() - _usage_report_cache_at) < ADMIN_STORAGE_CACHE_TTL_SECONDS:
            return _usage_report_cache
    report = _compute_usage_report()
    with _usage_report_cache_lock:
        _usage_report_cache = report
        _usage_report_cache_at = time.monotonic()
    return report


def _compute_usage_report() -> dict:
    cfg = get_quota_config()
    kb_by_owner, kb_shared = _kb_usage_by_owner()
    upload_by_owner, upload_unowned = _upload_usage_by_owner()
    job_by_owner, job_unowned = _job_usage_by_owner()
    chat_by_owner, chat_unowned = _chat_usage_by_owner()

    per_user = []
    for u in models.list_users():
        uid = str(u["id"])
        kb = kb_by_owner.get(uid, 0)
        upload = upload_by_owner.get(uid, 0)
        job = job_by_owner.get(uid, 0)
        chat = chat_by_owner.get(uid, 0)
        per_user.append({
            "user_id": uid,
            "username": u["username"],
            "email": u["email"],
            "kb_bytes": kb,
            "kb_quota_bytes": cfg["per_user_kb_quota_bytes"],
            "upload_bytes": upload,
            "upload_quota_bytes": cfg["per_user_uploads_quota_bytes"],
            "job_bytes": job,
            "chat_bytes": chat,
            "jobs_and_chat_bytes": job + chat,
            "jobs_and_chat_quota_bytes": cfg["per_user_jobs_and_chat_quota_bytes"],
            "total_bytes": kb + upload + job + chat,
        })
    per_user.sort(key=lambda r: r["total_bytes"], reverse=True)

    global_kb = sum(kb_by_owner.values()) + kb_shared
    global_upload = sum(upload_by_owner.values()) + upload_unowned
    global_job = sum(job_by_owner.values()) + job_unowned
    global_chat = sum(chat_by_owner.values()) + chat_unowned
    return {
        "per_user": per_user,
        "global": {
            "kb_bytes": global_kb,
            "upload_bytes": global_upload,
            "job_bytes": global_job,
            "chat_bytes": global_chat,
            "total_bytes": global_kb + global_upload + global_job + global_chat,
            "quota_bytes": cfg["global_storage_quota_bytes"],
        },
        # Orphaned directories are not in any of the figures above -- they
        # are invisible to _iter_job_ids(), so they count toward nobody's
        # quota and toward no global total. Reported separately for exactly
        # that reason: this is the only place in the app they show up at
        # all, and an admin cannot act on disk they cannot see.
        "orphaned_jobs": scan_orphan_job_dirs(),
        "quota_config": cfg,
    }


def headroom_for_user(user_id: str) -> dict:
    """How many more bytes this user can take on before their own
    jobs-and-chat cap or the deployment-wide cap stops them.

    Every other quota path in this module reacts to an overrun by evicting
    something. This one exists because accepting a shared job must not:
    the bytes are arriving because somebody else offered them, and silently
    deleting the recipient's own oldest results to make room would be a
    stranger reaching into their account. So the accept path asks this
    first and refuses with a message naming both figures, which is the
    behaviour the feature was specified with.

    Deliberately computed off _compute_usage_report() rather than the
    TTL-cached usage_report(): the cache exists so the admin console's
    storage view is cheap to poll, and its staleness window is fine for a
    display but not for a decision that either writes tens of megabytes or
    tells a user no. The cost is the same disk walk the admin view does
    (~174ms near-empty, up to ~2s at 5,000 jobs, per usage_report's own
    measurements), paid once per accept click rather than per poll.
    """
    report = _compute_usage_report()
    cfg = report["quota_config"]
    mine = next((r for r in report["per_user"] if r["user_id"] == str(user_id)), None)
    used = mine["jobs_and_chat_bytes"] if mine else 0
    quota = cfg["per_user_jobs_and_chat_quota_bytes"]
    g = report["global"]
    return {
        "jobs_and_chat_bytes": used,
        "jobs_and_chat_quota_bytes": quota,
        "user_headroom_bytes": max(0, quota - used),
        "global_bytes": g["total_bytes"],
        "global_quota_bytes": g["quota_bytes"],
        "global_headroom_bytes": max(0, g["quota_bytes"] - g["total_bytes"]),
    }


def single_item_can_ever_fit(category: str, incoming_bytes: int) -> tuple[bool, str]:
    """(ok, reason) for one incoming upload or knowledge-base source.

    Not headroom: the CAP. An item larger than the whole per-user allowance
    for its category cannot be kept no matter what is deleted to make room,
    so accepting it and then evicting it is pure waste, and the caller was
    told 201 with an id that 404s on the next request (R-047). Eviction
    sorts oldest-first and the just-written item is last in that order, so
    once everything older has gone it is evicted too -- the user loses their
    own history AND the thing they were uploading.

    The narrower "it fits in the cap but only by deleting your older work"
    case is deliberately NOT decided here. That is what eviction is for, and
    refusing it would break the documented behaviour. What the routes do
    instead is check afterwards whether the thing they just wrote survived,
    and say so if it did not.

    `category` is "uploads" or "kb".
    """
    key = {"uploads": "per_user_uploads_quota_bytes", "kb": "per_user_kb_quota_bytes"}[category]
    cap = int(get_quota_config()[key])
    if cap <= 0 or incoming_bytes <= cap:
        return True, ""
    what = "upload" if category == "uploads" else "knowledge-base source"
    return False, (
        f"This {what} is {_fmt_bytes(incoming_bytes)}, which is larger than your entire "
        f"{_fmt_bytes(cap)} {what} allowance. Nothing can be deleted to make room for it. "
        f"Split it up, or ask an admin to raise the limit."
    )


def fits_for_user(user_id: str, incoming_bytes: int) -> tuple[bool, str]:
    """(ok, human-readable reason). The reason names the actual numbers,
    because "quota exceeded" gives a user nothing to act on: whether they
    need to delete two jobs or ask an admin to raise a cap depends on which
    of the two limits bit, and by how much."""
    h = headroom_for_user(user_id)
    if incoming_bytes > h["user_headroom_bytes"]:
        return False, (
            f"This share needs {_fmt_bytes(incoming_bytes)} but you have "
            f"{_fmt_bytes(h['user_headroom_bytes'])} left of your "
            f"{_fmt_bytes(h['jobs_and_chat_quota_bytes'])} job and chat allowance. "
            "Delete some jobs and try again, or ask an admin to raise your quota."
        )
    if incoming_bytes > h["global_headroom_bytes"]:
        return False, (
            f"This share needs {_fmt_bytes(incoming_bytes)} but the deployment has only "
            f"{_fmt_bytes(h['global_headroom_bytes'])} of storage left. Ask an admin."
        )
    return True, ""


def _fmt_bytes(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if abs(n) < 1024 or unit == "GB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024.0
    return f"{n:.1f} GB"


# --- Eviction candidates & execution -------------------------------------


def _job_candidates(owner_filter: Optional[str] = None) -> list[dict]:
    """Terminal jobs only -- pending/running jobs are never eviction-
    eligible no matter how large the total gets, mirroring
    app/chemistry/jobs/quota.py's own long-standing rule. A master's
    sub-jobs are not candidates either; they are counted as part of the
    master, which is the unit that actually gets deleted.

    Each candidate carries whether it has been filed into a project
    archive, which _evict_oldest_first uses to reach for it last. Archiving
    is deliberately NOT an exemption: a category nothing can reclaim lets a
    user fill their quota with un-evictable data and then be unable to
    submit anything at all, which is a worse failure than losing the oldest
    of a set of finished results. Ordering is the honest middle: a job
    somebody took the trouble to name and file goes only after every
    unfiled one is gone."""
    from app.chemistry.jobs.base import job_is_terminal, read_spec, spec_created_at
    from app.chemistry.jobs.quota import _cached_dir_size, _iter_job_ids
    from app.projects import registry as project_registry

    archived = project_registry.job_project_map()
    owners = models.all_owners("job")

    # A sub-job is never a candidate in its own right, and its bytes are
    # folded into its master's. Deleting one on its own would leave a scan,
    # batch or ensemble with a hole in it that nothing reports and nothing
    # can refill, and `delete_job_dir` already treats master-and-children as
    # one unit: deleting a master removes every child. So the eviction unit
    # is the master, and its size has to say so, or a sweep that reclaims a
    # 300 MB scan would believe it had reclaimed the 4 MB of the master's own
    # directory and keep going.
    #
    # This became load-bearing when children gained ownership rows (R-001).
    # Before that they were unowned, so a per-user sweep skipped them by
    # accident; now it would find them.
    sizes: dict[str, int] = {}
    specs: dict[str, dict] = {}
    child_bytes: dict[str, int] = {}
    for job_id in _iter_job_ids():
        try:
            if not job_is_terminal(job_id):
                continue
            specs[job_id] = read_spec(job_id) or {}
            sizes[job_id] = _cached_dir_size(job_id)
        except OSError:
            continue
    for job_id, spec in specs.items():
        parent = spec.get("parent_job_id")
        if parent:
            child_bytes[parent] = child_bytes.get(parent, 0) + sizes[job_id]

    out = []
    for job_id, spec in specs.items():
        if spec.get("parent_job_id"):
            continue
        owner = owners.get(job_id)
        if owner_filter is not None and owner != owner_filter:
            continue
        out.append({
            "kind": "job", "key": job_id, "owner": owner,
            "size": sizes[job_id] + child_bytes.get(job_id, 0),
            "created_at": spec_created_at(job_id, spec), "archived": job_id in archived,
        })
    return out


# A job directory with no spec.json is not a job as far as this app is
# concerned: app/chemistry/jobs/quota.py's _iter_job_ids() requires that
# file, so nothing lists such a directory, nothing purges it, and it does
# not even count toward anyone's quota. It is disk no part of the app can
# see. They come from a delete interrupted partway through, or a runner
# writing an artifact into a directory whose job had already been purged.
#
# The age gate is not caution for its own sake. JobManager.submit()
# creates the directory and then writes spec.json, so a job submitted
# microseconds ago has exactly this shape -- without the gate, a purge
# could race a submission and delete a live job. An hour is far longer
# than that window and far shorter than anyone's patience for stale disk.
_ORPHAN_DIR_MIN_AGE_SECONDS = 3600.0


def scan_orphan_job_dirs() -> dict:
    """What the orphan sweep would do right now, without doing it.

    Returns the sweepable directory names, their total size, and how many
    were found but held back by the age gate. The held-back count is
    reported rather than silently dropped: an admin looking at a console
    that says "3 orphaned directories" and a purge that removes 1 needs
    the difference explained, and a purge that quietly does less than the
    number next to it is exactly the failure this whole area already had
    once.
    """
    from app.config import JOBS_DIR

    cutoff = time.time() - _ORPHAN_DIR_MIN_AGE_SECONDS
    sweepable: list[str] = []
    total_bytes = 0
    held_back = 0
    for d in JOBS_DIR.iterdir():
        if not d.is_dir() or d.name == "_seen" or (d / "spec.json").exists():
            continue
        try:
            files = [f for f in d.iterdir() if f.is_file()]
            newest = max((f.stat().st_mtime for f in files), default=d.stat().st_mtime)
            size = sum(f.stat().st_size for f in files)
        except OSError:
            continue  # vanished mid-sweep
        if newest >= cutoff:
            held_back += 1
            continue
        sweepable.append(d.name)
        total_bytes += size
    return {"job_ids": sorted(sweepable), "bytes": total_bytes, "held_back": held_back}


def _sweep_orphan_job_dirs() -> list[str]:
    """Deletes every sweepable orphan directory. Shared by purge_all_jobs
    and purge_orphaned_jobs so there is one sweep, not two."""
    job_ids = scan_orphan_job_dirs()["job_ids"]
    for job_id in job_ids:
        _evict({"kind": "job", "key": job_id})
    return job_ids


def purge_orphaned_jobs(actor_user_id: Optional[str]) -> dict:
    """The admin console's "purge orphaned directories" action: removes the
    disk no part of the app can see, and nothing else.

    Deliberately separate from purge_all_jobs, which also deletes every
    terminal job for every user. An orphan sweep destroys no user's data
    -- these directories are not jobs, nobody owns them, and nothing lists
    them -- so it should not require an admin to nuke everyone's job
    history to reclaim the space. Audit-logged like every other purge."""
    scan = scan_orphan_job_dirs()
    purged = _sweep_orphan_job_dirs()
    models.audit(
        actor_user_id, "purge_orphaned_jobs",
        details={"count": len(purged), "job_ids": purged, "bytes": scan["bytes"], "held_back": scan["held_back"]},
    )
    return {"purged_job_ids": purged, "count": len(purged), "bytes": scan["bytes"], "held_back": scan["held_back"]}


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


def _upload_candidates(owner_filter: Optional[str] = None) -> list[dict]:
    """Every geometry/blind-input upload, owned or unowned (unlike
    `_kb_candidates`, there is no shared/pre-seeded corpus here to exclude
    -- every upload in this store was added through the live upload
    route)."""
    from app.uploads.store import list_uploads

    out = []
    for r in list_uploads(owner_filter=owner_filter):
        out.append({
            "kind": "upload", "key": r["id"], "owner": r["owner"], "size": r.get("size_bytes", 0),
            "created_at": r.get("uploaded_at", 0.0),
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
    # Every purge/eviction path (manual bulk purge, purge_user_data, and
    # enforce_all_quotas' own automatic eviction) routes through this one
    # function, so invalidating the usage_report() cache here -- rather
    # than separately in each of those callers -- is the single point that
    # guarantees none of them can leave a stale "still full" reading
    # behind. Cheap to call once per candidate even inside a large bulk
    # purge's loop: it's just a lock + two variable resets, not a rebuild.
    invalidate_usage_report_cache()
    kind, key = candidate["kind"], candidate["key"]
    if kind == "job":
        from app.chemistry.jobs.base import delete_job_dir
        delete_job_dir(key)
        models.forget_ownership("job", key)
    elif kind == "kb":
        # delete_upload_file also prunes the owner's directory once empty,
        # which the inlined unlink this replaced never did (F-001).
        from app.rag.store import delete_source, delete_upload_file
        delete_source(key, owner_filter=candidate["owner"])
        delete_upload_file(key, candidate["owner"])
    elif kind == "upload":
        from app.uploads.store import delete_upload
        delete_upload(candidate["owner"], key)
    elif kind == "thread":
        from app.agent.graph import delete_thread_checkpoints
        thread_registry.delete_thread(key)
        delete_thread_checkpoints(key)
        models.forget_ownership("thread", key)
    else:
        raise ValueError(f"unknown eviction candidate kind: {kind}")


_EVICTED_KEY = {
    "job": "evicted_jobs", "kb": "evicted_kb_sources", "upload": "evicted_uploads", "thread": "evicted_threads",
}


def _evict_oldest_first(candidates: list[dict], cap_bytes: int, current_total: int, sink: dict) -> int:
    """Evicts from `candidates` (mutated in place: consumed oldest-first)
    until current_total <= cap_bytes or candidates run out. Returns the
    resulting total. Appends each evicted item's key into `sink` under the
    bucket matching its kind.

    Archived jobs sort last, so eviction exhausts everything a user has not
    filed away before it touches a project archive -- see _job_candidates
    for why this is an ordering rather than an exemption. Only job
    candidates carry the key; every other kind reads as unarchived, which
    is what makes an archived job the last thing to go in the global pass
    as well as the per-user one."""
    candidates.sort(key=lambda c: (c.get("archived", False), c["created_at"]))
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

    Four passes, each strictly oldest-first within its own scope:
      1. Per-user KB: for every user over their own KB cap, evict their
         own oldest KB sources until under it.
      2. Per-user uploads: for every user over their own uploads cap,
         evict their own oldest geometry/blind-input uploads until under
         it. Its own pass (not merged into jobs+chat) since it's a
         genuinely separate category with its own independent lifecycle,
         the same reasoning KB gets its own pass rather than being folded
         into jobs+chat.
      3. Per-user jobs+chat: for every user over their own COMBINED jobs+
         chat cap, evict their own oldest terminal jobs and non-pinned
         threads -- merged into one oldest-first queue by created_at,
         regardless of which of the two categories each item belongs to
         -- until under it.
      4. Global: if KB+uploads+jobs+chat combined, across every user plus
         shared/unowned content, still exceeds the global cap after all
         three passes above, evict the globally oldest eligible item
         across all four categories and all owners until under it.

    Ownership is recorded asynchronously (a job/thread's owner is written
    to ownership_index only after its approval/creation request returns --
    see server/routes/chat.py's approve_job), so a just-created resource
    can briefly appear unowned to this function and escape per-user
    enforcement for one cycle; per-user enforcement is therefore
    eventually consistent, not exact to the second. It self-corrects on
    the next call, and an unowned resource still counts toward (and is
    still evictable under) the global pass regardless."""
    evicted = {"evicted_jobs": [], "evicted_kb_sources": [], "evicted_uploads": [], "evicted_threads": []}
    if not DATABASE_URL:
        return evicted

    cfg = get_quota_config()

    # R-044: the starting total is what the user ACTUALLY holds, not what
    # happens to be evictable.
    #
    # Each pass below used to start from `sum(c["size"] for c in candidates)`,
    # the total of its own eviction candidates. Candidates exclude everything
    # that must not be evicted: a running or pending job, a thread pinned by an
    # open conversation, a scan or ensemble child that belongs to a master. So
    # a user whose usage was mostly non-evictable measured under their cap
    # while genuinely over it, and the pass evicted nothing at all. That is
    # under-enforcement rather than over-eviction, which is the safe direction
    # to have been wrong in, but it means the number the pass acts on and the
    # number the admin console shows were two different quantities with the
    # same name.
    #
    # `usage_report()` is the same measurement the console and every /quota
    # route read, so the pass now enforces against the figure the user is
    # shown. What cannot be evicted still is not: the candidate list is
    # unchanged, so a user over their cap on running jobs alone has nothing
    # taken away, which is correct. The difference is that everything they DO
    # have evictable now goes, instead of nothing.
    usage_by_user = {r["user_id"]: r for r in usage_report()["per_user"]}

    for u in models.list_users():
        uid = str(u["id"])
        kb_candidates = _kb_candidates(owner_filter=uid)
        current = (usage_by_user.get(uid) or {}).get(
            "kb_bytes", sum(c["size"] for c in kb_candidates))
        _evict_oldest_first(kb_candidates, cfg["per_user_kb_quota_bytes"], current, evicted)

    for u in models.list_users():
        uid = str(u["id"])
        upload_candidates = _upload_candidates(owner_filter=uid)
        current = (usage_by_user.get(uid) or {}).get(
            "upload_bytes", sum(c["size"] for c in upload_candidates))
        _evict_oldest_first(
            upload_candidates, cfg["per_user_uploads_quota_bytes"], current, evicted
        )

    for u in models.list_users():
        uid = str(u["id"])
        combined = _job_candidates(owner_filter=uid) + _thread_candidates(owner_filter=uid)
        current = (usage_by_user.get(uid) or {}).get(
            "jobs_and_chat_bytes", sum(c["size"] for c in combined))
        _evict_oldest_first(
            combined, cfg["per_user_jobs_and_chat_quota_bytes"], current, evicted
        )

    # The global pass below re-reads usage_report(). That is a fresh
    # measurement rather than the snapshot above, because _evict()
    # invalidates the cache on every eviction, so the passes above have
    # already dropped it if they removed anything.
    report = usage_report()
    if report["global"]["total_bytes"] > cfg["global_storage_quota_bytes"]:
        everything = _job_candidates() + _kb_candidates() + _upload_candidates() + _thread_candidates()
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
    # Swept here and only here: this is a deliberate admin action, whereas
    # automatic eviction runs inside JobManager.submit() and must never be
    # in a position to race the submission it is part of.
    orphans = _sweep_orphan_job_dirs()
    models.audit(
        actor_user_id, "purge_all_jobs",
        details={
            "count": len(candidates), "job_ids": [c["key"] for c in candidates],
            "orphan_dir_count": len(orphans), "orphan_dirs": orphans,
        },
    )
    return [c["key"] for c in candidates] + orphans


def purge_all_kb(actor_user_id: Optional[str]) -> list[str]:
    """Deletes every user-uploaded KB source for every user -- never the
    pre-seeded/shared manual corpus, matching app/rag/quota.py's own
    exclusion. Audit-logged."""
    candidates = _kb_candidates()
    for c in candidates:
        _evict(c)
    models.audit(actor_user_id, "purge_all_kb", details={"count": len(candidates), "sources": [c["key"] for c in candidates]})
    return [c["key"] for c in candidates]


def purge_all_uploads(actor_user_id: Optional[str]) -> list[str]:
    """Deletes every geometry/blind-input upload for every user. Audit-logged."""
    candidates = _upload_candidates()
    for c in candidates:
        _evict(c)
    models.audit(
        actor_user_id, "purge_all_uploads", details={"count": len(candidates), "upload_ids": [c["key"] for c in candidates]}
    )
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


_CANCEL_AWAIT_TIMEOUT_SECONDS = 20.0
_CANCEL_AWAIT_POLL_SECONDS = 0.2


def _cancel_and_await_terminal(job_id: str) -> None:
    """Cancels one job and blocks until status.json/result.json actually
    reflect a terminal state, not just until the underlying process has
    exited. JobManager.cancel() already blocks until the subprocess is
    confirmed dead (SIGTERM, then SIGKILL after a 10s grace period -- see
    its own docstring), but the JobManager's _run()/_watch_orphan_worker
    background thread still has to notice that exit and write
    status.json/result.json afterward -- a handoff that normally
    completes in well under a second, since by the time cancel() returns
    there's nothing left for that thread to do but pop a dict entry and
    call write_status(). purge_user_data() (below) can't tolerate that
    being merely "usually fast": it needs the job's directory to already
    be evictable by the time this call returns, so it polls rather than
    trusting the timing. If the background thread genuinely hasn't caught
    up within _CANCEL_AWAIT_TIMEOUT_SECONDS (a stalled disk write, not
    normal), this finalizes the status itself -- cancel() having already
    confirmed the process dead makes "cancelled" unambiguously correct at
    that point, so a redundant write from the background thread landing
    a moment later is harmless (same values, last-write-wins).

    A pending job (never dispatched) and a pes_scan master (whose
    cancel() cancels every sub-job and writes its own status
    synchronously, see JobManager.cancel()'s docstring) both already
    finalize synchronously inside cancel() itself -- the poll loop below
    exits on its first check for those, this is only actually waiting on
    the live-process and re-attached-orphan cases."""
    from app.chemistry.jobs.base import JobResult, get_job_manager, job_is_terminal, write_result, write_status

    if not get_job_manager().cancel(job_id):
        return  # already terminal -- nothing to cancel
    deadline = time.monotonic() + _CANCEL_AWAIT_TIMEOUT_SECONDS
    while time.monotonic() < deadline:
        if job_is_terminal(job_id):
            return
        time.sleep(_CANCEL_AWAIT_POLL_SECONDS)
    if not job_is_terminal(job_id):
        write_status(job_id, "cancelled", "cancelled by admin (account deletion)")
        write_result(JobResult(job_id, "cancelled", error="Cancelled as part of account deletion."))


def purge_user_data(user_id: str) -> dict:
    """Deletes every file this ONE user owns -- jobs (cancelling any still
    pending/running first), KB uploads, and threads (including pinned
    ones, unlike purge_all_threads' default: once the owning user is gone
    there's no one left for a pin to mean "keep this" to) -- called by
    DELETE /api/admin/users/{id} BEFORE the users row itself is deleted,
    so `_evict`'s models.forget_ownership calls still have a real
    ownership_index row to remove rather than racing the FK's own
    ON DELETE CASCADE.

    Without this, deleting a user only removed their identity row; the FK
    cascade on ownership_index still fired, but nothing removed the
    underlying files -- so every job/KB source they'd ever created
    survived on disk with no recorded owner, and app/auth/ownership.py's
    check_owner_or_admin treats an unowned resource as accessible to
    EVERYONE, not to no one. Confirmed empirically: a deleted user's
    completed job stayed fully readable by a totally unrelated user
    afterward.

    A still-PENDING/RUNNING job owned by the deleted user used to be
    left untouched here entirely (matching purge_all_jobs' own
    terminal-only rule, which is the right call for THAT function -- an
    admin bulk-purging terminal history shouldn't kill someone's
    in-flight calculation). But for account deletion specifically, that
    left the exact same bug as above, just deferred: the job kept running
    in its own detached subprocess after the account row (and its
    ownership_index entry) was gone, and once it finished it became a
    globally-readable unowned orphan with no window to close it in. So
    here -- and only here, not in purge_all_jobs -- any of this user's
    still-pending/running jobs are cancelled first (_cancel_and_await_
    terminal, which blocks until each one is genuinely terminal on disk,
    not just requested-to-stop) before the normal terminal-jobs-only
    eviction pass runs and picks them up like any other terminal job."""
    from app.chemistry.jobs.base import job_is_terminal

    owners = models.all_owners("job")
    for job_id, owner in owners.items():
        if owner == user_id and not job_is_terminal(job_id):
            _cancel_and_await_terminal(job_id)

    # This user's project archives, removed BEFORE the job pass below.
    #
    # Without this, deleting an account converted its private archives into
    # deployment-wide public ones. The project rows in data/projects.json
    # survived while ownership_index's ON DELETE CASCADE took their
    # ownership rows with the user, and an unowned project is deliberately
    # visible to everyone -- the same rule that governs an unowned job.
    # That rule is right and is not what changes here; what changes is that
    # a deletion stops manufacturing orphans for it to apply to.
    #
    # The member jobs need no special handling: they are this user's jobs,
    # so the owner-filtered pass below already deletes them. Archiving is a
    # membership label and a job's files never move (see
    # app/projects/registry.py), so a filed job is an ordinary owned job in
    # every respect that matters here. A job in this user's project that
    # belongs to SOMEBODY ELSE -- reachable only when an admin filed it --
    # is correctly left alone by that same filter.
    #
    # Ordered first purely for cost: _evict -> delete_job_dir calls
    # registry.prune_job per job, which is a read-modify-write of
    # projects.json each time. Deleting the projects first makes every one
    # of those a no-op instead.
    from app.projects import registry as project_registry
    project_ids = models.list_owned("project", user_id)
    if project_ids:
        project_registry.delete_projects(project_ids)
        for project_id in project_ids:
            models.forget_ownership("project", project_id)

    job_candidates = _job_candidates(owner_filter=user_id)
    kb_candidates = _kb_candidates(owner_filter=user_id)
    upload_candidates = _upload_candidates(owner_filter=user_id)
    thread_candidates = _thread_candidates(owner_filter=user_id, include_pinned=True)
    for c in job_candidates + kb_candidates + upload_candidates + thread_candidates:
        _evict(c)

    # This user's saved plots. Deleted directly rather than left to
    # sweep_orphans: a plot drawn from someone else's jobs, or from jobs that
    # outlive this account, would never become an orphan and would otherwise
    # survive the deletion under a directory named for a user who no longer
    # exists -- the same failure mode the KB reconciliation below exists for.
    from app.plots import store as plot_store
    plot_ids = [r["plot_id"] for r in plot_store.list_plots(owner_filter=user_id)]
    for plot_id in plot_ids:
        plot_store.delete_plot(user_id, plot_id)
    try:
        (PLOTS_DIR / user_id).rmdir()  # no-op unless now empty
    except OSError:
        pass

    # F-001 reconciliation. _kb_candidates enumerates from CHROMA, so it
    # can only ever see uploads whose vector entries still exist. Any file
    # whose chunks were deleted earlier -- every KB delete before the
    # F-001 fix landed, since the route removed chunks and left the file
    # -- is invisible to the loop above and would survive the account
    # deletion entirely, stranded under a directory named for a user who
    # no longer exists. This is a filesystem-side sweep precisely because
    # it has to see what Chroma cannot.
    orphans = []
    try:
        from app.rag.store import orphaned_upload_files
        for path in orphaned_upload_files(user_id):
            try:
                path.unlink()
                orphans.append(path.name)
            except OSError:
                pass
        try:
            (UPLOADS_DIR / user_id).rmdir()  # no-op unless now empty
        except OSError:
            pass
    except Exception:
        # A KB store that is unreachable must not block account deletion;
        # the account row and every other resource still go. But it is LOGGED
        # now rather than silently passed: this handler wraps the whole
        # reconciliation sweep, so it was also swallowing any bug inside it,
        # and a file left behind under a deleted user's directory with no
        # trace anywhere of why is exactly the shape of problem that costs an
        # afternoon later. e2e_10's K7 reported such a leftover at the
        # 2026-09 gate and could not be reproduced in isolation across three
        # sequences; if it happens again this line is what will say why.
        logger.warning(
            "the KB reconciliation sweep failed for user %s during account deletion; "
            "their upload directory may keep files whose chunks were already gone",
            user_id, exc_info=True,
        )

    return {
        "job_ids": [c["key"] for c in job_candidates],
        "kb_sources": [c["key"] for c in kb_candidates],
        "orphaned_kb_files": orphans,
        "upload_ids": [c["key"] for c in upload_candidates],
        "thread_ids": [c["key"] for c in thread_candidates],
        "plot_ids": plot_ids,
        "project_ids": project_ids,
    }


def purge_own_data(user_id: str) -> dict:
    """P9.4's self-scoped "danger zone" purge: a signed-in user deleting
    their OWN jobs, KB uploads and geometry/blind-input uploads -- called
    by POST /api/auth/purge-my-data, no admin role required, since it can
    only ever act on the caller's own resources (owner_filter=user_id on
    every candidate builder below).

    Also their own plots and project archives, as of R-087; see the comment
    at that pass for why those belong here and threads still do not.

    Deliberately narrower than purge_user_data (used for admin-driven
    account DELETION): chat threads are left untouched here. Losing every
    conversation as a side effect of "clear out my old jobs" would be a
    surprising, unrelated loss for someone whose account still exists
    afterward -- purge_user_data's inclusion of threads (even pinned ones)
    is correct there specifically because the account itself is going
    away and nothing will be left to own them regardless.

    Still always kills a pending/running job's real process first
    (_cancel_and_await_terminal, the same helper purge_user_data uses) --
    "delete my data" cannot leave an orphaned subprocess still writing
    into a job directory this call is about to remove out from under it."""
    from app.chemistry.jobs.base import job_is_terminal

    owners = models.all_owners("job")
    for job_id, owner in owners.items():
        if owner == user_id and not job_is_terminal(job_id):
            _cancel_and_await_terminal(job_id)

    # R-087: this user's plots and project archives go too.
    #
    # They did not, and the response counts did not mention them either, so
    # "Delete all my data" left a Plots panel full of charts and a Projects
    # list full of archives, and reported a job/KB/upload tally that read as
    # complete. For plots that was largely self-correcting, since every source
    # job had just gone and sweep_orphans would eventually catch up, but "the
    # cleanup pass will probably get to it" is not what a danger-zone button
    # should mean. For projects it was not self-correcting at all: a project
    # row survives with its member jobs gone, so the user was left with a list
    # of empty archives.
    #
    # Threads are still deliberately left alone here, which is the difference
    # from purge_user_data below. Losing every conversation as a side effect of
    # clearing out old jobs would be a surprising, unrelated loss for someone
    # whose account still exists afterwards. A plot and a project archive are
    # both views onto the jobs being deleted, so they go with them; a
    # conversation is not.
    #
    # Projects first, for the same cost reason purge_user_data gives: _evict
    # calls registry.prune_job per job, a read-modify-write of projects.json
    # each time, and deleting the projects first makes every one a no-op.
    from app.projects import registry as project_registry
    project_ids = models.list_owned("project", user_id)
    if project_ids:
        project_registry.delete_projects(project_ids)
        for project_id in project_ids:
            models.forget_ownership("project", project_id)

    job_candidates = _job_candidates(owner_filter=user_id)
    kb_candidates = _kb_candidates(owner_filter=user_id)
    upload_candidates = _upload_candidates(owner_filter=user_id)
    for c in job_candidates + kb_candidates + upload_candidates:
        _evict(c)

    from app.plots import store as plot_store
    plot_ids = [r["plot_id"] for r in plot_store.list_plots(owner_filter=user_id)]
    for plot_id in plot_ids:
        plot_store.delete_plot(user_id, plot_id)
    try:
        (PLOTS_DIR / user_id).rmdir()  # no-op unless now empty
    except OSError:
        pass

    # Same F-001 reconciliation purge_user_data does -- see its own
    # docstring for why a filesystem-side sweep is needed alongside the
    # Chroma-driven _kb_candidates loop above.
    orphans = []
    try:
        from app.rag.store import orphaned_upload_files
        for path in orphaned_upload_files(user_id):
            try:
                path.unlink()
                orphans.append(path.name)
            except OSError:
                pass
        try:
            (UPLOADS_DIR / user_id).rmdir()  # no-op unless now empty
        except OSError:
            pass
    except Exception:
        pass

    return {
        "job_ids": [c["key"] for c in job_candidates],
        "kb_sources": [c["key"] for c in kb_candidates],
        "orphaned_kb_files": orphans,
        "upload_ids": [c["key"] for c in upload_candidates],
        # R-087: reported, not just done. A count that omits a category the
        # call deleted is how the omission stayed invisible in the first
        # place.
        "plot_ids": plot_ids,
        "project_ids": [str(pid) for pid in project_ids],
    }
