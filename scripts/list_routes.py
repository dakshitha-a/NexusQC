#!/usr/bin/env python3
"""Every HTTP route the server declares, at a given commit, WITH its prefix.

    python3 scripts/list_routes.py            # the working tree
    python3 scripts/list_routes.py <commit>   # that commit, without checking it out

Used by scripts/check_destructive.sh's check 4, which asks whether an update
removes a route that a browser tab loaded before the update will keep calling.

It exists because reading the decorators alone is not enough, and that was
R-093. Each router in server/routes/ is created with
`APIRouter(prefix="/api/jobs")` and its handlers are decorated with the rest of
the path, so renaming the prefix leaves every decorator in the file untouched.
The old check extracted decorator literals only, saw an identical list, and
reported "no route was removed" for the single largest instance of the thing it
exists to catch: every route on that router disappearing at once. A false
negative, so it failed quietly.

Deliberately static. It parses the source rather than importing it or asking a
running app, because the FROM side of the comparison is a commit that is not
checked out and whose dependencies may not even be installed. That means it
cannot see a path built from an f-string or a router included under a second
prefix in main.py; those are named as limitations rather than guessed at.
"""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

_ROUTER_PREFIX = re.compile(r"""APIRouter\((?P<args>[^)]*)\)""", re.S)
_PREFIX_ARG = re.compile(r"""prefix\s*=\s*["'](?P<p>[^"']*)["']""")
_DECORATOR = re.compile(
    r"""@(?:app|router)\.(?P<verb>get|post|put|patch|delete)\(\s*["'](?P<path>[^"']*)["']"""
)


def routes_in(source: str) -> list[str]:
    """(VERB, full path) pairs declared in one module's source, as strings."""
    prefix = ""
    m = _ROUTER_PREFIX.search(source)
    if m:
        pm = _PREFIX_ARG.search(m.group("args"))
        if pm:
            prefix = pm.group("p")
    out = []
    for d in _DECORATOR.finditer(source):
        out.append(f"{d.group('verb').upper()} {prefix}{d.group('path')}")
    return out


def _files_at(commit: str | None) -> list[tuple[str, str]]:
    if commit is None:
        return [(str(p.relative_to(REPO)), p.read_text())
                for p in sorted((REPO / "server").rglob("*.py"))]
    listing = subprocess.run(
        ["git", "ls-tree", "-r", "--name-only", commit, "--", "server"],
        cwd=REPO, capture_output=True, text=True, check=True).stdout.split()
    out = []
    for name in listing:
        if not name.endswith(".py"):
            continue
        src = subprocess.run(["git", "show", f"{commit}:{name}"],
                             cwd=REPO, capture_output=True, text=True)
        if src.returncode == 0:
            out.append((name, src.stdout))
    return out


def main() -> int:
    commit = sys.argv[1] if len(sys.argv) > 1 else None
    routes: set[str] = set()
    for _name, src in _files_at(commit):
        routes.update(routes_in(src))
    for r in sorted(routes):
        print(r)
    return 0


if __name__ == "__main__":
    sys.exit(main())
