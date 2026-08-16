"""10GB disk-usage cap on the knowledge base's own storage (the persistent
Chroma vector store plus the raw uploaded/pasted/scraped-via-URL source
files), enforced right after a source is ingested (see server/routes/kb.py)
rather than by a background thread -- same reasoning as
app/chemistry/jobs/quota.py: usage here only grows when a source is added,
so a second thread racing ingestion for no benefit isn't worth it.

Only ever evicts sources that were actually added through the live
uploader/paste/URL flow (a file under UPLOADS_DIR) -- the manuals
scripts/seed_knowledge_base.py pre-seeds into data/scraped/ are the
deliberately-curated baseline reference corpus this app ships with, not
part of the unbounded growth this cap exists to bound, and are never
eviction-eligible.
"""
from __future__ import annotations

from pathlib import Path

from app.config import KB_DIR, UPLOADS_DIR
from app.rag.store import SHARED_OWNER, delete_source, list_sources

QUOTA_BYTES = 10 * 1024 * 1024 * 1024  # 10GB


def _dir_size(path: Path) -> int:
    if not path.is_dir():
        return 0
    total = 0
    for f in path.rglob("*"):
        if f.is_file():
            total += f.stat().st_size
    return total


def current_usage_bytes() -> int:
    """Total bytes across KB_DIR + UPLOADS_DIR right now -- for the
    Knowledge base panel's storage-usage display (server/routes/kb.py's
    GET /api/kb/quota). Read-only, evicts nothing."""
    return _dir_size(KB_DIR) + _dir_size(UPLOADS_DIR)


def enforce_quota() -> list[str]:
    """Evicts oldest-ingested user-added sources (raw file + vector-store
    chunks) until KB_DIR + UPLOADS_DIR is back under QUOTA_BYTES. Returns
    the list of evicted source names. Like job quota.py, this subtracts
    each eviction's raw-file size from its own running `total` rather than
    re-measuring disk after every delete -- Chroma's sqlite-backed store
    doesn't necessarily shrink the instant chunks are deleted from it (no
    auto-vacuum), so the real KB_DIR footprint may lag what this loop
    assumes; a later enforce_quota() call re-measures from disk and
    self-corrects, the same best-effort trade-off the job quota already
    makes."""
    total = _dir_size(KB_DIR) + _dir_size(UPLOADS_DIR)
    if total <= QUOTA_BYTES:
        return []

    # list_sources() is most-recently-ingested first (see store.py);
    # reversed here for oldest-first eviction. Each source's raw file lives
    # at UPLOADS_DIR/<owner>/<name> for an owned upload or flat at
    # UPLOADS_DIR/<name> for a shared/no-auth one (see server/routes/kb.py's
    # _upload_dir) -- list_sources() now returns `owner` per row (SHARED_OWNER
    # for shared content) specifically so this loop can build the right path
    # without re-deriving it. Sources with no raw file at all (pre-seeded
    # manuals living in data/scraped/, which share the SHARED_OWNER tag but
    # were never written under UPLOADS_DIR) are filtered out up front rather
    # than skipped mid-loop, so they never count against the eviction order --
    # global admin-quota eviction still reaches every user's uploads
    # (list_sources() is called with no owner_filter here, so nothing is
    # scoped away before this filter runs).
    def _upload_path(s: dict) -> Path:
        return UPLOADS_DIR / s["source"] if s["owner"] == SHARED_OWNER else UPLOADS_DIR / s["owner"] / s["source"]

    evictable = [s for s in list_sources() if _upload_path(s).is_file()]
    evictable.reverse()

    evicted = []
    for s in evictable:
        if total <= QUOTA_BYTES:
            break
        path = _upload_path(s)
        try:
            size = path.stat().st_size
        except OSError:
            size = 0
        # Scoped to exactly this row's own owner (never owner_filter=None/
        # unconditional) -- two different users (or a user and the shared
        # corpus) can have identically-named sources, and an unconditional
        # delete-by-name would evict BOTH of them for one row's worth of
        # over-quota bytes. s["owner"] is always a concrete value here
        # (a real user id, or SHARED_OWNER for shared content), never None.
        delete_source(s["source"], owner_filter=s["owner"])
        try:
            path.unlink()
        except OSError:
            pass
        total -= size
        evicted.append(s["source"])
    return evicted
