#!/usr/bin/env python3
"""The AVAS valence seed can no longer hand the entropy pilot a pool with
nothing in it to correlate, and says so instead of guessing when it does.

The bug this locks down, from the same dev-stack conversation as
casreco_01: an AutoCAS run on water/cc-pVDZ recommended (6e,3o) -- six
electrons in three orbitals, completely full, which cannot host a single
excitation -- and reported it as a result with a soft caveat.

The cascade had five stages and every one of them produced a plausible
number. `_default_avas_aolabels` skips hydrogens and names one valence
shell per heavy atom, so water seeded `['O 2p']`: three orbitals, all
occupied, no virtuals. A full pool holds exactly one configuration, so the
pilot CASCI returned a single determinant, so every single-orbital entropy
was identically zero (printed as `-0`), so there was no plateau, so the
fallback picked "the three highest-entropy orbitals" from a ranking that
did not exist.

Two fixes, checked separately here because either alone leaves a hole:
re-seed with hydrogens when the heavy-atom pool comes back full (the
standard AVAS treatment for a hydride -- `['O 2p', 'H 1s']` spans the O-H
sigma/sigma* pair), and refuse outright when the pool is still full after
that or full with labels the user chose themselves.

Needs PySCF but no live stack. Runs real SCF/AVAS/CASCI on 3-6 atom
molecules; a few seconds each.

Run:  PYTHONPATH=$PWD python3 tests/backend/casreco_02_avas_seed_and_guard.py
"""
from __future__ import annotations

import sys
import tempfile

from pyscf import gto, scf

from app.chemistry.jobs.pyscf_runner import (
    _avas_electron_count, _avas_pilot_space, _default_avas_aolabels,
    run_recommend_active_space,
)

PASS = 0
FAIL = 0

WATER = {
    "name": "water", "symbols": ["O", "H", "H"],
    "coords": [[0, 0, 0.117], [0, 0.757, -0.469], [0, -0.757, -0.469]],
    "charge": 0, "multiplicity": 1,
}
GEOMETRIES = {
    "water": "O 0 0 0.117; H 0 0.757 -0.469; H 0 -0.757 -0.469",
    "ammonia": "N 0 0 0.12; H 0 0.94 -0.27; H 0.81 -0.47 -0.27; H -0.81 -0.47 -0.27",
    "ethylene": ("C 0.66 0 0; C -0.66 0 0; H 1.23 0.92 0; H 1.23 -0.92 0; "
                 "H -1.23 0.92 0; H -1.23 -0.92 0"),
}


def check(label: str, ok: bool, detail: str = "") -> None:
    global PASS, FAIL
    if ok:
        PASS += 1
        print(f"  [PASS] {label}")
    else:
        FAIL += 1
        print(f"  [FAIL] {label}" + (f"\n         {detail}" if detail else ""))


def _pool(name: str, params: dict | None = None):
    mol = gto.M(atom=GEOMETRIES[name], basis="cc-pvdz", verbose=0)
    mf = scf.RHF(mol)
    mf.kernel()
    ncas, nelecas, _mo, labels, notes = _avas_pilot_space(mf, mol, params or {}, "[test]")
    return _avas_electron_count(nelecas), ncas, labels, notes


def run_seeding() -> None:
    print("\n== a full heavy-atom pool is re-seeded with hydrogens ==")
    for name, heavy in (("water", "O 2p"), ("ammonia", "N 2p")):
        mol = gto.M(atom=GEOMETRIES[name], basis="cc-pvdz", verbose=0)
        check(f"{name}'s default seed is heavy-atom only",
              _default_avas_aolabels(mol) == [heavy], repr(_default_avas_aolabels(mol)))
        n_e, n_o, labels, notes = _pool(name)
        check(f"{name} re-seeds", bool(notes), "no re-seed happened")
        check(f"...including the hydrogens", "H 1s" in labels, repr(labels))
        check(f"...leaving virtual orbitals in the pool ({n_e}e,{n_o}o)", n_e < 2 * n_o,
              f"({n_e}e,{n_o}o) is still full")

    print("\n== a pool that already has virtuals is left alone ==")
    n_e, n_o, labels, notes = _pool("ethylene")
    check("ethylene does not re-seed", not notes, repr(notes))
    check("...and keeps its heavy-atom labels", labels == ["C 2p"], repr(labels))
    check(f"...its pool has virtuals already ({n_e}e,{n_o}o)", n_e < 2 * n_o)

    print("\n== labels the user chose are never second-guessed ==")
    try:
        _pool("water", {"avas_aolabels": ["O 2p"]})
        check("an explicitly full user seed is refused, not re-seeded", False,
              "no exception raised")
    except ValueError as e:
        check("an explicitly full user seed is refused, not re-seeded", True)
        check("...naming the pool that was empty of virtuals", "completely occupied" in str(e),
              str(e)[:200])
        check("...and saying what to do instead", "avas_aolabels" in str(e), str(e)[:200])


def run_end_to_end() -> None:
    print("\n== water/cc-pVDZ produces a real recommendation end to end ==")
    with tempfile.TemporaryDirectory() as d:
        out = run_recommend_active_space(
            WATER, {"basis": "cc-pvdz", "n_states": 2, "method": "casscf", "_job_dir": d})
    s = out["summary"]
    n_e = s["recommended_active_electrons"]
    n_o = s["recommended_active_orbitals"]
    check(f"the recommended space ({n_e}e,{n_o}o) is not completely full", n_e < 2 * n_o,
          f"({n_e}e,{n_o}o) can host exactly one configuration")
    check("a genuine entropy plateau is found", s["plateau_found"] is True,
          s.get("findings_summary", ""))
    check("the entropies are not all zero", any(e > 1e-9 for e in s["pilot_orbital_entropies"]),
          repr(s["pilot_orbital_entropies"]))
    check("no entropy is reported as a negative zero",
          not any(str(e).startswith("-0") for e in s["pilot_orbital_entropies"]),
          repr(s["pilot_orbital_entropies"]))
    check("both requested states are hosted -- no clamp",
          s["n_states"] == s["n_states_requested"] == 2,
          f"{s['n_states']} of {s['n_states_requested']}")
    check("the re-seed is stated in the findings, not silent",
          "hydrogens were included" in s["findings_summary"], s["findings_summary"])


def main() -> int:
    run_seeding()
    run_end_to_end()
    total = PASS + FAIL
    print(f"\n{PASS}/{total} checks passed")
    if FAIL:
        print(f"[FAIL] {FAIL} check(s) failed")
        return 1
    print("[PASS] ALL CHECKS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
