"""Concurrency+admin-config interaction test (folded into the perf group
per the plan): confirms the admin-configurable max_concurrent_jobs_per_user
cap (app/chemistry/jobs/base.py's _concurrent_jobs_block_reason) is
actually enforced in real time against a live admin PATCH, not just
accepted and ignored.

Sets the cap to 1 via PATCH /api/admin/config, submits two jobs pre-owned
by the same user (ownership recorded before submission specifically to
test the cap's own logic cleanly, unlike the real approve_job flow's
after-the-fact recording -- see SEC-07 for that separate concern), and
confirms the second job's status.json reports the per-user-cap pending
reason while the first is still running. Restores the original cap
afterward regardless of outcome.
"""
from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from fixtures import admin_client, check, cleanup_user, mint_invite, register, summary  # noqa: E402

COMPOSE_DIR = Path(__file__).resolve().parent.parent.parent


def _exec_api(code: str) -> str:
    proc = subprocess.run(
        ["docker", "compose", "exec", "-T", "api", "python", "-c", code],
        cwd=str(COMPOSE_DIR), capture_output=True, text=True, timeout=60,
    )
    if proc.returncode != 0:
        print(proc.stderr, file=sys.stderr)
        raise RuntimeError(f"in-container exec failed: {proc.stderr[:500]}")
    return proc.stdout.strip()


def _submit_owned_job(owner_user_id: str, molecule: str) -> str:
    code = f'''
from app.chemistry.molecule import resolve_molecule
from app.chemistry.jobs.base import JobSpec, get_job_manager
from app.auth.models import record_ownership

m = resolve_molecule("{molecule}")
spec = JobSpec(method="frequency", engine="pyscf", molecule=m.to_dict(), params={{"method": "hf", "basis": "6-31g"}})
job_id = get_job_manager().submit(spec)
record_ownership("job", job_id, "{owner_user_id}")
print(job_id)
'''
    return _exec_api(code)


def _status(job_id: str) -> dict:
    import json
    return json.loads(_exec_api(
        f'import json; from app.chemistry.jobs.base import get_job_manager; print(json.dumps(get_job_manager().status("{job_id}")))'
    ))


def main() -> None:
    admin = admin_client()
    token = mint_invite(admin)
    _c, user = register(token)

    r_cfg = admin.get("/api/admin/config")
    original_cap = r_cfg.json()["max_concurrent_jobs_per_user"]

    try:
        r_patch = admin.patch("/api/admin/config", json={"key": "max_concurrent_jobs_per_user", "value": 1})
        check("admin sets max_concurrent_jobs_per_user=1", r_patch.status_code == 200, str(r_patch.status_code))

        job1 = _submit_owned_job(user["id"], "water")
        job2 = _submit_owned_job(user["id"], "ammonia")
        print(f"submitted job1={job1}, job2={job2}, both owned by the same user")

        # Give the pool a couple of poll ticks (~1s each per
        # _wait_for_resources' own pacing) to reach a stable pending/running split.
        time.sleep(3)
        s1, s2 = _status(job1), _status(job2)
        print(f"job1 status: {s1}")
        print(f"job2 status: {s2}")

        one_running_one_pending = {s1["status"], s2["status"]} <= {"running", "pending", "completed"} and (
            "pending" in (s1["status"], s2["status"])
        )
        check(
            "with the per-user cap set to 1, the second job is held pending while the first runs",
            one_running_one_pending,
            f"job1={s1['status']!r} job2={s2['status']!r} -- if both went straight to running, "
            "the per-user cap was not enforced",
        )
        pending_msg = s2["message"] if s2["status"] == "pending" else s1["message"]
        check(
            "the pending job's status message cites the per-user cap, not just generic CPU/memory headroom",
            "running" in pending_msg and ("slot" in pending_msg or "per_user" in pending_msg or "you have" in pending_msg),
            pending_msg,
        )

        # Let both finish before cleanup so no job is left running when we
        # restore the cap / delete the user.
        for _ in range(120):
            s1, s2 = _status(job1), _status(job2)
            if s1["status"] in ("completed", "failed") and s2["status"] in ("completed", "failed"):
                break
            time.sleep(1)
        print(f"final: job1={s1['status']} job2={s2['status']}")
    finally:
        admin.patch("/api/admin/config", json={"key": "max_concurrent_jobs_per_user", "value": original_cap})
        cleanup_user(admin, user["id"])

    summary(exit_on_failure=False)


if __name__ == "__main__":
    main()
