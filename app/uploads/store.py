"""Uploaded geometry (.xyz) and blind engine-input (.inp/.input/.json) file
lifecycle -- add/list/get/delete/clear-all, one directory per owner.

Storage layout mirrors `server/routes/kb.py`'s own `_upload_dir` exactly:
`GEOMETRY_UPLOADS_DIR/<owner_id>/` for an owned upload, flat
`GEOMETRY_UPLOADS_DIR/<filename-stem>` for a no-auth/legacy deployment (no
owner subdirectory at all). See `app/config.py`'s `GEOMETRY_UPLOADS_DIR`
docstring for why this is a directory of its own rather than reusing KB's
`UPLOADS_DIR` -- KB's orphan-sweep and quota accounting both enumerate
everything under that tree as "a KB upload with no matching Chroma entry",
which a geometry file would collide with.

Each upload is two files: `<id><ext>` (the raw bytes as uploaded) and
`<id>.meta.json` (a small sidecar -- original_name, uploaded_at,
size_bytes, and, for a .xyz upload, its sniffed frame count/kind). A
per-upload sidecar rather than one shared index.json avoids a
read-modify-write race between two concurrent uploads/deletes for the same
owner -- the same reasoning `app/chemistry/jobs/base.py`'s per-job
meta.json already follows.
"""
from __future__ import annotations

import json
import time
import uuid
from pathlib import Path
from typing import Optional

from app.chemistry.geometry_upload import sniff_xyz_upload
from app.config import GEOMETRY_UPLOADS_DIR

ALLOWED_EXTENSIONS = {".xyz", ".inp", ".input", ".json"}


def _owner_dir(owner: Optional[str]) -> Path:
    d = GEOMETRY_UPLOADS_DIR / owner if owner else GEOMETRY_UPLOADS_DIR
    d.mkdir(parents=True, exist_ok=True)
    return d


def _meta_path(owner_dir: Path, upload_id: str) -> Path:
    return owner_dir / f"{upload_id}.meta.json"


def _raw_path(owner_dir: Path, upload_id: str, extension: str) -> Path:
    return owner_dir / f"{upload_id}{extension}"


def _owner_of(meta_file: Path) -> Optional[str]:
    parent = meta_file.parent
    return None if parent == GEOMETRY_UPLOADS_DIR else parent.name


def add_upload(owner: Optional[str], original_name: str, content: bytes) -> dict:
    """Stores one upload, sniffing it (via `geometry_upload.sniff_xyz_upload`)
    if it's a .xyz file. Raises `ValueError` -- extension not allowed, or,
    for a .xyz file, malformed geometry content -- rather than storing
    something the rest of the system couldn't later use; validated at this
    boundary so a bad upload is rejected immediately rather than accepted
    and failing later at attach time."""
    extension = Path(original_name).suffix.lower()
    if extension not in ALLOWED_EXTENSIONS:
        raise ValueError(
            f"Unsupported file type '{extension}' -- only .xyz, .inp, .input, and .json files are accepted"
        )
    sniff = None
    if extension == ".xyz":
        sniff = sniff_xyz_upload(content.decode("utf-8", errors="replace")).to_dict()

    upload_id = uuid.uuid4().hex[:12]
    owner_dir = _owner_dir(owner)
    _raw_path(owner_dir, upload_id, extension).write_bytes(content)
    record = {
        "id": upload_id,
        "original_name": original_name,
        "extension": extension,
        "size_bytes": len(content),
        "uploaded_at": time.time(),
        "sniff": sniff,
    }
    _meta_path(owner_dir, upload_id).write_text(json.dumps(record))
    return {**record, "owner": owner}


def list_uploads(owner_filter: Optional[str]) -> list[dict]:
    """`owner_filter=None`: every upload regardless of owner (admin, or a
    no-auth deployment where that's the only kind there is) -- walked
    recursively, which naturally covers both the flat no-auth layout and
    the per-owner subdirectories an auth-configured deployment uses.
    Otherwise just `owner_filter`'s own directory. Newest-first, matching
    `app/rag/store.py`'s `list_sources` convention."""
    if owner_filter is None:
        meta_files = list(GEOMETRY_UPLOADS_DIR.rglob("*.meta.json"))
    else:
        owner_dir = GEOMETRY_UPLOADS_DIR / owner_filter
        meta_files = list(owner_dir.glob("*.meta.json")) if owner_dir.is_dir() else []

    records = []
    for meta_file in meta_files:
        try:
            record = json.loads(meta_file.read_text())
        except (OSError, json.JSONDecodeError):
            continue
        records.append({**record, "owner": _owner_of(meta_file)})
    records.sort(key=lambda r: r["uploaded_at"], reverse=True)
    return records


def get_upload(owner: Optional[str], upload_id: str) -> Optional[dict]:
    owner_dir = _owner_dir(owner)
    meta_file = _meta_path(owner_dir, upload_id)
    if not meta_file.exists():
        return None
    try:
        record = json.loads(meta_file.read_text())
    except (OSError, json.JSONDecodeError):
        return None
    return {**record, "owner": owner}


def read_upload_content(owner: Optional[str], upload_id: str) -> Optional[tuple[bytes, dict]]:
    record = get_upload(owner, upload_id)
    if record is None:
        return None
    raw = _raw_path(_owner_dir(owner), upload_id, record["extension"])
    if not raw.exists():
        return None
    return raw.read_bytes(), record


def delete_upload(owner: Optional[str], upload_id: str) -> bool:
    owner_dir = _owner_dir(owner)
    record = get_upload(owner, upload_id)
    if record is None:
        return False
    _raw_path(owner_dir, upload_id, record["extension"]).unlink(missing_ok=True)
    _meta_path(owner_dir, upload_id).unlink(missing_ok=True)
    return True


def clear_uploads(owner: Optional[str]) -> list[str]:
    """Deletes every upload owned by `owner` -- never another owner's
    files; there is no "clear everyone's" caller of this function. An
    admin bulk purge goes through `app/auth/storage_quota.py`'s own
    `purge_all_uploads` instead, mirroring `purge_all_kb`."""
    ids = [r["id"] for r in list_uploads(owner)]
    for upload_id in ids:
        delete_upload(owner, upload_id)
    return ids
