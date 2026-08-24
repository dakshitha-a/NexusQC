# Active Tracker: oscillator strengths are required for a nuclear-ensemble spectrum

A Wigner-sampled nuclear-ensemble spectrum is a Gaussian convolution of every
sampled transition weighted by its oscillator strength. Without intensities
there is nothing to convolve. Opened and completed 2026-08-24.

## What was wrong

`wigner_spectra`'s `TaskDef` declared `requires=("excited",)` and only warned
when an engine reported no oscillator strengths. `route_engine` picks the
first engine in `ENGINE_PREFERENCE` (PySCF, ORCA, BAGEL) that
`engines_supporting()` says can run the task, and PySCF is excited-capable
for both CASSCF and EOM-CCSD while supplying transition dipoles for neither.
So a CASSCF or EOM-CCSD ensemble request routed to PySCF by default, ran
every sample, and pooled nothing: the master ended on "No sample contributed
a usable (energy, oscillator strength) pair to pool" only after the full
ensemble had already run.

`app/agent/tools.py`'s `_build_ensemble_spec_or_error` separately forced
`want_oscillator_strengths` on only for `casscf`/`caspt2`, and gated the
allowed sub-job runners through a hand-maintained
`_ALLOWED_ENSEMBLE_JOB_TYPES` set keyed on method rather than on the
(engine, method) capability pair the actual requirement is about.

## How tracking works here

Development is linear, so there is never a reason to have two trackers open
at once. Each plan, feature or non-trivial request gets its own tracker,
this file is whichever one is currently in motion, and when its plan is
finished the file is closed out and moved to
[`trackers/`](trackers/), then a fresh one starts here for whatever comes
next.

Closed trackers are kept, never deleted. They are the audit trail for why
the code looks the way it does, and code comments cite them by path:

- [`trackers/2026-08-job-system-overhaul.md`](trackers/2026-08-job-system-overhaul.md)
  the 10-phase job-type/toolchain/agent overhaul. Closed 2026-08-22, 72
  steps across 5 merged phases.
- [`trackers/2026-08-plots-as-objects.md`](trackers/2026-08-plots-as-objects.md)
  plots as first-class objects. Closed 2026-08-22, 20 steps across 4
  merged phases.
- [`trackers/2026-08-excited-state-scans.md`](trackers/2026-08-excited-state-scans.md)
  excited states at every point of a scan or interpolated path. Closed
  2026-08-23, 9 steps across 2 merged phases.
- [`trackers/2026-08-scheduler-fairness.md`](trackers/2026-08-scheduler-fairness.md)
  the concurrency cap that bounded admissions per tick rather than in
  total, and the rotation pointer that advanced on refused attempts.
  Closed 2026-08-23, 5 steps across 2 merged phases.
- [`trackers/2026-08-test-job-cleanup.md`](trackers/2026-08-test-job-cleanup.md)
  the suite removing the jobs it creates instead of leaving them in
  everyone's job list. Closed 2026-08-23, 4 steps in 1 merged phase.
- [`trackers/2026-08-frontend-visual-fixes.md`](trackers/2026-08-frontend-visual-fixes.md)
  a long job name pushing a row's buttons out of view, viewer controls
  floating over the wrong thing, and corrugated orbital isosurfaces.
  Closed 2026-08-24, 9 steps across 3 merged phases.

Closing one out means: every step `done` with evidence, a `merged:` row on
each phase, `scripts/check_tracker.py` passing, then `git mv` into
`trackers/` and a new file here. Only the active tracker is machine-checked;
an archived one records what was true when it closed and is not
re-verified, since the scripts its evidence names may legitimately have
been deleted since.

## Rules (enforced by `scripts/check_tracker.py`)

- Step status is exactly one of `todo` | `in-progress` | `done`.
- A step may be marked `done` **only with an evidence field**: the
  verification script/command path plus a one-line observed result.
- The tracker edit ships **in the same commit** as the step's final code
  change, so `git log --follow docs/TRACKER.md` is the audit trail.
- A phase's `merged` row records the commit hash the stage landed as, and
  it must be a bare hash; the checker rejects anything else.

Format for a step row:

```
- [status] P<phase>.<step>: <short name>
  evidence: <script/command> → "<observed result>"   (required when done)
```

---

## Phase 1: The capability layer refuses what it cannot back

The task's own `requires` tuple is the single source of truth
(`app/chemistry/registry2/tasks.py`) -- `route_engine` and `supports()`
derive from it, so making the requirement real there is the whole fix, not
one of several places carrying it.

- [done] P1.1: `wigner_spectra` requires `osc_strengths`, not just `excited`
  evidence: tests/backend/wig_01_oscillator_strength_requirement.py → "wigner_spectra requires oscillator strengths, not only excitation energies -- ('excited', 'osc_strengths'); pyscf/casscf and pyscf/eom_ccsd both refused, each naming the missing capability; the same two pairs still run a plain single_point/ee unmodified"
- [done] P1.2: routing sends every method to an engine that can supply intensities, with no new rule in routing.py
  evidence: tests/backend/wig_01_oscillator_strength_requirement.py → "casscf/eom_ccsd route to orca, caspt2 to bagel, dft/hf stay on pyscf -- all five derived from ENGINE_PREFERENCE + engines_supporting(), no hard_rule added; an explicit pyscf+casscf request is refused with real alternatives (orca, bagel) rather than silently rerouted"
- [done] P1.3: the approval card always states that intensities are being computed, for every method
  evidence: tests/backend/wig_01_oscillator_strength_requirement.py → "want_oscillator_strengths forced True for all five (method, engine) pairs tested, each with a param_note naming the engine and method actually running; the old _ENSEMBLE_JOB_TYPES_NEEDING_OSC_FORCE/_ALLOWED_ENSEMBLE_JOB_TYPES sets (keyed on method, not the engine+method capability pair) are removed from app/agent/tools.py"
- [done] P1.4: docs regenerated and updated to match
  evidence: scripts/check_capability_matrix.py → "[PASS] capability matrix consistent with the golden table, no dangling references, docs in sync (after scripts/generate_capability_docs.py regenerated docs/QM_CAPABILITIES.md's wigner_spectra row); docs/CONFIGURATION.md and docs/ARCHITECTURE.md's wigner_ensemble section updated to describe the requirement instead of the old per-method force"

## Phase 2: The live spectrum preview matches the finished figure's scale

Raised mid-task by the user: the finished PNG
(`render_wigner_ensemble_spectrum`) has always normalized by the total
curve's own peak, but the in-browser live-broadening preview
(`WignerBroadeningPanel.tsx`) plotted the raw, unnormalized sum of
broadened Gaussians and labelled the axis `f`, which is not what that
number is.

- [done] P2.1: the preview panel normalizes to the in-window peak, dividing curve and sticks by the same divisor
  evidence: tests/frontend/p8_03_wigner_broadening.spec.mjs → "22/22 checks passed against the real docker-compose stack: y-axis reads 'Norm. intensity', no longer 'f (FWHM ...)'; the normalized curve reaches within 3% of the plot's own top, i.e. its peak is genuinely ~1"
