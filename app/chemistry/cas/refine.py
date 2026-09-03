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
constraint, and it was found by measurement. On uracil in cc-pVDZ, asked for
three states, 4.27 orbitals' worth of lone-pair character leaves the active
space during the optimisation -- it holds 5.50 at the start and 1.27 at the end
-- and both carbonyl lone pairs converge to natural occupations of about 2.00.
They look perfectly inert. They are not: the n->pi* state built on them is
absent from the CASSCF roots entirely. Prune on occupation alone and both are
discarded, that state becomes unreachable, and the calculation appears to have
proved it was never needed.

Adding roots does not rescue them, which is worth stating because an earlier
reading of this suggested it did. A six-root average appeared to leave one lone
pair at 1.667, comfortably above any cut -- but that run had not converged. A
converged six-root average puts both back at about 2.00. The protective signal
is not the root count; it is the **state audit** noticing that a predicted
n->pi* is missing, which no occupation carries.

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

`audit_character` measures over the **subspace**, not per orbital, and the
reason is structural rather than empirical. A CASSCF may rotate arbitrarily
within its active space, so "the character of active orbital j" is not a well
defined quantity -- relabel the same space under such a rotation and the
per-orbital answers change while the space has not. A trace over the projection
onto the target set is invariant to exactly those rotations, which
`tests/backend/cas_10_refinement.py` checks directly by applying a random
unitary to the active block.

The sigma target set is also over-complete -- 44 targets for uracil, 55 for
o-nitrophenol -- so it spans most of the space and discriminates poorly.
(An earlier note here quoted a sigma weight of 0.98 on every converged pi
orbital. That number is not reproducible across orbital sets: about 0.98 on
state-averaged natural orbitals and about 0.00 on the canonical active ones.
The invariance argument above is the one that holds.)
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

# And a tolerance on the *absolute* ground-state energy, in hartree.
#
# Without it a ground-state-only request has no guard at all: the excitation
# check loops over the predicted states, and with none predicted it passes
# vacuously. N2 asked for one state pruned CAS(8e,7o) down to CAS(4e,4o) --
# three cuts, nothing to object -- which drops the sigma framework a triple
# bond needs. Pruning removes correlation, so the ground state can only rise;
# 5 mHartree is about 0.14 eV, the same scale as the excitation tolerance.
MAX_GROUND_STATE_RISE_HA = 5e-3

# Target weight, in orbitals, that may leave the active space before it counts
# as character having been lost. Chosen well below one orbital's worth.
CHARACTER_LOSS = 0.50

# Per-loop caps. Separate, because they fail for different reasons and the
# right message differs.
MAX_RESEED = 2
MAX_AUGMENT = 2
MAX_PRUNE = 3

# CSF ceiling for the space refinement will start from.
#
# Deliberately not generous. The loop runs several CASSCF solves, not one, so a
# budget sized for a single affordable calculation is the wrong scale. Measured
# on this host: every refinement that did useful work ran well under 10^6 CSFs
# (pyrrole 105, furan 105, uracil 41,405), while formaldehyde starting from its
# 13,860-CSF maximal tier took 65 times longer than starting from its
# recommended one and pruned nothing at all.
CSF_BUDGET = 1e6

# Extra roots to solve for beyond the number requested.
#
# A linear-response pass and a CASSCF do not order states the same way, and
# demanding that a state TDA put first appear among the lowest few CASSCF roots
# is not sound. Uracil is the case that showed it: TDA puts its n->pi* at S1,
# while the two lowest CASSCF excited roots of its recommended space are both
# pi->pi*, and the n->pi* only appears once about six roots are solved for.
# Without a margin the state audit reports it missing forever, re-seeds and
# augments chasing it, and never reaches the prune step at all -- which is
# exactly what the first run of this loop did.
ROOT_MARGIN = 3

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
    started_from: str = ""
    start_space: tuple = ()
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
            "started_from": self.started_from,
            "start_space": list(self.start_space),
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


def _narrow_to_states(mol, recommendation, tier, analysis, n_states,
                      pi_targets, lp_targets):
    """The pi system, plus whatever orbitals the requested states occupy.

    Used when no tier is affordable enough to solve several times. Keeping the
    whole pi system rather than only the state-occupied orbitals is deliberate:
    a pi space with a hole in it is not a space, and the completion rule that
    applies to the recommendation applies here too.

    Returns ``(caslst, n_electrons)``.
    """
    from app.chemistry.cas.excited import _target_weights

    mo = np.asarray(recommendation.mo_coeff)
    ncore = recommendation.ncore
    idx = list(tier.orbital_indices)
    n_docc = tier.n_electrons // 2
    ovlp = mol.intor("int1e_ovlp")

    keep = set()
    for k, col in enumerate(idx):
        v = mo[:, col]
        wpi = _target_weights(mol, v, pi_targets).get("pi", 0.0)
        wlp = _target_weights(mol, v, lp_targets).get("lone_pair", 0.0)
        if wpi > wlp:                       # the whole pi system goes in
            keep.add(k)

    if analysis is not None:
        for st in analysis.states[:max(n_states - 1, 0)]:
            i = st.index - 1
            for block in (analysis.hole_orbitals, analysis.particle_orbitals):
                if block is None or i >= block.shape[1]:
                    continue
                proj = np.abs(mo[:, idx].T @ ovlp @ block[:, i])
                keep.update(int(k) for k in np.where(proj > 0.30)[0])

    keep = sorted(keep) or list(range(len(idx)))
    caslst = [idx[k] for k in keep]
    nelec = 2 * sum(1 for k in keep if k < n_docc)
    return caslst, nelec


def reseed_lost_character(mol, mc, recommendation, pi_targets, lp_targets,
                          max_swap: float = 99):
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
    # Never put back more character than left. Without a cap the reseed is
    # greedy: on uracil it swapped four then five orbitals and overshot the
    # lone-pair weight to 6.97, more than the tier ever held.
    budget = min(len(intruders), max(1, int(round(max_swap))))

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
        if len(picks) == budget:
            break
    if not picks:
        return conv, list(range(ncore, ncore + ncas)), 0

    active = np.hstack([block, np.asarray(picks).T]) if keep else np.asarray(picks).T
    # Symmetric orthonormalisation, so the block is a clean orbital set.
    w, u = np.linalg.eigh(active.T @ ovlp @ active)
    active = active @ (u @ np.diag(1.0 / np.sqrt(np.maximum(w, 1e-12))) @ u.T)

    # Any intruder not replaced stays in the orbital set, moved to the virtual
    # block. Dropping it would return fewer columns than the basis has, and a
    # non-square orbital set is not a valid starting guess -- it is the sort of
    # thing sort_mo reindexes around silently rather than rejecting.
    unused = [c for c in intruders if len(picks) < len(intruders)][len(picks):]
    virt = [c for c in range(conv.shape[1]) if c >= ncore + ncas]
    mo = np.hstack([conv[:, :ncore], active, conv[:, unused + virt]])
    assert mo.shape[1] == conv.shape[1], (
        f"reseed produced {mo.shape[1]} orbitals from {conv.shape[1]}")
    return mo, list(range(ncore, ncore + active.shape[1])), len(picks)


def _as_nelec(nelec, spin_2s):
    """CASSCF wants (n_alpha, n_beta) once the molecule is open shell.

    A bare int is read as closed shell, so an odd or spin-polarised count
    passed as one silently describes a different system.
    """
    if not spin_2s:
        return int(nelec)
    n_beta = (int(nelec) - spin_2s) // 2
    return (int(nelec) - n_beta, n_beta)


def _solve(mf, mo, ncas, nelec, nroots, max_macro=50, conv_tol=1e-6):
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
        # A refinement starts from orbitals that are already close, and its
        # outputs are compared at the 0.01 eV scale, so the default 1e-7 buys
        # nothing here and costs macro-iterations.
        mc.conv_tol = conv_tol
        mc.verbose = 0
        return mc

    mc = _build()
    mc.kernel(mo)
    if mc.converged:
        return mc
    try:
        mc2 = _build().newton()
        mc2.kernel(mo)
    except Exception:                                           # noqa: BLE001
        return mc
    # Neither converged: keep whichever got lower, so the failure that gets
    # reported is the better of the two attempts rather than the first.
    if mc2.converged:
        return mc2
    e1 = float(np.min(np.atleast_1d(getattr(mc, "e_states", mc.e_tot))))
    e2 = float(np.min(np.atleast_1d(getattr(mc2, "e_states", mc2.e_tot))))
    return mc2 if e2 < e1 else mc


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


def _ground_energy(mc):
    return float(np.min(np.atleast_1d(
        np.asarray(getattr(mc, "e_states", mc.e_tot), dtype=float))))


def _prune_is_free(mc2, mol, pi_t, lp_t, predicted, ev_before_full,
                   chars_before, e_ground_before=None):
    """Did the prune cost a state, or move one, or cost correlation?

    Three tests, because each catches something the others do not. Presence
    alone is too weak: a state can survive a smaller space and still shift half
    an electron-volt. And both state tests are vacuous when nothing was
    predicted, which is every ground-state-only request -- so the absolute
    ground-state energy is checked too. Pruning removes correlation, so that
    energy can only rise, and how far it rises is the direct measure of what
    the cut cost.
    """
    if not mc2.converged:
        return False, "the pruned space did not converge"
    if e_ground_before is not None:
        rise = _ground_energy(mc2) - e_ground_before
        if rise > MAX_GROUND_STATE_RISE_HA:
            return False, (f"the ground state rose {rise * 1e3:.1f} mHartree "
                           f"({rise * 27.211386245988:.2f} eV), past the "
                           f"{MAX_GROUND_STATE_RISE_HA * 1e3:.0f} mHartree "
                           f"tolerance -- the orbitals were carrying "
                           f"correlation their occupations understated")
    chars = _root_characters(mc2, mol, pi_t, lp_t)
    lost = [p for p in predicted if p not in chars]
    if lost:
        return False, f"{', '.join(lost)} disappeared from the pruned space"
    # Compare matched states, not matched indices. A prune can reorder the
    # roots -- reordering is the whole uracil finding -- so an index-wise
    # comparison measures the shuffle rather than the shift.
    ev_after = _energies(mc2)
    for p in predicted:
        if p not in chars or p not in chars_before:
            continue
        a = ev_after[chars.index(p) + 1]
        b = ev_before_full[chars_before.index(p) + 1]
        if abs(a - b) > MAX_ENERGY_DRIFT_EV:
            return False, (f"{p} moved {abs(a - b):.2f} eV, past the "
                           f"{MAX_ENERGY_DRIFT_EV} eV tolerance")
    return True, ""


def refine(mf, symbols, coords, recommendation, *, n_states: int = 1,
           analysis=None, predicted=None, start_tier: str = None,
           spin_2s: int = 0,
           csf_budget: float = CSF_BUDGET, max_cycles: int = 4,
           log=print):
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
    order = [start_tier] if start_tier else ["recommended", "minimal"]
    chosen, why, narrowed = None, "", None
    for name in order:
        t = tiers.get(name)
        if t is None:
            continue
        if t.feasibility.n_csf and t.feasibility.n_csf <= csf_budget:
            chosen = name
            why = (f"the {name} tier, {t.feasibility.n_csf:,} CSFs, within the "
                   f"{csf_budget:.0g}-CSF budget")
            break
    if chosen is None:
        # Nothing fits. Narrow the recommended tier to its pi system plus the
        # orbitals the requested states actually occupy, rather than starting
        # from a space no loop can afford to solve several times. This is the
        # narrowing that made uracil and o-nitrophenol tractable by hand.
        base = tiers.get("recommended") or tiers.get("minimal")
        narrowed = _narrow_to_states(mol, recommendation, base, analysis,
                                     n_states, pi_t, lp_t)
        chosen = "narrowed"
        why = (f"no tier fits the {csf_budget:.0g}-CSF budget "
               f"(the smallest is {base.feasibility.n_csf:,}), so the "
               f"recommended tier was narrowed to its pi system plus the "
               f"orbitals the requested states occupy")
    log(f"[refine] starting from {why}")

    mo = np.asarray(recommendation.mo_coeff).copy()
    ncore = recommendation.ncore
    if narrowed is not None:
        caslst, nelec = narrowed
        tier = tiers.get("recommended") or tiers.get("minimal")
    else:
        tier = tiers[chosen]
        caslst = list(tier.orbital_indices)
        nelec = tier.n_electrons
    ncas = len(caslst)
    start_space = (nelec, ncas)

    rotations, notes = [], []
    if narrowed is not None:
        # The budget fallback changes the space before the first solve, so it
        # is a rotation like any other. Leaving it out of the trail was a real
        # gap: o-nitrophenol goes from (24e,18o) to (12e,10o) here and nowhere
        # else, and a trail that does not mention it cannot be replayed.
        rotations.append(Rotation(
            cycle=0, action="narrow",
            why=(f"the recommended space was "
                 f"{tiers['recommended'].feasibility.n_csf:,} CSFs, over the "
                 f"{csf_budget:.0g} budget for a loop that solves several "
                 f"times; narrowed at the start to the pi system plus the "
                 f"orbitals the requested states occupy")))
    reseeds = augments = prunes = 0
    narrowed_once = narrowed is not None
    reseed_seen = []
    best = None
    stopped = "reached a fixed point: nothing further to correct or prune"
    cycle = 0

    for cycle in range(1, max_cycles + 1):
        f = feasibility.assess(ncas, nelec, spin_2s)
        log(f"[refine] cycle {cycle}: CAS({nelec},{ncas}), {f.n_csf:,} CSFs")
        start_block = mo[:, caslst].copy()
        seed = mcscf.sort_mo(
            mcscf.CASSCF(mf, ncas, _as_nelec(nelec, spin_2s)), mo,
                             [c + 1 for c in caslst], base=1)
        # Never ask for more roots than the space can hold. Ethylene's
        # CAS(2e,2o) has three singlet CSFs, and asking it for five roots dies
        # inside the FCI solver with a broadcast error rather than a message.
        nroots = max(1, n_states) + (ROOT_MARGIN if n_states > 1 else 0)
        nroots = max(1, min(nroots, int(f.n_csf) if f.n_csf else 1))
        mc = _solve(mf, seed, ncas, _as_nelec(nelec, spin_2s), nroots)
        if not mc.converged:
            # Two different outcomes, and reporting them the same way is how a
            # user ends up trusting the wrong one. If an earlier cycle
            # converged, that space is what comes back and it *is* converged --
            # the loop merely stopped early. If none did, the result itself is
            # unconverged and has to say so.
            if best is not None:
                stopped = (
                    f"cycle {cycle} did not converge, so the loop stopped there "
                    f"rather than prune on an unconverged density. The space "
                    f"returned is from the last cycle that did converge.")
            else:
                stopped = ("the CASSCF did not converge, and no earlier cycle "
                           "did either, so this result is provisional")
                best = (nelec, ncas, mc, list(caslst))
            log(f"[refine]   {stopped}")
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
        where = {p: chars.index(p) + 1 for p in predicted if p in chars}
        log(f"[refine]   states: {chars}"
            + (f"  MISSING {missing}" if missing else "  all predicted present"))
        late = {p: r for p, r in where.items() if r >= max(1, n_states)}
        if late:
            note = ("The CASSCF orders these states higher than the "
                    "linear-response pass did: "
                    + ", ".join(f"{p} is root {r}" for p, r in late.items())
                    + f". Asking for {n_states} state(s) would not reach them; "
                      f"this refinement solved for {nroots}.")
            if note not in notes:
                notes.append(note)

        intruders = sorted({c for c in chars if predicted and c not in predicted})
        if intruders:
            notes.append(
                f"Roots appeared that no linear-response state predicted "
                f"({', '.join(intruders)}). They contribute to the "
                f"state-averaged density the occupations are read from.")

        # A missing state in a space carrying orbitals those states never touch
        # is a dilution problem, and narrowing is both cheaper and more likely
        # to work than re-seeding. Uracil is the case: its recommended space
        # holds all six lone-pair-derived orbitals, four of which no requested
        # state uses, and the n->pi* cannot be found among the roots at all --
        # a refinement from there ran 33 minutes across two cycles and returned
        # the space it started with. Narrowed to the pi system plus the
        # orbitals the states occupy, it is a fraction of the size and the
        # state is reachable. Tried once, before the re-seed loop.
        # The guard is only "have we already tried this". Comparing against the
        # minimal tier looks reasonable and is wrong: where minimal and
        # recommended are the same space -- uracil, furan -- it blocks the
        # narrowing entirely, which is precisely where it was needed. Whether
        # narrowing helps is decided below by whether it actually produces a
        # smaller space, which is the real question.
        if missing and not narrowed_once and analysis is not None:
            narrowed_once = True
            new_cas, new_nelec = _narrow_to_states(
                mol, recommendation, tier, analysis, n_states, pi_t, lp_t)
            if new_cas and len(new_cas) < ncas:
                rotations.append(Rotation(
                    cycle=cycle, action="narrow",
                    why=(f"{', '.join(missing)} was absent from a space of "
                         f"{ncas} orbitals; narrowed to the {len(new_cas)} that "
                         f"the pi system and the requested states actually use, "
                         f"since orbitals no state touches dilute the average "
                         f"the missing one has to be found in")))
                mo = np.asarray(recommendation.mo_coeff).copy()
                caslst, nelec, ncas = new_cas, new_nelec, len(new_cas)
                log(f"[refine]   narrowing to CAS({nelec},{ncas}) and re-solving")
                continue

        # Character loss only means something is wrong when a state went with
        # it. With every predicted state present, character leaving is the
        # optimisation handing back orbitals these states do not use -- which
        # is an argument for pruning, not for forcing them back.
        if missing and lost > CHARACTER_LOSS and reseeds < MAX_RESEED:
            new_mo, new_cas, swapped = reseed_lost_character(
                mol, mc, recommendation, pi_t, lp_t, max_swap=lost)
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

        seed2 = mcscf.sort_mo(
            mcscf.CASSCF(mf, trial_ncas, _as_nelec(trial_nelec, spin_2s)),
            trial_mo, [c + 1 for c in trial_cas], base=1)
        mc2 = _solve(mf, seed2, trial_ncas,
                     _as_nelec(trial_nelec, spin_2s), nroots)
        ok, reason = _prune_is_free(mc2, mol, pi_t, lp_t, predicted, ev,
                                    chars, e_ground_before=_ground_energy(mc))
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
        rotations=rotations, cycles=cycle,
        started_from=chosen, start_space=start_space,
        converged=bool(mc.converged),
        stopped_because=stopped, notes=notes,
    )
