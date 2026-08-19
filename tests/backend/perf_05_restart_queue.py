"""Startup re-enqueue of on-disk queued jobs across a server restart
(Phase 4, P4.4/P4.5).

Before this phase, a job that was still genuinely QUEUED (submitted, but
never yet admitted by the scheduler -- no worker subprocess ever spawned,
so meta.json never got a worker_pid) died silently across a backend
restart: JobManager._reconcile_orphaned_jobs' old case 3 treated "no
result, no live worker pid" as a single bucket and reported EVERY such
job as an unrecoverable failure ("the server restarted while this job was
queued/running..."), which was correct for a job whose worker really had
died, but wrong for a job that simply hadn't started yet -- there was
never anything to have died. P4.4 splits that bucket: a job with no
worker_pid at all is re-enqueued behind the fair scheduler exactly as if
freshly submitted; only a job whose worker WAS spawned and is now
unrecoverable is still reported as failed.

Forces this with the admin-configurable max_concurrent_jobs_total cap set
to 1: job1 (a genuinely slow ORCA CASSCF(4,4)/STO-3G run, same probe
perf_03/perf_04 already established takes ~15s wall-clock here) occupies
the one admission slot; job2 (a fast HF/STO-3G single point) is submitted
right behind it and is confirmed -- before the restart, not assumed --
to be sitting "pending" with no worker_pid recorded in its own meta.json,
i.e. genuinely never admitted. The api container is then restarted
(`docker compose restart api`). This test does not assert anything about
job1's own fate beyond printing it -- `docker compose restart` was
observed empirically (not assumed) to sometimes leave job1's worker
subprocess alive across the restart (case 2's orphan re-attach handles
that correctly, unchanged by this phase) and sometimes not, depending on
timing; either outcome is fine and orthogonal to what this test exists to
check. What it actually checks is job2: that it is NOT marked failed with
the "server restarted" message, and instead resumes normal scheduling and
eventually runs to completion once the freshly-started JobManager's own
_reconcile_orphaned_jobs re-enqueues it in __init__ (before its
scheduler's dispatcher thread even starts -- see that method's own
docstring on why the ordering there matters).
"""
from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from fixtures import admin_client, check, new_client, summary  # noqa: E402

COMPOSE_DIR = Path(__file__).resolve().parent.parent.parent
CASSCF_PARAMS = {"active_electrons": 4, "active_orbitals": 4, "basis": "sto-3g", "n_states": 1, "weights": [1.0]}
QUEUE_OBSERVE_TIMEOUT_SECONDS = 60
POST_RESTART_TIMEOUT_SECONDS = 60


def _exec_api(code: str, timeout: int = 90) -> str:
    proc = subprocess.run(
        ["docker", "compose", "exec", "-T", "api", "python", "-c", code],
        cwd=str(COMPOSE_DIR), capture_output=True, text=True, timeout=timeout,
    )
    if proc.returncode != 0:
        print(proc.stderr, file=sys.stderr)
        raise RuntimeError(f"in-container exec failed: {proc.stderr[:500]}")
    return proc.stdout.strip()


def _wait_healthy(timeout: float = 60.0) -> bool:
    deadline = time.time() + timeout
    c = new_client()
    while time.time() < deadline:
        try:
            r = c.get("/api/health")
            if r.status_code == 200:
                return True
        except Exception:
            pass
        time.sleep(0.5)
    return False


def main() -> None:
    admin = admin_client()
    r_cfg = admin.get("/api/admin/config")
    original_cap = r_cfg.json()["max_concurrent_jobs_total"]

    try:
        r_patch = admin.patch("/api/admin/config", json={"key": "max_concurrent_jobs_total", "value": 1})
        check("admin sets max_concurrent_jobs_total=1", r_patch.status_code == 200, str(r_patch.status_code))

        submit_code = f'''
import json, time
from app.chemistry.molecule import resolve_molecule
from app.chemistry.jobs.base import JobSpec, get_job_manager, read_meta, read_status

mgr = get_job_manager()
m = resolve_molecule("water")
job1 = mgr.submit(JobSpec(task="single_point", subtype="gs", method="casscf", engine="orca",
                           molecule=m.to_dict(), params={CASSCF_PARAMS!r}))
job2 = mgr.submit(JobSpec(task="single_point", subtype="gs", method="hf", engine="pyscf",
                           molecule=m.to_dict(), params={{"basis": "sto-3g"}}))

deadline = time.time() + {QUEUE_OBSERVE_TIMEOUT_SECONDS}
job1_running = job2_queued = False
while time.time() < deadline:
    job1_running = read_status(job1)["status"] == "running"
    s2 = read_status(job2)
    job2_queued = s2["status"] == "pending" and read_meta(job2).get("worker_pid") is None
    if job1_running and job2_queued:
        break
    time.sleep(0.3)

print(json.dumps({{
    "job1": job1, "job2": job2,
    "job1_running": job1_running, "job2_queued_no_pid": job2_queued,
    "job2_status_before_restart": read_status(job2),
}}))
'''
        out = _exec_api(submit_code)
        pre = json.loads(out.splitlines()[-1])
        job1_id, job2_id = pre["job1"], pre["job2"]
        print(f"job1={job1_id} job2={job2_id}")
        print(f"before restart: {pre}")

        check(
            "job1 (occupying the one admission slot) is genuinely running before the restart",
            pre["job1_running"], str(pre),
        )
        check(
            "job2 is confirmed genuinely queued -- pending, with no worker_pid ever recorded -- "
            "before the restart, not merely assumed",
            pre["job2_queued_no_pid"], str(pre),
        )

        print("restarting api container to force a real mid-flight admission-queue loss...")
        subprocess.run(["docker", "compose", "restart", "api"], cwd=str(COMPOSE_DIR), check=True, capture_output=True)
        check("api container became healthy again after restart", _wait_healthy())

        poll_code = f'''
import json, time
from app.chemistry.jobs.base import read_status, get_job_manager

get_job_manager()  # forces _reconcile_orphaned_jobs to run on this fresh process, same as real startup

deadline = time.time() + {POST_RESTART_TIMEOUT_SECONDS}
s2 = read_status("{job2_id}")
while time.time() < deadline and s2["status"] not in ("completed", "failed", "cancelled"):
    time.sleep(0.5)
    s2 = read_status("{job2_id}")

print(json.dumps({{"job2_final": s2, "job1_final": read_status("{job1_id}")}}))
'''
        out = _exec_api(poll_code)
        post = json.loads(out.splitlines()[-1])
        print(f"after restart: {post}")

        check(
            "job2 (never admitted before the restart) reached a real terminal outcome, not stuck pending forever",
            post["job2_final"]["status"] in ("completed", "failed"),
            str(post["job2_final"]),
        )
        check(
            "job2 was NOT reported as an unrecoverable restart casualty -- it was re-enqueued and actually ran",
            post["job2_final"]["status"] == "completed"
            and "server restarted" not in post["job2_final"]["message"],
            f"job2 final status: {post['job2_final']} -- a still-queued job should resume normally after "
            "restart, not be reported as having lost a worker it never had",
        )
        print(f"(job1, which really was running when the container died, reconciled as: {post['job1_final']})")
    finally:
        admin.patch("/api/admin/config", json={"key": "max_concurrent_jobs_total", "value": original_cap})

    summary()


if __name__ == "__main__":
    main()
