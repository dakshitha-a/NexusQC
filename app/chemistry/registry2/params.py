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
    "neb_ts", "wigner_spectra", "cas_reco",
)
_EXCITED = ("single_point/ee", "single_point/nac", "opt/ci", "wigner_spectra")
# `cas_reco/explain` is here and the other two cas_reco subtypes are not:
# explaining a proposed active space takes that space as its input, while
# autocas and avas *produce* one. Asking a user for the active space
# before recommending an active space to them was the exact behaviour the
# previous toolset had to warn the model off in prose.
_CAS = ("single_point/ee", "single_point/gs", "opt", "freq", "opt_freq",
        "cas_reco/explain")

_MULTIREF = ("casscf", "caspt2")
_SINGLEREF = ("hf", "dft", "mp2", "ccsd", "eom_ccsd")


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
            {"eq": ["subtype", "autocas"]},
        ]},
        warn_when=(
            ({"in": ["method", list(_MULTIREF)]},
             "For a multireference method n_states counts the state-averaged roots "
             "including the ground state."),
            ({"in": ["method", list(_SINGLEREF)]},
             "For a single-reference method n_states counts excited states above the "
             "ground state, which is computed separately."),
        ),
        applies_to=_EXCITED + ("cas_reco",),
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
        applies_to=("single_point/ee", "wigner_spectra"),
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
    ParamSpec(
        name="n_points", type="int", label="Points",
        help="Number of points sampled along the scan, including both endpoints.",
        ask="How many points should the scan sample, counting both endpoints?",
        required_when=ALWAYS,
        applies_to=("pes_1d", "interp_pes"),
    ),
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
        ask="Which completed frequency job should the ensemble be sampled from?",
        required_when=ALWAYS,
        applies_to=("wigner_spectra",),
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
        default=0.4,
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
             "larger candidate pool. Only the pilot screening changes -- the final "
             "recommended space and its CASSCF are unaffected either way.",
        ask="Should the entropy pilot use exact FCI (fast, capped at 12 orbitals) or "
            "DMRG (slower, screens a larger candidate pool)?",
        options=("exact_fci", "dmrg"),
        default="exact_fci",
        applies_to=("cas_reco/autocas",),
    ),
    ParamSpec(
        name="max_active_orbitals", type="int", label="Maximum active orbitals",
        help="The largest final active space to recommend. Can only narrow the result; "
             "the final CASSCF is capped at 12 regardless.",
        ask="What is the largest active space you would accept as a recommendation?",
        default=12,
        # Only where something is being recommended. `cas_reco/explain`
        # takes a space the user already chose and explains it against the
        # literature; a ceiling on a recommendation that is not being made
        # is one more parameter on the card that nothing reads.
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
