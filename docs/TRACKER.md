# Tracker: clearing the backlog

**Complete as of 2026-09-01. Five steps across three phases, all done.**
The `merged:` row on each phase records the commit it landed as.

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
[`trackers/2026-09-sharing-jobs-and-projects.md`](trackers/2026-09-sharing-jobs-and-projects.md)
-- 18 steps across 6 phases, closed 2026-09-01.

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

`docs/BACKLOG.md` had three open items and the instruction was to address all
of them. One is a straightforward gap with a decision attached, one turned out
to be misdiagnosed, and one is mostly not a code problem at all but names a
real follow-up.

**Deleting a user left their projects behind.** `purge_user_data` removed the
account's jobs, KB entries, uploads, threads and plots but never touched
`data/projects.json`. Because `ownership_index.owner_user_id` is
`ON DELETE CASCADE`, the ownership rows went with the user while the project
rows survived, and an unowned project is deliberately visible to everyone. So
deleting an account converted its private archives into deployment-wide public
ones. The entry left open whether the member jobs should go too; the user
settled it directly: "deleting a user should delete all their projects and
data."

**The scan double-dispatch entry was wrong about its own cause.** It claimed a
3-point `pes_1d` scan dispatches five sub-jobs as a defect in
`scan_orchestrator.py`'s top-up loop. Re-run in a single process with its own
orchestrator, exactly the shape `server/main.py` produces, a 3-point scan
dispatches exactly three. The duplication only appeared because the original
reproduction submitted the scan from a separate one-shot process while the
running server's orchestrator was also polling, and `dispatch_lock` is a
`threading.Lock`, which coordinates nothing across processes. The observed
`[0, 1, 1, 2, 2]` is the exact signature of that race. Production has one
uvicorn worker and is unaffected, but the codebase's own test convention
submits jobs out of process and this cost real compute and real quota there,
so the claim is made true rather than merely explained away. Deliberately not
justified by "a second uvicorn worker would make it a production bug": a
second worker is not a supported configuration at all, since JobManager's
thread pool is sized once at process start, and this guard does not make one
safe.

**The concurrency entry is not a code problem.** Its own text already
establishes that the dominant term is the model server's KV-cache-per-slot
behaviour and that the lever is the context length, the card or a different
inference server, none of which live here. What it does name as actionable is
that the baseline fires a synthetic filler prompt while the app path carries a
66k-character tool schema, so the ratio conflates app overhead with prompt
size. That is fixable and is what this plan does.

## Phase 1: An account deletion takes its projects with it

- [done] P1.1: purge_user_data sweeps projects and their jobs
  evidence: tests/backend/purge_01_user_projects.py -> "9/9. The check that would have caught the original bug is 'the deletion left NO ownerless project behind', read in-container against all_owners('project') rather than through a route, because an admin's GET /api/projects shows owned and unowned alike without distinguishing them, which is exactly why this was invisible. Member jobs need no special handling: they are the user's own jobs, so the owner-filtered pass already deletes them, filed or not. A bystander account's project and job are asserted untouched, since a purge that scoped too widely is worse than the bug"
- [done] P1.2: No ownerless project is left anywhere on this deployment
  evidence: tests/backend/purge_01_user_projects.py -> "The orphan count is snapshotted before the deletion and compared after, so the check is 'this deletion created none' rather than 'there happen to be none'. Reads 0 ownerless of 1 project on the stack. The two ownerless 'qatest shared study' rows an earlier share_03 run had left behind were removed when found, and share_03 now deletes its own projects so the suite cannot recreate them"

- merged: c34d9c6

## Phase 2: Scan dispatch is correct regardless of process count

- [done] P2.1: A cross-process guard on a master's dispatch
  evidence: tests/backend/scan_01_no_double_dispatch.py -> "4/4, three consecutive runs, reproducing the exact out-of-process case that used to give [0, 1, 1, 2, 2]: indices [0, 1, 2] and a manifest of exactly three lines. base.master_dispatch_guard takes an flock on the master's own children.jsonl, held beside the existing threading.Lock, and is applied to all three orchestrators rather than only the scan, since ensemble and batch carry the identical process-local guard. The assertion is on the MANIFEST because sub_job_ids_of deduplicates by job id and the children route groups by _scan_index, which is why the duplication was invisible in the UI"
- [done] P2.2: The backlog entry says what is actually true
  evidence: docs/BACKLOG.md -> "The entry claimed a defect in scan_orchestrator.py's top-up loop. Re-run in a single process with its own orchestrator, the shape server/main.py actually produces since uvicorn.run takes no workers argument, a 3-point scan dispatches exactly three. The duplication only appeared because the original reproduction submitted from a second process while the server polled, and dispatch_lock is a threading.Lock. Entry removed rather than reworded, since the claim it made is now false and the fix is real"

- merged: c34d9c6

## Phase 3: A baseline the app path can be compared against

- [done] P3.1: The two workloads carry comparable prompts
  evidence: tests/backend/perf_02_ttft_and_concurrency.py -> "The baseline now sends app.agent.prompts.SYSTEM_PROMPT and the real convert_to_openai_tool(get_all_tools()) schema, read from the same source graph.py binds, instead of a synthetic filler string. Smoke-tested against the live model server: a 34,904-character payload returns a first token in 1.93s. Derived rather than hardcoded on purpose -- the old comment asserted a 66k-character schema and the real figure is 34.7k, which is what a number written into a comment does. The reader now counts a tool_call delta as a first token as well as content, since offering the tools means the model may answer with one"

- merged: c34d9c6
