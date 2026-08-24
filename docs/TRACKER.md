# Active Tracker: the job row is one click target

Opened 2026-08-24. Reported as "sometimes it takes a couple of clicks to open a
job preview from the job manager", and asked as a question about where the
latency was: in looking the job's information up, or in getting it to the
browser.

It was neither. Nothing was slow. The job's name was a dead click zone, and a
click that lands there produces no request, no render and no feedback at all,
so the second click a moment later looks like the first one finally arriving.

## Why the name swallowed the click

Renaming a job lived on a double-click on its name. A browser fires click,
click, dblclick in that order, so those two ordinary clicks reach the row's own
handler before the double-click is recognised, and the row's handler opens the
preview drawer. Left alone, starting a rename opened the drawer over the rename
field and stole its focus. The fix at the time was to stop single clicks
propagating out of the name, which worked, and cost this: the name is a block
element spanning the whole name column, measured at 227 to 251 px of a 419 px
row, so the widest and most obvious target in the row became the one place
clicking it did nothing.

The measurements that rule out the two latency explanations, both taken on the
running dev stack before anything was changed:

- `_job_row()`, everything `GET /api/jobs/{id}` does after the ownership
  check, runs in 0.34 to 0.82 ms per job for jobs whose rows are 3.6 KB and
  21 KB of JSON.
- A round trip through nginx measures 12 to 15 ms.
- `JobDetailDrawer` renders "Loading..." on its first frame, before the job
  query resolves, so a click that registers at all is acknowledged in the
  frame it happens in.

## The shape of the fix

Renaming moves out of the name and onto its own button in the action column,
next to delete. The name then needs no handler of its own, the whole row opens
the preview, and the two gestures stop competing for the same click. The
alternative, delaying the row's own click by a couple of hundred milliseconds
to see whether a second one follows, was rejected: it would add real latency to
the common action to protect the rare one, which is the complaint rather than
the cure.

## How tracking works here

Development is linear, so there is never a reason to have two trackers open
at once. Each plan, feature or non-trivial request gets its own tracker, this
file is whichever one is currently in motion, and when its plan is finished
the file is closed out and moved to [`trackers/`](trackers/), then a fresh one
starts here for whatever comes next.

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
- [`trackers/2026-08-scheduler-fairness.md`](trackers/2026-08-scheduler-fairness.md)
  the concurrency cap that bounded admissions per dispatcher tick rather than
  in total, and the rotation pointer that advanced on refused attempts and so
  handed every freed slot back to whoever sat first. Closed 2026-08-23, 5 steps
  across 2 merged phases.
- [`trackers/2026-08-test-job-cleanup.md`](trackers/2026-08-test-job-cleanup.md)
  the suite removing the jobs it creates instead of leaving them in everyone's
  job list. Closed 2026-08-23, 4 steps in 1 merged phase.
- [`trackers/2026-08-frontend-visual-fixes.md`](trackers/2026-08-frontend-visual-fixes.md)
  a long job name pushing the row's stop and delete buttons out of view, viewer
  controls floating over the wrong thing, and orbital isosurfaces corrugated by
  their own cube grid. Closed 2026-08-24, 9 steps across 3 merged phases.
- [`trackers/2026-08-wigner-oscillator-strength.md`](trackers/2026-08-wigner-oscillator-strength.md)
  making oscillator strengths a hard requirement for a nuclear-ensemble
  spectrum, so routing picks an engine that can actually supply them, and
  normalizing the live broadening preview to match the finished figure's
  scale. Closed 2026-08-24, 5 steps across 2 merged phases.

- [`trackers/2026-08-preview-pane-and-attached-geometries.md`](trackers/2026-08-preview-pane-and-attached-geometries.md)
  the job drawer showing a job's product in the preview pane rather than behind
  a click or under an overlay, the geometries of an attached job travelling with
  it so a new job can start from one named image of a path, and one shared
  energy-unit conversion for the agent and the plots. Closed 2026-08-24, 8 steps
  across 4 merged phases.

- [`trackers/2026-08-spectra-travel-with-the-job.md`](trackers/2026-08-spectra-travel-with-the-job.md)
  a tagged spectrum job carrying its own broadened curve instead of only the
  sticks behind it, and a plot kind that puts several methods' spectra on one
  shared axis. Closed 2026-08-24, 3 steps across 2 merged phases.

- [`trackers/2026-08-equilibrium-marker-on-distributions.md`](trackers/2026-08-equilibrium-marker-on-distributions.md)
  a Wigner ensemble's geometry-parameter histograms marking the structure the
  samples were displaced around, and the rule for which geometry that is moving
  into one function instead of three copies. Closed 2026-08-24, 2 steps across
  2 merged phases.

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

## Phase 1: The whole row opens the preview

- [done] P1.1: The name line stops swallowing clicks, and rename gets its own button
  evidence: tests/frontend/ui_07_row_click_target.spec.mjs → "all four non-control parts of the row open the drawer -- the name line (the regression), the job-id line, the status cell and the time cell -- while the checkbox, the rename button and delete all still act on the row instead of opening it; rename from the new button puts the row into an editable field and the new name persists"
- [done] P1.2: The action column holds the rename button next to delete's confirm pair
  evidence: tests/frontend/ui_07_row_click_target.spec.mjs → "with the column widened from w-14 to w-20 the list still reports scrollWidth 419 = clientWidth 419, and rename (1230-1250) and delete (1252-1272) both measure 20x20 inside a panel spanning 861-1280"
- [done] P1.3: Nothing the neighbouring layout spec pinned down moved
  evidence: tests/frontend/ui_06_row_and_viewer_controls.spec.mjs → "21/21, including both lists' no-sideways-scroll checks and the delete button staying inside the Job Manager panel, unchanged by the wider column"

## Phase 2: An open preview survives a dropped poll

- [done] P2.1: The list's loading, error and empty states stop unmounting the drawer
  evidence: frontend/src/jobs/JobManagerPanel.tsx → "the three states are a listBody variable rather than early returns, with the drawer a sibling of it. The Job Manager list polls every 4s and TanStack Query sets status to error on a failed refetch while keeping the data it already had, so as early returns one dropped poll replaced the whole panel, drawer included, with the error line and shut a preview the user was reading"
