# Workflow

**This is the primary guide to managing this project.** Branching, merging,
pushing, releasing, testing and deploying, in one place. Everything here is a
standing rule rather than a suggestion, and the tooling enforces most of it
rather than trusting anyone to remember.

The related documents, and what each is for:

| Document | Answers |
|---|---|
| this file | *how do I make and ship a change?* |
| [ARCHITECTURE.md](ARCHITECTURE.md) | *why is the code shaped like this?* |
| [DEVELOPMENT.md](DEVELOPMENT.md) | *why two remotes, and what makes that safe?* |
| [DEPLOYMENT.md](DEPLOYMENT.md) | *how do I stand a deployment up from nothing?* |
| [TESTING.md](TESTING.md) | *what does the test suite actually cover?* |
| [deployment-ledger.md](deployment-ledger.md) | *which commits may reach production?* |

## The shape of it

One repository. One linear history on `main`. Two remotes, and two running
stacks:

```
        work on a branch
               |
               v
   +-----------------------+        git push origin main
   |  main (linear)         | ------------------------------> origin
   +-----------------------+                              NexusQC-dev (private)
        |             |
        |             |  scripts/release.sh <version>
        |             +---------------------------------------> public
        |                                                   NexusQC (public)
        |
        |  verified on the dev stack, then
        |  scripts/promote.sh
        v
   the lab's production deployment
```

Two rules make the whole thing work, and both are load-bearing:

1. **Everything tracked in git is publishable.** Host-specific values live in
   untracked files (`.env`, `docker-compose.override.yml`, `nginx/certs/`,
   `CLAUDE.local.md`, `.deployment-role`), never in a tracked one. This is what
   removes the need for a sanitised parallel branch — see
   [DEVELOPMENT.md](DEVELOPMENT.md).
2. **Nothing reaches production that the dev stack has not verified.** Not a
   habit; `scripts/promote.sh` refuses.

## Making a change

### Always start on a branch

Every session gets its own branch. Never commit directly onto `main`.

```bash
git checkout main && git pull origin main
git checkout -b <short-descriptive-name>
```

Background agent sessions isolate in a git worktree instead, which satisfies this
by construction (`.claude/worktrees/<name>`, on branch
`worktree-<name>`).

The reason is not ceremony. A branch means an unfinished change can be abandoned
without touching `main`, and `main` therefore always names something coherent —
which matters here because `main` is simultaneously what gets published and what
production is promoted from.

### Merge into main before pushing

The history is deliberately **linear**. Integrate with a fast-forward:

```bash
git checkout main
git merge --ff-only <branch>      # or rebase the branch onto main first
git branch -d <branch>
```

If `--ff-only` refuses, rebase the branch onto `main` and try again. Do not
create a merge commit, and do not push the side branch as the deliverable — the
branch is scaffolding, `main` is the product. Work left parked on a branch is
work that will be forgotten, and reconciling five divergent branches is a cost
this project has already paid once.

### Push

"Push" means the **private** remote, and only ever `main`:

```bash
git push origin main
```

The pre-push hook runs `scripts/check_public_safe.sh` over both the working tree
and the commits being pushed. Install it once per clone — git does not track
`.git/hooks`, so a fresh clone has none:

```bash
scripts/hooks/install.sh
```

### Push to release

Publishing to the **public** remote is a separate, deliberate act:

```bash
scripts/release.sh <version>              # e.g. 1.1.0
scripts/release.sh <version> --dry-run    # run every gate, push nothing
```

It is a sequence of refusals, not a warning: on `main`, clean tree, both remotes
configured, safety scan passes, `main` matches `origin/main`, the tag is free,
`CHANGELOG.md` documents the version, and the public remote can be advanced
without discarding published history.

**Before publishing it reports every branch not merged into `main`** — local and
remote, how far ahead each is, and when it was last touched — and requires a
typed confirmation to continue without them. A public push cannot be amended
afterwards, so being told about stranded work belongs before it rather than in a
postmortem.

## Testing

### Where a change gets tested

| Change | Test it with |
|---|---|
| chemistry, agent, tools | run the thing directly — see [TESTING.md](TESTING.md); there is no pytest suite for this |
| frontend | a real browser via Playwright, not a code read |
| auth, admin, ownership, quotas | the standing suite, against the **dev stack** |
| anything going to production | the **dev stack**, then `dev_stack.sh verify` |

`python -m server.main` plus `npm run dev` remains the fastest loop for most
work and nothing replaces it. But the auth layer is inert without
`QC_AGENT_DATABASE_URL`, and a real class of bugs here exists only in the
containerised, nginx-fronted deployment. Those need the dev stack.

### The development stack

A second checkout, running the same compose file with
`docker-compose.dev.yml` layered on top. **It is destructible on purpose.**

```bash
scripts/dev_stack.sh up          # bring it up
scripts/dev_stack.sh status      # what is running, at which commit
scripts/dev_stack.sh logs api    # follow logs
scripts/dev_stack.sh frontend    # rebuild frontend/dist
scripts/dev_stack.sh down        # stop, keep the database
scripts/dev_stack.sh reset       # destroy database, volumes, jobs/threads/uploads
scripts/dev_stack.sh reset --all # ...and the knowledge base too
scripts/dev_stack.sh verify      # run the suite; record the commit as promotable
```

`reset` is a normal thing to do, not an emergency. Nothing in the dev stack is
backed up and nothing depends on it.

It deliberately **keeps `data/kb`, `data/scraped`, `data/molecules` and
`data/bse_basis_cache`.** Those are seeded content, not test residue — the vector
store is slow to rebuild from the scraped corpus — and a destructible stack you
avoid destroying because resetting it costs an hour of reseeding is just
production with fewer users. `reset --all` wipes them when the knowledge base is
itself what changed.

Four things keep it away from production, because sharing one host means the
separation has to be deliberate at every layer:

- **separate directory** — `./data` and `./frontend/dist` are relative bind
  mounts, so two stacks in one directory would share the users' job store.
- **separate compose project** (`COMPOSE_PROJECT_NAME`) — so the Postgres and
  Redis volumes cannot be the same bytes.
- **no LAN bind** — the dev stack publishes on loopback and the tailnet only,
  never the address lab users reach. `docker-compose.dev.yml` uses `!override`
  to *replace* the port list, because compose otherwise *appends* and dev would
  quietly answer on the lab's address.
- **separate secrets** — a different Postgres password and JWT secret. A shared
  JWT secret would make a dev session valid against production.

Job capacity on dev is deliberately small (`N_CORES=2`, two concurrent jobs).
Not for dev's sake: `JobManager` gates on **host-wide** headroom, so a big dev
run does not "steal" production's cores, it makes production's admission gate
stop admitting — and production's jobs then sit at `pending` with a message
about idle cores that says nothing about a dev stack being the cause.

Keep dev on the **same LLM model as production** unless changing the model is
the point. Both stacks share one host-wide Ollama; the same model costs nothing
extra, a different one loads a second multi-tens-of-GB resident copy that other
tenants of the machine pay for.

## Production

### What production is

A checkout that is never edited by hand and never on a branch. It sits on a
**detached HEAD** at the deployed commit, so `git status` there is a truthful
answer to "what is the lab running". It has its own `.env`, its own certs, and
`.deployment-role` containing the word `production` — which is what stops
`dev_stack.sh reset` from ever running against it.

### Promoting

From the production checkout:

```bash
scripts/promote.sh                # to origin/main
scripts/promote.sh <ref>          # to a specific commit or tag
scripts/promote.sh --dry-run      # run every gate, change nothing
```

In order, it: refuses unless this is a clean production checkout; fetches;
**refuses any commit with no passing row in
[deployment-ledger.md](deployment-ledger.md)**; reports what the change will do
to the running deployment; takes a backup; optionally drains jobs; checks out
the commit; rebuilds the frontend and the image; waits for health; records what
it did.

A commit whose only difference from a verified one is documentation is allowed
through — the commit that records a verification cannot contain the row
recording it. Anything touching code is not.

Production deploys **dev-verified commits, not release tags.** Publishing to the
public remote and updating the lab's deployment are unrelated acts on unrelated
schedules; coupling them would mean either releasing publicly every time the lab
needs a fix, or making the lab wait for a release.

### Destructive updates

`scripts/promote.sh` runs `scripts/check_destructive.sh` first and will not go
past a destructive finding without a typed confirmation. Run it yourself any
time:

```bash
scripts/check_destructive.sh --from <deployed> --to <candidate>
```

What it treats as **destructive**, and why each is worth a gate — all four
either fail silently or destroy something unrecoverable:

- **In-flight jobs die.** Workers are `subprocess.Popen` children inside the api
  container's PID namespace; `start_new_session=True` gives them their own
  process group, which is about signal delivery, not immunity from container
  teardown. Recreating the container kills them, and there is no resume. A
  CASSCF or CASPT2 run here is routinely tens of minutes to hours of compute
  somebody is waiting on.
- **A new column with no `ALTER TABLE`.** The schema is `CREATE TABLE IF NOT
  EXISTS` plus hand-written `ALTER TABLE ... ADD COLUMN IF NOT EXISTS`. Editing
  a `CREATE TABLE` body works on a fresh database and is a **silent no-op**
  against the deployed one. The check compares both commits' parsed DDL, and
  compares the new code's expectations against what `information_schema`
  actually holds — which also catches drift introduced several promotions ago.
- **A new required `${VAR:?}`** in the compose file, absent from production's
  `.env`. Compose aborts `up` *after* removing the old containers.
- **Bind mounts no file would recreate.** `docker-compose.override.yml` is
  untracked and is the only thing mounting the licensed engines. A container
  keeps the mounts it was created with, so that file can disappear while the
  deployment runs on perfectly — and the loss only surfaces at the next
  recreate, as a stack that is silently PySCF-only. This has happened here.

Warnings, which inform but do not block: an image rebuild (a longer outage), a
frontend change (open tabs keep the old bundle until reloaded), nginx changes
(reachability), on-disk layout changes under `data/` (which has no migration
mechanism at all), file deletions, and changes to the backup tooling itself.

### Draining, or not

If jobs are in flight, promotion refuses until you choose:

```bash
scripts/promote.sh --drain    # stop admitting new jobs, wait, then promote
scripts/promote.sh --force    # promote now, accept losing them
```

There is deliberately **no default.** One waits for users' calculations, the
other throws them away, and guessing on somebody's multi-hour CASPT2 run is not
a decision a script should make. `--drain` stops admission *first* (by setting
the admin cap to zero) and then waits — waiting without stopping admission is a
race that a busy deployment can lose indefinitely, because every job that
finishes frees a slot for the next queued one. Admission is restored on every
exit path, including Ctrl-C.

### Rolling back

```bash
scripts/promote.sh --rollback
```

Returns the checkout to the previously deployed commit, from `.promotion-log`.

**It rolls back code, not the database.** The schema ALTERs are forward-only and
idempotent, so re-checking-out the old commit leaves every added column in
place. The pre-promotion backup is the only way to undo a schema change — and
restoring it also rewinds every account, session and conversation created since,
which is almost never what you want. Killed jobs do not come back at all.

## Rules for Claude Code sessions

These are enforced, not advisory. They exist because the failure modes they
prevent have all actually happened in this repository.

1. **Start on a new branch** (or an isolated worktree). Never commit onto `main`
   directly.
2. **Merge into `main` before pushing**, fast-forward only. Never leave the
   deliverable on a session or worktree branch.
3. **"Push" means `git push origin main`** — the private remote. Never push to
   `public` by any route other than `scripts/release.sh`.
4. **Before a push to release, report every unmerged branch** with how far ahead
   each is, so nothing meant for the release is silently left out.
5. **Never promote to production what the dev stack has not verified.** If
   production is broken and a fix cannot wait for a full suite run, say so out
   loud and record a short verification — do not bypass the gate quietly.
6. **Warn before anything destructive**, in advance and specifically: which jobs
   die, which columns will not appear, what a rollback cannot undo.
7. **Never write host-specific values into a tracked file.** They belong in
   `.env`, `docker-compose.override.yml` or `CLAUDE.local.md`.
8. **Update the docs in the same change**, not afterwards — `README.md` and
   whichever of these documents the change affects.
9. **Long job runtimes are the design premise, not a defect.** Never write a
   multi-hour CASSCF or CASPT2 run up as a performance problem or steer a user
   away from it. The only genuine defects here are ones that break the
   leave-and-return workflow.

## Quick reference

```bash
# start work
git checkout main && git pull origin main && git checkout -b my-change

# test it
scripts/dev_stack.sh up
scripts/dev_stack.sh verify              # records the commit as promotable

# integrate and push (private)
git checkout main && git merge --ff-only my-change && git push origin main

# ship it to the lab (from the production checkout)
scripts/promote.sh --dry-run
scripts/promote.sh --drain

# publish (rare, deliberate)
scripts/release.sh 1.1.0 --dry-run
scripts/release.sh 1.1.0
```
