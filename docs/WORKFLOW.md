# Workflow

**This is the primary guide to managing this project.** Branching, merging,
pushing, releasing, testing, deploying, it's all here, and none of it is a
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

## The shape of it

One repository. One linear history on `main`. Two remotes:

```
         commit on main
               |
               v
   +-----------------------+        git push origin main
   |  main (linear)         | ------------------------------> origin
   +-----------------------+                              NexusQC-dev (private)
               |
               |  scripts/release.sh <version>
               +---------------------------------------> public
                                                       NexusQC (public)
```

Every actual deployment, yours, a lab's, anyone's. Is its own independent
checkout, stood up with `scripts/install.sh` and kept current with
`scripts/update.sh`. Neither script cares which remote it came from beyond
"whatever `origin` is in this clone"; there is no separate dev/production
apparatus in this repository for one to be verified against before the other
moves. See [DEPLOYMENT.md](DEPLOYMENT.md) for the full install/update/backup
story.

**Everything tracked in git is publishable.** Host-specific values live in
untracked files, `.env`, `docker-compose.override.yml`, `nginx/certs/`,
`CLAUDE.local.md`, never in a tracked one. That's what removes the need for
a sanitised parallel branch; see [DEVELOPMENT.md](DEVELOPMENT.md) for why.

## Making a change

### One active tracker at a time

Anything bigger than a small fix gets a tracker, and there is never more than
one open. `docs/TRACKER.md` is whichever plan is currently in motion. When that
plan finishes, the file is closed out and moved into `docs/trackers/`, and a
fresh `docs/TRACKER.md` starts for the next feature or request. Development
here is linear, so a second concurrent tracker would only ever describe work
nobody is doing.

Closing one out means every step is `done` with an evidence line, every phase
carries the commit hash it landed as, and `scripts/check_tracker.py` passes.
Then:

```bash
git mv docs/TRACKER.md docs/trackers/<yyyy-mm>-<short-name>.md
```

Archived trackers are never deleted. They are the record of why the code looks
the way it does, and comments throughout the codebase cite them by path, so a
move has to bring those references with it. Only the active tracker is
machine-checked; an archived one describes what was true when it closed, and
the scripts its evidence names may since have been deleted on purpose.

A step is `done` only when its evidence exists and its observed result is
written down. "It should work" is not evidence, and neither is a test that was
never run.

### Work on `main`

Every session works directly on `main`. The branch-per-session rule was
retired on 2026-08-19. Development here is serial, there's nothing to
isolate from, and the branch was costing more than it bought. Every push
went to two refs, and worktree isolation kept blocking operations a phase
actually needed.

```bash
git pull --ff-only origin main
```

Branches and worktrees are the exception now, reached for only when
someone explicitly asks. Genuinely parallel work, or an experiment worth
being able to throw away wholesale.

**The gate moved from the merge to the commit.** With no branch left to
park work on, commit only what you'd be willing to deploy. Run the backend
suite first. Keep each commit to one coherent change. Use `git revert` as
the undo, not an abandoned branch.

**Check for unpushed work when a session starts.** Compare `HEAD` against
`origin/main`, look for uncommitted changes, and say so plainly if either
is dirty. Without a branch, a local-only commit is invisible until
something trips over it.

A background agent session may still get forced into a worktree by its own
harness. That isolation belongs to the harness, not to this project. The
work still belongs on `main`, and the session should push it there instead
of leaving it parked on a `worktree-*` branch.

Some harnesses forbid that outright: they require the worktree before they
will accept a single file edit, and they refuse any merge or push to
`main`. A session in that position cannot land its own work however much it
would like to, and the failure mode is that the branch is simply forgotten,
because the next session inherits the repository and not the conversation
that explains it. So such a session finishes by writing the exact commands
into [`docs/HANDOFF.md`](HANDOFF.md), and whoever picks it up runs them and
clears the file. See "Handing off what you cannot do yourself" below.

The history stays linear either way. Nothing here creates a merge commit.

### Handing off what you cannot do yourself

`docs/HANDOFF.md` holds steps a session finished but could not perform: a
merge it lacked permission for, a rebuild only a person can run, a manual
verification. It exists because a session inherits the repository and never
the previous conversation, so an outstanding step that is not written down
is lost, and `CLAUDE.md` tells every session to read the file at start.

Three rules keep it useful:

- **Read it first.** If its "Open" section is empty, move on. If it lists
  something, do that before starting new work.
- **Clear it when it is done.** Delete the entry and commit that. An entry
  still standing has to mean something is genuinely pending or the file
  stops being trusted, which is the only way this fails.
- **Keep it to blocked actions.** Remaining development work goes in
  `docs/TRACKER.md`, and unimplemented bugs and ideas go in
  `docs/BACKLOG.md`. This file is not a second to-do list.

### Push

"Push" means the **private** remote, and only ever `main`:

```bash
git push origin main
```

This push isn't scanned. `origin` is private and stays private, so running
the public-safety scan on the way there would just be guarding against a
disclosure that can't happen, on every single push. Publication is gated
separately, `scripts/release.sh` runs `scripts/check_public_safe.sh`
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

Before publishing, it reports every branch not merged into `main`, local
and remote, how far ahead each is, when it was last touched, and asks for
a typed confirmation before continuing without them. A public push can't
be amended afterward, so finding out about stranded work belongs before
the push, not in a postmortem.

## Testing

| Change | Test it with |
|---|---|
| chemistry, agent, tools | run the thing directly. See [TESTING.md](TESTING.md); there is no pytest suite for this |
| frontend | a real browser via Playwright, not a code read |
| auth, admin, ownership, quotas | the standing suite (`tests/run_backend.sh`), against a real running deployment |

`python -m server.main` plus `npm run dev` is still the fastest loop for
most work, and nothing replaces it for day-to-day iteration. But the auth
layer is inert without `QC_AGENT_DATABASE_URL`, and a real class of bugs
here only shows up in the containerised, nginx-fronted deployment
(`docker compose up -d`).

There is no separate, tooling-enforced "dev stack" to verify a change on
before it reaches a real deployment. That apparatus (`scripts/dev_stack.sh`,
a second checkout, a verification ledger gating promotion) was retired on
2026-08-21 once `scripts/install.sh`/`scripts/update.sh` existed as the
standard way to stand up and advance a deployment; see
[DEPLOYMENT.md](DEPLOYMENT.md#backup-restore-and-updating). If you want to
rehearse a change before running `scripts/update.sh` against a deployment
that matters, that's a plain manual choice now, not enforced tooling: clone
the repo somewhere disposable and run `scripts/install.sh` there, exactly
like standing up any other deployment. `scripts/update.sh --dry-run` against
your real deployment is the built-in safety net either way. It reports what
a pending update would do (schema changes, new required config, in-flight
jobs) before anything is touched.

## Updating a deployment

```bash
scripts/update.sh                # fetch and update to origin/main
scripts/update.sh --dry-run      # report the impact, change nothing
scripts/update.sh --drain        # wait for in-flight jobs, then update
scripts/update.sh --force        # update now, accept losing them
scripts/update.sh --rollback     # back to the commit before the last update
```

Run from inside the deployment's own checkout. In order: refuses on a dirty
tree; fetches `origin`; runs `scripts/check_destructive.sh` and refuses past
a destructive finding without a typed confirmation; if jobs are in flight and
the update would restart the containers, refuses until you pick `--drain` or
`--force`; takes a full backup (`scripts/backup.sh --full`) unconditionally;
checks out the target commit; rebuilds the frontend and the image; waits for
health; records what it did in `.update-log`.

What counts as destructive, and why each earns a gate. All four either fail
silently or destroy something you can't get back:

- **In-flight jobs die.** Workers are `subprocess.Popen` children inside the
  api container's PID namespace; recreating the container kills them with no
  resume. A CASSCF or CASPT2 run here is routinely tens of minutes to hours
  of compute someone is actually waiting on.
- **A new column with no `ALTER TABLE`.** The schema is `CREATE TABLE IF NOT
  EXISTS` plus hand-written `ALTER TABLE ... ADD COLUMN IF NOT EXISTS`.
  Editing a `CREATE TABLE` body works on a fresh database and is a silent
  no-op against a deployed one.
- **A new required `${VAR:?}`** in the compose file, absent from the
  deployment's `.env`. Compose aborts `up` *after* removing the old
  containers.
- **Bind mounts nothing would recreate.** `docker-compose.override.yml` is
  untracked and is the only thing mounting the licensed engines. A container
  keeps whatever mounts it was created with, so that file can quietly
  disappear while the deployment keeps running, and the loss only surfaces
  at the next recreate, as a stack that's silently PySCF-only.

Rollback undoes the code, not the database: schema changes are forward-only
and idempotent, so a rolled-back checkout just leaves added columns sitting
there unused. The pre-update backup is the only real way to undo a schema
change, and restoring it also rewinds every account, session and
conversation created since. Killed jobs don't come back at all, backup or
not.

## Rules for Claude Code sessions

These are enforced, not advisory. Each one exists because the failure mode
it prevents has already happened in this repository, not hypothetically.

1. **Work on `main`.** No per-session branch, no worktree, unless one was
   explicitly asked for. Development is serial.
2. **Commit only what you'd deploy**, and check for unpushed work at the
   start of a session.
3. **"Push" means `git push origin main`**, the private remote. Never
   push to `public` by any route other than `scripts/release.sh`.
4. **Before a push to release, report every unmerged branch**, with how
   far ahead each is, so nothing meant for the release gets silently left
   out.
5. **Warn before anything destructive**, in advance and specifically:
   which jobs die, which columns won't appear, what a rollback can't undo.
6. **Never write host-specific values into a tracked file.** They belong
   in `.env`, `docker-compose.override.yml` or `CLAUDE.local.md`.
7. **Update the docs in the same change**, not afterward. `README.md`
   and whichever of these documents the change touches.
8. **Long job runtimes are the design premise, not a defect.** Don't write
   a multi-hour CASSCF or CASPT2 run up as a performance problem, and
   don't steer a user away from one. The only genuine defects here are
   ones that break the leave-and-return workflow.

## Quick reference

```bash
# start work
cat docs/HANDOFF.md          # anything a previous session left for a person
git pull --ff-only origin main

# push (private)
git push origin main

# ship a deployment forward
scripts/update.sh --dry-run
scripts/update.sh

# publish (rare, deliberate)
scripts/release.sh 1.1.0 --dry-run
scripts/release.sh 1.1.0
```
