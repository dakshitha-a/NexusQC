#!/usr/bin/env python3
"""P7.1 -- pes_1d refuses BAGEL and recommends interp_pes; interp_pes and
every other engine on pes_1d are unaffected.

Not a capability gap: every pes_1d image dispatches as an ordinary
single_point/gs sub-job (see JobManager.submit_scan / scan_orchestrator.py),
which BAGEL runs identically to PySCF/ORCA. This is a scope decision --
`registry2.tasks.pes_1d`'s TaskDef now carries `engines=("pyscf", "orca")`,
the same "this app's implementation, not the engine's physics" allow-list
mechanism neb_ts's ORCA-only restriction already used, plus a new
`engine_denial_hint` surfaced through the same refusal-text path routing
already uses for every other denial (route_engine -> RoutingDecision.
refusals -> the elicitation loop's ask_user_exactly) -- no special-cased
branch anywhere, only registry data.

Run:  PYTHONPATH=$PWD python3 tests/backend/p7_02_bagel_pes1d_denial.py
"""
from __future__ import annotations

import subprocess
import sys

from app.chemistry.molecule import resolve_molecule
from app.chemistry.registry2.elicitation import validate_draft
from app.chemistry.registry2.routing import route_engine
from app.chemistry.registry2.tasks import supports

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


WATER = resolve_molecule("water").to_dict()
STATE = {"molecule": WATER}


def main() -> int:
    # -- supports() ----------------------------------------------------
    v = supports("bagel", "casscf", "pes_1d")
    check("bagel/casscf/pes_1d: refused", not v.supported)
    check("refusal names PYSCF, ORCA as the allowed engines",
          "PYSCF" in v.reasons[0] and "ORCA" in v.reasons[0], v.reasons)
    check("refusal recommends interp_pes", "interp_pes" in v.reasons[0], v.reasons)

    for engine, method in [("pyscf", "hf"), ("orca", "hf"), ("bagel", "casscf")]:
        ok = supports(engine, method, "interp_pes").supported
        check(f"interp_pes unaffected on {engine}/{method}", ok)
    for engine, method in [("pyscf", "hf"), ("orca", "hf")]:
        ok = supports(engine, method, "pes_1d").supported
        check(f"pes_1d unaffected on {engine}/{method}", ok)

    # -- route_engine() --------------------------------------------------
    decision = route_engine("casscf", "pes_1d", "", requested_engine="bagel")
    check("routing refuses an explicit BAGEL pes_1d request", decision.engine is None)
    check("routing's refusal text also recommends interp_pes",
          any("interp_pes" in r for r in decision.refusals), decision.refusals)
    check("routing offers PySCF/ORCA as alternatives",
          set(decision.alternatives) == {"pyscf", "orca"}, decision.alternatives)

    unrequested = route_engine("casscf", "pes_1d", "", requested_engine=None)
    check("routing with no engine named still avoids BAGEL",
          unrequested.engine in ("pyscf", "orca"), unrequested.engine)

    # -- validate_draft(): the actual elicitation-loop path -----------------
    draft = {"task": "pes_1d", "subtype": "", "method": "casscf", "engine": "bagel",
              "params": {"basis": "sto-3g", "active_space": [2, 2],
                         "coordinate": {"type": "bond", "atoms": [1, 2]}, "scan_range": [0.8, 1.4]}}
    verdict = validate_draft(draft, STATE)
    check("draft status is 'unavailable', not a crash or a silent substitution",
          verdict.status == "unavailable", verdict.status)
    check("the question posed to the user names interp_pes",
          "interp_pes" in (verdict.ask_user_exactly or ""), verdict.ask_user_exactly)
    check("the question offers PySCF/ORCA",
          set(verdict.alternatives or ()) == {"pyscf", "orca"}, verdict.alternatives)

    # interp_pes itself must still reach 'ready' for bagel/casscf (only
    # pes_1d is restricted) -- both endpoints supplied since interp_pes
    # needs a second geometry.
    interp_draft = {
        "task": "interp_pes", "subtype": "", "method": "casscf", "engine": "bagel",
        "params": {"basis": "sto-3g", "active_space": [2, 2], "n_points": 3,
                   "_end_molecule": WATER},
    }
    interp_verdict = validate_draft(interp_draft, STATE)
    check("interp_pes/bagel is not refused by this change",
          interp_verdict.status != "unavailable", interp_verdict.status)

    # -- docs/QM_CAPABILITIES.md stays in sync with the registry ----------
    gen = subprocess.run([sys.executable, "scripts/generate_capability_docs.py", "--check"],
                          capture_output=True, text=True)
    check("generated capability matrix already reflects the new bagel/pes_1d gap",
          gen.returncode == 0, gen.stdout + gen.stderr)

    print(f"\n{PASS}/{PASS + FAIL} checks passed")
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
