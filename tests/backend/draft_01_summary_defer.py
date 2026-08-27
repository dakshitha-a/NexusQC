#!/usr/bin/env python3
"""Assembling a calculation outranks reporting on a finished one.

    PYTHONPATH=$PWD python3 tests/backend/draft_01_summary_defer.py

The bug this pins down was reported as "where is the card for the casscf
job?", asked twice in one conversation. A job finished while the user was
mid-draft, the watcher injected its "Job X finished, summarise it" notice
and ran a real agent turn, and that turn destroyed the approval card the
user was waiting for. The conversation ended up carrying five `submit_draft`
tool calls that no `ToolMessage` ever answered.

The destruction is the part worth stating plainly, because "a badly timed
message" would not justify any of this machinery. Invoking the graph with
new input while it sits at `submit_draft`'s `interrupt()` discards the
pending task: `interrupts` goes from one to zero, `next` goes from
`("tools",)` to `()`, the tool call stays unanswered forever, and the user's
later Approve is a silent no-op. `update_state` -- which looks far more
innocent, and is what a failed job's notice uses -- does exactly the same
thing. Both are asserted below, so nobody has to take that on trust.

What is checked here:

- a summary waits while a draft is being assembled, and while an approval
  card is open;
- it is not lost while it waits: the job stays unseen, and one turn delivers
  every job that finished during the hold;
- both endings release it, a submission and a rejection alike;
- the re-check happens **inside** the thread lock. This is the case that
  fails without the fix and passes with it: the watcher's pre-lock look at
  the state is useless on its own, because a drafting turn runs for a
  minute or more while the watcher polls every two seconds, so it takes its
  snapshot before the draft exists, blocks on the lock, and is let in at
  exactly the wrong moment;
- a failed job still speaks up immediately during a draft, but waits while a
  card is open;
- an abandoned draft does not suppress summaries for good.

Runs in-process against the real graph, the real checkpointer, the real
state reducers and a real JobManager. No server and no LLM: the graph is
parked at an interrupt by writing an assistant tool call into state with
`as_node="agent"` and resuming, which is what the model would have produced.
"""
from __future__ import annotations

import sys
import threading
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO))

from langchain_core.messages import AIMessage  # noqa: E402

from app.agent import graph as ag  # noqa: E402
from app.agent import job_watcher as jw  # noqa: E402
from app.agent import threads as thread_registry  # noqa: E402
from app.agent.graph import (  # noqa: E402
    draft_hold_reason, get_graph, invoke_turn_if_idle, pending_approval, read_state,
)
from app.agent.state import CLEAR_DRAFT_STATUS  # noqa: E402
from app.chemistry.jobs.base import (  # noqa: E402
    JobSpec, delete_job_dir, get_job_manager,
)

failures: list[str] = []
checks = 0

WATER = {
    "name": "water",
    "symbols": ["O", "H", "H"],
    "coords": [[0.0, 0.0, 0.117], [0.0, 0.757, -0.467], [0.0, -0.757, -0.467]],
    "charge": 0,
    "multiplicity": 1,
}

# Same reasoning as fail_01_notice_flow.py: not a near-miss, so
# param_normalize cannot rewrite it into something that works and make the
# failure branch untestable.
BOGUS_BASIS = "definitely-not-a-basis-set"

created_jobs: list[str] = []


def check(label: str, ok: bool, detail: str = "") -> None:
    global checks
    checks += 1
    if ok:
        print(f"  [PASS] {label}")
    else:
        print(f"  [FAIL] {label}" + (f" -- {detail}" if detail else ""))
        failures.append(label)


def submit(basis: str) -> str:
    """One cheap ground-state single point. `method` is the level of theory
    and `task`/`subtype` is what the job is -- they are separate axes in the
    v2 taxonomy, and swapping them produces a job that fails for reasons
    that have nothing to do with what is being tested here."""
    job_id = get_job_manager().submit(JobSpec(
        task="single_point", subtype="gs", method="hf", engine="pyscf",
        molecule=WATER, params={"basis": basis}))
    created_jobs.append(job_id)
    return job_id


def await_terminal(job_id: str, timeout: float = 240.0) -> str:
    mgr = get_job_manager()
    deadline = time.time() + timeout
    while time.time() < deadline:
        status = (mgr.status(job_id) or {}).get("status")
        if status in {"completed", "failed", "cancelled"}:
            return status
        time.sleep(0.5)
    return (mgr.status(job_id) or {}).get("status") or "unknown"


class Recorder:
    """Stands in for the agent turn and the SSE hub.

    `invoke_turn_if_idle` is patched at its use site in job_watcher rather
    than at its definition, so the real one is still there for the in-lock
    test further down. The stand-in delegates the hold decision to the real
    gate so that "did it defer?" is answered by production code, and only
    the LLM turn itself is faked.
    """

    def __init__(self) -> None:
        self.notices: list[str] = []
        self.events: list[dict] = []

    def invoke_turn_if_idle(self, input_dict, config, on_start=None):
        with ag._lock_for_thread(config):
            if draft_hold_reason(config) is not None:
                return None
            if on_start is not None:
                on_start()
            self.notices.append(input_dict["messages"][0].content)
            return read_state(config)

    def on_event(self, thread_id: str, event: dict) -> None:
        self.events.append(event)


def poll(rec: Recorder) -> None:
    real = jw.invoke_turn_if_idle
    jw.invoke_turn_if_idle = rec.invoke_turn_if_idle
    try:
        jw.JobWatcher(on_event=rec.on_event)._poll_once()
    finally:
        jw.invoke_turn_if_idle = real


def seen_ids(thread_id: str) -> set:
    return jw._read_seen(thread_id)


def park_at_card(config: dict) -> None:
    """Drive the real graph to a pending submit_draft interrupt, no LLM.

    Writing the assistant's tool call in `as_node="agent"` leaves the graph
    with the tools node queued, exactly as a real turn would; resuming with
    `None` then runs it and hits `interrupt()`.
    """
    get_graph().update_state(config, {"messages": [AIMessage(
        content="", tool_calls=[{"name": "submit_draft", "args": {}, "id": f"c{time.time_ns()}"}],
    )]}, as_node="agent")
    get_graph().invoke(None, config)


def main() -> int:
    thread = thread_registry.create_thread(label="qatest_draft_defer")
    thread_id = thread["thread_id"]
    config = {"configurable": {"thread_id": thread_id}}
    graph = get_graph()

    print("\n== two jobs finish while the user is drafting ==")
    good_a = submit("sto-3g")
    good_b = submit("sto-3g")
    thread_registry.set_active_job_ids(thread_id, [good_a, good_b])
    graph.update_state(config, {
        "molecule": WATER,
        "job_draft": {"task": "single_point", "method": "casscf", "engine": "pyscf", "params": {}},
        "draft_status": {"stage": "drafting", "at": time.time()},
    })
    for job_id in (good_a, good_b):
        status = await_terminal(job_id)
        check(f"job {job_id[:6]} completed", status == "completed", f"status={status}")

    check("the gate reports a drafting hold", draft_hold_reason(config) == "draft",
          str(draft_hold_reason(config)))

    rec = Recorder()
    poll(rec)
    poll(rec)
    check("no summary turn ran while the draft was open", rec.notices == [],
          f"{len(rec.notices)} turn(s)")
    check("neither job was marked seen, so nothing is lost",
          not (seen_ids(thread_id) & {good_a, good_b}), str(seen_ids(thread_id)))
    check("no turn_start was announced for a turn that never ran",
          not any(e.get("type") == "turn_start" for e in rec.events),
          str([e.get("type") for e in rec.events]))
    check("the jobs panel still hears that the jobs finished",
          {e.get("job_id") for e in rec.events if e.get("type") == "job_update"} >= {good_a, good_b},
          str([e for e in rec.events if e.get("type") == "job_update"]))

    print("\n== submitting the draft releases both at once ==")
    graph.update_state(config, {"draft_status": CLEAR_DRAFT_STATUS})
    check("the gate no longer holds", draft_hold_reason(config) is None,
          str(draft_hold_reason(config)))
    rec = Recorder()
    poll(rec)
    check("exactly one summary turn ran, not one per job", len(rec.notices) == 1,
          f"{len(rec.notices)} turn(s)")
    if rec.notices:
        check("that one notice names both jobs held during the draft",
              good_a in rec.notices[0] and good_b in rec.notices[0], rec.notices[0][:160])
    check("both jobs are now marked seen",
          {good_a, good_b} <= seen_ids(thread_id), str(seen_ids(thread_id)))
    check("the turn announced itself and closed",
          [e.get("type") for e in rec.events].count("turn_start") == 1
          and [e.get("type") for e in rec.events].count("turn_complete") == 1,
          str([e.get("type") for e in rec.events]))

    print("\n== an open approval card holds summaries too, and survives ==")
    good_c = submit("sto-3g")
    thread_registry.set_active_job_ids(thread_id, [good_c])
    graph.update_state(config, {"job_draft": {
        "task": "single_point", "subtype": "gs", "method": "hf",
        "engine": "pyscf", "params": {"basis": "sto-3g"}}})
    park_at_card(config)
    card = pending_approval(config)
    check("the graph is parked at a real approval card", card is not None,
          str(card)[:80] if card else "no interrupt")
    check("the gate reports an approval hold", draft_hold_reason(config) == "approval",
          str(draft_hold_reason(config)))
    status = await_terminal(good_c)
    check(f"job {good_c[:6]} completed", status == "completed", f"status={status}")

    rec = Recorder()
    poll(rec)
    check("no summary turn ran while the card was open", rec.notices == [],
          f"{len(rec.notices)} turn(s)")
    check("the approval card is still there afterwards", pending_approval(config) is not None)
    check("the job is still unseen", good_c not in seen_ids(thread_id))

    print("\n== the destruction this exists to prevent is real ==")
    # A throwaway thread, parked the same way, so the assertion below can be
    # made without wrecking the card the rest of this script is using.
    victim = thread_registry.create_thread(label="qatest_draft_victim")
    vconfig = {"configurable": {"thread_id": victim["thread_id"]}}
    graph.update_state(vconfig, {"molecule": WATER, "job_draft": {
        "task": "single_point", "subtype": "gs", "method": "hf",
        "engine": "pyscf", "params": {"basis": "sto-3g"}}})
    park_at_card(vconfig)
    check("the victim thread has a card", pending_approval(vconfig) is not None)
    ag.append_notice(vconfig, "an ungated notice")
    check("append_notice DESTROYS a pending approval card, which is why the "
          "failure notice is gated on it", pending_approval(vconfig) is None,
          "the card survived; if this is now true the gate can be relaxed")

    print("\n== the re-check happens inside the thread lock ==")
    # The real failure mode, reproduced. The watcher looks at the state
    # while a drafting turn is still running, sees nothing to hold for,
    # then blocks on the lock. Without an in-lock re-check it is released
    # straight into the draft that appeared meanwhile.
    lock_thread = thread_registry.create_thread(label="qatest_draft_race")
    lconfig = {"configurable": {"thread_id": lock_thread["thread_id"]}}
    check("no hold before the race starts", draft_hold_reason(lconfig) is None)

    lock = ag._lock_for_thread(lconfig)
    outcome: list = []
    released = threading.Event()

    def _contender():
        # Enters invoke_turn_if_idle having already "decided" to run, and
        # blocks acquiring the lock.
        outcome.append(invoke_turn_if_idle({"messages": [AIMessage(content="(notice)")]}, lconfig))

    lock.acquire()
    t = threading.Thread(target=_contender, daemon=True)
    t.start()
    time.sleep(0.5)
    # The drafting turn commits its draft, then finishes and drops the lock.
    get_graph().update_state(lconfig, {"draft_status": {"stage": "drafting", "at": time.time()}})
    lock.release()
    released.set()
    t.join(timeout=30)
    check("the contending turn deferred instead of interrupting the draft "
          "that appeared while it waited", outcome == [None], str(outcome))

    print("\n== a failed job still speaks up mid-draft, but not over a card ==")
    bad = submit(BOGUS_BASIS)
    fail_thread = thread_registry.create_thread(label="qatest_draft_failnotice")
    fconfig = {"configurable": {"thread_id": fail_thread["thread_id"]}}
    thread_registry.set_active_job_ids(fail_thread["thread_id"], [bad])
    graph.update_state(fconfig, {
        "draft_status": {"stage": "drafting", "at": time.time()}})
    status = await_terminal(bad)
    check("the bogus-basis job really failed", status == "failed", f"status={status}")

    rec = Recorder()
    poll(rec)
    notices = [m for m in read_state(fconfig).get("messages", [])
               if (getattr(m, "additional_kwargs", None) or {}).get("nexus_notice")]
    check("the death notice arrives during a draft rather than waiting",
          len(notices) == 1, f"{len(notices)} notice(s)")
    check("it is still only a notice, with no agent turn", rec.notices == [],
          f"{len(rec.notices)} turn(s)")

    # Same thread, now with a card open: the notice must wait.
    bad2 = submit(BOGUS_BASIS)
    thread_registry.set_active_job_ids(fail_thread["thread_id"], [bad2])
    graph.update_state(fconfig, {"molecule": WATER, "job_draft": {
        "task": "single_point", "subtype": "gs", "method": "hf",
        "engine": "pyscf", "params": {"basis": "sto-3g"}}})
    park_at_card(fconfig)
    check("a card is open on the failure thread", pending_approval(fconfig) is not None)
    status = await_terminal(bad2)
    check("the second bogus job failed too", status == "failed", f"status={status}")
    rec = Recorder()
    poll(rec)
    after = [m for m in read_state(fconfig).get("messages", [])
             if (getattr(m, "additional_kwargs", None) or {}).get("nexus_notice")]
    check("the death notice waits while a card is open", len(after) == len(notices),
          f"{len(notices)} -> {len(after)}")
    check("the card is intact", pending_approval(fconfig) is not None)
    check("the failed job stays unseen so the notice is not lost",
          bad2 not in seen_ids(fail_thread["thread_id"]))

    print("\n== an abandoned draft does not hold summaries for ever ==")
    stale = thread_registry.create_thread(label="qatest_draft_stale")
    sconfig = {"configurable": {"thread_id": stale["thread_id"]}}
    graph.update_state(sconfig, {"draft_status": {
        "stage": "drafting", "at": time.time() - (ag.DRAFT_HOLD_SECONDS + 60)}})
    check("a draft older than the hold window no longer holds",
          draft_hold_reason(sconfig) is None, str(draft_hold_reason(sconfig)))
    graph.update_state(sconfig, {"draft_status": {"stage": "drafting", "at": time.time()}})
    check("a fresh draft on the same thread holds again",
          draft_hold_reason(sconfig) == "draft", str(draft_hold_reason(sconfig)))

    real_window = ag.DRAFT_HOLD_SECONDS
    ag.DRAFT_HOLD_SECONDS = 0
    try:
        graph.update_state(sconfig, {"draft_status": {
            "stage": "drafting", "at": time.time() - 10_000_000}})
        check("with the window disabled the hold never expires",
              draft_hold_reason(sconfig) == "draft", str(draft_hold_reason(sconfig)))
    finally:
        ag.DRAFT_HOLD_SECONDS = real_window

    print("\n== the two endings, and only those, clear the flag ==")
    # At the tool level rather than through the graph. Resuming a real card
    # runs the tools node and then the agent node, i.e. a live LLM call,
    # which is exactly the dependency the rest of this script avoids; the
    # Command these functions return is where the decision actually lives.
    # Same technique as casreco_05_reporting_hygiene.py.
    from app.agent import tools as agt  # noqa: PLC0415

    started = agt.start_job_draft.func(
        task="single_point", method="hf", engine="pyscf",
        state={"molecule": WATER}, tool_call_id="c-start")
    check("starting a draft marks the exchange live",
          (started.update.get("draft_status") or {}).get("stage") == "drafting",
          str(started.update.get("draft_status")))
    check("and stamps it with a time, so an abandoned one can expire",
          isinstance((started.update.get("draft_status") or {}).get("at"), (int, float)),
          str(started.update.get("draft_status")))

    rejected = agt._finish_submission({"approved": False}, "single_point", {}, "c-reject")
    check("a rejection ends the drafting episode",
          rejected.update.get("draft_status") == CLEAR_DRAFT_STATUS,
          str(rejected.update.get("draft_status")))
    check("but keeps the draft itself, so the user can amend and resubmit",
          "job_draft" not in rejected.update, str(rejected.update.keys()))

    approved_spec = JobSpec(
        task="single_point", subtype="gs", method="hf", engine="pyscf",
        molecule=WATER, params={"basis": "sto-3g"})
    submitted = agt._finish_submission(
        {"approved": True, "spec": approved_spec.to_dict()}, "single_point", {}, "c-approve")
    created_jobs.extend(submitted.update.get("active_job_ids") or [])
    check("a submission ends it too",
          submitted.update.get("draft_status") == CLEAR_DRAFT_STATUS,
          str(submitted.update.get("draft_status")))
    check("and the job really was submitted", bool(submitted.update.get("active_job_ids")),
          str(submitted.update.keys()))

    nothing = agt.submit_draft.func(state={}, tool_call_id="c-empty")
    check("submitting with nothing assembled does NOT clear it -- that call "
          "lands one step before start_job_draft, and clearing there would "
          "open a window for a summary to slip between the two",
          "draft_status" not in nothing.update, str(nothing.update.keys()))

    print("\n== cleanup ==")
    for tid in (thread_id, victim["thread_id"], lock_thread["thread_id"],
                fail_thread["thread_id"], stale["thread_id"]):
        thread_registry.delete_thread(tid)
    # Every job this script created is removed, so a suite run leaves the
    # job list exactly as it found it.
    left = []
    for job_id in created_jobs:
        try:
            delete_job_dir(job_id)
        except Exception as e:  # noqa: BLE001
            left.append(f"{job_id} ({e})")
    check("every job this script created was deleted", not left, str(left))

    print(f"\n{checks - len(failures)}/{checks} checks passed")
    if failures:
        print(f"[FAIL] {len(failures)} check(s) failed")
        return 1
    print("[PASS] ALL CHECKS PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
