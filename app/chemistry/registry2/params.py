"""Which parameters a task needs, when it needs them, and what to ask.

The legacy contract was two dicts of bare parameter names
(`REQUIRED_PARAMS` / `OPTIONAL_PARAMS`) plus a pile of cross-field rules
scattered through `app/agent/tools.py` -- "functional is required, but only
when method is dft", "a NEB job also needs an end geometry", "n_states means
something different for CASSCF than for TDDFT". Those rules were expressed
partly in Python branches and partly as prose in the system prompt, which
is why the model could and did submit jobs missing a field the backend
would then reject.

Here every rule is **data**: a `ParamSpec` with a serializable condition.
That matters for three separate consumers.

- `elicitation.validate_draft()` (Phase 2) evaluates the conditions and
  returns the exact question to ask, so the model transcribes a question
  rather than deciding what is missing.
- `GET /api/job-registry` serves the same structures to the frontend, so
  the approval card and job drawer render requirements without
  reimplementing them in TypeScript.
- The conditions are inspectable, so a rule can be tested directly instead
  of only through a conversation.

The condition language is deliberately tiny -- six operators, no
expressions, no eval. Anything it cannot express belongs in a runner's own
validation, not smuggled in as a string to be exec'd.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional, Sequence

# Default Gaussian broadening for a nuclear-ensemble spectrum, in eV.
# Lower than the 0.4 eV a single job's UV/Vis spectrum is broadened by
# (UvVisSpectrumInline's DEFAULT_FWHM_EV), and deliberately so: a
# single-geometry spectrum is a handful of stick transitions that need
# enough broadening to read as a band at all, whereas a nuclear ensemble
# already carries its own width -- the spread of the sampled geometries IS
# the band shape. Broadening it as hard as a stick spectrum washes out the
# structure the ensemble was run to resolve.
#
# This is the one place the number lives. app/agent/tools.py's
# plot_wigner_ensemble_spectrum and ensemble_orchestrator.py's on-completion
# auto-render both import it rather than repeating a literal, which they
# previously did -- three copies of 0.4 that had to be changed together.
DEFAULT_ENSEMBLE_FWHM_EV = 0.2

# ---------------------------------------------------------- condition DSL
#
# A condition is a plain JSON-serializable dict, evaluated against a flat
# context: {"task", "subtype", "method", "engine", **params}.
#
#   {"always": True}                     -- unconditional
#   {"eq": ["method", "dft"]}            -- field equals value
#   {"in": ["method", ["casscf", ...]]}  -- field is one of
#   {"truthy": "want_oscillator_strengths"}
#   {"missing": "functional"}            -- field absent/None/empty
#   {"all": [cond, ...]}                 -- conjunction
#   {"any": [cond, ...]}                 -- disjunction
#   {"not": cond}                        -- negation

ALWAYS: dict = {"always": True}
NEVER: dict = {"not": {"always": True}}


def _is_empty(value: Any) -> bool:
    return value is None or value == "" or value == []


def evaluate(condition: Optional[dict], context: dict) -> bool:
    """Evaluate one condition against a flat context.

    An absent condition is False, not True: a rule that forgot to say when
    it applies must not silently apply always.
    """
    if not condition:
        return False
    if "always" in condition:
        return bool(condition["always"])
    if "eq" in condition:
        field_name, expected = condition["eq"]
        return context.get(field_name) == expected
    if "in" in condition:
        field_name, allowed = condition["in"]
        return context.get(field_name) in allowed
    if "truthy" in condition:
        return bool(context.get(condition["truthy"]))
    if "missing" in condition:
        return _is_empty(context.get(condition["missing"]))
    if "all" in condition:
        return all(evaluate(c, context) for c in condition["all"])
    if "any" in condition:
        return any(evaluate(c, context) for c in condition["any"])
    if "not" in condition:
        return not evaluate(condition["not"], context)
    raise ValueError(f"unknown condition {condition!r}")


@dataclass(frozen=True)
class ParamSpec:
    """One parameter, and the conditions under which it is needed.

    `default is None` combined with `required_when` truthy means the
    parameter is elicited rather than assumed. Several parameters here have
    **no default on purpose** -- `preopt`, `n_samples`, `state_pairs` --
    because silently picking a value for them makes a consequential choice
    on the user's behalf and hides it behind an approval card that looks
    like it was asked for.
    """
    name: str
    type: str                             # str | int | float | bool | list | dict
    label: str = ""
    help: str = ""
    # When this parameter is meaningful at all, within the tasks it
    # applies to. `None` means always. Distinct from `required_when`,
    # which says when a *meaningful* parameter must be supplied rather
    # than defaulted: `isoval` is meaningful only once orbitals are being
    # rendered, but even then it has a perfectly good default and is never
    # asked for. Without this distinction a default leaks onto every
    # approval card that does not use it -- an isosurface threshold on a
    # gradient job, a Tamm-Dancoff flag on a CASSCF one -- which teaches
    # the reader that the card lists parameters nothing acts on.
    applies_when: Optional[dict] = None
    # The question to put to the user verbatim when this is required and
    # missing. The model relays it; it does not compose its own.
    ask: str = ""
    options: tuple[Any, ...] = ()
    default: Any = None
    required_when: Optional[dict] = None
    # (condition, message) pairs -- surfaced on the approval card when the
    # condition holds. Never a refusal.
    warn_when: tuple[tuple[dict, str], ...] = ()
    # Tasks this parameter applies to. Entries are either "task" (any
    # subtype) or "task/subtype".
    applies_to: tuple[str, ...] = ()

    def applies(self, task: str, subtype: str = "") -> bool:
        full = f"{task}/{subtype}" if subtype else task
        return any(a == task or a == full for a in self.applies_to)

    def is_active(self, context: dict) -> bool:
        """Applies to this task *and* is meaningful in this context."""
        if not self.applies(context.get("task", ""), context.get("subtype", "") or ""):
            return False
        return self.applies_when is None or evaluate(self.applies_when, context)

    def is_required(self, context: dict) -> bool:
        return evaluate(self.required_when, context)

    def warnings(self, context: dict) -> tuple[str, ...]:
        return tuple(msg for cond, msg in self.warn_when if evaluate(cond, context))

    def to_dict(self) -> dict:
        """Serializable form for the registry API. Conditions travel as-is
        so the frontend evaluates the same rules the backend does."""
        return {
            "name": self.name, "type": self.type, "label": self.label or self.name,
            "help": self.help, "ask": self.ask, "options": list(self.options),
            "default": self.default, "required_when": self.required_when,
            "applies_when": self.applies_when,
            "warn_when": [{"when": c, "message": m} for c, m in self.warn_when],
            "applies_to": list(self.applies_to),
        }


# Task groups, so a spec's applies_to stays readable.
_ALL_COMPUTE = (
    "single_point", "opt", "freq", "opt_freq", "pes_1d", "interp_pes",
    "neb_ts", "wigner_spectra", "cas_reco", "batch",
)
_EXCITED = ("single_point/ee", "single_point/nac", "opt/ci", "wigner_spectra")
# Tasks resolved from ONE geometry -- the single-geometry job family
# (single_point/opt/freq/opt_freq, every subtype) plus the start/reactant
# endpoint of pes_1d/interp_pes/neb_ts. Matches
# geometry_resolve.NO_SINGLE_GEOMETRY_TASKS's complement, minus
# geometry_set/wigner_spectra/batch/blind, which take their geometry (or
# geometries) some other way entirely rather than from state["molecule"].
_SINGLE_GEOMETRY_TASKS = (
    "single_point", "opt", "freq", "opt_freq", "pes_1d", "interp_pes", "neb_ts",
)
# No cas_reco subtype appears here. autocas and avas *produce* an active
# space, so asking a user for one before recommending one to them is the
# exact behaviour the previous toolset had to warn the model off in prose.
# The one case that did take a space as its input -- cas_reco/explain --
# is no longer a job at all (see tasks.py), so there is nothing left in
# this family that a user supplies an active space for.
_CAS = ("single_point/ee", "single_point/gs", "opt", "freq", "opt_freq")
# _CAS plus single_point/grad and single_point/nac, which active_electrons/
# active_orbitals above don't cover (grad/nac get their CAS-space params
# some other way -- not this ParamSpec's concern) but which DO run a real
# CASSCF/CASPT2 calculation and so ARE valid destinations (and, once
# completed, valid sources) for orbital reuse.
_CAS_TASKS = _CAS + ("single_point/grad", "single_point/nac")

_MULTIREF = ("casscf", "caspt2")
_SINGLEREF = ("hf", "dft", "mp2", "ccsd", "eom_ccsd")
# Public alias: elicitation.py's zero-excited-states auto-route (n_states=0
# on a single_point/ee draft means "ground state only", which for a
# single-reference method is a plain single_point/gs request, not a
# degenerate excited-state one) needs to tell single- from multi-reference
# methods apart without reaching into a leading-underscore module constant.
SINGLEREF_METHODS = _SINGLEREF
# Public alias, same reasoning: elicitation's scan promotion has to read
# n_states differently per method family, because the number means different
# things. For casscf/caspt2 it counts state-averaged roots INCLUDING the
# ground state, so n_states=1 is a ground-state scan; for a single-reference
# method it counts excited states ABOVE the ground state, so n_states=1 is
# already an excited-state scan. Getting that boundary wrong turns a plain
# CASSCF scan into an excited-state one nobody asked for.
MULTIREF_METHODS = _MULTIREF


PARAMS: tuple[ParamSpec, ...] = (
    ParamSpec(
        name="method", type="str", label="Method",
        help="The level of theory: hf, dft, mp2, ccsd, eom_ccsd, casscf or caspt2. "
             "CIS, TDA and full TDDFT are not separate methods -- they are hf or dft "
             "with the use_tda parameter.",
        ask="Which level of theory should this use -- for example HF, DFT (with a "
            "functional), CASSCF, or CASPT2?",
        options=("hf", "dft", "mp2", "ccsd", "eom_ccsd", "casscf", "caspt2"),
        required_when=ALWAYS,
        applies_to=_ALL_COMPUTE,
    ),
    ParamSpec(
        name="basis", type="str", label="Basis set",
        help="Basis set name, e.g. sto-3g, 6-31g*, cc-pvdz, def2-svp. Anything the "
             "Basis Set Exchange knows can be resolved by name.",
        ask="Which basis set should this use (for example sto-3g, 6-31g*, cc-pvdz or "
            "def2-svp)?",
        required_when=ALWAYS,
        # The same misreading the n_states caveat below guards against. A
        # recommendation looks like it screens the chemistry and then runs a
        # CASSCF in whatever basis you name at the end -- it does not. The
        # basis builds the Mole that feeds RHF, AVAS, the pilot CASCI, the
        # entropies and the plateau search, so it is upstream of the
        # recommendation, not a setting on the calculation after it.
        warn_when=(
            ({"eq": ["subtype", "autocas"]},
             "The basis governs the whole recommendation, not just the CASSCF at the "
             "end of it -- AVAS, the pilot CASCI and the entropies are all computed in "
             "it, so a different basis can recommend a different active space."),
            ({"eq": ["subtype", "avas"]},
             "The basis governs which orbitals AVAS selects, not just the CASSCF run in "
             "them -- a different basis can give a different active space."),
        ),
        applies_to=_ALL_COMPUTE,
    ),
    ParamSpec(
        name="functional", type="str", label="Functional",
        # wb97x-d (bare, no dispersion-version digit) used to be the third
        # example here and is wrong on both engines this app supports, for
        # opposite reasons -- see docs/PARSER_GAPS.md. wb97x-d3 is ORCA's
        # real name for it; PySCF has no working gradient for either form.
        help="DFT exchange-correlation functional, e.g. b3lyp, pbe0, wb97x.",
        ask="Which exchange-correlation functional should the DFT calculation use "
            "(for example b3lyp, pbe0 or wb97x)?",
        # The cross-field rule that the legacy registry expressed as a
        # special case inside missing_required_params().
        required_when={"eq": ["method", "dft"]},
        # Scoped to contexts that actually take an excited-state gradient,
        # AND to the exact functional names this app checks for -- PBE0 and
        # every other functional in the same excited-state-gradient context
        # is unaffected and must not see a warning that does not apply to
        # it. `functional` arrives lowercased by `build_context`.
        warn_when=((
            {"all": [
                {"eq": ["method", "dft"]},
                {"eq": ["engine", "orca"]},
                {"in": ["functional", ["b3lyp", "blyp"]]},
                {"any": [
                    {"in": ["subtype", ["ee", "nac", "ci"]]},
                    {"eq": ["task", "wigner_spectra"]},
                    {"truthy": "target_state"},
                ]},
            ]},
            "ORCA refuses excited-state gradients for B88-containing functionals "
            "(B3LYP, BLYP) through its native path, and this app has no working substitute "
            "for that combination (a %method LibXC rewrite was tried and produced a wrong "
            "ground-state energy -- see docs/PARSER_GAPS.md) -- for single_point/grad the job "
            "is refused rather than run with a wrong functional. Ask for a different "
            "functional (e.g. PBE0) or engine.",
        ),),
        applies_to=_ALL_COMPUTE,
    ),
    ParamSpec(
        name="active_electrons", type="int", label="Active electrons",
        help="Number of electrons in the CAS active space.",
        ask="How many electrons should the active space contain?",
        required_when={"in": ["method", list(_MULTIREF)]},
        applies_to=_CAS + ("pes_1d", "interp_pes", "neb_ts", "wigner_spectra"),
    ),
    ParamSpec(
        name="active_orbitals", type="int", label="Active orbitals",
        help="Number of orbitals in the CAS active space.",
        ask="How many orbitals should the active space contain?",
        required_when={"in": ["method", list(_MULTIREF)]},
        applies_to=_CAS + ("pes_1d", "interp_pes", "neb_ts", "wigner_spectra"),
    ),
    ParamSpec(
        name="n_states", type="int", label="Number of states",
        # The semantics the plan asks to be encoded declaratively rather
        # than as prompt prose, because getting it wrong silently changes
        # what is computed: a CAS(4,4) with n_states=3 state-averages over
        # S0, S1, S2, while TDDFT with n_states=3 gives S1, S2, S3 on top
        # of a separate ground state.
        help="How many electronic states to compute. For the multireference methods "
             "(casscf, caspt2) this is the number of state-averaged roots and it "
             "INCLUDES the ground state, so n_states=3 means S0, S1 and S2. For the "
             "single-reference methods it is the number of EXCITED states computed on "
             "top of the ground state, so n_states=3 means S1, S2 and S3.",
        ask="How many electronic states should this compute? (For CASSCF/CASPT2 the "
            "count includes the ground state; for TDDFT/CIS/EOM-CCSD it is the number "
            "of excited states above it.)",
        # `ci` is in this list because a conical-intersection optimization
        # follows two roots of a state average: without n_states there is
        # no state average for target_state/target_state_2 to index into,
        # and the job would be built on a single-root calculation that
        # cannot express a crossing at all.
        required_when={"any": [
            {"in": ["subtype", ["ee", "nac", "ci"]]},
            {"eq": ["task", "wigner_spectra"]},
            # Both recommendation subtypes end in a state-averaged CASSCF,
            # so both need the root count. avas was missing from this list
            # while it shared autocas's runner and the omission was
            # invisible; on its own path it would silently default to a
            # single root for a user who asked for three.
            {"in": ["subtype", ["autocas", "avas"]]},
            # An excited-state scan reached by someone writing subtype="ee"
            # directly rather than through elicitation's promotion (which
            # only fires BECAUSE n_states is already there). Without this
            # clause that draft reaches READY with no root count and every
            # image runs a one-state calculation, which is the bug this
            # parameter's scan support exists to fix.
            {"all": [{"in": ["task", ["pes_1d", "interp_pes"]]},
                     {"eq": ["subtype", "ee"]}]},
        ]},
        warn_when=(
            ({"in": ["method", list(_MULTIREF)]},
             "For a multireference method n_states counts the state-averaged roots "
             "including the ground state."),
            ({"in": ["method", list(_SINGLEREF)]},
             "For a single-reference method n_states counts excited states above the "
             "ground state, which is computed separately."),
            # Not a restatement of the line above. It is natural to read the
            # state count as governing only the CASSCF at the end of a
            # recommendation, and for AutoCAS it does not: the F-020 widening
            # adds orbitals along the entropy ranking until the space can host
            # the roots asked for, so part of the recommended space can come
            # from this number rather than from the chemistry. A user who
            # believes otherwise reads a widened space as the algorithm's own
            # verdict on their molecule.
            ({"eq": ["subtype", "autocas"]},
             "n_states also shapes the recommendation itself, not just the CASSCF at "
             "the end of it: if the selected space cannot host this many roots, it is "
             "widened along the entropy ranking until it can."),
        ),
        # The bare task names, not "pes_1d/ee"/"interp_pes/ee". `applies`
        # matches `a == task or a == full`, so a bare name covers every
        # subtype of that task, and that is the point: this parameter has to
        # be writable onto a FRESH scan draft, which still has subtype "" --
        # it is what elicitation promotes to the excited-state subtype ON.
        # Scoped to /ee only, the model would be refused the very parameter
        # that gets it there.
        applies_to=_EXCITED + ("cas_reco", "pes_1d", "interp_pes"),
    ),
    ParamSpec(
        name="use_tda", type="bool", label="Tamm-Dancoff approximation",
        help="False (the default) gives full TDDFT with a DFT reference, or TD-HF/RPA "
             "with an HF reference. True gives TDA-DFT, or CIS with an HF reference.",
        ask="Should this use the Tamm-Dancoff approximation, or full TDDFT?",
        # Full TDDFT is the default; TDA is opt-in. TDA is cheaper and
        # avoids triplet instabilities, but it is an approximation to the
        # linear response, and a user who asks for "a TDDFT spectrum"
        # means the real thing. Defaulting to the approximation and not
        # saying so was the kind of silent substitution this registry
        # exists to stop.
        default=False,
        # Stated on the approval card either way. Which of the two was
        # used changes the excitation energies by tenths of an eV and
        # changes whether a triplet instability shows up at all, so
        # "TDDFT" alone on a card is not enough to know what ran.
        warn_when=(
            ({"all": [{"not": {"truthy": "use_tda"}}, {"eq": ["method", "dft"]}]},
             "Full TDDFT (the complete linear response, not the Tamm-Dancoff "
             "approximation)."),
            ({"all": [{"not": {"truthy": "use_tda"}}, {"eq": ["method", "hf"]}]},
             "TD-HF/RPA (the complete linear response, not CIS)."),
            ({"all": [{"truthy": "use_tda"}, {"eq": ["method", "dft"]}]},
             "TDA-DFT -- the Tamm-Dancoff approximation, cheaper than full TDDFT and "
             "less prone to triplet instabilities, but an approximation to it."),
            ({"all": [{"truthy": "use_tda"}, {"eq": ["method", "hf"]}]},
             "CIS -- the Tamm-Dancoff approximation applied to an HF reference."),
        ),
        # TDA is an approximation to the linear-response equations of a
        # single-reference excited-state method. A CASSCF or CASPT2 state
        # average does not solve those equations at all, so the flag is not
        # merely defaulted there -- it is meaningless, and showing it on a
        # CASSCF approval card implies a choice that does not exist.
        applies_when={"in": ["method", list(_SINGLEREF)]},
        # The /ee subtypes specifically, unlike n_states just above, which
        # lists the bare task names because it has to be writable on a scan
        # draft before the subtype exists. This one has a default of False,
        # so a bare task name would put "Tamm-Dancoff: no" on the approval
        # card of every GROUND-STATE scan -- a choice about a linear
        # response that a ground-state scan never solves.
        applies_to=("single_point/ee", "wigner_spectra", "pes_1d/ee", "interp_pes/ee"),
    ),
    ParamSpec(
        name="want_oscillator_strengths", type="bool", label="Oscillator strengths",
        help="Compute transition intensities, not only excitation energies. Routes a "
             "CASSCF job to ORCA, the only engine here that computes them; for CASPT2 "
             "it enables BAGEL's forces+dipole mechanism, one extra gradient per state.",
        ask="Do you want oscillator strengths (transition intensities) as well as the "
            "excitation energies?",
        default=False,
        applies_to=("single_point/ee", "wigner_spectra"),
    ),
    ParamSpec(
        name="state_pairs", type="list", label="State pairs",
        help="Which pairs of electronic states to couple, as 1-based pairs, e.g. "
             "[[1, 2]] for the S0/S1 coupling. There is no default: the pair is the "
             "whole content of the request.",
        ask="Between which pair of electronic states should the non-adiabatic coupling "
            "be computed? Give them as a pair, for example S0 and S1.",
        required_when=ALWAYS,
        # The single-reference counterpart of the multireference note below
        # is deliberately absent: `tasks._warn_nac_pairing` already says it,
        # and says it better, because it names the engine that was actually
        # routed to instead of hardcoding ORCA. Stating it in both places
        # put two near-identical sentences on the same approval card.
        warn_when=(
            ({"in": ["method", list(_MULTIREF)]},
             "State-averaged multireference couplings are available for any pair of "
             "roots inside the state average."),
        ),
        applies_to=("single_point/nac",),
    ),
    ParamSpec(
        name="constraints", type="list", label="Constraints",
        help="Internal coordinates held fixed during the optimization, e.g. "
             "[{'type': 'bond', 'atoms': [1, 2], 'value': 0.98}]. Atom numbers are "
             "1-based, matching the 3D viewer.",
        ask="Which coordinates should be held fixed, and at what values? Atom numbers "
            "are the ones shown in the 3D viewer.",
        required_when=ALWAYS,
        applies_to=("opt/constrained",),
    ),
    ParamSpec(
        name="target_state", type="int", label="Target state",
        help="Which electronic state's surface to optimize or differentiate on. Omit "
             "for the ground state.",
        ask="Which electronic state should this follow -- the ground state, or an "
            "excited one?",
        # Optional everywhere except a conical-intersection optimization,
        # which is defined by the pair of states whose surfaces cross. There
        # the ground-state default is not a sensible fallback, it is a
        # different calculation.
        required_when={"eq": ["subtype", "ci"]},
        applies_to=("opt", "freq", "opt_freq", "neb_ts", "single_point/grad"),
    ),
    ParamSpec(
        name="target_state_2", type="int", label="Second state",
        help="The second state defining the crossing seam for a conical-intersection "
             "optimization.",
        ask="Which second electronic state defines the crossing seam with the target "
            "state?",
        required_when=ALWAYS,
        applies_to=("opt/ci",),
    ),
    ParamSpec(
        name="preopt", type="bool", label="Pre-optimize endpoints",
        # No default, at the user's explicit instruction: the agent must
        # always ask rather than silently choosing either way.
        help="Whether to relax the reactant and product structures to their own minima "
             "before the band search. No default -- it is always asked.",
        ask="Should the reactant and product geometries be pre-optimized to their own "
            "minima before the NEB search? (Skip it if they already came from a "
            "geometry optimization.)",
        required_when=ALWAYS,
        applies_to=("neb_ts",),
    ),
    ParamSpec(
        name="n_images", type="int", label="Images",
        help="Movable images between the two fixed endpoints. The path length shown in "
             "the UI is n_images + 2.",
        ask="How many movable images should the band have?",
        default=6,
        applies_to=("neb_ts",),
    ),
    # Declaration order is the order these get asked in (missing_required
    # walks params_for in order), so it is a real part of the interface.
    # A scan was asking how many points to sample before asking what was
    # being scanned, which is a question nobody can answer in that order.
    # Coordinate, then range, then sampling density.
    ParamSpec(
        name="coordinate", type="dict", label="Scanned coordinate",
        help="The internal coordinate to step, e.g. {'type': 'bond', 'atoms': [1, 2]} "
             "or {'type': 'dihedral', 'atoms': [1, 2, 3, 4]}. Atom numbers are 1-based.",
        ask="Which internal coordinate should be scanned, and over which atoms? Atom "
            "numbers are the ones shown in the 3D viewer.",
        required_when=ALWAYS,
        applies_to=("pes_1d",),
    ),
    ParamSpec(
        name="scan_range", type="list", label="Scan range",
        help="[start, stop] for the scanned coordinate -- angstrom for a bond, degrees "
             "for an angle or dihedral.",
        ask="Over what range should the coordinate be scanned?",
        required_when=ALWAYS,
        applies_to=("pes_1d",),
    ),
    ParamSpec(
        name="n_points", type="int", label="Points",
        help="Number of points sampled along the scan, including both endpoints.",
        ask="How many points should the scan sample, counting both endpoints?",
        required_when=ALWAYS,
        applies_to=("pes_1d", "interp_pes"),
    ),
    ParamSpec(
        name="interpolation_method", type="str", label="Interpolation",
        help="idpp (default, avoids atom clashes), liic (linear in internal "
             "coordinates), or linear (naive Cartesian, cheapest but can produce "
             "unphysical intermediates).",
        ask="How should the path between the two geometries be built -- IDPP, LIIC or "
            "linear Cartesian?",
        options=("idpp", "liic", "linear"),
        default="idpp",
        applies_to=("interp_pes",),
    ),
    ParamSpec(
        name="source_frequency_job_id", type="str", label="Source frequency job",
        help="A completed frequency job whose normal modes are sampled. Its own "
             "geometry is used, so the samples stay consistent with the modes.",
        # Naming both routes out is the point of this wording. A
        # nuclear-ensemble spectrum cannot be sampled out of thin air -- it
        # needs somebody's normal modes -- and a user who asks for one
        # without having run a frequency calculation first has not made a
        # mistake, they just do not yet know this is a two-step job. Bare
        # "which job id?" strands both kinds of user: the one who has the
        # job but not its id in front of them, and the one who has no such
        # job at all. So the ask points the first at the Jobs panel's
        # "Attach to prompt" button, which is how a job id actually reaches
        # a prompt in this app, and offers the second the frequency
        # calculation itself as the next thing to approve.
        ask="A nuclear-ensemble spectrum is sampled from a molecule's vibrations, so "
            "it needs a finished frequency calculation to draw its geometries from. "
            "Pick one in the Jobs panel and hit \"Attach to prompt\", or give me its "
            "job id. If you haven't run a frequency calculation yet, say so and I'll "
            "set one up first -- the ensemble can be sampled from it once it "
            "finishes.",
        required_when=ALWAYS,
        applies_to=("wigner_spectra",),
    ),
    ParamSpec(
        name="source_job_id", type="str", label="Source job",
        # Any completed job whose result carries a multi-frame geometry
        # artifact -- geometry_set, pes_1d, interp_pes, wigner_spectra,
        # neb_ts (see tasks.BATCH_GEOMETRY_SOURCE_ARTIFACT_KEY for exactly
        # which artifact key each one uses). NOT required when
        # elicitation.py's own special-case step has already resolved
        # `_frame_geometries` instead (3+ individually-tagged molecule
        # panel frames, the same "tagged geometries" input shape
        # `_end_molecule` already uses for interp_pes/neb_ts's own second
        # endpoint) -- that resolution is not expressed as a declared
        # ParamSpec of its own for the same reason `_end_molecule` isn't:
        # it is never something a user types into a field, only ever
        # derived from state.
        help="A completed job to pull geometries from -- a geometry set, a 1D PES "
             "scan, an interpolated path, a nuclear-ensemble (Wigner) sample set, or "
             "a NEB-TS run. One child job is dispatched per geometry the source job "
             "produced. Not needed if 3 or more structures are already tagged in the "
             "molecule panel -- those are used instead.",
        ask="Which job should this batch pull its geometries from? Give its job id, or "
            "put 3 or more structures in the molecule panel and I'll use those instead.",
        required_when={"missing": "_frame_geometries"},
        applies_to=("batch",),
    ),
    ParamSpec(
        name="child_task", type="str", label="Job type",
        # Required, no default -- same reasoning neb_ts's own `preopt`
        # ParamSpec gives for never defaulting: a user asking to "optimize
        # all of these" who silently got single points back because the
        # model omitted the field would be a wrong answer, not a
        # convenience. Scoped to job types 1-4 (single_point, opt, freq,
        # opt_freq) -- the plan's own numbered job-type table -- not opt's
        # constrained/ci subtypes, which need per-geometry params (a
        # constraint shape, a CI state pair) that do not generalize across
        # a batch the same way a plain method+basis does.
        help="Which calculation to run on every geometry in the set: a single-point "
             "energy, a geometry optimization, a frequency calculation, or "
             "optimization followed by frequencies.",
        ask="What should run on every geometry in this batch -- single-point energy, "
            "optimization, frequencies, or optimization + frequencies?",
        options=("single_point", "opt", "freq", "opt_freq"),
        required_when=ALWAYS,
        applies_to=("batch",),
    ),
    ParamSpec(
        name="n_samples", type="int", label="Samples",
        # No silent default: the value drives both cost and spectral
        # quality. Default 50, cap 500 per the plan's recorded decision --
        # the default is offered in the question, not applied unasked.
        help="How many geometries to sample. 50 is a reasonable starting point; the "
             "hard cap is 500.",
        ask="How many geometries should the ensemble sample? 50 is a good default; the "
            "maximum is 500.",
        required_when=ALWAYS,
        applies_to=("wigner_spectra",),
    ),
    ParamSpec(
        name="fwhm_eV", type="float", label="Broadening (eV)",
        help="Gaussian broadening applied to each pooled transition when the spectrum "
             "is rendered.",
        ask="How much Gaussian broadening should the spectrum use, in eV?",
        default=DEFAULT_ENSEMBLE_FWHM_EV,
        applies_to=("wigner_spectra",),
    ),
    ParamSpec(
        name="low_freq_cutoff_cm1", type="float", label="Low-frequency cutoff",
        help="Modes below this wavenumber are excluded from sampling as "
             "translational/rotational residue. A retained soft mode inflates the "
             "sampling amplitude as roughly 1/sqrt(frequency).",
        ask="Below which wavenumber should modes be excluded from the sampling?",
        default=100.0,
        applies_to=("wigner_spectra",),
    ),
    ParamSpec(
        name="orbital_indices", type="list", label="Orbitals",
        # Optional, and a parameter of single_point rather than of a task
        # of its own: rendering orbitals is a way of looking at a
        # calculation that has already been done, not a different
        # calculation. Setting it asks for the cube files alongside the
        # ordinary single-point output.
        help="Which orbitals to render as isosurfaces -- 'HOMO', 'LUMO', 'HOMO-1', or a "
             "1-based index. Omit to skip orbital rendering entirely.",
        ask="Which molecular orbitals should be rendered (for example HOMO, LUMO, or "
            "an orbital number)?",
        applies_to=("single_point",),
    ),
    ParamSpec(
        name="isoval", type="float", label="Isosurface value",
        help="Isosurface threshold for the rendered orbitals.",
        ask="What isosurface value should the orbitals be rendered at?",
        default=0.04,
        # Only once there are orbitals to render. Otherwise every
        # single-point approval card -- including a plain gradient -- shows
        # an isosurface threshold that nothing reads.
        applies_when={"truthy": "orbital_indices"},
        applies_to=("single_point",),
    ),
    ParamSpec(
        name="raw_input_text", type="str", label="Input text",
        help="The complete literal ORCA or BAGEL input, used byte-for-byte with no "
             "structured parameter building and no task-specific output parsing.",
        ask="Paste the complete input file you want run.",
        required_when=ALWAYS,
        applies_to=("blind",),
    ),
    ParamSpec(
        name="entropy_method", type="str", label="Entropy pilot",
        help="exact_fci (default) is exact for the pilot space and capped at 12 "
             "orbitals; dmrg is approximate but polynomial-cost and screens a much "
             "larger candidate pool, up to 30. Only the pilot screening changes -- the "
             "final recommended space and its CASSCF are unaffected either way. dmrg "
             "needs the optional block2 package (requirements-optional.txt); where it "
             "is not installed the option is refused rather than offered and failed on, "
             "and it cannot state-average the pilot in any case.",
        ask="Should the entropy pilot use exact FCI (fast, capped at 12 orbitals) or "
            "DMRG (slower, screens a larger candidate pool)?",
        options=("exact_fci", "dmrg"),
        default="exact_fci",
        applies_to=("cas_reco/autocas",),
    ),
    ParamSpec(
        name="entropy_pilot_states", type="int", label="Entropy pilot states",
        help="How many electronic states the entropy pilot screens over. 1 (the default) "
             "ranks orbitals by their entanglement in the ground state alone, which is "
             "blind to an orbital that only matters once you excite out of it -- a "
             "doubly-occupied lone pair carries almost no ground-state entanglement "
             "however much the n->pi* states depend on it. Screening over several states "
             "averages the density matrices across them, so those orbitals enter the "
             "ranking. Costs roughly in proportion to the number of states. Exact-FCI "
             "pilot only; the DMRG pilot cannot state-average in this deployment.",
        ask="How many electronic states should the entropy pilot screen over? (1 screens "
            "the ground state only; more will notice orbitals that matter for excited "
            "states.)",
        default=1,
        applies_to=("cas_reco/autocas",),
    ),
    ParamSpec(
        name="active_occupied_orbitals", type="int", label="Occupied orbitals to keep",
        help="How many of the kept orbitals come from the occupied side. Half the cap, "
             "rounded down, by default -- raise it to hold on to lone-pair and other "
             "non-bonding character, which an excited state that promotes out of a lone "
             "pair needs and a symmetric split cannot express. Means slightly different "
             "things per method: for AutoCAS it shapes the pilot pool that gets screened, "
             "for AVAS it shapes the final active space directly. Clamped, and reported, "
             "if the pool holds fewer occupied orbitals than asked for.",
        ask="How many of the active orbitals should be occupied ones? (Half, rounded "
            "down, by default.)",
        applies_to=("cas_reco",),
    ),
    ParamSpec(
        name="dmrg_bond_dim", type="int", label="DMRG bond dimension",
        help="Bond dimension for the DMRG entropy pilot. The pilot is deliberately "
             "cheap and unconverged -- it only has to rank orbitals by entanglement, "
             "not produce an energy -- so the default is low. Raising it screens the "
             "same pool more carefully at proportionally more cost.",
        ask="What bond dimension should the DMRG entropy pilot use?",
        default=250,
        # Only once the DMRG pilot is actually selected. Undeclared until
        # now, which was invisible while unknown draft keys were silently
        # absorbed into params -- the runner read it, so it worked -- and
        # became a real hole the moment they were refused: a parameter the
        # pipeline honours that no draft could set.
        applies_when={"eq": ["entropy_method", "dmrg"]},
        applies_to=("cas_reco/autocas",),
    ),
    ParamSpec(
        name="max_active_orbitals", type="int", label="Maximum active orbitals",
        help="The largest final active space to accept, and it does different work in "
             "each method. With AutoCAS it only ever narrows: the entropy plateau picks "
             "a size and this stops it exceeding one, so if the plateau lands below this "
             "the setting changes nothing. With AVAS it decides the size, because there "
             "is no screening step -- AVAS's own selection is truncated to this many "
             "orbitals nearest the Fermi level, and active_occupied_orbitals says how "
             "many of them come from the occupied side. Either way 12 is the ceiling, "
             "which is where the final CASSCF stops being feasible on this host; a "
             "larger value is refused rather than quietly reduced. Note this is not the "
             "size of the pool AutoCAS screens -- that is set by the pilot (12 orbitals "
             "for exact FCI, 30 for DMRG) and is not adjustable.",
        ask="What is the largest active space you would accept? (12 at most; with AVAS "
            "this sets the size, with AutoCAS it only caps it.)",
        default=12,
        applies_to=("cas_reco/autocas", "cas_reco/avas"),
    ),
    ParamSpec(
        name="avas_aolabels", type="list", label="AVAS labels",
        help="Atomic-orbital character labels seeding the valence space, e.g. "
             "['C 2p', 'N 2p']. Omit for the valence p/d shells of every non-hydrogen "
             "atom. Narrowing this deliberately can miss orbitals that should have "
             "been screened.",
        ask="Which atomic-orbital characters should seed the active space, for example "
            "'C 2p' or 'N 2p'?",
        applies_to=("cas_reco/avas", "cas_reco/autocas"),
    ),
    ParamSpec(
        name="temperature_K", type="float", label="Temperature (K)",
        help="Temperature for the thermochemistry corrections, or for Wigner sampling "
             "(0 K samples the vibrational ground state).",
        ask="At what temperature should this be evaluated?",
        default=298.15,
        applies_to=("freq", "opt_freq", "wigner_spectra"),
    ),
    ParamSpec(
        name="max_steps", type="int", label="Maximum steps",
        help="Optimizer step limit.",
        ask="How many optimization steps should be allowed before giving up?",
        default=200,
        applies_to=("opt", "opt_freq", "neb_ts"),
    ),
    ParamSpec(
        name="df_basis", type="str", label="Density-fitting basis",
        help="Auxiliary basis for BAGEL. Auto-derived from the main basis for the "
             "cc-pVXZ/SVP/TZVPP families, otherwise svp-jkfit.",
        ask="Which density-fitting basis should BAGEL use?",
        applies_to=_ALL_COMPUTE,
    ),
    ParamSpec(
        name="initial_orbitals_job_id", type="str", label="Initial orbitals from",
        # Never asked (no `ask`/required_when): this is populated only when
        # the user names a prior job to reuse, the same tag-driven shape
        # source_job_id/source_frequency_job_id take -- but unlike those
        # two, omitting it is always a valid, complete draft (a fresh HF
        # guess, this app's -- and BAGEL's/ORCA's/PySCF's own -- existing
        # default), so it carries no required_when at all. When present,
        # elicitation.py validates it against the job store (existence,
        # completed, CASSCF/CASPT2, same engine as this job resolves to --
        # orbital files are engine-specific formats, never converted
        # between engines here) and drops it with a note rather than
        # blocking the draft if it doesn't hold up.
        help="Seed this CASSCF/CASPT2 calculation's initial orbital guess from a "
             "completed CASSCF/CASPT2 job on the SAME engine, instead of starting "
             "from a fresh HF guess. Tag a prior job to use this.",
        applies_when={"in": ["method", list(_MULTIREF)]},
        applies_to=_CAS_TASKS,
    ),
    ParamSpec(
        name="source_geometry_job_id", type="str", label="Geometry from job",
        # Never asked (no `ask`/required_when), same shape
        # initial_orbitals_job_id above takes -- omitting it is always a
        # valid, complete draft, since the ordinary molecule-panel geometry
        # (state["molecule"]) remains the default. Populated only when the
        # user asks to reuse a specific prior job's geometry ("same
        # geometry as before", "repeat that with a bigger basis"), which
        # this app cannot infer on its own without a job id to resolve --
        # the model supplies one it already has from earlier in the
        # conversation (a job it just submitted or reported on), never one
        # it invents. elicitation.py resolves it via
        # geometry_resolve.resolve_single_completed_geometry (the same
        # function P9.2's geometry_parameters tool uses) and, unlike
        # initial_orbitals_job_id, does NOT silently drop an invalid tag --
        # a user who named a specific job's geometry and got a different,
        # unnamed one instead would be a wrong answer, not a convenience.
        help="Use a completed job's own geometry (its optimized geometry if it "
             "produced one, otherwise its input geometry) instead of what's in the "
             "molecule panel. Only for a job asking to reuse a specific prior "
             "calculation's structure.",
        applies_to=_SINGLE_GEOMETRY_TASKS,
    ),
    ParamSpec(
        name="weights", type="list", label="State-average weights",
        help="State-average weights for a multireference calculation; defaults to equal "
             "weights over n_states.",
        ask="What state-average weights should be used? Equal weights are the default.",
        applies_to=_EXCITED + ("cas_reco",),
    ),
)


PARAMS_BY_NAME: dict[str, ParamSpec] = {p.name: p for p in PARAMS}


def params_for(task: str, subtype: str = "") -> tuple[ParamSpec, ...]:
    """Every parameter that can apply to one task, in declaration order."""
    return tuple(p for p in PARAMS if p.applies(task, subtype))


def build_context(task: str, subtype: str, method: Optional[str],
                  engine: Optional[str], params: Optional[dict] = None) -> dict:
    """The flat context conditions are evaluated against.

    `functional` is normalized to a stripped lowercase string here, and only
    here -- the real `params` dict a caller passed in is untouched. It is
    free text (a user or the model may type "B3LYP", "b3lyp" or "B3lyp"),
    unlike `method`/`engine`/`task`/`subtype`, which are drawn from a
    controlled vocabulary this app itself sets. A DSL `eq`/`in` condition on
    `functional` would otherwise have to match by exact case, which a
    free-text field cannot promise.
    """
    context = dict(params or {})
    if isinstance(context.get("functional"), str):
        context["functional"] = context["functional"].strip().lower()
    context.update({"task": task, "subtype": subtype, "method": method, "engine": engine})
    return context


def missing_required(task: str, subtype: str, method: Optional[str],
                     engine: Optional[str], params: Optional[dict] = None) -> tuple[ParamSpec, ...]:
    """Parameters this job needs and does not have.

    The v2 replacement for `registry.missing_required_params()`, which
    returned bare names and had the one cross-field rule (dft implies a
    functional) hardcoded as an `if`. Here that rule is just this
    parameter's `required_when`, and the caller gets the whole spec back so
    it has the question to ask without a second lookup.
    """
    context = build_context(task, subtype, method, engine, params)
    out = []
    for spec in params_for(task, subtype):
        if not spec.is_active(context):
            continue
        if spec.is_required(context) and _is_empty(context.get(spec.name)):
            out.append(spec)
    return tuple(out)


def applicable_warnings(task: str, subtype: str, method: Optional[str],
                        engine: Optional[str], params: Optional[dict] = None) -> tuple[str, ...]:
    """Parameter-level caveats for the approval card."""
    context = build_context(task, subtype, method, engine, params)
    out: list[str] = []
    for spec in params_for(task, subtype):
        if not spec.is_active(context):
            continue
        if _is_empty(context.get(spec.name)) and not spec.is_required(context):
            continue
        out.extend(spec.warnings(context))
    return tuple(dict.fromkeys(out))


def defaults_for(task: str, subtype: str = "", context: Optional[dict] = None) -> dict:
    """Parameters with a real default, as a dict.

    Parameters deliberately left without one (preopt, n_samples,
    state_pairs) are absent, and so are parameters that are inactive in
    this context -- pass `context` (a `build_context()` result) to get that
    filtering. Without it the answer is the static, whole-task list, which
    is what the registry API and the doc generator want.
    """
    out = {}
    for p in params_for(task, subtype):
        if p.default is None:
            continue
        if context is not None and not p.is_active(context):
            continue
        out[p.name] = p.default
    return out


def serialize(specs: Optional[Sequence[ParamSpec]] = None) -> list[dict]:
    return [p.to_dict() for p in (specs if specs is not None else PARAMS)]
