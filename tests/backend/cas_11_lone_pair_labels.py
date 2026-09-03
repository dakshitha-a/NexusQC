#!/usr/bin/env python3
"""A lone pair is an sp hybrid on more than one atom, and both classifiers know it.

Two independent pieces of code in this repository decide whether an orbital is
a lone pair, and in September 2026 both got it wrong in the same direction, for
the same underlying reason: they were looking for something narrower than what a
lone pair actually is.

**`app/chemistry/jobs/molden.py`** labelled an orbital `n` only if it sat on ONE
atom with more than 0.6 of the population. A nitro, carboxyl or carboxylate
group carries its lone pairs as the symmetric and antisymmetric combinations
across two equivalent oxygens, so each oxygen holds about 0.45 and neither
clears that bar. The orbital then fell through to the shape test, where an
in-plane lone pair is symmetric about the molecular plane exactly as a sigma
bond is, and came back `sigma`. Measured on a user's own o-nitrophenol
SA-5 CASSCF(14,10): the two orbitals at occupancies 1.805 and 1.794, both on
the nitro oxygens, were labelled sigma -- and those are the orbitals its S1 and
S2 n->pi* states are built from.

What separates them is that a sigma BOND sits on a bonded pair. The two nitro
oxygens are each bonded to the nitrogen and not to each other.

**`app/chemistry/cas/geometry.py`** built its lone-pair reference directions as
pure p functions while already building sigma references as sp hybrids. A lone
pair on a heteroatom is an sp hybrid too, so its s component was invisible: an
orbital scoring 0.72 against an sp reference scored 0.02 against the pure p one.

Both faults are cheap to re-introduce and neither shows up as an error, so this
script pins them with molecules where the right answer is not in doubt.

Needs pyscf but no live stack. RHF only, about a minute.

Run:  PYTHONPATH=$PWD python3 tests/backend/cas_11_lone_pair_labels.py
"""
import os
import sys
import tempfile

import numpy as np

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from pyscf import gto, scf                                       # noqa: E402
from pyscf.tools import molden as pyscf_molden                   # noqa: E402

from app.chemistry.cas.geometry import perceive                  # noqa: E402
from app.chemistry.cas.excited import _target_weights            # noqa: E402
from app.chemistry.jobs.molden import orbital_character          # noqa: E402

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


# Nitrite: planar, C2v, two equivalent oxygens that are bonded to the nitrogen
# and not to each other. The same lone-pair combination o-nitrophenol's nitro
# group carries, in three atoms instead of fifteen.
#
# Nitromethane was tried first and is the wrong test. It is not planar, so the
# classifier never finds a molecular plane, falls back to sampling between the
# two dominant atoms, and calls the O-O orbitals "pi" -- which the lone-pair
# branch then declines, correctly, since it will not overrule a pi assignment.
# The fault being pinned here is about planar systems and needs a planar case.
NITRITE = ([("N", (0.0, 0.0, 0.0)), ("O", (0.0, 1.1015, 0.4600)),
            ("O", (0.0, -1.1015, 0.4600))], -1)
WATER = [("O", (0.0, 0.0, 0.1173)), ("H", (0.0, 0.7572, -0.4692)),
         ("H", (0.0, -0.7572, -0.4692))]
ETHYLENE = [("C", (0.0, 0.0, 0.6695)), ("C", (0.0, 0.0, -0.6695)),
            ("H", (0.0, 0.9289, 1.2321)), ("H", (0.0, -0.9289, 1.2321)),
            ("H", (0.0, 0.9289, -1.2321)), ("H", (0.0, -0.9289, -1.2321))]
FORMALDEHYDE = [("C", (0.0, 0.0, -0.5296)), ("O", (0.0, 0.0, 0.6741)),
                ("H", (0.0, 0.9376, -1.1170)), ("H", (0.0, -0.9376, -1.1170))]


def classify(atoms, basis="6-31g", charge=0):
    """RHF, then the orbital table the app would show for it."""
    mol = gto.M(atom=[(s, c) for s, c in atoms], basis=basis, charge=charge,
                verbose=0)
    mf = scf.RHF(mol).run()
    fd, path = tempfile.mkstemp(suffix=".molden")
    os.close(fd)
    pyscf_molden.from_mo(mol, path, mf.mo_coeff, occ=mf.mo_occ)
    try:
        rows = orbital_character(path)
    finally:
        os.unlink(path)
    return mol, mf, rows


print("A lone pair spread over two non-bonded oxygens is still a lone pair")
atoms, charge = NITRITE
mol, mf, rows = classify(atoms, charge=charge)
nocc = int(np.count_nonzero(mf.mo_occ > 0))

# Orbitals held between the two oxygens with the nitrogen carrying little:
# lone-pair combinations, whatever the old single-atom rule said.
both_o = [(i, rows[i]) for i in range(nocc)
          if rows[i].get("localized_atom", "") in
          ("delocalized over O2, O3", "delocalized over O3, O2")]
check(f"nitrite has orbitals held between both oxygens ({len(both_o)} of them)",
      len(both_o) >= 2,
      str([(i, r["character"], r["localized_atom"]) for i, r in both_o]))
chars = [r["character"] for _i, r in both_o]
check("the in-plane ones are lone pairs -- this is the o-nitrophenol fault, "
      "where the two orbitals its n->pi* states are built from were sigma",
      chars.count("n") >= 2, str([(i, r["character"]) for i, r in both_o]))
# Not all of them: one orbital held between those oxygens is the genuine
# out-of-plane nitro pi, and the lone-pair branch declines to overrule a pi
# assignment for exactly this reason. What must not survive is "sigma".
check("and none of them is called sigma any more, while the real pi one is "
      "left alone", "sigma" not in chars and "pi" in chars, str(chars))

# The other direction: the guard has to keep real sigma bonds out. An orbital
# with the bonded nitrogen carrying weight is a bond, not a lone pair.
with_n = [(i, rows[i]) for i in range(nocc)
          if "N1" in rows[i].get("localized_atom", "")]
check(f"orbitals with the bonded nitrogen in them are still sigma "
      f"({sum(1 for _i, r in with_n if r['character'] == 'sigma')} of "
      f"{len(with_n)})",
      any(r["character"] == "sigma" for _i, r in with_n),
      str([(i, r["character"], r["localized_atom"]) for i, r in with_n]))

print("\nThe single-atom rule still works, and nothing else got swept in")
_m, _f, wrows = classify(WATER)
homo = int(np.count_nonzero(_f.mo_occ > 0)) - 1
check(f"water's HOMO is still a lone pair (character {wrows[homo]['character']!r})",
      wrows[homo]["character"] == "n", str(wrows[homo]))

_m2, _f2, erows = classify(ETHYLENE)
homo2 = int(np.count_nonzero(_f2.mo_occ > 0)) - 1
check(f"ethylene's HOMO is still pi, not a lone pair "
      f"(character {erows[homo2]['character']!r})",
      erows[homo2]["character"] == "pi", str(erows[homo2]))

# The guard that keeps this narrow: a sigma BOND sits on a bonded pair, so an
# orbital on C and O together must not become a lone pair.
_m3, _f3, frows = classify(FORMALDEHYDE)
nocc3 = int(np.count_nonzero(_f3.mo_occ > 0))
co_bond_rows = [r for r in frows[:nocc3]
                if r.get("localized_atom") in ("C1-O2", "O2-C1")]
check(f"formaldehyde's C=O bonding orbitals are not called lone pairs "
      f"({len(co_bond_rows)} such rows)",
      all(r["character"] != "n" for r in co_bond_rows),
      str([(r["character"], r["localized_atom"]) for r in co_bond_rows]))

print("\nThe reference directions are sp hybrids, because lone pairs are")
syms = [a for a, _c in FORMALDEHYDE]
co = np.array([c for _a, c in FORMALDEHYDE], float)
per = perceive(syms, co)
lp = per.targets_of("lone_pair")
check(f"lone-pair targets carry an s admixture ({len(lp)} targets)",
      bool(lp) and all(getattr(t, "s_amplitude", 0.0) > 0.0 for t in lp),
      str([(t.element, t.shell, getattr(t, "s_amplitude", None)) for t in lp]))

# The measurement that motivated it: an sp reference sees a carbonyl lone pair
# that a pure p reference does not. Compare like for like on the same orbital,
# same target count -- only the s admixture differs.
import dataclasses                                               # noqa: E402
mol_f = gto.M(atom=[(s, c) for s, c in FORMALDEHYDE], basis="cc-pvdz", verbose=0)
mf_f = scf.RHF(mol_f).run()
pure_p = [dataclasses.replace(t, s_amplitude=0.0) for t in lp]
nocc_f = int(np.count_nonzero(mf_f.mo_occ > 0))
best_sp = max(_target_weights(mol_f, mf_f.mo_coeff[:, j], lp).get("lone_pair", 0.0)
              for j in range(nocc_f))
best_p = max(_target_weights(mol_f, mf_f.mo_coeff[:, j], pure_p).get("lone_pair", 0.0)
             for j in range(nocc_f))
check(f"an sp reference finds more lone-pair character than a pure p one "
      f"({best_sp:.3f} vs {best_p:.3f}), with the same number of targets",
      best_sp >= best_p, f"sp {best_sp}, pure p {best_p}")

print(f"\n{PASS} passed, {FAIL} failed")
sys.exit(1 if FAIL else 0)
