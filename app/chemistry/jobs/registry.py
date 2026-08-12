"""Method -> engine routing and the parameter contract for each job type.

The agent consults `REQUIRED_PARAMS`/`OPTIONAL_PARAMS` to decide what's
still missing from a user's request before it will submit a job, and
`DEFAULT_ENGINE` to decide which backend runs it. A user can override the
engine explicitly (e.g. "use ORCA for this") as long as `ALLOWED_ENGINES`
permits it.
"""
from __future__ import annotations

METHODS = [
    "single_point",
    "geometry_optimization",
    "frequency",
    "casscf",
    "caspt2",
    "tddft",
    "mo_visualization",
    "pes_scan",
]

DEFAULT_ENGINE = {
    "single_point": "pyscf",
    "geometry_optimization": "pyscf",
    "frequency": "pyscf",
    "casscf": "pyscf",
    "caspt2": "bagel",
    "tddft": "pyscf",
    "mo_visualization": "pyscf",
    "pes_scan": "pyscf",
}

ALLOWED_ENGINES = {
    "single_point": {"pyscf", "orca"},
    "geometry_optimization": {"pyscf", "orca"},
    "frequency": {"pyscf", "orca"},
    "casscf": {"pyscf", "bagel"},
    "caspt2": {"bagel"},
    "tddft": {"pyscf", "orca"},
    "mo_visualization": {"pyscf"},
    "pes_scan": {"pyscf"},
}

# Parameters the agent MUST have (from the user or sensible defaults it
# explicitly confirms) before submitting. Anything not in this dict for a
# given method is optional/has a hardcoded default in the runner.
REQUIRED_PARAMS: dict[str, list[str]] = {
    "single_point": ["method", "basis"],  # method: e.g. "hf", "b3lyp"
    "geometry_optimization": ["method", "basis"],
    "frequency": ["method", "basis"],
    "casscf": ["basis", "active_electrons", "active_orbitals"],
    "caspt2": ["basis", "active_electrons", "active_orbitals"],
    "tddft": ["method", "basis", "n_states"],
    "mo_visualization": ["method", "basis", "orbital_indices"],
    "pes_scan": ["method", "basis", "coordinate", "n_points"],
}

OPTIONAL_PARAMS: dict[str, dict] = {
    "single_point": {"functional": None},
    "geometry_optimization": {"functional": None, "max_steps": 100},
    "frequency": {"functional": None, "temperature_K": 298.15},
    "casscf": {"n_states": 1, "weights": None, "df_basis": None},
    "caspt2": {"n_states": 1, "ms_caspt2": True, "shift": 0.2, "frozen_core": True, "df_basis": None},
    "tddft": {"functional": "b3lyp", "singlet_only": True},
    "mo_visualization": {"functional": None, "isoval": 0.04},
    "pes_scan": {"functional": None, "scan_range": None},  # scan_range: [start, stop] in the coord's native units
}

PARAM_HELP: dict[str, str] = {
    "method": "electronic structure method, e.g. 'hf' or 'dft'",
    "functional": "DFT exchange-correlation functional, e.g. 'b3lyp', 'pbe0', 'wb97x-d' (only if method is dft)",
    "basis": "basis set, e.g. 'sto-3g', '6-31g*', 'cc-pvdz', 'def2-svp'",
    "active_electrons": "number of active electrons in the CAS active space",
    "active_orbitals": "number of active orbitals in the CAS active space",
    "n_states": "number of electronic states to compute (state-averaging / excited states)",
    "weights": "state-average weights for CASSCF (list summing to 1); defaults to equal weights",
    "orbital_indices": "which molecular orbitals to visualize (e.g. 'HOMO', 'LUMO', 'HOMO-1', or a 1-based index)",
    "coordinate": (
        "the internal coordinate to scan, as a linear interpolation between two geometries or a "
        "bond/angle/dihedral spec, e.g. {'type': 'bond', 'atoms': [0, 1]} or "
        "{'type': 'dihedral', 'atoms': [0,1,2,3]}"
    ),
    "n_points": "number of points to sample along the scan",
    "scan_range": "[start, stop] values for the scanned coordinate (angstrom for bonds, degrees for angles/dihedrals)",
    "ms_caspt2": "whether to use multi-state CASPT2 (MS-CASPT2) instead of single-state",
    "shift": "CASPT2 imaginary/real level shift to avoid intruder states (typical: 0.1-0.3)",
    "frozen_core": "whether to freeze core orbitals in the correlation treatment",
    "df_basis": (
        "density-fitting basis for BAGEL (only needed for casscf/caspt2 on BAGEL); "
        "auto-derived from 'basis' for the cc-pVXZ/SVP/TZVPP families, otherwise falls back to svp-jkfit"
    ),
}


def default_engine(method: str, requested_engine: str | None = None) -> str:
    if requested_engine:
        if requested_engine not in ALLOWED_ENGINES.get(method, set()):
            raise ValueError(
                f"Engine '{requested_engine}' cannot run '{method}'. "
                f"Allowed engines: {sorted(ALLOWED_ENGINES.get(method, set()))}"
            )
        return requested_engine
    return DEFAULT_ENGINE[method]


def missing_required_params(method: str, params: dict) -> list[str]:
    required = REQUIRED_PARAMS.get(method, [])
    missing = []
    for key in required:
        val = params.get(key)
        if val is None or val == "":
            missing.append(key)
        if key == "method" and val == "dft" and not params.get("functional"):
            missing.append("functional")
    return missing
