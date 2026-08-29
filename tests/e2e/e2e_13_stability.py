"""Resource gating, cancellation, and orphan reconciliation.

Everything here needs to OBSERVE A TRANSIENT, which is why it uses the
slow ORCA CASSCF(4,4)/STO-3G probe rather than the water/HF/STO-3G probe
the rest of the suite uses. A trivial PySCF job reaches "completed"
before a polling loop can see it pending -- that is precisely why PERF-03
was originally inconclusive.

Two process-scoping rules are inherited from this repo's own hard-won
experience and must not be "simplified":

  * JobManager tracks a job's live Popen in a dict scoped to the process
    that called submit(). A cap-blocked job's pending->running promotion
    runs on THAT process's ThreadPoolExecutor worker. Submitting from one
    short-lived `docker compose exec` and observing from another strands
    the job and produces a misleading "failed".  So each in-container
    sub-test submits, observes, and cancels from ONE process.
  * The api process is PID 1 of its container (entrypoint.sh's exec), so
    `docker compose restart api` tears down the whole PID namespace
    INCLUDING detached workers. That cannot test "the job survives a
    restart". What it CAN test -- and what this script asserts -- is that
    _reconcile_orphaned_jobs() correctly classifies a job left `running`
    on disk with no live worker, instead of leaving it stuck forever.

Sub-tests:
  S1  per-user concurrency cap reports the CAP reason, not generic
      CPU/memory headroom text
  S2  the cap is per-user: another user is not blocked by it
  S3  cancel kills the real subprocess and reaches "cancelled"
  S4  orphan reconciliation after an api restart
"""
from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from fixtures import admin_client, check, cleanup_user, mint_invite, register, summary  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _agent import record  # noqa: E402

REPO = Path(__file__).resolve().parent.parent.parent
CAS = {"basis": "sto-3g", "active_electrons": 4, "active_orbitals": 4, "n_excited_states": 0}


def api_py(code: str, timeout: int = 600) -> str:
    p = subprocess.run(
        ["docker", "compose", "exec", "-T", "api", "python", "-c", code],
        cwd=str(REPO), capture_output=True, text=True, timeout=timeout,
    )
    if p.returncode != 0:
        raise RuntimeError(f"exec failed:\n{p.stdout[-800:]}\n{p.stderr[-800:]}")
    return p.stdout


def marker(out: str) -> dict:
    for line in out.splitlines():
        if line.startswith("@@@"):
            return json.loads(line[3:])
    raise RuntimeError(f"no marker in output: {out[-600:]}")


def set_cap(admin, key, value):
    r = admin.patch("/api/admin/config", json={"key": key, "value": value})
    r.raise_for_status()
    return r.json()


def main() -> None:
    admin = admin_client()
    cfg = admin.get("/api/admin/config").json()
    orig_per_user = cfg.get("max_concurrent_jobs_per_user")
    print(f"original max_concurrent_jobs_per_user = {orig_per_user}\n")

    tok = mint_invite(admin, "user")
    user, info = register(tok)
    uid = str((info.get("user") or info).get("id"))

    try:
        # ------------------------------------------------------------ S1
        print("=== S1: per-user concurrency cap (slow ORCA CASSCF probe) ===\n")
        set_cap(admin, "max_concurrent_jobs_per_user", 1)

        code = f'''
import json, time
from app.chemistry.molecule import resolve_molecule
from app.chemistry.jobs.base import JobSpec, get_job_manager, read_status
m = resolve_molecule("water").to_dict()
mgr = get_job_manager()
def mk():
    return JobSpec(method="casscf", engine="orca", molecule=m, params={json.dumps(CAS)})
j1 = mgr.submit(mk(), owner_user_id="{uid}")
time.sleep(3)
j2 = mgr.submit(mk(), owner_user_id="{uid}")
out = {{"j1": j1, "j2": j2}}
# watch for job2 to report WHY it is waiting
# submit() writes a generic "queued" placeholder immediately, and
# _wait_for_resources only overwrites it with the SPECIFIC reason on its
# next poll -- so breaking on the first non-empty message reads the
# placeholder and reports no cap. Skip it and keep waiting for a real one.
reason = ""
for _ in range(40):
    s2 = read_status(j2) or {{}}
    if s2.get("status") == "pending":
        msg = s2.get("message") or ""
        if msg and msg != "queued":
            reason = msg
            break
    if s2.get("status") == "running":
        break
    time.sleep(1)
out["j1_status"] = (read_status(j1) or {{}}).get("status")
out["j2_status"] = (read_status(j2) or {{}}).get("status")
out["j2_reason"] = reason
for j in (j1, j2):
    try: mgr.cancel(j)
    except Exception as e: out.setdefault("cancel_err", str(e))
# cancel() kills the worker's process group and returns; the TERMINAL
# STATUS is written afterwards by the manager's own watcher thread once it
# notices the exit. Reading status.json immediately therefore still shows
# "running" -- which is what this check saw, and what the original
# pre-fix run recorded too. Same lag purge_user_data's
# _cancel_and_await_terminal exists for. Wait for it rather than racing it.
_TERMINAL = ("completed", "failed", "cancelled")
deadline = time.time() + 30
while time.time() < deadline:
    if all((read_status(j) or {{}}).get("status") in _TERMINAL for j in (j1, j2)):
        break
    time.sleep(1)
out["j1_final"] = (read_status(j1) or {{}}).get("status")
out["j2_final"] = (read_status(j2) or {{}}).get("status")
print("@@@" + json.dumps(out))
'''
        res = marker(api_py(code, timeout=900))
        print(f"    j1={res['j1']} {res['j1_status']} | j2={res['j2']} {res['j2_status']}")
        print(f"    j2 reason: {res['j2_reason']!r}")
        check("S1a the second job was held pending while the first ran",
              res["j2_status"] == "pending" and res["j1_status"] == "running",
              f"j1={res['j1_status']} j2={res['j2_status']}")
        reason = (res.get("j2_reason") or "").lower()
        check("S1b the pending reason names the PER-USER JOB SLOT cap, not "
              "generic CPU/memory headroom",
              "slot" in reason or "you have" in reason,
              f"reason={res.get('j2_reason')!r}")
        check("S1c cancel() reached both jobs and drove them terminal",
              res["j1_final"] in ("cancelled", "completed", "failed")
              and res["j2_final"] in ("cancelled", "completed", "failed"),
              f"{res['j1_final']} / {res['j2_final']}")
        record("S1", "PASS" if "slot" in reason or "you have" in reason else "FAIL", **res)

        # ------------------------------------------------------------ S2
        print("\n=== S2: the cap is PER USER, not global ===\n")
        tok2 = mint_invite(admin, "user")
        user2, info2 = register(tok2)
        uid2 = str((info2.get("user") or info2).get("id"))
        code2 = f'''
import json, time
from app.chemistry.molecule import resolve_molecule
from app.chemistry.jobs.base import JobSpec, get_job_manager, read_status
m = resolve_molecule("water").to_dict()
mgr = get_job_manager()
def mk():
    return JobSpec(method="casscf", engine="orca", molecule=m, params={json.dumps(CAS)})
a = mgr.submit(mk(), owner_user_id="{uid}")
time.sleep(3)
b = mgr.submit(mk(), owner_user_id="{uid2}")
time.sleep(6)
out = {{"a": a, "b": b,
       "a_status": (read_status(a) or {{}}).get("status"),
       "b_status": (read_status(b) or {{}}).get("status"),
       "b_reason": (read_status(b) or {{}}).get("message")}}
for j in (a, b):
    try: mgr.cancel(j)
    except Exception: pass
print("@@@" + json.dumps(out))
'''
        res2 = marker(api_py(code2, timeout=900))
        print(f"    userA job {res2['a']} -> {res2['a_status']}")
        print(f"    userB job {res2['b']} -> {res2['b_status']} ({res2.get('b_reason')!r})")
        check("S2 a DIFFERENT user's job is not blocked by user A's per-user cap",
              res2["b_status"] == "running",
              f"userB job is {res2['b_status']}: {res2.get('b_reason')!r}")
        record("S2", "PASS" if res2["b_status"] == "running" else "FAIL", **res2)
        cleanup_user(admin, uid2)

        # ------------------------------------------------------------ S3
        print("\n=== S3: cancel actually kills the subprocess ===\n")
        code3 = f'''
import json, os, time
import psutil
from app.chemistry.molecule import resolve_molecule
from app.chemistry.jobs.base import JobSpec, get_job_manager, read_status, read_meta
m = resolve_molecule("water").to_dict()
mgr = get_job_manager()
j = mgr.submit(JobSpec(method="casscf", engine="orca", molecule=m,
                       params={json.dumps(CAS)}), owner_user_id="{uid}")
for _ in range(30):
    if (read_status(j) or {{}}).get("status") == "running":
        break
    time.sleep(1)
meta = read_meta(j) or {{}}
pid = meta.get("worker_pid")
alive_before = psutil.pid_exists(pid) if pid else None
t0 = time.time()
mgr.cancel(j)
elapsed = time.time() - t0
time.sleep(2)
alive_after = psutil.pid_exists(pid) if pid else None
print("@@@" + json.dumps({{"job": j, "pid": pid, "alive_before": alive_before,
                          "alive_after": alive_after, "cancel_seconds": round(elapsed,2),
                          "final": (read_status(j) or {{}}).get("status")}}))
'''
        res3 = marker(api_py(code3, timeout=900))
        print(f"    job {res3['job']} pid={res3['pid']} alive before/after cancel: "
              f"{res3['alive_before']}/{res3['alive_after']} in {res3['cancel_seconds']}s")
        check("S3a the worker subprocess was genuinely alive before cancel",
              res3["alive_before"] is True, str(res3))
        check("S3b cancel() left no surviving worker process",
              res3["alive_after"] is False, str(res3))
        check("S3c the job's status reached 'cancelled'",
              res3["final"] == "cancelled", f"final={res3['final']}")
        record("S3", "PASS" if res3["final"] == "cancelled" else "FAIL", **res3)

        # ------------------------------------------------------------ S4
        print("\n=== S4: orphan reconciliation after an api restart ===\n")
        print("    (the api is PID 1 of its container, so a restart also kills")
        print("     the detached worker -- what is asserted is that the job is")
        print("     CLASSIFIED, not that it survives)")
        code4 = f'''
import json, os, time
from app.chemistry.molecule import resolve_molecule
from app.chemistry.jobs.base import JobSpec, get_job_manager, read_status
m = resolve_molecule("water").to_dict()
mgr = get_job_manager()
j = mgr.submit(JobSpec(method="casscf", engine="orca", molecule=m,
                       params={json.dumps(CAS)}), owner_user_id="{uid}")
for _ in range(30):
    if (read_status(j) or {{}}).get("status") == "running":
        break
    time.sleep(1)
print("@@@" + json.dumps({{"job": j, "status": (read_status(j) or {{}}).get("status")}}))
os._exit(0)
'''
        res4 = marker(api_py(code4, timeout=600))
        orphan = res4["job"]
        check("S4a a job was left running on disk before the restart",
              res4["status"] == "running", f"status={res4['status']}")

        subprocess.run(["docker", "compose", "restart", "api"],
                       cwd=str(REPO), capture_output=True, timeout=180)
        # wait for the api to answer again
        for _ in range(60):
            try:
                if admin.get("/api/health", timeout=5).status_code == 200:
                    break
            except Exception:
                pass
            time.sleep(2)
        time.sleep(5)

        st = json.loads(api_py(
            f'import json;from app.chemistry.jobs.base import read_status;'
            f'print("@@@"+json.dumps(read_status("{orphan}") or {{}}))'
        ).splitlines()[-1][3:])
        print(f"    after restart, orphan {orphan} -> {st.get('status')} "
              f"({str(st.get('message'))[:100]})")
        check("S4b _reconcile_orphaned_jobs classified the orphan into a "
              "terminal state instead of leaving it stuck 'running' forever",
              st.get("status") in ("failed", "cancelled", "completed"),
              f"status={st.get('status')} message={str(st.get('message'))[:150]}")
        check("S4c the reconciliation explains itself in the job's message",
              bool(st.get("message")), str(st.get("message"))[:200])
        record("S4", "PASS" if st.get("status") in ("failed", "cancelled", "completed") else "FAIL",
               job=orphan, **st)

    finally:
        if orig_per_user is not None:
            set_cap(admin, "max_concurrent_jobs_per_user", orig_per_user)
            print(f"\nrestored max_concurrent_jobs_per_user = {orig_per_user}")
        cleanup_user(admin, uid)

    summary(exit_on_failure=False)


if __name__ == "__main__":
    main()
