"""P1.10: do the recommendation's narrowing and the refinement's ever disagree?

The two call sites differ in exactly two arguments:

  runner (run_cas_recommendation):  nroots=n_states,        csf_budget=inf
  refine():                         nroots=expected_roots,  csf_budget=CSF_BUDGET

`nroots` is read in ONE place inside narrow_to_states -- the `fits` backstop,
`c * max(nroots, 1) <= csf_budget` -- and nowhere else. So with an infinite
budget `fits` is always true and nroots cannot matter at all, and the two calls
can only diverge when the refinement's FINITE budget actually bites, i.e. when
the narrowed space costs more than CSF_BUDGET over its root count. This asks
how often that happens on the benchmark.

It is a priori: no CASSCF is run, only the SCF and the TDA the analysis needs.
"""
import numpy as np
from pyscf import tdscf

from app.chemistry.cas.excited import analyse
from app.chemistry.cas.geometry import perceive
from app.chemistry.cas.narrow import narrow_to_states
from app.chemistry.cas.recommend import recommend
from app.chemistry.cas.refine import CSF_BUDGET, ROOT_MARGIN
from app.chemistry.cas.feasibility import assess
from scripts.casbench import reference_data as ref
from scripts.casbench.run_bench import _mf

N_STATES = 3
BASIS = "def2-svpd"

print(f"CSF_BUDGET={CSF_BUDGET:.0f}  ROOT_MARGIN={ROOT_MARGIN}  "
      f"n_states={N_STATES}\n")
print(f"{'molecule':22s} {'runner(inf)':14s} {'refine(finite)':14s} verdict")
print("-" * 74)

differ, same, skipped = [], [], []
for name in sorted(ref.GEOMETRIES):
    syms, co, chg, mult = ref.molecule(name)
    if mult != 1:
        skipped.append(name)
        continue
    co = np.asarray(co, float)
    try:
        _m, mf = _mf(syms, co, BASIS, chg, mult)
        rec = recommend(mf, syms, co, spin_2s=0, n_states=N_STATES)
        _m2, ks = _mf(syms, co, BASIS, chg, mult, dft_xc="camb3lyp")
        td = tdscf.TDA(ks)
        td.nstates = max(6, 2 * (N_STATES - 1))
        td.kernel()
        per = perceive(syms, co, include_sigma=False)
        an = analyse(ks, td, per.targets, n_states=N_STATES - 1)
        pi_t = [t for t in per.targets if t.kind == "pi"]
        lp_t = [t for t in per.targets if t.kind == "lone_pair"]
        base = rec.tiers.get(rec.recommended) or rec.tiers.get("recommended")

        # The runner's call: chemistry first, cost reported afterwards.
        a_cas, a_ne = narrow_to_states(
            mf.mol, rec, base, an, N_STATES, pi_t, lp_t,
            nroots=N_STATES, csf_budget=float("inf"), perception=per)
        # refine()'s call: the same rule under a finite budget.
        expected_roots = max(1, N_STATES) + (ROOT_MARGIN if N_STATES > 1 else 0)
        b_cas, b_ne = narrow_to_states(
            mf.mol, rec, base, an, N_STATES, pi_t, lp_t,
            nroots=expected_roots, csf_budget=CSF_BUDGET, perception=per)
    except Exception as exc:                                    # noqa: BLE001
        print(f"{name:22s} FAILED {type(exc).__name__}: {exc}"[:74])
        skipped.append(name)
        continue

    # Compare the ORBITALS, not just how many there are. The first version of
    # this script compared `(n_electrons, n_orbitals)` and reported 34 of 34
    # agreeing, which was true and did not mean what it was used for: two calls
    # can select the same NUMBER of orbitals and not the same orbitals, and a
    # refinement started from a different set of ten columns is a different
    # refinement. cas_10 caught it downstream, which is the wrong place.
    a = (a_ne, tuple(sorted(a_cas)))
    b = (b_ne, tuple(sorted(b_cas)))
    if a == b:
        same.append(name)
        verdict = "same"
    else:
        differ.append((name, a, b))
        verdict = (f"*** DIFFERS  runner {sorted(a_cas)} vs "
                   f"refine {sorted(b_cas)}")
    print(f"{name:22s} {str((a[0],len(a[1]))):12s} "
          f"{str((b[0],len(b[1]))):12s} {verdict}")

print(f"\n{len(same)} agree, {len(differ)} differ, {len(skipped)} skipped")
for name, a, b in differ:
    print(f"  {name}: runner {(a[0], list(a[1]))}\n           refine {(b[0], list(b[1]))}")
