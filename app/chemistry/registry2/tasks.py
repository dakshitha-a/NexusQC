"""What the user asks for, separated from the level of theory they ask for
it at.

The legacy `app/chemistry/jobs/registry.py` has one `method` field doing two
jobs at once: `single_point`, `tddft` and `casscf` are all values of it, so
"a CASSCF single point" and "a CASSCF geometry optimization" are unrelated
strings rather than the same method under two tasks. That conflation is why
`ALLOWED_ENGINES` had to be hand-maintained per job type, with comments
explaining which entries were "vestigial" or "permissive" because the real
check happened somewhere else.

Here the two axes are separate: `capabilities.MethodCaps` says what an
(engine, method) pair can compute, and a `TaskDef` says which of those
properties a task needs. **`supports()` is derived from that pairing and is
never hand-enumerated** -- there is no table anywhere saying "BAGEL can do
constrained optimization", only `opt/constrained` requiring the
`constrained_opt` property and BAGEL's capability row recording that
`fix_atom` is silently ignored. Adding an engine or a method cannot leave a
stale allow-list behind, because there is no allow-list.

There is deliberately **no `mo_viz` task**, even though `mo_visualization`
is a legacy job type with a runner behind it. Both the plan's task list and
the projected end state in `docs/MASTER_PLAN_SUMMARY.md` treat orbital
rendering as a *presentation* of a single-point calculation -- the orbital
viewer is one of `single_point`'s previews -- rather than as a separate
thing to ask for. Asking for "the HOMO of water" is asking for a
calculation and a way to look at it, not for a different calculation.
`orbital_indices` is therefore a `single_point` parameter (see params.py).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Optional

from app.chemistry.registry2.capabilities import CAPABILITIES, ENGINES, MethodCaps, get_caps


@dataclass(frozen=True)
class SupportVerdict:
    """Whether one (engine, method) can run one (task, subtype).

    `warnings` are for a job that WILL run but carries a caveat the user
    should see before approving -- a numerical Hessian's cost, an excited
    state with no oscillator strengths. They are never a reason to refuse:
    a long or expensive calculation is this app's design premise, not a
    defect (see CLAUDE.md).
    """
    supported: bool
    reasons: tuple[str, ...] = ()      # why not, when unsupported
    warnings: tuple[str, ...] = ()     # caveats, when supported

    def __bool__(self) -> bool:
        return self.supported


@dataclass(frozen=True)
class TaskDef:
    """One thing a user can ask for.

    `requires` names capability fields on `MethodCaps`; each is checked
    through `MethodCaps.has()`, which is what makes an `unverified` or
    `gap` cell unroutable. `engines`/`methods` are hard allow-lists for the
    handful of tasks whose availability is a property of *this app's
    implementation* rather than of the engine's physics -- NEB-TS exists
    only in ORCA's runner here, active-space recommendation needs in-memory
    PySCF objects, and a blind text input is only accepted for engines with
    a literal input-file format.
    """
    task: str
    subtype: str = ""
    label: str = ""
    description: str = ""
    requires: tuple[str, ...] = ()
    engines: Optional[tuple[str, ...]] = None
    methods: Optional[tuple[str, ...]] = None
    # True for tasks with no compute of their own -- they fan out into
    # sub-jobs or hold state. `method` may legitimately be None for these.
    master: bool = False
    # Extra derived warnings, given the resolved capability row.
    warn: Optional[Callable[[MethodCaps], tuple[str, ...]]] = field(default=None, repr=False)
    # One extra sentence appended to `supports()`'s refusal text when the
    # `engines` allow-list above is what denies the request -- e.g.
    # steering a denied BAGEL pes_1d request toward interp_pes rather than
    # leaving the user to discover the alternative themselves. Never
    # consulted for a `requires`/capability-row denial (a genuine physics
    # gap), only for this app's own implementation-scope allow-lists.
    engine_denial_hint: Optional[str] = None
    # Illustrative summary-field names a completed job of this task/subtype
    # commonly reports, for plot(kind="custom")'s spec (app/agent/tools.py)
    # and lookup_capabilities' answer to "what can I plot from this task."
    # Deliberately NOT held to this module's evidence-graded verification
    # bar (Evidence/EVIDENCE_LEVELS above) and NOT a second validation path:
    # the runners in app/chemistry/jobs/*.py build summary dicts as literal
    # string keys with no schema, so this list can drift from them the way
    # a docstring can. The actual gate stays runtime field-path resolution
    # against one completed job's real summary at plot time, which refuses
    # cleanly (listing the real keys present) on any path this list got
    # wrong or didn't cover -- these names exist only to give the model
    # something to try first, before any job exists to introspect.
    plottable_fields: tuple[str, ...] = ()

    @property
    def key(self) -> tuple[str, str]:
        return (self.task, self.subtype)

    @property
    def name(self) -> str:
        return f"{self.task}/{self.subtype}" if self.subtype else self.task


# ------------------------------------------------------------ warning rules

def _warn_numerical_hessian(caps: MethodCaps) -> tuple[str, ...]:
    if caps.hessian == "numerical":
        return (
            f"{caps.engine.upper()} has no analytic Hessian for {caps.method} -- the "
            f"frequencies come from a numerical one (roughly 6x n_atoms gradient "
            f"evaluations). That is expected to take a while, not a fault.",
        )
    return ()


def _warn_no_osc(caps: MethodCaps) -> tuple[str, ...]:
    if not caps.has("osc_strengths"):
        return (
            f"{caps.engine.upper()} reports excitation energies but no oscillator "
            f"strengths for {caps.method}, so intensities will be absent rather than "
            f"estimated.",
        )
    return ()


def _warn_nac_pairing(caps: MethodCaps) -> tuple[str, ...]:
    """The inversion recorded in QM_CAPABILITIES.md's closing section.

    The original brief assumed single-reference NACs would be
    excited-to-excited and that a ground-to-excited request deserved a
    warning. The installed engines do exactly the opposite, so the warning
    has to describe what each engine really offers rather than restate the
    rule.
    """
    if caps.method in ("hf", "dft"):
        return (
            f"{caps.engine.upper()}'s CIS/TDDFT module computes the ground-to-excited "
            f"coupling only; it offers no excited-to-excited pair for a single-reference "
            f"method. Ask for a state pair involving the ground state.",
        )
    return ()


def _warn_es_gradient_b88(caps: MethodCaps) -> tuple[str, ...]:
    if caps.engine == "orca" and caps.method == "dft":
        return (
            "For a B88-containing functional (B3LYP, BLYP) ORCA refuses an excited-state "
            "gradient through its native path. A %method LibXC rewrite was attempted for "
            "single_point/grad (Phase 5) and produced a ground-state energy off by ~1.2 "
            "Hartree from the native B3LYP result -- not a working substitute -- so this app "
            "refuses the combination outright rather than guessing further (see "
            "docs/PARSER_GAPS.md). Ask for a different functional (e.g. PBE0) or engine.",
        )
    return ()


def _warn_numerical_gradient(caps: MethodCaps) -> tuple[str, ...]:
    if caps.gradient == "numerical":
        return (
            f"{caps.engine.upper()} has no analytic gradient for {caps.method}; the "
            f"optimization will use numerical gradients and take substantially longer.",
        )
    return ()


# ------------------------------------------------------------------- tasks

TASKS: dict[tuple[str, str], TaskDef] = {}


def _register(t: TaskDef) -> TaskDef:
    TASKS[t.key] = t
    return t


_register(TaskDef(
    task="single_point", subtype="gs", label="Single-point energy",
    description="One ground-state energy at a fixed geometry.",
    requires=("energy",),
    plottable_fields=("energy_hartree", "homo_lumo_gap_eV", "dipole_debye"),
))
_register(TaskDef(
    task="single_point", subtype="ee", label="Excited-state energies",
    description="Vertical excitation energies (and intensities where the engine "
                "computes them) at a fixed geometry.",
    requires=("energy", "excited"),
    warn=_warn_no_osc,
    plottable_fields=("excitation_energies_eV", "oscillator_strengths"),
))
_register(TaskDef(
    task="single_point", subtype="grad", label="Energy gradient",
    description="The nuclear energy gradient at a fixed geometry, ground or excited "
                "state.",
    requires=("gradient",),
))
_register(TaskDef(
    task="single_point", subtype="nac", label="Non-adiabatic coupling",
    description="The derivative coupling between a pair of electronic states.",
    requires=("nac",),
    warn=_warn_nac_pairing,
))
_register(TaskDef(
    task="opt", subtype="min", label="Geometry optimization",
    description="Relax the structure to an energy minimum.",
    requires=("gradient",),
    warn=_warn_numerical_gradient,
    plottable_fields=("final_energy_hartree", "optimization_energies_hartree"),
))
_register(TaskDef(
    task="opt", subtype="constrained", label="Constrained optimization",
    description="Relax the structure with one or more internal coordinates held fixed.",
    requires=("gradient", "constrained_opt"),
    plottable_fields=("final_energy_hartree", "optimization_energies_hartree", "constraints"),
))
_register(TaskDef(
    task="opt", subtype="ci", label="Conical-intersection optimization",
    description="Find the minimum-energy crossing point between two electronic states.",
    requires=("gradient", "excited", "ci_opt"),
    plottable_fields=("ci_energy_diff_hartree",),
))
_register(TaskDef(
    task="freq", label="Frequencies",
    description="Harmonic vibrational frequencies and thermochemistry from the Hessian.",
    requires=("hessian",),
    warn=_warn_numerical_hessian,
    plottable_fields=(
        "frequencies_cm-1", "zero_point_energy_hartree", "enthalpy_hartree", "gibbs_free_energy_hartree",
    ),
))
_register(TaskDef(
    task="opt_freq", label="Optimization then frequencies",
    description="A geometry optimization followed by a frequency calculation at the "
                "optimized structure, confirming it is a real minimum.",
    requires=("gradient", "hessian"),
    warn=_warn_numerical_hessian,
    plottable_fields=(
        "frequencies_cm-1", "zero_point_energy_hartree", "gibbs_free_energy_hartree",
        "optimization_energies_hartree",
    ),
))
_register(TaskDef(
    task="pes_1d", label="1-D potential energy scan",
    description="Step one internal coordinate (bond, angle or dihedral) and compute "
                "the chosen task at each point.",
    requires=("energy",),
    # P7.1: pyscf/orca only in this app -- not a capability gap (every
    # pes_1d image dispatches as an ordinary single_point/gs sub-job, which
    # BAGEL runs identically to the other two engines), a scope decision,
    # same "this app's implementation, not the engine's physics" reasoning
    # TaskDef's own docstring already gives for neb_ts being ORCA-only.
    # interp_pes is this app's other master-scan task and needs no bond/
    # angle/dihedral perception at all, so it is offered as the BAGEL path
    # instead of leaving the user to find it unprompted.
    engines=("pyscf", "orca"),
    engine_denial_hint=(
        "For BAGEL, use interp_pes instead: interpolate a path between two "
        "endpoint geometries (IDPP/LIIC/linear) rather than stepping one "
        "internal coordinate."
    ),
    master=True,
    plottable_fields=("coordinate_values", "energies_hartree", "relative_energies_kcal_mol"),
))
_register(TaskDef(
    task="interp_pes", label="Interpolated path scan",
    description="Interpolate between two geometries (IDPP, LIIC or linear) and compute "
                "the chosen task at each image.",
    requires=("energy",),
    master=True,
    plottable_fields=("coordinate_values", "energies_hartree", "relative_energies_kcal_mol"),
))
_register(TaskDef(
    task="neb_ts", label="NEB transition-state search",
    description="Nudged-elastic-band path search for a transition state between a "
                "reactant and a product structure.",
    requires=("gradient",),
    engines=("orca",),
    plottable_fields=("ts_energy_hartree",),
))
_register(TaskDef(
    task="wigner_spectra", label="Nuclear-ensemble spectrum",
    description="Wigner-sample geometries from a completed frequency job's normal "
                "modes, run an excited-state calculation at each, and pool the result "
                "into a broadened absorption spectrum.",
    requires=("excited",),
    master=True,
    warn=_warn_no_osc,
))
# There is deliberately no `cas_reco/explain` TaskDef. Explaining an active
# space the user already chose runs no engine calculation at all -- it is a
# literature lookup and a reading of the space -- so routing it through
# JobManager (resource admission, a core budget, a background subprocess, a
# spec.json on disk) was machinery for something that does no computing,
# and its `engines=("pyscf",)` declaration was fiction. It is the
# `explain_active_space` tool in app/agent/tools.py instead, sharing one
# literature-search implementation with the pre-draft search rather than
# growing a second.
_register(TaskDef(
    task="cas_reco", subtype="autocas", label="AutoCAS active-space recommendation",
    description="Single-orbital-entropy pilot (exact FCI or DMRG) followed by a "
                "state-averaged CASSCF with the recommended space.",
    requires=("energy", "excited"),
    engines=("pyscf",), methods=("casscf",),
))
_register(TaskDef(
    task="cas_reco", subtype="avas", label="AVAS active-space construction",
    description="Build an active space from atomic-valence character labels, then run a "
                "state-averaged CASSCF in it -- no entropy screening.",
    # "excited" alongside "energy" because the final CASSCF here is
    # state-averaged, exactly as autocas's is. It said "energy" alone while
    # the two subtypes shared a runner, which was wrong even then.
    requires=("energy", "excited"),
    engines=("pyscf",), methods=("casscf",),
))
_register(TaskDef(
    task="blind", label="Blind engine input",
    description="A literal ORCA or BAGEL input, run verbatim with no structured "
                "parameter building and no task-specific output parsing.",
    engines=("orca", "bagel"),
    master=True,
))
_register(TaskDef(
    task="batch", label="Batch",
    # No `requires` here, deliberately -- unlike every other TaskDef's
    # `requires`, a fixed tuple on `batch` itself would be fiction: batch
    # has no level of theory of its own, and what an (engine, method) can
    # actually deliver depends entirely on the user's chosen `child_task`
    # (single_point/opt/freq/opt_freq, see params.py's ParamSpec and
    # BATCH_CHILD_TASKS below). `supports()`/`route_engine()` are given the
    # CHILD's own (task, subtype) at the two call sites in elicitation.py
    # that need a real capability verdict, reusing that task's own
    # `requires` rather than duplicating it here -- an opt child on a
    # method with no gradient must be refused, and only opt/min's own
    # TaskDef knows that.
    description="Run one calculation (single-point energy, optimization, frequencies, "
                "or optimization + frequencies) over every geometry produced by another "
                "job -- one independent child job per geometry.",
    master=True,
))

# The one place `child_task` (params.py's ParamSpec, options
# single_point/opt/freq/opt_freq) is mapped to a real (task, subtype) pair
# -- elicitation.py's two capability-check call sites, batch_orchestrator.py's
# child dispatch, and app/agent/tools.py's preview builder all import this
# rather than re-deriving it, so the four job types 1-4 the plan restricts
# batch to are named in exactly one place.
BATCH_CHILD_TASKS: dict[str, tuple[str, str]] = {
    "single_point": ("single_point", "gs"),
    "opt": ("opt", "min"),
    "freq": ("freq", ""),
    "opt_freq": ("opt_freq", ""),
}

# Which artifact key holds a source job's multi-frame geometry file, per
# task -- `source_job_id` (params.py's ParamSpec) accepts any job whose
# task is a key here. All of these are already plain multi-frame xmol text
# (app/chemistry/geometry_upload.parse_multi_frame_xyz reads any of them
# identically): geometry_set/pes_1d/interp_pes/batch share the literal
# `_write_path_xyz` helper (base.py), wigner_spectra uses the same helper
# under its own "ensemble_xyz" name, and neb_ts's "neb_frames" is built by
# plain text concatenation of two already-valid standalone xmol blocks
# (see orca_runner.py's own run_neb_ts comment) -- a different writer, the
# same format. `batch` itself is deliberately excluded: its own children
# can be a heterogeneous mix of job families (an opt result and a freq
# result are not "the same path" the way scan/interp/wigner/NEB frames
# are), so re-batching a batch's own geometries is not offered.
BATCH_GEOMETRY_SOURCE_ARTIFACT_KEY: dict[str, str] = {
    "geometry_set": "path_xyz",
    "pes_1d": "path_xyz",
    "interp_pes": "path_xyz",
    "wigner_spectra": "ensemble_xyz",
    "neb_ts": "neb_frames",
}
_register(TaskDef(
    task="geometry_set", label="Geometry set",
    description="Three or more uploaded geometries held together for later use; no "
                "calculation of its own.",
    master=True,
))


def get_task(task: str, subtype: str = "") -> Optional[TaskDef]:
    return TASKS.get((task, subtype))


def subtypes_for(task: str) -> tuple[str, ...]:
    return tuple(st for (t, st) in TASKS if t == task)


def supports(engine: str, method: Optional[str], task: str, subtype: str = "") -> SupportVerdict:
    """Can `engine` run `task/subtype` at `method`?

    Derived entirely from the task's `requires` predicate over the
    capability row, plus the two hard allow-lists. Nothing here consults a
    per-job-type engine table, because none exists.
    """
    tdef = get_task(task, subtype)
    if tdef is None:
        return SupportVerdict(False, (f"Unknown task {task}/{subtype}." if subtype
                                      else f"Unknown task {task}.",))

    if engine not in ENGINES:
        return SupportVerdict(False, (f"Unknown engine {engine!r}.",))

    if tdef.engines is not None and engine not in tdef.engines:
        reason = (
            f"{tdef.label} is only available on {', '.join(e.upper() for e in tdef.engines)} "
            f"in this app."
        )
        if tdef.engine_denial_hint:
            reason = f"{reason} {tdef.engine_denial_hint}"
        return SupportVerdict(False, (reason,))

    # A master with no level of theory of its own (a batch, a geometry set,
    # a blind text input) is answered by the allow-list alone -- there is no
    # capability row to consult, and inventing one would be the same
    # hand-enumeration this module exists to avoid.
    if method is None:
        if tdef.master or not tdef.requires:
            return SupportVerdict(True)
        return SupportVerdict(False, (f"{tdef.label} needs a method.",))

    if tdef.methods is not None and method not in tdef.methods:
        return SupportVerdict(False, (
            f"{tdef.label} is only defined for {', '.join(tdef.methods)} in this app.",
        ))

    caps = get_caps(engine, method)
    if caps is None:
        return SupportVerdict(False, (
            f"This app does not run {method} on {engine.upper()}.",
        ))

    reasons: list[str] = []
    for capability in tdef.requires:
        if caps.has(capability):
            continue
        ev = caps.evidence.get(capability)
        detail = f" ({ev.observed})" if ev is not None and ev.level == "gap" else ""
        reasons.append(
            f"{engine.upper()} cannot supply '{capability}' for {method}{detail}."
        )
    if reasons:
        return SupportVerdict(False, tuple(reasons))

    warnings: list[str] = []
    if tdef.warn is not None:
        warnings.extend(tdef.warn(caps))
    # ORCA's B88/LibXC rewrite caveat belongs only where an excited-state
    # gradient is actually taken. Attaching it to every task that needs a
    # gradient would put it on ordinary ground-state optimizations, where
    # it is simply untrue.
    if "excited" in tdef.requires and "gradient" in tdef.requires:
        warnings.extend(_warn_es_gradient_b88(caps))
    return SupportVerdict(True, warnings=tuple(warnings))


def engines_supporting(method: Optional[str], task: str, subtype: str = "") -> tuple[str, ...]:
    """Every engine that can run this task at this method, in preference
    order. `routing.route_engine` picks from exactly this list."""
    return tuple(e for e in ENGINES if supports(e, method, task, subtype).supported)


def tasks_supported_by(engine: str, method: str) -> tuple[TaskDef, ...]:
    """Every task one (engine, method) pair can run -- the inverse view,
    used by the capability-doc generator."""
    return tuple(t for t in TASKS.values() if supports(engine, method, t.task, t.subtype).supported)


def all_pairs() -> tuple[tuple[str, str], ...]:
    """Every (engine, method) pair with a capability row, for exhaustive
    cross-product checks."""
    return tuple(CAPABILITIES.keys())
