# Changelog

All notable changes to NexusQC are recorded here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and versions follow
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

This file is load-bearing, not decoration: `scripts/release.sh` refuses to
publish a version that has no section here, so a release cannot happen without a
note saying what changed.

## [Unreleased]

### Added

- **Standalone energy-gradient and non-adiabatic-coupling job types**
  (`single_point/grad`, `single_point/nac`), on all three engines. Gradients
  cover HF/DFT/MP2/CCSD/CASSCF on PySCF, HF/DFT/MP2/CASSCF on ORCA and
  HF/CASSCF/CASPT2 on BAGEL, including excited-state gradients on HF/DFT.
  NAC covers PySCF's SA-CASSCF, ORCA's ground-to-excited HF/DFT coupling and
  BAGEL's CASSCF/CASPT2 coupling (which also reports the transition dipole
  and oscillator strength BAGEL computes alongside it for free). The job
  drawer shows a per-atom vector table and the norm for either. ORCA refuses
  an excited-state gradient/NAC for the B88-containing functionals this app
  checks for (B3LYP, BLYP) outright — a documented `%method` LibXC rewrite
  was tried and returned a wrong ground-state energy, so there is no working
  substitute here (see the Limitations section of the README). Confirmed as
  a genuine ORCA incapability rather than a bug in this app, along with
  ORCA's separate CASSCF-NAC absence, and logged as such rather than left
  open pending further investigation.
- **`wb97x-d` (bare, no dispersion-version digit) checked explicitly given
  how commonly it's requested**, and found invalid on both engines this app
  supports, for opposite reasons: PySCF's libxc parser accepts the name but
  its TDDFT gradient driver has no implementation for it, while ORCA's own
  functional list has no entry without an explicit dispersion version and
  refuses it outright. Bare `wb97x` is confirmed working on both engines and
  is now the example this app suggests; `wb97x-d3` works on ORCA only. See
  the Limitations section of the README for the full breakdown, including
  the further ORCA keywords (`wb97x-d3bj`, `wb97x-d4`, `wb97x-v`, `wb97m-v`)
  that are real but not yet verified working on this host.
- **Registry v2 (`app/chemistry/registry2/`), dark-launched.** Replaces the
  hand-maintained per-job-type engine and parameter dictionaries with four
  factored, declarative tables and one derivation. `capabilities.py` records
  what each (engine, method) pair can compute on this host, cell by cell, with
  the evidence for every claim; `tasks.py` states which of those properties a
  task needs, and support is **derived** from the pairing rather than
  enumerated anywhere. A capability resting on `unverified` or `gap` evidence
  is unroutable, so an untested claim can never reach a user's job. Served
  alongside the existing payload under a new `v2` key on
  `GET /api/job-registry`; the v1 keys are byte-identical and the frontend is
  untouched.
- `docs/QM_CAPABILITIES.md`'s tables are now generated from that code by
  `scripts/generate_capability_docs.py`, between explicit markers so the
  hand-written analysis around them survives regeneration.
  `scripts/check_capability_matrix.py` verifies the whole cross-product
  against a golden table derived from the document's observations rather than
  from the code it checks, and fails on doc/code drift.
- **A *Troubleshoot* action on failed jobs.** A failed job now states plainly
  in the conversation that it failed and that nothing was changed or
  resubmitted. Pressing *Troubleshoot* composes one message carrying the last
  25 lines of the job's real output — read off disk by code, not chosen by the
  model — and runs it through the ordinary chat-turn path.

### Removed

- **Auto-retry.** A failed job used to silently start an agent turn that
  investigated and resubmitted a corrected job on its own initiative, capped at
  three attempts per chain. It spent someone's compute on a guess they had
  never agreed to — a CASSCF run on this hardware can be hours — and it hid the
  failure, because the user's first sign of trouble was a new approval card
  rather than a clear statement that their calculation had died. Gone with it:
  `MAX_AUTO_RETRIES`, `count_failed_in_chain()`, `submit_job`'s
  `retry_of_job_id` parameter and its carry-forward logic, the
  `_retry_count`/`_retried_from` spec bookkeeping, the "retry N of M" note on
  the approval card and the retry banner in the job drawer.

### Changed

- The 2D sketcher's lazy chunk drops from 28.7 MB (8.5 MB gzipped) to 7.6 MB
  (1.2 MB gzipped) of JS the browser must parse before the editor can paint.
  `ketcher-standalone`'s default build inlines its ~21 MB Indigo wasm binary as
  a base64 string inside the JS bundle; switching to its `dist/binaryWasm`
  entry point loads the same wasm as a real separate asset via a Web Worker
  instead (11.8 MB, fetched and compiled natively by the browser rather than
  parsed as a giant string literal). Verified live under both `vite dev` and a
  genuine static file server over the production build (nginx's own mime.types
  already serves `.wasm` correctly, confirmed against the compose image): the
  worker initializes, the `.wasm` asset returns 200 with `application/wasm`,
  Indigo actually parses a pasted SMILES correctly with no console or network
  errors, and the round trip through "Use this structure" produces the right
  molecule.
- Viewer PNG captures ("Download this view as a PNG" on the molecule and
  orbital viewers) now render at up to 3x the on-screen resolution rather than
  exactly the on-screen canvas, capped at 4096px of actual backing-store
  pixels per edge. The capture is otherwise identical — same camera, zoom,
  isovalue and background swap, and a manual rotation/pan survives it — just
  sharper, which matters once a figure lands in a paper or a slide rather than
  staying on screen.

### Fixed

- The chat no longer goes silent while the agent follows up on a job of its own
  accord. When a job finished or failed, `job_watcher` ran an
  investigate-and-retry turn that held the conversation's lock for its whole
  duration — but told the frontend nothing until it was over, so the composer
  looked idle and a message sent into it blocked with no explanation. Measured
  on a real incident: ordinary turns take 53–77 s and that one is several LLM
  round trips longer, so two prompts sent during one read as a hang that then
  "suddenly started again". The watcher now announces the turn before it starts
  and the chat shows what it is doing. The user is **not** locked out — the
  composer stays enabled and a message sent meanwhile is queued and answered
  next, which is what already happened, only now visibly.

### Added

- The chat model is kept loaded in VRAM by a background keep-warm loop
  (`QC_AGENT_MODEL_KEEPALIVE_INTERVAL`, `0` to disable), removing the cold
  reload — 11.4 s against 2.9 s warm — that Ollama's ~5-minute idle eviction
  otherwise charged to whoever sent the first message after a quiet spell. It
  calls Ollama's native API on an interval: the OpenAI-compatible `/v1` endpoint
  the app uses for chat silently ignores `keep_alive`, and eviction by another
  tenant on a shared Ollama can undo it at any time.

- Download buttons throughout: the raw input, raw output, KB source preview and
  job geometry flyouts; a PNG of any 3D viewer's **current** state — same camera,
  zoom, isovalue and frame, which no server-rendered image can reproduce; and the
  running vibrational motion as an animated PNG.
- Downloads are now named after the job rather than its id:
  `20260817_water_Freq_HF_sto-3g_ORCA_78a32a61_mode3_3840cm-1.png` instead of
  `78a32a61bab7.png`. Renaming a job renames its downloads. The date is UTC and
  the short id is retained because job labels are not unique — the same
  calculation run twice would otherwise produce two identically-named files.
  Extensions are the engine's real ones (`.inp`, `.json`, `.out`).

- A separate, destructible development stack (`docker-compose.dev.yml`,
  `scripts/dev_stack.sh`). It runs the same compose file on its own compose
  project, port and secrets, and is deliberately never published on the
  LAN address a deployment's users reach.
- `scripts/promote.sh`, the only way the production deployment moves. It refuses
  any commit without a passing verification row in `docs/deployment-ledger.md`,
  takes a backup first, and can drain running jobs (stopping admission, then
  waiting) rather than killing them.
- `scripts/check_destructive.sh`, which reports what a promotion will do before
  it does it: jobs that will be killed, columns the deployed database will
  silently not get, newly required configuration that would abort `compose up`
  after the old containers are gone, and bind mounts no file on disk would
  recreate.
- `docs/WORKFLOW.md` as the primary guide to branching, merging, pushing,
  releasing, testing and promoting.

### Changed

- `scripts/release.sh` now lists every branch not merged into `main` before
  publishing, and requires a typed confirmation to publish without them.
- `scripts/backup.sh` now backs up `docker-compose.override.yml`,
  `.deployment-role` and `.promotion-log`. The override file is untracked and is
  the only thing that bind-mounts the licensed engines, so its loss is
  unrecoverable and silent until the next container recreate — which is exactly
  what had already happened on the development host, with no copy anywhere.
- `scripts/dev_stack.sh reset` keeps `data/kb`, `data/scraped`, `data/molecules`
  and `data/bse_basis_cache`. Those are seeded content rather than test residue,
  and a reset that costs an hour of reseeding the vector store is a reset nobody
  runs. `reset --all` wipes them when the knowledge base is what changed.

### Fixed

- `POST /api/jobs/{id}/render_plot` referenced a `spec` that was never defined in
  that function, which would have been a `NameError` on every plot download.
  Found while renaming the downloads; it now reads the spec it needs.
- `api.downloadPlotPng` never appended its `<a>` to the document and revoked the
  object URL on the line after `.click()`. Both work in Chrome and are
  historically flaky elsewhere; the logic now lives once in
  `frontend/src/lib/download.ts`.
- `scripts/backup.sh` read `QC_AGENT_BACKUP_DIR` from the environment only, and
  otherwise wrote inside the repository. Both of its callers — cron and
  `promote.sh` — have nearly-empty environments, so the fallback applied: the
  first promotion would have left the production checkout dirty and every
  subsequent promotion been refused by its own clean-tree gate. Configuration is
  now read from the environment first and the deployment's `.env` second, the
  same order is applied to the Postgres user and database name, and `/backups/`
  is gitignored as a backstop.

## [1.0.0] - 2026-08-17

First public release.

### Added

- Conversational agent over PySCF, ORCA and BAGEL, with every calculation gated
  behind a structural human approval step rather than a prompt instruction.
- Job types: single-point, geometry optimisation, frequencies, combined
  optimisation + frequencies, CASSCF, CASPT2, TDDFT/TDA/CIS/TD-HF, EOM-CCSD,
  conical-intersection optimisation, potential-energy scans, NEB transition-state
  search, orbital visualisation, active-space recommendation, nuclear-ensemble
  (Wigner) absorption spectra, and raw custom ORCA/BAGEL input.
- Basis Set Exchange integration: an offline, per-engine-translated escape hatch
  for exact published basis sets, including general-contraction handling for
  BAGEL and `%basis NewGTO` generation for ORCA.
- Multi-user deployment: Postgres, Redis and nginx via Docker Compose,
  invite-only registration, per-user ownership isolation, storage quotas, an
  append-only admin audit log, and an admin console covering invites, users and
  bug reports.
- Retrieval-augmented knowledge base over engine manuals, consulted mechanically
  on every job-input generation rather than at the model's discretion.
- `scripts/check_public_safe.sh` and a pre-push hook, so host-specific paths and
  credentials cannot reach a public remote by being forgotten.

### Fixed

- Wigner sampling applied `1/sqrt(mu)` twice, making every displacement too small
  by `sqrt(mu)` — about 4% for a hydrogen-dominated mode, but a factor of 2.2 for
  a 5 amu C=O stretch and 3.4 for the heaviest modes of a twelve-atom molecule.
  The reduced-mass helper separately fabricated `mu = 1.0 amu` for every ORCA
  mode, because ORCA's printed normal modes are unit-normalised where PySCF's are
  mass-deweighted. Both are replaced by a rescaling-invariant reduced mass paired
  with an explicitly unit-normalised direction.
- `job_context_summary` omitted a completed job's own method and basis, so "use
  the same method as the attached job" was unanswerable by any tool the agent had.
- The pre-push history scan could report a pass having examined nothing, on the
  two pushes it exists to guard: a first push to a remote that has never seen the
  branch, and a force-push after a history rewrite. In both cases the revision
  range failed to resolve, the error was discarded, and an empty commit list read
  as "this push touches nothing". An unresolvable range is now a hard error, and
  the hook recognises an unknown remote tip and widens the scan to every commit
  being pushed instead of narrowing it to none.
- The same scan blocked on its own redaction placeholders once run against the
  rewritten history, and blocked permanently on regenerable test telemetry that a
  later commit had already deleted. The placeholder exemptions are narrow and
  commented; the telemetry rule now warns about history while still blocking the
  working tree, because a hygiene rule that immutable history cannot satisfy is
  one that gets bypassed along with the rules that matter.
