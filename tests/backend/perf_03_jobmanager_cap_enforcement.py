"""Concurrency+admin-config interaction test (folded into the perf group
per the plan): confirms the admin-configurable max_concurrent_jobs_per_user
cap (app/chemistry/jobs/base.py's _concurrent_jobs_block_reason) is
actually enforced in real time against a live admin PATCH, not just
accepted and ignored.

Originally inconclusive on this host: a trivial PySCF single_point/
frequency job (even water/ammonia HF/6-31g frequency) completes faster
than a few seconds' worth of polling can reliably observe a `pending`
state at all -- confirmed directly (both jobs came back "completed" well
inside a 3s observation window).

Fixed by submitting genuinely slow jobs instead: a water CASSCF(4,4)/
STO-3G run via ORCA (confirmed to take ~15s wall-clock on this host,
correct -- its energy matches PySCF's own CASSCF to 1.7e-8 Ha, checked
while diagnosing an unrelated container MPI/library gap this same probe
surfaced -- see Dockerfile/app/config.py's BAGEL_EXTRA_LIB_DIRS notes) and
the same system via BAGEL (confirmed to take minutes on this host -- see
CLAUDE.md's own note on BAGEL/MKL being abnormally slow here -- so a
BAGEL run comfortably outlasts the whole observation window without
needing to reach convergence). Both engines are exercised as two
independent sub-tests sharing the same cap-enforcement assertion, run
sequentially (not concurrently with each other) to keep the failure
signal for either engine unambiguous.

Both jobs, for one engine, are submitted AND observed AND cancelled from
inside ONE single in-container process, not split across several
`docker compose exec` calls -- a real, previously-hit gotcha while
writing this test explains why, and Phase 4's fair scheduler
(app/chemistry/jobs/scheduler.py) makes the reasoning apply even more
directly than it used to. JobManager.submit() now enqueues each job into
that process's own single JobScheduler instance (one per JobManager,
constructed once at first get_job_manager() call) rather than dispatching
straight to a worker thread; a cap-blocked job's eventual
"pending -> running" promotion is driven by that scheduler's ONE
dispatcher thread re-evaluating the block reason each tick, not by a
per-job retry loop. If the submitting process were killed early (e.g. via
os._exit(), the technique sec_07/sec_08b's tests use to dodge
ThreadPoolExecutor's atexit-join stall) while job2 was still legitimately
pending behind the cap, that dispatcher thread -- and with it, admission
for every job in the process, not just this one -- would die with it,
permanently stranding job2 in "pending". Confirmed directly under the
pre-scheduler design (the underlying failure mode is unchanged by the
rewrite): an earlier version of this test that submitted job1 and job2 as
two SEPARATE one-shot processes (each os._exit()-ing right after
submit()) left one of the two jobs marked "failed" with a misleading "the
server restarted" message, because the next process's own fresh
JobManager reconciled it as an orphan with no live worker, not because
anything about the cap logic itself was wrong. Submitting, polling, and
cancelling both jobs from ONE process that exits normally (safe by then,
since both jobs are already cancelled/terminal) sidesteps this entirely
and matches how JobManager is actually used in the real, single
long-lived server process.

Sets the cap to 1 via PATCH /api/admin/config, submits two jobs pre-owned
by the same user (ownership passed straight into submit(), the same
owner_user_id parameter SEC-07's fix added -- not the real approve_job
flow's own resolution, which is a separate concern), and confirms the
second job's status.json reports the per-user-cap pending reason while
the first is still running. Restores the original cap afterward
regardless of outcome.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from fixtures import admin_client, check, cleanup_user, mint_invite, register, summary  # noqa: E402

COMPOSE_DIR = Path(__file__).resolve().parent.parent.parent
CASSCF_PARAMS = {"active_electrons": 4, "active_orbitals": 4, "basis": "sto-3g", "n_states": 1, "weights": [1.0]}
POLL_TIMEOUT_SECONDS = 30


def _exec_api(code: str, timeout: int = 90) -> str:
    proc = subprocess.run(
        ["docker", "compose", "exec", "-T", "api", "python", "-c", code],
        cwd=str(COMPOSE_DIR), capture_output=True, text=True, timeout=timeout,
    )
    if proc.returncode != 0:
        print(proc.stderr, file=sys.stderr)
        raise RuntimeError(f"in-container exec failed: {proc.stderr[:500]}")
    return proc.stdout.strip()


def _run_cap_check(engine: str, owner_user_id: str) -> None:
    # Everything below -- both submissions, the observation poll, and both
    # cancellations -- runs in ONE in-container process. See module
    # docstring for why splitting this across processes (or killing this
    # one early) breaks the cap-blocked job's own promotion loop.
    code = f'''
import json, time
from app.chemistry.molecule import resolve_molecule
from app.chemistry.jobs.base import JobSpec, get_job_manager

mgr = get_job_manager()
m = resolve_molecule("water")
job1 = mgr.submit(
    JobSpec(task="single_point", subtype="gs", method="casscf", engine="{engine}",
            molecule=m.to_dict(), params={CASSCF_PARAMS!r}),
    owner_user_id="{owner_user_id}",
)
job2 = mgr.submit(
    JobSpec(task="single_point", subtype="gs", method="casscf", engine="{engine}",
            molecule=m.to_dict(), params={CASSCF_PARAMS!r}),
    owner_user_id="{owner_user_id}",
)

deadline = time.time() + {POLL_TIMEOUT_SECONDS}
s1 = s2 = None
while time.time() < deadline:
    s1, s2 = mgr.status(job1), mgr.status(job2)
    statuses = {{s1["status"], s2["status"]}}
    pending_status = s2 if s2["status"] == "pending" else s1
    # "queued" is submit()'s own initial placeholder message, written
    # before the scheduler's dispatcher thread has evaluated this job even
    # once -- keep polling past a bare running/pending split until the
    # pending job's message has actually been updated by that check (it
    # always writes SOME reason,
    # per-user-cap or generic CPU/mem headroom), so a genuinely fast
    # observation doesn't get mistaken for "no reason was ever given".
    if (statuses <= {{"running", "pending"}} and len(statuses) > 1
            and pending_status["message"] != "queued"):
        break  # stable running/pending split, with a real block reason
    if "completed" in statuses or "failed" in statuses:
        break  # something finished/failed before a split was observed
    time.sleep(0.3)

print(json.dumps({{"job1": s1, "job2": s2}}))
mgr.cancel(job1)
mgr.cancel(job2)
'''
    out = _exec_api(code)
    result = json.loads(out.splitlines()[-1])
    s1, s2 = result["job1"], result["job2"]
    print(f"[{engine}] job1 status: {s1}")
    print(f"[{engine}] job2 status: {s2}")

    check(
        f"[{engine}] neither job finished within the observation window (job too fast to test the cap with)",
        s1["status"] != "completed" and s2["status"] != "completed",
        f"job1={s1['status']!r} job2={s2['status']!r} -- if either is already 'completed', this engine's "
        "CASSCF probe is no longer slow enough on this host and needs a heavier system",
    )
    one_running_one_pending = {s1["status"], s2["status"]} <= {"running", "pending"} and (
        "pending" in (s1["status"], s2["status"])
    )
    check(
        f"[{engine}] with the per-user cap set to 1, the second job is held pending while the first runs",
        one_running_one_pending,
        f"job1={s1['status']!r} job2={s2['status']!r} -- if both went straight to running, "
        "the per-user cap was not enforced",
    )
    pending_msg = s2["message"] if s2["status"] == "pending" else s1["message"]
    check(
        f"[{engine}] the pending job's status message cites the per-user cap, not just generic CPU/memory headroom",
        "running" in pending_msg and ("slot" in pending_msg or "per_user" in pending_msg or "you have" in pending_msg),
        pending_msg,
    )


def main() -> None:
    admin = admin_client()
    token = mint_invite(admin)
    _c, user = register(token)

    r_cfg = admin.get("/api/admin/config")
    original_cap = r_cfg.json()["max_concurrent_jobs_per_user"]

    try:
        r_patch = admin.patch("/api/admin/config", json={"key": "max_concurrent_jobs_per_user", "value": 1})
        check("admin sets max_concurrent_jobs_per_user=1", r_patch.status_code == 200, str(r_patch.status_code))

        _run_cap_check("orca", user["id"])
        _run_cap_check("bagel", user["id"])
    finally:
        admin.patch("/api/admin/config", json={"key": "max_concurrent_jobs_per_user", "value": original_cap})
        cleanup_user(admin, user["id"])

    summary()


if __name__ == "__main__":
    main()
