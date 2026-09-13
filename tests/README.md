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
bash tests/run_backend.sh          # everything except the two destructive scripts
python3 tests/backend/sec_10_bootstrap_reactivation_bypass.py   # opt-in, see its own docstring
python3 tests/backend/p1_07_purge_status_source.py              # opt-in, WIPES EVERY JOB
```

**`p1_07` destroys every job on the stack**, not only the ones it creates: it
exercises `POST /api/admin/purge/jobs`, which is a deployment-wide purge. It
used to be in the default run, and on 2026-08-28 a full suite run took out the
job artifacts behind three live conversations. The conversations themselves
survived, because a job purge does not touch the Postgres checkpoints, but the
results on disk were gone. Run it against a stack you are willing to empty,
and not against one somebody is using.

```bash

npm --prefix frontend run test:e2e   # requires: playwright install chromium (once)
```

## What "FAIL" means here

Group A (`sec_*`) scripts were originally written to PROVE a specific
already-suspected bug -- a `[FAIL]` line meant **the bug was confirmed
real**, which was the whole point of that script existing. Every one of
those bugs is fixed now (the ones with lasting design consequences are
written up in `docs/ARCHITECTURE.md`'s "Security findings that shaped the
code"; the narrower ones live only in their own script's docstring and git
history), so every `sec_*` script has since been rewritten into a
fix-regression test: `[PASS]` means the fix holds, `[FAIL]` means a
regression, full stop. No `sec_*` script should show `[FAIL]` on this suite
anymore. `sec_07_async_ownership_window.py` and
`sec_09_kb_delete_filename_collision.py` were the last two still in the
original bug-confirming shape; both were revisited and rewritten the same
way once their underlying bugs were fixed. Group B (`conf_*`) scripts
confirm a security boundary genuinely holds, so `[FAIL]` there means a
boundary assumed safe actually isn't. `p1_*`/`perf_*` scripts are ordinary
functional/performance coverage, where `[FAIL]` means what you'd expect.

After a fix lands for a confirmed `sec_*` finding, re-run that specific
script and confirm it flips to all-PASS before moving on -- this suite is
meant to be re-run on demand as informal regression coverage going
forward, not just a one-time audit.

**Two scripts race the running container and fail for that reason alone.**
`fail_01_notice_flow.py` and `perf_04_fair_scheduling.py` both run their own
`JobWatcher`/`JobManager` **in the host process** while the compose stack's own
API container is running one too, against the same bind-mounted `data/`. Two
things follow:

- `fail_01` shares `data/jobs/_seen/<thread_id>.json` with the container's
  watcher. If the container marks the failed job seen first, the host's
  watcher finds nothing newly-done, posts no notice, and the script reports
  "exactly one notice message -- 0 found" together with only a `job_update`
  event. Nothing is wrong with the notice path.
- `perf_04` asserts on admission ORDER under a global cap of 1. Jobs left
  running by earlier scripts in the same suite run occupy that cap, so it sees
  a partial, skewed order ("observed 5 of 7").

Both pass on their own: `fail_01` with the API container stopped (20/20), and
`perf_04` against an otherwise idle stack (5/5). Confirm that before treating
either as a regression, and do not "fix" the notice path on the strength of a
full-suite run.

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
```

The `backend/` directory outgrew a simple sec/conf/perf/p1 split a while
back. Each phase of the registry-v2/agent overhaul picked up its own
prefix as it landed. This table says what each prefix is *for*; it isn't
an exhaustive file list, because that would just go stale again the next
time a phase adds five scripts. Run `ls tests/backend/` for what's
actually there right now.

| Prefix | Covers |
|---|---|
| `sec_01`..`sec_10` | Group A, see "What FAIL means here" above |
| `conf_01`..`conf_04` | Group B, confirms a security boundary holds |
| `perf_01`..`perf_05` | login concurrency, admin storage latency, per-user job caps, fair round-robin scheduling, restart re-enqueue |
| `p1_01`..`p1_06` | registration, sessions, invites, suspend/restore + lockout, password changes |
| `p1_07` | the admin purge acts on the jobs the console lists, one definition of "terminal", and the orphan-directory sweep's age gate. **Excluded from `run_backend.sh`: it purges every job on the stack** |
| `deploy_01`..`deploy_03` | `scripts/update.sh`'s own logic, tested by lifting the shell out of it: what it believes is deployed, what it writes to `.update-log`, and what it tells an operator to do when an update fails |
| `install_01`, `install_02` | `scripts/install.sh` and the library it shares with `update.sh`. `install_01` is static: it parses, its prologue is still POSIX (a bashism there kills `curl \| sh` on every Debian-family machine), `--help` answers through a real `dash` pipe without cloning anything, every refusal names what to do instead, and README still documents the tools the script enforces. `install_02` runs the shared helpers against input built to break them. Neither installs anything |
| `agent_01`..`agent_04` | the LangGraph agent: system-prompt token budget, the job-draft flow, context trimming, resuming an old thread |
| `elic_01` | draft elicitation, twenty-one scenarios, every task walked from empty to `ready` |
| `tax_01`..`tax_02` | the v2 job taxonomy: specs and job rows read/write in the new shape |
| `reg_01`, `reg2_01`, `reg2b_01`..`reg2b_03` | the v2 capability registry. Payload shape, and that nothing still re-decides what it already decided |
| `sniff_01` | recognizing a pasted ORCA/BAGEL/PySCF input without ever executing pasted Python |
| `tddft_01` | full TDDFT, not TDA, is the excited-state default |
| `scan_01` | a malformed PES-scan draft fails with a sentence, not a stack trace |
| `grad_01`, `opt_01` | gradient/NAC and constrained-opt/CI-opt coverage against real engine runs, all three engines |
| `p7_01`..`p7_05`, `p7_orchestrator_fault_isolation` | batch/ensemble orchestration: pagination, cascade reordering, one bad master not stalling the rest |
| `p8_01`..`p8_04` | cross-job orbital reuse, the cas_reco follow-up, the Wigner sample cap, plain CCSD/MP2 single points |
| `up_01` | the upload manager's lifecycle and attach semantics |
| `dz_01` | the self-service "danger zone", purge/download your own data |
| `fail_01` | a failed job notifies the user and starts nothing (the regression test for removing auto-retry) |
| `plots_01` | the Plots panel lists saved plots, their thumbnails really load, delete is a two-click confirm, and attaching one puts a chip in the composer |
| `ui_06` | measured layout: a long job name does not push the row's stop/delete button out of view, and the orbital/mode viewers' controls sit in the viewer's own corner |
| `ui_07` | measured click targets: every part of a Job Manager row that is not a button opens the job's preview on the first click, and the checkbox, rename and delete buttons act on the row instead of opening it |
| `ui_11` | the appearance panel: four themes, five accents, five text sizes, density and motion all reach the DOM, survive a reload, and are applied before the first paint. It loads the page with the JS bundle blocked to prove the last of those, which is the only observable form of the claim |
| `ui_12` | the sidebar keeps Knowledge base, Files and Projects reachable with 26 conversations seeded, at the default text size and at the largest. Deletes every conversation it creates, including on failure |
| `ui_13` | a drawer's `+` button while the drawer is shut opens the drawer *and* shows the form, and the collapsed instrument dock's icons reach their own panels |
| `ui_14` | every colour pair the interface draws, checked numerically in all four themes: AA, and AAA on the Contrast theme. Status hues and the accent are checked as text, not only as fills |

`deploy_01`..`deploy_03` and `install_01`..`install_02` are the five scripts
here that need no stack at all. They read and run shell out of
`scripts/update.sh`, `scripts/install.sh` and `scripts/lib/common.sh`, so they
work in a bare checkout with nothing running.

```
  frontend/
    run_frontend.mjs              runs tests/frontend/*.spec.mjs
    fe_sec_*.spec.mjs             bug-proving Playwright scenarios
    p1_*.spec.mjs                 admin console (invites) + account panel
    draft_01, fail_01, grad_02,   one script each, added alongside the
    opt_02, p7_05, p8_03, up_02,  feature they cover
    plots_01, ui_06, ui_07,
    ui_11..ui_14

    brand_sheet.mjs               renders docs/brand-sheet.png
    ui_shots.mjs                  screenshot sweep, docs/e2e-artifacts/ui/
```

The last two are deliberately **not** named `*.spec.mjs`. `run_frontend.mjs`
runs every spec in that directory in sequence, and neither of those asserts
anything: one draws the mark at every size it is used at, the other photographs
the app in each theme and at both ends of the text-size range. They exist
because a passing assertion cannot tell you that a panel is ugly, that a hue
did not survive a theme swap, or that a row stopped fitting at the largest text
size, and those are the failures a visual change is most likely to produce. Run
them at a phase gate and look at the pictures:

```bash
node tests/frontend/brand_sheet.mjs
QC_AGENT_TEST_BASE_URL=https://127.0.0.1:8444 node tests/frontend/ui_shots.mjs
```

Note there is a **third** runner beyond `run_backend.sh` and
`run_frontend.mjs`: `node tests/e2e/ui/run_ui.mjs` drives
`tests/e2e/ui/*.spec.mjs`, which includes the admin console's visual/section
coverage. A change to the console's sections has to be reflected there too --
`ui_04_admin_visual.spec.mjs` asserts on the exact set of section headings.

Two of those specs had drifted behind the app and were repaired during the
2026-09 fix phase (R-100's step), because each was reporting a failure against
a panel that was working correctly:

- `ui_03_molecule_kb.spec.mjs` looked for a bare
  `input[placeholder="Search sources..."]` in the knowledge-base panel. The
  search field moved behind a magnifier toggle (`SearchToggle` in
  `frontend/src/app-shell/SearchField.tsx`) and is not in the DOM until that
  toggle is clicked, so the spec now clicks `[data-testid="kb-search-open"]`
  first and then types into `input[data-testid="kb-search"]`. Every panel with
  a search field follows the same `<testId>-open` toggle plus `<testId>` input
  pattern, so a new panel's spec should be written that way from the start.
- `ui_04_admin_visual.spec.mjs` expected the overview pane to show a "Public
  web access" heading. That control was removed from the console, so the
  expectation was simply stale; the pane now owns only the storage quota and
  concurrency block. The same step added the "Deployment" section, which was
  added to the nav after the spec was written and had no coverage.
