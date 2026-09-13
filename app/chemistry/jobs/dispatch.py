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
ordinary `single_point` jobs at the master's own method, constructed
directly by `JobManager.submit_scan`/`submit_ensemble`/
`EnsembleOrchestrator`, which is exactly the `single_point` branch below.
`wigner_spectra` is always `single_point/ee`; a scan is `gs` or `ee`
according to its own subtype (`base.scan_child_subtype`).

Worth noting for the scan case, because it is what makes one child subtype
enough: the casscf/caspt2 test in `resolve_runner` below comes BEFORE the
`subtype == "ee"` test, so an excited-state scan's images route to the
CASSCF runner for a multireference method and to the TDDFT/EOM-CCSD runner
for a single-reference one, with no per-method branching at the dispatch
site. Reversing those two branches would silently run a TDDFT calculation
on a CASSCF request.
"""
from __future__ import annotations

from typing import Optional

# Tasks with a v2 entry (registry2/tasks.py's TASKS) and no runner behind
# them yet -- the registry can describe them because Phase 0 verified the
# engines can do them, but the implementation lands in a later phase. Named
# explicitly so the refusal says which phase, rather than surfacing as
# "unknown task".
NOT_YET_IMPLEMENTED = {
    # geometry_set is fully implemented (Phase 3), but through a different
    # mechanism entirely: JobManager.submit_geometry_set, called directly
    # from server/routes/chat.py's attach_upload when a 3+-geometry file is
    # attached -- never through a job draft, since there is no method/
    # engine/params for a model to elicit and nothing here for
    # resolve_runner to dispatch (it never reaches this module at all; see
    # this file's own docstring on master tasks with no runner). Refused
    # here, not "not yet built": letting a draft reach READY for this task
    # would be a second, parallel way to create the same kind of job,
    # exactly what the no-legacy/one-mechanism principle rules out.
    ("geometry_set", ""): (
        "A geometry set isn't created by submitting a job. Three or more geometries become one "
        "automatically: pass them to set_geometry as one pasted block (titled blocks of "
        "coordinates, or a multi-frame xyz -- both work, and the block does not need atom-count "
        "lines), or have the user attach a file with 3+ geometries. Either way you get back a "
        "geometry_set job id to put in a batch's source_job_id. Do not ask for a file when the "
        "coordinates are already in the conversation."
    ),
}

# Methods whose single_point runner is named after the method itself,
# because what they report is a set of state energies rather than a ground
# state with excitations hung off it. Spelled out here rather than imported
# from registry2.params.MULTIREF_METHODS (which holds the same five names
# for its own reason -- they all need an active space) because this module
# is deliberately free of registry imports: registry2's package __init__
# pulls in elicitation, which imports back into app.chemistry.jobs. If a
# method is added there it belongs here too, and the cross-product check in
# scripts/check_capability_matrix.py is what catches the omission.
_STATE_ENERGY_METHODS = ("casscf", "caspt2", "nevpt2", "mcpdft", "lpdft", "cmspdft")

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
    # One subtype, not two. The old pair differed only in whether an entropy
    # pilot ran between the AVAS seeding and the final CASSCF; the engine that
    # replaces them always does both the projection and the ranking, so the
    # distinction has nothing left to name.
    ("cas_reco", ""): "cas_recommendation",
    ("cas_reco", "refine"): "cas_refinement",
    ("blind", ""): "custom",
}


def resolve_runner(task: str, subtype: str, method: Optional[str]) -> tuple[Optional[str], Optional[str]]:
    """(runner_key, error) -- exactly one is not None.

    `single_point` is the one task whose runner depends on `method`, not
    just `subtype`: a CASSCF/CASPT2/NEVPT2/MC-PDFT/L-PDFT single point is
    its own runner (state energies, not a ground-state-plus-excitations
    shape -- see `_STATE_ENERGY_METHODS`); an excited-state
    (`subtype="ee"`) single point is `eom_ccsd` when the method is
    `eom_ccsd` and `tddft` otherwise (TDA/TDDFT/CIS/TD-HF all being
    `hf`/`dft` plus the `use_tda` parameter, not distinct methods -- see
    registry2/capabilities.py's CANONICAL_METHODS). `grad`/`nac` are checked
    BEFORE the casscf/caspt2 branch below: a CASSCF gradient or NAC is still
    routed to the shared `gradient`/`nac` runner (which branches internally
    on method), not to the `casscf`/`caspt2` energy runner -- getting this
    ordering backwards would silently run a CASSCF energy job in place of a
    CASSCF gradient/NAC request.
    """
    if (task, subtype) in NOT_YET_IMPLEMENTED:
        return None, NOT_YET_IMPLEMENTED[(task, subtype)]
    if task == "single_point":
        if subtype == "grad":
            return "gradient", None
        if subtype == "nac":
            return "nac", None
        if method in _STATE_ENERGY_METHODS:
            return method, None
        # eom_ccsd BEFORE the subtype test, not inside it. R-028: this branch
        # read `if subtype == "ee": return "eom_ccsd" if method == ...`, so a
        # single_point/gs with method=eom_ccsd fell through to the plain
        # single_point runner, which then rejected the method. registry2
        # routes that cell -- supports() is True and route_engine picks an
        # engine for it -- and ARCHITECTURE.md says in as many words that
        # "eom_ccsd is its own method value (on single_point/gs or
        # single_point/ee)". The runner key follows the METHOD here; the
        # subtype only decides between tddft and the plain ground-state
        # runner for everything else.
        if method == "eom_ccsd":
            return "eom_ccsd", None
        if subtype == "ee":
            return "tddft", None
        return "single_point", None
    runner = _TASK_RUNNER.get((task, subtype))
    if runner is None:
        return None, f"No runner is wired up for {task}/{subtype} yet."
    return runner, None
