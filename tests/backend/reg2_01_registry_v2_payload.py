#!/usr/bin/env python3
"""The job-registry route serves the v2 capability tables, and only those.

    PYTHONPATH=$PWD python3 tests/backend/reg2_01_registry_v2_payload.py

Phase 1 dark-launched `app/chemistry/registry2/` behind the existing
`GET /api/job-registry` route, alongside a byte-identical v1 payload for
comparison. P2B.3 deleted `app/chemistry/jobs/registry.py` outright (no
importer needed it once P2B.1/2/4 finished), so there is no v1 module left
to compare against -- the negative assertion below is now a fixed list of
the v1-only key names the route must never re-introduce.

The rest checks that the v2 payload is actually usable by a client: it is
JSON round-trippable (a dataclass or a tuple leaking through would 500 the
route only when someone opened the approval card), every task carries its
parameters and per-method engine support, and the capability rows carry
both the raw field values and the `available` view that says what will
actually be routed.

Runs in-process against the FastAPI app -- no server, no engines, no
database. The route falls back to unauthenticated access when auth is not
configured, which is exactly the local-dev path this exercises.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO))

from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.chemistry.registry2.capabilities import CANONICAL_METHODS, ENGINES  # noqa: E402
from app.chemistry.registry2.tasks import TASKS  # noqa: E402
from server.routes import registry as registry_route  # noqa: E402

failures: list[str] = []
checks = 0


def check(label: str, ok: bool, detail: str = "") -> None:
    global checks
    checks += 1
    if ok:
        print(f"  [PASS] {label}")
    else:
        print(f"  [FAIL] {label}" + (f" -- {detail}" if detail else ""))
        failures.append(label)


def main() -> int:
    # A bare app with only this router: the point is the payload, not the
    # rest of the server's startup (which wants Postgres and a model).
    app = FastAPI()
    app.include_router(registry_route.router)
    client = TestClient(app)

    print("\n== route responds ==")
    response = client.get("/api/job-registry")
    check("GET /api/job-registry returns 200", response.status_code == 200,
          f"got {response.status_code}")
    if response.status_code != 200:
        return 1
    payload = response.json()

    print("\n== the v1 payload is gone ==")
    # Phase 2 retired the v1 payload on purpose: nothing read the v1 keys --
    # the frontend's only consumer was a `useJobRegistryQuery` hook no
    # component ever called -- and serving a second copy of the capability
    # tables that nobody reads is how the two drift apart. P2B.3 deleted the
    # module those keys came from, so this is now a closed list rather than
    # a comparison against it.
    for key in ("methods", "default_engine", "allowed_engines", "required_params",
                "optional_params", "param_help"):
        check(f"v1 key {key!r} is no longer served", key not in payload,
              f"payload still has {key!r}")

    print("\n== v2 payload is present and well-formed ==")
    check("v2 key present", "v2" in payload)
    v2 = payload.get("v2", {})
    check("schema_version is 2", v2.get("schema_version") == 2, str(v2.get("schema_version")))
    check("engines match the capability module", v2.get("engines") == list(ENGINES))
    check("methods match the capability module", v2.get("methods") == list(CANONICAL_METHODS))
    check("every task is present", len(v2.get("tasks", [])) == len(TASKS),
          f"{len(v2.get('tasks', []))} vs {len(TASKS)}")

    print("\n== v2 is JSON round-trippable ==")
    try:
        round_tripped = json.loads(json.dumps(v2))
        check("survives a json.dumps/loads round trip", round_tripped == v2)
    except (TypeError, ValueError) as exc:
        check("survives a json.dumps/loads round trip", False, str(exc))

    print("\n== every task carries what a client needs to render it ==")
    tasks_missing_label = [t["name"] for t in v2.get("tasks", []) if not t.get("label")]
    check("every task has a label", not tasks_missing_label, str(tasks_missing_label))
    tasks_missing_support = [
        t["name"] for t in v2.get("tasks", []) if "engine_support" not in t
    ]
    check("every task has per-method engine support", not tasks_missing_support,
          str(tasks_missing_support))

    bad_params = []
    for task in v2.get("tasks", []):
        for spec in task.get("params", []):
            if not spec.get("name") or not spec.get("type"):
                bad_params.append((task["name"], spec))
            # A required parameter with no question is the failure mode
            # this whole layer exists to prevent: the backend knows
            # something is missing and cannot say what to ask.
            if spec.get("required_when") and not spec.get("ask"):
                bad_params.append((task["name"], spec.get("name")))
    check("every parameter has a name, a type, and a question if required",
          not bad_params, str(bad_params[:5]))

    print("\n== capability rows carry values AND what is actually routable ==")
    caps = v2.get("capabilities", {})
    # Derived rather than hardcoded. This asserted 15 while the registry had
    # 19, so it had been failing on a stale literal rather than on anything
    # about the payload; scripts/check_capability_matrix.py is the check that
    # actually guards the matrix's contents.
    from app.chemistry.registry2.capabilities import CAPABILITIES
    expected_rows = len(CAPABILITIES)
    check(f"one row per (engine, method) pair ({expected_rows})",
          len(caps) == expected_rows, f"payload has {len(caps)}")
    rows_missing_available = [k for k, r in caps.items() if "available" not in r]
    check("every row has the 'available' view", not rows_missing_available,
          str(rows_missing_available))
    # The single most important negative in the whole matrix, asserted end
    # to end through the API rather than only in the module: BAGEL's
    # fix_atom is silently ignored, so constrained optimization must not be
    # advertised for it no matter how the payload is assembled.
    bagel_cas = caps.get("bagel/casscf", {})
    check("BAGEL/casscf does not advertise constrained_opt",
          bagel_cas.get("available", {}).get("constrained_opt") is False,
          str(bagel_cas.get("available", {}).get("constrained_opt")))
    opt_constrained = next(
        (t for t in v2.get("tasks", []) if t["name"] == "opt/constrained"), None)
    check("opt/constrained lists no BAGEL support for casscf",
          opt_constrained is not None
          and "bagel" not in opt_constrained["engine_support"]["casscf"],
          str(opt_constrained and opt_constrained["engine_support"].get("casscf")))

    print(f"\n{checks - len(failures)}/{checks} checks passed")
    if failures:
        print(f"[FAIL] {len(failures)} check(s) failed")
        return 1
    print("[PASS] ALL CHECKS PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
