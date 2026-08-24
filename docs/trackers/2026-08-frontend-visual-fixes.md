# Active Tracker: job-list rows and viewer control placement

Opened and completed 2026-08-24. Three visual defects in the frontend, the
first two reported together and the third found while looking at the result:

1. A long job name widened the job lists until the row's stop or delete button
   sat off the right edge of the panel, reachable only by finding and dragging
   a horizontal scrollbar.
2. The download and enlarge buttons for the orbital and vibrational-mode
   viewers sat in the corner of the whole section rather than the corner of the
   viewer, which for those two panels means over the orbital dropdown and over
   the frequency table.
3. Molecular-orbital isosurfaces rendered corrugated, and the corrugation was
   the cube grid showing through rather than anything in the wavefunction.

## Why the rows blew out in the first place

Both lists are `<table>`s, and both name cells already carried `min-w-0` and
`truncate`. Neither does anything under the browser's default `table-layout:
auto`, where a column is at least as wide as its widest unbreakable content: the
name (and the job id line under it, which is one unbreakable token) set the
column's minimum, the table grew past 100% of the panel, and `overflow-y-auto`
on the scroll container computes `overflow-x` to `auto`, so a scrollbar
appeared and the last column went with it. `table-fixed` is the whole fix for
the blowout; the fade and the tooltip are what make the truncation readable.

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
  plots as first-class objects. Closed 2026-08-22, 20 steps across 4 phases.
- [`trackers/2026-08-excited-state-scans.md`](trackers/2026-08-excited-state-scans.md)
  excited states at every point of a scan or interpolated path. Closed
  2026-08-23, 9 steps across 2 merged phases.
- [`trackers/2026-08-scheduler-fairness.md`](trackers/2026-08-scheduler-fairness.md)
  the concurrency cap that bounded admissions per tick rather than in total,
  and the rotation pointer that advanced on refused attempts. Closed
  2026-08-23, 5 steps across 2 merged phases.
- [`trackers/2026-08-test-job-cleanup.md`](trackers/2026-08-test-job-cleanup.md)
  the suite removing the jobs it creates instead of leaving them in everyone's
  job list. Closed 2026-08-23, 4 steps in 1 merged phase.

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

## Phase 1: The row keeps its buttons, the name gives way

Both lists get the same treatment, because they are the same control twice:
`JobsPanel.tsx` scoped to the open conversation and `JobManagerPanel.tsx`
across all of them. The action column is sized for the two-button confirm
state, not the resting single button, since a fixed-layout column cannot grow
to fit the pair the way an auto one silently did.

- [done] P1.1: Fixed table layout so the name column takes what is left
  evidence: tests/frontend/ui_06_row_and_viewer_controls.spec.mjs → "with a 120-character label seeded on a real job, both lists report scrollWidth 419 = clientWidth 419, i.e. no sideways scroll at all, and the cancel and delete buttons both measure inside the panel's own client rect"
- [done] P1.2: The name fades at the edge instead of ending in an ellipsis
  evidence: tests/frontend/ui_06_row_and_viewer_controls.spec.mjs → "the name line really does overflow its box, computed mask-image is a linear-gradient and text-overflow is clip rather than ellipsis, so the two truncation styles are not stacked on each other"
- [done] P1.3: The whole name on hover
  evidence: tests/frontend/ui_06_row_and_viewer_controls.spec.mjs → "the name cell's title attribute carries the full seeded label; in the Job Manager it reads label first and the double-click-to-rename hint second, so the existing affordance survives"
- merged: e920ce9

## Phase 2: The control row belongs to the viewer, not the section

`ExpandablePanel` keeps owning exactly one absolutely-positioned control row,
which is the invariant `73425bf` established and this must not undo. What
changes is where that row is allowed to sit: a viewer can nominate its own box
via `PanelControlAnchor` and the panel portals the whole row into it. Scoped to
the orbital and mode viewers, which are the two panels whose viewer is not the
first thing in the panel. `MoleculeViewer`'s four frame viewers are already
first, so anchoring them would move nothing.

The orbital viewer asks for the anchor per call site rather than always,
because it is not always its panel's subject: in the orbitals panel it is, but
a neb_ts panel renders it as a secondary per-frame inspector underneath the
path viewer, and there the whole panel's expand toggle would have been dragged
down into a sub-viewer.

- [done] P2.1: A viewer can claim the panel's control row
  evidence: frontend/src/app-shell/ExpandablePanel.tsx → "anchor is registered through useState and a callback ref, not a ref; with a ref the row renders in the panel corner on the first pass and never moves, which is the same lesson the slot node already records. MoCubeViewer takes it as an opt-in prop so the neb_ts panel's toggle stays where it is"
- [done] P2.2: The orbital viewer's buttons sit over the isosurface
  evidence: tests/frontend/ui_06_row_and_viewer_controls.spec.mjs → "download and expand both measure inside the isosurface box (button top 626/629 against a box spanning 621 to 877), where before they were above the orbital dropdown"
- [done] P2.3: The mode viewer's buttons sit over the animation, expanded and collapsed
  evidence: tests/frontend/ui_06_row_and_viewer_controls.spec.mjs → "both states pass: collapsed the pair is inside a 224px-tall viewer box, expanded inside the 640px one, side by side rather than stacked, and no console errors in either"
- [done] P2.4: The tables get their padding back
  evidence: frontend/src/jobs/JobDetailDrawer.tsx → "the pr-7 that kept the frequency and orbital tables clear of the floating control cluster is gone from both panels, since there is no longer a cluster floating over them; grep for pr-7 in frontend/src returns nothing"
- merged: e920ce9

## Phase 3: The isosurface is smooth

Reported as "the MO surfaces look like they have wrinkles". They did, and the
wrinkles were the cube grid rather than the wavefunction: 3Dmol runs marching
cubes over the grid and then smooths the mesh, and its default is a single
Laplacian pass, which is not enough to remove the staircase the cells leave.
Both cube paths write a fixed 80 points per axis over a box that grows with the
molecule, so the spacing coarsens with system size and the ripples coarsen with
it.

Smoothing rather than a denser grid: it costs nothing, needs no server-side
re-render, and applies to every job already on disk, where 160 points per axis
would be eight times the data to compute and to transfer on every lazy orbital
fetch. The cost is stated in the code, because it is real rather than free.

- [done] P3.1: Enough smoothing passes to bury the grid
  evidence: frontend/src/jobs/MoCubeViewer.tsx → "rendering one benzene HOMO cube headlessly at smoothness 1, 3, 5 and 10 shows the corrugation plainly at the 3Dmol default of 1, nearly gone at 5 and gone at 10; 6 is the chosen value. Laplacian smoothing shrinks the surface, measured on rendered lobe area as 1.4% for water and 3.1% for benzene, i.e. one to two percent in linear extent"
- [done] P3.2: Confirmed in the real viewer, not just a private harness
  evidence: frontend/src/jobs/MoCubeViewer.tsx → "a benzene HF/STO-3G single point seeded on the dev stack, its HOMO opened in the app's own MO panel and the canvas read back with toDataURL (page.screenshot cannot capture WebGL): the pi lobes render clean, with no trace of the ripples"
- merged: e920ce9
