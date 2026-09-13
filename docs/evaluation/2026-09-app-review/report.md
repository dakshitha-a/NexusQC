# NexusQC app review, September 2026

**Draft, assembled as the review runs.** This is the narrative report the
triage session reads. It is built from [`findings.md`](findings.md), never
from a session's scrollback, and every count in it is followed by the finding
IDs behind it so a reader can go straight to the evidence. The finding schema,
the severity scale and the list of settled decisions that are deliberately
*not* findings are in [`README.md`](README.md).



## What this was, and the one rule that shaped it

The user asked for a thorough review of the whole application at a single
frozen commit, covering three things at once: bugs, the creature comforts a
chemist using it daily would want, and performance. This is the first of three
stages. The review records findings and does not fix them; a triage session
then assigns a confirmed severity and a decision to each; a third stage, a
fresh tracker, does the fixing.

Findings are recorded and not fixed **on purpose**, and it is worth stating why
because it overrides a standing rule of this repository. Changing the system
under test while measuring it makes the findings on either side of the change
incomparable, which the project's own first backlog tracker established. So for
the duration of this review the "fix any bug you find" rule was suspended, and
every commit touched only `docs/` and `tests/`. The one exception permitted was
anything that blocked the review itself; none was needed.

## The frozen system under test

Everything here is measured against **commit `ca7e0ff`**. The deployment was
brought to it on 2026-09-11 (`scripts/update.sh`, both the api image and the
frontend bundle stamped `ca7e0ff`), and held there for the whole review;
`git diff ca7e0ff..HEAD` over `app server frontend scripts docker nginx` is
empty throughout, so every review commit is docs and tests only and no finding
is attributed to a moving target.

Engine and model versions, recorded so a number can be reproduced: PySCF
2.14.0, ORCA 6.1.1, BAGEL 1.2.2, on the model Ollama holds resident on GPU 0.
This is a shared workstation (255 logical cores, 1 TB RAM, 8x RTX 5000 Ada),
and BAGEL/MKL on it is documented-flaky, which is why some engine paths are
tagged `ENV` rather than measured to completion.

## How the review was done

Four bodies of work, in the order they could run:

1. **A static code audit** (Phase 2), six read-only agents over `server/`, the
   job system, the agent graph, the frontend, the auth layer, and the
   deployment scripts plus a documentation-claims checklist. 104 raw findings,
   merged and de-duplicated to 97. Their full output is committed under
   `evidence/audit/` so the merge is auditable.
2. **A baseline run of the existing suites** (Phase 1) at the frozen commit,
   written up in [`baseline.md`](baseline.md).
3. **A live walkthrough** (Phase 3), surface by surface, as real users through
   a real browser, with the tool trace read back from thread state. Drivers and
   evidence under `evidence/p3/`.
4. **Performance measurements** (Phase 4), each with the command and conditions
   that produced it, in [`perf.md`](perf.md).

Every finding was then verified to the level its `confidence` field records,
which ranges from "confirmed against the live deployment with a real request"
down to "suspected from a code read, not yet reproduced". The verification
respected the user's steer to confirm security-class findings as they landed
and batch the rest.

## The headline findings

These are the ones that would change what a chemist trusts or what an operator
should do before the next deployment. Full detail, repro and evidence for each
is in `findings.md` under the given ID.

### A wrong level of theory, presented as the one requested (R-004)

Asking for L-PDFT silently runs plain single-reference DFT, on the main
submission path, and the approval card the user signs off shows the correct
L-PDFT active space and on-top functional while the job that runs does not use
them. Traced end to end: the registry resolves `lpdft` correctly, but
`_build_spec_or_error` (the builder every ready draft passes through) re-runs
`normalize_method`, whose fuzzy-match cutoff of exactly 0.75 turns `lpdft` into
`dft`; the resulting spec has `method=dft` with the active-space and
`ot_functional=tpbe` params still attached (and ignored), plus a reassuring note
written for a different situation. `pdft`, `l-pdft` and `tddft` collapse the
same way; the two sibling pair-density methods do not, which is what would keep
it unnoticed. Confirmed by executing the builder in process. The fix is a
one-line canonical short-circuit at the second call site; the registry guard
alone does not cover it.

### Cross-user data exposure, proven live (R-001, R-003, R-009)

A brand-new ordinary account, owning nothing, can read and download another
user's completed jobs when those jobs are the children of a batch, scan,
interpolation or ensemble master. Proven end to end: `GET` on the master
returns 404, `GET` on its child returns 200, and the child's full artifact
bundle downloads. The database shows the master has an ownership row and its
children have none. This is a different thing from the settled decision that
unowned legacy jobs are public, and the entry argues that at length so triage
does not close it as one. Two related cross-user reads in `chat.py` (R-003) and
an unscoped knowledge-base search that can surface another user's private
uploaded paper into the model's context (R-009) round out the set.

### A knowledge-base upload that reaches the host (R-002)

The two KB upload routes join a caller-supplied filename into a path with no
sanitisation, and the data directory is bind-mounted into the container, so a
crafted filename lands a file on the host. One reachable target is the file the
host-side deploy runner polls, which runs `update.sh` or `--rollback` without
checking who wrote it. Not live on this host right now (the runner is not
running), but it completes on any deployment using the in-app update feature.
The same module's read path already defends against exactly this.

### Two silent contradictions in the six-hour job cap (R-011, R-012)

Every job is hard-killed at six hours by a timeout that is hardcoded in five
places and settable by no environment variable, against a README that invites
users to close the tab and come back and a design premise of multi-hour CASSCF
runs. Worse, the same six hours behaves in opposite wrong ways depending on
whether the server restarted: on the normal path it kills the job, and on the
restart path it marks a still-running job `failed` and detaches its pid so
cancel can no longer reach it.

### A recurring shape: a safety control applied to one of two sibling paths (R-005)

Five times over, a defence was written, commented, and applied to one place
while its twin was left open: the KB read but not the write, an orbital-cube
route's `gbw` parameter but not its `spin`, that route's download name but not
its filesystem path, the approval-card guard on one state-writer out of seven,
and `check_external=False` on the old submit path but not the new one. Reported
as a habit rather than five patches, because the fix is the habit.

## Findings by severity and class

Generated from `findings.md` by `evidence/summarize_findings.py` so every count
is reproducible and carries its ids. The cleared entry R-102 (a gating concern
raised and dismissed by looking at the drawer) is excluded. Severities are the
coordinator's; triage is where the user confirms or adjusts each.

| | security | bug | perf | docs | comfort | total |
|---|---|---|---|---|---|---|
| S1 | 4 | 4 |  |  |  | 8 |
| S2 | 1 | 22 | 1 | 1 |  | 25 |
| S3 | 3 | 31 | 11 | 6 | 2 | 53 |
| S4 | 1 | 7 |  | 2 | 5 | 15 |
| total | 9 | 64 | 12 | 9 | 7 | 101 |

Confirmed (code-read, executed, or live): 38 of 101. The rest are suspected-from-code-read, for the fix phase to reproduce.

## Ids by severity
- **S1** (8): R-001, R-002, R-003, R-004, R-009, R-010, R-011, R-012
- **S2** (25): R-006, R-007, R-013, R-014, R-015, R-016, R-017, R-018, R-019, R-020, R-021, R-022, R-023, R-024, R-025, R-026, R-027, R-028, R-029, R-030, R-031, R-032, R-033, R-098, R-101
- **S3** (53): R-005, R-008, R-034, R-035, R-036, R-037, R-038, R-039, R-040, R-041, R-042, R-043, R-044, R-045, R-046, R-047, R-048, R-049, R-050, R-051, R-052, R-053, R-054, R-055, R-056, R-057, R-058, R-059, R-060, R-061, R-062, R-063, R-064, R-065, R-066, R-067, R-068, R-069, R-070, R-071, R-072, R-073, R-074, R-075, R-076, R-077, R-078, R-079, R-080, R-081, R-082, R-083, R-099
- **S4** (15): R-084, R-085, R-086, R-087, R-088, R-089, R-090, R-091, R-092, R-093, R-094, R-095, R-096, R-097, R-100

Confirmed (code-read, executed, or live): 38 of 101. The rest are suspected-from-code-read, for the fix phase to reproduce.

### The S1 findings, all confirmed
- R-001 [security, confirmed]: any authenticated user can read and download another user's child jobs
- R-002 [security, confirmed]: a knowledge-base upload can write a file anywhere, and reach the host deploy runner
- R-003 [security, confirmed]: two routes read any user's job into the caller's conversation
- R-004 [bug, confirmed]: asking for L-PDFT silently runs plain DFT
- R-009 [security, confirmed]: The active-space literature search reads every user's private uploaded papers, because it passes `state=None` into the one KB path that exists to scope by owner
- R-010 [bug, confirmed]: ORCA multi-state gradient computes the S0 entry on an excited surface whenever `target_states` does not begin with 1
- R-011 [bug, confirmed]: every job is hard-killed at 6 hours by an undocumented, non-overridable timeout
- R-012 [bug, confirmed]: after 6 h the orphan watcher marks a still-running re-attached worker `failed`, and the status never recovers

## Surface-by-surface narrative

Each surface below carries the findings the audit and the walkthrough placed on
it. The pure-UX surfaces that were not hand-walked to completion say so and point to "What was not tested, and why".

### Multi-user isolation and access control

The strongest-evidence surface, and the one with the most severe findings. Two
live cross-user sweeps as a fresh account that owns nothing established the
shape precisely: **thread isolation holds** (404 on another user's thread and
its job list), **top-level owned jobs are protected** (404 on an owned master),
but **the children of an owned master leak completely** (R-001): a 200 with the
full job record and a full artifact download, because children get no ownership
row and the access check treats a missing row as public. The scheduler already
resolves a child's effective owner one line away, for fairness. Alongside it,
two `chat.py` routes accept another user's job id with no ownership check
(R-003, code-read), the active-space literature search reads across users'
private uploads via `state=None` (R-009), and a knowledge-base upload filename
reaches the host filesystem and the deploy runner (R-002). The auth suite's own
route sweep passes for thread and admin routes; the gaps are all on paths that
sweep does not cover (`job_ids` in a body, a child job id, a KB filename), which
is why a standing suite at 141/142 coexists with four S1 access findings.

### The job system and the engines

Where the wrong-science findings live. Asking for L-PDFT silently runs plain
DFT (R-004, confirmed by executing the normaliser); an ORCA multi-state
gradient can label an excited-state gradient as the ground state (R-010,
confirmed by generating the input); the six-hour cap kills long jobs and, after
a restart, mislabels a running one as failed (R-011, R-012); open-shell
oscillator strengths are parsed with a singlet-only pattern (R-030); and the
registry offers ten task/method/engine cells the runners refuse (R-028,
confirmed by executing `supports`/`route_engine`). The fair scheduler's
round-robin admission gave one user two slots before another's first on an idle
stack, which the suite's own README said could not happen (R-098, cause between
a real regression and a test race still to settle).

### Drafting, elicitation and the approval gate

The approval gate's integrity findings are code-read confirmed: an open card is
silently destroyed by any of six molecule-panel state writes (R-017, the guard
exists on a seventh), the `run_when_ready` path can drop a ready card on click
(R-013), and a mixed tool batch can submit with no confirmation (an S3). The
agent also unreliably reaches the card at all for excited-state, ensemble and
some complex jobs (R-101, deterministic for the wigner ensemble across three
retries). The live drafting walkthrough (P3.3) drove these: it confirmed R-004 end to
end (the L-PDFT card showed the correct active space, then the shared builder
was shown to emit a DFT spec) and observed the agent reaching cards unreliably
for the heavier job families (R-101).

### Results viewers and plots

The CAS refinement drawer renders its rotation trail but zero rows in the
natural-orbital occupation table (R-099), the likely lead being a section gated
on a `refined_*` summary key the runner does not publish. The e2e-UI suite also
flagged drawer-section gating (ui_02) and orbital-cube rendering plus a
scrubber-drag re-render count (ui_09); the job-matrix walkthrough (P3.4) cleared ui_02 by
looking at the HF single-point drawer directly (R-102): it shows the correct
sections, and the earlier gating signal was a whole-page-body scan picking up
chat text. R-099 (the refinement drawer's empty occupation table) stands, with
its code lead recorded. ui_09's viewer questions are the one viewer surface not
fully re-driven, since the matrix driver's job tracking broke. Frontend audit findings on this surface: every
3Dmol viewer pins listeners to `document.body`/`window` that are never released
(a WebGL-context leak, R-family in the frontend audit), and three of four
multi-frame viewers lack the `response.ok`/`.catch` the fourth has.

### Deployment, update and backup

Read-only audit only (the review never runs `install.sh`/`update.sh` against
its own stack beyond the frozen bring-up). `update.sh --rollback` never moves a
branch checkout and stamps the image with the old commit (R-019); `update.sh`
exits 0 when the deployment never came up healthy (R-020); `backup.sh --full`
omits `data/plots`, `data/projects.json` and `data/scraped`, the last of which
its own header cites as making the KB reproducible (R-021, and the review took a
full manual archive before the update because of it); `restore.sh` swallows
`pg_restore`'s exit status and reads the wrong database (R-022); the update
traps only EXIT, so Ctrl-C during the drain can leave the deployment in
maintenance (R-023); and `/deploy-status/runner.json` leaks the host path
unauthenticated (R-008).

### Documentation accuracy

The 252-claim checklist (`evidence/doc-claims.md`) drives P3.11. Fifteen claims
were already falsifiable from code, including a `DEPLOYMENT.md` bootstrap
command missing two required arguments (R-026), a welcome screen telling users
BAGEL can run scans the registry refuses, and `CONFIGURATION.md` documenting
parameters and subtypes retired by the CAS rebuild. The live doc walkthrough
confirms each against the running app.

### First contact, molecules, projects, sharing, admin, layout

These pure-UX surfaces were not each hand-walked to completion; see "What was
not tested, and why". Their findings rest on the frontend static audit and the
e2e-UI baseline (P1.4): the KB search moved behind a toggle, the admin overview
still references the removed public listener, several row-selection controls are
mouse-only (a keyboard-accessibility comfort finding), and the composer draft
follows the user between conversations. The drivers to walk each surface live
are written and committed under `evidence/p3/` for a follow-up pass or the fix
phase to run.

## Performance

Full method and numbers in [`perf.md`](perf.md). Headline: at the resting job
count everything is single-digit-to-low-tens of milliseconds, but the O(n)
list-route findings are real, measured across two points. `GET /api/jobs` goes
from 5.5 ms at 8 jobs to 20.9 ms at 58 (near-linear) and is polled every 4 s per
tab, so a deployment with a few hundred jobs would see it in the ~100 ms range
per poll; `/api/admin/activity` and `/api/admin/storage` grow more gently, and
the hot `/api/threads/{id}/state` is flat in job count. Warm time-to-first-token
is unchanged from the 2026-09-06 baseline (~2.5 s median), as expected for a
frozen commit. The gzipped bundle is 2.07 MB total with ~400 KB eager; the 7.6
MB Ketcher chunk is correctly lazy-loaded.

## What was not tested, and why

Stated plainly so the report does not overclaim its coverage.

- **BAGEL job completion.** BAGEL/MKL on this host is documented-flaky
  (`CLAUDE.local.md`): 80-96 s per CASSCF macro-iteration, occasional
  `dsyev`/`pdsyevd` crashes. BAGEL cells were exercised for dispatch and input
  but not driven to convergence; findings on BAGEL paths are code-read or
  dispatch-level, and two suite anomalies on ORCA/BAGEL under load (e2e_13's
  probe, e2e_08's M23 exit-2) are flagged for isolated re-runs rather than
  labelled, per the ENV discipline.
- **The full UX browser walkthrough.** The live isolation sweep (P3.9),
  drafting (P3.3) and the job-matrix drawers (P3.4) were driven and are the
  basis of the security, science and viewer findings. The remaining pure-UX
  surfaces (first contact, molecule entry, projects, sharing, admin visuals,
  layout at width, the job manager under load) have written drivers under
  `evidence/p3/` but were not each driven to completion: the browser drivers
  proved fragile (a job-tracking bug in the matrix driver cost ~50 minutes of
  timeouts), and these surfaces are already covered by the e2e-UI baseline
  (P1.4), the frontend static audit, and the drawer screenshot. Their findings
  therefore rest on the audit and the standing UI specs rather than a fresh
  hand-walk, and that is the one place this review is thinner than a clean-room
  pass would be.
- **Browser-side performance** (per-tab request count, JS heap growth over
  time, live WebGL context count) was deferred with those drivers; the
  server-side polling cost is captured in `perf.md` instead.
- **Comfort findings from real use.** The friction log
  (`friction-log.md`) is the user's to fill from their own daily use; it was
  empty at the time of writing, so the seven comfort findings here come from
  the audit and the walkthrough, not from a chemist's lived friction. That log
  is where the richest comfort findings will come from, and it stays open.

## A first-cut fix order for triage

Not a decision, a starting point for the triage session. S1 first, and within a
tier the smallest, most contained fixes first.

1. **R-004 (L-PDFT runs as DFT).** The single most important fix: a wrong level
   of theory presented as correct, on the main path, and the fix is a one-line
   canonical short-circuit at `tools.py:1187`. Do this first.
2. **R-001 (child jobs world-readable).** Give the access check the
   `parent_job_id` owner walk the scheduler already uses. Small, contained,
   and it closes a live cross-user read.
3. **R-002 (KB filename to host) and R-003 (chat.py job reads).** Filename
   sanitisation the read path already models, and the missing
   `check_owner_or_admin` the sibling route already has. Both small.
4. **R-010, R-011, R-012 (ORCA gradient label; the six-hour cap and its
   restart-path contradiction).** Wrong numbers and broken leave-and-return;
   each is a localised fix.
5. **R-009, R-006, R-007 and the rest of the S2 security/reliability set.**
6. **R-005 as a habit.** Sweep the five one-of-two-paths sites together.
7. The S3/S4 tail, and the perf O(n) routes (R-045 and the list routes) when a
   deployment's job count makes them worth it.

The register carries a fuller `scope` and fix direction on each entry; several
S3/S4 items are one-line test or doc fixes (R-100, R-026) that could ride along
cheaply.
