# Tracker: one-command install, and an in-app update path

<!-- artifact: https://claude.ai/code/artifact/f1ea9c70-7775-440f-96a3-db9141c683a5 -->

**Closed 2026-09-09, opened 2026-09-08.** Four phases, all merged. Makes installing NexusQC a
single `curl ... | sh`, moves the frontend bundle out of the api image instead
of building it twice, and puts a real update path in the admin panel.

Moved here from `docs/TRACKER.md` on 2026-09-09 when the next plan started.
**Exactly one tracker is active at a time.** The one this replaced is
[`2026-09-cas-closeout-and-suite-audit.md`](2026-09-cas-closeout-and-suite-audit.md),
and the one that replaced it is the UI redesign in `docs/TRACKER.md`.

## Rules (enforced by `scripts/check_tracker.py`)

- Step status is exactly one of `todo` | `in-progress` | `done`.
- A step may be marked `done` **only with an evidence field**: the
  verification script/command path plus a one-line observed result.
- The tracker edit ships **in the same commit** as the step's final code
  change, so `git log --follow docs/TRACKER.md` is the audit trail.
- A phase's `merged` row records the commit hash the stage landed as.

Format for a step row:

```
- [status] P<phase>.<step>: <short name>
  evidence: <script/command> → "<observed result>"   (required when done)
```

---

## Why this plan exists

**Installing** takes three steps a person has to get right in order: clone,
`cd`, run the installer. The one-liner other projects offer cannot work here as
things stand, for three independent reasons. `scripts/install.sh` finds itself
through `${BASH_SOURCE[0]}`, which names nothing when the script arrives on
stdin. Every prompt is a bare `read` against the stdin that *is* the script, so
the first question would swallow the rest of the installer. And
`set -euo pipefail` is a bashism that dash, which is `/bin/sh` on every
Debian-family machine, refuses before it reaches line two.

**Updating** is a host shell command. An admin inside the app cannot see that
an update exists, what it would break, who is halfway through a calculation, or
apply it. `scripts/update.sh` already does the hard parts well -- a mandatory
backup, the destructive report, draining, rollback, and the two build stamps --
and none of it is reachable from the admin panel.

The constraint that shapes the second half: the api container's only bind mount
is `./data`. It has no `.git`, no docker socket, no checkout, no `npm`, no
`psql`. And `docker compose up -d` destroys the very container serving the
admin's request, so the api can never be the thing that finishes its own
update.

## Phase 1: one command installs it

- merged: 142e320a2008bb4ee6c52a2d3082e5a87b43fc83


- [done] P1.1: POSIX bootstrap prologue, two modes in one file
  evidence: `cat scripts/install.sh | dash -s -- --help` → "prints usage and
  exits 0 having cloned nothing; `dash -n` parses the 165-line prologue clean;
  piped with `--dir` into an existing checkout it refuses to `git pull`, names
  `scripts/update.sh` instead, and execs into bash"
- [done] P1.2: `--bind`, `--dir`, `--repo`, `--help`, and a no-terminal refusal
  evidence: `cat scripts/install.sh | dash -s -- --dir=$PWD` → "dies with
  'no terminal to ask questions on' and the clone-and-run-it-directly recipe
  rather than hanging or silently defaulting; `--bogus` and `--bind=nonsense`
  are both rejected by name"
- [done] P1.3: `scripts/extract_frontend.sh`, bundle out of the built image
  evidence: `diff -r --exclude=.build-commit dist.from-host dist.from-image` →
  "IDENTICAL. A host `npm run build` on Node 24.19.0 and the bundle copied out
  of the api image agree byte for byte across the whole tree, so the second
  build was producing nothing the first had not"
- [done] P1.4: install.sh and update.sh both install the bundle from the image
  evidence: `grep -n 'npm ci\|npm run build\|node:24' scripts/install.sh` →
  "no host-node references remain; update.sh keeps one, inside a comment
  explaining what the ordering replaced"
- [done] P1.5: `update.sh` wrapped in `main()` so git cannot rewrite it mid-run
  evidence: `bash -n scripts/update.sh` → "clean; the three heredocs at lines
  152, 393 and 517 kept their terminators at column 0, which a naive reindent
  would have broken"
- [done] P1.6: public-safety scan passes
  evidence: scripts/check_public_safe.sh → "PASS - nothing blocking found in
  655 files, from three blocking categories before"
- [done] P1.7: README, DEPLOYMENT, ARCHITECTURE, CLAUDE.md, CHANGELOG
  evidence: tests/backend/deploy_01_rollback_target.py → "6/6, with
  deploy_02 14/14 and deploy_03 11/11. All three extract shell functions out of
  update.sh and re-run them, so they are what proves the main() wrapper changed
  the file's shape without changing its behaviour"
- [done] P1.8: full piped install into a scratch checkout, on a real pty
  evidence: scripts/extract_frontend.sh → "a piped `dash` install of commit
  c268a11 into a fresh clone built the images, installed the bundle from the
  image, came up healthy on 127.0.0.1:8443, and bootstrapped an admin who then
  logged in (200, role admin). frontend/dist/.build-commit and the container's
  org.opencontainers.image.revision both read c268a1195b, and no file under
  frontend/ is root-owned"

## Phase 2: the deployment tells you what it is running

- merged: 142e320a2008bb4ee6c52a2d3082e5a87b43fc83


- [done] P2.1: `/api/version`, and the frontend learns its own build sha
  evidence: tests/backend/deploy_04_deployment_activity.py → "/api/version
  answers unauthenticated with the full 40-character sha, and reports the same
  string as /api/admin/deployment. The commit is also baked into the served
  bundle: grepping frontend/dist/assets for the sha finds it in index-*.js"
- [done] P2.2: `GET /api/admin/deployment`
  evidence: tests/backend/conf_01_require_admin_boundary.py → "18/18, including
  the two new routes answering 403 to a non-admin"
- [done] P2.3: `GET /api/admin/activity` -- who is mid-calculation
  evidence: tests/backend/deploy_04_deployment_activity.py → "24/24. The
  per-user rows sum to the totals for all three counters, would_be_interrupted
  agrees with each row's own numbers, and a running job staged against the
  admin is counted on their row and not in the unowned bucket -- then the
  deployment reads idle again once it is removed"
- [done] P2.4: `DeploymentSection.tsx` in the admin panel
  evidence: tests/frontend/deploy_05_deployment_section.spec.mjs → "11/11 in
  chromium. The nav entry and the section both render, the API commit it
  prints is the one /api/version reports, no stale-build warning appears when
  the tab and server agree, the three counters on screen match the API's
  totals, another user's live stream is named rather than the panel claiming
  the deployment is idle, and a job staged mid-run appears without a reload"

## Phase 3: the execution channel

- merged: 142e320a2008bb4ee6c52a2d3082e5a87b43fc83


- [done] P3.1: host-side runner, triggered through `data/deploy/`
  evidence: scripts/deploy_runner.sh → "a ping request is answered with state
  done and 'the runner is alive'; a report request produces report.json with
  the same findings and exit code as the human report. The api container never
  gets a docker socket: it writes a request into the one shared directory and
  the runner, running on the host as the operator, accepts an action from a
  fixed set and resolves the ref itself"
- [done] P3.2: nginx serves the status file, so progress survives the restart
  evidence: scripts/deploy_runner.sh (live update, scratch deployment on :8443) → "with the api
  answering and then not, /deploy-status/<id>/status.json kept returning the
  runner's current step throughout, served by an nginx container that was never
  recreated"
- [done] P3.3: `check_destructive.sh --json`
  evidence: scripts/check_destructive.sh → "--from HEAD~1 --to HEAD --json
  reports exit_code 0, 0 destructive, 2 warnings and seven findings, matching
  the human report line for line. Findings are recorded by the same dest/warn/
  ok/skip functions that print them, so the two cannot drift"
- [done] P3.4: installer offers to install the runner; liveness ping
  evidence: scripts/install_updater.sh → "installed nexusqc-updater-c8ae4996
  (the suffix is a hash of the checkout path, so the dev checkout's own unit
  does not collide), wrote a heartbeat, and the api then reported
  runner={installed: true, alive: true}. With the heartbeat removed, an update
  request is refused with a 503 naming scripts/update.sh instead of queueing
  for nothing to claim"

## Phase 4: nobody loses work to an update

- merged: 142e320a2008bb4ee6c52a2d3082e5a87b43fc83


- [done] P4.1: pause admission, then drain, then maintenance, in that order
  evidence: scripts/update.sh (two live updates, scratch deployment on :8443, timed) → "with
  maintenance entered before the build (the original order), app_config
  .maintenance_mode was true for the whole run: 07:23:31 to 07:26:45, 3m14s,
  of which the api was actually unreachable for one 5s sample. With it moved to
  bracket only the recreate, an update of the same shape ran 07:28:55 to
  07:32:13 with maintenance off until 07:32:05 -- 3m04s of it fully served, and
  a lockout of about ten seconds. Same total duration, the lockout went from
  the whole run to the restart"
- [done] P4.2: `job_admission_paused`, replacing a cap the admin API refuses
  evidence: scripts/update.sh + app/chemistry/jobs/base.py → "the drain sets
  its own flag rather than max_concurrent_jobs_total=0, which the admin API
  refuses as a value; a job held by it now says the deployment is being updated
  and that it will start on its own"
- [done] P4.3: global logout before the restart
  evidence: scripts/deploy_runner.sh (live update, scratch deployment on :8443) → "caught
  mid-update, redis held 0 keys matching qc_agent:session:active:*, and a login
  afterwards returned 200. The logout happens after the drain, not at confirm
  time, so nobody is shut out while their own jobs finish"
- [done] P4.4: maintenance mode, and the 503 as the broadcast channel
  evidence: scripts/deploy_runner.sh (live update, scratch deployment on :8443) → "caught
  mid-update: app_config.maintenance_mode was true, redis held 0 active
  sessions (everyone logged out), /api/health and /api/version still answered
  200, and /api/threads returned 503 with {\"detail\": \"maintenance\"} and
  Retry-After: 30"
- [done] P4.5: progress and reload survive the api going away
  evidence: scripts/deploy_runner.sh (live update, scratch deployment on :8443) → "at 07:32:10 the
  api answered 502 while nginx was still serving /deploy-status/<id>/status.json
  from a container that was never recreated. The overlay polls that path, treats
  a failed fetch as 'still updating' so it survives nginx bouncing too, and
  hard-reloads when the run reports done -- index.html is served no-store and
  /assets/ is immutable and content-hashed, so the reload lands on the new
  bundle"
- [done] P4.6: preview, what's-new, history, rollback, backup
  evidence: tests/frontend/deploy_05_deployment_section.spec.mjs → "13/13
  against the dev stack, which has no updater installed, and 15/15 against the
  scratch deployment, which has one. Both branches are real: with a runner the
  preview button is offered and both irreversible controls sit behind a typed
  phrase; without one the panel names scripts/update.sh and offers no button at
  all"

## Incidental findings

Logged here rather than fixed silently or lost in conversation.

- [done] The installer's Node check accepted `>= 20` while the Dockerfile
  requires `>= 24.14.1` for Ketcher. A Node 20 host passed the check and built
  a bundle outside Ketcher's supported range. Resolved by deleting the host
  build entirely (P1.3).
- [done] The no-host-Node fallback ran `docker run -v frontend:/app node:24`
  with no `--user`, leaving `frontend/node_modules` and `frontend/dist`
  root-owned -- the exact problem `APP_UID`/`APP_GID` exists to prevent for
  `data/`. Resolved by the same deletion.
- [done] `install.sh` wrote neither build stamp, so every fresh install read as
  `unknown` and its first `update.sh` rebuilt unconditionally. It now exports
  `QC_AGENT_BUILD_COMMIT` before the build and stamps the bundle.
- [done] `update.sh` fast-forwards the checkout it is running from, and is
  itself a tracked file in it. With no `main()` wrapper, git rewrote the script
  while bash was still reading it. Wrapped (P1.5).
- [done] The installer's network-exposure notice had lost a clause, printing
  "considered step, not something to enable during a first install." as a
  sentence with no subject.
- [done] `models.revoke_session` has exactly one occurrence in the tree, its
  own definition. Nothing calls it, `get_current_user` never reads
  `sessions.revoked`, and `create_session` is always passed `user_agent=None`,
  so the Postgres `sessions` table is write-only bookkeeping that reads as a
  security control. Scheduled for P4.3.
- [done] `tests/fixtures.py` extracted shell functions from `update.sh` by
  matching a closing brace in column zero, and an awk program by a hardcoded
  four-space indent. Wrapping the script in `main()` broke all three deploy
  tests at once. Both extractors now take their indentation from the opening
  line rather than assuming it, which is what the tests' own error message
  ("fix this extraction rather than inlining a copy that cannot go stale")
  asks for.
- [done] The first `extract_frontend.sh` swapped `frontend/dist` for a
  freshly built directory. A docker bind mount follows the inode it was mounted
  on, not the path, so the running nginx stayed mounted on the directory that
  had been moved aside and served 404 for the entire site. Invisible on a fresh
  install (nginx starts after the copy) and fatal on every run against a live
  stack, which is what an update is. Contents are now replaced in place.
- [done] `CLAUDE.md`'s documented way to test the chemistry core produced a
  job that always failed. The recipe passed `JobSpec(method='single_point')`,
  which is the pre-v2 shape: `method` is the level of theory and `task`/
  `subtype` are what the job is, so the spec landed with an empty task and
  died at dispatch with "No runner is wired up for / yet." Corrected to
  `task='single_point', subtype='gs', method='hf'`, which completes.
- [done] The activity table counted the admin reading it as somebody an update
  would interrupt, because having the page open is itself an open event
  stream. A deployment that permanently claims someone is mid-calculation
  trains people to click through the warning that matters, so rows now carry
  `is_you` and the totals carry `others_interrupted`.
- [done] `admin.py` refuses any `max_concurrent_jobs_total <= 0`, so the drain
  `update.sh` performed by writing that row directly with psql was a value the
  console could never set. Replaced with a `job_admission_paused` flag.
- [done] Maintenance mode was entered before `docker compose build`, so a real
  update locked every user out for the ten-minute image build as well as the
  ninety-second restart. The build changes nothing about the running
  deployment; maintenance now brackets only the recreate. Found by running an
  update against a real deployment and watching the clock, not by reading it.
