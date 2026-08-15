"""100GB disk-usage cap across every job directory, enforced at submission
time from inside JobManager.submit() (see base.py, under its existing
lock) rather than by a separate background thread -- disk usage here only
grows when a job is submitted, and a second thread racing the watcher/
executor for no benefit would just add concurrency risk.

Only ever evicts *terminal* (completed/failed/cancelled) job directories,
oldest `created_at` first; pending/running jobs are never touched, no
matter how large the total gets.
"""
from __future__ import annotations

from app.chemistry.jobs.base import delete_job_dir, read_meta, read_result, read_spec, spec_created_at, write_meta
from app.config import JOBS_DIR

QUOTA_BYTES = 100 * 1024 * 1024 * 1024  # 100GB

_TERMINAL_STATUSES = {"completed", "failed", "cancelled"}


def _dir_size(path) -> int:
    total = 0
    for f in path.rglob("*"):
        if f.is_file():
            total += f.stat().st_size
    return total


def _cached_dir_size(job_id: str) -> int:
    """A terminal job's directory never changes size again, so its total
    is computed once and cached in meta.json -- recomputing a full rglob()
    walk for every already-finished job on every submit() call would get
    slower as the job count grows for no reason. Pre-existing jobs from
    before this cache existed get computed (and cached) lazily, on their
    first encounter here."""
    meta = read_meta(job_id)
    cached = meta.get("dir_size_bytes")
    if cached is not None:
        return cached
    size = _dir_size(JOBS_DIR / job_id)
    write_meta(job_id, {"dir_size_bytes": size})
    return size


def _iter_job_ids():
    # job_watcher.py's _SEEN_DIR ("_seen") lives inside JOBS_DIR but is its
    # own dedup bookkeeping, not a job -- must never be scanned, evicted,
    # or counted toward the quota.
    for d in JOBS_DIR.iterdir():
        if d.is_dir() and d.name != "_seen" and (d / "spec.json").exists():
            yield d.name


def _total_usage_bytes() -> int:
    """Shared by enforce_quota() (which also needs each job's size/age to
    decide what to evict) and current_usage_bytes() (the Job Manager
    panel's usage display, which only needs the total)."""
    total = 0
    for job_id in _iter_job_ids():
        try:
            result = read_result(job_id)
            status = (result or {}).get("status")
            if status in _TERMINAL_STATUSES:
                total += _cached_dir_size(job_id)
            else:
                # pending/running -- still growing, never cache.
                total += _dir_size(JOBS_DIR / job_id)
        except OSError:
            # The job's directory vanished mid-sweep (e.g. a concurrent
            # DELETE /api/jobs/{id}, which takes no lock against this).
            continue
    return total


def current_usage_bytes() -> int:
    """Total bytes across every job directory right now -- for the Job
    Manager panel's storage-usage display (server/routes/jobs.py's
    GET /api/jobs/quota). Read-only, evicts nothing."""
    return _total_usage_bytes()


def enforce_quota() -> list[str]:
    """Evicts oldest-first terminal job directories until total usage is
    back under QUOTA_BYTES. Returns the list of evicted job_ids. Caller
    (JobManager.submit()) is responsible for its own locking -- this
    function does none itself."""
    total = 0
    evictable: list[tuple[float, str, int]] = []  # (created_at, job_id, size)

    for job_id in _iter_job_ids():
        try:
            result = read_result(job_id)
            status = (result or {}).get("status")
            if status in _TERMINAL_STATUSES:
                size = _cached_dir_size(job_id)
                spec = read_spec(job_id) or {}
                evictable.append((spec_created_at(job_id, spec), job_id, size))
            else:
                # pending/running -- still growing, never cache; not
                # eligible for eviction no matter how large it gets.
                size = _dir_size(JOBS_DIR / job_id)
        except OSError:
            # The job's directory vanished mid-sweep (e.g. a concurrent
            # DELETE /api/jobs/{id}, which takes no lock against this).
            # Skip it rather than letting the exception propagate out of
            # JobManager.submit(), which holds a lock for this whole call.
            continue
        total += size

    if total <= QUOTA_BYTES:
        return []

    evictable.sort(key=lambda e: e[0])  # oldest created_at first
    evicted = []
    for _created_at, job_id, size in evictable:
        if total <= QUOTA_BYTES:
            break
        delete_job_dir(job_id)
        total -= size
        evicted.append(job_id)
    return evicted
