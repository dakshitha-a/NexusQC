# Audit: multi-user layer (`code:auth`)

Read in full before filing: `docs/ARCHITECTURE.md` "Multi-user deployment"
(2083-2305) and "Sharing" (2624-2762), `tests/README.md`, `app/auth/*`,
`app/projects/*`, `app/uploads/*`, `app/rag/*`, `app/plots/*`,
`app/chemistry/jobs/quota.py`, and `server/routes/{admin,auth,kb,plots,projects,
shares,uploads,bugs,threads}.py` plus the ownership call sites in
`server/routes/{jobs,chat}.py`.

Nothing was executed. Every entry is a code read.

---

### R-000: KB ingest writes a caller-supplied filename straight into a path join, giving arbitrary file write (cross-user overwrite, and a non-admin route into the host deploy runner)

- surface: code:auth
- class: security
- severity: S1
- cause: CODE
- confidence: suspected (code read)
- found by: audit:auth
- scope: `POST /api/kb/sources/text` (JSON body, no extension check at all) and
  `POST /api/kb/sources` (multipart, extension restricted to
  `.pdf/.txt/.md/.docx`). `POST /api/kb/sources/url` is safe: its filename is
  derived server-side by `_filename_from_url`. `app/uploads/store.py` is safe:
  its filename is a generated `uuid4().hex[:12]` plus a whitelisted extension.
- repro: as any signed-in non-admin,
  `POST /api/kb/sources/text {"text":"x","doc_type":"paper","filename":"../<victim_uuid>/theirfile.txt"}`
  overwrites another user's KB upload; `"filename":"../../deploy/request.json"`
  with a JSON body writes a deployment request; an absolute
  `"filename":"/app/data/threads.json"` replaces the conversation registry.
  `write_text`/`write_bytes` do not create parent directories, so a reproducer
  needs the target directory to exist already: the victim must have uploaded at
  least once, and `data/deploy/` exists once the runner is installed or any
  admin has used the deploy panel. A false negative on a fresh stack is the
  missing directory, not a missing bug.
  Victim UUIDs are obtainable by any user from `GET /api/users/search`, which
  deliberately returns `id`.
- observed: `server/routes/kb.py:150` `dest = _upload_dir(owner) / file.filename`
  then `dest.write_bytes(file.file.read())`, and `server/routes/kb.py:186-190`
  `filename = body.filename or _synthesize_filename(body.text)` /
  `(_upload_dir(owner) / filename).write_text(body.text)`. Neither applies
  `Path(...).name`. Starlette does not sanitise `UploadFile.filename`
  (`starlette/formparsers.py:229` decodes the raw Content-Disposition value),
  and `AddTextSource.filename` is a bare `str | None` with no validator
  (`server/routes/kb.py:160-163`). `pathlib` join with an absolute string
  discards the left operand, so `/abs/path` works as well as `../`.
- expected: the same rule this codebase already states for the read/delete
  side. `app/rag/store.py:197` `name = Path(source).name  # never let a source
  name escape UPLOADS_DIR`, and `server/routes/kb.py:104-113` `_find_source_file`
  applies `Path(source).name` plus a resolve/parent check. Only the two write
  paths were left out.
- evidence: `server/routes/kb.py:149-151`
  ```
      owner = _owner_key(request)
      dest = _upload_dir(owner) / file.filename
      dest.write_bytes(file.file.read())
  ```
  `server/routes/kb.py:186-190`
  ```
      filename = body.filename or _synthesize_filename(body.text)
      (_upload_dir(owner) / filename).write_text(body.text)
  ```
- pointer: `UPLOADS_DIR = DATA_DIR / "uploads"` (`app/config.py:47`) and
  `DEPLOY_DIR = DATA_DIR / "deploy"` (`app/config.py:81`) are siblings, so
  `../../deploy/request.json` from `UPLOADS_DIR/<owner>/` lands exactly where
  `POST /api/admin/deploy` writes (`server/routes/admin.py:653-672`).
  `scripts/deploy_runner.sh:100-176` reads only `id`, `action`, `ref`, `drain`,
  `force` from that file and never looks at `requested_by`, so an ordinary user
  can trigger `update` or `rollback`. The `update` path is at least constrained
  to `origin/main`'s lineage (`deploy_runner.sh:163-171`); `rollback` carries no
  such check.
- note: three separate fixes, all cheap: `Path(x).name` on both write paths, a
  pydantic validator on `AddTextSource.filename`, and a `requested_by`/origin
  check in the runner (or a marker file only the api writes). Secondary damage
  worth stating: a traversal-written file is invisible to
  `delete_upload_file`/`upload_path`, which resolve by basename, so it can never
  be reclaimed by eviction, self-purge or account deletion. `sec_06`'s
  hand-verified route table covers kb.py but only for *ownership checks on
  reads*, not for what a write path does with a filename.

---

### R-000: a scan/ensemble master's child jobs carry no ownership row, so every per-job route -- read, rename, cancel and delete -- serves them to any signed-in user, and their bytes escape the owner's quota

- surface: code:auth
- class: security
- severity: S1
- cause: CODE
- confidence: suspected (code read)
- found by: audit:auth
- scope: `submit_scan`, `submit_wigner_ensemble` and the NEB/batch master
  submitters in `app/chemistry/jobs/base.py`; every `check_owner_or_admin("job",
  ...)` route in `server/routes/jobs.py`, read and write alike. Not checked
  against a live stack.
- repro: user A runs a PES scan. User B calls `GET /api/jobs/<child_id>`,
  `/log`, `/raw_input`, `/download` or `/artifacts/<key>` with a child id and
  gets A's frame data -- and `DELETE /api/jobs/<child_id>` removes a finished
  frame out of A's scan, while `POST /api/jobs/<child_id>/cancel` kills a
  running one mid-calculation, leaving A's `children.jsonl` and frame scrubber
  pointing at a directory that is gone. B needs the id, and disclosure is
  out-of-band: `GET /api/jobs/<master>/children` is guarded, so the id has to
  arrive by another route (a pasted log line, a support screenshot, an error
  message). If child ids share the 12-hex shape of the rest, guessing them over
  HTTP is infeasible; this is a boundary that is absent, not one that is
  cheaply crossed.
- observed: ownership is recorded for the master only.
  `app/chemistry/jobs/base.py:1314-1316` (and the identical blocks at 1394-1396,
  1466-1468) `if owner_user_id: ... record_ownership("job", master_spec.job_id,
  owner_user_id)`, with the docstring "Per-image sub-jobs are deliberately left
  unowned". `app/auth/ownership.py:55-59` then reads
  ```
      if user is None or user["role"] == "admin":
          return
      owner = models.get_owner(kind, resource_id)
      if owner is not None and owner != str(user["id"]):
          raise HTTPException(status_code=404, ...)
  ```
  so a resource with no row passes for everyone.
- expected: the architecture makes the children unowned for a specific,
  correct reason ("A master copies as a whole family, and its children stay
  unowned": an owned child would become an independent eviction candidate and
  quota pressure could punch a hole in a scan). That reason is about
  `_job_candidates`/`owner_filter`, not about read access. The same document
  names the opposite hazard twice, in "Bug-report attachments sit outside every
  existing regime" ("a resource with *no* ownership row is readable by
  **everyone**, not by no-one") and in `purge_user_data`'s docstring. The two
  decisions collide here.
- evidence: `app/chemistry/jobs/base.py:1296-1316`, `app/auth/ownership.py:46-59`,
  `server/routes/jobs.py:404/541/676/856` (reads) and `:412` (rename), `:421`
  (delete), `:435` (cancel) -- each the same `check_owner_or_admin("job",
  job_id, ...)` and nothing else. Confirmed by reading `remove_job` in full
  (`server/routes/jobs.py:417-428`): it special-cases `_NON_TERMINAL_STATUSES`
  but never `parent_job_id`.
- pointer: resolve `spec["parent_job_id"]` to the master and check the master's
  owner inside `check_owner_or_admin` (or in a small `_effective_owner` helper),
  rather than giving children rows of their own, which would reintroduce the
  eviction hazard the current design avoids. That helper already exists in
  spirit: `_queue_owner` (`app/chemistry/jobs/base.py:735-762`) does exactly
  this walk -- `get_owner("job", job_id)`, and on None fall back to the
  `parent_job_id`'s owner -- so the scheduler already knows a child's effective
  owner while the access check does not.
- note: two follow-ons in the same mechanism, both worth fixing together.
  (1) `_job_usage_by_owner` (`app/auth/storage_quota.py:92-101`) buckets every
  child into `unowned`, so a fifty-image Wigner ensemble counts nothing against
  its owner's `per_user_jobs_and_chat_quota_bytes` and only shows up in the
  global total. (2) Deletion is *fine*: `delete_job_dir` cascades to
  `sub_job_ids_of` (`app/chemistry/jobs/base.py:501-504`), so `purge_user_data`
  removing the master takes the children with it, and this is not a second
  SEC-08. Settle (1) and the read gap; leave deletion alone.

---

### R-000: `AccessControlMiddleware.dispatch` runs a synchronous Postgres query (and, on the first request of a process, the whole DDL schema) on the event loop

- surface: code:auth
- class: bug
- severity: S2
- cause: CODE
- confidence: suspected (code read)
- found by: audit:auth
- scope: every request to a deployment with `QC_AGENT_DATABASE_URL` set, safe
  methods included; the middleware is only mounted in that case
  (`server/main.py:143`).
- repro: restart the api container, then time the first request of any kind
  while an SSE stream is open in another tab. Or stop Postgres and watch every
  in-flight SSE delivery stall for up to the pool's connect timeout.
- observed: `app/auth/middleware.py:86` `async def dispatch(...)` calls
  `_maintenance_mode()` at line 126, which at line 63 calls
  `models.get_app_config("maintenance_mode", False)` -- plain psycopg through
  `get_pool()`, no thread offload. The 2-second TTL
  (`_MAINT_TTL_SECONDS = 2.0`, line 54) bounds the steady-state cost but not
  the cold or degraded one. Nothing in `server/main.py`'s `lifespan` warms
  `get_pool()` explicitly, so *if* nothing at startup has already touched the
  pool, the first request through this middleware executes `_SCHEMA`
  (`app/auth/db.py:29-306`, ~30 DDL statements including a DROP/ADD CONSTRAINT
  pair) inline on the loop. That precondition is not guaranteed: the
  scheduler's admission gate calls `get_app_config`/`get_owner`/`all_owners`
  (`app/chemistry/jobs/base.py:683-724`), so a deployment that re-enqueues an
  orphaned job at startup may pay the DDL on that thread instead. The
  steady-state and degraded-Postgres halves of this finding stand either way.
- expected: CLAUDE.md and `docs/ARCHITECTURE.md`'s "Every route handler is a
  plain `def`" both state the rule and the reason: "an `async def` that blocks
  stalls the single event loop, including SSE delivery to every other open
  tab." A `BaseHTTPMiddleware.dispatch` is on the same loop as the handlers it
  wraps.
- evidence: `app/auth/middleware.py:58-71`
  ```
  def _maintenance_mode() -> bool:
      now = time.monotonic()
      if now - float(_maint_cache["checked_at"]) < _MAINT_TTL_SECONDS:
          return bool(_maint_cache["value"])
      try:
          value = bool(models.get_app_config("maintenance_mode", False))
  ```
- pointer: the failure case is the one that bites. `psycopg_pool`'s
  `connection()` waits up to 30 s by default, and the moment this branch is
  live at all is `scripts/update.sh --maintenance`, i.e. exactly when Postgres
  is being recreated. Every open tab's stream stalls together.
- note: fix direction is either `await run_in_threadpool(_maintenance_mode)` or
  refreshing the flag from a background thread and having `dispatch` read a
  plain in-memory variable. Warming `get_pool()` in `lifespan` is worth doing
  regardless, so the DDL is paid at startup rather than by the first user.

---

### R-000: `enforce_all_quotas()` re-walks all storage once per user per pass, and runs inside `JobManager.submit()`

- surface: code:auth
- class: perf
- severity: S3
- cause: CODE
- confidence: suspected (code read)
- found by: audit:auth
- scope: every job submit, every KB ingest, every geometry upload, plus the
  watcher's ~5-minute tick (`app/agent/job_watcher.py:146,450-452`).
- repro: seed N accounts and M jobs, then submit one job and time
  `JobManager.submit()`. `perf_02_admin_storage_latency.py` already measured the
  single-pass walk at ~343 ms median at 1,000 jobs and up to ~2 s at 5,000; this
  path pays that N times.
- observed: `app/auth/storage_quota.py:633-650` is three separate
  `for u in models.list_users():` loops, each rebuilding a candidate list from
  scratch inside the loop:
  ```
      for u in models.list_users():
          uid = str(u["id"])
          kb_candidates = _kb_candidates(owner_filter=uid)
      ...
      for u in models.list_users():
          combined = _job_candidates(owner_filter=uid) + _thread_candidates(owner_filter=uid)
  ```
  `_kb_candidates` calls `list_sources()` (a full Chroma `store.get`) with the
  filter applied *in Python* after the fetch (line 477-481). `_job_candidates`
  walks every job directory, calls `models.all_owners("job")` and
  `project_registry.job_project_map()` (line 373-376) -- all three per user.
  `_thread_candidates` calls `all_thread_checkpoint_bytes()` (a Postgres
  aggregate over the checkpoint tables) per user, line 518.
- expected: each of those sources is owner-independent. Build the candidate
  lists once, group by owner, then run the per-user passes over the groups. The
  admin read path already got this treatment (`usage_report`'s TTL cache); the
  write path did not.
- evidence: `app/auth/storage_quota.py:633-655`, `app/chemistry/jobs/quota.py:101-103`
  (`if DATABASE_URL: ... return enforce_all_quotas()["evicted_jobs"]`), called
  from `JobManager.submit()` under `_quota_lock`.
- pointer: the cost is serialised against every other submit by `_quota_lock`,
  so with a handful of accounts and a few thousand jobs this is seconds of
  added submit latency, not milliseconds. `docs/ARCHITECTURE.md` already records
  a ~4 s cold submit for this reason in the SEC-07 write-up.
- note: one grouped pass would be a mechanical rewrite of that block with no
  behaviour change. Confirm by timing `enforce_all_quotas()` against a seeded
  stack with 1 user vs 10.

---

### R-000: the per-user quota pass measures only *evictable* bytes, so a user over quota on running jobs, pinned threads, plots or scan children is never brought back under

- surface: code:auth
- class: bug
- severity: S3
- cause: CODE
- confidence: suspected (code read)
- found by: audit:auth
- scope: `enforce_all_quotas`'s three per-user passes. The global pass (line
  652-655) is correct: it takes its total from `usage_report()`.
- repro: give one user a pinned conversation plus a few finished jobs adding to
  more than `per_user_jobs_and_chat_quota_bytes`. `GET /api/admin/storage` shows
  them over; the enforcement pass computes a smaller total and evicts nothing,
  or stops early.
- observed: `app/auth/storage_quota.py:645-650`
  ```
      combined = _job_candidates(owner_filter=uid) + _thread_candidates(owner_filter=uid)
      _evict_oldest_first(
          combined, cfg["per_user_jobs_and_chat_quota_bytes"], sum(c["size"] for c in combined), evicted
      )
  ```
  `current_total` is `sum(c["size"] for c in combined)`. `_job_candidates`
  admits terminal jobs only (line 381) and `_thread_candidates` skips pinned
  threads (line 521). Meanwhile the figure the console and
  `GET /api/kb|uploads/quota` display for the same cap,
  `usage_report()["per_user"][i]["jobs_and_chat_bytes"]`, counts every job
  directory regardless of status (line 92-94), every plot (line 110-114) and
  every thread with checkpoint rows (line 176-181).
- expected: the two numbers should be the same quantity. Either the pass starts
  from the real usage figure and evicts what it can (correct, and it already
  degrades gracefully when candidates run out), or the displayed figure is
  narrowed to match.
- evidence: `app/auth/storage_quota.py:238-260` vs `645-650`.
- pointer: pass the user's real `jobs_and_chat_bytes` in as `current_total`
  instead of the candidate sum. Same for the KB and uploads passes, which have
  the milder version of the problem (their candidate sets are nearly complete).
- note: this is under-enforcement, never over-eviction, which is the safe
  direction -- but it means the per-user cap silently does not hold for the
  exact users who are hardest on storage. Related: R-000 on unowned scan
  children, which is a second reason a user's real footprint exceeds what this
  pass sees.

---

### R-000: accepting two shares concurrently is a check-then-act with no lock, and this is the one quota path that never evicts, so the overage is permanent

- surface: code:auth
- class: bug
- severity: S3
- cause: CODE
- confidence: suspected (code read)
- found by: audit:auth
- scope: `POST /api/shares/{id}/accept`. Not the upload/ingest paths, where the
  same race self-corrects because the following `enforce_all_quotas()` evicts.
- repro: two pending offers, each just under the recipient's headroom. Accept
  both at once from two tabs.
- observed: `server/routes/shares.py:227-237`
  ```
      incoming = sum(job_family_size_bytes(j) for j in live)
      ok, why = storage_quota.fits_for_user(me, incoming)
      if not ok:
          raise HTTPException(status_code=409, detail=why)
      ...
      for job_id in live:
          new_id = copy_job(job_id, me, shared_from=sender)
  ```
  `fits_for_user` -> `headroom_for_user` -> `_compute_usage_report()` is a read
  with no lock, and the copy that follows is not serialised against another
  accept. `set_share_status`'s compare-and-set only protects *the same* share
  row, not two different ones.
- expected: `docs/ARCHITECTURE.md`, "An offer is a row; accepting is what spends
  storage": "Accepting therefore checks headroom first and **refuses** rather
  than evicting... deleting the recipient's own oldest results to make room
  would be a stranger reaching into their account." Because nothing evicts here,
  a raced pair leaves the recipient permanently over their cap with no path that
  corrects it -- the per-user pass will then start deleting their own oldest
  jobs on their next submit, which is precisely the outcome the refuse-don't-
  evict rule exists to prevent.
- evidence: `server/routes/shares.py:224-239`, `app/auth/storage_quota.py:288-342`.
- pointer: a per-recipient lock (or an advisory lock keyed on the user id) held
  across check-and-copy. `_compute_usage_report()` is already ~200 ms-2 s, so
  the window is wide, not theoretical.
- note: `share_04_quota_refusal.py` covers the sequential refusal, not the
  concurrent one. Confirm with two simultaneous accepts and a `GET
  /api/admin/storage` afterwards.

---

### R-000: `GET /api/auth/download-my-data` omits conversations, plots, projects and scan frames -- most of what the same account's quota counts

- surface: code:auth
- class: bug
- severity: S3
- cause: CODE
- confidence: suspected (code read)
- found by: audit:auth
- scope: the whole route. The three categories it does include (owned jobs, KB
  uploads, geometry uploads) look correct.
- repro: run a PES scan, save a plot, hold a conversation, then download the
  zip. The scan's frames, the plot PNG and every message are absent.
- observed: `server/routes/auth.py:275-308` enumerates exactly
  `all_owners("job")` filtered to the caller, `list_uploads(owner_filter=user_id)`
  and `list_sources(owner_filter=user_id)`. There is no
  `thread_registry.list_threads()`/checkpoint export, no
  `plot_store.list_plots(owner_filter=...)` and no project manifest. Sub-job
  directories are absent for a different reason: `all_owners("job")` returns
  every job that has an ownership row, and a master's children have none.
- expected: the same account's quota bills them for chat history
  ("a combined per-user job-artifacts-plus-chat-history quota (one shared pool,
  since both are 'this user's own activity')") and for plots
  (`app/plots/store.py:362-376`, counted in the job category). A "download all
  my data" control that omits the largest categories it charges for is a
  GDPR-shaped feature that does not do what its label says.
- evidence: `server/routes/auth.py:279-308`.
- pointer: threads are the awkward one -- they live behind `graph.py`'s
  `_graph_lock`, and this router must not take it. A JSON export of
  `thread_registry.list_threads()` plus the serialised messages the SSE layer
  already renders would cover it without the lock; at minimum the response
  should say what it does not contain.
- note: `dz_01_self_purge.py` covers the purge half of the danger zone, not the
  download half's completeness.

---

### R-000: an upload or KB source larger than the caller's own quota is written, returned as 201, and then deleted by the same request's eviction pass

- surface: code:auth
- class: bug
- severity: S3
- cause: CODE
- confidence: suspected (code read)
- found by: audit:auth
- scope: `POST /api/uploads` and the three `POST /api/kb/sources*` routes. Same
  shape for a single job whose directory exceeds the cap, though a job is only
  reached by a later submit.
- repro: with `per_user_uploads_quota_bytes` at its 512 MB default, upload a
  600 MB `.xyz`. Expect 201, then `GET /api/uploads` shows nothing.
- observed: `server/routes/uploads.py:76-83` writes first
  (`record = add_upload(...)`), records ownership, then calls `enforce_quota()`,
  and returns `record` regardless of what eviction did.
  `_evict_oldest_first` (`app/auth/storage_quota.py:582-589`) sorts candidates
  by `created_at` and keeps evicting `while current_total > cap_bytes and i <
  len(candidates)` -- the just-written item is last in that order, so once
  everything older is gone it is evicted too.
- expected: either refuse up front when a single item cannot fit (the
  non-evicting `fits_for_user` already exists for exactly this shape of
  decision, on the share path), or report in the response what was evicted. A
  201 naming an id that 404s on the next request is the worst of the three.
- evidence: `server/routes/uploads.py:72-83`, `server/routes/kb.py:139-157`,
  `app/auth/storage_quota.py:570-590`.
- pointer: also note the write itself is unbounded --
  `content = file.file.read()` (`server/routes/uploads.py:75`) and
  `dest.write_bytes(file.file.read())` (`kb.py:151`) buffer the whole body in a
  threadpool worker, with nginx's `client_max_body_size 512m` as the only
  ceiling.
- note: at exactly the limit the behaviour is consistent and correct
  (`>` in both `_evict_oldest_first` and `fits_for_user`), so this is only about
  a single oversized item.

---

### R-000: a KB upload that fails ingestion leaves its bytes on disk, invisible to every accounting path

- surface: code:auth
- class: bug
- severity: S3
- cause: CODE
- confidence: suspected (code read)
- found by: audit:auth
- scope: `POST /api/kb/sources` (and `/text`, `/url`, which write before
  `ingest_text` the same way).
- repro: upload a scanned PDF with no extractable text. The route answers 400
  (`ValueError` from `_extract_text`/`ingest_text`), and the file stays under
  `UPLOADS_DIR/<owner>/`.
- observed: `server/routes/kb.py:150-155`
  ```
      dest = _upload_dir(owner) / file.filename
      dest.write_bytes(file.file.read())
      try:
          n_chunks = ingest_file(dest, doc_type, owner=owner)
      except ValueError as e:
          raise HTTPException(status_code=400, detail=str(e))
  ```
  No cleanup on the failure branch.
- expected: `_kb_candidates` and `_kb_usage_by_owner` both enumerate from
  Chroma (`app/auth/storage_quota.py:477`, `129-134`), so a file with no chunks
  is counted by no quota, listed by no route, and reclaimed by no eviction --
  the exact F-001 shape the codebase already fixed once on the delete side.
- evidence: `server/routes/kb.py:152-155`; `app/auth/storage_quota.py:470-491`.
- pointer: `dest.unlink(missing_ok=True)` in the `except`. Only
  `orphaned_upload_files()` (run by account deletion and self-purge) ever finds
  these, and repeated failed uploads accumulate until then.
- note: cheap and self-contained. Same three lines needed in `/text` and `/url`.

---

### R-000: an admin cannot preview any per-user KB file, contradicting the route's own contract

- surface: code:auth
- class: bug
- severity: S3
- cause: CODE
- confidence: suspected (code read)
- found by: audit:auth
- scope: `GET /api/kb/sources/{source}/content` for an admin caller only. A
  non-admin's own files and the shared corpus both resolve correctly.
- repro: as admin, `GET /api/kb/sources` (unfiltered, shows every user's
  sources), then request `/content` for one belonging to another user. Expect
  404.
- observed: `_owner_filter` returns `None` for an admin
  (`server/routes/kb.py:60-63`), and `_content_search_dirs(None)` returns
  `[_upload_dir(None)] + list(_SCRAPED_DIR.glob("*"))` -- i.e. `UPLOADS_DIR`
  itself plus the seeded corpus (lines 94-97). An owned upload lives at
  `UPLOADS_DIR/<owner_id>/<name>`, one level deeper, and `_find_source_file`
  requires `resolved.parent == d.resolve()` (line 112), so it never matches.
- expected: the docstring says "The `owner is None` branch (admin, or a
  no-auth deployment...) is deliberately left alone: UPLOADS_DIR itself is that
  branch's own directory, and an admin is meant to see everything." The second
  half of that sentence is not what the code does.
- evidence: `server/routes/kb.py:94-97, 100-114`.
- pointer: for the `None` branch, extend the search to
  `[d for d in UPLOADS_DIR.iterdir() if d.is_dir()]` as well as `UPLOADS_DIR`
  itself. Note this is the *pre*-F-022 behaviour, which is correct for an admin
  and was wrong only for an ordinary user, so restoring it must stay inside the
  `owner is None` branch.
- note: low blast radius (admin-only, read-only), but it means the admin
  console lists sources it cannot open.

---

### R-000: an unreachable Redis turns every authenticated request into a 500, while the rate limiter next to it deliberately fails open

- surface: code:auth
- class: bug
- severity: S3
- cause: CODE
- confidence: suspected (code read)
- found by: audit:auth
- scope: every route that resolves a user, i.e. everything except
  `/api/health` and `/api/version`.
- repro: `docker compose stop redis`, then load the app. Expect 500s rather
  than a bounce to the login screen.
- observed: `app/auth/deps.py:47` `if not is_active_session(user_id,
  session_id):`, and `app/auth/redis_session.py:55-56`
  `return get_client().get(_key(user_id)) == session_id` with no try/except --
  a `redis.ConnectionError` propagates out of `get_current_user` as a 500.
  `app/auth/rate_limit.py:80-82` takes the opposite posture for the same
  dependency: "a Redis blip must degrade to 'no rate limiting' for a few
  seconds, not 'no one can log in'".
- expected: `redis_session.py`'s own module docstring says "if Redis is
  restarted/flushed, the worst case is every logged-in user gets treated as
  'already superseded' on their next request and has to log in again". That is
  a 401, which the frontend's global auth-error handler already turns into a
  login redirect. A 500 is neither that nor the rate limiter's fail-open.
- evidence: `app/auth/redis_session.py:55-56` vs `app/auth/rate_limit.py:75-82`.
- pointer: catch the connection error in `is_active_session` and return False
  (fail closed as a 401), which matches the documented worst case exactly.
- note: `conf_04_pool_redis_cold_start_race.py` covers the concurrent
  *construction* of the client, not an unavailable server, so this is
  uncovered. A cold-but-reachable Redis (flushed) is already handled correctly:
  `get` returns None, the comparison fails, 401.

---

### R-000: `GET /api/admin/activity` walks every job's `status.json` and `spec.json` on every poll, uncached

- surface: code:auth
- class: perf
- severity: S3
- cause: CODE
- confidence: suspected (code read)
- found by: audit:auth
- scope: the admin console's deployment panel, which polls this while open.
- repro: seed a few thousand jobs, open the panel, watch the request time.
  `perf_02_admin_storage_latency.py`'s own figures for a comparable walk
  (~343 ms at 1,000 jobs, ~2 s at 5,000) are the right order of magnitude.
- observed: `server/routes/admin.py:761-768`
  ```
      for job_id in _iter_job_ids_on_disk():
          try:
              state = (read_status(job_id) or {}).get("status")
              if state not in ("running", "pending"):
                  continue
              if is_master_spec(read_spec(job_id)):
  ```
  Two JSON reads per job on disk, with no cache, plus `models.all_owners` twice
  and `models.list_users()`.
- expected: the neighbouring `GET /api/admin/storage` was given a 20 s TTL cache
  for exactly this reason (`usage_report`'s docstring, and
  `ADMIN_STORAGE_CACHE_TTL_SECONDS`). This route answers a question that changes
  no faster.
- evidence: `server/routes/admin.py:750-782`; `app/config.py:675`.
- pointer: a short TTL cache, or restrict the walk to ids the scheduler already
  knows are non-terminal rather than rediscovering them from disk.
- note: read-only and admin-only, so it degrades a panel rather than the app.

---

### R-000: bug-report attachments are uncapped per account -- no quota, no rate limit, no ceiling on report count

- surface: code:auth
- class: security
- severity: S3
- cause: CODE
- confidence: suspected (code read)
- found by: audit:auth
- scope: `POST /api/bug-reports`. Authenticated, so this is an insider/compromised-
  account storage-exhaustion path, not an anonymous one.
- repro: loop `POST /api/bug-reports` with three 5 MB PNGs. 15 MB per call, no
  throttle, nothing counting it.
- observed: `server/routes/bugs.py:22-23` caps `MAX_ATTACHMENTS = 3` and
  `MAX_ATTACHMENT_BYTES = 5 * 1024 * 1024` *per report*. Nothing caps reports
  per user or per unit time, and by design these bytes live in
  `DATA_DIR/bug_reports/<id>/` where `usage_report()` never sees them. The only
  rate-limited routes in the app are login, register and password reset
  (`app/auth/rate_limit.py:90-104`).
- expected: `docs/ARCHITECTURE.md`, "Bug-report attachments sit outside every
  existing regime, on purpose": "The bound is a hard cap instead: images only,
  at most 3 per report, at most 5MB each, necessary, because
  `client_max_body_size` is 512m and would otherwise be the only limit on the
  route." The per-report cap is the stated bound; the per-account one is
  missing, so the aggregate is still unbounded.
- evidence: `server/routes/bugs.py:16-35, 69-124`.
- pointer: reuse `rate_limit.enforce` with its own bucket keyed on the user id
  rather than the IP, or refuse when the account already has N open reports.
  Not a quota -- the architecture's reason for keeping these out of the quota
  ("a bug report a user cannot file because they are near their storage cap is
  worse than the bytes it saves") is sound and should stand.
- note: the rest of this route is careful: magic-byte sniffing, server-generated
  stored names, validate-all-before-write, admin-only serving.

---

### R-000: `POST /api/kb/sources/url` fetches any URL the caller names, with no host restriction and redirects followed

- surface: code:auth
- class: security
- severity: S3
- cause: CODE
- confidence: suspected (code read)
- found by: audit:auth
- scope: `app/rag/web_scrape.py`'s `fetch_page` and `robots_disallows`, both
  reachable by any signed-in non-admin.
- repro: `POST /api/kb/sources/url {"url":"http://localhost:11434/","doc_type":"paper","ignore_robots":true}`,
  then read the stored page back through `GET /api/kb/sources/{source}/content`.
- observed: `app/rag/web_scrape.py:90-94` validates only the scheme
  ```
      if not re.match(r"^https?://", url, re.IGNORECASE):
          raise ScrapeError("URL must start with http:// or https://")
      resp = requests.get(url, headers=HEADERS, timeout=_TIMEOUT_SECONDS)
  ```
  No hostname/IP-literal check, and `requests` follows redirects by default, so
  a public URL can redirect to a loopback or link-local address.
- expected: an authenticated web app that fetches on the user's behalf should
  refuse private/loopback/link-local destinations, or resolve and pin the
  address before the request.
- evidence: `app/rag/web_scrape.py:83-106`; `server/routes/kb.py:245-262`.
- pointer: exfiltration is narrow -- the response must be `text/html` with
  >50 characters of extracted text (lines 98-119) -- so this is mostly an
  internal-service prober rather than a general read primitive. On this host
  there is no cloud metadata service to reach; on another deployment there
  might be.
- note: mitigating context worth recording rather than dismissing the finding:
  the compose network exposes little that answers HTML, and the caller must
  already have an account.

---

### R-000: `purge_own_data` leaves the caller's plots and projects behind, and the response counts do not mention them

- surface: code:auth
- class: comfort
- severity: S4
- cause: CODE
- confidence: suspected (code read)
- found by: audit:auth
- scope: `POST /api/auth/purge-my-data`. `purge_user_data` (account deletion)
  handles both correctly.
- repro: save a plot from a job, file that job into a project, then click
  "delete all my data". The response counts three categories, the project
  survives as an empty shell, and the Plots panel still lists the chart until
  the next `GET /api/plots` sweeps it.
- observed: `app/auth/storage_quota.py:921-925` builds job, KB and upload
  candidates only. `purge_user_data` beside it additionally deletes projects
  (lines 830-835) and plots (lines 849-856). The self-purge route reports
  `purged_jobs`/`purged_kb_sources`/`purged_uploads`
  (`server/routes/auth.py:236-241`) and says nothing about either.
- expected: the architecture's stated omission from `purge_own_data` is
  `_thread_candidates`, and only that: "The one deliberate omission is
  `_thread_candidates`". Plots and projects are not named as omissions.
- evidence: `app/auth/storage_quota.py:895-925` vs `768-892`.
- pointer: largely self-correcting for plots -- every source job is gone, so
  `sweep_orphans()` collects them on the caller's next `GET /api/plots`
  (`server/routes/plots.py:62`). The exception is a plot with an empty
  `job_ids`, which `sweep_orphans` never touches by design
  (`app/plots/store.py:392-395`). Projects survive as empty shells, since
  `delete_job_dir` -> `registry.prune_job` removes only the membership.
- note: file as tidy-up, not as data loss. The user-visible edge is a danger-
  zone action that reports "3 jobs purged" while the Plots panel still shows
  charts until the next visit.

---

### R-000: `revoke_session` is never called, so the `sessions` table only ever grows

- surface: code:auth
- class: comfort
- severity: S4
- cause: CODE
- confidence: suspected (code read)
- found by: audit:auth
- scope: `app/auth/models.py`'s sessions helpers and the `sessions` table. The
  Redis half of session handling is unaffected and is where enforcement
  actually lives.
- repro: `grep -rn revoke_session --include=*.py .` returns only the definition;
  `SELECT count(*), count(*) FILTER (WHERE revoked) FROM sessions` after a few
  logout cycles shows the second number stuck at zero.
- observed: `grep -rn revoke_session --include=*.py .` returns exactly one hit,
  the definition at `app/auth/models.py:490`. Logout
  (`server/routes/auth.py:132-137`) clears the Redis key and the cookie and
  never touches the row; nothing prunes expired rows either.
- expected: the `revoked` column and the `expires_at` column both exist and
  neither is ever read. Enforcement is entirely Redis-side, which is the
  documented design ("a fast, TTL'd cache, not the durable session record"),
  but then the durable record is write-only and unbounded.
- evidence: `app/auth/db.py:83-91`; `app/auth/models.py:479-492`.
- pointer: either set `revoked` on logout/deactivate and delete expired rows
  periodically, or drop the columns. A lab-sized deployment will not notice the
  growth; the misleading part is a `revoked` flag that is always false.
- note: rows do cascade away with the user (`ON DELETE CASCADE`).

---

### R-000: `POST /api/admin/invites` accepts any `ttl_hours`, unlike the reset-token route beside it

- surface: code:auth
- class: comfort
- severity: S4
- cause: CODE
- confidence: suspected (code read)
- found by: audit:auth
- scope: `POST /api/admin/invites` only. `POST /api/admin/users/{id}/password-reset`
  is bounded correctly.
- repro: as an admin, `POST /api/admin/invites {"role":"admin","ttl_hours":87600}`
  and read the `expires_at` that comes back; then try `-1` and observe a token
  that is born expired rather than a 400.
- observed: `server/routes/admin.py:303-315`, `InviteCreateIn.ttl_hours: int = 72`
  passed straight to `create_invite_token`. `PasswordResetCreateIn` two hundred
  lines down is bounded: `if body.ttl_hours < 1 or body.ttl_hours > 72: raise
  HTTPException(400, "ttl_hours must be between 1 and 72")` (line 383-384).
- expected: an admin invite that mints another admin should not be able to sit
  valid for ten years because a client sent `ttl_hours: 87600`. A negative value
  also produces an already-expired token rather than an error.
- evidence: `server/routes/admin.py:303-315` vs `368-384`.
- pointer: the same two-line bound.
- note: admin-only, so this is hardening rather than a hole; worth doing because
  the identical guard already exists twelve lines of file away and the
  asymmetry reads as an oversight rather than a decision.

---

### R-000: `GET /api/projects/{id}` returns a row per member job with no per-job ownership check, unlike the download route

- surface: code:auth
- class: security
- severity: S4
- cause: CODE
- confidence: suspected (code read)
- found by: audit:auth
- scope: `server/routes/projects.py:136-153`. Reachability is narrow, see below.
- repro: as an admin, create a project containing another user's job, then
  `GET /api/projects/{id}` and compare its `jobs` array against what
  `GET /api/projects/{id}/download`'s manifest says it skipped.
- observed: `_require` checks the *project*, then the loop calls
  `_job_list_row(job_id, spec)` for every member with no
  `check_owner_or_admin("job", ...)`. `download_project` in the same file does
  check each one and names the ones it skips (lines 319-329).
- expected: the two routes should agree about what a member job the caller
  cannot read means.
- evidence: `server/routes/projects.py:144-152` vs `319-329`.
- pointer: only reachable when a project the caller owns holds someone else's
  job, which `_check_jobs` prevents for a non-admin and an admin can create.
  What leaks is a list row (label, engine, method, status, size), not results.
- note: filing it because the asymmetry is the kind that becomes a real hole if
  membership rules ever loosen; fix is one call inside the loop.

---

## What was checked and found clean

- **Audit-log coverage in `server/routes/admin.py` is complete.** Every
  state-changing handler writes a row: `patch_config` (:102), `purge_jobs` via
  `purge_all_jobs` (`storage_quota.py:676`), `purge_orphaned` via
  `purge_orphaned_jobs` (:463), `purge_kb` via `purge_all_kb` (:693),
  `purge_threads` via `purge_all_threads` (:717), `delete_user` (:248),
  `set_user_active` (:291), `create_invite` (:314), `revoke_invite` (:351),
  `create_password_reset` (:394), `revoke_password_reset` (:425),
  `patch_bug_report` (:454 and :459, one row per field), `delete_bug_report`
  (:472, written *before* the delete so a failure still leaves the intent
  recorded), `post_deploy` (:674). Outside admin.py, `change_password`,
  `reset_password`, `purge_own_data` and all four share transitions audit too.
- **The append-only trigger cannot be bypassed from application code.** There
  is no UPDATE or DELETE function for `admin_audit_log` in `models.py`, the
  row-level trigger covers UPDATE/DELETE and a separate statement-level trigger
  covers TRUNCATE (`db.py:185-193`), and the FK that used to force a cascade
  UPDATE was removed for precisely that reason (`db.py:131-152, 290`). The
  `DROP TRIGGER IF EXISTS`/`CREATE TRIGGER` pair on every startup runs inside
  one multi-statement `conn.execute` (`db.py:336`), which Postgres wraps in an
  implicit transaction, so there is no observable window.
- **Token lifecycles.** 32 characters from a 62-symbol alphabet via
  `secrets.choice` (`models.py:184-186`) -- ~190 bits. Both redemption paths
  take `SELECT ... FOR UPDATE` inside one transaction
  (`models.py:234-286`, `396-435`), so single-use holds under concurrency
  (`sec_02`). Invites decide "spent" on `redeemed_at`, not the nullable
  `redeemed_by` FK, which is the 2026-09-04 fix. Revocation is checked in the
  same branch as already-redeemed and returns one generic message, so neither
  endpoint is an existence oracle; the password hash is only computed *after*
  the token validates, so there is no timing distinction either. Redeeming a
  reset revokes every other outstanding token for that account
  (`models.py:430-434`) and refuses a suspended account. Deleted admins'
  tokens staying redeemable is the settled decision and is not filed.
- **Sessions.** Session ids are server-generated per login (`new_session_id`),
  so no fixation. The JWT's `role` claim is written (`security.py:53`) and
  never read anywhere -- `get_current_user` re-reads the users row on every
  request (`deps.py:52-54`), so a demotion or deactivation takes effect
  immediately, which is what `conf_02_role_demotion_live_effect.py` covers.
  Cookie flags are `httponly`, `secure`, `samesite=lax`, `path=/`. Both
  `change_password` and `reset_password` rotate the session, which overwrites
  the Redis key and kills every other cookie (`sec_04`). A cold/flushed Redis
  degrades to 401, which is correct; an *unreachable* one does not, filed above.
- **CSRF.** The missing-`Origin` case is rejected, not allowed
  (`middleware.py:99-100`), which is the SEC-01 fix and is covered by
  `sec_01`. `CORSMiddleware` is configured without `allow_credentials`, so it
  cannot hand out a credentialed cross-origin exemption.
- **Rate limiting keys on the forwarded client IP** (`rate_limit.py:42-59`),
  X-Real-IP first, with the client-controllable X-Forwarded-For only as a
  fallback for a path that cannot exist behind nginx's `expose:`-only api port.
  Login, register (which is also the invite-redemption path) and password reset
  all have buckets. KB ingest, job submission and bug reports have none; only
  the last is filed, because the other two are already bounded by the storage
  quota and the admission gate.
- **Purge scoping.** The three shapes stay distinct. `purge_all_jobs` is
  terminal-only and never cancels; `purge_user_data` cancels and *awaits* every
  non-terminal owned job before evicting (`storage_quota.py:803-806` via
  `_cancel_and_await_terminal`, which polls `job_is_terminal` and finalises
  itself after 20 s), which is the SEC-08b requirement; `purge_own_data` does
  the same cancel-and-await and leaves the account and its conversations intact.
  No bulk purge reaches another user's data: `purge_all_*` are deployment-wide
  by design and audit-logged, and `purge_my_projects` resolves ownership from
  `list_owned` rather than from the list route, explicitly so an admin's
  "delete all of MY projects" does not wipe everyone's
  (`server/routes/projects.py:74-104`).
- **At exactly the limit**, both quota comparisons use `>`
  (`_evict_oldest_first`'s `while current_total > cap_bytes`,
  `fits_for_user`'s `if incoming_bytes > h[...]`), so a user landing exactly on
  their cap is allowed and evicts nothing. Consistent.
- **Usage accounting is recomputed, never incremented**, so it cannot drift; the
  only cached figure is `meta.json`'s `dir_size_bytes` for a terminal job, whose
  directory cannot change again, and the share accept path deliberately
  recomputes rather than trusting the offer's snapshot. Deleting an object does
  release its quota: every path goes through `_evict`, which also drops the
  ownership row and invalidates the usage cache.

**One coverage gap worth naming.** `sec_06_ownership_sweep.py`'s hand-verified
route table covers `server/routes/{jobs,threads,chat}.py` and `kb.py` only.
`uploads.py`, `plots.py`, `projects.py` and `shares.py` have no equivalent
sweep, and they are where three of the entries above live. Each of those four
does call `check_owner_or_admin` on its per-resource routes (see the matrix),
so this is a missing regression test rather than a known hole -- but the
artifact-route finding SEC-06 exists to commemorate was found precisely by
building that table.

---

## Ownership matrix

`check` = `app/auth/ownership.py:check_owner_or_admin` (404 if a row exists and
is not yours; **passes when no row exists**, deliberately). `filter` =
`owned_ids_filter` / an `owner_filter` argument (None for admin and no-auth).
`dir` = the resource is looked up under the caller's own owner directory, so a
wrong id simply is not found. `admin` = `require_admin`.

| Object | list | read | update | delete | download | side-effecting |
|---|---|---|---|---|---|---|
| job (ordinary) | `filter`, jobs.py:275 | `check`, jobs.py:404 | rename `check`, :412 | `check`, :421 | `check`, :490 (+ artifacts :856, raw_input :541, log :676, cubes :733, neb_frames :820) | cancel `check`, :435; render_plot `check`, :572; troubleshoot via thread `check` |
| job (master's child) | hidden from the list (`parent_job_id` skip, jobs.py:238) | **none** -- no ownership row exists, `check` passes for everyone (FINDING) | **none** | **none** (delete cascades from the master) | **none** on every artifact route | **none** |
| job, indirect via project | `_require` on the project only, projects.py:144 (S4 finding) | per-job `check` in `download_project` :325 | -- | `_delete_jobs` :205 runs after project `_require`, no per-job check | project zip skips and names unreadable members | add/remove: `_check_jobs` :165-173, per job |
| job, indirect via share | inbox/outbox scoped by user id, models.py:677-711 | offer carries only a label + size snapshot | -- | -- | -- | offer `_require_shareable_job` :92; accept `_load_pending` side="to" :169 |
| thread | `filter`, threads.py:28 | `_require_thread` -> `check`, chat.py:94-97 | rename/pin `check`, threads.py:45,55 | `check`, threads.py:65 | not offered | messages/stop/approve/molecule/* all `_require_thread`; SSE `/events` `_require_thread`, chat.py:729 |
| plot | `filter` = `_owner_filter`, plots.py:63 | `dir` + `check`, plots.py:68-71 | rename `dir` + `check`, :129-131 | `dir` + `check`, :140-141 | `dir` + `check`, :98-101; versioned PNG :81-84 | `sweep_orphans()` on list is global but only removes plots whose every source job is gone |
| plot, indirect via share | -- | -- | -- | -- | -- | `copy_plot_to_owner` duplicates into the recipient's own directory with a fresh id (`app/plots/store.py:139`), so a copied job never serves the sender's file |
| project | `filter`, projects.py:116-120 | `_require` -> `check`, :58-67 | `_require`, :158 | `_require`, :236 | `_require`, :314 | purge-mine scoped off `list_owned`, :97 |
| upload (geometry/blind) | `filter`, uploads.py:50 | `check` + `dir`, :121-123 | -- | `check` + `dir`, :88-94; clear-all is caller-scoped, :114 | content route as read | attach to thread uses the caller's own id, never the admin None (chat.py:214-220) |
| KB source | Chroma `owner` filter, kb.py:119 / store.py:105-112 | `_find_source_file` restricted to the caller's dir + shared corpus, kb.py:94-114 | re-ingest overwrites by (owner, filename) id, ingest.py:78 | caller-scoped `delete_source(owner_filter=caller)`, kb.py:302-315; admin branch needs `?owner=` on a collision (SEC-09) | content route as read | **write path unscoped**: filename is joined unsanitised (FINDING) |
| share (offer) | `to_user_id`/`from_user_id` in SQL, models.py:689,706 | `get_share` + party check, shares.py:186-188 | -- | -- | -- | accept/decline require side="to", withdraw side="from"; `set_share_status` is a compare-and-set on 'pending' |
| bug report | `admin` only | `admin` only | `admin` only | `admin` only | attachment served by an explicitly `admin`-only handler, admin.py:478 (never `check`, on purpose) | create requires a session; no per-user cap (FINDING) |
| bug-report attachment | `admin` | `admin` + path-escape check, admin.py:493-498 | -- | with the report | `admin` | uncounted by every quota, by design |
| geometry frame (thread state) | via thread state | `_require_thread` | build/reset `_require_thread`, chat.py:111,138 | `_require_thread`, chat.py:125 | -- | tag_job_frame checks BOTH the thread and the named job, chat.py:280 |
| molecule (resolved, thread state) | -- | via thread state, `_require_thread` | `_require_thread` | -- | -- | -- |
| deploy request | `admin`, admin.py:512 | `admin` + id charset check, :688 | -- | -- | -- | `admin` to create, :621 -- but the runner honours the file, not the route, and never reads `requested_by` (see the traversal finding) |
| user account | `admin` (`list_users`) or the narrow `search_users` projection (id/username/first/last, active only, caller excluded, >=2 chars, LIKE-escaped) | `/api/auth/me` is self only | `admin` (activate/suspend), self (change-password) | `admin`, with self-delete and last-active-admin refused | `download-my-data` is self-scoped (incomplete, FINDING) | invites/resets `admin`; reset redemption is unauthenticated by design and rate-limited |
| audit row | `admin` | `admin` | **impossible** (DB trigger) | **impossible** (DB trigger, incl. TRUNCATE) | -- | append-only via `models.audit` |
