"""Test-probe sizing policy and the job_type x engine matrix, as data.

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

SLOW_ORCA = {
    "molecule": "water",
    "engine": "orca",
    "job_type": "casscf",
    "params": {"basis": "sto-3g", "active_electrons": 4, "active_orbitals": 4, "n_states": 1},
    "note": (
        "~15s on this host; energy verified against PySCF's own CASSCF to "
        "1.7e-8 Ha. The established probe for observing transients."
    ),
}

SLOW_BAGEL = {
    "molecule": "water",
    "engine": "bagel",
    "job_type": "casscf",
    "params": {"basis": "sto-3g", "active_electrons": 4, "active_orbitals": 4, "n_states": 1},
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
    # id, job_type, engine, tier, params, prompt-shaping notes
    ("M01", "single_point",          "pyscf", 1, {"method": "hf", "basis": "sto-3g"}, ""),
    ("M02", "single_point",          "orca",  1, {"method": "hf", "basis": "sto-3g"}, ""),
    ("M03", "geometry_optimization", "pyscf", 1, {"method": "hf", "basis": "sto-3g"}, ""),
    ("M04", "geometry_optimization", "orca",  2, {"method": "hf", "basis": "sto-3g"}, ""),
    ("M05", "geometry_optimization", "bagel", 3,
     {"method": "casscf", "basis": "sto-3g", "active_electrons": 4, "active_orbitals": 4},
     "BAGEL geo-opt is casscf/caspt2 only; HF/DFT must raise. XN-08."),
    ("M06", "frequency",             "pyscf", 1, {"method": "hf", "basis": "sto-3g"},
     "no IR intensities on PySCF -> XN-07"),
    ("M07", "frequency",             "orca",  2, {"method": "hf", "basis": "sto-3g"},
     "HAS IR intensities; plot_ir_spectrum must succeed here"),
    ("M08", "frequency",             "bagel", 3, {"method": "hf", "basis": "sto-3g"},
     "HF-reference numerical Hessian only. XN-08."),
    ("M09", "casscf",                "pyscf", 1,
     {"basis": "sto-3g", "active_electrons": 4, "active_orbitals": 4}, "XN-03"),
    ("M10", "casscf",                "orca",  1,
     {"basis": "sto-3g", "active_electrons": 4, "active_orbitals": 4,
      "want_oscillator_strengths": True},
     "MECHANICAL ROUTING: want_oscillator_strengths must send this to ORCA "
     "even if the user never says 'ORCA'. Also the SLOW probe."),
    ("M11", "casscf",                "bagel", 3,
     {"basis": "sto-3g", "active_electrons": 4, "active_orbitals": 4}, ""),
    ("M12", "caspt2",                "bagel", 3,
     {"basis": "sto-3g", "active_electrons": 4, "active_orbitals": 4},
     "BAGEL-only; any other engine must be refused. XN-04."),
    ("M13", "tddft",                 "pyscf", 1,
     {"method": "hf", "basis": "sto-3g", "n_states": 5, "use_tda": True},
     "TDA on an HF reference IS CIS"),
    ("M14", "tddft",                 "pyscf", 2,
     {"method": "dft", "basis": "sto-3g", "n_states": 5, "functional": "b3lyp"},
     "method=dft must make `functional` required and elicited"),
    ("M15", "tddft",                 "orca",  2,
     {"method": "hf", "basis": "sto-3g", "n_states": 5}, ""),
    ("M16", "eom_ccsd",              "orca",  2, {"basis": "sto-3g", "n_states": 3},
     "default engine is ORCA precisely because PySCF has no oscillator strengths"),
    ("M17", "eom_ccsd",              "pyscf", 2, {"basis": "sto-3g", "n_states": 3},
     "explicit engine request; energies only -> XN-02"),
    ("M18", "mo_visualization",      "pyscf", 1,
     {"method": "hf", "basis": "sto-3g", "orbital_indices": [3, 4, 5]},
     "orbital_indices are 1-BASED everywhere a user or the LLM sees them"),
    ("M19", "mo_visualization",      "orca",  2,
     {"method": "hf", "basis": "sto-3g", "orbital_indices": [3, 4, 5]}, ""),
    ("M20", "mo_visualization",      "bagel", 3,
     {"method": "hf", "basis": "sto-3g", "orbital_indices": [3, 4, 5]}, "XN-05"),
    ("M21", "pes_scan",              "pyscf", 1,
     {"scan_job_type": "single_point", "n_points": 5, "method": "hf", "basis": "sto-3g",
      "coordinate": {"type": "bond", "atoms": [1, 2]}, "scan_range": [0.8, 1.4]},
     "1-based atom numbering"),
    ("M22", "pes_scan",              "orca",  2,
     {"scan_job_type": "single_point", "n_points": 5, "method": "hf", "basis": "sto-3g",
      "coordinate": {"type": "bond", "atoms": [1, 2]}, "scan_range": [0.8, 1.4]}, ""),
    ("M23", "neb_ts",                "orca",  3,
     {"method": "hf", "basis": "sto-3g", "preopt": True, "n_images": 6},
     "preopt has NO default -- must be elicited. Needs an end molecule. XN-09."),
    ("M24", "custom",                "orca",  2, {}, "agent composes raw_input_text itself"),
    ("M25", "custom",                "bagel", 3, {}, "raw BAGEL JSON"),
    ("M26", "recommend_active_space", "pyscf", 1, {"basis": "sto-3g", "n_states": 3},
     "PySCF-only; any other engine must be refused"),
]

# Required-param elicitation negatives: for each, the prompt deliberately
# omits the named param and the agent must ASK rather than guess. This is
# where registry.py's REQUIRED_PARAMS earns its keep.
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

# Engine pairings that must be REFUSED outright by default_engine()'s
# ALLOWED_ENGINES check, regardless of how the request is phrased.
DISALLOWED_PAIRINGS = [
    ("D01", "caspt2", "orca", "ORCA has no CASPT2 at all -- it has NEVPT2"),
    ("D02", "caspt2", "pyscf", ""),
    ("D03", "neb_ts", "pyscf", "PySCF has no native NEB and this app doesn't build one"),
    ("D04", "neb_ts", "bagel", ""),
    ("D05", "recommend_active_space", "orca", ""),
    ("D06", "recommend_active_space", "bagel", ""),
    ("D07", "eom_ccsd", "bagel", ""),
    ("D08", "single_point", "bagel", ""),
]


def tier(n: int) -> list:
    return [row for row in MATRIX if row[3] == n]
