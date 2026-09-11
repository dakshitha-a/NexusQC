# Audit: `server/` (area slug `server`)

Scope covered: `server/main.py`, `server/sse.py`, `server/schemas.py`,
`server/admin_cli.py`, all twelve routers under `server/routes/`, the one
middleware (`app/auth/middleware.py`), and the app-side helpers those routes
reach (`app/auth/ownership.py`, `app/auth/deps.py`, `app/auth/db.py`,
`app/auth/redis_session.py`, `app/uploads/store.py`, `app/plots/store.py`,
`app/rag/web_scrape.py`, `app/chemistry/jobs/base.py` path handling,
`app/chemistry/spectrum.py`). 103 route handlers inventoried (101 in
`routes/` plus `/api/health` and `/api/version` in `main.py`).

---

### R-000: An `async def` middleware makes a blocking Postgres call on the event loop for every request
- surface: code:server
- class: bug
- severity: S1
- cause: CODE
- confidence: suspected (code read)
- found by: audit:server
- scope: `app/auth/middleware.py`'s `AccessControlMiddleware.dispatch`, which is the only middleware in the app and is mounted on every request when `QC_AGENT_DATABASE_URL` is set (`server/main.py:139`). Checked every handler under `server/routes/` for `async def` first: there are **none**, so the rule is honoured at the route layer. This is the one place it is not.
- repro: With the compose stack up, `docker compose pause postgres` (a pause, not a stop, so TCP hangs rather than refusing), then request anything. Every request, including an open SSE stream's next write, stalls together. Or, less destructively: add a `time.sleep(2)` inside `models.get_app_config` and watch two concurrent `curl /api/health` serialize.
- observed: `dispatch` is `async def` (it must be, `BaseHTTPMiddleware` requires it) and calls `_maintenance_mode()` inline:
  ```python
  if _maintenance_mode():
  ```
  which does
  ```python
  value = bool(models.get_app_config("maintenance_mode", False))
  ```
  and `models.get_app_config` (`app/auth/models.py:901`) is
  ```python
  with get_pool().connection() as conn:
      row = conn.execute("SELECT value FROM app_config WHERE key = %s", (key,)).fetchone()
  ```
  a synchronous psycopg call. The module's own comment states the wrong model of where it runs: `"This runs on EVERY request on a sync path"` (`app/auth/middleware.py:52`). It does not run on a sync path; `BaseHTTPMiddleware.dispatch` runs on the single asyncio event loop.
- expected: `docs/ARCHITECTURE.md`'s "Every route handler is a plain `def`" section says an `async def` that blocks "stalls the single event loop, including SSE delivery to every other open connection", and records the KB-upload route being converted for exactly this reason. The same reasoning applies verbatim to middleware, which runs on the loop unconditionally. `CLAUDE.md` states the rule without a middleware carve-out.
- evidence: `app/auth/middleware.py:52-72` (the TTL cache and `_maintenance_mode`), `app/auth/middleware.py:80` (`async def dispatch`), `app/auth/middleware.py:127` (`if _maintenance_mode():`), `app/auth/models.py:901-904`.
- pointer: The 2-second TTL bounds the *frequency* to one round trip per 2 s, not the *duration* of any one of them. Three separate unbounded waits exist inside that call: `ConnectionPool.connection()` defaults to `timeout=30.0` on pool exhaustion; the DSN built in `app/auth/db.py:328-333` sets **no** `connect_timeout`, so a black-holed TCP connect waits out the OS default; and no `statement_timeout` is set, so a slow query waits forever. The `except Exception` in `_maintenance_mode` fails open on an *error* but a *hang* never raises. Additionally, `get_pool()` is lazy and `lifespan` never warms it, so the very first request after startup executes the whole `_SCHEMA` DDL block (`app/auth/db.py:334-337`, several hundred lines of `CREATE TABLE`/`ALTER TABLE`) on the event loop.
- note: Would be settled by timing `/api/health` while Postgres is paused, or by instrumenting the loop with `asyncio.get_event_loop().slow_callback_duration`. Fix direction: run the whole `_maintenance_mode()` check in a thread (`await anyio.to_thread.run_sync(...)`), or move it to a pure-ASGI middleware wrapping a sync callable, or refresh the cache from the existing background thread in `lifespan` rather than from the request path. Independently: add `connect_timeout` and a `statement_timeout` to the DSN, and warm the pool in `lifespan`.

---

### R-000: `POST /api/threads/{id}/troubleshoot/{job_id}` reads any user's failed job into the caller's conversation
- surface: code:server
- class: security
- severity: S1
- cause: CODE
- confidence: suspected (code read)
- found by: audit:server
- scope: `server/routes/chat.py:654-703`. Checked every other job-touching handler in the same file: `tag_job_frame` (chat.py:280) *does* call `check_owner_or_admin("job", ...)`, and the plot path is owner-scoped. This one is the outlier.
- repro: As user B, with any thread of B's own and the id of a *failed* job belonging to user A: `POST /api/threads/<B's thread>/troubleshoot/<A's job id>`. The 202 returns, and A's job's parameters plus a tail of its engine output appear in B's conversation.
- observed:
  ```python
  def troubleshoot_job(thread_id: str, job_id: str, request: Request):
      _require_thread(thread_id, request)
      text = compose_troubleshoot_message(job_id)
  ```
  `_require_thread` checks the *thread*'s ownership only (`chat.py:94-97`). `job_id` is never checked. `compose_troubleshoot_message` (`app/agent/troubleshoot.py:95-119`) then reads that job's `result.json`, `spec.json`, its parameters and `raw_output_tail(job_id)`, and embeds them into a `HumanMessage` that is persisted into the caller's own LangGraph checkpoint.
- expected: `docs/ARCHITECTURE.md`'s "Multi-user deployment / Security findings that shaped the code" makes cross-user resource reads the class of bug that shaped this layer (SEC-06, the artifact route). Ownership must be checked on the *object being read*, not on an unrelated object the caller happens to own. `tag_job_frame` in the same file is the correct pattern.
- evidence: `server/routes/chat.py:655-677`:
  ```python
  @router.post("/api/threads/{thread_id}/troubleshoot/{job_id}", status_code=202)
  def troubleshoot_job(thread_id: str, job_id: str, request: Request):
      ...
      _require_thread(thread_id, request)
      text = compose_troubleshoot_message(job_id)
  ```
  versus `server/routes/chat.py:279-280`:
  ```python
      _require_thread(thread_id, request)
      check_owner_or_admin("job", body.job_id, current_user_or_none(request))
  ```
- pointer: The `check_owner_or_admin("job", job_id, current_user_or_none(request))` line is simply missing. It is also worth noting the disclosure is *persisted*: the text goes into the checkpoint, so deleting the offending job afterwards does not remove the leaked output from B's history.
- note: `tests/e2e/e2e_03_route_auth_sweep.py` cannot catch this. Its pass 3 (cross-user) probes only thread-scoped routes (the `probes` list at line 306 is eight `/api/threads/{tid}/...` entries); user B is never pointed at user A's *job* id anywhere in the suite. Fix: add the one `check_owner_or_admin` call, and extend pass 3 with A-owned job ids.

---

### R-000: `POST /api/threads/{id}/messages` injects any job's full results into the caller's conversation via unchecked `job_ids`
- surface: code:server
- class: security
- severity: S1
- cause: CODE
- confidence: suspected (code read)
- found by: audit:server
- scope: `server/routes/chat.py:385-431` (`_run_turn` / `_attached_job_messages`) reached from `post_message` (`chat.py:631`). `MessageIn.job_ids` is `list[str] = []` with no validator (`server/schemas.py:27-32`).
- repro: As user B: `POST /api/threads/<B's thread>/messages` with `{"text":"summarise the attached job","job_ids":["<A's job id>"]}`. `job_context_summary` for A's job is prepended as a synthetic `HumanMessage`, sent to the model, and persisted in B's checkpoint; the model then reports A's numbers back to B.
- observed:
  ```python
  def _attached_job_messages(state: dict, job_ids: list[str] | None) -> list:
      ...
      messages.append(HumanMessage(content=f"{prefix} {job_context_summary(jid)}"))
  ```
  No ownership check anywhere on the path from `body.job_ids` to `job_context_summary(jid)`. Contrast the plot branch three lines below, which *is* owner-scoped:
  ```python
  HumanMessage(content=f"(attached plot, not typed by the user) "
                       f"{plot_context_summary(owner_user_id, pid)}")
  ```
- expected: same as the finding above. `job_context_summary` (`app/chemistry/jobs/summarize.py:390`) returns the job's spec line, its full summary table, geometries, spectra and children, described in `chat.py:340` as "around 20,000 characters of numeric tables". That is the whole scientific content of somebody else's calculation.
- evidence: `server/routes/chat.py:361`; `server/routes/chat.py:437-440` (the owner-scoped plot comparison); `server/schemas.py:27-32` (`job_ids: list[str] = []`, no cap, no validation).
- pointer: `job_ids` has no length cap either, so a single request can enumerate every job id on the deployment (obtainable, for an unowned job, straight from `GET /api/jobs`) and pull all of their summaries in one turn. That is also an unbounded prompt-size and unbounded work amplifier, independent of the disclosure.
- note: Same fix and same test gap as the troubleshoot finding: check each id with `check_owner_or_admin("job", jid, user)` in `post_message` (in the request thread, where `request` still exists) before spawning `_run_turn`, and cap the list length in `MessageIn`. Filing separately from troubleshoot because the entry points and the fix sites differ.

---

### R-000: `POST /api/kb/sources/text` writes an attacker-named file anywhere the app user can write
- surface: code:server
- class: security
- severity: S1
- cause: CODE
- confidence: suspected (code read)
- found by: audit:server
- scope: `server/routes/kb.py:181-196`. Compared against `_find_source_file` in the same module (`kb.py:100-114`), which *does* sanitise with `Path(source).name` and then re-checks the resolved parent. The write path has neither.
- repro: As any signed-in user:
  ```
  POST /api/kb/sources/text
  {"doc_type":"manual","filename":"../../jobs/<some job id>/result.json","text":"{\"status\":\"completed\",\"summary\":{\"total_energy_hartree\":-76.0}}"}
  ```
  `UPLOADS_DIR` is `data/uploads` and `JOBS_DIR` is `data/jobs` (`app/config.py:45,47`), so from `data/uploads/<uid>/` the path `../../jobs/<id>/result.json` lands exactly on another user's job result.
- observed:
  ```python
  filename = body.filename or _synthesize_filename(body.text)
  (_upload_dir(owner) / filename).write_text(body.text)
  ```
  `body.filename` is `str | None` on the pydantic model (`kb.py:163`) with no validator, no extension allowlist (unlike `add_source` two functions up), and no `Path(...).name`. The write happens before `ingest_text` runs, so a later `ValueError` -> 400 does not undo it.
- expected: A user-supplied name must never become a path segment. `bugs.py:271` states the rule for this codebase explicitly: *"The stored name is generated here. The uploaded filename is attacker-controlled and is never used as a path segment"*. `kb.py`'s own read path already applies `Path(source).name`.
- evidence: `server/routes/kb.py:160-163` (`filename: str | None = None`, no validator), `server/routes/kb.py:186-190`:
  ```python
  filename = body.filename or _synthesize_filename(body.text)
  # Written to disk (not just the vector store) so it shows up uniformly
  # alongside file uploads for list_sources/delete_source, ...
  (_upload_dir(owner) / filename).write_text(body.text)
  ```
- pointer: This is an S1 under the brief's own definition, not merely "a file write": the reachable target set includes `data/jobs/<id>/result.json` and `status.json`, i.e. **a fabricated scientific result presented to another user as correct**. Two amplifiers worth checking together:
  (a) `data/spec.json` is writable this way, and `DELETE /api/jobs/{job_id}` accepts `job_id=".."` (uvicorn percent-decodes the path before Starlette routes it, verified by reading `uvicorn.protocols.http.h11_impl`: `path = unquote(raw_path.decode("ascii"))`, so `DELETE /api/jobs/%2E%2E` yields `job_id=".."`). `remove_job` then needs only `read_spec("..")` non-None (= `data/spec.json` exists), and `mgr.status("..")` returns `{"status": "unknown"}` (`app/chemistry/jobs/base.py:1814`) which is **not** in `NON_TERMINAL_STATUSES`, so the 409 gate passes and `delete_job_dir("..")` reaches `shutil.rmtree(JOBS_DIR / "..")` — the whole `data/` tree. `check_owner_or_admin("job", "..", user)` waves it through because there is no ownership row for `..`.
  (b) `.env` sits at the project root, one level above `data/`.
- note: The nginx `location /api/` block uses `proxy_pass` with no URI component (`nginx/nginx.conf:91-94` includes `proxy_common.conf`), so per nginx's documented behaviour the request URI is forwarded as sent by the client, `%2E%2E` included. That part is inference from the nginx contract, not tested. Fix: `filename = Path(body.filename).name` plus an extension allowlist, and independently reject a `job_id` that is not the 12-hex-char shape `JobManager` mints.

---

### R-000: `POST /api/kb/sources` writes the raw multipart filename into a path
- surface: code:server
- class: security
- severity: S1
- cause: CODE
- confidence: suspected (code read)
- found by: audit:server
- scope: `server/routes/kb.py:139-157`. Same module as the finding above; filed separately because the input channel (a multipart header) and the constraint (a four-extension allowlist) differ.
- repro: A multipart POST whose part carries `Content-Disposition: form-data; name="file"; filename="../../../../etc/whatever.txt"` and `doc_type=manual`.
- observed:
  ```python
  suffix = Path(file.filename or "").suffix.lower()
  if suffix not in ALLOWED_FILE_EXTENSIONS: ...
  owner = _owner_key(request)
  dest = _upload_dir(owner) / file.filename
  dest.write_bytes(file.file.read())
  ```
  Only the *suffix* is validated; the rest of the name goes straight into the join.
- expected: as above. Starlette does not sanitise `UploadFile.filename`. Read directly from the installed `starlette 1.6.0` (`inspect.getsource(starlette.formparsers)`), the only handling is:
  ```python
  if b"filename" in options:
      filename = _user_safe_decode(options[b"filename"], self._charset)
  ```
  a charset decode, no path handling.
- evidence: `server/routes/kb.py:143-151`.
- pointer: The write is constrained to `.pdf/.txt/.md/.docx` (`ALLOWED_FILE_EXTENSIONS`), which rules out overwriting `result.json`, but not overwriting a pre-seeded manual under `data/scraped/`, nor dropping a file into any writable directory the container reaches.
- note: Same fix (`Path(file.filename).name`). `tests/backend/e2e_10_kb_lifecycle.py` and `sec_06_ownership_sweep.py` exercise this route but only with ordinary filenames.

---

### R-000: The `spin` query parameter on the orbital-cube route builds a filesystem path unvalidated
- surface: code:server
- class: security
- severity: S2
- cause: CODE
- confidence: suspected (code read)
- found by: audit:server
- scope: `server/routes/jobs.py:699-795`. Checked the sibling `gbw` parameter on the same route, which *is* allowlisted.
- repro: On a job the caller owns whose engine is `orca` (so the cube is produced by `orca_plot` and then renamed into place):
  `POST /api/jobs/<own job id>/orbitals/1/cube?spin=../../<victim job id>/mo_idx1`
  writes into another user's job directory. `spin` is a query parameter, so unlike a path parameter it is not constrained by Starlette's `[^/]+` segment matching.
- observed:
  ```python
  cube_key = f"idx{index}" + (f"_{spin}" if spin else "") + (f"_{gbw_filename}" if gbw is not None else "")
  ...
  cube_path = job_dir / f"mo_{cube_key}.cube"
  ```
  and later, on the ORCA branch, `Path(raw_cube).replace(cube_path)`; on the molden branch, `molden_tools.cube_for_orbital(molden_path, index, str(cube_path), spin=spin)`.
  Verified the join resolves outside the job directory (`python3 -c` with `pathlib`, not run against the app):
  `Path('/data/jobs/abc123') / 'mo_idx1_../../../../tmp/pwned.cube'` -> resolves to `/data/tmp/pwned.cube`.
- expected: The route's own docstring states the rule and applies it to the *other* client-supplied parameter, twelve lines above the unvalidated one: *"`gbw` ... Strictly allowlist-validated against `_GBW_NAME_RE` before ever touching the filesystem, since it's client-supplied and otherwise builds a path directly."* `spin` is equally client-supplied and equally builds a path directly.
- evidence: `server/routes/jobs.py:725-729` (the gbw docstring), `server/routes/jobs.py:739-742` (the gbw check), `server/routes/jobs.py:744` and `server/routes/jobs.py:759` (spin, unchecked, in the path).
- pointer: The suffix is forced to `.cube` and the content is a cube file, so this is a scoped write rather than arbitrary content; it is still a cross-user write into `JOBS_DIR/<someone else>/`, and a `mo_idx*.cube` planted in another job's directory will be picked up by that job's own download zip (`download_job` zips every file in the directory) and by its artifact listing once cached.
- note: The molden branch raises before writing for a restricted (non-UHF) molden with a junk `spin`, so the repro should use an ORCA job. Fix: validate `spin` against `{"alpha", "beta"}`, which is the only vocabulary `cube_for_orbital` understands (`app/chemistry/jobs/molden.py:119`).

---

### R-000: `POST /api/kb/sources/url` fetches an arbitrary URL before it checks who is calling
- surface: code:server
- class: security
- severity: S2
- cause: CODE
- confidence: suspected (code read)
- found by: audit:server
- scope: `server/routes/kb.py:224-262` and `app/rag/web_scrape.py`. Checked the other two KB POSTs: `add_source` resolves `_owner_key` after only a cheap extension check, and `add_text_source` after only a `doc_type` check; neither does I/O before authenticating. This one does two outbound HTTP requests.
- repro: `curl -k -X POST https://<host>:8444/api/kb/sources/url -H 'Origin: https://<host>:8444' -H 'Content-Type: application/json' -d '{"url":"http://ollama:11434/","doc_type":"manual","ignore_robots":true}'` **with no session cookie**. The middleware only checks `Origin`, not auth, so the request reaches the handler; `robots_disallows` and `fetch_page` both run; the 400 body then reports the target's HTTP status or Content-Type, or the connection error.
- observed: the handler's order of operations is
  ```python
  if body.doc_type not in ("manual", "paper"): ...        # line 227
  if not body.ignore_robots:
      reason = robots_disallows(body.url)                  # line 235 -- outbound GET
  ...
  title, text, html = fetch_page(body.url)                 # line 246 -- outbound GET
  owner = _owner_key(request)                              # line 250 -- FIRST auth check
  ```
  `_owner_key` -> `current_user_or_none` -> `get_current_user`, which is what raises 401, and it is reached only after both fetches.
- expected: Every other route in the app resolves the caller first. `server/routes/registry.py`'s docstring records the standard the project holds itself to: *"'everything requires a session except this one route nobody remembered' is not a posture to turn a public listener on top of."* An unauthenticated request must not be able to make the server issue outbound HTTP.
- evidence: `server/routes/kb.py:227-250` (the ordering above); `app/rag/web_scrape.py:88-99` — the only restriction is `re.match(r"^https?://", url)` and `"text/html" not in content_type`; there is no host, port or private-address restriction. Errors are surfaced verbatim: `raise ScrapeError(f"Fetching {url} returned HTTP {resp.status_code}")` and `f"{url} is not an HTML page (Content-Type: {content_type or 'unknown'})"`, both turned into a 400 detail at `kb.py:248`.
- pointer: Two distinct problems. (a) The auth check is in the wrong place, making this an *unauthenticated* SSRF. (b) Even authenticated, there is no egress restriction, so the compose network (`postgres:5432`, `redis:6379`, `ollama`/`host.docker.internal:11434`, `api:8000`) and the host's own loopback are reachable, and the differentiated 400 messages make it a working port/service scanner. Timeouts *are* present (20 s / 5 s), so this is not a hang risk.
- note: `tests/e2e/e2e_03_route_auth_sweep.py` cannot catch (a): its pass 1 posts `VALID_BODIES.get(tmpl, {})`, and this template has no entry, so an empty `{}` fails pydantic validation with a 422 before the handler body runs — the sweep records a non-2xx and passes. This is also the only route in the whole inventory with **zero** direct test coverage (`grep -rlF "sources/url" tests/` -> 0 files). Fix: move `_owner_key(request)` to the first line of the handler, and add an allowlist or private-address rejection in `fetch_page`.

---

### R-000: The Redis session client has no socket timeout, and it is on the path of every authenticated request
- surface: code:server
- class: bug
- severity: S2
- cause: CODE
- confidence: suspected (code read)
- found by: audit:server
- scope: `app/auth/redis_session.py:40`, reached from `app/auth/deps.py:47` (`is_active_session`) which every `get_current_user` call runs, which every `current_user_or_none` call runs, which is on essentially every route in the inventory. Checked the other outbound clients named in the brief; see the "clean" list below.
- repro: `docker compose pause redis` (pause, not stop) and then issue authenticated requests. Each one occupies a threadpool worker indefinitely; after the anyio default of 40, the API answers nothing at all, including `/api/health`.
- observed:
  ```python
  _client = redis.Redis.from_url(REDIS_URL, decode_responses=True)
  ```
  No `socket_timeout`, no `socket_connect_timeout`, no `health_check_interval`. redis-py's default `socket_timeout` is `None`, i.e. block forever.
- expected: `docs/ARCHITECTURE.md`'s "Three outbound calls needed explicit timeouts" states the principle: *"Anything that runs inside a graph turn can hold that thread's lock for as long as it hangs."* Redis is a fourth such call, and it is worse placed than the three that were fixed — it is not on the graph path but on the *authentication* path, so it gates every request rather than one tool.
- evidence: `app/auth/redis_session.py:40`; `app/auth/deps.py:45-51`:
  ```python
  if not is_active_session(user_id, session_id):
      raise HTTPException(status_code=401, detail="session superseded or expired")
  ```
- pointer: A refused connection fails fast and is fine; a black-holed connection (network partition, a paused container, an overloaded Redis) is the hang case. Same shape as the psycopg pool having no `connect_timeout` (noted under the middleware finding).
- note: Confirm by pausing the container and timing one request. Fix: `redis.Redis.from_url(REDIS_URL, decode_responses=True, socket_timeout=2, socket_connect_timeout=2)`, and decide deliberately whether a Redis timeout should fail closed (401) or open — failing closed logs everyone out, so a short retry then 503 is probably right.

---

### R-000: Every open SSE stream permanently occupies one of anyio's 40 default threadpool tokens
- surface: code:server
- class: perf
- severity: S2
- cause: CODE
- confidence: suspected (code read)
- found by: audit:server
- scope: `server/sse.py:107-124` (`event_stream`) plus `server/routes/chat.py:728-731` (`get_events`). This engages `sse.py`'s own documented decision to use `queue.Queue` rather than `asyncio.Queue`; the queue choice is right for the publishers, the cost is on the consumer side.
- repro: Open 40 concurrent `curl -N https://<host>/api/threads/<id>/events` (they need not be distinct threads), then time `curl /api/health`. Expect it to hang rather than answer.
- observed: `event_stream` is a plain synchronous generator handed to `StreamingResponse`. Starlette drives a sync iterator via `iterate_in_threadpool`, i.e. one `anyio.to_thread.run_sync(next, iterator)` per yielded item, on the process-wide default thread limiter (40 tokens). Each `next()` blocks in
  ```python
  event = q.get(timeout=_KEEPALIVE_SECONDS)
  ```
  for up to 15 seconds, so a stream holds a token essentially continuously. Those are the *same* 40 tokens FastAPI uses to run every plain `def` route handler in this app — which is all of them.
- expected: The architecture's whole reason for the plain-`def` rule is that a stalled request must not take SSE delivery down with it. The inverse coupling exists too and is not addressed anywhere: SSE streams and route handlers share one fixed-size pool. There is no `anyio` limiter tuning anywhere in the repo (`grep -rn "total_tokens\|to_thread\|limiter" --include=*.py .` finds nothing in app code).
- evidence: `server/sse.py:113-118`; `server/routes/chat.py:731`:
  ```python
  return StreamingResponse(event_stream(thread_id), media_type="text/event-stream")
  ```
  `frontend/src/lib/sse.ts:17` confirms the multiplier: *"One EventSource per mounted thread; torn down and reopened whenever threadId changes"*, so roughly one stream per open browser tab.
- pointer: Two other handlers make the ceiling easier to hit than the tab count alone suggests: `get_orbital_cube` runs `subprocess.run(..., timeout=300)` on a request thread, which `app/chemistry/jobs/orca_runner.py:1691-1693` acknowledges in a comment (*"this one runs in the API process on a request thread ... outside the job admission gate"*), and `download_project`/`download-my-data` hold a token for the whole download.
- note: This is a scalability ceiling on a lab-shared deployment, not a today-crash — say so when triaging. Confirm with the 40-stream test above. Fix directions: make `event_stream` an async generator that awaits `asyncio.to_thread(q.get, ...)` under its own dedicated `CapacityLimiter`, or bridge `hub.publish` into an `asyncio.Queue` with `loop.call_soon_threadsafe`, or simply raise the default limiter's `total_tokens` in `lifespan` and document why.

---

### R-000: `plt.subplots`/`plt.rc_context` are called from concurrent request and orchestrator threads with no lock
- surface: code:server
- class: bug
- severity: S3
- cause: CODE
- confidence: suspected (code read)
- found by: audit:server
- scope: reached from `POST /api/jobs/{job_id}/render_plot` (`server/routes/jobs.py:559-619`) and from the plot tools and scan/ensemble orchestrator threads. Area overlap: `app/chemistry/spectrum.py` is chemistry-layer, so the chemistry auditor may see this too.
- repro: Fire two `POST /api/jobs/<id>/render_plot` for different `kind`s at the same time (they land on two threadpool workers) and compare the PNGs against sequential renders.
- observed: every renderer in `app/chemistry/spectrum.py` uses the pyplot state machine:
  ```python
  with plt.rc_context(st.rc()):
      fig, ax = plt.subplots(figsize=st.figsize)
      ...
      plt.close(fig)
  ```
  at lines 115, 209, 269, 339, 416, 504, 592, 664. There is no lock in the module (`grep -n "_lock\|threading" app/chemistry/spectrum.py` -> no hits). `plt.rc_context` mutates the process-global `matplotlib.rcParams` and restores it on exit, so two threads with different styles interleave: the second entry overwrites the first's params and the first exit restores the second's.
- expected: matplotlib documents pyplot as not thread-safe. A figure produced under another render's rcParams is a chart with the wrong fonts, sizes or colours — and the project treats a chart as a scientific artifact (`docs/ARCHITECTURE.md`'s "One style vocabulary, and why the defaults are load-bearing").
- evidence: `app/chemistry/spectrum.py:8-9` (`matplotlib.use("Agg")`, `import matplotlib.pyplot as plt`) and the eight `plt.rc_context` / `plt.subplots` sites listed above; `server/routes/jobs.py:587-602` (three call sites in one handler).
- pointer: The failure mode is a cosmetically wrong plot, not a wrong number, which is why S3 rather than S1 — but `plt.subplots` also registers the figure in a global manager, so a crash or a leaked figure is possible too.
- note: Fix is cheap: a module-level `threading.Lock()` around each render, or the object-oriented API (`Figure()` + `FigureCanvasAgg`) with an explicit `rcParams` dict, which needs no global state at all.

---

### R-000: Six list routes return the whole collection with no limit or pagination
- surface: code:server
- class: perf
- severity: S3
- cause: CODE
- confidence: suspected (code read)
- found by: audit:server
- scope: filed as one entry rather than six. Checked every list-shaped route in the inventory; the bounded ones are named below so this is not read as blanket criticism.
- repro: Seed a few thousand jobs (`tests/` has a seeding path used for the storage-report measurement quoted in `storage_quota.usage_report`'s docstring) and watch `GET /api/jobs` on a 3-second poll from three tabs.
- observed, unbounded:
  - `GET /api/jobs` (`jobs.py:243`) — walks all of `JOBS_DIR` and returns one row per job, every poll, per tab. `_job_list_row` was already trimmed for exactly this reason, but the row *count* is still unbounded.
  - `GET /api/threads/{id}/state` (`chat.py:100`) — `serialize_state` returns the full message list for the conversation, with no windowing.
  - `GET /api/threads` (`threads.py:24`), `GET /api/kb/sources` (`kb.py:117`), `GET /api/uploads` (`uploads.py:48`), `GET /api/plots` (`plots.py:60`) — full collections.
  Bounded, and correctly so: `GET /api/admin/audit-log` (`LIMIT 500` in `models.list_audit_log`), `GET /api/jobs/{id}/children` (`_CHILDREN_PAGE_LIMIT_MAX = 500`, offset/limit), `GET /api/jobs/{id}/log` (`n = max(1, min(lines, 200))` plus a 64 KB tail window), `GET /api/admin/deploy/{id}` (log tailed to 20,000 chars).
- expected: `docs/ARCHITECTURE.md`'s "Polling is separated from expensive rendering" is about keeping each *row* cheap; it does not claim the list is bounded. `get_scan_children`'s own docstring shows the project already accepts offset/limit as the right shape when a list can be large.
- evidence: `server/routes/jobs.py:276` (`rows = [_job_list_row(job_id, spec) for job_id, spec in _iter_all_job_specs()]`); `server/routes/chat.py:104-107`; `server/routes/jobs.py:316` and `677` for the bounded counterexamples.
- pointer: `GET /api/jobs` is the one that matters, because it is polled. `GET /api/threads/{id}/state` is the one that grows without a ceiling for a single user, since a long conversation's message list only ever gets longer.
- note: Not urgent at current scale; worth a tracker item rather than a fix now. The cheapest change is offset/limit on `GET /api/jobs` mirroring `get_scan_children` exactly.

---

### R-000: `GET /api/jobs/{id}/neb_frames_live` reads and splits the whole trajectory file on every poll
- surface: code:server
- class: perf
- severity: S3
- cause: CODE
- confidence: suspected (code read)
- found by: audit:server
- scope: `server/routes/jobs.py:798-833`. Contrast `get_job_log` in the same file, which solves the identical problem correctly.
- repro: Run a `neb_ts` job with a large molecule and watch the handler's cost grow as `input_MEP_ALL_trj.xyz` grows; the frontend polls this while the job runs.
- observed:
  ```python
  text = all_trj_path.read_text()
  frames = orca_runner.split_xyz_frames(text)
  last_iteration = frames[-n_images_total:] if frames else []
  ```
  The whole file is read into memory and split into every frame, on every poll, in order to keep the last `n_images + 2`. The route's own docstring says the file *"genuinely grows by one full path's worth of frames every NEB iteration"*, so the cost grows linearly with iteration count while the poll rate stays constant.
- expected: `_tail_lines` (`jobs.py:625-642`), thirty lines earlier in the same module, exists precisely to avoid this: *"reads only the trailing max_bytes window"*.
- evidence: `server/routes/jobs.py:830-832`; `server/routes/jobs.py:625-639`.
- pointer: A trailing-window read sized at `n_images_total * (natoms + 2)` lines would give the same answer at constant cost.
- note: Only reachable for `neb_ts` jobs, which bounds the blast radius. Confirm by timing the route against a long NEB run.

---

### R-000: `PATCH /api/admin/bug-reports/{id}` returns 200 for a report that does not exist, and 500 for a malformed id
- surface: code:server
- class: bug
- severity: S3
- cause: CODE
- confidence: suspected (code read)
- found by: audit:server
- scope: `server/routes/admin.py:446-465`, and `DELETE /api/admin/bug-reports/{id}` (`admin.py:468-474`) has the same shape.
- repro: As an admin, `PATCH /api/admin/bug-reports/00000000-0000-0000-0000-000000000000 {"status":"closed"}` -> 200 with `{"id": ..., "status": "closed"}` and nothing written. Then `PATCH /api/admin/bug-reports/not-a-uuid` -> 500, because psycopg raises `InvalidTextRepresentation` on the UUID column.
- observed: the handler never looks the report up:
  ```python
  models.set_bug_report_status(report_id, body.status)
  models.audit(str(admin["id"]), "bug_report_status", target=report_id, details={"status": body.status})
  ...
  return {"id": report_id, "status": body.status, "archived": body.archived}
  ```
  and `models.set_bug_report_status` is a bare `UPDATE ... WHERE id = %s` (`app/auth/models.py:797-799`) whose zero-row result is discarded. `delete_bug_report` audits *before* deleting, so the audit log records a deletion that may not have happened.
- expected: `server/routes/shares.py:79-89` records the exact precedent and the reason: *"Without the parse, a hand-crafted request with a junk id reaches Postgres and raises InvalidTextRepresentation, which surfaces as a 500 -- an error shape that tells a prober their input got further than a well-formed miss would."* And a mutation that changed nothing should be a 404, not a 200 — this is the "swallow and return success" shape the brief asks about.
- evidence: `server/routes/admin.py:453-465`, `server/routes/admin.py:472-473`, `app/auth/models.py:797-809`, `server/routes/shares.py:79-89`.
- pointer: Low impact (admin-only, and the console always passes ids it just listed), but it writes a misleading append-only audit row, and the audit log is documented as immutable and therefore has to be right.
- note: Fix: parse the UUID and `get_bug_report(report_id)` first, 404 if absent, audit after the write.

---

### R-000: Two error paths return an internal 500 carrying engine paths and stack text
- surface: code:server
- class: comfort
- severity: S3
- cause: CODE
- confidence: suspected (code read)
- found by: audit:server
- scope: `server/routes/jobs.py:769-770` and `server/routes/chat.py:882-883`. Checked the rest of the inventory for `detail=str(e)` on a 5xx; these two are the ones that carry more than a sentence.
- repro: `POST /api/jobs/<orca job>/orbitals/0/cube` (index 0 becomes `-1` on the way to `orca_plot`) and read the response body.
- observed:
  ```python
  except Exception as exc:
      raise HTTPException(status_code=500, detail=f"orca_plot failed: {exc}")
  ```
  `render_orbital_cube` builds that exception as
  ```python
  raise RuntimeError(
      f"orca_plot did not produce a cube for orbital {orbital_index_0based}. "
      f"stdout:\n{proc.stdout[-2000:]}\nstderr:\n{proc.stderr[-1000:]}")
  ```
  (`app/chemistry/jobs/orca_runner.py:1706-1710`), so up to 3 KB of ORCA's own output — which contains absolute deployment paths — reaches the browser. Separately, an out-of-range `index` is a client error but produces a 500 rather than a 400 (the molden branch correctly maps `ValueError` to 400 at `jobs.py:780-781`; the ORCA branch has no equivalent).
- expected: A client-supplied out-of-range index is a 400. An internal tool's raw stderr belongs in the server log, which `chat.py:882` already does correctly (`logger.exception(...)` before raising) and which this site does not do at all.
- evidence: `server/routes/jobs.py:767-770`; `server/routes/jobs.py:778-781` (the correct pattern, five lines below); `app/chemistry/jobs/orca_runner.py:1706-1710`.
- pointer: `index` is unvalidated on entry (no bound, no positivity check) on the ORCA branch; the molden branch validates inside `cube_for_orbital` (`app/chemistry/jobs/molden.py:128-130`).
- note: Fix: validate `index >= 1` at the route, log the exception, and return a short 500 detail.

---

### R-000: `_pop_cancel_event` can disarm the Stop button for a turn it does not belong to
- surface: code:server
- class: bug
- severity: S4
- cause: CODE
- confidence: suspected (code read)
- found by: audit:server
- scope: `server/routes/chat.py:53-66`, `chat.py:627`.
- repro: Start a turn, press Troubleshoot on a failed job in the same conversation before the first turn finishes (both go through `_run_turn`), then press Stop for the second one after the first completes.
- observed: `_pop_cancel_event(thread_id)` pops by thread id, not by identity:
  ```python
  def _pop_cancel_event(thread_id: str) -> None:
      with _cancel_lock:
          _cancel_events.pop(thread_id, None)
  ```
  so the first turn's `finally` removes whatever event is currently registered — which may be the second turn's. `stop_turn` then hits its documented no-op branch and silently does nothing.
- expected: The module already reasons about exactly this class of race (`_run_turn`'s docstring on why the event is registered synchronously in the request thread). The stated assumption — *"Only one turn can be in flight per thread at a time (the composer disables sending while turnInProgress)"* — is a frontend guarantee, and `troubleshoot_job` and the job watcher's background turns are not the composer.
- evidence: `server/routes/chat.py:49-52` (the assumption), `chat.py:64-66`, `chat.py:627`.
- pointer: `_cancel_events.pop(thread_id, None)` should be conditional on the stored event being the one this turn registered (`if _cancel_events.get(tid) is ev: del ...`).
- note: Cosmetic in practice; the user presses Stop again and the turn ends on its own. Worth a one-line fix while the file is open.

---

## What I checked and found clean

Recording these so the coordinator does not re-derive them.

- **No `async def` route handlers anywhere.** `grep -rn "async def" server/` returns exactly one function body: `lifespan` in `main.py:52`, which is correct (a lifespan hook must be async) and does no blocking work — it starts five background threads and yields. Every one of the 103 handlers is a plain `def`. The rule is violated only in the middleware (filed above).
- **`server/routes/jobs.py` is genuinely lock-free.** Traced every call out of the module, not just grepped for `read_state`: `thread_registry.get_thread` takes `app/agent/threads.py`'s own `_lock` over `threads.json` and is documented as unrelated to the graph lock; `project_registry.job_project_map()` is a single flat-file read with no lock; `auth_models.all_owners` is one Postgres query; `usage_report()` (reached from `get_jobs_quota`) is TTL-cached; `result_artifact_transaction` takes a per-job file lock; `JobManager.status/result/cancel` are disk reads and a signal. Nothing touches `graph._graph_lock`. `projects.py` and `shares.py` hold the same property and say so in their docstrings; I confirmed neither imports from `app.agent.graph`.
- **`GET /api/jobs/{job_id}/artifacts/{key:path}` containment is sound.** The served path comes from the job's own `result.json`, and the defence-in-depth check is real: `Path(node).resolve(strict=True)` followed by `if not any(root in path.parents for root in (JOBS_DIR.resolve(), PLOTS_DIR.resolve()))` -> 403 (`jobs.py:868-882`). `resolve(strict=True)` collapses `..` and follows symlinks *before* the parent check, so a symlinked artifact is caught. The two-root allowlist is justified in the comment.
- **KB source *reading* is correctly sanitised.** `_find_source_file` (`kb.py:100-114`) strips with `Path(source).name`, then requires `resolved.parent == d.resolve()`. `_content_search_dirs` is the caller's own directory plus the shared corpus, per the F-022 fix recorded in its docstring.
- **Bug-report attachments.** Filename generated server-side, content type sniffed from magic bytes, `MAX_ATTACHMENTS`/`MAX_ATTACHMENT_BYTES` enforced with a `read(N+1)` so an oversized file is never fully buffered, all files validated before any is written, and the serving route is `require_admin` rather than `check_owner_or_admin` with a `.resolve()` containment check. This module is the model the two KB write routes should have followed.
- **Plot version paths.** `version` is a path parameter but is validated against the record: `if record is None or version not in record.get("versions", [])` (`app/plots/store.py:330`), so no traversal.
- **Path parameters cannot carry `/`.** I initially suspected `upload_id` and `plot_id` traversal, since `app/uploads/store.py:41-46` and `app/plots/store.py:86` both join them into paths with no sanitisation. They are not reachable: uvicorn percent-decodes before routing (`path = unquote(raw_path.decode("ascii"))` in `uvicorn.protocols.http.h11_impl`) and Starlette compiles `{upload_id}` to `(?P<upload_id>[^/]+)`, so `%2F` decodes to `/` and simply fails to match. Only `{key:path}` compiles to `.*`, and that one is validated. **This is why the `spin` finding matters and the id ones do not — `spin` is a query parameter.** Worth guarding the stores anyway, defensively, since a future non-path caller would not be protected.
- **nginx SSE configuration is right.** `nginx/proxy_common.conf:30-32`: `proxy_buffering off; proxy_read_timeout 3600s; chunked_transfer_encoding on;`, applied to all of `/api/` rather than only the events path, which `nginx/nginx.conf:27-33` explains. That comfortably outlasts the 15 s keepalive.
- **Outbound timeouts, all six the brief named.** PubChem: `socket.setdefaulttimeout(MOLECULE_LOOKUP_TIMEOUT)` scoped around the call with restore-on-exception (`app/chemistry/molecule.py:199-203`). OPSIN: `timeout=10` (`molecule.py:220-222`). DuckDuckGo: `DDGS(timeout=WEB_SEARCH_TIMEOUT)` (`app/agent/web_search.py:32`). Semantic Scholar: `timeout=SEMANTIC_SCHOLAR_TIMEOUT` (`app/agent/scholar_search.py:75`). Ollama chat: `timeout=150` on `ChatOpenAI` (`app/agent/graph.py:137`); Ollama embeddings: `client_kwargs={"timeout": OLLAMA_EMBEDDING_TIMEOUT}` (`app/rag/store.py:57-59`); Ollama warmer: `timeout=_REQUEST_TIMEOUT` (`app/agent/model_warmer.py:87`). Basis Set Exchange is a **fully offline library call** (`basis_set_exchange.get_basis`, `app/chemistry/jobs/bse_basis.py:48,80`), not an HTTP call at all. Web scraping: 20 s / 5 s. The two gaps are Redis and Postgres, both filed above.
- **The audit log is bounded and the admin user list projection is safe.** `models.list_audit_log(limit=500)` has a real `LIMIT`; `models.list_users` selects an explicit column list that excludes `password_hash` (`app/auth/models.py:106-112`), so `GET /api/admin/users` returning `{**u}` is not a hash leak.
- **`shares.py`.** UUID parsing before every DB lookup so a junk id 404s rather than 500s, terminality re-checked at accept, size recomputed rather than trusted from the offer row, compare-and-set on `pending` with rollback of the copy if the race is lost, and identical 404s for "not yours" and "does not exist". Nothing to file.
- **CSRF.** The missing-`Origin` case is rejected rather than allowed (`app/auth/middleware.py:88-90`), which is the documented SEC fix; the deployed-origin reconstruction from `X-Forwarded-Proto` + `Host` is sound given nginx is the only ingress.
- **Content-Disposition injection.** Every download header interpolates a slugified stem (`job_filename_stem`/`slugify_label`) or a regex-validated username (`_USERNAME_RE` in `auth.py:31`), so a free-text job, project or plot label cannot inject a header. Checked all nine download routes.

---

## Route inventory

103 handlers. Columns: **Auth** = requires a session when `QC_AGENT_DATABASE_URL` is set; **Admin** = `require_admin`; **Own** = performs an ownership check on the object it touches; **Tests** = number of files under `tests/` referencing that route's distinctive path segment.

Note on the Tests column: `tests/e2e/e2e_03_route_auth_sweep.py` enumerates the app's own `/openapi.json` and probes **every** route for anonymous rejection and (for `/api/admin/*`) non-admin 403, so no route is entirely unprobed for auth. A low or zero count here means "no *functional* test beyond that sweep". Its cross-user pass covers thread routes only.

| Method | Path | Auth | Admin | Own | Tests | Notes |
|---|---|---|---|---|---|---|
| GET | `/api/health` | no | no | n/a | 3 | deliberately public |
| GET | `/api/version` | no | no | n/a | 4 | deliberately public, documented in `main.py` |
| POST | `/api/auth/register` | no | no | n/a | 7 | invite-token gated, rate-limited |
| POST | `/api/auth/login` | no | no | n/a | 9 | rate-limited, timing-equalised |
| POST | `/api/auth/reset-password` | no | no | n/a | 1 | token is the auth; **not in the sweep's `PUBLIC_ROUTES`** |
| POST | `/api/auth/logout` | yes | no | self | 2 | |
| POST | `/api/auth/change-password` | yes | no | self | 5 | rotates the session |
| GET | `/api/auth/me` | yes | no | self | 37 | |
| POST | `/api/auth/purge-my-data` | yes | no | self | 2 | |
| GET | `/api/auth/download-my-data` | yes | no | self | 2 | streamed zip |
| POST | `/api/bug-reports` | yes | no | self | 2 | hard caps, magic-byte sniff |
| GET | `/api/threads` | yes | no | filtered | 17 | **unbounded list** |
| POST | `/api/threads` | yes | no | records | 17 | |
| PATCH | `/api/threads/{id}` | yes | no | yes | 17 | |
| PATCH | `/api/threads/{id}/pin` | yes | no | yes | 2 | |
| DELETE | `/api/threads/{id}` | yes | no | yes | 17 | frees checkpoints |
| GET | `/api/threads/{id}/state` | yes | no | yes | 17 | **unbounded message list** |
| POST | `/api/threads/{id}/messages` | yes | no | thread only | 17 | **`job_ids` unchecked and uncapped — S1 above** |
| POST | `/api/threads/{id}/troubleshoot/{job_id}` | yes | no | thread only | 4 | **`job_id` unchecked — S1 above** |
| POST | `/api/threads/{id}/stop` | yes | no | yes | 2 | |
| GET | `/api/threads/{id}/events` | yes | no | yes | 3 | SSE; **threadpool token per stream — S2 above** |
| POST | `/api/threads/{id}/approvals/job` | yes | no | yes | 6 | validates hand-edited input pre-resume |
| POST | `/api/threads/{id}/molecule/reset` | yes | no | yes | 1 | |
| POST | `/api/threads/{id}/molecule/build` | yes | no | yes | 2 | RDKit `ValueError` -> 400 |
| DELETE | `/api/threads/{id}/molecule/frames/{frame_id}` | yes | no | yes | **0** | no functional test |
| POST | `/api/threads/{id}/attach_upload` | yes | no | yes (both) | 4 | upload scoped to caller, tighter than admin-sees-all |
| POST | `/api/threads/{id}/tag_job_frame` | yes | no | yes (both) | 2 | correct two-object check |
| GET | `/api/threads/{id}/jobs` | yes | no | thread | 17 | |
| GET | `/api/jobs` | yes | no | filtered | many | **unbounded, polled** |
| GET | `/api/jobs/quota` | yes | no | self | 1 | |
| GET | `/api/jobs/{id}` | yes | no | yes | many | |
| PATCH | `/api/jobs/{id}` | yes | no | yes | many | |
| DELETE | `/api/jobs/{id}` | yes | no | yes | many | `job_id` shape unvalidated; see kb S1 amplifier (a) |
| POST | `/api/jobs/{id}/cancel` | yes | no | yes | 5 | |
| GET | `/api/jobs/{id}/children` | yes | no | yes | 4 | paginated, capped 500 |
| GET | `/api/jobs/{id}/wigner_transitions` | yes | no | yes | 2 | |
| GET | `/api/jobs/{id}/download` | yes | no | yes | 6 | buffers in memory — documented decision, not filed |
| GET | `/api/jobs/{id}/raw_input` | yes | no | yes | 2 | |
| POST | `/api/jobs/{id}/render_plot` | yes | no | yes | 2 | **pyplot global state — S3 above** |
| GET | `/api/jobs/{id}/log` | yes | no | yes | ~5 | bounded (200 lines / 64 KB) |
| POST | `/api/jobs/{id}/orbitals/{index}/cube` | yes | no | yes | 1 | **`spin` traversal — S2; `index` unvalidated; 500 leaks paths** |
| GET | `/api/jobs/{id}/neb_frames_live` | yes | no | yes | 1 | **whole-file read per poll — S3 above** |
| GET | `/api/jobs/{id}/artifacts/{key:path}` | yes | no | yes | 14 | containment verified clean |
| GET | `/api/kb/sources` | yes | no | filtered | 4 | unbounded |
| GET | `/api/kb/quota` | yes | no | self | 1 | |
| POST | `/api/kb/sources` | yes | no | writes as caller | 4 | **filename traversal — S1 above**; whole body buffered |
| POST | `/api/kb/sources/text` | yes | no | writes as caller | 2 | **filename traversal, any extension — S1 above** |
| POST | `/api/kb/sources/url` | **after the fetch** | no | writes as caller | **0** | **unauth SSRF — S2 above** |
| GET | `/api/kb/sources/{source}/content` | yes | no | dir-scoped | 4 | sanitised, clean |
| DELETE | `/api/kb/sources/{source}` | yes | no | dir-scoped | 4 | admin `?owner=` disambiguator |
| GET | `/api/uploads` | yes | no | filtered | 3 | unbounded |
| GET | `/api/uploads/quota` | yes | no | self | 1 | |
| POST | `/api/uploads` | yes | no | records | 3 | `file.file.read()` buffers up to `client_max_body_size` (512m) before validating |
| DELETE | `/api/uploads` | yes | no | self only | 3 | |
| DELETE | `/api/uploads/{id}` | yes | no | yes | 3 | |
| GET | `/api/uploads/{id}/content` | yes | no | yes | 3 | |
| GET | `/api/plots` | yes | no | filtered | 2 | unbounded; runs `sweep_orphans()` on every call |
| GET | `/api/plots/{id}` | yes | no | yes | 2 | |
| GET | `/api/plots/{id}/versions/{version}.png` | yes | no | yes | **0** | `version` validated against the record |
| GET | `/api/plots/{id}/download` | yes | no | yes | 2 | |
| PATCH | `/api/plots/{id}` | yes | no | yes | 2 | |
| DELETE | `/api/plots/{id}` | yes | no | yes | 2 | |
| GET | `/api/projects` | yes | no | filtered | 8 | |
| POST | `/api/projects` | yes | no | records + per-job | 8 | `_check_jobs` per id |
| POST | `/api/projects/purge-mine` | yes | no | self | 1 | refuses on a no-auth deployment |
| GET | `/api/projects/{id}` | yes | no | yes | 8 | |
| PATCH | `/api/projects/{id}` | yes | no | yes | 8 | |
| DELETE | `/api/projects/{id}` | yes | no | yes | 8 | `?delete_jobs=` explicit |
| POST | `/api/projects/{id}/jobs` | yes | no | yes (both) | 8 | |
| POST | `/api/projects/{id}/jobs/remove` | yes | no | project only | 2 | fine: only removes ids from a project you own |
| GET | `/api/projects/{id}/download` | yes | no | yes, per job | 8 | streamed; unreadable members skipped and named in the manifest |
| GET | `/api/job-registry` | yes | no | n/a | 2 | schema only; F-010 fix |
| GET | `/api/users/search` | yes | no | n/a | 1 | narrow projection, min-length gate |
| POST | `/api/shares` | yes | no | yes | 3 | |
| GET | `/api/shares/inbox` | yes | no | self | 2 | |
| GET | `/api/shares/outbox` | yes | no | self | 2 | |
| POST | `/api/shares/{id}/accept` | yes | no | party check | 3 | quota re-checked, CAS on pending |
| POST | `/api/shares/{id}/decline` | yes | no | party check | 1 | |
| POST | `/api/shares/{id}/withdraw` | yes | no | party check | 2 | |
| GET | `/api/admin/config` | yes | yes | n/a | 15 | |
| PATCH | `/api/admin/config` | yes | yes | n/a | 15 | key allowlist + range checks |
| GET | `/api/admin/storage` | yes | yes | n/a | 4 | TTL-cached |
| POST | `/api/admin/purge/jobs` | yes | yes | n/a | 8 | destructive; see the standing purge rule |
| POST | `/api/admin/purge/orphaned-jobs` | yes | yes | n/a | 3 | |
| POST | `/api/admin/purge/kb` | yes | yes | n/a | 1 | |
| POST | `/api/admin/purge/threads` | yes | yes | n/a | 2 | |
| GET | `/api/admin/audit-log` | yes | yes | n/a | 8 | `LIMIT 500` |
| GET | `/api/admin/users` | yes | yes | n/a | 25 | projection excludes `password_hash` |
| DELETE | `/api/admin/users/{id}` | yes | yes | last-admin guard | 25 | purges data first |
| PATCH | `/api/admin/users/{id}` | yes | yes | last-admin guard | 25 | clears the Redis session |
| POST | `/api/admin/invites` | yes | yes | n/a | 8 | `ttl_hours` unbounded (admin-only, not filed) |
| GET | `/api/admin/invites` | yes | yes | n/a | 8 | |
| POST | `/api/admin/invites/{token}/revoke` | yes | yes | n/a | 8 | |
| POST | `/api/admin/users/{id}/password-reset` | yes | yes | n/a | 2 | token never audited, correctly |
| GET | `/api/admin/password-resets` | yes | yes | n/a | 1 | |
| POST | `/api/admin/password-resets/{token}/revoke` | yes | yes | n/a | 1 | |
| GET | `/api/admin/bug-reports` | yes | yes | n/a | 3 | |
| PATCH | `/api/admin/bug-reports/{id}` | yes | yes | n/a | 3 | **no existence check, 500 on junk id — S3 above** |
| DELETE | `/api/admin/bug-reports/{id}` | yes | yes | n/a | 3 | audits before deleting |
| GET | `/api/admin/bug-reports/attachments/{id}` | yes | yes | admin-only by design | 1 | containment checked; regression test in `ui_06` |
| GET | `/api/admin/deployment` | yes | yes | n/a | 4 | |
| POST | `/api/admin/deploy` | yes | yes | n/a | 4 | action allowlist, id server-generated |
| GET | `/api/admin/deploy/{deploy_id}` | yes | yes | n/a | 4 | id alnum-checked, log tailed |
| GET | `/api/admin/activity` | yes | yes | n/a | 3 | one disk walk; not cached |
