#!/usr/bin/env python3
"""The Hartree-Fock reference is stabilised before the recommendation reads it.

**Why this exists.** A converged SCF solution is not necessarily a stable one.
An unstable solution is a stationary point that is not a minimum, so it passes
the convergence test exactly and looks finished. The active-space recommendation
is built by projecting geometric targets onto that reference's orbitals, so an
unstable reference is not a cosmetic problem: it moves the projection weights,
and a weight sitting near the admission threshold then decides membership
differently from one run to the next.

That was measured rather than supposed. Twisted ethylene's reference converges
to either of two solutions about 31.5 mHa apart, and the recommendation came
back CAS(2e,2o) on 51 runs in 60 and CAS(4e,3o) on the other nine. Re-measured
while writing this script, that molecule's reference is unstable in STO-3G by
58.1 mHa and in cc-pVDZ by 30.8 mHa, and stable in def2-SVP, so the basis and
the initial guess decide whether there is anything to follow at all. Three further
benchmark molecules were being built on a non-minimum every single time, which
no amount of repeating a run could have revealed: repeating a deterministic
wrong answer just returns the same wrong answer.

`app/chemistry/cas/reference.py` now stabilises before reading. Until this
script nothing asserted that behaviour. `cas_18` calls `stabilise` only
incidentally, while setting up a constants sweep, so the fix had no standing
test of its own.

What is checked, in order:

1. `stabilise` reports a shape a caller can act on: whether it moved, how many
   instabilities it followed, and the energy on each side.
2. On twisted ethylene it actually finds and follows one, and the energy
   afterwards is **lower**, which is what following an instability means. A
   repair that silently did nothing would still satisfy a "did it converge"
   check, so the energy comparison is the assertion with teeth.
3. The stabilised reference is a real minimum: asking again reports stable, so
   the follow loop reached a fixed point rather than stopping at its cap.
4. An open-shell reference does not crash on the external check. pyscf raises
   `NotImplementedError` for `rohf_external`, and `_ask` traps it and reports
   `external_stable=None`. "Could not be asked" and "was asked and came back
   stable" are different answers and must not be conflated, which is the exact
   mistake that produced a false 20-of-20 claim earlier in this engine's
   history: a loop read the external entry of a tuple that is None unless
   `external=True` was passed, and `not None` is true.

    PYTHONPATH=$PWD python3 tests/backend/cas_21_reference_stability.py
"""
from __future__ import annotations

import sys

FAILURES = []


def check(label, ok, detail=""):
    print(f"  [{'PASS' if ok else 'FAIL'}] {label}" + (f" -- {detail}" if detail else ""))
    if not ok:
        FAILURES.append(label)


def geometry(name):
    import numpy as np
    from scripts.casbench import reference_data as ref
    syms, co, chg, mult = ref.molecule(name)
    return syms, np.asarray(co, float), chg, mult


def scf_for(name, basis="def2-svp"):
    """A converged but deliberately UNstabilised reference."""
    from pyscf import gto, scf
    syms, co, chg, mult = geometry(name)
    atom = "\n".join(f"{s} {c[0]:.8f} {c[1]:.8f} {c[2]:.8f}"
                     for s, c in zip(syms, co))
    mol = gto.M(atom=atom, basis=basis, charge=chg, spin=mult - 1, verbose=0)
    mf = (scf.RHF(mol) if mult == 1 else scf.ROHF(mol)).density_fit()
    mf.kernel()
    return mf


def main():
    from app.chemistry.cas.reference import MAX_FOLLOW, stabilise

    print("The report a caller can act on")
    mf = scf_for("water")
    st = stabilise(mf, check_external=False)
    d = st.to_dict()
    missing = [k for k in ("followed", "internal_stable", "energy_before",
                           "energy_after") if k not in d]
    check("the report carries followed, internal_stable and both energies",
          not missing, f"missing {missing}" if missing else str(sorted(d)))
    check("water's RHF reference is already stable, so nothing is followed",
          st.followed == 0 and st.internal_stable is True,
          f"followed={st.followed} internal_stable={st.internal_stable}")
    check("and `moved` is False when nothing was followed", st.moved is False)

    # Which basis matters here, and the reason is the finding itself. Measured
    # over the benchmark's diradicals in three bases, twisted ethylene's
    # reference is unstable in STO-3G (58.1 mHa below) and in cc-pVDZ (30.8
    # mHa, which is the gap the CHANGELOG records) and STABLE in def2-SVP.
    # Stretched N2 is unstable in all three. So whether there is an instability
    # to follow depends on where the initial guess lands, which is precisely
    # why repeating a run could never have exposed this: a deterministic wrong
    # answer repeats.
    print("\nTwisted ethylene in cc-pVDZ, the case the fix was built for")
    mf = scf_for("ethylene_twisted", basis="cc-pvdz")
    st = stabilise(mf, check_external=False)
    check("an instability is found and followed", st.followed >= 1,
          f"followed={st.followed}")
    check("`moved` reports it", st.moved is True)
    if st.energy_after is not None and st.energy_before is not None:
        drop_mha = (st.energy_before - st.energy_after) * 1000.0
        check("the energy afterwards is LOWER, which is what following an "
              "instability means",
              st.energy_after < st.energy_before,
              f"{st.energy_before:.8f} -> {st.energy_after:.8f} Ha "
              f"({drop_mha:.2f} mHa lower)")
        check("and the drop is the tens-of-mHa one on record, not convergence "
              "noise", drop_mha > 10.0, f"{drop_mha:.2f} mHa")
    else:
        check("both energies are recorded when something was followed",
              False, f"before={st.energy_before} after={st.energy_after}")
    check("the follow loop stopped short of its cap rather than giving up at it",
          st.followed < MAX_FOLLOW, f"followed={st.followed}, cap={MAX_FOLLOW}")

    print("\nThe stabilised reference is a minimum, not just a different point")
    st2 = stabilise(mf, check_external=False)
    check("asking again reports stable and follows nothing",
          st2.followed == 0 and st2.internal_stable is True,
          f"followed={st2.followed} internal_stable={st2.internal_stable}")

    print("\nStretched N2, which is unstable in every basis tried")
    mf = scf_for("N2_stretched")
    st = stabilise(mf, check_external=False)
    check("an instability is found and followed here too", st.followed >= 1,
          f"followed={st.followed}")
    if st.energy_after is not None and st.energy_before is not None:
        check("and the energy drops",
              st.energy_after < st.energy_before,
              f"{(st.energy_before - st.energy_after) * 1000:.2f} mHa lower")

    print("\nWhether there is an instability to follow depends on the basis")
    mf = scf_for("ethylene_twisted", basis="def2-svp")
    st = stabilise(mf, check_external=False)
    check("the same molecule in def2-SVP lands on the stable solution and "
          "nothing is followed",
          st.followed == 0 and st.internal_stable is True,
          f"followed={st.followed}. This is not a weaker case than the one "
          f"above: it is why the defect survived repeated runs, since the "
          f"guess decides which solution is reached and a deterministic wrong "
          f"answer repeats")

    print("\nAn open-shell reference does not crash on the external check")
    try:
        mf = scf_for("O2")
        st = stabilise(mf, check_external=True)
        raised = None
    except NotImplementedError as exc:                      # noqa: BLE001
        st, raised = None, exc
    check("ROHF external stability is unavailable in pyscf and is trapped, "
          "not raised", raised is None, f"{raised!r}")
    if st is not None:
        check("and it is reported as None rather than as stable, because "
              "'could not be asked' is not an answer",
              st.external_stable is None,
              f"external_stable={st.external_stable}")
        check("the internal check still ran",
              st.internal_stable is not None,
              f"internal_stable={st.internal_stable}")

    print(f"\n{len(FAILURES)} failure(s)"
          + (": " + "; ".join(FAILURES) if FAILURES else ""))
    return 1 if FAILURES else 0


if __name__ == "__main__":
    sys.exit(main())
