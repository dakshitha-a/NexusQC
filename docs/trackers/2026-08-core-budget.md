# Tracker: holding every job to its core budget

**Complete as of 2026-08-30. Six steps across three phases, all done.** The
`merged:` row on each phase records the commit it landed as.

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
[`trackers/2026-08-multireference-on-pyscf.md`](trackers/2026-08-multireference-on-pyscf.md)
-- 31 steps across 11 phases, closed 2026-08-29.

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

The request was to make sure an ORCA job really uses the `%pal` core count, a
PySCF job really uses its thread count, and that BAGEL's own parallelism is
working, because ORCA and PySCF felt slower than jobs that were genuinely
parallel while BAGEL felt fine.

That intuition was right, and the cause was the opposite of what the symptom
suggests. Nothing was running on too few cores. Everything except BAGEL was
running on too many: `N_CORES` was a number the scheduler debited and no engine
obeyed. The mechanism is the same in all three places and worth stating once,
because it is the reason a code read cannot settle any of this. libgomp, MKL,
OpenBLAS and BAGEL's task scheduler each read their thread-count variable
exactly once, when the shared library loads, and default to every core on the
machine when it is unset. A cap therefore has to be in the environment a
process is *created* with; set from inside a running process it is not a
weaker cap, it is no cap at all.

The user then asked, mid-plan, that the work be checked against the global host
admission gate and the per-user concurrency quotas. Phase 3 is that check.

## Phase 1: Find out what each engine was actually doing

- [done] P1.1: Measure the real thread count of a PySCF job
  evidence: docker compose exec api python3 -c "import app.chemistry.jobs.pyscf_runner; from pyscf import lib; print(lib.num_threads())" → "255, against N_CORES=4. The cap was an os.environ.setdefault('OMP_NUM_THREADS') placed after `from pyscf import ...`, so it was both too late (libgomp had already read the variable) and a setdefault (this host's shell profile sets OMP_NUM_THREADS=8, so a bare-metal run lost to it as well)"
- [done] P1.2: Establish what the oversubscription costs
  evidence: a direct PySCF benzene/6-31G* HF run at both thread counts inside the container → "1.17 s at 255 threads against 0.55 s at 4, i.e. the uncapped job is 2.1x SLOWER. For ORCA, benzene/def2-TZVP HF on 4 MPI ranks: 39.6 s wall / 30.7 s SCF with OMP_NUM_THREADS unset against 26.1 s / 17.2 s at one thread per rank"
- [done] P1.3: Confirm ORCA's MPI parallelism itself is healthy, so the fix targets the real fault
  evidence: a direct ORCA benzene/def2-TZVP HF run at nprocs 1 and 4 → "95.3 s SCF on one rank against 17.2 s on four, so MPI scaling is fine. On a small job (benzene/6-31G*) one rank finishes in 7.4 s against 16.6 s on four, which is MPI startup cost, not a defect"
- [done] P1.4: Find BAGEL's actual threading interface
  evidence: strings on BAGEL 1.2.2's own libbagel.so → "'Set BAGEL_NUM_THREADS for the number of threads used', with OMP_NUM_THREADS as the fallback. There is no -nt flag anywhere in the binary or the library. This host's shell profile sets BAGEL_NUM_THREADS=8, which was silently outranking the OMP_NUM_THREADS=4 the runner exported"

- merged: 4e5c0b8


## Phase 2: One place that decides, applied everywhere a job runs

- [done] P2.1: A single per-engine definition of the thread budget
  evidence: app/config.py → "engine_thread_env(engine) returns OMP/MKL/OPENBLAS/NUMEXPR_NUM_THREADS, plus BAGEL_NUM_THREADS for BAGEL. ORCA gets 1 rather than N_CORES because its width is N_CORES MPI ranks; N_CORES threads per rank would be N_CORES**2 threads for a job admitted as N_CORES wide"
- [done] P2.2: Applied to every worker, and again by the two engines that spawn their own subprocess
  evidence: scripts/spikes/spike_thread_caps.py → "3/3 engines within budget. PySCF worker created with all four variables at 4, peak 10 threads in its process group; ORCA at 1, 4 MPI ranks reported by ORCA itself, '%pal nprocs 4 end' in the input; BAGEL at 4 with BAGEL_NUM_THREADS, and bagel.out printing 'using 4 threads per process'"
- [done] P2.3: Clamp the ORCA inputs this app did not build
  evidence: a direct call of _cap_parallelism on eight inputs → "all three spellings clamped ('%pal nprocs 64 end', an nprocs line inside a multi-line %pal block, '! PAL16'); an input with no parallelism directive at all gains '%pal nprocs 4 end' rather than running on one core; an input asking for 2 keeps 2; and 'PAL16' inside a %moinp filename is left alone"

- merged: 4e5c0b8


## Phase 3: The admission gate and the quotas

- [done] P3.1: Confirm the caps read nothing this plan changed
  evidence: app/chemistry/jobs/base.py and scheduler.py → "_resources_available measures with psutil (host CPU/memory percent and a per-core idle count) and _concurrent_jobs_block_reason counts running jobs against the admin-configurable total and per-user caps. Neither reads a thread variable, so neither changes. What does change is that the scheduler's `idle_budget -= N_CORES` per admission is now true: a PySCF job used to cost ~255 cores against a 4-core debit"
- [done] P3.2: Cap the one engine path that runs outside the gate entirely
  evidence: docker compose exec api python3 -c "import server.routes.jobs; from pyscf import lib; print(lib.num_threads())" → "4, previously 255. The lazy orbital-cube route renders cubes with PySCF inside the API process on a request thread, where no spawn-time environment applies and no admission gate does either, so it could drive the idle-core count under N_CORES and hold every queued job at pending. molden.py now calls lib.num_threads(N_CORES) at import; orca_plot gets the same environment as ORCA itself"
- [done] P3.3: Both lazy-cube paths still render
  evidence: a direct call of orca_runner.render_orbital_cube and molden.cube_for_orbital on completed water/6-31G jobs → "input.mo2a.cube at 7,258,004 bytes from orca_plot under OMP_NUM_THREADS=1, and 6,746,023 bytes from the molden path under the in-process cap"

- merged: 4e5c0b8

