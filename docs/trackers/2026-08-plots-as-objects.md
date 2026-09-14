# Active Tracker: plots as first-class objects

Live status of the plan in motion. **Exactly one tracker is active at a time.**

## How tracking works here

Development is linear, so there is never a reason to have two trackers open at
once. Each plan, feature or non-trivial request gets its own tracker, this file
is whichever one is currently in motion, and when its plan is finished the file
is closed out and moved to [`trackers/`](trackers/), then a fresh one starts
here for whatever comes next.

Closed trackers are kept, never deleted. They are the audit trail for why the
code looks the way it does, and code comments cite them by path:

- [`trackers/2026-08-job-system-overhaul.md`](trackers/2026-08-job-system-overhaul.md)
  ‑ the 10-phase job-type/toolchain/agent overhaul, closed 2026-08-22, 72 steps
  across 5 merged phases.

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
- A phase's `merged` row records the commit hash the stage landed as.

Format for a step row:

```
- [status] P<phase>.<step>: <short name>
  evidence: <script/command> → "<observed result>"   (required when done)
```

---

## Phase 1: A real chart spec

The agent could not draw a categorical chart. Asked for the excitation energies
of seven methods with the method names on the x axis and a stack of horizontal
lines per state, it correctly refused: `plot(kind="custom")` resolved its x axis
from a numeric summary field and only ever drew a connected line.

- [done] P1.1: Three-stage plot pipeline (rows / placement / marks), categorical x, four mark styles
  evidence: app/chemistry/spectrum.py → "render_series_plot draws line/scatter/bar/levels over one data shape; the seven-method level diagram renders with all seven columns, per-state colours and a two-entry legend"
- [done] P1.2: x_labels keyed by job id, so a dropped job cannot shift labels onto the wrong column
  evidence: app/agent/tools.py → "_column_labels refuses a positional list when rows are jobs, naming the shift as the reason; accepts a list only for a single job's own arrays, where nothing can drop"
- [done] P1.3: A missing value leaves a gap instead of deleting a column
  evidence: app/agent/tools.py → "oscillator-strength chart across seven methods keeps EOM-CCSD and PySCF CASSCF as labelled empty columns; under the previous code both vanished silently"
- [done] P1.4: kind="comparison" folded onto the same pipeline, keeping only its per-job alias resolution
  evidence: app/agent/tools.py → "render_job_comparison_plot deleted; alias resolved to a literal key per job via y_field_by_job, verified drawing five real columns and two honest gaps across three different energy keys"
- [done] P1.5: field and width moved into spec; tool surface still within budget
  evidence: tests/backend/agent_01_token_budget.py → "13/13 checks passed; plot takes 5 parameters, widest tool 6, fixed surface 7,287/10,000 tokens (+372 for the new docstring)"
- [done] P1.6: The model reaches for the new capability unprompted
  evidence: tests/e2e/e2e_09_plot_tools.py → "P-custom-levels added; a live invoke_turn with the original request and no hint about the spec emitted style='levels', omitted x_field, and wrote x_labels distinguishing the TDDFT and TDA runs, which the auto-generated job names cannot"
- [done] P1.7: Legend never covers data, on linear or log axes
  evidence: app/chemistry/spectrum.py → "explicit headroom before the legend, multiplicative on a log axis; the CASSCF ORCA S2 level at 11.98 eV is clear in both, having been covered in the first render"
- merged: 4056ed2

## Phase 2: Plot identity and conversational editing

A plot becomes a stored record (spec, source jobs, cached numbers) rendered on
demand, so an edit is a patch and a re-render rather than a fresh image.

- [done] P2.1: Per-owner plot store, reclaimed when a plot's last source job is gone
  evidence: app/plots/store.py → "a three-source plot with one job missing survives, a single-source plot whose job is gone is reclaimed, and a plot with no sources is never swept"
- [done] P2.2: ownership_index admits 'plot'; plot bytes counted in the existing job quota category
  evidence: app/auth/db.py → "kind CHECK widened by the same idempotent DROP/ADD used for 'upload'; plot bytes fold into _job_usage_by_owner, and purge_user_data deletes an account's plots directly rather than waiting for them to orphan"
- [done] P2.3: Every plot kind renders through the store, with versioned PNGs
  evidence: app/agent/tools.py → "one _save_plot path for custom, uvvis, ir, ensemble and histogram; uvvis/ir/ensemble also keep their job artifact key, pointing at the same file, so the job drawer's panels are unaffected"
- [done] P2.4: plot(kind="edit", plot_id=..., spec=<patch>) merges and re-renders
  evidence: app/agent/tools.py → "editing a level diagram with {log_y, series:[{label:S2,color}]} pinned v2, kept v1, matched the series by label and preserved its y_field; a missing plot id and an empty patch both refuse with the reason"
- [done] P2.5: New PLOT_ARTIFACT marker and the matching frontend regex, all emitters moved together
  evidence: frontend/src/chat/MessageBubble.tsx → "zero remaining job_id/key emitters; marker is plot_id+version, tsc --noEmit clean"
- [done] P2.6: Version numbering survives pruning
  evidence: app/plots/store.py → "a monotonic counter, not len(versions): eight renders at MAX_VERSIONS=5 kept v4..v8 with five distinct files, where deriving from the list length had produced v4,v5,v6,v6,v6 and silently overwrote versions older messages still pointed at"
- merged: 76cfb10

## Phase 3: The Plots panel

- [done] P3.1: server/routes/plots.py (list, image, download, rename, delete), ownership-scoped
  evidence: tests/frontend/plots_01_panel.spec.mjs → "8/8 in chromium against the compose stack; caught check_owner_or_admin being handed the request instead of the user, which 500'd every image fetch and which no code read or type check would have found"
- [done] P3.2: Job-intrinsic plots registered as records when a job completes
  evidence: app/plots/intrinsic.py → "registering against a real completed excited-state job produced its UV/Vis record; re-running is a no-op rather than a duplicate or a pointless new version"
- [done] P3.3: PlotsPanel in the instrument panel, with attach, download and delete per row
  evidence: tests/frontend/plots_01_panel.spec.mjs → "thumbnail loads from the plots route (naturalWidth 2400, not a broken-image box), delete is a two-click confirm that dismisses cleanly, attach puts a chip in the composer"
- [done] P3.4: Collapsed-rail icon and layout store entry
  evidence: frontend/src/app-shell/RightDock.tsx → "plotsCollapsed added to the persisted layout store and an icon added to the hand-maintained collapsed strip, without which the section disappears when the dock is collapsed"
- [done] P3.5: The job drawer's spectrum panels still serve, now that a spectrum PNG lives in the plot store
  evidence: tests/frontend/plots_01_panel.spec.mjs → "GET /api/jobs/<id>/artifacts/uvvis_spectrum returns 200 against the compose stack; the artifact route's containment check had to admit the plot store as a second root, and until it did every spectrum panel in the drawer would have 403'd"
- merged: d4a7909

## Phase 4: Attach and ask

- [done] P4.1: plot_ids on MessageIn, attached-plot store, composer chips
  evidence: tests/frontend/plots_01_panel.spec.mjs → "attaching a plot renders composer-detach-plot-<id>; plot_ids travels MessageIn to _run_turn as its own branch beside job_ids and frame_id"
- [done] P4.2: plot_context_summary emits the spec plus the resolved numbers as a table
  evidence: app/plots/store.py → "an attached seven-method level diagram renders as a markdown table of S1/S2 against the seven method names, from the record's cached numbers rather than a description of an image the model cannot see"
- merged: d4a7909
