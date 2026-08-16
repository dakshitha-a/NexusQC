"""SEC-08: DELETE /api/admin/users/{id} (server/routes/admin.py) deletes
the users row (cascading sessions/ownership_index via FK) but its own
docstring admits it does NOT reach into data/jobs/ or data/uploads/ to
remove the underlying files. Once the ownership_index row is gone, the
job becomes "unowned" -- and app/auth/ownership.py's documented policy
treats an unowned resource as accessible to EVERYONE, not to no one.

Proof: user A creates a job, admin deletes user A's account, then a
completely unrelated user C requests that now-owner-less job. Expected-if-
fixed: denied (files were cleaned up, or ownership was preserved/
reassigned). Confirmed-bug: user C can read it.
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


def _submit_job(owner_user_id: str) -> str:
    code = f'''
import time
from app.chemistry.molecule import resolve_molecule
from app.chemistry.jobs.base import JobSpec, get_job_manager
from app.auth.models import record_ownership

m = resolve_molecule("water")
spec = JobSpec(method="single_point", engine="pyscf", molecule=m.to_dict(), params={{"method": "hf", "basis": "sto-3g"}})
job_id = get_job_manager().submit(spec)
for _ in range(60):
    status = get_job_manager().status(job_id)
    if status["status"] in ("completed", "failed"):
        break
    time.sleep(1)
record_ownership("job", job_id, "{owner_user_id}")
print(job_id)
'''
    return _exec_api(code)


def main() -> None:
    admin = admin_client()
    token_a = mint_invite(admin)
    token_c = mint_invite(admin)
    client_a, user_a = register(token_a)
    client_c, user_c = register(token_c)

    job_id = _submit_job(user_a["id"])
    print(f"created job {job_id}, owned by user A")

    r_before = client_c.get(f"/api/jobs/{job_id}")
    check("unrelated user C is denied A's job BEFORE A is deleted", r_before.status_code == 404, str(r_before.status_code))

    r_delete = admin.delete(f"/api/admin/users/{user_a['id']}")
    check("admin successfully deletes user A", r_delete.status_code == 200, f"{r_delete.status_code} {r_delete.text[:200]}")
    print(f"delete response: {r_delete.json()}")

    r_after = client_c.get(f"/api/jobs/{job_id}")
    check(
        "unrelated user C is STILL denied A's job after A's account is deleted",
        r_after.status_code == 404,
        f"got {r_after.status_code} -- 200 confirms the job became globally-readable 'unowned' orphan "
        "(the ownership_index row was cascade-deleted, but the job files were not)",
    )

    r_artifact = client_c.get(f"/api/jobs/{job_id}/artifacts/nonexistent_key")
    print(f"(for context) artifact route after delete: {r_artifact.status_code} -- "
          "note SEC-06 already shows this route has no ownership check regardless of user-delete")

    cleanup_user(admin, user_c["id"])
    summary(exit_on_failure=False)


if __name__ == "__main__":
    main()
