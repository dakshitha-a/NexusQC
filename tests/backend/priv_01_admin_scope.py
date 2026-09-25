"""An admin sees and touches only their own work, like everyone else.

Until 2026-09-24 app/auth/ownership.py exempted admins from ownership, so
every workspace list showed an admin all users' conversations, jobs and
projects. On the research group's deployment an admin found another
member's conversation in their own sidebar, streaming live as he typed, and
his private copy of a project they had shared with him. Admins are held to
the same boundary now, and the one thing they legitimately needed from the
old exemption, removing a particular item, has its own admin-only routes.

The setup: the test admin and a fresh test user each get a conversation and
a finished job (a water HF/STO-3G single point, seeded in-container with its
owner recorded), and the user gets a project. Then, as the admin:

  lists     GET /api/threads, /api/jobs and /api/projects show the admin's
            own items and none of the user's
  reads     the user's conversation state, its live event stream, the job,
            and the project all answer 404
  writes    renaming the user's conversation, deleting it, and deleting
            the job all answer 404 and change nothing
  admin     DELETE /api/admin/jobs/{id} and /api/admin/threads/{id} remove
            the user's job and conversation, and the user sees them gone

Everything created is removed at the end: the user's remaining items go
with the account, and the admin's through the ordinary routes.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from fixtures import admin_client, check, cleanup_jobs, cleanup_user, mint_invite, register, summary  # noqa: E402

REPO = Path(__file__).resolve().parent.parent.parent


def _exec_api(code: str) -> str:
    proc = subprocess.run(
        ["docker", "compose", "exec", "-T", "api", "python", "-c", code],
        cwd=str(REPO), capture_output=True, text=True, timeout=180,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"in-container exec failed: {proc.stderr[-800:]}")
    return proc.stdout.strip()


def seed_job(owner_user_id: str, label: str) -> str:
    code = f'''
import time
from app.chemistry.molecule import resolve_molecule
from app.chemistry.jobs.base import JobSpec, get_job_manager

m = resolve_molecule("water")
spec = JobSpec(method="hf", engine="pyscf", task="single_point", subtype="gs",
               molecule=m.to_dict(), params={{"basis": "sto-3g"}}, label={label!r})
job_id = get_job_manager().submit(spec, owner_user_id={owner_user_id!r})
for _ in range(90):
    if get_job_manager().status(job_id)["status"] in ("completed", "failed"):
        break
    time.sleep(1)
print(job_id)
'''
    return _exec_api(code).splitlines()[-1].strip()


def main() -> None:
    admin = admin_client()
    admin_id = admin.get("/api/auth/me").json()["id"]
    user_c, user = register(mint_invite(admin))
    jobs: list[str] = []
    admin_thread = None
    try:
        admin_thread = admin.post("/api/threads", json={"label": "qatest priv_01 admin"}).json()["thread_id"]
        user_thread = user_c.post("/api/threads", json={"label": "qatest priv_01 user"}).json()["thread_id"]
        admin_job = seed_job(admin_id, "qatest priv_01 admin job")
        user_job = seed_job(user["id"], "qatest priv_01 user job")
        jobs += [admin_job, user_job]
        r = user_c.post("/api/projects", json={"name": "qatest priv_01 project", "job_ids": [user_job]})
        check("the user files their job into a project", r.status_code == 200, f"{r.status_code} {r.text[:150]}")
        user_project = r.json().get("project_id")

        print("\n== lists ==")
        threads = {t["thread_id"] for t in admin.get("/api/threads").json()}
        check("the admin's conversation list has their own", admin_thread in threads)
        check("and not the user's", user_thread not in threads)
        job_ids = {j["job_id"] for j in admin.get("/api/jobs", params={"include_archived": "true"}).json()}
        check("the admin's job list has their own", admin_job in job_ids)
        check("and not the user's", user_job not in job_ids)
        projects = {p["project_id"] for p in admin.get("/api/projects").json()}
        check("the admin's project list does not have the user's", user_project not in projects)

        print("\n== reads ==")
        for what, url in [
            ("conversation state", f"/api/threads/{user_thread}/state"),
            ("live event stream", f"/api/threads/{user_thread}/events"),
            ("job", f"/api/jobs/{user_job}"),
            ("project", f"/api/projects/{user_project}"),
        ]:
            r = admin.get(url, timeout=15)
            check(f"the admin is refused the user's {what}", r.status_code == 404, f"HTTP {r.status_code}")

        print("\n== writes ==")
        r = admin.patch(f"/api/threads/{user_thread}", json={"label": "renamed by admin"})
        check("the admin cannot rename the user's conversation", r.status_code == 404, f"HTTP {r.status_code}")
        r = admin.delete(f"/api/threads/{user_thread}")
        check("or delete it through the ordinary route", r.status_code == 404, f"HTTP {r.status_code}")
        r = admin.delete(f"/api/jobs/{user_job}")
        check("or delete the user's job through the ordinary route", r.status_code == 404, f"HTTP {r.status_code}")
        mine = {t["thread_id"]: t for t in user_c.get("/api/threads").json()}
        check("the user's conversation is untouched",
              user_thread in mine and mine[user_thread]["label"] == "qatest priv_01 user",
              str(mine.get(user_thread)))
        check("and so is their job", user_c.get(f"/api/jobs/{user_job}").status_code == 200)

        print("\n== the admin-only routes ==")
        r = admin.delete(f"/api/admin/jobs/{user_job}", timeout=60)
        check("DELETE /api/admin/jobs/{id} removes the user's job", r.status_code == 200,
              f"{r.status_code} {r.text[:150]}")
        check("and the user no longer has it", user_c.get(f"/api/jobs/{user_job}").status_code == 404)
        r = admin.delete(f"/api/admin/threads/{user_thread}")
        check("DELETE /api/admin/threads/{id} removes the user's conversation", r.status_code == 200,
              f"{r.status_code} {r.text[:150]}")
        check("and the user no longer has it",
              user_thread not in {t["thread_id"] for t in user_c.get("/api/threads").json()})
        r = user_c.get("/api/admin/jobs/x")
        check("a non-admin cannot use the admin routes", r.status_code in (403, 404, 405), f"HTTP {r.status_code}")
        r = user_c.delete(f"/api/admin/jobs/{admin_job}")
        check("a non-admin cannot delete through them", r.status_code == 403, f"HTTP {r.status_code}")
    finally:
        if admin_thread:
            admin.delete(f"/api/threads/{admin_thread}")
        cleanup_jobs(admin, jobs)
        cleanup_user(admin, user["id"])
    summary()


if __name__ == "__main__":
    main()
