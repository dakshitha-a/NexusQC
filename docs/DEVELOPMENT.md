# Development workflow

> **[WORKFLOW.md](WORKFLOW.md) is the primary guide** and holds the procedure:
> branching, merging, pushing, releasing, testing and promoting to a deployment.
> This document is the *rationale* for the two-remote arrangement specifically —
> why it is safe to keep one history and publish from it, and what would break
> that. Read WORKFLOW.md to find out what to run; read this to find out why it is
> shaped this way.

One repository, one branch, one history, two remotes. Development happens
continuously against a private remote; publishing to the public remote is a
separate, deliberate act.

| Remote | Repository | Visibility | When it is pushed |
|---|---|---|---|
| `origin` | `NexusQC-dev` | private | continuously, as ordinary work |
| `public` | `NexusQC` | public | only by `scripts/release.sh` |

```bash
git push origin main            # ordinary work
scripts/release.sh 1.1.0        # publish a release
```

## The invariant that makes this cheap

**Everything tracked in git is publishable.** There is no sanitised branch, no
export filter and no parallel tree, because nothing host-specific is ever
committed in the first place.

That invariant is what removes the per-change cost. It is worth understanding why
it holds, because the cost comes straight back if it is broken:

- Host-specific configuration reaches the app through the environment, never
  through committed defaults. `app/config.py` carries generic defaults; `.env`
  overrides them. See [CONFIGURATION.md](CONFIGURATION.md).
- Anything genuinely host-specific is untracked and gitignored: `.env`,
  `docker-compose.override.yml`, `nginx/certs/*`, and `CLAUDE.local.md` for
  "on this particular machine" notes. Each has a committed `*.example`
  counterpart where one is useful.
- `scripts/check_public_safe.sh` enforces it mechanically on the way to the
  public remote — `scripts/release.sh` runs it before publishing anything, and
  the pre-push hook runs it for any remote that is not known-private. Pushes to
  `origin` are exempt: it is private, so there is nothing there to disclose.

So the rule for new work is simply: if a value is true of *your machine* rather
than of the project, it belongs in `.env` or `CLAUDE.local.md`, not in a tracked
file.

## Required once per clone

```bash
scripts/hooks/install.sh
```

Git does not track `.git/hooks`, so **a fresh clone has no protection until this
runs.** It installs a pre-push hook that runs the public-safety scan and refuses
the push on a finding.

## What the safety scan covers

`scripts/check_public_safe.sh` blocks: home- or user-scoped absolute paths,
site-specific install trees, the operator's username in file content, private key
material, hardcoded credentials, bare institutional hostnames, files that must
never be tracked (`.env`, `*.key`, `CLAUDE.local.md`, ...), and machine-generated
test output. It warns on routable IP literals.

Three modes:

```bash
scripts/check_public_safe.sh                  # all tracked files
scripts/check_public_safe.sh --staged         # staged changes only
scripts/check_public_safe.sh --range A..B     # the commits in a range
```

The range mode exists because a working-tree scan alone has a hole: content
committed and then removed in a later commit passes the scan while the leak sits
permanently in history. The pre-push hook uses both.

**Two things the scan cannot do.** It cannot read images, so any new screenshot
needs a human look before it is committed — a screenshot of the app can show a
username, an email or unpublished chemistry that no text pattern will catch. And
it only sees what is tracked; it says nothing about what you have running.

### If the scan flags something

Fix the content. If it is genuinely a false positive, **narrow the pattern in the
script** rather than adding an exception or using `--no-verify`. One pattern in
that file is deliberately written as a character class (`/[s]oftware/`) so that a
find-and-replace over this repository's history cannot rewrite the detector
itself — that is not a typo, and the same care applies to any pattern naming a
real path or host.

## Publishing

`scripts/release.sh <version>` refuses to run unless: you are on `main`, the tree
is clean, the safety scan passes, `main` matches `origin/main`, the tag does not
already exist, and `CHANGELOG.md` has a section for the version. It then updates
`CITATION.cff`, commits, tags, and pushes to both remotes.

```bash
scripts/release.sh 1.1.0 --dry-run   # run every gate, push nothing
scripts/release.sh 1.1.0
```

Because history is published, it is worth remembering the asymmetry: a private
push is reversible, a public one is not.

## Why the public repository must stay a separate repository

`NexusQC-dev` and `NexusQC` are two repositories rather than one repository with
a visibility switch, and that is not an accident of how this was set up. **Never
publish by flipping `NexusQC-dev` to public in the GitHub settings.**

The private repository predates the one-time history rewrite, so it once held
commits containing this host's real paths, hostname and addresses. Force-pushing
the rewritten history replaced what `main` points at, but a merged pull request
leaves a server-side `refs/pull/<n>/head` ref that no push can remove and that
keeps the original commits alive. They are unreachable from any branch and
invisible in normal use, yet still fetchable by SHA. Nothing secret is in them —
no key or credential was ever committed — but the pre-rewrite host details are.

Publication therefore has to be a **fresh push into a repository that has never
had a pull request**, which is exactly what the `public` remote is. A visibility
toggle on the development repository would expose the pre-rewrite refs along with
everything else.

A timing detail that mattered while this was being set up, and would matter
again for anyone repeating it: GitHub redirects a renamed repository's old URL,
so between renaming `NexusQC` to `NexusQC-dev` and creating the new public
`NexusQC`, the old URL still resolved to the **private** repository. A `public`
remote added in that window would have pushed development history straight into
the private repo while `release.sh` reported a successful publication. Creating
the public repository under the freed name overrides the redirect; the remote is
safe to configure only after that, which is the order used here.

### The placeholder commit on the public remote

`public/main` currently holds a single commit containing `README.md` and nothing
else, with no parent, so the repository has a name and a readable landing page
without publishing any code ahead of the first release. It shares no history with
`main` by design, which means the first real publication is a non-fast-forward.

`release.sh` handles this rather than discovering it at the end: one of its gates
identifies that commit by its exact shape — no parent, and a tree containing only
`README.md` — and replaces it with `--force-with-lease`, which still refuses if
the remote has moved. Anything else on `public/main` that is not an ancestor of
`main` stops the release, because at that point something real is published and
reconciling it is a decision, not a flag. Until that first release, the README's
links to files under `docs/` do not resolve on the public repository.
