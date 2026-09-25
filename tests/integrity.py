"""Proves a test run left real users' data alone.

The stack the suites run against is also a research group's deployment, so
"the tests passed" is not enough: a test can pass while deleting somebody
else's work, and on 2026-09-24 one did. Every runner therefore takes a
snapshot before it starts and compares against it when it finishes:

    python3 tests/integrity.py snapshot <file>
    python3 tests/integrity.py compare <file>     # exit 1 if anything was lost

What a snapshot records, for every account whose name does not start with
qatest_ (the test accounts are the suites' own and come and go):

  - the account itself;
  - every resource the ownership index says it owns (jobs, conversations,
    uploads, plots, projects), and whether that resource is really there
    (a job's directory, a conversation's registry entry);
  - for each of its finished jobs, the name and size of every file;
  - its knowledge-base, plot and geometry-upload files on disk.

It also records every job with no owner, because the app shows those to
everybody and nothing says whose they are, so they are treated as real.

compare fails on: an account gone, a resource gone or owned by someone else,
a finished job missing a file it had, a knowledge-base, plot or upload file gone.
New things, and files changing on jobs that were still running, are fine.
Deployment settings that changed are listed but do not fail the run, since
an admin may legitimately change one mid-run. If a real user deleted
something themselves during the run, it will be reported too; the report
names each item so a person can tell which.

Standalone invoke-and-print, like the rest of tests/. Runs the snapshot
inside the api container, which already has every path and the database.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

COMPOSE_DIR = Path(__file__).resolve().parent.parent

_SNAPSHOT_CODE = r'''
import json, os
from pathlib import Path
from app.auth import models
from app.auth.db import get_pool
from app.config import JOBS_DIR, UPLOADS_DIR, PLOTS_DIR, GEOMETRY_UPLOADS_DIR
from app.agent import threads as thread_registry
from app.chemistry.jobs.base import read_status

TERMINAL = {"completed", "failed", "cancelled"}

def manifest(d):
    out = {}
    if not d.is_dir():
        return out
    for p in d.rglob("*"):
        if p.is_file():
            try:
                out[str(p.relative_to(d))] = p.stat().st_size
            except OSError:
                pass
    return out

users = {str(u["id"]): u["username"] for u in models.list_users()
         if not (u["username"] or "").startswith("qatest_")}
with get_pool().connection() as conn:
    rows = conn.execute("SELECT kind, resource_id, owner_user_id::text AS owner FROM ownership_index").fetchall()
    cfg = {r["key"]: r["value"] for r in conn.execute("SELECT key, value FROM app_config").fetchall()}

owned = {}
all_owned_jobs = set()
for r in rows:
    if r["kind"] == "job":
        all_owned_jobs.add(r["resource_id"])
    if r["owner"] not in users:
        continue
    kind, rid = r["kind"], r["resource_id"]
    item = {"kind": kind, "id": rid, "owner": users[r["owner"]]}
    if kind == "job":
        d = JOBS_DIR / rid
        item["present"] = (d / "spec.json").exists()
        st = (read_status(rid) or {}).get("status")
        item["status"] = st
        if st in TERMINAL:
            item["files"] = manifest(d)
    elif kind == "thread":
        item["present"] = thread_registry.get_thread(rid) is not None
    elif kind == "upload":
        item["present"] = any((GEOMETRY_UPLOADS_DIR / r["owner"]).glob(f"{rid}*"))
    else:
        item["present"] = True
    owned[f"{kind}:{rid}"] = item

unowned_jobs = {}
if JOBS_DIR.is_dir():
    for d in JOBS_DIR.iterdir():
        # A scan's or ensemble's sub-jobs carry no row of their own and go
        # with their master, so they are the master's, not ownerless jobs;
        # counting them made a test deleting its own scan look like a loss.
        if d.is_dir() and not d.name.startswith("_") and d.name not in all_owned_jobs and (d / "spec.json").exists():
            try:
                if json.loads((d / "spec.json").read_text()).get("parent_job_id"):
                    continue
            except Exception:
                pass
            st = (read_status(d.name) or {}).get("status")
            unowned_jobs[d.name] = {"status": st, "files": manifest(d) if st in TERMINAL else None}

files = {}
for uid, name in users.items():
    files[f"kb:{name}"] = manifest(UPLOADS_DIR / uid)
    files[f"plots:{name}"] = manifest(PLOTS_DIR / uid)
    files[f"uploads:{name}"] = manifest(GEOMETRY_UPLOADS_DIR / uid)

print("@@@" + json.dumps({"users": sorted(users.values()), "owned": owned,
                          "unowned_jobs": unowned_jobs, "files": files, "config": cfg}))
'''


def take() -> dict:
    proc = subprocess.run(
        ["docker", "compose", "exec", "-T", "api", "python", "-c", _SNAPSHOT_CODE],
        cwd=str(COMPOSE_DIR), capture_output=True, text=True, timeout=300,
    )
    line = next((ln for ln in proc.stdout.splitlines() if ln.startswith("@@@")), None)
    if line is None:
        raise RuntimeError(f"snapshot failed: {proc.stderr[-800:]}")
    return json.loads(line[3:])


def compare(before: dict, after: dict) -> tuple[list[str], list[str]]:
    """(losses, notes). A loss fails the run; a note is only printed."""
    losses: list[str] = []
    notes: list[str] = []

    for name in before["users"]:
        if name not in after["users"]:
            losses.append(f"account {name} is gone")

    for key, b in before["owned"].items():
        a = after["owned"].get(key)
        label = f"{b['kind']} {b['id']} of {b['owner']}"
        if not b.get("present"):
            continue
        if a is None:
            if b["owner"] in after["users"]:
                losses.append(f"{label} is gone, or no longer owned by {b['owner']}")
            continue
        if not a.get("present"):
            losses.append(f"{label} is gone from disk")
            continue
        for fname, size in (b.get("files") or {}).items():
            if fname not in (a.get("files") or {}):
                losses.append(f"{label} lost the file {fname} ({size} bytes)")

    for jid, b in before["unowned_jobs"].items():
        a = after["unowned_jobs"].get(jid)
        if a is None:
            if f"job:{jid}" in after["owned"]:
                continue  # it was given an owner, which is not a loss
            losses.append(f"job {jid} with no owner is gone")
            continue
        for fname, size in (b.get("files") or {}).items():
            if fname not in (a.get("files") or {}):
                losses.append(f"job {jid} with no owner lost the file {fname} ({size} bytes)")

    for key, bfiles in before["files"].items():
        afiles = after["files"].get(key, {})
        for fname in bfiles:
            if fname not in afiles:
                losses.append(f"{key.replace(':', ' file of ', 1)}: {fname} is gone")

    for k in sorted(set(before["config"]) | set(after["config"])):
        if before["config"].get(k) != after["config"].get(k):
            notes.append(f"setting {k}: {before['config'].get(k)!r} -> {after['config'].get(k)!r}")

    return losses, notes


def main() -> int:
    if len(sys.argv) != 3 or sys.argv[1] not in ("snapshot", "compare"):
        print(__doc__.split("\n\n")[1], file=sys.stderr)
        return 2
    path = Path(sys.argv[2])
    if sys.argv[1] == "snapshot":
        snap = take()
        path.write_text(json.dumps(snap))
        n_items = len(snap["owned"])
        print(f"integrity: recorded {len(snap['users'])} real account(s), {n_items} item(s) they own, "
              f"{len(snap['unowned_jobs'])} job(s) with no owner")
        return 0

    before = json.loads(path.read_text())
    losses, notes = compare(before, take())
    for n in notes:
        print(f"integrity: note: {n}")
    if losses:
        print(f"integrity: FAIL -- {len(losses)} thing(s) belonging to real users were lost during this run:")
        for line in losses:
            print(f"  - {line}")
        return 1
    print(f"integrity: PASS -- real users' data unchanged ({len(before['users'])} account(s), "
          f"{len(before['owned'])} owned item(s), {len(before['unowned_jobs'])} job(s) with no owner)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
