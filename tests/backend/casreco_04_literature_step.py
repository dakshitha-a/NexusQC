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
in every query at every tier, the narrower tiers rank rather than gate (every
one is issued, and their hits are merged and labelled), and the no-match text
says outright not to substitute an analogue.

The three search backends are injected, so this exercises the staging with
no network call and no seeded knowledge base.

Run:  PYTHONPATH=$PWD python3 tests/backend/casreco_04_literature_step.py
"""
from __future__ import annotations

import sys

from app.agent import active_space_lit
from langgraph.types import Command

from app.agent.tools import (
    _spec_from_draft, explain_active_space, search_active_space_literature,
)

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
          and "3-state" in f.queries_tried[1] and "3-state" not in f.queries_tried[2],
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

    print("\n== every tier runs; the narrower ones rank, they do not gate ==")
    # Stopping at the first tier that returned anything looked right and was
    # wrong: a web backend answers almost any string, so the narrowest query
    # satisfied the search every time and the broader, more productive ones
    # were never issued. Found on uracil, where the narrow query returned a
    # flaky mix of method documentation and unrelated systems while the
    # molecule-only query returned uracil CASSCF papers, one with a
    # CASSCF(10,9).
    full = active_space_lit.search("water", 2, "cc-pvdz",
                                   kb=lambda q: HIT, scholar=_none, web=_none)
    check("the most specific tier that answered is the one reported",
          full.matched_at == "molecule+states+basis", full.matched_at)
    check("...and the broader tiers were issued anyway",
          len(full.queries_tried) == 3, repr(full.queries_tried))

    def per_tier(q: str) -> str:
        if "cc-pvdz" in q:
            return "NARROW hit\nhttps://example.org/n\nCASSCF(2,2)."
        if "state-averaged" in q:
            return "MID hit\nhttps://example.org/m\nCASSCF(4,4)."
        return "BROAD hit\nhttps://example.org/b\nCASSCF(10,9)."

    merged = active_space_lit.search("uracil", 2, "cc-pvdz", kb=_none, scholar=_none,
                                     web=per_tier)
    check("hits from every tier are kept, not just the narrowest",
          len(merged.hits) == 3, repr([src for src, _ in merged.hits]))
    check("...each labelled with the tier that produced it",
          all("molecule" in src for src, _ in merged.hits),
          repr([src for src, _ in merged.hits]))
    check("...and the broad tier's evidence reaches the notes",
          "CASSCF(10,9)" in merged.as_notes(), merged.as_notes()[-300:])

    relaxed = active_space_lit.search(
        "water", 2, "cc-pvdz", kb=_none, scholar=_none,
        web=lambda q: EMPTY if "cc-pvdz" in q else HIT)
    check("a second-tier hit is labelled as having relaxed the basis",
          relaxed.matched_at == "molecule+states", relaxed.matched_at)
    check("...and its notes warn that basis details may differ",
          "may differ" in relaxed.as_notes(), relaxed.as_notes()[:300])
    check("...with the identical broad-tier hit de-duplicated",
          len(relaxed.hits) == 1, repr([src for src, _ in relaxed.hits]))

    # Every backend does keyword retrieval, so "returned results" is the
    # most the notes may claim. The first live run came back at the
    # narrowest tier with an ORCA manual page and a paper about DNA base
    # pairs; saying that "matched on the molecule" would be the same
    # overstatement this module exists to prevent, one level up.
    notes = full.as_notes()
    check("a hit is described as a query returning results, not as a match",
          "returned results" in notes and "matched on the molecule" not in notes,
          notes[:300])
    check("...and the reader is told to judge relevance",
          "Read these before relying on them" in notes, notes[:400])
    check("...including that irrelevant hits are the same finding as none",
          "same finding as an empty search" in notes, notes[:500])

    loosest = active_space_lit.search(
        "water", 2, "cc-pvdz", kb=_none, scholar=_none,
        # Only the broadest tier lacks the "2-state" term, so this stub
        # answers there and nowhere else.
        web=lambda q: EMPTY if "2-state" in q else HIT)
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


def run_tool_contract() -> None:
    """Invoke through the real tool interface, not the underlying function.

    Every other check here calls `.func(...)` directly, which skips
    pydantic validation of the tool's own signature -- and that is exactly
    where the first live run of this flow failed. `tool_call_id` had been
    annotated `Annotated[InjectedToolCallId, InjectedToolCallId]`, making
    the marker class the field's TYPE rather than its metadata, so every
    call was rejected with "Input should be an instance of
    InjectedToolCallId" before the body ever ran. The correct form is
    `Annotated[str, InjectedToolCallId]`, which is what the rest of the
    module already used.
    """
    print("\n== the tools can actually be invoked, injections and all ==")
    real_search = active_space_lit.search
    active_space_lit.search = lambda molecule, n_states=None, basis=None, **kw: (
        active_space_lit.LiteratureFindings(molecule=molecule, matched_at="none",
                                            queries_tried=["stub"], n_states=n_states,
                                            basis=basis))
    try:
        result = search_active_space_literature.invoke({
            "name": "search_active_space_literature",
            # molecule passed explicitly: a bare .invoke() has no ToolNode
            # to supply the InjectedState the tool would otherwise read it
            # from, and the molecule is not what is under test here.
            "args": {"n_excited_states": 2, "basis": "cc-pvdz", "molecule": "water"},
            "id": "call-1",
            "type": "tool_call",
        }, config={"configurable": {}})
        check("search_active_space_literature invokes without a validation error",
              isinstance(result, Command), repr(result)[:200])
        messages = (getattr(result, "update", None) or {}).get("messages") or []
        check("...and returns a ToolMessage carrying the findings",
              bool(messages) and "Literature search" in messages[0].content,
              repr(messages)[:200])

        # The capability line, which nothing asserted until 2026-09-04.
        #
        # The tool builds it by asking the registry about each cas_reco
        # subtype it knows, and it knew `autocas` and `avas` -- both retired
        # with the legacy engine. `capability_answer` returned an unsupported
        # answer for each, the options list came back empty, and the tool
        # emitted "This deployment cannot run an active-space recommendation
        # job" on every call, while cas_reco and cas_reco/refine were both
        # supported and running. The agent relayed that to users.
        #
        # This is the failure `casreco_01`'s own docstring is about -- an
        # agent telling a user a shipped feature does not exist -- reappearing
        # one layer up, in a caller that names subtypes rather than in the
        # registry it asks. So the assertion is on the SUBSTANCE of the line
        # and not on its wording: it must name a subtype the registry actually
        # supports, and it must not be the refusal.
        body = messages[0].content if messages else ""
        check("the capability line does not tell the user the deployment "
              "cannot recommend an active space",
              "cannot run an active-space recommendation" not in body,
              body[:300])
        from app.chemistry.registry2.lookup import capability_answer
        live = [capability_answer("cas_reco", s) for s in ("", "refine")]
        labels = [a["label"] for a in live if a.get("supported")]
        check(f"...and names every cas_reco subtype the registry supports "
              f"({', '.join(labels) or 'none'})",
              bool(labels) and all(lbl in body for lbl in labels),
              f"labels {labels} against {body[:300]}")
    except Exception as exc:  # noqa: BLE001
        check("search_active_space_literature invokes without a validation error", False,
              f"{type(exc).__name__}: {exc}")
    finally:
        active_space_lit.search = real_search


def run_injection() -> None:
    print("\n== findings ride into the job, and only for their own molecule ==")
    draft = {"task": "cas_reco", "subtype": "", "method": "casscf",
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

    # These count EXCITED states now; the tool adds the ground-state root
    # itself, so n_excited_states=1 is the two-root average it used to mean.
    full = call(active_electrons=6, active_orbitals=3, n_excited_states=0, basis="sto-3g")
    check("a completely full space is called out as describing no correlation",
          "completely full" in full and "no correlation" in full, full[:400])

    ok = call(active_electrons=4, active_orbitals=4, n_excited_states=1, basis="sto-3g")
    check("a workable space reports its configuration count",
          "many-electron configurations" in ok, ok[:400])
    check("...and confirms it can host the requested roots",
          "enough for the 2" in ok, ok[:400])

    too_small = call(active_electrons=2, active_orbitals=2, n_excited_states=98, basis="sto-3g")
    check("a space too small for the requested roots says so",
          "cannot be run in it" in too_small, too_small[:400])

    check("no molecule means no explanation, rather than a guessed one",
          "No molecule is set" in explain_active_space.func(
              active_electrons=4, active_orbitals=4, state={}))
    check("a malformed space is refused",
          "not a well-formed active space" in call(active_electrons=4, active_orbitals=0))


def run_cost_shape() -> None:
    """What the search is allowed to COST, asserted as behaviour.

    The step was nearly dropped on 2026-09-04 for eating more context than it
    earned, and was kept because its value is the empty outcome: it exists so
    "no published space for this molecule" is reportable, which is what stops
    the model substituting a space from a similar compound (see this module's
    header). Keeping it meant paying down the cost instead, and these are the
    three things that did it. They are behaviour, not style, so they are
    asserted rather than left to a comment someone may later tidy away.
    """
    print("\n== what the search costs ==")
    calls = {"kb": 0, "scholar": 0, "web": 0}

    def counting(name, answer):
        def fn(_q):
            calls[name] += 1
            return answer
        return fn

    # 1. A hit in the user's own uploaded papers at the NARROWEST tier means
    #    all three terms matched, so the network backend is not asked at all.
    calls.update(kb=0, scholar=0, web=0)
    active_space_lit.search("uracil", n_states=4, basis="cc-pvdz",
               kb=counting("kb", "Uploaded paper: uracil CASSCF(14,10) cc-pVDZ."),
               scholar=counting("scholar", "must not be called"))
    check("a local hit at the narrowest tier skips the network entirely",
          calls["scholar"] == 0, f"scholar called {calls['scholar']} time(s)")

    # 2. A hit only at a BROADER tier must NOT skip it. The narrow query
    #    matching is what carries the information; matching only after the
    #    basis and state count were dropped does not.
    calls.update(kb=0, scholar=0, web=0)
    seen = {"n": 0}

    def kb_broad_only(_q):
        calls["kb"] += 1
        seen["n"] += 1
        return ("No matching passages found" if seen["n"] < 3
                else "Uploaded paper: uracil active space.")

    active_space_lit.search("uracil", n_states=4, basis="cc-pvdz", kb=kb_broad_only,
               scholar=counting("scholar", "Semantic Scholar: uracil CASSCF."))
    check("a local hit only at the broad tier still runs the network",
          calls["scholar"] == 3, f"scholar called {calls['scholar']} time(s)")

    # 3. The open web is no longer built. Its own tier comment records why it
    #    is the noise source: it returns something for almost any string, so
    #    its hits carry the least information per token of the three backends,
    #    and it was being asked once per tier.
    calls.update(kb=0, scholar=0, web=0)
    findings = active_space_lit.search("nonesuchium",
                          kb=counting("kb", "No matching passages found"),
                          scholar=counting("scholar", "No matching papers found"))
    check("the open-web backend is not built by default",
          calls["web"] == 0, f"web called {calls['web']} time(s)")

    # 4. The empty note stops riding into the job chain as prose. The full
    #    text still exists and is what the model sees at search time, when it
    #    is about to propose a space; the job carries the short form.
    full, short = findings.as_notes(), findings.as_job_note()
    check("the not-found guardrail is still in the full note",
          "do not substitute" in full, full[:200])
    check(f"...and the job-borne form is short ({len(short.split())} words "
          f"against {len(full.split())})",
          len(short.split()) < 20, short)
    found = active_space_lit.search("uracil", n_states=4, basis="cc-pvdz",
                       kb=counting("kb", "Uploaded paper: uracil CASSCF(14,10)."),
                       scholar=counting("scholar", "unused"))
    check("a FOUND note is not shortened, since its content is the finding",
          found.as_job_note() == found.as_notes())


def main() -> int:
    run_staging()
    run_tool_contract()
    run_injection()
    run_explain()
    run_cost_shape()
    total = PASS + FAIL
    print(f"\n{PASS}/{total} checks passed")
    if FAIL:
        print(f"[FAIL] {FAIL} check(s) failed")
        return 1
    print("[PASS] ALL CHECKS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
