# Active Tracker: clearing the backlog

Everything that was open in [`BACKLOG.md`](BACKLOG.md), as one plan. Most of
it came out of the manuscript evaluation battery; the rest had been carried
forward for a while with nobody owning it. The backlog's Open section is now
empty by design -- work from here, and put anything new that is found along
the way back into the backlog rather than growing this plan sideways.

Phases 1 to 3 are the battery's findings, Phase 2B is the audit one of those
findings provoked, Phase 4 is the deployment surface nobody had ever
exercised, and phases 5 and 6 are the older carried-forward items. Phase 7
closes the battery out and runs last.

The battery itself is closed and archived at
[`trackers/2026-08-manuscript-evaluation-battery.md`](trackers/2026-08-manuscript-evaluation-battery.md).
Its results are in `rsc_digital_discovery/evaluation/summary.md`, and the
score sheet for every trial named below is in that directory's `results/`.

**Why none of this was fixed while the battery ran.** Changing the system
under test mid-run makes the trials on either side of the change
incomparable. So each item was diagnosed, reproduced, written up with its
evidence, and deliberately left alone.

The plan was that Phase 7 would then re-run the affected trials, turning that
discipline back into a result. It did not work out that way, and the reason is
worth carrying forward: the battery kept finding defects in its own task cards
rather than in the app -- four of them -- so each re-run attempt was started,
interrupted by a card fix, and restarted. Phase 7 now ends at the rebuild, and
the next run waits on an audit of every card against the app's real
capabilities. See P7.1/P7.2 below for what that means in practice.

## How tracking works here

Development is linear, so there is never a reason to have two trackers open
at once. Each plan, feature or non-trivial request gets its own tracker, this
file is whichever one is currently in motion, and when its plan is finished
the file is closed out and moved to [`trackers/`](trackers/), then a fresh one
starts here for whatever comes next.

Closed trackers are kept, never deleted. They are the audit trail for why the
code looks the way it does, and code comments cite them by path.

A step is `todo`, `in-progress` or `done`. A `done` step carries an evidence
line naming a script or command that a reader can run, and
`scripts/check_tracker.py` verifies the named path really exists. A phase
records its merge hash only once every step in it is done.

## What is deliberately NOT here

**The small models failing is a result, not a defect.** Condition G's 8B arm
scored 1 of 48 and the 14B arm 32 of 60, against 55 of 60 for the deployed
27B. That is the expected shape and the point of running the sweep; it needs
documenting (Phase 3), not fixing. Do not open work to make an 8B model pass.

## Phase 1: the three that defeat the approval card

Each lets a card promise something that cannot happen, which is the one
failure mode the whole approval design exists to prevent. Cheapest first.

- [done] P1.1: normalise the engine name at the registry boundary
  evidence: app/chemistry/registry2/capabilities.py adds canonical_engine, applied in supports, get_caps, methods_for_engine, describe_engine, capability_answer and route_engine; ORCA/Orca/' BAGEL ' all resolve and an unknown name still reports the caller's spelling
  `registry2.tasks.supports("ORCA", ...)` answers `Unknown engine 'ORCA'.`
  while `"orca"` answers supported, and `capability_answer` echoes the
  caller's spelling back rather than normalising. The model writes `ORCA` and
  `BAGEL` naturally. Four sightings in the battery: three cost a wasted tool
  round-trip ("The engine name needs to be lowercase. Let me fix that."), and
  the fourth cost the job. Asked for a CASSCF excited-state job on BAGEL, the
  agent answered "BAGEL cannot run this job here -- the engine name isn't
  recognized in this deployment. Would you like to run it on PySCF or ORCA
  instead?" and raised no card, having just run three BAGEL CASSCF jobs to
  completion minutes earlier. Lower-case at the boundary, the way the 1-based
  atom numbering conversion happens at the RDKit boundary rather than in every
  caller. Affected trials: A-18 t1/t3, B-10 t2, A-15 t1.
- [done] P1.2: refuse a CASPT2 request with no virtual space to correlate into
  evidence: app/chemistry/jobs/validate.py adds caspt2_virtual_space_problem, called from tools.py before the card; water/STO-3G CAS(4,4) is refused with the arithmetic shown, cc-pVDZ passes
  Water in STO-3G is 7 basis functions; CAS(4,4) with 3 closed orbitals uses
  all 7. CASPT2 is a second-order correction into the virtual space, so with
  none left the amplitude equations are empty and BAGEL dies inside LAPACK
  (`Parameter 9 was incorrect on entry to cblas_dgemm`, then
  `dsyev/pdsyevd failed in Matrix`). The app builds that input, cards it,
  submits it, and lets the engine crash. `nclosed + nact` against the basis
  size is already known at input-build time in `bagel_runner._build_input`,
  and the same arithmetic applies to the other multireference engines.
- [done] P1.3: stop `single_point` promising orbital cubes it never rendered
  evidence: app/chemistry/registry2/params.py -- both specs removed and added to RETIRED_PARAMS, which elicitation.normalize_draft strips, so a model writing the key cannot put it back on the card

  Resolved by removing the promise rather than implementing it: orbital
  viewing is a presentation of a job that has already run. The lazy route
  POST /api/jobs/{id}/orbitals/{index}/cube already renders one orbital on
  first click and caches it into result.json's artifacts.cubes, works from a
  molden artifact or ORCA's retained input.gbw, and both are produced by an
  ordinary single point. Verified during this phase that a re-clicked orbital
  is a cache hit, not a re-render. The legacy mo_visualization runner is left
  in place -- nothing routes to it, and deleting it would buy nothing.
  `params_for('single_point', 'gs')` includes `orbital_indices` and `isoval`,
  and `registry2/tasks.py` explains why there is deliberately no `mo_viz`
  task. But `dispatch.runner_for` sends the spec to the `single_point` runner,
  and neither `orca_runner.run_single_point` nor
  `pyscf_runner.run_single_point` does anything with it -- PySCF's only
  mention writes a comment into the generated input. Cubes come solely from
  the legacy `mo_visualization` runner, which v2 dispatch never reaches. A
  user can ask for cube files, watch the card show `orbital_indices: [4, 5]`,
  approve, and get a job with no cube in it. Leaving the parameter inert is
  the one option that should be off the table, since the card promises it.

## Phase 2: honesty of what the app reports

- [done] P2.1: attribute a BAGEL crash to the engine, not the parser
  evidence: app/chemistry/jobs/bagel_runner.py adds _engine_exception, consulted first by _safe_parse; the crashed A-19 output now reports "dsyev/pdsyevd failed in Matrix" as BAGEL's own failure, and the healthy R-6 output still reports nothing
  `bagel_runner._safe_parse` wraps any parsing exception in "BAGEL ran to
  completion but the '<job_type>' output parser could not find the expected
  results", and suggests a hand-edited input as the likely cause. When BAGEL
  has died, that message is wrong in both halves and sends whoever reads it to
  the wrong place -- as it did during the battery, for some time. Scan for
  BAGEL's own `ERROR: EXCEPTION RAISED` line first and say so when it is
  there. The underlying MKL instability on this host is environmental and not
  this project's to fix; the misattribution is.
- [done] P2.2: show defaulted-but-consequential parameters on the approval card
  evidence: app/agent/tools.py adds `applied_defaults` to the job_approval
  interrupt payload, and frontend/src/approvals/JobApprovalCard.tsx renders it
  as its own block -- "You did not specify these, so they take their
  defaults" -- with those keys filtered out of the ordinary parameter row so a
  value nobody chose is never shown as one that was.

  Much smaller than budgeted, because the hard part already existed:
  `validate_draft` has always computed `applied_defaults` and has always told
  the *model* about it in a ToolMessage. Only the card never saw it. That is
  worth noticing in itself -- the information needed to prevent three of this
  session's findings was being computed and then dropped one layer short of
  the person it was for.

  **This covers the `use_tda` half of the item; the `-D3` half is P2C.**
  A request for "B3LYP-D3" reaches the card as `functional: "B3LYP D3"`, which
  is not a default at all -- it is the user's own string -- so marking
  defaults cannot surface it. Split out and fixed separately; see Phase 2C.

  **A correction, because this session asserted the opposite repeatedly.**
  It was claimed here and in BACKLOG.md that ORCA silently resolves a bare D3
  as D3(zero) rather than D3BJ. That is wrong. The ORCA manual: "The D3
  correction can be invoked by the !D3 keyword that will automatically make
  use of the default Becke-Johnson damping and is thus equivalent to !D3BJ."
  `tests/backend/dft_01_functional_resolution.py` had said so in a comment for
  as long as it has existed. The defect was real but smaller and different
  from the one described -- see Phase 2C.

- [done] P2.3: stop the model inventing scan atom numbers
  evidence: app/chemistry/registry2/params.py (the `coordinate` help) and app/agent/tools.py (update_job_draft's docstring) both now forbid it, on the same footing and for the same stated reason as active_space_orbital_indices
  "Scan a bond in water ... from 0.8 to 1.2 angstrom, 5 points" produced a
  card carrying `coordinate: {atoms: [1, 2], type: bond}` in two of three
  trials. `coordinate` is `required_when: ALWAYS`, so the elicitation table is
  right and the model fills it in anyway. Consider forbidding it in
  `update_job_draft`'s docstring the way inventing an
  `active_space_orbital_indices` list is already forbidden.
- [done] P2.4: end the turn after submitting instead of polling
  evidence: check_job_status's docstring in app/agent/tools.py now says to call it once and end the turn, naming the observed fifteen-message wall and the fact that the watcher starts a new turn by itself
  On a job of more than a few seconds the model calls `check_job_status` in a
  loop within the same turn, narrating each one: fifteen consecutive "Still
  running. Let me check again." messages in one A-12 turn. Nothing breaks, but
  it burns model time on a system whose asynchronous design exists so nobody
  has to wait, and `job_watcher` already runs a follow-up turn the moment the
  job finishes. Check whether `check_job_status`'s docstring invites it.
- [done] P2.5: gate the XMS rotation on more than one state
  evidence: app/chemistry/jobs/bagel_runner.py; a generated caspt2 input carries ms/xms false at n_states=1 and true at n_states=3. Note this changes the numbers a single-state CASPT2 returns -- they are now unrotated, which is correct, and A-19's re-run value will differ from its pre-fix one.
  `bagel_runner._build_input` sets `ms: True, xms: True` unconditionally, so a
  ground-state-only CASPT2 requests an XMS rotation of a 1x1 problem. Tidiness
  rather than a defect -- it was tested during the battery as a suspected
  crash trigger and cleared -- but a reader of the generated input should not
  have to work out that it is harmless.

## Phase 2B: every required parameter, not one at a time

Opened 2026-08-25, mid-re-run, because the same defect surfaced a second
time. P2.3 stopped the model inventing a scan coordinate; B-05 t3 then showed
it inventing `n_states: 5` for a request that named no state count. Two by
accident is enough to look deliberately.

**The audit:** 15 of the 16 `required_when` parameters had no guard at all.
Only `coordinate` did, because it had just been fixed. So the fix could not
be another line of prose in one more `help` string -- that approach was
already failing at a rate of one parameter per discovery.

- [done] P2B.1: one rule in `update_job_draft`, covering every required field
  evidence: app/agent/tools.py states it once, in the docstring the model
  reads on every call: write what the user said, never what you would have
  chosen, for every required field without exception -- and says why, which
  is that a value you supplied and a value they chose are indistinguishable
  on the approval card, so a guess is not a correctable default but a
  different calculation carrying their approval.
- [done] P2B.2: guard the parameters most likely to be invented, at the point of use
  evidence: app/chemistry/registry2/params.py now carries an explicit
  prohibition on method, basis, functional, n_states, active_electrons,
  active_orbitals, coordinate, scan_range, n_points, n_samples, constraints,
  target_state and preopt -- thirteen of sixteen. The remaining three
  (state_pairs, target_state_2, and the job-id and blind-input references)
  are covered by the docstring rule alone: a fabricated job id or input file
  fails immediately rather than silently running something else, which is a
  different and much less dangerous failure.
- [done] P2B.3: the mechanical backstop to Phase 2B's prose
  evidence: the same change as P2.2 -- app/agent/tools.py and
  frontend/src/approvals/JobApprovalCard.tsx.

  Phase 2B guarded thirteen parameters with instructions telling the model not
  to invent them, and prose had already failed twice at exactly that. This is
  the half that does not depend on the model complying: whatever it writes, a
  value the app supplied is now labelled as one on the card the human reads.
  The prohibition and the disclosure are worth having together -- the first
  reduces how often it happens, the second means it is visible when it does.

## Phase 2C: dispersion, written out rather than aliased

Split from P2.2 once the ORCA manual was actually read. The defect there was
described as ORCA silently choosing zero damping; the truth is that `!D3` is a
documented alias for `!D3BJ`, and the app was passing the alias through
unresolved. Smaller than claimed, and still worth fixing: an approval card
reading `B3LYP D3` does not tell the person approving it which damping they
are getting, and someone who wanted the original zero-damping form had no
signal they had not got it.

- [done] P2C.1: resolve ORCA's D3 alias to its explicit spelling
  evidence: app/chemistry/jobs/functional.py adds _ORCA_DISPERSION_ALIASES, so
  `B3LYP-D3` now resolves to `B3LYP D3BJ` with a note citing the manual and
  naming D3ZERO as the way to ask for the other form. Explicit spellings are
  left untouched, as is PySCF's existing behaviour of refusing the bare form
  and offering both -- right there, because PySCF has no default to resolve to.
- [done] P2C.2: refuse a dispersion correction on a VV10 functional
  evidence: app/chemistry/jobs/functional.py adds _VV10_SUFFIX_RE; `wB97X-V D3`
  is now refused with the bare functional offered as the fix. The manual is
  explicit that such functionals "do not need (and cannot be used together
  with) dispersion corrections", so ORCA rejects the combination -- this was a
  real error reaching the engine, not a redundancy.
- [done] P2C.3: stop a damping keyword resolving as a functional
  evidence: app/chemistry/jobs/functional.py adds _NOT_A_FUNCTIONAL, filtered
  out of the engine index. The verified ORCA pool lists D3BJ, D4 and the rest
  because it was built by asking ORCA what it accepts on the simple input line
  -- which it does. The pool file is generated, so the filter lives in the
  reader rather than being hand-edited out of the data.

## Phase 3: the hardware floor the sweep established

- [done] P3.1: document the minimum model and VRAM in README
  evidence: README.md gives, under "Before you run it", 16.3 GB resident, a 24 GB practical floor, the consumer cards that clears, and the three-model table showing 8B unable to emit tool calls at all
  Measured on this host: `qwen3.8:27b` at Q4_K_M is 16.5 GB on disk and sits
  at **16.3 GB resident in VRAM** while serving. With headroom for the context
  window and the embedding model alongside it, **24 GB of VRAM is the
  practical floor**, which puts the app within reach of a single RTX 4090 or
  5090 (24-32 GB) as well as workstation cards like the RTX 5000 Ada this was
  run on. Say what the sweep actually showed rather than only the
  recommendation: at 14B (8.6 GB) task success and elicitation degrade sharply
  while grounding holds, and at 8B (4.9 GB) the model cannot reliably emit
  tool calls at all. That is the floor under the "a modest local model is
  enough" claim and it is more useful stated with its failure mode than as a
  bare minimum spec.
- [done] P3.2: state the same floor in the deployment docs
  evidence: docs/DEPLOYMENT.md gains, in "Before you start", a GPU row and a "How much GPU you need" section carrying the same measured numbers and the same table
  `docs/DEPLOYMENT.md` and the install path should say it too, so someone
  standing up a deployment finds it before choosing hardware rather than after.

## Phase 4: the unverified deployment surface

Not defects, and that distinction has to survive being moved here: these are
surfaces nobody has ever exercised, so their absence from a defect list was
never clearance. They are in this plan because the backlog is being emptied
and an unexercised surface with no owner is indistinguishable from one that
works.

Each step closes by producing evidence either way. "Verified, works" and
"verified, here is the defect" are both results; the only non-result is
leaving it untouched, which is where these have sat.

One of them is real chemistry rather than plumbing, and the battery has just
made it cheaper: R-6 ran BAGEL CASPT2 to completion in this container with a
deviation of exactly 0, which is the first convergence-sensitive BAGEL result
this project has. That settles the "abnormally slow BAGEL" caveat for this
host; what it does not settle is whether the app's own CASSCF/CASPT2
convergence handling is right on a host where BAGEL is slow, which is what
that caveat was really about.

**P4.1 and P4.2 were closed by removal on 2026-08-25, not by being run.**
Asked whether the public `:443` listener should be tested, the answer turned
out to be that it should not exist. Its port had been commented out of
`docker-compose.yml` long enough that nothing had ever reached it, and the
controls built around it -- the admin panel's soft toggle, the middleware
check keyed on `X-Access-Channel`, and `scripts/toggle_public_access.sh` --
were locks on a door that was not in the wall.

That is a better outcome than a passing test. An unexercised listener is
attack surface; the controls over it were three mechanisms to keep working
and to explain in the docs; and on a managed campus network, exercising any
of it means a conversation with whoever runs the firewall. Removing the whole
subsystem retires all of that at once.

- [done] P4.1: remove the public listener rather than verify it
  evidence: nginx/nginx.conf no longer defines a public server block, and its
  commented port is gone from docker-compose.yml; `docker compose exec nginx
  nginx -t` passes against the new config, and `docker compose config -q` is
  clean. Only one certificate is needed now, where nginx previously refused to
  start without a `public.crt` pair that nothing served.
- [done] P4.2: remove the kill switch and everything it guarded
  evidence: app/auth/middleware.py no longer carries the channel check, and
  `git log --diff-filter=D -- scripts/toggle_public_access.sh` shows the kill
  switch itself removed. The `POST /api/admin/toggle-public-access` route, the
  `public_access_enabled` config surface and the admin panel control went with
  it. The Origin/CSRF check in app/auth/middleware.py is deliberately
  untouched -- it is unrelated to public access and is a real control.
  tests/backend/sec_01_csrf_origin_bypass.py, which used the toggle as its
  probe target, now drives `purge/orphaned-jobs`, chosen for the same reason:
  idempotent, and a no-op on a healthy deployment.
  tests/frontend/fe_sec_02_adminpanel_silent_failure.spec.mjs was rewritten
  from a bug report into a regression test -- the silent-failure bug it
  documented has since been fixed in DangerZoneSection and StorageSection, so
  it now asserts that a forced 500 *does* surface an error.

**P4.3 and P4.4 were removed on 2026-08-25, not completed.** Both asked for
chemistry validation, and chemistry correctness is not this project's claim --
PySCF, ORCA and BAGEL are responsible for their own numbers. What this app is
responsible for is that a request becomes the right input, the job runs to
completion, and the output is parsed into the right fields, and the evaluation
battery tests exactly that across every task type and all three engines.

- *`neb_ts` against a real barrier* (was P4.3): the battery covers drafting,
  submission and parsing; whether a particular band converges is a property of
  the reaction and the engine. The operator will exercise a real chemistry case
  directly. One observation is worth keeping rather than losing with the step:
  a 2026-08-20 regression pass hit an ORCA exit-code-2 on
  `tests/e2e/e2e_08_job_matrix.py`'s M23, whose raw output showed identical,
  non-decreasing energies -- consistent with a non-converging band on whatever
  system that turn happened to set up. If `neb_ts` misbehaves later, start
  there.
- *BAGEL convergence on a faster host* (was P4.4): R-6 of the battery ran BAGEL
  CASPT2 to completion in this container with a deviation of exactly 0 from a
  reference computed beforehand, which is the drafting-to-parsing evidence that
  was actually missing. A host where BAGEL runs pathologically slowly is an
  environment problem, not a defect to test for; long runtimes are this
  project's design premise rather than a fault.

- [done] P4.5: decide the vLLM backend's status -- kept, documented as the HPC path, not implemented
  evidence: docker-compose.yml's `vllm` block opens "NEVER EXERCISED"; docs/DEPLOYMENT.md gains "What this deployment is for, and where it stops", scoping this deployment to a lab or small group and naming a paged-KV server as the HPC answer

  **Decided 2026-08-25: not implementing vLLM.** The backend work stays
  commented and intact, and the recommendation is documented as future work
  for an HPC or shared-cluster deployment, which the paper will carry as
  well. The target for this release is a lab or small-group deployment on one
  GPU, which Ollama serves at 1.9 s warm with no per-model configuration.

  Kept rather than deleted because the block is considered work, not a
  sketch: a deliberately-low `gpu-memory-utilization` for a shared host, a
  GPU-id allowlist so the app never claims every card, and the tool-call and
  reasoning parser flags. Reconstructing that costs more than keeping it.

  **Not adopted now, and the reason is the evaluation rather than the
  technology.** vLLM wants safetensors, not Ollama's GGUF, so switching means
  serving a *different quantisation* of the same model -- and every number in
  the battery is tied to `qwen3.8:27b` as Ollama serves it. Tool-calling
  reliability is this app's single point of failure (condition G's 8B arm
  scored 1 of 48, almost entirely `gave-up`, because it could not drive the
  tool loop), so a quantisation change has to be re-measured, not assumed.
  Doing that before the paper would invalidate the numbers it just produced.

  What vLLM would buy, when it is time: continuous batching, which is the
  actual answer to 3-4 concurrent users; automatic prefix caching over the
  system prompt and tool schema, which are identical on every turn and every
  user here; and chunked prefill so one user's long context does not sit in
  front of another user's first token. The tool-call parser itself costs
  nothing measurable -- it is string handling on CPU.

  What decides it is P6.1, not an argument. Measure Ollama at four concurrent
  users first; there is no measurement showing it fails. When the time comes,
  the battery is the acceptance test: same conditions, new backend, and a
  single run says whether tool calling held.
- [done] P4.6: record what multi-host, real TLS and multi-operator load actually need
  evidence: docs/DEPLOYMENT.md gains "What is not built for, and what it would take",
  naming for each the specific thing that blocks it -- JobManager scheduling
  against one host's headroom, a local data/ bind mount and an in-process SSE
  queue for multi-host; a resolvable hostname and a renewal challenge path for
  a real certificate; and, for concurrency, the measured 17 GB-per-slot KV
  reservation with the three levers in increasing order of effort. Scoping
  rather than doing, which is what the step asked for.

## Phase 5: README accuracy

Both found 2026-08-24 while writing the manuscript, both wrong in a way a
reader would act on.

- [done] P5.1: fix the autoCAS DOI
  evidence: README.md links 10.1021/acs.jctc.6b00156; no occurrence of 6b00722 remains outside this tracker's own description of the defect
  The active-space section links `10.1021/acs.jctc.6b00722` for Stein and
  Reiher, "Automated Selection of Active Orbital Spaces" (*JCTC* 2016, 12,
  1760). That paper is `10.1021/acs.jctc.6b00156`. Fix `README.md` and check
  anywhere the wrong DOI was copied to (docstrings, KB seeds).
- [done] P5.2: state every outbound call, not just web search
  evidence: README.md lists web search, PubChem, OPSIN and Semantic Scholar, and says plainly that a name being looked up is the whole of what leaves
  "Web search is the only thing that reaches the public internet" is not
  true. Molecule resolution sends compound names to PubChem (`pubchempy`) and
  to the hosted OPSIN service at `opsin.ch.cam.ac.uk`
  (`app/chemistry/molecule.py`), and `search_academic_literature` sends query
  text to Semantic Scholar. None of them carries computed data or structures
  beyond the name being looked up, but a compound name is exactly what a
  privacy-conscious reader assumes stays local after reading that sentence.
  List all four. Consider bundling OPSIN locally via `py2opsin` so systematic
  names never leave the machine at all.

## Phase 6: measurement and frontend debt

Older items, none urgent, all carried forward because each is small and none
has an owner. Worth doing in one pass rather than one at a time.

- [done] P6.1: re-measure time to first token, and measure concurrency while there
  evidence: tests/backend/perf_02_ttft_and_concurrency.py measures both through the app's own chat API; README.md carries the numbers under "Before you run it"

  **TTFT warm is 1.9 s at the median (n=6, range 1.90-4.46), not "6-32s,
  median ~15s".** The old figure was ~8x pessimistic, and the suspicion in
  this step's original text was right: it was measuring cold loads. Nothing
  user-facing quoted it, so nothing needed correcting -- it lived only in the
  backlog, shaping expectations that were never true.

  **Four users at once is a queue, not a slowdown, and that is the real
  finding.** First-output times were 2.48, 7.79, 10.38 and 13.66 s -- almost
  exactly one ~4 s turn stacked behind another. Median TTFT went to 9.09 s,
  4.75x the single-user median, and four concurrent turns took 15.5 s of wall
  clock against about 17 s if run strictly one after another. Ollama is
  serialising, and the script's "under 3x" check fails deliberately rather
  than being relaxed to pass.

  **Why, and it is not Ollama's fault.** `OLLAMA_NUM_PARALLEL` is unset, so
  Ollama sizes concurrency from available VRAM -- and this model's KV cache is
  about 260 KB per token (65 layers, 4 KV heads, 256+256 key/value length, at
  fp16), so the configured `OLLAMA_CONTEXT_LENGTH=65536` is roughly 17 GB for
  a single slot. With 16.3 GB of weights, one slot is what a 32 GB card holds.
  The service is also pinned to GPU 0 by `CUDA_VISIBLE_DEVICES=0`, which is
  the right call on a shared host and is what the deployment wants.

  So the trade is context length against concurrency, on one GPU. Raising
  `OLLAMA_NUM_PARALLEL` requires shrinking the served context to roughly 16k
  per slot, which `QC_AGENT_LLM_NUM_CTX` and the app's history trimming are
  built around -- not a free change. It also needs a restart of a root-owned
  service shared with other tenants.

  **This is now the concrete argument for P4.5.** vLLM's paged attention
  allocates KV cache in blocks on demand rather than reserving a full context
  per slot, which is exactly the constraint measured here: four users rarely
  all sit at 64k tokens, so they pack into memory that Ollama has to reserve
  up front. That is a sharper reason than "continuous batching is faster", and
  it is measured rather than argued.
  The standing "6-32s, median ~15s" is an n=4 sample from 2026-08-16 that
  almost certainly predates its own explanation: the keep-warm loop
  (`QC_AGENT_MODEL_KEEPALIVE_INTERVAL`) landed the next day, and this host
  later measured 11.4s cold against 2.9s warm. Nobody re-measured after. The
  number is quoted in user-facing text, so measure it warm, on the current
  deployment, with a real sample size, and replace it.

  Then measure the thing that actually decides P4.5: **TTFT and tokens per
  second per user with four concurrent conversations.** The deployment has to
  support 3-4 simultaneous users, and nothing has ever tested whether Ollama
  does. The battery ran three streams and worked, slowly -- but three agents
  hammering continuously is far harsher than four people typing, so that is
  not the answer.

  Check `OLLAMA_NUM_PARALLEL` first. It is unset on this host, so Ollama
  auto-selects from available VRAM; if it has picked 1 rather than 4, setting
  it explicitly is a one-line change that recovers most of the benefit before
  any architecture question is asked.
- [done] P6.2: `aria-expanded` on every collapsible, plus the named testids
  evidence: frontend/src/app-shell/CollapsibleSection.tsx now sets
  `aria-expanded`, `aria-controls` and a `section-<slug>-toggle` /
  `section-<slug>-panel` pair derived from the title, so every section that
  uses the component gets both without each caller opting in -- previously
  the only signal that a section was collapsed was which chevron glyph
  happened to render, which is a screen-reader gap first and a testing gap
  second. The scheme's named hooks are in too: `chat-composer` and
  `chat-send` in frontend/src/chat/Composer.tsx, `job-row-<id>` in
  frontend/src/jobs/JobsPanel.tsx.

  Not done: a testid on every one of the 75 components. That was never the
  useful part of this item, and adding them speculatively produces hooks
  nothing uses and nobody maintains. What was missing and mattered was the
  accessibility attribute and the handful of hooks the suite actually reaches
  for.
- [done] P6.3: preload the sketcher on hover
  evidence: frontend/src/molecule/MoleculePanel.tsx starts the dynamic import
  from `onPointerEnter` and `onFocus` on the "Build a molecule" button, not
  only from the click. `import()` caches, so repeated hovers cost one fetch
  and a click that never followed a hover behaves exactly as before. The
  focus handler is there so keyboard users get the same head start.

  **Half of this item is deliberately not done.** Shrinking the ~7.6 MB
  Ketcher chunk means auditing a third-party bundle to find out what inside it
  is unused, which is real work with an unknown payoff -- and the measured
  sizes say the chunk is not even the larger half: the Indigo wasm binary
  beside it is 11.8 MB. Preloading addresses the symptom that was actually
  reported, which is the pause after clicking. If the download itself becomes
  the complaint, the wasm is where to look first.

- [done] P6.4: make viewer PNG capture resolution independent of pane size
  evidence: frontend/src/molecule/captureViewer.ts adds MIN_EXPORT_EDGE_PX,
  and the scale is now the larger of the plain 3x multiplier and whatever
  reaches that floor on the long edge, still capped by MAX_EXPORT_EDGE_PX. A
  pane already large enough keeps exactly its previous behaviour; a narrow one
  stops producing a thumbnail from the same button and the same multiplier.
  This re-renders at higher resolution rather than upscaling a bitmap, so the
  extra pixels carry real detail -- the scene is geometry.
  A capture at 3x an already-small in-panel view is still smaller than 3x an
  enlarged one, so the multiplier does not mean what it appears to. Render at
  a fixed high resolution regardless of pane size, briefly resizing the
  container before capture.

## Phase 7: close out the battery

Run after Phases 1 and 2 land. Every runner skips a trial whose score sheet
already exists, so a re-run is: delete the affected sheets, run the same
command, and the gaps refill. `rsc_digital_discovery/evaluation/README.md`
has the commands and the resume rules.

**P7.1 and P7.2 cannot be completed as written, and are being carried
forward rather than marked done.** Both say "re-run the trials that failed",
and two things happened after they were written that make that the wrong
instruction.

The battery found four defects in its own cards -- A-20's ambiguous state
count, C-07's plot counting, C-06's wrong engine and wrong framing -- each
discovered by a trial failing and each fixed reactively, which is why the run
was started three times. The cards were written from EVALUATION.md before
anything had been run against the real system, and several encoded
assumptions about the app that turned out to be false. Re-running individual
trials against cards nobody has audited would repeat that.

And the stack rebuild in P7.4 clears `data/jobs`, which every archived score
sheet references. The sheets keep their transcripts and their job ids, so the
findings stay citable, but re-scoring against `result.json` stops being
possible. Anything that needs the artifacts has to happen before the wipe, and
neither of these does.

So the next step is an audit of every card against the app's real
capabilities -- registry lookups, not GPU time -- and then one clean run. That
belongs in a tracker of its own, opened when the audit starts.

- [done] P7.3: leave the published page describing the run that actually exists
  evidence: rsc_digital_discovery/evaluation/summary.md and progress.html both
  describe the completed first run, whose 293 score sheets are archived at
  results-2026-08-25-prefix/ with their own README.

  Nothing new to regenerate: the second run was abandoned twice and its
  partial sheets discarded, so `results/` is empty by intent rather than by
  accident. Regenerating from an empty directory would have replaced a real
  result with a blank table, which is the opposite of what this step is for.
  The page keeps the first run's numbers and says plainly that they predate
  the fixes; the next run replaces them when the card audit is done.
  `harness/summarise.py` then `harness/report.py`, and republish
  `evaluation/progress.html` to the same artifact URL.
- [done] P7.4: rebuild the dev stack from nothing
  evidence: docker-compose.yml brought back up on a `--no-cache` api image and
  a freshly built `frontend/dist`, after `docker compose down -v` dropped both
  volumes; `qatest_admin` bootstrapped by tests/backend/_00_bootstrap.py and
  the operator's account created through an invite from it. Verified in a
  browser against the rebuilt stack: 0 jobs, 0 threads, two accounts.

  **One correction worth keeping.** The first pass cleared only `data/jobs`
  and `data/plots`, because those were the two directories this step named --
  and `data/` holds more than that. `threads.json`, the chat-history sqlite,
  `geometry_uploads/`, `molecules/` and `bug_reports/` all survived, which is
  why the sidebar still listed old battery conversations after a wipe that had
  been described as removing them. Cleared on a second pass, with the 64 MB
  seeded knowledge base deliberately kept so it did not have to be re-embedded.
  A step that names directories should name all of them, or survey instead.

  Original plan, for reference: a full wipe rather than a sweep. `docker compose down -v`
  drops the postgres and redis volumes, `data/jobs` and `data/plots` are
  cleared, the api image is rebuilt from scratch, and the stack comes back up
  empty. Then `tests/backend/_00_bootstrap.py` provisions `qatest_admin`, and
  the operator's own account is created through an invite token issued by that
  admin -- the order this project has always used, because bootstrap-admin
  refuses once any admin exists.

  **Ordering constraint, and it is easy to get wrong.** `summarise.py` and
  `rescore.py` read each job's `result.json` off disk, so both stop working
  the moment `data/jobs` is cleared. Generate `summary.md` and
  `progress.html`, and publish the artifact, BEFORE the wipe. The score sheets
  in `results/` survive it -- they live under the manuscript directory, not
  under `data/` -- and they carry the job ids, which is the whole reason ids
  are logged before anything is deleted.

  What the wipe destroys, stated plainly so nobody is surprised: every
  account including the operator's, every conversation and its history, all
  191 jobs and 219 MB of artifacts, and every saved plot.
