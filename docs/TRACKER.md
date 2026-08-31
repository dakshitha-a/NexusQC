# Tracker: bundling jobs into named project archives

**In motion as of 2026-08-30.** The `merged:` row on each phase records the
commit it landed as, and is `-` until the phase is done.

It stays here rather than moving to [`trackers/`](trackers/) until the next
plan starts, which is when it gets archived and a fresh tracker takes its
place. **Exactly one tracker is active at a time.**

## How tracking works here

Development is linear, so there is never a reason to have two trackers open at
once. Each plan, feature or non-trivial request gets its own tracker, this file
is whichever one is currently in motion, and when its plan is finished the file
is closed out and moved to [`trackers/`](trackers/), then a fresh one starts
here for whatever comes next.

Closed trackers are kept, never deleted. They are the audit trail for why the
code looks the way it does, and code comments cite them by path. The one this
replaces is
[`trackers/2026-08-core-budget.md`](trackers/2026-08-core-budget.md)
-- 6 steps across 3 phases, closed 2026-08-30.

## Rules (enforced by `scripts/check_tracker.py`)

- Step status is exactly one of `todo` | `in-progress` | `done`.
- A step may be marked `done` **only with an evidence field**: the
  verification script/command path plus a one-line observed result.
- The tracker edit ships **in the same commit** as the step's final code
  change, so `git log --follow docs/TRACKER.md` is the audit trail.
- A phase's `merged` row records the commit hash the stage landed as.

Format for a step row:

```
- [status] P<phase>.<step>: <short name>
  evidence: <script/command> → "<observed result>"   (required when done)
```

---

## Why this plan exists

The job manager is a single flat list of every job a user has ever run. There is
no way to group a set of related calculations and no way to get them off the
list once they are finished with. A study that took thirty jobs to complete
leaves thirty rows sitting above the next study's, forever.

The request was for an archive: bundle jobs under a project name, put the
archive in the left rail, and be able to move jobs back and forth between the
archive and the job manager, with rename, delete and download-as-zip on the
project.

Three things were settled with the user before any code was written. Deleting a
project asks every time whether the jobs go with it, with neither option
preselected, and a separate cascading "delete all my projects" lives in the
per-user danger zone. An archived job is hidden from the job manager, with a
"Show archived" toggle that brings it back into view carrying a project badge. A
job belongs to at most one project, so filing it into a second one moves it.

The request suggested repurposing "the existing tagging system" to select jobs.
There is no tagging system. A grep across `app/`, `server/`, `frontend/src` and
the on-disk `meta.json` finds no tags field, no tag table and no tag routes; the
three things named "tag" here are `tagJobFrame` (a geometry frame attached to a
draft), the job `label` string, and the ephemeral `attachedJobsStore`. What the
request was pointing at is the checkbox multi-select and selection bar in
`frontend/src/jobs/JobManagerPanel.tsx`, which today drives exactly one action.
That selection machinery is what gets repurposed, and it needs no new model.

The rule the whole feature rests on: **archiving is a membership label and job
files never move.** Quota accounting walks job directories, the conversation
registry filters on `spec.json` existing, and the drawer, cube, artifact and
download routes all read `JOBS_DIR / job_id`. A move would corrupt all of it.

## Phase 1: The registry, the ownership migration and the routes

- [done] P1.1: A project registry that never touches the graph lock
  evidence: tests/backend/proj_01_registry.py → "29/29. Filing a job into a second project moves it rather than copying it, and does so in ONE file write: a counting wrapper around _atomic_write_text sees a single call, and asserts on the bytes of that call that the job is held by exactly one project. The remove-then-add spelling would be two writes with a window where it belongs to neither"
- [done] P1.2: Widen the ownership index to admit a project
  evidence: app/auth/db.py → "'project' added in both places it has to be: the CREATE TABLE body for a fresh install, and a DROP/ADD CONSTRAINT pair in the appended-migration region for an already-deployed database, where editing the table body is a silent no-op. The running stack accepted a project ownership row after a rebuild"
- [done] P1.3: The route module, kept out of the lock-free jobs router
  evidence: tests/backend/proj_02_lifecycle.py → "32/32 against the running stack. Nine routes in a new server/routes/projects.py rather than additions to jobs.py, every handler a plain def. purge-mine is declared before the parameterised routes so it is not swallowed as a project id"
- [done] P1.4: Deleting a job prunes it from its project
  evidence: tests/backend/proj_01_registry.py → "prune_job drops the id from the project holding it and leaves every other project alone; delete_job_dir calls it beside the existing conversation-registry prune. A job whose directory is gone is also filtered on every read, so an eviction that bypasses delete_job_dir cannot leave a project claiming a job no download could produce"

- merged: -


## Phase 2: The streaming zip and the manifest

- [done] P2.1: A zip that streams rather than buffering the project into memory
  evidence: tests/backend/proj_04_zip_streams.py → "10/10. Downloading a project holding a 200 MB incompressible artifact grew the api container's total RSS by 1 MB, against a 63 MB threshold. No new dependency: zipfile already emits data descriptors when its output object answers False to seekable(), so app/projects/zipstream.py is a sink plus a generator that drains it inside the per-file read loop"
- [done] P2.2: A manifest that makes an archive readable a year later
  evidence: tests/backend/proj_04_zip_streams.py → "The zip carries {slug}_manifest.csv at its root naming each job by the label the user gave it, plus engine, method, calculation, status, date, size and headline summary. The zip itself is named 20260831_qatest_big_3366be_archive.zip, and members keep the engine's own filenames so an unpacked ORCA job still has input.inp"

- merged: -


## Phase 3: The job manager learns about projects

- [done] P3.1: An archived job leaves the job list, and a toggle brings it back
  evidence: tests/backend/proj_02_lifecycle.py → "GET /api/jobs omits an archived job by default and returns it under include_archived=true, each row then carrying project_id/project_name, and an unarchived row carrying both as null rather than omitting them. job_project_map() is one small flat-file read taking no lock, so jobs.py's lock-free contract is intact"
- [done] P3.2: The test fixtures still find every job they created
  evidence: tests/fixtures.py → "list_job_ids passes include_archived=true. Without it, cleanup_jobs cannot see a job a script archived, so the script would silently leave qatest_ clutter behind. Inert for the scripts that archive nothing: tax_02_job_rows, jobs_01_status_semantics, perf_06_lockfree_reads, sec_06_ownership_sweep and dz_01_self_purge all still pass"
- [done] P3.3: The selection bar files jobs into a project
  evidence: tests/frontend/proj_01_archive_roundtrip.spec.mjs → "The checkbox multi-select that only ever drove Attach to prompt now also opens an Add to project popover, listing existing projects and offering a new one. Attach to prompt is still beside it rather than replaced. Filing two selected jobs removes both rows from the list and leaves the third; typing the project's name into the job search pulls its jobs back up"

- merged: -


## Phase 4: The archive panel in the left rail

- [done] P4.1: A Projects section beside Conversations, Knowledge base and Files
  evidence: tests/frontend/proj_03_render_and_rail.spec.mjs → "36/36. The section renders empty and populated, collapses and expands with a correct aria-expanded, and its rows stay inside the rail at both 220px and 520px with no horizontal page scroll: a project name long enough to overflow the rail four times truncates instead. No PanelErrorBoundary fallback appears at any point, and no console or page errors after login"
- [done] P4.2: A project opens to its jobs, and they can be sent back
  evidence: tests/frontend/proj_01_archive_roundtrip.spec.mjs → "40/40. The flyout lists exactly the member jobs; returning one puts it back in the job manager unarchived and drops the project to '1 job'. Show archived returns archived rows to the list carrying a project badge with a one-click return, and a rename reaches both the rail row and every badge"

- merged: -


## Phase 5: Delete semantics, the danger zone and quota ordering

- [done] P5.1: Deleting a project asks, with neither answer preselected
  evidence: tests/frontend/proj_02_delete_and_download.spec.mjs → "The dialog names the project and its job count, renders both options, and arms the destructive one only on the project's exact name. The spec caught a real defect here: Radix focuses the first focusable child on open, so 'Delete the project only' was focused and Enter would have taken it, which is a default answer by another name. onOpenAutoFocus now sends focus to the dialog itself. Delete-project-only leaves the job on disk and back in the job manager; delete-both removes it"
- [done] P5.2: Delete all my projects, scoped to the caller even for an admin
  evidence: tests/backend/proj_03_ownership.py and proj_02_lifecycle.py → "15/15 and 32/32. Every project route answers 404 rather than 403 to another user, so the id cannot be probed, and a job cannot be filed away by someone who cannot see it. purge-mine scopes off models.list_owned rather than the list route: the test first proves an admin's list DOES show other users' projects, then that the admin running purge-mine leaves them untouched"
- [done] P5.3: Quota eviction exhausts unarchived jobs first
  evidence: tests/backend/proj_05_eviction_order.py → "10/10. _evict_oldest_first sorts on (archived, created_at), so an archived job that is the OLDEST of the set is the last thing evicted rather than the first. Deliberately an ordering and not an exemption: with nothing unarchived left, the archive is still evicted, because a category nothing can reclaim would let a user fill their quota and then submit nothing"

- merged: -


## Phase 6: The whole workflow in a browser, and the docs

- [done] P6.1: The archive round trip, driven end to end
  evidence: tests/frontend/proj_01_archive_roundtrip.spec.mjs → "40/40 in headless chromium. One continuous session: register, seed three jobs, file two, watch them leave, find them under Show archived, open the project, send one back, move one between projects, rename, search. Console and page errors are collected throughout and an empty collection is itself a check"
- [done] P6.2: Delete and download, both destructive paths and the zip
  evidence: tests/frontend/proj_02_delete_and_download.spec.mjs → "27/27. The download is captured through page.waitForEvent('download') and the saved file read back: it is a real zip named 20260831_qatest_keep_these_6c066c_archive.zip carrying a manifest and the job's own files. The account danger zone's delete-all-projects is exercised end to end and reports 'Deleted 1 project and 1 job'"
- [done] P6.3: Every new component renders, at both rail widths and when collapsed
  evidence: tests/frontend/proj_03_render_and_rail.spec.mjs → "36/36. Collapsing the rail and RELOADING (leftRailCollapsed is persisted, so this is the state a returning user lands in) still shows a Projects icon in the collapsed strip, and a Files icon, which was missing entirely before this work. One branch is reported as a NOTE rather than a PASS: the job manager's empty state could not be reached, because unowned jobs are visible to every user so a fresh account never sees an empty list"
- [done] P6.4: The docs say why archiving is a label rather than a move
  evidence: docs/ARCHITECTURE.md → "A Project archives section covering the six decisions worth not relitigating: files never move and why that is load-bearing, membership on the project rather than in each meta.json, the single atomic write that enforces one-project-per-job, why the zip streams when the two older ones do not, why an archive is ordered last for eviction rather than exempted, and why deleting asks. README.md and CHANGELOG.md carry the user-facing version; docs/BACKLOG.md carries two incidental findings"

- merged: -
