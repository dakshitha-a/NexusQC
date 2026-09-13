# P5.1: the polled paths, and paging the list routes

`tests/backend/perf_08_list_paging_and_walks.py`, before and after, in this
directory. Before: 0 of 20 checks pass (the code has none of it). After: 31 of
31.

## R-080, opt-in paging on six list routes

`GET /api/jobs`, `GET /api/threads`, `GET /api/kb/sources`, `GET /api/uploads`,
`GET /api/plots` and the message list inside `GET /api/threads/{id}/state` all
returned a whole collection with no ceiling. `/api/jobs` is the one that
matters, because every open tab polls it every four seconds and it walks a
directory that only grows: the review measured 5.5 ms median at 8 jobs and
20.9 ms at 58, roughly linear, so about 100 ms per poll at a few hundred jobs.

`server/routes/_paging.py` is the one implementation. **Paging is opt-in and
that is the design decision, not an oversight.** This project's testing rests
on a two-sided cleanup diff, and the snapshot tooling, every script in
`tests/backend` and the e2e suite all read the full list. A truncating default
would not have failed any of them; it would have made all of them quietly
incomplete, which is worse. So no `limit` means the same plain array as before,
byte for byte, and only a caller that asks for a page gets one, as
`{"rows": [...], "total": n, "offset": k, "limit": l}`.

The conversation window is a trailing one rather than an offset page: a
conversation is read from its end, and windowing from the front would return
the opening exchange and hide the answer that just arrived.

The Job Manager panel opts in at 200 rows, and drops the limit the moment a
search or a status/engine filter is active, because its fuzzy match runs
client-side over whatever it was given and a search covering only the most
recent page would be quietly wrong. The panel says which of the two it is
showing.

## R-051 and R-075, one shared index instead of five walks

Five loops answered "what is on disk and what state is it in" by walking
`JOBS_DIR` and parsing two JSON files per job: the scan, ensemble and batch
orchestrators every three seconds, the job watcher every two, and
`_running_job_ids()` once per queued owner per dispatch tick. `GET
/api/admin/activity` did the same walk on every poll of the admin console,
uncached, next to a sibling route that had been given a cache for exactly this
reason.

`app/chemistry/jobs/base.py` now holds one `job_index()` of
`{job_id: (task, parent_job_id, status)}` with a one-second TTL, dropped
outright by `write_status` so a change made in this process is visible at once.
One second is shorter than the fastest consumer's tick, so no consumer ever
acts on an index older than its own poll interval, and the staleness that
admits is the staleness these callers already document as acceptable ("soft,
eventually-consistent" caps).

Measured on the dev stack with 360 job directories on disk: the walk costs
about 30 ms, a cached read about 0.0015 ms. At the old cadence those five
loops made roughly 2.3 walks a second between them, so about 70 ms of every
second was spent rediscovering the same answer on a stack with nothing
running.

One thing the code deliberately does not promise, so that nobody reads a
stronger claim into the number above: the rebuild itself runs outside the
lock. `job_index()` takes `_job_index_lock` to read the cache and takes it
again to store the result, but the 30 ms walk in between is unlocked, so two
threads that both find the cache expired in the same instant will both walk.
The alternative, holding the lock across the walk, would park every other
caller behind a disk traversal, which is exactly the stall this change exists
to remove, and a duplicated walk is harmless because the build is idempotent
and the last writer simply wins. So the guarantee is "at most one walk per
second per thread that asks", not "one walk per second for the whole
process". With five consumers on staggered two and three second ticks that is
still an order of magnitude fewer walks than before.

## R-039, the watcher stops re-reading settled jobs

`JobWatcher._poll_once` called `mgr.status(job_id)` for every id in every
conversation's `active_job_ids` on every two-second tick. A job that has
reached a terminal state and is already recorded in `seen` can never change
and can never produce another notice, and `active_job_ids` only grows: its
reducer is append-only. So a conversation from months ago went on costing a
filesystem read per job per tick for the life of the process. `_last_status`
was already there, caching the status for event deduplication; it now also
skips the read. Both conditions are required (terminal AND already seen), so a
job that finished while nobody was looking still gets its one notice.

## R-040, quota enforcement off the watcher thread

`enforce_all_quotas()` ran inline on the watcher's own thread every 150 ticks.
Its thread-eviction branch calls `delete_thread_checkpoints`, which takes that
thread's graph lock, and a running turn holds that lock for its whole ReAct
loop, documented at 53 to 77 seconds. While the watcher was blocked there,
`_poll_once` was not running for anybody: every conversation on the deployment
stopped receiving job updates for the length of one unrelated turn. It runs on
its own thread now, one pass at a time, skipping a tick rather than queueing
threads.

## R-043 and R-075, one quota sweep per wave

`enforce_quota()` walks every non-terminal job's directory with `rglob`, and
wave dispatch called `submit()` once per child, so a forty-child wave ran forty
full sweeps back to back, each `rglob`-ing up to twenty live engine scratch
directories. A sub-job no longer runs the sweep; each orchestrator runs it once
when the wave is placed, outside the dispatch lock. Nothing is unbounded by
that: the master ran the sweep on the way in, and the next wave catches an
ensemble filling up mid-flight.

## R-081, the NEB live path reads a trailing window

`GET /api/jobs/{id}/neb_frames_live` read and split the whole trajectory file
on every poll to keep the last `n_images + 2` frames, and the file grows by one
full path's worth of frames every NEB iteration, so the cost of a poll grew
linearly while the poll rate stayed constant. It seeks to a window sized from
the spec's own atom count and realigns to the first frame boundary, which gives
the same answer at constant cost. `_tail_lines`, thirty lines up in the same
module, was already doing this for `/log`.

## R-075, the scheduler stops rewriting identical messages

While the host has no headroom the dispatch tick rewrote `status.json` for
every queued job of every owner about once a second, almost always saying
exactly what the last one said. It compares against the last message written
per job now. The message carries live CPU and memory figures so it does change
as those move; what is gone is the identical rewrite, which is most of them.
