#!/usr/bin/env python3
"""Removes the jobs this suite run created. Runs last, by name.

Why this exists. Test scripts submit real jobs, and most do it by calling
`JobManager.submit`/`submit_scan` in-process rather than through the HTTP
API. Ownership is recorded by the API ROUTE, not by `JobManager`, so those
jobs end up with no recorded owner -- and an unowned job is deliberately
visible to every user (`server/routes/jobs.py`'s `list_all_jobs`; the point
is that anyone can see it, so anyone can clear it). Left alone, every suite
run therefore added permanent clutter to everybody's job list. 13 such jobs
had accumulated by 2026-08-23, which is what prompted this.

Why it is scoped to a baseline rather than "delete every unowned job".
An unowned job is a legitimate, deliberately shared thing on a real
deployment. A test run has no business removing one it did not create. So
`_00_bootstrap.py` records which jobs already existed at the start of the
run, and this removes only what appeared since. With no baseline file this
script SKIPS rather than guessing -- an over-eager sweep here would delete
a user's work, which is far worse than leaving clutter.

The `zz_` prefix is doing real work: `run_backend.sh` runs
`find tests/backend -name '*.py' | sort`, so this sorts after every other
script and before nothing. `_00_bootstrap.py` sorts first for the same
reason (`_` is 0x5F, below the lowercase letters).

Note this covers the SUITE. A script run on its own still leaves its jobs
behind unless it cleans up itself -- `fixtures.cleanup_jobs` is there for
that, and a new script that submits anything should wire it up.

Run:  PYTHONPATH=$PWD python3 tests/backend/zz_99_job_cleanup.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from fixtures import admin_client, check, cleanup_jobs, list_job_ids, skip, summary  # noqa: E402

BASELINE_FILE = Path(__file__).resolve().parent.parent / ".jobs_before_run"


def main() -> None:
    if not BASELINE_FILE.exists():
        skip("job sweep",
             f"no baseline at {BASELINE_FILE.name} -- _00_bootstrap.py writes it at the "
             f"start of a full run. Skipping rather than deleting jobs this run may not "
             f"have created.")
        summary()
        return

    baseline = {line.strip() for line in BASELINE_FILE.read_text().splitlines() if line.strip()}
    # admin_client() hands back an already-open client, so it is assigned
    # rather than used as a context manager -- the convention every other
    # script in this directory follows.
    admin = admin_client()
    now = list_job_ids(admin)
    created = now - baseline
    print(f"  {len(baseline)} job(s) pre-existed, {len(now)} present now, "
          f"{len(created)} created by this run")
    if not created:
        check("no jobs left behind by this run", True)
        summary()
        return

    deleted, remaining = cleanup_jobs(admin, created)
    check("every job this run created was removed",
          not remaining,
          f"deleted {deleted}/{len(created)}; still present: {remaining}")

    # Prove it against the route the user actually looks at, rather than
    # trusting the delete responses.
    leftover = list_job_ids(admin) - baseline
    check("the job list is back to what it held before the run",
          not leftover, f"unexpected leftovers: {sorted(leftover)}")

    # The baseline is per-run bookkeeping; leaving it behind would let a
    # later standalone invocation sweep against a stale, much older list.
    BASELINE_FILE.unlink(missing_ok=True)
    summary()


if __name__ == "__main__":
    main()
