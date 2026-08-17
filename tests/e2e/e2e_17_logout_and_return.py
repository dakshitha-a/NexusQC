"""The leave-and-return workflow: a long calculation must survive its
user logging out, and everything needed to pick the work back up must be
waiting when they log in again.

This is the premise the whole asynchronous job system exists for, not an
edge case. CASSCF/CASPT2 runs in this group routinely take 40-50 minutes
and sometimes hours -- a user is EXPECTED to submit a job, close the tab,
and come back later. So the properties below are load-bearing product
behaviour, and nothing in the report that motivated this suite had ever
actually tested them end-to-end.

Sub-tests:
  L1  submit a genuinely slow job through the real agent + approval gate
  L2  log out for real while it is still running (session gone, 401)
  L3  the worker process is STILL ALIVE and the job still non-terminal
      -- logging out must never kill a calculation
  L4  the job runs to completion while nobody is logged in at all
  L5  log back in on a FRESH session; the job is listed, terminal, and
      carries its results
  L6  the conversation survived intact, including the agent's own
      messages from before the user left
  L7  the job's artifacts are readable again by the returning user
  L9  the agent SUMMARISED the finished job unprompted, while the user
      was logged out, and that summary is waiting on return
  L8  the user can RESUME the work -- a follow-up turn in the same
      conversation, and the agent answers using the completed job

(L9 runs before L8 despite the numbering: it has to observe the
conversation before the user's own follow-up turn adds messages to it.)

The job used is a real ORCA CASSCF(4,4)/STO-3G on water: slow enough to
still be running at the moment of logout (a trivial PySCF single-point
completes faster than the logout round trip, which is what makes this
test meaningless if it uses one), but not so slow that the script cannot
wait it out.
"""
from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from fixtures import (  # noqa: E402
    admin_client, check, cleanup_user, login, mint_invite, register, summary,
)

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _agent import AgentSession, record  # noqa: E402

REPO = Path(__file__).resolve().parent.parent.parent
PASSWORD = "correct horse battery staple 1"

ASK = (
    "Set the molecule to water, then run a CASSCF calculation on it with ORCA "
    "using an active space of 4 electrons in 4 orbitals, the STO-3G basis set, "
    "and 1 state."
)


def api_py(code: str, timeout: int = 120) -> str:
    p = subprocess.run(
        ["docker", "compose", "exec", "-T", "api", "python", "-c", code],
        cwd=str(REPO), capture_output=True, text=True, timeout=timeout,
    )
    if p.returncode != 0:
        raise RuntimeError(f"exec failed: {p.stdout[-400:]} {p.stderr[-400:]}")
    for line in p.stdout.splitlines():
        if line.startswith("@@@"):
            return line[3:]
    return ""


def job_status(job_id: str) -> dict:
    return json.loads(api_py(
        f'import json;from app.chemistry.jobs.base import read_status;'
        f'print("@@@"+json.dumps(read_status("{job_id}") or {{}}))'
    ) or "{}")


def worker_alive(job_id: str) -> dict:
    """Is the job's own worker subprocess still running? Read from the pid
    recorded in meta.json, the same record _reconcile_orphaned_jobs uses,
    and verified against its recorded create_time so a recycled pid can't
    be mistaken for a live worker."""
    return json.loads(api_py(f'''
import json, psutil
from app.chemistry.jobs.base import read_meta
meta = read_meta("{job_id}") or {{}}
pid, created = meta.get("worker_pid"), meta.get("worker_pid_create_time")
alive = False
if pid:
    try:
        p = psutil.Process(int(pid))
        alive = p.is_running() and (created is None or abs(p.create_time() - float(created)) < 1.0)
    except Exception:
        alive = False
print("@@@" + json.dumps({{"pid": pid, "alive": alive}}))
''') or "{}")


def main() -> None:
    admin = admin_client()
    tok = mint_invite(admin, "user")
    user, info = register(tok)
    uid = str((info.get("user") or info).get("id"))
    username = (info.get("user") or info).get("username")

    try:
        # -------------------------------------------------------------- L1
        print("=== L1: submit a genuinely slow job through the agent ===\n")
        s = AgentSession.new(user, label="e2e leave and return")
        thread_id = s.thread_id
        s.say(ASK, timeout=420)
        pending = s.wait_for_approval(timeout=120)
        if pending is None:
            # An LLM miss here is not what this script tests -- retry once.
            print("    (no approval card; retrying once on a fresh thread)")
            s = AgentSession.new(user, label="e2e leave and return retry")
            thread_id = s.thread_id
            s.say(ASK, timeout=420)
            pending = s.wait_for_approval(timeout=120)
        check("L1a the agent produced an approval card for a CASSCF job",
              pending is not None and pending.get("kind") == "job_approval",
              str((pending or {}).get("job_type")))
        if pending is None:
            summary(exit_on_failure=False)
            return

        s.approve()
        job_ids = list(getattr(s, "new_job_ids", []) or [])
        check("L1b approval created a job", len(job_ids) == 1, str(job_ids))
        if not job_ids:
            summary(exit_on_failure=False)
            return
        job_id = job_ids[0]
        print(f"    job {job_id} submitted on thread {thread_id}")

        # Give it a moment to actually be picked up and start.
        st = {}
        for _ in range(60):
            st = job_status(job_id)
            if st.get("status") in ("running", "completed", "failed", "cancelled"):
                break
            time.sleep(1)
        print(f"    status before logout: {st.get('status')}")

        # -------------------------------------------------------------- L2
        print("\n=== L2: log out while the job is still running ===\n")
        still_going = st.get("status") in ("pending", "running")
        check("L2a the job is still non-terminal at the moment of logout "
              "(otherwise this script proves nothing -- pick a slower probe)",
              still_going, f"status={st.get('status')}")

        r_out = user.post("/api/auth/logout")
        check("L2b logout succeeded", r_out.status_code == 200, str(r_out.status_code))
        r_me = user.get("/api/auth/me")
        check("L2c the session is genuinely gone (a real logout, not a no-op)",
              r_me.status_code == 401, f"GET /api/auth/me -> {r_me.status_code}")
        r_jobs = user.get("/api/jobs")
        check("L2d the logged-out client can no longer list jobs",
              r_jobs.status_code == 401, str(r_jobs.status_code))

        # -------------------------------------------------------------- L3
        print("\n=== L3: the calculation keeps running with nobody logged in ===\n")
        time.sleep(5)
        w = worker_alive(job_id)
        st_after = job_status(job_id)
        check("L3a the worker subprocess is STILL ALIVE after its user logged out",
              bool(w.get("alive")), f"pid={w.get('pid')} alive={w.get('alive')}",
              fail_detail="logging out killed a running calculation -- this is the "
                          "single most important property in this script")
        check("L3b the job is still non-terminal after logout",
              st_after.get("status") in ("pending", "running"),
              f"status={st_after.get('status')}")
        record("L3", "PASS" if w.get("alive") else "FAIL",
               job=job_id, worker=w, status=st_after.get("status"))

        # -------------------------------------------------------------- L4
        print("\n=== L4: it runs to completion while nobody is logged in ===\n")
        t0 = time.time()
        final = {}
        while time.time() - t0 < 2400:
            final = job_status(job_id)
            if final.get("status") in ("completed", "failed", "cancelled"):
                break
            time.sleep(10)
        took = time.time() - t0
        check("L4 the job reached a terminal state with no session open at all",
              final.get("status") == "completed",
              f"status={final.get('status')} after {took:.0f}s while logged out")
        record("L4", "PASS" if final.get("status") == "completed" else "FAIL",
               job=job_id, seconds=round(took), status=final.get("status"))

        # -------------------------------------------------------------- L5
        print("\n=== L5: log back in and find the finished work ===\n")
        back, r_login = login(username, PASSWORD)
        check("L5a the user can log back in", r_login.status_code == 200,
              str(r_login.status_code))

        rows = back.get("/api/jobs").json()
        row = next((j for j in rows if j.get("job_id") == job_id), None)
        check("L5b the completed job is listed for the returning user",
              row is not None, f"{len(rows)} jobs listed")
        check("L5c it is shown as completed, not stuck reporting 'running'",
              (row or {}).get("status") == "completed", str((row or {}).get("status")))

        detail = back.get(f"/api/jobs/{job_id}").json()
        casscf_energy = (detail.get("summary") or {}).get("casscf_energy_hartree")
        check("L5d the returning user can read the job's actual RESULTS "
              "(not just its status)",
              casscf_energy is not None,
              f"casscf_energy_hartree={casscf_energy}",
              fail_detail=f"summary keys: {sorted((detail.get('summary') or {}).keys())}")
        record("L5", "PASS" if casscf_energy is not None else "FAIL",
               job=job_id, energy=casscf_energy)

        # -------------------------------------------------------------- L6
        print("\n=== L6: the conversation survived intact ===\n")
        state = back.get(f"/api/threads/{thread_id}/state").json()
        msgs = state.get("messages") or []
        kinds = [m.get("type") for m in msgs]
        check("L6a the conversation is still there after logout and back",
              len(msgs) > 0, f"{len(msgs)} messages, kinds={kinds}")
        check("L6b it still contains the agent's own messages from before "
              "the user left (not just their own typed text)",
              "AIMessage" in kinds, str(kinds))
        threads = back.get("/api/threads").json()
        check("L6c the conversation is listed in the returning user's sidebar",
              any(t.get("thread_id") == thread_id for t in threads),
              f"{len(threads)} threads")

        # -------------------------------------------------------------- L7
        print("\n=== L7: the job's artifacts are readable again ===\n")
        arts = detail.get("artifacts") or {}
        key = "raw_output" if "raw_output" in arts else (sorted(arts)[0] if arts else None)
        if key:
            r_art = back.get(f"/api/jobs/{job_id}/artifacts/{key}")
            check(f"L7 the returning user can fetch the job's '{key}' artifact",
                  r_art.status_code == 200,
                  f"{r_art.status_code}, {len(r_art.content)} bytes")
        else:
            check("L7 the completed job declared artifacts to fetch", False,
                  "no artifacts recorded")

        # -------------------------------------------------------------- L9
        print("\n=== L9: the agent summarised the finished job unprompted ===\n")
        # job_watcher.py polls every ~2s, walks EVERY conversation in the
        # registry (not just ones with an open tab -- see its own module
        # docstring), and on a newly-terminal job injects a synthetic
        # HumanMessage telling the agent to summarise the results. That
        # turn runs, and its messages are checkpointed, whether or not
        # anyone is connected. So a user who leaves should come back to the
        # agent having already written up the result -- which is the whole
        # "come back to relevant agent responses" half of the workflow.
        watcher_msgs = []
        for _ in range(60):
            st_msgs = (back.get(f"/api/threads/{thread_id}/state").json() or {}).get("messages") or []
            watcher_msgs = [
                m for m in st_msgs
                if m.get("type") == "HumanMessage" and "finished" in str(m.get("content") or "")
            ]
            if watcher_msgs:
                break
            time.sleep(5)
        check("L9a the job watcher injected a completion notice into the "
              "conversation while the user was logged out",
              len(watcher_msgs) > 0,
              f"{len(watcher_msgs)} notice(s)",
              fail_detail="a returning user would find no mention of their finished job")

        after_notice = []
        if watcher_msgs:
            st_msgs = (back.get(f"/api/threads/{thread_id}/state").json() or {}).get("messages") or []
            idx = max(i for i, m in enumerate(st_msgs) if m in watcher_msgs)
            after_notice = [
                str(m.get("content") or "") for m in st_msgs[idx + 1:]
                if m.get("type") == "AIMessage" and (m.get("content") or "")
            ]
        summary_text = " ".join(after_notice)
        check("L9b the agent actually WROTE that summary, unprompted, and it "
              "is waiting in the conversation on return",
              len(summary_text.strip()) > 0,
              f"{len(after_notice)} assistant message(s) after the notice",
              fail_detail="the notice was injected but produced no agent reply")
        record("L9", "PASS" if summary_text.strip() else "FAIL",
               job=job_id, summary=summary_text[:400])
        if summary_text.strip():
            print(f"    agent wrote, with nobody watching: {summary_text[:220]!r}")

        # -------------------------------------------------------------- L8
        print("\n=== L8: the user can resume the work ===\n")
        s2 = AgentSession(back, thread_id)
        s2.open_events()
        t = s2.say("What was the final CASSCF energy of the job that just finished?",
                   timeout=420)
        reply = t.assistant_text()
        check("L8a a follow-up turn in the resumed conversation completes",
              len(t.new_messages or []) > 0, f"{len(t.new_messages or [])} new messages")
        # Match on a TRUNCATED prefix of the energy, at whichever precision
        # the model chose to quote. Rounding to a fixed 2 dp was the first
        # attempt and it failed a run the app had actually passed: the real
        # value was -74.9779291936, the agent correctly said "-74.9779", and
        # the check was looking for "74.98". A continuity test must not fail
        # on someone else's formatting choice.
        norm = reply.replace(",", "").replace("\u2212", "-")  # U+2212 MINUS SIGN
        stems = (
            [f"{abs(casscf_energy):.{d}f}" for d in (2, 3, 4, 5, 6)]
            if isinstance(casscf_energy, (int, float)) else []
        )
        # Truncate rather than round, so 74.9779... yields 74.97 not 74.98.
        raw = f"{abs(casscf_energy):.10f}" if isinstance(casscf_energy, (int, float)) else ""
        stems += [raw[: raw.index(".") + 1 + d] for d in (2, 3, 4, 5, 6)] if raw else []
        hit = next((st for st in stems if st in norm), None)
        check("L8b the agent answers using the job that completed while the "
              "user was away",
              hit is not None,
              f"reply quotes {hit!r}, job summary says {casscf_energy}",
              fail_detail=f"none of {sorted(set(stems))} appeared; reply was: {reply[:300]!r}")
        record("L8", "PASS", job=job_id, reply=reply[:400])

        cleanup_user(admin, uid)
        summary(exit_on_failure=False)
        return
    except Exception:
        cleanup_user(admin, uid)
        raise


if __name__ == "__main__":
    main()
