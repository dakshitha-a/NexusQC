# Development workflow

> **[WORKFLOW.md](WORKFLOW.md) is the primary guide** and holds the actual
> procedure, branching, merging, pushing, releasing, testing, promoting to
> a deployment. This document is the rationale for the two-remote
> arrangement specifically: why it's safe to keep one history and publish
> from it, and what would break that. Read WORKFLOW.md to find out what to
> run; read this one to find out why it's shaped this way.

One repository, one branch, one history, two remotes. Development happens
continuously against a private remote; publishing to the public remote is
a separate, deliberate act, not something that falls out of ordinary work.

| Remote | Repository | Visibility | When it is pushed |
|---|---|---|---|
| `origin` | `NexusQC-dev` | private | continuously, as ordinary work |
| `public` | `NexusQC` | public | only by `scripts/release.sh` |

```bash
git push origin main            # ordinary work
scripts/release.sh 1.1.0        # publish a release
```

## The invariant that makes this cheap

Everything tracked in git is publishable. No sanitised branch, no export
filter, no parallel tree, because nothing host-specific gets committed in
the first place.

That invariant is what removes the per-change cost, and it's worth
understanding why it holds, since the cost comes straight back the moment
it's broken:

- Host-specific configuration reaches the app through the environment,
  never through a committed default. `app/config.py` carries generic
  defaults; `.env` overrides them. See
  [CONFIGURATION.md](CONFIGURATION.md).
- Anything genuinely host-specific is untracked and gitignored: `.env`,
  `docker-compose.override.yml`, `nginx/certs/*`, and `CLAUDE.local.md`
  for "true of this particular machine" notes. Each has a committed
  `*.example` counterpart where one earns its keep.
- `scripts/check_public_safe.sh` enforces the invariant mechanically on
  the way to the public remote. `scripts/release.sh` runs it before
  publishing anything, and the pre-push hook runs it for any remote that
  isn't known-private. Pushes to `origin` are exempt, since it's private
  and there's nothing there to disclose.

So the rule for new work is simple: if a value is true of *your machine*
rather than of the project, it belongs in `.env` or `CLAUDE.local.md`, not
in a tracked file.

## Running from source

Deployments run the Docker stack ([DEPLOYMENT.md](DEPLOYMENT.md)), but two
bare processes are the fastest loop for day-to-day work. Vite proxies
`/api/*` to port 8000, so there's no CORS setup.

```bash
# one-time
conda create -n qc-agent python=3.11 -y && conda activate qc-agent
pip install -r requirements.txt
conda create -n node24 -c conda-forge nodejs=24 -y   # system Node is usually too old
conda activate node24 && cd frontend && npm install && cd ..

# terminal 1 -- backend, binds to localhost only
conda activate qc-agent
PYTHONPATH=$PWD python3 -m server.main

# terminal 2 -- frontend
conda activate node24
cd frontend && npm run dev
```

You should see `Uvicorn running on http://127.0.0.1:8000` in the first
terminal and a `Local: http://localhost:5173/` URL in the second. Confirm the
backend independently with `curl http://127.0.0.1:8000/api/health`.

Seeding the knowledge base is optional but worth it. It gives the agent the
ORCA and BAGEL manuals plus a PySCF reference, so it gets keyword syntax right
from the start:

```bash
PYTHONPATH=$PWD python3 scripts/seed_knowledge_base.py
```

That takes a few minutes and is safe to re-run. It crawls the ORCA and BAGEL
manuals, both of which permit it, and generates the PySCF docs from your
*installed* package rather than scraping pyscf.org, whose `robots.txt`
disallows AI crawlers.

**This mode has no auth layer.** `QC_AGENT_DATABASE_URL` is the single switch
that activates accounts, ownership and the admin console; without it those
routes aren't even mounted and the checkpointer stays on SQLite. So anything
touching auth, quotas or ownership has to be tested against the full compose
stack instead. See [TESTING.md](TESTING.md).

## Required once per clone

```bash
scripts/hooks/install.sh
```

Git doesn't track `.git/hooks`, so a fresh clone has no protection until
this runs. It installs a pre-push hook that runs the public-safety scan
and refuses the push on a finding.

## What the safety scan covers

`scripts/check_public_safe.sh` blocks home- or user-scoped absolute paths
(`/home/<user>`, `/data/<user>`, `/root`, `/Users/<name>`), site-specific
install trees, private key material, hardcoded credentials, bare
institutional hostnames, files that must never be tracked (`.env`,
`*.key`, `CLAUDE.local.md`, ...), and machine-generated test output. It
warns on routable IP literals too. In range mode it also reads each
commit's author and committer email and fails on an institutional host
there, which no file scan can see: 319 commits reached the private remote
under `<user>@<machine>.<institution>.edu` before the first release found
them.

`/data/<name>` has a closed safe-list of this app's own data
subdirectories (`/data/jobs`, `/data/uploads`, `/data/backups`, ...),
which tests and audit notes write as container-side absolute paths. Those
name directories the project creates, not a user; anything else under
`/data/` still fails. A category with more hits than it shows says so
(`showing 25 of 40`), so a scan that finds forty is never mistaken for one
that found twenty-five.

It does not flag the author's name. The name is already in the repository
URL, in every commit's authorship, and in the README. Publication
doesn't need to hide it, and flagging it just produced findings that got
waved through every time, which is how a scan trains people to stop
reading it. What must not be published is a path that describes a
particular machine, and that's what the path patterns actually target. A
fork that needs to catch its own site-specific words (an internal group
name, a cluster hostname) can set `NEXUSQC_SCAN_EXTRA_TERMS` to a
`|`-separated list; it's empty by default.

Three modes:

```bash
scripts/check_public_safe.sh                  # all tracked files
scripts/check_public_safe.sh --staged         # staged changes only
scripts/check_public_safe.sh --range A..B     # the commits in a range
```

Range mode exists because a working-tree scan alone has a hole: content
committed and then removed in a later commit passes the scan clean while
the leak sits permanently in history. The pre-push hook uses both modes
together.

Two things the scan genuinely cannot do. It can't read images, so any new
screenshot needs a human look before it's committed. A screenshot of the
app can show a username, an email, or unpublished chemistry that no text
pattern will ever catch. And it only sees what's tracked; it has nothing
to say about what you happen to have running.

### If the scan flags something

Fix the content. If it's genuinely a false positive, narrow the pattern in
the script itself rather than adding an exception or reaching for
`--no-verify`. One pattern in that file is deliberately written as a
character class (`/[s]oftware/`), specifically so a find-and-replace over
this repository's own history can't rewrite the detector along with
everything else. That's not a typo, and the same care applies to any
pattern naming a real path or host.

## Publishing

`scripts/release.sh <version>` refuses to run unless you're on `main`, the
tree is clean, the safety scan passes on the tree, `main` matches
`origin/main`, the tag doesn't already exist, `CHANGELOG.md` has a section
for the version, the public remote can be advanced, and the safety scan
passes on every commit about to be published (about a minute for a first
release). Then it asks for one typed confirmation, updates `CITATION.cff`,
commits, tags, and pushes: public first, private second. The order is
about recoverability. A public push that fails leaves only local state,
undone with the two commands the script prints; a private push that fails
after a successful publication is repaired by re-running one push. The
other order left a tag on the private remote that could never be re-cut.

```bash
scripts/release.sh 1.1.0 --dry-run   # run every gate, push nothing
scripts/release.sh 1.1.0
```

Because history gets published, the asymmetry is worth keeping in mind: a
private push is reversible, and a public one really isn't.

## Why the public repository has to stay a separate repository

`NexusQC-dev` and `NexusQC` are two repositories, not one repository with
a visibility switch, and that split isn't an accident of how this got
set up. Never publish by flipping `NexusQC-dev` to public in GitHub's
settings.

The private repository predates a one-time history rewrite, so it once
held commits with this host's real paths, hostname, and addresses.
Force-pushing the rewritten history replaced what `main` points at, but a
merged pull request leaves behind a server-side `refs/pull/<n>/head` ref
that no push can remove, and that keeps the original commits alive.
They're unreachable from any branch, invisible in normal use, and still
fetchable by SHA anyway. Nothing secret ever lived in them, no key or
credential was ever committed, but the pre-rewrite host details did.

So publication has to be a fresh push into a repository that's never had a
pull request, which is exactly what the `public` remote is. A visibility
toggle on the development repository would drag the pre-rewrite refs out
along with everything else.

It happened twice. The first release attempt, on 2026-09-14, found the
same class of content back in history: the checkout's path, the deployment's
path, the lab's software tree, the hostname and the tailnet address, in
about 4,580 blobs across 575 commits, none of them in code. They came in
through trackers, handoff notes and the evaluation's audit notes, which are
exactly the documents where someone writes down what they ran, and through
commit metadata, which no scan had ever read. The remedy was the same
rewrite (`git filter-repo --replace-text` plus a `--mailmap` for the
emails), rehearsed in a scratch clone until the tree scan, the range scan
over all of history and a raw grep were all clean, then applied and
force-pushed to the private remote. Two consequences of that are visible
today. The archived trackers' `merged:` rows were remapped to the new
hashes in one commit after the rewrite, so the tip is right while
historical versions of those files still cite pre-rewrite hashes. And the
evaluation's files read `/data/qcuser/...` in their historical versions,
which is the mechanical replacement, while the tip reads `<repo>`, which
is the deliberate one written by `evidence/redact_paths.py`.

The lesson that outlasts both rewrites: the scan has to run on the commits,
not only the tree, before anything irreversible, and it now does, as a
gate in `release.sh` rather than a hook that fires at the end.

One timing detail mattered while this was being set up, and would matter
again for anyone repeating it: GitHub redirects a renamed repository's old
URL, so between renaming `NexusQC` to `NexusQC-dev` and creating the new
public `NexusQC`, the old URL still resolved to the private repository. A
`public` remote added in that window would have pushed development
history straight into the private repo while `release.sh` reported a
clean publication. Creating the public repository under the freed name is
what overrides the redirect. The remote is only safe to configure after
that, which is the order used here.

### The placeholder on the public remote

Until the first release, `public/main` held commits containing `README.md`
and nothing else, so the repository had a name and a readable landing page
without any code published ahead of the first release. It shared no history
with `main` by design, which meant the first real publication landed as a
non-fast-forward.

`release.sh` handles this case rather than discovering it at the end. One
of its gates identifies the placeholder by shape: every commit reachable
from the public `main` has a tree containing only `README.md`, and none of
them is an ancestor of `main`. It then replaces it with
`--force-with-lease`, which still refuses if the remote has moved
underneath it. The gate was first written for exactly one parentless
commit, and refused the legitimate first release after the README had been
refreshed on the public remote and the placeholder became two commits; the
shape is what matters, not the count. Anything else sitting on
`public/main` that isn't an ancestor of `main` stops the release outright,
because at that point something real is already published and reconciling
it is a decision someone has to make, not something a flag should paper
over.
