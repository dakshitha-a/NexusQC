# Overhaul Tracker

Live status of the overhaul defined in [`OVERHAUL_PLAN.md`](OVERHAUL_PLAN.md).

Published artifact (regenerate with `scripts/render_tracker_html.py` and
re-publish **to this same URL** at every step completion and phase gate):
https://claude.ai/code/artifact/121a529d-2c9a-4dff-ae4a-a0047cb6afa6

## Rules (enforced by `scripts/check_tracker.py`)

- Step status is exactly one of `todo` | `in-progress` | `done`.
- A step may be marked `done` **only with an evidence field**: the
  verification script/command path plus a one-line observed result.
- The tracker edit ships **in the same commit** as the step's final code
  change, so `git log --follow docs/TRACKER.md` is the audit trail.
- A phase's `merged` row records the merge commit hash, added in the next
  commit after the fast-forward merge (the one edit allowed to trail).
- The published tracker artifact is re-rendered at every step completion and
  every phase gate.

Format for a step row:

```
- [status] P<phase>.<step> — <short name>
  evidence: <script/command> → "<observed result>"   (required when done)
```

---

## Phase 0 — Verify, document, baseline

- [done] P0.1 — Plan committed (docs/OVERHAUL_PLAN.md), tracker + check script + published artifact, continuation memory saved
  evidence: scripts/check_tracker.py → "PASS, tracker consistent: 59 steps; artifact published at /artifact/121a529d"
- [done] P0.2 — docs/MASTER_PLAN_SUMMARY.md (projected implementation)
  evidence: docs/MASTER_PLAN_SUMMARY.md → "projected end state written: 11 job types, tagging contract, visualizer contract, dev notes"
- [done] P0.3 — ORCA verification spikes (EnGrad/.engrad, IRoot ES gradient, NACME scope+format, %geom Constraints, CASSCF MECI keywords, Opt(Num)Freq single-input, MOREAD/%moinp restart)
  evidence: scripts/spikes/spike_orca_caps.py → "9 probes: gradients/ES-gradients/full-TDDFT/TDDFT-NACME/constraints/%CONICAL/Opt+Freq/MOREAD all PASS; %casscf NACME = GAP"
- [done] P0.4 — BAGEL verification spikes (forces format, nacme casscf+caspt2, orbital restart molden-vs-archive, optimize+hessian one-input, constrained-opt conflict)
  evidence: scripts/spikes/spike_bagel_caps.py → "forces/nacme/opt+hessian/save_ref-load_ref PASS; fix_atom proven a silent no-op by differential geometry comparison"
- [done] P0.5 — PySCF verification spikes (analytic gradients per method, NAC availability, chkfile+project_init_guess, geomeTRIC constraints, MECI feasibility)
  evidence: scripts/spikes/spike_pyscf_caps.py → "18/22 confirmed; all 3 orbital-reuse paths work; SA-CASSCF NAC real (scales 1/dE); no CASSCF Hessian, no TDDFT NAC, no MECI. DMRG initially misreported as absent -- the app uses pyblock2, not pyscf.dmrgscf; block2 0.5.3 installed and the pilot verified"
- [done] P0.6 — docs/QM_CAPABILITIES.md v1 (verified matrix, diff vs user's summary, "claims not confirmed" section)
  evidence: docs/QM_CAPABILITIES.md → "3 engine tables with per-cell evidence level; 7 unconfirmed claims documented"
- [done] P0.7 — docs/PARSER_GAPS.md skeleton
  evidence: docs/PARSER_GAPS.md → "protocol + open/closed tables in place, zero rows"
- [done] P0.8 — Model-context spike (prompt/schema token counts, num_ctx via Ollama /v1, draft-tool-call reliability harness on both target models)
  evidence: scripts/spikes/spike_model_context.py --truncation --draftshape → "measured end-to-end: fixed surface 14,468 tokens, window saturates ~32,697, system prompt lost only at saturation; dict-arg draft tool 3/3 on both models at 1 call vs up to 5 flat -- see docs/MODEL_CONTEXT_BUDGET.md (carries a correction notice)"
- [done] P0.9 — Bugfix batch (tools.py:556 engine arg; stale qwen3:30b comments; naming.py labels; stale BAGEL-freq comment; ARCHITECTURE LIIC claim; drop miew)
  evidence: tests/backend/reg_01_wigner_prep.py → "ALL CHECKS PASSED (7/7); frontend npm run build succeeds without miew; no package declares miew"
- merged: 8d8a289

## Phase 1 — Registry v2 dark launch + auto-retry removal

  note: the adapter (`registry2/adapter.py`, `LEGACY_JOB_TYPE_MAP`) and its
  round-trip test **P1.3 are dropped at the user's instruction** (2026-08-18):
  jobs on disk were wiped and the overhaul starts from a clean slate, so
  there is no legacy `spec.json` shape left to keep renderable and the v2
  taxonomy is the only taxonomy. Later phases must not reintroduce a
  legacy-compatibility reader on the strength of OVERHAUL_PLAN.md's older
  "readers via adapter" wording. P1.3's number is retired rather than reused,
  so the step numbering stays an audit trail.

- [done] P1.1 — app/chemistry/registry2/ (capabilities, tasks, params, routing, lookup)
  evidence: scripts/check_capability_matrix.py → "PASS, 506 assertions across 15 capability rows and 19 tasks; golden table hand-derived from QM_CAPABILITIES (not from the code it checks) and mutation-tested — flipping BAGEL constrained_opt to trust the exit code makes it fail"
- [done] P1.2 — scripts/generate_capability_docs.py + drift check
  evidence: scripts/generate_capability_docs.py → "regenerates docs/QM_CAPABILITIES.md only between BEGIN/END markers, idempotent, --check PASSes; hand-written prose (claims-not-confirmed, ORCA banner trap, BAGEL fix_atom note, orbital reuse) survives regeneration"
- [done] P1.4 — Registry API v2 payload alongside v1
  evidence: tests/backend/reg2_01_registry_v2_payload.py → "ALL CHECKS PASSED (20/20); all six v1 keys byte-identical to the legacy module, v2 JSON round-trippable, and BAGEL/casscf advertises no constrained_opt end-to-end through the API"
- [done] P1.5 — Auto-retry removal (full removal map)
  evidence: tests/backend/fail_01_notice_flow.py → "ALL CHECKS PASSED (20/20); MAX_AUTO_RETRIES, count_failed_in_chain, retry_of_job_id, _retry_count/_retried_from and the retry_note card are gone from app/, server/, frontend/src/ and tests/; e2e_12_failure_retry.py deleted; README/HelpFlyout/WelcomeMessage/ARCHITECTURE copy rewritten"
- [done] P1.6 — Plain-failed branch + troubleshoot flow (tests/backend/fail_01_notice_flow.py)
  evidence: tests/backend/fail_01_notice_flow.py → "ALL CHECKS PASSED (20/20) against a real failed PySCF job; the load-bearing negative holds — invoke_turn replaced by a sentinel is never called for a failed job; the notice is a checkpointed message read back through read_state, polling twice does not duplicate it, and the composed troubleshoot message carries the engine's real output tail"
- [done] P1.7 — Failed-job notice card + Troubleshoot button
  evidence: tests/frontend/fail_01_notice_card.spec.mjs → "ALL CHECKS PASSED (10/10) in headless chromium against a real dev stack; card renders, survives a full page reload, POSTs 202 to the troubleshoot route and becomes one-shot afterwards"
  smoke: one manual conversation against the served qwen3.8:27b → "turn 1 called set_molecule and resolved water (12.2s); a real troubleshooting turn called search_knowledge_base then submit_job (13.3s), i.e. it consulted the manual and proposed a corrected job through the approval card rather than running anything itself -- also confirming submit_job's changed signature still binds"
- merged: 5a3b1e6

## Phase 2 — Agent rebuild: draft workflow, taxonomy switch, context diet

  note: **P2.6 does not go through an adapter, and its acceptance criterion
  is replaced.** `OVERHAUL_PLAN.md`'s step 6 still says "legacy runner key
  via `adapter.runner_key()`; readers go through `normalize_job_spec`" and
  its accept line asks that "a fixture set of all 14 legacy-type completed
  jobs renders identically". Both predate the Phase 1 clean-slate decision
  recorded above: the adapter was removed outright and the jobs on disk were
  wiped, so there is no legacy spec left to render and nothing to render it
  identically to. Runner selection is therefore keyed on the v2 task fields
  directly, and the criterion becomes: **a v2-spec fixture set of equivalent
  breadth (one completed job per task/subtype the legacy taxonomy covered)
  renders in the drawer, and newly submitted jobs render.** Recorded here
  rather than edited into the plan, on the same principle as P1.3's
  retirement — the plan is the approved artifact, the tracker is where its
  deviations are accounted for.

- [done] P2.0 — Capture a pre-rebuild checkpoint fixture (thread with a pending old-shape approval) for the P2.7 resume test
  evidence: scripts/capture_approval_fixture.py → "captured tests/data/pre_rebuild_approval.sqlite (45 KB) + .json against the post-Phase-1 toolset; the v1 interrupt shape is pinned at 12 keys and a spec carrying no task/subtype; the script's own self-check resumed a copy down the reject path and got the not-approved ToolMessage back, so the fixture is live rather than merely present"
  note: moved here from Phase 0. The fixture has to come from the toolset as it stands immediately before the rebuild, so it is captured at the START of this phase. **Correction:** Phase 1 DID alter the interrupt payload — `retry_note` was removed from it with auto-retry — so the fixture must be captured against the post-Phase-1 toolset, and any approval left pending from before Phase 1 will fail to resume (its recorded `submit_job` call carries `retry_of_job_id`, which the tool no longer accepts). Wiping old threads is the intended remedy, consistent with the clean-slate decision above.
- [done] P2.1 — registry2/elicitation.py::validate_draft (12+ scenario script)
  evidence: tests/backend/elic_01_draft_scenarios.py → "161/161 checks passed across 21 scenarios walked empty→ready, covering every single_point and opt subtype; the ask sequence is asserted by name and each question is asserted to be `ParamSpec.ask` verbatim rather than composed text; mutation-tested — removing use_tda's applies_when gate fails 4 checks. Walking the scenarios found seven real defects in the Phase 1 parameter data, all fixed here: isoval, use_tda and max_active_orbitals defaulted onto jobs that never read them, opt/ci asked for neither n_states nor target_state, cas_reco/autocas asked the user for the active space it exists to produce, a blind input was silently routed to ORCA, and a stale Wigner source-job id survived four further questions before being caught"
- [done] P2.2 — New toolset (draft tools, lookup_capabilities, consolidated plot; token-budget test; e2e_08 via drafts)
  evidence: tests/backend/agent_02_draft_flow.py → "32/32 checks passed against the real state schema, reducers, checkpointer and interrupt(); a draft is built one answered question at a time, survives in state, reaches the approval gate carrying the v2 task fields plus a runnable spec and its input preview, and both branches out of that gate work. Two defects found by running it: routing's engine choice was being written back onto the user's request, so the card claimed PYSCF 'was requested explicitly' about a choice the user never made; and a Wigner draft reached the spec builder with no scan_job_type. A third — a geometry absorbed into the draft as a parameter named `molecule`, riding into the submitted spec — was found only by a real smoke conversation, and is now refused rather than absorbed"
  smoke: one manual conversation against the served qwen3.8:27b → "'Run a geometry optimization on water' → set_geometry + start_job_draft, the backend's questions relayed verbatim, then 'Use HF with the sto-3g basis' → DRAFT READY and submit_draft pausing on the approval card with a correct PySCF input preview. The model self-corrected after the geometry-as-parameter refusal, so the final spec params are clean"
  browser: tests/frontend/draft_01_approval_card.spec.mjs → "11/11 in headless chromium against a live backend and vite, driving a real conversation end to end: the backend's elicitation question arrives in the chat, submit_draft paints the card, the PySCF input is shown for approval, Approve POSTs 200, the card is dismissed, and there are no uncaught JS errors. Verified in a browser rather than by reading the payload, per CLAUDE.md — the new interrupt payload is a superset (task, subtype, capability_note added, nothing removed), which a code read says is safe and a silently-empty card looks identical to"
  not re-run: tests/frontend/fail_01_notice_card.spec.mjs (P1.7) needs a harness that seeds
  a failed job before launching. It asserts on the Troubleshoot button and the route, not
  on `troubleshoot.py`'s prose, so the P2.2 wording change does not touch it — and the
  composed message itself is still covered by fail_01_notice_flow.py, which passes 20/20.

  known limitation, recorded rather than fixed here: `validate_draft` is now
  deterministic across the approval interrupt (`check_external=False`), but
  `_build_ensemble_spec_or_error` does its **own** job-store read before the
  interrupt, so a `wigner_spectra` approval whose source frequency job is deleted
  between the card rendering and the click fails with an explanation instead of
  running. That is pre-existing behaviour, not introduced by the rebuild, and the
  outcome is arguably right — the job genuinely cannot run — but it is the one
  remaining path where the pre-interrupt half is not a pure function of the draft.
  Worth revisiting when P2.6 rebuilds spec construction on the v2 taxonomy.

  deferred: **e2e_08 via drafts moves to P2.9**, which already owns the e2e suite
  update. The whole e2e suite still drives the pre-rebuild tool names
  (`submit_job`, `set_molecule`, `generate_job_input`, the four plot tools) and has
  to be rewritten as one piece rather than one script at a time.

  decisions taken during the step, recorded so they are not re-litigated:
  - **P2.4 (prompt rewrite) ships with P2.2, not after it.** The prompt's job catalog
    is deleted *because* `lookup_capabilities` and the draft errors replace it — one
    change, not two. It also has to, for the evidence to mean anything:
    `docs/MODEL_CONTEXT_BUDGET.md` sets the target as the **combined** fixed surface
    (system prompt + tool schemas) materially under 10,000 tokens, measured as
    `usage.prompt_tokens` against the served model, down from 14,468. Asserting the
    schema half alone at P2.2 would pass while the real number stayed over budget.
  - **`generate_job_input` is not carried over as a tool.** "Show me the input without
    running it" is answered by the draft itself: a `ready` verdict carries the engine
    input preview, so the input is visible one tool call before the approval gate
    rather than through a second tool that duplicated the whole build path.
  - **`submit_draft` must not re-gate on `validate_draft` after the interrupt.**
    Everything before `interrupt()` re-executes on the approve click; a verdict that
    flipped to `incomplete` in between (`validate_draft` reads the job store for a
    Wigner source job, which can change) would return an ask, never reach
    `interrupt()`, and silently drop the approval. The approved spec comes from
    `decision["spec"]` verbatim, exactly as the pre-rebuild tool did.
  - **The v2→v1 spec mapping at submit time is interim and local to `tools.py`.**
    It is not the removed `registry2/adapter.py` coming back: that was a *read-time*
    legacy-spec-to-v2 mapping for old jobs on disk, and this is a write-time mapping
    in the opposite direction, existing only so the runners keep working between P2.2
    and P2.6. **P2.6 deletes it** by keying runner selection on the v2 task fields.
    Recorded here so it cannot quietly become permanent. A second interim map,
    `_EXCITED_STATE_JOB_TYPE`, derives a nuclear-ensemble spectrum's per-geometry
    sub-job from its method; it has the same expiry.
- [done] P2.3 — TDDFT default flip (full TDDFT; ORCA %tddft tda false; approval-card hint)
  evidence: tests/backend/tddft_01_full_response_default.py → "12/12 checks passed, asserted in the generated engine input rather than in the parameter dict — ORCA emits `tda false` and PySCF builds `tdscf.TDDFT(mf)`, with TDA still reachable when asked for explicitly. The approval card now names which of the four ran (full TDDFT / TD-HF/RPA / TDA-DFT / CIS) and says nothing about TDA for a CASSCF job. Six fallback sites plus two registry defaults; one, in orca_runner.py, used single quotes and was missed by the first sweep — the test caught it, which is the argument for asserting on the input file"
  note: the plan says ORCA should emit `%tddft RPA true`. What Phase 0 actually verified
  against ORCA 6.1.1 is `%tddft ... tda false` (`scripts/spikes/spike_orca_caps.py`,
  "full TDDFT vs TDA"), so that is what ships — the repo's standing rule is that engine
  input is written against real output, not documentation.
- [done] P2.4 — Prompt rewrite ≤ 6KB
  evidence: tests/backend/agent_01_token_budget.py → "13/13 checks passed. SYSTEM_PROMPT is 4,519 bytes, down from 22,644, and the job catalog is gone — the test asserts the prompt no longer spells out job_type, active_electrons, generate_job_input or submit_job, because that catalog duplicated registry2 and went stale silently. Measured end to end against the served qwen3.8:27b as usage.prompt_tokens, the way Phase 0 established: the fixed surface is **4,489 tokens against the 14,468 baseline, a 69% reduction**, comfortably inside the 10,000 target. 12 tools, widest schema 6 parameters, where submit_job alone took 38"
  note: shipped in the same commit as P2.2, deliberately. The prompt's catalog is
  deleted *because* `lookup_capabilities` and the draft questions replace it, and the
  budget in `docs/MODEL_CONTEXT_BUDGET.md` is a **combined** figure — asserting the
  schema half alone at P2.2 would have passed while the real number stayed over budget.
- [done] P2.5 — Context bounding (num_ctx, mechanical trimming + digest)
  evidence: tests/backend/agent_03_context_bounding.py → "12/12 checks passed. A 240-message conversation now completes a real turn at 9,975 prompt tokens against the requested 32,768 window, where before the whole thread was sent every time. The trim is checked at every thread length from 1 to 120 for an orphaned tool result — the shape an OpenAI-compatible endpoint rejects outright — and the digest is asserted to be built from AgentState alone. The end-to-end check found a real bug: the digest was originally a second SystemMessage, which Ollama rejects with `system message must be at the beginning`, so every conversation long enough to be trimmed, and only those, would have failed in production. It is now appended to the one system message"
  note: the token measurement is skipped only for an unreachable server. Any other
  exception is reported as a failure, because the bug above first surfaced *as* a skip
  — a red result that means "the server is down" teaches people to ignore red results.
- [done] P2.6 — Taxonomy switch (v2 specs; readers keyed on task fields; drawer keyed on task fields; jobFilename dedupe)
  evidence: tests/backend/tax_01_v2_specs.py → "30/30. `JobSpec` carries `task`/`subtype` as first-class fields and `method` is documented as the runner key only; one spec is built per task the agent can submit and each carries its taxonomy through a JSON round trip. Masters are derived from `TaskDef.master` rather than a hand-kept set of runner-key strings, and single_point/grad and /nac are refused by name ('lands in Phase 5') instead of falling through to 'unknown job_type'"
  evidence: tests/backend/tax_02_job_rows.py → "16/16. `GET /api/jobs` serves task/subtype beside the runner key; `is_scan_master`/`is_ensemble_master` key on the task (a stale runner-key comparison there does not raise — it returns False and the sub-jobs become unreachable); and `filename_stem` is served from `naming.py` rather than recomputed in TypeScript, with the two asserted to agree on a label containing quotes, a newline and a slash"
  browser: tests/frontend/draft_01_approval_card.spec.mjs → "11/11 again after the switch and after the frontend changes; verified live that the registry route is v2-only and a real job row carries task=opt, subtype=min, filename_stem=20260819_water_OptHF_sto-3g_PYSCF_f3836c45"

  what the frontend half came to: `JobRow` gains task/subtype/filename_stem; the jobs
  panel labels a job by its task rather than by the function that ran it;
  `lib/jobFilename.ts` no longer computes the stem at all (it was the self-declared
  "SECOND COPY" of `naming.py`, each copy carrying a comment asking whoever edited it
  to remember the other — a drift no browser test could catch, since the two names
  appear on different downloads); and the registry API is v2-only, its v1 half removed
  along with the dead `useJobRegistryQuery` hook that was its only consumer and which
  no component ever called. `reg2_01`'s v1-is-byte-identical assertion inverted
  accordingly: Phase 1's dark-launch property is deliberately retired.

  **`jobs/excitedState.ts` deliberately still keys on the runner key**, and says so in
  a comment. The question it asks is "which summary shape is this?", and a summary
  shape is produced by the runner that wrote it — a CASSCF and a TDDFT excited-state
  job are the same task (`single_point/ee`) and emit incompatible dicts, so keying on
  the task would merge the two cases the function exists to tell apart. Moving it would
  have been pattern-matching, not correctness.

  **correction to an earlier note in this file:** it said P2.6 would delete
  `_LEGACY_JOB_TYPE` / `_EXCITED_STATE_JOB_TYPE`. That was wrong. `OVERHAUL_PLAN.md`
  always expected a v2 spec to carry a "legacy runner key", and what the user removed
  was the *read-time* adapter for old specs on disk — the opposite direction. Deleting
  these means rewriting all three engines' `if job_type == ...` dispatch onto the v2
  fields, which is what Phases 5–8 do one job family at a time. They are now documented
  in `tools.py` as `runner_key()`-style derivations rather than as something interim.
  What P2.6 *did* remove is every reader that used the runner key to decide what a job
  **means** — masters, ensemble sources, input validation, display labels.

- [done] P2.7 — Old-thread compatibility (dual interrupt shapes)
  evidence: tests/backend/agent_04_old_thread_resume.py → "14/14 checks passed against the real P2.0 fixture — nothing reconstructed; the pending interrupt, its twelve-key payload and its task-less v1 spec are what the pre-rebuild code actually left behind. Before the fix, clicking Approve on such a card returned `Error: submit_job is not a valid tool, try one of [...]`, i.e. a list of internal tool names shown to someone who pressed a button. Both the approve and the reject path now land on a plain explanation that nothing was submitted, with an offer to set the job up again"
  note: the fix is a resume-only shim named `submit_job`, bound to the tool executor
  via a new `get_executable_tools()` but **never offered to the model** — `get_all_tools()`
  is unchanged, so the prompt surface is untouched (agent_01 still measures 4,489 tokens).
  It does not attempt to run the job: that spec was built by a tool that no longer
  exists, in a taxonomy the runners are moving off. Approve and reject deliberately give
  the same answer, because neither can produce the calculation and the distinction
  stopped meaning anything when the tool went away.
- [done] P2.8 — Pasted blind input (input_sniff.py; ORCA/BAGEL only)
  evidence: tests/backend/sniff_01_pasted_inputs.py → "69/69 checks passed over 9 ORCA, 7 BAGEL and 3 PySCF samples plus 3 non-inputs. Most samples are the app's own generated inputs — the exact text these engines accept — and the rest hand-written in the shape a user pastes, with comments and manual-style spacing. A pasted ORCA input now resolves its own engine and is described back ('ORCA input for a opt/min calculation at dft/def2-SVP') with the structured alternative offered; a stated engine that contradicts the text is queried rather than overridden; and a pasted PySCF script is classified as precisely as the others and refused for execution"
  note: one expectation was wrong on first writing and the code was right — this app runs
  an ORCA `opt_freq` as two sequential jobs and previews only the optimization stage, so
  the generated text genuinely *is* an optimization input. Reading it as `opt_freq` would
  have been the sniffer inventing a second stage that is not in the text. The combined
  `! Opt Freq` keyword line ORCA does support is covered by its own hand-written sample.
- [done] P2.9 — e2e suite update + e2e_18_elicitation.py
  **executed against the live dev stack** (nginx on :8444, running `main` at c4fe1c7).
  The suite is moved onto the rebuilt toolset:
  `set_molecule`→`set_geometry`, `submit_job`→`submit_draft`, the four plot tools→`plot`,
  and `generate_job_input` retired (e2e_06's T03 now asserts the half that mattered — that
  showing an input is not running one). e2e_08's assertion moved off the tool call and onto
  the approval payload, because `submit_draft` takes no arguments: the draft lives in graph
  state, so "did the agent ask for the right job?" is now a question about the card, which
  is also what determines what runs. New `e2e_18_elicitation.py` asserts the property only
  a real conversation can show — that the agent **relays the backend's question rather than
  composing its own** — by pulling the expected wording from `ParamSpec.ask` at runtime, so
  a reworded question cannot leave the script asserting text that exists nowhere.

  evidence: tests/e2e/e2e_04_harness_gate.py → "16/16 against the live stack. The whole
  rebuilt flow runs end to end: set_geometry → start_job_draft → update_job_draft ×2 →
  submit_draft → an approval card carrying task/subtype/capability_note → approved → the
  job ran to completion, and the job that ran matches the spec that was approved. H12 also
  confirms agent_step events still publish after an approval resume"
  evidence: tests/e2e/e2e_18_elicitation.py → "17/17 against the live stack and the served
  model. The agent relays the backend's questions **in the registry's own words** — token
  containment against `ParamSpec.ask`, nothing missing on either the basis or the
  active-space question — a method given where a task was expected is not rejected,
  answering two parameters at once is not re-asked, and the card carries the user's own
  active space and basis rather than a guess. The CASPT2-on-PySCF turn reaches no card at
  all and names BAGEL as the alternative"

  evidence: tests/e2e/e2e_06_agent_tools.py → "12/13 against the live stack. Every non-draft
  tool is exercised, elicitation refuses to guess on all three scenarios, and all four
  disallowed engine/method pairings are refused with nothing reaching an approval card"
  evidence: tests/e2e/e2e_07_approval_flow.py → "21/22 against the live stack, including
  the load-bearing one — a hand-edited input is used byte-identically rather than
  regenerated, and an invalid edit leaves the interrupt pending so the user can fix it in
  place"

  evidence: tests/e2e/e2e_11_param_correction.py → "6/7 against the live stack. Everything
  the script exists to test passes: the `6-31gd`→`6-31g(d)` repair happens *and is
  surfaced* rather than applied invisibly, an RHF request resolves to this app's single
  `hf` value, mistyped functional and basis both produce candidate menus, and an
  unsupported method produces no job with the agent explaining instead of submitting"
  evidence: tests/e2e/e2e_08_job_matrix.py → "first pass 99/116 with ten failing cells,
  which is what produced almost every fix below. A re-run against the fixed stack is in
  progress and clean through the first ten cells except M10, whose fix (a6be716) was
  committed after that deploy"

  evidence: tests/e2e/e2e_09_plot_tools.py → "11/12 against the live stack. The four plot
  tools collapsed into one `plot(kind=...)` without losing the property the script exists
  for: real UV/Vis and IR spectra are written and downloadable as PNGs for ORCA
  TDDFT/EOM/frequency, the PLOT_ARTIFACT marker the chat UI keys its inline image off is
  intact, and the refusal paths survive — a PySCF eom_ccsd job and a PySCF frequency job
  are both declined rather than drawn. Its one failure is the script's own refusal
  detector: the tool refused correctly and wrote no artifact, saying 'no excitation
  energies to plot a spectrum from', which is not in REFUSAL_WORDS"

  **closed with five job-matrix cells still failing, none of them a product defect**, and
  deliberately rather than by grinding them green — P2B.6 rewrites `MATRIX` and
  `EXPECTED_SUMMARY_KEYS` on the v2 taxonomy, so polishing them here is work done twice:

  - **M10** is a harness artifact, not a stall: the same request reaches an approval card
    3/3 through the graph on the same code, and 0/2 through the e2e path. The matrix
    labels this cell "the SLOW probe" and could not distinguish "the model stopped" from
    "the 600s turn cap cut it off", so `timed_out` and elapsed time are now reported on
    that failure.
  - **M20, M24, M26** are the stalled-after-draft shape whose fix (a6be716) is deployed
    but unverified on those specific cells.
  - **M23** fails engine-side — ORCA exits 2 on NEB-TS. Tier 3, `XN-09`, already
    documented as unverified territory; NEB belongs to Phase 7.

  what the suite was for, it did: it found the permanently-500ing job detail page, the
  scan drafts raising through `submit_draft`, the ready draft that carried no engine
  input, the agent asking for parameters the user had just given, and two diagnostic
  blind spots that had been hiding those. All fixed, and the fixes verified against a
  real stack — the matrix went from 99/116 with ten failing cells to 125/133 with five.

  what the job matrix found, and it is worth reading as a whole rather than as ten
  separate cells — **the single most common failure shape was "the model stopped after
  start_job_draft", and it had more than one cause underneath it**:

  - **A malformed scan draft raised straight through `submit_draft`.** The geometry
    builder indexes and does arithmetic on whatever shape the draft carries and only
    `ValueError` was caught, so an unexpected shape surfaced as `TypeError`, `KeyError`
    or `OverflowError`, escaped the tool, and produced no approval card and no
    explanation. Five of seven plausible model-written shapes crashed. 0-based atom
    indices threw `OverflowError` — and this app's numbering is 1-based everywhere a user
    or a model can see it, so reaching for 0 is a predictable slip that deserved to be
    told which convention it broke. Fixed in three layers; `scan_01_draft_shapes.py`
    (13/13) pins the class, its load-bearing negative being that *nothing raises*.
  - **Four v1 job-type names resolved to nothing** — `mo_visualization`, `custom`,
    `recommend_active_space`, `wigner_ensemble` — so the agent told users a calculation
    it plainly runs was not one. Found three times in three separate cells before the
    whole legacy list was checked at once, which is now an assertion.
  - **A fully-specified request still asked for a parameter the user had just given.**
    `start_job_draft` carries only task/method/engine, so the draft came back INCOMPLETE
    and the reply's "put this question to the user word for word" was obeyed on a
    question already answered in the same sentence. Right instruction when the answer is
    unknown, wrong when it is in the message just read; nothing distinguished the two.
    Measured after the fix: 4/4 reach a card, with an identical tool sequence each run.
  - **A ready draft did not carry the engine input**, though the tracker and the commit
    that removed `generate_job_input` both said it did.
  - One cell was **the agent being right and the test wrong**: it refused to submit
    because `n_states=2` on CASSCF means the ground state plus one excited state, not
    two. That is P2.1's multireference caveat working in a live conversation, on a
    discrepancy no assertion was looking for.
  - M23 (NEB-TS/ORCA) fails engine-side. Tier 3, `XN-09`, already documented as
    unverified territory; NEB belongs to Phase 7.
  - M12 remains **not reproduced**. Its approval POST 500'd while the same draft approves
    cleanly through both a tools-only and a full graph. It fired immediately after M11's
    BAGEL job was cancelled at the 900s cap, so a cancel-then-submit race is the standing
    hypothesis — but a hypothesis is not a diagnosis, and no speculative fix was shipped.

  two diagnostic gaps were closed, each of which had been hiding one of the above:
  `chat.py` flattened any resume failure into a 500 while logging nothing, and the job
  matrix reported only the tool list when no card appeared, so "the model never
  submitted" and "the submit was refused, and here is why" were indistinguishable.

  three defects were found by running the suite, all fixed and pushed, none of them found
  by reading:
  - **e2e_18's own first run failed 3/15, and the script was wrong rather than the app.**
    Written before the method-as-task fix, it still expected the basis question first,
    where the backend now correctly asks which *calculation* a "CASSCF calculation" is
    meant to be. Rewritten to assert the improved behaviour; 17/17.
  - **`get_pending` in e2e_07 promised a retry it never performed.** Its docstring has long
    said it "retries once on a fresh thread if the model didn't call submit_draft"; the code
    did not, which is why A6 failed intermittently for reasons with nothing to do with spec
    tampering. The retry is now real.
  - **A ready draft did not carry the engine input, though the tracker and the commit that
    removed `generate_job_input` both said it did.** So "show me the input, don't run it"
    had no answer at all: e2e_06's T03 showed the model setting the geometry and stopping,
    three attempts running, because nothing offered it a way to comply. Fixed in f171bb5,
    with a prompt line pointing at it. **T03 has not been re-run yet** — the fix is on
    `main` but the stack was not redeployed before the session ended.

  and one genuine product bug, found by watching the api logs rather than by any assertion:
  - **A non-finite float permanently 500'd a job's detail page.** An ORCA frequency job's
    `reduced_mass_amu` is deliberately `inf` for the six projected translation/rotation
    modes — their displacement vectors are exactly zero, so the mass ratio is undefined,
    and `vibrations.py` documents the sentinel. JSON cannot express infinity and FastAPI's
    encoder refuses to invent a spelling, so `GET /api/jobs/{id}` raised inside the
    response renderer: every poll, every drawer open, forever, for a job that had completed
    perfectly well. It is also what stalled the e2e_08 run — the suite sat retrying a job
    detail that could never succeed, 41 polls in two minutes, and would have spun to its
    own 90-minute timeout. Fixed at the serialization boundary in 9c057d6 rather than at
    the one field that was caught, since the next engine to emit a NaN should not brick a
    job the same way. Regression checks in tax_02 (22/22).

  two real defects were found by running that verification, both fixed with regression
  checks in elic_01 (now 193/193):
  - **"Run a CASSCF calculation on water" dead-ended.** CASSCF is a method, not a task, so
    task resolution failed and the user was told "I don't recognize 'CASSCF' as a
    calculation this app runs" — a sentence that reads as nonsense, because it plainly is
    one. A method given where a task was expected is now kept as the method, and the
    question becomes the one the user actually left open. The task is still asked, never
    inferred: a CASSCF on water could be an energy, an optimization or a spectrum.
  - **A free-text phrase was rejected whole.** The model passes what the user said —
    "CASSCF single point energy", "B3LYP geometry optimization", "excited states with
    TDDFT" — one string carrying both a task and a level of theory. These are now read
    apart. `tddft` resolves to both halves at once (excited states, at DFT), which is
    exactly the conflation the v2 taxonomy exists to undo.
- merged: 3592b5a
  note: merged continuously rather than at one gate. The branch was fast-forwarded onto
  `main` at 54b558d — twelve commits, no merge commit — and then advanced commit by commit
  as the e2e run found and fixed things; 3592b5a is the commit that closed the last step.
  The hash stayed blank until then on purpose, because
  `scripts/check_tracker.py` treats a recorded hash as the claim that every step is done,
  and filling it in now makes that check fail. The check is right: this phase was merged
  early, at the user's explicit direction, so the e2e suite could run at all. It needs the
  docker-compose stack, which runs the main checkout rather than a worktree, so running it
  before the merge would have meant pointing the dev stack at a branch and restarting the
  user's deployment. Order: merge → bring the dev stack onto `main` → run the suite → fix
  what it catches → record the hash here.

  Everything else in the phase is `done` with recorded evidence; the backend suite is green
  (193/193 elicitation, 32/32 draft flow, 30/30 taxonomy, 16/16 job rows, 69/69 sniffer,
  14/14 old-thread resume, plus the Phase 0/1 regressions) and the approval flow is
  verified in a real browser at 11/11.

## Phase 2B — One taxonomy, end to end

  Added 2026-08-19 and rescoped the same day, at the user's direction: stability through
  simplicity, no legacy architecture running beside v2, unified processes, and no fear of
  breaking things — "what exists is mere inspiration for the direction we are headed."
  Efficiency is wanted at both ends, front and back.

  Numbered `2B` rather than renumbering Phases 3-9: that cascade would have touched ~30
  references, including the refusal text a user reads ("Non-adiabatic couplings land in
  Phase 5"), a test asserting on it, three spike docstrings, and a `bse_basis.py` comment
  reading "Phase 3: ORCA" that is not an overhaul phase at all.

  **Supersedes a Phase 2 decision.** P2.6's note said the v1-shaped runner key could
  persist and be retired per job family across Phases 5-8. Under the rescope it goes here
  instead: two mechanisms that both work is worse than one that works, because the pair
  must be kept in agreement forever and the disagreement is what eventually bites.

  What is duplicated today: `validate_draft` decides what a job needs and where it runs,
  then the builders decide it again with v1 rules (six `missing_required_params`, four
  `default_engine`, live in the submit path); a spec carries both `task`/`subtype` and a
  v1 runner key bridged by two maps; and the frontend keys some renderers on one, some on
  the other.

- [done] P2B.1 — Registry2 decides; builders construct only (drop v1 validation/routing from the submit path)
  evidence: tests/backend/reg2b_01_no_v1_redecision.py → "16/16 checks passed; default_engine and
  missing_required_params are no longer imported into app.agent.tools, and no builder function's
  source (`_build_spec_or_error` and its four per-task builders, plus `_spec_from_draft`) calls either
  one; registry.py itself is untouched, its exports just have no callers left in the submit path"
  regression: tests/backend/elic_01_draft_scenarios.py (201/201), tests/backend/agent_02_draft_flow.py
  (35/35 -- including the approval-gate and pre/post-interrupt determinism checks), and
  tests/backend/scan_01_draft_shapes.py (13/13) all still pass unchanged
  note: the removed calls were exactly the six missing_required_params + four default_engine call
  sites the plan named -- verified by grep before and after. `resolved_engine` in each builder is now
  simply the `engine` argument (already registry2's routing decision by the time a ready draft reaches
  `_spec_from_draft`, via `draft.get("resolved_engine")`), not re-derived. Left in place, as genuinely
  out of this step's scope (not part of the named six/four, and not something registry2's ParamSpec
  table can express -- no "present but out of range" concept exists there): the n_samples 1..250 range
  check, the scan_job_type-validity/shape-ambiguity guards (derivation of an internal dispatch key, not
  user-facing validation), the custom-job engine-in-(orca,bagel) guard, and the
  conical_intersection-requires-bagel guard. Also left in place, deliberately: the P2.2-recorded open
  item that `_build_ensemble_spec_or_error` re-reads the source frequency job from disk before the
  approval interrupt rather than trusting the draft alone -- that is a considered exception to
  "verdict is a pure function of the draft" (validate_draft's own `check_external` flag exists because
  of it), not the v1-redecision duplication this step targets, and redesigning it is a separate,
  riskier change than this step's accept criterion calls for.
- [done] P2B.2 — Runners dispatch on (task, subtype, method); delete _LEGACY_JOB_TYPE and _EXCITED_STATE_JOB_TYPE
  evidence: tests/backend/reg2b_02_scan_dispatch_e2e.py → "8/8 checks passed" -- see P2B.4's
  evidence line immediately below, which this step shares (landed as one commit; see its note
  for why).
- [done] P2B.4 — spec.method becomes the level of theory, task carried by task/subtype
  note: landed as one commit (P2B.2+P2B.4), per the plan's own note that these two are not
  separable -- runner dispatch cannot be freed from spec.method while spec.method still carries
  the runner key, and spec.method cannot be freed while dispatch still reads it.

  New module `app/chemistry/jobs/dispatch.py::resolve_runner(task, subtype, method)` is now the
  single derivation from the v2 taxonomy to which run_*/build_input_preview function handles a
  job -- called only at the point of actual dispatch (each worker's `main()`, preview.py), never
  at spec-construction time. `_LEGACY_JOB_TYPE`/`_EXCITED_STATE_JOB_TYPE`/`_legacy_job_type` are
  deleted from tools.py outright, not relocated under a new name -- an earlier draft of this step
  relocated+renamed them instead, which the advisor call caught as exactly the "runner key in the
  old vocabulary bridged by a mapping table" the no-legacy-compatibility decision prohibits.

  `JobSpec.method` now holds the level of theory ("hf"/"dft"/"casscf"/"caspt2"/"eom_ccsd"/... --
  registry2's CANONICAL_METHODS), "" for a task with none (blind: raw text only). Runner internals
  (build_input_preview/run_* functions) were left reading `params["method"]` completely unchanged
  -- each worker's `main()` and preview.py inject `params["method"] = spec.method` into a local
  copy right before calling into them, so there is exactly one persisted "method" (on `spec.method`
  itself), not a second copy duplicated onto `spec.params`.

  Master task sub-jobs (pes_1d/interp_pes -> single_point/gs; wigner_spectra -> single_point/ee,
  both at the master's own method) are now constructed directly with `task`/`subtype`/`method` in
  `JobManager.submit_scan`/`submit_ensemble`/`EnsembleOrchestrator._dispatch_more`, replacing
  `method=master_spec.params["scan_job_type"]` -- `scan_job_type` no longer exists as a stored
  param at all (it was never a real registry2 param; registry2/params.py never had an entry for
  it). `is_master_spec`/`spec_task` in base.py, and every `spec.get("method") == "pes_scan"`-shaped
  reader across scan_orchestrator.py, ensemble_orchestrator.py, job_watcher.py,
  server/routes/jobs.py and chat.py, and elicitation.py's `_source_frequency_problem`, are now
  keyed on `task`/`subtype` alone -- the v1-runner-key fallback each of these carried (originally
  added so a job submitted between the Phase 2 agent rebuild and this switch would still resolve)
  is removed outright, per the no-legacy-compatibility decision: no on-disk spec is expected to
  exist without a task.

  `app/chemistry/jobs/naming.py::auto_job_name` (the Job Manager's default label) was keyed on the
  v1 job-type string via `_METHOD_LABELS`; rekeyed onto `(task, subtype)` via `_TASK_LABELS`, with
  the level-of-theory detail (functional/CAS space/HF-DFT) now read directly off `spec.method`
  rather than a second `params["method"]` that no longer exists.

  frontend/src/approvals/JobApprovalCard.tsx's two `pending.job_type` reads (the approval-card
  heading, and the recommend_active_space-specific "no single input file" note) are updated to
  `pending.task`/`pending.subtype` -- `job_type` is dropped from the `interrupt()` payload
  entirely rather than kept correct via a `resolve_runner` call, per the same no-bridge decision:
  `resolve_runner` has no entries for master/blind tasks (by design -- see its own docstring), and
  widening it just to serve a display string would be exactly the mapping table being removed. This
  was the one part of the change that reaches the frontend; the rest of P2B.5's frontend audit
  (JobDetailDrawer, JobsPanel, excitedState.ts, scan_job_type in job summaries) is unstarted and
  remains that step's job. **Not verified in a browser** -- the dev stack tracks `main`, not this
  worktree; a Playwright check of the approval card lands with P2B.5/P2B.7, which own that surface.

  evidence: tests/backend/reg2b_02_scan_dispatch_e2e.py → "8/8 checks passed; a real water
  HF/STO-3G pes_1d scan (3 points) submitted through the actual JobManager.submit_scan path
  reaches 3 child jobs, each spec.json shaped task=single_point/subtype=gs/method=hf, and all
  three reach status=completed via the real PySCF worker's new resolve_runner-based dispatch --
  the one path unit tests on a not-submitted spec can't cover: a mistake in child-spec
  construction or worker DISPATCH lookup producing N malformed jobs instead of one clean error"
  regression: tests/backend/reg2b_01_no_v1_redecision.py (16/16), agent_02_draft_flow.py (35/35),
  elic_01_draft_scenarios.py (201/201), scan_01_draft_shapes.py (13/13), tax_01_v2_specs.py
  (30/30 -- rewritten from the P2.6-era "runner key" assumptions this step retires),
  tax_02_job_rows.py (22/22, same), reg_01_wigner_prep.py (rewritten to call
  _build_ensemble_spec_or_error's new signature with an already-resolved engine/method, matching
  what registry2 now guarantees), tddft_01_full_response_default.py (12/12, rewritten off a
  directly-constructed v1-shaped JobSpec) all pass. perf_03_jobmanager_cap_enforcement.py's
  JobSpec(method="casscf", ...) fixture is updated to task="single_point"/subtype="gs" for
  correctness but NOT run this session -- it drives real ORCA/BAGEL CASSCF jobs inside the
  docker-compose stack via `docker compose exec`, which this worktree does not have access to;
  left for P2B.7's regression pass.
  `_make_completed_frequency_job()` in elic_01_draft_scenarios.py was rewritten from a v1-shaped
  fixture (`{"method": "frequency", ...}`, no `task` key) to a v2-shaped one, because
  `_source_frequency_problem` no longer falls back to reading `spec["method"]` as a runner key.
  Worth being explicit about what that trades away, not just what it fixes: before this step, that
  fixture was the only test exercising `_source_frequency_problem` against a genuinely v1-shaped
  on-disk spec, so the failure mode "a spec has no `task` at all" is no longer covered by anything
  -- correct under no-legacy-compatibility (no such spec is expected to exist), but a real drop in
  coverage, not merely a fixture correction, and worth knowing if a future step needs to reason
  about specs written before this migration.
  wigner_spectra's own submission path (JobManager.submit_ensemble/EnsembleOrchestrator's child
  dispatch) is unit-verified (reg_01_wigner_prep's master-spec build) and verified-by-symmetry
  with submit_scan's now-confirmed-correct pattern, but not driven end-to-end the way
  reg2b_02_scan_dispatch_e2e.py drives pes_1d -- a full wigner_spectra run needs a completed
  frequency job as a source and is minutes of real TDDFT compute; left for P2B.7.
- [done] P2B.3 — Delete app/chemistry/jobs/registry.py
  evidence: `git rm app/chemistry/jobs/registry.py`; grep swept for every remaining
  `chemistry.jobs.registry` reference across app/, server/, tests/ first. Two real
  importers were left after P2B.1/2/4: app/agent/tools.py's `PARAM_HELP` (one call site,
  the CAS active_electrons/active_orbitals cross-field message) -- swapped onto
  `registry2.params.PARAMS_BY_NAME[p].help`, which already carries the same text -- and
  `METHODS`, which turned out to already be unused (P2B.2/4 had removed its last call
  site without a matching import cleanup). registry2/tasks.py, registry2/__init__.py and
  server/routes/registry.py, flagged in the P2B.2/4 note as needing untangling first,
  turned out to already import only registry2 -- that untangling had already happened
  earlier in P2B. The two test files that imported `jobs.registry` were rewritten rather
  than left importing a module about to vanish: reg2_01_registry_v2_payload.py's `v1`
  import was dead code (the "v1 key no longer served" check compares against a fixed
  list of key names, never dereferences the module) and is now documented as such;
  reg2b_01_no_v1_redecision.py's `run_still_defined_elsewhere` asserted registry.py was
  untouched, which was P2B.1-scoped and false the moment P2B.3 lands -- replaced with
  `run_module_gone`, asserting `import app.chemistry.jobs.registry` now raises
  `ModuleNotFoundError`. Full re-run after the deletion: reg2_01_registry_v2_payload.py
  (20/20), reg2b_01_no_v1_redecision.py (15/15), tax_01_v2_specs.py (30/30),
  tax_02_job_rows.py (22/22), agent_02_draft_flow.py (35/35), elic_01_draft_scenarios.py
  (201/201), scan_01_draft_shapes.py (13/13), reg_01_wigner_prep.py (all pass),
  tddft_01_full_response_default.py (12/12), reg2b_02_scan_dispatch_e2e.py (8/8, real
  worker dispatch re-verified against the now-registry.py-free import graph).
- [done] P2B.5 — Frontend keyed on the task, once; no renderer on a runner key
  evidence: `tsc -b` clean (frontend/node_modules symlinked in from the main checkout for this
  worktree session only, then removed again -- not committed, not the dev stack's own install).
  A full grep sweep for `.method === "` and `job_type`/`scan_job_type` across frontend/src found
  three real post-P2B.4 regressions, all now fixed:
  - `frontend/src/jobs/excitedState.ts`'s `normalizeExcitedStates`/`oscillatorSeries` compared
    `job.method === "tddft"`, which can never be true any more -- "tddft" is a runner key
    (dispatch.py's return value), and `spec.method` now holds the level of theory ("dft" or "hf")
    instead. Every DFT/HF-referenced excited-state job's table and UV/Vis spectrum silently
    stopped rendering the moment P2B.2+P2B.4 landed. Fixed by gating on `job.subtype === "ee"`
    instead (verified safe: registry2/params.py's `n_states` is `required_when subtype in
    ["ee","nac","ci"]`, never a signal that sets subtype, so there is no path to an excited-state
    job with any other subtype), and picking the ground-state summary key off `method ===
    "eom_ccsd"` specifically rather than off the now-impossible "tddft" comparison. Also added a
    `job.task !== "single_point"` guard the original code lacked: `job.method === "casscf"` is
    genuinely ambiguous now between a real CASSCF single-point job and a cas_reco/autocas job
    (registry2/tasks.py gives cas_reco `methods=("casscf",)` too), which share nothing else.
  - `frontend/src/jobs/JobDetailDrawer.tsx`'s `isNebTs = job?.method === "neb_ts"` and
    `isActiveSpaceRec = job?.method === "recommend_active_space"` had the same failure mode --
    both compared against runner keys that no longer appear in `method`. The NEB-TS path
    viewer/plot and the whole active-space-recommendation section (findings summary, plateau
    image, recommended space) stopped rendering for real jobs of exactly those types. Fixed to
    `job?.task === "neb_ts"` / `job?.task === "cas_reco"`.
  - The drawer's task/method heading (`{job.method} · {job.engine}`) read as a plain CASSCF
    single point for a cas_reco job (same method value, different task) -- now shows
    `{task}{/subtype} · {method} · {engine}`.
  - `frontend/src/lib/api.ts`'s `JobRow.method`/`.task` doc comments were rewritten -- they
    described `method` as "the runner key" (P2B.4 retired that meaning) and described an empty
    `task` as an expected pre-taxonomy case (Phase 1's clean-slate wipe means no such job exists
    any more; P2B.4's tracker note already established this as policy).
  `frontend/src/jobs/JobsPanel.tsx`'s `job.method ?? "job"` fallback (only reached when `job.task`
  is falsy) and `ScanPlot.tsx`'s docstring mention of "scan_job_type" were both checked and left
  alone: the former is genuinely unreachable dead code under the same no-empty-task policy above,
  the latter is prose describing a still-accurate concept (the master job's resolved runner key,
  which `job.summary["scan_job_type"]` still carries -- `submit_scan`/`submit_ensemble` in
  base.py still write it into the master's own summary for display; only the *stored child-spec
  param* of that name was removed in P2B.4).
  **Not verified in a browser.** `JobsPanel` requires an `activeThreadId`, which only exists once
  a thread has been created through the chat path, which needs Ollama and a seeded KB -- a live
  dev-stack dependency this isolated worktree does not have (confirmed via an advisor call before
  attempting a workaround). P2B.7 owns the Playwright pass against `main` on the real dev stack;
  this step's evidence is code-level (`tsc -b`, the grep sweep above, and the subtype/n_states
  proof for the guard) rather than rendered pixels.
- [done] P2B.6 — e2e MATRIX + EXPECTED_SUMMARY_KEYS keyed on v2 (task, subtype, method)
  Migrated `tests/e2e/_probes.py`'s `MATRIX` (26 cells) and `DISALLOWED_PAIRINGS` (8 rows), and
  `tests/e2e/e2e_08_job_matrix.py`'s `EXPECTED_SUMMARY_KEYS`/`prompt_for`/`human` lookup and
  `e2e_06_agent_tools.py`'s consumption of `DISALLOWED_PAIRINGS`, off the v1 job_type vocabulary
  onto v2 (task, subtype, method). This step could not be run against the live stack it targets
  (Ollama, a seeded KB, ORCA/BAGEL licenses -- none available in this worktree), so the work here
  is the migration plus everything checkable without that stack: `registry2`'s capability
  functions (`supports`, `missing_required`) are pure in-process Python, and both tables exist
  specifically to encode what those functions decide, so the actual verification method was
  checking every migrated row against them directly rather than assuming the mapping was right.
  That surfaced four findings worth recording, since they are real architecture facts a future
  session needs, not migration bugs to quietly paper over:
  - **D08 dropped from DISALLOWED_PAIRINGS, not migrated.** v1's row asserted plain single-point
    HF was refused on BAGEL. Checked directly: `supports("bagel", "hf", "single_point", "gs")`
    returns `supported=True` (BAGEL's `MethodCaps` row for hf has `energy=True`). v1's
    `registry.py` had an `ALLOWED_ENGINES` restriction excluding BAGEL from plain single points as
    an app-level policy choice, independent of physical capability; v2's capability-driven model
    carries no such extra restriction. This is a real, user-visible capability change that landed
    somewhere in P2B.1/2/4 as a side effect of retiring the v1 registry, not a P2B.6 regression --
    BAGEL is now a legitimate engine for a plain single-point HF energy, where it previously
    wasn't. Recorded here because nothing else in this phase's tracker entries mentions it.
  - **E05 (mo_visualization/orbital_indices) in `ELICITATION_NEGATIVES` has no v2 equivalent.**
    `orbital_indices` carries no `required_when` in registry2/params.py -- confirmed via
    `missing_required("single_point", "gs", "hf", "pyscf", {})`, which returns nothing for it.
    There is no mechanical registry hook forcing the agent to ask for it; if omitted, MO
    visualization silently degrades to a plain energy job with no orbitals rendered. `MATRIX`'s
    M18-M20 (the mo_visualization cells) carry a note flagging that `EXPECTED_SUMMARY_KEYS` alone
    cannot catch this -- a live run must check the approval card's params for `orbital_indices`
    explicitly.
  - **`ELICITATION_NEGATIVES` itself is dead and was NOT migrated.** Nothing imports it --
    confirmed via grep across the whole tree. `e2e_18_elicitation.py` already covers this ground
    natively in v2, with its own hardcoded scenarios against registry2 directly, written after
    this table. Left in its original v1 shape as a record of what it once drove, with a comment
    explaining why, rather than migrated for cosmetic consistency with MATRIX.
  - **No registry2 ParamSpec exists for a NEB-TS end geometry at all** (grep
    `applies_to=("neb_ts",)`: only `preopt` and `n_images`). M23's "needs an end molecule"
    requirement is enforced entirely through conversation-state elicitation, not `missing_required`
    -- confirmed by `missing_required` returning `[]` for M23's full params with no end-geometry
    key. `reg2b_03_matrix_v2_taxonomy.py` cannot and does not check this; only a live conversation
    can.
  `SLOW_ORCA`/`SLOW_BAGEL` in `_probes.py` (also dead, also unmigrated by the same reasoning as
  `ELICITATION_NEGATIVES`) had their `"job_type": "casscf"` key folded into `params` instead, since
  they sit four lines from the migrated MATRIX and leaving the exact removed key name there read as
  a miss rather than a decision.
  evidence: tests/backend/reg2b_03_matrix_v2_taxonomy.py → "120/120 checks passed" -- every MATRIX
  cell's (task, subtype) is a real registered task, every cell's (engine, method, task, subtype) is
  genuinely supported, every cell's own params satisfy missing_required (with M24/M25's blind-job
  gap and M23's clean pass both asserted as intentional, not accidental), every DISALLOWED_PAIRINGS
  row is genuinely refused, D08's drop is independently verified (not assumed), every (task,
  subtype) in MATRIX has an EXPECTED_SUMMARY_KEYS entry, and prompt_for builds a non-empty request
  for every non-special-cased cell. **Not run against the live stack**: e2e_08_job_matrix.py itself
  (needs a real agent conversation reaching an approval card and a real job completing) and
  e2e_06_agent_tools.py's refusal loop (needs the same). Both are P2B.7's job.
- [done] P2B.7 — Regression pass: backend suite, job matrix, Playwright approval + drawer
  Run against the real dev stack (`scripts/dev_stack.sh up`, commit 4eaf81f then the fixes below),
  not a worktree — the first time this phase's changes have been exercised end to end rather than
  checked in isolation. Three real, pre-existing bugs were found and fixed along the way, all
  invisible until something finally drove the exact path they sat on:
  - **`_source_frequency_problem` (registry2/elicitation.py) read the wrong file for job status.**
    It called `read_meta(job_id)` and looked for a `"status"` key there, but status lives in
    `status.json`/`read_status` -- `meta.json` is the mutable label/favorite file and has never
    carried a `"status"` key. So the check `(meta or {}).get("status") != "completed"` was `True`
    unconditionally, for every job, regardless of actual state. Consequence: a wigner_spectra
    draft's `source_frequency_job_id` could NEVER pass `update_job_draft`'s external check --
    `check_external=True` is that tool's default -- so the draft could never reach `ready` and
    `submit_draft` was never reached, no matter how genuinely complete the source frequency job
    was. `submit_draft` itself calls `validate_draft(..., check_external=False)`, so this was
    invisible from that side entirely. Found by driving a real wigner_spectra conversation end to
    end (see below) and watching the agent report "the backend keeps saying my source job isn't
    finished when I can see it's completed" -- a live symptom no unit test surfaces, because two
    existing unit-test fixtures (`elic_01_draft_scenarios.py`'s `_make_completed_frequency_job`,
    `tax_01_v2_specs.py`'s own inline fixture) wrote `meta.json` with a `"status"` key to match
    the bug, not `status.json` to match reality -- the tests were asserting the code was
    internally consistent with itself, not that either matched a real job's shape. All three
    fixed (elicitation.py reads `read_status`; both fixtures now write `status.json`). Predates
    P2B entirely -- unchanged by 96b6a29's own diff to this function, confirmed by `git show`.
    `tests/backend/elic_01_draft_scenarios.py` (201/201), `tax_01_v2_specs.py` (30/30) re-verified
    after the fix.
  - **`tests/backend/sniff_01_pasted_inputs.py`'s own `generated()` helper was never migrated off
    v1.** It called `JobSpec(method=<v1 job_type string>, engine=engine, params=params)` --
    `method` held things like `"single_point"`, `"geometry_optimization"`, `"tddft"`, `"caspt2"`,
    a fossil of the era before P2B.2/P2B.4 split `task`/`subtype` out of `method`. Every ORCA
    `generated(...)` call crashed outright (`ValueError: No runner is wired up for / yet.` --
    `task`/`subtype` were never set, so `resolve_runner("", "", ...)` had nothing to resolve);
    the BAGEL cases happened to not crash but built the wrong method for the CASPT2 case (the
    shared `CAS` params dict's own `"method": "casscf"` silently overrode what the case was
    supposed to test). Fixed by rewriting `generated()` to take an explicit `(engine, task,
    subtype, method, params)` and updating every call site to the v2 shape it should have had
    since P2B.2/P2B.4. 69/69 after the fix (up from a crash on line 1).
    **Both container-image bind-mount note, for the next session**: the api container does NOT
    bind-mount `app/` -- only `./data`. A host-side fix to `app/*.py` needs `scripts/dev_stack.sh
    up` (rebuilds via its own `--build`) before anything driven through the live HTTP API sees it;
    `tests/backend/*.py` scripts import `app.*` directly on the host and see a fix immediately,
    which is why the elicitation.py bug showed as fixed in `elic_01`/`tax_01` before it was
    verified fixed for real conversations below.
  - **`JobManager.submit_ensemble` and `EnsembleOrchestrator._dispatch_more` could double-dispatch
    the same sample.** `submit_ensemble` writes the master's status/result as "running" (so the
    job list shows something immediately), THEN runs its own `for i in range(wave_size): ...
    self.submit(sub_spec)` loop -- but the master is already visible to
    `_iter_running_ensemble_masters` the instant that first write lands, before any sub-job
    exists. A poll tick (every 3s) landing in that window calls `_dispatch_more`, which read its
    own `len(sub_ids)` off disk, saw zero, and dispatched a full wave of its own; when
    `submit_ensemble`'s own loop then ran, it dispatched the identical `range(wave_size)` again,
    since it had never checked what already existed -- two independent "how many are dispatched,
    send the rest" implementations, each blind to the other. A lock around each side's *own*
    existing loop would only have narrowed the window, not closed it, since `submit_ensemble`'s
    loop still wouldn't have checked for already-existing sub-jobs. Found by the same live
    wigner_spectra drive below: a real 5-sample run came back `n_dispatched=6`, one duplicate,
    which `pool_ensemble_transitions` then pooled and double-weighted without complaint (nothing
    checks for a repeated `_ensemble_index`). Fixed by removing `submit_ensemble`'s own dispatch
    loop entirely and having it call straight into `_dispatch_more` for its initial wave too, so
    there is exactly one function that ever decides "which indices to send," guarded by one
    `dispatch_lock`, always re-reading `sub_job_ids_of` fresh under that lock rather than trusting
    a snapshot taken before it was acquired. Re-verified against the rebuilt dev stack: two clean
    live runs (`--n-samples 5` and, to actually widen the race window rather than hope it recurs
    by chance, `--n-samples 20`, since a longer initial-wave loop gives the 3s poll tick
    proportionally more chances to land inside it) both came back with `_ensemble_index` values
    exactly `0..N-1`, no duplicates, no gaps -- `tests/e2e/e2e_19_wigner_ensemble.py` now asserts
    this directly (the final `n_dispatched` count alone can look right even when a duplicate and a
    drop both happened, so it isn't a substitute for checking the actual indices).

    Unifying the two dispatch paths this way introduced -- and then, before it was committed,
    surfaced -- two more problems, both caught by the advisor review this step's own convention
    calls for before declaring a fix done, not by any test (`e2e_19` sources only from a plain
    `freq` job, so neither is reachable from it):
    - `_dispatch_more`'s own `sample_from_source_job` call passed `source_spec["molecule"]`
      unconditionally, where `app/agent/tools.py`'s two callers of the same sampler both branch on
      `source_spec["task"] == "opt_freq"` and use `summary["optimized_molecule"]` instead --
      the *pre*-optimization input geometry an opt_freq job started from, not the equilibrium
      structure its own normal modes were actually computed at. Before this step's refactor only
      `EnsembleOrchestrator`'s later top-ups took this path (the initial wave used the caller's own
      correctly-sourced `samples`), so this was a narrower, pre-existing bug; after the refactor
      every sample of an opt_freq-sourced ensemble would have been silently generated around the
      wrong geometry, with `ensemble_xyz` (still written from the correct source) disagreeing with
      what actually ran. Fixed by mirroring tools.py's branch inside `_dispatch_more` itself.
    - The count-based `range(n_dispatched, n_dispatched + wave)` this bullet's fix still used is
      only correct while existing indices occupy a contiguous `0..n_dispatched-1` block -- exactly
      the assumption `submit_ensemble`'s own docstring already names as unsafe (quota eviction can
      reap the ensemble's earliest sub-jobs before the rest finish). A hole from an evicted index 0
      would never be revisited; the next top-up would dispatch a duplicate at the far end instead.
      Pre-existing, not introduced by this step, but the bullet above claims "no way for them to
      duplicate an index between them," which the count-based range didn't actually deliver. Fixed
      by reading each surviving sub-job's real `_ensemble_index` and dispatching the actual missing
      values, capped at `available`, rather than a length-derived range. Left as a known, narrow
      gap rather than fixed further: `_update_one` still sets the master's own summary
      `n_dispatched` to `len(sub_ids)` (directories present), not to the size of the
      `_ensemble_index` set the dispatch decision now actually uses -- the two agree except under
      eviction, where `n_dispatched` would count an evicted-and-not-yet-redispatched slot as sent.
    Re-verified after both: `tests/backend/reg_01_wigner_prep.py` (still passes -- the preview path
    it drives never went through `_dispatch_more`), the full backend suite (40/40, see evidence
    below), and one more live `e2e_19_wigner_ensemble.py` run (20/20, `_ensemble_index` values
    `[0,1,2,3,4]`) against the rebuilt dev stack.

  evidence: tests/backend/_00_bootstrap.py → "qatest_admin already provisioned and reachable"
  evidence: tests/run_backend.sh (`PYTHONPATH=$PWD QC_AGENT_TEST_BASE_URL=https://127.0.0.1:8444
  bash tests/run_backend.sh`, `QC_AGENT_TEST_BASE_URL` per the dev stack's own nginx port, 8444 on
  this host -- see `.env`'s `QC_AGENT_DEV_PORT`) → "40/40 scripts reported all checks passing"
  (final run, after all fixes above)
  evidence: tests/e2e/e2e_08_job_matrix.py --tier 1 → "45/51 checks passed", 3 of 26 tier-1 cells
  not clean, none of them a P2B regression:
  - **M02** (plain single_point/gs/orca) reached an approval card in some runs and not others
    across this session's several invocations (`update_job_draft` looped without ever calling
    `submit_draft`) -- the documented "flaky-local-model allowance" this harness already accounts
    for (`_agent.py`'s own docstring), not a new failure mode; identical params on `pyscf` (M01)
    passed cleanly every time.
  - **M10** (CASSCF/orca with `want_oscillator_strengths`, "the SLOW probe") has never passed in
    any of the 5 runs recorded in `tests/e2e/results/*.jsonl` across this session, going back to
    before P2B.7 started. Already recorded in this file's P2 history as "a harness artifact, not
    a stall: the same request reaches an approval card 3/3 through the graph on the same code, and
    0/2 through the e2e path" -- unchanged by anything in P2B, and closed there deliberately
    rather than chased further.
  - **M26** (cas_reco/autocas/pyscf) is a genuinely new symptom, not the old one: it now reaches
    `submit_draft` (the P2-era "stalled after draft" harness bug this cell used to hit is fixed),
    but the submitted job itself fails: `RuntimeError: The AVAS pilot space for this molecule
    (6e,3o) can host at most 1 many-electron configuration(s), fewer than the 3 states requested`.
    This is the probe's own params (`n_states=3` on water/STO-3G) asking for more states than
    water's AVAS pilot space can host at this basis -- a real, previously-hidden limitation of
    this specific probe, unrelated to task/subtype/method (the AVAS pilot-sizing code was not
    touched by P2B), surfaced now only because the harness-level stall that used to mask it is
    gone. Left unfixed: fixing it means picking a probe (bigger basis, fewer states, or a
    different molecule) that a chemist should choose, not a mechanical migration correction.
  evidence: tests/e2e/e2e_06_agent_tools.py → "13/13 checks passed in this script" -- every
  non-`submit_draft` tool, elicitation, and all four disallowed engine/method pairings, clean.
  evidence: tests/backend/perf_03_jobmanager_cap_enforcement.py → "7/7 checks passed" -- the
  per-user concurrency cap deferred from P2B.2 (JobSpec fixtures updated to task="single_point"/
  subtype="gs" there but not run) is now driven for real: a water CASSCF(4,4)/STO-3G job on ORCA
  and on BAGEL each dispatch correctly under the v2 taxonomy, and a second job for the same user
  is genuinely held pending citing the per-user cap while the first runs.
  evidence: tests/e2e/e2e_19_wigner_ensemble.py (new -- the wigner_spectra live drive deferred by
  P2B.2+P2B.4 and P2B.6, since neither could reach a real completed frequency job to sample from)
  → 4/6 and 6/18 blocked on the `_source_frequency_problem` bug above; after that fix, a clean
  5-sample run surfaced the dispatch-race bug above instead (`n_dispatched=6` against a requested
  5, one duplicate `_ensemble_index`); after BOTH fixes, "20/20 checks passed" at `--n-samples 5`
  and again "20/20 checks passed" at `--n-samples 20` (a deliberately wider run to close, not just
  narrow, the dispatch-race window -- see that bullet), with the added index-level check (exactly
  `0..N-1`, no dupes, no gaps) passing both times. Drives a real two-turn conversation -- a water
  HF/STO-3G frequency job submitted and approved, then a nuclear-ensemble TDDFT/B3LYP/STO-3G
  spectrum sampled from it, approved, and polled to completion -- and checks the approval card
  names the right source job, the master's pooled summary reports usable (energy, oscillator
  strength) pairs, every dispatched sample has a distinct `_ensemble_index`, and all three
  declared artifacts (`ensemble_xyz`, `ensemble_spectrum`, `ensemble_spectrum_data`) download.
  evidence: frontend/`npm run test:e2e` (`QC_AGENT_TEST_BASE_URL=https://127.0.0.1:8444`, against
  the docker dev stack, its documented default target) → "7/9 specs reported all checks passing".
  The two non-passing specs are pre-existing, already-documented setup dependencies, not
  regressions -- matching the exact pattern recorded earlier in this file's P1/P2 history:
  `draft_01_approval_card.spec.mjs` needs a standalone Vite dev server + bare backend on :8000/
  :5173 (the docker stack serves everything through nginx on :8444 instead), and
  `fail_01_notice_card.spec.mjs` needs a bespoke harness that seeds a failed job and exports
  `QC_AGENT_TEST_THREAD_ID`/`QC_AGENT_TEST_JOB_ID` before launch, which nothing in this repo
  currently provides.
  Additionally ran `draft_01_approval_card.spec.mjs` standalone (`python3 -m server.main` on
  :8000 + `vite --port 5173`, matching the prior phases' own practice for this spec, per this
  file's P1/P2 entries), and found a second real, pre-existing bug along the way: the spec's own
  two `page.waitForFunction(fn, { timeout: N })` calls silently drop the timeout. Playwright's
  real signature is `waitForFunction(pageFunction, arg, options)` -- a two-argument call with a
  zero-parameter `pageFunction` binds the object as `arg`, not `options`, so every wait in this
  spec was actually capped at Playwright's 30s default regardless of the 60000-240000 requested
  (confirmed empirically: a bare repro with `{ timeout: 5000 }` measured 30020ms elapsed before
  timing out). Fixed by passing an explicit `undefined` arg before `options` at both call sites.
  After that fix the spec still did not complete clean in the bare/:5173 environment: the
  browser's SSE connection to `/events` reproducibly drops ("Lost connection to the server --
  reconnecting...") shortly after the first message posts, even though the SSE endpoint itself is
  confirmed healthy by direct `curl` (immediate `: connected` preamble, both hitting :8000
  directly and through the Vite proxy on :5173) and even though this exact session's own
  httpx-based SSE conversations (e2e_06, e2e_08, e2e_19, each holding a stream open across
  multi-minute real LLM turns) ran cleanly for hours against the docker dev stack. This localizes
  the drop specifically to the bare single-process `python3 -m server.main` + Vite dev-proxy
  combination -- not the documented dev-stack path `scripts/dev_stack.sh`/`docs/WORKFLOW.md`
  actually gate promotion on -- so it is recorded here as an open environment note for a future
  session that wants the lightweight two-process dev loop to be Playwright-clean, not chased
  further or fixed speculatively in this pass.
- merged: —

  (this row is vestigial under the work-directly-on-main policy adopted 2026-08-19: every P2B
  commit above landed straight on `main`, so there is no separate merge commit to record here --
  left blank rather than backfilled with a hash that would misleadingly suggest a real merge)

## Phase 3 — Geometry input & uploaded-file manager

  note: P3.2 landed first (advisor-recommended order: the parser is pure
  in-process Python with zero stack dependency, and P3.1/P3.3 both consume
  its output shape), then P3.1, then P3.3 -- all three verified together
  against the real docker-compose dev stack before this commit, since
  `up_01_lifecycle.py` exercises P3.1 and P3.3 in one script.

- [done] P3.1 — server/routes/uploads.py (lifecycle, quota, ownership)
  evidence: tests/backend/up_01_lifecycle.py → "31/31 checks passed against the real dev stack --
  upload/list/quota/delete/clear-all, each ownership-scoped (a second user sees and can touch
  none of the first user's uploads, verified as 404s not empty-but-visible)"
  note: uploads get their OWN store (`app/uploads/`) and their OWN directory
  (`GEOMETRY_UPLOADS_DIR = data/geometry_uploads`), deliberately not KB's
  `UPLOADS_DIR` despite the plan text's literal "data/uploads/<owner>/" --
  that directory is already owned by KB's semantics end to end:
  `app/rag/store.py::orphaned_upload_files` sweeps any file there with no
  matching Chroma entry as a leaked KB upload (would delete a geometry file
  on sight), and `app/auth/storage_quota.py`'s KB accounting enumerates
  from Chroma, so a geometry file living there would be invisible to every
  quota category at once on a multi-user deployment -- an unbounded growth
  vector. `app/config.py::GEOMETRY_UPLOADS_DIR` docstring records this.
  Quota is a full 4th category alongside kb/job/chat in
  `app/auth/storage_quota.py` (own per-user cap
  `DEFAULT_PER_USER_UPLOADS_QUOTA_BYTES=500MB`, own admin-editable config
  key, own pass in `enforce_all_quotas`, folded into the global cap and
  `purge_user_data`) -- not merged into jobs+chat, on the same reasoning KB
  gets its own pass rather than being folded in. Ownership uses
  `app/auth/ownership.py`'s generic `record`/`check_owner_or_admin`
  directly (kind="upload") rather than KB's bespoke Chroma-metadata
  approach, since an upload has no vector-store entry to key off. This
  required a real schema change (`app/auth/db.py`): `ownership_index`'s
  `kind` CHECK constraint only admitted `('thread','job')`; the first live
  upload attempt hit `psycopg.errors.CheckViolation` against the ALREADY-
  RUNNING dev stack's Postgres, confirming `CREATE TABLE IF NOT EXISTS`
  editing the literal doesn't reach a deployed database -- fixed with an
  idempotent `DROP CONSTRAINT IF EXISTS` + re-`ADD CONSTRAINT`, the
  standard pattern for a CHECK (no `ADD CONSTRAINT IF NOT EXISTS` in
  Postgres), alongside the existing `ADD COLUMN IF NOT EXISTS` migration
  block. This ALTER is forward-only per the standing rule -- name it
  explicitly if this commit is ever described for promotion.
  admin console: `per_user_uploads_quota_bytes` added to
  `_EDITABLE_CONFIG_KEYS` (server/routes/admin.py) for consistency with
  kb/jobs_and_chat/global, all four now editable the same way. The admin
  console's own storage-usage table/frontend is NOT updated to display an
  uploads column -- out of this phase's stated scope (Phase 9 owns the
  per-user danger-zone/admin UI); recorded here as a known gap rather than
  silently left undiscoverable.
- [done] P3.2 — Backend multi-geometry xyz parser + upload-time sniff
  evidence: app/chemistry/geometry_upload.py → "parse_multi_frame_xyz/sniff_xyz_upload verified
  directly: 2-frame and 3-frame files parse correctly (including a blank comment line defaulting
  to 'frame N', matching xyz.ts), and a truncated frame / non-numeric count line / malformed atom
  line / empty file each raise ValueError naming the frame index and the problem"
  note: **two parsers, for two different reasons, not duplication.**
  `frontend/src/molecule/xyz.ts::parseMultiFrameXyz` is kept, unchanged --
  its only remaining job is rendering an already-completed job's own
  path_xyz artifact (P3.4 confirms this: the geometry_set drawer fetches
  path_xyz via the existing artifact route and reuses xyz.ts, not a new
  frames endpoint), content this app itself wrote, so its documented
  leniency (a truncated trailing frame is silently dropped rather than
  raising) is fine for that purpose. The backend parser instead validates
  a file a user just handed the app -- untrusted input -- and raises on
  anything malformed rather than silently truncating, since a bad upload
  should be rejected at the boundary (upload time) rather than accepted
  and failing later at attach time. **The backend record (an upload's
  stored `sniff` field, computed once at upload time) is the sole
  authority for frame count/kind** -- the frontend never independently
  re-decides "3 frames -> geometry_set"; that decision is made once, in
  `app/uploads/store.py::add_upload`, and everything downstream (attach
  semantics, the Files panel's badge) reads it rather than re-parsing.
- [done] P3.3 — Attach semantics (1/2/≥3 geometries; geometry_set job; tests/backend/up_01_lifecycle.py)
  evidence: tests/backend/up_01_lifecycle.py → "31/31 checks passed -- 1-geometry and 2-geometry
  uploads attach as molecule_frames (first frame active, both present in thread state, verified
  after a fresh GET .../state, not just the POST response); a 3-geometry upload creates an
  immediately-completed geometry_set job (JobManager.submit_geometry_set, no engine/worker) plus a
  checkpointed notice message (app.agent.graph.append_notice, same mechanism as the P1.6 failure
  notice) that survives a reload and is published live over SSE; tagging frame 2 (1-based) of the
  geometry_set into a draft via POST .../tag_job_frame sets it as the active molecule, verified by
  name ('water stretched') not just success; an out-of-range frame_index is refused (400), and
  every cross-user path (another user's upload, job, or attach/tag against a thread they don't own)
  is refused as a 404, never a silent empty result"
  evidence: tests/backend/tax_01_v2_specs.py → "geometry_set is refused as a draft with a message
  pointing at attach, not submission -- see app/chemistry/jobs/dispatch.py's NOT_YET_IMPLEMENTED"
  note: **the advisor review caught a real gap before this could be marked done**: task="geometry_set"
  is a registered master task in `_NO_MOLECULE` with no required params, so an empty draft for it
  would otherwise reach `validate_draft`'s "ready" verdict and fall through `_build_spec_or_error`'s
  generic path -- a second, parallel mechanism creating the same kind of job the no-legacy-
  compatibility decision rules out. Fixed by adding `("geometry_set", "")` to
  `dispatch.NOT_YET_IMPLEMENTED`, consulted by `_spec_from_draft` before any builder runs; confirmed
  by driving `validate_draft` + `_spec_from_draft` directly both before (reached "ready" with an
  empty spec) and after (refused, naming attach as the correct path) the fix.
  frame injection: `app/agent/graph.py::add_geometry_frames` (new, alongside `add_built_frame`)
  writes one or more already-resolved molecules into `molecule_frames` in a single `update_state`
  call, making the FIRST molecule active -- generalizes `add_built_frame` to more than one frame at
  once rather than calling it N times (which would leave the LAST frame active, wrong for a 2-frame
  upload where the first/start endpoint should be the default). `server/routes/chat.py::attach_upload`
  and `::tag_job_frame` are both on the chat-route side specifically (never `uploads.py`, never a
  tool) per CLAUDE.md's lock rules: they touch graph state under `_lock_for_thread`, which
  `server/routes/jobs.py` must never do, and a tool function must never call
  `invalidate_graph_cache()`. A tagged frame is injected into `molecule_frames` (the sanctioned
  geometry slot `set_geometry`/`add_built_frame` already use), never absorbed into a draft
  parameter -- P2.2 already refuses a geometry landing in `params["molecule"]`, and duplicating that
  mechanism here would reopen exactly what that refusal closed.
- [todo] P3.4 — Composer + button, FilesSection below KB, geometry_set drawer (Playwright uploads spec)
- merged: —

## Phase 4 — Fair scheduler

- [todo] P4.1 — Extract _resources_available()
- [todo] P4.2 — scheduler.py (per-user queues, RR dispatcher, MASTER_MAX_IN_FLIGHT)
- [todo] P4.3 — Orchestrators trickle-enqueue
- [todo] P4.4 — Cancel pre-admission path + startup re-enqueue
- [todo] P4.5 — perf_04_fair_scheduling.py, perf_05_restart_queue.py, regressions
- [todo] P4.6 — Dev/production config parity check
- merged: —

## Phase 5 — Single-point family: gradients + NAC

- [todo] P5.1 — Registry2 entries sp/grad, sp/nac
- [todo] P5.2 — run_gradient (3 engines) + run_nac (per Phase 0 verdicts)
- [todo] P5.3 — Dispatch + summarize (matrix+norm tagging contract)
- [todo] P5.4 — GradientSection/NacSection in drawer
- [todo] P5.5 — Per-engine parse tests + central-difference cross-check + e2e + Playwright
- merged: —

## Phase 6 — Optimization family

- [todo] P6.1 — opt/constrained (pyscf, orca; bagel per verdict)
- [todo] P6.2 — opt/ci (bagel kept; orca/pyscf per verdict)
- [todo] P6.3 — opt/min polish (ES target_state; numerical-gradient warning)
- [todo] P6.4 — opt_freq single-input where confirmed; pyscf sequential verified
- [todo] P6.5 — Subtype tests + denial-path assertions + e2e + Playwright
- merged: —

## Phase 7 — PES family, batch, nested-preview performance

- [todo] P7.1 — pes_1d split (bagel denial + interp_pes recommendation)
- [todo] P7.2 — Standalone interp_pes (steps card, editable cascade template, atom reorder)
- [todo] P7.3 — Children pagination + lazy frame loads
- [todo] P7.4 — batch master task
- [todo] P7.5 — 200-child latency spec, cascade-edit e2e, batch e2e, reorder unit, NEB regression
- merged: —

## Phase 8 — CAS workflows, orbital reuse, ensemble spectra

- [todo] P8.1 — Cross-job orbital reuse (initial_orbitals_job_id; per-engine)
- [todo] P8.2 — cas_reco overhaul (explain/autocas/avas + follow-up CASSCF-ee draft)
- [todo] P8.3 — wigner_spectra via drafts; cap 250→500; live broadening slider (client-side)
- merged: —

## Phase 9 — Custom plotting, danger zone, polish, final docs

- [todo] P9.1 — plot(kind="custom") declarative plotting from tagged data
- [todo] P9.2 — Per-user danger zone (self-scoped purges; dz_01_self_purge.py)
- [todo] P9.3 — UI polish sweep (spectrum download buttons, 8x6 PNG symmetry, ensemble marker, MiniLineChart multi-series, MO viewer 20-unoccupied cap)
- [todo] P9.4 — Finalize MASTER_PLAN_SUMMARY.md, README, HelpFlyout, ARCHITECTURE addenda, CHANGELOG
- [todo] P9.5 — Full regression pass; tracker closed with merge-hash ledger
- merged: —
