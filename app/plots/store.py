"""Saved plot records: the lifecycle of a plot as an object rather than a
one-shot image.

A plot here is a SPEC plus the numbers it drew, not just a PNG. That is what
makes the rest of the feature possible: an edit is a patch to the spec and a
re-render, a question about a plot is answered from the cached numbers, and the
Plots panel has something with a name and a history to list.

Layout mirrors `app/uploads/store.py` closely, including the per-item sidecar
rather than one shared index (a shared index would put two concurrent writers
for the same owner into a read-modify-write race, the same reasoning
`app/chemistry/jobs/base.py`'s per-job meta.json already follows):

    PLOTS_DIR/<owner_id>/<plot_id>/record.json     owned deployment
    PLOTS_DIR/<plot_id>/record.json                no-auth deployment
    ...                /v1.png, v2.png, ...

**Why not inside the job directory.** It is the obvious cheaper design, and it
is wrong. A plot can aggregate several jobs, and a seven-method comparison has
no owning job at all. Parenting it to an arbitrary "primary" job would destroy
the chart the moment that one job was deleted, with every other source still
sitting on disk. So reclamation follows one rule instead:

    a plot is deleted when its LAST source job is gone

which reads correctly at both ends without a special case. A single-job UV/Vis
spectrum disappears with its job, which is what anyone would expect, and a
seven-method comparison survives until the seventh job goes. `sweep_orphans`
is what enforces it.

**Versions.** An edit pins a new version rather than overwriting the current
one, so a chat message keeps showing the image it actually described while the
panel shows the latest. This also fixes a real bug in the old artifact-key
scheme: `uvvis_spectrum` and friends used a FIXED key, so re-plotting rebound
the key and an older message retroactively displayed the newer image.
"""
from __future__ import annotations

import json
import shutil
import time
import uuid
from pathlib import Path
from typing import Callable, Optional

from app.config import JOBS_DIR, PLOTS_DIR

# How many rendered versions of one plot are kept. Older ones are pruned
# oldest-first. Five is enough that ordinary back-and-forth editing never
# loses an image a recent message still points at, without letting a long
# tuning session accumulate a hundred PNGs against the owner's quota.
MAX_VERSIONS = 5


def _owner_dir(owner: Optional[str]) -> Path:
    d = PLOTS_DIR / owner if owner else PLOTS_DIR
    d.mkdir(parents=True, exist_ok=True)
    return d


def _plot_dir(owner: Optional[str], plot_id: str) -> Path:
    return _owner_dir(owner) / plot_id


def _owner_of(record_file: Path) -> Optional[str]:
    parent = record_file.parent.parent
    return None if parent == PLOTS_DIR else parent.name


def _read(record_file: Path) -> Optional[dict]:
    try:
        return json.loads(record_file.read_text())
    except (OSError, json.JSONDecodeError):
        return None


def _find_record_file(owner_filter: Optional[str], plot_id: str) -> Optional[Path]:
    """Locate a plot by id. `owner_filter=None` means admin or a no-auth
    deployment and searches every owner; otherwise only that owner's own
    directory is consulted, so a caller cannot reach another owner's plot by
    guessing an id even before the route's own ownership check runs."""
    if owner_filter is None:
        matches = list(PLOTS_DIR.glob(f"*/{plot_id}/record.json"))
        matches += [p for p in [PLOTS_DIR / plot_id / "record.json"] if p.exists()]
        return matches[0] if matches else None
    candidate = PLOTS_DIR / owner_filter / plot_id / "record.json"
    return candidate if candidate.exists() else None


def create_plot(
    owner: Optional[str], kind: str, label: str, spec: dict, job_ids: list[str],
    data: Optional[dict] = None, origin: str = "agent",
) -> dict:
    """Register a new plot. No image yet: `add_version` renders that."""
    plot_id = "p" + uuid.uuid4().hex[:11]
    now = time.time()
    record = {
        "plot_id": plot_id,
        "kind": kind,
        "label": label,
        "spec": spec,
        "job_ids": list(job_ids),
        "origin": origin,
        "created_at": now,
        "updated_at": now,
        "versions": [],
        # Monotonic, and deliberately NOT derived from len(versions):
        # pruning truncates that list, so deriving from it starts handing out
        # version numbers that already exist, which silently overwrites a
        # version an older chat message still points at.
        "version_counter": 0,
        "data": data or {},
    }
    plot_dir = _plot_dir(owner, plot_id)
    plot_dir.mkdir(parents=True, exist_ok=True)
    (plot_dir / "record.json").write_text(json.dumps(record))

    # Ownership is recorded here rather than in the route, because unlike an
    # upload a plot is created by the agent mid-turn and no request handler is
    # on the stack to do it. Imported lazily and skipped entirely without an
    # owner, exactly as JobManager.submit does, so a no-auth deployment never
    # even attempts the app.auth import.
    if owner:
        try:
            from app.auth.models import record_ownership
            record_ownership("plot", plot_id, owner)
        except Exception:
            # Losing the ownership row must not lose the plot. Access is
            # gated primarily by the owner DIRECTORY -- list_plots and
            # get_plot are both scoped to it, so another user can neither see
            # nor fetch this plot regardless -- and check_owner_or_admin is
            # defense in depth on top of that. Failing the whole render
            # because the index write hiccuped would trade a real result for
            # a redundant one.
            pass
    return {**record, "owner": owner}


def add_version(owner: Optional[str], plot_id: str, render: Callable[[str], None]) -> Optional[dict]:
    """Render the next version of a plot. `render` is handed the destination
    path and writes the PNG there.

    Deliberately renders BEFORE the record is rewritten, so a renderer that
    raises leaves the record exactly as it was rather than advertising a
    version whose file never landed."""
    record_file = _find_record_file(owner, plot_id)
    if record_file is None:
        return None
    record = _read(record_file)
    if record is None:
        return None

    counter = record.get("version_counter", len(record["versions"])) + 1
    version = f"v{counter}"
    render(str(record_file.parent / f"{version}.png"))

    record["version_counter"] = counter
    record["versions"].append(version)
    record["updated_at"] = time.time()
    for stale in record["versions"][:-MAX_VERSIONS]:
        (record_file.parent / f"{stale}.png").unlink(missing_ok=True)
    record["versions"] = record["versions"][-MAX_VERSIONS:]
    record_file.write_text(json.dumps(record))
    return {**record, "owner": _owner_of(record_file)}


def update_plot(owner: Optional[str], plot_id: str, **fields) -> Optional[dict]:
    """Patch a record's own fields (spec, label, job_ids, data). Does not
    render; `add_version` does that, and an edit calls both."""
    record_file = _find_record_file(owner, plot_id)
    if record_file is None:
        return None
    record = _read(record_file)
    if record is None:
        return None
    record.update(fields)
    record["updated_at"] = time.time()
    record_file.write_text(json.dumps(record))
    return {**record, "owner": _owner_of(record_file)}


def get_plot(owner_filter: Optional[str], plot_id: str) -> Optional[dict]:
    record_file = _find_record_file(owner_filter, plot_id)
    if record_file is None:
        return None
    record = _read(record_file)
    return None if record is None else {**record, "owner": _owner_of(record_file)}


def list_plots(owner_filter: Optional[str]) -> list[dict]:
    """Newest-first, matching `list_uploads`' convention. `owner_filter=None`
    walks every owner (admin, or a no-auth deployment where that is the only
    kind there is), which the recursive glob covers for both layouts."""
    if owner_filter is None:
        record_files = list(PLOTS_DIR.glob("*/record.json")) + list(PLOTS_DIR.glob("*/*/record.json"))
    else:
        owner_dir = PLOTS_DIR / owner_filter
        record_files = list(owner_dir.glob("*/record.json")) if owner_dir.is_dir() else []
    records = []
    for record_file in record_files:
        record = _read(record_file)
        if record is not None:
            records.append({**record, "owner": _owner_of(record_file)})
    records.sort(key=lambda r: r.get("updated_at", 0), reverse=True)
    return records


def find_by_job_and_kind(owner_filter: Optional[str], job_id: str, kind: str) -> Optional[dict]:
    """The existing record for one job's own intrinsic plot of this kind, if
    there is one.

    Spectra are a property of a job rather than something a user composes, so
    a job has at most ONE UV/Vis spectrum and one IR spectrum, and re-plotting
    at a different broadening should add a version to it rather than leave a
    trail of near-identical records in the panel. Composed plots (kind
    "custom") are the opposite and are never matched here: two different
    charts over the same jobs are two different plots."""
    for record in list_plots(owner_filter):
        if record.get("kind") == kind and record.get("job_ids") == [job_id]:
            return record
    return None


def version_path(owner_filter: Optional[str], plot_id: str, version: str) -> Optional[Path]:
    record_file = _find_record_file(owner_filter, plot_id)
    if record_file is None:
        return None
    record = _read(record_file)
    if record is None or version not in record.get("versions", []):
        return None
    path = record_file.parent / f"{version}.png"
    return path if path.exists() else None


def latest_version(record: dict) -> Optional[str]:
    versions = record.get("versions") or []
    return versions[-1] if versions else None


def delete_plot(owner_filter: Optional[str], plot_id: str) -> bool:
    record_file = _find_record_file(owner_filter, plot_id)
    if record_file is None:
        return False
    owner = _owner_of(record_file)
    shutil.rmtree(record_file.parent, ignore_errors=True)
    if owner:
        try:
            from app.auth.models import forget_ownership
            forget_ownership("plot", plot_id)
        except Exception:
            pass  # the files are gone, which is what delete means here
    return True


def usage_bytes_by_owner() -> tuple[dict[str, int], int]:
    """(bytes per owner id, total). Counted toward the existing `job`
    category rather than a fifth quota category of its own: a plot is derived
    from jobs, is small, and is already garbage-collected by the
    last-source-job rule, so it needs honest accounting without its own
    oldest-first eviction pass."""
    by_owner: dict[str, int] = {}
    total = 0
    for record_file in list(PLOTS_DIR.glob("*/record.json")) + list(PLOTS_DIR.glob("*/*/record.json")):
        size = sum(f.stat().st_size for f in record_file.parent.glob("*") if f.is_file())
        total += size
        owner = _owner_of(record_file)
        if owner:
            by_owner[owner] = by_owner.get(owner, 0) + size
    return by_owner, total


def sweep_orphans() -> list[str]:
    """Delete every plot whose source jobs are ALL gone, and return their ids.

    This is the one rule the whole storage design rests on, so it is worth
    being precise about the two edges. A plot with an empty `job_ids` is never
    swept, since there is nothing to decide from and silently deleting it would
    be worse than keeping it. A plot keeps its record while even one source
    job survives, which is exactly the case that ruled out storing plots inside
    a job directory in the first place.

    Called after a job is deleted and after quota eviction, both of which can
    remove the last source without knowing a plot pointed at it."""
    removed = []
    for record in list_plots(owner_filter=None):
        job_ids = record.get("job_ids") or []
        if not job_ids:
            continue
        if any((JOBS_DIR / job_id).is_dir() for job_id in job_ids):
            continue
        if delete_plot(record.get("owner"), record["plot_id"]):
            removed.append(record["plot_id"])
    return removed


def context_summary(owner_filter: Optional[str], plot_id: str) -> str:
    """What the model is told when a plot is attached to a prompt.

    The spec and the NUMBERS, never a description of the picture. The model
    cannot see the PNG, so "which method is the outlier?" is answerable only
    from the values, and a prose description of a chart it cannot look at is
    exactly the sort of thing it would then confidently embroider.

    The numbers come from the record's cached `data` rather than being
    re-read from the jobs, so an attached plot stays answerable even after
    some of its sources have been evicted. Terminal job summaries do not
    change, so the cache cannot silently disagree with them."""
    record = get_plot(owner_filter, plot_id)
    if record is None:
        return f"Plot {plot_id} no longer exists."

    lines = [
        f"Plot {plot_id}: \"{record.get('label')}\" ({record.get('kind')}).",
        f"Drawn from job(s): {', '.join(record.get('job_ids') or []) or 'none recorded'}.",
    ]
    spec = record.get("spec") or {}
    style = spec.get("style")
    if style:
        lines.append(f"Style: {style}." + (" Log y axis." if spec.get("log_y") else ""))

    data = record.get("data") or {}
    columns = data.get("columns")
    series = data.get("series")
    if isinstance(columns, list) and isinstance(series, dict):
        header = "| | " + " | ".join(str(c) for c in columns) + " |"
        divider = "|---" * (len(columns) + 1) + "|"
        rows = [
            "| " + str(name) + " | "
            + " | ".join("" if v is None else f"{v:g}" for v in values) + " |"
            for name, values in series.items()
        ]
        lines += ["The values it draws:", header, divider, *rows]
    elif data:
        # A spectrum's own data is a pair of long parallel arrays rather than
        # a small labelled table, and pasting a few hundred numbers into every
        # turn would cost far more context than it is worth. Say what is there
        # and let the model ask the job for specifics if it needs them.
        lines.append("Underlying data: " + ", ".join(
            f"{k} ({len(v)} values)" if isinstance(v, list) else f"{k} = {v}"
            for k, v in data.items()))
    lines.append(f"To change it, call plot(kind=\"edit\", plot_id=\"{plot_id}\", spec=<just the parts to change>).")
    return "\n".join(lines)
