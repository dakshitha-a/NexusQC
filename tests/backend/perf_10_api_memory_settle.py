"""R-103: is the api process's memory growth a leak, or a warm cache?

    QC_AGENT_TEST_BASE_URL=https://127.0.0.1:8444 \\
      PYTHONPATH=$PWD python3 tests/backend/perf_10_api_memory_settle.py

WHAT WAS MEASURED IN THE REVIEW, AND WHY IT DID NOT SETTLE ANYTHING
--------------------------------------------------------------------
Two readings of `VmRSS` from the api container's own `/proc/1/status`, taken
from one uninterrupted process: 551 MB right after the frozen bring-up, and
1,231 MB at the end of a day that submitted a few hundred jobs and ran many
agent turns and SSE streams. Thread count moved 658 to 660 and open file
descriptors 28 to 54, so the growth is heap rather than threads or handles.

Two points on a rising line do not distinguish the two things that produce
one. A leak keeps climbing with use and never comes back. A warm cache climbs
once, to whatever the working set costs, and then stays flat however much more
work arrives. Both look identical from two samples taken a day apart, and the
difference decides whether anything needs fixing at all.

THE EXPERIMENT
--------------
Restart the api so the process starts from a known floor, then run the SAME
fixed load LOADS times over, reading RSS between each one, with one idle
period after the first load to see whether anything is given back on its own:

    R0  read RSS at rest, right after the restart
    L1  run a fixed, repeatable load; read RSS
        idle for IDLE_SECONDS with nothing driving the process; read RSS
    L2  the same load again; read RSS
    L3  the same load again; read RSS
    L4  the same load again; read RSS

WHY FOUR LOADS, WHEN THE REGISTER ASKED FOR TWO
------------------------------------------------
Two were run first, and the result is kept alongside this one in
`perf_10-two-loads.log` rather than discarded, because it is why the
experiment grew. It gave a first rise of 179.8 MB and a second of 61.1 MB
against a leak threshold, set before the run, of a third of the first, which
is 59.3 MB. The second rise cleared that threshold by 1.8 MB.

A verdict that turns on 1.8 MB is not a verdict. Two points cannot separate a
warm-up that is still decaying, where each load costs a fraction of the last
and the total converges, from a genuine leak that happens to be smaller than
the first load's one-off costs. Those have different consequences for a
long-running deployment and only the shape of the series tells them apart: a
leak gives roughly equal rises, a filling working set gives shrinking ones.

The load is fixed so that every pass asks the process to do the same work,
which is what makes the rises comparable. It is:

  - POLLS reads of GET /api/chat/state for a fresh thread, the request every
    open tab makes every few seconds
  - TURNS real agent turns, each on its own fresh thread, each one a full pass
    through the graph, the tool bindings and the LLM
  - SUBMITS job submissions through the approval path, cancelled immediately,
    so the scheduler, the watcher and the job index all see traffic without
    paying for the calculations
  - CUBES orbital cube renders off one completed PySCF job, which is the
    heaviest per-request allocation the app makes on a read path

The reading is `VmRSS` from `/proc/1/status` inside the container, which is the
same number the review took, plus thread and descriptor counts for the same
reason it took those.

HOW TO READ THE RESULT
----------------------
The script prints RSS after every load and the rise each load cost, and reads
the verdict off the series:

    rises roughly flat            the same work keeps costing the same memory
                                  and nothing gives it back: a leak, and its
                                  size per load is the number that matters
    rises shrinking, last one     the first loads paid for a working set the
    under FINAL_RISE_FRACTION     later ones reused: a warm cache, and the
    of the first                  review's two points were the first half of
                                  exactly this curve
    RSS falls during the idle     the allocator returned it unprompted, which
                                  is neither and is reported separately. It
                                  can also RISE there, since the watcher, the
                                  scheduler and the quota pass keep working
                                  when no request is arriving; the line is
                                  printed as a signed change for that reason

Both thresholds are named here rather than buried, and both were fixed before
the four-load run. A threshold chosen after seeing the data is not a
threshold.
"""
from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from fixtures import admin_client, check, cleanup_user, mint_invite, register, summary  # noqa: E402

COMPOSE_DIR = Path(__file__).resolve().parent.parent.parent
POLLS = 50
TURNS = 5
SUBMITS = 5
CUBES = 20
LOADS = 4
IDLE_SECONDS = 300
# The last load's rise must be under this fraction of the first for the series
# to read as a working set that has filled rather than a leak. Chosen before
# the four-load run, and see "WHY FOUR LOADS" below for why the earlier
# two-load run could not use a threshold at all.
FINAL_RISE_FRACTION = 0.33
TURN_PROMPT = "What basis sets can this app run with PySCF?"


def _compose(*args: str, timeout: int = 300) -> str:
    proc = subprocess.run(["docker", "compose", *args], cwd=str(COMPOSE_DIR),
                          capture_output=True, text=True, timeout=timeout)
    if proc.returncode != 0:
        raise RuntimeError(f"docker compose {' '.join(args)} failed: {proc.stderr[:400]}")
    return proc.stdout


def read_process_stats() -> dict:
    out = _compose("exec", "-T", "api", "sh", "-c",
                   "grep -E '^VmRSS|^Threads' /proc/1/status; ls /proc/1/fd | wc -l")
    stats = {"rss_kb": None, "threads": None, "fds": None}
    for line in out.splitlines():
        line = line.strip()
        if line.startswith("VmRSS:"):
            stats["rss_kb"] = int(line.split()[1])
        elif line.startswith("Threads:"):
            stats["threads"] = int(line.split()[1])
        elif line.isdigit():
            stats["fds"] = int(line)
    return stats


def mb(kb: int | None) -> float:
    return round((kb or 0) / 1024.0, 1)


def restart_api() -> None:
    _compose("restart", "api", timeout=300)
    # Wait for the container's own healthcheck rather than guessing.
    deadline = time.time() + 300
    while time.time() < deadline:
        out = _compose("ps", "--format", "json")
        if '"Service":"api"' in out and "healthy" in out:
            return
        time.sleep(5)
    raise RuntimeError("the api container did not become healthy after a restart")


def seed_orbital_job(owner_id: str) -> str:
    """One completed PySCF HF/STO-3G single point on water, whose orbitals the
    cube renders below are taken from. Water in STO-3G has seven orbitals, so
    CUBES renders cycle through them; a render is not cached between calls
    (`orbital-visualisation-is-lazy-and-per-job`), which is the point."""
    code = '''
import json, time
from app.chemistry.molecule import resolve_molecule
from app.chemistry.jobs.base import JobSpec, get_job_manager
mgr = get_job_manager()
m = resolve_molecule("water")
jid = mgr.submit(JobSpec(task="single_point", subtype="gs", method="hf", engine="pyscf",
                         molecule=m.to_dict(), params={"basis": "sto-3g"}),
                 owner_user_id=OWNER)
end = time.time() + 300
while time.time() < end:
    s = (mgr.status(jid) or {}).get("status")
    if s in ("completed", "failed", "cancelled"):
        break
    time.sleep(1.0)
print(json.dumps({"job_id": jid, "status": s}))
'''
    code = code.replace("OWNER", repr(owner_id))
    proc = subprocess.run(["docker", "compose", "exec", "-T", "api", "python", "-c", code],
                          cwd=str(COMPOSE_DIR), capture_output=True, text=True, timeout=420)
    if proc.returncode != 0:
        raise RuntimeError(f"seeding the orbital job failed: {proc.stderr[:400]}")
    return json.loads(proc.stdout.strip().splitlines()[-1])["job_id"]


def run_load(client, label: str, orbital_job: str, created: dict) -> None:
    """The fixed load. Identical on both passes, which is what makes the two
    rises comparable; anything that varies between them is measurement noise
    dressed as a result."""
    t0 = time.time()

    thread = client.post("/api/threads", json={"label": f"perf_10 {label} polls"}).json()
    tid = thread.get("thread_id") or thread.get("id")
    created.setdefault("threads", []).append(tid)
    for _ in range(POLLS):
        client.get(f"/api/threads/{tid}/state")

    for i in range(TURNS):
        t = client.post("/api/threads", json={"label": f"perf_10 {label} turn {i + 1}"}).json()
        t_id = t.get("thread_id") or t.get("id")
        created.setdefault("threads", []).append(t_id)
        r = client.post(f"/api/threads/{t_id}/messages",
                        json={"text": TURN_PROMPT, "job_ids": [], "frame_id": None},
                        timeout=300.0)
        if r.status_code >= 400:
            raise RuntimeError(f"posting a turn failed: HTTP {r.status_code} {r.text[:200]}")
        # POST /messages answers 202 and the turn runs on a worker thread, so
        # the load has to wait for the turn rather than for the request. The
        # thread starts empty, so "an assistant message has appeared after the
        # user's" is the end of the turn, and the timeout is generous because
        # this host is shared and a turn is a real LLM call.
        # The turn is over when the transcript has stopped growing. Reading the
        # last message's role would be shape-dependent, and this only needs to
        # know the work finished, so it waits for two consecutive polls to
        # report the same count with at least the user's message and one reply.
        deadline = time.time() + 300
        last = -1
        stable = 0
        while time.time() < deadline:
            st = client.get(f"/api/threads/{t_id}/state").json()
            n = len(st.get("messages") or [])
            stable = stable + 1 if n == last and n >= 2 else 0
            last = n
            if stable >= 2:
                break
            time.sleep(1.0)

    code = f'''
import json, time
from app.chemistry.molecule import resolve_molecule
from app.chemistry.jobs.base import JobSpec, get_job_manager
mgr = get_job_manager()
m = resolve_molecule("water")
ids = []
for _ in range({SUBMITS}):
    jid = mgr.submit(JobSpec(task="single_point", subtype="gs", method="hf", engine="pyscf",
                             molecule=m.to_dict(), params={{"basis": "sto-3g"}}))
    ids.append(jid)
time.sleep(2)
for jid in ids:
    mgr.cancel(jid)
print(json.dumps(ids))
'''
    proc = subprocess.run(["docker", "compose", "exec", "-T", "api", "python", "-c", code],
                          cwd=str(COMPOSE_DIR), capture_output=True, text=True, timeout=300)
    if proc.returncode == 0:
        created.setdefault("jobs", []).extend(json.loads(proc.stdout.strip().splitlines()[-1]))

    for i in range(CUBES):
        client.post(f"/api/jobs/{orbital_job}/orbitals/{(i % 7) + 1}/cube", timeout=180.0)

    print(f"   load {label}: {POLLS} state polls, {TURNS} turns, {SUBMITS} submissions, "
          f"{CUBES} cube renders in {time.time() - t0:.0f}s")


def main() -> None:
    admin = admin_client()
    token = mint_invite(admin)
    client, user = register(token)
    created: dict = {}

    print("restarting the api so the measurement starts from a known floor")
    restart_api()
    # A newly-healthy container has just imported everything and answered one
    # health check; give the import-time allocations a moment to settle so R0
    # is a floor rather than a transient.
    time.sleep(20)

    r0 = read_process_stats()
    print(f"R0 at rest after restart:      {mb(r0['rss_kb'])} MB, "
          f"{r0['threads']} threads, {r0['fds']} open fds")

    try:
        orbital_job = seed_orbital_job(user["id"])
        created.setdefault("jobs", []).append(orbital_job)
        print(f"   seeded {orbital_job} for the cube renders")

        readings = [("R0", r0)]
        rises: list[tuple[str, float]] = []
        idle_return = 0.0
        prev = r0

        for i in range(1, LOADS + 1):
            run_load(client, f"L{i}", orbital_job, created)
            r = read_process_stats()
            rise = mb(r["rss_kb"]) - mb(prev["rss_kb"])
            readings.append((f"after L{i}", r))
            rises.append((f"L{i}", rise))
            print(f"   RSS after L{i}: {mb(r['rss_kb'])} MB "
                  f"({rise:+.1f} MB), {r['threads']} threads, {r['fds']} open fds")
            prev = r
            if i == 1:
                print(f"   idling {IDLE_SECONDS}s with nothing driving the process")
                time.sleep(IDLE_SECONDS)
                r_idle = read_process_stats()
                idle_return = mb(r["rss_kb"]) - mb(r_idle["rss_kb"])
                readings.append((f"after {IDLE_SECONDS}s idle", r_idle))
                print(f"   RSS after {IDLE_SECONDS}s idle: {mb(r_idle['rss_kb'])} MB "
                      f"(change {-idle_return:+.1f} MB), {r_idle['threads']} threads, "
                      f"{r_idle['fds']} open fds")
                prev = r_idle

        last = readings[-1][1]
        first_rise = rises[0][1]
        final_rise = rises[-1][1]

        print()
        print("RESULT R-103")
        for label, r in readings:
            print(f"  {label:<24} {mb(r['rss_kb']):>7.1f} MB  "
                  f"{r['threads']:>4} threads  {r['fds']:>3} fds")
        print("  cost of each load, in MB of RSS: "
              + ", ".join(f"{n} {v:+.1f}" for n, v in rises))
        # Signed as a CHANGE, not as an amount returned. The first version of
        # this line was labelled "returned unprompted" and printed the same
        # number, so a process whose RSS ROSE while nothing was driving it read
        # as one that had given memory back. It rises on this deployment: the
        # watcher, the scheduler and the quota pass are all still working
        # during an idle period, which is worth knowing and is the opposite of
        # what the old label said.
        print(f"  change in RSS across the {IDLE_SECONDS}s idle, nothing driving it: "
              f"{-idle_return:+.1f} MB")

        threshold = first_rise * FINAL_RISE_FRACTION
        if first_rise <= 0:
            verdict = ("INCONCLUSIVE: the first load did not raise RSS at all, so there is no "
                       "first rise for the rest of the series to be compared against")
        elif final_rise < threshold:
            verdict = (f"WARM CACHE: the loads cost "
                       f"{', '.join(f'{v:.1f}' for _, v in rises)} MB in order, so the last "
                       f"cost {final_rise:.1f} MB against the first load's {first_rise:.1f} MB, "
                       f"under the {threshold:.1f} MB threshold. The same work costs less each "
                       f"time, which is a working set filling rather than memory being lost")
        else:
            verdict = (f"LEAK: the loads cost "
                       f"{', '.join(f'{v:.1f}' for _, v in rises)} MB in order, so the last "
                       f"still cost {final_rise:.1f} MB against the first load's "
                       f"{first_rise:.1f} MB, at or above the {threshold:.1f} MB threshold. "
                       f"The same work keeps taking memory and the process does not settle")
        print(f"  verdict: {verdict}")

        check(
            f"the same load costs less each time rather than the same again (loads cost "
            f"{', '.join(f'{v:.1f}' for _, v in rises)} MB; the last must be under "
            f"{threshold:.1f} MB, a third of the first)",
            first_rise > 0 and final_rise < threshold,
            verdict,
        )
        check(
            "the thread count is not still climbing by the last load, so nothing leaks threads "
            "load on load",
            (last["threads"] or 0) <= (readings[2][1]["threads"] or 0) + 40,
            f"{readings[2][0]} {readings[2][1]['threads']} -> last {last['threads']}",
        )
        check(
            "open file descriptors are stable across the whole series",
            abs((last["fds"] or 0) - (r0["fds"] or 0)) <= 40,
            f"{r0['fds']} -> {last['fds']}",
        )
    finally:
        # Reported rather than swallowed. The first version of this script hid
        # every status code behind `except Exception: pass` and left eleven
        # jobs and twenty-two threads on the deployment, which the cleanup diff
        # found and the script had said nothing about. A cleanup that cannot
        # fail loudly is a cleanup nobody can trust.
        #
        # A fresh admin client, too: this runs up to an hour after the one at
        # the top of main(), with a container restart in between, and a
        # cleanup is the wrong place to discover a stale session.
        closer = admin_client()
        job_codes: dict[int, int] = {}
        for jid in created.get("jobs", []):
            try:
                c = closer.delete(f"/api/jobs/{jid}").status_code
            except Exception as exc:  # noqa: BLE001
                c = -1
                print(f"   deleting job {jid} raised {type(exc).__name__}")
            job_codes[c] = job_codes.get(c, 0) + 1
        thread_codes: dict[int, int] = {}
        for tid in created.get("threads", []):
            try:
                c = closer.delete(f"/api/threads/{tid}").status_code
            except Exception as exc:  # noqa: BLE001
                c = -1
                print(f"   deleting thread {tid} raised {type(exc).__name__}")
            thread_codes[c] = thread_codes.get(c, 0) + 1
        print(f"   cleanup: {len(created.get('jobs', []))} jobs {job_codes}, "
              f"{len(created.get('threads', []))} threads {thread_codes}")
        cleanup_user(closer, user["id"])

    summary()


if __name__ == "__main__":
    main()
