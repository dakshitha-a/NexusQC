"""The orientation-aware valence projector.

This is AVAS's mathematics (Sayfutyarova, Sun, Chan and Knizia,
*J. Chem. Theory Comput.* **2017**, 13, 4063; arXiv:1701.07862) with one
generalisation: the reference space is not a set of *coordinate-aligned*
minimal-basis AOs picked out by label, but an arbitrary set of *oriented*
combinations of them, built along directions that ``geometry.perceive``
derives from the molecular structure.

Why that generalisation is necessary, and not a nicety
------------------------------------------------------
Stock AVAS takes labels like ``'C 2px'``. The component is named in the
laboratory frame, so the space it selects depends on how the molecule happens
to be oriented in its input file. Measured here on pyrrole: a correct CAS(6,5)
in the frame where the ring lies in a coordinate plane becomes CAS(10,7) after
an arbitrary rotation of the same molecule. Geometries in this app come from
PubChem, from a sketcher, or from an optimiser, in whatever orientation those
produce, so an orientation-dependent selector cannot be used.

Writing the target as ``|t> = a_x |p_x> + a_y |p_y> + a_z |p_z>`` with **a**
a unit vector taken from the geometry fixes this: **a** rotates with the
molecule, so the target orbital does too, and the selected space is invariant.

The same construction is what makes the result basis-set independent. The
targets live in a fixed minimal reference basis (``minao``), so the *question*
asked of the wavefunction -- "how much of this MO is oxygen's in-plane
non-bonding p?" -- does not change when the calculation basis does. Verified
across STO-3G, def2-SVP, cc-pVDZ, def2-TZVP and aug-cc-pVDZ, where the
recommended ``(ne, no)`` is identical.

The mathematics
---------------
Let :math:`\\mathbf{T}` (``n_minao x n_target``) hold the oriented target
combinations, :math:`\\mathbf{S}^{pp}` the minimal-basis overlap and
:math:`\\mathbf{S}^{cp}` the cross overlap between the calculation basis and
the minimal one. With MO coefficients :math:`\\mathbf{C}`,

.. math::

    \\mathbf{S}^{2} = \\mathbf{T}^{\\dagger}\\mathbf{S}^{pp}\\mathbf{T},
    \\qquad
    \\mathbf{S}^{21} = \\mathbf{T}^{\\dagger}\\mathbf{S}^{pc}\\mathbf{C},
    \\qquad
    \\mathbf{A} = (\\mathbf{S}^{21})^{\\dagger}
                  (\\mathbf{S}^{2})^{-1}\\mathbf{S}^{21}

:math:`\\mathbf{A}` is the matrix of the projector onto the target space,
expressed in the MO basis. Diagonalising its occupied and virtual blocks
*separately* -- which is what keeps the occupied/virtual partition, and so the
electron count, well defined -- gives eigenvalues in [0, 1] measuring how much
target character each rotated orbital carries. Those above ``threshold`` are
the active space; the rest become core and virtual.

Cost is one matrix solve and two small eigendecompositions on top of a
converged SCF: milliseconds. Nothing here is iterative.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

import numpy as np
import scipy.linalg

# AVAS's own default, and deliberately unchanged: the eigenvalues it applies to
# have the same meaning here, so a different number would only make the two
# harder to compare in the head-to-head evaluation.
THRESHOLD = 0.2
MINAO = "minao"

# Shell letter -> the m-labels pyscf uses for its cartesian-ish p components.
# Only p and s are orientable; d targets go in whole (see `metal_d`).
_P_COMPONENTS = ("x", "y", "z")


@dataclass
class ProjectedSpace:
    """The candidate pool: an active space and the orbitals that define it."""

    ncas: int
    nelecas: tuple                 # (n_alpha, n_beta)
    mo_coeff: np.ndarray           # full set, ordered core | active | virtual
    ncore: int
    occ_weights: np.ndarray        # projector eigenvalues, occupied block
    vir_weights: np.ndarray        # projector eigenvalues, virtual block
    active_weights: np.ndarray     # the ones that passed threshold, in mo order
    target_labels: list = field(default_factory=list)
    notes: list = field(default_factory=list)

    @property
    def active_slice(self) -> slice:
        return slice(self.ncore, self.ncore + self.ncas)


def build_target_matrix(pmol, targets) -> tuple:
    """Assemble ``T``: oriented target combinations in the minimal basis.

    Each `Target` with an axis becomes one column, a unit-vector combination of
    that atom's p (or s) components. A target with ``axis=None`` -- a
    transition-metal d shell -- contributes one column per component, since the
    ligand field rather than the geometry decides which of them matter and
    prejudging that here would be wrong.

    Returns ``(T, labels)``. A target whose shell is absent from the minimal
    basis for that element is skipped with no column, rather than raising: a
    missing reference AO should shrink the pool, not fail the job.
    """
    labels = pmol.ao_labels(fmt=None)      # (atom_id, symbol, nl, ml)
    columns, names = [], []

    for t in targets:
        shell = t.shell
        # Index the components of this atom's requested shell by their m label.
        comp = {
            ml: k for k, (a, _sym, nl, ml) in enumerate(labels)
            if a == t.atom_index and nl == shell
        }
        if not comp:
            continue

        if t.axis is None:
            # Whole shell, one column each.
            for ml, k in sorted(comp.items()):
                col = np.zeros(pmol.nao)
                col[k] = 1.0
                columns.append(col)
                names.append(f"{t.element}{t.atom_index} {shell}{ml} [{t.kind}]")
            continue

        axis = np.asarray(t.axis, dtype=float)
        col = np.zeros(pmol.nao)
        if shell.endswith("s"):
            # An s function has no orientation; the axis is carried by the
            # partner atom's p in the same sigma bond.
            k = comp.get("", next(iter(comp.values())))
            col[k] = 1.0
        else:
            hit = False
            for ml, amp in zip(_P_COMPONENTS, axis):
                if ml in comp:
                    col[comp[ml]] = amp
                    hit = True
            if not hit:
                continue
        columns.append(col)
        names.append(f"{t.element}{t.atom_index} {shell} [{t.kind}] {t.note}")

    if not columns:
        return np.zeros((pmol.nao, 0)), []
    return np.asarray(columns).T, names


def project(mf, targets, *, threshold: float = THRESHOLD, minao: str = MINAO,
            ncore: int = 0) -> ProjectedSpace:
    """Project the SCF orbitals onto the oriented target space.

    Follows AVAS's ``openshell_option=2``: a singly occupied orbital is treated
    on the alpha side, so an open-shell molecule is handled rather than
    refused. The legacy runners raised on ``mol.spin != 0``; there is no such
    refusal here.
    """
    mol = mf.mol
    is_uhf = getattr(mf, "mo_coeff", None) is not None and np.ndim(mf.mo_coeff) == 3
    if is_uhf:
        # UHF/UKS: alpha orbitals, as AVAS does. The beta set spans nearly the
        # same space for the systems this is used on, and mixing the two would
        # make the occupied/virtual partition ambiguous.
        mo_coeff = mf.mo_coeff[0]
        mo_occ = mf.mo_occ[0]
    else:
        mo_coeff = mf.mo_coeff
        mo_occ = mf.mo_occ

    nocc = int(np.count_nonzero(mo_occ != 0))

    pmol = mol.copy()
    pmol.atom = mol._atom
    pmol.unit = "B"                 # mol._atom is already in bohr
    pmol.symmetry = False
    pmol.basis = minao
    pmol.build(False, False)

    T, names = build_target_matrix(pmol, targets)
    if T.shape[1] == 0:
        raise ValueError(
            "No projection targets survived into the reference basis, so no "
            "active space can be built. This means the perceived targets name "
            "shells that the minimal basis does not carry for these elements."
        )

    # S2: target-target overlap.  S21: target-MO overlap.
    s_pp = pmol.intor_symmetric("int1e_ovlp")
    from pyscf import gto
    s_pc = gto.intor_cross("int1e_ovlp", pmol, mol)

    s2 = T.T @ s_pp @ T
    s21 = (T.T @ s_pc) @ mo_coeff[:, ncore:]

    # The target set is over-complete by construction -- sigma targets on
    # bonded neighbours overlap heavily, and a lone-pair direction can be
    # near-parallel to a sigma one. So S2 is singular in general and a plain
    # inverse is not available. `lstsq` takes the pseudo-inverse, which is the
    # projector onto the span, which is exactly the quantity we want: the
    # answer depends on the SPAN of the targets, never on the particular
    # (redundant, non-orthogonal) vectors chosen to describe it. This is also
    # what makes the degenerate pi pair of a linear centre safe to emit.
    sol, *_ = np.linalg.lstsq(s2, s21, rcond=None)
    sa = s21.T @ sol
    sa = 0.5 * (sa + sa.T)          # symmetrise away round-off

    n_occ_block = nocc - ncore
    wocc, uocc = np.linalg.eigh(sa[:n_occ_block, :n_occ_block])
    wvir, uvir = np.linalg.eigh(sa[n_occ_block:, n_occ_block:])

    occ_active = wocc >= threshold
    vir_active = wvir >= threshold

    mocore = mo_coeff[:, ncore:nocc] @ uocc[:, ~occ_active]
    mocas_o = mo_coeff[:, ncore:nocc] @ uocc[:, occ_active]
    mocas_v = mo_coeff[:, nocc:] @ uvir[:, vir_active]
    movir = mo_coeff[:, nocc:] @ uvir[:, ~vir_active]

    mocas = np.hstack([mocas_o, mocas_v])
    ncas = mocas.shape[1]
    n_core_total = ncore + mocore.shape[1]

    # Electron count: every occupied orbital that did NOT make the cut stays
    # doubly occupied in the core, so the active space carries the rest.
    n_dropped_occ = int((~occ_active).sum())
    nelec_total = mol.nelectron - ncore * 2
    nelecas_total = nelec_total - 2 * n_dropped_occ
    n_beta = (nelecas_total - mol.spin) // 2
    n_alpha = nelecas_total - n_beta

    mo_out = np.hstack([mo_coeff[:, :ncore], mocore, mocas, movir])

    notes = []
    if ncas and nelecas_total == 2 * ncas:
        notes.append(
            "Every orbital in this pool is doubly occupied, so it holds exactly "
            "one configuration and describes no correlation. That means the "
            "targets found no virtual character -- usually a molecule whose "
            "sigma bonds were left out of the target set."
        )

    return ProjectedSpace(
        ncas=ncas,
        nelecas=(int(n_alpha), int(n_beta)),
        mo_coeff=mo_out,
        ncore=int(n_core_total),
        occ_weights=wocc[::-1].copy(),
        vir_weights=wvir[::-1].copy(),
        active_weights=np.hstack([wocc[occ_active], wvir[vir_active]]),
        target_labels=names,
        notes=notes,
    )
