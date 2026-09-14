#!/usr/bin/env python3
"""Replace this host's absolute paths in the evaluation's evidence logs.

    python3 docs/evaluation/2026-09-app-review/evidence/redact_paths.py [--check]

WHY THIS EXISTS
---------------
The logs under `evidence/` are the primary record of the review and the fix
phase: every number quoted in a README, in `perf.md` and in `resolution.md` was
read off one of them, and a citation to a file nobody can open is not a
citation. So they belong in the repository.

But `CLAUDE.md` states the invariant that keeps this project cheap to publish:
everything tracked is publishable, and a value true of one machine rather than
of the project never goes in a tracked file.
`scripts/check_public_safe.sh` enforces it by scanning for exactly the paths a
test runner prints all over its output, the checkout's own location and the
lab's licensed-software tree.

Both of those are right, and they only conflict because the logs were never
tracked at all until 2026-09-13, when adding them to the repository made the
question live. This script resolves it in the direction that keeps the
evidence: the paths are replaced by placeholders that say what was removed, and
nothing else in the file is touched. A reader loses the fact that this
particular deployment lived at one directory rather than another, which is not
part of any measurement, and keeps every line that is.

The substitutions are ordered longest-first so that the checkout's own path is
replaced as a whole rather than being half-consumed by the shorter prefix it
starts with.

`--check` reports what would change and rewrites nothing, which is what to run
before a release.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

EVIDENCE = Path(__file__).resolve().parent

# Longest first. `<repo>` is what a reader should mentally expand to their own
# checkout; the other two are named for what they were.
SUBSTITUTIONS: list[tuple[str, str]] = [
    ("/data/qcuser/9.NexusQC/NexusQC-dev-repo", "<repo>"),
    ("/data/qcuser/9.NexusQC", "<checkouts>"),
    ("/home/qcuser", "<home>"),
    ("/data/qcuser", "<data>"),
    ("/software", "<licensed-software>"),
]

HEADER = ("# Host paths in this log were replaced with placeholders by "
          "evidence/redact_paths.py.\n")


def redact(text: str) -> tuple[str, int]:
    n = 0
    for needle, placeholder in SUBSTITUTIONS:
        count = text.count(needle)
        if count:
            text = text.replace(needle, placeholder)
            n += count
    return text, n


def main() -> int:
    check_only = "--check" in sys.argv
    touched = 0
    total = 0
    for path in sorted(EVIDENCE.rglob("*.log")):
        try:
            original = path.read_text(errors="replace")
        except OSError as exc:
            print(f"  could not read {path.relative_to(EVIDENCE)}: {exc}")
            continue
        redacted, n = redact(original)
        if not n:
            continue
        touched += 1
        total += n
        rel = path.relative_to(EVIDENCE)
        if check_only:
            print(f"  {rel}: {n} host path(s)")
            continue
        if not redacted.startswith(HEADER):
            redacted = HEADER + redacted
        path.write_text(redacted)
        print(f"  {rel}: replaced {n} host path(s)")

    verb = "would be redacted in" if check_only else "redacted in"
    print(f"{total} host path(s) {verb} {touched} log(s) under "
          f"{EVIDENCE.relative_to(EVIDENCE.parents[3])}")
    return 1 if (check_only and touched) else 0


if __name__ == "__main__":
    raise SystemExit(main())
