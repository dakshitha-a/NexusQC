# Tracker: none active

**No plan is in motion as of 2026-09-01.** This file is a placeholder, and it
exists rather than being deleted for two reasons: `scripts/check_tracker.py`
requires it, and its absence would read as "tracking was abandoned" rather than
"the last plan finished and nothing has started".

The one this replaces is
[`trackers/2026-08-plotter-and-casscf-intensities.md`](trackers/2026-08-plotter-and-casscf-intensities.md)
-- 29 steps across 5 phases, closed 2026-09-01.

## How tracking works here

Development is linear, so there is never a reason to have two trackers open at
once. Each plan, feature or non-trivial request gets its own, this file is
whichever one is currently in motion, and when its plan is finished the file is
closed out and moved into [`trackers/`](trackers/), then a fresh one starts
here for whatever comes next.

Closed trackers are kept, never deleted. They are the audit trail for why the
code looks the way it does, and code comments cite them by path, so moving one
has to bring those references with it.

## Starting the next one

Replace this file wholesale. A new tracker needs a title saying what the plan
is, a paragraph on what prompted it, phases with numbered steps, and the rules
block below, which is what `scripts/check_tracker.py` reads.

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
