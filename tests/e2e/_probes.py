"""Test-probe sizing policy and the (task, subtype) x engine matrix, as data.

PROBE SIZING IS A DELIBERATE TWO-TIER CHOICE, not an oversight.

The default everywhere is water / HF / STO-3G -- the smallest meaningful
system and basis, which is what a functional or rendering check actually
needs. But a trivial PySCF job reaches "completed" faster than any
polling loop can observe it in a transient state. That is not a guess:
tests/backend/perf_03_jobmanager_cap_enforcement.py's own docstring
records that this is exactly why the per-user concurrency cap test was
originally inconclusive, and that it only became conclusive after
switching to a genuinely slow probe.

So anything that must OBSERVE A TRANSIENT -- pending/queueing, the
concurrency cap, the live log tail, cancel, orphan reconciliation, live
NEB frames -- uses SLOW or MEDIUM instead. Same small molecule, same
minimal basis; only the method is heavier.
"""
from __future__ import annotations

# --------------------------------------------------------------------------
# Probes
# --------------------------------------------------------------------------

FAST = {
    "molecule": "water",
    "params": {"method": "hf", "basis": "sto-3g"},
    "note": "seconds; the default for every correctness/rendering check",
}

MEDIUM = {
    "molecule": "benzene",
    "params": {"method": "hf", "basis": "6-31g"},
    "note": (
        "tens of seconds; documented in sec_08b as reliably still `running` at "
        "the next status check, unlike the water/HF/STO-3G probe which was "
        "confirmed already completed before the very next poll"
    ),
}

# P2B.6: nothing imports FAST/MEDIUM/SLOW_ORCA/SLOW_BAGEL (same orphaned
# status as ELICITATION_NEGATIVES above), but unlike that table their
# `job_type` key is one line from the migrated MATRIX and read as a miss if
# left alone -- these two folded `method` into `params`, matching FAST/
# MEDIUM's shape, since "casscf" needed no other change to be a v2 method.
SLOW_ORCA = {
    "molecule": "water",
    "engine": "orca",
    "params": {"method": "casscf", "basis": "sto-3g", "active_electrons": 4,
               "active_orbitals": 4, "n_states": 1},
    "note": (
        "~15s on this host; energy verified against PySCF's own CASSCF to "
        "1.7e-8 Ha. The established probe for observing transients."
    ),
}

SLOW_BAGEL = {
    "molecule": "water",
    "engine": "bagel",
    "params": {"method": "casscf", "basis": "sto-3g", "active_electrons": 4,
               "active_orbitals": 4, "n_states": 1},
    "note": (
        "minutes on this host -- BAGEL/MKL here is documented as abnormally "
        "slow (~80-96s per CASSCF macro-iteration for a trivial system). "
        "Comfortably outlasts any observation window without converging."
    ),
}

# --------------------------------------------------------------------------
# The job matrix
# --------------------------------------------------------------------------
# tier 1 = blocks deployment, 2 = spot-check, 3 = attempt and classify
# (BAGEL paths are tier 3 because BAGEL/MKL flakiness on this host is ENV,
#  not CODE -- see _expected.py's taxonomy.)

MATRIX = [
    # id, task, subtype, engine, tier, params, prompt-shaping notes
    #
    # P2B.6: migrated off the v1 job_type vocabulary. Every cell's `method`
    # (level of theory) is now always in `params`, even where v1 left it
    # implicit in the job_type string itself (the four CASSCF/CASPT2 energy
    # cells, M09-M12, and the two EOM-CCSD cells, M16-M17). `scan_job_type`
    # is dropped from M21/M22's params -- P2B.4 retired it as a stored
    # param; the master job's resolved runner key is still visible, but
    # only via the master job's own summary (see naming.py/base.py), never
    # as an input the caller supplies.
    ("M01", "single_point", "gs", "pyscf", 1, {"method": "hf", "basis": "sto-3g"}, ""),
    ("M02", "single_point", "gs", "orca",  1, {"method": "hf", "basis": "sto-3g"}, ""),
    ("M03", "opt", "min", "pyscf", 1, {"method": "hf", "basis": "sto-3g"}, ""),
    ("M04", "opt", "min", "orca",  2, {"method": "hf", "basis": "sto-3g"}, ""),
    ("M05", "opt", "min", "bagel", 3,
     {"method": "casscf", "basis": "sto-3g", "active_electrons": 4, "active_orbitals": 4},
     "BAGEL geo-opt is casscf/caspt2 only; HF/DFT must raise. XN-08."),
    ("M06", "freq", "", "pyscf", 1, {"method": "hf", "basis": "sto-3g"},
     "no IR intensities on PySCF -> XN-07"),
    ("M07", "freq", "", "orca",  2, {"method": "hf", "basis": "sto-3g"},
     "HAS IR intensities; plot(kind='ir') must succeed here"),
    ("M08", "freq", "", "bagel", 3, {"method": "hf", "basis": "sto-3g"},
     "HF-reference numerical Hessian only. XN-08."),
    ("M09", "single_point", "gs", "pyscf", 1,
     {"method": "casscf", "basis": "sto-3g", "active_electrons": 4, "active_orbitals": 4},
     "XN-03"),
    ("M10", "single_point", "gs", "orca",  1,
     {"method": "casscf", "basis": "sto-3g", "active_electrons": 4, "active_orbitals": 4,
      "want_oscillator_strengths": True},
     "MECHANICAL ROUTING: want_oscillator_strengths must send this to ORCA "
     "even if the user never says 'ORCA'. Also the SLOW probe."),
    ("M11", "single_point", "gs", "bagel", 3,
     {"method": "casscf", "basis": "sto-3g", "active_electrons": 4, "active_orbitals": 4}, ""),
    ("M12", "single_point", "gs", "bagel", 3,
     {"method": "caspt2", "basis": "sto-3g", "active_electrons": 4, "active_orbitals": 4},
     "BAGEL-only; any other engine must be refused. XN-04."),
    ("M13", "single_point", "ee", "pyscf", 1,
     {"method": "hf", "basis": "sto-3g", "n_states": 5, "use_tda": True},
     "TDA on an HF reference IS CIS"),
    ("M14", "single_point", "ee", "pyscf", 2,
     {"method": "dft", "basis": "sto-3g", "n_states": 5, "functional": "b3lyp"},
     "method=dft must make `functional` required and elicited"),
    ("M15", "single_point", "ee", "orca",  2,
     {"method": "hf", "basis": "sto-3g", "n_states": 5}, ""),
    ("M16", "single_point", "ee", "orca",  2,
     {"method": "eom_ccsd", "basis": "sto-3g", "n_states": 3},
     "default engine is ORCA precisely because PySCF has no oscillator strengths"),
    ("M17", "single_point", "ee", "pyscf", 2,
     {"method": "eom_ccsd", "basis": "sto-3g", "n_states": 3},
     "explicit engine request; energies only -> XN-02"),
    ("M18", "single_point", "gs", "pyscf", 1,
     {"method": "hf", "basis": "sto-3g", "orbital_indices": [3, 4, 5]},
     "orbital_indices are 1-BASED everywhere a user or the LLM sees them. NOTE: "
     "orbital_indices carries no required_when in registry2/params.py, so nothing "
     "mechanically forces the agent to set it -- if the card's params come back without "
     "it, EXPECTED_SUMMARY_KEYS still passes on energy_hartree alone with no orbitals "
     "actually rendered. Check the approval card's params for orbital_indices "
     "explicitly, not just the summary-keys assertion."),
    ("M19", "single_point", "gs", "orca",  2,
     {"method": "hf", "basis": "sto-3g", "orbital_indices": [3, 4, 5]},
     "same orbital_indices caveat as M18"),
    ("M20", "single_point", "gs", "bagel", 3,
     {"method": "hf", "basis": "sto-3g", "orbital_indices": [3, 4, 5]},
     "XN-05. Same orbital_indices caveat as M18"),
    ("M21", "pes_1d", "", "pyscf", 1,
     {"n_points": 5, "method": "hf", "basis": "sto-3g",
      "coordinate": {"type": "bond", "atoms": [1, 2]}, "scan_range": [0.8, 1.4]},
     "1-based atom numbering"),
    ("M22", "pes_1d", "", "orca",  2,
     {"n_points": 5, "method": "hf", "basis": "sto-3g",
      "coordinate": {"type": "bond", "atoms": [1, 2]}, "scan_range": [0.8, 1.4]}, ""),
    ("M23", "neb_ts", "", "orca",  3,
     {"method": "hf", "basis": "sto-3g", "preopt": True, "n_images": 6},
     "preopt has NO default -- must be elicited. Needs an end molecule. XN-09."),
    ("M24", "blind", "", "orca",  2, {}, "agent composes raw_input_text itself"),
    ("M25", "blind", "", "bagel", 3, {}, "raw BAGEL JSON"),
    ("M26", "cas_reco", "autocas", "pyscf", 1,
     {"method": "casscf", "basis": "sto-3g", "n_states": 3},
     "PySCF-only; any other engine must be refused"),
    ("M27", "single_point", "grad", "pyscf", 1, {"method": "hf", "basis": "sto-3g"},
     "Phase 5. ground-state gradient, no target_state"),
    ("M28", "single_point", "grad", "orca", 2,
     {"method": "dft", "basis": "sto-3g", "functional": "pbe0", "target_state": 1, "n_states": 3},
     "Phase 5. excited-state gradient; PBE0 not B3LYP -- B88-containing functionals are refused "
     "here (see docs/PARSER_GAPS.md), so this cell must NOT be B3LYP/BLYP"),
    ("M29", "single_point", "nac", "pyscf", 1,
     {"method": "casscf", "basis": "sto-3g", "active_electrons": 4, "active_orbitals": 4,
      "n_states": 2, "state_pairs": [[1, 2]]},
     "Phase 5. only NAC path PySCF has (SA-CASSCF)"),
    ("M30", "single_point", "nac", "orca", 2,
     {"method": "dft", "basis": "sto-3g", "functional": "pbe0", "n_states": 3, "state_pairs": [[1, 2]]},
     "Phase 5. ground-to-excited only on ORCA hf/dft -- state_pairs must include state 1 (ground)"),
]

# Required-param elicitation negatives: for each, the prompt deliberately
# omits the named param and the agent must ASK rather than guess.
#
# P2B.6: NOT migrated to the v2 (task, subtype) vocabulary, on purpose.
# Nothing imports this table -- `e2e_18_elicitation.py` already covers this
# ground natively in v2, with its own hardcoded scenarios against
# registry2.params.PARAMS_BY_NAME directly, and was written after this list.
# Left in its original v1 shape as a record of what it once drove, not
# migrated for cosmetic consistency with MATRIX. One entry is worth flagging
# for whoever next touches this: E05 (mo_visualization/orbital_indices) has
# no v2 equivalent -- `orbital_indices` carries no `required_when` in
# registry2/params.py (confirmed via `missing_required("single_point", "gs",
# "hf", "pyscf", {})`, which returns nothing for it), so there is no
# mechanical registry hook that forces asking for it. Under v2, requesting
# an MO visualization without naming which orbitals just runs a plain
# single-point energy; whether the agent still asks is a prompting/model
# behavior, not something this table's mechanism (a required-param check)
# can express or test.
ELICITATION_NEGATIVES = [
    ("E01", "single_point", "basis"),
    ("E02", "casscf", "active_electrons"),
    ("E03", "casscf", "active_orbitals"),
    ("E04", "tddft", "n_states"),
    ("E05", "mo_visualization", "orbital_indices"),
    ("E06", "neb_ts", "preopt"),
    ("E07", "tddft", "functional"),  # only when method=dft
    ("E08", "geometry_optimization", "active_electrons"),  # only when method=casscf
]

# Engine pairings that must be REFUSED outright by registry2 (route_engine/
# supports), regardless of how the request is phrased.
#
# P2B.6: migrated from v1 job_type strings to method/task/subtype -- these
# are now the actual arguments `route_engine`/`supports` take, not a single
# runner-key string. `phrase` is kept as its own field, separate from task,
# because the prompt text still needs to read as something a person would
# say ("Run a CASPT2 calculation..."), which is no longer always the same
# word as the task name once task/subtype and method are split apart.
#
# D08 (v1: "single_point" refused on bagel) is DROPPED, not migrated -- it
# is not a migration bug, it is a real, verified behavior change. Under v1,
# registry.py's ALLOWED_ENGINES excluded bagel from plain single points as
# an app-level policy choice, independent of physical capability. Under
# v2's capability-driven model there is no such extra restriction:
# `supports("bagel", "hf", "single_point", "gs")` returns `supported=True`
# (BAGEL's MethodCaps row for hf has `energy=True`), so BAGEL is a
# legitimate engine for a plain single-point HF energy now. Per this
# project's no-legacy-compatibility principle, that is not something to
# quietly restore to match the old table -- v2 tells the truth about what
# is runnable rather than layering an artificial UX restriction on top of
# it, and this row would just be a false claim if kept.
DISALLOWED_PAIRINGS = [
    ("D01", "a CASPT2 calculation", "caspt2", "single_point", "gs", "orca",
     "ORCA has no CASPT2 at all -- it has NEVPT2"),
    ("D02", "a CASPT2 calculation", "caspt2", "single_point", "gs", "pyscf", ""),
    ("D03", "a NEB-TS transition state search", None, "neb_ts", "", "pyscf",
     "PySCF has no native NEB and this app doesn't build one"),
    ("D04", "a NEB-TS transition state search", None, "neb_ts", "", "bagel", ""),
    ("D05", "an active space recommendation", "casscf", "cas_reco", "autocas", "orca", ""),
    ("D06", "an active space recommendation", "casscf", "cas_reco", "autocas", "bagel", ""),
    ("D07", "an EOM-CCSD calculation", "eom_ccsd", "single_point", "ee", "bagel", ""),
]


def tier(n: int) -> list:
    return [row for row in MATRIX if row[4] == n]
