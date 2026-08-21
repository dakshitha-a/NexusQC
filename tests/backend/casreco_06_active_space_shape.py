#!/usr/bin/env python3
"""The occupied/virtual split of a truncated AVAS space is the caller's
choice, not a hardcoded near-even one.

`_truncate_avas_space` kept `ceiling - ceiling // 2` virtuals and filled the
rest from the occupied side, so the occupied count was always
floor(ceiling/2) and the SHAPE of every recommended space was fixed by an
implementation detail. On uracil/cc-pVDZ that made a cap of 9 yield (8e,9o)
and nothing else, and it made (12e,9o) -- six occupied, three virtual, the
standard choice when the n -> pi* states matter -- unreachable at every cap:
9 gave (8e,9o), 10 gave (10e,10o), 12 gave (12e,12o).

An excited state that promotes out of a lone pair needs those occupied
orbitals in the space, and a symmetric split cannot express the preference.

Needs PySCF but no live stack. One RHF on uracil; the truncation itself is
pure linear algebra, so no CASSCF is run here.

Run:  PYTHONPATH=$PWD python3 tests/backend/casreco_06_active_space_shape.py
"""
from __future__ import annotations

import sys

from pyscf import scf

from app.chemistry.jobs.pyscf_runner import (
    _avas_pilot_space, _truncate_avas_space, build_mole,
)
from app.chemistry.molecule import resolve_molecule

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


def main() -> int:
    mol_dict = resolve_molecule("uracil").to_dict()
    mol = build_mole(mol_dict, "cc-pvdz")
    mf = scf.RHF(mol)
    mf.kernel()
    ncas, nelec, mo, _labels, _notes = _avas_pilot_space(mf, mol, {}, "[test]")
    n_occ, n_virt = nelec // 2, ncas - nelec // 2
    print(f"\n== uracil/cc-pVDZ AVAS pool: ({nelec}e, {ncas}o), "
          f"{n_occ} occupied / {n_virt} virtual ==")
    check("the pool is lopsided toward occupied orbitals", n_occ > n_virt,
          f"{n_occ} occ vs {n_virt} virt")

    def cut(cap: int, occ=None):
        _mo, o, e, trunc, note = _truncate_avas_space(mol, mo, ncas, nelec, cap,
                                                      "[test]", n_occupied=occ)
        return e, o, trunc, note

    print("\n== the old behaviour is still what you get by default ==")
    for cap, expected in ((9, (8, 9)), (10, (10, 10)), (12, (12, 12))):
        e, o, _t, _n = cut(cap)
        check(f"cap={cap} defaults to ({expected[0]}e,{expected[1]}o)",
              (e, o) == expected, f"got ({e}e,{o}o)")

    print("\n== the occupied count is now the caller's to choose ==")
    for occ, expected in ((3, (6, 9)), (4, (8, 9)), (5, (10, 9)), (6, (12, 9)), (7, (14, 9))):
        e, o, _t, _n = cut(9, occ)
        check(f"cap=9 with {occ} occupied gives ({expected[0]}e,{expected[1]}o)",
              (e, o) == expected, f"got ({e}e,{o}o)")

    # The number this feature exists for, and the one that was unreachable.
    e, o, _t, _n = cut(9, 6)
    check("(12e,9o) is reachable -- it was not at any cap before", (e, o) == (12, 9),
          f"got ({e}e,{o}o)")

    print("\n== a request the pool cannot meet is clamped and said out loud ==")
    e, o, _t, note = cut(12, 40)
    check("asking for more occupied orbitals than exist is clamped",
          o <= 12 and e <= 2 * 12, f"({e}e,{o}o)")
    check("...and the clamp is reported, not silent", bool(note), repr(note))
    check("...naming what was asked for and what was kept",
          note is not None and "40" in note and "kept" in note, repr(note))

    print("\n== a shape that would leave no virtuals is repaired, not shipped ==")
    e, o, _t, note = cut(12, 12)
    check("an all-occupied request keeps at least one virtual orbital", o - e // 2 >= 1,
          f"({e}e,{o}o) has {o - e // 2} virtual(s)")
    check("...and says why it changed what was asked for",
          note is not None and "no correlation" in note, repr(note))

    print("\n== a space that already fits is untouched ==")
    e, o, trunc, note, = None, None, None, None
    _mo, o, e, trunc, note = _truncate_avas_space(mol, mo, ncas, nelec, ncas + 5, "[test]",
                                                  n_occupied=3)
    check("no truncation happens when the pool is under the cap", trunc is False)
    check("...and the pool comes back whole", (e, o) == (nelec, ncas), f"({e}e,{o}o)")
    check("...with no note to report", note is None, repr(note))

    total = PASS + FAIL
    print(f"\n{PASS}/{total} checks passed")
    if FAIL:
        print(f"[FAIL] {FAIL} check(s) failed")
        return 1
    print("[PASS] ALL CHECKS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
