#!/usr/bin/env python3
"""An interpolated path's geometries travel with the job.

Attaching or tagging an `interp_pes` master used to hand the model the
energies along the path and nothing else -- it could see that image 5
exists and what it costs, but not what it IS, so "optimize image 5" or
"run a frequency job at the top of the barrier" had nothing to resolve
against. `job_context_summary` now appends every image's geometry as an
xyz block, which is the exact shape `set_geometry` accepts back.

Two properties this checks that a code read cannot settle:

- the geometries are there for a STILL-RUNNING master, not only a
  finished one. They come from the master's own path file, written in
  full at submission time, so unlike the energies they never wait on a
  sub-job; starting a new job from one image while the rest of the path
  runs is a normal thing to want.
- the section is capped by images x atoms. This text is the model's own
  input on every check_job_status call, not only on an attach, so an
  unbounded dump would be paid for repeatedly.

Runs the assertions INSIDE the api container: artifact paths in a job's
result.json are container paths (/app/data/...), so reading them from the
host is guaranteed to fail. Needs the docker-compose stack, and the api
image must carry the code under test (`docker compose build api`) -- only
./data is bind-mounted, app/ is baked in.

    python3 tests/backend/attach_01_path_geometries.py
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
from app.chemistry.jobs import interpolate
from app.chemistry.jobs.base import (
    JobSpec, get_job_manager, sub_job_ids_of, delete_job_dir,
)
from app.chemistry.jobs.summarize import job_context_summary

WATER = {"name": "water", "symbols": ["O", "H", "H"],
         "coords": [[0.0, 0.0, 0.117], [0.0, 0.757, -0.467], [0.0, -0.757, -0.467]],
         "charge": 0, "multiplicity": 1}
STRETCHED = {**WATER, "coords": [[0.0, 0.0, 0.117], [0.0, 1.157, -0.667], [0.0, -0.757, -0.467]]}

N_POINTS = 4
images, _warnings = interpolate.build_path(WATER, STRETCHED, N_POINTS, "linear")
mgr = get_job_manager()
master_id = mgr.submit_scan(
    JobSpec(task="interp_pes", subtype="", method="hf", engine="pyscf", molecule=images[0],
            params={"basis": "sto-3g", "n_points": N_POINTS, "interpolation_method": "linear",
                    "_end_molecule": STRETCHED, "_scan_start_molecule": WATER}),
    images, [float(i + 1) for i in range(N_POINTS)], "image number (linear)",
)

# Read it back immediately: the path file is written by submit_scan itself,
# so this is the still-running case by construction.
while_running = job_context_summary(master_id)

deadline = time.time() + 240
while time.time() < deadline:
    if (mgr.status(master_id) or {}).get("status") in ("completed", "failed", "cancelled"):
        break
    time.sleep(1.0)
final_status = (mgr.status(master_id) or {}).get("status")
when_done = job_context_summary(master_id)

# The cap, exercised without needing a big molecule: shrink the limit and
# re-render the same master.
import app.chemistry.jobs.summarize as summarize
summarize.MAX_GEOMETRY_ATOM_LINES = 4
capped = job_context_summary(master_id)
summarize.MAX_GEOMETRY_ATOM_LINES = 400

# A plain single point has one geometry rather than a path, and gets it in
# the same xyz form.
plain_id = mgr.submit(JobSpec(task="single_point", subtype="", method="hf", engine="pyscf",
                              molecule=WATER, params={"basis": "sto-3g"}))
deadline = time.time() + 120
while time.time() < deadline:
    if (mgr.status(plain_id) or {}).get("status") in ("completed", "failed", "cancelled"):
        break
    time.sleep(1.0)
plain_text = job_context_summary(plain_id)

# A statistical ensemble is deliberately excluded, so check the gate itself
# rather than paying for a real 50-sample Wigner run to prove it.
import app.chemistry.jobs.summarize as _s
ensemble_gated = _s._ordered_geometries_section(master_id, {"task": "wigner_spectra"}) == ""

# An NEB band comes through the same reader under a different artifact key
# (neb_frames rather than path_xyz). Checked structurally, against a real
# multi-frame file but a stand-in job, rather than paying minutes of ORCA
# compute for a path-reading check that has nothing engine-specific in it.
import app.chemistry.jobs.geometry_resolve as _gr
_path_xyz = (mgr.result(master_id)["artifacts"])["path_xyz"]


class _FakeMgr:
    def result(self, job_id):
        return {"artifacts": {"neb_frames": _path_xyz}, "summary": {}}


_real_get = _gr.get_job_manager
_gr.get_job_manager = lambda: _FakeMgr()
try:
    _frames, _labels, _coord, _err = _gr.resolve_ordered_master_frames("fake-neb", {"task": "neb_ts"})
    neb = {"error": _err, "n_frames": len(_frames or []), "labels": _labels,
           "coordinate_label": _coord,
           "frame_names": [f.name for f in (_frames or [])][:2]}
finally:
    _gr.get_job_manager = _real_get

out = {"master_id": master_id, "final_status": final_status, "while_running": while_running,
       "when_done": when_done, "capped": capped, "plain_text": plain_text,
       "ensemble_gated": ensemble_gated, "neb": neb}

# Clean up: the master, its images, and the plain job. A suite run must not
# leave jobs in everyone's list.
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


def main() -> int:
    print("== seed an interpolated path in the api container and read its context back ==")
    proc = subprocess.run(
        ["docker", "compose", "exec", "-T", "api", "python", "-c", IN_CONTAINER],
        cwd=REPO, capture_output=True, text=True, timeout=600,
    )
    line = next((l for l in proc.stdout.splitlines() if l.startswith("RESULT_JSON ")), None)
    if line is None:
        print(proc.stdout[-2000:])
        print(proc.stderr[-2000:], file=sys.stderr)
        check("the container run produced a result", False, "no RESULT_JSON line")
        return 1
    r = json.loads(line[len("RESULT_JSON "):])
    print(f"  master={r['master_id']} final_status={r['final_status']}")
    if r.get("cleanup_errors"):
        print(f"  (cleanup) {r['cleanup_errors']}")

    running, done, capped, plain = r["while_running"], r["when_done"], r["capped"], r["plain_text"]

    print("\n== a still-running path already carries its geometries ==")
    check("the running master's context names its geometries",
          "Geometries (4 images, 3 atoms each)" in running, running[:200])
    check("every image is labelled by its own number",
          all(f"Image {i}" in running for i in (1, 2, 3, 4)))
    check("the coordinates themselves are there, as xyz blocks",
          running.count("\nO ") >= 4 and running.count("\nH ") >= 8)
    check("the model is told how to start a job from one",
          "set_geometry" in running)

    print("\n== a finished path carries them too, alongside the energies ==")
    check("the finished master's context still names its geometries",
          "Geometries (4 images, 3 atoms each)" in done)
    check("the energies are still reported", "energies_hartree" in done)

    print("\n== the section is bounded by images x atoms ==")
    check("past the limit, the endpoints are kept",
          "Image 1 (" in capped and "Image 4 (" in capped)
    check("...and the middle is described rather than printed",
          "Images 2 to 3 are not printed here" in capped, capped[-300:])
    check("...so the capped section is much smaller than the full one",
          len(capped) < len(done), f"{len(capped)} vs {len(done)} chars")

    print("\n== a job with one geometry carries that one ==")
    check("a plain single point carries the structure it ran on",
          "The geometry this job ran on (3 atoms)" in plain, plain[:200])
    check("...in the same form set_geometry accepts",
          "set_geometry" in plain and plain.count("\nO ") >= 1)
    check("...and is not described as a path", "Geometries (" not in plain)

    print("\n== a statistical ensemble is deliberately left out ==")
    check("a wigner_spectra master lists no per-sample geometries",
          r["ensemble_gated"] is True,
          "its samples are a random cloud, not an ordered set anyone names an element of")

    print("\n== an NEB band reads through the same path reader ==")
    neb = r["neb"]
    check("neb_ts resolves its frames from its own neb_frames artifact",
          neb["error"] is None and neb["n_frames"] == 4, json.dumps(neb)[:200])
    check("...labelled by image number, since an NEB band has no scan coordinate",
          neb["coordinate_label"] == "frame" and neb["labels"] == ["1", "2", "3", "4"],
          json.dumps(neb)[:200])

    print(f"\n{PASS}/{PASS + FAIL} checks passed in this script.")
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
