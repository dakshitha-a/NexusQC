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

- [todo] P2.0 — Capture a pre-rebuild checkpoint fixture (thread with a pending old-shape approval) for the P2.7 resume test
  note: moved here from Phase 0. The fixture has to come from the toolset as it stands immediately before the rebuild, so it is captured at the START of this phase. **Correction:** Phase 1 DID alter the interrupt payload — `retry_note` was removed from it with auto-retry — so the fixture must be captured against the post-Phase-1 toolset, and any approval left pending from before Phase 1 will fail to resume (its recorded `submit_job` call carries `retry_of_job_id`, which the tool no longer accepts). Wiping old threads is the intended remedy, consistent with the clean-slate decision above.
- [todo] P2.1 — registry2/elicitation.py::validate_draft (12+ scenario script)
- [todo] P2.2 — New toolset (draft tools, lookup_capabilities, consolidated plot; token-budget test; e2e_08 via drafts)
- [todo] P2.3 — TDDFT default flip (full TDDFT; ORCA %tddft RPA true; approval-card hint)
- [todo] P2.4 — Prompt rewrite ≤ 6KB
- [todo] P2.5 — Context bounding (num_ctx, mechanical trimming + digest)
- [todo] P2.6 — Taxonomy switch (v2 specs; readers via adapter; drawer keyed on task fields; jobFilename dedupe)
- [todo] P2.7 — Old-thread compatibility (dual interrupt shapes)
- [todo] P2.8 — Pasted blind input (input_sniff.py; ORCA/BAGEL only)
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
