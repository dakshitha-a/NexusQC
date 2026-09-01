"""P1.1: deleting a user takes their project archives with them.

`purge_user_data` removed the account's jobs, KB entries, uploads, threads
and plots but never touched `data/projects.json`. The project rows survived
while `ownership_index`'s `ON DELETE CASCADE` took their ownership rows away
with the user, and an unowned project is deliberately visible to EVERY user
-- the same rule that governs an unowned job. So deleting an account
silently converted its private archives into deployment-wide public ones.

The visibility rule is not what changes. It is right: a resource nobody owns
has to be reachable by somebody or it becomes undeletable clutter. What
changes is that a deletion stops manufacturing orphans for it to apply to.

The assertion that would have caught the original bug is the third one:
after the account is gone, no project on the whole deployment is ownerless.
Checking only that "A's project is not in A's list" would have passed
against the broken code, since A no longer has a list.

A bystander account is created alongside, and every check is repeated
against it. A purge that scoped wrongly would take their archive too, and
that failure is worse than the one being fixed.

Creates two qatest_ users, their jobs and their projects, and deletes
exactly those.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from fixtures import (  # noqa: E402
    admin_client, check, cleanup_jobs, cleanup_user, mint_invite, register, summary,
)

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
    return _exec_api(code).splitlines()[-1].strip()


def ownerless_projects() -> list[str]:
    """Every project on disk with no ownership_index row. Read in-container
    rather than through a route, because no route exposes this: an admin's
    GET /api/projects shows owned and unowned alike without distinguishing
    them, which is exactly why the original bug was invisible."""
    out = _exec_api('''
import json
from app.projects import registry
from app.auth.models import all_owners
owners = all_owners("project")
print(json.dumps([p["project_id"] for p in registry.list_projects()
                  if p["project_id"] not in owners]))
''')
    return json.loads(out.splitlines()[-1])


def main() -> None:
    admin = admin_client()
    doomed_c, doomed = register(mint_invite(admin))
    bystander_c, bystander = register(mint_invite(admin))
    created: list[str] = []
    bystander_project = None

    try:
        before_orphans = set(ownerless_projects())

        # --- The account that is about to go ------------------------------
        j1 = seed_job(doomed["id"], "qatest purge filed A")
        j2 = seed_job(doomed["id"], "qatest purge filed B")
        loose = seed_job(doomed["id"], "qatest purge unfiled")
        created += [j1, j2, loose]
        r = doomed_c.post("/api/projects",
                          json={"name": "qatest doomed archive", "job_ids": [j1, j2]})
        check("the doomed account has a project holding two jobs",
              r.status_code == 200 and r.json()["job_count"] == 2,
              f"status={r.status_code}")
        doomed_project = r.json()["project_id"]

        # --- A bystander who must be untouched ----------------------------
        b1 = seed_job(bystander["id"], "qatest purge bystander job")
        created.append(b1)
        r = bystander_c.post("/api/projects",
                             json={"name": "qatest bystander archive", "job_ids": [b1]})
        bystander_project = r.json()["project_id"]
        check("a bystander account has its own project", r.status_code == 200)

        # --- Delete the account -------------------------------------------
        r = admin.delete(f"/api/admin/users/{doomed['id']}")
        check("the account was deleted", r.status_code in (200, 204),
              f"status={r.status_code}")

        # --- Their archive is gone ----------------------------------------
        all_projects = {p["project_id"] for p in admin.get("/api/projects").json()}
        check("the deleted account's project is gone",
              doomed_project not in all_projects,
              fail_detail="the project row outlived its owner")

        # The check that would have caught the original bug. An admin's
        # project list shows unowned projects too, so "it left A's list" is
        # not the same claim as "it is gone".
        after_orphans = set(ownerless_projects())
        check("the deletion left NO ownerless project behind",
              not (after_orphans - before_orphans),
              f"{len(after_orphans)} ownerless on the deployment, unchanged from {len(before_orphans)}",
              fail_detail=f"new orphans: {sorted(after_orphans - before_orphans)}")

        # --- Their jobs are gone, filed or not ----------------------------
        gone = _exec_api(f'''
import json
from app.chemistry.jobs.base import read_spec
print(json.dumps({{jid: read_spec(jid) is not None for jid in {[j1, j2, loose]!r}}}))
''')
        alive = [k for k, v in json.loads(gone.splitlines()[-1]).items() if v]
        check("every job they owned is gone, whether filed into the project or not",
              not alive, "filed and unfiled alike",
              fail_detail=f"still on disk: {alive}")

        # --- The bystander is untouched -------------------------------------
        check("the bystander's project survives",
              bystander_project in all_projects,
              fail_detail="the purge scoped too widely")
        r = bystander_c.get(f"/api/jobs/{b1}")
        check("the bystander's job survives", r.status_code == 200,
              f"status={r.status_code}")
        r = bystander_c.get("/api/projects")
        mine = [p for p in r.json() if p["project_id"] == bystander_project]
        check("the bystander's project still holds its job",
              bool(mine) and mine[0]["job_count"] == 1,
              f"job_count={mine[0]['job_count'] if mine else 'gone'}")

    finally:
        if bystander_project:
            try:
                bystander_c.delete(f"/api/projects/{bystander_project}",
                                   params={"delete_jobs": "false"})
            except Exception:
                pass
        doomed_c.close()
        bystander_c.close()
        cleanup_jobs(admin, created)
        cleanup_user(admin, bystander["id"])
        admin.close()

    summary()


if __name__ == "__main__":
    main()
