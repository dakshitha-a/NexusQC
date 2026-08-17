# NexusQC architecture

How NexusQC is put together, and — more usefully — *why*. Most of what follows
records a decision that had a plausible alternative, and the reason the
alternative was rejected. Where a claim is empirical ("ORCA truncates this
table", "these two energies agree to 1.7e-8 Ha"), it was established by running
the thing, not by reading documentation.

**Contents**

- [The through-line: mechanical, not prompt-dependent](#the-through-line-mechanical-not-prompt-dependent)
- [Job execution](#job-execution)
- [The agent graph](#the-agent-graph)
- [The approval gate](#the-approval-gate)
- [Engine integration](#engine-integration)
- [Orbitals and molden](#orbitals-and-molden)
- [Vibrations and spectra](#vibrations-and-spectra)
- [Knowledge base and retrieval](#knowledge-base-and-retrieval)
- [The frontend](#the-frontend)
- [Multi-user deployment](#multi-user-deployment)
- [Known limitations](#known-limitations)

---

## The through-line: mechanical, not prompt-dependent

One principle recurs throughout this codebase, and most of the specific designs
below are instances of it: **anything that matters for safety or correctness is
enforced in code, never left to the language model's discretion.**

The reason is experience, not taste. An early version of this app relied on
prompt instructions for a behaviour that mattered, and the resulting bug took
hours to diagnose precisely because "the model usually does the right thing" is
indistinguishable from "the model always does the right thing" until it isn't.

Concrete instances, each covered in detail below:

| Concern | Prompt-based approach (rejected) | What the code does instead |
|---|---|---|
| Nothing runs without human approval | Tell the model to ask first | A real LangGraph `interrupt()` pauses the graph |
| Retry budget for failed jobs | Have the model count its attempts | `count_failed_in_chain()` walks the chain on disk |
| Routing CASSCF to the engine that can compute oscillator strengths | Hope the model infers it from phrasing | `default_engine()` routes on an explicit parameter |
| Consulting the manuals before writing an input | A "use the KB when relevant" instruction | Every `submit_job` mechanically runs a KB query |
| Showing a generated plot in the chat | Ask the model to paste a markdown image link | The tool returns a parseable marker the UI renders |

Where behaviour genuinely requires judgement — interpreting a terse human reply
like "1b" against a disambiguation menu, or deciding which of four knowledge
sources fits a question — that *is* the model's job, and the prompt guides it.
The split is deliberate: mechanical generation, model interpretation.

---

## Job execution

### Jobs are fully decoupled from the agent and the UI

`app/chemistry/jobs/base.py`'s `JobManager` accepts a `JobSpec` and immediately
returns a `job_id`. The actual work runs in a subprocess
(`python -m app.chemistry.jobs.{pyscf,orca,bagel}_worker <spec.json>`), so a
crash or a multi-hour calculation can never block the API server or the agent's
tool-calling loop.

**Long runtimes are the design premise, not a defect.** CASSCF and CASPT2 jobs
routinely run for tens of minutes and sometimes hours, depending on atom count,
active space and basis set. The whole asynchronous design exists so a user can
submit, close the tab, and come back. Anything that would make a job's lifetime
depend on its user's session is a serious regression.

Worker subprocesses are launched with `start_new_session=True`, in their own
process group, specifically so that restarting the backend cannot kill an
in-progress calculation.

### Status is written atomically

Status and results are written to `data/jobs/<job_id>/{status,result}.json`
using temp-file-then-rename (`_atomic_write_text`). A plain `write_text`
truncates before writing, which races with the frontend's polling reads and
yields a torn or empty file.

`result_artifact_transaction()` exists for the same class of problem one level
up. Several tools add a key to a completed job's `artifacts` dict — the UV/Vis
plot, the IR plot, the job-comparison chart, the lazy per-orbital cube endpoint.
LangGraph's `ToolNode` can run multiple tool calls from one model turn
concurrently, so two of them racing on the same `job_id` previously meant
whichever wrote last silently discarded the other's key. The transaction makes
that read-modify-write lock-serialised.

### Admission is gated on the whole host, not just this app

`JobManager._wait_for_resources` decides when a queued job may start. An earlier
version tracked only this application's own subprocess trees, which was blind to
load from anything else on the machine — another tenant could saturate the host
and this app would cheerfully dispatch more work.

The gate now checks two things per poll, both from a single
`psutil.cpu_percent(interval=1.0, percpu=True)` call whose one-second block also
paces the loop:

1. Host-wide CPU and memory below `MAX_CPU_PERCENT` / `MAX_MEM_PERCENT` — a
   coarse "is the machine in distress" backstop.
2. At least `N_CORES` individual logical cores currently idle
   (`CORE_IDLE_THRESHOLD_PERCENT`, default 20% busy). This is kept as a separate
   condition because a low *aggregate* can hide uneven load just as easily as a
   moderate aggregate can hide plenty of idle capacity. In practice this is the
   check that does the real gatekeeping.

There is deliberately **no** additional app-scoped cap limiting this app's own
concurrent jobs to some fixed slice of the machine. That was considered and
rejected: self-limiting to a courtesy ceiling wastes an idle host. **The whole
machine is available**, and load — not a core budget — is what holds jobs back.
All the relevant thresholds are `QC_AGENT_*`-overridable.

### `N_CORES` is per-job width, not a total

`N_CORES` (default **4**) is how many MPI ranks or OpenMP threads a *single*
ORCA or BAGEL job requests, and correspondingly how many idle cores the gate
above waits to find. With `MAX_CONCURRENT_JOBS` (default **20**) in flight, the
app may use up to 80 cores at once. That is intended: most quantum chemistry
jobs scale poorly past a handful of ranks, so a modest per-job width and a
generous job count uses a large machine far better than one very wide job.

Setting `N_CORES` near the machine's total core count is the one genuinely
dangerous choice, because the two roles interact: the gate then waits for nearly
every core to be simultaneously idle, which on a busy host never happens, and
every job sits at `pending` indefinitely — with no error, no log line, and
nothing in the UI distinguishing it from a legitimately busy machine. The
resolved value is logged at startup specifically so that failure is diagnosable.

**This used to be auto-detected by shelling out to `nproc`, and that was
removed.** It was wrong in both directions. On a host whose shell profile sets
`OMP_NUM_THREADS`, GNU `nproc` reports *that* rather than anything about the
machine — so the value was a stray environment variable, not a measurement.
Inside a container, where no such variable exists, `nproc` reports every host
core, and the idle-core check then waited for hundreds of simultaneously-idle
cores that never materialised: every job hung `pending` forever. That was a real
deployment-blocking bug. A fixed, explicit default cannot fail either way, and
an operator who knows their hardware can still override it.

### Orphaned jobs are reconciled at startup

Worker subprocesses outlive their parent by design — but the code that finalised
`status.json` did not. The only thing that ever wrote the terminal status was
`_run_inner`'s blocking `proc.wait()`, running on a thread inside the API
process. Restart the backend mid-job and that thread, and the whole in-memory
`JobManager`, vanish; the orphaned worker keeps computing and writes a perfectly
correct `result.json`, with nothing left alive to sync `status.json` to match.

This was reproduced for real: a completed CASSCF job stuck reporting `running`
forever, with both `cancel()` and `DELETE /api/jobs/{id}` permanently unable to
touch it.

The fix: every worker spawn persists its pid and `psutil`-reported `create_time`
into the job's `meta.json`. `JobManager.__init__` then calls
`_reconcile_orphaned_jobs()`, which walks every job still on disk as
`pending`/`running` and handles three cases:

- `result.json` is already terminal → sync `status.json` to match.
- The recorded pid is alive **and** its `create_time` matches (guarding against
  pid reuse) → re-attach it via a watcher thread, and register it so `cancel()`
  can still reach it. Note this uses `psutil.Process.wait()`, not `Popen.wait()`
  — it is not this process's child.
- Neither → mark it `failed` with an explanation, rather than leaving it stuck.

---

## The agent graph

### State needs `NotRequired` and custom reducers

`AgentState` (`app/agent/state.py`) carries side-channel fields that tools mutate
via `Command(update=...)`, separate from the `messages` ReAct loop. Two
non-obvious requirements:

**They must be `NotRequired[...]`, not merely `Optional[...]`.** On a brand-new
thread the keys are genuinely absent, and `ToolNode` validates injected state
against a pydantic model derived from this TypedDict *before* any tool body
runs. Plain `Optional` therefore fails validation on every tool call in a fresh
conversation. This one caused a long-misdiagnosed bug: every tool call failed
and the graph looped, which looked like the model "thinking" for minutes.

**They need custom reducers** (`_last_molecule`, `_append_job_ids`) because a
single model turn can emit several tool calls in one batch — `set_molecule` plus
`submit_job`, or two `submit_job` calls — which all read the same pre-batch
state. Without a reducer, LangGraph's default channel either silently drops one
write or hard-errors on multiple writes in one step.

### Checkpointer and locking are chosen together

The backend is selected by whether `QC_AGENT_DATABASE_URL` is set.

**Unset (local single-user):** `SqliteSaver` over one process-global
`sqlite3.Connection`.

**Set (multi-user):** `PostgresSaver` built around a `psycopg_pool.ConnectionPool`
— constructed directly, *not* via `PostgresSaver.from_conn_string`, which
returns a context-manager-wrapped single connection unsuitable as a long-lived
module global. `.setup()` was confirmed idempotent, so it is called
unconditionally rather than needing a separate migration step.

Independent of backend, the original single process-wide `_graph_lock` was
replaced by `_lock_for_thread(config)` — lock striping keyed on `thread_id`. Ten
users' turns no longer queue behind one another, while two operations on the
*same* conversation still serialise correctly. That serialisation is a real
application-level invariant: several functions do a `get_state()` then
`update_state()` read-then-write that neither checkpointer guarantees atomically.

`get_graph()` / `invalidate_graph_cache()` use a separate `_compiled_graph_lock`
guarding the single global compiled graph, held only for the instant needed to
fetch or rebuild it. Lock acquisition order is always thread-lock then
compiled-graph-lock, so no cycle is possible.

Verified empirically rather than by inspection: a `read_state()` on a *different*
`thread_id` returns in ~30 ms while another thread holds a 1.5 s lock on its own
thread; the same call on the *same* `thread_id` correctly blocks for the full
1.5 s.

### `invalidate_graph_cache()` must never be called from inside a tool

`ToolNode` runs tool calls on its own `ThreadPoolExecutor` worker thread, not the
thread that called `.invoke()`. A tool that tried to acquire its own
conversation's lock would deadlock for real: the calling thread holds that lock
for the entire `.invoke()` while waiting on the tool, and the tool's worker
thread blocks trying to acquire it. An `RLock` would not help — reentrancy only
assists the *same* thread. Any legitimate caller must invoke it from a
request-handling thread, strictly after the turn has returned.

---

## The approval gate

`submit_job` gates execution behind a real LangGraph `interrupt()`, not prompt
instructions. After building the `JobSpec` and rendering its input preview, it
calls `interrupt()`, which pauses the graph; `graph.invoke()` returns with a
`__interrupt__` key instead of completing. The paused payload is also readable
later via `graph.get_state(config).interrupts`, so reloading the page while an
approval is pending still shows the card.

**The safety property holds even if the model never asks for confirmation,
because the pause is structural.**

The sharp edge: per LangGraph's own documentation, the graph *"resumes from the
start of the node, re-executing all logic."* Everything before the `interrupt()`
runs again on resume and is discarded — including a freshly built `JobSpec` with
a **new random `job_id`**. Two consequences shaped the design:

1. **`submit_job` never resolves a molecule name itself.** A network-backed
   lookup redone on every resume could return a different molecule than the one
   approved, or raise on a transient failure and crash the approval click
   outright. (Verified: an exception in the pre-interrupt path during resume
   propagates straight out of `resume_turn` — it is *not* caught into a
   `ToolMessage` the way a normal tool exception is.) The molecule must already
   be in state via a separate `set_molecule` call. `generate_job_input`, which
   is preview-only and has no interrupt, freely resolves names inline.

2. **The approved spec is round-tripped, not rebuilt.** The interrupt payload
   includes `spec.to_dict()`, the UI returns that exact dict, and the submitted
   job is `JobSpec(**decision["spec"])`. What runs is bit-for-bit what was
   shown and approved, regardless of what the discarded re-execution produced.

### Hand-editing the input

ORCA (`.inp`) and BAGEL (JSON) inputs can be edited on the approval card before
running. Both are genuine text formats the engine parses itself, so editing
changes nothing about the trust model — the binary was always going to interpret
whatever text it was given.

PySCF has no such file. Its "preview" is a synthetic driver script standing in
for direct API calls, so there is nothing an edit could change at execution
time; it renders read-only.

Edited text is validated (`app/chemistry/jobs/validate.py`) **before** the
approval is spent: balanced ORCA `%...end` blocks including single-line
self-closing ones, a recognised geometry block, valid element symbols; JSON
validity and required blocks for BAGEL. A typo is caught and shown in place with
no model round-trip, and the interrupt stays pending so it can be fixed and
resubmitted. `submit_job` re-validates server-side as defence in depth.

Because an edit can change what the engine prints, the job-type-specific parser
may not find what it expects. Both runners wrap summary-building in `_safe_parse`,
which turns that into a clear "ran fine but couldn't parse X, raw output at
`<path>`" rather than a bare traceback or, worse, silently wrong numbers.

### Automatic troubleshooting, with a code-enforced budget

A failed job triggers an investigate-and-retry cycle driven by
`app/agent/job_watcher.py` — a background thread that walks every conversation in
the registry rather than being tied to any browser tab. That matters twice over:
closing a tab must not silently stop auto-retry, and two open tabs on the same
conversation must not both inject the same retry.

The agent is instructed to call `check_job_status`, search the manuals, search
the web if needed, then call `submit_job` again with corrections and
`retry_of_job_id` set. **That retry still pauses on `interrupt()` like any other
job**, so "the agent silently reruns a job with different parameters" is never
possible.

### A background turn must announce itself

That retry cycle runs through `invoke_turn`, which holds the conversation's
`_lock_for_thread` for the whole ReAct loop. A user message posted meanwhile
takes the same lock inside `stream_turn_tokens` — acquired lazily on the first
`next()`, so its SSE stream opens successfully and then produces nothing at all
until the background turn finishes.

That serialisation is deliberate and correct; one conversation's turns must not
interleave. The defect was that it was **invisible**. A background turn set
neither `turnInProgress` nor `pendingApproval`, the two things that make the
composer show a busy state, so the UI looked completely idle while messages
piled up behind the lock.

The scale is what made it a bug report rather than a nitpick. Measured from the
checkpoint history of a real incident: a single agent loop step takes 26–40 s,
complete turns 53–77 s, and this investigate-and-retry turn is several LLM round
trips longer still. Two prompts sent during one therefore looked exactly like a
hang, and then "suddenly started again" when the lock was released and both ran.

So `job_watcher` now emits `turn_start` before it takes the lock, and the chat
renders a distinct notice for it. Three details are load-bearing:

- It is emitted **before** `read_state`, not just before `invoke_turn` — that
  call takes the lock too.
- It is paired with `turn_complete` from a `finally`, so a failed turn cannot
  leave the UI claiming a background turn is running forever.
- It sets its own store flag rather than reusing `turnInProgress`, which
  *disables* the composer. Reusing it would have converted an invisible wait
  into a lock-out, which is a different and worse behaviour: the user's message
  is accepted and answered as soon as the lock frees, and only ever needed
  saying so.

The same contention is why `chatStore`'s `threadLoading` exists — opening a
conversation calls `GET /api/threads/{id}/state`, which takes that thread's lock
and so blocks behind a running turn.

The budget is **not** read from anything the model supplies.
`count_failed_in_chain()` walks the retry chain backwards on disk via each job's
`params["_retried_from"]` and counts current failures; `job_watcher` calls it
directly to decide between a retry notice and a stop-and-explain notice. A
model-tracked counter keyed on an optional argument it might simply omit resets
to zero for free.

---

### What the agent can see about an attached job

`job_context_summary` (`app/chemistry/jobs/summarize.py`) is the entirety of what
the model knows about a job the user attached to a prompt — the same text also
backs `check_job_status`, so there is no second channel.

It originally emitted the job's own `job_type`/`engine`/`params` only in the
*failed* branch, on the reasoning that a retry needs to know what it is retrying.
That left a gap for every job type. A completed job's `summary` dict carries none
of its own input settings: no `method`, no `basis`, no `functional` — verified
against real results on disk, not assumed. So an ordinary request like *"use the
same method and basis as the attached job"* or *"run that again with a bigger
basis"* was unanswerable from any tool the agent has, and the model's only
options were to ask or to invent a level of theory.

Inventing one is caught by nothing downstream. The approval card faithfully
displays whatever was picked, and a user who trusts their own phrasing reads it
as inherited. The line is now emitted for completed jobs too; params beginning
with `_` stay hidden, since those are internal plumbing rather than anything a
user chose.

## Engine integration

### The runner/worker pair

Each engine has `{engine}_runner.py` with pure functions
`run_<method>(molecule, params) -> {"summary": ..., "artifacts": ...}`, and
`{engine}_worker.py` as the subprocess entrypoint that dispatches by method name.

`app/chemistry/jobs/registry.py` is the single source of truth for which engine
handles which method (`DEFAULT_ENGINE` / `ALLOWED_ENGINES`) and which parameters
are required per job type (`REQUIRED_PARAMS`). The agent's `submit_job` consults
it to decide what to ask the user for, rather than hardcoding elicitation logic
per method.

### Text parsing is derived from real runs

PySCF results come straight from its own Python objects. ORCA and BAGEL have no
structured output, so their runners regex-parse plain text — and **every one of
those patterns was derived from actual runs**, not from documentation, because
exact stdout formatting is not guaranteed across versions.

A representative example of why this matters: **ORCA's default `ORBITAL ENERGIES`
output is silently truncated to the first 10 virtual orbitals**, with a literal
`*Only the first 10 virtual orbitals were printed.` line. Confirmed on a real
def2-SVP water run: 24 basis functions, 16 rows printed. Adding `LargePrint`
forces the full table — but `LargePrint` *also* dumps the full MO coefficient
matrix immediately afterwards with no blank line between. The original parser
matched to the next blank line and would have absorbed that unrelated section.
`_orbital_energy_rows` now scans row-by-row from the header and stops at the
first line that doesn't match the four-column shape, which naturally handles both
the truncation notice and the coefficient dump without special-casing either.

### Excited states route through shared job types

Rather than one job type per method: `tddft`'s `qc_method` (`hf` vs `dft`)
combined with `use_tda` covers CIS, TD-HF/RPA, TDA-DFT and TDDFT. PySCF's
`tdscf.TDA`/`TDDFT` are dispatchers that pick their implementation from the
reference wavefunction's type, and an HF reference has no XC kernel — so
TDA-on-HF *is* CIS. ORCA's `%tddft` module makes the same selection. Confirmed:
energies and oscillator strengths from a real ORCA CIS run agree with PySCF's
`tdscf.TDA(scf.RHF(...))` to five decimal places.

`eom_ccsd` is its own job type because PySCF's `EOMEESinglet` has **no**
oscillator-strength or transition-dipole support at all, while ORCA's MDCI module
computes them by default. Hence `DEFAULT_ENGINE["eom_ccsd"] = "orca"`, with
PySCF available for energies only.

CASSCF has the same asymmetry: only ORCA computes oscillator strengths for it
here, given `DoDipoleLength true`. So `casscf` gained ORCA as a *non-default*
allowed engine, and `default_engine()` takes an optional `params` argument so a
caller passing `want_oscillator_strengths=True` is **mechanically** routed to
ORCA — deliberately not left to the model to infer from phrasing.

CASPT2 is BAGEL-only and energies-only; ORCA implements NEVPT2, not CASPT2.

### Convergence policy is explicit and identical across engines

Rather than inheriting three different engine defaults, `app/config.py` defines
`CASSCF_CONV_TOL_ENERGY` (1e-6), `CASSCF_CONV_TOL_OPT_FREQ` (1e-7, tighter
because a loose wavefunction shows up as gradient and Hessian noise) and
`CASSCF_MAX_CYCLE_MACRO` (200), applied at every construction site. `GTol`
(ORCA) and `thresh_micro` (BAGEL) are deliberately left at each engine's own
default.

This surfaced a real pre-existing gap: ORCA's `build_input_text` never emitted a
`%geom` block at all, so `max_steps` silently never reached ORCA's optimiser.

### CASSCF and CASPT2 gradients

Support was confirmed per-engine before implementation, not assumed.

**PySCF** has a real analytic CASSCF gradient, so `geometric_solver.optimize(mc, ...)`
works directly. It has **no** analytic CASSCF Hessian — `pyscf.hessian.casscf`
does not exist — so frequencies use a hand-rolled `_numerical_casscf_hessian()`:
central differences of a gradient scanner over all `3*natm` displacements,
assembled into the exact `(natm, natm, 3, 3)` shape the analytic path produces so
it drops into the existing thermochemistry calls unchanged. This is O(6·natm)
full CASSCF solves — markedly slower than an analytic Hessian.

**ORCA** has an analytic gradient but a numerical-only Hessian, so CASSCF
optimisation uses `! Opt` while frequencies need `! NumFreq`. Verified live: a
water CASSCF(4,4)/STO-3G optimisation converged in 5 steps with genuinely
fractional natural-orbital occupations (1.9979 / 1.9874 / 0.0133 / 0.0014), and a
frequency run at that geometry gave 3 real frequencies with the 6
translational/rotational modes projected to exactly 0.0.

**BAGEL** accepts a nested `"method"` array inside `optimize`/`hessian` blocks,
using the same per-method dict shapes already built for the plain job types.
This support is *structurally confirmed and observed executing correctly* rather
than *convergence-verified end to end* — see [Known limitations](#known-limitations).

### `custom` jobs

`job_type='custom'` runs an arbitrary ORCA or BAGEL calculation through the same
approval and execution pipeline, with the agent composing the complete input text
itself. This needed almost no new machinery: worker dispatch is already generic
over `(method, engine)`, validation does not look at job type, and the approval
card's editable-textarea branching keys purely on engine.

Structural validation is deliberately **non-blocking** here. Unlike every other
job type — where the input started from a generated, standard-geometry template,
so a validation failure means something broke — a custom job's entire purpose is
carrying syntax the validator was never built to recognise. Hard-blocking would
defeat the premise. Complaints surface as a "structural check found possible
issues (not blocking)" banner, deliberately *not* reusing the existing
auto-correction channel whose banner reads "Auto-corrected:" and would
misrepresent a complaint as a change actually made.

ORCA's normal success marker (`FINAL SINGLE POINT ENERGY`) is specific to
SCF-based job types, so custom jobs use `_write_and_run_generic`, which checks for
`ORCA TERMINATED NORMALLY` instead — confirmed calculation-type-agnostic across
real job output.

### Parameter repair is narrow and verified

`app/chemistry/jobs/param_normalize.py` corrects two specific, previously-observed
typo classes before validation, rather than relying on the model's retry loop.

`normalize_method` handles the fact that this app's `method` parameter only ever
means `hf` or `dft` for most job types — restricted vs unrestricted reference is
chosen automatically from spin, never exposed — so RHF/UHF/ROHF and misspellings
collapse to `hf` via an alias table plus a tight fuzzy fallback.

`normalize_basis` targets exactly one shape: a Pople basis name with a
polarisation suffix glued on without parentheses (`6-31gd`), which a real job hit
and failed on with an unhelpful `KeyError`. The repair is re-verified against
PySCF's own parser before being accepted — necessary because PySCF was found to
silently accept *and discard* an unrecognised parenthesised suffix (`6-31G(zzz)`
loads as plain unpolarised 6-31G), which would otherwise let the repair mask
nonsense instead of catching it.

Both are deliberately narrow. An unrecognised value falls through to the existing
error path untouched, never silently guessed at. Corrections are surfaced on the
approval card, not applied invisibly.

---

### Basis Set Exchange is an escape hatch, not a replacement

The keyword menus above suggest names each engine actually recognises. When none
of them is what the user meant — an exotic, relativistic or ECP basis — the
menu's last entry offers a Basis Set Exchange search, and `resolve_basis_from_bse`
confirms the candidate covers every element in the current molecule before
telling the agent it is usable. Same "never offer a candidate that doesn't
validate" discipline as the rest of `keyword_suggest.py`.

The sentinel is appended *only* alongside at least one real suggestion, which
preserves the existing contract that a menu with nothing to disambiguate is not
shown at all.

The `basis_set_exchange` package is fully offline — the basis data ships inside
the wheel — so unlike every other external integration here (PubChem, Semantic
Scholar, web search) there is no timeout, no cache-of-a-network-fetch, and no
failure mode to design around. `params["basis"]` carries a plain `bse:<name>`
sentinel and every engine translates it lazily inside its own runner, at the
point it already turns `basis` into something it can run, so nothing upstream —
param normalisation, engine resolution, the interrupt/resume boundary — changed
shape.

Per-engine translation is where the real work was, and two findings came from
checking against reality rather than documentation:

- **BAGEL** never uses a multi-row contraction. A general contraction is instead
  several shell entries sharing one `prim` list — established by diffing against
  a real installed BAGEL basis file, after a first attempt preserved BSE's own
  general-contraction shape. The translator therefore uncontracts general
  contractions first, and uncontracts combined shells with `max_am=0` rather than
  the `max_am=1` BSE's own GAMESS-US/ORCA writers use, because BAGEL has no
  combined-shell concept. Output is cached by content hash under
  `DATA_DIR/bse_basis_cache/` and referenced by absolute path, which BAGEL's
  manual explicitly supports — necessary because a BAGEL install's own `share/`
  directory is typically not writable by this app.
- **ORCA's `fmt="orca"` is a naming trap.** It emits GAMESS-US's `$DATA` wrapper,
  not ORCA's `%basis NewGTO ... end` syntax. The translator fetches
  `fmt="gamess_us"` per element and rewraps it. Confirmed against a real run that
  the basis keyword can be omitted from the `!` line entirely when a `%basis`
  block supplies it.

BAGEL mandates a density-fitting basis with no "off" mode, so `df_basis`
resolution tries the existing family map first, then BSE's own role metadata
(`jkfit`, then `rifit` — which of those exists is family-dependent), and only
then a generic fallback.

ECP handling is explicitly out of scope: ECP-named entries pass harmlessly
through the suggestion pools, but nothing special-cases core-electron counting or
ECP/basis pairing.

## Orbitals and molden

MO cube visualisation works identically across all three engines via a shared
parsing layer (`app/chemistry/jobs/molden.py`), but each engine reaches a correct
cube by a different route. **This was confirmed by point-sampling AO evaluation
against native PySCF calculations at several off-axis points** — not by
inspection, and not by cheap self-consistency checks, which turned out to be
actively misleading.

`pyscf.tools.molden.load()`'s return shape depends on whether the file has one MO
section (restricted — flat arrays) or two (genuinely unrestricted — a 2-tuple),
so every function normalises to a flat, 1-based, optionally spin-labelled list up
front.

**PySCF** needs no round-trip for its own cubes, but writes a molden export
anyway so the lazy per-orbital endpoint can treat all three engines uniformly.

**BAGEL**'s molden export round-trips exactly — AO evaluation matched a native
PySCF calculation to a ratio of 1.0 at every sampled point. Its own native
`moprint` block was tried first and rejected: those cubes are per-orbital
electron *density* (`|ψ|²` — non-negative, symmetric double lobe with a node at
the bond centre) rather than the signed amplitude a two-isosurface viewer needs,
and carry no per-orbital energy table.

**ORCA**'s molden export is the case that does *not* round-trip despite passing
every cheap check. It parses without error, and both individual AOs and the
target MO pass a naive self-overlap check of 1.0. Point-sampling showed each AO
column scaled by a different, shell-dependent constant relative to native
evaluation of the same basis (~0.35x / 1.1x / 0.5–0.6x for different shell types)
— consistent with a contraction-coefficient normalisation mismatch, not a
sign-or-ordering difference, which would give ratios of exactly ±1. ORCA's cubes
therefore come from `orca_plot`, ORCA's own generator, driven via piped stdin
against a completed job's `.gbw` file.

### Orbitals are available on every relevant completed job

`single_point`, `tddft`, `eom_ccsd`, `casscf` and `caspt2` all write a molden
export and an `orbital_table`, at negligible marginal cost since the wavefunction
is already computed. Users never need to submit a separate `mo_visualization`
job. Any orbital can additionally be rendered lazily on click, cached into
`result.json` under a key scheme distinct from the eagerly-rendered HOMO/LUMO
keys so the two never collide.

CASSCF orbitals needed real verification. PySCF's `mc.mo_coeff` after a plain
`.kernel()` are *canonicalised* MOs with integer 0/2 occupations, not natural
orbitals. `molden.from_mcscf(mc, path, cas_natorb=True)` is what actually
produces natural orbitals with genuinely fractional active-space occupations
(~1.98/1.98/0.02/0.02 for a closed-shell CAS(4,4)), confirmed by point-sampling
against `mc.canonicalize(sort=True, cas_natorb=True)` directly.

BAGEL surfaced a real bug here. The first implementation appended the molden
`print` block last in the pipeline, reasoning that CASPT2 does not reoptimise
orbitals so placement shouldn't matter. A real CASPT2 run came back with every
occupation flattened to integer 0/2 and every orbital energy 0.0 — BAGEL's
"current wavefunction" is no longer the CASSCF natural-orbital state once `smith`
has run. Moving the `print` block to immediately after `casscf` fixed it, with
the CASPT2 energy bit-for-bit identical (a print block is pure I/O, so its
position changes only what it captures).

---

## Vibrations and spectra

`app/chemistry/jobs/vibrations.py` is the single source of truth for what counts
as an imaginary frequency (`IMAGINARY_FREQ_THRESHOLD_CM1`, default 50 cm⁻¹).
Before this, four places used three different rules, and the same molecule could
be a minimum on BAGEL and a saddle point on ORCA. All three runners now call
`summarize_frequencies`, and the frontend consumes the resulting per-mode flags
rather than re-deriving from the sign.

Mode animation works on all three engines. ORCA prints the mass-*deweighted*
Cartesian displacement matrix — its own header confirms the mass-weighting has
been undone, i.e. these are real-space displacements. BAGEL's equivalent is under
a section titled "corresponding cartesian eigenvectors" — critically **not** the
earlier "Mass Weighted Hessian Eigenvectors" section, which has an identical
block layout but is the wrong physical quantity and would make heavier atoms
visibly under-displace. One shared structural helper parses both, since the
block shape is identical even though the surrounding page layout differs.

Spectrum plots drop modes below 10 cm⁻¹ before broadening: both text-parsed
engines keep the five or six near-zero projected translational/rotational modes
in their frequency lists (deliberately, so indices stay aligned between engines),
and including a literal 0.0 point would stretch the x-axis across a long dead
zone. Plots follow the conventional IR display direction, high wavenumber left.

Plot tools **refuse rather than fabricate**. `plot_excited_state_spectrum` will
not render a flat line when oscillator strengths are missing, `None`, or all zero
— exactly the situation for a PySCF `eom_ccsd`/`casscf` job or any CASPT2 job.

---

### Nuclear-ensemble (Wigner) spectra

A `wigner_ensemble` job samples geometries from a completed frequency job's
normal modes, runs one excited-state sub-job per sample, and pools every sample's
transitions into one broadened spectrum. The architecture mirrors `pes_scan`'s
master/sub-job fan-out, with one deliberate deviation: sub-jobs dispatch in
throttled waves rather than all at once, because sample counts (up to 250) dwarf
a typical scan's image count and would otherwise stress the quota and concurrency
scanning at a scale it was not built for.

`casscf` and `caspt2` sub-jobs get `want_oscillator_strengths` forced on, since
without it they report no intensities on any engine and the ensemble would pool
nothing. Pooling accounts for every sub-job in exactly one category, so a caller
can always say what happened to each sample rather than silently dropping some.

The random seed is generated and written into `params` *before* the approval
interrupt, so the ensemble a human approves is the one that runs. `pes_scan` does
not need this because its image construction is deterministic and safe to
re-execute on resume; Wigner sampling draws random numbers, and everything before
`interrupt()` re-runs on resume.

#### The mode/reduced-mass convention, and why a passing test proved nothing

This feature first shipped with the sampling width wrong on every engine, in two
compounding ways. Both are worth recording, because the shape of the mistake
generalises.

`sigma_q = sqrt(hbar / (2 * mu * omega))` carries a `1/sqrt(mu)`, which pairs it
with a **unit-length** direction vector: in mass-weighted normal coordinates the
effective mass is exactly 1, so the mass dependence is carried once, by `mu`, and
once only.

1. The original code multiplied `sigma_q` into PySCF's raw `norm_mode` array,
   whose own norm is *itself* `1/sqrt(mu)` — it is the mass-deweighted eigenvector
   `l/sqrt(m)`. The factor was applied twice and every displacement came out too
   small by `sqrt(mu)`: about 4% for a hydrogen-dominated mode, a factor of 2.2
   for formaldehyde's 5.05 amu C=O stretch, 3.4 for the 11.5 amu modes of a real
   twelve-atom molecule. Wrong, in other words, precisely on the heavy-atom modes
   that shape a real chromophore's band — while a water test looked almost right.
2. The reduced-mass helper inferred `mu = 1/sum(v**2)`, an identity that holds
   only for mass-deweighted vectors. **ORCA's printed normal modes are
   additionally unit-normalised** (`sum(v**2) == 1.0000` exactly, confirmed
   against a real run), so it returned a fabricated `mu = 1.0 amu` for every mode
   of every ORCA job — erring in the *opposite* direction from PySCF and making
   the same molecule's ensemble depend on which engine produced the frequencies.

Compounding the trap: that helper is used by ORCA and BAGEL and *not* by PySCF,
which passes its own authoritative `reduced_mass` through. The only engine it had
ever been validated against was the one engine that never calls it.

The fix is a reduced mass invariant under any per-mode rescaling of the mode
vector, `mu_k = sum_a m_a |v_ak|^2 / sum_a |v_ak|^2`, paired with an explicitly
unit-normalised direction. That is correct for all three engines with no
per-engine special case — it reproduces PySCF's own `reduced_mass` to 1e-15 and
recovers ORCA's true values where the old formula returned 1.0.

Reduced masses are now always *recomputed* from the modes plus the molecule's
element symbols rather than read back from a stored summary, because `mu` and the
mode vectors must be a matched pair and a summary written before this fix carries
the fabricated values. A useful side effect: any completed frequency job with a
`normal_modes` array is a valid ensemble source, including jobs predating the
stored-reduced-mass field entirely, so nobody re-runs a finished multi-hour
calculation for a number derivable from what it already recorded.

**The original gating test could not have failed.** It compared the ensemble's
mean harmonic potential energy against `sum(hbar*omega/4)` using the sampler's own
per-sample diagnostic — but that diagnostic is `0.5*mu*omega^2*q^2` evaluated on
the very `q` drawn from a distribution of width `sqrt(hbar/(2*mu*omega))`, so
`<V> = hbar*omega/4` is an algebraic *identity* in those coordinates for any `mu`,
whether the normal-coordinate-to-Cartesian mapping is right or wrong. The
docstring claimed to test exactly what the arithmetic made it blind to.

`scripts/validate_wigner_sampling.py` now evaluates the **Cartesian** Hessian
quadratic form on the geometries the sampler actually emits, against a Hessian
obtained independently — sharing no arithmetic with the sampler. It reports 0.756
of the analytic value before the fix and 0.989 after. Keep a molecule with a
genuinely heavy-atom mode in its `CASES` list: water's modes are all near 1 amu,
so water alone lets a `sqrt(mu)` error hide inside a loose tolerance.

The generalisable lesson: a check expressed in the same coordinates as the code
it checks can be an identity rather than a test. Verify against a quantity
derived independently.

Imaginary-mode detection routes through the shared `is_imaginary` rule rather
than a bare `f < 0`, which matters beyond consistency: PySCF's `freq_wavenumber`
is genuinely complex, and an imaginary root's *real* part is `0.0`, so a sign test
buckets it as a low-frequency mode and reports zero imaginary modes.

Per-state overlays group transitions by literal excited-state index across the
ensemble, not by adiabatic character. States genuinely reorder between sampled
geometries; that is inherent to pooling independently-run sub-jobs, not a defect
of this implementation.

## Knowledge base and retrieval

### The manuals lookup is mechanical

`search_knowledge_base` is an ordinary model-discretionary tool, and a soft
prompt instruction to use it for exact syntax was **not** enough: a real job was
submitted with a basis string PySCF doesn't recognise, failing at runtime with a
raw `KeyError`.

So `_build_spec_or_error` — shared by `generate_job_input` and `submit_job` — now
*always* runs `_kb_context_for_job()`, a similarity search filtered to
`doc_type="manual"` keyed on the engine, job type, method, functional and basis.
The result is threaded into the tool message the model sees **and** into the
approval card, under "Manual/reference excerpts consulted" — the last checkpoint
before execution, and the one place that does not depend on the model reading
anything.

This is retrieval-and-surface, not verification. Nothing parses the retrieved
text or blocks a bad parameter. KB quality also varies by engine: ORCA and BAGEL
manuals document keyword syntax directly, while PySCF's KB is generated from
installed-package docstrings, which cover signatures well but say nothing about
basis-set naming — weaker grounding for exactly the error class that motivated
this.

### Four knowledge sources, deliberately differentiated

The system prompt gives each source an ordered hierarchy keyed to a recognisable
situation — preparing an input, troubleshooting a failure, answering a chemistry
question, or writing a parser — rather than one flat "use when relevant"
instruction, because those situations call for genuinely different sources and
mixing them risks answering a chemistry-judgement question with a software manual
snippet.

`search_academic_literature` wraps Semantic Scholar's `/paper/search/bulk`
endpoint specifically, not `/paper/search`: the latter returns `429` repeatedly on
the shared unauthenticated pool, and `bulk` is the only one supporting
`sort=citationCount:desc`. Its query syntax is literal boolean AND/OR of
bare/quoted tokens, not semantic search — a real usability trap, confirmed by
testing: a natural multi-word question returns zero hits because every word is
ANDed, while unquoted common words match hundreds of irrelevant papers. Only a
query of a few double-quoted distinctive technical terms works. This is enforced
through the tool's docstring contract with explicit good and bad examples; there
is no query-rewriting layer.

### Seeding

`scripts/seed_knowledge_base.py` crawls the BAGEL and ORCA manuals and generates
PySCF reference docs from the *installed* package's docstrings. PySCF is
deliberately not scraped: pyscf.org's `robots.txt` disallows it.

Watch for dispatcher functions when extracting docstrings — `mcscf.CASSCF`,
`mp.MP2` and `tdscf.TDA` at the top level are runtime dispatchers with **no
docstring of their own**; the real content lives on the concrete classes they
resolve to. The crawler also force-corrects encoding via `apparent_encoding` when
a server omits `charset`, because `requests` otherwise falls back to ISO-8859-1
and mangles curly quotes and em-dashes.

---

## The frontend

### Polling is separated from expensive rendering

Job status is polled via TanStack Query against lock-free disk reads in
`server/routes/jobs.py`. Those routes deliberately never call `read_state()` or
take the graph lock, so a polling tab is never stalled behind an in-flight chat
turn. The list routes read a job's `result.json` only once it has actually
failed, since a trimmed list row needs nothing else from it.

The MO-cube viewer and other artifact viewers mount only when the job detail
drawer opens for that specific job. React's own mount/unmount lifecycle achieves
what previously had to be done by hand: they are never rebuilt by an unrelated
re-render or polling tick, so an in-progress WebGL rotation is never discarded.

### Turns stream over SSE

A chat turn is submitted via `POST /api/threads/{id}/messages`, which returns
`202` immediately and runs the turn on a background thread, streaming progress
over `GET /api/threads/{id}/events`. The stream requests both `updates` and
`messages` modes, so real per-token deltas and tool-call progress arrive together.
The frontend renders the user's own message optimistically before the POST even
completes, appends token deltas to an in-progress bubble by message id, then
reconciles with the authoritative final message.

Approval resumes stream too. The live job log is deliberately on its own 1.5 s
poll gated on `status === "running"` — a raw log tail is cheap, low-stakes state,
not worth a second event type.

### Every route handler is a plain `def`

FastAPI runs sync handlers in a worker threadpool, while an `async def` handler
that blocks stalls the single event loop — including SSE delivery to every other
open connection. The KB upload route violated this: it was `async def` and called
a synchronous chunk-and-embed pipeline directly on the event-loop thread, so a
large PDF upload stalled every other tab for the whole ingestion. Fixed by making
it a plain `def` like every other route.

### Three outbound calls needed explicit timeouts

Anything that runs inside a graph turn can hold that thread's lock for as long as
it hangs. The embedding client, the web-search client, and — most severely — the
PubChem lookup all lacked bounds.

That last one is instructive: `pubchempy`'s `request()` calls
`urllib.request.urlopen()` with no timeout and **no parameter to pass one in**.
Since molecule resolution is almost always the first tool call of a conversation,
an unreachable PubChem hung that call forever, and with it the lock, and with it
every open conversation, with no recovery short of restarting the backend. Since
the library offers no per-call timeout, the fix scopes Python's process-wide
`socket.setdefaulttimeout()` around just that call, always restoring the previous
value even on exception.

### The 3Dmol wrapper is deliberately imperative

The viewer instance lives in a `useRef`, rebuilt only by an effect keyed on the
molecule or cube data itself. Putting `createViewer()` in the render path would
rebuild the WebGL view — and discard camera state — on every unrelated re-render.

One bug shaped the current implementation, and it is worth knowing about because
reasoning from the docs gives the wrong answer. **`GLViewer` has no `destroy()`,
`dispose()` or `remove()` method, and `createViewer()` unconditionally appends a
new `<canvas>` into the container.** React 18 Strict Mode's dev-time
mount→cleanup→remount nulls the container ref *before* running cleanup, even
though the DOM node is not actually torn down — so a "clear the container in
cleanup" fix is silently a no-op, and the first mount's orphaned canvas is still
present when the second `createViewer()` appends another on top.

Browsers cap live WebGL contexts per page (commonly 8–16). Repeated
mount/unmount exhausted that cap and every subsequent context silently failed to
initialise — the viewer rendered as a blank square with no error. The actual fix
clears the container at the *start* of the init effect. Verified by
instrumentation: live canvas count stays at exactly 1 across dozens of rapid
cycles, where it previously grew without bound.

Related, and easy to lose an afternoon to: **`page.screenshot()` cannot reliably
capture WebGL canvas content.** Use `canvas.toDataURL()` via `page.evaluate()`
when verifying anything the molecule or orbital viewers render.

### Camera framing: `zoomTo()` has a floor, and it is not ours

Molecules were reported as "always zoomed out and small". Every viewer already
called `zoomTo()` on load, so the framing call was never missing. Measuring the
library directly — a two-atom dimer, sweeping the separation — showed an
*identical* camera distance (`getView()[3] == 121.644`) at 0.5 Å, 1 Å, 5 Å and
10 Å, moving only above 10 Å. The source says why:

```js
var MAXD = this.config.minimumZoomToDistance || 5;   // 3dmol/build/3Dmol.js
var maxDsq = MAXD * MAXD;                            // floor on the bounding radius
maxD = Math.sqrt(maxDsq) * 2;
```

The fit is on a sphere of radius `max(MAXD, r_max)`, and MAXD defaults to 5 Å —
so **every molecule with a bounding radius under 5 Å**, which is most of what
this app runs, was framed as though it were 10 Å across. Water covered 6% of the
frame width; benzene 39%.

`minimumZoomToDistance` is a supported config option, so the fix is to pass a
floor low enough that it stops binding. It cannot be zero: the floor is what
stops a single-atom system (`r_max == 0`) putting the camera at the origin.

With the floor lowered, 3Dmol's own fit turns out to *clip* — benzene measured
0.769 × 0.993 of the frame with content touching the edge — because it measures
atom **centres** and knows nothing about the sphere radii, sticks and labels
drawn around them. So the framing pulls back by a fixed fraction. The fraction
is the important part: it is scale-invariant, behaving identically on water and
on a 40-atom system, where the tempting `zoom(1.2)` constant would be tuned on
one and overshoot the other. Measured across water, benzene and a 19 Å chain,
each 0.05 step moves all three by the same ~5%.

`fitView()` deliberately passes no selection, because `zoomTo()` folds every
shape's bounding sphere into the fit — that is what keeps `MoCubeViewer`'s two
volumetric isosurfaces in frame, which extend past the atoms and grow further as
the isovalue drops.

Sizing is a `ResizeObserver`, not an effect keyed on the `height` prop. The prop
covered exactly one case (a panel being expanded) and missed the other: LeftRail
and RightDock are both drag-resizable, so the container's *width* changed and
nothing ever called `resize()` — the canvas kept its old pixel width inside a box
that had grown around it.

### Viewer panels own exactly one overlay control row

`ExpandablePanel`'s expand toggle and the download button each viewer overlays on
itself both claimed `absolute right-1 top-1 z-10`. Equal z-index means DOM order
decides, the viewer's button is the later sibling, and it carries a background —
so it painted over the toggle in every molecule, orbital and vibration panel. The
plots were unaffected only because they have no overlay control of their own.

The fix is structural rather than an offset. The panel renders one
absolutely-positioned row and publishes a slot node through a context; viewers
render into it via `createPortal`, falling back to positioning themselves when
there is no panel above them (`MoleculeViewer` is used both ways). Offsetting one
button to `right-8` would have fixed the instance and left the defect class
intact, with nothing in the tree explaining the offset — the same reasoning F-013
records for the account bar. React portals keep the child in its declared React
tree, so a click on a download button still bubbles through that component's
handlers and never reaches the expand toggle it is now a DOM sibling of.

### Error boundaries are per-region

`PanelErrorBoundary` wraps each major region independently — chat, sidebar,
instrument panel, the KB section, the conversation list, and the job detail
drawer body. React's default behaviour is to unmount the *entire* tree on an
uncaught render error, so one bad field in a single job's summary (a `null` where
`.toFixed()` was called) could blank the whole app rather than just the drawer
showing that job. Each boundary resets independently.

The boundary wrapping the auth gate sits *outside* the shell layout deliberately:
everything else mounts only after a session is confirmed, so a render-time
exception in the login screen itself would otherwise take down the page with no
recovery UI.

---

## Multi-user deployment

Setting `QC_AGENT_DATABASE_URL` activates the auth layer: accounts, sessions,
ownership isolation, admin actions and storage quotas. Without it the app runs in
its original single-user local mode and the auth layer is inert.

### Storage quotas have two regimes

**No auth:** job artifacts capped at a flat total, KB storage capped separately,
both enforced at write time with oldest-first eviction, and both deliberately
sparing content they did not create — a pending job, a pre-seeded manual.

**Auth configured:** both modules defer entirely to a tiered scheme — a per-user
KB quota, a combined per-user job-artifacts-plus-chat-history quota (one shared
pool, since both are "this user's own activity"), and a single global cap across
everything. All three are admin-editable at runtime.

Chat-history bytes are a `pg_column_size` estimate summed across the checkpoint
tables per thread. This closed a real shipped gap: deleting a conversation
removed it from the visible registry but never freed its underlying checkpoint
rows at all.

### The audit log is append-only at the database level

A Postgres trigger rejects `UPDATE`, `DELETE` and `TRUNCATE` outright, confirmed
by direct testing. The lockout-recovery CLI deliberately narrows its own reset to
`DELETE FROM users` rather than `TRUNCATE ... CASCADE`, which would silently wipe
the audit log and bug reports wholesale via Postgres's cascade-truncate
behaviour, regardless of each foreign key's own `ON DELETE` action.

### Lazy singletons need double-checked locking

Building the admin console surfaced a real pre-existing bug by exercise rather
than inspection. The vector store's lazy module-global client had no lock — fine
under the old one-panel-at-a-time load pattern, but the admin console's first
paint fires several KB-touching requests at once, and two worker threads racing
into the constructor hit a genuine thread-safety bug inside chromadb's own
`SharedSystemClient._create_system_if_not_exists` (a bare `KeyError`, reproduced
concurrently, not assumed). Fixed with the same double-checked-locking pattern
the database pool already used.

### Security findings that shaped the code

A dedicated test suite for this layer found and fixed eleven real bugs. The ones
with lasting architectural consequences:

- **Ownership must be recorded inside `submit()`, not after it.** Recording
  ownership once the submit call *returned* still left a window: `submit()`
  writes `spec.json`/`status.json` near the top — making the job visible — and
  then runs a quota pass before returning, measured at ~4 s in a cold process.
  `JobManager.submit()` now records ownership itself, immediately after writing
  those files and before anything else.
- **Deleting a user must cancel their in-flight jobs.** Purging only *terminal*
  jobs is right for routine bulk purges, but at account deletion a still-running
  job kept computing after its ownership row was gone and became a globally
  readable orphan on completion. Deletion now cancels and awaits those jobs
  first.
- **A missing `Origin` header is rejected, not allowed.** The CSRF check
  originally only consulted its allowlist when `Origin` was present. A real
  browser always sends it; a request without one is exactly what the check exists
  to catch.
- **Login timing was an oracle.** The unknown-user branch short-circuited with no
  password hash, while the wrong-password branch ran a real argon2 verification —
  a measurable difference distinguishing "no such user" from "wrong password"
  with identical status codes. Both branches now pay the same cost via a
  module-level dummy hash.
- **Rate limiting keys on the forwarded client IP**, not `request.client.host`,
  which behind a reverse proxy is always the proxy's own address and would put
  every user in one shared bucket. It is a 429 backoff rather than an account
  lockout, deliberately: there is no password-reset flow, so a lockout would
  strand a legitimate user with no recovery path.

### Bug-report attachments sit outside every existing regime, on purpose

Screenshots attached to a bug report are the one user-uploaded file in this app
that is **not** owned, not quota-counted, and not reachable through the ownership
index. Each of those is a decision rather than an omission.

- **Not quota-counted.** They live in `DATA_DIR/bug_reports/<report_id>/`, not
  under `UPLOADS_DIR/<owner>/`, so `usage_report()` never sees them. A bug report
  a user cannot file because they are near their storage cap is worse than the
  bytes it saves. The bound is a hard cap instead: images only, at most 3 per
  report, at most 5MB each — necessary, because `client_max_body_size` is 512m
  and would otherwise be the only limit on the route.
- **Served by an explicitly admin-only handler, never `check_owner_or_admin`.**
  This is the subtle one. Under that helper a resource with *no* ownership row is
  readable by **everyone**, not by no-one — the same shape as the orphaned-job
  finding above. These attachments will never have such a row, so routing them
  through the generic helper would silently make every screenshot public. The
  regression test for it lives in `tests/e2e/ui/ui_06_bug_reports.spec.mjs` and
  asserts a plain 403 for the *reporter themselves*.
- **File cleanup belongs to report deletion, not `purge_user_data`.**
  `bug_reports.user_id` is `ON DELETE SET NULL` and the lockout-recovery CLI
  preserves reports deliberately, so a report outlives its reporter by design. An
  attachment must not vanish while the report it belongs to survives. Postgres
  cascades the attachment *rows*; it cannot cascade into the filesystem, so
  `delete_bug_report()` removes the directory first and the row second.
- **The stored filename is generated server-side.** The uploaded name is
  attacker-controlled and is kept only as `original_name`, for display. The
  content type is sniffed from magic bytes, not read from the client's header.

Archiving is a nullable `archived_at` rather than a third `status` value.
Widening that `CHECK` against a deployed database needs a DROP/ADD constraint
pair, which the `ADD COLUMN IF NOT EXISTS` idiom does not cover and which would
run inside `db.py`'s single all-or-nothing `execute` on every process start. It
also composes: a report can be closed *and* archived.

---

## Known limitations

Stated plainly, because a limitation you know about is cheaper than one you
discover.

**Engine coverage**

- CASPT2 is BAGEL-only; ORCA implements NEVPT2 instead. Oscillator strengths for
  CASSCF and EOM-CCSD are ORCA-only. There is no workaround for either.
- NEB-TS is ORCA-only. PySCF has no native NEB implementation and this project
  does not build one. A PySCF path was assessed as feasible — IDPP for the
  initial path, ASE's climbing-image NEB over a PySCF calculator, then
  `geometric_solver.optimize(transition=True)` to refine — but it would need
  hand-rolled convergence criteria and would run serial per-image evaluations
  with no equivalent to ORCA's image-level parallelism.
- NEB-TS's excited-state path is less verified than its ground-state path. Two
  real runs confirmed the input is generated correctly and drives genuine
  per-iteration excited-state gradient steps, and that a real ORCA-side rejection
  is surfaced as a failed job — but neither reached a converged excited-state
  transition state, so the exact energy-column semantics on a *successful* run
  were not directly confirmed.
- BAGEL's CASSCF/CASPT2 geometry optimisation and frequencies are
  **structurally confirmed and observed executing correctly, not
  convergence-verified end to end.** Minimal runs showed BAGEL genuinely parsing
  and acting on the input shape — real optimiser setup output followed by the
  nested CASSCF starting with correct parameters — but neither was allowed to
  reach full convergence. Re-run a full test before relying on it for a result.
- BAGEL's conical-intersection optimisation has only that same structural
  verification.
- Software this project does not wrap at all (Gaussian, NWChem, Q-Chem, Psi4,
  Molpro) has no execution path whatsoever, by design. `custom` is ORCA/BAGEL
  only. The agent will compose an input file for such a program in its reply and
  say plainly that it cannot run it.

**Scope boundaries**

- Automatic orbital visualisation does not extend to `geometry_optimization`,
  `frequency` or `pes_scan` — extending it would mean deciding which geometry's
  orbitals to export from a multi-step run.
- Constrained geometry optimisation is not implemented. It is feasible on PySCF
  (geomeTRIC's existing `constraints` kwarg) and ORCA (`%geom Constraints`), but
  no equivalent surfaced in BAGEL's manual.
- `pes_scan`'s two-endpoint mode does Cartesian interpolation, not true
  internal-coordinate LIIC. The single-coordinate mode is proper internal-
  coordinate manipulation.
- `plot_job_comparison` supports a fixed set of scalar fields only. It will not
  plot list-valued quantities across jobs, and a request outside the set gets a
  plain "not supported" rather than a guess.
- Hand-editing approval-card input is ORCA/BAGEL only, and its validation is
  structural, not a dry run — neither engine offers one. A syntactically valid
  edit can still fail chemically.

**Known gaps**

- There is no general pre-flight basis-set or keyword validator. An invalid basis
  outside the two narrow corrected cases is still only caught when the engine
  fails at runtime — though the automatic retry cycle often self-corrects exactly
  this.
- Opening a conversation whose agent turn is currently running blocks on that
  thread's lock — measured at 19.5 s for an ordinary turn, longer for an
  investigate-and-retry turn. This is the lock working as designed; what was a
  defect was the UI showing a "start a new conversation" welcome screen during
  the wait, which a user returning to a failed job would read as lost work. It
  now shows an explicit loading state.
- `web_search` is the only component that calls the public internet, and it sends
  query text — which may include job parameters or error messages — to a third
  party. It is ungated, on the reasoning that a search carries the risk profile of
  a search rather than an action, but it is a genuinely different trust boundary
  from everything else here.
- BAGEL's standalone `casscf` job type and agent-driven `pes_scan` are less
  thoroughly tested than other paths.
