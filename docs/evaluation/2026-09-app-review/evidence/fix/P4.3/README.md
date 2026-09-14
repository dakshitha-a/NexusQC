# P4.3, R-103: the api process's memory, a leak or a warm cache

R-103 recorded two readings of the api container's `VmRSS`, taken from one
uninterrupted process: 551 MB right after the frozen bring-up and 1,231 MB at
the end of a review day that submitted a few hundred jobs and ran many agent
turns. Threads moved 658 to 660 and open descriptors 28 to 54, so the growth
was heap. The entry did not call it a leak, and was right not to: two points on
a rising line cannot tell a leak from a working set that filled once.

The experiment is `tests/backend/perf_10_api_memory_settle.py`. It is opt-in
rather than part of `run_backend.sh`, because it restarts the api to start from
a known floor and takes most of an hour, neither of which belongs inside a
suite.

## The load, so the numbers can be reproduced

One pass of the load is, against the running deployment on this host:

- 50 reads of `GET /api/threads/{id}/state`, the request every open tab makes
  every few seconds
- 5 real agent turns, each on its own fresh thread, each a full pass through
  the graph, the tool bindings and the LLM, driven to completion by polling the
  transcript rather than by the 202 the post returns
- 5 job submissions through `JobManager.submit`, cancelled two seconds later,
  so the scheduler, the watcher and the job index all see traffic without
  paying for the calculations
- 20 orbital cube renders off one completed PySCF HF/STO-3G single point on
  water, cycling through its seven orbitals; a cube is rendered lazily per
  request and never cached, which makes this the heaviest per-request
  allocation the app makes on a read path

`VmRSS`, thread count and open descriptor count are read from
`/proc/1/status` and `/proc/1/fd` inside the container, which is the same
measurement the review took.

## Why the experiment grew from two loads to four

The register asked for one load, an idle settle, and a repeat. That was run
first and is kept in `perf_10-two-loads.log` rather than discarded, because it
is the reason the experiment changed shape. With ten turns per load it gave a
first rise of 179.8 MB and a second of 61.1 MB, against a leak threshold fixed
before the run at a third of the first rise, which came to 59.3 MB. The second
rise cleared that threshold by 1.8 MB and the script duly printed LEAK.

A verdict that turns on 1.8 MB is not a verdict. Two points cannot separate a
warm-up that is still decaying from a genuine leak that is simply smaller than
the first load's one-off costs, and those two have very different consequences
for a deployment meant to run for weeks. Only the shape of a series tells them
apart: a leak gives roughly equal rises, a filling working set gives shrinking
ones. So the load was made smaller, five turns instead of ten, and run four
times.

## The result

`perf_10-run.log`, on a host at load average 135 with the stack otherwise idle:

| reading | RSS | threads | open fds |
|---|---|---|---|
| R0, at rest after the restart | 333.9 MB | 142 | 15 |
| after load 1 | 524.6 MB | 1173 | 32 |
| after 300 s idle | 550.9 MB | 912 | 30 |
| after load 2 | 568.3 MB | 664 | 32 |
| after load 3 | 610.6 MB | 663 | 32 |
| after load 4 | 620.5 MB | 664 | 31 |

The cost of each identical load, in MB of RSS: **190.7, 17.4, 42.3, 9.9**.

The fourth load costs about a twentieth of the first. That is not what a leak
looks like. The first pass through this app touches a great deal of code and
data for the first time: the graph and its tool bindings, the Chroma store and
its embedding client, matplotlib's font cache, the PySCF import chain and the
cube machinery. All of it is process-lifetime and none of it is paid for
again. The variation between the later loads, 17.4 then 42.3 then 9.9, is the
kind of scatter a shared machine produces: load 3 took 638 s where load 4 took
171 s, on a host with other tenants on it.

So the review's two points were the first half of exactly this curve, taken at
551 MB and 1,231 MB rather than 334 MB and 620 MB because that process had also
served a full review's worth of distinct work. **R-103 is a warm cache, not a
leak**, and there is nothing to fix.

The threshold that decides this, the last load's rise being under a third of
the first, was fixed before the four-load run and is in the script's own
constants. It is met by a wide margin: 9.9 MB against 62.9 MB.

## Two things the experiment turned up that the finding did not name

**RSS rises during an idle period**, by 26.3 MB over five minutes here. That
is not an allocator quirk. Nothing is arriving over HTTP, but the job watcher,
the scheduler and the quota pass all keep working, so an "idle" api process is
not an idle Python process. The script reports that line as a signed change
rather than as an amount returned, because the first version of it was labelled
"returned unprompted" and would have described a process whose memory grew as
one that had given memory back.

**The thread count is dominated by a Rust runtime sized from the host's core
count.** `thread-breakdown.txt` is `/proc/1/task/*/comm` grouped by name on the
settled process: 510 `tokio-rt-worker`, 146 `python`, 2 `sqlx-sqlite-wor`. The
tokio and sqlx threads are ChromaDB's Rust core, and 510 is exactly twice the
255 CPUs the container sees, so it is two tokio runtimes each sized to the
machine. That is where the review's unexplained 658 threads came from, and why
they were stable at 658 to 660 across its day: they are allocated once and
sized by the hardware, not by the workload. The peak of 1173 during the first
load, settling back to 664, is the transient python threads on top.

Nothing here is a defect: the threads are idle, they cost stack address space
rather than resident memory, and the count is stable load on load, which the
script now checks. It is recorded because 658 threads on a process nobody
thought was doing anything is the sort of number that gets misread as a leak
later, and because it would look very different on a four-core deployment.
