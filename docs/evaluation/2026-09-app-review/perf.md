# Phase 4: performance, with a number and a method for each

Every figure here carries the command that produced it and the conditions it
ran under, per the standing rule, so a reader can reconstruct it. All against
the frozen commit `ca7e0ff`, on this shared workstation (255 cores, 1 TB RAM,
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
