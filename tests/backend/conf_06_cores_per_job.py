"""CONF-06: "Cores per calculation" set from the admin console reaches the
calculation.

The number of cores one job runs on used to be QC_AGENT_N_CORES, read once
at process start, and read AGAIN by each job's worker at its own import. So a
setting could not simply be stored somewhere: the worker would have reset
itself to the .env value. This checks each hop from the console to the job:

  1. PATCH cores_per_job=2 is accepted, and GET reports 2 with source
     "setting". Values the host cannot supply (0, one above the ceiling),
     a fraction, a string and a boolean are each refused with a 400 that
     names the ceiling.
  2. One benzene HF/cc-pVDZ PySCF job, submitted inside the api container
     after the change, records cores=2 in its meta.json. While it runs,
     its worker's environment (read from /proc/<pid>/environ in the
     container) carries QC_AGENT_N_CORES=2, OMP_NUM_THREADS=2 and the
     worker marker. Pass means all three are exactly as stated. If the job
     finishes before the worker can be read, that sub-check is reported
     as skipped, not passed.
  3. Inside that worker environment PySCF really runs 2 threads: a
     fresh interpreter started with the recorded environment imports
     pyscf_runner and reports lib.num_threads() == 2. This is the step
     that failed silently before, when the worker's own import reset it.
  4. In the api process, an ORCA input is written with '%pal nprocs 2 end'
     and a pasted input asking for 16 ranks is held to 2.
  5. PATCH null clears the override. GET then reports the .env default
     with source "env". The setting is restored to whatever it was
     before the test, and the job is deleted.

Needs the docker-compose stack.

Run:  PYTHONPATH=$PWD python3 tests/backend/conf_06_cores_per_job.py
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from fixtures import admin_client, require_jobs_quiet, check, cleanup_jobs, skip, summary  # noqa: E402

REPO = Path(__file__).resolve().parent.parent.parent
KEY = "cores_per_job"


def _exec_api(code: str) -> str:
    proc = subprocess.run(
        ["docker", "compose", "exec", "-T", "api", "python", "-c", code],
        cwd=str(REPO), capture_output=True, text=True, timeout=240,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"in-container exec failed: {proc.stderr[-800:]}")
    return proc.stdout.strip()


# Submits the job and watches its worker from inside the container, where
# the worker's pid is meaningful. Prints one JSON line.
SUBMIT_AND_WATCH = r'''
import json, threading, time
from pathlib import Path
from app.chemistry.molecule import resolve_molecule
from app.chemistry.jobs.base import JobSpec, get_job_manager
from app.config import JOBS_DIR

# submit() returns only once the job is done when called from a process like
# this one, so the worker is watched from a thread started first. It looks
# for any job directory that appears, reads its worker pid from meta.json,
# and reads that process's environment while it is alive. Benzene
# HF/cc-pVDZ runs for a few seconds, which is ample at a 20 ms poll.
existing = {p.name for p in JOBS_DIR.iterdir()}
found = {}
stop = threading.Event()

def watch():
    while not stop.is_set() and "env" not in found:
        for d in JOBS_DIR.iterdir():
            if d.name in existing:
                continue
            try:
                pid = json.loads((d / "meta.json").read_text()).get("worker_pid")
                raw = Path(f"/proc/{pid}/environ").read_bytes().split(b"\0") if pid else None
            except Exception:
                raw = None
            if raw:
                found["env"] = dict(kv.decode().split("=", 1) for kv in raw if b"=" in kv)
        time.sleep(0.02)

watcher = threading.Thread(target=watch, daemon=True)
watcher.start()
m = resolve_molecule("benzene")
spec = JobSpec(method="hf", engine="pyscf", task="single_point", subtype="gs",
               molecule=m.to_dict(), params={"basis": "cc-pvdz"}, label="qatest conf_06 cores")
job_id = get_job_manager().submit(spec)
deadline = time.time() + 300
while get_job_manager().status(job_id)["status"] not in ("completed", "failed", "cancelled") and time.time() < deadline:
    time.sleep(0.2)
stop.set()
meta = json.loads((JOBS_DIR / job_id / "meta.json").read_text())
env = found.get("env")
keep = ("QC_AGENT_N_CORES", "OMP_NUM_THREADS", "MKL_NUM_THREADS", "QC_AGENT_JOB_WORKER")
print(json.dumps({"job_id": job_id, "cores": meta.get("cores"),
                  "status": get_job_manager().status(job_id)["status"],
                  "env": {k: env.get(k) for k in keep} if env else None}))
'''

# A fresh interpreter with the environment a worker is launched with, asked
# how many threads PySCF settled on after pyscf_runner's own import.
PYSCF_THREADS = r'''
import subprocess, sys, os
env = dict(os.environ, QC_AGENT_N_CORES="2", OMP_NUM_THREADS="2", MKL_NUM_THREADS="2",
           OPENBLAS_NUM_THREADS="2", QC_AGENT_JOB_WORKER="1")
out = subprocess.run([sys.executable, "-c",
    "import app.chemistry.jobs.pyscf_runner; from pyscf import lib; print(lib.num_threads())"],
    env=env, capture_output=True, text=True, timeout=120)
print(out.stdout.strip().splitlines()[-1] if out.stdout.strip() else "ERR " + out.stderr[-300:])
'''

ORCA_INPUTS = r'''
from app.chemistry.jobs.orca_runner import _pal_block, _cap_parallelism
print(_pal_block("")[0])
print(_cap_parallelism("%pal nprocs 16 end\n! HF sto-3g").splitlines()[0])
'''


def main() -> None:
    admin = admin_client()
    require_jobs_quiet(admin, "conf_06 cores per calculation", include_open_apps=True)
    before = admin.get("/api/admin/config").json()
    original = before.get(KEY) if before.get("cores_per_job_source") == "setting" else None
    ceiling = before.get("cores_per_job_ceiling")
    default = before.get("cores_per_job_default")
    check("GET config reports cores_per_job, its default and its ceiling",
          all(isinstance(before.get(k), int) for k in (KEY, "cores_per_job_default", "cores_per_job_ceiling")),
          json.dumps({k: before.get(k) for k in (KEY, "cores_per_job_default", "cores_per_job_ceiling",
                                                 "cores_per_job_source")}))
    job_ids: list[str] = []
    try:
        for bad in (0, ceiling + 1, 2.5, "2", True):
            r = admin.patch("/api/admin/config", json={"key": KEY, "value": bad})
            check(f"cores_per_job={bad!r} is refused", r.status_code == 400 and str(ceiling) in r.text,
                  f"{r.status_code} {r.text[:120]}")

        r = admin.patch("/api/admin/config", json={"key": KEY, "value": 2})
        check("cores_per_job=2 is accepted", r.status_code == 200, f"{r.status_code} {r.text[:120]}")
        now = admin.get("/api/admin/config").json()
        check("GET reports 2, set from the console", now.get(KEY) == 2 and now.get("cores_per_job_source") == "setting",
              json.dumps({KEY: now.get(KEY), "source": now.get("cores_per_job_source")}))

        watched = json.loads(_exec_api(SUBMIT_AND_WATCH).splitlines()[-1])
        job_ids.append(watched["job_id"])
        check("the job ran", watched["status"] == "completed", watched["status"])
        check("its meta.json records the 2 cores it was launched with", watched["cores"] == 2, str(watched["cores"]))
        env = watched["env"]
        if env is None:
            skip("the worker's environment carries the width", "the job finished before its worker could be read")
        else:
            check("the worker's environment carries the width",
                  env.get("QC_AGENT_N_CORES") == "2" and env.get("OMP_NUM_THREADS") == "2"
                  and env.get("QC_AGENT_JOB_WORKER") == "1", json.dumps(env))

        threads = _exec_api(PYSCF_THREADS).splitlines()[-1]
        check("a worker started that way runs PySCF on 2 threads after its own import", threads == "2", threads)

        pal, capped = _exec_api(ORCA_INPUTS).splitlines()[-2:]
        check("an ORCA input is written for 2 ranks", pal == "%pal nprocs 2 end", pal)
        check("a pasted ORCA input asking for 16 ranks is held to 2", capped == "%pal nprocs 2 end", capped)

        r = admin.patch("/api/admin/config", json={"key": KEY, "value": None})
        cleared = admin.get("/api/admin/config").json()
        check("PATCH null clears the override back to the .env default",
              r.status_code == 200 and cleared.get(KEY) == default and cleared.get("cores_per_job_source") == "env",
              json.dumps({KEY: cleared.get(KEY), "source": cleared.get("cores_per_job_source")}))
    finally:
        admin.patch("/api/admin/config", json={"key": KEY, "value": original})
        if job_ids:
            cleanup_jobs(admin, job_ids)
    summary()


if __name__ == "__main__":
    main()
