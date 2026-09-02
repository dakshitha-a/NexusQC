#!/usr/bin/env python3
"""The recommended space is checked, not merely asserted.

Everything the engine does before this point is a prediction: the projector
says these orbitals matter, the excited-state branch says the requested states
are built from them, and neither has solved the CI problem the user is actually
going to run. The verification tier closes that loop with a CASCI in the
recommended space -- orbitals not reoptimised, so one diagonalisation rather
than a self-consistent optimisation, seconds rather than minutes.

What is asserted here:

- a real recommendation verifies, and the state it predicted is present with
  the character it predicted;
- a **deliberately mutilated** space fails, and fails with a specific message
  naming what went missing rather than a generic error. This is the assertion
  that matters: a check that cannot fail is not a check, so the negative case
  is tested explicitly;
- a space too large for an exact CASCI is reported as *not verified* rather
  than silently passing. Saying "this was not confirmed" is a different claim
  from "this was confirmed", and the difference has to survive into the output.

Needs pyscf but no live stack.

Run:  PYTHONPATH=$PWD python3 tests/backend/cas_07_verification.py
"""
import numpy as np
from pyscf import gto, scf

from app.chemistry.cas.recommend import recommend
from app.chemistry.cas.verify import FCI_CSF_LIMIT, verify

PASS = 0
FAIL = 0

CH2O = (["C", "O", "H", "H"],
        np.asarray([[0, 0, -0.5295], [0, 0, 0.6755], [0, 0.94, -1.10],
                    [0, -0.94, -1.10]], float))
BUTADIENE = (["C", "C", "C", "C", "H", "H", "H", "H", "H", "H"],
             np.asarray([[-1.830, -0.360, 0], [-0.610, 0.180, 0],
                         [0.610, -0.180, 0], [1.830, 0.360, 0],
                         [-2.710, 0.270, 0], [-2.000, -1.430, 0],
                         [-0.440, 1.250, 0], [0.440, -1.250, 0],
                         [2.000, 1.430, 0], [2.710, -0.270, 0]], float))


def check(label: str, ok: bool, detail: str = "") -> None:
    global PASS, FAIL
    if ok:
        PASS += 1
        print(f"  [PASS] {label}")
    else:
        FAIL += 1
        print(f"  [FAIL] {label}" + (f"\n         {detail}" if detail else ""))


def _setup(syms, co, basis="cc-pvdz"):
    mol = gto.M(atom="\n".join(f"{s} {c[0]} {c[1]} {c[2]}" for s, c in zip(syms, co)),
                basis=basis, verbose=0)
    mf = scf.RHF(mol).density_fit().run()
    return mf, recommend(mf, syms, co)


def main() -> int:
    print("A real recommendation verifies, and finds the state it predicted")
    syms, co = CH2O
    mf, rec = _setup(syms, co)
    v = verify(mf, rec, syms, co, n_states=4, predicted=["n->pi*"])
    check(f"formaldehyde CAS{rec.space}: the CASCI ran ({v.method})", v.ran,
          f"{v.notes}")
    check(f"the predicted n->pi* state is present "
          f"(root characters: {v.characters})",
          "n->pi*" in v.found, f"found {v.found}, missing {v.missing}")
    check("and the verification says so in words",
          any("present" in n for n in v.notes), f"notes {v.notes}")
    check(f"the excitation energies are reported ({[round(x,2) for x in v.energies_ev[:3]]} eV)",
          len(v.energies_ev) > 1)

    print("\nA mutilated space fails -- the assertion that makes this a check")
    import copy
    broken = copy.deepcopy(rec)
    # Strip the space down to a single occupied/virtual pair of the wrong
    # character: the sigma-derived orbitals at the bottom of the pool. The
    # n->pi* state cannot be built out of these.
    t = broken.tiers["recommended"]
    t.orbital_indices = t.orbital_indices[:1] + t.orbital_indices[-1:]
    t.n_orbitals = 2
    t.n_electrons = 2
    broken.tiers["recommended"] = t
    v2 = verify(mf, broken, syms, co, n_states=3, predicted=["n->pi*"])
    check("the mutilated space does not contain the predicted state",
          (not v2.ran) or "n->pi*" in v2.missing,
          f"ran={v2.ran} found={v2.found} missing={v2.missing} chars={v2.characters}")
    check("and the message names what went missing rather than failing generically",
          any("did not appear" in n or "not verified" in n or "nothing to verify" in n
              for n in v2.notes),
          f"notes {v2.notes}")

    print("\nA ground-state recommendation with nothing to predict still reports")
    syms, co = BUTADIENE
    mf3, rec3 = _setup(syms, co)
    v3 = verify(mf3, rec3, syms, co, n_states=3, predicted=[])
    check(f"butadiene CAS{rec3.space}: the CASCI ran and reported "
          f"{v3.n_roots} states", v3.ran and v3.n_roots >= 1, f"{v3.notes}")
    check("and says there was no prediction to check against",
          any("nothing to check" in n for n in v3.notes), f"notes {v3.notes}")

    print("\nA space too large to verify says so, rather than passing quietly")
    huge = copy.deepcopy(rec3)
    t = huge.tiers["recommended"]
    t.n_orbitals, t.n_electrons = 30, 30
    from app.chemistry.cas import feasibility
    t.feasibility = feasibility.assess(30, 30)
    huge.tiers["recommended"] = t
    v4 = verify(mf3, huge, syms, co, n_states=2, predicted=["pi->pi*"])
    check(f"a {t.feasibility.n_csf:,}-CSF space is not verified", not v4.ran)
    check("the method is reported as 'skipped', not silently omitted",
          v4.method == "skipped", f"method {v4.method}")
    check("and the note distinguishes 'not confirmed' from 'confirmed'",
          any("not verified" in n or "has not been" in n for n in v4.notes),
          f"notes {v4.notes}")
    check(f"the threshold it compares against is stated ({FCI_CSF_LIMIT:,} CSFs)",
          any(f"{FCI_CSF_LIMIT:,}" in n for n in v4.notes), f"notes {v4.notes}")

    print(f"\n{PASS} passed, {FAIL} failed")
    return 1 if FAIL else 0


if __name__ == "__main__":
    raise SystemExit(main())
