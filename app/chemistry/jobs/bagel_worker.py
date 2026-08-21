"""Subprocess entry point: `python -m app.chemistry.jobs.bagel_worker <spec.json>`."""
from __future__ import annotations

import json
import sys
import traceback

from app.chemistry.jobs import bagel_runner
from app.chemistry.jobs.base import JobResult, format_job_error, write_result
from app.chemistry.jobs.dispatch import resolve_runner

DISPATCH = {
    "single_point": bagel_runner.run_single_point,
    "casscf": bagel_runner.run_casscf,
    "caspt2": bagel_runner.run_caspt2,
    "gradient": bagel_runner.run_gradient,
    "nac": bagel_runner.run_nac,
    "geometry_optimization": bagel_runner.run_geometry_optimization,
    "frequency": bagel_runner.run_frequency,
    "opt_freq": bagel_runner.run_opt_freq,
    "mo_visualization": bagel_runner.run_mo_visualization,
    "custom": bagel_runner.run_custom,
}


def main(spec_path: str) -> None:
    spec = json.loads(open(spec_path).read())
    job_id = spec["job_id"]
    method = spec["method"]
    params = dict(spec.get("params", {}))
    params["_job_dir"] = str(spec_path).rsplit("/", 1)[0]
    # `spec.method` is the level of theory (see JobSpec's docstring in
    # base.py); runner internals were left reading params["method"]
    # unchanged, so it's injected here rather than persisted twice.
    params["method"] = method

    runner_key, error = resolve_runner(spec.get("task") or "", spec.get("subtype") or "", method)
    fn = DISPATCH.get(runner_key) if runner_key else None
    if fn is None:
        write_result(JobResult(job_id, "failed", error=error or f"BAGEL backend has no handler for "
                               f"{spec.get('task')}/{spec.get('subtype')}"))
        sys.exit(1)

    try:
        outcome = fn(spec["molecule"], params)
        write_result(JobResult(job_id, "completed", summary=outcome["summary"], artifacts=outcome["artifacts"]))
    except Exception as e:
        write_result(JobResult(job_id, "failed", error=format_job_error(e)))
        sys.exit(1)


if __name__ == "__main__":
    main(sys.argv[1])
