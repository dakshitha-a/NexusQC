# Testing

How NexusQC is tested, what a full end-to-end pass actually covered, and — kept
deliberately prominent — what it did **not** cover. The gaps are the useful part
of a test report; a list of passes without them is marketing.

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

A complete pre-deployment pass was run from a clean install: the stack built from
zero, then the whole product exercised through a real browser with a real user
account, driven by the agent itself rather than by direct API calls.

**Environment:** Ubuntu 22.04, 255 logical CPUs, 1 TB RAM, RTX 5000 Ada.
Docker Compose stack with Postgres 16, Redis 7 and nginx.

That pass produced 26 findings. All 21 actionable ones were fixed; the remaining
5 were positive or environmental observations needing no action. A follow-up
verification pass then re-ran every suite against the live stack, on the
principle that **"the code changed" and "the behaviour changed" are different
claims**, and only the second is worth anything before a deployment.

### Job matrix

Every job type on every engine that supports it — 26 cells.

| job type | PySCF | ORCA | BAGEL |
|---|---|---|---|
| `single_point` | pass 25.7 s | pass 25.2 s | — |
| `geometry_optimization` | pass 15.1 s | pass 90.1 s | timeout (see below) |
| `frequency` | pass 29.6 s | pass 34.0 s | **pass 26.2 s** |
| `casscf` | pass 21.3 s | pass 52.8 s | timeout |
| `caspt2` | — | — | timeout |
| `tddft` (CIS) | pass 41.6 s | pass 52.0 s | — |
| `tddft` (DFT) | pass 20.9 s | — | — |
| `eom_ccsd` | pass 25.4 s | pass 39.0 s | — |
| `mo_visualization` | pass 18.5 s | pass 28.0 s | pass 21.7 s |
| `pes_scan` | pass 24.1 s | pass 74.2 s | — |
| `neb_ts` | — | expected failure | — |
| `custom` | — | pass | pass 87.3 s |
| `recommend_active_space` | pass | — | — |

Result: **22 pass, 3 timeouts (all BAGEL), 1 real defect found, 2 explained.**

A passing cell was verified four ways, not one: the agent called `submit_job`
with the correct job type, engine and parameters; the approval card appeared
showing the right engine; the job reached `completed`; and its summary carried
the keys that job type is supposed to produce, with every declared artifact
downloadable.

The `neb_ts` cell is an *expected* failure: it correctly surfaced ORCA's
"No barrier was found" rejection as a failed job with the real reason. The toy
geometry used genuinely has no barrier.

**About the BAGEL timeouts.** These are an artefact of the test host, not a
product limitation and not a correctness problem — the energies BAGEL produced
were physically sensible. That machine's BAGEL/MKL install runs CASSCF
macro-iterations at roughly 80–96 s each for a trivial three-atom STO-3G system,
where PySCF and ORCA finish the same system in well under a second. Against a
600 s test budget, that is a timeout.

It is worth being explicit that **a long-running job is not a defect here.**
CASSCF and CASPT2 calculations routinely run for tens of minutes and sometimes
hours; the entire asynchronous job architecture exists so that is fine. The
leave-and-return workflow this depends on has its own standing regression test
(21/21), verified against a real ORCA CASSCF job submitted through the agent's
own approval gate: logging out touches no job, no process and no thread; the
worker subprocess is confirmed still alive afterwards by pid *and* recorded
creation time, so a recycled pid cannot be mistaken for a live one; the job
reaches `completed` with no session open at all; and on logging back in the job,
its results, its artifacts and the whole conversation are all still there.

### Authorization

All **57** routes, with the inventory taken from the app's own `/openapi.json`
rather than hand-written — so a new route cannot be silently omitted.

| Pass | Result |
|---|---|
| Anonymous access to non-public routes | 54/54 correctly reject |
| Non-admin → `/api/admin/*` | 14/14 return 403 |
| Cross-user access to another user's threads | All return 404 — indistinguishable from a nonexistent thread, so no existence leak |

One methodological note worth preserving, because it nearly produced a false
alarm: a first pass appeared to show a cross-user gap. It was the harness sending
empty request bodies, which FastAPI rejects with 422 *before* the ownership check
runs. Re-probed with valid bodies, ownership enforcement was correct and the
other user's data was verifiably unmodified. The sweep now carries a per-route
valid-body table so this cannot recur.

A dedicated security pass over the auth layer found and fixed eleven real bugs,
including one unauthenticated route serving another user's data. See
[ARCHITECTURE.md](ARCHITECTURE.md#security-findings-that-shaped-the-code) for the
ones with lasting design consequences.

### Performance

| Measurement | Value |
|---|---|
| Agent turn (n=23) | median 14.1 s, p90 26.3 s, max 78.9 s |
| Full scenario including job (n=24) | median 28.8 s, p90 74.2 s |
| Time to first streamed token (n=4) | median 15.2 s, range 6.3–31.7 s |
| First authenticated request (cold, creates schema) | 3 ms |
| Knowledge-base seed | 5 m 11 s → 4,186 chunks |
| Frontend main bundle | 1.19 MB (336 KB gzipped) |
| Ketcher lazy chunk | 28.7 MB (8.5 MB gzipped) |
| Cancel → subprocess confirmed dead | 0.01 s |

No horizontal page overflow at 1280, 1600 or 1920 px. Keyboard focus reaches
real controls with a visible indicator. `prefers-reduced-motion` collapses
animations globally.

### Chemistry correctness, checked by reading it

Some things only a human reading real output will catch. A BAGEL
`mo_visualization` run on water reported HOMO index 5 — correct for a
ten-electron closed shell — with MOs 1–5 at occupancy 2.00 and MO 6 at 0.00, the
oxygen 1s core at −550.9 eV (≈ −20.2 Ha, correct for STO-3G), and character
labels that read as a chemist would expect. Orbital indices honoured the 1-based
convention exactly.

Panel gating was correct in both directions across seven job types: the job
drawer showed every section it should and, equally important, omitted every
section it should not — no orbital section on a scan, no excited-state table on a
single-point.

Refusals also behaved well. Asked to plot a UV/Vis spectrum for a PySCF EOM-CCSD
job, the agent declined *and explained the fix*: PySCF's EOM-CCSD reports
excitation energies only, and re-running on ORCA would produce oscillator
strengths — then offered to do it.

**One defect was found this way and no other way**: an imaginary-frequency
colouring contradiction, invisible inside a passing test but obvious the moment a
human read the table. That fix produced the single-source-of-truth threshold
module described in ARCHITECTURE.md.

---

## What was not tested

Read this section as carefully as the ones above.

- **The public `:443` listener, end to end.** The deployment was exercised only
  through the intranet listener. Do not read any of the above as clearance to
  expose the public listener.
- **The host-level public-access kill switch**, which requires `sudo` and
  modifies a shared host's real firewall.
- **`neb_ts` against a reaction with a genuine barrier.** The geometry used had
  none, so the ground-state NEB path is unverified beyond correct failure
  handling. The excited-state path (`target_state`) was not attempted at all in
  this pass.
- **BAGEL CASSCF/CASPT2 to convergence** — not practically possible on the test
  host, for the environmental reason above.
- **The vLLM inference backend**, which remains commented out in compose.
- **Multi-host operation, real (non-self-signed) TLS, and any load beyond a
  single operator.**

## Testability note

The app historically shipped almost no `data-testid` attributes, so tests
targeted elements by `title`, visible text or placeholder — and several `title`
values collide across components. Test IDs are being added to newly-written UI;
adding one alongside a change is cheap and makes the test that follows far less
brittle.
