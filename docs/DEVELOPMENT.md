# Development workflow

> **[WORKFLOW.md](WORKFLOW.md) is the primary guide** and holds the actual
> procedure — branching, merging, pushing, releasing, testing, promoting to
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
filter, no parallel tree — because nothing host-specific gets committed in
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
warns on routable IP literals too.

It does not flag the author's name. The name is already in the repository
URL, in every commit's authorship, and in the README — publication
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
screenshot needs a human look before it's committed — a screenshot of the
app can show a username, an email, or unpublished chemistry that no text
pattern will ever catch. And it only sees what's tracked; it has nothing
to say about what you happen to have running.

### If the scan flags something

Fix the content. If it's genuinely a false positive, narrow the pattern in
the script itself rather than adding an exception or reaching for
`--no-verify`. One pattern in that file is deliberately written as a
character class (`/[s]oftware/`), specifically so a find-and-replace over
this repository's own history can't rewrite the detector along with
everything else — that's not a typo, and the same care applies to any
pattern naming a real path or host.

## Publishing

`scripts/release.sh <version>` refuses to run unless you're on `main`, the
tree is clean, the safety scan passes, `main` matches `origin/main`, the
tag doesn't already exist, and `CHANGELOG.md` has a section for the
version. Then it updates `CITATION.cff`, commits, tags, and pushes to both
remotes.

```bash
scripts/release.sh 1.1.0 --dry-run   # run every gate, push nothing
scripts/release.sh 1.1.0
```

Because history gets published, the asymmetry is worth keeping in mind: a
private push is reversible, and a public one really isn't.

## Why the public repository has to stay a separate repository

`NexusQC-dev` and `NexusQC` are two repositories, not one repository with
a visibility switch — and that split isn't an accident of how this got
set up. Never publish by flipping `NexusQC-dev` to public in GitHub's
settings.

The private repository predates a one-time history rewrite, so it once
held commits with this host's real paths, hostname, and addresses.
Force-pushing the rewritten history replaced what `main` points at, but a
merged pull request leaves behind a server-side `refs/pull/<n>/head` ref
that no push can remove, and that keeps the original commits alive.
They're unreachable from any branch, invisible in normal use, and still
fetchable by SHA anyway. Nothing secret ever lived in them — no key or
credential was ever committed — but the pre-rewrite host details did.

So publication has to be a fresh push into a repository that's never had a
pull request, which is exactly what the `public` remote is. A visibility
toggle on the development repository would drag the pre-rewrite refs out
along with everything else.

One timing detail mattered while this was being set up, and would matter
again for anyone repeating it: GitHub redirects a renamed repository's old
URL, so between renaming `NexusQC` to `NexusQC-dev` and creating the new
public `NexusQC`, the old URL still resolved to the private repository. A
`public` remote added in that window would have pushed development
history straight into the private repo while `release.sh` reported a
clean publication. Creating the public repository under the freed name is
what overrides the redirect — the remote is only safe to configure after
that, which is the order used here.

### The placeholder commit on the public remote

`public/main` currently holds a single commit containing `README.md` and
nothing else, with no parent, so the repository has a name and a readable
landing page without any code published ahead of the first release. It
shares no history with `main` by design, which means the first real
publication lands as a non-fast-forward.

`release.sh` handles this case rather than discovering it at the end. One
of its gates identifies that commit by its exact shape — no parent, a tree
containing only `README.md` — and replaces it with `--force-with-lease`,
which still refuses if the remote has moved underneath it. Anything else
sitting on `public/main` that isn't an ancestor of `main` stops the
release outright, because at that point something real is already
published and reconciling it is a decision someone has to make, not
something a flag should paper over. Until that first release, the
README's links to files under `docs/` won't resolve on the public
repository.
