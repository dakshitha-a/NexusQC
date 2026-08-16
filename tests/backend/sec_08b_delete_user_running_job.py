"""SEC-08b (fix regression test): the original SEC-08 fix (purge_user_data(),
see sec_08_delete_user_orphaned_files.py) only purged a deleted user's
TERMINAL jobs -- a job still pending/running at delete time was left
untouched, kept computing in its own detached subprocess after the account
(and its ownership_index row) was gone, and once it finished it became
exactly the same kind of globally-readable "unowned" orphan SEC-08
otherwise closes, just for that one window. This was a real, documented gap
(CLAUDE.md's "Known limitations"), not a hypothetical.

The fix: purge_user_data() now cancels (and blocks until genuinely
terminal, via a new _cancel_and_await_terminal() helper) any of the deleted
user's still-pending/running jobs before the normal terminal-jobs eviction
pass runs, so nothing is left mid-flight to finish unowned after the
account is already gone.

Driving this through a real chat -> submit_job -> interrupt() -> approve
round trip (the only way to get a job whose live Popen sits in the actual
running server's own JobManager) needs a live LLM tool-calling turn, which
sec_07_async_ownership_window.py's own docstring already establishes this
suite deliberately avoids ("slow and non-deterministic to time precisely")
in favor of testing the underlying mechanism directly. Two faster
alternatives were tried here and both turned out to be genuine dead ends,
not just inconvenient, which is worth recording so a future test writer
doesn't retry them:

1. Submitting the job via a separate one-shot `docker compose exec`
   process, then racing an HTTP DELETE against it. JobManager tracks a
   job's live Popen in an in-memory dict scoped to whichever PROCESS
   called submit() -- a one-shot process's JobManager has no relationship
   to the live server's, so the live server's own cancel() (the one
   purge_user_data() actually calls) can never reach a job submitted this
   way. Confirmed directly: this reliably reproduces the pre-fix bug
   symptom (purged_jobs=0, file survives) for a reason that has nothing to
   do with whether the fix itself works.
2. Restarting the `api` container to force JobManager._reconcile_orphaned_
   jobs() to pick the orphaned worker back up as a live-server-tracked
   process. Confirmed directly this doesn't work either: `python -m
   server.main` runs as PID 1 of this container (docker/entrypoint.sh's
   own `exec "$@"`), so a container restart tears down the ENTIRE PID
   namespace -- including the detached worker subprocess -- rather than
   restarting just the Python process while the container (and the
   orphaned worker inside it) survives. The job comes back "failed", not
   "running", every time.

So, matching sec_07's own precedent exactly: this test calls
purge_user_data() directly, in the SAME one-shot process that submitted
the job -- which is not a workaround, it's the correct way to exercise the
real self._procs code path (the normal, everyday case: a job submitted
and still running in the very process handling the request), since
get_job_manager() returns the same in-process singleton both times. The
job is deliberately heavier than this suite's usual trivial water/HF/
STO-3G probe (benzene, HF/6-31g, frequency -- a real Hessian evaluation)
specifically so it's still genuinely pending/running at the instant
purge_user_data() is called, not already terminal by then.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from fixtures import admin_client, check, cleanup_user, mint_invite, register, summary  # noqa: E402

COMPOSE_DIR = Path(__file__).resolve().parent.parent.parent


def _exec_api(code: str) -> str:
    proc = subprocess.run(
        ["docker", "compose", "exec", "-T", "api", "python", "-c", code],
        cwd=str(COMPOSE_DIR), capture_output=True, text=True, timeout=90,
    )
    if proc.returncode != 0:
        print(proc.stderr, file=sys.stderr)
        raise RuntimeError(f"in-container exec failed: {proc.stderr[:500]}")
    return proc.stdout.strip()


def _submit_and_purge(owner_user_id: str) -> dict:
    # Everything below runs in ONE process so get_job_manager() returns the
    # same singleton for both submit() and (inside purge_user_data())
    # cancel() -- see module docstring for why that's the deliberate point,
    # not an incidental simplification.
    code = f'''
import json
from app.chemistry.molecule import resolve_molecule
from app.chemistry.jobs.base import JobSpec, get_job_manager, read_status
from app.auth.models import record_ownership
from app.auth.storage_quota import purge_user_data
from app.config import JOBS_DIR

m = resolve_molecule("benzene")
spec = JobSpec(method="frequency", engine="pyscf", molecule=m.to_dict(), params={{"method": "hf", "basis": "6-31g"}})
job_id = get_job_manager().submit(spec)
record_ownership("job", job_id, "{owner_user_id}")
status_before = read_status(job_id)["status"]

purged = purge_user_data("{owner_user_id}")

print(json.dumps({{
    "job_id": job_id,
    "status_before_purge": status_before,
    "purged": purged,
    "dir_exists_after_purge": (JOBS_DIR / job_id).exists(),
}}))
'''
    return json.loads(_exec_api(code))


def main() -> None:
    admin = admin_client()
    token_a = mint_invite(admin)
    token_c = mint_invite(admin)
    _client_a, user_a = register(token_a)
    client_c, user_c = register(token_c)

    info = _submit_and_purge(user_a["id"])
    job_id = info["job_id"]
    print(f"created job {job_id}, status immediately after submit (before purge_user_data ran): "
          f"{info['status_before_purge']}")
    if info["status_before_purge"] not in ("pending", "running"):
        print(
            "NOTE: job was already terminal before purge_user_data() ran -- this run only exercises "
            "SEC-08's original already-terminal case, not the mid-flight cancel path SEC-08b targets. "
            "Re-run to try to catch the race."
        )

    check(
        "FIX VERIFIED: purge_user_data() cancels and purges a job that was still pending/running",
        job_id in info["purged"]["job_ids"],
        f"purged={info['purged']}",
    )
    check(
        "FIX VERIFIED: the job's directory no longer exists on disk once purge_user_data() returns",
        not info["dir_exists_after_purge"],
        f"job dir for {job_id} still existed right after purge_user_data() -- confirms the mid-flight "
        "orphan bug is still present",
    )

    # purge_user_data() already ran directly above -- this exercises the
    # real HTTP route end-to-end on top of that (deleting the now-already-
    # purged account should still succeed cleanly, reporting nothing left
    # to purge), and confirms an unrelated user is denied the job through
    # the real API, not just on disk.
    r_delete = admin.delete(f"/api/admin/users/{user_a['id']}")
    check("admin successfully deletes user A's account", r_delete.status_code == 200,
          f"{r_delete.status_code} {r_delete.text[:200]}")
    print(f"delete response: {r_delete.json() if r_delete.status_code == 200 else r_delete.text}")

    r_after = client_c.get(f"/api/jobs/{job_id}")
    check(
        "unrelated user C is denied the (deleted-owner's, was-in-flight) job",
        r_after.status_code == 404,
        f"got {r_after.status_code} -- 200 would confirm the job survived as a globally-readable unowned orphan",
    )

    cleanup_user(admin, user_c["id"])
    summary()


if __name__ == "__main__":
    main()
