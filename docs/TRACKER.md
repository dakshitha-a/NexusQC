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
- [todo] P2.6 — Taxonomy switch (v2 specs; readers keyed on task fields; drawer keyed on task fields; jobFilename dedupe)
  standing note, not work for this step: `ParamSpec.to_dict()` ships `applies_when`
  alongside `required_when`. There is **no condition evaluator in `frontend/src/` at
  all** (grepped: no `required_when`, no `warn_when`), so nothing is out of sync and
  nothing here needs building. *If* one is ever written, it must evaluate
  `applies_when` too, or the card will render `isoval` and `use_tda` exactly where
  P2.1 stopped the backend from doing so.
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
- [todo] P2.9 — e2e suite update + e2e_18_elicitation.py
- merged: —

## Phase 3 — Geometry input & uploaded-file manager

- [todo] P3.1 — server/routes/uploads.py (lifecycle, quota, ownership)
- [todo] P3.2 — Backend multi-geometry xyz parser + upload-time sniff
- [todo] P3.3 — Attach semantics (1/2/≥3 geometries; geometry_set job; tests/backend/up_01_lifecycle.py)
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
