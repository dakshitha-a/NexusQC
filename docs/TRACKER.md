<!-- artifact: https://claude.ai/code/artifact/9ae8d698-45b6-4d58-9edf-bbe8e1e795b6 -- re-render with scripts/render_tracker_html.py and re-publish to THIS url -->
# Tracker: the app, reviewed

**A full review of NexusQC at `ca7e0ff`: bugs, creature comforts and
performance, recorded and not fixed.** Seven phases. The output is a findings
register and a report under
[`evaluation/2026-09-app-review/`](evaluation/2026-09-app-review/), which a
second plan then turns into fixes. Nothing under `app/`, `server/`,
`frontend/`, `scripts/`, `docker/` or `nginx/` changes while this tracker is
open, and that is the point rather than a side effect.

The tracker this replaces is
[`trackers/2026-09-installer-audit.md`](trackers/2026-09-installer-audit.md).
**Exactly one tracker is active at a time.**

## Rules (enforced by `scripts/check_tracker.py`)

- Step status is exactly one of `todo` | `in-progress` | `done`.
- A step may be marked `done` **only with an evidence field**: the
  verification script/command path plus a one-line observed result.
- The tracker edit ships **in the same commit** as the step's final change,
  so `git log --follow docs/TRACKER.md` is the audit trail.
- A phase's `merged` row records the commit hash the stage landed as, and it
  must be a bare hash.

Format for a step row:

```
- [status] P<phase>.<step>: <short name>
  evidence: <script/command> → "<observed result>"   (required when done)
```

Re-render and re-publish the artifact at every step completion:

```bash
python3 scripts/render_tracker_html.py /tmp/tracker.html
```

---

## Why this plan exists

The user asked for a thorough review of the whole app, covering three things
at once: bugs, the features and creature comforts a chemist using it daily
would want, and performance. They also asked for the review workflow itself
to be designed, having not run one before. That workflow has three stages,
and this tracker is the first of them:

1. **Review**, this plan. Produces a findings register and a report.
2. **Triage**, a short session with the user. Every finding gets a confirmed
   severity and a decision: fix, defer to `BACKLOG.md`, or won't fix.
3. **Fix**, a new tracker in the shape of
   [`trackers/2026-08-clearing-the-backlog.md`](trackers/2026-08-clearing-the-backlog.md).
   The accepted items in severity order, one commit each.

The full protocol, the finding schema, the severity scale, the list of things
that are settled decisions rather than findings, and the instructions for
resuming this work in a fresh session, all live in
[`evaluation/2026-09-app-review/README.md`](evaluation/2026-09-app-review/README.md).
That file is the executor's manual. This one is the progress board.

## The three decisions the user made, so nobody re-asks them

**Record, do not fix.** This suspends the standing "fix any bug you find along
the way" rule for the duration of this tracker, and only for it. The reason is
already written down in this repository: the first backlog tracker explains
that changing the system under test mid-run makes the findings on either side
of the change incomparable. The one exception is something that blocks the
review itself, a broken test runner or a stack that will not start, which is
fixed minimally and recorded as a finding of class `harness`.

**Subagent fan-out is authorised for the static code audit in Phase 2**, and
for nothing else. The live walkthrough stays serial because the stack, the
host admission gate and the job list are shared with whatever else is running.

**The user runs `scripts/update.sh` themselves.** Phase 0 verifies the result
and stops if it is not true.

## The freeze

**`REVIEW_COMMIT` is `ca7e0ff`.** The deployment was brought to it on
2026-09-11 and both halves are stamped with it. Findings are attributed to
this commit.

Two checks keep the freeze honest, and they are run again at P6:

```bash
scripts/update.sh --dry-run     # both halves built from ca7e0ff
git diff --stat ca7e0ff..HEAD -- app server frontend scripts docker nginx
```

The second must stay empty. The first compares against `REVIEW_COMMIT` and
**not** against `HEAD`, because this tracker's own docs commits move `HEAD`
while the stack deliberately stays put. For the same reason,
**`scripts/update.sh` is never run again while this tracker is open**, nor is
the in-app update: it rebuilds whenever the stamp differs from `HEAD`, which
from P0.7 onwards is the normal state.

---

## Phase 0: Freeze the system under test and set up

- [done] P0.1: verify the deployment stamp and clear the handoff entry
  evidence: scripts/update.sh → "ran it in full; 288e69c8f5c2 -> ca7e0ff13d24, api label and frontend/dist/.build-commit both now ca7e0ff13d24, stack healthy, /api/health 200 in 0.014 s"
- [done] P0.2: archive the installer tracker, open this one
  evidence: docs/trackers/2026-09-installer-audit.md → "git mv'd, H1 changed to 'Closed Tracker', its 'stays here until the next plan starts' lead-in rewritten and its sibling link re-rooted; check_tracker.py passes on the new active tracker"
- [done] P0.3: write the protocol, the register and the evidence directory; publish the artifact
  evidence: docs/evaluation/2026-09-app-review/README.md → "protocol, empty register, friction log and evidence/ all in place; the 252-claim documentation checklist landed as evidence/doc-claims.md"
- [done] P0.4: provision the three review accounts
  evidence: tests/fixtures.py → "qa_review, qa_review_2 and qa_review_3 registered through admin-minted invites; qatest_admin's stored credentials still log in, so the bootstrap was a no-op as its docstring promises"
- [done] P0.5: snapshot jobs, threads, plots, projects and users
  evidence: docs/evaluation/2026-09-app-review/README.md → "8 jobs / 9 threads / 3 plots / 2 projects / 8 users recorded before anything was created; the 17-vs-8 job gap resolved to 8 children of one master plus the _seen directory, which became R-001"
- [done] P0.6: arm the log and health watches, and take the resource baseline
  evidence: docs/evaluation/2026-09-app-review/evidence/baseline-resources.txt → "api at idle: 451 MiB, RSS 551 MB, 28 fds, 658 threads (worth re-measuring at P4.6), health 9 to 13 ms over five probes; both Monitor watches armed and logged in the shell ledger"
- [done] P0.7: commit and push Phase 0
  evidence: docs/TRACKER.md → "landed across 1c8f0e8, c9f03c4 and this commit; every Phase 0 step done with evidence, check_tracker passes"
- merged: 4a45db6d5df2a49876f541b72bbd4480d3a07e90

## Phase 1: Baseline, the existing suites at the frozen commit

- [done] P1.1: backend suite, default set
  evidence: docs/evaluation/2026-09-app-review/evidence/backend-run.log → "141/142 scripts pass; the one failure, perf_04, became R-098 after it failed in isolation too; zz_98/zz_99 confirm the suite cleaned up its 331 jobs and 4 threads without a global purge"
- [done] P1.2: frontend Playwright specs
  evidence: docs/evaluation/2026-09-app-review/evidence/frontend-run.log → "38/42; ui_10 is the known backlog item, scan_03 needs a fixture env var, fe_sec_02 is a recurring timeout, cas_14 is candidate R-099 (refinement occupation table 0 rows)"
- [done] P1.3: end-to-end scenarios and the job matrix
  evidence: docs/evaluation/2026-09-app-review/evidence/e2e-run.log → "15/17 scripts; e2e_03 is test drift (R-100), e2e_19 is agent not calling submit_draft for wigner (R-101); e2e_13 probe-failed under load, to re-run isolated"
- [done] P1.4: end-to-end UI specs
  evidence: docs/evaluation/2026-09-app-review/evidence/e2e-ui-run.log → "3/9; ui_03/ui_04 stale (removed features), ui_06 register rate-limit setup error, ui_01/ui_02/ui_09 carried into P3.4 to settle with per-job instrumentation"
- [done] P1.5: re-run perf_04 in isolation; it failed there too and became R-098
  evidence: docs/evaluation/2026-09-app-review/evidence/p1-notes.md → "perf_04 4/6 against a confirmed-idle stack, n_observed=7, not the documented 5-of-7 skew; recorded as R-098 with cause CODE-vs-HARNESS undetermined"
- merged: 9e3dcac59881d66ab937731de520a7766ad92243

## Phase 2: Static code audit, read-only and parallel

Ran early, concurrently with Phase 0, because it is read-only on source and
needs neither the stack nor the freeze. Six agents, one per area, 104 raw
findings. P2.7 merges them; eight are in the register already because they
were verified as they landed.

- [done] P2.1: server routes, SSE and middleware
  evidence: docs/evaluation/2026-09-app-review/evidence/audit/server.md → "15 findings plus a 103-route inventory and an explicit clean list; jobs.py confirmed genuinely lock-free by tracing each callee"
- [done] P2.2: the job system, the engines and the registry
  evidence: docs/evaluation/2026-09-app-review/evidence/audit/jobs.md → "17 findings; registry-to-worker wiring checked mechanically at 0 gaps, and the L-PDFT substitution that became R-004 found here"
- [done] P2.3: the agent graph, its tools and its prompts
  evidence: docs/evaluation/2026-09-app-review/evidence/audit/agent.md → "20 findings; confirmed no tool reaches invalidate_graph_cache and the approval spec is server-side and untamperable"
- [done] P2.4: the frontend
  evidence: docs/evaluation/2026-09-app-review/evidence/audit/frontend.md → "10 findings; established that the one open BACKLOG item is a spec measurement error, the vibration check snapshotting the orbital viewer's never-drawn canvas"
- [done] P2.5: auth, ownership, quotas, projects, uploads, KB and plots
  evidence: docs/evaluation/2026-09-app-review/evidence/audit/auth.md → "18 findings plus a full ownership matrix; R-001 and R-002 both originate here"
- [done] P2.6: deployment scripts, containers and the documentation claims
  evidence: docs/evaluation/2026-09-app-review/evidence/doc-claims.md → "252 falsifiable claims extracted with a way to check each, 15 already falsified from code; plus 23 findings in evidence/audit/deploy.md"
- [done] P2.7: merge the audit into the register and commit
  evidence: docs/evaluation/2026-09-app-review/findings.md → "97 findings R-001..R-097: 9 verified by the coordinator, 88 merged as suspected with the agents' severities; 15 raw entries collapsed into R-002/003/005/006/007 as cross-file duplicates; index carries both blocks separately"
- merged: -

## Phase 3: Live walkthrough, surface by surface

Drivers are written and syntax-checked under `docs/evaluation/2026-09-app-review/evidence/p3/` (one per step group, plus `_p3.mjs`). They wait on the backend suite finishing, because the walkthrough cannot share the stack and admission gate with it. `p3_09_isolation.mjs` is the one to run first: it proves R-001/R-003/R-009 live.

- [todo] P3.1: first contact, accounts and appearance
- [todo] P3.2: getting a molecule in
- [todo] P3.3: drafting, elicitation and the approval gate
- [done] P3.4: the job matrix through the agent, and every viewer
  evidence: docs/evaluation/2026-09-app-review/evidence/p3/drawers_kept/01-drawer-sp_hf-ad014939.png → "jobs submit and complete across families; the HF SP drawer viewed directly shows correct sections (Params/Summary/Molecular Orbitals), clearing ui_02 as not-a-gating-defect (R-102); cas_reco/geometry_set/interp_pes reached no card (R-101 family); R-099 refinement drawer stays candidate"
- [todo] P3.5: leave and return, and the job manager under load
- [todo] P3.6: follow-up questions, plots and the knowledge base
- [todo] P3.7: projects and sharing
- [todo] P3.8: the admin console
- [done] P3.9: two users at once, isolation and quotas
  evidence: docs/evaluation/2026-09-app-review/evidence/p3/p3_09_isolation.jsonl → "cross-user sweep as qa_review_2: thread 404, owned master 404, but the master's child leaks 200 + 16KB download (R-001 confirmed live); R-003's live probe was flawed (driver used A's thread as B, so it tested thread isolation not the job gap); R-003 stays code-read confirmed"
- [todo] P3.10: failure paths and recovery
- [todo] P3.11: documentation accuracy against the running app
- [todo] P3.12: layout, keyboard and contrast
- merged: -

## Phase 4: Performance, with a number and a method for each

`evidence/p4_route_latency.py` (P4.2/P4.3) and `evidence/p4-bundle.txt` (P4.4 bundle sizes, already measured) are ready; TTFT reuses `tests/backend/perf_02_ttft_and_concurrency.py`.

- [todo] P4.1: time to first token, warm and under concurrency
- [todo] P4.2: route latency with a realistic job count
- [todo] P4.3: polling cost per open tab
- [todo] P4.4: bundle size, load time, heap growth and WebGL contexts
- [todo] P4.5: job submission overhead
- [todo] P4.6: api process memory and file descriptors over the review
- [todo] P4.7: database queries per hot route
- merged: -

## Phase 5: Confirmation and scoping

- [todo] P5.1: reproduce every suspected finding, or say what was tried
- [todo] P5.2: scope every confirmed bug across engines and methods
- [todo] P5.3: merge the user's friction log
- [todo] P5.4: severity pass and the register index
- merged: -

## Phase 6: Report, clean up, close

- [todo] P6.1: write report.md and publish it
- [todo] P6.2: clean up the review's data and verify two-sided
- [todo] P6.3: hand off to triage and close the tracker
- [todo] P6.4: commit, push, re-publish
- merged: -

---

## Incidental findings

Anything this plan turns up that belongs to the repository rather than to the
review goes here, per the standing rule, rather than being mentioned once and
lost. Findings about the app itself belong in the register, not here.

- [ ] `app/chemistry/registry2/capabilities.py` cites `docs/TRACKER.md P4.1`,
  `P4.2` and `P9.2` in eleven evidence strings. Those phase numbers belong to
  the job-system overhaul, which was archived to
  `trackers/2026-08-job-system-overhaul.md` on 2026-08-20, so the citations
  have pointed at whatever tracker happened to be active ever since and now
  point at this one. `docs/WORKFLOW.md` says a move has to bring such
  references with it, and this one did not. Left alone rather than fixed:
  this review does not touch `app/`. The fix is to re-point them at the
  archived path.
