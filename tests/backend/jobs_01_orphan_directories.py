"""A deleted job leaves nothing behind, and a half-deleted one is reclaimable.

Two job directories were found by hand on this host in a single day. One held
only an `orbitals.molden`; the other a full set that `delete_job_dir` had
failed to remove while ORCA was still writing into it.

The mechanism is worth stating because it makes the leftovers permanent rather
than merely untidy. `delete_job_dir` used `shutil.rmtree(..., ignore_errors=True)`,
so a delete that could not finish reported nothing -- and `spec.json` is
usually among the first entries to go. Every iterator in this app gates on
`spec.json` (`base._iter_job_ids_on_disk`, `quota._iter_job_ids`), so whatever
survived was no longer a job by the app's own definition: not listed, not
counted toward any quota, and not findable by the very function that failed to
delete it. Unreachable disk that grows.

Needs nothing running: no stack, no model, no Postgres. It writes only into
directories it creates under JOBS_DIR and removes them again.

Run:  PYTHONPATH=$PWD python3 tests/backend/jobs_01_orphan_directories.py
"""
import json
import shutil
import sys
import time
import uuid

from app.chemistry.jobs.base import (  # noqa: E402
    JOBS_DIR, delete_job_dir, reclaim_orphan_job_dirs, _iter_job_ids_on_disk,
)
from app.chemistry.jobs.quota import _iter_job_ids as quota_iter  # noqa: E402

failures = []


def check(name, ok, detail=""):
    print("[%s] %s%s" % ("PASS" if ok else "FAIL", name, ("  -- %s" % detail) if detail else ""))
    if not ok:
        failures.append(name)


made = []


def a_job_dir(with_spec: bool, extra_files=()) -> str:
    jid = "t" + uuid.uuid4().hex[:11]
    d = JOBS_DIR / jid
    d.mkdir(parents=True, exist_ok=True)
    made.append(d)
    if with_spec:
        (d / "spec.json").write_text(json.dumps({
            "job_id": jid, "task": "single_point", "subtype": "gs", "method": "hf",
            "engine": "pyscf", "molecule": {}, "params": {}, "label": "",
            "created_at": time.time(), "parent_job_id": None}))
        (d / "status.json").write_text(json.dumps(
            {"status": "completed", "message": "", "updated_at": time.time()}))
    for name in extra_files:
        (d / name).write_text("x")
    return jid


try:
    # --- the shape both real leftovers had ---------------------------------
    orphan = a_job_dir(with_spec=False, extra_files=("orbitals.molden",))
    check("a directory with an artifact but no spec is not a job to any iterator",
          orphan not in set(_iter_job_ids_on_disk()),
          "which is exactly why nothing could reach the two found by hand")
    check("nor to the quota accounting, which gates on spec.json the same way",
          orphan not in set(quota_iter()),
          "so it is not listed, not evicted and not counted -- pure unreachable disk")
    # delete_job_dir would remove it happily, since it deletes by path. That is
    # the whole shape of the bug: nothing can ever hand it the id, because no
    # iterator will yield one for a directory with no spec. A sweep that looks
    # for the directories themselves is the only thing that can reach them.

    reclaimed = reclaim_orphan_job_dirs()
    check("reclaim_orphan_job_dirs removes it", orphan in reclaimed and not (JOBS_DIR / orphan).exists(),
          "reclaimed %s" % reclaimed)

    # --- a real job is never mistaken for an orphan ------------------------
    real = a_job_dir(with_spec=True, extra_files=("output.out",))
    reclaimed2 = reclaim_orphan_job_dirs()
    check("a real job is never reclaimed by the sweep",
          real not in reclaimed2 and (JOBS_DIR / real).exists(),
          "a spec.json is what makes it a job, and it has one")
    check("and it is visible to the ordinary iterator", real in set(_iter_job_ids_on_disk()))

    # --- an ordinary delete leaves nothing --------------------------------
    delete_job_dir(real)
    check("delete_job_dir removes a real job's directory entirely",
          not (JOBS_DIR / real).exists())

    # --- an empty directory is reclaimed too ------------------------------
    empty = a_job_dir(with_spec=False)
    check("an empty leftover directory is reclaimed as well",
          empty in reclaim_orphan_job_dirs() and not (JOBS_DIR / empty).exists())

    # --- _seen is never touched -------------------------------------------
    seen = JOBS_DIR / "_seen"
    seen.mkdir(exist_ok=True)
    reclaim_orphan_job_dirs()
    check("the _seen bookkeeping directory is never reclaimed", seen.exists(),
          "it lives under JOBS_DIR but is not a job, and losing it loses notice dedup")
finally:
    for d in made:
        shutil.rmtree(d, ignore_errors=True)

print("\n%d failure(s)" % len(failures))
sys.exit(1 if failures else 0)
