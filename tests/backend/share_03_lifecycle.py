"""P3: the share lifecycle routes in server/routes/shares.py.

Offer, accept, decline, withdraw, and the boundaries around each. The
shape being defended here is that an offer is a row and nothing else until
the recipient accepts: that is what stops one user pushing bytes into
another user's account, and it is what makes withdraw possible at all.

Boundary checks worth naming, because each is a way the feature could have
shipped wrong:

  * A third party gets 404 (not 403) on every route, so share ids cannot
    be probed, matching check_owner_or_admin's own convention.
  * Only the recipient may accept or decline; only the sender may withdraw.
  * A second PENDING offer of the same thing to the same person is refused
    by resource_shares_pending_idx, but re-offering after a decline is
    legitimate and must work.
  * A non-terminal job cannot be offered at all: a copy taken mid-run is a
    torn snapshot carrying a `running` status nothing will ever advance.
  * Accepting is a compare-and-set, so a settled offer cannot be re-answered.

Creates three qatest_ users, its own jobs and its own project, and deletes
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


def main() -> None:
    admin = admin_client()
    alice_c, alice = register(mint_invite(admin))
    bob_c, bob = register(mint_invite(admin))
    eve_c, eve = register(mint_invite(admin))
    created: list[str] = []
    made_projects: list[tuple] = []  # (client, project_id)

    try:
        job_a = seed_job(alice["id"], "qatest share lifecycle A")
        job_b = seed_job(alice["id"], "qatest share lifecycle B")
        created += [job_a, job_b]

        # --- Offering -----------------------------------------------------
        r = alice_c.post("/api/shares", json={
            "kind": "job", "resource_id": job_a, "to_user_id": bob["id"],
            "note": "have a look",
        })
        check("offer accepted", r.status_code == 200, f"status={r.status_code} {r.text[:120]}")
        share = r.json()
        check("offer starts pending", share.get("status") == "pending")
        check("offer snapshots a readable label", bool(share.get("source_label")),
              f"label={share.get('source_label')!r}")
        check("offer snapshots a size", share.get("size_bytes", 0) > 0,
              f"{share.get('size_bytes')} bytes")

        # Nothing was copied yet -- that is the whole point of the offer step.
        r = bob_c.get("/api/jobs")
        check("offering copies NOTHING into the recipient's account",
              not any(row["job_id"] == job_a for row in r.json()),
              "the recipient's job list is untouched until they accept")

        # --- Duplicate offers ---------------------------------------------
        r = alice_c.post("/api/shares", json={
            "kind": "job", "resource_id": job_a, "to_user_id": bob["id"]})
        check("a second PENDING offer of the same job to the same user is refused",
              r.status_code == 409, f"status={r.status_code}")

        # --- Self-share ------------------------------------------------------
        r = alice_c.post("/api/shares", json={
            "kind": "job", "resource_id": job_a, "to_user_id": alice["id"]})
        check("you cannot share with yourself", r.status_code == 400,
              f"status={r.status_code}")

        # --- Sharing what you do not own -------------------------------------
        r = eve_c.post("/api/shares", json={
            "kind": "job", "resource_id": job_a, "to_user_id": bob["id"]})
        check("you cannot offer somebody else's job", r.status_code == 404,
              f"status={r.status_code}")

        # --- The inbox -------------------------------------------------------
        r = bob_c.get("/api/shares/inbox")
        inbox = r.json()
        check("the offer reaches the recipient's inbox",
              any(s["share_id"] == share["share_id"] for s in inbox),
              f"{len(inbox)} row(s)")
        row = next(s for s in inbox if s["share_id"] == share["share_id"])
        check("the inbox row names the sender", row.get("from_username") == alice["username"],
              f"from={row.get('from_username')}")
        check("the inbox row does not leak the sender's email", "from_email" not in row)

        r = eve_c.get("/api/shares/inbox")
        check("a third party's inbox does not show the offer",
              not any(s["share_id"] == share["share_id"] for s in r.json()))

        r = alice_c.get("/api/shares/outbox")
        check("the sender sees it in their outbox",
              any(s["share_id"] == share["share_id"] for s in r.json()))

        # --- Who may act -----------------------------------------------------
        r = eve_c.post(f"/api/shares/{share['share_id']}/accept")
        check("a third party cannot accept (404, not 403)", r.status_code == 404,
              f"status={r.status_code}")
        r = alice_c.post(f"/api/shares/{share['share_id']}/accept")
        check("the SENDER cannot accept their own offer", r.status_code == 404,
              f"status={r.status_code}")
        r = bob_c.post(f"/api/shares/{share['share_id']}/withdraw")
        check("the recipient cannot withdraw", r.status_code == 404,
              f"status={r.status_code}")
        r = alice_c.post("/api/shares/not-a-uuid/accept")
        check("a malformed share id is a 404, not a 500", r.status_code == 404,
              f"status={r.status_code}")

        # --- Accept ----------------------------------------------------------
        r = bob_c.post(f"/api/shares/{share['share_id']}/accept")
        check("the recipient can accept", r.status_code == 200,
              f"status={r.status_code} {r.text[:160]}")
        accepted = r.json() if r.status_code == 200 else {}
        copy_id = accepted.get("copied_resource_id")
        if copy_id:
            created.append(copy_id)
        check("accept records what it produced", bool(copy_id), f"copy={copy_id}")
        check("the offer is now accepted", accepted.get("status") == "accepted")

        r = bob_c.get("/api/jobs")
        check("the copy is in the recipient's job list",
              any(row["job_id"] == copy_id for row in r.json()))

        r = bob_c.post(f"/api/shares/{share['share_id']}/accept")
        check("a settled offer cannot be accepted twice", r.status_code == 409,
              f"status={r.status_code}")

        # --- Decline, and re-offer afterwards ---------------------------------
        r = alice_c.post("/api/shares", json={
            "kind": "job", "resource_id": job_b, "to_user_id": bob["id"]})
        second = r.json()
        r = bob_c.post(f"/api/shares/{second['share_id']}/decline")
        check("the recipient can decline", r.status_code == 200,
              f"status={r.status_code}")

        r = bob_c.get("/api/jobs")
        check("declining copies nothing",
              not any(row.get("shared_from") for row in r.json()
                      if row["job_id"] not in (copy_id,)),
              "no second copy appeared")

        r = alice_c.post("/api/shares", json={
            "kind": "job", "resource_id": job_b, "to_user_id": bob["id"]})
        check("re-offering after a decline is allowed", r.status_code == 200,
              f"status={r.status_code}",
              fail_detail="the pending-unique index must be PARTIAL, not total")
        third = r.json()

        # --- Withdraw ---------------------------------------------------------
        r = alice_c.post(f"/api/shares/{third['share_id']}/withdraw")
        check("the sender can withdraw a pending offer", r.status_code == 200,
              f"status={r.status_code}")
        r = bob_c.get("/api/shares/inbox")
        check("a withdrawn offer leaves the recipient's inbox",
              not any(s["share_id"] == third["share_id"] for s in r.json()))
        r = bob_c.post(f"/api/shares/{third['share_id']}/accept")
        check("a withdrawn offer cannot be accepted", r.status_code == 409,
              f"status={r.status_code}")

        # --- A running job cannot be offered ------------------------------------
        # The status is set directly rather than by racing a real slow job.
        # An earlier spelling submitted a ccsd_t/cc-pvtz job and hoped it
        # would still be running when the offer landed; it reached `failed`
        # first and the check proved nothing. What is under test is the
        # route's job_is_terminal() guard, and write_status exercises that
        # guard exactly, every time.
        held = seed_job(alice["id"], "qatest share held open")
        created.append(held)
        _exec_api(f"""
from app.chemistry.jobs.base import write_status
write_status({held!r}, "running", "held open by share_03")
print("ok")
""")
        r = alice_c.post("/api/shares", json={
            "kind": "job", "resource_id": held, "to_user_id": bob["id"]})
        check("an unfinished job cannot be offered", r.status_code == 409,
              f"status={r.status_code}",
              fail_detail="a copy taken mid-run is a torn snapshot carrying a status nothing will advance")
        _exec_api(f"""
from app.chemistry.jobs.base import write_status
write_status({held!r}, "completed", "released by share_03")
print("ok")
""")

        # --- Project sharing -----------------------------------------------------
        job_c = seed_job(alice["id"], "qatest share project member")
        created.append(job_c)
        r = alice_c.post("/api/projects", json={"name": "qatest shared study", "job_ids": [job_c]})
        project = r.json()
        made_projects.append((alice_c, project["project_id"]))
        r = alice_c.post("/api/shares", json={
            "kind": "project", "resource_id": project["project_id"], "to_user_id": bob["id"]})
        check("a project can be offered", r.status_code == 200,
              f"status={r.status_code} {r.text[:160]}")
        pshare = r.json()
        r = bob_c.post(f"/api/shares/{pshare['share_id']}/accept")
        check("a project share can be accepted", r.status_code == 200,
              f"status={r.status_code} {r.text[:160]}")
        new_project_id = r.json().get("copied_resource_id")

        r = bob_c.get("/api/projects")
        mine = [p for p in r.json() if p["project_id"] == new_project_id]
        check("the recipient gets their own project", bool(mine),
              f"project={new_project_id}")
        if mine:
            check("the recipient's project carries its own copies of the jobs",
                  mine[0]["job_count"] == 1 and job_c not in mine[0]["job_ids"],
                  f"job_ids={mine[0]['job_ids']}",
                  fail_detail="a shared project must not reference the sender's job ids")
            created += list(mine[0]["job_ids"])
            made_projects.append((bob_c, new_project_id))

        r = alice_c.get("/api/projects")
        check("the sender still has their original project",
              any(p["project_id"] == project["project_id"] for p in r.json()))

    finally:
        # Projects are NOT removed by deleting their owner (purge_user_data
        # covers jobs, KB, uploads, threads and plots but not projects), so
        # this script deletes its own or it leaves them behind as ownerless
        # rows that every user can then see.
        for client, project_id in made_projects:
            try:
                client.delete(f"/api/projects/{project_id}", params={"delete_jobs": "false"})
            except Exception:
                pass
        for c in (alice_c, bob_c, eve_c):
            c.close()
        cleanup_jobs(admin, created)
        for u in (alice, bob, eve):
            cleanup_user(admin, u["id"])
        admin.close()

    summary()


if __name__ == "__main__":
    main()
