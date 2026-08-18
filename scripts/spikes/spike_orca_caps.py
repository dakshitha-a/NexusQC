#!/usr/bin/env python3
"""Phase 0 verification spike: what ORCA on THIS host actually does.

    PYTHONPATH=$PWD python3 scripts/spikes/spike_orca_caps.py [probe ...] [-v]

Runs real (tiny) ORCA calculations and reports, for each capability the
overhaul's routing table wants to claim, both whether it ran AND whether the
datum a job preview needs can be located in the output. Documentation is not
a substitute here: this repo's parsers are derived from real runs because
ORCA's exact output formatting is not guaranteed across versions, and the
capability matrix must be traceable to something observed on this host.

Each probe prints PASS/FAIL plus either the parsed value or the raw block it
could not parse -- the latter is what gets pasted into docs/PARSER_GAPS.md.
Named probes can be run individually; with no arguments every probe runs.

Water/STO-3G throughout. Scratch goes to a temp dir that is kept on failure
so the raw output can be inspected.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO))

from app.config import ORCA_BIN  # noqa: E402

WATER_XYZ = """  O   0.000000   0.000000   0.117300
  H   0.000000   0.757000  -0.467000
  H   0.000000  -0.757000  -0.467000"""
# C1-distorted: symmetry-forbidden couplings come back as exact zeros at
# C2v, which proves nothing about whether the machinery ran.
WATER_C1 = """  O   0.000000   0.000000   0.130000
  H   0.100000   0.790000  -0.510000
  H  -0.040000  -0.720000  -0.430000"""

RESULTS: list[tuple[str, str, str]] = []
VERBOSE = "-v" in sys.argv
KEEP: list[str] = []


def run_orca(name: str, body: str, geom: str = WATER_XYZ, timeout: int = 900) -> tuple[str, Path]:
    """Write an input, run ORCA in its own scratch dir, return (stdout, dir)."""
    d = Path(tempfile.mkdtemp(prefix=f"orca-{name}-"))
    inp = d / "input.inp"
    inp.write_text(f"{body}\n\n* xyz 0 1\n{geom}\n*\n")
    proc = subprocess.run(
        [str(ORCA_BIN), "input.inp"], cwd=d, capture_output=True, text=True, timeout=timeout,
        env={**os.environ, "OMP_NUM_THREADS": "1"},
    )
    out = proc.stdout + proc.stderr
    (d / "output.log").write_text(out)
    return out, d


def record(cap: str, verdict: str, evidence: str, keep_dir: Path | None = None) -> None:
    RESULTS.append((cap, verdict, evidence))
    print(f"[{verdict:4s}] {cap}\n        {evidence}\n")
    if verdict != "PASS" and keep_dir is not None:
        KEEP.append(str(keep_dir))
    elif keep_dir is not None and not VERBOSE:
        shutil.rmtree(keep_dir, ignore_errors=True)


def probe(cap: str):
    def deco(fn):
        fn._cap = cap
        return fn
    return deco


def tail(text: str, n: int = 12) -> str:
    return "\n        ".join(text.strip().splitlines()[-n:])


def section(text: str, header_re: str, n: int = 10) -> str | None:
    """Return n lines starting at the first line matching header_re, skipping
    ORCA's credits banner.

    The banner lists contributors' specialities -- "NACMEs", "NEB-TS", "SF"
    and so on -- so a naive search for a capability name matches the credits
    of every ORCA run ever made and reports a feature as present even when
    the run aborted on an unknown keyword. This probe suite produced exactly
    that false positive before the offset existed."""
    lines = text.splitlines()
    start = 0
    for i, ln in enumerate(lines[:400]):
        if "Program Version" in ln or "With contributions from" in ln:
            start = i
        if re.search(r"INPUT FILE|={10,}", ln) and start:
            start = i
            break
    for i, ln in enumerate(lines):
        if i <= start:
            continue
        if re.search(header_re, ln):
            return "\n        ".join(lines[i:i + n])
    return None


def terminated_ok(text: str) -> bool:
    return "ORCA TERMINATED NORMALLY" in text


def unknown_keyword(text: str) -> str | None:
    m = re.search(r"Unknown identifier[^\n]*\n[^\n]*\n?[^\n]*", text)
    return m.group(0).strip() if m else None


# ------------------------------------------------------------------ probes

@probe("gradient: ! EnGrad -- stdout block and .engrad file")
def p_engrad():
    out, d = run_orca("engrad", "! HF STO-3G EnGrad")
    eg = d / "input.engrad"
    blk = section(out, r"CARTESIAN GRADIENT", 8)
    if not eg.exists() and blk is None:
        return "FAIL", f"no .engrad file and no CARTESIAN GRADIENT block. tail:\n        {tail(out)}", d
    parts = []
    if blk:
        parts.append("stdout block found:\n        " + blk)
    if eg.exists():
        body = eg.read_text().strip().splitlines()
        parts.append(f".engrad present ({len(body)} lines), first data lines:\n        "
                     + "\n        ".join(body[:14]))
    return "PASS", "\n        ".join(parts), d


@probe("excited-state gradient: TDDFT + IRoot (PBE0)")
def p_es_grad():
    # PBE0 deliberately, not B3LYP -- see p_es_grad_b88 below.
    out, d = run_orca("esgrad", "! PBE0 STO-3G EnGrad\n%tddft nroots 3 iroot 1 end")
    blk = section(out, r"CARTESIAN GRADIENT", 8)
    if blk is None:
        return "FAIL", f"no gradient block. tail:\n        {tail(out)}", d
    return "PASS", "ES gradient present with IRoot 1:\n        " + blk, d


@probe("excited-state gradient: B88-containing functional needs LibXC")
def p_es_grad_b88():
    """The finding this probe exists to pin down: ORCA refuses TDDFT
    gradients for B88-containing functionals through the native code path
    ('Third functional derivative of a B88 exchange-containing functional
    requested ... not available natively with ORCA. Please, use the LibXC
    version'), but computes them happily when the same functional is
    requested through the %method LibXC route. The input builder therefore
    has to rewrite B3LYP/BLYP into their LibXC components whenever an
    excited-state gradient is being asked for, instead of refusing."""
    native, d1 = run_orca("esgrad-b3lyp", "! B3LYP STO-3G EnGrad\n%tddft nroots 3 iroot 1 end")
    native_ok = section(native, r"CARTESIAN GRADIENT", 3) is not None
    shutil.rmtree(d1, ignore_errors=True)
    libxc, d2 = run_orca(
        "esgrad-libxc",
        "! STO-3G EnGrad\n%method method dft exchange gga_x_b88 correlation gga_c_lyp end\n"
        "%tddft nroots 3 iroot 1 end")
    libxc_ok = section(libxc, r"CARTESIAN GRADIENT", 3) is not None
    if native_ok or not libxc_ok:
        return "FAIL", f"expected native=False/libxc=True, got native={native_ok} libxc={libxc_ok}", d2
    return "PASS", ("native B3LYP ES gradient refused (needs 3rd derivative of B88); "
                    "the same functional via %method LibXC components DOES produce one -- "
                    "input builder must route B88 functionals through LibXC for ES gradients"), d2


@probe("full TDDFT vs TDA: %tddft tda false")
def p_rpa():
    out, d = run_orca("rpa", "! B3LYP STO-3G\n%tddft nroots 3 tda false end")
    blk = section(out, r"TD-DFT.*EXCITED STATES|ABSORPTION SPECTRUM", 12)
    if blk is None:
        return "FAIL", f"no excited-state block. tail:\n        {tail(out)}", d
    mode = "RPA/full TDDFT" if re.search(r"TD-DFT/TDA|TDA[- ]?off|RPA", out) else "unclear"
    return "PASS", f"tda false accepted ({mode}):\n        " + blk, d


@probe("NAC: TDDFT NACME (ground-to-excited only)")
def p_nac_td():
    """Syntax taken from the scraped manual (%TDDFT ... NACME TRUE), not
    guessed. Note what ORCA actually computes here: <GS|d/dx|ES>, a
    GROUND-to-excited coupling for one IROOT. It does not offer
    excited-to-excited couplings from this module, which is the opposite
    of the restriction one might assume for a single-reference method."""
    out, d = run_orca(
        "nactd",
        "! PBE0 STO-3G\n%TDDFT NROOTS 3\n  IROOT 1\n  NACME TRUE\n  ETF TRUE\nEND",
        geom=WATER_C1)
    if not terminated_ok(out):
        return "FAIL", f"{unknown_keyword(out) or tail(out, 8)}", d
    blk = section(out, r"CARTESIAN NON-ADIABATIC COUPLINGS", 16)
    if blk is None:
        return "GAP", "ran normally but no NAC block located:\n        " + tail(out, 18), d
    norm = re.search(r"Norm of the NACs\s*\.\.\.\s*([-\d.]+)", out)
    return "PASS", (f"GS->ES couplings printed; norm={norm.group(1) if norm else 'n/a'}\n        " + blk), d


@probe("NAC: CASSCF NACME keyword surface")
def p_nac_cas():
    """%casscf does not take a NACME keyword in this build -- it aborts with
    'Unknown identifier in CASSCF block'. Recorded as a GAP rather than a
    FAIL because the capability may exist under different syntax (the
    manual documents NACMEs mainly for the CIS/TDDFT module and for
    conical-intersection searches via %CONICAL)."""
    out, d = run_orca(
        "naccas",
        "! CASSCF STO-3G\n%casscf nel 4 norb 4 nroots 2\n  nacme true\nend",
        geom=WATER_C1)
    if not terminated_ok(out):
        return "GAP", ("CASSCF NACME not available under this syntax: "
                       + (unknown_keyword(out) or tail(out, 6))), d
    blk = section(out, r"CARTESIAN NON-ADIABATIC COUPLINGS", 14)
    return ("PASS", "CASSCF NAC block:\n        " + blk, d) if blk else \
           ("GAP", "ran but no NAC block:\n        " + tail(out, 14), d)


@probe("constrained opt: %geom Constraints")
def p_constrained():
    out, d = run_orca(
        "constr",
        "! HF STO-3G Opt\n%geom Constraints\n  {B 0 1 0.98 C}\n end\nend")
    if "HURRAY" not in out and "THE OPTIMIZATION HAS CONVERGED" not in out:
        return "FAIL", f"did not converge/accept. tail:\n        {tail(out)}", d
    blk = section(out, r"Constraints|constrained", 6) or "(constraint echo not located)"
    return "PASS", "converged with constraint:\n        " + blk, d


@probe("conical intersection: %CONICAL block")
def p_conical():
    """ORCA 6 spells this %CONICAL, not %mecp. The manual documents three
    methods: GRADIENT_PROJECTION (default when NACMEs are available),
    GP_NONACME (neglects the couplings), and UBP (updated branching plane,
    the default when NACMEs are not available). Probing the keyword surface
    and one optimization step is enough for the matrix -- converging a real
    conical intersection is a Phase 6 job, not a Phase 0 one."""
    out, d = run_orca(
        "conical",
        "! PBE0 STO-3G Opt\n%TDDFT NROOTS 3 IROOT 1 END\n%CONICAL\n  METHOD UBP\nEND",
        geom=WATER_C1, timeout=1200)
    if not terminated_ok(out):
        uk = unknown_keyword(out)
        if uk:
            return "GAP", f"%CONICAL not accepted: {uk}", d
        return "GAP", f"ran but did not terminate normally:\n        {tail(out, 10)}", d
    return "PASS", f"%CONICAL METHOD UBP accepted and terminated normally", d


@probe("opt+freq in one input: ! Opt Freq")
def p_optfreq():
    out, d = run_orca("optfreq", "! HF STO-3G Opt Freq")
    conv = "HURRAY" in out or "THE OPTIMIZATION HAS CONVERGED" in out
    blk = section(out, r"VIBRATIONAL FREQUENCIES", 12)
    if not (conv and blk):
        return "FAIL", f"conv={conv}, freq block={'yes' if blk else 'no'}. tail:\n        {tail(out)}", d
    return "PASS", "single input produced both opt and freq:\n        " + blk, d


@probe("orbital restart: %moinp + ! MOREAD across method change (HF -> CASSCF)")
def p_moread():
    out1, d1 = run_orca("moread-src", "! HF STO-3G")
    gbw = d1 / "input.gbw"
    if not gbw.exists():
        return "FAIL", "source run produced no input.gbw", d1
    d2 = Path(tempfile.mkdtemp(prefix="orca-moread-dst-"))
    shutil.copy(gbw, d2 / "source.gbw")
    (d2 / "input.inp").write_text(
        '! CASSCF STO-3G MOREAD\n%moinp "source.gbw"\n%casscf nel 4 norb 4 nroots 1 end\n'
        f"\n* xyz 0 1\n{WATER_XYZ}\n*\n")
    proc = subprocess.run([str(ORCA_BIN), "input.inp"], cwd=d2, capture_output=True,
                          text=True, timeout=900, env={**os.environ, "OMP_NUM_THREADS": "1"})
    out2 = proc.stdout + proc.stderr
    (d2 / "output.log").write_text(out2)
    shutil.rmtree(d1, ignore_errors=True)
    read = re.search(r"reading orbitals|Orbitals read|MORead|initial guess.*MOs", out2, re.I)
    ok = "ORCA TERMINATED NORMALLY" in out2
    if not ok:
        return "FAIL", f"restart run failed. tail:\n        {tail(out2)}", d2
    return "PASS", (f"HF orbitals accepted as CASSCF guess ({'read confirmed' if read else 'no explicit echo'}); "
                    f"terminated normally"), d2


PROBES = [p_engrad, p_es_grad, p_es_grad_b88, p_rpa, p_nac_td, p_nac_cas, p_constrained, p_conical, p_optfreq, p_moread]


def main() -> int:
    if not Path(ORCA_BIN).exists():
        print(f"ORCA not found at {ORCA_BIN}; set QC_AGENT_ORCA_BIN in .env")
        return 2
    wanted = [a for a in sys.argv[1:] if not a.startswith("-")]
    for fn in PROBES:
        if wanted and not any(w in fn._cap for w in wanted):
            continue
        try:
            verdict, evidence, d = fn()
        except subprocess.TimeoutExpired:
            verdict, evidence, d = "FAIL", "timed out", None
        except Exception as e:
            verdict, evidence, d = "FAIL", f"{type(e).__name__}: {e}", None
        record(fn._cap, verdict, evidence, d)

    print("=" * 70)
    print("SUMMARY (orca column of docs/QM_CAPABILITIES.md)")
    print("=" * 70)
    for cap, verdict, _ in RESULTS:
        print(f"  {verdict:4s}  {cap}")
    gaps = [c for c, v, _ in RESULTS if v == "GAP"]
    if gaps:
        print("\nPARSER_GAPS candidates:")
        for g in gaps:
            print(f"  - {g}")
    if KEEP:
        print("\nScratch kept for inspection:")
        for k in KEEP:
            print(f"  {k}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
