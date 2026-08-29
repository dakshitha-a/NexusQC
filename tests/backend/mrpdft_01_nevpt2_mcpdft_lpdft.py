#!/usr/bin/env python3
"""NEVPT2, MC-PDFT and L-PDFT: what is offered, what is refused, and why.

The interesting content of this feature is not that three methods were
added. It is the shape of what each one can and cannot do, which was
established by real runs on this host (`scripts/spikes/spike_pyscf_caps.py`)
and then encoded as capability cells that everything else derives from:

- NEVPT2 gives energies and excited states and nothing else, because
  `pyscf.mrpt` exposes no gradient. Optimization and frequencies must be
  refused with that reason, not attempted.
- MC-PDFT and L-PDFT have analytic gradients for ground and excited states
  and non-adiabatic couplings, so the whole single-point family plus
  optimization, frequencies and opt+freq are available.
- **None of the three can produce oscillator strengths.** PySCF implements
  transition dipoles for the CMS-PDFT variant only. A nuclear-ensemble
  spectrum must therefore be refused up front, naming that gap, rather
  than running an entire ensemble and discovering at pooling time that
  there is nothing to convolve. That failure mode is exactly what
  `wigner_spectra`'s `requires=("excited", "osc_strengths")` exists to
  prevent, and this script checks the refusal says so.

Two live single-point runs are included, on water/STO-3G/CAS(4,4), because
a registry that says "supported" while the runner raises is the failure
this app's evidence rule is meant to make impossible. They are seconds of
compute.

**No jobs and no threads are created**: this drives the registry and the
runners directly rather than submitting through JobManager, so there is
nothing for it to clean up afterwards.

Run:  PYTHONPATH=$PWD python3 tests/backend/mrpdft_01_nevpt2_mcpdft_lpdft.py
"""
from __future__ import annotations

import sys
import tempfile
import traceback

from app.chemistry.registry2 import route_engine, supports
from app.chemistry.registry2.capabilities import CAPABILITIES, get_caps
from app.chemistry.registry2.params import (
    MULTIREF_METHODS, ONTOP_METHODS, PARAMS_BY_NAME, missing_required,
)
from app.chemistry.jobs.dispatch import resolve_runner
from app.chemistry.jobs.naming import auto_job_name

PASS = 0
FAIL = 0

WATER = {
    "name": "water", "symbols": ["O", "H", "H"],
    "coords": [[0, 0, 0.117], [0, 0.757, -0.467], [0, -0.757, -0.467]],
    "charge": 0, "multiplicity": 1,
}

NEW_METHODS = ("nevpt2", "mcpdft", "lpdft")


def check(label: str, ok: bool, detail: str = "") -> None:
    global PASS, FAIL
    if ok:
        PASS += 1
        print(f"  [PASS] {label}")
    else:
        FAIL += 1
        print(f"  [FAIL] {label}" + (f"\n         {detail}" if detail else ""))


def _undefined_names(script: str) -> set[str]:
    """Names a generated preview reads without ever binding.

    A preview is a script we tell the reader is equivalent to what runs, so
    a name that is never assigned is a real defect rather than a cosmetic
    one -- valid Python to read and a `NameError` to run. Written against
    the AST rather than by grepping, because the thing that made this worth
    checking (`thermo.thermo(state_model, ...)` with no `state_model`
    anywhere) reads perfectly naturally.

    Deliberately approximate in the safe direction: comprehension and
    lambda variables are collected as bindings without tracking their
    scope, so this under-reports rather than crying wolf on a preview that
    is fine.
    """
    import ast
    import builtins

    tree = ast.parse(script)
    bound: set[str] = set(dir(builtins))
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and isinstance(node.ctx, (ast.Store, ast.Del)):
            bound.add(node.id)
        elif isinstance(node, ast.alias):
            bound.add((node.asname or node.name).split(".")[0])
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            bound.add(node.name)
        elif isinstance(node, ast.arg):
            bound.add(node.arg)
    return {n.id for n in ast.walk(tree)
            if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Load)} - bound


def run_capability_shape() -> None:
    print("\n== each method is offered exactly what this host verified ==")
    for method in NEW_METHODS:
        check(f"{method} has a PySCF capability row", ("pyscf", method) in CAPABILITIES)

    energy_only = ("single_point", "gs"), ("single_point", "ee")
    for task, subtype in energy_only:
        for method in NEW_METHODS:
            v = supports("pyscf", method, task, subtype)
            check(f"{method} {task}/{subtype} is offered", v.supported,
                  "; ".join(v.reasons))

    print("\n== NEVPT2 is energy-only, and says why ==")
    for task, subtype in (("opt", "min"), ("freq", ""), ("single_point", "grad")):
        v = supports("pyscf", "nevpt2", task, subtype)
        name = f"{task}/{subtype}" if subtype else task
        check(f"nevpt2 {name} is refused", not v.supported)
        check(f"nevpt2 {name} refusal names the missing derivative",
              any("gradient" in r or "hessian" in r for r in v.reasons),
              f"reasons={list(v.reasons)}")

    print("\n== the two pair-density methods get the derivative-driven tasks ==")
    for method in ("mcpdft", "lpdft"):
        for task, subtype in (("single_point", "grad"), ("single_point", "nac"),
                              ("opt", "min"), ("opt", "constrained"),
                              ("freq", ""), ("opt_freq", "")):
            v = supports("pyscf", method, task, subtype)
            name = f"{task}/{subtype}" if subtype else task
            check(f"{method} {name} is offered", v.supported, "; ".join(v.reasons))


def run_no_intensities() -> None:
    print("\n== no oscillator strengths, so no nuclear-ensemble spectrum ==")
    for method in NEW_METHODS:
        caps = get_caps("pyscf", method)
        check(f"{method} does not claim osc_strengths", not caps.has("osc_strengths"))

        v = supports("pyscf", method, "wigner_spectra")
        check(f"{method} wigner_spectra is refused", not v.supported)
        # The point of the refusal is that it is specific. "No engine can
        # run this" would be true and useless; the user needs to know it is
        # the intensities that are missing, since the excitation energies
        # themselves are perfectly available.
        check(f"{method} wigner refusal names the intensities, not just a failure",
              any("osc_strengths" in r for r in v.reasons),
              f"reasons={list(v.reasons)}")

        # And no other engine quietly picks the job up instead. These
        # methods exist on PySCF only, so there is nothing to fall back to.
        decision = route_engine(method, "wigner_spectra")
        check(f"{method} wigner routes nowhere rather than to another engine",
              decision.engine is None, f"routed to {decision.engine}")


def run_wiring() -> None:
    print("\n== the plumbing agrees with the registry ==")
    for method in NEW_METHODS:
        check(f"{method} is in the multireference set (needs an active space)",
              method in MULTIREF_METHODS)
    for method in ("mcpdft", "lpdft"):
        check(f"{method} is in the on-top set (needs an on-top functional)",
              method in ONTOP_METHODS)
    check("nevpt2 takes no on-top functional", "nevpt2" not in ONTOP_METHODS)

    print("\n== single-point dispatch reaches each method's own runner ==")
    # Getting this wrong is the specific silent failure dispatch.py's own
    # docstring warns about: falling through to the CASSCF runner would run
    # a CASSCF energy for an MC-PDFT request and report it as one.
    for method in NEW_METHODS:
        for subtype in ("gs", "ee"):
            key, err = resolve_runner("single_point", subtype, method)
            check(f"{method} single_point/{subtype} -> '{method}' runner",
                  key == method, f"got {key!r}, err={err!r}")

    print("\n== names are written the way a chemist writes them ==")
    for method, want in (("nevpt2", "NEVPT2"), ("mcpdft", "MC-PDFT"), ("lpdft", "L-PDFT")):
        name = auto_job_name({
            "task": "single_point", "subtype": "gs", "method": method,
            "molecule": WATER, "params": {"active_electrons": 4, "active_orbitals": 4},
        })
        check(f"{method} appears as {want} in a job name", want in name, f"name={name!r}")


def run_lpdft_needs_a_state_count() -> None:
    """The regression this section exists for, found by review.

    L-PDFT is multi-state by construction, so `n_excited_states` is required
    for every L-PDFT task and not only the excited-state ones. It was not,
    at first: `n_excited_states` only *applied* to the excited-state family,
    and `required_when` is never consulted for a parameter that does not
    apply, so the `{"eq": ["method", "lpdft"]}` clause was dead code for
    `single_point/gs`, `opt`, `freq` and `opt_freq`. Those drafts reached
    READY with no state count and the job then died after approval on
    "L-PDFT needs at least two states" -- the worst place to fail, since the
    user has already approved it.

    The live runs did not catch this because every one of them passed a
    state count explicitly.
    """
    print("\n== L-PDFT asks for a state count on every task, not just excited ones ==")
    spec = PARAMS_BY_NAME["n_excited_states"]
    params = {"basis": "sto-3g", "active_electrons": 4, "active_orbitals": 4,
              "ot_functional": "tPBE"}
    for task, subtype in (("single_point", "gs"), ("opt", "min"), ("freq", ""),
                          ("opt_freq", ""), ("single_point", "ee")):
        name = f"{task}/{subtype}" if subtype else task
        missing = [s.name for s in missing_required(task, subtype, "lpdft", "pyscf", params)]
        check(f"lpdft {name} is incomplete without a state count",
              "n_excited_states" in missing, f"missing={missing}")

    print("\n== and nothing else grew a state count it should not have ==")
    # The widening that made the above work is on `applies_to`, which is
    # blunt; `applies_when` is what keeps it off everything else. Getting
    # that wrong would put "Number of excited states" on the approval card
    # of every ground-state single point and every plain HF optimization.
    for method, task, subtype in (("hf", "opt", "min"), ("dft", "freq", ""),
                                  ("casscf", "single_point", "gs"),
                                  ("mcpdft", "single_point", "gs"),
                                  ("mcpdft", "opt", "min"),
                                  ("nevpt2", "single_point", "gs")):
        ctx = {"method": method, "task": task, "subtype": subtype, "engine": "pyscf"}
        name = f"{task}/{subtype}" if subtype else task
        check(f"{method} {name} does not ask for a state count",
              not spec.is_active(ctx))

    print("\n== the contexts that always asked for one still do ==")
    for method, task, subtype in (("dft", "single_point", "ee"),
                                  ("casscf", "single_point", "nac"),
                                  ("dft", "opt", "ci"),
                                  ("dft", "wigner_spectra", ""),
                                  ("casscf", "cas_reco", "autocas"),
                                  ("casscf", "cas_reco", "avas"),
                                  # A fresh scan draft still has subtype "",
                                  # and the count is what elicitation
                                  # promotes it to an excited-state scan ON.
                                  ("dft", "pes_1d", ""),
                                  ("dft", "interp_pes", "")):
        ctx = {"method": method, "task": task, "subtype": subtype, "engine": "pyscf"}
        name = f"{task}/{subtype}" if subtype else task
        check(f"{method} {name} still asks for a state count", spec.is_active(ctx))


def run_previews() -> None:
    """Every approval-card preview renders, and says the thing that makes
    the calculation what it is.

    These are checked because a preview is what the user approves against,
    and because the whole family was written without being executed once.
    Doing that afterwards found a `thermo.thermo(state_model, ...)` line
    referring to a name the generated script never defined -- valid Python
    to read, a `NameError` to run.
    """
    print("\n== approval-card previews render and name what they do ==")
    from app.chemistry.jobs.pyscf_runner import build_input_preview

    base = {"basis": "sto-3g", "active_orbitals": 4, "active_electrons": 4}
    pd = {**base, "ot_functional": "tPBE"}
    cases = (
        ("nevpt2 energy", "nevpt2", {**base, "method": "nevpt2", "n_states": 1},
         ("mrpt.NEVPT",)),
        # The CASCI step is the non-obvious part of the excited path, so the
        # preview has to show it rather than imply a state average works.
        ("nevpt2 excited", "nevpt2", {**base, "method": "nevpt2", "n_states": 3},
         ("mrpt.NEVPT", "CASCI", "nroots")),
        ("mcpdft energy", "mcpdft", {**pd, "method": "mcpdft", "n_states": 1},
         ("mcpdft.CASSCF", "tPBE")),
        ("lpdft energy", "lpdft", {**pd, "method": "lpdft", "n_states": 2},
         ("multi_state", "LIN")),
        # The scanner, not the object: handing geomeTRIC the object raises
        # NotImplementedError, so a preview showing that would be wrong.
        ("lpdft optimization", "geometry_optimization",
         {**pd, "method": "lpdft", "n_states": 2, "target_state": 1},
         ("as_scanner(state=1)", "optimize(scanner")),
        ("mcpdft frequency", "frequency", {**pd, "method": "mcpdft", "n_states": 1},
         ("_numerical_casscf_hessian", "state_model = ")),
        ("mcpdft nac", "nac",
         {**pd, "method": "mcpdft", "n_states": 2, "state_pairs": [[1, 2]]},
         ("nac_method",)),
    )
    for label, job_type, params, needles in cases:
        try:
            text = build_input_preview(job_type, WATER, params)
        except Exception as exc:  # noqa: BLE001 -- reporting, not handling
            check(f"{label} preview renders", False, f"{type(exc).__name__}: {exc}")
            continue
        for needle in needles:
            check(f"{label} preview shows {needle!r}", needle in text)
        undefined = _undefined_names(text)
        check(f"{label} preview uses only names it defines", not undefined,
              f"undefined: {sorted(undefined)}")


def run_live_single_points() -> None:
    print("\n== the runners actually produce what the registry promises ==")
    from app.chemistry.jobs import pyscf_runner

    base = {"basis": "sto-3g", "active_orbitals": 4, "active_electrons": 4}
    cases = (
        ("nevpt2 ground state", pyscf_runner.run_nevpt2,
         {**base, "method": "nevpt2", "n_states": 1}, "nevpt2_energy_hartree"),
        ("mcpdft ground state", pyscf_runner.run_mcpdft,
         {**base, "method": "mcpdft", "ot_functional": "tPBE", "n_states": 1},
         "mcpdft_energy_hartree"),
        ("lpdft two states", pyscf_runner.run_lpdft,
         {**base, "method": "lpdft", "ot_functional": "tPBE", "n_states": 2},
         "state_energies_hartree"),
    )
    for label, fn, params, key in cases:
        params = dict(params)
        params["_job_dir"] = tempfile.mkdtemp()
        try:
            summary = fn(WATER, params)["summary"]
        except Exception as exc:  # noqa: BLE001 -- reporting, not handling
            check(label, False, f"{type(exc).__name__}: {exc}")
            if "-v" in sys.argv:
                traceback.print_exc()
            continue
        check(f"{label} returned {key}", summary.get(key) is not None,
              f"summary keys: {sorted(summary)}")
        # Every one of these ends on a converged CASSCF-like object, so the
        # orbital table comes along for free and the job is lazily
        # orbital-visualizable. An empty table means the molden export
        # silently degraded.
        check(f"{label} carries an orbital table",
              bool(summary.get("orbital_table")))
        # The thing that must never appear: an intensity nobody can compute.
        check(f"{label} reports no oscillator strengths",
              not summary.get("oscillator_strengths"))

    # L-PDFT is multi-state by construction, and a one-root request is not a
    # cheaper L-PDFT, it is not one. Refused in the builder rather than left
    # to fail somewhere less legible.
    params = {**base, "method": "lpdft", "ot_functional": "tPBE", "n_states": 1,
              "_job_dir": tempfile.mkdtemp()}
    try:
        pyscf_runner.run_lpdft(WATER, params)
        check("lpdft with one state is refused", False, "it ran instead")
    except ValueError as exc:
        check("lpdft with one state is refused", "at least two states" in str(exc),
              f"message was: {exc}")


def main() -> int:
    print("NEVPT2 / MC-PDFT / L-PDFT capability and runner checks")
    run_capability_shape()
    run_no_intensities()
    run_wiring()
    run_lpdft_needs_a_state_count()
    run_previews()
    run_live_single_points()
    print(f"\n{PASS} passed, {FAIL} failed")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
