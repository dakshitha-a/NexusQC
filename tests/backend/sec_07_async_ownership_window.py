"""SEC-07 (fix regression test): chat.py's approve_job used to record
ownership via app/auth/ownership.record() only AFTER resume_turn()
returned -- i.e. the job existed and was servable for a real window
before it had an owner at all. app/auth/ownership.py's check_owner_or_admin
treats "no recorded owner" as accessible to EVERYONE (the documented
legacy/unowned policy), so during that window any other user could read a
just-created job.

The fix went through two iterations, the first of which turned out to be
incomplete -- caught by this very test, not assumed correct:

  v1 (incomplete): record ownership inside submit_job's tool body,
  immediately after JobManager.submit()/submit_scan() RETURNS. This
  closed the original HTTP-layer window, but this test's own first run
  against it still showed hundreds of spurious 200s and a multi-SECOND
  gap between "job visible" and "ownership recorded" -- because
  JobManager.submit() itself writes spec.json/status.json (making the job
  visible) near the TOP of the call, then runs a real quota-enforcement
  pass (enforce_quota(), which recomputes usage across every user's jobs/
  KB/chat) AFTER that, before returning. On a populated deployment that
  pass can itself take multiple seconds -- so "record right after
  submit() returns" still left the job unowned-and-readable for that
  entire quota-enforcement duration.

  v2 (the actual fix): JobManager.submit()/submit_scan() (app/chemistry/
  jobs/base.py) now record ownership THEMSELVES, immediately after
  writing spec.json/status.json and before anything else in the call --
  including their own quota-enforcement pass. submit_job (tools.py) just
  passes owner_user_id through (from AgentState, set once per turn by
  _run_turn, the same field search_knowledge_base already reads), rather
  than recording anything itself. approve_job's own post-hoc record()
  call still runs afterward too, as a defense-in-depth backstop
  (record_ownership is ON CONFLICT DO NOTHING, so the redundant write is
  harmless), but is no longer the primary mechanism.

Driving this through the real chat -> submit_job -> interrupt() ->
approve_job round trip still needs a live LLM tool-calling turn, which
this suite deliberately avoids for the same "slow and non-deterministic"
reason its own original version already gave. So, same precedent: this
test calls JobManager.submit() directly with owner_user_id set -- the
actual production code path, just invoked without the chat/LLM layer
around it, not a reimplementation of its adjacency.

Two parts:
  1. POSITIVE CONTROL -- reproduces the pre-fix ordering (submit, then
     record after an artificial delay) to prove the polling mechanism
     below can actually detect the race when it's really there. A test
     that never observes a 200 is only meaningful if it's also capable of
     observing one.
  2. FIX VERIFICATION -- submits a SECOND job via the real, fixed
     JobManager.submit(owner_user_id=...) call while a separate thread
     polls the job as a different user in as tight a loop as this host/
     network allows, starting before the job even exists and continuing
     through the whole submit call. GET /api/jobs/{job_id} only ever
     returns 200 to a non-owner while the job exists AND has no recorded
     owner (the exact SEC-07 window) -- both "doesn't exist yet" and
     "exists, owned by someone else" come back 404 (check_owner_or_admin's
     deliberate not-found-vs-forbidden design, see its own docstring), so
     "was a 200 ever observed" is an unambiguous yes/no signal for
     whether the window was hit.
"""
from __future__ import annotations

import subprocess
import sys
import threading
import time
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from fixtures import admin_client, check, cleanup_user, mint_invite, register, summary  # noqa: E402

COMPOSE_DIR = Path(__file__).resolve().parent.parent.parent
CONTROL_DELAY_SECONDS = 2
POLL_BUFFER_SECONDS = 0.5


def _exec_api(code: str) -> str:
    proc = subprocess.run(
        ["docker", "compose", "exec", "-T", "api", "python", "-c", code],
        cwd=str(COMPOSE_DIR), capture_output=True, text=True, timeout=60,
    )
    if proc.returncode != 0:
        print(proc.stderr, file=sys.stderr)
        raise RuntimeError(f"in-container exec failed: {proc.stderr[:500]}")
    return proc.stdout.strip()


def _submit_job_unowned(job_id: str) -> None:
    # os._exit(0) here too (see _submit_with_owner's docstring
    # below for why) -- otherwise this call doesn't return until the job
    # itself finishes, which would make "left unowned for
    # CONTROL_DELAY_SECONDS" inaccurate (the job could already be done
    # computing, though still correctly unowned, by the time this returns).
    code = f'''
import os
from app.chemistry.molecule import resolve_molecule
from app.chemistry.jobs.base import JobSpec, get_job_manager

m = resolve_molecule("water")
spec = JobSpec(
    job_id="{job_id}", method="single_point", engine="pyscf",
    molecule=m.to_dict(), params={{"method": "hf", "basis": "sto-3g"}},
)
get_job_manager().submit(spec)
os._exit(0)
'''
    _exec_api(code)


def _submit_with_owner(job_id: str, owner_user_id: str) -> float:
    """Calls the REAL fixed JobManager.submit() signature directly --
    ownership is recorded INSIDE that call now (app/chemistry/jobs/
    base.py), the instant the job's spec/status become visible, before its
    own quota-enforcement pass even runs. This is not a reimplementation
    of the fix's adjacency; it's the actual production code path
    submit_job (tools.py) itself calls, just invoked directly instead of
    through a full chat/LLM turn (see this suite's established precedent
    for why, in the module docstring above).

    Two test-harness pitfalls, both hit directly while writing this test
    (not assumed), both worth recording so a future test writer doesn't
    re-discover them the hard way:

    1. os._exit(0) at the end is required, not optional cleanup: a plain
       script exit here blocks `docker compose exec` until the submitted
       job's OWN background thread finishes, because JobManager.submit()
       dispatches via a concurrent.futures.ThreadPoolExecutor, whose
       atexit hook joins every worker thread (including this job's)
       before the interpreter exits -- see sec_08b_delete_user_running_
       job.py's own docstring, which hit this identical gotcha first.

    2. A "warm-up" call before the real, timed submit() is ALSO required,
       not just cleanup: enforce_quota() (called inside submit(), AFTER
       this fix's ownership-recording line but still inside the same
       call) lazily imports app.agent.graph on its first-ever use in a
       process, and that import alone costs ~3s in a genuinely fresh
       interpreter -- confirmed directly by timing it in isolation. The
       real, long-running server process already has that module resident
       (it's imported at startup, since the whole app depends on it), so
       it NEVER pays this cost when handling a real submit_job call -- but
       every one of this suite's one-shot `docker compose exec` processes
       starts genuinely cold and would pay it fresh, making a correctly-
       fast fix look like a multi-second regression for a reason that has
       nothing to do with whether the fix works. The throwaway warm-up
       submit() below (a different job_id, immediately cancelled, ignored)
       forces that import to happen before the REAL, measured/polled
       submit() runs, matching the real server's already-warm state.
    """
    code = f'''
import os, time
from app.chemistry.molecule import resolve_molecule
from app.chemistry.jobs.base import JobSpec, get_job_manager

m = resolve_molecule("water")
mgr = get_job_manager()

warmup_spec = JobSpec(method="single_point", engine="pyscf", molecule=m.to_dict(), params={{"method": "hf", "basis": "sto-3g"}})
warmup_id = mgr.submit(warmup_spec)
mgr.cancel(warmup_id)

spec = JobSpec(
    job_id="{job_id}", method="single_point", engine="pyscf",
    molecule=m.to_dict(), params={{"method": "hf", "basis": "sto-3g"}},
)
t0 = time.perf_counter()
mgr.submit(spec, owner_user_id="{owner_user_id}")
print(f"SUBMIT_MS={{(time.perf_counter() - t0) * 1000:.1f}}")
os._exit(0)
'''
    out = _exec_api(code)
    line = next((ln for ln in out.splitlines() if ln.startswith("SUBMIT_MS=")), "SUBMIT_MS=0")
    return float(line.split("=", 1)[1])


def _poll_for_200(client, job_id: str, stop_event: threading.Event) -> list[int]:
    codes = []
    while not stop_event.is_set():
        r = client.get(f"/api/jobs/{job_id}")
        codes.append(r.status_code)
    return codes


def main() -> None:
    admin = admin_client()
    token_a = mint_invite(admin)
    token_b = mint_invite(admin)
    client_a, user_a = register(token_a)
    client_b, user_b = register(token_b)

    # --- 1. Positive control: reproduce the pre-fix ordering -----------
    control_job_id = uuid.uuid4().hex[:12]
    _submit_job_unowned(control_job_id)
    print(f"[control] created job {control_job_id}, deliberately left unowned for {CONTROL_DELAY_SECONDS}s")

    recorder = threading.Thread(
        target=lambda: (time.sleep(CONTROL_DELAY_SECONDS),
                         _exec_api(f'from app.auth.models import record_ownership; '
                                    f'record_ownership("job", "{control_job_id}", "{user_a["id"]}")')),
    )
    recorder.start()
    r_during_window = client_b.get(f"/api/jobs/{control_job_id}")
    check(
        "CONTROL: an unowned job is reachable by a DIFFERENT user during a deliberately delayed record() "
        "-- proves the polling technique below can detect this race when it's really there",
        r_during_window.status_code == 200,
        f"got {r_during_window.status_code}",
    )
    recorder.join()
    time.sleep(0.5)
    r_after_window = client_b.get(f"/api/jobs/{control_job_id}")
    check("CONTROL: the same job is denied to user B once ownership is recorded",
          r_after_window.status_code == 404, f"got {r_after_window.status_code}")

    # --- 2. Fix verification: the real, immediate adjacency ------------
    fix_job_id = uuid.uuid4().hex[:12]
    stop_event = threading.Event()
    poll_results: list[int] = []
    poller = threading.Thread(
        target=lambda: poll_results.extend(_poll_for_200(client_b, fix_job_id, stop_event))
    )
    poller.start()
    time.sleep(0.1)  # let the poller get a few "doesn't exist yet" 404s in before we create it

    # submit_ms is the REAL submit(owner_user_id=...) call's own duration,
    # measured inside the (now warmed-up) in-container process itself --
    # not the wall time of this whole _exec_api round trip, which would
    # also include the deliberate warm-up submit()+cancel() beforehand
    # (see _submit_with_owner's own docstring for why that's needed and
    # why it must be excluded from this figure to mean anything).
    submit_ms = _submit_with_owner(fix_job_id, user_a["id"])

    time.sleep(POLL_BUFFER_SECONDS)
    stop_event.set()
    poller.join()

    n_200 = poll_results.count(200)
    print(f"[fix] job {fix_job_id}: JobManager.submit(owner_user_id=...) itself took {submit_ms:.1f}ms; "
          f"{len(poll_results)} polls from user B during and around the whole call (incl. warm-up), "
          f"{n_200} returned 200")
    check(
        "FIX VERIFIED: user B never observes the job as accessible (200) at any point around the real "
        "submit()-immediately-followed-by-record() adjacency the fix ships",
        n_200 == 0,
        f"{n_200}/{len(poll_results)} polls returned 200" + ("" if n_200 == 0 else " -- the window is still observable"),
    )

    r_owner_check = client_a.get(f"/api/jobs/{fix_job_id}")
    check("the actual owner (user A) can see the job once it's recorded", r_owner_check.status_code == 200)

    cleanup_user(admin, user_a["id"])
    cleanup_user(admin, user_b["id"])
    summary()


if __name__ == "__main__":
    main()
