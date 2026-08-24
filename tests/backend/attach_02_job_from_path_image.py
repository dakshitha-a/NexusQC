#!/usr/bin/env python3
"""A new job can start from one named image of a path.

Seeing a path's geometries is half of it; the other half is being able to
say "optimize image 5" and have that resolve. A master job is deliberately
refused as a geometry source -- picking one of several arbitrarily would be
a wrong answer, not a convenience -- so before this there was no way to
name one at all. `source_geometry_image` alongside `source_geometry_job_id`
is that way, counting from 1, the same way the drawer and every message
about a path already count.

What has to hold, and cannot be settled by reading the code:

- the geometry that comes back is really that image's, not the master's own
  spec molecule (which is a real but arbitrary point of the path, so a
  wrong implementation looks right for image 1 and only image 1).
- both validate_draft passes agree. The approval card is rendered from one
  and the job is built from the other; if they disagreed, the card would
  describe a different structure than the one that ran.
- an out-of-range or unqualified image is refused in a way that says how to
  fix it, rather than resolving to something.

Runs inside the api container: a master's geometries come from its own path
file, whose recorded path is a container path.

    python3 tests/backend/attach_02_job_from_path_image.py
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent.parent

PASS = FAIL = 0


def check(label: str, ok: bool, detail: str = "") -> None:
    global PASS, FAIL
    if ok:
        PASS += 1
        print(f"  [PASS] {label}" + (f" -- {detail}" if detail else ""))
    else:
        FAIL += 1
        print(f"  [FAIL] {label}" + (f"\n         {detail}" if detail else ""))


IN_CONTAINER = r'''
import json, time
from app.chemistry.jobs import interpolate, geometry_resolve
from app.chemistry.jobs.base import JobSpec, get_job_manager, sub_job_ids_of, delete_job_dir
from app.chemistry.registry2.elicitation import validate_draft
from app.agent import tools as T

WATER = {"name": "water", "symbols": ["O", "H", "H"],
         "coords": [[0.0, 0.0, 0.117], [0.0, 0.757, -0.467], [0.0, -0.757, -0.467]],
         "charge": 0, "multiplicity": 1}
STRETCHED = {**WATER, "coords": [[0.0, 0.0, 0.117], [0.0, 1.457, -0.867], [0.0, -0.757, -0.467]]}

images, _w = interpolate.build_path(WATER, STRETCHED, 4, "linear")
mgr = get_job_manager()
master_id = mgr.submit_scan(
    JobSpec(task="interp_pes", subtype="", method="hf", engine="pyscf", molecule=images[0],
            params={"basis": "sto-3g", "n_points": 4, "interpolation_method": "linear",
                    "_end_molecule": STRETCHED, "_scan_start_molecule": WATER}),
    images, [float(i + 1) for i in range(4)], "image number (linear)",
)
plain_id = mgr.submit(JobSpec(task="single_point", subtype="", method="hf", engine="pyscf",
                              molecule=WATER, params={"basis": "sto-3g"}))
deadline = time.time() + 240
while time.time() < deadline:
    if all((mgr.status(j) or {}).get("status") in ("completed", "failed", "cancelled")
           for j in (master_id, plain_id)):
        break
    time.sleep(1.0)

out = {"master_id": master_id, "path_images": [im["coords"] for im in images]}

mol2, err2 = geometry_resolve.resolve_job_geometry(master_id, 2)
out["image_2"] = {"molecule": mol2, "error": err2}
out["image_1"] = geometry_resolve.resolve_job_geometry(master_id, 1)[0]
out["out_of_range"] = geometry_resolve.resolve_job_geometry(master_id, 99)[1]
out["zeroth"] = geometry_resolve.resolve_job_geometry(master_id, 0)[1]
out["no_image"] = geometry_resolve.resolve_job_geometry(master_id)[1]
out["not_a_path"] = geometry_resolve.resolve_job_geometry(plain_id, 2)[1]

# The draft path: both passes, and the molecule the job would really run on.
draft = {"task": "opt", "subtype": "min", "method": "hf", "engine": "pyscf",
         "params": {"basis": "sto-3g", "source_geometry_job_id": master_id,
                    "source_geometry_image": 2}}
v1 = validate_draft(dict(draft, params=dict(draft["params"])), {"molecule": None}, check_external=True)
v2 = validate_draft(dict(draft, params=dict(draft["params"])), {"molecule": None}, check_external=True)
out["draft_status"] = [v1.status, v2.status]
out["draft_asks"] = [getattr(v1, "ask_param", None), getattr(v2, "ask_param", None)]
resolved, resolve_err = T._resolve_draft_molecule(v1.draft, {"molecule": None})
out["draft_molecule"] = {"molecule": resolved, "error": resolve_err}

orphan = {"task": "opt", "subtype": "min", "method": "hf", "engine": "pyscf",
          "params": {"basis": "sto-3g", "source_geometry_image": 2}}
v3 = validate_draft(orphan, {"molecule": None}, check_external=True)
out["orphan_image"] = {"status": v3.status, "message": getattr(v3, "message", "") or str(v3.draft)}

for jid in [*sub_job_ids_of(master_id), master_id, plain_id]:
    try:
        mgr.cancel(jid)
    except Exception:
        pass
    try:
        delete_job_dir(jid)
    except Exception as e:
        out.setdefault("cleanup_errors", []).append(f"{jid}: {e}")

print("RESULT_JSON " + json.dumps(out))
'''


def same_geometry(a, b, tol=1e-6):
    """Coordinates agree to within the path file's own precision.

    The images are built in full float precision and written to the path
    file with 8 decimals, so a geometry read back from the file is that
    rounding of the one the sub-job ran on -- a difference of ~1e-9 A,
    which is nothing physically and everything to an == comparison. The
    file is also what the frame viewer and geometry_parameters read, so
    reading it here is what keeps a new job's structure identical to the
    one the user was looking at when they named the image.
    """
    if a is None or b is None or len(a) != len(b):
        return False
    return all(abs(x - y) < tol for ra, rb in zip(a, b) for x, y in zip(ra, rb))


def main() -> int:
    proc = subprocess.run(
        ["docker", "compose", "exec", "-T", "api", "python", "-c", IN_CONTAINER],
        cwd=REPO, capture_output=True, text=True, timeout=600,
    )
    line = next((l for l in proc.stdout.splitlines() if l.startswith("RESULT_JSON ")), None)
    if line is None:
        print(proc.stdout[-2000:])
        print(proc.stderr[-3000:], file=sys.stderr)
        check("the container run produced a result", False, "no RESULT_JSON line")
        return 1
    r = json.loads(line[len("RESULT_JSON "):])
    if r.get("cleanup_errors"):
        print(f"  (cleanup) {r['cleanup_errors']}")

    print("== an image resolves to that image's own structure ==")
    mol2 = r["image_2"]["molecule"]
    want2 = r["path_images"][1]
    check("image 2 resolves without error", r["image_2"]["error"] is None, str(r["image_2"]["error"]))
    check("its coordinates are image 2's, not the master's own spec molecule",
          bool(mol2) and same_geometry(mol2["coords"], want2)
          and not same_geometry(mol2["coords"], r["path_images"][0]),
          f"got {mol2 and mol2['coords']}")
    check("image 1 is the first image, so counting starts at 1",
          bool(r["image_1"]) and same_geometry(r["image_1"]["coords"], r["path_images"][0]))
    check("charge and multiplicity come from the master, since a frame carries neither",
          bool(mol2) and mol2["charge"] == 0 and mol2["multiplicity"] == 1)
    check("the name says where it came from",
          bool(mol2) and f"image 2 of job {r['master_id']}" in mol2["name"], mol2 and mol2["name"])

    print("\n== a number that names nothing is refused, and says how to fix it ==")
    check("past the end of the path, the real range is given",
          "numbered 1 to 4" in (r["out_of_range"] or ""), str(r["out_of_range"]))
    check("image 0 is refused too, rather than read as the first",
          "no image 0" in (r["zeroth"] or ""), str(r["zeroth"]))
    check("a path with no image named says which parameter names one",
          "source_geometry_image" in (r["no_image"] or ""), str(r["no_image"]))
    check("an image number on a job that is not a path is refused",
          "not a path" in (r["not_a_path"] or ""), str(r["not_a_path"]))

    print("\n== the draft path ==")
    check("a draft naming a job and an image is ready, not asking",
          r["draft_status"] == ["ready", "ready"], str(r["draft_status"]))
    check("both validate passes agree, so the card and the job cannot differ",
          r["draft_status"][0] == r["draft_status"][1] and r["draft_asks"][0] == r["draft_asks"][1])
    drafted = r["draft_molecule"]["molecule"]
    check("the job would run on image 2's structure",
          r["draft_molecule"]["error"] is None and bool(drafted)
          and same_geometry(drafted["coords"], want2),
          str(r["draft_molecule"]["error"] or (drafted and drafted["coords"])))
    check("an image with no job id is asked about rather than ignored",
          r["orphan_image"]["status"] == "incomplete", json.dumps(r["orphan_image"])[:200])

    print(f"\n{PASS}/{PASS + FAIL} checks passed in this script.")
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
