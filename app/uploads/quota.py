"""Flat disk-usage cap on the geometry/blind-input uploads store --
local-dev/no-auth deployments only (see `app/auth/storage_quota.py` for the
tiered per-user/global scheme used once `QC_AGENT_DATABASE_URL` is set).
Mirrors `app/rag/quota.py`'s shape exactly; kept as its own flat cap for the
same reason `GEOMETRY_UPLOADS_DIR` itself is kept separate from KB's
`UPLOADS_DIR` (see `app/config.py`).
"""
from __future__ import annotations

from pathlib import Path

from app.config import DATABASE_URL, GEOMETRY_UPLOADS_DIR
from app.uploads.store import delete_upload, list_uploads

QUOTA_BYTES = 512 * 1024 * 1024  # 512MB -- the local-dev/no-auth flat cap only (see enforce_quota below)


def _dir_size(path: Path) -> int:
    if not path.is_dir():
        return 0
    return sum(f.stat().st_size for f in path.rglob("*") if f.is_file())


def current_usage_bytes() -> int:
    """Total bytes under GEOMETRY_UPLOADS_DIR right now -- for the Files
    panel's storage-usage display. Read-only, evicts nothing."""
    return _dir_size(GEOMETRY_UPLOADS_DIR)


def enforce_quota() -> list[str]:
    """Evicts oldest-uploaded files until back under QUOTA_BYTES. When this
    deployment has auth configured, defers entirely to
    `app/auth/storage_quota.py`'s tiered per-user/global scheme instead of
    this flat cap -- identical reasoning to `app/rag/quota.py`'s and
    `app/chemistry/jobs/quota.py`'s own `enforce_quota`."""
    if DATABASE_URL:
        from app.auth.storage_quota import enforce_all_quotas
        return enforce_all_quotas()["evicted_uploads"]

    total = current_usage_bytes()
    if total <= QUOTA_BYTES:
        return []

    records = list_uploads(owner_filter=None)  # newest-first
    records.reverse()  # oldest-first for eviction

    evicted = []
    for r in records:
        if total <= QUOTA_BYTES:
            break
        if delete_upload(r["owner"], r["id"]):
            total -= r.get("size_bytes", 0)
            evicted.append(r["id"])
    return evicted
