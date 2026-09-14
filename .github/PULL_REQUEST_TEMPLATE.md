Thanks for the change. Two things worth knowing before you spend time on it:

- Pull requests here are not merged on this repository. Published history is
  pushed from a private development repository, so your commits are applied
  there with `git am`, which keeps you as the author, and the pull request is
  closed with a comment naming the release that shipped them. See
  [CONTRIBUTING.md](../blob/main/CONTRIBUTING.md).
- Link the issue this fixes, or open one first if there is none. A regression
  test in `tests/backend/issue_<n>_<slug>.py` or
  `tests/frontend/issue_<n>_<slug>.spec.mjs` is very welcome and is what the
  maintainer would write anyway.

Fixes what, and how:

