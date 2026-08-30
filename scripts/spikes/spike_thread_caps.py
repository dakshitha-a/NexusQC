#!/usr/bin/env python3
"""Verification spike: does a job really run on N_CORES cores?

    PYTHONPATH=$PWD python3 scripts/spikes/spike_thread_caps.py [engine ...]

Every one of these libraries -- libgomp, MKL, OpenBLAS, BAGEL's own task
scheduler -- uses every core on the machine when its environment variable is
unset, and none of them can be told otherwise once the shared library has
loaded. So "the job runs on four cores" is a claim about a subprocess's
environment, and the only way to check it is to look at a real job while it
runs. Reading the code is not enough: the line this script exists to defend
against was a plausible-looking `os.environ.setdefault("OMP_NUM_THREADS", ...)`
that ran after `import pyscf` and therefore did nothing at all, while
`pyscf.lib.num_threads()` quietly reported 255.

For each engine this submits one small real job through JobManager -- the same
path a user's job takes, which is the point -- then reports:

  * the thread-count variables the worker process was actually created with,
  * the peak number of threads across the worker's whole process group,
  * for BAGEL, the "using N threads per process" line it prints itself,
  * for ORCA, the MPI rank count it reports and the '%pal' line that produced
    it (ORCA parallelises by MPI, so its per-rank thread count is 1 and its
    width comes from '%pal nprocs' instead).

The peak thread count is a ceiling, not an equality: a healthy PySCF job shows
roughly N_CORES plus a handful, since libgomp's team, OpenBLAS's pool and the
main thread are counted together. What it catches is the failure this exists
for, which is not subtle -- an uncapped job shows hundreds.

Jobs created here are deleted before the script exits, including on failure,
so a run leaves the job list exactly as it found it.
"""
from __future__ import annotations

import json
import os
import shutil
import sys
import threading
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO))

from app.chemistry.jobs.base import JOBS_DIR, JobSpec, get_job_manager, read_status  # noqa: E402
from app.chemistry.molecule import resolve_molecule  # noqa: E402
from app.config import BAGEL_BIN, N_CORES, ORCA_BIN, engine_thread_env  # noqa: E402

# One small real job per engine, sized so the worker lives for a few seconds:
# the whole measurement is taken from /proc while it runs, and a job that
# finishes in 200 ms cannot be observed at all. These are seconds on this host.
JOB = {
    "pyscf": ("benzene", "6-31G*"),
    "orca": ("water", "6-31G"),
    "bagel": ("water", "6-31G"),
}

# A job whose thread pools are capped shows N_CORES plus the main thread plus
# whatever second pool the engine keeps warm. Hundreds means uncapped, which is
# the only thing this bound needs to separate.
THREAD_CEILING = 4 * N_CORES + 8


def _probe(engine: str) -> bool:
    name, basis = JOB[engine]
    mol = resolve_molecule(name)
    spec = JobSpec(method="hf", engine=engine, task="single_point", subtype="gs",
                   molecule=mol.to_dict(), params={"method": "hf", "basis": basis})
    # The sampler starts BEFORE submit() rather than after it. submit() is not
    # the quick enqueue it looks like -- it runs enforce_quota() inline, which
    # is real disk and Postgres work and can outlast a small job, so by the time
    # it returns the worker has often already exited and there is nothing left
    # in /proc to look at. JobSpec assigns its own job_id at construction, so
    # the watcher has everything it needs before the job exists.
    job_dir = Path(JOBS_DIR) / spec.job_id
    result: list[bool] = []
    watcher = threading.Thread(
        target=lambda: result.append(_watch(engine, spec.job_id, job_dir)))
    try:
        watcher.start()
        job_id = get_job_manager().submit(spec)
        print(f"  job {job_id} submitted")
        watcher.join()
        return bool(result and result[0])
    finally:
        # This script leaves the job list as it found it, whatever happened --
        # a spike's own jobs are clutter in someone's Job Manager otherwise.
        shutil.rmtree(job_dir, ignore_errors=True)


def _watch(engine: str, job_id: str, job_dir: Path) -> bool:
    """Samples the running job and reports whether it stayed inside its budget."""
    expected = engine_thread_env(engine)
    started = time.time()
    # The job does not exist on disk yet, and read_status returns None (not an
    # empty dict) for a job with no status file, which is why the read below is
    # guarded rather than chained straight onto .get().
    peak_threads = 0
    worker_env: dict[str, str] = {}
    status = None
    while True:
        status = (read_status(job_id) or {}).get("status")
        pid = None
        try:
            pid = json.loads((job_dir / "meta.json").read_text()).get("worker_pid")
        except (OSError, ValueError):
            pass
        if pid:
            peak_threads = max(peak_threads, _process_group_threads(pid))
            worker_env = _thread_vars(pid) or worker_env
        if status in ("completed", "failed", "cancelled"):
            break
        if time.time() - started > 900:
            print("  [FAIL] job never reached a terminal status")
            return False
        time.sleep(0.05)

    if status != "completed":
        error = ""
        try:
            error = str(json.loads((job_dir / "result.json").read_text()).get("error"))
        except (OSError, ValueError):
            pass
        print(f"  [FAIL] job {status}: {error[:300]}")
        return False

    ok = True
    if not worker_env:
        # Nothing was read from /proc, so nothing was verified. Reported as a
        # failure rather than a pass: an unobserved job is not a capped one.
        print("  [FAIL] the job finished before it could be sampled -- nothing "
              "was verified. Give this engine a longer job in JOB above.")
        return False
    for var, want in expected.items():
        got = worker_env.get(var)
        if got != want:
            print(f"  [FAIL] worker was created with {var}={got!r}, expected {want!r}")
            ok = False
    print(f"  [PASS] worker environment: "
          f"{' '.join(f'{k}={v}' for k, v in sorted(worker_env.items()))}")

    if peak_threads > THREAD_CEILING:
        print(f"  [FAIL] peak {peak_threads} threads in the worker's process group, "
              f"above the ceiling of {THREAD_CEILING} for N_CORES={N_CORES}")
        ok = False
    else:
        print(f"  [PASS] peak {peak_threads} threads in the worker's process group "
              f"(ceiling {THREAD_CEILING})")

    return _engine_specific(engine, job_dir) and ok


def _engine_specific(engine: str, job_dir: Path) -> bool:
    """The engine's own account of how wide it ran, where it gives one."""
    if engine == "bagel":
        line = _first_matching(job_dir / "bagel.out", "threads per process")
        if not line:
            print("  [FAIL] bagel.out has no 'using N threads per process' line")
            return False
        if f"using {N_CORES} threads" not in line:
            print(f"  [FAIL] BAGEL reports '{line}', expected {N_CORES} threads")
            return False
        print(f"  [PASS] BAGEL reports '{line}'")
        return True
    if engine == "orca":
        pal = _first_matching(job_dir / "input.inp", "%pal")
        ranks = _first_matching(job_dir / "output.out", "parallel MPI-processes")
        if not ranks:
            print("  [FAIL] output.out never reported an MPI process count")
            return False
        if f"with {N_CORES} parallel" not in ranks:
            print(f"  [FAIL] ORCA reports '{ranks}', expected {N_CORES} ranks")
            return False
        print(f"  [PASS] input carries '{pal}'; ORCA reports '{ranks}'")
        return True
    return True


def _first_matching(path: Path, needle: str) -> str:
    try:
        for line in path.read_text(errors="replace").splitlines():
            if needle in line:
                return line.strip().strip("*").strip()
    except OSError:
        pass
    return ""


def _process_group_threads(pgid: int) -> int:
    """Threads across every process in the worker's group.

    start_new_session=True puts the worker and everything it spawns -- ORCA's
    MPI ranks, BAGEL's bash wrapper -- in one group, so this counts the whole
    job rather than only the Python process at its root.
    """
    total = 0
    for entry in os.listdir("/proc"):
        if not entry.isdigit():
            continue
        try:
            if os.getpgid(int(entry)) != pgid:
                continue
            total += len(os.listdir(f"/proc/{entry}/task"))
        except (OSError, ProcessLookupError, PermissionError):
            continue
    return total


def _thread_vars(pid: int) -> dict[str, str]:
    try:
        raw = Path(f"/proc/{pid}/environ").read_text(errors="replace")
    except OSError:
        return {}
    pairs = (item.split("=", 1) for item in raw.split("\0") if "=" in item)
    return {k: v for k, v in pairs if k.endswith("_NUM_THREADS")}


def main() -> int:
    available = {"pyscf": True,
                 "orca": os.path.exists(ORCA_BIN),
                 "bagel": os.path.exists(BAGEL_BIN)}
    wanted = sys.argv[1:] or list(available)
    failures = 0
    for engine in wanted:
        print(f"\n=== {engine} (N_CORES={N_CORES})")
        if engine not in available:
            print(f"  [FAIL] unknown engine {engine!r}")
            failures += 1
            continue
        if not available[engine]:
            print("  [skip] engine not installed on this host")
            continue
        if not _probe(engine):
            failures += 1
    print(f"\n{'[FAIL]' if failures else '[PASS]'} "
          f"{len(wanted) - failures}/{len(wanted)} engines within their core budget")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
