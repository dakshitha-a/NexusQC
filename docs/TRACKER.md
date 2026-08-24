# Active Tracker: the job drawer's preview pane shows a job's product

A finished job's drawer should show what the job produced, in the pane, without
a click and without an overlay covering everything else. Three pieces of that
were open at once: an optimization's geometry was reachable only through a
flyout, an interpolated-path scan's real plot was reachable only as a download,
and the geometries an interpolated path is made of do not travel with the job
when it is attached or tagged into a conversation. Opened 2026-08-24.

## What is wrong

`e98ba04` made the geometry flyout open by itself for a completed optimization.
That put the job's main result in an overlay covering the rest of the drawer,
and left the same geometry reachable from two places at once. An opt job's
product IS a geometry, so it belongs in the preview pane as its own section,
the way an interpolated-path scan already shows its path viewer.

`699c70a` made the server-rendered PES plot the preview for an interpolated
scan, which is right, but it left `tests/frontend/scan_03_excited_state_drawer.
spec.mjs` asserting on a mini chart that no longer renders for a finished scan.

Separately, attaching or tagging an `interp_pes` job into a conversation hands
the agent the scan's energies but not the geometries behind them, so a user
cannot point at an image on the path and ask for a new job from it.

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

## Phase 1: An optimization's geometry is embedded, not flown out

The preview pane already had the right shape for this in the scan and geometry
set panels; the fix is to use it rather than to invent a second overlay.

- [done] P1.1: the optimized geometry renders as its own section in the preview pane
  evidence: tests/frontend/opt_02_optimization_drawer.spec.mjs → "no flyout opens by itself, the embedded panel renders the molecule (canvas read back via toDataURL, several hundred distinct colours), and the .xyz download and coordinates toggle both work inline"
- [done] P1.2: the header shortcut button stops competing with it
  evidence: tests/frontend/opt_02_optimization_drawer.spec.mjs → "the View geometry button is absent for a job with an optimized geometry, and the interpolation drawer's own Scan path viewer and PES plot are untouched"
- merged: 3ab94e4

## Phase 2: The specs match what the drawer now does

Both breakages are real and were found by running the suite, not by reading it.

- [done] P2.1: scan_03 checks the finished scan's PNG, and the multi-series mini chart where it still lives
  evidence: tests/frontend/scan_03_excited_state_drawer.spec.mjs → "9/9 against the live stack: the finished scan's preview is the 2400x1800 server-rendered PNG with no mini chart underneath it, and aborting the pes_plot request trips ScanPlot's own onError path, which puts back the three-series chart with its Ground state / State 1 / State 2 legend"
- [done] P2.2: opt_02 switches drawers deterministically and deletes the jobs it seeds
  evidence: tests/frontend/opt_02_optimization_drawer.spec.mjs → "16/16, up from 9/11: waiting for the first dialog to detach and for the second to show the CI job's own id fixed two failures that were the constrained job's drawer still being on screen; both seeded jobs are gone from data/jobs afterwards"

## Phase 3: An interpolated path's geometries travel with the job

Asked for by the user on 2026-08-24: "when attaching/tagging interpolated pes
jobs, i want the geometries to be included as well. That way i can reference
them and tell the agent to run new jobs from them." An `interp_pes` master
already writes every image's geometry to `artifacts.path_xyz`, so the material
exists; what is missing is that attaching or tagging the job hands the agent
its energies without those structures, leaving no way to say "optimize image 5"
or "run a frequency job at the top of the barrier".

- [todo] P3.1: attaching or tagging an interp_pes job carries its per-image geometries
- [todo] P3.2: the agent can start a new job from one named image of an attached path
