"""The recommendation itself: perceive, project, rank, size, report.

This is the orchestrator. It takes a converged mean field and returns an active
space with the reasoning attached. It never builds a ``Mole`` and never imports
``registry2`` or ``pyscf_runner``, so it is equally callable from the job
worker, from the evaluation harness, and from a bare test script.

The tier rule
-------------
The projector is run twice, on two different target sets, and the two answers
are what the tiers are built from.

- **valence** targets are pi normals and lone pairs. For a conjugated or
  carbonyl-bearing molecule this is the space a chemist would name: benzene's
  six pi orbitals, butadiene's four, formaldehyde's pi/pi* plus the oxygen n.
- **extended** targets add every sigma bond, which brings in sigma and sigma*.

If the valence pool contains virtual orbitals, it is the recommendation, and
the extended pool is the maximal tier. If the valence pool is *full* -- every
orbital doubly occupied, so it holds one configuration and describes no
correlation -- then it is not a space at all and the extended pool becomes the
recommendation. That fallback is what makes hydrides and saturated molecules
work: water has no pi system, so its valence pool is a full ``(4e,2o)`` and
only the sigma-inclusive ``(8e,6o)`` is a real active space.

The minimal tier is the APC-ranked head of the recommended space, cut where
the entropy falls off, and then repaired by the completion rules so it is never
chemically half-finished.

Nothing here caps anything. A large space is reported with its cost, per
``feasibility``.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from app.chemistry.cas import feasibility
from app.chemistry.cas.geometry import perceive
from app.chemistry.cas.projector import project
from app.chemistry.cas.ranking import rank_pool

# Smallest gap in the *relative* APC entropy profile that counts as a real
# shoulder, and so as grounds for a smaller minimal tier.
#
# This number was calibrated, not inherited, and the reason is a finding worth
# recording. AEGISS and AutoCAS apply an absolute cut (S_max/10 and similar)
# because their entropies rank a pool of ~100 frontier orbitals, most of which
# are inert and must be discarded. Here the projector has already done that
# selection on chemical grounds, so *every* orbital that reaches the ranking is
# relevant and the entropies come out flat: measured over water, formaldehyde,
# benzene, pyrrole and butadiene, the relative entropies span only 0.55 to 1.00
# and never an order of magnitude. An absolute S_max/10 cut therefore prunes
# nothing at all, which is the correct answer for the wrong reason.
#
# A gap search says something meaningful about a flat profile: it fires only
# when there really is a shoulder. At 0.15 it recovers the textbook minimal
# spaces -- formaldehyde (4e,3o), the classical n/pi/pi* space, and pyrrole
# (6e,5o), its classical pi space -- while correctly declining to cut benzene
# below (6e,6o) and butadiene below (4e,4o), whose profiles have no shoulder
# because all of their pi orbitals genuinely matter. See
# `tests/backend/cas_05_tiers.py`.
MINIMAL_ENTROPY_GAP = 0.15


@dataclass
class Tier:
    name: str
    n_electrons: int
    n_orbitals: int
    orbital_indices: list          # 0-based, into the full MO set
    feasibility: object
    rationale: str = ""

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "n_electrons": self.n_electrons,
            "n_orbitals": self.n_orbitals,
            "orbital_indices_1based": [i + 1 for i in self.orbital_indices],
            "feasibility": self.feasibility.to_dict(),
            "rationale": self.rationale,
        }


@dataclass
class Recommendation:
    tiers: dict                    # name -> Tier
    recommended: str               # which tier name is the recommendation
    entropies: list
    target_labels: list
    notes: list = field(default_factory=list)
    states: list = field(default_factory=list)
    mo_coeff: object = None
    ncore: int = 0

    @property
    def space(self) -> tuple:
        t = self.tiers[self.recommended]
        return t.n_electrons, t.n_orbitals

    def to_dict(self) -> dict:
        return {
            "recommended_active_electrons": self.space[0],
            "recommended_active_orbitals": self.space[1],
            "recommended_tier": self.recommended,
            "tiers": {k: v.to_dict() for k, v in self.tiers.items()},
            "orbital_entropies": list(self.entropies),
            "projection_targets": list(self.target_labels),
            "state_table": list(self.states),
            "notes": list(self.notes),
        }


def _is_full(nelec: int, norb: int) -> bool:
    return norb == 0 or nelec >= 2 * norb


def _tier_from_pool(name, projected, spin_2s, rationale, keep=None,
                    occupations=None):
    """Build a Tier from a projected pool, optionally keeping a subset.

    The electron count of a subset is read off the pool's own per-orbital
    occupations rather than re-derived from the orbital ordering. Deriving it
    was subtly wrong for open shells -- the singly occupied orbitals of an O2
    triplet are not where a closed-shell "first half is occupied" rule puts
    them -- and produced spaces like a (2e,3o) O2 that were arithmetically
    consistent and physically meaningless.
    """
    idx = list(range(projected.ncore, projected.ncore + projected.ncas))
    if keep is not None:
        keep = sorted(keep)
        if occupations is None:
            raise ValueError("a subset tier needs the pool's occupations")
        n_elec = int(round(sum(float(occupations[k]) for k in keep)))
        idx = [idx[k] for k in keep]
    else:
        n_elec = sum(projected.nelecas)
    n_orb = len(idx)
    return Tier(
        name=name, n_electrons=n_elec, n_orbitals=n_orb, orbital_indices=idx,
        feasibility=feasibility.assess(n_orb, n_elec, spin_2s),
        rationale=rationale,
    )


def _balance(keep, ent, occupations, ncas):
    """Grow a candidate subset until it is a usable space.

    Adds back the highest-entropy orbital from whichever side is missing, so a
    cut that stranded all the occupied or all the virtual orbitals is repaired
    rather than returned, and a completely full result -- one configuration, no
    correlation -- is grown until it has somewhere for an electron to go.

    Occupancy comes from the pool's own occupations, so this is correct for
    open shells, where a singly occupied orbital counts as neither fully
    occupied nor empty.
    """
    keep = sorted(set(int(k) for k in keep))
    occupied = [k for k in range(ncas) if occupations[k] > 0]
    empty = [k for k in range(ncas) if occupations[k] == 0]
    for _ in range(ncas):
        n_elec = sum(float(occupations[k]) for k in keep)
        if not any(occupations[k] > 0 for k in keep):
            pool = [k for k in occupied if k not in keep]
        elif n_elec >= 2 * len(keep):
            pool = [k for k in empty if k not in keep]
        else:
            break
        if not pool:
            break
        keep.append(max(pool, key=lambda k: ent[k]))
        keep.sort()
    return keep


def _n_occ_in(projected, spin_2s) -> int:
    """How many of the pool's orbitals came from the occupied block."""
    nelec = sum(projected.nelecas)
    return (nelec + spin_2s) // 2 if nelec % 2 else nelec // 2


def recommend(mf, symbols, coords, *, spin_2s: int = 0,
              n_states: int = 1, threshold: float = 0.2) -> Recommendation:
    """Recommend an active space for the molecule behind `mf`.

    `n_states` is the number of electronic states the user wants, ground state
    included. It is accepted here so the ground-state path and the
    excited-state path share one entry point; the excited branch is applied by
    `app.chemistry.cas.excited` on top of the result.
    """
    coords = np.asarray(coords, dtype=float)
    notes = []

    per_valence = perceive(symbols, coords, include_sigma=False)
    per_extended = perceive(symbols, coords, include_sigma=True)

    pool_ext = project(mf, per_extended.targets, threshold=threshold)
    try:
        pool_val = project(mf, per_valence.targets, threshold=threshold)
    except ValueError:
        # No pi system and no lone pairs at all -- an alkane. The extended pool
        # is the only one there is.
        pool_val = None

    if pool_val is not None and not _is_full(sum(pool_val.nelecas), pool_val.ncas):
        primary, secondary = pool_val, pool_ext
        rationale_primary = (
            "the pi system and the non-bonding orbitals, which is the space a "
            "chemist would name for this molecule"
        )
    else:
        primary, secondary = pool_ext, pool_ext
        if pool_val is not None:
            notes.append(
                f"The pi and lone-pair orbitals alone give "
                f"({sum(pool_val.nelecas)}e, {pool_val.ncas}o), which is "
                f"completely full and so describes no correlation. This "
                f"molecule has no pi system to correlate, so the recommendation "
                f"is built from its sigma bonds instead."
            )
        rationale_primary = (
            "the sigma-bonding framework, used because this molecule has no "
            "pi system that could carry an active space on its own"
        )

    ranked = rank_pool(mf, primary, spin_2s=spin_2s)

    tiers = {}
    tiers["recommended"] = _tier_from_pool(
        "recommended", primary, spin_2s, rationale_primary)

    # Minimal: the entropy-ranked head of the recommended space, cut at the
    # largest shoulder in the profile -- but only if there is one.
    ent = ranked.entropies
    keep = list(range(primary.ncas))
    if ent.size > 2 and float(ent.max()) > 0:
        rel = ent / float(ent.max())
        srt = np.sort(rel)[::-1]
        gaps = srt[:-1] - srt[1:]
        g = int(np.argmax(gaps))
        if float(gaps[g]) >= MINIMAL_ENTROPY_GAP:
            cut = float(srt[g])
            keep = sorted(int(k) for k in np.where(rel >= cut - 1e-12)[0])
        else:
            notes.append(
                "The orbital entropies inside this space are flat (relative "
                f"range {float(srt[-1]):.2f} to 1.00, largest gap "
                f"{float(gaps[g]):.2f}), so there is no smaller subset that "
                "stands out: every orbital the projection selected carries "
                "comparable correlation. The minimal tier is the recommended "
                "space itself."
            )
    # Completion guard. A tier is only offered if it is a chemically sensible
    # space in its own right: it must hold electrons, must not be completely
    # full, and must keep at least one orbital on each side of the Fermi level.
    # Without this the gap search happily returns things like N2 (4e,5o) or an
    # O2 triplet (2e,3o), which are arithmetically fine and chemically useless.
    n_occ = _n_occ_in(primary, spin_2s)
    keep = _balance(keep, ent, ranked.occupations, primary.ncas)
    has_occ = any(k < n_occ for k in keep)
    has_vir = any(k >= n_occ for k in keep)
    if not (keep and has_occ and has_vir):
        # Fall back to the highest-entropy occupied and virtual pair.
        occ_idx = [k for k in range(primary.ncas) if k < n_occ]
        vir_idx = [k for k in range(primary.ncas) if k >= n_occ]
        keep = sorted(
            ([max(occ_idx, key=lambda k: ent[k])] if occ_idx else [])
            + ([max(vir_idx, key=lambda k: ent[k])] if vir_idx else [])
        )
        notes.append(
            "The minimal tier fell back to the single most strongly correlated "
            "occupied/virtual pair: the entropy profile had no clear shoulder."
        )
    if len(keep) < primary.ncas:
        tiers["minimal"] = _tier_from_pool(
            "minimal", primary, spin_2s,
            f"the {len(keep)} most strongly correlated orbitals of the "
            f"recommended space, by approximate pair-coefficient entropy",
            keep=keep, occupations=ranked.occupations)
    else:
        tiers["minimal"] = tiers["recommended"]

    if secondary is not primary:
        tiers["maximal"] = _tier_from_pool(
            "maximal", secondary, spin_2s,
            "the recommended space plus the sigma-bonding framework, for a "
            "calculation that must describe bond breaking as well")
    else:
        tiers["maximal"] = tiers["recommended"]

    notes.extend(primary.notes)
    for t in tiers.values():
        notes.extend(t.feasibility.warnings)

    return Recommendation(
        tiers=tiers,
        recommended="recommended",
        entropies=[float(x) for x in ranked.entropies],
        target_labels=list(primary.target_labels),
        notes=list(dict.fromkeys(notes)),
        mo_coeff=primary.mo_coeff,
        ncore=primary.ncore,
    )
