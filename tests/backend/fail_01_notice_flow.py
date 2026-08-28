#!/usr/bin/env python3
"""A failed job notifies the user and starts nothing.

    PYTHONPATH=$PWD python3 tests/backend/fail_01_notice_flow.py

This is the regression test for removing auto-retry. The old behaviour was
that a failed job silently started an agent turn which investigated and
resubmitted a corrected job on its own initiative, up to a hard cap. It
spent someone's compute on a guess they had never agreed to -- a CASSCF run
on this host can be hours -- and it hid the failure, because the user's
first sign of trouble was a new approval card rather than a plain statement
that their calculation had died.

The load-bearing assertion here is a negative one: **the watcher must not
invoke the agent for a failed job.** `invoke_turn_if_idle` is replaced with a
sentinel that records calls, so a future change that quietly reintroduces
an automatic investigation fails this script rather than being discovered
by a user whose GPU time it spent.

The rest of the flow:

- the notice is a real checkpointed message, not just an SSE event, so a
  user who closed the tab finds it waiting (the leave-and-return workflow
  is the whole reason jobs run detached);
- it carries structured `notice` data, so the UI renders a card with a
  Troubleshoot button rather than pattern-matching on prose;
- polling twice does not notify twice;
- declining -- simply not pressing Troubleshoot -- leaves the conversation
  untouched;
- accepting composes a message carrying the job's real output tail,
  gathered by code rather than chosen by the model.

Runs in-process: a real PySCF job that fails in seconds on a deliberately
invalid basis set, a real JobManager, a real checkpointer. No server, no
network, no LLM call (the notice path never invokes one, which is precisely
what is being tested).
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
from app.agent.troubleshoot import compose_troubleshoot_message  # noqa: E402
from app.chemistry.jobs.base import JobSpec, get_job_manager, read_result  # noqa: E402

failures: list[str] = []
checks = 0

WATER = {
    "name": "water",
    "symbols": ["O", "H", "H"],
    "coords": [[0.0, 0.0, 0.117], [0.0, 0.757, -0.467], [0.0, -0.757, -0.467]],
    "charge": 0,
    "multiplicity": 1,
}

# Deliberately not a real basis set, and deliberately not a near-miss:
# param_normalize.normalize_basis rewrites Pople-style typos like "6-31gd"
# into something valid, which would make the job succeed and the test
# vacuous. This string resembles nothing and is left untouched, so PySCF
# raises and the job genuinely fails.
BOGUS_BASIS = "definitely-not-a-basis-set"


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
    print("\n== submit a job that really fails ==")
    thread = thread_registry.create_thread(label="qatest_fail_notice")
    thread_id = thread["thread_id"]
    config = {"configurable": {"thread_id": thread_id}}

    mgr = get_job_manager()
    spec = JobSpec(
        method="single_point", engine="pyscf", molecule=WATER,
        params={"method": "hf", "basis": BOGUS_BASIS},
    )
    job_id = mgr.submit(spec)
    thread_registry.set_active_job_ids(thread_id, [job_id])

    deadline = time.time() + 180
    status = None
    while time.time() < deadline:
        status = (mgr.status(job_id) or {}).get("status")
        if status in {"completed", "failed", "cancelled"}:
            break
        time.sleep(1.0)
    check("the job reached a terminal status", status in {"completed", "failed", "cancelled"},
          f"status={status}")
    check("the job FAILED (an invalid basis set is a real failure)", status == "failed",
          f"status={status}")
    if status != "failed":
        print("\n[FAIL] cannot test the failure flow without a failed job")
        return 1
    result = read_result(job_id) or {}
    check("a real error was recorded", bool(result.get("error")), str(result.get("error"))[:80])

    print("\n== the watcher notices, and starts NO agent turn ==")
    invoked: list = []

    def _sentinel_invoke_turn(*args, **kwargs):
        invoked.append((args, kwargs))
        raise AssertionError(
            "invoke_turn_if_idle was called for a failed job -- auto-retry has been reintroduced"
        )

    real_invoke_turn = jw.invoke_turn_if_idle
    jw.invoke_turn_if_idle = _sentinel_invoke_turn
    events: list[dict] = []
    try:
        watcher = jw.JobWatcher(on_event=lambda tid, ev: events.append(ev))
        watcher._poll_once()
        before_second = len(_notice_messages(read_state(config)))
        watcher._poll_once()
        after_second = len(_notice_messages(read_state(config)))
    finally:
        jw.invoke_turn_if_idle = real_invoke_turn

    check("the agent was NOT invoked for the failed job", not invoked,
          f"{len(invoked)} invocation(s)")

    print("\n== the notice is a real, persisted message ==")
    # Read back through read_state rather than trusting the return value of
    # the call that wrote it: that is what proves it was checkpointed and
    # will still be there after a reload or a logout.
    state = read_state(config)
    notices = _notice_messages(state)
    check("exactly one notice message is in the conversation", len(notices) == 1,
          f"{len(notices)} found")
    if notices:
        payload = (notices[0].additional_kwargs or {}).get("nexus_notice") or {}
        check("the notice is marked as a job failure", payload.get("kind") == "job_failed",
              str(payload.get("kind")))
        check("the notice names the failed job", payload.get("job_id") == job_id,
              str(payload.get("job_id")))
        check("the notice offers the troubleshoot action",
              payload.get("action") == "troubleshoot", str(payload.get("action")))
        text = notices[0].content
        check("the notice says plainly that nothing was resubmitted",
              "resubmitted" in text.lower(), text[:100])
        check("the notice names the job id in its text", job_id in text, text[:100])

    check("polling again does not notify twice", before_second == after_second,
          f"{before_second} -> {after_second}")

    print("\n== a job_failed event is published for live viewers ==")
    check("a job_failed SSE event was emitted",
          any(e.get("type") == "job_failed" and e.get("job_id") == job_id for e in events),
          str([e.get("type") for e in events]))

    print("\n== declining changes nothing ==")
    # "Declining" is simply not pressing the button. There is no decline
    # endpoint to call, and that is the point: the quiet path is the
    # default, so this asserts the conversation is untouched by doing
    # nothing at all.
    quiet_state = read_state(config)
    check("the conversation is unchanged when the user does nothing",
          len(quiet_state.get("messages", [])) == len(state.get("messages", [])),
          f"{len(state.get('messages', []))} -> {len(quiet_state.get('messages', []))}")

    print("\n== the route marks that message as the app's, not the user's ==")
    # The troubleshoot text is injected as a HumanMessage, because the served
    # model needs a user turn to answer. Without being marked it renders in
    # the user's own bubble, showing them "(system notice, not from the
    # user)" as though they had typed it. The route passes the flag by
    # keyword, so what a rename would break is the parameter itself.
    import inspect

    from server.routes.chat import _run_turn as _route_run_turn
    params = inspect.signature(_route_run_turn).parameters
    check("_run_turn still takes system_notice", "system_notice" in params,
          str(list(params)))
    source = inspect.getsource(sys.modules["server.routes.chat"])
    check("the troubleshoot route still sets it",
          '"system_notice": True' in source, "the flag is not passed anywhere")

    print("\n== accepting composes a message carrying real evidence ==")
    text = compose_troubleshoot_message(job_id)
    check("a troubleshoot message is composed for a failed job", text is not None)
    if text:
        check("it names the failed job", job_id in text, text[:80])
        check("it carries the engine's own output, gathered by code",
              "```" in text, text[:120])
        check("the invalid basis appears in the evidence",
              BOGUS_BASIS in text, "basis not found in composed message")
        check("it directs the model to the manuals rather than the paper search",
              "doc_type='manual'" in text and "search_academic_literature is not" not in text,
              "manual instruction missing")
        check("any proposed fix is routed through an approval card, not run directly",
              "approval card" in text, text[-120:])

    print("\n== a job that did not fail cannot be troubleshot ==")
    # This is the 409 branch of the troubleshoot route: a completed or
    # unknown job must not be able to start an investigation turn.
    check("an unknown job composes no message",
          compose_troubleshoot_message("ffffffffffff") is None)

    # Leave no qatest thread behind.
    thread_registry.delete_thread(thread_id)

    print(f"\n{checks - len(failures)}/{checks} checks passed")
    if failures:
        print(f"[FAIL] {len(failures)} check(s) failed")
        return 1
    print("[PASS] ALL CHECKS PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
