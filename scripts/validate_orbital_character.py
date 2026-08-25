"""Checks classify_orbital_character against orbitals whose sigma/pi/n
assignment is not in doubt.

Run it after touching app/chemistry/jobs/molden.py:

    conda activate qc-agent
    PYTHONPATH=$PWD python3 scripts/validate_orbital_character.py

Water and ethylene are the two anchors the classifier was originally
written against. Uracil is the case that exposed the bug fixed on
2026-08-24: its orbital 25 is antisymmetric about the molecular plane,
so it is part of the pi system, but it carries only 37 percent of its
population on N2 with the rest spread over N1, O8 and C3. The old code
asked the atom count before the shape test, saw a single dominant atom
and called it a lone pair. Ammonia and ethane exercise the non-planar
fallback, which this change deliberately left alone.

Every expectation below is a symmetry statement rather than a judgement
call: in a planar molecule an orbital is a' or a'', and the count of each
is fixed by the molecule. That is what makes them safe to assert.
"""
import sys

from pyscf import gto, scf

from app.chemistry.jobs.molden import classify_orbital_character

URACIL_XYZ = """
N -0.0000 0.9906 -0.0000; N -1.1416 -1.0165 0.0000; C -1.2209 0.3614 0.0000
C 0.0504 -1.6961 0.0000; C 1.2274 -1.0730 0.0000; C 1.2562 0.3915 0.0000
O 2.2676 1.0759 0.0000; O -2.2649 0.9454 -0.0000; H -0.0243 1.9912 -0.0000
H -2.0126 -1.5021 -0.0000; H -0.0335 -2.7732 0.0000; H 2.1618 -1.6084 0.0000
"""

ETHYLENE_XYZ = """
C 0.0000 0.0000 0.6695; C 0.0000 0.0000 -0.6695
H 0.0000 0.9289 1.2321; H 0.0000 -0.9289 1.2321
H 0.0000 0.9289 -1.2321; H 0.0000 -0.9289 -1.2321
"""


def classify(name, atom, basis):
    mol = gto.M(atom=atom, basis=basis, verbose=0)
    mf = scf.RHF(mol).run()
    rows = classify_orbital_character(mol, mf.mo_coeff, mf.mo_occ)
    print(f"\n{name}  ({mol.nelectron // 2} occupied of {mol.nao})")
    for i, (row, occ) in enumerate(zip(rows, mf.mo_occ), start=1):
        print(f"  {i:>3}  occ {occ:.1f}  {str(row['character']):>7}  {row['localized_atom']}")
    return rows, mf.mo_occ


def check(label, condition, detail=""):
    print(f"  [{'PASS' if condition else 'FAIL'}] {label}" + (f"  {detail}" if detail else ""))
    return condition


ok = True

WATER = "O 0 0 0.117; H 0 0.755 -0.469; H 0 -0.755 -0.469"
FORMALDEHYDE = "C 0 0 -0.53; O 0 0 0.68; H 0 0.94 -1.10; H 0 -0.94 -1.10"

rows, occ = classify("water / STO-3G", WATER, "sto-3g")
print("expectations:")
# The 1s core and the out-of-plane lone pair both sit on oxygen alone. Water's
# plane here is the yz plane, so the in-plane orbitals are a' and the pure
# oxygen 2p perpendicular to it is a''. Both single-atom orbitals must be
# reported as sitting on oxygen, whatever shape label they carry.
ok &= check("core orbital 1 is on O1", rows[0]["localized_atom"] == "O1", rows[0]["localized_atom"])
ok &= check("no occupied orbital is called antibonding",
            not any(r["character"] and r["character"].endswith("*") for r in rows[:5]))
# The HOMO (1b1) is antisymmetric about the molecular plane and would read as
# pi on symmetry alone, but it is 100 percent oxygen with nothing to bond to.
# This is the case that stops the shape test from overriding the population
# test outright.
ok &= check("HOMO is a lone pair, not pi", rows[4]["character"] == "n", str(rows[4]))

rows, occ = classify("formaldehyde / 6-31G* (the other side of that boundary)", FORMALDEHYDE, "6-31g*")
print("expectations:")
# Same symmetry as water's HOMO, but the population splits 0.658 O / 0.342 C,
# so it is a polarized pi bond and must not collapse into a lone pair.
pi_rows = [i for i, r in enumerate(rows[:8]) if r["character"] == "pi"]
ok &= check("the C=O pi bond is reported as pi", len(pi_rows) == 1, f"pi at {[i + 1 for i in pi_rows]}")
ok &= check("that pi orbital names both C and O",
            bool(pi_rows) and "-" in rows[pi_rows[0]]["localized_atom"],
            rows[pi_rows[0]]["localized_atom"] if pi_rows else "")

rows, occ = classify("ethylene / 6-31G", ETHYLENE_XYZ, "6-31g")
homo = int(sum(occ > 0)) - 1
print("expectations:")
ok &= check("HOMO is pi", rows[homo]["character"] == "pi", str(rows[homo]))
ok &= check("LUMO is pi*", rows[homo + 1]["character"] == "pi*", str(rows[homo + 1]))

rows, occ = classify("uracil / cc-pVDZ", URACIL_XYZ, "cc-pvdz")
print("expectations:")
occupied = [r for r, o in zip(rows, occ) if o > 0]
n_pi = sum(1 for r in occupied if r["character"] in ("pi", "pi*"))
# Uracil has 12 heavy-atom p_z functions in the minimal picture, filled by
# 5 occupied pi orbitals in the neutral closed-shell ground state (two C=O
# pi, one ring C=C pi, and the two nitrogen lone pairs that conjugate into
# the ring). Anything else means the a'/a'' split has gone wrong.
ok &= check("exactly 5 occupied pi orbitals", n_pi == 5, f"got {n_pi}")
ok &= check("no occupied orbital both delocalized and called a lone pair",
            not any(r["character"] == "n" and r["localized_atom"].startswith("delocalized")
                    for r in occupied))
ok &= check("every lone pair names exactly one atom",
            all("-" not in r["localized_atom"] and " " not in r["localized_atom"]
                for r in occupied if r["character"] == "n"))

rows, occ = classify("ammonia / 6-31G (non-planar fallback)", "N 0 0 0.12; H 0 0.94 -0.27; H 0.81 -0.47 -0.27; H -0.81 -0.47 -0.27", "6-31g")
print("expectations:")
ok &= check("classifier returns a row per orbital", len(rows) == len(occ))
ok &= check("nitrogen lone pair (HOMO) is on N1 alone",
            rows[sum(occ > 0) - 1]["localized_atom"] == "N1", rows[sum(occ > 0) - 1]["localized_atom"])

print("\nRESULT:", "all checks passed" if ok else "FAILURES above")
sys.exit(0 if ok else 1)
