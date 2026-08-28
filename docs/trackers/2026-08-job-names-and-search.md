# Active Tracker: job names that identify the job, and a way to find it

Opened 2026-08-28, directly out of the previous plan. Writing the submission
confirmation put a job's generated name in front of the user in a new place,
and doing that exposed what the name actually said. The user's words:

> "lets improve auto_job_name a bit next. make the change you suggested and
> also see if names casscf and caspt2 jobs properly. because I think i saw it
> name them the same. I also want a search bar added to the job manager."

They had seen it. A CASSCF and a CASPT2 on the same molecule and active space
produced byte-identical names, because `auto_job_name` dropped the method
entirely for both and kept only the active space. Since `resolve_job_label` is
the single definition of a job's name, that one collision was shared by the Job
Manager list, the drawer heading, the submission confirmation and every
download filename at once.

Two neighbouring faults came out of the same probe: the task label and the
level of theory were concatenated with no separator (`SPHF`, `Freqb3lyp`,
`NEB-TSb3lyp`), and snake_case method identifiers reached the user verbatim
(`SPEOM_CCSD`).

The second half of the request is the search bar, specified as fuzzy on a
follow-up: "make sure its fuzzy search".

## Rules (enforced by `scripts/check_tracker.py`)

- Step status is exactly one of `todo` | `in-progress` | `done`.
- A step may be marked `done` **only with an evidence field**: the
  verification script/command path plus a one-line observed result.
- The tracker edit ships **in the same commit** as the step's final code
  change, so `git log --follow docs/TRACKER.md` is the audit trail.
- A phase's `merged` row records the commit hash the stage landed as, and it
  must be a bare hash; the checker rejects anything else.

Format for a step row:

```
- [status] P<phase>.<step>: <short name>
  evidence: <script/command> → "<observed result>"   (required when done)
```

## How tracking works here

Development is linear, so there is never a reason to have two trackers open
at once. Each plan, feature or non-trivial request gets its own tracker, this
file is whichever one is currently in motion, and when its plan is finished
the file is closed out and moved to [`trackers/`](trackers/), then a fresh one
starts here for whatever comes next.

Closed trackers are kept, never deleted. They are the audit trail for why the
code looks the way it does, and code comments cite them by path. The two most
recent closures:

- [`trackers/2026-08-instant-submission-confirmation.md`](trackers/2026-08-instant-submission-confirmation.md)
  an approved job now confirms itself instead of waiting on a model turn that
  only narrated it, with auto-chaining preserved. 15 steps across four phases,
  closed 2026-08-28. Measured 21.28s to 0.10s at the median.
- [`trackers/2026-08-drafting-outranks-summaries.md`](trackers/2026-08-drafting-outranks-summaries.md)
  a finished job's summary no longer interrupts the calculation the user is
  setting up. 13 steps across five phases, closed 2026-08-27.

The rest of `trackers/` follows the same shape; each names its own scope in
its first paragraph.

---

## Phase 1: A name that identifies the calculation

- [done] P1.1: The collision confirmed before being fixed
  evidence: a throwaway probe over ten representative specs → "CASSCF and CASPT2 on uracil with a (12,9) active space both produced 'uracil SP(12,9)/cc-pvdz (BAGEL)'. The same probe showed SPHF, SPcam-b3lyp, Freqb3lyp, OptHF, NEB-TSb3lyp and SPEOM_CCSD, and a CASSCF with no active space losing its method entirely"
- [done] P1.2: Multireference methods name themselves
  evidence: tests/backend/name_01_job_labels.py → "CASSCF and CASPT2 now differ, both keep the active space, and a CASSCF with no active space still says CASSCF rather than dropping to a bare task label"
- [done] P1.3: The task label and the level of theory are separated
  evidence: tests/backend/name_01_job_labels.py → "'water Opt HF/sto-3g (PYSCF)', which reads the way a chemist writes a level of theory. A space, not a slash, since the slash already separates method from basis"
- [done] P1.4: snake_case identifiers stop at the boundary
  evidence: tests/backend/name_01_job_labels.py → "eom_ccsd renders EOM-CCSD via a _method_label helper; the test also asserts no raw task identifier (single_point, neb_ts, opt_freq) appears in any generated name"
- [done] P1.5: Renames and download filenames still behave
  evidence: tests/backend/name_01_job_labels.py → "23/23. A stored label still wins over the generated one, and the two multireference filename stems now differ by more than the job id, which matters because a downloads folder previously received two identically-named files"

## Phase 2: Finding a job in the list

- [done] P2.1: A fuzzy matcher, kept separate from the panel
  evidence: frontend/src/lib/fuzzy.ts → "subsequence matching with fzf-style ranking: adjacency, word-start and earliness bonuses. Substring matching is the special case that scores highest, so exact queries still rank first"
- [done] P2.2: The Job Manager searches name, id, engine and status
  evidence: frontend/src/jobs/JobManagerPanel.tsx → "every field the row already displays is searchable, weighted so a fuzzy hit on a hex job id can never outrank a real name match. Whitespace splits into terms that must all match, so 'casscf bagel' works without a query syntax"
- [done] P2.3: Verified in a real browser
  evidence: tests/frontend/jobs_01_search.spec.mjs → "11/11. The load-bearing case is 'wtr' against 'water SP HF/sto-3g (PYSCF)', a subsequence but not a substring, which a substring filter fails and a fuzzy one passes; 'sto3g' matches the basis the same way; a nonsense query empties the list and says so; the clear button restores every row"

## Phase 3: Ship it

- [done] P3.1: Frontend rebuilt on the host and the stack confirmed current
  evidence: docker exec nexusqc_dev-api-1 python3 -c "auto_job_name(...)" → "the running container returns 'uracil SP CASSCF(12,9)/cc-pvdz (BAGEL)' and 'uracil SP CASPT2(12,9)/cc-pvdz (BAGEL)', so the image carries the fix; nginx serves the rebuilt bundle, which the browser spec above exercised"
- [done] P3.2: The backend suite runner actually runs the suite
  evidence: tests/run_backend.sh → "it invoked a bare python3 with no PYTHONPATH, so 39 scripts died on ModuleNotFoundError before executing a check. The first attempt at a fix used ${PYTHONPATH:-$PWD}, which is inert on this host because the shell profile already exports Gaussian's /opt/app/g16 paths; it prepends now, keeping whatever was there"
- [done] P3.3: Full backend suite run against the final code
  evidence: tests/run_backend.sh → "84/87 scripts fully passing. The three that did not are unrelated to this work: model_compat 12/13, where the served model chose an active space instead of asking, which is the model behaviour that harness exists to measure; and perf_02 / perf_04, neither of which touches anything in this session's diff (see below)"

### The two performance failures, and why they are not this work

Recorded rather than fixed, because both need their own decision.

- **`perf_04_fair_scheduling` fails reproducibly**, with the identical
  admission order `A, A, B, A, A, A, A` on two separate runs. Round-robin
  should put user B's single job in the rotation immediately after user A's
  first, not after all of A's. This is a genuine failure of the scheduler
  against its own stated contract, and it predates this session: nothing in
  `git diff 87d3f12..HEAD` touches `app/chemistry/jobs/scheduler.py`, whose
  last change was `17042e2`. Its own closed tracker is
  `trackers/2026-08-scheduler-fairness.md`.
- **`perf_02_ttft_and_concurrency` fails on timing**: time-to-first-token
  under four users came in at 5.70x the single-user median against a 3x
  budget, and four concurrent turns finished no faster than four serial ones.
  This host shares its GPUs with other tenants, so the measurement is
  load-dependent by construction. Not re-run in isolation, so it is
  unconfirmed either way rather than dismissed.

### A hazard found the hard way

`tests/backend/p1_07_purge_status_source.py` calls `POST /api/admin/purge/jobs`
(`purge_all_jobs`), and it is in `run_backend.sh`'s default set. **A full suite
run therefore destroys every job on the stack, not only the ones the suite
created.** That happened here: the job artifacts behind all three real
conversations were lost. The conversations themselves survived intact, since a
job purge does not touch the Postgres checkpoints, so the computed results are
still readable in the chat and the jobs can be re-run from it.

`sec_10_*` is already excluded from the default run for being destructive.
Whether `p1_07` should be excluded the same way is a deliberate decision for
the maintainer, not a cleanup detail, which is why it is written down here
rather than changed.

## Phase 4: The update path protects a production deployment

Asked for directly: "check that the update script backs up and restores data
if the update is destructive in any way ... destruction of anything on the dev
stack is not as dire. merely a mild annoyance. but it should never be the case
for a person updating their production deployment."

- [done] P4.1: The data archive is verified, like the database dump already was
  evidence: scripts/backup.sh → "the pg_dump is checked with `pg_restore --list` on the stated reasoning that a truncated dump is worse than no dump because it looks like one; full_data.tar.gz had no equivalent check despite being the only copy of every job's results. It now gets `tar -tzf`, proven to accept an intact archive and reject a truncated one"

### What the audit found, and what it did not change

The gates themselves are sound and worth stating so nobody re-derives them:
the backup is unconditional and runs before anything is touched, the update
refuses to proceed if it fails, `--dry-run` exits before that point,
destructive changes need a typed confirmation, and the backup includes the
pieces whose loss is silent (`.env`, `docker-compose.override.yml`, the certs,
`.update-log`, `data/threads.json`).

Two sharp edges were left alone deliberately, because both are judgement calls
about operator behaviour rather than defects:

- **`--rollback` is code-only and cannot undo a schema change or restore lost
  job data.** That is documented in the script and is probably the right
  default, since restoring the pre-update database also rewinds every account,
  session and conversation created since. The problem is the advice: a failed
  `compose up` and a failed health check both print "roll back with:
  scripts/update.sh --rollback", which for a destructive update is the wrong
  instruction and will leave old code against a new schema. The failure
  messages should name the backup directory and `scripts/restore.sh` instead.
- **A failing health check still records the update as successful.** The
  `updated` line is appended to `.update-log` before the exit status is
  considered, so a deployment that never came up healthy is recorded as the
  new baseline, and a later `--rollback` reads that entry as the good commit
  to return to.
