"""The admin purge must act on the same jobs the admin console lists.

It did not. `_job_candidates` in app/auth/storage_quota.py asked
`read_result(job_id)` whether a job was terminal, while the job list, the
job drawer and DELETE /api/jobs/{id} all ask `read_status(job_id)`.
`write_status()` and `write_result()` are two separate writes, so a job
interrupted between them -- or written by anything that sets a status
without a result -- was listed as completed and was permanently
unpurgeable: `POST /api/admin/purge/jobs` returned `count: 0` against a
console listing hundreds of finished jobs. Found in practice, not in
theory.

Also covers the orphan-directory sweep added alongside the fix: a job
directory with no spec.json is invisible to `_iter_job_ids()`, so nothing
lists it, nothing purges it, and it never counted toward a quota. The
sweep only touches such a directory once it has been untouched for
_ORPHAN_DIR_MIN_AGE_SECONDS, because JobManager.submit() creates the
directory before writing spec.json and a purge must never be able to race
a submission. Both halves of that gate are checked here.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from fixtures import admin_client, check, summary  # noqa: E402

COMPOSE_DIR = Path(__file__).resolve().parent.parent.parent

NO_RESULT_JOB = "qatestnores01"
ORPHAN_OLD = "qatestorphold"
ORPHAN_YOUNG = "qatestorphnew"


def _exec_api(code: str) -> tuple[int, str, str]:
    proc = subprocess.run(
        ["docker", "compose", "exec", "-T", "api", "python", "-c", code],
        cwd=str(COMPOSE_DIR), capture_output=True, text=True, timeout=60,
    )
    return proc.returncode, proc.stdout, proc.stderr


_SEED = f'''
import json, os, pathlib, time
from app.config import JOBS_DIR

# A job the console lists as completed whose result.json was never written
# -- exactly the shape an interrupted write leaves behind.
d = pathlib.Path(JOBS_DIR) / "{NO_RESULT_JOB}"
d.mkdir(parents=True, exist_ok=True)
(d / "spec.json").write_text(json.dumps({{
    "job_id": "{NO_RESULT_JOB}", "task": "single_point", "subtype": "gs",
    "method": "hf", "engine": "pyscf",
    "molecule": {{"name": "water", "symbols": ["O"], "coords": [[0, 0, 0]]}},
    "params": {{"basis": "sto-3g"}}, "created_at": time.time(),
}}))
(d / "status.json").write_text(json.dumps({{
    "status": "completed", "message": "terminal, but no result written", "updated_at": time.time(),
}}))

# An orphan directory old enough to be certain it is not mid-submission.
old_dir = pathlib.Path(JOBS_DIR) / "{ORPHAN_OLD}"
old_dir.mkdir(parents=True, exist_ok=True)
(old_dir / "orbitals.molden").write_text("stale artifact")
stale = time.time() - 7200
os.utime(old_dir / "orbitals.molden", (stale, stale))
os.utime(old_dir, (stale, stale))

# An orphan directory that has JUST appeared. This stands in for a live
# submission between mkdir and the spec.json write, and must survive.
young = pathlib.Path(JOBS_DIR) / "{ORPHAN_YOUNG}"
young.mkdir(parents=True, exist_ok=True)
(young / "partial.tmp").write_text("just created")
print("seeded")
'''

_SURVEY = f'''
import json, pathlib
from app.config import JOBS_DIR
names = sorted(p.name for p in pathlib.Path(JOBS_DIR).iterdir() if p.is_dir())
print(json.dumps([n for n in names if n in ("{NO_RESULT_JOB}", "{ORPHAN_OLD}", "{ORPHAN_YOUNG}")]))
'''

_CLEANUP = f'''
import pathlib, shutil
from app.config import JOBS_DIR
for name in ("{NO_RESULT_JOB}", "{ORPHAN_OLD}", "{ORPHAN_YOUNG}"):
    shutil.rmtree(pathlib.Path(JOBS_DIR) / name, ignore_errors=True)
print("cleaned")
'''


def _dirs_present() -> list[str]:
    _, out, _ = _exec_api(_SURVEY)
    return json.loads(out.strip().splitlines()[-1])


def main() -> None:
    admin = admin_client()
    try:
        rc, out, err = _exec_api(_SEED)
        check("seeded the three directories", rc == 0 and "seeded" in out, err[-200:] if rc else "")

        listed = {j["job_id"]: j["status"] for j in admin.get("/api/jobs").json()}
        check(
            "the console lists the result-less job as completed",
            listed.get(NO_RESULT_JOB) == "completed",
            str(listed.get(NO_RESULT_JOB)),
        )

        r = admin.post("/api/admin/purge/jobs", timeout=180)
        purged = set(r.json().get("purged_job_ids", []))
        check("purge succeeds", r.status_code == 200, f"{r.status_code} {r.text[:150]}")

        # The regression itself: this used to be reported as 0 purged.
        check(
            "a terminal job with no result.json IS purged (was silently skipped)",
            NO_RESULT_JOB in purged,
            f"purged={sorted(purged)}",
        )
        check(
            "a stale orphan directory with no spec.json is swept",
            ORPHAN_OLD in purged,
            f"purged={sorted(purged)}",
        )
        check(
            "a JUST-created orphan directory is NOT swept (it could be a live submission)",
            ORPHAN_YOUNG not in purged,
            f"purged={sorted(purged)}",
        )

        remaining = _dirs_present()
        check(
            "on disk: both stale directories are gone, the fresh one survives",
            remaining == [ORPHAN_YOUNG],
            f"remaining={remaining}",
        )

        still_listed = {j["job_id"] for j in admin.get("/api/jobs").json()}
        check(
            "the console no longer lists the purged job",
            NO_RESULT_JOB not in still_listed,
            f"listed={sorted(still_listed)}",
        )

        # --- The dedicated orphan purge, which reclaims that disk without
        # --- destroying anyone's job history the way purge_all_jobs does.
        rc, out, err = _exec_api(_SEED)
        check("re-seeded for the dedicated orphan purge", rc == 0 and "seeded" in out, err[-200:] if rc else "")

        report = admin.get("/api/admin/storage").json()["orphaned_jobs"]
        check(
            "the storage report surfaces the stale orphan, which nothing else in the app lists",
            ORPHAN_OLD in report["job_ids"],
            f"report={report}",
        )
        check(
            "and reports the fresh one as held back rather than silently dropping it",
            report["held_back"] >= 1,
            f"held_back={report['held_back']}",
        )
        check(
            "orphan bytes are reported, so the admin knows whether it is worth reclaiming",
            report["bytes"] > 0,
            f"bytes={report['bytes']}",
        )

        r_orph = admin.post("/api/admin/purge/orphaned-jobs", timeout=180)
        body = r_orph.json()
        check("the dedicated orphan purge succeeds", r_orph.status_code == 200, f"{r_orph.status_code} {r_orph.text[:150]}")
        check(
            "it removes the stale orphan",
            ORPHAN_OLD in body.get("purged_job_ids", []),
            str(body),
        )
        check(
            "it leaves the just-created one alone",
            ORPHAN_YOUNG not in body.get("purged_job_ids", []),
            str(body),
        )
        check(
            "it does NOT touch a real job -- that is purge_all_jobs' business, not this action's",
            NO_RESULT_JOB not in body.get("purged_job_ids", [])
            and NO_RESULT_JOB in {j["job_id"] for j in admin.get("/api/jobs").json()},
            str(body),
        )

        audit = admin.get("/api/admin/audit-log").json()
        check(
            "the orphan purge is audit-logged under its own action name",
            any(e["action"] == "purge_orphaned_jobs" for e in audit),
            str(sorted({e["action"] for e in audit})),
        )
    finally:
        _exec_api(_CLEANUP)

    summary()


if __name__ == "__main__":
    main()
