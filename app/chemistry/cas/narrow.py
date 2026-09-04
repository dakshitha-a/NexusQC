"""Trim a recommended space to what the requested states actually use.

This is a priori. It needs a geometry, a projected recommendation and the
linear-response analysis of the requested states, and nothing else: no
converged CASSCF, no natural occupations, no orbital optimisation. That is why
it lives in its own module rather than inside `refine`, where it was written
and where it was reachable only from the refinement loop. Both the quick
recommendation and the refinement can call it, and the quick recommendation is
the one that changes a user's answer, since it is what turns uracil's
CAS(22e,14o) into something near the CAS(14e,10o) the literature uses.

The rule and the two rules it replaced are in section 9.5 of
`docs/CAS_ENGINE_METHOD.md`. In short: project each predicted n->pi* hole onto
the atoms, keep the heteroatoms carrying at least `HOLE_ATOM_SHARE` of it,
expand that set to chemically equivalent partners, and admit
`LONE_PAIRS_PER_STATE` lone-pair orbitals per predicted state spread across
those centres. The pi system stays whole.

`csf_budget` is deliberately required rather than defaulted. A budget with a
silent default is a size limit nobody chose, and the two callers have different
reasons for the number they pass.
"""
from __future__ import annotations

import numpy as np

# A heteroatom counts as carrying a state's hole once it holds this much of it.
# o-Nitrophenol's two n->pi* holes sit 66%/27% on the nitro oxygens with 5% on
# the nitrogen; the cut keeps the oxygens and drops the nitrogen, which is the
# chemistry those states are made of.
HOLE_ATOM_SHARE = 0.10

# Lone-pair orbitals admitted per predicted n->pi* state.
#
# Two, because an n->pi* hole is routinely a combination of two lone pairs
# rather than one, and the literature spaces bear that out from both
# directions: formaldehyde's CAS(6e,4o) is pi, pi* and BOTH lone pairs of its
# single oxygen, while uracil's CAS(14e,10o) is one lone pair on each of two
# carbonyl oxygens. Different arrangements, the same count.
#
# Allocating per STATE rather than per atom is what reconciles them. One per
# participating centre gives formaldehyde a single lone pair and CAS(4e,3o);
# all the lone pairs of every participating centre gives uracil four and
# CAS(18e,12o). A budget of two per state, spread across the centres, gives
# both molecules the space their literature uses.
LONE_PAIRS_PER_STATE = 2


def _equivalent_heteroatoms(symbols, neighbours, centres):
    """Expand a set of atoms to include their chemically equivalent partners.

    Two heteroatoms are treated as equivalent when they are the same element
    with the same multiset of neighbour elements: the two oxygens of a nitro
    group, the two carbonyl oxygens of uracil, the two oxygens of a carboxylate.

    This exists because a linear-response hole does not see the symmetry. Uracil
    has two carbonyls and TDA puts 76% of its S1 hole on ONE of them, so
    counting atoms gives a single lone pair -- and a single lone pair is known
    not to work for this molecule: `reference_data` records that with 5pi+1n+3pi*
    the SA-CASSCF produces no n->pi* state at all, because the CASSCF hole is a
    combination of BOTH oxygens'. The state that is asked for is one of a pair,
    and its partner has to be in the space for either to be described.
    """
    def signature(i):
        return (symbols[i], tuple(sorted(symbols[j] for j in neighbours[i])))

    wanted = {signature(i) for i in centres}
    return {i for i in range(len(symbols))
            if symbols[i] not in ("H", "C") and signature(i) in wanted}


def narrow_to_states(mol, recommendation, tier, analysis, n_states,
                     pi_targets, lp_targets, *, nroots=1, csf_budget,
                     perception=None):
    """The pi system, plus the lone pairs the requested states actually use.

    The rule this replaces was "the whole pi system, plus every pool orbital
    projecting more than 0.30 onto a state's hole or particle". The second half
    is far too generous. o-Nitrophenol carries six lone-pair-derived orbitals --
    every nitrogen and oxygen contributes one -- and five of them clear that
    threshold, giving CAS(22e,15o) where the space a chemist uses for this
    molecule is CAS(12e,9o).

    Two tempting replacements were measured and rejected.

    *Coverage of the hole* does not work: an n->pi* hole expressed in the
    projector's eigenbasis smears across most of the lone-pair block, and
    uracil's needs FOUR of its six orbitals to reach 90% even though the
    chemistry is two carbonyl lone pairs. The projector's eigenbasis is not the
    chemist's basis and no threshold reconciles them.

    *Growing while the budget allows* does not work either, and fails in an
    instructive way: adding an occupied orbital to a nearly-full space REDUCES
    the CSF count (CAS(24e,15o) is 63,700 CSFs where CAS(22e,15o) is 496,860),
    so a greedy fill exploits the combinatorics instead of choosing chemistry
    and returns a larger space than it started from.

    What works is counting atoms rather than orbitals. Project each predicted
    n->pi* hole onto the atoms, keep the heteroatoms carrying at least
    HOLE_ATOM_SHARE of it, expand that set to chemically equivalent partners
    (see `_equivalent_heteroatoms`), and admit LONE_PAIRS_PER_STATE lone-pair
    orbitals per predicted state, spread across those centres. Per STATE and
    not per centre: formaldehyde's literature space is two lone pairs on one
    oxygen and uracil's is one on each of two, so a per-centre budget
    reproduces one of them and breaks the other whichever way it is set.
    The pi system stays whole, because the completion rule of section 4.3
    applies here too.

    Returns ``(caslst, n_electrons)``.
    """
    from app.chemistry.cas.excited import _target_weights
    from app.chemistry.cas.feasibility import n_csf

    mo = np.asarray(recommendation.mo_coeff)
    idx = list(tier.orbital_indices)
    n_docc = tier.n_electrons // 2
    ovlp = mol.intor("int1e_ovlp")
    labels = mol.ao_labels(fmt=None)

    def atom_populations(vec):
        gross = np.asarray(vec) * np.asarray(ovlp @ vec)
        pops = np.zeros(mol.natm)
        for k, (ia, _sym, _nl, _ml) in enumerate(labels):
            pops[ia] += gross[k]
        return pops

    # Which heteroatoms do the predicted n->pi* states actually sit on?
    centres = set()
    if analysis is not None:
        for st in analysis.states[:max(n_states - 1, 0)]:
            if "n->" not in (st.character or ""):
                continue
            i = st.index - 1
            if analysis.hole_orbitals is None or i >= analysis.hole_orbitals.shape[1]:
                continue
            pops = atom_populations(analysis.hole_orbitals[:, i])
            total = float(np.sum(np.abs(pops))) or 1.0
            for ia in range(mol.natm):
                sym = mol.atom_symbol(ia).rstrip("0123456789")
                if sym in ("H", "C"):
                    continue
                if pops[ia] / total >= HOLE_ATOM_SHARE:
                    centres.add(ia)

    if centres and perception is not None:
        centres = _equivalent_heteroatoms(list(perception.symbols),
                                          perception.neighbours, centres)

    # Classify the pool, and score each lone-pair orbital by how much of it sits
    # on a participating centre.
    pi_pool, lp_scores, other = [], {}, []
    for k, col in enumerate(idx):
        v = mo[:, col]
        wpi = _target_weights(mol, v, pi_targets).get("pi", 0.0)
        wlp = _target_weights(mol, v, lp_targets).get("lone_pair", 0.0)
        if wpi > wlp:
            pi_pool.append(k)
        elif wlp > 0.30:
            pops = atom_populations(v)
            lp_scores[k] = sum(float(pops[ia]) for ia in centres)
        else:
            other.append(k)

    # A budget of LONE_PAIRS_PER_STATE per predicted n->pi*, spread across the
    # participating centres so that a molecule with two carbonyls takes one
    # from each before taking a second from either. With no predicted n->pi*
    # there is nothing to keep them for and the pi system stands alone.
    n_npi = 0
    if analysis is not None:
        n_npi = sum(1 for st in analysis.states[:max(n_states - 1, 0)]
                    if "n->" in (st.character or ""))
    quota = LONE_PAIRS_PER_STATE * n_npi if centres else 0

    # Which centre does each lone-pair orbital belong to? Round-robin over the
    # centres by rank so the first pass takes one from each.
    by_centre = {}
    for k in sorted(lp_scores, key=lambda k: -lp_scores[k]):
        pops = atom_populations(mo[:, idx[k]])
        home = max(centres, key=lambda ia: float(pops[ia])) if centres else None
        by_centre.setdefault(home, []).append(k)

    picked = []
    while len(picked) < quota:
        took_any = False
        for home in sorted(by_centre,
                           key=lambda h: -max((lp_scores[k]
                                               for k in by_centre[h]),
                                              default=0.0)):
            if by_centre[home] and len(picked) < quota:
                picked.append(by_centre[home].pop(0))
                took_any = True
        if not took_any:
            break

    keep = sorted(set(pi_pool) | set(picked))

    # A backstop, not the selection rule: if the result still does not fit, drop
    # the weakest lone pairs before touching the pi system.
    def fits(sel):
        ne = 2 * sum(1 for j in sel if j < n_docc)
        c = n_csf(len(sel), ne, 0)
        return (not c) or c * max(nroots, 1) <= csf_budget

    while len(keep) > len(pi_pool) and not fits(keep):
        weakest = min((k for k in keep if k in lp_scores),
                      key=lambda k: lp_scores[k], default=None)
        if weakest is None:
            break
        keep.remove(weakest)

    keep = keep or list(range(len(idx)))
    caslst = [idx[k] for k in keep]
    nelec = 2 * sum(1 for k in keep if k < n_docc)
    return caslst, nelec
