# Contributing

NexusQC is developed in a private repository and published here in releases.
That one fact shapes everything below: a report you file here is read by the
maintainer, worked in the private repository, and lands here with the next
release. Nothing is merged on this repository. What you can see of the work in
between is carried by labels and comments on your issue, which is why they are
kept current rather than left to the imagination.

## Reporting a bug

Use the **Bug report** form under *Issues → New issue*. Blank issues are off
because a report without a version and a description cannot be worked.

The form asks for the version. Every deployment shows its own under
**Help → About** in the app, with a copy button; it looks like
`v1.1.0 (0123456789ab)` and names the exact commit the server was built from.
The in-app **Report a bug** panel also has an **Open on GitHub** link that
opens the form with the version and your text already filled in.

Two reporting paths exist on purpose. **Report a bug** inside the app sends the
report to the administrator of *that deployment*, screenshots included, and
nowhere else. Filing here makes it public and reaches the maintainer of the
software. Use the first for "something is wrong with our server", the second
for "something is wrong with NexusQC". The deployment's administrator can
forward an in-app report here with one click if it turns out to be the latter.

A security problem is neither: see [SECURITY.md](SECURITY.md).

## Requesting a feature

Use the **Feature request** form. Say what you are trying to do in chemistry
terms before saying what the interface should look like; the first is what
decides whether and how it gets built.

## What the labels mean

| Label | Meaning |
|---|---|
| `triage` | Filed, not yet looked at. Applied automatically. |
| `needs-info` | Could not be reproduced from what is there; the question is in the comments. |
| `fixed-on-main` | Fixed on the development branch. Not yet installable; the comment says so. |
| *closed* | Released. The closing comment names the version that carries the fix. |

An issue is closed only when the fix is in a release you can install, never
when it is merely fixed. "Closed" and "shipped" mean the same thing here.

## Pull requests

Pull requests are welcome, with one mechanical caveat: they are not merged on
this repository, because published history is pushed from the private one and
the two are kept as a single history. Your commits are applied to the
development branch with `git am`, which preserves you as the author, and the
pull request is closed with a comment naming the release that shipped them.
CI runs on the pull request here in the meantime.

To make that smooth:

- Open or link an issue first, so the change has a reason on record.
- Keep commits self-contained; a commit that mixes a fix with an unrelated
  reformat cannot be applied as is.
- A regression test is the most useful thing you can add. Backend tests are
  standalone scripts in `tests/backend/`, frontend ones are Playwright specs
  in `tests/frontend/`; an issue's test is named `issue_<n>_<slug>` in either.
  [tests/README.md](tests/README.md) explains the conventions.
- Running from source, the two-remote workflow and the public-safety scan are
  in [docs/DEVELOPMENT.md](docs/DEVELOPMENT.md).

## Style

Prose in this repository is written for a scientist who will rely on it: every
number comes with what produced it, every claim with what verifies it.
Documentation changes ship in the same commit as the code they describe.
