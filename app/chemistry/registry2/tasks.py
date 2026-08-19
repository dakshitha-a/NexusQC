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
            "gradient through its native path; the input is rewritten into the equivalent "
            "LibXC components automatically rather than the job being refused.",
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
))
_register(TaskDef(
    task="single_point", subtype="ee", label="Excited-state energies",
    description="Vertical excitation energies (and intensities where the engine "
                "computes them) at a fixed geometry.",
    requires=("energy", "excited"),
    warn=_warn_no_osc,
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
))
_register(TaskDef(
    task="opt", subtype="constrained", label="Constrained optimization",
    description="Relax the structure with one or more internal coordinates held fixed.",
    requires=("gradient", "constrained_opt"),
))
_register(TaskDef(
    task="opt", subtype="ci", label="Conical-intersection optimization",
    description="Find the minimum-energy crossing point between two electronic states.",
    requires=("gradient", "excited", "ci_opt"),
))
_register(TaskDef(
    task="freq", label="Frequencies",
    description="Harmonic vibrational frequencies and thermochemistry from the Hessian.",
    requires=("hessian",),
    warn=_warn_numerical_hessian,
))
_register(TaskDef(
    task="opt_freq", label="Optimization then frequencies",
    description="A geometry optimization followed by a frequency calculation at the "
                "optimized structure, confirming it is a real minimum.",
    requires=("gradient", "hessian"),
    warn=_warn_numerical_hessian,
))
_register(TaskDef(
    task="pes_1d", label="1-D potential energy scan",
    description="Step one internal coordinate (bond, angle or dihedral) and compute "
                "the chosen task at each point.",
    requires=("energy",),
    master=True,
))
_register(TaskDef(
    task="interp_pes", label="Interpolated path scan",
    description="Interpolate between two geometries (IDPP, LIIC or linear) and compute "
                "the chosen task at each image.",
    requires=("energy",),
    master=True,
))
_register(TaskDef(
    task="neb_ts", label="NEB transition-state search",
    description="Nudged-elastic-band path search for a transition state between a "
                "reactant and a product structure.",
    requires=("gradient",),
    engines=("orca",),
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
_register(TaskDef(
    task="cas_reco", subtype="explain", label="Active-space explanation",
    description="Explain a proposed active space against the literature, without "
                "running a recommendation pilot.",
    requires=("energy",),
    engines=("pyscf",), methods=("casscf",),
))
_register(TaskDef(
    task="cas_reco", subtype="autocas", label="AutoCAS active-space recommendation",
    description="Single-orbital-entropy pilot (exact FCI or DMRG) followed by a "
                "state-averaged CASSCF with the recommended space.",
    requires=("energy", "excited"),
    engines=("pyscf",), methods=("casscf",),
))
_register(TaskDef(
    task="cas_reco", subtype="avas", label="AVAS active-space construction",
    description="Build an active space from atomic-valence character labels.",
    requires=("energy",),
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
    task="batch", label="Batch of jobs",
    description="A master holding several independent child jobs submitted together.",
    master=True,
))
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
        return SupportVerdict(False, (
            f"{tdef.label} is only available on {', '.join(e.upper() for e in tdef.engines)} "
            f"in this app.",
        ))

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
