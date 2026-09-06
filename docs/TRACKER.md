# Tracker

One plan is tracked here at a time, and right now there is none in motion.

This file holds the active plan while it is being worked. When the plan
finishes it moves to [`trackers/`](trackers/) under a dated name, and this file
goes back to what you are reading. A new feature or request starts a fresh
tracker rather than being appended to a closed one; a closed tracker is a
record of what was decided and why, and reopening it to hold unrelated work
destroys that.

The most recent plan to close was the CAS engine closeout, archived as
[`trackers/2026-09-cas-engine-closeout.md`](trackers/2026-09-cas-engine-closeout.md).
It ran to 43 steps across fifteen phases, and its write-up is
[`CAS_ENGINE_METHOD.md`](CAS_ENGINE_METHOD.md), rewritten from the measurements
that closed it.

Three things it leaves behind are worth knowing before starting the next one.

**`docs/BACKLOG.md` carries nothing about the CAS engine.** Ten entries closed
together, each through one of three doors: fixed and validated across the
benchmark, settled as a deliberate decision, or measured and written into the
method document as a stated limitation with its number attached. Two of the ten
turned out to be wrong about their own subject, which is the argument for
closing a related set together rather than one at a time.

**A benchmark set with no committed ledger is a set nobody is reading.**
`--set stability` had existed for a whole campaign and its output had only ever
gone to a terminal. The first time it was committed it showed six molecules
failing rotation invariance, which is the property the engine's geometric
perception exists to provide, and had been failing for at least as long as
anyone had been looking elsewhere. That limitation is now in the method
document with its number, and it is the sharpest thing left open about this
engine.

**Every ledger records the commit, the wall time and the thread counts.** The
last of those is not decoration: a state average can converge to more than one
solution and which one a run reaches is decided by reduction order in threaded
linear algebra, so a row that moved between runs cannot be explained without it.

`scripts/check_tracker.py` validates whatever is here. It accepts this file as
it stands, with no steps to check.
