#!/usr/bin/env python3
"""The narrowed space is the same space every time, and is always a space.

Two failures the narrowing had, both of which reach a user as a recommendation
that changes between identical runs.

**It was not reproducible.** Water asked for three states narrowed to (4e,2o) in
one run and (2e,1o) in the next with no code change in between. What decides it
is a bare floating-point comparison between two near-degenerate projection
weights, and on a threaded machine that comparison is a coin toss.

**It could return something that is not an active space at all.** (2e,1o) is one
doubly occupied orbital: a single configuration, describing no correlation
whatsoever. `recommend()` has a guard for exactly this and declines to publish a
full space; the narrowing, which was added later, never got one.

Water is the regression molecule and it has to be asked for **three** states.
At one state nothing narrows, so the ground-state protocol every other test uses
would exercise none of this.

    PYTHONPATH=$PWD python3 tests/backend/cas_16_narrowing_stability.py
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


def geometry(name):
    from scripts.casbench import reference_data as ref
    syms, co, chg, mult = ref.molecule(name)
    return syms, np.asarray(co, float), chg, mult


def narrow_once(name, basis, n_states):
    """One full pass, exactly as `run_cas_recommendation` does it.

    The SCF, the linear response and the analysis are all redone per call
    rather than shared, because sharing them would test only the arithmetic
    downstream of them and the instability being chased lives in the
    projection weights those produce.
    """
    from pyscf import dft, gto, scf, tdscf

    from app.chemistry.cas.diffuse import rydberg_representable
    from app.chemistry.cas.excited import analyse
    from app.chemistry.cas.geometry import perceive
    from app.chemistry.cas.narrow import add_state_narrowed_tier
    from app.chemistry.cas.recommend import recommend

    syms, co, chg, mult = geometry(name)
    atom = "\n".join(f"{s} {c[0]:.8f} {c[1]:.8f} {c[2]:.8f}"
                     for s, c in zip(syms, co))
    mol = gto.M(atom=atom, basis=basis, charge=chg, spin=mult - 1, verbose=0)

    mf = (scf.RHF(mol) if mult == 1 else scf.ROHF(mol)).density_fit()
    mf.kernel()
    rec = recommend(mf, syms, co, spin_2s=mult - 1)

    ks = (dft.RKS(mol) if mult == 1 else dft.ROKS(mol)).density_fit()
    ks.xc = "camb3lyp"
    ks.kernel()
    td = tdscf.TDA(ks)
    td.nstates = max(2 * n_states, 6)
    td.kernel()

    per = perceive(syms, co, include_sigma=False)
    an = analyse(ks, td, per.targets, n_states=n_states,
                 rydberg_detectable=bool(rydberg_representable(ks)))

    added = add_state_narrowed_tier(rec, mol, an, n_states, per.targets,
                                    perception=per, spin_2s=mult - 1)
    tier = rec.tiers[rec.recommended]
    return {
        "added": bool(added),
        "tier_name": rec.recommended,
        "space": (tier.n_electrons, tier.n_orbitals),
        "orbitals": tuple(sorted(int(i) for i in tier.orbital_indices)),
        "characters": tuple(s.character or "?" for s in an.states[:n_states]),
    }


def main() -> int:
    print("cas_16: the narrowed space is stable, and is a space")

    repeats = 5
    name, basis, n_states = "water", "def2-svpd", 3
    print(f"\n{name} at {n_states} states in {basis}, {repeats} identical runs")

    runs = []
    for i in range(repeats):
        try:
            runs.append(narrow_once(name, basis, n_states))
        except Exception as exc:                            # noqa: BLE001
            check(f"run {i + 1} completes", False,
                  f"{type(exc).__name__}: {exc}")
            return 1

    for r in runs:
        print(f"    {r['tier_name']:16s} "
              f"({r['space'][0]}e,{r['space'][1]}o) "
              f"orbitals={r['orbitals']} states={r['characters']}")

    # Reproducibility. Compared on the orbital indices rather than the size,
    # because two runs can select the same NUMBER of orbitals and not the same
    # orbitals, and a size comparison would call that agreement.
    spaces = {r["space"] for r in runs}
    orbitals = {r["orbitals"] for r in runs}
    check("the narrowed space is identical across identical runs",
          len(spaces) == 1,
          f"{len(spaces)} distinct: {sorted(spaces)}")
    check("the selected orbitals are identical, not merely the same count",
          len(orbitals) == 1,
          f"{len(orbitals)} distinct selections")

    # Never a full space. A space whose every orbital is doubly occupied holds
    # exactly one configuration, so it describes no correlation and is not an
    # answer to the question that was asked.
    for r in runs:
        ne, no = r["space"]
        if r["tier_name"] != "state-narrowed":
            continue
        check(f"the narrowed tier ({ne}e,{no}o) is not a full space",
              ne < 2 * no,
              "every orbital doubly occupied: one configuration, no correlation")
        break

    # Every requested state here is Rydberg, and a valence space cannot hold
    # one. Narrowing a valence space toward states it cannot describe is what
    # makes the result arbitrary, so the engine should decline rather than
    # narrow toward nothing.
    all_rydberg = all("Rydberg" in c for c in runs[0]["characters"])
    if all_rydberg:
        check("no narrowed tier is published when every requested state is "
              "Rydberg", not any(r["added"] for r in runs),
              "narrowed toward states a valence space cannot hold")
    else:
        print(f"    (states were {runs[0]['characters']}, not all Rydberg -- "
              f"the decline check does not apply in this basis)")

    print(f"\n{len(FAILURES)} failure(s)"
          + (": " + "; ".join(FAILURES) if FAILURES else ""))
    return 1 if FAILURES else 0


if __name__ == "__main__":
    sys.exit(main())
