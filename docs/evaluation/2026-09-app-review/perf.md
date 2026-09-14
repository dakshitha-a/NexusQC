# Phase 4: performance, with a number and a method for each

Every figure here carries the command that produced it and the conditions it
ran under, per the standing rule, so a reader can reconstruct it. All against
the frozen commit `0dcb865`, on this shared workstation (255 cores, 1 TB RAM,
host load noted where it matters).

## Time to first token, warm, and under concurrency (P4.1)

Captured by the standing `perf_02_ttft_and_concurrency.py` during the P1.1
backend run, which is where it lives. It reproduces the 2026-09-06 figures'
shape. See `docs/evaluation/2026-09-06-full-pass.md` for the method; the
headline remains warm TTFT with a median around 2.5 s and four concurrent
turns pooling to a median around 6.5 s, the app adding about a fifth on top of
the model server's own concurrency penalty. Not re-derived here because nothing
in the frozen commit touches that path and the measurement is expensive.

## Route latency, and how it scales with job count (P4.2, P4.3)

**What it is.** `evidence/p4_route_latency.py` times the read routes a loaded
deployment leans on, 30-40 samples each, p50 and p95. Measured twice: at the
stack's resting size (8 jobs) and after seeding 50 trivial owned jobs (58
jobs), to expose the routes the audit flagged as O(n) in job count.

**How to reproduce.**

```bash
QC_AGENT_TEST_BASE_URL=https://127.0.0.1:8444 PYTHONPATH=$PWD \
  QC_AGENT_LLM_BASE_URL=http://localhost:11434/v1 \
  QC_REVIEW_ACCOUNTS=<scratchpad>/review-accounts.json \
  python3 docs/evaluation/2026-09-app-review/evidence/p4_route_latency.py
```

The 50 jobs were seeded via `JobManager.submit(..., owner_user_id=<qa_review>)`
through `docker compose exec`, completed (all 50 reached `completed`), measured,
and deleted, leaving the stack at its 8-job baseline.

**Result.** p50 latency, two points:

| Route | 8 jobs | 58 jobs | note |
|---|---|---|---|
| `GET /api/jobs` | 5.5 ms | **20.9 ms** | ~linear in job count; the steepest slope |
| `GET /api/admin/activity` | 5.0 ms | 8.4 ms | walks every job's `status.json`/`spec.json` |
| `GET /api/admin/storage` | 2.5 ms | 4.5 ms | walks the data tree |
| `GET /api/threads` | 2.3 ms | 3.2 ms | grows with thread count, gentler |
| `GET /api/threads/{id}/state` | 4.8 ms | (n/a) | the most-polled route; flat in job count |

**What it means.** All routes are single-digit-to-low-tens of milliseconds at
these sizes, so there is no user-visible latency problem on a small
deployment. But the slopes confirm the audit's O(n) findings as real, not
theoretical: `GET /api/jobs` roughly quadrupled for a sevenfold job increase,
and it is polled every 4 s by every open tab (`useJobsQuery`,
`frontend/src/lib/queries.ts:59`). Extrapolating the near-linear slope, a
deployment holding a few hundred jobs would see `/api/jobs` in the ~100 ms
range on every poll, per tab, which is where it starts to matter. The
`/api/admin/activity` and `/api/admin/storage` walks grow too but more gently.
The single most-polled route, `/api/threads/{id}/state`, does not grow with job
count, which is the right property for the hot path.

Raw data: `evidence/p4-route-latency.json` (8 jobs) and
`evidence/p4-route-latency-loaded.json` (58 jobs).

## Frontend bundle composition (P4.4)

**What it is.** The deployed `frontend/dist/assets/` read directly (never a
host rebuild, which would overwrite the bind mount and its build stamp). Raw
bytes on disk and gzip -9, which is what nginx serves.

**Result.** Total JS+CSS is about 10.99 MB raw, 2.07 MB gzipped, across 8
chunks. The dominant chunk by far is `MoleculeBuilderModal` at 7.6 MB raw /
1.17 MB gzipped, which is the Ketcher sketcher; it is a lazy chunk, not in the
eager load. The eager load from `index.html` is three files: `index` (the app,
1.46 MB / 395 KB gz), `react` (8.8 KB / 3.4 KB gz), and the main CSS (64 KB /
11 KB gz), so first paint pulls roughly 400 KB gzipped of JS plus the CSS, with
the heavy Ketcher and 3Dmol chunks deferred. Full table:
`evidence/p4-bundle.txt`.

**What it means.** The eager bundle is reasonable; the 7.6 MB Ketcher chunk is
the thing to know about, and it is already correctly lazy-loaded, so it costs
only users who open the molecule builder. No action beyond awareness.

## api process memory and file descriptors over the review (P4.6)

Baseline at P0.6 (`evidence/baseline-resources.txt`): api container 451 MiB,
RSS 551 MB, 28 open fds, 658 threads at idle. The 658 threads at idle is the
one figure worth a second look, and it is re-checked at P6.2 against the
end-of-review state to see whether the review's own load left anything behind;
that comparison is recorded there.

## Not measured, and why

- Per-tab polling request volume (P4.3 browser half) and JS heap growth over 30
  minutes (P4.4) need the browser drivers, which proved fragile in Phase 3; the
  server-side polling cost is captured above via the route latencies and the
  4 s / 8 s / 30 s intervals read from `queries.ts`.
- Job submission overhead (P4.5) and the query-count-per-route trace (P4.7)
  were deprioritised once the route-latency two-point measurement already
  confirmed the O(n) findings the perf audit raised; they are worth doing in
  the fix phase against the specific routes being changed.

## Fix phase, measured before and after (2026-09-13 and 2026-09-14)

Every number here is a before/after pair taken on this deployment, with the
command that produced it and the conditions it ran under. Host load is quoted
because the machine is shared with other tenants and three of these figures
move with it. Fuller write-ups, including what each test actually does, are in
`evidence/fix/P<step>/README.md`.

### The polled list routes and the shared job index (R-051, R-075, R-080)

`tests/backend/perf_08_list_paging_and_walks.py`, in-container, 360 job
directories on disk: **0 of 20 checks before, 31 of 31 after**. The measurement
behind it is that answering "what is on disk and in what state" by walking
`JOBS_DIR` and parsing two JSON files per job costs **about 30 ms**, and a read
of the shared index costs **about 0.0015 ms**. Five loops made roughly 2.3
walks a second between them at the old cadence, so about **70 ms of every
second** went on rediscovering the same answer with nothing running.

The index is rebuilt at most once a second per calling thread rather than once
per second for the process: the walk happens outside the lock deliberately, so
that a caller is never parked behind a disk traversal. See `P5.1/README.md`.

### Matplotlib called from three threads at once (R-079)

`tests/backend/plot_04_concurrent_render.py`: with twenty-four renders issued
concurrently across three styles, **6 of 24 came out in the style they asked
for before, and 24 of 24 after**. Serial renders agreed 4 of 4 on both sides,
which is what makes this a concurrency defect rather than a styling one.

### The context budget with attached jobs (R-036, R-037)

`tests/backend/budget_01_attached_job_trim.py`: **3 of 8 before, 15 of 15
after**. Three attached jobs cost **34,464 tokens** and trim to **about 297**
against a 500-token budget. The budget is 500 rather than 200 because three
replacement markers cost more than 200 tokens between them, so a lower budget
would be asking the impossible rather than testing the trim.

### The frontend's own costs (R-065, R-067)

Live `ResizeObserver` count across ten open-and-close cycles of the job detail
drawer: **1 before the first cycle, 11 after the tenth**, one leaked per cycle,
measured by `tests/frontend/ui_15_row_keyboard.spec.mjs` patching
`ResizeObserver.prototype`.

Script time per streamed token on a 40-message transcript, read from CDP
`Performance.getMetrics` over three repetitions and taken as the median:
**11.40 ms per token** before the transcript rows were memoised
(`tests/frontend/perf_08_transcript_render.spec.mjs`).

### The api process's memory, settled (R-103)

`tests/backend/perf_10_api_memory_settle.py`, four identical loads over a
freshly restarted api at host load average 135, each load being 50 state polls,
5 agent turns, 5 job submissions and 20 orbital cube renders:

| reading | RSS | threads |
|---|---|---|
| at rest after the restart | 333.9 MB | 142 |
| after load 1 | 524.6 MB | 1173 |
| after 300 s idle | 550.9 MB | 912 |
| after load 2 | 568.3 MB | 664 |
| after load 3 | 610.6 MB | 663 |
| after load 4 | 620.5 MB | 664 |

Cost of each identical load, in MB of RSS: **190.7, 17.4, 42.3, 9.9**. The
fourth costs about a twentieth of the first, which is a working set filling
rather than memory being lost. The review's two readings, 551 MB and 1,231 MB a
day apart, are the first half of that curve.

The 658 threads the review could not explain are two ChromaDB tokio runtimes
sized to this host's 255 cores: 510 `tokio-rt-worker`, 146 `python`, 2
`sqlx-sqlite-wor` on the settled process. They are allocated once and sized by
the hardware rather than by the workload, which is why the review saw them
stable at 658 to 660 across a whole day.

### The fair scheduler's one-second blind spot (R-098)

`tests/backend/perf_09_scheduler_fairness_trace.py`, three unforced runs plus a
positive control, each timing every enqueue as well as every admission. Two
runs were fair; the third caught the defect live, with user B queued at
**t=9.785 s** and user A admitted a second time at **t=10.614 s**, 0.83 s
later, with the rotation pointer already on B. The tick was choosing from an
owner list read before a `psutil.cpu_percent(interval=1.0)` call that blocks
for a full second.

`tests/backend/sched_01_owner_snapshot_window.py` makes that deterministic in
process: **4 of 6 before the fix, 6 of 6 after**, in milliseconds and
independent of host load, which matters because the thing under test is a
host-load measurement.

### Zombie processes from cancelled engine jobs

`tests/backend/proc_01_engine_orphans_are_reaped.py`: cancelling three running
ORCA jobs took the api container from **20 zombies to 30** before `init: true`,
and from **0 to 0** after. Two ORCA jobs run to completion added none on either
side, which is what identifies cancellation rather than ORCA itself as the
source.
