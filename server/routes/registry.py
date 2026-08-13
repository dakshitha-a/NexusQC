"""Read-only exposure of app/chemistry/jobs/registry.py's method/engine/
param schema, for the approval-card and job-detail-drawer param display."""
from __future__ import annotations

from fastapi import APIRouter

from app.chemistry.jobs import registry as job_registry

router = APIRouter()


@router.get("/api/job-registry")
def get_job_registry():
    return {
        "methods": job_registry.METHODS,
        "default_engine": job_registry.DEFAULT_ENGINE,
        "allowed_engines": {k: sorted(v) for k, v in job_registry.ALLOWED_ENGINES.items()},
        "required_params": job_registry.REQUIRED_PARAMS,
        "optional_params": job_registry.OPTIONAL_PARAMS,
        "param_help": job_registry.PARAM_HELP,
    }
