# Tracker: the plotter -- styles that land, and charts we do not draw yet

Opened 2026-08-31, out of a review of the plot tool prompted by one report:
*"I could not ask the agent to change font sizes."* That turned out to be true,
and true for three more requests besides, all of the same shape. The style
vocabulary accepted a key, validated it, reported the plot as drawn, and threw
the request away. `app/chemistry/plot_style.py`'s own docstring names that as
the one outcome it exists to prevent, because a plot that comes back looking
identical reads as the app ignoring you.

Phase 1 closes the four. Phases 2 and 3 are the rest of what the review found:
a real vector export, and the charts this app has the data for and does not
draw.

It stays here rather than moving to [`trackers/`](trackers/) until the next
plan starts, which is when it gets archived and a fresh tracker takes its
place. **Exactly one tracker is active at a time.** The one this replaces is
[`trackers/2026-08-backlog-and-job-manager-controls.md`](trackers/2026-08-backlog-and-job-manager-controls.md)
-- 8 steps across 5 phases, closed 2026-08-31.

## Rules (enforced by `scripts/check_tracker.py`)

- Step status is exactly one of `todo` | `in-progress` | `done`.
- A step may be marked `done` **only with an evidence field**: the
  verification script/command path plus a one-line observed result.
- The tracker edit ships **in the same commit** as the step's final code
  change, so `git log --follow docs/TRACKER.md` is the audit trail.
- A phase's `merged` row records the commit hash the stage landed as.

Format for a step row:

```
- [status] P<phase>.<step>: <short name>
  evidence: <script/command> → "<observed result>"   (required when done)
```

---

## Phase 1: every accepted style key reaches the figure

Four defects, one shape. Each was invisible in the same way: the request came
back reported as done, and the image was unchanged.

The reason none of this was caught is worth recording, because it is a lesson
about the test and not about the code. `tests/backend/plot_02_style_vocabulary.py`
restyles with seven keys at once and asserts the image changed. It changes. A
single inert key inside that bundle passes every assertion, and one was inert.
`plot_03` asserts one key at a time and measures the text, rather than hashing
the file and hoping.

- [done] P1.1: `font_size` is the base size, not a fifth number beside four fixed ones
  evidence: tests/backend/plot_03_style_actually_lands.py → "default (16.0, 14.0, 12.0, 12.0) -> font_size=26 (32.0, 28.0, 24.0, 24.0), and PlotStyle().rc() is unchanged"
- [done] P1.2: `plot(kind="comparison")` forwards the caller's spec
  evidence: tests/backend/plot_03_style_actually_lands.py → "the caller's look reaches the drawing pipeline; the front door still owns the mark and the series"
- [done] P1.3: an ensemble spectrum stops overwriting its plot spec with the job's
  evidence: tests/backend/plot_03_style_actually_lands.py → "look survives to the record; molecule/params/engine/parent_job_id no longer stored as the chart's spec; width still defaults from the job"
- [done] P1.4: a distribution is stylable and editable like every other kind
  evidence: tests/backend/plot_03_style_actually_lands.py → "a style patch changes the render, an edit is no longer refused with 'cannot redraw', and an unstyled distribution now draws at 16/14 rather than matplotlib's 12/10"
- [done] P1.6: the refusal for an unknown plot kind names all ten, not six
  evidence: app/agent/tools.py → "pes_scan, neb, entropy and spectra are real kinds and the fallthrough said they were not"
- [done] P1.5: an export format nothing implements is refused rather than ignored
  evidence: tests/backend/plot_03_style_actually_lands.py → "style 'fmt': svg export is not available yet ...; png still accepted"

### What P1.3 and P1.4 looked like in practice

`plot_wigner_ensemble_spectrum` read the job's spec into `spec`, the same local
the plot's spec had arrived in. Both consequences were silent. Restyling an
ensemble spectrum did nothing at all, and the saved record stored the
calculation (molecule, params, engine, parent_job_id) as though it described
the chart. Four of the eight records in the dev data directory still carry that
shape. Verified end to end on a real 50-sample uracil master copied into a
scratch checkout: the record now stores `kind` and `width` only, and an edit
setting a title, `font_size: 22` and a grid produces a genuinely different
image.

P1.4 was verified the same way rather than only against the stub in `plot_03`:
`geometry_parameters` drew a two-panel bond and angle distribution off that
same master, and `plot(kind="edit", ...)` with a title, `font_size: 20` and a
grid redrew it as v2 under the same plot id. The title lands as the figure's,
over the row, because each panel's own title carries the parameter name and
the sample count and is the only thing telling the panels apart.

One deliberate change of appearance came with it. `render_histogram_plot`
opened no `rc_context` at all, so an unstyled distribution drew on
matplotlib's stock 12/10/10 while every other chart in the app drew on this
project's 16/14/12. `spectrum.py`'s own header already called that out as
something to fix. It is fixed, so a distribution saved before this looks
slightly different from one saved after, and that is the one exception to
"an unstyled render is unchanged".

## Phase 2: a plot you can put in a paper

`fmt` has been in the vocabulary since it was written and nothing has ever read
it. `app/plots/store.py` writes `<version>.png`, `version_path` looks for
`.png`, the image route serves `image/png` and the download names `.png`. P1.5
made that honest; this makes it work. A group that publishes needs vector
output, and this is the one improvement here that a user would call a feature
rather than a repair.

- [todo] P2.1: the store carries a per-version format instead of assuming PNG
- [todo] P2.2: the image route and the download name follow the stored format
- [todo] P2.3: `fmt` renders SVG and PDF, and the refusal added in P1.5 goes

## Phase 3: charts we have the data for and do not draw

From a census of every job summary in the dev data directory, ranked by how
many jobs already carry the data. Each is a data adapter onto renderers that
exist, not a new plotting mechanism; `render_series_plot`'s four marks already
cover the shapes.

- [todo] P3.1: MO energy-level diagram from `orbital_table` (present on 156 of
  162 jobs, and on nothing else). Occupied and virtual levels as `levels`
  ticks, HOMO and LUMO marked, the gap annotated. Reads across jobs too, which
  is what "how does the gap move with the functional" means.
- [todo] P3.2: optimization convergence trace from `optimization_energies_hartree`,
  with `max_force_eh_bohr`/`rms_force_eh_bohr` when the engine reports them.
  `app/plots/intrinsic.py` excludes this as client-side-only with no rendered
  file behind it; that exclusion is now as stale as the NEB and PES ones it
  already lost, and a convergence trace should be downloadable, attachable and
  restyleable like every other chart.
- [todo] P3.3: transition-composition chart from `dominant_transitions` (156
  jobs). Which orbital pairs carry each excited state, as a horizontal bar per
  state. It is the thing a chemist asks for immediately after seeing a peak,
  and there is no view of it anywhere in the app.
- [todo] P3.4: label the sticks `render_uvvis_plot` already draws. They are
  there and anonymous; naming the strongest few with their state and oscillator
  strength is a small change to one renderer.
- [todo] P3.5: reaction profile across jobs -- connected levels with the
  barrier annotated in kcal/mol. `levels` draws the ticks today and nothing
  joins them, which is most of the distance to the standard figure.
- [todo] P3.6: thermochemistry breakdown from `zero_point_energy_hartree`,
  `enthalpy_hartree`, `gibbs_free_energy_hartree` and `entropy_hartree_per_K`:
  electronic energy to Gibbs free energy as a waterfall. Every frequency job
  produces all four.
- [todo] P3.7: Wigner sampling diagnostics from
  `per_sample_harmonic_potential_hartree` and the `n_modes_*` counters. The
  standard check that an ensemble is sane, from data already pooled.
- [todo] P3.8: difference between two spectra. `kind="spectra"` already
  resamples every curve onto one shared grid, so the subtraction is the only
  new part, and "how does this method differ from that one" is not answerable
  by an overlay once the curves are close.

## Phase 4: smaller things the review turned up

- [todo] P4.1: the spectrum renderers do not reserve headroom for their legend
  the way `render_series_plot` does, so at a large `font_size` the legend sits
  on top of the peak. Visible in the P1.3 end-to-end image.
- [todo] P4.2: `legend` takes a matplotlib location string only, so there is no
  way to put a legend outside the axes, which is what a seven-series
  comparison needs.
- [todo] P4.3: `custom` has `y_units` and no `x_units`, so a scan coordinate
  cannot be redrawn in different units the way a y axis can.
- [todo] P4.4: `render_uvvis_plot` hardcodes its stick colour and is the only
  renderer in the file whose `savefig` omits `facecolor="white"`.
- [todo] P4.5: a distribution applies one `xlim` to every panel, because
  `st.apply` runs per panel and the style has one x axis in it. A bond panel
  and an angle panel do not share a range, so the key is close to unusable
  there; it wants to be per panel or refused.
- [todo] P4.6: the equilibrium annotation on a distribution keeps a hardcoded
  `fontsize=11`, so it stays put while the rest of the panel scales with
  `font_size`.
- [todo] P4.7: `plot_job_comparison`'s docstring says the alias table exists
  because "energy" means a different key per job, but every alias tuple holds
  exactly one key. On the 157 jobs with a result on disk, `total_energy_hartree`
  is universal, so nothing is broken; the comment describes a mechanism that is
  not being used and should either be made true or corrected.
