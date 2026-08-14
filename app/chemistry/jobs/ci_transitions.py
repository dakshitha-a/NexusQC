"""Shared helpers for deriving "orbital_number -> orbital_number (weight)"
dominant-transition strings from a multiconfigurational CI expansion
(CASSCF/CASPT2's leading determinants), reused by orca_runner.py,
bagel_runner.py, and pyscf_runner.py. Each engine prints/exposes an
active-space occupation-count string or vector per configuration, just with
different character conventions (ORCA: plain digits 0/1/2; BAGEL: 2/a/b/.
for doubly-occ/singly-occ-alpha/singly-occ-beta/empty; PySCF: separate
alpha/beta occupied-orbital-index lists from pyscf.fci.addons.large_ci) --
see each engine's own occupancy-string-to-counts converter for that
difference. Everything downstream of a plain list[int] occupation-count
vector (one int per active orbital, ascending orbital order) is shared.

Every number this module deals in is a WEIGHT (= |CI coefficient|^2,
non-negative), not a signed coefficient -- ORCA's own printed CASSCF/TDDFT
"weight" column already is one, but BAGEL and PySCF only expose the signed
coefficient directly, so those two callers square it before handing values
in here (see aggregate_by_configuration below, and each engine runner's own
squaring at the TDDFT/EOM-CCSD single-amplitude call sites that don't need
aggregation).

The "reference" determinant a leading configuration is diffed against is
not assumed to be the lowest-index root/state -- CASSCF roots can come out
of energy order relative to which one is the closed-shell-like reference
and which is the excited one (state-averaging optimizes orbitals jointly,
not per-root energy ordering), so the reference is instead taken to be
whichever single configuration has the highest weight across the ENTIRE
CI-vector block (all states/roots combined) -- this is robust to that
root-flipping regardless of which state index it lands on.
"""
from __future__ import annotations


def aggregate_by_configuration(raw_coefficients: list[tuple[float, list[int]]]) -> list[tuple[float, list[int]]]:
    """BAGEL's and PySCF's (pyscf.fci.addons.large_ci) CI-vector printouts
    are at the raw Slater-determinant level, not the spin-adapted
    configuration-state-function level ORCA's CASSCF table already is --
    an open-shell singlet's two spin arrangements (e.g. BAGEL's
    "22222ab.." / "22222ba.." pair, both with the same |coefficient|) show
    up as two separate lines with the SAME occupation-count vector. Left
    alone, that would make the same orbital pair appear twice in a ranked
    list under two different coefficients. This groups entries that share
    an identical occupation-count vector and sums their squared
    coefficients into one aggregate weight per unique spatial
    configuration -- also the physically correct way to combine them (the
    total probability of a spatial configuration is the sum of its
    determinants' squared amplitudes).

    `raw_coefficients` holds SIGNED CI coefficients (as printed/returned by
    the engine); returns (weight, counts) pairs -- weight always
    non-negative -- sorted by descending weight."""
    grouped: dict[tuple[int, ...], float] = {}
    for coef, counts in raw_coefficients:
        key = tuple(counts)
        grouped[key] = grouped.get(key, 0.0) + coef * coef
    result = [(weight, list(key)) for key, weight in grouped.items()]
    result.sort(key=lambda c: c[0], reverse=True)
    return result


def leading_single_excitations(
    ranked_configs: list[tuple[float, list[int]]],
    reference_counts: list[int],
    n_closed: int,
    max_results: int = 2,
) -> list[tuple[int, int, float]]:
    """ranked_configs: (weight, occupation_counts) pairs for ONE state,
    weight = |CI coefficient|^2 (non-negative), already sorted descending
    (caller's responsibility). occupation_counts is one int (0/1/2) per
    active orbital, in ascending active-orbital order (position 0 = lowest
    active orbital, i.e. orbital number n_closed + 1).

    If the state's own single largest-weight config IS the reference
    itself, returns [] immediately -- this state has essentially no
    single-excitation character (it's the closed-shell-like reference
    state), so there's nothing to search further down its list for; a tiny,
    near-noise contributor further down would be a misleading "dominant
    transition" for a state that fundamentally doesn't have one.

    Otherwise returns up to max_results (source_orbital_1based,
    target_orbital_1based, weight) tuples, one per config that is a clean
    single excitation relative to `reference_counts` (exactly one position
    with a lower count -- the source/hole -- and exactly one with a higher
    count -- the target/particle). A config that differs from the
    reference by more than a single orbital pair (a double+ excitation, not
    representable as one clean source->target pair) is skipped entirely
    rather than mischaracterized -- it does not count toward max_results,
    so the search continues to the next-ranked config."""
    if ranked_configs and ranked_configs[0][1] == reference_counts:
        return []
    results: list[tuple[int, int, float]] = []
    seen_pairs: set[tuple[int, int]] = set()
    for weight, counts in ranked_configs:
        if len(results) >= max_results:
            break
        sources = [i for i, (c, r) in enumerate(zip(counts, reference_counts)) if c < r]
        targets = [i for i, (c, r) in enumerate(zip(counts, reference_counts)) if c > r]
        if len(sources) == 1 and len(targets) == 1:
            pair = (n_closed + sources[0] + 1, n_closed + targets[0] + 1)
            # A lower-ranked config landing on a pair already reported (e.g.
            # a near-degenerate spin-coupling partner that wasn't already
            # merged by aggregate_by_configuration) adds no new information
            # -- skip it and keep looking further down the ranked list
            # instead of showing the same orbital pair twice.
            if pair in seen_pairs:
                continue
            seen_pairs.add(pair)
            results.append((pair[0], pair[1], weight))
    return results


def format_dominant(transitions: list[tuple[int, int, float]], threshold: float = 0.1) -> str | None:
    """Up to 2 transitions, formatted 'src->tgt (weight)' with weight
    (= |CI coefficient|^2) rounded to 2 decimals; the second is included
    only if its weight is >= threshold -- an insignificant runner-up isn't
    worth cluttering the table with. `transitions` must already be ranked
    by descending weight."""
    if not transitions:
        return None
    parts = [f"{s}->{t} ({w:.2f})" for s, t, w in transitions[:1]]
    if len(transitions) > 1 and transitions[1][2] >= threshold:
        s, t, w = transitions[1]
        parts.append(f"{s}->{t} ({w:.2f})")
    return ", ".join(parts)
