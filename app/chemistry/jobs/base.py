"""Job data model and background execution manager.

Every calculation — regardless of which engine (PySCF/ORCA/BAGEL) actually
runs it — is represented as a `JobSpec` on the way in and a `JobResult` on
the way out. Jobs execute in a subprocess (not just a thread) so that a
crash or runaway calculation in PySCF/ORCA/BAGEL can never take down the
Streamlit process itself. State is persisted to disk (status.json /
result.json) so the UI can poll it across Streamlit reruns.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from app.config import JOBS_DIR, MAX_CONCURRENT_JOBS

VALID_STATUSES = {"pending", "running", "completed", "failed"}

# Hard cap on automatic (agent-driven, no user request) failed-job retries
# per troubleshooting chain -- see count_failed_in_chain below and
# app/main.py's _jobs_fragment, which is the actual enforcement point.
MAX_AUTO_RETRIES = 3


@dataclass
class JobSpec:
    method: str  # single_point | geometry_optimization | frequency | casscf | caspt2 | tddft | mo_visualization | pes_scan
    engine: str  # pyscf | orca | bagel
    molecule: dict
    params: dict = field(default_factory=dict)
    job_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    label: str = ""

    def job_dir(self) -> Path:
        d = JOBS_DIR / self.job_id
        d.mkdir(parents=True, exist_ok=True)
        return d

    def to_dict(self) -> dict:
        return {
            "job_id": self.job_id, "method": self.method, "engine": self.engine,
            "molecule": self.molecule, "params": self.params, "label": self.label,
        }


@dataclass
class JobResult:
    job_id: str
    status: str
    summary: dict = field(default_factory=dict)  # key numeric/text results, engine-agnostic
    artifacts: dict = field(default_factory=dict)  # named file paths (cube files, xyz, raw output, etc.)
    error: Optional[str] = None

    def to_dict(self) -> dict:
        return {"job_id": self.job_id, "status": self.status, "summary": self.summary,
                "artifacts": self.artifacts, "error": self.error}


def _status_path(job_id: str) -> Path:
    return JOBS_DIR / job_id / "status.json"


def _result_path(job_id: str) -> Path:
    return JOBS_DIR / job_id / "result.json"


def _spec_path(job_id: str) -> Path:
    return JOBS_DIR / job_id / "spec.json"


def _atomic_write_text(path: Path, text: str) -> None:
    """Write via a temp file + rename so concurrent readers never observe a
    truncated/partial file (plain write_text truncates-then-writes, which
    races with pollers reading status.json from another process/thread)."""
    tmp = path.with_suffix(path.suffix + f".tmp{os.getpid()}")
    tmp.write_text(text)
    os.replace(tmp, path)


def write_status(job_id: str, status: str, message: str = "") -> None:
    assert status in VALID_STATUSES
    _atomic_write_text(_status_path(job_id), json.dumps({
        "status": status, "message": message, "updated_at": time.time(),
    }))


def read_status(job_id: str) -> dict:
    p = _status_path(job_id)
    if not p.exists():
        return {"status": "pending", "message": "", "updated_at": None}
    try:
        return json.loads(p.read_text())
    except json.JSONDecodeError:
        return {"status": "pending", "message": "", "updated_at": None}


def read_result(job_id: str) -> Optional[dict]:
    p = _result_path(job_id)
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text())
    except json.JSONDecodeError:
        return None


def write_result(result: JobResult) -> None:
    _atomic_write_text(_result_path(result.job_id), json.dumps(result.to_dict(), indent=2))


def read_spec(job_id: str) -> Optional[dict]:
    """Returns None (never raises) on a missing or corrupt spec.json --
    this is read from submit_job's pre-interrupt() code path (see its
    retry_of_job_id handling in tools.py), which re-executes in full on
    every resume; an exception there propagates straight out of
    resume_turn and kills the approval click outright rather than being
    caught into a ToolMessage (confirmed empirically, documented in
    CLAUDE.md). A vanished spec.json (e.g. its job dir was cleaned up
    between the approval card rendering and the click) must degrade
    gracefully, not crash the resume.
    """
    p = _spec_path(job_id)
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text())
    except json.JSONDecodeError:
        return None


def count_failed_in_chain(job_id: str) -> int:
    """Walks a retry chain backward via params['_retried_from'], counting
    how many jobs in it (including job_id itself) currently have
    status == 'failed'. This is the actual enforcement mechanism for the
    auto-retry budget (see MAX_AUTO_RETRIES) -- submit_job's own
    retry_of_job_id/'_retry_count' bookkeeping (see tools.py) is
    provenance for the approval card's "retry N of M" display only, not a
    gate, since an LLM call that simply omits retry_of_job_id would reset
    an LLM-tracked counter to zero. app/main.py's _jobs_fragment calls
    this directly instead, since that code is never at the LLM's
    discretion.
    """
    count = 0
    seen: set[str] = set()
    current: Optional[str] = job_id
    while current and current not in seen:
        seen.add(current)
        result = read_result(current)
        if result and result.get("status") == "failed":
            count += 1
        spec = read_spec(current)
        current = (spec or {}).get("params", {}).get("_retried_from")
    return count


# Entry-point script invoked as a subprocess for each engine.
_WORKER_MODULE = {
    "pyscf": "app.chemistry.jobs.pyscf_worker",
    "orca": "app.chemistry.jobs.orca_worker",
    "bagel": "app.chemistry.jobs.bagel_worker",
}


class JobManager:
    """Singleton-ish manager: submits jobs to a bounded thread pool, each
    thread blocking on a subprocess that does the real work."""

    def __init__(self, max_concurrent: int = MAX_CONCURRENT_JOBS):
        self._executor = ThreadPoolExecutor(max_workers=max_concurrent)
        self._lock = threading.Lock()
        self._futures: dict[str, Any] = {}

    def submit(self, spec: JobSpec) -> str:
        job_dir = spec.job_dir()
        (job_dir / "spec.json").write_text(json.dumps(spec.to_dict(), indent=2))
        write_status(spec.job_id, "pending", "queued")

        future = self._executor.submit(self._run, spec)
        with self._lock:
            self._futures[spec.job_id] = future
        return spec.job_id

    def _run(self, spec: JobSpec) -> None:
        write_status(spec.job_id, "running", f"running {spec.method} via {spec.engine}")
        module = _WORKER_MODULE.get(spec.engine)
        if module is None:
            write_status(spec.job_id, "failed", f"unknown engine '{spec.engine}'")
            write_result(JobResult(spec.job_id, "failed", error=f"unknown engine '{spec.engine}'"))
            return

        job_dir = spec.job_dir()
        log_path = job_dir / "worker.log"
        try:
            with open(log_path, "w") as log_f:
                proc = subprocess.run(
                    [sys.executable, "-m", module, str(job_dir / "spec.json")],
                    stdout=log_f, stderr=subprocess.STDOUT,
                    cwd=str(Path(__file__).resolve().parents[3]),
                    timeout=6 * 3600,
                )
            if proc.returncode != 0 and read_result(spec.job_id) is None:
                # A non-zero exit with no result.json means the worker crashed
                # before its own try/except could run (e.g. an import error) --
                # synthesize a failure from the log. If result.json DOES exist,
                # the worker already caught its exception and wrote a detailed
                # error there (its normal failure path); fall through and use
                # that instead of clobbering it with an empty worker.log tail.
                tail = log_path.read_text()[-4000:]
                write_status(spec.job_id, "failed", f"worker exited with code {proc.returncode}")
                write_result(JobResult(spec.job_id, "failed", error=tail or "worker produced no output"))
                return
        except subprocess.TimeoutExpired:
            write_status(spec.job_id, "failed", "timed out")
            write_result(JobResult(spec.job_id, "failed", error="job exceeded 6h timeout"))
            return
        except Exception as e:
            write_status(spec.job_id, "failed", str(e))
            write_result(JobResult(spec.job_id, "failed", error=str(e)))
            return

        result = read_result(spec.job_id)
        if result is None:
            write_status(spec.job_id, "failed", "worker produced no result.json")
            write_result(JobResult(spec.job_id, "failed", error="worker produced no result.json; see worker.log"))
            return
        write_status(spec.job_id, result["status"], "done")

    def status(self, job_id: str) -> dict:
        return read_status(job_id)

    def result(self, job_id: str) -> Optional[dict]:
        return read_result(job_id)


_manager: Optional[JobManager] = None


def get_job_manager() -> JobManager:
    global _manager
    if _manager is None:
        _manager = JobManager()
    return _manager
