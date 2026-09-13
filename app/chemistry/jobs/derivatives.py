"""One result shape for multi-state gradients and multi-pair couplings.

All three engines can now return several derivatives from one job -- BAGEL
from a single `forces` block with an entry per target, PySCF from repeated
kernel calls against one converged wavefunction, ORCA from one process per
target -- and all three must hand back the same thing, because a caller
reading a result should never have to know which engine produced it to know
which keys exist.

Built here rather than in each runner because assembling the same dict in
three places is precisely the failure this work exists to fix. The parser
bug that prompted it (bagel_runner's `sections[-1]`, which reported the
last gradient block beside the first pair's energy gap) survived as long as
it did because nothing in the codebase stated what a coupling result was
supposed to look like.

Two shapes, deliberately parallel:

  couplings:  [{state_pair, nac_hartree_per_bohr, nac_norm_hartree_per_bohr,
                energy_gap_eV, transition_dipole_au, oscillator_strength}]
  gradients:  [{target_state, gradient_hartree_per_bohr,
                gradient_norm_hartree_per_bohr, energy_hartree}]

Every key is present in every entry from every engine. An engine that does
not compute one of them writes None rather than omitting it, so `.get`
returning None means "this engine does not report it" and never "this
result is from the other engine".

Both result shapes also carry the state ladder the job solved for --
`state_energies_hartree` (absolute, ground state first) and
`excitation_energies_eV` beside it -- because neither a coupling nor a
gradient can be computed without first solving for the states, on any of
the three engines. Reporting the derivative and discarding the energies
made a perfectly ordinary follow-up ("and what were the state energies at
each of those geometries?") unanswerable from a job that had computed
exactly that, and sent the user round a second and third batch to
recover numbers the first one already had. Where an engine prints no
energy gap of its own, the per-pair `energy_gap_eV` is derived from that
same ladder rather than left null.

The per-atom vectors are unbounded arrays (three floats per atom, per entry)
and are listed in facts.BULK_FIELDS so they are never rendered into an LLM
context. The scalar-per-entry lists this module derives alongside them --
norms, gaps, oscillator strengths -- are small, bounded by the number of
states asked for, and are what an agent actually needs to answer "how
strongly are these states coupled along the scan".
"""
from __future__ import annotations

from typing import Any, Optional, Sequence

HARTREE_TO_EV = 27.211386245988

# States and pairs are 1-based INCLUDING the ground state everywhere in
# these results: state 1 is S0, and the pair [1, 2] is the S0/S1 coupling.
# Each engine converts to its own indexing at its own input-building
# boundary and nowhere else. Note this is NOT the convention of the older
# scalar `target_state` parameter (still used by opt/freq/opt_freq/neb_ts),
# where 0 or absent means the ground state.


def excitation_energies_eV(state_energies_hartree: Optional[Sequence[Optional[float]]]):
    """Every state's energy above the ground state, in eV, or None.

    The same derivation each runner had privately (`_excitation_energies_eV`
    in pyscf_runner and bagel_runner). Here as well because a derivative job
    now reports the ladder it solved for, and the eV view of it must be the
    one view, not a fourth copy of the arithmetic.
    """
    states = list(state_energies_hartree or [])
    if len(states) < 2 or states[0] is None:
        return None
    # The ground state is the LOWEST root, not the first-labelled one, and it
    # is the one dropped from the list. For every ladder that comes out
    # ascending those are the same root and this is byte-identical to the
    # `states[1:]` relative to `states[0]` it replaces, which is all of them
    # except MC-PDFT.
    #
    # MC-PDFT is the exception and R-077 is about it: each state's energy is
    # evaluated separately and the states keep the ordinal labels the
    # underlying CASSCF gave them, so they are not guaranteed to come out in
    # ascending order. `run_pdft_family` writes that into the summary as
    # `mcpdft_state_order_note`, and then this function assumed the opposite.
    # A reordered ladder gave a NEGATIVE entry under a name that cannot be
    # negative, and dropped the genuinely excited first-labelled state from
    # the list while keeping the real ground state in it as a 0.0 eV
    # "excitation".
    #
    # Entry i is therefore the i-th state in label order that is not the
    # ground state, which for an ascending ladder is state i+1 as before.
    finite = [e for e in states if e is not None]
    if not finite:
        return None
    e0 = min(finite)
    ground_at = states.index(e0)
    rest = [e for i, e in enumerate(states) if i != ground_at]
    return [None if e is None else (e - e0) * HARTREE_TO_EV for e in rest]


def _state_ladder(state_energies_hartree: Optional[Sequence[Optional[float]]]) -> dict:
    """The `state_energies_hartree`/`excitation_energies_eV` pair that every
    result carrying a solved state ladder reports, or {} when the engine
    genuinely produced none.

    Written once, here, rather than in each runner: an energy the engine
    already computed and then threw away is precisely the gap this module
    exists to close, and six runners assembling the same two keys is how
    they drift apart.

    A ladder that is not in ascending energy order carries a third key
    saying so. That was R-077: MC-PDFT's reordering was documented in
    `docs/QM_CAPABILITIES.md`, recorded in the capability table, and written
    into the summary by `run_pdft_family` -- and by nothing else, so
    `run_gradient`'s PDFT branch and `run_nac` reported the same reorderable
    ladder with no note at all. Deriving the note from the numbers rather
    than from the method name means every summary carrying a ladder gets it,
    including a method nobody has thought to flag yet, and a method that
    could reorder but did not on this particular molecule does not carry a
    warning it did not earn.
    """
    states = [None if e is None else float(e) for e in (state_energies_hartree or [])]
    if not states:
        return {}
    out = {
        "state_energies_hartree": states,
        "excitation_energies_eV": excitation_energies_eV(states),
    }
    finite = [e for e in states if e is not None]
    if len(finite) > 1 and finite != sorted(finite):
        out["state_order_note"] = (
            "These states are not in ascending energy order. They keep the ordinal labels "
            "the underlying wavefunction gave them, so state 1 here is not the lowest one; "
            "the ground state is the lowest energy in the list, and the excitation energies "
            "are measured from it."
        )
    return out


def _fill_energy_gaps(couplings: Sequence[dict],
                      state_energies_hartree: Optional[Sequence[Optional[float]]]) -> list[dict]:
    """Each coupling's `energy_gap_eV`, derived from the ladder when the
    engine did not print one itself.

    An engine's own printed gap always wins: BAGEL prints one per NACME
    section and that is the number it actually coupled with. PySCF and ORCA
    print none, which is why every PySCF coupling on disk carries
    `energy_gap_eV: null` beside a perfectly well determined gap -- the
    state-averaged solve that produced the coupling produced both energies.

    Absolute difference, so a pair written either way round gives the same
    gap. That matches what the existing consistency check in
    tests/backend/grad_01_gradients_and_nac.py already asserts about BAGEL's
    own gaps (S0->S1 + S1->S2 == S0->S2, on absolute values).
    """
    states = list(state_energies_hartree or [])
    out = []
    for coupling in couplings:
        entry = dict(coupling)
        if entry.get("energy_gap_eV") is None:
            pair = entry.get("state_pair") or []
            if len(pair) == 2:
                lo, hi = int(pair[0]) - 1, int(pair[1]) - 1
                if 0 <= lo < len(states) and 0 <= hi < len(states) \
                        and states[lo] is not None and states[hi] is not None:
                    entry["energy_gap_eV"] = abs(states[hi] - states[lo]) * HARTREE_TO_EV
        out.append(entry)
    return out


def coupling_result(couplings: Sequence[dict], state_pairs: Sequence[Sequence[int]],
                    state_energies_hartree: Optional[Sequence[Optional[float]]] = None,
                    **extra: Any) -> dict:
    """The summary dict for a single_point/nac job, however many pairs.

    `state_energies_hartree` is the FULL ladder the job solved for, ground
    state first, 1-based state 1 = S0 -- not only the states named in
    `state_pairs`. A coupling calculation cannot happen without it: every
    engine here solves the state-averaged (or TDDFT) problem first and reads
    the coupling off that wavefunction, so the energies exist in every case
    and used to be discarded at the summary boundary. A user who asked for
    couplings along a scan and then asked where the states went could be
    told, truthfully and uselessly, that the job did not report them.
    """
    couplings = _fill_energy_gaps(couplings, state_energies_hartree)
    return {
        "couplings": list(couplings),
        "state_pairs": [[int(p[0]), int(p[1])] for p in state_pairs],
        "n_pairs": len(couplings),
        # Scalar-per-pair views, aligned with `couplings`, so a reader (or
        # an LLM that must not be handed the vectors) can answer questions
        # about coupling strength without unpacking the bulk field.
        "nac_norms_hartree_per_bohr": [c.get("nac_norm_hartree_per_bohr") for c in couplings],
        "energy_gaps_eV": [c.get("energy_gap_eV") for c in couplings],
        "oscillator_strengths": [c.get("oscillator_strength") for c in couplings],
        **_state_ladder(state_energies_hartree),
        **extra,
    }


def gradient_result(gradients: Sequence[dict], target_states: Sequence[int],
                    state_energies_hartree: Optional[Sequence[Optional[float]]] = None,
                    **extra: Any) -> dict:
    """The summary dict for a single_point/grad job, however many states.

    Two per-state energy views, and the distinction is not cosmetic:

      state_energies_hartree           the FULL ladder the job solved for,
                                       ground state first, one entry per
                                       state -- the same key, meaning the
                                       same thing, as in every energy job
      gradient_state_energies_hartree  one entry per REQUESTED gradient,
                                       aligned with `gradients` and
                                       `target_states`

    The aligned view used to be written under the ladder's name, which made
    a gradient taken on S2 alone report `state_energies_hartree: [E(S2)]`.
    facts.py reads that key to decide how many states a job has and to fill
    `total_energy_hartree` from entry 0, so such a job read back as a
    one-state calculation whose total energy was S2's -- a plausible number
    under a name that means something else.
    """
    return {
        "gradients": list(gradients),
        "target_states": [int(s) for s in target_states],
        "n_states_computed": len(gradients),
        "gradient_norms_hartree_per_bohr": [
            g.get("gradient_norm_hartree_per_bohr") for g in gradients
        ],
        "gradient_state_energies_hartree": [g.get("energy_hartree") for g in gradients],
        **_state_ladder(state_energies_hartree),
        **extra,
    }


def coupling_entry(state_pair: Sequence[int], vector: list[list[float]],
                   norm: Optional[float] = None,
                   energy_gap_eV: Optional[float] = None,
                   transition_dipole_au: Optional[list[float]] = None,
                   oscillator_strength: Optional[float] = None) -> dict:
    """One coupling. `norm` is computed from the vector when not supplied --
    ORCA prints its own ("Norm of the NACs"), BAGEL and PySCF do not."""
    if norm is None:
        norm = sum(v * v for row in vector for v in row) ** 0.5
    return {
        "state_pair": [int(state_pair[0]), int(state_pair[1])],
        "nac_hartree_per_bohr": vector,
        "nac_norm_hartree_per_bohr": float(norm),
        "energy_gap_eV": energy_gap_eV,
        "transition_dipole_au": transition_dipole_au,
        "oscillator_strength": oscillator_strength,
    }


def gradient_entry(target_state: int, vector: list[list[float]],
                   energy_hartree: Optional[float] = None) -> dict:
    """One state's gradient."""
    return {
        "target_state": int(target_state),
        "gradient_hartree_per_bohr": vector,
        "gradient_norm_hartree_per_bohr": sum(v * v for row in vector for v in row) ** 0.5,
        "energy_hartree": energy_hartree,
    }
