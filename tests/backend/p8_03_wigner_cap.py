#!/usr/bin/env python3
"""Phase 8 P8.3 -- wigner_spectra's n_samples ceiling, raised 250->500.

Narrow and mechanical on purpose: the actual live route
(GET /api/jobs/{id}/wigner_transitions) and the frontend's live broadening
slider are covered end to end, against a real 6-sample ensemble and a real
browser, by tests/frontend/p8_03_wigner_broadening.spec.mjs -- this script
only pins the enforced ceiling itself and the fact that the card's own
promised number (registry2/params.py's n_samples ParamSpec help/ask text)
actually matches what app/agent/tools.py enforces. That drift is exactly
the bug this step found and fixed: the ParamSpec text already said "the
maximum is 500" while _MAX_ENSEMBLE_SAMPLES still enforced 250, so a user
following the card's own instructions could ask for 500 and be refused.

Run:  PYTHONPATH=$PWD python3 tests/backend/p8_03_wigner_cap.py
"""
from __future__ import annotations

import sys

from app.agent.tools import _MAX_ENSEMBLE_SAMPLES
from app.chemistry.registry2.params import PARAMS_BY_NAME

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


def main() -> int:
    check("the enforced ceiling is 500, not the old 250", _MAX_ENSEMBLE_SAMPLES == 500,
          str(_MAX_ENSEMBLE_SAMPLES))

    n_samples_spec = PARAMS_BY_NAME["n_samples"]
    check("the card's own help text names the SAME ceiling the code enforces",
          str(_MAX_ENSEMBLE_SAMPLES) in n_samples_spec.help,
          f"help={n_samples_spec.help!r}")
    check("the card's own ask text names the SAME ceiling the code enforces",
          str(_MAX_ENSEMBLE_SAMPLES) in n_samples_spec.ask,
          f"ask={n_samples_spec.ask!r}")
    check("n_samples has no silent default -- still asked for explicitly",
          n_samples_spec.default is None)

    print(f"\n{PASS} passed, {FAIL} failed")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
