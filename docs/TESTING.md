# Testing

How NexusQC is tested: the shape of the standing suite, and what a full
end-to-end pass looks like when one is run. For what's currently open or
unverified, see [`docs/BACKLOG.md`](BACKLOG.md) — that's the living record,
kept separate from this description of the testing infrastructure itself.

## The shape of the test suite

There is no pytest suite for the chemistry and agent core. Validating a change
there means invoking the relevant runner or graph function directly, which suits
code whose "assertions" are mostly physical: does this energy match an
independent calculation, does this parser find what a real run actually printed.

`tests/` **is** a real, standing suite, covering the multi-user auth/admin layer
and full end-to-end product behaviour. It follows the same invoke-and-print
convention rather than introducing a test framework:

| Location | What it is | How to run |
|---|---|---|
| `tests/backend/*.py` | Standalone httpx scripts against a live stack | `tests/run_backend.sh` |
| `tests/frontend/*.spec.mjs` | Raw Playwright scripts (no `@playwright/test` runner) | `npm run test:e2e` |
| `tests/e2e/*.py`, `tests/e2e/ui/*.mjs` | Full-product end-to-end scenarios | `tests/e2e/` — see its README |

This suite needs the **full `docker-compose.yml` stack** (Postgres, Redis, api,
nginx), not just a running `server.main`. The auth layer is inert without
`QC_AGENT_DATABASE_URL`, and several of the bugs these tests exist to catch are
properties of the nginx-fronted deployment rather than of the bare process.

Two things that look like breakage but are not:

- **A `sec_*` script printing `[FAIL]` is often the expected outcome.** Several
  exist specifically to demonstrate that a particular gap is real. `run_backend.sh`
  still reports overall success for those.
- **Every script in `tests/backend/` shares one apparent client IP**, which
  collides with the per-IP login rate limiter. The shared fixture resets the
  buckets before logging in; scripts that must exceed the budget within their own
  run reset around their own heavy sections. A lone rate-limit failure usually
  means something else was running against the same stack concurrently.

`tests/backend/sec_10_*` is excluded from the default run — destructive-shaped,
though scoped to a disposable account — and must be run deliberately.

---

## Full end-to-end pass

A complete pre-deployment pass — clean install, full product exercised through
a real browser and a real user account, driven by the agent itself — was run on
2026-08-16/17. Its findings, ranked fix plan, and fix-verification record are
retired now that the last items they tracked are closed; the raw investigation
is preserved in git history rather than carried forward as living documentation
(`git log --all --full-history -- docs/ROADMAP.md` finds the commit, `git show
<sha>:docs/ROADMAP.md` prints it). What it established that
still generally holds — the shape of a good pass (clean install, driven by the
agent rather than direct API calls, four-way verification per job cell, reading
real output rather than trusting only pass/fail, distinguishing "the code
changed" from "the behaviour changed") — is worth repeating in the next one,
not worth re-reading in the old one.

**`docs/BACKLOG.md` is where a fresh pass's findings belong.** It also carries
the "what was not tested" list forward, since that's genuinely still true and
independent of which pass produced it.

For lasting security-design consequences of that pass rather than its point-in-time
results, see [ARCHITECTURE.md](ARCHITECTURE.md#security-findings-that-shaped-the-code).

## Testability note

The app historically shipped almost no `data-testid` attributes, so tests
targeted elements by `title`, visible text or placeholder — and several `title`
values collide across components. Test IDs are being added to newly-written UI;
adding one alongside a change is cheap and makes the test that follows far less
brittle.
