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
- [todo] P2.3: Verified in a real browser
  evidence:

## Phase 3: Ship it

- [todo] P3.1: Frontend rebuilt on the host and the stack confirmed current
  evidence:
