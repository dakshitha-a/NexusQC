"""Job status/detail/cancel. Deliberately reads status/spec/result via the
lock-free disk functions in app/chemistry/jobs/base.py, never through
graph.read_state()/_graph_lock -- see job_watcher.py's module docstring for
why job data must never share that lock with in-flight chat turns."""
from __future__ import annotations

import re
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from app.agent import threads as thread_registry
from app.chemistry.jobs import molden as molden_tools
from app.chemistry.jobs import orca_runner
from app.chemistry.jobs.base import (
    JobResult,
    delete_job_dir,
    get_job_manager,
    read_meta,
    read_spec,
    spec_created_at,
    write_meta,
    write_result,
)
from app.chemistry.jobs.naming import auto_job_name
from app.config import JOBS_DIR
from server.schemas import RenameJobIn

router = APIRouter()

_NON_TERMINAL_STATUSES = {"pending", "running"}


def _job_row(job_id: str) -> dict:
    mgr = get_job_manager()
    status = mgr.status(job_id)
    result = mgr.result(job_id)
    spec = read_spec(job_id) or {}
    meta = read_meta(job_id)
    label = meta.get("label") or (auto_job_name(spec) if spec else "")
    return {
        "job_id": job_id,
        "status": status["status"],
        "message": status.get("message", ""),
        "updated_at": status.get("updated_at"),
        "created_at": spec_created_at(job_id, spec),
        "method": spec.get("method"),
        "engine": spec.get("engine"),
        "label": label,
        # Only meaningful on the single-job GET (_job_list_row strips it
        # like summary/artifacts) -- needed by ModeAnimationViewer to
        # build a base geometry for a frequency job's vibration animation,
        # since job.params never carries the molecule (that's a separate
        # top-level field on JobSpec).
        "molecule": spec.get("molecule"),
        "params": {k: v for k, v in spec.get("params", {}).items() if not k.startswith("_")},
        "retried_from": spec.get("params", {}).get("_retried_from"),
        "retry_count": spec.get("params", {}).get("_retry_count", 0),
        "summary": (result or {}).get("summary"),
        "artifacts": (result or {}).get("artifacts"),
        "error": (result or {}).get("error"),
    }


def _job_list_row(job_id: str) -> dict:
    """A trimmed version of _job_row for the two list endpoints below,
    which only ever render status/label/engine/timestamps -- dropping
    summary/artifacts/full params keeps a large (up to 100GB-worth of
    jobs) job store cheap to list and poll. GET /api/jobs/{id} (single-job
    detail, used by JobDetailDrawer) is unaffected and still returns
    everything via _job_row."""
    row = _job_row(job_id)
    row.pop("summary", None)
    row.pop("artifacts", None)
    row.pop("molecule", None)
    return row


def _iter_all_job_ids():
    # job_watcher.py's _SEEN_DIR ("_seen") lives inside JOBS_DIR but is its
    # own dedup bookkeeping, not a job -- must never show up in a job list.
    for d in JOBS_DIR.iterdir():
        if d.is_dir() and d.name != "_seen" and (d / "spec.json").exists():
            yield d.name


@router.get("/api/jobs")
def list_all_jobs():
    """Global, cross-thread job list for the persistent Job Manager panel
    -- distinct from GET /api/threads/{id}/jobs below, which stays scoped
    to one conversation's active_job_ids for the chat sidebar. Scans
    JOBS_DIR directly so a job from a since-deleted conversation still
    shows up here. Sorted newest-first by created_at."""
    rows = [_job_list_row(job_id) for job_id in _iter_all_job_ids()]
    rows.sort(key=lambda r: r["created_at"], reverse=True)
    return rows


@router.get("/api/threads/{thread_id}/jobs")
def list_jobs(thread_id: str):
    entry = thread_registry.get_thread(thread_id)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"No such conversation: {thread_id}")
    job_ids = entry.get("active_job_ids", [])
    return [_job_list_row(job_id) for job_id in reversed(job_ids)]


@router.get("/api/jobs/{job_id}")
def get_job(job_id: str):
    spec = read_spec(job_id)
    if spec is None:
        raise HTTPException(status_code=404, detail=f"No such job: {job_id}")
    return _job_row(job_id)


@router.patch("/api/jobs/{job_id}")
def rename_job(job_id: str, body: RenameJobIn):
    if read_spec(job_id) is None:
        raise HTTPException(status_code=404, detail=f"No such job: {job_id}")
    write_meta(job_id, {"label": body.label})
    return _job_row(job_id)


@router.delete("/api/jobs/{job_id}")
def remove_job(job_id: str):
    if read_spec(job_id) is None:
        raise HTTPException(status_code=404, detail=f"No such job: {job_id}")
    status = get_job_manager().status(job_id)
    if status["status"] in _NON_TERMINAL_STATUSES:
        raise HTTPException(status_code=409, detail="Cancel the job before deleting it.")
    delete_job_dir(job_id)
    return {"deleted": True}


@router.post("/api/jobs/{job_id}/cancel")
def cancel_job(job_id: str):
    if read_spec(job_id) is None:
        raise HTTPException(status_code=404, detail=f"No such job: {job_id}")
    cancelled = get_job_manager().cancel(job_id)
    return {"cancelled": cancelled, **_job_row(job_id)}


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
def get_job_log(job_id: str, lines: int = 20):
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


@router.post("/api/jobs/{job_id}/orbitals/{index}/cube")
def get_orbital_cube(job_id: str, index: int, spin: str | None = None):
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
    why it distorts orbital shapes."""
    spec = read_spec(job_id)
    if spec is None:
        raise HTTPException(status_code=404, detail=f"No such job: {job_id}")
    result = get_job_manager().result(job_id)
    if result is None:
        raise HTTPException(status_code=404, detail=f"No result for job: {job_id}")

    cube_key = f"idx{index}" + (f"_{spin}" if spin else "")
    artifacts = dict(result.get("artifacts") or {})
    cubes = dict(artifacts.get("cubes") or {})
    cached = cubes.get(cube_key)
    if cached and Path(cached).exists():
        return FileResponse(cached)

    job_dir = JOBS_DIR / job_id
    cube_path = job_dir / f"mo_{cube_key}.cube"
    engine = spec.get("engine")
    if engine == "orca":
        gbw = job_dir / "input.gbw"
        if not gbw.exists():
            raise HTTPException(
                status_code=404, detail="input.gbw not retained for this job -- cannot render orbitals lazily"
            )
        try:
            raw_cube = orca_runner.render_orbital_cube(str(job_dir), index - 1)
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

    cubes[cube_key] = str(cube_path)
    artifacts["cubes"] = cubes
    write_result(JobResult(
        job_id, result["status"], summary=result.get("summary", {}), artifacts=artifacts, error=result.get("error"),
    ))
    return FileResponse(cube_path)


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
