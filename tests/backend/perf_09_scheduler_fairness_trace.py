"""R-098: is the fair scheduler's round-robin wrong, or is perf_04 racing itself?

    QC_AGENT_TEST_BASE_URL=https://127.0.0.1:8444 \\
      PYTHONPATH=$PWD python3 tests/backend/perf_09_scheduler_fairness_trace.py

WHAT THE REVIEW SAW, AND WHY IT WAS NOT ENOUGH TO ACT ON
--------------------------------------------------------
`tests/backend/perf_04_fair_scheduling.py` sets the global concurrency cap to
1, submits six jobs as user A and then one as user B, and records the order in
which the scheduler admits them. The fair scheduler exists so that B's single
job is admitted in the rotation right after A's first, that is `A, B, A, A,
...`. The review got `A, A, B, A, A, A, A` twice, once inside a full suite run
and once on a stack confirmed idle, byte-identical both times.

That is two readings of the same wrong-looking order and still not a diagnosis,
because two very different things produce it:

CODE. B is queued before A's second admission and the dispatcher admits A twice
anyway. That is a real round-robin defect, and on a shared lab machine it is
the starvation this module was written to remove.

HARNESS. B is not queued yet when A's second admission happens. The test
submits all seven jobs in a plain loop with nothing synchronising it against
the dispatcher thread, so if A's first job is admitted and released before the
seventh `submit()` call returns, the scheduler is behaving perfectly and the
test is describing a race in itself.

Nothing in `admission_order` alone can tell those apart, which is why R-098's
`cause:` line says "CODE or HARNESS, undetermined" and names this experiment
as the thing that has to run first.

WHAT THIS SCRIPT MEASURES
-------------------------
The same submission shape as perf_04, with two spies added, both installed on
the scheduler instance inside the api container and both removed afterwards:

- `enqueue` is wrapped to record a monotonic timestamp for every job the
  moment it enters its owner's queue. This is the fact perf_04 never recorded
  and the one the whole question turns on.
- `_on_admit` is wrapped to record a timestamp plus the scheduler's own state
  at that instant: the live `_order` list of owners, `_rr_pos` (already
  advanced past the admitted owner by the time `_on_admit` runs), and the size
  of `_in_flight`.

The two timelines are then interleaved into one wall-ordered event log, which
is what gets printed, and the verdict is read off it mechanically:

    B enqueued BEFORE A's second admission, and admitted third  -> CODE
    B enqueued AFTER  A's second admission                      -> HARNESS

Three runs, because one run of a race proves nothing. A mixed result is itself
informative and is reported as such rather than averaged away.

The probe job is the same ORCA CASSCF(4,4)/STO-3G on water that perf_03 and
perf_04 use: real, correct, and slow enough (about 15 s here) that admissions
are separable in time. Every job is cancelled as soon as its admission is
observed, so the run costs one ORCA start-up at a time rather than seven full
calculations, and every job is cancelled again at the end whatever happened.

Everything runs in ONE process inside the api container, for the reason
perf_04's docstring gives at length: the dispatcher thread that admits these
jobs belongs to that process, and killing the submitter would strand every
job still queued behind the cap.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from fixtures import admin_client, check, cleanup_user, mint_invite, register, summary  # noqa: E402

COMPOSE_DIR = Path(__file__).resolve().parent.parent.parent
CASSCF_PARAMS = {"active_electrons": 4, "active_orbitals": 4, "basis": "sto-3g",
                 "n_states": 1, "weights": [1.0]}
N_USER_A_JOBS = 6
OBSERVE_TIMEOUT_SECONDS = 180
N_RUNS = 3


def _exec_api(code: str, timeout: int = 260) -> str:
    proc = subprocess.run(
        ["docker", "compose", "exec", "-T", "api", "python", "-c", code],
        cwd=str(COMPOSE_DIR), capture_output=True, text=True, timeout=timeout,
    )
    if proc.returncode != 0:
        print(proc.stderr, file=sys.stderr)
        raise RuntimeError(f"in-container exec failed: {proc.stderr[:500]}")
    return proc.stdout.strip()


def _probe_code(uid_a: str, uid_b: str) -> str:
    return f'''
import json, time
from app.chemistry.molecule import resolve_molecule
from app.chemistry.jobs.base import JobSpec, get_job_manager

mgr = get_job_manager()
sched = mgr._scheduler
m = resolve_molecule("water")

t0 = time.monotonic()
events = []

_real_enqueue = sched.enqueue
_real_admit = sched._on_admit


def _spy_enqueue(job_id, owner):
    # Two timestamps, because the answer turns on an ordering and the honest
    # thing is to bound it from both sides: t is taken before the real call,
    # t_done after it returns. The classification below uses t_done, the
    # instant the job is CERTAINLY in its owner's queue, so a borderline case
    # is read in favour of the scheduler rather than against it.
    t_before = time.monotonic() - t0
    r = _real_enqueue(job_id, owner)
    with sched._lock:
        order = list(sched._order)
    events.append({{"kind": "enqueue", "t": t_before,
                   "t_done": time.monotonic() - t0,
                   "job_id": job_id, "order": order}})
    return r


def _spy_admit(job_id):
    with sched._lock:
        order = list(sched._order)
        in_flight = len(sched._in_flight)
    events.append({{"kind": "admit", "t": time.monotonic() - t0,
                   "job_id": job_id, "order": order,
                   "rr_pos": sched._rr_pos, "in_flight": in_flight}})
    return _real_admit(job_id)


sched.enqueue = _spy_enqueue
sched._on_admit = _spy_admit


def submit(owner):
    return mgr.submit(
        JobSpec(task="single_point", subtype="gs", method="casscf", engine="orca",
                molecule=m.to_dict(), params={CASSCF_PARAMS!r}),
        owner_user_id=owner,
    )


try:
    a_ids = [submit("{uid_a}") for _ in range({N_USER_A_JOBS})]
    b_id = submit("{uid_b}")
    label = {{}}
    for jid in a_ids:
        label[jid] = "A"
    label[b_id] = "B"
    all_ids = a_ids + [b_id]

    seen = set()
    deadline = time.time() + {OBSERVE_TIMEOUT_SECONDS}
    while time.time() < deadline and len(seen) < len(all_ids):
        for jid in all_ids:
            if jid in seen:
                continue
            st = mgr.status(jid)["status"]
            if st == "running":
                seen.add(jid)
                mgr.cancel(jid)
            elif st in ("completed", "failed", "cancelled"):
                seen.add(jid)
        time.sleep(0.3)

    for jid in all_ids:
        mgr.cancel(jid)
finally:
    sched.enqueue = _real_enqueue
    sched._on_admit = _real_admit

for e in events:
    e["who"] = label.get(e["job_id"], "?")

print(json.dumps({{
    "events": events,
    "job_ids": all_ids,
}}))
'''


def _classify(events: list[dict]) -> tuple[str, str, list[str]]:
    """Reads the verdict off the interleaved timeline.

    Returns (verdict, explanation, admission_order)."""
    admits = [e for e in events if e["kind"] == "admit"]
    order = [e["who"] for e in admits]
    b_enq = next((e for e in events if e["kind"] == "enqueue" and e["who"] == "B"), None)
    a_admits = [e for e in admits if e["who"] == "A"]

    if b_enq is None:
        return "INCONCLUSIVE", "user B's job was never enqueued at all", order
    if len(a_admits) < 2:
        return "INCONCLUSIVE", "user A was admitted fewer than twice, so there is no second admission to compare against", order

    a2 = a_admits[1]
    b_admits = [e for e in admits if e["who"] == "B"]
    b_position = order.index("B") + 1 if "B" in order else None

    b_t = b_enq.get("t_done", b_enq["t"])
    if b_t > a2["t"]:
        return ("HARNESS",
                f"user B's job was enqueued at t={b_t:.3f}s, which is AFTER "
                f"user A's second admission at t={a2['t']:.3f}s. At the moment the "
                f"scheduler chose A a second time, B had nothing queued, so there "
                f"was no other owner to rotate to and the round robin had no "
                f"opportunity to be unfair. The submissions are not synchronised "
                f"against the dispatcher thread, which is the race.",
                order)
    if b_position is not None and b_position <= 2:
        return ("FAIR",
                f"user B's job was enqueued at t={b_t:.3f}s, before A's second "
                f"admission at t={a2['t']:.3f}s, and B was admitted in position "
                f"{b_position}. That is the rotation working.",
                order)
    if not b_admits:
        return ("CODE",
                f"user B's job was enqueued at t={b_t:.3f}s, before A's second "
                f"admission at t={a2['t']:.3f}s, and was never admitted at all inside "
                f"the observation window.",
                order)
    return ("CODE",
            f"user B's job was enqueued at t={b_t:.3f}s, before A's second "
            f"admission at t={a2['t']:.3f}s, and was still admitted only in position "
            f"{b_position}. The scheduler had both owners queued and chose A twice, "
            f"which is the round-robin defect.",
            order)


def _print_timeline(events: list[dict]) -> None:
    print("    t(s)   event    owner  rr_pos  in_flight  order")
    for e in events:
        if e["kind"] == "enqueue":
            print(f"    {e['t']:6.3f}  enqueue  {e['who']:5s}  {'':6s}  {'':9s}  {e['order']}")
        else:
            print(f"    {e['t']:6.3f}  ADMIT    {e['who']:5s}  {e['rr_pos']:6d}  "
                  f"{e['in_flight']:9d}  {e['order']}")


def main() -> None:
    admin = admin_client()
    token_a = mint_invite(admin)
    _client_a, user_a = register(token_a)
    token_b = mint_invite(admin)
    _client_b, user_b = register(token_b)

    r_cfg = admin.get("/api/admin/config")
    original_cap = r_cfg.json()["max_concurrent_jobs_total"]

    verdicts: list[str] = []
    created_job_ids: list[str] = []
    try:
        r_patch = admin.patch("/api/admin/config",
                              json={"key": "max_concurrent_jobs_total", "value": 1})
        check("admin sets max_concurrent_jobs_total=1", r_patch.status_code == 200,
              str(r_patch.status_code))

        for run in range(1, N_RUNS + 1):
            print(f"\n=== run {run} of {N_RUNS} ===")
            out = _exec_api(_probe_code(user_a["id"], user_b["id"]))
            result = json.loads(out.splitlines()[-1])
            created_job_ids.extend(result["job_ids"])
            events = result["events"]
            _print_timeline(events)
            verdict, why, order = _classify(events)
            verdicts.append(verdict)
            print(f"    admission order: {order}")
            print(f"    verdict: {verdict}")
            print(f"    {why}")

        unique = sorted(set(verdicts))
        print(f"\nRESULT R-098 over {N_RUNS} runs: {verdicts}")
        check(
            "the three runs agree on one cause, so the classification is not itself a coin flip",
            len(unique) == 1,
            f"verdicts were {verdicts}",
        )
        check(
            "the round robin does not admit one owner twice while another owner's job is already queued "
            "(a CODE verdict here is a real starvation defect and must be fixed, not recorded)",
            "CODE" not in verdicts,
            f"verdicts were {verdicts}",
        )
    finally:
        admin.patch("/api/admin/config",
                    json={"key": "max_concurrent_jobs_total", "value": original_cap})
        for jid in created_job_ids:
            try:
                admin.delete(f"/api/jobs/{jid}")
            except Exception:  # noqa: BLE001
                pass
        cleanup_user(admin, user_a["id"])
        cleanup_user(admin, user_b["id"])

    summary()


if __name__ == "__main__":
    main()
