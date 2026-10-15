# Raw run output behind the method document

Two archives hold the terminal output of the runs that produced the numbers in
[`../CAS_ENGINE_METHOD.md`](../CAS_ENGINE_METHOD.md), as they came out.
`evidence-2026-10-14.tar.gz` carries the current sweep of the six benchmark
sets and the QUESTDB run. `evidence-2026-09-06.tar.gz` carries the targeted
studies of 4 to 6 September that the document still cites, described in the
second half of this file. Neither is edited, apart from one substitution in
the October archive: absolute paths on the machine that ran it are replaced by
`<repo>`, `<conda>` and `<scratch>`, because a tracked file must not describe a
particular host.

## `evidence-2026-10-14.tar.gz`

| path | what it is |
|---|---|
| `sweep/six-sets.log` | the six `run_bench.py` sets at commit `c5a8fbc`, in the order excited, nevpt2, refine, spaces, narrowed, stability, 4 h 4 m |
| `sweep/cost-attribution.log` | `cost_attribution.py` at the same commit, the SCF / stability / selection split of section 3.10 |
| `hole-capture/all-states.log` | `hole_capture.py` at the same commit, re-measuring the captures of sections 3.5 and 3.6 |
| `questdb/results.jsonl` | every final and intermediate result line of the QUESTDB run, 542 excitations by three modes, which `quest_report.py` reads |
| `questdb/runner.log` | the detached runner's log: each launch, attempt, wall-cap kill and completion, with host load at launch |
| `questdb/config.json` | the run's modes, worker count, threads per worker, start time and starting commit |
| `questdb/king_m.json` | the M diagnostic of every excitation from King's own wave functions, as written by `quest_mdiag.py` |

The QUESTDB ledger, `questdb.md`, is regenerated from `questdb/results.jsonl`
by `quest_report.py --write`, given the manifest that `quest_fetch.py` builds
from King's Zenodo record. The run's inputs are not archived here: they are
King's and QUESTDB's, under CC-BY 4.0 and ODbL, and `quest_fetch.py` downloads
and checksums them.

## `evidence-2026-09-06.tar.gz`

The `.md` ledgers beside this file are the processed form of the same runs and
are what the document cites. This archive is the layer underneath: what to read
when a figure looks wrong, or when someone wants to see a molecule the ledger
summarises away.

**There are no job directories in here, and that is not an omission.**
`scripts/casbench/run_bench.py` calls PySCF in process and never goes through
the JobManager, so the benchmark creates no jobs in a deployment. Nothing about
these measurements is recoverable from `data/jobs`, which is why the raw output
is archived here instead.

### What is in it

| path | what it is |
|---|---|
| `sweep/all-six-sets.log` | the closing `--set all` run: spaces, stability, excited, nevpt2, refine, narrowed, in that order, 6 h 11 m, per-molecule lines for every one |
| `sweep/all-six-sets.json` | the same run's machine-readable results, one record per molecule per set |
| `sweep/spaces-regression-check.log` | `--set spaces` on its own, run to confirm the rotation repair moved no recommended space before the long sweep was spent |
| `rotation/after-direction-fix.log` | the 30-molecule rotation sweep after the perpendicular pair was seeded from the molecule: 0 of 30 change |
| `rotation/after-sign-fix.log` | the same sweep after the in-plane sign was fixed as well, confirming the second repair moved nothing |
| `hole-capture/all-nine-states.log` | hole capture for every n->pi\* state in the benchmark, def2-SVPD, three states requested |
| `hole-capture/both-signs.log` | the same nine states at each in-plane sign in turn, which is what shows the four symmetric carbonyls give identical capture either way and the five asymmetric ones prefer the outward choice |
| `hole-capture/uracil-four-sign-combinations.log` | uracil has two carbonyls and therefore four sign combinations; this enumerates them, and the mixed one reproduces the 0.759 and 0.819 an earlier study recorded |
| `hole-capture/formamide-four-repeats.log` | four consecutive runs of one molecule, which is what established that 0.802 was reproducible rather than scatter before the difference from 0.806 was chased |
| `latency/ttft-and-concurrency.log` | warm time to first token and four concurrent turns, the measurement that closed the last backlog entry |

## Reproducing rather than reading

Every file here is output; the inputs are all in the repository.

```bash
# the whole sweep, about six hours
python3 -u scripts/casbench/run_bench.py --set all --out results.json

# the rotation half on its own, minutes rather than an hour
PYTHONPATH=$PWD python3 -u scripts/casbench/rotation_invariance.py

# hole capture for every n->pi* state
PYTHONPATH=$PWD python3 scripts/casbench/hole_capture.py

# where a recommendation's time actually goes, which is section 3.10's table
PYTHONPATH=$PWD python3 scripts/casbench/cost_attribution.py

# warm TTFT and four-at-once, needs the stack and a quiet GPU
PYTHONPATH=$PWD QC_AGENT_TEST_BASE_URL=https://127.0.0.1:8444 \
  python3 tests/backend/perf_02_ttft_and_concurrency.py
```

Two of those will not reproduce their recorded numbers exactly, and the reason
is in the measurements themselves rather than in the setup. Twisted ethylene's
SCF converges to either of two solutions about 31 mHa apart, so whether a run
finds an instability to follow depends on where its initial guess lands; and
the latency figures depend on what else is using the card. Everything else in
the archive is deterministic.
