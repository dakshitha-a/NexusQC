#!/usr/bin/env python3
"""The deployment tooling does what it says, and says what it did.
Regression test for R-019 through R-026, R-053 to R-059 and R-091 to R-093.

    PYTHONPATH=$PWD python3 tests/backend/deploy_07_update_rollback_and_backup.py

Phase 2 of the fix plan is one file cluster: the four shell scripts an
operator runs when something has to change or has already gone wrong. The
review found nine separate ways they overstate, understate, or silently skip
what they are doing. Most are not reproducible by running the real thing
against the real deployment -- a rollback, a Postgres major bump, a killed
drain -- so the checks here are of three kinds, and each says which it is:

**Executed.** `backup.sh --full` runs for real against a scratch backup root
seeded with a foreign directory that must survive, and its archive is read
back to see what it holds. `git merge --ff-only <ancestor>` is run in a
scratch repository to show the behaviour R-019 rests on. `list_routes.py` is
run against synthetic sources.

**Read.** For the branches that need a broken deployment to reach -- the
unhealthy exit, the interrupt trap, the ordering of the bundle install --
what is asserted is the shape of the code, named line by line, because the
alternative is asserting nothing at all.

**Checked against the app.** `/api/health/deep` is exercised in process.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tarfile
import tempfile
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO))

from tests.fixtures import check, summary  # noqa: E402

UPDATE = (REPO / "scripts" / "update.sh").read_text()
BACKUP = (REPO / "scripts" / "backup.sh").read_text()
RESTORE = (REPO / "scripts" / "restore.sh").read_text()
CHECKD = (REPO / "scripts" / "check_destructive.sh").read_text()

print("Phase 2: the deployment tooling\n")

print("1. R-019: --rollback moves the checkout, and git says why it had to change")
# Executed: the git behaviour the finding rests on, in a scratch repository.
tmp = Path(tempfile.mkdtemp(prefix="r019-"))
def git(*a, cwd=tmp):
    return subprocess.run(["git", *a], cwd=cwd, capture_output=True, text=True)
git("init", "-q", "-b", "main")
git("config", "user.email", "t@example.invalid"); git("config", "user.name", "t")
(tmp / "f").write_text("one"); git("add", "-A"); git("commit", "-qm", "one")
first = git("rev-parse", "HEAD").stdout.strip()
(tmp / "f").write_text("two"); git("add", "-A"); git("commit", "-qm", "two")
second = git("rev-parse", "HEAD").stdout.strip()
r = git("merge", "--ff-only", first)
after = git("rev-parse", "HEAD").stdout.strip()
check("git merge --ff-only <ancestor> exits 0 and moves nothing",
      r.returncode == 0 and after == second,
      f"rc={r.returncode}, HEAD still {after[:7]}: {r.stdout.strip()}")
r = git("checkout", "--detach", "-q", first)
after = git("rev-parse", "HEAD").stdout.strip()
check("git checkout --detach does move it", after == first, f"HEAD now {after[:7]}")

check("update.sh takes the detach path on --rollback",
      'if [ "$ROLLBACK" -eq 1 ]; then\n            git checkout --detach' in UPDATE, "",
      "the rollback path still merges, which is a no-op onto an ancestor")
check("and refuses to continue if the checkout did not actually move",
      'if [ "$MOVED_SHA" != "$TARGET_SHA" ]; then' in UPDATE, "",
      "a git command that declines and exits 0 would still be believed")

print("\n2. R-020: an unhealthy deployment exits non-zero")
check("the unhealthy branch returns 1",
      re.search(r"updated, but it did not come up healthy[\s\S]{0,900}?return 1", UPDATE) is not None,
      "", "main still falls off its end after the warning, so the exit status is 0 "
          "and deploy_runner.sh writes 'done' for a deployment that is down")

print("\n3. R-023: INT and TERM are trapped, not just EXIT")
check("update.sh has an on_signal handler", "on_signal()" in UPDATE)
for sig in ("INT", "TERM"):
    check(f"and traps {sig}", f"trap 'on_signal {2 if sig == 'INT' else 15}' {sig}" in UPDATE, "",
          f"a Ctrl-C during the drain leaves job admission paused")
check("and the later clears release all three",
      "trap - EXIT INT TERM" in UPDATE and "trap - EXIT\n" not in UPDATE, "",
      "a stale INT trap would fire after the script meant to be done")

print("\n4. R-091: no bare read at a prompt")
check("update.sh's confirmation uses the shared ask()",
      "ask 'Type UPDATE to go ahead anyway: '" in UPDATE, "",
      "a bare read exits silently at end of input under set -e")
check("restore.sh handles end of input at both prompts",
      RESTORE.count("read -r") == RESTORE.count("read -r reply || ") + RESTORE.count("read -r full_reply || "),
      f"{RESTORE.count('read -r')} read(s)",
      "one of restore.sh's prompts still dies silently, mid-outage")

print("\n5. R-021, R-024, R-025: backup.sh, run for real")
# Executed. A scratch backup root, seeded with something this script does not
# own and must not touch, and a data/ tree with one of each thing the old
# include list missed.
scratch = Path(tempfile.mkdtemp(prefix="r021-"))
backup_root = scratch / "shared-archive"
(backup_root / "someone-elses-archive").mkdir(parents=True)
(backup_root / "someone-elses-archive" / "keep-me.txt").write_text("not this script's")
old = time.time() - 400 * 86400
os.utime(backup_root / "someone-elses-archive", (old, old))
stale_backup = backup_root / "20200101-000000"
stale_backup.mkdir()
(stale_backup / "MANIFEST.txt").write_text("created: long ago\n")
os.utime(stale_backup, (old, old))

env = dict(os.environ,
           QC_AGENT_BACKUP_DIR=str(backup_root),
           QC_AGENT_BACKUP_RETAIN_DAYS="30")
r = subprocess.run(["bash", "scripts/backup.sh", "--full"], cwd=REPO, env=env,
                   capture_output=True, text=True, timeout=900)
check("backup.sh --full completes", r.returncode == 0,
      f"rc={r.returncode}", f"rc={r.returncode}\n{r.stdout[-800:]}\n{r.stderr[-400:]}")

made = sorted(d for d in backup_root.iterdir()
              if d.is_dir() and re.fullmatch(r"\d{8}-\d{6}", d.name) and d.name != "20200101-000000")
check("it wrote one backup directory", len(made) == 1, f"{[d.name for d in made]}")
if made:
    archive = made[0] / "full_data.tar.gz"
    check("with a full data archive", archive.exists(), f"{archive.name}" if archive.exists() else "")
    if archive.exists():
        with tarfile.open(archive) as tf:
            tops = sorted({m.name.split("/")[1] for m in tf.getmembers()
                           if m.name.startswith("data/") and len(m.name.split("/")) > 1})
        # The three R-021 named, plus the six that were already there.
        for want in ("plots", "projects.json", "scraped", "jobs", "kb", "uploads"):
            present = want in tops
            live = (REPO / "data" / want).exists()
            if not live:
                continue
            check(f"the archive holds data/{want}", present, "",
                  f"data/{want} exists on this deployment and is not in the archive")
        print(f"        (archive holds: {', '.join(tops)})")

check("R-024: the foreign directory survived the retention pass",
      (backup_root / "someone-elses-archive" / "keep-me.txt").exists(), "",
      "an unrelated directory older than the window was deleted, from a script "
      "that normally runs unattended from cron")
check("R-024: and a real old backup of this script's own was pruned",
      not stale_backup.exists(), "",
      "retention no longer prunes anything at all, which is the other way to "
      "get this wrong")

tar_line = next((ln for ln in BACKUP.splitlines()
                 if ln.strip().startswith("tar -C") and "-czf" in ln), "")
check("R-025: tar's exit status does not abort the run",
      "|| true" in tar_line, tar_line.strip()[:80],
      "GNU tar exits 1 for 'file changed as we read it', which for a running "
      "job is expected, and that aborted the backup update.sh insists on")
check("R-025: and the archive is still verified by reading it back",
      'tar -tzf "${DEST}/full_data.tar.gz"' in BACKUP, "",
      "removing the exit-status check without the integrity check would be worse "
      "than the bug")
check("R-024: backup.sh no longer chmods the whole backup root",
      'chmod 700 "$DEST"' in BACKUP and 'chmod 700 "$BACKUP_ROOT"' not in BACKUP, "",
      "it still re-locks a directory it does not own")

print("\n6. R-022: restore.sh reads .env and reports pg_restore's status")
check("it reads the database name from the manifest and .env, not the environment alone",
      "manifestget" in RESTORE and "envget" in RESTORE, "",
      "a restore from a plain shell still targets qc_agent whatever .env says")
check("and stops on a non-zero pg_restore",
      'PG_RC=$?' in RESTORE and 'exit "$PG_RC"' in RESTORE, "",
      "every failure is still absorbed into one reassuring sentence and the "
      "script prints 'Restore finished.'")

print("\n7. R-053, R-054, R-058: ordering, drift and what healthy means")
build_at = UPDATE.index('"${COMPOSE[@]}" build')
extract_at = UPDATE.index("bash scripts/extract_frontend.sh")
health_at = UPDATE.index("qc_wait_for_health 300")
check("R-053: the bundle is installed after the health check, not before the recreate",
      build_at < health_at < extract_at, "",
      "the new SPA goes live against the old api for the length of the recreate "
      "plus up to 300 s of health wait")
check("R-054: the up-to-date test allows a documentation-only gap",
      "stamp_is_current" in UPDATE, "",
      "a docs-only update leaves the stamp permanently behind, so every later "
      "run takes a full backup and does nothing")
check("R-058: update.sh asks whether the dependencies are reachable",
      "/api/health/deep" in UPDATE, "",
      "a wrong Postgres password still reads as a healthy deployment")

from fastapi.testclient import TestClient  # noqa: E402
import server.main as main_mod  # noqa: E402

client = TestClient(main_mod.app)
r = client.get("/api/health")
check("/api/health is still cheap and still 200", r.status_code == 200, f"{r.json()}")
r = client.get("/api/health/deep")
check("/api/health/deep answers", r.status_code in (200, 503), f"HTTP {r.status_code} {r.json()}")
check("and reports each dependency separately",
      isinstance(r.json().get("checks"), dict), f"{r.json()}")

print("\n8. R-055, R-057, R-093: what check_destructive.sh can see")
check("R-055: the mount check compares the live mounts against the resolved config",
      "CONFIG_MOUNTS" in CHECKD and "docker compose config" in CHECKD, "",
      "it still only asks whether the override file exists")
check("R-057: image tags are compared between the two commits",
      "compose_images" in CHECKD, "",
      "a postgres major bump still passes as a generic recreate warning")
check("R-057: and named volumes",
      "compose_volumes" in CHECKD, "",
      "a renamed volume still starts an empty database that comes up healthy")

sys.path.insert(0, str(REPO / "scripts"))
try:
    from list_routes import routes_in  # noqa: E402
except ImportError:
    routes_in = None
if routes_in is None:
    check("R-093: routes are read with their router's prefix", False, "",
          "scripts/list_routes.py does not exist, so check 4 still extracts "
          "decorator literals only and a prefix rename reads as no change")
else:
    before = 'router = APIRouter(prefix="/api/jobs")\n@router.get("/{job_id}")\ndef g(): ...\n'
    after = 'router = APIRouter(prefix="/api/job")\n@router.get("/{job_id}")\ndef g(): ...\n'
    check("R-093: a route is read with its router's prefix",
          routes_in(before) == ["GET /api/jobs/{job_id}"], f"{routes_in(before)}")
    check("R-093: so renaming the prefix reads as the route disappearing",
          routes_in(before) != routes_in(after),
          f"{routes_in(before)} vs {routes_in(after)}",
          "a prefix rename still reads as 'no route was removed', for every route "
          "on that router at once")
check("R-093: and check 4 uses it", "list_routes.py" in CHECKD, "")

print("\n9. R-059: the dependencies are pinned")
reqs = [ln.strip() for ln in (REPO / "requirements.txt").read_text().splitlines()
        if ln.strip() and not ln.strip().startswith("#")]
unpinned = [ln for ln in reqs if "==" not in ln]
check("every requirement carries an exact version", not unpinned,
      f"{len(reqs)} requirements, all pinned", f"unpinned: {unpinned}")

print("\n10. R-026, R-062, R-092: the documentation runs as printed")
dep = (REPO / "docs" / "DEPLOYMENT.md").read_text()
check("R-026: the bootstrap command passes all four required arguments",
      "--first-name" in dep and "--last-name" in dep, "",
      "the documented command exits with an argparse error")
check("R-062: the cron line creates its own log directory",
      "mkdir -p backups && ./scripts/backup.sh" in dep, "",
      "the shell opens the redirect before the script runs, so the job fails "
      "nightly and silently")
check("R-062: the curl examples pass -k against the self-signed certificate",
      "curl -s " not in dep, "", "some examples still fail certificate verification")
check("R-062: no pointer to the deleted docker-compose.dev.yml",
      "docker-compose.dev.yml" not in dep, "")
check("R-062: the status table no longer lists removed features",
      "Public nginx listener" not in dep and "Host-level kill switch" not in dep, "")
ngx = (REPO / "nginx" / "nginx.conf").read_text()
header = ngx[:ngx.index("worker_processes")]
check("R-092: nginx.conf's header does not describe the removed listener",
      "toggle_public_access.sh -- \n" not in header
      and "a public listener that a host sysadmin can cut off" not in header, "",
      "the top of the file still contradicts the bottom of the same file")

summary()
