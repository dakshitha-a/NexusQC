"""Read-only exposure of app/chemistry/jobs/registry.py's method/engine/
param schema, for the approval-card and job-detail-drawer param display."""
from __future__ import annotations

from fastapi import APIRouter, Request

from app.auth.ownership import current_user_or_none
from app.chemistry.jobs import registry as job_registry
from app.chemistry.registry2 import lookup as registry2_lookup

router = APIRouter()


@router.get("/api/job-registry")
def get_job_registry(request: Request):
    """F-010: this was the only route in the app with no authentication of
    any kind -- and it could not have been gated as it was written, because
    the handler took no `Request` to read a session from. That made it an
    accident rather than a decision, which is the part worth fixing: the
    response is a complete map of every calculation this deployment can
    run, on which engines, with which parameters, and it was readable by
    any anonymous caller who could reach the port.

    The content is schema, not user data, so this is a small exposure.
    But the decision it was left to is not small: the public `:443`
    listener is a documented future step, and "everything requires a
    session except this one route nobody remembered" is not a posture to
    turn a public listener on top of.

    `current_user_or_none` is the same helper every other read-only route
    uses. It returns None -- and this route stays fully open -- when auth
    is not configured at all (local dev, `python -m server.main` with no
    Postgres), preserving that workflow exactly; when auth IS configured it
    401s an anonymous caller like everything else.
    """
    current_user_or_none(request)
    return {
        "methods": job_registry.METHODS,
        "default_engine": job_registry.DEFAULT_ENGINE,
        "allowed_engines": {k: sorted(v) for k, v in job_registry.ALLOWED_ENGINES.items()},
        "required_params": job_registry.REQUIRED_PARAMS,
        "optional_params": job_registry.OPTIONAL_PARAMS,
        "param_help": job_registry.PARAM_HELP,
        # Registry v2, dark-launched in Phase 1: served alongside the v1
        # keys above, which stay byte-identical so the current frontend is
        # untouched. Phase 2 switches the UI over and the v1 keys go then,
        # not now -- shipping both for one phase is what makes the
        # switchover a separate, revertible change rather than a flag day.
        "v2": registry2_lookup.catalog(),
    }
