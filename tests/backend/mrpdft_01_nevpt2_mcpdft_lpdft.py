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
from app.chemistry.registry2.params import MULTIREF_METHODS, ONTOP_METHODS
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
    run_live_single_points()
    print(f"\n{PASS} passed, {FAIL} failed")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
