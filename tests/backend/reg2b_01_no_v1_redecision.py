#!/usr/bin/env python3
"""P2B.1 -- registry2 decides, submit_draft's builders construct only.

Before this step, `_build_spec_or_error` and its four per-task builders in
app/agent/tools.py re-decided what `registry2.elicitation.validate_draft`
had already decided: six `missing_required_params` calls and four
`default_engine` calls, live in the submit path, each capable of disagreeing
with the draft that already said READY. This asserts the v1 decision
functions are unreachable from submit_draft -- not merely unused by
today's test cases, but genuinely gone from the module that used to call
them.

Run:  PYTHONPATH=$PWD python3 tests/backend/reg2b_01_no_v1_redecision.py
"""
from __future__ import annotations

import inspect
import sys

from app.agent import tools as agent_tools
from app.chemistry.jobs import registry as v1_registry

PASS = 0
FAIL = 0


def check(label: str, ok: bool, detail: str = "") -> None:
    global PASS, FAIL
    if ok:
        PASS += 1
        print(f"  [PASS] {label}")
    else:
        FAIL += 1
        print(f"  [FAIL] {label}" + (f"\n         {detail}" if detail else ""))


def run_not_imported() -> None:
    print("== the v1 decision functions are not names in tools.py's namespace ==")
    check("default_engine is not imported into app.agent.tools",
          not hasattr(agent_tools, "default_engine"))
    check("missing_required_params is not imported into app.agent.tools",
          not hasattr(agent_tools, "missing_required_params"))


def run_not_called() -> None:
    print("== no builder function's source calls either one ==")
    builders = [
        agent_tools._build_spec_or_error,
        agent_tools._build_scan_spec_or_error,
        agent_tools._build_neb_ts_spec_or_error,
        agent_tools._build_ensemble_spec_or_error,
        agent_tools._build_custom_spec_or_error,
        agent_tools._spec_from_draft,
    ]
    for fn in builders:
        src = inspect.getsource(fn)
        check(f"{fn.__name__} does not call default_engine(",
              "default_engine(" not in src)
        check(f"{fn.__name__} does not call missing_required_params(",
              "missing_required_params(" not in src)


def run_still_defined_elsewhere() -> None:
    # The functions themselves are not deleted here (that is P2B.3, once
    # registry.py's other exports -- METHODS, PARAM_HELP -- have somewhere
    # else to live). This step is about reachability from submit_draft,
    # not about the module's existence.
    print("== registry.py itself is untouched by this step (P2B.3's job) ==")
    check("default_engine is still defined in registry.py",
          callable(getattr(v1_registry, "default_engine", None)))
    check("missing_required_params is still defined in registry.py",
          callable(getattr(v1_registry, "missing_required_params", None)))


def main() -> int:
    run_not_imported()
    run_not_called()
    run_still_defined_elsewhere()

    total = PASS + FAIL
    print(f"\n{PASS}/{total} checks passed")
    if FAIL:
        print(f"[FAIL] {FAIL} check(s) failed")
        return 1
    print("[PASS] ALL CHECKS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
