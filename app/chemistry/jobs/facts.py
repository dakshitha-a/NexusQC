"""The canonical vocabulary every completed job's summary is written in.

Before this module each runner invented its own key names, and the same
physical quantity had four of them: a ground-state energy was
`state_energies_hartree[0]` in a BAGEL CASSCF job,
`ground_state_ccsd_energy_hartree` in EOM-CCSD, `ground_state_energy_hartree`
in TDDFT and `final_energy_hartree` in an optimization. `casscf_energy_hartree`
was written as null while the value it names sat in `state_energies_hartree[0]`.
`n_states` counted state-averaged roots including the ground state for a
multireference method and excited states above it for a single-reference one,
under one key. Nothing named the HOMO at all; it could only be recovered by
reading a 132-row orbital table.

That cost real accuracy, not just tokens. Asked to tabulate ground-state
energies across five methods, the agent reported an active space of (6e,6o) for
a job whose spec says twelve electrons in nine orbitals, and then reasoned at
length about why "a small (6e,6o) active space" behaves as it does. It had
never received the number.

`canonicalize` runs at the one point where a result is persisted
(`base.write_result`), so what lands in result.json is already canonical and
every reader -- the agent, the query tool, the plot field paths, the frontend --
sees one name per quantity. This is deliberately NOT a read-time adapter: there
is one taxonomy on disk, not two with a translation layer between them, per the
project's standing rule against running a legacy and a current shape side by
side.

It also leaves `_resolve_field_path`'s contract intact. That function consults
no schema of known names ahead of a job's real summary, and it still doesn't.
The names it introspects simply became consistent, because that is what got
written.

**Where the boundary is, exactly.** `canonicalize` runs in `write_result`, so
a *stored* result is canonical and everything that reads one -- the agent, the
query tool, the plot field paths, the HTTP routes, the frontend -- sees only
canonical names. A runner function's direct return value is not yet
canonicalized: `pyscf_runner.run_casscf(...)["summary"]` still says
`casscf_energy_hartree`, because normalizing at the point of persistence was
worth far more than editing forty summary literals across three runners and
risking a typo in one of them. Nothing in the application consumes a runner's
return value except the worker that immediately persists it, so the only place
this seam is visible is a test that calls a runner directly (tests/backend's
opt_01, active_01 and p8_01 do, deliberately, and assert the runner's own key
names). If that ever stops being true -- if some new caller wants a summary
without storing it -- call `canonicalize` there too. It is idempotent, so a
double application is harmless.
"""

from __future__ import annotations

from typing import Any, Optional

# --- Fields that are stored but must never render as values into an LLM -----
#
# Each of these is an unbounded array. `orbital_table` alone measured 83% of an
# entire six-job conversation, at ~25,000 characters a copy, refetched up to
# three times for the same job. They stay in result.json -- the job drawer, the
# MO viewer and the cube endpoint all read them from there -- but a text
# rendering shows their shape (`orbital_table[132 rows]`) and the agent asks
# for a window (check_job_status with `fields`) when it actually needs one.
BULK_FIELDS: frozenset = frozenset({
    "orbital_table",
    "normal_modes",
    "gradient_hartree_per_bohr",
    "nac_hartree_per_bohr",
    "state_energies_per_image",
    "pilot_orbital_entropies",
    "mo_energies_eV",
    "reduced_mass_amu",
})

# --- One name per quantity --------------------------------------------------
#
# Ordered, because the first alias present and non-null wins. `energy_hartree`
# trails the more specific names so a job carrying both keeps the one that says
# what it actually is.
_TOTAL_ENERGY_ALIASES = (
    "final_energy_hartree",
    "ground_state_energy_hartree",
    "ground_state_ccsd_energy_hartree",
    # The correlated/on-top totals come BEFORE casscf_energy_hartree, since
    # a job that reports both is a job whose answer is the corrected number
    # -- the CASSCF value is the reference it was built on, not the result.
    "nevpt2_energy_hartree",
    "mcpdft_energy_hartree",
    "lpdft_energy_hartree",
    "casscf_energy_hartree",
    "caspt2_energy_hartree",
    "electronic_energy_hartree",
    "energy_hartree",
)

# Flat one-to-one renames. Everything not listed here and not an energy alias
# keeps the name it already had, because most names were already unambiguous
# (`frequencies_cm-1`, `oscillator_strengths`, `zero_point_energy_hartree`).
# Renaming those would have broken `spectrum_source` and the inline charts for
# no gain.
_RENAMES = {
    "optimized_molecule": "optimized_geometry",
}

OCCUPANCY_THRESHOLD = 0.5
"""Above this an orbital counts as occupied.

A closed-shell table has occupancies of exactly 2.0 and 0.0 and a spin-resolved
one has 1.0 and 0.0, so any threshold in between works for those. What forces
an explicit constant is the CASSCF natural-orbital table, whose active-space
occupancies are genuinely fractional -- 1.94, 0.06 -- and where "occupied" is a
choice rather than a reading. There was no shared threshold anywhere in the
codebase to reuse.
"""

_ORBITAL_TABLE_NOTES = {
    "natural": (
        "Natural orbitals with active-space occupation numbers rather than integer "
        "HF-style occupancies: core orbitals show 2, active orbitals their "
        "natural-orbital occupation, virtuals 0. Character (sigma/pi/n/sigma*/pi*) and "
        "dominant localized atom are best-effort -- sigma vs pi from the orbital's "
        "symmetry about the molecular plane, lone-pair vs bonding from Mulliken "
        "populations. diffuse_fraction is how much density lies outside 1.5 van der "
        "Waals radii of every atom; above 0.5 an orbital is flagged diffuse and "
        "reported without an atom localization, since a population analysis of a "
        "function centred nowhere describes nothing. That is a measure of spatial "
        "extent, not a Rydberg assignment."
    ),
    "canonical": (
        "Canonical molecular orbitals with integer occupancies. Character and dominant "
        "localized atom are best-effort, as is diffuse_fraction (density outside 1.5 van "
        "der Waals radii of every atom; above 0.5 an orbital is flagged diffuse and "
        "reported without a localization)."
    ),
}
"""The orbital-table caveats, once, keyed by table kind.

These used to be written into every job's summary as a per-job string, which
put 1.7 KB of identical prose into context on every single fetch of every job.
The table kind is stored instead and the prose is looked up only when the
orbital table is genuinely under discussion.
"""

BAGEL_ACTIVE_ORBITAL_ENERGY_NOTE = (
    "BAGEL's molden export writes energy_eV = 0.0 for every active-space orbital: a "
    "multi-configurational active orbital has no single-particle Fock eigenvalue, "
    "unlike ORCA's and PySCF's CASSCF exports, which report a generalized-Fock-based "
    "value there. This is confirmed in the raw .molden file and is not a parsing gap."
)


def _first_present(summary, names):
    for name in names:
        if name in summary and summary[name] is not None:
            return name, summary[name]
    return None, None


def _as_float(value):
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    if out != out or out in (float("inf"), float("-inf")):
        return None
    return out


def frontier_orbitals(orbital_table) -> dict:
    """HOMO and LUMO index, energy and gap, derived once from an orbital table.

    The energies are nullable, and that is the whole point of doing this here
    rather than leaving it to whoever reads the table.

    A BAGEL CASSCF molden export writes energy_eV = 0.0 for every active-space
    orbital. Since the HOMO of such a job IS an active orbital, the obvious
    derivation returns 0.0 -- a plausible-looking float that is not an energy.
    Handing that to the model would be the app manufacturing exactly the class
    of confident, baseless number this vocabulary exists to stop it inventing.
    An orbital energy of exactly 0.0 does not otherwise occur, so it is read as
    "absent" and the reason travels with it.

    Indices are 1-based, matching what the MO viewer and every user-facing
    number in this app use.
    """
    if not isinstance(orbital_table, list) or not orbital_table:
        return {}

    rows = [r for r in orbital_table if isinstance(r, dict) and r.get("index") is not None]
    if not rows:
        return {}

    # A spin-resolved table holds two interleaved ladders; a frontier taken
    # across both would pair an alpha HOMO with a beta LUMO. Group first, then
    # keep the channel whose HOMO actually lies highest.
    spins = {r.get("spin") for r in rows}
    if len(spins) > 1:
        groups = [[r for r in rows if r.get("spin") == s]
                  for s in sorted(spins, key=lambda x: str(x))]
    else:
        groups = [rows]

    best: dict = {}
    for group in groups:
        group = sorted(group, key=lambda r: r["index"])
        occupied = [r for r in group
                    if (_as_float(r.get("occupancy")) or 0.0) > OCCUPANCY_THRESHOLD]
        if not occupied:
            continue
        homo = occupied[-1]
        virtuals = [r for r in group if r["index"] > homo["index"]]
        lumo = virtuals[0] if virtuals else None

        homo_e = _as_float(homo.get("energy_eV"))
        lumo_e = _as_float(lumo.get("energy_eV")) if lumo else None
        # Exactly zero means "the export had nothing to write here".
        homo_e = None if homo_e == 0.0 else homo_e
        lumo_e = None if lumo_e == 0.0 else lumo_e

        candidate = {
            "homo_index": homo["index"],
            "lumo_index": lumo["index"] if lumo else None,
            "homo_energy_eV": homo_e,
            "lumo_energy_eV": lumo_e,
            "homo_lumo_gap_eV": (lumo_e - homo_e)
                                if (homo_e is not None and lumo_e is not None) else None,
        }
        if not best:
            best = candidate
        elif candidate["homo_energy_eV"] is not None and (
            best.get("homo_energy_eV") is None
            or candidate["homo_energy_eV"] > best["homo_energy_eV"]
        ):
            best = candidate

    if best and best.get("homo_energy_eV") is None:
        best["frontier_energy_unavailable"] = (
            "The orbital export carries no eigenvalue for the frontier orbital, so its "
            "energy is not available. The index and occupancy are."
        )
    return best


def _orbital_table_kind(orbital_table) -> str:
    """Whether a table holds natural orbitals, read from the occupancies.

    Decided from the numbers rather than from the runner's prose note. The
    note is not a reliable signal: EOM-CCSD's says these are "the ground-state
    HF reference orbitals ... not correlated natural orbitals", so a substring
    test for "natural orbital" labels the one table that definitely isn't one.
    A fractional occupancy, on the other hand, is what actually distinguishes
    the two, and it cannot be phrased the other way round.
    """
    if not isinstance(orbital_table, list):
        return "canonical"
    for row in orbital_table:
        if not isinstance(row, dict):
            continue
        occ = _as_float(row.get("occupancy"))
        if occ is None:
            continue
        if min(abs(occ - n) for n in (0.0, 1.0, 2.0)) > 1e-3:
            return "natural"
    return "canonical"


def _state_counts(summary) -> dict:
    """`n_states_total` and `n_excited_states`, both explicit.

    Derived from the arrays that are actually present rather than from the
    method family, because the arrays cannot disagree with themselves. The
    submitted `n_states` parameter is the ambiguous one: for CASSCF and CASPT2
    it counts state-averaged roots INCLUDING the ground state, and for TDDFT it
    counts excited states above a separate ground state. One key, two meanings,
    and reading it without knowing the method family is how a correct two-root
    CASSCF job got reported as defective for "only reporting one excitation".
    """
    out: dict = {}
    states = summary.get("state_energies_hartree")
    excitations = summary.get("excitation_energies_eV")

    if isinstance(states, list) and states:
        out["n_states_total"] = len(states)
    if isinstance(excitations, list):
        out["n_excited_states"] = len(excitations)

    if "n_states_total" in out and "n_excited_states" not in out:
        out["n_excited_states"] = max(out["n_states_total"] - 1, 0)
    elif "n_excited_states" in out and "n_states_total" not in out:
        out["n_states_total"] = out["n_excited_states"] + 1
    return out


def _align_to_excited_states(value, n_total, n_excited):
    """Re-index a per-state array so entry i always describes state i+1.

    BAGEL writes `dominant_transitions` with one slot per state and None in the
    ground-state slot; PySCF's TDDFT writes one entry per excited state and no
    ground-state slot at all. Same key, two indexing conventions, so `[0]` meant
    different things depending on which engine had run.
    """
    if not isinstance(value, list) or n_total is None or n_excited is None:
        return value
    if len(value) == n_total == n_excited + 1 and value and value[0] is None:
        return value[1:]
    return value


_PER_EXCITED_STATE_FIELDS = (
    "dominant_transitions",
    "oscillator_strengths",
    "excitation_wavelengths_nm",
)


def canonicalize(summary, spec=None):
    """Rewrite one runner's summary into the canonical vocabulary.

    Total by construction: an unrecognized key is passed through untouched, so
    a runner growing a new field does not need to be registered here first, and
    a master job's seed summary survives unchanged.
    """
    if not isinstance(summary, dict) or not summary:
        return summary

    out = dict(summary)

    # One energy name. Every alias is removed afterwards, so exactly one key
    # holds the value and there is never a pair that can drift apart.
    source, value = _first_present(out, _TOTAL_ENERGY_ALIASES)
    if source is not None:
        out["total_energy_hartree"] = value
    for alias in _TOTAL_ENERGY_ALIASES:
        out.pop(alias, None)

    states = out.get("state_energies_hartree")
    if out.get("total_energy_hartree") is None and isinstance(states, list) and states:
        # A state-averaged job reports no scalar energy at all; its ground state
        # is the first root. This is the case that made `casscf_energy_hartree`
        # read as null while the value sat one key away.
        out["total_energy_hartree"] = states[0]

    for old, new in _RENAMES.items():
        if old in out:
            out[new] = out.pop(old)

    counts = _state_counts(out)
    out.update(counts)
    out.pop("n_states", None)

    n_total = counts.get("n_states_total")
    n_excited = counts.get("n_excited_states")
    for field in _PER_EXCITED_STATE_FIELDS:
        if field in out:
            out[field] = _align_to_excited_states(out[field], n_total, n_excited)

    # A runner that computed the gap from a mean-field object it had in hand
    # knows better than a table reading, so an existing value wins.
    frontier = frontier_orbitals(out.get("orbital_table"))
    for key, val in frontier.items():
        if out.get(key) is None:
            out[key] = val

    # The 1.7 KB of shared caveat prose becomes a kind, looked up on demand.
    out.pop("orbital_table_note", None)
    if "orbital_table" in out:
        kind = _orbital_table_kind(out["orbital_table"])
        out["orbital_table_kind"] = kind
        if kind == "natural" and (spec or {}).get("engine") == "bagel":
            out.setdefault("frontier_energy_unavailable", BAGEL_ACTIVE_ORBITAL_ENERGY_NOTE)

    return out


def orbital_table_note(kind) -> str:
    """The caveat prose for a table kind, for the one place that shows a table."""
    return _ORBITAL_TABLE_NOTES.get(kind or "canonical", _ORBITAL_TABLE_NOTES["canonical"])
