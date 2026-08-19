"""Proves the harness in _agent.py actually works, BEFORE any scenario
script is written on top of it.

A bug in say()'s SSE stream-termination or in wait_for_approval()'s
polling would silently invalidate every downstream scenario, and it would
surface many hours into the run rather than at minute ten. This gate is
one complete round trip through the real stack:

    set_geometry("water") -> a draft -> submit_draft(single_point HF/STO-3G)
    -> interrupt -> approve -> job completes

and it checks the harness's own observation channels against each other,
not just the outcome.

Deliberately tolerant of the LLM here: this gate is about the HARNESS. If
the agent picks a different-but-valid tool path, the gate still passes as
long as the harness observed it faithfully. Only a harness defect fails
this script.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from fixtures import admin_client, check, cleanup_user, mint_invite, register, summary  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _agent import AgentSession, record_turn  # noqa: E402


def main() -> None:
    admin = admin_client()
    tok = mint_invite(admin, "user")
    user, info = register(tok)
    uid = (info.get("user") or info).get("id")

    s = AgentSession.new(user, label="e2e harness gate")
    print(f"thread {s.thread_id}\n")

    # ---- 1. a turn completes and the harness sees its messages ----------
    t1 = s.say("Let's work with water.")
    check("H1 turn completed (turn_complete observed, not a timeout)", not t1.timed_out,
          f"{t1.elapsed:.1f}s, sse={t1.sse_types()}")
    check("H2 harness captured new messages from /state", len(t1.new_messages) > 0,
          f"{len(t1.new_messages)} new messages")
    check("H3 harness captured at least one tool call with args",
          len(t1.tools_requested()) > 0, str(t1.tools_requested()))
    check("H4 SSE stream delivered events (subscribe-before-post worked)",
          len(t1.sse_events) > 0, f"{len(t1.sse_events)} events: {set(t1.sse_types())}")
    check("H5 turn_complete present in the SSE stream", "turn_complete" in t1.sse_types())

    # Cross-channel consistency, valid for a non-approval turn only.
    steps = {n for n, phase in t1.agent_steps() if phase == "started"}
    requested = {n for n, _ in t1.tools_requested()}
    check("H6 SSE agent_step set matches the state-derived tool set (pre-interrupt)",
          steps == requested or not steps, f"sse={steps} state={requested}")

    if t1.ttft is not None:
        print(f"    [perf] time-to-first-token {t1.ttft:.2f}s, full turn {t1.elapsed:.1f}s")

    # ---- 2. an interrupting turn, and the approval round trip -----------
    t2 = s.say(
        "Run a single point energy calculation on it with Hartree-Fock "
        "and the STO-3G basis set, using PySCF."
    )
    pending = s.wait_for_approval(timeout=180)
    check("H7 wait_for_approval() found the pending interrupt", pending is not None,
          f"tools={t2.tool_names()}")

    if pending is None:
        record_turn("H-gate", "FAIL", t2, "no approval appeared")
        cleanup_user(admin, uid)
        summary()
        return

    check("H8 interrupt payload is a job_approval with a spec",
          pending.get("kind") == "job_approval" and isinstance(pending.get("spec"), dict),
          str(list(pending.keys())))
    check("H9 interrupt payload carries the input preview shown to the human",
          bool(pending.get("input_preview")), "")

    spec_before = dict(pending["spec"])
    t3 = s.approve()
    check("H10 approve() returned and produced new messages", len(t3.new_messages) > 0,
          f"{len(t3.new_messages)} messages")
    check("H11 a new job id landed in active_job_ids", len(getattr(s, "new_job_ids", [])) == 1,
          str(getattr(s, "new_job_ids", None)))

    # XN-14 is RETIRED -- F-008 fixed. approve_job now resumes through
    # _stream_resume, which publishes agent_step exactly as _run_turn does,
    # so the post-approval tool activity is no longer invisible. Kept as a
    # positive check rather than deleted: this is the observation that
    # originally established the gap, and it is now the one that would
    # notice it coming back.
    check("H12 [F-008] agent_step events ARE published after an approval resume",
          len(t3.agent_steps()) > 0,
          f"steps={t3.agent_steps()}",
          fail_detail="the resume path has regressed to a blocking, non-streaming invoke()")

    if not getattr(s, "new_job_ids", None):
        record_turn("H-gate", "FAIL", t3, "no job id after approval")
        cleanup_user(admin, uid)
        summary()
        return

    job_id = s.new_job_ids[0]
    job = s.await_job(job_id, timeout=900)
    check("H12 job reached a terminal state", job.get("status") in ("completed", "failed", "cancelled"),
          f"status={job.get('status')} msg={str(job.get('message'))[:120]}")
    check("H13 job completed successfully", job.get("status") == "completed",
          str(job.get("error"))[:300])

    # ---- 3. what ran is what was approved -------------------------------
    # The HTTP body carries no spec (JobApprovalIn is {approved, input_text}),
    # so the server resumes with its own pending["spec"]. The job that ran
    # must therefore match what was displayed, field for field, except for
    # job_id -- which is legitimately new, because LangGraph re-executes
    # submit_draft from the top on resume and JobSpec.job_id's default_factory
    # reruns with it.
    mismatches = []
    for field in ("method", "engine"):
        if job.get(field) != spec_before.get(field):
            mismatches.append(f"{field}: approved={spec_before.get(field)!r} ran={job.get(field)!r}")
    for k, v in (spec_before.get("params") or {}).items():
        if k.startswith("_"):
            continue
        if (job.get("params") or {}).get(k) != v:
            mismatches.append(f"params.{k}: approved={v!r} ran={(job.get('params') or {}).get(k)!r}")
    check("H14 the job that ran matches the spec that was approved", not mismatches,
          "; ".join(mismatches))

    check("H15 await_job returned a summary to assert against",
          bool(job.get("summary")), str(list((job.get("summary") or {}).keys()))[:200])

    record_turn("H-gate", "PASS", t3, f"job {job_id} {job.get('status')}",
                job_id=job_id, energy=(job.get("summary") or {}).get("energy_hartree"))

    s.close()
    cleanup_user(admin, uid)
    summary()


if __name__ == "__main__":
    main()
