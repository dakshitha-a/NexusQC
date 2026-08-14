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

from app.config import (
    CORE_IDLE_THRESHOLD_PERCENT, JOBS_DIR, MAX_CONCURRENT_JOBS, MAX_CPU_PERCENT, MAX_MEM_PERCENT, N_CORES,
)

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
    # Written once at submission as part of spec.json's normal write-once
    # lifecycle (unlike the user-settable display label, which lives in the
    # separate mutable meta.json below). Used for the Job Manager's
    # descending sort and for quota.py's oldest-first eviction order.
    created_at: float = field(default_factory=time.time)

    def job_dir(self) -> Path:
        d = JOBS_DIR / self.job_id
        d.mkdir(parents=True, exist_ok=True)
        return d

    def to_dict(self) -> dict:
        return {
            "job_id": self.job_id, "method": self.method, "engine": self.engine,
            "molecule": self.molecule, "params": self.params, "label": self.label,
            "created_at": self.created_at,
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


def spec_created_at(job_id: str, spec: dict) -> float:
    """spec['created_at'] for any job submitted after this field was added
    to JobSpec; jobs submitted before that have no such key in their
    already-written spec.json, so this falls back to the file's own mtime
    -- still a reasonable "when was this submitted" proxy, and keeps
    sort/eviction order sane instead of every pre-existing job tying at 0
    (which would sort them all to one end and evict them all first)."""
    created_at = spec.get("created_at")
    if created_at is not None:
        return created_at
    try:
        return _spec_path(job_id).stat().st_mtime
    except OSError:
        return 0.0


def _meta_path(job_id: str) -> Path:
    return JOBS_DIR / job_id / "meta.json"


_DEFAULT_META = {"label": None, "dir_size_bytes": None}


def read_meta(job_id: str) -> dict:
    """The only *mutable* per-job file -- kept separate from spec.json
    (write-once) deliberately, since spec.json is read lock-free elsewhere
    (see read_spec's docstring) and a non-atomic rewrite of it could race
    those readers. Returns the defaults (never raises) on a missing or
    corrupt meta.json, same fail-open convention as read_spec/read_status."""
    p = _meta_path(job_id)
    if not p.exists():
        return dict(_DEFAULT_META)
    try:
        data = json.loads(p.read_text())
    except json.JSONDecodeError:
        return dict(_DEFAULT_META)
    return {**_DEFAULT_META, **data}


def write_meta(job_id: str, updates: dict) -> None:
    """Merges `updates` into the existing meta.json (e.g. a rename only
    touches 'label', quota.py's size caching only touches
    'dir_size_bytes') and writes it back atomically."""
    current = read_meta(job_id)
    current.update(updates)
    _atomic_write_text(_meta_path(job_id), json.dumps(current))


def delete_job_dir(job_id: str) -> None:
    """Removes a job's entire directory from disk and prunes it from every
    conversation's active_job_ids. Shared by the DELETE /api/jobs/{id}
    endpoint and quota.py's eviction sweep -- without the active_job_ids
    prune, job_watcher.py's poll loop would error every tick trying to
    stat a directory that no longer exists, and a stale drawer/
    check_job_status call would 404 mid-conversation. Callers are
    responsible for confirming the job is terminal (not pending/running)
    before calling this -- it does not check itself."""
    import shutil

    from app.agent import threads as thread_registry

    job_dir = JOBS_DIR / job_id
    if job_dir.exists():
        shutil.rmtree(job_dir, ignore_errors=True)
    for entry in thread_registry.list_threads():
        active = entry.get("active_job_ids", [])
        if job_id in active:
            thread_registry.set_active_job_ids(entry["thread_id"], [j for j in active if j != job_id])


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


def _host_cpu_snapshot() -> tuple[float, int]:
    """Genuinely host-wide CPU reading -- every logical CPU the host
    reports (255 in this deployment), not just this app's own job
    subprocess trees -- because this machine is shared with other
    tenants/processes outside this app's control (confirmed, not
    assumed) and a per-app-only measurement is blind to their load.
    `os.sched_getaffinity(0)` returns all 255 host core IDs here (no
    cpuset pinning restricts this container to specific physical cores,
    only a CFS-quota-style throttle `nproc` correctly detects as
    N_CORES), so this app's threads -- and everyone else's -- can land
    on any of them; checking across all of them is the right scope.

    Returns (aggregate_percent, n_idle_cores). aggregate_percent is a
    plain average across every core -- with 255 cores here, reaching a
    high aggregate takes 200+ cores near-saturated at once, a rare
    whole-host event, so it's a coarse backstop, not the main signal.
    n_idle_cores counts individual cores under CORE_IDLE_THRESHOLD_PERCENT
    busy -- the practically useful number, since it directly answers "can
    an N_CORES-wide job actually find that much real parallelism right
    now," which a single aggregate percentage can mask either way (a low
    aggregate diluted across many idle cores says nothing about whether
    the specific handful this job needs are free; a merely moderate
    aggregate could still hide N_CORES idle cores among other busy ones).

    psutil.cpu_percent(interval=1.0, ...) with a positive interval is a
    self-contained blocking sample -- reads /proc/stat, sleeps, reads
    again, diffs locally -- unlike the interval=None non-blocking form,
    which needs a prior same-object baseline to diff against (that
    priming requirement is exactly what made the old app-scoped
    _cpu_percent_used need a per-pid psutil.Process cache; this form
    needs none, and is safe to call from multiple threads concurrently
    since it touches no shared module-level cache in blocking mode). The
    1s block also serves as this function's caller's own poll pacing."""
    percpu = psutil.cpu_percent(interval=1.0, percpu=True)
    aggregate = sum(percpu) / len(percpu)
    n_idle = sum(1 for v in percpu if v < CORE_IDLE_THRESHOLD_PERCENT)
    return aggregate, n_idle


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

    def submit(self, spec: JobSpec) -> str:
        job_dir = spec.job_dir()
        (job_dir / "spec.json").write_text(json.dumps(spec.to_dict(), indent=2))
        write_status(spec.job_id, "pending", "queued")

        future = self._executor.submit(self._run, spec)
        with self._lock:
            self._futures[spec.job_id] = future
            # Deferred import: quota.py imports several names from this
            # module at its own top level, so importing it eagerly at
            # base.py's module scope would be a circular import. By the
            # time submit() actually runs, this module has long finished
            # loading, so the deferred import resolves cleanly. Folded into
            # submit() (under the same lock as _futures) rather than a
            # separate background thread, since disk usage here only grows
            # at submission time -- see quota.py's module docstring.
            from app.chemistry.jobs.quota import enforce_quota
            enforce_quota()
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

    def _wait_for_resources(self, job_id: str) -> bool:
        """Blocks the calling worker thread until the HOST (not just this
        app's own jobs -- this machine is genuinely shared with other
        tenants/processes outside this app's control) has CPU/memory
        headroom AND at least N_CORES individual logical cores are
        actually idle right now. MAX_CONCURRENT_JOBS alone is a job-COUNT
        cap, not a resource cap, and a single CASSCF/ORCA job can already
        saturate every core in N_CORES -- and even a low-looking aggregate
        percentage doesn't guarantee N_CORES worth of real, contiguous
        idle capacity exists on a 255-logical-CPU host another tenant may
        also be using. See _host_cpu_snapshot's docstring for why both an
        aggregate-percent check and a per-core idle count are kept, not
        just one. Returns False if the job was cancelled while waiting
        (caller must not spawn its subprocess in that case), True once
        it's clear to proceed.

        The _host_cpu_snapshot() call below blocks for ~1s and must stay
        outside self._lock -- it's the loop's own pacing (no separate
        time.sleep needed), and up to MAX_CONCURRENT_JOBS worker threads
        can be calling this method concurrently; holding the lock across
        that blocking call would serialize their otherwise-independent
        resource waits into up to a MAX_CONCURRENT_JOBS-times-longer
        effective poll interval."""
        while True:
            with self._lock:
                if job_id in self._cancelled:
                    return False
            cpu, n_idle = _host_cpu_snapshot()
            mem = _mem_percent_used()
            if cpu < MAX_CPU_PERCENT and mem < MAX_MEM_PERCENT and n_idle >= N_CORES:
                return True
            write_status(
                job_id, "pending",
                f"waiting for CPU/memory headroom (cpu {cpu:.0f}%, mem {mem:.0f}%, {n_idle}/{N_CORES} cores idle)",
            )

    def _run(self, spec: JobSpec) -> None:
        try:
            self._run_inner(spec)
        finally:
            # Runs after every exit path of _run_inner (completed, failed,
            # or cancelled -- including mid-run cancellation, which can
            # leave partial scratch behind just as much as a finished run).
            # Deferred import for the same circular-import reason submit()
            # defers quota.py's import (see its comment above).
            from app.chemistry.jobs.scratch import cleanup_scratch_files
            cleanup_scratch_files(spec.job_id, spec.engine)

    def _run_inner(self, spec: JobSpec) -> None:
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
