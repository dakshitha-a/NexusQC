#!/usr/bin/env python3
"""P7.4 -- `batch`: a master task fanning a single_point/gs job out over
every geometry in a tagged geometry_set, real end to end.

Scoped deliberately narrow (see docs/TRACKER.md's own P7.4 note): children
are single_point/gs only in this pass (a future phase can widen this the
same way wigner_spectra's children are currently fixed at single_point/ee),
and the geometry source is an existing geometry_set job id, not yet also
ad hoc individually-tagged molecule frames. Within that scope this is the
real path end to end: a real geometry_set job, a real batch draft through
registry2's own validate_draft, real PySCF single-point children dispatched
through JobManager.submit_batch/batch_orchestrator.py, and the P7.3
children-pagination route reused unmodified for a third master kind.

Run:  PYTHONPATH=$PWD python3 tests/backend/p7_04_batch_master.py
"""
from __future__ import annotations

import sys
import time

from app.agent.tools import _build_batch_spec_or_error, _resolve_batch_geometries
from app.chemistry.jobs.base import get_job_manager, read_spec, read_status, sub_job_ids_of
from app.chemistry.molecule import resolve_molecule
from app.chemistry.registry2.elicitation import validate_draft

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


WATER = resolve_molecule("water").to_dict()


def _wait_terminal(sub_ids: list[str], timeout_s: float = 180) -> dict[str, str]:
    deadline = time.time() + timeout_s
    statuses: dict[str, str] = {}
    while time.time() < deadline:
        statuses = {sid: (read_status(sid) or {}).get("status") for sid in sub_ids}
        if all(s in ("completed", "failed") for s in statuses.values()):
            break
        time.sleep(1)
    return statuses


def main() -> int:
    mgr = get_job_manager()

    # Three distinct geometries -- O-H bond stretched by a different
    # amount each time, so per-child geometry identity is easy to check.
    frames = []
    for i, dx in enumerate((0.0, 0.2, 0.4)):
        frames.append({
            "name": f"water {i}",
            "symbols": list(WATER["symbols"]),
            "coords": [[c[0] + dx, c[1], c[2]] for c in WATER["coords"]],
        })
    gs_id = mgr.submit_geometry_set(frames, label="p7_04 test set")
    check("geometry_set job is completed immediately", read_status(gs_id)["status"] == "completed")

    print("\n== _resolve_batch_geometries ==")
    geometries, error = _resolve_batch_geometries(gs_id)
    check("resolves the 3 geometries with no error", error is None, error)
    check("3 geometries resolved", geometries is not None and len(geometries) == 3,
          str(len(geometries) if geometries else None))
    check("each geometry defaults to charge=0/multiplicity=1",
          all(g["charge"] == 0 and g["multiplicity"] == 1 for g in geometries))

    bad_geometries, bad_error = _resolve_batch_geometries("no-such-job-id")
    check("a bad source job id refuses cleanly, not a crash",
          bad_geometries is None and bad_error is not None, bad_error)

    print("\n== validate_draft reaches 'ready' for a batch draft ==")
    draft = {
        "task": "batch", "subtype": "", "method": "hf", "engine": "pyscf",
        "params": {"basis": "sto-3g", "source_geometry_set_job_id": gs_id},
    }
    verdict = validate_draft(draft, {})
    check("draft status is ready", verdict.status == "ready", verdict.status)

    print("\n== batch dispatch end to end ==")
    from app.chemistry.jobs.base import JobSpec
    spec, preview, _kb, _notes, batch_note, _kw, warnings, build_error = _build_batch_spec_or_error(
        {}, "pyscf", "hf", {"basis": "sto-3g", "source_geometry_set_job_id": gs_id}, [],
    )
    check("builder returns a spec with no error", spec is not None and build_error is None, build_error)
    check("preview is job 1 of 3", "job 1 of 3" in (batch_note or ""), batch_note)
    check("no warnings for a well-formed batch", warnings == [], warnings)
    spec.task, spec.subtype = "batch", ""

    master_id = mgr.submit_batch(spec, geometries)
    sub_ids = sub_job_ids_of(master_id)
    check("3 children dispatched", len(sub_ids) == 3, str(sub_ids))
    for sid in sub_ids:
        child_spec = read_spec(sid) or {}
        check(f"{sid}: child is single_point/gs at the master's method",
              (child_spec.get("task"), child_spec.get("subtype"), child_spec.get("method")) == ("single_point", "gs", "hf"),
              f"got {child_spec.get('task')}/{child_spec.get('subtype')} @ {child_spec.get('method')!r}")
        check(f"{sid}: parent_job_id points at the batch master",
              child_spec.get("parent_job_id") == master_id)

    statuses = _wait_terminal(sub_ids)
    for sid, status in statuses.items():
        check(f"{sid}: reached completed", status == "completed", status)

    # This script runs standalone (no live server), so nothing ticks
    # BatchOrchestrator's own background thread the way server/main.py's
    # lifespan does -- drive its _update_one directly instead of starting
    # a real thread, same role a live poll tick plays.
    from app.chemistry.jobs.batch_orchestrator import get_batch_orchestrator
    orchestrator = get_batch_orchestrator()
    deadline = time.time() + 30
    master_status = None
    while time.time() < deadline:
        orchestrator._update_one(master_id)
        master_status = read_status(master_id)
        if master_status and master_status["status"] == "completed":
            break
        time.sleep(1)
    check("master reaches completed once every child is terminal",
          master_status is not None and master_status["status"] == "completed", master_status)

    result = mgr.result(master_id)
    summary = result["summary"]
    check("summary counts 3 complete, 0 failed",
          summary.get("n_complete") == 3 and summary.get("n_failed", 0) == 0, summary)

    print("\n== master_kind + children pagination reused unmodified for batch ==")
    from server.routes.jobs import _job_row, get_scan_children
    row = _job_row(master_id)
    check("master_kind is 'batch'", row["master_kind"] == "batch", row["master_kind"])

    page = get_scan_children(master_id, None, offset=0, limit=2)
    check("page 1: total is 3", page["total"] == 3, page["total"])
    check("page 1: 2 items", len(page["items"]) == 2, len(page["items"]))
    check("page 1: rows are trimmed (no summary/artifacts/molecule)",
          all("summary" not in r and "artifacts" not in r and "molecule" not in r for r in page["items"]))

    print(f"\n{PASS}/{PASS + FAIL} checks passed")
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
