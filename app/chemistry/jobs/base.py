"""Job data model and background execution manager.

Every calculation — regardless of which engine (PySCF/ORCA/BAGEL) actually
runs it — is represented as a `JobSpec` on the way in and a `JobResult` on
the way out. Jobs execute in a subprocess (not just a thread) so that a
crash or runaway calculation in PySCF/ORCA/BAGEL can never take down the
FastAPI server process itself. State is persisted to disk (status.json /
result.json) so the frontend can poll it across page reloads.
"""
from __future__ import annotations

import contextlib
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
from typing import Any, Iterator, Optional

import psutil

from app.config import (
    CORE_IDLE_THRESHOLD_PERCENT, JOBS_DIR, MAX_CONCURRENT_JOBS, MAX_CPU_PERCENT, MAX_MEM_PERCENT, N_CORES,
)

VALID_STATUSES = {"pending", "running", "completed", "failed", "cancelled"}

# pes_scan-only keys on a scan master's JobSpec.params that describe the
# scan itself (interpolation method, how many images, which coordinate),
# not the per-image calculation -- JobManager.submit_scan strips these out
# before using params as the template for every per-image sub-job's own
# params, so e.g. n_points doesn't leak into a single_point sub-job's spec.
SCAN_ONLY_PARAM_KEYS = {
    "scan_job_type", "interpolation_method", "n_points", "coordinate", "scan_range",
}

# wigner_ensemble-only keys on an ensemble master's JobSpec.params that
# describe the ensemble itself (which frequency job to sample from, how
# many samples, sampling parameters), not the per-sample excited-state
# calculation -- JobManager.submit_ensemble strips these out before using
# params as the template for every per-sample sub-job's own params, same
# role SCAN_ONLY_PARAM_KEYS plays for pes_scan.
ENSEMBLE_ONLY_PARAM_KEYS = {
    "source_frequency_job_id", "scan_job_type", "n_samples", "random_seed",
    "temperature_K", "low_freq_cutoff_cm1", "fwhm_eV",
}

# Job methods whose spec represents a "master" with no worker process of
# its own -- it fans out into independent sub-jobs (JobSpec.parent_job_id)
# that do the actual work, aggregated back by a dedicated background
# orchestrator (scan_orchestrator.py / ensemble_orchestrator.py). Every
# function below that needs to special-case "this is a master, cascade to
# its children" (delete_job_dir, cancel, _reconcile_orphaned_jobs,
# _running_job_ids) checks membership in this set rather than a literal
# method-name string, so a new master-shaped job_type only needs adding
# here, not at every call site.
MASTER_METHODS = {"pes_scan", "wigner_ensemble"}


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
    # Set only on a pes_scan image sub-job (see JobManager.submit_scan) --
    # the id of the "master" pes_scan job that spawned it. None for every
    # ordinary job, including every pes_scan master itself (a master's own
    # parent_job_id is always None; only its children set this).
    parent_job_id: Optional[str] = None

    def job_dir(self) -> Path:
        d = JOBS_DIR / self.job_id
        d.mkdir(parents=True, exist_ok=True)
        return d

    def to_dict(self) -> dict:
        return {
            "job_id": self.job_id, "method": self.method, "engine": self.engine,
            "molecule": self.molecule, "params": self.params, "label": self.label,
            "created_at": self.created_at, "parent_job_id": self.parent_job_id,
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


def read_status(job_id: str) -> Optional[dict]:
    """The job's current status, or None if there is no job by this id.

    F-024. This used to return a synthetic `{"status": "pending"}` for a
    job it had never heard of, which made two entirely different states
    indistinguishable to every internal caller: a job that was genuinely
    just queued (directory created, status.json not written yet) and a job
    that had been deleted, purged by a quota eviction, or never existed at
    all. Callers reasonably treat "pending" as "wait for it", so a
    reference to a purged job could be waited on indefinitely.

    The distinction is drawn at the job DIRECTORY, not at status.json: a
    directory with no status.json yet really is a queued job and still
    reports "pending", which is what it is. No directory means no job, and
    that is None -- matching `read_result`/`read_spec`, which have always
    returned None for a job that isn't there.
    """
    if not (JOBS_DIR / job_id).is_dir():
        return None
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


def format_job_error(exc: BaseException) -> str:
    """The error text a failed job stores in result.json.

    Every worker used to store a bare `traceback.format_exc()`, which puts
    the Python stack FIRST and the actually-useful diagnosis last. For an
    engine failure that diagnosis is the whole point -- a real ORCA run
    with a bad keyword produced 300 characters of `orca_worker.py`/
    `orca_runner.py` frames before "UNRECOGNIZED OR DUPLICATED KEYWORD(S)
    IN SIMPLE INPUT LINE: NOSUCHBASIS777". Anything that truncates (the
    job list, the drawer's error line, check_job_status' report to the
    agent) therefore showed the reader the least informative part.

    This matters most in exactly the workflow this app is built around:
    a user comes back to a job that failed an hour ago, and the first
    thing they see should be why.

    The message leads; the traceback follows under a marker, so nothing
    is lost for debugging.
    """
    import traceback as _tb
    message = str(exc).strip() or exc.__class__.__name__
    tb = _tb.format_exc()
    return f"{exc.__class__.__name__}: {message}\n\n--- traceback ---\n{tb}"


def read_spec(job_id: str) -> Optional[dict]:
    """Returns None (never raises) on a missing or corrupt spec.json --
    this is read from submit_job's pre-interrupt() code path, which
    re-executes in full on
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


# Guards the read-modify-write cycle in write_meta()/result_artifact_
# transaction() below -- _atomic_write_text alone only makes a single
# write torn-free for a *reader*; it does nothing to stop two concurrent
# *writers* from both reading the same starting state and one silently
# overwriting the other's update. Real, not hypothetical, races this
# closes: a rename_job PATCH landing in the same instant _run_inner()
# writes worker_pid/worker_pid_create_time for the same job (the latter is
# exactly the state _reconcile_orphaned_jobs depends on to recover a job
# across a server restart -- losing it silently would undermine that
# recovery path); and two tool calls in one LLM turn (e.g.
# plot_excited_state_spectrum + plot_ir_spectrum on the same job) each
# adding a different artifacts key to the same job's result.json. A single
# process-wide lock (not per-job_id) is intentionally coarse -- these are
# all small, infrequent operations, and per-job_id lock bookkeeping would
# add real complexity for no measurable benefit at this job volume.
_meta_write_lock = threading.Lock()
_result_write_lock = threading.Lock()


def write_meta(job_id: str, updates: dict) -> None:
    """Merges `updates` into the existing meta.json (e.g. a rename only
    touches 'label', quota.py's size caching only touches
    'dir_size_bytes') and writes it back atomically."""
    with _meta_write_lock:
        current = read_meta(job_id)
        current.update(updates)
        _atomic_write_text(_meta_path(job_id), json.dumps(current))


@contextlib.contextmanager
def result_artifact_transaction(job_id: str) -> Iterator[Optional[dict]]:
    """Read-modify-write result.json's `artifacts` dict as one atomic unit,
    serialized against every other caller of this same function. Yields the
    live `artifacts` dict to mutate in place (add/replace keys, including
    nested ones like artifacts['cubes'][...]); the updated result.json is
    written on a clean exit, with status/summary/error carried over
    unchanged. Yields None (nothing to write back) if the job has no
    result.json yet -- callers must check for that before mutating.

    Every caller that reads a job's current artifacts, adds one key, and
    writes the whole dict back (plot_excited_state_spectrum/plot_ir_spectrum/
    plot_job_comparison in app/agent/tools.py, and the lazy per-orbital cube
    endpoint in server/routes/jobs.py) must go through this rather than its
    own bare read/mutate/write_result -- otherwise two such calls racing on
    the same job_id (plausible: LangGraph's ToolNode can run multiple tool
    calls from one LLM turn concurrently) silently lose whichever wrote
    first's artifact key.

    Two deliberate scope limits, both fine given what actually calls this:
    (1) _result_write_lock only serializes callers of *this* function
    against each other -- it does NOT protect every write_result() call in
    the codebase. _run_inner's own terminal write, _reconcile_orphaned_jobs,
    cancel(), and scan_orchestrator.py's per-tick aggregation all still call
    write_result() directly, unlocked. That's fine in practice: those all
    write a *different* job_id than the one a plot/cube call targets (a
    scan master's own result.json vs. one of its sub-job's), or happen long
    before/after a job is in a state these artifact-adding callers would
    ever touch it. Widening this lock to cover those too would be the wrong
    fix even if it mattered -- it would serialize _run_inner's terminal
    status write and the orchestrator's own polling loop behind a single
    process-wide lock for no reason. (2) The caller's body (the code
    between `as artifacts` and the end of the `with` block) runs while
    _result_write_lock is held -- keep it to plain dict mutation, the same
    way every current caller does. Slow work (rendering a plot, running
    orca_plot/cube_for_orbital) must happen BEFORE entering the `with`
    block, not inside it, or it would serialize unrelated concurrent
    artifact writes behind whatever's slow."""
    with _result_write_lock:
        result = read_result(job_id)
        if result is None:
            yield None
            return
        artifacts = dict(result.get("artifacts") or {})
        yield artifacts
        write_result(JobResult(
            job_id=result["job_id"], status=result["status"],
            summary=result.get("summary", {}), artifacts=artifacts, error=result.get("error"),
        ))


def delete_job_dir(job_id: str) -> None:
    """Removes a job's entire directory from disk and prunes it from every
    conversation's active_job_ids. Shared by the DELETE /api/jobs/{id}
    endpoint and quota.py's eviction sweep -- without the active_job_ids
    prune, job_watcher.py's poll loop would error every tick trying to
    stat a directory that no longer exists, and a stale drawer/
    check_job_status call would 404 mid-conversation. Callers are
    responsible for confirming the job is terminal (not pending/running)
    before calling this -- it does not check itself.

    Deleting a master job (pes_scan/wigner_ensemble -- see MASTER_METHODS)
    also deletes every one of its sub-jobs -- otherwise their directories
    would become permanently unreachable disk usage, since a sub-job is
    deliberately excluded from every job list (only visible nested under
    its master; see server/routes/jobs.py)."""
    import shutil

    from app.agent import threads as thread_registry

    spec = read_spec(job_id)
    if spec is not None and spec.get("method") in MASTER_METHODS:
        for sub_id in sub_job_ids_of(job_id):
            delete_job_dir(sub_id)

    job_dir = JOBS_DIR / job_id
    if job_dir.exists():
        shutil.rmtree(job_dir, ignore_errors=True)
    for entry in thread_registry.list_threads():
        active = entry.get("active_job_ids", [])
        if job_id in active:
            thread_registry.set_active_job_ids(entry["thread_id"], [j for j in active if j != job_id])


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


def _iter_job_ids_on_disk():
    # Same _seen-skipping, spec.json-gated convention as quota.py's
    # _iter_job_ids -- duplicated locally rather than imported, since
    # quota.py itself imports names from this module at its own top level
    # (see submit()'s deferred-import comment) and importing back the
    # other way here would be circular.
    for d in JOBS_DIR.iterdir():
        if d.is_dir() and d.name != "_seen" and (d / "spec.json").exists():
            yield d.name


def sub_job_ids_of(master_id: str) -> list[str]:
    """Every job whose spec.json['parent_job_id'] == master_id (a pes_scan
    master's per-image sub-jobs, ordered by params['_scan_index'] -- see
    JobManager.submit_scan -- or a wigner_ensemble master's per-sample
    sub-jobs, ordered by params['_ensemble_index'] -- see
    JobManager.submit_ensemble). A plain linear scan of JOBS_DIR is fine
    here: job counts in this deployment are small (see CLAUDE.md), and
    this is only called for a master's own detail view/aggregation, not on
    every job-list poll."""
    found = []
    for job_id in _iter_job_ids_on_disk():
        spec = read_spec(job_id)
        if spec and spec.get("parent_job_id") == master_id:
            params = spec.get("params", {})
            found.append((params.get("_scan_index", params.get("_ensemble_index", 0)), job_id))
    found.sort(key=lambda t: t[0])
    return [job_id for _, job_id in found]


def _write_path_xyz(job_dir: Path, images: list[dict], filename: str = "path.xyz") -> str:
    """Multi-frame XYZ trajectory (no blank-line separator between frames
    -- each frame's own atom-count line is the delimiter, standard xmol
    multi-frame convention), one frame per image, in list order. Used both
    by pes_scan (default filename "path.xyz", one frame per scan image)
    and wigner_ensemble (filename="ensemble.xyz", one frame per sampled
    geometry) -- generic over any images: list[dict], no scan-specific
    logic here."""
    lines = []
    for i, geom in enumerate(images):
        lines.append(str(len(geom["symbols"])))
        lines.append(geom.get("name") or f"frame {i}")
        for sym, (x, y, z) in zip(geom["symbols"], geom["coords"]):
            lines.append(f"{sym:2s} {x: .8f} {y: .8f} {z: .8f}")
    path = job_dir / filename
    path.write_text("\n".join(lines) + "\n")
    return str(path)


def _pid_is_same_process(pid: Optional[int], create_time: Optional[float]) -> bool:
    """True if `pid` is currently alive AND its process start time matches
    `create_time` (recorded by this app itself when it originally spawned
    the process). Guards against the OS having reused that pid for a
    completely unrelated process in the time since a since-restarted
    backend last had it in memory -- a bare `psutil.pid_exists(pid)` check
    would not catch that."""
    if not pid or create_time is None:
        return False
    try:
        return abs(psutil.Process(pid).create_time() - create_time) < 1.0
    except psutil.NoSuchProcess:
        return False


class JobManager:
    """Singleton-ish manager: submits jobs to a bounded thread pool, each
    thread blocking on a subprocess that does the real work."""

    def __init__(self, max_concurrent: int = MAX_CONCURRENT_JOBS):
        self._executor = ThreadPoolExecutor(max_workers=max_concurrent)
        self._lock = threading.Lock()
        # Separate from self._lock deliberately: enforce_quota() does real
        # disk I/O (an rglob size walk for any not-yet-cached job directory,
        # potentially many of them cold after a fresh deploy or with several
        # large running jobs -- see quota.py) that can take seconds, whereas
        # every self._lock critical section elsewhere in this class is a
        # microsecond in-memory dict operation (_futures/_procs/_cancelled).
        # Holding self._lock across enforce_quota() would block cancel() and
        # _run_inner()'s own lock-guarded state transitions for every OTHER
        # concurrently running job for that whole duration -- the same
        # "blocking I/O must stay outside self._lock" principle
        # _wait_for_resources already follows for _host_cpu_snapshot()'s 1s
        # blocking call. This lock only serializes concurrent enforce_quota()
        # calls against each other (avoiding two submits racing the same
        # eviction sweep); it does not gate submission itself.
        self._quota_lock = threading.Lock()
        self._futures: dict[str, Any] = {}
        self._procs: dict[str, subprocess.Popen] = {}  # job_id -> live worker process
        self._orphan_pids: dict[str, int] = {}  # job_id -> pid of a re-attached orphaned worker (see below)
        self._cancelled: set[str] = set()  # cancel() requested, not yet reaped by _run
        self._reconcile_orphaned_jobs()

    def _reconcile_orphaned_jobs(self) -> None:
        """Runs once, at the moment a brand-new JobManager is constructed
        (server startup, or first get_job_manager() call) -- nothing this
        fresh instance has itself submitted could possibly be non-terminal
        yet, so any job still on disk as "pending"/"running" was left
        mid-flight by a *previous* backend process that died (killed,
        restarted, crashed) while that job's worker subprocess -- a
        fully-detached, own-process-group child per _run_inner's
        start_new_session=True -- was still going. That worker keeps
        running to completion on its own regardless of its parent's fate
        (the whole point of a subprocess over a thread -- see this
        module's docstring), but nothing was then left alive to perform
        _run_inner's final `write_status(job_id, result["status"], "done")`
        call, so status.json can get stuck reporting "running" forever even
        after result.json already holds the real, correct terminal
        outcome -- and both cancel() (looks for a live Popen in
        self._procs, empty in a fresh process) and DELETE /api/jobs/{id}
        (refuses to delete a non-terminal job) become permanently unable to
        touch it. Confirmed as a real, reproduced bug in this dev
        environment (which restarts the backend routinely -- no
        autoreload), not a hypothetical: an ORCA CASSCF job's result.json
        held a complete, valid "completed" summary while its status.json
        was stuck at "running" with no live process behind it anywhere.

        Three cases, handled differently:
          1. result.json already has a terminal status -- the worker
             finished after its parent died. Sync status.json to match.
          2. No result.json yet, but meta.json's worker_pid is still alive
             and identity-verified (_pid_is_same_process, guarding against
             pid reuse) -- the worker is still silently computing as an
             orphan. Re-attach it (_watch_orphan_worker) so it still gets
             finalized once it exits, and so cancel() can still reach it
             via self._orphan_pids.
          3. Neither -- the worker is actually gone with nothing to show
             for it (e.g. it also died, or predates worker_pid tracking).
             Mark it "failed" with an explanatory message rather than
             leaving it stuck; there is no outcome left to recover."""
        for job_id in _iter_job_ids_on_disk():
            status = read_status(job_id) or {}
            if status.get("status") not in ("pending", "running"):
                continue
            result = read_result(job_id)
            if result is not None and result.get("status") in ("completed", "failed", "cancelled"):
                write_status(job_id, result["status"], "recovered after a server restart")
                continue
            spec = read_spec(job_id)
            if spec is not None and spec.get("method") in MASTER_METHODS:
                # A master job (pes_scan/wigner_ensemble) is never itself a
                # dispatched subprocess (see submit_scan/submit_ensemble)
                # -- it has no worker pid to reconcile, and "running"
                # across a server restart is its normal state, not an
                # orphan: its dedicated background orchestrator
                # (scan_orchestrator.py / ensemble_orchestrator.py) is
                # stateless and simply resumes polling/dispatching this
                # master's sub-jobs (which reconcile via their own entries
                # in this same loop) on its next tick.
                continue
            meta = read_meta(job_id)
            pid = meta.get("worker_pid")
            if _pid_is_same_process(pid, meta.get("worker_pid_create_time")):
                self._orphan_pids[job_id] = pid
                # A plain daemon thread, deliberately NOT self._executor
                # (the job-dispatch pool, bounded to MAX_CONCURRENT_JOBS):
                # submitting here would let orphan watchers -- which do no
                # CPU work of their own, just block in psutil's wait -- eat
                # dispatch slots a real job needs, silently dropping actual
                # concurrency below the configured cap (worse with more
                # orphans, e.g. all 4 slots parked on watchers after a
                # restart during 4 running jobs). A non-daemon thread here
                # would also be joined at interpreter shutdown, meaning the
                # backend process itself could never exit while any orphan
                # was still mid-run -- daemon=True lets the process exit
                # freely; the watcher's job is still safe to lose, since
                # the next startup's _reconcile_orphaned_jobs() picks the
                # same job back up (case 1 if it finished by then, case 2
                # again if not).
                threading.Thread(target=self._watch_orphan_worker, args=(job_id, pid), daemon=True).start()
                continue
            write_status(
                job_id, "failed",
                "the server restarted while this job was queued/running and its outcome could not be "
                "recovered -- its worker process is no longer alive and left no result",
            )
            write_result(JobResult(job_id, "failed", error=(
                "Job interrupted by a server restart with no recoverable result. Please resubmit."
            )))

    def _watch_orphan_worker(self, job_id: str, pid: int) -> None:
        """Companion to _reconcile_orphaned_jobs case 2: finalizes a job
        whose worker subprocess is still alive but was spawned by a
        *previous* backend process, not this one, so it's not our child
        and proc.wait() isn't available. psutil's Process.wait() busy-polls
        instead (documented psutil behavior for non-child pids on POSIX),
        which is all we need here -- we only care that it eventually exits,
        not its exit code (the worker's own result.json is the source of
        truth for outcome either way, same as _run_inner's normal path)."""
        try:
            psutil.Process(pid).wait(timeout=6 * 3600)
        except Exception:
            pass
        with self._lock:
            self._orphan_pids.pop(job_id, None)
            was_cancelled = job_id in self._cancelled
            self._cancelled.discard(job_id)
        if was_cancelled:
            write_status(job_id, "cancelled", "cancelled by user")
            write_result(JobResult(job_id, "cancelled", error="Cancelled by user."))
            return
        result = read_result(job_id)
        if result is not None and result.get("status") in ("completed", "failed", "cancelled"):
            write_status(job_id, result["status"], "recovered after a server restart")
            return
        write_status(job_id, "failed", "worker process exited after a server restart with no result recorded")
        write_result(JobResult(job_id, "failed", error=(
            "Worker process ended (after a server restart) without producing a result.json; "
            "see worker.log if present."
        )))

    def submit(self, spec: JobSpec, owner_user_id: Optional[str] = None) -> str:
        job_dir = spec.job_dir()
        (job_dir / "spec.json").write_text(json.dumps(spec.to_dict(), indent=2))
        write_status(spec.job_id, "pending", "queued")

        # SEC-07: record ownership HERE, the instant the job is genuinely
        # visible (spec.json/status.json already written above), before
        # ANYTHING else in this call -- not after this method returns.
        # That distinction matters: this method's own quota-enforcement
        # pass below (enforce_quota(), which recomputes usage across every
        # user's jobs/KB/chat) is real, measured disk+Postgres work that
        # can itself take multiple seconds on a populated deployment --
        # confirmed directly (not assumed) while verifying this fix,
        # where a caller recording ownership only after THIS METHOD
        # returned still observed the job as unowned-and-readable for the
        # entire duration of enforce_quota() below, i.e. the window moved,
        # it didn't close. owner_user_id is None (skipped entirely, no
        # app.auth import even attempted) for local-dev/no-auth callers
        # and for every internal call this class makes to itself (e.g.
        # submit_scan()'s per-image sub-jobs, which are never individually
        # owned -- only the pes_scan master is, recorded once in
        # submit_scan() itself, see below).
        if owner_user_id:
            from app.auth.models import record_ownership
            record_ownership("job", spec.job_id, owner_user_id)

        future = self._executor.submit(self._run, spec)
        with self._lock:
            self._futures[spec.job_id] = future
        # Deferred import: quota.py imports several names from this module
        # at its own top level, so importing it eagerly at base.py's module
        # scope would be a circular import. By the time submit() actually
        # runs, this module has long finished loading, so the deferred
        # import resolves cleanly. Runs under self._quota_lock, NOT
        # self._lock -- see that lock's docstring in __init__ for why
        # enforce_quota()'s disk I/O must not share a lock with cancel()/
        # _run_inner()'s fast in-memory state transitions.
        from app.chemistry.jobs.quota import enforce_quota
        with self._quota_lock:
            enforce_quota()
        return spec.job_id

    def submit_scan(
        self, master_spec: JobSpec, images: list[dict], coordinate_values: list[float], coordinate_label: str,
        image0_raw_input: Optional[str] = None, owner_user_id: Optional[str] = None,
    ) -> str:
        """Submits a pes_scan "master" job: writes the master's own spec/
        status/result immediately (with the full interpolated path already
        rendered to disk as artifacts['path_xyz'] -- so the frontend can
        show the frame slider and every geometry the instant this call
        returns, not only once sub-jobs finish), then submits one ordinary
        JobSpec per image via the normal submit() path -- reusing all of
        its resource-gating/concurrency logic unchanged. The master itself
        never runs as a dispatched subprocess (it does no compute of its
        own); app/chemistry/jobs/scan_orchestrator.py is what later
        aggregates the sub-jobs' results back into the master's own
        result.json once they're terminal.

        owner_user_id is recorded for the MASTER only, immediately after
        its own spec/status become visible below -- same SEC-07 reasoning
        as submit()'s own owner_user_id handling. Per-image sub-jobs are
        never individually recorded in ownership_index (they're not
        independently reachable -- see server/routes/jobs.py, only
        visible nested under their already-owner-checked master), so their
        own self.submit(sub_spec) calls below deliberately pass no owner.
        """
        job_dir = master_spec.job_dir()
        (job_dir / "spec.json").write_text(json.dumps(master_spec.to_dict(), indent=2))
        write_status(master_spec.job_id, "running", f"submitting {len(images)} images")
        if owner_user_id:
            from app.auth.models import record_ownership
            record_ownership("job", master_spec.job_id, owner_user_id)

        path_xyz = _write_path_xyz(job_dir, images)
        n = len(images)
        summary = {
            "scan_job_type": master_spec.params.get("scan_job_type"),
            "engine": master_spec.engine,
            "coordinate": coordinate_label,
            "coordinate_values": [float(v) for v in coordinate_values],
            "n_points": n,
            "energies_hartree": [None] * n,
            "relative_energies_kcal_mol": [None] * n,
            "failed_images": [],
        }
        write_result(JobResult(master_spec.job_id, "running", summary=summary, artifacts={"path_xyz": path_xyz}))

        # Also drops underscore-prefixed bookkeeping keys (_scan_start_molecule,
        # _end_molecule, etc.) -- none of those belong on a
        # per-image sub-job's own params (they'd otherwise duplicate a full
        # molecule geometry dict into every single image's spec.json).
        sub_params = {
            k: v for k, v in master_spec.params.items() if k not in SCAN_ONLY_PARAM_KEYS and not k.startswith("_")
        }
        for i, image in enumerate(images):
            image_params = {**sub_params, "_scan_index": i}
            if i == 0 and image0_raw_input is not None:
                # A hand-edited approval-card input only ever applies to
                # this one image's own literal file -- every other image
                # needs its own geometry baked into its input, which a
                # single fixed edited text can't provide (see submit_job's
                # docstring in app/agent/tools.py).
                image_params["_raw_input"] = image0_raw_input
            sub_spec = JobSpec(
                method=master_spec.params["scan_job_type"], engine=master_spec.engine, molecule=image,
                params=image_params, parent_job_id=master_spec.job_id,
            )
            self.submit(sub_spec)
        return master_spec.job_id

    def submit_ensemble(
        self, master_spec: JobSpec, samples: list[dict], diagnostics: dict, owner_user_id: Optional[str] = None,
    ) -> str:
        """Submits a wigner_ensemble "master" job -- mirrors submit_scan's
        shape closely (writes the master's own spec/status/result
        immediately, with every sampled geometry already rendered to disk
        as artifacts['ensemble_xyz'] so it's downloadable the instant this
        call returns), with one deliberate deviation: at up to 250 samples
        (registry.py's PARAM_HELP), submitting every sub-job up front the
        way submit_scan does would run enforce_quota()'s disk-size walk
        and _wait_for_resources's JOBS_DIR scan once per sub-job inside
        this one blocking call, and could let quota eviction reap the
        ensemble's own earliest members before it finishes -- problems
        pes_scan's usual handful-to-dozens of images never had to solve.
        Instead, only an initial wave (up to
        app.config.ENSEMBLE_MAX_IN_FLIGHT) is dispatched here;
        app.chemistry.jobs.ensemble_orchestrator.EnsembleOrchestrator tops
        up the rest each tick as earlier sub-jobs go terminal, and (once
        every sub-job is terminal) pools their results into the master's
        own result.json, mirroring ScanOrchestrator's aggregation role.

        `samples` is the FULL list of n_samples geometries (already
        computed by the caller via app.chemistry.jobs.wigner.
        sample_wigner_ensemble, using the random_seed already round-
        tripped through master_spec.params -- see
        app/agent/tools.py's _build_ensemble_spec_or_error docstring for
        why that seed must be fixed before interrupt()) -- writing all of
        them to ensemble_xyz up front, not just the initial wave, lets
        EnsembleOrchestrator re-derive later waves deterministically from
        (random_seed, n_samples) without this method needing to persist
        the sample set a second time. `diagnostics` (wigner.
        sample_wigner_ensemble's own second return value -- dropped-mode
        counts, cutoffs used) is surfaced directly in the master's summary
        so a human sees exactly which modes were excluded, matching this
        app's "corrections are surfaced, not silent" convention.

        owner_user_id is recorded for the MASTER only, same SEC-07
        reasoning as submit_scan's own owner_user_id handling -- per-
        sample sub-jobs are never individually recorded in
        ownership_index (only visible nested under their already-owner-
        checked master), so their own self.submit(sub_spec) calls below
        pass no owner."""
        from app.config import ENSEMBLE_MAX_IN_FLIGHT

        job_dir = master_spec.job_dir()
        (job_dir / "spec.json").write_text(json.dumps(master_spec.to_dict(), indent=2))
        n_samples = len(samples)
        write_status(master_spec.job_id, "running", f"submitting an initial wave of samples (0 of {n_samples})")
        if owner_user_id:
            from app.auth.models import record_ownership
            record_ownership("job", master_spec.job_id, owner_user_id)

        ensemble_xyz = _write_path_xyz(job_dir, samples, filename="ensemble.xyz")
        summary = {
            "scan_job_type": master_spec.params.get("scan_job_type"),
            "source_frequency_job_id": master_spec.params.get("source_frequency_job_id"),
            "engine": master_spec.engine,
            "n_samples": n_samples,
            "n_dispatched": 0,
            "n_complete": 0,
            "random_seed": master_spec.params.get("random_seed"),
            "temperature_K": master_spec.params.get("temperature_K", 0.0),
            **diagnostics,
        }
        write_result(JobResult(master_spec.job_id, "running", summary=summary, artifacts={"ensemble_xyz": ensemble_xyz}))

        sub_params = {
            k: v for k, v in master_spec.params.items() if k not in ENSEMBLE_ONLY_PARAM_KEYS and not k.startswith("_")
        }
        wave_size = min(ENSEMBLE_MAX_IN_FLIGHT, n_samples)
        for i in range(wave_size):
            sub_spec = JobSpec(
                method=master_spec.params["scan_job_type"], engine=master_spec.engine, molecule=samples[i],
                params={**sub_params, "_ensemble_index": i}, parent_job_id=master_spec.job_id,
            )
            self.submit(sub_spec)
        summary["n_dispatched"] = wave_size
        write_status(master_spec.job_id, "running", f"{wave_size} of {n_samples} samples dispatched")
        write_result(JobResult(master_spec.job_id, "running", summary=summary, artifacts={"ensemble_xyz": ensemble_xyz}))
        return master_spec.job_id

    def cancel(self, job_id: str) -> bool:
        """Requests cancellation of a pending or running job. Returns True
        if a cancellation was applied, False if the job was already
        terminal (nothing to cancel). Kills the worker's whole process
        group, not just its direct child -- ORCA/BAGEL launch MPI ranks as
        child processes of the worker, which `start_new_session=True` in
        _run puts in the same group, so killing only the worker pid would
        orphan the actual running computation (still burning CPU/writing
        output) while the UI reports "cancelled".

        Also reaches jobs whose worker was re-attached as an orphan by
        _reconcile_orphaned_jobs (a prior backend process died mid-job and
        this one picked its still-running worker back up) -- those have no
        Popen in self._procs, only a bare pid in self._orphan_pids, since
        we never spawned them ourselves in this process.

        A master job (pes_scan/wigner_ensemble -- see MASTER_METHODS) has
        no process of its own to kill (see submit_scan/submit_ensemble) --
        cancelling one instead cancels every still-pending/running sub-job
        (each a normal cancel() call, recursively) and marks the master
        itself "cancelled" directly."""
        spec = read_spec(job_id)
        if spec is not None and spec.get("method") in MASTER_METHODS:
            for sub_id in sub_job_ids_of(job_id):
                if (read_status(sub_id) or {}).get("status") in ("pending", "running"):
                    self.cancel(sub_id)
            write_status(job_id, "cancelled", "cancelled by user")
            write_result(JobResult(job_id, "cancelled", error="Cancelled by user.",
                                    summary=(read_result(job_id) or {}).get("summary", {})))
            return True
        with self._lock:
            proc = self._procs.get(job_id)
            orphan_pid = self._orphan_pids.get(job_id) if proc is None else None
            pending = proc is None and orphan_pid is None and (read_status(job_id) or {}).get("status") == "pending"
            if proc is None and orphan_pid is None and not pending:
                return False
            self._cancelled.add(job_id)
        if orphan_pid is not None:
            try:
                os.killpg(orphan_pid, signal.SIGTERM)
            except ProcessLookupError:
                return True
            try:
                # Not our child, so proc.wait() isn't available -- psutil's
                # Process.wait() busy-polls instead, which works the same
                # for a foreign pid (see _watch_orphan_worker's docstring).
                psutil.Process(orphan_pid).wait(timeout=10)
            except (psutil.NoSuchProcess, psutil.TimeoutExpired):
                if psutil.pid_exists(orphan_pid):
                    try:
                        os.killpg(orphan_pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
            return True
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

    def _running_job_ids(self) -> set[str]:
        """Every job_id currently reporting status=="running" on disk,
        EXCLUDING master jobs (pes_scan/wigner_ensemble -- see
        MASTER_METHODS) -- a master is marked "running" for its whole
        lifetime as a bookkeeping convenience (see submit_scan/
        submit_ensemble) but is never itself a dispatched subprocess and
        consumes no CPU/dispatch-slot of its own; counting it toward a
        concurrent-jobs cap would consume an admission slot for a job that
        isn't actually computing anything, starving real jobs behind it
        for no reason. Used only by the concurrent-jobs admission gate
        below -- a small O(n) directory walk per resource-wait poll tick,
        same cost profile as the existing CPU/mem snapshot it runs
        alongside."""
        running = set()
        for job_id in _iter_job_ids_on_disk():
            try:
                if (read_status(job_id) or {}).get("status") != "running":
                    continue
                spec = read_spec(job_id)
                if spec is not None and spec.get("method") in MASTER_METHODS:
                    continue
            except OSError:
                continue
            running.add(job_id)
        return running

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
            # _host_cpu_snapshot() blocks for its sampling interval, so it stays
            # first: it is this loop's pacing, and skipping it on any path would
            # turn the loop into a spin.
            cpu, n_idle = _host_cpu_snapshot()
            mem = _mem_percent_used()
            has_headroom = cpu < MAX_CPU_PERCENT and mem < MAX_MEM_PERCENT and n_idle >= N_CORES
            blocked_by = self._concurrent_jobs_block_reason(job_id)

            if blocked_by is None and has_headroom:
                return True

            # An admin-set cap is reported IN PREFERENCE to host headroom, and
            # that ordering is the point. The two are not equally useful to the
            # person waiting: headroom is ambient and transient ("it'll start
            # when the box frees up"), whereas a cap is deterministic and about
            # them -- with a per-user cap of 1, their second job will not start
            # until their own first one finishes no matter how idle the host
            # becomes. Reporting headroom in that situation is actively
            # misleading, and it is what a loaded host used to report, because
            # the cap was only ever consulted on ticks where headroom happened
            # to exist.
            #
            # Cost: the cap check now runs on every tick rather than only on
            # headroom-available ticks, so a loaded host does one extra small
            # indexed lookup per waiting job per second. That is the case where
            # jobs are queued anyway, and it is the same query the idle path
            # has always made.
            write_status(
                job_id, "pending",
                blocked_by
                or f"waiting for CPU/memory headroom (cpu {cpu:.0f}%, mem {mem:.0f}%, {n_idle}/{N_CORES} cores idle)",
            )

    def _concurrent_jobs_block_reason(self, job_id: str) -> Optional[str]:
        """Admin-configurable concurrent-RUNNING-jobs caps (total and
        per-user), layered on top of the CPU/memory headroom gate above --
        that gate answers "does the host have room", this answers "has the
        admin decided to allow this many jobs running AT ONCE regardless of
        headroom". Multi-user-deployment-only (returns None immediately,
        i.e. never blocks, when QC_AGENT_DATABASE_URL is unset -- there's
        no "user" concept to cap per-user in local dev, and the total cap
        is redundant with MAX_CONCURRENT_JOBS' own executor pool size
        there anyway).

        Ownership is recorded only after a job's approval request returns
        (see server/routes/chat.py's approve_job, which calls submit()
        before recording ownership) -- so a just-submitted job can briefly
        read back as unowned here. That only means its OWN per-user check
        is skipped for this poll tick (it still counts toward the total
        check, and toward every other user's per-user check); the next
        poll tick (this loop runs roughly once a second) almost always
        finds the ownership row by then. This is the same soft,
        eventually-consistent character as the CPU/memory gate above, not
        a hard guarantee."""
        from app.config import DATABASE_URL
        if not DATABASE_URL:
            return None
        from app.auth.models import get_owner
        from app.auth.storage_quota import get_quota_config

        cfg = get_quota_config()
        running = self._running_job_ids()
        running.discard(job_id)  # this job's own status.json may already say "running" from a prior loop iteration
        if len(running) >= cfg["max_concurrent_jobs_total"]:
            return f"waiting for a free job slot ({len(running)}/{cfg['max_concurrent_jobs_total']} running total)"

        owner = get_owner("job", job_id)
        if owner is None:
            return None
        from app.auth.models import all_owners
        owners = all_owners("job")
        user_running = sum(1 for jid in running if owners.get(jid) == owner)
        if user_running >= cfg["max_concurrent_jobs_per_user"]:
            return f"waiting for a free job slot (you have {user_running}/{cfg['max_concurrent_jobs_per_user']} running)"
        return None

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
        # block2 (recommend_active_space's optional DMRG entropy backend, pyscf
        # engine only) ships its own bundled MKL .so files but dlopen's a sibling
        # libmkl_def.so.1 that only exists in the conda env's own lib/ dir, not
        # inside block2's bundled lib set -- confirmed empirically (a plain
        # `import pyblock2` fails with "Intel MKL FATAL ERROR: Cannot load
        # libmkl_def.so.1" unless that dir is on LD_LIBRARY_PATH, since this
        # host's shell profile sets LD_LIBRARY_PATH to unrelated system-wide
        # paths, not the conda env's own lib dir). Scoped to engine=="pyscf"
        # only, not applied universally: ORCA's own subprocess invocation
        # (orca_runner.py) builds its env as dict(os.environ), inherited
        # straight from this worker process, so prepending conda's MKL/libgomp
        # here for every engine risks the classic "wrong MKL/libgomp picked up"
        # failure mode for ORCA's own bundled libraries.
        env = None
        if spec.engine == "pyscf":
            env = dict(os.environ)
            conda_lib = str(Path(sys.executable).resolve().parents[1] / "lib")
            env["LD_LIBRARY_PATH"] = conda_lib + os.pathsep + env.get("LD_LIBRARY_PATH", "")
        try:
            with open(log_path, "w") as log_f:
                proc = subprocess.Popen(
                    [sys.executable, "-m", module, str(job_dir / "spec.json")],
                    stdout=log_f, stderr=subprocess.STDOUT,
                    cwd=str(Path(__file__).resolve().parents[3]),
                    env=env,
                    start_new_session=True,  # own process group, so cancel()/timeout
                                              # can reach ORCA/BAGEL's MPI child ranks too
                )
                with self._lock:
                    self._procs[spec.job_id] = proc
                    already_cancelled = spec.job_id in self._cancelled
                try:
                    # Persisted so a *future* backend process (this one may
                    # get killed/restarted while proc.wait() below is still
                    # blocking -- routine in this dev workflow, no
                    # autoreload) can find and re-attach this worker via
                    # _reconcile_orphaned_jobs instead of leaving status.json
                    # stuck at "running" forever with no live Popen anywhere
                    # to finalize it. create_time guards _pid_is_same_process
                    # against pid reuse.
                    write_meta(spec.job_id, {
                        "worker_pid": proc.pid,
                        "worker_pid_create_time": psutil.Process(proc.pid).create_time(),
                    })
                except psutil.NoSuchProcess:
                    pass
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
        """Always a dict, unlike read_status (F-024), because every HTTP
        caller indexes `["status"]` directly and each of them has already
        404'd on a missing spec before getting here. A job that genuinely
        isn't on disk reports "unknown" rather than the old "pending",
        which claimed a deleted job was about to run."""
        return read_status(job_id) or {"status": "unknown", "message": "no such job", "updated_at": None}

    def result(self, job_id: str) -> Optional[dict]:
        return read_result(job_id)


_manager: Optional[JobManager] = None


def get_job_manager() -> JobManager:
    global _manager
    if _manager is None:
        _manager = JobManager()
    return _manager
