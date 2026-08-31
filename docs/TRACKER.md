# Tracker: clearing the backlog, and two job-manager controls

**In motion as of 2026-08-31.** The `merged:` row on each phase records the
commit it landed as, and is `-` until the phase is done.

It stays here rather than moving to [`trackers/`](trackers/) until the next
plan starts, which is when it gets archived and a fresh tracker takes its
place. **Exactly one tracker is active at a time.**

## How tracking works here

Development is linear, so there is never a reason to have two trackers open at
once. Each plan, feature or non-trivial request gets its own tracker, this file
is whichever one is currently in motion, and when its plan is finished the file
is closed out and moved to [`trackers/`](trackers/), then a fresh one starts
here for whatever comes next.

Closed trackers are kept, never deleted. They are the audit trail for why the
code looks the way it does, and code comments cite them by path. The one this
replaces is
[`trackers/2026-08-project-archives.md`](trackers/2026-08-project-archives.md)
-- 18 steps across 6 phases, closed 2026-08-31.

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

Asked what was left in the tracker and the backlog, the answer was: nothing in
the tracker, and five open items in the backlog. Four of those had been written
down during the project-archive work rather than acted on, which is what the
backlog is for, and the fifth predates it. The instruction was to fix all five
and to postpone only the public-release items, which are tracked separately and
are not in this list.

Two job-manager controls were asked for in the same breath, both about the
panel being cramped: the search box and the "Show archived" toggle sit on
separate lines when they could share one, and a selection of jobs can be added
to a project or attached to a prompt but not simply cleared.

The five backlog items, in the order they are tackled:

1. `tests/frontend/ui_06_row_and_viewer_controls.spec.mjs` fails a containment
   check whose message prints only the horizontal bounds, so what actually
   fails is invisible from the output.
2. `tests/backend/tax_02_job_rows.py` leaks one job directory per run, because
   its cleanup block runs before the last section that creates a job.
3. `GET /api/auth/download-my-data` still assembles an entire account in
   memory, which is a larger version of the problem the project download was
   written to avoid, and the fix for it now exists.
4. The collapsed left rail's icons are decorative, so a collapsed rail shows
   what sections exist and reaches none of them.
5. Something in the app roughly doubles the model server's own concurrency
   penalty. This is the only one that is an investigation rather than a fix,
   and it is deliberately last.

## Phase 1: The two test-hygiene bugs

- [done] P1.1: ui_06 measures what it claims to, and says so when it fails
  evidence: tests/frontend/ui_06_row_and_viewer_controls.spec.mjs → "21/21, was 20/21. Both panel-containment checks now scroll the control into view before measuring, so the result no longer depends on how many jobs the deployment happens to carry: these panels scroll vertically by design, and the seeded row had fallen below the fold. The failure message prints both axes, which is why a vertical failure used to read as a passing horizontal measurement next to a FAIL"
- [done] P1.2: tax_02 cleans up the job it makes last
  evidence: tests/backend/tax_02_job_rows.py → "21/21 and the job-directory count is unchanged across a run, previously +1 every time. The sweep over MADE was the FIRST statement in the finally block, and the non-finite-number section runs inside that same block after it, so the fixture it creates was never swept. Moved to the end of the block"

- merged: -


## Phase 2: The account export stops buffering

- [todo] P2.1: download-my-data streams, with the archive unchanged

- merged: -


## Phase 3: The two job-manager controls

- [todo] P3.1: Search and Show archived share one line
- [todo] P3.2: A selection can be cleared

- merged: -


## Phase 4: The collapsed rail reaches its sections

- [todo] P4.1: Each collapsed-rail icon opens the section it names

- merged: -


## Phase 5: The concurrency penalty

- [todo] P5.1: Find what the app adds on top of the model server's own penalty
- [todo] P5.2: Fix it, or write down precisely what it is

- merged: -
