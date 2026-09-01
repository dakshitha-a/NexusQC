# NexusQC architecture

How NexusQC is put together, and, more usefully, *why*. Most of what follows
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
| Acting on a failed job | Let the model decide whether to resubmit | Nothing happens until the user presses *Troubleshoot*; the evidence is then gathered by code |
| What parameters a job draft still needs, and what to ask for them | Prose in the system prompt listing requirements per job type | `registry2/elicitation.py`'s `validate_draft()` evaluates declared conditions and hands back the exact question to relay |
| Routing CASSCF to the engine that can compute oscillator strengths | Hope the model infers it from phrasing | `routing.route_engine()` routes on an explicit parameter |
| Consulting the manuals before writing an input | A "use the KB when relevant" instruction | `submit_draft` mechanically runs a KB query before the approval card ever renders |
| Showing a generated plot in the chat | Ask the model to paste a markdown image link | The tool returns a parseable marker the UI renders |

Where behaviour genuinely requires judgement, interpreting a terse human reply
like "1b" against a disambiguation menu, or deciding which of four knowledge
sources fits a question. That *is* the model's job, and the prompt guides it.
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

**One deliberate exception: `geometry_set` (Phase 3) is a job with no
subprocess at all.** It exists to hold 3+ geometries from an uploaded xyz file
that the user can later pull individual frames from into a real calculation,
there is no method/engine/params for a worker to run, so
`JobManager.submit_geometry_set` writes `spec.json`/`status.json`
(`status="completed"` immediately, never "pending"/"running")/`result.json`
directly and returns, never touching `self._executor` or
`app/chemistry/jobs/dispatch.py::resolve_runner` at all. The same reason
`master=True`-but-childless is documented on its `TaskDef` in
`registry2/tasks.py`. Submitting one as a job draft is refused by name
(`dispatch.NOT_YET_IMPLEMENTED`); the only way to create one is
`server/routes/chat.py`'s `attach_upload`.

### Status is written atomically

Status and results are written to `data/jobs/<job_id>/{status,result}.json`
using temp-file-then-rename (`_atomic_write_text`). A plain `write_text`
truncates before writing, which races with the frontend's polling reads and
yields a torn or empty file.

`result_artifact_transaction()` exists for the same class of problem one level
up. Several tools add a key to a completed job's `artifacts` dict. The UV/Vis
plot, the IR plot, the job-comparison chart, the lazy per-orbital cube endpoint.
LangGraph's `ToolNode` can run multiple tool calls from one model turn
concurrently, so two of them racing on the same `job_id` previously meant
whichever wrote last silently discarded the other's key. The transaction makes
that read-modify-write lock-serialised.

### Admission is gated on the whole host, not just this app

`JobManager._wait_for_resources` decides when a queued job may start. An earlier
version tracked only this application's own subprocess trees, which was blind to
load from anything else on the machine. Another tenant could saturate the host
and this app would cheerfully dispatch more work.

The gate now checks two things per poll, both from a single
`psutil.cpu_percent(interval=1.0, percpu=True)` call whose one-second block also
paces the loop:

1. Host-wide CPU and memory below `MAX_CPU_PERCENT` / `MAX_MEM_PERCENT`, a
   coarse "is the machine in distress" backstop.
2. At least `N_CORES` individual logical cores currently idle
   (`CORE_IDLE_THRESHOLD_PERCENT`, default 20% busy). This is kept as a separate
   condition because a low *aggregate* can hide uneven load just as easily as a
   moderate aggregate can hide plenty of idle capacity. In practice this is the
   check that does the real gatekeeping.

There is deliberately **no** additional app-scoped cap limiting this app's own
concurrent jobs to some fixed slice of the machine. That was considered and
rejected: self-limiting to a courtesy ceiling wastes an idle host. **The whole
machine is available**, and load, not a core budget, is what holds jobs back.
All the relevant thresholds are `QC_AGENT_*`-overridable.

### `N_CORES` is per-job width, not a total

`N_CORES` (default **4**) is how many MPI ranks or threads a *single* PySCF,
ORCA or BAGEL job runs on, and correspondingly how many idle cores the gate
above waits to find. With `MAX_CONCURRENT_JOBS` (default **20**) in flight, the
app may use up to 80 cores at once. That is intended: most quantum chemistry
jobs scale poorly past a handful of ranks, so a modest per-job width and a
generous job count uses a large machine far better than one very wide job.

Setting `N_CORES` near the machine's total core count is the one genuinely
dangerous choice, because the two roles interact: the gate then waits for nearly
every core to be simultaneously idle, which on a busy host never happens, and
every job sits at `pending` indefinitely, with no error, no log line, and
nothing in the UI distinguishing it from a legitimately busy machine. The
resolved value is logged at startup specifically so that failure is diagnosable.

**This used to be auto-detected by shelling out to `nproc`, and that was
removed.** It was wrong in both directions. On a host whose shell profile sets
`OMP_NUM_THREADS`, GNU `nproc` reports *that* rather than anything about the
machine, so the value was a stray environment variable, not a measurement.
Inside a container, where no such variable exists, `nproc` reports every host
core, and the idle-core check then waited for hundreds of simultaneously-idle
cores that never materialised: every job hung `pending` forever. That was a real
deployment-blocking bug. A fixed, explicit default cannot fail either way, and
an operator who knows their hardware can still override it.

### How `N_CORES` is actually enforced

Nothing about a job is four cores wide by nature. libgomp, MKL, OpenBLAS and
BAGEL's own task scheduler each use every core on the machine unless told
otherwise, and each of them reads its environment variable exactly once, when
the shared library loads. So the cap has to be in the environment a subprocess
is *created* with, and `app/config.py`'s `engine_thread_env` is the one place
that decides it. `JobManager` applies it to every worker it spawns; ORCA's and
BAGEL's own subprocess launches apply it again on top, so a runner called
directly rather than through a worker is capped too.

The value differs per engine, because they spend their parallelism differently.
PySCF and BAGEL are one process with `N_CORES` threads. ORCA is `N_CORES` *MPI
ranks* -- that is what `%pal nprocs` means -- so each rank gets one thread;
giving each rank `N_CORES` threads would run `N_CORES²` threads for a job
admitted as `N_CORES` wide, and ORCA's own manual asks for one.

Two paths need something beyond the environment. An ORCA input this app did not
build -- a blind job's model-composed text, or an input the user hand-edited on
the approval card -- reaches ORCA verbatim and can name any rank count it likes,
so `_cap_parallelism` clamps `%pal` (in all three spellings ORCA accepts) on the
way to disk; an input asking for fewer ranks keeps what it asked for, since the
number is a ceiling rather than a target. And the lazy orbital-cube route
renders cubes with PySCF *inside the API process*, on a request thread, where no
environment variable set at spawn time can reach and no admission gate applies;
`app/chemistry/jobs/molden.py` therefore calls `lib.num_threads(N_CORES)` at
import, which works at runtime because it is `omp_set_num_threads` underneath.

This was not decoration. Until 2026-08-30 the PySCF cap was an
`os.environ.setdefault("OMP_NUM_THREADS", ...)` placed *after* `import pyscf`,
which reads correctly and does nothing at all: `pyscf.lib.num_threads()`
reported 255 inside the container. That is a job costing sixty times what the
scheduler debited it, so it was not only slower than the same job on four cores
(measured: 2.1x slower for benzene/6-31G* HF) but silently made the admission
gate's arithmetic wrong for every other job in the queue.
`scripts/spikes/spike_thread_caps.py` submits one real job per engine and reads
the answer out of `/proc`, because this is a claim about a running process that
no amount of reading the code can settle.

### A master's dispatch is guarded across processes, not just threads

The scan, ensemble and batch orchestrators each hold a module-level
`threading.Lock` over the "read which sub-jobs exist, dispatch the missing
ones" section. That is the correct guard for the deployment `server/main.py`
produces: `uvicorn.run` is called with no `workers` argument, so there is one
process and one orchestrator, and a single process really does dispatch a
3-point scan as exactly three sub-jobs.

It coordinates nothing between processes, and two things make that reachable.
The first is this repository's own test convention, which submits jobs with
`docker compose exec api python -c ...` -- a second process sharing
`data/jobs/` with the running server. A scan submitted that way has its
initial wave dispatched by the one-shot process while the server's
orchestrator polls the same master, and each can read "index 1 is missing"
before the other's child has its `spec.json` on disk. The signature is
unmistakable and was observed: `_scan_index` values of `[0, 1, 1, 2, 2]` for a
3-point scan, image 0 dispatched once and every later image twice. It is
invisible in the UI, because the children route groups by `_scan_index`, but
each duplicate is a real subprocess holding a scheduler slot and a real job
directory billed to the owner's quota.

It is worth saying what this is *not* justified by, since the obvious second
argument is wrong. A second uvicorn worker would not merely turn this race
into a production bug, because a second worker is not a supported
configuration at all: `JobManager`'s `ThreadPoolExecutor` is sized once at
process start and cannot be resized, which is exactly why
`PATCH /api/admin/config` refuses a `max_concurrent_jobs_total` above it, and
two workers would mean two schedulers and two admission gates long before
dispatch mattered. This guard does not make multi-worker safe and is not a
step toward it.

`base.master_dispatch_guard` takes an `flock` on the master's own
`children.jsonl`, held alongside the existing in-process lock. That file
rather than a new one, because it is precisely what the guarded section
read-modify-writes, and because a lock file of its own would be copied by
`app/chemistry/jobs/copy.py` and packaged into every project zip. It degrades
to a no-op if the lock cannot be taken, since a filesystem without `flock`
must not stop jobs from being dispatched. That degradation is safe when the
call fails outright; it does assume a local filesystem, because a network
mount that accepts `flock` without actually excluding would degrade silently
instead. `data/` is a bind mount here, and `docs/DEPLOYMENT.md` does not
forbid putting it elsewhere.

### Orphaned jobs are reconciled at startup

Worker subprocesses outlive their parent by design, but the code that finalised
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
  can still reach it. Note this uses `psutil.Process.wait()`, not `Popen.wait()`.
It is not this process's child.
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
single model turn can emit several tool calls in one batch, `set_geometry`
plus `start_job_draft`, or two `update_job_draft` calls, which all read the
same pre-batch state. Without a reducer, LangGraph's default channel either
silently drops one write or hard-errors on multiple writes in one step.

### Checkpointer and locking are chosen together

The backend is selected by whether `QC_AGENT_DATABASE_URL` is set.

**Unset (local single-user):** `SqliteSaver` over one process-global
`sqlite3.Connection`.

**Set (multi-user):** `PostgresSaver` built around a `psycopg_pool.ConnectionPool`.
Constructed directly, *not* via `PostgresSaver.from_conn_string`, which
returns a context-manager-wrapped single connection unsuitable as a long-lived
module global. `.setup()` was confirmed idempotent, so it is called
unconditionally rather than needing a separate migration step.

Independent of backend, the original single process-wide `_graph_lock` was
replaced by `_lock_for_thread(config)`, lock striping keyed on `thread_id`. Ten
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
thread blocks trying to acquire it. An `RLock` would not help, reentrancy only
assists the *same* thread. Any legitimate caller must invoke it from a
request-handling thread, strictly after the turn has returned.

---

## The approval gate

Job submission is three tools working together, not one:
`start_job_draft`/`update_job_draft` build a draft incrementally in
`state["job_draft"]`, re-checking it after every change against
`registry2/elicitation.py`'s `validate_draft()`, which decides what's still
missing and, once nothing is, returns a `ready` verdict with a full preview.
Only `submit_draft` (`app/agent/tools.py`) actually gates on a real LangGraph
`interrupt()`, not prompt instructions. It re-validates the draft, resolves
its molecule and builds the real `JobSpec`, then calls `interrupt()`, which
pauses the graph; `graph.invoke()` returns with a `__interrupt__` key instead
of completing. The paused payload is also readable later via
`graph.get_state(config).interrupts`, so reloading the page while an approval
is pending still shows the card.

**The safety property holds even if the model never asks for confirmation,
because the pause is structural.** That's true regardless of which specific
tool trio implements it. It was true of the single `submit_job` tool this
mechanism replaced during the registry v2 overhaul, and it's true of the
three-tool draft/submit split that replaced it, because in both cases the
pause itself is LangGraph machinery, not something the model has to remember
to invoke correctly.

The sharp edge, unchanged by that rebuild: per LangGraph's own documentation,
the graph *"resumes from the start of the node, re-executing all logic."*
Everything before the `interrupt()` runs again on resume and is discarded,
including a freshly built `JobSpec` with a **new random `job_id`**. Two
consequences shaped the design, both still load-bearing in the current
draft/submit split:

1. **`submit_draft` never resolves a molecule *name* itself.** By the time a
   draft reaches `submit_draft`, its molecule is either already sitting in
   `state["molecule"]` (set earlier, in a separate turn, by `set_geometry`,
   the tool that actually talks to PubChem/OPSIN) or is re-read from a
   completed prior job's own geometry on disk
   (`geometry_resolve.resolve_single_completed_geometry`, a local read, not a
   network call). `_resolve_draft_molecule` does that lookup fresh on every
   call rather than trusting a value carried on the draft, specifically so
   the pre-approval render and the post-approval resume agree by
   construction, but neither path ever redoes the network-backed name
   resolution itself. A network lookup redone on every resume could return a
   different molecule than the one approved, or raise on a transient failure
   and crash the approval click outright; keeping that resolution in an
   earlier, separate tool call sidesteps the problem entirely rather than
   guarding against it inline.

2. **The approved spec is round-tripped, not rebuilt.** The interrupt payload
   includes `spec.to_dict()` (`submit_draft`'s `interrupt({...})` call), the
   UI returns that exact dict, and the submitted job is built from
   `decision["spec"]` in `_finish_submission`. What runs is bit-for-bit what
   was shown and approved, regardless of what the discarded re-execution
   produced.

### After the click: the app writes the confirmation, not the model

Approving used to be followed by a full agent turn whose entire output was
narration, along the lines of "the job is now running, I'll report the results
when it finishes". That turn decided nothing. The user had just reviewed the
exact input, the job either runs or fails, and both endings already have their
own paths: the watcher's summary and the failed-job notice. It is a full model
turn against the whole conversation, so it was tens of seconds of silence
between the click and any sign the job had started, and a chance for the model
to restate the id or the parameters wrongly. For scale, drafting turns on this
host were measured at 53 to 77 seconds
(`docs/trackers/2026-08-drafting-outranks-summaries.md`); a narration turn
emits less but pays the same prompt-processing cost, and has not been timed
separately.

So the tools node no longer always hands back to the model. `_after_tools`
routes to a `job_submitted` node, which writes the confirmation itself from a
receipt `_finish_submission` left in `state["pending_submissions"]`, naming the
job through `resolve_job_label` so the message, the job list, the drawer heading
and the download filenames all agree.

Two details carry the weight:

1. **The node runs inside the graph, which `append_notice` does not.** The other
   app-authored messages go through `update_state`, and that discards a pending
   interrupt and destroys an open approval card (see
   `docs/trackers/2026-08-drafting-outranks-summaries.md`). A node cannot do
   that. It also means `_stream_resume` publishes the message as the graph
   streams, so it reaches the browser the moment the node completes.

2. **Only a batch that was nothing but successful submissions short-circuits.**
   `_submissions_this_step` walks back over the trailing run of `ToolMessage`s
   and requires every call in the batch to be answered *and* to have a receipt.
   A rejection, any of `_finish_submission`'s error returns, and a mixed batch
   (the model emitting `check_job_status` alongside `submit_draft`, which real
   conversations do) all still go to the model, because those are exactly the
   results that need relaying. Routing keys on tool call ids, never on message
   prose.

Auto-chaining survives this. When the user asks for several calculations at
once, the model sets `submit_draft`'s `follow_up_work=True`, and
`_after_job_submitted` hands the turn back so it can draft the next card
straight away. The confirmation is still written first, so the user sees it
immediately in that case too; the only difference is whether the turn ends
there.

### The same rule, applied to everything else that decided nothing

A later sweep asked where else this applied, and covered every path that starts
a turn: the three routes in `server/routes/chat.py`, the watcher loop, and all
sixteen tools. Three more places came back, and each took a different shape,
which is the part worth remembering.

**A declined card** is the direct sibling of the confirmation, and got the same
treatment: a `pending_rejections` receipt, a `job_rejected` node,
`_after_job_rejected` for the multi-part case. Two things differ deliberately.
The draft SURVIVES a decline, because the message invites the user to change
something and `update_job_draft` needs a draft to amend. And the wait was worse
here than after an approval, because `JobApprovalCard`'s `onMutate` dismisses
the card on click, so the user sat in front of an empty pane after acting.

**A cancelled job** could NOT use the node pattern, and this is the distinction
to hold onto. A cancellation arrives on the watcher thread with no graph step in
flight, so there is nothing to hang a node off; it takes the `append_notice_
unless_card_pending` path that failures already took. The trap there is the
`seen` bookkeeping: the tick's own `seen` write lives after the agent turn, and
a cancellation-only tick now returns at the guard before reaching it, so the ids
have to be marked seen in the same block that writes their notice or a single
cancelled job re-notifies every two seconds forever.

**A ready draft** is neither, because the judgment cannot move into the app.
"The user asked for this to be run" is a fact about what they said. So the model
still makes it, once, through `run_when_ready`, and the app acts on it when the
draft completes. `_finish_submission` therefore has a second caller now, which
is why `_job_submitted_node`'s boundary condition is re-checked rather than
assumed. One hazard is specific to this path: `interrupt()` aborts the tool node
without committing its writes, so the draft built in the chained call would be
lost, and every `Command` out of `_submit_ready_draft` carries it back.

The dividing line the sweep settled on: a turn earns its keep when the model
must READ something the app holds only as raw data (a finished job's numbers, an
engine's output tail) or must WEIGH something against free text (an active space
against literature notes). It does not when the app already holds the sentence.

### Prompt shape, and why the front of it must not move

Unrelated to turns, found in the same sweep, and worth its own note because
nothing in the codebase reasoned about it before.

An inference server reuses its KV cache for however much of a prompt matches the
previous one from the front. A prompt that only grew is nearly free to process;
one whose start moved by a single message is reprocessed in full. Measured here
against the real system prompt and all sixteen tool schemas, at 31,727 prompt
tokens: an identical prompt 0.31s, one with messages appended 0.57s, one whose
window had slid by one exchange 14.85s, one with the digest line added to the
system message 16.12s.

Two things were defeating that on every long conversation. `_trim_history` took
`messages[-40:]`, so past forty messages the start moved on every append; and
`_digest_line` was appended to the SYSTEM message, which changes whenever a
draft gains a parameter and invalidates the tool schemas along with it.

So the window start is quantized to `LLM_HISTORY_STEP` and moves in blocks, and
the digest travels as a trailing message. A second `SystemMessage` is not an
option, since Ollama's OpenAI-compatible endpoint rejects one outright, so it
goes as a `HumanMessage` marked as a system notice. Over four consecutive agent
steps past the window: 9.69s, 9.66s, 9.65s, 9.70s before; 10.70s once while
cold, then 0.35s, 1.44s, 0.38s after.

Note what this is NOT. It is not the explanation for the 53 to 77 second turns
recorded in earlier trackers: that measurement came from a 30-message
conversation, below the window, where neither effect was active. Below the
window every step is an append and costs well under a second, and what remains
is queueing behind other tenants on the shared GPU, which this app does not
control. This removes a cliff that long conversations fall off, and that is all
it does.

### A turn may not silently lose the results it just fetched

`_trim_history` drops the oldest messages until the prompt fits. It used to do
that with no notion of which messages the answer being written actually
depended on, and the failure that produced was not a shorter prompt but a
wrong answer.

Replaying a real turn: the agent called `check_job_status` four times, and the
trimmer kept the last two and dropped the first two, purely by position. Those
two were the CASSCF and CASPT2 results it had fetched *in order to answer the
question in front of it*. It never saw them, nothing told it they were
missing, and it filled the gap with an active space that sounded right.

Two rules now.

**The current turn is pinned, as a unit with its caller.** `_current_turn_start`
walks back over the tool exchanges the model has issued and not yet answered
from, and then over the contiguous block of human messages that opened the turn
(the user's text plus any job contexts the frontend attached ahead of it). The
pinned unit includes the `AIMessage` carrying the `tool_calls`, not just the
`ToolMessage`s answering them. Pinning the answers while dropping their caller
breaks the call/response pairing and produces the 400 that
`_drop_orphan_tool_messages` exists to prevent.

**Over budget, a result is blanked in place, never removed.** The
`ToolMessage`'s content is replaced with a marker that says the result was
dropped for budget and tells the model to re-fetch the specific fields with
`job_data`; the message and its `tool_call_id` stay exactly where they are. A
marker is self-correcting where a hole is not. The existing `logger.warning`
told the operator something was wrong; nothing told the model, which is what
turned a size problem into a fabrication.

### Hand-editing the input

ORCA (`.inp`) and BAGEL (JSON) inputs can be edited on the approval card before
running. Both are genuine text formats the engine parses itself, so editing
changes nothing about the trust model. The binary was always going to interpret
whatever text it was given.

PySCF has no such file. Its "preview" is a synthetic driver script standing in
for direct API calls, so there is nothing an edit could change at execution
time; it renders read-only.

Edited text is validated (`app/chemistry/jobs/validate.py`) **before** the
approval is spent: balanced ORCA `%...end` blocks including single-line
self-closing ones, a recognised geometry block, valid element symbols; JSON
validity and required blocks for BAGEL. A typo is caught and shown in place with
no model round-trip, and the interrupt stays pending so it can be fixed and
resubmitted. `_finish_submission` (the code that runs once the approval
resumes, carried over unchanged from the pre-rebuild `submit_job` this logic
originally lived in) re-validates server-side as defence in depth.

Because an edit can change what the engine prints, the job-type-specific parser
may not find what it expects. Both runners wrap summary-building in `_safe_parse`,
which turns that into a clear "ran fine but couldn't parse X, raw output at
`<path>`" rather than a bare traceback or, worse, silently wrong numbers.

### Automatic troubleshooting, with a code-enforced budget

A failed job is detected by `app/agent/job_watcher.py`. A background thread that
walks every conversation in the registry rather than being tied to any browser
tab. That matters twice over: closing a tab must not silently stop job notices
working, and two open tabs on the same conversation must not both inject the
same notice.

**A failure starts no agent turn.** The watcher writes a plain notice into the
conversation, "the job failed, I haven't changed anything or resubmitted it".
Via `graph.append_notice()`, a direct `update_state()` write with no LLM call at
all. The notice is a real checkpointed message rather than only an SSE event,
because the user most likely to hit a failure is the one who closed the tab and
came back; it has to be waiting for them.

Only if the user presses *Troubleshoot* does anything else happen. That POSTs to
`/api/threads/{id}/troubleshoot/{job_id}`, which composes one synthetic message
(`app/agent/troubleshoot.py`) carrying the **last 25 lines of the job's real
output, read off disk by code rather than chosen by the model**, and runs it
through the ordinary `_run_turn` path so it gets the thread lock, the SSE
bracketing and the stop button for free. Any corrected job the agent proposes
still pauses on `interrupt()` like any other, so "the agent silently reruns a job
with different parameters" is never possible.

This replaced an auto-retry cycle that investigated and resubmitted on its own
initiative up to a hard cap. Two things were wrong with it: it spent someone's
compute on a guess they had not agreed to, a CASSCF run here can be hours, and
it hid the failure, since the user's first sign of trouble was a new approval
card rather than a clear statement that their calculation had died.

### A background turn must announce itself

A troubleshooting turn runs through `invoke_turn`, which holds the conversation's
`_lock_for_thread` for the whole ReAct loop. A user message posted meanwhile
takes the same lock inside `stream_turn_tokens`. Acquired lazily on the first
`next()`, so its SSE stream opens successfully and then produces nothing at all
until the background turn finishes.

That serialisation is deliberate and correct; one conversation's turns must not
interleave. The defect was that it was **invisible**. A background turn set
neither `turnInProgress` nor `pendingApproval`, the two things that make the
composer show a busy state, so the UI looked completely idle while messages
piled up behind the lock.

The scale is what made it a bug report rather than a nitpick. Measured from the
checkpoint history of a real incident: a single agent loop step takes 26–40 s,
complete turns 53–77 s, and a troubleshooting turn is several LLM round
trips longer still. Two prompts sent during one therefore looked exactly like a
hang, and then "suddenly started again" when the lock was released and both ran.

So `job_watcher` emits `turn_start` before the ReAct loop, and the chat renders
a distinct notice for it. Three details are load-bearing:

- It is emitted once the thread lock is held and the hold check has passed
  (`invoke_turn_if_idle`'s `on_start`), immediately before the loop itself.
  Earlier than that would announce turns that then defer to a draft; later
  would leave the wait silent. Waiting for the lock is not silent either: it
  only happens while another turn is running, and that turn has announced
  itself. `read_state` is lock-free and so does not need to be sequenced
  around this.
- It is paired with `turn_complete` from a `finally`, and both are guarded on
  the turn actually having started. A failed turn must not leave the UI
  claiming a background turn is running for ever, and a deferred one must not
  emit a `turn_complete` for a `turn_start` the frontend never saw.
- It sets its own store flag rather than reusing `turnInProgress`, which
  *disables* the composer. Reusing it would have converted an invisible wait
  into a lock-out, which is a different and worse behaviour: the user's message
  is accepted and answered as soon as the lock frees, and only ever needed
  saying so.

The same contention is why `chatStore`'s `threadLoading` exists. Opening a
conversation calls `GET /api/threads/{id}/state`, which takes that thread's lock
and so blocks behind a running turn.

The budget is **not** read from anything the model supplies.
`count_failed_in_chain()` walks the retry chain backwards on disk via each job's
`params["_retried_from"]` and counts current failures; `job_watcher` calls it
directly to decide between a retry notice and a stop-and-explain notice. A
model-tracked counter keyed on an optional argument it might simply omit resets
to zero for free.

---

### Drafting outranks summarising, and the check has to be inside the lock

A background turn announcing itself was only half the problem. The other half
was that it should not have been running at all.

The trigger was a user asking "where is the card for the casscf job?" twice in
one conversation. A job had finished while they were mid-draft, the watcher
injected its "Job X finished, summarise it" notice, and the turn that followed
destroyed the approval card. That thread now carries five `submit_draft` tool
calls that no `ToolMessage` ever answered.

**The destruction is literal, and worth stating precisely, because "a badly
timed message" would not justify any of this.** Invoking the graph with new
input while it sits at `submit_draft`'s `interrupt()` discards the pending
task. Measured on the real topology: `interrupts` one to zero, `next` from
`("tools",)` to `()`, the tool call orphaned permanently, and the user's later
Approve a silent no-op. `update_state` does exactly the same thing, which
matters because that is the innocent-looking call a failed job's notice uses.
Both are asserted directly in `tests/backend/draft_01_summary_defer.py` so that
nobody has to take it on trust, and so the gates cannot be relaxed by accident.

Two holes let it happen, and fixing either alone leaves the bug:

- **The guard ran outside the lock.** `_poll_once` checked `pending_approval`
  before calling `invoke_turn`, and `invoke_turn` is what takes the lock. With
  turns at 53–77 s and a two-second poll, the watcher took about thirty
  snapshots *inside* a drafting turn, every one before the interrupt was
  committed, then blocked on the lock and was let in at exactly the moment the
  card appeared. That is the ordinary path, not a race.
- **The elicitation phase was unguarded.** Everything before `submit_draft`
  has no interrupt to detect at all.

`job_draft` cannot serve as the signal. `CLEAR_DRAFT` is defined in
`app/agent/state.py` and nothing has ever written it, so a draft outlives both
its submission and its rejection; the field is true forever after a
conversation's first draft. That is deliberate and worth keeping, because a
draft surviving a rejection is what lets someone say "use cc-pvdz instead" and
have `update_job_draft` amend the thing they just declined. So a separate
`draft_status` spans exactly the drafting episode, stamped by `_draft_command`
(the single funnel both draft tools pass through) and cleared by
`_finish_submission` on both branches, which are the two endings.

`invoke_turn_if_idle` is the load-bearing piece: it re-evaluates
`draft_hold_reason` **while holding the thread lock**, and declines rather than
running. The watcher's own pre-lock check is only a cheap fast path.

Three consequences worth knowing:

- A held summary is not lost. The job stays out of `_seen`, and the first tick
  after the draft resolves delivers every job that finished during the hold in
  one turn rather than one per job.
- `job_update` events still fire throughout, so the jobs panel shows the job
  reaching `completed` live. Without that a held summary would be
  indistinguishable from a stalled job.
- A draft nobody ever finishes would otherwise suppress that conversation's
  summaries for good, which breaks the leave-and-return workflow the job
  system exists for. `QC_AGENT_DRAFT_HOLD_SECONDS` (default 900, `0` to hold
  strictly) expires it, timed from the last draft mutation. Deliberately not
  from the thread registry's `last_active_at`: the watcher bumps that itself
  when it writes a failure notice, which would restart the clock on a draft
  nobody was working on.

Failures are the one exception. A dying job still says so immediately during a
draft, because that notice runs no LLM and asks the agent for nothing. It waits
only while a card is genuinely open, since `update_state` destroys a pending
interrupt just as thoroughly as invoking does.

---

### One vocabulary per quantity, written where a result is stored

`summary` used to be an untyped dict each runner built as a literal, so the
same physical quantity had a different name in every engine. A ground-state
energy was `state_energies_hartree[0]` in a BAGEL CASSCF job,
`ground_state_ccsd_energy_hartree` in EOM-CCSD, `ground_state_energy_hartree`
in TDDFT and `final_energy_hartree` in an optimization. `casscf_energy_hartree`
was written as null while the value it names sat one key away. `n_states`
counted state-averaged roots *including* the ground state for a multireference
method and excited states *above* it for a single-reference one, under one key.
Nothing named the HOMO at all.

That was not only a tidiness problem, and the way it failed is the argument for
fixing it. Asked to tabulate the ground-state energies of six uracil jobs, the
agent reported an active space of (6e,6o) for a job whose spec says twelve
electrons in nine orbitals, and then wrote a paragraph of physical reasoning
about why "a small (6e,6o) active space" behaves as it does. Every number it
needed was on disk and correct.

`app/chemistry/jobs/facts.py` defines one name per quantity and
`base.write_result` applies it, which is the single point every result reaches
disk through: three engine workers, four orchestrators and the account-deletion
sweeper all funnel there. So what is stored is canonical, and no reader needs a
translation layer.

Three decisions inside it are easy to get wrong later.

**It is applied at persistence, not in each runner.** A runner function's
direct return value still carries its own literal key names; only the stored
result is canonical. Normalizing at the boundary was worth far more than
editing forty summary literals across three runners and risking a typo in one.
Nothing in the app consumes a runner's return except the worker that
immediately persists it, so the seam is visible only to a test that calls a
runner directly, and `tests/backend`'s `opt_01`, `active_01` and `p8_01` do
exactly that, deliberately.

**`_resolve_field_path`'s contract survives untouched.** That function
consults no schema of known names ahead of a job's real summary, and it still
doesn't. The names it introspects simply became consistent, because that is
what got written. This is the same reason `_COMPARISON_FIELD_ALIASES` and the
`homo`/`lumo` shortcuts sit *outside* it: they only ever choose which literal
path to ask for.

**Derived frontier energies are nullable, and that is the point.** BAGEL's
molden export writes `energy_eV = 0.0` for every active-space orbital, because
a multi-configurational active orbital has no single-particle Fock eigenvalue.
The HOMO of a CASSCF job *is* an active orbital, so the obvious derivation
returns 0.0: a plausible-looking float that is not an energy. Emitting it would
be the app manufacturing exactly the class of confident, baseless number the
vocabulary exists to stop the model inventing. `homo_energy_eV` is null there,
with the reason alongside, and the index and occupancy still reported.

### Bulk fields are described, not printed

`facts.BULK_FIELDS` names the arrays that are stored but must never render
into an LLM payload as values: `orbital_table` above all, plus `normal_modes`,
gradients, NAC vectors and the per-image energy grids. A text rendering shows
their shape (`orbital_table [132 orbitals]`) and the agent asks `job_data` for
a window when it needs one.

The measurement that forced this: across one six-job conversation,
`orbital_table` was 250,770 of 302,315 characters, 83% of everything the model
was given, and the same job's copy was paid for again on every refetch. The
data has not moved. The job drawer, the MO viewer and the cube endpoint all
still read it out of `result.json`.

### What the agent can see about an attached job

`job_context_summary` (`app/chemistry/jobs/summarize.py`) is the entirety of what
the model knows about a job the user attached to a prompt. The same text also
backs `check_job_status`, so there is no second channel.

It originally emitted the job's own `job_type`/`engine`/`params` only in the
*failed* branch, on the reasoning that a retry needs to know what it is retrying.
That left a gap for every job type. A completed job's `summary` dict carries none
of its own input settings: no `method`, no `basis`, no `functional`, verified
against real results on disk, not assumed. So an ordinary request like *"use the
same method and basis as the attached job"* or *"run that again with a bigger
basis"* was unanswerable from any tool the agent has, and the model's only
options were to ask or to invent a level of theory.

Inventing one is caught by nothing downstream. The approval card faithfully
displays whatever was picked, and a user who trusts their own phrasing reads it
as inherited. The line is now emitted for completed jobs too; params beginning
with `_` stay hidden, since those are internal plumbing rather than anything a
user chose.

The same gap existed for structures. The energies along a scan or interpolated
path were in the summary table, but the geometries behind them were not, so
*"optimize image 5"* or *"run a frequency job at the top of the barrier"* had
nothing to resolve against: the model could see that image 5 exists and what it
costs, but not what it is. Every attached job now carries its structures as xyz
blocks, in the exact shape `set_geometry` accepts back, so acting on one needs
no new tool.

Three details of that are deliberate rather than incidental:

- **A still-running path carries them too.** A master's geometries are written
  in full when it is submitted, not as its images finish, so unlike the energies
  they are complete from the job's first moment. Starting a new job from one
  image while the rest of the path runs is a normal thing to want.
- **A statistical ensemble is excluded.** A Wigner ensemble's samples are a
  random cloud around one equilibrium structure; nobody asks to run a job from
  sample 37, the distribution is the point, and at up to 500 samples it is by
  far the largest of these. Every other multi-geometry job is an ordered set
  someone names an element of, an NEB band's transition state most of all.
- **It is bounded by atoms times images**, not by image count. This text is the
  model's input on every status check, not only on an attach, so it has to be
  paid for repeatedly. Past the limit the endpoints are printed and the middle
  is described, since the two ends are what a user names most often.

Naming one of those images is a draft's `source_geometry_job_id` plus
`source_geometry_image`, counting from 1 as the drawer and every message about
a path already do. A master job stays refused as a geometry source *without* an
image: picking one of several arbitrarily would be a wrong answer rather than a
convenience, and the refusal now says which parameter names one. The geometry
comes from the same path file the frame viewer reads, so a job started from
image 5 runs on exactly the structure the user was looking at when they said
"image 5" -- to the file's eight decimals, which is where the images
themselves are recorded.

### Which geometry a Wigner ensemble is "around"

An ensemble displaces its samples from one structure, and three places need to
know which one: the approval-card preview, the post-approval re-derivation that
rebuilds the samples deterministically, and the geometry-parameter histograms,
which mark it as a red dashed line so a distribution says what it spread *from*
and not only how far.

The rule is not obvious and getting it wrong is silent. An `opt_freq` job's
`spec.molecule` is the PRE-optimization input; `summary.optimized_molecule` is
the minimum its normal modes were computed at. A plain `freq` job was run AT
its `spec.molecule`, so there that field is the minimum. Sampling around an
optimization's input geometry would displace every sample from a structure the
modes do not describe, and the ensemble would still look perfectly normal.

It is also not the first sample, which a reader reasonably guesses: a Wigner
ensemble displaces every sample, sample 1 included, so it sits no closer to the
equilibrium than any other.

`geometry_resolve.equilibrium_geometry_of_source` is now the one place that
rule lives, with `equilibrium_geometry_for_ensemble` looking the source job up
from a master's own `source_frequency_job_id`. It was previously written out at
all three call sites, each carrying a comment saying the others had to be kept
in step — which is the point at which a comment should have been a function.

### One spectrum, three origins

`app/chemistry/jobs/spectrum_source.py` answers "what is this job's spectrum?"
for the three job types that have one, and both the tagged-job context and the
overlay plot read it rather than each building a curve of their own.

The origins genuinely differ. A `wigner_spectra` master has already pooled
every sample's transitions and written a broadened curve to
`artifacts.ensemble_spectrum_data`, so that file is read rather than the
pooling being done again. A `single_point/ee` job has excitation energies and
oscillator strengths, and a `freq` job has frequencies and IR intensities;
those are sticks, and the curve is built by broadening them at the same widths
the single-job plots use, so a curve taken from here and one drawn by
`plot(kind="uvvis")` are the same curve rather than two broadenings of the same
data.

**Everything it returns peaks at 1.** The ensemble file already does; the two
stick paths are normalized to match. Without that, an overlay mixing a Wigner
spectrum with a TDDFT one shows the first at 1.0 and the second at raw
oscillator-strength scale, which looks like a result rather than a units
mistake.

`plot(kind="spectra")` is the shape the other plots could not make: `uvvis`,
`ir` and `ensemble` each draw one job, and a custom plot resolves one value per
job across several. Neither can put N curves on one x axis, which is what
comparing methods means. Every curve is resampled onto one shared grid spanning
the union of their ranges, because each source builds its own grid from its own
data and two methods' curves are otherwise not comparable point-for-point, and
each is renormalized *after* that resampling: the shared grid does not land
exactly on a curve's own maximum, so an already-normalized curve comes off it
peaking at 0.99996, and the invariant should hold of what is drawn rather than
of what was drawn from. Each curve keeps its own peak rather than sharing one
divisor, which the user chose directly: shapes and band positions compare, and
no curve disagrees with how that same spectrum looks on its own.

An IR spectrum and a UV/Vis one are refused as a pair rather than converted
onto one scale. Both axes are energy and `convert_energy_units` would happily
turn cm-1 into eV, but a vibrational band and an electronic transition on one
axis is a picture of nothing.

### Energy units

`app/chemistry/units.py` holds one conversion table for hartree, eV, nm and
cm-1, and both the agent's `convert_energy_units` tool and the custom-plot path
use it. Two implementations of the same table is the failure this exists to
prevent: a number in a reply disagreeing with the number on an axis is
invisible until someone lines up two figures.

Three of the four units are a scale factor apart. nm is not: a wavelength is
inversely proportional to an energy, so it converts through the reciprocal, a
value in nm has to be positive, and an energy of exactly zero has no wavelength
rather than an infinite one.

That is also why a **relative** energy can be reported in hartree or eV and in
nothing else. A custom plot takes `y_reference_hartree`, an absolute energy to
measure from, which turns every value into a difference; *"0.4 eV above the
ground state"* is a sentence and *"0.4 nm above the ground state"* is not, so
nm and cm-1 are refused there with that reason. The restriction is on the
reference, not on the units: asked for absolute energies, the same code
converts all four in both directions, which is what answers *"that absorption
is at 480 nm, what is that in eV"*.

A series' source unit comes from the field's own name (`energies_hartree`,
`excitation_energies_eV`, `frequencies_cm-1`), since this project already
writes the unit into the name. A field whose name is silent, such as
`state_energies_per_image`, is asked about via `y_units_from` rather than
assumed to be hartree: relabelling an axis without changing the numbers is the
one mistake here with no visible symptom. `kcal/mol` is recognised by name for
exactly the same reason, purely so a field in it is refused as kcal/mol instead
of read as hartree.

## Engine integration

### The runner/worker pair

Each engine has `{engine}_runner.py` with pure functions
`run_<method>(molecule, params) -> {"summary": ..., "artifacts": ...}`, and
`{engine}_worker.py` as the subprocess entrypoint that dispatches by method name.

`app/chemistry/registry2/` is the single source of truth for what a job needs
and where it runs. Not one flat file, but three modules with separate jobs:
`tasks.py`'s `TASKS` dict says which `(task, subtype)` pairs exist and which
capability properties each one needs (`TaskDef.requires`); `capabilities.py`'s
`CAPABILITIES` table says which `(engine, method)` pairs actually have those
properties, evidence-graded rather than assumed; and `routing.py`'s
`route_engine()` combines the two into an actual engine choice, in
`ENGINE_PREFERENCE` order unless a hard rule overrides it (CASPT2 always goes
to BAGEL; a CASSCF job wanting oscillator strengths always goes to ORCA).
`registry2/elicitation.py`'s `validate_draft()` is what the `start_job_draft`/
`update_job_draft`/`submit_draft` tool trio calls on every draft change to
decide what's still missing and what to ask for it, rather than hardcoding
elicitation logic per method the way the pre-overhaul single flat registry
did.

### Text parsing is derived from real runs

PySCF results come straight from its own Python objects. ORCA and BAGEL have no
structured output, so their runners regex-parse plain text, and **every one of
those patterns was derived from actual runs**, not from documentation, because
exact stdout formatting is not guaranteed across versions.

A representative example of why this matters: **ORCA's default `ORBITAL ENERGIES`
output is silently truncated to the first 10 virtual orbitals**, with a literal
`*Only the first 10 virtual orbitals were printed.` line. Confirmed on a real
def2-SVP water run: 24 basis functions, 16 rows printed. Adding `LargePrint`
forces the full table, but `LargePrint` *also* dumps the full MO coefficient
matrix immediately afterwards with no blank line between. The original parser
matched to the next blank line and would have absorbed that unrelated section.
`_orbital_energy_rows` now scans row-by-row from the header and stops at the
first line that doesn't match the four-column shape, which naturally handles both
the truncation notice and the coefficient dump without special-casing either.

### Excited states route through a shared task, not one job type per method

Rather than one job type per method: `single_point/ee`'s `method` (`hf` vs
`dft`) combined with `use_tda` covers CIS, TD-HF/RPA, TDA-DFT and TDDFT.
There is no separate `tddft` task at all. PySCF's `tdscf.TDA`/`TDDFT` are
dispatchers that pick their implementation from the reference wavefunction's
type, and an HF reference has no XC kernel, so TDA-on-HF *is* CIS. ORCA's
`%tddft` module makes the same selection. Confirmed: energies and oscillator
strengths from a real ORCA CIS run agree with PySCF's
`tdscf.TDA(scf.RHF(...))` to five decimal places.

`use_tda` defaults to **False**. The complete linear response, so full TDDFT
with a DFT reference and TD-HF/RPA with an HF one. It defaulted to True until
Phase 2, which meant a user asking for "a TDDFT spectrum" got TDA and a job
card that said TDDFT. TDA is cheaper and less prone to triplet instabilities,
which is a good reason to offer it and not a good reason to substitute it
silently; it stays available as an explicit choice, and the approval card now
names which of the four is actually being run.

`eom_ccsd` is its own *method* value (on `single_point/gs` or `single_point/ee`,
not a separate task) because PySCF's `EOMEESinglet` has **no**
oscillator-strength or transition-dipole support at all, while ORCA's MDCI
module computes them by default. `routing.route_engine()` picks ORCA for it
in ordinary preference order (PySCF has no hard-rule exception here, it's
simply not first for this method), with PySCF still available for energies
only.

CASSCF has the same asymmetry: only ORCA computes oscillator strengths for it
here, given `DoDipoleLength true`. This is one of exactly two mechanical
overrides in `routing.py`'s `_hard_rule()`: a CASSCF draft carrying
`want_oscillator_strengths=True` is routed to ORCA regardless of preference
order, deliberately not left to the model to infer from phrasing. (The other
hard rule is CASPT2, always BAGEL, see the capability table above.)

CASPT2 is BAGEL-only and energies-only; ORCA implements NEVPT2, not CASPT2.

### Several states or pairs are one job, and the engines differ underneath

A gradient job takes `target_states` and a coupling job takes `state_pairs`,
both lists, and one job returns one result per entry. That is the request
shape on every engine, even though what happens underneath is different in
each: BAGEL emits one `forces` block whose `grads` list carries an entry per
target and serves all of them from a single converged wavefunction; PySCF
converges the state average once and calls its coupling or gradient kernel
per entry against that same object; ORCA takes one `IROOT` per run and one
state per `.engrad`, so several targets mean several ORCA processes, one
per subdirectory, with a combined raw output at the top level. Which of
those an engine does is recorded in `MethodCaps.multi_state_gradient` and
`nac_multi_pair`, an axis the capability matrix did not have before -- every
other field answers "can it at all", these two answer "how many at once".
A False is never a refusal, only a cost: the runner still returns every
result asked for, it just converges the wavefunction more than once.

Keeping the request shape uniform is deliberate. Which engine batches
internally is not something a user asking for the couplings between three
state pairs should have to know, and it is exactly the kind of detail that
would otherwise leak into the elicitation flow as a question nobody can
answer.

Both result shapes are built in `app/chemistry/jobs/derivatives.py` rather
than assembled in each runner, and that is a direct consequence of how the
bug that prompted this work survived. Three runners were producing the same
result dict independently, nothing anywhere stated what a coupling result
was supposed to look like, and so nothing noticed that BAGEL's parser took
the LAST gradient block (`sections[-1]`) while its energy gap and oscillator
strength took the FIRST regex match. With one pair that is invisible. With
three it reports pair 3's vector beside pair 1's gap and looks entirely
normal doing it. The parser now segments BAGEL's output on the engine's own
`NACME Target states` announcement and keys each coupling by the targets
BAGEL says it computed, not by position in the request -- which is what
makes a mismatch between what was asked and what ran detectable at all.
Every key is present in every entry from every engine, `None` where an
engine does not report it, so a missing value means "this engine does not
report it" and never "this result came from the other engine".

Which STATES a gradient may be taken on is a narrower question than which
methods have a gradient, and conflating the two produced a wrong answer that
looked right. `single_point/grad` requires only the `gradient` capability, so
every engine with a gradient is a routing candidate; preference order then
picks PySCF, whose CASSCF row has no excited-state gradient at all. A batch
asking for S0/S1/S2 therefore returned thirteen ground-state gradients and
said nothing. `route_engine` now filters candidates on `excited_gradient`
whenever `target_states` names a state above 1 -- the same filter it already
applied for oscillator strengths, for the same reason -- and refuses an
explicitly requested engine that lacks it rather than letting the draft reach
READY and fail at spec-build.

The capability table itself was part of that failure, and the lesson
generalizes past this one row. `orca/casscf` claimed `excited_gradient=True`
on `manual` evidence: "documented for a CASSCF root; not executed here". ORCA
does document it. This app's ORCA CASSCF gradient branch emits a
byte-identical input whichever state is named -- there is no root selector --
so a three-state request would have run one calculation three times and
labelled the answer S0, S1 and S2. `manual` is a TRUSTED level, so the
untested claim was gating routing. What a capability cell has to describe is
what THIS APP can deliver, not what the engine's manual promises, and an
untested claim that routes is worse than no claim: it converts a missing
feature into a wrong number. The row is now `False` with a `gap` recording the
diff, and BAGEL's identical claim was upgraded to `run` only once three
targets in one input returned three genuinely distinct norms -- distinctness
being what proves a target is honoured rather than ignored.

One numbering trap is worth stating, because there are two conventions in
the codebase and they differ by one. `target_states` and `state_pairs` are
1-based INCLUDING the ground state: state 1 is S0, and `[[1, 2]]` is the
S0/S1 coupling. The older scalar `target_state`, still used by `opt`,
`freq`, `opt_freq` and `neb_ts`, counts the other way -- 0 or absent means
the ground state. `single_point/grad` was moved off the scalar rather than
overloading it, and the excited-state capability guard asks
`_excited_state_requested` rather than testing one key, because reading
`target_states=[1]` as truthy would refuse an ordinary ground-state
gradient while reading it as a `target_state` would silently compute the
wrong surface.

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
works directly. It has **no** analytic CASSCF Hessian, `pyscf.hessian.casscf`
does not exist, so frequencies use a hand-rolled `_numerical_casscf_hessian()`:
central differences of a gradient scanner over all `3*natm` displacements,
assembled into the exact `(natm, natm, 3, 3)` shape the analytic path produces so
it drops into the existing thermochemistry calls unchanged. This is O(6·natm)
full CASSCF solves, markedly slower than an analytic Hessian.

**ORCA** has an analytic gradient but a numerical-only Hessian, so CASSCF
optimisation uses `! Opt` while frequencies need `! NumFreq`. Verified live: a
water CASSCF(4,4)/STO-3G optimisation converged in 5 steps with genuinely
fractional natural-orbital occupations (1.9979 / 1.9874 / 0.0133 / 0.0014), and a
frequency run at that geometry gave 3 real frequencies with the 6
translational/rotational modes projected to exactly 0.0.

**BAGEL** accepts a nested `"method"` array inside `optimize`/`hessian` blocks,
using the same per-method dict shapes already built for the plain job types.
This support is *structurally confirmed and observed executing correctly* rather
than *convergence-verified end to end*. See [Known limitations](#known-limitations).

### `blind` jobs

`task='blind'` runs an arbitrary ORCA or BAGEL calculation through the same
approval and execution pipeline, with the agent (or the user, pasting their
own input verbatim) supplying the complete input text itself, run byte for
byte with no structured parameter building. This needed almost no new
machinery: worker dispatch is already generic over `(method, engine)`,
validation does not look at task, and the approval card's editable-textarea
branching keys purely on engine. PySCF is deliberately excluded from this
path entirely. A blind PySCF input would be user-supplied Python, and this
app never executes that, at any confidence level (see `elicitation.py`'s
handling of a sniffed-but-unexecutable PySCF script, which offers to build
the equivalent structured job instead of running the pasted code).

Structural validation is deliberately **non-blocking** here. Unlike every other
job type, where the input started from a generated, standard-geometry template,
so a validation failure means something broke. A custom job's entire purpose is
carrying syntax the validator was never built to recognise. Hard-blocking would
defeat the premise. Complaints surface as a "structural check found possible
issues (not blocking)" banner, deliberately *not* reusing the existing
auto-correction channel whose banner reads "Auto-corrected:" and would
misrepresent a complaint as a change actually made.

ORCA's normal success marker (`FINAL SINGLE POINT ENERGY`) is specific to
SCF-based job types, so custom jobs use `_write_and_run_generic`, which checks for
`ORCA TERMINATED NORMALLY` instead, confirmed calculation-type-agnostic across
real job output.

### Parameter repair is narrow and verified

`app/chemistry/jobs/param_normalize.py` corrects two specific, previously-observed
typo classes before validation, rather than relying on the model's retry loop.

`normalize_method` handles the fact that this app's `method` parameter only ever
means `hf` or `dft` for most job types, restricted vs unrestricted reference is
chosen automatically from spin, never exposed, so RHF/UHF/ROHF and misspellings
collapse to `hf` via an alias table plus a tight fuzzy fallback.

`normalize_basis` targets exactly one shape: a Pople basis name with a
polarisation suffix glued on without parentheses (`6-31gd`), which a real job hit
and failed on with an unhelpful `KeyError`. The repair is re-verified against
PySCF's own parser before being accepted. Necessary because PySCF was found to
silently accept *and discard* an unrecognised parenthesised suffix (`6-31G(zzz)`
loads as plain unpolarised 6-31G), which would otherwise let the repair mask
nonsense instead of catching it.

Both are deliberately narrow. An unrecognised value falls through to the existing
error path untouched, never silently guessed at. Corrections are surfaced on the
approval card, not applied invisibly.

---

### Basis Set Exchange is an escape hatch, not a replacement

The keyword menus above suggest names each engine actually recognises. When none
of them is what the user meant, an exotic, relativistic or ECP basis. The
menu's last entry offers a Basis Set Exchange search, and `resolve_basis_from_bse`
confirms the candidate covers every element in the current molecule before
telling the agent it is usable. Same "never offer a candidate that doesn't
validate" discipline as the rest of `keyword_suggest.py`.

The sentinel is appended *only* alongside at least one real suggestion, which
preserves the existing contract that a menu with nothing to disambiguate is not
shown at all.

The `basis_set_exchange` package is fully offline, the basis data ships inside
the wheel, so unlike every other external integration here (PubChem, Semantic
Scholar, web search) there is no timeout, no cache-of-a-network-fetch, and no
failure mode to design around. `params["basis"]` carries a plain `bse:<name>`
sentinel and every engine translates it lazily inside its own runner, at the
point it already turns `basis` into something it can run, so nothing upstream,
param normalisation, engine resolution, the interrupt/resume boundary, changed
shape.

Per-engine translation is where the real work was, and two findings came from
checking against reality rather than documentation:

- **BAGEL** never uses a multi-row contraction. A general contraction is instead
  several shell entries sharing one `prim` list. Established by diffing against
  a real installed BAGEL basis file, after a first attempt preserved BSE's own
  general-contraction shape. The translator therefore uncontracts general
  contractions first, and uncontracts combined shells with `max_am=0` rather than
  the `max_am=1` BSE's own GAMESS-US/ORCA writers use, because BAGEL has no
  combined-shell concept. Output is cached by content hash under
  `DATA_DIR/bse_basis_cache/` and referenced by absolute path, which BAGEL's
  manual explicitly supports. Necessary because a BAGEL install's own `share/`
  directory is typically not writable by this app.
- **ORCA's `fmt="orca"` is a naming trap.** It emits GAMESS-US's `$DATA` wrapper,
  not ORCA's `%basis NewGTO ... end` syntax. The translator fetches
  `fmt="gamess_us"` per element and rewraps it. Confirmed against a real run that
  the basis keyword can be omitted from the `!` line entirely when a `%basis`
  block supplies it.

BAGEL mandates a density-fitting basis with no "off" mode, so `df_basis`
resolution tries the existing family map first, then BSE's own role metadata
(`jkfit`, then `rifit`, which of those exists is family-dependent), and only
then a generic fallback.

ECP handling is explicitly out of scope: ECP-named entries pass harmlessly
through the suggestion pools, but nothing special-cases core-electron counting or
ECP/basis pairing.

## Orbitals and molden

MO cube visualisation works identically across all three engines via a shared
parsing layer (`app/chemistry/jobs/molden.py`), but each engine reaches a correct
cube by a different route. **This was confirmed by point-sampling AO evaluation
against native PySCF calculations at several off-axis points**. Not by
inspection, and not by cheap self-consistency checks, which turned out to be
actively misleading.

`pyscf.tools.molden.load()`'s return shape depends on whether the file has one MO
section (restricted, flat arrays) or two (genuinely unrestricted, a 2-tuple),
so every function normalises to a flat, 1-based, optionally spin-labelled list up
front.

**PySCF** needs no round-trip for its own cubes, but writes a molden export
anyway so the lazy per-orbital endpoint can treat all three engines uniformly.

**BAGEL**'s molden export round-trips exactly. AO evaluation matched a native
PySCF calculation to a ratio of 1.0 at every sampled point. Its own native
`moprint` block was tried first and rejected: those cubes are per-orbital
electron *density* (`|ψ|²`, non-negative, symmetric double lobe with a node at
the bond centre) rather than the signed amplitude a two-isosurface viewer needs,
and carry no per-orbital energy table.

**ORCA**'s molden export is the case that does *not* round-trip despite passing
every cheap check. It parses without error, and both individual AOs and the
target MO pass a naive self-overlap check of 1.0. Point-sampling showed each AO
column scaled by a different, shell-dependent constant relative to native
evaluation of the same basis (~0.35x / 1.1x / 0.5–0.6x for different shell types).
Consistent with a contraction-coefficient normalisation mismatch, not a
sign-or-ordering difference, which would give ratios of exactly ±1. ORCA's cubes
therefore come from `orca_plot`, ORCA's own generator, driven via piped stdin
against a completed job's `.gbw` file.

### Orbitals are available on every relevant completed job

Every `single_point` subtype and every CASSCF/CASPT2 job writes a molden
export and an `orbital_table`, at negligible marginal cost since the
wavefunction is already computed. There is deliberately no separate task for
this, `registry2/tasks.py`'s own module docstring is explicit that orbital
rendering is a *presentation* of a `single_point` job, not a different
calculation to ask for, so `orbital_indices` is just one of `single_point`'s
own parameters (`registry2/params.py`) rather than its own job type. Any
orbital can additionally be rendered lazily on click, cached into
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
occupation flattened to integer 0/2 and every orbital energy 0.0. BAGEL's
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
Cartesian displacement matrix. Its own header confirms the mass-weighting has
been undone, i.e. these are real-space displacements. BAGEL's equivalent is under
a section titled "corresponding cartesian eigenvectors". Critically **not** the
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
not render a flat line when oscillator strengths are missing, `None`, or all zero.
Exactly the situation for a PySCF `eom_ccsd`/`casscf` job or any CASPT2 job.

What changed in that rule is its granularity, not the rule. A field path that is
missing from *one* job in a multi-job chart now leaves a gap at that column and
names the omission in the reply, rather than dropping the job from the chart
entirely. The old behaviour was itself a quiet fabrication: comparing oscillator
strengths across seven methods silently produced a five-method chart, because
EOM-CCSD and PySCF CASSCF report no oscillator strengths, and nothing on the
picture said they had been asked. A plot is refused outright only when nothing
requested resolves anywhere, and that refusal lists the real reason, since a
field that is absent and a field that is present but needs an index are
different mistakes to correct.

**The MO diagram is the sharpest case of the same rule** (`kind="orbitals"`,
2026-08-31). A CASSCF job exports NATURAL orbitals: the occupancies are real,
and every active orbital's energy is recorded as exactly `0.0` because the
export carries no eigenvalue for it. The summary says so in
`frontier_energy_unavailable`. The first working version of the diagram read
those zeros as energies, drew nine levels stacked at the origin, called the top
one the HOMO and annotated a HOMO-LUMO gap of 4.50 eV. Every number on it was
arithmetic on a placeholder. 53 of the 156 orbital tables in the development
data directory are that shape and 103 are canonical, so this is the common case
for multireference work, not an edge.

It is refused in two places on purpose. `job_charts.render_mo_diagram` checks
the DATA -- a frontier orbital at exactly 0.0 while core orbitals of the same
table sit hundreds of eV below it -- so the renderer is safe whoever calls it.
`plot_mo_diagram` checks `orbital_table_kind` and relays the summary's own
sentence, so what the user reads explains their job rather than reporting a
`ValueError`. The lesson generalises: a placeholder that happens to be a valid
float is more dangerous than a `None`, because every downstream check passes.

### Charts that are adapters, not mechanisms

`app/chemistry/job_charts.py` holds four charts over data jobs already
reported: MO levels, an optimization trace, an excited-state map, and Wigner
sampling diagnostics. They are functions rather than `custom` plot specs
because each needs domain arithmetic a declarative spec cannot express -- which
orbital is the HOMO, what the energies are measured from, which unit the answer
is read in -- and none of them adds a plotting mechanism: they are the marks
`spectrum.py` already draws, pointed at different fields.

They cost one `kind:` line each in `plot()`'s docstring because each takes a
job id and nothing else. That is deliberate, and it is the constraint to design
against when adding more: the tool surface is measured against a hard budget
(`tests/backend/agent_01_token_budget.py`), and a kind needing a paragraph of
spec documentation is competing for the same headroom as every other tool.

---

### One chart spec, not one function per chart

`plot(kind="custom")` is a small declarative spec rather than a fixed catalogue
of chart types, and everything it draws comes out of three ordered stages, each
with exactly one rule:

| stage | question | rule |
|---|---|---|
| rows | what one x slot is | how many `job_ids` there are |
| placement | where that slot sits | `x_field` present means numeric, absent means one column per job |
| marks | how a value is drawn | `style`: line, scatter, bar, levels |

The point of naming the stages is that a new chart someone describes is almost
always a different combination of the three rather than new code. The request
that drove this design ("method names on the x axis, stacks of horizontal lines
for the states, colour coded by state") was refused by the previous version,
correctly, because it only knew a numeric x axis and a connected line. It is now
`style="levels"` with `x_field` omitted, and nothing else about it is special.

Two decisions inside that are easy to get wrong later:

**`x_labels` is keyed by job id, never a positional list.** A job that is not
finished has no column and is dropped, so with a positional list every label
after that point slides one column left. The chart still renders and the legend
is still right, and the method names sit over the wrong bars. That is the worst
failure mode a comparison chart has, because nothing about the picture looks
broken. Keying by job id makes it unrepresentable.

**Sorting happens under exactly one condition:** a numeric axis whose rows are
unrelated jobs, where the trend along the axis is the whole point. Categorical
order is the caller's order, and a single job's own arrays are already in
coordinate order.

`kind="comparison"` survives as a thin front door onto the same pipeline rather
than a second mechanism. What it adds, and the only thing that justifies it, is
that "energy" is `final_energy_hartree` in one job and `casscf_energy_hartree`
in another, so a single raw field path cannot express it across a mixed set of
jobs. It resolves the friendly name to a literal key per job and hands off. That
alias table deliberately stays outside `_resolve_field_path`, because that
function's contract is that no schema of known names is consulted ahead of the
job's real summary, and a table consulted inside it would make that false.

### A plot is a saved object, not an image

Every chart the app draws is stored as a record: its spec, the jobs it came
from, the numbers it drew, and a series of rendered versions
(`app/plots/store.py`). Almost everything else about the feature follows from
that one decision. An edit is a patch to the spec and a re-render. A question
about a plot is answered from the cached numbers. The Plots panel is a list of
records. And the model can be handed a plot without being handed a picture it
cannot see.

**Plots are not stored inside job directories,** which was the obvious cheaper
option and is wrong. A plot can aggregate several jobs, and a seven-method
comparison has no owning job at all, so parenting it to an arbitrary "primary"
job would destroy the chart the moment that one job was deleted with six
sources still on disk. Reclamation instead follows a single rule:

> a plot is deleted when its **last** source job is gone

which reads correctly at both ends with no special case. A single-job UV/Vis
spectrum disappears with its job, which is what anyone expects, and a
seven-method comparison survives until the seventh goes. `sweep_orphans` is
what enforces it, called after job deletion and on every panel listing, since
neither job deletion nor quota eviction knows a plot pointed at what it removed.

The costs of a separate store are all bounded and all have a precedent:
`app/uploads/store.py` is the template, including per-item sidecars over a
shared index (avoiding a read-modify-write race between concurrent writers);
`ownership_index.kind` needed the same idempotent DROP/ADD it once needed for
`'upload'`; and plot bytes count toward the existing **job** quota category
rather than a fifth of their own, since a plot is derived from jobs, is small,
and already garbage-collects itself.

**Ownership is recorded by the store, not by a route.** Unlike an upload, a
plot is created by the agent mid-turn with no request handler on the stack.
`AgentState.owner_user_id` is what carries the owner in, the same value job
submission records with.

**An edit pins a new version rather than overwriting one.** A chat message
cites the version it actually drew, so scrollback keeps showing what it
described while the panel shows the latest. That also retired a live bug: the
fixed artifact keys `uvvis_spectrum`, `ir_spectrum` and `ensemble_spectrum`
meant re-plotting a spectrum at a different broadening silently changed the
image in every older message that had ever shown it.

Two details worth not undoing. Version numbers come from a monotonic counter
and **not** from `len(versions)`, because pruning truncates that list and the
next render would then reuse a number that already exists, overwriting a
version an older message still points at. And an edit merges `series` **by
label**, so "make S2 red" is a two-key patch rather than a restatement of every
series with its field paths, which a model gets wrong far more often than right.

The marker in a tool's reply is therefore `PLOT_ARTIFACT plot_id=... version=...`
rather than a job artifact key: the job artifact route enforces `JOBS_DIR`
containment and cannot serve a file from the plot store. UV/Vis, IR and
ensemble spectra additionally keep their old job artifact keys pointing at the
same file, so the job drawer's own panels are unaffected.

**Job-intrinsic plots are records too.** A finished job's spectra are
registered from `job_watcher`'s poll loop, which already knows a job has newly
finished. Deleting one is meaningful rather than destructive: it removes the
saved view and leaves the job's data alone, so asking again brings it back. The
interactive charts in the job drawer (optimization energy, PES scan, NEB path)
are deliberately not registered. They are drawn client-side from job data and
have no stored parameters an edit could patch, and inventing some to make them
look like plots would be worse than leaving them the live views they are.

### One style vocabulary, and why the defaults are load-bearing

Four of the eight plot kinds could not be restyled at all. The reason was not
a missing spec key, which is what it looked like: `render_uvvis_plot`,
`render_ir_spectrum_plot`, `render_wigner_ensemble_spectrum` and
`render_pes_plot` took no title, label, colour or size argument, and their
titles were f-strings inside the function bodies. `plot(kind="edit")` refused
them because there was genuinely nothing a patch could reach. So "rename the
title of my UV/Vis spectrum" had no answer.

`app/chemistry/plot_style.py` is one `PlotStyle` every renderer takes, and
every kind is editable through `spec["look"]`.

**Fonts and figure settings are applied per plot, through `rc_context`.**
They used to be a module-level `plt.rcParams.update(...)` that ran once at
import and set the look of every figure the process would ever draw. That is
fine while there is one look, and wrong the moment a caller asks for a bigger
font on one chart: in a long-lived server shared by every user, a global
mutation restyles the next person's plot too.

**Every default reproduces the previous output exactly, and that is asserted.**
`tests/backend/plot_02_style_vocabulary.py` checks that an unstyled render is
unchanged, which is what makes this safe underneath images people already have
saved. It earned its place immediately: the first implementation collapsed
each renderer's considered line width onto one number (a levels tick is 2.5pt
because it must read as a level, not a line; an ensemble's total curve is 2.0pt
because it sits over dotted overlays) and quietly took matplotlib's default
colour cycle away from `render_line_plot`, changing every saved scan and
optimization plot. So `line_width`, `marker_size` and `palette` are `None`
until a caller sets one, and each renderer supplies its own value through
`lw()`, `ms()`, `accent()` and `cycle_color()`.

**The appearance block is `look`, not `style`, because `style` was taken.**
For a custom plot `spec["style"]` is the MARK: the string `line`, `scatter`,
`bar` or `levels`. The two are told apart by type, so a dict-valued `style` is
read as appearance and a string one still selects the mark. Without that,
every existing custom plot would have started failing validation the moment
the style block existed.

**The vocabulary is not in `plot`'s docstring.** The fixed tool surface is
measured against a hard 10,000-token budget
(`tests/backend/agent_01_token_budget.py`) and was already at 9,874 before this
work. Spelling out forty style keys on every ReAct iteration to serve an
occasional request is the trade `submit_job`'s 35 flat optionals lost. The
docstring names the categories; an unknown key is refused with the complete
list, so it is paid only when someone gets it wrong.

### Nuclear-ensemble (Wigner) spectra

A `wigner_ensemble` job samples geometries from a completed frequency job's
normal modes, runs one excited-state sub-job per sample, and pools every sample's
transitions into one broadened spectrum. The architecture mirrors `pes_scan`'s
master/sub-job fan-out, with one deliberate deviation: sub-jobs dispatch in
throttled waves rather than all at once, because sample counts (up to 500) dwarf
a typical scan's image count and would otherwise stress the quota and concurrency
scanning at a scale it was not built for.

Oscillator strengths are structural to this job type rather than optional, and
that is enforced in the capability layer: `wigner_spectra` declares
`requires=("excited", "osc_strengths")`, so a method with no trusted
intensity capability on a given engine cannot be routed there at all. The
spectrum is a Gaussian convolution of every sampled transition weighted by its
intensity, so an ensemble without intensities has nothing to broaden and ends
on "No sample contributed a usable (energy, oscillator strength) pair to pool"
after running every sample. That is what used to happen: the task asked only for
`excited` and merely warned when intensities were missing, so a CASSCF or
EOM-CCSD request took PySCF, first in preference order and excited-capable, and
produced nothing. Because `route_engine` picks from `engines_supporting`, adding
the requirement is the whole fix; those two now route to ORCA, and no rule in
`routing.py` had to learn about this task. Every sub-job additionally gets
`want_oscillator_strengths` forced on, whatever the method, so the approval card
states what is being computed instead of showing a toggle the job overrides.
Pooling accounts for every sub-job in exactly one category, so a caller can
always say what happened to each sample rather than silently dropping some.

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
   whose own norm is *itself* `1/sqrt(mu)`. It is the mass-deweighted eigenvector
   `l/sqrt(m)`. The factor was applied twice and every displacement came out too
   small by `sqrt(mu)`: about 4% for a hydrogen-dominated mode, a factor of 2.2
   for formaldehyde's 5.05 amu C=O stretch, 3.4 for the 11.5 amu modes of a real
   twelve-atom molecule. Wrong, in other words, precisely on the heavy-atom modes
   that shape a real chromophore's band, while a water test looked almost right.
2. The reduced-mass helper inferred `mu = 1/sum(v**2)`, an identity that holds
   only for mass-deweighted vectors. **ORCA's printed normal modes are
   additionally unit-normalised** (`sum(v**2) == 1.0000` exactly, confirmed
   against a real run), so it returned a fabricated `mu = 1.0 amu` for every mode
   of every ORCA job. Erring in the *opposite* direction from PySCF and making
   the same molecule's ensemble depend on which engine produced the frequencies.

Compounding the trap: that helper is used by ORCA and BAGEL and *not* by PySCF,
which passes its own authoritative `reduced_mass` through. The only engine it had
ever been validated against was the one engine that never calls it.

The fix is a reduced mass invariant under any per-mode rescaling of the mode
vector, `mu_k = sum_a m_a |v_ak|^2 / sum_a |v_ak|^2`, paired with an explicitly
unit-normalised direction. That is correct for all three engines with no
per-engine special case. It reproduces PySCF's own `reduced_mass` to 1e-15 and
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
per-sample diagnostic, but that diagnostic is `0.5*mu*omega^2*q^2` evaluated on
the very `q` drawn from a distribution of width `sqrt(hbar/(2*mu*omega))`, so
`<V> = hbar*omega/4` is an algebraic *identity* in those coordinates for any `mu`,
whether the normal-coordinate-to-Cartesian mapping is right or wrong. The
docstring claimed to test exactly what the arithmetic made it blind to.

`scripts/validate_wigner_sampling.py` now evaluates the **Cartesian** Hessian
quadratic form on the geometries the sampler actually emits, against a Hessian
obtained independently, sharing no arithmetic with the sampler. It reports 0.756
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

So the spec-building path `submit_draft` calls on every submission now
*always* runs a KB similarity search filtered to `doc_type="manual"`, keyed on
the engine, task, method, functional and basis. The result (`kb_context`)
lands in the `interrupt()` payload's own `kb_context` field, shown on the
approval card under "Manual/reference excerpts consulted". The last
checkpoint before execution, and the one place that does not depend on the
model reading anything.

This is retrieval-and-surface, not verification. Nothing parses the retrieved
text or blocks a bad parameter. KB quality also varies by engine: ORCA and BAGEL
manuals document keyword syntax directly, while PySCF's KB is generated from
installed-package docstrings, which cover signatures well but say nothing about
basis-set naming. Weaker grounding for exactly the error class that motivated
this.

### Four knowledge sources, deliberately differentiated

The system prompt gives each source an ordered hierarchy keyed to a recognisable
situation, preparing an input, troubleshooting a failure, answering a chemistry
question, or writing a parser, rather than one flat "use when relevant"
instruction, because those situations call for genuinely different sources and
mixing them risks answering a chemistry-judgement question with a software manual
snippet.

`search_academic_literature` wraps Semantic Scholar's `/paper/search/bulk`
endpoint specifically, not `/paper/search`: the latter returns `429` repeatedly on
the shared unauthenticated pool, and `bulk` is the only one supporting
`sort=citationCount:desc`. Its query syntax is literal boolean AND/OR of
bare/quoted tokens, not semantic search. A real usability trap, confirmed by
testing: a natural multi-word question returns zero hits because every word is
ANDed, while unquoted common words match hundreds of irrelevant papers. Only a
query of a few double-quoted distinctive technical terms works. This is enforced
through the tool's docstring contract with explicit good and bad examples; there
is no query-rewriting layer.

### Seeding

`scripts/seed_knowledge_base.py` crawls the BAGEL and ORCA manuals and generates
PySCF reference docs from the *installed* package's docstrings. PySCF is
deliberately not scraped: pyscf.org's `robots.txt` disallows it.

Watch for dispatcher functions when extracting docstrings, `mcscf.CASSCF`,
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
poll gated on `status === "running"`. A raw log tail is cheap, low-stakes state,
not worth a second event type.

### Every route handler is a plain `def`

FastAPI runs sync handlers in a worker threadpool, while an `async def` handler
that blocks stalls the single event loop, including SSE delivery to every other
open connection. The KB upload route violated this: it was `async def` and called
a synchronous chunk-and-embed pipeline directly on the event-loop thread, so a
large PDF upload stalled every other tab for the whole ingestion. Fixed by making
it a plain `def` like every other route.

### Three outbound calls needed explicit timeouts

Anything that runs inside a graph turn can hold that thread's lock for as long as
it hangs. The embedding client, the web-search client, and, most severely, the
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
rebuild the WebGL view, and discard camera state, on every unrelated re-render.

One bug shaped the current implementation, and it is worth knowing about because
reasoning from the docs gives the wrong answer. **`GLViewer` has no `destroy()`,
`dispose()` or `remove()` method, and `createViewer()` unconditionally appends a
new `<canvas>` into the container.** React 18 Strict Mode's dev-time
mount→cleanup→remount nulls the container ref *before* running cleanup, even
though the DOM node is not actually torn down, so a "clear the container in
cleanup" fix is silently a no-op, and the first mount's orphaned canvas is still
present when the second `createViewer()` appends another on top.

Browsers cap live WebGL contexts per page (commonly 8–16). Repeated
mount/unmount exhausted that cap and every subsequent context silently failed to
initialise, the viewer rendered as a blank square with no error. The actual fix
clears the container at the *start* of the init effect. Verified by
instrumentation: live canvas count stays at exactly 1 across dozens of rapid
cycles, where it previously grew without bound.

Related, and easy to lose an afternoon to: **`page.screenshot()` cannot reliably
capture WebGL canvas content.** Use `canvas.toDataURL()` via `page.evaluate()`
when verifying anything the molecule or orbital viewers render.

### Camera framing: `zoomTo()` has a floor, and it is not ours

Molecules were reported as "always zoomed out and small". Every viewer already
called `zoomTo()` on load, so the framing call was never missing. Measuring the
library directly, a two-atom dimer, sweeping the separation. Showed an
*identical* camera distance (`getView()[3] == 121.644`) at 0.5 Å, 1 Å, 5 Å and
10 Å, moving only above 10 Å. The source says why:

```js
var MAXD = this.config.minimumZoomToDistance || 5;   // 3dmol/build/3Dmol.js
var maxDsq = MAXD * MAXD;                            // floor on the bounding radius
maxD = Math.sqrt(maxDsq) * 2;
```

The fit is on a sphere of radius `max(MAXD, r_max)`, and MAXD defaults to 5 Å,
so **every molecule with a bounding radius under 5 Å**, which is most of what
this app runs, was framed as though it were 10 Å across. Water covered 6% of the
frame width; benzene 39%.

`minimumZoomToDistance` is a supported config option, so the fix is to pass a
floor low enough that it stops binding. It cannot be zero: the floor is what
stops a single-atom system (`r_max == 0`) putting the camera at the origin.

With the floor lowered, 3Dmol's own fit turns out to *clip*, benzene measured
0.769 × 0.993 of the frame with content touching the edge, because it measures
atom **centres** and knows nothing about the sphere radii, sticks and labels
drawn around them. So the framing pulls back by a fixed fraction. The fraction
is the important part: it is scale-invariant, behaving identically on water and
on a 40-atom system, where the tempting `zoom(1.2)` constant would be tuned on
one and overshoot the other. Measured across water, benzene and a 19 Å chain,
each 0.05 step moves all three by the same ~5%.

`fitView()` deliberately passes no selection, because `zoomTo()` folds every
shape's bounding sphere into the fit. That is what keeps `MoCubeViewer`'s two
volumetric isosurfaces in frame, which extend past the atoms and grow further as
the isovalue drops.

Sizing is a `ResizeObserver`, not an effect keyed on the `height` prop. The prop
covered exactly one case (a panel being expanded) and missed the other: LeftRail
and RightDock are both drag-resizable, so the container's *width* changed and
nothing ever called `resize()`. The canvas kept its old pixel width inside a box
that had grown around it.

### Isosurface smoothing: another library default that is not ours

Orbital lobes rendered with fine ripples running across them, which read as
structure in the orbital and were nothing of the kind. Same shape of cause as
the camera floor above. `3Dmol`'s `addIsosurface` runs marching cubes over the
cube grid and then smooths the resulting mesh, and `smoothness` defaults to 1,
a single Laplacian pass. One pass does not remove the staircase the grid cells
leave, so the cube's own voxel structure showed through as corrugation. The
library's own documented example uses 5 and 10.

The grid makes it worse as molecules get bigger, without being the cause. Both
cube paths write a fixed 80 points per axis, `orca_plot`'s `ngrid` and PySCF
`cubegen`'s `nx/ny/nz`, over a box that grows with the molecule: measured from
the cube headers, water gets 0.076 Bohr spacing and benzene 0.195 Bohr in its
widest axis. Coarser cells, bigger steps for the smoothing to hide.

Smoothing was chosen over a denser grid because it costs nothing, needs no
server-side re-render, and applies to every job already on disk. A grid of 160
points per axis is eight times the data to compute and to ship on every lazy
orbital fetch, for a display artifact. The trade-off is recorded in
`MoCubeViewer.tsx` rather than left implicit: Laplacian smoothing pulls
vertices inward, so the drawn surface sits fractionally inside the true
isosurface, measured on rendered lobe area as 1.4% for water and 3.1% for
benzene, one to two percent in linear extent. That is well inside one notch of
the isovalue slider, and the alternative is a surface whose visible texture is
an artifact of the sampling.

### The frame scrubber is a scrollbar, and its thumb is the frame count

Four viewers browsed multi-frame results with a bare `<input type="range">`.
Two problems, and the second is the one worth designing around.

A native range draws its own chrome, which the design tokens do not reach: on
this dark surface Chrome renders a bright, chunky thumb on a light track, so a
minor control became the loudest thing on the panel. More usefully, a range
thumb is a fixed size and therefore says nothing about the length of what it
scrolls. A scrollbar's thumb *is* that information, which is why a long
document gets a short one.

So `FrameScrubber` sizes its thumb at `1/count` of the track: a 3-frame scan
gets a third, a 200-frame trajectory a sliver, and you can see how long a
series is before touching it. Measured in the browser at 2, 3 and 4 frames:
198px, 132px, 99px on the same track. Below a floor the thumb stops shrinking,
because the honest width becomes ungrabbable, under a pixel at 200 frames on a
280px dock, and by then "very many" is the only message left to carry.

The bounds are drawn explicitly and are dimmer than the thumb. Without them the
track dissolves into the panel and the series has no visible extent; brighter
than the thumb (the first attempt) and the static furniture out-shouts the one
part you actually grab.

Genuinely continuous sliders that remain, the orbital isovalue. Keep a fixed
thumb, since a proportional one would mean nothing there, but are restyled into
the same palette via `.qc-range` in `index.css`. `appearance: none` has to be
set on the input itself; setting it only on `::-webkit-slider-thumb` leaves the
track native and the two halves visibly disagree.

### Viewer panels own exactly one overlay control row

`ExpandablePanel`'s expand toggle and the download button each viewer overlays on
itself both claimed `absolute right-1 top-1 z-10`. Equal z-index means DOM order
decides, the viewer's button is the later sibling, and it carries a background,
so it painted over the toggle in every molecule, orbital and vibration panel. The
plots were unaffected only because they have no overlay control of their own.

The fix is structural rather than an offset. The panel renders one
absolutely-positioned row and publishes a slot node through a context; viewers
render into it via `createPortal`, falling back to positioning themselves when
there is no panel above them (`MoleculeViewer` is used both ways). Offsetting one
button to `right-8` would have fixed the instance and left the defect class
intact, with nothing in the tree explaining the offset, the same reasoning F-013
records for the account bar. React portals keep the child in its declared React
tree, so a click on a download button still bubbles through that component's
handlers and never reaches the expand toggle it is now a DOM sibling of.

Where that row sits is a second question, and the panel's own corner is the
wrong answer for two of the panels. For a panel whose visualization starts at
the top, a spectrum image or a frame viewer, the panel's top-right corner is
the picture's top-right corner and nothing more needs saying. The orbital panel
has a label dropdown above its viewer and the vibrations panel has the frequency
table above it collapsed and beside it expanded, so in both the row floated over
that other content rather than over the thing it controls, and both tables
carried a right-padding hack to keep their own text out from under it. A viewer
may now nominate its own box with `PanelControlAnchor`, and the panel portals
the whole row there. The whole row, deliberately: moving one button to dodge
another is the anti-pattern this section exists to reject, and one row with one
owner is what keeps it rejected. `frontend/src/app-shell/ExpandablePanel.tsx`
registers the anchor through state rather than a ref for the same reason the
slot node is state, a ref is null on the render that matters and notifies nobody
when it stops being.

### Who names a download depends on who knows its extension

Every file a job hands a user is named `{safe job name}_{descriptor}{extension}`,
`job_download_name()` in `app/chemistry/jobs/naming.py`, with the job's label
slugified so a rename cannot smuggle a quote into a `Content-Disposition` header
or a slash into a filename. What varies is which side builds it.

Anything served by an API route is named **server-side**, in the response
header, and the frontend link carries a valueless `download` attribute so the
browser takes that name. That is not a stylistic preference: for an artifact the
extension is a property of the file the runner actually wrote, `ensemble.xyz`,
`bagel.out`, `opt.molden`, and only the server can read it off disk. The
alternative, a table in the frontend saying which artifact is which format, was
rejected because it would be a second copy of a fact that already exists, and
the drift would be invisible to any test: the two names appear on different
downloads. One artifact link, the plot card in a chat message, has no job row at
all, so no name is derivable in the browser for it in any case.

The browser names only what it already holds and what arrives with no header to
read: a captured 3D-viewer canvas, an animated PNG of a vibration, or text it
fetched earlier and is re-saving. `lib/jobFilename.ts` mirrors the same
three-part shape for exactly those.

The bug that prompted this was the artifact route sending no
`Content-Disposition` at all, so a Wigner ensemble's sampled geometries landed
named after the last segment of their URL, `ensemble_xyz`, with no extension
and no viewer willing to open it.

### An expanded panel carries its own table, and a React dep array caused a hang

Expanding a viewer panel makes it `fixed inset-6`, which covers everything behind
it. Including the orbital and frequency tables the selection came from. The only
way to reach a different orbital or mode was therefore to collapse first, which
defeats the point of expanding. Both panels now hold their table as a column
beside the viewer, so a row is clickable in place; the scrubber stays as a second
way to move through a long list without aiming at rows.

The scrubber is also what exposed a subtler defect. `FrameScrubber` fires
`onChange` on every `pointermove`, and many consecutive moves land inside the
*same* orbital's slice of track. The drawer answered each one with a fresh
`{index, spin}` object, and `MoCubeViewer`'s fetch effect listed that object in
its dependency array. React compares dependencies by reference, so every
pointermove re-fired the effect, and every re-fire is a real `orca_plot` or
molden-to-cube run on the server. One measured drag across a 36-orbital table
issued **42 POSTs, several of them duplicates of the same index**. The browser
allows six connections per origin, so they queued; the request the user was
actually waiting for went last; and the viewer sat spinning long after the drag
ended. Job polling and the SSE stream were starved alongside it, since they
compete for the same six connections.

Three changes, and the first subsumes the others' worst case:

- **The effect depends on primitives** (`index`, `spin`, `gbw`), never on the
  selection object. This also fixed `NebFrameViewer` for free: it passes an
  inline object literal, so *every* render of its parent, i.e. every job poll,
  was re-requesting the same cube.
- **Superseded fetches are aborted**, not merely ignored. A `cancelled` flag
  suppresses the state write but leaves the request holding its connection until
  the server is done with it, which is what starved everything else.
- **A 200 ms settle** before the request goes out, so the orbitals a drag passes
  over are never rendered at all. It lives in `MoCubeViewer` rather than in
  `FrameScrubber`, because the scrubber's other consumers, scan, NEB and
  vibrational-mode frames. Are pure client-side redraws that must stay instant.

Guarding against a repeated index inside `onChange` was rejected: it is a second
copy of the same rule in another file, and primitive dependencies already cover
it.

One constraint on the layout itself, recorded because it is invisible and
expensive to rediscover: the two-column and stacked arrangements are the same
JSX tree with different class names. Giving the expanded case its own nesting
would move the viewer to a different position in the tree, which unmounts it.
Rebuilding the WebGL context, losing the camera, and re-triggering the very
server-side render this section is about. That is the same hazard `ExpandablePanel`
was built to avoid by toggling CSS rather than portalling into a dialog.

### A panel scrolls its own content; the row never scrolls

`ShellLayout`'s three-panel row is the app's fixed viewport, and nothing in it
may scroll it. Each panel is responsible for bounding and scrolling whatever it
contains: the chat pane its message list, the instrument panel its stack of
sections, and several sections their own inner lists on top of that.

This was learned rather than designed. The instrument panel's sections are all
`shrink-0` except the job manager, and the molecule section has no cap at all,
so an open 3D viewer (about 350px, about 615px expanded) plus `Jobs` at
`max-h-56` and `Plots` at `max-h-64` comes to roughly 870px of incompressible
content. On a window shorter than that the excess escaped the panel, because
the panel had no scroll container of its own.

What turned that into a visible artifact was the row. It carries
`overflow-x-auto` as a safety net for a dragged-wide panel, and CSS computes the
*other* axis to `auto` whenever one axis is not `visible`, so the row had
silently become vertically scrollable as well. Scrolling it moved the whole row:
the sidebar and the chat pane were dragged up out of the viewport, leaving a
black band along the bottom of the window. Collapsing the molecule pane made the
symptom vanish, which is what made it look like a molecule-panel problem rather
than a layout one.

Two rules came out of it. A row that clips on one axis must state the other
explicitly rather than inherit `auto` by omission. And a `flex-1` child inside a
scrolling column needs a minimum height when it is the one meant to absorb
leftover space: with `min-h-0` the job manager was squeezed to literally zero
pixels on a short window, so the panel silently disappeared instead of the dock
gaining a scrollbar. `tests/frontend/ui_08_dock_overflow.spec.mjs` measures all
of this, since none of it is visible to a code read or to a screenshot.

### Error boundaries are per-region

`PanelErrorBoundary` wraps each major region independently, chat, sidebar,
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
geometry/blind-input uploads (`app/uploads/`, Phase 3) capped separately again in
their own directory (deliberately not KB's `UPLOADS_DIR`, see that module's
config docstring for why sharing it would break KB's own orphan-file sweep and
quota accounting), all three enforced at write time with oldest-first eviction,
and all deliberately sparing content they did not create, a pending job, a
pre-seeded manual.

**Auth configured:** all three modules defer entirely to a tiered scheme. A
per-user KB quota, a per-user uploads quota, a combined per-user job-artifacts-
plus-chat-history quota (one shared pool, since both are "this user's own
activity"), and a single global cap across everything. All four are
admin-editable at runtime.

Chat-history bytes are a `pg_column_size` estimate summed across the checkpoint
tables per thread. This closed a real shipped gap: deleting a conversation
removed it from the visible registry but never freed its underlying checkpoint
rows at all.

### "Has this job finished?" has one answer, and it is `status.json`

Both quota modules used to ask `read_result(job_id)`, while the job list, the
job drawer and `DELETE /api/jobs/{id}` all asked `read_status(job_id)`. That is
two sources of truth for one question, and they disagree in a reachable way:
`write_status()` and `write_result()` are two separate writes, and every
`write_result` in `base.py` is preceded by a `write_status`, so a job can have
a status and no result, but never the reverse. A job interrupted between those
two writes was therefore listed as completed and was permanently unpurgeable
and mis-measured. Observed, not theorised: `POST /api/admin/purge/jobs`
returned `count: 0` against a console listing 299 finished jobs.

`job_is_terminal()` in `app/chemistry/jobs/base.py` is now the only answer, and
it reads `status.json`. The file the JobManager maintains across the whole
lifecycle, not just at the end. The rejected alternative was to fall back to
`result.json` when `status.json` is absent, which would have kept both
definitions alive and left the pair to be held in agreement forever.

A related gap in the same area is deliberately *not* closed the same way: a job
directory with no `spec.json` is invisible to `_iter_job_ids()`, so nothing
lists it, purges it, or counts it against a quota. Both `purge_all_jobs` and the
admin console's own "reclaim orphaned directories" action sweep those, but only
after they have been untouched for an hour, and never from the automatic
eviction pass, `JobManager.submit()` creates the directory before writing
`spec.json`, so a job submitted microseconds ago has exactly that shape, and
automatic eviction runs *inside* `submit()`.

That sweep is its own admin action rather than something reachable only by
purging every job in the deployment, because it destroys nothing anybody owns.
It sits in the storage view, not the danger zone, for the same reason, and
because the admin needs to see the count before acting on it: these directories
appear nowhere else in the app. The count the console shows and the number the
button removes can differ when the age gate holds one back, so the console says
so explicitly. A control that quietly does less than the figure printed beside
it is the exact shape of the bug this whole section exists to record.

### The audit log is append-only at the database level

A Postgres trigger rejects `UPDATE`, `DELETE` and `TRUNCATE` outright, confirmed
by direct testing. The lockout-recovery CLI deliberately narrows its own reset to
`DELETE FROM users` rather than `TRUNCATE ... CASCADE`, which would silently wipe
the audit log and bug reports wholesale via Postgres's cascade-truncate
behaviour, regardless of each foreign key's own `ON DELETE` action.

### Lazy singletons need double-checked locking

Building the admin console surfaced a real pre-existing bug by exercise rather
than inspection. The vector store's lazy module-global client had no lock. Fine
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
  writes `spec.json`/`status.json` near the top, making the job visible, and
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
  password hash, while the wrong-password branch ran a real argon2 verification.
  A measurable difference distinguishing "no such user" from "wrong password"
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
  report, at most 5MB each, necessary, because `client_max_body_size` is 512m
  and would otherwise be the only limit on the route.
- **Served by an explicitly admin-only handler, never `check_owner_or_admin`.**
  This is the subtle one. Under that helper a resource with *no* ownership row is
  readable by **everyone**, not by no-one, the same shape as the orphaned-job
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

### A self-purge is a narrower thing than an account deletion, deliberately

`purge_own_data()` (`app/auth/storage_quota.py`) backs the account panel's own
danger zone, every signed-in user's self-scoped "delete my data" button, and
was built by composing the *same* candidate builders and cancel-and-await
helper `purge_user_data()` already used for admin-driven account deletion
(`_job_candidates`/`_kb_candidates`/`_upload_candidates`,
`_cancel_and_await_terminal`), not by writing a second purge implementation.
The one deliberate omission is `_thread_candidates`: `purge_user_data()`
removes chat history too, including pinned conversations, because the account
itself is going away and nothing is left to own them regardless; `purge_own_data()`
leaves every conversation untouched, because the account survives a self-purge
and losing every chat as a side effect of "clear out my old jobs" would be a
surprising, unrelated loss for someone still using the app afterward. A
still-pending/running job is always cancelled and awaited to a genuinely
terminal state first, in both functions, "delete my data" cannot leave an
orphaned subprocess still writing into a job directory the call is about to
remove out from under it, the same invariant SEC-08b's regression test exists
to hold admin-driven deletion to.

### A job draft's geometry can be tagged from a specific prior job, not just read from the panel

`source_geometry_job_id` (a `ParamSpec` in `registry2/params.py`, resolved in
`registry2/elicitation.py` and `app/agent/tools.py`'s `_resolve_draft_molecule`)
lets a draft take its geometry from a named prior job instead of
`state["molecule"]`, "same geometry as job X", "repeat that with a bigger
basis." The (molecule, error) resolver it shares with `geometry_parameters`
(the P9.2 bond/angle/dihedral tool) lives in `app/chemistry/jobs/
geometry_resolve.py`, a chemistry-layer module, rather than in `app/agent/
tools.py` where it was first written: `elicitation.py` is deliberately
independent of the agent layer (see `validate_draft`'s own docstring, a test
can pass it a two-key state dict with no graph behind it), so a function it
needs has to live where both layers can reach it, not wherever its first
caller happened to be.

The "last job this conversation ran" question a user's "same as before"
phrasing implicitly asks turned out to need no new state at all:
`check_job_status`'s own existing fallback (`state["active_job_ids"][-1]`,
already how "check on it" without a job id resolves) already *is* that
tracker, populated at submission time regardless of whether the job has
finished. An earlier design sketch added a dedicated state slot and a
`job_watcher` write site for this; that was dropped once reusing the existing
field was confirmed to work, rather than shipped as a second, narrower
mechanism sitting beside the general one.

Unlike `initial_orbitals_job_id` (an unresolvable tag degrades silently to "use
a fresh guess," a genuine convenience since the alternative is scarcely worse),
an unresolvable `source_geometry_job_id` is never silently dropped. The draft
is refused, naming the problem, so the user is asked to fix the tag or say
to fall back to the panel rather than a different geometry than the one they
named being substituted underneath them.

### Fuzzy find is word-level, not character-subsequence

`SearchableText` (`frontend/src/app-shell/SearchableText.tsx`), the one
shared find bar behind every plain-text document viewer in this app (raw job
input/output, a KB manual or paper, an uploaded file). Runs an exact,
case-insensitive substring search first, and additionally fuzzy-matches
single-word queries against whitespace-delimited word tokens within a small
Levenshtein distance. A VSCode-command-palette-style character-subsequence
matcher (where a query's letters just have to appear in order somewhere in
the candidate, e.g. "cvg" matching "convergence") was the other natural
reading of "fuzzy search," and was rejected for this use case specifically: it
lights up nearly every short substring of a large raw ORCA/BAGEL output,
which is noise, not a find tool, in a single continuous document rather than a
short list of distinct file/command names. Word-level typo tolerance
("convergance" still finds "convergence") is the reading that actually helps
here. A multi-word query stays exact-substring-only. Fuzzy phrase matching
across word boundaries is a different, much less predictable feature, and the
text length is capped (`FUZZY_MAX_TEXT_LENGTH`) so a multi-megabyte raw output
still finds exact matches instantly without paying for a token-by-token
edit-distance pass over the whole document on every keystroke.

---

## Project archives

A project is a named bundle of jobs, listed in the left rail beside
Conversations, Knowledge base and Files. Selecting finished jobs in the job
manager and filing them into a project takes them off that list, which is the
point: the job list otherwise only ever grows, and a study that took thirty
calculations sits on top of the next study's forever.

### Archiving is a membership label, and a job's files never move

This is the constraint the whole feature is built around, and it is worth
stating plainly because the obvious implementation of an "archive" is to move
the files somewhere.

Everything in this app is keyed on `data/jobs/<job_id>/` staying exactly where
it is. `app/auth/storage_quota.py`'s `_job_usage_by_owner` walks those
directories to compute quota. `app/agent/threads.py`'s `set_active_job_ids`
filters on `(JOBS_DIR / j / "spec.json").exists()`, so a job whose files moved
would silently vanish from its own conversation's panel. The detail drawer, the
orbital-cube route, the artifact route and the per-job download all read
`JOBS_DIR / job_id` directly.

So `app/projects/registry.py` stores job ids and nothing else. Moving a file
would have corrupted quota accounting and evicted archived jobs from their own
conversations, and neither failure would have been visible until much later.

### Membership lives on the project, not on the job

`data/projects.json` is a flat JSON file with the same shape and the same
reasoning as `data/threads.json`: list-shaped state the left rail polls, which
must need no coordination with `graph.py`'s `_graph_lock`. Each entry holds its
own `job_ids`.

The alternative was a `project_id` key in each job's `meta.json`. That file is
already the designated mutable one, so it would have worked, but filing twelve
jobs at once would be twelve read-modify-write cycles across twelve
directories instead of one atomic rewrite of one small file.

A job belongs to at most one project, and `add_jobs` is what enforces it. It
does the removal from the old project and the addition to the new one in a
single read-modify-write cycle under a single lock acquisition. The obvious
spelling, `remove_jobs(other, ids)` followed by `add_jobs(this, ids)`, is two
file writes with a window between them where the job belongs to nothing, and a
crash there loses it from both. Every affected project is an entry in the same
file, so one write covers all of them.

Deleted jobs are pruned from whichever project held them by
`delete_job_dir`, beside the existing conversation-registry prune. Every read
additionally filters ids whose `spec.json` is gone, as a safety net for any
path that removes a directory without going through that function.

### The two large zips stream; the per-job one still buffers

`app/projects/zipstream.py` builds the archive as a generator of bytes rather
than in an `io.BytesIO`.

The per-job download in `server/routes/jobs.py` still buffers, and that is
fine: it explains why in its own comment, `/data` is close to full so writing
the zip out to disk is not an option either, and one job is small enough to
hold resident.

The whole-account export in `server/routes/auth.py` used to buffer on the same
reasoning, and that was not fine. It is by definition the largest archive the
app can produce, every job a person owns rather than the ones they chose to
file, so it was the worse case of the two rather than a smaller one. It now
uses the same stream, with its archive layout deliberately unchanged.

A project is not one job. A single orbital cube here runs to about seven
megabytes, so a study-sized archive held resident would be hundreds of
megabytes per concurrent download, in a FastAPI worker thread. Measured, a
project holding a 200 MB artifact now grows the api container's resident set by
one megabyte while downloading.

No new dependency was needed. Python's `zipfile` already emits data descriptors
instead of seeking backwards when its output object answers `False` to
`seekable()`, so all that was missing was an object to write into. The
generator drains that sink inside the per-file read loop rather than after each
member, which is what keeps a single large cube from being resident either.

The archive carries a `{slug}_manifest.csv` at its root naming each job in the
terms a chemist would use, plus engine, method, status, date and size. A
directory of engine output files says nothing about which calculation produced
which, and the manifest is what makes an archive readable a year later.

### An archive is not exempt from the storage quota

`_evict_oldest_first` sorts on `(archived, created_at)` rather than
`created_at` alone, so quota eviction exhausts every unfiled job before it
touches a project archive, whatever the dates say.

Deliberately an ordering and not an exemption. A category nothing can reclaim
would let a user fill their quota with un-evictable data and then be unable to
submit anything at all, which is a worse failure than losing the oldest of a set
of finished results. Someone who took the trouble to name a project and file
jobs into it has said something about what they want to keep, and the ordering
is where that gets respected without breaking the cap.

### Deleting a project asks, every time

"Delete this project" is genuinely ambiguous. It can mean "I am done with this
grouping, put the jobs back" or "this study was a dead end, take the results
too", and guessing wrong in the second direction is unrecoverable. So
`DELETE /api/projects/{id}` takes an explicit `delete_jobs` query parameter
with no default, and the dialog offers both options with neither preselected
and neither focused: Radix would otherwise focus the first button, which is a
default answer by another name.

The cascading option is gated on typing the project's own name rather than a
fixed phrase like `DangerZoneSection`'s `PurgeAction` uses. That component
guards a single deployment-wide action where any phrase is as good as another;
here there may be a dozen projects on screen, and the thing worth confirming is
which one is about to lose its results.

Deleting the whole ACCOUNT is the one case that does not ask, and takes
everything. `purge_user_data` removes the user's projects and, through the
same owner-filtered job pass it already ran, every job in them. There is
nobody left to put the question to, and the alternative is worse than either
answer: the project rows used to survive their owner while
`ownership_index`'s `ON DELETE CASCADE` took their ownership rows away, and an
unowned project is deliberately visible to *everyone*, so deleting an account
quietly converted its private archives into deployment-wide public ones. That
visibility rule is not what changed. It is right, and narrowing it would make
an unowned resource undeletable by anyone. What changed is that a deletion
stops manufacturing orphans for it to apply to. The projects are removed
before the job pass rather than after, purely so that `delete_job_dir`'s
per-job `registry.prune_job` call is a no-op instead of a read-modify-write of
`projects.json` once per job.

A job in the deleted user's project that belongs to somebody else, reachable
only when an admin filed it there, is left alone by the same owner filter.

The per-user "delete all my projects" in the account danger zone is scoped off
`models.list_owned("project", user_id)` and never off what
`GET /api/projects` returns. `owned_ids_filter` returns `None` for an admin,
meaning "do not filter", so that route shows an admin every project on the
deployment; an admin typing the confirmation phrase into a control labelled
"delete all of *my* projects" must not wipe everybody else's.

### The global job list hides archived jobs; the per-conversation one does not

`GET /api/jobs` takes `include_archived`, false by default. The
per-conversation `GET /api/threads/{id}/jobs` is deliberately not filtered: a
job never stops belonging to the conversation that started it.

`job_project_map()` is one read of a small flat file taking no lock of any
kind, which is what keeps `server/routes/jobs.py`'s lock-free contract intact.
The routes themselves live in `server/routes/projects.py` rather than being
added to `jobs.py`, so that module's contract does not have to be re-verified
every time the archive changes.

---

## Sharing

A user can hand a finished job, or a whole project archive, to another user.
The picker finds people by username or by their real name, the offer lands in
a "Shared with me" section in the recipient's left rail, and accepting it puts
a copy in their account.

### A share is a copy, not a grant

The requirement that settled this was stated up front: **the recipient keeps
the result even if the owner deletes theirs.** No reference-based share can
give that, and the reasons are structural rather than a matter of effort.

`_evict` in `app/auth/storage_quota.py` and `purge_user_data` beside it delete
a job after consulting nobody but its owner, so a grantee's access could
evaporate under quota pressure they never caused. `ownership_index` has
`PRIMARY KEY (kind, resource_id)`, so a second owner cannot be expressed in
the table the whole app reads as a scalar. And `add_jobs` in
`app/projects/registry.py` enforces one project per job in a single atomic
write, so a donor and a recipient could not both file the same job into their
own archives.

Copying inverts all of it. The recipient's copy is an ordinary job with its
own id, its own `ownership_index` row and its own quota bytes, which is why
this feature changed **nothing** in `app/auth/ownership.py` and nothing in any
list route's filter. The bytes genuinely exist twice on disk, so counting them
against both users is correct rather than double-counting.

The cost is honest and worth stating: a share of a 54 MB orbital job really
does consume another 54 MB, and the copy does not track the original. A rename
or a re-render on the sender's side never reaches it. That is the trade the
durability requirement buys.

### `spec.json` is written last, and ownership is recorded before it

This is the invariant `app/chemistry/jobs/copy.py` is built around.

Every walk that enumerates jobs gates on `spec.json` existing:
`_iter_all_job_specs` in `server/routes/jobs.py`, `_iter_job_ids_on_disk` in
`base.py`, `_iter_job_ids` in `quota.py`. So a half-built copy is invisible to
listing, to quota accounting and to deletion, and the copy gets its atomicity
for free. A failure part-way leaves a directory with no `spec.json`, which is
exactly the shape `reclaim_orphan_job_dirs()` already sweeps after its
one-hour age gate. There is no rollback code because none is needed.

Ownership is recorded immediately **before** that final write rather than
after. A job that is visible with no ownership row is visible to *every* user:
`check_owner_or_admin` treats an unowned resource as legacy and public, and
the job list has an explicit `not in owners` clause saying so. The window
would have been microseconds, but it is the exact shape of F-022 and SEC-06,
and closing it costs nothing.

### Two things a directory copy alone gets wrong

**Artifact paths are absolute and carry the job id.**
`GET /api/jobs/{id}/artifacts/{key}` opens whatever string it finds in
`result.json`, so a `shutil.copytree` alone produces a copy that still serves
the sender's files and 404s the moment they delete them. The rewrite recurses,
because `cubes` is a nested dict and a top-level-only walk would leave every
orbital cube pointing at the sender.

**Some artifacts point outside the job directory entirely.** `uvvis_spectrum`
and `ensemble_spectrum` point into `PLOTS_DIR`, at a plot object the sender
owns, and `PLOTS_DIR` is one of the artifact route's allowed roots. Reusing
that path would serve the sender's image cross-user, and would also pin it
forever, since `sweep_orphans()` reclaims a plot only once its **last** source
job is gone. So `app/plots/store.py`'s `copy_plot_to_owner` duplicates the
plot into the recipient's own owner directory with a fresh id, and the copy's
artifact points there.

### A master copies as a whole family, and its children stay unowned

A scan or ensemble master's sub-jobs live in sibling directories carrying
`parent_job_id`, found through the master's own `children.jsonl`. Copying the
master alone would hand the recipient a scan whose frame slider has nothing
behind it, so the whole family is copied: fresh ids, `parent_job_id`
repointed, the manifest regenerated, and `params` verbatim so `_scan_index`
keeps the images in order. Children are written before the master's
`spec.json`, so the master is never visible for an instant with an empty
panel.

The copied children deliberately get **no** `ownership_index` row, matching
what `JobManager.submit` does for a natively-run scan. `_job_candidates` does
not skip child jobs, so an owned child would become an independent eviction
candidate and quota pressure could delete one out from under its master,
leaving a scan with a hole in it. Leaving children unowned is precisely what
makes `owner_filter` skip them.

### An offer is a row; accepting is what spends storage

Nothing is copied when a share is sent. `resource_shares` holds one row per
offer, and the files move only when the recipient accepts. That ordering is
what makes the other three properties possible: nobody can push gigabytes into
another account unasked, the sender can withdraw an offer until it is
answered, and the quota decision happens at a moment the recipient chose.

Accepting therefore checks headroom first and **refuses** rather than
evicting. Every other quota path in `storage_quota.py` reacts to an overrun by
deleting the oldest thing, which is right when a user's own submission caused
it and wrong when the bytes arrive on somebody else's initiative. So
`fits_for_user` is a non-evicting check, it names both figures in its refusal
because "quota exceeded" gives a user nothing to act on, and a refused offer
stays pending so it can be retried after making room.

Two smaller decisions in the same area. The size is recomputed at accept
rather than read from the offer's snapshot, since `meta.json`'s
`dir_size_bytes` is a cache and a stale under-report would let a share past
the cap. And `set_share_status` is a compare-and-set carrying
`status = 'pending'` in its `WHERE`, so two accept clicks racing each other
leave one winner rather than copying the job twice.

### What the picker publishes, and what it does not

Before this feature, no ordinary user could learn that another account
existed: ownership was purely a filter and every list route stripped other
people's rows before they reached the client. A picker has to give some of
that up, so it gives up as little as possible. `search_users` returns exactly
`id`, `username`, `first_name` and `last_name`. It deliberately reuses neither
`get_user_by_login` (whose projection includes `password_hash`) nor
`_user_public` in `server/routes/auth.py` (which carries email and role).
Inactive accounts and the caller are excluded, a query under two characters
returns nothing rather than the roster, and `LIKE` wildcards are escaped so
`%` is a literal.

The `ILIKE` has no supporting index and that is deliberate. `users` is a
lab-sized table, the query runs behind a picker, and an expression index would
cost more to maintain and explain than it saves.

### Conversations are out of scope

Sharing a thread would mean copying LangGraph checkpoint rows, which live
behind `graph.py`'s `_graph_lock`. Doing that from these routes would break
the lock-free contract `server/routes/jobs.py` and `server/routes/projects.py`
both hold, and which `server/routes/shares.py` holds for the same reason. A
received job therefore lands in the Job Manager attached to no conversation,
carrying a "from <sender>" badge, and the recipient can attach it to a
conversation of their own like any other job.

---

## Known limitations

Stated plainly, because a limitation you know about is cheaper than one you
discover.

**Engine coverage**

- CASPT2 is BAGEL-only; ORCA implements NEVPT2 instead. Oscillator strengths for
  CASSCF and EOM-CCSD are ORCA-only. There is no workaround for either.
- NEB-TS is ORCA-only. PySCF has no native NEB implementation and this project
  does not build one. A PySCF path was assessed as feasible, IDPP for the
  initial path, ASE's climbing-image NEB over a PySCF calculator, then
  `geometric_solver.optimize(transition=True)` to refine, but it would need
  hand-rolled convergence criteria and would run serial per-image evaluations
  with no equivalent to ORCA's image-level parallelism.
- NEB-TS's excited-state path is less verified than its ground-state path. Two
  real runs confirmed the input is generated correctly and drives genuine
  per-iteration excited-state gradient steps, and that a real ORCA-side rejection
  is surfaced as a failed job, but neither reached a converged excited-state
  transition state, so the exact energy-column semantics on a *successful* run
  were not directly confirmed.
- BAGEL's CASSCF/CASPT2 geometry optimisation and frequencies are
  **structurally confirmed and observed executing correctly, not
  convergence-verified end to end.** Minimal runs showed BAGEL genuinely parsing
  and acting on the input shape, real optimiser setup output followed by the
  nested CASSCF starting with correct parameters, but neither was allowed to
  reach full convergence. Re-run a full test before relying on it for a result.
- BAGEL's conical-intersection optimisation has only that same structural
  verification. A Phase 6 run completed without error but did not converge to
  a true crossing within 100 cycles on an arbitrary water/CASSCF(4,4)/SVP
  system (excitation gap stayed ~7.6 eV) -- consistent with "structural, not
  convergence-verified" rather than a regression; a genuinely hard search on
  this system, not a broken mechanism.
- ORCA's conical-intersection optimisation (Phase 6; `opt/ci`, HF/DFT via
  `%CONICAL`) needs the dedicated `! CI-OPT` keyword, not `! Opt`. The
  distinction matters because both accept the identical `%TDDFT`/`%CONICAL`
  blocks without complaint, but `! Opt` silently does nothing with them (a
  live rerun showed 0.013s of "Geometry relaxation", i.e. no search at all),
  while `! CI-OPT` genuinely drives the crossing gap to zero. This is why the
  Phase 0 capability spike's "accepted and terminated normally" verdict for
  this cell was wrong, that phrasing is the same "ran without error" evidence
  class this project already distrusts for BAGEL's `fix_atom`, and why this
  project's own rule (verify against real output, not against a clean exit
  code) exists.
- Software this project does not wrap at all (Gaussian, NWChem, Q-Chem, Psi4,
  Molpro) has no execution path whatsoever, by design. `custom` is ORCA/BAGEL
  only. The agent will compose an input file for such a program in its reply and
  say plainly that it cannot run it.

**Scope boundaries**

- Automatic orbital visualisation does not extend to `geometry_optimization`,
  `frequency` or `pes_scan`. Extending it would mean deciding which geometry's
  orbitals to export from a multi-step run.
- Constrained geometry optimisation (Phase 6) is implemented on PySCF
  (geomeTRIC's `constraints` kwarg, fed a generated `$set` constraints file --
  confirmed live that its atom numbering is 1-based, matching this app's own,
  so no index conversion happens there) and ORCA (`%geom Constraints`, whose
  own block IS 0-based internally, confirmed live and converted at that one
  boundary). BAGEL is mechanically denied: `fix_atom` is accepted and silently
  ignored (see the capability table), not merely undocumented.
- `interp_pes` (the two-endpoint scan) offers Cartesian interpolation, true
  internal-coordinate LIIC (`interpolate.liic_path`, via `zmatrix.py`'s NeRF
  reconstruction) and IDPP (the default). `pes_1d` (the single-coordinate
  scan) is proper internal-coordinate manipulation via RDKit bond/angle/
  dihedral perturbation (`pyscf_runner.build_coordinate_scan_images`,
  engine-agnostic despite its module name).
- `pes_1d` is mechanically denied on BAGEL (Phase 7, `registry2.tasks`'s
  `engines=("pyscf", "orca")`) -- not a capability gap, since every
  pes_1d image dispatches as an ordinary single_point/gs sub-job BAGEL
  runs identically to the other two engines, but a scope decision, the
  same allow-list mechanism `neb_ts`'s ORCA-only restriction already
  used. The denial names `interp_pes` as the alternative in its own
  refusal text (`TaskDef.engine_denial_hint`, surfaced through
  `route_engine`'s existing refusal path -- no special-cased branch).
- `interp_pes`'s two endpoints no longer have to arrive with their atoms
  in the same order (Phase 7). `interpolate._reconcile_endpoints` always
  computes the minimum-total-distance one-to-one atom correspondence
  (`scipy.optimize.linear_sum_assignment`, per element) between the two
  geometries; a genuine element-count mismatch still hard-refuses (not
  the same molecule at all), but an order mismatch is reordered and
  always surfaced as an approval-card warning rather than rejected
  outright. This is deliberately keyed on the computed geometric
  correspondence, never on whether `end["symbols"]` merely looks
  reordered as a string list -- two same-element atoms read identically
  in that list regardless of which physical atom is which, so a molecule
  can have its atoms genuinely swapped between endpoints while the
  symbols list stays trivially equal. A reorder is only applied when it
  is a strictly cheaper correspondence than the given order (not merely
  whenever the optimal assignment differs from identity by floating-point
  noise), so a correctly-ordered pair that has moved a lot -- a real
  reaction path -- is never spuriously relabeled. Still a heuristic for a
  highly symmetric molecule, which is why it always warns rather than
  treating a reorder as settled.
- `interp_pes`'s hand-edited approval-card input is a TEMPLATE (Phase 7),
  not single-image-only the way `pes_1d`'s edit is: every image is the
  same molecule at a different geometry, so an edit (an extra keyword, a
  tightened setting) is applied to every image via geometry substitution
  (`app/chemistry/jobs/scan_template.py`, ORCA `* xyz` block / BAGEL
  `"geometry"` array, both mechanically located the same way
  `validate.py`'s structural checks already do), proven against the
  master's own starting geometry once at approval time rather than
  discovered broken mid-scan. `pes_1d`'s edit still applies to image 0
  only (`image0_raw_input`) -- the two master tasks now have genuinely
  different edit semantics, both stated explicitly on the approval
  card's own note text so a user who has seen one does not assume the
  other behaves the same way.
- `batch` (Phase 7) fans ONE calculation (its `child_task`) out over every
  geometry produced by another job. It began as job types 1-4 only
  (single_point, opt, freq, opt_freq), restricted from the plan's original
  1-6 by the user on 2026-08-20; pes_1d/interp_pes stay out to this day,
  since nesting a master job inside a master job was ruled out of scope.
  On 2026-09-01 it gained excited states, gradients, non-adiabatic
  couplings and both `opt` subtypes, which is the whole point of running
  a calculation at every point of a scan and had simply been missing.

  The recorded reason for excluding `opt`'s constrained and CI subtypes
  was that they "need per-geometry params that do not generalize across a
  batch the same way a plain method+basis does". That was half right, and
  the halves needed separating. A conical-intersection optimization
  generalizes fine: its per-job parameters are a pair of states, and the
  same pair means the same thing at every geometry. A constrained
  optimization genuinely does not, because a constraint carries a VALUE,
  and one absolute value applied to every image of a scan drags them all
  to the same structure. So rather than exclude it, a constraint may now
  omit its value, meaning "hold this coordinate wherever this geometry
  already has it" -- the relaxed-scan shape such a batch is almost always
  wanted for. Each child's value is measured on its own structure by
  `geometry_resolve.measure_geometry_parameter`, the same function that
  answers a user's "what is this dihedral", so the two can never disagree;
  `_build_batch_spec_or_error` fills child 0's the same way, because an
  approval card showing a constraint with no number would misstate what
  is being approved, and the batch note gains a clause saying which
  coordinate varies per job.

  Widening the child set also exposed that a batch elicited only its OWN
  parameters. That is why the original four were exactly the four needing
  nothing beyond method and basis: a coupling child needs `state_pairs`
  and an excited-state child needs `n_excited_states`, and those
  ParamSpecs are declared against the child task, not against `batch`.
  `elicitation._missing_for_draft` now walks batch's own parameters first
  (so `child_task` is answered before anything that depends on knowing
  it) and then the child's. The same function is why a batch's child
  parameters are validated at all: `_build_spec_or_error` returns early
  for a batch, so `_validate_task_params` is called explicitly against the
  child's `(task, subtype)` -- an unvalidated model-written parameter
  becomes N bad jobs in a batch rather than one.

  `chain_orbitals` (off by default) starts each geometry's calculation
  from the previous one's converged orbitals, which keeps a multireference
  active space from changing character partway along a path -- the usual
  reason a CASSCF scan through a conical intersection comes back
  discontinuous. It is off by default and warned about on the card
  because it caps the in-flight wave at one, turning a parallel batch into
  a serial one; trading a batch's whole concurrency for an accuracy gain
  nobody asked for is exactly the kind of silent consequential default
  this app does not make.

  A finished batch no longer reports completion counts alone.
  `batch_aggregate` collects each child's headline numbers, indexed by the
  child's own `_batch_index` rather than by position (dispatch is trickled
  and quota eviction can reap an early child, so the two are not the
  same), and joins them to the source scan's own `coordinate_values` where
  it has them -- which is what makes "|NAC| against the torsion angle"
  possible rather than "|NAC| against image number". Only the child tasks
  with an obvious single headline number per state or pair are aggregated:
  a batch of optimizations is deliberately left with its counts, because
  optimizations that converged to different minima at each geometry are
  not one curve and drawing them as one would assert a continuity the
  calculation does not have.

  `child_task` has no
  default (`registry2/params.py`, same "ask, never silently resolve"
  precedent `neb_ts`'s `preopt` set). An omitted field is a question, not
  a single-point guess. The `batch` `TaskDef` itself carries no
  `requires` at all, deliberately: unlike every other task, batch has no
  level of theory of its own, so a fixed capability tuple on it would be
  fiction (an early version had `requires=("energy",)`, which is
  trivially true for every method and so never actually gated anything).
  Instead `elicitation.py`'s two capability-check call sites
  (`route_engine`, the final `supports()`) substitute the CHILD task's own
  `(task, subtype)` via `_capability_task()`, reusing `opt/min`'s or
  `freq`'s own `requires` rather than re-deriving a parallel rule. An
  `opt` child on a method with no gradient anywhere (`eom_ccsd`) is
  refused with the real reason, not silently accepted the way the fixed
  tuple would have let it through. Before `child_task` is answered,
  `_capability_task()` falls back to the trivial `("batch", "")` verdict
  and routing picks its usual default; the next `validate_draft()` call
  re-derives routing against the real child task once it is known, since
  routing is recomputed from the whole draft on every call rather than
  cached, so no draft can get stuck on an engine choice made before the
  capability that actually matters was known.

  Which job a batch can pull geometries from was widened the same day
  from geometry_set-only to any of geometry_set/pes_1d/interp_pes/
  wigner_spectra/neb_ts (`tasks.BATCH_GEOMETRY_SOURCE_ARTIFACT_KEY`),
  all five already render their geometries as plain multi-frame xmol
  text, just under different artifact keys (`path_xyz` for the first
  three, the literal `_write_path_xyz` helper. `ensemble_xyz` for
  wigner_spectra under the same helper, `neb_frames` for neb_ts via plain
  text concatenation of two already-valid standalone xmol blocks), so one
  `parse_multi_frame_xyz` reads all of them without a per-source parser.
  `pes_1d`/`interp_pes`/`wigner_spectra` all render their geometry
  artifact in full before dispatching any child of their own, so a batch
  can source from one still in flight; `neb_ts`'s `neb_frames` exists
  only once its single run has finished, which the existing
  "no geometries on disk yet" branch already covers with no extra status
  check. The ParamSpec was renamed `source_geometry_set_job_id` ->
  `source_job_id` outright (no compatibility alias) once the accepted set
  stopped being just geometry sets, per this project's standing rule
  against carrying a legacy name forward. Individually-tagged geometries
  that are not themselves a job (the instrument panel's frame-tagging
  mechanism, Phase 3) remain out of scope. They would need a different
  resolution path (thread-local conversation state, not a job artifact on
  disk) than the job-to-job case built here.

  That last gap closed the same day: 3+ individually-tagged
  molecule-panel frames now serve as a batch source too, resolved by a
  new special-case step in `elicitation.py::validate_draft` placed
  beside `_end_molecule`'s own frame-resolution block and following its
  exact shape. Guarded on neither `source_job_id` nor
  `_frame_geometries` already being present, so it resolves once and
  never re-derives on the resume pass after approval (the same guard
  `_end_molecule`'s resolution already relies on for the same reason).
  `_frame_geometries` is never a declared ParamSpec, matching
  `_end_molecule`'s own status. It is derived from state, never typed
  into a field. `source_job_id`'s `required_when` changed from `ALWAYS`
  to `{"missing": "_frame_geometries"}`, which needed checking through
  `missing_required()` itself rather than trusted from `evaluate()` on
  the bare condition. The two are easy to conflate and only one of them
  reflects what `validate_draft`'s own parameter sweep actually asks
  for. An explicit `source_job_id` always outranks on-screen frames, so
  a named job is never silently overridden by whatever else happens to
  be tagged; 3 is the adoption floor, matching `geometry_set`'s own
  established "three or more" upload convention, and 1–2 frames fall
  through to the ordinary `source_job_id` question instead (whose `ask`
  text now names the tagging alternative too). Because `molecule_frames`
  is an append-only log of every molecule the user set the whole
  thread, not a curated batch selection. The auto-adoption note names
  every adopted frame's own description, not just a count, so a wrong
  adoption is visible on the approval card rather than discovered three
  dispatched jobs later. At dispatch time, the round-tripped approved
  spec's own `_frame_geometries` is used as-is rather than re-reading
  `state['molecule_frames']` a second time, which could disagree with
  what the approval card actually showed if the panel changed in
  between. The mirror-image concern to why `source_job_id`'s own
  geometries are always re-read fresh from disk rather than reused from
  the draft (there the risk is a stale in-memory copy; here it is a
  live state read disagreeing with what was shown).

  A related, broader request came out of this same conversation and was
  deliberately NOT built here: a general default geometry-selection
  hierarchy for every job type (an explicit tag, then conversation
  context such as "use the same geometry" or "repeat with a different
  basis", then the active instrument-panel frame, in that priority
  order) whenever a request does not name a geometry explicitly. That is
  cross-cutting rather than batch-specific and needs its own design pass
  (see `docs/OVERHAUL_PLAN.md`'s Phase 9, P9.3), in particular, how
  "conversation context" gets recognized mechanically rather than left
  as prompt-only guidance the model can and will get wrong.
- `plot(kind="comparison")` supports a fixed set of six named scalars only, and
  a request outside that set gets a plain "not supported" rather than a guess.
  That is a limit on the *named* shortcut, not on plotting: `kind="custom"`
  takes any field path a job's summary really holds, indexed elements of a list
  included, in four mark styles and on either a categorical or a numeric axis.
- Hand-editing approval-card input is ORCA/BAGEL only, and its validation is
  structural, not a dry run, neither engine offers one. A syntactically valid
  edit can still fail chemically.

**Known gaps**

- There is no general pre-flight basis-set or keyword validator. An invalid basis
  outside the two narrow corrected cases is still only caught when the engine
  fails at runtime; the *Troubleshoot* action is how that failure becomes a
  diagnosis.
- Opening a conversation whose agent turn is currently running **used** to
  block on that thread's lock, measured at 19.5 s for an ordinary turn and
  longer for a troubleshooting one. That was written up here as the lock
  working as designed, and it was not: the lock exists so a
  `get_state`/`update_state` pair cannot interleave with another write, and
  `read_state`/`pending_approval` only ever read. They no longer take it. A
  read behind a running turn went from 5.7 s to 9 ms against a synthetic
  6-second hold, and writes still serialize exactly as before (see
  `tests/backend/perf_06_lockfree_reads.py`, which asserts both halves,
  because a change that made everything lock-free would satisfy the first and
  destroy the invariant).

  The knock-on mattered more than the page load. `job_watcher` calls
  `pending_approval` once per thread on every poll tick, so one conversation's
  long turn used to stall the entire watcher and delay job-finished notices on
  every *other* conversation.

  A read during a turn now returns the last committed checkpoint rather than
  the finished turn, which is the better answer as well as the faster one: the
  rest of the turn arrives over SSE as it happens, instead of landing all at
  once after a stall that looks like a hang. The related UI defect, a "start a
  new conversation" welcome screen shown during the wait, was fixed separately
  and still shows an explicit loading state.
- `web_search` is the only component that calls the public internet, and it sends
  query text, which may include job parameters or error messages, to a third
  party. It is ungated, on the reasoning that a search carries the risk profile of
  a search rather than an action, but it is a genuinely different trust boundary
  from everything else here.
- BAGEL's standalone `casscf` job type and agent-driven `pes_scan` are less
  thoroughly tested than other paths.
