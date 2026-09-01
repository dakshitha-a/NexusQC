#!/usr/bin/env python3
"""Across all three engines: correct, or refused. Never silently narrowed.

A CASSCF gradient batch asking for two excited states routed to PySCF --
which has no CASSCF excited-state gradient at all -- and came back with
thirteen ground-state gradients and nothing anywhere saying the excited
ones had been dropped. Every part of that was individually defensible:
single_point/grad requires only the `gradient` capability, so PySCF is a
legitimate candidate; `target_states` defaulted to the ground state; and
no check fired because none had been asked for. The result was a wrong
answer that looked like a right one.

So this walks the matrix and asserts the only two acceptable outcomes for
each cell: it produces what was asked for, or it refuses with a reason
naming the real obstacle. A cell that "succeeds" while quietly computing
something narrower is a failure here, which is what makes this different
from the per-engine suites in grad_01.

ORCA has no CASSCF NACME (its %casscf block rejects the keyword) and that
is expected -- the matrix asserts the refusal, not the capability.

Run:  PYTHONPATH=$PWD python3 tests/backend/grad_03_engine_matrix.py
"""
from __future__ import annotations

import sys

from app.agent.tools import _build_spec_or_error
from app.chemistry.registry2.capabilities import get_caps
from app.chemistry.registry2.routing import route_engine

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


WATER = {"name": "water", "symbols": ["O", "H", "H"],
         "coords": [[0.0, 0.0, 0.117], [0.0, 0.757, -0.467], [0.0, -0.757, -0.467]],
         "charge": 0, "multiplicity": 1}
CAS = {"active_electrons": 4, "active_orbitals": 4}


def build(task, subtype, engine, method, params):
    out = _build_spec_or_error(task, subtype, WATER, engine, method, dict(params))
    return out[0], out[-1]          # spec, error


def main() -> int:
    print("== an excited-state CASSCF gradient routes to an engine that HAS one ==")
    # The specific misroute: preference order alone hands single_point/grad
    # to PySCF, whose casscf row carries excited_gradient=False.
    decision = route_engine("casscf", "single_point", "grad",
                            params={"target_states": [1, 2, 3]})
    # Asserted as "an engine that has the capability", not as a named
    # engine: which of the survivors wins is the ordinary preference order's
    # business, and naming one here would be the hard-coded-engine mistake
    # _requires_osc_strengths' own comment records having made before.
    from app.chemistry.registry2.capabilities import get_caps as _caps
    routed = decision.engine
    check("routes to an engine that HAS an excited-state CASSCF gradient",
          routed is not None and _caps(routed, "casscf").has("excited_gradient"), str(routed))
    check("does not route to pyscf, which has none", routed != "pyscf", str(routed))
    check("bagel/casscf really does have an excited-state gradient",
          get_caps("bagel", "casscf").has("excited_gradient"))
    check("pyscf/casscf really does not", not get_caps("pyscf", "casscf").has("excited_gradient"))

    # A GROUND-state gradient must not be narrowed away from the ordinary
    # preference order -- target_states=[1] is not an excited request.
    ground = route_engine("casscf", "single_point", "grad", params={"target_states": [1]})
    check("a ground-state gradient still routes by ordinary preference",
          ground.engine == "pyscf", str(ground.engine))

    print("\n== gradients, per engine ==")
    for engine, states, want in [
        ("bagel", [1], "ok"),
        ("bagel", [1, 2, 3], "ok"),          # native forces+grads
        ("pyscf", [1], "ok"),
        ("pyscf", [1, 2, 3], "refuse"),      # no CASSCF excited gradient
        ("orca", [1], "ok"),
        ("orca", [1, 2, 3], "refuse"),       # no CASSCF excited gradient either
    ]:
        spec, err = build("single_point", "grad", engine, "casscf",
                          {"basis": "cc-pvdz", **CAS, "n_states": 3,
                           "n_excited_states": 2, "target_states": states})
        if want == "ok":
            check(f"{engine} casscf gradient on states {states} builds", not err, str(err))
            if spec:
                check(f"{engine} carries the states through to the spec",
                      spec.params.get("target_states") == states,
                      str(spec.params.get("target_states")))
        else:
            check(f"{engine} casscf gradient on states {states} is refused with a reason",
                  bool(err) and "excited-state gradient" in err, str(err))

    print("\n== couplings, per engine ==")
    for engine, want, marker in [
        ("bagel", "ok", ""),
        ("pyscf", "ok", ""),
        ("orca", "refuse", "casscf"),   # %casscf rejects NACME -- a known gap
    ]:
        spec, err = build("single_point", "nac", engine, "casscf",
                          {"basis": "cc-pvdz", **CAS, "n_states": 3, "n_excited_states": 2,
                           "state_pairs": [[1, 2], [1, 3], [2, 3]]})
        if want == "ok":
            check(f"{engine} casscf 3-pair coupling builds", not err, str(err))
            if spec:
                check(f"{engine} carries all three pairs through to the spec",
                      spec.params.get("state_pairs") == [[1, 2], [1, 3], [2, 3]],
                      str(spec.params.get("state_pairs")))
        else:
            check(f"{engine} casscf coupling is refused (documented engine gap)",
                  bool(err), str(err))

    print("\n== single-reference couplings still behave ==")
    spec, err = build("single_point", "nac", "orca", "dft",
                      {"basis": "sto-3g", "functional": "pbe0", "n_states": 3,
                       "n_excited_states": 3, "state_pairs": [[1, 2], [1, 3]]})
    check("orca dft ground-to-excited pairs build", not err, str(err))
    _, err = build("single_point", "nac", "orca", "dft",
                   {"basis": "sto-3g", "functional": "pbe0", "n_states": 3,
                    "n_excited_states": 3, "state_pairs": [[2, 3]]})
    check("orca dft excited-to-excited pair is refused",
          bool(err) and "ground-to-excited" in err, str(err))

    print("\n== a batch child is checked the same way a single job is ==")
    # _build_spec_or_error returns early for a batch, so this check used to
    # be skipped entirely and each child failed in its own runner instead.
    from app.agent.tools import _validate_task_params
    err = _validate_task_params("single_point", "grad", WATER, "casscf", "pyscf",
                                {"target_states": [1, 2, 3], "n_states": 3}, in_batch=True)
    check("a pyscf casscf excited-gradient batch child is refused at draft time",
          bool(err) and "excited-state gradient" in err, str(err))
    err = _validate_task_params("single_point", "grad", WATER, "casscf", "bagel",
                                {"target_states": [1, 2, 3], "n_states": 3}, in_batch=True)
    check("the same child on bagel is allowed", not err, str(err))

    print(f"\n{PASS}/{PASS + FAIL} checks passed")
    if FAIL:
        print("[FAIL] some checks failed")
        return 1
    print("[PASS] ALL CHECKS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
