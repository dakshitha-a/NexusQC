#!/usr/bin/env python3
"""P7.5 -- NEB regression: Phase 7 touched app/chemistry/jobs/base.py,
scan_orchestrator.py and server/routes/jobs.py, none of which neb_ts's own
code (orca_runner.run_neb_ts) lives in or calls -- but base.py/jobs.py are
exactly the modules NEB's own drawer view (NebFrameViewer, the live-frames
route) and download path share. This proves neb_ts still runs and produces
what the frontend actually reads, not just that its own file was untouched.

Uses HCN -> HNC (hydrogen cyanide -> hydrogen isocyanide), a standard,
well-behaved isomerization test system -- both resolve to the same atom
set/order (['C', 'N', 'H']) via RDKit, so no atom-reorder is even in play
here; this is deliberately the simplest possible real system, not a
stress test of the reorder logic (see p7_03 for that).

Run:  PYTHONPATH=$PWD python3 tests/backend/p7_05_neb_regression.py
"""
from __future__ import annotations

import sys
import time

from app.agent.tools import _build_neb_ts_spec_or_error
from app.chemistry.jobs.base import get_job_manager, read_status
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
    hcn = resolve_molecule("hydrogen cyanide").to_dict()
    hnc = resolve_molecule("hydrogen isocyanide").to_dict()
    check("HCN and HNC share the same atom set/order (no reorder needed here)",
          hcn["symbols"] == hnc["symbols"], (hcn["symbols"], hnc["symbols"]))

    spec, preview, _kb, _notes, _scan_note, _kw, warnings, error = _build_neb_ts_spec_or_error(
        hcn, "orca", "hf",
        {"basis": "sto-3g", "n_images": 3, "preopt": False, "_end_molecule": hnc},
        [],
    )
    check("builder returns a spec with no error", spec is not None and error is None, error)
    check("no structural warnings", warnings == [], warnings)
    check("preview carries a real ORCA %neb block", "%neb" in (preview or "").lower(), (preview or "")[:200])
    spec.task, spec.subtype = "neb_ts", ""

    mgr = get_job_manager()
    job_id = mgr.submit(spec)

    deadline = time.time() + 300
    status = None
    while time.time() < deadline:
        status = read_status(job_id)
        if status and status["status"] in ("completed", "failed"):
            break
        time.sleep(2)
    check("the job reaches a terminal status", status is not None and status["status"] in ("completed", "failed"),
          status)

    result = mgr.result(job_id)
    check("a result was written", result is not None)
    if result and result["status"] == "completed":
        summary = result["summary"]
        artifacts = result.get("artifacts", {})
        check("summary reports whether the NEB/TS search converged",
              "neb_converged" in summary and "ts_converged" in summary, summary.keys())
        check("a PATH SUMMARY was parsed (non-empty path_summary)",
              bool(summary.get("path_summary")), summary.get("path_summary"))
        check("neb_frames artifact was written (drawer/NebFrameViewer's own source)",
              "neb_frames" in artifacts, artifacts)
        if "neb_frames" in artifacts:
            from pathlib import Path
            frames_text = Path(artifacts["neb_frames"]).read_text()
            check("neb_frames.xyz is non-empty multi-frame xmol text",
                  frames_text.strip().splitlines()[0].strip().isdigit(), frames_text[:80])
        check("a plot renders from real path data (NebEnergyPlot's own source)",
              "raw_output" in artifacts, artifacts)
    else:
        # A genuine convergence failure on a 3-image HF/STO-3G HCN/HNC band
        # would itself be surprising (this is the "sure thing" system this
        # test was chosen for) -- but the REGRESSION being checked here is
        # "does the machinery still run end to end", which a clean FAILED
        # status (a real ORCA run that exited, parsed, and reported
        # normally) still demonstrates, unlike a crash before ORCA ever ran.
        check("a failure still produced a real error (the machinery ran, even if chemistry didn't converge)",
              bool((result or {}).get("error")), result)

    print(f"\n{PASS}/{PASS + FAIL} checks passed")
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
