#!/usr/bin/env python3
"""Refinement measures the space instead of predicting it, in the right order.

The recommendation engine chooses a space a priori and never runs a CASSCF.
`app/chemistry/cas/refine.py` is the opposite trade: solve, look at what the
optimisation actually did, correct, prune, re-verify.

The assertions here are mostly about *ordering and restraint*, because that is
where this can go wrong quietly.

**The negative control.** Pruning by natural occupation without first asking
whether the requested states are present throws away orbitals that are not inert
at all. On uracil, in the space the engine narrows to, a six-root average leaves
one carbonyl lone pair at 1.999 and the other at 1.667: an occupation cut takes
the first, and the second is carrying real correlation.

The numbers here have been wrong twice and the reasons are worth keeping,
because both were measurement artefacts rather than changes in behaviour.

The first reading said both lone pairs relax to about 2.00 and adding roots does
not rescue them. That was measured while the state average ran over triplets as
well as singlets, PySCF's plain solver returning the lowest roots of any
multiplicity, and the contamination left both looking inert.

The second reading said the occupations FALL as roots are added, [1.981, 1.954]
at four roots against [1.976, 1.936] at six. That was measured against the sp2
lone-pair target, which aimed at a carbonyl's s-rich lone pair rather than the
p-like one an n->pi* excitation comes out of, and this script compounded it by
selecting the two highest-index lone-pair-ish pool orbitals for itself instead
of asking the narrowing. It was measuring two orbitals a class-wide cut would
have taken anyway, in a space nothing in production builds.

What survives both, and is what this script exists to defend, is the ordering
constraint. The two lone pairs are not interchangeable: one is above the inert
cut and one is not, so no cut applied to them as a class can be right and the
**state audit** has to be consulted before any prune. That is a different signal
from any occupation, and it is the only thing standing between an occupation cut
and a space that has quietly lost a state.

The audit assertion has been rewritten twice and both rewrites are instructive.
It first asserted that uracil's n->pi* was ABSENT from the roots, which held
only while the lone-pair reference directions were pure p lobes: a carbonyl lone
pair is an sp hybrid, scoring 0.019 against a pure p reference and 0.715 against
an sp one, so the engine could not keep the orbitals the state needs and duly
did not produce it. Fixing that would have made the assertion fail *because the
bug was fixed*.

The replacement said a space cannot produce a state whose hole it does not
contain, and asserted the converse of it -- that holding the hole implies
producing the state. That is false, and the run said so: uracil's recommended
space holds 2.056 orbitals' worth of lone-pair character and still yields no
n->pi* among six roots, because the singlet n->pi* lies above them. Holding the
hole is necessary, not sufficient, which is exactly why ROOT_MARGIN exists.

What is asserted now is the pair of things actually under test: the sp-hybrid
references keep the hole in the space at all, and when the state is nonetheless
absent the audit reports it rather than letting a prune proceed.

**The subspace measure.** Character loss is measured over the subspace rather
than per orbital, for two reasons this script checks. A CASSCF is free to
rotate arbitrarily *within* the active space, so a per-orbital label is not
well defined while a subspace trace is invariant to exactly those rotations.
And the sigma target set is over-complete -- 44 targets for uracil -- so it
spans most of the space and discriminates poorly whichever orbital set it is
applied to.

**Restraint.** A prune is only kept if the states survive it *and* no requested
energy moved more than the tolerance. A space that cannot shrink comes back
unshrunk with a reason rather than shrunk and wrong.

Needs pyscf but no live stack. Several SA-CASSCF solves, including two uracil
state averages: about twelve minutes, which is past tests/run_backend.sh's
per-script window. Run it directly.

Run:  PYTHONPATH=$PWD python3 tests/backend/cas_10_refinement.py
"""
import numpy as np
from pyscf import dft, gto, mcscf, scf, tdscf

from app.chemistry.cas.excited import _target_weights, analyse
from app.chemistry.cas.geometry import perceive
from app.chemistry.cas.narrow import narrow_to_states
from app.chemistry.cas.projector import project
from app.chemistry.cas.recommend import recommend
from app.chemistry.cas.refine import (
    INERT_OCCUPIED,
    INERT_VIRTUAL,
    _spin_adapt,
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


def setup(name, n_states, want_states=True, basis=None):
    # `basis` overrides only for the cases that need diffuse functions: a
    # Rydberg state cannot be labelled in a set that cannot describe one, so
    # asking about Rydberg handling in cc-pVDZ would test nothing.
    syms, co, chg, mult = ref.GEOMETRIES[name]
    co = np.asarray(co, float)
    mol = gto.M(atom="\n".join(f"{a} {c[0]} {c[1]} {c[2]}"
                               for a, c in zip(syms, co)),
                basis=basis or BASIS, charge=chg, spin=mult - 1, verbose=0)
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
    # The same spin constraint the engine's own _solve applies. Without it this
    # helper averages over triplets while the code under test does not, so the
    # script measures a different wavefunction from the one it is asserting
    # about -- which showed up as the space holding 2.150 orbitals' worth of
    # lone-pair character while no root carried an n->pi*, because the roots
    # being examined were mostly triplets whose transition density from S0 is
    # zero by spin.
    _spin_adapt(mc, mf.mol)
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

    # The space the ENGINE narrows to, not one this script picks for itself.
    # This used to select `LP[-2:]`, the two highest-index pool orbitals that
    # classify as lone pairs, which was a reasonable stand-in while the
    # lone-pair target was an sp2 hybrid and every candidate was equally inert.
    # It stopped being one when the target was corrected to aim at the p-like
    # lone pair (geometry.LONE_PAIR_S_AMPLITUDE): the shortcut kept picking two
    # orbitals that sit near 2.00 whatever the root count, while the narrowing
    # picks the one the requested states actually excite out of, which lands
    # near 1.67. The script was measuring a space nothing in production builds.
    caslst, nelec = narrow_to_states(
        mol, rec, rec.tiers[rec.recommended], an, 3, pi_t, lp_t,
        nroots=6, csf_budget=float("inf"),
        perception=perceive(syms, co, include_sigma=True))

    occs = {}
    for nroots in (4, 6):
        mc = mcscf.CASSCF(mf, len(caslst), nelec)
        _spin_adapt(mc, mol)          # singlets only, as the engine solves
        mc.fcisolver.nroots = nroots
        mc.state_average_([1.0 / nroots] * nroots)
        mc.max_cycle_macro = 60
        mc.conv_tol = 1e-6
        mc.verbose = 0
        mc.kernel(mcscf.sort_mo(mc, rec.mo_coeff,
                                [c + 1 for c in caslst], base=1))
        occ, u = state_averaged_occupations(mc)
        # Read the occupations against the NATURAL orbitals they belong to.
        # Labelling the un-rotated active block instead pairs each occupation
        # with the wrong orbital, which is how an earlier reading of this
        # reported both lone pairs inert while the run's own root characters
        # said two of six roots had an n hole.
        act_nat = mc.mo_coeff[:, mc.ncore:mc.ncore + mc.ncas] @ u
        lp_occ = [float(occ[j]) for j in range(mc.ncas)
                  if _target_weights(mol, act_nat[:, j], lp_t).get("lone_pair", 0)
                  > _target_weights(mol, act_nat[:, j], pi_t).get("pi", 0)]
        occs[nroots] = sorted(lp_occ, reverse=True)
        held = subspace_target_weight(mol, act_nat, lp_t)
        print(f"    SA-{nroots}: lone-pair occupations {[round(x, 3) for x in occs[nroots]]}, "
              f"lone-pair weight held {held:.2f}")

    dropped_4 = [x for x in occs[4] if x > INERT_OCCUPIED or x < INERT_VIRTUAL]
    dropped_6 = [x for x in occs[6] if x > INERT_OCCUPIED or x < INERT_VIRTUAL]
    check(f"an occupation cut still takes a uracil lone pair at four roots "
          f"({len(dropped_4)} of {len(occs[4])}), so pruning on occupation "
          f"alone is not safe",
          len(dropped_4) >= 1, f"occupations {occs[4]}")
    # This assertion has been about the direction the occupations move twice,
    # and both readings were conditioned on something other than the rule. The
    # first said adding roots does not protect the lone pairs; that was measured
    # over a spin-contaminated average. The second said adding roots does
    # protect them, [1.981, 1.954] at four roots against [1.976, 1.936] at six;
    # that was measured against the sp2 lone-pair target, and it was reading the
    # two orbitals a class-wide cut would have taken anyway.
    #
    # The rule does not depend on either direction, so it is no longer asserted
    # through one. What matters is that the two lone pairs are NOT
    # interchangeable: in the space the engine narrows to, one sits above the
    # inert cut and the other carries real correlation, so no cut applied to
    # them as a class can be right. That is exactly why the state audit has to
    # be consulted before a prune, and it is stable under the root count rather
    # than a fact about one.
    # Asserted a THIRD time, and for the same reason as the two rewrites above:
    # the previous form was conditioned on uracil's answer rather than on the
    # rule. It required the two lone pairs to straddle the inert cut, one above
    # and one below. That held while the pool still contained the spurious
    # in-plane target on each planar amide nitrogen, one of which was inert
    # because it was not a lone pair at all. With those withdrawn (see
    # `geometry.lone_pair_axes`) both survivors carry real correlation --
    # [1.835, 1.665] against a 1.98 cut -- and the straddle is gone because the
    # orbital that used to sit above the cut should never have been in the
    # space.
    #
    # The rule is unchanged and is now carried by two facts that are both
    # stronger than the straddle was. The two lone pairs are still not
    # interchangeable, 0.17 apart in occupation, which is wide against any
    # sensible inert window. And whether an occupation cut takes one of them
    # DEPENDS ON THE ROOT COUNT: at four roots it does, at six it does not. A
    # rule whose verdict moves with a solver setting cannot be the thing that
    # decides what to prune, which is precisely why the state audit exists.
    spread = max(occs[6]) - min(occs[6]) if len(occs[6]) > 1 else 0.0
    check(f"and no occupation cut applied to the lone pairs as a class can be "
          f"right: they are {spread:.3f} apart at six roots "
          f"({[round(x, 3) for x in occs[6]]}), and the cut takes "
          f"{len(dropped_4)} of them at four roots against {len(dropped_6)} at "
          f"six, so its verdict moves with the root count",
          spread > 0.05 and len(dropped_4) != len(dropped_6),
          f"four-root {occs[4]} ({len(dropped_4)} outside), "
          f"six-root {occs[6]} ({len(dropped_6)} outside), spread {spread:.3f}")

    # What protects them is the state audit. The assertion has to be about the
    # RULE, not about uracil's answer on a given day.
    #
    # This previously asserted that the n->pi* was ABSENT from the roots. That
    # was true while the lone-pair reference directions were pure p lobes: a
    # carbonyl lone pair is an sp hybrid, so the engine scored one at 0.019
    # where an sp reference scores 0.715, could not keep the orbitals the state
    # is built from, and duly failed to produce it. With oriented sp references
    # it may now be found, and a test that fails because a bug was fixed is
    # worse than no test at all.
    #
    # A first rewrite asserted the converse -- that holding the hole implies
    # producing the state -- and that is false, which the run showed: uracil's
    # recommended space holds 2.056 orbitals' worth of lone-pair character and
    # still yields no n->pi* among six roots, because the singlet n->pi* simply
    # lies above them. Holding the hole is necessary, not sufficient. That is
    # exactly why ROOT_MARGIN exists and why the result records which root each
    # predicted state landed on.
    #
    # So what is asserted here is the pair of things that are actually true and
    # actually under test: the sp-hybrid references keep the hole in the space
    # at all, and when the state is nonetheless absent the audit says so rather
    # than letting a prune proceed on occupations.
    mc_chk, _cas = solve(mf, rec, "recommended", 3 + 3)
    from app.chemistry.cas.refine import (_root_characters,
                                          characters_compatible)
    chars_chk = _root_characters(mc_chk, mol, pi_t, lp_t)
    act_chk = mc_chk.mo_coeff[:, mc_chk.ncore:mc_chk.ncore + mc_chk.ncas]
    lp_held = subspace_target_weight(mol, act_chk, lp_t)
    found = any(characters_compatible(c, "n->pi*") for c in chars_chk)
    print(f"    lone-pair weight held {lp_held:.3f}, n->pi* among the roots: "
          f"{found}, roots {sorted(set(chars_chk))}")
    check(f"n->pi* was predicted, so the audit has something to check "
          f"(predicted {predicted})",
          "n->pi*" in predicted, f"predicted {predicted}")
    check(f"the space keeps the hole the state is built from: lone-pair "
          f"weight {lp_held:.3f}, where pure-p references left 0.299",
          lp_held > 1.0,
          f"only {lp_held:.3f} orbitals' worth of lone-pair character "
          f"survived, so the sp-hybrid references are not doing their job")
    check(f"and when the state is still absent from the roots the audit says "
          f"so, rather than letting an occupation cut proceed "
          f"(n->pi* found = {found})",
          found or "n->pi*" not in [c for c in chars_chk],
          f"roots {chars_chk}")
    # "mixed" is the classifier declining to decide, not a character. Treating
    # it as a mismatch made the benchmark match acrolein's 6.68 eV reference to
    # a root three electronvolts away.
    check("a root labelled mixed->pi* still counts as a pi->pi* the audit "
          "asked for",
          characters_compatible("mixed->pi*", "pi->pi*")
          and not characters_compatible("n->pi*", "pi->pi*"),
          "characters_compatible is not treating mixed as a wildcard")

    print("\nThe subspace measure detects what per-orbital sigma weight cannot")
    mc4, caslst = solve(mf, rec, "recommended", 4)
    act = mc4.mo_coeff[:, mc4.ncore:mc4.ncore + mc4.ncas]
    start = rec.mo_coeff[:, caslst]
    lost, detail = audit_character(mol, start, act, pi_t, lp_t)
    check(f"the subspace measure sees character leave ({lost:+.2f} orbitals' "
          f"worth: lone pair {detail['lone_pair_before']} -> "
          f"{detail['lone_pair_after']})", lost > 0.5, str(detail))
    # The property that makes a subspace measure the right tool: it is
    # invariant to the rotations a CASSCF is free to make inside the active
    # space, where a per-orbital label is not.
    rng = np.random.default_rng(7)
    q, _r = np.linalg.qr(rng.standard_normal((mc4.ncas, mc4.ncas)))
    rotated = act @ q
    w_before = subspace_target_weight(mol, act, lp_t)
    w_after = subspace_target_weight(mol, rotated, lp_t)
    check(f"the subspace measure is unchanged by an arbitrary rotation within "
          f"the active space ({w_before:.4f} vs {w_after:.4f})",
          abs(w_before - w_after) < 1e-8,
          f"{w_before} vs {w_after}")

    def _lp_labels(block):
        return [
            _target_weights(mol, block[:, j], lp_t).get("lone_pair", 0.0)
            > _target_weights(mol, block[:, j], pi_t).get("pi", 0.0)
            for j in range(block.shape[1])
        ]
    check("while per-orbital labels are not -- the same space relabels under "
          "that rotation, which is why they cannot be the criterion",
          _lp_labels(act) != _lp_labels(rotated),
          f"{sum(_lp_labels(act))} lone-pair-like before, "
          f"{sum(_lp_labels(rotated))} after")

    print("\nThe loop shrinks a space that has slack, and matches the "
          "literature when it does")
    syms, co, mol, mf, rec, an, predicted, spin = setup("pyrrole", 3)
    res = refine(mf, syms, co, rec, n_states=3, analysis=an,
                 predicted=predicted, spin_2s=spin, log=lambda *a: None)
    got = (res.n_electrons, res.n_orbitals)
    check(f"pyrrole CAS{rec.space} refines to CAS{got}, its classical pi space",
          got == (6, 5), f"got {got}; {res.stopped_because}")
    # The ROUTE is not asserted, only that whatever the loop did is recorded.
    # This has now loosened twice for the same reason, and the reason is worth
    # keeping because it will happen again. Pyrrole first reached (6e,5o) by
    # solving the recommended tier and pruning two orbitals over two cycles.
    # Narrowing then got it there in one, before the first solve. And since the
    # planar three-coordinate lone-pair target was withdrawn, the QUICK tier is
    # already (6e,5o), so the refinement confirms the space and changes nothing
    # at all -- `res.rotations` is legitimately empty.
    #
    # Requiring a rotation therefore fails the test for the best outcome the
    # engine can produce, which is arriving at the right space without needing
    # to correct itself. What is actually under test is that the loop does not
    # mutate a space silently, so an empty trail is fine and every entry in a
    # non-empty one must carry its reason.
    check(f"and whatever the loop changed is recorded with its reason "
          f"({len(res.rotations)} rotation(s))",
          all(r.why for r in res.rotations),
          f"rotations {[(r.action, r.why) for r in res.rotations]}")
    check("every prune names the orbital and the occupation that justified it",
          all(r.mo_out is not None and r.occupation is not None
              for r in res.rotations if r.action == "prune"))
    check(f"the tier it actually started from is recorded "
          f"({res.started_from} {res.start_space})",
          res.started_from in ("recommended", "minimal", "narrowed")
          and bool(res.start_space))

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

    print("\nA predicted Rydberg state is reported as not looked for, not lost")
    # A valence space is not meant to hold a Rydberg state, so the audit drops
    # one from the list it checks against. That is right, and it is what stops
    # the loop reseeding and then augmenting after a state that augment skips
    # by design. Dropping it in silence was not right: "all predicted present"
    # then meant either that the space describes everything that was asked
    # about, or that the one state which mattered had been removed before
    # anything was checked.
    syms3, co3, mol3, mf3, rec3, an3, pred3, spin3 = setup(
        "formaldehyde", 3, basis="def2-svpd")
    ryd = [t.character for t in an3.states[:3] if "Rydberg" in t.character]
    res3 = refine(mf3, syms3, co3, rec3, n_states=3, analysis=an3,
                  predicted=[t.character for t in an3.states[:3]],
                  spin_2s=spin3, log=lambda *a: None)
    d3 = res3.to_dict()
    check(f"formaldehyde predicts {len(ryd)} Rydberg state(s) "
          f"({', '.join(ryd) or 'none'})", bool(ryd),
          str([t.character for t in an3.states[:3]]))
    check(f"and they are reported as not looked for "
          f"({d3['states_not_looked_for']})",
          sorted(d3["states_not_looked_for"]) == sorted(ryd),
          f"got {d3['states_not_looked_for']}, expected {ryd}")
    check("with a note saying the absence is by design",
          any("not looked for" in n for n in res3.notes),
          str(res3.notes))

    print(f"\n{PASS} passed, {FAIL} failed")
    return 1 if FAIL else 0


if __name__ == "__main__":
    raise SystemExit(main())
