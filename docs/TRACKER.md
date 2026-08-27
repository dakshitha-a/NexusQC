# Active Tracker: none

No plan is currently in motion. **Exactly one tracker is active at a time**, and
this file is it; when work starts, this file becomes that plan's tracker.

## How tracking works here

Development is linear, so there is never a reason to have two trackers open
at once. Each plan, feature or non-trivial request gets its own tracker, this
file is whichever one is currently in motion, and when its plan is finished
the file is closed out and moved to [`trackers/`](trackers/), then a fresh one
starts here for whatever comes next.

Closed trackers are kept, never deleted. They are the audit trail for why the
code looks the way it does, and code comments cite them by path.

A step is `todo`, `in-progress` or `done`. A `done` step carries an evidence
line naming a script or command that a reader can run, and
`scripts/check_tracker.py` verifies the named path really exists. A phase
records its merge hash only once every step in it is done.

## The two most recent closures

- [`trackers/2026-08-evaluation-battery-run-2.md`](trackers/2026-08-evaluation-battery-run-2.md)
  the second full run of the manuscript evaluation battery, from a mandatory
  card audit through execution to the two fixes it earned. 20 steps across six
  phases, closed 2026-08-27. The audit was the load-bearing part: eight of the
  83 cards were wrong in ways that would each have cost trials mid-run. Results
  in `rsc_digital_discovery/evaluation/`, in three sheet sets that are never
  pooled because each describes a different tree.
- [`trackers/2026-08-clearing-the-backlog.md`](trackers/2026-08-clearing-the-backlog.md)
  everything the manuscript evaluation battery found, plus the older items that
  had been carried forward without an owner. 28 steps across nine phases,
  closed 2026-08-26. Two steps were closed by removing the thing rather than
  verifying it -- the public `:443` listener and its kill switch -- and two
  were carried forward to the backlog rather than marked done.

The rest of `trackers/` follows the same shape; each names its own scope in
its first paragraph.
