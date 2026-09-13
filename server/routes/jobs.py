"""Job status/detail/cancel. Deliberately reads status/spec/result via the
lock-free disk functions in app/chemistry/jobs/base.py, never through
graph.read_state()/_graph_lock -- see job_watcher.py's module docstring for
why job data must never share that lock with in-flight chat turns."""
from __future__ import annotations

import io
import math
import re
import tempfile
import zipfile
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse, Response

from app.agent import threads as thread_registry
from app.projects import registry as project_registry
from app.auth import models as auth_models
from app.auth.ownership import check_owner_or_admin, current_user_or_none, owned_ids_filter
from app.chemistry.jobs import molden as molden_tools
from app.chemistry.jobs import orca_runner
from app.chemistry.jobs.base import (
    NON_TERMINAL_STATUSES as _NON_TERMINAL_STATUSES,
    is_master_spec,
    delete_job_dir,
    get_job_manager,
    read_meta,
    read_spec,
    result_artifact_transaction,
    spec_created_at,
    sub_job_ids_of,
    write_meta,
)
from app.chemistry.jobs.ensemble_spectrum import pool_ensemble_transitions
from app.chemistry.registry2.params import DEFAULT_UVVIS_FWHM_EV
from app.chemistry.jobs.naming import job_download_name, job_filename_stem, resolve_job_label
from app.chemistry.jobs.quota import QUOTA_BYTES as JOB_QUOTA_BYTES
from app.chemistry.jobs.quota import current_usage_bytes as job_storage_usage_bytes
from app.chemistry.spectrum import render_ir_spectrum_plot, render_line_plot, render_uvvis_plot
from app.config import DATABASE_URL, JOBS_DIR, PLOTS_DIR
from server.schemas import RenameJobIn, RenderPlotIn

router = APIRouter()


def _attachment(filename: str) -> dict[str, str]:
    """The Content-Disposition header naming a job download, for the routes
    that build their own Response. The FileResponse ones below get the same
    header from Starlette by passing `filename=`; either way the name itself
    comes from job_download_name, so every file this app hands a user has
    the same three-part shape: `{safe job name}_{descriptor}{extension}`.

    Two routes used to send no such header at all -- the artifact route and
    raw_input -- which is how a Wigner ensemble's sampled geometries came
    down named "ensemble_xyz", with no extension, after the last segment of
    their URL.

    `filename` is safe to interpolate unquoted only because
    job_download_name slugifies both halves of it -- see naming.py."""
    return {"Content-Disposition": f'attachment; filename="{filename}"'}


# The download descriptor for each on-demand plot kind. The kind is an API
# parameter shaped by what the frontend renders inline ("uvvis_inline"), not
# a word anyone wants in a filename.
_PLOT_DESCRIPTORS = {
    "optimization_energy": "opt_energy_plot",
    "uvvis_inline": "uvvis_plot",
    "ir_spectrum_inline": "ir_plot",
}

# Artifact keys are internal names, and a few of them read badly as the
# descriptor half of a filename -- "..._ensemble_xyz.xyz" says "xyz" twice.
# Anything not listed here uses its key as-is, which reads fine
# ("pes_plot", "uvvis_spectrum", "molden", ...). Coordinates are called
# "coords" wherever they appear, here and in the frontend, rather than
# geometry in one place and xyz in another.
#
# Note the failure mode if an entry's key is wrong: it silently does
# nothing, because an unmatched key falls back to itself. Every key below
# is a real artifact key written by a runner or an orchestrator -- grep for
# it in app/chemistry/jobs/ before adding or renaming one.
_ARTIFACT_DESCRIPTORS = {
    # The drawer fetches this artifact's text and re-saves it itself, under
    # the name lib/jobFilename.ts's rawOutputFilename builds -- so a direct
    # hit on this route has to produce that same name, not "raw_output".
    "raw_output": "output",
    "ensemble_xyz": "sampled_coords",
    "path_xyz": "path_coords",
    "neb_frames": "path_coords",
    "mep_trajectory": "mep_coords",
    "ts_geometry": "ts_coords",
    "optimized_geometry_molden": "optimized_molden",
}


def _json_safe(value):
    """Replace non-finite floats with None, recursively.

    JSON has no way to write infinity or NaN, and FastAPI's encoder refuses
    rather than inventing one -- so a single `inf` anywhere in a summary
    raises `ValueError: Out of range float values are not JSON compliant`
    inside the response renderer and the whole request 500s. Which it did:
    an ORCA frequency job's `reduced_mass_amu` is deliberately `inf` for the
    six projected translation/rotation modes (their displacement vectors are
    exactly zero, so the mass ratio is undefined -- see
    `vibrations.reduced_masses_from_normal_modes`). That is a meaningful
    sentinel and worth keeping, but it made that job's detail endpoint fail
    permanently: every poll, every drawer open, 500.

    `None` is what JSON has for "no value", and every consumer of these
    arrays already handles nulls, so the sentinel survives the boundary with
    its meaning intact. Applied to whatever a job row contains rather than
    to the one field that was caught, because the next engine to emit a NaN
    should not brick a job the same way.
    """
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, dict):
        return {k: _json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(v) for v in value]
    return value


def _master_kind(task: str) -> str | None:
    """Which children-fetching/rendering shape a master job needs, or None
    for an ordinary job (or a childless master like geometry_set, which
    the frontend already renders through its own dedicated GeometrySetViewer
    without ever calling GET .../children). P7.4: replaces the former
    separate `is_scan_master`/`is_ensemble_master` booleans with one field
    rather than adding a third `is_batch_master` alongside them -- exactly
    the taxonomy duplication this project's no-legacy-compatibility rule
    targets; see docs/ARCHITECTURE.md."""
    if task in ("pes_1d", "interp_pes"):
        return "scan"
    if task == "wigner_spectra":
        return "ensemble"
    if task == "batch":
        return "batch"
    return None


def _job_row(job_id: str, spec: dict | None = None, need_result: bool = True) -> dict:
    """`spec`, if given, is used as-is instead of re-reading spec.json --
    list_all_jobs's own directory walk (_iter_all_job_specs) already reads
    every job's spec.json once to check parent_job_id, so a second,
    identical read here on every list poll was pure waste.

    `need_result=False` (only ever passed by _job_list_row) skips reading
    result.json entirely unless the job has actually failed. A trimmed
    list row only ever keeps `error` from it (summary/artifacts are popped
    right back off by the caller either way) -- parsing a potentially large
    result.json (a full orbital table, vibrational-mode list, etc.) for
    every non-failed job just to throw almost all of it away was the
    dominant disk/JSON-parsing cost of GET /api/jobs at even a few dozen
    jobs, repeated on every poll tick."""
    mgr = get_job_manager()
    status = mgr.status(job_id)
    spec = spec if spec is not None else (read_spec(job_id) or {})
    result = mgr.result(job_id) if (need_result or status["status"] == "failed") else None
    meta = read_meta(job_id)
    label = resolve_job_label(spec, meta)
    return _json_safe({
        "job_id": job_id,
        "status": status["status"],
        "message": status.get("message", ""),
        "updated_at": status.get("updated_at"),
        "created_at": spec_created_at(job_id, spec),
        # `method` is the level of theory (P2B.4); `task`/`subtype` are the
        # rest of the v2 taxonomy. P2B.5 moves the frontend's remaining
        # runner-key-keyed renderers onto these.
        "method": spec.get("method"),
        "task": spec.get("task") or "",
        "subtype": spec.get("subtype") or "",
        "engine": spec.get("engine"),
        "label": label,
        # The one authoritative filename stem, computed by
        # app/chemistry/jobs/naming.py and served rather than recomputed in
        # TypeScript. It used to exist twice, once per language, with a
        # comment on each copy asking whoever changed one to remember the
        # other -- and a drift between them is invisible to a browser test,
        # because the two names appear on different downloads.
        "filename_stem": job_filename_stem(
            job_id, spec, meta, spec_created_at(job_id, spec)),
        "master_kind": _master_kind(spec.get("task") or ""),
        "parent_job_id": spec.get("parent_job_id"),
        # The username of whoever shared this job, on a copy the caller
        # accepted from someone else; None on a job they ran themselves.
        # Read from meta.json, which this function already loads for the
        # label, so it costs nothing extra on a list poll and takes no lock
        # -- this module's contract (see its docstring) is unaffected.
        "shared_from": meta.get("shared_from"),
        # Only meaningful on the single-job GET (_job_list_row strips it
        # like summary/artifacts) -- needed by ModeAnimationViewer to
        # build a base geometry for a frequency job's vibration animation,
        # since job.params never carries the molecule (that's a separate
        # top-level field on JobSpec).
        "molecule": spec.get("molecule"),
        "params": {k: v for k, v in spec.get("params", {}).items() if not k.startswith("_")},
        "summary": (result or {}).get("summary"),
        "artifacts": (result or {}).get("artifacts"),
        "error": (result or {}).get("error"),
    })


def _job_list_row(job_id: str, spec: dict | None = None) -> dict:
    """A trimmed version of _job_row for the two list endpoints below,
    which only ever render status/label/engine/timestamps -- dropping
    summary/artifacts/full params keeps a large (up to 100GB-worth of
    jobs) job store cheap to list and poll. GET /api/jobs/{id} (single-job
    detail, used by JobDetailDrawer) is unaffected and still returns
    everything via _job_row."""
    row = _job_row(job_id, spec, need_result=False)
    row.pop("summary", None)
    row.pop("artifacts", None)
    row.pop("molecule", None)
    return row


def _iter_all_job_specs():
    # job_watcher.py's _SEEN_DIR ("_seen") lives inside JOBS_DIR but is its
    # own dedup bookkeeping, not a job -- must never show up in a job list.
    # A master's sub-job (spec.parent_job_id set -- pes_scan/wigner_ensemble,
    # see is_master_spec) is also excluded here -- it's only ever visible
    # nested under its master's own detail view (see get_scan_children
    # below), never as its own top-level row.
    #
    # Yields (job_id, spec) rather than just job_id -- list_all_jobs's own
    # per-row rendering (_job_row) needs this same spec.json again right
    # away, and re-reading/re-parsing it a second time for every job on
    # every list poll was pure waste (verified: this route reads spec.json
    # exactly once per job now, not twice).
    for d in JOBS_DIR.iterdir():
        if d.is_dir() and d.name != "_seen" and (d / "spec.json").exists():
            spec = read_spec(d.name)
            if spec is not None and spec.get("parent_job_id"):
                continue
            yield d.name, spec


@router.get("/api/jobs")
def list_all_jobs(request: Request, include_archived: bool = False):
    """Global, cross-thread job list for the persistent Job Manager panel
    -- distinct from GET /api/threads/{id}/jobs below, which stays scoped
    to one conversation's active_job_ids for the chat sidebar. Scans
    JOBS_DIR directly so a job from a since-deleted conversation still
    shows up here. Sorted newest-first by created_at.

    Scoped to the caller's own jobs when auth is configured for this
    deployment and the caller isn't an admin (owned_ids_filter returns
    None -- "don't filter" -- for an unauthenticated deployment or an
    admin caller, matching this route's pre-auth behavior of showing
    every job). A job with NO recorded owner (created before auth was
    configured) is always included -- see ownership.py's module
    docstring for the same legacy/unowned-resource reasoning. Uses one
    bulk all_owners() query rather than one get_owner() call per row, since
    this route is polled on an interval by every open tab (see
    JobManagerPanel.tsx) and a job store can hold thousands of entries.

    A job filed into a project archive is left out by default -- that is
    what makes archiving worth doing, since the point is to get a finished
    study off a list that otherwise only grows. include_archived=true
    brings them back, and every row then carries project_id/project_name so
    the panel can show which archive a row belongs to. Note that the
    per-conversation list below is deliberately NOT filtered: archiving is
    about this global list, and a job never stops belonging to the
    conversation that started it.

    job_project_map() is one read of a small flat JSON file
    (data/projects.json) and takes no lock of any kind, so this module's
    lock-free contract is intact -- see app/projects/registry.py."""
    user = current_user_or_none(request)
    owned = owned_ids_filter("job", user)
    rows = [_job_list_row(job_id, spec) for job_id, spec in _iter_all_job_specs()]
    if owned is not None:
        owners = auth_models.all_owners("job")
        rows = [r for r in rows if r["job_id"] in owned or r["job_id"] not in owners]
    archived = project_registry.job_project_map()
    if include_archived:
        for r in rows:
            entry = archived.get(r["job_id"])
            r["project_id"] = entry["project_id"] if entry else None
            r["project_name"] = entry["project_name"] if entry else None
    else:
        rows = [r for r in rows if r["job_id"] not in archived]
    rows.sort(key=lambda r: r["created_at"], reverse=True)
    return rows


@router.get("/api/jobs/quota")
def get_jobs_quota(request: Request):
    """Job-artifact storage usage for the Job Manager panel's usage
    display. Two different meanings depending on deployment: with no auth
    configured, the original flat app/chemistry/jobs/quota.py 100GB cap
    shared by everyone. With auth configured, the CALLER'S OWN job-storage
    usage against their per-user quota -- which is a combined cap shared
    with their chat history (see app/auth/storage_quota.py), so the
    reported quota_bytes here is that combined figure, not a jobs-only
    one; `category` tells the frontend which meaning it's looking at."""
    user = current_user_or_none(request)
    if user is not None:
        from app.auth.storage_quota import usage_report
        report = usage_report()
        row = next((r for r in report["per_user"] if r["user_id"] == str(user["id"])), None)
        if row is not None:
            return {
                "used_bytes": row["job_bytes"],
                "quota_bytes": row["jobs_and_chat_quota_bytes"],
                "category": "per_user_jobs_and_chat",
            }
    return {"used_bytes": job_storage_usage_bytes(), "quota_bytes": JOB_QUOTA_BYTES, "category": "global"}


_CHILDREN_PAGE_LIMIT_MAX = 500


@router.get("/api/jobs/{job_id}/children")
def get_scan_children(job_id: str, request: Request, offset: int = 0, limit: int = 100):
    """A master job's (pes_scan's per-image, or wigner_ensemble's
    per-sample -- see is_master_spec) sub-jobs, in path order -- the
    nested list/frame-viewer window JobDetailDrawer.tsx shows when a
    master is opened.

    P7.3: paginated (offset/limit) and trimmed to the same summary-only
    shape _job_list_row already uses for the top-level job list, not the
    full _job_row. Neither ScanFrameViewer/EnsembleFrameViewer nor the
    drawer's own child-button list read a child's summary/molecule/
    artifacts -- they only ever show its status/label (the geometry comes
    from the MASTER's own path_xyz/ensemble_xyz, one file, not per
    child); opening a specific child for its own full detail goes through
    a completely separate GET /api/jobs/{id} call (JobDetailDrawer
    recursing on itself), not through this list. Fetching and parsing
    every child's result.json here was pure waste at scan/ensemble sizes
    in the hundreds, on a route polled every 3 seconds while running.

    `offset`/`limit` index into sub_job_ids_of's already-sorted (by scan/
    ensemble index) order, so a page is a contiguous slice along the scan
    coordinate / sample index -- exactly what a FrameScrubber positioned
    at a given frame needs to request."""
    spec = read_spec(job_id)
    if spec is None:
        raise HTTPException(status_code=404, detail=f"No such job: {job_id}")
    check_owner_or_admin("job", job_id, current_user_or_none(request))
    if not is_master_spec(spec):
        raise HTTPException(
            status_code=400,
            detail=f"Job {job_id} has no sub-jobs -- it is not a scan, path or ensemble.")
    offset = max(0, offset)
    limit = max(1, min(limit, _CHILDREN_PAGE_LIMIT_MAX))
    all_ids = sub_job_ids_of(job_id)
    page_ids = all_ids[offset:offset + limit]
    return {
        "total": len(all_ids),
        "offset": offset,
        "items": [_job_list_row(sub_id) for sub_id in page_ids],
    }


@router.get("/api/jobs/{job_id}/wigner_transitions")
def get_wigner_transitions(job_id: str, request: Request):
    """Pooled raw (energy_eV, oscillator_strength) pairs across every
    sample of a wigner_spectra master, for P8.3's live broadening slider:
    fetched ONCE when the drawer opens, then re-broadened client-side on
    every slider move with no further request (the existing
    artifacts.ensemble_spectrum PNG -- see EnsembleSpectrumPanel.tsx -- is
    a server-rendered image at one fixed FWHM and would need a fresh
    render per move). Reuses pool_ensemble_transitions unmodified -- the
    same pooling EnsembleOrchestrator already does to build that PNG --
    so the two never disagree about which sub-jobs' transitions count.
    Works on a still-running ensemble the same as a completed one (any
    sub-job not yet completed is simply reported in diagnostics, not an
    error), matching P7.4/_resolve_batch_geometries's own precedent that a
    master's rendered-so-far data is readable before every child
    finishes."""
    spec = read_spec(job_id)
    if spec is None:
        raise HTTPException(status_code=404, detail=f"No such job: {job_id}")
    check_owner_or_admin("job", job_id, current_user_or_none(request))
    if spec.get("task") != "wigner_spectra":
        raise HTTPException(
            status_code=400,
            detail=f"Job {job_id} is not a wigner_spectra master.")
    pooled, diagnostics = pool_ensemble_transitions(sub_job_ids_of(job_id))
    return {"pooled": pooled, "diagnostics": diagnostics}


@router.get("/api/threads/{thread_id}/jobs")
def list_jobs(thread_id: str, request: Request):
    entry = thread_registry.get_thread(thread_id)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"No such conversation: {thread_id}")
    check_owner_or_admin("thread", thread_id, current_user_or_none(request))
    job_ids = entry.get("active_job_ids", [])
    return [_job_list_row(job_id) for job_id in reversed(job_ids)]


@router.get("/api/jobs/{job_id}")
def get_job(job_id: str, request: Request):
    spec = read_spec(job_id)
    if spec is None:
        raise HTTPException(status_code=404, detail=f"No such job: {job_id}")
    check_owner_or_admin("job", job_id, current_user_or_none(request))
    return _job_row(job_id)


@router.patch("/api/jobs/{job_id}")
def rename_job(job_id: str, body: RenameJobIn, request: Request):
    if read_spec(job_id) is None:
        raise HTTPException(status_code=404, detail=f"No such job: {job_id}")
    check_owner_or_admin("job", job_id, current_user_or_none(request))
    write_meta(job_id, {"label": body.label})
    return _job_row(job_id)


@router.delete("/api/jobs/{job_id}")
def remove_job(job_id: str, request: Request):
    if read_spec(job_id) is None:
        raise HTTPException(status_code=404, detail=f"No such job: {job_id}")
    check_owner_or_admin("job", job_id, current_user_or_none(request))
    status = get_job_manager().status(job_id)
    if status["status"] in _NON_TERMINAL_STATUSES:
        raise HTTPException(status_code=409, detail="Cancel the job before deleting it.")
    delete_job_dir(job_id)
    if DATABASE_URL:
        auth_models.forget_ownership("job", job_id)
    return {"deleted": True}


@router.post("/api/jobs/{job_id}/cancel")
def cancel_job(job_id: str, request: Request):
    if read_spec(job_id) is None:
        raise HTTPException(status_code=404, detail=f"No such job: {job_id}")
    check_owner_or_admin("job", job_id, current_user_or_none(request))
    cancelled = get_job_manager().cancel(job_id)
    return {"cancelled": cancelled, **_job_row(job_id)}


def _format_value(value) -> str:
    if isinstance(value, float):
        return f"{value:.6f}"
    if isinstance(value, list):
        return "[" + ", ".join(_format_value(v) for v in value) + "]"
    if isinstance(value, dict):
        return "{" + ", ".join(f"{k}: {_format_value(v)}" for k, v in value.items()) + "}"
    return str(value)


def _pyscf_text_summary(job_id: str, spec: dict, result: dict | None) -> str:
    """PySCF has no literal input/output file on disk (results come from
    in-memory PySCF objects, not a parsed text file -- see CLAUDE.md) so
    its "download" is a generated text report rather than a zip of files,
    built from the same summary/params data the job detail drawer already
    renders."""
    lines = [f"Job {job_id}", f"{spec.get('method')} / {spec.get('engine')}", ""]
    lines.append("Molecule:")
    molecule = spec.get("molecule") or {}
    lines.append(f"  name: {molecule.get('name')}")
    for sym, coord in zip(molecule.get("symbols", []), molecule.get("coords", [])):
        lines.append(f"  {sym:2s} {coord[0]: .8f} {coord[1]: .8f} {coord[2]: .8f}")
    lines.append("")
    lines.append("Parameters:")
    for k, v in (spec.get("params") or {}).items():
        if not k.startswith("_"):
            lines.append(f"  {k}: {_format_value(v)}")
    lines.append("")
    if result and result.get("status") == "failed":
        lines.append("Status: failed")
        lines.append(f"Error: {result.get('error')}")
    else:
        lines.append("Summary:")
        for k, v in ((result or {}).get("summary") or {}).items():
            lines.append(f"  {k}: {_format_value(v)}")
    return "\n".join(lines) + "\n"


@router.get("/api/jobs/{job_id}/download")
def download_job(job_id: str, request: Request):
    """PySCF: a generated plain-text summary (see _pyscf_text_summary --
    there's no literal input/output file to package). ORCA/BAGEL: a zip of
    every file in the job's directory (input/output text, retained .gbw,
    cubes, etc.), built entirely in memory -- /data is already close to
    full (see CLAUDE.md's known limitations), so this never writes the
    zip to disk, where it would also risk being swept into a later
    download of the very same job."""
    spec = read_spec(job_id)
    if spec is None:
        raise HTTPException(status_code=404, detail=f"No such job: {job_id}")
    check_owner_or_admin("job", job_id, current_user_or_none(request))

    # Named after the job rather than its id: a downloads folder full of
    # "78a32a61bab7.zip" says nothing about which calculation produced what.
    # job_filename_stem slugifies the label, which is also what stops a
    # free-text job name (set through PATCH /api/jobs/{id}) from injecting
    # anything into this header.
    stem = job_filename_stem(job_id, spec, read_meta(job_id), spec_created_at(job_id, spec))

    if spec.get("engine") == "pyscf":
        result = get_job_manager().result(job_id)
        text = _pyscf_text_summary(job_id, spec, result)
        return Response(
            content=text, media_type="text/plain",
            headers=_attachment(job_download_name(stem, "summary", ".txt")),
        )

    job_dir = JOBS_DIR / job_id
    if not job_dir.is_dir():
        raise HTTPException(status_code=404, detail=f"No job directory for: {job_id}")
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        for f in job_dir.iterdir():
            if f.is_file():
                zf.write(f, arcname=f.name)
    return Response(
        content=buffer.getvalue(), media_type="application/zip",
        # Only the zip itself is renamed. Its members keep the engine's own
        # names (arcname=f.name above): someone re-running an ORCA job from an
        # unpacked directory needs input.inp to still be called input.inp.
        headers=_attachment(job_download_name(stem, "jobfiles", ".zip")),
    )


_ENGINE_INPUT_FILES = {"orca": "input.inp", "bagel": "input.json"}


@router.get("/api/jobs/{job_id}/raw_input")
def get_job_raw_input(job_id: str, request: Request):
    """The literal input file ORCA/BAGEL's binary actually parsed --
    input.inp/input.json, written unconditionally before the engine runs
    (see orca_runner._write_and_run/bagel_runner._run_bagel), so this
    works for a running, failed, or completed job alike, and is
    byte-identical to a hand-edited approval-card submission (see
    submit_draft's _raw_input handling in tools.py). scratch.py's cleanup
    always keeps this file (see _ORCA_KEEP_NAMES / _bagel_scratch_files),
    so it stays available for the life of the job directory. PySCF has no
    such file (see CLAUDE.md/_pyscf_text_summary above) -- 404 there."""
    spec = read_spec(job_id)
    if spec is None:
        raise HTTPException(status_code=404, detail=f"No such job: {job_id}")
    check_owner_or_admin("job", job_id, current_user_or_none(request))
    filename = _ENGINE_INPUT_FILES.get(spec.get("engine"))
    if filename is None:
        raise HTTPException(status_code=404, detail="This engine has no literal input file")
    path = JOBS_DIR / job_id / filename
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Input file not found on disk")
    return Response(
        content=path.read_text(), media_type="text/plain",
        headers=_attachment(
            job_download_name(
                job_filename_stem(job_id, spec, read_meta(job_id), spec_created_at(job_id, spec)),
                "input", Path(filename).suffix,
            )
        ),
    )


@router.post("/api/jobs/{job_id}/render_plot")
def render_plot(job_id: str, body: RenderPlotIn, request: Request):
    """On-demand white-background/publication-style PNG for the two chart
    kinds that only ever exist as a hand-rolled SVG in the frontend today
    (OptimizationEnergyPlot.tsx, UvVisSpectrumInline.tsx) -- reusing
    app/chemistry/spectrum.py's matplotlib helpers (already used for the
    always-on-disk uvvis_spectrum/pes_plot artifacts) rather than adding a
    third rendering path. Not cached -- both are cheap to regenerate and
    rarely requested (a manual "download as PNG" click), so there's no
    result.json bookkeeping to add for this, unlike the lazy orbital-cube
    endpoint above. Rendered into a system temp file, never under
    JOBS_DIR/data -- /data is already close to full (see CLAUDE.md's known
    limitations) and this PNG isn't a job artifact worth keeping around."""
    check_owner_or_admin("job", job_id, current_user_or_none(request))
    result = get_job_manager().result(job_id)
    if result is None:
        raise HTTPException(status_code=404, detail=f"No result for job: {job_id}")
    summary = result.get("summary") or {}
    # Only needed to name the download; a missing spec is not worth failing a
    # render over, and job_filename_stem falls back to the short id alone.
    spec = read_spec(job_id) or {}

    with tempfile.TemporaryDirectory() as tmp_dir:
        out_path = str(Path(tmp_dir) / "plot.png")
        if body.kind == "optimization_energy":
            energies = summary.get("optimization_energies_hartree")
            if not energies or len(energies) < 2:
                raise HTTPException(status_code=400, detail="No optimization energy trace to plot for this job")
            render_line_plot(
                list(range(1, len(energies) + 1)), {"Energy": energies},
                "Optimization step", "Energy (Eh)", "Geometry optimization energy", out_path,
            )
        elif body.kind == "uvvis_inline":
            energies_eV = summary.get("excitation_energies_eV")
            strengths = summary.get("oscillator_strengths")
            if not energies_eV or not strengths or any(s is None for s in strengths):
                raise HTTPException(status_code=400, detail="No usable excitation/oscillator-strength data to plot")
            render_uvvis_plot(energies_eV, strengths, DEFAULT_UVVIS_FWHM_EV, out_path)
        elif body.kind == "ir_spectrum_inline":
            freqs = summary.get("frequencies_cm-1")
            ir = summary.get("ir_intensities_km_mol")
            if not freqs or not ir or any(i is None for i in ir):
                raise HTTPException(status_code=400, detail="No usable frequency/IR-intensity data to plot")
            render_ir_spectrum_plot(freqs, ir, 20.0, out_path)
        else:
            raise HTTPException(status_code=400, detail=f"Unknown plot kind '{body.kind}'")
        png_bytes = Path(out_path).read_bytes()

    return Response(
        content=png_bytes, media_type="image/png",
        # The one place this PNG gets named. The frontend used to pass its own
        # filename to downloadBlob, which won for a click in the UI and left a
        # direct hit on the route with a different name for the same bytes;
        # api.downloadPlotPng now reads this header instead.
        headers=_attachment(
            job_download_name(
                job_filename_stem(job_id, spec, read_meta(job_id), spec_created_at(job_id, spec)),
                _PLOT_DESCRIPTORS.get(body.kind, body.kind), ".png",
            )
        ),
    )


_ANSI_ESCAPE_RE = re.compile(r"\x1b\[[0-9;]*[a-zA-Z]")


def _tail_lines(path: Path, n: int, max_bytes: int = 65536) -> list[str]:
    """Last `n` lines of a text file without reading the whole thing into
    memory for a long-running job's worker.log (ORCA/BAGEL output can run
    to many MB) -- reads only the trailing max_bytes window, which is
    always enough to contain the last `n` lines unless individual lines
    are implausibly long. PySCF's geometry optimizer (pyberny/geomeTRIC)
    emits ANSI color codes into its progress lines regardless of whether
    stdout is a real terminal, which would otherwise show up as literal
    "[92m"-style text in the browser -- stripped here rather than in the
    frontend since this is the only consumer of worker.log text."""
    size = path.stat().st_size
    with open(path, "rb") as f:
        if size > max_bytes:
            f.seek(size - max_bytes)
        data = f.read()
    text = data.decode("utf-8", errors="replace")
    lines = text.splitlines()[-n:]
    return [_ANSI_ESCAPE_RE.sub("", line) for line in lines]


# ORCA/BAGEL are external binaries invoked via a nested subprocess.run()/
# shell redirect that writes their live stdout straight to their own
# output file, not to the worker process's own stdout -- so worker.log
# (which IS live for PySCF, which runs in-process) stays empty for these
# two engines the whole run. See orca_runner.py's _write_and_run and
# bagel_runner.py's _run_bagel for the exact (fixed, not input-derived)
# filenames this maps to.
_ENGINE_LOG_FILES = {"orca": "output.out", "bagel": "bagel.out"}


@router.get("/api/jobs/{job_id}/log")
def get_job_log(job_id: str, request: Request, lines: int = 20):
    """Tail of the job's live output, for the "tail -f"-style preview on a
    running job. Polled from the frontend rather than pushed over SSE --
    job_watcher.py's SSE events only fire on a status *transition* (see its
    module docstring), not continuously while a job stays "running", and a
    dedicated per-job polling loop is simpler than adding a second push
    channel for something this low-stakes (a raw log tail, not app state).

    Engine-aware: PySCF's engine output genuinely IS the worker
    subprocess's own stdout (worker.log). ORCA/BAGEL redirect their
    binary's stdout to a separate file instead, so for those two engines
    this tails that file, falling back to worker.log if it doesn't exist
    yet (job hasn't started writing engine output) or for any spec that
    predates the 'engine' field. On a failed ORCA/BAGEL job, a non-empty
    worker.log means the runner raised a Python-level error (e.g. before
    the engine binary even started) -- appended after the engine log so
    that traceback isn't silently hidden."""
    spec = read_spec(job_id)
    if spec is None:
        raise HTTPException(status_code=404, detail=f"No such job: {job_id}")
    check_owner_or_admin("job", job_id, current_user_or_none(request))
    n = max(1, min(lines, 200))
    job_dir = JOBS_DIR / job_id
    worker_log = job_dir / "worker.log"

    engine_log_name = _ENGINE_LOG_FILES.get(spec.get("engine"))
    if engine_log_name:
        engine_log = job_dir / engine_log_name
        if engine_log.exists() and engine_log.stat().st_size > 0:
            result_lines = _tail_lines(engine_log, n)
            status = get_job_manager().status(job_id)
            if status["status"] == "failed" and worker_log.exists() and worker_log.stat().st_size > 0:
                result_lines = result_lines + ["--- runner log ---"] + _tail_lines(worker_log, n)
            return {"lines": result_lines}

    if not worker_log.exists():
        return {"lines": []}
    return {"lines": _tail_lines(worker_log, n)}


_GBW_NAME_RE = re.compile(r"^input(_im\d+)?\.gbw$")
# The only two values `spin` ever legitimately carries: molden.py's
# cube_for_orbital maps it to alpha=0 / beta=1 and treats anything else as
# "not specified". It reaches the filesystem through cube_key, so it is
# allowlisted rather than merely ignored (R-005).
_SPIN_VALUES = ("alpha", "beta")


@router.post("/api/jobs/{job_id}/orbitals/{index}/cube")
def get_orbital_cube(job_id: str, index: int, request: Request, spin: str | None = None, gbw: str | None = None):
    """Lazily renders one orbital's cube file, keyed the same way
    OrbitalTable.tsx numbers rows (1-based, matching molden.orbital_table()
    and ORCA's _orbital_table()/render_orbital_cube conventions) -- generating a
    cube for every orbital of a job up front would waste compute for
    orbitals nobody ever looks at, so this generates on first click and
    caches the result into result.json's artifacts.cubes, keyed by
    "idx{N}"/"idx{N}_{spin}" (distinct from the "HOMO"/"LUMO" keys the
    originating mo_visualization job already wrote at submit time, so the
    two schemes never collide). Repeat requests are then a cache hit
    served by the existing GET .../artifacts/{key} path just as much as
    this endpoint -- both read the same cached file, this one just knows
    how to produce it the first time.

    Works for any job with the raw material to render one: a "molden"
    artifact (PySCF's and BAGEL's mo_visualization jobs write one; other
    job types don't yet) or, for ORCA, a retained input.gbw (kept by
    scratch.py for every completed ORCA job, not just mo_visualization
    ones -- see its docstring) via orca_plot, the same path
    run_mo_visualization itself uses. ORCA's molden export is
    deliberately never used here -- see render_orbital_cube's docstring for
    why it distorts orbital shapes.

    `gbw` (ORCA only) picks a specific .gbw file other than the job's own
    input.gbw -- used by neb_ts's per-frame orbital viewer to render from
    one path image's own wavefunction (input_im{N}.gbw). Strictly
    allowlist-validated against _GBW_NAME_RE before ever touching the
    filesystem, since it's client-supplied and otherwise builds a path
    directly; the cube cache key includes it so different frames' cubes
    for the "same" orbital index never collide.

    All three inputs that reach `cube_key` are validated, and R-005 is why
    that sentence is worth writing down. `gbw` was allowlisted and `spin`
    was not, although both are client-supplied query parameters and both
    land in the same `cube_key`, which two lines later becomes
    `job_dir / f"mo_{cube_key}.cube"`. The download NAME built from
    `cube_key` was slugified, with a comment saying it was slugified
    because `cube_key` carries client input, so the cosmetic surface was
    hardened while the real path beside it was not. `index` is bounded
    here too: FastAPI guarantees it is an integer and nothing guaranteed it
    was positive, and a negative index reached ORCA's plotting as
    `index - 1` (R-083)."""
    spec = read_spec(job_id)
    if spec is None:
        raise HTTPException(status_code=404, detail=f"No such job: {job_id}")
    check_owner_or_admin("job", job_id, current_user_or_none(request))
    result = get_job_manager().result(job_id)
    if result is None:
        raise HTTPException(status_code=404, detail=f"No result for job: {job_id}")

    if index < 1:
        raise HTTPException(
            status_code=400,
            detail=f"Orbital index must be 1 or greater (orbitals are numbered from 1 here); got {index}.",
        )
    if spin is not None and spin not in _SPIN_VALUES:
        raise HTTPException(
            status_code=400,
            detail=f"spin must be one of {', '.join(_SPIN_VALUES)} if given; got {spin!r}.",
        )
    gbw_filename = "input.gbw"
    if gbw is not None:
        if not _GBW_NAME_RE.match(gbw):
            raise HTTPException(status_code=400, detail=f"Invalid gbw filename: {gbw!r}")
        gbw_filename = gbw

    cube_key = f"idx{index}" + (f"_{spin}" if spin else "") + (f"_{gbw_filename}" if gbw is not None else "")
    # Named for the same reason every other download here is, and slugified
    # for one reason the others aren't: cube_key can carry the client-supplied
    # `gbw` filename.
    cube_name = job_download_name(
        job_filename_stem(job_id, spec, read_meta(job_id), spec_created_at(job_id, spec)),
        f"orbital_{cube_key}", ".cube",
    )
    artifacts = dict(result.get("artifacts") or {})
    cubes = dict(artifacts.get("cubes") or {})
    cached = cubes.get(cube_key)
    if cached and Path(cached).exists():
        return FileResponse(cached, filename=cube_name)

    job_dir = JOBS_DIR / job_id
    cube_path = job_dir / f"mo_{cube_key}.cube"
    # Defence in depth behind the three allowlists above: the path that is
    # actually written must land in this job's own directory, whatever
    # cube_key turned out to be.
    if cube_path.resolve().parent != job_dir.resolve():
        raise HTTPException(status_code=400, detail="Invalid orbital request.")
    engine = spec.get("engine")
    if engine == "orca":
        gbw_path = job_dir / gbw_filename
        if not gbw_path.exists():
            raise HTTPException(
                status_code=404, detail=f"{gbw_filename} not retained for this job -- cannot render orbitals lazily"
            )
        try:
            raw_cube = orca_runner.render_orbital_cube(str(job_dir), index - 1, gbw_filename=gbw_filename)
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f"orca_plot failed: {exc}")
        Path(raw_cube).replace(cube_path)
    else:
        molden_path = artifacts.get("molden")
        if not molden_path or not Path(molden_path).exists():
            raise HTTPException(
                status_code=404, detail="no molden artifact for this job -- cannot render orbitals lazily"
            )
        try:
            molden_tools.cube_for_orbital(molden_path, index, str(cube_path), spin=spin)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))

    # Re-reads artifacts fresh under result_artifact_transaction's lock
    # rather than reusing the `artifacts`/`cubes` dicts read at the top of
    # this function -- two concurrent requests for different orbitals of
    # the same job (plausible: a user clicking through several OrbitalTable
    # rows quickly) would otherwise each build their own stale copy of
    # `cubes` and the second write to finish would silently drop the
    # first's newly-cached entry.
    with result_artifact_transaction(job_id) as fresh_artifacts:
        if fresh_artifacts is not None:
            fresh_cubes = dict(fresh_artifacts.get("cubes") or {})
            fresh_cubes[cube_key] = str(cube_path)
            fresh_artifacts["cubes"] = fresh_cubes
    return FileResponse(cube_path, filename=cube_name)


@router.get("/api/jobs/{job_id}/neb_frames_live")
def get_neb_frames_live(job_id: str, request: Request):
    """The current, still-in-progress path for a running neb_ts job --
    NOT input_MEP_trj.xyz (which, verified against a real run, is written
    exactly once when the NEB/CI-NEB part itself converges and never
    updated again, despite its name), but input_MEP_ALL_trj.xyz, which
    genuinely grows by one full path's worth of frames every NEB
    iteration (confirmed: its size increased between two polls of a still-
    running job while input_MEP_trj.xyz didn't exist yet at all). Returns
    the LAST n_images_total frames (one full iteration's worth) as
    multi-frame xyz text, same format the completed-job artifacts.neb_frames
    route already returns -- the frontend's parseMultiFrameXyz doesn't care
    which route produced it. A live disk read on every call (like /log's
    tail), not cached in result.json, since the file is still being
    written and there's nothing to cache until the job actually completes.
    Returns an empty frame list (200, not 404) if the file doesn't exist
    yet (NEB hasn't started iterating) or the job isn't a neb_ts job at
    all, so a polling frontend doesn't need to special-case those as
    errors."""
    spec = read_spec(job_id)
    if spec is None:
        raise HTTPException(status_code=404, detail=f"No such job: {job_id}")
    check_owner_or_admin("job", job_id, current_user_or_none(request))
    if spec.get("task") != "neb_ts":
        return Response(content="", media_type="text/plain")

    n_images = spec.get("params", {}).get("n_images", 6)
    n_images_total = int(n_images) + 2
    all_trj_path = JOBS_DIR / job_id / "input_MEP_ALL_trj.xyz"
    if not all_trj_path.exists():
        return Response(content="", media_type="text/plain")

    text = all_trj_path.read_text()
    frames = orca_runner.split_xyz_frames(text)
    last_iteration = frames[-n_images_total:] if frames else []
    return Response(content="".join(last_iteration), media_type="text/plain")


@router.get("/api/jobs/{job_id}/artifacts/{key:path}")
def get_job_artifact(job_id: str, key: str, request: Request):
    """Serves a single named artifact file (a cube file under
    artifacts.cubes.<label>, or artifacts.uvvis_spectrum, etc.) -- `key`
    may contain '/' to reach a value nested in a dict artifact. The path
    actually opened always comes from this job's own result.json (written
    server-side, never user-supplied), but a defense-in-depth check still
    confirms the resolved path is actually under JOBS_DIR before serving
    it, in case an artifact path was ever malformed.

    check_owner_or_admin call added here -- this was the one resource-
    scoped route in this file that never got one, confirmed by reading
    every other handler here (all of which call it) and live-testing this
    one specifically: it served any job's artifacts to any caller,
    including a caller with no session cookie at all, since nothing here
    ever touched auth. Safe to add without breaking the plain `<img src=
    "/api/jobs/{id}/artifacts/{key}">`/`<a href=...>` usage this route is
    built for (UvVisPanel, MoCubeViewer, etc.) -- the session cookie is
    httpOnly+SameSite=Lax, which browsers still attach to same-origin
    subresource requests like these, not just fetch()/XHR calls."""
    check_owner_or_admin("job", job_id, current_user_or_none(request))
    result = get_job_manager().result(job_id)
    if result is None:
        raise HTTPException(status_code=404, detail=f"No result for job: {job_id}")
    node = result.get("artifacts") or {}
    for part in key.split("/"):
        if not isinstance(node, dict) or part not in node:
            raise HTTPException(status_code=404, detail=f"No such artifact: {key}")
        node = node[part]
    if not isinstance(node, str):
        raise HTTPException(status_code=404, detail=f"Artifact '{key}' is not a file")

    try:
        path = Path(node).resolve(strict=True)
    except OSError:
        raise HTTPException(status_code=404, detail=f"Artifact file missing on disk: {key}")
    # Two roots, both fixed: a job's own files, and the plot store. A
    # spectrum's PNG lives in the plot store now (it is a saved plot like any
    # other, see app/plots/store.py) while still being registered under the
    # artifact key the job drawer's panels fetch it by, so containment has to
    # admit that second root or every spectrum panel 404s. Still an
    # allowlist of two known directories, not a relaxation to "anywhere":
    # ensemble_spectrum_data, for one, is genuinely job data and stays under
    # JOBS_DIR.
    allowed_roots = (JOBS_DIR.resolve(), PLOTS_DIR.resolve())
    if not any(root in path.parents for root in allowed_roots):
        raise HTTPException(status_code=403, detail="Artifact path escapes the jobs and plots directories")

    # The extension comes off the file the writer actually wrote, not from a
    # table here: a second list of "which artifact is which format" would be
    # exactly the copy that drifts. A suffixless file stays suffixless --
    # inventing an extension is worse than omitting one.
    spec = read_spec(job_id)
    stem = job_filename_stem(job_id, spec, read_meta(job_id), spec_created_at(job_id, spec))
    descriptor = _ARTIFACT_DESCRIPTORS.get(key, key)
    return FileResponse(path, filename=job_download_name(stem, descriptor, path.suffix))
