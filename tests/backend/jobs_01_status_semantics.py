#!/usr/bin/env python3
"""A job directory is only a job if it holds a spec.

    PYTHONPATH=$PWD python3 tests/backend/jobs_01_status_semantics.py

F-024 established that a job the system has never heard of must not report
"pending": callers reasonably read "pending" as "wait for it", so a reference
to a purged job could be waited on forever. That fix drew its line at the job
DIRECTORY, which turned out to be one level too shallow.

A directory can outlive its job, or be recreated after it, holding nothing but
a stray artifact -- observed live as a directory containing only an
orbitals.molden, written by an orbital-reuse path after the job it belonged to
had been purged. It reported "pending" indefinitely while the Job Manager
hid it, because that listing requires spec.json. The app would then tell a
user a job was queued and show them a list it was not in.

`submit` writes spec.json first and status.json immediately after, so the
honest test of "is this a job" is spec.json, and this asserts all three
states around it.
"""
from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO))

from app.chemistry.jobs.base import get_job_manager, read_status  # noqa: E402
from app.config import JOBS_DIR  # noqa: E402

failures: list[str] = []
checks = 0


def check(name: str, ok: bool, detail: str = "") -> bool:
    global checks
    checks += 1
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f" -- {detail}" if detail else ""))
    if not ok:
        failures.append(name)
    return ok


def main() -> int:
    mgr = get_job_manager()
    debris = JOBS_DIR / "zz_status_debris"
    queued = JOBS_DIR / "zz_status_queued"
    for d in (debris, queued):
        shutil.rmtree(d, ignore_errors=True)

    try:
        print("\n== a directory holding only a stray artifact is not a job ==")
        debris.mkdir(parents=True, exist_ok=True)
        (debris / "orbitals.molden").write_text("[Molden Format]\n")
        check("read_status returns None for it", read_status(debris.name) is None)
        st = mgr.status(debris.name)
        check("and the manager calls it unknown, not pending",
              st["status"] == "unknown", json.dumps(st))

        print("\n== a directory holding a spec but no status IS a queued job ==")
        # This is the state `submit` passes through: spec.json written, then
        # status.json. It must keep reporting pending, or a genuinely queued
        # job would look like it had vanished.
        queued.mkdir(parents=True, exist_ok=True)
        (queued / "spec.json").write_text(json.dumps({"job_id": queued.name}))
        st = read_status(queued.name)
        check("read_status reports pending", st is not None and st["status"] == "pending", json.dumps(st))

        print("\n== a directory that is not there at all ==")
        check("read_status returns None", read_status("zz_status_absent") is None)
        check("and the manager calls it unknown",
              mgr.status("zz_status_absent")["status"] == "unknown")
    finally:
        for d in (debris, queued):
            shutil.rmtree(d, ignore_errors=True)

    print(f"\n{checks - len(failures)}/{checks} checks passed")
    if failures:
        print(f"[FAIL] {len(failures)} check(s) failed")
        return 1
    print("[PASS] ALL CHECKS PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
