# Active Tracker: how far outside the molecule an orbital lies

The orbital table names each orbital's character, and every measurement behind
that label assumes the orbital sits on the atoms. Mulliken populations do, and
so does the sigma/pi test. An orbital that lies mostly outside the molecular
framework breaks that assumption without saying so: it gets whatever population
analysis reports, which on a set of diffuse functions means nothing. In a
uracil CASSCF run, orbital 34 came back as a lone pair on a hydrogen and
orbital 33 as an antibonding sigma between two hydrogens on opposite sides of
the ring. Both are diffuse virtuals, and neither label describes anything.

The failure is silent rather than absent, which is the part worth fixing. A
table that says nothing about diffuseness reads as a table where diffuseness
did not come up.

Asked for by the user on 2026-08-24, after they caught a related
misclassification: "lets implement the diffuseness feature as well. test with
aug-cc-pvdz." Opened 2026-08-24.

## What this measures, and what it does not

Each orbital gets the fraction of its own density lying outside the molecule,
where "outside" means beyond 1.5 times the van der Waals radius of every atom.
The fraction is the number on the row; the boolean flag is a convenience
derived from it at 0.5, so a partly diffuse orbital stays visible as 0.42
rather than being rounded away into "not diffuse".

It is deliberately not called a Rydberg label. Telling a true Rydberg series
member from a diffuse virtual needs the principal quantum number and a quantum
defect, not a spatial extent. What this says is the thing it actually measured:
this orbital lies mostly outside the molecule, which is the property a Rydberg
state is built out of.

The measure is size-independent by construction, which a raw rms radius is not.
Measured across water, formaldehyde, ethylene, benzene and uracil, every
occupied orbital comes in below 0.010 and every cc-pVDZ virtual below 0.29,
while aug-cc-pVDZ virtuals reach 0.98. That gap from 0.29 to 0.5 is the margin
the threshold rests on.

There is no attempt to classify the basis set as diffuse or not. The minimum
primitive exponent is reported as a fact and left to speak, because the
candidate thresholds do not separate: cc-pVTZ sits at 0.1027 and ma-def2-SVP at
0.0851, so any cut lands between them by luck rather than physics. The orbitals
answer the question empirically anyway. If nothing comes out diffuse, that is
the finding.

ORCA gets no diffuseness column, for the same reason it gets no character
column: its molden export scales AO columns per shell, so anything derived from
its coefficients through pyscf is wrong in a way that looks fine. That is a
standing property of the ORCA path, not an oversight here.

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

- [`trackers/2026-08-ci-reference-determinant.md`](trackers/2026-08-ci-reference-determinant.md)
  dominant transitions measured from an excited state's own leading
  configuration, because the reference was chosen after an open-shell singlet's
  two spin partners had been summed and a closed-shell determinant's had not.
  Closed 2026-08-24, 3 steps in 1 merged phase.

- [`trackers/2026-08-context-window-budget.md`](trackers/2026-08-context-window-budget.md)
  replies cut off mid-sentence before they could raise a job-approval card,
  because history was bounded by message count while the prompt was measured in
  tokens, the declared context window was half the real one, and an attached
  job's results were re-sent in full on every turn. Closed 2026-08-24, 4 steps
  in 1 merged phase.

- [`trackers/2026-08-capability-discoverability.md`](trackers/2026-08-capability-discoverability.md)
  a capability answer that never named the parameters a draft accepts, so the
  agent offered to "check whether this deployment supports" something it had
  supported all along, plus an old-approval test that was green on a host and
  red in the container it is meant to run in. Closed 2026-08-24, 3 steps in 1
  merged phase.

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

## Phase 1: Measure it

The grid this needs is not the grid the symmetry test needed. A level 0 Becke
grid integrates a valence orbital exactly but loses 1.9% of a diffuse orbital's
norm, because most of that norm sits in the sparse outer shells. Level 1 holds
to 0.2%, and one grid now serves both measurements rather than each building
its own.

- [done] P1.1: per-orbital fraction of density outside the molecular envelope
  evidence: scripts/validate_orbital_character.py → "water/aug-cc-pVDZ flags 5 diffuse virtuals at fractions 0.63 to 0.94, the lowest of them the 3s-like orbital at 0.96 eV; no occupied orbital anywhere exceeds 0.01"
- [done] P1.2: the standing check covers aug-cc-pVDZ and a non-augmented control
  evidence: scripts/validate_orbital_character.py → "water/cc-pVDZ flags nothing, max fraction 0.22; ethylene/aug-cc-pVDZ keeps every occupied orbital at or below 0.01 while still finding diffuse virtuals, so the measure does not scale with the molecule"

## Phase 2: Say it where a chemist and the agent can see it

A number nobody reads is not a fix. The rows already flow into both PySCF paths
and BAGEL through the existing `row.update(char_row)`, so the work here is the
labels that go with it: a diffuse orbital must stop claiming an atom it does
not sit on, the note has to explain what the column means, and the table has to
show it.

- [todo] P2.1: a diffuse orbital stops claiming a false atom localization
  evidence:
- [todo] P2.2: the note explains the column and reports the minimum basis exponent
  evidence:
- [todo] P2.3: the orbital table shows diffuseness, verified in a real browser
  evidence:
