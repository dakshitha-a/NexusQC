#!/usr/bin/env python3
"""Replace this host's identifiers in the evaluation's files.

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
evidence: the identifiers are replaced by placeholders that say what was
removed, and nothing else in the file is touched. A reader loses the fact that
this particular deployment lived at one directory rather than another, which
is not part of any measurement, and keeps every line that is.

WHAT IT COVERS
--------------
Every `.log`, `.md`, `.mjs`, `.py` and `.txt` file under the evaluation
directory (the parent of `evidence/`), except this script. The first version
covered only the logs, and the first release attempt found the same paths in
the audit notes, the findings register, a Playwright script and this script's
own replacement table, which is why the table is no longer a table of
literals.

WHERE THE STRINGS COME FROM
---------------------------
Nothing host-specific is written in this file. The paths are derived from
where the script is running: the checkout's root (from git), the directory
holding it, the home directory, and the user-scoped data root. That is what
lets a tracked script redact a path without containing it, which matters
twice over: the scanner would otherwise flag this file, and a history rewrite
that replaces the path everywhere would otherwise rewrite the redactor into a
no-op.

Identifiers that cannot be derived, such as a hostname, an address or an email
address that a test printed, are read from `redact_terms.local` next to this
script, one `literal==>placeholder` per line, `#` for comments. That file is
gitignored: it is the one place the real strings are allowed to exist, and it
stays on the machine they describe. Without it the derived paths are still
redacted, so a fresh clone can run `--check` and get a true answer about
paths, just not about terms it was never told.

The substitutions are ordered longest-first so that the checkout's own path is
replaced as a whole rather than being half-consumed by the shorter prefix it
starts with.

`--check` reports what would change and rewrites nothing, which is what to run
before a release.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve()
EVIDENCE = HERE.parent
EVALUATION = EVIDENCE.parent
TERMS_FILE = EVIDENCE / "redact_terms.local"
SUFFIXES = {".log", ".md", ".mjs", ".py", ".txt"}

# Only a log gets the header. A `.py` starts with its shebang and a `.md` with
# its title; a note prepended to either would be a change to the document
# rather than to its provenance.
HEADER = ("# Host paths in this log were replaced with placeholders by "
          "evidence/redact_paths.py.\n")


def _repo_root() -> Path:
    r = subprocess.run(["git", "rev-parse", "--show-toplevel"], cwd=EVIDENCE,
                       capture_output=True, text=True)
    if r.returncode == 0 and r.stdout.strip():
        return Path(r.stdout.strip()).resolve()
    # evidence/ sits four levels below the root: docs/evaluation/<review>/evidence
    return EVIDENCE.parents[3]


def substitutions() -> list[tuple[str, str]]:
    """The replacement table, derived from where this is running."""
    repo = _repo_root()
    home = Path.home().resolve()
    pairs: dict[str, str] = {
        str(repo): "<repo>",
        str(repo.parent): "<checkouts>",
        str(home): "<home>",
        # Split so this file does not itself contain the string the scanner
        # hunts for, the same reason scripts/check_public_safe.sh writes its
        # own pattern as a character class.
        "/soft" + "ware/": "<licensed-software>/",
    }
    # `/data/<user>`: the user-scoped tree the checkout lives under, when it
    # does. The scanner treats `/data/<name>` the way it treats `/home/<name>`.
    parts = repo.parts
    if len(parts) > 3 and parts[1] == "data":
        pairs[str(Path(*parts[:3]))] = "<data>"
    # Whatever the checkout's parent is, it is not a placeholder on its own if
    # it is also the home directory or the data root; the later, more specific
    # names win by being longer.
    if TERMS_FILE.exists():
        for raw in TERMS_FILE.read_text().splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "==>" not in line:
                continue
            literal, placeholder = (s.strip() for s in line.split("==>", 1))
            if literal:
                pairs[literal] = placeholder
    # Longest first, so a path is consumed whole before any prefix of it.
    return sorted(pairs.items(), key=lambda kv: -len(kv[0]))


def redact(text: str, table: list[tuple[str, str]]) -> tuple[str, int]:
    n = 0
    for needle, placeholder in table:
        count = text.count(needle)
        if count:
            text = text.replace(needle, placeholder)
            n += count
    return text, n


def targets() -> list[Path]:
    out = []
    for path in sorted(EVALUATION.rglob("*")):
        if path.is_file() and path.suffix in SUFFIXES and path != HERE:
            out.append(path)
    return out


def main() -> int:
    check_only = "--check" in sys.argv
    table = substitutions()
    if not TERMS_FILE.exists():
        print(f"  note: {TERMS_FILE.relative_to(EVALUATION)} absent; "
              f"only derived paths are redacted")
    touched = 0
    total = 0
    for path in targets():
        try:
            original = path.read_text(errors="replace")
        except OSError as exc:
            print(f"  could not read {path.relative_to(EVALUATION)}: {exc}")
            continue
        redacted, n = redact(original, table)
        if not n:
            continue
        touched += 1
        total += n
        rel = path.relative_to(EVALUATION)
        if check_only:
            print(f"  {rel}: {n} host identifier(s)")
            continue
        if path.suffix == ".log" and not redacted.startswith(HEADER):
            redacted = HEADER + redacted
        path.write_text(redacted)
        print(f"  {rel}: replaced {n} host identifier(s)")

    verb = "would be redacted in" if check_only else "redacted in"
    print(f"{total} host identifier(s) {verb} {touched} file(s) under "
          f"{EVALUATION.relative_to(_repo_root())}")
    return 1 if (check_only and touched) else 0


if __name__ == "__main__":
    raise SystemExit(main())
