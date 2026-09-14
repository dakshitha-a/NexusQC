---
name: issue
description: Work a public GitHub issue or pull request end to end in this repository, or file one for a maintainer-originated feature. Use when the user says "/issue <n>", "work issue 12", "fix #12", "look at the bug reports", "/issue new <title>", or "/issue pr <n>". Reproduce first, fix on main, reference the issue without closing it; releases close issues.
---

# Working a public issue

The reporter can see the public repository and nothing else. The branch you
are on is private. Everything they learn about the state of their report comes
from its labels and its comments, so those are kept current by the commands
below rather than from memory, and the words are fixed in `scripts/issues.sh`
so every reporter reads the same sentence at the same step.

Forms: `/issue <n>` works issue n. `/issue new "<title>" [--feature]` files an
issue first, for work the maintainer originates, so the roadmap is visible
before the work starts, then continues as `/issue <n>`. `/issue pr <n>` lands
a contributor's pull request. Start of a session with nothing in mind:
`scripts/issues.sh list` prints the queue, `triage` first.

## Steps

1. **Read it.** `scripts/issues.sh show <n>` (the issue and its comments).
   For `new`: `scripts/issues.sh new "<title>"` (`--feature` for an
   enhancement), then continue with the number it prints. For `pr`: `gh pr
   diff <n> -R dakshitha-a/NexusQC --patch | git am` applies the commits with
   the contributor's authorship; from here on it is a fix like any other, and
   the pull request number is what gets referenced.

2. **Reproduce before touching anything.** Write the regression test first:
   `tests/backend/issue_<n>_<slug>.py` or
   `tests/frontend/issue_<n>_<slug>.spec.mjs`, following `tests/fixtures.py`
   and the conventions in `tests/README.md`. Both runners pick the file up by
   name. Before it joins the default backend run, check it against the
   quarantine rule at the top of `tests/run_backend.sh`: `grep -l
   "admin/purge/jobs" tests/backend/*.py` must not gain a name that purges.
   Run the test and show it failing. If it cannot be made to fail from what
   the report says, do not guess: `scripts/issues.sh needs-info <n> "<the
   specific question>"` and stop.

3. **Decide whether it needs a tracker.** `docs/WORKFLOW.md`'s threshold:
   anything bigger than a small fix gets a tracker, and there is never more
   than one open. A one-file fix with a test does not.

4. **Fix it on `main`.** A frontend change is verified in a real browser, by
   rendering it and looking (CLAUDE.md). A bug found along the way is fixed
   along the way. A fix that applies to one engine or method is carried to
   all of them.

5. **CHANGELOG.** An entry under `## [Unreleased]` that says what was wrong
   and what changed, ending with the reference:
   `([#<n>](https://github.com/dakshitha-a/NexusQC/issues/<n>))`. Pull
   requests use `/pull/<n>`.

6. **Commit**, docs in the same commit, with the trailer
   `Refs: dakshitha-a/NexusQC#<n>` on its own line at the end of the body.
   The full `owner/repo#n` form, never a bare `#n`, and never `Fixes`,
   `Closes` or `Resolves`: every commit message is replayed against the
   public repository when a release is pushed, and a closing keyword would
   close the issue there without the "released in" comment that gives the
   reporter the version to install. `scripts/release_announce.sh` reads the
   `Refs:` trailers to know which issues a release closes, so a missing
   trailer is an issue that never gets closed.

7. **Push** (`git push origin main`), then `scripts/issues.sh fixed <n>`.
   That comments "fixed on the development branch, ships in the next
   release" and swaps `triage` for `fixed-on-main`. Never close the issue
   yourself; `release.sh` does, with the version.

## What not to do

- Do not close, or let a commit close, a public issue. Closed means shipped.
- Do not comment on the issue in your own words for state changes; use the
  script so the vocabulary stays fixed. Free-form comments are for questions
  and for explaining a decision.
- Do not merge or push anything on the public repository. Publication is
  `scripts/release.sh` only.
- Do not skip the failing test because the fix is obvious. The test is what
  proves the issue is the one the reporter had.
