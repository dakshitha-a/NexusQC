"""Fair-scheduler round-robin admission test (Phase 4, P4.5).

Confirms the starvation vector app/chemistry/jobs/scheduler.py exists to
close is actually closed: with the admin-configurable global concurrency
cap (max_concurrent_jobs_total) set to 1, one user's own burst of several
jobs must not occupy every admission slot ahead of a second user's single
job, submitted after the burst. Before the fair scheduler, JobManager
handed every submitted job straight to a ThreadPoolExecutor in submission
order, so user B's job would sit behind however many of user A's jobs
were submitted first, however unrelated the two users' work was. The fair
scheduler's per-owner FIFO + round-robin dispatcher should instead admit
B's job in the very next rotation after A's first, not after all of A's
remaining jobs.

Asserts the ADMISSION *ORDER* (the sequence in which job_ids first
transition out of "pending"), not wall-clock timing -- perf_03's own
history is that trying to reason about this from elapsed time alone is
unreliable on a host whose load varies. A trivial job also completes
faster than polling can reliably observe intermediate states at all (see
perf_03's own module docstring), so this uses the same real, genuinely
slow ORCA CASSCF(4,4)/STO-3G probe perf_03 already established takes
~15s wall-clock here -- long enough to poll reliably, and correct (its
energy matches PySCF's own CASSCF to 1.7e-8 Ha, confirmed while writing
perf_03). Each job is cancelled the instant its admission is observed
(rather than left to run to completion) so the whole test only pays for
one admission's worth of ORCA startup at a time, not six full CASSCF
runs serialized behind a cap of 1.

Everything below -- both users' submissions, the observation poll, and
every cancellation -- runs in ONE in-container process, for the same
reason perf_03's own module docstring gives at length: JobManager.submit()
now enqueues into that process's own single JobScheduler instance, whose
ONE dispatcher thread is what re-evaluates every queued job's admission
each tick. Killing the submitting process early would kill that
dispatcher along with it, stranding every job still queued behind the cap
in "pending" forever -- not just the one this test happens to be watching.

Also confirms the structural property the round-robin fix depends on:
while 5 of user A's 6 jobs sit queued behind the cap, JobManager holds no
thread-pool Future for any of them -- `len(mgr._futures)` matches the
number of jobs actually ADMITTED so far, never the number submitted. That
is what "only admitted jobs enter the executor" (scheduler.py's own
docstring) means concretely, and is exactly the property whose absence
was the starvation vector: a burst submission used to occupy a Future/
worker-thread slot per job the instant it was submitted, not once it was
actually allowed to run.
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
N_USER_A_JOBS = 6
OBSERVE_TIMEOUT_SECONDS = 180


def _exec_api(code: str, timeout: int = 220) -> str:
    proc = subprocess.run(
        ["docker", "compose", "exec", "-T", "api", "python", "-c", code],
        cwd=str(COMPOSE_DIR), capture_output=True, text=True, timeout=timeout,
    )
    if proc.returncode != 0:
        print(proc.stderr, file=sys.stderr)
        raise RuntimeError(f"in-container exec failed: {proc.stderr[:500]}")
    return proc.stdout.strip()


def main() -> None:
    admin = admin_client()
    token_a = mint_invite(admin)
    _client_a, user_a = register(token_a)
    token_b = mint_invite(admin)
    _client_b, user_b = register(token_b)

    r_cfg = admin.get("/api/admin/config")
    original_cap = r_cfg.json()["max_concurrent_jobs_total"]

    try:
        r_patch = admin.patch("/api/admin/config", json={"key": "max_concurrent_jobs_total", "value": 1})
        check("admin sets max_concurrent_jobs_total=1", r_patch.status_code == 200, str(r_patch.status_code))

        code = f'''
import json, time
from app.chemistry.molecule import resolve_molecule
from app.chemistry.jobs.base import JobSpec, get_job_manager

mgr = get_job_manager()
m = resolve_molecule("water")

def submit(owner):
    return mgr.submit(
        JobSpec(task="single_point", subtype="gs", method="casscf", engine="orca",
                molecule=m.to_dict(), params={CASSCF_PARAMS!r}),
        owner_user_id=owner,
    )

a_ids = [submit("{user_a["id"]}") for _ in range({N_USER_A_JOBS})]
b_id = submit("{user_b["id"]}")
label = {{}}
for jid in a_ids:
    label[jid] = "A"
label[b_id] = "B"
all_ids = a_ids + [b_id]

# Structural check, taken BEFORE any admission is observed below: with
# the cap at 1, at most one of these {N_USER_A_JOBS + 1} just-submitted
# jobs may hold a thread-pool Future -- the rest are queued in the
# scheduler's own in-memory deques, not in self._futures/self._executor.
futures_at_submit_time = len(mgr._futures)

admission_order = []
seen = set()
deadline = time.time() + {OBSERVE_TIMEOUT_SECONDS}
while time.time() < deadline and len(seen) < len(all_ids):
    for jid in all_ids:
        if jid in seen:
            continue
        st = mgr.status(jid)["status"]
        if st == "running":
            seen.add(jid)
            admission_order.append(jid)
            mgr.cancel(jid)  # free the cap slot immediately -- only admission order matters here
        elif st in ("completed", "failed", "cancelled"):
            # Finished/died before we observed it running (shouldn't happen at cap=1
            # with a ~15s job, but don't hang forever if it does).
            seen.add(jid)
            admission_order.append(jid)
    time.sleep(0.3)

# Belt-and-braces: make sure nothing is left pending/running after the observation
# window, regardless of what was seen above.
for jid in all_ids:
    mgr.cancel(jid)

print(json.dumps({{
    "futures_at_submit_time": futures_at_submit_time,
    "admission_order": [label[j] for j in admission_order],
    "n_observed": len(admission_order),
}}))
'''
        out = _exec_api(code)
        result = json.loads(out.splitlines()[-1])
        order = result["admission_order"]
        print(f"admission order: {order}")
        print(f"Futures held at submit time (cap=1, {N_USER_A_JOBS + 1} jobs just submitted): "
              f"{result['futures_at_submit_time']}")

        check(
            "all jobs were eventually observed admitted (none stuck pending forever)",
            result["n_observed"] == N_USER_A_JOBS + 1,
            f"observed {result['n_observed']} of {N_USER_A_JOBS + 1}",
        )
        check(
            "only admitted jobs hold a thread-pool Future -- a burst submission under a cap of 1 "
            "holds at most 1, not one per submitted job",
            result["futures_at_submit_time"] <= 1,
            f"futures_at_submit_time={result['futures_at_submit_time']} -- more than 1 Future existed "
            f"immediately after submitting {N_USER_A_JOBS + 1} jobs under a global cap of 1, meaning "
            "queued jobs are still occupying worker-pool slots rather than sitting in the scheduler's "
            "own queue",
        )
        check(
            "user A's own burst does not occupy every admission ahead of user B",
            len(order) >= 2 and order[1] == "B",
            f"order={order} -- user B's single job should be admitted in the very next rotation after "
            "user A's first (round-robin: A, then B, then back to A), not after all of A's remaining jobs",
        )
        check(
            "admission interleaves both users rather than draining user A's queue first",
            order[:2] == ["A", "B"] if len(order) >= 2 else False,
            f"order={order}",
        )
    finally:
        admin.patch("/api/admin/config", json={"key": "max_concurrent_jobs_total", "value": original_cap})
        cleanup_user(admin, user_a["id"])
        cleanup_user(admin, user_b["id"])

    summary()


if __name__ == "__main__":
    main()
