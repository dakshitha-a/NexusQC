#!/usr/bin/env python3
"""A batch of couplings over a scan's geometries, end to end.

Submits a real `batch` master through the job manager, lets the
orchestrator dispatch and aggregate its children, and checks the thing a
user actually wanted: one coupling per state pair at every geometry,
collected into a curve against the scan's own coordinate.

The source scan is built here rather than tagged from data/jobs, so this
runs anywhere and leaves nothing behind but its own jobs -- which it
deletes at the end, per this project's rule that a test cleans up the jobs
it creates and never purges anything it did not.

Deliberately small: two images, SA-CASSCF(2,2)/STO-3G on ethylene. The
point is the plumbing (dispatch, per-child indexing, aggregation, the
plot), and every engine-level claim it would otherwise duplicate is
already covered by grad_01.

Run:  PYTHONPATH=$PWD python3 tests/backend/batch_01_multi_geometry.py
"""
from __future__ import annotations

import os
import shutil
import sys
import time

from app.chemistry.jobs.base import (
    JobSpec, get_job_manager, read_result, read_status, sub_job_ids_of,
)
from app.chemistry.jobs.batch_orchestrator import get_batch_orchestrator
from app.config import JOBS_DIR

def _host_path(recorded: str):
    """An artifact path a job recorded, resolved to where this script can read it.

    A batch's `artifacts` dict mixes two kinds of path, and always has. Some are
    written by this script in process, so they are already host paths. The
    aggregate's plot is written by the batch orchestrator, which lives in the
    API process, and against the compose stack that process runs in a container
    where the same directory is `/app/data` -- `docker-compose.yml` bind-mounts
    `./data:/app/data`, so the two name identical bytes and only one of them
    exists from here.

    Without this, `os.path.exists(artifacts["batch_plot"])` passes when the API
    happens to be a bare host process and fails against the compose stack the
    suite is otherwise written for, which is not a difference this assertion
    means to be sensitive to.
    """
    text = str(recorded)
    prefix = "/app/data/jobs/"
    if text.startswith(prefix):
        return os.path.join(JOBS_DIR, text[len(prefix):])
    return text



PASS = 0
FAIL = 0
CREATED: list[str] = []


def check(label: str, ok: bool, detail: str = "") -> None:
    global PASS, FAIL
    if ok:
        PASS += 1
        print(f"  [PASS] {label}")
    else:
        FAIL += 1
        print(f"  [FAIL] {label}" + (f"\n         {detail}" if detail else ""))


# Two points of an ethylene torsion: planar, and twisted by 30 degrees.
_PLANAR = [[0.6120248, 0.26529847, 0.03353069], [-0.61202479, -0.26529846, -0.03353071],
           [1.49586907, -0.3436518, -0.12861611], [0.75428389, 1.31904059, 0.25189414],
           [-0.7542839, -1.31904059, -0.25189412], [-1.49586907, 0.34365179, 0.12861611]]
_TWISTED = [[0.6120248, 0.26529847, 0.03353069], [-0.61202479, -0.26529846, -0.03353071],
            [1.49586907, -0.3436518, -0.12861611], [0.75428389, 1.31904059, 0.25189414],
            [-1.09270, -0.90135, 0.62050], [-1.15600, 0.19860, -0.95360]]


def _molecule(coords, name):
    return {"name": name, "symbols": ["C", "C", "H", "H", "H", "H"],
            "coords": [list(c) for c in coords], "charge": 0, "multiplicity": 1}


def _wait(job_id: str, timeout: float = 3600) -> str:
    deadline = time.time() + timeout
    while time.time() < deadline:
        status = read_status(job_id)["status"]
        if status in ("completed", "failed", "cancelled"):
            return status
        time.sleep(3)
    return "timeout"


def main() -> int:
    mgr = get_job_manager()
    # The orchestrator's polling thread is started by server/main.py on
    # startup, not by importing the module -- so a standalone script has to
    # start it itself or the master would sit at "running" forever while its
    # children quietly finished. Same reason this script starts it rather
    # than reaching into _update_one directly: the point is to exercise the
    # dispatch-and-aggregate loop the server actually runs.
    get_batch_orchestrator().start()

    print("== a geometry set to batch over ==")
    # geometry_set is the simplest source: three or more structures held
    # together, no calculation of its own. Every other accepted source
    # (pes_1d, interp_pes, wigner_spectra, neb_ts) writes the same
    # multi-frame xmol artifact, so one of them exercises the reading path.
    frames = [_molecule(_PLANAR, "planar"), _molecule(_TWISTED, "twisted")]
    source_id = mgr.submit_geometry_set(frames)
    CREATED.append(source_id)
    check("the geometry set carries both structures on disk",
          bool((read_result(source_id) or {}).get("artifacts", {}).get("path_xyz")))

    print("\n== a batch of couplings over it ==")
    master = JobSpec(
        task="batch", subtype="", method="casscf", engine="pyscf",
        molecule=frames[0],
        params={"source_job_id": source_id, "child_task": "nac",
                "basis": "sto-3g", "active_electrons": 2, "active_orbitals": 2,
                "n_excited_states": 2, "n_states": 3,
                "state_pairs": [[1, 2], [1, 3], [2, 3]]},
    )
    master_id = mgr.submit_batch(master, frames)
    CREATED.append(master_id)
    status = _wait(master_id)
    sub_ids = sub_job_ids_of(master_id)
    CREATED.extend(sub_ids)
    check("the batch completes", status == "completed", status)
    check("one child per geometry, and no duplicates",
          len(sub_ids) == 2 and len(set(sub_ids)) == 2, str(sub_ids))

    result = read_result(master_id) or {}
    summary = result.get("summary") or {}
    check("every child succeeded", summary.get("n_failed") == 0, str(summary.get("n_failed")))

    print("\n== what the finished batch shows ==")
    # The point of the whole feature: not "2 of 2 succeeded" but a value
    # per pair per geometry, against the path.
    series = summary.get("series") or {}
    check("one series per state pair", sorted(series) == ["S0/S1", "S0/S2", "S1/S2"],
          str(sorted(series)))
    check("each series has a value at every geometry",
          all(len(v) == 2 and all(x is not None for x in v) for v in series.values()),
          str(series))
    check("the pairs are genuinely different from one another",
          len({round(v[0], 9) for v in series.values()}) == 3,
          str({k: v[0] for k, v in series.items()}))
    check("a coordinate axis is recorded for the curve",
          len(summary.get("coordinate_values") or []) == 2, str(summary.get("coordinate_values")))
    _plot = (result.get("artifacts") or {}).get("batch_plot", "")
    check("the plot was rendered",
          bool(_plot) and os.path.exists(_host_path(_plot)),
          f"{result.get('artifacts')} "
          f"(resolved to {_host_path(_plot) if _plot else '-'})")
    check("no aggregation error", "aggregate_error" not in summary, str(summary.get("aggregate_error")))

    print("\n== each child carries the full multi-pair result ==")
    child = read_result(sub_ids[0]) or {}
    child_summary = child.get("summary") or {}
    check("a child computed all three pairs in its own single job",
          child_summary.get("n_pairs") == 3, str(child_summary.get("n_pairs")))

    print(f"\n{PASS}/{PASS + FAIL} checks passed")
    return 1 if FAIL else 0


def cleanup() -> None:
    """Delete only what this script created. Never a blind purge -- job
    directories here may belong to someone's real work."""
    for job_id in CREATED:
        path = JOBS_DIR / job_id
        if path.is_dir():
            shutil.rmtree(path, ignore_errors=True)
    print(f"cleaned up {len(CREATED)} job(s) this script created")


if __name__ == "__main__":
    try:
        code = main()
    finally:
        cleanup()
    print("[PASS] ALL CHECKS PASSED" if code == 0 else "[FAIL] some checks failed")
    sys.exit(code)
