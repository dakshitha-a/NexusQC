"""What --rollback returns to, given a deployment history that includes
updates which never came up healthy.

scripts/update.sh used to append its `updated` line to .update-log BEFORE
the health check was considered, so a deployment that never came up was
recorded exactly like one that did. The consequence is not visible until a
second update follows a failed one: `--rollback` then resolves to a commit
that was never healthy, which is the worst possible answer to "put it back
the way it was".

The script now records `unhealthy` instead when the health check fails, and
resolves the rollback target to the most recent commit the deployment is
known to have actually run. This exercises the real awk program, extracted
from scripts/update.sh rather than copied here -- a copy would keep passing
after the original changed, which for a recovery path is worse than no test.

Needs no stack: it is log arithmetic, and every case below is a synthetic
.update-log written to a temporary file.
"""
from __future__ import annotations

import re
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from fixtures import check, summary  # noqa: E402

UPDATE_SH = Path(__file__).resolve().parent.parent.parent / "scripts" / "update.sh"


def _awk_program() -> str:
    """The rollback-target program as it actually appears in update.sh."""
    src = UPDATE_SH.read_text()
    m = re.search(r"PREV=\"\$\(awk '\n(.*?)\n    ' \"\$UPDATE_LOG\"\)\"", src, re.S)
    if not m:
        raise SystemExit(
            "could not find the rollback awk program in scripts/update.sh -- if it was "
            "restructured, update this extraction rather than inlining a copy."
        )
    return m.group(1)


def resolve(lines: list[str]) -> str:
    with tempfile.NamedTemporaryFile("w", suffix=".update-log", delete=False) as fh:
        fh.write("".join(line + "\n" for line in lines))
        path = fh.name
    try:
        out = subprocess.run(["awk", _awk_program(), path], capture_output=True, text=True)
        if out.returncode != 0:
            raise RuntimeError(out.stderr)
        return out.stdout.strip()
    finally:
        Path(path).unlink(missing_ok=True)


def main() -> None:
    # A log written before the `unhealthy` verb existed contains only `updated`
    # lines. Those must resolve exactly as the old `tail -n1` of $4 did, or
    # this change breaks rollback on every deployment that predates it.
    check(
        "one healthy update rolls back to what was running before it",
        resolve(["updated 2026-08-01T00:00:00Z bbb aaa"]) == "aaa",
        resolve(["updated 2026-08-01T00:00:00Z bbb aaa"]),
    )
    check(
        "a chain of healthy updates rolls back exactly one step",
        resolve([
            "updated 2026-08-01T00:00:00Z bbb aaa",
            "updated 2026-08-02T00:00:00Z ccc bbb",
        ]) == "bbb",
        resolve([
            "updated 2026-08-01T00:00:00Z bbb aaa",
            "updated 2026-08-02T00:00:00Z ccc bbb",
        ]),
    )

    # The case the old code got wrong. ccc never came up; rolling back from it
    # must return to bbb, which did.
    check(
        "an update that failed its health check rolls back to the last healthy commit",
        resolve([
            "updated 2026-08-01T00:00:00Z bbb aaa",
            "unhealthy 2026-08-02T00:00:00Z ccc bbb",
        ]) == "bbb",
        resolve([
            "updated 2026-08-01T00:00:00Z bbb aaa",
            "unhealthy 2026-08-02T00:00:00Z ccc bbb",
        ]),
    )

    # The failure this test exists for: an operator does not notice the failed
    # health check and updates again. bbb was never healthy, so it must not be
    # the commit --rollback returns to.
    check(
        "a second update after a failed one still skips past the commit that never came up",
        resolve([
            "unhealthy 2026-08-01T00:00:00Z bbb aaa",
            "unhealthy 2026-08-02T00:00:00Z ccc bbb",
        ]) == "aaa",
        resolve([
            "unhealthy 2026-08-01T00:00:00Z bbb aaa",
            "unhealthy 2026-08-02T00:00:00Z ccc bbb",
        ]),
    )
    check(
        "a healthy update after a failed one is rolled back to, not past",
        resolve([
            "unhealthy 2026-08-01T00:00:00Z bbb aaa",
            "updated 2026-08-02T00:00:00Z ccc bbb",
        ]) == "aaa",
        resolve([
            "unhealthy 2026-08-01T00:00:00Z bbb aaa",
            "updated 2026-08-02T00:00:00Z ccc bbb",
        ]),
    )

    # The very first entry's own $4 is the only record of what the deployment
    # ran before this script ever touched it, so a log whose only line is a
    # failure still has somewhere to go back to.
    check(
        "a first-ever update that failed rolls back to the pre-install commit",
        resolve(["unhealthy 2026-08-01T00:00:00Z bbb aaa"]) == "aaa",
        resolve(["unhealthy 2026-08-01T00:00:00Z bbb aaa"]),
    )

    summary()


if __name__ == "__main__":
    main()
