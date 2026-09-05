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

# The state-narrowing moved to its own module because it needs no CASSCF: a
# geometry, a projection and the linear-response analysis are enough. It was
# reachable only from this loop while it lived here, so the quick
# recommendation could not use it and uracil's quick answer stayed at
# CAS(22e,14o) when the states it was asked about use ten orbitals.
from app.chemistry.cas.narrow import narrow_to_states as _narrow_to_states

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

# ...and no more than this fraction of the correlation energy the full space
# captured. The absolute tolerance above does not scale: 5 mHartree is noise on
# a large molecule and decisive on a small one, so a cut costing 4 mHartree out
# of 20 mHartree of total correlation passes it while destroying a fifth of
# what the space was for.
#
# Measured on the four ground-state-only molecules in the benchmark, this
# changes no verdict, which is the point of adding it -- it is insurance
# against the case the absolute test cannot see, not a re-tuning of the ones it
# handles. Water's cut costs 1.9 mHartree and 3.6% and is accepted; N2's costs
# 56 mHartree and 38%, methane's 81 mHartree and 100%, O2's 1025 mHartree, and
# all three are rejected on either test.
MAX_CORRELATION_LOSS = 0.10

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
#
# The budget is spent against ``n_csf * nroots``, not ``n_csf`` alone. A state
# average over R roots solves R CI problems per macro-iteration, so cost tracks
# the product, and testing the bare CSF count against a flat budget lets a
# large state average through as though it were a ground-state calculation.
#
# Measured: o-nitrophenol asked for five states narrowed to CAS(22e,15o) at
# 496,860 CSFs, which passes a flat 10^6 test comfortably. With eight roots
# (five requested plus ROOT_MARGIN) one cycle took about two hours, putting a
# four-cycle refinement past eight -- against a benchmark cap of ten minutes.
# Uracil at 41,405 CSFs over six roots runs a cycle in minutes. The product
# separates those two where the bare count does not: 3.97M against 248k.

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
    characters: list = field(default_factory=list)   # per excited root
    orbital_labels: list = field(default_factory=list)   # per active orbital
    orbital_weights: list = field(default_factory=list)  # per active orbital
    # The full orbital set with the ACTIVE BLOCK replaced by the
    # state-averaged natural orbitals -- the basis `occupations`,
    # `orbital_labels` and `orbital_weights` are all expressed in.
    # `mo_coeff` is deliberately kept separate and unrotated, because
    # that is what a production CASSCF restarts from; the two are
    # different orbital sets spanning the same space, and pairing a
    # reported occupation with the wrong one is an easy mistake to
    # make from the outside.
    natural_orbitals: object = None
    rotations: list = field(default_factory=list)
    cycles: int = 0
    started_from: str = ""
    start_space: tuple = ()
    converged: bool = False
    stopped_because: str = ""
    notes: list = field(default_factory=list)
    # How many roots the state average actually solved for, which is NOT the
    # number of states requested: it carries ROOT_MARGIN extras so a state a
    # linear-response pass puts at S1 can still be found when the CASSCF puts
    # it at root 3, and it is clamped down when the space holds fewer CSFs than
    # that. A refined space is a function of this number -- uracil's lone-pair
    # occupations fall from [1.981, 1.954] at four roots to [1.976, 1.936] at
    # six, which changes what the prune takes -- so a result that does not
    # record it cannot be compared against another one or against a reference.
    n_roots_solved: int = 0
    # False when the CSF solver could not be imported and the state average ran
    # spin-contaminated. This used to be swallowed in silence on the reasoning
    # that a contaminated answer beats no answer. It may, but not silently:
    # section 6.3 of the method document shows that a triplet's transition
    # density from a singlet ground state is zero by spin, so every character
    # built from one is noise, and characters are what the state audit and
    # every reported label rest on.
    spin_adapted: bool = True
    # Predicted states this refinement deliberately did not look for, because
    # they are Rydberg and a valence space is not meant to hold them. They were
    # always filtered out of the audit, which is correct and is what stops the
    # loop chasing a state it can never reach, but filtering them in silence
    # made "all predicted present" ambiguous: it could mean the space describes
    # everything asked about, or that the one state that mattered was quietly
    # dropped before anything was checked. A state correctly absent by design
    # and a valence state genuinely lost are different outcomes and now read
    # differently.
    rydberg_excluded: list = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "refined_active_electrons": self.n_electrons,
            "refined_active_orbitals": self.n_orbitals,
            "natural_occupations": [round(float(x), 4) for x in self.occupations],
            # Renamed from "orbital_characters", which is what these
            # were published as for one release. They are one label per
            # excited ROOT and sat directly above natural_occupations,
            # which is one number per ORBITAL -- different lengths and
            # different meanings, inviting anyone to zip them.
            "state_characters": list(self.characters),
            "orbital_characters": list(self.orbital_labels),
            "active_space_composition": composition(self.orbital_labels),
            # Published alongside the labels, never instead of them: the
            # reference sets are over-complete and non-orthogonal, so a
            # label can turn on a margin of a few hundredths.
            "orbital_character_weights": list(self.orbital_weights),
            "excitation_energies_ev": [round(float(x), 3) for x in self.energies_ev],
            "rotations": [r.to_dict() for r in self.rotations],
            "cycles": self.cycles,
            "started_from": self.started_from,
            "start_space": list(self.start_space),
            "converged": self.converged,
            "stopped_because": self.stopped_because,
            "n_roots_solved": self.n_roots_solved,
            "spin_adapted": self.spin_adapted,
            "states_not_looked_for": list(self.rydberg_excluded),
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


def characters_compatible(root_char: str, want: str) -> bool:
    """Could `root_char` be the state `want` describes?

    Exact equality is too strict, because "mixed" on either side of the arrow
    is not a character -- it is the classifier saying it could not decide. A
    hole whose pi weight fell just under the 0.30 floor comes back
    "mixed->pi*", and treating that as evidence AGAINST pi->pi* is treating
    absence of evidence as evidence of absence.

    That is not hypothetical. Acrolein's root 4 was labelled pi->pi* and
    matched its 6.68 eV reference to within 0.35 eV. After the lone-pair
    targets changed, the same root came back "mixed->pi*", stopped being a
    candidate, and the reference matched instead to root 2 -- a genuine
    pi->pi* three electronvolts lower. One state, and it moved the benchmark's
    whole SC-NEVPT2 mean absolute error from 0.29 eV to 0.43 eV.

    So "mixed" matches anything on the side it appears, and the caller is
    expected to prefer an exact match where one exists.
    """
    if root_char == want:
        return True
    rh, _sep, rp = root_char.partition("->")
    wh, _sep2, wp = want.partition("->")
    if not _sep or not _sep2:
        return False
    return ((rh == wh or "mixed" in (rh, wh))
            and (rp == wp or "mixed" in (rp, wp)))


def _natural_orbital_set(mc, u):
    """`mc.mo_coeff` with the active block rotated into natural orbitals.

    Core and virtual columns are untouched, so the result is a complete orbital
    set that can be written to a molden and read alongside the occupations.
    """
    mo = np.array(mc.mo_coeff, copy=True)
    act = slice(mc.ncore, mc.ncore + mc.ncas)
    mo[:, act] = mo[:, act] @ u
    return mo


def occupation_vector(mc, occ):
    """Occupations for every column of the full orbital set: 2 / n_i / 0."""
    full = np.zeros(mc.mo_coeff.shape[1])
    full[:mc.ncore] = 2.0
    full[mc.ncore:mc.ncore + mc.ncas] = np.asarray(occ, float)
    return full


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



def reseed_lost_character(mol, mc, recommendation, pi_targets, lp_targets,
                          max_swap: float = 99, nelec=None, spin_2s: int = 0):
    """Rebuild a starting guess with the lost character rotated back in.

    This is the manual fix automated: keep the orbitals the CASSCF converged
    to, drop the ones that no longer carry the character they were chosen for,
    and put the geometry-projected orbitals back in their place. The result is
    a genuinely different starting point from the one the optimisation just
    walked away from -- restarting from the original projector orbitals is not,
    which is why the first implementation of this looped without progress.

    Returns ``(mo_coeff, caslst, swapped, nelec)``; `swapped` is how many
    orbitals were exchanged, and zero means there was nothing better to put in.

    `nelec` is RECOMPUTED rather than carried through, and that is the point of
    it. Swapping an acceptor in for a donor changes how many of the active
    orbitals are occupied, and the electron count has to follow or the space
    silently keeps the old occupied/virtual split. On uracil at three states
    that is the difference between the 7 occupied + 2 virtual this loop used to
    return -- only two pi* acceptors, too few to host two pi->pi* states and an
    n->pi* at once -- and the 6 + 3 the literature space uses. The orbitals were
    never the whole problem; the balance was.

    Only closed-shell spaces are rebalanced. For an open shell the donor count
    no longer fixes the electron count on its own, and getting that wrong is
    worse than leaving it alone, so the caller's `nelec` is returned unchanged.
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
        return conv, list(range(ncore, ncore + ncas)), 0, nelec
    # Never put back more character than left. Without a cap the reseed is
    # greedy: on uracil it swapped four then five orbitals and overshot the
    # lone-pair weight to 6.97, more than the tier ever held.
    budget = min(len(intruders), max(1, int(round(max_swap))))

    # Candidate replacements: projector orbitals with real character that the
    # surviving active block does not already span.
    block = conv[:, keep] if keep else np.zeros((conv.shape[0], 0))
    # Which of the recommendation's active orbitals were occupied. The
    # projector returns its active block occupied-first, so the split is an
    # index, and it is what says whether a pick is a donor or an acceptor.
    rec_occ = int(recommendation.space[0]) // 2
    picks, pick_is_donor = [], []
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
            pick_is_donor.append((c - p_lo) < rec_occ)
        if len(picks) == budget:
            break
    if not picks:
        return conv, list(range(ncore, ncore + ncas)), 0, nelec

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

    # Rebalance. A kept orbital is a donor if the state-averaged density says
    # it is occupied; a pick is a donor if it came from the projector's
    # occupied block. Reading the kept ones off the RDM diagonal works in mc's
    # own active basis, so it needs no natural-orbital rotation.
    new_nelec = nelec
    if spin_2s == 0:
        try:
            dm = np.asarray(mc.fcisolver.make_rdm1(mc.ci, mc.ncas, mc.nelecas))
            diag = np.diag(dm)
            kept = [float(diag[c - ncore]) for c in keep]
            # Only rebalance when every kept orbital is UNAMBIGUOUSLY a donor
            # or an acceptor. A bare "> 1.0" test was safe under the old
            # spin-contaminated solver, where averaging over triplets left
            # singly-occupied orbitals around 1.5 to 1.8; confined to singlets
            # a pi orbital carrying a strong pi->pi* sits much lower --
            # o-nitrophenol's converged CAS(12e,9o) has one at 1.597 and a pi*
            # at 0.749. An orbital drifting under 1.0 would flip from donor to
            # acceptor, drop the count by two electrons, and hand the next
            # cycle an electron count that does not describe the space.
            #
            # Refusing to rebalance is the safe failure: the space keeps the
            # electron count it had, which is what happened before this existed.
            ambiguous = [x for x in kept if 0.8 <= x <= 1.2]
            if ambiguous:
                new_nelec = nelec
            else:
                donors = sum(1 for x in kept if x > 1.2)
                donors += sum(1 for d in pick_is_donor if d)
                if donors > 0:
                    new_nelec = 2 * donors
        except Exception:                                       # noqa: BLE001
            new_nelec = nelec
    return (mo, list(range(ncore, ncore + active.shape[1])), len(picks),
            new_nelec)


def _as_nelec(nelec, spin_2s):
    """CASSCF wants (n_alpha, n_beta) once the molecule is open shell.

    A bare int is read as closed shell, so an odd or spin-polarised count
    passed as one silently describes a different system.
    """
    if not spin_2s:
        return int(nelec)
    n_beta = (int(nelec) - spin_2s) // 2
    return (int(nelec) - n_beta, n_beta)


def _spin_adapt(mc, mol) -> bool:
    """Restrict the CI space to the declared multiplicity.

    Mirrors `pyscf_runner._apply_spin_constraint`. A CSF solver rather than
    `fix_spin_`, because the penalty route leaks into the stored MCSCF
    energies; see that function for the full account.

    **Returns whether the constraint was actually applied**, and the caller is
    expected to record it. This used to fall back in silence, on the reasoning
    that a spin-contaminated answer is still better than no recommendation at
    all. That may be true, but silence is not: section 6.3 of the method
    document is the account of what an unconstrained state average does here,
    and it is not a degradation in accuracy. PySCF's plain solver returns the
    lowest roots of any multiplicity, a triplet's one-particle transition
    density from a singlet ground state is zero by spin, so every natural
    transition orbital built from one is numerical noise and the character
    assigned to it means nothing. Characters are what the state audit branches
    on and what every reported label is. A result computed that way is not a
    worse answer to the same question, it is an answer to a different one, and
    it has to say so on its face.
    """
    try:
        from pyscf.csf_fci import csf_solver
        mc.fcisolver = csf_solver(mol, smult=mol.spin + 1)
        return True
    except Exception:                                           # noqa: BLE001
        return False


def _solve(mf, mo, ncas, nelec, nroots, max_macro=100, conv_tol=1e-8,
           conv_tol_grad=1e-5):
    """One SA-CASSCF, with the newton retry the legacy runner used.

    Non-convergence is a real case here -- uracil's six-root average does not
    converge in cc-pVDZ -- and it must stop the loop rather than feed an
    unconverged density into an occupation cut.

    A spin-adapted CI space, for the reason `pyscf_runner._apply_spin_constraint`
    already documents for production jobs: PySCF's plain FCI solver returns the
    lowest roots of ANY multiplicity, so a state average over five roots of a
    closed-shell molecule can be three triplets and two singlets. Measured on
    o-nitrophenol's CAS(12e,9o) at five roots, <S^2> came back
    [0.000, 2.000, 2.000, 2.000, 0.000] -- roots 1 to 3 are triplets.

    That is not a cosmetic problem for this module. A triplet's one-particle
    transition density from the singlet ground state is zero by spin, so every
    NTO built from it is numerical noise and the character it is given is
    meaningless; o-nitrophenol's two n->pi* singlets were reported as pi->pi*
    on exactly that basis. It is also why states kept coming back "missing":
    the singlet a user asked about was pushed out of the requested root count
    by triplets nobody asked for.

    The production runner has used a CSF solver since the overhaul and this
    engine did not, so the engine was recommending and verifying against a
    different wavefunction from the one the job would actually run.
    """
    from pyscf import mcscf

    def _build():
        mc = mcscf.CASSCF(mf, ncas, nelec)
        # Carried on the object rather than returned, because `_solve` may hand
        # back either of two attempts and the flag has to travel with whichever
        # one wins.
        mc._nexusqc_spin_adapted = _spin_adapt(mc, mf.mol)
        mc.fcisolver.nroots = nroots
        if nroots > 1:
            mc.state_average_([1.0 / nroots] * nroots)
        mc.max_cycle_macro = max_macro
        # These tolerances are what make the refinement reproducible, and the
        # looser ones they replace are what made it not.
        #
        # This block used to read 1e-6 with no gradient tolerance at all, on
        # the argument that a refinement starts from orbitals that are already
        # close and compares its outputs at the 0.01 eV scale, so a tighter
        # convergence bought nothing and cost macro-iterations. Both halves of
        # that were measured and both are wrong.
        #
        # `scripts/casbench/repeat_scatter.py` runs the same acrolein
        # SA-CASSCF five times. At 1e-6 / 1e-4 / 50 macro-iterations on eight
        # BLAS threads the ground-state energy moves 36 meV between identical
        # runs, root 4 moves 0.275 eV and root 5 moves 0.459 eV, and the
        # CHARACTER of both roots changes from run to run: root 5 comes back
        # pi->pi* in some trials and mixed->pi* in others. That is 45 times the
        # 0.01 eV scale the old comment claimed to be working at, and a moving
        # character is not a tolerance question at all, because the state audit
        # this whole loop is built around compares characters. PySCF reports
        # `converged = True` on all five of those runs, so convergence at 1e-6
        # is not evidence of reproducibility.
        #
        # The mechanism is threading, not chemistry: the identical loose
        # protocol pinned to one BLAS thread reproduces exactly, so the run to
        # run difference is reduction order in the linear algebra, and a loose
        # tolerance is what lets that perturbation survive into the answer
        # instead of being squeezed out. Pinning threads would also fix it and
        # is the wrong fix, since it costs a factor of three in wall time.
        #
        # What tightening costs depends on the size of the system, and quoting
        # only the small case would misrepresent it. On acrolein it is not
        # measurable: over five repeats each, 4.1 s mean here against 3.3 s
        # median at the loose settings on the same eight threads, with the
        # loose arm throwing a 15.7 s outlier of its own. On uracil it is real,
        # going from a recorded 154 s to 282 s on the run that converges and to
        # 926 s and 974 s on the two that do not, because missing the criterion
        # inside `max_macro` also buys a second attempt through the Newton
        # solver below. Uracil converged once in three tries and now sits at
        # the edge of this budget.
        #
        # It is still the right trade, because what it buys is not accuracy in
        # the abstract: uracil's refined space used to come back as two
        # different active spaces across three identical runs and now comes
        # back as one. But it is a trade, and raising `max_macro` for the large
        # cases is the obvious follow-up, wanting measurement rather than
        # assumption.
        mc.conv_tol = conv_tol
        mc.conv_tol_grad = conv_tol_grad
        mc.verbose = 0
        return mc

    mc = _build()
    mc.kernel(mo)
    if mc.converged:
        return mc
    try:
        base = _build()
        mc2 = base.newton()
        # The newton wrapper is a different object, so the flag has to be
        # carried across explicitly or it reads as the default on the retry.
        mc2._nexusqc_spin_adapted = base._nexusqc_spin_adapted
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


# A lone pair only has to reach this to beat sigma, even when the sigma weight
# is the larger of the two. The sets are not symmetric: uracil emits 44 sigma
# targets against 6 lone-pair ones, so sigma spans more of any orbital simply by
# being a bigger set, and an argmax between them is biased before the chemistry
# is considered. It is also physically right -- a carbonyl lone pair is an sp
# hybrid, so real overlap with the sigma frame is expected rather than
# disqualifying. Measured on uracil's canonical occupied orbitals, four of them
# score n ~ 0.92 and sigma ~ 0.98 at once, and a plain argmax calls all four
# sigma on a margin of about 0.06.
LONE_PAIR_OVER_SIGMA = 0.50
# Below that but still substantial, with sigma also high, the honest answer is
# that the orbital is both and no threshold separates them. Uracil's second
# carbonyl lone pair lands here (n 0.33, sigma 0.97). Reporting it as "sigma"
# would be a decision the numbers do not support, and reporting it as "n" would
# be the same error in the other direction.
LONE_PAIR_AMBIGUOUS = 0.25
SIGMA_PRESENT = 0.50


def orbital_characters(mol, block, occupations, pi_t, lp_t, sigma_t=()):
    """Per-orbital character for the orbitals the result actually reports.

    Returns ``(labels, weights)`` -- one label and one ``{kind: weight}`` dict
    per column of `block`. Both are returned because the label alone is not
    trustworthy enough to be the only thing published: pi, n and sigma reference
    sets are each over-complete and mutually non-orthogonal, so the weights do
    not sum to one and a single winner can be decided by a margin far smaller
    than the uncertainty in what the labels mean.

    This is a REPORT, not a criterion, and keeping that distinction straight is
    the reason the audits in this module measure a subspace trace instead (see
    `subspace_target_weight`). A per-orbital label is not invariant to a
    rotation within the active space, so it can never decide whether an orbital
    stays or goes. But `block` here is one specific, named set -- the
    state-averaged natural orbitals the run converged to, which the occupation
    ordering fixes uniquely up to degeneracies -- and for that set the label is
    well defined. It is also the thing a user needs in order to rebuild the
    space by hand, which a bare ``(14, 9)`` does not tell them.

    Occupation, not column index, decides whether an orbital is labelled as a
    donor or an acceptor: in a natural-orbital basis there is no core/virtual
    split to read the answer off.

    `sigma_t` matters and should be passed. Without it sigma is not a candidate,
    so a sigma orbital cannot be named as one and is handed to whichever of pi
    or lone pair scores higher on it -- which is how uracil's one sigma orbital
    came to be reported as `pi*` on a pi weight of 0.003.
    """
    from app.chemistry.cas.excited import CHARACTER_WEIGHT, _target_weights

    targets = list(pi_t) + list(lp_t) + list(sigma_t)
    labels, weights = [], []
    for j in range(block.shape[1]):
        occ_j = float(occupations[j]) if j < len(occupations) else 0.0
        star = "*" if occ_j < 1.0 else ""
        try:
            w = _target_weights(mol, block[:, j], targets)
        except Exception:                                       # noqa: BLE001
            labels.append("unassigned")
            weights.append({})
            continue
        weights.append({k: round(float(v), 4) for k, v in w.items()})
        lp_w = float(w.get("lone_pair", 0.0))
        sig_w = float(w.get("sigma", 0.0))
        kind, top = (max(w.items(), key=lambda kv: kv[1]) if w
                     else ("mixed", 0.0))
        if lp_w >= LONE_PAIR_OVER_SIGMA and kind == "sigma":
            kind, top = "lone_pair", lp_w
        elif (kind == "sigma" and sig_w >= SIGMA_PRESENT
              and lp_w >= LONE_PAIR_AMBIGUOUS):
            # Say it is both rather than picking. The weights are published
            # next to this, so the reader can make the call the engine cannot.
            labels.append(f"n/sigma{star}")
            continue
        if top < CHARACTER_WEIGHT:
            labels.append("mixed")
            continue
        labels.append({"pi": f"pi{star}",
                       "lone_pair": "n" if not star else "n*",
                       "sigma": f"sigma{star}",
                       "metal_d": "d"}.get(kind, "mixed"))
    return labels, weights


def composition(labels) -> str:
    """``["pi","pi","n","pi*"]`` -> ``"2 pi, 1 n, 1 pi*"``.

    Ordered donors-before-acceptors rather than by count, so the string reads
    the way a chemist would write the space.
    """
    order = ["pi", "n", "n/sigma", "sigma", "d", "pi*", "n*", "n/sigma*",
             "sigma*", "mixed", "unassigned"]
    seen = {}
    for lab in labels:
        seen[lab] = seen.get(lab, 0) + 1
    parts = [f"{seen[k]} {k}" for k in order if k in seen]
    parts += [f"{v} {k}" for k, v in seen.items() if k not in order]
    return ", ".join(parts)


def _ground_energy(mc):
    return float(np.min(np.atleast_1d(
        np.asarray(getattr(mc, "e_states", mc.e_tot), dtype=float))))


def _prune_is_free(mc2, mol, pi_t, lp_t, predicted, ev_before_full,
                   chars_before, e_ground_before=None, e_reference=None):
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
        # The same question asked scale-free: what fraction of the correlation
        # the full space captured did the cut throw away?
        if e_reference is not None:
            corr_full = e_ground_before - e_reference
            if corr_full < 0:                       # correlation lowers it
                lost = rise / abs(corr_full)
                if lost > MAX_CORRELATION_LOSS:
                    return False, (
                        f"the cut cost {lost * 100:.1f}% of the correlation "
                        f"energy the full space captured "
                        f"({rise * 1e3:.1f} of {abs(corr_full) * 1e3:.1f} "
                        f"mHartree), past the "
                        f"{MAX_CORRELATION_LOSS * 100:.0f}% tolerance")
    chars = _root_characters(mc2, mol, pi_t, lp_t)
    # A prune costs a state only when the space HAD that state and now does
    # not. This used to test the pruned space alone, so a predicted state the
    # space could not describe in the first place was counted as lost by every
    # prune, forever, and the loop stopped one cycle early asserting a causal
    # claim it had not checked. Found in uracil's own output: it reported
    # "n->pi* disappeared from the pruned space" on a run whose five reported
    # root characters were all pi->pi*, so there was no n->pi* to lose.
    # `chars_before` was already being passed in and already used for the
    # energy-drift test below; it simply was not consulted here.
    #
    # A state absent both before and after is a real problem, but a different
    # one, and it belongs to the state audit in the main loop rather than to
    # the prune guard. Blocking the prune does not recover it.
    had_before = [p for p in predicted
                  if any(characters_compatible(c, p) for c in chars_before)]
    lost = [p for p in had_before
            if not any(characters_compatible(c, p) for c in chars)]
    if lost:
        return False, (f"{', '.join(lost)} was in the space before the prune "
                       f"and is not after")
    # Compare matched states, not matched indices. A prune can reorder the
    # roots -- reordering is the whole uracil finding -- so an index-wise
    # comparison measures the shuffle rather than the shift.
    ev_after = _energies(mc2)
    for p in predicted:
        if (not any(characters_compatible(c, p) for c in chars)
                or not any(characters_compatible(c, p) for c in chars_before)):
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
    # Sigma targets are perceived separately and are used ONLY to report what
    # the final orbitals are. They are deliberately absent from `per`, whose
    # targets drive the re-seed, because a sigma orbital is never something
    # this loop rotates IN -- but without them in the labelling, a sigma
    # orbital that rotated in on its own cannot be named and gets reported as
    # whichever of pi or lone pair happens to score higher on it.
    sig_t = [t for t in perceive(symbols, coords).targets if t.kind == "sigma"]
    # A predicted Rydberg state is dropped from the audit rather than chased.
    # The loop's response to a missing state is to reseed and then to augment,
    # and augment skips Rydberg particles by design, so leaving one in the list
    # would have the loop pursue a state it can never reach until it runs out
    # of cycles. Keep the names, though: "correctly not looked for" and
    # "looked for and lost" are different results and the caller is told which.
    rydberg_excluded = [p for p in (predicted or []) if p and "Rydberg" in p]
    predicted = [p for p in (predicted or []) if p and "Rydberg" not in p]
    if rydberg_excluded:
        log(f"[refine] not looking for {', '.join(rydberg_excluded)}: a "
            f"Rydberg state needs diffuse orbitals a valence space is not "
            f"meant to carry, so its absence here is by design and is not "
            f"evidence the space is wrong")

    tiers = recommendation.tiers
    order = [start_tier] if start_tier else ["recommended", "minimal"]
    chosen, why, narrowed = None, "", None
    # How many roots each solve will carry, which is what the budget is spent
    # against alongside the CSF count.
    expected_roots = max(1, n_states) + (ROOT_MARGIN if n_states > 1 else 0)
    for name in order:
        t = tiers.get(name)
        if t is None:
            continue
        if (t.feasibility.n_csf
                and t.feasibility.n_csf * expected_roots <= csf_budget):
            chosen = name
            why = (f"the {name} tier, {t.feasibility.n_csf:,} CSFs over "
                   f"{expected_roots} roots, within the "
                   f"{csf_budget:.0g}-CSF budget")
            break
    # Narrowing is not only a fallback for spaces that do not fit. A quick
    # recommendation admits every lone-pair-derived orbital in the molecule --
    # six for uracil, six for o-nitrophenol, one from every nitrogen and oxygen
    # -- because it cannot know which of them a state will use. Once the states
    # have been asked for, that is knowable, and carrying four lone pairs no
    # state touches makes the loop slower without making the answer better.
    #
    # The trim is taken from the recommendation when it published one, and
    # computed here only when it did not -- a library caller, or a
    # ground-state-only request that never had states to narrow against. On
    # uracil the trim is the difference between the pool and CAS(14e,10o), the
    # space the multireference literature uses for this molecule.
    #
    # It is not applied to a ground-state-only request: with no state to name
    # the participating heteroatoms, there is nothing to trim against and the
    # correlated valence space is the right answer.
    base = tiers.get("recommended") or tiers.get("minimal")
    published = tiers.get("state-narrowed")
    if published is not None and base is not None:
        # The recommendation already narrowed, and this loop is not entitled to
        # a second opinion about it. Until 2026-09-04 it computed its own from
        # its own TDA analysis in its own basis, with `nroots=expected_roots`
        # against the recommendation's `n_states` and a finite budget against
        # its infinite one, so a refinement could start from a space the user
        # was never shown. `narrowing_agreement.py` measured 34 molecules and
        # found the two agree everywhere, which is what makes deferring to the
        # published tier a simplification rather than a behaviour change.
        narrowed = (list(published.orbital_indices), published.n_electrons)
        chosen = "narrowed"
        why = (f"CAS({published.n_electrons},{published.n_orbitals}), the "
               f"space the recommendation narrowed to for the requested "
               f"states")
    elif base is not None and analysis is not None and n_states > 1:
        trial_cas, trial_ne = _narrow_to_states(
            mol, recommendation, base, analysis, n_states, pi_t, lp_t,
            nroots=expected_roots, csf_budget=csf_budget, perception=per)
        if trial_cas and len(trial_cas) < len(base.orbital_indices):
            was = (f"the {chosen} tier" if chosen else
                   f"CAS({base.n_electrons},{len(base.orbital_indices)})")
            narrowed = (trial_cas, trial_ne)
            chosen = "narrowed"
            why = (f"CAS({trial_ne},{len(trial_cas)}), the pi system plus one "
                   f"lone pair per heteroatom the requested states are built "
                   f"on, narrowed from {was} "
                   f"({len(base.orbital_indices)} orbitals) because the extra "
                   f"lone pairs no requested state touches cost time without "
                   f"changing the answer")

    if chosen is None:
        # Nothing fits and there was nothing to narrow against.
        narrowed = _narrow_to_states(mol, recommendation, base, analysis,
                                     n_states, pi_t, lp_t,
                                     nroots=expected_roots,
                                     csf_budget=csf_budget, perception=per)
        chosen = "narrowed"
        why = (f"no tier fits the {csf_budget:.0g}-CSF budget over "
               f"{expected_roots} roots (the smallest is "
               f"{base.feasibility.n_csf:,} CSFs, "
               f"{base.feasibility.n_csf * expected_roots:,} root-CSFs), so the "
               f"recommended tier was narrowed to its pi system plus the "
               f"lone pairs the requested states are built on")
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
    if rydberg_excluded:
        notes.append(
            f"{', '.join(rydberg_excluded)} was predicted but deliberately "
            f"not looked for. A Rydberg state lives in diffuse orbitals that a "
            f"valence active space does not carry, so its absence from the "
            f"roots below is by design rather than a gap in the space. "
            f"Describing it needs a space built to include diffuse orbitals, "
            f"which is a different request from this one.")
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
    reseeds = augments = prunes = nroots = 0
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
        missing = [p for p in predicted
                   if not any(characters_compatible(c, p) for c in chars)]
        log(f"[refine]   character held: pi {detail['pi_before']}->"
            f"{detail['pi_after']}, lone pair {detail['lone_pair_before']}->"
            f"{detail['lone_pair_after']} (lost {lost:+.2f} orbitals' worth)")
        where = {p: next(i + 1 for i, c in enumerate(chars)
                         if characters_compatible(c, p))
                 for p in predicted
                 if any(characters_compatible(c, p) for c in chars)}
        log(f"[refine]   states: {chars}"
            + (f"  MISSING {missing}" if missing
               else "  all predicted present"
                    + (f" (not counting {', '.join(rydberg_excluded)}, "
                       f"deliberately not looked for)"
                       if rydberg_excluded else "")))
        late = {p: r for p, r in where.items() if r >= max(1, n_states)}
        if late:
            note = ("The CASSCF orders these states higher than the "
                    "linear-response pass did: "
                    + ", ".join(f"{p} is root {r}" for p, r in late.items())
                    + f". Asking for {n_states} state(s) would not reach them; "
                      f"this refinement solved for {nroots}.")
            if note not in notes:
                notes.append(note)

        intruders = sorted({
            c for c in chars
            if predicted and not any(characters_compatible(c, p)
                                     for p in predicted)})
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
            new_mo, new_cas, swapped, rebalanced = reseed_lost_character(
                mol, mc, recommendation, pi_t, lp_t, max_swap=lost,
                nelec=nelec, spin_2s=spin_2s)
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
                if rebalanced != nelec:
                    rotations.append(Rotation(
                        cycle=cycle, action="rebalance",
                        why=(f"the swap changed how many active orbitals are "
                             f"occupied, so the electron count moved from "
                             f"{nelec} to {rebalanced}: CAS({rebalanced},{ncas}) "
                             f"has {ncas - rebalanced // 2} acceptor orbitals "
                             f"where CAS({nelec},{ncas}) had "
                             f"{ncas - nelec // 2}")))
                    log(f"[refine]   rebalanced {nelec} -> {rebalanced} electrons")
                    nelec = rebalanced
                log(f"[refine]   swapped {swapped} orbital(s) back in; re-solving")
                continue
            notes.append(
                f"{', '.join(missing)} is absent and {lost:.2f} orbitals' worth "
                f"of character has left the space, but no orbital outside it "
                f"carries enough of that character to swap back in.")
        elif missing and analysis is not None and augments < MAX_AUGMENT:
            augments += 1
            # `augment` reads the active orbitals as the contiguous slice
            # mo[:, ncore:ncore + ncas], while everywhere else in this loop
            # they are named by `caslst` against `mo`. Those two agree only
            # while `caslst` happens to be range(ncore, ncore + ncas), and the
            # narrowing branch above breaks exactly that: it resets `mo` to the
            # recommendation's own column order and makes `caslst` a SUBSET of
            # the tier's indices, non-contiguous as soon as it skips anything
            # in the middle, without touching `ncore`. Augmentation would then
            # decide which requested orbitals are already spanned by measuring
            # against a window that is not the active space, and nothing would
            # error. The `caslst` rebuilt below makes the same assumption.
            #
            # So make it true rather than assume it: sort the named orbitals
            # into the active window first, exactly as the seed construction at
            # the top of the cycle does, and use that ordering for both.
            aug_mc = mcscf.CASSCF(mf, ncas, _as_nelec(nelec, spin_2s))
            aug_mo = mcscf.sort_mo(aug_mc, mo, [c + 1 for c in caslst], base=1)
            aug_ncore = int(aug_mc.ncore)
            new_mo, n_added, aug_notes = augment(aug_mo, aug_ncore, ncas,
                                                 analysis, mol, n_states)
            if n_added:
                notes.extend(aug_notes)
                for note in aug_notes:
                    rotations.append(Rotation(cycle=cycle, action="augment",
                                              why=note))
                mo = new_mo
                ncore = aug_ncore
                caslst = list(range(aug_ncore, aug_ncore + ncas + n_added))
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
                                    chars, e_ground_before=_ground_energy(mc),
                                    e_reference=float(mf.e_tot))
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
    spin_adapted = bool(getattr(mc, "_nexusqc_spin_adapted", True))
    if not spin_adapted:
        notes.append(
            "The spin-adapted CI solver could not be imported, so the state "
            "average was NOT confined to one multiplicity and its roots may be "
            "of mixed spin. A triplet's transition density from a singlet "
            "ground state is zero by spin, so any character reported here is "
            "unreliable and the states this space was audited against may not "
            "be the ones it was asked about. Install pyscf-forge to restore "
            "the constraint.")
    return RefineResult(
        n_roots_solved=int(nroots),
        spin_adapted=spin_adapted,
        n_electrons=nelec, n_orbitals=ncas,
        mo_coeff=mc.mo_coeff, ncore=mc.ncore,
        occupations=[float(x) for x in occ],
        energies_ev=[float(x) for x in _energies(mc)],
        characters=_root_characters(mc, mol, pi_t, lp_t),
        natural_orbitals=_natural_orbital_set(mc, _u),
        **dict(zip(("orbital_labels", "orbital_weights"),
                   orbital_characters(
                       mol, mc.mo_coeff[:, mc.ncore:mc.ncore + mc.ncas] @ _u,
                       occ, pi_t, lp_t, sig_t))),
        rotations=rotations, cycles=cycle,
        started_from=chosen, start_space=start_space,
        converged=bool(mc.converged),
        rydberg_excluded=list(rydberg_excluded),
        stopped_because=stopped, notes=notes,
    )
