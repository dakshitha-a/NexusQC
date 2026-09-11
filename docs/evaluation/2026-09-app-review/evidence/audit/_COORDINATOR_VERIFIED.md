# Coordinator's own verification, 2026-09-11

Checks run by the main session against the working tree at `ca7e0ff`, on
claims raised by the audit agents. Read-only; no exploit was executed and no
file was written outside this scratchpad. These upgrade the confidence field
but are still short of a live reproduction, which P5 owns.

## CONFIRMED by code read: KB write paths do not sanitise the filename

`server/routes/kb.py`

- `add_text_source` (line ~190): `filename = body.filename or _synthesize_filename(body.text)`
  then `(_upload_dir(owner) / filename).write_text(body.text)`. `body.filename`
  is a plain `str | None` on the Pydantic model with no validator. Nothing
  between the request and the write touches it.
- `add_source` (line ~150): `dest = _upload_dir(owner) / file.filename` after
  checking only `Path(file.filename).suffix.lower()` against
  `ALLOWED_FILE_EXTENSIONS`. A name like `../../../x/result.json.txt` passes
  the suffix check.
- `_upload_dir` does `UPLOADS_DIR / owner` and `mkdir(parents=True)`. No
  containment check.

**The asymmetry is the finding.** The READ path already defends against
exactly this and says so: line 101 comments "Path(source).name strips any
directory components a malicious/odd..." and line 105-112 does
`Path(source).name` plus `resolved.parent == d.resolve()`. So the class was
known, the defence was written, and it was applied to one direction only.

Path arithmetic verified in isolation:
`Path("/app/data/kb/uploads/user-123") / "../../../../jobs/victimjob/result.json"`
resolves to `/app/jobs/victimjob/result.json`. `write_text` follows it.

Impact for THIS app specifically: the reachable set includes another user's
`result.json`, which is a fabricated scientific result rather than a generic
file write. That is what makes it S1 on this severity scale rather than S2.

## CONFIRMED by code read: two cross-user reads in chat.py

Both audit agents raised this independently, which is corroboration.

- `post_message` (`server/routes/chat.py:631`) calls `_require_thread` and
  resolves `owner_user_id`, then passes `body.job_ids` straight into
  `_run_turn`. No `check_owner_or_admin("job", ...)` anywhere on the path.
- `troubleshoot_job` (`server/routes/chat.py:654`) checks the thread and
  never the `job_id` in its own path.
- The sibling `tag_job_frame` (`:264`) does it correctly:
  `check_owner_or_admin("job", body.job_id, current_user_or_none(request))`
  on the line after `_require_thread`. `plot_ids` on the same request is
  owner-scoped too.

So the control exists in the same file and is missing on two paths.

## CONFIRMED, but the frequency claim was WRONG: blocking DB call on the loop

`app/auth/middleware.py`. `AccessControlMiddleware.dispatch` is `async def`
(line 86) and calls `_maintenance_mode()` (line 126), which calls
`models.get_app_config` -> `get_pool().connection()` -> a synchronous psycopg
query. That is a blocking DB round-trip on the event loop, and the app's own
stated rule exists to prevent exactly this.

**The server audit said this runs on every request. It does not.**
`_maintenance_mode` is TTL-cached: `_MAINT_TTL_SECONDS = 2.0` (line 54), so
the query runs at most once per two seconds, and only the unlucky request that
finds the cache cold pays for it.

That changes the severity. Steady state it is a few tens of blocking
round-trips per minute against a local Postgres, which is small. The S1 tail
is a slow or unreachable database: there is no `connect_timeout`, the pool
timeout is 30 s, and a stall there freezes the whole event loop and every
open SSE stream with it, which is precisely the failure the plain-`def` rule
was written for. File as S2 with the tail risk stated, and let P5 decide by
measuring it.

## CONFIRMED by code read: unscoped KB search from the literature step

`app/agent/active_space_lit.py:203` builds its default kb callable as
`search_knowledge_base.func(q, doc_type="paper", k=5, state=None)`.

`app/rag/query_tool.py:39-51` reads the owner as `(state or {}).get("owner_user_id")`
and, when it is absent, falls through to an unfiltered search. Its own comment
says that is intended for the single-user case only, and spells out the harm
in the multi-user case: "any user's chat could trigger a search that surfaces
another user's private upload verbatim into the model's context." Passing
`state=None` unconditionally makes the multi-user case take the single-user
branch. `doc_type="paper"` is the more sensitive category, which the same
comment also notes.

## ESCALATED: the KB filename write reaches the host deploy runner

Raised by the auth agent, verified link by link by the coordinator. This is
the most serious finding of the review so far and it changes the severity of
the KB filename issue from "overwrite a result file" to "privilege escalation
to a host-side deployment action".

**The chain, each link checked:**

1. `AddTextSource.filename` is a bare `str | None` with no validator
   (`server/routes/kb.py`), and `add_text_source` does
   `(_upload_dir(owner) / filename).write_text(body.text)`.
2. `pathlib` join with an ABSOLUTE string discards the left operand. No `../`
   is needed. Verified:
   `Path('/app/data/kb/uploads/user-123') / '/app/data/deploy/request.json'`
   -> `/app/data/deploy/request.json`.
3. The bind mount is confirmed on this deployment:
   `/data/qcuser/9.NexusQC/NexusQC-dev-repo/data -> /app/data`. A write
   inside the api container lands where the host runner looks.
4. `scripts/deploy_runner.sh` line 51-52 watches `data/deploy/request.json`,
   line 230-233 polls it every 3 seconds under `--watch`, lines 125-128 read
   `action`, `ref`, `drain` and `force` out of it with `json.load`, line 138
   allows `report|update|rollback`, and lines 198-216 execute
   `bash scripts/update.sh ... "$target_sha"` or `--rollback` on the HOST.
5. **`requested_by` is never read.** Nothing in the runner checks who wrote
   the file. The API route that normally creates it is admin-gated; the file
   itself is the only authority.
6. The write happens BEFORE `ingest_text`, so even a request that then 400s
   has already left the file on disk.

**What an attacker needs:** any authenticated account, of any role.
Registration is invite-only, so not an anonymous internet attacker, but on a
shared lab deployment every ordinary user has one. Then a single
`POST /api/kb/sources/text` with `filename` set to the absolute path and
`text` set to `{"action": "rollback"}`.

**Live or not, on this host:** NOT live right now. `deploy_runner.sh --watch`
is not running (checked with `ps`; only the grep's own command lines matched).
The chain completes on any deployment where the admin has enabled the in-app
update feature, which is a documented feature in the README and the whole
point of `docs/ARCHITECTURE.md`'s "Updating from inside the app" section.

**Severity: S1.** Two independent controls would each break it: sanitising the
filename (`Path(x).name`, which the read path in the same module already
does), or having the runner verify the request came from an admin rather than
trusting the file.

## CONFIRMED: a master's child jobs are owned by nobody, for access purposes

Raised by the auth agent. Child jobs get no `ownership_index` row, so
`check_owner_or_admin` passes for every user, on read AND on `PATCH` rename,
`POST /cancel` and `DELETE`. Leaving children out of the index is deliberate
and documented, but the reason given is about eviction candidates, not about
access. `_queue_owner` (`app/chemistry/jobs/base.py:735-762`) already knows
how to resolve a child's effective owner through `parent_job_id`; the access
check simply does not use it. Deletion cascades correctly, so this is not a
repeat of SEC-08.

## CONFIRMED BY EXECUTION: asking for L-PDFT silently runs plain DFT

Raised by the jobs agent, confirmed by the coordinator by RUNNING the
function rather than reading it. This is the most consequential finding of
the review for someone using the app to do chemistry, and it is the one class
this severity scale puts at the very top: a wrong level of theory presented
as the one that was asked for.

Reproduce, in process, no stack needed:

```bash
PYTHONPATH=$PWD python3 -c "
from app.chemistry.jobs.param_normalize import normalize_method
print(normalize_method('lpdft'))"
```

Observed:

```
('dft', "Interpreted method 'lpdft' as 'dft' (restricted/unrestricted
 reference is chosen automatically from the molecule's spin, not from this
 parameter).")
```

Also collapses: `l-pdft` -> `dft`, `pdft` -> `dft`, `tddft` -> `dft`,
`hfx` -> `hf`. Correctly preserved: `mcpdft`, `cmspdft`, `casscf`, `caspt2`,
`nevpt2`, `ccsd`, `mp2`, `eom_ccsd`, `hf`, `dft`.

**Mechanism.** `app/chemistry/jobs/param_normalize.py:72` calls
`difflib.get_close_matches(key, _METHOD_ALIASES.keys(), n=1, cutoff=0.75)`.
`SequenceMatcher(None, 'lpdft', 'dft').ratio()` is **exactly 0.75**, so it
meets the cutoff on the boundary. `tddft` vs `dft` is also exactly 0.75. The
repair path runs on input that was never a typo: `lpdft` is a real method
with its own row in `app/chemistry/registry2/capabilities.py` (confirmed
present), it simply is not a key in `_METHOD_ALIASES`, and the call site has
no "is this already a valid method?" short-circuit before reaching for the
fuzzy matcher.

**Why it is worse than a wrong answer.** The note attached to the
substitution is the wrong note. It is the text written for the `rdft`/`udft`
spelling variants, explaining that the restricted/unrestricted reference is
chosen automatically. So a chemist who asks for L-PDFT is told something
true-sounding, about a different subject, which makes a silent change of
method look like a deliberate and harmless normalisation. Nothing anywhere
says "L-PDFT was not run".

**Scope.** L-PDFT is documented in `docs/QM_CAPABILITIES.md` as the preferred
multi-state MC-PDFT variant, the one to reach for over plain MC-PDFT because
it restores the correct topology near same-symmetry crossings. So the
substitution hits the recommended method and silently replaces a
multireference treatment with a single-reference one. Its two siblings
survive, which is what would make this hard to notice: `mcpdft` and
`cmspdft` behave, only `lpdft` collapses.

**Contradicts a stated contract.** `param_normalize`'s own module
documentation says repair is narrow and is never a guess at different
chemistry. `docs/ARCHITECTURE.md` has a "Parameter repair is narrow and
verified" section making the same promise.

Severity S1. Not fixed: the user chose to hold every finding to triage.

## CONFIRMED: child jobs inherit "unowned" by accident, not by decision

This one needs care, because at first glance it looks like the settled
decision on the not-a-finding list ("jobs with no recorded owner are visible
to every user, deliberately"). It is not that decision. It is a different
thing wearing its clothes, and the difference is what makes it a finding.

**The mechanics, verified.**

- `JobManager.submit` (`app/chemistry/jobs/base.py:1198`) records ownership
  only under `if owner_user_id:`. A master's children are submitted with
  `owner_user_id=None`, which the code says itself in the comment at line
  ~1235: "calls (owner_user_id=None, parent_job_id set)". So no child of any
  batch, scan, interpolation or ensemble master ever gets an
  `ownership_index` row.
- `check_owner_or_admin` (`app/auth/access.py`) reads
  `if owner is not None and owner != str(user["id"]): raise 404`. An absent
  owner falls straight through, so the check **passes for every user**. That
  covers read, `PATCH` rename, `POST /cancel` and `DELETE`.

**Why the settled decision does not cover this.** That decision, and the
docstring that implements it, are about jobs "created before auth was
configured on this deployment", described in the docstring as
"legacy/unowned". Children are created now, on a fully authenticated
deployment, by a parent that has a perfectly good owner. They are not legacy
and nobody decided they should be public.

**The machinery already exists.** The very same `submit` resolves a child's
effective owner one line later for fair scheduling:
`self._scheduler.enqueue(spec.job_id, owner_user_id or _queue_owner(spec.job_id, spec.to_dict()))`,
and `_queue_owner` (lines 735-762) walks `parent_job_id` to find it. The
scheduler knows who a child belongs to. The access check does not ask.

So on a multi-user deployment every child of every master is world-readable
and world-writable, and the fix is to give the access check the same
`parent_job_id` walk the scheduler already uses. Severity S1, class security.
Reported by the auth agent, mechanics verified here.

## THEME: a path-safety control applied to one of two sibling paths, three times

Three separate findings turn out to be the same mistake, and the report
should say so rather than listing them as unrelated bugs. In each case the
author identified the hazard, wrote a defence, left a comment about it, and
applied it to one of two places that needed it. That is a much more useful
thing to tell a maintainer than three independent "sanitise this" items,
because the fix is a habit rather than three patches.

**1. Knowledge base, read defended and write not.**
`server/routes/kb.py:101` comments "Path(source).name strips any directory
components a malicious/odd..." and line 105-112 does `Path(source).name` plus
a `resolved.parent == d.resolve()` containment check. The two write paths in
the same module, `add_source` (~150) and `add_text_source` (~190), do
neither.

**2. Orbital cube route, `gbw` validated and `spin` not.**
`server/routes/jobs.py:700` takes both `spin` and `gbw` from the query
string. `gbw` is allowlist-checked against `_GBW_NAME_RE` before use, and the
docstring is explicit about why: "Strictly allowlist-validated against
_GBW_NAME_RE before ever touching the filesystem, since it's client-supplied
and otherwise builds a path directly." `spin` is the other client-supplied
component of the very same key and is validated nowhere. Line 744 builds
`cube_key = f"idx{index}" + (f"_{spin}" if spin else "") + ...` and line 763
builds `cube_path = job_dir / f"mo_{cube_key}.cube"`.

**3. The same route again, download name defended and filesystem path not.**
The comment at 745-747 says the download name is "slugified for one reason
the others aren't: cube_key can carry the client-supplied `gbw` filename". So
the author saw that `cube_key` carries client input and hardened the
**cosmetic** surface, the filename the browser shows, while the real
filesystem path built from the same unslugified `cube_key` two lines later
was left as it was.

Note that path *parameters* cannot carry a slash (uvicorn unquotes, then
Starlette matches `[^/]+`), which is why `upload_id` and `plot_id` joins are
safe and why the exposure here is specifically through **query** parameters
and **request bodies**. That distinction is what makes this a pattern rather
than a general absence of care.

## CONFIRMED: the URL ingest route fetches before it knows who is calling

`server/routes/kb.py:224` is `def add_url_source(body, request)` with no auth
dependency. `server/main.py:109` includes the router with no `dependencies=`
list, and `AccessControlMiddleware` does CORS/Origin and maintenance mode
only, no authentication. Inside the handler, `robots_disallows(body.url)` and
then `fetch_page(body.url)` both run BEFORE `owner = _owner_key(request)`.

So the server makes two outbound requests to a caller-chosen URL before it
establishes any identity. No host restriction and redirects are followed, so
this reaches cloud metadata endpoints and anything else on the host network.

**One honest qualification.** The Origin check in the middleware rejects a
request with no `Origin` header, so a bare `curl` gets 403 before reaching
this. An attacker who sets `Origin` to the deployment's own origin gets
through. That lowers it from "trivially reachable by anyone who can route to
the host" but does not make it authenticated, and the ordering inside the
handler is wrong regardless: the fetch should be after the identity check,
not before.

## CONFIRMED: /deploy-status/runner.json leaks the host path, unauthenticated

`nginx/nginx.conf:98-109` aliases the whole `data/deploy` directory to
`/deploy-status/` with no auth, `autoindex off`, and a comment that states the
security model plainly: "Nothing here should be browsable: the ids are the
only thing keeping one run's log out of a casual reader's way."

That model holds for the per-run subdirectories, whose names are generated
ids. It does not hold for the two files that sit at the top of the directory
under **fixed** names, which need no guessing:

- `runner.json` (`scripts/deploy_runner.sh:53`), written by
  `touch_runner_state` as
  `{"alive_at": ..., "pid": ..., "repo": "$REPO_ROOT"}`. On this host
  `REPO_ROOT` is `/data/qcuser/9.NexusQC/NexusQC-dev-repo`, so an
  unauthenticated GET returns the operator's username and the absolute
  filesystem layout of the host.
- `request.json` (line 52), the pending deploy action.

The host path is exactly the class of string `scripts/check_public_safe.sh`
exists to keep out of published files. Here it is served at runtime to anyone
who can reach the deployment, which no scan can catch because it is generated
rather than committed.

Raise from the deploy agent's S4 to **S3**: unauthenticated information
disclosure revealing a username and host layout. Also worth noting for the
fix plan that `request.json`'s fixed, documented name is what makes the KB
arbitrary-write escalation aimable; a per-run or unguessable name would not
fix that bug but would remove the convenient target.

## UPGRADED to confirmed on live data: the unowned children are real, and there are eight

Taking the Phase 0 snapshot surfaced a live instance of the child-ownership
finding, so it is no longer only a code read.

`GET /api/jobs` as admin returns 8 jobs; `data/jobs/` holds 17 directories.
The gap is fully accounted for and is not itself a defect: 8 of the 9 extras
are children of one master, `186fe458ec9e`, each a completed
`single_point/ee`, and the 9th is the `_seen` bookkeeping directory. Masters
are what the list route returns.

Queried against the live database (`ownership_index`, columns
`kind, resource_id, owner_user_id, created_at`):

```
master   186fe458ec9e  ->  owner c3038f42-d37c-4be7-8eb0-c37a5ad3db05
children (all 8)       ->  no rows returned at all
```

36 job ownership rows exist in total against 16 real job directories, so the
index is not simply empty; it is specifically the children that are absent.

Consequence on this deployment as it stands: eight completed excited-state
jobs that belong to a named user can be read, renamed, cancelled and deleted
by any other authenticated user, because `check_owner_or_admin` passes when
`get_owner` returns None.

Confidence is now "confirmed on live data". The remaining step, an actual
cross-user HTTP request proving the read succeeds, is cheap once the two
review accounts exist and belongs in P3.9's isolation sweep.
