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

The per-atom vectors are unbounded arrays (three floats per atom, per entry)
and are listed in facts.BULK_FIELDS so they are never rendered into an LLM
context. The scalar-per-entry lists this module derives alongside them --
norms, gaps, oscillator strengths -- are small, bounded by the number of
states asked for, and are what an agent actually needs to answer "how
strongly are these states coupled along the scan".
"""
from __future__ import annotations

from typing import Any, Optional, Sequence

# States and pairs are 1-based INCLUDING the ground state everywhere in
# these results: state 1 is S0, and the pair [1, 2] is the S0/S1 coupling.
# Each engine converts to its own indexing at its own input-building
# boundary and nowhere else. Note this is NOT the convention of the older
# scalar `target_state` parameter (still used by opt/freq/opt_freq/neb_ts),
# where 0 or absent means the ground state.


def coupling_result(couplings: Sequence[dict], state_pairs: Sequence[Sequence[int]],
                    **extra: Any) -> dict:
    """The summary dict for a single_point/nac job, however many pairs."""
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
        **extra,
    }


def gradient_result(gradients: Sequence[dict], target_states: Sequence[int],
                    **extra: Any) -> dict:
    """The summary dict for a single_point/grad job, however many states."""
    return {
        "gradients": list(gradients),
        "target_states": [int(s) for s in target_states],
        "n_states_computed": len(gradients),
        "gradient_norms_hartree_per_bohr": [
            g.get("gradient_norm_hartree_per_bohr") for g in gradients
        ],
        "state_energies_hartree": [g.get("energy_hartree") for g in gradients],
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
