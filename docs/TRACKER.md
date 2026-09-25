<!-- artifact: https://claude.ai/artifact/WfEymuYySz4YWuVSn5xHqx -- re-render with scripts/render_tracker_html.py and re-publish to THIS url -->
# Tracker: the stack holds real data, and updates warn, lock out and let back in

**Opened 2026-09-24.** Four phases. The tracker this replaces is
[`trackers/2026-09-cores-per-calculation.md`](trackers/2026-09-cores-per-calculation.md),
which closed the same day. **Exactly one tracker is active at a time.**

## Rules (enforced by `scripts/check_tracker.py`)

- Step status is exactly one of `todo` | `in-progress` | `done`.
- A step may be marked `done` **only with an evidence field**: one path that
  exists on disk plus a one-line observed result.
- The tracker edit ships **in the same commit** as the step's final change.
- A phase's `merged` row records the commit hash the stage landed as.

Format for a step row:

```
- [status] P<phase>.<step>: <short name>
  evidence: <path> → "<observed result>"   (required when done)
```

---

## Why this plan exists

The dev stack is now also the research group's testing deployment, so its data
belongs to real people. On 2026-09-24 a test script, `p1_03`, was run on its own
to check a config change. Its admin purge deleted seven finished uracil jobs
belonging to the `dma` account. They were restored from the backup taken at
21:02 the same evening. The user then asked for four things:

1. Audit every script so none can wipe user data.
2. When the stack is updated, notify every user, lock them out, and let them
   back in when it is done.
3. Change testing and evaluation to suit a stack with real users on it.
4. Make it possible to update the dev stack from the admin console.

Stopping and rebuilding the stack is still fine. Deleting data is not.

**What the audit found.** A read of every test, evaluation and host script:

- `tests/e2e/e2e_16_admin_destructive.py --destroy` runs `admin_cli
  reset-all`, which deletes every account. Only that flag guards it.
- Three scripts in the default suites restart the live api, which interrupts
  whoever is using the app: `conf_04`, `perf_05_restart_queue` and
  `e2e_13_stability`.
- Two scripts change a deployment-wide quota and never put it back: `up_01`
  and `e2e_16`.
- `fixtures.reset_rate_limits()` clears every client's login rate-limit
  buckets before every backend script, not only the test client's.
- nginx logs every client as `172.18.0.1`, the Docker gateway. If the app sees
  the same address, the whole group shares one rate-limit bucket.
- A few host scripts write jobs into the live `data/jobs`. They clean up
  unless they crash.

**What already existed for updates.** The console update path is built end to
end, but the host service it needs was never installed here and the signing
secret is unset. Maintenance mode locks non-admins out and every exit path
clears it. There was no advance notice and no "it's back" message.
Maintenance was off by default, and entering it logged every user out for no
reason that holds: sessions live in Redis, which an api update does not
restart.

**The user's decisions.** Ten minutes' notice by default, adjustable per update
in the console. An update waits for running calculations; the console also
offers an override that stops them, behind a typed confirmation that names
whose jobs would stop.

The full plan is in `.claude/plans/witty-painting-lantern.md` (not tracked).

---

## Phase 1: tests cannot lose other people's data or drop them

- [done] P1.1: whole-stack purges and reset-all refuse on a stack with real users
  evidence: tests/fixtures.py → "with QC_AGENT_TEST_ALLOW_PURGE=1 set on this stack: a direct admin purge raised BlindPurgeRefused naming dakshitha, dma, maneesh; p1_07 skipped; e2e_16 --destroy skipped D3 and D6-D8, 6/6 other checks passed; no purge reached nginx, job list and accounts unchanged"
- [done] P1.2: api restarts are opt-in and refuse while real users are active
  evidence: tests/fixtures.py → "conf_04 and perf_05 printed [SKIP] without the flag; with QC_AGENT_TEST_ALLOW_RESTART=1 restart_refusal answered 'real users are active: dma (0 running, 1 open)'; api StartedAt unchanged. Scripts kept in the default set since they skip themselves; e2e_13 S4 and perf_10 use the same check"
- [todo] P1.3: every config change in tests restores; quota tests cannot evict others
- [todo] P1.4: rate-limit reset scoped to test identities; real client IPs reach the app
- [todo] P1.5: every test run checks real users' data is intact before and after
- [todo] P1.6: host scripts stay out of the live job folder
- [todo] P1.7: guidance says the stack holds real data
- merged:

## Phase 2: updates warn, lock out, and let back in

- [todo] P2.1: the update notice: app_config row and GET /api/notice
- [todo] P2.2: update.sh posts the notice, waits it out, locks, restarts, posts done
- [todo] P2.3: users stay logged in through an update
- [todo] P2.4: the banner in the app, and the overlay text to match
- merged:

## Phase 3: update from the console

- [todo] P3.1: console controls: notice minutes, message, cancel, stop-and-update override
- [todo] P3.2: deploy request carries the notice; cancel is an api action
- [todo] P3.3: the updater runs on this host
- merged:

## Phase 4: verification and rollout

- [todo] P4.1: backend and browser tests for the notice, console and guards
- [todo] P4.2: full default suites leave real users' data unchanged and restart nothing
- [todo] P4.3: rollout, then a console update watched from a non-admin session
- [todo] P4.4: docs, changelog, and the tracker closed out
- merged:
