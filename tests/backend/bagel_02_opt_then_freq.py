"""BAGEL's CASSCF geometry optimisation, then frequencies on its result.

Until 2026-11-10 this pair was "structurally confirmed, not convergence-
verified", because BAGEL on the development host was believed unstable. It
was a test input instead: water CAS(4,4) in STO-3G has no virtual orbitals.
Run end to end on water CAS(8,6)/6-31G, the first real chain found two bugs:

- the optimised geometry named its atoms "O1", "H2", "H3" (labels from the
  molden file it is read back from), and a frequency job on it died in BAGEL
  with "Unknown Atom number in a basis set file. Requested: o1";
- the optimisation summary had no `converged` key, so anything that follows
  only a converged minimum never followed a BAGEL one.

The live half, against the ORCA numbers for the same system measured the
same day (r(OH) 0.9784 A, angle 106.94 deg, 1693 / 3572 / 3720 cm-1):

    BAGEL_02_LIVE=1 PYTHONPATH=$PWD python3 tests/backend/bagel_02_opt_then_freq.py

Without the flag only the parser checks run, which need no engine.
"""
from __future__ import annotations

import math
import os
import shutil
import sys
import tempfile

from app.chemistry.jobs.bagel_runner import _optimization_converged

PASS = FAIL = 0


def check(label: str, ok: bool, detail: str = "") -> None:
    global PASS, FAIL
    PASS += ok
    FAIL += not ok
    print(f"  [{'PASS' if ok else 'FAIL'}] {label}" + ("" if ok or not detail else f"\n         {detail}"))


def table(*flags: str) -> str:
    names = ("Gradient", "Displacement", "Energy change")
    rows = "\n".join(f"  * {n:<16}    0.000007      0.000010           {f}" for n, f in zip(names, flags))
    return f"  === Convergence status ===\n\n                         Maximum     Tolerance   Converged?\n{rows}\n\n"


def parser_checks() -> None:
    print("== the convergence table is read from opt.log, last table wins ==")
    d = tempfile.mkdtemp()
    try:
        first = table("No", "No", "No")
        check("bagel.out alone, first step only: not converged", _optimization_converged(d, first) is False)
        with open(os.path.join(d, "opt.log"), "w") as fh:
            fh.write(table("No", "No", "No") + table("Yes", "No", "Yes") + table("Yes", "Yes", "Yes"))
        check("opt.log's last table all Yes: converged", _optimization_converged(d, first) is True)
        with open(os.path.join(d, "opt.log"), "w") as fh:
            fh.write(table("Yes", "Yes", "Yes") + table("Yes", "No", "Yes"))
        check("a last table with a No: not converged", _optimization_converged(d, first) is False)
    finally:
        shutil.rmtree(d, ignore_errors=True)
    check("no table at all: unknown", _optimization_converged("/nonexistent", "no table") is None)


def live_checks() -> None:
    from app.chemistry.jobs import bagel_runner
    start = {"name": "water", "symbols": ["O", "H", "H"], "charge": 0, "multiplicity": 1,
             "coords": [[0.0, 0.0, 0.12], [0.0, 0.80, -0.48], [0.0, -0.74, -0.44]]}
    cas = {"method": "casscf", "basis": "6-31g", "active_electrons": 8, "active_orbitals": 6,
           "n_states": 1}
    root = tempfile.mkdtemp()
    for sub in ("opt", "freq"):
        os.makedirs(os.path.join(root, sub))
    try:
        print("\n== live: BAGEL CASSCF(8,6)/6-31G optimisation ==")
        opt = bagel_runner.run_geometry_optimization(start, {**cas, "_job_dir": os.path.join(root, "opt")})
        s = opt["summary"]
        g = s.get("optimized_geometry") or {}
        check("the optimisation reports converged", s.get("converged") is True, str(s.get("converged")))
        check("the optimised geometry names plain elements", g.get("symbols") == ["O", "H", "H"],
              str(g.get("symbols")))
        c = g.get("coords") or [[0, 0, 0]] * 3
        r1, r2 = math.dist(c[0], c[1]), math.dist(c[0], c[2])
        v1 = [c[1][i] - c[0][i] for i in range(3)]
        v2 = [c[2][i] - c[0][i] for i in range(3)]
        ang = math.degrees(math.acos(sum(a * b for a, b in zip(v1, v2)) / (math.hypot(*v1) * math.hypot(*v2))))
        check("symmetric, r(OH) within 0.002 A of ORCA's 0.9784", abs(r1 - 0.9784) < 0.002 and abs(r2 - 0.9784) < 0.002,
              f"{r1:.4f} {r2:.4f}")
        check("angle within 0.3 deg of ORCA's 106.94", abs(ang - 106.94) < 0.3, f"{ang:.2f}")

        print("\n== live: BAGEL frequencies on that geometry ==")
        freq = bagel_runner.run_frequency(g, {**cas, "_job_dir": os.path.join(root, "freq")})
        f = sorted(x for x in (freq["summary"].get("frequencies_cm-1") or []) if abs(x) > 50)
        check("three vibrational modes, none imaginary", len(f) == 3 and all(x > 0 for x in f), str(f))
        ref = (1693.0, 3571.9, 3720.0)
        check("each within 25 cm-1 of ORCA's", len(f) == 3 and all(abs(a - b) < 25 for a, b in zip(f, ref)),
              f"BAGEL {[round(x, 1) for x in f]} vs ORCA {list(ref)}")
    finally:
        shutil.rmtree(root, ignore_errors=True)


def main() -> int:
    parser_checks()
    if os.environ.get("BAGEL_02_LIVE"):
        live_checks()
    else:
        print("\n  [GAP] live BAGEL opt/freq not run (set BAGEL_02_LIVE=1; about 15 s)")
    print(f"\n{PASS}/{PASS + FAIL} checks passed")
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
