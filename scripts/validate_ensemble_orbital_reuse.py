"""Checks that a nuclear-ensemble spectrum seeds every sample from the
frequency job it was built around, for CASSCF and CASPT2.

    conda activate qc-agent
    PYTHONPATH=$PWD python3 scripts/validate_ensemble_orbital_reuse.py

A wigner_spectra master runs one excited-state job per sampled geometry.
Without this each one starts from its own fresh HF guess, so nothing holds
the active space to the same orbitals across samples and the pooled
spectrum can mix two different spaces.

The id is derived at draft time rather than at dispatch, which is what
makes it visible on the approval card and overridable. It then reaches the
sub-jobs through the params template the orchestrator already builds, so
the checks below cover the derivation, the propagation, and the two gates
(method, and a source that cannot actually supply orbitals).
"""
import sys

from app.chemistry.jobs.base import ENSEMBLE_ONLY_PARAM_KEYS
from app.chemistry.registry2.params import PARAMS_BY_NAME
from app.chemistry.registry2.elicitation import validate_draft

ok = True


def check(label, condition, detail=""):
    global ok
    print(f"  [{'PASS' if condition else 'FAIL'}] {label}" + (f"  {detail}" if detail else ""))
    ok = ok and condition


def draft(method, **params):
    """A wigner draft far enough along that validate_draft reaches the
    orbital-reuse step. check_external=False keeps it off the job store,
    so the derivation is exercised without needing a real frequency job."""
    d = {"task": "wigner_spectra", "subtype": "", "method": method,
         "molecule": {"symbols": ["O", "H", "H"],
                      "coords": [[0, 0, 0.117], [0, 0.755, -0.469], [0, -0.755, -0.469]]},
         "params": {"source_frequency_job_id": "freqjob01", "n_samples": 4,
                    "basis": "cc-pvdz", "n_states": 3,
                    "active_electrons": 4, "active_orbitals": 4, **params}}
    return validate_draft(d, check_external=False).draft["params"]


print("the id is derived from the frequency job:")
for method in ("casscf", "caspt2"):
    p = draft(method)
    check(f"{method} seeds from the frequency job",
          p.get("initial_orbitals_job_id") == "freqjob01", str(p.get("initial_orbitals_job_id")))

print("\nthe gates:")
# Reuse is an active-space concept. A single-reference method has no
# active-space orbitals to carry from one geometry to the next.
p = draft("tddft")
check("a single-reference method derives nothing", "initial_orbitals_job_id" not in p,
      str(p.get("initial_orbitals_job_id")))
# Naming a different source must still win, or a user cannot override it.
p = draft("casscf", initial_orbitals_job_id="someotherjob")
check("a hand-named source is not overwritten",
      p.get("initial_orbitals_job_id") == "someotherjob", str(p.get("initial_orbitals_job_id")))

print("\nthe parameter is accepted on this task at all:")
# update_job_draft refuses a parameter whose applies_to does not cover the
# task, which would strip the derived value before it reached the master.
check("initial_orbitals_job_id applies to wigner_spectra",
      PARAMS_BY_NAME["initial_orbitals_job_id"].applies("wigner_spectra"))

print("\nit reaches every sample:")
# The orchestrator builds each sub-job's params from the master's, minus the
# keys that describe the ensemble itself. If this one were stripped there,
# the master would carry it and no sample would.
check("it is not stripped as an ensemble-only key",
      "initial_orbitals_job_id" not in ENSEMBLE_ONLY_PARAM_KEYS)
master_params = draft("casscf")
sub_params = {k: v for k, v in master_params.items()
              if k not in ENSEMBLE_ONLY_PARAM_KEYS and not k.startswith("_")}
check("a sample's params carry the source",
      sub_params.get("initial_orbitals_job_id") == "freqjob01")
check("the sample does not inherit the ensemble's own settings",
      "n_samples" not in sub_params and "source_frequency_job_id" not in sub_params)

print("\na frequency job that cannot supply orbitals degrades rather than blocking:")
# The common real workflow: optimize and take frequencies at DFT, then run the
# ensemble's excited states at CASSCF. That freq job is a perfectly valid
# sampling source and has no active-space orbitals at all, so the derived id
# has to drop out with a note instead of failing the draft. Needs a job on
# disk, since this is the one branch that reads the job store.
import json, os, shutil
from app.config import JOBS_DIR

FAKE = "zzvalidate01"
job_dir = os.path.join(str(JOBS_DIR), FAKE)
try:
    os.makedirs(job_dir, exist_ok=True)
    with open(os.path.join(job_dir, "spec.json"), "w") as f:
        json.dump({"job_id": FAKE, "task": "freq", "subtype": "", "method": "dft",
                   "engine": "pyscf", "params": {"basis": "cc-pvdz", "functional": "b3lyp"},
                   "molecule": {"symbols": ["O", "H", "H"],
                                "coords": [[0, 0, 0.117], [0, 0.755, -0.469], [0, -0.755, -0.469]]}}, f)
    with open(os.path.join(job_dir, "status.json"), "w") as f:
        json.dump({"status": "completed", "message": "done", "updated_at": 0}, f)
    with open(os.path.join(job_dir, "result.json"), "w") as f:
        json.dump({"job_id": FAKE, "status": "completed",
                   "summary": {"frequencies_cm1": [1600.0, 3700.0, 3800.0],
                               "reduced_masses_amu": [1.08, 1.05, 1.08],
                               "normal_modes": [[[0, 0, 0.1]] * 3] * 3}}, f)

    d = {"task": "wigner_spectra", "subtype": "", "method": "casscf",
         "molecule": {"symbols": ["O", "H", "H"],
                      "coords": [[0, 0, 0.117], [0, 0.755, -0.469], [0, -0.755, -0.469]]},
         "params": {"source_frequency_job_id": FAKE, "n_samples": 4, "basis": "cc-pvdz",
                    "n_states": 3, "active_electrons": 4, "active_orbitals": 4}}
    verdict = validate_draft(d, check_external=True)
    check("the draft is not blocked", verdict.status != "unavailable", verdict.status)
    check("the unusable source is dropped",
          "initial_orbitals_job_id" not in verdict.draft["params"])
    check("and the user is told why",
          any("fresh guess" in n for n in verdict.notes),
          " | ".join(verdict.notes) or "(no notes)")
finally:
    shutil.rmtree(job_dir, ignore_errors=True)

print("\nRESULT:", "all checks passed" if ok else "FAILURES above")
sys.exit(0 if ok else 1)
