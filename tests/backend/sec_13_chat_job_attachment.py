#!/usr/bin/env python3
"""Attaching a job to a conversation is a read of that job.
Regression test for R-003.

    QC_AGENT_TEST_BASE_URL=https://127.0.0.1:8444 PYTHONPATH=$PWD \
      python3 tests/backend/sec_13_chat_job_attachment.py

R-003. `POST /api/threads/{id}/messages` and
`POST /api/threads/{id}/troubleshoot/{job_id}` both checked that the caller
owned the CONVERSATION and nothing else. A conversation is free: anyone can
create one. So a user could open their own thread, name someone else's job in
`job_ids`, and the turn would expand it into a synthetic context message
carrying `job_context_summary()`, which is around twenty thousand characters
of that job's numeric tables. The troubleshoot route did the same for a failed
job's engine output, which is composed mechanically from the job's own files.

The shape of the fix was already in the same file. `tag_job_frame`, three
hundred lines above, calls `check_owner_or_admin("job", ...)` on the id in its
own body. It was applied to one of the three routes that take a job id, which
is the habit R-005 is about. `_require_attachments` is now the one place all
three ask, and it covers `plot_ids` too, since those ride in on the same
request and become context messages the same way.

Two halves, timed differently (see the tracker's rule 2). The source-level
checks run against the working tree at step time. The live probes need the
deployment rebuilt onto the fixed code, so before the gate they fail, and
their failure IS the finding.

The probe reads only. It attaches another user's job to its own thread and
looks at what comes back; it submits nothing and deletes the thread and the
account it created.
"""
from __future__ import annotations

import inspect
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO))

from tests.fixtures import admin_client, check, mint_invite, register, skip, summary  # noqa: E402

print("R-003: a job id in a chat request is checked like a job id anywhere else\n")

print("1. the routes ask, in the source")
from server.routes import chat as chat_route  # noqa: E402

for fn in ("post_message", "troubleshoot_job"):
    src = inspect.getsource(getattr(chat_route, fn))
    check(f"{fn} calls _require_attachments", "_require_attachments" in src, "",
          "it still checks only that the caller owns the conversation")

helper = inspect.getsource(chat_route._require_attachments)
check("_require_attachments checks jobs", 'check_owner_or_admin("job"' in helper)
check("and plots, which ride in on the same request", 'check_owner_or_admin("plot"' in helper)
check("and 404s an id that names no job at all", "No such job" in helper)

print("\n2. the boundary, live")
admin = admin_client()

# Someone else's job: any job the deployment already holds that has an owner.
owned_job = None
for row in admin.get("/api/jobs").json():
    r = admin.get(f"/api/jobs/{row['job_id']}")
    if r.status_code == 200:
        owned_job = row["job_id"]
        break

if owned_job is None:
    skip("the live probe", "this deployment holds no job to attach")
else:
    tok = mint_invite(admin)
    b, b_user = register(tok, password="R003-probe-passphrase-long-enough!")
    # Confirm the probe account really is a stranger to this job before
    # concluding anything from what the chat route does with it.
    direct = b.get(f"/api/jobs/{owned_job}")
    if direct.status_code == 200:
        skip("the live probe",
             f"job {owned_job} is readable by any user through the ordinary job "
             f"route too, so it is unowned and proves nothing here")
    else:
        thread = b.post("/api/threads", json={}).json()
        tid = thread.get("thread_id") or thread.get("id")
        r = b.post(f"/api/threads/{tid}/messages",
                   json={"text": "what is in this job?", "job_ids": [owned_job]})
        check("attaching another user's job to your own thread is refused",
              r.status_code in (403, 404), f"HTTP {r.status_code}",
              f"HTTP {r.status_code}: the turn was accepted")

        if r.status_code == 202:
            # The turn is running on a background thread. Wait for it and
            # read back what actually landed in the caller's conversation,
            # so the finding is measured rather than inferred.
            for _ in range(30):
                time.sleep(1)
                state = b.get(f"/api/threads/{tid}/state").json()
                msgs = state.get("messages") or []
                if any(owned_job in str(m) for m in msgs):
                    break
            blob = str(state.get("messages") or [])
            check("and no part of it reached the caller's conversation",
                  owned_job not in blob, "",
                  f"the job's context is in the thread ({len(blob)} chars of state)")

        r = b.post(f"/api/threads/{tid}/troubleshoot/{owned_job}")
        check("troubleshooting another user's job is refused",
              r.status_code in (403, 404), f"HTTP {r.status_code}",
              f"HTTP {r.status_code}: 409 would mean the job was read and found "
              f"not to have failed, which is already a read")

        r = b.post(f"/api/threads/{tid}/messages",
                   json={"text": "hello", "job_ids": ["deadbeefdead"]})
        check("a job id that names nothing is a 404, not a silent no-op",
              r.status_code == 404, f"HTTP {r.status_code}")

        b.delete(f"/api/threads/{tid}")
        b.post("/api/auth/logout")
        admin.delete(f"/api/admin/users/{b_user['id']}")

summary()
