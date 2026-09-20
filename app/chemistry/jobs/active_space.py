"""What a CASSCF-family job records about the orbitals it made active.

An orbital index in this app is a position in one particular job's orbital
table, 1-based. That single sentence is the contract every function here
serves, and it was learned the hard way: a user read orbital numbers off a
finished job's natural-orbital table, asked for a rerun with two of them
swapped, and the rerun applied the numbers to a fresh SCF's canonical
orbitals, a different ordering, so the job that came back had the wrong
active space and nothing in its result said so. The result only echoed the
list it was given, which made a wrongly applied space look identical to a
right one.

Three things are recorded now, on every engine that can supply them:

- `active_orbital_window`: which rows of THIS job's own table are active.
  After `sort_mo`, natural-orbital canonicalization or BAGEL's own
  ordering, the active orbitals always sit in one contiguous block, so this
  is `[ncore+1 .. ncore+ncas]`. It is the list a later "swap orbital X for
  Y" is made against, and it is present whether or not the user named
  anything.
- `reference_orbital_weights`: for each orbital that STARTED in the active
  space (the user's named list, or the default window of whatever orbitals
  the optimisation began from), how much of it survives in the converged
  active space, as the summed squared overlap with the final active
  orbitals. A retained orbital scores near 1, one the optimiser rotated out
  scores near 0. Row sums are invariant to rotations within the active
  space, so a degenerate pair still scores 1 each.
- `active_space_warning`: present only when a starting orbital's weight
  falls below RETAINED_WEIGHT_THRESHOLD. CASSCF active/inactive rotations
  are non-redundant, so the optimiser is free to replace a requested
  orbital with a lower-energy one; that is legitimate physics, and the
  only defect would be not saying it happened.

Each active row of the table also carries `active: true` and, when a
mapping was computed, `reference_index` and `reference_weight`: the
starting orbital it most resembles and the squared overlap with it.

`reference_job_id` names the table the starting labels index: a source
job's when the orbitals were reused from one, None when the job began from
its own fresh SCF, in which case the labels are positions in that SCF's
canonical ordering, which no table shows and which the warning text says.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

import numpy as np

# Below this share of a starting orbital surviving in the converged active
# space, the optimiser is taken to have rotated it out. 0.5 sits between the
# two regimes seen in practice (near 1 retained, near 0 replaced) and leaves
# a degenerate pair, whose row sums stay near 1, out of the warning.
RETAINED_WEIGHT_THRESHOLD = 0.5


@dataclass
class InitialActiveSpace:
    """The active block a CASSCF-family optimisation started from.

    `coeff` is the AO x ncas block of the starting orbitals, copied before
    the kernel runs; `labels` is the reference-table index of each column
    (the user's named list, or the default window); `reference_job_id` is
    the job whose table those labels index, None for this job's own SCF."""

    coeff: np.ndarray
    labels: list[int]
    reference_job_id: Optional[str] = None


@dataclass
class Mapping:
    """Overlap bookkeeping between starting and converged active orbitals."""

    # For each final active orbital, (best-matching starting label, weight).
    per_final: list[tuple[int, float]] = field(default_factory=list)
    # For each starting label, its total weight in the final active space.
    per_initial: dict[int, float] = field(default_factory=dict)


def window(ncore: int, ncas: int) -> list[int]:
    """The 1-based table rows that are active: `[ncore+1 .. ncore+ncas]`."""
    return list(range(int(ncore) + 1, int(ncore) + int(ncas) + 1))


def overlap_mapping(
    c_init: np.ndarray,
    c_final: np.ndarray,
    init_labels: list[int],
    *,
    s_cross: np.ndarray,
    s_init: Optional[np.ndarray] = None,
    s_final: Optional[np.ndarray] = None,
) -> Mapping:
    """Squared overlaps between the starting and the converged active block.

    `c_init` and `c_final` are AO x n coefficient blocks; `s_cross` is the
    overlap between their AO bases (the plain AO overlap when both live in
    the same basis, `gto.intor_cross('int1e_ovlp', ...)` otherwise). Each
    squared overlap is divided by the two orbitals' own norms, taken in
    `s_init` and `s_final` when given, so a source set read back from a
    file that is not exactly orthonormal still scores a retained orbital
    as 1; omitted, the sets are taken as orthonormal already."""
    c_init = np.asarray(c_init, dtype=float)
    c_final = np.asarray(c_final, dtype=float)
    if c_init.ndim != 2 or c_final.ndim != 2 or c_init.shape[1] != len(init_labels):
        raise ValueError("overlap_mapping: coefficient blocks and labels disagree in shape")
    overlap = c_init.T @ s_cross @ c_final

    def _norms(c: np.ndarray, s: Optional[np.ndarray]) -> np.ndarray:
        if s is None:
            return np.ones(c.shape[1])
        return np.einsum("pi,pq,qi->i", c, s, c)

    weights = overlap**2 / np.outer(
        np.maximum(_norms(c_init, s_init), 1e-12), np.maximum(_norms(c_final, s_final), 1e-12)
    )
    per_final = []
    for j in range(weights.shape[1]):
        i = int(np.argmax(weights[:, j]))
        per_final.append((int(init_labels[i]), float(weights[i, j])))
    per_initial = {int(label): float(weights[i, :].sum()) for i, label in enumerate(init_labels)}
    return Mapping(per_final=per_final, per_initial=per_initial)


def reference_name(reference_job_id: Optional[str]) -> str:
    """How the warning names the table the starting labels index."""
    if reference_job_id:
        return f"job {reference_job_id}'s orbital table"
    return "this job's own fresh SCF orbitals (canonical order, which no table shows)"


def annotate(
    summary: dict,
    orbital_table: list[dict] | None,
    *,
    ncore: int,
    ncas: int,
    requested: list[int] | None = None,
    reference_job_id: Optional[str] = None,
    mapping: Optional[Mapping] = None,
) -> None:
    """Writes the active-space record into a summary and its orbital table.

    Always: `active_orbital_window`, `initial_orbitals_source_job_id`, and an
    `active` flag on every table row. With a named list: the list is echoed
    as `active_space_orbital_indices` (the meaning it has always had, the
    user's numbers against the reference table). With a mapping: the
    per-row reference columns, `reference_orbital_weights`, and the warning
    when something was rotated out."""
    active = window(ncore, ncas)
    summary["active_orbital_window"] = active
    summary["initial_orbitals_source_job_id"] = reference_job_id or None
    if requested:
        summary["active_space_orbital_indices"] = [int(i) for i in requested]

    rows_by_index: dict[int, dict] = {}
    for row in orbital_table or []:
        if not isinstance(row, dict) or row.get("index") is None:
            continue
        row["active"] = int(row["index"]) in active
        # A spin-resolved table would hold two rows per index; a CASSCF
        # table here is spin-free, so the last one wins and that is fine.
        rows_by_index[int(row["index"])] = row

    if mapping is None:
        return

    for position, (label, weight) in zip(active, mapping.per_final):
        row = rows_by_index.get(position)
        if row is not None:
            row["reference_index"] = int(label)
            row["reference_weight"] = round(float(weight), 4)
    summary["reference_orbital_weights"] = {str(k): round(v, 4) for k, v in mapping.per_initial.items()}

    lost = [(label, w) for label, w in mapping.per_initial.items() if w < RETAINED_WEIGHT_THRESHOLD]
    if not lost:
        summary.pop("active_space_warning", None)
        return
    where = reference_name(reference_job_id)
    parts = []
    for label, w in lost:
        parts.append(f"orbital {label} kept weight {w:.2f}")
    replaced = []
    for position, (label, weight) in zip(active, mapping.per_final):
        if weight < RETAINED_WEIGHT_THRESHOLD:
            replaced.append(f"final active orbital {position} is only {weight:.2f} of its best match, orbital {label}")
    text = (
        f"The optimizer did not keep the active space it started from. Against {where}: "
        + "; ".join(parts)
        + " in the converged active space, so it was rotated out."
    )
    if replaced:
        text += " " + "; ".join(replaced) + ", so that row is an orbital that was not in the starting set."
    text += (
        " The energies are those of the converged space, not the requested one. "
        "To hold a specific orbital active, start from orbitals that already have it there "
        "(a job whose table shows it in the active window) or freeze the rotation."
    )
    summary["active_space_warning"] = text
