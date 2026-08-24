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

from dataclasses import dataclass, field, replace
from typing import Any, Optional

from app.chemistry.jobs import keyword_suggest, param_normalize
from app.chemistry.optional_deps import has_dmrg_backend
from app.chemistry.registry2.lookup import (
    METHOD_SYNONYMS, TASK_SYNONYMS, method_is_really_a_task, resolve_method,
    resolve_task, suggest_basis, suggest_functional,
)
from app.chemistry.registry2.params import (
    MULTIREF_METHODS, PARAMS_BY_NAME, SINGLEREF_METHODS, applicable_warnings,
    build_context, defaults_for, missing_required, params_for,
)
from app.chemistry.registry2.routing import route_engine
from app.chemistry.registry2.tasks import BATCH_CHILD_TASKS, TASKS, get_task, supports

# Draft keys that are not parameters. Anything else the model writes into a
# draft is folded into `params`, because a model that puts `basis` at the
# top level instead of inside `params` has made a formatting mistake, not a
# chemistry one, and rejecting it would spend a conversation turn teaching
# the model a shape it will forget by the next thread.
STRUCTURAL_KEYS = ("task", "subtype", "method", "engine", "resolved_engine", "params")

# Tasks that compute nothing on a structure of their own: a blind text
# input carries its own geometry, a batch and a geometry set hold others,
# and a nuclear-ensemble spectrum samples its geometries from the
# frequency job it is built on.
_NO_MOLECULE = {"blind", "batch", "geometry_set", "wigner_spectra"}

# Tasks defined by a path between two structures rather than by one.
_NEEDS_END_GEOMETRY = {"interp_pes", "neb_ts"}

# The two master tasks that fan a geometry path out into one single-point
# sub-job per image. Both come in a ground-state flavour (the BARE subtype,
# not "gs" -- see tasks.py) and an excited-state one, and which of the two a
# draft lands on is decided by _scan_state_subtype below rather than by the
# model naming a subtype, since `start_job_draft` takes no subtype argument
# at all.
SCAN_TASKS = {"pes_1d", "interp_pes"}


def _scan_state_subtype(task: str, method: Optional[str], params: dict) -> Optional[str]:
    """The subtype a scan draft should carry given its root count, or None
    when this is not a scan and the question does not arise.

    The whole excited-state scan feature turns on this function, because
    there is no other reliable way in. `start_job_draft` accepts only a
    `task` phrase; `TASK_SYNONYMS` matches longest-phrase-first, so "scan the
    excited states along the path" hits `excited states` and lands on a
    `single_point/ee` rather than a scan at all; and asking the model to
    write `subtype` directly works but is not something it reliably thinks
    to do. What the model DOES reliably do, because every excited-state job
    in this app already requires it, is write `n_states`. So the root count
    is the signal, and the subtype is derived from it.

    That is also why `n_states` lists the bare task names in its
    `applies_to` (params.py): the parameter has to be accepted on a fresh
    scan draft, which still has subtype "", or `update_job_draft` refuses it
    as inapplicable and there is nothing here to read.

    The boundary differs by method family and the difference is not
    cosmetic. For casscf/caspt2 `n_states` counts state-averaged roots
    INCLUDING the ground state, so 1 root is a ground-state scan and 2 is
    the first excited-state one. For a single-reference method it counts
    excited states ABOVE the ground state, so 1 is already excited and 0
    means ground state only. Reading them the same way would silently turn
    an ordinary CASSCF scan into a state-averaged one the user never asked
    for.
    """
    if task not in SCAN_TASKS:
        return None
    # int() rather than an isinstance check: nothing in this module coerces
    # a draft's parameter types, so a model that writes "3" instead of 3
    # hands over a string. Rejecting it here would demote the draft to a
    # ground-state scan without saying anything, which is the one outcome
    # this function must never produce silently.
    try:
        n_states = int(params.get("n_states"))
    except (TypeError, ValueError):
        return ""
    threshold = 1 if method in MULTIREF_METHODS else 0
    return "ee" if n_states > threshold else ""


def _capability_task(d: dict) -> tuple[str, str]:
    """Which (task, subtype) `supports()`/`route_engine()` should actually
    check for capability purposes.

    For every ordinary draft this is just (d["task"], d["subtype"]). For a
    `batch` draft it is the CHILD task the user chose
    (params.py's `child_task`, mapped through tasks.BATCH_CHILD_TASKS) --
    batch itself has no level of theory of its own, so its own `requires`
    would be fiction (see tasks.py's own comment on the batch TaskDef).
    Before `child_task` has been answered, this falls back to ("batch", "")
    -- a master task with no `requires` and no allow-list, so `supports()`
    trivially passes and routing picks its usual preference-order default;
    the very next `validate_draft()` call re-runs this against the real
    child task once it is known, since routing is re-derived from the full
    draft on every call rather than cached."""
    if d["task"] == "batch":
        child = d["params"].get("child_task")
        if child in BATCH_CHILD_TASKS:
            return BATCH_CHILD_TASKS[child]
        return "batch", ""
    return d["task"], d["subtype"]

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
        # `engine` is what the *user* asked for and is never written back
        # by validation; `resolved_engine` is what routing chose. Keeping
        # them apart matters because a draft is re-validated after every
        # change: fold the routed engine back into `engine` and the next
        # pass reads it as an explicit request, so the approval card ends
        # up claiming "PYSCF was requested explicitly" about a choice the
        # backend made and the user never saw.
        "engine": draft.get("engine") or None,
        "resolved_engine": draft.get("resolved_engine") or None,
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
    from app.chemistry.jobs.base import read_spec, read_status

    try:
        spec = read_spec(job_id)
        status_doc = read_status(job_id)
    except Exception:
        return (f"No job with id {job_id} was found, so its normal modes cannot be "
                f"sampled.")
    if not spec:
        return f"No job with id {job_id} was found, so its normal modes cannot be sampled."
    task = spec.get("task") or "unknown"
    if task not in ("freq", "opt_freq"):
        return (f"Job {job_id} is a '{task}' job. Wigner sampling needs the normal "
                f"modes from a frequency (or optimization-then-frequency) job.")
    status = (status_doc or {}).get("status")
    if status != "completed":
        return (f"Job {job_id} is {status or 'not finished'}. Its normal modes are only "
                f"available once it has completed.")
    return None


def _initial_orbitals_problem(job_id: str, engine: str) -> Optional[str]:
    """Why a named source job cannot seed this CASSCF/CASPT2 job's initial
    orbital guess, if it cannot -- same "read through the job store rather
    than trust the draft" reasoning as _source_frequency_problem above.

    Orbital files are engine-specific formats this app never converts
    between (PySCF chkfile/molden, ORCA .gbw, BAGEL save_ref archive), so
    the source job's own engine must match the engine THIS job is about to
    run on -- checked against `engine` (the already-routed destination),
    not the source's own requested engine, so a source job that itself ran
    on a routing fallback is still compared against where this job is
    really headed.
    """
    from app.chemistry.jobs.base import read_spec, read_status

    try:
        spec = read_spec(job_id)
        status_doc = read_status(job_id)
    except Exception:
        return f"No job with id {job_id} was found, so its orbitals cannot be reused."
    if not spec:
        return f"No job with id {job_id} was found, so its orbitals cannot be reused."
    if spec.get("method") not in ("casscf", "caspt2"):
        return (f"Job {job_id} is not a CASSCF or CASPT2 job, so it has no active-space "
                f"orbitals to reuse.")
    status = (status_doc or {}).get("status")
    if status != "completed":
        return f"Job {job_id} is {status or 'not finished'}. Its orbitals aren't available yet."
    source_engine = spec.get("engine")
    if source_engine != engine:
        return (f"Job {job_id} ran on {(source_engine or '?').upper()}, but this job runs on "
                f"{engine.upper()} -- orbitals can only be reused on the same engine.")
    return None


def _source_geometry_problem(job_id: str) -> Optional[str]:
    """Why a named source_geometry_job_id cannot supply this draft's
    geometry, if it cannot -- same "read through the job store" reasoning
    as _source_frequency_problem/_initial_orbitals_problem above, but
    unlike those two this one is NOT dropped-with-a-note on failure: a
    user who named a specific job's geometry and silently got a different,
    unnamed one instead (whatever happened to be in the molecule panel)
    would be a wrong answer, not a convenience. See validate_draft's own
    call site."""
    from app.chemistry.jobs.geometry_resolve import resolve_single_completed_geometry

    _molecule, error = resolve_single_completed_geometry(job_id)
    return error


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


def _read_phrase(text: str) -> tuple[Optional[tuple[str, str]], Optional[str]]:
    """Pull a (task, method) pair out of a free-text phrase.

    Longest synonym first, so "single point" is preferred over a shorter
    fragment that also happens to appear. Matching is on whole words -- a
    padded substring search -- because "sp" inside "dispersion" is not a
    request for a single point.

    `tddft` deliberately appears in both pools and resolves to both halves
    at once: it is a request for excited states (the task) computed at DFT
    (the method), which is exactly the conflation the v2 taxonomy exists to
    undo.
    """
    lowered = f" {(text or '').lower().replace('_', ' ')} "
    task = None
    for phrase in sorted(TASK_SYNONYMS, key=len, reverse=True):
        if f" {phrase} " in lowered:
            task = TASK_SYNONYMS[phrase]
            break
    method = None
    for name in sorted(METHOD_SYNONYMS, key=len, reverse=True):
        if f" {name} " in lowered:
            method = METHOD_SYNONYMS[name]
            break
    return task, method


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

def validate_draft(draft: Optional[dict], state: Optional[dict] = None,
                   check_external: bool = True) -> DraftVerdict:
    """Normalize a draft, decide whether it can run, and say what to ask.

    `state` is the agent's own state as a plain dict -- only `molecule`,
    `molecule_frames` and `pes_scan_end_molecule` are read, so this module
    stays independent of the graph and a test can pass a two-key dict.

    `check_external=False` drops the one check that reads anything outside
    the draft: whether a Wigner source job still exists and is finished.
    That check is right at elicitation time and wrong at submission time,
    because everything before the approval `interrupt()` re-runs when the
    user clicks Approve. If the answer changed in between -- the job was
    deleted, say -- a re-validating submitter would return a question
    instead of resuming, and the approval would disappear with no error at
    all. With it off, the verdict is a pure function of the draft and the
    conversation's own geometry, so both passes agree by construction.
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
        # A model hands over whatever phrase the user used, and a user says
        # "a CASSCF single point energy", "a B3LYP geometry optimization",
        # "excited states with TDDFT" -- one string carrying both a task and
        # a level of theory. Read both out of it rather than rejecting the
        # phrase for not being exactly a task name.
        phrase_task, phrase_method = _read_phrase(d["task"])
        if phrase_task is not None:
            name = f"{phrase_task[0]}/{phrase_task[1]}" if phrase_task[1] else phrase_task[0]
            if phrase_method and not d["method"]:
                d["method"] = phrase_method
                notes.append(f"Read '{d['task']}' as a {name} at {phrase_method}.")
            else:
                notes.append(f"Read '{d['task']}' as {name}.")
            resolved = phrase_task
            d["task"], d["subtype"] = resolved

    if resolved is None:
        # Nothing task-shaped in it at all. Before telling someone that
        # CASSCF is not a calculation this app runs -- which reads as
        # nonsense, because it plainly is one -- check whether what they
        # named is a method, keep it, and ask the question they actually
        # left open. The task is still asked rather than inferred: a CASSCF
        # on water could be an energy, an optimization or a spectrum, and
        # picking one would be the assumption this module exists to avoid.
        as_method, _ = resolve_method(d["task"])
        if as_method and not d["method"]:
            notes.append(f"Read '{d['task']}' as the level of theory, not the kind of "
                         f"calculation.")
            d["method"], d["task"] = as_method, ""
            return _ask(d, "What kind of calculation would you like to run?", "task",
                        options=_task_menu(), notes=tuple(notes))
        return _ask(d, f"I don't recognize '{d['task']}' as a calculation this app runs. "
                       f"Which of these did you mean?", "task",
                    options=tuple(suggestions) or _task_menu(), notes=tuple(notes))

    if (resolved[0], resolved[1]) != (d["task"], d["subtype"]):
        notes.append(f"Read '{d['task']}/{d['subtype']}' as "
                     f"{resolved[0]}/{resolved[1]}." if d["subtype"] else
                     f"Read '{d['task']}' as "
                     f"{resolved[0] if not resolved[1] else resolved[0] + '/' + resolved[1]}.")
    d["task"], d["subtype"] = resolved
    tdef = get_task(d["task"], d["subtype"])

    # -- 2. Something to compute on -------------------------------------
    #
    # source_geometry_job_id (P9.3) lets a draft take its geometry from a
    # prior job's own result instead of state["molecule"] -- "same
    # geometry as before", "repeat that with a bigger basis". Checked
    # BEFORE the ordinary molecule gate below, and unlike
    # initial_orbitals_job_id this is never silently dropped on failure:
    # asked about instead, so a stale or mistyped id does not quietly
    # substitute a different geometry the user never named. check_external-
    # gated for the same pre-interrupt-determinism reason as
    # source_frequency_job_id/initial_orbitals_job_id above -- the actual
    # geometry substitution happens downstream in app/agent/tools.py,
    # which re-resolves the (by-then re-validated) id itself rather than
    # trusting a value computed here.
    source_geometry_job = d["params"].get("source_geometry_job_id")
    if source_geometry_job and check_external:
        problem = _source_geometry_problem(str(source_geometry_job))
        if problem:
            return _ask(d, f"{problem} Give a valid job id to reuse its geometry, or say "
                           f"to use whatever is in the molecule panel instead.",
                        "source_geometry_job_id", notes=tuple(notes))
    if d["task"] not in _NO_MOLECULE and not state.get("molecule") and not source_geometry_job:
        return _ask(d, "Which molecule should this run on? You can give a name, a "
                       "SMILES string, or draw it in the sketcher.", "molecule",
                    notes=tuple(notes))

    if d["task"] in _NEEDS_END_GEOMETRY and not d["params"].get("_end_molecule"):
        frames = _frames(state)
        if state.get("pes_scan_end_molecule"):
            # An end geometry resolved explicitly into its own state slot
            # (set_geometry's "end" role) is the least ambiguous source
            # there is -- the user named it as the end structure, rather
            # than it being inferred from what happens to be on screen.
            d["params"]["_end_molecule"] = state["pes_scan_end_molecule"]
        elif len(frames) == 2:
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

    # A batch's geometries come from EITHER a source job (source_job_id,
    # a declared ParamSpec, asked for in the ordinary parameter sweep
    # below) OR 3+ individually-tagged molecule-panel frames -- the same
    # "tagged geometries" input shape _end_molecule already uses above,
    # resolved here rather than as a declared ParamSpec for the same
    # reason _end_molecule isn't one: never something a user types into a
    # field. Guarded on neither already being present, same "resolve once"
    # pattern as _end_molecule, so a later validate_draft call (the
    # resume pass after approval) does not silently re-derive against
    # panel contents that may have changed since. `molecule_frames` is an
    # append-only log of every molecule the user set THIS THREAD, not a
    # curated batch selection -- three incidental frames from three
    # unrelated earlier questions are not a batch anyone asked for. Since
    # this auto-adopts rather than asking the user to pick, the note has
    # to do real work: it names every frame's own description, not just a
    # count, so a wrong adoption is visible on the approval card instead
    # of discovered three dispatched jobs later.
    if (d["task"] == "batch" and not d["params"].get("source_job_id")
            and not d["params"].get("_frame_geometries")):
        frames = _frames(state)
        if len(frames) >= 3:
            d["params"]["_frame_geometries"] = [f.get("molecule") for f in frames]
            names = ", ".join(f.get("description") or f.get("id") or "?" for f in frames)
            notes.append(f"Using the {len(frames)} structures currently tagged in the "
                         f"molecule panel as this batch's geometries: {names}.")

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
        problem = _source_frequency_problem(str(source_job)) if check_external else None
        if problem:
            d["params"].pop("source_frequency_job_id")
            return _ask(d, f"{problem} {spec.ask}", spec.name, notes=tuple(notes))

    # -- 3. Level of theory ----------------------------------------------
    if d["method"]:
        canonical, method_suggestions = resolve_method(d["method"])
        if canonical is None:
            # A word on the wrong axis, before it is treated as a wrong word.
            # A model told to run "autocas" writes method="autocas", and
            # autocas is a SUBTYPE of cas_reco, not a level of theory -- so
            # the old branch offered "casscf" as the nearest method and threw
            # the actual request away. Move it to the axis it belongs on when
            # it names a subtype of the task already in hand.
            as_task = method_is_really_a_task(d["method"])
            if as_task is not None and as_task[0] == d["task"]:
                notes.append(f"Read '{d['method']}' as the {as_task[0]}/{as_task[1]} "
                             f"kind of calculation, not a level of theory.")
                d["subtype"], d["method"] = as_task[1], None
                rerouted = validate_draft(d, state, check_external=check_external)
                return replace(rerouted, notes=tuple(notes) + rerouted.notes)
            return _ask(d, f"I don't recognize '{d['method']}' as a method this app "
                           f"runs. Which of these did you mean?", "method",
                        options=tuple(method_suggestions)
                                or PARAMS_BY_NAME["method"].options,
                        notes=tuple(notes))
        if canonical != d["method"]:
            notes.append(f"Read method '{d['method']}' as '{canonical}'.")
        d["method"] = canonical

    method_spec = PARAMS_BY_NAME["method"]
    # A task whose own allow-list names exactly one level of theory has
    # nothing to elicit -- asking "which level of theory: casscf?" spends a
    # round trip on a question with one possible answer, and every cas_reco
    # draft paid it. Adopted with a note rather than silently, since the
    # user never said the word themselves.
    if d["method"] is None and tdef.methods is not None and len(tdef.methods) == 1:
        d["method"] = tdef.methods[0]
        notes.append(f"{tdef.label} only runs at {d['method']} in this app, so that is "
                     f"the level of theory used.")
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
    # A pasted input identifies its own engine far more reliably than a
    # user recalling which program it was for. The sniffer is mechanical
    # (app/chemistry/jobs/input_sniff.py), so this is a reading of the
    # text, not a guess about it.
    if d["task"] == "blind":
        pasted = d["params"].get("raw_input_text")
        if pasted:
            from app.chemistry.jobs.input_sniff import sniff

            result = sniff(pasted)
            if result.engine and not result.executable:
                # PySCF, always. A pasted script is user-supplied Python and
                # is never executed here at any confidence level.
                return DraftVerdict(
                    status="unavailable", draft=d,
                    ask_user_exactly=(
                        f"{result.describe()} This app never runs a pasted Python "
                        f"script. I can build the equivalent job properly instead, "
                        f"which also gets you the input preview and the parsed "
                        f"results -- shall I?"),
                    asking_for="task", notes=tuple(notes),
                    refusals=("A pasted PySCF script is classified but never "
                              "executed.",),
                    routing_reason=result.describe(),
                )
            if result.engine:
                if d["engine"] and d["engine"] != result.engine:
                    return _ask(d, f"This looks like {result.engine.upper()} input, but "
                                   f"it was going to be run with "
                                   f"{d['engine'].upper()}. Which is right?",
                                "engine", options=("orca", "bagel"), notes=tuple(notes))
                d["engine"] = d["engine"] or result.engine
                notes.append(result.describe())
                if result.confident:
                    notes.append(
                        f"Offer the choice: run it verbatim as a blind job, or build "
                        f"the equivalent {result.task_name} job, which gets an input "
                        f"preview and parsed results.")

    if d["task"] == "blind" and not d["engine"]:
        tdef_engines = tdef.engines or ()
        return _ask(d, "Which engine should this input be run with -- ORCA or BAGEL? "
                       "A pasted input is run verbatim, so its syntax has to match the "
                       "engine.", "engine", options=tdef_engines, notes=tuple(notes))

    cap_task, cap_subtype = _capability_task(d)
    decision = route_engine(d["method"], cap_task, cap_subtype,
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
    # Routing's answer, kept beside the user's request rather than on top
    # of it -- see normalize_draft.
    d["resolved_engine"] = engine = decision.engine

    # Optional, tag-driven, never asked for (initial_orbitals_job_id has no
    # required_when) -- so an invalid tag degrades to "start from a fresh
    # guess" with a note instead of blocking the draft the way a required
    # field's problem would. check_external-gated for the same pre-interrupt-
    # determinism reason as source_frequency_job_id above (P2B.1's known
    # exception); the actual file copy happens at dispatch regardless.
    orbitals_job = d["params"].get("initial_orbitals_job_id")
    if orbitals_job and check_external:
        problem = _initial_orbitals_problem(str(orbitals_job), engine)
        if problem:
            d["params"].pop("initial_orbitals_job_id")
            notes.append(f"{problem} Starting from a fresh initial guess instead.")

    # -- 5. Parameters, in declaration order ------------------------------
    keyword_options = keyword_options_for(engine, d["method"], d["params"])

    for spec in missing_required(d["task"], d["subtype"], d["method"], engine, d["params"]):
        options: tuple = spec.options
        if spec.name == "basis":
            options = tuple(suggest_basis(d["params"].get("basis"), engine=engine))
        elif spec.name == "functional":
            options = tuple(suggest_functional(d["params"].get("functional"), engine=engine))
        return _ask(d, spec.ask, spec.name, options=options, notes=tuple(notes),
                    keyword_options=keyword_options,
                    missing=tuple(s.name for s in missing_required(
                        d["task"], d["subtype"], d["method"], engine, d["params"])))

    # -- 5a0. The DMRG backend is optional, and may simply not be here ----
    #
    # block2 is not in requirements.txt: a 379 MB MKL-linked wheel is a poor
    # tax on every install for a screening backend most will never run, and
    # the exact-FCI pilot covers every pool up to 12 orbitals. What is not
    # acceptable is advertising the option and then dying on it, so a draft
    # naming an absent backend is refused here rather than reaching a worker
    # that raises ModuleNotFoundError.
    if (d["task"] == "cas_reco" and d["params"].get("entropy_method") == "dmrg"
            and not has_dmrg_backend()):
        d["params"].pop("entropy_method")
        return _ask(d, "The DMRG screening backend (block2) is not installed in this "
                       "deployment, so the entropy pilot can only use exact FCI, which "
                       "caps the screening pool at 12 orbitals. Shall it use exact FCI, "
                       "or would you rather stop and have block2 installed first?",
                    "entropy_method", options=("exact_fci",), notes=tuple(notes))

    # -- 5a. A state-averaged entropy pilot is exact-FCI only -------------
    #
    # Refused here rather than in the runner, and the distinction matters.
    # block2 0.5.3 solves happily for several roots but segfaults inside
    # get_orbital_entropies on the resulting multi-root MPS (reproduced on
    # a water/STO-3G CAS(4,4) probe; see _pilot_entropies_dmrg's docstring).
    # A segfault takes the worker process down with it, so no result is ever
    # written and the job never reaches a terminal status -- the one
    # job-lifecycle failure this project treats as a real defect rather than
    # a slow calculation. A draft that cannot run must not reach READY.
    if (d["task"] == "cas_reco" and d["subtype"] == "autocas"
            and (d["params"].get("entropy_pilot_states") or 1) > 1
            and d["params"].get("entropy_method") == "dmrg"):
        return _ask(d, "A state-averaged entropy pilot is not available with the DMRG "
                       "screening backend in this deployment -- only with the exact-FCI "
                       "one. Should this use the exact-FCI pilot instead (which caps the "
                       "screening pool at 12 orbitals), or screen the ground state only?",
                    "entropy_method", options=("exact_fci", "dmrg"), notes=tuple(notes))

    # -- 5a2. A scan's root count decides whether it is a ground-state or an
    # excited-state scan --------------------------------------------------
    #
    # Placed here rather than earlier so it reads the CANONICAL method (step
    # 3 above resolves "tddft" to "dft", and the multireference boundary in
    # _scan_state_subtype depends on that). It re-enters validate_draft
    # rather than falling through, because the subtype it sets changes what
    # `requires` routing checks, which parameters apply, and which of them
    # are required -- all of which were already computed above against the
    # old subtype. Same shape as 5b just below.
    scan_subtype = _scan_state_subtype(d["task"], d["method"], d["params"])
    if scan_subtype is not None and scan_subtype != d["subtype"]:
        was_excited = d["subtype"] == "ee"
        d["subtype"] = scan_subtype
        if scan_subtype == "ee":
            n = d["params"]["n_states"]
            notes.append(
                f"Computing excited states at every point of this scan, not just the "
                f"ground state, since {n} state{'' if n == 1 else 's'} "
                f"{'was' if n == 1 else 'were'} asked for."
            )
        elif was_excited:
            # The demotion. Reached either by clearing n_states off an
            # excited-state scan, or by a count that means ground state only
            # for this method family (n_states=0 single-reference, n_states=1
            # multireference). Said out loud because it changes what runs.
            notes.append(
                "Reading this as a ground-state scan: the number of states asked for "
                "does not add an excited state on top of the ground state for this "
                "method."
            )
        rerouted = validate_draft(d, state, check_external=check_external)
        return replace(rerouted, notes=tuple(notes) + rerouted.notes)

    # -- 5b. Zero excited states is a ground-state request, not a degenerate
    # excited-state one --------------------------------------------------
    #
    # n_states' own help text says single-reference methods count EXCITED
    # states above the ground state (params.py), so n_states=0 there means
    # "no excited states" -- i.e. just the ground-state energy. That is a
    # real, well-formed request (a plain single_point/gs), but nothing
    # downstream of here treats it that way: eom_ccsd's PySCF runner asks
    # its Davidson solver for zero roots and crashes with an opaque
    # IndexError, and ORCA's MDCI module refuses outright ("Number of roots
    # is not set, it should be NRoots>0!"). Both were confirmed by running
    # them, not inferred. Multireference methods are excluded on purpose:
    # for casscf/caspt2, n_states INCLUDES the ground state, so n_states=1
    # already means "just the ground state" through the ordinary
    # state-average machinery, and n_states=0 there is not this case at
    # all (it fails missing_required's active_electrons/active_orbitals
    # requirement the same as any other CASSCF/CASPT2 draft would).
    # `task not in SCAN_TASKS` because a scan's ground-state key is the BARE
    # subtype, not "gs" (see tasks.py's comment on the scan TaskDefs). Left
    # unguarded, a single-reference scan with n_states=0 would be rewritten
    # to a `pes_1d/gs` that does not exist in TASKS at all. The scan case is
    # handled by _scan_state_subtype below, which demotes to "" instead.
    if (d["subtype"] == "ee" and d["task"] not in SCAN_TASKS
            and d["method"] in SINGLEREF_METHODS
            and d["params"].get("n_states") == 0):
        for stale in ("n_states", "use_tda", "want_oscillator_strengths", "target_state", "weights"):
            d["params"].pop(stale, None)
        old_method = d["method"]
        d["subtype"] = "gs"
        # eom_ccsd is the excited-state PACKAGE built on a CCSD reference --
        # asking for zero excited states out of it means the CCSD ground
        # state itself, which is method='ccsd' on a plain single_point/gs
        # (hf/dft need no such translation: single_point/gs already speaks
        # those method names natively).
        if d["method"] == "eom_ccsd":
            d["method"] = "ccsd"
        notes.append(
            f"Requesting 0 excited states means only the ground state -- switched this to a "
            f"plain single_point/gs {d['method'].upper()} energy instead of an excited-state "
            f"({old_method.upper().replace('_', '-')}) calculation, since EOM-CCSD/TDDFT need at "
            f"least 1 excited state to solve for."
        )
        rerouted = validate_draft(d, state, check_external=check_external)
        return replace(rerouted, notes=tuple(notes) + rerouted.notes)

    # -- 6. Ready ---------------------------------------------------------
    context = build_context(d["task"], d["subtype"], d["method"], engine, d["params"])
    filled = defaults_for(d["task"], d["subtype"], context)
    applied_defaults = {k: v for k, v in filled.items() if k not in d["params"]}
    d["params"] = {**filled, **d["params"]}

    # A nuclear-ensemble spectrum always computes oscillator strengths --
    # see registry2/tasks.py's `wigner_spectra` TaskDef and params.py's
    # `want_oscillator_strengths` ParamSpec, whose `default=False` is the
    # single-geometry answer and stays False here for exactly that reason
    # (one ParamSpec, one default, shared with single_point/ee). Forcing
    # it here rather than only in app/agent/tools.py's
    # _build_ensemble_spec_or_error matters because this function is what
    # builds `preview["params"]` and the DRAFT READY message the model
    # reads -- forcing it only downstream in tools.py left this function
    # reporting the untouched `False` default at the point the model
    # decides whether to ask the user about it, so the model (correctly
    # reading a stale "off by default") asked a question that was already
    # settled and would have been overridden regardless of the answer.
    if d["task"] == "wigner_spectra" and not d["params"].get("want_oscillator_strengths"):
        d["params"]["want_oscillator_strengths"] = True
        notes.append(
            "Oscillator strengths are always computed for a nuclear-ensemble spectrum: "
            "the spectrum is a Gaussian convolution weighted by the transition "
            "intensities, so without them there is nothing to broaden."
        )

    verdict = supports(engine, d["method"], *_capability_task(d))
    warnings = tuple(dict.fromkeys(
        tuple(decision.warnings) + tuple(verdict.warnings)
        + applicable_warnings(d["task"], d["subtype"], d["method"], engine, d["params"])
    ))

    return DraftVerdict(
        status="ready", draft=d, notes=tuple(notes), warnings=warnings,
        routing_reason=decision.reason,
        keyword_options=keyword_options_for(engine, d["method"], d["params"]),
        preview={
            "task": tdef.name,
            "label": tdef.label,
            "description": tdef.description,
            "engine": engine,
            "method": d["method"],
            "params": dict(d["params"]),
            "applied_defaults": applied_defaults,
            "molecule_name": (state.get("molecule") or {}).get("name"),
            "summary": _summary_line(tdef, d, engine, state),
        },
    )


def _summary_line(tdef, d: dict, engine: str, state: dict) -> str:
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
    parts.append(f"using {engine.upper()}")
    # Only the first character, not str.capitalize(), which lowercases
    # everything after it and turned "HF/sto-3g ... using PYSCF" into
    # "hf/sto-3g ... using pyscf".
    sentence = " ".join(parts)
    return sentence[:1].upper() + sentence[1:] + "."
