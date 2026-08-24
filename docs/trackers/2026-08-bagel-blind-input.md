# Closed Tracker: a pasted BAGEL input, read correctly and kept whole

A user pasted a BAGEL CASSCF input with a hand-picked active space, ran it as a
blind job, and got back two wrong answers: the app described a three-root CASSCF
calculation as an HF ground-state single point, and the orbital file the input
had asked BAGEL to write was gone from the downloaded job directory. Opened and closed 2026-08-24.

## What actually went wrong

Two separate defects, plus a third found underneath them.

**The sniffer reads a BAGEL input's scaffolding as its method.** A BAGEL input
is a script, not a declaration. A CASSCF run opens with an `hf` block because
the SCF orbitals are the starting guess, and a CASPT2 run carries a `casscf`
block ahead of `smith` for the same reason. `_sniff_bagel` took the first
method-shaped section title it found, so it reported the scaffolding rather
than the calculation. It also never looked at `nstate`, which on this engine is
the only thing separating one ground-state energy from a set of vertical
excitation energies, since BAGEL has no keyword equivalent to ORCA's `%tddft`.
The pasted three-root CASSCF therefore came back as `single_point/gs` at `hf`.

**Scratch cleanup deleted the file the input asked for.** A completed BAGEL job
gets a denylist sweep: everything goes except `input.json` and `bagel.out`,
which is safe only because a structured runner declares its real outputs as
artifacts and `_artifact_filenames` protects those. A blind job's runner cannot
declare them, because the pasted input names its own output files and this app
has no list of what they are. So `orbitals.molden` and `orbitals.archive` were
both written, then deleted, before the download route zipped the directory.

**And the same sweep quietly broke BAGEL orbital reuse.** `save_ref` writes
`orbitals.archive` on every CASSCF/CASPT2 input this app builds, and
`_copy_initial_orbitals_archive` reads it to start a later job from those
orbitals. Nothing declares it as an artifact, because it is an input to a
future job rather than a result of this one, so the broad rule deleted it from
every completed BAGEL job. Verified on a real one: job `8c5fd55d5566`, a
structured BAGEL CASSCF excited-state run, has its molden and no archive at
all.

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

## Phase 1: The sniffer reports the calculation, not its scaffolding

- [done] P1.1: Read a BAGEL input's method by precedence, not by position
  evidence: tests/backend/sniff_01_pasted_inputs.py → "the user's own pasted input now reads as casscf/cc-pvdz where it read as hf, and every generated BAGEL job type reports the method it computes rather than its hf preamble; a CASPT2 input's smith block carries its method as a plain string, not a list, which the old nested-block walk would have raised on had it ever reached that far"
- [done] P1.2: Treat more than one root as an excited-state calculation
  evidence: tests/backend/sniff_01_pasted_inputs.py → "nstate 3 makes the pasted input single_point/ee; nstate 1 stays gs, since BAGEL's count includes the ground state; the promotion fires only from gs, so a nacme block carrying several roots is still a coupling"

- [done] P1.3: Read the same root count on ORCA
  evidence: tests/backend/sniff_01_pasted_inputs.py → "the suite's own ORCA_CASSCF sample, nroots 3, was asserted as single_point/gs and is now ee; nroots is found in a block written on one line as well as across several, and a %mecp input carrying its own roots stays opt/ci"
- merged: dc74201

## Phase 2: A job keeps the files it wrote

- [done] P2.1: A blind BAGEL job takes the narrow scratch rule
  evidence: tests/backend/blind_01_bagel_artifacts.py → "a completed blind job keeps orbitals.molden and orbitals.archive and still loses casscf.log; the real job fe37bed7811e on disk is the before picture, its input asking BAGEL for both files and its directory holding neither"
- [done] P2.2: Keep the save_ref archive on every completed BAGEL job
  evidence: tests/backend/blind_01_bagel_artifacts.py → "orbitals.archive survives a structured job's broad sweep, so orbital reuse has a source; job 8c5fd55d5566, a real completed BAGEL CASSCF excited-state run, is the before picture with its molden kept and no archive at all"
- [done] P2.3: A blind job's molden becomes an artifact and an orbital table
  evidence: tests/backend/blind_01_bagel_artifacts.py → "a truncated molden degrades to no table instead of raising, which matters because run_custom calls _add_orbital_table outside _safe_parse and would otherwise have turned a completed blind job into a failed one"
- merged: dc74201

## Phase 3: The run the user asked for

- [done] P3.1: Rebuild the image and redo the uracil CASSCF with the named active space
  evidence: tests/backend/blind_01_bagel_artifacts.py → "job 8030d89f0604, the same input rerun against the rebuilt image, kept orbitals.molden (506 KB) and orbitals.archive (1.1 MB); both are in the download zip, the artifact route serves the molden, and an active orbital renders a cube through the lazy MO route. Energies reproduce the first run exactly, since the active space is the same set"
- merged: 13f7bbf

## Phase 4: The classifier reads what each program really writes

Asked for after the two defects above were fixed: make the recognition robust
across all three programs rather than only on the input that exposed it. Held
to method detection and subtype promotion inside the task vocabulary that
already exists. A pasted input that maps onto no registered job type is
reported as unidentified and still runs verbatim, which is what the
unconfident result is for, rather than being forced into the nearest task.

- [done] P4.1: ORCA writes the optimization keyword many ways, and the method family in front of it
  evidence: tests/backend/sniff_01_pasted_inputs.py → "TightOpt, VeryTightOpt, COpt and L-Opt are all opt/min, where a bare token match read them as inputs with no task keyword and therefore as single points; DLPNO-CCSD(T), RI-MP2 and SC-NEVPT2 resolve to the method they approximate, and STEOM-DLPNO-CCSD to EOM-CCSD rather than to plain coupled cluster, which the hyphenated-tail rule alone would have got wrong"
- [done] P4.2: A transition-state search is reported as unidentified, not as the nearest task
  evidence: tests/backend/sniff_01_pasted_inputs.py → "OptTS, OptTS Freq and ScanTS all come back with the engine known and no task claimed; reading the second as a plain frequency job dropped the search it was really doing"
- [done] P4.3: The composite and wB97 families, which do not enumerate
  evidence: tests/backend/sniff_01_pasted_inputs.py → "r2SCAN-3c, B97-3c, PBEh-3c, wB97M-V and wB97X-D4 are dft; HF-3c is hf, which it has to be, since the rule that makes the others dft is a trailing -3c"
- [done] P4.4: BAGEL's singular gradient section, and PySCF's method ordering
  evidence: tests/backend/sniff_01_pasted_inputs.py → "a 'force' section is a gradient like 'forces'; a PySCF script's method is read by precedence too, since a CASSCF script builds scf.RHF before mcscf.CASSCF and reading the first would report the starting guess"
- [done] P4.5: The root count read on all three programs
  evidence: tests/backend/sniff_01_pasted_inputs.py → "state_average and nroots both make a PySCF CASSCF script excited-state; EOM-CCSD is excited-state on ORCA and PySCF without a count, having nothing else to compute; every PySCF case still reports executable=False"
- merged: 13f7bbf
