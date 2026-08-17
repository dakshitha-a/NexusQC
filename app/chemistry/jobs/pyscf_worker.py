"""Subprocess entry point: `python -m app.chemistry.jobs.pyscf_worker <spec.json>`.

Runs a single PySCF job to completion and writes result.json next to the
spec, so the parent process (JobManager) never has to hold PySCF/numpy
state across job boundaries.
"""
from __future__ import annotations

import json
import sys
import traceback

from app.chemistry.jobs import pyscf_runner
from app.chemistry.jobs.base import JobResult, format_job_error, write_result

DISPATCH = {
    "single_point": pyscf_runner.run_single_point,
    "geometry_optimization": pyscf_runner.run_geometry_optimization,
    "frequency": pyscf_runner.run_frequency,
    "opt_freq": pyscf_runner.run_opt_freq,
    "casscf": pyscf_runner.run_casscf,
    "tddft": pyscf_runner.run_tddft,
    "eom_ccsd": pyscf_runner.run_eom_ccsd,
    "mo_visualization": pyscf_runner.run_mo_visualization,
    "recommend_active_space": pyscf_runner.run_recommend_active_space,
    # No "pes_scan"/"wigner_ensemble" entry -- a master job is never
    # itself dispatched to a worker subprocess (see app/chemistry/jobs/
    # base.py's JobManager.submit_scan/submit_ensemble); its per-image/
    # per-sample sub-jobs are ordinary entries in this same table.
}


def main(spec_path: str) -> None:
    spec = json.loads(open(spec_path).read())
    job_id = spec["job_id"]
    method = spec["method"]
    params = dict(spec.get("params", {}))
    params["_job_dir"] = str(spec_path).rsplit("/", 1)[0]

    fn = DISPATCH.get(method)
    if fn is None:
        write_result(JobResult(job_id, "failed", error=f"PySCF backend has no handler for method '{method}'"))
        sys.exit(1)

    try:
        outcome = fn(spec["molecule"], params)
        write_result(JobResult(job_id, "completed", summary=outcome["summary"], artifacts=outcome["artifacts"]))
    except Exception as e:
        write_result(JobResult(job_id, "failed", error=format_job_error(e)))
        sys.exit(1)


if __name__ == "__main__":
    main(sys.argv[1])
