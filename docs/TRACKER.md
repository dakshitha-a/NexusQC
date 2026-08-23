# Active Tracker: none

No plan is currently in motion. **Exactly one tracker is active at a time**, and
this file is it; when work starts, this file becomes that plan's tracker.

## How tracking works here

Development is linear, so there is never a reason to have two trackers open at
once. Each plan, feature or non-trivial request gets its own tracker, this file
is whichever one is currently in motion, and when its plan is finished the file
is closed out and moved to [`trackers/`](trackers/), then a fresh one starts
here for whatever comes next.

Closed trackers are kept, never deleted. They are the audit trail for why the
code looks the way it does, and code comments cite them by path:

- [`trackers/2026-08-job-system-overhaul.md`](trackers/2026-08-job-system-overhaul.md)
  the 10-phase job-type/toolchain/agent overhaul. Closed 2026-08-22, 72 steps
  across 5 merged phases.
- [`trackers/2026-08-plots-as-objects.md`](trackers/2026-08-plots-as-objects.md)
  plots as first-class objects: a real chart spec, saved plot records with
  versions, conversational editing, and the Plots panel. Closed 2026-08-22,
  20 steps across 4 merged phases.
- [`trackers/2026-08-excited-state-scans.md`](trackers/2026-08-excited-state-scans.md)
  excited states at every point of a scan or interpolated path, for any method
  and any scan mode, plus the two latent bugs that surfaced underneath it.
  Closed 2026-08-23, 9 steps across 2 merged phases.

Closing one out means: every step `done` with evidence, a `merged:` row on each
phase, `scripts/check_tracker.py` passing, then `git mv` into `trackers/` and a
new file here. Only the active tracker is machine-checked; an archived one
records what was true when it closed and is not re-verified, since the scripts
its evidence names may legitimately have been deleted since.

## Rules (enforced by `scripts/check_tracker.py`)

- Step status is exactly one of `todo` | `in-progress` | `done`.
- A step may be marked `done` **only with an evidence field**: the
  verification script/command path plus a one-line observed result.
- The tracker edit ships **in the same commit** as the step's final code
  change, so `git log --follow docs/TRACKER.md` is the audit trail.
- A phase's `merged` row records the commit hash the stage landed as, and it
  must be a bare hash; the checker rejects anything else.

Format for a step row:

```
- [status] P<phase>.<step>: <short name>
  evidence: <script/command> → "<observed result>"   (required when done)
```

---

## Queued: the public-safety scan

Not started, and deliberately not an active tracker yet. Recorded here so it
is not rediscovered from scratch.

`scripts/check_public_safe.sh` currently fails with two blocking findings:

- host-specific paths (`/data/qcuser/nexusqc-prod`) inside
  `docs/trackers/2026-08-job-system-overhaul.md`
- the lab's licensed-software path (`/opt/Orca-6.1.1/orca`) inside
  `data/verified/orca_functionals.txt`

Deferred deliberately on 2026-08-23. Nothing about it blocks day-to-day work,
because `origin` is private and ordinary pushes are not scanned. It does block
the first public release: `scripts/release.sh` runs the scan itself and refuses
to publish while it fails, so a release attempt hits this regardless.

Both findings sit in files that are not code. One is an archived planning
document, which by this project's own convention is never edited after it
closes; the other is generated reference data. So the likely shape of the fix
is narrowing the scan's patterns rather than rewriting either file, but that
is a starting point for the conversation and not a decision anyone has made.
