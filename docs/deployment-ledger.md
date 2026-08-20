# Deployment ledger

Which commits have been verified on the development stack, and are therefore
allowed to reach the lab's production deployment.

This file is a gate, not a report. `scripts/promote.sh` reads it and refuses any
commit that has no passing `verified` row here — so an empty table means nothing
can be promoted, which is the correct behaviour for a project where nothing has
been tested yet. See [DEVELOPMENT.md](DEVELOPMENT.md) for the workflow this
belongs to.

## How rows get here

Only `scripts/dev_stack.sh verify` appends them. It refuses to write one unless
the working tree is clean, so the sha in a row is genuinely the code that ran,
and it refuses to write one at all if the suite fails. Do not add rows by hand:
the point of the row is that a machine observed the suite pass, and a
hand-written row records only that somebody believed it had.

The sha named is the commit that was tested. A commit that adds *only*
documentation on top of a verified one is also promotable — `promote.sh` works
that out from the diff, because the commit that records a verification cannot
contain the row recording it.

## Why this is a tracked file rather than a git note or local state

Two rejected alternatives, for the record:

- **git notes** (`refs/notes/*`) do not push without an explicit refspec, so the
  verification would exist on one machine and be invisible everywhere else.
- **an untracked local file** has the same problem, and additionally cannot be
  read by a promotion running in a different checkout — which is exactly where
  `promote.sh` runs.

The gate has to travel with the commit, so it lives in the commit.

## What a row does not tell you

That the suite passed on this host, against the dev stack, at that moment. It is
evidence, not proof: `tests/` covers the auth/admin layer and the deployment
shape, not the chemistry (see [TESTING.md](TESTING.md)). A green row does not
mean a new CASSCF code path is correct, and nothing here substitutes for running
the calculation you changed and looking at the numbers.

## Ledger

| kind | when (UTC) | commit | suite | result |
|---|---|---|---|---|
| verified | 2026-08-17T15:53:04Z | 54046ad7ec4f95cd8a774401e8011f5fc0795e33 | backend | pass |
| verified | 2026-08-17T16:00:27Z | ec068c620029d2f41847d708798328b8e52e5b4a | backend | pass |
| verified | 2026-08-17T16:12:32Z | 9d7a36c99a5a854ab60006594b592cec01b18603 | backend | pass |
| verified | 2026-08-17T20:08:14Z | a08ed5828f8f41f8aa6cea833efeb6514a162bfb | backend | pass |
| verified | 2026-08-17T21:10:04Z | c339673d5c5054740ea51b3113bd7fb8a1eaf60e | backend | pass |
| verified | 2026-08-18T00:58:59Z | a59277c9c77f72d59b88309158ea3ed39cc028c7 | backend | pass |
| verified | 2026-08-20T01:03:03Z | d2a88d0801f34eb3f809c6f9f39923990d797880 | backend | pass |
