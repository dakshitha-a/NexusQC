#!/usr/bin/env python3
"""A nuclear-ensemble spectrum needs intensities, so the task requires them.

    PYTHONPATH=$PWD python3 tests/backend/wig_01_oscillator_strength_requirement.py

The spectrum a `wigner_spectra` job produces is a Gaussian convolution of
every sampled transition weighted by its oscillator strength. Without
intensities there is nothing to convolve, and the master job runs the whole
ensemble before ending on "No sample contributed a usable (energy,
oscillator strength) pair to pool".

The task used to declare `requires=("excited",)` and merely warn when an
engine reported no intensities. That warning was on the wrong side of the
decision: `route_engine` picks from `engines_supporting`, PySCF is first in
preference order, and PySCF is excited-capable for both CASSCF and EOM-CCSD
while supplying transition dipoles for neither. So a CASSCF or EOM-CCSD
ensemble was routed to PySCF and pooled nothing, after however long the
samples took.

`requires=("excited", "osc_strengths")` is the whole fix. Nothing in
`routing.py` learned about this task; the derivation already picks from
whatever `supports()` allows, so the two methods move to ORCA on their own.

Checks, in order:

1. The capability layer refuses the two (engine, method) pairs that have no
   trusted oscillator-strength evidence, and names the specific gap.
2. Routing sends each method to an engine that can actually supply them.
3. The builder forces `want_oscillator_strengths` on for every method, not
   just the two that need the flag to change the input file.
4. The builder refuses outright if it is somehow handed an engine that
   cannot supply intensities, rather than building a job that cannot
   produce its own artifact.

Needs only the qc-agent environment; no server, no engines.
"""
from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO))

# `app.config.JOBS_DIR` is a hardcoded `PROJECT_ROOT / "data" / "jobs"`; it
# reads no environment variable at all, and `./data` is bind-mounted into the
# running stack by docker-compose.yml. So a fixture job written here lands in
# the LIVE job store, where an unowned job is deliberately visible to every
# user. Both this script and reg_01_wigner_prep.py used to set
# `QC_AGENT_JOBS_DIR` to a temp directory and believe that redirected it,
# which is why `srcfreq00001` sat in everyone's job list. The fixture is
# removed in a `finally` instead -- see `main`.

from app.agent.tools import _build_ensemble_spec_or_error  # noqa: E402
from app.chemistry.registry2.routing import route_engine  # noqa: E402
from app.chemistry.registry2.tasks import get_task, supports  # noqa: E402
from app.config import JOBS_DIR  # noqa: E402

WATER = {
    "name": "water",
    "symbols": ["O", "H", "H"],
    "coords": [[0.0, 0.0, 0.117], [0.0, 0.757, -0.467], [0.0, -0.757, -0.467]],
    "charge": 0,
    "multiplicity": 1,
}

NORMAL_MODES = [
    [[0.0, 0.0, -0.07], [0.0, 0.43, 0.55], [0.0, -0.43, 0.55]],
    [[0.0, 0.0, 0.05], [0.0, 0.58, -0.40], [0.0, -0.58, -0.40]],
    [[0.0, 0.07, 0.0], [0.0, -0.55, 0.43], [0.0, -0.55, -0.43]],
]


FIXTURE_JOB_ID = "testfixture-wig01-freq"


def write_source_job(job_id: str = FIXTURE_JOB_ID) -> str:
    d = Path(JOBS_DIR) / job_id
    d.mkdir(parents=True, exist_ok=True)
    (d / "spec.json").write_text(json.dumps({
        "job_id": job_id, "task": "freq", "subtype": "", "method": "hf", "engine": "pyscf",
        "molecule": WATER, "params": {"basis": "sto-3g"},
    }))
    (d / "status.json").write_text(json.dumps({"status": "completed", "detail": ""}))
    (d / "result.json").write_text(json.dumps({
        "job_id": job_id, "status": "completed",
        "summary": {
            "frequencies_cm-1": [1580.2, 3650.1, 3755.9],
            "imaginary_flags": [False, False, False],
            "n_imaginary_frequencies": 0,
            "normal_modes": NORMAL_MODES,
            "reduced_mass_amu": [1.08, 1.05, 1.08],
        },
        "artifacts": {},
    }))
    return job_id


# (method, engine that must be chosen when the user names none, why)
ROUTING_EXPECTATIONS = [
    ("dft", "pyscf", "TDDFT reports intensities on PySCF, so preference order stands"),
    ("hf", "pyscf", "TD-HF likewise"),
    ("casscf", "orca", "PySCF exposes no CASSCF transition dipoles, so first place moves on"),
    ("eom_ccsd", "orca", "PySCF's EOMEESinglet exposes no transition dipoles"),
    ("caspt2", "bagel", "CASPT2 is BAGEL-only here, and BAGEL supplies intensities for it"),
]

# (engine, method) pairs that are excited-capable but supply no intensities.
NO_INTENSITY_PAIRS = [("pyscf", "casscf"), ("pyscf", "eom_ccsd")]

BASE_PARAMS = {
    "n_samples": 4,
    "basis": "sto-3g",
    "n_states": 3,
    "functional": "b3lyp",
    "active_electrons": 4,
    "active_orbitals": 4,
}


def main() -> int:
    try:
        return _run()
    finally:
        shutil.rmtree(Path(JOBS_DIR) / FIXTURE_JOB_ID, ignore_errors=True)


def _run() -> int:
    src = write_source_job()
    failures = 0

    def check(label: str, ok: bool, detail: str = "") -> None:
        nonlocal failures
        print(f"[{'PASS' if ok else 'FAIL'}] {label}{(' -- ' + detail) if detail else ''}")
        if not ok:
            failures += 1

    # -- 1. The requirement itself ------------------------------------
    tdef = get_task("wigner_spectra", "")
    check("wigner_spectra requires oscillator strengths, not only excitation energies",
          tdef is not None and "osc_strengths" in tdef.requires,
          str(getattr(tdef, "requires", None)))
    check("the no-intensities warning is gone, since the case it warned about is now refused",
          tdef is not None and tdef.warn is None,
          getattr(getattr(tdef, "warn", None), "__name__", "None"))

    for engine, method in NO_INTENSITY_PAIRS:
        verdict = supports(engine, method, "wigner_spectra")
        check(f"{engine}/{method} is refused for an ensemble spectrum",
              not verdict.supported, str(verdict.reasons))
        check(f"{engine}/{method}'s refusal names the missing capability",
              any("osc_strengths" in r for r in verdict.reasons), str(verdict.reasons))
        # The same pair must stay available for a single-geometry excited
        # state: energies with no intensities is a perfectly good answer
        # there, and narrowing that would be a regression, not a fix.
        check(f"{engine}/{method} still runs a plain single_point/ee",
              supports(engine, method, "single_point", "ee").supported)

    # -- 2. Routing follows from the requirement ----------------------
    for method, expected, why in ROUTING_EXPECTATIONS:
        decision = route_engine(method, "wigner_spectra", "")
        check(f"a {method} ensemble routes to {expected} ({why})",
              decision.engine == expected, f"got {decision.engine}")

    # An engine the user named explicitly is refused with its reasons and
    # real alternatives, never silently swapped for a working one.
    decision = route_engine("casscf", "wigner_spectra", "", requested_engine="pyscf")
    check("an explicit pyscf casscf ensemble is refused rather than rerouted silently",
          decision.engine is None, f"got {decision.engine}")
    check("...and offers the engines that can run it",
          set(decision.alternatives) == {"orca", "bagel"}, str(decision.alternatives))

    # -- 3. Intensities are forced on for every method ----------------
    for method, engine, _why in ROUTING_EXPECTATIONS:
        params = {**BASE_PARAMS, "source_frequency_job_id": src}
        notes: list = []
        built = _build_ensemble_spec_or_error(WATER, engine, method, params, notes)
        spec, _preview, _kb, param_notes, _note, _kwopts, _warnings, err = built
        check(f"a {method}/{engine} ensemble builds", err is None and spec is not None, str(err))
        if spec is None:
            continue
        check(f"...with want_oscillator_strengths forced on for {method}",
              spec.params.get("want_oscillator_strengths") is True,
              repr(spec.params.get("want_oscillator_strengths")))
        check(f"...and a note on the card saying why, for {method}",
              any("Oscillator strengths are always computed" in n for n in param_notes),
              str(param_notes))

    # -- 4. The builder is not the place the mistake gets through -----
    #
    # Reachable only if something bypasses elicitation, since a refused
    # combination never reaches "ready". Checked anyway: this used to be a
    # hardcoded allow-list of runner names, which could only speak about
    # the method and so passed a CASSCF ensemble aimed at PySCF.
    params = {**BASE_PARAMS, "source_frequency_job_id": src}
    built = _build_ensemble_spec_or_error(WATER, "pyscf", "casscf", params, [])
    spec, _p, _k, _n, _sn, _ko, _w, err = built
    check("the builder refuses a pyscf casscf ensemble outright",
          spec is None and err is not None, str(err)[:80])
    check("...explaining that the spectrum is weighted by the intensities",
          bool(err) and "convolution" in err, str(err)[:120])

    print("\n" + ("ALL CHECKS PASSED" if not failures else f"{failures} CHECK(S) FAILED"))
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
