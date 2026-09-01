"""P2.1: a scan dispatches each image exactly once, even across processes.

The three orchestrators each guard their decide-then-dispatch section with a
module-level `threading.Lock`. That is the correct guard for the deployment
`server/main.py` actually produces -- `uvicorn.run` takes no `workers`
argument, so there is one process and one orchestrator -- and a single
process really does dispatch a 3-point scan as exactly three sub-jobs.

It coordinates nothing between processes, though, and this script reproduces
the case that matters: submitting a scan the way every other script in this
directory submits a job, with `docker compose exec api python -c ...`, which
is a SECOND process sharing `data/jobs/` with the running server. The
one-shot process dispatches the initial wave while the server's orchestrator
polls the same master, and each can read "index 1 is missing" before the
other's child has its `spec.json` on disk.

Before `base.master_dispatch_guard`, this produced `_scan_index` values of
`[0, 1, 1, 2, 2]` for a 3-point scan: image 0 dispatched once by whoever got
there first, every later image twice. Each duplicate is a real PySCF
subprocess occupying a scheduler slot and a real job directory billed to the
owner's quota, so a 50-point scan paid for about 99 images to show 50.

The assertion is on the MANIFEST, not on `sub_job_ids_of`. That function
deduplicates by job id, so it would happily return five entries for a
three-image scan without anything looking obviously wrong; and the route
that renders a scan groups by `_scan_index`, which is why the duplication
was invisible in the UI for as long as it was. What has to be true is that
each index was dispatched once.

Creates one qatest_ user and one scan family, and deletes exactly those.
"""
from __future__ import annotations

import json
import subprocess
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from fixtures import (  # noqa: E402
    admin_client, check, cleanup_jobs, cleanup_user, mint_invite, register, summary,
)

REPO = Path(__file__).resolve().parent.parent.parent
N_POINTS = 3


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
    user_c, user = register(mint_invite(admin))
    created: list[str] = []

    try:
        out = _exec_api(f'''
import json, time
from app.chemistry.molecule import resolve_molecule
from app.chemistry.jobs.base import (
    JobSpec, get_job_manager, job_is_terminal, read_spec, sub_job_ids_of,
    _children_manifest_path,
)
from app.agent.tools import _build_scan_images

m = resolve_molecule("water")
params = {{"_scan_start_molecule": m.to_dict(), "n_points": {N_POINTS},
           "coordinate": {{"type": "bond", "atoms": [1, 2]}},
           "scan_range": [0.9, 1.1], "basis": "sto-3g"}}
images, values, label, _w = _build_scan_images(params)
spec = JobSpec(method="hf", engine="pyscf", task="pes_1d", subtype="gs",
               molecule=m.to_dict(), params=params, label="qatest scan dispatch")
master = get_job_manager().submit_scan(spec, images, values, label,
                                       owner_user_id={user["id"]!r})
for _ in range(300):
    kids = sub_job_ids_of(master)
    if len(kids) >= {N_POINTS} and all(job_is_terminal(k) for k in kids):
        # Let the server-side orchestrator take several more ticks at a
        # master it now believes is complete. A top-up that was going to
        # dispatch a duplicate would do it here.
        time.sleep(12)
        break
    time.sleep(1)

manifest = _children_manifest_path(master).read_text().split()
kids = sub_job_ids_of(master)
print("RESULT" + json.dumps({{
    "master": master,
    "manifest": manifest,
    "children": kids,
    "indices": [read_spec(k)["params"].get("_scan_index") for k in kids],
}}))
''')
        data = json.loads([ln for ln in out.splitlines() if ln.startswith("RESULT")][-1][6:])
        created.append(data["master"])
        created += data["children"]
        created += [j for j in data["manifest"] if j not in data["children"]]

        indices = data["indices"]
        counts = Counter(indices)
        dupes = {i: n for i, n in counts.items() if n > 1}

        check("the scan ran and produced children", len(data["children"]) > 0,
              f"master={data['master']}")
        check("every image was dispatched exactly once", not dupes,
              f"indices={sorted(indices)}",
              fail_detail=f"dispatched more than once: {dupes}")
        check("the manifest holds exactly one line per image",
              len(data["manifest"]) == N_POINTS,
              f"{len(data['manifest'])} line(s) for {N_POINTS} images",
              fail_detail="a duplicate dispatch appends a second line for an index")
        check("all three images are present, so nothing was lost either",
              set(indices) == set(range(N_POINTS)),
              f"distinct indices={sorted(set(indices))}")

    finally:
        user_c.close()
        cleanup_jobs(admin, created)
        cleanup_user(admin, user["id"])
        admin.close()

    summary()


if __name__ == "__main__":
    main()
