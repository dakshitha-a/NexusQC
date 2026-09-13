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

**Merged from the audit, not yet reproduced.** 89 entries. Severities
are the audit agents' own and will move at P5.4; several already look
over-rated on a first read, and the report will say which. Sorted by the
severity claimed, then by area.

| ID | Severity | Class | Surface | Title |
|---|---|---|---|---|
| R-009 | S1 | security | agent | The active-space literature search reads every user's private uploaded papers, because … |
| R-010 | S1 | bug | jobs | ORCA multi-state gradient computes the S0 entry on an excited surface whenever `target_… |
| R-011 | S1 | bug | jobs | every job is hard-killed at 6 hours by an undocumented, non-overridable timeout |
| R-012 | S1 | bug | jobs | after 6 h the orphan watcher marks a still-running re-attached worker `failed`, and the… |
| R-013 | S2 | bug | agent | On the `run_when_ready` path the approval can silently evaporate on click, because that… |
| R-014 | S2 | bug | agent | The troubleshooting message tells the model to call three tools that are not bound to it |
| R-015 | S2 | bug | agent | A literature-search backend that raises is recorded as a literature *hit*, so a failed … |
| R-016 | S2 | bug | agent | `explain_active_space` reports the wrong configuration count for any odd-electron activ… |
| R-017 | S2 | bug | agent | Any molecule-panel action or file attach silently destroys an open approval card |
| R-018 | S2 | bug | agent | A checkpoint-write failure after `submit()` can leave the interrupt live, so a re-appro… |
| R-019 | S2 | bug | deploy | `scripts/update.sh --rollback` never moves the checkout back, and stamps the new image … |
| R-020 | S2 | bug | deploy | `update.sh` exits 0 when the deployment never came up healthy, so the admin panel recor… |
| R-021 | S2 | bug | deploy | `backup.sh --full` does not archive `data/plots`, `data/projects.json` or `data/scraped… |
| R-022 | S2 | bug | deploy | `restore.sh` ignores `.env` when choosing the database and swallows `pg_restore`'s exit… |
| R-023 | S2 | bug | deploy | `update.sh` traps only EXIT, so a Ctrl-C during the drain can leave job admission pause… |
| R-024 | S2 | bug | deploy | `backup.sh`'s retention pass deletes *any* subdirectory of `QC_AGENT_BACKUP_DIR` older … |
| R-025 | S2 | bug | deploy | `--full` archives `data/jobs` while jobs are writing into it, and `update.sh` takes tha… |
| R-026 | S2 | docs | deploy | `docs/DEPLOYMENT.md`'s by-hand admin bootstrap command is missing two required argument… |
| R-027 | S2 | bug | frontend | A job opened from the Job Manager stops updating in the drawer while SSE is connected, … |
| R-028 | S2 | bug | jobs | the registry offers and routes ten (task, method, engine) cells whose input builder ref… |
| R-029 | S2 | bug | jobs | cancelling a master job erases its `path_xyz` / `ensemble_xyz` artifact pointers, so th… |
| R-030 | S2 | bug | jobs | ORCA oscillator strengths are parsed with a singlet-only row pattern, so any open-shell… |
| R-031 | S2 | bug | jobs | startup reconciliation can overwrite a `result.json` written in the window between its … |
| R-032 | S2 | bug | server | The Redis session client has no socket timeout, and it is on the path of every authenti… |
| R-033 | S2 | perf | server | Every open SSE stream permanently occupies one of anyio's 40 default threadpool tokens |
| R-034 | S3 | bug | agent | A submission in a mixed tool batch produces no confirmation at all — the app's node is … |
| R-035 | S3 | bug | agent | The system prompt tells the model not to ask for a basis set before an active-space sea… |
| R-036 | S3 | bug | agent | An attached job's one-line pointer tells the model its results are "in this conversatio… |
| R-037 | S3 | bug | agent | `_shed_pinned_results` can only shrink `ToolMessage`s, so several jobs attached to one … |
| R-038 | S3 | bug | agent | `POST /messages` has no server-side guard against posting while an approval card is ope… |
| R-039 | S3 | perf | agent | The job watcher re-reads `status.json` for every job of every conversation every two se… |
| R-040 | S3 | perf | agent | Quota enforcement runs on the watcher thread and can block on a conversation's graph lo… |
| R-041 | S3 | docs | agent | ARCHITECTURE.md's "Automatic troubleshooting, with a code-enforced budget" describes a … |
| R-042 | S3 | bug | agent | The troubleshooting message describes a failed job by its level of theory instead of by… |
| R-043 | S3 | perf | auth | `enforce_all_quotas()` re-walks all storage once per user per pass, and runs inside `Jo… |
| R-044 | S3 | bug | auth | the per-user quota pass measures only *evictable* bytes, so a user over quota on runnin… |
| R-045 | S3 | bug | auth | accepting two shares concurrently is a check-then-act with no lock, and this is the one… |
| R-046 | S3 | bug | auth | `GET /api/auth/download-my-data` omits conversations, plots, projects and scan frames -… |
| R-047 | S3 | bug | auth | an upload or KB source larger than the caller's own quota is written, returned as 201, … |
| R-048 | S3 | bug | auth | a KB upload that fails ingestion leaves its bytes on disk, invisible to every accountin… |
| R-049 | S3 | bug | auth | an admin cannot preview any per-user KB file, contradicting the route's own contract |
| R-050 | S3 | bug | auth | an unreachable Redis turns every authenticated request into a 500, while the rate limit… |
| R-051 | S3 | perf | auth | `GET /api/admin/activity` walks every job's `status.json` and `spec.json` on every poll… |
| R-052 | S3 | security | auth | bug-report attachments are uncapped per account -- no quota, no rate limit, no ceiling … |
| R-053 | S3 | bug | deploy | the new frontend bundle goes live before the new api exists, and a failure between the … |
| R-054 | S3 | perf | deploy | after a documentation-only update, every later `update.sh` run takes a full backup and … |
| R-055 | S3 | bug | deploy | `check_destructive.sh`'s vanishing-bind-mount check tests whether the override file exi… |
| R-056 | S3 | bug | deploy | `check_destructive.sh` and `update.sh` both tell the operator that *pending* jobs will … |
| R-057 | S3 | bug | deploy | a fifth destructive class `check_destructive.sh` misses — a change to a service's image… |
| R-058 | S3 | bug | deploy | `/api/health` proves only that uvicorn is answering, so `update.sh` can declare a deplo… |
| R-059 | S3 | bug | deploy | almost every Python dependency is unpinned, so two installs a month apart get different… |
| R-060 | S3 | docs | deploy | `docs/CONFIGURATION.md`'s job-parameter tables document four parameters and two task su… |
| R-061 | S3 | docs | deploy | the in-app welcome screen's capability table is a hand-written duplicate of engine rout… |
| R-062 | S3 | docs | deploy | several `docs/DEPLOYMENT.md` commands cannot run as printed, and two rows of its status… |
| R-063 | S3 | docs | deploy | README and CONFIGURATION.md contradict each other on whether the active-space recommend… |
| R-064 | S3 | bug | frontend | `ui_10`'s atom-label check on the vibration viewer snapshots the orbital viewer's empty… |
| R-065 | S3 | perf | frontend | Every `createViewer()` pins its `GLViewer` to `document.body` and `window` for the life… |
| R-066 | S3 | docs | frontend | The architecture's WebGL-context-cap mechanism does not describe 3Dmol 2.5.5's render p… |
| R-067 | S3 | perf | frontend | Every streamed token re-renders the whole chat transcript and re-parses every assistant… |
| R-068 | S3 | bug | frontend | Three of the four multi-frame viewers never check `response.ok` and have no `.catch`, s… |
| R-069 | S3 | bug | frontend | A half-typed message follows the user into whatever conversation they switch to |
| R-070 | S3 | comfort | frontend | Every selection row in the app is a `div`/`tr` with an `onClick` and no role, `tabIndex… |
| R-071 | S3 | bug | jobs | `_atomic_write_text`'s temp filename is keyed on pid alone, so two threads writing the … |
| R-072 | S3 | bug | jobs | a malformed `spec.json` leaks a scheduler admission slot permanently and strands the jo… |
| R-073 | S3 | bug | jobs | cancelling a master races the orchestrator's next dispatch wave, leaving children nothi… |
| R-074 | S3 | bug | jobs | `registry2` says ORCA has an analytic CASSCF Hessian; the runner, the architecture doc … |
| R-075 | S3 | perf | jobs | three orchestrators and the scheduler each re-walk every job directory on disk on a tim… |
| R-076 | S3 | perf | jobs | ORCA multi-state gradient / multi-pair NAC subdirectories are never scratch-cleaned |
| R-077 | S3 | bug | jobs | MC-PDFT's documented state reordering is noted only on the energy runner, and the deriv… |
| R-078 | S3 | bug | jobs | BAGEL per-atom gradient/NAC vectors are assembled without checking the atom count |
| R-079 | S3 | bug | server | `plt.subplots`/`plt.rc_context` are called from concurrent request and orchestrator thr… |
| R-080 | S3 | perf | server | Six list routes return the whole collection with no limit or pagination |
| R-081 | S3 | perf | server | `GET /api/jobs/{id}/neb_frames_live` reads and splits the whole trajectory file on ever… |
| R-082 | S3 | bug | server | `PATCH /api/admin/bug-reports/{id}` returns 200 for a report that does not exist, and 5… |
| R-083 | S3 | comfort | server | Two error paths return an internal 500 carrying engine paths and stack text |
| R-084 | S4 | bug | agent | `_agent_notice`'s cas_reco branch tests the same condition twice where the comment says… |
| R-085 | S4 | bug | agent | `update_job_draft` silently discards valid parameters when one key in the same call is … |
| R-086 | S4 | bug | agent | `search_academic_literature` parses the response body outside its try block |
| R-087 | S4 | comfort | auth | `purge_own_data` leaves the caller's plots and projects behind, and the response counts… |
| R-088 | S4 | comfort | auth | `revoke_session` is never called, so the `sessions` table only ever grows |
| R-089 | S4 | comfort | auth | `POST /api/admin/invites` accepts any `ttl_hours`, unlike the reset-token route beside … |
| R-090 | S4 | security | auth | `GET /api/projects/{id}` returns a row per member job with no per-job ownership check, … |
| R-091 | S4 | comfort | deploy | `update.sh`'s destructive-change confirmation uses a bare `read`, which under `set -e` … |
| R-092 | S4 | docs | deploy | `nginx/nginx.conf`'s header describes a public listener and a kill-switch script that w… |
| R-093 | S4 | bug | deploy | `check_destructive.sh`'s disappearing-route check cannot see a router prefix, so a rena… |
| R-094 | S4 | docs | frontend | `main.tsx`'s comment says no query in the app sets `refetchInterval`; thirteen of them … |
| R-095 | S4 | bug | frontend | Several raw `fetch()` call sites bypass `lib/api.ts`'s `request()`, so their 401 and 50… |
| R-096 | S4 | comfort | jobs | a PES-scan plot's "State 1" is S1, while `target_states=[1]` is S0 |
| R-097 | S4 | bug | server | `_pop_cancel_event` can disarm the Stop button for a turn it does not belong to |

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
- coordinator (P3.9 live sweep): re-confirmed through the running app with a
  second account. In one cross-user sweep as qa_review_2 (owning nothing):
  qa_review's thread returns 404, the owned master `186fe458ec9e` returns 404,
  and its child `0d87ea39ec68` returns 200 with the full 17,365-byte record
  and a 16,185-byte artifact download. So top-level owned jobs and threads are
  correctly isolated and ONLY the child of an owned master leaks, which is
  exactly the scope of this finding. The three unowned top-level jobs the
  sweep also saw are the settled visible-to-all behavior, not leaks, and are
  labelled as such in the evidence. Evidence:
  docs/evaluation/2026-09-app-review/evidence/p3/p3_09_isolation.jsonl. Note the
  driver's attempt to also seed a freshly-owned top-level job for A failed
  (the agent did not produce a job in the 120 s window, adjacent to R-101), so
  the "A's own top-level job is protected" leg rests on the master's 404 rather
  than a seeded job; worth a clean re-seed if triage wants it, but the child
  leak is not in doubt.
- resolution: fixed 106cb5b
- regression test: tests/backend/sec_11_child_job_ownership.py

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
- resolution: fixed 111a6b0
- regression test: tests/backend/sec_12_kb_path_safety.py

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
- resolution: fixed 3498cfc
- regression test: tests/backend/sec_13_chat_job_attachment.py

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
- coordinator (P3.3, definitive, main path): traced end to end and confirmed on
  the shared submission builder, not just the isolated function. `resolve_method`
  (`registry2/lookup.py:158`) correctly returns `lpdft` because of its
  `if q in CANONICAL_METHODS` guard, so the registry and the approval card are
  fine (the live lpdft card carried `active_electrons=4, active_orbitals=4,
  ot_functional="tpbe"`, all correct). But `_build_spec_or_error`
  (`app/agent/tools.py:1187`), which its own docstring calls "shared by every
  draft that reaches READY", re-runs `normalize_method` on the already-resolved
  method with no canonical short-circuit. Called in process with method=`lpdft`
  it returns a spec with **`method='dft'`** while KEEPING `active_electrons`,
  `active_orbitals` and `ot_functional='tpbe'` (params plain DFT ignores), plus
  the wrong reassuring note. So the user approves a card showing an L-PDFT
  active space and tPBE, and the job runs single-reference DFT. This is the
  worst form of the finding and it is on the main path, not a corner. Fix: give
  `tools.py:1187` the same `if method in CANONICAL_METHODS` short-circuit that
  `lookup.py:158` already has. The registry guard alone is not enough because
  this builder runs after it.
- resolution: fixed b307ed4
- regression test: tests/backend/draft_02_canonical_method_survives.py

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
- coordinator addendum: two further instances were confirmed during Phase 5 verification and belong to this theme. (4) The approval-card guard `append_notice_unless_card_pending` was measured, documented and applied to one `update_state` caller out of seven (see the molecule-panel finding). (5) `check_external=False` was documented in `elicitation.py`, applied in `submit_draft`, and omitted from the newer `run_when_ready` shortcut (see the evaporating-approval finding). Five sites, one habit.
- resolution: fixed 111a6b0
- regression test: tests/backend/sec_12_kb_path_safety.py

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
- resolution: fixed 111a6b0
- regression test: tests/backend/sec_12_kb_path_safety.py

### R-009: The active-space literature search reads every user's private uploaded papers, because it passes `state=None` into the one KB path that exists to scope by owner
- surface: code:agent
- class: security
- severity: S1
- cause: CODE
- confidence: confirmed by code read (coordinator followed the call into app/rag/query_tool.py)
- found by: audit:agent
- scope: `app/agent/active_space_lit.py`'s default backends only. The
  model-facing `search` tool (`tools.py:2875`) correctly forwards
  `state=state` for both `"manuals"` and `"papers"`, and
  `_kb_context_for_job` (`tools.py:161`) is `doc_type="manual"` only, so
  neither is affected. Not checked: whether any other module calls
  `search_knowledge_base.func` with `state=None`.
- repro: user B uploads a private paper on molecule M. User A asks about
  an active space for M; the agent calls `active_space` → 
  `search_active_space_literature` → `active_space_lit.search`, whose
  knowledge-base tier retrieves B's paper verbatim into A's conversation
  and into the resulting job's `literature_notes`.
- observed: `app/agent/active_space_lit.py:203`
  `kb = kb or (lambda q: search_knowledge_base.func(q, doc_type="paper", k=5, state=None))`.
  `app/rag/query_tool.py:39` reads the owner off that state:
  `owner = (state or {}).get("owner_user_id")`, and with `owner` falsy it
  falls through to an unfiltered search. Its own comment (lines 43-51)
  states the harm exactly: *"without this scoping any user's chat could
  trigger a search that surfaces another user's private upload verbatim
  into the model's context."*
- expected: `search_active_space_literature` already receives
  `state: Annotated[AgentState, InjectedState]` (`tools.py:3528`) and so
  has `owner_user_id` in hand; it should thread it into
  `active_space_lit.search`, which should pass it to the kb lambda. The
  `doc_type="paper"` here is precisely the case
  `query_tool.py`'s comment calls "the more privacy-sensitive case".
- evidence: `app/agent/active_space_lit.py:203` (quoted above);, evidence/audit/_COORDINATOR_VERIFIED.md
  `app/rag/query_tool.py:39-53`; `app/agent/state.py:299-307`
  (`owner_user_id` … "Read by `search_knowledge_base` … so one user's chat
  can never surface another user's private KB uploads").
- pointer: `active_space_lit.search` takes its backends as injectable
  callables so tests can drive it without a network call
  (docstring, lines 186-190); the production default was written for that
  signature and never grew the owner argument the tool already holds.
- note: settled by uploading a paper as one user and searching as another
  on the compose stack. Related to the previous finding: both are cases
  where a scoping rule that exists is not applied on one path. The
  `explain_active_space` branch (`tools.py:3671`) calls the same
  `active_space_lit.search` and is affected identically.
- resolution: fixed c42b735
- regression test: tests/backend/sec_14_active_space_lit_scope.py


---

### R-010: ORCA multi-state gradient computes the S0 entry on an excited surface whenever `target_states` does not begin with 1
- surface: code:jobs
- class: bug
- severity: S1
- cause: CODE
- confidence: confirmed by executing the input builder (no job submitted)
- found by: audit:jobs
- scope: ORCA only. PySCF (`pyscf_runner.run_gradient`, hf/dft branch: `root = state - 1`, `state == 1` uses `mf.nuc_grad_method()`) and BAGEL (`bagel_runner._build_input`: `grads = [{"title": "force", "target": int(s) - 1} ...]`) convert per entry and are correct; I checked both. Not checked: whether any caller upstream of `_build_spec_or_error` happens to sort the list in practice.
- repro: submit a `single_point/grad` draft on ORCA with `target_states=[2, 1]` (a plausible phrasing of "S1 and the ground state"). Compare the two `.engrad` energies: both come from `IRoot 1`. Same input text is produced for the `state_2` and the top-level run.
- observed: `run_gradient` loops over `targets` and, per state, sets `state_params = {**params, "target_state": (state - 1) or None}` (`orca_runner.py:952`) — so the ground state passes `target_state=None`. `build_input_text`'s gradient branch then does
  `target_state = params.get("target_state") or ((targets[0] - 1) or None)` (`orca_runner.py:573`).
  `None` is falsy, so the ground-state run falls through to the fallback and takes its root from `targets[0]`. With `targets = [2, 1]` the S0 run emits `%tddft / NRoots 1 / IRoot 1 / end` and the parsed `.engrad` is S1's gradient — recorded as `derivatives.gradient_entry(1, ...)`, i.e. labelled S0.
- expected: the fallback exists only so a *preview* built straight from a draft (which carries `target_states` but no `target_state`) shows an excited-state input; it must not fire when `run_gradient` has explicitly set the key. Nothing normalises or sorts `target_states`: `app/agent/tools.py::_validate_target_states` (l.1004) checks shape, distinctness and ceiling only, and `_normalized_state_list` preserves order.
- evidence: `app/chemistry/jobs/orca_runner.py:573`
  `target_state = params.get("target_state") or ((targets[0] - 1) or None)`
  and `app/chemistry/jobs/orca_runner.py:952`
  `state_params = {**params, "target_state": (state - 1) or None}`
- pointer: `or` on a value whose legitimate "ground state" encoding is exactly the falsy one. `docs/ARCHITECTURE.md` §"Several states or pairs are one job" warns about precisely this pair of conventions ("`target_states` … 1-based INCLUDING the ground state … the older scalar `target_state` … 0 or absent means the ground state").
- note: settled by diffing the input text for `target_states=[2,1]` state 1 vs `target_states=[1]`. Fix direction: `target_state = params["target_state"] if "target_state" in params else ((targets[0] - 1) or None)` — key presence, not truthiness. A cheaper belt-and-braces fix is to sort `target_states` ascending in `_validate_target_states`, but that only hides this instance.
- coordinator: Reproduced in process with `orca_runner.build_input_text("gradient", water, {..., "target_states": ts, "target_state": (1-1) or None})`, which is exactly what `run_gradient` does for the ground-state run at `orca_runner.py:952`. Results, for the S0 run: `[1,2]` -> no `%tddft` block (correct); `[2,1]` -> `IRoot 1`, so S1's gradient is labelled S0; `[3,1]` -> `IRoot 2`, so S2's is; `[1,3]` -> correct. The encoding at :952 is right and the `or` at :573 undoes it. Severity S1 stands: a wrong scientific number presented as correct. ORCA only; PySCF and BAGEL convert without the `or`.
- resolution: fixed da6efb6
- regression test: tests/backend/grad_04_target_state_zero.py

### R-011: every job is hard-killed at 6 hours by an undocumented, non-overridable timeout
- surface: code:jobs
- class: bug
- severity: S1
- cause: CODE
- confidence: confirmed by code read
- found by: audit:jobs
- scope: all three engines. `base._run_inner` wraps every worker; `orca_runner._write_and_run`/`_write_and_run_generic` and `bagel_runner._run_bagel` each add the same cap to their own `subprocess` call, so ORCA and BAGEL are capped twice.
- repro: submit anything that runs past 6 h (a CASPT2 or a numerical CASSCF Hessian on a real molecule is the ordinary case here). At 6 h the process group is SIGTERM'd and the job reports `failed` / `job exceeded 6h timeout`.
- observed: `app/chemistry/jobs/base.py:1752` `returncode = proc.wait(timeout=6 * 3600)`, then `base.py:1786` `write_result(JobResult(spec.job_id, "failed", error="job exceeded 6h timeout"))`. Also `orca_runner.py:763` and `:792` (`timeout=6 * 3600`), `bagel_runner.py:722` (`subprocess.run([...], timeout=6 * 3600)`), and `base.py:1177` in the orphan watcher.
- expected: `CLAUDE.md` and `docs/ARCHITECTURE.md` both state that multi-hour CASSCF/CASPT2 runs are the design premise and that "anything that would make a job's lifetime depend on its user's session is a serious regression". Every other threshold in this subsystem is `QC_AGENT_*`-overridable (`N_CORES`, `MAX_CONCURRENT_JOBS`, `MAX_CPU_PERCENT`, `MAX_MEM_PERCENT`, `CORE_IDLE_THRESHOLD_PERCENT`, `MASTER_MAX_IN_FLIGHT`, `IMAGINARY_FREQ_THRESHOLD_CM1` — all in `app/config.py`). This one is a literal in four files. `grep -rn -i "hour|timeout" docs/ README.md` finds no mention of a 6 h cap anywhere — not in `ARCHITECTURE.md`, not in `QM_CAPABILITIES.md`, not in the known-limitations section, and not in the README, whose line 613 says the opposite in as many words: *"A CASSCF job can run for hours. Close the tab and come back; it'll still be [there]"*.
- evidence: `app/chemistry/jobs/base.py:1752`, `:1786`; `app/chemistry/jobs/orca_runner.py:763,792`; `app/chemistry/jobs/bagel_runner.py:722`
- pointer: a defensive timeout written for a runaway process, left at a value shorter than the workload the app exists to run.
- note: confirm by asking the maintainer whether 6 h is intended at all. If it is, it belongs in `app/config.py` as `QC_AGENT_JOB_TIMEOUT_SECONDS` and in the docs, and the four literals should read the same constant. Note the ordering: the OUTER `proc.wait` in `_run_inner` starts at worker spawn, the inner `subprocess.run(timeout=...)` in the ORCA/BAGEL runners only once imports are done seconds later, so the outer one expires first and the user does see the tidy "job exceeded 6h timeout" message. The inner caps matter only for a runner invoked outside `JobManager`.
- coordinator: `grep -rn '6 \* 3600' app/` finds five sites: `base.py:1177` and `:1752`, `orca_runner.py:763` and `:792`, `bagel_runner.py:722`. Not one is read from `app/config.py`, where every other timeout in the app has a `QC_AGENT_*` variable. At `:1752` the expiry is handled by `os.killpg(SIGTERM)`, then SIGKILL, so the kill is real, not a warning. README line 613 says "A CASSCF job can run for hours. Close the tab and come back; it'll still be there", and `CLAUDE.md` names multi-hour CASSCF/CASPT2 as the design premise. On this host BAGEL takes 80 to 96 s per CASSCF macro-iteration on water, so six hours is not a theoretical ceiling here. Severity S1 stands as a hard, silent cap on the leave-and-return premise.
- resolution: fixed 2c0c19f
- regression test: tests/backend/jobs_04_job_timeout_and_dispatch.py

### R-012: after 6 h the orphan watcher marks a still-running re-attached worker `failed`, and the status never recovers
- surface: code:jobs
- class: bug
- severity: S1
- cause: CODE
- confidence: confirmed by code read
- found by: audit:jobs
- scope: any engine; only reachable for a job re-attached by `_reconcile_orphaned_jobs` case 2 (worker survived a backend restart) that then runs more than 6 h from the moment of re-attachment.
- repro: start a long job, restart the backend, leave the re-attached worker running past 6 h. `status.json` flips to `failed` while the worker keeps computing; when it finishes it writes a `completed` `result.json`, and the two disagree until the *next* backend restart runs `_reconcile_orphaned_jobs` case 1.
- observed: `_watch_orphan_worker` does
  ```
  try:
      psutil.Process(pid).wait(timeout=6 * 3600)
  except Exception:
      pass
  ```
  (`base.py:1176-1179`). A `psutil.TimeoutExpired` is swallowed identically to a normal exit. Execution then falls through, pops the pid from `self._orphan_pids` (so `cancel()` can no longer reach the live process at all), finds no terminal `result.json`, and writes
  `write_status(job_id, "failed", "worker process exited after a server restart with no result recorded")` (`base.py:1192`) plus a matching failed `result.json`.
- expected: the architecture's whole orphan-reconciliation section exists so that "a status that never reaches terminal" cannot happen; the mirror failure — a *wrong* terminal status on a job that is still running and will succeed — is equally an S1 by the brief's definition, and it additionally strands the process (no `Popen`, no `_orphan_pids` entry, cancel returns False).
- evidence: `app/chemistry/jobs/base.py:1176-1196`
- pointer: `except Exception: pass` around a `wait(timeout=...)` conflates "it exited" with "I gave up waiting".
- note: distinguish `TimeoutExpired` from a real exit — on timeout, either loop the wait or leave the job alone and keep the pid registered. Independent of whether the 6 h value itself is kept.
- coordinator: `_watch_orphan_worker` (`base.py:1167-1196`) is the path taken when the server restarts under a running job, which is precisely the leave-and-return scenario P3.5 exercises. `psutil.Process(pid).wait(timeout=6 * 3600)` sits inside `except Exception: pass`, so a `TimeoutExpired` is indistinguishable from a normal exit. The code then pops `_orphan_pids` (cancel can no longer reach the pid), calls `read_result`, finds nothing because the worker is still running, and writes `status=failed` with the message "worker process exited after a server restart with no result recorded", which is false on both counts. Contrast with `:1752`, where the same six hours ends in a kill. So a job that crosses six hours is killed if the server never restarted and falsely marked failed while still running if it did. Severity S1: a wrong terminal status, and `docs/ARCHITECTURE.md` says `status.json` is the one answer to "has this job finished?".
- resolution: fixed 2c0c19f
- regression test: tests/backend/jobs_04_job_timeout_and_dispatch.py

### R-013: On the `run_when_ready` path the approval can silently evaporate on click, because that path re-validates with the external checks that `submit_draft` deliberately turns off
- surface: code:agent
- class: bug
- severity: S2
- cause: CODE
- confidence: confirmed by code read against the module's own documented hazard
- found by: audit:agent
- scope: the two blocking `check_external`-gated checks in
  `registry2/elicitation.py`: `source_geometry_job_id` (line 673) and
  wigner `source_frequency_job_id` (line 751). Both return `_ask(...)`,
  i.e. they flip a `ready` verdict to `incomplete`.
  `initial_orbitals_job_id` (line 929) is drop-with-a-note and leaves the
  verdict `ready`, so it does not trigger this. Not checked on the
  explicit `submit_draft` path, which is correct by construction.
- repro: draft a job with `{"source_geometry_job_id": "<id>"}` and
  `run_when_ready=True` so the card appears from inside
  `update_job_draft`. Delete that source job (or let a quota eviction
  take it) while the card is on screen. Click Approve. Everything before
  `interrupt()` re-runs, `validate_draft` now returns a question, no
  `interrupt()` is reached, the resume value goes nowhere, and the user's
  click produces an elicitation question instead of a job.
- observed: `app/agent/tools.py:3352` (in `_draft_command`, the single
  funnel both draft tools pass through)
  `verdict = validate_draft(draft, state or {})` — `check_external`
  defaults to `True`. When that verdict is `ready` and the run intent is
  set, line 3363 goes straight to `_submit_ready_draft(...)`, which calls
  `interrupt()` at `tools.py:3972`. Compare `tools.py:3916`, inside
  `submit_draft`: `verdict = validate_draft(draft, state or {}, check_external=False)`.
- expected: `check_external=False` on any path that can reach
  `interrupt()`, for the reason `validate_draft`'s own docstring gives
  (`app/chemistry/registry2/elicitation.py:563-570`): *"That check is
  right at elicitation time and wrong at submission time, because
  everything before the approval `interrupt()` re-runs when the user
  clicks Approve. If the answer changed in between … a re-validating
  submitter would return a question instead of resuming, and the approval
  would disappear with no error at all."* `docs/ARCHITECTURE.md:338-390`
  makes the same argument for why `submit_draft` never redoes network
  resolution.
- evidence: `app/agent/tools.py:3352` vs `app/agent/tools.py:3916`;
  `app/chemistry/registry2/elicitation.py:563-570`.
- pointer: `_submit_ready_draft` was factored out of `submit_draft` so
  `_draft_command` could reach the card directly (its docstring,
  `tools.py:3930-3941`), but the `check_external=False` guard stayed
  behind in `submit_draft` rather than moving into `_submit_ready_draft`
  or being applied at the `_draft_command` call site.
- note: the fix direction is to re-validate with `check_external=False`
  immediately before `_submit_ready_draft`, or to pass the flag through
  `_draft_command`. `run_when_ready=True` is what the system prompt calls
  "the ordinary case" (`prompts.py:41-43`), so this is the common path,
  not an edge one. What would settle it: raise a card via
  `run_when_ready` with a `source_geometry_job_id`, delete the source
  job, click Approve, and check whether `snapshot.interrupts` empties
  with no submission — the same measurement
  `tests/backend/draft_01_summary_defer.py` already makes for the
  neighbouring case.

---
- coordinator: `registry2/elicitation.py:563-570` states the hazard verbatim: everything before the approval `interrupt()` re-runs on Approve, so a validator that reads anything outside the draft can 'return a question instead of resuming, and the approval would disappear with no error at all', which is why `check_external=False` exists. `submit_draft` (`tools.py:3916`) uses it. `_draft_command` (`tools.py:3352`) calls `validate_draft(draft, state or {})` with the default `check_external=True` and, at 3363, when `run_intent` is set, goes straight to `_submit_ready_draft` and the interrupt. `prompts.py` describes `run_when_ready` as the ordinary case. The trigger is narrow, a Wigner source job deleted or unfinished between the card and the click, so the realistic severity is S3 rather than the filed S2; the class is the point, being the fifth one-of-two-paths instance.

### R-014: The troubleshooting message tells the model to call three tools that are not bound to it
- surface: code:agent
- class: bug
- severity: S2
- cause: CODE
- confidence: confirmed by grep
- found by: audit:agent
- scope: `app/agent/troubleshoot.py`'s composed message, i.e. every press
  of the Troubleshoot button. Cross-checked every tool name in
  `prompts.py` and in `job_watcher.py`'s `_agent_notice` against
  `STATIC_TOOLS`; those two are clean. `troubleshoot.py` is the only
  offender found.
- repro: let any job fail, press Troubleshoot, read the injected message
  in the transcript, and compare the three names in it against
  `get_all_tools()`.
- observed: `app/agent/troubleshoot.py:126-131`:
  `"Consult search_knowledge_base(doc_type='manual') for the engine's own documentation … and web_search for the specific error text … not search_academic_literature, which covers published papers rather than software errors."`
  None of `search_knowledge_base`, `web_search` or
  `search_academic_literature` is in `STATIC_TOOLS`
  (`app/agent/tools.py:5345-5352`), which is what `get_all_tools()`
  returns and therefore all the model is offered. The three were folded
  into one `search(source=...)` tool (`tools.py:2875`), whose sources are
  `("manuals", "papers", "scholar", "web")` (`tools.py:2871`).
- expected: the message should name `search(source='manuals')` and
  `search(source='web')`, exactly as `prompts.py:100-106` already does
  for the same workflow. A model told to call a non-existent tool either
  emits an invalid call (a wasted ReAct iteration and an error
  ToolMessage) or ignores the instruction and troubleshoots without
  consulting the manuals at all — which is the whole value of the
  feature.
- evidence: `app/agent/troubleshoot.py:126-131`; `app/agent/tools.py:5345`
  `STATIC_TOOLS = [set_geometry, lookup_capabilities, active_space, start_job_draft, update_job_draft, submit_draft, check_job_status, plot, geometry_parameters, list_ensemble_geometries_in_window, convert_energy_units, search, resolve_basis_from_bse]`.
- pointer: the four-tools-into-one collapse
  (`docs/MODEL_CONTEXT_BUDGET.md`, "Where this landed. Phase 2, done")
  updated `prompts.py` and missed this second prompt surface.
- note: `web_search` and `search_academic_literature` still exist as
  `@tool`-decorated functions in `web_search.py`/`scholar_search.py`, and
  `search_knowledge_base` in `app/rag/query_tool.py`, which is why a grep
  for the names does not look wrong. They are reached only via
  `search`'s dispatch (`tools.py:2913-2919`). Confirmed by reading
  `get_all_tools`/`get_executable_tools` (`tools.py:5400-5414`): neither
  returns them.

---
- coordinator: `app/agent/troubleshoot.py:126,127,129` name `search_knowledge_base`, `web_search` and `search_academic_literature`. `STATIC_TOOLS` (`app/agent/tools.py:5345`) binds `set_geometry, start_job_draft, check_job_status, convert_energy_units, search, resolve_basis_from_bse, ...`; a grep of that list for the three names returns 0. They were unified into `search(source=...)` and only `prompts.py` was updated. Cause is CODE even though the symptom is LLM-shaped: the model is being instructed to call things that do not exist.

### R-015: A literature-search backend that raises is recorded as a literature *hit*, so a failed search can be reported as published support for an active space
- surface: code:agent
- class: bug
- severity: S2
- cause: CODE
- confidence: confirmed by executing the marker check
- found by: audit:agent
- scope: `app/agent/active_space_lit.py`, both backends (`kb`,
  `scholar`) and both callers (`search_active_space_literature`,
  `explain_active_space`). Traced the marker list against the literal
  return strings in `app/rag/query_tool.py`, `app/agent/scholar_search.py`
  and `app/agent/web_search.py`; those match. It is the wrapper's own
  string that does not.
- repro: make the KB store raise (stop chromadb, or point it at a missing
  path) and ask for an active space. The narrowest tier "matches",
  `search()` short-circuits, and `as_notes()` reports a literature match
  whose evidence is the text `"knowledge base search failed (...)"`.
- observed: `app/agent/active_space_lit.py:259-267`:
  ```
  def _call(fn, source: str, query: str) -> str:
      try:
          return fn(query)
      except Exception as exc:
          return f"{source} search failed ({exc})."
  ```
  `_is_empty` (lines 53-58) does
  `any(text.lstrip().startswith(m) for m in _NO_RESULT_MARKERS)`, and
  `_NO_RESULT_MARKERS` (lines 43-51) is
  `("No matching passages found", "No matching papers found", "No web results found", "Academic literature search failed", "Academic literature search is rate-limited", "Web search failed")`.
  `"knowledge base search failed (…)"` and
  `"published literature search failed (…)"` start with none of them, so
  `_absorb` (lines 271-283) records the string as a hit and sets
  `findings.matched_at = label`. At the knowledge-base tier that then
  triggers `if findings.matched_at == tiers[0][0]: return findings`
  (line 240), skipping the network backends entirely.
- expected: a backend that threw is "nothing found", which `_call`'s own
  docstring says it intends: *"a search that found nothing because a
  backend threw is reported as 'nothing', which is honest."* The marker
  list already treats the two in-tool failure strings as empty, so the
  wrapper's own string was simply overlooked.
- evidence: `app/agent/active_space_lit.py:43-58`, `:242`, `:257-265`,
  `:268-283`.
- pointer: the markers were written against the three tools' return
  values, before `_call` was added to wrap them.
- note: this is S1 if the fabricated "hit" reaches a user as a literature
  claim, which `as_notes()`' found-branch (lines 100+) is written to do
  — it qualifies how narrowly the query matched and the report is
  reconciled against it. It also defeats the guardrail this module exists
  for (its docstring, lines 1-27, and the standing decision that the
  empty result IS the guardrail). Fix: return `""` from `_call`, or add
  `f"{source} search failed"` shapes to `_NO_RESULT_MARKERS`. Settled by
  a one-line unit drive: `active_space_lit.search("water", kb=lambda q: 1/0)`
  and check `.found`.

---
- coordinator: `active_space_lit.py:259` `_call` returns `f"{source} search failed ({exc})."` on any exception, and it is invoked with `source` = `"knowledge base"` (line 238) and the per-backend names at 250. `_NO_RESULT_MARKERS` (line 43) lists `"Academic literature search failed"` and `"Web search failed"`, neither of which is a prefix of `"knowledge base search failed (...)"` or `"scholar search failed (...)"`. Checked directly: five plausible source spellings, all `recognised as no-result: False`. So a backend that raises is absorbed by `_absorb` as a finding. The module's whole purpose is that an empty result is the guardrail; this inverts it for the failure case. Compounds R-009, which is about the same function's `state=None`.

### R-016: `explain_active_space` reports the wrong configuration count for any odd-electron active space
- surface: code:agent
- class: bug
- severity: S2
- cause: CODE
- confidence: confirmed by executing the arithmetic
- found by: audit:agent
- scope: `explain_active_space` only (reached via the `active_space` tool
  when the user supplies `(ne, no)`). Did not check whether the same
  arithmetic is duplicated in `app/chemistry/cas/`.
- repro: ask "is (5e,4o) a reasonable active space for <molecule>". The
  reply says "holds at most 36 many-electron configurations". The correct
  determinant count for 5 electrons in 4 orbitals is
  C(4,3)·C(4,2) = 4·6 = 24.
- observed: `app/agent/tools.py:3672-3673`:
  ```
  n_alpha = n_beta = active_electrons // 2
  max_configs = math.comb(active_orbitals, n_alpha) * math.comb(active_orbitals, n_beta)
  ```
  Integer division discards the unpaired electron, so an odd count is
  treated as the even count below it and the product is computed from the
  wrong pair of occupations. It over-counts (36 vs 24 above), never
  under-counts.
- expected: `n_alpha = (active_electrons + 1) // 2`,
  `n_beta = active_electrons // 2` for the lowest-multiplicity case, or
  derive both from the molecule's actual multiplicity — which is
  available, since the tool already reads `state["molecule"]` at line
  3660.
- evidence: `app/agent/tools.py:3672-3673`, and the use of the number at
  lines 3683-3691, where it decides between *"enough for the N
  state-averaged root(s) asked about"* and *"fewer than the N root(s)
  asked about, so a state-averaged CASSCF of that size cannot be run in
  it."*
- pointer: the closed-shell case was written first and the `//` was never
  revisited for an odd electron count, which a radical or a cation makes
  ordinary.
- note: the direction matters — over-counting makes the "cannot be run in
  it" guard *too permissive*, so the tool can tell a user a space is
  large enough for their state average when it is not. That is a wrong
  scientific statement presented as correct, which is why this is not S3.
  Two seconds with `math.comb` settles the arithmetic; what needs a
  decision is whether the intended quantity is determinants or CSFs, and
  the docstring should say which.

---
- coordinator: `tools.py:3672` does `n_alpha = n_beta = active_electrons // 2`. For CAS(5,4) that yields `comb(4,2)*comb(4,2) = 36` where the correct `comb(4,3)*comb(4,2) = 24`; for CAS(7,6), 400 against 300. Every odd-electron space is described as the even-electron space one electron smaller. CAS(3,3) happens to agree (9 = 9) by coincidence, which would hide it in a casual check. The downstream 'too small for N roots' guard inherits the error.

### R-017: Any molecule-panel action or file attach silently destroys an open approval card
- surface: code:agent
- class: bug
- severity: S2
- cause: CODE
- confidence: confirmed by the app's own measured docstring
- found by: audit:agent
- scope: the `update_state` callers in `app/agent/graph.py` reachable
  from a route while a card is open: `clear_molecule` (:996),
  `remove_frame` (:1016), `add_built_frame` (:1061),
  `add_geometry_frames` (:1087), `append_attached_file` (:1225) and the
  plain `append_notice` (:1154). Deliberately NOT included:
  `set_active_frame` (only reached from `_run_turn`, and the composer is
  disabled while a card is open) and `remove_messages` (its call site is
  guarded by `pending is None`, `chat.py:590`).
- repro: get an approval card on screen, then click the molecule panel's
  reset button (`POST /api/threads/{id}/molecule/reset`), or delete a
  frame, or attach a `.xyz` from the Files panel. The card's underlying
  interrupt is discarded; the card stays on screen because the client
  never hears otherwise, and clicking Approve then 409s or no-ops.
- observed: each of those functions does a bare
  `get_graph().update_state(config, {...})` under the thread lock with no
  `pending_approval` check — e.g. `graph.py:1010-1011`:
  ```
  with _lock_for_thread(config):
      get_graph().update_state(config, {"molecule": CLEAR_MOLECULE, "molecule_frames": {"__replace__": []}})
  ```
  The routes that call them (`chat.py:110-260`) check thread ownership and
  nothing else.
- expected: `docs/ARCHITECTURE.md:648-716` and
  `append_notice_unless_card_pending`'s docstring (`graph.py:1197-1216`)
  state the rule: *"`update_state` discards a pending `interrupt()` —
  the approval card disappears, the submit_draft call is orphaned and the
  user's later Approve does nothing."* `append_notice` names this itself
  (`graph.py:1175-1182`) and hand-waves the remaining callers as
  *"user-initiated (attaching a file), where the user is looking at the
  app rather than at a card"* — which is exactly the case where a card IS
  on screen, since the composer is disabled and the panel is the only
  thing left to click.
- evidence: `app/agent/graph.py:1010-1011`, `:1027-1031`, `:1081-1082`,
  `:1112-1113`, `:1246-1248`, `:1185-1186`;
  `app/agent/graph.py:1175-1182` (`append_notice`'s own warning);
  `server/routes/chat.py:119`, `:132`, `:157`, `:228`, `:249-251`, `:258`,
  `:310`.
- pointer: the guard was built for the watcher's notice path
  (`append_notice_unless_card_pending`) and never generalised to the
  six other `update_state` callers, because the reasoning was framed as
  "background writes are dangerous" rather than "`update_state` is
  dangerous".
- note: confidence is `suspected` for a specific reason worth recording:
  the measured evidence (`tests/backend/draft_01_summary_defer.py`,
  per ARCHITECTURE.md:660-668) is for a `messages` update. That a
  `molecule`-only `update_state` destroys the interrupt the same way is
  inferred from LangGraph's task model, not measured. Settling it is one
  script: raise a card, call `clear_molecule(config)`, then read
  `get_state(config).interrupts` and `.next`. If it holds, the fix is a
  shared guard (return 409 while a card is pending) rather than six
  copies of the check.

---
- coordinator: `app/agent/graph.py:1197` `append_notice_unless_card_pending` exists for exactly this, and its docstring is the evidence: 'Measured on the real topology, `update_state` discards the pending approval task exactly as thoroughly as invoking with new input does -- interrupts one to zero, `next` emptied, the submit_draft call orphaned, the user's later Approve a silent no-op.' The guard checks `pending_approval(config)` first. The six other `update_state` writers in the same file do not: `clear_molecule` (1011), `remove_frame` (1031), `set_active_frame` (1056), `add_built_frame` (1082), `add_geometry_frames` (1113) and `append_attached_file` (1186). Every one is reachable from a route while a card is on screen. So clearing the molecule, stepping a frame, sketching, or attaching a file with a card open makes the Approve button do nothing, with no message. Fourth instance of the R-005 pattern: the defence was written, measured and applied to one caller.

### R-018: A checkpoint-write failure after `submit()` can leave the interrupt live, so a re-approval submits the job twice
- surface: code:agent
- class: bug
- severity: S2
- cause: CODE
- confidence: suspected (code read), not yet reproduced
- found by: audit:agent
- scope: `_finish_submission` → `approve_job`. Reasoned about, not
  reproduced; I did not verify at what point LangGraph clears the
  interrupt relative to the node's checkpoint commit, and that is the
  crux.
- repro: inject a failure in the Postgres checkpointer's `put` (kill the
  DB, or exhaust the pool) during an approval resume, then reload the
  page and click Approve again.
- observed: in `_finish_submission` the real submission happens first —
  `job_id = get_job_manager().submit(approved_spec, owner_user_id=owner_user_id)`
  (`tools.py:2541`) and the scan/ensemble/batch equivalents above it —
  and only afterwards is the `Command(update=...)` returned for the graph
  to commit. If the commit raises, `_stream_resume` propagates, and
  `approve_job` (`chat.py:870-883`) logs and raises a 500 *before* line
  908's `pending_approval(config)` re-read and the `interrupt` SSE event.
  The job directory exists on disk regardless.
- expected: an approval is single-use. Either the interrupt is spent the
  moment the resume begins (in which case this is only a lost
  confirmation, S3) or it is not (in which case a second click runs the
  calculation twice, which on this host can be hours of compute).
- evidence: `app/agent/tools.py:2541`; `server/routes/chat.py:865-883`;
  `server/routes/chat.py:908-910`.
- pointer: the resume path has no idempotency key. `active_job_ids` would
  have caught a duplicate, but its write is in the same uncommitted
  update.
- note: file low-confidence and settle it before acting. The cheap
  observation that settles it: after a successful approval, does
  `get_state(config).interrupts` empty as of the *node* commit or as of
  the resume call? A `_retried_from`-style marker written into the job
  directory before the Command returns would make a duplicate detectable
  either way.

---
- coordinator: Left at suspected on purpose. The ordering the entry describes is real (`tools.py:2541` submits before the `Command` is returned, and `chat.py:870-883` raises before the `pending_approval` re-read), but whether the interrupt is cleared at node return or at checkpoint commit is a LangGraph semantics question that a code read cannot settle and the audit said as much. Settling it means a fault-injection run: make the checkpointer's write raise once, immediately after `submit()`, and see whether a second Approve reaches `submit()` again. That is Phase 5 work with the stack quiet and is scoped there; it has not been done, and the entry should not be acted on until it has.

### R-019: `scripts/update.sh --rollback` never moves the checkout back, and stamps the new image with the old commit
- surface: code:deploy
- class: bug
- severity: S2
- cause: CODE
- confidence: confirmed by reproducing the git semantics in a scratch repository — the git behaviour itself is confirmed empirically
- found by: audit:deploy
- scope: `scripts/update.sh` rollback path only. Checked for both branch and
  detached-HEAD checkouts; the detached case is correct. The forward-update
  path is unaffected. Not checked against a real deployment.
- repro: on a deployment made by `scripts/install.sh` (which `git clone`s, so
  HEAD is on branch `main`), run one successful `update.sh`, then
  `scripts/update.sh --rollback`. Expected: the checkout returns to the
  previous commit. Actual: HEAD stays where it is, the image is rebuilt from
  the *current* source, and the run reports a successful rollback.
- observed: `scripts/update.sh:559-564`

      CURRENT_BRANCH="$(git rev-parse --abbrev-ref HEAD)"
      if [ "$CURRENT_BRANCH" = "HEAD" ]; then
          git checkout --detach --quiet "$TARGET_SHA"
      else
          git merge --ff-only --quiet "$TARGET_SHA"
      fi

  On the rollback path `TARGET_SHA` is by construction an **ancestor** of
  HEAD (`scripts/update.sh:207-214` picks the last healthy commit out of
  `.update-log`). `git merge --ff-only <ancestor>` prints "Already up to
  date." and exits 0 without moving HEAD. Verified in a scratch repository:
  two commits, `git merge --ff-only <first>` from the second → exit 0, HEAD
  unchanged.
- expected: the rollback path should return the working tree to the recorded
  commit. `scripts/update.sh:54` documents `--rollback` as "go back to the
  last healthy commit", `check_destructive.sh:645` tells the operator "Code
  and frontend assets: fully reversible, update.sh --rollback", and
  `recovery_advice()` (`update.sh:427-429`) sends them there after a failed
  update.
- evidence: `scripts/update.sh:563` (`git merge --ff-only --quiet "$TARGET_SHA"`);
  `scripts/update.sh:191-220` (the rollback target resolution);
  `scripts/update.sh:588` (`export QC_AGENT_BUILD_COMMIT="$TARGET_SHA"`)
- pointer: two amplifiers make this worse than a no-op.
  (a) `QC_AGENT_BUILD_COMMIT` is exported as `TARGET_SHA` *before* the build,
  so the image is built from the un-rolled-back source and carries the OCI
  label of the commit it is not running. `deployed_commit()` then reports the
  old sha on every later run, and `update.sh <that sha>` answers "already up
  to date -- nothing to do".
  (b) `record_update updated` writes that same false pair into `.update-log`,
  so the *next* rollback also resolves against a fiction.
  The step even prints `ok "checked out $(git rev-parse --short HEAD)"` —
  the unchanged sha — directly under `step "moving the checkout to
  ${TARGET_SHA:0:12}"`, which is the one place an operator could have caught
  it.
- note: `tests/backend/deploy_01_rollback_target.py` covers the `awk` that
  chooses the target, not the git move, which is why this survived that work
  (`docs/trackers/2026-08-update-knows-what-it-runs.md` P3.2). The admin
  panel's Rollback button goes through the same path
  (`scripts/deploy_runner.sh:211`). Fix direction: on the rollback path use
  `git checkout --detach --quiet "$TARGET_SHA"` unconditionally (the
  subsequent forward update already handles a detached HEAD), and assert
  `git rev-parse HEAD` equals `TARGET_SHA` after the move rather than
  printing whatever HEAD happens to be.
- coordinator: `update.sh:561-565`: on a branch checkout, which `install.sh` always produces, the move is `git merge --ff-only --quiet "$TARGET_SHA"`. A fast-forward to an ancestor is by definition impossible, and git reports 'Already up to date' with exit 0. Reproduced: two empty commits, `merge --ff-only` to the first, exit 0, HEAD unchanged. The next line then prints `ok "checked out $(git rev-parse --short HEAD)"`, which is the commit it did not leave. `export QC_AGENT_BUILD_COMMIT="$TARGET_SHA"` at line 588 follows, so the image is built from the un-rolled-back source and stamped with the old commit, after which `deployed_commit()` reports a rollback that did not happen. The `--detach` branch at 562 is correct and is the one that never runs on a real deployment.
- resolution: fixed, pending commit
- regression test: tests/backend/deploy_07_update_rollback_and_backup.py

### R-020: `update.sh` exits 0 when the deployment never came up healthy, so the admin panel records a failed update as done
- surface: code:deploy
- class: bug
- severity: S2
- cause: CODE
- confidence: confirmed by code read
- found by: audit:deploy
- scope: `scripts/update.sh` verification block and its one programmatic
  caller, `scripts/deploy_runner.sh`. Not checked: whether anything else
  shells out to `update.sh`.
- repro: make the api fail to start (e.g. a syntax error in `server/main.py`),
  run an update through the admin panel. The deployment stays down; the panel
  shows `state: done, step: "updated"`.
- observed: `scripts/update.sh:656-699`. When `qc_wait_for_health` fails, the
  script warns, dumps 25 log lines, calls `recovery_advice`, writes
  `record_update unhealthy`, prints "updated, but it did not come up
  healthy", and falls off the end of `main`. The last command is an `echo`,
  so `main` returns 0 and the script exits 0.
- expected: a non-zero exit. `scripts/deploy_runner.sh:201-207` is written on
  the assumption that the exit status carries the verdict:

      if stdbuf -oL -eL bash scripts/update.sh "${args[@]}" "$target_sha" ...; then
          write_status "$dir" done "updated" ...
      else
          rc=$?; write_status "$dir" failed "the update did not complete" ...

  so a deployment that is down is reported to the admin's browser as a
  completed update.
- evidence: `scripts/update.sh:697` (`echo "${YEL}updated, but it did not come
  up healthy${RST} ..."`) is the last statement of `main`;
  `scripts/deploy_runner.sh:201`
- pointer: `.update-log` is written correctly (`unhealthy`), so only the
  process exit code and the panel are wrong. That split is what makes it
  survivable and also what makes it hard to notice.
- note: fix is one line — `exit 1` (or a captured status returned from
  `main`) on the unhealthy branch. Worth checking at the same time that
  `deploy_runner.sh` surfaces `log.txt`'s tail in the failure status, since
  the panel currently shows only `exit_code`.
- coordinator: After `warn "not healthy after 300s."` the script calls `recovery_advice`, then `record_update unhealthy`, prints where that was recorded, and falls off the end of `main` with status 0; there is no `exit 1` on that branch, where every earlier gate uses `die`. `scripts/deploy_runner.sh:201-203` then does `if ... bash scripts/update.sh ...; then write_status "$dir" done "updated"`, so the admin panel's progress overlay reports a completed update over a stack that did not come back. The `.update-log` entry says `unhealthy`, so the two records disagree, and the one the operator is looking at is the wrong one.
- resolution: fixed, pending commit
- regression test: tests/backend/deploy_07_update_rollback_and_backup.py

### R-021: `backup.sh --full` does not archive `data/plots`, `data/projects.json` or `data/scraped`, so a restore silently loses saved plots, every project archive, and the KB's own source
- surface: code:deploy
- class: bug
- severity: S2
- cause: CODE
- confidence: confirmed by code read, and acted on before the pre-review update
- found by: audit:deploy
- scope: `scripts/backup.sh` (both default and `--full`) against the
  directory inventory in `app/config.py:55-95`. Not checked: whether the
  operator additionally snapshots `/data` at the filesystem level, which the
  header suggests as an alternative.
- repro: `scripts/backup.sh --full`, then `tar -tzf <dest>/full_data.tar.gz |
  cut -d/ -f2 | sort -u` — the list is `jobs kb uploads geometry_uploads
  bug_reports molecules`. Save a plot in the app and repeat: the plot's
  `record.json` is not in the archive.
- observed: `scripts/backup.sh:212` `FULL_DATA_DIRS=(jobs kb uploads
  geometry_uploads bug_reports molecules)`, and the small-file loop at
  `scripts/backup.sh:195` `for f in data/threads.json; do`.
- expected: `--full` is documented as "an explicit, occasional,
  everything-included backup" and is what `update.sh:393` takes before every
  update. Three things under `data/` are neither in it nor regenerable:
  - `data/plots` — "saved plot records, one subdirectory per plot:
    record.json plus its rendered versions" (`app/config.py:71`,
    `app/plots/store.py:14`). First-class user objects with their own
    routes, quota accounting and owner directories.
  - `data/projects.json` — "project archives: named bundles of jobs"
    (`app/config.py:66`, `app/projects/registry.py`). This is exactly the
    same class of small, list-shaped, unrecoverable state as
    `data/threads.json`, which the script *does* copy for precisely the
    stated reason ("small, high-value, and genuinely lost if the disk
    goes").
  - `data/scraped` — the raw manual text (`app/config.py:59`). The script's
    own header justifies excluding `data/kb` by default on the grounds that
    it "is in any case reproducible from data/scraped via
    scripts/seed_knowledge_base.py" — but `data/scraped` is backed up in
    neither mode, so after a disk loss that reproducibility does not exist.
- evidence: `scripts/backup.sh:212`; `scripts/backup.sh:195`;
  `scripts/backup.sh:31-34` (the `data/kb` justification);
  `app/config.py:59,66,71`
- pointer: the list was written when `data/` had fewer children and has not
  been re-derived from `app/config.py` since projects and plots landed.
- note: `data/bse_basis_cache` is genuinely a cache (content-hashed, pure
  function of its inputs) and `data/deploy` is transient, so both are
  correctly out. `data/agent_checkpoints.sqlite` only matters for a
  no-Postgres deployment, which this script refuses to run against anyway.
  Fix direction: derive `FULL_DATA_DIRS` from a list kept next to
  `app/config.py`'s directory declarations, or at minimum add
  `plots`/`scraped` and put `projects.json` beside `threads.json`. A cheap
  guard: fail the backup if `ls data/` contains a directory the script does
  not know about.
- coordinator: `scripts/backup.sh:203`: `FULL_DATA_DIRS=(jobs kb uploads geometry_uploads bug_reports molecules)`, plus `data/threads.json` at 195. Present on this host and absent from that list: `data/plots` (548 KB, 14 files), `data/projects.json`, `data/scraped` (5.0 MB, 200 files), plus `agent_checkpoints.sqlite`, `verified`, `bse_basis_cache` and `deploy`. The header at lines 28-32 argues `data/kb` need not be archived because it is 'reproducible from data/scraped via scripts/seed_knowledge_base.py', and `data/scraped` is not archived either, so the argument defeats itself. This finding changed what the review did: a complete `data/` archive was taken by hand before `update.sh` ran, because the built-in backup would not have preserved the user's plots or projects.
- resolution: fixed, pending commit
- regression test: tests/backend/deploy_07_update_rollback_and_backup.py

### R-022: `restore.sh` ignores `.env` when choosing the database and swallows `pg_restore`'s exit status, so a restore can report success having restored nothing
- surface: code:deploy
- class: bug
- severity: S2
- cause: CODE
- confidence: confirmed by code read
- found by: audit:deploy
- scope: `scripts/restore.sh` only; compared against `scripts/backup.sh`,
  which handles the same question correctly and documents why.
- repro: on a deployment whose `.env` sets `QC_AGENT_POSTGRES_DB=nexusqc`,
  run `scripts/restore.sh <backup>` from a shell with no exported
  `QC_AGENT_*`. The prompt asks you to type `qc_agent`, and the restore runs
  against a database of that name.
- observed: two independent halves.
  (a) `scripts/restore.sh:63-64`

      PGUSER_VAL="${QC_AGENT_POSTGRES_USER:-qc_agent}"
      PGDB_VAL="${QC_AGENT_POSTGRES_DB:-qc_agent}"

  Environment only. `scripts/backup.sh:69-80,131-135` reads the same two
  values out of `.env` when the environment is empty, and the comment there
  spells out why ("cron and scripts/update.sh ... Neither exports .env").
  The backup's own `MANIFEST.txt` records `pg database:` / `pg user:`
  (`backup.sh:236-244`) and the restore reads neither.
  (b) `scripts/restore.sh:88-91`

      docker compose exec -T postgres pg_restore ... < "$DUMP" \
        || echo "(pg_restore reported errors -- review the output above; ...)"

  Every failure is absorbed into that one message, including
  "database ... does not exist", an authentication failure, or a restore
  that aborted half-way. The script then prints "Restore finished."
- expected: the two halves compose into the failure mode the file's own
  header warns about. A renamed database gives `pg_restore` a target that
  does not exist, the error is printed as expected noise, and the operator
  is told the restore finished — during an outage, which is the only time
  this script runs.
- evidence: `scripts/restore.sh:63,88,120`; `scripts/backup.sh:69-80`
- pointer: `--exit-on-error` is deliberately not set, and the reasoning
  given (DROP-on-missing-object noise from `--clean`) is sound. But
  "expected noise" and "the restore did not happen" are being conflated;
  they are distinguishable.
- note: fix direction — read `.env` for user/db exactly as `backup.sh` does
  (or read them out of `MANIFEST.txt`, which is more faithful to the dump),
  and verify afterwards rather than trusting the exit code: the script
  already prints a `SELECT count(*) FROM users;` for the operator to run by
  hand, so run it and compare against `pg_restore --list`'s table count.
- coordinator: Two defects, both verified. (1) `scripts/restore.sh:97`: `pg_restore ... < "$DUMP" || echo "(pg_restore reported errors -- review the output above ...)"`. Under `set -euo pipefail` the `|| echo` converts any failure, including a dump that could not be read at all, into a printed remark and a continuing script that ends by telling the operator how to check the row count. (2) `restore.sh:70` reads `PGDB_VAL="${QC_AGENT_POSTGRES_DB:-qc_agent}"` from the environment only, where `backup.sh:142-143` goes through `envget QC_AGENT_POSTGRES_DB` to read `.env`. A deployment that renamed its database in `.env` is backed up from the right database and restored into the wrong one.
- resolution: fixed, pending commit
- regression test: tests/backend/deploy_07_update_rollback_and_backup.py

### R-023: `update.sh` traps only EXIT, so a Ctrl-C during the drain can leave job admission paused — and maintenance mode on — with nothing scheduled to undo it
- surface: code:deploy
- class: bug
- severity: S2
- cause: CODE
- confidence: confirmed by code read against the installer's own precedent — the bash behaviour is asserted
  empirically by this repository's own installer audit
- found by: audit:deploy
- scope: `scripts/update.sh`'s EXIT trap and the two flags it exists to clear.
  `scripts/install.sh` has the fix; `update.sh` did not get it.
- repro: `scripts/update.sh --drain` with a job running, then Ctrl-C at the
  "waiting for N in-flight job(s)" line. Then check
  `select * from app_config where key='job_admission_paused'`.
- observed: `scripts/update.sh:504`

      trap 'leave_maintenance; restore_admission' EXIT

  and nothing for INT or TERM. The drain then prints, at
  `scripts/update.sh:519`, `info "waiting for ${INFLIGHT} in-flight job(s);
  Ctrl-C is safe, admission is restored on exit"`.
- expected: commit `a91e352` ("Trap the interrupt, and stop the override diff
  being a date change", 2026-09-10) fixed exactly this in `install.sh`, and its
  message records the behaviour as observed rather than reasoned: "The
  installer trapped only EXIT, and bash does not reliably run an EXIT trap when
  it is killed by a signal it does not handle -- it re-raises and dies -- so
  the one message the trap exists to print was exactly the one that never
  appeared." `install.sh` now carries `trap 'on_signal 2' INT` and
  `trap 'on_signal 15' TERM` alongside its EXIT trap.
- evidence: `scripts/update.sh:504,519`; `scripts/install.sh` `on_signal()` and
  its three traps; `git show a91e352`
- pointer: in `install.sh` the consequence was a missing message. Here it is
  persistent state in the database. `job_admission_paused` left set means every
  new job queues as `pending` forever, and the script's own comment
  (`update.sh:508-513`) explains that this flag was chosen specifically because
  it is *not* the admin-facing concurrency setting — so there is no console
  control to notice or clear it. With `--maintenance` the same interrupt can
  leave `maintenance_mode` set, which 503s every non-admin.
- note: the drain is the most likely thing anyone ever interrupts, because it
  can wait four hours by default, and the script explicitly tells them it is
  safe to do so. Fix: give `update.sh` the same INT/TERM handlers, ideally by
  moving `install.sh`'s `on_signal` into `scripts/lib/common.sh`, which both
  already source. What would settle the bash question either way:
  `bash -c 'trap "echo TRAP" EXIT; sleep 30' &` then `kill -INT %1`.
- coordinator: `scripts/update.sh:504`: `trap 'leave_maintenance; restore_admission' EXIT`, and nothing for INT or TERM. `scripts/install.sh:321-323` traps all three, and the commit that added them (`a91e352`, 2026-09-10) explains why from a real run: 'Ctrl-C during the build printed nothing at all ... bash does not reliably run an EXIT trap when it is killed by a signal it does not handle -- it re-raises and dies.' The same class stands in `update.sh` ten days later, and the consequence is worse than a missing message: the EXIT trap is what clears `maintenance_mode` (every user sees 503) and un-pauses job admission. `tests/install_interactive.py` already knows how to send the signal to a process group; the same test does not exist for `update.sh`.
- resolution: fixed, pending commit
- regression test: tests/backend/deploy_07_update_rollback_and_backup.py

### R-024: `backup.sh`'s retention pass deletes *any* subdirectory of `QC_AGENT_BACKUP_DIR` older than the retention window, not only its own backups
- surface: code:deploy
- class: bug
- severity: S2
- cause: CODE
- confidence: confirmed by code read, and it applies to this review's own backup
- found by: audit:deploy
- scope: the retention block at the end of `scripts/backup.sh`. Not run.
- repro: `mkdir -p "$QC_AGENT_BACKUP_DIR/someone-elses-archive"`, set its mtime
  to 40 days ago, run `scripts/backup.sh`. The directory is gone.
- observed: `scripts/backup.sh:248`

      pruned="$(find "$BACKUP_ROOT" -mindepth 1 -maxdepth 1 -type d -mtime "+${RETAIN_DAYS}" -print -exec rm -rf {} + 2>/dev/null | wc -l)"

  No name filter, no check that the directory is one of this script's own
  (which are named `YYYYmmdd-HHMMSS` and always contain `MANIFEST.txt`).
- expected: `docs/DEPLOYMENT.md:562` tells the operator to "Point
  `QC_AGENT_BACKUP_DIR` at a filesystem with real room (not wherever
  `/var/lib/docker` sits)", which invites pointing it at a general-purpose
  archive location rather than a directory this script owns. On this host
  `CLAUDE.local.md` records it pointing at a sibling directory
  (`NexusQC-dev-data-backup`). Anything else parked there and untouched for
  `QC_AGENT_BACKUP_RETAIN_DAYS` is deleted, from cron, nightly.
- evidence: `scripts/backup.sh:248`; `docs/DEPLOYMENT.md:562-564`;
  `CLAUDE.local.md` ("this checkout's `.env` does point `QC_AGENT_BACKUP_DIR`
  at `NexusQC-dev-data-backup`")
- pointer: the same block's sibling, `chmod 700 "$BACKUP_ROOT"`
  (`scripts/backup.sh:120`), silently re-locks the whole directory on every
  run, which is the other half of "this script assumes it owns that path".
- note: this is the standing never-blind-purge rule in a script that runs
  unattended. Fix: constrain the find with
  `-name '[0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9]-[0-9]*'`, or require
  `MANIFEST.txt` inside the candidate before removing it. Cheap either way,
  and it also makes the printed `pruned` count honest.
- coordinator: `scripts/backup.sh:248`: `find "$BACKUP_ROOT" -mindepth 1 -maxdepth 1 -type d -mtime "+${RETAIN_DAYS}" -print -exec rm -rf {} +`. There is no name filter, so any directory in the backup root older than the retention window goes, whatever put it there. Concretely: the complete `data/` archive this review took on 2026-09-11 lives at `${QC_AGENT_BACKUP_DIR}/pre-review-supplement-20260911T164640/` and will be deleted by the next cron backup after 30 days. That is a user-data-loss path from the one script whose job is the opposite.
- resolution: fixed, pending commit
- regression test: tests/backend/deploy_07_update_rollback_and_backup.py

### R-025: `--full` archives `data/jobs` while jobs are writing into it, and `update.sh` takes that backup *before* the drain — so the drained-update path aborts exactly when it is needed
- surface: code:deploy
- class: bug
- severity: S2
- cause: CODE
- confidence: confirmed by code ordering
- found by: audit:deploy
- scope: `scripts/backup.sh`'s `--full` tar and its one automated caller,
  `scripts/update.sh:399`. Not reproduced; GNU tar's exit status is the load-
  bearing assumption.
- repro: with a job actively writing output, run `scripts/backup.sh --full`.
  GNU `tar -czf` prints "file changed as we read it" and exits 1.
- observed: `scripts/backup.sh:214` runs

      tar -C "$REPO_ROOT" -czf "${DEST}/full_data.tar.gz" "${EXISTING_DIRS[@]}"

  bare, under `set -euo pipefail`, with `data/jobs` in `EXISTING_DIRS`. A
  non-zero tar aborts the script. `scripts/update.sh` then reaches

      die "backup failed -- refusing to update without one."

  at line 405.
- expected: the ordering makes this worst in the one case it matters. In
  `update.sh` the backup is at line 399 and the drain does not start until line
  506, so `--drain` — which a person only passes *because* jobs are running —
  tars a live `data/jobs` every time. The tracker's end-to-end run
  (`docs/TRACKER.md`, the installer audit) was against a scratch deployment,
  where there was nothing in flight to trip it.
- evidence: `scripts/backup.sh:212-227`; `scripts/update.sh:393-407`;
  `scripts/update.sh:506`
- pointer: GNU tar's exit 1 means "some files differ", which for a running job
  is expected rather than a corrupt archive — and the script already has a
  real integrity check immediately after (`tar -tzf`), so the exit status is
  not carrying the weight it appears to.
- note: two independent fixes, and both are worth having. Move the `--full`
  backup after the drain in `update.sh` (it is also faster once nothing is
  writing), and treat tar exit 1 as a warning in `backup.sh` while keeping
  exit ≥ 2 fatal and keeping the `tar -tzf` verification as the real gate.
  What would settle it: run `scripts/backup.sh --full` on a scratch stack with
  one job writing.
- coordinator: `update.sh:393` is `step "backing up before changing anything"` and runs `backup.sh --full`; the drain (`step` at ~516, admission paused, then waiting on running jobs) comes after it. So under `--drain`, which exists precisely for the case where jobs are running, the archive is taken over `data/jobs` while those jobs are still writing status and output. `backup.sh:209` runs `tar -czf` with no `--warning=no-file-changed` or `--ignore-failed-read`; GNU tar exits 1 when a file changed while being read, `backup.sh` runs under `set -e`, and `update.sh:405` turns a backup failure into `die "backup failed -- refusing to update without one."`. Net effect: `--drain` on a busy deployment refuses to update, for a reason unrelated to the jobs it was asked to wait for. Not reproduced live; the ordering alone is sufficient.
- resolution: fixed, pending commit
- regression test: tests/backend/deploy_07_update_rollback_and_backup.py

### R-026: `docs/DEPLOYMENT.md`'s by-hand admin bootstrap command is missing two required arguments and cannot run
- surface: code:deploy
- class: docs
- severity: S2
- cause: CODE
- confidence: confirmed by comparing the doc to the argparse definition
- found by: audit:deploy
- scope: `docs/DEPLOYMENT.md` step 7 and the lockout-recovery section that
  refers back to it. `scripts/install.sh` gets it right.
- repro: `docker compose run --rm api python -m server.admin_cli bootstrap-admin
  --email you@yourlab.edu --username admin` → argparse exits 2 with "the
  following arguments are required: --first-name, --last-name".
- observed: `docs/DEPLOYMENT.md:344-347` gives exactly that command;
  `server/admin_cli.py:146-151` declares `--email`, `--username`,
  `--first-name` and `--last-name` all `required=True`.
- expected: step 7 is the last step of the documented by-hand install and the
  second half of lockout recovery (`DEPLOYMENT.md:420`, "Then bootstrap a fresh
  admin, as in step 7"). Someone reaching for it is either standing up a
  deployment or locked out of one. `scripts/install.sh:957-959` passes all four
  flags plus `--password-stdin`.
- evidence: `docs/DEPLOYMENT.md:345`; `server/admin_cli.py:149-150`;
  `scripts/install.sh:957-959`
- pointer: the first/last-name arguments were added to the CLI and the
  installer, and the hand-run documentation was not updated with them.
- note: the doc also says "It prompts for a password", which is worth
  confirming at the same time — the installer uses `--password-stdin` instead,
  so the interactive prompt path may be the less-exercised one.
- coordinator: `docs/DEPLOYMENT.md:345-346` prints `bootstrap-admin --email you@yourlab.edu --username admin`. `server/admin_cli.py` declares `--email`, `--username`, `--first-name` and `--last-name` all `required=True`. The documented command exits with an argparse error before prompting for anything. Class docs; it is the one command the doc offers for recovering a deployment with no admin.
- resolution: fixed, pending commit
- regression test: tests/backend/deploy_07_update_rollback_and_backup.py

### R-027: A job opened from the Job Manager stops updating in the drawer while SSE is connected, because `job_update` only reaches the owning thread's stream

- surface: code:frontend
- class: bug
- severity: S2
- cause: CODE
- confidence: suspected (code read), not yet reproduced
- found by: audit:frontend
- scope: Checked `lib/queries.ts` (`useJobQuery`, `useJobsListQuery`), `lib/sse.ts`, `app/agent/job_watcher.py`'s emit path, and every call site of `jobQueryKey`. Engine-independent: this is the drawer's cache policy, identical for PySCF/ORCA/BAGEL and every task. Not checked live in a browser.
- repro: Open conversation A. From the Job Manager panel (which is cross-conversation by design) click a *running* job belonging to conversation B, or a job submitted outside any conversation. Watch the drawer. The Job Manager row behind it turns green on its own 4 s poll; the open drawer's header keeps saying `running`, its Live output keeps ticking, and no summary or artifacts ever appear. Close and reopen the drawer and everything is there.
- observed: `frontend/src/lib/queries.ts:87-95`

  ```ts
  return useQuery({
    queryKey: jobQueryKey(jobId ?? ""),
    queryFn: () => api.getJob(jobId as string),
    enabled: !!jobId,
    refetchInterval: (query) => {
      if (sseConnected) return false;
      return isNonTerminal((query.state.data as JobRow | undefined)?.status) ? 4000 : false;
    },
  });
  ```

  `sseConnected` is a single global boolean set by `useThreadEvents` for the **active** thread (`lib/sse.ts:41,50`). The only thing that invalidates `["job", jobId]` anywhere in the app is that same per-thread stream (`lib/sse.ts:99`, and a `grep` for `jobQueryKey` / `["job",` finds no other invalidation — only `KillButton.tsx:28`'s optimistic `setQueryData`).

  On the server, the event is emitted per thread and only for that thread's own active jobs — `app/agent/job_watcher.py:463-479`:

  ```python
  for entry in thread_registry.list_threads():
      thread_id = entry["thread_id"]
      active_job_ids = entry.get("active_job_ids", [])
      if not active_job_ids:
          continue
      ...
          self._emit(thread_id, {
              "type": "job_update", "job_id": job_id, ...
          })
  ```

  So the client subscribes to `/api/threads/{activeThreadId}/events` and receives `job_update` **only** for jobs in that thread's `active_job_ids`. A job owned by another conversation, a job with no owning thread at all (deliberately visible to everyone, per the settled design), and a job whose thread has already had its summary turn and cleared `active_job_ids`, all produce no event on the open stream — yet `sseConnected` is true, so the poll fallback is disabled.
- expected: The drawer should reach a terminal status without user intervention. `queries.ts:83-85`'s own comment states the assumption ("normally `sse.ts` invalidates `["job", jobId]` on that job's own `job_update` event, so an open `JobDetailDrawer` doesn't need to poll at all while connected"), and that assumption holds only for jobs of the currently-open conversation. The architecture's "polling is separated from expensive rendering" section says job status is polled against the lock-free routes precisely so a tab is never stalled — the lock-free route is there to be called.
- evidence: `frontend/src/lib/queries.ts:82-96`; `frontend/src/lib/sse.ts:91-108`; `app/agent/job_watcher.py:461-479`.
- pointer: `sseConnected` answers "is *a* stream open", not "does that stream carry this job". The gate needs the second question.
- note: What would settle it: open two conversations, submit a job in one, open it from the Job Manager while the other is active, and watch. Partial mitigations that make it intermittent rather than permanent, and that are worth knowing before reproducing: TanStack's `refetchOnWindowFocus` defaults to true, so alt-tabbing away and back refetches after the 10 s `staleTime`; and if the SSE connection ever drops, the fallback poll switches on. The misleading part is the combination — `LiveLogPanel` is gated on `job.status === "running"` (`JobDetailDrawer.tsx:451`), so with a stuck status it polls the log forever and the user watches the engine's output finish under a header that still says the job is running. Fix direction: make the gate per-job rather than global (e.g. only disable the interval when the job's `thread_id` is the active thread), or simply always poll a non-terminal job at 4 s and let the SSE invalidation be the fast path — the route is lock-free and the cost is the same one `useJobsListQuery` already pays unconditionally.

---

### R-028: the registry offers and routes ten (task, method, engine) cells whose input builder refuses them
- surface: code:jobs
- class: bug
- severity: S2
- cause: CODE
- confidence: confirmed by executing supports() and route_engine() for all ten cells
- found by: audit:jobs
- scope: all three engines, whole `TASKS` × `CANONICAL_METHODS` cross-product. Master tasks excluded. `blind`+`basis` and `single_point/ee`+`n_states` rows my first sweep produced were artifacts of my own parameter fixture and are excluded from the list below.
- repro:
  ```
  cd /data/qcuser/9.NexusQC/NexusQC-dev-repo && PYTHONPATH=$PWD \
  QC_AGENT_LLM_BASE_URL=http://localhost:11434/v1 \
  /home/qcuser/apps/miniconda3/envs/qc-agent/bin/python3 -c '
  from app.chemistry.registry2.elicitation import validate_draft
  MOL={"symbols":["O","H","H"],"coords":[[0,0,0],[0,0,0.96],[0.93,0,-0.24]],"charge":0,"multiplicity":1}
  for d in [{"task":"single_point","subtype":"gs","method":"eom_ccsd","params":{"basis":"sto-3g"}},
            {"task":"opt","subtype":"min","method":"mp2","params":{"basis":"sto-3g"}},
            {"task":"opt","subtype":"min","method":"ccsd","params":{"basis":"sto-3g"}},
            {"task":"freq","subtype":"","method":"mp2","params":{"basis":"sto-3g"}}]:
      d["molecule"]=MOL; print(d["task"], d["method"], validate_draft(d, {"molecule":MOL}, check_external=False).status)'
  ```
  prints `ready` for all four. Feeding the same specs to `app.chemistry.jobs.preview.build_input_preview` raises.
- observed: `supports()` returns True and `route_engine()` actively picks an engine for each of:
  | task/subtype | engine | method | what the builder raises |
  |---|---|---|---|
  | `opt/min`, `opt/constrained` | pyscf (**default route**) | `mp2`, `ccsd` | `Unsupported method 'mp2' for PySCF (use 'hf' or 'dft')` — `pyscf_runner.build_mf`, reached from `run_geometry_optimization`'s final `build_mf(mol, method, ...)` at `pyscf_runner.py:1190` |
  | `opt/min`, `opt/constrained`, `opt_freq`, `freq`, `neb_ts` | orca | `mp2` | `Unsupported method 'mp2' for ORCA (use 'hf' or 'dft')` — `orca_runner._method_line` |
  | `neb_ts` | orca | `casscf` | same |
  | `opt/min`, `opt_freq` | bagel | `hf` | `BAGEL geometry optimization in this app only supports method='casscf' or 'caspt2'` |
  | `single_point/gs` | pyscf (**default route**), orca | `eom_ccsd` | `dispatch.resolve_runner` returns the plain `single_point` runner (the `eom_ccsd` branch is gated on `subtype == "ee"`), which then rejects the method |
  `route_engine("mp2", "opt", "min")` → `pyscf` with reason *"PYSCF is the preferred engine for this combination; ORCA could also run it"*; `route_engine("eom_ccsd", "single_point", "gs")` → `pyscf`; `route_engine("mp2", "freq", "")` → `orca` *"the only one here that can run it"*.
- expected: `docs/ARCHITECTURE.md` — "`supports()` is derived from that pairing and is never hand-enumerated … there is no allow-list". `_method_line`'s `hf`/`dft`-only rule and `bagel_runner`'s `"only supports method='casscf' or 'caspt2'"` are exactly the hardcoded capability knowledge `registry2` is supposed to be the single source of truth for (brief item 5), and they have drifted from it. Several of these cells rest on `manual` evidence — `orca/mp2 hessian="analytic"` ("documented; not executed here for MP2"), `pyscf/{mp2,ccsd} constrained_opt=True` ("geomeTRIC drives any method exposing a gradient; run here with HF") — which is the failure mode `docs/ARCHITECTURE.md` records for `orca/casscf excited_gradient`: "an untested claim that routes is worse than no claim".
- evidence: `app/chemistry/jobs/orca_runner.py:220-232` (`_method_line`); `app/chemistry/jobs/pyscf_runner.py:1190` and `build_mf`; `app/chemistry/jobs/bagel_runner.py:183-188`; `app/chemistry/jobs/dispatch.py::resolve_runner` (the `eom_ccsd` test sits inside `if subtype == "ee"`); `app/chemistry/registry2/capabilities.py:602-612` (`orca/mp2`)
- pointer: capability rows describe the *engine*; the builders describe *this app*. `docs/ARCHITECTURE.md` says a cell must describe what this app can deliver.
- note: two independent fixes. (a) Make the builders' scope declarative — a `methods=` allow-list on the `TaskDef`s, or downgrade the offending rows to `gap` with the diff recorded, exactly as `orca/casscf excited_gradient` was. (b) `resolve_runner` should test `method == "eom_ccsd"` before the `subtype` test, matching what `docs/ARCHITECTURE.md` says ("`eom_ccsd` is its own method value (on `single_point/gs` or `single_point/ee`)"). A cheap standing guard: fold the `build_input_preview` sweep above into `scripts/check_capability_matrix.py` as a sixth check.
- coordinator: Independently re-run with `supports(engine, method, task, subtype)` and `route_engine(method, task, subtype, requested_engine=engine)`: **10 of 10** return `ok=True` and pick the named engine. The runners refuse the same ten: `orca_runner._method_line` raises `Unsupported method 'mp2' for ORCA (use 'hf' or 'dft')` and likewise for `casscf` on `neb_ts`; `pyscf_runner.build_mf` accepts only hf/dft; BAGEL optimisation accepts only casscf/caspt2. So the approval card is raised, approved, and the job fails at dispatch, which the first backlog tracker names as the one failure mode the gate exists to prevent. A first attempt at this check passed the arguments in the wrong order and returned False for all ten; recorded because it is the reason a summary is never trusted without a re-run. S2 stands: it fails loudly rather than silently, but on a method the app said it could do.

### R-029: cancelling a master job erases its `path_xyz` / `ensemble_xyz` artifact pointers, so the geometries become unreachable
- surface: code:jobs
- class: bug
- severity: S2
- cause: CODE
- confidence: confirmed by code read
- found by: audit:jobs
- scope: every master task (`pes_1d`, `interp_pes`, `wigner_spectra`, `batch`) on every engine. Not an issue for ordinary jobs, whose runners had written no artifacts by the time they were cancelled.
- repro: submit a 5-point scan, cancel it while running, then try to open its frame slider / download its path / start a job from image 3.
- observed: `JobManager.cancel`'s master branch writes
  ```
  write_result(JobResult(job_id, "cancelled", error="Cancelled by user.",
                          summary=(read_result(job_id) or {}).get("summary", {})))
  ```
  (`base.py:1562-1564`). `summary` is carried over; `artifacts` is not — `JobResult.artifacts` defaults to `{}`, so `path_xyz` (written by `submit_scan`/`submit_batch`) and `ensemble_xyz` (written by `submit_ensemble`), plus any `pes_plot`/`ensemble_spectrum_data`, are dropped from `result.json`.
- expected: every reader resolves these through the artifacts dict, not through the fixed filename: `scan_orchestrator.py:206`, `batch_orchestrator.py:141` (`(master_result or {}).get("artifacts", {}).get("path_xyz")`), `server/routes/chat.py:285`, `server/routes/jobs.py:89-90`, and `registry2/tasks.py:507-510`'s `path_xyz`/`ensemble_xyz` map. The file itself is still on disk, so this is a lost pointer to real data — the brief's S1 category "a result that cannot be found later"; I file it S2 only because it needs a cancellation to trigger.
- evidence: `app/chemistry/jobs/base.py:1562-1564`
- pointer: `JobResult` has a mutable-default-shaped API where omitting a field means "erase it", and this is the one call site that rebuilds a result from a partial read.
- note: `artifacts=(read_result(job_id) or {}).get("artifacts", {})` alongside the existing summary carry-over. Same shape of bug, lower stakes, in `_watch_orphan_worker`'s two failure writes and `_run_inner`'s failure writes.
- coordinator: `base.py:1562-1564`, verbatim: `write_result(JobResult(job_id, "cancelled", error="Cancelled by user.", summary=(read_result(job_id) or {}).get("summary", {})))`. `summary` is carried across from the existing result; `artifacts` is not named, and `JobResult.artifacts` is `field(default_factory=dict)`, so the rewritten `result.json` has `artifacts: {}`. The files a scan or ensemble master already wrote (`path_xyz`, `ensemble_xyz`, `pes_plot`, `ensemble_spectrum_data`) remain on disk with nothing pointing at them, which is 'a result that cannot be found afterwards' in the leave-and-return sense, for the completed part of a cancelled batch. Reproducible live in P3.5 by cancelling a scan after its first child completes.

### R-030: ORCA oscillator strengths are parsed with a singlet-only row pattern, so any open-shell job silently reports none
- surface: code:jobs
- class: bug
- severity: S2
- cause: CODE
- confidence: confirmed by code read
- found by: audit:jobs
- scope: ORCA only, and all three of its intensity paths — `run_tddft`, `run_eom_ccsd`, `run_casscf`. PySCF gets intensities from objects, BAGEL from its own `Oscillator strength for transition between N - M` line, so neither is affected. I did **not** find a committed multiplicity>1 ORCA output to check against; `data/verified/` holds only `orca_functionals.txt`.
- repro: run any ORCA `single_point/ee` on a triplet (`multiplicity=3`) and read `summary.oscillator_strengths` — expect all `None`. Or, cheaper: `grep -n "0-1A" $(any real ORCA triplet output)`; ORCA labels those rows `0-3A -> 1-3A`.
- observed:
  ```
  _ABSORPTION_ROW = re.compile(
      r"0-1A\s*->\s*\d+-1A\s+-?\d+\.\d+\s+-?\d+\.\d+\s+-?\d+\.\d+\s+(-?\d+\.\d+)"
  )
  ```
  (`orca_runner.py:100-102`). The `1` in `0-1A`/`N-1A` is the state's *multiplicity*, hardcoded to singlet. On no match, each caller pads: `osc if len(osc) == len(ev) else osc + [None] * (len(ev) - len(osc))` (`orca_runner.py:1484`, `:1523`, `:1576`) — an empty list becomes all-`None` with no warning anywhere.
- expected: `docs/ARCHITECTURE.md` §Engine integration and the capability table both claim oscillator strengths for `orca/hf`, `orca/dft`, `orca/eom_ccsd` and `orca/casscf` without a multiplicity caveat, and the `wigner_spectra` task *requires* `osc_strengths` and force-routes CASSCF to ORCA for exactly that reason. A triplet Wigner ensemble therefore runs every sample and ends on "No sample contributed a usable (energy, oscillator strength) pair to pool" — the exact failure the requirement was added to prevent. The app already knows non-singlets reach this code: `_dominant_transitions_orca` is explicitly documented as restricted-only.
- evidence: `app/chemistry/jobs/orca_runner.py:100-102`; padding at `:1484` (tddft), `:1523` (eom_ccsd), `:1576` (casscf)
- pointer: a regex derived from one real run (a singlet) generalised to a class it does not cover, and a padding rule that turns "did not parse" into "engine does not report it".
- note: partial confirmation without a run — `grep -rhoE "[0-9]+-[0-9][A-Za-z']+ *-> *[0-9]+-[0-9][A-Za-z']+" data/scraped/orca/` returns rows including `0-1A  -> 10-3A` and `0-1A  ->  1-3A`, so the digit after the dash is unambiguously the state's multiplicity and the manual's own examples already contain values other than 1. What is still unconfirmed is only the left-hand side for a genuinely open-shell reference, which one water-triplet ORCA TDDFT run would settle. A second consequence falls out of the same evidence: on any run that computes singlets AND triplets, `_TDDFT_STATE` collects every state while `_ABSORPTION_ROW` collects only the singlet rows, and the padding then appends the Nones at the END — so the singlet intensities are silently attached to the wrong states. This app's own `_tddft_block` never asks for triplets, but a hand-edited input on a `tddft` job reaches the same parser through `_effective_input_text`. Fix direction: `r"0-(\d+)([A-Za-z0-9']+)\s*->\s*\d+-\1\2\s+..."`, and make an empty match raise inside `_safe_parse` rather than pad, so a parse failure is distinguishable from a genuine absence.
- coordinator: `orca_runner.py:100`: `_ABSORPTION_ROW = re.compile(r"0-1A\s*->\s*\d+-1A\s+...")`. The `1A` after the hyphen is ORCA 6's multiplicity-plus-irrep label, so the pattern admits singlet-to-singlet rows only. A doublet ground state prints `0-2A -> 1-2A` and matches nothing; both call sites (`:1463`, `:1522`) then get `osc = []` with no warning. Scope: every open-shell excited-state job on ORCA, and by extension any Wigner ensemble built on one, which is where the audit says it surfaces as 'No sample contributed'. Worth a live reproduction in P5 on a doublet, since the label format is version-specific and the parsers here are meant to be derived from real output.

### R-031: startup reconciliation can overwrite a `result.json` written in the window between its own read and its `failed` write
- surface: code:jobs
- class: bug
- severity: S2
- cause: CODE
- confidence: confirmed by code read
- found by: audit:jobs
- scope: all engines; `_reconcile_orphaned_jobs` case 4 only (worker pid recorded but not alive-and-verified).
- repro: hard to force deliberately — kill the backend while a job is in its final `write_result`, restart immediately. The window is the several file reads between `read_result` and the `write_result(... "failed" ...)`.
- observed: the loop reads `result = read_result(job_id)` at `base.py:1118`, then does `read_spec`, `is_master_spec` (which imports `registry2.tasks`), `read_meta` and `_pid_is_same_process` (a `psutil.Process` lookup), and only then, at `base.py:1158-1165`, writes both a `failed` status and a `failed` `result.json` — clobbering whatever the worker may have written in between. `write_result` does not check the existing file.
- expected: the whole point of case 1 is that a worker's own result is authoritative; a worker that lands its result microseconds late should be treated as case 1, not case 4. This is the only path in the module that *replaces* a terminal result rather than syncing to it.
- evidence: `app/chemistry/jobs/base.py:1118` (`result = read_result(job_id)`) → `:1158-1165` (the `failed` write)
- pointer: read-then-write with no re-read at the point of decision, on the one branch that destroys data.
- note: re-read `result.json` immediately before the `failed` write and fall back to case 1 if it is now terminal. Cheap and complete.
- coordinator: `base.py:1118` reads `result = read_result(job_id)`; between there and `:1158-1165` the loop calls `read_spec`, `is_master_spec` (a registry import), `read_meta` and `_pid_is_same_process` (a `psutil.Process` lookup), and only then writes a `failed` status and a `failed` `result.json`. `write_result` (verified) canonicalises and writes; it never checks whether a terminal result already exists. A worker that lands its `completed` result inside that window has it replaced. The window is milliseconds and the trigger is a restart, so this is rare; it is also the only branch in the module that replaces a terminal result rather than syncing to one, and the fix is a one-line re-read before the write.

### R-032: The Redis session client has no socket timeout, and it is on the path of every authenticated request
- surface: code:server
- class: bug
- severity: S2
- cause: CODE
- confidence: confirmed by grep
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
- coordinator: `app/auth/redis_session.py:40`: `redis.Redis.from_url(REDIS_URL, decode_responses=True)`, no `socket_timeout`, no `socket_connect_timeout`. `get_client()` is on the path of `get_current_user`, so every authenticated request. A Redis that accepts the TCP connection and then stalls holds the request thread indefinitely.

### R-033: Every open SSE stream permanently occupies one of anyio's 40 default threadpool tokens
- surface: code:server
- class: perf
- severity: S2
- cause: CODE
- confidence: confirmed by code read
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
- coordinator: `server/sse.py:107` `def event_stream(thread_id) -> Iterator[str]` is a synchronous generator, and `server/routes/chat.py:731` hands it to `StreamingResponse`. Starlette iterates a sync generator through `iterate_in_threadpool`, one `to_thread.run_sync(next, it)` per item, and each `next()` blocks in `q.get(timeout=_KEEPALIVE_SECONDS)` at `:113` with `_KEEPALIVE_SECONDS = 15.0`, so a stream holds a token almost continuously. `sse.py:8` acknowledges the generator runs in the threadpool. `grep -rn 'total_tokens|CapacityLimiter|to_thread' app server` returns nothing, so the pool is anyio's default 40 and it is the same pool every plain-`def` route handler runs on. A ceiling rather than a defect today; P4.3 can measure it by opening tabs until `/api/health` latency moves.

### R-034: A submission in a mixed tool batch produces no confirmation at all — the app's node is skipped and the tool text forbids the model from saying anything
- surface: code:agent
- class: bug
- severity: S3
- cause: CODE
- confidence: suspected (code read), not yet reproduced
- found by: audit:agent
- scope: both branches of `_finish_submission` (success and rejection).
  Traced `_receipts_this_step` / `_after_tools` in `graph.py:536-597`.
- repro: get the model to emit `check_job_status` and `submit_draft` in
  one batch — `docs/ARCHITECTURE.md:432` says real conversations do this
  — and approve the card. The job starts and nothing on screen says so.
- observed: `_submissions_this_step` requires every trailing tool_call_id
  in the batch to carry a receipt (`graph.py:569-573`), so a mixed batch
  returns `[]`, `_after_tools` routes to `"agent"` (`graph.py:593-597`),
  and `_job_submitted_node` — the only writer of "Started X. Job id Y."
  — never runs. But the ToolMessage the model then reads ends with
  (`tools.py:2580-2582`):
  `"The user has already been shown a confirmation that this job is running -- do not announce it again."`
  which is false in this case. The rejection branch has the same shape at
  `tools.py:2362-2368`: *"The user has already been shown a message
  saying so and asking what they would like to change, so do not ask
  again and do not resubmit."*
- expected: `docs/ARCHITECTURE.md:428-433` says a mixed batch routes to
  the model *"because those are exactly the results that need relaying"*.
  The tool text should be conditional on whether the node will actually
  run, or the instruction should be softened to "if the app has not
  already confirmed this, say so".
- evidence: `app/agent/tools.py:2580-2582`; `app/agent/graph.py:569-573`
  and `:593-597`; `docs/ARCHITECTURE.md:428-433`.
- pointer: the receipt/`pending_submissions` mechanism knows about the
  mixed-batch case; the ToolMessage prose, written on the assumption that
  the node always runs, does not.
- note: worst case for the user is a job that started with no
  acknowledgement anywhere in the chat — which is the same silence the
  `job_submitted` node was introduced to remove. Settled by driving a
  turn that emits both calls (or by writing the state directly) and
  reading the transcript.

---

### R-035: The system prompt tells the model not to ask for a basis set before an active-space search, but the tool cannot be called without one
- surface: code:agent
- class: bug
- severity: S3
- cause: CODE
- confidence: suspected (code read), not yet reproduced
- found by: audit:agent
- scope: `active_space` and the two functions it dispatches to. Every
  other tool name, argument and source string in `prompts.py` was checked
  against `STATIC_TOOLS` and against `registry2` and is correct.
- repro: ask "what active space should I use for benzene". The prompt
  says not to ask about a basis; the tool schema has `basis` as a
  required string; the model must either ask anyway or invent one.
- observed: `app/agent/prompts.py:116-119`:
  *"**Active spaces: the active_space tool, not the three above.** … Do
  not ask for a basis set first: the recommendation does not depend on
  one. Ask how many states they want, since that does change the answer."*
  `app/agent/tools.py:2923-2930`:
  `def active_space(basis: str, n_excited_states: int, active_electrons: Optional[int] = None, ...)`
  — `basis` is the first positional parameter with no default, so it is
  required in the bound schema. The tool's own docstring then says the
  opposite of the prompt (`tools.py:2944-2946`): *"Ask the user how many
  excited states and which basis they are targeting FIRST"*, as does
  `search_active_space_literature`'s (`tools.py:3534-3538`).
- expected: one answer. `active_space_lit.search` accepts
  `basis: Optional[str] = None` (`active_space_lit.py:180`) and the tier
  builder simply omits the basis tier when it is absent
  (`active_space_lit.py:152-174`), so the plumbing already supports the
  behaviour the prompt describes; only the tool signatures do not.
- evidence: `app/agent/prompts.py:116-119`; `app/agent/tools.py:2923`;
  `app/agent/tools.py:2944-2946`; `app/agent/active_space_lit.py:180`.
- pointer: the prompt was rewritten for the collapsed `active_space` tool
  and the tool's own required-argument list was not revisited.
- note: an invented basis is not inert here — it narrows the literature
  search's first tier to conditions nobody asked for, which is precisely
  what the tool docstring warns against two sentences later. Fix
  direction: make `basis: Optional[str] = None` on `active_space` and
  `search_active_space_literature`, and reconcile the two docstrings with
  `prompts.py`.

---

### R-036: An attached job's one-line pointer tells the model its results are "in this conversation above" even after they have been trimmed out of the window
- surface: code:agent
- class: bug
- severity: S3
- cause: CODE
- confidence: suspected (code read), not yet reproduced
- found by: audit:agent
- scope: `_attached_job_messages` / `_already_attached_job_ids` in
  `server/routes/chat.py`, against `_trim_history` in `graph.py`.
- repro: attach a job's results, then have a long conversation (past
  `LLM_HISTORY_WINDOW`, default 40 messages, or past the token budget),
  keeping the attachment on. The frontend re-sends the job id, the
  pointer message is generated, and the full summary it points at is no
  longer in the prompt.
- observed: `_already_attached_job_ids` (`chat.py:321-327`) scans
  `state["messages"]` — the *entire* checkpointed history — while
  `_trim_history` (`graph.py:343-421`) is what decides what the model
  actually sees. When the id is found anywhere in history, the message
  becomes (`chat.py:356-359`):
  `"… Its full results are already in this conversation above; they are not repeated here. Refer to them there."`
- expected: either check against the trimmed window, or word the pointer
  so it is safe when the referent is gone — the pattern already exists
  one file over, in `_OMITTED_RESULT_NOTICE` (`graph.py:302-307`), which
  tells the model to re-fetch with `check_job_status` rather than answer
  from memory. `docs/ARCHITECTURE.md:508-539` ("A turn may not silently
  lose the results it just fetched") is the section this cuts against:
  the same fabrication risk, arriving by a different route.
- evidence: `server/routes/chat.py:321-327` and `:353-362`;
  `app/agent/graph.py:302-307`.
- pointer: the dedupe was built to fix a token-budget blowout
  (`docs/MODEL_CONTEXT_BUDGET.md`, "One job's results were attached three
  times") and correctly keyed on the durable history; nothing tied it to
  the window the model is actually shown.
- note: low-cost fix — append "if they are no longer visible, re-read
  them with check_job_status" to the pointer. Settled by replaying a long
  conversation with a persistent attachment and printing
  `build_prompt_messages(state)`.

---

### R-037: `_shed_pinned_results` can only shrink `ToolMessage`s, so several jobs attached to one message can hold the prompt over budget with nothing able to give
- surface: code:agent
- class: bug
- severity: S3
- cause: CODE
- confidence: suspected (code read), not yet reproduced
- found by: audit:agent
- scope: `_trim_history` / `_shed_pinned_results` in `app/agent/graph.py`.
  Checked the interaction with `_current_turn_start`'s pinning of the
  leading human block.
- repro: attach four completed jobs to one message (each
  `job_context_summary` is ~20,000 characters, ~10,000 tokens per
  `docs/MODEL_CONTEXT_BUDGET.md`). Each arrives as its own synthetic
  `HumanMessage` (`chat.py:361`), all inside the pinned current turn.
- observed: `_current_turn_start` (`graph.py:281-299`) deliberately pins
  "the contiguous block of human messages that opened the turn … plus any
  job contexts the frontend attached ahead of it". Both drop loops
  (`graph.py:394-403`) stop at `pin_from`, and the only remaining lever,
  `_shed_pinned_results` (`graph.py:310-340`), skips anything that is not
  a `ToolMessage`:
  `if not isinstance(m, ToolMessage) or m.content == _OMITTED_RESULT_NOTICE: continue`.
  So a turn whose bulk is attached-job HumanMessages exits the function
  over budget with only a `logger.warning` (`graph.py:411-419`).
- expected: the same in-place blanking, applied to a synthetic attached-job
  HumanMessage. Those messages are app-authored, carry a machine-readable
  prefix (`_JOB_ATTACH_PREFIX`, `chat.py:318`) and name their own job id,
  so replacing one with "re-read job X with check_job_status" is exactly
  the self-correcting marker the ToolMessage path already uses. Blanking
  the user's own typed text would not be acceptable; blanking these is.
- evidence: `app/agent/graph.py:310-340`, `:391-419`;
  `server/routes/chat.py:318` and `:361`.
- pointer: `docs/MODEL_CONTEXT_BUDGET.md`'s fix addressed the
  *repeat*-attachment case (a job already in history becomes a pointer)
  but not the first attachment of several jobs at once, which is one
  click in the Job Manager.
- note: this is the answer to "can the budget be exceeded anyway by one
  huge tool result" — yes, but the route is attached HumanMessages, not
  tool results. Settled by constructing the state and calling
  `_trim_history` directly, then summing `_message_tokens`.

---

### R-038: `POST /messages` has no server-side guard against posting while an approval card is open, so anything but the browser destroys the card
- surface: code:agent
- class: bug
- severity: S3
- cause: CODE
- confidence: suspected (code read), not yet reproduced
- found by: audit:agent
- scope: `post_message` in `server/routes/chat.py`. The browser IS
  guarded (`frontend/src/chat/ChatPane.tsx:125`,
  `const disabled = … || !!pendingApproval`), so this is only reachable
  from curl, a script, a stale tab, or a second client.
- repro: raise a card, then `POST /api/threads/{id}/messages` from curl.
  The turn invokes the graph with new input, which discards the pending
  task; the `submit_draft` call is orphaned and a later Approve is a
  silent no-op.
- observed: `server/routes/chat.py:631-651` calls `_require_thread`,
  resolves the owner, registers a cancel event and starts `_run_turn`.
  There is no `pending_approval(config)` check anywhere on the path.
  Contrast `approve_job` (`chat.py:806-808`), which does check and
  returns 409.
- expected: a 409 mirroring `approve_job`'s, since
  `docs/ARCHITECTURE.md:648-668` treats invoking over a pending interrupt
  as destruction rather than as bad timing, and the watcher path
  (`invoke_turn_if_idle`) already refuses for exactly this reason while
  holding the lock.
- evidence: `server/routes/chat.py:631-651`; `server/routes/chat.py:806-808`;
  `app/agent/graph.py:1357-1383`.
- pointer: the invariant is enforced in three places (the client, the
  watcher, the approval route) and not in the one route a third-party
  client would use.
- note: same family as the molecule-panel finding above and probably the
  same fix — one shared "is a card open" gate applied to every
  state-mutating entry point.

---

### R-039: The job watcher re-reads `status.json` for every job of every conversation every two seconds, forever, including jobs that reached terminal months ago
- surface: code:agent
- class: perf
- severity: S3
- cause: CODE
- confidence: suspected (code read), not yet reproduced
- found by: audit:agent
- scope: `JobWatcher._poll_once`. Did not measure; the cost is a
  filesystem read per (thread, job) pair per tick.
- repro: `strace`/`inotify` the api container for ten seconds with a few
  populated conversations and count opens of `data/jobs/*/status.json`.
- observed: `app/agent/job_watcher.py:471-481` loops over every id in
  `entry["active_job_ids"]` and calls `mgr.status(job_id)` unconditionally.
  `self._last_status` (`job_watcher.py:389`) dedups the *SSE event*, not
  the read. A terminal job is also already in `seen`
  (`job_watcher.py:480`), so nothing further will ever be done with it —
  yet it is re-read on every tick for the life of the process.
  `active_job_ids` only grows: its reducer is append-only
  (`app/agent/state.py:136-152`) and the registry mirror
  (`threads.py:118-120`) drops an id only when its directory is gone.
- expected: skip a job whose cached status is already terminal and whose
  id is in `seen` — a terminal status cannot change. That reduces the
  steady-state cost to one `_read_seen` per thread per tick plus reads
  for genuinely running jobs.
- evidence: `app/agent/job_watcher.py:471-481`;
  `app/agent/job_watcher.py:389`; `app/agent/state.py:136-152`.
- pointer: `_last_status` was added for event deduplication and the same
  cache was never used to skip the read.
- note: also worth folding in: `_agent_notice` calls `read_spec(jid)`
  twice per candidate id inside one comprehension
  (`job_watcher.py:261-265`), and `_poll_once` does a full `_read_seen`
  JSON read per thread per tick. Both are small next to the status reads.
  Nothing here is a correctness problem; the reason it is worth filing is
  that the cost grows monotonically with how much the deployment has been
  used, which is the shape that goes unnoticed until it doesn't.

---

### R-040: Quota enforcement runs on the watcher thread and can block on a conversation's graph lock, stalling every conversation's job notices for the length of a turn
- surface: code:agent
- class: perf
- severity: S3
- cause: CODE
- confidence: suspected (code read), not yet reproduced
- found by: audit:agent
- scope: the `enforce_all_quotas` call inside `JobWatcher._loop`, and the
  one eviction branch that takes a graph lock. Postgres deployments only
  (`DATABASE_URL` gated).
- repro: fill a user past their combined jobs+chat cap so a thread is
  evicted, start a long turn on that thread, and watch whether
  `job_update` events stop arriving on *other* conversations for the
  duration.
- observed: `app/agent/job_watcher.py:449-458` calls
  `enforce_all_quotas()` inline on the watcher's own thread every 150
  ticks (~5 minutes). Its thread-eviction branch
  (`app/auth/storage_quota.py:555-558`) calls
  `delete_thread_checkpoints(key)`, and that function takes the per-thread
  graph lock (`app/agent/graph.py:1449`
  `with _lock_for_thread(config):`) — the same lock a running turn holds
  for its whole 53-77 s ReAct loop
  (`docs/ARCHITECTURE.md:686-696`). While the watcher is blocked there,
  `_poll_once` is not running for anybody.
- expected: the watcher's whole design premise is that job polling never
  shares a lock with a chat turn (`job_watcher.py:54-64`,
  `graph.py:1118-1146`). This is the one path that reintroduces exactly
  that coupling, one level down.
- evidence: `app/agent/job_watcher.py:449-458`;
  `app/auth/storage_quota.py:555-558`; `app/agent/graph.py:1434-1452`.
- pointer: the watcher loop was chosen as the trigger because
  chat-history growth has no per-message hook (`job_watcher.py:137-145`),
  which is sound; what was not considered is that one of the eviction
  branches blocks.
- note: fix direction is a separate daemon thread for quota enforcement,
  or a non-blocking `acquire(blocking=False)` in
  `delete_thread_checkpoints` that defers rather than waits. Also worth
  checking (outside my scope) whether evicting a thread whose turn is
  in flight leaves that turn writing to deleted rows.

---

### R-041: ARCHITECTURE.md's "Automatic troubleshooting, with a code-enforced budget" describes a budget that no longer exists in the code
- surface: code:agent
- class: docs
- severity: S3
- cause: CODE
- confidence: suspected (code read), not yet reproduced
- found by: audit:agent
- scope: `docs/ARCHITECTURE.md:565-646`, checked against the whole
  repository by grep.
- repro: `grep -rn "count_failed_in_chain\|_retried_from" app/ server/ tests/`
  → the only hits in the entire tree are `docs/ARCHITECTURE.md:640-641`.
- observed: `docs/ARCHITECTURE.md:638-644`: *"The budget is **not** read
  from anything the model supplies. `count_failed_in_chain()` walks the
  retry chain backwards on disk via each job's `params["_retried_from"]`
  and counts current failures; `job_watcher` calls it directly to decide
  between a retry notice and a stop-and-explain notice."* No such
  function exists; `job_watcher` has no retry notice and no
  stop-and-explain notice; nothing writes `_retried_from`. The section
  title still promises a budget. The current design has none, and
  correctly so: troubleshooting is user-initiated
  (`server/routes/chat.py:654-703`) and starts no job of its own, so
  there is nothing to cap. The rest of that section (the mechanically-read
  25-line tail) is accurate.
- expected: the paragraph should be removed or rewritten to say that the
  budget went away with auto-retry, because the section as written tells
  a reader a guard is in place that is not. The brief's item 7 asks
  precisely whether that budget is code-enforced; the honest answer is
  that there is no budget.
- evidence: `docs/ARCHITECTURE.md:638-644`; empty grep across `app/`,
  `server/`, `tests/`.
- pointer: the auto-retry removal updated the surrounding prose and left
  the budget paragraph.
- note: a second, smaller instance in the same family:
  `docs/ARCHITECTURE.md:517` tells the model to *"re-fetch the specific
  fields with `job_data`"*, but the `job_data` tool was folded into
  `check_job_status`'s `fields` argument (`app/agent/tools.py:2800-2804`
  — *"Was its own `job_data` tool for about a day"*). The runtime string
  was updated correctly (`graph.py:302-307` names
  `check_job_status`); only the doc still says `job_data`. Also, the
  comment at `tools.py:3019` says "Eleven tools" where `STATIC_TOOLS` has
  thirteen.

---

### R-042: The troubleshooting message describes a failed job by its level of theory instead of by what it was
- surface: code:agent
- class: bug
- severity: S3
- cause: CODE
- confidence: suspected (code read), not yet reproduced
- found by: audit:agent
- scope: `compose_troubleshoot_message` only. The sibling notice,
  `_failure_notice_text` (`job_watcher.py:347-352`), gets this right.
- repro: fail a `freq` job at b3lyp and press Troubleshoot. The message
  the model is given opens: *"job <id>, a 'b3lyp' job on orca that
  FAILED"* — with nothing anywhere in it saying the job was a frequency
  calculation.
- observed: `app/agent/troubleshoot.py:100`
  `job_type = spec.get("method", "unknown")`, used at line 112 as
  `f"a '{job_type}' job on {engine} that FAILED"`. `CLAUDE.md` states the
  taxonomy directly: *"task/subtype say what the job IS; method says the
  level of theory."*
- expected: `f"{task}/{subtype}"` (with `method` alongside), the way
  `_failure_notice_text` builds it:
  `label = f"{task}/{subtype}" if task and subtype else task`
  (`job_watcher.py:350`).
- evidence: `app/agent/troubleshoot.py:100` and `:110-113`;
  `app/agent/job_watcher.py:347-352`; `CLAUDE.md`, "Testing conventions".
- pointer: a pre-v2 field name left behind by the registry v2 rewrite,
  in the one file that still reads `spec["method"]` as the job's kind.
- note: this matters more than a wording slip because the message is the
  entire evidence package for a diagnosis. An optimisation that failed to
  converge and a frequency run that hit a negative mode fail for
  different reasons, and the model is not told which it is looking at.
  Cheap fix; same two lines as `_failure_notice_text`.

---

### R-043: `enforce_all_quotas()` re-walks all storage once per user per pass, and runs inside `JobManager.submit()`

- surface: code:auth
- class: perf
- severity: S3
- cause: CODE
- confidence: suspected (code read), not yet reproduced
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

### R-044: the per-user quota pass measures only *evictable* bytes, so a user over quota on running jobs, pinned threads, plots or scan children is never brought back under

- surface: code:auth
- class: bug
- severity: S3
- cause: CODE
- confidence: suspected (code read), not yet reproduced
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

### R-045: accepting two shares concurrently is a check-then-act with no lock, and this is the one quota path that never evicts, so the overage is permanent

- surface: code:auth
- class: bug
- severity: S3
- cause: CODE
- confidence: suspected (code read), not yet reproduced
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

### R-046: `GET /api/auth/download-my-data` omits conversations, plots, projects and scan frames -- most of what the same account's quota counts

- surface: code:auth
- class: bug
- severity: S3
- cause: CODE
- confidence: suspected (code read), not yet reproduced
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

### R-047: an upload or KB source larger than the caller's own quota is written, returned as 201, and then deleted by the same request's eviction pass

- surface: code:auth
- class: bug
- severity: S3
- cause: CODE
- confidence: suspected (code read), not yet reproduced
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

### R-048: a KB upload that fails ingestion leaves its bytes on disk, invisible to every accounting path

- surface: code:auth
- class: bug
- severity: S3
- cause: CODE
- confidence: suspected (code read), not yet reproduced
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

### R-049: an admin cannot preview any per-user KB file, contradicting the route's own contract

- surface: code:auth
- class: bug
- severity: S3
- cause: CODE
- confidence: suspected (code read), not yet reproduced
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

### R-050: an unreachable Redis turns every authenticated request into a 500, while the rate limiter next to it deliberately fails open

- surface: code:auth
- class: bug
- severity: S3
- cause: CODE
- confidence: suspected (code read), not yet reproduced
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

### R-051: `GET /api/admin/activity` walks every job's `status.json` and `spec.json` on every poll, uncached

- surface: code:auth
- class: perf
- severity: S3
- cause: CODE
- confidence: suspected (code read), not yet reproduced
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
- coordinator (P4): measured: p50 5.0 ms at 8 jobs, 8.4 ms at 58 jobs. Real growth, gentler slope than /api/jobs. evidence/p4-route-latency-loaded.json.

### R-052: bug-report attachments are uncapped per account -- no quota, no rate limit, no ceiling on report count

- surface: code:auth
- class: security
- severity: S3
- cause: CODE
- confidence: suspected (code read), not yet reproduced
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

### R-053: the new frontend bundle goes live before the new api exists, and a failure between the two leaves new JS talking to the old backend with no recovery advice
- surface: code:deploy
- class: bug
- severity: S3
- cause: CODE
- confidence: suspected (code read), not yet reproduced
- found by: audit:deploy
- scope: `scripts/update.sh` rebuild sequence. The `--maintenance` case is
  much narrower (non-admins get a 503 through the window); the default CLI
  case, without `--maintenance`, is the exposed one. The admin panel always
  passes `--maintenance` (`deploy_runner.sh:194`).
- repro: run `scripts/update.sh` (no flags) on a commit that changes both the
  frontend and an api route's response shape, with a browser tab open.
  Between the bundle swap and the api coming back healthy — the build is
  already done, so this is the `compose up -d` plus up to 300 s of health
  wait — a reload serves the new SPA against the old api.
- observed: `scripts/update.sh:596-657` in order: `compose build` →
  `extract_frontend.sh` (which atomically flips `frontend/dist/index.html`,
  and nginx serves that directory through a bind mount, so the new bundle is
  live that instant) → `enter_maintenance` → `compose up -d` → health wait.
- expected: the reverse pairing is the one the project has already reasoned
  about and accepted. `check_destructive.sh:444-449` says of a frontend
  change: "Open tabs keep the old bundle until reloaded; no route was
  removed, so they keep working in the meantime" — old JS against a new api
  is tolerated by design. Nothing anywhere accepts new JS against an old api,
  and check 4 (`check_destructive.sh:433-442`) only screens for routes that
  *disappear*, never for routes whose shape changed.
- evidence: `scripts/update.sh:602` (`bash scripts/extract_frontend.sh
  "$TARGET_SHA"`), `scripts/update.sh:617` (`enter_maintenance`),
  `scripts/update.sh:619` (`compose up -d`); `scripts/extract_frontend.sh:100-133`
- pointer: the ordering comment at `update.sh:590-595` justifies building
  before installing the bundle, and building before `up -d`. Neither reason
  requires installing the bundle before `up -d`.
- note: a second, worse exit from the same window. `enter_maintenance` can
  `die` (`update.sh:477`, "could not enter maintenance mode -- refusing to
  restart without it") *after* the bundle has been swapped and before
  anything is recreated. `die` prints no `recovery_advice`, writes no
  `.update-log` entry, and leaves the deployment serving the new frontend
  against the old api permanently, with the checkout already moved. Fix
  direction: move the `extract_frontend.sh` call to after the health check
  passes (and re-run it as part of the failure path only if the api came
  back), or at minimum call `recovery_advice` from the `enter_maintenance`
  failure.
- resolution: fixed, pending commit
- regression test: tests/backend/deploy_07_update_rollback_and_backup.py

### R-054: after a documentation-only update, every later `update.sh` run takes a full backup and then does nothing, permanently
- surface: code:deploy
- class: perf
- severity: S3
- cause: CODE
- confidence: suspected (code read), not yet reproduced
- found by: audit:deploy
- scope: `scripts/update.sh` up-to-date test and the `NEEDS_RESTART=0` fast
  path. Not measured on this host; the cost is whatever `tar -czf` over
  `data/jobs` + `data/kb` costs, which for a deployment with real CASSCF
  output is large.
- repro: update to a commit that only touches `docs/`. Then run
  `scripts/update.sh` again with no new commits upstream. It takes another
  full backup, prints "not restarting anything", and exits — and will do so
  on every subsequent run.
- observed: the docs-only path (`update.sh:568-581`) exits without rebuilding,
  so the api image's OCI stamp and `frontend/dist/.build-commit` both stay at
  the previous commit. On the next run `DEPLOYED_SHA != TARGET_SHA`, so the
  "already up to date" test at `update.sh:255-260` fails; `REBUILD_ONLY=1`;
  the unconditional `bash scripts/backup.sh --full` at `update.sh:399` runs;
  `check_destructive` reports the same docs-only diff; `NEEDS_RESTART=0`
  again; exit. The stamp can never catch up, because catching up requires a
  rebuild the same branch declines to do.
- expected: a run with nothing to do should reach `ok "already up to date --
  nothing to do."` and exit before the backup.
- evidence: `scripts/update.sh:346-352` (`RUNTIME_IRRELEVANT_RE` and
  `NEEDS_RESTART`), `scripts/update.sh:255-260`, `scripts/update.sh:399`
- pointer: the up-to-date test compares shas; the restart decision compares
  file paths. The two disagree about what "current" means.
- note: fix direction — in the up-to-date test, treat `DEPLOYED_SHA →
  TARGET_SHA` as current when the diff between them matches
  `RUNTIME_IRRELEVANT_RE` (the same computation, hoisted above the test), or
  write the stamp forward on the docs-only exit so the deployment records
  that it is serving that commit.
- resolution: fixed, pending commit
- regression test: tests/backend/deploy_07_update_rollback_and_backup.py

### R-055: `check_destructive.sh`'s vanishing-bind-mount check tests whether the override file exists, not whether it still declares the mounts the running container has
- surface: code:deploy
- class: bug
- severity: S3
- cause: CODE
- confidence: suspected (code read), not yet reproduced
- found by: audit:deploy
- scope: check 10 (`check_destructive.sh:618-639`), which is one of the four
  classes the script's header claims to catch. The absent-file case is
  covered correctly.
- repro: with a running stack that has `/software:/software:ro` mounted, edit
  `docker-compose.override.yml` to remove the `volumes:` block (keeping the
  file, e.g. for its `ports:` override, which `install.sh:791-797` also
  writes into this file). Run `scripts/check_destructive.sh`. It reports
  `[ok] docker-compose.override.yml is present, so engine mounts survive a
  recreate`. The next recreate produces a PySCF-only stack.
- observed: `check_destructive.sh:625-638`

      if [ "$ENGINE_MOUNTED" -eq 1 ] && [ ! -f "${STACK_DIR}/docker-compose.override.yml" ]; then
          dest "..."
      elif [ -f "${STACK_DIR}/docker-compose.override.yml" ]; then
          ok "docker-compose.override.yml is present, so engine mounts survive a recreate"

- expected: the header's claim 4 is that "a deployment can be running happily
  with ORCA and BAGEL mounted while the file that mounts them no longer
  exists on disk". The file being *edited* rather than deleted produces the
  same silent PySCF-only stack, and on this host that file is also the ports
  override, so it is a file people edit.
- evidence: `check_destructive.sh:634-635`; `docker-compose.override.yml.example`;
  `scripts/install.sh:791-797`
- pointer: the live mount list is already in hand (`LIVE_MOUNTS`,
  `check_destructive.sh:622`). Comparing it against `docker compose config
  --format json`'s `services.api.volumes` would answer the real question.
- note: two smaller weaknesses in the same block. `STACK_DIR` is
  interpolated straight into a regex (`grep -vE "^${STACK_DIR}(/|$)"`), so a
  path containing regex metacharacters — this host's own
  `/data/qcuser/9.NexusQC/NexusQC-dev-repo` contains `.` — matches more
  loosely than intended; and the whole check is skipped silently when
  `compose ps -q api` returns nothing.
- resolution: fixed, pending commit
- regression test: tests/backend/deploy_07_update_rollback_and_backup.py

### R-056: `check_destructive.sh` and `update.sh` both tell the operator that *pending* jobs will be killed by the restart; they are re-enqueued
- surface: code:deploy
- class: bug
- severity: S3
- cause: CODE
- confidence: suspected (code read), not yet reproduced
- found by: audit:deploy
- scope: the in-flight count in `update.sh:354-384` and check 8 in
  `check_destructive.sh:509-552`, against
  `JobManager._reconcile_orphaned_jobs` in `app/chemistry/jobs/base.py:1068-1163`.
  Verified by reading the reconciliation, not by restarting a container.
- repro: queue a job that cannot be admitted yet (so its `status.json` says
  `pending` and `meta.json` has no `worker_pid`), then run
  `scripts/update.sh`. It refuses with "1 job(s) are running or pending, and
  they will be killed", pushing the operator to `--drain` (up to four hours)
  or `--force`.
- observed: both scripts count `status in ("running", "pending")` and then
  describe the whole set as lost. `check_destructive.sh:543` — `dest "jobs are
  in flight and WILL BE KILLED by the restart" ... "there is no resume"`.
  `update.sh:378` — `die "${INFLIGHT} job(s) are running or pending, and they
  will be killed."`
- expected: case 3 of `_reconcile_orphaned_jobs`
  (`app/chemistry/jobs/base.py:1101-1106,1155-1157`): "meta.json's worker_pid
  is unset -- this job was never admitted by the scheduler before the previous
  process died, so there is no worker to have lost, only a still-queued job.
  Re-enqueue it exactly as if freshly submitted". Only a job with a dead
  `worker_pid` and no result is marked failed. A pending job survives a
  restart intact.
- evidence: `scripts/update.sh:366` (`in ("running", "pending")`),
  `scripts/check_destructive.sh:530`, `app/chemistry/jobs/base.py:1155`
- pointer: the drain loop itself already gets this right — it waits only on
  `status == "running"` (`update.sh:533`). It is the two operator-facing
  messages that overstate.
- note: safe direction (nothing is lost), but it costs a real decision: an
  operator with only pending jobs is steered into a four-hour drain or an
  unnecessary `--force`. Fix direction: count and report the two states
  separately — "N running (will be killed), M pending (will be re-queued
  after the restart)".
- resolution: fixed 2c0c19f
- regression test: tests/backend/jobs_04_job_timeout_and_dispatch.py

### R-057: a fifth destructive class `check_destructive.sh` misses — a change to a service's image tag or a named volume in `docker-compose.yml`
- surface: code:deploy
- class: bug
- severity: S3
- cause: CODE
- confidence: suspected (code read), not yet reproduced
- found by: audit:deploy
- scope: all ten checks in `check_destructive.sh` were read against the four
  classes its header claims. Claims 1 (in-flight jobs), 2 (silent no-op
  schema change) and 3 (new required `.env` variable) are genuinely
  implemented (checks 8, 3+9, 2 respectively); claim 4 is partial (previous
  finding). This is the gap I could not find a check for.
- repro: craft a commit that changes `postgres:16-alpine` to
  `postgres:17-alpine` in `docker-compose.yml` and run
  `scripts/check_destructive.sh --to <that commit>`. It reports one generic
  `[warn] docker-compose.yml changed -- containers will be recreated, not
  restarted` and no destructive finding, and `update.sh` proceeds without
  asking.
- observed: `check_destructive.sh:462-466` is the only check keyed on
  `docker-compose.yml`, and it warns about recreation in the abstract
  ("Diff the ports and volumes sections specifically" — advice to a human,
  not a check). Nothing compares image tags or volume names between the two
  commits.
- expected: two concrete silent failures live here.
  - A Postgres **major** version bump makes the existing `postgres-data`
    volume unreadable; the container exits at once with "database files are
    incompatible with server", after the old containers are gone. Recoverable
    only from the backup (which `update.sh` does take) plus a hand-run
    `pg_upgrade` or dump/restore cycle.
  - A **renamed named volume** (`postgres-data` → anything) starts an empty
    database. `app/auth/db.py`'s `CREATE TABLE IF NOT EXISTS` then populates
    it, the app comes up healthy, and it looks like a fresh install with zero
    accounts. The old volume still exists, so nothing is technically lost, but
    the deployment is silently serving an empty identity store — and per
    `docker-compose.yml`'s own header note, an empty `ownership_index` makes
    every job on disk unowned, which this app treats as readable by everyone.
    That is a security consequence, not only an availability one.
- evidence: `check_destructive.sh:462-466`; `docker-compose.yml` `image:`
  lines and the `volumes:` block at the end
- pointer: both are one `git show "$TO_SHA":docker-compose.yml` and a diff of
  `grep -E '^\s+image:|^  [a-z-]+:$'` away — the script already does exactly
  this shape of comparison for `${VAR:?}` in check 2 and for requirements
  pairs in check 1.
- note: image tags are currently pinned to a major (`postgres:16-alpine`,
  `redis:7-alpine`, `nginx:1.27-alpine`), so this is latent rather than live.
  Worth adding before anyone bumps one.
- resolution: fixed, pending commit
- regression test: tests/backend/deploy_07_update_rollback_and_backup.py

### R-058: `/api/health` proves only that uvicorn is answering, so `update.sh` can declare a deployment healthy when Postgres is unusable
- surface: code:deploy
- class: bug
- severity: S3
- cause: CODE
- confidence: suspected (code read), not yet reproduced
- found by: audit:deploy
- scope: `server/main.py:150-152`, the compose healthcheck
  (`docker-compose.yml` api service), and `qc_wait_for_health`
  (`scripts/lib/common.sh`). Not checked: whether any startup path opens a
  Postgres connection eagerly — I could not find one; the pool looks lazy.
- repro: put a wrong password in `QC_AGENT_POSTGRES_PASSWORD` for the api's
  `QC_AGENT_DATABASE_URL` only (the postgres container's own healthcheck uses
  `pg_isready -U <user>` and does not authenticate). `update.sh` reports
  `ok "healthy at ..."`, nginx starts, and every login fails.
- observed: `server/main.py:150-152`

      @app.get("/api/health")
      def health():
          return {"status": "ok"}

  Nothing touches Postgres, Redis, the job manager, or the graph. The compose
  healthcheck urlopens exactly this route.
- expected: the health gate is what `update.sh` uses to decide whether to
  record a commit as good and rollback-able (`update.sh:656-686`), and what
  nginx's `depends_on: service_healthy` uses to decide whether to start
  serving. Both questions are "can this deployment serve requests", not "did
  the interpreter finish importing".
- evidence: `server/main.py:150`; `docker-compose.yml` api `healthcheck:`;
  `scripts/lib/common.sh` `qc_wait_for_health` (`curl .../api/health`)
- pointer: startup does check that `QC_AGENT_JWT_SECRET` and
  `QC_AGENT_REDIS_URL` are *set* (`server/main.py:126-141`) and refuses to
  start without them, so those two are partly covered by process liveness.
  Postgres reachability is not covered at all.
- note: deliberately cheap health endpoints are a reasonable design and
  `/api/health` must keep answering during maintenance, so do not just add a
  query to it. Fix direction: a separate `/api/ready` that does a `SELECT 1`
  through the pool, used by `qc_wait_for_health` and the compose healthcheck,
  with `/api/health` left as the liveness probe.
- resolution: fixed, pending commit
- regression test: tests/backend/deploy_07_update_rollback_and_backup.py

### R-059: almost every Python dependency is unpinned, so two installs a month apart get different langchain/langgraph
- surface: code:deploy
- class: bug
- severity: S3
- cause: CODE
- confidence: suspected (code read), not yet reproduced
- found by: audit:deploy
- scope: `requirements.txt` as a whole. I did not attempt to determine
  whether any currently-resolvable version actually breaks the app.
- repro: `grep -vE '^#|^$' requirements.txt | grep -vc '=='` → 33 unpinned
  lines against 2 pinned (`pyscf==2.14.0`, `pyscf-forge==1.1.1`). `pip
  download -r requirements.txt` on two dates and compare.
- observed: `langgraph`, `langchain`, `langchain-openai`, `langchain-ollama`,
  `langchain-chroma`, `langchain-community`, `langchain-text-splitters`,
  `chromadb`, `fastapi`, `uvicorn[standard]`, `numpy`, `scipy`, `rdkit`,
  `ase` and the rest carry no specifier at all.
- expected: the file itself argues for pinning where it matters, and the
  argument generalises: "The point of the pin is that a fresh install works
  first time" (`requirements.txt`, above `pyscf==2.14.0`).
  `check_destructive.sh:268-271` treats a newly added unpinned package as
  worth calling out — "(new, UNPINNED -- resolves to whatever is latest at
  build time)" — so the tooling already regards this as a hazard. The
  langchain/langgraph family in particular makes breaking changes across
  minors, and it sits directly under the agent loop.
- evidence: `requirements.txt:3-35,83`; `check_destructive.sh:270`
- pointer: `Dockerfile` runs a plain `pip install --no-cache-dir -r
  requirements.txt` with no constraints file, so the image is whatever PyPI
  serves the day it is built.
- note: this may be a deliberate standing choice — the two pins carry long
  justifications and one nearby package is explicitly marked "Deliberately
  NOT pinned" — so treat this as a question rather than a defect if so. What
  would settle it: `pip freeze` inside the current working image versus a
  rebuild today. Fix direction that keeps the freedom: commit a
  `requirements.lock` produced by `pip freeze` from a verified image and have
  the Dockerfile install from that, leaving `requirements.txt` as the
  human-edited input.
- resolution: fixed, pending commit
- regression test: tests/backend/deploy_07_update_rollback_and_backup.py

### R-060: `docs/CONFIGURATION.md`'s job-parameter tables document four parameters and two task subtypes that no longer exist, and the in-app help still offers AVAS
- surface: code:deploy
- class: docs
- severity: S3
- cause: CODE
- confidence: suspected (code read), not yet reproduced — confirmed by importing the registry
- found by: audit:deploy
- scope: `docs/CONFIGURATION.md`'s "Job parameter defaults" section and
  `frontend/src/app-shell/HelpFlyout.tsx:169-172`, against
  `app/chemistry/registry2/params.py` and `registry2/tasks.py`.
- repro: `PYTHONPATH=$PWD python3 -c "from app.chemistry.registry2.params
  import PARAMS, RETIRED_PARAMS; print(sorted(RETIRED_PARAMS))"` and
  `... from app.chemistry.registry2 import TASKS; print(sorted(TASKS))`.
- observed: `RETIRED_PARAMS` contains `orbital_indices`, `isoval`,
  `entropy_method`, `dmrg_bond_dim`, `max_active_orbitals`, `avas_aolabels`,
  `entropy_pilot_states`, `active_occupied_orbitals`, with the comment
  "Retired with the active-space rebuild. The entropy pilot, its DMRG variant
  and its state averaging are gone; **there is no ceiling to set**". `TASKS`
  has `('cas_reco','')` and `('cas_reco','refine')` — no `explain`, no
  `autocas`, no `avas`. Against that, `docs/CONFIGURATION.md` still says:
  - line 145: "`cas_reco` (subtypes `explain`/`autocas`/`avas`)"
  - line 166: a default for `cas_reco/autocas` → `entropy_method` `exact_fci`,
    "`dmrg` is the opt-in alternative"
  - line 167: a default for `cas_reco/autocas`, `cas_reco/avas` →
    `max_active_orbitals` `12`, "can only narrow it, never widen past 12"
  - line 168: `single_point` → `isoval` `0.04`, "only shown once
    `orbital_indices` is actually set"
  - lines 146-148: "Rendering molecular orbitals … It's now just the
    `orbital_indices` parameter on an ordinary `single_point`"

  and `HelpFlyout.tsx:170-171` tells users the active-space job "analyses the
  orbitals (entanglement-based, or AVAS)".
- expected: the section opens by asserting exactly the property it has lost —
  "Every default below lives in `app/chemistry/registry2/params.py`'s `PARAMS`
  tuple … This table is a transcription of it, not separate policy"
  (`CONFIGURATION.md:133-137`). It also settles the README contradiction filed
  above: README:449-453's "There is no size limit" is the correct account and
  `max_active_orbitals` is the stale one.
- evidence: `app/chemistry/registry2/params.py:295-306`;
  `app/chemistry/registry2/tasks.py` (`TASKS` keys);
  `docs/CONFIGURATION.md:141-148,166-168`;
  `frontend/src/app-shell/HelpFlyout.tsx:170`
- pointer: the CAS engine rebuild deleted the parameters and the subtypes and
  did not reach the configuration reference or the in-app tutorial — the
  "audit every surface a method touches" case, one rebuild later.
- note: the same section omits `opt/min`, `geometry_set`, `pes_1d/ee` and
  `interp_pes/ee`, all of which are real task keys. Since the tables claim to
  be a transcription, the durable fix is to generate them the way
  `docs/QM_CAPABILITIES.md` is generated, and add a drift check beside
  `scripts/check_capability_matrix.py`. AVAS in the tutorial is the row a user
  is most likely to act on: they will ask for an AVAS active space and get
  something else.

### R-061: the in-app welcome screen's capability table is a hand-written duplicate of engine routing and disagrees with the registry in four places
- surface: code:deploy
- class: docs
- severity: S3
- cause: CODE
- confidence: suspected (code read), not yet reproduced — the registry side is confirmed by importing it
- found by: audit:deploy
- scope: `frontend/src/chat/WelcomeMessage.tsx`'s `ROWS` array, checked cell by
  cell against `app/chemistry/registry2` via `engines_supporting()` and
  `CAPABILITIES`. Not checked in a browser.
- repro: open a new conversation, expand "What can it run?", then ask for the
  calculation each disputed cell describes.
- observed: four cells, verified against the registry by import:

      { calc: "Geometry optimisation", ..., bagel: "CASSCF/CASPT2 only" }   # line 14
      { calc: "Frequencies / thermochemistry", ..., bagel: "numerical, HF only" }  # line 15
      { calc: "CASSCF (incl. state-averaged)", orca: "yes, + oscillator strengths", bagel: "yes" }  # line 16
      { calc: "Potential-energy scan", pyscf: "default*", orca: "yes*", bagel: "yes*" }  # line 21

  `engines_supporting('hf','opt','min')` → `('pyscf','orca','bagel')`;
  `engines_supporting('hf','freq','')` and `('casscf','freq','')` → both include
  `bagel`; `engines_supporting('casscf','pes_1d','')` → `('pyscf','orca')`, i.e.
  **BAGEL cannot scan at all**; and
  `CAPABILITIES[('bagel','casscf')].osc_strengths` is `True`.
- expected: the scan row is the one that misleads in the dangerous direction —
  it tells a new user, on the first screen they see, that an engine supports
  something the app will refuse. The other three understate BAGEL. README's own
  matrix (lines 71, 76, 79) agrees with the registry in all four places, so it
  is only this table that is wrong. The oscillator-strengths cell also
  contradicts README:144-147 ("A CASSCF job that needs oscillator strengths
  also goes to BAGEL, which is the preferred engine for those on this
  deployment").
- evidence: `frontend/src/chat/WelcomeMessage.tsx:9-25`, whose own comment
  says "Mirrors app/chemistry/jobs/registry.py's ALLOWED_ENGINES/DEFAULT_ENGINE
  -- kept as a small hand-written table here rather than fetched from the
  backend since it's static per-deployment reference info"
- pointer: the comment names `app/chemistry/jobs/registry.py`, but routing now
  lives in `app/chemistry/registry2/`. The table was mirrored from a module
  that has since been replaced, and nothing checks it.
- note: `CLAUDE.md` makes the registry the single source of truth and says
  logic duplicated elsewhere is a finding. There is already a route that serves
  this data (`server/routes/registry.py`: "a complete map of every calculation
  this deployment can" run), so the table could be fetched instead of
  transcribed — which would also make it honest on a PySCF-only deployment,
  where it currently claims ORCA and BAGEL rows regardless.

### R-062: several `docs/DEPLOYMENT.md` commands cannot run as printed, and two rows of its status table describe removed features
- surface: code:deploy
- class: docs
- severity: S3
- cause: CODE
- confidence: suspected (code read), not yet reproduced
- found by: audit:deploy
- scope: `docs/DEPLOYMENT.md` only. Four separate problems, grouped because
  they are one editing pass.
- repro / observed:
  1. **The nightly cron line writes into a directory that does not exist.**
     `DEPLOYMENT.md:566-568` gives
     `0 3 * * * cd /path/to/NexusQC && ./scripts/backup.sh >> backups/backup.log 2>&1`,
     two lines after telling the operator to point `QC_AGENT_BACKUP_DIR`
     somewhere with real room. `backups/` is only created by `backup.sh` when
     that variable is *unset*, so on the recommended configuration the shell
     cannot open the redirect and the job fails before the script starts —
     silently, nightly. Even with the variable unset the *first* run fails,
     because the shell opens the redirect before the script gets to `mkdir`.
     Confirmed on this host: `backups/` does not exist.
  2. **Every `curl` example omits `-k`.** `DEPLOYMENT.md:385-406` gives five
     admin examples against `https://<host>`, on a deployment whose own step 3
     generates a self-signed certificate and whose step 8 tells you to accept
     the browser warning. As printed each fails certificate verification.
  3. **A pointer to a file that does not exist.** `DEPLOYMENT.md:191` tells the
     reader to see "`docker-compose.dev.yml`'s `ports: !override` for the
     pattern". That file was removed with the dev/production split.
  4. **Two stale status rows.** `DEPLOYMENT.md:712-713` still lists "Public
     nginx listener | Not verified end to end. Commented out by default" and
     "Host-level kill switch | Implemented for `iptables`; not yet run against
     a real firewall". Both were removed on 2026-08-25, which the same document
     says at lines 474-480.
- expected: a deployment guide's commands should run as printed; its status
  table should not contradict its own body.
- evidence: `docs/DEPLOYMENT.md:567`, `:385-406`, `:191`, `:712-713`;
  `scripts/backup.sh:83-85`; `.gitignore:63`
- pointer: (1) and (2) are the two that cost real time — a backup everyone
  believes is running and is not, and a support recipe that fails on its first
  line.
- note: `scripts/toggle_public_access.sh` is referenced in the same removed-
  feature family from `nginx/nginx.conf:6`, filed separately above.
- resolution: fixed, pending commit
- regression test: tests/backend/deploy_07_update_rollback_and_backup.py

### R-063: README and CONFIGURATION.md contradict each other on whether the active-space recommendation has a size limit
- surface: code:deploy
- class: docs
- severity: S3
- cause: CODE
- confidence: suspected (code read), not yet reproduced
- found by: audit:deploy
- scope: the two documents; I did not trace which one the code implements.
- repro: ask for a recommendation on a molecule whose valence space exceeds
  twelve orbitals and see which document describes what happens.
- observed: `README.md:449-453` — "*There is no size limit.* The previous
  version refused anything above twelve orbitals ... This one does not run that
  CASSCF. A large space is reported with its determinant and CSF counts and
  which engines can actually reach it, and you decide."
  `docs/CONFIGURATION.md:167` — `cas_reco/autocas`, `cas_reco/avas` →
  `max_active_orbitals` default `12`, "Ceiling on the recommended space; can
  only narrow it, never widen past 12".
- expected: these can both be true only if `max_active_orbitals` bounds
  something other than what README calls "the recommended space", and neither
  document says so. As written, a user reads README, asks for a large space,
  and gets twelve orbitals.
- evidence: `README.md:449-453`; `docs/CONFIGURATION.md:167`
- pointer: the twelve-orbital ceiling is exactly the limit README says was
  removed, so this reads like a parameter default that outlived its rationale.
- note: a second, smaller contradiction in the same family, also worth one
  edit: `README.md:869-871` says user and invite management, suspensions,
  deletions and bug-report triage all happen in the admin console, while
  `docs/DEPLOYMENT.md:381-382` and `:708` say user/invite management and the
  bug inbox are not in it yet and go through the API directly.

---

### R-064: `ui_10`'s atom-label check on the vibration viewer snapshots the orbital viewer's empty canvas, which is the mechanism behind the open backlog item

- surface: code:frontend
- class: bug
- severity: S3
- cause: CODE
- confidence: suspected (code read), not yet reproduced
- found by: audit:frontend
- scope: `tests/frontend/ui_10_atom_label_toggle.spec.mjs` step 5, against `JobDetailDrawer`'s freq-job layout and `MoCubeViewer`'s mount behaviour. The same spec's step 4 (orbital viewer) is unaffected and does measure what it claims. Not run.
- repro: In the freq-job drawer the spec opens, evaluate `Array.from(document.querySelectorAll("canvas")).filter(c => c.offsetParent !== null).length` and then, for the last of them, `c.closest("[data-panel]")?.dataset.panel`. Expectation from this reading: two canvases, and the last one reports `orbitals`, not `vibrations`.
- observed: This is the "Atom numbers do not come back after a vibrational mode change" entry in `docs/BACKLOG.md`'s Open section, which records that the mechanism has not been established, that `applyAtomLabels` is stateless, and that the dependency list looks right on a code read. The dependency list *is* right. The check is reading the wrong canvas.

  The spec's snapshot helper takes the **last** visible canvas (`ui_10_atom_label_toggle.spec.mjs:59-68`):

  ```js
  const canvases = Array.from(document.querySelectorAll("canvas")).filter((c) => c.offsetParent !== null);
  const c = canvases[canvases.length - 1];
  ```

  In `JobDetailDrawer.tsx` the vibrations panel is at line 978 and the **orbitals** panel at line 1450 — later in the DOM. The orbitals panel renders whenever the job has cubes *or* an orbital table (`JobDetailDrawer.tsx:1433-1435`), and a PySCF frequency job always writes one: `app/chemistry/jobs/pyscf_runner.py:1467`, `molden_path, summary["orbital_table"] = _write_molden_and_table(...)` at the end of `run_frequency`. `ExpandablePanel` evaluates its render-prop child eagerly (`ExpandablePanel.tsx:183-185`), so `MoCubeViewer` mounts.

  `MoCubeViewer` creates its 3Dmol viewer — and therefore a `<canvas>` — unconditionally in its init effect, before any cube exists (`MoCubeViewer.tsx:101-118`). With no `artifacts.cubes` on a freq job, `cubeLabels` is `[]`, so `selected` is `""`, so the fetch effect's `url` is `null` and returns early (`MoCubeViewer.tsx:153-157`), and `cubeText` stays `null`. Both the render effect and the label effect then bail on `if (!v || !cubeText) return` (`MoCubeViewer.tsx:206`, `MoCubeViewer.tsx:253`).

  So the canvas the spec snapshots has never been drawn into and does not respond to the atom-label toggle at all. Two reads of it are byte-identical, which is exactly the failure reported: *"identical before/after the switch, i.e. the mode change had already wiped the labels"*.
- expected: The check should read the canvas inside `[data-panel="vibrations"]`. `ExpandablePanel`'s `name` prop exists for precisely this problem and its own comment says so (`ExpandablePanel.tsx:100-107`: a test that wants one particular panel "resorted to 'the last one in the drawer'. That silently retargets the moment a section is added below").
- evidence: `tests/frontend/ui_10_atom_label_toggle.spec.mjs:59-68` and `:349-365`; `frontend/src/jobs/JobDetailDrawer.tsx:978` vs `:1450`; `frontend/src/jobs/MoCubeViewer.tsx:101-118`, `:153-157`, `:206`, `:253`; `app/chemistry/jobs/pyscf_runner.py:1467`.
- pointer: A selector that means "the most recently mounted viewer" instead of "this panel's viewer", against a drawer whose last panel mounts a viewer eagerly and leaves it blank.
- note: This explains the known backlog item rather than being a new defect, and it explains all three things the backlog says were established: it is not a regression (the drawer has had this shape all along), the theme wiring is irrelevant, and longer settles cannot help. Two consequences for whoever fixes it. **First, the app-side behaviour is unobserved, not proven correct** — the spec never looked at the vibration viewer after a mode change, so "do the labels come back?" is still an open question, just not one this failure answers. **Second, fixing the selector alone makes the check vacuous**: `ModeAnimationViewer` calls `v.animate({loop: "backAndForth", reps: 0})` (`ModeAnimationViewer.tsx:86`), so the canvas is repainting continuously and two snapshots 400 ms apart will differ whatever the labels do. The fixed check needs the animation paused (3Dmol has `pauseAnimate()`/`stopAnimate()`) or both snapshots taken at the same animation frame, as well as `[data-panel="vibrations"] canvas` as the target. Worth noting the same reasoning applies in reverse to the orbital check, which is sound because that viewer is static.

---

### R-065: Every `createViewer()` pins its `GLViewer` to `document.body` and `window` for the life of the page; clearing the container does not release it

- surface: code:frontend
- class: perf
- severity: S3
- cause: CODE
- confidence: suspected (code read), not yet reproduced
- found by: audit:frontend
- scope: All seven viewer call sites — `MoleculeViewer`, `MoCubeViewer`, `ModeAnimationViewer`, and the four that render `MoleculeViewer` (`ScanFrameViewer`, `NebFrameViewer`, `EnsembleFrameViewer`, `GeometrySetViewer`). Read against the installed 3Dmol, `frontend/node_modules/3dmol/package.json` version `2.5.5`. Not measured in a browser.
- repro: Open and close the job detail drawer twenty times, then in devtools count the window `resize` listeners (`getEventListeners(window).resize.length` in Chrome) — expectation from this reading is one per viewer ever created, none removed. Then drag the dock's resize handle and watch the frame count: every orphan re-renders too.
- observed: The three components each end their init effect's cleanup with the container clear the architecture documents:

  `frontend/src/molecule/MoleculeViewer.tsx:111-115`
  ```ts
  return () => {
    stopThemeWatch();
    if (containerRef.current) containerRef.current.innerHTML = "";
    viewerRef.current = null;
  };
  ```

  That detaches the `<canvas>` and drops the app's own reference. It does not make the `GLViewer` unreachable, because the constructor registers five things that are never removed — `frontend/node_modules/3dmol/src/GLViewer.ts:729-755`:

  ```js
  document.body.addEventListener('mouseup', this._handleMouseUp.bind(this));
  document.body.addEventListener('touchend', this._handleMouseUp.bind(this));
  ...
  window.addEventListener("resize", this.resize.bind(this));
  if (typeof (window.ResizeObserver) !== "undefined") {
      this.divwatcher = new window.ResizeObserver(this.resize.bind(this));
      this.divwatcher.observe(this.container);
  }
  if (typeof (window.IntersectionObserver) !== "undefined") {
      ...
      this.intwatcher.observe(this.container);
  }
  ```

  `GLViewer` exposes no `destroy()`/`dispose()` (the architecture already records this), so those bound closures keep every viewer ever created alive, along with its scene graph, geometry buffers and detached canvas.

  There is a second, visible cost. `this.divwatcher` observes `this.container`, and in this app the container is a stable `<div ref={containerRef}>` that survives the viewer swap — `MoleculeViewer.tsx:90-91` clears that same div and builds a new viewer inside it. So after a Strict-Mode double-invoke or any rebuild, *both* the orphan and the live viewer's observers fire on the same element, and the orphan runs `resize()` (`GLViewer.ts:1459`) which re-reads the box, calls `renderer.setSize()` and re-renders into a canvas nobody can see. Every window resize does the same thing to every orphan.
- expected: A viewer that has been replaced should stop consuming work and memory. The architecture's own framing of the original bug — "browsers cap live WebGL contexts per page... once exhausted, every new context silently fails to initialize" — is the right *concern*; the container clear addresses the DOM symptom rather than the reachability.
- evidence: `frontend/node_modules/3dmol/src/GLViewer.ts:729-755` (registration), `:1459-1480` (`resize`, which the orphans keep receiving); `frontend/src/molecule/MoleculeViewer.tsx:111-115`, `frontend/src/jobs/MoCubeViewer.tsx:119-123`, `frontend/src/jobs/ModeAnimationViewer.tsx:69-74`.
- pointer: `innerHTML = ""` removes a DOM reference. The listener lists on `document.body` and `window` are a separate, stronger reference the cleanup never touches.
- note: What would settle it: hold a `WeakRef` to each created viewer in a dev-only array, cycle the drawer, force GC in devtools, and check that none of the refs clear. Fix direction, in the cleanup of each of the three init effects, before nulling the ref: `(v as any).divwatcher?.disconnect(); (v as any).intwatcher?.disconnect();` — that removes the two observers and, importantly, the last reference from the *container* side. The `document.body` and `window` bindings cannot be removed from outside the library (the bound functions were never stored), so the honest options are an upstream patch adding a `destroy()`, or accepting the residual. Related and folded in here rather than filed separately: `ModeAnimationViewer.tsx:51`'s `rafRef` is declared and cancelled in cleanup but never assigned anywhere, left over from a `requestAnimationFrame` loop that `v.animate()` replaced — dead, and misleading about what the cleanup actually cancels.

---

### R-066: The architecture's WebGL-context-cap mechanism does not describe 3Dmol 2.5.5's render path, and nothing in the app recovers from a lost context

- surface: code:frontend
- class: docs
- severity: S3
- cause: CODE
- confidence: suspected (code read), not yet reproduced
- found by: audit:frontend
- scope: `docs/ARCHITECTURE.md`'s "The 3Dmol wrapper is deliberately imperative" and "The 3D viewer follows the theme by mutation, never by remount" sections, against `frontend/node_modules/3dmol` at the pinned `2.5.5`. Not reproduced.
- repro: With two viewers open (the molecule panel and a job drawer), run in devtools: pick either viewer's canvas, take `_3dmol_viewer.renderer.getContext().getExtension('WEBGL_lose_context').loseContext()`. Expectation from this reading: **both** viewers go blank simultaneously, because they share one context, and neither recovers until a window resize or a reload.
- observed: The architecture states the constraint as "browsers cap live WebGL contexts per page (commonly 8-16). Repeated mount/unmount exhausted that cap", and records the fix as verified by "live canvas count stays at exactly 1 across dozens of rapid cycles".

  In 2.5.5 the renderer takes a shared-context path whenever `OffscreenCanvas` exists, which it does in every browser this app targets — `frontend/node_modules/3dmol/src/WebGL/Renderer.ts:2136-2154`:

  ```js
  if (OffscreenCanvas && !(this.rows != undefined && ...)) {
      if (_gl_singleton == null || _gl_singleton.isContextLost()) {
          _offscreen_singleton = new OffscreenCanvas(this._canvas.width, this._canvas.height);
          _gl_singleton = _offscreen_singleton.getContext("webgl2", {...});
      }
      this._offscreen = _offscreen_singleton;
      this._gl = _gl_singleton;
      this._bitmap = this._canvas.getContext("bitmaprenderer", { alpha: true });
  }
  ```

  `_gl_singleton` is module-level (`Renderer.ts:25`). Every viewer draws into that one offscreen context, resizes it to its own canvas immediately before each render (`Renderer.ts:299-304`), and copies the result out with `transferToImageBitmap` / `transferFromImageBitmap` (`Renderer.ts:895-899`). Each *visible* canvas holds only a `bitmaprenderer` context, which is not the capped resource.

  Two consequences. The counted quantity ("DOM canvases") was never the capped one under this render path, so the verification does not support the claim. And a single shared context is a single point of failure with no handling in this app: if it is lost, `initGL` recreates it only when a *new* `Renderer` is constructed, so every already-mounted viewer keeps a dead `this._gl` and silently draws nothing. `GLViewer.resize()` does contain a recovery path (`GLViewer.ts:1463`, `if (this.renderer.isLost() && this.WIDTH > 0 ...)`) but it only fires on a resize event, and `grep -rn "webglcontextlost" frontend/src` returns nothing.
- expected: The architecture is the place a future session goes to understand why the viewers are written this way, and the recorded mechanism should match the code that ships. Note that nothing here argues the imperative wrapper or the container clear is *wrong* — both are still right, for the reachability reason in the previous finding.
- evidence: `frontend/node_modules/3dmol/src/WebGL/Renderer.ts:25`, `:2136-2154`, `:299-304`, `:895-899`; `frontend/node_modules/3dmol/src/GLViewer.ts:289` (the library's own per-canvas `webglcontextlost` listener, which the offscreen path's loss does not fire), `:1459-1480`; `docs/ARCHITECTURE.md`'s "The 3Dmol wrapper is deliberately imperative".
- note: Deliberately **not** claiming this explains the original blank-square report — the bug was found on whatever 3Dmol was installed then, and that history is not recoverable from the current tree. What is checkable now is the shipped render path. Two suggested actions: amend the architecture section to say the pinned version shares one context and that the container clear is justified by object reachability rather than by the context cap; and add a `webglcontextlost` listener on each viewer's canvas that calls `viewer.resize()` (the library's own recovery) and, failing that, shows a "reload to restore the 3D view" line instead of a blank square. The largest allocation the app makes against that shared context is `capturePng`'s up-to-4096 px re-render (`captureViewer.ts:94`, `:164-166`), which is the most likely trigger on a modest GPU.

---

### R-067: Every streamed token re-renders the whole chat transcript and re-parses every assistant message's markdown

- surface: code:frontend
- class: perf
- severity: S3
- cause: CODE
- confidence: suspected (code read), not yet reproduced
- found by: audit:frontend
- scope: `chat/ChatPane.tsx`, `chat/MessageBubble.tsx`, `lib/chatStore.ts`. React 19.2 with no React Compiler (`frontend/vite.config.ts` has a plain `react()` plugin, no `babel-plugin-react-compiler`), and `react-markdown` 10.1 has no internal memo (`grep -n "memo(" node_modules/react-markdown/lib/index.js` is empty). Not profiled.
- repro: Open a conversation with 30+ messages, ask something that produces a long answer, and record a React Profiler trace or a Performance trace during the stream. Expectation: one commit per token, each re-running `MessageBubbleRow` for every message in the list.
- observed: `frontend/src/chat/ChatPane.tsx:15-29` subscribes to the whole store with no selector:

  ```ts
  const {
    messages, streaming, activeSteps, turnInProgress, ...
  } = useChatStore();
  ```

  and `lib/chatStore.ts:178-185` writes a new `streaming` object on every token:

  ```ts
  case "token": {
    ...
    return {
      turnInProgress: true,
      streaming: { ...s.streaming, [messageId]: (s.streaming[messageId] ?? "") + delta },
    };
  }
  ```

  So every token is a store change, every store change re-renders `ChatPane`, and `ChatPane.tsx:189-191` maps the full history through an unmemoised component:

  ```tsx
  {messages.map((m, i) => (
    <MessageBubbleRow key={m.id ?? `pending-${i}`} message={m} />
  ))}
  ```

  `MessageBubbleRow` is a plain function (`MessageBubble.tsx:253`), and for an `AIMessage` it renders `AssistantBubble`, which runs `<ReactMarkdown remarkPlugins={[remarkGfm]}>{content}</ReactMarkdown>` (`MessageBubble.tsx:86`) — a full remark parse of that message's text, from scratch, on every render. `ToolResultChip` similarly re-runs `splitPaperBlocks` and `parsePlotArtifacts` (`MessageBubble.tsx:18-60`) per render.

  With a local model at a few tens of tokens per second and a conversation of a few dozen messages, that is on the order of a thousand markdown parses per second, all of them producing identical output.
- expected: A token append should re-render the streaming bubble and nothing else. The store's `token` case leaves `s.messages` untouched, so every element of `messages` keeps its identity across a token — the memo boundary is available for free.
- evidence: `frontend/src/chat/ChatPane.tsx:15-29`, `:189-191`; `frontend/src/chat/MessageBubble.tsx:78-99`, `:253-267`; `frontend/src/lib/chatStore.ts:178-185`.
- pointer: A whole-store subscription feeding an unmemoised list whose leaves do real parsing work.
- note: What would settle it: React Profiler during a stream, or simply `console.count()` in `AssistantBubble`. Fix direction, smallest first: wrap the export as `export const MessageBubbleRow = memo(function MessageBubbleRow({message}) {...})`. Because the `token` reducer does not touch `messages`, that alone removes essentially all of the cost. Narrowing `ChatPane`'s subscription to per-field selectors is a second, larger step and is not needed for the win. This is the only place in the frontend where memoisation is actually missing — the list panels (`JobManagerPanel`, `ConversationList`, `ProjectsSection`) all memoise their filter/sort correctly.

---

### R-068: Three of the four multi-frame viewers never check `response.ok` and have no `.catch`, so an artifact that fails to load shows "Loading..." forever

- surface: code:frontend
- class: bug
- severity: S3
- cause: CODE
- confidence: suspected (code read), not yet reproduced
- found by: audit:frontend
- scope: `ScanFrameViewer` (pes_scan/interp_pes masters), `GeometrySetViewer` (geometry_set), `EnsembleFrameViewer` (wigner_ensemble). `NebFrameViewer` (neb_ts) does it correctly and is the counter-example. Engine-independent — these read job artifacts, not engine output.
- repro: Open a scan master's drawer for a job whose `path_xyz` has been evicted or whose artifact route 404s (an archived job whose files were cleaned, or any 500 from the artifact route). The panel renders `Loading scan path...` indefinitely, with an unhandled promise rejection in the console and no way to tell whether it is slow or broken.
- observed: `frontend/src/jobs/ScanFrameViewer.tsx:45-56`

  ```ts
  fetch(jobArtifactUrl(job.job_id, "path_xyz"))
    .then((r) => r.text())
    .then((text) => {
      if (!cancelled) setFrames(parseMultiFrameXyz(text));
    });
  return () => { cancelled = true; };
  ```

  No `r.ok` check, so a JSON error body (`{"detail": "..."}`) or an HTML error page is handed to `parseMultiFrameXyz`; and no `.catch`, so a network failure or a throw inside the parser becomes an unhandled rejection that never reaches the UI. `frames` stays `null` and line 58-60 renders `Loading scan path...` permanently.

  `GeometrySetViewer.tsx:162-173` and `EnsembleFrameViewer.tsx:42-53` are the same five lines, with `Loading geometry set...` and `Loading sampled geometries...` as the stuck states.

  `NebFrameViewer.tsx:44-56` is the one that got the treatment:

  ```ts
  fetch(jobArtifactUrl(job.job_id, "neb_frames"))
    .then((r) => { if (!r.ok) throw new Error(`${r.status} ${r.statusText}`); return r.text(); })
    .then((text) => { if (!cancelled) setFrames(parseMultiFrameXyz(text)); })
    .catch((e) => { if (!cancelled) setFetchError(String(e)); });
  ```

  and it renders `Couldn't load frames: {fetchError}` (`NebFrameViewer.tsx:96-99`).
- expected: The standing rule in `.claude` memory `fixes-span-all-engines-and-methods` is that a fix is carried across every path, not only the one where the bug was noticed. `NebFrameViewer` is that fix; the other three multi-frame viewers were left behind. A permanent spinner with no error is also the failure mode the architecture's per-region boundary work exists to avoid — except a boundary cannot catch this, because nothing throws into React.
- evidence: `frontend/src/jobs/ScanFrameViewer.tsx:45-56` and `:58-60`; `frontend/src/jobs/GeometrySetViewer.tsx:162-177`; `frontend/src/jobs/EnsembleFrameViewer.tsx:42-57`; `frontend/src/jobs/NebFrameViewer.tsx:44-56`, `:94-104`.
- pointer: `fetch` does not reject on 4xx/5xx, so the only signal a route failed is `r.ok`, and it is not read.
- note: What would settle it: `docker compose exec` a rename of one scan job's `path_xyz` on disk and open its drawer. Fix direction: lift `NebFrameViewer`'s three-line shape into one shared hook (`useArtifactFrames(jobId, key)`), so the next viewer added inherits it rather than re-deciding. All three failures are silent today because the fetches also bypass `lib/api.ts`'s `request()` (see the raw-fetch finding below).

---

### R-069: A half-typed message follows the user into whatever conversation they switch to

- surface: code:frontend
- class: bug
- severity: S3
- cause: CODE
- confidence: suspected (code read), not yet reproduced
- found by: audit:frontend
- scope: `chat/Composer.tsx` and its one mount site in `chat/ChatPane.tsx`. Not reproduced in a browser.
- repro: In conversation A, type "optimise the geometry of" into the composer without sending. Click conversation B in the sidebar. The text is still in the box, now over B's transcript. Press Enter and it is sent to B.
- observed: The composer's text is plain local state and nothing resets it on a conversation change — `frontend/src/chat/Composer.tsx:36`:

  ```ts
  const [text, setText] = useState("");
  ```

  `setText` is called in exactly three places (`Composer.tsx:114` the welcome-screen prefill, `:162` after a successful send, `:281` the user typing). `ChatPane` renders `<Composer ... />` (`ChatPane.tsx:246-253`) with no `key`, and `ChatPane` itself is never unmounted on a thread switch — `useActiveThreadController` swaps the store contents in place (`lib/useActiveThreadController.ts:168-200`), which is deliberate and correct for the transcript.

  So the draft neither persists per conversation nor is cleared: it is a single global draft attached to whichever conversation happens to be open when Enter is pressed.
- expected: Either behaviour would be defensible; this is the one that is not. Every other piece of per-conversation state is swapped by `loadThread` (`useActiveThreadController.ts:178`), whose own comment explains that leaving the previous thread's content on screen "would visibly flash the old conversation's messages/molecule under the newly-active thread's identity". A draft is the same class of state and was not included.
- evidence: `frontend/src/chat/Composer.tsx:36`, `:114`, `:162`, `:281`; `frontend/src/chat/ChatPane.tsx:246-253`; `frontend/src/lib/useActiveThreadController.ts:168-200`.
- pointer: Component-local state in a component that outlives the thing it belongs to.
- note: What would settle it: type into the composer, switch conversations, look. Fix direction, in order of increasing value: `key={activeThreadId}` on `<Composer>` clears it (and drops the draft, which is the lesser evil); or a `Record<threadId, string>` in a small zustand store so each conversation keeps its own draft, which is what a user who switches to check a result and comes back would expect. `lib/composerDraftStore.ts` already exists for the prefill path and is the natural home, though note its current single-slot `{draft, nonce}` shape is for a different job and should not just be overloaded.

---

### R-070: Every selection row in the app is a `div`/`tr` with an `onClick` and no role, `tabIndex` or key handler, so conversations, jobs, orbitals and modes cannot be reached from the keyboard

- surface: code:frontend
- class: comfort
- severity: S3
- cause: CODE
- confidence: suspected (code read), not yet reproduced
- found by: audit:frontend
- scope: A scan of every `.tsx` in `frontend/src` for an element opening tag carrying `onClick` but neither `role=` nor `tabIndex`. Seven components; listed in full below. Radix-based controls (dialogs, popovers, tooltips) and all `<button>`s are excluded and are fine.
- repro: Load the app and press Tab repeatedly. Expectation from this reading: focus never lands on a conversation in the sidebar, a job row in either job list, an orbital row, a vibrational-mode row, a plot card, or a project's job row. Every one of those is a mouse-only target.
- observed: The scan (a small Python regex over each file's element opening tags) returns:

  | file:line | element | what it selects |
  |---|---|---|
  | `chat/ConversationList.tsx:154` | `div` | open a conversation |
  | `jobs/JobsPanel.tsx:72` | `tr` | open a job's drawer |
  | `jobs/JobManagerPanel.tsx:320` | `tr` | open a job's drawer |
  | `jobs/OrbitalTable.tsx:136` | `tr` | choose which orbital the isosurface shows |
  | `jobs/VibrationTable.tsx:64` | `tr` | choose which normal mode animates |
  | `plots/PlotsPanel.tsx:130` | `li` | open a plot |
  | `projects/ProjectFlyout.tsx:137` | `tr` | open a job filed in a project |

  For example `frontend/src/jobs/JobManagerPanel.tsx:319-338`:

  ```tsx
  <tr
    key={job.job_id}
    data-testid={`jobmanager-row-${job.job_id}`}
    onClick={() => setOpenJobId(job.job_id)}
    ...
  >
  ```

  Two of these are scientific controls rather than navigation: `OrbitalTable` and `VibrationTable` are how a user picks which orbital and which vibrational mode to look at.
- expected: The codebase already knows how to do this and does it elsewhere. `frontend/src/jobs/FrameScrubber.tsx:93` carries `tabIndex={0}`, and its own comment at `:113` records the lesson: *"`tabIndex` alone only made it reachable by Tab"* — so it handles keys too. The scrubber exists as "a second way to move through a long list without aiming at rows" (`docs/ARCHITECTURE.md`), which is currently the *only* keyboard way, and it is shown only when a panel is expanded (`JobDetailDrawer.tsx:1010`, `:1478`).
- evidence: The seven sites above; `frontend/src/jobs/FrameScrubber.tsx:93` and `:110-120` as the in-repo counter-example.
- pointer: Rows were built as styled table rows rather than as controls, so no affordance was inherited.
- note: What would settle it: tab through the running app, or an axe-core pass. Fix direction: one shared `rowProps(onActivate)` helper returning `{role: "button", tabIndex: 0, onClick, onKeyDown}` handling Enter and Space, applied at all seven sites — the same "one owner for the pattern" reasoning `ExpandablePanel` records for the overlay control row. Filed as `comfort` rather than `bug` per the brief's framing, but note the two table cases are the scientific selection path, not chrome. Checked and clean alongside this: every icon-only button in the app carries either `title` or `aria-label` (scan of all `<button>` elements with no text child found none missing both), and every modal and flyout is Radix, so focus trapping and Escape are handled.

---

### R-071: `_atomic_write_text`'s temp filename is keyed on pid alone, so two threads writing the same file in one process race
- surface: code:jobs
- class: bug
- severity: S3
- cause: CODE
- confidence: suspected (code read), not yet reproduced
- found by: audit:jobs
- scope: every caller of `write_status`/`write_result`/`write_meta` — all engines, all tasks.
- repro: `cancel()` a running job at the moment `_run_inner` writes its terminal status. `cancel()`'s pending branch and `_run_inner`'s writes are documented in the code as able to interleave ("a harmless 'cancelled' -> briefly 'running' -> 'cancelled again' flicker"), and both go through `_atomic_write_text`.
- observed: `tmp = path.with_suffix(path.suffix + f".tmp{os.getpid()}")` (`base.py:216`). Two threads in the same process targeting the same `status.json` compute the *same* temp path. Thread A's `tmp.write_text` truncates while B is mid-write (torn content published by whichever `os.replace` wins), and — worse — A's `os.replace` unlinks the temp file, so B's `os.replace` can raise `FileNotFoundError`. In `_run_inner` the final `write_status(spec.job_id, result["status"], "done")` (`base.py:1806`) sits *outside* the surrounding try/except, so an exception there propagates into `_run`, whose `finally` still releases the scheduler slot but leaves `status.json` non-terminal while `result.json` says `completed`.
- expected: the temp name must be unique per writer. `docs/ARCHITECTURE.md` §"Status is written atomically" claims the rename makes concurrent writes safe; the rename is atomic, the temp file is not private.
- evidence: `app/chemistry/jobs/base.py:216`
- pointer: pid uniqueness was chosen against the cross-process case (a `docker compose exec` test process) and is not enough for the in-process case the same module documents as reachable.
- note: `f".tmp{os.getpid()}.{threading.get_ident()}"`, or `tempfile.mkstemp(dir=path.parent)`. Related: `read_status` maps a `JSONDecodeError` to `{"status": "pending"}` (`base.py:263-265`), so a torn `status.json` presents a finished job as queued until the next restart's reconciliation. Also worth noting that `result_artifact_transaction`'s docstring justifies its narrow lock with "those all write a *different* `job_id`" — `cancel()` on a master and the orchestrator's per-tick `write_result` of that same master violate that assumption.

### R-072: a malformed `spec.json` leaks a scheduler admission slot permanently and strands the job at `pending`, silently
- surface: code:jobs
- class: bug
- severity: S3
- cause: CODE
- confidence: suspected (code read), not yet reproduced
- found by: audit:jobs
- scope: engine-independent; needs a `spec.json` that is valid JSON but not a valid `JobSpec` kwargs dict (an older/newer schema, a hand-edited file, a partially-written file that happens to parse).
- repro: place a `spec.json` containing `{"job_id": "x", "unexpected": 1}` in a job dir with a `pending` status, restart the backend.
- observed:
  ```
  spec_dict = read_spec(job_id)
  if spec_dict is None:
      self._scheduler.release(job_id); return
  spec = JobSpec(**spec_dict)          # base.py:1057 -- outside the try
  try:
      future = self._executor.submit(self._run, spec)
  except Exception:
      self._scheduler.release(job_id); raise
  ```
  A `TypeError` from `JobSpec(**spec_dict)` propagates out of `_on_admit` into `JobScheduler._dispatch_tick` and is swallowed by `_loop`'s `except Exception: pass` (`scheduler.py:179-181`) with no log line. By then `_pop_if_head` has already removed the job from the queue and added it to `_in_flight` (`scheduler.py:203-206`), and nothing will ever call `release` for it — the slot counts against `max_concurrent_jobs_total` and against that user's per-user cap for the life of the process, and the job sits at `pending` forever.
- expected: `_on_admit`'s own comments say the slot "has to be handed back here or it is held for the life of the process" — that reasoning covers the two branches inside the function but not the construction line above them.
- evidence: `app/chemistry/jobs/base.py:1049-1064`; `app/chemistry/jobs/scheduler.py:172-181`
- pointer: one statement outside the guarded region, plus a bare `pass` that makes the whole class of dispatcher failure invisible.
- note: move `JobSpec(**spec_dict)` inside the try, and log in `_loop`'s handler (`logger.exception("dispatch tick failed")`) — a silent dispatcher is the hardest thing here to diagnose, and the same `pass` hides any future exception from `_block_reason` (which does Postgres I/O) or `_resources_available`.
- resolution: fixed 2c0c19f
- regression test: tests/backend/jobs_04_job_timeout_and_dispatch.py

### R-073: cancelling a master races the orchestrator's next dispatch wave, leaving children nothing will cancel or aggregate
- surface: code:jobs
- class: bug
- severity: S3
- cause: CODE
- confidence: suspected (code read), not yet reproduced
- found by: audit:jobs
- scope: `pes_1d`/`interp_pes` (`scan_orchestrator`), `wigner_spectra` (`ensemble_orchestrator`), `batch` (`batch_orchestrator`); all engines.
- repro: cancel a 40-image scan while its orchestrator tick is inside `_dispatch_more`. Look for sub-jobs whose `created_at` is after the master's cancellation.
- observed: `JobManager.cancel`'s master branch snapshots `sub_job_ids_of(job_id)`, cancels the non-terminal ones, and only then writes the master's own `cancelled` status (`base.py:1556-1565`). It takes neither the orchestrator's module-level `dispatch_lock` nor `base.master_dispatch_guard`. An orchestrator tick that entered `_dispatch_more` before the master's status flipped will submit its wave afterwards; those children are `pending`/`running`, are not in the snapshot, and their master is terminal so no later tick (`_iter_running_*_masters` filters on `status == "running"`) will ever reconcile them.
- expected: `docs/ARCHITECTURE.md` §"A master's dispatch is guarded across processes" makes "decide which sub-jobs exist, dispatch the missing ones" a guarded section; cancellation reads and invalidates exactly that state and should be inside the same guard.
- evidence: `app/chemistry/jobs/base.py:1556-1565`; `app/chemistry/jobs/scan_orchestrator.py:57` (`dispatch_lock`) and the equivalents in the other two orchestrators
- pointer: the guard was added for the double-dispatch race and not extended to the other writer of the same state.
- note: write the master's terminal status *first*, then cancel children, then re-read `sub_job_ids_of` once more and cancel any stragglers — or take `master_dispatch_guard(job_id)` around the whole branch. Cheap either way.

### R-074: `registry2` says ORCA has an analytic CASSCF Hessian; the runner, the architecture doc and the ORCA manual all say numerical
- surface: code:jobs
- class: bug
- severity: S3
- cause: CODE
- confidence: suspected (code read), not yet reproduced
- found by: audit:jobs
- scope: ORCA CASSCF only. PySCF (`hessian="numerical"`, evidence `run`) and BAGEL (`numerical`, `run`) are consistent with their runners; I checked both.
- repro: `PYTHONPATH=$PWD python3 -c "from app.chemistry.registry2.tasks import supports; print(supports('orca','casscf','freq','').warnings)"` → `()`. Compare with `supports('bagel','casscf','freq','')`, which warns about the numerical Hessian's cost.
- observed: `capabilities.py:649` sets `hessian="analytic"` for `orca/casscf`, with `capabilities.py:670` `"hessian": _ev("manual", "documented; not executed here for CASSCF", _MANUALS)`. Meanwhile `orca_runner.build_input_text`'s frequency branch (`orca_runner.py:483-495`, the `NumFreq` bang line at `:491`) emits `NumFreq` for CASSCF with the comment *"the real ORCA manual states directly that CASSCF 'may be used for geometry optimizations and numerical frequency calculations' (analytic gradient, numerical Hessian only), so NumFreq here, not Freq"*, and `docs/ARCHITECTURE.md` §"CASSCF and CASPT2 gradients" says *"**ORCA** has an analytic gradient but a numerical-only Hessian"*.
- expected: the capability cell must describe what this app delivers. Two consequences: `docs/QM_CAPABILITIES.md:169` (the ORCA summary row) and `:213` (the per-cell row) (generated from this table) publishes "analytic (manual)" for `orca/casscf`, which is wrong; and `tasks._warn_numerical_hessian` only fires on `hessian == "numerical"`, so an ORCA CASSCF frequency job — genuinely `6·n_atoms` gradient evaluations — is approved with no cost warning while the same job on BAGEL or PySCF gets one.
- evidence: `app/chemistry/registry2/capabilities.py:649,670`; `app/chemistry/jobs/orca_runner.py:483-495`; `docs/ARCHITECTURE.md` §"CASSCF and CASPT2 gradients"; `docs/QM_CAPABILITIES.md:213`
- pointer: a `manual`-evidence cell transcribed from the manual's general statement rather than from the branch the runner actually emits — the same class the doc records for `orca/casscf excited_gradient`.
- note: change to `hessian="numerical"` with the runner's own citation as the evidence string, then re-run `scripts/generate_capability_docs.py --check` and `scripts/check_capability_matrix.py` (the golden table in the latter may also need the row corrected — worth checking, since a matching pair of mistakes is exactly what that script warns about).

### R-075: three orchestrators and the scheduler each re-walk every job directory on disk on a timer, so background cost scales with total jobs ever run
- surface: code:jobs
- class: perf
- severity: S3
- cause: CODE
- confidence: suspected (code read), not yet reproduced
- found by: audit:jobs
- scope: engine-independent; process-wide. Measured nowhere — this is a read of the loops, not a profile.
  Two halves have different reach: the per-owner `_running_job_ids()` walk and the `all_owners`/`get_quota_config`
  round trips only happen when `QC_AGENT_DATABASE_URL` is set (`_concurrent_jobs_block_reason` returns None
  immediately otherwise), while the `rglob`-per-`submit()` claim below is the **no-auth** path — with auth,
  `enforce_quota()` defers to `app/auth/storage_quota.enforce_all_quotas()`, which is outside this area and which
  I did not audit. The four directory-walking timers are unconditional in both configurations.
- repro: populate `data/jobs/` with a few thousand terminal job directories and watch backend CPU / `strace -c -f -e trace=openat` with no jobs running at all.
- observed: four independent timers, each doing `JOBS_DIR.iterdir()` and then `read_spec` + `read_status` (two `stat`s and two `json.loads`) *per job on disk*:
  - `scan_orchestrator._iter_running_scan_masters` (`scan_orchestrator.py:111`), every 3.0 s
  - `ensemble_orchestrator._iter_running_ensemble_masters` (`ensemble_orchestrator.py:70`), every 3.0 s
  - `batch_orchestrator._iter_running_batch_masters` (`batch_orchestrator.py:47`), every 3.0 s
  - `app/agent/job_watcher.py`, every 2.0 s
  plus `base._running_job_ids()` (`base.py:625-646`), called from `_concurrent_jobs_block_reason` **once per owner per dispatch tick** — so with `k` owners queued the scheduler walks the whole directory `k` times a second, and each call additionally does a `get_quota_config()` and an `all_owners("job")` Postgres round trip.
  Separately, `quota.enforce_quota()` runs inside every single `submit()` under `_quota_lock` (`base.py:1247-1249`) and, for every non-terminal job, does a full uncached `_dir_size` `rglob` (`quota.py:65-71`, `:108-118`). Wave dispatch calls `submit()` once per child, so dispatching a 40-child wave runs 40 quota sweeps, each `rglob`-ing up to 20 live ORCA/BAGEL scratch directories.
  Finally, when the host has no headroom, `_dispatch_tick` writes a fresh `status.json` for *every* queued job of *every* owner on every ~1 s tick (`scheduler.py:251-253`).
- expected: `docs/ARCHITECTURE.md` already made this argument once for `sub_job_ids_of` — P7.3 replaced a `JOBS_DIR` walk with a per-master `children.jsonl` manifest precisely because "its cost scales with EVERY job ever run, not with this master's own child count". The same reasoning applies to the four loops above, which were not converted.
- evidence: `app/chemistry/jobs/scan_orchestrator.py:111-121`; `app/chemistry/jobs/ensemble_orchestrator.py:70`; `app/chemistry/jobs/batch_orchestrator.py:47`; `app/chemistry/jobs/base.py:625-646`, `:1247-1249`; `app/chemistry/jobs/quota.py:65-71`; `app/chemistry/jobs/scheduler.py:251-253`
- pointer: "find the running masters" and "count the running jobs" are both answered by scanning the archive of everything that ever ran.
- note: the cheapest real fix is one shared, short-TTL (~1 s) in-process cache of `{job_id: (task, status)}` invalidated by `write_status`, consumed by all four loops and by `_running_job_ids` — the caps are already documented as "soft, eventually-consistent". Second: hoist `_running_job_ids()` out of `_concurrent_jobs_block_reason` and compute it once per `_dispatch_tick`. Third: call `enforce_quota()` once per wave rather than once per child (or move it to `job_watcher`'s existing `_QUOTA_ENFORCE_EVERY_N_TICKS` path, which already exists). Fourth: only rewrite a queued job's `status.json` when the message actually changes.

### R-076: ORCA multi-state gradient / multi-pair NAC subdirectories are never scratch-cleaned
- surface: code:jobs
- class: perf
- severity: S3
- cause: CODE
- confidence: suspected (code read), not yet reproduced
- found by: audit:jobs
- scope: ORCA only, and only the multi-entry paths (`len(target_states) > 1` or `len(state_pairs) > 1`). BAGEL and PySCF write no subdirectories.
- repro: run an ORCA `single_point/grad` with `target_states=[1,2,3]` and `du -sh` the job directory after it completes; compare with a single-state run.
- observed: `run_gradient` and `run_nac` create `state_<n>/` and `pair_<a>_<b>/` subdirectories and run a full ORCA process in each (`orca_runner.py:943-948`, `:1026-1030`). `scratch.cleanup_scratch_files` only ever looks at the top level: `_orca_scratch_files` returns `[f for f in job_dir.iterdir() if f.name.startswith("input") ...]` (`scratch.py:70`), and the delete loop is additionally gated on `f.is_file()`. So every per-state ORCA scratch set — the module docstring cites ~60 MB for one CASSCF/cc-pVDZ run — survives in full, one copy per state or pair.
- expected: the module exists precisely so "ORCA/BAGEL's large intermediate files … don't accumulate indefinitely". The leftovers are also billed to the owner's storage quota via `quota._dir_size`'s `rglob`, and re-walked by every uncached quota sweep.
- evidence: `app/chemistry/jobs/scratch.py:70`; `app/chemistry/jobs/orca_runner.py:943-948`, `:1026-1030`
- pointer: the cleanup allowlist predates the one-process-per-target layout added with multi-state derivatives.
- note: recurse into direct subdirectories in `_orca_scratch_files` (the same `input*` allowlist applies unchanged there), keeping the protected-basename cross-check. Related and smaller: a job finalised by `_watch_orphan_worker` never runs `cleanup_scratch_files` at all — only `JobManager._run`'s `finally` calls it.

### R-077: MC-PDFT's documented state reordering is noted only on the energy runner, and the derived excitation/total-energy fields still assume state 0 is the ground state
- surface: code:jobs
- class: bug
- severity: S3
- cause: CODE
- confidence: suspected (code read), not yet reproduced
- found by: audit:jobs
- scope: PySCF `mcpdft` (the only engine with it). `lpdft`/`cmspdft` diagonalise an effective Hamiltonian, so ascending order is expected there; I did not verify that claim independently. Not applicable to ORCA/BAGEL.
- repro: run a state-averaged MC-PDFT job on a system where the MC-PDFT ordering differs from the SA-CASSCF ordering, then read `summary.excitation_energies_eV[0]` (expect a negative number) and `summary.total_energy_hartree` (expect the second-lowest state).
- observed: `_state_energies_from` returns `mc.e_states` in SA-CASSCF label order with no sort (`pyscf_runner.py:1771-1783`; `grep -n "sort\|argsort" pyscf_runner.py` finds only `sort_mo` and unrelated uses). `run_pdft_family` correctly writes `summary["mcpdft_state_order_note"]` explaining this (`pyscf_runner.py:2120-2125`) — but `grep -rn mcpdft_state_order_note app/` returns that one line only, so `run_gradient`'s PDFT branch and `run_nac` report the same ladder with no note. Meanwhile `derivatives.excitation_energies_eV` computes `(e - states[0]) * HARTREE_TO_EV` (`derivatives.py:74`) and `facts.canonicalize` sets `total_energy_hartree = states[0]` when no scalar energy is present (`facts.py:356`), both under names that assert "ground state".
- expected: `docs/QM_CAPABILITIES.md:73` and `capabilities.py:375` both record that "states can come out reordered against their MCSCF labels"; the brief asks whether the code honours it. It half does.
- evidence: `app/chemistry/jobs/pyscf_runner.py:1771-1783`, `:2120-2125`; `app/chemistry/jobs/derivatives.py:74`; `app/chemistry/jobs/facts.py` `canonicalize`'s `total_energy_hartree = states[0]` fallback at `facts.py:356`
- pointer: a caveat written as prose on one runner rather than as a property of the ladder every reader consumes.
- note: two options, and the maintainer should pick — either sort the MC-PDFT ladder ascending and remap `target_states` accordingly (changes what "S1" means for a gradient), or leave the order and have `facts` emit `total_energy_hartree = min(states)` plus carry the note onto every summary that carries `state_energies_hartree` for `method == "mcpdft"`. Confirming it needs one real reordering case; a negative `excitation_energies_eV[0]` in any existing MC-PDFT `result.json` on disk would settle it immediately.
- resolution: fixed da6efb6
- regression test: tests/backend/grad_04_target_state_zero.py

### R-078: BAGEL per-atom gradient/NAC vectors are assembled without checking the atom count
- surface: code:jobs
- class: bug
- severity: S3
- cause: CODE
- confidence: suspected (code read), not yet reproduced
- found by: audit:jobs
- scope: BAGEL only (`run_gradient`, `run_nac`). ORCA reads `.engrad` (a length-checked structured file) for gradients; PySCF returns arrays.
- observed: `_parse_atom_vectors` builds `{int(idx): [x, y, z]}` from `_BAGEL_ATOM_VEC.findall(section)` and returns `[by_index[i] for i in sorted(by_index)]` (`bagel_runner.py:863-866`). Any atom row the regex misses is simply absent: the returned vector is shorter than the molecule and every downstream consumer (the derivative norm, the frontend's per-atom arrow overlay) silently reads atom *k*'s vector as belonging to atom *k*. Nothing compares `len(vector)` with `len(molecule["symbols"])`.
- expected: the module already treats a request/result count mismatch as a hard failure ("refusing to guess which state each belongs to", `bagel_runner.py:1312-1316`); the same standard should apply one level down, to atoms.
- evidence: `app/chemistry/jobs/bagel_runner.py:863-866`
- pointer: dict-then-sort silently tolerates gaps, where a list-append plus a length assertion would not.
- note: low confidence that the regex ever *does* miss a row on real BAGEL output — I have no committed BAGEL derivative output to check. Cheap and unambiguous fix regardless: raise if `len(vector) != len(molecule["symbols"])`, alongside the existing section-count check.

---

### R-079: `plt.subplots`/`plt.rc_context` are called from concurrent request and orchestrator threads with no lock
- surface: code:server
- class: bug
- severity: S3
- cause: CODE
- confidence: suspected (code read), not yet reproduced
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

### R-080: Six list routes return the whole collection with no limit or pagination
- surface: code:server
- class: perf
- severity: S3
- cause: CODE
- confidence: suspected (code read), not yet reproduced
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
- coordinator (P4): measured: GET /api/jobs p50 5.5 ms at 8 jobs, 20.9 ms at 58 jobs (~linear), p95 30 ms; polled every 4 s per tab, so ~100 ms per poll at a few hundred jobs. Confirms the O(n). evidence/p4-route-latency-loaded.json.

### R-081: `GET /api/jobs/{id}/neb_frames_live` reads and splits the whole trajectory file on every poll
- surface: code:server
- class: perf
- severity: S3
- cause: CODE
- confidence: suspected (code read), not yet reproduced
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

### R-082: `PATCH /api/admin/bug-reports/{id}` returns 200 for a report that does not exist, and 500 for a malformed id
- surface: code:server
- class: bug
- severity: S3
- cause: CODE
- confidence: suspected (code read), not yet reproduced
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

### R-083: Two error paths return an internal 500 carrying engine paths and stack text
- surface: code:server
- class: comfort
- severity: S3
- cause: CODE
- confidence: suspected (code read), not yet reproduced
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
- partial: the unvalidated `index` half was closed in P1.3 alongside R-005,
  which is where the same route's other unvalidated inputs were fixed; the
  500-carrying-engine-paths half is P5.2's.
- note: Fix: validate `index >= 1` at the route, log the exception, and return a short 500 detail.


---

### R-084: `_agent_notice`'s cas_reco branch tests the same condition twice where the comment says it tests the subtype
- surface: code:agent
- class: bug
- severity: S4
- cause: CODE
- confidence: suspected (code read), not yet reproduced
- found by: audit:agent
- scope: `JobWatcher._poll_once`'s bucketing. Currently inert, because
  `cas_reco` has no subtype that recommends nothing.
- repro: none today. It becomes live the first time `cas_reco` gains a
  non-recommending subtype.
- observed: `app/agent/job_watcher.py:518-519`:
  ```
  elif spec is not None and spec.get("task") == "cas_reco" \
          and spec.get("task") == "cas_reco":
  ```
  The comment immediately above (lines 511-514) explains the second
  clause as a *subtype* check: *"The subtype check is not redundant: it
  keeps this branch honest if cas_reco ever gains a subtype that
  recommends nothing, the way the since-removed cas_reco/explain did."*
- expected: the second clause should read `spec.get("subtype")` against
  whatever set of subtypes should get the recommendation notice — which
  is the check the comment describes and the code does not perform.
- evidence: `app/agent/job_watcher.py:511-520`.
- pointer: a copy-paste when `cas_reco/explain` was removed.
- note: filed at S4 because it is currently unreachable, but it is the
  kind of thing that is invisible until the subtype exists and then
  routes a non-recommending job into a notice that instructs the model to
  open a pre-filled CASSCF draft.

---

### R-085: `update_job_draft` silently discards valid parameters when one key in the same call is a misrouted geometry
- surface: code:agent
- class: bug
- severity: S4
- cause: CODE
- confidence: suspected (code read), not yet reproduced
- found by: audit:agent
- scope: the `misrouted` branch of `update_job_draft`. Its sibling
  branch (`unknown`/`inapplicable`) handles this correctly.
- repro: have the model call
  `update_job_draft({"molecule": "water", "basis": "cc-pvdz"})`. The
  reply names only `molecule`; `basis` is also not recorded, and nothing
  says so.
- observed: `app/agent/tools.py:3869-3876` returns a `Command` carrying
  only a `ToolMessage` — no `job_draft` key — so the locally-built
  `params`/`draft` (including `basis`) is thrown away. The message reads
  *"A structure is not a job parameter, so molecule was not recorded in
  the draft"*, which implies the rest was. The `unknown`/`inapplicable`
  branch a few lines earlier is explicit about the same behaviour
  (`_unknown_param_message`, `tools.py:3200-3206`): *"so nothing was
  recorded -- not even the keys in the same call, since a half-applied
  update is harder to reason about than none."*
- expected: the same sentence, or persist the valid keys. Either is fine;
  what is not fine is doing one and saying the other, because the model
  then believes `basis` is set and moves on.
- evidence: `app/agent/tools.py:3869-3876`; `app/agent/tools.py:3200-3206`.
- pointer: the all-or-nothing rule was articulated when the unknown-key
  refusal was added and not applied to the older misrouted-key refusal's
  wording.
- note: trivial fix. Settled by calling
  `update_job_draft.func(updates={"molecule":"water","basis":"cc-pvdz"}, ...)`
  against a draft and reading back `job_draft`.
- resolution: fixed b307ed4
- regression test: tests/backend/draft_02_canonical_method_survives.py


---

### R-086: `search_academic_literature` parses the response body outside its try block
- surface: code:agent
- class: bug
- severity: S4
- cause: CODE
- confidence: suspected (code read), not yet reproduced
- found by: audit:agent
- scope: `app/agent/scholar_search.py`. `web_search.py` is clean —
  everything network-facing is inside its `try`.
- repro: have Semantic Scholar return a 200 with a non-JSON body (a
  proxy interstitial, an HTML error page). `resp.json()` raises
  `JSONDecodeError`.
- observed: `app/agent/scholar_search.py:74-85`: the `try/except` covers
  only `requests.get`, and status handling covers 429 and `not resp.ok`.
  Line 85 is `data = resp.json().get("data") or []`, outside any guard.
- expected: the same graceful degrade the rest of the function has — the
  tool's own docstring promises *"If this tool errors (including a
  rate-limit response), it tells you to use web_search instead"*.
- evidence: `app/agent/scholar_search.py:74-85`.
- pointer: the try was scoped to the connection, not the round trip.
- note: S4 because `ToolNode` catches a tool exception into a ToolMessage
  by default, so the model gets an error string rather than a crashed
  turn — but it gets a raw `JSONDecodeError` instead of the
  fall-back-to-web instruction the docstring promises. This also
  interacts with the `_call` finding above: an exception here becomes a
  false literature hit.

---

### R-087: `purge_own_data` leaves the caller's plots and projects behind, and the response counts do not mention them

- surface: code:auth
- class: comfort
- severity: S4
- cause: CODE
- confidence: suspected (code read), not yet reproduced
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

### R-088: `revoke_session` is never called, so the `sessions` table only ever grows

- surface: code:auth
- class: comfort
- severity: S4
- cause: CODE
- confidence: suspected (code read), not yet reproduced
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

### R-089: `POST /api/admin/invites` accepts any `ttl_hours`, unlike the reset-token route beside it

- surface: code:auth
- class: comfort
- severity: S4
- cause: CODE
- confidence: suspected (code read), not yet reproduced
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

### R-090: `GET /api/projects/{id}` returns a row per member job with no per-job ownership check, unlike the download route

- surface: code:auth
- class: security
- severity: S4
- cause: CODE
- confidence: suspected (code read), not yet reproduced
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
- resolution: fixed 106cb5b
- regression test: tests/backend/sec_11_child_job_ownership.py


---

### R-091: `update.sh`'s destructive-change confirmation uses a bare `read`, which under `set -e` exits silently at EOF — the exact class the installer audit removed from `install.sh`
- surface: code:deploy
- class: comfort
- severity: S4
- cause: CODE
- confidence: suspected (code read), not yet reproduced
- found by: audit:deploy
- scope: `scripts/update.sh:335-337` and `scripts/restore.sh:81,100`. The
  admin-panel path always passes `--yes`, so this only bites a human running
  the script with stdin closed, redirected, or from a non-interactive
  wrapper.
- repro: `scripts/update.sh < /dev/null` on a commit the report calls
  destructive. The script exits 1 at the prompt having printed the question
  and nothing else.
- observed: `scripts/update.sh:335-337`

      printf 'Type UPDATE to go ahead anyway: '
      read -r reply
      [ "$reply" = "UPDATE" ] || die "aborted -- nothing was touched."

  `read` returns non-zero at end of input and `set -euo pipefail` is in force,
  so the `die` message never prints.
- expected: `scripts/lib/common.sh` — which `update.sh` already sources —
  carries `ask()` and `ask_yn()`, written for exactly this ("A bare `read`
  returns non-zero at end of input, and under `set -e` that exits
  mid-question with nothing printed at all -- which is what Ctrl-D, a closed
  terminal, or a pipe that ran out used to do to install.sh").
- evidence: `scripts/update.sh:336`; `scripts/lib/common.sh` `ask()`
  docstring; `scripts/restore.sh:81`
- pointer: the fix landed in `install.sh` and in the shared library, but
  `update.sh`'s one prompt was not converted to use it.
- note: harmless in outcome (nothing has been changed at that point) but
  silent, and `restore.sh`'s two prompts have the same shape at a much worse
  moment — mid-outage, at "Type the database name to proceed".
- resolution: fixed, pending commit
- regression test: tests/backend/deploy_07_update_rollback_and_backup.py

### R-092: `nginx/nginx.conf`'s header describes a public listener and a kill-switch script that were both deleted
- surface: code:deploy
- class: docs
- severity: S4
- cause: CODE
- confidence: suspected (code read), not yet reproduced
- found by: audit:deploy
- scope: `nginx/nginx.conf` comments only; the directives are correct.
- repro: `ls scripts/toggle_public_access.sh` → does not exist.
- observed: `nginx/nginx.conf:3-9` — "Two listeners, one config, per the
  deployment plan: an always-on campus intranet listener ... and a public
  listener that a host sysadmin can cut off independent of application health
  (see scripts/toggle_public_access.sh -- that's the REAL kill switch; the
  app-level admin toggle below is the fast, graceful one)". Lines 11-14 then
  tell the reader to "Replace <intranet-hostname>/<public-hostname> and the
  campus CIDR below", neither of which appears in the file. Lines 148-160 say
  the public listener, the admin toggle and that script were all removed on
  2026-08-25.
- expected: the top of the file should not contradict the bottom of the same
  file. A reader reaches for a script that is not there, and looks for a
  hostname placeholder that does not exist.
- evidence: `nginx/nginx.conf:3-14` vs `nginx/nginx.conf:148-160`
- pointer: the removal edited the block it deleted and not the header above
  it.
- note: also worth a line in the same pass — `docs/DEPLOYMENT.md` should be
  checked for the same stale reference (I have flagged the DEPLOYMENT.md
  claims for the live walkthrough in `doc-claims.md`).
- resolution: fixed, pending commit
- regression test: tests/backend/deploy_07_update_rollback_and_backup.py

### R-093: `check_destructive.sh`'s disappearing-route check cannot see a router prefix, so a renamed prefix reads as "no routes removed"
- surface: code:deploy
- class: bug
- severity: S4
- cause: CODE
- confidence: suspected (code read), not yet reproduced
- found by: audit:deploy
- scope: check 4 (`check_destructive.sh:433-450`) only.
- repro: change `APIRouter(prefix="/api/jobs")` to `prefix="/api/job"` in
  `server/routes/jobs.py`, leaving every decorator untouched. Run
  `check_destructive.sh` across that commit: every route path it extracts is
  unchanged, so it reports the benign `[warn]` branch rather than
  `[destructive] API routes disappear while old frontend assets are still in
  browsers`.
- observed: `check_destructive.sh:434`

      git grep -h -E '@(app|router)\.(get|post|put|patch|delete)\(' "$FROM_SHA" -- server \
        | sed -E 's/.*\("([^"]*)".*/\1/' | sort -u

  Only the decorator's own literal is captured. It also misses any path
  written with single quotes or built from an f-string, and any decorator
  whose path is not on the same line.
- expected: the check exists to catch "a tab open across the update keeps its
  already-loaded JS and will call these until it is reloaded", and a prefix
  rename breaks exactly that, for every route on the router at once — the
  largest instance of the thing being checked for.
- evidence: `check_destructive.sh:434-436`; the `prefix=` arguments in
  `server/routes/*.py`
- pointer: a false negative, not a false positive, so it fails quietly.
- note: cheap improvement — also diff the `APIRouter(prefix=...)` literals per
  file and report a changed prefix as removing every route under it. Or
  extract routes from the running app's `/openapi.json` for the FROM side.
- resolution: fixed, pending commit
- regression test: tests/backend/deploy_07_update_rollback_and_backup.py

### R-094: `main.tsx`'s comment says no query in the app sets `refetchInterval`; thirteen of them do

- surface: code:frontend
- class: docs
- severity: S4
- cause: CODE
- confidence: suspected (code read), not yet reproduced
- found by: audit:frontend
- scope: `frontend/src/main.tsx` against `frontend/src/lib/queries.ts`.
- repro: `grep -c refetchInterval frontend/src/lib/queries.ts`.
- observed: `frontend/src/main.tsx:17-21`:

  ```ts
  // Job/thread/state data is kept fresh by SSE push (see server/sse.py),
  // not by polling -- refetchInterval is deliberately never set on any
  // query in this app. staleTime just avoids redundant refetches on
  // component remount for data that hasn't been invalidated.
  staleTime: 10_000,
  ```

  `lib/queries.ts` sets `refetchInterval` thirteen times, across these hooks: `useJobsQuery` (4 s fallback), `useJobsListQuery` (4 s), `useProjectsQuery` (8 s), `useJobsQuotaQuery` (30 s), `useJobQuery` (4 s fallback), `useJobChildrenQuery` (3 s), `useWignerTransitionsQuery` (3 s), `useKbQuotaQuery` (30 s), `usePlotsQuery` (8 s), `useUploadsQuotaQuery` (30 s), `useJobLogQuery` (1.5 s), `useShareInboxQuery` and `useShareOutboxQuery` (8 s).
- expected: This is the first file anyone reads when asking "how much does one open tab cost", and it currently answers "nothing", which is off by roughly fifty requests a minute.
- evidence: `frontend/src/main.tsx:17-21`; `frontend/src/lib/queries.ts:40-213`.
- note: Trivial to fix and worth fixing because of what it is: the file that sets the global default is where someone will look before adding the fourteenth interval. Suggested replacement text: SSE push is the fast path for the active conversation's own data; anything cross-conversation (the job manager, projects, plots, shares) and anything with no event behind it is polled, per-hook, in `queries.ts`.

---

### R-095: Several raw `fetch()` call sites bypass `lib/api.ts`'s `request()`, so their 401 and 503 never reach the auth or maintenance handlers, and one download name ignores the naming convention

- surface: code:frontend
- class: bug
- severity: S4
- cause: CODE
- confidence: confirmed by code read
- found by: audit:frontend
- scope: All `fetch(` call sites outside `lib/api.ts`'s `request()`, plus `downloadPlotPng` inside it. Not reproduced.
- repro: With a job drawer open showing an orbital, expire the session (log in as the same user in another browser, which supersedes the Redis session key). Click a different orbital row. Expectation: the viewer shows `Couldn't load orbital: Error: 401 Unauthorized` and the app stays on screen, rather than returning to the login screen the way any `request()`-routed call would.
- observed: `request()` is where the 401 and the maintenance-503 hooks live (`lib/api.ts:236-242` and `:221-235`). These call sites do not go through it: `jobs/MoCubeViewer.tsx:178` (the orbital cube POST/GET), `jobs/ScanFrameViewer.tsx:48`, `jobs/GeometrySetViewer.tsx:165`, `jobs/EnsembleFrameViewer.tsx:45`, `jobs/NebFrameViewer.tsx:45` and `:63`, and `lib/api.ts:481` (`downloadPlotPng`, which re-implements the error branch by hand and omits both hooks).

  Separately, `downloadPlotPng`'s fallback filename does not follow the convention — `frontend/src/lib/api.ts:491`:

  ```ts
  downloadBlob(await res.blob(), filenameFromResponse(res) ?? `${jobId}_${kind}.png`);
  ```

  `${jobId}` is the raw id, not the job's `filename_stem`, and `${kind}` is an internal identifier (`uvvis_inline`, `optimization_energy`), so the fallback lands as e.g. `78a32a61e4f2...b1_uvvis_inline.png`. The header is normally present, so this is a fallback path only — but `filenameFromResponse` (`lib/api.ts:460-463`) matches only a quoted `filename="..."`, so an unquoted or `filename*=` header falls through to it.
- expected: `docs/ARCHITECTURE.md`'s "Who names a download depends on who knows its extension" states the shape as `{safe job name}_{descriptor}{extension}`, and `lib/jobFilename.ts` exists to build exactly that browser-side. The fallback should be `jobDownloadName(jobFilenameStem(job), kind, ".png")`, which needs the job row rather than just its id.
- evidence: `frontend/src/lib/api.ts:205-244` (`request`), `:478-492` (`downloadPlotPng`), `:460-463`; `frontend/src/jobs/MoCubeViewer.tsx:178`.
- note: Low severity on both halves. The maintenance case in particular is already covered in practice — `useJobsListQuery`'s unconditional 4 s poll goes through `request()` and trips `MaintenanceGate` within seconds of an update starting, which is exactly the mechanism `lib/api.ts:194-198` describes. The 401 case is the one with a real user-visible symptom (a stale-session tab whose viewers show raw HTTP errors instead of bouncing to login), and `tests/frontend/fe_sec_*` is where a check for it would belong. Fix direction: give `api.ts` an exported `requestText(path, init)` that shares `request()`'s error branch and returns text, and route all six viewer fetches through it; that also gives the three frame viewers in the finding above their `r.ok` check for free.

---
- coordinator: Both halves verified. `request()` centralises the maintenance-503 branch (`api.ts:226`) and the 401 branch (`:236`); the viewer fetches (`MoCubeViewer`, `ScanFrameViewer`, `GeometrySetViewer`, `EnsembleFrameViewer`, `NebFrameViewer`) and `downloadPlotPng` (`:477`) use bare `fetch` and reach neither, so during an in-app update those calls fail with a raw error instead of the maintenance overlay, and a session that expired mid-view is not bounced to login. The naming half: `api.ts:491` falls back to `${jobId}_${kind}.png`, a bare job id, when the Content-Disposition header is absent, which breaks the standing safename_descriptor.extension rule; the primary path (the header) follows it. S4 stands for both.

### R-096: a PES-scan plot's "State 1" is S1, while `target_states=[1]` is S0
- surface: code:jobs
- class: comfort
- severity: S4
- cause: CODE
- confidence: suspected (code read), not yet reproduced
- found by: audit:jobs
- scope: `pes_1d`/`interp_pes` excited-state scans, all engines.
- observed: `_build_state_series` labels index 0 `"Ground state"` and index `i` `f"State {i}"` (`scan_orchestrator.py:103-106`), so the legend's "State 1" is the first excited state. `target_states`/`state_pairs` use the opposite convention (state 1 is S0), stated explicitly in `derivatives.py:52-63` and `docs/ARCHITECTURE.md`.
- expected: one user-facing numbering. The architecture already flags this as "one numbering trap … there are two conventions in the codebase and they differ by one".
- evidence: `app/chemistry/jobs/scan_orchestrator.py:103-106`
- pointer: two independently reasonable labelling choices meeting in one UI.
- note: `"S0"` / `f"S{i}"` in the legend would be unambiguous and matches how ORCA's own multi-run headers are written elsewhere in this codebase (`f"===== state S{state - 1} ====="`, `orca_runner.py:961`).
- resolution: fixed da6efb6
- regression test: tests/backend/grad_04_target_state_zero.py

### R-097: `_pop_cancel_event` can disarm the Stop button for a turn it does not belong to
- surface: code:server
- class: bug
- severity: S4
- cause: CODE
- confidence: suspected (code read), not yet reproduced
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

### R-098: fair-scheduler admission gives one user two slots before a second user's first, on an idle stack
- surface: code:jobs
- class: bug
- severity: S2
- cause: CODE or HARNESS, undetermined (see the settling experiment)
- confidence: confirmed reproducible 2/2 against a confirmed-idle stack; the cause between a real scheduler regression and a test race is not yet settled
- found by: baseline P1.1, then P1.5 in isolation
- scope: `app/chemistry/jobs/scheduler.py`'s round-robin dispatch under a global cap of 1. Not engine-specific; the probe is ORCA CASSCF only because it needs a job slow enough to observe admitting.
- repro:
  ```bash
  QC_AGENT_TEST_BASE_URL=https://127.0.0.1:8444 PYTHONPATH=$PWD \
    QC_AGENT_LLM_BASE_URL=http://localhost:11434/v1 \
    python3 tests/backend/perf_04_fair_scheduling.py
  ```
  against an otherwise-idle stack (confirmed idle here: 8 admin jobs, 9 threads, matching the pre-review snapshot).
- observed: 4 of 6 checks pass; the two fairness checks fail with
  `order=['A', 'A', 'B', 'A', 'A', 'A', 'A']` and `n_observed=7`. User A's
  burst of six and user B's single job are submitted synchronously
  (`perf_04:143-144`), cap is 1, and B is admitted third rather than second.
  The order was byte-identical on the full-suite run and the isolated run.
- expected: the fair scheduler exists precisely so B's one job is admitted in
  the rotation right after A's first (`A, B, A, A, ...`). `_dispatch_tick`
  advances `_rr_pos` to `idx+1` only on a real admission, and a hand-trace of
  A1 admitted at idx 0 (`_rr_pos=1`) predicts the next tick starts at B. The
  observed order contradicts that trace.
- expected (the README claim this breaks): `tests/README.md` states perf_04
  "against an otherwise idle stack (5/5)" and tells the reader to confirm that
  before treating a failure as a regression. Confirmed here, and it is **not**
  5/5 on an idle stack, and `n_observed=7` is not the documented "observed 5
  of 7" cap-occupied skew. So either the scheduler regressed since that note
  was written or the note was always optimistic; the doc is wrong either way.
- evidence: docs/evaluation/2026-09-app-review/evidence/p1-notes.md, and the
  full run at evidence/backend-run.log
- pointer: `app/chemistry/jobs/scheduler.py` `_dispatch_tick`, the `_rr_pos`
  advance and the `start = self._rr_pos % n` walk; and the synchronous
  submit-both-then-observe shape at `perf_04:143-146`.
- note: **the settling experiment**, which decides CODE vs HARNESS and must run
  before this is acted on. Instrument `enqueue` (or the test) to log the wall
  order in which each job_id is enqueued AND the `_order`/`_rr_pos` state at
  each admission, then re-run. If B's enqueue lands after A's second admission,
  it is a test race (HARNESS): the test intends B queued while A's queue is
  full, but submits are not synchronised against the dispatcher thread, so a
  fast dispatcher can admit A1, release on cancel, and admit A2 before B is
  enqueued. If B is enqueued before A's second admission and still admitted
  third, it is a real round-robin defect (CODE), which on a shared lab
  deployment is the starvation this module exists to prevent and is S2. This
  is exactly the kind of discrepancy the standing rule says to chase rather
  than round away: the README invited treating it as a known artifact, and
  re-running per the README's own instruction showed it is not one.

### R-099: the CAS refinement drawer's natural-orbital occupation table renders zero data rows
- surface: job-viewers (cas refinement drawer)
- class: bug
- severity: S3
- cause: CODE, undetermined between empty summary data and a render guard
- confidence: reproduced once via cas_14's own seeded refinement; the root cause is not yet settled
- found by: baseline P1.2 (tests/frontend/cas_14_refinement_drawer.spec.mjs)
- scope: the refinement drawer for a completed `cas_reco/refine` job. Seen on a water refinement on PySCF; not checked on other molecules.
- repro: `node tests/frontend/cas_14_refinement_drawer.spec.mjs` against the stack. It seeds a real recommendation and refinement (both completed here: `056dbd79c4eb` / `9487f0258ba1`), opens the refinement drawer, and checks the occupation table.
- observed: 13 of 17 checks pass. The rotation trail renders correctly (2 rows, each with the prune reason and the orbital, e.g. "prune out 2 (occ 1.9994)"), but the natural-orbital occupation table has **0 data rows**: "it has one row per active orbital (0 rows) -- 0". The failing checks are "the refined space is stated", "the occupation table renders", "one row per active orbital", and "each row carries a character label".
- expected: one row per active orbital of the refined space, each with its natural occupation and orbital-character label. The drawer reads `job.summary["natural_occupations"]` and renders only when it is a non-empty array (`frontend/src/jobs/JobDetailDrawer.tsx:1282-1298`); the runner publishes that key at `pyscf_runner.py:3301` and `refine.py:255`. So either the refinement's summary carried an empty `natural_occupations` for this job, or the refined-space section is gated on a field the runner does not publish (`JobDetailDrawer.tsx:942` reads `refined_active_electrons`/`refined_active_orbitals`, and the code comment at :1239-1242 warns the runner does NOT publish `refined_*` keys).
- evidence: docs/evaluation/2026-09-app-review/evidence/frontend-run.log (the cas_14 block)
- pointer: the comment at `JobDetailDrawer.tsx:1239-1242` is itself the likely lead: it says `RefineResult` names fields `refined_active_*` but the runner publishes them under the recommendation's own keys, "so there is no `refined_` anything". If the "refined space is stated" line and the occupation table are gated on a `refined_*` key that is never published, the table is empty by construction.
- note: settle in P3.4, which drives `cas_reco/refine` end to end and can read the completed job's `result.json` directly to see whether `natural_occupations` is populated and under which key. cas_14 was not in the 2026-09-06 frontend failure list, but the suite has changed since, so "regression" is not established; the spec's own header says the drawer "did not exist" before it was written, so this may be a still-incomplete rendering rather than a regression.

### R-100: the route auth-sweep test reports a false regression because its public-route list omits the intentionally-public /api/version
- surface: code:tests (harness)
- class: bug
- severity: S4
- cause: HARNESS
- confidence: confirmed by code read
- found by: baseline P1.3 (tests/e2e/e2e_03_route_auth_sweep.py)
- scope: the anonymous pass of the route auth sweep only.
- repro: `bash tests/e2e/run_e2e.sh e2e_03`.
- observed: `[FAIL] anonymous caller is rejected by all 101 non-public routes -- GET /api/version -> 200`, so the whole e2e suite reports 2 failed scripts instead of 1. The non-admin pass (25 admin routes, all 403) and the cross-user pass (thread routes, all 404) both pass.
- expected: `/api/version` is deliberately unauthenticated. `server/main.py:155-160`: "Unauthenticated and outside the `if DATABASE_URL:` block above, for the same reason /api/health is: it has to answer while the deployment is in [maintenance]". The test's `PUBLIC_ROUTES` set (`e2e_03:40`) lists only `/api/health`, `/api/auth/login`, `/api/auth/register`, and omits `/api/version`.
- evidence: docs/evaluation/2026-09-app-review/evidence/e2e-run.log (the e2e_03 block)
- pointer: add `("GET", "/api/version")` to `PUBLIC_ROUTES` in `tests/e2e/e2e_03_route_auth_sweep.py:40`.
- note: this is a test fix, in the docs/tests zone the review may touch, but it is left for the fix phase to keep the review record-only. It matters for the report's honesty: without it the e2e suite looks like it has an auth regression, and it does not. Distinct from R-001/R-003, which are real cross-user paths this sweep does not probe (it covers thread routes only, as its own cross-user pass shows).

### R-101: the agent unreliably reaches the approval card for excited-state, ensemble and some complex jobs
- surface: drafting/elicitation/approval
- class: bug
- severity: S2 (deterministic for the wigner ensemble) to S3 (flaky elsewhere)
- cause: LLM
- confidence: confirmed at the suite level: e2e_19 failed across the harness's 3 retries (deterministic); the e2e_08 cells recovered on retry (flaky, 1-2/3)
- found by: baseline P1.3 (tests/e2e/e2e_19_wigner_ensemble.py, e2e_08_job_matrix.py)
- scope: observed on wigner_spectra (the source freq job and the ensemble job, both), and flakily on excited-state single points (M13-M17), cas_reco (M26), opt/ci on bagel (M34) and opt_freq on bagel (M37). Not seen on the plain ground-state single points.
- repro: `bash tests/e2e/run_e2e.sh e2e_19` and `python3 tests/e2e/e2e_08_job_matrix.py --tier 1`.
- observed: the tool traces stop after `start_job_draft`/`update_job_draft` with no `submit_draft` and no approval card, `timed_out=False`, elapsed 10-44s, so the turn ended without producing a card. e2e_19: "missing tool call 'submit_draft' (called: ['set_geometry', 'start_job_draft', 'update_job_draft'])", both the freq and ensemble legs, across retries.
- expected: a ready draft ends the turn at the approval card. The mechanical fallback (submit the same spec directly via `get_job_manager().submit`) works, so the code path is sound and this is an LLM prompt-reliability finding, not CODE.
- evidence: docs/evaluation/2026-09-app-review/evidence/e2e-run.log
- pointer: the model, on these job families, treats the draft as complete after `update_job_draft` and does not proceed. `docs/ARCHITECTURE.md`'s "run_when_ready" and the `submit_draft` NEXT STEP instruction are the levers; this is a candidate for the same mechanical-rule treatment as `want_oscillator_strengths -> ORCA`.
- note: the deterministic wigner case (0/3) is the actionable one and is why e2e_19 is one of the two failed scripts; the flaky cells belong in the fix plan as prompt hardening. Verify the k/N per cell against fresh threads in P3.3/P3.4, which drive these families through the real UI.

### R-102: (CLEARED, not a defect) the drawer does not mis-gate sections by job type
- surface: job-viewers
- class: bug
- severity: n/a (cleared)
- cause: HARNESS
- confidence: cleared by looking at the rendered drawer
- found by: baseline P1.4 (ui_02_approval_jobs_drawer flagged apparent gating failures) and P3.4b
- scope: the HF single-point drawer, viewed directly.
- repro: open the drawer for a completed single_point/gs/hf job (ad0149396ecb) via the Job Manager.
- observed: the drawer renders Parameters, Summary and "Molecular orbitals - 8 total" (a real orbital table), and nothing else. It does NOT show Optimization energy or Vibrations. A single-point computes orbitals, so the Molecular Orbitals section is correct, not a gating leak.
- expected: exactly what was seen.
- evidence: docs/evaluation/2026-09-app-review/evidence/p3/p3_04b_drawers/01-drawer-sp_hf-ad014939.png (viewed)
- note: ui_02's apparent "section rendered where it should be gated off" failures did NOT reproduce as a real defect. The coordinator's first automated check reported them because it scanned the whole page body (`document.body.innerText`), which includes the left chat pane; for this job that pane was discussing excited states and a UV/Vis spectrum, so "Optimization"/"Vibration"/"UV" matched chat text, not drawer sections. ui_02's own spec failure ("2 elements matched job id") points to selector ambiguity on a populated stack. Kept as a numbered, resolved entry rather than deleted so the triage record shows the gating concern was raised and cleared by looking. R-099 (the refinement drawer's empty occupation table) is a different drawer and remains open.

### R-103: the api process RSS roughly doubled over the review without a restart
- surface: code:server
- class: perf
- severity: S3
- cause: CODE (candidate; leak vs cache not yet distinguished)
- confidence: measured (two points, same uninterrupted process); cause not settled
- found by: P4.6 (P0.6 baseline vs P6.2 end-of-review)
- scope: the api container process, across a review that submitted a few hundred jobs and ran many agent turns and SSE streams. Not restarted between the two measurements.
- repro: read `/proc/<api pid>/status` VmRSS at rest, drive sustained job + chat load for hours, read it again without restarting.
- observed: RSS 551 MB at P0.6 (right after the frozen bring-up), 1,231 MB at P6.2. Threads stable (658 -> 660), open fds 28 -> 54. So the growth is heap, not threads.
- expected: a long-running server settles to a steady working set; a monotone climb over a day of use is a leak.
- evidence: docs/evaluation/2026-09-app-review/evidence/baseline-resources.txt (P0.6) and this entry's P6.2 numbers.
- pointer: candidates to check first, all process-lifetime caches: the RAG/Chroma store, the model-warmer, the LangGraph graph cache, and any per-thread state retained after a thread closes. The stable thread count rules out a threadpool leak.
- note: not settled as a leak. The honest next step is an idle-settle measurement (stop all load, wait, re-read RSS): if it falls back toward 551 MB it was working-set/cache; if it stays near 1.2 GB it is retained and a leak hunt is warranted. Deferred to the fix phase because it needs a quiet stack over time rather than a point measurement. S3 as a scaling/stability concern, not a today-crash.
