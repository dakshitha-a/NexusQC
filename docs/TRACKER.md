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
- [done] P1.3: every config change in tests restores; quota tests cannot evict others
  evidence: tests/backend/share_04_quota_refusal.py → "9/9 on the rebuilt stack at 89e9bac: the squeeze is a per-user override on the recipient only and the deployment-wide cap stays 18 GB; p1_03 7/7 writes back the value already set, up_01 31/31 likewise; the settings tests had left behind (dma's per-user job cap 8 overwritten to 3, uploads quota below its default since 09-14) were put back through the admin API"
- [done] P1.4: rate-limit reset scoped to test identities; real client IPs reach the app
  evidence: tests/backend/sec_17_login_per_account.py → "4/4: account A throttled after ten wrong passwords while account B on the same address signs in at once; sec_03 4/4 unchanged. Every client reaches the app as 172.18.0.1 because Docker's userland proxy fronts nginx; fixing that is a root-owned daemon change for a person, recorded in docs/HANDOFF.md"
- [done] P1.5: every test run checks real users' data is intact before and after
  evidence: tests/backend/integ_01_integrity_check.py → "5/5: a live snapshot (3 real accounts, 29 owned items) compared with itself passes; a removed job, a file removed from a finished job, and a removed account are each reported by name; a changed setting is a note, not a loss. run_e2e.sh e2e_03 ran wrapped: snapshot, 9/9, integrity PASS"
- [done] P1.6: host scripts stay out of the live job folder
  evidence: scripts/validate_ensemble_orbital_reuse.py → "all checks passed against a scratch QC_AGENT_DATA_DIR; data/jobs listing identical before and after. spike_thread_caps.py carries the same header (compile-checked; it needs engines). verify_orca_functionals writes data/verified, a reference list, not user data, so it is unchanged"
- [done] P1.7: guidance says the stack holds real data
  evidence: tests/README.md → "new section 'This stack has real users on it' tabulates all ten guards, where each lives and what it stops; CLAUDE.md, docs/TESTING.md and docs/WORKFLOW.md point at it, WORKFLOW forbids docker compose down -v; the Docker userland-proxy decision is in docs/HANDOFF.md"
- [done] P1.8: admins see only their own work (raised mid-run: an admin saw another user's live chat and his project copy)
  evidence: tests/backend/priv_01_admin_scope.py → "21/21 on the rebuilt stack: an admin's conversation, job and project lists hold only their own; the other user's conversation state, event stream, job and project are 404 to the admin, and renaming or deleting them through workspace routes is 404 and changes nothing; the admin-only delete routes work. proj_02, proj_03, kb_01, sec_09, sec_11, sec_13, purge_01 pass with their admin assertions flipped. Not looked at as dma in a browser: the session has no dma password"
- merged: 12c7f31

## Phase 2: updates warn, lock out, and let back in

- [done] P2.1: the update notice: app_config row and GET /api/notice
  evidence: tests/backend/notice_01_update_notice.py → "18/18: public route with server clock, maintenance-exempt, expiry hides a notice, deploy bounds 0-120 min and 500 chars, cancel with nothing announced is 409, update.sh post_notice keeps quotes and backslash, cancel_requested matches only its own id; the live done notice was saved and put back identical"
- [in-progress] P2.2: update.sh posts the notice, waits it out, locks, restarts, posts done
- [done] P2.3: users stay logged in through an update
  evidence: scripts/update.sh → "first rollout (a38f690 -> 89e9bac) logged out no one: no 'logged out' line in its log, and dma's Redis session key dates from 8.6 h before, maneesh's from his password reset an hour before"
- [done] P2.4: the banner in the app, and the overlay text to match
  evidence: tests/frontend/notice_01_update_notice.spec.mjs → "36/36 on the deployed bundle: every phase renders its sentence, done dismisses and stays dismissed, the sign-in screen shows it, the overlay does not reload while the lockout is on and reloads once it lifts; screenshots of each phase looked at"
- merged:

## Phase 3: update from the console

- [in-progress] P3.1: console controls: notice minutes, message, cancel, stop-and-update override
- [in-progress] P3.2: deploy request carries the notice; cancel is an api action
- [todo] P3.3: the updater runs on this host
- merged:

## Phase 4: verification and rollout

- [todo] P4.1: backend and browser tests for the notice, console and guards
- [todo] P4.2: full default suites leave real users' data unchanged and restart nothing
- [todo] P4.3: rollout, then a console update watched from a non-admin session
- [todo] P4.4: docs, changelog, and the tracker closed out
- merged:
