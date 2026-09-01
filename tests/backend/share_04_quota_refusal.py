"""P3.1: an accept that would not fit is REFUSED, and evicts nothing.

Every other quota path in app/auth/storage_quota.py reacts to an overrun by
deleting something: enforce_all_quotas evicts oldest-first, and that is the
right behaviour when a user's own submission pushes them over their cap.
Accepting a share is the one case where it would not be, because the bytes
are arriving on somebody else's initiative. Silently deleting the
recipient's oldest results to make room for a stranger's gift is the exact
failure this check exists to prevent, and it is the behaviour the user
chose when the feature was specified.

So there are two assertions here, and the second matters more than the
first. The accept must fail with a message naming real numbers, AND the
recipient's own jobs must all still be there afterwards. A version that
refused but evicted on the way would pass the first and fail the second.

The per-user quota is deployment-wide config, so this script lowers it,
runs, and restores it in a finally. Creates two qatest_ users and its own
jobs, and deletes exactly those.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from fixtures import (  # noqa: E402
    admin_client, check, cleanup_jobs, cleanup_user, mint_invite, register, summary,
)

REPO = Path(__file__).resolve().parent.parent.parent
QUOTA_KEY = "per_user_jobs_and_chat_quota_bytes"


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
    # PATCH /api/admin/config takes {key, value}, one setting per call --
    # not a partial map of the config object. Worth stating because the
    # obvious {KEY: value} spelling is accepted as valid JSON and then
    # rejected as 422, which reads like an auth problem rather than a shape
    # one.
    original_quota = admin.get("/api/admin/config").json().get(QUOTA_KEY)
    alice_c, alice = register(mint_invite(admin))
    bob_c, bob = register(mint_invite(admin))
    created: list[str] = []

    try:
        offered = seed_job(alice["id"], "qatest quota offered")
        bobs_own = seed_job(bob["id"], "qatest quota bob keeps this")
        created += [offered, bobs_own]

        r = alice_c.post("/api/shares", json={
            "kind": "job", "resource_id": offered, "to_user_id": bob["id"]})
        check("offer created while the quota is still generous", r.status_code == 200,
              f"status={r.status_code}")
        share = r.json()

        before = {row["job_id"] for row in bob_c.get("/api/jobs").json()}
        check("the recipient has their own job before the attempt",
              bobs_own in before, f"{len(before)} job(s)")

        # --- Squeeze the cap below what the share needs --------------------
        # 1 byte, so no real job can ever fit. The point is the refusal path,
        # not a particular threshold.
        r = admin.patch("/api/admin/config", json={"key": QUOTA_KEY, "value": 1})
        check("per-user jobs-and-chat quota lowered for the test",
              r.status_code == 200, f"status={r.status_code}")

        r = bob_c.post(f"/api/shares/{share['share_id']}/accept")
        check("an accept that would not fit is refused", r.status_code == 409,
              f"status={r.status_code}")
        detail = ""
        try:
            detail = r.json().get("detail", "")
        except Exception:
            detail = r.text
        check("the refusal names real numbers rather than saying 'quota exceeded'",
              any(u in detail for u in ("B", "KB", "MB", "GB")) and "allowance" in detail,
              f"detail={detail!r}")

        # --- The assertion that matters ------------------------------------
        after = {row["job_id"] for row in bob_c.get("/api/jobs").json()}
        check("the refusal EVICTED NOTHING of the recipient's own",
              before <= after, f"{len(before)} before, {len(after)} after",
              fail_detail=f"lost: {sorted(before - after)}")

        r = bob_c.get("/api/shares/inbox")
        still = next((s for s in r.json() if s["share_id"] == share["share_id"]), None)
        check("a refused share stays pending rather than being consumed",
              still is not None and still["status"] == "pending",
              f"status={still['status'] if still else 'gone'}",
              fail_detail="the recipient must be able to retry after freeing space")

        # --- And succeeds once there is room --------------------------------
        admin.patch("/api/admin/config", json={"key": QUOTA_KEY, "value": original_quota})
        r = bob_c.post(f"/api/shares/{share['share_id']}/accept")
        check("the same share accepts once the quota is restored",
              r.status_code == 200, f"status={r.status_code} {r.text[:140]}")
        if r.status_code == 200:
            copy_id = r.json().get("copied_resource_id")
            if copy_id:
                created.append(copy_id)

    finally:
        if original_quota is not None:
            admin.patch("/api/admin/config", json={"key": QUOTA_KEY, "value": original_quota})
        alice_c.close()
        bob_c.close()
        cleanup_jobs(admin, created)
        cleanup_user(admin, alice["id"])
        cleanup_user(admin, bob["id"])
        admin.close()

    summary()


if __name__ == "__main__":
    main()
