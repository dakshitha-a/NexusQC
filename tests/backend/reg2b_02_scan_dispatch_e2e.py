#!/usr/bin/env python3
"""P2B.2/P2B.4 -- a real pes_1d scan reaches the PySCF worker and completes.

Every other P2B.2/4 check exercises the builders directly (tax_01, scan_01,
reg_01_wigner_prep) or asserts on a JobSpec that is never actually
submitted. None of them prove the one edit where a mistake produces N
malformed jobs instead of one clean error: `JobManager.submit_scan`'s
child-spec construction (`task="single_point", subtype="gs",
method=master_spec.method`, replacing the old
`method=master_spec.params["scan_job_type"]`) and each worker's new
`dispatch.resolve_runner`-based DISPATCH lookup (replacing
`DISPATCH.get(spec["method"])`).

This submits a real water HF/STO-3G pes_1d scan (3 points, seconds of
PySCF compute) through the actual `JobManager.submit_scan` path used by
`_finish_submission`, and asserts every child spec is shaped the way
`submit_scan` is now supposed to write it and every child reaches
`completed` -- i.e. the worker's own dispatch resolved a callable, not just
that the spec looks right.

Run:  PYTHONPATH=$PWD python3 tests/backend/reg2b_02_scan_dispatch_e2e.py
"""
from __future__ import annotations

import sys
import time

from app.agent.tools import _build_scan_images
from app.chemistry.jobs.base import JobSpec, get_job_manager, read_spec, read_status, sub_job_ids_of
from app.chemistry.molecule import resolve_molecule

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


def main() -> int:
    m = resolve_molecule("water")
    mgr = get_job_manager()

    master = JobSpec(
        task="pes_1d", subtype="", method="hf", engine="pyscf",
        molecule=m.to_dict(),
        params={"basis": "sto-3g", "n_points": 3,
                "coordinate": {"type": "bond", "atoms": [1, 2]}, "scan_range": [0.8, 1.2],
                "_scan_start_molecule": m.to_dict()},
    )
    images, coordinate_values, coordinate_label, _warnings = _build_scan_images(master.params)
    check("3 images built", len(images) == 3, str(len(images)))

    master_id = mgr.submit_scan(master, images, coordinate_values, coordinate_label)
    sub_ids = sub_job_ids_of(master_id)
    check("3 sub-jobs were dispatched", len(sub_ids) == 3, str(sub_ids))

    for sid in sub_ids:
        spec = read_spec(sid) or {}
        check(f"{sid}: child is single_point/gs at the master's method",
              (spec.get("task"), spec.get("subtype"), spec.get("method"))
              == ("single_point", "gs", "hf"),
              f"got {spec.get('task')}/{spec.get('subtype')} @ {spec.get('method')!r}")

    deadline = time.time() + 90
    statuses: dict[str, str] = {}
    while time.time() < deadline:
        statuses = {sid: (read_status(sid) or {}).get("status") for sid in sub_ids}
        if all(s in ("completed", "failed") for s in statuses.values()):
            break
        time.sleep(1)

    for sid, status in statuses.items():
        check(f"{sid}: reached completed (worker dispatch resolved a callable)",
              status == "completed", f"status={status!r}")

    print("\n== P4.3's trickle-dispatch rewrite still threads image0_raw_input correctly ==")
    # submit_scan used to inject a hand-edited approval-card input into
    # image 0's own sub_spec directly, inline in its own dispatch loop.
    # P4.3 moved that loop into scan_orchestrator.py's _dispatch_more
    # (stashing the text on the master's own params under
    # "_image0_raw_input" so a LATER wave can still apply it -- see
    # submit_scan's own docstring) -- this is the one path that carries a
    # user's edited engine input through that rewrite, and nothing else
    # in this suite submits a scan with image0_raw_input set.
    master2 = JobSpec(
        task="pes_1d", subtype="", method="hf", engine="pyscf",
        molecule=m.to_dict(),
        params={"basis": "sto-3g", "n_points": 3,
                "coordinate": {"type": "bond", "atoms": [1, 2]}, "scan_range": [0.8, 1.2],
                "_scan_start_molecule": m.to_dict()},
    )
    images2, coordinate_values2, coordinate_label2, _warnings2 = _build_scan_images(master2.params)
    HAND_EDITED = "! HF STO-3G\n* xyz 0 1\nO 0.0 0.0 0.0\n*\n"
    master2_id = mgr.submit_scan(master2, images2, coordinate_values2, coordinate_label2, image0_raw_input=HAND_EDITED)
    sub_ids2 = sub_job_ids_of(master2_id)
    check("3 sub-jobs were dispatched for the image0_raw_input scan", len(sub_ids2) == 3, str(sub_ids2))
    by_index = {}
    for sid in sub_ids2:
        spec = read_spec(sid) or {}
        by_index[spec.get("params", {}).get("_scan_index")] = spec.get("params", {}).get("_raw_input")
    check("image 0 carries the hand-edited input byte-identically",
          by_index.get(0) == HAND_EDITED, repr(by_index.get(0)))
    check("image 1 carries no _raw_input (only image 0's own literal file applies)",
          by_index.get(1) is None, repr(by_index.get(1)))
    check("image 2 carries no _raw_input either",
          by_index.get(2) is None, repr(by_index.get(2)))
    mgr.cancel(master2_id)

    total = PASS + FAIL
    print(f"\n{PASS}/{total} checks passed")
    if FAIL:
        print(f"[FAIL] {FAIL} check(s) failed")
        return 1
    print("[PASS] ALL CHECKS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
