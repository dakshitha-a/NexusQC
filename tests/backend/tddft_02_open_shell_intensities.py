#!/usr/bin/env python3
"""Oscillator strengths are parsed for open-shell jobs too, and a partial
per-atom vector is refused rather than mis-assigned.
Regression test for R-030, R-076 and R-078.

    PYTHONPATH=$PWD python3 tests/backend/tddft_02_open_shell_intensities.py

R-030. ORCA labels a spectrum row `<root>-<multiplicity><symmetry>`, so a
singlet prints `0-1A -> 1-1A` and a triplet prints `0-3A -> 1-3A`. The
pattern hardcoded the multiplicity to 1, and every ORCA intensity path went
through it -- run_tddft, run_eom_ccsd, run_casscf alike. Each caller then
pads a short list with None to the length of the energy list, so an
open-shell job reported oscillator_strengths full of None, with no warning,
while the capability table and ARCHITECTURE.md both claim ORCA oscillator
strengths without qualification.

The fixture is a real run, not a hand-written sample:
`data/verified/orca_triplet_tddft_absorption.txt` is ORCA 6.1.1 output
produced here on 2026-09-13 from `! B3LYP sto-3g TightSCF` with
`%tddft NRoots 3 end` on water at multiplicity 3, trimmed to the spectrum
blocks. Engine parsers in this repository are derived from real output rather
than from documentation, and the review noted there was no committed
open-shell ORCA output to check this one against. Now there is.

R-076: a multi-state gradient runs one ORCA process per state in its own
subdirectory, and the scratch sweep only looked at the top level, so every
per-state scratch set survived -- roughly 60 MB per CASSCF run by the
module's own measurement, billed to the owner's quota.

R-078: BAGEL per-atom vectors were assembled into a dict and returned sorted
by index, so a row the regex missed was simply absent and the vector came
back shorter than the molecule, with every consumer reading atom k's vector
as atom k's.
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO))

from tests.fixtures import check, summary  # noqa: E402

from app.chemistry.jobs.orca_runner import _ABSORPTION_ROW, _ELECTRIC_DIPOLE_SECTION  # noqa: E402

print("R-030: ORCA intensities on an open shell\n")

FIXTURE = REPO / "data" / "verified" / "orca_triplet_tddft_absorption.txt"
check("the real triplet output is committed", FIXTURE.exists(), str(FIXTURE.name))
if FIXTURE.exists():
    text = FIXTURE.read_text()
    section = _ELECTRIC_DIPOLE_SECTION.search(text)
    check("the absorption section is found", section is not None)
    if section:
        fosc = _ABSORPTION_ROW.findall(section.group(1))
        check("all three triplet rows are parsed", len(fosc) == 3, f"{fosc}",
              f"{len(fosc)} of 3 -- the row labels are 0-3A, and the pattern "
              f"only ever matched 0-1A")
        check("and the values are the ones ORCA printed",
              fosc == ["0.001236276", "0.092543326", "0.000000055"], f"{fosc}")

print("\n   and a singlet still parses, so this is not a widened pattern that stopped discriminating")
SINGLET = """                     ABSORPTION SPECTRUM VIA TRANSITION ELECTRIC DIPOLE MOMENTS
----------------------------------------------------------------------------------------------------
     Transition      Energy     Energy  Wavelength fosc(D2)      D2        DX        DY        DZ
                      (eV)      (cm-1)    (nm)                 (au**2)    (au)      (au)      (au)
----------------------------------------------------------------------------------------------------
  0-1A  ->  1-1A    9.055859   24647.2   405.7   0.012360000   0.01651   0.00000  -0.12850   0.00000
  0-1A  ->  2-1A    9.946555   31831.1   314.2   0.925430000   0.95713   0.59907   0.00000  -0.77346

"""
sec = _ELECTRIC_DIPOLE_SECTION.search(SINGLET)
check("a singlet section parses both rows",
      sec is not None and _ABSORPTION_ROW.findall(sec.group(1)) == ["0.012360000", "0.925430000"],
      f"{_ABSORPTION_ROW.findall(sec.group(1)) if sec else None}")
check("and a symmetry-labelled row parses too (0-1B1u, not just 0-1A)",
      bool(_ABSORPTION_ROW.findall(
          "  0-1B1u ->  1-1B1u   7.055859   24647.2   405.7   0.031000000   0.01 0.0 0.0 0.0\n")),
      "")

print("\nR-076: per-state subdirectories are swept")
from app.chemistry.jobs import scratch  # noqa: E402

tmp = Path(tempfile.mkdtemp(prefix="r076-"))
job = tmp / "job1"
(job / "state_2").mkdir(parents=True)
(job / "pair_1_2").mkdir(parents=True)
for path in (job / "input.gbw", job / "input.tmp", job / "output.out",
             job / "state_2" / "input.tmp", job / "state_2" / "input.densities",
             job / "pair_1_2" / "input.tmp"):
    path.write_text("x")
real_dir = scratch.JOBS_DIR
scratch.JOBS_DIR = tmp
try:
    found = {str(f.relative_to(job)) for f in scratch._orca_scratch_files(job)}
finally:
    scratch.JOBS_DIR = real_dir
check("the sweep reaches state_<n>/ and pair_<a>_<b>/ scratch",
      {"state_2/input.tmp", "state_2/input.densities", "pair_1_2/input.tmp"} <= found,
      f"{sorted(found)}",
      "only the top level is swept, so one full scratch set survives per state")
check("and still finds the top-level scratch", "input.tmp" in found, f"{sorted(found)}")
check("without listing output.out, which is never scratch", "output.out" not in found)

print("\nR-078: a BAGEL vector list is complete or it is refused")
from app.chemistry.jobs import bagel_runner  # noqa: E402

def _atom_block(index: int, x: float) -> str:
    """One atom's vector in BAGEL's own layout: the index on its own line,
    then x, y and z each on theirs."""
    return (f"    o Atom {index}\n"
            f"        x {x:.10f}\n"
            f"        y {x + 0.1:.10f}\n"
            f"        z {x + 0.2:.10f}\n")


COMPLETE = "".join(_atom_block(i, 0.1 * (i + 1)) for i in range(3))
# The same three atoms with the middle row missing, which is exactly what a
# regex that fails to match one atom leaves behind.
GAPPED = _atom_block(0, 0.1) + _atom_block(2, 0.3)
vecs = bagel_runner._parse_atom_vectors(COMPLETE)
check("a complete section parses to one vector per atom", len(vecs) == 3, f"{len(vecs)}")
try:
    bagel_runner._parse_atom_vectors(GAPPED)
    check("a gapped section is refused", False, "",
          "it returned a short list, which every consumer reads as atom k's "
          "vector belonging to atom k")
except ValueError as exc:
    check("a gapped section is refused", True, f"{str(exc)[:70]}...")

summary()
