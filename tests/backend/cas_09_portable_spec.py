#!/usr/bin/env python3
"""A recommended space survives being handed to a different basis set.

Basis independence is only worth something if the handoff has it too. The
recommendation is computed in one basis and the CASSCF that follows is usually
run in another, so what passes between them decides whether the property holds
end to end.

The contrast is the point of this script and is asserted, not described. A
handoff by molecular-orbital index -- what the previous engine used --
identifies "the n-th orbital of one particular calculation", so the same
indices name **different** orbitals in a different basis. A handoff by target
direction re-asks the question that selected the space, in a fixed minimal
reference basis, and gets the same answer.

Also asserted: a specification applied to the wrong molecule, or to a geometry
that has moved, is refused rather than quietly reproducing a plausible-looking
space for something it was not built for. That is the class of failure this
project has met before, where a space recommended for one molecule was reported
for another.

Needs pyscf but no live stack.

Run:  PYTHONPATH=$PWD python3 tests/backend/cas_09_portable_spec.py
"""
import numpy as np
from pyscf import gto, scf

from app.chemistry.cas import spec as spec_mod
from app.chemistry.cas.geometry import perceive
from app.chemistry.cas.recommend import recommend

PASS = 0
FAIL = 0

PYRROLE = (["N", "C", "C", "C", "C", "H", "H", "H", "H", "H"],
           np.asarray([[0, 0, 1.140], [0, 1.121, 0.339], [0, -1.121, 0.339],
                       [0, 0.713, -0.966], [0, -0.713, -0.966], [0, 0, 2.149],
                       [0, 2.125, 0.737], [0, -2.125, 0.737], [0, 1.356, -1.833],
                       [0, -1.356, -1.833]], float))
CH2O = (["C", "O", "H", "H"],
        np.asarray([[0, 0, -0.5295], [0, 0, 0.6755], [0, 0.94, -1.10],
                    [0, -0.94, -1.10]], float))


def check(label: str, ok: bool, detail: str = "") -> None:
    global PASS, FAIL
    if ok:
        PASS += 1
        print(f"  [PASS] {label}")
    else:
        FAIL += 1
        print(f"  [FAIL] {label}" + (f"\n         {detail}" if detail else ""))


def _mf(syms, co, basis):
    mol = gto.M(atom="\n".join(f"{s} {c[0]} {c[1]} {c[2]}" for s, c in zip(syms, co)),
                basis=basis, verbose=0)
    return scf.RHF(mol).density_fit().run()


def main() -> int:
    syms, co = PYRROLE

    print("Build the specification in def2-SVP")
    mf = _mf(syms, co, "def2-svp")
    rec = recommend(mf, syms, co)
    targets = perceive(syms, co, include_sigma=False).targets
    sp = spec_mod.build(rec, syms, co, targets)
    text = sp.to_json()
    check(f"pyrrole recommends CAS{rec.space} and the spec records it",
          sp.space() == rec.space, f"{sp.space()} vs {rec.space}")
    check(f"the spec serialises ({len(text)} bytes of JSON) and round-trips",
          spec_mod.ActiveSpaceSpec.from_json(text).space() == rec.space)
    check("every target is recorded in the minimal reference basis",
          sp.reference["basis_of_record"] == "minao")

    print("\nRebuild it against a mean field in three other basis sets")
    reloaded = spec_mod.ActiveSpaceSpec.from_json(text)
    for basis in ("sto-3g", "cc-pvdz", "aug-cc-pvdz"):
        mf2 = _mf(syms, co, basis)
        ncas, nelecas, mo, caslst, notes = spec_mod.rebuild_in_basis(mf2, reloaded)
        got = (sum(nelecas), ncas)
        check(f"{basis}: rebuilds to CAS{got}, the space it was built as",
              got == rec.space, f"got {got}, expected {rec.space}; notes {notes}")
        check(f"{basis}: the orbitals come back as a usable set "
              f"({mo.shape[1]} columns, {len(caslst)} active)",
              mo.shape[1] == mf2.mol.nao and len(caslst) == ncas)

    print("\nThe contrast: what a molecular-orbital index handoff does instead")
    # Take the indices the def2-SVP recommendation would have handed off and
    # ask what orbitals they name in each other basis. The comparison is
    # against the CANONICAL mean-field orbitals, which is what an index handoff
    # indexes into -- `mcscf.sort_mo` takes positions in mf.mo_coeff. Comparing
    # the projector's own output in two bases would compare the projector
    # against itself and show it agreeing, which is true and not the question.
    #
    # The result is more specific than "indices do not work". Between two
    # double-zeta bases they very nearly do, because the orbital count and
    # ordering happen to line up. They break when the basis changes size class,
    # which is exactly the case a user hits going from a cheap recommendation
    # to a production calculation.
    from pyscf import gto as _gto

    idx = rec.tiers["recommended"].orbital_indices
    pm = mf.mol.copy()
    pm.basis = "minao"
    pm.build(False, False)
    qa = np.linalg.qr(_gto.intor_cross("int1e_ovlp", pm, mf.mol)
                      @ mf.mo_coeff[:, idx])[0]

    index_overlaps = {}
    for basis in ("sto-3g", "cc-pvdz", "def2-tzvp", "aug-cc-pvdz"):
        mfx = _mf(syms, co, basis)
        if max(idx) >= mfx.mo_coeff.shape[1]:
            index_overlaps[basis] = 0.0     # the orbital does not even exist
            continue
        qb = np.linalg.qr(_gto.intor_cross("int1e_ovlp", pm, mfx.mol)
                          @ mfx.mo_coeff[:, idx])[0]
        sv = np.linalg.svd(qa.T @ qb, compute_uv=False)
        index_overlaps[basis] = float(np.min(sv))

    for basis, ov in index_overlaps.items():
        print(f"      index handoff into {basis:12s}: smallest principal "
              f"cosine {ov:.3f}")

    worst = min(index_overlaps.values())
    check(f"an index handoff fails for at least one basis (worst principal "
          f"cosine {worst:.3f}) -- so indices are not a safe handoff even "
          f"though they happen to survive between same-size bases",
          worst < 0.95,
          f"overlaps {index_overlaps}; if indices now transfer everywhere the "
          f"specification mechanism could be simplified")

    rebuilt = {}
    for basis in index_overlaps:
        ncas, nelecas, _mo, _cas, _n = spec_mod.rebuild_in_basis(
            _mf(syms, co, basis), reloaded)
        rebuilt[basis] = (sum(nelecas), ncas)
    check(f"the specification, by contrast, rebuilds to CAS{rec.space} in "
          f"every one of those bases",
          set(rebuilt.values()) == {rec.space}, str(rebuilt))

    print("\nA specification is refused where it does not apply")
    other_syms, other_co = CH2O
    mf4 = _mf(other_syms, other_co, "def2-svp")
    try:
        spec_mod.rebuild_in_basis(mf4, reloaded)
        check("applying pyrrole's spec to formaldehyde is refused", False,
              "it returned a space instead of raising")
    except ValueError as exc:
        check("applying pyrrole's spec to formaldehyde is refused",
              "does not transfer" in str(exc) or "different" in str(exc),
              str(exc)[:150])

    moved = co.copy()
    moved[1, 0] += 0.5
    mf5 = _mf(syms, moved, "def2-svp")
    try:
        spec_mod.rebuild_in_basis(mf5, reloaded)
        check("applying it to a geometry that has moved is refused", False,
              "it returned a space instead of raising")
    except ValueError as exc:
        check("applying it to a geometry that has moved is refused",
              "moved" in str(exc), str(exc)[:150])

    print("\nA specification from a future schema is refused, not guessed at")
    bad = text.replace(spec_mod.SCHEMA, "nexusqc.active_space_spec/99")
    try:
        spec_mod.ActiveSpaceSpec.from_json(bad)
        check("an unknown schema version is refused", False, "it parsed")
    except ValueError as exc:
        check("an unknown schema version is refused", "version" in str(exc),
              str(exc)[:120])

    print(f"\n{PASS} passed, {FAIL} failed")
    return 1 if FAIL else 0


if __name__ == "__main__":
    raise SystemExit(main())
