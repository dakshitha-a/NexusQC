"""The backend decides what a job draft is still missing, and what to ask.

This is the module that takes the elicitation decision away from the model.

The old arrangement spread that decision across three places: prose in the
system prompt listing which parameters each job type needed, a hardcoded
`if method == "dft"` inside `registry.missing_required_params()`, and the
model's own judgement about when it had enough to submit. The failure mode
was not that the model asked badly -- it was that the model decided *what*
to ask, so a rule the prompt did not mention was a rule that did not exist,
and a job would reach the backend missing a field only the backend knew
about.

Here the model never makes that decision. It maintains a draft, calls
`validate_draft()` after every change, and either relays the returned
question **verbatim** or presents the returned preview for approval. The
question text comes from `ParamSpec.ask` (params.py), the engine choice
from `routing.route_engine()`, the capability verdict from
`tasks.supports()`, and the spelling menus from the same `keyword_suggest`
pools the previous toolset already used. Nothing here is new chemistry
knowledge; it is the existing knowledge arranged so a model cannot skip it.

Two properties are deliberate and worth not breaking:

**One question at a time, in a fixed order.** A verdict carries exactly one
`ask_user_exactly` string. Returning a list of everything missing invites
the model to summarize it in its own words, which is precisely the
paraphrasing this module exists to remove -- and a wall of six questions is
worse conversation than six exchanges. The order is fixed (state, then
level of theory, then parameters in `PARAMS` declaration order) so a
conversation is reproducible and a test can assert the exact sequence.

**Nothing is guessed.** A parameter with no default is asked for, never
filled in. `preopt`, `n_samples` and `state_pairs` have no default on
purpose (see params.py), and an unavailable engine/method combination comes
back as `unavailable` with every engine's refusal attached, rather than
being quietly rerouted to something that would run but answer a different
question.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

from app.chemistry.jobs import keyword_suggest, param_normalize
from app.chemistry.registry2.lookup import (
    resolve_method, resolve_task, suggest_basis, suggest_functional,
)
from app.chemistry.registry2.params import (
    PARAMS_BY_NAME, applicable_warnings, build_context, defaults_for, missing_required,
    params_for,
)
from app.chemistry.registry2.routing import route_engine
from app.chemistry.registry2.tasks import TASKS, get_task, supports

# Draft keys that are not parameters. Anything else the model writes into a
# draft is folded into `params`, because a model that puts `basis` at the
# top level instead of inside `params` has made a formatting mistake, not a
# chemistry one, and rejecting it would spend a conversation turn teaching
# the model a shape it will forget by the next thread.
STRUCTURAL_KEYS = ("task", "subtype", "method", "engine", "params")

# Tasks that compute nothing on a structure of their own: a blind text
# input carries its own geometry, a batch and a geometry set hold others,
# and a nuclear-ensemble spectrum samples its geometries from the
# frequency job it is built on.
_NO_MOLECULE = {"blind", "batch", "geometry_set", "wigner_spectra"}

# Tasks defined by a path between two structures rather than by one.
_NEEDS_END_GEOMETRY = {"interp_pes", "neb_ts"}

# Kept identical to the sentinel the previous toolset appended, because the
# frontend's approval card and the shorthand-reply convention ("1b" picks
# functional 1 and basis b) both key on this exact string.
BSE_SEARCH_OPTION = "(search Basis Set Exchange for the exact basis set)"

_BASIS_LETTERS = "abcdefghijklmnopqrstuvwxyz"


@dataclass(frozen=True)
class DraftVerdict:
    """What the backend decided about one draft.

    `status` is the only thing a caller must branch on:

    - `incomplete` -- `ask_user_exactly` holds the next question, to be
      relayed word for word. `options` holds its menu, if it has one.
    - `unavailable` -- no engine here can run the combination. `refusals`
      says why, per engine; `alternatives` lists engines that could run the
      task at some other method. `ask_user_exactly` still holds a question,
      so the model always has something to say rather than composing an
      apology of its own.
    - `ready` -- `draft` is complete and normalized, `preview` describes it
      for the approval card, and `warnings` holds the caveats that card
      must show.
    """
    status: str
    draft: dict
    ask_user_exactly: str = ""
    asking_for: str = ""
    options: tuple[Any, ...] = ()
    missing: tuple[str, ...] = ()
    notes: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()
    refusals: tuple[str, ...] = ()
    alternatives: tuple[str, ...] = ()
    routing_reason: str = ""
    keyword_options: Optional[dict] = None
    preview: Optional[dict] = None

    @property
    def ready(self) -> bool:
        return self.status == "ready"

    def to_dict(self) -> dict:
        """Flat, JSON-safe form -- what the agent tool returns and what a
        test asserts against."""
        out = {
            "status": self.status,
            "draft": self.draft,
            "ask_user_exactly": self.ask_user_exactly,
            "asking_for": self.asking_for,
            "options": list(self.options),
            "missing": list(self.missing),
            "notes": list(self.notes),
            "warnings": list(self.warnings),
            "refusals": list(self.refusals),
            "alternatives": list(self.alternatives),
            "routing_reason": self.routing_reason,
        }
        if self.keyword_options:
            out["keyword_options"] = self.keyword_options
        if self.preview is not None:
            out["preview"] = self.preview
        return out


# ------------------------------------------------------------- draft shape

def normalize_draft(draft: Optional[dict]) -> dict:
    """Put a draft into the canonical shape, tolerantly.

    Accepts a flattened draft (parameters at the top level) as well as the
    canonical one, and drops keys whose value is None so that "not set" and
    "explicitly cleared" do not have to be distinguished by every caller
    downstream -- clearing a field is expressed by writing None, and this
    is where that write is applied.
    """
    draft = dict(draft or {})
    params = dict(draft.get("params") or {})
    for key in list(draft.keys()):
        if key in STRUCTURAL_KEYS:
            continue
        params[key] = draft.pop(key)
    return {
        "task": draft.get("task") or "",
        "subtype": draft.get("subtype") or "",
        "method": draft.get("method") or None,
        "engine": draft.get("engine") or None,
        "params": {k: v for k, v in params.items() if v is not None},
    }


def keyword_options_for(engine: str, method: Optional[str], params: dict) -> Optional[dict]:
    """The numbered/lettered spelling menu, in the format the frontend and
    the shorthand-reply convention already expect.

    Carried over from the previous toolset's `_keyword_options_for_job` in
    format, and in the rule that a functional menu appears only where there
    is a genuine spelling choice -- `hf`, `casscf` and `caspt2` are spelled
    the same everywhere, and a menu for them would be noise.

    One behaviour is tightened. `suggest_basis_options` is fuzzy, so a
    perfectly good name matched itself first and then three neighbours,
    and every approval card for an `sto-3g` job carried a menu offering
    `sto-6g`, `6-31g` and `6-31g*`. A menu exists to resolve a misspelling;
    offering alternatives to a name the engine already accepts is
    second-guessing a choice the user made. So an exact hit suppresses the
    menu entirely -- checked against the same pool the suggestions come
    from, not against a second list that could disagree with it.
    """
    basis = params.get("basis")
    basis_options = keyword_suggest.suggest_basis_options(basis, engine=engine)
    if basis and any(o.lower() == str(basis).strip().lower() for o in basis_options):
        basis_options = []

    functional = params.get("functional")
    functional_options: list[str] = []
    if method == "dft":
        functional_options = keyword_suggest.suggest_functional_options(
            functional, engine=engine)
        if functional and any(o.lower() == str(functional).strip().lower()
                              for o in functional_options):
            functional_options = []

    if not basis_options and not functional_options:
        return None
    if basis_options:
        basis_options = basis_options + [BSE_SEARCH_OPTION]
    return {"basis_options": basis_options, "functional_options": functional_options}


def format_keyword_options(keyword_options: Optional[dict]) -> str:
    """Render `keyword_options_for()`'s result as the menu text shown to
    the user. Same layout as before the rebuild, so a reply like '1b' keeps
    meaning functional option 1 with basis option b."""
    if not keyword_options:
        return ""
    lines = [
        "Closest-matching exact syntax keywords found (present these before finalizing --",
        "a reply like '1b' picks functional/method option 1 and basis option b):",
    ]
    functional_options = keyword_options.get("functional_options") or []
    if functional_options:
        lines.append("Functional/method options:")
        for i, opt in enumerate(functional_options, start=1):
            lines.append(f"  {i}) {opt}")
    basis_options = keyword_options.get("basis_options") or []
    if basis_options:
        lines.append("Basis set options:")
        for letter, opt in zip(_BASIS_LETTERS, basis_options):
            lines.append(f"  {letter}) {opt}")
    return "\n".join(lines)


# ------------------------------------------------------------ cross-state

def _frames(state: Optional[dict]) -> list[dict]:
    return list((state or {}).get("molecule_frames") or [])


def _source_frequency_problem(job_id: str) -> Optional[str]:
    """Why a named source job cannot seed a Wigner ensemble, if it cannot.

    Read through the job store rather than trusted from the draft: the id
    reaches the draft as a string the model transcribed, and a stale or
    mistyped one otherwise fails much later, inside a sampler, as
    something that reads like a chemistry error.
    """
    # Imported lazily. registry2 is a table module that a test, the doc
    # generator and the registry API all import; making it pull in the job
    # manager at import time would put the whole runner stack behind a
    # capability lookup.
    from app.chemistry.jobs.base import read_meta, read_spec

    try:
        spec = read_spec(job_id)
        meta = read_meta(job_id)
    except Exception:
        return (f"No job with id {job_id} was found, so its normal modes cannot be "
                f"sampled.")
    if not spec:
        return f"No job with id {job_id} was found, so its normal modes cannot be sampled."
    method = spec.get("method") or ""
    if method not in ("frequency", "freq", "opt_freq"):
        return (f"Job {job_id} is a '{method}' job. Wigner sampling needs the normal "
                f"modes from a frequency (or optimization-then-frequency) job.")
    status = (meta or {}).get("status")
    if status != "completed":
        return (f"Job {job_id} is {status or 'not finished'}. Its normal modes are only "
                f"available once it has completed.")
    return None


# ------------------------------------------------------------------ asks

def _ask(draft: dict, question: str, asking_for: str, *,
         options: tuple = (), notes: tuple[str, ...] = (),
         keyword_options: Optional[dict] = None,
         missing: tuple[str, ...] = ()) -> DraftVerdict:
    return DraftVerdict(
        status="incomplete", draft=draft, ask_user_exactly=question,
        asking_for=asking_for, options=tuple(options), notes=tuple(notes),
        keyword_options=keyword_options, missing=tuple(missing) or (asking_for,),
    )


def _task_menu() -> tuple[str, ...]:
    """The offerable tasks, labelled. Masters that only exist as the result
    of some other action (a geometry set comes from an upload, a batch from
    several drafts) are not things to ask a user to pick."""
    return tuple(
        f"{tdef.name} -- {tdef.label}"
        for tdef in TASKS.values()
        if tdef.task not in ("batch", "geometry_set")
    )


# --------------------------------------------------------------- the check

def validate_draft(draft: Optional[dict], state: Optional[dict] = None) -> DraftVerdict:
    """Normalize a draft, decide whether it can run, and say what to ask.

    `state` is the agent's own state as a plain dict -- only `molecule` and
    `molecule_frames` are read, so this module stays independent of the
    graph and a test can pass a two-key dict.
    """
    d = normalize_draft(draft)
    notes: list[str] = []
    state = state or {}

    # -- 1. What kind of calculation ------------------------------------
    if not d["task"]:
        return _ask(d, "What kind of calculation would you like to run?", "task",
                    options=_task_menu())

    resolved, suggestions = resolve_task(
        f"{d['task']}/{d['subtype']}" if d["subtype"] else d["task"])
    if resolved is None:
        # Try the bare task word before giving up: a model may write a real
        # task with a subtype that does not exist for it.
        resolved, suggestions = resolve_task(d["task"])
    if resolved is None:
        return _ask(d, f"I don't recognize '{d['task']}' as a calculation this app runs. "
                       f"Which of these did you mean?", "task",
                    options=tuple(suggestions) or _task_menu())
    if (resolved[0], resolved[1]) != (d["task"], d["subtype"]):
        notes.append(f"Read '{d['task']}/{d['subtype']}' as "
                     f"{resolved[0]}/{resolved[1]}." if d["subtype"] else
                     f"Read '{d['task']}' as "
                     f"{resolved[0] if not resolved[1] else resolved[0] + '/' + resolved[1]}.")
    d["task"], d["subtype"] = resolved
    tdef = get_task(d["task"], d["subtype"])

    # -- 2. Something to compute on -------------------------------------
    if d["task"] not in _NO_MOLECULE and not state.get("molecule"):
        return _ask(d, "Which molecule should this run on? You can give a name, a "
                       "SMILES string, or draw it in the sketcher.", "molecule",
                    notes=tuple(notes))

    if d["task"] in _NEEDS_END_GEOMETRY and not d["params"].get("_end_molecule"):
        frames = _frames(state)
        if len(frames) == 2:
            # Unambiguous: two structures are on screen and the task is
            # defined by exactly two. Adopting the second is a reading of
            # what is already there, not a choice made on the user's behalf.
            d["params"]["_end_molecule"] = frames[-1].get("molecule")
            notes.append("Using the second structure in the molecule panel as the end "
                         "geometry.")
        elif len(frames) > 2:
            return _ask(d, "Which of the structures in the molecule panel is the end "
                           "geometry?", "_end_molecule",
                        options=tuple(f.get("description") or f.get("id") for f in frames),
                        notes=tuple(notes))
        else:
            return _ask(d, "This needs a second structure as well. What is the end "
                           "geometry -- a name, a SMILES string, or a structure you "
                           "draw?", "_end_molecule", notes=tuple(notes))

    # A nuclear-ensemble spectrum takes its geometry, and its normal modes,
    # from a completed frequency job. That makes the source job the same
    # kind of prerequisite a molecule is for every other task -- asked for
    # here rather than in the parameter sweep below, and checked against
    # the job store as soon as it arrives, so a stale id is corrected in
    # the same breath instead of surviving four more questions and then
    # failing inside a sampler.
    if d["task"] == "wigner_spectra":
        source_job = d["params"].get("source_frequency_job_id")
        spec = PARAMS_BY_NAME["source_frequency_job_id"]
        if not source_job:
            return _ask(d, spec.ask, spec.name, notes=tuple(notes))
        problem = _source_frequency_problem(str(source_job))
        if problem:
            d["params"].pop("source_frequency_job_id")
            return _ask(d, f"{problem} {spec.ask}", spec.name, notes=tuple(notes))

    # -- 3. Level of theory ----------------------------------------------
    if d["method"]:
        canonical, method_suggestions = resolve_method(d["method"])
        if canonical is None:
            return _ask(d, f"I don't recognize '{d['method']}' as a method this app "
                           f"runs. Which of these did you mean?", "method",
                        options=tuple(method_suggestions)
                                or PARAMS_BY_NAME["method"].options,
                        notes=tuple(notes))
        if canonical != d["method"]:
            notes.append(f"Read method '{d['method']}' as '{canonical}'.")
        d["method"] = canonical

    method_spec = PARAMS_BY_NAME["method"]
    if d["method"] is None and method_spec.applies(d["task"], d["subtype"]):
        return _ask(d, method_spec.ask, "method",
                    options=method_spec.options, notes=tuple(notes))

    basis = d["params"].get("basis")
    if basis:
        fixed, note = param_normalize.normalize_basis(basis)
        if note:
            notes.append(note)
        d["params"]["basis"] = fixed

    # -- 4. Which engine --------------------------------------------------
    #
    # A blind input is the one case where the engine is never inferred. The
    # text carries its own syntax, and preference order would happily route
    # a BAGEL JSON input to ORCA -- which fails in a way that reads like a
    # chemistry error rather than a mix-up. The user states the engine, per
    # the recorded decision that blind execution is ORCA/BAGEL only and
    # never PySCF.
    if d["task"] == "blind" and not d["engine"]:
        tdef_engines = tdef.engines or ()
        return _ask(d, "Which engine should this input be run with -- ORCA or BAGEL? "
                       "A pasted input is run verbatim, so its syntax has to match the "
                       "engine.", "engine", options=tdef_engines, notes=tuple(notes))

    decision = route_engine(d["method"], d["task"], d["subtype"],
                            requested_engine=d["engine"], params=d["params"])
    if decision.engine is None:
        alternatives = tuple(decision.alternatives)
        if alternatives:
            question = (f"{decision.reason} {' '.join(decision.refusals)} "
                        f"Would you like to run it on "
                        f"{' or '.join(e.upper() for e in alternatives)} instead?")
        else:
            question = (f"{decision.reason} {' '.join(decision.refusals)} "
                        f"Would you like to change the method, or the kind of "
                        f"calculation?")
        return DraftVerdict(
            status="unavailable", draft=d, ask_user_exactly=question,
            asking_for="engine", options=alternatives, notes=tuple(notes),
            refusals=tuple(decision.refusals), alternatives=alternatives,
            routing_reason=decision.reason,
        )
    d["engine"] = decision.engine

    # -- 5. Parameters, in declaration order ------------------------------
    keyword_options = keyword_options_for(d["engine"], d["method"], d["params"])

    for spec in missing_required(d["task"], d["subtype"], d["method"], d["engine"], d["params"]):
        options: tuple = spec.options
        if spec.name == "basis":
            options = tuple(suggest_basis(d["params"].get("basis"), engine=d["engine"]))
        elif spec.name == "functional":
            options = tuple(suggest_functional(d["params"].get("functional"), engine=d["engine"]))
        return _ask(d, spec.ask, spec.name, options=options, notes=tuple(notes),
                    keyword_options=keyword_options,
                    missing=tuple(s.name for s in missing_required(
                        d["task"], d["subtype"], d["method"], d["engine"], d["params"])))

    # -- 6. Ready ---------------------------------------------------------
    context = build_context(d["task"], d["subtype"], d["method"], d["engine"], d["params"])
    filled = defaults_for(d["task"], d["subtype"], context)
    applied_defaults = {k: v for k, v in filled.items() if k not in d["params"]}
    d["params"] = {**filled, **d["params"]}

    verdict = supports(d["engine"], d["method"], d["task"], d["subtype"])
    warnings = tuple(dict.fromkeys(
        tuple(decision.warnings) + tuple(verdict.warnings)
        + applicable_warnings(d["task"], d["subtype"], d["method"], d["engine"], d["params"])
    ))

    return DraftVerdict(
        status="ready", draft=d, notes=tuple(notes), warnings=warnings,
        routing_reason=decision.reason,
        keyword_options=keyword_options_for(d["engine"], d["method"], d["params"]),
        preview={
            "task": tdef.name,
            "label": tdef.label,
            "description": tdef.description,
            "engine": d["engine"],
            "method": d["method"],
            "params": dict(d["params"]),
            "applied_defaults": applied_defaults,
            "molecule_name": (state.get("molecule") or {}).get("name"),
            "summary": _summary_line(tdef, d, state),
        },
    )


def _summary_line(tdef, d: dict, state: dict) -> str:
    """One sentence naming what is about to run, for the approval card's
    heading and for the model to read back."""
    molecule = (state.get("molecule") or {}).get("name")
    parts = [tdef.label.lower()]
    if d["method"]:
        level = d["method"].upper()
        functional = d["params"].get("functional")
        if functional:
            level = f"{level}/{functional}"
        basis = d["params"].get("basis")
        if basis:
            level = f"{level}/{basis}"
        parts.append(f"at {level}")
    if molecule:
        parts.append(f"on {molecule}")
    parts.append(f"using {d['engine'].upper()}")
    return " ".join(parts).capitalize() + "."
