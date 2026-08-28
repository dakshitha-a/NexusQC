#!/usr/bin/env python3
"""A cancelled job says so plainly and starts no agent turn.

    PYTHONPATH=$PWD python3 tests/backend/cancel_01_notice_flow.py

The sibling of fail_01_notice_flow.py. A cancellation used to be grouped
with a completion and bought a full agent turn, whose notice read in part
"just acknowledge the cancellation briefly if it's relevant to what you say
next" -- an instruction that permits saying nothing at all. The user pressed
Cancel themselves, and the jobs panel has already flipped the row through
the job_update event before any of this runs, so the turn narrated a fact
the app held and the user had caused.

The load-bearing assertion is the same negative one fail_01 makes:
`invoke_turn_if_idle` is replaced with a sentinel that raises, so a change
that quietly puts cancellations back on the turn path fails here rather
than showing up as a minute of silence after a click.

The rest of the flow, and the parts that are easy to get wrong:

- the notice is a real checkpointed message, so a user who closed the tab
  finds it waiting;
- polling twice does not notify twice. This is the trap the bookkeeping
  exists for: the tick's own `seen` write lives after the agent turn, and a
  tick whose only terminal ids are cancellations now returns before ever
  reaching it, so without an explicit write here a single cancelled job
  would re-notify every two seconds forever;
- the notice names the job the way the job list does rather than by an
  internal task identifier.

Runs in-process against a real JobManager and a real checkpointer. No
server, no network, and no LLM call, which is the point.
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO))

from app.agent import job_watcher as jw  # noqa: E402
from app.agent import threads as thread_registry  # noqa: E402
from app.agent.graph import read_state  # noqa: E402
from app.chemistry.jobs.base import JobSpec, delete_job_dir, get_job_manager  # noqa: E402

failures: list[str] = []
checks = 0

WATER = {
    "name": "water",
    "symbols": ["O", "H", "H"],
    "coords": [[0.0, 0.0, 0.117], [0.0, 0.757, -0.467], [0.0, -0.757, -0.467]],
    "charge": 0,
    "multiplicity": 1,
}


def check(label: str, ok: bool, detail: str = "") -> None:
    global checks
    checks += 1
    if ok:
        print(f"  [PASS] {label}")
    else:
        print(f"  [FAIL] {label}" + (f" -- {detail}" if detail else ""))
        failures.append(label)


def _notice_messages(state: dict) -> list:
    out = []
    for m in state.get("messages", []):
        kwargs = getattr(m, "additional_kwargs", None) or {}
        if kwargs.get("nexus_notice"):
            out.append(m)
    return out


def main() -> int:
    print("\n== submit a job and cancel it ==")
    thread = thread_registry.create_thread(label="qatest_cancel_notice")
    thread_id = thread["thread_id"]
    config = {"configurable": {"thread_id": thread_id}}

    mgr = get_job_manager()
    # Cancelled immediately, so which side of the start boundary it lands on
    # does not matter: both paths write status "cancelled", which is all this
    # script cares about.
    spec = JobSpec(
        method="single_point", engine="pyscf", molecule=WATER,
        params={"method": "hf", "basis": "sto-3g"},
    )
    job_id = mgr.submit(spec)
    thread_registry.set_active_job_ids(thread_id, [job_id])
    mgr.cancel(job_id)

    deadline = time.time() + 120
    status = None
    while time.time() < deadline:
        status = (mgr.status(job_id) or {}).get("status")
        if status in {"completed", "failed", "cancelled"}:
            break
        time.sleep(0.5)
    check("the job reached a terminal status", status in {"completed", "failed", "cancelled"},
          f"status={status}")
    check("the job was CANCELLED", status == "cancelled", f"status={status}")
    if status != "cancelled":
        print("\n[FAIL] cannot test the cancellation flow without a cancelled job")
        try:
            delete_job_dir(job_id)
        except Exception:  # noqa: BLE001
            pass
        thread_registry.delete_thread(thread_id)
        return 1

    print("\n== the watcher notices, and starts NO agent turn ==")
    invoked: list = []

    def _sentinel_invoke_turn(*args, **kwargs):
        invoked.append((args, kwargs))
        raise AssertionError(
            "invoke_turn_if_idle was called for a cancelled job -- the acknowledgement "
            "turn has been reintroduced"
        )

    real_invoke_turn = jw.invoke_turn_if_idle
    jw.invoke_turn_if_idle = _sentinel_invoke_turn
    try:
        watcher = jw.JobWatcher(on_event=lambda tid, ev: None)
        watcher._poll_once()
        before_second = len(_notice_messages(read_state(config)))
        watcher._poll_once()
        after_second = len(_notice_messages(read_state(config)))
    finally:
        jw.invoke_turn_if_idle = real_invoke_turn

    check("the agent was NOT invoked for the cancelled job", not invoked,
          f"{len(invoked)} invocation(s)")

    print("\n== the notice is a real, persisted message ==")
    # Read back through read_state rather than trusting the return value of
    # the call that wrote it: that is what proves it was checkpointed and
    # survives a reload.
    state = read_state(config)
    notices = _notice_messages(state)
    check("exactly one notice message is in the conversation", len(notices) == 1,
          f"{len(notices)} found")
    if notices:
        payload = (notices[0].additional_kwargs or {}).get("nexus_notice") or {}
        check("the notice is marked as a cancellation", payload.get("kind") == "job_cancelled",
              str(payload.get("kind")))
        check("the notice names the cancelled job", payload.get("job_id") == job_id,
              str(payload.get("job_id")))
        text = notices[0].content
        check("it says the job was stopped as asked", "as you asked" in text.lower(), text[:120])
        check("it names the job id", job_id in text, text[:120])
        check("it names the job the way the job list does", "water" in text.lower(), text[:120])
        check("it does not leak an internal task identifier",
              "single_point" not in text and "subtype" not in text, text[:120])

    check("polling again does not notify twice", before_second == after_second,
          f"{before_second} -> {after_second}")

    try:
        delete_job_dir(job_id)
    except Exception as exc:  # noqa: BLE001
        print(f"  (cleanup) could not remove job {job_id}: {exc}")
    thread_registry.delete_thread(thread_id)

    print(f"\n{checks - len(failures)}/{checks} checks passed")
    if failures:
        print("FAILED:")
        for label in failures:
            print(f"  - {label}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
