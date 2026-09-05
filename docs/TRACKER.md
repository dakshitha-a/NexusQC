# Tracker

One plan is tracked here at a time, and right now there is none in motion.

This file holds the active plan while it is being worked. When the plan
finishes it moves to [`trackers/`](trackers/) under a dated name, and this file
goes back to what you are reading. A new feature or request starts a fresh
tracker rather than being appended to a closed one; a closed tracker is a
record of what was decided and why, and reopening it to hold unrelated work
destroys that.

The most recent plan to close was the CAS engine audit, archived as
[`trackers/2026-09-cas-engine-audit.md`](trackers/2026-09-cas-engine-audit.md).
It ran to 43 steps across eleven phases, and its write-up is
[`CAS_ENGINE_METHOD.md`](CAS_ENGINE_METHOD.md).

Two things it left behind are worth knowing before starting the next one.
`docs/BACKLOG.md` gained two entries from it, one of which, the two-solution
state average, is a live user-facing issue rather than a nicety. And it
established a rule the next tracker should inherit: a change to what the engine
perceives is a change to everything downstream of it, and that includes the
measurements, not only the results. Three numbers in the audit's own write-up
were taken before a perception fix and had to be re-measured at the end; one of
them turned out to have been wrong about its cause rather than merely stale.

`scripts/check_tracker.py` validates whatever is here. It accepts this file as
it stands, with no steps to check.
