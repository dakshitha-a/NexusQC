# Active Tracker: none

No plan is currently in motion. **Exactly one tracker is active at a time**, and
this file is it; when work starts, this file becomes that plan's tracker.

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

## Queued: multi-state PES scans

Not started, and deliberately not an active tracker yet. Recorded here so the
diagnosis is not repeated. Raised 2026-08-22 as "PES by interpolation only
supports calculating one state", confirmed, and found to be broader than that.

**What is true.** `n_states` declares
`applies_to=_EXCITED + ("cas_reco",)`, and neither `pes_1d` nor `interp_pes` is
in `_EXCITED`, so neither scan task accepts it:

```
interp_pes: method, basis, functional, active_electrons, active_orbitals,
            n_points, interpolation_method, df_basis, source_geometry_job_id
pes_1d:     method, basis, functional, active_electrons, active_orbitals,
            coordinate, scan_range, n_points, df_basis, source_geometry_job_id
```

That looks like an oversight rather than a decision: `active_electrons` and
`active_orbitals` already declare
`applies_to=_CAS + ("pes_1d", "interp_pes", "neb_ts", "wigner_spectra")`, so a
scan can be given a CAS active space but no way to say how many roots to
state-average over.

**Why it is worth doing.** The multi-state machinery is already written and is
currently unreachable. In `app/chemistry/jobs/scan_orchestrator.py`,
`_state_energies_hartree` already normalises both shapes (CASSCF's
`state_energies_hartree`, and single-reference `energy_hartree` plus
`excitation_energies_eV`), `_build_state_series` already builds N series
labelled `Ground state` / `State 1` / ..., `render_pes_plot` already draws one
line per state on a shared relative-energy zero, and the master summary already
stores `state_energies_per_image` for every image. Only
`summary["energies_hartree"]` narrows to `states[0]`.

**The easy part.** Add `pes_1d` and `interp_pes` to `n_states`'
`applies_to`, and add `state_energies_per_image` to both tasks'
`plottable_fields` (today they advertise only `coordinate_values`,
`energies_hartree` and `relative_energies_kcal_mol`, so `lookup_capabilities`
tells the agent a single series is all there is).

**The real work, and where the care is needed.** Confirming the child spec
carries `n_states` through to each image, and settling what it means per
method. `n_states`' own help text already draws the distinction: for CASSCF and
CASPT2 the count INCLUDES the ground state, while for TDDFT/CIS/EOM-CCSD it is
the number of excited states above it. Get that wrong and the plot's state
labels are off by one between methods, which is the kind of error that looks
like physics. Also still open: whether an excited-state child task can be
requested for a scan at all, or only ground state plus a CAS space.
