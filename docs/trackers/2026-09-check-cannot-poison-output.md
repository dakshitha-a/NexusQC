# Tracker: a test script could silently lose its own verdict

**Complete as of 2026-09-01. Two steps in one phase, both done.**
The `merged:` row records the commit it landed as.

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
[`trackers/2026-09-clearing-the-backlog.md`](trackers/2026-09-clearing-the-backlog.md)
-- 5 steps across 3 phases, closed 2026-09-01.

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

A batch run of several backend scripts printed `proj_03_ownership`'s header
and then nothing at all, between two neighbours that reported normally. That
reads exactly like a script that crashed, and it was reported as an
undiagnosed caveat: "standalone pass; batch silence not diagnosed."

It was not a crash and not the per-IP rate limiter, which was the guess. The
script had passed 15/15 the whole time. `proj_03` asserts that a project's
owner can download it and prints `resp.text[:150]` as the check's detail; for
a zip that begins `PK\x03\x04` and carries NUL bytes. A single NUL makes the
entire stream binary to grep, and this host's `grep` is ugrep 7.8.4, which
then prints **nothing** -- no matching lines, and no "binary file matches"
note on stderr either, unlike GNU grep. `grep -a` recovered the summary
immediately.

The consequence is worse than one confusing run. Any filtered read of a test
run -- a `| grep` in a shell loop, a CI log scraper -- can lose a script's
entire verdict without a trace, and a lost verdict looks like a failure, which
is the most expensive kind of false alarm to chase.

Fixed at the funnel rather than the call site. Every line these scripts print
goes through `fixtures.check`, so escaping there means no future script can
reintroduce it, and the call site is additionally made to describe a binary
body rather than dump it, because 150 characters of escaped zip header tells a
reader nothing even when it is safe.

## Phase 1: A check cannot poison its own script's output

- [done] P1.1: fixtures.check escapes non-printable detail
  evidence: tests/fixtures.py -> "A check deliberately fed 60 raw bytes of an ELF binary still prints a greppable line and the script's summary is still visible, where before a single NUL made ugrep emit nothing for the whole stream. Unit-checked that plain and non-ASCII text are untouched ('cafe' with an accent and a tick survive verbatim) and that the 300-character cap applies. Fixed at the funnel every script's output already goes through, so a future script cannot reintroduce it at a new call site"
- [done] P1.2: The download check describes the body instead of dumping it
  evidence: tests/backend/proj_03_ownership.py -> "The line now reads '200 <application/zip, 1253 bytes>' rather than 150 characters of zip header. Run through the exact filter that lost it before, proj_03 reports 15/15, and all five scripts in that batch now report: 12/12, 32/32, 15/15, 34/34, 9/9. The escape in check() alone would have made it safe; this makes it useful, since escaped binary tells a reader nothing"

- merged: 9c019b0
