<!-- artifact: https://claude.ai/artifact/2QtKjAAMthQ1dmqSr8pbVW -- re-render with scripts/render_tracker_html.py and re-publish to THIS url -->
# Closed Tracker: named active spaces mean the table they were read from

**Closed 2026-09-20. Twenty-three steps in nine phases, all done.**
No tracker is active until the next plan begins.

**Opened 2026-09-20.** Nine phases. The tracker this replaces is
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

- merged: 03f4c27

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

- merged: f0bce36

## Phase 2: Reproduction script

- [done] P2.1: `tests/backend/active_02_recorded_active_space.py`: window, mapping, mechanisms 2 and 3, opt and SA paths, warning path, source acceptance
  evidence: tests/backend/active_02_recorded_active_space.py → "39/39 on water/6-31G CASSCF(4,4): constructed-matrix mapping and warning; job A fresh named [4,5,7,8]; mechanisms 2 and 3 by overlap of starting blocks against the source molden; job B end to end, where dropping A's correlating orbital makes the optimiser rotate row 4 out (weight 0.0) and the warning names it, while re-requesting A's own window keeps every orbital above 0.95 and reproduces A's energy to 1e-6; SA-CASSCF transitions name table rows; L-PDFT and a geometry optimisation carry the record; six fixture jobs removed. Source acceptance (HF and cas_reco sources) is asserted in Phase 3's elicitation script"

- merged: f0bce36

## Phase 3: Elicitation, parameters, agent teaching

- [done] P3.1: Draft tool passes conversation and attached job ids to validation
  evidence: app/agent/state.py → "attached_job_id and attached_jobs_this_turn live beside the marker (graph.py imports the former; tools.py both); tests/backend/active_03_reference_table.py: the current turn's attachments are the run before the last user text, oldest first, an earlier turn's is excluded; _state_for_validation in tools.py hands validate_draft conversation_job_ids (active ids plus every attached id) and attached_job_ids"
- [done] P3.2: Elicitation: attached job as reference, candidate question, `fresh`, occupancy sanity, source problems are questions
  evidence: tests/backend/active_03_reference_table.py → "26/26: an attached job becomes the reference without a question and the card says so; with candidates and no pointer the draft asks, listing usable jobs by label and id with options plus `fresh`; with nothing to read from it goes through against fresh orbitals and says so; an unusable source is a question when indices are named and a dropped note otherwise; an index beyond the source table is refused; four empty rows warn about the electron count and an omitted partly occupied row warns it becomes core; both resolved drafts stay READY under re-validation without external checks; HF and recommendation jobs are valid sources, running and other-engine jobs are not; `fresh` never reaches a runner (dropped in _build_spec_or_error)"
- [done] P3.3: Parameter help for `active_space_orbital_indices` and `initial_orbitals_job_id`
  evidence: app/chemistry/registry2/params.py → "the index help keeps the literal 'ONLY set this' (tests/backend/agent_09_unstated_parameters.py 0 failures) and says each number is a row of one job's table named in initial_orbitals_job_id, or `fresh`; the source help admits any same-engine job with a table and says the numbers index that table; tests/backend/agent_01_token_budget.py 13/13, elic_01 205/205, agent_06 18/18 and 0 failures"
- [done] P3.4: `update_job_draft` and `check_job_status` docstrings, job watcher notice, prompt sentence
  evidence: app/agent/tools.py → "update_job_draft's docstring carries the swap pattern beside the geometry one (read active_orbital_window, replace keeping the length, write the full list, name the job); check_job_status documents the `active` shortcut and why homo/lumo are absent on natural tables; job_watcher._agent_notice tells the model to report an active_space_warning before any energy. The prompt sentence was written and reverted: SYSTEM_PROMPT sat 14 bytes under its 6,144-byte budget (agent_01) and the rule lives where the model reads it at the moment of use"
- [done] P3.5: Existing tests updated; new elicitation script
  evidence: tests/backend/p8_01_orbital_reuse.py → "40/40 with the helper renamed, an HF source now accepted, and its five fixture jobs removed at exit; active_01 44/44; cas_12 10/10; mrpdft_01 153/153; active_03_reference_table.py is the new script"

- merged: a13417e

## Phase 4: BAGEL and ORCA

- [done] P4.1: BAGEL records its window and, with a source, the mapping
  evidence: tests/backend/active_04_engine_records.py → "8/8 structural: a named space reaches BAGEL's casscf block as `active`, and a summary with no molden on disk still records window [4,5,6,7] from nclosed; the record hangs off _add_orbital_table with the mapping taken between the source's and the job's moldens (active_space.molden_mapping, cross overlap in each file's AO metric). The live source/destination pair could not complete here: the source CASSCF converged (16 macro-iterations, E = -74.98699597) and BAGEL then crashed in its molden print block with 'dsyev/pdsyevd failed in Matrix', this host's documented MKL failure, so no molden or archive was written; docs/HANDOFF.md carries the re-verification for a host where BAGEL runs"
- [done] P4.2: ORCA records its window and active flags
  evidence: tests/backend/active_04_engine_records.py → "a real ORCA CASSCF(4,4)/STO-3G on water: window [4,5,6,7] from the electron count, ORCA's fractional-occupation rows lie inside it with no disagreement recorded, exactly those rows flagged, no mapping or echo on a default-space job, reference null; the record is written by _record_active_space on the single-point, optimisation and frequency CASSCF paths"

- merged: d5dddd8

## Phase 5: Frontend

- [done] P5.1: OrbitalTable marks active rows, shows the reference column, note and warning; drawer wiring
  evidence: frontend/src/jobs/OrbitalTable.tsx → "active rows carry the hairline on the index cell with the index in full text colour and a hover title, a From column appears when rows carry reference_index (sub-threshold weights in accent), the header line takes the drawer's activeSpaceNote and the warning renders above the table in accent; JobDetailDrawer composes the note from active_orbital_window, active_space_orbital_indices and initial_orbitals_source_job_id; tsc -b clean"
- [done] P5.2: Browser verification with a stubbed payload and a screenshot looked at
  evidence: tests/frontend/orbital_09_active_space_marks.spec.mjs → "7/7 in headless Chromium against the worktree's dev server proxied to the stack: exactly the window rows are marked, hairlined and titled, the From column shows '#5 · 0.67' style cells on active rows and '--' elsewhere, the header names the window and the reference table, the warning is above the table; the screenshot in docs/e2e-artifacts/ was looked at twice: an 'active' text tag made the sixth column clip in the 400px drawer and was replaced by the hairline alone, after which every column fits"

- merged: a13417e

## Phase 6: Docs and changelog

- [done] P6.1: ARCHITECTURE.md, README.md, QM_CAPABILITIES.md, CHANGELOG.md
  evidence: docs/ARCHITECTURE.md → "new section 'An orbital index is a position in one job's table' under the orbital-availability section: the three mechanisms, sort-then-project, the record and its threshold, the two figures, the recommendation table, no adapter for old jobs; README.md's 'Or name the orbitals outright' says which job's table the numbers are rows of, the swap phrasing and the rotation warning; QM_CAPABILITIES.md does not list the parameter and needed nothing; CHANGELOG.md Unreleased carries Added and Fixed entries; scripts/check_public_safe.sh PASS"

- merged: cae8db6

## Phase 7: Acceptance on the dev stack

- [done] P7.1: Uracil L-PDFT(12,9)/cc-pVDZ default, then the literal swap request through `invoke_turn` with the job attached
  evidence: app/agent/tools.py → "in-process on the worktree code with the host's Ollama (qwen3.8:27b), isolated in the worktree's data directory: job 1 (111 s) reproduced the user's run, S1 5.22 eV and S2 6.03 eV, window rows 24 to 32 with sigma C7-C1 at 26 and sigma* at 32; the turn 'repeat this calculation but swap out orbital 26 for 21 and 32 for 37' with job 1 attached made the model call check_job_status(fields=['active_orbital_window']), start_job_draft, then update_job_draft with active_space_orbital_indices [21, 24, 25, 27, 28, 29, 30, 31, 37] and initial_orbitals_job_id = job 1, and the draft reached the approval interrupt in 30 s with no question asked"
- [done] P7.2: The rerun's mapping, weights and window reported; test jobs and thread deleted
  evidence: app/chemistry/jobs/active_space.py → "job 2 from the draft's parameters converged in 21 s from job 1's orbitals; reference_orbital_weights 21: 0.9998, 24: 0.9999, 25: 1.0, 27: 0.9999, 28: 0.9962, 29: 0.9999, 30: 0.9994, 31: 0.9943, 37: 0.9055, no warning; its window rows 24 to 32 are pi, pi, pi, pi, n(O8), pi, pi*, pi*, pi*(C4-O5, reference 37) with no sigma; ground state 0.8 mEh lower, S1 4.75 eV (29->30) and S2 5.06 eV (28->30) against 5.22 and 6.03 before. On the default job the fresh-HF window's own weights (26: 0.01, 32: 0.004) showed that a warning must need a request, so annotate now warns only for a named list or a reused job's space; active_02 40/40 with that asserted. Both jobs and the thread were deleted"

- merged: 4730f24

## Phase 8: Deploy and release (raised by the user mid-run)

Asked while Phase 3 was in progress: "bring the dev stack up to date when
you are done and do a release push". Runs last, after the tracker above is
closed out, since a release publishes whatever `main` holds.

- [done] P8.1: Integrate into `main`, push `origin`, remove the worktree; `scripts/update.sh` brings the dev stack onto the commit (raised mid-run)
  evidence: scripts/update.sh → "main fast-forwarded to 3a7ddc2 (seven commits) and pushed to origin; the worktree and its branch removed; the dry run passed every gate with no jobs running and no destructive changes, and the real update took its backup, rebuilt the api image, installed frontend/dist from the image stamped 3a7ddc27de72, and reported healthy at https://127.0.0.1:8444; the served bundle carries the new orbital-table markup"
- [done] P8.2: `scripts/release.sh 1.2.0` publishes the tag and release; a fresh Unreleased section follows (raised mid-run)
  evidence: scripts/release.sh → "the 1.2.0 dry run on 3a7ddc2 passed on main, clean tree, both remotes, public-safety scan, main matching origin and a free tag, refusing only for the missing changelog section that this close-out commit writes; the publish runs from the commit after this one and the tag is recorded in the Unreleased commit that follows it"
- merged: 3a7ddc2
