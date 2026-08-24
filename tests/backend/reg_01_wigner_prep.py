#!/usr/bin/env python3
"""Regression: preparing a wigner_ensemble job must not raise.

    PYTHONPATH=$PWD python3 tests/backend/reg_01_wigner_prep.py

_build_ensemble_spec_or_error called _keyword_options_for_job with two
arguments where the function requires three (job_type, params, engine), so
EVERY wigner_ensemble preparation raised TypeError just before returning --
in both generate_job_input and submit_job. It never crashed the server
because ToolNode catches tool exceptions and hands the model an error
ToolMessage, which is exactly why it survived: the failure looked like the
model being confused rather than a bug.

This drives the real builder against a synthetic completed frequency job
written into a temporary jobs directory, so the whole path -- source-job
lookup, Wigner sampling, sub-job param derivation, input preview, KB
context, keyword menu -- runs for real. Prints PASS/FAIL per check.

Needs only the qc-agent environment; no server, no engines.
"""
from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO))

# `app.config.JOBS_DIR` is a hardcoded `PROJECT_ROOT / "data" / "jobs"` and
# reads no environment variable, so the `QC_AGENT_JOBS_DIR` redirect this
# script used to set never did anything: the fixture went into the live job
# store, which docker-compose.yml bind-mounts as `./data`, and an unowned
# job there is deliberately visible to every user. It is removed in a
# `finally` instead -- see `main`.

from app.agent.tools import _build_ensemble_spec_or_error  # noqa: E402
from app.config import JOBS_DIR  # noqa: E402

WATER = {
    "name": "water",
    "symbols": ["O", "H", "H"],
    "coords": [[0.0, 0.0, 0.117], [0.0, 0.757, -0.467], [0.0, -0.757, -0.467]],
    "charge": 0,
    "multiplicity": 1,
}

# Three real-looking normal modes for a bent triatomic. Values need only be
# physically plausible: the point is to exercise the code path, not to
# reproduce a particular calculation.
NORMAL_MODES = [
    [[0.0, 0.0, -0.07], [0.0, 0.43, 0.55], [0.0, -0.43, 0.55]],
    [[0.0, 0.0, 0.05], [0.0, 0.58, -0.40], [0.0, -0.58, -0.40]],
    [[0.0, 0.07, 0.0], [0.0, -0.55, 0.43], [0.0, -0.55, -0.43]],
]


FIXTURE_JOB_ID = "testfixture-reg01-freq"


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

    params = {
        "source_frequency_job_id": src,
        "n_samples": 4,
        "functional": "b3lyp",
        "basis": "sto-3g",
        "n_states": 3,
    }

    # P2B.1/P2B.4: engine and method are registry2's decisions by the time
    # a ready draft reaches this builder (validate_draft's route_engine),
    # passed in already-resolved rather than re-derived here -- "pyscf"/
    # "dft" is what route_engine would resolve a DFT-based wigner_spectra
    # draft to by default.
    try:
        spec, preview, kb, notes, note, kwopts, warnings, err = _build_ensemble_spec_or_error(
            WATER, "pyscf", "dft", dict(params), []
        )
        raised = None
    except Exception as e:  # the regression: TypeError from the missing engine arg
        spec = preview = kb = notes = note = kwopts = warnings = err = None
        raised = e

    check("builder does not raise", raised is None, repr(raised) if raised else "")
    if raised is not None:
        return 1

    check("no error string returned", err is None, str(err))
    check("spec built", spec is not None and spec.method == "dft",
          getattr(spec, "method", None))
    check("engine resolved", spec is not None and spec.engine in {"pyscf", "orca", "bagel"},
          getattr(spec, "engine", None))
    check("input preview generated", bool(preview and preview.strip()))
    check("scan note mentions the sample count", bool(note and "4" in note), str(note)[:80])
    # keyword_options is legitimately None when nothing needs disambiguating;
    # what matters is that computing it did not raise (checked above) and that
    # its shape is right when present.
    check("keyword options shape", kwopts is None or isinstance(kwopts, dict), type(kwopts).__name__)

    print("\n" + ("ALL CHECKS PASSED" if not failures else f"{failures} CHECK(S) FAILED"))
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
