#!/usr/bin/env python3
"""Verify docs/TRACKER.md is telling the truth.

Read-only. Run from the repo root (or anywhere inside the repo) at every
phase gate, and before any tracker-touching commit if in doubt:

    python3 scripts/check_tracker.py

Checks, matching the rules stated at the top of docs/TRACKER.md:

1. Every step row parses and carries a valid status (todo|in-progress|done).
2. Every `done` step has an evidence line, and the script/command path named
   in it exists on disk. Evidence lines name paths relative to the repo root
   (the first whitespace-separated token that looks like a path is checked;
   bare commands like `npm run test:e2e` are accepted as-is but flagged in
   the summary so a human eye lands on them).
3. A phase whose steps are all `done` and whose `merged:` row records a hash
   must have that hash reachable in git history.
4. A `merged:` hash on a phase with non-done steps is an error -- a phase is
   merged whole or not at all.

Exit code 0 = consistent, 1 = violations (each printed with its line number).
This is deliberately a standalone invoke-and-print script, per the repo's
testing conventions -- no pytest.
"""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
TRACKER = REPO / "docs" / "TRACKER.md"

STEP_RE = re.compile(r"^- \[(?P<status>[a-z-]+)\] (?P<id>P\d+[A-Z]?\.\d+): (?P<name>.+)$")
EVIDENCE_RE = re.compile(r"^\s+evidence: (?P<body>.+)$")
MERGED_RE = re.compile(r"^- merged: (?P<val>.+)$")
PHASE_RE = re.compile(r"^## (?P<title>Phase \d+[A-Z]?: .*)$")
VALID_STATUS = {"todo", "in-progress", "done"}
# Evidence bodies begin with the verifying script/command; paths are checked
# against the working tree. A token counts as a path if it contains a slash.
PATHLIKE_RE = re.compile(r"^[\w./-]+$")


def commit_exists(sha: str) -> bool:
    r = subprocess.run(
        ["git", "cat-file", "-e", f"{sha}^{{commit}}"],
        cwd=REPO, capture_output=True,
    )
    return r.returncode == 0


def main() -> int:
    if not TRACKER.exists():
        print(f"[FAIL] {TRACKER} does not exist")
        return 1

    errors: list[str] = []
    notes: list[str] = []
    lines = TRACKER.read_text().splitlines()

    phase = None
    phase_all_done: dict[str, bool] = {}
    phase_merged: dict[str, str | None] = {}
    pending_done: tuple[str, int] | None = None  # (step id, line no) awaiting evidence
    n_steps = 0

    for i, line in enumerate(lines, 1):
        m = PHASE_RE.match(line)
        if m:
            if pending_done:
                errors.append(f"line {pending_done[1]}: {pending_done[0]} is done but has no evidence line")
                pending_done = None
            phase = m.group("title")
            phase_all_done[phase] = True
            phase_merged[phase] = None
            continue

        m = STEP_RE.match(line)
        if m:
            if pending_done:
                errors.append(f"line {pending_done[1]}: {pending_done[0]} is done but has no evidence line")
                pending_done = None
            n_steps += 1
            status = m.group("status")
            if status not in VALID_STATUS:
                errors.append(f"line {i}: {m.group('id')} has invalid status '{status}'")
            if phase is None:
                errors.append(f"line {i}: step {m.group('id')} appears before any phase heading")
            elif status != "done":
                phase_all_done[phase] = False
            if status == "done":
                pending_done = (m.group("id"), i)
            continue

        m = EVIDENCE_RE.match(line)
        if m:
            if pending_done is None:
                # Evidence on a non-done step is fine (work in progress); skip.
                continue
            step_id, _ = pending_done
            pending_done = None
            first = m.group("body").split()[0].rstrip(",;")
            if "/" in first:
                if not (REPO / first).exists():
                    errors.append(f"line {i}: {step_id} evidence path '{first}' does not exist")
            elif PATHLIKE_RE.match(first):
                notes.append(f"line {i}: {step_id} evidence is a bare command ('{first}') -- eyeball it")
            continue

        m = MERGED_RE.match(line)
        if m and phase is not None:
            val = m.group("val").strip()
            phase_merged[phase] = None if val in {"-", ""} else val

    if pending_done:
        errors.append(f"line {pending_done[1]}: {pending_done[0]} is done but has no evidence line")

    for ph, sha in phase_merged.items():
        if sha is None:
            continue
        if not phase_all_done.get(ph, False):
            errors.append(f"{ph}: merged hash recorded but not all steps are done")
        if not re.fullmatch(r"[0-9a-f]{7,40}", sha):
            errors.append(f"{ph}: merged value '{sha}' is not a commit hash")
        elif not commit_exists(sha):
            errors.append(f"{ph}: merged commit {sha} not found in this repository")

    for n in notes:
        print(f"[NOTE] {n}")
    if errors:
        for e in errors:
            print(f"[FAIL] {e}")
        print(f"\n{len(errors)} violation(s) across {n_steps} steps.")
        return 1
    print(f"[PASS] tracker consistent: {n_steps} steps, {sum(1 for v in phase_merged.values() if v)} phase(s) merged.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
