# Closed Tracker: the reference determinant a transition is measured from

Job `51a14d838f5b`, a uracil CAS(12,9)/cc-pVDZ state-averaged CASSCF over three
roots, reported its dominant transitions as `30->28 (0.74), 29->28 (0.18)` for
the ground state, nothing at all for S1, and `29->28 (0.68), 30->28 (0.14)` for
S2. Every one of those is wrong, and the raw CI vectors on disk say so plainly.
Opened and closed 2026-08-24.

## What actually went wrong

A transition is a difference between two occupation patterns, so it is only as
meaningful as the reference it is measured from. `ci_transitions.py` picks that
reference as the single highest-weight configuration across every state's CI
vector, deliberately rather than taking state 0's, so that a root coming out of
energy order relative to the closed-shell-like one is still characterized
correctly.

That rule was written for ORCA, whose CASSCF table is already spin-adapted and
prints one weight per configuration. Two of the three engines are not: BAGEL and
PySCF print raw Slater determinants, so an open-shell singlet arrives as two
lines with the same occupation pattern and the same magnitude, and
`aggregate_by_configuration` correctly sums them into one configuration weight.
A closed-shell determinant has no partner to sum with. The comparison that picks
the reference is then between a sum of two terms and a single term, and it
systematically favours the open-shell one.

On this job that is exactly what happened. The ground state's closed-shell
`222222000` carries 0.858, so 0.7364 as a weight. S1's open-shell `222212100`
carries 0.659 twice, so 0.8684 once summed. The reference became S1's own
leading configuration, which is why S1 came back empty (a state whose top
configuration is the reference has no excitation to report) and why the other
two were described as transitions into orbital 28, an orbital that is doubly
occupied in the actual reference.

The fix is to choose the reference before aggregation, on the largest single
term, which is the comparison the rule always meant to make.

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

- [`trackers/2026-08-job-row-click-target.md`](trackers/2026-08-job-row-click-target.md)
  the job's name being the one part of a Job Manager row that did not open its
  preview, which read as the app being slow to answer, and an open preview
  being unmounted by a single failed poll of the list behind it. Closed
  2026-08-24, 4 steps across 2 merged phases.

- [`trackers/2026-08-bagel-blind-input.md`](trackers/2026-08-bagel-blind-input.md)
  a pasted BAGEL CASSCF input described as the Hartree-Fock section it starts
  from, the orbital file a verbatim run asked the engine to write being deleted
  before anyone could download it, and the same sweep quietly leaving BAGEL
  orbital reuse with no source to reuse. Closed 2026-08-24, 12 steps across 4
  merged phases.

- [`trackers/2026-08-named-active-space.md`](trackers/2026-08-named-active-space.md)
  naming which orbitals form a CASSCF active space instead of only how many,
  through BAGEL's `active` keyword and PySCF's `sort_mo`, and the rule that the
  list is only ever set when the user names the orbitals themselves. Closed
  2026-08-24, 6 steps across 2 merged phases.

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

## Phase 1: The reference is chosen before the spin partners are summed

- [done] P1.1: One shared reference-selection function, ranking raw rows
  evidence: tests/backend/ci_01_reference_determinant.py → "on the rows that reproduce the reported run, the closed-shell determinant is the largest single row while the open-shell configuration is the heaviest once summed, so the two rankings genuinely disagree and only the row ranking picks the reference; sign is ranked by magnitude, and an empty block gives no reference rather than raising"
- [done] P1.2: BAGEL and PySCF stop comparing a sum against a single term
  evidence: tests/backend/ci_01_reference_determinant.py → "both now choose from the pre-aggregation determinant rows; ORCA passes its own already-spin-adapted rows through the same function, which is the selection its max() always made, so its behaviour is unchanged"
- [done] P1.3: Re-derive the reported job's table from the output it already has
  evidence: tests/backend/ci_01_reference_determinant.py → "job 51a14d838f5b's own CI vectors now give [none, 28->30 (0.87), 29->30 (0.68)] where they gave [30->28 (0.74) 29->28 (0.18), none, 29->28 (0.68) 30->28 (0.14)]; nothing is described as an excitation into orbital 28 any more, which is doubly occupied in the real reference and can accept nothing"
- merged: 16f0b3c
