"""P2.3 and P2.4: the two shapes of job a naive directory copy gets wrong.

**A master is not one directory.** A pes_1d scan's per-image sub-jobs live
in sibling directories carrying parent_job_id, and sub_job_ids_of finds them
by reading the master's own children.jsonl. Copying the master alone would
hand the recipient a scan whose frame slider has nothing behind it, so
copy_job copies the whole family: fresh ids, parent_job_id repointed, the
manifest regenerated, and params (which carry _scan_index) verbatim so the
images stay in order.

Children deliberately get NO ownership_index row, matching what
JobManager.submit does for a natively-run scan. That is not an oversight and
this script asserts it: storage_quota._job_candidates does not skip child
jobs, so an owned child would become an independent eviction candidate and
quota pressure could delete one out from under its master.

**A job's artifact can point outside its own directory.** uvvis_spectrum
and ensemble_spectrum point into PLOTS_DIR, at a plot object owned by the
sender. Reusing that path in a copy would serve the sender's file to the
recipient, and sweep_orphans() only reclaims a plot once its LAST source job
is gone, so the copy would pin the sender's plot forever. copy_plot_to_owner
duplicates it into the recipient's own space instead.

Creates two qatest_ users, a scan family and its own plot, and deletes
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
        cwd=str(REPO), capture_output=True, text=True, timeout=600,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"in-container exec failed: {proc.stderr[-900:]}")
    return proc.stdout.strip()


def main() -> None:
    admin = admin_client()
    alice_c, alice = register(mint_invite(admin))
    bob_c, bob = register(mint_invite(admin))
    created: list[str] = []

    try:
        # ================= A scan master and its children =================
        out = _exec_api(f'''
import json, time
from app.chemistry.molecule import resolve_molecule
from app.chemistry.jobs.base import JobSpec, get_job_manager, job_is_terminal, sub_job_ids_of
m = resolve_molecule("water")
params = {{"_scan_start_molecule": m.to_dict(), "n_points": 3,
           "coordinate": {{"type": "bond", "atoms": [1, 2]}}, "scan_range": [0.9, 1.1],
           "basis": "sto-3g"}}
from app.agent.tools import _build_scan_images
images, values, label, _w = _build_scan_images(params)
spec = JobSpec(method="hf", engine="pyscf", task="pes_1d", subtype="gs",
               molecule=m.to_dict(), params=params, label="qatest share scan")
master = get_job_manager().submit_scan(spec, images, values, label,
                                       owner_user_id={alice["id"]!r})
for _ in range(240):
    kids = sub_job_ids_of(master)
    if len(kids) >= 3 and all(job_is_terminal(k) for k in kids):
        break
    time.sleep(1)
from app.chemistry.jobs.base import read_spec
kids = sub_job_ids_of(master)
print(json.dumps({{"master": master, "children": kids,
                   "indices": [read_spec(k)["params"].get("_scan_index") for k in kids]}}))
''')
        scan = json.loads(out.splitlines()[-1])
        master, kids = scan["master"], scan["children"]
        created.append(master)
        created += kids
        # NOT asserted as len(kids) == 3. A 3-point scan currently produces
        # FIVE sub-jobs on this codebase, because the orchestrator's top-up
        # loop dispatches every non-initial image twice (indices come back
        # [0, 1, 1, 2, 2]). That is a real, pre-existing bug in
        # scan_orchestrator.py, reproduced with no sharing involved and
        # logged in docs/BACKLOG.md. It is not this feature's to fix, and
        # this script must not encode it as correct either -- so what gets
        # asserted below is that the COPY faithfully reproduces whatever
        # family it was given, measured against the source rather than
        # against a hardcoded three.
        check("a real scan master with children was seeded", len(kids) >= 3,
              f"master={master}, {len(kids)} children, indices "
              f"{sorted(set(scan.get('indices', [])))or 'n/a'}")

        out = _exec_api(f'''
import json
from app.chemistry.jobs.copy import copy_job
from app.chemistry.jobs.base import read_spec, sub_job_ids_of
from app.auth.models import get_owner
from app.config import JOBS_DIR

new_master = copy_job({master!r}, {bob["id"]!r}, shared_from="alice")
new_kids = sub_job_ids_of(new_master)
print(json.dumps({{
    "new_master": new_master,
    "new_kids": new_kids,
    "parents": [read_spec(k)["parent_job_id"] for k in new_kids],
    "indices": [read_spec(k)["params"].get("_scan_index") for k in new_kids],
    "master_owner": get_owner("job", new_master),
    "kid_owners": [get_owner("job", k) for k in new_kids],
    "manifest": (JOBS_DIR / new_master / "children.jsonl").read_text().split(),
}}))
''')
        c = json.loads(out.splitlines()[-1])
        created.append(c["new_master"])
        created += c["new_kids"]

        check("the copy has exactly as many children as the source",
              len(c["new_kids"]) == len(kids),
              f"{len(kids)} source -> {len(c['new_kids'])} copied")
        check("no child id is shared with the original",
              not (set(c["new_kids"]) & set(kids)),
              fail_detail=f"overlap: {set(c['new_kids']) & set(kids)}")
        check("every child points at the NEW master",
              set(c["parents"]) == {c["new_master"]},
              f"parents={set(c['parents'])}")
        check("children.jsonl was regenerated with the new ids",
              c["manifest"] == c["new_kids"],
              f"manifest={c['manifest']}")
        check("_scan_index survives, so the images stay in order",
              sorted(c["indices"]) == sorted(scan["indices"]),
              f"indices={c['indices']}",
              fail_detail=f"source had {scan['indices']}")
        check("every scan image is represented in the copy",
              set(c["indices"]) == {0, 1, 2},
              f"distinct indices={sorted(set(c['indices']))}")
        check("the copied master is owned by the recipient",
              c["master_owner"] == str(bob["id"]))
        check("children are deliberately left unowned",
              all(o is None for o in c["kid_owners"]),
              "an owned child would be an independent quota-eviction candidate",
              fail_detail=f"kid_owners={c['kid_owners']}")

        r = bob_c.get(f"/api/jobs/{c['new_master']}/children")
        rows = r.json().get("rows", r.json()) if r.status_code == 200 else []
        check("the recipient's scan renders its children over the API",
              r.status_code == 200 and len(rows) == 3,
              f"status={r.status_code}, {len(rows)} row(s)")

        # ================= A plot-rooted artifact =========================
        out = _exec_api(f'''
import json
from app.chemistry.molecule import resolve_molecule
from app.chemistry.jobs.base import JobSpec, get_job_manager, result_artifact_transaction
from app.auth.models import record_ownership
from app.plots import store
import time

m = resolve_molecule("water")
spec = JobSpec(method="hf", engine="pyscf", task="single_point", subtype="gs",
               molecule=m.to_dict(), params={{"basis": "sto-3g"}}, label="qatest share plotted")
job_id = get_job_manager().submit(spec)
for _ in range(90):
    if get_job_manager().status(job_id)["status"] in ("completed", "failed"):
        break
    time.sleep(1)
record_ownership("job", job_id, {alice["id"]!r})

rec = store.create_plot({alice["id"]!r}, "uvvis", "qatest spectrum",
                        {{"job_id": job_id}}, [job_id])
store.add_version({alice["id"]!r}, rec["plot_id"],
                  lambda path: open(path, "wb").write(b"\\x89PNG\\r\\n\\x1a\\n" + b"0" * 64))
rec = store.get_plot({alice["id"]!r}, rec["plot_id"])
from app.config import PLOTS_DIR
img = str(PLOTS_DIR / {alice["id"]!r} / rec["plot_id"] / (rec["versions"][-1] + ".png"))
with result_artifact_transaction(job_id) as artifacts:
    artifacts["uvvis_spectrum"] = img
print(json.dumps({{"job_id": job_id, "plot_id": rec["plot_id"], "path": img}}))
''')
        pj = json.loads(out.splitlines()[-1])
        created.append(pj["job_id"])

        out = _exec_api(f'''
import json
from app.chemistry.jobs.copy import copy_job
from app.chemistry.jobs.base import read_result
from app.auth.models import get_owner
new_id = copy_job({pj["job_id"]!r}, {bob["id"]!r}, shared_from="alice")
art = (read_result(new_id) or {{}}).get("artifacts", {{}})
path = art.get("uvvis_spectrum", "")
plot_id = path.split("/")[-2] if path else ""
print(json.dumps({{"new_id": new_id, "path": path, "plot_id": plot_id,
                  "plot_owner": get_owner("plot", plot_id) if plot_id else None}}))
''')
        pc = json.loads(out.splitlines()[-1])
        created.append(pc["new_id"])

        check("the copy's spectrum does not point at the sender's plot",
              pc["plot_id"] and pc["plot_id"] != pj["plot_id"],
              f"{pj['plot_id']} -> {pc['plot_id']}",
              fail_detail="reusing the path would leak the sender's file and pin it forever")
        check("the duplicated plot sits in the RECIPIENT's plot space",
              f"/{bob['id']}/" in pc["path"], f"path={pc['path']}")
        check("the duplicated plot is owned by the recipient",
              pc["plot_owner"] == str(bob["id"]), f"owner={pc['plot_owner']}")

        r = bob_c.get(f"/api/jobs/{pc['new_id']}/artifacts/uvvis_spectrum")
        check("the recipient can fetch their own copy of the image",
              r.status_code == 200, f"status={r.status_code}")

        # The real test: the sender deletes everything, recipient keeps it.
        alice_c.delete(f"/api/jobs/{pj['job_id']}")
        r = bob_c.get(f"/api/jobs/{pc['new_id']}/artifacts/uvvis_spectrum")
        check("the image survives deletion of the sender's job AND plot",
              r.status_code == 200, f"status={r.status_code}",
              fail_detail="sweep_orphans reclaimed a plot the copy still pointed at")

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
