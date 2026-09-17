#!/usr/bin/env python3
"""A task given while a plan is running becomes an amendment to the plan.

Claude Code runs this from three hooks registered in `.claude/settings.json`,
and the model runs it once by hand.

`started`, from `PostToolUse` on `ExitPlanMode`, writes a marker saying this
session is executing the plan the user just approved. `prompt`, from
`UserPromptSubmit`, reads that marker on every message the user sends and,
while it exists, tells the model that the message is an amendment: re-enter
plan mode, merge it into the plan file and into `docs/TRACKER.md`, validate,
get it approved, resume. `session`, from `SessionStart`, names any plan an
earlier session left unfinished. `done` is what the model runs when the
tracker is closed out, and removes the marker.

The reason for a hook rather than a rule is that the rule already existed
and the tasks were still being dropped. A rule lives in the model's context,
which is at its longest and most crowded exactly when a plan has been
running for a while; a hook fires from the harness on every message,
however long the context has become.

This repository's ledger is `docs/TRACKER.md`, not the plan file. The plan
file is where an amendment goes for approval; the tracker is where it goes
to be checked against the git log by `scripts/check_tracker.py`, so the
text below names both, and the marker's lifetime is the tracker's.

Markers are keyed by session id so two sessions working the same checkout
never read each other's plan. They live under `.claude/plan-in-progress/`,
which is gitignored. Every unexpected failure below is silent and exits 0:
a broken hook must not wedge the session, it should just stop reminding.
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path


def root() -> Path:
    return Path(os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd())


def markers() -> Path:
    return root() / ".claude" / "plan-in-progress"


def marker_for(session: str) -> Path:
    return markers() / f"{session}.json"


def hook_input() -> dict:
    try:
        return json.load(sys.stdin)
    except (json.JSONDecodeError, OSError):
        return {}


def read(path: Path) -> dict | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def age(seconds: float) -> str:
    minutes = int(seconds // 60)
    if minutes < 60:
        return f"{minutes} min"
    hours = minutes // 60
    if hours < 48:
        return f"{hours} h"
    return f"{hours // 24} days"


def respond(event: str, text: str) -> None:
    print(json.dumps({
        "hookSpecificOutput": {"hookEventName": event, "additionalContext": text},
    }))


def relative(path: str) -> str:
    try:
        return str(Path(path).relative_to(root()))
    except ValueError:
        return path


HOW_TO_FINISH = (
    "When every item in the plan is done and verified, docs/TRACKER.md is "
    "closed out (every step done with evidence, scripts/check_tracker.py "
    "passes) and moved into docs/trackers/, run "
    "`python3 scripts/hooks/claude_plan_amendment.py done {session}` so this "
    "reminder stops."
)


def started(data: dict) -> None:
    """An approved plan. The hook only fires when `ExitPlanMode` succeeded,
    which is to say when the user approved rather than rejected."""
    session = data.get("session_id") or ""
    response = data.get("tool_response") or {}
    plan = response.get("filePath") if isinstance(response, dict) else None
    if not session or not plan:
        return
    path = marker_for(session)
    existing = read(path) or {}
    now = time.time()
    record = {
        "session_id": session,
        "plan": plan,
        "cwd": data.get("cwd") or os.getcwd(),
        "started": existing.get("started", now),
        "approved": now,
        "amendments": existing.get("amendments", -1) + 1,
    }
    markers().mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    if record["amendments"]:
        text = (
            f"The amended plan at {relative(plan)} is approved. Make sure the "
            "amendment is a step in docs/TRACKER.md, then resume from the item "
            "you were on when it arrived."
        )
    else:
        text = (
            f"The plan at {relative(plan)} is approved and this session is now "
            "executing it. docs/TRACKER.md is the ledger: every item in the "
            "plan is a step there, and a step's state changes in the same "
            "commit as its work. Any message the user sends before the plan is "
            "finished is treated as an amendment (see the reminder that "
            "arrives with each one). "
        ) + HOW_TO_FINISH.format(session=session)
    respond("PostToolUse", text)


def prompt(data: dict) -> None:
    """Every message the user sends while a plan is running."""
    session = data.get("session_id") or ""
    record = read(marker_for(session)) if session else None
    if not record:
        return
    plan = relative(record.get("plan", ""))
    since = age(time.time() - float(record.get("approved", time.time())))
    if data.get("permission_mode") == "plan":
        respond("UserPromptSubmit", (
            f"You are in plan mode amending the running plan at {plan}. "
            "Merge this message into that plan file rather than starting a "
            "new plan, then ExitPlanMode for approval and resume where you "
            "left off."
        ))
        return
    respond("UserPromptSubmit", (
        f"A plan is being executed in this session: {plan}, approved {since} "
        "ago. If this message asks for work, it is an amendment to that "
        "plan, not a side task: finish the tool call in flight, call "
        "EnterPlanMode, add the request to the plan file as its own item "
        "with an acceptance criterion and a note that the user raised it "
        "mid-run, add it to docs/TRACKER.md as its own step named as raised "
        "mid-run, re-validate the plan's order and dependencies against what "
        "is already done, ExitPlanMode for approval, then resume the item you "
        "were on. If it only asks a question, answer it inline and carry on; "
        "if the answer exposes a defect, that defect is an amendment. "
    ) + HOW_TO_FINISH.format(session=session))


def session(data: dict) -> None:
    """A new session. Name what earlier ones left running, so an interrupted
    plan is picked up rather than rediscovered."""
    mine = data.get("session_id") or ""
    left = []
    if markers().is_dir():
        for path in sorted(markers().glob("*.json")):
            record = read(path)
            if not record or record.get("session_id") == mine:
                continue
            since = age(time.time() - float(record.get("approved", 0)))
            left.append(f"{relative(record.get('plan', '?'))} (session "
                        f"{record.get('session_id', '?')[:8]}, {since} ago)")
    if not left:
        return
    respond("SessionStart", (
        "An earlier session in this checkout left a plan in progress: "
        + "; ".join(left)
        + ". Before starting new work, read it and docs/TRACKER.md, compare "
        "their items against the git log, and tell the user what is "
        "unfinished. If it is in fact complete, close the tracker out and "
        "remove the marker with "
        "`python3 scripts/hooks/claude_plan_amendment.py done <session id>`."
    ))


def done(session: str) -> int:
    """The plan is finished. With no session named, one marker is
    unambiguous and is the one removed."""
    if not session:
        found = sorted(markers().glob("*.json")) if markers().is_dir() else []
        if len(found) != 1:
            print("name the session: " + ", ".join(p.stem for p in found)
                  if found else "no plan is in progress", file=sys.stderr)
            return 1
        path = found[0]
    else:
        path = marker_for(session)
    try:
        path.unlink()
    except FileNotFoundError:
        print(f"no plan in progress for {session}", file=sys.stderr)
        return 1
    print(f"plan finished: {path.stem}")
    return 0


def main(argv: list[str]) -> int:
    action = argv[1] if len(argv) > 1 else ""
    if action == "done":
        return done(argv[2] if len(argv) > 2 else "")
    handlers = {"started": started, "prompt": prompt, "session": session}
    handler = handlers.get(action)
    if handler is None:
        print(f"usage: {argv[0]} started|prompt|session|done [session]",
              file=sys.stderr)
        return 2
    try:
        handler(hook_input())
    except Exception as exc:  # noqa: BLE001 -- a broken hook must not wedge the session
        print(f"claude_plan_amendment: {exc}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
