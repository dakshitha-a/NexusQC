# Phase 2, the deployment tooling

One regression test for the whole phase,
`tests/backend/deploy_07_update_rollback_and_backup.py`, because the four
scripts are one cluster: `update.sh` calls `backup.sh` and
`check_destructive.sh`, `restore.sh` reads what `backup.sh` wrote, and
several findings are visible from more than one of them.

**11 of 45 checks before, 46 of 46 after.**

The checks are of three kinds and the script says which is which, because
most of these branches cannot be reached by running the real thing against
the real deployment.

**Executed.** `backup.sh --full` runs against a scratch backup root seeded
with a foreign directory that must survive a retention pass and a real old
backup that must not, and its archive is read back to see what it holds.
`git merge --ff-only <ancestor>` runs in a scratch repository to show the
behaviour R-019 rests on: exit 0, HEAD unmoved. `list_routes.py` runs against
synthetic sources.

**Read.** For branches that need a broken deployment -- the unhealthy exit,
the interrupt trap, the order of the bundle install -- the shape of the code
is asserted, named line by line. The alternative is asserting nothing.

**Exercised in process.** `/api/health` and the new `/api/health/deep`.

One thing worth recording about the executed half: it ran while the
end-to-end suite was writing job output into `data/jobs`, which is exactly
the condition R-025 is about. GNU tar exited non-zero for "file changed as we
read it", the archive was still complete and readable, and the run continued
instead of aborting with "backup failed -- refusing to update without one".
That is the fix demonstrating itself.
