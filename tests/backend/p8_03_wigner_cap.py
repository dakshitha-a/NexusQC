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

Also exercises the boundary itself against _build_ensemble_spec_or_error
directly (n_samples=500 clears the ceiling check, 501 is refused by name):
the constant and the help text can agree with each other and both still be
wrong about what the enforcement code does at 500/501 -- a stale 250 ceiling
would have passed every other assertion in this file unchanged.

Run:  PYTHONPATH=$PWD python3 tests/backend/p8_03_wigner_cap.py
"""
from __future__ import annotations

import sys

from app.agent.tools import _MAX_ENSEMBLE_SAMPLES, _build_ensemble_spec_or_error
from app.chemistry.registry2.params import PARAMS_BY_NAME

WATER = {"name": "water", "symbols": ["O", "H", "H"],
         "coords": [[0.0, 0.0, 0.117], [0.0, 0.757, -0.467], [0.0, -0.757, -0.467]],
         "charge": 0, "multiplicity": 1}

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

    # The constant and the help text can agree with each other and still be
    # wrong about what the enforcement code actually does at the boundary --
    # 250/251 would have passed every check above unchanged. Exercise the
    # real ceiling check in _build_ensemble_spec_or_error directly: 500 must
    # clear it (and fail later, for an unrelated reason -- no real source
    # job exists), 501 must be refused BY NAME, citing the ceiling.
    *_, error_500 = _build_ensemble_spec_or_error(
        WATER, "pyscf", "hf",
        {"n_samples": 500, "source_frequency_job_id": None}, [])
    check("n_samples=500 clears the ceiling (fails later, not on the ceiling check)",
          error_500 is not None and "n_samples must be" not in error_500,
          error_500)

    *_, error_501 = _build_ensemble_spec_or_error(
        WATER, "pyscf", "hf",
        {"n_samples": 501, "source_frequency_job_id": None}, [])
    check("n_samples=501 is refused, naming the ceiling",
          error_501 is not None and "n_samples must be" in error_501 and "500" in error_501,
          error_501)

    print(f"\n{PASS} passed, {FAIL} failed")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
