# Active Tracker: a spectrum travels with the job that produced it

A tagged job carried its spectrum as sticks -- excitation energies and
oscillator strengths, or frequencies and IR intensities -- and for a nuclear
ensemble, not at all: the broadened curve existed only as a PNG and a .dat
file on disk. So the total spectrum could be looked at and could not be
worked with. No way to quote it, and no way to put two methods' spectra on
one axis. Opened 2026-08-24.

## What is wrong

Three job types produce a spectrum and none of them hands it over. A
`wigner_spectra` master writes a 2000-point normalized curve to
`artifacts.ensemble_spectrum_data`, which never reaches the model. A
`single_point/ee` job carries excitation energies and oscillator strengths
but not the broadened curve they imply. A `freq` job carries frequencies and
IR intensities, the same way.

Plotting has the matching gap. `plot` draws one job's spectrum
(`kind="uvvis"`, `"ir"`, `"ensemble"`), and a custom plot resolves one value
per job across several jobs. Neither shape can put N jobs' curves on one
axis, which is what comparing methods means.

Asked for by the user on 2026-08-24: "a tagged spectrum job carries the data
for the total spectrum (x,y coord set or something appropriate) ... that way
the user can combine spectra from different methods into one plot". Asked
directly, they chose both halves, the curve in the tagged context AND an
overlay plot, and each curve normalized to its own peak so shapes and peak
positions compare directly across methods while no curve disagrees with how
that same spectrum looks on its own.

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

## Phase 1: One place that answers "what is this job's spectrum?"

The curve has three different origins (a pooled ensemble file, excited-state
sticks, vibrational sticks) and every caller wants the same answer, so the
resolution belongs in one function rather than at each call site. The
ensemble file is already normalized; the two stick paths have to be
normalized to match, or an overlay mixing them shows one curve at 1.0 and
the other at raw oscillator-strength scale.

- [done] P1.1: one resolver returning a normalized total spectrum for an ensemble, excited-state or frequency job
  evidence: tests/backend/spec_01_spectra_overlay.py → "an excited-state job resolves to a 2000-point UV/Vis curve peaking at exactly 1.0 with the same 0.4 eV broadening its single-job plot uses; the kind comes from the task rather than from which fields exist; a job with no spectrum and a job with energies but no oscillator strengths are each refused with the reason"
- [done] P1.2: a tagged spectrum job carries a compact sampled curve
  evidence: tests/backend/spec_01_spectra_overlay.py → "a tagged excited-state job carries a 65-row sampled table that still reaches its own peak of 1.0, says it is normalized, and points at plot(kind=\"spectra\") rather than at rebuilding the curve; an optimization grows no spectrum section"

## Phase 2: Several methods, one axis

An overlay needs one shared grid: every source builds its own from its own
data range, so two methods' curves are not comparable point-for-point until
they are resampled onto a common one. An IR spectrum in cm-1 and a UV/Vis
spectrum in eV do not share an axis at all, and are refused rather than
silently converted.

- [done] P2.1: a plot kind that overlays several jobs' spectra, each normalized to its own peak
  evidence: tests/backend/spec_01_spectra_overlay.py → "21/21: two functionals' spectra drawn as one plot, both series reaching exactly 1.0 in the cached table and sharing one resampled grid; x_units=nm gives an ascending wavelength axis; a job with no spectrum is named and left out rather than fatal; an IR and a UV/Vis spectrum are refused as a pair; and an overlay is editable in place, unlike a single-job spectrum"
