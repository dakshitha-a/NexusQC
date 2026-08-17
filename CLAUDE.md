# CLAUDE.md

Guidance for Claude Code (claude.ai/code) when working in this repository.

**Read [`docs/WORKFLOW.md`](docs/WORKFLOW.md) first — it is the primary guide to
managing this project.** Branching, merging, pushing, releasing, testing and
promoting to the lab's deployment, in one place. The rules in it are enforced by
the tooling rather than trusted to memory, and the short version is:

- Every session works on **its own branch**, never directly on `main`.
- Work is **merged into `main` (fast-forward only) before any push.** The history
  is deliberately linear, and a branch is scaffolding — `main` is the product.
- **Before any push to release, report every unmerged branch**, so nothing meant
  for the release is silently left behind.
- **Production only ever receives commits the dev stack has verified**, and
  anything destructive is described in advance and specifically.

**Then read [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md).** It explains how
the system is put together and, more importantly, why each significant decision
was made and what alternative was rejected. Almost every question of the form
"why is this done the awkward way?" is answered there. This file covers only the
working agreements that govern *how to make changes*.

If a `CLAUDE.local.md` exists alongside this file, it holds machine-specific
details for this particular checkout — absolute paths, install locations, and
observations that are true of one host rather than of the project. It is
deliberately untracked.

## What this is

NexusQC — a conversational computational-chemistry agent. A React single-page app
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
spec = JobSpec(method='single_point', engine='pyscf', molecule=m.to_dict(),
               params={'method':'hf','basis':'sto-3g'})
print(get_job_manager().submit(spec))
"
```

Or drive the graph directly with `app.agent.graph.invoke_turn(...)` to test a
full conversational turn without the UI, or curl the routes in `server/routes/`.

**`tests/` is a real, standing suite for the multi-user auth/admin layer
specifically** — account creation, login, session lifecycle, ownership
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

- A `sec_*` script printing `[FAIL]` is often the expected, informative outcome —
  several exist specifically to prove a gap is real. See `tests/README.md`.
- Every script in `tests/backend/` shares one apparent client IP, which collides
  with the per-IP login rate limiter. `tests/fixtures.py`'s `admin_client()`
  resets the buckets before logging in, so each script starts with a full budget.
  Scripts that must exceed the budget within their own run reset around their own
  heavy sections.

`tests/backend/sec_10_*` is excluded from `run_backend.sh` by default —
destructive-shaped even though scoped to a disposable account — and must be run
manually.

## Frontend changes must be verified in a real browser

Launch both dev servers headless and drive the app with Playwright (chromium
only) rather than trusting a code read. Several real bugs here appeared only
under real browser interaction — see `docs/ARCHITECTURE.md`'s notes on the React
Strict Mode WebGL leak, which a code-inspection fix silently failed to address.

Two specific traps:

- **`page.screenshot()` cannot reliably capture WebGL canvas content.** Use
  `canvas.toDataURL()` via `page.evaluate()` for anything the molecule or orbital
  viewers render.
- **nginx serves `frontend/dist` via a host bind mount**, independent of whatever
  is baked into the image. Any frontend change intended for the compose
  deployment needs an explicit `npm run build` on the host — `docker compose
  build` will not refresh it.

## Conventions that are easy to violate accidentally

- **Every FastAPI route handler is a plain `def`, never `async def`.** A sync
  handler runs in a worker threadpool; an `async def` that blocks stalls the
  single event loop, including SSE delivery to every other open tab.
- **`server/routes/jobs.py` is deliberately lock-free.** It must never call
  `read_state()` or take the graph lock, or polling will stall behind chat turns.
- **Never call `invalidate_graph_cache()` from inside a tool function.** It
  deadlocks — see `docs/ARCHITECTURE.md`.
- **Atom numbering is 1-based everywhere** a user or the model sees it. RDKit is
  0-based, so conversions happen at that boundary and never leak outward.
- **`app/chemistry/jobs/registry.py` is the single source of truth** for which
  engine handles which method and which params are required. Don't hardcode that
  logic elsewhere.
- **Engine output parsers are derived from real runs, not documentation.** If you
  change one, verify against actual output — exact formatting is not guaranteed
  across versions.

## Two stacks: dev is destructible, production is not

There are two running deployments on this host, from two checkouts of this one
repository. Which one you are standing in is recorded in `.deployment-role` —
untracked, one word, `dev` or `production` — because both checkouts hold the same
commit and the same scripts, so nothing else distinguishes them at a glance.

- **dev** is destructible by design. `scripts/dev_stack.sh reset` drops its
  database volume and empties its `data/` after one typed confirmation, and that
  is routine rather than an emergency. It publishes on loopback and the tailnet
  only — never the LAN address lab users reach.
- **production** is the lab's deployment, used by real people who report bugs
  against it. It is never edited by hand, never on a branch (detached HEAD at the
  deployed commit), and only ever advanced by `scripts/promote.sh`, which refuses
  any commit without a passing row in `docs/deployment-ledger.md`.

Test on dev first — always, including small fixes. `scripts/check_destructive.sh`
reports in advance what a promotion will do; the four things it blocks on all
either fail silently or destroy something unrecoverable. See
[`docs/WORKFLOW.md`](docs/WORKFLOW.md) for the whole procedure.

## Two remotes: what "push" means

Development is continuous against a **private** remote (`origin`,
`NexusQC-dev`); publishing to the **public** remote (`public`, `NexusQC`) is a
separate deliberate act via `scripts/release.sh`. One branch, one history, no
sanitised parallel tree — see [docs/DEVELOPMENT.md](docs/DEVELOPMENT.md).

- "push" means `git push origin main` — and only after the session's branch has
  been merged into `main` with a fast-forward.
- "push to release" means `scripts/release.sh <version>`, which refuses unless
  the tree is clean, the scan passes, `main` matches the private remote, the tag
  is free, and `CHANGELOG.md` documents the version. It also **lists every
  branch not merged into `main`** and requires a typed confirmation before
  publishing without them, because a public push cannot be amended afterwards.

The invariant that makes this cheap: **everything tracked is publishable.** If a
value is true of one machine rather than of the project, it belongs in `.env` or
`CLAUDE.local.md`, never in a tracked file. Break that and the per-change
sanitisation cost comes straight back.

## Before pushing

`scripts/check_public_safe.sh` must pass. It scans for host-specific absolute
paths, credentials, bare institutional hostnames and machine-generated data.
Install the git hook once per clone with `scripts/hooks/install.sh` so this
cannot be forgotten — git does not track `.git/hooks`, so a fresh clone starts
with no hooks at all. The hook scans both the working tree and the commits being
pushed (`--range`), because content committed and then removed later leaves a
clean tree and a permanent leak in history.

Two limits worth knowing: the scan cannot read images, so any new screenshot
needs a human look; and one pattern is written as a character class
(`/[s]oftware/`) so a find-and-replace over history cannot rewrite the detector
itself. That is not a typo.

Optionally, `cp .claude/settings.local.json.example .claude/settings.local.json`
makes Claude Code run the same scan before any `git push` it issues. That is
deliberately opt-in and untracked rather than shipped as `settings.json`: it
adds a subprocess to every Bash call, and auto-executing a repository's own
script in someone else's environment is not a reasonable default to hand
someone who just cloned this.

Check whether `README.md` needs updating as part of any change that affects
installation, configuration or user-visible behaviour.

## A standing framing note

Long job runtimes are the design premise, not a defect. CASSCF and CASPT2 runs
routinely take tens of minutes and sometimes hours. Do not write them up as a
performance problem, a hang, or something to steer users away from. The
asynchronous job system exists precisely so a user can submit, leave, and return.
The only genuine defects in this area are ones that break the leave-and-return
workflow: a job that dies with its parent process, a status that never reaches
terminal, or a result that cannot be found afterwards.
