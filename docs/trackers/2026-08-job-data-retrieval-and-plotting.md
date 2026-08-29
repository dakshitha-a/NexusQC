# Closed Tracker: job data retrieval and conversational plotting

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
- [`trackers/2026-08-plots-as-objects.md`](trackers/2026-08-plots-as-objects.md)
  ‑ plots as saved, versioned, editable objects, closed 2026-08-22, 20 steps
  across 4 merged phases.
- [`trackers/2026-08-spectra-travel-with-the-job.md`](trackers/2026-08-spectra-travel-with-the-job.md)
  ‑ a job carries its own total spectrum so several can share one axis,
  closed 2026-08-24.

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

## Why this plan exists

A conversation about six uracil jobs asked for the ground-state energies of
every method in one table. The reply gave "CASSCF (6e,6o)" and "CASPT2
(6e,6o)" for two jobs whose specs say twelve electrons in nine orbitals, and
then reasoned at length about why a small (6e,6o) active space behaves as it
does. Measured on the stored checkpoint for that thread:

| measurement | value |
|---|---|
| whole conversation | 302,315 chars / 147,620 est. tokens |
| carried by 10 `check_job_status` payloads | 281,250 chars (93%) |
| of that, `orbital_table` text | 250,770 chars (83% of the thread) |
| history token budget on this host | 53,488 |
| messages surviving `_trim_history` on the final turn | 3 of 92 |

Three separate things had to be true for correct results to produce a wrong
answer, and this plan is one phase per cause, plus the plotting work the same
request asked for.

---

## Phase 1: One vocabulary for every job result

`summary` was an untyped dict built as a literal per runner, so the same
quantity had a different name in each engine: a ground-state energy was
`state_energies_hartree[0]` in BAGEL CASSCF, `ground_state_ccsd_energy_hartree`
in EOM-CCSD, `ground_state_energy_hartree` in TDDFT and `final_energy_hartree`
in an optimization. `casscf_energy_hartree` was written null while its value
sat one key away. `n_states` counted roots including the ground state for a
multireference method and excited states above it otherwise. HOMO and LUMO did
not exist as fields at all. Narrow retrieval over that would have returned
narrow wrong answers.

- [done] P1.1: One canonical name per quantity, applied where results are stored
  evidence: tests/backend/agent_06_job_retrieval.py → "CASSCF ground-state energy is recovered from state_energies_hartree[0]; the old per-engine energy names are gone"
- [done] P1.2: Frontier orbital energies derived once, and nullable
  evidence: tests/backend/agent_06_job_retrieval.py → "a BAGEL active-space HOMO energy is null, not 0.0; the reason travels with the missing value"
- [done] P1.3: State counts and per-excited-state indexing made unambiguous
  evidence: tests/backend/agent_06_job_retrieval.py → "CASSCF n_states=2 reads as 2 total, 1 excited; TDDFT n_states=2 reads as 3 total, 2 excited"
- [done] P1.4: Every reader moved, including stored plot specs
  evidence: scripts/backfill_job_facts.py → "6/6 job results and 0/2 plot records need rewriting; a second run reports 0/6, so it is idempotent"

- merged: 2d7396e

## Phase 2: Retrieve fields, not documents

Every excited-state or CASSCF job rendered ~26,500 characters into context,
93-96% of it a 132-row orbital table plus 1.7 KB of caveat prose repeated
verbatim on every fetch, and the same job's copy was paid for again on each
refetch.

- [done] P2.1: Bulk arrays described rather than printed
  evidence: app/chemistry/jobs/summarize.py → "the six uracil payloads measure 133,788 -> 10,287 chars, 13x smaller; the CASSCF one now carries active_electrons 12 and active_orbitals 9"
- [done] P2.2: `job_data` fetches named fields across many jobs in one call
  evidence: tests/backend/agent_06_job_retrieval.py → "a slice returns the window; a slice past the end clamps; an unknown field is refused, naming what is there"
- [done] P2.3: The addition stays inside the tool-surface budget
  evidence: tests/backend/agent_01_token_budget.py → "prompt_tokens = 9,971 against the 10,000 cap, 13/13 checks passed"

- merged: 2d7396e

## Phase 3: A turn may not lose what it just fetched

`_trim_history` dropped from the front in blocks with a message-count floor
and no notion of which results the current answer depended on. Of four job
results fetched in one turn, the first two went before the model read them,
and nothing told it a hole was there.

- [done] P3.1: The current turn is pinned as a unit with its calling message
  evidence: tests/backend/agent_06_job_retrieval.py → "every current-turn tool result is still represented; no ToolMessage is left without its calling AIMessage"
- [done] P3.2: Over budget, a result is blanked with a marker, never silently
  evidence: tests/backend/agent_06_job_retrieval.py → "an over-budget turn blanks results with an explicit marker, 2 of 4 blanked; at realistic payload sizes nothing has to be blanked"

- merged: 2d7396e

## Phase 4: Every plot restyleable, conversationally

Four of the eight plot kinds could not be restyled at all, and it was not a
missing spec key: their renderers accepted no title, label, colour or size
argument, so `plot(kind="edit")` refused them outright.

- [done] P4.1: One style vocabulary, taken by every renderer
  evidence: tests/backend/plot_02_style_vocabulary.py → "a style patch changes the render, for all of uvvis, ir, ensemble, pes_scan and line"
- [done] P4.2: An unstyled render is unchanged
  evidence: tests/backend/plot_02_style_vocabulary.py → "unset line width, marker size and palette defer to the renderer's own; four regressions in the first pass were caught this way"
- [done] P4.3: The mark and the appearance block cannot be confused
  evidence: tests/backend/plot_02_style_vocabulary.py → "a dict-valued spec['style'] is read as the look; a string one is left as the MARK"
- [done] P4.4: An edit merges the look rather than replacing it
  evidence: tests/backend/plot_02_style_vocabulary.py → "an edit keeps look keys it did not mention; a null inside look removes just that key"
- [done] P4.5: One reply can carry several charts
  evidence: frontend/src/chat/MessageBubble.tsx → "every leading PLOT_ARTIFACT line is parsed, not one anchored marker; uvvis and ir now emit the marker every other kind emits"

- merged: 61385e2

## Phase 6: One state count, for every method

The same conversation carried a second, independent bug. "Calculate 2 excited
states with casscf(12,9)/cc-pvdz" submitted `n_states=2`, and for a
multireference method that counts state-averaged roots INCLUDING the ground
state, so it ran S0 and S1: one excited state. The approval card faithfully
showed the number the user had themselves said. When the results came back,
the agent then described the job as defective for "only reporting one
excitation energy".

`n_states` was documented in three places at once -- the ParamSpec's help, its
`ask`, and two opposing `warn_when` entries -- and the model still got it
wrong, which is the general lesson `docs/BACKLOG.md` already carried: a
parameter whose wrong value is silently plausible wants a structural guard,
not a probabilistic one.

- [done] P6.1: The model-facing count means one thing for every method
  evidence: tests/backend/agent_07_excited_state_count.py → "the ambiguous n_states parameter is no longer model-facing; CASSCF: 2 excited states becomes a 3-root state average"
- [done] P6.2: The engine's root count is derived, not negotiated
  evidence: tests/backend/agent_07_excited_state_count.py → "single-reference methods stay at 2 roots; a CASSCF scan is promoted on the same unambiguous count and zero excited states stays a ground-state scan"
- [done] P6.3: Every tool that asks for a state count asks the same question
  evidence: tests/backend/agent_01_token_budget.py → "prompt_tokens = 9,963, 13/13 checks passed, with search_active_space_literature and explain_active_space converted too"

- merged: 3e43805

## Phase 7: Room on the fixed surface

Every ReAct iteration of every turn pays for the system prompt and all the tool
schemas. After Phases 1-6 that surface sat at 9,970 tokens against a 10,000
cap: adding one sentence to the system prompt pushed it over both its caps at
once, which is a fair way of learning there is no headroom left.

Measured per tool with the served model's own `usage.prompt_tokens`, removing
one tool at a time -- the system prompt is 1,368 tokens and the seventeen tool
schemas were 8,595, so the schemas were the whole question.

- [done] P7.1: update_job_draft stops restating what ParamSpec.help already says
  evidence: tests/backend/agent_01_token_budget.py → "9,970 -> 9,411 tokens; the rule was stated three times in full and then again per-parameter for two params whose own help carries it verbatim"
- [done] P7.2: Three search tools become one with a `source`
  evidence: tests/backend/agent_01_token_budget.py → "9,411 -> 8,837 tokens, 17 tools -> 15; each of the three had spent docstring on when to prefer the other two, which is a parameter rather than a tool"
- [done] P7.3: check_job_status absorbs job_data as a `fields` argument
  evidence: tests/backend/agent_01_token_budget.py → "8,837 -> 8,688 tokens, 15 tools -> 14; describing a job and reading fields from several is one question with and without a list"
- [done] P7.4: A field table can never label two jobs the same
  evidence: verified against three probe jobs on disk → "two jobs that auto-name identically render as (aaaa1111) and (cccc5555) via _default_column_labels, the helper the comparison chart already used"

- merged: 9bc1a7f

## Phase 8: The rest of the consolidations, evaluated rather than assumed

Three were left in the backlog after Phase 7 because they change which tool the
model reaches for. Two of them do not survive reading the code; the third was
measured against the real model and kept.

- [done] P8.1: The two active-space tools become one, mode following the arguments
  evidence: tests/backend/agent_01_token_budget.py → "8,688 -> 8,361 tokens, 14 tools -> 13, 13/13"
- [done] P8.2: The merged tool picks the right mode as reliably as two tools did
  evidence: a 7-prompt x 3-repeat probe against the served model → "21/21, identical to the two-tool baseline, including three adversarial prompts that mention a space while asking for a recommendation"
- [done] P8.3: Nothing downstream of the merge breaks
  evidence: tests/backend/casreco_04_literature_step.py → "34/34; both underlying functions still exist and are still directly callable, only unbound from the tool list"
- [done] P8.4: The other two are closed as not worth doing, with reasons in the backlog
  evidence: docs/BACKLOG.md → "convert_energy_units converts values that never came from a job; the ensemble window pools across sub-jobs and filters, which no field path expresses"

- merged: c15e310

## Phase 5: Verified end to end

- [done] P5.1: The question that started this, replayed against the real model
  evidence: tests/backend/agent_06_job_retrieval.py → "a live turn over the six real uracil jobs reports 12e/9o for both multireference methods, tabulates all five in eV and hartree, and spends 12,030 chars of tool output against 281,250 for the original conversation"
- [done] P5.2: The fixed tool surface still fits its budget
  evidence: tests/backend/agent_01_token_budget.py → "prompt_tokens = 9,971 against the 10,000 cap, 13/13 checks passed, with job_data added"
- [done] P5.3: Two charts in one reply, in a real browser
  evidence: tests/frontend/plots_02_multiple_per_reply.spec.mjs → "both markers in one tool message render a card, each with its own download link, no marker text leaked, no console errors"
- [done] P5.4: The stack-dependent backend suite, run against the deployment
  evidence: tests/run_backend.sh → "94/99 scripts fully passing. Two failures were this work's and are fixed (active_01 44/44, spec_01 22/22); draft_01 passes 41/41 alone and fails only inside the suite; perf_02 and perf_04 are logged in BACKLOG.md, and app/chemistry/jobs/scheduler.py is untouched by this work"
- [done] P5.5: The backfill is not needed
  evidence: docs/BACKLOG.md → "every job was purged on request instead, so there is nothing on disk written in the old vocabulary; the script stays for any deployment that does need it, verified idempotent on copies of the six real jobs"

- merged: 8742391
