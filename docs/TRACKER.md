# Tracker

One plan is tracked here at a time, and right now there is none in motion.

This file holds the active plan while it is being worked. When the plan
finishes it moves to [`trackers/`](trackers/) under a dated name, and this file
goes back to what you are reading. A new feature or request starts a fresh
tracker rather than being appended to a closed one; a closed tracker is a
record of what was decided and why, and reopening it to hold unrelated work
destroys that.

The most recent plan to close was the CAS engine closeout and the
repository-wide suite audit that followed it, archived as
[`trackers/2026-09-cas-closeout-and-suite-audit.md`](trackers/2026-09-cas-closeout-and-suite-audit.md).

Four things it leaves behind are worth knowing before starting the next one.

**`docs/BACKLOG.md` is empty.** The last entry to close was the app-versus-host
latency split, which had stood not because nobody had looked but because its
denominator could not be measured against a card shared with other tenants. It
was settled by a fact about the host rather than a change to the code: GPU 0
here is reserved for NexusQC and Ollama serves only NexusQC, so the baseline is
measurable. The lesson generalises. An entry that says a thing cannot be
measured is worth re-reading whenever the environment changes.

**A test suite can destroy the data it runs against, and a cleanup check can be
blind to it.** A full backend run took the stack from 275 jobs to 1, through two
scripts calling `purge_all_jobs` that were never added to the runner's
exclusion list. The check meant to catch it compared only what a run added
against the baseline, a one-sided difference that cannot see what a run
removed, and it reported PASS while printing "39 job(s) pre-existed, 10 present
now". Both cleanup scripts now assert the other direction. Derive that
exclusion list from `grep -l "admin/purge/jobs" tests/backend/*.py` rather than
from memory of which script it was.

**Suites drift silently, and the drift is not always in the direction you
expect.** This pass found a test asserting a magic count that had moved, a
matrix cell naming a subtype removed three days earlier, a spec that reported
failure while passing all its checks because `process.exit(summary())` passes a
boolean, a spec asserting on data it never seeded, and a matrix requiring a tool
the system prompt tells the agent not to call. None was a defect in the
product; all of them made the suite lie.

**A number worth quoting is worth re-deriving.** The method document said a
recommendation costs 0.27 s at the median. It costs 1.52 s, and the difference
is the stability analysis that a previous campaign added for correctness and
nobody costed. Splitting it three ways turned a stale figure into an argument
the document can make.
