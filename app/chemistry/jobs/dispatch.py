"""The one place a v2 (task, subtype, method) is translated into which
internal run_*/build_input_preview function handles it.

Three engines' worth of already-tested compute code (`run_casscf`,
`run_tddft`, `run_geometry_optimization`, ...) is named after the v1
taxonomy, and nothing about that needs to change -- these are Python
identifiers, not data that flows through a `JobSpec` or gets persisted to
`spec.json`. What P2B removes is the OLD arrangement, where that same
v1-shaped string was *also* the thing stored on `JobSpec.method` and
re-derived independently in more than one place (`app/agent/tools.py`'s
`_legacy_job_type` at spec-construction time, and each worker's
`spec["method"]` read at dispatch time) -- two copies of one decision that
could drift. `resolve_runner()` here is the only remaining derivation,
called fresh at the point something actually needs to pick a function:
each worker's `main()` and `app/chemistry/jobs/preview.py`. Nothing
upstream of that -- not `JobSpec`, not `spec.json`, not the approval card --
carries a runner key at all; see `JobSpec.method`'s own docstring in
base.py for what it holds instead.

Master tasks (`pes_1d`, `interp_pes`, `wigner_spectra`) never reach this
function themselves: they have no compute of their own; their sub-jobs are
ordinary `single_point/gs` (pes_1d, interp_pes) or `single_point/ee`
(wigner_spectra) jobs at the master's own method, constructed directly by
`JobManager.submit_scan`/`submit_ensemble`/`EnsembleOrchestrator`, which is
exactly the `single_point` branch below.
"""
from __future__ import annotations

from typing import Optional

# Tasks with a v2 entry (registry2/tasks.py's TASKS) and no runner behind
# them yet -- the registry can describe them because Phase 0 verified the
# engines can do them, but the implementation lands in a later phase. Named
# explicitly so the refusal says which phase, rather than surfacing as
# "unknown task".
NOT_YET_IMPLEMENTED = {
    ("single_point", "grad"): "Energy gradients as a standalone job land in Phase 5.",
    ("single_point", "nac"): "Non-adiabatic couplings land in Phase 5.",
}

# (task, subtype) -> the run_*/build_input_preview function family to use,
# for every task whose runner doesn't vary by method. single_point varies
# by method (see resolve_runner below) so it isn't listed here.
_TASK_RUNNER: dict[tuple[str, str], str] = {
    ("opt", "min"): "geometry_optimization",
    ("opt", "constrained"): "geometry_optimization",
    ("opt", "ci"): "geometry_optimization",
    ("freq", ""): "frequency",
    ("opt_freq", ""): "opt_freq",
    ("neb_ts", ""): "neb_ts",
    ("cas_reco", "explain"): "recommend_active_space",
    ("cas_reco", "autocas"): "recommend_active_space",
    ("cas_reco", "avas"): "recommend_active_space",
    ("blind", ""): "custom",
}


def resolve_runner(task: str, subtype: str, method: Optional[str]) -> tuple[Optional[str], Optional[str]]:
    """(runner_key, error) -- exactly one is not None.

    `single_point` is the one task whose runner depends on `method`, not
    just `subtype`: a CASSCF/CASPT2 single point is its own runner (state
    energies, not a ground-state-plus-excitations shape); an excited-state
    (`subtype="ee"`) single point is `eom_ccsd` when the method is
    `eom_ccsd` and `tddft` otherwise (TDA/TDDFT/CIS/TD-HF all being
    `hf`/`dft` plus the `use_tda` parameter, not distinct methods -- see
    registry2/capabilities.py's CANONICAL_METHODS).
    """
    if (task, subtype) in NOT_YET_IMPLEMENTED:
        return None, NOT_YET_IMPLEMENTED[(task, subtype)]
    if task == "single_point":
        if method in ("casscf", "caspt2"):
            return method, None
        if subtype == "ee":
            return ("eom_ccsd" if method == "eom_ccsd" else "tddft"), None
        return "single_point", None
    runner = _TASK_RUNNER.get((task, subtype))
    if runner is None:
        return None, f"No runner is wired up for {task}/{subtype} yet."
    return runner, None
