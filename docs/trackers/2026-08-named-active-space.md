# Closed Tracker: naming the active orbitals yourself

A CASSCF active space is chosen by count today: say twelve electrons in nine
orbitals and the engine picks the nine orbitals centred on the HOMO. A user who
has looked at a previous job's orbitals and knows which nine they want has no
way to say so, which is why the request that opened
[`trackers/2026-08-bagel-blind-input.md`](trackers/2026-08-bagel-blind-input.md)
had to go through a verbatim job: the app had no field for BAGEL's `active`
keyword. That run came back unparsed, because a verbatim job is verbatim.
Opened and closed 2026-08-24.

## What this adds, and the line it must not cross

One optional parameter, `active_space_orbital_indices`, a list of 1-based
orbital numbers naming exactly which orbitals form the active space.

**It is only ever set when the user names those orbitals.** That is the whole
constraint, stated by the user when approving the work, and it is not enforced
by leaving the field out of the elicitation flow -- that only stops the app
from asking. It has to be enforced against the model filling it in on its own,
primed by a conversation already full of orbital numbers, because a guessed
active space reaches the approval card looking exactly like a chosen one and
computes a different molecule's worth of chemistry. So the parameter's `help`
and `update_job_draft`'s docstring both say it plainly, and the check that
matters is that a CASSCF request which says nothing about specific orbitals
reaches READY with the field absent rather than defaulted.

Two engines can express it. BAGEL has an `active` keyword in its casscf
section, and PySCF has `mcscf.sort_mo`, whose `caslst` is the same list with
the same 1-based convention. ORCA has no equivalent, and a user who asks for
one on a draft routed to ORCA is told which engines can do it rather than
having the field quietly disappear.

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

## Phase 1: The parameter, and the promise that it is never invented

- [done] P1.1: Declare active_space_orbital_indices, asked for by nobody
  evidence: tests/backend/active_01_named_orbitals.py → "a CASSCF draft that says nothing about specific orbitals reaches READY with the field absent, not defaulted and not an empty list; missing_required never names it on any of the three engines, it carries no question text and no required_when, and its help tells the model not to infer one"
- [done] P1.2: Validate its shape, and refuse rather than drop a malformed one
  evidence: tests/backend/active_01_named_orbitals.py → "too few, too many, a repeated orbital and a zero or negative index each stop the draft with the reason named, ask about the orbitals rather than something else, and leave the user's list in the draft instead of discarding it"
- [done] P1.3: Tell a user on ORCA which engines can do this
  evidence: tests/backend/active_01_named_orbitals.py → "an ORCA draft naming orbitals asks which engine to use, offers bagel and pyscf as the options, and says what dropping the list would mean instead of letting the field vanish because applies_when gated it off"
- merged: deb4c22

## Phase 2: Both engines that can express it

- [done] P2.1: BAGEL's active keyword
  evidence: tests/backend/active_01_named_orbitals.py → "the approval-card preview carries the active keyword before anything runs; job e9c2b482b7ed, a real uracil CAS(12,9)/cc-pVDZ run over the user's own nine orbitals, reproduces the verbatim run 8030d89f0604 to 1e-8 hartree and comes back parsed, with 6.04 and 7.99 eV, the 29->30 and 28->30 characters, an orbital table and a molden"
- [done] P2.2: PySCF's sort_mo
  evidence: tests/backend/active_01_named_orbitals.py → "three real water CAS(4,4) runs: the default space, orbitals 3,4,5,6 and orbitals 3,4,5,7 all give different energies, so sort_mo is really applied and not quietly ignored; base=1 is spelled out in the preview and at the call site, and the optimization path converges its SCF first because geomeTRIC hands it an un-run one and an orbital index into None means nothing"
- [done] P2.3: Run the user's own active space as a structured job
  evidence: tests/backend/active_01_named_orbitals.py → "every CASSCF-family summary records the named space when there was one and stays silent when there was not, so an ordinary job's summary table gains no empty row; the drawer already renders this key for an active-space recommendation, so the request and the result read in the same vocabulary"
- merged: deb4c22
