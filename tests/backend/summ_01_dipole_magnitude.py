"""A job's dipole reaches the model as a magnitude, not only as a vector.

Found on 2026-11-10 while retaking the thesis screenshots: given water
HF/cc-pVDZ's dipole as the vector (-0.026, -2.075, 0.000) D, the model
reported "Dipole moment: 1.87 D" twice. The magnitude is 2.08 D. The
results table now carries dipole_magnitude_debye beside the vector.

In-process, no stack and no model needed:

    PYTHONPATH=$PWD python3 tests/backend/summ_01_dipole_magnitude.py
"""
from __future__ import annotations

import sys

from app.chemistry.jobs.summarize import _summary_as_markdown_table

PASS = FAIL = 0


def check(label: str, ok: bool, detail: str = "") -> None:
    global PASS, FAIL
    PASS += ok
    FAIL += not ok
    print(f"  [{'PASS' if ok else 'FAIL'}] {label}" + ("" if ok or not detail else f"\n         {detail}"))


def main() -> int:
    t = _summary_as_markdown_table({"total_energy_hartree": -76.026,
                                    "dipole_debye": [-0.0263061, -2.07545, -4.3e-16]})
    check("the vector is still shown", "| dipole_debye |" in t, t)
    check("its magnitude is shown beside it", "| dipole_magnitude_debye | 2.076 |" in t, t)
    t = _summary_as_markdown_table({"dipole_debye": None})
    check("no dipole, no magnitude row", "dipole_magnitude_debye" not in t, t)
    t = _summary_as_markdown_table({"total_energy_hartree": -1.0})
    check("a summary without a dipole is unchanged", "dipole" not in t, t)
    print(f"\n{PASS}/{PASS + FAIL} checks passed")
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
