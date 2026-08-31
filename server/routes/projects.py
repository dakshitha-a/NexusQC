"""Project archives: named bundles of jobs, and the zip that packages one.

A separate module from server/routes/jobs.py on purpose. That file carries
a contract -- it never calls read_state() or takes the graph lock, so
job polling cannot stall behind a chat turn -- and a reviewer should not
have to re-verify it every time the archive feature changes. Everything
here reads the same lock-free disk functions plus one flat JSON registry,
so the same property holds, but it holds separately.

Every handler is a plain `def`, never `async def`: a sync handler runs in
the worker threadpool, while an `async def` that blocks stalls the single
event loop and with it SSE delivery to every other open tab. That matters
more here than in most modules, because the download route below streams
a potentially very large zip.
"""
from __future__ import annotations

import csv
import datetime
import io
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse

from app.auth import models as auth_models
from app.auth.ownership import check_owner_or_admin, current_user_or_none, owned_ids_filter, record
from app.chemistry.jobs.base import (
    NON_TERMINAL_STATUSES as _NON_TERMINAL_STATUSES,
    delete_job_dir,
    read_meta,
    read_spec,
    read_status,
    spec_created_at,
)
from app.chemistry.jobs.naming import job_download_name, job_filename_stem, resolve_job_label, slugify_label
from app.config import DATABASE_URL, JOBS_DIR
from app.projects import registry
from app.projects.zipstream import stream_zip
from server.schemas import CreateProjectIn, ProjectJobsIn, UpdateProjectIn

router = APIRouter()


def _row(project: dict, size_bytes: int) -> dict:
    """What the left rail renders. job_ids comes along because the panel
    needs to know which jobs to un-archive without a second round trip."""
    return {
        "project_id": project["project_id"],
        "name": project["name"],
        "description": project["description"],
        "created_at": project["created_at"],
        "updated_at": project["updated_at"],
        "job_ids": list(project["job_ids"]),
        "job_count": len(project["job_ids"]),
        "size_bytes": size_bytes,
    }


def _require(project_id: str, request: Request) -> dict:
    """404 for a project that does not exist, and the identical 404 for one
    owned by somebody else -- check_owner_or_admin deliberately does not
    distinguish the two, so this route cannot be used to probe which
    project ids exist on a deployment."""
    project = registry.get_project(project_id)
    if project is None:
        raise HTTPException(status_code=404, detail=f"No such project: {project_id}")
    check_owner_or_admin("project", project_id, current_user_or_none(request))
    return project


# Declared before the /{project_id} routes below. FastAPI matches in
# declaration order, so a literal path that shares a prefix with a
# parameterised one has to come first or the parameterised route swallows
# it and "purge-mine" arrives as a project id.
@router.post("/api/projects/purge-mine")
def purge_my_projects(request: Request):
    """Deletes every project the CALLER owns, and the jobs in them. The
    per-user danger-zone action, alongside "delete all my data".

    Scoped off list_owned() rather than off this module's own list route,
    and the distinction is load-bearing rather than stylistic.
    owned_ids_filter() returns None -- meaning "do not filter" -- for an
    admin, so GET /api/projects shows an admin every project on the
    deployment. An admin typing the confirmation phrase into a control
    labelled "delete all of MY projects" must not wipe everybody else's,
    so ownership is resolved explicitly here and never inherited from what
    the list route happens to show. Same shape as the artifact-route leak
    recorded in server/routes/jobs.py's get_job_artifact docstring.

    A deployment with no auth configured has no "me" to scope to, so this
    refuses rather than guessing that it means "everything"."""
    user = current_user_or_none(request)
    if user is None:
        raise HTTPException(
            status_code=400,
            detail="This deployment has no user accounts, so there is no set of projects to scope this to.",
        )
    mine = set(auth_models.list_owned("project", str(user["id"])))
    projects = [p for p in registry.list_projects() if p["project_id"] in mine]
    job_ids = [j for p in projects for j in p["job_ids"]]
    registry.delete_projects([p["project_id"] for p in projects])
    for project_id in mine:
        auth_models.forget_ownership("project", project_id)
    purged = _delete_jobs(job_ids)
    return {"purged_projects": len(projects), "purged_jobs": purged}


@router.get("/api/projects")
def list_projects(request: Request):
    """Scoped to the caller's own projects when auth is configured and the
    caller is not an admin, matching GET /api/jobs exactly. A project with
    no recorded owner stays visible to everyone, for the same reason an
    unowned job does: it was created before auth, or outside it, and
    hiding it from everybody would make it unreachable rather than
    private."""
    user = current_user_or_none(request)
    owned = owned_ids_filter("project", user)
    projects = registry.list_projects()
    if owned is not None:
        owners = auth_models.all_owners("project")
        projects = [p for p in projects if p["project_id"] in owned or p["project_id"] not in owners]
    sizes = registry.project_sizes(projects)
    return [_row(p, sizes.get(p["project_id"], 0)) for p in projects]


@router.post("/api/projects")
def create_project(body: CreateProjectIn, request: Request):
    user = current_user_or_none(request)
    project = registry.create_project(body.name, body.description)
    record("project", project["project_id"], user)
    if body.job_ids:
        _check_jobs(body.job_ids, request)
        project = registry.add_jobs(project["project_id"], body.job_ids)
    return _row(project, registry.project_sizes([project]).get(project["project_id"], 0))


@router.get("/api/projects/{project_id}")
def get_project(project_id: str, request: Request):
    """The project plus a row per member job, in the same shape the job
    manager's own list uses (imported from server/routes/jobs.py rather
    than rebuilt, so the archive's job table and the job manager can never
    drift apart)."""
    from server.routes.jobs import _job_list_row

    project = _require(project_id, request)
    jobs = []
    for job_id in project["job_ids"]:
        spec = read_spec(job_id)
        if spec is not None:
            jobs.append(_job_list_row(job_id, spec))
    jobs.sort(key=lambda r: r["created_at"], reverse=True)
    row = _row(project, registry.project_sizes([project]).get(project_id, 0))
    row["jobs"] = jobs
    return row


@router.patch("/api/projects/{project_id}")
def update_project(project_id: str, body: UpdateProjectIn, request: Request):
    _require(project_id, request)
    project = registry.update_project(project_id, name=body.name, description=body.description)
    if project is None:
        raise HTTPException(status_code=404, detail=f"No such project: {project_id}")
    return _row(project, registry.project_sizes([project]).get(project_id, 0))


def _check_jobs(job_ids: list[str], request: Request) -> None:
    """A user must not be able to file away a job they cannot see. Each id
    is checked individually, which is what makes the archive respect the
    same ownership boundary the job list does."""
    user = current_user_or_none(request)
    for job_id in job_ids:
        if read_spec(job_id) is None:
            raise HTTPException(status_code=404, detail=f"No such job: {job_id}")
        check_owner_or_admin("job", job_id, user)


@router.post("/api/projects/{project_id}/jobs")
def add_project_jobs(project_id: str, body: ProjectJobsIn, request: Request):
    """Files jobs into this project, moving each out of whichever project
    currently holds it -- a job belongs to at most one. Nothing on disk
    moves; see app/projects/registry.py's docstring."""
    _require(project_id, request)
    _check_jobs(body.job_ids, request)
    project = registry.add_jobs(project_id, body.job_ids)
    if project is None:
        raise HTTPException(status_code=404, detail=f"No such project: {project_id}")
    return _row(project, registry.project_sizes([project]).get(project_id, 0))


@router.post("/api/projects/{project_id}/jobs/remove")
def remove_project_jobs(project_id: str, body: ProjectJobsIn, request: Request):
    """Returns jobs to the job manager. Purely a registry edit: the job
    directories were never moved, so there is nothing to restore.

    A POST rather than a DELETE carrying a body. DELETE-with-body is legal
    but poorly supported on both sides -- httpx's client.delete() takes no
    json= argument at all, which every test script here would have to work
    around -- and this removes nothing, it moves jobs back into view."""
    _require(project_id, request)
    project = registry.remove_jobs(project_id, body.job_ids)
    if project is None:
        raise HTTPException(status_code=404, detail=f"No such project: {project_id}")
    return _row(project, registry.project_sizes([project]).get(project_id, 0))


def _delete_jobs(job_ids: list[str]) -> int:
    """Deletes job directories, cancelling anything still running first.
    delete_job_dir does not check terminality and will happily remove a
    running job's directory out from under its worker, which is why
    DELETE /api/jobs/{id} answers 409 rather than doing it. A cascading
    project delete cannot answer 409 -- the user has already said to
    delete the jobs -- so it cancels and waits instead, reusing the same
    helper account deletion uses."""
    from app.auth.storage_quota import _cancel_and_await_terminal

    deleted = 0
    for job_id in job_ids:
        if read_spec(job_id) is None:
            continue
        status = (read_status(job_id) or {}).get("status")
        if status in _NON_TERMINAL_STATUSES:
            _cancel_and_await_terminal(job_id)
        delete_job_dir(job_id)
        if DATABASE_URL:
            auth_models.forget_ownership("job", job_id)
        deleted += 1
    return deleted


@router.delete("/api/projects/{project_id}")
def delete_project(project_id: str, request: Request, delete_jobs: bool = False):
    """delete_jobs is an explicit query parameter with no sensible default,
    because the two answers are genuinely different actions and the user
    is asked every time. False dissolves the grouping and its jobs
    reappear in the job manager untouched; True deletes the results too,
    and is what the typed confirmation in the UI is guarding."""
    _require(project_id, request)
    project = registry.delete_project(project_id)
    if project is None:
        raise HTTPException(status_code=404, detail=f"No such project: {project_id}")
    if DATABASE_URL:
        auth_models.forget_ownership("project", project_id)
    purged = _delete_jobs(project["job_ids"]) if delete_jobs else 0
    return {"deleted": True, "released_jobs": 0 if delete_jobs else len(project["job_ids"]), "purged_jobs": purged}


def _manifest_csv(project: dict, jobs: list[tuple[str, dict]], skipped: list[str]) -> bytes:
    """The thing that makes an archive readable a year later. A directory
    of engine output files says nothing about which calculation produced
    which; this says it in one table, in the terms a chemist would use
    rather than internal identifiers."""
    from app.chemistry.jobs.base import read_result
    from app.chemistry.jobs.quota import _cached_dir_size

    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["job name", "job id", "engine", "method", "calculation", "status",
                "created", "size (bytes)", "files", "summary"])
    for job_id, spec in jobs:
        meta = read_meta(job_id)
        status = (read_status(job_id) or {}).get("status", "unknown")
        try:
            size = _cached_dir_size(job_id)
        except OSError:
            size = 0
        job_dir = JOBS_DIR / job_id
        files = sorted(f.name for f in job_dir.iterdir() if f.is_file()) if job_dir.is_dir() else []
        summary = ((read_result(job_id) or {}).get("summary") or {})
        headline = "; ".join(f"{k}={v}" for k, v in list(summary.items())[:6])
        w.writerow([
            resolve_job_label(spec, meta), job_id, spec.get("engine", ""), spec.get("method", ""),
            spec.get("task", ""), status,
            _utc_day(spec_created_at(job_id, spec), "%Y-%m-%d %H:%M UTC"),
            size, " ".join(files), headline,
        ])
    if skipped:
        w.writerow([])
        w.writerow([f"{len(skipped)} job(s) in this project were not included, because they are owned by "
                    "another user or their files are gone:"])
        for job_id in skipped:
            w.writerow([job_id])
    return buf.getvalue().encode("utf-8")


def _utc_day(epoch: float, fmt: str) -> str:
    return datetime.datetime.fromtimestamp(epoch, datetime.timezone.utc).strftime(fmt)


def _project_stem(project: dict) -> str:
    """Named after the project rather than its id, for the same reason a
    job download is: a downloads folder full of a1b2c3d4e5f6.zip says
    nothing about which study produced what. slugify_label is also what
    stops a free-text project name from injecting anything into the
    Content-Disposition header."""
    day = _utc_day(project["created_at"], "%Y%m%d")
    return f"{day}_{slugify_label(project['name'])}_{project['project_id'][:6]}"


@router.get("/api/projects/{project_id}/download")
def download_project(project_id: str, request: Request):
    """One zip holding every job in the project, plus a manifest.

    Streamed, never assembled in memory. The per-job download in
    server/routes/jobs.py builds its zip in a BytesIO and says in its own
    comment that this is because /data is close to full, so writing it out
    is not an option either. That trade is fine for one job and not fine
    for a project: a single orbital cube here runs to several megabytes,
    and a study-sized archive would sit resident in a threadpool worker
    for the length of the download. See app/projects/zipstream.py.

    A member job the caller cannot read is skipped rather than failing the
    whole download, and the manifest says so by name. That case only
    arises for an admin-assembled project, but a half-successful download
    that silently omits things is worse than one that admits it."""
    project = _require(project_id, request)
    user = current_user_or_none(request)

    included: list[tuple[str, dict]] = []
    skipped: list[str] = []
    for job_id in project["job_ids"]:
        spec = read_spec(job_id)
        if spec is None:
            skipped.append(job_id)
            continue
        try:
            check_owner_or_admin("job", job_id, user)
        except HTTPException:
            skipped.append(job_id)
            continue
        included.append((job_id, spec))

    stem = _project_stem(project)

    def entries():
        """(arcname, path_or_bytes) pairs, yielded lazily so no more than
        one job's worth of paths is held at a time."""
        yield f"{stem}_manifest.csv", _manifest_csv(project, included, skipped)
        for job_id, spec in included:
            job_stem = job_filename_stem(job_id, spec, read_meta(job_id), spec_created_at(job_id, spec))
            if spec.get("engine") == "pyscf":
                # No literal input/output file exists for a PySCF job, so it
                # gets the same generated text summary the single-job
                # download hands out. Imported here rather than at module
                # scope to keep this module's import graph free of the
                # lock-free jobs router at startup.
                from server.routes.jobs import _pyscf_text_summary
                from app.chemistry.jobs.base import read_result

                text = _pyscf_text_summary(job_id, spec, read_result(job_id))
                yield f"jobs/{job_download_name(job_stem, 'summary', '.txt')}", text.encode("utf-8")
                continue
            job_dir = JOBS_DIR / job_id
            if not job_dir.is_dir():
                continue
            for f in sorted(job_dir.iterdir()):
                if f.is_file():
                    # Members keep the engine's own names: someone re-running
                    # an ORCA job from an unpacked directory needs input.inp
                    # to still be called input.inp. Only the zip is renamed.
                    yield f"jobs/{job_stem}/{f.name}", f

    filename = job_download_name(stem, "archive", ".zip")
    return StreamingResponse(
        stream_zip(entries()),
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
