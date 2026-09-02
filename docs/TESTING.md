# Testing

How NexusQC is tested: the shape of the standing suite, and what a full
end-to-end pass looks like when one is run. For what's currently open or
unverified, see [`docs/BACKLOG.md`](BACKLOG.md). That's the living record,
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
| `tests/e2e/*.py`, `tests/e2e/ui/*.mjs` | Full-product end-to-end scenarios | `tests/e2e/`. See its README |

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

`tests/backend/sec_10_*` is excluded from the default run, destructive-shaped,
though scoped to a disposable account, and must be run deliberately.

---

## Full end-to-end pass

There have been two of these so far. The first, clean install, full product
exercised through a real browser and a real user account, driven by the agent
itself, ran 2026-08-16/17. Its findings, fix plan and verification record are
retired now that the last items they tracked are closed; the raw investigation
still lives in git history (`git log --all --full-history -- docs/ROADMAP.md`
finds the commit, `git show <sha>:docs/ROADMAP.md` prints it) rather than
being carried forward as something you're meant to keep reading. What's
worth keeping from it is the *shape* of a good pass. Clean install, driven
by the agent rather than direct API calls, four-way verification per job
cell, reading real output instead of trusting a bare pass/fail, and being
careful to distinguish "the code changed" from "the behaviour changed."
That shape is worth repeating each time, not the specific findings.

The second was the overhaul's closing regression pass, 2026-08-20
(`docs/trackers/2026-08-job-system-overhaul.md`'s P9.8), `tests/run_backend.sh`, `tests/e2e/run_e2e.sh`
and `tests/e2e/ui` all run clean against the finished registry v2/agent
rebuild. Its findings live in `docs/BACKLOG.md`'s "Found by testing" section,
including one fixed the same day: `cas_reco/autocas` was refusing an entire
active-space recommendation whenever the requested number of states
exceeded what the AVAS pilot space could hold, even though AVAS itself,
checked against the real published method, not just this app's own call
site, has no notion of states at all. It was fixed then by running the
recommendation regardless and clamping the state count at the final CASSCF
step. Both the pilot and that final CASSCF are gone as of the 2026-09-02
rebuild (`docs/CAS_ENGINE_METHOD.md`); the paragraph is kept as the record of
what that pass found.

**`docs/BACKLOG.md` is where a fresh pass's findings belong**, going forward.
It also carries the "what was not tested" list, since that's genuinely still
true and independent of which pass produced it.

For lasting security-design consequences of that pass rather than its point-in-time
results, see [ARCHITECTURE.md](ARCHITECTURE.md#security-findings-that-shaped-the-code).

## Testability note

The app historically shipped almost no `data-testid` attributes, so tests
targeted elements by `title`, visible text or placeholder, and several `title`
values collide across components. Test IDs are being added to newly-written UI;
adding one alongside a change is cheap and makes the test that follows far less
brittle.
