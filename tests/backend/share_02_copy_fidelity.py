"""P2: app/chemistry/jobs/copy.py -- is a copied job genuinely independent?

The whole feature rests on the answer being yes. The requirement the user
asked for is that a recipient keeps the result after the sender deletes
theirs, and every way of getting that subtly wrong looks fine right up
until the sender presses delete.

The three traps this script exists to catch, all of them real properties of
this codebase rather than hypotheticals:

  * result.json stores artifact paths ABSOLUTE and containing the job id,
    and GET /api/jobs/{id}/artifacts/{key} opens exactly that stored string.
    A shutil.copytree alone produces a copy whose every artifact still
    serves the sender's files and 404s the moment they are deleted. `cubes`
    is a nested dict, so a rewrite that only walked the top level would miss
    every orbital cube.
  * meta.json carries worker_pid/worker_pid_create_time identifying a
    process on the machine that ran the ORIGINAL job. Carried into a copy
    they name either nothing or an unrelated live process.
  * spec.json is what makes a directory a job to every listing walk in the
    app. It must be written LAST, and ownership recorded BEFORE it, because
    a visible job with no ownership row is visible to EVERY user.

Driven through the copy primitive directly rather than through the share
routes -- share_03 covers the routes. Creates two qatest_ users and its own
jobs, and deletes exactly those.
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
    """A real, trivial PySCF water single point through the same JobManager
    the app uses. Same shape and reasoning as proj_02_lifecycle.py's."""
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
    created: list[str] = []

    try:
        src = seed_job(alice["id"], "qatest share source")
        created.append(src)
        check("source job seeded", bool(src), f"job_id={src}")

        # --- Copy it into Bob's ownership --------------------------------
        out = _exec_api(f'''
import json
from pathlib import Path
from app.chemistry.jobs.copy import copy_job
from app.chemistry.jobs.base import read_meta, read_result, read_spec
from app.auth.models import get_owner
from app.config import JOBS_DIR

new_id = copy_job({src!r}, {bob["id"]!r}, shared_from="alice")
print(json.dumps({{
    "new_id": new_id,
    "spec": read_spec(new_id),
    "meta": read_meta(new_id),
    "result": read_result(new_id),
    "owner": get_owner("job", new_id),
    "files": sorted(p.name for p in (JOBS_DIR / new_id).iterdir()),
}}))
''')
        info = json.loads(out.splitlines()[-1])
        new_id = info["new_id"]
        created.append(new_id)

        check("copy produced a new job id", bool(new_id) and new_id != src,
              f"{src} -> {new_id}")
        check("spec.json carries the NEW job id", info["spec"]["job_id"] == new_id,
              fail_detail=f"spec says {info['spec']['job_id']}")
        check("the copy is owned by the recipient", info["owner"] == str(bob["id"]),
              f"owner={info['owner']}")
        check("spec.json is present, so the copy is a real job to every listing walk",
              "spec.json" in info["files"])

        # --- meta.json --------------------------------------------------
        meta = info["meta"]
        check("worker_pid is not carried into the copy", "worker_pid" not in meta,
              fail_detail=f"meta={meta}")
        check("worker_pid_create_time is not carried into the copy",
              "worker_pid_create_time" not in meta)
        check("the copy records who shared it", meta.get("shared_from") == "alice",
              f"shared_from={meta.get('shared_from')}")

        # --- artifact paths ----------------------------------------------
        artifacts = (info["result"] or {}).get("artifacts") or {}
        flat: list[str] = []

        def walk(node):
            if isinstance(node, dict):
                for v in node.values():
                    walk(v)
            elif isinstance(node, list):
                for v in node:
                    walk(v)
            elif isinstance(node, str):
                flat.append(node)

        walk(artifacts)
        check("the copied job has artifacts to check at all", bool(flat),
              f"{len(flat)} artifact path(s): {sorted(artifacts)}")
        stale = [p for p in flat if f"/jobs/{src}/" in p]
        check("no artifact path still points at the source job",
              not stale, f"{len(flat)} path(s) checked",
              fail_detail=f"still pointing at the sender: {stale}")
        mine = [p for p in flat if f"/jobs/{new_id}/" in p or "/plots/" in p]
        check("every artifact path points into the copy (or the copy's own plot)",
              len(mine) == len(flat),
              fail_detail=f"unaccounted: {[p for p in flat if p not in mine]}")

        check("result.json carries the new job id",
              (info["result"] or {}).get("job_id") == new_id)

        # --- The point of the whole feature ------------------------------
        r = bob_c.get(f"/api/jobs/{new_id}")
        check("the recipient can open their copy", r.status_code == 200,
              f"status={r.status_code}")

        r = alice_c.delete(f"/api/jobs/{src}")
        check("the sender can delete their original", r.status_code in (200, 204),
              f"status={r.status_code}")

        r = bob_c.get(f"/api/jobs/{new_id}")
        check("the copy SURVIVES deletion of the original", r.status_code == 200,
              f"status={r.status_code}",
              fail_detail="this is the requirement the whole feature exists for")

        # Every artifact must still be served, not just the job row.
        served = []
        for key in artifacts:
            if isinstance(artifacts[key], dict):
                continue
            rr = bob_c.get(f"/api/jobs/{new_id}/artifacts/{key}")
            served.append((key, rr.status_code))
        check("the copy's artifacts are still served after the original is gone",
              all(code == 200 for _, code in served),
              f"{served}",
              fail_detail="an artifact path survived the rewrite but not the delete")

        # --- Isolation ----------------------------------------------------
        r = alice_c.get(f"/api/jobs/{new_id}")
        check("the sender cannot read the recipient's copy", r.status_code == 404,
              f"status={r.status_code}")

    finally:
        alice_c.close()
        bob_c.close()
        cleanup_jobs(admin, created)
        cleanup_user(admin, alice["id"])
        cleanup_user(admin, bob["id"])
        admin.close()

    summary()


if __name__ == "__main__":
    main()
