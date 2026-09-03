#!/usr/bin/env python3
"""Refinement measures the space instead of predicting it, in the right order.

The recommendation engine chooses a space a priori and never runs a CASSCF.
`app/chemistry/cas/refine.py` is the opposite trade: solve, look at what the
optimisation actually did, correct, prune, re-verify.

The assertions here are mostly about *ordering and restraint*, because that is
where this can go wrong quietly.

**The negative control.** Pruning by natural occupation without first asking
whether the requested states are present will throw away orbitals that are not
inert at all -- they only look inert because the state that needed them fell
outside the averaging window and their character leaked out of the space.
Uracil at four roots is the case: both carbonyl lone pairs relax to 2.000 and
1.999, and a cut takes them. At six roots, with the n->pi* state inside the
window, one sits at 1.667 and survives. If the naive path ever stops looking
inert, the ordering constraint has gone and the docstrings are wrong.

**The subspace measure.** Per-orbital sigma weight cannot detect character
loss: the sigma target set is over-complete and spans nearly everything, so
every converged pi orbital reports a sigma weight near 1. The subspace measure
-- how much pi and lone-pair target weight the active space holds, before
against after -- does detect it.

**Restraint.** A prune is only kept if the states survive it *and* no requested
energy moved more than the tolerance. A space that cannot shrink comes back
unshrunk with a reason rather than shrunk and wrong.

Needs pyscf but no live stack. Several SA-CASSCF solves: about two minutes.

Run:  PYTHONPATH=$PWD python3 tests/backend/cas_10_refinement.py
"""
import numpy as np
from pyscf import dft, gto, mcscf, scf, tdscf

from app.chemistry.cas.excited import _target_weights, analyse
from app.chemistry.cas.geometry import perceive
from app.chemistry.cas.projector import project
from app.chemistry.cas.recommend import recommend
from app.chemistry.cas.refine import (
    INERT_OCCUPIED,
    INERT_VIRTUAL,
    audit_character,
    prune_candidates,
    refine,
    state_averaged_occupations,
    subspace_target_weight,
)
from scripts.casbench import reference_data as ref

PASS = 0
FAIL = 0
BASIS = "cc-pvdz"


def check(label: str, ok: bool, detail: str = "") -> None:
    global PASS, FAIL
    if ok:
        PASS += 1
        print(f"  [PASS] {label}")
    else:
        FAIL += 1
        print(f"  [FAIL] {label}" + (f"\n         {detail}" if detail else ""))


def setup(name, n_states, want_states=True):
    syms, co, chg, mult = ref.GEOMETRIES[name]
    co = np.asarray(co, float)
    mol = gto.M(atom="\n".join(f"{a} {c[0]} {c[1]} {c[2]}"
                               for a, c in zip(syms, co)),
                basis=BASIS, charge=chg, spin=mult - 1, verbose=0)
    mf = (scf.RHF(mol) if mult == 1 else scf.ROHF(mol)).density_fit().run()
    rec = recommend(mf, syms, co, spin_2s=mult - 1, n_states=n_states)
    an, predicted = None, []
    if want_states and mult == 1 and n_states > 1:
        ks = dft.RKS(mol); ks.xc = "camb3lyp"; ks = ks.density_fit(); ks.kernel()
        td = tdscf.TDA(ks); td.nstates = max(6, 2 * (n_states - 1)); td.kernel()
        per = perceive(syms, co, include_sigma=False)
        an = analyse(ks, td, per.targets, n_states=n_states - 1)
        predicted = [s.character for s in an.states[:n_states - 1]
                     if s.particle_kind != "Rydberg" and "mixed" not in s.character]
    return syms, co, mol, mf, rec, an, predicted, mult - 1


def solve(mf, rec, tier_name, nroots, spin_2s=0):
    tier = rec.tiers[tier_name]
    caslst = list(tier.orbital_indices)
    ncas, nelec = len(caslst), tier.n_electrons
    mc = mcscf.CASSCF(mf, ncas, nelec)
    mc.fcisolver.nroots = nroots
    mc.state_average_([1.0 / nroots] * nroots)
    mc.max_cycle_macro = 60
    mc.conv_tol = 1e-6
    mc.verbose = 0
    mc.kernel(mcscf.sort_mo(mc, rec.mo_coeff, [c + 1 for c in caslst], base=1))
    return mc, caslst


def main() -> int:
    print("The negative control: occupations alone would discard uracil's "
          "lone pairs")
    syms, co, mol, mf, rec, an, predicted, spin = setup("uracil", 3)
    per = perceive(syms, co, include_sigma=False)
    pi_t = [t for t in per.targets if t.kind == "pi"]
    lp_t = [t for t in per.targets if t.kind == "lone_pair"]
    sg_t = [t for t in perceive(syms, co, include_sigma=True).targets
            if t.kind == "sigma"]

    # Uracil's own reference space, 5pi + 2n + 3pi*, solved two ways.
    idx = list(rec.tiers["recommended"].orbital_indices)
    pool_kind = []
    n_docc = rec.tiers["recommended"].n_electrons // 2
    for k, col in enumerate(idx):
        v = rec.mo_coeff[:, col]
        wpi = _target_weights(mol, v, pi_t).get("pi", 0.0)
        wlp = _target_weights(mol, v, lp_t).get("lone_pair", 0.0)
        pool_kind.append(("pi" if wpi > wlp else "n", 2 if k < n_docc else 0))
    PI = [k for k, (x, o) in enumerate(pool_kind) if x == "pi" and o]
    PIS = [k for k, (x, o) in enumerate(pool_kind) if x == "pi" and not o]
    LP = [k for k, (x, o) in enumerate(pool_kind) if x == "n" and o]
    sel = sorted(LP[-2:] + PI + PIS)
    nelec = 2 * sum(1 for k in sel if k < n_docc)

    occs = {}
    for nroots in (4, 6):
        mc = mcscf.CASSCF(mf, len(sel), nelec)
        mc.fcisolver.nroots = nroots
        mc.state_average_([1.0 / nroots] * nroots)
        mc.max_cycle_macro = 60
        mc.conv_tol = 1e-6
        mc.verbose = 0
        mc.kernel(mcscf.sort_mo(mc, rec.mo_coeff,
                                [idx[k] + 1 for k in sel], base=1))
        occ, _u = state_averaged_occupations(mc)
        act = mc.mo_coeff[:, mc.ncore:mc.ncore + mc.ncas]
        lp_occ = [float(occ[j]) for j in range(mc.ncas)
                  if _target_weights(mol, act[:, j], lp_t).get("lone_pair", 0)
                  > _target_weights(mol, act[:, j], pi_t).get("pi", 0)]
        occs[nroots] = sorted(lp_occ, reverse=True)
        held = subspace_target_weight(mol, act, lp_t)
        print(f"    SA-{nroots}: lone-pair occupations {[round(x, 3) for x in occs[nroots]]}, "
              f"lone-pair weight held {held:.2f}")

    dropped_4 = [x for x in occs[4] if x > INERT_OCCUPIED or x < INERT_VIRTUAL]
    dropped_6 = [x for x in occs[6] if x > INERT_OCCUPIED or x < INERT_VIRTUAL]
    check(f"at four roots an occupation cut takes {len(dropped_4)} lone pair(s) "
          f"-- they look inert only because the n->pi* fell outside the window",
          len(dropped_4) >= 1,
          f"occupations {occs[4]}")
    check(f"at six roots, with the state inside the window, fewer are taken "
          f"({len(dropped_6)} against {len(dropped_4)})",
          len(dropped_6) < len(dropped_4),
          f"SA-4 {occs[4]} vs SA-6 {occs[6]}")

    print("\nThe subspace measure detects what per-orbital sigma weight cannot")
    mc4, caslst = solve(mf, rec, "recommended", 4)
    act = mc4.mo_coeff[:, mc4.ncore:mc4.ncore + mc4.ncas]
    start = rec.mo_coeff[:, caslst]
    lost, detail = audit_character(mol, start, act, pi_t, lp_t)
    check(f"the subspace measure sees character leave ({lost:+.2f} orbitals' "
          f"worth: lone pair {detail['lone_pair_before']} -> "
          f"{detail['lone_pair_after']})", lost > 0.5, str(detail))
    sigma_weights = [
        _target_weights(mol, act[:, j], sg_t).get("sigma", 0.0)
        for j in range(mc4.ncas)
        if _target_weights(mol, act[:, j], pi_t).get("pi", 0.0) > 0.5
    ]
    check(f"while per-orbital sigma weight says nothing: every pi orbital "
          f"reports sigma {min(sigma_weights):.2f}-{max(sigma_weights):.2f}, "
          f"so a 'has sigma character' rule would flag all of them or none",
          sigma_weights and min(sigma_weights) > 0.2,
          f"sigma weights {[round(x, 2) for x in sigma_weights]}")

    print("\nThe loop shrinks a space that has slack, and matches the "
          "literature when it does")
    syms, co, mol, mf, rec, an, predicted, spin = setup("pyrrole", 3)
    res = refine(mf, syms, co, rec, n_states=3, analysis=an,
                 predicted=predicted, spin_2s=spin, log=lambda *a: None)
    got = (res.n_electrons, res.n_orbitals)
    check(f"pyrrole CAS{rec.space} refines to CAS{got}, its classical pi space",
          got == (6, 5), f"got {got}; {res.stopped_because}")
    check("and the change is recorded as a rotation with its reason",
          any(r.action == "prune" for r in res.rotations),
          f"rotations {[r.action for r in res.rotations]}")
    check("every prune names the orbital and the occupation that justified it",
          all(r.mo_out is not None and r.occupation is not None
              for r in res.rotations if r.action == "prune"))
    check(f"the tier it actually started from is recorded "
          f"({res.started_from} {res.start_space})",
          res.started_from == "recommended" and res.start_space == rec.space)

    print("\nA space with no slack comes back unchanged rather than cut")
    syms, co, mol, mf, rec, an, predicted, spin = setup("formaldehyde", 3)
    res = refine(mf, syms, co, rec, n_states=3, analysis=an,
                 predicted=predicted, spin_2s=spin, log=lambda *a: None)
    check(f"formaldehyde CAS{rec.space} stays CAS({res.n_electrons},"
          f"{res.n_orbitals}) -- every orbital carries correlation",
          (res.n_electrons, res.n_orbitals) == rec.space,
          f"{res.stopped_because}")
    check("nothing was pruned, and the reason says so",
          not [r for r in res.rotations if r.action == "prune"]
          and "correlation" in res.stopped_because,
          res.stopped_because)

    print("\nOpen-shell molecules refine, with the electron count kept spin "
          "aware")
    syms, co, mol, mf, rec, an, predicted, spin = setup("O2", 2, want_states=False)
    res = refine(mf, syms, co, rec, n_states=2, spin_2s=spin,
                 log=lambda *a: None)
    check(f"O2 triplet CAS{rec.space} refines to CAS({res.n_electrons},"
          f"{res.n_orbitals}) and converges", res.converged,
          res.stopped_because)
    check("the refined space still holds the two unpaired electrons",
          res.n_electrons >= 2 and res.n_electrons < 2 * res.n_orbitals,
          f"CAS({res.n_electrons},{res.n_orbitals})")

    print("\nThe occupation window is what decides a prune, and it is stated")
    check(f"the inert window is [{INERT_VIRTUAL}, {INERT_OCCUPIED}]",
          INERT_VIRTUAL < 0.05 and INERT_OCCUPIED > 1.95)
    check("an orbital at 1.999 is a prune candidate and one at 1.667 is not",
          prune_candidates(np.array([1.999, 1.667])) == [0])

    print(f"\n{PASS} passed, {FAIL} failed")
    return 1 if FAIL else 0


if __name__ == "__main__":
    raise SystemExit(main())
