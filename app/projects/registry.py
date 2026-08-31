"""Project archives: named bundles of jobs.

A project groups a set of finished jobs under a name the user chose, so a
study that took thirty calculations stops sitting on top of the next study's
in the job manager. Backed by a flat JSON file (data/projects.json) for the
same reason app/agent/threads.py is: this is list-shaped state that the left
rail polls, and it must need no coordination with graph.py's _graph_lock at
all. Every function here is a plain disk read or an atomic rewrite.

Two invariants the rest of the app depends on.

**Archiving is a membership label. Job files never move.** Everything else
is keyed on data/jobs/<job_id>/ staying where it is: app/auth/storage_quota
walks those directories for quota accounting, app/agent/threads.py's
set_active_job_ids filters on (JOBS_DIR / j / "spec.json").exists(), and the
detail drawer, orbital-cube, artifact and download routes all read
JOBS_DIR / job_id directly. Moving an archived job's files would silently
evict it from its own conversation's panel and make its bytes vanish from
its owner's quota. So this module stores ids and nothing else.

**A job belongs to at most one project.** add_jobs is what enforces that,
and it does the removal and the addition in ONE read-modify-write cycle
under ONE lock acquisition. The obvious spelling -- remove_jobs(other, ids)
then add_jobs(this, ids) -- is two acquisitions and two file writes, and a
crash between them loses the job from both projects. Every affected project
is an entry in the same file, so one write covers all of them.
"""
from __future__ import annotations

import json
import os
import threading
import time
import uuid
from typing import Optional

from app.config import JOBS_DIR, PROJECTS_FILE

_lock = threading.Lock()

# Normalized onto every entry read back, once, so no other function and no
# API response needs its own .get(key, default) fallback -- the same
# convention app/agent/threads.py uses for its "pinned" key.
_DEFAULTS = {"description": "", "job_ids": []}


def _atomic_write_text(text: str) -> None:
    """Write via a temp file + rename so a concurrent reader never observes
    a truncated/partial file -- same pattern as app/agent/threads.py and
    app/chemistry/jobs/base.py's _atomic_write_text."""
    tmp = PROJECTS_FILE.with_suffix(PROJECTS_FILE.suffix + f".tmp{os.getpid()}")
    tmp.write_text(text)
    os.replace(tmp, PROJECTS_FILE)


def _job_exists(job_id: str) -> bool:
    return (JOBS_DIR / job_id / "spec.json").exists()


def _read_all() -> list[dict]:
    """Every read filters out ids whose job directory is gone, for exactly
    the reason app/agent/threads.py's set_active_job_ids does: a job can
    leave through DELETE /api/jobs/{id} or through quota eviction, and a
    project holding a dead id would report a job count and an archive size
    that no download could ever produce. delete_job_dir calls prune_job()
    so the file is normally already clean; this is the safety net for any
    path that removes a directory without going through it."""
    if not PROJECTS_FILE.exists():
        return []
    try:
        projects = json.loads(PROJECTS_FILE.read_text())
    except json.JSONDecodeError:
        return []
    for p in projects:
        for key, default in _DEFAULTS.items():
            p.setdefault(key, default if not isinstance(default, list) else list(default))
        p["job_ids"] = [j for j in p["job_ids"] if _job_exists(j)]
    return projects


def _write_all(projects: list[dict]) -> None:
    _atomic_write_text(json.dumps(projects, indent=2))


def _touch(project: dict) -> None:
    project["updated_at"] = time.time()


def list_projects() -> list[dict]:
    """Most recently changed first. Callers wanting sizes should use
    project_sizes() rather than walking the directories themselves."""
    with _lock:
        projects = _read_all()
    return sorted(projects, key=lambda p: -p["updated_at"])


def get_project(project_id: str) -> Optional[dict]:
    with _lock:
        for p in _read_all():
            if p["project_id"] == project_id:
                return p
    return None


def create_project(name: str, description: str = "") -> dict:
    now = time.time()
    entry = {
        "project_id": uuid.uuid4().hex[:12],
        "name": name.strip() or "Untitled project",
        "description": description,
        "created_at": now,
        "updated_at": now,
        "job_ids": [],
    }
    with _lock:
        projects = _read_all()
        projects.append(entry)
        _write_all(projects)
    return entry


def update_project(project_id: str, name: Optional[str] = None,
                   description: Optional[str] = None) -> Optional[dict]:
    """Returns the updated entry, or None if no such project. Both fields
    are optional so a rename does not have to restate the description."""
    with _lock:
        projects = _read_all()
        for p in projects:
            if p["project_id"] != project_id:
                continue
            if name is not None and name.strip():
                p["name"] = name.strip()
            if description is not None:
                p["description"] = description
            _touch(p)
            _write_all(projects)
            return p
    return None


def add_jobs(project_id: str, job_ids: list[str]) -> Optional[dict]:
    """Files these jobs into the project, removing each from whichever
    project currently holds it. Single membership is enforced here, and it
    has to be one read-modify-write cycle: see this module's docstring for
    why the two-call spelling can lose a job from both projects.

    Ids naming a job directory that no longer exists are dropped rather
    than stored, so _read_all's filter never has to see them."""
    wanted = [j for j in dict.fromkeys(job_ids) if _job_exists(j)]
    with _lock:
        projects = _read_all()
        target = next((p for p in projects if p["project_id"] == project_id), None)
        if target is None:
            return None
        moving = set(wanted)
        for p in projects:
            if p["project_id"] == project_id:
                continue
            kept = [j for j in p["job_ids"] if j not in moving]
            if len(kept) != len(p["job_ids"]):
                p["job_ids"] = kept
                _touch(p)
        existing = set(target["job_ids"])
        target["job_ids"].extend(j for j in wanted if j not in existing)
        _touch(target)
        _write_all(projects)
        return target


def remove_jobs(project_id: str, job_ids: list[str]) -> Optional[dict]:
    """Returns these jobs to the job manager. Nothing on disk is touched:
    the job directories were never moved in the first place."""
    dropping = set(job_ids)
    with _lock:
        projects = _read_all()
        for p in projects:
            if p["project_id"] != project_id:
                continue
            p["job_ids"] = [j for j in p["job_ids"] if j not in dropping]
            _touch(p)
            _write_all(projects)
            return p
    return None


def delete_project(project_id: str) -> Optional[dict]:
    """Removes the project itself and returns it (so a caller that wants to
    cascade still knows which jobs it held). Deleting the jobs is the
    caller's decision and the caller's work -- see
    server/routes/projects.py, where the choice is always the user's."""
    with _lock:
        projects = _read_all()
        gone = next((p for p in projects if p["project_id"] == project_id), None)
        if gone is None:
            return None
        _write_all([p for p in projects if p["project_id"] != project_id])
        return gone


def delete_projects(project_ids: list[str]) -> list[dict]:
    """Bulk form of delete_project, one write rather than N. Used by the
    per-user "delete all my projects" danger-zone action."""
    dropping = set(project_ids)
    with _lock:
        projects = _read_all()
        gone = [p for p in projects if p["project_id"] in dropping]
        if gone:
            _write_all([p for p in projects if p["project_id"] not in dropping])
        return gone


def job_project_map() -> dict[str, dict]:
    """job_id -> {"project_id", "project_name"}, built in one pass. This is
    what GET /api/jobs uses to decide which rows are archived; it is a
    single small-file read taking no lock of any kind, which is what keeps
    server/routes/jobs.py's lock-free contract intact."""
    out: dict[str, dict] = {}
    for p in list_projects():
        for job_id in p["job_ids"]:
            out[job_id] = {"project_id": p["project_id"], "project_name": p["name"]}
    return out


def prune_job(job_id: str) -> None:
    """Drops a deleted job from whichever project held it. Called from
    app/chemistry/jobs/base.py's delete_job_dir alongside the existing
    conversation-registry prune, so the two registries that name job ids
    stay consistent by the same mechanism. A no-op when no project holds
    it, which is the common case."""
    with _lock:
        projects = _read_all()
        touched = False
        for p in projects:
            if job_id in p["job_ids"]:
                p["job_ids"] = [j for j in p["job_ids"] if j != job_id]
                _touch(p)
                touched = True
        if touched:
            _write_all(projects)


def project_sizes(projects: list[dict]) -> dict[str, int]:
    """project_id -> total bytes on disk. Reads each job's cached
    dir_size_bytes rather than walking the directory: an archived job is by
    definition terminal, so its size never changes again, and
    quota.py's _cached_dir_size already computes-and-caches it once into
    meta.json. The left rail polls this list, so a bare rglob() walk per
    job per tick would be a latency regression in a panel that is on screen
    permanently."""
    from app.chemistry.jobs.quota import _cached_dir_size

    sizes: dict[str, int] = {}
    for p in projects:
        total = 0
        for job_id in p["job_ids"]:
            try:
                total += _cached_dir_size(job_id)
            except OSError:
                pass
        sizes[p["project_id"]] = total
    return sizes
