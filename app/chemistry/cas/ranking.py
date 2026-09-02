"""Ranking the candidate pool by approximate pair-coefficient entropy.

The projector says *which orbitals are chemically relevant*. It does not say
which of them actually carry static correlation, and for a molecule of any
size it returns more than anyone wants to correlate: benzene's full
pi+sigma pool is 25 orbitals. Something has to order them.

The measure used here is the approximate pair coefficient (APC) of King and
Gagliardi (*J. Chem. Theory Comput.* **2021**, 17, 2817), which ships with
pyscf as ``pyscf.mcscf.apc``. For an occupied orbital :math:`i` and a virtual
orbital :math:`a` it estimates the coefficient of the doubly excited
configuration :math:`|\\Phi_{i\\bar{i}}^{a\\bar{a}}\\rangle` in closed form from
quantities a converged SCF already has:

.. math::

    c_{ia} = \\frac{-K_{aa}/2}
                   {\\Delta_{ia} + \\sqrt{(K_{aa}/2)^2 + \\Delta_{ia}^2}},
    \\qquad \\Delta_{ia} = F_{aa} - F_{ii}

which is the two-level (two-electron-in-two-orbital) CI solution with an
exchange coupling over an orbital-energy gap. Normalising the row or column of
coefficients belonging to one orbital and reading the result as a two-state
population gives that orbital an entropy,

.. math::

    s_p = -\\sigma_p \\ln \\sigma_p - (1 - \\sigma_p)\\ln(1 - \\sigma_p),
    \\qquad \\sigma_p = \\frac{\\sum_q c_{pq}^2}{1 + \\sum_q c_{pq}^2}

so orbitals that are strongly coupled to a near-degenerate partner rank high
and inert ones rank low. The APC-N variant repeats the estimate `n` times,
promoting the highest-entropy virtual to singly occupied each round, which
stops a single low-lying virtual dominating the ranking.

**The cost is the point.** This needs only ``mf.get_fock()`` and
``mf.get_k()``: no CASCI, no MP2, no DMRG, no iteration. Measured here at
about 0.1 s for molecules where the legacy runner's exact-FCI entropy pilot
took seconds and its DMRG pilot took minutes. That is what lets the
recommendation stay interactive while having no orbital cap.

**Why it ranks inside the pool and never selects from the whole MO space.**
APC over all molecular orbitals is not basis independent. Measured on pyrrole,
raw APC returns CAS(18e,12o) in def2-SVP and CAS(22e,13o) in def2-TZVP: the
virtual manifold it ranks over grows with the basis, and the orbitals it
promotes are partly artefacts of that manifold rather than chemistry. Applied
to the projector's pool, the candidates are fixed by the geometry before APC
sees them, so the ranking orders a basis-independent set and the result
inherits that. This is the same division of labour AEGISS uses (Chen et al.,
arXiv:2508.10671) -- atomic-orbital projection to choose candidates, an
entropy to order them -- with a closed-form entropy in place of its partially
converged DMRG, which is where essentially all of AEGISS's cost lives.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

# APC-N rounds. 2 is the pyscf default and King and Gagliardi's recommendation;
# a larger value biases towards spaces with fewer doubly occupied orbitals.
APC_N = 2


@dataclass
class RankedPool:
    """The projected pool, with an importance ordering over its orbitals."""

    entropies: np.ndarray      # one per active orbital, pool-local order
    order: np.ndarray          # indices into the active block, most important first
    occupations: np.ndarray    # 2/1/0 per active orbital
    notes: list


def apc_entropies(mf, mo_coeff, mo_occ) -> np.ndarray:
    """APC entropies for an arbitrary orbital set, not just the SCF's own.

    ``pyscf.mcscf.apc.APC`` reads ``mf.mo_coeff``/``mf.mo_occ`` off the mean
    field object, but the orbitals we need entropies for are the projector's
    rotated ones. Rather than mutate the caller's ``mf`` -- which would corrupt
    an object the runner reuses for TDA later -- the Fock and exchange matrices
    are pulled once and transformed here. This mirrors what ``APC._apc`` does
    internally, on the orbitals we choose.
    """
    from pyscf import scf

    f_ao = mf.get_fock()
    k_ao = mf.get_k()
    occ = np.asarray(mo_occ, dtype=float).copy()

    if isinstance(mf, scf.uhf.UHF):
        # APC's own convention for unrestricted references: averaged Fock,
        # summed exchange, summed occupation, alpha orbitals.
        f_ao = np.sum(f_ao, axis=0) / 2
        k_ao = np.sum(k_ao, axis=0)
        if occ.ndim == 2:
            occ = occ.sum(axis=0)
    elif isinstance(mf, scf.rohf.ROHF) and np.ndim(k_ao) == 3:
        k_ao = np.sum(k_ao, axis=0)

    f_mo = mo_coeff.T @ f_ao @ mo_coeff
    k_mo = mo_coeff.T @ k_ao @ mo_coeff

    docc = np.where(occ == 2)[0]
    single = np.where(occ == 1)[0]
    virt = np.where(occ == 0)[0]

    ent = np.zeros(mo_coeff.shape[1])
    if len(docc) and len(virt):
        # c_ia from the closed-form two-level solution, vectorised over the
        # whole occupied x virtual block.
        k12 = 0.5 * np.diag(k_mo)[virt]                     # (nvir,)
        delta = np.diag(f_mo)[virt][None, :] - np.diag(f_mo)[docc][:, None]
        c = -k12[None, :] / (delta + np.sqrt(k12[None, :] ** 2 + delta ** 2))
        c2 = c ** 2
        for idx, row in zip(docc, c2.sum(axis=1)):
            ent[idx] = _two_state_entropy(row)
        for idx, col in zip(virt, c2.sum(axis=0)):
            ent[idx] = _two_state_entropy(col)

    # A singly occupied orbital is by definition open shell and belongs in any
    # active space; give it the top rank rather than a computed value.
    if len(single):
        ent[single] = ent.max() + 1e-3
    return ent


def _two_state_entropy(sum_c2: float) -> float:
    """von Neumann entropy of the normalised two-state population."""
    norm2 = sum_c2 + 1.0
    sigma = sum_c2 / norm2
    ground = 1.0 / norm2
    out = 0.0
    for p in (sigma, ground):
        if p > 1e-15:
            out -= p * np.log(p)
    return float(out)


def rank_pool(mf, projected, *, spin_2s: int = 0, n: int = APC_N) -> RankedPool:
    """Order the projector's active orbitals by APC entropy.

    Only the active block is ranked -- the pool is already the answer to "which
    orbitals are chemically relevant", and re-asking that question over the
    whole MO space is what makes raw APC basis dependent.
    """
    sl = projected.active_slice
    mo = projected.mo_coeff
    nelec = sum(projected.nelecas)

    # Occupations within the active block. The projector emits its
    # occupied-derived orbitals first, so the block fills from the bottom: the
    # doubly occupied orbitals, then `spin_2s` singly occupied ones, then the
    # virtuals.
    #
    # This must be driven by the molecule's spin, not by the electron count
    # alone. Filling `nelec // 2` orbitals doubly is only right for a closed
    # shell; for an O2 triplet it puts ten electrons into five doubly occupied
    # orbitals and loses the two singly occupied pi* orbitals that are the
    # entire reason the molecule needs a multireference treatment. That in turn
    # fed a wrong electron count into every subset tier.
    occ = np.zeros(projected.ncas)
    n_docc = (nelec - spin_2s) // 2
    occ[:n_docc] = 2.0
    if spin_2s:
        occ[n_docc:n_docc + spin_2s] = 1.0

    # Entropies are computed over the full orbital set -- an active orbital's
    # coupling to the inactive virtuals is part of what makes it important --
    # then read off for the active block.
    full_occ = np.zeros(mo.shape[1])
    full_occ[:projected.ncore] = 2.0
    full_occ[sl] = occ

    ent_full = apc_entropies(mf, mo, full_occ)

    # APC-N: promote the highest-entropy virtual to singly occupied and redo,
    # so one low virtual cannot dominate the ordering.
    notes = []
    for _round in range(max(0, n)):
        virt = np.where(full_occ == 0)[0]
        if virt.size == 0:
            notes.append("APC-N stopped early: no virtual orbitals left to promote.")
            break
        full_occ[virt[np.argmax(ent_full[virt])]] = 1.0
        ent_full = apc_entropies(mf, mo, full_occ)

    ent = ent_full[sl]
    order = np.argsort(ent)[::-1]
    return RankedPool(entropies=ent, order=order, occupations=occ, notes=notes)
