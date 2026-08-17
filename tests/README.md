# Auth/admin/user-management test suite

Standalone invoke-and-print scripts run against a LIVE stack, matching this
repo's existing verification style (CLAUDE.md: no pytest exists, backend
changes are validated by invoking real code/routes directly). There is no
test framework here on purpose -- each script prints `[PASS]`/`[FAIL]` lines
per check and exits non-zero if anything failed.

## Bring-up

This suite runs against the full `docker-compose.yml` stack (Postgres,
Redis, the `api` container, nginx with a self-signed cert), not the bare
`python -m server.main` local-dev workflow -- auth/admin only exist when
`QC_AGENT_DATABASE_URL` is set, which the compose stack does.

```bash
cd /path/to/NexusQC

# One-time setup, if you haven't already brought the stack up:
#   1. `docker compose version` must work (Compose v2 CLI plugin).
#   2. Generate throwaway TLS certs into nginx/certs/ -- nginx requires
#      HTTPS, and the session cookie is Secure, so login fails over plain
#      HTTP. See docs/DEPLOYMENT.md for the openssl one-liner.
#   3. `cp .env.example .env` and set QC_AGENT_POSTGRES_PASSWORD and
#      QC_AGENT_JWT_SECRET to generated values.

docker compose up -d postgres redis api nginx
docker compose ps   # wait for all four to be healthy/running

python3 tests/backend/_00_bootstrap.py   # provisions qatest_admin, run once per fresh stack
```

## Running the suite

```bash
bash tests/run_backend.sh          # everything except the isolated destructive test
python3 tests/backend/sec_10_bootstrap_reactivation_bypass.py   # opt-in, see its own docstring

npm --prefix frontend run test:e2e   # requires: playwright install chromium (once)
```

## What "FAIL" means here

Group A (`sec_*`) scripts were originally written to PROVE a specific
already-suspected bug -- a `[FAIL]` line meant **the bug was confirmed
real**, the useful signal this suite existed to produce. Every one of
those bugs is now fixed (see `CLAUDE.md` for the full list), so every
`sec_*` script has since been rewritten into a fix-regression test:
`[PASS]` now means the fix holds, and a `[FAIL]` means a regression, full
stop -- no `sec_*` script is expected to show `[FAIL]` on this suite
anymore. (`sec_07_async_ownership_window.py` and
`sec_09_kb_delete_filename_collision.py` were the last two still in the
original bug-confirming shape; both were revisited and their findings
fixed -- see CLAUDE.md's SEC-07/SEC-09 notes.) Group B (`conf_*`) scripts
confirm a security boundary genuinely holds, so `[FAIL]` there means a
boundary that was assumed safe isn't. `p1_*`/`perf_*` scripts are ordinary
functional/performance coverage where `[FAIL]` means what it normally
means.

After a fix lands for a confirmed `sec_*` finding, re-run that specific
script and confirm it flips to all-PASS before moving on -- this suite is
meant to be re-run on demand as informal regression coverage going
forward, not just a one-time audit.

**Every script shares one apparent client IP** (whatever machine runs the
suite, seen by nginx as one address), which collides with the per-IP
login/register rate limiter (`app/auth/rate_limit.py`) unless managed --
`fixtures.admin_client()` (the first call in every script) already calls
`fixtures.reset_rate_limits()` before logging in, so a fresh script always
gets a full budget. If you add a new script that itself needs more than a
handful of login/register calls within its own run, call
`reset_rate_limits()` around that specific burst too (see `sec_03`,
`sec_05`, `p1_01`, `perf_01` for the pattern) -- otherwise later calls in
that same script will 429 instead of exercising whatever you're actually
testing.

## Fixture / cleanup policy

- Every test-created account has a username prefixed `qatest_`
  (`fixtures.qatest_username()`), making it trivial to find and delete.
- `fixtures.cleanup_user()` / `cleanup_all_qatest_users()` delete via the
  real `DELETE /api/admin/users/{id}` route -- never `server/admin_cli.py
  reset-all`, which would also wipe any real, non-test account on this
  stack.
- Several `sec_*`/`conf_*` scripts exec into the running `api` container
  (`docker compose exec -T api python -c ...`) to directly call functions
  like `record_ownership()` or flip a DB flag -- this is a deliberate,
  documented shortcut to construct a specific test scenario (e.g. "a job
  owned by user A, without going through a full chat/LLM tool-calling
  turn") using the exact same functions the real app calls, not a
  different code path. Each script's docstring explains why.
- `tests/.admin_creds` (gitignored) holds the qatest_admin password
  `_00_bootstrap.py` generates -- delete it and re-run `_00_bootstrap.py`
  to rotate it, or if you've reset the stack's database.

## Layout

```
tests/
  fixtures.py                     shared httpx helpers
  run_backend.sh                  runs tests/backend/*.py, aggregates PASS/FAIL
  backend/
    _00_bootstrap.py              MUST run first
    sec_01..09_*.py                Group A: prove a specific bug (see plan)
    sec_08b_*.py                   SEC-08 follow-up: cancel-on-delete race
    sec_10_*.py                    isolated/destructive, opt-in only
    conf_01..04_*.py               Group B: confirm a boundary holds
    perf_01..03_*.py               performance baselines, not pass/fail gates
    p1_01..04_*.py                 functional coverage
  frontend/
    run_frontend.mjs              runs tests/frontend/*.spec.mjs
    fe_*.spec.mjs                  bug-proving Playwright scenarios
```
