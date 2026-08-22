#!/usr/bin/env python3
"""Reading a conversation does not wait for its turn to finish.

    PYTHONPATH=$PWD python3 tests/backend/perf_06_lockfree_reads.py

app/agent/graph.py holds a per-thread lock for the whole of a ReAct turn --
53-77 seconds for an ordinary one, longer for a troubleshooting turn. That is
correct for writes: a get_state/update_state pair must not interleave with
another write to the same conversation.

It was badly wrong for reads. read_state and pending_approval only call
get_state, and both took that same lock, so:

- opening a conversation whose turn was running blocked until the turn ended
  (~19.5s recorded in docs/ARCHITECTURE.md; 5.7s measured here against a 6s
  synthetic hold), and the frontend polls /state, so the whole UI dragged
  whenever a background job-summary turn was in flight;
- worse, job_watcher calls pending_approval once per thread per poll tick, so
  ONE conversation's long turn stalled the entire watcher and delayed
  job-finished notices on every other conversation.

This asserts the fix in both directions, because half of it is easy to lose:
reads must not block behind a turn, and writes must still serialize.
"""
from __future__ import annotations

import sys
import threading
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO))

from app.agent import graph  # noqa: E402

failures: list[str] = []
checks = 0

# Generous enough that a slow or loaded host cannot make this flaky, small
# enough that it cannot pass by accident: the failure mode being caught is a
# read waiting out a whole turn, which is seconds, not milliseconds.
HOLD_SECONDS = 6.0
READ_BUDGET_SECONDS = 1.0


def check(name: str, ok: bool, detail: str = "") -> bool:
    global checks
    checks += 1
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f" -- {detail}" if detail else ""))
    if not ok:
        failures.append(name)
    return ok


def main() -> int:
    cfg = {"configurable": {"thread_id": "perf06-lockfree"}}
    lock = graph._lock_for_thread(cfg)

    def hold(seconds: float) -> None:
        with lock:
            time.sleep(seconds)

    print("\n== a read does not wait for a running turn ==")
    holder = threading.Thread(target=hold, args=(HOLD_SECONDS,), daemon=True)
    holder.start()
    time.sleep(0.3)  # let the "turn" take the lock

    timings: dict[str, float] = {}

    def probe(name, fn):
        t0 = time.perf_counter()
        fn(cfg)
        timings[name] = time.perf_counter() - t0

    threads = [
        threading.Thread(target=probe, args=("read_state", graph.read_state)),
        threading.Thread(target=probe, args=("pending_approval", graph.pending_approval)),
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    still_running = holder.is_alive()
    check("the turn was still holding the lock while the reads ran", still_running,
          "the hold ended too early for this to prove anything")
    for name, seconds in timings.items():
        check(f"{name} returns without waiting for the turn",
              seconds < READ_BUDGET_SECONDS, f"{seconds:.3f}s (budget {READ_BUDGET_SECONDS}s)")
    holder.join()

    print("\n== a write still serializes behind it ==")
    # The other half. A 'fix' that made everything lock-free would pass the
    # checks above and quietly destroy the read-then-write consistency the
    # lock exists for.
    holder = threading.Thread(target=hold, args=(3.0,), daemon=True)
    holder.start()
    time.sleep(0.3)
    t0 = time.perf_counter()
    with graph._lock_for_thread(cfg):
        pass
    waited = time.perf_counter() - t0
    check("acquiring the turn lock still waits for the turn", waited > 1.0, f"{waited:.2f}s")
    holder.join()

    print(f"\n{checks - len(failures)}/{checks} checks passed")
    if failures:
        print(f"[FAIL] {len(failures)} check(s) failed")
        return 1
    print("[PASS] ALL CHECKS PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
