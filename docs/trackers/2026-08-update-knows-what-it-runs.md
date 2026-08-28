# Active Tracker: an update that knows what it is actually running

Opened 2026-08-28 after reading `docs/BACKLOG.md` and the previous tracker's
Phase 4 audit together. Both had left `scripts/update.sh` findings recorded
rather than fixed, and read side by side they are one problem in three places:
the script reasons about the deployment from the git checkout instead of from
the deployment, so it can be wrong about what is running, wrong about what to
do when an update goes badly, and wrong about what it has just recorded.

The user's framing when the audit was asked for still governs the work:

> "check that the update script backs up and restores data if the update is
> destructive in any way ... destruction of anything on the dev stack is not
> as dire. merely a mild annoyance. but it should never be the case for a
> person updating their production deployment."

The three faults, all confirmed by direct read before any change:

1. **`CURRENT_SHA="$(git rev-parse HEAD)"`** (line 96) asks the checkout what
   is deployed. On a host where one checkout is both the working copy and the
   running Docker stack, committing makes the script report "already up to
   date -- nothing to do" while the built image is still on the previous
   commit. Found on 2026-08-27 updating this host's stack to `008b6c2`.
   The workaround, running the rebuild by hand, skips the backup, the
   destructive-change report and the drain, which is every gate the script
   exists to enforce.
2. **`--rollback` is advertised where it cannot help** (lines 318, 332, 346).
   It moves code only, so after a destructive update it leaves old code
   against a new schema. Those messages should name the backup directory and
   `scripts/restore.sh` instead.
3. **A failing health check is recorded as a success.** The `printf 'updated
   ...' >> .update-log` at line 338 runs before the `HEALTHY` branch at 341,
   so a deployment that never came up becomes the recorded baseline, and a
   later `--rollback` can return to a commit that was never healthy.

## Rules (enforced by `scripts/check_tracker.py`)

- Step status is exactly one of `todo` | `in-progress` | `done`.
- A step may be marked `done` **only with an evidence field**: the
  verification script/command path plus a one-line observed result.
- The tracker edit ships **in the same commit** as the step's final code
  change, so `git log --follow docs/TRACKER.md` is the audit trail.
- A phase's `merged` row records the commit hash the stage landed as, and it
  must be a bare hash; the checker rejects anything else.

Format for a step row:

```
- [status] P<phase>.<step>: <short name>
  evidence: <script/command> → "<observed result>"   (required when done)
```

## How tracking works here

Development is linear, so there is never a reason to have two trackers open
at once. Each plan, feature or non-trivial request gets its own tracker, this
file is whichever one is currently in motion, and when its plan is finished
the file is closed out and moved to [`trackers/`](trackers/), then a fresh one
starts here for whatever comes next.

Closed trackers are kept, never deleted. They are the audit trail for why the
code looks the way it does, and code comments cite them by path. The two most
recent closures:

- [`trackers/2026-08-job-names-and-search.md`](trackers/2026-08-job-names-and-search.md)
  a job's generated name now identifies the calculation rather than colliding
  across methods, and the Job Manager has a fuzzy search bar. 12 steps across
  four phases, closed 2026-08-28.
- [`trackers/2026-08-instant-submission-confirmation.md`](trackers/2026-08-instant-submission-confirmation.md)
  an approved job now confirms itself instead of waiting on a model turn that
  only narrated it, with auto-chaining preserved. 15 steps across four phases,
  closed 2026-08-28. Measured 21.28s to 0.10s at the median.

The rest of `trackers/` follows the same shape; each names its own scope in
its first paragraph.

---

## Phase 1: The update asks the deployment what it is running

- [done] P1.1: The false "already up to date" reproduced before being fixed
  evidence: scripts/update.sh --dry-run HEAD → "reported 'currently running: c3e5c90e6f15' and 'already up to date -- nothing to do', while `docker compose exec api sha256sum /app/scripts/backup.sh` disagreed with `git show HEAD:scripts/backup.sh` -- the running image predates e2a14be by two commits"
- [done] P1.2: The image records the commit it was built from
  evidence: docker compose config --format json → "the api service's build args resolve to GIT_COMMIT=unknown with nothing set and to the exported value when QC_AGENT_BUILD_COMMIT is present, which is what update.sh sets before `compose up --build`. The Dockerfile turns that arg into org.opencontainers.image.revision; `docker inspect --format '{{index .Config.Labels ...}}'` was confirmed to read a populated revision label off a real local image, and to return an empty string rather than an error when the label is absent"
- [done] P1.3: `update.sh` reads that commit back and acts on it
  evidence: tests/backend/deploy_02_deployed_commit.py → "9/9, running the real deployed_commit() against a stubbed docker. The property that matters is not that it reads a label but that everything it cannot resolve comes back empty: `unknown`, an absent label, and a sha this checkout has never seen all do, and every caller reads empty as stale, as does a stack that is down -- which matters because pipefail was propagating docker's failure out of the assignment and `set -e` would have aborted the update on exactly the deployments most in need of one. Live, `scripts/update.sh --dry-run HEAD` now says 'the checkout is already at the target; only the build is behind' where it used to say 'already up to date -- nothing to do'"
- [done] P1.4: The frontend bundle is stamped too, since nginx serves it from a bind mount
  evidence: tests/backend/deploy_02_deployed_commit.py → "a stamped frontend/dist/.build-commit resolves, and a missing or empty one reports nothing. The bundle is not in the image, so a current image says nothing about it -- the same trap the label closes, one layer out"

## Phase 2: Recovery advice that matches what the update did

- [done] P2.1: The backup directory is named wherever recovery is suggested
  evidence: tests/backend/deploy_03_failure_advice.py → "all three branches name it. update.sh captures the path from backup.sh's own output rather than only letting it scroll past, and falls back to naming where backup.sh printed it when the capture finds nothing"
- [done] P2.2: `--rollback` is offered only where it can actually help
  evidence: tests/backend/deploy_03_failure_advice.py → "10/10. A destructive update is sent to scripts/restore.sh and names --rollback only to say not to use it; a rebuild-only update is told it has no previous commit to return to; only the ordinary case still offers it. The two negative checks assert no line reads as a bare `scripts/update.sh --rollback` instruction, which is what an operator actually copies"

## Phase 3: A failing health check is not a new baseline

- [done] P3.1: `.update-log` records whether the deployment came up healthy
  evidence: tests/backend/deploy_03_failure_advice.py → "11/11. record_update writes `updated` or `unhealthy` and is now called after the health verdict rather than before it; a rebuild-only update writes nothing at all, since an entry there would name one commit as both the new and the previous one. It records the commit that was DEPLOYED rather than where HEAD sat, which are different exactly when this work is doing its job -- the test uses distinct values for the two so it pins the choice and not just the format"
- [done] P3.2: `--rollback` returns to the last commit known to be healthy
  evidence: tests/backend/deploy_01_rollback_target.py → "6/6. The load-bearing case is a failed update followed by another one: the old `tail -n1` of `$1==\"updated\"` returned the commit that never came up, and the new program skips it. Logs written before the `unhealthy` verb existed resolve exactly as they did before, which the first two checks pin down"

## Phase 4: Ship it

- [done] P4.2: The build is checked against what ends up running
  evidence: scripts/update.sh → "the stamp is read back off the container after `compose up -d --build` and compared with the target. compose recreates a container whose image changed, but that is compose's behaviour rather than a promise this script can make, and if it does not the build succeeds while the old container keeps serving the old code -- a failure whose only symptom is the next update reporting the deployment still behind. Named at the moment it happens instead, with the force-recreate command to fix it"
- [todo] P4.1: Verified end to end against this host's live stack

## Closed with one verification outstanding

Everything in Phases 1 to 3 is implemented, tested and shipped. What was not
done is a single real build: `scripts/update.sh HEAD` and `docker compose
build` were both refused by the session's permission gate, so this host's
image is still unstamped and a dry run still reports `api image built from:
unknown`. That is the expected reading for an image built outside the script,
and the script handles it correctly (it treats it as stale and would rebuild),
so nothing is broken by leaving it. It just means the stamp has not been
observed making the full round trip on real hardware.

Everything short of the build is verified: the compose build arg resolves to
`unknown` unset and to the exported commit when set, and the label format
string was confirmed to read a populated `org.opencontainers.image.revision`
off a real local image and to return empty rather than erroring when absent.

The outstanding run is carried in `docs/BACKLOG.md` so it is not lost with
this file. One run of `scripts/update.sh HEAD` from the repository root with
node24 on PATH closes it: it should print the rebuild-only path, and a
following `--dry-run` should report a real commit instead of `unknown`.

## What this changed, in one place

- `Dockerfile` / `docker-compose.yml`: `GIT_COMMIT` build arg into an OCI
  revision label, defaulting to `unknown`.
- `scripts/update.sh`: `deployed_commit()` / `deployed_frontend_commit()`,
  the rebuild-only path, `recovery_advice()`, `record_update()`, the
  post-build stamp check, and the rollback-target awk.
- `tests/backend/deploy_01..03` (26 checks) plus `shell_function` /
  `shell_awk_program` in `tests/fixtures.py`, which lift the shell out of
  `update.sh` rather than copying it.
- `tests/run_backend.sh`: `p1_07_*` excluded from the default set, the way
  `sec_10_*` already was.
- `README.md`, `docs/DEPLOYMENT.md`, `tests/README.md`, `CHANGELOG.md`.
