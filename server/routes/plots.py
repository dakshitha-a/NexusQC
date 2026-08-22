"""Saved plots: list, view, download, rename, delete.

Mirrors server/routes/uploads.py's shape, against app/plots/store.py rather
than the uploads store, because a plot is the same kind of thing as an upload
in every way that matters to a route: a user-owned artifact that is not a job,
scoped by owner directory, with a per-item sidecar. Handlers are plain `def`,
per CLAUDE.md, and this router must never call read_state() or take the graph
lock, the same rule server/routes/jobs.py follows.

The one thing here that is not in uploads.py is the last-source-job sweep. A
plot can outlive some of its sources but not all of them, and neither job
deletion nor quota eviction knows that a plot pointed at what it removed, so
the sweep runs on list and delete rather than being hooked into every path
that can remove a job.
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel

from app.auth.ownership import check_owner_or_admin, current_user_or_none
from app.chemistry.jobs.naming import job_download_name, slugify_label
from app.plots import store as plot_store

router = APIRouter()


class RenamePlotIn(BaseModel):
    label: str


def _owner_key(request: Request) -> str | None:
    """The id to WRITE under: the caller's own, or None with no auth."""
    user = current_user_or_none(request)
    return str(user["id"]) if user is not None else None


def _owner_filter(request: Request) -> str | None:
    """The filter to READ/DELETE with: None for admin or no-auth (see
    everything), else the caller's own id. Mirrors uploads.py exactly."""
    user = current_user_or_none(request)
    if user is None or user["role"] == "admin":
        return None
    return str(user["id"])


def _row(record: dict) -> dict:
    """One list row. The cached `data` block is deliberately dropped here: it
    can hold a few hundred numbers per plot and the panel only ever shows a
    thumbnail and a name. It is fetched with the single-plot GET, and it is
    what plot_context_summary reads when a plot is attached to a prompt."""
    return {k: v for k, v in record.items() if k != "data"}


@router.get("/api/plots")
def get_plots(request: Request):
    plot_store.sweep_orphans()
    return [_row(r) for r in plot_store.list_plots(owner_filter=_owner_filter(request))]


@router.get("/api/plots/{plot_id}")
def get_plot(plot_id: str, request: Request):
    record = plot_store.get_plot(_owner_filter(request), plot_id)
    if record is None:
        raise HTTPException(status_code=404, detail="No such plot")
    check_owner_or_admin("plot", plot_id, current_user_or_none(request))
    return record


@router.get("/api/plots/{plot_id}/versions/{version}.png")
def get_plot_image(plot_id: str, version: str, request: Request):
    """One rendered version. Versioned rather than "the current image" on
    purpose: a chat message cites the version it actually drew, so an edit
    cannot retroactively change what an older message appears to show."""
    owner_filter = _owner_filter(request)
    record = plot_store.get_plot(owner_filter, plot_id)
    if record is None:
        raise HTTPException(status_code=404, detail="No such plot")
    check_owner_or_admin("plot", plot_id, current_user_or_none(request))
    path = plot_store.version_path(owner_filter, plot_id, version)
    if path is None:
        raise HTTPException(status_code=404, detail="No such plot version")
    return FileResponse(path, media_type="image/png")


@router.get("/api/plots/{plot_id}/download")
def download_plot(plot_id: str, request: Request):
    """The latest version, named for a downloads folder rather than by id.
    Same three-part convention every job file follows (see
    app/chemistry/jobs/naming.py): a safe name, a word saying what the file
    is, and a real extension."""
    owner_filter = _owner_filter(request)
    record = plot_store.get_plot(owner_filter, plot_id)
    if record is None:
        raise HTTPException(status_code=404, detail="No such plot")
    check_owner_or_admin("plot", plot_id, current_user_or_none(request))
    version = plot_store.latest_version(record)
    path = plot_store.version_path(owner_filter, plot_id, version) if version else None
    if path is None:
        raise HTTPException(status_code=404, detail="This plot has no rendered image")
    stem = slugify_label(record.get("label") or plot_id)
    return FileResponse(path, media_type="image/png",
                        filename=job_download_name(stem, "plot", ".png"))


@router.patch("/api/plots/{plot_id}")
def rename_plot(plot_id: str, body: RenamePlotIn, request: Request):
    owner_filter = _owner_filter(request)
    if plot_store.get_plot(owner_filter, plot_id) is None:
        raise HTTPException(status_code=404, detail="No such plot")
    check_owner_or_admin("plot", plot_id, current_user_or_none(request))
    record = plot_store.update_plot(_plot_owner_dir(owner_filter, plot_id), plot_id, label=body.label)
    return _row(record) if record else {}


@router.delete("/api/plots/{plot_id}")
def remove_plot(plot_id: str, request: Request):
    owner_filter = _owner_filter(request)
    if plot_store.get_plot(owner_filter, plot_id) is None:
        raise HTTPException(status_code=404, detail="No such plot")
    check_owner_or_admin("plot", plot_id, current_user_or_none(request))
    plot_store.delete_plot(owner_filter, plot_id)
    return {"deleted": plot_id}


def _plot_owner_dir(owner_filter: str | None, plot_id: str) -> str | None:
    """The owner a plot actually lives under. An admin reads with
    owner_filter=None but must still write into the owning user's directory,
    so the record's own `owner` is the authority, not the caller's identity."""
    record = plot_store.get_plot(owner_filter, plot_id)
    return record.get("owner") if record else owner_filter
