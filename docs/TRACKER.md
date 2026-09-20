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

- [todo] P1.1: `app/chemistry/jobs/active_space.py`: window, overlap mapping, annotate, warning text
- [todo] P1.2: `_apply_orbital_choices` returns the initial active block; sort source columns before projecting; `fresh`; SCF converged first
- [todo] P1.3: `_casscf_molden_and_table` writes natural orbitals from one `canonicalize` call and annotates the table
- [todo] P1.4: `dominant_transitions` in the natural-orbital basis; `facts.py` drops HOMO/LUMO on natural tables; `active` shortcut
- [todo] P1.5: Every CASSCF-family call site threads the initial block; `_record_named_active_space` deleted
- [todo] P1.6: Preview scripts show the source load, sort and projection
- [todo] P1.7: `run_cas_recommendation` writes its table from the projected set

## Phase 2: Reproduction script

- [todo] P2.1: `tests/backend/active_02_recorded_active_space.py`: window, mapping, mechanisms 2 and 3, opt and SA paths, warning path, source acceptance

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
