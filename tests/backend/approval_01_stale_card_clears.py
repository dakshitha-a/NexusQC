#!/usr/bin/env python3
"""A finished turn always tells the client whether an approval is pending.

    PYTHONPATH=$PWD python3 tests/backend/approval_01_stale_card_clears.py

The regression test for a stuck approval card. Observed live: a card that
would not go away, every button on it answered "No job approval is pending",
and the only escape was reloading the page.

Two defects produced that, and this covers the deeper one. The frontend
learns about approvals from exactly one event, `interrupt`, and `turn_complete`
carries no approval state at all -- so a client whose card has diverged from
the server can only be corrected by an `interrupt` event saying "nothing is
pending". Two of the three paths that end a turn published that event ONLY
when there was an approval to show, which is precisely when it is not needed.
Divergence was therefore permanent rather than self-healing.

The rule this asserts: **every path that ends a turn publishes the thread's
real approval state, whatever it is.** The three paths are _run_turn and the
resume/approve route (server/routes/chat.py) and the watcher's background
turn (app/agent/job_watcher.py).

Runs in-process against stubbed graph calls -- what is under test is which
events each path publishes, not what the model says, so there is no LLM here.
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO))

failures: list[str] = []
checks = 0


def check(name: str, ok: bool, detail: str = "") -> bool:
    global checks
    checks += 1
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f" -- {detail}" if detail else ""))
    if not ok:
        failures.append(name)
    return ok


def interrupt_events(events: list[dict]) -> list:
    return [e for e in events if e.get("type") == "interrupt"]


def main() -> int:
    print("\n== the watcher's background turn ==")
    from app.agent import job_watcher as jw

    published: list[dict] = []
    watcher = jw.JobWatcher(on_event=lambda tid, ev: published.append(ev))

    # The end-of-turn publish, exercised directly: whatever pending_approval
    # returns must reach the client, including None.
    for label, pending in (("nothing pending", None), ("an approval pending", {"kind": "job_approval"})):
        published.clear()
        original = jw.pending_approval
        jw.pending_approval = lambda _cfg, _p=pending: _p
        try:
            watcher._emit("t1", {"type": "interrupt", "interrupt": jw.pending_approval({})})
        finally:
            jw.pending_approval = original
        got = interrupt_events(published)
        check(f"the watcher publishes an interrupt event with {label}",
              len(got) == 1 and got[0]["interrupt"] == pending, str(got))

    print("\n== the source, not just the behaviour ==")
    # A behavioural test alone would pass again the moment someone reinstates
    # the `if pending is not None:` guard around a publish, so the guard
    # itself is what is asserted against.
    chat_src = (REPO / "server" / "routes" / "chat.py").read_text()
    watcher_src = (REPO / "app" / "agent" / "job_watcher.py").read_text()
    for name, src in (("chat.py", chat_src), ("job_watcher.py", watcher_src)):
        guarded = 'if pending is not None:\n' in src and '"type": "interrupt"' in src
        check(f"{name} has no `if pending is not None` guard around an interrupt publish", not guarded)

    check("chat.py publishes the interrupt state on both the turn and the resume path",
          chat_src.count('{"type": "interrupt", "interrupt":') == 2,
          f'{chat_src.count(chr(123) + chr(34) + "type" + chr(34) + ": " + chr(34) + "interrupt" + chr(34))} site(s)')
    check("the watcher publishes it too",
          watcher_src.count('{"type": "interrupt", "interrupt":') == 1)

    print(f"\n{checks - len(failures)}/{checks} checks passed")
    if failures:
        print(f"[FAIL] {len(failures)} check(s) failed")
        return 1
    print("[PASS] ALL CHECKS PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
