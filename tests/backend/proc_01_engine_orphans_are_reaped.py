"""The api container does not accumulate zombie processes as engines run.

    QC_AGENT_TEST_BASE_URL=https://127.0.0.1:8444 \\
      PYTHONPATH=$PWD python3 tests/backend/proc_01_engine_orphans_are_reaped.py

WHAT THIS IS ABOUT
------------------
`entrypoint.sh` execs `python -m server.main`, so before 2026-09-14 the app
itself was PID 1 of its container. PID 1 inherits every orphaned process in
its namespace and is expected to reap them, and Python does not: it collects
the child `subprocess.run` started and nothing else.

ORCA is not one process. It starts a shell, `mpirun`, and a per-module binary
for each stage of a calculation. A job that runs to completion is fine:
everything ORCA started exits before ORCA does, and `subprocess.run` collects
ORCA itself. A job that is CANCELLED is not. Cancellation kills the process
group, and the grandchildren that were mid-exit at that moment are re-parented
to PID 1, where they stay as zombies. Each one holds a PID and a kernel task
struct until the process that owns them exits, which for a server is never.

Measured during the 2026-09 fix phase, and the distinction was measured rather
than assumed: after the scheduler and stability work, which cancels ORCA jobs
by the dozen to observe admission transients, the api container held twenty
zombies, every one of them `orca`, `sh` or `mpirun`. Running two more ORCA jobs
to COMPLETION added none. So this is the cancellation path, which is also the
Stop button, and not something exotic. Nothing else in the stack does it:
PySCF runs in-process and BAGEL's launcher is a single binary.

The fix is `init: true` on the api service in docker-compose.yml, which puts
docker's own tini in front as PID 1. Tini reaps orphans and forwards signals,
which is the entire job PID 1 has in a container and the one the application
was never going to do.

WHAT THIS SCRIPT CHECKS
-----------------------
Counts zombies inside the container, submits N real ORCA jobs and CANCELS each
one as soon as it is running, and counts again. A deployment that reaps sees
the same number; one that does not sees it grow.

The probe is the same ORCA CASSCF(4,4)/STO-3G on water the timing probes use,
because what matters is that ORCA's multi-process launcher is mid-flight when
the kill arrives, not what it computes. Each job is deleted afterwards.

The script also asserts that tini is actually in front, because the count
alone would pass on a stack that simply had not run an ORCA job yet, and
because a compose file edited back would otherwise fail silently here.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from fixtures import admin_client, check, summary  # noqa: E402

COMPOSE_DIR = Path(__file__).resolve().parent.parent.parent
# About three zombies per cancelled ORCA run were observed before the fix
# (orca, sh, mpirun), so three cancellations would leave roughly nine. Two are
# allowed for whatever else happens to be mid-exit as the count is taken;
# anything at or above this is the leak.
ZOMBIE_TOLERANCE = 3
N_JOBS = 3


def _compose(*args: str, timeout: int = 900) -> str:
    proc = subprocess.run(["docker", "compose", *args], cwd=str(COMPOSE_DIR),
                          capture_output=True, text=True, timeout=timeout)
    if proc.returncode != 0:
        raise RuntimeError(f"docker compose {' '.join(args)} failed: {proc.stderr[:300]}")
    return proc.stdout


def zombie_count() -> int:
    """Zombies inside the api container, counted from /proc rather than with
    `ps`, which this image does not have."""
    script = (
        "n=0; "
        "for p in /proc/[0-9]*; do "
        "  s=$(awk '/^State:/ {print $2}' $p/status 2>/dev/null); "
        "  [ \"$s\" = Z ] && n=$((n+1)); "
        "done; echo $n"
    )
    return int(_compose("exec", "-T", "api", "sh", "-c", script).strip() or 0)


def pid1_comm() -> str:
    return _compose("exec", "-T", "api", "sh", "-c",
                    "cat /proc/1/comm").strip()


def main() -> None:
    admin = admin_client()

    comm = pid1_comm()
    check(
        "tini is PID 1 of the api container, so orphaned engine processes have "
        "something to reap them (docker-compose.yml's `init: true` on the api service)",
        "tini" in comm.lower() or "docker-init" in comm.lower(),
        f"PID 1 is {comm!r}; if that is the app itself then nothing reaps what ORCA leaves behind",
    )

    before = zombie_count()
    print(f"zombies in the api container before: {before}")

    code = f'''
import json, time
from app.chemistry.molecule import resolve_molecule
from app.chemistry.jobs.base import JobSpec, get_job_manager
mgr = get_job_manager()
m = resolve_molecule("water").to_dict()
ids, states, ran = [], [], []
for _ in range({N_JOBS}):
    jid = mgr.submit(JobSpec(task="single_point", subtype="gs", method="casscf",
                             engine="orca", molecule=m,
                             params={{"basis": "sto-3g", "active_electrons": 4,
                                     "active_orbitals": 4, "n_excited_states": 0}}))
    ids.append(jid)
    # Wait until ORCA is genuinely running before cancelling. Cancelling a
    # queued job kills nothing and would leave nothing behind either way,
    # which would make this script pass on a broken deployment.
    end = time.time() + 300
    saw_running = False
    while time.time() < end:
        st = (mgr.status(jid) or {{}}).get("status")
        if st == "running":
            saw_running = True
            break
        if st in ("completed", "failed", "cancelled"):
            break
        time.sleep(0.25)
    ran.append(saw_running)
    if saw_running:
        # A moment for ORCA to start its own children, which are what gets
        # orphaned. Killing the group in the first instant of the run would
        # test a case that leaves nothing to reap.
        time.sleep(3)
        mgr.cancel(jid)
    end = time.time() + 120
    st = None
    while time.time() < end:
        st = (mgr.status(jid) or {{}}).get("status")
        if st in ("completed", "failed", "cancelled"):
            break
        time.sleep(0.5)
    states.append(st)
print(json.dumps({{"ids": ids, "states": states, "ran": ran}}))
'''
    out = _compose("exec", "-T", "api", "python", "-c", code, timeout=1800)
    ran = json.loads(out.strip().splitlines()[-1])
    print(f"submitted and cancelled {len(ran['ids'])} ORCA job(s): {ran['states']}")
    check(f"all {N_JOBS} probe job(s) reached 'running' before being cancelled, so ORCA's "
          f"own child processes existed to be orphaned",
          all(ran["ran"]),
          f"reached running: {ran['ran']}, final states {ran['states']}")

    after = zombie_count()
    print(f"zombies in the api container after:  {after}")
    check(
        f"cancelling {N_JOBS} running ORCA job(s) leaves no zombie processes behind "
        f"(before {before}, after {after}, tolerance {ZOMBIE_TOLERANCE})",
        after - before < ZOMBIE_TOLERANCE,
        f"{after - before} new zombie(s); a cancelled ORCA run leaves about three "
        f"when nothing reaps them",
    )

    for jid in ran["ids"]:
        try:
            admin.delete(f"/api/jobs/{jid}")
        except Exception:  # noqa: BLE001
            pass

    summary()


if __name__ == "__main__":
    main()
