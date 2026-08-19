#!/usr/bin/env python3
"""A malformed scan draft must produce a sentence, never an exception.

Both `pes_scan` cells in the e2e job matrix called submit_draft and got no
approval card. The cause was not the model and not the taxonomy: the
geometry builder indexes and does arithmetic on whatever shape the draft
carries, so anything unexpected surfaced as TypeError, KeyError or
OverflowError -- and an exception raised inside submit_draft escapes it
entirely. No card, no explanation, a traceback where an answer belonged.

Every shape below is one a model produced or plausibly would when asked to
"scan the O-H bond between atoms 1 and 2 from 0.8 to 1.4 angstroms". The
contract asserted here is narrow and absolute: **the tool answers**. A
wrong shape gets a sentence naming what is wrong; a merely sloppy one gets
absorbed.

The 0-based case is called out by name. This app's atom numbering is
1-based everywhere a user or a model can see it (CLAUDE.md) -- RDKit's
0-based indices are converted at that boundary and never leak outward --
so a model reaching for 0 is a predictable slip and deserves to be told
which convention it just broke, rather than an OverflowError from deep
inside a geometry routine.

Run:  PYTHONPATH=$PWD python3 tests/backend/scan_01_draft_shapes.py
"""
from __future__ import annotations

import sys

from app.agent.tools import _spec_from_draft
from app.chemistry.molecule import resolve_molecule
from app.chemistry.registry2.elicitation import validate_draft

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


WATER = resolve_molecule("water").to_dict()
STATE = {"molecule": WATER}


def build(extra: dict):
    """(spec, error_text) for a pes_1d draft carrying `extra`. Never raises
    -- that is the whole point."""
    draft = {"task": "pes_1d", "subtype": "", "method": "hf", "engine": "pyscf",
             "params": {"basis": "sto-3g", **extra}}
    verdict = validate_draft(draft, STATE)
    if verdict.status != "ready":
        return None, f"draft {verdict.status}: {verdict.ask_user_exactly}"
    built, error = _spec_from_draft(verdict.draft, WATER, STATE)
    if error:
        return None, error
    spec, _preview, _kb, _notes, _scan, _kw, _warn, build_error = built
    return (None, build_error) if build_error else (spec, None)


GOOD = {"coordinate": {"type": "bond", "atoms": [1, 2]}, "scan_range": [0.8, 1.4],
        "n_points": 5}


def main() -> int:
    print("== a well-formed scan reaches a spec ==")
    spec, error = build(dict(GOOD))
    check("the canonical shape builds", spec is not None, str(error))
    check("and is a scan master", spec is not None and spec.method == "pes_scan",
          f"method={getattr(spec, 'method', None)!r}")

    print("\n== a sloppy but unambiguous shape is absorbed ==")
    spec, error = build(dict(GOOD, coordinate={"type": "bond", "atoms": ["1", "2"]}))
    check("atom numbers written as strings are coerced, not refused",
          spec is not None, str(error))

    print("\n== a wrong shape is explained, never raised ==")
    cases = [
        ("a coordinate written as free text",
         {"coordinate": "bond 1 2"}, "must be an object"),
        ("a coordinate with no atoms list",
         {"coordinate": {"type": "bond", "atom1": 1, "atom2": 2}}, "must be a list"),
        ("a range given as an object",
         {"scan_range": {"start": 0.8, "stop": 1.4}}, "[start, stop]"),
        ("a coordinate type this app does not scan",
         {"coordinate": {"type": "improper", "atoms": [1, 2, 3, 4]}}, "bond, angle or dihedral"),
        ("too few atoms for the coordinate type",
         {"coordinate": {"type": "angle", "atoms": [1, 2]}}, "exactly 3 atom numbers"),
        ("an atom number past the end of the molecule",
         {"coordinate": {"type": "bond", "atoms": [1, 9]}}, "does not exist"),
    ]
    for label, extra, fragment in cases:
        spec, error = build(dict(GOOD, **extra))
        check(f"{label} is refused with a reason",
              spec is None and error is not None and fragment in error,
              f"error={error!r}")

    print("\n== 0-based atom numbers are named as the mistake they are ==")
    spec, error = build(dict(GOOD, coordinate={"type": "bond", "atoms": [0, 1]}))
    check("a 0-based index is refused", spec is None, "it built anyway")
    check("and the message says the numbering is 1-based",
          error is not None and "1-based" in error, f"error={error!r}")
    check("without leaking an OverflowError from the geometry code",
          error is not None and "OverflowError" not in error, f"error={error!r}")

    print("\n== nothing in this path raises ==")
    # The load-bearing negative. An exception inside submit_draft means no
    # approval card at all, which is how this class of bug hid: the model
    # was blamed for not submitting when the submit had actually been
    # refused by a crash.
    raised = []
    for label, extra, _ in cases:
        try:
            build(dict(GOOD, **extra))
        except Exception as exc:
            raised.append(f"{label}: {type(exc).__name__}")
    for label, extra in (("junk coordinate", {"coordinate": 42}),
                         ("null range", {"scan_range": None}),
                         ("range of one", {"scan_range": [0.8]}),
                         ("atoms as a bare int", {"coordinate": {"type": "bond", "atoms": 1}})):
        try:
            build(dict(GOOD, **extra))
        except Exception as exc:
            raised.append(f"{label}: {type(exc).__name__}")
    check("no shape raises out of the build path", not raised, f"raised: {raised}")

    total = PASS + FAIL
    print(f"\n{PASS}/{total} checks passed")
    if FAIL:
        print(f"[FAIL] {FAIL} check(s) failed")
        return 1
    print("[PASS] ALL CHECKS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
