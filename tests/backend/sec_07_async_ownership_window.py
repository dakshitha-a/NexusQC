"""SEC-07: chat.py's approve_job records ownership via
app/auth/ownership.record() AFTER resume_turn() returns -- i.e. the job
exists and is servable for a real (if usually brief) window before it has
an owner at all. app/auth/ownership.py's check_owner_or_admin treats "no
recorded owner" as accessible to EVERYONE (the documented legacy/unowned
policy), so during that window any other user can read a just-created job.

Driving this through the real chat -> submit_job -> interrupt() ->
approve_job round trip needs a live LLM tool-calling turn, which is slow
and non-deterministic to time precisely. Instead, this test exercises the
exact mechanism approve_job relies on directly: create a job (bypassing
chat, same as SEC-06), leave it deliberately unowned for a short window,
and confirm from a SECOND user's session that the job is reachable during
that window and stops being reachable the instant ownership is recorded --
this is precisely the invariant approve_job's ordering (resume first,
record() after) exposes a race on. The window size in the real app depends
on resume_turn()'s own duration (usually well under a second, but
uncapped), not this test's artificial delay -- this test's job is to prove
the mechanism is racy at all, not to measure the real app's window.
"""
from __future__ import annotations

import subprocess
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from fixtures import admin_client, check, cleanup_user, mint_invite, register, summary  # noqa: E402

COMPOSE_DIR = Path(__file__).resolve().parent.parent.parent
WINDOW_SECONDS = 4


def _exec_api(code: str) -> str:
    proc = subprocess.run(
        ["docker", "compose", "exec", "-T", "api", "python", "-c", code],
        cwd=str(COMPOSE_DIR), capture_output=True, text=True, timeout=60,
    )
    if proc.returncode != 0:
        print(proc.stderr, file=sys.stderr)
        raise RuntimeError(f"in-container exec failed: {proc.stderr[:500]}")
    return proc.stdout.strip()


def _submit_job_unowned() -> str:
    code = '''
import time
from app.chemistry.molecule import resolve_molecule
from app.chemistry.jobs.base import JobSpec, get_job_manager

m = resolve_molecule("water")
spec = JobSpec(method="single_point", engine="pyscf", molecule=m.to_dict(), params={"method": "hf", "basis": "sto-3g"})
job_id = get_job_manager().submit(spec)
for _ in range(60):
    status = get_job_manager().status(job_id)
    if status["status"] in ("completed", "failed"):
        break
    time.sleep(1)
print(job_id)
'''
    return _exec_api(code)


def _record_ownership_after_delay(job_id: str, owner_user_id: str, delay: float) -> None:
    time.sleep(delay)
    _exec_api(
        f'from app.auth.models import record_ownership; record_ownership("job", "{job_id}", "{owner_user_id}")'
    )


def main() -> None:
    admin = admin_client()
    token_a = mint_invite(admin)
    token_b = mint_invite(admin)
    client_a, user_a = register(token_a)
    client_b, user_b = register(token_b)

    job_id = _submit_job_unowned()
    print(f"created job {job_id}, deliberately left unowned for up to {WINDOW_SECONDS}s")

    recorder = threading.Thread(target=_record_ownership_after_delay, args=(job_id, user_a["id"], WINDOW_SECONDS))
    recorder.start()

    r_during_window = client_b.get(f"/api/jobs/{job_id}")
    check(
        "unowned job is reachable by a DIFFERENT user during the ownership-recording window",
        r_during_window.status_code == 200,
        f"got {r_during_window.status_code} -- this reproduces the documented 'no recorded owner = "
        "accessible to everyone' policy that creates SEC-07's window in the real approve_job flow",
    )

    recorder.join()
    time.sleep(0.5)  # let the write settle
    r_after_window = client_b.get(f"/api/jobs/{job_id}")
    check(
        "the SAME job is denied to user B once ownership is recorded for user A",
        r_after_window.status_code == 404,
        f"got {r_after_window.status_code}",
    )

    r_owner_check = client_a.get(f"/api/jobs/{job_id}")
    check("the actual owner (user A) can still see it after ownership is recorded", r_owner_check.status_code == 200)

    cleanup_user(admin, user_a["id"])
    cleanup_user(admin, user_b["id"])
    summary(exit_on_failure=False)


if __name__ == "__main__":
    main()
