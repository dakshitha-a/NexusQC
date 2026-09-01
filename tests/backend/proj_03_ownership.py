#!/usr/bin/env python3
"""A project archive is private to whoever made it, on every route.

    QC_AGENT_TEST_BASE_URL=https://127.0.0.1:8444 \
      PYTHONPATH=$PWD python3 tests/backend/proj_03_ownership.py

A new route module is a new set of chances to forget the ownership check,
and this repository has already been bitten by exactly that: the job
artifact route served any job's files to any caller, including one with no
cookie at all, until it was found by a sweep (see get_job_artifact's
docstring in server/routes/jobs.py). Every project route is therefore
checked individually here rather than trusting that they share a helper.

Two properties beyond the obvious:

  * The refusal is 404, not 403. A 403 would confirm that a project id
    exists, which turns the list route into a way to enumerate other
    people's archives.
  * A user cannot file away a job they do not own. The check has to be on
    the job as well as on the project, or a project would be a way to
    reach another user's results through the archive download.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fixtures import (  # noqa: E402
    admin_client, check, cleanup_jobs, cleanup_user, mint_invite, register, summary,
)


def seed_job(owner_user_id: str, label: str) -> str:
    code = f'''
import time
from app.chemistry.molecule import resolve_molecule
from app.chemistry.jobs.base import JobSpec, get_job_manager
from app.auth.models import record_ownership

m = resolve_molecule("water")
spec = JobSpec(method="hf", engine="pyscf", task="single_point", subtype="gs",
               molecule=m.to_dict(), params={{"basis": "sto-3g"}}, label={label!r})
job_id = get_job_manager().submit(spec)
for _ in range(90):
    if get_job_manager().status(job_id)["status"] in ("completed", "failed"):
        break
    time.sleep(1)
record_ownership("job", job_id, {owner_user_id!r})
print(job_id)
'''
    proc = subprocess.run(
        ["docker", "compose", "exec", "-T", "api", "python", "-c", code],
        cwd=str(REPO), capture_output=True, text=True, timeout=180,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"seeding failed: {proc.stderr[-500:]}")
    return proc.stdout.strip().splitlines()[-1].strip()


def _body_hint(resp) -> str:
    """What to print about a response body.

    A zip is described rather than dumped. `resp.text[:150]` on the project
    download begins `PK\x03\x04` and carries NUL bytes, and a single NUL
    makes the whole stream binary to grep -- which on a host whose grep is
    ugrep means a filtered run prints nothing at all for this script, so a
    passing 15/15 reads as a script that crashed. fixtures.check now escapes
    that as a backstop; this keeps the line useful as well as safe, since
    150 characters of escaped zip header tells a reader nothing.
    """
    ctype = resp.headers.get("content-type", "")
    if "json" in ctype or ctype.startswith("text/"):
        return resp.text[:150]
    return f"<{ctype or 'binary'}, {len(resp.content)} bytes>"


def main() -> None:
    admin = admin_client()
    owner_client, owner = register(mint_invite(admin))
    other_client, other = register(mint_invite(admin))

    jobs: list[str] = []
    projects: list[str] = []
    try:
        mine = seed_job(owner["id"], "qatest owned by owner")
        theirs = seed_job(other["id"], "qatest owned by other")
        jobs += [mine, theirs]

        r = owner_client.post("/api/projects", json={"name": "qatest private", "job_ids": [mine]})
        r.raise_for_status()
        project_id = r.json()["project_id"]
        projects.append(project_id)

        print("\n== the owner can reach every route ==")
        for name, resp in [
            ("read", owner_client.get(f"/api/projects/{project_id}")),
            ("rename", owner_client.patch(f"/api/projects/{project_id}", json={"name": "qatest private"})),
            ("download", owner_client.get(f"/api/projects/{project_id}/download")),
        ]:
            check(f"the owner can {name} their own project", resp.status_code == 200,
                  f"{resp.status_code} {_body_hint(resp)}")

        print("\n== another user cannot reach any of them ==")
        cases = [
            ("read it", other_client.get(f"/api/projects/{project_id}")),
            ("rename it", other_client.patch(f"/api/projects/{project_id}", json={"name": "hijacked"})),
            ("download it", other_client.get(f"/api/projects/{project_id}/download")),
            ("add jobs to it", other_client.post(f"/api/projects/{project_id}/jobs",
                                                 json={"job_ids": [theirs]})),
            ("take jobs out of it", other_client.post(f"/api/projects/{project_id}/jobs/remove",
                                                      json={"job_ids": [mine]})),
            ("delete it", other_client.delete(f"/api/projects/{project_id}",
                                              params={"delete_jobs": "false"})),
        ]
        for name, resp in cases:
            check(f"another user cannot {name}", resp.status_code == 404,
                  f"got {resp.status_code} {resp.text[:150]}",
                  "403 would be a leak in itself: it confirms the project id exists")

        print("\n== and it is absent from their list entirely ==")
        listed = {p["project_id"] for p in other_client.get("/api/projects").json()}
        check("another user's project list does not contain it", project_id not in listed,
              f"listed: {sorted(listed)}")

        print("\n== an admin CAN, which is the documented override ==")
        check("an admin can read any project", admin.get(f"/api/projects/{project_id}").status_code == 200)
        check("and download it", admin.get(f"/api/projects/{project_id}/download").status_code == 200)

        print("\n== a job cannot be filed away by someone who cannot see it ==")
        r = other_client.post("/api/projects", json={"name": "qatest thief"})
        r.raise_for_status()
        thief_project = r.json()["project_id"]
        projects.append(thief_project)
        r = other_client.post(f"/api/projects/{thief_project}/jobs", json={"job_ids": [mine]})
        check("filing another user's job into your own project is refused", r.status_code == 404,
              f"got {r.status_code} {r.text[:150]}",
              "otherwise a project download is a way to read another user's results")
        check("and the project stayed empty",
              other_client.get(f"/api/projects/{thief_project}").json()["job_count"] == 0)

        print("\n== the renamed check above did not actually rename anything ==")
        check("the owner's project still has its own name",
              owner_client.get(f"/api/projects/{project_id}").json()["name"] == "qatest private",
              "a refused PATCH still wrote")
    finally:
        for project_id in projects:
            for client in (owner_client, other_client, admin):
                try:
                    if client.delete(f"/api/projects/{project_id}",
                                     params={"delete_jobs": "false"}).status_code == 200:
                        break
                except Exception:
                    pass
        cleanup_jobs(admin, jobs)
        cleanup_user(admin, owner["id"])
        cleanup_user(admin, other["id"])

    summary()


if __name__ == "__main__":
    main()
