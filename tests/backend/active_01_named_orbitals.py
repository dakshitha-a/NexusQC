#!/usr/bin/env python3
"""Naming the active orbitals yourself -- see
docs/trackers/2026-08-named-active-space.md.

A CASSCF active space is chosen by count everywhere else in this app: say
twelve electrons in nine orbitals and the engine takes the nine orbitals
around the HOMO. `active_space_orbital_indices` names them instead, as a
list of 1-based orbital numbers, which BAGEL expresses through its
`active` keyword and PySCF through `mcscf.sort_mo`.

**The load-bearing check is the first one.** The parameter exists only
for a user who named the orbitals themselves. Leaving it out of the
elicitation flow stops the app from asking for it and does nothing about
the real risk, which is a model filling it in unprompted from orbital
numbers lying around in the conversation -- a previous job's orbital
table, an active-space recommendation. A guessed space reaches the
approval card looking exactly like a chosen one and computes something
else entirely, so a draft that says nothing about specific orbitals has
to arrive READY with the field ABSENT, not defaulted and not an empty
list.

The rest is shape (both engines require the list to be as long as
active_orbitals), the ORCA answer (no equivalent keyword -- the user is
offered the engines that have one rather than losing the field quietly),
and one real PySCF run proving the orbitals named are the orbitals used.

Runs in-process against the registry and the PySCF runner. The CASSCF
runs use a temporary directory rather than the job store, so this script
creates no jobs and leaves nothing in anyone's job list.

Run:  PYTHONPATH=$PWD python3 tests/backend/active_01_named_orbitals.py
"""
from __future__ import annotations

import contextlib
import io
import shutil
import sys
import tempfile

from app.chemistry.jobs.base import JobSpec
from app.chemistry.jobs.preview import build_input_preview
from app.chemistry.molecule import resolve_molecule
from app.chemistry.registry2.elicitation import validate_draft
from app.chemistry.registry2.params import PARAMS, missing_required

PASS = 0
FAIL = 0
FIELD = "active_space_orbital_indices"


def check(label: str, ok: bool, detail: str = "") -> None:
    global PASS, FAIL
    if ok:
        PASS += 1
        print(f"  [PASS] {label}")
    else:
        FAIL += 1
        print(f"  [FAIL] {label}" + (f"\n         {detail}" if detail else ""))


with contextlib.redirect_stderr(io.StringIO()):
    WATER = resolve_molecule("water").to_dict()
STATE = {"molecule": WATER}
BASE_PARAMS = {"basis": "sto-3g", "active_electrons": 4, "active_orbitals": 4, "n_states": 2}
# A draft states EXCITED states and a JobSpec states state-averaged ROOTS,
# and this file exercises both: `draft()` goes through validate_draft while
# the preview and live-run sections build a JobSpec directly. Two roots is
# one excited state, so these describe the same calculation.
DRAFT_PARAMS = {k: v for k, v in BASE_PARAMS.items() if k != "n_states"}
DRAFT_PARAMS["n_excited_states"] = BASE_PARAMS["n_states"] - 1


def draft(engine: str = "bagel", **extra):
    d = {"task": "single_point", "subtype": "ee", "method": "casscf", "engine": engine,
         "params": {**DRAFT_PARAMS, **extra}}
    return validate_draft(d, STATE, check_external=False)


def main() -> int:
    print("== the field is never asked for, and never appears on its own ==")
    v = draft()
    check("a CASSCF draft that says nothing about orbitals is READY",
          v.status == "ready", f"got {v.status}, asking for {v.asking_for}")
    check("and the field is absent, not defaulted and not an empty list",
          FIELD not in v.draft["params"] or v.draft["params"][FIELD] is None,
          f"got {v.draft['params'].get(FIELD)!r}")
    for engine in ("bagel", "pyscf", "orca"):
        missing = [s.name for s in missing_required("single_point", "ee", "casscf", engine, {})]
        check(f"the elicitor never asks for it on {engine}", FIELD not in missing,
              f"missing_required returned {missing}")
    spec = next(s for s in PARAMS if s.name == FIELD)
    check("it has no question text, so nothing can ask it", not spec.ask)
    check("and no required_when, so no draft is ever incomplete without it",
          spec.required_when is None, f"got {spec.required_when!r}")
    check("its help tells the model not to infer one",
          "ONLY set this when" in spec.help and "never infer" in spec.help, spec.help)

    print("\n== a named space is carried through, and said out loud ==")
    v = draft(**{FIELD: [3, 4, 5, 6]})
    check("a list as long as the active space is accepted", v.status == "ready",
          f"got {v.status}: {v.ask_user_exactly}")
    check("and reaches the params unchanged", v.draft["params"].get(FIELD) == [3, 4, 5, 6],
          f"got {v.draft['params'].get(FIELD)!r}")
    check("with a note saying the space is the named one, not the engine's",
          any("named orbitals" in n for n in v.notes), f"notes: {list(v.notes)}")

    print("\n== a malformed list is refused, never quietly dropped ==")
    for label, value, expect in (
        ("too few orbitals for the space", [3, 4], "4 orbitals wide"),
        ("too many", [3, 4, 5, 6, 7], "4 orbitals wide"),
        ("the same orbital twice", [3, 3, 5, 6], "more than once"),
        ("a zero index, when numbering starts at 1", [0, 4, 5, 6], "start at 1"),
        ("a negative index", [-2, 4, 5, 6], "start at 1"),
    ):
        v = draft(**{FIELD: value})
        check(f"{label} stops the draft", v.status != "ready", f"got {v.status}")
        check(f"{label}: asks about the orbitals, not something else",
              v.asking_for == FIELD, f"asking for {v.asking_for!r}")
        check(f"{label}: says what is wrong with it",
              expect in (v.ask_user_exactly or ""), v.ask_user_exactly)
        check(f"{label}: the list is not silently discarded",
              v.draft["params"].get(FIELD) == value, f"got {v.draft['params'].get(FIELD)!r}")

    print("\n== ORCA has no keyword for this, and says so ==")
    v = draft(engine="orca", **{FIELD: [3, 4, 5, 6]})
    check("an ORCA draft asking for named orbitals is not READY", v.status != "ready",
          f"got {v.status}")
    check("it asks which engine to use instead", v.asking_for == "engine",
          f"asking for {v.asking_for!r}")
    check("naming the two that can do it",
          "bagel" in (v.ask_user_exactly or "").lower()
          and "pyscf" in (v.ask_user_exactly or "").lower(), v.ask_user_exactly)
    check("and offering them as the options", set(v.options or ()) == {"bagel", "pyscf"},
          f"got {v.options!r}")
    check("while saying what dropping the list would mean",
          "around the HOMO" in (v.ask_user_exactly or ""), v.ask_user_exactly)

    print("\n== the approval card shows the space that will actually run ==")
    named = {**BASE_PARAMS, FIELD: [3, 4, 5, 6]}
    bagel_text = build_input_preview(JobSpec(task="single_point", subtype="ee", method="casscf",
                                             engine="bagel", molecule=WATER, params=dict(named)))
    check("BAGEL's preview carries the active keyword",
          '"active"' in bagel_text and "3," in bagel_text,
          [l for l in bagel_text.splitlines() if "active" in l])
    pyscf_text = build_input_preview(JobSpec(task="single_point", subtype="ee", method="casscf",
                                             engine="pyscf", molecule=WATER, params=dict(named)))
    check("PySCF's preview carries the sort_mo call, with its base spelled out",
          "sort_mo([3, 4, 5, 6], base=1)" in pyscf_text,
          [l for l in pyscf_text.splitlines() if "sort_mo" in l])
    # A draft with no named space must not grow either of them.
    plain = build_input_preview(JobSpec(task="single_point", subtype="ee", method="casscf",
                                        engine="pyscf", molecule=WATER, params=dict(BASE_PARAMS)))
    check("and neither appears when no orbitals were named", "sort_mo" not in plain)

    print("\n== a real run uses the orbitals it was given ==")
    from app.chemistry.jobs import pyscf_runner
    energies = {}
    tmpdirs = []
    for label, extra in (("default", {}), ("3,4,5,6", {FIELD: [3, 4, 5, 6]}),
                         ("3,4,5,7", {FIELD: [3, 4, 5, 7]})):
        d = tempfile.mkdtemp()
        tmpdirs.append(d)
        params = {**BASE_PARAMS, "n_states": 1, **extra, "_job_dir": d}
        with contextlib.redirect_stdout(io.StringIO()):
            result = pyscf_runner.run_casscf(WATER, params)
        energies[label] = result["summary"]["casscf_energy_hartree"]
        got = result["summary"].get(FIELD)
        check(f"the {label} run records the space it used",
              got == extra.get(FIELD), f"got {got!r}")
    for d in tmpdirs:
        shutil.rmtree(d, ignore_errors=True)
    check("naming a space changes the energy, i.e. sort_mo is really applied",
          energies["3,4,5,6"] != energies["default"],
          f"{energies['3,4,5,6']} vs {energies['default']}")
    check("and naming a different space changes it again",
          energies["3,4,5,7"] != energies["3,4,5,6"],
          f"{energies['3,4,5,7']} vs {energies['3,4,5,6']}")

    print(f"\n{PASS}/{PASS + FAIL} checks passed")
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    code = main()
    print("[PASS] ALL CHECKS PASSED" if code == 0 else "[FAIL] see above")
    sys.exit(code)
