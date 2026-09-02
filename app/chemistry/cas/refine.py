"""Refine a recommended active space against real CASSCF evidence.

The recommendation engine chooses a space *a priori*: geometry-derived
projection, then a closed-form entropy from the Hartree-Fock Fock and exchange
matrices. It never runs a CASSCF, which is what removes any cap on the space
and keeps a recommendation to a fraction of a second. The cost is that nothing
measures what was predicted.

This module is the opposite trade. It runs the CASSCF, looks at what actually
happened, and corrects the space accordingly -- slower by design, and offered
only after a recommendation exists.

Three things are measured that an a-priori method cannot see.

**Orbitals rotate.** A CASSCF optimises the orbitals as well as the CI vector,
and the space it converges to need not be the space it was handed: sigma can
rotate in and displace the pi/pi* pair that was put there. The manual fix is to
restart with the correct pair rotated back in, and that is what
`audit_character` and `reseed` automate.

**Occupations say what the entropy only estimated.** An orbital whose
state-averaged natural occupation stays at 2.00 or 0.00 across every averaged
root carries no correlation and can go.

**The two interact, and the order matters.** This is the whole design
constraint, and it was found by measurement rather than argument. On uracil in
cc-pVDZ, averaging over four roots, both carbonyl lone pairs converge to
occupations of 2.000 and 1.999 and look perfectly inert. They are not inert:
the n->pi* state has fallen outside the four-root window, and the lone-pair
character has leaked out of the active space -- the space holds 0.52 of the
lone-pair target weight where it started with 1.95. Prune on occupation alone
and both are discarded, the n->pi* states become unreachable, and the
calculation appears to have proved they were never needed. Average over six
roots instead, so the state is inside the window, and one lone pair sits at
1.667 and survives any sensible cut.

So the loop is **audit the states, then decide, then prune** -- and the
character measurement is the *diagnostic* that decides how to respond to a
missing state, not a gate of its own. That ordering was corrected after the
first implementation ran: firing a re-seed on character loss alone dead-ends,
because character leaving an active space has two entirely different meanings.

- A predicted state is **missing** and character has left: the space lost
  something it needed. Re-seed it.
- Every predicted state is **present** and character has left: the space
  contained orbitals those states do not use, and the optimisation quietly
  handed them back. That is evidence for *pruning*, not against it.

Uracil shows the second case plainly. Its recommended space, CAS(22e,14o),
holds all six lone-pair-derived orbitals; asked for three states it gives back
4.26 orbitals' worth of lone-pair character, because three states do not need
six lone pairs. Forcing them back in is fighting the right answer.

A second measurement shaped `audit_character`. Detecting the leak per orbital
by asking "does this converged orbital have sigma character?" does not work:
the sigma target set is over-complete -- 44 targets for uracil, 55 for
o-nitrophenol -- and spans almost everything, so *every* converged pi orbital
reports a sigma weight of 0.98. The measure that does work is at the level of
the subspace: how much of the pi and lone-pair target weight the active space
holds, before against after. That separates the two uracil cases cleanly (a
loss of 1.48 against 0.57) and, unlike a per-orbital label, is invariant to the
active-active rotations that CASSCF is free to make.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

# Natural-occupation window outside which an orbital is carrying nothing.
INERT_OCCUPIED = 1.98
INERT_VIRTUAL = 0.02

# A requested excitation that moves further than this under a prune means the
# prune was not free, whatever the occupations said.
MAX_ENERGY_DRIFT_EV = 0.20

# Target weight, in orbitals, that may leave the active space before it counts
# as character having been lost. Chosen well below one orbital's worth.
CHARACTER_LOSS = 0.50

# Per-loop caps. Separate, because they fail for different reasons and the
# right message differs.
MAX_RESEED = 2
MAX_AUGMENT = 2
MAX_PRUNE = 3

EV = 27.211386245988


@dataclass
class Rotation:
    """One orbital swap, recorded so a user can reproduce it by hand."""

    cycle: int
    action: str            # "reseed" | "augment" | "prune"
    mo_out: object = None  # 1-based index in the space it left, or None
    mo_in: object = None
    character: str = ""
    occupation: object = None
    why: str = ""

    def to_dict(self) -> dict:
        return {"cycle": self.cycle, "action": self.action,
                "orbital_removed": self.mo_out, "orbital_added": self.mo_in,
                "character": self.character,
                "natural_occupation": (None if self.occupation is None
                                       else round(float(self.occupation), 4)),
                "reason": self.why}


@dataclass
class RefineResult:
    n_electrons: int
    n_orbitals: int
    mo_coeff: object = None
    ncore: int = 0
    occupations: list = field(default_factory=list)
    energies_ev: list = field(default_factory=list)
    characters: list = field(default_factory=list)
    rotations: list = field(default_factory=list)
    cycles: int = 0
    converged: bool = False
    stopped_because: str = ""
    notes: list = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "refined_active_electrons": self.n_electrons,
            "refined_active_orbitals": self.n_orbitals,
            "natural_occupations": [round(float(x), 4) for x in self.occupations],
            "orbital_characters": list(self.characters),
            "excitation_energies_ev": [round(float(x), 3) for x in self.energies_ev],
            "rotations": [r.to_dict() for r in self.rotations],
            "cycles": self.cycles,
            "converged": self.converged,
            "stopped_because": self.stopped_because,
            "notes": list(self.notes),
        }


def subspace_target_weight(mol, block, targets) -> float:
    """How much of `targets` the span of `block` holds, in orbitals.

    The target set is orthonormalised first, so an over-complete set -- which
    every sigma set is -- does not inflate the answer. The result is a trace of
    a projector, so it counts orbitals' worth of character and is invariant to
    any rotation within `block`.
    """
    from pyscf import gto

    from app.chemistry.cas.projector import build_target_matrix

    if not targets or block.size == 0:
        return 0.0
    pmol = mol.copy()
    pmol.atom = mol._atom
    pmol.unit = "B"
    pmol.symmetry = False
    pmol.basis = "minao"
    pmol.build(False, False)

    T, _names = build_target_matrix(pmol, targets)
    if T.shape[1] == 0:
        return 0.0
    s_pp = pmol.intor_symmetric("int1e_ovlp")
    s_pc = gto.intor_cross("int1e_ovlp", pmol, mol)

    w, v = np.linalg.eigh(T.T @ s_pp @ T)
    keep = w > 1e-8
    if not keep.any():
        return 0.0
    X = T @ (v[:, keep] / np.sqrt(w[keep]))
    P = (X.T @ s_pc) @ block
    return float(np.trace(P @ P.T))


def state_averaged_occupations(mc):
    """Natural occupations of the state-averaged 1-RDM, descending.

    Averaged over every root the CASSCF was told to average, never the ground
    state alone: an orbital inert in S0 can be what carries S2, and pruning on
    a ground-state density is how an excited state gets thrown away.
    """
    dm = np.asarray(mc.fcisolver.make_rdm1(mc.ci, mc.ncas, mc.nelecas))
    occ, u = np.linalg.eigh(dm)
    order = np.argsort(occ)[::-1]
    return occ[order], u[:, order]


def audit_character(mol, start_block, end_block, pi_targets, lp_targets):
    """Did the chosen character survive the orbital optimisation?

    Returns ``(lost, detail)`` where `lost` is in orbitals. Positive means
    character left the active space.
    """
    before = (subspace_target_weight(mol, start_block, pi_targets)
              + subspace_target_weight(mol, start_block, lp_targets))
    after = (subspace_target_weight(mol, end_block, pi_targets)
             + subspace_target_weight(mol, end_block, lp_targets))
    detail = {
        "pi_before": round(subspace_target_weight(mol, start_block, pi_targets), 3),
        "pi_after": round(subspace_target_weight(mol, end_block, pi_targets), 3),
        "lone_pair_before": round(subspace_target_weight(mol, start_block, lp_targets), 3),
        "lone_pair_after": round(subspace_target_weight(mol, end_block, lp_targets), 3),
    }
    return before - after, detail


def prune_candidates(occ) -> list:
    """Indices of orbitals carrying no correlation, by natural occupation."""
    return [j for j, n in enumerate(occ)
            if n > INERT_OCCUPIED or n < INERT_VIRTUAL]


def reseed_lost_character(mol, mc, recommendation, pi_targets, lp_targets):
    """Rebuild a starting guess with the lost character rotated back in.

    This is the manual fix automated: keep the orbitals the CASSCF converged
    to, drop the ones that no longer carry the character they were chosen for,
    and put the geometry-projected orbitals back in their place. The result is
    a genuinely different starting point from the one the optimisation just
    walked away from -- restarting from the original projector orbitals is not,
    which is why the first implementation of this looped without progress.

    Returns ``(mo_coeff, caslst, swapped)``; `swapped` is how many orbitals were
    exchanged, and zero means there was nothing better to put in.
    """
    from app.chemistry.cas.excited import _target_weights

    ncore, ncas = mc.ncore, mc.ncas
    ovlp = mol.intor("int1e_ovlp")
    conv = mc.mo_coeff
    proj = np.asarray(recommendation.mo_coeff)
    p_lo, p_hi = recommendation.ncore, recommendation.ncore + len(
        recommendation.tiers[recommendation.recommended].orbital_indices)

    def char(v):
        return (_target_weights(mol, v, pi_targets).get("pi", 0.0)
                + _target_weights(mol, v, lp_targets).get("lone_pair", 0.0))

    keep, intruders = [], []
    for j in range(ncas):
        (keep if char(conv[:, ncore + j]) > 0.30 else intruders).append(ncore + j)
    if not intruders:
        return conv, list(range(ncore, ncore + ncas)), 0

    # Candidate replacements: projector orbitals with real character that the
    # surviving active block does not already span.
    block = conv[:, keep] if keep else np.zeros((conv.shape[0], 0))
    picks = []
    for c in range(p_lo, p_hi):
        v = proj[:, c].copy()
        if char(v) < 0.30:
            continue
        for blk in [block] + ([np.asarray(picks).T] if picks else []):
            if blk.size:
                v = v - blk @ (blk.T @ ovlp @ v)
        n = float(np.sqrt(max(v @ ovlp @ v, 0.0)))
        if n > 0.30:
            picks.append(v / n)
        if len(picks) == len(intruders):
            break
    if not picks:
        return conv, list(range(ncore, ncore + ncas)), 0

    active = np.hstack([block, np.asarray(picks).T]) if keep else np.asarray(picks).T
    # Symmetric orthonormalisation, so the block is a clean orbital set.
    w, u = np.linalg.eigh(active.T @ ovlp @ active)
    active = active @ (u @ np.diag(1.0 / np.sqrt(np.maximum(w, 1e-12))) @ u.T)

    rest = [c for c in range(conv.shape[1])
            if c < ncore or c >= ncore + ncas]
    mo = np.hstack([conv[:, [c for c in rest if c < ncore]], active,
                    conv[:, [c for c in rest if c >= ncore]]])
    return mo, list(range(ncore, ncore + active.shape[1])), len(picks)


def _solve(mf, mo, ncas, nelec, nroots, max_macro=150):
    """One SA-CASSCF, with the newton retry the legacy runner used.

    Non-convergence is a real case here -- uracil's six-root average does not
    converge in cc-pVDZ -- and it must stop the loop rather than feed an
    unconverged density into an occupation cut.
    """
    from pyscf import mcscf

    def _build():
        mc = mcscf.CASSCF(mf, ncas, nelec)
        mc.fcisolver.nroots = nroots
        if nroots > 1:
            mc.state_average_([1.0 / nroots] * nroots)
        mc.max_cycle_macro = max_macro
        mc.verbose = 0
        return mc

    mc = _build()
    mc.kernel(mo)
    if not mc.converged:
        try:
            mc2 = _build().newton()
            mc2.kernel(mo)
            if mc2.converged:
                return mc2
        except Exception:                                       # noqa: BLE001
            pass
    return mc


def _energies(mc):
    e = np.atleast_1d(np.asarray(getattr(mc, "e_states", mc.e_tot), dtype=float))
    return (e - e[0]) * EV


def _root_characters(mc, mol, pi_t, lp_t, rydberg_detectable=False):
    from app.chemistry.cas.excited import _label, _second_moments, _target_weights

    act = mc.mo_coeff[:, mc.ncore:mc.ncore + mc.ncas]
    r2 = _second_moments(mol, mc.mo_coeff[:, :mc.ncore + mc.ncas])
    extent = float(np.max(r2)) if r2.size else 1.0
    n = len(np.atleast_1d(np.asarray(getattr(mc, "e_states", mc.e_tot))))
    out = []
    for k in range(1, n):
        try:
            tdm = np.asarray(mc.fcisolver.trans_rdm1(mc.ci[0], mc.ci[k],
                                                     mc.ncas, mc.nelecas))
            u, _s, vt = np.linalg.svd(tdm)
            particle, hole = act @ u[:, 0], act @ vt[0, :]
            ratio = float(_second_moments(mol, particle[:, None])[0]) / extent
            hk = _label(_target_weights(mol, hole, pi_t + lp_t), 0.0, False,
                        rydberg_detectable)
            pk = _label(_target_weights(mol, particle, pi_t + lp_t), ratio, True,
                        rydberg_detectable)
            out.append(f"{hk}->{pk}")
        except Exception:                                       # noqa: BLE001
            out.append("unassigned")
    return out


def _prune_is_free(mc2, mol, pi_t, lp_t, predicted, ev_before):
    """Did the prune cost a state, or move one?

    Presence alone is too weak a test: a state can survive a smaller space and
    still shift half an electron-volt, which is not a free prune.
    """
    if not mc2.converged:
        return False, "the pruned space did not converge"
    chars = _root_characters(mc2, mol, pi_t, lp_t)
    lost = [p for p in predicted if p not in chars]
    if lost:
        return False, f"{', '.join(lost)} disappeared from the pruned space"
    ev_after = _energies(mc2)
    n = min(len(ev_before), len(ev_after))
    if n > 1:
        drift = float(np.max(np.abs(ev_after[1:n] - ev_before[1:n])))
        if drift > MAX_ENERGY_DRIFT_EV:
            return False, (f"an excitation energy moved {drift:.2f} eV, past the "
                           f"{MAX_ENERGY_DRIFT_EV} eV tolerance")
    return True, ""


def refine(mf, symbols, coords, recommendation, *, n_states: int = 1,
           analysis=None, predicted=None, start_tier: str = None,
           csf_budget: float = 1e8, max_cycles: int = 4, log=print):
    """Refine `recommendation` against SA-CASSCF evidence.

    `analysis` is the excited-state analysis from the quick recommendation, if
    there was one; it supplies the NTOs `augment` needs and the characters the
    state audit compares against.
    """
    from pyscf import mcscf

    from app.chemistry.cas import feasibility
    from app.chemistry.cas.excited import augment
    from app.chemistry.cas.geometry import perceive

    coords = np.asarray(coords, float)
    mol = mf.mol
    per = perceive(symbols, coords, include_sigma=False)
    pi_t = [t for t in per.targets if t.kind == "pi"]
    lp_t = [t for t in per.targets if t.kind == "lone_pair"]
    predicted = [p for p in (predicted or []) if p and "Rydberg" not in p]

    tiers = recommendation.tiers
    order = [start_tier] if start_tier else ["maximal", "recommended", "minimal"]
    chosen, why = None, ""
    for name in order:
        t = tiers.get(name)
        if t is None:
            continue
        if t.feasibility.n_csf and t.feasibility.n_csf <= csf_budget:
            chosen = name
            why = (f"the {name} tier, the largest under the "
                   f"{csf_budget:.0g}-CSF budget, at "
                   f"{t.feasibility.n_csf:,} CSFs")
            break
    if chosen is None:
        chosen = "recommended"
        why = ("no tier fits the CSF budget, so the recommended tier is used "
               "as the starting point")
    tier = tiers[chosen]
    log(f"[refine] starting from {why}")

    mo = np.asarray(recommendation.mo_coeff).copy()
    ncore = recommendation.ncore
    caslst = list(tier.orbital_indices)
    ncas, nelec = len(caslst), tier.n_electrons

    rotations, notes = [], []
    reseeds = augments = prunes = 0
    reseed_seen = []
    best = None
    stopped = "reached a fixed point: nothing further to correct or prune"
    cycle = 0

    for cycle in range(1, max_cycles + 1):
        f = feasibility.assess(ncas, nelec)
        log(f"[refine] cycle {cycle}: CAS({nelec},{ncas}), {f.n_csf:,} CSFs")
        start_block = mo[:, caslst].copy()
        seed = mcscf.sort_mo(mcscf.CASSCF(mf, ncas, nelec), mo,
                             [c + 1 for c in caslst], base=1)
        mc = _solve(mf, seed, ncas, nelec, max(1, n_states))
        if not mc.converged:
            stopped = ("the CASSCF did not converge, so the loop stopped rather "
                       "than prune on an unconverged density")
            log(f"[refine]   {stopped}")
            if best is None:
                best = (nelec, ncas, mc, list(caslst))
            break

        occ, u = state_averaged_occupations(mc)
        ev = _energies(mc)
        end_block = mc.mo_coeff[:, mc.ncore:mc.ncore + mc.ncas]
        best = (nelec, ncas, mc, list(caslst))

        lost, detail = audit_character(mol, start_block, end_block, pi_t, lp_t)
        chars = _root_characters(mc, mol, pi_t, lp_t)
        missing = [p for p in predicted if p not in chars]
        log(f"[refine]   character held: pi {detail['pi_before']}->"
            f"{detail['pi_after']}, lone pair {detail['lone_pair_before']}->"
            f"{detail['lone_pair_after']} (lost {lost:+.2f} orbitals' worth)")
        log(f"[refine]   states: {chars}"
            + (f"  MISSING {missing}" if missing else "  all predicted present"))

        intruders = sorted({c for c in chars if predicted and c not in predicted})
        if intruders:
            notes.append(
                f"Roots appeared that no linear-response state predicted "
                f"({', '.join(intruders)}). They contribute to the "
                f"state-averaged density the occupations are read from.")

        # Character loss only means something is wrong when a state went with
        # it. With every predicted state present, character leaving is the
        # optimisation handing back orbitals these states do not use -- which
        # is an argument for pruning, not for forcing them back.
        if missing and lost > CHARACTER_LOSS and reseeds < MAX_RESEED:
            new_mo, new_cas, swapped = reseed_lost_character(
                mol, mc, recommendation, pi_t, lp_t)
            if swapped:
                reseeds += 1
                rotations.append(Rotation(
                    cycle=cycle, action="reseed", character="pi/lone-pair",
                    why=(f"{', '.join(missing)} was absent and {lost:.2f} "
                         f"orbitals' worth of pi/lone-pair character had left "
                         f"the space; {swapped} orbital(s) were swapped back in "
                         f"from the geometry projection")))
                mo, caslst = new_mo, new_cas
                ncas = len(caslst)
                log(f"[refine]   swapped {swapped} orbital(s) back in; re-solving")
                continue
            notes.append(
                f"{', '.join(missing)} is absent and {lost:.2f} orbitals' worth "
                f"of character has left the space, but no orbital outside it "
                f"carries enough of that character to swap back in.")
        elif missing and analysis is not None and augments < MAX_AUGMENT:
            augments += 1
            new_mo, n_added, aug_notes = augment(mo, ncore, ncas, analysis,
                                                 mol, n_states)
            if n_added:
                notes.extend(aug_notes)
                for note in aug_notes:
                    rotations.append(Rotation(cycle=cycle, action="augment",
                                              why=note))
                mo = new_mo
                caslst = list(range(ncore, ncore + ncas + n_added))
                ncas += n_added
                log(f"[refine]   added {n_added} orbital(s) for "
                    f"{', '.join(missing)}; re-solving")
                continue
            notes.append(
                f"{', '.join(missing)} is absent and no orbital outside the "
                f"space carries enough of it to add.")
        elif lost > CHARACTER_LOSS:
            notes.append(
                f"{lost:.2f} orbitals' worth of pi/lone-pair character left the "
                f"active space, but every predicted state is still present. "
                f"That is the optimisation handing back orbitals these states "
                f"do not use, so they are pruned below rather than forced back.")

        cand = prune_candidates(occ)
        if not cand:
            stopped = "reached a fixed point: every orbital carries correlation"
            log(f"[refine]   {stopped}")
            break
        if prunes >= MAX_PRUNE:
            stopped = f"the prune limit of {MAX_PRUNE} was reached"
            log(f"[refine]   {stopped}")
            break

        keep = [j for j in range(ncas) if j not in cand]
        if not keep or not any(occ[j] > 0.5 for j in keep) \
                or not any(occ[j] < 1.5 for j in keep):
            stopped = ("pruning would leave no correlated pair, so the space is "
                       "left as it is")
            log(f"[refine]   {stopped}")
            break

        prunes += 1
        nat = mc.mo_coeff[:, mc.ncore:mc.ncore + mc.ncas] @ u
        trial_mo = np.hstack([mc.mo_coeff[:, :mc.ncore], nat[:, keep],
                              nat[:, cand],
                              mc.mo_coeff[:, mc.ncore + mc.ncas:]])
        trial_ncas = len(keep)
        trial_nelec = int(round(sum(occ[j] for j in keep)))
        trial_cas = list(range(mc.ncore, mc.ncore + trial_ncas))
        log(f"[refine]   pruning {len(cand)} inert orbital(s) -> "
            f"CAS({trial_nelec},{trial_ncas}); re-verifying")

        seed2 = mcscf.sort_mo(mcscf.CASSCF(mf, trial_ncas, trial_nelec),
                              trial_mo, [c + 1 for c in trial_cas], base=1)
        mc2 = _solve(mf, seed2, trial_ncas, trial_nelec, max(1, n_states))
        ok, reason = _prune_is_free(mc2, mol, pi_t, lp_t, predicted, ev)
        if not ok:
            stopped = f"the prune was rejected and undone: {reason}"
            log(f"[refine]   {stopped}")
            break

        for j in cand:
            rotations.append(Rotation(
                cycle=cycle, action="prune",
                mo_out=int(mc.ncore + j + 1), occupation=float(occ[j]),
                why=(f"state-averaged natural occupation {occ[j]:.3f} lies "
                     f"outside [{INERT_VIRTUAL}, {INERT_OCCUPIED}], so it "
                     f"carries no correlation for these states")))
        mo, ncore = trial_mo, mc.ncore
        caslst, ncas, nelec = trial_cas, trial_ncas, trial_nelec
        best = (nelec, ncas, mc2, list(caslst))
    else:
        stopped = f"the cycle limit of {max_cycles} was reached"

    nelec, ncas, mc, caslst = best
    occ, _u = state_averaged_occupations(mc)
    return RefineResult(
        n_electrons=nelec, n_orbitals=ncas,
        mo_coeff=mc.mo_coeff, ncore=mc.ncore,
        occupations=[float(x) for x in occ],
        energies_ev=[float(x) for x in _energies(mc)],
        characters=_root_characters(mc, mol, pi_t, lp_t),
        rotations=rotations, cycles=cycle, converged=bool(mc.converged),
        stopped_because=stopped, notes=notes,
    )
