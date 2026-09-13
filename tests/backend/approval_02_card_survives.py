#!/usr/bin/env python3
"""An approval card is not destroyed by anything but answering it.
Regression test for R-013, R-017, R-018, R-034 and R-038.

    PYTHONPATH=$PWD python3 tests/backend/approval_02_card_survives.py

The approval gate is the safety property this whole application is built
around: nothing runs without a card the user answered, and the spec that runs
is the one the card showed. Five ways it could be voided, mis-answered or
never reached.

R-013: everything before `interrupt()` re-executes when the user clicks
Approve, and the chained path re-validated WITH the two checks that read
state outside the draft. If the source geometry job went away between the
card appearing and the click, a ready verdict became an incomplete one, the
interrupt was never reached, and the approval vanished with no error.
`submit_draft` has always turned those checks off for exactly this reason.

R-017: `update_state` discards a pending interrupt as thoroughly as invoking
the graph with new input does -- measured, and written up in
`append_notice_unless_card_pending`, and then applied to one of the seven
callers that do the same thing. The other six are the molecule panel's own
buttons and the attach-a-file path.

R-018: an approval is single-use, and a checkpoint failure after `submit()`
could leave the interrupt live. Whatever the answer to that, two workers must
never start on one job directory.

R-034: a submission in a mixed tool batch skips the app's own confirmation
node, and the ToolMessage told the model "the user has already been shown a
confirmation ... do not announce it again", which in that case nobody had.

R-038: `POST /messages` had no guard against posting while a card is open.
The browser disables the composer, but that is a frontend guarantee, and a
script, a stale tab or a second client can all do it.
"""
from __future__ import annotations

import inspect
import json
import sys
import tempfile
import threading
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO))

from tests.fixtures import check, summary  # noqa: E402

print("R-013: the card is built from a verdict the resume can reproduce\n")
from app.agent import tools as agent_tools  # noqa: E402

src = inspect.getsource(agent_tools._draft_command)
check("the chained path re-validates with check_external=False",
      "validate_draft(draft, state or {}, check_external=False)" in src, "",
      "the resume re-runs this validation with the external checks on, so a "
      "source job that disappeared makes the approval evaporate on click")

print("\nR-017: a panel action refuses rather than voiding a card")
from app.agent import graph as agent_graph  # noqa: E402

check("there is a dedicated exception for it", hasattr(agent_graph, "ApprovalCardOpen"), "")
guarded = []
for fn in ("clear_molecule", "remove_frame", "set_active_frame", "add_built_frame",
           "add_geometry_frames", "append_attached_file"):
    f = getattr(agent_graph, fn, None)
    if f is None:
        continue
    if "_refuse_if_card_pending" in inspect.getsource(f):
        guarded.append(fn)
check("every molecule-panel writer and the file attach are guarded",
      len(guarded) >= 6, f"{guarded}",
      f"only {guarded} are guarded; the rest silently discard a pending approval")
try:
    from server import main as server_main  # noqa: E402
    handlers = list(server_main.app.exception_handlers.values())
except Exception as exc:                                        # noqa: BLE001
    # server/main.py imports the exception type, so before the fix it cannot
    # even be imported. That is the finding, reported as one.
    handlers = []
    print(f"        (server.main could not be imported: {type(exc).__name__}: {exc})")
check("and the route layer turns that refusal into a 409, not a 500",
      any(getattr(h, "__name__", "") == "_approval_card_open" for h in handlers), "",
      "nothing maps it, so a guarded panel action would be a 500")

print("\nR-038: posting a message over an open card is refused")
try:
    from server.routes import chat as chat_route  # noqa: E402
    psrc_available = True
except Exception as exc:                                        # noqa: BLE001
    psrc_available = False
    print(f"        (server.routes.chat could not be imported: {exc})")

psrc = inspect.getsource(chat_route.post_message) if psrc_available else ""
check("post_message checks for a pending approval",
      "pending_approval(_config(thread_id))" in psrc, "",
      "invoking the graph with new input discards the interrupt, so the "
      "user's later Approve is a silent no-op")
check("and answers 409, mirroring approve_job's own refusal",
      "status_code=409" in psrc, "")

print("\nR-034: the tool text matches whether the app will speak")
check("there is a helper that asks", hasattr(agent_tools, "_app_will_confirm"), "")
fsrc = inspect.getsource(agent_tools._finish_submission)
check("the submission branch has both wordings", fsrc.count("_app_will_confirm") >= 2, "",
      "one branch still claims the user has been shown a confirmation "
      "regardless of whether the app's node will run")
check("and the mixed-batch wording tells the model to say it itself",
      "Nothing has been shown to the user about this yet" in fsrc, "")
check("while the id stays greppable in both, as e2e_12 requires",
      fsrc.count("id={job_id}") >= 2, "")


class _AI:
    def __init__(self, ids):
        self.tool_calls = [{"id": i, "name": "x", "args": {}} for i in ids]


_will_confirm = getattr(agent_tools, "_app_will_confirm", None)
check("a lone call means the app confirms",
      _will_confirm is not None and _will_confirm({"messages": [_AI(["a"])]}, "a") is True, "",
      "there is no such helper, so the wording cannot depend on the answer")
check("a mixed batch means the model has to",
      _will_confirm is not None and _will_confirm({"messages": [_AI(["a", "b"])]}, "a") is False,
      "")

print("\nR-018: one job id, one worker")
from app.chemistry.jobs import base as jobs_base  # noqa: E402

ssrc = inspect.getsource(jobs_base.JobManager.submit)
check("submit refuses to start a second worker on a non-terminal job",
      "was submitted again while still" in ssrc, "",
      "an approval card carries the job id, so a second approval of the same "
      "card enqueues the same directory twice")

tmp = Path(tempfile.mkdtemp(prefix="r018-"))
real_dir = jobs_base.JOBS_DIR
jobs_base.JOBS_DIR = tmp
try:
    jid = "already-running"
    (tmp / jid).mkdir()
    # spec.json as well as status.json: read_status treats a directory
    # without a spec as "not a job at all" (F-024), which is right, and a
    # fixture missing it would test nothing.
    (tmp / jid / "spec.json").write_text(json.dumps({"job_id": jid, "task": "single_point"}))
    (tmp / jid / "status.json").write_text(json.dumps({"status": "running", "message": "go"}))

    class _Sched:
        def __init__(self):
            self.enqueued = []

        def enqueue(self, job_id, owner):
            self.enqueued.append(job_id)

    mgr = object.__new__(jobs_base.JobManager)
    mgr._scheduler = _Sched()
    mgr._lock = threading.RLock()
    mgr._quota_lock = threading.RLock()
    mgr._futures = {}
    spec = jobs_base.JobSpec(task="single_point", subtype="gs", method="hf", engine="pyscf",
                             molecule={"symbols": ["H"], "coords": [[0, 0, 0]], "charge": 0,
                                       "multiplicity": 2},
                             params={"basis": "sto-3g"}, job_id=jid)
    returned = jobs_base.JobManager.submit(mgr, spec)
    check("the second submit returns the same id", returned == jid, returned)
    check("and enqueues nothing", mgr._scheduler.enqueued == [], f"{mgr._scheduler.enqueued}",
          "two workers would run in one job directory, each overwriting the "
          "other's status and result")
finally:
    jobs_base.JOBS_DIR = real_dir

summary()
