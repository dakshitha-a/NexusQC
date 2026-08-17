#!/usr/bin/env python3
"""Claude Code PreToolUse guard: block `git push` when the repo isn't clean.

Wired up in `.claude/settings.json` as a PreToolUse hook on the Bash tool.
It reads the tool-call JSON on stdin, and if the command being run looks like
a `git push`, it runs `scripts/check_public_safe.sh` first and blocks the call
when that scan fails.

This duplicates the `.git/hooks/pre-push` guard on purpose. The git hook is
the one that actually cannot be bypassed by tooling, but it lives in
`.git/hooks`, which is not tracked and so is missing from every fresh clone
until someone runs the installer. This one is tracked and needs no install
step. Belt and braces, for something that cannot be undone once published.

Exit codes are the hook protocol, not this script's own convention:
    0 -- allow the tool call
    2 -- block it, and show stderr to the model
Anything else is treated as a non-blocking error, which is why every
unexpected failure below deliberately exits 0: a broken guard must not wedge
the session, it should just stop guarding and say so.
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

# `git push`, allowing for flags and extra whitespace between the two words,
# but not matching unrelated commands that merely contain the word "push".
_GIT_PUSH = re.compile(r"\bgit\s+(?:-[^\s]+\s+)*push\b")


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except Exception:
        return 0

    command = (payload.get("tool_input") or {}).get("command") or ""
    if not _GIT_PUSH.search(command):
        return 0

    # `--no-verify` already signals a deliberate, eyes-open bypass of the git
    # hook; second-guessing it here would just be noise.
    if "--no-verify" in command:
        return 0

    try:
        root = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            capture_output=True, text=True, timeout=10,
        )
        if root.returncode != 0:
            return 0
        check = Path(root.stdout.strip()) / "scripts" / "check_public_safe.sh"
        if not check.is_file():
            return 0
        bash = shutil.which("bash")
        if bash is None:
            return 0
        result = subprocess.run(
            [bash, str(check)], capture_output=True, text=True, timeout=120,
        )
    except Exception as exc:  # guard must never wedge the session
        print(f"push guard could not run ({exc}); not blocking.", file=sys.stderr)
        return 0

    if result.returncode == 0:
        return 0

    print(
        "Blocked `git push`: scripts/check_public_safe.sh found content that "
        "must not be published.\n\n"
        f"{result.stdout}\n{result.stderr}\n"
        "Fix the findings, or narrow the pattern in that script if it is a "
        "false positive.",
        file=sys.stderr,
    )
    return 2


if __name__ == "__main__":
    sys.exit(main())
