"""Job data model and background execution manager.

Every calculation, regardless of which engine (PySCF/ORCA/BAGEL) actually
runs it. Is represented as a `JobSpec` on the way in and a `JobResult` on
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

# A job that has finished, however it finished. Six modules used to carry
# their own copy of this literal; they now import this one.
TERMINAL_STATUSES = {"completed", "failed", "cancelled"}
NON_TERMINAL_STATUSES = VALID_STATUSES - TERMINAL_STATUSES

# pes_1d/interp_pes-only keys on a scan master's JobSpec.params that
# describe the scan itself (interpolation method, how many images, which
# coordinate), not the per-image calculation -- JobManager.submit_scan
# strips these out before using params as the template for every per-image
# sub-job's own params, so e.g. n_points doesn't leak into a single_point
# sub-job's spec. Note what is deliberately NOT here: n_states and use_tda
# describe the per-image calculation, not the scan, so they DO travel to
# every child -- that is what makes an excited-state scan compute excited
# states at each point rather than only on the master that has no compute
# of its own.
SCAN_ONLY_PARAM_KEYS = {
    "interpolation_method", "n_points", "coordinate", "scan_range",
}


def scan_child_subtype(master_subtype: Optional[str]) -> str:
    """The `single_point` subtype every image of a scan runs, given the
    scan master's own subtype.

    A scan master is either ground state (the BARE subtype, "" -- see
    registry2/tasks.py on why the scan tasks were not renamed to a
    symmetric gs/ee pair) or excited state ("ee"). Its images are ordinary
    `single_point` jobs, and those DO use the symmetric spelling, so the
    empty string has to be translated to "gs" rather than passed through.

    Two callers, and they must agree: scan_orchestrator dispatches the real
    sub-jobs, and app/agent/tools.py builds the image-0 spec whose input
    preview goes on the approval card. If they disagreed the card would
    show a ground-state input for a job that then ran excited states, which
    is the exact class of silent substitution the approval gate exists to
    prevent -- hence one function rather than the same conditional written
    twice.

    Note that no per-method branching is needed here or anywhere below it.
    `dispatch.resolve_runner` tests casscf/caspt2 BEFORE it tests
    subtype == "ee", so "ee" reaches the CASSCF runner for a multireference
    method and the TDDFT/EOM-CCSD runner for a single-reference one.
    """
    return "ee" if master_subtype == "ee" else "gs"

# wigner_spectra-only keys on an ensemble master's JobSpec.params that
# describe the ensemble itself (which frequency job to sample from, how
# many samples, sampling parameters), not the per-sample excited-state
# calculation -- JobManager.submit_ensemble strips these out before using
# params as the template for every per-sample sub-job's own params, same
# role SCAN_ONLY_PARAM_KEYS plays for pes_1d/interp_pes.
ENSEMBLE_ONLY_PARAM_KEYS = {
    "source_frequency_job_id", "n_samples", "random_seed",
    "temperature_K", "low_freq_cutoff_cm1", "fwhm_eV",
}

# batch-only keys on a batch master's JobSpec.params -- describe the
# batch itself (its geometry SOURCE, and which task family every child
# runs), not any individual child's own calculation params. Stripped
# before using params as the template for every child's own params, same
# role SCAN_ONLY_PARAM_KEYS/ENSEMBLE_ONLY_PARAM_KEYS play above.
BATCH_ONLY_PARAM_KEYS = {"source_job_id", "child_task"}

# The v2 tasks that fan out into sub-jobs. Derived from the registry rather
# than listed here, so adding a master task cannot leave a stale set behind
# -- the same reason `registry2/tasks.py` derives `supports()` instead of
# enumerating it. `blind` is excluded despite `master=True` in the registry:
# a blind job is one ordinary ORCA/BAGEL subprocess; `master=True` there
# means only "no `method` of its own", per TaskDef's own docstring, not "has
# children". `batch` gained real sub-job orchestration in Phase 7
# (JobManager.submit_batch/batch_orchestrator.py) and is included here like
# any other master task now. `geometry_set` (Phase 3) creates its job
# directly through `JobManager.submit_geometry_set` below with zero
# sub-jobs of its own -- `delete_job_dir` et al. treating it as a childless
# master is already correct, so it is included here rather than excluded.
# Every function below that needs to special-case "this is a master,
# cascade to its children" (delete_job_dir, cancel,
# _reconcile_orphaned_jobs, _running_job_ids) goes through `is_master_spec`
# rather than a literal task-name string, so a new master task only needs
# adding to the registry, not at every call site.
def _master_tasks() -> frozenset[str]:
    from app.chemistry.registry2.tasks import TASKS

    return frozenset(t.task for t in TASKS.values() if t.master and t.task != "blind")


def spec_task(spec: Optional[dict]) -> str:
    """The v2 task of an on-disk spec, or "" for one with none (a spec this
    read-through-disk path could not find, or an internal/transient one
    that was never persisted)."""
    return (spec or {}).get("task") or ""


def is_master_spec(spec: Optional[dict]) -> bool:
    """Does this job fan out into sub-jobs? Keyed on the v2 task alone --
    no on-disk spec is expected to exist without one, per the clean-slate
    decision (see docs/trackers/2026-08-job-system-overhaul.md's Phase 1 note)."""
    return spec_task(spec) in _master_tasks()


@dataclass
class JobSpec:
    # The level of theory ("hf", "dft", "casscf", "caspt2", "eom_ccsd", ...
    # -- registry2/capabilities.py's CANONICAL_METHODS), matching what the
    # word means everywhere else in v2. Empty ("") for a task with no level
    # of theory of its own (task="blind": raw text, no structured method).
    # What a job *is* -- task/subtype below -- is a completely separate
    # axis; which internal run_*/build_input_preview function handles a
    # (task, subtype, method) is derived fresh, only at the point of actual
    # dispatch, by app/chemistry/jobs/dispatch.py's resolve_runner -- never
    # stored here. See that module's docstring for the full reasoning.
    method: str
    engine: str  # pyscf | orca | bagel
    molecule: dict
    params: dict = field(default_factory=dict)
    # The v2 taxonomy: `task` is what the user asked for ("opt", "freq",
    # "wigner_spectra"), `subtype` narrows it ("min", "ci", "ee"). Every
    # reader that decides what a job *means* -- is it a master, can it seed
    # an ensemble, does its input need validating -- keys on these.
    task: str = ""
    subtype: str = ""
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
            "task": self.task, "subtype": self.subtype,
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

    The distinction is drawn at spec.json, not at status.json and not at
    the directory: `submit` writes spec.json FIRST and status.json
    immediately after, so a directory holding a spec but no status really is
    a queued job and still reports "pending", which is what it is. Anything
    else is not a job, and that is None -- matching `read_result`/`read_spec`,
    which have always returned None for a job that isn't there.

    Keying on the directory alone was not enough, and the gap was observed
    live: a directory can outlive its job, or be recreated after it, holding
    nothing but a stray artifact (an orbitals.molden written by an
    orbital-reuse path after the job it belonged to was purged). Such a
    directory reported "pending" forever. That is the worst of both worlds --
    the Job Manager hides it, because its own listing requires spec.json, so
    the app would tell a user a job was queued while showing them a list it
    was not in, and any caller treating "pending" as "wait for it" would wait
    on it indefinitely. Exactly the failure F-024 set out to remove, just one
    level further in.
    """
    if not (JOBS_DIR / job_id / "spec.json").exists():
        return None
    p = _status_path(job_id)
    if not p.exists():
        return {"status": "pending", "message": "", "updated_at": None}
    try:
        return json.loads(p.read_text())
    except json.JSONDecodeError:
        return {"status": "pending", "message": "", "updated_at": None}


def job_is_terminal(job_id: str) -> bool:
    """Has this job finished? The one answer to that question.

    Reads status.json, via read_status, because that is what the job list,
    the job drawer and DELETE /api/jobs/{id} all already read -- so what
    the admin console shows and what its purge acts on cannot disagree.

    They did disagree. Both quota modules used to ask read_result()
    instead, and skip anything whose result.json was missing or
    statusless. write_status() and write_result() are two separate writes,
    so a job interrupted between them -- or written by anything that sets
    a status without a result -- was listed as completed and was
    permanently unpurgeable and mis-measured: `POST /api/admin/purge/jobs`
    reported `count: 0` against a console listing 299 finished jobs.

    Returns False for a job id with no directory at all (read_status ->
    None), which is right: there is nothing there to evict.
    """
    return (read_status(job_id) or {}).get("status") in TERMINAL_STATUSES


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
    this is read from submit_draft's pre-interrupt() code path, which
    re-executes in full on
    every resume; an exception there propagates straight out of
    resume_turn and kills the approval click outright rather than being
    caught into a ToolMessage (see docs/ARCHITECTURE.md's "The approval
    gate" for why the pre-interrupt path re-executes on resume at all).
    A vanished spec.json (e.g. its job dir was cleaned up
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

    Deleting a master job (pes_1d/interp_pes/wigner_spectra -- see is_master_spec)
    also deletes every one of its sub-jobs -- otherwise their directories
    would become permanently unreachable disk usage, since a sub-job is
    deliberately excluded from every job list (only visible nested under
    its master; see server/routes/jobs.py)."""
    import shutil

    from app.agent import threads as thread_registry

    spec = read_spec(job_id)
    if is_master_spec(spec):
        for sub_id in sub_job_ids_of(job_id):
            delete_job_dir(sub_id)

    job_dir = JOBS_DIR / job_id
    if job_dir.exists():
        shutil.rmtree(job_dir, ignore_errors=True)
    for entry in thread_registry.list_threads():
        active = entry.get("active_job_ids", [])
        if job_id in active:
            thread_registry.set_active_job_ids(entry["thread_id"], [j for j in active if j != job_id])

    # A saved plot is reclaimed only once its LAST source job is gone, so this
    # cannot simply delete the plots that mention this job: a seven-method
    # comparison must survive losing one of its seven. The sweep is what knows
    # the difference. Imported here rather than at module scope because
    # app.plots.store imports from app.config, which this module is itself
    # imported by during startup.
    from app.plots.store import sweep_orphans
    sweep_orphans()


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


def _resources_available() -> tuple[bool, int, str]:
    """One-shot host-headroom snapshot -- P4.1's extraction of the check
    that used to live inline in JobManager._wait_for_resources' polling
    loop (removed; see app/chemistry/jobs/scheduler.py). Blocks ~1s (see
    _host_cpu_snapshot's own docstring for why) -- a caller that calls this
    repeatedly gets that block as its own natural poll pacing, the same
    role it always played here.

    Returns (has_headroom, n_idle, message). n_idle is exposed (not just a
    bool) so the scheduler can spend one snapshot's idle-core count across
    several admissions in the same dispatch tick rather than reading it
    fresh per job; message is the ready-to-write "waiting for..." status
    text for when has_headroom is False.
    """
    cpu, n_idle = _host_cpu_snapshot()
    mem = _mem_percent_used()
    has_headroom = cpu < MAX_CPU_PERCENT and mem < MAX_MEM_PERCENT and n_idle >= N_CORES
    message = f"waiting for CPU/memory headroom (cpu {cpu:.0f}%, mem {mem:.0f}%, {n_idle}/{N_CORES} cores idle)"
    return has_headroom, n_idle, message


def _running_job_ids() -> set[str]:
    """Every job_id currently reporting status=="running" on disk,
    EXCLUDING master jobs (pes_scan/wigner_ensemble -- see is_master_spec)
    -- a master is marked "running" for its whole lifetime as a bookkeeping
    convenience (see submit_scan/submit_ensemble) but is never itself a
    dispatched subprocess and consumes no CPU/dispatch-slot of its own;
    counting it toward a concurrent-jobs cap would consume an admission
    slot for a job that isn't actually computing anything, starving real
    jobs behind it for no reason. Used only by the scheduler's own
    admission gate below -- a small O(n) directory walk per dispatch tick,
    same cost profile as the CPU/mem snapshot it runs alongside."""
    running = set()
    for job_id in _iter_job_ids_on_disk():
        try:
            if (read_status(job_id) or {}).get("status") != "running":
                continue
            spec = read_spec(job_id)
            if is_master_spec(spec):
                continue
        except OSError:
            continue
        running.add(job_id)
    return running


def _concurrent_jobs_block_reason(job_id: str, already_admitted: int = 0,
                                  already_admitted_for_owner: int = 0) -> Optional[str]:
    """Admin-configurable concurrent-RUNNING-jobs caps (total and
    per-user), evaluated centrally by the scheduler's dispatcher thread on
    top of the CPU/memory headroom gate above -- that gate answers "does
    the host have room", this answers "has the admin decided to allow this
    many jobs running AT ONCE regardless of headroom". Multi-user-
    deployment-only (returns None immediately, i.e. never blocks, when
    QC_AGENT_DATABASE_URL is unset -- there's no "user" concept to cap
    per-user in local dev, and the total cap is redundant with
    MAX_CONCURRENT_JOBS' own executor pool size there anyway).

    Ownership is recorded only after a job's approval request returns (see
    server/routes/chat.py's approve_job, which calls submit() before
    recording ownership) -- so a just-submitted job can briefly read back
    as unowned here. That only means its OWN per-user check is skipped for
    this dispatch tick (it still counts toward the total check, and toward
    every other user's per-user check); the scheduler's own ~1s poll
    pacing almost always finds the ownership row by the next tick. This is
    the same soft, eventually-consistent character as the CPU/memory gate
    above, not a hard guarantee.

    Deliberately keyed on this job's OWN recorded ownership (get_owner),
    not the "effective owner" _queue_owner() below resolves for a sub-job
    via its parent -- a sub-job is never individually recorded in
    ownership_index (SEC-07), so this per-user cap has never restricted
    sub-jobs specifically, and that is unchanged here. _queue_owner exists
    to fix a different problem (which user's FIFO a job's admission
    ATTEMPT is interleaved through), not this one (whether that specific
    job, once its turn comes up, is allowed to run)."""
    from app.config import DATABASE_URL
    if not DATABASE_URL:
        return None
    from app.auth.models import get_owner
    from app.auth.storage_quota import get_quota_config

    cfg = get_quota_config()
    running = _running_job_ids()
    running.discard(job_id)  # this job's own status.json may already say "running" from a prior loop iteration
    # `already_admitted` is the count of jobs the caller has admitted since
    # the newest status.json this scan could possibly have seen. It exists
    # because admission does NOT write status.json: _on_admit hands the job
    # to the executor and returns immediately (it must -- see scheduler.py),
    # and "running" is written later on a pool thread inside _run_inner. So
    # a caller that admits more than once between disk reads is invisible to
    # itself here, and the cap ends up bounding admissions PER CALLER PASS
    # rather than in total. See docs/trackers/ for the tracker that found it.
    n_running = len(running) + already_admitted
    if n_running >= cfg["max_concurrent_jobs_total"]:
        return f"waiting for a free job slot ({n_running}/{cfg['max_concurrent_jobs_total']} running total)"

    owner = get_owner("job", job_id)
    if owner is None:
        return None
    from app.auth.models import all_owners
    owners = all_owners("job")
    # Same blind spot, scoped to one owner. `already_admitted_for_owner` is
    # separate from the total above rather than derived from it, because the
    # caller's in-flight admissions may belong to several different owners
    # and only the ones matching THIS owner count against their per-user cap.
    user_running = (sum(1 for jid in running if owners.get(jid) == owner)
                    + already_admitted_for_owner)
    if user_running >= cfg["max_concurrent_jobs_per_user"]:
        return f"waiting for a free job slot (you have {user_running}/{cfg['max_concurrent_jobs_per_user']} running)"
    return None


def _queue_owner(job_id: str, spec: Optional[dict]) -> Optional[str]:
    """Resolves the effective owner used only to BUCKET a job into the
    fair scheduler's per-user FIFO queues -- a distinct concern from
    ownership *recording* (record_ownership/get_owner via ownership_index),
    which sub-jobs deliberately never receive (SEC-07: only a master job is
    individually reachable/ownership-checked, so per-image/per-sample
    sub-jobs are never given their own ownership_index row). Without this
    fallback, every pes_1d/interp_pes/wigner_spectra sub-job would land in
    the same unowned bucket regardless of who submitted the master, and
    round-robin fairness would not apply to exactly the case a large
    scan/ensemble exists to stress -- its dozens of sub-jobs would still
    all queue together as one undifferentiated block, invisible to any
    other user's own bucket.

    Falls back through: this job's own recorded owner (ordinary jobs) ->
    its parent master's recorded owner (sub-jobs) -> None (local-dev/
    no-auth, or an owner that could not be resolved either way -- these
    share the one "unowned" bucket, matching this app's single-tenant
    local-dev posture where fairness between "users" is not a meaningful
    concept)."""
    from app.config import DATABASE_URL
    if not DATABASE_URL:
        return None
    from app.auth.models import get_owner
    owner = get_owner("job", job_id)
    if owner is not None:
        return owner
    parent_id = (spec or {}).get("parent_job_id")
    if parent_id:
        return get_owner("job", parent_id)
    return None


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


def _children_manifest_path(master_id: str) -> Path:
    return JOBS_DIR / master_id / "children.jsonl"


def _record_child(master_id: str, job_id: str) -> None:
    """Appends `job_id` to its master's children manifest -- the index
    sub_job_ids_of reads instead of scanning JOBS_DIR. A one-line append
    under 4KB is atomic on a local filesystem with O_APPEND (POSIX
    PIPE_BUF guarantee), so no lock is needed here any more than one is
    needed around spec.json/status.json writes elsewhere in this module.
    Called from exactly one place -- submit() below -- so every master
    task (pes_1d/interp_pes today, batch once P7.4 lands) gets this for
    free rather than each orchestrator maintaining its own manifest."""
    with open(_children_manifest_path(master_id), "a") as f:
        f.write(job_id + "\n")


def sub_job_ids_of(master_id: str) -> list[str]:
    """Every job whose spec.json['parent_job_id'] == master_id (a pes_scan
    master's per-image sub-jobs, ordered by params['_scan_index'] -- see
    JobManager.submit_scan -- or a wigner_ensemble master's per-sample
    sub-jobs, ordered by params['_ensemble_index'] -- see
    JobManager.submit_ensemble).

    Reads the master's own children.jsonl manifest (written once per
    child by submit()'s _record_child call) rather than scanning every
    job on disk -- P7.3: a linear JOBS_DIR walk here was fine when this
    deployment's total job count was small, but its cost scales with
    EVERY job ever run, not with this master's own child count, which
    made both this function and the two orchestrators' every-3-second
    dispatch-loop tick (each of which calls this at least once) scale
    with total jobs on disk rather than with the scan/ensemble's own
    size. A master that has dispatched no children yet has no manifest
    file (not an error -- just zero children so far).

    A listed id whose spec.json no longer exists (deleted, e.g. by quota
    eviction) is silently dropped rather than erroring -- the manifest is
    an append-only log of what was ever dispatched, not a live index, so
    staleness here is expected and self-heals at read time."""
    manifest = _children_manifest_path(master_id)
    if not manifest.exists():
        return []
    found = []
    seen: set[str] = set()
    for line in manifest.read_text().splitlines():
        job_id = line.strip()
        if not job_id or job_id in seen:
            continue
        spec = read_spec(job_id)
        if spec is None:
            continue
        seen.add(job_id)
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
        # "blocking I/O must stay outside self._lock" principle the
        # scheduler's own dispatcher thread already follows for
        # _host_cpu_snapshot()'s 1s blocking call. This lock only
        # serializes concurrent enforce_quota()
        # calls against each other (avoiding two submits racing the same
        # eviction sweep); it does not gate submission itself.
        self._quota_lock = threading.Lock()
        # job_id -> the pool Future of a job that has been ADMITTED and has
        # not yet finished. Added in _on_admit, removed in _run's finally, so
        # its size is the number of jobs currently occupying a worker thread.
        # Nothing in the app reads it; it is kept because that size is the
        # one direct observation of "only admitted jobs enter the executor",
        # which is the property the fair scheduler exists to provide and
        # which tests/backend/perf_04_fair_scheduling.py asserts on.
        self._futures: dict[str, Any] = {}
        self._procs: dict[str, subprocess.Popen] = {}  # job_id -> live worker process
        self._orphan_pids: dict[str, int] = {}  # job_id -> pid of a re-attached orphaned worker (see below)
        self._cancelled: set[str] = set()  # cancel() requested, not yet reaped by _run
        # Deferred import: scheduler.py imports several names from this
        # module at its own top level (JobSpec, read_spec, etc.), so
        # importing it eagerly at base.py's module scope would be
        # circular -- same convention submit()'s own deferred quota.py
        # import already follows, for the same reason.
        from app.chemistry.jobs.scheduler import JobScheduler
        self._scheduler = JobScheduler(
            on_admit=self._on_admit,
            resources_available=_resources_available,
            block_reason=_concurrent_jobs_block_reason,
        )
        self._reconcile_orphaned_jobs()
        self._scheduler.start()

    def _on_admit(self, job_id: str) -> None:
        """The scheduler's dispatcher thread calls this the instant it
        decides a job may run -- must return immediately (see
        scheduler.py's own docstring on why nothing slow may execute on
        that thread). `self._executor.submit` itself only enqueues onto
        the pool and returns a Future right away; the actual subprocess
        spawn-and-block happens on a POOL thread inside self._run, never
        on the dispatcher thread that called this."""
        spec_dict = read_spec(job_id)
        if spec_dict is None:
            return  # job dir vanished between admission and dispatch (e.g. deleted) -- nothing to run
        spec = JobSpec(**spec_dict)
        future = self._executor.submit(self._run, spec)
        with self._lock:
            self._futures[job_id] = future

    def _reconcile_orphaned_jobs(self) -> None:
        """Runs once, at the moment a brand-new JobManager is constructed
        (server startup, or first get_job_manager() call), BEFORE the
        scheduler's own dispatcher thread starts -- nothing this fresh
        instance has itself submitted could possibly be non-terminal yet,
        so any job still on disk as "pending"/"running" was left mid-flight
        by a *previous* backend process that died (killed, restarted,
        crashed) while that job was still queued or its worker subprocess
        -- a fully-detached, own-process-group child per _run_inner's
        start_new_session=True -- was still going. A spawned worker keeps
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

        Four cases, handled differently:
          1. result.json already has a terminal status -- the worker
             finished after its parent died. Sync status.json to match.
          2. No result.json yet, but meta.json's worker_pid is still alive
             and identity-verified (_pid_is_same_process, guarding against
             pid reuse) -- the worker is still silently computing as an
             orphan. Re-attach it (_watch_orphan_worker) so it still gets
             finalized once it exits, and so cancel() can still reach it
             via self._orphan_pids.
          3. meta.json's worker_pid is unset -- this job was never
             admitted by the scheduler before the previous process died,
             so there is no worker to have lost, only a still-queued job.
             Re-enqueue it exactly as if freshly submitted (P4.4) rather
             than reporting a failure it never actually had; the
             scheduler itself hasn't started yet at this point in
             __init__, so this only appends to its in-memory queue.
          4. worker_pid is set but neither alive-and-verified nor unset --
             the worker really is gone with nothing to show for it (e.g.
             it also died, or predates worker_pid tracking). Mark it
             "failed" with an explanatory message rather than leaving it
             stuck; there is no outcome left to recover."""
        for job_id in _iter_job_ids_on_disk():
            status = read_status(job_id) or {}
            if status.get("status") not in ("pending", "running"):
                continue
            result = read_result(job_id)
            if result is not None and result.get("status") in ("completed", "failed", "cancelled"):
                write_status(job_id, result["status"], "recovered after a server restart")
                continue
            spec = read_spec(job_id)
            if is_master_spec(spec):
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
            if pid is None:
                self._scheduler.enqueue(job_id, _queue_owner(job_id, spec))
                continue
            write_status(
                job_id, "failed",
                "the server restarted while this job was running and its outcome could not be "
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
        if spec.parent_job_id:
            _record_child(spec.parent_job_id, spec.job_id)
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

        # Enqueues into the fair scheduler rather than dispatching to
        # self._executor directly -- see scheduler.py for why: only an
        # explicit admission decision by its dispatcher thread may spawn a
        # worker now, so a burst submission never occupies every pool slot
        # in submission order ahead of another user's job. owner_user_id
        # (the explicit, cheapest case) takes precedence over _queue_owner's
        # own parent-lookup fallback, which exists for sub-jobs (see that
        # function's docstring) -- passed here mainly so submit_scan's
        # per-image / EnsembleOrchestrator's per-sample self.submit(...)
        # calls (owner_user_id=None, parent_job_id set) still land in their
        # owning user's own queue rather than the shared unowned bucket.
        self._scheduler.enqueue(spec.job_id, owner_user_id or _queue_owner(spec.job_id, spec.to_dict()))

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
        image0_raw_input: Optional[str] = None, input_template: Optional[str] = None,
        owner_user_id: Optional[str] = None,
    ) -> str:
        """Submits a pes_1d/interp_pes "master" job: writes the master's own
        spec/status/result immediately (with the full interpolated path
        already rendered to disk as artifacts['path_xyz'] -- so the
        frontend can show the frame slider and every geometry the instant
        this call returns, not only once sub-jobs finish), then dispatches
        an initial WAVE of per-image sub-jobs (up to
        app.config.MASTER_MAX_IN_FLIGHT) rather than all of them at once.
        app/chemistry/jobs/scan_orchestrator.py tops up the rest as
        earlier images go terminal, mirroring submit_ensemble's own wave
        dispatch below -- P4.3 generalized this from wigner_spectra-only
        to pes_1d/interp_pes too: submitting every sub-job up front is
        exactly the kind of burst a single user's large scan could use to
        occupy every fair-scheduler admission attempt in one rotation
        ahead of any other queued job (see scheduler.py's own docstring on
        the starvation vector this closes). The master itself never runs
        as a dispatched subprocess (it does no compute of its own);
        scan_orchestrator.py both dispatches its sub-jobs and later
        aggregates their results back into the master's own result.json
        once they're all terminal.

        image0_raw_input (a hand-edited approval-card input, applying only
        to image 0's own literal file -- see submit_draft's docstring in
        app/agent/tools.py) is stashed on the master spec's own params
        under a `_`-prefixed key so ScanOrchestrator's later wave dispatch
        can still apply it once image 0 is actually sent; the same
        underscore-prefix filtering that already keeps scan-only keys off
        every per-image sub-job's own params (see sub_params below, in
        scan_orchestrator.py's own _dispatch_more) keeps it from leaking
        into any OTHER image's params too.

        input_template (P7.2, interp_pes only) is the cascade counterpart:
        a hand-edited input applied to EVERY image, with only its geometry
        block substituted per image (app/chemistry/jobs/scan_template.py),
        so every other edit the user made (an extra keyword, a tightened
        setting) survives to every image rather than just the first. Never
        set together with image0_raw_input -- callers pass at most one of
        the two, keyed on which master task this is (pes_1d vs interp_pes;
        see app/agent/tools.py's _finish_submission).

        owner_user_id is recorded for the MASTER only, immediately after
        its own spec/status become visible below -- same SEC-07 reasoning
        as submit()'s own owner_user_id handling. Per-image sub-jobs are
        never individually recorded in ownership_index (they're not
        independently reachable -- see server/routes/jobs.py, only
        visible nested under their already-owner-checked master); the
        self.submit(sub_spec) calls ScanOrchestrator makes on this
        master's behalf therefore pass no owner, relying on
        _queue_owner's parent-lookup fallback (above) to still land each
        sub-job in the master's owner's own fair-scheduler queue.
        """
        job_dir = master_spec.job_dir()
        if image0_raw_input is not None:
            master_spec.params = {**master_spec.params, "_image0_raw_input": image0_raw_input}
        if input_template is not None:
            master_spec.params = {**master_spec.params, "_input_template": input_template}
        (job_dir / "spec.json").write_text(json.dumps(master_spec.to_dict(), indent=2))
        write_status(master_spec.job_id, "running", f"submitting {len(images)} images")
        if owner_user_id:
            from app.auth.models import record_ownership
            record_ownership("job", master_spec.job_id, owner_user_id)

        path_xyz = _write_path_xyz(job_dir, images)
        n = len(images)
        from app.chemistry.jobs.dispatch import resolve_runner
        scan_job_type, _ = resolve_runner("single_point", "gs", master_spec.method)
        summary = {
            "scan_job_type": scan_job_type,
            "engine": master_spec.engine,
            "coordinate": coordinate_label,
            "coordinate_values": [float(v) for v in coordinate_values],
            "n_points": n,
            "energies_hartree": [None] * n,
            "relative_energies_eV": [None] * n,
            "failed_images": [],
        }
        write_result(JobResult(master_spec.job_id, "running", summary=summary, artifacts={"path_xyz": path_xyz}))

        # Dispatches the initial wave through ScanOrchestrator's own
        # _dispatch_more rather than a separate loop here -- same
        # reasoning submit_ensemble's own initial-wave call already
        # established below: two independent "how many are dispatched,
        # dispatch the rest" implementations is exactly how
        # EnsembleOrchestrator used to double-dispatch a sample (see its
        # dispatch_lock docstring). Routing the initial wave through the
        # one function that ever decides this keeps scan sub-jobs from
        # being able to repeat that bug.
        from app.chemistry.jobs.scan_orchestrator import get_scan_orchestrator
        get_scan_orchestrator()._dispatch_more(master_spec.job_id, master_spec.to_dict(), n)
        return master_spec.job_id

    def submit_ensemble(
        self, master_spec: JobSpec, samples: list[dict], diagnostics: dict, owner_user_id: Optional[str] = None,
    ) -> str:
        """Submits a wigner_ensemble "master" job -- mirrors submit_scan's
        wave-dispatch shape closely (writes the master's own spec/status/
        result immediately, with every sampled geometry already rendered
        to disk as artifacts['ensemble_xyz'] so it's downloadable the
        instant this call returns; dispatches only an initial wave, up to
        app.config.MASTER_MAX_IN_FLIGHT, rather than submitting every
        sub-job up front). At up to 500 samples (app/agent/tools.py's
        _MAX_ENSEMBLE_SAMPLES, raised from 250 in Phase 8), submitting
        them all up front inside this one blocking
        call would run enforce_quota()'s disk-size walk once per sub-job
        and could let quota eviction reap the ensemble's own earliest
        members before it finishes -- this is in fact what first motivated
        wave-dispatch here, before P4.3 generalized the same pattern to
        pes_1d/interp_pes too (see submit_scan's own docstring).
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
        checked master), so the self.submit(sub_spec) calls inside
        EnsembleOrchestrator's own dispatch (see below) pass no owner."""
        job_dir = master_spec.job_dir()
        (job_dir / "spec.json").write_text(json.dumps(master_spec.to_dict(), indent=2))
        n_samples = len(samples)
        write_status(master_spec.job_id, "running", f"submitting an initial wave of samples (0 of {n_samples})")
        if owner_user_id:
            from app.auth.models import record_ownership
            record_ownership("job", master_spec.job_id, owner_user_id)

        ensemble_xyz = _write_path_xyz(job_dir, samples, filename="ensemble.xyz")
        from app.chemistry.jobs.dispatch import resolve_runner
        scan_job_type, _ = resolve_runner("single_point", "ee", master_spec.method)
        summary = {
            "scan_job_type": scan_job_type,
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

        # Dispatches the initial wave through EnsembleOrchestrator's own
        # _dispatch_more rather than a separate loop here -- two independent
        # "how many are dispatched, dispatch the rest" implementations is
        # exactly how this used to double-dispatch: the master becomes
        # visible as "running" (write_result above) before this point, so
        # EnsembleOrchestrator's poll thread can already be calling
        # _dispatch_more concurrently with whatever runs next. A lock alone
        # does not fix that if the two sides compute "which indices to send"
        # differently -- _dispatch_more re-reads sub_job_ids_of under its
        # own lock and dispatches only what's actually missing, so calling
        # it here (instead of a second, blind range(wave_size) loop) makes
        # the initial wave and every later top-up the same code path, with
        # no way for them to duplicate an index between them.
        from app.chemistry.jobs.ensemble_orchestrator import get_ensemble_orchestrator
        get_ensemble_orchestrator()._dispatch_more(master_spec.job_id, master_spec.to_dict(), summary)
        n_dispatched = len(sub_job_ids_of(master_spec.job_id))
        summary["n_dispatched"] = n_dispatched
        write_status(master_spec.job_id, "running", f"{n_dispatched} of {n_samples} samples dispatched")
        write_result(JobResult(master_spec.job_id, "running", summary=summary, artifacts={"ensemble_xyz": ensemble_xyz}))
        return master_spec.job_id

    def submit_batch(
        self, master_spec: JobSpec, geometries: list[dict],
        image0_raw_input: Optional[str] = None, owner_user_id: Optional[str] = None,
    ) -> str:
        """Submits a `batch` "master" job (P7.4): one single_point/gs
        child per geometry in `geometries` (read from an existing
        geometry_set job -- see app/agent/tools.py's
        _build_batch_spec_or_error). Mirrors submit_scan's wave-dispatch
        shape closely: writes the master's own spec/status/result
        immediately (every geometry already rendered to disk as
        artifacts['path_xyz']), dispatches only an initial wave (up to
        app.config.MASTER_MAX_IN_FLIGHT), and
        app/chemistry/jobs/batch_orchestrator.py tops up the rest as
        earlier children go terminal. Unlike submit_scan/submit_ensemble
        there is no energy/spectrum aggregation to do once every child is
        terminal -- a batch's children are independent, unordered jobs,
        not points along one path or samples pooled into one spectrum --
        so the orchestrator's own "aggregation" step is just a completion
        count.

        owner_user_id is recorded for the MASTER only, same SEC-07
        reasoning as submit_scan's own owner_user_id handling -- per-
        child sub-jobs are never individually recorded in
        ownership_index (only visible nested under their already-owner-
        checked master)."""
        job_dir = master_spec.job_dir()
        if image0_raw_input is not None:
            master_spec.params = {**master_spec.params, "_image0_raw_input": image0_raw_input}
        (job_dir / "spec.json").write_text(json.dumps(master_spec.to_dict(), indent=2))
        n = len(geometries)
        write_status(master_spec.job_id, "running", f"submitting {n} jobs")
        if owner_user_id:
            from app.auth.models import record_ownership
            record_ownership("job", master_spec.job_id, owner_user_id)

        path_xyz = _write_path_xyz(job_dir, geometries)
        summary = {"engine": master_spec.engine, "n_children": n, "n_dispatched": 0, "n_complete": 0}
        write_result(JobResult(master_spec.job_id, "running", summary=summary, artifacts={"path_xyz": path_xyz}))

        # Initial wave through BatchOrchestrator's own _dispatch_more,
        # same reasoning submit_scan/submit_ensemble already established --
        # one function ever decides "which indices are missing, dispatch
        # them", so this can never double-dispatch a child the way two
        # independent loops once did (see ensemble_orchestrator.py's own
        # dispatch_lock docstring for that history).
        from app.chemistry.jobs.batch_orchestrator import get_batch_orchestrator
        get_batch_orchestrator()._dispatch_more(master_spec.job_id, master_spec.to_dict(), n)
        return master_spec.job_id

    def submit_geometry_set(
        self, frames: list[dict], owner_user_id: Optional[str] = None, label: str = "",
    ) -> str:
        """Materializes an uploaded 3+-frame xyz file (Phase 3's attach
        semantics) as a genuinely terminal `geometry_set` job -- unlike
        `submit_scan`/`submit_ensemble`, there is no compute to run and no
        sub-job to dispatch, so this writes spec/status/result once and
        returns; it never touches `self._executor` or `self.submit()` at
        all. `task="geometry_set"` carries no `method`/`engine` of its own
        (both empty strings, the same "no level of theory" convention
        `task="blind"` already uses -- see JobSpec.method's own docstring)
        since `app/chemistry/jobs/dispatch.py::resolve_runner` has no entry
        for this task and is never consulted for it (no worker `main()`
        ever runs against a `geometry_set` spec).

        Written `status="completed"` immediately, not "running": a master
        with sub-jobs still in flight is legitimately "running" until they
        finish, but a `geometry_set` has none -- `app/chemistry/jobs/
        quota.py`'s eviction only ever treats a TERMINAL job as
        size-cacheable/evictable (see its own `_TERMINAL_STATUSES`), so
        writing "running" here would leave this job walked on every quota
        check and never evictable, forever.

        `frames` is `[{"symbols": [...], "coords": [[x,y,z], ...], "name":
        str}, ...]`, the same shape `_write_path_xyz` already expects (one
        dict per `app.chemistry.geometry_upload.GeometryFrame.to_dict()`).

        `label`, if given, is written into meta.json's mutable `label`
        immediately -- `spec.label`/`JobSpec.label` itself is read by
        nothing outside the `blind` task's own submit path (see
        app/agent/tools.py's `approved_spec.label` handling), so setting it
        on the `JobSpec` alone would silently do nothing for display; a job
        list/drawer/download-filename all resolve a job's name through
        `naming.py::resolve_job_label`, which checks meta.json first."""
        job_id = uuid.uuid4().hex[:12]
        spec = JobSpec(method="", engine="", molecule={}, task="geometry_set", job_id=job_id)
        job_dir = spec.job_dir()
        (job_dir / "spec.json").write_text(json.dumps(spec.to_dict(), indent=2))
        if label:
            write_meta(job_id, {"label": label})
        if owner_user_id:
            from app.auth.models import record_ownership
            record_ownership("job", job_id, owner_user_id)

        path_xyz = _write_path_xyz(job_dir, frames)
        n = len(frames)
        summary = {"n_geometries": n, "frame_names": [f.get("name", f"frame {i}") for i, f in enumerate(frames)]}
        write_status(job_id, "completed", f"{n} geometries")
        write_result(JobResult(job_id, "completed", summary=summary, artifacts={"path_xyz": path_xyz}))
        return job_id

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

        A master job (pes_1d/interp_pes/wigner_spectra -- see is_master_spec) has
        no process of its own to kill (see submit_scan/submit_ensemble) --
        cancelling one instead cancels every still-pending/running sub-job
        (each a normal cancel() call, recursively) and marks the master
        itself "cancelled" directly."""
        spec = read_spec(job_id)
        if is_master_spec(spec):
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
        # Best-effort removal from the scheduler's own queue -- a no-op if
        # the dispatcher already popped this job (it's a live proc/orphan
        # by then, not this branch) or it was never queued at all. The
        # self._cancelled guard above is what actually prevents a job the
        # dispatcher popped a moment before this ran from being spawned
        # anyway (checked at the top of _run_inner); this dequeue just
        # keeps it from sitting visibly "pending" in a queue nothing will
        # ever admit.
        self._scheduler.dequeue(job_id)
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
            # Not started yet -- still sitting in the scheduler's own queue
            # (dequeued just above) or about to be admitted. Write the
            # cancelled status immediately rather than waiting for the
            # scheduler to even consider it (which could be delayed
            # arbitrarily long behind a saturated cap); _run_inner's own
            # pre-spawn cancellation check re-writes the same status
            # idempotently if it does run, so this is safe even if the
            # dispatcher had already popped this job and called _on_admit
            # concurrently with this method (worst case is a harmless
            # "cancelled" -> briefly "running" -> "cancelled again once the
            # just-spawned process is killed" flicker in the sub-millisecond
            # window between this write and _run_inner's next check).
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
            cleanup_scratch_files(spec.job_id, spec.engine, spec.task)
            # Drop this job's Future. Nothing in the app reads _futures --
            # it was write-only, so on a backend that stays up for weeks it
            # grew by one completed Future per job forever and nothing ever
            # released them. Discarded here rather than in _run_inner
            # because this `finally` is the one path every outcome passes
            # through, cancellation included.
            with self._lock:
                self._futures.pop(spec.job_id, None)
            # This job going terminal may have just freed a cap/headroom
            # slot another queued job was blocked on -- nudge the
            # dispatcher to reconsider now rather than wait out its own
            # up-to-1s idle poll (harmless either way; jobs here run for
            # minutes to hours, so the difference is imperceptible, but
            # free to make prompt).
            self._scheduler.wake()

    def _run_inner(self, spec: JobSpec) -> None:
        """Spawns spec's worker subprocess and blocks until it exits.
        Assumes admission has ALREADY happened -- the scheduler's
        dispatcher thread only calls _on_admit (which submits this method
        to self._executor) once its own resource-headroom and
        concurrent-jobs-cap checks have passed, so the only thing left to
        check here is the narrow race where cancel() ran between that
        admission decision and this method actually starting."""
        with self._lock:
            if spec.job_id in self._cancelled:
                self._cancelled.discard(spec.job_id)
                write_status(spec.job_id, "cancelled", "cancelled before it started")
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
