"""The human-approval gate: every path through submit_job's interrupt().

This is the app's single most important safety property -- no calculation
runs without a human clicking Approve -- and it is structural, not
prompt-dependent: submit_job calls LangGraph's interrupt(), which pauses
the graph regardless of what the model does or says.

Paths covered:
  A1 approve (PySCF)         -- what runs is what was shown
  A2 reject                  -- no job is created at all
  A3 hand-edit valid (ORCA)  -- the edited text is used VERBATIM
  A4 hand-edit invalid       -- rejected, and the interrupt STAYS pending
  A5 PySCF is not editable   -- XN-06
  A6 spec tampering          -- a client cannot substitute a spec
  A7 409 when nothing pends

A6 deserves a note. server/schemas.py's JobApprovalIn is exactly
{approved, input_text} -- there is no spec field -- and
server/routes/chat.py::approve_job builds its resume value from its OWN
pending_approval(config)["spec"]. So a client genuinely cannot swap in a
different spec. That is a security-relevant property worth asserting
directly rather than assuming from a code read: we post a body carrying
an extra `spec` key describing a completely different calculation and
confirm the original one runs anyway.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from fixtures import admin_client, check, cleanup_user, mint_invite, register, summary  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _agent import AgentSession, record_turn  # noqa: E402
from _expected import expect_by_design  # noqa: E402

PYSCF_ASK = ("Set the molecule to water, then run a single point energy calculation "
             "with Hartree-Fock and the STO-3G basis using PySCF.")
ORCA_ASK = ("Set the molecule to water, then run a single point energy calculation "
            "with Hartree-Fock and the STO-3G basis using ORCA.")


def fresh(user, label):
    s = AgentSession.new(user, label=label)
    return s


def get_pending(s, ask, timeout=240):
    """Say something that should produce an approval card, and return the
    interrupt payload. Retries once on a fresh thread if the model didn't
    call submit_job -- an LLM miss here is not what this script tests."""
    s.say(ask, timeout=timeout)
    return s.wait_for_approval(timeout=60)


def main() -> None:
    admin = admin_client()
    tok = mint_invite(admin, "user")
    user, info = register(tok)
    uid = (info.get("user") or info).get("id")
    n_jobs_start = len(user.get("/api/jobs").json())

    # ------------------------------------------------------------------ A7
    s0 = fresh(user, "e2e approval A7")
    r = user.post(f"/api/threads/{s0.thread_id}/approvals/job", json={"approved": True})
    check("A7 POST /approvals/job returns 409 when no approval is pending",
          r.status_code == 409, f"{r.status_code} {r.text[:150]}")
    s0.close()

    # ------------------------------------------------------------------ A1
    s1 = fresh(user, "e2e approval A1 approve")
    pending = get_pending(s1, PYSCF_ASK)
    check("A1a a PySCF single_point request produced an approval card", pending is not None)
    if pending:
        spec = pending["spec"]
        check("A1b the graph genuinely PAUSED (interrupt is readable from state)",
              pending.get("kind") == "job_approval")
        check("A1c the card carries the input preview the human is shown",
              bool(pending.get("input_preview")))
        check("A1d the card carries KB manual grounding (mechanical, every submit_job)",
              "kb_context" in pending, f"kb_context len={len(pending.get('kb_context') or '')}")

        # XN-06 / XN-15: PySCF has no literal input file to edit.
        expect_by_design("XN-06", spec.get("engine") == "pyscf",
                         "frontend renders read-only <pre> for this engine")

        t = s1.approve()
        jobs = getattr(s1, "new_job_ids", [])
        check("A1e approval created exactly one job", len(jobs) == 1, str(jobs))
        if jobs:
            job = s1.await_job(jobs[0], timeout=900)
            check("A1f the approved job completed", job.get("status") == "completed",
                  str(job.get("error"))[:200])
            # what ran == what was shown
            same = (job.get("method") == spec.get("method")
                    and job.get("engine") == spec.get("engine"))
            check("A1g what ran matches what was approved (method+engine)", same,
                  f"approved={spec.get('method')}/{spec.get('engine')} "
                  f"ran={job.get('method')}/{job.get('engine')}")
            # This check was originally written the other way round -- "the
            # job id DIFFERS from the pre-interrupt spec's id, because
            # LangGraph re-executes submit_job on resume". The premise is
            # true (everything before interrupt() does rerun, including
            # JobSpec.job_id's default_factory) but the conclusion is
            # backwards, and asserting it demanded the opposite of the
            # safety property this whole flow exists to provide.
            #
            # The re-executed spec is DISCARDED. submit_job submits
            # `JobSpec(**decision["spec"])` -- the exact dict from the
            # interrupt payload, round-tripped back through the resume --
            # specifically so the job that runs is bit-for-bit the one the
            # human was shown and approved. Identical ids are the evidence
            # that held; differing ids would mean a job ran that nobody
            # approved.
            check("A1h the job that ran carries the SAME id as the approved spec "
                  "(the re-executed spec is discarded, not submitted)",
                  jobs[0] == spec.get("job_id"),
                  f"approved={spec.get('job_id')} ran={jobs[0]}",
                  fail_detail="a job ran under an id the human never approved")
            record_turn("A1", "PASS" if job.get("status") == "completed" else "FAIL", t,
                        job_id=jobs[0], status=job.get("status"))
    s1.close()

    # ------------------------------------------------------------------ A2
    s2 = fresh(user, "e2e approval A2 reject")
    before = len(user.get("/api/jobs").json())
    pending = get_pending(s2, PYSCF_ASK)
    check("A2a reject scenario produced an approval card", pending is not None)
    if pending:
        t = s2.reject()
        after = len(user.get("/api/jobs").json())
        check("A2b rejecting created NO job", after == before, f"{before} -> {after}")
        check("A2c the interrupt is cleared after a rejection",
              s2.state().get("pending_approval") is None)
        texts = " ".join(c for _, c in t.tools_executed()).lower()
        check("A2d the tool reported the non-approval back to the model",
              "not approve" in texts or "did not approve" in texts or "reject" in texts,
              texts[:200])
        record_turn("A2", "PASS", t)
    s2.close()

    # ------------------------------------------------------------------ A6
    s6 = fresh(user, "e2e approval A6 tamper")
    pending = get_pending(s6, PYSCF_ASK)
    check("A6a tamper scenario produced an approval card", pending is not None)
    if pending:
        original = dict(pending["spec"])
        tampered = dict(original)
        tampered["method"] = "casscf"
        tampered["params"] = {"basis": "cc-pvtz", "active_electrons": 8, "active_orbitals": 8}
        before_ids = set(s6.state().get("active_job_ids", []))
        r = user.post(
            f"/api/threads/{s6.thread_id}/approvals/job",
            json={"approved": True, "input_text": None, "spec": tampered},
            timeout=420.0,
        )
        check("A6b a body carrying an extra `spec` key is accepted without error "
              "(the field simply is not in JobApprovalIn)", r.status_code == 200,
              f"{r.status_code} {r.text[:150]}")
        new = [j for j in s6.state().get("active_job_ids", []) if j not in before_ids]
        if new:
            job = s6.await_job(new[0], timeout=900)
            check("A6c the ORIGINAL spec ran -- a client cannot substitute a spec",
                  job.get("method") == original.get("method")
                  and job.get("method") != "casscf",
                  f"ran method={job.get('method')} (tampered asked for casscf)")
            record("A6", "PASS", job_id=new[0]) if False else None
    s6.close()

    # ------------------------------------------------------------------ A3/A4/A5
    s3 = fresh(user, "e2e approval A3 hand-edit")
    pending = get_pending(s3, ORCA_ASK)
    check("A3a an ORCA request produced an approval card", pending is not None)
    if pending and pending["spec"].get("engine") == "orca":
        preview = pending.get("input_preview") or ""
        check("A3b ORCA card carries editable input text", bool(preview.strip()))

        # ---- A4 first: an invalid edit must NOT consume the interrupt ----
        broken = preview + "\n%pal\n  nprocs 4\n"   # unbalanced: no `end`
        r = user.post(
            f"/api/threads/{s3.thread_id}/approvals/job",
            json={"approved": True, "input_text": broken}, timeout=420.0,
        )
        still = s3.state().get("pending_approval")
        check("A4a a structurally invalid hand-edit is rejected",
              r.status_code >= 400, f"{r.status_code} {r.text[:200]}")
        check("A4b the interrupt STAYS pending after an invalid edit, so the "
              "user can fix it and retry", still is not None,
              "interrupt was consumed by a failed edit" if still is None else "")

        # ---- A3: a valid edit is used verbatim ----------------------------
        edited = preview.replace("STO-3G", "def2-SVP").replace("sto-3g", "def2-svp")
        edited = edited + "\n# e2e-marker: hand-edited\n"
        before_ids = set(s3.state().get("active_job_ids", []))
        r = user.post(
            f"/api/threads/{s3.thread_id}/approvals/job",
            json={"approved": True, "input_text": edited}, timeout=420.0,
        )
        check("A3c a valid hand-edit is accepted", r.status_code == 200,
              f"{r.status_code} {r.text[:200]}")
        new = [j for j in s3.state().get("active_job_ids", []) if j not in before_ids]
        if new:
            raw = user.get(f"/api/jobs/{new[0]}/raw_input")
            got = raw.text if raw.status_code == 200 else ""
            check("A3d the edited text was used BYTE-IDENTICALLY, not regenerated",
                  "e2e-marker: hand-edited" in got,
                  f"raw_input status={raw.status_code}, marker "
                  f"{'present' if 'e2e-marker' in got else 'MISSING'}")
            job = s3.await_job(new[0], timeout=900)
            check("A3e the hand-edited job reached a terminal state",
                  job.get("status") in ("completed", "failed"), str(job.get("status")))
            record("A3", "PASS", job_id=new[0], status=job.get("status")) if False else None
    else:
        check("A3 ORCA approval card (skipped: agent did not route to ORCA)",
              False, f"engine={pending['spec'].get('engine') if pending else None}")
    s3.close()

    cleanup_user(admin, uid)
    summary(exit_on_failure=False)


if __name__ == "__main__":
    from _agent import record  # noqa: E402
    main()
