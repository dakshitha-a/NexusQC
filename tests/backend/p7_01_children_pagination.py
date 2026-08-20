#!/usr/bin/env python3
"""P7.3 -- children pagination is real windowing, not a sliced full scan.

`sub_job_ids_of` used to walk every job directory on disk (see git history
of app/chemistry/jobs/base.py) to find a master's children -- fine at the
job counts this deployment used to see, but its cost scaled with EVERY job
ever run, not with the master's own child count, which is exactly backwards
for a 500-sub-job pes_1d/interp_pes/wigner_spectra master polled every 3
seconds while running (see docs/OVERHAUL_PLAN.md's Phase 7 P7.3). P7.3
replaces that with a per-master children.jsonl manifest (appended to once
per child, from the one place a sub-job is ever created: JobManager.submit)
and adds offset/limit to GET /api/jobs/{id}/children so the drawer never
has to fetch every child at once either.

This script proves both halves against a REAL scan (not a synthetic
children.jsonl), sitting among a deliberately large number of UNRELATED
jobs -- per this phase's own design note, a fixture with only the master's
children in JOBS_DIR would pass even a full-scan implementation, since
there'd be nothing else to scan past.

Run:  PYTHONPATH=$PWD python3 tests/backend/p7_01_children_pagination.py
"""
from __future__ import annotations

import json
import sys
import time

from app.agent.tools import _build_scan_images
from app.chemistry.jobs import base as jobs_base
from app.chemistry.jobs.base import JobSpec, get_job_manager, read_spec, read_status, sub_job_ids_of, write_status
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


N_UNRELATED = 300
N_IMAGES = 12


def _pad_with_unrelated_jobs(molecule: dict, n: int) -> None:
    """N tiny, unrelated, already-"completed" jobs directly on disk -- no
    real compute, just spec.json + status.json, matching what a full
    JOBS_DIR scan would have had to read through for every one of them."""
    for _ in range(n):
        spec = JobSpec(task="single_point", subtype="gs", method="hf", engine="pyscf",
                        molecule=molecule, params={"basis": "sto-3g"})
        job_dir = spec.job_dir()
        (job_dir / "spec.json").write_text(json.dumps(spec.to_dict(), indent=2))
        write_status(spec.job_id, "completed", "unrelated noise job")


def main() -> int:
    m = resolve_molecule("water")
    _pad_with_unrelated_jobs(m.to_dict(), N_UNRELATED)
    print(f"  (padded JOBS_DIR with {N_UNRELATED} unrelated jobs)")

    mgr = get_job_manager()
    master = JobSpec(
        task="pes_1d", subtype="", method="hf", engine="pyscf",
        molecule=m.to_dict(),
        params={"basis": "sto-3g", "n_points": N_IMAGES,
                "coordinate": {"type": "bond", "atoms": [1, 2]}, "scan_range": [0.8, 1.3],
                "_scan_start_molecule": m.to_dict()},
    )
    images, coordinate_values, coordinate_label, _warnings = _build_scan_images(master.params)
    master_id = mgr.submit_scan(master, images, coordinate_values, coordinate_label)

    deadline = time.time() + 120
    sub_ids: list[str] = []
    while time.time() < deadline:
        sub_ids = sub_job_ids_of(master_id)
        statuses = [(read_status(sid) or {}).get("status") for sid in sub_ids]
        if len(sub_ids) == N_IMAGES and all(s in ("completed", "failed") for s in statuses):
            break
        time.sleep(1)
    check(f"all {N_IMAGES} images dispatched", len(sub_ids) == N_IMAGES, str(len(sub_ids)))

    indices = [(read_spec(sid) or {}).get("params", {}).get("_scan_index") for sid in sub_ids]
    check("sub_job_ids_of returns ascending _scan_index order", indices == sorted(indices), str(indices))

    manifest_path = JOBS_DIR / master_id / "children.jsonl"
    check("children.jsonl manifest was written", manifest_path.exists())
    manifest_ids = [ln.strip() for ln in manifest_path.read_text().splitlines() if ln.strip()]
    check("manifest holds exactly the dispatched child ids",
          set(manifest_ids) == set(sub_ids), f"manifest={manifest_ids} sub_ids={sub_ids}")

    # The actual complexity proof: sub_job_ids_of must not call read_spec
    # once per job in JOBS_DIR (300+ unrelated jobs plus 12 children) --
    # only once per manifest entry.
    calls = {"n": 0}
    real_read_spec = jobs_base.read_spec

    def _counting_read_spec(job_id):
        calls["n"] += 1
        return real_read_spec(job_id)

    jobs_base.read_spec = _counting_read_spec
    try:
        result = jobs_base.sub_job_ids_of(master_id)
    finally:
        jobs_base.read_spec = real_read_spec
    check(f"sub_job_ids_of makes O(children) read_spec calls, not O(all jobs)",
          calls["n"] <= N_IMAGES + 1, f"{calls['n']} calls against {N_UNRELATED} unrelated + {N_IMAGES} real children")
    check("that call still returns the right set", set(result) == set(sub_ids))

    # Pagination endpoint, called in-process (no DATABASE_URL configured in
    # this script's environment, so current_user_or_none(None) is a no-op --
    # same convention reg2b_02_scan_dispatch_e2e.py's sibling scripts rely on).
    from server.routes.jobs import get_scan_children

    page1 = get_scan_children(master_id, None, offset=0, limit=5)
    check("page 1: total is the real child count", page1["total"] == N_IMAGES, str(page1["total"]))
    check("page 1: offset echoed", page1["offset"] == 0)
    check("page 1: 5 items", len(page1["items"]) == 5, str(len(page1["items"])))
    check("page 1: items are the first 5 in scan order",
          [row["job_id"] for row in page1["items"]] == sub_ids[:5])
    check("page 1: rows are trimmed (no summary/artifacts/molecule)",
          all("summary" not in row and "artifacts" not in row and "molecule" not in row for row in page1["items"]))

    page2 = get_scan_children(master_id, None, offset=10, limit=5)
    check("page 2 (offset=10, past the end): 2 items", len(page2["items"]) == 2, str(len(page2["items"])))
    check("page 2: items are the tail in scan order",
          [row["job_id"] for row in page2["items"]] == sub_ids[10:12])

    # Self-healing: a child evicted (e.g. by quota) drops out of both the
    # manifest read and the paginated route without any cleanup step.
    import shutil
    evicted = sub_ids[0]
    shutil.rmtree(JOBS_DIR / evicted, ignore_errors=True)
    after_evict = sub_job_ids_of(master_id)
    check("evicted child silently dropped from sub_job_ids_of",
          evicted not in after_evict and len(after_evict) == N_IMAGES - 1, str(after_evict))
    page_after = get_scan_children(master_id, None, offset=0, limit=100)
    check("evicted child silently dropped from the paginated route too",
          page_after["total"] == N_IMAGES - 1, str(page_after["total"]))

    print(f"\n{PASS}/{PASS + FAIL} checks passed")
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
