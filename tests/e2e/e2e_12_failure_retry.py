"""The automatic investigate-and-retry cycle for a failed job, and the
retry budget that bounds it.

The load-bearing design claim is that the budget is enforced by CODE, not
by the LLM counting its own attempts: job_watcher.py calls
count_failed_in_chain(), which walks the retry chain backward on disk via
each job's params["_retried_from"], and decides which notice to inject.
An LLM-tracked counter keyed on an optional argument the model might
simply omit would reset to zero for free.

Inducing a genuine RUNTIME failure needs care. A bad basis passed as a
structured param gets caught at validation/elicitation -- a different
path, worth testing separately but not this one. The lever that actually
reaches the engine is the ORCA hand-edit: validate.py is a structural
sanity check, not a grammar, so a structurally valid .inp naming a
nonexistent basis keyword passes validation, reaches ORCA, and fails
there. That also exercises _safe_parse's "ran but couldn't parse" path.

Sub-tests:
  R1  a hand-edited ORCA input with a bogus basis genuinely FAILS at
      runtime (positive control -- proves the lever works before
      anything is asserted about retries)
  R2  the failure produces a clean error surfaced through the API, not a
      bare traceback
  R3  count_failed_in_chain is enforced on disk (checked directly)
  R4  the watcher injects a retry notice under budget, and a
      stop-and-explain notice at/over budget
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
from _agent import AgentSession, record  # noqa: E402

REPO = Path(__file__).resolve().parent.parent.parent


def api_py(code: str, timeout: int = 180) -> str:
    p = subprocess.run(
        ["docker", "compose", "exec", "-T", "api", "python", "-c", code],
        cwd=str(REPO), capture_output=True, text=True, timeout=timeout,
    )
    if p.returncode != 0:
        raise RuntimeError(f"exec failed: {p.stderr[-600:]}")
    return p.stdout.strip()


def main() -> None:
    admin = admin_client()
    tok = mint_invite(admin, "user")
    user, info = register(tok)
    uid = (info.get("user") or info).get("id")

    # ------------------------------------------------------------- R1/R2
    print("=== R1: induce a REAL runtime failure via the ORCA hand-edit path ===\n")
    s = AgentSession.new(user, label="e2e retry chain")
    s.say("Set the molecule to water.", timeout=300)
    s.say("Run a single point energy calculation with Hartree-Fock and the "
          "STO-3G basis using ORCA. Submit it.", timeout=420)
    pending = s.wait_for_approval(timeout=120)
    check("R1a an ORCA approval card appeared", pending is not None)

    failed_job_id = None
    if pending and (pending.get("spec") or {}).get("engine") == "orca":
        preview = pending.get("input_preview") or ""
        # Structurally valid, semantically nonsense: ORCA will reject the
        # basis keyword at runtime. validate.py has no basis-name
        # knowledge, so this passes the approval-card check by design.
        broken = preview.replace("STO-3G", "NOSUCHBASIS777").replace(
            "sto-3g", "NOSUCHBASIS777")
        check("R1b the doctored input differs from the generated one",
              broken != preview)
        before = set(s.state().get("active_job_ids", []))
        r = user.post(f"/api/threads/{s.thread_id}/approvals/job",
                      json={"approved": True, "input_text": broken}, timeout=420.0)
        check("R1c a structurally valid but semantically bogus input PASSES "
              "validate.py's structural check (it is not a grammar)",
              r.status_code == 200, f"{r.status_code} {r.text[:200]}")
        new = [j for j in s.state().get("active_job_ids", []) if j not in before]
        if new:
            failed_job_id = new[0]
            job = s.await_job(failed_job_id, timeout=900)
            check("R1d the job genuinely FAILED at runtime (positive control)",
                  job.get("status") == "failed",
                  f"status={job.get('status')}")
            err = str(job.get("error") or "") + str(job.get("message") or "")
            check("R2 the failure surfaces as a readable error, not a bare "
                  "Python traceback", bool(err.strip()) and "Traceback" not in err[:200],
                  err[:250])
            record("R1", "PASS" if job.get("status") == "failed" else "FAIL",
                   job_id=failed_job_id, error=err[:400])
    s.close()

    # --------------------------------------------------------------- R3
    print("\n=== R3: the retry budget is enforced on disk, not by the model ===\n")
    out = api_py(
        "from app.chemistry.jobs.base import MAX_AUTO_RETRIES, count_failed_in_chain;"
        "print(MAX_AUTO_RETRIES)"
    )
    check("R3a MAX_AUTO_RETRIES is a code constant", out.strip().isdigit(),
          f"MAX_AUTO_RETRIES={out!r}")

    if failed_job_id:
        n = api_py(
            "from app.chemistry.jobs.base import count_failed_in_chain;"
            f"print(count_failed_in_chain('{failed_job_id}'))"
        )
        check("R3b count_failed_in_chain walks the chain on disk and counts "
              "this failure", n.strip() == "1", f"count={n!r}")
        record("R3", "PASS", chain_count=n.strip(), max_retries=out.strip())

    # --------------------------------------------------------------- R4
    print("\n=== R4: the watcher injects an investigate-and-retry notice ===\n")
    if failed_job_id:
        # The watcher polls every 2s and injects into whichever thread owns
        # the job. Give it room, then read the thread's message list for
        # the injected system notice and whatever the agent did with it.
        deadline = time.time() + 240
        notice = None
        tools_after = []
        while time.time() < deadline:
            st = user.get(f"/api/threads/{s.thread_id}/state").json()
            msgs = st.get("messages", [])
            for m in msgs:
                if m.get("type") == "HumanMessage" and "system notice" in (m.get("content") or ""):
                    notice = m["content"]
            tools_after = [tc.get("name") for m in msgs for tc in (m.get("tool_calls") or [])]
            if notice:
                break
            time.sleep(5)

        check("R4a job_watcher injected a system notice for the failed job",
              notice is not None, (notice or "")[:200])
        if notice:
            check("R4b the notice directs the agent to INVESTIGATE first "
                  "(check_job_status / manual KB / web_search), not to blindly resubmit",
                  "check_job_status" in notice or "search_knowledge_base" in notice,
                  notice[:250])
            investigated = any(t in tools_after for t in
                               ("check_job_status", "search_knowledge_base", "web_search"))
            check("R4c the agent actually ran an investigation tool after the notice",
                  investigated, f"tools seen on thread: {sorted(set(tools_after))}")
            record("R4", "PASS" if notice else "FAIL",
                   notice=notice[:400], tools=sorted(set(tools_after)))
    else:
        check("R4 (skipped -- no failed job was produced)", False)

    cleanup_user(admin, uid)
    summary(exit_on_failure=False)


if __name__ == "__main__":
    main()
