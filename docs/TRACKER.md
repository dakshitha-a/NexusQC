# Tracker: one-command install, and an in-app update path

<!-- artifact: (recorded on first publish) -->

**In motion, opened 2026-09-08.** Four phases. Makes installing NexusQC a
single `curl ... | sh`, moves the frontend bundle out of the api image instead
of building it twice, and puts a real update path in the admin panel.

It stays here rather than moving to [`trackers/`](trackers/) until the next
plan starts. **Exactly one tracker is active at a time.** The one this replaces
is
[`trackers/2026-09-cas-closeout-and-suite-audit.md`](trackers/2026-09-cas-closeout-and-suite-audit.md).

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
- [in-progress] P1.8: full piped install into a scratch checkout, driven through a pty

## Phase 2: the deployment tells you what it is running


- [todo] P2.1: `/api/version`, and the frontend learns its own build sha
- [todo] P2.2: `GET /api/admin/deployment`
- [todo] P2.3: `GET /api/admin/activity` -- who is mid-calculation
- [todo] P2.4: `DeploymentSection.tsx` in the admin panel

## Phase 3: the execution channel


- [todo] P3.1: host-side runner, triggered through `data/deploy/`
- [todo] P3.2: nginx serves the status file, so progress survives the restart
- [todo] P3.3: `check_destructive.sh --json`
- [todo] P3.4: installer offers to install the runner; liveness ping

## Phase 4: nobody loses work to an update


- [todo] P4.1: pause admission, then drain, then maintenance -- in that order
- [todo] P4.2: `job_admission_paused`, which the admin API can actually set
- [todo] P4.3: global logout, and the write-only `sessions` table made real
- [todo] P4.4: maintenance mode, and the 503 as the broadcast channel
- [todo] P4.5: auto-reload onto the new build
- [todo] P4.6: preview, what's-new, history, rollback, backup, badge

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
- [todo] `admin.py` refuses any `max_concurrent_jobs_total <= 0`, so the admin
  API cannot express the drain that `update.sh` performs by writing the same
  row directly with psql. Scheduled for P4.2.
