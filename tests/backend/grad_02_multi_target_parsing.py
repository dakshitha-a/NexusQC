#!/usr/bin/env python3
"""Several states and state pairs per job -- the parts that need no engine.

grad_01 runs the real engines and is slow. This script covers the same
feature's logic in under a second: which drafts are accepted, which are
refused, and whether a multi-target output is taken apart correctly. It is
the one to run while changing any of it; grad_01 is the one that proves the
engines actually agree.

The parser check is the important one. Before it, a coupling job asked for
three state pairs would have come back with three couplings that were all
the LAST gradient block, each carrying the FIRST pair's energy gap -- a
result indistinguishable from a correct one without knowing the numbers in
advance. So the check does not merely confirm three couplings came back: it
builds an output whose sections differ, and asserts each is matched to its
own pair, and asserts that the old behaviour would have produced something
different (so the test cannot pass against the bug it exists for).

Run:  PYTHONPATH=$PWD python3 tests/backend/grad_02_multi_target_parsing.py
"""
from __future__ import annotations

import sys

from app.agent.tools import (
    _input_build_error, _validate_state_pairs, _validate_target_states,
)
from app.chemistry.jobs import bagel_runner as br

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


def _nacme_section(t1: int, t2: int, gap: str, zval: str, osc: str) -> str:
    """One '=== NACME evaluation ===' section, in BAGEL's own layout.

    Copied from a real CAS(2,2)/cc-pvdz ethylene run rather than invented,
    including the 0-based targets, the blank lines and the Z-vector block
    that sits between the header and the gradient.
    """
    return f"""
  === NACME evaluation ===

    * NACME Target states: {t1} - {t2}
    * Energy gap is:       {gap} eV

    * Permanent dipole moment: Transition dipole moment between {t1} - {t2}
           (    0.000000,     0.000000,    -0.000000) a.u.

    * Oscillator strength for transition between {t1} - {t2} {osc} a.u.

  === CASSCF Z-vector iteration ===

         0      0.0010732833     0.0000000000      0.01
    * Permanent dipole moment: Relaxed
           (   -0.000000,    -0.000000,    -0.000000) a.u.

  * Nuclear energy gradient

    o Atom   0
        x         -0.0000000000
        y         -0.0000000000
        z         {zval}
    o Atom   1
        x          0.0000000000
        y         -0.0000000000
        z          0.1817420898
  * Gradient computed with                              0.10
"""


def main() -> int:
    print("== BAGEL multi-pair NACME output is taken apart per pair ==")
    # BAGEL's targets are 0-based, so 0-1 / 0-2 / 1-2 are S0/S1, S0/S2, S1/S2.
    output = (
        "  * METHOD: CASSCF\n"
        + _nacme_section(0, 1, "-5.1111111111", "-0.1111111111", "-0.111111")
        + _nacme_section(0, 2, "-15.1697861980", "-0.2222222222", "-0.222222")
        + _nacme_section(1, 2, "-9.3333333333", "-0.3333333333", "-0.333333")
        + "\n  * METHOD: CASSCF\n"
    )
    sections = br._parse_nacme_sections(output)
    check("every NACME section is found, with its pair read from BAGEL's own announcement",
          [p for p, _ in sections] == [(1, 2), (1, 3), (2, 3)], str([p for p, _ in sections]))

    expected = {
        (1, 2): (-5.1111111111, -0.1111111111, -0.111111),
        (1, 3): (-15.1697861980, -0.2222222222, -0.222222),
        (2, 3): (-9.3333333333, -0.3333333333, -0.333333),
    }
    all_matched = True
    for pair, text in sections:
        want_gap, want_z, want_osc = expected[pair]
        vec = br._parse_atom_vectors(text)
        got_gap = float(br._BAGEL_ENERGY_GAP_EV.search(text).group(1))
        got_osc = float(br._BAGEL_OSC_STRENGTH.search(text).group(1))
        matched = (abs(got_gap - want_gap) < 1e-9 and abs(vec[0][2] - want_z) < 1e-9
                   and abs(got_osc - want_osc) < 1e-9)
        all_matched = all_matched and matched
    check("each pair's vector, energy gap and oscillator strength come from its own section",
          all_matched)

    blocks = br._gradient_sections(output)
    check("the gradient blocks are separated rather than collapsed into one",
          len(blocks) == 3, str(len(blocks)))
    # The specific old failure: the LAST gradient block beside the FIRST
    # energy gap. Asserted so this test cannot pass against the bug.
    old_vector = br._parse_atom_vectors(blocks[-1])
    old_gap = float(br._BAGEL_ENERGY_GAP_EV.search(output).group(1))
    check("the previous last-block/first-match behaviour really would have mismatched them",
          old_vector[0][2] == expected[(2, 3)][1] and old_gap == expected[(1, 2)][0])

    print("\n== which state pairs a draft may ask for ==")
    # n_states counts roots INCLUDING the ground state for casscf and
    # excited states ABOVE it otherwise, so both spell "S0, S1, S2".
    cas, hf = {"n_states": 3}, {"n_states": 2}
    cases = [
        ("all three pairs on a 3-root CASSCF", [[1, 2], [1, 3], [2, 3]], "casscf", cas, None),
        ("the S1/S2 pair of a 3-root CASSCF", [[2, 3]], "casscf", cas, None),
        ("a state above the state average", [[1, 4]], "casscf", cas, "outside"),
        ("the same pair written both ways round", [[1, 2], [2, 1]], "casscf", cas, "same pair twice"),
        ("a state coupled to itself", [[2, 2]], "casscf", cas, "DIFFERENT"),
        ("an empty list", [], "casscf", cas, "non-empty"),
        ("something that is not a pair", [[1, 2, 3]], "casscf", cas, "pair of two"),
        ("a non-integer state index", [[1, 2.0]], "casscf", cas, "whole numbers"),
        ("excited-to-excited on a single-reference method", [[2, 3]], "hf", hf, "ground-to-excited"),
        ("two ground-to-excited pairs on hf", [[1, 2], [1, 3]], "hf", hf, None),
        ("the top state of an hf solve", [[1, 3]], "hf", hf, None),
        ("a state above an hf solve", [[1, 4]], "hf", hf, "outside"),
    ]
    for label, pairs, method, params, want in cases:
        err = _validate_state_pairs(pairs, method, "orca", params)
        check(label, (err is None) if want is None else (err is not None and want in err),
              str(err))

    print("\n== which target states a draft may ask for ==")
    for label, states, method, params, want in [
        ("the ground state alone", [1], "casscf", cas, None),
        ("three states", [1, 2, 3], "casscf", cas, None),
        ("omitted entirely", None, "casscf", cas, None),
        ("the same state twice", [2, 2], "casscf", cas, "more than once"),
        ("a state above the state average", [4], "casscf", cas, "outside"),
        ("state zero", [0], "casscf", cas, "1 or more"),
    ]:
        err = _validate_target_states(states, method, params)
        check(label, (err is None) if want is None else (err is not None and want in err),
              str(err))

    print("\n== a missing required parameter says so ==")
    message = _input_build_error("this job", KeyError("active_electrons"))
    # The bare KeyError message ("...: 'active_electrons'") named a key with
    # no hint that it was required, and a real session read that as the job
    # type being misconfigured.
    check("the message says the parameter is missing, not just its name",
          "needs a 'active_electrons' parameter and the draft has none" in message, message)
    check("a deliberately raised error still reads as itself",
          "Unsupported method" in _input_build_error("this job", ValueError("Unsupported method 'casscf'")))

    print(f"\n{PASS}/{PASS + FAIL} checks passed")
    if FAIL:
        print("[FAIL] some checks failed")
        return 1
    print("[PASS] ALL CHECKS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
