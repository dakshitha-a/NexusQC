# Findings register

Every finding from the September 2026 app review, in the order it was found.
The schema, the severity scale and the list of things that are settled
decisions rather than findings are in [`README.md`](README.md). Read that
first; an entry filed against a settled decision costs the user triage time.

**This file is appended to as work happens, never written up at the end.**
The report is assembled from here, not from a session's scrollback, because a
session ends and the register does not.

IDs are assigned in order of discovery and never renumbered: the report, the
triage notes and the fix tracker all cite them.

## Index

Severities are the coordinator's, and are settled at P5.4. Everything below
came out of Phase 2 and has been verified to the level its `confidence` field
states. The 96 further findings the audit raised are not yet merged in; they
are in `evidence/audit/` and arrive as Phase 5 reproduces them.

| ID | Severity | Class | Surface | Title |
|---|---|---|---|---|
| R-001 | S1 | security | auth | any user can read and download another user's child jobs |
| R-002 | S1 | security | auth | a KB upload can write a file anywhere, and reach the host deploy runner |
| R-003 | S1 | security | server | two routes read any user's job into the caller's conversation |
| R-004 | S1 | bug | jobs | asking for L-PDFT silently runs plain DFT |
| R-006 | S2 | security | server | the URL ingest route fetches before it knows who is calling |
| R-007 | S2 | bug | server | a blocking database call runs on the event loop |
| R-005 | S3 | security | server | a path-safety control applied to one of two sibling paths, three times |
| R-008 | S3 | security | deploy | `/deploy-status/` serves the host path unauthenticated |

## Template

Copy this for each new entry. Delete the optional lines that do not apply.

```
### R-000: <the claim itself, as one line>
- surface:
- class: bug | security | perf | comfort | docs
- severity: S1 | S2 | S3 | S4
- cause: CODE | LLM | ENV | HARNESS
- confidence: confirmed k/N | suspected (code read) | not reproduced
- found by:
- scope:
- repro:
- observed:
- expected:
- evidence:
- pointer:
- note:
```

---

## Findings

The first entries came out of Phase 2's static audit, which ran early because
it is read-only and needed neither the stack nor the freeze. Each was then
verified by the coordinator rather than taken on the audit's word, and the
`confidence` field says exactly how far that verification got. The raw audit
output all six agents produced is kept under `evidence/audit/` so a reader can
check that nothing was dropped in the merge.

### R-001: any authenticated user can read and download another user's child jobs
- surface: code:auth
- class: security
- severity: S1
- cause: CODE
- confidence: confirmed 1/1 against the live deployment, with a real HTTP request
- found by: audit:auth, corroborated while taking the P0.5 snapshot
- scope: every per-job route, on all engines, for every task that produces
  children: `batch`, `pes_1d`, `interp_pes`, `wigner_spectra`, `geometry_set`.
  Verified on a `single_point/ee` child of a `wigner_spectra`-shaped master on
  PySCF. Not engine-specific: the gap is in the access check, not any runner.
- repro:
  1. Find a master with children. On this deployment, `186fe458ec9e`.
  2. Log in as any ordinary user who owns nothing. `qa_review`, created for
     this review, was minutes old.
  3. `GET /api/jobs/186fe458ec9e` -> **404**, correctly denied.
  4. `GET /api/jobs/0d87ea39ec68` (one of its children) -> **200**.
  5. `GET /api/jobs/0d87ea39ec68/download` -> **200**, 16,185 bytes.
- observed: the master is denied and its own child is served, to the same
  caller, in the same session, one request apart. The child hands over the
  17,365-byte job record, the engine log, and the full 16,185-byte artifact
  bundle. Confirmed in the database directly: `ownership_index` holds
  `186fe458ec9e -> c3038f42-...` for the master and **no row at all** for any
  of its eight children, against 36 job ownership rows in total, so the index
  is populated and it is specifically children that are missing from it.
- expected: a child should be as private as its parent. The effective owner is
  already computable and is already computed elsewhere in the same function:
  `JobManager.submit` enqueues with
  `owner_user_id or _queue_owner(spec.job_id, spec.to_dict())`, and
  `_queue_owner` (`app/chemistry/jobs/base.py:735-762`) walks `parent_job_id`
  to find it. The scheduler asks who a child belongs to; the access check does
  not.
- evidence: evidence/audit/auth.md, evidence/audit/_COORDINATOR_VERIFIED.md
- pointer: `app/chemistry/jobs/base.py:1198` records ownership only under
  `if owner_user_id:`, and children are submitted with `owner_user_id=None`
  (the code says so itself in a comment near line 1235).
  `app/auth/access.py::check_owner_or_admin` reads
  `if owner is not None and owner != str(user["id"]): raise 404`, so an absent
  owner falls through and the check passes.
- note: **This is not the settled "unowned jobs are visible to everyone"
  decision, and it must not be closed as one.** That decision, and the
  docstring implementing it, are about jobs "created before auth was
  configured on this deployment", which the docstring calls "legacy/unowned".
  These children are created now, on an authenticated deployment, by a parent
  with a perfectly good owner. Write access is in scope too: `PATCH` rename,
  `POST /cancel` and `DELETE` use the same check. Deletion does cascade
  correctly, so this is not a repeat of SEC-08.

### R-002: a knowledge-base upload can write a file anywhere, and reach the host deploy runner
- surface: code:auth
- class: security
- severity: S1
- cause: CODE
- confidence: confirmed by code read and by path arithmetic; NOT exploited
- found by: audit:auth, audit:server (filed three times between them)
- scope: both KB write routes. `POST /api/kb/sources/text` (JSON body, no
  extension check at all) and `POST /api/kb/sources` (multipart, extension
  checked but the path is still unsanitised). Not engine- or method-specific.
- repro: as any authenticated user, `POST /api/kb/sources/text` with
  `{"filename": "/app/data/deploy/request.json", "doc_type": "paper",
  "text": "{\"action\": \"rollback\"}"}`. Deliberately not executed here.
- observed: `add_text_source` does
  `(_upload_dir(owner) / filename).write_text(body.text)` with `filename`
  taken straight from a Pydantic `str | None` that has no validator. A
  `pathlib` join with an **absolute** string discards the left operand
  entirely, so no `../` is even required. Verified in isolation:
  `Path("/app/data/kb/uploads/user-123") / "/app/data/deploy/request.json"`
  is `/app/data/deploy/request.json`. The write also happens *before*
  `ingest_text`, so a request that then returns 400 has already left the file.
- expected: the same treatment the read path in this very module already
  gives. `server/routes/kb.py:101` carries the comment "Path(source).name
  strips any directory components a malicious/odd..." and lines 105-112 do
  `Path(source).name` plus a `resolved.parent == d.resolve()` containment
  check. The hazard was recognised and the defence was written; it was applied
  in one direction only.
- evidence: evidence/audit/_COORDINATOR_VERIFIED.md
- pointer: `server/routes/kb.py` `add_text_source` (~190) and `add_source`
  (~150); `_upload_dir` does `UPLOADS_DIR / owner` with no containment check.
- note: **The escalation is what sets the severity.** `data/` is bind-mounted
  into the api container (`.../NexusQC-dev-repo/data -> /app/data`, confirmed
  on this deployment), and `scripts/deploy_runner.sh` watches
  `data/deploy/request.json` at a fixed name, polls it every 3 seconds under
  `--watch` (line 230-233), reads `action`/`ref`/`drain`/`force` out of it
  (125-128), allows `report|update|rollback` (138), and then runs
  `bash scripts/update.sh` or `--rollback` **on the host** (198-216).
  `requested_by` is never read, so the file is the only authority, while the
  API route that normally creates it is admin-gated. Not currently live on
  this host: `deploy_runner.sh --watch` is not running, checked with `ps`. It
  completes on any deployment using the in-app update feature. Two independent
  fixes each break it: sanitise the filename, or have the runner verify the
  requester.

### R-003: two routes read any user's job into the caller's conversation
- surface: code:server
- class: security
- severity: S1
- cause: CODE
- confidence: confirmed by code read
- found by: audit:agent and audit:server, independently
- scope: `POST /api/threads/{id}/messages` via its `job_ids` body field, and
  `POST /api/threads/{id}/troubleshoot/{job_id}` via its path parameter. The
  same gap exists one layer down in the tool functions `check_job_status`,
  `plot` and `geometry_parameters`.
- repro: as an ordinary user, post a message to your own thread carrying
  another user's `job_ids`, then read the turn back from
  `GET /api/threads/{id}/state`. Not executed; R-001 already demonstrates the
  same class live.
- observed: both handlers call `_require_thread`, which checks the *thread*,
  and neither calls `check_owner_or_admin("job", ...)` on the job id it was
  handed. The results are then expanded into the conversation and into the
  model's context.
- expected: what `tag_job_frame` does twelve lines away in the same file, at
  `server/routes/chat.py:280`:
  `check_owner_or_admin("job", body.job_id, current_user_or_none(request))`
  on the line after `_require_thread`. `plot_ids` on the very same request is
  owner-scoped at `:438`. So two of the four job-ish inputs to this file are
  checked and two are not.
- evidence: evidence/audit/agent.md, evidence/audit/server.md
- pointer: `server/routes/chat.py:631` (`post_message`) and `:654`
  (`troubleshoot_job`).
- note: needs a known job id, so it is a boundary crossing rather than a
  browsing hole. `e2e_03_route_auth_sweep.py`'s cross-user pass probes thread
  routes only, which is why the standing suite does not catch it.

### R-004: asking for L-PDFT silently runs plain DFT
- surface: code:jobs
- class: bug
- severity: S1
- cause: CODE
- confidence: confirmed by executing the function
- found by: audit:jobs
- scope: `lpdft`, `l-pdft`, `pdft` and `tddft` all collapse to `dft`, and
  `hfx` to `hf`. Engine-independent: the substitution happens in parameter
  normalisation, before any runner sees it, so it affects PySCF, ORCA and
  BAGEL alike. `mcpdft`, `cmspdft`, `casscf`, `caspt2`, `nevpt2`, `ccsd`,
  `mp2`, `eom_ccsd`, `hf` and `dft` were all checked and are preserved.
- repro:
  ```bash
  PYTHONPATH=$PWD python3 -c "
  from app.chemistry.jobs.param_normalize import normalize_method
  print(normalize_method('lpdft'))"
  ```
- observed:
  ```
  ('dft', "Interpreted method 'lpdft' as 'dft' (restricted/unrestricted
   reference is chosen automatically from the molecule's spin, not from this
   parameter).")
  ```
- expected: `lpdft` passes through untouched. It is a real method with its own
  row in `app/chemistry/registry2/capabilities.py`, and
  `docs/QM_CAPABILITIES.md` documents it as the preferred multi-state MC-PDFT
  variant, the one to choose over plain MC-PDFT because it restores the
  correct topology where same-symmetry surfaces approach. The substitution
  therefore replaces a multireference treatment with a single-reference one,
  on the method the documentation steers people toward.
- evidence: evidence/audit/jobs.md, evidence/audit/_COORDINATOR_VERIFIED.md
- pointer: `app/chemistry/jobs/param_normalize.py:72` calls
  `difflib.get_close_matches(key, _METHOD_ALIASES.keys(), n=1, cutoff=0.75)`.
  `SequenceMatcher(None, "lpdft", "dft").ratio()` is **exactly 0.75**, so it
  meets the cutoff on the boundary; `tddft` against `dft` is also exactly
  0.75. The typo-repair path runs on input that was never a typo, because
  `lpdft` is simply not a key in `_METHOD_ALIASES` and the call site has no
  "is this already a known method?" short-circuit before the fuzzy match.
- note: three things make this worse than a wrong answer. The note attached to
  the substitution is **the wrong note**, written for the `rdft`/`udft`
  spelling variants, so the user is told something true-sounding about a
  different subject and the change of method reads as a benign normalisation;
  nothing anywhere says L-PDFT was not run. The two sibling pair-density
  methods behave correctly, which is exactly what would stop anyone noticing.
  And it contradicts a promise the repository makes twice: this module's own
  documentation says repair is never a guess at different chemistry, and
  `docs/ARCHITECTURE.md` has a "Parameter repair is narrow and verified"
  section saying the same.

### R-005: a path-safety control applied to one of two sibling paths, three times over
- surface: code:server
- class: security
- severity: S3 (as a theme; the individual instances are R-002 and the two below)
- cause: CODE
- confidence: confirmed by code read
- found by: coordinator, merging audit:server and audit:auth
- scope: three sites, all reached through **query parameters and request
  bodies** rather than path parameters. That distinction is load-bearing: a
  path parameter cannot carry a slash, because uvicorn unquotes and then
  Starlette matches `[^/]+`, which is why the `upload_id` and `plot_id` joins
  are safe and these are not.
- repro: see each instance below.
- observed: in all three cases the author identified the hazard, wrote a
  defence, left a comment explaining it, and applied it to one of the two
  places that needed it.
  1. **KB, read defended and write not.** R-002.
  2. **Orbital cube route, `gbw` validated and `spin` not.**
     `server/routes/jobs.py:700` takes both from the query string. The
     docstring says of `gbw`: "Strictly allowlist-validated against
     `_GBW_NAME_RE` before ever touching the filesystem, since it's
     client-supplied and otherwise builds a path directly." `spin` is the
     other client-supplied component of the same key and is validated nowhere.
     Line 744 builds `cube_key = f"idx{index}" + (f"_{spin}" if spin else "")
     + ...` and line 763 builds `cube_path = job_dir / f"mo_{cube_key}.cube"`.
  3. **The same route again, download name defended and real path not.** The
     comment at 745-747 says the download name is "slugified for one reason
     the others aren't: cube_key can carry the client-supplied `gbw`
     filename". So the author saw that `cube_key` carries client input and
     hardened the **cosmetic** surface, the filename the browser is offered,
     while the actual filesystem path built from the same unslugified
     `cube_key` two lines later was left alone.
- expected: the defence applied to both members of each pair.
- evidence: evidence/audit/_COORDINATOR_VERIFIED.md
- note: filed as one theme because the useful thing to tell a maintainer is
  the habit rather than three separate patches. Triage may prefer to split it;
  the instances are individually actionable. Instance 2 is independently at
  least S2 and is worth reproducing live in P5.

### R-006: the URL ingest route fetches an arbitrary URL before it knows who is calling
- surface: code:server
- class: security
- severity: S2
- cause: CODE
- confidence: confirmed by code read
- found by: audit:server, audit:auth
- scope: `POST /api/kb/sources/url`. Two outbound fetches, `robots_disallows`
  and `fetch_page`, both before any identity is established.
- repro: not executed. Executing it would mean making this host fetch a URL of
  my choosing, which is the thing the finding is about.
- observed: `server/routes/kb.py:224` is
  `def add_url_source(body, request)` with no auth dependency;
  `server/main.py:109` includes the router with no `dependencies=` list; and
  `AccessControlMiddleware` performs CORS/Origin and maintenance checks only,
  never authentication. Inside the handler, `robots_disallows(body.url)` then
  `fetch_page(body.url)` both run before `owner = _owner_key(request)`. No
  host restriction, and redirects are followed, so this reaches cloud
  metadata endpoints and anything else on the host network.
- expected: identity established first, then the fetch, with an egress
  restriction on the URL.
- evidence: evidence/audit/server.md, evidence/audit/auth.md
- note: one honest qualification, which is why this is S2 and not S1. The
  middleware's Origin check rejects a request with no `Origin` header, so a
  bare `curl` gets 403 before reaching the handler; an attacker who sets
  `Origin` to the deployment's own origin gets through. That makes it harder
  to reach than "anyone who can route to the host", but not authenticated,
  and the ordering inside the handler is wrong regardless.

### R-007: a blocking database call runs on the event loop, in an `async def` middleware
- surface: code:server
- class: bug
- severity: S2
- cause: CODE
- confidence: confirmed by code read; the frequency claim was measured and corrected
- found by: audit:server (as S1), audit:auth (as S2)
- scope: every request to the deployment, through
  `AccessControlMiddleware.dispatch`.
- repro: read `app/auth/middleware.py:86` (`async def dispatch`) and `:126`
  (`if _maintenance_mode():`), then follow `_maintenance_mode` to
  `models.get_app_config` to `get_pool().connection()`, a synchronous psycopg
  query.
- observed: a blocking Postgres round-trip on the single event loop, which is
  precisely what this codebase's plain-`def` rule exists to prevent. Every
  route handler in `server/` honours that rule correctly; the only `async def`
  there is `lifespan`. The middleware is where it breaks.
- expected: no blocking I/O on the loop. `CLAUDE.md` states the rule and says
  why: an `async def` that blocks stalls SSE delivery to every open tab.
- evidence: evidence/audit/server.md, evidence/audit/auth.md
- pointer: `app/auth/middleware.py:54,58,86,126`.
- note: **the server audit said this runs on every request; it does not, and
  the correction matters for severity.** `_maintenance_mode` is TTL-cached at
  `_MAINT_TTL_SECONDS = 2.0`, so the query runs at most once every two seconds
  and only for the request that finds the cache cold. Steady state that is a
  few tens of round-trips a minute against a local Postgres, which is small.
  The S1 tail is a slow or unreachable database: there is no `connect_timeout`,
  the pool timeout is 30 s, and a stall there freezes the whole event loop and
  every open SSE stream with it. Filed S2 with the tail stated. P4 should
  measure it rather than argue about it.

### R-008: `/deploy-status/` serves two fixed-name files, unauthenticated, one carrying the host path
- surface: code:deploy
- class: security
- severity: S3
- cause: CODE
- confidence: confirmed by code read
- found by: audit:deploy (as S4; raised here after reading the nginx comment)
- scope: `nginx/nginx.conf:98-109`, and the two files
  `scripts/deploy_runner.sh` writes at the top of `data/deploy`.
- repro: `curl -k https://<host>:8444/deploy-status/runner.json`, with no
  credentials.
- observed: nginx aliases the whole `data/deploy` directory to
  `/deploy-status/` with no auth and `autoindex off`. Its comment states the
  security model outright: "Nothing here should be browsable: the ids are the
  only thing keeping one run's log out of a casual reader's way." That holds
  for the per-run subdirectories, whose names are generated ids. It does not
  hold for the two files beside them at **fixed** names: `runner.json`
  (`deploy_runner.sh:53`), written by `touch_runner_state` as
  `{"alive_at": ..., "pid": ..., "repo": "$REPO_ROOT"}`, and `request.json`
  (`:52`). On this host `REPO_ROOT` is
  `/data/qcuser/9.NexusQC/NexusQC-dev-repo`, so the response hands out the
  operator's username and the host's filesystem layout.
- expected: either authentication on the location, or unguessable names for
  the two top-level files.
- evidence: evidence/audit/deploy.md, evidence/audit/_COORDINATOR_VERIFIED.md
- note: raised from the audit's S4 because an absolute host path with a
  username in it is exactly the class of string
  `scripts/check_public_safe.sh` exists to keep out of published files, and no
  scan can catch this one because it is generated at runtime rather than
  committed. Separately worth carrying into the fix plan: `request.json`'s
  fixed, documented name is what makes R-002's escalation aimable. Changing it
  would not fix R-002 but would remove the convenient target.

