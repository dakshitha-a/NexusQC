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
    # Nudged Elastic Band transition-state search (ORCA's native !NEB-TS) --
    # a single job (ORCA parallelizes the images itself via %pal, unlike
    # pes_scan's one-real-sub-job-per-image architecture). See
    # app/chemistry/jobs/orca_runner.py's run_neb_ts and CLAUDE.md's
    # architecture note for the full design (file-naming conventions were
    # verified against real ORCA 6.1.1 runs on this machine, not just the
    # manual).
    "neb_ts",
    # No structured params, no default engine, no output parsing -- an
    # arbitrary ORCA/BAGEL calculation the agent composes as literal input
    # text itself (raw_input_text) because none of the job_types above map
    # onto it (e.g. IRC, a relaxed surface scan, a property calculation
    # with no dedicated parser here). Still runs through the same
    # approval-card + background-execution pipeline as every other job --
    # see app/agent/tools.py's _build_custom_spec_or_error and
    # orca_runner.py/bagel_runner.py's run_custom.
    "custom",
    # AutoCAS-style Single-Orbital-Entropy active-space recommendation: one
    # job that internally runs a full sequential pipeline (HF -> AVAS pilot
    # valence space -> exact-FCI pilot CASCI -> entropy/plateau analysis ->
    # final state-averaged CASSCF with the recommended space), same "one
    # job_id, several in-process stages" shape as neb_ts, not pes_scan's
    # master/sub-job fan-out (there is no independent-and-parallel work
    # here, every stage depends on the previous one's in-memory result).
    # PySCF-only -- see run_recommend_active_space's docstring in
    # pyscf_runner.py for why (ORCA/BAGEL have no round-trippable in-memory
    # RDM/mo_coeff access this app can rely on for the entropy/character
    # analysis).
    "recommend_active_space",
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
    # Vestigial: pes_scan has no compute of its own (see JobManager.
    # submit_scan) -- the real engine choice is whatever scan_job_type
    # resolves to via default_engine(scan_job_type, ...), decided in
    # app/agent/tools.py's dedicated pes_scan branch of
    # _build_spec_or_error, not here. Kept as a harmless placeholder so
    # "pes_scan" stays a valid key everywhere METHODS is iterated.
    "pes_scan": "pyscf",
    # ORCA is the only engine in this app with a native NEB/NEB-TS
    # implementation -- see ALLOWED_ENGINES below.
    "neb_ts": "orca",
    # "custom" deliberately has NO entry here -- it requires an explicit
    # engine ('orca' or 'bagel') from the caller every time, enforced in
    # app/agent/tools.py's _build_custom_spec_or_error before default_engine()
    # is ever reached, since there's no sensible default for "run this
    # arbitrary text on some engine or other."
    "recommend_active_space": "pyscf",
}

ALLOWED_ENGINES = {
    "single_point": {"pyscf", "orca"},
    # "bagel" is only reachable here when method is 'casscf'/'caspt2'
    # (geometry_optimization's own required-param cross-check in
    # app/agent/tools.py enforces active_electrons/active_orbitals are
    # present, which only happens for those methods) -- plain HF/DFT
    # geometry optimization on BAGEL was never asked for and isn't
    # implemented; bagel_runner.run_geometry_optimization raises clearly
    # if method isn't casscf/caspt2, mirroring frequency's existing
    # HF-only scope boundary on BAGEL below, just inverted.
    "geometry_optimization": {"pyscf", "orca", "bagel"},
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
    "mo_visualization": {"pyscf", "orca", "bagel"},
    # Permissive/vestigial for the same reason as DEFAULT_ENGINE["pes_scan"]
    # above -- a scan's actual per-image engine is validated against
    # scan_job_type's own ALLOWED_ENGINES entry, not this one.
    "pes_scan": {"pyscf", "orca", "bagel"},
    # PySCF has no native NEB/NEB-TS implementation and this app doesn't
    # build one from scratch (see CLAUDE.md's known limitations) -- ORCA
    # only, for now.
    "neb_ts": {"orca"},
    # PySCF has no literal input-file format for a raw job (its "preview"
    # is a synthetic driver script, not something PySCF itself parses --
    # see validate.py's module docstring for the same reasoning applied to
    # hand-edits) -- not reachable via default_engine() anyway since
    # "custom" requires an explicit engine, but kept here for consistency/
    # introspection.
    "custom": {"orca", "bagel"},
    # PySCF only -- the entropy/character analysis needs genuine in-memory
    # mo_coeff/mol/RDM access (see run_recommend_active_space); ORCA's
    # molden export doesn't round-trip (AO-normalization mismatch, see
    # mo_visualization's CLAUDE.md note) and BAGEL's only path is a molden
    # round-trip with no per-orbital energy signal for active orbitals.
    "recommend_active_space": {"pyscf"},
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
    # pes_scan's own required params -- separate from scan_job_type's own
    # requirements (e.g. single_point's method/basis), which are validated
    # in app/agent/tools.py's dedicated pes_scan branch via a second
    # missing_required_params(scan_job_type, params) call, unioned with
    # this one. Whether coordinate+scan_range (single-molecule bond/angle/
    # dihedral mode) or a second endpoint geometry (two-molecule
    # interpolation mode, via the set_pes_scan_endpoint tool) is what's
    # actually supplied is a cross-state check tools.py makes itself
    # (registry.py has no access to AgentState), not encoded here.
    "pes_scan": ["scan_job_type", "n_points"],
    # end_molecule (the product structure) is a cross-state check tools.py
    # makes itself (see _build_neb_ts_spec_or_error), not encoded here, same
    # as pes_scan's two-endpoint mode. preopt has no default on purpose --
    # required so the agent always asks the user explicitly rather than
    # silently picking true or false (per the user's own instruction).
    "neb_ts": ["method", "basis", "preopt"],
    "custom": ["raw_input_text"],
    # No active_electrons/active_orbitals -- the whole point of this
    # job_type is that it recommends those, rather than requiring them.
    "recommend_active_space": ["basis", "n_states"],
}

OPTIONAL_PARAMS: dict[str, dict] = {
    "single_point": {"functional": None},
    # n_states/weights/df_basis/target_state are only meaningful when
    # method='casscf'/'caspt2' (unused otherwise, same as this app's other
    # per-job-type optional params that only apply to some engines/
    # methods -- e.g. want_oscillator_strengths below is ORCA-CASSCF-only).
    # optimization_type/target_state_2 are BAGEL-CASSCF-only (conical-
    # intersection optimization) -- see PARAM_HELP and
    # app/chemistry/jobs/bagel_runner.py's run_geometry_optimization.
    "geometry_optimization": {
        "functional": None, "max_steps": 200, "n_states": 1, "weights": None, "df_basis": None,
        "target_state": None, "optimization_type": None, "target_state_2": None,
    },
    "frequency": {
        "functional": None, "temperature_K": 298.15, "dx": None, "df_basis": None,
        "n_states": 1, "weights": None, "target_state": None,
    },
    "casscf": {"n_states": 1, "weights": None, "df_basis": None, "want_oscillator_strengths": False},
    "caspt2": {
        "n_states": 1, "ms_caspt2": True, "shift": 0.2, "frozen_core": True, "df_basis": None,
        "want_oscillator_strengths": False,
    },
    "tddft": {"functional": "b3lyp", "singlet_only": True, "use_tda": True},
    "eom_ccsd": {},
    "mo_visualization": {"functional": None, "isoval": 0.04, "cube_grid_points": 80},
    # coordinate/scan_range: bond/angle/dihedral mode only. interpolation_method:
    # two-endpoint mode only (idpp/liic/linear, default idpp -- see
    # app/chemistry/jobs/interpolate.py).
    "pes_scan": {"coordinate": None, "scan_range": None, "interpolation_method": "idpp"},
    # target_state/n_states unset means a ground-state search; n_states
    # (NRoots) is auto-raised to at least target_state in
    # _build_neb_ts_spec_or_error if the caller didn't set it explicitly.
    "neb_ts": {"functional": None, "n_images": 6, "target_state": None, "n_states": None},
    # max_active_orbitals caps the RECOMMENDED final active space (a
    # chemistry/cost choice the user can lower); the hard pilot-space
    # ceiling (12 orbitals, an exact-FCI feasibility limit on this host --
    # see pyscf_runner._PILOT_CAS_CEILING) is a separate, non-configurable
    # module constant, not exposed here.
    "recommend_active_space": {
        "weights": None, "max_active_orbitals": 12, "avas_aolabels": None, "literature_notes": None,
        # "exact_fci" (default): pyscf CASCI, exact for the pilot space, capped at
        # pyscf_runner._PILOT_CAS_CEILING (12 orbitals, benchmarked on this host).
        # "dmrg": block2/pyblock2, approximate but polynomial-cost, capped at the
        # much larger pyscf_runner._DMRG_PILOT_CAS_CEILING -- lets the pilot
        # screen a bigger, more basis-faithful candidate pool at the cost of an
        # extra dependency and a slower job. The FINAL recommended active space
        # and its CASSCF are unaffected either way -- only the pilot screening
        # step's candidate-pool size and entropy fidelity change.
        "entropy_method": "exact_fci",
        # DMRG bond dimension (M) for the pilot pass only -- a deliberately low,
        # "cheap unconverged pilot" value per autoCAS's own design philosophy,
        # not a tightly-converged production DMRG setting. Ignored when
        # entropy_method="exact_fci".
        "dmrg_bond_dim": 250,
    },
}

PARAM_HELP: dict[str, str] = {
    "method": (
        "electronic structure method: 'hf' or 'dft' everywhere; for geometry_optimization/frequency "
        "specifically, also 'casscf' or 'caspt2' (caspt2 is BAGEL-only) -- these need "
        "active_electrons/active_orbitals like the standalone casscf/caspt2 job types do"
    ),
    "functional": "DFT exchange-correlation functional, e.g. 'b3lyp', 'pbe0', 'wb97x-d' (only if method is dft)",
    "basis": "basis set, e.g. 'sto-3g', '6-31g*', 'cc-pvdz', 'def2-svp'",
    "active_electrons": "number of active electrons in the CAS active space",
    "active_orbitals": "number of active orbitals in the CAS active space",
    "n_states": "number of electronic states to compute (state-averaging / excited states)",
    "weights": "state-average weights for CASSCF (list summing to 1); defaults to equal weights",
    "orbital_indices": "which molecular orbitals to visualize (e.g. 'HOMO', 'LUMO', 'HOMO-1', or a 1-based index)",
    "cube_grid_points": "for mo_visualization on ORCA: number of grid points per axis for the cube file (default 80)",
    "coordinate": (
        "the internal coordinate to scan, as a linear interpolation between two geometries or a "
        "bond/angle/dihedral spec, e.g. {'type': 'bond', 'atoms': [1, 2]} or "
        "{'type': 'dihedral', 'atoms': [1,2,3,4]}. Atom numbers are 1-based, matching the numbers "
        "shown next to each atom in the 3D molecule viewer."
    ),
    "n_points": "number of points/images to sample along the scan (including both endpoints)",
    "scan_range": (
        "[start, stop] values for the scanned coordinate (angstrom for bonds, degrees for angles/dihedrals) -- "
        "bond/angle/dihedral scan mode only, mutually exclusive with a second endpoint geometry"
    ),
    "scan_job_type": (
        "which job_type to run at each pes_scan image, e.g. 'single_point' (ground-state energy per image, "
        "the common case) or an excited-state job_type (tddft/casscf/caspt2/eom_ccsd) to get one energy curve "
        "per electronic state instead of just the ground state. Takes the same required params as that "
        "job_type itself (e.g. n_states/active_electrons/active_orbitals for casscf)"
    ),
    "interpolation_method": (
        "how to build the path between the two endpoint geometries for a two-molecule pes_scan (set via "
        "set_molecule for the start structure and set_pes_scan_endpoint for the end structure) -- 'idpp' "
        "(default, Image Dependent Pair Potential: aligns the two structures then iteratively adjusts every "
        "image to avoid atom clashes, generally the best-behaved choice), 'liic' (true Linear Interpolation "
        "in Internal Coordinates: bond/angle/dihedral values interpolated linearly), or 'linear' (naive "
        "Cartesian coordinate interpolation -- cheapest but can produce unphysical intermediate geometries "
        "for anything but a small displacement). Not used for the single-molecule bond/angle/dihedral scan "
        "mode."
    ),
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
        "None/unavailable rather than fabricated. For caspt2 (BAGEL only -- the only engine this app "
        "runs CASPT2 on): computes real ground-state-relative transition dipoles/oscillator strengths "
        "via BAGEL's 'forces'+dipole mechanism, which requires one extra gradient evaluation per state "
        "on top of the plain energy calculation -- noticeably more expensive than a plain CASPT2 run. "
        "Defaults to False (energies only) for an ordinary caspt2 job; only set it when the user "
        "explicitly wants intensities, or when composing per-sample sub-jobs for a wigner_ensemble "
        "whose scan_job_type is 'caspt2', where it's required for that sample to contribute any usable "
        "intensity to the pooled spectrum."
    ),
    "raw_input_text": (
        "the complete, literal ORCA .inp file text or BAGEL JSON input text you have composed yourself for "
        "this calculation -- used verbatim, byte-for-byte, with no structured-parameter input building and "
        "no job-type-specific output parsing afterward (only geometry and raw output are shown to the "
        "user). Only for a job_type='custom' job -- an engine of 'orca' or 'bagel' must also be given "
        "explicitly, since there's no sensible default engine for arbitrary text."
    ),
    "preopt": (
        "for neb_ts: whether to pre-optimize the reactant and product endpoint geometries to their own "
        "energy minima before running the NEB path search (ORCA's PreOpt keyword). Has no default -- "
        "always ask the user explicitly if they haven't said. Skip this if both endpoints are already "
        "known to be relaxed minima (e.g. they came from a prior geometry_optimization job)."
    ),
    "n_images": (
        "for neb_ts: number of movable images between the two fixed endpoints (ORCA's NImages). "
        "Defaults to 6 if not specified; the total path length shown in the UI is n_images + 2 "
        "(including both endpoints)."
    ),
    "target_state": (
        "for neb_ts: which electronic state to run the NEB search on -- omit/None for a ground-state "
        "search (the common case), or an integer N (1 = first excited state, 2 = second, ...) to run "
        "the whole NEB-TS path search directly on that excited-state potential energy surface via ORCA's "
        "TD-DFT/TD-HF gradients. n_states (NRoots) is automatically raised to at least this value if not "
        "set explicitly. For geometry_optimization/frequency with method='casscf'/'caspt2', this instead "
        "picks which state's PES to optimize/differentiate (omit/None for the ground state) -- only "
        "meaningful when engine='bagel' (BAGEL's 0-based 'target'; pyscf/orca CASSCF opt/freq in this app "
        "only ever target the lowest state of the state-average)."
    ),
    "optimization_type": (
        "for geometry_optimization with method='casscf'/'caspt2' and engine='bagel' only: 'minimum' "
        "(default, omit/None) finds the lowest-energy geometry of target_state; "
        "'conical_intersection' instead finds the minimum-energy crossing point between target_state and "
        "target_state_2 (BAGEL's gradient-projection MECI algorithm). Requesting 'conical_intersection' "
        "on pyscf/orca raises an error -- ORCA's equivalent (%mecp) is a separate, unimplemented module, "
        "and pyscf/geomeTRIC has no native multi-state crossing-point mode."
    ),
    "target_state_2": (
        "for geometry_optimization with optimization_type='conical_intersection' (BAGEL only): the second "
        "electronic state defining the crossing seam with target_state. Defaults to target_state + 1 (or "
        "1 if target_state is unset) -- a ground/first-excited-state seam, BAGEL's own default -- but is "
        "always shown on the approval card so the human sees exactly which two states before approving."
    ),
    "calculation_description": (
        "a short, human-readable label for a job_type='custom' calculation, e.g. 'NEB transition-state "
        "search' or 'relaxed surface scan' -- used as the job's display label in the Job Manager and to "
        "focus the manual/reference-doc lookup shown on the approval card, since a custom job has no "
        "method/basis parameters of its own to build that query from."
    ),
    "max_active_orbitals": (
        "for recommend_active_space: the largest FINAL active space (in orbitals) you're willing to accept "
        "as the recommendation -- defaults to 12, the practical ceiling for the final state-averaged CASSCF "
        "step (which always uses exact orbital optimization regardless of entropy_method), so this can only "
        "ever narrow the result, never widen it beyond 12. This is independent of the PILOT screening "
        "space's own ceiling, which is much larger when entropy_method='dmrg' -- a bigger pilot means a "
        "more basis-faithful SELECTION among candidate orbitals, not a bigger final recommendation."
    ),
    "entropy_method": (
        "for recommend_active_space: 'exact_fci' (default) computes single-orbital entropies exactly via "
        "pyscf CASCI on the pilot space, capped at 12 orbitals (an exact-FCI cost limit on this host) -- "
        "fast, no extra dependency. 'dmrg' uses block2/pyblock2 for an approximate but polynomial-cost "
        "pilot, capped much higher (tens of orbitals) -- lets AVAS's full candidate pool be screened at a "
        "real production basis instead of being truncated hard, at the cost of a slower job and requiring "
        "the block2 package. Offer 'dmrg' when the user wants a more basis-accurate recommendation or "
        "explicitly asks about DMRG; default to 'exact_fci' otherwise."
    ),
    "dmrg_bond_dim": (
        "for recommend_active_space with entropy_method='dmrg': the DMRG bond dimension (M) for the pilot "
        "screening pass only (never the final CASSCF, which doesn't use DMRG). Defaults to 250, a "
        "deliberately low 'cheap unconverged pilot' value -- higher values give a more accurate but slower "
        "pilot; this is a cost/accuracy knob, not something to change without a specific reason."
    ),
    "avas_aolabels": (
        "for recommend_active_space: optional list of AO character labels (e.g. ['C 2p', 'N 2p']) used to "
        "seed the AVAS valence pilot space -- omit to default to the valence p/d shells of every "
        "non-hydrogen atom in the molecule. Only narrow this deliberately (e.g. the user names a specific "
        "conjugated fragment or metal center) -- an unnecessarily narrow seed can miss orbitals that "
        "should have been screened."
    ),
    "literature_notes": (
        "for recommend_active_space: a short summary, in your own words, of what the "
        "search_knowledge_base(doc_type='paper')/search_academic_literature precedent search found for "
        "this molecule's active-space choice -- stored on the job itself so it's visible later in the "
        "job's own detail view, not just in the chat transcript."
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
