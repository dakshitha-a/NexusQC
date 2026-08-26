"""Mechanical answers to "can this engine do that?" and "did you mean...?".

This is the module behind the agent's `lookup_capabilities` tool (Phase 2)
and the v2 half of `GET /api/job-registry`. Its whole purpose is that
**the model never answers a capability question from its weights.** A
model asked "does BAGEL support constrained optimization?" will say yes --
it is in BAGEL's documentation, it is in the literature, and it is wrong on
this host, where `fix_atom` is accepted and silently ignored. The only way
to keep that out of a conversation is to make the answer a lookup rather
than a recollection, and to make the lookup cheap enough that there is no
reason to skip it.

Nothing new is computed here. Capability verdicts come from
`tasks.supports()`, routing from `routing.route_engine()`, and the
fuzzy-matching pools from the existing `keyword_suggest` / `bse_basis` /
`param_normalize` layers, which are already written against the engines'
own scraped manuals and PySCF's own parser. This is a façade over them, so
there is exactly one implementation of "is this a real basis set" in the
codebase and it is the one that was already being trusted.
"""
from __future__ import annotations

import difflib
from typing import Any, Optional

from app.chemistry.jobs import keyword_suggest, param_normalize
from app.chemistry.jobs.bse_basis import search_bse_basis_names
from app.chemistry.registry2.capabilities import (
    CANONICAL_METHODS, CAPABILITIES, CAPABILITY_FIELDS, ENGINES, canonical_engine, get_caps,
)
from app.chemistry.registry2.params import missing_required, params_for
from app.chemistry.registry2.routing import route_engine
from app.chemistry.registry2.tasks import TASKS, engines_supporting, get_task, supports

# Words users and models reach for that are not the canonical name. Kept
# small and explicit rather than fuzzy-matched, because these are synonyms
# rather than typos -- "tddft" is not a misspelling of "dft", it is a
# request for excited states at DFT, and resolving it needs the task too.
METHOD_SYNONYMS: dict[str, str] = {
    "hartree-fock": "hf", "hartree fock": "hf", "scf": "hf", "rhf": "hf",
    "uhf": "hf", "rohf": "hf",
    "b3lyp": "dft", "pbe0": "dft", "pbe": "dft", "wb97x-d": "dft", "m06-2x": "dft",
    "ks": "dft", "kohn-sham": "dft", "tddft": "dft", "td-dft": "dft", "tda": "dft",
    "cis": "hf", "td-hf": "hf", "rpa": "hf",
    "mp2": "mp2", "møller-plesset": "mp2", "moller-plesset": "mp2",
    "ccsd": "ccsd", "coupled cluster": "ccsd",
    "eom-ccsd": "eom_ccsd", "eom": "eom_ccsd", "eomccsd": "eom_ccsd",
    "cas": "casscf", "casscf": "casscf", "sa-casscf": "casscf", "mcscf": "casscf",
    "caspt2": "caspt2", "pt2": "caspt2", "ms-caspt2": "caspt2", "xms-caspt2": "caspt2",
}

# Task phrasings, same reasoning. The value is a (task, subtype) pair.
TASK_SYNONYMS: dict[str, tuple[str, str]] = {
    "single point": ("single_point", "gs"), "energy": ("single_point", "gs"),
    "sp": ("single_point", "gs"),
    "excited states": ("single_point", "ee"), "uv-vis": ("single_point", "ee"),
    "absorption": ("single_point", "ee"), "spectrum": ("single_point", "ee"),
    "tddft": ("single_point", "ee"), "excitation energies": ("single_point", "ee"),
    "gradient": ("single_point", "grad"), "forces": ("single_point", "grad"),
    "nac": ("single_point", "nac"), "nacme": ("single_point", "nac"),
    "non-adiabatic coupling": ("single_point", "nac"),
    "derivative coupling": ("single_point", "nac"),
    "optimization": ("opt", "min"), "optimize": ("opt", "min"),
    "geometry optimization": ("opt", "min"), "minimize": ("opt", "min"),
    "constrained optimization": ("opt", "constrained"),
    "scan": ("pes_1d", ""), "pes": ("pes_1d", ""), "potential energy surface": ("pes_1d", ""),
    # Excited-state scans. These have to be here AND longer than "excited
    # states" above, because _read_phrase takes the longest matching synonym:
    # without them "scan the excited states along the path" matches `excited
    # states` and resolves to a single_point/ee, silently dropping the scan.
    # This is only the secondary route in -- the primary one is writing
    # n_states onto a scan draft, which elicitation._scan_state_subtype reads
    # (and which is what catches the phrasings nobody thought to list here).
    "excited state scan": ("pes_1d", "ee"), "excited state pes": ("pes_1d", "ee"),
    "excited state potential energy surface": ("pes_1d", "ee"),
    "excited state path": ("interp_pes", "ee"),
    "excited state path scan": ("interp_pes", "ee"),
    "excited state interpolation": ("interp_pes", "ee"),
    "conical intersection": ("opt", "ci"), "meci": ("opt", "ci"), "mecp": ("opt", "ci"),
    "frequency": ("freq", ""), "frequencies": ("freq", ""), "vibrations": ("freq", ""),
    "ir": ("freq", ""), "hessian": ("freq", ""), "thermochemistry": ("freq", ""),
    "opt freq": ("opt_freq", ""), "optimization and frequencies": ("opt_freq", ""),
    "neb": ("neb_ts", ""), "transition state": ("neb_ts", ""), "nudged elastic band": ("neb_ts", ""),
    "wigner": ("wigner_spectra", ""), "nuclear ensemble": ("wigner_spectra", ""),
    "ensemble spectrum": ("wigner_spectra", ""),
    "active space": ("cas_reco", "autocas"), "autocas": ("cas_reco", "autocas"),
    "avas": ("cas_reco", "avas"),
    # Orbital rendering is a single-point calculation plus the
    # the orbital table of a job that has already run, not a task or a
    # parameter of its own -- see tasks.py.
    "orbitals": ("single_point", "gs"), "molecular orbitals": ("single_point", "gs"),
    # Singular as well as plural. Justified as ordinary language, not as
    # compatibility: someone asks to see "a molecular orbital" as readily
    # as "molecular orbitals", and would whether or not a previous version
    # of this app had ever existed.
    "orbital": ("single_point", "gs"), "molecular orbital": ("single_point", "gs"),
    "orbital visualization": ("single_point", "gs"),
    "molecular orbital visualization": ("single_point", "gs"),
    "mo": ("single_point", "gs"),
    "homo": ("single_point", "gs"), "lumo": ("single_point", "gs"),
    # Ways of describing a verbatim engine input. `custom` -- the v1 job
    # type for this -- is deliberately NOT here: the overhaul is a
    # ground-up build and owes nothing to the previous version's
    # vocabulary. What is here are phrases that describe the v2 concept on
    # their own terms.
    "raw input": ("blind", ""), "blind job": ("blind", ""),
    "blind engine input": ("blind", ""), "verbatim input": ("blind", ""),
    # Plain descriptions of three v2 tasks whose canonical names are
    # short. Same test: would someone say this without ever having seen
    # the old system? Yes -- so they earn their place. The v1 identifiers
    # themselves (`pes_scan`, `recommend_active_space`, `wigner_ensemble`)
    # are not registered, and should not be.
    "potential energy scan": ("pes_1d", ""),
    "active space recommendation": ("cas_reco", "autocas"),
    "nuclear ensemble spectrum": ("wigner_spectra", ""),
    "ensemble": ("wigner_spectra", ""),
    "cube": ("single_point", "gs"),
}


def _fuzzy(query: str, pool, n: int = 3, cutoff: float = 0.6) -> list[str]:
    return difflib.get_close_matches(query.lower().strip(), list(pool), n=n, cutoff=cutoff)


def resolve_method(query: Optional[str]) -> tuple[Optional[str], list[str]]:
    """(canonical method, suggestions).

    Exact and synonym matches resolve outright; anything else comes back as
    suggestions rather than a guess, because coercing an unrecognized
    method into a plausible one silently computes different chemistry than
    was asked for -- the same rule `param_normalize` already follows.
    """
    if not query:
        return None, []
    q = query.lower().strip()
    if q in CANONICAL_METHODS:
        return q, []
    if q in METHOD_SYNONYMS:
        return METHOD_SYNONYMS[q], []
    normalized, _note = param_normalize.normalize_method(q)
    if normalized in CANONICAL_METHODS:
        return normalized, []
    hits = _fuzzy(q, list(CANONICAL_METHODS) + list(METHOD_SYNONYMS))
    return None, [METHOD_SYNONYMS.get(h, h) for h in hits]


def resolve_task(query: Optional[str]) -> tuple[Optional[tuple[str, str]], list[str]]:
    """((task, subtype), suggestions) for a free-text task phrase."""
    if not query:
        return None, []
    q = query.lower().strip().replace("_", " ")
    if q in TASK_SYNONYMS:
        return TASK_SYNONYMS[q], []
    for (task, subtype) in TASKS:
        name = f"{task}/{subtype}" if subtype else task
        if q in (name, task.replace("_", " "), name.replace("_", " ")):
            return (task, subtype), []
    hits = _fuzzy(q, TASK_SYNONYMS, n=3, cutoff=0.55)
    return None, hits


def method_is_really_a_task(query: Optional[str]) -> Optional[tuple[str, str]]:
    """(task, subtype) when a phrase offered as a level of theory actually
    names a task or one of its subtypes -- otherwise None.

    `avas` and `autocas` are the cases that motivated this. They are
    subtypes of `cas_reco`, so `resolve_method` cannot resolve them and,
    before this existed, returned "Closest matches: none" -- a flat dead
    end for a capability this app has. A model that reaches for the wrong
    axis is making a category error, not naming something unavailable, and
    the answer it needs is which axis the word belongs on.

    Deliberately narrow: only consulted where a method lookup has ALREADY
    failed, so a real method is never reinterpreted as a task.
    """
    if not query:
        return None
    if resolve_method(query)[0] is not None:
        return None
    resolved, _ = resolve_task(query)
    return resolved


def suggest_basis(query: Optional[str], engine: str = "pyscf", n: int = 4) -> list[str]:
    """Basis-set suggestions from the engine's own name pool, falling back
    to a Basis Set Exchange search."""
    hits = keyword_suggest.suggest_basis_options(query, engine=engine, n=n)
    if hits:
        return hits
    return search_bse_basis_names(query or "", n=n)


def suggest_functional(query: Optional[str], engine: str = "pyscf", n: int = 4) -> list[str]:
    return keyword_suggest.suggest_functional_options(query, engine=engine, n=n)


def _parameter_summary(task: str, subtype: str = "") -> list[dict]:
    """The parameters a draft for this task accepts, by name.

    Added because the absence of this list cost a user two turns. Asked to
    seed a CASSCF from a previous job's orbitals, the agent looked at the
    draft it had, did not find a field for it, and told the user it would
    "check whether this deployment supports that" -- for a parameter,
    `initial_orbitals_job_id`, that has existed all along. It then guessed
    the name wrong on the next attempt and needed a rejection to learn it.

    The names were reachable only by getting one wrong: `update_job_draft`
    lists them when it refuses an unknown key. That makes the error path
    the only documentation, so the agent has to be wrong once, in front of
    the user, before it can be right. This puts the same list on the
    question-answering path, where "can it do X?" is asked.

    `help` in preference to `label`, because the label alone is not enough
    to answer the question that was asked. "Initial orbitals from" does not
    tell anyone that the source job has to be a completed CASSCF/CASPT2 run
    on the SAME engine; the help text says exactly that, and that condition
    is the part an agent would otherwise have to discover by submitting a
    job that fails.

    Name, type and one line each, on purpose. This travels in the
    conversation whenever a capability is looked up, so it is bounded and
    costs nothing on turns that do not ask -- unlike the fixed prompt
    surface, which pays on every ReAct iteration and is the reason
    `ParamSpec.ask` is not carried here. See docs/MODEL_CONTEXT_BUDGET.md.
    """
    summary = []
    for spec in params_for(task, subtype):
        entry = {"name": spec.name, "type": spec.type}
        gloss = " ".join((spec.help or spec.label or "").split())
        if gloss:
            entry["what"] = gloss if len(gloss) <= 160 else gloss[:157] + "..."
        if spec.default is not None:
            entry["default"] = spec.default
        summary.append(entry)
    return summary


def capability_answer(task: str, subtype: str = "", method: Optional[str] = None,
                      engine: Optional[str] = None) -> dict:
    """The structured answer to a capability question.

    The engine is canonicalised on the way in, so the answer echoes the name
    this app uses rather than the caller's spelling. Echoing the caller's was
    half of the engine-case defect: the verdict came back correct while the
    engine field still said "ORCA", which reads as confirmation that "ORCA"
    is the spelling everything else will accept.

    Deliberately returns the same shape whether the answer is yes or no,
    with the reasons attached either way, so the agent relays a fact rather
    than composing an explanation of its own.
    """
    engine = canonical_engine(engine)
    tdef = get_task(task, subtype)
    if tdef is None:
        return {"known": False, "task": task, "subtype": subtype,
                "message": f"No such task as {task}/{subtype}." if subtype
                           else f"No such task as {task}."}

    if engine:
        verdict = supports(engine, method, task, subtype)
        return {
            "known": True, "task": task, "subtype": subtype, "method": method,
            "engine": engine, "label": tdef.label, "supported": verdict.supported,
            "reasons": list(verdict.reasons), "warnings": list(verdict.warnings),
            "plottable_fields": list(tdef.plottable_fields),
            "parameters": _parameter_summary(task, subtype),
        }

    # "Can this deployment recommend an active space?" asked without a
    # method used to come back `supported: false` with the reason "No engine
    # in this deployment can run a cas_reco/autocas job" -- because
    # `supports()` answers None-method by refusing (tasks.py: "{label} needs
    # a method"), and `engines_supporting` then found nothing. The detail
    # underneath said the real reason was the missing method, so the summary
    # line contradicted its own per-engine block and read as a flat no. An
    # agent relaying that tells the user a shipped feature does not exist,
    # which is exactly what happened.
    #
    # A missing method is missing information, not a refusal. Answer it over
    # the task's own candidate methods instead, and say which method the
    # answer is still waiting on.
    if method is None and not tdef.master and tdef.requires:
        return _answer_without_method(tdef, task, subtype)

    available = engines_supporting(method, task, subtype)
    decision = route_engine(method, task, subtype)
    per_engine = {}
    for e in ENGINES:
        v = supports(e, method, task, subtype)
        per_engine[e] = {"supported": v.supported, "reasons": list(v.reasons),
                         "warnings": list(v.warnings)}
    return {
        "known": True, "task": task, "subtype": subtype, "method": method,
        "label": tdef.label, "description": tdef.description,
        "supported": bool(available), "engines": list(available),
        "recommended_engine": decision.engine, "reason": decision.reason,
        "refusals": list(decision.refusals), "warnings": list(decision.warnings),
        "per_engine": per_engine,
        "plottable_fields": list(tdef.plottable_fields),
        "parameters": _parameter_summary(task, subtype),
    }


def _answer_without_method(tdef, task: str, subtype: str) -> dict:
    """`capability_answer` for a task whose method has not been named yet.

    `supported` stays a plain bool -- true when SOME (engine, method) pair
    can run this task here -- so nothing downstream has to learn a third
    state. `needs_method` carries the rest: the answer is real, and it is
    not yet the whole answer.
    """
    candidates = tdef.methods if tdef.methods is not None else tuple(CANONICAL_METHODS)
    by_method: dict[str, list[str]] = {}
    per_engine: dict[str, dict] = {}
    for e in ENGINES:
        ok_methods = [m for m in candidates if supports(e, m, task, subtype).supported]
        per_engine[e] = {
            "supported": bool(ok_methods),
            "methods": ok_methods,
            # The refusal for an engine that cannot run this at ANY method is
            # the same for every one of them, so report it once rather than
            # once per candidate.
            "reasons": ([] if ok_methods else
                        list(supports(e, candidates[0] if candidates else None,
                                      task, subtype).reasons)),
            "warnings": [],
        }
        for m in ok_methods:
            by_method.setdefault(m, []).append(e)

    engines = [e for e in ENGINES if per_engine[e]["supported"]]
    methods = sorted(by_method)
    if engines and len(methods) == 1:
        reason = (f"{tdef.label} runs here on {', '.join(e.upper() for e in engines)}, "
                  f"at {methods[0]} -- the only level of theory this app defines it for.")
    elif engines:
        reason = (f"{tdef.label} runs here on {', '.join(e.upper() for e in engines)}. "
                  f"Which level of theory: {', '.join(methods)}? Naming one narrows this "
                  f"to the engine that would actually be chosen.")
    else:
        reason = f"No engine in this deployment can run {tdef.name} at any method."
    return {
        "known": True, "task": task, "subtype": subtype, "method": None,
        "label": tdef.label, "description": tdef.description,
        "supported": bool(engines), "needs_method": True,
        "engines": engines, "methods": methods, "engines_by_method": by_method,
        "recommended_engine": None, "reason": reason,
        "refusals": [], "warnings": [],
        "per_engine": per_engine,
        "plottable_fields": list(tdef.plottable_fields),
        "parameters": _parameter_summary(task, subtype),
    }


def describe_engine(engine: str) -> dict:
    """Everything recorded about one engine, with per-cell evidence."""
    engine = canonical_engine(engine)
    rows = {}
    for (e, m), caps in CAPABILITIES.items():
        if e != engine:
            continue
        rows[m] = {
            "capabilities": {c: getattr(caps, c) for c in CAPABILITY_FIELDS},
            "available": {c: caps.has(c) for c in CAPABILITY_FIELDS},
            "evidence": {c: {"level": caps.level_for(c),
                             "observed": caps.evidence[c].observed,
                             "source": caps.evidence[c].source}
                         for c in CAPABILITY_FIELDS if c in caps.evidence},
            "verified": caps.verified,
            "notes": caps.notes,
        }
    return {"engine": engine, "methods": rows}


def what_is_missing(task: str, subtype: str, method: Optional[str],
                    engine: Optional[str], params: Optional[dict] = None) -> list[dict]:
    """Required-but-absent parameters, each with the question to ask.

    Phase 2's `validate_draft` builds on this; exposing it here means the
    same answer is available to the registry API and to a test without
    going through the agent.
    """
    return [
        {"name": spec.name, "type": spec.type, "label": spec.label,
         "ask": spec.ask, "help": spec.help, "options": list(spec.options)}
        for spec in missing_required(task, subtype, method, engine, params)
    ]


def catalog() -> dict:
    """The whole v2 registry, serialized. Backs `GET /api/job-registry`'s
    v2 payload and the capability-doc generator."""
    tasks_out = []
    for (task, subtype), tdef in TASKS.items():
        tasks_out.append({
            "task": task, "subtype": subtype, "name": tdef.name, "label": tdef.label,
            "description": tdef.description, "requires": list(tdef.requires),
            "engines": list(tdef.engines) if tdef.engines else None,
            "methods": list(tdef.methods) if tdef.methods else None,
            "master": tdef.master,
            "params": [p.to_dict() for p in params_for(task, subtype)],
            "engine_support": {
                m: list(engines_supporting(m, task, subtype))
                for m in CANONICAL_METHODS
            },
        })
    return {
        "schema_version": 2,
        "engines": list(ENGINES),
        "methods": list(CANONICAL_METHODS),
        "tasks": tasks_out,
        "capabilities": {f"{e}/{m}": {
            "engine": e, "method": m,
            "capabilities": {c: getattr(caps, c) for c in CAPABILITY_FIELDS},
            "available": {c: caps.has(c) for c in CAPABILITY_FIELDS},
            "verified": caps.verified, "notes": caps.notes,
        } for (e, m), caps in CAPABILITIES.items()},
    }


def suggest_for_param(name: str, value: Any = None, engine: str = "pyscf") -> list[str]:
    """Suggestions for one parameter's value, where a pool exists."""
    if name == "basis":
        return suggest_basis(value, engine=engine)
    if name == "functional":
        return suggest_functional(value, engine=engine)
    if name == "df_basis":
        return keyword_suggest.suggest_df_basis_options(value, engine="bagel")
    if name == "method":
        resolved, hits = resolve_method(value)
        return [resolved] if resolved else hits
    spec = next((p for p in params_for("single_point", "gs") if p.name == name), None)
    return list(spec.options) if spec is not None else []


def engines_for(task: str, subtype: str = "", method: Optional[str] = None) -> list[str]:
    return list(engines_supporting(method, task, subtype))


def get_caps_row(engine: str, method: str):
    return get_caps(engine, method)
