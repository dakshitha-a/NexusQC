#!/usr/bin/env python3
"""Project archives: creating one, filing jobs into it, taking them back
out, and the two different things "delete" can mean.

    QC_AGENT_TEST_BASE_URL=https://127.0.0.1:8444 \
      PYTHONPATH=$PWD python3 tests/backend/proj_02_lifecycle.py

Against the running stack, because most of what is worth checking here is
a property of the routes rather than of the registry (which
tests/backend/proj_01_registry.py covers as pure functions). Specifically:

  * An archived job leaves GET /api/jobs and comes back with
    include_archived. That default is the whole point of the feature, and
    it is also the change most likely to break something else, since it
    alters what the job manager's main list returns.
  * Filing a job into a second project moves it rather than copying it,
    end to end through the API rather than through the registry directly.
  * Deleting a project without delete_jobs leaves the jobs on disk and
    puts them back in the job list; deleting WITH delete_jobs removes
    them. Neither is a default: the query parameter is explicit.
  * purge-mine deletes only the caller's projects, and an admin running it
    does not touch another user's. That last one is the data-loss path.

Creates only qatest_ users and its own jobs, and deletes exactly those in
a finally block -- never a blind purge.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fixtures import (  # noqa: E402
    BASE_URL, admin_client, check, cleanup_jobs, cleanup_user, mint_invite, register, summary,
)


def seed_job(owner_user_id: str, label: str) -> str:
    """A real, trivial PySCF water single point, submitted through the same
    JobManager the app uses and recorded against `owner_user_id` the way
    chat.py's approval handler does. Bypasses the agent entirely: nothing
    here is testing the LLM, and a real completed job is what the archive
    needs to have something to package.

    Same in-container exec shape as tests/backend/sec_06_ownership_sweep.py
    uses, and for the same reason: this must construct the scenario with
    the functions the real app calls, not with a synthetic fixture."""
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


def job_ids(client, include_archived: bool = False) -> set[str]:
    params = {"include_archived": "true"} if include_archived else None
    r = client.get("/api/jobs", params=params)
    r.raise_for_status()
    return {row["job_id"] for row in r.json()}


def main() -> None:
    admin = admin_client()
    token = mint_invite(admin)
    user_client, user = register(token)
    other_token = mint_invite(admin)
    other_client, other = register(other_token)

    created_jobs: list[str] = []
    created_projects: list[str] = []
    try:
        print("\n== seeding three real jobs ==")
        a = seed_job(user["id"], "qatest archive A")
        b = seed_job(user["id"], "qatest archive B")
        c = seed_job(user["id"], "qatest archive C")
        created_jobs += [a, b, c]
        check("three jobs seeded and visible to their owner",
              {a, b, c} <= job_ids(user_client), f"listed: {sorted(job_ids(user_client))}")

        print("\n== creating a project and filing jobs into it ==")
        r = user_client.post("/api/projects", json={"name": "qatest project one"})
        check("a project can be created", r.status_code == 200, f"{r.status_code} {r.text[:200]}")
        p1 = r.json()["project_id"]
        created_projects.append(p1)
        check("a new project starts empty", r.json()["job_count"] == 0, str(r.json()))

        r = user_client.post(f"/api/projects/{p1}/jobs", json={"job_ids": [a, b]})
        check("two jobs file into it", r.status_code == 200 and r.json()["job_count"] == 2,
              f"{r.status_code} {r.text[:200]}")

        print("\n== an archived job leaves the job manager's list ==")
        plain = job_ids(user_client)
        check("both archived jobs are gone from GET /api/jobs",
              a not in plain and b not in plain, f"still listed: {sorted(plain & {a, b})}")
        check("the unarchived one is still there", c in plain, f"listed: {sorted(plain)}")

        withArchived = job_ids(user_client, include_archived=True)
        check("include_archived brings them back", {a, b, c} <= withArchived, f"listed: {sorted(withArchived)}")

        rows = {row["job_id"]: row for row in user_client.get(
            "/api/jobs", params={"include_archived": "true"}).json()}
        check("an archived row names its project",
              rows[a]["project_name"] == "qatest project one" and rows[a]["project_id"] == p1,
              str({k: rows[a].get(k) for k in ("project_id", "project_name")}))
        check("an unarchived row says so explicitly rather than omitting the field",
              rows[c]["project_id"] is None and rows[c]["project_name"] is None,
              str({k: rows[c].get(k) for k in ("project_id", "project_name")}))

        print("\n== the per-conversation list is deliberately NOT filtered ==")
        # A job never stops belonging to the conversation that started it.
        # These jobs were submitted outside a conversation, so the check
        # that matters is the route's shape rather than its contents: it
        # must not have grown an include_archived parameter of its own.
        r = user_client.get("/api/jobs?include_archived=true")
        check("the global list accepts include_archived", r.status_code == 200, str(r.status_code))

        print("\n== a job belongs to exactly one project ==")
        r = user_client.post("/api/projects", json={"name": "qatest project two", "job_ids": [a]})
        check("a project can be created with jobs in one call", r.status_code == 200, f"{r.status_code} {r.text[:200]}")
        p2 = r.json()["project_id"]
        created_projects.append(p2)
        one = user_client.get(f"/api/projects/{p1}").json()
        two = user_client.get(f"/api/projects/{p2}").json()
        check("filing into a second project MOVED the job rather than copying it",
              one["job_ids"] == [b] and two["job_ids"] == [a],
              f"project one {one['job_ids']}, project two {two['job_ids']}")

        print("\n== the detail route carries real job rows ==")
        check("a project's jobs come back in the job manager's own row shape",
              len(two["jobs"]) == 1 and two["jobs"][0]["job_id"] == a and "engine" in two["jobs"][0],
              str(two["jobs"])[:200])
        check("and the project reports a non-zero archive size", two["size_bytes"] > 0, str(two["size_bytes"]))

        print("\n== renaming ==")
        r = user_client.patch(f"/api/projects/{p1}", json={"name": "qatest renamed"})
        check("a project can be renamed", r.status_code == 200 and r.json()["name"] == "qatest renamed",
              f"{r.status_code} {r.text[:200]}")
        rows = {row["job_id"]: row for row in user_client.get(
            "/api/jobs", params={"include_archived": "true"}).json()}
        check("the rename reaches the archived job's badge", rows[b]["project_name"] == "qatest renamed",
              str(rows[b].get("project_name")))

        print("\n== returning a job to the job manager ==")
        r = user_client.post(f"/api/projects/{p1}/jobs/remove", json={"job_ids": [b]})
        check("a job can be returned", r.status_code == 200 and r.json()["job_count"] == 0,
              f"{r.status_code} {r.text[:200]}")
        check("and it is listed again without include_archived", b in job_ids(user_client))
        check("its files were never moved, so it still opens",
              user_client.get(f"/api/jobs/{b}").status_code == 200)

        print("\n== delete: the project only ==")
        r = user_client.delete(f"/api/projects/{p1}", params={"delete_jobs": "false"})
        check("deleting a project without its jobs succeeds", r.status_code == 200, f"{r.status_code} {r.text[:200]}")
        created_projects.remove(p1)
        check("the project is gone", user_client.get(f"/api/projects/{p1}").status_code == 404)

        print("\n== delete: the project and its jobs ==")
        released = user_client.get(f"/api/projects/{p2}").json()["job_ids"]
        check("the project still holds the job before the cascade", released == [a], str(released))
        r = user_client.delete(f"/api/projects/{p2}", params={"delete_jobs": "true"})
        check("a cascading delete succeeds", r.status_code == 200, f"{r.status_code} {r.text[:200]}")
        check("and it reports the jobs it purged", r.json().get("purged_jobs") == 1, str(r.json()))
        created_projects.remove(p2)
        check("the job is really gone", user_client.get(f"/api/jobs/{a}").status_code == 404)
        if a in created_jobs:
            created_jobs.remove(a)

        print("\n== purge-mine is scoped to the caller, even for an admin ==")
        r = user_client.post("/api/projects", json={"name": "qatest mine", "job_ids": [b]})
        mine = r.json()["project_id"]
        created_projects.append(mine)
        r = other_client.post("/api/projects", json={"name": "qatest theirs"})
        theirs = r.json()["project_id"]
        created_projects.append(theirs)

        # The admin's own list shows every project on the deployment, which
        # is exactly the trap: purge-mine must not be scoped off it.
        admin_sees = {p["project_id"] for p in admin.get("/api/projects").json()}
        check("an admin's project list does show other users' projects",
              mine in admin_sees and theirs in admin_sees,
              "if this fails the next check proves nothing, since there would be nothing to wrongly delete")
        r = admin.post("/api/projects/purge-mine")
        check("an admin can run purge-mine", r.status_code == 200, f"{r.status_code} {r.text[:200]}")
        check("and it left the OTHER users' projects alone",
              other_client.get(f"/api/projects/{theirs}").status_code == 200
              and user_client.get(f"/api/projects/{mine}").status_code == 200,
              "an admin's 'delete all MY projects' deleted somebody else's data")

        r = user_client.post("/api/projects/purge-mine")
        check("a user's own purge-mine succeeds", r.status_code == 200, f"{r.status_code} {r.text[:200]}")
        check("it deleted their project", user_client.get(f"/api/projects/{mine}").status_code == 404)
        check("and the job that was in it, since purge-mine cascades",
              user_client.get(f"/api/jobs/{b}").status_code == 404)
        created_projects.remove(mine)
        if b in created_jobs:
            created_jobs.remove(b)
        check("the other user's project survived a second purge",
              other_client.get(f"/api/projects/{theirs}").status_code == 200)
    finally:
        for project_id in created_projects:
            for client in (user_client, other_client, admin):
                try:
                    if client.delete(f"/api/projects/{project_id}",
                                     params={"delete_jobs": "false"}).status_code == 200:
                        break
                except Exception:
                    pass
        if created_jobs:
            cleanup_jobs(admin, created_jobs)
        cleanup_user(admin, user["id"])
        cleanup_user(admin, other["id"])

    summary()


if __name__ == "__main__":
    main()
