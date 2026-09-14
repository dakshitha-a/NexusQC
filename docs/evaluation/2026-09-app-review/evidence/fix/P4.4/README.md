# P4.4, the two suite anomalies on ORCA under load

Two results were carried out of the review as observations rather than
findings, because the review could not tell contention from a defect and its
own discipline was to re-run in isolation before labelling either:

- `e2e_13_stability` reported 4 of 10, with every failure downstream of its
  ORCA CASSCF probe reaching `failed`, on a host at load average 12 to 13.
- `e2e_08`'s M23 cell, a NEB transition-state search on ORCA, died with
  `RuntimeError: ORCA exited with code 2`.

Both were re-run alone on a stack nobody else was using, at load average 10 to
11, which is the same neighbourhood the review ran in. Both reproduced exactly.
So neither was contention. Both turned out to be defects in the probes rather
than in the app, and one of them exposed a real gap in how the app reports an
engine failure, which is fixed here.

## M23: the two endpoints were the same molecule

`m23-run1.log` is the isolated re-run: 4 of 5, failing on the same cell with the
same message, and `m23-output-tail-before.txt` is the end of ORCA's own output
from that job. ORCA says what happened in one line, and the app never showed
it:

```
No barrier was found. Skipping NEB-TS run here.
```

The probe set the start geometry to ammonia and the end point to
`m23-product-before.xyz`, which puts the nitrogen at the origin and all three
hydrogens at z = -0.290. That is the nitrogen on the same side of the H3 plane
as the start geometry has it, so the two endpoints are the same pyramid written
twice. ORCA's endpoint pre-optimisation duly relaxed both to the same minimum,
recorded in `m23-output-tail-before.txt` as -55.45541978 Eh at both ends, and a
NEB with no barrier between its endpoints has nothing to find.

The fix in the probe is one sign. Inverting z on the three hydrogens puts the
nitrogen below their plane, which is the umbrella flipped over, and the path
between the two runs through the planar D3h transition state that ammonia
inversion is the textbook example of. `m23-run2-corrected-endpoint.log` is that
run: **6 of 6**, the job completes, and the summary carries `neb_converged`,
`ts_converged`, `ts_energy_hartree` and a `path_summary`, with six downloadable
artifacts.

### What the app got wrong, and what changed in it

The user-facing failure was `RuntimeError: ORCA exited with code 2` followed by
three thousand characters of output whose tail happened to be four identical
rows of a convergence table reading `-55.45542  0.00  0.00000  0.00000`. Every
part of that is true and none of it is usable. ORCA had already said, in
English, that it found no barrier.

`app/chemistry/jobs/orca_runner.py` now runs the output through
`_orca_failure_reason` before raising, and both of the module's run wrappers
share one `_orca_exit_error`. Where a signature is recognised the message leads
with the explanation and what to do about it, and still carries the exit code
and the raw tail underneath, because a recognised reason is a summary and not a
replacement for the evidence. Exactly one signature is recognised today, the
one verified against the real failing run kept here, per this repository's
standing rule that ORCA parsers are derived from runs rather than from the
manual.

## e2e_13: the probe was built with no task

`e2e_13-run1.log` is the isolated re-run: **4 of 10**, identical to the review's,
on a host at load 11. Every probe job reached `failed` immediately, with an
empty pending reason and a message of `done`.

Submitting the same spec by hand gives the answer in one line, from the job's
own `result.json`:

```
No runner is wired up for / yet.
```

The probe was `JobSpec(method="casscf", engine="orca", molecule=m, params=CAS)`,
with no `task` and no `subtype`. That is the pre-v2 JobSpec shape, and
`CLAUDE.md`'s testing section warns about it by name. A spec with an empty task
is accepted by `submit()`, is queued, is admitted, and dies at dispatch. So no
ORCA process ever started in any of the four sub-tests.

Six of the ten checks are about what happens to a job that is genuinely
running, so all six failed, and they failed in the shape of a resource problem:
a job that never runs is indistinguishable from a job the host would not admit.
That is why this read as an under-load anomaly for as long as it did.

`e2e_13-run2-corrected-probe.log`, with the task and subtype supplied: **7 of
10**. S3 and S4, cancellation and orphan reconciliation, pass completely.

### The three that were still failing, and why they were also the harness

The remaining three were the probe being too fast for the way the test looked
at it. An ORCA CASSCF(4,4)/STO-3G on water takes about **7 seconds** here,
timed directly on 2026-09-13 (a CAS(6,6)/cc-pVDZ state-averaged over five
states takes 8.4 s, so there is no slower probe of this shape to reach for).

- **S1a** submitted the second job three seconds after the first, then polled
  once a second until it saw something, and only afterwards read both jobs'
  statuses. By then the first had finished, so the check reported
  `j1=completed j2=running` no matter what the cap had done. It now records the
  transient at the instant it occurs, polls four times a second, and prints the
  whole timeline.
- **S1b** depended on the same read.
- **S2** required user B's job to be `running` exactly, six seconds after
  submitting it. A job that sailed straight through the cap and completed in
  seven seconds was therefore scored the same as one the cap had held. What a
  blocked job looks like is `pending`, and that is what the check refuses now.

`e2e_13-run3-transient-captured.log` is the result: **10 of 10**, and the
timeline it prints is the per-user cap doing its job, second by second:

```
[7.53, 'running',   'pending', 'queued']
[8.03, 'running',   'pending', 'waiting for a free job slot (you have 1/1 running)']
[8.28, 'completed', 'pending', 'waiting for a free job slot (you have 1/1 running)']
[9.28, 'completed', 'running', 'running casscf via orca']
```

The second job is held while the first runs, told exactly why in the words the
finding asked for, and admitted one second after the slot frees.

## Classification

Both are **HARNESS**, and the review was right to refuse to label them from a
suite run. One of them, M23, also produced a genuine improvement to the app:
an engine failure whose reason ORCA had already printed is no longer reported
as an exit code and a table.
