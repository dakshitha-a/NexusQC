"""Job status/detail/cancel. Deliberately reads status/spec/result via the
lock-free disk functions in app/chemistry/jobs/base.py, never through
graph.read_state()/_graph_lock -- see job_watcher.py's module docstring for
why job data must never share that lock with in-flight chat turns."""
from __future__ import annotations

import io
import re
import tempfile
import zipfile
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse, Response

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
    sub_job_ids_of,
    write_meta,
    write_result,
)
from app.chemistry.jobs.naming import auto_job_name
from app.chemistry.jobs.quota import QUOTA_BYTES as JOB_QUOTA_BYTES
from app.chemistry.jobs.quota import current_usage_bytes as job_storage_usage_bytes
from app.chemistry.spectrum import render_line_plot, render_uvvis_plot
from app.config import JOBS_DIR
from server.schemas import RenameJobIn, RenderPlotIn

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
        "is_scan_master": spec.get("method") == "pes_scan",
        "parent_job_id": spec.get("parent_job_id"),
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
    # A pes_scan sub-job (spec.parent_job_id set) is also excluded here --
    # it's only ever visible nested under its master's own detail view
    # (see get_scan_children below), never as its own top-level row.
    for d in JOBS_DIR.iterdir():
        if d.is_dir() and d.name != "_seen" and (d / "spec.json").exists():
            spec = read_spec(d.name)
            if spec is not None and spec.get("parent_job_id"):
                continue
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


@router.get("/api/jobs/quota")
def get_jobs_quota():
    """Job-artifact storage usage against app/chemistry/jobs/quota.py's
    100GB cap, for the Job Manager panel's usage display."""
    return {"used_bytes": job_storage_usage_bytes(), "quota_bytes": JOB_QUOTA_BYTES}


@router.get("/api/jobs/{job_id}/children")
def get_scan_children(job_id: str):
    """A pes_scan master's per-image sub-jobs, in path order -- the
    nested list JobDetailDrawer.tsx shows when a scan master is opened.
    Full _job_row shape per child (not the trimmed list row) since the
    drawer needs each child's own summary/molecule to support opening a
    nested JobDetailDrawer for it directly."""
    spec = read_spec(job_id)
    if spec is None:
        raise HTTPException(status_code=404, detail=f"No such job: {job_id}")
    if spec.get("method") != "pes_scan":
        raise HTTPException(status_code=400, detail=f"Job {job_id} is not a pes_scan master")
    return [_job_row(sub_id) for sub_id in sub_job_ids_of(job_id)]


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
def download_job(job_id: str):
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

    if spec.get("engine") == "pyscf":
        result = get_job_manager().result(job_id)
        text = _pyscf_text_summary(job_id, spec, result)
        return Response(
            content=text, media_type="text/plain",
            headers={"Content-Disposition": f'attachment; filename="{job_id}_summary.txt"'},
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
        headers={"Content-Disposition": f'attachment; filename="{job_id}.zip"'},
    )


_ENGINE_INPUT_FILES = {"orca": "input.inp", "bagel": "input.json"}


@router.get("/api/jobs/{job_id}/raw_input")
def get_job_raw_input(job_id: str):
    """The literal input file ORCA/BAGEL's binary actually parsed --
    input.inp/input.json, written unconditionally before the engine runs
    (see orca_runner._write_and_run/bagel_runner._run_bagel), so this
    works for a running, failed, or completed job alike, and is
    byte-identical to a hand-edited approval-card submission (see
    submit_job's _raw_input handling in tools.py). scratch.py's cleanup
    always keeps this file (see _ORCA_KEEP_NAMES / _bagel_scratch_files),
    so it stays available for the life of the job directory. PySCF has no
    such file (see CLAUDE.md/_pyscf_text_summary above) -- 404 there."""
    spec = read_spec(job_id)
    if spec is None:
        raise HTTPException(status_code=404, detail=f"No such job: {job_id}")
    filename = _ENGINE_INPUT_FILES.get(spec.get("engine"))
    if filename is None:
        raise HTTPException(status_code=404, detail="This engine has no literal input file")
    path = JOBS_DIR / job_id / filename
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Input file not found on disk")
    return Response(content=path.read_text(), media_type="text/plain")


@router.post("/api/jobs/{job_id}/render_plot")
def render_plot(job_id: str, body: RenderPlotIn):
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
    result = get_job_manager().result(job_id)
    if result is None:
        raise HTTPException(status_code=404, detail=f"No result for job: {job_id}")
    summary = result.get("summary") or {}

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
            render_uvvis_plot(energies_eV, strengths, 0.4, out_path)
        else:
            raise HTTPException(status_code=400, detail=f"Unknown plot kind '{body.kind}'")
        png_bytes = Path(out_path).read_bytes()

    return Response(
        content=png_bytes, media_type="image/png",
        headers={"Content-Disposition": f'attachment; filename="{job_id}_{body.kind}.png"'},
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
