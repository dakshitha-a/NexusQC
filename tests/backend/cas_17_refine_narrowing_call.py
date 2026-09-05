#!/usr/bin/env python3
"""The refinement's in-loop narrowing runs, instead of raising TypeError.

`refine()` has three corrective moves when a requested state does not appear in
the space: narrow, re-seed, augment. The first of them has never executed. Its
call passes seven positional arguments to `narrow_to_states`, whose signature
makes `csf_budget` keyword-only with no default, so reaching that branch raises

    TypeError: narrow_to_states() missing 1 required keyword-only
               argument: 'csf_budget'

and takes the whole refinement job down rather than correcting the space.

Nothing caught it because the branch is guarded by `narrowed_once`, which is set
when the start tier was itself produced by a narrowing. So it fires only when a
tier from the ladder was used, no narrowing shrank the space, and a state still
came back missing. Every benchmark molecule that reaches the corrective moves
had already narrowed on the way in, so the benchmark never tried it.

This test forces the branch instead of hoping for it: ethylene has no lone pair
and so cannot have an n->pi* state, and its pool does not shrink under
narrowing, which is exactly the combination the guard requires.

    PYTHONPATH=$PWD python3 tests/backend/cas_17_refine_narrowing_call.py
"""
from __future__ import annotations

import sys

import numpy as np

FAILURES = []


def check(label, ok, detail=""):
    print(f"  [{'PASS' if ok else 'FAIL'}] {label}"
          + (f" -- {detail}" if detail else ""))
    if not ok:
        FAILURES.append(label)


def main() -> int:
    from pyscf import dft, gto, scf, tdscf

    from app.chemistry.cas.excited import analyse
    from app.chemistry.cas.geometry import perceive
    from app.chemistry.cas.recommend import recommend
    from app.chemistry.cas.refine import refine
    from scripts.casbench import reference_data as ref

    print("cas_17: the refinement's in-loop narrowing is reachable")

    syms, co, chg, mult = ref.molecule("ethylene")
    co = np.asarray(co, float)
    atom = "\n".join(f"{s} {c[0]:.8f} {c[1]:.8f} {c[2]:.8f}"
                     for s, c in zip(syms, co))
    mol = gto.M(atom=atom, basis="def2-svp", charge=chg, spin=0, verbose=0)

    mf = scf.RHF(mol).density_fit()
    mf.kernel()
    rec = recommend(mf, syms, co, spin_2s=0)

    ks = dft.RKS(mol).density_fit()
    ks.xc = "camb3lyp"
    ks.kernel()
    td = tdscf.TDA(ks)
    td.nstates = 6
    td.kernel()
    per = perceive(syms, co, include_sigma=False)
    an = analyse(ks, td, per.targets, n_states=2, rydberg_detectable=False)

    print(f"    pool {rec.space}, tiers "
          f"{ {k: (t.n_electrons, t.n_orbitals) for k, t in rec.tiers.items()} }")

    # An n->pi* state on a molecule with no lone pair. The audit cannot find it
    # in any space, so `missing` is non-empty on the first cycle and the
    # corrective moves are entered.
    impossible = ["n->pi*"]

    try:
        result = refine(mf, syms, co, rec, n_states=2, analysis=an,
                        predicted=impossible, spin_2s=0,
                        max_cycles=2, log=lambda m: None)
    except TypeError as exc:
        check("reaching the in-loop narrowing does not raise TypeError",
              False, str(exc))
        print(f"\n{len(FAILURES)} failure(s)")
        return 1
    except Exception as exc:                                # noqa: BLE001
        check("the refinement completes", False,
              f"{type(exc).__name__}: {exc}")
        print(f"\n{len(FAILURES)} failure(s)")
        return 1

    check("reaching the in-loop narrowing does not raise TypeError", True,
          f"refined to ({result.n_electrons}e,{result.n_orbitals}o)")

    # The state genuinely is not there, and the result has to say so rather
    # than returning a space and letting the absence pass unremarked. The
    # engine reports it as a note, so that is what is asserted; an earlier
    # version of this check read a field that does not exist and passed on its
    # own fallback, which is no better than not checking.
    notes = " ".join(getattr(result, "notes", []) or [])
    check("the impossible state is reported absent, in words",
          "n->pi*" in notes and "absent" in notes,
          f"notes={getattr(result, 'notes', None)}")

    print(f"\n{len(FAILURES)} failure(s)"
          + (": " + "; ".join(FAILURES) if FAILURES else ""))
    return 1 if FAILURES else 0


if __name__ == "__main__":
    sys.exit(main())
