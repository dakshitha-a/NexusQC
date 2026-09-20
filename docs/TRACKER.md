<!-- artifact: https://claude.ai/artifact/2QtKjAAMthQ1dmqSr8pbVW -- re-render with scripts/render_tracker_html.py and re-publish to THIS url -->
# Active Tracker: named active spaces mean the table they were read from

**Opened 2026-09-20.** Eight phases. The tracker this replaces is
[`2026-09-plan-amendments-and-subagents.md`](trackers/2026-09-plan-amendments-and-subagents.md),
which closed on 2026-09-16. **Exactly one tracker is active at a time.**

## Rules (enforced by `scripts/check_tracker.py`)

- Step status is exactly one of `todo` | `in-progress` | `done`.
- A step may be marked `done` **only with an evidence field**: one path that
  exists on disk plus a one-line observed result.
- The tracker edit ships **in the same commit** as the step's final change.
- A phase's `merged` row records the commit hash the stage landed as.

Format for a step row:

```
- [status] P<phase>.<step>: <short name>
  evidence: <path> → "<observed result>"   (required when done)
```

Re-render and re-publish the artifact at every step completion:

```bash
python3 scripts/render_tracker_html.py /tmp/tracker.html
```

---

## Why this plan exists

In the "uracil l-pdft" conversation the user ran an L-PDFT(12,9)/cc-pVDZ job
on PySCF, saw two sigma orbitals in the default active window, and asked to
swap them for a lone pair and a pi* orbital read off that job's orbital
table. The agent could not resolve "swap" because no CASSCF-family result
records which of its own orbitals were active; and the full list the user
then gave was applied with `sort_mo` to a fresh SCF's canonical orbitals,
not to the natural-orbital table the numbers were read from. A third defect
sat underneath: PySCF's `project_init_guess` keeps only the source's
core+active columns, so a source virtual index could never survive the
projection even with `initial_orbitals_job_id` set. Nothing verified
afterwards which orbitals ended up active, so a wrong space and a right one
produced the same report.

The plan (`.claude/plans/look-at-the-latest-splendid-aurora.md`) makes an
orbital index mean a position in one named table, records every CASSCF-family
job's own active window and a per-orbital mapping back to the reference with
a warning when the optimizer rotates a requested orbital out, teaches the
agent the swap pattern, and carries the record across BAGEL and ORCA and into
the orbital table in the drawer. Two black-box figures found in the same
conversation (a "HOMO/LUMO gap" thresholded from natural occupations, and
`dominant_transitions` computed in pseudo-canonical ordering) are fixed with
it, as is the CAS recommendation job whose listed orbitals did not index its
own table.

Decision the user made on 2026-09-20: when indices are named without a
source, an attached or named job is the reference; otherwise the draft asks.

## Phase 0: Tracker

- [done] P0.1: Open this tracker, publish it as an artifact
  evidence: docs/TRACKER.md → "published from scripts/render_tracker_html.py output; URL recorded in the header comment; check_tracker PASS on 21 steps"

## Phase 1: PySCF applies indices against the source and records the window

- [done] P1.1: `app/chemistry/jobs/active_space.py`: window, overlap mapping, annotate, warning text
  evidence: app/chemistry/jobs/active_space.py → "tests/backend/active_02_recorded_active_space.py's constructed-matrix section: a 50/50 rotated pair scores 1 each by row sum, a replaced orbital scores 0, the window is ncore+1..ncore+ncas, rows in it are flagged, the warning names the lost orbital, the reference table and the replacing row, and nothing is said when everything is retained"
- [done] P1.2: `_apply_orbital_choices` returns the initial active block; sort source columns before projecting; `fresh`; SCF converged first
  evidence: app/chemistry/jobs/pyscf_runner.py → "active_02 mechanisms 2 and 3: with the source named, each starting active orbital overlaps the source's table column at above 0.999 while the same numbers against the fresh SCF pick different orbitals; a source core row (3) and virtual rows (9, 10) arrive intact; an index beyond the source table is refused; `fresh` normalises to no source"
- [done] P1.3: `_casscf_molden_and_table` writes natural orbitals from one `canonicalize` call and annotates the table
  evidence: app/chemistry/jobs/pyscf_runner.py → "active_02: the written molden's occupations equal the table's row for row and its columns are orthonormal in the AO metric; job A records window [4,5,6,7], the echo [4,5,7,8], weights for exactly the named rows with the two occupied ones above 0.95"
- [done] P1.4: `dominant_transitions` in the natural-orbital basis; `facts.py` drops HOMO/LUMO on natural tables; `active` shortcut
  evidence: app/chemistry/jobs/facts.py → "active_02: the SA-CASSCF excited state's dominant transition is between rows of the active window and runs from the more-occupied natural orbital to the less-occupied one; facts.canonicalize withholds homo_index and homo_lumo_gap_eV for a natural table and records frontier_orbitals_unavailable; app/agent/tools.py's `active` shortcut slices the window and `homo` on a natural table returns that reason"
- [done] P1.5: Every CASSCF-family call site threads the initial block; `_record_named_active_space` deleted
  evidence: app/chemistry/jobs/pyscf_runner.py → "grep finds no _record_named_active_space, _apply_initial_orbitals or _apply_named_active_space; active_02 covers run_casscf, SA-CASSCF, run_lpdft and run_geometry_optimization (window [4,5,6,7] from mc_final, weights present, no echo on a default-space job); scripts/casbench/legacy_cas_reco.py adapted and imports; tests/backend/p8_01_orbital_reuse.py renamed to _apply_orbital_choices and now removes its fixture jobs"
- [done] P1.6: Preview scripts show the source load, sort and projection
  evidence: app/chemistry/jobs/pyscf_runner.py → "_orbital_choice_preview_lines is shared by the CASSCF and PDFT previews: with a source it shows molden.load, sort_mo on the source and project_init_guess(use_hf_core=False); without one the sort_mo line says the numbers index this run's own SCF orbitals; tests/backend/active_01_named_orbitals.py 44/44"
- [done] P1.7: `run_cas_recommendation` writes its table from the projected set
  evidence: tests/backend/cas_12_orbital_identity.py → "10/10: the listed 1-based rows of the written molden are the recommended orbitals one by one (overlap above 0.999), the recommended block holds exact 2/0 occupations, the table matches the file row for row, and the file carries the full set; the summary also records active_orbital_window and per-row active flags"

## Phase 2: Reproduction script

- [done] P2.1: `tests/backend/active_02_recorded_active_space.py`: window, mapping, mechanisms 2 and 3, opt and SA paths, warning path, source acceptance
  evidence: tests/backend/active_02_recorded_active_space.py → "39/39 on water/6-31G CASSCF(4,4): constructed-matrix mapping and warning; job A fresh named [4,5,7,8]; mechanisms 2 and 3 by overlap of starting blocks against the source molden; job B end to end, where dropping A's correlating orbital makes the optimiser rotate row 4 out (weight 0.0) and the warning names it, while re-requesting A's own window keeps every orbital above 0.95 and reproduces A's energy to 1e-6; SA-CASSCF transitions name table rows; L-PDFT and a geometry optimisation carry the record; six fixture jobs removed. Source acceptance (HF and cas_reco sources) is asserted in Phase 3's elicitation script"

## Phase 3: Elicitation, parameters, agent teaching

- [todo] P3.1: Draft tool passes conversation and attached job ids to validation
- [todo] P3.2: Elicitation: attached job as reference, candidate question, `fresh`, occupancy sanity, source problems are questions
- [todo] P3.3: Parameter help for `active_space_orbital_indices` and `initial_orbitals_job_id`
- [todo] P3.4: `update_job_draft` and `check_job_status` docstrings, job watcher notice, prompt sentence
- [todo] P3.5: Existing tests updated; new elicitation script

## Phase 4: BAGEL and ORCA

- [todo] P4.1: BAGEL records its window and, with a source, the mapping
- [todo] P4.2: ORCA records its window and active flags

## Phase 5: Frontend

- [todo] P5.1: OrbitalTable marks active rows, shows the reference column, note and warning; drawer wiring
- [todo] P5.2: Browser verification with a stubbed payload and a screenshot looked at

## Phase 6: Docs and changelog

- [todo] P6.1: ARCHITECTURE.md, README.md, QM_CAPABILITIES.md, CHANGELOG.md

## Phase 7: Acceptance on the dev stack

- [todo] P7.1: Uracil L-PDFT(12,9)/cc-pVDZ default, then the literal swap request through `invoke_turn` with the job attached
- [todo] P7.2: The rerun's mapping, weights and window reported; test jobs and thread deleted
