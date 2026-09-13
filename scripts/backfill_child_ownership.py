#!/usr/bin/env python3
"""Give every existing sub-job the ownership row its master already has.

    docker compose exec -T api python3 scripts/backfill_child_ownership.py --dry-run
    docker compose exec -T api python3 scripts/backfill_child_ownership.py

Run once per deployment, after updating past the commit that closed R-001.
Idempotent: a second run reports nothing to do.

Why it exists. A batch, scan, ensemble or geometry-set master is submitted
with an owner; its children were submitted with none, on the reasoning that
only the master is individually reachable. `GET /api/jobs/{id}` reaches any
job id, so that reasoning was wrong and the children were readable, and
downloadable, by any authenticated user. The code fix is two-sided: children
are recorded at submit from now on, and `app/auth/ownership.effective_owner`
walks `parent_job_id` when a row is missing, so children created before this
runs are already protected without it.

This script exists anyway, for two reasons. The walk is a per-request
Postgres lookup plus a spec.json read on a route the job manager polls, and a
real row makes it a single indexed read. And a child with a row of its own
appears in `list_owned`, which is what `download-my-data` and the per-user
quota accounting consult, so without the backfill an older child is private
but invisible to the user's own accounting.

Reads `parent_job_id` from each job's `spec.json` and the owner from
`ownership_index`. Writes nothing for a child whose master has no owner
either: that is the genuine legacy/unowned case, which stays visible to
everyone by design (see app/auth/ownership.py's module docstring).
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from app.chemistry.jobs.base import JOBS_DIR  # noqa: E402
from app.config import DATABASE_URL  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dry-run", action="store_true",
                    help="report what would be written and write nothing")
    args = ap.parse_args()

    if not DATABASE_URL:
        print("QC_AGENT_DATABASE_URL is not set, so this deployment has no ownership "
              "index and nothing to back-fill. Nothing to do.")
        return 0

    from app.auth.models import get_owner, record_ownership

    children: dict[str, str] = {}
    for d in sorted(JOBS_DIR.iterdir()):
        if not d.is_dir() or d.name == "_seen":
            continue
        spec_path = d / "spec.json"
        if not spec_path.exists():
            continue
        try:
            parent = json.loads(spec_path.read_text()).get("parent_job_id")
        except (json.JSONDecodeError, OSError) as exc:
            print(f"  [skip] {d.name}: unreadable spec.json ({exc})")
            continue
        if parent:
            children[d.name] = parent

    print(f"{len(children)} sub-job(s) found under {JOBS_DIR}.")
    wrote = already = orphaned = unowned = 0
    for job_id, parent_id in sorted(children.items()):
        if get_owner("job", job_id) is not None:
            already += 1
            continue
        owner = get_owner("job", parent_id)
        if owner is None:
            if not (JOBS_DIR / parent_id / "spec.json").exists():
                orphaned += 1
                print(f"  [skip] {job_id}: its master {parent_id} no longer exists")
            else:
                unowned += 1
                print(f"  [skip] {job_id}: its master {parent_id} has no owner either "
                      f"(legacy/unowned, visible to everyone by design)")
            continue
        if args.dry_run:
            print(f"  [would write] {job_id} -> {owner} (from master {parent_id})")
        else:
            record_ownership("job", job_id, owner)
            print(f"  [wrote] {job_id} -> {owner} (from master {parent_id})")
        wrote += 1

    verb = "would be written" if args.dry_run else "written"
    print(f"\n{wrote} row(s) {verb}; {already} already had one; "
          f"{unowned} left alone (master unowned); {orphaned} skipped (master gone).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
