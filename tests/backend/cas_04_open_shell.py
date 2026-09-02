#!/usr/bin/env python3
"""Open-shell molecules reach the projector instead of being refused.

Both legacy runners opened with ``if mol.spin != 0: raise ValueError`` and
declined the job -- so a radical, a triplet or any doublet could not get an
active-space recommendation at all, which is unfortunate given that
open-shell species are among the systems most likely to need a
multireference treatment in the first place.

The projector follows AVAS's ``openshell_option=2`` convention: singly
occupied orbitals are counted on the alpha side, so the occupied/virtual
partition stays well defined and the electron count comes out as an
``(n_alpha, n_beta)`` pair. Nothing here refuses on spin.

ROHF is the reference the engine projects onto rather than UHF, and the reason
changed under measurement. It began as an empirical preference: with a p-only
sigma target set, ROHF gave an identical space over these four radicals and
three basis sets while UHF moved for the methyl radical, its alpha and beta
orbitals relaxing differently so that the alpha set being projected was not
quite the same object from basis to basis.

**That instability is now gone.** Adding the valence-s component to each
heavy-atom sigma target -- done to recover the full valence spaces of N2 and O2
-- made the projection robust enough that UHF is basis stable here too, and the
assertion below, written to fire exactly when that happened, did. ROHF remains
the default on the physical argument rather than the empirical one: it carries
no spin contamination, so the orbitals being projected are eigenfunctions of
S^2 and the character analysis means what it says. The test now checks that
*both* references are stable and that they agree, which is the stronger
statement.

Needs pyscf but no live stack. Small SCF calculations only, no CASSCF.

Run:  PYTHONPATH=$PWD python3 tests/backend/cas_04_open_shell.py
"""
import numpy as np
from pyscf import gto, scf

from app.chemistry.cas.geometry import perceive
from app.chemistry.cas.projector import project

PASS = 0
FAIL = 0

BASES = ["sto-3g", "cc-pvdz", "def2-tzvp"]

CASES = {
    "O2 triplet": (["O", "O"], [[0, 0, 0], [0, 0, 1.208]], 0, 3),
    "NO doublet": (["N", "O"], [[0, 0, 0], [0, 0, 1.154]], 0, 2),
    "CH3 radical": (["C", "H", "H", "H"],
                    [[0, 0, 0], [0, 1.079, 0], [0.9345, -0.5395, 0],
                     [-0.9345, -0.5395, 0]], 0, 2),
    "CH2 triplet": (["C", "H", "H"],
                    [[0, 0, 0.1], [0, 0.99, -0.32], [0, -0.99, -0.32]], 0, 3),
}


def check(label: str, ok: bool, detail: str = "") -> None:
    global PASS, FAIL
    if ok:
        PASS += 1
        print(f"  [PASS] {label}")
    else:
        FAIL += 1
        print(f"  [FAIL] {label}" + (f"\n         {detail}" if detail else ""))


def _geom(syms, co):
    return "\n".join(f"{s} {c[0]:.8f} {c[1]:.8f} {c[2]:.8f}" for s, c in zip(syms, co))


def _space(syms, co, basis, chg, mult, builder):
    mol = gto.M(atom=_geom(syms, co), basis=basis, charge=chg, spin=mult - 1,
                verbose=0)
    mf = builder(mol).density_fit().run()
    ps = project(mf, perceive(syms, np.asarray(co, float)).targets)
    return ps.nelecas, ps.ncas


def main() -> int:
    print("An open-shell molecule produces a space rather than an exception")
    for name, (syms, co, chg, mult) in CASES.items():
        try:
            nelecas, ncas = _space(syms, co, "cc-pvdz", chg, mult, scf.ROHF)
            unpaired = nelecas[0] - nelecas[1]
            check(f"{name}: CAS({nelecas[0]}a,{nelecas[1]}b,{ncas}o) with "
                  f"{unpaired} unpaired electron(s), as the multiplicity requires",
                  unpaired == mult - 1,
                  f"expected {mult - 1} unpaired, got {unpaired}")
        except Exception as exc:                      # noqa: BLE001
            check(f"{name}: produces a space", False, f"{type(exc).__name__}: {exc}")

    print("\nThe space carries virtual orbitals, so there is correlation to describe")
    for name, (syms, co, chg, mult) in CASES.items():
        nelecas, ncas = _space(syms, co, "cc-pvdz", chg, mult, scf.ROHF)
        check(f"{name}: CAS({sum(nelecas)}e,{ncas}o) is not full",
              sum(nelecas) < 2 * ncas)

    print("\nROHF gives a basis-independent space for every case")
    for name, (syms, co, chg, mult) in CASES.items():
        spaces = {b: _space(syms, co, b, chg, mult, scf.ROHF) for b in BASES}
        check(f"{name}: identical across {', '.join(BASES)}",
              len(set(spaces.values())) == 1,
              "  ".join(f"{b}:{s}" for b, s in spaces.items()))

    print("\nand so does UHF, since the valence-s sigma targets went in")
    syms, co, chg, mult = CASES["CH3 radical"]
    uhf = {b: _space(syms, co, b, chg, mult, scf.UHF) for b in BASES}
    rohf = {b: _space(syms, co, b, chg, mult, scf.ROHF) for b in BASES}
    check("CH3: both references are now basis stable, and they agree with each "
          "other -- the UHF instability that originally motivated preferring "
          "ROHF was an artefact of the p-only sigma target set",
          len(set(rohf.values())) == 1 and len(set(uhf.values())) == 1
          and set(rohf.values()) == set(uhf.values()),
          f"ROHF {sorted(set(rohf.values()))}, UHF {sorted(set(uhf.values()))}")

    print(f"\n{PASS} passed, {FAIL} failed")
    return 1 if FAIL else 0


if __name__ == "__main__":
    raise SystemExit(main())
