#!/usr/bin/env python3
"""P2.1 -- drive `validate_draft` from an empty draft to a ready one.

Twenty-one scenarios, covering every single_point and opt subtype plus
every other task a user can ask for, each walked from nothing to `ready`
by answering whatever question the backend returns. What is asserted at
each step is the *sequence* -- which parameter is asked for, in what order
-- and, separately, that the question's wording came from the registry
rather than being composed here or by a model.

That split matters. Hard-coding all twenty-one question strings would make
this file fail every time a help text is reworded, which trains whoever
sees the failure to update the expectation without reading it. Instead:

- the ordered list of `asking_for` names is written out literally, because
  that IS the behaviour under test and it must not drift silently;
- each question's text is compared to `PARAMS_BY_NAME[name].ask`, so a
  question that stops coming from the parameter table fails immediately;
- the handful of questions `elicitation` composes itself -- for a
  molecule, a task, an end geometry, a blind job's engine, an unavailable
  combination, a stale job id -- have no ParamSpec to compare against, so
  those are pinned literally here.

Several checks are negative, and those are the load-bearing ones: they
pin behaviours whose absence is silent. A gradient job must NOT carry an
isosurface threshold, a CASSCF excited-state job must NOT carry a
Tamm-Dancoff flag, an autoCAS recommendation must NOT ask the user for the
active space it exists to produce, and a blind input must NOT be routed to
an engine the user did not name. Every one of those was a real defect in
the tables this script was written against, found by walking the
scenarios, and none would have shown up as an error -- only as a wrong
job quietly submitted.

Run:  PYTHONPATH=$PWD python3 tests/backend/elic_01_draft_scenarios.py
"""
from __future__ import annotations

import json
import shutil
import sys
from dataclasses import dataclass, field
from typing import Any, Optional

from app.chemistry.registry2.elicitation import BSE_SEARCH_OPTION, validate_draft
from app.chemistry.registry2.params import PARAMS_BY_NAME
from app.config import JOBS_DIR

PASS = 0
FAIL = 0


def check(label: str, ok: bool, detail: str = "") -> None:
    global PASS, FAIL
    if ok:
        PASS += 1
        print(f"  [PASS] {label}")
    else:
        FAIL += 1
        print(f"  [FAIL] {label}" + (f"\n         {detail}" if detail else ""))


WATER = {
    "name": "water", "formula": "H2O", "charge": 0, "multiplicity": 1,
    "atoms": [
        {"element": "O", "x": 0.0, "y": 0.0, "z": 0.117},
        {"element": "H", "x": 0.0, "y": 0.757, "z": -0.469},
        {"element": "H", "x": 0.0, "y": -0.757, "z": -0.469},
    ],
}
STATE = {"molecule": WATER}

# The questions elicitation.py composes rather than reading off a
# ParamSpec. Pinned literally, because there is nowhere else to compare
# them to and their wording is what the user actually hears.
ASK_TASK = "What kind of calculation would you like to run?"
ASK_MOLECULE = ("Which molecule should this run on? You can give a name, a SMILES "
                "string, or draw it in the sketcher.")
ASK_END_GEOMETRY = ("This needs a second structure as well. What is the end geometry "
                    "-- a name, a SMILES string, or a structure you draw?")
ASK_BLIND_ENGINE = ("Which engine should this input be run with -- ORCA or BAGEL? A "
                    "pasted input is run verbatim, so its syntax has to match the "
                    "engine.")

COMPOSED = {
    "task": ASK_TASK,
    "molecule": ASK_MOLECULE,
    "_end_molecule": ASK_END_GEOMETRY,
    "engine": ASK_BLIND_ENGINE,
}


@dataclass
class Scenario:
    name: str
    draft: dict
    steps: list[tuple[str, Any]]          # (asking_for, answer to give)
    engine: str
    params: dict                          # exact final params
    state: dict = field(default_factory=lambda: dict(STATE))
    warnings_containing: tuple[str, ...] = ()
    notes_containing: tuple[str, ...] = ()
    absent_params: tuple[str, ...] = ()


def _apply(draft: dict, state: dict, asking_for: str, answer: Any) -> tuple[dict, dict]:
    if asking_for == "task":
        draft["task"], draft["subtype"] = answer
    elif asking_for == "molecule":
        state = dict(state, molecule=answer)
    elif asking_for in ("method", "engine"):
        draft[asking_for] = answer
    else:
        draft.setdefault("params", {})[asking_for] = answer
    return draft, state


def run_scenario(s: Scenario) -> None:
    print(f"\n== {s.name} ==")
    draft, state = dict(s.draft), dict(s.state)
    actual_sequence: list[str] = []

    for index, (expected_field, answer) in enumerate(s.steps):
        verdict = validate_draft(draft, state)
        if verdict.status != "incomplete":
            check(f"step {index + 1} asks for {expected_field}", False,
                  f"status was {verdict.status!r}, not 'incomplete'")
            return
        actual_sequence.append(verdict.asking_for)
        if verdict.asking_for != expected_field:
            check(f"step {index + 1} asks for {expected_field}", False,
                  f"asked for {verdict.asking_for!r} instead")
            return
        # The wording must come from the registry, not from this file and
        # not from a model.
        spec = PARAMS_BY_NAME.get(expected_field)
        if spec is not None:
            source_ok = verdict.ask_user_exactly == spec.ask
            detail = (f"got {verdict.ask_user_exactly!r}\n         "
                      f"want {spec.ask!r}")
        else:
            source_ok = verdict.ask_user_exactly == COMPOSED[expected_field]
            detail = f"got {verdict.ask_user_exactly!r}"
        if not source_ok:
            check(f"step {index + 1} ({expected_field}) asks the registry's own question",
                  False, detail)
            return
        draft, state = _apply(draft, state, expected_field, answer)

    check(f"ask sequence is {' -> '.join(x for x, _ in s.steps)}",
          actual_sequence == [x for x, _ in s.steps],
          f"got {actual_sequence}")

    verdict = validate_draft(draft, state)
    check("reaches ready", verdict.status == "ready",
          f"status={verdict.status!r} asking_for={verdict.asking_for!r} "
          f"ask={verdict.ask_user_exactly!r}")
    if verdict.status != "ready":
        return
    check(f"routes to {s.engine}", verdict.draft["resolved_engine"] == s.engine,
          f"routed to {verdict.draft['resolved_engine']!r}")
    # Routing's answer must not be written back onto the user's request.
    # A draft is re-validated after every change, so folding the two
    # together makes the next pass read the backend's own choice as an
    # explicit request -- and the approval card then tells the user that
    # PYSCF "was requested explicitly" when they never named an engine.
    requested = s.draft.get("engine") or next(
        (a for f, a in s.steps if f == "engine"), None)
    check("the user's engine request is kept separate from routing's answer",
          verdict.draft["engine"] == requested,
          f"engine={verdict.draft['engine']!r}, user asked for {requested!r}")
    check("final params exact", verdict.draft["params"] == s.params,
          f"got  {json.dumps(verdict.draft['params'], sort_keys=True, default=str)}\n"
          f"         want {json.dumps(s.params, sort_keys=True, default=str)}")
    for absent in s.absent_params:
        check(f"{absent} is absent", absent not in verdict.draft["params"],
              f"present with value {verdict.draft['params'].get(absent)!r}")
    for fragment in s.warnings_containing:
        check(f"warns about {fragment!r}",
              any(fragment in w for w in verdict.warnings),
              f"warnings were {list(verdict.warnings)}")
    for fragment in s.notes_containing:
        check(f"notes {fragment!r}", any(fragment in n for n in verdict.notes),
              f"notes were {list(verdict.notes)}")
    check("a ready verdict asks nothing", verdict.ask_user_exactly == "")
    check("a ready verdict carries a preview", bool(verdict.preview))


BOND = {"type": "bond", "atoms": [1, 2]}
CONSTRAINT = [{"type": "bond", "atoms": [1, 2], "value": 0.98}]

SCENARIOS = [
    Scenario(
        name="1 -- single_point/gs, from a completely empty draft",
        draft={}, state={},
        steps=[("task", ("single_point", "gs")), ("molecule", WATER),
               ("method", "hf"), ("basis", "sto-3g")],
        engine="pyscf", params={"basis": "sto-3g"},
        # The defect this pins: isoval used to be defaulted onto every
        # single_point, including ones rendering no orbitals at all.
        absent_params=("isoval", "orbital_indices"),
    ),
    Scenario(
        name="2 -- single_point/gs at DFT needs a functional",
        draft={"task": "single_point", "subtype": "gs", "method": "dft"},
        steps=[("basis", "6-31g*"), ("functional", "b3lyp")],
        engine="pyscf", params={"basis": "6-31g*", "functional": "b3lyp"},
    ),
    Scenario(
        name="3 -- single_point/ee at DFT",
        draft={"task": "single_point", "subtype": "ee", "method": "dft"},
        steps=[("basis", "6-31g*"), ("functional", "b3lyp"), ("n_states", 3)],
        engine="pyscf",
        # Full TDDFT, not TDA. A user who asks for "a TDDFT spectrum" means
        # the complete linear response; defaulting to the approximation
        # and not saying so is a silent substitution.
        params={"basis": "6-31g*", "functional": "b3lyp", "n_states": 3,
                "use_tda": False, "want_oscillator_strengths": False},
        warnings_containing=("counts excited states above the ground state",
                             "Full TDDFT (the complete linear response"),
    ),
    Scenario(
        name="4 -- single_point/ee at CASSCF",
        draft={"task": "single_point", "subtype": "ee", "method": "casscf"},
        steps=[("basis", "sto-3g"), ("active_electrons", 4), ("active_orbitals", 4),
               ("n_states", 3)],
        engine="pyscf",
        params={"basis": "sto-3g", "active_electrons": 4, "active_orbitals": 4,
                "n_states": 3, "want_oscillator_strengths": False},
        # TDA is a single-reference linear-response approximation; a state
        # average does not solve those equations, so the flag must not
        # appear on the card at all.
        absent_params=("use_tda",),
        warnings_containing=("no oscillator strengths",
                             "state-averaged roots including the ground state"),
    ),
    Scenario(
        name="5 -- single_point/grad",
        draft={"task": "single_point", "subtype": "grad", "method": "hf"},
        steps=[("basis", "sto-3g")],
        engine="pyscf", params={"basis": "sto-3g"},
        absent_params=("isoval",),
    ),
    Scenario(
        name="6 -- single_point/nac at CASSCF routes to PySCF",
        draft={"task": "single_point", "subtype": "nac", "method": "casscf"},
        steps=[("basis", "sto-3g"), ("n_states", 3), ("state_pairs", [[1, 2]])],
        engine="pyscf",
        params={"basis": "sto-3g", "n_states": 3, "state_pairs": [[1, 2]]},
        warnings_containing=("any pair of roots inside the state average",),
    ),
    Scenario(
        name="7 -- single_point/nac at DFT routes to ORCA and warns about pairing",
        draft={"task": "single_point", "subtype": "nac", "method": "dft"},
        steps=[("basis", "sto-3g"), ("functional", "b3lyp"), ("n_states", 3),
               ("state_pairs", [[1, 2]])],
        engine="orca",
        params={"basis": "sto-3g", "functional": "b3lyp", "n_states": 3,
                "state_pairs": [[1, 2]]},
        warnings_containing=("ground-to-excited coupling only", "B88-containing"),
    ),
    Scenario(
        name="8 -- opt/min",
        draft={"task": "opt", "subtype": "min", "method": "hf"},
        steps=[("basis", "sto-3g")],
        engine="pyscf", params={"basis": "sto-3g", "max_steps": 200},
    ),
    Scenario(
        name="9 -- opt/constrained",
        draft={"task": "opt", "subtype": "constrained", "method": "hf"},
        steps=[("basis", "sto-3g"), ("constraints", CONSTRAINT)],
        engine="pyscf",
        params={"basis": "sto-3g", "max_steps": 200, "constraints": CONSTRAINT},
    ),
    Scenario(
        name="10 -- opt/ci needs both states and a state average to hold them",
        draft={"task": "opt", "subtype": "ci", "method": "casscf"},
        steps=[("basis", "sto-3g"), ("active_electrons", 4), ("active_orbitals", 4),
               ("n_states", 3), ("target_state", 1), ("target_state_2", 2)],
        engine="bagel",
        params={"basis": "sto-3g", "active_electrons": 4, "active_orbitals": 4,
                "n_states": 3, "target_state": 1, "target_state_2": 2,
                "max_steps": 200},
    ),
    Scenario(
        name="11 -- freq",
        draft={"task": "freq", "method": "hf"},
        steps=[("basis", "sto-3g")],
        engine="pyscf", params={"basis": "sto-3g", "temperature_K": 298.15},
    ),
    Scenario(
        name="12 -- opt_freq",
        draft={"task": "opt_freq", "method": "hf"},
        steps=[("basis", "sto-3g")],
        engine="pyscf",
        params={"basis": "sto-3g", "temperature_K": 298.15, "max_steps": 200},
    ),
    Scenario(
        name="13 -- pes_1d",
        draft={"task": "pes_1d", "method": "hf"},
        steps=[("basis", "sto-3g"), ("n_points", 10), ("coordinate", BOND),
               ("scan_range", [0.8, 1.6])],
        engine="pyscf",
        params={"basis": "sto-3g", "n_points": 10, "coordinate": BOND,
                "scan_range": [0.8, 1.6]},
    ),
    Scenario(
        name="14 -- interp_pes asks for the end geometry first",
        draft={"task": "interp_pes", "method": "hf"},
        steps=[("_end_molecule", WATER), ("basis", "sto-3g"), ("n_points", 10)],
        engine="pyscf",
        params={"basis": "sto-3g", "n_points": 10, "_end_molecule": WATER,
                "interpolation_method": "idpp"},
    ),
    Scenario(
        name="15 -- neb_ts is ORCA-only here and always asks about preopt",
        draft={"task": "neb_ts", "method": "hf"},
        steps=[("_end_molecule", WATER), ("basis", "sto-3g"), ("preopt", True)],
        engine="orca",
        params={"basis": "sto-3g", "preopt": True, "_end_molecule": WATER,
                "n_images": 6, "max_steps": 200},
    ),
    Scenario(
        name="17 -- cas_reco/autocas never asks for the space it produces",
        draft={"task": "cas_reco", "subtype": "autocas", "method": "casscf"},
        steps=[("basis", "sto-3g"), ("n_states", 3)],
        engine="pyscf",
        params={"basis": "sto-3g", "n_states": 3, "entropy_method": "exact_fci",
                "max_active_orbitals": 12},
        absent_params=("active_electrons", "active_orbitals"),
    ),
    Scenario(
        name="18 -- cas_reco/explain does ask, because the space is its input",
        draft={"task": "cas_reco", "subtype": "explain", "method": "casscf"},
        steps=[("basis", "sto-3g"), ("active_electrons", 6), ("active_orbitals", 6)],
        engine="pyscf",
        params={"basis": "sto-3g", "active_electrons": 6, "active_orbitals": 6},
        # Nothing is being recommended here, so there is no recommendation
        # to put a ceiling on.
        absent_params=("max_active_orbitals",),
    ),
    Scenario(
        name="19 -- blind input, engine stated by the user, never inferred",
        draft={"task": "blind"}, state={},
        steps=[("engine", "orca"),
               ("raw_input_text", "! HF STO-3G\n* xyz 0 1\nO 0 0 0\n*\n")],
        engine="orca",
        params={"raw_input_text": "! HF STO-3G\n* xyz 0 1\nO 0 0 0\n*\n"},
    ),
    Scenario(
        name="20 -- a free-text task phrase resolves, and says so",
        draft={"task": "geometry optimization", "method": "hf"},
        steps=[("basis", "sto-3g")],
        engine="pyscf", params={"basis": "sto-3g", "max_steps": 200},
        notes_containing=("Read 'geometry optimization' as opt/min.",),
    ),
    Scenario(
        name="21 -- a glued Pople suffix is corrected, and says so",
        draft={"task": "single_point", "subtype": "gs", "method": "hf",
               "params": {"basis": "6-31Gd"}},
        steps=[],
        engine="pyscf", params={"basis": "6-31G(d)"},
        notes_containing=("Interpreted basis '6-31Gd' as '6-31G(d)'",),
    ),
]


# ------------------------------------------------------- wigner, on a real job

_FIXTURE_JOB = "elic01-freq-fixture"


def _make_completed_frequency_job() -> None:
    """A minimal on-disk frequency job, so the Wigner scenario's source-job
    check runs against the job store rather than a stub. Removed again at
    the end of the run."""
    d = JOBS_DIR / _FIXTURE_JOB
    d.mkdir(parents=True, exist_ok=True)
    (d / "spec.json").write_text(json.dumps({
        "job_id": _FIXTURE_JOB, "method": "frequency", "engine": "pyscf",
        "molecule": WATER, "params": {"method": "hf", "basis": "sto-3g"},
        "label": None, "created_at": "2026-08-18T00:00:00", "parent_job_id": None,
    }))
    (d / "meta.json").write_text(json.dumps({"status": "completed"}))


def _remove_fixture_job() -> None:
    shutil.rmtree(JOBS_DIR / _FIXTURE_JOB, ignore_errors=True)


def run_wigner_scenarios() -> None:
    print("\n== 16 -- wigner_spectra checks its source job before anything else ==")
    spec = PARAMS_BY_NAME["source_frequency_job_id"]

    # The source job is asked for first: it supplies the geometry, so it is
    # a prerequisite in the same sense a molecule is, not a late parameter.
    draft = {"task": "wigner_spectra", "method": "casscf"}
    verdict = validate_draft(draft, {})
    check("asks for the source frequency job first",
          verdict.asking_for == "source_frequency_job_id",
          f"asked for {verdict.asking_for!r}")
    check("with the registry's own question", verdict.ask_user_exactly == spec.ask)

    # A stale id is corrected immediately, not four questions later.
    draft["params"] = {"source_frequency_job_id": "no-such-job"}
    verdict = validate_draft(draft, {})
    check("a missing job is caught at once",
          verdict.asking_for == "source_frequency_job_id"
          and "No job with id no-such-job was found" in verdict.ask_user_exactly,
          f"got {verdict.ask_user_exactly!r}")
    check("and the bad id is cleared from the draft",
          "source_frequency_job_id" not in verdict.draft["params"])

    # A real job of the wrong kind is refused by kind, not by id.
    draft["params"] = {"source_frequency_job_id": _FIXTURE_JOB}
    verdict = validate_draft(draft, {})
    check("a completed frequency job is accepted",
          verdict.asking_for != "source_frequency_job_id",
          f"still asking: {verdict.ask_user_exactly!r}")

    # Walk it the rest of the way.
    for name, value in (("basis", "sto-3g"), ("active_electrons", 4),
                        ("active_orbitals", 4), ("n_states", 3), ("n_samples", 50)):
        verdict = validate_draft(draft, {})
        if verdict.status != "incomplete":
            break
        check(f"asks for {verdict.asking_for}", verdict.asking_for == name,
              f"asked for {verdict.asking_for!r}, expected {name!r}")
        draft["params"][verdict.asking_for] = value
    verdict = validate_draft(draft, {})
    check("wigner_spectra reaches ready", verdict.status == "ready",
          f"status={verdict.status!r} ask={verdict.ask_user_exactly!r}")
    if verdict.status == "ready":
        check("n_samples was asked, never defaulted", verdict.draft["params"]["n_samples"] == 50)
        check("use_tda is absent for a CASSCF ensemble",
              "use_tda" not in verdict.draft["params"],
              f"params were {verdict.draft['params']}")


def run_unavailable_scenarios() -> None:
    print("\n== unavailable combinations explain themselves ==")
    verdict = validate_draft(
        {"task": "single_point", "subtype": "gs", "method": "caspt2", "engine": "pyscf",
         "params": {"basis": "sto-3g", "active_electrons": 4, "active_orbitals": 4}},
        STATE)
    check("CASPT2 on PySCF is unavailable, not rerouted",
          verdict.status == "unavailable", f"status={verdict.status!r}")
    check("with a reason naming the combination",
          any("caspt2" in r.lower() for r in verdict.refusals),
          f"refusals={list(verdict.refusals)}")
    check("and BAGEL offered as the alternative",
          list(verdict.alternatives) == ["bagel"], f"alts={list(verdict.alternatives)}")
    check("an unavailable verdict still gives the model something to say",
          bool(verdict.ask_user_exactly))

    verdict = validate_draft(
        {"task": "opt", "subtype": "constrained", "method": "casscf", "engine": "bagel",
         "params": {"basis": "sto-3g", "active_electrons": 4, "active_orbitals": 4,
                    "constraints": CONSTRAINT}},
        STATE)
    check("BAGEL constrained CASSCF optimization is refused (fix_atom is a no-op there)",
          verdict.status == "unavailable", f"status={verdict.status!r}")


def run_shape_scenarios() -> None:
    print("\n== draft shape and menus ==")
    # A model that flattens the draft has made a formatting mistake, not a
    # chemistry one; absorbing it costs nothing and saves a turn.
    flat = validate_draft({"task": "single_point", "subtype": "gs", "method": "hf",
                           "basis": "sto-3g"}, STATE)
    nested = validate_draft({"task": "single_point", "subtype": "gs", "method": "hf",
                             "params": {"basis": "sto-3g"}}, STATE)
    check("a flattened draft is read the same as a nested one",
          flat.status == nested.status == "ready"
          and flat.draft["params"] == nested.draft["params"],
          f"flat={flat.draft['params']} nested={nested.draft['params']}")

    # Writing None clears a field rather than setting it to null.
    cleared = validate_draft({"task": "single_point", "subtype": "gs", "method": "hf",
                              "params": {"basis": None}}, STATE)
    check("writing None clears a field instead of storing a null",
          cleared.status == "incomplete" and cleared.asking_for == "basis",
          f"status={cleared.status!r} asking_for={cleared.asking_for!r}")

    # A misspelled basis produces the lettered menu, with the BSE escape
    # hatch last; a correctly spelled one produces no menu at all.
    misspelled = validate_draft({"task": "single_point", "subtype": "gs", "method": "hf",
                                 "params": {"basis": "ccpvdz"}}, STATE)
    options = (misspelled.keyword_options or {}).get("basis_options") or []
    check("a misspelled basis offers a spelling menu", len(options) > 1,
          f"options={options}")
    check("whose last entry is the Basis Set Exchange escape hatch",
          options[-1:] == [BSE_SEARCH_OPTION], f"options={options}")
    exact = validate_draft({"task": "single_point", "subtype": "gs", "method": "hf",
                            "params": {"basis": "sto-3g"}}, STATE)
    check("a correctly spelled basis offers no menu", not exact.keyword_options,
          f"keyword_options={exact.keyword_options}")

    # "Run a CASSCF calculation on water" names a level of theory and
    # leaves the calculation implicit -- which is how people talk, and which
    # used to dead-end with "I don't recognize 'CASSCF' as a calculation
    # this app runs", a sentence that reads as nonsense because CASSCF
    # plainly is one. Found by running a real conversation, not by reading.
    as_method = validate_draft({"task": "CASSCF"}, STATE)
    check("a method given where a task was expected is kept, not rejected",
          as_method.draft["method"] == "casscf" and as_method.draft["task"] == "",
          f"draft={ {k: as_method.draft[k] for k in ('task', 'method')} }")
    check("and the question becomes the one the user actually left open",
          as_method.asking_for == "task"
          and as_method.ask_user_exactly == ASK_TASK,
          f"asking_for={as_method.asking_for!r} ask={as_method.ask_user_exactly!r}")
    check("with the reading stated, so the user can correct it",
          any("level of theory" in n for n in as_method.notes),
          f"notes={list(as_method.notes)}")
    # The task itself is still never guessed: a CASSCF on water could be an
    # energy, an optimization or a spectrum.
    check("the task is asked, not inferred from the method",
          as_method.status == "incomplete", f"status={as_method.status!r}")
    # An explicitly-given method is not overwritten by a task-shaped guess.
    both = validate_draft({"task": "CASSCF", "method": "hf"}, STATE)
    check("a method already set is not clobbered by this reading",
          both.draft["method"] == "hf", f"method={both.draft['method']!r}")

    # A model hands over whatever phrase the user used, and a user says
    # "a CASSCF single point energy" -- one string carrying both a task and
    # a level of theory. Both were rejected outright until a real
    # conversation exposed it.
    for phrase, want_task, want_sub, want_method in (
        ("CASSCF single point energy", "single_point", "gs", "casscf"),
        ("B3LYP geometry optimization", "opt", "min", "dft"),
        # `tddft` is a task synonym AND a method synonym, and resolves to
        # both halves at once -- excited states, computed at DFT. That
        # conflation is precisely what the v2 taxonomy exists to undo.
        ("excited states with TDDFT", "single_point", "ee", "dft"),
    ):
        v = validate_draft({"task": phrase}, STATE)
        check(f"{phrase!r} reads as {want_task}/{want_sub} at {want_method}",
              (v.draft["task"], v.draft["subtype"], v.draft["method"])
              == (want_task, want_sub, want_method),
              f"got {v.draft['task']}/{v.draft['subtype']} at {v.draft['method']}")
        check(f"{phrase!r} then asks for a parameter, not for the task again",
              v.asking_for not in ("task", ""), f"asking_for={v.asking_for!r}")

    # Orbital rendering is a single_point with `orbital_indices`, not a task
    # of its own (see tasks.py) -- so every way of asking for one has to
    # land there. Only the plurals were registered, which meant "a molecular
    # orbital visualization" (how the job matrix asks, and how a user
    # naturally would) matched nothing, and neither did `mo_visualization`,
    # the v1 job type still in older notes and in muscle memory.
    for phrase in ("a molecular orbital visualization", "mo_visualization",
                   "molecular orbital", "orbital visualization", "orbitals", "mo"):
        v = validate_draft({"task": phrase, "method": "hf",
                            "params": {"basis": "sto-3g", "orbital_indices": [3, 4, 5]}},
                           STATE)
        check(f"{phrase!r} asks for a single_point with orbitals",
              (v.draft["task"], v.draft["subtype"]) == ("single_point", "gs")
              and v.status == "ready",
              f"got {v.draft['task']}/{v.draft['subtype']} status={v.status}")

    # `custom` was the v1 name for what v2 calls `blind`, and it is still
    # the word in older notes and in the e2e matrix's own phrasing. It
    # resolved to nothing, so "run it as a custom job" got told that a
    # custom job is not a calculation this app runs.
    for phrase in ("custom", "custom job", "raw input", "verbatim input"):
        v = validate_draft({"task": phrase, "engine": "orca",
                            "params": {"raw_input_text": "! HF STO-3G\n* xyz 0 1\nO 0 0 0\n*\n"}},
                           STATE)
        check(f"{phrase!r} asks for a blind engine input",
              v.draft["task"] == "blind" and v.status == "ready",
              f"got task={v.draft['task']!r} status={v.status}")

    # An unrecognized task is not guessed at.
    unknown = validate_draft({"task": "quantum wizardry"}, STATE)
    check("an unrecognized task is queried, never guessed",
          unknown.status == "incomplete" and unknown.asking_for == "task"
          and "quantum wizardry" in unknown.ask_user_exactly,
          f"got {unknown.ask_user_exactly!r}")

    # Exactly two frames on screen make the end geometry unambiguous.
    two_frames = validate_draft(
        {"task": "interp_pes", "method": "hf", "params": {"basis": "sto-3g", "n_points": 5}},
        {"molecule": WATER,
         "molecule_frames": [{"id": "a", "molecule": WATER, "description": "start"},
                             {"id": "b", "molecule": WATER, "description": "end"}]})
    check("two structures on screen resolve the end geometry without asking",
          two_frames.status == "ready"
          and two_frames.draft["params"].get("_end_molecule") == WATER,
          f"status={two_frames.status!r} ask={two_frames.ask_user_exactly!r}")
    check("and the adoption is stated as a note",
          any("second structure in the molecule panel" in n for n in two_frames.notes),
          f"notes={list(two_frames.notes)}")


def main() -> int:
    _make_completed_frequency_job()
    try:
        for scenario in SCENARIOS:
            run_scenario(scenario)
        run_wigner_scenarios()
        run_unavailable_scenarios()
        run_shape_scenarios()
    finally:
        _remove_fixture_job()

    total = PASS + FAIL
    print(f"\n{PASS}/{total} checks passed")
    if FAIL:
        print(f"[FAIL] {FAIL} check(s) failed")
        return 1
    print("[PASS] ALL CHECKS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
