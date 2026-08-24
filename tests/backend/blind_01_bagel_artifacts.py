#!/usr/bin/env python3
"""A BAGEL job keeps the files it wrote -- see
docs/trackers/2026-08-bagel-blind-input.md.

Two defects in one sweep. `scratch.py`'s BAGEL rule deletes everything a
completed job left except the handful of names it keeps, which is safe
only because a structured runner declares its real outputs as artifacts
and `_artifact_filenames` protects those. Neither half of that held:

- A **blind** job's runner cannot declare its outputs, because the pasted
  input names its own files and this app has no list of what they are. A
  user who wrote `{"title": "print", "file": "orbitals.molden"}` got an
  empty directory back.
- `orbitals.archive` is written by every CASSCF/CASPT2 input this app
  builds (the `save_ref` block) so a later job can start from those
  orbitals, and nothing declares it either, because it is an input to a
  future job rather than a result of this one. It was deleted from every
  completed BAGEL job, structured ones included, which left BAGEL orbital
  reuse with no source to reuse.

Runs against the job store directly rather than the API: `scratch.py` is
called by the JobManager after a run finishes and takes a job id, so a
directory laid out the way a finished run leaves one is the whole input.
Every directory this creates is removed again, per the repo's rule that a
suite run leaves no clutter behind.

Run:  PYTHONPATH=$PWD python3 tests/backend/blind_01_bagel_artifacts.py
"""
from __future__ import annotations

import json
import shutil
import sys
import tempfile
from pathlib import Path

from app.chemistry.jobs.base import JOBS_DIR
from app.chemistry.jobs.bagel_runner import _add_orbital_table
from app.chemistry.jobs.scratch import cleanup_scratch_files

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


def make_job(job_id: str, task: str, status: str, artifacts: dict, files: list[str]) -> Path:
    """A job directory shaped the way a finished BAGEL run leaves one."""
    d = JOBS_DIR / job_id
    if d.exists():
        shutil.rmtree(d)
    d.mkdir(parents=True)
    (d / "spec.json").write_text(json.dumps(
        {"job_id": job_id, "engine": "bagel", "task": task, "subtype": "", "method": ""}))
    (d / "status.json").write_text(json.dumps({"job_id": job_id, "status": status}))
    (d / "result.json").write_text(json.dumps(
        {"job_id": job_id, "status": status,
         "artifacts": {k: str(d / v) for k, v in artifacts.items()}}))
    (d / "meta.json").write_text(json.dumps({"label": None}))
    (d / "worker.log").write_text("")
    for name in files:
        (d / name).write_text("x")
    return d


def survivors(d: Path) -> set[str]:
    return {f.name for f in d.iterdir() if f.is_file()}


# A BAGEL run leaves its input and output, whatever the input asked it to
# write, and scratch with no consistent naming stem -- a CASSCF run leaves
# "casscf.log", a Hessian run "freq.log" (both observed on real runs).
WROTE = ["input.json", "bagel.out", "orbitals.molden", "orbitals.archive", "casscf.log"]

JOB_IDS = ["zz_blind_test1", "zz_struct_test1", "zz_failed_test1"]


def main() -> int:
    print("== a blind job keeps everything its own input asked for ==")
    # The runner declares the molden now, but not the archive and not
    # whatever else a pasted input might name -- so the narrow rule, not
    # the artifact list, is what has to carry this.
    d = make_job(JOB_IDS[0], "blind", "completed", {"raw_output": "bagel.out"}, WROTE)
    cleanup_scratch_files(JOB_IDS[0], "bagel", "blind")
    left = survivors(d)
    check("the molden the pasted input asked BAGEL to write survives",
          "orbitals.molden" in left, f"left: {sorted(left)}")
    check("so does the save_ref archive", "orbitals.archive" in left, f"left: {sorted(left)}")
    check("input and output are untouched",
          {"input.json", "bagel.out"} <= left, f"left: {sorted(left)}")
    check("and the one scratch pattern actually observed is still swept",
          "casscf.log" not in left, f"left: {sorted(left)}")

    print("\n== a structured job keeps the archive a later job reuses ==")
    d = make_job(JOB_IDS[1], "single_point", "completed",
                 {"raw_output": "bagel.out", "molden": "orbitals.molden"}, WROTE)
    cleanup_scratch_files(JOB_IDS[1], "bagel", "single_point")
    left = survivors(d)
    check("orbitals.archive survives, so orbital reuse has a source",
          "orbitals.archive" in left, f"left: {sorted(left)}")
    check("the declared molden artifact survives",
          "orbitals.molden" in left, f"left: {sorted(left)}")
    check("the broad denylist still sweeps real scratch",
          "casscf.log" not in left, f"left: {sorted(left)}")

    print("\n== a failed job is unchanged by any of this ==")
    d = make_job(JOB_IDS[2], "single_point", "failed", {}, WROTE)
    cleanup_scratch_files(JOB_IDS[2], "bagel", "single_point")
    left = survivors(d)
    check("a partial run's real output is kept",
          {"bagel.out", "orbitals.molden"} <= left, f"left: {sorted(left)}")
    check("its logs are not", "casscf.log" not in left, f"left: {sorted(left)}")

    print("\n== the orbital table is best-effort, not a way to fail a job ==")
    tmp = Path(tempfile.mkdtemp())
    (tmp / "orbitals.molden").write_text("[Molden Format]\ntruncated, and not valid\n")
    summary: dict = {"note": "raw"}
    try:
        got = _add_orbital_table(summary, str(tmp), multireference=False)
        raised = False
    except Exception as exc:  # noqa: BLE001
        got, raised = None, True
        print(f"         raised: {exc!r}")
    check("a molden the reader chokes on degrades to no table, and does not raise",
          not raised and got is None and "orbital_table" not in summary,
          f"raised={raised} got={got!r} keys={list(summary)}")
    shutil.rmtree(tmp, ignore_errors=True)

    empty: dict = {}
    check("a job with no molden at all is simply given no table",
          _add_orbital_table(empty, tempfile.mkdtemp()) is None and not empty)

    print(f"\n{PASS}/{PASS + FAIL} checks passed")
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    try:
        code = main()
    finally:
        for job_id in JOB_IDS:
            shutil.rmtree(JOBS_DIR / job_id, ignore_errors=True)
    print("[PASS] ALL CHECKS PASSED" if code == 0 else "[FAIL] see above")
    sys.exit(code)
