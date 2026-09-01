"""Copying a finished job into another user's ownership.

This is what a share actually does. A recipient gets a real second copy of
the job directory under a new id that they own, not a reference to the
sender's, and that is the whole point: the requirement the feature was
asked for is that the recipient keeps the result after the sender deletes
theirs. A reference cannot give that, because `_evict` and
`purge_user_data` in app/auth/storage_quota.py delete a job without
consulting anyone but its owner, and `add_jobs` in app/projects/registry.py
enforces one project per job so donor and recipient could not both file it.
See docs/ARCHITECTURE.md's "Sharing" section.

The payoff of copying is that the result is an ordinary job. It has its own
id, its own ownership_index row and its own quota bytes, so nothing in
app/auth/ownership.py and no list-route filter has to learn about sharing
at all.

**The invariant this module rests on: spec.json is written last, and
ownership is recorded before it.**

Every walk that enumerates jobs gates on spec.json existing -- jobs.py's
_iter_all_job_specs, base._iter_job_ids_on_disk, quota._iter_job_ids -- so
a half-built copy is invisible to listing, to quota accounting and to
deletion. That gives the copy its atomicity for free: a failure part-way
through leaves a directory with no spec.json, which is exactly the shape
reclaim_orphan_job_dirs() already sweeps after its one-hour age gate. There
is no rollback code here because none is needed.

Ownership is recorded before that final write rather than after, because a
job that is visible with no ownership row is visible to EVERY user --
check_owner_or_admin treats an unowned resource as legacy and public, and
jobs.py's list filter has an explicit `not in owners` clause saying so. The
window would be microseconds, but it is the exact shape of F-022 and
SEC-06, and closing it costs nothing.

Children of a master are deliberately NOT given ownership rows, matching
what JobManager.submit does for a natively-run scan or ensemble. This is
not an oversight: storage_quota._job_candidates does not skip child jobs,
so an owned child would become an independent eviction candidate and quota
pressure could delete one out from under its master, leaving a scan with a
hole in it. Leaving children unowned is what makes owner_filter skip them.
"""
from __future__ import annotations

import json
import shutil
import uuid
from pathlib import Path
from typing import Optional

from app.config import JOBS_DIR, PLOTS_DIR

# Files rebuilt rather than copied byte for byte. Everything else in a job
# directory is engine output and is copied verbatim.
_REBUILT = {"spec.json", "result.json", "meta.json", "children.jsonl"}

# Dropped from a copied meta.json. worker_pid/worker_pid_create_time
# identify a process on the machine that ran the ORIGINAL job; carried into
# a copy they name either nothing or, worse, an unrelated live process that
# _reconcile_orphaned_jobs or a cancel path could then act on. dir_size_bytes
# is dropped because it is a cache keyed to the source directory and the copy
# recomputes it on first read.
_META_DROP = {"worker_pid", "worker_pid_create_time", "dir_size_bytes"}


def _new_job_id() -> str:
    """Same formula as JobManager.submit -- a copy is an ordinary job and
    must be indistinguishable from one by its id."""
    return uuid.uuid4().hex[:12]


def _rewrite_artifact_path(value: str, src_id: str, dst_id: str,
                           new_owner: Optional[str], plot_map: dict) -> Optional[str]:
    """One artifact path, repointed at the copy. None means drop the key.

    Three cases, and the third is the interesting one. A path inside the
    source job's own directory is rewritten to the copy's. A path inside
    PLOTS_DIR belongs to a saved plot object owned by the sender, so the
    plot is duplicated into the recipient's plot space and the path points
    at the duplicate (see app/plots/store.py's copy_plot_to_owner for why
    reusing the sender's path would both leak and pin it). Anything else is
    a path this function does not understand, and the safe answer is to drop
    the key rather than leave a copy pointing at a file the recipient has no
    claim on.
    """
    try:
        p = Path(value)
    except (TypeError, ValueError):
        return None

    src_dir = (JOBS_DIR / src_id).resolve()
    try:
        rel = p.resolve().relative_to(src_dir)
    except (ValueError, OSError):
        rel = None
    if rel is not None:
        return str(JOBS_DIR / dst_id / rel)

    try:
        plots_rel = p.resolve().relative_to(PLOTS_DIR.resolve())
    except (ValueError, OSError):
        return None

    # PLOTS_DIR/<owner>/<plot_id>/<file> owned, PLOTS_DIR/<plot_id>/<file>
    # in a no-auth deployment. The plot id is always the file's parent.
    parts = plots_rel.parts
    if len(parts) < 2:
        return None
    plot_id = parts[-2]
    filename = parts[-1]

    if plot_id not in plot_map:
        from app.plots.store import copy_plot_to_owner
        copied = copy_plot_to_owner(plot_id, new_owner, [dst_id])
        plot_map[plot_id] = copied["plot_id"] if copied else None
    new_plot_id = plot_map[plot_id]
    if new_plot_id is None:
        return None
    owner_part = (PLOTS_DIR / new_owner) if new_owner else PLOTS_DIR
    return str(owner_part / new_plot_id / filename)


def _rewrite_artifacts(node, src_id: str, dst_id: str, new_owner: Optional[str],
                       plot_map: dict):
    """Recursive because `cubes` is a nested dict of per-orbital paths, and a
    rewrite that only walked the top level would leave every cube in a copied
    orbital job pointing at the sender's files."""
    if isinstance(node, dict):
        out = {}
        for k, v in node.items():
            rewritten = _rewrite_artifacts(v, src_id, dst_id, new_owner, plot_map)
            if rewritten is not None:
                out[k] = rewritten
        return out
    if isinstance(node, list):
        items = [_rewrite_artifacts(v, src_id, dst_id, new_owner, plot_map) for v in node]
        return [i for i in items if i is not None]
    if isinstance(node, str):
        return _rewrite_artifact_path(node, src_id, dst_id, new_owner, plot_map)
    return node


def _copy_one(src_id: str, new_owner: Optional[str], *,
              dst_id: Optional[str] = None,
              parent_job_id: Optional[str] = None,
              children: Optional[list[str]] = None,
              shared_from: Optional[str] = None,
              record_owner: bool = True) -> Optional[str]:
    """Copy a single job directory. Returns the new job id, or None if the
    source has no spec.json (nothing to copy).

    `dst_id` is passed in when the caller needs to know the id before the
    copy happens -- copy_job mints the master's id first so the children it
    writes can carry a parent pointer that is correct on their first write,
    rather than being patched afterwards.
    """
    from app.chemistry.jobs.base import read_meta, read_result, read_spec

    spec = read_spec(src_id)
    if spec is None:
        return None

    dst_id = dst_id or _new_job_id()
    src_dir = JOBS_DIR / src_id
    dst_dir = JOBS_DIR / dst_id
    dst_dir.mkdir(parents=True, exist_ok=True)

    # 1. Engine output and status.json, verbatim.
    for f in src_dir.iterdir():
        if f.name in _REBUILT:
            continue
        try:
            if f.is_dir():
                shutil.copytree(f, dst_dir / f.name, dirs_exist_ok=True)
            else:
                shutil.copy2(f, dst_dir / f.name)
        except OSError:
            continue

    # 2. result.json, with every artifact path repointed.
    plot_map: dict = {}
    result = read_result(src_id)
    if result is not None:
        result = dict(result)
        result["job_id"] = dst_id
        if result.get("artifacts"):
            result["artifacts"] = _rewrite_artifacts(
                result["artifacts"], src_id, dst_id, new_owner, plot_map
            )
        (dst_dir / "result.json").write_text(json.dumps(result))

    # 3. meta.json, without the source's process identity.
    meta = {k: v for k, v in read_meta(src_id).items() if k not in _META_DROP}
    if shared_from:
        meta["shared_from"] = shared_from
    (dst_dir / "meta.json").write_text(json.dumps(meta))

    # 4. Ownership BEFORE spec.json -- see this module's docstring.
    if record_owner and new_owner:
        try:
            from app.auth.models import record_ownership
            record_ownership("job", dst_id, new_owner)
        except Exception:
            # Leave the directory spec-less rather than publishing a job
            # nobody owns: reclaim_orphan_job_dirs sweeps it, and the accept
            # reports a failure the user can retry.
            shutil.rmtree(dst_dir, ignore_errors=True)
            raise

    # 5. children.jsonl, regenerated -- the source manifest names the
    # sender's child ids. Before spec.json, so the master is never visible
    # for an instant with a scan panel that would render empty.
    if children:
        (dst_dir / "children.jsonl").write_text("".join(c + "\n" for c in children))

    # 6. spec.json LAST. The copy becomes a job at this instant.
    new_spec = dict(spec)
    new_spec["job_id"] = dst_id
    if parent_job_id is not None:
        new_spec["parent_job_id"] = parent_job_id
    else:
        new_spec.pop("parent_job_id", None)
    (dst_dir / "spec.json").write_text(json.dumps(new_spec))
    return dst_id


def copy_job(src_id: str, new_owner: Optional[str],
             shared_from: Optional[str] = None) -> Optional[str]:
    """Copy a job, and every child if it is a master, into `new_owner`'s
    ownership. Returns the new master/job id, or None if there is nothing
    to copy.

    A master is copied as a whole family rather than on its own. Its
    children live in sibling directories with parent_job_id set, and
    sub_job_ids_of reads the master's children.jsonl to find them, so a
    master copied alone would render an empty scan or ensemble panel for the
    recipient. Children are written first so that by the time the master's
    spec.json makes it visible, everything it points at already exists.
    A child never appears in a job listing on its own -- jobs.py's
    _iter_all_job_specs skips any spec carrying parent_job_id -- so there is
    no window in which the recipient sees a loose sub-job.
    """
    from app.chemistry.jobs.base import read_spec, sub_job_ids_of

    if read_spec(src_id) is None:
        return None

    child_ids = sub_job_ids_of(src_id)
    dst_id = _new_job_id()

    new_children: list[str] = []
    for child in child_ids:
        # record_owner=False: see the module docstring on why an owned child
        # would become an independent quota-eviction candidate.
        new_child = _copy_one(child, new_owner, parent_job_id=dst_id, record_owner=False)
        if new_child:
            new_children.append(new_child)

    if _copy_one(src_id, new_owner, dst_id=dst_id, children=new_children,
                 shared_from=shared_from) is None:
        # The children are already on disk but nothing points at them, and
        # each carries a parent_job_id so no listing shows them. They are
        # spec-bearing, so reclaim_orphan_job_dirs will not sweep them --
        # remove them here rather than leave a family with no head.
        for new_child in new_children:
            shutil.rmtree(JOBS_DIR / new_child, ignore_errors=True)
        return None
    return dst_id


def job_family_size_bytes(job_id: str) -> int:
    """Total bytes a share of this job would add to the recipient, master
    plus every child. Walked fresh rather than read from meta.json's
    dir_size_bytes cache, because a stale cached figure that under-reports
    would let a share through the headroom check that should not fit."""
    from app.chemistry.jobs.base import sub_job_ids_of

    total = 0
    for jid in [job_id, *sub_job_ids_of(job_id)]:
        d = JOBS_DIR / jid
        if not d.exists():
            continue
        for p in d.rglob("*"):
            try:
                if p.is_file():
                    total += p.stat().st_size
            except OSError:
                continue
    return total
