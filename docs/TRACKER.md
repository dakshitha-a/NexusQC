# Active Tracker: a distribution needs its equilibrium marked

A geometry-parameter histogram from a Wigner ensemble shows how far the
sampled structures spread, and says nothing about what they spread AROUND.
The number a reader wants first, "where was the equilibrium?", is the one
value not on the plot. Opened and completed 2026-08-24.

## What is wrong

`_geometry_parameters_histogram` (app/agent/tools.py) draws one panel per
requested bond, angle or dihedral over an ensemble's sampled geometries. It
reads `ensemble_xyz`, which holds the samples and only the samples, so the
equilibrium value has nowhere to come from and is not drawn.

Asked for by the user on 2026-08-24: "for the geometry parameter
distribution plots (histograms) from wigner spectra jobs, make sure to
include the parameter of the equilibrium geometry as a red dashed line with
its value labeled in the plot."

**Where that value comes from, since the request guessed at two places.**
Not the first sample: a Wigner ensemble displaces every sample, sample 1
included, so it is no closer to the equilibrium than any other. The user's
second guess is the right one. The master's summary carries
`source_frequency_job_id`, and that job's geometry is the structure the
normal modes were computed at.

Which field of it, though, is a decision this codebase has already made
twice, in `ensemble_orchestrator.py` and in `app/agent/tools.py`'s own
ensemble builder: an `opt_freq` source's `spec.molecule` is the
PRE-optimization input, and `summary.optimized_molecule` is the minimum the
modes belong to, while a plain `freq` source's `spec.molecule` IS that
minimum. Getting it wrong draws a line that looks authoritative and sits in
the wrong place. A third copy of that rule is what this phase must avoid.

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

## Phase 1: One answer to "what geometry was this ensemble built around?"

The rule already exists twice and is about to be needed a third time, which
is the point at which it belongs in one place.

- [done] P1.1: one helper resolving an ensemble's equilibrium geometry, with both existing call sites using it
  evidence: tests/backend/wig_02_equilibrium_marker.py → "for an opt_freq source the rule picks the optimized geometry (O-H 0.9894 A) and not the pre-optimization input (1.1715 A), and an ensemble finds the same value through its own recorded source_frequency_job_id; ensemble_orchestrator.py and both call sites in tools.py now call it instead of repeating the branch"
- merged: PLACEHOLDER

## Phase 2: The line, on the plot

- [done] P2.1: each histogram panel marks the equilibrium value as a labelled red dashed line
  evidence: tests/backend/wig_02_equilibrium_marker.py → "10/10: the line is drawn and labelled on every panel, the reply names it and quotes the same number the plot does through one shared formatter, and a batch histogram draws no line at all since its children can start from unrelated structures; confirmed by eye on a real uracil ensemble, where the marker sits mid-distribution and a planar ring's dihedral reads 0"
- merged: PLACEHOLDER
