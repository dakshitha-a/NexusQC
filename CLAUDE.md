# CLAUDE.md

Guidance for Claude Code (claude.ai/code) when working in this repository.

**Read [`docs/WORKFLOW.md`](docs/WORKFLOW.md) first. It is the primary guide to
managing this project.** Branching, merging, pushing, releasing, testing and
updating a deployment, in one place. The rules in it are enforced by
the tooling rather than trusted to memory, and the short version is:

- **Every session works directly on `main`.** Development is serial, so there is
  nothing to isolate from; branches and worktrees are only for when you ask for
  one. The branch-per-session rule was retired on 2026-08-19.
- **The gate moved from merge to commit.** With no branch to park work on, commit
  only work you would be willing to deploy. Run the backend suite first, keep
  commits atomic, and use `git revert` as the undo.
- **Check for unpushed work when a session starts** and say so plainly. Without a
  branch, local-only commits are invisible until something trips over them.
- **Read [`docs/HANDOFF.md`](docs/HANDOFF.md) at the start of every session.** A
  session inherits the repository and never the previous conversation, so a step
  a previous session could not perform itself, a merge it lacked permission for,
  a rebuild only a person can run, lives there or is lost. If its "Open"
  section is empty, move on. If it lists something, do that before starting
  new work, then delete the entry.
- **Before any push to release, report every unmerged branch**, so nothing meant
  for the release is silently left behind.
- **A deployment only ever advances via `scripts/update.sh`**, which reports what
  the update will do, including anything destructive. Before touching anything,
  and takes a full backup first.
- **Public issues are worked with `/issue <n>`** and referenced in commits as
  `Refs: dakshitha-a/NexusQC#<n>`, never with a closing keyword. Nothing closes
  a public issue but a release; `scripts/release_announce.sh` does it from
  `release.sh`. `scripts/issues.sh list` shows the queue.
- **A task given while a plan is running is an amendment to the plan**, not
  a side task, and a hook reminds you of that on every message until the
  tracker is closed out. See the section of that name below.
- **Subagents that only read run on Sonnet**; anything that edits, plans or
  forks stays on the session model. See "Subagents" below.

**Then read [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md).** It explains how
the system is put together and, more importantly, why each significant decision
was made and what alternative was rejected. Almost every question of the form
"why is this done the awkward way?" is answered there. This file covers only the
working agreements that govern *how to make changes*.

If a `CLAUDE.local.md` exists alongside this file, it holds machine-specific
details for this particular checkout. Absolute paths, install locations, and
observations that are true of one host rather than of the project. It is
deliberately untracked.

## What this is

NexusQC, a conversational computational-chemistry agent. A React single-page app
talks to a FastAPI backend wrapping a LangGraph tool-calling agent, backed by a
local LLM served through Ollama's OpenAI-compatible endpoint. It resolves
molecules by name/SMILES/sketch, elicits missing job parameters instead of
guessing them, runs quantum chemistry jobs as background subprocesses across
PySCF/ORCA/BAGEL behind a human approval gate, and answers follow-up questions
from a RAG knowledge base.

A prior Streamlit UI was fully retired and deleted once the React frontend
reached parity. Comments referring to it describe a now-removed transitional
state; treat them as historical context for *why* a design choice exists.

## Running it

Two processes: the FastAPI backend and the Vite dev server.

```bash
# Terminal 1 -- backend (binds to localhost only)
conda activate qc-agent
cd /path/to/NexusQC && PYTHONPATH=$PWD python3 -m server.main

# Terminal 2 -- frontend (system Node is usually too old for Vite)
conda activate node24   # conda create -n node24 -c conda-forge nodejs=24
cd /path/to/NexusQC/frontend && npm run dev
```

Vite proxies `/api/*` to port 8000, so no CORS setup is needed locally.

`app/config.py` loads a project-root `.env` if present, so engine paths and
secrets can live there rather than in your shell profile.

## Testing conventions

**There is no pytest suite for the chemistry/agent core.** Validating a change
there means invoking the relevant runner directly:

```bash
PYTHONPATH=$PWD python3 -c "
from app.chemistry.molecule import resolve_molecule
from app.chemistry.jobs.base import JobSpec, get_job_manager
m = resolve_molecule('water')
# task/subtype say what the job IS; method says the level of theory. Passing
# method='single_point' (the pre-v2 shape) submits a job with an empty task
# that fails at dispatch with 'No runner is wired up for / yet.'
spec = JobSpec(task='single_point', subtype='gs', method='hf', engine='pyscf',
               molecule=m.to_dict(), params={'basis': 'sto-3g'})
print(get_job_manager().submit(spec))
"
```

Or drive the graph directly with `app.agent.graph.invoke_turn(...)` to test a
full conversational turn without the UI, or curl the routes in `server/routes/`.

**`tests/` is a real, standing suite for the multi-user auth/admin layer
specifically**. Account creation, login, session lifecycle, ownership
isolation, admin actions, storage quotas. It follows the same
invoke-and-print-script convention rather than introducing pytest:
`tests/backend/*.py` are standalone httpx scripts run via `tests/run_backend.sh`;
`tests/frontend/*.spec.mjs` are raw Playwright scripts (no `@playwright/test`
runner) run via `npm run test:e2e`.

Unlike the rest of the app, this suite needs the **full `docker-compose.yml`
stack**, not just a running `server.main`: the auth layer is inert without
`QC_AGENT_DATABASE_URL`, and several of the bugs it exists to catch are
properties of the nginx-fronted deployment rather than the bare process.

Two things that look like breakage but aren't:

- A `sec_*` script printing `[FAIL]` is often the expected, informative outcome.
  Several exist specifically to prove a gap is real. See `tests/README.md`.
- Every script in `tests/backend/` shares one apparent client IP, which collides
  with the per-IP login rate limiter. `tests/fixtures.py`'s `admin_client()`
  resets the buckets before logging in, so each script starts with a full budget.
  Scripts that must exceed the budget within their own run reset around their own
  heavy sections.

`tests/backend/sec_10_*` is excluded from `run_backend.sh` by default,
destructive-shaped even though scoped to a disposable account, and must be run
manually.

## Frontend changes must be verified in a real browser

Launch both dev servers headless and drive the app with Playwright (chromium
only) rather than trusting a code read. Several real bugs here appeared only
under real browser interaction. See `docs/ARCHITECTURE.md`'s notes on the React
Strict Mode WebGL leak, which a code-inspection fix silently failed to address.

Two specific traps:

- **`page.screenshot()` cannot reliably capture WebGL canvas content.** Use
  `canvas.toDataURL()` via `page.evaluate()` for anything the molecule or orbital
  viewers render.
- **nginx serves `frontend/dist` via a host bind mount**, so `docker compose
  build` alone will not refresh it. The bundle is built inside the api image and
  copied onto the host by `scripts/extract_frontend.sh`, which both
  `install.sh` and `update.sh` call after building. For a frontend change
  intended for the compose deployment, rebuild the image and run that script (a
  host `npm run build` produces the same bytes, verified, and is fine for
  iterating, but the image is the source of truth). Do not reintroduce a host
  Node dependency for deployment: it was the one prerequisite an installer could
  not fetch for itself.

## Conventions that are easy to violate accidentally

- **Every FastAPI route handler is a plain `def`, never `async def`.** A sync
  handler runs in a worker threadpool; an `async def` that blocks stalls the
  single event loop, including SSE delivery to every other open tab.
- **`server/routes/jobs.py` is deliberately lock-free.** It must never call
  `read_state()` or take the graph lock, or polling will stall behind chat turns.
- **Never call `invalidate_graph_cache()` from inside a tool function.** It
  deadlocks. See `docs/ARCHITECTURE.md`.
- **Atom numbering is 1-based everywhere** a user or the model sees it. RDKit is
  0-based, so conversions happen at that boundary and never leak outward.
- **`app/chemistry/registry2/` is the single source of truth** for which
  engine handles which method and which params are required: `capabilities.py`,
  `tasks.py`, `params.py`, `routing.py`, with `lookup.py` as the façade the
  agent and the API ask. Don't hardcode that logic elsewhere. (It replaced
  `app/chemistry/jobs/registry.py`, which no longer exists; older comments
  still name it.)
- **Engine output parsers are derived from real runs, not documentation.** If you
  change one, verify against actual output. Exact formatting is not guaranteed
  across versions.

## Standing up and updating a deployment

There is no separate dev/production apparatus in this repository. That
dual-checkout workflow, a destructible dev stack, a `.deployment-role` file,
`scripts/promote.sh` gated on a verification ledger. Was retired on
2026-08-21 once `scripts/install.sh` and `scripts/update.sh` existed as the
standard way to stand up and advance a deployment. Each deployment is just
its own independent checkout: `scripts/install.sh` for a fresh one,
`scripts/update.sh` to move an existing one forward.

`scripts/update.sh` reports in advance what an update will do,
`scripts/check_destructive.sh` catches the same four things that either fail
silently or destroy something unrecoverable (in-flight jobs, a silently
no-op schema change, a newly required `.env` variable, a bind mount that
would quietly disappear), and takes a full backup before touching anything.
It also diffs `requirements.txt` package by package and prints the version
transitions, flagging an added package as a possible new system dependency,
since that is what a source-only distribution turns into: a build failure
minutes in rather than anything visible in the file.
See [`docs/DEPLOYMENT.md`](docs/DEPLOYMENT.md) for the full install/update
story and [`docs/WORKFLOW.md`](docs/WORKFLOW.md) for where it fits in the
day-to-day git workflow.

## Two remotes: what "push" means

Development is continuous against a **private** remote (`origin`,
`NexusQC-dev`); publishing to the **public** remote (`public`, `NexusQC`) is a
separate deliberate act via `scripts/release.sh`. One branch, one history, no
sanitised parallel tree. See [docs/DEVELOPMENT.md](docs/DEVELOPMENT.md).

- "push" means `git push origin main`.
- "push to release" means `scripts/release.sh <version>`, which refuses unless
  the tree is clean, the scan passes on the tree **and on every commit being
  published** (file content and commit author emails), `main` matches the
  private remote, the tag is free, and `CHANGELOG.md` documents the version.
  It **lists every branch not merged into `main`** and always asks for one
  typed confirmation before the push, because a public push cannot be amended
  afterwards.

The invariant that makes this cheap: **everything tracked is publishable.** If a
value is true of one machine rather than of the project, it belongs in `.env` or
`CLAUDE.local.md`, never in a tracked file. Break that and the per-change
sanitisation cost comes straight back.

## Before publishing

`scripts/check_public_safe.sh` must pass **before anything reaches the public
remote**. It scans for host-specific absolute paths (`/home/<user>`,
`/data/<user>`, and the lab's licensed-software tree), credentials, bare
institutional hostnames and machine-generated data, and in range mode the
author and committer email of every commit as well.

The author's name is **not** a finding. It is in the repository URL, the
commit authorship and the README. What must never be published is a path that
describes a particular machine. Keep those out of tracked files; write the
name freely.

**Ordinary pushes to `origin` are not scanned.** `origin` (NexusQC-dev) is
private and stays private, so the scan was defending against a disclosure that
cannot happen there and only cost time. What keeps this safe is that
`scripts/release.sh`, the only route to the public remote. Runs the scan
itself, so publication is gated even with no hooks installed. Do not add a scan
back to the `origin` push path; if `release.sh` ever stops calling
`check_public_safe.sh`, that changes.

Install the git hook once per clone with `scripts/hooks/install.sh`. Git does
not track `.git/hooks`, so a fresh clone starts with none. The hook skips
private remotes, scans everything else (including any remote it does not
recognise), and when it does scan it covers both the working tree and the
commits being pushed (`--range`), because content committed and then removed
later leaves a clean tree and a permanent leak in history.

Two limits worth knowing: the scan cannot read images, so any new screenshot
needs a human look; and one pattern is written as a character class
(`/[s]oftware/`) so a find-and-replace over history cannot rewrite the detector
itself. That is not a typo.

Optionally, `cp .claude/settings.local.json.example .claude/settings.local.json`
makes Claude Code run the same scan before any `git push` it issues. That is
deliberately opt-in rather than part of the tracked `.claude/settings.json`:
it adds a subprocess to every Bash call, which is a cost to hand someone who
just cloned this. The tracked file carries only event-scoped hooks (the
plan-amendment reminders described below), which fire a few times a session
and touch nothing outside a gitignored directory. Claude Code merges the two
files, so the local one adds to the tracked one rather than replacing it.

Check whether `README.md` needs updating as part of any change that affects
installation, configuration or user-visible behaviour.

## Subagents

The session runs on Opus with the advisor on Fable, and a subagent inherits
the session model unless something lowers it. The lowering is explicit and
deliberate, so a forgotten rule overspends and never underplans. Never set
`CLAUDE_CODE_SUBAGENT_MODEL`; it flips that default the other way.

- `Explore` is defined in `.claude/agents/Explore.md` and runs on Sonnet.
  The definition replaces the built-in, so its body is the agent's whole
  prompt; edit it there. It carries a map of where things are in this
  repository, so keep that paragraph current when a top-level directory
  moves.
- A general-purpose agent that only reads, researches or verifies is
  launched with `model: sonnet`.
- An agent that edits the repository, a `Plan` agent and a fork stay on the
  session model.
- `claude-code-guide` is launched with `model: haiku`.
- The advisor stays on Fable; it must be at least as capable as the session
  model.

## A task given while a plan is running is an amendment to the plan

Work here usually starts in plan mode, and the user usually gives new tasks
while the plan is being executed. Those are the tasks that get dropped, so
they are not side tasks. When a message asking for work arrives mid-plan:
finish the tool call in flight, call `EnterPlanMode`, add the request to the
plan file as its own item with an acceptance criterion and a note that the
user raised it mid-run, add it to `docs/TRACKER.md` as its own step named as
raised mid-run, re-validate the plan's order and dependencies against what
is already done, `ExitPlanMode` for approval, then resume the item you were
on. A message that only asks a question is answered inline and the plan
continues; if the answer exposes a defect, the defect is an amendment.

`docs/TRACKER.md` is the ledger, as `docs/WORKFLOW.md` says: the plan file is
where an amendment goes for approval, the tracker is where it is checked
against the git log, and a plan is reported finished only once the tracker
is closed out with nothing left unmarked.
`scripts/hooks/claude_plan_amendment.py` enforces the timing: `ExitPlanMode`
writes a per-session marker under `.claude/plan-in-progress/`, every later
message the user sends arrives with a reminder of the rule while the marker
exists, a new session is told about any plan an earlier one left running,
and `python3 scripts/hooks/claude_plan_amendment.py done <session id>`
removes the marker when the tracker is closed out. The hooks are registered
in the tracked `.claude/settings.json`, which also puts plan files under
`.claude/plans/` in this checkout rather than the home directory, so the
plan sits beside the code it describes. Both directories are gitignored.
The rule is written here as well so it holds where the hooks are not
installed.

## A standing framing note

Long job runtimes are the design premise, not a defect. CASSCF and CASPT2 runs
routinely take tens of minutes and sometimes hours. Do not write them up as a
performance problem, a hang, or something to steer users away from. The
asynchronous job system exists precisely so a user can submit, leave, and return.
The only genuine defects in this area are ones that break the leave-and-return
workflow: a job that dies with its parent process, a status that never reaches
terminal, or a result that cannot be found afterwards.
