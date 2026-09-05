"""Confirm that the recommended space really contains the requested states.

Everything before this module is a prediction: the projector says these
orbitals are the chemically relevant ones, the excited-state branch says the
requested states are made of these, and neither has solved the CI problem the
user will actually run. This closes the loop cheaply, by running a CASCI in the
recommended space and checking that the states are there with the character
they were predicted to have.

It is a CASCI, not a CASSCF. The orbitals are not reoptimised, so this costs a
single CI diagonalisation rather than a self-consistent orbital optimisation --
seconds for the spaces this engine typically recommends. That is enough to
answer the question being asked, which is whether the *space* can hold the
states, not what their converged energies are.

Two failure modes are worth distinguishing and are reported separately:

- **A state is missing.** The requested number of roots came back, but none of
  them has the predicted character. Usually this means an orbital the state
  needs is outside the space.
- **The states are there but reordered.** All the characters are present at
  different root indices than predicted. This is not a defect in the space; it
  is what a state average has to cope with, and it is worth telling the user
  because it changes which root they should ask for.

Two constraints inherited from this project's earlier DMRG work, both recorded
in `scripts/casbench/legacy_cas_reco._pilot_entropies_dmrg`, and both found
the hard way:

- **block2 0.5.3 segfaults** on ``get_orbital_entropies()`` over a multi-root
  MPS. A segfault kills the worker process outright, so no result is ever
  written and the job never reaches a terminal status -- the one job-lifecycle
  failure this project treats as a real defect. Multi-root DMRG energies and
  density matrices are fine; entropies over a multi-root MPS are not, and are
  never requested here.
- **``SymmetryTypes.SZ``, not ``SU2``**: SU2 hits a pybind11 cast bug in this
  build for single-orbital quantities and its fallback returns
  ``NotImplemented``.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

# Above this many CSFs, an exact CASCI stops being cheap and the check either
# moves to DMRG-CI or is skipped and said to be skipped. Chosen so the check
# stays in the seconds range that makes it worth doing by default.
FCI_CSF_LIMIT = 500_000

# How many determinants pyscf's FCI solver builds its initial guess from
# (`fcisolver.pspace_size`, default 400). It is recorded here because a
# "state missing" verdict means two different things either side of it: below,
# the guess spans the space and an absent state really is undescribable;
# above, the state may simply never have been reached. The number is pyscf's
# rather than this engine's, so it is named rather than tuned.
PSPACE_DETERMINANTS = 400


@dataclass
class Verification:
    ran: bool
    method: str                     # "casci" | "dmrg-ci" | "skipped"
    n_roots: int = 0
    energies_ev: list = field(default_factory=list)
    characters: list = field(default_factory=list)
    found: list = field(default_factory=list)      # predicted characters that appeared
    missing: list = field(default_factory=list)    # predicted characters that did not
    reordered: bool = False
    notes: list = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "ran": self.ran, "method": self.method, "n_roots": self.n_roots,
            "energies_ev": [round(float(e), 3) for e in self.energies_ev],
            "characters": list(self.characters),
            "states_found": list(self.found),
            "states_missing": list(self.missing),
            "reordered": self.reordered,
            "notes": list(self.notes),
        }


def _root_characters(mc, mol, targets, nroots, rydberg_detectable):
    """Character of each root's transition from the ground state.

    Delegates to the refinement's implementation rather than repeating it. The
    two were near-identical copies, and the copy here silently missed a fix the
    other received: diffuseness measured as an extent ratio against the active
    space cannot see a diffuse orbital that is inside that space, so a root
    built on one came back "mixed". Two audits of the same space disagreeing
    about the same root is the failure this whole module exists to prevent, so
    there is now one implementation.

    `nroots` is accepted for the caller's signature and not used: the root count
    is read from the solved object, which is the only place it is certain.
    """
    from app.chemistry.cas.refine import _root_characters as _chars

    pi_t = [t for t in targets if t.kind == "pi"]
    lp_t = [t for t in targets if t.kind == "lone_pair"]
    return _chars(mc, mol, pi_t, lp_t, rydberg_detectable)


def verify(mf, recommendation, symbols, coords, *, n_states: int = 1,
           predicted=None, spin_2s: int = 0,
           rydberg_detectable: bool = False) -> Verification:
    """Run a CASCI in the recommended space and check the states are there.

    `predicted` is the list of state characters the excited-state branch
    expects, in order. When it is empty the check still runs and reports what
    it found, which is the useful thing for a ground-state recommendation: it
    confirms the space is solvable and reports the lowest excitations in it.
    """
    from pyscf import mcscf

    from app.chemistry.cas import feasibility
    from app.chemistry.cas.geometry import perceive

    tier = recommendation.tiers[recommendation.recommended]
    ne, no = tier.n_electrons, tier.n_orbitals
    f = feasibility.assess(no, ne, spin_2s)
    nroots = max(1, n_states)

    if f.n_csf == 0:
        return Verification(ran=False, method="skipped", notes=[
            f"({ne}e, {no}o) holds no states of the requested spin, so there "
            f"was nothing to verify."])

    if f.n_csf > FCI_CSF_LIMIT:
        # DMRG-CI would be the route above this, and block2 is installed; it is
        # left for a later step rather than claimed here, because a check that
        # has never been run is not a check. Saying the verification was
        # skipped is the honest outcome, and it is said rather than left for
        # the user to infer from a missing field.
        return Verification(ran=False, method="skipped", notes=[
            f"The recommended space is {f.n_csf:,} CSFs, above the "
            f"{FCI_CSF_LIMIT:,} at which an exact CASCI stops being cheap, so "
            f"it was not verified. The recommendation stands; what has not "
            f"been confirmed is that a CI in it reproduces the predicted "
            f"states."])

    mol = mf.mol
    try:
        mc = mcscf.CASCI(mf, no, ne)

        from app.chemistry.cas.refine import _spin_adapt

        _spin_adapt(mc, mf.mol)  # singlets only; see _solve
        mc.fcisolver.nroots = min(nroots, f.n_csf)
        mc.verbose = 0
        mc.kernel(recommendation.mo_coeff)
    except Exception as exc:                                    # noqa: BLE001
        return Verification(ran=False, method="skipped", notes=[
            f"The verification CASCI did not run ({type(exc).__name__}: {exc}). "
            f"The recommendation is unaffected; it simply has not been "
            f"confirmed."])

    e = np.atleast_1d(np.asarray(mc.e_tot, dtype=float))
    ev = (e - e[0]) * 27.211386245988
    targets = perceive(symbols, np.asarray(coords, float),
                       include_sigma=False).targets
    chars = _root_characters(mc, mol, targets, len(e), rydberg_detectable) \
        if len(e) > 1 else []

    # The same comparison the refinement's state audit uses. This used to be
    # exact string equality, which disagrees with `refine()` about the same
    # state: a root the classifier declines to label sharply comes back as
    # "mixed->pi*", which `characters_compatible` counts as matching "pi->pi*"
    # and `==` does not. Two audits of one space reporting different verdicts
    # is worse than either verdict, because nothing says which to believe.
    from app.chemistry.cas.refine import characters_compatible

    predicted = [p for p in (predicted or []) if p]
    found, missing = [], []
    reordered = False
    for i, want in enumerate(predicted):
        hit = next((j for j, c in enumerate(chars)
                    if characters_compatible(c, want)), None)
        if hit is not None:
            found.append(want)
            if hit != i:
                reordered = True
        else:
            missing.append(want)

    notes = []
    if missing:
        # Whether the verdict can carry a cause depends on whether the solver
        # could see the whole space. A Davidson reaches only what its initial
        # guess spans, pyscf builds that guess from the PSPACE_DETERMINANTS
        # lowest-diagonal determinants, and in a planar molecule the coupling
        # between the a' and a'' blocks is identically zero, so configurations
        # outside the window are not pulled back in however many roots are
        # asked for. On a small space this does not arise, because the guess
        # spans everything: formaldehyde's 16-determinant (6e,4o) finds its
        # A2 n->pi* at root 1. On a large one it does, and "the orbitals are
        # outside the space" and "the solver never looked there" produce the
        # same silence.
        beyond_guess = bool(f.n_csf and f.n_csf > PSPACE_DETERMINANTS)
        notes.append(
            f"{len(missing)} of {len(predicted)} predicted states did not "
            f"appear in the recommended space: {', '.join(missing)}."
            + (
                f" This space holds {f.n_csf:,} configuration state functions, "
                f"more than the {PSPACE_DETERMINANTS} the solver builds its "
                f"initial guess from, so a state can be absent from the roots "
                f"without being absent from the space. Treat this as "
                f"'not found' rather than 'not there'; the refinement tier "
                f"settles it by optimising the orbitals, which a CASCI cannot."
                if beyond_guess else
                f" This space holds {f.n_csf:,} configuration state functions, "
                f"which the solver's initial guess spans, so the state is "
                f"genuinely not describable here. The orbitals it is built "
                f"from are outside the space; the maximal tier is the first "
                f"thing to try."
            )
        )
    if reordered and not missing:
        notes.append(
            "Every predicted state is present, but not in the predicted order. "
            "That is a property of the state average rather than a defect in "
            "the space, and it matters only in that it changes which root to "
            "ask for."
        )
    if predicted and not missing and not reordered:
        notes.append(
            f"All {len(predicted)} predicted states are present in the "
            f"recommended space, in the predicted order.")
    if not predicted:
        notes.append(
            f"A CASCI in the recommended space converged and gave "
            f"{len(e)} state(s). No excited-state prediction was made for this "
            f"recommendation, so there was nothing to check them against.")

    return Verification(
        ran=True, method="casci", n_roots=len(e),
        energies_ev=[float(x) for x in ev], characters=chars,
        found=found, missing=missing, reordered=reordered, notes=notes,
    )
