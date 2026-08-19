"""Harness for driving the LangGraph agent through the real HTTP API and
asserting on WHICH TOOLS IT ACTUALLY CALLED, with which arguments.

This is the piece the existing tests/backend/ suite deliberately does not
have. Those scripts call mechanisms directly (JobManager.submit(), etc.)
because they are testing the mechanism. Here the whole point is the
opposite: a real natural-language turn goes in, and we check that the
agent reached for the right tool with the right parameters. A job that
completes is NOT evidence of that -- param_normalize.py silently repairs
some typos, and the keyword-suggestion menus can make a wrong call look
right in the finished result.

Two observation channels, and the choice between them matters:

PRIMARY -- GET /api/threads/{id}/state.
    app/agent/serialize.py::serialize_message preserves `tool_calls` on
    every AIMessage (name AND args) and `name` on every ToolMessage. So
    diffing the message list across a turn gives a complete, replayable
    audit of the turn's tool usage. Every assertion in this suite runs
    against this.

SECONDARY -- SSE `agent_step` events, and only for the pre-interrupt
    segment of a turn.
    server/routes/chat.py publishes agent_step exclusively from
    _run_turn's streaming "updates" loop. approve_job() USED TO resume via
    a blocking resume_turn().invoke() and then call
    _publish_new_messages(), which emits ONLY `message` events -- making
    every tool call in the post-resume tail of a turn (including the
    re-executed submit_draft itself) invisible to agent_step. That was
    expected-negative XN-14, now fixed (F-008): approve_job streams
    through _stream_resume and publishes agent_step like any other turn.

    State-diffing REMAINS the primary channel anyway, for a reason that
    outlives that fix: it reads what the graph actually committed, so it
    cannot miss a call because an SSE event was dropped (SSEHub.publish is
    fire-and-forget, see below) or because a subscriber attached late.

Two SSE facts drive the connection handling, both read out of
server/sse.py rather than assumed:
  * SSEHub.publish is fire-and-forget and DROPS an event when nobody is
    subscribed to that thread_id. POST /messages returns 202 and spawns
    its turn thread immediately, so the stream must be open and past its
    `: connected` preamble BEFORE the message is posted, or the opening
    events are simply lost.
  * Each subscriber queue is bounded at 500 with a drop-oldest policy, so
    a slow reader loses old events rather than blocking the publisher.

Approvals are detected by POLLING GET /state for a non-null
pending_approval, never by racing the `interrupt` SSE event:
POST /approvals/job returns 409 when nothing is pending, so the event is
an optimization, not a contract.
"""
from __future__ import annotations

import json
import queue
import sys
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterable, Optional

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from fixtures import BASE_URL  # noqa: E402

RESULTS_DIR = Path(__file__).resolve().parent / "results"


# --------------------------------------------------------------------------
# Turn result
# --------------------------------------------------------------------------


@dataclass
class Turn:
    """Everything one turn produced, as observed through both channels."""

    new_messages: list[dict] = field(default_factory=list)
    sse_events: list[dict] = field(default_factory=list)
    pending_approval: Optional[dict] = None
    elapsed: float = 0.0
    ttft: Optional[float] = None  # POST -> first `token` event
    timed_out: bool = False

    # ---- primary channel ------------------------------------------------

    def tools_requested(self) -> list[tuple[str, dict]]:
        """(tool_name, args) for every tool call the agent ASKED for."""
        out = []
        for m in self.new_messages:
            for tc in m.get("tool_calls") or []:
                out.append((tc.get("name"), tc.get("args") or {}))
        return out

    def tools_executed(self) -> list[tuple[str, str]]:
        """(tool_name, content) for every ToolMessage that came back."""
        return [
            (m.get("name"), m.get("content") or "")
            for m in self.new_messages
            if m.get("type") == "ToolMessage"
        ]

    def tool_names(self) -> list[str]:
        return [n for n, _ in self.tools_requested()]

    def args_for(self, tool_name: str) -> list[dict]:
        return [a for n, a in self.tools_requested() if n == tool_name]

    def assistant_text(self) -> str:
        return "\n".join(
            m.get("content") or ""
            for m in self.new_messages
            if m.get("type") == "AIMessage"
        )

    # ---- secondary channel ----------------------------------------------

    def agent_steps(self) -> list[tuple[str, str]]:
        return [
            (e.get("tool_name"), e.get("phase"))
            for e in self.sse_events
            if e.get("type") == "agent_step"
        ]

    def sse_types(self) -> list[str]:
        return [e.get("type") for e in self.sse_events]


# --------------------------------------------------------------------------
# Session
# --------------------------------------------------------------------------


class AgentSession:
    """One conversation thread, driven as one authenticated user, with a
    live SSE reader attached for the whole life of the session."""

    def __init__(self, client: httpx.Client, thread_id: str):
        self.client = client
        self.thread_id = thread_id
        self._events: queue.Queue = queue.Queue()
        self._stop = threading.Event()
        self._reader: Optional[threading.Thread] = None
        self._connected = threading.Event()
        self.last_approved_spec: Optional[dict] = None

    # ---- construction ----------------------------------------------------

    @classmethod
    def new(cls, client: httpx.Client, label: Optional[str] = None) -> "AgentSession":
        r = client.post("/api/threads", json={"label": label} if label else {})
        r.raise_for_status()
        thread_id = r.json()["thread_id"]
        s = cls(client, thread_id)
        s.open_events()
        return s

    # ---- SSE -------------------------------------------------------------

    def open_events(self, timeout: float = 20.0) -> None:
        """Opens the SSE stream on its own thread and BLOCKS until the
        `: connected` preamble has actually arrived. Returning before that
        would race SSEHub.publish's drop-if-no-subscriber behavior."""
        if self._reader is not None:
            return

        def _run():
            # A separate client: httpx.Client is not safe to use for a
            # long-lived stream on one thread while another thread issues
            # ordinary requests on it. Cookies are copied so the stream
            # authenticates as the same user.
            c = httpx.Client(
                base_url=BASE_URL, verify=False, timeout=None,
                headers={"Origin": BASE_URL},
                cookies=self.client.cookies,
            )
            try:
                with c.stream("GET", f"/api/threads/{self.thread_id}/events") as resp:
                    for line in resp.iter_lines():
                        if self._stop.is_set():
                            return
                        if line.startswith(": connected"):
                            self._connected.set()
                            continue
                        if line.startswith("data:"):
                            try:
                                self._events.put(json.loads(line[5:].strip()))
                            except json.JSONDecodeError:
                                pass
            except Exception:
                pass
            finally:
                c.close()

        self._reader = threading.Thread(target=_run, daemon=True)
        self._reader.start()
        if not self._connected.wait(timeout):
            raise RuntimeError(
                f"SSE stream for thread {self.thread_id} never sent its "
                f"`: connected` preamble within {timeout}s -- refusing to "
                f"proceed, since every event published before now is dropped."
            )

    def close(self) -> None:
        self._stop.set()

    def _drain_events(self) -> list[dict]:
        out = []
        while True:
            try:
                out.append(self._events.get_nowait())
            except queue.Empty:
                return out

    # ---- state -----------------------------------------------------------

    def state(self) -> dict:
        r = self.client.get(f"/api/threads/{self.thread_id}/state")
        r.raise_for_status()
        return r.json()

    def _message_ids(self, state: Optional[dict] = None) -> set:
        st = state if state is not None else self.state()
        return {m.get("id") for m in st.get("messages", [])}

    # ---- speaking --------------------------------------------------------

    def say(
        self,
        text: str,
        job_ids: Optional[list[str]] = None,
        frame_id: Optional[str] = None,
        timeout: float = 420.0,
    ) -> Turn:
        """Posts a message and waits for the turn to finish.

        A turn ends at `turn_complete`. An interrupting turn (submit_draft)
        publishes `interrupt` and then `turn_complete`, so waiting on
        turn_complete alone is correct for both cases -- but we also
        cross-check pending_approval from /state afterward, since that is
        the authoritative source (it survives a reload, unlike the event)."""
        before = self._message_ids()
        self._drain_events()  # discard anything left over from a prior turn
        collected: list[dict] = []
        t0 = time.perf_counter()
        ttft: Optional[float] = None

        r = self.client.post(
            f"/api/threads/{self.thread_id}/messages",
            json={"text": text, "job_ids": job_ids or [], "frame_id": frame_id},
        )
        r.raise_for_status()

        done = False
        deadline = t0 + timeout
        while time.perf_counter() < deadline:
            try:
                ev = self._events.get(timeout=1.0)
            except queue.Empty:
                continue
            collected.append(ev)
            if ev.get("type") == "token" and ttft is None:
                ttft = time.perf_counter() - t0
            if ev.get("type") == "turn_complete":
                done = True
                break

        elapsed = time.perf_counter() - t0
        st = self.state()
        new = [m for m in st.get("messages", []) if m.get("id") not in before]
        return Turn(
            new_messages=new,
            sse_events=collected,
            pending_approval=st.get("pending_approval"),
            elapsed=elapsed,
            ttft=ttft,
            timed_out=not done,
        )

    def stop(self) -> None:
        self.client.post(f"/api/threads/{self.thread_id}/stop")

    # ---- approvals -------------------------------------------------------

    def wait_for_approval(self, timeout: float = 240.0) -> Optional[dict]:
        """Polls /state. See the module docstring for why this is polled
        rather than driven off the `interrupt` event."""
        deadline = time.perf_counter() + timeout
        while time.perf_counter() < deadline:
            pending = self.state().get("pending_approval")
            if pending is not None:
                return pending
            time.sleep(1.0)
        return None

    def approve(self, input_text: Optional[str] = None, timeout: float = 420.0) -> Turn:
        return self._resume(True, input_text, timeout)

    def reject(self, timeout: float = 420.0) -> Turn:
        return self._resume(False, None, timeout)

    def _resume(self, approved: bool, input_text: Optional[str], timeout: float) -> Turn:
        """POST /approvals/job. NOTE the body carries no `spec` -- the
        server reads pending_approval(config)["spec"] itself (see
        server/routes/chat.py::approve_job and JobApprovalIn). A client
        genuinely cannot substitute a different spec; that property is
        asserted directly in e2e_03."""
        st = self.state()
        pending = st.get("pending_approval")
        if pending is not None:
            self.last_approved_spec = pending.get("spec")
        before = self._message_ids(st)
        before_jobs = set(st.get("active_job_ids", []))
        self._drain_events()
        t0 = time.perf_counter()

        body: dict[str, Any] = {"approved": approved}
        if input_text is not None:
            body["input_text"] = input_text
        r = self.client.post(
            f"/api/threads/{self.thread_id}/approvals/job", json=body, timeout=timeout,
        )
        r.raise_for_status()

        elapsed = time.perf_counter() - t0
        collected = self._drain_events()
        st2 = self.state()
        new = [m for m in st2.get("messages", []) if m.get("id") not in before]
        self.new_job_ids = [
            j for j in st2.get("active_job_ids", []) if j not in before_jobs
        ]
        return Turn(
            new_messages=new,
            sse_events=collected,
            pending_approval=st2.get("pending_approval"),
            elapsed=elapsed,
        )

    # ---- jobs ------------------------------------------------------------

    def await_job(self, job_id: str, timeout: float = 1800.0, poll: float = 3.0) -> dict:
        """Polls GET /api/jobs/{id} until terminal. Returns the full job
        record so callers can assert on summary/artifacts, not just status."""
        terminal = {"completed", "failed", "cancelled"}
        deadline = time.perf_counter() + timeout
        last: dict = {}
        while time.perf_counter() < deadline:
            r = self.client.get(f"/api/jobs/{job_id}")
            if r.status_code == 200:
                last = r.json()
                if last.get("status") in terminal:
                    return last
            time.sleep(poll)
        last["_timed_out"] = True
        return last


# --------------------------------------------------------------------------
# Assertions
# --------------------------------------------------------------------------


def _subset_match(expected: Any, actual: Any) -> bool:
    """Recursive subset match. The agent is free to add parameters it
    legitimately elicited, so we only require that what we specified is
    present and equal. Strings compare case-insensitively -- 'STO-3G' and
    'sto-3g' are the same basis, and which one the model emits is not a
    property worth failing on."""
    if isinstance(expected, dict):
        if not isinstance(actual, dict):
            return False
        return all(k in actual and _subset_match(v, actual[k]) for k, v in expected.items())
    if isinstance(expected, str) and isinstance(actual, str):
        return expected.strip().lower() == actual.strip().lower()
    if isinstance(expected, (list, tuple)):
        if not isinstance(actual, (list, tuple)) or len(expected) != len(actual):
            return False
        return all(_subset_match(e, a) for e, a in zip(expected, actual))
    return expected == actual


def check_tools(
    turn: Turn,
    name: str,
    must_call: Iterable[str] = (),
    must_not_call: Iterable[str] = (),
    args_match: Optional[dict] = None,
) -> tuple[bool, str]:
    """Returns (ok, detail). Does not print -- the caller decides whether
    this is a hard failure or one attempt among several it will retry
    itself (a flaky-local-model allowance in the harness; unrelated to the
    job auto-retry mechanism, which was removed in Phase 1)."""
    called = turn.tool_names()
    problems = []

    for want in must_call:
        if want not in called:
            problems.append(f"missing tool call {want!r} (called: {called})")
    for forbidden in must_not_call:
        if forbidden in called:
            problems.append(f"unexpected tool call {forbidden!r}")

    for tool, expected_args in (args_match or {}).items():
        candidates = turn.args_for(tool)
        if not candidates:
            problems.append(f"no {tool!r} call to match args against")
            continue
        if not any(_subset_match(expected_args, a) for a in candidates):
            problems.append(
                f"{tool!r} args mismatch: wanted subset {expected_args!r}, got {candidates!r}"
            )

    if turn.timed_out:
        problems.append("turn timed out before turn_complete")

    return (not problems), "; ".join(problems)


def run_with_retries(
    scenario: Callable[[], Turn],
    name: str,
    must_call: Iterable[str] = (),
    must_not_call: Iterable[str] = (),
    args_match: Optional[dict] = None,
    attempts: int = 3,
) -> tuple[str, str, Turn]:
    """LLM non-determinism policy. A scenario that fails its tool
    assertion is re-run on a FRESH thread (the caller's `scenario` closure
    is responsible for that) up to `attempts` times.

    Returns (verdict, detail, last_turn) where verdict is one of
    PASS / FLAKY / FAIL. A FLAKY result is a prompt-reliability finding,
    not a code defect, and is reported with its observed k/N rate."""
    ok_count = 0
    last_turn: Optional[Turn] = None
    details: list[str] = []
    for i in range(attempts):
        turn = scenario()
        last_turn = turn
        ok, detail = check_tools(turn, name, must_call, must_not_call, args_match)
        if ok:
            ok_count += 1
            if i == 0:
                return "PASS", f"1/1", turn
        else:
            details.append(f"attempt {i + 1}: {detail}")
    if ok_count == 0:
        return "FAIL", f"0/{attempts}; " + " | ".join(details), last_turn
    return "FLAKY", f"{ok_count}/{attempts}; " + " | ".join(details), last_turn


# --------------------------------------------------------------------------
# Durable results -- the report is assembled from this, never from scrollback
# --------------------------------------------------------------------------

_RUN_ID = time.strftime("%Y%m%dT%H%M%S")


def record(scenario_id: str, verdict: str, **extra) -> None:
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    row = {"ts": time.time(), "scenario": scenario_id, "verdict": verdict}
    row.update(extra)
    path = RESULTS_DIR / f"run-{_RUN_ID}.jsonl"
    with path.open("a") as f:
        f.write(json.dumps(row, default=str) + "\n")


def record_turn(scenario_id: str, verdict: str, turn: Optional[Turn], detail: str = "", **extra) -> None:
    payload = dict(extra)
    payload["detail"] = detail
    if turn is not None:
        payload["tools_requested"] = turn.tools_requested()
        payload["tools_executed"] = [n for n, _ in turn.tools_executed()]
        payload["sse_types"] = turn.sse_types()
        payload["elapsed"] = round(turn.elapsed, 2)
        payload["ttft"] = round(turn.ttft, 2) if turn.ttft else None
    record(scenario_id, verdict, **payload)
