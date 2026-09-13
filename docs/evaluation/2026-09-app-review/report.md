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

_(pending Phase 3)_

## Performance

_(pending Phase 4; see perf.md)_

## What was not tested, and why

_(pending; will record the engine paths left at ENV, anything the frozen
single-user data set could not exercise, and any surface time-boxed short.)_

## A first-cut fix order for triage

_(pending P5.4; S1 first, then by containment. Draft: the L-PDFT substitution
and the child-ownership gap are the two that most directly threaten a
scientific result and are both small, contained fixes.)_
