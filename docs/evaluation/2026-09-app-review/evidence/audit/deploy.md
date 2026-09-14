# audit:deploy — the deployment surface

Read-only static audit at `0dcb865`. Nothing was executed against the stack;
`install.sh`, `update.sh`, `backup.sh`, `restore.sh` and `--dry-run` were all
left alone. Three things were run: `shellcheck` in a throwaway container
(read-only bind mount); one `git merge --ff-only` experiment in a scratch
repository under the scratchpad, to settle finding 1 empirically; and
`python3 -c` imports of `app.chemistry.registry2` and
`app.chemistry.registry2.params` to read the capability and parameter tables
directly. Those imports pull in `app/config.py`, whose module-level loop calls
`Path.mkdir(parents=True, exist_ok=True)` on the `data/` subdirectories — every
one already existed, `git status --porcelain` is empty afterwards, and nothing
tracked was touched. Disclosed because the brief's read-only rule is absolute.

`docs/TRACKER.md` (the 2026-09-10 installer audit, complete) was read first;
nothing already fixed or already listed under its "Incidental findings" is
refiled here.

---

### R-000: `scripts/update.sh --rollback` never moves the checkout back, and stamps the new image with the old commit
- surface: code:deploy
- class: bug
- severity: S2
- cause: CODE
- confidence: suspected (code read) — the git behaviour itself is confirmed empirically
- found by: audit:deploy
- scope: `scripts/update.sh` rollback path only. Checked for both branch and
  detached-HEAD checkouts; the detached case is correct. The forward-update
  path is unaffected. Not checked against a real deployment.
- repro: on a deployment made by `scripts/install.sh` (which `git clone`s, so
  HEAD is on branch `main`), run one successful `update.sh`, then
  `scripts/update.sh --rollback`. Expected: the checkout returns to the
  previous commit. Actual: HEAD stays where it is, the image is rebuilt from
  the *current* source, and the run reports a successful rollback.
- observed: `scripts/update.sh:559-564`

      CURRENT_BRANCH="$(git rev-parse --abbrev-ref HEAD)"
      if [ "$CURRENT_BRANCH" = "HEAD" ]; then
          git checkout --detach --quiet "$TARGET_SHA"
      else
          git merge --ff-only --quiet "$TARGET_SHA"
      fi

  On the rollback path `TARGET_SHA` is by construction an **ancestor** of
  HEAD (`scripts/update.sh:207-214` picks the last healthy commit out of
  `.update-log`). `git merge --ff-only <ancestor>` prints "Already up to
  date." and exits 0 without moving HEAD. Verified in a scratch repository:
  two commits, `git merge --ff-only <first>` from the second → exit 0, HEAD
  unchanged.
- expected: the rollback path should return the working tree to the recorded
  commit. `scripts/update.sh:54` documents `--rollback` as "go back to the
  last healthy commit", `check_destructive.sh:645` tells the operator "Code
  and frontend assets: fully reversible, update.sh --rollback", and
  `recovery_advice()` (`update.sh:427-429`) sends them there after a failed
  update.
- evidence: `scripts/update.sh:563` (`git merge --ff-only --quiet "$TARGET_SHA"`);
  `scripts/update.sh:191-220` (the rollback target resolution);
  `scripts/update.sh:588` (`export QC_AGENT_BUILD_COMMIT="$TARGET_SHA"`)
- pointer: two amplifiers make this worse than a no-op.
  (a) `QC_AGENT_BUILD_COMMIT` is exported as `TARGET_SHA` *before* the build,
  so the image is built from the un-rolled-back source and carries the OCI
  label of the commit it is not running. `deployed_commit()` then reports the
  old sha on every later run, and `update.sh <that sha>` answers "already up
  to date -- nothing to do".
  (b) `record_update updated` writes that same false pair into `.update-log`,
  so the *next* rollback also resolves against a fiction.
  The step even prints `ok "checked out $(git rev-parse --short HEAD)"` —
  the unchanged sha — directly under `step "moving the checkout to
  ${TARGET_SHA:0:12}"`, which is the one place an operator could have caught
  it.
- note: `tests/backend/deploy_01_rollback_target.py` covers the `awk` that
  chooses the target, not the git move, which is why this survived that work
  (`docs/trackers/2026-08-update-knows-what-it-runs.md` P3.2). The admin
  panel's Rollback button goes through the same path
  (`scripts/deploy_runner.sh:211`). Fix direction: on the rollback path use
  `git checkout --detach --quiet "$TARGET_SHA"` unconditionally (the
  subsequent forward update already handles a detached HEAD), and assert
  `git rev-parse HEAD` equals `TARGET_SHA` after the move rather than
  printing whatever HEAD happens to be.

### R-000: `update.sh` exits 0 when the deployment never came up healthy, so the admin panel records a failed update as done
- surface: code:deploy
- class: bug
- severity: S2
- cause: CODE
- confidence: suspected (code read)
- found by: audit:deploy
- scope: `scripts/update.sh` verification block and its one programmatic
  caller, `scripts/deploy_runner.sh`. Not checked: whether anything else
  shells out to `update.sh`.
- repro: make the api fail to start (e.g. a syntax error in `server/main.py`),
  run an update through the admin panel. The deployment stays down; the panel
  shows `state: done, step: "updated"`.
- observed: `scripts/update.sh:656-699`. When `qc_wait_for_health` fails, the
  script warns, dumps 25 log lines, calls `recovery_advice`, writes
  `record_update unhealthy`, prints "updated, but it did not come up
  healthy", and falls off the end of `main`. The last command is an `echo`,
  so `main` returns 0 and the script exits 0.
- expected: a non-zero exit. `scripts/deploy_runner.sh:201-207` is written on
  the assumption that the exit status carries the verdict:

      if stdbuf -oL -eL bash scripts/update.sh "${args[@]}" "$target_sha" ...; then
          write_status "$dir" done "updated" ...
      else
          rc=$?; write_status "$dir" failed "the update did not complete" ...

  so a deployment that is down is reported to the admin's browser as a
  completed update.
- evidence: `scripts/update.sh:697` (`echo "${YEL}updated, but it did not come
  up healthy${RST} ..."`) is the last statement of `main`;
  `scripts/deploy_runner.sh:201`
- pointer: `.update-log` is written correctly (`unhealthy`), so only the
  process exit code and the panel are wrong. That split is what makes it
  survivable and also what makes it hard to notice.
- note: fix is one line — `exit 1` (or a captured status returned from
  `main`) on the unhealthy branch. Worth checking at the same time that
  `deploy_runner.sh` surfaces `log.txt`'s tail in the failure status, since
  the panel currently shows only `exit_code`.

### R-000: `backup.sh --full` does not archive `data/plots`, `data/projects.json` or `data/scraped`, so a restore silently loses saved plots, every project archive, and the KB's own source
- surface: code:deploy
- class: bug
- severity: S2
- cause: CODE
- confidence: suspected (code read)
- found by: audit:deploy
- scope: `scripts/backup.sh` (both default and `--full`) against the
  directory inventory in `app/config.py:55-95`. Not checked: whether the
  operator additionally snapshots `/data` at the filesystem level, which the
  header suggests as an alternative.
- repro: `scripts/backup.sh --full`, then `tar -tzf <dest>/full_data.tar.gz |
  cut -d/ -f2 | sort -u` — the list is `jobs kb uploads geometry_uploads
  bug_reports molecules`. Save a plot in the app and repeat: the plot's
  `record.json` is not in the archive.
- observed: `scripts/backup.sh:212` `FULL_DATA_DIRS=(jobs kb uploads
  geometry_uploads bug_reports molecules)`, and the small-file loop at
  `scripts/backup.sh:195` `for f in data/threads.json; do`.
- expected: `--full` is documented as "an explicit, occasional,
  everything-included backup" and is what `update.sh:393` takes before every
  update. Three things under `data/` are neither in it nor regenerable:
  - `data/plots` — "saved plot records, one subdirectory per plot:
    record.json plus its rendered versions" (`app/config.py:71`,
    `app/plots/store.py:14`). First-class user objects with their own
    routes, quota accounting and owner directories.
  - `data/projects.json` — "project archives: named bundles of jobs"
    (`app/config.py:66`, `app/projects/registry.py`). This is exactly the
    same class of small, list-shaped, unrecoverable state as
    `data/threads.json`, which the script *does* copy for precisely the
    stated reason ("small, high-value, and genuinely lost if the disk
    goes").
  - `data/scraped` — the raw manual text (`app/config.py:59`). The script's
    own header justifies excluding `data/kb` by default on the grounds that
    it "is in any case reproducible from data/scraped via
    scripts/seed_knowledge_base.py" — but `data/scraped` is backed up in
    neither mode, so after a disk loss that reproducibility does not exist.
- evidence: `scripts/backup.sh:212`; `scripts/backup.sh:195`;
  `scripts/backup.sh:31-34` (the `data/kb` justification);
  `app/config.py:59,66,71`
- pointer: the list was written when `data/` had fewer children and has not
  been re-derived from `app/config.py` since projects and plots landed.
- note: `data/bse_basis_cache` is genuinely a cache (content-hashed, pure
  function of its inputs) and `data/deploy` is transient, so both are
  correctly out. `data/agent_checkpoints.sqlite` only matters for a
  no-Postgres deployment, which this script refuses to run against anyway.
  Fix direction: derive `FULL_DATA_DIRS` from a list kept next to
  `app/config.py`'s directory declarations, or at minimum add
  `plots`/`scraped` and put `projects.json` beside `threads.json`. A cheap
  guard: fail the backup if `ls data/` contains a directory the script does
  not know about.

### R-000: `restore.sh` ignores `.env` when choosing the database and swallows `pg_restore`'s exit status, so a restore can report success having restored nothing
- surface: code:deploy
- class: bug
- severity: S2
- cause: CODE
- confidence: suspected (code read)
- found by: audit:deploy
- scope: `scripts/restore.sh` only; compared against `scripts/backup.sh`,
  which handles the same question correctly and documents why.
- repro: on a deployment whose `.env` sets `QC_AGENT_POSTGRES_DB=nexusqc`,
  run `scripts/restore.sh <backup>` from a shell with no exported
  `QC_AGENT_*`. The prompt asks you to type `qc_agent`, and the restore runs
  against a database of that name.
- observed: two independent halves.
  (a) `scripts/restore.sh:63-64`

      PGUSER_VAL="${QC_AGENT_POSTGRES_USER:-qc_agent}"
      PGDB_VAL="${QC_AGENT_POSTGRES_DB:-qc_agent}"

  Environment only. `scripts/backup.sh:69-80,131-135` reads the same two
  values out of `.env` when the environment is empty, and the comment there
  spells out why ("cron and scripts/update.sh ... Neither exports .env").
  The backup's own `MANIFEST.txt` records `pg database:` / `pg user:`
  (`backup.sh:236-244`) and the restore reads neither.
  (b) `scripts/restore.sh:88-91`

      docker compose exec -T postgres pg_restore ... < "$DUMP" \
        || echo "(pg_restore reported errors -- review the output above; ...)"

  Every failure is absorbed into that one message, including
  "database ... does not exist", an authentication failure, or a restore
  that aborted half-way. The script then prints "Restore finished."
- expected: the two halves compose into the failure mode the file's own
  header warns about. A renamed database gives `pg_restore` a target that
  does not exist, the error is printed as expected noise, and the operator
  is told the restore finished — during an outage, which is the only time
  this script runs.
- evidence: `scripts/restore.sh:63,88,120`; `scripts/backup.sh:69-80`
- pointer: `--exit-on-error` is deliberately not set, and the reasoning
  given (DROP-on-missing-object noise from `--clean`) is sound. But
  "expected noise" and "the restore did not happen" are being conflated;
  they are distinguishable.
- note: fix direction — read `.env` for user/db exactly as `backup.sh` does
  (or read them out of `MANIFEST.txt`, which is more faithful to the dump),
  and verify afterwards rather than trusting the exit code: the script
  already prints a `SELECT count(*) FROM users;` for the operator to run by
  hand, so run it and compare against `pg_restore --list`'s table count.

### R-000: the new frontend bundle goes live before the new api exists, and a failure between the two leaves new JS talking to the old backend with no recovery advice
- surface: code:deploy
- class: bug
- severity: S3
- cause: CODE
- confidence: suspected (code read)
- found by: audit:deploy
- scope: `scripts/update.sh` rebuild sequence. The `--maintenance` case is
  much narrower (non-admins get a 503 through the window); the default CLI
  case, without `--maintenance`, is the exposed one. The admin panel always
  passes `--maintenance` (`deploy_runner.sh:194`).
- repro: run `scripts/update.sh` (no flags) on a commit that changes both the
  frontend and an api route's response shape, with a browser tab open.
  Between the bundle swap and the api coming back healthy — the build is
  already done, so this is the `compose up -d` plus up to 300 s of health
  wait — a reload serves the new SPA against the old api.
- observed: `scripts/update.sh:596-657` in order: `compose build` →
  `extract_frontend.sh` (which atomically flips `frontend/dist/index.html`,
  and nginx serves that directory through a bind mount, so the new bundle is
  live that instant) → `enter_maintenance` → `compose up -d` → health wait.
- expected: the reverse pairing is the one the project has already reasoned
  about and accepted. `check_destructive.sh:444-449` says of a frontend
  change: "Open tabs keep the old bundle until reloaded; no route was
  removed, so they keep working in the meantime" — old JS against a new api
  is tolerated by design. Nothing anywhere accepts new JS against an old api,
  and check 4 (`check_destructive.sh:433-442`) only screens for routes that
  *disappear*, never for routes whose shape changed.
- evidence: `scripts/update.sh:602` (`bash scripts/extract_frontend.sh
  "$TARGET_SHA"`), `scripts/update.sh:617` (`enter_maintenance`),
  `scripts/update.sh:619` (`compose up -d`); `scripts/extract_frontend.sh:100-133`
- pointer: the ordering comment at `update.sh:590-595` justifies building
  before installing the bundle, and building before `up -d`. Neither reason
  requires installing the bundle before `up -d`.
- note: a second, worse exit from the same window. `enter_maintenance` can
  `die` (`update.sh:477`, "could not enter maintenance mode -- refusing to
  restart without it") *after* the bundle has been swapped and before
  anything is recreated. `die` prints no `recovery_advice`, writes no
  `.update-log` entry, and leaves the deployment serving the new frontend
  against the old api permanently, with the checkout already moved. Fix
  direction: move the `extract_frontend.sh` call to after the health check
  passes (and re-run it as part of the failure path only if the api came
  back), or at minimum call `recovery_advice` from the `enter_maintenance`
  failure.

### R-000: after a documentation-only update, every later `update.sh` run takes a full backup and then does nothing, permanently
- surface: code:deploy
- class: perf
- severity: S3
- cause: CODE
- confidence: suspected (code read)
- found by: audit:deploy
- scope: `scripts/update.sh` up-to-date test and the `NEEDS_RESTART=0` fast
  path. Not measured on this host; the cost is whatever `tar -czf` over
  `data/jobs` + `data/kb` costs, which for a deployment with real CASSCF
  output is large.
- repro: update to a commit that only touches `docs/`. Then run
  `scripts/update.sh` again with no new commits upstream. It takes another
  full backup, prints "not restarting anything", and exits — and will do so
  on every subsequent run.
- observed: the docs-only path (`update.sh:568-581`) exits without rebuilding,
  so the api image's OCI stamp and `frontend/dist/.build-commit` both stay at
  the previous commit. On the next run `DEPLOYED_SHA != TARGET_SHA`, so the
  "already up to date" test at `update.sh:255-260` fails; `REBUILD_ONLY=1`;
  the unconditional `bash scripts/backup.sh --full` at `update.sh:399` runs;
  `check_destructive` reports the same docs-only diff; `NEEDS_RESTART=0`
  again; exit. The stamp can never catch up, because catching up requires a
  rebuild the same branch declines to do.
- expected: a run with nothing to do should reach `ok "already up to date --
  nothing to do."` and exit before the backup.
- evidence: `scripts/update.sh:346-352` (`RUNTIME_IRRELEVANT_RE` and
  `NEEDS_RESTART`), `scripts/update.sh:255-260`, `scripts/update.sh:399`
- pointer: the up-to-date test compares shas; the restart decision compares
  file paths. The two disagree about what "current" means.
- note: fix direction — in the up-to-date test, treat `DEPLOYED_SHA →
  TARGET_SHA` as current when the diff between them matches
  `RUNTIME_IRRELEVANT_RE` (the same computation, hoisted above the test), or
  write the stamp forward on the docs-only exit so the deployment records
  that it is serving that commit.

### R-000: `check_destructive.sh`'s vanishing-bind-mount check tests whether the override file exists, not whether it still declares the mounts the running container has
- surface: code:deploy
- class: bug
- severity: S3
- cause: CODE
- confidence: suspected (code read)
- found by: audit:deploy
- scope: check 10 (`check_destructive.sh:618-639`), which is one of the four
  classes the script's header claims to catch. The absent-file case is
  covered correctly.
- repro: with a running stack that has `/software:/software:ro` mounted, edit
  `docker-compose.override.yml` to remove the `volumes:` block (keeping the
  file, e.g. for its `ports:` override, which `install.sh:791-797` also
  writes into this file). Run `scripts/check_destructive.sh`. It reports
  `[ok] docker-compose.override.yml is present, so engine mounts survive a
  recreate`. The next recreate produces a PySCF-only stack.
- observed: `check_destructive.sh:625-638`

      if [ "$ENGINE_MOUNTED" -eq 1 ] && [ ! -f "${STACK_DIR}/docker-compose.override.yml" ]; then
          dest "..."
      elif [ -f "${STACK_DIR}/docker-compose.override.yml" ]; then
          ok "docker-compose.override.yml is present, so engine mounts survive a recreate"

- expected: the header's claim 4 is that "a deployment can be running happily
  with ORCA and BAGEL mounted while the file that mounts them no longer
  exists on disk". The file being *edited* rather than deleted produces the
  same silent PySCF-only stack, and on this host that file is also the ports
  override, so it is a file people edit.
- evidence: `check_destructive.sh:634-635`; `docker-compose.override.yml.example`;
  `scripts/install.sh:791-797`
- pointer: the live mount list is already in hand (`LIVE_MOUNTS`,
  `check_destructive.sh:622`). Comparing it against `docker compose config
  --format json`'s `services.api.volumes` would answer the real question.
- note: two smaller weaknesses in the same block. `STACK_DIR` is
  interpolated straight into a regex (`grep -vE "^${STACK_DIR}(/|$)"`), so a
  path containing regex metacharacters — this host's own
  `<repo>` contains `.` — matches more
  loosely than intended; and the whole check is skipped silently when
  `compose ps -q api` returns nothing.

### R-000: `check_destructive.sh` and `update.sh` both tell the operator that *pending* jobs will be killed by the restart; they are re-enqueued
- surface: code:deploy
- class: bug
- severity: S3
- cause: CODE
- confidence: suspected (code read)
- found by: audit:deploy
- scope: the in-flight count in `update.sh:354-384` and check 8 in
  `check_destructive.sh:509-552`, against
  `JobManager._reconcile_orphaned_jobs` in `app/chemistry/jobs/base.py:1068-1163`.
  Verified by reading the reconciliation, not by restarting a container.
- repro: queue a job that cannot be admitted yet (so its `status.json` says
  `pending` and `meta.json` has no `worker_pid`), then run
  `scripts/update.sh`. It refuses with "1 job(s) are running or pending, and
  they will be killed", pushing the operator to `--drain` (up to four hours)
  or `--force`.
- observed: both scripts count `status in ("running", "pending")` and then
  describe the whole set as lost. `check_destructive.sh:543` — `dest "jobs are
  in flight and WILL BE KILLED by the restart" ... "there is no resume"`.
  `update.sh:378` — `die "${INFLIGHT} job(s) are running or pending, and they
  will be killed."`
- expected: case 3 of `_reconcile_orphaned_jobs`
  (`app/chemistry/jobs/base.py:1101-1106,1155-1157`): "meta.json's worker_pid
  is unset -- this job was never admitted by the scheduler before the previous
  process died, so there is no worker to have lost, only a still-queued job.
  Re-enqueue it exactly as if freshly submitted". Only a job with a dead
  `worker_pid` and no result is marked failed. A pending job survives a
  restart intact.
- evidence: `scripts/update.sh:366` (`in ("running", "pending")`),
  `scripts/check_destructive.sh:530`, `app/chemistry/jobs/base.py:1155`
- pointer: the drain loop itself already gets this right — it waits only on
  `status == "running"` (`update.sh:533`). It is the two operator-facing
  messages that overstate.
- note: safe direction (nothing is lost), but it costs a real decision: an
  operator with only pending jobs is steered into a four-hour drain or an
  unnecessary `--force`. Fix direction: count and report the two states
  separately — "N running (will be killed), M pending (will be re-queued
  after the restart)".

### R-000: a fifth destructive class `check_destructive.sh` misses — a change to a service's image tag or a named volume in `docker-compose.yml`
- surface: code:deploy
- class: bug
- severity: S3
- cause: CODE
- confidence: suspected (code read)
- found by: audit:deploy
- scope: all ten checks in `check_destructive.sh` were read against the four
  classes its header claims. Claims 1 (in-flight jobs), 2 (silent no-op
  schema change) and 3 (new required `.env` variable) are genuinely
  implemented (checks 8, 3+9, 2 respectively); claim 4 is partial (previous
  finding). This is the gap I could not find a check for.
- repro: craft a commit that changes `postgres:16-alpine` to
  `postgres:17-alpine` in `docker-compose.yml` and run
  `scripts/check_destructive.sh --to <that commit>`. It reports one generic
  `[warn] docker-compose.yml changed -- containers will be recreated, not
  restarted` and no destructive finding, and `update.sh` proceeds without
  asking.
- observed: `check_destructive.sh:462-466` is the only check keyed on
  `docker-compose.yml`, and it warns about recreation in the abstract
  ("Diff the ports and volumes sections specifically" — advice to a human,
  not a check). Nothing compares image tags or volume names between the two
  commits.
- expected: two concrete silent failures live here.
  - A Postgres **major** version bump makes the existing `postgres-data`
    volume unreadable; the container exits at once with "database files are
    incompatible with server", after the old containers are gone. Recoverable
    only from the backup (which `update.sh` does take) plus a hand-run
    `pg_upgrade` or dump/restore cycle.
  - A **renamed named volume** (`postgres-data` → anything) starts an empty
    database. `app/auth/db.py`'s `CREATE TABLE IF NOT EXISTS` then populates
    it, the app comes up healthy, and it looks like a fresh install with zero
    accounts. The old volume still exists, so nothing is technically lost, but
    the deployment is silently serving an empty identity store — and per
    `docker-compose.yml`'s own header note, an empty `ownership_index` makes
    every job on disk unowned, which this app treats as readable by everyone.
    That is a security consequence, not only an availability one.
- evidence: `check_destructive.sh:462-466`; `docker-compose.yml` `image:`
  lines and the `volumes:` block at the end
- pointer: both are one `git show "$TO_SHA":docker-compose.yml` and a diff of
  `grep -E '^\s+image:|^  [a-z-]+:$'` away — the script already does exactly
  this shape of comparison for `${VAR:?}` in check 2 and for requirements
  pairs in check 1.
- note: image tags are currently pinned to a major (`postgres:16-alpine`,
  `redis:7-alpine`, `nginx:1.27-alpine`), so this is latent rather than live.
  Worth adding before anyone bumps one.

### R-000: `/api/health` proves only that uvicorn is answering, so `update.sh` can declare a deployment healthy when Postgres is unusable
- surface: code:deploy
- class: bug
- severity: S3
- cause: CODE
- confidence: suspected (code read)
- found by: audit:deploy
- scope: `server/main.py:150-152`, the compose healthcheck
  (`docker-compose.yml` api service), and `qc_wait_for_health`
  (`scripts/lib/common.sh`). Not checked: whether any startup path opens a
  Postgres connection eagerly — I could not find one; the pool looks lazy.
- repro: put a wrong password in `QC_AGENT_POSTGRES_PASSWORD` for the api's
  `QC_AGENT_DATABASE_URL` only (the postgres container's own healthcheck uses
  `pg_isready -U <user>` and does not authenticate). `update.sh` reports
  `ok "healthy at ..."`, nginx starts, and every login fails.
- observed: `server/main.py:150-152`

      @app.get("/api/health")
      def health():
          return {"status": "ok"}

  Nothing touches Postgres, Redis, the job manager, or the graph. The compose
  healthcheck urlopens exactly this route.
- expected: the health gate is what `update.sh` uses to decide whether to
  record a commit as good and rollback-able (`update.sh:656-686`), and what
  nginx's `depends_on: service_healthy` uses to decide whether to start
  serving. Both questions are "can this deployment serve requests", not "did
  the interpreter finish importing".
- evidence: `server/main.py:150`; `docker-compose.yml` api `healthcheck:`;
  `scripts/lib/common.sh` `qc_wait_for_health` (`curl .../api/health`)
- pointer: startup does check that `QC_AGENT_JWT_SECRET` and
  `QC_AGENT_REDIS_URL` are *set* (`server/main.py:126-141`) and refuses to
  start without them, so those two are partly covered by process liveness.
  Postgres reachability is not covered at all.
- note: deliberately cheap health endpoints are a reasonable design and
  `/api/health` must keep answering during maintenance, so do not just add a
  query to it. Fix direction: a separate `/api/ready` that does a `SELECT 1`
  through the pool, used by `qc_wait_for_health` and the compose healthcheck,
  with `/api/health` left as the liveness probe.

### R-000: `/deploy-status/` serves two fixed-name files, unauthenticated, that leak the host's absolute checkout path and the deployment's commit history
- surface: code:deploy
- class: security
- severity: S4
- cause: CODE
- confidence: suspected (code read)
- found by: audit:deploy
- scope: the nginx `location /deploy-status/` block and what
  `scripts/deploy_runner.sh` writes into `data/deploy/`. Reachability is
  limited to the CIDR allowlist (10/8, 172.16/12, tailnet 100.64/10,
  loopback) — but *any* client there, logged in or not, user or not.
- repro: `curl -k https://<host>:8443/deploy-status/runner.json` with no
  cookie. Then `curl -k https://<host>:8443/deploy-status/update-log.txt`.
- observed: `docker-compose.yml` bind-mounts `./data/deploy` into nginx and
  `nginx/nginx.conf:98-113` serves it with no auth, justified by the comment
  "nothing in here is secret (a state word, a step name, a commit sha)".
  What is actually in there:
  - `runner.json` — `{"alive_at": ..., "pid": ..., "repo":
    "/data/<user>/..."}` (`deploy_runner.sh:63-65`). Absolute host path and a
    host pid, at a fixed, guessable name.
  - `update-log.txt` — the whole `.update-log`, copied in deliberately
    (`deploy_runner.sh:223`). Fixed name.
  - `<id>/log.txt` — the entire stdout+stderr of `update.sh`, which on a
    failure includes `docker compose logs --tail 25 api`
    (`update.sh:664,670`), i.e. application log lines.
- expected: the comment's claim. `<id>/log.txt` is at least behind a
  128-bit-ish capability (`uuid.uuid4().hex[:12]`,
  `server/routes/admin.py:657`), and the block sets `autoindex off`, so the
  per-run files are not enumerable — but the two fixed names are not
  protected by anything.
- evidence: `nginx/nginx.conf:96-113`; `scripts/deploy_runner.sh:61-66,223`;
  `server/routes/admin.py:657`
- pointer: `/data/<user>/...` in an unauthenticated response is the exact
  class `scripts/check_public_safe.sh` exists to keep out of the repository,
  reintroduced at runtime.
- note: low impact on a CIDR-restricted intranet listener, and the whole
  point of the location is that it answers while auth is down, so this is a
  trade rather than a mistake. Cheapest fix: drop `repo` from `runner.json`
  (the browser only needs `alive_at`), and write `update-log.txt` under the
  per-run id directory rather than at the top level. Worth also confirming
  that nothing an operator would consider sensitive reaches `log.txt` — the
  `compose logs api` tail is the part I would look at first.

### R-000: `update.sh`'s destructive-change confirmation uses a bare `read`, which under `set -e` exits silently at EOF — the exact class the installer audit removed from `install.sh`
- surface: code:deploy
- class: comfort
- severity: S4
- cause: CODE
- confidence: suspected (code read)
- found by: audit:deploy
- scope: `scripts/update.sh:335-337` and `scripts/restore.sh:81,100`. The
  admin-panel path always passes `--yes`, so this only bites a human running
  the script with stdin closed, redirected, or from a non-interactive
  wrapper.
- repro: `scripts/update.sh < /dev/null` on a commit the report calls
  destructive. The script exits 1 at the prompt having printed the question
  and nothing else.
- observed: `scripts/update.sh:335-337`

      printf 'Type UPDATE to go ahead anyway: '
      read -r reply
      [ "$reply" = "UPDATE" ] || die "aborted -- nothing was touched."

  `read` returns non-zero at end of input and `set -euo pipefail` is in force,
  so the `die` message never prints.
- expected: `scripts/lib/common.sh` — which `update.sh` already sources —
  carries `ask()` and `ask_yn()`, written for exactly this ("A bare `read`
  returns non-zero at end of input, and under `set -e` that exits
  mid-question with nothing printed at all -- which is what Ctrl-D, a closed
  terminal, or a pipe that ran out used to do to install.sh").
- evidence: `scripts/update.sh:336`; `scripts/lib/common.sh` `ask()`
  docstring; `scripts/restore.sh:81`
- pointer: the fix landed in `install.sh` and in the shared library, but
  `update.sh`'s one prompt was not converted to use it.
- note: harmless in outcome (nothing has been changed at that point) but
  silent, and `restore.sh`'s two prompts have the same shape at a much worse
  moment — mid-outage, at "Type the database name to proceed".

### R-000: almost every Python dependency is unpinned, so two installs a month apart get different langchain/langgraph
- surface: code:deploy
- class: bug
- severity: S3
- cause: CODE
- confidence: suspected (code read)
- found by: audit:deploy
- scope: `requirements.txt` as a whole. I did not attempt to determine
  whether any currently-resolvable version actually breaks the app.
- repro: `grep -vE '^#|^$' requirements.txt | grep -vc '=='` → 33 unpinned
  lines against 2 pinned (`pyscf==2.14.0`, `pyscf-forge==1.1.1`). `pip
  download -r requirements.txt` on two dates and compare.
- observed: `langgraph`, `langchain`, `langchain-openai`, `langchain-ollama`,
  `langchain-chroma`, `langchain-community`, `langchain-text-splitters`,
  `chromadb`, `fastapi`, `uvicorn[standard]`, `numpy`, `scipy`, `rdkit`,
  `ase` and the rest carry no specifier at all.
- expected: the file itself argues for pinning where it matters, and the
  argument generalises: "The point of the pin is that a fresh install works
  first time" (`requirements.txt`, above `pyscf==2.14.0`).
  `check_destructive.sh:268-271` treats a newly added unpinned package as
  worth calling out — "(new, UNPINNED -- resolves to whatever is latest at
  build time)" — so the tooling already regards this as a hazard. The
  langchain/langgraph family in particular makes breaking changes across
  minors, and it sits directly under the agent loop.
- evidence: `requirements.txt:3-35,83`; `check_destructive.sh:270`
- pointer: `Dockerfile` runs a plain `pip install --no-cache-dir -r
  requirements.txt` with no constraints file, so the image is whatever PyPI
  serves the day it is built.
- note: this may be a deliberate standing choice — the two pins carry long
  justifications and one nearby package is explicitly marked "Deliberately
  NOT pinned" — so treat this as a question rather than a defect if so. What
  would settle it: `pip freeze` inside the current working image versus a
  rebuild today. Fix direction that keeps the freedom: commit a
  `requirements.lock` produced by `pip freeze` from a verified image and have
  the Dockerfile install from that, leaving `requirements.txt` as the
  human-edited input.

### R-000: `nginx/nginx.conf`'s header describes a public listener and a kill-switch script that were both deleted
- surface: code:deploy
- class: docs
- severity: S4
- cause: CODE
- confidence: suspected (code read)
- found by: audit:deploy
- scope: `nginx/nginx.conf` comments only; the directives are correct.
- repro: `ls scripts/toggle_public_access.sh` → does not exist.
- observed: `nginx/nginx.conf:3-9` — "Two listeners, one config, per the
  deployment plan: an always-on campus intranet listener ... and a public
  listener that a host sysadmin can cut off independent of application health
  (see scripts/toggle_public_access.sh -- that's the REAL kill switch; the
  app-level admin toggle below is the fast, graceful one)". Lines 11-14 then
  tell the reader to "Replace <intranet-hostname>/<public-hostname> and the
  campus CIDR below", neither of which appears in the file. Lines 148-160 say
  the public listener, the admin toggle and that script were all removed on
  2026-08-25.
- expected: the top of the file should not contradict the bottom of the same
  file. A reader reaches for a script that is not there, and looks for a
  hostname placeholder that does not exist.
- evidence: `nginx/nginx.conf:3-14` vs `nginx/nginx.conf:148-160`
- pointer: the removal edited the block it deleted and not the header above
  it.
- note: also worth a line in the same pass — `docs/DEPLOYMENT.md` should be
  checked for the same stale reference (I have flagged the DEPLOYMENT.md
  claims for the live walkthrough in `doc-claims.md`).

### R-000: `check_destructive.sh`'s disappearing-route check cannot see a router prefix, so a renamed prefix reads as "no routes removed"
- surface: code:deploy
- class: bug
- severity: S4
- cause: CODE
- confidence: suspected (code read)
- found by: audit:deploy
- scope: check 4 (`check_destructive.sh:433-450`) only.
- repro: change `APIRouter(prefix="/api/jobs")` to `prefix="/api/job"` in
  `server/routes/jobs.py`, leaving every decorator untouched. Run
  `check_destructive.sh` across that commit: every route path it extracts is
  unchanged, so it reports the benign `[warn]` branch rather than
  `[destructive] API routes disappear while old frontend assets are still in
  browsers`.
- observed: `check_destructive.sh:434`

      git grep -h -E '@(app|router)\.(get|post|put|patch|delete)\(' "$FROM_SHA" -- server \
        | sed -E 's/.*\("([^"]*)".*/\1/' | sort -u

  Only the decorator's own literal is captured. It also misses any path
  written with single quotes or built from an f-string, and any decorator
  whose path is not on the same line.
- expected: the check exists to catch "a tab open across the update keeps its
  already-loaded JS and will call these until it is reloaded", and a prefix
  rename breaks exactly that, for every route on the router at once — the
  largest instance of the thing being checked for.
- evidence: `check_destructive.sh:434-436`; the `prefix=` arguments in
  `server/routes/*.py`
- pointer: a false negative, not a false positive, so it fails quietly.
- note: cheap improvement — also diff the `APIRouter(prefix=...)` literals per
  file and report a changed prefix as removing every route under it. Or
  extract routes from the running app's `/openapi.json` for the FROM side.

### R-000: `update.sh` traps only EXIT, so a Ctrl-C during the drain can leave job admission paused — and maintenance mode on — with nothing scheduled to undo it
- surface: code:deploy
- class: bug
- severity: S2
- cause: CODE
- confidence: suspected (code read) — the bash behaviour is asserted
  empirically by this repository's own installer audit
- found by: audit:deploy
- scope: `scripts/update.sh`'s EXIT trap and the two flags it exists to clear.
  `scripts/install.sh` has the fix; `update.sh` did not get it.
- repro: `scripts/update.sh --drain` with a job running, then Ctrl-C at the
  "waiting for N in-flight job(s)" line. Then check
  `select * from app_config where key='job_admission_paused'`.
- observed: `scripts/update.sh:504`

      trap 'leave_maintenance; restore_admission' EXIT

  and nothing for INT or TERM. The drain then prints, at
  `scripts/update.sh:519`, `info "waiting for ${INFLIGHT} in-flight job(s);
  Ctrl-C is safe, admission is restored on exit"`.
- expected: commit `4faa632` ("Trap the interrupt, and stop the override diff
  being a date change", 2026-09-10) fixed exactly this in `install.sh`, and its
  message records the behaviour as observed rather than reasoned: "The
  installer trapped only EXIT, and bash does not reliably run an EXIT trap when
  it is killed by a signal it does not handle -- it re-raises and dies -- so
  the one message the trap exists to print was exactly the one that never
  appeared." `install.sh` now carries `trap 'on_signal 2' INT` and
  `trap 'on_signal 15' TERM` alongside its EXIT trap.
- evidence: `scripts/update.sh:504,519`; `scripts/install.sh` `on_signal()` and
  its three traps; `git show 4faa632`
- pointer: in `install.sh` the consequence was a missing message. Here it is
  persistent state in the database. `job_admission_paused` left set means every
  new job queues as `pending` forever, and the script's own comment
  (`update.sh:508-513`) explains that this flag was chosen specifically because
  it is *not* the admin-facing concurrency setting — so there is no console
  control to notice or clear it. With `--maintenance` the same interrupt can
  leave `maintenance_mode` set, which 503s every non-admin.
- note: the drain is the most likely thing anyone ever interrupts, because it
  can wait four hours by default, and the script explicitly tells them it is
  safe to do so. Fix: give `update.sh` the same INT/TERM handlers, ideally by
  moving `install.sh`'s `on_signal` into `scripts/lib/common.sh`, which both
  already source. What would settle the bash question either way:
  `bash -c 'trap "echo TRAP" EXIT; sleep 30' &` then `kill -INT %1`.

### R-000: `backup.sh`'s retention pass deletes *any* subdirectory of `QC_AGENT_BACKUP_DIR` older than the retention window, not only its own backups
- surface: code:deploy
- class: bug
- severity: S2
- cause: CODE
- confidence: suspected (code read)
- found by: audit:deploy
- scope: the retention block at the end of `scripts/backup.sh`. Not run.
- repro: `mkdir -p "$QC_AGENT_BACKUP_DIR/someone-elses-archive"`, set its mtime
  to 40 days ago, run `scripts/backup.sh`. The directory is gone.
- observed: `scripts/backup.sh:248`

      pruned="$(find "$BACKUP_ROOT" -mindepth 1 -maxdepth 1 -type d -mtime "+${RETAIN_DAYS}" -print -exec rm -rf {} + 2>/dev/null | wc -l)"

  No name filter, no check that the directory is one of this script's own
  (which are named `YYYYmmdd-HHMMSS` and always contain `MANIFEST.txt`).
- expected: `docs/DEPLOYMENT.md:562` tells the operator to "Point
  `QC_AGENT_BACKUP_DIR` at a filesystem with real room (not wherever
  `/var/lib/docker` sits)", which invites pointing it at a general-purpose
  archive location rather than a directory this script owns. On this host
  `CLAUDE.local.md` records it pointing at a sibling directory
  (`NexusQC-dev-data-backup`). Anything else parked there and untouched for
  `QC_AGENT_BACKUP_RETAIN_DAYS` is deleted, from cron, nightly.
- evidence: `scripts/backup.sh:248`; `docs/DEPLOYMENT.md:562-564`;
  `CLAUDE.local.md` ("this checkout's `.env` does point `QC_AGENT_BACKUP_DIR`
  at `NexusQC-dev-data-backup`")
- pointer: the same block's sibling, `chmod 700 "$BACKUP_ROOT"`
  (`scripts/backup.sh:120`), silently re-locks the whole directory on every
  run, which is the other half of "this script assumes it owns that path".
- note: this is the standing never-blind-purge rule in a script that runs
  unattended. Fix: constrain the find with
  `-name '[0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9]-[0-9]*'`, or require
  `MANIFEST.txt` inside the candidate before removing it. Cheap either way,
  and it also makes the printed `pruned` count honest.

### R-000: `--full` archives `data/jobs` while jobs are writing into it, and `update.sh` takes that backup *before* the drain — so the drained-update path aborts exactly when it is needed
- surface: code:deploy
- class: bug
- severity: S2
- cause: CODE
- confidence: suspected (code read)
- found by: audit:deploy
- scope: `scripts/backup.sh`'s `--full` tar and its one automated caller,
  `scripts/update.sh:399`. Not reproduced; GNU tar's exit status is the load-
  bearing assumption.
- repro: with a job actively writing output, run `scripts/backup.sh --full`.
  GNU `tar -czf` prints "file changed as we read it" and exits 1.
- observed: `scripts/backup.sh:214` runs

      tar -C "$REPO_ROOT" -czf "${DEST}/full_data.tar.gz" "${EXISTING_DIRS[@]}"

  bare, under `set -euo pipefail`, with `data/jobs` in `EXISTING_DIRS`. A
  non-zero tar aborts the script. `scripts/update.sh` then reaches

      die "backup failed -- refusing to update without one."

  at line 405.
- expected: the ordering makes this worst in the one case it matters. In
  `update.sh` the backup is at line 399 and the drain does not start until line
  506, so `--drain` — which a person only passes *because* jobs are running —
  tars a live `data/jobs` every time. The tracker's end-to-end run
  (`docs/TRACKER.md`, the installer audit) was against a scratch deployment,
  where there was nothing in flight to trip it.
- evidence: `scripts/backup.sh:212-227`; `scripts/update.sh:393-407`;
  `scripts/update.sh:506`
- pointer: GNU tar's exit 1 means "some files differ", which for a running job
  is expected rather than a corrupt archive — and the script already has a
  real integrity check immediately after (`tar -tzf`), so the exit status is
  not carrying the weight it appears to.
- note: two independent fixes, and both are worth having. Move the `--full`
  backup after the drain in `update.sh` (it is also faster once nothing is
  writing), and treat tar exit 1 as a warning in `backup.sh` while keeping
  exit ≥ 2 fatal and keeping the `tar -tzf` verification as the real gate.
  What would settle it: run `scripts/backup.sh --full` on a scratch stack with
  one job writing.

### R-000: `docs/CONFIGURATION.md`'s job-parameter tables document four parameters and two task subtypes that no longer exist, and the in-app help still offers AVAS
- surface: code:deploy
- class: docs
- severity: S3
- cause: CODE
- confidence: suspected (code read) — confirmed by importing the registry
- found by: audit:deploy
- scope: `docs/CONFIGURATION.md`'s "Job parameter defaults" section and
  `frontend/src/app-shell/HelpFlyout.tsx:169-172`, against
  `app/chemistry/registry2/params.py` and `registry2/tasks.py`.
- repro: `PYTHONPATH=$PWD python3 -c "from app.chemistry.registry2.params
  import PARAMS, RETIRED_PARAMS; print(sorted(RETIRED_PARAMS))"` and
  `... from app.chemistry.registry2 import TASKS; print(sorted(TASKS))`.
- observed: `RETIRED_PARAMS` contains `orbital_indices`, `isoval`,
  `entropy_method`, `dmrg_bond_dim`, `max_active_orbitals`, `avas_aolabels`,
  `entropy_pilot_states`, `active_occupied_orbitals`, with the comment
  "Retired with the active-space rebuild. The entropy pilot, its DMRG variant
  and its state averaging are gone; **there is no ceiling to set**". `TASKS`
  has `('cas_reco','')` and `('cas_reco','refine')` — no `explain`, no
  `autocas`, no `avas`. Against that, `docs/CONFIGURATION.md` still says:
  - line 145: "`cas_reco` (subtypes `explain`/`autocas`/`avas`)"
  - line 166: a default for `cas_reco/autocas` → `entropy_method` `exact_fci`,
    "`dmrg` is the opt-in alternative"
  - line 167: a default for `cas_reco/autocas`, `cas_reco/avas` →
    `max_active_orbitals` `12`, "can only narrow it, never widen past 12"
  - line 168: `single_point` → `isoval` `0.04`, "only shown once
    `orbital_indices` is actually set"
  - lines 146-148: "Rendering molecular orbitals … It's now just the
    `orbital_indices` parameter on an ordinary `single_point`"

  and `HelpFlyout.tsx:170-171` tells users the active-space job "analyses the
  orbitals (entanglement-based, or AVAS)".
- expected: the section opens by asserting exactly the property it has lost —
  "Every default below lives in `app/chemistry/registry2/params.py`'s `PARAMS`
  tuple … This table is a transcription of it, not separate policy"
  (`CONFIGURATION.md:133-137`). It also settles the README contradiction filed
  above: README:449-453's "There is no size limit" is the correct account and
  `max_active_orbitals` is the stale one.
- evidence: `app/chemistry/registry2/params.py:295-306`;
  `app/chemistry/registry2/tasks.py` (`TASKS` keys);
  `docs/CONFIGURATION.md:141-148,166-168`;
  `frontend/src/app-shell/HelpFlyout.tsx:170`
- pointer: the CAS engine rebuild deleted the parameters and the subtypes and
  did not reach the configuration reference or the in-app tutorial — the
  "audit every surface a method touches" case, one rebuild later.
- note: the same section omits `opt/min`, `geometry_set`, `pes_1d/ee` and
  `interp_pes/ee`, all of which are real task keys. Since the tables claim to
  be a transcription, the durable fix is to generate them the way
  `docs/QM_CAPABILITIES.md` is generated, and add a drift check beside
  `scripts/check_capability_matrix.py`. AVAS in the tutorial is the row a user
  is most likely to act on: they will ask for an AVAS active space and get
  something else.

### R-000: the in-app welcome screen's capability table is a hand-written duplicate of engine routing and disagrees with the registry in four places
- surface: code:deploy
- class: docs
- severity: S3
- cause: CODE
- confidence: suspected (code read) — the registry side is confirmed by importing it
- found by: audit:deploy
- scope: `frontend/src/chat/WelcomeMessage.tsx`'s `ROWS` array, checked cell by
  cell against `app/chemistry/registry2` via `engines_supporting()` and
  `CAPABILITIES`. Not checked in a browser.
- repro: open a new conversation, expand "What can it run?", then ask for the
  calculation each disputed cell describes.
- observed: four cells, verified against the registry by import:

      { calc: "Geometry optimisation", ..., bagel: "CASSCF/CASPT2 only" }   # line 14
      { calc: "Frequencies / thermochemistry", ..., bagel: "numerical, HF only" }  # line 15
      { calc: "CASSCF (incl. state-averaged)", orca: "yes, + oscillator strengths", bagel: "yes" }  # line 16
      { calc: "Potential-energy scan", pyscf: "default*", orca: "yes*", bagel: "yes*" }  # line 21

  `engines_supporting('hf','opt','min')` → `('pyscf','orca','bagel')`;
  `engines_supporting('hf','freq','')` and `('casscf','freq','')` → both include
  `bagel`; `engines_supporting('casscf','pes_1d','')` → `('pyscf','orca')`, i.e.
  **BAGEL cannot scan at all**; and
  `CAPABILITIES[('bagel','casscf')].osc_strengths` is `True`.
- expected: the scan row is the one that misleads in the dangerous direction —
  it tells a new user, on the first screen they see, that an engine supports
  something the app will refuse. The other three understate BAGEL. README's own
  matrix (lines 71, 76, 79) agrees with the registry in all four places, so it
  is only this table that is wrong. The oscillator-strengths cell also
  contradicts README:144-147 ("A CASSCF job that needs oscillator strengths
  also goes to BAGEL, which is the preferred engine for those on this
  deployment").
- evidence: `frontend/src/chat/WelcomeMessage.tsx:9-25`, whose own comment
  says "Mirrors app/chemistry/jobs/registry.py's ALLOWED_ENGINES/DEFAULT_ENGINE
  -- kept as a small hand-written table here rather than fetched from the
  backend since it's static per-deployment reference info"
- pointer: the comment names `app/chemistry/jobs/registry.py`, but routing now
  lives in `app/chemistry/registry2/`. The table was mirrored from a module
  that has since been replaced, and nothing checks it.
- note: `CLAUDE.md` makes the registry the single source of truth and says
  logic duplicated elsewhere is a finding. There is already a route that serves
  this data (`server/routes/registry.py`: "a complete map of every calculation
  this deployment can" run), so the table could be fetched instead of
  transcribed — which would also make it honest on a PySCF-only deployment,
  where it currently claims ORCA and BAGEL rows regardless.

### R-000: `docs/DEPLOYMENT.md`'s by-hand admin bootstrap command is missing two required arguments and cannot run
- surface: code:deploy
- class: docs
- severity: S2
- cause: CODE
- confidence: suspected (code read)
- found by: audit:deploy
- scope: `docs/DEPLOYMENT.md` step 7 and the lockout-recovery section that
  refers back to it. `scripts/install.sh` gets it right.
- repro: `docker compose run --rm api python -m server.admin_cli bootstrap-admin
  --email you@yourlab.edu --username admin` → argparse exits 2 with "the
  following arguments are required: --first-name, --last-name".
- observed: `docs/DEPLOYMENT.md:344-347` gives exactly that command;
  `server/admin_cli.py:146-151` declares `--email`, `--username`,
  `--first-name` and `--last-name` all `required=True`.
- expected: step 7 is the last step of the documented by-hand install and the
  second half of lockout recovery (`DEPLOYMENT.md:420`, "Then bootstrap a fresh
  admin, as in step 7"). Someone reaching for it is either standing up a
  deployment or locked out of one. `scripts/install.sh:957-959` passes all four
  flags plus `--password-stdin`.
- evidence: `docs/DEPLOYMENT.md:345`; `server/admin_cli.py:149-150`;
  `scripts/install.sh:957-959`
- pointer: the first/last-name arguments were added to the CLI and the
  installer, and the hand-run documentation was not updated with them.
- note: the doc also says "It prompts for a password", which is worth
  confirming at the same time — the installer uses `--password-stdin` instead,
  so the interactive prompt path may be the less-exercised one.

### R-000: several `docs/DEPLOYMENT.md` commands cannot run as printed, and two rows of its status table describe removed features
- surface: code:deploy
- class: docs
- severity: S3
- cause: CODE
- confidence: suspected (code read)
- found by: audit:deploy
- scope: `docs/DEPLOYMENT.md` only. Four separate problems, grouped because
  they are one editing pass.
- repro / observed:
  1. **The nightly cron line writes into a directory that does not exist.**
     `DEPLOYMENT.md:566-568` gives
     `0 3 * * * cd /path/to/NexusQC && ./scripts/backup.sh >> backups/backup.log 2>&1`,
     two lines after telling the operator to point `QC_AGENT_BACKUP_DIR`
     somewhere with real room. `backups/` is only created by `backup.sh` when
     that variable is *unset*, so on the recommended configuration the shell
     cannot open the redirect and the job fails before the script starts —
     silently, nightly. Even with the variable unset the *first* run fails,
     because the shell opens the redirect before the script gets to `mkdir`.
     Confirmed on this host: `backups/` does not exist.
  2. **Every `curl` example omits `-k`.** `DEPLOYMENT.md:385-406` gives five
     admin examples against `https://<host>`, on a deployment whose own step 3
     generates a self-signed certificate and whose step 8 tells you to accept
     the browser warning. As printed each fails certificate verification.
  3. **A pointer to a file that does not exist.** `DEPLOYMENT.md:191` tells the
     reader to see "`docker-compose.dev.yml`'s `ports: !override` for the
     pattern". That file was removed with the dev/production split.
  4. **Two stale status rows.** `DEPLOYMENT.md:712-713` still lists "Public
     nginx listener | Not verified end to end. Commented out by default" and
     "Host-level kill switch | Implemented for `iptables`; not yet run against
     a real firewall". Both were removed on 2026-08-25, which the same document
     says at lines 474-480.
- expected: a deployment guide's commands should run as printed; its status
  table should not contradict its own body.
- evidence: `docs/DEPLOYMENT.md:567`, `:385-406`, `:191`, `:712-713`;
  `scripts/backup.sh:83-85`; `.gitignore:63`
- pointer: (1) and (2) are the two that cost real time — a backup everyone
  believes is running and is not, and a support recipe that fails on its first
  line.
- note: `scripts/toggle_public_access.sh` is referenced in the same removed-
  feature family from `nginx/nginx.conf:6`, filed separately above.

### R-000: README and CONFIGURATION.md contradict each other on whether the active-space recommendation has a size limit
- surface: code:deploy
- class: docs
- severity: S3
- cause: CODE
- confidence: suspected (code read)
- found by: audit:deploy
- scope: the two documents; I did not trace which one the code implements.
- repro: ask for a recommendation on a molecule whose valence space exceeds
  twelve orbitals and see which document describes what happens.
- observed: `README.md:449-453` — "*There is no size limit.* The previous
  version refused anything above twelve orbitals ... This one does not run that
  CASSCF. A large space is reported with its determinant and CSF counts and
  which engines can actually reach it, and you decide."
  `docs/CONFIGURATION.md:167` — `cas_reco/autocas`, `cas_reco/avas` →
  `max_active_orbitals` default `12`, "Ceiling on the recommended space; can
  only narrow it, never widen past 12".
- expected: these can both be true only if `max_active_orbitals` bounds
  something other than what README calls "the recommended space", and neither
  document says so. As written, a user reads README, asks for a large space,
  and gets twelve orbitals.
- evidence: `README.md:449-453`; `docs/CONFIGURATION.md:167`
- pointer: the twelve-orbital ceiling is exactly the limit README says was
  removed, so this reads like a parameter default that outlived its rationale.
- note: a second, smaller contradiction in the same family, also worth one
  edit: `README.md:869-871` says user and invite management, suspensions,
  deletions and bug-report triage all happen in the admin console, while
  `docs/DEPLOYMENT.md:381-382` and `:708` say user/invite management and the
  bug inbox are not in it yet and go through the API directly.

---

## Checked and clean

Recorded because "no finding here" is a result.

- **shellcheck.** `docker run --rm -v "$PWD:/mnt" koalaman/shellcheck:stable
  -x scripts/update.sh scripts/backup.sh scripts/restore.sh
  scripts/lib/common.sh scripts/check_destructive.sh
  scripts/extract_frontend.sh scripts/deploy_runner.sh` — **`update.sh` is
  clean at every severity, including info and style.** No unquoted expansion,
  no unguarded `cd`, no `rm -rf $VAR`. The only hits anywhere are three
  cosmetic ones: SC2043 on `for f in data/threads.json` (`backup.sh:195`) and
  `for f in docker-compose.yml` (`check_destructive.sh:312`), both
  single-element loops left deliberately extensible, and SC1010 four times in
  `deploy_runner.sh` where `done` is a legitimate string argument to
  `write_status`, not a keyword.
- **`set -e` interaction review**, done by hand on top of shellcheck, looking
  specifically for the class that broke `install.sh` (a function whose last
  command is a test). `ask()` in `common.sh` carries the fix and explains it;
  no other function in `update.sh`, `backup.sh`, `restore.sh` or
  `common.sh` ends on a bare test. The `[ "$pruned" -gt 0 ] && log ...` and
  `[ -f ... ] && { ...; }` forms in `backup.sh` are `&&`-list-exempt and safe.
  `HEALTHY=0; qc_wait_for_health ... && HEALTHY=1 || HEALTH_RC=$?` captures
  the right status.
- **Interrupt handling: partly clean, and one finding.** The EXIT trap itself
  is correctly built — registered before either flag can be set
  (`update.sh:504`), both handlers idempotent and guarded by their own state
  variable, and the drain's timeout path calls `restore_admission` explicitly
  before dying. What is missing is INT/TERM, which this repository established
  empirically in `4faa632` that bash does not reliably cover through EXIT.
  Filed above; I had this entry down as clean until that commit corrected me.
- **nginx and SSE.** `proxy_buffering off`, `proxy_read_timeout 3600s`,
  `proxy_http_version 1.1`, `proxy_set_header Connection ""` and
  `chunked_transfer_encoding on` (`nginx/proxy_common.conf`) are all correct
  for a long-lived event stream, and are applied to all of `/api/` rather
  than only the events path. `proxy_set_header Host $http_host` (not `$host`)
  is required by `AccessControlMiddleware`'s origin reconstruction on a
  non-default port, and the file explains the empirical finding behind it.
- **Upload limits.** `client_max_body_size 512m` on the intranet listener is
  above every application-side cap I could find (bug-report attachments are
  5 MB each, max 3 per report, `server/routes/bugs.py:22-23`; KB ingestion is
  bounded by the per-user storage quota rather than a request size). So the
  app's own limit is always the one that fires, which is what the comment at
  `nginx/nginx.conf:85-89` intends. No 413-before-the-app path found.
- **TLS.** TLS 1.2/1.3 only, AEAD-only cipher list, session tickets off,
  short HSTS max-age with the reasoning for keeping it short while the
  certificate is self-signed, no `includeSubDomains`/`preload`. Security
  headers are re-included inside the nested `/assets/` and `= /index.html`
  locations, which is required by nginx's `add_header` inheritance rule and
  is correctly commented as load-bearing.
- **Redis is correctly absent from the backup.** Its only uses are session
  records (`app/auth/redis_session.py`), the per-IP login rate limiter
  (`app/auth/rate_limit.py`) and dependency plumbing — all reconstructible,
  and losing them logs everyone out rather than losing data. The
  `redis-data` volume exists but nothing durable is written to it.
- **`backup.sh`'s Postgres half is sound.** It reads `.env` (with the reason
  documented), refuses to write an empty dump when the stack is down, uses
  `-Fc --clean --if-exists`, and — unusually and correctly — *verifies* both
  the dump (`pg_restore --list`) and the `--full` tar (`tar -tzf`) before
  declaring success, keeping the directory for inspection on failure.
  `chmod 700` on the destination and `chmod -R go-rwx` afterwards are right
  for a shared host, and the `.env`/certs/`.update-log` copy list is
  well-chosen (the reasoning about `docker-compose.override.yml` being the
  only thing that mounts the engines is exactly right).
- **`extract_frontend.sh`.** The in-place, index.html-last replacement order
  is correct and the comment explaining why `mv`-based staging breaks a live
  bind mount is accurate. It validates the extracted bundle
  (`index.html` + `assets/index-*.js`) before installing it, never touches
  `frontend/dist` on a failure path, and warns when the installed stamp
  disagrees with HEAD — the fix for the 2026-09-09 stale-bundle incident.
- **`.dockerignore`** excludes `.git`, `data`, both `node_modules` trees,
  `.env`/`.env.*`, `nginx/certs`, `docker-compose.override.yml`,
  `CLAUDE.local.md` and `tests/.admin_creds`. The Dockerfile uses targeted
  `COPY`s only, so no secret reaches the image, and the build context cannot
  clobber the image's own `npm ci` output.
- **Container user and ownership.** Non-root `app` user built from
  `APP_UID`/`APP_GID` build args, `chown -R` before `USER app`, base image
  pinned to `python:3.11-slim-bookworm` (with the OpenMPI-4 reasoning), the
  api healthcheck deliberately using `python` rather than a curl the image
  does not have. `restart: unless-stopped` and per-service log rotation
  (10 MB × 5) are set on every service.
- **`check_destructive.sh` claims 1-3 really are implemented**: in-flight jobs
  (check 8, reading every `status.json` including sub-jobs), the silent no-op
  schema change (check 3 parses `_SCHEMA` at both commits and, better, check
  9 compares against `information_schema.columns` on the live database, with
  the new-table false positive correctly excluded), and a newly required
  `.env` variable (check 2, matching `${VAR:?}` and testing it against the
  deployment's own `.env`). Its `--json` path emits the same recorded
  findings as the prose rather than a second implementation.
- **`deploy_runner.sh`'s trust boundary.** The action is checked against a
  fixed set, the id is validated before becoming a path segment, the ref is
  resolved to a sha and required to be an ancestor or descendant of
  `origin/main`, and nothing from the request reaches a shell. The
  api-writes-a-file design avoids handing the container a docker socket, and
  `server/routes/admin.py:620` gates the request behind `require_admin`.
- **No `async def` route handlers, api never scaled beyond 1.** The only
  `async def` under `server/` is the FastAPI `lifespan` at `server/main.py:52`,
  which is correct; every route handler is a plain `def`, and three route
  modules carry the reasoning in their own docstrings. `docker-compose.yml`
  declares no `deploy.replicas` and says at the top why it must not.
- **Compose sets no resource limits at all**, which is worth stating plainly
  rather than as "nothing misused": no `mem_limit`, no `cpus`, no
  `pids_limit` on any of the four services. The substitute is `JobManager`'s
  host-wide admission gate (`QC_AGENT_MAX_CPU_PERCENT` /
  `MAX_MEM_PERCENT` / `CORE_IDLE_THRESHOLD_PERCENT`) plus
  `QC_AGENT_MAX_MEMORY_MB` per job. On a machine deliberately shared with
  other tenants that is the documented choice (`CLAUDE.local.md`,
  `docs/CONFIGURATION.md:73-90`), not an omission — a container-level cap
  would fight the gate rather than help it. Recorded so a reader knows there
  are none.
- **`.update-log` and `frontend/dist/` are both gitignored**
  (`.gitignore:57`, `frontend/.gitignore:11`), so neither the rollback log nor
  the installed bundle can dirty the tree and trip `update.sh:116`'s clean-tree
  gate on the next run. This is load-bearing and easy to break.
