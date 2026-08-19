"""Read-only exposure of the registry v2 capability/task/parameter tables,
for the approval card and the job-detail drawer."""
from __future__ import annotations

from fastapi import APIRouter, Request

from app.auth.ownership import current_user_or_none
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
    # v2 only, as of Phase 2. The v1 half (methods/default_engine/
    # allowed_engines/required_params/optional_params/param_help, mirroring
    # app/chemistry/jobs/registry.py) was dark-launched alongside this one
    # in Phase 1 and is gone now that nothing reads it -- confirmed by
    # grep, not assumed: the frontend's only consumer was a
    # `useJobRegistryQuery` hook no component ever called, removed in the
    # same commit. Serving a second copy of the capability tables that
    # nobody reads is how the two drift apart.
    #
    # `v2` is kept as the key rather than being flattened to the top level,
    # so a caller written against the dark-launched shape keeps working and
    # `schema_version` inside it stays the thing to branch on.
    return {"v2": registry2_lookup.catalog()}
