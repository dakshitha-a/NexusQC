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
    "eom_ccsd",
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
    # ORCA's MDCI module computes oscillator strengths for EOM-CCSD
    # natively; PySCF's EOMEESinglet gives energies only (no transition
    # dipoles), so ORCA is the default unless the user explicitly asks
    # for PySCF (accepting energies-only in exchange for not needing ORCA).
    "eom_ccsd": "orca",
    "mo_visualization": "pyscf",
    "pes_scan": "pyscf",
}

ALLOWED_ENGINES = {
    "single_point": {"pyscf", "orca"},
    "geometry_optimization": {"pyscf", "orca"},
    # BAGEL's numerical Hessian ("hessian" block, central gradient
    # differences) is HF-reference only in this app -- not the general
    # CASSCF/CASPT2-Hessian capability BAGEL itself supports, since the
    # frequency job type elsewhere (pyscf/orca) is likewise HF/DFT-only
    # and this is meant as parity with those, not a new feature. It's 6x
    # n_atoms gradient evaluations (two-sided differencing), so noticeably
    # slower than pyscf/orca's analytic Hessians -- see PARAM_HELP's dx.
    "frequency": {"pyscf", "orca", "bagel"},
    # ORCA's CASSCF is not the default (kept as pyscf, for backward
    # compatibility) but is the only engine of the three that computes
    # oscillator strengths for CASSCF -- default_engine() below routes
    # here automatically when a caller passes want_oscillator_strengths.
    "casscf": {"pyscf", "bagel", "orca"},
    "caspt2": {"bagel"},  # ORCA doesn't implement CASPT2 (NEVPT2 instead); BAGEL is the only option
    "tddft": {"pyscf", "orca"},
    "eom_ccsd": {"orca", "pyscf"},
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
    "tddft": ["method", "basis", "n_states"],  # method: 'dft' (TDA/TDDFT) or 'hf' (CIS/TD-HF)
    "eom_ccsd": ["basis", "n_states"],  # always post-HF-CCSD -- no method/functional choice
    "mo_visualization": ["method", "basis", "orbital_indices"],
    "pes_scan": ["method", "basis", "coordinate", "n_points"],
}

OPTIONAL_PARAMS: dict[str, dict] = {
    "single_point": {"functional": None},
    "geometry_optimization": {"functional": None, "max_steps": 100},
    "frequency": {"functional": None, "temperature_K": 298.15, "dx": None, "df_basis": None},
    "casscf": {"n_states": 1, "weights": None, "df_basis": None, "want_oscillator_strengths": False},
    "caspt2": {"n_states": 1, "ms_caspt2": True, "shift": 0.2, "frozen_core": True, "df_basis": None},
    "tddft": {"functional": "b3lyp", "singlet_only": True, "use_tda": True},
    "eom_ccsd": {},
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
        "bond/angle/dihedral spec, e.g. {'type': 'bond', 'atoms': [1, 2]} or "
        "{'type': 'dihedral', 'atoms': [1,2,3,4]}. Atom numbers are 1-based, matching the numbers "
        "shown next to each atom in the 3D molecule viewer."
    ),
    "n_points": "number of points to sample along the scan",
    "scan_range": "[start, stop] values for the scanned coordinate (angstrom for bonds, degrees for angles/dihedrals)",
    "ms_caspt2": "whether to use multi-state CASPT2 (MS-CASPT2) instead of single-state",
    "shift": "CASPT2 imaginary/real level shift to avoid intruder states (typical: 0.1-0.3)",
    "frozen_core": "whether to freeze core orbitals in the correlation treatment",
    "df_basis": (
        "density-fitting basis for BAGEL (only needed for casscf/caspt2/frequency on BAGEL); "
        "auto-derived from 'basis' for the cc-pVXZ/SVP/TZVPP families, otherwise falls back to svp-jkfit"
    ),
    "dx": (
        "for frequency on BAGEL only: finite-difference step size (bohr) for the numerical Hessian's "
        "central gradient differences. Defaults to BAGEL's own default (1.0e-3 bohr) if unset. BAGEL's "
        "numerical Hessian costs ~6x n_atoms gradient evaluations -- noticeably slower than PySCF/ORCA's "
        "analytic Hessians, so BAGEL is not the default frequency engine."
    ),
    "use_tda": (
        "for tddft: whether to use the Tamm-Dancoff approximation. True (default) + method='dft' is "
        "TDA-DFT; True + method='hf' is CIS; False + method='dft' is full TDDFT; False + method='hf' "
        "is TD-HF/RPA"
    ),
    "want_oscillator_strengths": (
        "for casscf: whether to also compute UV/Vis oscillator strengths/intensities, not just "
        "excitation energies. Only ORCA computes these for CASSCF in this app (PySCF/BAGEL report "
        "energies only) -- setting this True routes the job to ORCA automatically unless a different "
        "engine was explicitly requested, in which case oscillator_strengths in the result will be "
        "None/unavailable rather than fabricated."
    ),
}


def default_engine(method: str, requested_engine: str | None = None, params: dict | None = None) -> str:
    if requested_engine:
        if requested_engine not in ALLOWED_ENGINES.get(method, set()):
            raise ValueError(
                f"Engine '{requested_engine}' cannot run '{method}'. "
                f"Allowed engines: {sorted(ALLOWED_ENGINES.get(method, set()))}"
            )
        return requested_engine
    # Mechanical (not prompt-dependent) routing: CASSCF oscillator strengths
    # are only available via ORCA in this app, so a caller that actually
    # wants them gets routed there automatically rather than depending on
    # the LLM inferring intent and picking the right engine unprompted.
    if method == "casscf" and params and params.get("want_oscillator_strengths"):
        return "orca"
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
