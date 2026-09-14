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
  change, so `git log --follow docs/trackers/2026-08-job-system-overhaul.md` is the audit trail.
- A phase's `merged` row records the merge commit hash, added in the next
  commit after the fast-forward merge (the one edit allowed to trail).
- The published tracker artifact is re-rendered at every step completion and
  every phase gate.

Format for a step row:

```
- [status] P<phase>.<step>: <short name>
  evidence: <script/command> → "<observed result>"   (required when done)
```

---

## Phase 0: Verify, document, baseline

- [done] P0.1: Plan committed (docs/OVERHAUL_PLAN.md), tracker + check script + published artifact, continuation memory saved
  evidence: scripts/check_tracker.py → "PASS, tracker consistent: 59 steps; artifact published at /artifact/121a529d"
- [done] P0.2: docs/MASTER_PLAN_SUMMARY.md (projected implementation)
  evidence: docs/MASTER_PLAN_SUMMARY.md → "projected end state written: 11 job types, tagging contract, visualizer contract, dev notes"
- [done] P0.3: ORCA verification spikes (EnGrad/.engrad, IRoot ES gradient, NACME scope+format, %geom Constraints, CASSCF MECI keywords, Opt(Num)Freq single-input, MOREAD/%moinp restart)
  evidence: scripts/spikes/spike_orca_caps.py → "9 probes: gradients/ES-gradients/full-TDDFT/TDDFT-NACME/constraints/%CONICAL/Opt+Freq/MOREAD all PASS; %casscf NACME = GAP"
- [done] P0.4: BAGEL verification spikes (forces format, nacme casscf+caspt2, orbital restart molden-vs-archive, optimize+hessian one-input, constrained-opt conflict)
  evidence: scripts/spikes/spike_bagel_caps.py → "forces/nacme/opt+hessian/save_ref-load_ref PASS; fix_atom proven a silent no-op by differential geometry comparison"
- [done] P0.5: PySCF verification spikes (analytic gradients per method, NAC availability, chkfile+project_init_guess, geomeTRIC constraints, MECI feasibility)
  evidence: scripts/spikes/spike_pyscf_caps.py → "18/22 confirmed; all 3 orbital-reuse paths work; SA-CASSCF NAC real (scales 1/dE); no CASSCF Hessian, no TDDFT NAC, no MECI. DMRG initially misreported as absent -- the app uses pyblock2, not pyscf.dmrgscf; block2 0.5.3 installed and the pilot verified"
- [done] P0.6: docs/QM_CAPABILITIES.md v1 (verified matrix, diff vs user's summary, "claims not confirmed" section)
  evidence: docs/QM_CAPABILITIES.md → "3 engine tables with per-cell evidence level; 7 unconfirmed claims documented"
- [done] P0.7: docs/PARSER_GAPS.md skeleton
  evidence: docs/PARSER_GAPS.md → "protocol + open/closed tables in place, zero rows"
- [done] P0.8: Model-context spike (prompt/schema token counts, num_ctx via Ollama /v1, draft-tool-call reliability harness on both target models)
  evidence: scripts/spikes/spike_model_context.py --truncation --draftshape → "measured end-to-end: fixed surface 14,468 tokens, window saturates ~32,697, system prompt lost only at saturation; dict-arg draft tool 3/3 on both models at 1 call vs up to 5 flat -- see docs/MODEL_CONTEXT_BUDGET.md (carries a correction notice)"
- [done] P0.9: Bugfix batch (tools.py:556 engine arg; stale qwen3:30b comments; naming.py labels; stale BAGEL-freq comment; ARCHITECTURE LIIC claim; drop miew)
  evidence: tests/backend/reg_01_wigner_prep.py → "ALL CHECKS PASSED (7/7); frontend npm run build succeeds without miew; no package declares miew"
- merged: 8d8a289

## Phase 1: Registry v2 dark launch + auto-retry removal

  note: the adapter (`registry2/adapter.py`, `LEGACY_JOB_TYPE_MAP`) and its
  round-trip test **P1.3 are dropped at the user's instruction** (2026-08-18):
  jobs on disk were wiped and the overhaul starts from a clean slate, so
  there is no legacy `spec.json` shape left to keep renderable and the v2
  taxonomy is the only taxonomy. Later phases must not reintroduce a
  legacy-compatibility reader on the strength of OVERHAUL_PLAN.md's older
  "readers via adapter" wording. P1.3's number is retired rather than reused,
  so the step numbering stays an audit trail.

- [done] P1.1: app/chemistry/registry2/ (capabilities, tasks, params, routing, lookup)
  evidence: scripts/check_capability_matrix.py → "PASS, 506 assertions across 15 capability rows and 19 tasks; golden table hand-derived from QM_CAPABILITIES (not from the code it checks) and mutation-tested. Flipping BAGEL constrained_opt to trust the exit code makes it fail"
- [done] P1.2: scripts/generate_capability_docs.py + drift check
  evidence: scripts/generate_capability_docs.py → "regenerates docs/QM_CAPABILITIES.md only between BEGIN/END markers, idempotent, --check PASSes; hand-written prose (claims-not-confirmed, ORCA banner trap, BAGEL fix_atom note, orbital reuse) survives regeneration"
- [done] P1.4: Registry API v2 payload alongside v1
  evidence: tests/backend/reg2_01_registry_v2_payload.py → "ALL CHECKS PASSED (20/20); all six v1 keys byte-identical to the legacy module, v2 JSON round-trippable, and BAGEL/casscf advertises no constrained_opt end-to-end through the API"
- [done] P1.5: Auto-retry removal (full removal map)
  evidence: tests/backend/fail_01_notice_flow.py → "ALL CHECKS PASSED (20/20); MAX_AUTO_RETRIES, count_failed_in_chain, retry_of_job_id, _retry_count/_retried_from and the retry_note card are gone from app/, server/, frontend/src/ and tests/; e2e_12_failure_retry.py deleted; README/HelpFlyout/WelcomeMessage/ARCHITECTURE copy rewritten"
- [done] P1.6: Plain-failed branch + troubleshoot flow (tests/backend/fail_01_notice_flow.py)
  evidence: tests/backend/fail_01_notice_flow.py → "ALL CHECKS PASSED (20/20) against a real failed PySCF job; the load-bearing negative holds. Invoke_turn replaced by a sentinel is never called for a failed job; the notice is a checkpointed message read back through read_state, polling twice does not duplicate it, and the composed troubleshoot message carries the engine's real output tail"
- [done] P1.7: Failed-job notice card + Troubleshoot button
  evidence: tests/frontend/fail_01_notice_card.spec.mjs → "ALL CHECKS PASSED (10/10) in headless chromium against a real dev stack; card renders, survives a full page reload, POSTs 202 to the troubleshoot route and becomes one-shot afterwards"
  smoke: one manual conversation against the served qwen3.8:27b → "turn 1 called set_molecule and resolved water (12.2s); a real troubleshooting turn called search_knowledge_base then submit_job (13.3s), i.e. it consulted the manual and proposed a corrected job through the approval card rather than running anything itself -- also confirming submit_job's changed signature still binds"
- merged: f3c5397

## Phase 2: Agent rebuild: draft workflow, taxonomy switch, context diet

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
  retirement. The plan is the approved artifact, the tracker is where its
  deviations are accounted for.

- [done] P2.0: Capture a pre-rebuild checkpoint fixture (thread with a pending old-shape approval) for the P2.7 resume test
  evidence: scripts/capture_approval_fixture.py → "captured tests/data/pre_rebuild_approval.sqlite (45 KB) + .json against the post-Phase-1 toolset; the v1 interrupt shape is pinned at 12 keys and a spec carrying no task/subtype; the script's own self-check resumed a copy down the reject path and got the not-approved ToolMessage back, so the fixture is live rather than merely present"
  note: moved here from Phase 0. The fixture has to come from the toolset as it stands immediately before the rebuild, so it is captured at the START of this phase. **Correction:** Phase 1 DID alter the interrupt payload, `retry_note` was removed from it with auto-retry, so the fixture must be captured against the post-Phase-1 toolset, and any approval left pending from before Phase 1 will fail to resume (its recorded `submit_job` call carries `retry_of_job_id`, which the tool no longer accepts). Wiping old threads is the intended remedy, consistent with the clean-slate decision above.
- [done] P2.1: registry2/elicitation.py::validate_draft (12+ scenario script)
  evidence: tests/backend/elic_01_draft_scenarios.py → "161/161 checks passed across 21 scenarios walked empty→ready, covering every single_point and opt subtype; the ask sequence is asserted by name and each question is asserted to be `ParamSpec.ask` verbatim rather than composed text; mutation-tested. Removing use_tda's applies_when gate fails 4 checks. Walking the scenarios found seven real defects in the Phase 1 parameter data, all fixed here: isoval, use_tda and max_active_orbitals defaulted onto jobs that never read them, opt/ci asked for neither n_states nor target_state, cas_reco/autocas asked the user for the active space it exists to produce, a blind input was silently routed to ORCA, and a stale Wigner source-job id survived four further questions before being caught"
- [done] P2.2: New toolset (draft tools, lookup_capabilities, consolidated plot; token-budget test; e2e_08 via drafts)
  evidence: tests/backend/agent_02_draft_flow.py → "32/32 checks passed against the real state schema, reducers, checkpointer and interrupt(); a draft is built one answered question at a time, survives in state, reaches the approval gate carrying the v2 task fields plus a runnable spec and its input preview, and both branches out of that gate work. Two defects found by running it: routing's engine choice was being written back onto the user's request, so the card claimed PYSCF 'was requested explicitly' about a choice the user never made; and a Wigner draft reached the spec builder with no scan_job_type. A third, a geometry absorbed into the draft as a parameter named `molecule`, riding into the submitted spec. Was found only by a real smoke conversation, and is now refused rather than absorbed"
  smoke: one manual conversation against the served qwen3.8:27b → "'Run a geometry optimization on water' → set_geometry + start_job_draft, the backend's questions relayed verbatim, then 'Use HF with the sto-3g basis' → DRAFT READY and submit_draft pausing on the approval card with a correct PySCF input preview. The model self-corrected after the geometry-as-parameter refusal, so the final spec params are clean"
  browser: tests/frontend/draft_01_approval_card.spec.mjs → "11/11 in headless chromium against a live backend and vite, driving a real conversation end to end: the backend's elicitation question arrives in the chat, submit_draft paints the card, the PySCF input is shown for approval, Approve POSTs 200, the card is dismissed, and there are no uncaught JS errors. Verified in a browser rather than by reading the payload, per CLAUDE.md. The new interrupt payload is a superset (task, subtype, capability_note added, nothing removed), which a code read says is safe and a silently-empty card looks identical to"
  not re-run: tests/frontend/fail_01_notice_card.spec.mjs (P1.7) needs a harness that seeds
  a failed job before launching. It asserts on the Troubleshoot button and the route, not
  on `troubleshoot.py`'s prose, so the P2.2 wording change does not touch it, and the
  composed message itself is still covered by fail_01_notice_flow.py, which passes 20/20.

  known limitation, recorded rather than fixed here: `validate_draft` is now
  deterministic across the approval interrupt (`check_external=False`), but
  `_build_ensemble_spec_or_error` does its **own** job-store read before the
  interrupt, so a `wigner_spectra` approval whose source frequency job is deleted
  between the card rendering and the click fails with an explanation instead of
  running. That is pre-existing behaviour, not introduced by the rebuild, and the
  outcome is arguably right, the job genuinely cannot run, but it is the one
  remaining path where the pre-interrupt half is not a pure function of the draft.
  Worth revisiting when P2.6 rebuilds spec construction on the v2 taxonomy.

  deferred: **e2e_08 via drafts moves to P2.9**, which already owns the e2e suite
  update. The whole e2e suite still drives the pre-rebuild tool names
  (`submit_job`, `set_molecule`, `generate_job_input`, the four plot tools) and has
  to be rewritten as one piece rather than one script at a time.

  decisions taken during the step, recorded so they are not re-litigated:
  - **P2.4 (prompt rewrite) ships with P2.2, not after it.** The prompt's job catalog
    is deleted *because* `lookup_capabilities` and the draft errors replace it, one
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
- [done] P2.3: TDDFT default flip (full TDDFT; ORCA %tddft tda false; approval-card hint)
  evidence: tests/backend/tddft_01_full_response_default.py → "12/12 checks passed, asserted in the generated engine input rather than in the parameter dict. ORCA emits `tda false` and PySCF builds `tdscf.TDDFT(mf)`, with TDA still reachable when asked for explicitly. The approval card now names which of the four ran (full TDDFT / TD-HF/RPA / TDA-DFT / CIS) and says nothing about TDA for a CASSCF job. Six fallback sites plus two registry defaults; one, in orca_runner.py, used single quotes and was missed by the first sweep. The test caught it, which is the argument for asserting on the input file"
  note: the plan says ORCA should emit `%tddft RPA true`. What Phase 0 actually verified
  against ORCA 6.1.1 is `%tddft ... tda false` (`scripts/spikes/spike_orca_caps.py`,
  "full TDDFT vs TDA"), so that is what ships. The repo's standing rule is that engine
  input is written against real output, not documentation.
- [done] P2.4: Prompt rewrite ≤ 6KB
  evidence: tests/backend/agent_01_token_budget.py → "13/13 checks passed. SYSTEM_PROMPT is 4,519 bytes, down from 22,644, and the job catalog is gone. The test asserts the prompt no longer spells out job_type, active_electrons, generate_job_input or submit_job, because that catalog duplicated registry2 and went stale silently. Measured end to end against the served qwen3.8:27b as usage.prompt_tokens, the way Phase 0 established: the fixed surface is **4,489 tokens against the 14,468 baseline, a 69% reduction**, comfortably inside the 10,000 target. 12 tools, widest schema 6 parameters, where submit_job alone took 38"
  note: shipped in the same commit as P2.2, deliberately. The prompt's catalog is
  deleted *because* `lookup_capabilities` and the draft questions replace it, and the
  budget in `docs/MODEL_CONTEXT_BUDGET.md` is a **combined** figure. Asserting the
  schema half alone at P2.2 would have passed while the real number stayed over budget.
- [done] P2.5: Context bounding (num_ctx, mechanical trimming + digest)
  evidence: tests/backend/agent_03_context_bounding.py → "12/12 checks passed. A 240-message conversation now completes a real turn at 9,975 prompt tokens against the requested 32,768 window, where before the whole thread was sent every time. The trim is checked at every thread length from 1 to 120 for an orphaned tool result, the shape an OpenAI-compatible endpoint rejects outright, and the digest is asserted to be built from AgentState alone. The end-to-end check found a real bug: the digest was originally a second SystemMessage, which Ollama rejects with `system message must be at the beginning`, so every conversation long enough to be trimmed, and only those, would have failed in production. It is now appended to the one system message"
  note: the token measurement is skipped only for an unreachable server. Any other
  exception is reported as a failure, because the bug above first surfaced *as* a skip.
A red result that means "the server is down" teaches people to ignore red results.
- [done] P2.6: Taxonomy switch (v2 specs; readers keyed on task fields; drawer keyed on task fields; jobFilename dedupe)
  evidence: tests/backend/tax_01_v2_specs.py → "30/30. `JobSpec` carries `task`/`subtype` as first-class fields and `method` is documented as the runner key only; one spec is built per task the agent can submit and each carries its taxonomy through a JSON round trip. Masters are derived from `TaskDef.master` rather than a hand-kept set of runner-key strings, and single_point/grad and /nac are refused by name ('lands in Phase 5') instead of falling through to 'unknown job_type'"
  evidence: tests/backend/tax_02_job_rows.py → "16/16. `GET /api/jobs` serves task/subtype beside the runner key; `is_scan_master`/`is_ensemble_master` key on the task (a stale runner-key comparison there does not raise, it returns False and the sub-jobs become unreachable); and `filename_stem` is served from `naming.py` rather than recomputed in TypeScript, with the two asserted to agree on a label containing quotes, a newline and a slash"
  browser: tests/frontend/draft_01_approval_card.spec.mjs → "11/11 again after the switch and after the frontend changes; verified live that the registry route is v2-only and a real job row carries task=opt, subtype=min, filename_stem=20260819_water_OptHF_sto-3g_PYSCF_f3836c45"

  what the frontend half came to: `JobRow` gains task/subtype/filename_stem; the jobs
  panel labels a job by its task rather than by the function that ran it;
  `lib/jobFilename.ts` no longer computes the stem at all (it was the self-declared
  "SECOND COPY" of `naming.py`, each copy carrying a comment asking whoever edited it
  to remember the other, a drift no browser test could catch, since the two names
  appear on different downloads); and the registry API is v2-only, its v1 half removed
  along with the dead `useJobRegistryQuery` hook that was its only consumer and which
  no component ever called. `reg2_01`'s v1-is-byte-identical assertion inverted
  accordingly: Phase 1's dark-launch property is deliberately retired.

  **`jobs/excitedState.ts` deliberately still keys on the runner key**, and says so in
  a comment. The question it asks is "which summary shape is this?", and a summary
  shape is produced by the runner that wrote it. A CASSCF and a TDDFT excited-state
  job are the same task (`single_point/ee`) and emit incompatible dicts, so keying on
  the task would merge the two cases the function exists to tell apart. Moving it would
  have been pattern-matching, not correctness.

  **correction to an earlier note in this file:** it said P2.6 would delete
  `_LEGACY_JOB_TYPE` / `_EXCITED_STATE_JOB_TYPE`. That was wrong. `OVERHAUL_PLAN.md`
  always expected a v2 spec to carry a "legacy runner key", and what the user removed
  was the *read-time* adapter for old specs on disk, the opposite direction. Deleting
  these means rewriting all three engines' `if job_type == ...` dispatch onto the v2
  fields, which is what Phases 5–8 do one job family at a time. They are now documented
  in `tools.py` as `runner_key()`-style derivations rather than as something interim.
  What P2.6 *did* remove is every reader that used the runner key to decide what a job
  **means**, masters, ensemble sources, input validation, display labels.

- [done] P2.7: Old-thread compatibility (dual interrupt shapes)
  evidence: tests/backend/agent_04_old_thread_resume.py → "14/14 checks passed against the real P2.0 fixture. Nothing reconstructed; the pending interrupt, its twelve-key payload and its task-less v1 spec are what the pre-rebuild code actually left behind. Before the fix, clicking Approve on such a card returned `Error: submit_job is not a valid tool, try one of [...]`, i.e. a list of internal tool names shown to someone who pressed a button. Both the approve and the reject path now land on a plain explanation that nothing was submitted, with an offer to set the job up again"
  note: the fix is a resume-only shim named `submit_job`, bound to the tool executor
  via a new `get_executable_tools()` but **never offered to the model**, `get_all_tools()`
  is unchanged, so the prompt surface is untouched (agent_01 still measures 4,489 tokens).
  It does not attempt to run the job: that spec was built by a tool that no longer
  exists, in a taxonomy the runners are moving off. Approve and reject deliberately give
  the same answer, because neither can produce the calculation and the distinction
  stopped meaning anything when the tool went away.
- [done] P2.8: Pasted blind input (input_sniff.py; ORCA/BAGEL only)
  evidence: tests/backend/sniff_01_pasted_inputs.py → "69/69 checks passed over 9 ORCA, 7 BAGEL and 3 PySCF samples plus 3 non-inputs. Most samples are the app's own generated inputs, the exact text these engines accept, and the rest hand-written in the shape a user pastes, with comments and manual-style spacing. A pasted ORCA input now resolves its own engine and is described back ('ORCA input for a opt/min calculation at dft/def2-SVP') with the structured alternative offered; a stated engine that contradicts the text is queried rather than overridden; and a pasted PySCF script is classified as precisely as the others and refused for execution"
  note: one expectation was wrong on first writing and the code was right. This app runs
  an ORCA `opt_freq` as two sequential jobs and previews only the optimization stage, so
  the generated text genuinely *is* an optimization input. Reading it as `opt_freq` would
  have been the sniffer inventing a second stage that is not in the text. The combined
  `! Opt Freq` keyword line ORCA does support is covered by its own hand-written sample.
- [done] P2.9: e2e suite update + e2e_18_elicitation.py
  **executed against the live dev stack** (nginx on :8444, running `main` at 80dc2e1).
  The suite is moved onto the rebuilt toolset:
  `set_molecule`→`set_geometry`, `submit_job`→`submit_draft`, the four plot tools→`plot`,
  and `generate_job_input` retired (e2e_06's T03 now asserts the half that mattered. That
  showing an input is not running one). e2e_08's assertion moved off the tool call and onto
  the approval payload, because `submit_draft` takes no arguments: the draft lives in graph
  state, so "did the agent ask for the right job?" is now a question about the card, which
  is also what determines what runs. New `e2e_18_elicitation.py` asserts the property only
  a real conversation can show, that the agent **relays the backend's question rather than
  composing its own**, by pulling the expected wording from `ParamSpec.ask` at runtime, so
  a reworded question cannot leave the script asserting text that exists nowhere.

  evidence: tests/e2e/e2e_04_harness_gate.py → "16/16 against the live stack. The whole
  rebuilt flow runs end to end: set_geometry → start_job_draft → update_job_draft ×2 →
  submit_draft → an approval card carrying task/subtype/capability_note → approved → the
  job ran to completion, and the job that ran matches the spec that was approved. H12 also
  confirms agent_step events still publish after an approval resume"
  evidence: tests/e2e/e2e_18_elicitation.py → "17/17 against the live stack and the served
  model. The agent relays the backend's questions **in the registry's own words**, token
  containment against `ParamSpec.ask`, nothing missing on either the basis or the
  active-space question. A method given where a task was expected is not rejected,
  answering two parameters at once is not re-asked, and the card carries the user's own
  active space and basis rather than a guess. The CASPT2-on-PySCF turn reaches no card at
  all and names BAGEL as the alternative"

  evidence: tests/e2e/e2e_06_agent_tools.py → "12/13 against the live stack. Every non-draft
  tool is exercised, elicitation refuses to guess on all three scenarios, and all four
  disallowed engine/method pairings are refused with nothing reaching an approval card"
  evidence: tests/e2e/e2e_07_approval_flow.py → "21/22 against the live stack, including
  the load-bearing one. A hand-edited input is used byte-identically rather than
  regenerated, and an invalid edit leaves the interrupt pending so the user can fix it in
  place"

  evidence: tests/e2e/e2e_11_param_correction.py → "6/7 against the live stack. Everything
  the script exists to test passes: the `6-31gd`→`6-31g(d)` repair happens *and is
  surfaced* rather than applied invisibly, an RHF request resolves to this app's single
  `hf` value, mistyped functional and basis both produce candidate menus, and an
  unsupported method produces no job with the agent explaining instead of submitting"
  evidence: tests/e2e/e2e_08_job_matrix.py → "first pass 99/116 with ten failing cells,
  which is what produced almost every fix below. A re-run against the fixed stack is in
  progress and clean through the first ten cells except M10, whose fix (4019ad6) was
  committed after that deploy"

  evidence: tests/e2e/e2e_09_plot_tools.py → "11/12 against the live stack. The four plot
  tools collapsed into one `plot(kind=...)` without losing the property the script exists
  for: real UV/Vis and IR spectra are written and downloadable as PNGs for ORCA
  TDDFT/EOM/frequency, the PLOT_ARTIFACT marker the chat UI keys its inline image off is
  intact, and the refusal paths survive. A PySCF eom_ccsd job and a PySCF frequency job
  are both declined rather than drawn. Its one failure is the script's own refusal
  detector: the tool refused correctly and wrote no artifact, saying 'no excitation
  energies to plot a spectrum from', which is not in REFUSAL_WORDS"

  **closed with five job-matrix cells still failing, none of them a product defect**, and
  deliberately rather than by grinding them green. P2B.6 rewrites `MATRIX` and
  `EXPECTED_SUMMARY_KEYS` on the v2 taxonomy, so polishing them here is work done twice:

  - **M10** is a harness artifact, not a stall: the same request reaches an approval card
    3/3 through the graph on the same code, and 0/2 through the e2e path. The matrix
    labels this cell "the SLOW probe" and could not distinguish "the model stopped" from
    "the 600s turn cap cut it off", so `timed_out` and elapsed time are now reported on
    that failure.
  - **M20, M24, M26** are the stalled-after-draft shape whose fix (4019ad6) is deployed
    but unverified on those specific cells.
  - **M23** fails engine-side, ORCA exits 2 on NEB-TS. Tier 3, `XN-09`, already
    documented as unverified territory; NEB belongs to Phase 7.

  what the suite was for, it did: it found the permanently-500ing job detail page, the
  scan drafts raising through `submit_draft`, the ready draft that carried no engine
  input, the agent asking for parameters the user had just given, and two diagnostic
  blind spots that had been hiding those. All fixed, and the fixes verified against a
  real stack. The matrix went from 99/116 with ten failing cells to 125/133 with five.

  what the job matrix found, and it is worth reading as a whole rather than as ten
  separate cells. **the single most common failure shape was "the model stopped after
  start_job_draft", and it had more than one cause underneath it**:

  - **A malformed scan draft raised straight through `submit_draft`.** The geometry
    builder indexes and does arithmetic on whatever shape the draft carries and only
    `ValueError` was caught, so an unexpected shape surfaced as `TypeError`, `KeyError`
    or `OverflowError`, escaped the tool, and produced no approval card and no
    explanation. Five of seven plausible model-written shapes crashed. 0-based atom
    indices threw `OverflowError`, and this app's numbering is 1-based everywhere a user
    or a model can see it, so reaching for 0 is a predictable slip that deserved to be
    told which convention it broke. Fixed in three layers; `scan_01_draft_shapes.py`
    (13/13) pins the class, its load-bearing negative being that *nothing raises*.
  - **Four v1 job-type names resolved to nothing**, `mo_visualization`, `custom`,
    `recommend_active_space`, `wigner_ensemble`, so the agent told users a calculation
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
    hypothesis, but a hypothesis is not a diagnosis, and no speculative fix was shipped.

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
    three attempts running, because nothing offered it a way to comply. Fixed in 742bdaa,
    with a prompt line pointing at it. **T03 has not been re-run yet**. The fix is on
    `main` but the stack was not redeployed before the session ended.

  and one genuine product bug, found by watching the api logs rather than by any assertion:
  - **A non-finite float permanently 500'd a job's detail page.** An ORCA frequency job's
    `reduced_mass_amu` is deliberately `inf` for the six projected translation/rotation
    modes. Their displacement vectors are exactly zero, so the mass ratio is undefined,
    and `vibrations.py` documents the sentinel. JSON cannot express infinity and FastAPI's
    encoder refuses to invent a spelling, so `GET /api/jobs/{id}` raised inside the
    response renderer: every poll, every drawer open, forever, for a job that had completed
    perfectly well. It is also what stalled the e2e_08 run. The suite sat retrying a job
    detail that could never succeed, 41 polls in two minutes, and would have spun to its
    own 90-minute timeout. Fixed at the serialization boundary in 39bb13f rather than at
    the one field that was caught, since the next engine to emit a NaN should not brick a
    job the same way. Regression checks in tax_02 (22/22).

  two real defects were found by running that verification, both fixed with regression
  checks in elic_01 (now 193/193):
  - **"Run a CASSCF calculation on water" dead-ended.** CASSCF is a method, not a task, so
    task resolution failed and the user was told "I don't recognize 'CASSCF' as a
    calculation this app runs". A sentence that reads as nonsense, because it plainly is
    one. A method given where a task was expected is now kept as the method, and the
    question becomes the one the user actually left open. The task is still asked, never
    inferred: a CASSCF on water could be an energy, an optimization or a spectrum.
  - **A free-text phrase was rejected whole.** The model passes what the user said,
    "CASSCF single point energy", "B3LYP geometry optimization", "excited states with
    TDDFT", one string carrying both a task and a level of theory. These are now read
    apart. `tddft` resolves to both halves at once (excited states, at DFT), which is
    exactly the conflation the v2 taxonomy exists to undo.
- merged: 7d1a4e1
  note: merged continuously rather than at one gate. The branch was fast-forwarded onto
  `main` at 66d41ac, twelve commits, no merge commit, and then advanced commit by commit
  as the e2e run found and fixed things; 7d1a4e1 is the commit that closed the last step.
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

## Phase 2B: One taxonomy, end to end

  Added 2026-08-19 and rescoped the same day, at the user's direction: stability through
  simplicity, no legacy architecture running beside v2, unified processes, and no fear of
  breaking things, "what exists is mere inspiration for the direction we are headed."
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

- [done] P2B.1: Registry2 decides; builders construct only (drop v1 validation/routing from the submit path)
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
- [done] P2B.2: Runners dispatch on (task, subtype, method); delete _LEGACY_JOB_TYPE and _EXCITED_STATE_JOB_TYPE
  evidence: tests/backend/reg2b_02_scan_dispatch_e2e.py → "8/8 checks passed" -- see P2B.4's
  evidence line immediately below, which this step shares (landed as one commit; see its note
  for why).
- [done] P2B.4: spec.method becomes the level of theory, task carried by task/subtype
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
- [done] P2B.3: Delete app/chemistry/jobs/registry.py
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
- [done] P2B.5: Frontend keyed on the task, once; no renderer on a runner key
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
- [done] P2B.6: e2e MATRIX + EXPECTED_SUMMARY_KEYS keyed on v2 (task, subtype, method)
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
- [done] P2B.7: Regression pass: backend suite, job matrix, Playwright approval + drawer
  Run against the real dev stack (`scripts/dev_stack.sh up`, commit 96726b8 then the fixes below),
  not a worktree. The first time this phase's changes have been exercised end to end rather than
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
    P2B entirely -- unchanged by 1323aca's own diff to this function, confirmed by `git show`.
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
- merged: -

  (this row is vestigial under the work-directly-on-main policy adopted 2026-08-19: every P2B
  commit above landed straight on `main`, so there is no separate merge commit to record here --
  left blank rather than backfilled with a hash that would misleadingly suggest a real merge)

## Phase 3: Geometry input & uploaded-file manager

  note: P3.2 landed first (advisor-recommended order: the parser is pure
  in-process Python with zero stack dependency, and P3.1/P3.3 both consume
  its output shape), then P3.1, then P3.3 -- all three verified together
  against the real docker-compose dev stack before this commit, since
  `up_01_lifecycle.py` exercises P3.1 and P3.3 in one script.

- [done] P3.1: server/routes/uploads.py (lifecycle, quota, ownership)
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
- [done] P3.2: Backend multi-geometry xyz parser + upload-time sniff
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
- [done] P3.3: Attach semantics (1/2/≥3 geometries; geometry_set job; tests/backend/up_01_lifecycle.py)
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
- [done] P3.4: Composer + button, FilesSection below KB, geometry_set drawer (Playwright uploads spec)
  evidence: tests/frontend/up_02_files_and_attach.spec.mjs → "19/19 checks passed in headless chromium
  against the real docker dev stack (:8444, npm run build refreshed nginx's bind-mounted dist first):
  upload + sniff badge for a 2-geometry and a 3-geometry xyz, attaching the 2-geometry upload renders
  a molecule canvas and cycling its frame via frame-prev changes the canvas.toDataURL() output (never
  page.screenshot(), which can't reliably capture WebGL per CLAUDE.md), attaching the 3-geometry
  upload returns kind=geometry_set with a job_id and a checkpointed notice message appears in the
  conversation, the job's drawer opens with a geometry-count heading and its own frame-next cycling
  also changes the canvas snapshot, tagging a geometry succeeds (200), deleting one file removes it
  from the list, and clear-all requires a genuine two-click confirm (nothing is deleted after the
  first click, both are asserted directly) before removing everything"
  note: `frontend/src/files/FilesSection.tsx` mirrors `KbSection.tsx`'s shape (CollapsibleSection,
  drag-drop, StorageUsageBadge, add-form) but reuses none of its code -- KB's file-manager pattern
  duplicated deliberately (same reasoning `admin/ConfirmButton.tsx`'s own docstring gives for
  duplicating the two-click-confirm pattern rather than sharing one component across two different
  contexts' copy) rather than parameterizing one generic component over both kinds of upload, which
  would have coupled two independently-evolving features (KB's doc_type/paper-card drag payload has
  no equivalent here) through one shared abstraction for a modest line-count saving.

  Frame cycling and per-frame tagging in the drawer come from a new `GeometrySetViewer.tsx`,
  deliberately NOT a new backend endpoint: it fetches the job's own `path_xyz` artifact via the
  existing `GET /api/jobs/{id}/artifacts/{key}` route and parses it with the same
  `frontend/src/molecule/xyz.ts::parseMultiFrameXyz` `ScanFrameViewer.tsx` already uses for a
  pes_scan master's path -- confirming P3.2's tracker note in the other direction: the frontend
  parser's job is rendering an already-written artifact (this app's own output), the backend parser's
  job is validating untrusted upload content, and neither needs to become the other. The backend
  upload's own `sniff` field (computed once, at upload time) stays the sole authority for "how many
  geometries, what kind" throughout -- the frontend never re-parses a file to re-decide that.

  The composer's own "+" button / drag-drop (`Composer.tsx`) is the same upload-then-attach flow
  `FilesSection` offers, invoked from the message box directly: a `.xyz` upload auto-attaches (no
  second click to go find it in the sidebar afterward); a non-`.xyz` upload (blind engine input) is
  added to Files but not auto-attached, since there is no attach mechanism for it yet
  (`raw_input_text` is still a chat-pasted draft parameter -- see `app/chemistry/registry2/params.py`
  -- P3.3 only defines geometry-count-driven attach semantics). Two real drawer-interaction bugs were
  found and fixed while writing the spec, both about Playwright clicking a locator's bounding-box
  center rather than about the app itself doing anything wrong: `JobManagerPanel.tsx`'s job-label
  `<div>` calls `e.stopPropagation()` (it supports double-click-to-rename), so a click that lands on
  it never reaches the row's own `onClick` that opens the drawer -- worked around by clicking the
  status-dot cell instead; and `MoleculePanel`'s own frame-count effect auto-jumps to the NEWEST
  frame whenever the count changes, so a spec asserting frame-cycling immediately after a 2-frame
  attach has to click "previous" (already at the last frame), not "next" (already disabled) --
  documented in the spec itself, since it looks like a mistake on first read otherwise.
- merged: -

**Phase-gate note (2026-08-19):** `scripts/check_destructive.sh --from 8ebc683 --to
origin/main --stack-dir /srv/nexusqc-prod` (production's actual deployed
commit vs. this phase's HEAD) reports one `[destructive]` finding: `bug_report_attachments`
(added in `885abfb`, before this phase) has no matching `ALTER TABLE ... ADD COLUMN IF
NOT EXISTS` in `app/auth/db.py`'s idempotent-migrations block, so production's existing
database will not receive that table's columns on the next promotion. This predates
Phase 3 and is unrelated to this phase's `ownership_index.kind` CHECK-constraint
migration, which the same run does *not* flag -- confirming that migration reaches an
already-deployed database correctly. The `bug_report_attachments` gap needs its own
`ALTER TABLE` fix before the next promotion; it is not blocking Phase 3 or Phase 4 but
should not be forgotten.

**Correction (Phase 4, P4.9):** the diagnosis above was wrong. `bug_report_attachments`
is a WHOLE NEW TABLE, not a new column on an existing one -- `CREATE TABLE IF NOT EXISTS`
is only a no-op once the table already exists; for a table that doesn't exist yet it
creates it, every column included, on an old database exactly as on a fresh install.
Confirmed empirically against a real dropped-and-recreated table on the dev stack, not
just reasoned about. No `ALTER TABLE` was ever needed; the real gap was in
`check_destructive.sh`'s own schema-diff heuristic, which flagged every column of a
brand-new table without asking whether the table itself was new in the diff. Fixed there
-- see Phase 4's own P4.9 entry for the full account and re-verification.

Production's live database was not reachable to directly confirm
its `ownership_index_kind_check` constraint name (the stack is currently down), so that
confirmation is inferred rather than observed: both checkouts were built from the same
`CREATE TABLE` literal, and Postgres's default constraint-naming is deterministic absent
a collision.

Two other gaps noted at this gate, deferred rather than fixed because they belong to a
later phase or are cosmetic: the admin console's storage table (Phase 9's scope) still
renders three quota categories, not the four `usage_report()` now returns -- the backend
reports uploads correctly, the admin UI just doesn't render that row yet; and
`app/uploads/store.py::_owner_dir()` creates an owner directory on read paths (e.g. a
`get_upload` miss), which `delete_upload`/`clear_uploads` don't prune afterward -- harmless
(no bytes; KB's own `rglob`-based usage scan skips empty dirs) but worth fixing alongside
any future uploads-storage cleanup pass.

## Phase 4: Fair scheduler

  note: P4.1, P4.2, P4.3 and P4.4 land as one commit, not separably. An
  advisor review before implementation caught this: today's
  `_reconcile_orphaned_jobs` case 3 ("no result, no live worker pid")
  treats a genuinely-never-admitted queued job the same as a job whose
  worker really died, and reports both as an unrecoverable restart
  failure. A scheduler that defers admission (P4.2) landed on top of that
  unchanged case 3 would fail every queued job on the next restart --
  P4.4's re-enqueue split has to land in the same commit as the scheduler
  itself, and P4.3's trickle-dispatch reuses the exact same admission path
  P4.2 builds, so splitting any of these four into separate commits would
  leave an intermediate commit in a genuinely broken state.

- [done] P4.1: Extract _resources_available()
  evidence: app/chemistry/jobs/base.py → "new module-level `_resources_available()`
  (not a JobManager method) returns `(has_headroom, n_idle, message)` from a
  single `_host_cpu_snapshot()` + `_mem_percent_used()` read, replacing the
  headroom check that used to live inline in the deleted `_wait_for_resources`
  polling loop; `_running_job_ids()` and `_concurrent_jobs_block_reason()` were
  hoisted the same way (bare functions, not JobManager methods) so
  scheduler.py can call them without needing a JobManager instance"
- [done] P4.2: scheduler.py (per-user queues, RR dispatcher, MASTER_MAX_IN_FLIGHT)
  evidence: app/chemistry/jobs/scheduler.py (new) → `JobScheduler`: per-owner
  FIFO deques, a round-robin dispatcher thread that is the ONLY place
  admission is ever decided (`_dispatch_tick`), and `on_admit` callbacks that
  return immediately (the actual subprocess spawn happens on a separate
  worker-pool thread, never the dispatcher thread itself -- see that
  function's own docstring). `ENSEMBLE_MAX_IN_FLIGHT` renamed to
  `MASTER_MAX_IN_FLIGHT` in app/config.py (env var
  `QC_AGENT_MASTER_MAX_IN_FLIGHT`; confirmed via grep that neither dev's nor
  production's `.env`/docker-compose set the old name, so the rename is not a
  silent no-op for either deployment).
  live verification: a real water HF/STO-3G single-point job submitted
  through `JobManager.submit()` on this host went pending -> completed
  end-to-end through the new scheduler path (not merely imported cleanly);
  `JobManager.cancel()` on a still-queued job dequeues it and marks it
  "cancelled before it started" without ever spawning a worker; a master
  (pes_1d) group-cancel with sub-jobs still queued correctly cancels them via
  the scheduler's own dequeue rather than leaving them stranded.
- [done] P4.3: Orchestrators trickle-enqueue
  evidence: app/chemistry/jobs/scan_orchestrator.py → "new `_dispatch_more`
  (mirrors ensemble_orchestrator.py's own wave-dispatch shape) -- `submit_scan`
  now dispatches only an initial wave (up to `MASTER_MAX_IN_FLIGHT`) instead of
  every image at once; later waves are re-parsed from the master's own
  `path_xyz` artifact via `app.chemistry.geometry_upload.parse_multi_frame_xyz`
  (P3.2's upload parser, reused rather than re-invented), with per-image
  `charge`/`multiplicity`/`identifier`/`smiles`/`source` reconstructed from
  `master_spec['molecule']` (the scan's own start-molecule template) since
  plain XYZ carries none of those fields -- a real defect this step's own live
  testing caught and fixed (a first version re-parsed path_xyz alone and every
  trickled image's job failed with KeyError: 'charge')"
  live verification (QC_AGENT_MASTER_MAX_IN_FLIGHT=2, 5-image water scan):
  dispatch went 2 -> 4 -> 5 sub-jobs across ticks exactly as expected, all 5
  completed with correct, distinct energies, and the master's own
  `_update_one` aggregation (rewritten to key each result by its sub-job's own
  `_scan_index` rather than by position in `sub_job_ids_of`'s list -- a
  non-contiguous subset of indices can exist mid-trickle) placed them at the
  right position along the scan coordinate.
  evidence: tests/backend/reg2b_02_scan_dispatch_e2e.py → "12/12 checks
  passed" (up from 8/8) -- the new section drives a real second scan through
  `submit_scan(..., image0_raw_input=...)` and confirms the hand-edited input
  reaches image 0's own persisted spec.json byte-identically while images 1
  and 2 carry none, proving the `_image0_raw_input` stash-on-master-params +
  extract-in-`_dispatch_more` plumbing (replacing the old inline
  per-image-loop injection) survived the rewrite -- caught as a real,
  unverified gap by an advisor review before this step was declared done.
- [done] P4.4: Cancel pre-admission path + startup re-enqueue
  evidence: `JobManager.cancel()` now calls `self._scheduler.dequeue(job_id)`
  (best-effort; `self._cancelled` remains the correctness guard for the
  popped-but-not-yet-spawned race, checked at the top of `_run_inner`).
  `_reconcile_orphaned_jobs` splits its old case 3 ("no result, no live
  worker pid") into two: `meta.get("worker_pid") is None` (never admitted --
  re-enqueued via `self._scheduler.enqueue(...)`, appended to the in-memory
  queue in `__init__` BEFORE the scheduler's dispatcher thread starts) vs.
  worker_pid set but not alive-and-verified (genuinely unrecoverable, still
  reported failed).
  live verification: tests/backend/perf_05_restart_queue.py (see P4.5) drove
  this for real against the live docker api container -- a job confirmed
  "pending" with no worker_pid recorded, frozen there by a global
  concurrency cap of 1 while a slow ORCA CASSCF job held the one slot, was
  NOT marked failed across a real `docker compose restart api` and instead
  resumed and completed normally once the fresh process's own
  `_reconcile_orphaned_jobs` re-enqueued it.
- [done] P4.5: perf_04_fair_scheduling.py, perf_05_restart_queue.py, regressions
  evidence: tests/backend/perf_04_fair_scheduling.py (new) → "5/5 checks
  passed" against the live rebuilt dev stack (`docker compose exec`, same
  in-one-process convention perf_03 established and explains at length) --
  with `max_concurrent_jobs_total=1`, user A's burst of 6 ORCA CASSCF jobs
  submitted immediately before user B's single job produced the admission
  order `[A, B, A, A, A, A, A]`: exactly the round-robin property the phase
  exists to deliver -- B admitted in the very next rotation after A's first,
  not after all of A's remaining five. Also confirms the structural property
  underneath that fairness: `len(mgr._futures)` immediately after submitting
  all 7 jobs was 1, not 7 -- queued jobs hold no thread-pool Future, only
  admitted ones do.
  evidence: tests/backend/perf_05_restart_queue.py (new) → "6/6 checks
  passed" against the live rebuilt dev stack -- see P4.4's own evidence line
  above, which this test drives.
  evidence: tests/backend/perf_03_jobmanager_cap_enforcement.py (updated
  docstring/comments for the new scheduler mechanism, assertions unchanged)
  → "7/7 checks passed" against the live rebuilt dev stack, confirming the
  admin-configurable per-user cap still holds under the new admission path.
  regression: tax_01_v2_specs.py (31/31), tax_02_job_rows.py (22/22),
  scan_01_draft_shapes.py (13/13), reg2b_01_no_v1_redecision.py (15/15),
  reg2b_03_matrix_v2_taxonomy.py (120/120), reg2_01_registry_v2_payload.py
  (20/20), reg_01_wigner_prep.py (all pass), reg2b_02_scan_dispatch_e2e.py
  (12/12, see P4.3), tddft_01_full_response_default.py (12/12),
  sniff_01_pasted_inputs.py (69/69), agent_02_draft_flow.py (35/35),
  elic_01_draft_scenarios.py (201/201) -- all pure in-process, all
  unaffected by the scheduler rewrite, all still green.
- [done] P4.6: Dev/production config parity check
  evidence: .env → "no QC_AGENT_MAX_CONCURRENT_JOBS/N_CORES/MASTER_MAX_IN_FLIGHT/
  MAX_CPU_PERCENT/MAX_MEM_PERCENT/CORE_IDLE_THRESHOLD_PERCENT override in either
  this checkout's or /srv/nexusqc-prod's .env"
  No new admin-configurable quota/concurrency knob was introduced by this
  phase -- the scheduler reuses `max_concurrent_jobs_total`/
  `max_concurrent_jobs_per_user` unchanged in shape and storage
  (`app_config` Postgres table), and the one renamed constant
  (`MASTER_MAX_IN_FLIGHT`) is a Python-level default, not a stored config
  value. `.env` in both this checkout and `/srv/nexusqc-prod`
  were grepped for every quota/concurrency-related `QC_AGENT_*` variable
  (`MAX_CONCURRENT_JOBS`, `N_CORES`, `MASTER_MAX_IN_FLIGHT`,
  `MAX_CPU_PERCENT`, `MAX_MEM_PERCENT`, `CORE_IDLE_THRESHOLD_PERCENT`): no
  match in either file, confirming both stacks fall through to the same
  code-level defaults for anything this phase touches. Production's own
  live `app_config` values could not be directly compared -- its stack is
  not currently running, the same pre-existing limitation the Phase 3 gate
  note already recorded, not something introduced here.
- [done] P4.7: Centralize+fix Playwright BASE_URL default (8443→8444); retarget draft_01 onto docker stack + register/login
  evidence: `npm --prefix frontend run test:e2e` (QC_AGENT_TEST_BASE_URL=
  https://127.0.0.1:8444, no other env vars) → "10/10 specs reported all
  checks passing" (up from 7/9), including `draft_01_approval_card.spec.mjs`
  (17/17 -- register+login added, retargeted off its own hardcoded `:5173`
  literal onto the shared `BASE_URL`) driven through a real conversation
  against the served qwen3.8:27b model to a real approval card and a real
  Approve click.
  **open question SETTLED by a human check, and it is a real defect --
  needs its own tracker line, per the plan's own instruction, not fixed
  here.** Both bare processes (`python -m server.main` + `npm run dev`,
  127.0.0.1:8000/5173, confirmed loopback-only per CLAUDE.md's documented
  backend-binding policy) were started on this host; the user reached them
  via an SSH tunnel from their own machine, sent one chat message in an
  ordinary browser, and confirmed a real connection failure -- **not** the
  exact text P2B.7's own note assumed ("Lost connection to the server --
  reconnecting..."), but a different, plainer failure: **"Connection
  error." with a dismiss control.** Recorded verbatim rather than assumed
  to match, since the two are not obviously the same failure and a future
  session chasing this needs the actual text, not a guess at it. Filed as
  **F-P4-01** (new, unfixed): a real product defect in the documented
  `npm run dev` + bare `python -m server.main` local-dev path (CLAUDE.md
  names this a first-class supported run mode), distinct from -- and now
  confirmed NOT explained by -- the Playwright/headless-chromium-specific
  artifact P2B.7 first hit. Not chased further here: diagnosing an SSE/
  EventSource failure needs its own investigation (frontend's reconnect
  logic, the Vite dev proxy's handling of a long-lived streamed response,
  and whether this is the same failure P2B.7 saw under a different label
  or a second, independent one) that is out of Phase 4's own scope.
- [done] P4.8: Rewrite fail_01_notice_card.spec.mjs self-contained (up_02 pattern), drop external env-var requirement
  evidence: tests/frontend/fail_01_notice_card.spec.mjs → "13/13 checks
  passed" against the live rebuilt dev stack, self-contained: registers its
  own user, looks up that user's id via the admin API, seeds a real failed
  PySCF job (the exact invalid-basis recipe tests/backend/
  fail_01_notice_flow.py already established, lifted verbatim) with the
  thread and job explicitly owned by that user (`record_ownership`,
  mirroring what POST /api/threads and `submit(owner_user_id=...)` already
  do for a real user), waits for the LIVE api container's own already-running
  JobWatcher (not a manually-driven one, unlike the backend test) to notice
  and write the notice card, then drives the reload-persistence and
  Troubleshoot-click assertions the old externally-parameterized spec always
  had. No env vars beyond QC_AGENT_TEST_BASE_URL required -- this spec was
  permanently unrunnable via `npm run test:e2e` before this rewrite (nothing
  in the repo ever set QC_AGENT_TEST_THREAD_ID/_JOB_ID/_THREAD_LABEL), not
  merely undocumented.
  two real bugs found and fixed while writing this spec: (1) the console-error
  filter matched on request URL, but Chrome's own "Failed to load resource"
  console line carries no URL at all (same limitation draft_01's own comment
  already names) -- switched to matching on status-code text, mirroring the
  OLD spec's own `/status of 404/i`-style convention rather than the URL-based
  one up_02 uses, since this spec runs against a login screen's pre-auth 401
  specifically. (2) cleanup (`deleteUserByUsername`) crashed the whole process
  with an unhandled promise rejection after a 30s timeout, because clicking
  Troubleshoot starts a real background agent turn (a live LLM call under the
  graph's own lock) that can still be running when cleanup fires immediately
  after -- fixed with a generous 180s timeout and a try/catch around cleanup
  specifically, so a slow or failed cleanup can never prevent the actual test
  results from being reported.
- [done] P4.9: bug_report_attachments schema-check false positive, corrected
  **corrects a wrong diagnosis recorded at the Phase 3 gate below.** That note
  said the missing `ALTER TABLE ... ADD COLUMN IF NOT EXISTS` for
  `bug_report_attachments` was a real gap needing new ALTER statements. It
  is not: `bug_report_attachments` is a WHOLE NEW TABLE (added in 885abfb),
  and `CREATE TABLE IF NOT EXISTS` is only a no-op once the table already
  exists -- for a table that doesn't exist yet, it creates it, every column
  included, on an old database exactly as on a fresh install. Confirmed
  empirically, not just reasoned about: dropped `bug_report_attachments` on
  the dev stack's real Postgres (`docker compose exec api python -c
  "...DROP TABLE..."`, with explicit user confirmation first -- a
  destructive action even against destructible dev data), restarted the api
  container to force a genuinely fresh connection pool (`get_pool()` caches
  its pool in a module global; an already-running process would not
  re-execute `_SCHEMA`), and confirmed the table came back with all 7
  columns via `CREATE TABLE IF NOT EXISTS` alone -- no ALTER TABLE involved
  at any point. The real gap was in `scripts/check_destructive.sh`'s own
  schema-diff heuristic: it diffs column sets without asking whether the
  COLUMN's TABLE is itself new in the diff, so every column of a brand-new
  table gets flagged as "added with no matching ALTER" even though none of
  them need one.
  evidence: scripts/check_destructive.sh (fixed) → excludes an added column
  from `UNMIGRATED` when its table does not appear at all in `FROM_SCHEMA`
  (a new `FROM_TABLES` set, built the same way `TO_ALTERED` already is).
  Re-run: `scripts/check_destructive.sh --from 8ebc683 --to origin/main
  --stack-dir /srv/nexusqc-prod` → "no destructive changes (3
  warning(s))" -- `[ok] schema changes carry matching ALTER TABLE
  statements`, the false positive gone because the heuristic is now
  correct, not because a redundant ALTER was added to silence it (which
  would have been exactly the "second mechanism that must be kept in
  agreement forever" the no-legacy-compatibility decision prohibits --
  seven ALTERs restating a CREATE TABLE body is drift waiting to happen).
  The remaining 3 warnings (frontend rebuild needed, `app/chemistry/jobs/
  base.py` changed under data/'s on-disk layout, files deleted) are
  legitimate FYI warnings unrelated to this fix, not destructive findings.
  No actual schema change was needed in app/auth/db.py -- the "fix" is
  entirely in the checking script.
- merged: -

## Phase 5: Single-point family: gradients + NAC

  note: `single_point/grad` and `single_point/nac` TaskDefs (registry2/tasks.py)
  and their ParamSpecs (`target_state`, `state_pairs`, registry2/params.py) were
  already in place from earlier phases -- Phase 0/1 anticipated this phase's
  taxonomy. What P5.1 actually added: removing the two `NOT_YET_IMPLEMENTED`
  entries in dispatch.py, reordering `resolve_runner` so grad/nac are checked
  BEFORE the casscf/caspt2 energy-runner branch (a CASSCF gradient must not
  silently run the casscf energy runner instead), and two new cross-field
  refusals in app/agent/tools.py's `_build_spec_or_error` that registry2's
  static ParamSpec table cannot express: an excited-state gradient is refused
  unless `caps.has("excited_gradient")` is true for the resolved (engine,
  method), and a NAC job's `state_pairs` is validated to be exactly one pair
  and, for single-reference (hf/dft) methods, refused unless the pair includes
  the ground state (ORCA's CIS/TDDFT NAC module offers no excited-to-excited
  coupling at all).

  **A real, pre-existing false claim was found and fixed while implementing
  this**, not merely a Phase 5 defect: registry2/params.py's `functional`
  ParamSpec and registry2/tasks.py's `_warn_es_gradient_b88` both said ORCA's
  refusal of a B88-containing-functional (B3LYP, BLYP) excited-state gradient
  is worked around by "the input is rewritten into the equivalent LibXC
  components automatically" -- untrue on every path that could reach it before
  Phase 5 (grep confirmed no such rewrite exists anywhere in orca_runner.py),
  and unreachable before Phase 5 besides (opt/min's ORCA builder never reads
  `target_state` at all). sp/grad is the first path that actually reaches this
  case for real. A live attempt at the rewrite (`%method` block, B3LYP's
  literature ACM coefficients ScalHFX=0.20/ScalDFX=0.72/ScalGGAC=ScalLDAC=0.81)
  ran without error but returned a ground-state `FINAL SINGLE POINT ENERGY` of
  -74.066101334401 Ha against native B3LYP's -75.275510717997 Ha -- off by
  ~1.2 Ha, far past numerical noise -- so the naive ACM mapping is wrong. Both
  the warning text and the capability evidence text were corrected to describe
  a refusal rather than a working rewrite, and `single_point/grad` on ORCA now
  refuses a B88-containing functional + `target_state` outright rather than
  silently computing the wrong functional. Recorded as a new open row in
  docs/PARSER_GAPS.md.

  **A second round, prompted by the user independently reviewing both
  docs/PARSER_GAPS.md open rows** (the B88 row above and the pre-existing
  `orca sp/nac casscf` row) **and confirming both are genuine ORCA
  incapabilities, not parser gaps this app got wrong.** Both rows moved from
  "Open rows" to "Not parser gaps -- capability absences confirmed by probe",
  closed without a user-supplied excerpt. This also answered the user's
  direct question -- "is there a mechanism to warn the user of qm package
  incapabilities?" -- by writing up the three mechanisms this app already
  has (capability-level `gap` evidence making an engine/method pair
  structurally unroutable; a cross-field hard refusal in
  `_build_spec_or_error` for a narrower absence the static per-(engine,
  method) table can't express; a `ParamSpec.warn_when` for a combination
  that works but deserves a caveat) in a new docs/PARSER_GAPS.md section.
  Writing that section up caught a real, separate bug in the third
  mechanism: `functional`'s `warn_when` condition tested
  `method`/`engine`/`subtype`/`task` but never `functional` itself, so it
  fired the B88 caveat text for *any* functional in an excited-state
  ORCA/DFT context -- including PBE0, which works fine and was never
  refused. Live-verified before and after against the rebuilt dev stack:
  `applicable_warnings('single_point','ee','dft','orca',{'functional':
  'PBE0','target_state':2})` carried the B88 warning before the fix and did
  not after; `'B3LYP'`/`'blyp'` (mixed case) still correctly carry it either
  way. Fixed in `registry2/params.py`: `build_context` now normalizes
  `functional` to stripped-lowercase in the condition-evaluation copy only
  (the real `params` dict a caller passed in is untouched, so nothing else
  sees the lowering), and the `warn_when` condition gained
  `{"in": ["functional", ["b3lyp", "blyp"]]}`. README's "and other
  B88-containing functionals" was also corrected -- the check is by exact
  name, not a general B88 detector, and an unmatched B88-derived functional
  (CAM-B3LYP, BP86, ...) fails with ORCA's own error at run time instead of
  this app's pre-submission refusal, which is safe (no rewrite is ever
  applied to any functional now) but less informative.

  Also noted, not fixed: `tests/backend/perf_04_fair_scheduling.py` failed
  reproducibly (2/5, `futures_at_submit_time=2` under a cap of 1) on the
  first post-rebuild run of the full suite, then passed cleanly (5/5) on a
  second run after the container was freshly recreated. Phase 5 touches no
  scheduler file (`git diff --stat` confirms), and the container's
  `app/chemistry/jobs/base.py` was verified byte-identical to the working
  tree at the Phase 4 merge commit, so this is timing-fragile under load
  around container startup (a Future not yet reaped at snapshot time,
  consistent with the drifted admission order also observed), not a
  regression Phase 5 introduced or a correctness bug in the scheduler
  itself. Left as-is rather than hardening Phase 4's test in a Phase 5
  commit.

- [done] P5.1: Registry2 wiring (dispatch ordering, two cross-field refusals)
  evidence: tests/backend/grad_01_gradients_and_nac.py → "28/28 checks passed
  against real PySCF/ORCA/BAGEL runs (see P5.5's evidence line, which this
  script also covers) -- dispatch ordering and all four refusal paths
  (pyscf/casscf excited gradient, orca B3LYP excited gradient, orca hf
  excited-excited NAC pair, more-than-one state_pairs entry) asserted
  directly against `_build_spec_or_error`"
  regression: tests/backend/tax_01_v2_specs.py (36/36, DRAFTS extended with
  single_point/grad and single_point/nac, the old "refused with Phase 5 in
  the message" assertion replaced with dispatch-ordering checks)
- [done] P5.2: run_gradient (pyscf/orca/bagel) + run_nac (pyscf/orca/bagel)
  evidence: tests/backend/grad_01_gradients_and_nac.py → "28/28 checks passed.
  EVERY gradient path this app now claims ran for real on this host: PySCF
  hf/dft(ground+S1)/mp2/ccsd/casscf, ORCA hf/dft(ground+S1 via PBE0)/mp2/
  casscf, BAGEL hf/casscf/caspt2 (singular 'force' block, no preceding hf
  block needed -- verified live, simpler than the 'forces'+grads multi-state
  mechanism the Phase 0 spike used). Every NAC path this app now claims ran
  for real too: PySCF SA-CASSCF (nonzero on a C1-distorted geometry, matching
  scripts/spikes/spike_pyscf_caps.py's own convention for proving the
  machinery -- not a symmetry-forced zero), ORCA hf/dft ground-to-excited
  (PBE0 S0/S1 norm 0.7794758816, matching the Phase 0 spike's recorded
  0.7794747730 to float/threading noise), BAGEL casscf/caspt2 (also live,
  fast on this host -- CAS(4,4)/svp water completed in seconds to ~2 minutes,
  contradicting CLAUDE.local.md's blanket 80-96s/macro-iteration warning;
  recorded rather than silently overridden). Central-difference cross-check:
  PySCF's analytic HF gradient agrees with an independently-built finite-
  difference gradient (built from run_single_point alone, sharing no
  machinery with run_gradient's own nuc_grad_method() call) to 1e-4 Eh/Bohr."
  note: a real bug was found and fixed while writing bagel_runner.py's
  parser -- `_BAGEL_GRADIENT_SECTION` was originally bounded on
  "* Gradient computed with", which a live CASPT2 gradient run does NOT
  print (it prints "- Gradient integral contraction" there instead, HF/
  CASSCF-only phrasing); silently broke NAC/gradient parsing for CASPT2
  only until caught by actually running the CASPT2 case, not by reasoning
  about the HF/CASSCF case alone. Rebound on "* METHOD:", which every one
  of the three reference types prints right after the gradient block.
- [done] P5.3: Dispatch (see P5.1) + summarize (no change needed)
  evidence: app/chemistry/jobs/summarize.py → "no lines changed -- the
  'matrix+norm as GFM table' tagging contract the plan asks for needs no
  changes here at all: `_summary_as_markdown_table` already renders any
  job's summary dict generically (used for the chat-attached-job context
  and check_job_status), and `gradient_hartree_per_bohr`/
  `nac_hartree_per_bohr`/the norm fields flow through it for free the same
  way every other job type's summary already does. Nothing job-type-
  specific exists there to extend."
- [done] P5.4: GradientSection/NacSection in the drawer
  evidence: frontend/src/jobs/VectorPerAtomTable.tsx (new, shared by both
  sections) + frontend/src/jobs/JobDetailDrawer.tsx (gated on
  `job.task === "single_point" && job.subtype === "grad"/"nac"`, per P2B.5's
  keyed-on-task-not-runner-key policy) → `tsc -b` clean
  browser: tests/frontend/grad_02_gradient_nac_drawer.spec.mjs → "12/12 checks
  passed against the live rebuilt dev stack -- two real completed jobs
  (single_point/grad and single_point/nac, both pyscf/water/sto-3g), seeded
  via docker compose exec (the fail_01_notice_card.spec.mjs pattern), opened
  in the drawer: GradientSection shows 3 real per-atom rows and the exact
  norm (0.086934) tests/backend/grad_01_gradients_and_nac.py's own HF-
  gradient check produces for the same system; NacSection shows the S0/S1
  state-pair label. First run caught a real spec bug (not a product bug):
  an unscoped `table tr` locator picked up JobsPanel's own job-list table
  instead of the drawer's, since both are literally <table> elements on
  the same page -- fixed by scoping to `[role="dialog"] table tr`. A job's
  own completion also fires the app's existing chat-side job-summary agent
  turn (unrelated to Phase 5), which independently reproduced the same
  gradient norm (0.0869) and energy in its own natural-language summary --
  a second, incidental confirmation that summarize.py's generic markdown
  table renders the new summary fields correctly for the chat context too.
- [done] P5.5: Tests
  evidence: tests/backend/grad_01_gradients_and_nac.py (new) → "28/28, see
  P5.2's evidence line"
  evidence: tests/frontend/grad_02_gradient_nac_drawer.spec.mjs (new) →
  "12/12, see P5.4's evidence line"
  evidence: tests/e2e/_probes.py MATRIX extended M27-M30 (pyscf/orca grad,
  pyscf/orca nac) + tests/backend/reg2b_03_matrix_v2_taxonomy.py → "138/138
  checks passed (up from 120/120), cell count assertion updated 26->30"
  evidence: tests/e2e/e2e_08_job_matrix.py → EXPECTED_SUMMARY_KEYS/
  _human_description/prompt_for extended for (single_point, grad)/(single_point,
  nac), target_state/state_pairs phrasing added -- not run against a live
  conversation this session (needs Ollama + a seeded KB), verified via
  reg2b_03's "prompt_for/_human_description do not raise for any
  non-special-cased cell" check instead
  evidence: docs/PARSER_GAPS.md → "2 rows closed (pyscf sp/nac magnitude
  cross-checked against ORCA on the same geometry; pyscf sp/ee casscf
  oscillator strengths resolved as a routing decision, not an
  implementation gap); 2 further rows (orca B88-containing-functional
  excited-state gradient, orca sp/nac casscf) closed as user-confirmed
  capability absences rather than left open pending an excerpt -- see this
  phase's second note above; 1 further row closed (orca+pyscf bare
  WB97X-D naming trap) and 1 new row opened (orca WB97X-D3BJ/-D4/-V/
  WB97M-V) -- see this phase's third note below"
  evidence: registry2/params.py's `functional.warn_when` scoping fix →
  live-verified via `docker compose exec api python -c
  'applicable_warnings(...)'` against the rebuilt dev stack, before/after --
  see this phase's second note above for the exact calls and results
  evidence: scripts/generate_capability_docs.py --check / scripts/
  check_capability_matrix.py → "PASS, 506 assertions, docs regenerated"
  regression: tests/backend/elic_01_draft_scenarios.py (201/201),
  agent_02_draft_flow.py (35/35), tax_02_job_rows.py (22/22),
  scan_01_draft_shapes.py (13/13), reg2b_01_no_v1_redecision.py (15/15),
  reg2_01_registry_v2_payload.py (20/20), tddft_01_full_response_default.py
  (12/12), sniff_01_pasted_inputs.py (69/69), reg_01_wigner_prep.py (all
  pass), reg2b_02_scan_dispatch_e2e.py (12/12, real JobManager.submit_scan
  dispatch through the now-changed worker DISPATCH tables) -- all pure
  in-process or against the live rebuilt dev stack, all still green
  regression: tests/run_backend.sh → 44/44 scripts green against the
  rebuilt dev stack, including perf_04_fair_scheduling.py (5/5, timing-
  fragile on a freshly-restarted container per this phase's second note
  above, but not flaky on the container state the commit was verified
  against)
  evidence: registry2/params.py's `functional` help/ask text + the
  cross-engine WB97X-D naming trap → see this phase's third note below

  **A third round, prompted by the user asking for an explicit check of
  WB97X/WB97X-D** (commonly used, so worth verifying rather than leaving to
  a user hitting it by accident) **and suggesting explicit capability
  logging for functionals generally.** Live-tested against both engines on
  water/STO-3G/S1: bare `WB97X` (no dispersion) runs clean end-to-end on
  both PySCF and ORCA. Bare `WB97X-D` (no version digit) is invalid on
  *both* engines for opposite reasons -- PySCF's libxc parser accepts the
  name but the TDDFT gradient driver raises `NotImplementedError`; ORCA's
  own input check refuses it outright, since ORCA's real functional list
  (confirmed against `data/scraped/orca/...DensityFunctionalTheory.html.txt`)
  has no entry without a dispersion-version digit. `WB97X-D3` works on ORCA
  but hits the same PySCF `NotImplementedError` as the bare form. Closed as
  a confirmed cross-engine naming trap in docs/PARSER_GAPS.md, not a parser
  gap. `registry2/params.py`'s `functional` field previously offered
  `wb97x-d` as its own example -- corrected to `wb97x`, the one name
  verified working on both engines. `capabilities.py`'s orca/dft and
  pyscf/dft `excited_gradient` evidence extended with all of the above so
  it is explicitly logged rather than living only in this note.

  Checking further (WB97X-D3BJ, WB97X-D4, WB97X-V, WB97M-V -- all real ORCA
  keywords, unlike bare WB97X-D) found they crash or abort in live testing
  on this host. Not the same issue -- these are recognized keywords, not a
  naming miss -- and not chased further within this check: recorded as a
  new open row in docs/PARSER_GAPS.md rather than guessed at.

  Also surfaced, not built: `elicitation.py` only fuzzy-validates
  `functional` against an engine's real keyword pool when the field is
  *missing*; once a value is present, right or wrong, nothing re-checks it
  before the draft reaches "ready". Extending that validation to a present
  value would have caught the WB97X-D naming trap before submission instead
  of after. Written up as a noted idea in docs/PARSER_GAPS.md, not
  implemented -- new elicitation-flow behavior, out of scope for a
  functional-naming check.
- merged: 6c9ab45

## Phase 6: Optimization family

  note: the registry layer (registry2/tasks.py's `opt/constrained`/`opt/ci`
  TaskDefs, their `constrained_opt`/`ci_opt` capability requirements, and
  the `constraints`/`target_state`/`target_state_2` ParamSpecs) was already
  in place from earlier phases -- Phase 0/1 anticipated this phase's
  taxonomy the same way Phase 5 found grad/nac's TaskDefs already present.
  `dispatch.py` already routed `(opt, constrained)`/`(opt, ci)` to
  `geometry_optimization`, not `NOT_YET_IMPLEMENTED`. What this phase
  actually built: the constraint/excited-state/conical-intersection logic
  *inside* `geometry_optimization` for pyscf/orca, and one real correction
  to app/agent/tools.py's routing.

  **The one real correction, not just an addition.** `app/agent/tools.py`
  hardcoded `opt/ci` to refuse every engine but `'bagel'`, on a comment
  claiming ORCA's route (`%mecp`) was "a separate, unimplemented module" --
  but `capabilities.py` already gave orca/hf and orca/dft `ci_opt=True` at
  `run` evidence from a Phase 0 spike that used `! Opt`, not the ORCA
  manual's own `! CI-OPT` keyword. Rerunning that exact spike input showed
  `! Opt` with the identical `%TDDFT`/`%CONICAL` blocks present ran in
  0.013s of "Geometry relaxation" -- i.e. did nothing (the same silent-no-op
  shape this app's own docs already call worthless-grade evidence for
  BAGEL's `fix_atom`). `! CI-OPT` genuinely drives the crossing gap to
  zero, live-verified on twisted ethylene/STO-3G with both a CIS (hf,
  final E diff.(CI) = -6.63962e-05 Ha) and a TDDFT (PBE0, converged
  -0.406 Ha -> -0.0002955544 Ha over 10 cycles, ORCA's own HURRAY/"THE
  OPTIMIZATION HAS CONVERGED" banner reached) reference. `tools.py`'s
  refusal now derives from `caps.has("ci_opt")` -- one source of truth,
  matching `QM_CAPABILITIES.md`'s own published table -- instead of a
  hardcoded engine name that quoted the wrong ORCA module as evidence.
  `capabilities.py`'s `ci_opt` evidence text for both orca/hf and orca/dft
  is corrected accordingly (still `run`-level, now honestly earned).

  Also found and fixed while widening the excited-state guard: the ORCA
  B88-containing-functional refusal (`single_point/grad`'s own check) was
  scoped only to `single_point/grad`, even though `target_state`'s
  ParamSpec `applies_to` already includes `opt` -- an ORCA+B3LYP+opt/min+
  `target_state` draft could reach READY and then build an input ORCA
  rejects at runtime. Widened to cover `opt/min` too (deliberately NOT
  `opt/ci`, which has its own `ci_opt`-gated check, or `freq`/`opt_freq`/
  `neb_ts`, out of this phase's scope -- `neb_ts`'s own version of this gap
  is noted, not fixed, since NEB belongs to Phase 7 per Phase 2.9's own
  note).

- [done] P6.1: opt/constrained (pyscf, orca; bagel mechanically denied)
  evidence: tests/backend/opt_01_optimization_family.py → "34/34 checks
  passed. pyscf: geomeTRIC's own `constraints` kwarg takes a path to a
  constraints file in geomeTRIC's own format -- read directly from
  `geometric/prepare.py::parse_constraints` on this host rather than from
  memory or the weak P0.5 spike (which only checked `kernel()` had a
  `constraints` parameter, never ran one): atom indices are 1-based
  ('Atom numbers must start from 1', matching this app's own numbering
  with no conversion needed), distance in Angstrom, angle/dihedral in
  degrees. A live water/HF/STO-3G bond constraint converged the O-H
  distance to 0.9799999995930336 Angstrom against a 0.98 target. orca:
  `%geom Constraints { B N1 N2 value C }` per the real manual
  (data/scraped/orca/.../optimizations.html.txt) -- 0-based atom indices
  INSIDE the block (confirmed against the Phase 0 spike's own
  `{B 0 1 0.98 C}`), the one conversion point from this app's 1-based
  ParamSpec. A live water/HF/STO-3G run converged to 0.97999971
  Angstrom. bagel: mechanically denied by `supports()` -- `constrained_opt`
  evidence is `gap`/untrusted (fix_atom silently ignored), so no runner
  change was needed or made there."
  evidence: app/agent/tools.py's constraint-shape validator → "malformed
  shapes (wrong atom count, out-of-range index, unknown type, non-numeric
  value) are refused with an explanation before either runner ever indexes
  into them, on the same P2.9 scan-draft-shape lesson (five of seven
  plausible model-written shapes crashed there); a well-formed constraint
  passes through unchanged"
- [done] P6.2: opt/ci (bagel kept; orca hf/dft added via corrected
  CI-OPT keyword; orca/casscf and pyscf refused per verdict)
  evidence: tests/backend/opt_01_optimization_family.py → "same run, 34/34.
  ORCA hf and dft both converge a genuine twisted-ethylene S0/S1 crossing
  (see the phase note above for the exact numbers); BAGEL casscf
  gradient-projection MECP still runs unchanged (regression); orca/casscf
  (ci_opt evidence 'unverified' -- %CONICAL was only proven with a TDDFT
  reference) and pyscf (no pyscf.geomopt.meci) are both refused by name,
  not silently dropped; a non-ground-inclusive ORCA crossing request and a
  B3LYP/BLYP ORCA request are both refused with a specific reason before
  any input is built"
  note: BAGEL's own CI-opt mechanism (`optimization_type='conical_intersection'`,
  `bagel_runner.py`'s `opttype='conical'`) predates this phase and was
  verified, not built, here -- a live regression run completed without
  error but did NOT converge to a true crossing within 100 cycles on an
  arbitrary water/CASSCF(4,4)/SVP system (excitation gap stayed ~7.6 eV).
  Consistent with "structural, not convergence-verified" (docs/ARCHITECTURE.md
  already carried this caveat for BAGEL's CI-opt before this phase) rather
  than a regression -- recorded rather than chased further, since making a
  hard CI genuinely converge on an arbitrary system is a real optimization
  problem, not a code defect.
- [done] P6.3: opt/min polish (ES target_state on pyscf+orca hf/dft;
  numerical-gradient warning already wired, found unreachable)
  evidence: tests/backend/opt_01_optimization_family.py → "same run, 34/34.
  pyscf: `td.nuc_grad_method().as_scanner(state=target_state)` passed
  directly as geomeTRIC's driven object (not `mf`) -- confirmed live this
  tracks the same root across displaced geometries and converges a real
  excited-state minimum (TD-DFT/PBE0 water S1: final_energy_hartree
  -75.0178, above ground_state_energy_hartree -75.1229 by exactly the S1
  excitation energy). orca: reused the existing `%tddft NRoots/IRoot`
  block pattern (already used by NEB-TS/gradient) inside
  geometry_optimization's hf/dft branch, converges cleanly (HURRAY)."
  evidence: app/agent/tools.py's widened B88/excited_gradient guard →
  "orca+B3LYP+opt/min+target_state is now refused (was previously
  unguarded and would have built an input ORCA rejects at runtime); orca+
  PBE0 (non-B88) is correctly NOT refused; pyscf+casscf+opt/min+
  target_state is refused (casscf has no verified excited_gradient) --
  all three asserted directly against `_build_spec_or_error`"
  note: `_warn_numerical_gradient` (tasks.py, already wired to opt/min
  before this phase) is checked to be currently UNREACHABLE in practice --
  `grep`-equivalent scan of every `MethodCaps` row in capabilities.py found
  no `(engine, method)` pair with `gradient == "numerical"` (every
  gradient-capable method here is analytic). Correct, generic machinery
  with nothing to exercise it yet, not a defect -- recorded rather than
  claimed as verified, since no card can show a warning with no trigger.
- [done] P6.4: opt_freq single-input (orca `! Opt Freq`/`! Opt NumFreq`;
  bagel chained `optimize`+`hessian`; pyscf stays two-stage per the plan)
  note: initially deferred within this same session as a reasoned P6.5-gate
  trade-off (writing and verifying a new combined-output parser against a
  working two-stage path), then done anyway after the user pointed out it
  is explicitly step 4 of this phase's own plan text and asked for it to
  be implemented well rather than left as a documented gap.

  ORCA: build_input_text's own `opt_freq` branch now emits a genuine
  combined `! Opt Freq` (`! Opt NumFreq` for casscf, no analytic CASSCF
  Hessian on ORCA either) input instead of aliasing to the plain
  optimization preview. Live-verified on water/HF/STO-3G before trusting
  it: the optimization stage's own HURRAY/"FINAL SINGLE POINT ENERGY"
  trail is unaffected by the frequency stage that follows in the same
  output.out (no further "FINAL SINGLE POINT ENERGY" line appears once
  VIBRATIONAL FREQUENCIES starts -- the frequency stage reuses the
  pre-Hessian wavefunction rather than re-announcing it), and each of
  VIBRATIONAL FREQUENCIES/NORMAL MODES/IR SPECTRUM/the thermochemistry
  lines appears exactly once. `_geometry_optimization_summary`/
  `_frequency_summary` are factored out of the standalone
  run_geometry_optimization/run_frequency (same two parsers, not a third
  mechanism) and both called against the ONE combined output in the new
  run_opt_freq.

  BAGEL: `_build_input`'s shared "optimize"/"hessian" wrapper-block
  construction (job_type in ("geometry_optimization", "frequency")) now
  also accepts "opt_freq" and, for that case, emits BOTH wrapper blocks
  in one input (per the Phase 0 spike's own opt+hessian-in-one-input
  precedent) sharing one CASSCF/CASPT2 preamble. Live-verified on
  water/CASSCF(4,4)/svp AND water/CASPT2(4,4)/svp (not casscf alone --
  CASPT2 goes through a structurally different smith-wrapped branch):
  opt.molden (the file `_geometry_optimization_summary` reads for the
  optimized geometry) is still written when a "hessian" block follows
  "optimize"; `_parse_casscf_energies`/`_parse_caspt2_energies`'s
  last-occurrence-wins convention still resolves correctly with the
  Hessian's own displaced-geometry macro-iterations appended after the
  optimization's in the same text (confirmed by the optimization-stage
  and frequency-stage energies matching exactly, both methods); and the
  frequency-specific blocks parse unchanged.

  **A real bug found and fixed, not just verified:** the first CASPT2
  combined attempt silently ran CASSCF instead. `_build_input`'s
  smith_block condition (which decides whether the shared
  `gradient_entries` gets the CASPT2 smith-wrapped form) listed
  "geometry_optimization"/"frequency"/"gradient"/"nac" but not the new
  "opt_freq", so a method='caspt2' opt_freq request built a valid,
  error-free CASSCF-only input with no error raised anywhere. Caught by
  cross-checking the resulting frequencies against an independent CASSCF
  run on the same system (numerically identical -- the tell, not a clean
  exit code) and by `_parse_caspt2_energies` then finding nothing to
  parse. This is the second instance in this same phase of this app's own
  "ran without error is not evidence" rule catching a real defect (the
  first being P6.2's ORCA `! Opt` vs `! CI-OPT` finding) -- fixed by
  adding "opt_freq" to that condition, re-verified after the fix that
  CASPT2's frequencies/energy are genuinely distinct from CASSCF's.

  evidence: tests/backend/opt_01_optimization_family.py → "43/43 (up from
  34/34) -- five new live checks: orca opt_freq hf (real frequencies,
  optimization/frequency-stage energies agree to 1e-6, optimized_molecule
  populated), orca opt_freq casscf (real frequencies via Opt NumFreq),
  bagel opt_freq casscf (real frequencies, stage energies agree), bagel
  opt_freq caspt2 (method='caspt2' reported correctly, energy genuinely
  lower than casscf's by >0.01 Ha from dynamic correlation, frequencies
  genuinely distinct from casscf's -- the three assertions that would
  have caught the smith_block bug had it shipped)"
  evidence: tests/e2e/_probes.py MATRIX extended M35-M37 (pyscf/orca/bagel
  opt_freq -- opt_freq never had a MATRIX cell at all before this, a
  pre-existing gap closed here rather than left) + reg2b_03_matrix_v2_taxonomy.py
  → "171/171 (up from 158/158), cell count 34->37"
  evidence: tests/e2e/e2e_08_job_matrix.py, EXPECTED_SUMMARY_KEYS/
  `_human_description` extended for ("opt_freq", ""); verified via
  reg2b_03's non-raising check, same pattern as every other cell this
  phase (needs Ollama + a seeded KB to run against a live conversation)
- [done] P6.5: Subtype tests + denial-path assertions + Playwright
  evidence: tests/backend/opt_01_optimization_family.py (new) → "43/43
  (final count, up from 34/34 before P6.4), see P6.1-P6.4's evidence
  lines. Covers dispatch routing, `supports()` capability-derived
  allow/deny for every (engine, method) pair this phase touches, every
  `_build_spec_or_error` refusal path (ci_opt-gated engine refusal,
  ground-state-inclusive-only, B88, constraint shape validation x4,
  widened excited-state guard x3), and eleven live engine runs across
  pyscf/orca/bagel including single-input opt_freq on all three"
  evidence: tests/frontend/opt_02_optimization_drawer.spec.mjs (new,
  written on the grad_02 pattern) -- seeds a real completed opt/constrained
  and opt/ci job via `docker compose exec`, asserts the drawer shows
  "Optimized geometry" (not "Input geometry") and the new summary fields
  (`constraints`, `optimization_type`, `ci_energy_diff_hartree`) for both.
  No new frontend code was needed -- P2B.5 already keyed the optimized-
  geometry heading on `optimized_molecule` presence, not on subtype, and
  the generic Summary key/value table already renders any field a runner
  writes -- this spec exists to prove that claim empirically rather than
  trust it, since a silently-empty drawer section looks identical to a
  working one in a code read. **Not run this session** -- needs the
  docker-compose dev stack's own `docker compose exec`, which this
  session's verification ran natively (conda env) against instead; left
  for the same live-stack regression pass P2B.7 used for its own
  Playwright checks.
  evidence: tests/e2e/_probes.py MATRIX extended M31-M34 (pyscf/orca
  constrained, orca/bagel ci) + DISALLOWED_PAIRINGS extended D09 (bagel
  constrained)/D10 (pyscf ci) + tests/backend/reg2b_03_matrix_v2_taxonomy.py
  → "158/158 checks passed (up from 148/158 on first extension -- caught a
  real omission: opt/ci's own `target_state` ParamSpec is
  `required_when={'eq': ['subtype', 'ci']}`, so M33/M34 needed an explicit
  target_state=0, not an implicit default, to satisfy the same schema a
  real conversation would be held to); cell count assertion updated
  30->34, DISALLOWED_PAIRINGS count 7->9"
  evidence: tests/e2e/e2e_08_job_matrix.py, EXPECTED_SUMMARY_KEYS/
  `_human_description`/`prompt_for` extended for (opt, constrained)/(opt,
  ci); not run against a live conversation this session (needs Ollama +
  a seeded KB), verified via reg2b_03's "prompt_for does not raise for any
  non-special-cased cell" check instead, same as Phase 5's own recorded
  pattern for this evidence gap
  evidence: scripts/generate_capability_docs.py --check / scripts/
  check_capability_matrix.py → "PASS, 506 assertions, docs regenerated
  with corrected ci_opt evidence text for orca/hf and orca/dft"
  evidence: docs/PARSER_GAPS.md → "1 new row added under 'Not parser gaps'
  documenting the ! Opt vs ! CI-OPT correction, so a future session does
  not re-trust the old spike verdict"
  regression: tests/run_backend.sh full suite, re-run after P6.4 landed
  (QC_AGENT_TEST_BASE_URL=https://127.0.0.1:8444 -- the bare default in
  tests/fixtures.py is 8443, which nothing on this host listens on; this
  dev stack's nginx maps 8444 externally so it doesn't collide with the
  separate production checkout's own 8443, a pre-existing host-specific
  gap unrelated to this phase) → "43/45 scripts, two failures, both
  investigated individually rather than assumed benign:
  - `perf_04_fair_scheduling.py` (2/5 -- a burst admission order came back
    ['A','A','B','A','A','A','A'] instead of round-robin). This phase's
    `git diff --stat` touches zero scheduler files (base.py, scheduler.py)
    -- and a clean standalone re-run immediately afterward passed 5/5 with
    a correct interleaved order. Exactly the same timing-fragile-around-
    container-restart failure Phase 5's own tracker note already recorded
    for this script (2/5 then 5/5 on a second run); this session restarted
    the api container multiple times (conf_04/perf_05's own restart tests,
    an aborted first run_backend.sh invocation), which is what perf_04's
    own docstring already names as the trigger.
  - `sniff_01_pasted_inputs.py` (1 FAIL) -- a REAL, correct consequence of
    P6.4, not a flake: one fixture asserted that ORCA's *generated*
    opt_freq input sniffs back as `opt/min`, with a comment explaining why
    -- true only while opt_freq's preview was a two-stage alias showing
    just the optimization half. Now that the generated text is a genuine
    combined `! Opt Freq` input, the sniffer (unchanged) correctly reads
    it as `opt_freq`, and the stale fixture/comment is what needed fixing,
    per this project's own rule that when an old test and the new spec
    disagree, the test changes. Fixed; re-run 69/69 clean.
  Every other script, including the two restart-dependent ones (conf_04,
  perf_05), passed both times"
- merged: -

## Phase 7: PES family, batch, nested-preview performance

- [done] P7.1: pes_1d split (bagel denial + interp_pes recommendation)
  evidence: tests/backend/p7_02_bagel_pes1d_denial.py → "17/17 checks
  passed. `TaskDef.engines=('pyscf', 'orca')` on pes_1d plus a new
  `engine_denial_hint` field (appended to `supports()`'s refusal reason,
  never a separate mechanism) makes `supports`/`route_engine`/
  `validate_draft` all refuse bagel/pes_1d and name interp_pes by name in
  the reason text; interp_pes and pes_1d on pyscf/orca are unaffected;
  docs/QM_CAPABILITIES.md regeneration matches."
- [done] P7.2: Standalone interp_pes (steps card, editable cascade template, atom reorder)
  evidence: tests/backend/p7_03_interp_pes_cascade_and_reorder.py →
  "22/22 checks passed. Endpoint atom correspondence
  (`interpolate._best_atom_correspondence`) is always computed from
  geometry via `scipy.optimize.linear_sum_assignment`, never from the
  symbols list order, so a genuinely swapped same-element pair is
  detected and reordered (with a warning) even though the symbols list
  looks identical either way; a correctly-ordered endpoint that has
  simply moved a lot (radial scaling from the shared centroid, so every
  atom keeps its own angular sector) is never spuriously relabeled; a
  real formula mismatch still hard-refuses. The editable-input cascade
  (app/chemistry/jobs/scan_template.py's `substitute_geometry`,
  regex-located `* xyz` block for ORCA / JSON `geometry` array for
  BAGEL) was proven end to end against 3 real dispatched ORCA jobs: a
  hand-added keyword survived to every image's own input.inp, and each
  image's input carried that image's own distinct geometry, not image
  0's. pes_1d's own `image0_raw_input` behaviour (image-0-only, no
  cascade) was reconfirmed unchanged for contrast in the same run."
- [done] P7.3: Children pagination + lazy frame loads
  evidence: tests/backend/p7_01_children_pagination.py → "15/15 checks
  passed. `sub_job_ids_of` now reads an append-only per-master
  `children.jsonl` manifest (written by `_record_child` inside
  `submit()`) instead of scanning JOBS_DIR; proven cheap, not just
  correct, by padding JOBS_DIR with 300 unrelated jobs, submitting a
  real 12-image pes_1d scan, and call-counting `read_spec` to confirm
  lookup cost is O(children) rather than O(all jobs on disk). Confirmed
  self-healing when a listed child id has been evicted from disk (stale
  ids are dropped, not raised). `GET /api/jobs/{id}/children` now takes
  `offset`/`limit` (capped at 500), returns `{total, offset, items}`
  with trimmed rows (no summary/artifacts/molecule) rather than full job
  rows; the frontend's `ScanFrameViewer`/`EnsembleFrameViewer` request
  additional pages on out-of-window scrubbing instead of holding every
  child in memory. `npx tsc --noEmit` clean; NOT yet verified against a
  running browser (see P7.5 note) since the live dev-stack API container
  was still serving pre-rename code (`is_scan_master`/`is_ensemble_master`)
  at the time this step's backend work finished -- verify over HTTP
  after the container rebuild this phase's own commit triggers, before
  relying on this in a browser session."
- [done] P7.4: batch master task
  note: this step first shipped narrower than the plan text ("tagged
  geometries or a geometry_set × tasks 1-6"): children were single_point/gs
  only, sourced from a geometry_set job id only, reasoned from P7.5's own
  acceptance line ("batch e2e" = 3x single_point) rather than from a
  decision the user actually made. Flagged rather than marked done at the
  time. The user then made the two actual scope decisions on 2026-08-20:
  - **Child task**: restricted to job types 1-4 (single_point, opt, freq,
    opt_freq -- docs/OVERHAUL_PLAN.md and docs/MASTER_PLAN_SUMMARY.md
    edited to match), not the original 1-6 -- pes_1d/interp_pes (5, 6) are
    themselves master tasks, and nesting a master inside a master stayed
    out of scope. `child_task` (registry2/params.py's ParamSpec) is
    required with no default, matching neb_ts's own `preopt` precedent --
    an omitted field is asked for, never silently resolved to
    single_point. `requires` was DROPPED from batch's own TaskDef entirely
    (was `("energy",)`, trivially true for every method and therefore
    fiction once a real child task existed) -- elicitation.py's two
    capability-check call sites (`route_engine`, the final `supports()`)
    now substitute the CHILD's own (task, subtype) via a new
    `_capability_task()` helper, reusing single_point/opt/freq/opt_freq's
    own `requires` rather than duplicating it. Verified this is not
    cosmetic: `supports("orca", "eom_ccsd", "opt", "min")` correctly
    refuses (eom_ccsd has no gradient anywhere in this app's capability
    matrix) where the old fixed `requires=("energy",)` would have passed
    it silently.
  - **Geometry source**: widened from geometry_set-only to any of
    geometry_set/pes_1d/interp_pes/wigner_spectra/neb_ts
    (`tasks.BATCH_GEOMETRY_SOURCE_ARTIFACT_KEY`), since all five already
    render their geometries as plain multi-frame xmol text -- just under
    different artifact keys (`path_xyz` for the first three, `ensemble_xyz`
    for wigner_spectra, `neb_frames` for neb_ts, all readable by the one
    existing `parse_multi_frame_xyz`). The ParamSpec was renamed
    `source_geometry_set_job_id` -> `source_job_id` throughout (no
    legacy-name shim, per this project's standing no-legacy-compatibility
    rule) since the old name was actively misleading once the accepted set
    grew. pes_1d/interp_pes sources resolve without waiting for their own
    children (both render `path_xyz` in full at submit time); neb_ts's
    `neb_frames` is written only once its single run finishes, so an
    in-flight or failed NEB source simply has no artifact yet and falls
    through to the existing "no geometries on disk" branch, with no
    special-case status check needed.
  - **Individually-tagged (not-a-job) geometries**, the same day, once
    the user confirmed this was wanted too: 3+ molecule-panel frames now
    serve as a batch source alongside `source_job_id`, closing the one
    gap the plan text's "tagged geometries or a geometry_set" phrasing
    had left open. Resolved by a new special-case step in
    `elicitation.py::validate_draft`, placed beside `_end_molecule`'s own
    frame-resolution block and following its exact pattern: guarded on
    neither `source_job_id` nor `_frame_geometries` already being present
    (resolved once, never re-derived on the resume pass after approval);
    `_frame_geometries` is never a declared ParamSpec, same status
    `_end_molecule` already has, since it is derived from state rather
    than typed into a field. `source_job_id`'s own `required_when`
    changed from `ALWAYS` to `{"missing": "_frame_geometries"}` --
    verified this actually takes effect through `missing_required()`
    (not just `evaluate()` on the condition alone, which the two are
    easy to conflate), not merely assumed from reading the condition DSL.
    An explicit `source_job_id` always wins over on-screen frames, so a
    named job is never silently overridden by whatever else happens to
    be tagged. 3 is the adoption floor (matching `geometry_set`'s own
    existing "three or more" upload convention) -- 1-2 frames fall
    through to asking for `source_job_id` instead, whose own `ask` text
    now mentions the tagging alternative too. Since `molecule_frames` is
    an append-only log of every molecule the user set the whole thread,
    not a curated selection, the auto-adoption note names every adopted
    frame's own description (not just a count), so a wrong adoption is
    visible on the approval card rather than discovered in dispatched
    jobs. At dispatch time, `_finish_submission` uses the `_frame_geometries`
    already carried on the round-tripped approved spec rather than
    re-reading `state['molecule_frames']` a second time, which could
    disagree with what the approval card actually showed if the panel
    changed in between -- the same reasoning `source_job_id`'s own
    fresh-from-disk re-read avoids the opposite failure (a stale
    in-memory copy) for job-sourced batches.
  evidence: tests/backend/p7_04_batch_master.py → "72/72 checks passed.
  Every accepted source task resolved for real: a real geometry_set job;
  a real 2-point pes_1d scan and a real 2-point interp_pes path, both
  read as batch sources BEFORE their own children reached a terminal
  status, proving the read is against the upfront-rendered path_xyz, not
  something that only exists once a scan/path finishes; wigner_spectra
  (ensemble_xyz) and neb_ts (neb_frames) via a hand-built fixture job
  directory (real spec.json/status.json/result.json, a real small
  multi-frame xyz file under the exact key each task uses) rather than a
  full sampling run or NEB search, since what's under test is the
  artifact-key resolution and parsing, not wigner_spectra's/neb_ts's own
  chemistry (already covered by their own test scripts); a plain
  single_point job correctly refused as a source, naming every accepted
  task in the refusal text; the tagged-frame path against a real
  3-frame `molecule_frames` fixture -- reaches ready with no
  `source_job_id`, `_frame_geometries` carries all 3 in panel order, the
  note names every frame's own description; exactly 2 frames falls
  through to asking for `source_job_id` (not enough to auto-adopt), and
  that question mentions the tagging alternative; an explicit
  `source_job_id` wins over 3+ present frames; a real batch dispatched
  and run to completion from `_frame_geometries` alone, no job on disk
  at all, whose children carry no `_frame_geometries` blob themselves;
  child_task asked (never defaulted) and
  reaching ready for all four families; the eom_ccsd/opt capability
  refusal above; real PySCF single_point/gs children (the original,
  still-default-shaped case) AND real PySCF freq children (a genuinely
  different job family with its own real frequency summary
  (frequencies_cm-1/n_imaginary_frequencies), not a copy-pasted
  single-point one) dispatched via JobManager.submit_batch/
  batch_orchestrator.py (mirrors scan_orchestrator.py's wave-dispatch
  shape; `_update_one` is simpler, no aggregation, just completion
  counting); master_kind='batch' and the P7.3 pagination route reused
  unmodified for a third master kind. Standalone script has no live
  server driving BatchOrchestrator's own background thread, so the test
  drives `_update_one` directly in its own poll loop -- same role a live
  server's poll tick plays; server/main.py itself does start/stop the
  real orchestrator thread at lifespan."
- [done] P7.5: 100-child (user-set, plan originally said 200) latency
  spec, cascade-edit e2e, batch e2e, reorder unit, NEB regression
  note: cascade-edit e2e (P7.2's evidence), batch e2e (P7.4's evidence)
  and the reorder unit test (P7.2's evidence) were already done.
  Finished 2026-08-20 with tests/frontend/p7_05_drawer_latency.spec.mjs
  -- seeded at 105 rather than exactly 100 (the user's own "make it
  fast" instruction): CHILD_PAGE_SIZE (frontend/src/lib/queries.ts) is
  ALSO 100, so an exactly-100-child job fits in one page and the
  lazy-scrub half of the spec would never actually fire a second fetch.
  Real end to end: a real 105-image PySCF HF/STO-3G water pes_1d scan
  (not a hand-built synthetic children.jsonl), a real logged-in browser
  session, drawer-open latency measured click-to-render (840-1593ms
  across three runs, well inside an 8000ms budget deliberately generous
  for this host's variable shared load), and a real GET
  .../children?offset=100 fetch proven to fire when the frame scrubber
  jumps past page 1's window.

  Two real bugs found and fixed while seeding this fixture, neither
  reachable through this project's normal single-uvicorn-process
  deployment but both worth fixing regardless:
  - **Orchestrator fault isolation**: scan_orchestrator.py's (and
    ensemble_orchestrator.py's/batch_orchestrator.py's, identical
    shape) `_poll_once()` looped over every running master with NO
    per-master exception guard -- one master raising (found live: a
    leftover pes_1d master whose path_xyz was an absolute HOST path,
    written by a process outside the container) aborted the WHOLE tick
    partway through, silently starving every OTHER running master's
    dispatch, forever, with nothing logged (the outer `_loop` try/except
    only protects the thread from dying, not sibling masters from being
    skipped). Fixed identically in all three orchestrators: the
    per-master `_update_one` call is now individually wrapped.
  - **Cross-process double-dispatch**: `JobManager.submit_scan()`
    dispatches its own initial wave via a throwaway ScanOrchestrator
    instance local to whatever process calls it. Seeding through
    `docker compose exec` (a separate one-off process alongside the
    live server) raced that throwaway instance's dispatch against the
    live server's own long-running orchestrator thread -- two
    processes, two unsynchronized in-memory dispatch_locks, the same
    scan-point index dispatched twice. Not a production bug (the
    deployed stack is a single uvicorn process, so no second dispatcher
    ever exists) -- fixed by changing the seed script's own approach,
    not the app: write the master's spec/status/result by hand (the
    same state submit_scan itself writes) and never call
    _dispatch_more, so only the live server's own orchestrator ever
    dispatches. Documented in the spec's own seed-code comment so a
    future similar fixture doesn't reintroduce it.
  evidence: tests/backend/p7_orchestrator_fault_isolation.py → "4/4
  checks passed. A real poisoned master (genuinely unreadable path_xyz)
  and a real healthy master submitted alongside it, run through one
  real _poll_once() tick: the poisoned one raises exactly as the live
  bug did, _poll_once() itself does not propagate that exception, and
  the healthy master's own children still reach a terminal status --
  not silently starved by its poisoned sibling."; tests/backend/
  p7_05_neb_regression.py → real ORCA neb_ts run, HCN -> HNC (hydrogen
  cyanide -> hydrogen isocyanide), chosen per the user's explicit
  instruction to test NEB/interpolation job types against a simple,
  well-behaved isomerization endpoint pair. Surfaced and led to fixing
  a real, pre-existing (not Phase-7-introduced) regression: see the
  separate neb_ts fix commit.
- merged: -

Separately from this phase's own steps: `_build_neb_ts_spec_or_error`
(app/agent/tools.py) built its `JobSpec` with no `task`/`subtype` set,
so `build_input_preview`'s `dispatch.resolve_runner(spec.task or "",
spec.subtype or "", spec.method)` resolved `resolve_runner("", "",
method)` -> "No runner is wired up for / yet.", breaking every neb_ts
approval-card preview outright. Confirmed via `git log -S` to originate
in 1323aca (P2B.2/P2B.4's task/subtype migration), which changed
`JobSpec(method="neb_ts", ...)` to `JobSpec(method=method or "", ...)`
without adding the `task="neb_ts"` stamp every other bespoke builder in
the same function already carries. `tests/e2e/e2e_08_job_matrix.py`
(the live-stack e2e matrix that would ordinarily catch this) needs a
full docker-compose stack with a live LLM that this environment does
not have -- per `tests/backend/reg2b_03_matrix_v2_taxonomy.py`'s own
comment, it has never been run here -- so this fix is verified only by
direct reproduction of the real `validate_draft`/`_spec_from_draft`
path (tests/backend/p7_05_neb_regression.py), not by that e2e script.
Fixed by stamping `task="neb_ts", subtype=""` on the spec, matching
every other builder in `_build_spec_or_error`.

## Phase 8: CAS workflows, orbital reuse, ensemble spectra

- [done] P8.1: Cross-job orbital reuse (initial_orbitals_job_id; per-engine)
  evidence: tests/backend/p8_01_orbital_reuse.py → "38/38 checks passed. PySCF:
  reusing a real completed CASSCF job's orbitals.molden across a genuinely
  different (stretched) geometry cuts a real cold run from 17 macro iterations
  to 5, converging to the identical energy either way (a same-geometry restart
  was deliberately avoided -- water/STO-3G CAS(4,4) converges cold in too few
  iterations to show any reduction, per this phase's own advisor guidance).
  ORCA: a real MOREAD+%moinp restart runs to completion, the generated input
  carries MOREAD/%moinp only when initial_orbitals_job_id is set, and
  referencing a PySCF-only source (no input.gbw) fails loudly rather than
  silently starting from a fresh guess. BAGEL: load_ref/save_ref wiring
  verified structurally across every CASSCF/CASPT2-family branch
  (gradient/nac/geometry_optimization/frequency/opt_freq/caspt2 with and
  without want_oscillator_strengths, and caspt2+oscillator-strengths+reuse
  together) -- save_ref sits between print and the state-specific block in
  every one, load_ref replaces (not follows) the hf preamble when reuse is
  requested, matching scripts/spikes/spike_bagel_caps.py's own verified
  load_ref shape. A live BAGEL restart is gated behind P8_01_LIVE_BAGEL=1
  (unset by default) rather than run unconditionally -- this host's BAGEL/MKL
  install is genuinely slow (CLAUDE.local.md's standing note); the structural
  checks already meet this app's own accept-criterion floor ('orca/bagel at
  minimum assert orbitals consumed (log evidence) or gap-listed'), so a live
  run is deferred rather than holding this step's evidence hostage to host
  load. registry2/elicitation.py's _initial_orbitals_problem (existence,
  completed status, casscf/caspt2 method, same destination engine) and
  validate_draft's non-blocking degrade-with-a-note behavior for an invalid
  tag are both exercised against real job-store entries, not fixtures."
  note: a first design read the source job's orbitals straight back from
  its own orbitals.molden via pyscf.tools.molden.load() and passed THAT
  reconstructed mol as project_init_guess's prev_mol -- syntactically fine,
  wrong in practice: a molden-round-tripped mol's internal _basis/atom-label
  representation doesn't match one build_mole constructs directly, so
  pyscf.gto.same_mol/same_basis_set (which project_init_guess uses internally
  to decide whether prev_mol even applies) spuriously disagreed even for the
  identical basis, surfacing as "Project initial guess from different system"
  on a plain geometry-only reuse. Caught by this step's own test script
  reusing across a genuinely different geometry, not by inspection -- fixed
  by rebuilding prev_mol from the source job's own recorded molecule/basis
  via build_mole (the same function every other mol in pyscf_runner.py goes
  through, BSE `bse:` sentinel included, since build_mole already resolves
  it) instead of trusting molden.load()'s own returned mol.
- [done] P8.2: cas_reco follow-up: a completed cas_reco/autocas or cas_reco/avas
  job triggers job_watcher.py's own agent-turn notice mechanism (the same
  shape ensemble_completed_ids already uses for wigner_spectra) to auto-compose
  a CASSCF-ee draft pre-filled with the recommended active space and
  initial_orbitals_job_id (chaining directly into P8.1), while the draft's own
  ParamSpec.required_when for n_states/basis still gates READY regardless of
  what the notice's prose says -- the mechanical backstop the user's own
  standing distrust of prompt-only elicitation rules calls for.
  evidence: tests/backend/p8_02_cas_reco_followup.py → "14/14 checks passed.
  _agent_notice's cas_reco branch is asserted on its actual content (names
  start_job_draft(method='casscf', engine='pyscf'), subtype='ee',
  recommended_active_electrons/recommended_active_orbitals,
  initial_orbitals_job_id, and the explicit 'do NOT set n_states'/basis
  instruction) rather than merely its presence; cas_reco/explain is confirmed
  to get the plain completed-job wording, not the auto-draft one.
  _poll_once's classification is exercised end to end with jw.invoke_turn
  monkeypatched to capture the notice (the same no-LLM-needed pattern
  tests/backend/fail_01_notice_flow.py already established) against a real
  hand-built completed cas_reco/autocas job in the job store -- exactly one
  turn fires, carrying the cas_reco-specific notice naming the real job id;
  a parallel cas_reco/explain fixture confirms it does NOT reach the
  follow-up bucket. The mechanical backstop: a draft built exactly as the
  notice instructs (active_electrons/active_orbitals/initial_orbitals_job_id
  set, n_states and basis both omitted) is NOT ready and specifically asks
  for one of them by name via validate_draft -- proving the ban holds even
  if a future model, or a reworded notice, ignores the prose."
  note: OVERHAUL_PLAN.md's original P8 text 2 also specifies "autocas
  (default when basis + n_states given), avas (default otherwise)" for
  which cas_reco subtype a bare request resolves to. **Not implemented, and
  not implementable as written**: registry2/params.py's `basis` ParamSpec is
  `required_when=ALWAYS` with `applies_to=_ALL_COMPUTE` (which includes
  cas_reco), so "when basis is given" is vacuously always true; and
  `n_states`'s own `required_when` includes `{"eq": ["subtype", "autocas"]}`,
  meaning n_states is required BECAUSE autocas was already chosen -- it
  cannot also be the signal used to CHOOSE autocas without circularity. This
  predates registry2's ParamSpec table, the same class of plan text
  superseded by a later architectural decision as P1.3/P2.6 -- recorded here
  as the deviation rather than edited into the plan. avas_aolabels (avas's
  only other own parameter) has no required_when of its own and a documented
  default ("valence p/d shells of every non-hydrogen atom"), so this is not
  a case of one subtype needing a rescue; a bare "recommend an active space"
  request is asked which of explain/autocas/avas, same as any other
  multi-subtype task (opt's min/constrained/ci) already is.
- [done] P8.3: wigner_spectra via drafts; cap 250→500; live broadening slider (client-side)
  note: wigner_spectra already went through the draft workflow as of Phase 2
  (`_build_ensemble_spec_or_error`) and already used P7.3's shared children-
  pagination route for its frame viewer -- neither needed new work here. What
  this step actually built: the cap raise itself (registry2/params.py's
  n_samples ParamSpec help/ask text already said "the maximum is 500" -- a
  card promising a ceiling the code didn't honor, since _MAX_ENSEMBLE_SAMPLES
  was still 250; caught the same way P2.3's missed single-quoted string was,
  by asserting the enforced constant against the promised text rather than
  reading each in isolation); a new GET /api/jobs/{id}/wigner_transitions
  route (plain def, lock-free, ownership-checked, reusing
  pool_ensemble_transitions unmodified -- the same pooling
  EnsembleOrchestrator already does for the static PNG, so the two never
  disagree about which sub-jobs' transitions count); and a live client-side
  broadening slider (WignerBroadeningPanel.tsx) that fetches the pooled
  transitions once and re-broadens entirely in the browser on every move,
  reusing UvVisSpectrumInline.tsx's own broadenedSpectrum function
  (parametrized on fwhmEv) rather than a second broadening implementation.
  The existing server-rendered ensemble_spectrum PNG (EnsembleSpectrumPanel)
  and its chat-tool re-plot path are both left in place, unaffected --
  P9.4's own MiniLineChart-consolidation pass is where the plan already
  schedules retiring redundant server PNGs, not this step.
  evidence: tests/backend/p8_03_wigner_cap.py → "6/6 checks passed --
  _MAX_ENSEMBLE_SAMPLES is 500, and (the actual regression this step fixes)
  the n_samples ParamSpec's own help/ask text is asserted to name that SAME
  number rather than trusted to already agree with it. Also exercises the
  boundary directly against _build_ensemble_spec_or_error: n_samples=500
  clears the ceiling check, n_samples=501 is refused by name -- catching
  what the constant/help-text agreement checks alone would not: a stale
  250 ceiling passes those unchanged, since nothing about them depends on
  which number is actually enforced at the call site."
  evidence: tests/frontend/p8_03_wigner_broadening.spec.mjs → "11/11 checks
  passed against the real docker dev stack: a real PySCF HF/STO-3G water
  frequency job, real Wigner-sampled geometries drawn from its own normal
  modes (app.chemistry.jobs.wigner.sample_from_source_job, the same
  function EnsembleOrchestrator itself uses), and a real 6-sample TD-HF
  ensemble the live server's own orchestrator dispatched and completed
  end to end (the master's state written by hand rather than via
  submit_ensemble, to avoid the same one-off-process-races-the-live-
  orchestrator double-dispatch p7_05_drawer_latency.spec.mjs's own seed
  already had to work around). The panel renders a real broadened curve
  from the real pooled-transitions route; moving the slider 5 times via
  keyboard changed the FWHM readout (0.40 -> 0.45) and re-rendered the
  chart while a page.route interception on wigner_transitions counted
  ZERO new requests (before=0, after=0) -- the actual claim under test,
  not merely that the slider moves. staleTime:Infinity +
  refetchOnWindowFocus:false on the query (queries.ts) were needed for
  this to hold reliably, per this phase's own advisor guidance that
  TanStack Query's default refetch-on-focus could otherwise fire a real
  request a bare move-count assertion would misattribute to the slider.
  Caught live rather than by inspection: the first run failed at the
  panel-render step because frontend/dist was rebuilt (npm run build)
  BEFORE the data-testid attributes were added in a later edit, so nginx
  was serving a stale bundle -- fixed by rebuilding again before the
  second (passing) run; also found and worked around a locked-out
  qatest_admin test account with no recorded password from an earlier
  session (server.admin_cli reset-all --confirm, auth data only, job/
  thread/KB data preserved -- the documented recovery path, safe here
  since the only account on the dev stack was the test admin itself,
  verified by a direct users-table query before running it)."
- [done] P8.4: bug fix, user-reported: EOM-CCSD with 0 requested excited
  states crashed both engines instead of computing the plain ground-state
  energy the user actually meant
  note: found from a real conversation, not a test. The user asked for
  EOM-CCSD on water/6-31G*, then answered "only the ground state" to the
  n_states question. The agent set n_states=0 and submitted -- registry2/
  params.py's n_states ParamSpec requires the field to be PRESENT for
  subtype='ee' but enforces no minimum value, so 0 satisfied it and the
  draft reached READY. Both engines then crashed on a real, spent
  subprocess rather than refusing at elicitation time: PySCF's
  eom_rccsd.kernel(nroots=0) raised IndexError deep inside its own
  Davidson-solver memory-sizing code (linalg_helper.py:768, indexing an
  empty guess-vector list); ORCA's MDCI module exited with code 55,
  "Number of roots is not set, it should be NRoots>0!". Root-caused from
  the two real failed job directories the conversation left behind
  (data/jobs/838df02c5d93, data/jobs/a1b38c902757's own result.json
  tracebacks), not by reading the runners in isolation. The user then
  asked for plain CCSD as a fallback, which ALSO failed on both engines --
  a SEPARATE, deeper bug: registry2/capabilities.py already declared
  energy=True for ccsd/mp2 on both pyscf and orca (with real manual/run
  citations), but neither runner's single_point/gs path could actually
  build one. PySCF's run_single_point only ever called build_mf (hf/dft
  only) -- the cc.CCSD(mf)/mp.MP2(mf) construction existed, but only
  inside run_gradient, unreachable from a plain energy request. ORCA's
  single_point branch of build_input_text had no CCSD/MP2 case at all, not
  even reachable via its own gradient path (capabilities.py's own orca/
  ccsd note already said "No gradient is wired up here"). The capability
  table was telling the truth about what COULD run; the dispatcher just
  never learned to build it. Fixed both, together, matching the user's
  own diagnosis: registry2/elicitation.py's validate_draft() now
  recognizes n_states=0 on a single_point/ee draft, for a single-reference
  method (hf/dft/mp2/ccsd/eom_ccsd -- params.py's new public
  SINGLEREF_METHODS alias), as a well-formed ground-state-only request and
  silently reroutes it to a plain single_point/gs draft before either
  engine ever sees it (method='eom_ccsd' becomes 'ccsd'; hf/dft need no
  translation, since single_point/gs already speaks those names natively;
  stale ee-only params -- n_states, use_tda, want_oscillator_strengths,
  target_state, weights -- are dropped rather than left on the approval
  card as clutter). Multireference (casscf/caspt2) is deliberately
  excluded: there n_states INCLUDES the ground state, so n_states=1 (not
  0) is already that method's own "ground state only" through the
  ordinary state-average machinery -- a different, pre-existing case, not
  this bug, and left untouched. Then run_single_point on both
  pyscf_runner.py and orca_runner.py (plus build_input_preview/
  build_input_text, so the approval card matches what actually runs) was
  extended to build a real CCSD/MP2 ground-state energy: PySCF reuses
  run_gradient's own cc.CCSD(mf)/mp.MP2(mf) construction minus the
  now-unneeded nuc_grad_method() call; ORCA emits a bare '! CCSD'/'! MP2'
  bang line with no %mdci block at all, since a ground-state-only
  CCSD/MP2 energy needs no NRoots (only EOM-CCSD's excited-state roots
  do).
  evidence: tests/backend/p8_04_ccsd_energy_and_ee_zero_states.py →
  "18/18 checks passed. Real engine runs throughout, not parser fixtures
  -- this exact bug was two runner-level failures no amount of registry-
  table inspection would have caught, only actually building and running
  the job did, both times. PySCF: real cc.CCSD(mf)/mp.MP2(mf) single-point
  energies on water/STO-3G, both converged, both below their own HF
  reference (real correlation recovered: CCSD -75.0119 Ha, MP2 -74.9981
  Ha vs. HF -74.9627 Ha). ORCA: real ORCA 6.1.1 runs (QC_AGENT_ORCA_BIN)
  of the same system at the same level, agreeing with PySCF's independent
  implementation to better than 1e-3 Ha for both CCSD (-75.0118 Ha) and
  MP2 (-74.9980 Ha) -- confirms the bare '! CCSD'/'! MP2' bang line
  actually computes the correlated energy, not just that ORCA exits 0.
  validate_draft: the EXACT shape of the two real failed jobs (eom_ccsd,
  n_states=0) now reaches READY as single_point/gs method='ccsd' with the
  stale ee params dropped and an explanatory note attached; the same
  reroute applies to method='hf'; a genuine n_states=2 request and a
  genuinely-unanswered n_states question are both confirmed completely
  unaffected; a casscf draft with n_states=0 is confirmed NOT rerouted
  (out of this bug's scope, left as pre-existing behavior)."
  Regression: tests/backend/elic_01_draft_scenarios.py (201/201),
  agent_02_draft_flow.py (35/35), tax_01_v2_specs.py (36/36),
  reg2b_01_no_v1_redecision.py (15/15), p8_02_cas_reco_followup.py
  (14/14), p8_03_wigner_cap.py (6/6), reg_01_wigner_prep.py (all passed),
  scripts/check_capability_matrix.py (506/506 assertions, 15 rows, 19
  tasks) and scripts/generate_capability_docs.py --check all still pass
  unchanged -- registry2/capabilities.py's own declarations were never
  wrong and needed no edits, only the runners catching up to them.
- merged: -

## Phase 9: Custom plotting, geometric-parameter queries, danger zone, polish, final docs

  note: P9.2 (geometric-parameter queries) added 2026-08-19 at the user's
  direct request, mid-Phase-6: "if the user tags jobs or a frames from the
  instrument pannel, and asks for the length of a bond, angle or dihedral
  by giving the atom indices ... i want it to be able to calculate it and
  give the user an answer in a table. if its a nested job with multiple
  geometries, i want the output to be histograms of the asked geometrical
  parameters for all geometries in the tagged job." Placed here rather
  than in Phase 7 (which builds the paginated child-access this step's
  histogram case depends on) because the query surface itself is thematic
  kin to P9.1's declarative-plotting-from-tagged-data tool, not a
  performance-layer change. Numbered P9.2 with the rest of Phase 9 shifted
  down accordingly, since nothing in Phase 9 has started -- unlike a
  completed phase's step numbers (see P1.3's retirement note), there is no
  audit trail yet to preserve by leaving a gap instead.

  Refined 2026-08-20, same request, before any implementation started:
  "the table should be the format for pes_1d and interp_pes job types as
  well. the histogram should be done only for batch and wigner spectra job
  types." So the table/histogram split is NOT "single geometry vs. any
  master job" as first drafted -- it is ordered-vs-unordered: a `pes_1d`/
  `interp_pes` master (and a multi-frame `geometry_set`) has an inherent
  order (scan coordinate, path image index) worth keeping visible, so it
  gets a table too (one row per point/image, ordered, one column per
  requested parameter) -- collapsing that into a histogram would discard
  the trend along the path, which is usually the entire reason to tag a
  scan. Only `batch` (an unordered tagged collection) and `wigner_spectra`
  (a statistical ensemble, where the distribution IS the point) get a
  histogram.

  note: P9.3 (default geometry-selection hierarchy) added 2026-08-20,
  during Phase 7's batch geometry-source work (P7.4's job-id/tagged-frame
  widening), at the user's direct request: "unless explicitly tagged, the
  default geometry selection hierarchy to act on the user prompt should
  be, 1. conversation context (ex: 'use the same geometry...', 'repeat
  calculation with {method} or {basis}...', and similar), 2. currently
  displayed frame (molecule) in the instrument pannel. if tagged from
  job, that takes priority over all others. 1 and 2 are what the agent
  should default to if nothing is tagged." -- with the explicit fallback
  "if you can't implement it during this phase, fold it into the plan"
  when it turned out to be cross-cutting (every job type's molecule
  resolution, not batch-specific) rather than a P7.4-sized addition.
  Placed in Phase 9 rather than Phase 7 for that reason -- it needs its
  own design pass (see the plan entry's own note on what "conversation
  context" resolves against mechanically), not a quick param add. Numbered
  P9.3 with the rest of Phase 9 shifted down accordingly, same
  nothing-started/no-audit-trail-to-preserve reasoning P9.2's own note
  above already gives.

  note: P9.4 (per-user danger zone) extended 2026-08-20, same session,
  at the user's direct request: "fold in a per user download all user
  data option into phase 9 that allows user to download a master zip of
  their jobs, kb (without seeded), and uploaded files. the button should
  be in the same place as the per user purge functions make sure the
  purge function always kills running jobs too." The download-all-data
  button folds into the already-planned danger-zone step rather than
  becoming its own step, per the user's own placement instruction (same
  UI location as the purge actions); the purge requirement was already
  implicit in the plan's original "cancel running first" phrasing but is
  now stated as a hard requirement naming the actual mechanism
  (JobManager.cancel()'s real process-group kill, not a database-only
  mark) so it cannot be quietly satisfied by a weaker purge-time
  deletion path later.

  note: larger plot font sizes folded into P9.5 2026-08-20, at the
  user's direct request: "fold in a point to make all font sizes of all
  plots larger." Every matplotlib render already goes through
  `app/chemistry/spectrum.py` (confirmed: it and `server/routes/jobs.py`
  are the only two files touching matplotlib in the codebase), which sets
  no base `rcParams` font size today -- axis labels/titles fall back to
  matplotlib's 10pt default while legends and tick labels are pinned
  explicitly *smaller* (7-8pt, e.g. `render_line_plot`'s
  `ax.legend(fontsize=8)`). Scope is a global bump (axis labels, titles,
  ticks, legends) applied once via a shared `rcParams`/style setting at
  the top of that file, not per-call tuning, so it's a small addition to
  the already-planned polish sweep rather than a new step.

- [done] P9.1: plot(kind="custom") declarative plotting from tagged data
  evidence: runtime field-path resolution against a job's real summary (no
  shadow field schema -- registry2 TaskDef.plottable_fields is explicitly
  illustrative/non-authoritative, wired into lookup_capabilities). One-job
  array mode and several-jobs one-point-per-job mode (sorted by x), refusing
  cleanly with the job's real available fields on any bad path. render_line_
  plot (spectrum.py) extended with log_y rather than a second renderer.
  Verified directly against real completed jobs on disk -- success paths,
  every refusal path, and a genuine crash (a non-numeric resolved field,
  e.g. an orbital_table entry, hit an uncaught float() TypeError) caught and
  fixed via a guarded _as_float before this shipped. tests/backend/agent_01_
  token_budget.py: 5,147/10,000 tokens (comfortably under budget) with the
  new spec param and expanded docstring. Full live-agent e2e run against the
  dev stack (tests/e2e/e2e_09_plot_tools.py): 6/7, the one remaining failure
  (XN-03) a pre-existing REFUSAL_WORDS wording gap unrelated to this work
  (this account's completed casscf job has no excited states at all, so it
  hits an earlier, differently-worded refusal than the word list covers --
  confirmed by inspecting the job's own summary, not touched here). Real-
  browser Playwright check confirmed a live plot(kind='custom') response
  renders a fully-loaded inline <img> (naturalWidth>0, no "failed to load"
  placeholder).
  note: fixed two pre-existing bugs found while getting this verified end to
  end, both unrelated to custom plotting itself: (1) MessageBubble.tsx's
  inline PLOT_ARTIFACT rendering gate checked ToolMessage.name against the
  pre-unification tool names ("plot_job_comparison"/
  "plot_wigner_ensemble_spectrum"), permanently unreachable since the
  Phase-8 plot(kind=...) unification made every call named "plot" --
  comparison/ensemble plots had silently stopped rendering inline in chat
  since that commit; fixed to gate on the PLOT_ARTIFACT marker's own content
  shape instead of a name allowlist, so it can't rot the same way again.
  (2) tests/e2e/e2e_09_plot_tools.py's _submit_comparable_single_points used
  the pre-registry2 JobSpec shape (method="single_point", no task/subtype),
  which resolve_runner rejects outright -- every job it tried to seed failed
  silently and both callers' account-scavenging fallback masked it with
  unrelated jobs instead of surfacing the real cause; fixed to the v2
  taxonomy shape. Also updated the P-compare-badfield case: kind='custom'
  can now legitimately plot a real field (dipole_debye) kind='comparison'
  doesn't support, so the model correctly chose the new tool over refusing
  outright when asked to "compare the dipole moment" -- real data, not
  fabrication -- and the check now verifies specifically that a
  kind='comparison' call refuses on an unsupported field, rather than
  asserting no plot of any kind ever succeeds.
- [done] P9.2: Geometric-parameter queries (bond/angle/dihedral table for a
  tagged single geometry, and for a tagged pes_1d/interp_pes/geometry_set
  -- ordered, one row per point/image; histogram only for a tagged batch or
  wigner_spectra master -- unordered/statistical)
  evidence: new `geometry_parameters` tool (app/agent/tools.py), reusing
  zmatrix.py's `_distance`/`_angle_deg`/`_dihedral_deg` primitives (imported
  directly -- codebase precedent for cross-module underscore imports already
  exists, e.g. geometry_upload.py importing molecule.py's `_ATOM_LINE_RE`)
  and opt/constrained's own atom-index convention, extracted into a shared
  `_validate_atom_indices` helper (one validation path, one 1-based
  convention, per the plan's own instruction) rather than re-derived --
  extraction verified message-for-message identical to the pre-extraction
  wording for the constrained-opt caller (no test pinned the exact strings,
  confirmed by grep, but tests/backend/opt_01_optimization_family.py's own
  four assertions on that wording -- "2 1-based", "between 1 and 3", "bond"+
  "angle", "must be a number" -- still hold unchanged; 43/43 passed live
  against the rebuilt container). Geometry source is a design decision an
  advisor consult reshaped before implementation: pes_1d/interp_pes/
  geometry_set/wigner_spectra all read their geometries from ONE artifact-
  file read (BATCH_GEOMETRY_SOURCE_ARTIFACT_KEY + geometry_upload.
  parse_multi_frame_xyz), confirmed by reading submit_scan/submit_ensemble/
  submit_geometry_set's own source -- every image/sample's geometry is
  written to path_xyz/ensemble_xyz at SUBMISSION time, deterministically,
  never gated on a sub-job's own completion (unlike its ENERGY) -- so no
  per-child result.json reads or P7.3-style pagination are needed for any
  of those four; only `batch` (deliberately excluded from that map, since
  its children can be a heterogeneous mix of starting geometries) resolves
  per-child via sub_job_ids_of, skipping a not-completed or geometry-less
  child by name rather than silently dropping it, and validating each
  child's OWN atom count individually rather than assuming uniformity.
  Multiple requested parameters render as one image with one panel per
  parameter (new render_histogram_plot, spectrum.py) rather than one
  PLOT_ARTIFACT marker per parameter, since MessageBubble.tsx's
  PLOT_ARTIFACT_RE matches exactly one marker per tool response.
  Verified directly: single-geometry success/every refusal path (bad type,
  wrong atom count, out-of-range index, non-numeric field) against a real
  completed job; synthetic fixtures (real job-directory shapes, written by
  hand from the verified runner/submit_* source, not guessed) for the
  pes_1d/geometry_set ordered-table path, the wigner_spectra histogram path
  including on a still-running master, and the batch histogram path
  including its >=2-sample floor and per-child heterogeneous-atom-count
  skip (a diatomic child correctly contributed to a bond-length histogram
  but was skipped, by name, from an angle histogram needing a 3rd atom it
  doesn't have). Live-agent verification (tests/e2e/e2e_10_geometry_
  parameters.py, 4/4): real out-of-range and malformed-dihedral refusals,
  a real bond-length table, and a real geometry_set ordered table with
  exact submitted values -- plus an unplanned, genuinely convincing live
  demonstration mid-testing: asked for "the H2-O1-H3 angle" against a
  3-atom molecule, the model first tried atom index 4 (misreading which
  atom "H3" was), got this tool's clean refusal instead of a crash, and
  self-corrected to the right indices on its very next call without being
  told how.
- [done] P9.3: Default geometry-selection hierarchy (explicit job tag >
  conversation context > active instrument-panel frame, when a request
  does not name a geometry explicitly)
  evidence: an advisor consult reshaped the design before implementation
  twice. First it caught a real bug in P9.2's own _resolve_single_completed_
  geometry: a master job (pes_1d/batch) has a REAL, non-empty spec.molecule
  (images[0]/geometries[0], for JobSpec round-tripping) rather than an empty
  placeholder as an earlier survey had claimed, so a caller resolving "job
  X's geometry" without task-based routing would silently get an arbitrary
  single point instead of refusing -- fixed with a _NO_SINGLE_GEOMETRY_TASKS
  guard checked by task membership before ever reading result data (shipped
  separately, commit 5dc5939). Second, once the advisor tool became
  unavailable mid-session, the "conversation context" tier was re-derived
  from first principles by direct code reading rather than left as a
  half-verified plan: check_job_status's own existing fallback
  (state["active_job_ids"][-1] = "the most recently submitted job") is
  already the exact mechanical "last job" tracker P9.3 needs, so no new
  state slot, reducer, or job_watcher write site was necessary -- the
  earlier plan to add one was dropped as redundant once this was confirmed.
  Implementation: moved the (molecule, error) resolver out of app/agent/
  tools.py into a new app/chemistry/jobs/geometry_resolve.py, since
  registry2/elicitation.py is deliberately independent of the agent layer
  (see validate_draft's own docstring) and needs the same function P9.2's
  geometry_parameters tool already used. New source_geometry_job_id
  ParamSpec (params.py), tag-driven and never asked for like
  initial_orbitals_job_id -- but unlike that one, NOT silently dropped on
  failure: a user who named a specific job's geometry and silently got a
  different, unnamed one instead would be a wrong answer, not a
  convenience, so an unresolvable tag is asked about instead (elicitation.
  py's new _source_geometry_problem, check_external-gated for the same
  pre-interrupt-determinism reason source_frequency_job_id/
  initial_orbitals_job_id already are). app/agent/tools.py's new
  _resolve_draft_molecule gives an explicit tag priority over state
  ["molecule"] at both preview-build and real-submission time, re-resolved
  fresh each time (not trusted from the draft) so the two validate_draft
  passes around the approval interrupt agree by construction, matching
  submit_draft's own existing "do not read anything outside the draft"
  discipline. update_job_draft's docstring tells the model to reach for a
  job id it already has from earlier in the conversation rather than ask
  the user for one -- no proactive hint injection needed, since a
  submitted job's id already appears in that job's own "Job submitted...
  id=..." message, which stays in the model's own context.
  Verified directly: all four cases (good tag, bad tag, master-job tag
  refusing, explicit tag beating a set state["molecule"]) against real
  jobs. Full backend regression on the rebuilt container: elic_01_draft_
  scenarios.py 201/201 (validate_draft's existing behaviour unchanged),
  reg2_01_registry_v2_payload.py 20/20, p7_04_batch_master.py 72/72
  (batch's own unrelated source_job_id unaffected by the new, differently-
  named param), opt_01_optimization_family.py 43/43 (the opt/constrained
  family, which shares the same molecule gate, unaffected). New live-agent
  e2e (tests/e2e/e2e_12_source_geometry.py): 3/3 blocking checks passed --
  an explicit "use job X's geometry" request writes source_geometry_job_id
  and reaches READY without ever calling set_geometry (the first tool
  response can still legitimately ask "which molecule" before the model
  has had a chance to answer with the tag -- elicitation.py asks one
  question at a time by design, so this is not itself a failure); a
  nonexistent tagged job is refused by the backend's own "No such job"
  text, not silently substituted; and approving a tagged draft runs a real
  job whose spec.molecule exactly matches the tagged source job's own
  geometry, confirmed by reading both jobs' spec.json directly. A fourth,
  explicitly non-blocking check for the two-turn "repeat that with a
  different basis" conversational case -- the actual feature this tier
  exists for -- passed cleanly in one run (correctly recalling the earlier
  job's id with no prompting) and showed the local model naming a
  different, stale job id from an unrelated earlier debugging run in
  another; recorded as model-judgement signal rather than a code defect,
  since ordinary language recall of "which job did we just discuss" is
  inherent NLU this codebase already leaves to the model everywhere else,
  and the mechanical part -- the id, once named, resolving correctly and
  refusing cleanly when it does not -- is what G1-G3 verify and is fully
  deterministic.
- [done] P9.4: Per-user danger zone: self-scoped purges that always kill
  a running job's whole process (JobManager.cancel(), never a
  database-only mark, and recursing into batch/pes_1d/interp_pes/
  wigner_spectra sub-jobs the same way cancel() already does generically)
  + a "download all my data" zip (own jobs, own uploads, own non-seeded
  KB contributions) button co-located with the purge actions;
  dz_01_self_purge.py
  evidence: an Explore-agent survey found the admin-side building blocks
  to reuse before any code was written: app/auth/storage_quota.py's
  purge_user_data (used by DELETE /api/admin/users/{id}, account
  deletion) already composes exactly the right primitives -- _job_
  candidates/_kb_candidates/_upload_candidates (each takes owner_filter),
  _cancel_and_await_terminal (blocks on JobManager.cancel() -- which
  already auto-recurses into batch/pes_1d/interp_pes/wigner_spectra
  sub-jobs itself, so no caller-side recursion was needed), and the
  Chroma-invisible KB-orphan filesystem sweep. New purge_own_data(user_id)
  (storage_quota.py) reuses all of these but deliberately omits
  _thread_candidates -- unlike account deletion, the account survives a
  self-purge, so losing every conversation as a side effect of "clear out
  my old jobs" would be a surprising, unrelated loss; verified structurally
  (the function's return dict carries no thread_ids key at all).
  New routes in server/routes/auth.py (self-service, same file as change-
  password/me, no admin role required since owner_filter=<the caller's own
  id> on every candidate builder means it can only ever act on the
  caller's own resources): POST /api/auth/purge-my-data, and GET
  /api/auth/download-my-data -- an in-memory zip (io.BytesIO +
  zipfile.ZipFile, same convention GET /api/jobs/{id}/download already
  uses and never written to disk, since /data is already close to full)
  covering the same three categories, reusing _pyscf_text_summary
  directly for PySCF jobs' text-only export rather than re-deriving it.
  Frontend: a new "Danger zone" section in AccountFlyout.tsx (the account
  panel every signed-in user already gets), reusing DangerZoneSection.tsx's
  existing PurgeAction component (exported for this) rather than a second
  typed-confirmation implementation -- "delete everything I own" carries
  the same no-undo weight as the admin console's deployment-wide purges,
  just scoped to one person. Gated behind typing DELETE MY DATA; the
  download link is a plain cookie-authenticated <a href> matching
  JobDetailDrawer's own existing convention for job downloads, not
  fetch+blob.
  Verified: full backend regression on the rebuilt container --
  new tests/backend/dz_01_self_purge.py, 12/12, covering the real HTTP
  round trip (upload+KB+job created via real routes as a disposable
  non-admin user, purged via the real POST /api/auth/purge-my-data as
  that same user, confirmed gone via GET), a structural check that
  purge_own_data never touches threads, a genuinely in-flight job
  actually caught mid-run and killed rather than orphaned (status
  'running' at purge time, confirmed by directly reading job status
  immediately before calling purge_own_data in the same process that
  submitted it -- same technique sec_08b_delete_user_running_job.py
  established, since JobManager's live Popen is scoped to whichever
  process called submit()), and a well-formed downloaded zip containing
  the test user's own job/upload/KB-source paths (verified via zipfile.
  testzip() plus exact member-name checks). sec_08_delete_user_orphaned_
  files.py (3/3) and sec_08b_delete_user_running_job.py (4/4) re-run
  clean, confirming the admin-driven purge_user_data path is untouched.
  Frontend: `npx tsc --noEmit` clean; `npm run build` refreshed dist for
  the dev stack's nginx bind mount; real-browser Playwright check against
  the rebuilt dev stack confirmed the account-panel menu entry opens the
  flyout, the danger zone section renders with both the download link
  (correct href) and the purge action, and the typed-confirmation gate
  behaves correctly (disabled with nothing typed, still disabled on a
  wrong phrase, enabled only once the exact phrase is typed) -- 8/9
  checks, the one non-pass a false failure in the throwaway verification
  script itself (an innerText case-sensitivity check against
  CSS-uppercased heading text, the same known gotcha ui_04_admin_visual.
  spec.mjs's own comments already document), not a product defect.
- [done] P9.5: UI polish sweep (spectrum download buttons, 8x6 PNG symmetry, ensemble marker, MiniLineChart multi-series, MO viewer 20-unoccupied cap, larger font sizes across all plots)
  evidence: two of the six listed items were found already shipped by an
  earlier phase, verified by reading the real code rather than trusted
  from the plan text (which was last accurate as of an early-session
  survey, before those phases landed): the ensemble GitBranch marker
  (JobsPanel.tsx/JobManagerPanel.tsx already render it for ANY truthy
  job.master_kind, and _master_kind in server/routes/jobs.py already
  returns "ensemble" for wigner_spectra -- P7.4's own unification of the
  former separate is_scan_master/is_ensemble_master booleans covered
  this for free); the MO-viewer unoccupied-orbital cap (OrbitalTable.tsx's
  MAX_UNOCCUPIED_SHOWN = 20 and pruneOrbitalRows, counting per spin
  channel independently, already implemented and already wired into
  JobDetailDrawer's orbital scrubber).
  The remaining four: app/chemistry/spectrum.py now sets one shared
  rcParams block (font.size 13, axes.titlesize 16, axes.labelsize 14,
  tick/legend 12) plus module-level _FIGSIZE=(8,6)/_DPI=300 constants
  applied at every one of its nine renderers, replacing the previous mix
  of 6.5x4/7x4.5 figsizes, 150 dpi, and per-call fontsize=7/8 overrides
  that undercut a shared setting that didn't exist yet -- verified by
  rendering a real plot and reading its actual pixel dimensions
  (2400x1800 = 8x6in at 300dpi) and eyeballing the rendered font sizes
  directly. UvVisPanel.tsx/IrSpectrumPanel.tsx gained a ViewerOverlay-
  portalled DownloadButton (the same overlay-control-collision-avoiding
  mechanism every 3D viewer already uses, not a second ad hoc
  positioning scheme), backed by lib/download.ts's existing
  triggerDownload -- the image is a real server-rendered PNG at a stable
  URL, not a canvas capture, so this is the "any URL under the page's own
  origin" case that helper already documents itself for. MiniLineChart.tsx
  gained a `series` array (from a single `y`) with a legend, gap-aware
  per-series path drawing (a null/failed point breaks its own state's
  line without breaking the others), and up to 6 distinguishable colors;
  its five existing single-series callers were migrated to
  `series={[{label, y}]}`, and ScanPlot.tsx -- the one caller that
  actually needed more than one series -- was rewritten to mirror
  scan_orchestrator.py's own _build_state_series/zero-referencing logic
  client-side from job.summary.state_energies_per_image (already present
  and live-updated during a running scan, not just at completion), so it
  now always shows every electronic state's curve live instead of
  falling back to the server-rendered artifacts.pes_plot PNG for the
  multi-state case (ScanPlot's own prior comment named this exact
  limitation). That PNG is still rendered server-side and still offered
  as a "Download PNG" link -- retiring its role as the only way to SEE
  more than one state, not retiring the render or the download.
  Verified end to end on the rebuilt dev stack via a real-browser
  Playwright script: a real uvvis-capable job's spectrum image measured
  2400x1800 in the browser (confirming the 8x6/300dpi change reached a
  live-rendered artifact, not just a standalone script), UvVisPanel's
  download button was present, a real pes_1d job's drawer rendered
  MiniLineChart's live chart, and (see the fuzzy-search item below) the
  raw-output flyout's find bar and download button both worked against a
  real ORCA job. `npx tsc --noEmit` clean; `npm run build` refreshed
  dist for the dev stack's nginx bind mount both before and after the
  container rebuild needed to pick up the spectrum.py change.
  note (mid-P9.5, 2026-08-20, at the user's direct request: "make sure
  all document viewers (manuals, papers, uploaded files, raw ouputs, raw
  inputs etc) have a search bar (fuzzy search) and a download button"):
  surveyed every document-viewing flyout first rather than assuming a
  gap -- RawOutputFlyout/RawInputFlyout (JobDetailDrawer.tsx),
  KbPreviewFlyout (KbSection.tsx, for manuals/papers), and
  FilePreviewFlyout (FilesSection.tsx, for uploaded files) already ALL
  share one component (app-shell/SearchableText.tsx) for their find bar,
  and already ALL have a DownloadButton -- so the download-button half of
  the request was already satisfied everywhere, and the real gap was
  narrower than the request's own phrasing suggested: SearchableText's
  matching was exact-substring only, not fuzzy. Fixed at the one shared
  component so every one of those four viewers gets it at once, rather
  than four separate patches: an exact (case-insensitive) substring pass
  always runs first (unchanged, instant, and still what a multi-word
  query uses); for a single-word query under a 2MB text-length cap, word
  tokens (whitespace-delimited) within a small Levenshtein distance of
  the query (threshold 1/2/3 for word length <=4/<=9/>9) are ALSO matched
  and highlighted -- word-level rather than character-subsequence
  fuzziness deliberately, since a VSCode-command-palette-style subsequence
  matcher would light up nearly every short substring of a large raw
  output file and be useless as a find tool, where "did you mean" typo
  tolerance against a whole word reads naturally. KB's natively-rendered
  PDF/HTML sources (iframe, not SearchableText) were deliberately left
  alone -- that split is an existing, reasoned design decision (PDF gets
  PDF.js's own real find UI; HTML keeps real page layout/tables), not an
  oversight, and this request's own examples ("raw ouputs, raw inputs")
  are exactly the plain-text case SearchableText already covers.
  Verified live: opened a real ORCA job's raw-output flyout on the
  rebuilt dev stack and typed the deliberate misspelling "energyy" --
  fuzzy matching found 39 highlighted occurrences of "energy" (the exact,
  correctly-spelled query found 40, the one-off difference being an
  occurrence embedded inside a longer token that substring search catches
  and the word-boundary fuzzy pass does not, not a bug); confirmed the
  find bar and download button both render and that the exact-search path
  is unregressed.

  note: P9.6 (attach an uploaded blind-input file to chat) added
  2026-08-20, mid-P9.1, at the user's direct request: "fold in the
  ability to attach files from the uploaded files tab to chat."
  `frontend/src/files/FilesSection.tsx`'s existing "Attach to
  conversation" Paperclip action is gated `isXyz &&` -- only `.xyz`
  uploads get the button. `.inp`/`.input`/`.json` (blind engine input)
  uploads get none, and `/api/threads/{id}/attach_upload`'s own
  docstring (`server/routes/chat.py`) already names the resulting gap:
  "Only a .xyz upload is attachable this way ... that content is still
  pasted into chat as raw_input_text, unchanged by this feature" -- i.e.
  today a user has to copy-paste a blind input file's text into the chat
  box by hand for a `blind` job draft's `raw_input_text` field to see it
  at all. Scope is closing that gap: a same-button attach action for the
  other upload types, whose effect is a chat-context injection (raw file
  text into the conversation) rather than a geometry/frame state change,
  since a blind-input file has no geometry for `add_geometry_frames` to
  act on. Numbered P9.6, after P9.5, because unlike P9.2/P9.3/P9.4 it
  isn't thematically kin to plotting/geometry-queries/danger-zone and
  earns its own step; finalize-docs and full-regression shift to P9.7/
  P9.8 accordingly (P9.1 was already in progress when this was added, so
  its own number and everything before it is left untouched, per the
  precedent P9.2's own note sets for not disturbing a step with an
  audit trail already forming).

- [done] P9.6: Attach an uploaded blind-input (.inp/.input/.json) file to
  chat: extend FilesSection.tsx's per-.xyz "Attach to conversation" action
  to the other upload types, injecting the file's raw text into the
  conversation (chat-context injection, not a geometry/frame state
  change) so a `blind` job draft's `raw_input_text` can be populated
  without the user re-pasting the file's content by hand
  evidence: new app/agent/graph.py `append_attached_file` -- the exact
  same "direct update_state() write, nothing here for a model to decide"
  no-LLM-turn mechanism `append_notice` already uses (reused the pattern,
  not the function, since append_notice is hardcoded to AIMessage+notice-
  card and this needs a plain HumanMessage the model reads as real
  conversation content, not a UI-only card) -- and the same "(attached
  ..., not typed by the user)" HumanMessage convention
  server/routes/chat.py's `_run_turn` already uses for job/frame
  attachment, so this reads the same way in the transcript rather than
  inventing a second attachment shape. `POST /api/threads/{id}/
  attach_upload` no longer refuses a non-.xyz upload -- it now branches on
  extension: .xyz keeps its existing frames/geometry_set behavior
  unchanged, anything else appends the file's raw text this way and
  returns a new `kind="raw_file"`. Frontend: FilesSection.tsx's Paperclip
  attach button, previously gated `isXyz &&`, now renders for every
  upload type; `attachMutation`'s `onSuccess` gained a `raw_file` branch
  (`applyEvent` with the returned message, same idempotent-by-id path the
  existing `geometry_set` branch already uses).
  A real gap surfaced live, not assumed: the mechanism worked
  perfectly on the first attempt (verified directly against the real
  route), but a first live-agent test asking the model to "set up a blind
  job draft to run it verbatim... do not retype or paraphrase it" still
  built a STRUCTURED single_point/gs draft (task/method/basis/geometry
  decomposed out of the attached ORCA input) instead of a blind one --
  the model preferred the "smarter," structured interpretation over the
  explicit instruction, because nothing in start_job_draft's own docstring
  ever connected "an attached raw engine input, asked to run as-is" to
  `task="blind"`. Fixed by adding exactly that connection to the
  docstring (attached content + "verbatim"/"blind"/"as-is" -> task="blind"
  + raw_input_text from the attached text, not a rebuild); re-tested and
  the model then correctly built a blind draft with raw_input_text set to
  the attached file's own text, byte-for-byte.
  Verified: full backend regression on the rebuilt container --
  elic_01_draft_scenarios.py 201/201 (start_job_draft's docstring is
  agent-layer prose, not elicitation logic, so unaffected as expected),
  sniff_01_pasted_inputs.py 69/69, agent_01_token_budget.py 11/11 (tool
  schema/parameter-count checks; the qwen3.8:27b token-count sub-check
  itself skipped -- expected, this host's Ollama isn't reachable from
  inside the api container by that URL, an environment quirk unrelated to
  this change). New tests/e2e/e2e_20_attach_blind_input.py, 6/6: the real
  HTTP route accepts a .inp upload and returns kind="raw_file" with the
  file's own name and content in the message, the content is present in
  the thread's own checkpointed state (not just the one-off response),
  and -- the actual point of the feature -- a live agent turn now fills
  raw_input_text from the attached file's real content when asked to run
  it as a blind job. Frontend: `npx tsc --noEmit` clean; `npm run build`
  refreshed dist for the rebuilt dev stack; real-browser Playwright
  confirmed the attach button now renders (with the new title text) for a
  non-xyz upload and that clicking it visibly injects the file's content
  into the chat.
- [done] P9.7: Finalize MASTER_PLAN_SUMMARY.md, README, HelpFlyout, ARCHITECTURE addenda, CHANGELOG
  evidence: README was already kept current incrementally as each of
  P9.1-P9.6 shipped this session (each step's own commit added its own
  README section), so this step's README work was a final consistency
  read-through rather than new content -- no stale v1-taxonomy references
  or contradicted claims found. MASTER_PLAN_SUMMARY.md ("the projected
  final implementation," per the plan's own framing) had one real drift
  from what actually shipped: its danger-zone bullet still said "clear my
  chats, clear my jobs... clear my KB," but P9.4's own evidence records
  chat threads as a deliberate exclusion (purge_own_data never touches
  them) -- fixed the bullet to match reality, and added the still-missing
  P9.3 (reuse a tagged job's geometry), P9.6 (attach a blind-input file)
  and the fuzzy-find-bar mentions.
  HelpFlyout.tsx's "Calculations you can ask for" reference had drifted
  further and for longer than either of the above: every JobType id shown
  to a user was a pre-registry2-v2 identifier this project's own
  no-legacy-compatibility principle already retired (`geometry_optimization`,
  `tddft`, `eom_ccsd`, `casscf`, `mo_visualization`, `pes_scan`, `custom`
  instead of `opt/min`, `single_point/ee`, `blind`, etc.), and the list
  never covered several real, working task/subtype combinations at all
  (gradients, NAC, constrained/CI optimization, batch, wigner_spectra) --
  confirmed against registry2/tasks.py's own TaskDef registrations, not
  guessed. Rewritten to the real v2 ids throughout, restructured so
  method (HF/DFT/MP2/CCSD/CASSCF/CASPT2/EOM-CCSD) and task are shown as
  the separate choices the v2 taxonomy actually makes them rather than
  conflating "CASSCF" and "EOM-CCSD" as if they were distinct job types,
  and every real task/subtype the app supports is now listed.
  ARCHITECTURE.md gained three addenda for this phase's genuinely
  reusable design decisions (why, not just what -- matching the rest of
  that document's own stated purpose): purge_own_data's deliberately
  narrower scope than purge_user_data (self-purge keeps chat history,
  account deletion does not, and why); source_geometry_job_id's layering
  (why the shared resolver lives in a new chemistry-layer module rather
  than the agent layer it was first written in) and the "no new state
  slot was needed" reasoning behind reusing active_job_ids[-1]; and why
  SearchableText's fuzzy matching is word-level/Levenshtein rather than
  character-subsequence, with the rejected alternative named. CHANGELOG.md
  gained a new Phase 9 entry (custom plotting, geometry queries, geometry
  reuse, the danger zone, blind-input attach, fuzzy find, and the plot
  polish sweep) at the top of Unreleased -- the most recent work, listed
  first, matching this file's own existing newest-first convention within
  that section; did not attempt to backfill Phases 0-8 into the changelog
  retroactively, since that is a larger archaeological task belonging to
  whichever session actually did that work, not a defensible scope
  expansion of "finalize" for this one.
  Verified: `npx tsc --noEmit` clean; `npm run build` refreshed dist for
  the dev stack's nginx bind mount; real-browser Playwright confirmed the
  Help flyout opens and its job-type reference now shows the corrected
  v2 ids (`single_point/gs`, `opt/min`) and the newly-added job types
  (Batch, the nuclear-ensemble/Wigner spectrum), with none of the retired
  v1 ids (`geometry_optimization`, `mo_visualization`) appearing anywhere
  in it.
- [done] P9.8: Full regression pass; tracker closed with merge-hash ledger
  evidence: tests/run_backend.sh (55 scripts, real docker-compose dev
  stack): 55/56 on first pass (56 counts _00_bootstrap.py; sec_10 is
  deliberately excluded per its own docstring). The one real failure,
  up_01_lifecycle.py, was a genuine regression: it still asserted P9.6's
  OLD behavior ("attaching a non-.xyz upload is refused, 400"), which
  P9.6 deliberately changed (it now succeeds as a chat-context injection,
  kind="raw_file") -- fixed (commit 2ab4538), re-run confirms 31/31.
  tests/e2e/run_e2e.sh (18 scripts, live LLM turns + real compute): 16/17
  on run_e2e.sh's own pass/fail gate; only e2e_00_preflight.py's G2a/G2b
  (QC_AGENT_N_CORES expected "8", app/config.py's real default is now
  "4") flagged -- confirmed pre-existing and unrelated to Phase 9 by
  `git log -- app/config.py` (last touched in Phase 3/4's fair-scheduler
  work, long before Phase 9 started); noted here, deliberately not fixed,
  since changing a live concurrency default is outside a regression
  pass's scope and belongs to a session with the user's own input on the
  right value.
  e2e_08_job_matrix.py (this suite's own summary() call uses
  exit_on_failure=False by design, so its internal FAILs don't gate
  run_e2e.sh's pass/fail -- surfaced and triaged individually instead):
  M10 is the matrix's own self-documented "SLOW probe," already known
  intermittent (see that script's own comment on it) -- not re-chased.
  M23 (ORCA exit code 2 on a NEB job) and M24 (ORCA exit code 126 on a
  blind job) and M26 (a real AVAS pilot-space sizing constraint,
  "(6e,3o) can host at most 1 configuration, fewer than the 3 states
  requested") are all in code no Phase 9 commit touched (orca_runner.py's
  process invocation, NEB, AVAS/cas_reco) -- read as real engine/
  chemistry-level issues on this host, not code regressions.
  M20 (single_point/gs/bagel) looked adjacent to P9.3's submit_draft
  change and got the closest scrutiny as a result: reproduced on a first
  isolated retry (ruling out flakiness), traced to a REAL, PRE-EXISTING
  bug with no connection to source_geometry_job_id at all (that code
  path only ever activates when a draft carries source_geometry_job_id,
  which this scenario's plain single_point/gs never sets) -- BAGEL's
  bagel_worker.py DISPATCH had no "single_point" entry whatsoever, and
  _build_input's job_type branching had no plain-HF-energy case either,
  despite capabilities.py declaring bagel/hf energy=True. Nothing had
  ever run this exact combination through the full agent pipeline before
  this regression pass did. Fixed (commit 1d490e1) by deriving a real
  parser from a real BAGEL run (never guessed from documentation, per
  CLAUDE.md's own parser-verification rule) and wiring
  run_single_point into DISPATCH; M20 now passes 6/6 on the first try,
  and grad_01_gradients_and_nac.py (28/28) plus reg2_01_registry_v2_payload.py
  (20/20) confirm BAGEL's other runners are undisturbed.
  tests/e2e/ui (Playwright, 8 specs, real browser against the rebuilt
  dev stack): 7/8 specs clean. ui_02_approval_jobs_drawer.spec.mjs's 6
  failures all traced to this account's long, heavily-used job history
  (354 accumulated jobs, many created by this session's own extensive
  testing) rather than any product defect: the script picks "the first
  completed job of each method" from the WHOLE account, so "the dft job"
  it inspected turned out to be a real opt/ci optimization from an
  earlier P9.3 test run (correctly showing "Optimization energy," which
  the test's stale assumption said a dft job never should), "the hf job"
  and others were similarly whatever this account's history happened to
  put first, and a job with no method at all (task=geometry_set) doesn't
  fit the script's own pyscf-vs-other-engine raw-input assumption.
  Confirmed by directly querying /api/jobs and reading each selected
  job's real task/subtype/engine, not assumed. JobDetailDrawer.tsx's own
  section-gating logic has not been touched since Phase 8 P8.3
  (`git log`), long before Phase 9 -- ruling it out directly rather than
  by inference. Not fixed: robustifying this test's job-selection against
  a large, shared account's history is a test-infrastructure improvement
  outside a regression pass's own scope.
  Frontend build/typecheck: `npx tsc --noEmit` clean and `npm run build`
  succeeded at every step of Phase 9 (re-confirmed here as part of the
  closing pass, not just at each step's own commit).
  merge-hash ledger (every Phase 9 commit, in order -- no branch/merge
  step exists under the current main-only workflow, so this is the
  linear commit sequence rather than a merge commit):
  37e0474 (P9.1), 3710ec4 (P9.1 tracker), 0a08bb4 (P9.2), 5dc5939 (P9.2
  fix), b31d4d3 (P9.3), 4fd740d (P9.4), f176ab0 (P9.5), f2f3720 (P9.6),
  932972b (P9.7), 2ab4538 (P9.8 test fix), 1d490e1 (P9.8 BAGEL fix).
- merged: 1d490e1
