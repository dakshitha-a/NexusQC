"""A job-finished notice shows the user a plain line, not the model's instruction.

Found on 2026-11-10 while retaking the thesis screenshots: the chat showed
"Job(s) b23486553278 finished. Check their status and give the user a
concise summary of the results." That sentence is addressed to the model.
The model still receives it; the notice payload now also carries a line for
the user, which the chat row shows instead.

In-process, no stack and no model needed:

    PYTHONPATH=$PWD python3 tests/backend/notice_02_finished_line.py
"""
from __future__ import annotations

import sys

from app.agent.job_watcher import _agent_notice, _finished_line, _system_notice_message
from app.agent.serialize import serialize_message

PASS = FAIL = 0


def check(label: str, ok: bool, detail: str = "") -> None:
    global PASS, FAIL
    PASS += ok
    FAIL += not ok
    print(f"  [{'PASS' if ok else 'FAIL'}] {label}" + ("" if ok or not detail else f"\n         {detail}"))


def main() -> int:
    print("== the user's line ==")
    check("one job", _finished_line(["abc123"]) == "Job abc123 finished.", _finished_line(["abc123"]))
    check("several jobs, each once", _finished_line(["a", "b", "a"]) == "Jobs a, b finished.",
          _finished_line(["a", "b", "a"]))
    check("none gives no line", _finished_line([]) == "")

    print("\n== the message: model text unchanged, user line beside it ==")
    text = _agent_notice(["abc123"])
    m = _system_notice_message(text, _finished_line(["abc123"]))
    check("the model still gets its instruction", "Check their status" in m.content, m.content[:120])
    out = serialize_message(m)
    notice = out.get("notice") or {}
    check("the payload is still a system notice", notice.get("kind") == "system_notice", str(notice))
    check("and carries the user's line", notice.get("display") == "Job abc123 finished.", str(notice))
    bare = serialize_message(_system_notice_message(text)).get("notice") or {}
    check("a notice with no line carries no display key", "display" not in bare, str(bare))

    print(f"\n{PASS}/{PASS + FAIL} checks passed")
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
