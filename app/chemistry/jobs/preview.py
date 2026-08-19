"""Engine-agnostic entry point for generating a human-readable preview of
what a job would actually run -- the literal .inp/.json text for ORCA/
BAGEL, or an equivalent driver script for PySCF (which has no input-file
format of its own). Used both by the "just show me the input" tool and as
the thing the user approves before submit_job actually runs anything.
"""
from __future__ import annotations

from app.chemistry.jobs.base import JobSpec
from app.chemistry.jobs.dispatch import resolve_runner


def build_input_preview(spec: JobSpec) -> str:
    runner_key, error = resolve_runner(spec.task or "", spec.subtype or "", spec.method)
    if runner_key is None:
        raise ValueError(error or f"No runner for {spec.task}/{spec.subtype}")
    # `spec.method` is the level of theory; each build_input_preview below
    # still reads it out of `params["method"]` (unchanged runner internals
    # -- see dispatch.py's module docstring), so it's injected into a copy
    # rather than persisted on `spec.params` itself.
    params = {**spec.params, "method": spec.method}
    if spec.engine == "pyscf":
        from app.chemistry.jobs import pyscf_runner
        return pyscf_runner.build_input_preview(runner_key, spec.molecule, params)
    if spec.engine == "orca":
        from app.chemistry.jobs import orca_runner
        return orca_runner.build_input_text(runner_key, spec.molecule, params)
    if spec.engine == "bagel":
        from app.chemistry.jobs import bagel_runner
        return bagel_runner.build_input_preview(runner_key, spec.molecule, params)
    raise ValueError(f"Unknown engine '{spec.engine}'")
