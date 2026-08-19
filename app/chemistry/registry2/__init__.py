"""Registry v2 -- the declarative capability/task/parameter tables.

Replaces `app/chemistry/jobs/registry.py`'s hand-maintained per-job-type
engine and parameter dicts with four factored tables and one derivation:

- `capabilities` -- what each (engine, method) pair can compute here, cell
  by cell, with the evidence for each claim.
- `tasks` -- what a user can ask for, as predicates over those
  capabilities. `supports()` is derived, never enumerated.
- `params` -- which parameters a task needs, when, and what to ask, as
  serializable conditions rather than Python branches.
- `routing` -- which engine runs it when the user named none.
- `lookup` -- the mechanical façade the agent and the API ask, so a
  capability question is answered by a table rather than from a model's
  weights.

Dark-launched in Phase 1: nothing in the running app reads this yet except
the v2 half of `GET /api/job-registry`. Phase 2 switches the agent and the
job pipeline over to it.
"""
from __future__ import annotations

from app.chemistry.registry2.capabilities import (
    CANONICAL_METHODS, CAPABILITIES, CAPABILITY_FIELDS, ENGINES, Evidence, MethodCaps,
    get_caps,
)
from app.chemistry.registry2.params import (
    PARAMS, PARAMS_BY_NAME, ParamSpec, defaults_for, evaluate, missing_required,
    params_for,
)
from app.chemistry.registry2.routing import ENGINE_PREFERENCE, RoutingDecision, route_engine
from app.chemistry.registry2.tasks import (
    TASKS, SupportVerdict, TaskDef, engines_supporting, get_task, supports,
)

__all__ = [
    "CANONICAL_METHODS", "CAPABILITIES", "CAPABILITY_FIELDS", "ENGINES", "Evidence",
    "MethodCaps", "get_caps",
    "PARAMS", "PARAMS_BY_NAME", "ParamSpec", "defaults_for", "evaluate",
    "missing_required", "params_for",
    "ENGINE_PREFERENCE", "RoutingDecision", "route_engine",
    "TASKS", "SupportVerdict", "TaskDef", "engines_supporting", "get_task", "supports",
]
