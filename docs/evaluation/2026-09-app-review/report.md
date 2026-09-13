# NexusQC app review, September 2026

**Draft, assembled as the review runs.** This is the narrative report the
triage session reads. It is built from [`findings.md`](findings.md), never
from a session's scrollback, and every count in it is followed by the finding
IDs behind it so a reader can go straight to the evidence. The finding schema,
the severity scale and the list of settled decisions that are deliberately
*not* findings are in [`README.md`](README.md).

Sections marked _(pending)_ are filled as their phase completes.

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
   written up in [`baseline.md`](baseline.md). _(pending)_
3. **A live walkthrough** (Phase 3), surface by surface, as real users through
   a real browser, with the tool trace read back from thread state. Drivers and
   evidence under `evidence/p3/`. _(pending)_
4. **Performance measurements** (Phase 4), each with the command and conditions
   that produced it, in [`perf.md`](perf.md). _(pending)_

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

`normalize_method('lpdft')` returns `'dft'`. Asking for L-PDFT, the multi-state
MC-PDFT variant the capability documentation steers people toward, silently
runs plain single-reference DFT instead, and attaches a reassuring note written
for a different situation so the substitution reads as harmless. The cause is a
fuzzy-match cutoff of exactly 0.75 firing on a method name that was never a
typo. `pdft`, `l-pdft` and `tddft` collapse the same way; the two sibling
pair-density methods do not, which is what would keep it unnoticed. Confirmed by
running the function.

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

Counts are provisional until the triage severity pass (P5.4); the audit agents'
own severities are used where the coordinator has not yet re-rated. Every count
lists its IDs so nothing is a bare number.

_(the full table is generated at P6.1 from findings.md; a draft count as of the
last commit is 97 findings: 9 S1, 24 S2, 51 S3, 14 S4; by class 61 bug, 14
security, 12 perf, 9 docs, 7 comfort. The verified subset and the exact ID
lists land here at P6.1.)_

## Surface-by-surface narrative

Each surface below carries the findings the audit and the walkthrough placed on
it. Surfaces still being walked are marked _(walkthrough in progress)_.

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

### Drafting, elicitation and the approval gate _(walkthrough in progress)_

The approval gate's integrity findings are code-read confirmed: an open card is
silently destroyed by any of six molecule-panel state writes (R-017, the guard
exists on a seventh), the `run_when_ready` path can drop a ready card on click
(R-013), and a mixed tool batch can submit with no confirmation (an S3). The
agent also unreliably reaches the card at all for excited-state, ensemble and
some complex jobs (R-101, deterministic for the wigner ensemble across three
retries). The live drafting walkthrough (P3.3) reconfirms these and R-004
through the real UI.

### Results viewers and plots _(walkthrough in progress)_

The CAS refinement drawer renders its rotation trail but zero rows in the
natural-orbital occupation table (R-099), the likely lead being a section gated
on a `refined_*` summary key the runner does not publish. The e2e-UI suite also
flagged drawer-section gating (ui_02) and orbital-cube rendering plus a
scrubber-drag re-render count (ui_09); the job-matrix walkthrough (P3.4) settles
all three with per-job evidence. Frontend audit findings on this surface: every
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

### First contact, molecules, projects, sharing, admin, layout _(walkthrough in progress)_

## Performance

_(pending Phase 4; see perf.md)_

## What was not tested, and why

_(pending; will record the engine paths left at ENV, anything the frozen
single-user data set could not exercise, and any surface time-boxed short.)_

## A first-cut fix order for triage

_(pending P5.4; S1 first, then by containment. Draft: the L-PDFT substitution
and the child-ownership gap are the two that most directly threaten a
scientific result and are both small, contained fixes.)_
