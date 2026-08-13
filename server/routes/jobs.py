"""Job status/detail/cancel. Deliberately reads status/spec/result via the
lock-free disk functions in app/chemistry/jobs/base.py, never through
graph.read_state()/_graph_lock -- see job_watcher.py's module docstring for
why job data must never share that lock with in-flight chat turns."""
from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from app.agent import threads as thread_registry
from app.chemistry.jobs.base import get_job_manager, read_spec
from app.config import JOBS_DIR

router = APIRouter()


def _job_row(job_id: str) -> dict:
    mgr = get_job_manager()
    status = mgr.status(job_id)
    result = mgr.result(job_id)
    spec = read_spec(job_id) or {}
    return {
        "job_id": job_id,
        "status": status["status"],
        "message": status.get("message", ""),
        "updated_at": status.get("updated_at"),
        "method": spec.get("method"),
        "engine": spec.get("engine"),
        "label": spec.get("label", ""),
        "params": {k: v for k, v in spec.get("params", {}).items() if not k.startswith("_")},
        "retried_from": spec.get("params", {}).get("_retried_from"),
        "retry_count": spec.get("params", {}).get("_retry_count", 0),
        "summary": (result or {}).get("summary"),
        "artifacts": (result or {}).get("artifacts"),
        "error": (result or {}).get("error"),
    }


@router.get("/api/threads/{thread_id}/jobs")
def list_jobs(thread_id: str):
    entry = thread_registry.get_thread(thread_id)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"No such conversation: {thread_id}")
    job_ids = entry.get("active_job_ids", [])
    return [_job_row(job_id) for job_id in reversed(job_ids)]


@router.get("/api/jobs/{job_id}")
def get_job(job_id: str):
    spec = read_spec(job_id)
    if spec is None:
        raise HTTPException(status_code=404, detail=f"No such job: {job_id}")
    return _job_row(job_id)


@router.post("/api/jobs/{job_id}/cancel")
def cancel_job(job_id: str):
    if read_spec(job_id) is None:
        raise HTTPException(status_code=404, detail=f"No such job: {job_id}")
    cancelled = get_job_manager().cancel(job_id)
    return {"cancelled": cancelled, **_job_row(job_id)}


@router.get("/api/jobs/{job_id}/artifacts/{key:path}")
def get_job_artifact(job_id: str, key: str):
    """Serves a single named artifact file (a cube file under
    artifacts.cubes.<label>, or artifacts.uvvis_spectrum, etc.) -- `key`
    may contain '/' to reach a value nested in a dict artifact. The path
    actually opened always comes from this job's own result.json (written
    server-side, never user-supplied), but a defense-in-depth check still
    confirms the resolved path is actually under JOBS_DIR before serving
    it, in case an artifact path was ever malformed."""
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
    if JOBS_DIR.resolve() not in path.parents:
        raise HTTPException(status_code=403, detail="Artifact path escapes the jobs directory")
    return FileResponse(path)
