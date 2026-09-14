# Resolution of the 2026-09 application review

The review closed on 2026-09-13 with 102 open findings recorded against commit
`ca7e0ff`: 8 S1, 25 S2, 54 S3 and 15 S4. It was deliberately record-only, so
none of them had been acted on. This document is what happened to each.

The decision that shaped the phase was to attempt **all 102**, not the 38 the
review had confirmed. An unconfirmed finding had to be reproduced with a
failing test before it could be fixed, and one that could not be reproduced
after an honest attempt closes as `not reproduced` with what was tried rather
than as a quiet pass.

Everything below is generated from `findings.md` by
`evidence/summarize_resolution.py`, so the counts and the ids behind them can
be re-derived rather than trusted.

## What changed, for someone who uses the app

**Nobody can read anybody else's work by accident any more.** Four of the eight
S1 findings were one shape: a route that took a job id, a project id or a
search and did not ask whose it was. A scan's child jobs carried no owner at
all, so they were visible to everyone; the two chat routes that accept a job id
did not check ownership where their sibling did; the literature search read
every user's papers rather than the caller's. All four now resolve ownership
before they do anything else, and a job with no parent and no owner is still
deliberately visible to everyone, which is a separate and settled rule.

**A calculation you asked for is the calculation that runs.** Asking for L-PDFT
ran plain DFT, because a canonical method name was being normalised into
something else on its way to the spec. A multi-state gradient asked for the
ground state ran on the wrong surface, because state 0 is a real state and the
code was treating it as a falsy value. An ORCA open-shell excited-state job
reported every oscillator strength as absent, because the row pattern assumed a
singlet. Ten capability cells were offered, drafted, approved and then killed
at input building; most of them are built now, because the engines could always
do them and only this app could not.

**The approval card appears when it should.** The agent used to reach a ready
draft and then simply stop, with no card and no question, on ensemble and
excited-state requests: measured at 0 of 3 for one family and 1 to 2 of 3 for
four others. A complete draft raises its own card now rather than depending on
the model to make one more tool call, and the same measurement across the same
five families is **15 of 15**. Nothing about the gate changed: the card is
still the review step and the spec that runs is still the one it showed.

**Long jobs and shared machines are treated properly.** The six-hour hard kill
is now a setting that defaults to off, because a CASSCF that takes hours is the
premise of this app rather than a fault. A job that was merely being waited on
is no longer reported as failed. A second user's job is no longer skipped by
the admission rotation because they queued during the second the dispatcher
spends measuring the host. And a cancelled engine job no longer leaves three
zombie processes behind for the life of the server.

**"Download all my data" and "delete all my data" now mean what they say.** The
archive includes conversations, saved plots with every version, project
archives and scan frames, none of which it carried before. The purge covers
plots and projects, and reports counts that name them. It still leaves
conversations alone, deliberately, because losing every chat as a side effect
of clearing out old calculations is not what that button says.

**The deployment scripts stopped lying.** `--rollback` moved the checkout back
and left the image stamped with a commit it had not built. A backup called
`--full` omitted plots, projects and scraped pages, and its retention pass
deleted directories it had not created. An update reported "no jobs running"
from a check that could not see them. Those are the tools the rest of this
phase depended on, which is why they were fixed second, immediately after the
security findings.

## The two that close as "not reproduced"

Both are closed with a measurement rather than a shrug.

**R-099**, the CAS refinement drawer's empty occupation table, does not
reproduce: the script that found it is 17 of 17 against the repro as written,
and the runner cannot produce the combination the review described, because the
rotation trail and the occupations are written from the same object in the same
breath. What was actually happening is that `JobDetailDrawer` renders its
dialog element before the job has been fetched, so the spec's assertions raced
a network request, and the four checks the review saw fail are the first four
in the file. A positive control that holds the job request for three seconds
reproduces the review's exact reading. The spec waits for the drawer to paint
now.

**R-103**, the api process's memory growth, is a warm cache and not a leak.
Four identical loads over a freshly restarted process cost 190.7, 17.4, 42.3
and 9.9 MB of RSS in order. The register asked for two loads; two were run
first and landed 1.8 MB over a threshold fixed beforehand, which is not a
verdict, so the experiment was extended until the shape of the series could
answer.

## Found while fixing

The standing rule in this repository is that a defect found while doing
something else is fixed in the same piece of work. Six were, and none of them
had an R-id because nobody had seen them:

- An active-space refinement could publish CAS(2,1), two electrons in one
  orbital, which holds a single configuration and describes no correlation at
  all. Found by asking for two states on water while settling R-099.
- The api container accumulated zombie processes, three per cancelled engine
  job, for the life of the server.
- `purge_own_data` answered 500 with a Postgres error for an id that is not a
  uuid, which is a danger-zone route leaking a database exception.
- `check_destructive.sh` reported "no image rebuild needed" on a deployment
  that rebuilds the image on every single update.
- `conf_04` waited 60 s for the api to come back after a restart, when the
  compose file documents a 90 s start period as deliberately generous.
- `.gitignore`'s `*.log` was silently dropping every evidence log this
  evaluation had ever produced, so each evidence directory in the tracker held
  only its README and every number in those READMEs cited a file that was not
  in the repository.

## Where the numbers are

Every performance figure quoted in this phase, with its command, its sample
size and the host conditions it ran under, is in
[`perf.md`](perf.md#fix-phase-measured-before-and-after-2026-09-13-and-2026-09-14).
Each step's before and after logs are in `evidence/fix/P<step>/`, with a README
that says what the test does and what the numbers mean. The final gate's four
suite runs and their triage are in `evidence/fix/P6.2/README.md`.

Findings that surfaced during the gate and were not part of this phase's scope
are in [`../../BACKLOG.md`](../../BACKLOG.md), each with the next experiment
named.

# Resolution of the 102 open findings

Carrying a resolution: 102 of 102.

## Outcome by severity

| | fixed | not reproduced | won't fix | other | (none) | total |
|---|---|---|---|---|---|---|
| S1 | 8 |  |  |  |  | 8 |
| S2 | 25 |  |  |  |  | 25 |
| S3 | 52 | 2 |  |  |  | 54 |
| S4 | 15 |  |  |  |  | 15 |
| total | 100 | 2 | 0 | 0 | 0 | 102 |

## Ids by outcome

- **fixed** (100): R-001, R-002, R-003, R-004, R-005, R-006, R-007, R-008, R-009, R-010, R-011, R-012, R-013, R-014, R-015, R-016, R-017, R-018, R-019, R-020, R-021, R-022, R-023, R-024, R-025, R-026, R-027, R-028, R-029, R-030, R-031, R-032, R-033, R-034, R-035, R-036, R-037, R-038, R-039, R-040, R-041, R-042, R-043, R-044, R-045, R-046, R-047, R-048, R-049, R-050, R-051, R-052, R-053, R-054, R-055, R-056, R-057, R-058, R-059, R-060, R-061, R-062, R-063, R-064, R-065, R-066, R-067, R-068, R-069, R-070, R-071, R-072, R-073, R-074, R-075, R-076, R-077, R-078, R-079, R-080, R-081, R-082, R-083, R-084, R-085, R-086, R-087, R-088, R-089, R-090, R-091, R-092, R-093, R-094, R-095, R-096, R-097, R-098, R-100, R-101
- **not reproduced** (2): R-099, R-103

## Fixed entries naming no regression test: 0

## Resolution hashes not reachable from HEAD: 0

## Named test paths that do not exist on disk: 0
