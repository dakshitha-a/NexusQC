"""Job data model and background execution manager.

Every calculation — regardless of which engine (PySCF/ORCA/BAGEL) actually
runs it — is represented as a `JobSpec` on the way in and a `JobResult` on
the way out. Jobs execute in a subprocess (not just a thread) so that a
crash or runaway calculation in PySCF/ORCA/BAGEL can never take down the
FastAPI server process itself. State is persisted to disk (status.json /
result.json) so the frontend can poll it across page reloads.
"""
from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

import psutil

from app.config import JOBS_DIR, MAX_CONCURRENT_JOBS, MAX_CPU_PERCENT, MAX_MEM_PERCENT, N_CORES

VALID_STATUSES = {"pending", "running", "completed", "failed", "cancelled"}

# Hard cap on automatic (agent-driven, no user request) failed-job retries
# per troubleshooting chain -- see count_failed_in_chain below and
# app/agent/job_watcher.py, which is the actual enforcement point.
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
    an LLM-tracked counter to zero. app/agent/job_watcher.py calls this
    directly instead, since that code is never at the LLM's discretion.
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


def _mem_percent_used() -> float:
    """Host-wide memory percent. This environment exposes no accessible
    cgroup memory limit (no memory.max/memory.current under
    /sys/fs/cgroup, confirmed empirically) -- host-wide
    psutil.virtual_memory() is the best available signal for what's
    actually free. Revisit if a memory cgroup limit is ever added here."""
    return psutil.virtual_memory().percent


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
        self._procs: dict[str, subprocess.Popen] = {}  # job_id -> live worker process
        self._cancelled: set[str] = set()  # cancel() requested, not yet reaped by _run
        self._cpu_trackers: dict[int, psutil.Process] = {}  # pid -> cached Process, for cpu_percent() deltas

    def submit(self, spec: JobSpec) -> str:
        job_dir = spec.job_dir()
        (job_dir / "spec.json").write_text(json.dumps(spec.to_dict(), indent=2))
        write_status(spec.job_id, "pending", "queued")

        future = self._executor.submit(self._run, spec)
        with self._lock:
            self._futures[spec.job_id] = future
        return spec.job_id

    def cancel(self, job_id: str) -> bool:
        """Requests cancellation of a pending or running job. Returns True
        if a cancellation was applied, False if the job was already
        terminal (nothing to cancel). Kills the worker's whole process
        group, not just its direct child -- ORCA/BAGEL launch MPI ranks as
        child processes of the worker, which `start_new_session=True` in
        _run puts in the same group, so killing only the worker pid would
        orphan the actual running computation (still burning CPU/writing
        output) while the UI reports "cancelled"."""
        with self._lock:
            proc = self._procs.get(job_id)
            pending = proc is None and read_status(job_id)["status"] == "pending"
            if proc is None and not pending:
                return False
            self._cancelled.add(job_id)
        if proc is None:
            # Not started yet -- still queued behind MAX_CONCURRENT_JOBS
            # other jobs, or about to begin its own resource-headroom wait.
            # Write the cancelled status immediately rather than waiting for
            # _run() to even be dispatched (which could be delayed
            # arbitrarily long by a saturated thread pool); _run()'s own
            # pre-spawn/pre-resource-wait checks re-write the same status
            # idempotently once they do run, so this is safe even if _run()
            # is concurrently mid-flight and hasn't reached those checks yet
            # (worst case is a harmless "cancelled" -> briefly "running" ->
            # "cancelled again once the just-spawned process is killed"
            # flicker in the sub-millisecond window between this write and
            # _run()'s next cancellation check).
            write_status(job_id, "cancelled", "cancelled before it started")
            write_result(JobResult(job_id, "cancelled", error="Cancelled by user before it started."))
            return True
        try:
            os.killpg(proc.pid, signal.SIGTERM)
        except ProcessLookupError:
            return True
        try:
            # Popen internally serializes concurrent wait()/poll() calls
            # from multiple threads (its own _waitpid_lock), so it's safe
            # for this call and _run's long-running proc.wait() to observe
            # the same process concurrently -- only one performs the actual
            # waitpid, both see the same exit once the process dies.
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        return True

    def _cpu_percent_used(self) -> float:
        """Percentage of this app's own CPU quota (N_CORES, itself derived
        via `nproc` in config.py -- see its docstring) that this app's own
        running job subprocess trees are currently using, including any
        MPI child ranks ORCA/BAGEL spawn. Host-wide psutil.cpu_percent()
        is deliberately NOT used here: confirmed empirically to read
        near-zero in this environment even under full load on the 8 real
        cores, since it's a system-wide average diluted across the
        host's 255 cores (os.cpu_count()/psutil.cpu_count() both
        misreport this container's real core count the same way N_CORES
        already had to work around).

        psutil.Process.cpu_percent(interval=None) only returns a
        meaningful (non-zero) delta on the *second and later* calls made
        on the *same* Process object -- it diffs against that object's
        own previous sample. A fresh `psutil.Process(pid)` constructed on
        every call (the first version of this method) has no previous
        sample and silently always returns 0.0 -- confirmed empirically
        (Part D of verify_job_cancel.py failed to ever throttle admission
        until this was fixed). self._cpu_trackers caches one Process
        object per pid across calls so real deltas accumulate."""
        with self._lock:
            pids: set[int] = set()
            for p in self._procs.values():
                try:
                    proc = psutil.Process(p.pid)
                    pids.add(proc.pid)
                    pids.update(c.pid for c in proc.children(recursive=True))
                except psutil.NoSuchProcess:
                    continue
            for stale_pid in [pid for pid in self._cpu_trackers if pid not in pids]:
                del self._cpu_trackers[stale_pid]
            total = 0.0
            for pid in pids:
                tracker = self._cpu_trackers.get(pid)
                if tracker is None:
                    try:
                        tracker = psutil.Process(pid)
                        tracker.cpu_percent(interval=None)  # prime; first-ever sample, not a real delta
                    except psutil.NoSuchProcess:
                        continue
                    self._cpu_trackers[pid] = tracker
                    continue
                try:
                    total += tracker.cpu_percent(interval=None)
                except psutil.NoSuchProcess:
                    del self._cpu_trackers[pid]
            return (total / N_CORES) if N_CORES else 0.0

    def _wait_for_resources(self, job_id: str) -> bool:
        """Blocks the calling worker thread until this app's own jobs are
        using less than MAX_CPU_PERCENT of its CPU quota and the host is
        under MAX_MEM_PERCENT memory -- MAX_CONCURRENT_JOBS alone is a
        job-COUNT cap, not a resource cap, and a single CASSCF/ORCA job
        can already saturate every core in N_CORES. Returns False if the
        job was cancelled while waiting (caller must not spawn its
        subprocess in that case), True once it's clear to proceed.
        Primes CPU sampling with a throwaway call first, since a
        newly-seen process reads 0 on the first sample (see
        _cpu_percent_used's docstring)."""
        self._cpu_percent_used()
        while True:
            with self._lock:
                if job_id in self._cancelled:
                    return False
            time.sleep(1.0)
            cpu = self._cpu_percent_used()
            mem = _mem_percent_used()
            if cpu < MAX_CPU_PERCENT and mem < MAX_MEM_PERCENT:
                return True
            write_status(
                job_id, "pending",
                f"waiting for CPU/memory headroom (cpu {cpu:.0f}%, mem {mem:.0f}%)",
            )

    def _run(self, spec: JobSpec) -> None:
        with self._lock:
            if spec.job_id in self._cancelled:
                self._cancelled.discard(spec.job_id)
                write_status(spec.job_id, "cancelled", "cancelled before it started")
                write_result(JobResult(spec.job_id, "cancelled", error="Cancelled by user before it started."))
                return

        if not self._wait_for_resources(spec.job_id):
            with self._lock:
                self._cancelled.discard(spec.job_id)
            write_status(spec.job_id, "cancelled", "cancelled while waiting for resource headroom")
            write_result(JobResult(spec.job_id, "cancelled", error="Cancelled by user before it started."))
            return

        write_status(spec.job_id, "running", f"running {spec.method} via {spec.engine}")
        module = _WORKER_MODULE.get(spec.engine)
        if module is None:
            write_status(spec.job_id, "failed", f"unknown engine '{spec.engine}'")
            write_result(JobResult(spec.job_id, "failed", error=f"unknown engine '{spec.engine}'"))
            return

        job_dir = spec.job_dir()
        log_path = job_dir / "worker.log"
        was_cancelled = False
        try:
            with open(log_path, "w") as log_f:
                proc = subprocess.Popen(
                    [sys.executable, "-m", module, str(job_dir / "spec.json")],
                    stdout=log_f, stderr=subprocess.STDOUT,
                    cwd=str(Path(__file__).resolve().parents[3]),
                    start_new_session=True,  # own process group, so cancel()/timeout
                                              # can reach ORCA/BAGEL's MPI child ranks too
                )
                with self._lock:
                    self._procs[spec.job_id] = proc
                    already_cancelled = spec.job_id in self._cancelled
                if already_cancelled:
                    # cancel() ran between the pre-spawn check above and this
                    # Popen actually starting -- kill it now that a pid exists.
                    try:
                        os.killpg(proc.pid, signal.SIGTERM)
                    except ProcessLookupError:
                        pass
                returncode: Optional[int]
                try:
                    returncode = proc.wait(timeout=6 * 3600)
                except subprocess.TimeoutExpired:
                    try:
                        os.killpg(proc.pid, signal.SIGTERM)
                        proc.wait(timeout=10)
                    except (ProcessLookupError, subprocess.TimeoutExpired):
                        try:
                            os.killpg(proc.pid, signal.SIGKILL)
                        except ProcessLookupError:
                            pass
                    returncode = None
                finally:
                    with self._lock:
                        self._procs.pop(spec.job_id, None)
                        was_cancelled = spec.job_id in self._cancelled
                        self._cancelled.discard(spec.job_id)
        except Exception as e:
            with self._lock:
                self._procs.pop(spec.job_id, None)
                self._cancelled.discard(spec.job_id)
            write_status(spec.job_id, "failed", str(e))
            write_result(JobResult(spec.job_id, "failed", error=str(e)))
            return

        # A cancellation always wins over whatever the process's own exit
        # looked like (e.g. a SIGTERM'd process typically exits non-zero,
        # which would otherwise be reported as "failed" here).
        if was_cancelled:
            write_status(spec.job_id, "cancelled", "cancelled by user")
            write_result(JobResult(spec.job_id, "cancelled", error="Cancelled by user."))
            return

        if returncode is None:
            write_status(spec.job_id, "failed", "timed out")
            write_result(JobResult(spec.job_id, "failed", error="job exceeded 6h timeout"))
            return

        if returncode != 0 and read_result(spec.job_id) is None:
            # A non-zero exit with no result.json means the worker crashed
            # before its own try/except could run (e.g. an import error) --
            # synthesize a failure from the log. If result.json DOES exist,
            # the worker already caught its exception and wrote a detailed
            # error there (its normal failure path); fall through and use
            # that instead of clobbering it with an empty worker.log tail.
            tail = log_path.read_text()[-4000:]
            write_status(spec.job_id, "failed", f"worker exited with code {returncode}")
            write_result(JobResult(spec.job_id, "failed", error=tail or "worker produced no output"))
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
