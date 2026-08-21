#!/usr/bin/env python3
"""The active-space literature step: staged matching that never leaves the
molecule, and a "nothing found" outcome that is reachable.

`literature_notes` was a parameter that travelled from tools.py into the
result summary and was touched by nothing in between -- no search populated
it. That empty field is where the fabrication in the founding conversation
came from: asked for an active space for cis,cis-1,3-cyclooctadiene, the
agent found one number anywhere in its search results, a (6e,6o) space for
**cyclotetrasilene**, copied its shape, doubled the pi part to (8e,8o), and
credited a cyclooctadiene paper that gave no active space at all.

The retrieval was fine. What was missing was a step that can come back
empty, so "nothing published for this molecule" was the one answer the
model could not return. These checks hold that shape: the molecule term is
in every query at every tier, relaxation drops the basis and then the state
count and stops, and the no-match text says outright not to substitute an
analogue.

The three search backends are injected, so this exercises the staging with
no network call and no seeded knowledge base.

Run:  PYTHONPATH=$PWD python3 tests/backend/casreco_04_literature_step.py
"""
from __future__ import annotations

import sys

from app.agent import active_space_lit
from app.agent.tools import _spec_from_draft, explain_active_space

PASS = 0
FAIL = 0

WATER = {
    "name": "water", "symbols": ["O", "H", "H"],
    "coords": [[0, 0, 0.117], [0, 0.757, -0.469], [0, -0.757, -0.469]],
    "charge": 0, "multiplicity": 1,
}
EMPTY = "No matching papers found. Try fewer/broader quoted terms."
HIT = "A paper\nhttps://example.org/x\nA CASSCF(4,4) active space was used."


def check(label: str, ok: bool, detail: str = "") -> None:
    global PASS, FAIL
    if ok:
        PASS += 1
        print(f"  [PASS] {label}")
    else:
        FAIL += 1
        print(f"  [FAIL] {label}" + (f"\n         {detail}" if detail else ""))


def _none(_q: str) -> str:
    return EMPTY


def run_staging() -> None:
    print("\n== the molecule is in every query, at every tier ==")
    f = active_space_lit.search("cis,cis-1,3-cyclooctadiene", 3, "def2-svp",
                                kb=_none, scholar=_none, web=_none)
    check("all three tiers were tried", len(f.queries_tried) == 3, repr(f.queries_tried))
    check("every query names the molecule",
          all("cis,cis-1,3-cyclooctadiene" in q for q in f.queries_tried),
          repr(f.queries_tried))
    check("every query quotes it, for literal keyword matching",
          all('"cis,cis-1,3-cyclooctadiene"' in q for q in f.queries_tried),
          repr(f.queries_tried))
    check("the basis relaxes off before the state count",
          "def2-svp" in f.queries_tried[0] and "def2-svp" not in f.queries_tried[1]
          and "3 states" in f.queries_tried[1] and "states" not in f.queries_tried[2],
          repr(f.queries_tried))

    print("\n== nothing found is a real, reportable outcome ==")
    check("matched_at says none", f.matched_at == "none")
    check("found is False", f.found is False)
    notes = f.as_notes()
    check("the notes say nothing was found", "nothing found" in notes, notes[:200])
    check("...and forbid substituting another molecule",
          "do not substitute" in notes.lower(), notes[:300])
    check("...and say any space from here is not a literature value",
          "not a literature value" in notes, notes[:400])

    print("\n== a match stops at the most specific tier that answers ==")
    full = active_space_lit.search("water", 2, "cc-pvdz",
                                   kb=lambda q: HIT, scholar=_none, web=_none)
    check("a first-tier hit matches on all three", full.matched_at == "molecule+states+basis",
          full.matched_at)
    check("...and stops after one query", len(full.queries_tried) == 1,
          repr(full.queries_tried))

    relaxed = active_space_lit.search(
        "water", 2, "cc-pvdz", kb=_none, scholar=_none,
        web=lambda q: EMPTY if "cc-pvdz" in q else HIT)
    check("a second-tier hit is labelled as having relaxed the basis",
          relaxed.matched_at == "molecule+states", relaxed.matched_at)
    check("...and its notes warn that basis details may differ",
          "may differ" in relaxed.as_notes(), relaxed.as_notes()[:300])

    loosest = active_space_lit.search(
        "water", 2, "cc-pvdz", kb=_none, scholar=_none,
        web=lambda q: HIT if "states" not in q else EMPTY)
    check("a third-tier hit is labelled as molecule-only",
          loosest.matched_at == "molecule", loosest.matched_at)
    check("...and its notes say the conditions may not be the ones asked for",
          "may not be the ones" in loosest.as_notes(), loosest.as_notes()[:400])

    print("\n== a failing backend does not sink the search ==")
    def boom(_q: str) -> str:
        raise RuntimeError("network down")
    survived = active_space_lit.search("water", 1, "sto-3g", kb=boom, scholar=_none,
                                       web=lambda q: HIT)
    check("a backend that raises is skipped, not fatal", survived.found is True,
          survived.matched_at)


def run_injection() -> None:
    print("\n== findings ride into the job, and only for their own molecule ==")
    draft = {"task": "cas_reco", "subtype": "avas", "method": "casscf",
             "resolved_engine": "pyscf", "params": {"basis": "cc-pvdz", "n_states": 2}}
    state = {"molecule": WATER,
             "active_space_literature": {"molecule": "water", "notes": "WATER-NOTES",
                                         "matched_at": "molecule"}}
    built, err = _spec_from_draft(draft, WATER, state)
    check("the spec builds", err is None, str(err))
    check("literature_notes is carried in from the search",
          built[0].params.get("literature_notes") == "WATER-NOTES",
          repr(built[0].params.get("literature_notes")))

    other = {"molecule": WATER,
             "active_space_literature": {"molecule": "benzene", "notes": "BENZENE-NOTES",
                                         "matched_at": "molecule"}}
    built2, _ = _spec_from_draft(draft, WATER, other)
    check("another molecule's findings are never carried across",
          built2[0].params.get("literature_notes") is None,
          repr(built2[0].params.get("literature_notes")))


def run_explain() -> None:
    print("\n== explain_active_space reads the space it is given ==")
    # Stubbed rather than left to hit the network: what is under test is
    # the reading of the active space, and a live DuckDuckGo/Semantic
    # Scholar call would make this slow and occasionally red for reasons
    # that have nothing to do with the code.
    real_search = active_space_lit.search
    active_space_lit.search = lambda molecule, n_states=None, basis=None, **kw: (
        active_space_lit.LiteratureFindings(molecule=molecule, matched_at="none",
                                            queries_tried=["stub"], n_states=n_states,
                                            basis=basis))
    try:
        _run_explain_checks()
    finally:
        active_space_lit.search = real_search


def _run_explain_checks() -> None:
    call = lambda **kw: explain_active_space.func(state={"molecule": WATER}, **kw)  # noqa: E731

    full = call(active_electrons=6, active_orbitals=3, n_states=1, basis="sto-3g")
    check("a completely full space is called out as describing no correlation",
          "completely full" in full and "no correlation" in full, full[:400])

    ok = call(active_electrons=4, active_orbitals=4, n_states=2, basis="sto-3g")
    check("a workable space reports its configuration count",
          "many-electron configurations" in ok, ok[:400])
    check("...and confirms it can host the requested roots",
          "enough for the 2" in ok, ok[:400])

    too_small = call(active_electrons=2, active_orbitals=2, n_states=99, basis="sto-3g")
    check("a space too small for the requested roots says so",
          "cannot be run in it" in too_small, too_small[:400])

    check("no molecule means no explanation, rather than a guessed one",
          "No molecule is set" in explain_active_space.func(
              active_electrons=4, active_orbitals=4, state={}))
    check("a malformed space is refused",
          "not a well-formed active space" in call(active_electrons=4, active_orbitals=0))


def main() -> int:
    run_staging()
    run_injection()
    run_explain()
    total = PASS + FAIL
    print(f"\n{PASS}/{total} checks passed")
    if FAIL:
        print(f"[FAIL] {FAIL} check(s) failed")
        return 1
    print("[PASS] ALL CHECKS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
