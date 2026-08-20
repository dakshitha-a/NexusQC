#!/usr/bin/env python3
"""P7.5 -- one bad master must not stall every other master's dispatch.

Found live while seeding a 105-child pes_1d scan for the Playwright
drawer-latency spec: a leftover pes_1d master (created via a bare host
Python process, so its own artifacts['path_xyz'] was written as an
ABSOLUTE HOST PATH -- e.g. /data/.../data/jobs/<id>/path.xyz -- rather
than the container's own /app/data/jobs/<id>/path.xyz) raised
FileNotFoundError on every _poll_once() tick, inside the SAME unguarded
for-loop every OTHER running scan master's dispatch went through. The
outer _loop try/except ("a single bad tick must never kill the
orchestrator thread") protected the thread from dying, but not sibling
masters from being skipped -- ~20 genuinely healthy running scans sat
stalled at their initial wave indefinitely, no error surfaced anywhere,
because the exception aborted _poll_once() partway through its loop
every single tick, forever.

Fixed identically in scan_orchestrator.py, ensemble_orchestrator.py and
batch_orchestrator.py (same shape in all three): _poll_once()'s own loop
now catches per master, not just once around the whole tick.

This script proves the fix, not just describes it: a real broken master
(a genuinely unreadable path_xyz) sits alongside a real healthy one in
the same _poll_once() call, and the healthy one must still progress.

Run:  PYTHONPATH=$PWD python3 tests/backend/p7_orchestrator_fault_isolation.py
"""
from __future__ import annotations

import sys
import time

from app.agent.tools import _build_scan_images
from app.chemistry.jobs.base import JobSpec, get_job_manager, read_status, sub_job_ids_of, write_result, write_status
from app.chemistry.jobs.scan_orchestrator import get_scan_orchestrator
from app.chemistry.molecule import resolve_molecule
from app.config import JOBS_DIR

PASS = 0
FAIL = 0


def check(label: str, ok: bool, detail: str = "") -> None:
    global PASS, FAIL
    if ok:
        PASS += 1
        print(f"  [PASS] {label}")
    else:
        FAIL += 1
        print(f"  [FAIL] {label}" + (f"\n         {detail}" if detail else ""))


def make_poisoned_master(molecule: dict) -> str:
    """A real pes_1d master whose result.json points at a path_xyz that
    genuinely does not exist -- the same failure shape the live foreign-
    path jobs produced (FileNotFoundError inside _dispatch_more), built
    directly rather than needing a second filesystem namespace to
    reproduce it in."""
    import json
    import uuid

    from app.chemistry.jobs.base import JobResult

    job_id = uuid.uuid4().hex[:12]
    spec = JobSpec(task="pes_1d", subtype="", method="hf", engine="pyscf", molecule=molecule,
                   params={"basis": "sto-3g", "n_points": 3,
                           "coordinate": {"type": "bond", "atoms": [1, 2]}, "scan_range": [0.8, 1.3]},
                   job_id=job_id)
    job_dir = spec.job_dir()
    (job_dir / "spec.json").write_text(json.dumps(spec.to_dict(), indent=2))
    write_status(job_id, "running", "submitting 3 images")
    write_result(JobResult(job_id, "running", summary={"n_images": 3, "n_dispatched": 0},
                           artifacts={"path_xyz": str(job_dir / "path.xyz")}))
    # Deliberately never write path.xyz itself -- _dispatch_more's own
    # Path(path_xyz).read_text() raises FileNotFoundError, matching the
    # live bug's failure mode exactly.
    return job_id


def main() -> int:
    m = resolve_molecule("water").to_dict()
    orch = get_scan_orchestrator()

    print("== a poisoned master (unreadable path_xyz) ==")
    poisoned_id = make_poisoned_master(m)
    check("poisoned master really does raise inside _dispatch_more",
          _raises(orch, poisoned_id))

    print("\n== a real, healthy pes_1d master, submitted alongside it ==")
    mgr = get_job_manager()
    healthy_master = JobSpec(
        task="pes_1d", subtype="", method="hf", engine="pyscf", molecule=m,
        params={"basis": "sto-3g", "n_points": 4,
                "coordinate": {"type": "bond", "atoms": [1, 2]}, "scan_range": [0.8, 1.3],
                "_scan_start_molecule": m},
    )
    images, coordinate_values, coordinate_label, _w = _build_scan_images(healthy_master.params)
    healthy_id = mgr.submit_scan(healthy_master, images, coordinate_values, coordinate_label)
    healthy_children = sub_job_ids_of(healthy_id)
    check("healthy master's initial wave dispatched", len(healthy_children) == 4, str(healthy_children))

    print("\n== _poll_once(): the poisoned master raising must not stop the healthy one's own tick ==")
    # Simulates one real orchestrator tick with BOTH masters present --
    # not calling _dispatch_more directly on the healthy one, so this
    # only passes if _poll_once()'s own per-master isolation is real.
    import app.chemistry.jobs.scan_orchestrator as scan_orch_mod
    real_iter = scan_orch_mod._iter_running_scan_masters
    scan_orch_mod._iter_running_scan_masters = lambda: iter([poisoned_id, healthy_id])
    try:
        raised = False
        try:
            orch._poll_once()
        except Exception:
            raised = True
        check("_poll_once() itself does not raise even with a poisoned master in the batch", not raised)
    finally:
        scan_orch_mod._iter_running_scan_masters = real_iter

    deadline = time.time() + 180
    healthy_statuses: list[str] = []
    while time.time() < deadline:
        healthy_statuses = [(read_status(sid) or {}).get("status") for sid in sub_job_ids_of(healthy_id)]
        if all(s in ("completed", "failed") for s in healthy_statuses):
            break
        time.sleep(1)
    check("the healthy master's children still reach a terminal status "
          "(not silently starved by the poisoned sibling)",
          len(healthy_statuses) == 4 and all(s == "completed" for s in healthy_statuses),
          healthy_statuses)

    print(f"\n{PASS}/{PASS + FAIL} checks passed")
    return 0 if FAIL == 0 else 1


def _raises(orch, master_id: str) -> bool:
    from app.chemistry.jobs.base import read_spec
    spec = read_spec(master_id)
    try:
        orch._dispatch_more(master_id, spec, 3)
    except Exception:
        return True
    return False


if __name__ == "__main__":
    sys.exit(main())
