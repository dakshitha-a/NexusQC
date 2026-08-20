# NexusQC Overhaul — Job Types, Toolchain & LangGraph Rebuild

## Context

The job-type selection per QM package (PySCF/ORCA/BAGEL) and the LangGraph
toolset are misbehaving too much on the small local models; the user calls the
current mechanisms "more inspiration than anything else" and wants a
comprehensive phased overhaul, rebuilding from scratch where necessary. The
outcome: a task-named job taxonomy (11 job types with subtypes) driven by a
verified capability matrix, an agent optimized for qwen3-coder:30b /
qwen3.8:27B (Q4_K_M), fair multi-user scheduling, file-upload geometry input,
richer per-job-type previews, and the auto-retry mechanism replaced by
user-consented troubleshooting.

## Execution model (standing, applies to every phase)

- **Phases execute strictly sequentially, directly on `main`.** Each phase:
  implement → dev-stack verification → **push to `origin`**. Branches and
  worktrees were retired for this plan on 2026-08-19 — development is serial, so
  there is nothing to isolate from, and the branch cost real time in Phase 2
  (double pushes, and worktree isolation blocking the dev-stack operations a
  phase needs). The gate is now the commit rather than the merge: commit only
  what you would deploy, because the dev stack tracks `main`. Every merge leaves the app fully working (v1→v2 switchovers
  happen *within* a phase via dark-launch-then-flip).
- **Sonnet implements; Opus advises** and runs `scripts/check_tracker.py` at
  each phase gate before the merge. Fable produced this plan.
- **One session per phase** (user-agreed): each phase runs in a fresh session
  **on `main`**, resuming from `docs/OVERHAUL_PLAN.md` + `docs/TRACKER.md` in
  the repo — never from compacted conversation history. Avoid splitting a
  session mid-phase; if unavoidable, the tracker's step granularity and the
  pushed commits keep it recoverable. A session should check for unpushed
  work before starting anything, since there is no branch on which stray
  work could be sitting.
- **Production is shut down for the duration of the overhaul** (2026-08-18, at
  the user's instruction). `docker compose down` was run in the production
  checkout; containers and the compose network are gone, while the named
  volumes (`nexusqc_prod_postgres-data`, `nexusqc_prod_redis-data`) and the
  69 MB under its `data/` were deliberately preserved — no `-v`. The user
  intends to tear it down completely and rebuild from scratch once the
  overhaul lands, so **do not promote to production, do not run
  `scripts/promote.sh`, and do not treat production breakage as a
  consideration during these phases.** Verify on the dev stack only. The
  standing dev-before-production rule resumes when the rebuild happens.
- **Phase-exit checklist** (every phase): all phase test scripts pass and are
  recorded in the tracker with evidence; dev stack boots clean + one manual
  smoke conversation; Playwright (chromium, headless) for any UI change —
  `canvas.toDataURL()` for WebGL assertions, never `page.screenshot()`;
  `docs/PARSER_GAPS.md` updated if applicable; **README + technical docs
  updated before the push** (standing repo rule); `scripts/check_tracker.py`
  passes; tracker artifact re-published; ff-merge; push.
- **Testing convention**: standalone invoke-and-print scripts,
  `tests/backend/*.py` httpx scripts, `tests/e2e/*.py` agent scripts, raw
  Playwright `.spec.mjs` — **no pytest**.
- **Parser-gap protocol** (recurring in Phases 5–8): for each ORCA/BAGEL
  datum, run a cheap real calculation (e.g. water/STO-3G) and write the parser
  against the *actual* output; PySCF from docs/docstrings/objects. Any datum
  that cannot be parsed → row in `docs/PARSER_GAPS.md` (engine, task, datum,
  excerpt needed, status); the feature ships with that datum marked "pending
  output excerpt" in the UI rather than blocking. The user will later supply
  excerpts to close rows.
- **User decision (recorded)**: **PySCF is removed from the blind/unknown
  input system.** Blind jobs accept ORCA/BAGEL text inputs only (engine must
  be user-stated). A pasted PySCF script is declined for blind execution; the
  sniffer may still recognize it and offer to build an equivalent structured
  job. No user-supplied Python ever executes.

### Decisions taken after Phase 0's findings

- **NAC follows the engines, not the brief's rule.** The brief asked for
  excited-excited-only couplings on single-reference methods, warning on
  ground↔excited. The installed engines do the opposite: ORCA's TDDFT module
  computes only ⟨GS|∂/∂R|ES⟩ and offers no excited-excited coupling, and
  PySCF's NAC support is SA-CASSCF only. Phase 5 therefore offers whatever
  each engine actually computes and warns only when a requested pair is
  genuinely unavailable, rather than refusing a combination the engine
  supports. The capability matrix is the arbiter.
- **DMRG stays in scope.** block2 0.5.3 and pyscf-forge are installed in the
  `qc-agent` environment, and the app's own `_pilot_entropies_dmrg` runs. The
  autoCAS entropy pilot keeps both `exact_fci` and `dmrg` paths. (Phase 0
  briefly recorded DMRG as unavailable; that was a probe of the wrong module —
  see QM_CAPABILITIES.md.) Note pyscf-forge did **not** add TDDFT NACs or a
  MECI optimizer; both remain absent.
- **Context window raised to 65536, and the diet still stands.** The operator
  applied `OLLAMA_CONTEXT_LENGTH=65536` on 2026-08-18; verified at
  `100% GPU` with 9,973 MiB free, and the truncation probe reaches 60,368
  prompt tokens with the system prompt intact. The fixed surface is now 22% of
  the window rather than 44%, and the truncation edge is out of reach of any
  realistic session. Phase 2's diet proceeds regardless: the agent should fit
  on any host, not only on one tuned for it. See MODEL_CONTEXT_BUDGET.md.

## Tracker (user-facing, mandatory)

- `docs/TRACKER.md` in-repo: full phase/step skeleton, status
  `todo|in-progress|done`; `done` requires an evidence field (verification
  script path + one-line observed result). Tracker edits ship in the same
  commit as the step's final code change.
- **Published artifact** mirroring the tracker (Phase 0 deliverable; URL
  handed to the user), re-rendered at every phase gate and at each step
  completion within a phase.
- `scripts/check_tracker.py`: every `done` step's evidence script exists; no
  phase marked merged without a merge commit; run at each gate.

---

## Current-state findings (from three exploration passes — reference)

### Chemistry/job system
- `app/chemistry/jobs/registry.py` (524 lines): 14 **method-named** job types
  (`single_point, geometry_optimization, frequency, opt_freq, casscf, caspt2,
  tddft, eom_ccsd, mo_visualization, pes_scan, neb_ts, custom,
  recommend_active_space, wigner_ensemble`); `default_engine()`;
  `PARAM_HELP` prose; served at `GET /api/job-registry`.
- Execution (`base.py`): JobSpec → per-engine worker subprocess (detached,
  outlives backend), atomic JSON persistence in `data/jobs/<id>/`, host-wide
  admission gate `_wait_for_resources`, orphan reconciliation, group cancel.
  Nested shapes: master fan-out (`pes_scan`, `wigner_ensemble` +
  orchestrator daemons), in-process sequential stages (`opt_freq`, `neb_ts`,
  `recommend_active_space`), retry chains.
- **Scheduling is unfair (verified)**: `ThreadPoolExecutor(MAX_CONCURRENT_JOBS)`
  FIFO (`base.py:531`); per-user caps enforced *inside* worker threads
  (`_concurrent_jobs_block_reason`), so a capped user's queued batch occupies
  pool threads spinning in `_wait_for_resources`; `submit_scan` enqueues all
  images at once → one user's batch starves everyone.
- Input generation: inline builders, no templates (`preview.py`,
  `orca_runner.build_input_text`, `bagel_runner._build_input`; PySCF preview
  is a display-only synthesized script). Edited approval text →
  `params["_raw_input"]`, used byte-for-byte.
- Keyword layers (keep): `param_normalize.py` (alias + difflib 0.75),
  `keyword_suggest.py` (difflib menus; ORCA/BAGEL pools parsed from scraped
  manuals in `data/scraped/` — pool membership is the validity oracle),
  `bse_basis.py` (offline BSE, `bse:` sentinel), `validate.py` (ORCA/BAGEL
  structural validation).
- Parsers exist for all 14 types (per-engine gaps noted in the exploration);
  ORCA/BAGEL parse wrapped in `_safe_parse`; shared `vibrations.py`,
  `ci_transitions.py`, `molden.py`, `spectrum.py` (matplotlib).
- Orbitals: molden + `orbital_table` written by most jobs; lazy cube rendering
  (`orca_plot` for ORCA, cubegen otherwise); `input.gbw` retained.
  **Cross-job orbital reuse does not exist** (biggest gap).
- Missing: gradient job (no parser anywhere), NAC (nothing), constrained opt,
  CI-opt outside BAGEL, xyz upload, arbitrary multi-geometry input, batch
  jobs, standalone interpolated-PES type (`interpolate.py` already has
  linear/LIIC(z-matrix NeRF)/IDPP(ASE) though).
- Auto-retry: `job_watcher.py` daemon injects retry notices;
  `MAX_AUTO_RETRIES=3` + `count_failed_in_chain` (`base.py`);
  `submit_job(retry_of_job_id=...)`. **`_poll_once` has no plain-failed
  branch** — removal must add one or failures go silent.

### Agent/LLM layer
- Plain ReAct loop (`graph.py`), approval = `interrupt()` inside `submit_job`;
  qwen3.8:27b via Ollama /v1, temp 0.1, `max_tokens=1024`, **no num_ctx, no
  trimming** — 22.6KB system prompt + unbounded history each iteration.
- 14 tools; `submit_job` has 35 flat optional params + ~220-line docstring
  (second prompt surface). Job-type selection purely LLM.
- Hard-won mechanics to preserve: interrupt with verbatim-spec resume (tool
  re-executes from top on resume; no network pre-interrupt), mechanical
  `_kb_context_for_job` (Chroma manual-only k=3), NotRequired state keys,
  per-thread locks, sync-def routes, never `invalidate_graph_cache` from
  tools, `_looks_fabricated` guard, `model_warmer.py` (Ollama /v1 drops
  keep_alive).
- Live bug: `tools.py:556` missing `engine` arg → every wigner prep raises
  TypeError. Stale comments graph.py:56/:328 (qwen3:30b).
- `opt_freq`/`wigner_ensemble` absent from submit_job docstring and prompts —
  model can't discover them.

### Frontend
- React 19 + Vite + Tailwind v4 + TanStack Query + Zustand + Radix; 3Dmol.js
  everywhere; Ketcher (molecule panel). No router.
- Reuse: `ExpandablePanel` (+close, `ViewerOverlay`), `FrameScrubber` /
  `FrameStepper` (keyboard scrubbing), `captureViewer.ts` (3× PNG, APNG),
  `molecule/xyz.ts` (multi-frame parse, xmol serialize), `JobDetailDrawer.tsx`
  (847 lines, ~19 conditional sections, recurses for sub-jobs),
  `JobApprovalCard.tsx` (ORCA/BAGEL editable, severity-gated warnings),
  `kb/KbSection.tsx` (pattern for file manager), `admin/DangerZoneSection`
  (typed-phrase confirm pattern), SSE (`lib/sse.ts`) + targeted polling.
- Missing: gradient/NAC sections, composer attachments, per-user danger zone,
  download buttons on `UvVisPanel`/`IrSpectrumPanel`, multi-series
  `MiniLineChart`, ensemble `GitBranch` marker; `miew` unused dep;
  `lib/jobFilename.ts` hand-synced with `naming.py`.

---

## Architecture decisions

### Registry v2 — factored declarative tables (`app/chemistry/registry2/`)
- **`MethodCaps`** keyed `(engine, method)`: frozen dataclass of *properties*
  — `energy, excited, osc_strengths, gradient("analytic"|"numerical"|None),
  excited_gradient, hessian, nac, ci_opt, constrained_opt,
  verified("run"|"manual"|"unverified"), notes, source`. Canonical methods:
  `hf, dft, mp2, ccsd, eom_ccsd, casscf, caspt2` (CIS/TDA/TDDFT stay
  `hf|dft` + `use_tda`).
- **`TaskDef`** keyed `(task, subtype)`: `single_point/{gs,ee,grad,nac}`,
  `opt/{min,constrained,ci}`, `freq`, `opt_freq`, `pes_1d`, `interp_pes`,
  `neb_ts`, `wigner_spectra`, `cas_reco/{explain,autocas,avas}`, `blind`,
  `batch`, `geometry_set` (≥3-geometry dummy job). Requirements are
  *predicates over MethodCaps*; `supports(engine, method, task, subtype) →
  SupportVerdict(supported, warnings)` is **derived, never hand-enumerated**.
- **`ParamSpec`** per task: declarative, serializable condition DSL
  (`required_when`, `warn_when`, `ask` elicitation text, `help`). Encodes NAC
  `state_pairs` (required, no default; warn single-ref GS pair), CAS params,
  NEB `preopt` (required, no silent default), **`n_states` semantics per
  method family (multireference: ground state included in nroots;
  single-reference: GS separate) encoded declaratively, not prompt prose**.
- **Routing** `route_engine(...)`: pyscf → orca → bagel preference over
  derived verdicts; hard rules on top (caspt2 → bagel always;
  casscf + want_oscillator_strengths → orca).
- **`lookup.py`**: façade over existing `keyword_suggest`/`param_normalize`/
  `bse_basis` + method/task fuzzy lookup. Backs the agent's fast-lookup tool
  and the UI via `GET /api/job-registry` v2.
- **Docs generated from code**: `scripts/generate_capability_docs.py` writes
  `docs/QM_CAPABILITIES.md` tables from `capabilities.py`;
  `scripts/check_capability_matrix.py` fails on drift or dangling refs.
- **Migration — SUPERSEDED, no adapter.** This bullet originally specified an
  `adapter.py::normalize_job_spec()` mapping legacy job types to v2 triples,
  with every reader going through it so old jobs rendered forever. **The user
  cancelled that during Phase 1 (2026-08-18): the jobs under `data/jobs/` were
  wiped and the overhaul starts from a clean slate.** With no legacy specs left
  on disk there is nothing to stay compatible with, so `adapter.py` and its
  round-trip test (P1.3) were deleted and the v2 taxonomy is the only
  taxonomy. Readers do **not** go through an adapter. Later phases must not
  reintroduce one on the strength of the wording left in Phases 2, 5, 6 and 7
  below, which predates this decision — where those steps say "adapter keys"
  or "adapter maps old …", read them as "the v2 taxonomy directly".

### Agent — keep the single ReAct loop; backend-validated job draft
- No router/elicitation graph nodes. New `NotRequired` state key
  `job_draft: dict` (last-write reducer).
- Tools (~10): `set_geometry` (merges set_molecule/set_pes_scan_endpoint +
  frame ops), `lookup_capabilities` (mechanical fast lookup over matrix +
  keyword pools — the model never answers capability questions from weights),
  `start_job_draft` / `update_job_draft` / `submit_draft`,
  `check_job_status`, `plot` (consolidates 4 plot tools + custom plotting;
  refuse-don't-fabricate), `search_knowledge_base`,
  `search_academic_literature`, `web_search`, `resolve_basis_from_bse`.
- After every draft mutation, `registry2/elicitation.py::validate_draft()`
  normalizes keywords, routes engine, checks cross-field/cross-state
  requirements, and returns `ready(preview)` or
  `incomplete(ask_user_exactly=..., options=[...])`. The model transcribes
  answers and **relays the backend's question verbatim** — it never decides
  what's missing.
- `submit_draft` keeps interrupt mechanics unchanged (KB context at finalize,
  verbatim spec resume, pre-interrupt determinism).
- Context diet: system prompt ≤ 6KB (job catalog deleted — served by
  lookup + draft errors); tool-schema token budget enforced by test; explicit
  `num_ctx`; mechanical trimming (recent window + digest line built from
  AgentState — no LLM summarization). Keep `_looks_fabricated`, locks,
  warmer, checkpointer.
- Fallback (Phase 0 spike decides): flatten `update_job_draft(name, value)`
  to single-field calls if dict-valued args prove unreliable on Q4 models.

### Blind-input sniffer — `app/chemistry/jobs/input_sniff.py`
- Pure mechanical. Detect: JSON with top-level `"bagel"` → BAGEL; `!` bang
  line / `%block…end` / `* xyz` → ORCA; `import pyscf` → PySCF
  (**classify-only → offer structured job or decline; never execute**).
- Classify to `(task, subtype, method, basis)` using scraped-manual keyword
  pools (ORCA), section titles (BAGEL: `optimize`→opt, `hessian`→freq,
  `smith`→caspt2, `forces`/`nacme`→grad/nac). Confident → offer structured
  job (gets parsing/previews); unconfident → blind job (ORCA/BAGEL only,
  user-stated engine, editable input on card, raw in/out buttons,
  troubleshoot-on-failure).
- Entry points: upload-time sniff (classification stored on file record,
  injected as synthetic message on attach) and pasted text via the draft flow.

### Fair scheduler — `app/chemistry/jobs/scheduler.py`
- Per-user FIFO queues + round-robin admission by a single dispatcher thread;
  the executor survives but **only admitted jobs enter it** — no thread held
  by queued work. `_resources_available()` (factored from
  `_wait_for_resources`, same thresholds; its 1s cpu_percent paces the loop).
  Per-user caps evaluated centrally. `MASTER_MAX_IN_FLIGHT` (generalizes
  `ENSEMBLE_MAX_IN_FLIGHT`) trickles scan/ensemble/batch sub-jobs; sub-jobs
  join their owner's queue so RR fairness handles batches.
- Preserved: orphan reconciliation (+ startup re-enqueue of on-disk `queued`
  jobs — today they die silently with the executor), cheap pre-admission
  cancel, group cancel drains queued sub-jobs, jobs outlive the backend,
  host-headroom-only throttling philosophy, ownership-before-admission.

### Failure flow (replaces auto-retry)
- New plain-failed branch in `job_watcher._poll_once`: `job_failed` SSE +
  chat notice ("Job X failed — want me to troubleshoot?") **without invoking
  the agent**. On acceptance: backend composes one synthetic HumanMessage
  that mechanically includes the **last 25 lines of raw output** + manual
  excerpts instruction → normal turn → explanation + new approval card.

---

## Phases

### Phase 0 — Verify, document, baseline (no product features)
1. **Commit this plan into the repo as `docs/OVERHAUL_PLAN.md`** (copy from
   the session plan file), then `docs/TRACKER.md` (full skeleton, update
   rules) + `scripts/check_tracker.py` + **publish tracker artifact, hand
   user the URL**. Save an auto-memory pointing future sessions at
   OVERHAUL_PLAN.md + TRACKER.md and the one-session-per-phase operating
   model, so "continue the overhaul plan" works in any fresh session.
   *Accept: check passes; artifact URL delivered; plan committed.*
2. `docs/MASTER_PLAN_SUMMARY.md` — the **projected** final implementation
   (job types, subtypes, engines, previews, tagging contract), basis for
   tutorials/README; kept current when scope shifts; finalized Phase 9.
3. ORCA verification spikes (`scripts/spikes/spike_orca_*.py`, cheap real
   runs, print parsed datum or raw block): EnGrad + `.engrad` format;
   excited-state gradient (IRoot); NAC availability/format (CIS/TDDFT NACME,
   CASSCF) in installed ORCA 6.1.1; `%geom Constraints` output; CASSCF
   MECI/CI-opt keywords; `! Opt Freq`/`! Opt NumFreq` single-input matrix;
   `%moinp` + `! MOREAD` restart incl. across method/geometry change.
4. BAGEL spikes: `forces` gradient format; `nacme` (casscf + caspt2) format;
   orbital restart (molden read vs archive save_ref/load_ref, across geometry
   change); optimize+hessian one-input; constrained opt (capability summary
   claims Cartesian freezing; current registry exploration found nothing —
   conflict to resolve).
5. PySCF spikes (docstrings + tiny in-process runs): analytic gradients per
   method incl. TDDFT ES; NAC availability in installed version (mainline vs
   pyscf-forge — shakiest claim); chkfile + `mcscf.project_init_guess` reuse
   across geometry/basis; geomeTRIC constraints; geomeTRIC MECI feasibility.
6. `docs/QM_CAPABILITIES.md` v1 — verified factored matrix, every cell
   `run|manual|unverified`, explicit diff vs
   the operator-supplied capability summary, with a "claims not confirmed"
   section. *Accept: every cell a target job type uses is run/manual or a
   named risk.*
7. `docs/PARSER_GAPS.md` skeleton.
8. Model-context spike: measure current prompt+schema tokens; confirm
   `num_ctx` takes effect through Ollama /v1 for both target models; short
   canned-conversation harness testing draft-tool-call reliability
   (dict-valued args vs flattened) on qwen3-coder:30b and qwen3.8:27b Q4_K_M.
   Record budgets Phase 2 designs to.
9. Bugfix batch: `tools.py:556` engine arg (wigner TypeError); stale
   qwen3:30b comments; `naming.py:_METHOD_LABELS` missing entries; stale
   BAGEL-freq registry comment; `ARCHITECTURE.md:1131` LIIC claim; drop
   `miew`. *Accept: wigner prep e2e passes; frontend builds.*
10. Capture a pre-rebuild checkpoint fixture (thread with pending old-shape
    approval) for Phase 2's dual-shape resume test.

### Phase 1 — Registry v2 dark launch + auto-retry removal
1. Build `app/chemistry/registry2/` (`capabilities.py` from QM_CAPABILITIES
   with provenance, `tasks.py`, `params.py`, `routing.py`, `lookup.py`).
   *Accept: `scripts/check_capability_matrix.py` — full cross-product, no
   dangling refs, verdicts match golden table.*
2. `scripts/generate_capability_docs.py`; doc/code drift fails the check.
3. ~~Adapter round-trip test.~~ **Dropped** with the adapter itself — see the
   superseded Migration bullet above. The step number is retired, not reused.
4. `server/routes/registry.py`: v2 payload alongside v1 (frontend untouched).
5. Remove auto-retry per removal map (job_watcher branches, base.py
   MAX_AUTO_RETRIES + count_failed_in_chain, tools.py retry plumbing,
   prompts, provenance display chain jobs.py:84→api.ts:64→drawer:314, delete
   `tests/e2e/e2e_12_failure_retry.py`, README/HelpFlyout/ARCHITECTURE/
   CHANGELOG copy).
6. Add plain-failed branch + troubleshoot flow (design above).
   *Accept: `tests/backend/fail_01_notice_flow.py` — broken job → notice;
   acceptance → turn containing raw tail → new approval card; declined stays
   quiet. Playwright notice spec.*
7. Failed-job notice card + Troubleshoot button (`frontend/src/chat/`).

### Phase 2 — Agent rebuild: draft workflow, taxonomy switch, context diet
1. `registry2/elicitation.py::validate_draft` (normalization via existing
   layers; routing; ParamSpec-driven asks; keyword menus reusing
   `_keyword_options_for_job` format; cross-state checks).
   *Accept: standalone script drives 12+ scenarios (every sp/opt subtype)
   empty→ready asserting exact ask-text sequence + final params.*
2. New toolset in `app/agent/tools.py` (rewrite; interrupt mechanics
   verbatim; `job_draft` state key). *Accept:
   `tests/backend/agent_01_token_budget.py` (schema+prompt under Phase 0
   budget); updated `e2e_08_job_matrix.py` reaches approval for every
   legacy-supported type via drafts.*
3. **TDDFT default flip**: `use_tda` defaults to **False** (full TDDFT);
   ORCA builder emits `%tddft RPA true` accordingly; approval card shows the
   full-TDDFT hint. *Accept: generated ORCA/PySCF ee inputs assert full
   TDDFT; card hint in Playwright spec.*
4. Prompt rewrite ≤ 6KB (catalog deleted; draft workflow ~15 lines;
   troubleshoot behavior).
5. Context bounding in `graph.py`: `num_ctx`, mechanical trimming + digest;
   keep fabrication guard/locks/warmer. *Accept: scripted 30-turn convo stays
   under num_ctx (log per-step prompt tokens); fresh-thread tool call works.*
6. Taxonomy switch: `submit_draft` writes v2 specs (+ legacy runner key via
   `adapter.runner_key()`); readers go through `normalize_job_spec`; frontend
   drawer/api types keyed on normalized task fields; registry API v2-only;
   capability display on approval card; `lib/jobFilename.ts` dedupe (stem
   served by API). *Accept: Playwright — fixture set of all 14 legacy-type
   completed jobs renders identically; new jobs render.*
7. Old-thread compatibility: `resume_turn` handles both interrupt shapes
   (test with Phase 0 fixture; accept + reject paths).
8. Pasted blind input: `input_sniff.py` + `blind` task (ORCA/BAGEL only —
   user decision; PySCF classify-only/decline). *Accept: sniffer script ≥6
   real samples per engine; pasted ORCA input yields "recognized as X —
   structured or blind?".*
9. Update e2e suite (e2e_06/07/08/11, _expected, _probes) + new
   `e2e_18_elicitation.py` (multi-turn, exact-question assertions).

### Phase 2B — One taxonomy, end to end

Not in the original plan. Added 2026-08-19, and **rescoped the same day** at
the user's direction: "the long horizon goal should be grounded in stability
through simplicity ... try not to maintain legacy and v2 architectures to do
things. try to recreate unified processes. Don't be afraid to break things.
we are rebuilding from scratch and what exists is mere inspiration."

Numbered `2B` rather than renumbering Phases 3-9, which would have touched
~30 references including a refusal message users read, a test asserting on
that text, three spike docstrings, and a `bse_basis.py` comment reading
"Phase 3: ORCA" that is not an overhaul phase at all.

**The problem is duplication, not naming.** Right now a submission is
decided twice and described twice:

- `validate_draft` (registry2) resolves the task, normalizes method and
  basis, checks required parameters, routes the engine and applies
  defaults. Then the builders in `tools.py` re-decide all of it against v1
  rules -- six `missing_required_params` calls and four `default_engine`
  calls, live in the submit path. A v1 rule can demand a parameter v2 does
  not, or route somewhere v2 would not, and the user sees a refusal *after*
  the draft said READY.
- A spec carries `task`/`subtype` **and** a v1-shaped runner key, bridged by
  `_LEGACY_JOB_TYPE` and `_EXCITED_STATE_JOB_TYPE`. The runners dispatch on
  the latter, so both vocabularies stay alive.
- The frontend keys some renderers on the runner key and others on the
  task.

An earlier note in this plan said the runner key could persist and be
retired gradually per job family across Phases 5-8. **That is superseded.**
Two mechanisms that both work is worse than one that works: the pair has to
be kept in agreement forever, and the disagreement is what bites.

1. **Registry2 decides; nothing re-decides.** Remove `missing_required_params`
   and `default_engine` from the submit path. Builders receive an
   already-validated, already-routed draft and construct only. *Accept: a
   test asserting the v1 decision functions are unreachable from
   `submit_draft`.*
2. **Runners dispatch on the v2 task.** `run_*` entry points selected from
   `(task, subtype, method)` rather than a job-type string. Deletes
   `_LEGACY_JOB_TYPE`, `_EXCITED_STATE_JOB_TYPE` and the `method`-as-job-type
   reading everywhere. This is the breaking change the rescope calls for,
   and it is what makes Phases 5-8 add a family once instead of twice.
3. **Delete `app/chemistry/jobs/registry.py`.** Its decision tables die with
   step 1; `PARAM_HELP` already exists as `ParamSpec.help`. Nothing should
   import it afterwards.
4. **`spec.method` becomes the level of theory**, matching what the word
   means everywhere else in v2, with the task carried by `task`/`subtype`.
   On-disk specs are rewritten or discarded -- there is no compatibility
   burden, per the clean-slate decision.
5. **Frontend keyed on the task, once.** `excitedState.ts`,
   `ExcitedStateTable`, `JobsPanel` and the drawer read `task`/`subtype`
   plus `params.method`; no renderer keys on a runner key. *Accept:
   Playwright renders one completed job per task family.*
6. **Tests speak the spec.** `_probes.py`'s `MATRIX` and
   `EXPECTED_SUMMARY_KEYS` keyed on v2 `(task, subtype, method)`.
7. **Regression pass**: backend suite, job matrix, Playwright approval and
   drawer specs.

### Phase 3 — Geometry input & uploaded-file manager
1. `server/routes/uploads.py` (plain `def`): `.xyz/.inp/.input/.json` →
   `data/uploads/<owner>/`, quota-counted, server-generated names +
   original_name, list/delete/clear-all, ownership-scoped.
2. Backend multi-geometry xyz parser (mirrors `frontend/src/molecule/xyz.ts`
   semantics) + upload-time sniff stored on file record.
3. Semantics: attach injects synthetic message (geometry count or sniff
   classification). 1 geom → active frame; 2 → two frames (interp/NEB
   endpoints); ≥3 → synthetic completed `geometry_set` job (no engine/worker,
   terminal at creation), cycling viewer, per-geometry taggable, user
   informed in chat. *Accept: `tests/backend/up_01_lifecycle.py`; e2e attach
   3-frame xyz → geometry_set exists → tag frame 2 into a draft.*
4. Frontend: composer `+` button + drag-drop; `frontend/src/files/
   FilesSection.tsx` below KB (pattern: KbSection) with view/delete/clear-all;
   geometry_set drawer rendering (reuse FrameScrubber/MoleculePanel).
   *Accept: Playwright uploads spec — upload, cycle frames
   (canvas.toDataURL diff), delete, clear-all confirmation.*

### Phase 4 — Fair scheduler
1. Extract `_resources_available()` from `_wait_for_resources` (identical
   thresholds).
2. `app/chemistry/jobs/scheduler.py` (queues, RR, condition, dispatcher
   thread); `submit()` enqueues (ownership ordering preserved); completion
   callback; `MASTER_MAX_IN_FLIGHT` in `app/config.py`.
3. Orchestrators trickle-enqueue (scans currently enqueue all images — the
   verified starvation vector).
4. Cancel pre-admission path; startup re-enqueue of on-disk `queued` jobs;
   group cancel drains queued sub-jobs.
5. Tests: update `perf_03_jobmanager_cap_enforcement.py`; new
   `perf_04_fair_scheduling.py` (user A 40-sub-job master + user B one job →
   B admitted within one rotation; active threads == running jobs);
   `perf_05_restart_queue.py`; orphan/cancel regressions unchanged.
   *Accept: all green; manual two-user dev-stack run shows interleaving.*
6. Keep dev/production quota+concurrency config identical (production is
   source of truth) when touching config.
7. Playwright suite hygiene (appended here because Phase 4 is the last
   remaining phase whose own accept criteria are all `tests/backend/`
   scripts — Phases 5-9 each carry a Playwright criterion, so this is the
   cheapest window that still lands before the suite needs to be trusted at
   exit-code granularity): fix `tests/frontend/_helpers.mjs`'s stale
   `BASE_URL` fallback (`8443`, the LAN/tailnet-facing port) to `8444`
   (`scripts/dev_stack.sh`'s actual loopback default, `QC_AGENT_DEV_PORT`),
   and retarget `draft_01_approval_card.spec.mjs` off its own hardcoded
   `:5173` literal onto the shared `BASE_URL`, adding register+login (the
   docker stack requires auth; the spec's current bare-mode assumption
   doesn't). Closes the last outstanding gap from P2B.7's suite pass.
   **Open question, not settled by this step:** the bare `:5173`+`:8000`
   dev-mode SSE drop ("Lost connection to the server — reconnecting…")
   P2B.7 documented is unresolved — confirmed healthy by `curl` on both
   ports, but the browser's `EventSource` drops shortly after the first
   post. `npm run dev` + bare `server.main` is a first-class documented
   run mode (CLAUDE.md), so before treating the retarget as closing this
   rather than merely reclassifying it, check by hand: bare backend +
   `npm run dev`, ordinary browser, send one message, watch. If a human
   sees the same drop, it is a product defect in the local-dev path and
   needs its own tracker line, not this one.
8. `fail_01_notice_card.spec.mjs`: rewrite self-contained on the P3.4
   `up_02_files_and_attach.spec.mjs` pattern — register+login, seed its own
   failed job (lift the existing recipe from
   `tests/backend/fail_01_notice_flow.py`, which already produces "a real
   failed PySCF job"), find its own thread by the label it creates — instead
   of requiring three externally-injected env vars
   (`QC_AGENT_TEST_THREAD_ID`/`_JOB_ID`/`_THREAD_LABEL`) that nothing in the
   repo currently provides. Preserve the post-reload assertion: the spec's
   own header calls the reload the load-bearing check (a notice that only
   lived in an SSE event would be invisible to exactly the user it's for).
9. `bug_report_attachments` schema gap (found at the Phase 3 gate via
   `check_destructive.sh` against production's actual deployed commit;
   unrelated to Phase 3 or 4's own feature work — the table was added in
   `885abfb`, before either): add the missing
   `ALTER TABLE ... ADD COLUMN IF NOT EXISTS` entries to `app/auth/db.py`'s
   idempotent-migrations block so production's already-deployed database
   receives the columns that a `CREATE TABLE IF NOT EXISTS` body alone never
   reaches on an existing installation. *Accept (7-9):
   `npm --prefix frontend run test:e2e` reports every spec passing with no
   env vars set (today: 7/9, the two failures being exactly the specs steps
   7-8 fix); `scripts/check_destructive.sh --from <production's deployed
   commit> --to HEAD` reports no `[destructive]` finding for
   `bug_report_attachments`.*

### Phase 5 — Single-point family completion: gradients + NAC
1. Registry2 entries `sp/grad`, `sp/nac` (ParamSpecs: `target_states` default
   GS; `state_pairs` required-no-default + single-ref GS-pair warning;
   analytic-default / numerical-warn from MethodCaps).
2. Runners: `run_gradient` (pyscf analytic per caps + numerical fallback with
   warning; orca `! EnGrad`/IRoot parsing `.engrad` + stdout per spike; bagel
   `forces`); `run_nac` per Phase 0 verdicts (bagel `nacme` casscf/caspt2
   certain; orca per spike; pyscf per spike or mechanical denial).
   Summary: per-state matrix + norm.
3. Worker dispatch + adapter keys; `summarize.py` exposes matrix+norm as GFM
   table (tagging contract).
4. Frontend: `GradientSection`/`NacSection` in drawer (matrix + norm per
   state, download); approval-card display.
5. Tests: per-engine cheap-run scripts asserting parsed values; pyscf
   analytic vs central-difference cross-check; e2e "gradient of S1 water" →
   elicitation → approval → parsed result; Playwright drawer check.
   *Accept: all engine grad paths verified or gap-listed; NAC ≥1 engine
   end-to-end; PARSER_GAPS.md updated.*

### Phase 6 — Optimization family completion
1. `opt/constrained`: pyscf (geomeTRIC constraints), orca (`%geom
   Constraints`); bagel per Phase 0 verdict (likely mechanical denial +
   recommendation). Constraint ParamSpec (bond/angle/dihedral, 1-based).
2. `opt/ci`: bagel kept (adapter rename); orca CASSCF CI-opt if verified;
   pyscf MECI if feasible, else documented denial. `state_pairs` ParamSpec
   shared with NAC (excited-only warning for single-ref).
3. `opt/min` polish: ES `target_state` across engines per caps;
   numerical-gradient warning on approval card (from SupportVerdict).
4. `opt_freq`: single-input orca/bagel where confirmed; pyscf stays two
   sequential stages with concatenated approval card + nested view (verify
   combined preview).
5. Tests: per-subtype cheap run on ≥1 engine; denial-path scripts assert
   exact recommendation text; e2e constrained-opt conversation; Playwright
   drawer. *Accept: every subtype runs end-to-end or produces its designed
   denial; capability doc regenerated.*

### Phase 7 — PES family, batch, nested-preview performance
1. `pes_1d` split from legacy pes_scan coordinate mode (adapter maps old
   jobs); bagel request → mechanical denial + interp_pes recommendation.
2. Standalone `interp_pes` (licc→linear, liic, idpp default; 8 images; two
   frames required): approval card lays out steps (alignment → interpolation
   → per-image sp) + **editable input template with cascade** (template
   stored once on master; per-image inputs generated by geometry substitution;
   template validated). Atom-order mismatch: warn + best-effort reorder
   (element-wise matching helper) before interpolation; LIIC z-matrix
   matching per `interpolate.py`.
3. Children pagination: `GET /api/jobs/{id}/children` offset/limit +
   summary-only rows; drawer + master viewers fetch windowed; FrameScrubber
   drives lazy frame loads; polling cost bounded for 500-sub-job masters.
4. `batch`: master task over tagged geometries or a geometry_set × tasks 1–6;
   fan-out via scheduler trickle; nested previews reuse each subtype's drawer
   sections (drawer already recurses); input xyz via tagging only.
5. Tests: synthetic 200-child fixture → Playwright drawer-open latency budget
   + lazy scrub; interp_pes cascade-edit e2e (edit template → all images
   reflect it, geometry differs); batch of 3×sp end-to-end; atom-reorder unit
   script; NEB regression (drawer + plot).

### Phase 8 — CAS workflows, orbital reuse, ensemble spectra
1. **Cross-job orbital reuse** (flagship): `initial_orbitals_job_id`
   ParamSpec on CAS-family drafts (tag-driven); ORCA copy source `.gbw` +
   `%moinp`/`! MOREAD`; BAGEL molden/archive per spike; PySCF chkfile +
   `mcscf.project_init_guess`. Card names source job; summary records
   provenance. *Accept: per-engine script — CASSCF from prior job's orbitals
   runs and records reuse; pyscf asserts macro-iteration reduction; orca/
   bagel at minimum assert orbitals consumed (log evidence) or gap-listed.*
2. `cas_reco` overhaul: subtypes `explain` (dialogue via draft elicitation),
   `autocas` (entanglement-based, default when basis + n_states given —
   extend existing entropy/plateau pipeline + DMRG pilot), `avas` (default
   otherwise). After recommendation → backend auto-composes CASSCF-ee draft
   (approval card) so user inspects orbitals; summary inferred from results.
   **The auto-composed CASSCF-ee draft always asks the user for its own
   `n_states` and `basis`, never inherits or silently defaults them from the
   recommendation step's own values** — the recommendation's basis/n_states
   govern the screening calculation only (autocas's entanglement scan,
   avas's AO projection), a different, usually cheaper computation than the
   final CASSCF the user actually wants run, so the two must not be
   conflated even when the numbers happen to match.
3. `wigner_spectra` through drafts (tagged-freq source); **cap raised
   250→500, default 50** (touch `tools.py` ceiling + wave dispatch); new
   endpoint serving pooled raw transitions; frontend **live broadening
   slider** re-broadening client-side (extend existing gaussian machinery —
   no network per slider move); verify nested previews against Phase 7
   pagination. *Accept: Playwright slider spec asserts no network on move
   (request interception); ensemble regression e2e; 500-sample cap script.*

### Phase 9 — Custom plotting, geometric-parameter queries, danger zone, polish, final docs
1. Custom plotting: `plot(kind="custom", spec=...)` — declarative series from
   tagged jobs' parsed summaries (field paths, labels, style), matplotlib
   server render per `spectrum.py` conventions, refuse-don't-fabricate;
   `lookup_capabilities` exposes plottable fields per task. *Accept: e2e
   "plot S1 energies of three tagged jobs vs bond length, log y" renders;
   unsupported field → clean refusal.*
2. Geometric-parameter queries: a new tool that answers "what's the C4-C6
   bond length" / "the angle between atoms 1, 2 and 3" / "the C7-C8-C9-C10
   dihedral" against whatever the user has tagged — a completed job (its
   `optimized_molecule` if the job produced one, else its input `molecule`)
   or a molecule frame from the instrument panel (the frame-tagging
   mechanism Phase 3 already built). The model parses free text, including
   several requests in one sentence, into the same `{type: "bond"|"angle"|
   "dihedral", atoms: [...]}` shape `opt/constrained`'s `constraints`
   ParamSpec already uses (2/3/4 1-based atom indices) — one validation
   path, one atom-index convention, reused rather than re-invented; an
   out-of-range or malformed index is refused with the same message
   P2.9's scan-draft-shape fix already established, not a crash. The
   actual math reuses `app/chemistry/zmatrix.py`'s existing `_distance`/
   `_angle_deg`/`_dihedral_deg` primitives (already used internally for
   z-matrix construction) rather than re-deriving bond/angle/dihedral
   formulas a second time.

   A single tagged geometry returns a table: one row per requested
   parameter, the atom indices, the value, and its unit (Å for a bond,
   degrees for an angle/dihedral). A tagged `pes_1d`/`interp_pes` master or
   a multi-frame `geometry_set` — every case with an inherent ORDER (scan
   coordinate, path image index) worth seeing rather than collapsing —
   **also returns a table**, one row per child point/image (ordered by
   scan coordinate/image index) and one column per requested parameter,
   so a trend along the path is visible rather than discarded. Only a
   tagged `batch` or `wigner_spectra` master — an unordered collection or
   a statistical ensemble, where the distribution is the point, not any
   one member — returns **one histogram per requested parameter**,
   computed across every child geometry. Either shape reuses Phase 7's
   paginated child access (P7.3) rather than fetching every child at once,
   and the existing plot/`PLOT_ARTIFACT` rendering convention (for the
   histogram case) or the same table rendering the single-geometry case
   uses (for the ordered case), so this is a new query surface over
   infrastructure Phase 7 and P9.1 already built, not a third rendering
   path. *Accept: e2e "what's the O-H1 bond length in
   [tagged job]" returns a one-row table with the right value against a
   completed job with a known geometry; "the C-C bond length along [tagged
   pes_1d scan]" returns a table with one ordered row per scan point, not
   a histogram; "histogram the C-C-C angle across [tagged wigner_spectra
   ensemble]" returns a real histogram with one sample per child job;
   multiple parameters in one request each get their own
   table column/histogram; an out-of-range atom index is refused, not
   fabricated.*
3. Per-user danger zone in `AccountFlyout.tsx`: clear-my-chats /
   clear-my-jobs (cancel running first — account-deletion precedent) /
   clear-my-KB-except-seeded; typed-phrase confirmations; danger styling per
   `admin/DangerZoneSection`; backend self-scoped purge routes (plain `def`,
   ownership-checked). *Accept: `tests/backend/dz_01_self_purge.py` — strict
   self-scoping, seeded manuals survive, running job cancelled; Playwright
   confirmation spec.*
4. UI polish sweep: download buttons on `UvVisPanel`/`IrSpectrumPanel`;
   symmetric plot downloads (8x6 high-res PNG everywhere); ensemble
   `GitBranch` marker; `MiniLineChart` multi-series + legend (retire now-
   redundant server PNGs); **MO viewer caps unoccupied orbitals at 20**
   (backend orbital_table + drawer pruning).
5. Finalize `docs/MASTER_PLAN_SUMMARY.md` from shipped state; README +
   HelpFlyout refresh; ARCHITECTURE.md addenda (registry2, scheduler, draft
   agent); CHANGELOG.
6. Full regression pass: entire tests/e2e + tests/backend + Playwright;
   tracker closed with merge-hash ledger.

---

## Risks / unknowns (Phase 0 resolves)
1. PySCF NAC availability (mainline vs pyscf-forge) — may change sp/nac
   routing.
2. BAGEL constrained opt — capability summary vs registry exploration
   conflict.
3. ORCA NAC scope + output format in installed 6.1.1 (never parsed here).
4. ORCA CASSCF MECI/CI-opt keyword surface — decides Phase 6 scope.
5. PySCF geomeTRIC MECI feasibility (depends on 1).
6. Orbital-restart mechanics per engine (dimension-mismatch behavior across
   method/basis/geometry drift) — decides Phase 8 flagship design.
7. `opt_freq` single-input support matrix (BAGEL opt+hessian structurally
   plausible, not convergence-verified on this host — see CLAUDE.local BAGEL
   instability note; verify structure, don't block on convergence).
8. Small-model draft-tool reliability (dict args vs flattened single-field).
9. `num_ctx` actually honored through Ollama /v1 (repo precedent: keep_alive
   silently dropped).
10. BAGEL CASPT2 `nacme` output format — high parser-gap likelihood.
11. Old-thread migration — pre-rebuild checkpoint fixture captured Phase 0.
12. Atom-reorder for interp_pes on symmetric molecules — best-effort with
    explicit failure messaging.
13. Scheduler × quota interplay — the ~4s quota pass in `submit()` moves to
    the enqueue path; verify it doesn't serialize submissions (may move to
    dispatcher thread).

## Verification (overall)
- Every phase gate: full phase-exit checklist above (tests + dev stack +
  Playwright + docs/README + tracker check + artifact re-publish + ff-merge +
  push).
- Chemistry validation: cheap real calculations per engine per job type
  (water/STO-3G class), parsed values asserted against actual output.
- End state: full e2e + backend + Playwright suites green; QM_CAPABILITIES
  generated-from-code with no drift; PARSER_GAPS.md enumerates every
  unparsed datum for the user's excerpt pass; MASTER_PLAN_SUMMARY.md final.

## Deliverable documents
- `docs/QM_CAPABILITIES.md` — verified, generated from code (Phase 0 v1,
  Phase 1 generated).
- `docs/PARSER_GAPS.md` — living list for the user's excerpt pass.
- `docs/MASTER_PLAN_SUMMARY.md` — projected implementation (Phase 0), kept
  current, finalized Phase 9.
- `docs/TRACKER.md` + published tracker artifact (URL to user, re-rendered
  every gate).
