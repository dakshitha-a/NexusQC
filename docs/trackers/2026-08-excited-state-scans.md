# Active Tracker: excited-state scans

Excited-state energies at every point of a scan, for any method and any of
the four scan modes, while a scan that nobody said "excited states" about
stays exactly what it is today.

Opened 2026-08-23, from the queued diagnosis the previous tracker recorded
under "multi-state PES scans". That diagnosis was right about the symptom and
understated the work in one place and overstated it in two, all three of which
are recorded in Phase 1 below rather than left for the next reader to
rediscover.

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

## What was actually wrong

`n_states` declared `applies_to=_EXCITED + ("cas_reco",)` and neither scan task
was in `_EXCITED`, so `update_job_draft` refused the parameter on a scan draft
outright. A scan could be given a CAS active space with no way to say how many
roots to state-average over.

Three things the queued diagnosis got wrong, in the direction that matters:

**It understated the dispatch.** Both scan modes build their geometries in this
app (`interpolate.build_path` for a path, `build_coordinate_scan_images` for a
stepped internal coordinate), so a 1-D scan is not delegated to any engine's
own relaxed-scan facility and does not differ from an interpolated one after
the images exist. Whatever works for one works for the other.

**It overstated the labelling hazard.** The worry was that state labels would
be off by one between method families. They are not: `_state_energies_hartree`
returns CASSCF's ladder as-is and rebuilds the single-reference one
ground-state-first, so `Ground state` / `State 1` / ... is already right for
both. Only the line count per `n_states` differs, and that parameter's own
`warn_when` text already says so on the approval card.

**It said the downstream machinery was complete. It was not.** The
single-reference branch of `_state_energies_hartree` read `energy_hartree`,
which no excited-state runner writes, so it was dead code with a docstring
asserting a key that did not exist. And ORCA's TDDFT and EOM-CCSD runners
recorded no absolute energy at all. That was invisible for as long as a scan's
children were always ground state, and it is Phase 2's whole subject.

## Phase 1: An excited-state scan exists and dispatches

- [done] P1.1: `pes_1d/ee` and `interp_pes/ee` in the registry, gated on the real excited-state capability
  evidence: tests/backend/scan_02_excited_state_scans.py → "CASSCF excited-state scans route to all three engines and CASPT2 to BAGEL, so requires=('energy','excited') does not refuse the multireference case the bug report named; mp2 and ccsd are refused everywhere, and the ground-state scan is unchanged"
- [done] P1.2: `n_states`/`use_tda` accepted on a scan draft, and required once it is excited-state
  evidence: tests/backend/scan_02_excited_state_scans.py → "n_states reaches a fresh scan draft at all now, where update_job_draft used to refuse it as inapplicable; a draft carrying subtype=ee with no root count is asked for one rather than reaching READY and running one state per image"
- [done] P1.3: The root count decides the subtype, per method family
  evidence: tests/backend/scan_02_excited_state_scans.py → "n_states=3 on TDDFT and on CASSCF both promote to /ee; n_states=1 is excited on TDDFT but ground state on CASSCF, because the multireference count includes the ground state; n_states=0 falls back to the BARE scan subtype and stays routable, where the pre-existing 5b branch would have rewritten it to a pes_1d/gs that is not in TASKS"
- [done] P1.4: Images dispatch as `single_point/ee`, previewed the same way they run
  evidence: tests/backend/scan_02_excited_state_scans.py → "every child of a real 3-image scan is single_point/ee carrying the root count, for both dft and casscf; one shared scan_child_subtype helper backs both the orchestrator and the approval card's preview so the card cannot show a ground-state input for a job that runs excited states"
- [done] P1.5: Docs, capability matrix and changelog
  evidence: scripts/generate_capability_docs.py → "the generated matrix now carries pes_1d/ee and interp_pes/ee rows, which p7_02_bagel_pes1d_denial.py checks against the registry and which failed until it was regenerated; README gains one row and CHANGELOG an Unreleased entry, both in a chemist's words rather than task identifiers"
- merged: 2edbe1c

## Phase 2: The result can be read back

The half that decides whether the feature looks like it works rather than
merely running.

- [done] P2.1: `_state_energies_hartree` reads the keys the excited-state runners actually write
  evidence: tests/backend/scan_02_excited_state_scans.py → "PySCF TDDFT children normalise to a 3-state absolute ladder; before this they normalised to None, because the single-reference branch read energy_hartree and the runners write ground_state_energy_hartree (and ground_state_ccsd_energy_hartree for EOM-CCSD)"
- [done] P2.2: ORCA's excited-state runners record their ground-state reference
  evidence: tests/backend/scan_02_excited_state_scans.py → "a real ORCA TDDFT path scan now returns a 3-state ladder per image and renders a plot, where it returned [None, None, None] and no plot before; the reference is the converged SCF total for TDDFT/TDA and the CCSD total for EOM-CCSD, NOT the line ORCA labels FINAL SINGLE POINT ENERGY, which in an excited-state run is the first excited state (-74.860946 against an SCF total of -75.278921 on water/B3LYP/STO-3G)"
- [done] P2.3: Job labels and the agent-facing summary
  evidence: tests/backend/scan_02_excited_state_scans.py → "an ee scan is labelled 'PES scan'/'Path scan' rather than falling through to the raw pes_1d/interp_pes identifier, which is what the label lookup does on a miss and which would have reached every download filename; state_energies_per_image renders as one bracketed group per image instead of a flat run of numbers with the per-image structure lost"
- [done] P2.4: The drawer chart picks up the new data
  evidence: tests/frontend/scan_03_excited_state_drawer.spec.mjs → "6/6 in chromium against the compose stack, for all three of PySCF TDDFT, ORCA TDDFT and PySCF CASSCF: three series paths and a Ground state / State 1 / State 2 legend, rather than the single-series fallback ScanPlot lands on when it cannot read the per-image states. No frontend logic changed; the row gained a data-testid because rows display a job's label, not its id, so a test could not address the job it had seeded"
- merged: 2edbe1c

## Queued behind this

Not started, and deliberately not an active tracker. `scripts/check_public_safe.sh`
currently fails with two blocking findings: host paths
(`/data/qcuser/nexusqc-prod`) inside `docs/trackers/2026-08-job-system-overhaul.md`,
and `/opt/Orca-6.1.1/orca` inside `data/verified/orca_functionals.txt`.
Deferred deliberately on 2026-08-23; `scripts/release.sh` runs the scan itself
and will refuse to publish while it fails, so this has to be settled before the
first public release and not before.
