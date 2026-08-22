#!/usr/bin/env python3
"""Ask ORCA which functional keywords it actually accepts, and write the
answer to data/verified/orca_functionals.txt.

`keyword_suggest.py` used to state that ORCA had "no equivalent 'ask the
engine' validity oracle" and fell back to pool membership -- a regex over
all-caps tokens in the manual's DFT chapter. That is true of library
calls and false of ORCA itself: a single-atom single point answers in
well under a second, and answers unambiguously.

    accepted  ->  "FINAL SINGLE POINT ENERGY" / "ORCA TERMINATED NORMALLY"
    rejected  ->  "UNRECOGNIZED OR DUPLICATED KEYWORD(S) IN SIMPLE INPUT LINE"

The scrape is still how candidates are generated -- it is a good net --
but ORCA decides. A ten-keyword pilot found three classes of error the
manual could not have told us about: table fragments that look like
keywords (X_TPSS, B97X-D3, WHPBE0), a functional whose documented display
name is not its keyword (M06-2X is rejected; M062X is accepted), and
dispersion written as a separate keyword rather than a suffix (B3LYP D3BJ
accepted, B3LYP-D3BJ rejected).

Needs a licensed ORCA binary, so this cannot run in CI and the result is
committed as data rather than rebuilt on demand -- the same posture the
scraped manuals themselves already have. Re-run it after an ORCA upgrade.

    PYTHONPATH=$PWD python3 scripts/verify_orca_functionals.py
"""
from __future__ import annotations

import argparse
import subprocess
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.chemistry.jobs.keyword_suggest import _orca_functional_name_pool  # noqa: E402
from app.config import DATA_DIR, ORCA_BIN  # noqa: E402

OUT_PATH = DATA_DIR / "verified" / "orca_functionals.txt"

# Helium, and a basis set that comes with both auxiliary sets.
#
# STO-3G alone was the obvious choice and was wrong: every double hybrid
# (B2PLYP, DSD-BLYP, PWPB95, wB97X-2, the R2SCAN-*DH family -- 43 of them)
# came back inconclusive with "RI-MP2 needs an AuxC basis but none was
# defined!". That is not a rejected keyword, it is a perfectly good
# functional whose MP2 step had nothing to expand in, and recording it as
# a rejection would have silently deleted every double hybrid from the
# pool. def2-SVP with def2/J and def2-SVP/C gives them what they need and
# costs nothing on one helium atom.
_INPUT = (
    "! {keyword} def2-SVP def2/J def2-SVP/C\n"
    "%maxcore 500\n* xyz 0 1\nHe 0.0 0.0 0.0\n*\n"
)

# Keywords the DFT chapter documents that are not functionals: an
# integral approximation and a wavefunction method that happen to be
# named in the same tables. ORCA accepts them, so only an explicit
# exclusion keeps them out of a list of functionals to offer someone.
_NOT_FUNCTIONALS = {"RI", "MP2", "RI-MP2", "NOFROZENCORE", "FROZENCORE"}

_REJECTED_MARKER = "UNRECOGNIZED OR DUPLICATED KEYWORD(S)"
_ACCEPTED_MARKER = "ORCA TERMINATED NORMALLY"


def ask_orca(keyword: str, work_dir: Path, timeout: int = 120) -> bool | None:
    """True if ORCA accepts the keyword, False if it rejects it, None if
    the run was inconclusive (crash, timeout, missing licence) -- an
    inconclusive answer must never be recorded as a rejection, or one bad
    run silently deletes a real functional from the pool."""
    inp = work_dir / "probe.inp"
    inp.write_text(_INPUT.format(keyword=keyword))
    try:
        proc = subprocess.run(
            [str(ORCA_BIN), str(inp)],
            cwd=str(work_dir), capture_output=True, text=True, timeout=timeout,
        )
    except (subprocess.TimeoutExpired, OSError):
        return None
    out = proc.stdout + proc.stderr
    if _REJECTED_MARKER in out:
        return False
    if _ACCEPTED_MARKER in out:
        return True
    return None


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--limit", type=int, default=0, help="probe only the first N candidates (for a smoke run)")
    args = ap.parse_args()

    if not Path(ORCA_BIN).exists():
        print(f"ORCA not found at {ORCA_BIN} -- set QC_AGENT_ORCA_BIN. Nothing written.")
        return 2

    candidates = [c for c in _orca_functional_name_pool() if c.upper() not in _NOT_FUNCTIONALS]
    if args.limit:
        candidates = candidates[: args.limit]
    print(f"probing {len(candidates)} scraped candidates against {ORCA_BIN}")

    accepted, rejected, inconclusive = [], [], []
    started = time.time()
    with tempfile.TemporaryDirectory() as tmp:
        work = Path(tmp)
        for i, keyword in enumerate(candidates, start=1):
            verdict = ask_orca(keyword, work)
            (accepted if verdict is True else rejected if verdict is False else inconclusive).append(keyword)
            if i % 25 == 0 or i == len(candidates):
                print(f"  {i}/{len(candidates)}  accepted={len(accepted)} rejected={len(rejected)} "
                      f"inconclusive={len(inconclusive)}  ({time.time() - started:.0f}s)")
            # ORCA leaves scratch behind between runs; a stale .gbw from the
            # previous keyword makes the next run reuse it instead of
            # re-reading the input line we are actually testing.
            for stale in work.glob("probe.*"):
                if stale.suffix != ".inp":
                    stale.unlink(missing_ok=True)

    if not accepted:
        print("no keyword was accepted -- refusing to write an empty pool. Check the ORCA install.")
        return 1

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    header = [
        "# ORCA simple-input DFT functional keywords, verified by running ORCA.",
        "# Regenerate with: PYTHONPATH=$PWD python3 scripts/verify_orca_functionals.py",
        "# Do not hand-edit: every name here was accepted by a real ORCA run,",
        f"# and {len(rejected)} scraped candidates were rejected and left out.",
        f"# ORCA binary: {ORCA_BIN}",
        "",
    ]
    OUT_PATH.write_text("\n".join(header + sorted(accepted)) + "\n")

    print(f"\nwrote {len(accepted)} verified keywords to {OUT_PATH}")
    print(f"rejected {len(rejected)}: {', '.join(sorted(rejected)[:20])}"
          + (" ..." if len(rejected) > 20 else ""))
    if inconclusive:
        print(f"INCONCLUSIVE {len(inconclusive)} (not recorded either way): {', '.join(sorted(inconclusive))}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
