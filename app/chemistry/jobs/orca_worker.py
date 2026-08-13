"""Subprocess entry point: `python -m app.chemistry.jobs.orca_worker <spec.json>`."""
from __future__ import annotations

import json
import sys
import traceback

from app.chemistry.jobs import orca_runner
from app.chemistry.jobs.base import JobResult, write_result

DISPATCH = {
    "single_point": orca_runner.run_single_point,
    "geometry_optimization": orca_runner.run_geometry_optimization,
    "frequency": orca_runner.run_frequency,
    "tddft": orca_runner.run_tddft,
    "eom_ccsd": orca_runner.run_eom_ccsd,
    "casscf": orca_runner.run_casscf,
    "mo_visualization": orca_runner.run_mo_visualization,
}


def main(spec_path: str) -> None:
    spec = json.loads(open(spec_path).read())
    job_id = spec["job_id"]
    method = spec["method"]
    params = dict(spec.get("params", {}))
    params["_job_dir"] = str(spec_path).rsplit("/", 1)[0]

    fn = DISPATCH.get(method)
    if fn is None:
        write_result(JobResult(job_id, "failed", error=f"ORCA backend has no handler for method '{method}'"))
        sys.exit(1)

    try:
        outcome = fn(spec["molecule"], params)
        write_result(JobResult(job_id, "completed", summary=outcome["summary"], artifacts=outcome["artifacts"]))
    except Exception:
        write_result(JobResult(job_id, "failed", error=traceback.format_exc()))
        sys.exit(1)


if __name__ == "__main__":
    main(sys.argv[1])
