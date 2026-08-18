#!/usr/bin/env python3
"""Phase 0 verification spike: what BAGEL on THIS host actually does.

    PYTHONPATH=$PWD python3 scripts/spikes/spike_bagel_caps.py [probe ...] [-v]

Same contract as spike_orca_caps.py: real (tiny) runs, and for each
capability both "did it run" and "can the datum a preview needs be found in
the output". BAGEL is the least-documented of the three engines here and the
one whose output this repo has parsed least, so the raw blocks printed on a
GAP verdict are the point of the exercise as much as the PASS lines are.

Note CLAUDE.local.md's standing warning: this host's BAGEL/MKL build is
genuinely slow and has produced a real dsyev/pdsyevd crash during orbital
canonicalisation. A probe that times out here is evidence about the host,
not necessarily about BAGEL, and is reported as such.

Water/STO-3G (svp where sto-3g is unavailable) throughout.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO))

from app.config import BAGEL_BIN, BAGEL_EXTRA_LIB_DIRS, BAGEL_ONEAPI_SETVARS  # noqa: E402

RESULTS: list[tuple[str, str, str]] = []
VERBOSE = "-v" in sys.argv
KEEP: list[str] = []

GEOM = [
    {"atom": "O", "xyz": [0.000, 0.000, 0.130]},
    {"atom": "H", "xyz": [0.100, 0.790, -0.510]},
    {"atom": "H", "xyz": [-0.040, -0.720, -0.430]},
]


def molecule_block(basis: str = "svp") -> dict:
    return {
        "title": "molecule", "basis": basis, "df_basis": f"{basis}-jkfit",
        "angstrom": True, "geometry": GEOM,
    }


def run_bagel(name: str, blocks: list[dict], timeout: int = 1800) -> tuple[str, Path, int]:
    d = Path(tempfile.mkdtemp(prefix=f"bagel-{name}-"))
    (d / "input.json").write_text(json.dumps({"bagel": blocks}, indent=1))
    cmd = (
        f"source {BAGEL_ONEAPI_SETVARS} > /dev/null 2>&1; "
        f"export OMP_NUM_THREADS=2 MKL_NUM_THREADS=2; "
        f'export LD_LIBRARY_PATH="{BAGEL_EXTRA_LIB_DIRS}:$LD_LIBRARY_PATH"; '
        f'cd "{d}" && "{BAGEL_BIN}" input.json > bagel.out 2>&1'
    )
    try:
        proc = subprocess.run(["bash", "-c", cmd], timeout=timeout)
        rc = proc.returncode
    except subprocess.TimeoutExpired:
        rc = -1
    out = (d / "bagel.out").read_text() if (d / "bagel.out").exists() else ""
    return out, d, rc


def record(cap: str, verdict: str, evidence: str, keep_dir: Path | None = None) -> None:
    RESULTS.append((cap, verdict, evidence))
    print(f"[{verdict:4s}] {cap}\n        {evidence}\n", flush=True)
    if verdict != "PASS" and keep_dir is not None:
        KEEP.append(str(keep_dir))
    elif keep_dir is not None and not VERBOSE:
        shutil.rmtree(keep_dir, ignore_errors=True)


def probe(cap: str):
    def deco(fn):
        fn._cap = cap
        return fn
    return deco


def tail(text: str, n: int = 14) -> str:
    return "\n        ".join(text.strip().splitlines()[-n:]) or "(no output)"


def section(text: str, header_re: str, n: int = 12) -> str | None:
    lines = text.splitlines()
    for i, ln in enumerate(lines):
        if re.search(header_re, ln, re.I):
            return "\n        ".join(lines[i:i + n])
    return None


# ------------------------------------------------------------------ probes

@probe("gradient: 'forces' block output format")
def p_forces():
    out, d, rc = run_bagel("forces", [
        molecule_block(),
        {"title": "forces", "grads": [{"title": "force", "target": 0}],
         "method": [{"title": "casscf", "nstate": 1, "nact": 4, "nclosed": 3}]},
    ])
    # Anchored on the exact header. A loose match on "gradient" also hits
    # "DIIS with orbital gradients will be used" in the SCF preamble, which
    # is present whether or not any nuclear gradient was ever computed.
    blk = section(out, r"^\s*Nuclear energy gradient\s*$", 16)
    if blk is None:
        return "GAP", f"rc={rc}; no 'Nuclear energy gradient' block. tail:\n        {tail(out)}", d
    return "PASS", f"rc={rc}; per-atom x/y/z gradient block:\n        {blk}", d


@probe("NAC: 'nacme' block (CASSCF)")
def p_nacme():
    out, d, rc = run_bagel("nacme", [
        molecule_block(),
        {"title": "forces", "grads": [{"title": "nacme", "target": 0, "target2": 1}],
         "method": [{"title": "casscf", "nstate": 2, "nact": 4, "nclosed": 3}]},
    ])
    blk = section(out, r"NACME|Non-adiabatic|nonadiabatic|interstate coupling", 16)
    if blk is None:
        return "GAP", f"rc={rc}; no NAC block located. tail:\n        {tail(out, 20)}", d
    return "PASS", f"rc={rc}; NAC block:\n        {blk}", d


@probe("optimize + hessian in one input")
def p_opt_hess():
    out, d, rc = run_bagel("optfreq", [
        molecule_block(),
        {"title": "optimize", "opttype": "energy", "maxiter": 5,
         "method": [{"title": "hf"}]},
        {"title": "hessian", "method": [{"title": "hf"}]},
    ], timeout=2400)
    freq = section(out, r"Frequencies|frequency|Vibrational", 14)
    if freq is None:
        return "GAP", f"rc={rc}; no frequency block. tail:\n        {tail(out, 20)}", d
    return "PASS", f"rc={rc}; opt then hessian in one input:\n        {freq}", d


@probe("orbital restart: save_ref / load_ref archive")
def p_ref_archive():
    """Which of BAGEL's two orbital-continuation mechanisms actually
    restarts a CASSCF -- the molden read-in or the binary archive -- decides
    the BAGEL half of the Phase 8 orbital-reuse feature."""
    out1, d1, rc1 = run_bagel("saveref", [
        molecule_block(),
        {"title": "hf"},
        {"title": "save_ref", "file": "orbitals"},
    ])
    arch = list(d1.glob("orbitals*"))
    if not arch:
        return "GAP", f"rc={rc1}; save_ref produced no archive file. tail:\n        {tail(out1)}", d1
    d2 = Path(tempfile.mkdtemp(prefix="bagel-loadref-"))
    for a in arch:
        shutil.copy(a, d2 / a.name)
    (d2 / "input.json").write_text(json.dumps({"bagel": [
        molecule_block(),
        {"title": "load_ref", "file": "orbitals"},
        {"title": "casscf", "nstate": 1, "nact": 4, "nclosed": 3},
    ]}, indent=1))
    cmd = (f"source {BAGEL_ONEAPI_SETVARS} > /dev/null 2>&1; export OMP_NUM_THREADS=2; "
           f'export LD_LIBRARY_PATH="{BAGEL_EXTRA_LIB_DIRS}:$LD_LIBRARY_PATH"; '
           f'cd "{d2}" && "{BAGEL_BIN}" input.json > bagel.out 2>&1')
    try:
        rc2 = subprocess.run(["bash", "-c", cmd], timeout=1800).returncode
    except subprocess.TimeoutExpired:
        rc2 = -1
    out2 = (d2 / "bagel.out").read_text() if (d2 / "bagel.out").exists() else ""
    shutil.rmtree(d1, ignore_errors=True)
    if rc2 != 0:
        return "GAP", f"load_ref run rc={rc2}. tail:\n        {tail(out2, 18)}", d2
    return "PASS", (f"save_ref wrote {[a.name for a in arch]}; load_ref + CASSCF ran (rc=0)"), d2


def _final_atom0(out: str) -> tuple | None:
    blocks = re.findall(
        r'\{ "atom" : "(\w+)", "xyz" : \[\s*([-\d.eE+]+),\s*([-\d.eE+]+),\s*([-\d.eE+]+)', out)
    return blocks[-3] if len(blocks) >= 3 else None


@probe("constrained optimization: does BAGEL expose one?")
def p_constrained():
    """The capability summary claims Cartesian atom-freezing; an earlier pass
    over the scraped manual found nothing.

    A zero exit code settles nothing here, and that is the whole point of the
    differential: BAGEL's JSON reader ACCEPTS an unrecognised key like
    'fix_atom' without complaint, so the constrained run exits 0 and looks
    successful. Comparing the optimized geometry against an unconstrained run
    of the same system is what exposes it -- if the supposedly frozen atom
    lands in exactly the same place either way, the key did nothing. Anything
    that reports on this capability from the exit code alone will report a
    feature this engine does not have."""
    constrained, d, rc = run_bagel("constr", [
        molecule_block(),
        {"title": "optimize", "opttype": "energy", "maxiter": 4,
         "fix_atom": [0], "method": [{"title": "hf"}]},
    ], timeout=1200)
    if rc != 0:
        err = section(out=constrained, header_re=r"error|unknown|not (yet )?(implemented|supported)", n=6)
        return "GAP", f"rc={rc}; {err or tail(constrained, 12)}", d
    free, d2, rc2 = run_bagel("unconstr", [
        molecule_block(),
        {"title": "optimize", "opttype": "energy", "maxiter": 4,
         "method": [{"title": "hf"}]},
    ], timeout=1200)
    a_con, a_free = _final_atom0(constrained), _final_atom0(free)
    shutil.rmtree(d2, ignore_errors=True)
    if a_con is None or a_free is None:
        return "GAP", "could not read back optimized geometries to compare", d
    if a_con == a_free:
        return "GAP", (f"'fix_atom' is SILENTLY IGNORED: rc=0, but the frozen atom ends at the same "
                       f"place with and without it ({a_con}). BAGEL has no working constrained "
                       f"optimization by this route."), d
    return "PASS", f"'fix_atom' changed the outcome: constrained {a_con} vs free {a_free}", d


PROBES = [p_forces, p_nacme, p_opt_hess, p_ref_archive, p_constrained]


def main() -> int:
    if not Path(BAGEL_BIN).exists():
        print(f"BAGEL not found at {BAGEL_BIN}; set QC_AGENT_BAGEL_BIN in .env")
        return 2
    wanted = [a for a in sys.argv[1:] if not a.startswith("-")]
    for fn in PROBES:
        if wanted and not any(w.lower() in fn._cap.lower() for w in wanted):
            continue
        try:
            verdict, evidence, d = fn()
        except Exception as e:
            verdict, evidence, d = "FAIL", f"{type(e).__name__}: {e}", None
        record(fn._cap, verdict, evidence, d)

    print("=" * 70)
    print("SUMMARY (bagel column of docs/QM_CAPABILITIES.md)")
    print("=" * 70)
    for cap, verdict, _ in RESULTS:
        print(f"  {verdict:4s}  {cap}")
    gaps = [c for c, v, _ in RESULTS if v in ("GAP", "FAIL")]
    if gaps:
        print("\nPARSER_GAPS / unresolved:")
        for g in gaps:
            print(f"  - {g}")
    if KEEP:
        print("\nScratch kept for inspection:")
        for k in KEEP:
            print(f"  {k}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
