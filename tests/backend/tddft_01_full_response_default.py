#!/usr/bin/env python3
"""P2.3 -- full TDDFT is what runs when nobody says otherwise.

TDA is cheaper and less prone to triplet instabilities, but it is an
approximation to the linear response, and a user who asks for "a TDDFT
spectrum" means the complete thing. The app used to default to TDA and
label the result "TDDFT" on the job card, which is a silent substitution
of one calculation for another.

Asserted where it actually matters -- in the generated engine input, not
in the parameter dict -- because that is the artefact the user approves and
the engine executes. A default flipped in the registry but not reaching the
input file would leave every one of these passing while TDA still ran.

The ORCA form asserted here is `%tddft ... tda false`, which is what Phase
0's spike verified against a real ORCA 6.1.1 run
(scripts/spikes/spike_orca_caps.py, "full TDDFT vs TDA"). OVERHAUL_PLAN.md
speaks of emitting `%tddft RPA true`; that phrasing was never run against
the installed binary, and this repo's standing rule is that engine input is
written against real output rather than documentation.

Run:  PYTHONPATH=$PWD python3 tests/backend/tddft_01_full_response_default.py
"""
from __future__ import annotations

import sys

from app.chemistry.jobs.base import JobSpec
from app.chemistry.jobs.preview import build_input_preview
from app.chemistry.molecule import resolve_molecule
from app.chemistry.registry2.params import PARAMS_BY_NAME, applicable_warnings, defaults_for

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


def preview(engine: str, params: dict) -> str:
    spec = JobSpec(method="tddft", engine=engine, molecule=WATER, params=params)
    return build_input_preview(spec)


WATER = resolve_molecule("water").to_dict()
BASE = {"method": "dft", "functional": "b3lyp", "basis": "sto-3g", "n_states": 3}


def main() -> int:
    print("== the registry's own default ==")
    spec = PARAMS_BY_NAME["use_tda"]
    check("use_tda defaults to False (full response)", spec.default is False,
          f"default is {spec.default!r}")
    filled = defaults_for("single_point", "ee")
    check("so a fresh excited-state draft carries use_tda=False",
          filled.get("use_tda") is False, f"defaults_for gave {filled.get('use_tda')!r}")

    print("\n== what reaches the ORCA input ==")
    text = preview("orca", dict(BASE))
    check("the %tddft block turns TDA off", "tda false" in text.lower(),
          text[:400])
    check("and does not leave it on", "tda true" not in text.lower(), text[:400])
    text_tda = preview("orca", dict(BASE, use_tda=True))
    check("asking for TDA explicitly still gets it", "tda true" in text_tda.lower(),
          text_tda[:400])

    print("\n== what reaches the PySCF driver ==")
    text = preview("pyscf", dict(BASE))
    check("the driver builds a full TDDFT object", "tdscf.TDDFT(mf)" in text, text[:400])
    check("not a TDA one", "tdscf.TDA(mf)" not in text, text[:400])
    text_tda = preview("pyscf", dict(BASE, use_tda=True))
    check("asking for TDA explicitly still gets it", "tdscf.TDA(mf)" in text_tda,
          text_tda[:400])

    print("\n== the user is told which one ran ==")
    warnings = applicable_warnings("single_point", "ee", "dft", "orca",
                                   {**BASE, "use_tda": False})
    check("a full-TDDFT job says so on the approval card",
          any("Full TDDFT" in w for w in warnings), f"warnings={list(warnings)}")
    warnings = applicable_warnings("single_point", "ee", "dft", "orca",
                                   {**BASE, "use_tda": True})
    check("and a TDA job says that instead",
          any("Tamm-Dancoff approximation" in w for w in warnings),
          f"warnings={list(warnings)}")
    warnings = applicable_warnings("single_point", "ee", "hf", "orca",
                                   {**BASE, "method": "hf", "use_tda": False})
    check("with an HF reference it is named TD-HF/RPA, not TDDFT",
          any("TD-HF/RPA" in w for w in warnings), f"warnings={list(warnings)}")
    warnings = applicable_warnings("single_point", "ee", "casscf", "orca",
                                   {"basis": "sto-3g", "active_electrons": 4,
                                    "active_orbitals": 4, "n_states": 3})
    check("and a CASSCF job is told nothing about TDA at all",
          not any("Tamm-Dancoff" in w or "TDDFT" in w for w in warnings),
          f"warnings={list(warnings)}")

    total = PASS + FAIL
    print(f"\n{PASS}/{total} checks passed")
    if FAIL:
        print(f"[FAIL] {FAIL} check(s) failed")
        return 1
    print("[PASS] ALL CHECKS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
