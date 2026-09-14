# Closed Tracker: the plotter, and CASSCF intensities on BAGEL

**Closed 2026-09-01. 29 steps across 5 phases, all done.** The `merged:` row on
each phase records the commit it landed as.

Phases 1 to 4 are the plotter. Phase 5 is unrelated and was added here rather
than in a second tracker, because exactly one tracker is active at a time.

Two items were struck rather than built, both after looking at what they would
actually buy: a reaction profile as its own plot kind (mostly served already by
`kind="neb"` and by `custom` + `levels`), and kcal/mol as a relative unit
(against the standing convention that energy profiles are in eV). Re-running
the ensemble that the Phase 5 bug had spoiled was struck too; the maintainer
repeats such a job directly.

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

The tracker this replaced is
[`2026-08-backlog-and-job-manager-controls.md`](2026-08-backlog-and-job-manager-controls.md)
-- 8 steps across 5 phases, closed 2026-08-31. Nothing has superseded this one
yet: `docs/TRACKER.md` is a placeholder until the next plan starts.

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

- merged: 28ba51f

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

- [done] P2.1: the store carries a per-version format instead of assuming PNG
  evidence: tests/backend/plot_04_vector_export.py → "an SVG and a PDF are written beside the PNG, recorded per version, and pruned together with it"
- [done] P2.2: the download follows the stored format; display stays PNG
  evidence: tests/backend/plot_04_vector_export.py → "version_path still defaults to PNG for the runners' job artifacts; only download_plot asks for the vector"
- [done] P2.3: `fmt` renders SVG and PDF, and the refusal added in P1.5 goes
  evidence: tests/backend/plot_03_style_actually_lands.py → "png/svg/pdf accepted and carried, case-folded; tiff still refused"

- merged: 6e2a739

**The shape worth keeping.** A vector is rendered ALONGSIDE the PNG, never
instead of it. The Plots panel, the chat bubble and the job drawer all display
a version through an `<img>`, and a PDF cannot be shown that way at all. So
the app always has something to display, `version_path` still answers with a
PNG for every existing caller (the runners record one as a job artifact), and
`fmt` decides only what a download hands over. The cost is a second pass
through the renderer, paid only when somebody asked for a vector.

## Phase 3: charts we have the data for and do not draw

From a census of every job summary in the dev data directory, ranked by how
many jobs already carry the data. Each is a data adapter onto renderers that
exist, not a new plotting mechanism; `render_series_plot`'s four marks already
cover the shapes.

- [done] P3.1: MO energy-level diagram from `orbital_table`
  evidence: tests/backend/plot_05_job_charts.py → "occupancy decides what is occupied, so a fractional CASSCF active still counts; window narrows a 132-row table; drawn live from job 17d3825f3c68 with a 8.67 eV gap
- [done] P3.2: optimization convergence trace, and intrinsic registration for it
  evidence: tests/backend/plot_05_job_charts.py → "relative to the final energy in kcal/mol, log by default, standing down for a run that overshoots; drawn live from job 395ce412a547 over four decades"
- [done] P3.3: excited-state map from energies, intensities and `dominant_transitions`
  evidence: tests/backend/plot_05_job_charts.py → "a state with no label keeps its bar; a job with no intensities draws and says so rather than refusing"

  Reshaped from the tracker's original wording once the data was looked at.
  `dominant_transitions` is ONE string per state ("28->30 (0.73)"), not a
  decomposition, so "which orbital pairs carry each state, as a horizontal bar
  per state" was describing data this app does not have. What it does have is
  each state's energy, its oscillator strength and its dominant pair, and those
  three together answer the question the original item was really asking:
  which state is the bright one, and what does it involve.
- [done] P3.4: label the sticks `render_uvvis_plot` already draws
  evidence: app/chemistry/spectrum.py `_label_sticks` → "the four brightest are named S<n> with their f, and a stick below 2% of the strongest is left unlabelled"
**Struck 2026-08-31: P3.5, a reaction profile as its own plot kind, and P3.5b,
kcal/mol as a relative unit.** The plot kind was the weakest of the eight and
is mostly served already -- `kind="neb"` draws a reaction path with the TS
marked, and `custom` + `levels` + `y_reference_hartree` draws reactant/TS/
product as levels, so a new kind bought connecting guides and a barrier label
on a chart that already shows the barrier.

P3.5b then proposed adding kcal/mol to `units.RELATIVE_UNITS` so a barrier
could be drawn in the unit the wider literature quotes. The user struck that
too, and stated the convention: **energy profiles in eV wherever possible.**
So the absence of kcal/mol from `ENERGY_UNITS` and `RELATIVE_UNITS` is a
decision, not a gap, and `units.py` now says so where someone would otherwise
add it back. Two charts from Phase 3 were written in kcal/mol before this was
checked and have been converted; see the commit that did it.

- [done] P3.6: thermochemistry breakdown, electronic energy to Gibbs free energy
  evidence: tests/backend/plot_05_job_charts.py → "the steps sum to G - E by construction; the entropy term is the measured G - H rather than a TS recomputed from S and T; drawn live from job 0d61b995b535's real numbers"

  **Reopened after the diagnosis in this tracker was found to be wrong.** It
  was recorded as blocked because "the one frequency job in the data directory
  carries no electronic energy", read as the quantity being unavailable and
  needing a cross-job lookup into the parent optimization. It is not. PySCF's
  frequency runner calls `mf.kernel()` and hands the result straight to
  `pyscf_thermo.thermo`, which reads `mol` and `e_tot` and nothing else -- so
  every enthalpy and Gibbs value those jobs already report was DERIVED from
  the electronic energy, and the runner simply never wrote it into the
  summary. ORCA has recorded its own as `electronic_energy_hartree` all along.
  One field in one runner (three call sites: plain SCF, PDFT, CASSCF), not a
  cross-job lookup.

  BAGEL is a genuine absence and stays one: its Hessian module prints no
  thermochemistry at all, which the runner already records in
  `thermochemistry_note`, so there is nothing to add there and the chart
  refuses those jobs naming what is missing.

  Jobs that finished before this still have no electronic energy recorded and
  cannot be charted without re-parsing their raw output, which is kept as an
  artifact.

- [done] P3.7: Wigner sampling diagnostics
  evidence: tests/backend/plot_05_job_charts.py → "distribution in kcal/mol above equilibrium with the mean marked; the temperature reaches the figure; one sample refused"
- [done] P3.8: difference between two spectra
  evidence: _plot_spectra's `difference` flag → "drawn live from two real excited-state jobs; a single job is refused by name rather than subtracting from nothing"

- merged: f4b1138

**The defect P3.1 turned up, which is the one worth remembering.** A CASSCF
job exports NATURAL orbitals: occupancies are real, and every active orbital's
energy is recorded as exactly 0.0 because the export carries no eigenvalue for
it. The first working version of the diagram drew nine levels stacked at zero,
called the top one the HOMO, and annotated a 4.50 eV gap measured from a number
nobody computed. 53 of the 156 orbital tables in the data directory are that
shape and 103 are canonical. It refuses now, in the renderer on the data's own
signature and in the tool on `orbital_table_kind`, relaying the summary's own
`frontier_energy_unavailable` wording. A fabricated quantity on an axis is
worse than no chart.

## Phase 4: smaller things the review turned up

None of these was a broken chart. They are the places where a reasonable
request had nowhere to land, or where a fixed number stayed fixed while
everything around it scaled with `font_size`.

- [done] P4.1: the spectrum renderers reserve room for their own legend
  evidence: tests/backend/plot_06_legend_units_panels.py → "headroom lifts the axis above the data, and is skipped for an explicit ylim, a legend that is off, and a legend outside the axes"
- [done] P4.2: a legend can be placed outside the axes
  evidence: tests/backend/plot_06_legend_units_panels.py → "look.legend = 'outside' is accepted and renders differently from any in-axes location"
- [done] P4.3: `custom` converts its x axis, not only its label
  evidence: tests/backend/plot_06_legend_units_panels.py → "x_units/x_units_from go through the same units module y does, points re-sorted because nm runs the other way from eV; refused on a categorical axis"
- [done] P4.4: `render_uvvis_plot` stops hardcoding its stick colour and saves with facecolor
  evidence: app/chemistry/spectrum.py → "sticks follow st.accent, and the one savefig in the file that omitted facecolor='white' no longer does"
- [done] P4.5: one `xlim` no longer lands on every distribution panel
  evidence: tests/backend/plot_06_legend_units_panels.py → "a bond-range xlim leaves a two-panel figure unchanged rather than silently emptying the angle panel; a single-panel one still honours it"
- [done] P4.6: the equilibrium annotation scales with the rest of the panel
  evidence: tests/backend/plot_06_legend_units_panels.py → "the label grows with font_size instead of staying pinned at 11pt"
- [done] P4.7: `plot_job_comparison`'s docstring stops claiming a mechanism it is not using
  evidence: app/agent/tools.py → "every alias holds exactly one key and total_energy_hartree is universal across the 157 jobs with a result on disk; recorded as where a per-job alias would go, not as something already handled"



- merged: c9a3b8a

**P4.1 and P4.2 turned out to be one thing.** Reserving headroom and choosing
where a legend goes both belong to the style, not to a renderer, so they moved
onto `PlotStyle` as `reserve_legend_headroom` and `place_legend`.
`render_series_plot` had carried a private copy of the headroom logic since it
was written and the spectrum renderers had none at all, which is why an
ensemble spectrum at `font_size: 22` put its legend on the peak. That was
visible in the P1.3 verification image and is what put both items on this list.

## Phase 5: BAGEL computes CASSCF oscillator strengths, and now says so

Unrelated to plotting, added here rather than in a second tracker because
exactly one tracker is active at a time.

Reported as "the capability table thinks BAGEL cannot do this". The table was
right all along: `capabilities.py` has carried `osc_strengths=True` for
bagel+casscf since it was written, and `supports()` offered BAGEL for a CASSCF
`wigner_spectra` ensemble on the strength of it. The break was one layer down.
`bagel_runner._build_input` emitted the forces+dipole block only for CASPT2, so
a CASSCF job carrying `want_oscillator_strengths: True` had the flag silently
dropped, and nothing anywhere recorded that it had been.

Job `bc26178c7406` in this checkout's data directory is what that cost: a
50-sample uracil CASSCF ensemble, `want_oscillator_strengths: True` in its
spec, `oscillator_strengths: None` in every one of the fifty children, no note,
and a pooled spectrum reporting "50 of 50 samples had no intensity data".

- [done] P5.1: a CASSCF job asking for intensities emits a forces+dipole block
  evidence: tests/backend/bagel_01_casscf_oscillator_strengths.py → "dipole set, grads empty, nested method restating this job's own CASSCF including nspin; absent when not asked for and when there is only one state"
- [done] P5.2: the dipole-section parser serves CASSCF and CASPT2 without confusing them
  evidence: tests/backend/bagel_01_casscf_oscillator_strengths.py → "CASSCF read as [0.000646, 0.38971] from an output carrying both sections; CASPT2 read as its own numbers; ground-state-relative only"
- [done] P5.3: a run that asked and got nothing says so
  evidence: tests/backend/bagel_01_casscf_oscillator_strengths.py → "a missing section parses to None, which is what attaches oscillator_strengths_note"
- [done] P5.4: live BAGEL run, end to end through run_casscf
  evidence: tests/backend/bagel_01_casscf_oscillator_strengths.py → "water/cc-pVDZ CAS(4,4), 3 states, BAGEL 1.2.2: f = [0.014916, 0.0], no note, lengths matching excitation_energies_eV"
- [done] P5.5: routing stops asserting ORCA is the only engine that can
  evidence: tests/backend/bagel_01_casscf_oscillator_strengths.py → "with no engine named the job still lands on ORCA, by preference order; BAGEL accepted when named; PySCF filtered out because it genuinely has no route"
- [done] P5.6: docs and README carry the corrected claim
  evidence: scripts/check_capability_matrix.py → "791 assertions across 19 capability rows and 20 tasks, docs in sync"

### Two things worth keeping

**`grads` is empty for CASSCF and deliberately not for CASPT2.** The user's own
verified input uses an empty list: no gradient is wanted, the block is there
for its dipole side effect, and BAGEL still prints the full section. The CASPT2
path asks for one gradient per state and is live-verified in that shape. Do not
unify them on the assumption that what holds here holds there.

**The first verification attempt failed for a reason that was not the code.**
Water/STO-3G with CAS(4,4) leaves `nvirt = 0`, and BAGEL's dipole path then
multiplies a zero-dimension matrix and floods `Intel oneMKL ERROR: Parameter 9
was incorrect on entry to cblas_dgemm`. That reads exactly like this host's
known BAGEL/MKL instability and is not it. cc-pVDZ ran clean in 6.6 seconds.

### The cascade

No gating change was needed: `supports()` already said yes, the ensemble
orchestrator already passes `want_oscillator_strengths` down to its children,
and a child (`single_point`/`ee`, casscf) already resolves to `run_casscf`,
which is the function that now asks. A BAGEL CASSCF nuclear-ensemble spectrum
therefore works from this commit on, and the reason it never did was never in
that path.

An ensemble that finished before this cannot be repaired in place, since the
dipole section was never computed at all; it has to be re-run. That is not
tracked here as work -- the maintainer re-runs such a job directly.

- merged: 0f0d560
