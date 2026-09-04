"""The excited-state branch: which orbitals do the requested states need?

A ground-state active space is chosen by asking which orbitals carry static
correlation. That question does not identify the orbitals a *particular
excited state* is made of, and for the states this app is usually asked about
the difference decides whether the answer is right or useless.

The legacy runner widened its space when more states were requested than it
could hold, by adding whichever remaining orbital maximised the *configuration
count*, with entropy as a tiebreak. That rule cannot know chemistry. A dark
n->pi* state needs the heteroatom lone pair in the space; nothing about
counting configurations will put it there, and if it is missing the state is
simply absent from the calculation, with no error to say so.

The approach here is to ask the states themselves, cheaply, before choosing.

Step 1: a linear-response pass
------------------------------
TDA on a range-separated hybrid (CAM-B3LYP; Yanai, Tew and Handy, *Chem. Phys.
Lett.* **2004**, 393, 51), for at least twice the requested number of roots so
the window has margin. A range-separated functional matters: TDA on a
Hartree-Fock reference is CIS, which overestimates valence excitations by of
order an electron-volt and misorders them, and state *ordering* is exactly what
this branch depends on.

Step 2: natural transition orbitals
-----------------------------------
Each root's transition density matrix :math:`\\mathbf{T}` is decomposed
(Martin, *J. Chem. Phys.* **2003**, 118, 4775) by singular value
decomposition,

.. math::

    \\mathbf{T} = \\mathbf{U}\\,\\boldsymbol{\\lambda}\\,\\mathbf{V}^{\\dagger}

so that a transition described by many canonical orbital pairs collapses into
one dominant hole/particle pair :math:`(u_1, v_1)` with weight
:math:`\\lambda_1^2`. Using NTOs rather than the largest canonical amplitude is
what makes the classification stable: canonical orbitals mix arbitrarily among
degenerate sets, NTOs do not.

Step 3: character, from the orbitals rather than from the energy
----------------------------------------------------------------
Each state is labelled by what its NTOs actually are.

*Spatial extent* separates Rydberg from valence. The second moment of the
particle NTO is compared with the largest second moment among occupied
orbitals, which is a measure of the molecule's own size:

.. math::

    \\rho = \\frac{\\langle v_1 | r^2 | v_1 \\rangle}
                 {\\max_i \\langle \\phi_i | r^2 | \\phi_i \\rangle}

Measured on formaldehyde in aug-cc-pVDZ, valence states sit at
:math:`\\rho \\approx 0.86` and Rydberg states at 4.6 to 8.7 -- a factor of five,
so the threshold is not delicate.

*Projection onto the perceived targets* separates pi from n from sigma, using
the same oriented targets the ground-state projector uses. A hole with large
overlap on a lone-pair target is an n orbital; one with large overlap on a pi
target is a pi orbital.

*Oscillator strength* labels the state bright or dark. This is reported, never
used to select: a dark state is not a less important state, and the reason this
branch exists is that dark n->pi* states are the ones a ground-state-only
criterion loses.

The basis limit, reported rather than hidden
--------------------------------------------
Rydberg states cannot be described at all without diffuse basis functions. In
cc-pVDZ no state is flagged Rydberg -- correctly, since none can be
represented. This is the one place where the engine's basis independence
genuinely ends, so when the analysis basis carries no diffuse functions the
result says that Rydberg states were not looked for, instead of silently
returning a valence-only answer that looks complete.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

# <r^2> of the particle NTO relative to the largest occupied-orbital <r^2>,
# above which a state is called Rydberg. Valence states measure ~0.9 and
# Rydberg ones 4.6-8.7 on formaldehyde/aug-cc-pVDZ, so anything in 2-4 works;
# 3.0 sits in the middle of that gap.
RYDBERG_R2_RATIO = 3.0

# Weight on a target kind, above which the hole or particle is called that kind.
CHARACTER_WEIGHT = 0.30

# Oscillator strength above which a state is called bright. Reported only.
BRIGHT_THRESHOLD = 0.01

HARTREE_TO_EV = 27.211386245988


@dataclass
class ExcitedState:
    index: int                    # 1-based root number
    energy_ev: float
    oscillator_strength: float
    character: str                # "n->pi*", "pi->pi*", "->Rydberg", ...
    hole_kind: str                # "n" | "pi" | "sigma" | "mixed"
    particle_kind: str            # "pi*" | "sigma*" | "Rydberg" | "mixed"
    r2_ratio: float
    bright: bool
    nto_weight: float             # lambda_1^2, how well one pair describes it

    def to_dict(self) -> dict:
        return {
            "state": self.index,
            "energy_ev": round(self.energy_ev, 3),
            "oscillator_strength": round(self.oscillator_strength, 5),
            "character": self.character,
            "bright": self.bright,
            "spatial_extent_ratio": round(self.r2_ratio, 2),
            "nto_weight": round(self.nto_weight, 3),
        }


@dataclass
class ExcitedAnalysis:
    states: list = field(default_factory=list)
    hole_orbitals: object = None      # (nao, n) dominant hole NTOs
    particle_orbitals: object = None  # (nao, n) dominant particle NTOs
    diffuse_present: bool = False
    rydberg_detectable: bool = False
    notes: list = field(default_factory=list)


# Whether a Rydberg state can be described here is asked of the calculation
# rather than of the basis set's name or its exponents. `basis_has_diffuse`
# used to live here and tested the smallest primitive exponent against 0.05;
# it got def2-svpd wrong, which is this engine's own default analysis basis
# whenever excited states are requested, so every production excited-state
# recommendation reported that Rydberg states had not been looked for while
# the same calculation was finding one and mislabelling it as valence.
# `app/chemistry/cas/diffuse.py` carries the measurement and the evidence.
from app.chemistry.cas.diffuse import rydberg_representable  # noqa: E402,F401


def _second_moments(mol, mo):
    """<r^2> for each column of `mo`, about the molecular centroid."""
    with mol.with_common_orig(mol.atom_coords().mean(axis=0)):
        r2 = mol.intor("int1e_r2")
    ovlp = mol.intor("int1e_ovlp")
    num = np.einsum("pi,pq,qi->i", mo, r2, mo)
    den = np.einsum("pi,pq,qi->i", mo, ovlp, mo)
    return num / np.where(np.abs(den) > 1e-12, den, 1.0)


def _target_weights(mol, orbital, targets, minao="minao"):
    """How much of `orbital` lies on each kind of perceived target.

    Reuses the ground-state projector's target construction, so "is this a
    lone pair" is answered by the same machinery that decides which orbitals
    enter the space -- one definition of pi and n, not two.
    """
    from pyscf import gto

    from app.chemistry.cas.projector import build_target_matrix

    pmol = mol.copy()
    pmol.atom = mol._atom
    pmol.unit = "B"
    pmol.symmetry = False
    pmol.basis = minao
    pmol.build(False, False)

    weights = {}
    s_pc = gto.intor_cross("int1e_ovlp", pmol, mol)
    s_pp = pmol.intor_symmetric("int1e_ovlp")
    ovlp = mol.intor("int1e_ovlp")
    norm = float(orbital @ ovlp @ orbital)
    if norm < 1e-12:
        return weights

    for kind in {t.kind for t in targets}:
        subset = [t for t in targets if t.kind == kind]
        T, _names = build_target_matrix(pmol, subset)
        if T.shape[1] == 0:
            continue
        s2 = T.T @ s_pp @ T
        proj = (T.T @ s_pc) @ orbital
        sol, *_ = np.linalg.lstsq(s2, proj, rcond=None)
        weights[kind] = float(proj @ sol) / norm
    return weights


def _label(weights, r2_ratio, is_particle, rydberg_detectable):
    if is_particle and rydberg_detectable and r2_ratio > RYDBERG_R2_RATIO:
        return "Rydberg"
    if not weights:
        return "mixed"
    kind, w = max(weights.items(), key=lambda kv: kv[1])
    if w < CHARACTER_WEIGHT:
        return "mixed"
    star = "*" if is_particle else ""
    return {"pi": f"pi{star}", "lone_pair": "n" if not is_particle else "n*",
            "sigma": f"sigma{star}", "metal_d": "d"}.get(kind, "mixed")


def analyse(mf_ks, td, targets, n_states: int) -> ExcitedAnalysis:
    """Classify `td`'s roots and return their dominant NTO pairs.

    `mf_ks` is the Kohn-Sham reference the TDA was run on; `td` the solved
    TDA object; `targets` the perceived targets from `geometry.perceive`.
    """
    mol = mf_ks.mol
    mo = mf_ks.mo_coeff
    occ = mf_ks.mo_occ
    nocc = int(np.count_nonzero(occ != 0))

    diffuse = rydberg_representable(mf_ks)
    notes = []
    if not diffuse:
        notes.append(
            "This calculation offers no orbital diffuse enough to hold a Rydberg "
            "state, so none were looked for. That is a statement about this "
            "basis on these atoms rather than about the basis set's name: a set "
            "that augments carbon usefully may do little for fluorine. If the "
            "states of interest may be Rydberg, the recommendation needs a more "
            "diffuse basis to find them; a valence answer computed here would "
            "look complete while silently omitting them."
        )

    r2_occ = _second_moments(mol, mo[:, occ > 0])
    valence_extent = float(np.max(r2_occ)) if r2_occ.size else 1.0

    osc = td.oscillator_strength()
    holes, particles, states = [], [], []

    for n in range(min(len(td.e), max(n_states * 2, n_states))):
        w, nto = td.get_nto(state=n + 1)
        # pyscf returns the full orbital set with both blocks already sorted by
        # weight, descending: the dominant hole is the FIRST column of the
        # occupied block and the dominant particle the first of the virtual
        # block. Taking the hole from `nocc - 1` instead -- the column next to
        # the HOMO, which looks like the natural place for it -- picks an
        # essentially unused NTO, and every state then classifies as "mixed"
        # because that orbital has no character to find.
        hole = nto[:, 0]
        particle = nto[:, nocc]
        weight = float(np.asarray(w).ravel()[0]) if np.size(w) else float("nan")

        r2_p = float(_second_moments(mol, particle[:, None])[0])
        ratio = r2_p / valence_extent if valence_extent else float("nan")

        hk = _label(_target_weights(mol, hole, targets), 0.0, False, diffuse)
        pk = _label(_target_weights(mol, particle, targets), ratio, True, diffuse)

        holes.append(hole)
        particles.append(particle)
        states.append(ExcitedState(
            index=n + 1,
            energy_ev=float(td.e[n]) * HARTREE_TO_EV,
            oscillator_strength=float(osc[n]),
            character=f"{hk}->{pk}",
            hole_kind=hk, particle_kind=pk,
            r2_ratio=ratio,
            bright=bool(osc[n] >= BRIGHT_THRESHOLD),
            nto_weight=weight,
        ))

    any_rydberg = any(s.particle_kind == "Rydberg" for s in states)
    if any_rydberg:
        notes.append(
            f"{sum(1 for s in states if s.particle_kind == 'Rydberg')} of the "
            f"{len(states)} lowest states are Rydberg. Their orbitals are "
            "diffuse and do not belong in a valence active space; including "
            "them destabilises a CASSCF without improving the valence states."
        )
    return ExcitedAnalysis(
        states=states,
        hole_orbitals=np.asarray(holes).T if holes else None,
        particle_orbitals=np.asarray(particles).T if particles else None,
        diffuse_present=diffuse,
        rydberg_detectable=diffuse,
        notes=notes,
    )


def augment(mo_coeff, ncore: int, ncas: int, analysis, mol, n_states: int, *,
            min_residual: float = 0.30):
    """Add the orbitals the requested states need, if they are not present.

    Each requested state's dominant hole and particle natural transition
    orbitals are projected against the space already selected. What survives
    that projection is the part of the transition the space cannot describe;
    where its norm is significant the residual is orthonormalised and appended
    to the active block.

    Rydberg particle orbitals are deliberately **not** added. They are diffuse,
    they do not mix appreciably with the valence orbitals, and putting them in
    a CASSCF active space is a well-known way to make it hard to converge
    without improving the valence states. They are reported instead.

    Takes a bare ``(mo_coeff, ncore, ncas)`` rather than a `ProjectedSpace`,
    which is what kept it from being called for a whole release. The
    recommendation path holds a `ProjectedSpace`, the refinement path holds a
    converged `mcscf` object, and neither could be passed to a function typed
    for the other. Both can supply three arrays.

    Returns ``(mo_coeff, n_added, notes)``. When nothing needs adding the
    coefficients come back unchanged, so a caller can use the result
    unconditionally.
    """
    ovlp = mol.intor("int1e_ovlp")
    mo = np.asarray(mo_coeff).copy()
    active = mo[:, ncore:ncore + ncas].copy()
    core = mo[:, :ncore]
    notes, added = [], []

    for state in analysis.states[:max(n_states - 1, 0)]:
        idx = state.index - 1
        for role, block in (("hole", analysis.hole_orbitals),
                            ("particle", analysis.particle_orbitals)):
            if block is None or idx >= block.shape[1]:
                continue
            if role == "particle" and state.particle_kind == "Rydberg":
                continue
            v = block[:, idx].copy()
            # Project out everything already spanned: the active space, the
            # core, and anything added so far in this loop.
            for blk in [active, core] + ([np.asarray(added).T] if added else []):
                if blk.size:
                    v = v - blk @ (blk.T @ ovlp @ v)
            norm = float(np.sqrt(max(v @ ovlp @ v, 0.0)))
            if norm > min_residual:
                added.append(v / norm)
                notes.append(
                    f"State {state.index} ({state.character}, "
                    f"{state.energy_ev:.2f} eV) needed its {role} orbital "
                    f"added: {norm:.2f} of it lay outside the space."
                )
    if not added:
        return mo, 0, notes

    add = np.asarray(added).T
    new_mo = np.hstack([
        mo[:, :ncore + ncas], add,
        _drop_columns(mo[:, ncore + ncas:], add, ovlp),
    ])
    return new_mo, add.shape[1], notes


def _drop_columns(virtual, added, ovlp):
    """Remove from `virtual` the components now carried by `added`.

    Keeps the orbital set square and orthonormal by discarding the virtual
    orbitals with the largest overlap on the added ones -- one per addition.
    """
    if not virtual.size or not added.size:
        return virtual
    weight = np.abs(added.T @ ovlp @ virtual).sum(axis=0)
    drop = set(np.argsort(weight)[::-1][:added.shape[1]].tolist())
    keep = [i for i in range(virtual.shape[1]) if i not in drop]
    return virtual[:, keep]
