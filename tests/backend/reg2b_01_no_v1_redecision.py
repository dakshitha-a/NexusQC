#!/usr/bin/env python3
"""P2B.1/P2B.3 -- registry2 decides, submit_draft's builders construct only,
and the v1 registry module they used to call is gone.

Before P2B.1, `_build_spec_or_error` and its four per-task builders in
app/agent/tools.py re-decided what `registry2.elicitation.validate_draft`
had already decided: six `missing_required_params` calls and four
`default_engine` calls, live in the submit path, each capable of disagreeing
with the draft that already said READY. This asserts the v1 decision
functions are unreachable from submit_draft -- not merely unused by
today's test cases, but genuinely gone from the module that used to call
them -- and, since P2B.3, that the module itself no longer exists.

Run:  PYTHONPATH=$PWD python3 tests/backend/reg2b_01_no_v1_redecision.py
"""
from __future__ import annotations

import inspect
import sys

from app.agent import tools as agent_tools

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


def run_module_gone() -> None:
    # P2B.1 only made default_engine/missing_required_params unreachable
    # from submit_draft; registry.py itself, and its other exports
    # (METHODS, PARAM_HELP), were left in place until they had somewhere
    # else to live. P2B.3 finished that: PARAM_HELP's job moved to
    # registry2.params.PARAMS_BY_NAME[...].help and nothing else imported
    # the module, so it was deleted outright rather than kept around for
    # these two functions alone.
    print("== registry.py no longer exists ==")
    try:
        import app.chemistry.jobs.registry  # noqa: F401
        check("app.chemistry.jobs.registry does not import", False,
              "the module still exists -- P2B.3 was supposed to delete it")
    except ModuleNotFoundError:
        check("app.chemistry.jobs.registry does not import", True)


def main() -> int:
    run_not_imported()
    run_not_called()
    run_module_gone()

    total = PASS + FAIL
    print(f"\n{PASS}/{total} checks passed")
    if FAIL:
        print(f"[FAIL] {FAIL} check(s) failed")
        return 1
    print("[PASS] ALL CHECKS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
