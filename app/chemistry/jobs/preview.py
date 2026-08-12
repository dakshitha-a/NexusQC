"""Engine-agnostic entry point for generating a human-readable preview of
what a job would actually run -- the literal .inp/.json text for ORCA/
BAGEL, or an equivalent driver script for PySCF (which has no input-file
format of its own). Used both by the "just show me the input" tool and as
the thing the user approves before submit_job actually runs anything.
"""
from __future__ import annotations

from app.chemistry.jobs.base import JobSpec


def build_input_preview(spec: JobSpec) -> str:
    if spec.engine == "pyscf":
        from app.chemistry.jobs import pyscf_runner
        return pyscf_runner.build_input_preview(spec.method, spec.molecule, spec.params)
    if spec.engine == "orca":
        from app.chemistry.jobs import orca_runner
        return orca_runner.build_input_text(spec.method, spec.molecule, spec.params)
    if spec.engine == "bagel":
        from app.chemistry.jobs import bagel_runner
        return bagel_runner.build_input_preview(spec.method, spec.molecule, spec.params)
    raise ValueError(f"Unknown engine '{spec.engine}'")
