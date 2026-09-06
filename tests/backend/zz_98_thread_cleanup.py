#!/usr/bin/env python3
"""Removes the conversations this suite run created. Runs second-to-last.

The counterpart to `zz_99_job_cleanup.py`, and it exists for the same reason
that one does, arrived at the same way: a full run left four `qatest_*`
conversations in the sidebar on 2026-08-29, and they had been accumulating
before that. Scripts open threads through `thread_registry.create_thread`,
which -- unlike the HTTP route -- records no ownership at all, so nothing
associated them with a test user and nothing removed them.

Scoped to a baseline rather than a name pattern, for a sharper version of the
reason the job sweep gives. Sweeping every conversation whose label starts
`qatest_` would work today and would be wrong tomorrow: the rule the repo
actually holds to is that a session deletes what it created and nothing else,
and a conversation is the more painful of the two things here to lose by
mistake. So `_00_bootstrap.py` records which conversations already existed and
this removes only what appeared since. With no baseline file it SKIPS.

Sorts before `zz_99_job_cleanup.py` deliberately: jobs are what a reader
notices missing, so the job sweep's own report should be the last word in the
run's output.

Run:  PYTHONPATH=$PWD python3 tests/backend/zz_98_thread_cleanup.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from fixtures import (  # noqa: E402
    admin_client, check, cleanup_threads, list_thread_ids, skip, summary,
)

BASELINE_FILE = Path(__file__).resolve().parent.parent / ".threads_before_run"


def main() -> None:
    if not BASELINE_FILE.exists():
        skip("conversation sweep",
             f"no baseline at {BASELINE_FILE.name} -- _00_bootstrap.py writes it at the "
             f"start of a full run. Skipping rather than deleting conversations this run "
             f"may not have created.")
        summary()
        return

    baseline = {line.strip() for line in BASELINE_FILE.read_text().splitlines() if line.strip()}
    admin = admin_client()
    now = list_thread_ids(admin)
    created = now - baseline
    print(f"  {len(baseline)} conversation(s) pre-existed, {len(now)} present now, "
          f"{len(created)} created by this run")
    if not created:
        check("no conversations left behind by this run", True)
        summary()
        return

    deleted, remaining = cleanup_threads(admin, created)
    check("every conversation this run created was removed",
          not remaining,
          f"deleted {deleted}/{len(created)}; still present: {remaining}")

    final = list_thread_ids(admin)
    leftover = final - baseline
    check("the conversation list is back to what it held before the run",
          not leftover, f"unexpected leftovers: {sorted(leftover)}")

    # The other direction, for the same reason zz_99 grew one on 2026-09-06.
    # `leftover` is one-sided: it catches conversations the run ADDED and is
    # blind to ones it DESTROYED. A run that wiped every pre-existing
    # conversation would pass this check, which is the one outcome it exists to
    # prevent.
    vanished = baseline - final
    check("and no conversation that pre-existed the run was destroyed by it",
          not vanished,
          f"{len(vanished)} pre-existing conversation(s) are gone: "
          f"{sorted(vanished)[:10]}{' ...' if len(vanished) > 10 else ''}")

    # Per-run bookkeeping; leaving it would let a later standalone invocation
    # sweep against a stale, much older list.
    BASELINE_FILE.unlink(missing_ok=True)
    summary()


if __name__ == "__main__":
    main()
