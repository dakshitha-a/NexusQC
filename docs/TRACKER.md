<!-- artifact: https://claude.ai/code/artifact/5739e72d-33f4-4a28-9db0-023e82c5b9ea -- re-render with scripts/render_tracker_html.py and re-publish to THIS url -->
# Tracker: fixing what the review found

**All 102 findings of the September 2026 app review, worked to a resolution.**
Seven phases. Every finding in
[`evaluation/2026-09-app-review/findings.md`](evaluation/2026-09-app-review/findings.md)
ends this plan with a `resolution:` line saying `fixed`, `not reproduced`, or
`won't fix` with a reason, and every `fixed` one names a regression test that
failed before the fix and passes after.

The tracker this replaces is
[`trackers/2026-09-app-review.md`](trackers/2026-09-app-review.md), the review
that produced the register. **Exactly one tracker is active at a time.**

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

Re-render and re-publish the artifact at every step completion:

```bash
python3 scripts/render_tracker_html.py /tmp/tracker.html
```

---

## Why this plan exists

The review recorded 102 open findings against `ca7e0ff` and deliberately fixed
none of them, because changing the system under test mid-run makes findings on
either side of the change incomparable. That discipline is now over. The user
asked for all 102 attempted rather than a confirmed-only subset, so the
unconfirmed ones get a reproduction attempt first and are closed honestly if
they do not reproduce.

Three decisions the user made on 2026-09-13, recorded so they are not re-asked:

1. **All 102 findings are in scope**, not just the 38 confirmed ones.
2. **The new job timeout defaults to disabled** (R-011). A long job is the
   design premise; a hung engine is stopped by the kill and cancel buttons.
   Operators may set `QC_AGENT_JOB_TIMEOUT_HOURS`.
3. **The four settling experiments run inside this tracker** (Phase 4), not in
   a follow-up round.

## Working rules for this plan

1. **One finding cluster, one commit, one regression test.** Every fix ships a
   test that fails before and passes after. Both runs log into
   `evaluation/2026-09-app-review/evidence/fix/P<n>.<k>/`, which is the step's
   evidence path.
2. **Timing of the two runs.** Only nginx publishes a host port, so there is no
   working-tree route server. An in-process test (a function call, a parser on
   saved output, an input builder) gets both logs at step time. A route or
   browser test gets its before-log any time before the phase gate, while the
   stack still runs the old code, and its after-log at the gate once
   `update.sh` has advanced the stack.
3. **Fixes span all engines and methods.** A class found on ORCA is checked on
   PySCF and BAGEL before the entry closes, and `scope:` says what was checked.
4. **Audit every surface a change touches**: runner, elicitation, README,
   `CONFIGURATION.md`, `QM_CAPABILITIES.md` (regenerated, never hand-edited),
   `ARCHITECTURE.md`, welcome screen, help flyout, the deploy scripts' wording.
5. **Admission gate and quotas.** Anything touching how jobs execute is checked
   against `JobManager._wait_for_resources` and the per-user quota.
6. **Gate order is fixed**: data archive, `update.sh --yes`, stamp shows HEAD,
   re-arm watches, four suites, after-logs, two-sided cleanup diff. Before P2.1
   lands, `update.sh --rollback` is broken (R-019): on a failed health check,
   fix forward, never roll back.
7. **Test-data hygiene.** Work as `qa_fix` and `qa_fix_2`. Snapshot before,
   delete only the after-minus-before set. Never `p1_07`, `p1_03`,
   `perf_02_admin_storage_latency`, `sec_10`, `--with-destructive`,
   `--destroy`, `POST /api/admin/purge/*`, `reset-all`.
8. **Register traceability.** Each closed finding gets `- resolution: ...` and
   `- regression test: ...` appended to its entry in `findings.md`.
9. **An honest attempt**, before any `not reproduced`: the register's repro plus
   one variation, three fresh threads for LLM-cause items, and the mechanical
   fallback to split LLM from CODE.

---

## Phase 0: Open the fix tracker

- [done] P0.1: Archive the review tracker, write this one, clear the handoff
  evidence: docs/trackers/2026-09-app-review.md → "review tracker archived and retitled Closed Tracker, its artifact restored at 9ae8d698; this tracker published at 5739e72d; the triage entry is out of HANDOFF.md; check_tracker.py passes with 45 steps"
- [done] P0.2: Accounts, snapshot, and the R-001 backfill target list
  evidence: docs/evaluation/2026-09-app-review/evidence/fix/P0.2 → "8 listed jobs, 16 on disk (8 of them unowned children of 186fe458ec9e), 9 threads, 0 plots, 0 projects, 3 users snapshotted; qa_fix and qa_fix_2 registered"
- [done] P0.3: Arm the log and health watches
  evidence: docs/evaluation/2026-09-app-review/evidence/fix/P0.3 → "api log watch pid 1169987 and health probe pid 1169988 running, both writing here, both in the scratchpad shell ledger"
- [done] P0.4: The resolution summariser, so the close-out is reproducible
  evidence: docs/evaluation/2026-09-app-review/evidence/summarize_resolution.py → "summarize_resolution.py reports 0 of 102 findings carrying a resolution, which is the correct starting state and confirms the 102 denominator"
- merged: 6519a63

## Phase 1: The S1 findings, in containment order

- [done] P1.1: R-004, R-085 - a canonical method name is never renormalised
  evidence: docs/evaluation/2026-09-app-review/evidence/fix/P1.1 → "draft_02_canonical_method_survives.py went 30/33 to 41/41; lpdft, pdft, l-pdft and tddft now resolve the registry's way and an L-PDFT draft builds a spec whose method is lpdft with its active space intact; elic_01 205/205, mrpdft_01 153/153, dft_01 58/58, reg2_01, reg2b_01, tddft_01 and draft_01 all unchanged"
- [done] P1.2: R-001, R-090 - child jobs inherit their parent's owner
  evidence: docs/evaluation/2026-09-app-review/evidence/fix/P1.2 → "in process, effective_owner resolves a child to its master's owner, leaves a genuinely unowned chain alone, and terminates on a parent cycle; live, the before-log records all eight children of 186fe458ec9e served in full to an account owning nothing (11/35), which the Phase 1 gate re-runs against the rebuilt stack"
- [done] P1.3: R-002, R-005, R-008 - path safety on both siblings, everywhere
  evidence: docs/evaluation/2026-09-app-review/evidence/fix/P1.3 → "sec_12_kb_path_safety.py 20/24 with 2 skipped before the fix; the live probe wrote r002-probe-marker.txt into data/ and data/uploads/ through POST /api/kb/sources/text and removed both, and the KB write, text and URL paths now share one _safe_dest, spin and index are allowlisted beside gbw, runner.json drops the host path, nginx serves only per-run files, and the runner refuses an unsigned update"
- [done] P1.4: R-003 - the two chat routes check job ownership
  evidence: docs/evaluation/2026-09-app-review/evidence/fix/P1.4 → "sec_13_chat_job_attachment.py 5/9 before; the live probe attached another user's job to its own fresh thread, got 202, and read 5305 characters of that job's context back out of its own conversation state, and troubleshoot returned 409 which is itself a read"
- [done] P1.5: R-009 - the literature search sees only the caller's papers
  evidence: docs/evaluation/2026-09-app-review/evidence/fix/P1.5 → "sec_14_active_space_lit_scope.py 3/10 before and 9/9 after; the before-log records three knowledge-base calls made with state None, which is the unscoped paper search itself, and both tools.py call sites now pass the state they already hold"
- [done] P1.6: R-010, R-096, R-077 - state zero is a state, not a falsy value
  evidence: docs/evaluation/2026-09-app-review/evidence/fix/P1.6 → "grad_04_target_state_zero.py 19/28 before and 28/28 after; the before-log shows the S0 run of target_states=[2,1] emitting IRoot 1 and of [3,1] emitting IRoot 2, and a reordered ladder returning a negative excitation energy; BAGEL and PySCF were already right and are checked so"
- [done] P1.7: R-011, R-012, R-072, R-056 - the six-hour kill becomes a setting
  evidence: docs/evaluation/2026-09-app-review/evidence/fix/P1.7 → "jobs_04_job_timeout_and_dispatch.py 1/22 before and 27/27 after; the six-hour literal is gone from all five sites and replaced by QC_AGENT_JOB_TIMEOUT_HOURS which defaults to no limit, the orphan watcher polls instead of deadlining, an unloadable spec releases its slot and reports why, and both deploy scripts now separate running from queued"
- [done] P1.8: Gate 1 - advance the stack, four suites, live S1 re-checks
  evidence: docs/evaluation/2026-09-app-review/evidence/fix/P1.8 → "advanced ca7e0ff to c5e8835 with the data archived first; sec_11 went 11/35 to 35/35, sec_12 20/24 to 27/27, sec_13 5/9 to 8/8; backend 145/149 and frontend 34/42, with every new failure re-run alone and passing except p7_05, which is the host-wide admission gate under a load average of 141 from other tenants and is now a skip; two-sided cleanup clean on jobs, threads, plots and projects"
- merged: ba97822

## Phase 2: Deploy, backup and restore

- [done] P2.1: R-019, R-020, R-023, R-091, R-093 - update.sh tells the truth
  evidence: docs/evaluation/2026-09-app-review/evidence/fix/P2.1 → "update.sh --rollback detaches at the target and asserts the checkout moved, the unhealthy branch returns 1, INT and TERM are trapped alongside EXIT, the confirmation uses common.sh's ask(), and check 4 reads routes with their router prefix via the new scripts/list_routes.py"
- [done] P2.2: R-021, R-024, R-025 - a full backup is actually full
  evidence: docs/evaluation/2026-09-app-review/evidence/fix/P2.2 → "backup.sh --full derives its list from data/'s own children minus an explicit exclude, so plots, projects.json and scraped are in it; retention prunes only YYYYmmdd-HHMMSS directories that hold a MANIFEST.txt, verified against a foreign directory that survived; tar's exit status no longer aborts the run and the table-of-contents read is the verdict"
- [done] P2.3: R-022 - restore reads .env and reports pg_restore's status
  evidence: docs/evaluation/2026-09-app-review/evidence/fix/P2.3 → "restore.sh reads the database and user from the environment, then the backup's own manifest, then .env, and stops on a non-zero pg_restore instead of printing Restore finished"
- [done] P2.4: R-053, R-054, R-055, R-057, R-058 - ordering, drift and health
  evidence: docs/evaluation/2026-09-app-review/evidence/fix/P2.4 → "the bundle is installed after the health check rather than before the recreate, a documentation-only gap no longer makes every later run take a full backup and do nothing, and update.sh asks the new /api/health/deep whether Postgres and Redis are actually reachable"
- [done] P2.5: R-059 - pin the Python dependencies
  evidence: docs/evaluation/2026-09-app-review/evidence/fix/P2.5 → "all 33 unpinned requirements pinned to what the working image runs, taken with pip freeze inside the running api container"
- [done] P2.6: R-026, R-062, R-092 - deployment docs that run as printed
  evidence: docs/evaluation/2026-09-app-review/evidence/fix/P2.6 → "the bootstrap command passes all four required arguments, the cron line creates its own log directory, every curl example passes -k, the pointer to the deleted docker-compose.dev.yml is gone, two status rows describing removed features are gone, and nginx.conf's header stops describing a listener and a kill switch that were deleted in August"
- [todo] P2.7: Advance the stack on the fixed scripts, verify, push
  evidence: docs/evaluation/2026-09-app-review/evidence/fix/P2.7
- merged:

## Phase 3: S2 reliability and correctness

- [todo] P3.1: R-006, R-047, R-048, R-049 - the knowledge base checks first
  evidence: docs/evaluation/2026-09-app-review/evidence/fix/P3.1
- [todo] P3.2: R-007, R-032, R-050 - nothing blocking on the event loop
  evidence: docs/evaluation/2026-09-app-review/evidence/fix/P3.2
- [todo] P3.3: R-033, R-097 - an SSE stream costs no threadpool token
  evidence: docs/evaluation/2026-09-app-review/evidence/fix/P3.3
- [todo] P3.4: R-013, R-017, R-018, R-034, R-038 - the approval card survives
  evidence: docs/evaluation/2026-09-app-review/evidence/fix/P3.4
- [todo] P3.5: R-014, R-041, R-042 - troubleshooting names real tools
  evidence: docs/evaluation/2026-09-app-review/evidence/fix/P3.5
- [todo] P3.6: R-015, R-016, R-035, R-084, R-086 - active space and literature
  evidence: docs/evaluation/2026-09-app-review/evidence/fix/P3.6
- [todo] P3.7: R-028, R-060, R-061, R-063, R-074 - the registry tells the truth
  evidence: docs/evaluation/2026-09-app-review/evidence/fix/P3.7
- [todo] P3.8: R-029, R-031, R-071, R-073 - job state survives every race
  evidence: docs/evaluation/2026-09-app-review/evidence/fix/P3.8
- [todo] P3.9: R-030, R-076, R-078 - parsers across the three engines
  evidence: docs/evaluation/2026-09-app-review/evidence/fix/P3.9
- [todo] P3.10: R-027, R-068, R-069, R-094, R-095 - the frontend gaps
  evidence: docs/evaluation/2026-09-app-review/evidence/fix/P3.10
- [todo] P3.11: R-101 - a ready draft raises its card mechanically
  evidence: docs/evaluation/2026-09-app-review/evidence/fix/P3.11
- [todo] P3.12: Gate 2 - advance, four suites, live re-checks
  evidence: docs/evaluation/2026-09-app-review/evidence/fix/P3.12
- merged:

## Phase 4: Settle, then fix

- [todo] P4.1: R-098 - scheduler fairness, instrumented and classified
  evidence: docs/evaluation/2026-09-app-review/evidence/fix/P4.1
- [todo] P4.2: R-099 - the refinement drawer's empty occupation table
  evidence: docs/evaluation/2026-09-app-review/evidence/fix/P4.2
- [todo] P4.3: R-103 - api memory, a leak or a warm cache
  evidence: docs/evaluation/2026-09-app-review/evidence/fix/P4.3
- [todo] P4.4: e2e_13 and M23 - ORCA under load, ENV or CODE
  evidence: docs/evaluation/2026-09-app-review/evidence/fix/P4.4
- merged:

## Phase 5: The remaining S3 and S4 findings

- [todo] P5.1: R-039, R-040, R-043, R-051, R-075, R-080, R-081 - server cost
  evidence: docs/evaluation/2026-09-app-review/evidence/fix/P5.1
- [todo] P5.2: R-044 to R-046, R-052, R-082, R-083, R-087 to R-089 - auth and admin
  evidence: docs/evaluation/2026-09-app-review/evidence/fix/P5.2
- [todo] P5.3: R-064, R-065, R-066, R-067, R-070 - the frontend's own costs
  evidence: docs/evaluation/2026-09-app-review/evidence/fix/P5.3
- [todo] P5.4: R-036, R-037 - the context budget tells the truth
  evidence: docs/evaluation/2026-09-app-review/evidence/fix/P5.4
- [todo] P5.5: R-079 - matplotlib is not called from three threads at once
  evidence: docs/evaluation/2026-09-app-review/evidence/fix/P5.5
- [todo] P5.6: R-100 and the stale specs - the harness stops lying
  evidence: docs/evaluation/2026-09-app-review/evidence/fix/P5.6
- merged:

## Phase 6: Close

- [todo] P6.1: The docs sweep and the doc-claims re-walk
  evidence: docs/evaluation/2026-09-app-review/evidence/fix/P6.1
- [todo] P6.2: Gate 3 - advance, four suites, tear down the test accounts
  evidence: docs/evaluation/2026-09-app-review/evidence/fix/P6.2
- [todo] P6.3: resolution.md, published, and the backlog updated
  evidence: docs/evaluation/2026-09-app-review/resolution.md
- [todo] P6.4: Changelog, handoff, push, republish
  evidence: CHANGELOG.md
- merged:
