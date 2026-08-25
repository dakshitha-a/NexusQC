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
and called it a lone pair. Carbon dioxide and carbon monoxide cover linear geometries, which pass
the planarity test while having no unique plane: reflecting through an
arbitrary plane containing the axis splits every degenerate pi pair and
labels half of it sigma, so those go through a rotation about the axis
instead. Ammonia exercises the non-planar fallback. The last three cases
cover diffuseness rather than character: aug-cc-pVDZ against a
non-augmented control, and a second molecule to show the measure does not
scale with molecular size.

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

rows, occ = classify("carbon dioxide / 6-31G* (linear)", "O 0 0 -1.16; C 0 0 0; O 0 0 1.16", "6-31g*")
print("expectations:")
# A linear molecule passes the planarity test but has no unique plane, and its
# pi orbitals are degenerate pairs the SCF may hand back in any mixture. CO2
# has four occupied pi orbitals, two in 1pi_u and two in 1pi_g. Getting two
# rather than four is the signature of a plane test splitting each pair.
n_pi = sum(1 for r, o in zip(rows, occ) if o > 0 and r["character"] == "pi")
ok &= check("all four occupied pi orbitals are found", n_pi == 4, f"got {n_pi}")
ok &= check("no occupied orbital is left unclassified",
            all(r["character"] for r, o in zip(rows, occ) if o > 0))

rows, occ = classify("carbon monoxide / 6-31G* (diatomic)", "C 0 0 -0.56; O 0 0 0.56", "6-31g*")
print("expectations:")
ok &= check("the 1pi pair is found", sum(1 for r, o in zip(rows, occ) if o > 0 and r["character"] == "pi") == 2)
# CO's HOMO is the carbon lone pair, which is what makes the molecule a ligand.
homo = rows[int(sum(occ > 0)) - 1]
ok &= check("HOMO is the carbon lone pair",
            (homo["character"], homo["localized_atom"]) == ("n", "C1"), str(homo))

# --- diffuseness ---------------------------------------------------------
# The measure is the fraction of an orbital's density lying outside 1.5 van der
# Waals radii of every atom. cc-pVDZ is the negative control: it has no diffuse
# functions, so nothing should clear the threshold, and a measure that flags
# something here is measuring the molecule's size rather than the orbital's.
rows, occ = classify("water / cc-pVDZ (no diffuse functions)", WATER, "cc-pvdz")
print("expectations:")
ok &= check("no orbital is flagged diffuse", not any(r["diffuse"] for r in rows),
            f"max fraction {max(r['diffuse_fraction'] for r in rows):.2f}")

rows, occ = classify("water / aug-cc-pVDZ", WATER, "aug-cc-pvdz")
print("expectations:")
n_diffuse = sum(1 for r in rows if r["diffuse"])
ok &= check("the augmented set produces diffuse virtuals", n_diffuse >= 4, f"got {n_diffuse}")
ok &= check("no occupied orbital is flagged diffuse",
            not any(r["diffuse"] for r, o in zip(rows, occ) if o > 0),
            f"max occupied fraction {max(r['diffuse_fraction'] for r, o in zip(rows, occ) if o > 0):.2f}")
# The whole point of the flag: a diffuse orbital must stop claiming an atom it
# does not sit on, which is what put a lone pair on a hydrogen in uracil.
ok &= check("no diffuse orbital claims an atom",
            all("diffuse" in r["localized_atom"] for r in rows if r["diffuse"]))
ok &= check("no diffuse orbital is called a lone pair",
            not any(r["character"] == "n" for r in rows if r["diffuse"]))
# Symmetry survives diffuseness, since it is a property of the orbital rather
# than of where its density sits.
ok &= check("diffuse orbitals still carry a shape",
            all(r["character"] for r in rows if r["diffuse"]))

rows, occ = classify("ethylene / aug-cc-pVDZ (size independence)", ETHYLENE_XYZ, "aug-cc-pvdz")
print("expectations:")
# A raw radius would scale with the molecule and drag ethylene's valence
# orbitals over any threshold tuned on water. A fraction does not.
ok &= check("no occupied orbital is flagged diffuse",
            not any(r["diffuse"] for r, o in zip(rows, occ) if o > 0),
            f"max occupied fraction {max(r['diffuse_fraction'] for r, o in zip(rows, occ) if o > 0):.2f}")
ok &= check("diffuse virtuals are found", sum(1 for r in rows if r["diffuse"]) >= 4)

rows, occ = classify("ammonia / 6-31G (non-planar fallback)", "N 0 0 0.12; H 0 0.94 -0.27; H 0.81 -0.47 -0.27; H -0.81 -0.47 -0.27", "6-31g")
print("expectations:")
ok &= check("classifier returns a row per orbital", len(rows) == len(occ))
ok &= check("nitrogen lone pair (HOMO) is on N1 alone",
            rows[sum(occ > 0) - 1]["localized_atom"] == "N1", rows[sum(occ > 0) - 1]["localized_atom"])

print("\nRESULT:", "all checks passed" if ok else "FAILURES above")
sys.exit(0 if ok else 1)
