# Workflow

**This is the primary guide to managing this project.** Branching, merging,
pushing, releasing, testing, deploying — it's all here, and none of it is a
suggestion. Most of it is enforced by tooling rather than left to memory,
because memory is exactly what fails at 2am when a deploy needs to go out.

The related documents, and what each one answers:

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
         commit on main
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

Two rules carry the whole thing, and both are load-bearing.

**Everything tracked in git is publishable.** Host-specific values live in
untracked files — `.env`, `docker-compose.override.yml`, `nginx/certs/`,
`CLAUDE.local.md`, `.deployment-role` — never in a tracked one. That's what
removes the need for a sanitised parallel branch; see
[DEVELOPMENT.md](DEVELOPMENT.md) for why.

**Nothing reaches production that the dev stack hasn't verified.** Not a
habit. `scripts/promote.sh` actually refuses.

## Making a change

### Work on `main`

Every session works directly on `main`. The branch-per-session rule was
retired on 2026-08-19, for the rest of the overhaul and everything after
it. Development here is serial — there's nothing to isolate from — and the
branch was costing more than it bought. Every push went to two refs, and
worktree isolation kept blocking the dev-stack operations a phase actually
needed.

```bash
git pull --ff-only origin main
```

Branches and worktrees are the exception now, reached for only when
someone explicitly asks — genuinely parallel work, or an experiment worth
being able to throw away wholesale.

**The gate moved from the merge to the commit.** With no branch left to
park work on, commit only what you'd be willing to deploy: the dev stack
tracks `main`, so a broken push is a broken dev stack. Run the backend
suite first. Keep each commit to one coherent change. Use `git revert` as
the undo, not an abandoned branch.

**Check for unpushed work when a session starts.** Compare `HEAD` against
`origin/main`, look for uncommitted changes, and say so plainly if either
is dirty. Without a branch, a local-only commit is invisible until
something trips over it — and since the dev stack deploys from `main`, an
unpushed commit means the running stack and the repository quietly
disagree with each other.

A background agent session may still get forced into a worktree by its own
harness. That isolation belongs to the harness, not to this project — the
work still belongs on `main`, and the session should push it there instead
of leaving it parked on a `worktree-*` branch.

The history stays linear either way. Nothing here creates a merge commit.

### Push

"Push" means the **private** remote, and only ever `main`:

```bash
git push origin main
```

This push isn't scanned. `origin` is private and stays private, so running
the public-safety scan on the way there would just be guarding against a
disclosure that can't happen, on every single push. Publication is gated
separately — `scripts/release.sh` runs `scripts/check_public_safe.sh`
itself before it touches the public remote, so the guarantee doesn't
depend on anyone remembering to install a hook.

Installing the hook is still worth doing, though: it scans any remote it
doesn't recognise as private, over both the working tree and the commits
being pushed. Once per clone, since git doesn't track `.git/hooks` and a
fresh clone starts with none:

```bash
scripts/hooks/install.sh
```

Keeping a second private mirror? Name it in `QC_AGENT_PRIVATE_REMOTES`
(space-separated) so it's exempt too.

### Push to release

Publishing to the **public** remote is a separate, deliberate act:

```bash
scripts/release.sh <version>              # e.g. 1.1.0
scripts/release.sh <version> --dry-run    # run every gate, push nothing
```

It reads more like a sequence of refusals than a warning: on `main`, clean
tree, both remotes configured, safety scan passes, `main` matches
`origin/main`, the tag is free, `CHANGELOG.md` documents the version, and
the public remote can move forward without discarding published history.

Before publishing, it reports every branch not merged into `main` — local
and remote, how far ahead each is, when it was last touched — and asks for
a typed confirmation before continuing without them. A public push can't
be amended afterward, so finding out about stranded work belongs before
the push, not in a postmortem.

## Testing

### Where a change gets tested

| Change | Test it with |
|---|---|
| chemistry, agent, tools | run the thing directly — see [TESTING.md](TESTING.md); there is no pytest suite for this |
| frontend | a real browser via Playwright, not a code read |
| auth, admin, ownership, quotas | the standing suite, against the **dev stack** |
| anything going to production | the **dev stack**, then `dev_stack.sh verify` |

`python -m server.main` plus `npm run dev` is still the fastest loop for
most work, and nothing replaces it for day-to-day iteration. But the auth
layer is inert without `QC_AGENT_DATABASE_URL`, and a real class of bugs
here only shows up in the containerised, nginx-fronted deployment. Those
need the dev stack.

### The development stack

A second checkout, running the same compose file with
`docker-compose.dev.yml` layered on top. It's destructible on purpose.

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

To move the dev stack onto the current `main`, use the wrapper rather than
doing the steps by hand:

```bash
scripts/sync_dev_stack.sh        # fetch + fast-forward, rebuild dist, rebuild + restart
scripts/sync_dev_stack.sh --no-pull   # already on the commit; just redeploy it
```

The wrapper exists because doing it by hand has three separate traps, and
all three got hit in a single evening once. `git pull` with no upstream
configured on `main` reports "Already up to date" and fetches nothing —
the branch sat two phases behind while two separate pull attempts looked
like they'd worked. `dev_stack.sh frontend` needs npm, which isn't on
`PATH` until the host's node environment is activated (named in
`CLAUDE.local.md`). And `frontend/dist` is served from a host bind mount,
so rebuilding the image without rebuilding dist leaves the browser on the
old UI while the API serves the new one, which looks exactly like a
frontend bug and isn't one. The wrapper fetches explicitly, refuses a
non-fast-forward, activates the node environment when it can, and always
rebuilds dist before the image.

`reset` is a normal thing to run, not an emergency. Nothing in the dev
stack is backed up, and nothing depends on it surviving.

It deliberately keeps `data/kb`, `data/scraped`, `data/molecules` and
`data/bse_basis_cache`. Those are seeded content, not test residue — the
vector store is slow to rebuild from the scraped corpus, and a
destructible stack you end up avoiding destroying, because resetting it
costs an hour of reseeding, is just production with fewer users.
`reset --all` wipes them too, for when the knowledge base itself is what
changed.

Four things keep it away from production. Sharing one host means the
separation has to be deliberate at every layer, so there isn't one single
thing doing all the work here:

- **separate directory** — `./data` and `./frontend/dist` are relative
  bind mounts, so two stacks in one directory would share the users' job
  store.
- **separate compose project** (`COMPOSE_PROJECT_NAME`), so the Postgres
  and Redis volumes can't end up being the same bytes.
- **no LAN bind.** The dev stack publishes on loopback and the tailnet
  only, never the address lab users reach. `docker-compose.dev.yml` uses
  `!override` to *replace* the port list rather than append to it, because
  compose's default append behavior would have dev quietly answering on
  the lab's address too.
- **separate secrets** — a different Postgres password and JWT secret. A
  shared JWT secret would make a dev session valid against production.

Job capacity on dev is deliberately small (`N_CORES=2`, two concurrent
jobs), and not for dev's own sake. `JobManager` gates on host-wide
headroom, so a big dev run doesn't "steal" production's cores so much as
make production's admission gate stop admitting — and production's jobs
then sit at `pending` with a message about idle cores that says nothing
about a dev stack being the actual cause.

Keep dev on the same LLM model as production unless changing the model is
the point of the work. Both stacks share one host-wide Ollama; the same
model costs nothing extra to keep loaded, while a different one loads a
second multi-tens-of-GB resident copy that every other tenant of the
machine ends up paying for.

## Production

### What production is

A checkout that's never edited by hand and never on a branch. It sits on a
detached HEAD at the deployed commit, so `git status` there gives a
truthful answer to "what is the lab running." It has its own `.env`, its
own certs, and a `.deployment-role` file holding the single word
`production` — which is what stops `dev_stack.sh reset` from ever running
against it by mistake.

### Promoting

From the production checkout:

```bash
scripts/promote.sh                # to origin/main
scripts/promote.sh <ref>          # to a specific commit or tag
scripts/promote.sh --dry-run      # run every gate, change nothing
```

In order, it refuses unless this is a clean production checkout; fetches;
refuses any commit with no passing row in
[deployment-ledger.md](deployment-ledger.md); reports what the change will
do to the running deployment; takes a backup; optionally drains jobs;
checks out the commit; rebuilds the frontend and the image; waits for
health; records what it did.

A commit whose only difference from a verified one is documentation is
let through — the commit that records a verification can't very well
contain the row recording itself. Anything touching code doesn't get that
exception.

A documentation-only promotion doesn't restart anything. It moves the
checkout and stops there, leaving the containers running. Recreating them
is the destructive part of a promotion (it kills in-flight jobs), and
doing that just to ship a CHANGELOG entry would mean the tooling
committing the exact harm it exists to warn about. So jobs in flight are
reported as safe rather than treated as a blocker, and no drain runs. The
check itself is an allow-list of paths that can't affect a running stack —
a new top-level directory is treated as needing a restart rather than
silently assumed harmless, which is the safer direction to be wrong in.

Production deploys dev-verified commits, not release tags. Publishing to
the public remote and updating the lab's deployment are unrelated acts on
unrelated schedules. Coupling them would mean either releasing publicly
every time the lab needs a fix, or making the lab wait on a release.

### Destructive updates

`scripts/promote.sh` runs `scripts/check_destructive.sh` first and won't
go past a destructive finding without a typed confirmation. You can run it
yourself any time:

```bash
scripts/check_destructive.sh --from <deployed> --to <candidate>
```

What counts as destructive here, and why each one earns a gate — all four
either fail silently or destroy something you can't get back:

- **In-flight jobs die.** Workers are `subprocess.Popen` children inside
  the api container's PID namespace. `start_new_session=True` gives them
  their own process group, which is about how signals get delivered, not
  immunity from container teardown. Recreating the container kills them
  and there's no resume. A CASSCF or CASPT2 run here is routinely tens of
  minutes to hours of compute someone is actually waiting on.
- **A new column with no `ALTER TABLE`.** The schema is `CREATE TABLE IF
  NOT EXISTS` plus hand-written `ALTER TABLE ... ADD COLUMN IF NOT
  EXISTS`. Editing a `CREATE TABLE` body works fine on a fresh database
  and is a silent no-op against the deployed one. The check compares both
  commits' parsed DDL against what `information_schema` actually holds,
  which also catches drift that snuck in several promotions ago.
- **A new required `${VAR:?}`** in the compose file that's absent from
  production's `.env`. Compose aborts `up` *after* it's already removed
  the old containers — so you find out the hard way.
- **Bind mounts nothing would recreate.** `docker-compose.override.yml` is
  untracked and is the only thing mounting the licensed engines. A
  container keeps whatever mounts it was created with, so that file can
  quietly disappear while the deployment keeps running fine, and the loss
  only surfaces at the next recreate — as a stack that's silently
  PySCF-only. This has actually happened here.

Warnings inform but don't block: an image rebuild (a longer outage), a
frontend change (open tabs keep the old bundle until reloaded), nginx
changes (reachability), on-disk layout changes under `data/` (which has no
migration mechanism at all), file deletions, and changes to the backup
tooling itself.

### Draining, or not

If jobs are in flight, promotion refuses until you choose:

```bash
scripts/promote.sh --drain    # stop admitting new jobs, wait, then promote
scripts/promote.sh --force    # promote now, accept losing them
```

There's deliberately no default here. One option waits for users'
calculations to finish; the other throws them away. Guessing on somebody's
multi-hour CASPT2 run isn't a decision a script should get to make on its
own. `--drain` stops admission first, by setting the admin cap to zero,
and only then waits — waiting without stopping admission first is a race a
busy deployment can lose indefinitely, since every job that finishes just
frees a slot for the next one in the queue. Admission is restored on every
exit path, Ctrl-C included.

### Rolling back

```bash
scripts/promote.sh --rollback
```

Returns the checkout to the previously deployed commit, read from
`.promotion-log`.

It rolls back code, not the database. The schema ALTERs are forward-only
and idempotent, so re-checking-out the old commit just leaves every added
column sitting there unused. The pre-promotion backup is the only real way
to undo a schema change, and restoring it also rewinds every account,
session and conversation created since — which is almost never actually
what you want. Killed jobs don't come back at all, backup or not.

## Rules for Claude Code sessions

These are enforced, not advisory. Each one exists because the failure mode
it prevents has already happened in this repository, not hypothetically.

1. **Work on `main`.** No per-session branch, no worktree, unless one was
   explicitly asked for. Development is serial.
2. **Commit only what you'd deploy**, and check for unpushed work at the
   start of a session. The dev stack tracks `main`, so an unpushed commit
   means the running stack and the repository disagree without saying so.
3. **"Push" means `git push origin main`** — the private remote. Never
   push to `public` by any route other than `scripts/release.sh`.
4. **Before a push to release, report every unmerged branch**, with how
   far ahead each is, so nothing meant for the release gets silently left
   out.
5. **Never promote to production what the dev stack hasn't verified.** If
   production is broken and a fix can't wait for a full suite run, say so
   out loud and record a short verification instead of bypassing the gate
   quietly.
6. **Warn before anything destructive**, in advance and specifically:
   which jobs die, which columns won't appear, what a rollback can't undo.
7. **Never write host-specific values into a tracked file.** They belong
   in `.env`, `docker-compose.override.yml` or `CLAUDE.local.md`.
8. **Update the docs in the same change**, not afterward — `README.md`
   and whichever of these documents the change touches.
9. **Long job runtimes are the design premise, not a defect.** Don't write
   a multi-hour CASSCF or CASPT2 run up as a performance problem, and
   don't steer a user away from one. The only genuine defects here are
   ones that break the leave-and-return workflow.

## Quick reference

```bash
# start work
git pull --ff-only origin main

# test it
scripts/dev_stack.sh up
scripts/dev_stack.sh verify              # records the commit as promotable

# push (private)
git push origin main

# ship it to the lab (from the production checkout)
scripts/promote.sh --dry-run
scripts/promote.sh --drain

# publish (rare, deliberate)
scripts/release.sh 1.1.0 --dry-run
scripts/release.sh 1.1.0
```
