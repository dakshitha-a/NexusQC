# Backlog

The living record of unimplemented bugs and features. Kept short deliberately.
This is a list to work from, not an investigation report. When an item needs
more explanation than a line or two, that reasoning belongs in the commit that
closes it, not here.

## History

This replaces `docs/ROADMAP.md` and the four `docs/e2e-*-2026-08-16*.md` /
`docs/e2e-*-2026-08-17.md` documents, retired once the last two items they
tracked (FR-2's higher-resolution viewer capture, and the Ketcher chunk-weight
reduction) were implemented and verified live. Their full investigation,
findings, the ranked fix plan, and what was checked live versus by inspection
only, is preserved in git history rather than carried forward. To recover one:

```
git log --all --full-history -- docs/ROADMAP.md   # find the last commit that has it
git show <that-commit-sha>:docs/ROADMAP.md          # print its content
```

A fresh testing pass is expected to populate this file going forward, superseding
the 2026-08-16/17 pass's results.

The 10-phase registry v2/agent-rebuild overhaul (`docs/trackers/2026-08-job-system-overhaul.md`, all 72
steps done as of 2026-08-20) retired the `submit_job` tool this file's own
"Open" section used to name. Replaced by `start_job_draft`/
`update_job_draft`/`submit_draft`, whose ready-draft response now always
carries an explicit "NEXT STEP: ... call submit_draft now" instruction,
resolving the skipped-submission problem that item described. Recovered the
same way as `docs/ROADMAP.md` above if the original wording is ever wanted.

The CAS recommendation engine's entries were closed out together in September
2026 (`docs/trackers/2026-09-cas-engine-closeout.md`). Ten of them left this
file at once, which is worth explaining rather than leaving as a gap in the
history. Each left through one of three doors: fixed and validated across the
benchmark, settled as a deliberate decision, or measured and written into
`docs/CAS_ENGINE_METHOD.md` as a stated limitation with its number attached. A
limitation reported with a measurement behind it is not an open item, and
`docs/casbench/` holds the measurements.

Two of those entries turned out to be wrong about their own subject, which is
the argument for closing a set of related items together rather than one at a
time. The irreproducible recommendation was blamed on the orbital ranking and
was caused by an unstable SCF reference two stages earlier. And the molecule
said to exceed the refinement cap was not the one that did.

## Open

Everything here came out of the 2026-09 fix phase's final gate. Each entry says
what was observed, what has been ruled out, and the next experiment, because an
entry with no next step is a note rather than a backlog item.

**The CAS engine misses aza-naphthalene's n->pi\* states.** All 12 in the
QUESTDB run; 8 scored at +2.3 to +6.0 eV in a (14e,12o) space, 4 left at an
unrunnable (18e,14o); APC-2 is good on 10 of 12, and the smaller azines are
good in 33 of 42. The user decided on 2026-11-10 that this gets its own plan
rather than a fix inside another one; it is recorded as a limitation in
`docs/CAS_ENGINE_METHOD.md` §4.4. **Next experiment:** compare the engine's
(14e,12o) orbitals for aza-naphthalene-x1 against APC-2's (18e,13o) and see
which nitrogen lone pair or pi orbital the narrowing drops; the fix is then
validated across the whole benchmark.

**Closed 2026-11-10, each reproduced on the current code first:**

- **deploy_05 under a four-suite load.** Not load. The app keeps one session
  per account by design (`app/auth/redis_session.py`), and every suite logs in
  as `qatest_admin`, so concurrent suites log each other out; the page drops to
  the login screen and the next click finds its element detached. Alone it
  passes. `tests/README.md` now says suites sharing an account run one at a time.
- **The approval card rate.** `e2e_21` on the stack: the ensemble request now
  drafts its frequency prerequisite for approval (user decision), 3 of 3;
  the conical intersection derives its state count from the crossing pair,
  3 of 3 in-process; the other cases 3 of 3. That fix also closed a real bug:
  a CASSCF optimisation targeting S1 with no state count ran on the ground
  state (`tests/backend/draft_09_target_state_count.py`).
- **The orbital scrubber.** The viewer now waits for the drag's release;
  `ui_09` measures 0 renders during the drag and 1 in total.
- **Drawer sections "where they should be gated off".** A stale test: it keyed
  jobs on `method`, which became the level of theory in the v2 job model. The
  drawer was right; `ui_02` now checks each section against the job's data.
- **`e2e_11` C2.** A stale test reading `spec.params.method`; 8 of 8 on the
  stack. Keyword suggestion itself was never broken.
- **`e2e_12` G1.** A stale test: a complete draft goes straight to the
  approval card now, so "DRAFT READY" text never arrives. The card carries
  the source job's geometry (reproduced in-process).
- **`start_job_draft` dropped a basis the model passed it** (logged and fixed
  the same day). Its `run_when_ready` input had done nothing since ready
  drafts began raising their own card, so it was replaced by an `updates`
  dict that goes through the same checks as `update_job_draft`'s; the tool
  stays at 8 inputs. The system prompt also told the model to preview an
  input by leaving `run_when_ready` unset, which would have raised a card;
  it now says `preview_only`. In-process: an HF single point reaches its card
  in 2 tool calls, and a preview stops with the input shown.
- **BAGEL CASSCF optimisation and frequencies "only structurally confirmed".**
  Verified end to end the same day on water CAS(8,6)/6-31G against ORCA; the
  first real chain found and fixed two bugs (optimised atoms named "O1", and no
  `converged` key). `tests/backend/bagel_02_opt_then_freq.py`, 10 of 10 live.
  CAS(4,4) on water was a poor comparison: its active space is not unique, and
  ORCA's rotated mid-optimisation.
- **`e2e_17` L9b.** A test race: it read the conversation the moment the
  notice appeared, while the summary turn was still running. 21 of 21.

**Atom numbers do not come back after a vibrational mode change.**
CLOSED on 2026-09-14. `tests/frontend/ui_10_atom_label_toggle.spec.mjs` is
21 of 21 at the final gate. The mechanism was R-064: `canvasSnapshot` was
capturing the first canvas on the page rather than the one belonging to the
panel under test, so it compared the molecule viewer's canvas with itself while
the labels were toggling on the vibration viewer's. The helper takes a panel
now. Left here rather than deleted because the entry's own investigation ruled
out three plausible mechanisms and it is worth knowing which one it was.

The last entry to close was the app-versus-host latency split, which had
stood because its denominator could not be measured against a card shared
with other tenants: sampled twice in one run it came back 3.05x and 0.95x,
so the script reported the split as unavailable rather than assert one.
GPU 0 on this host is reserved for NexusQC and Ollama serves only NexusQC,
which is what made the measurement possible rather than any change to the
code. Measured 2026-09-06 on the current deployment: warm time to first
token has a median of 2.49 s over twelve samples, ranging 1.44 to 3.81 s;
with four turns at once, pooled over three bursts, the median is 6.47 s and
a whole turn 8.32 s. The stack as a whole slows by 2.60x under that load
and the model server on its own accounts for 2.13x of it, so **the app
multiplies the server's own concurrency penalty by 1.22x**. Four concurrent
turns still finish faster than four serial ones, 14.8 s against about 17 s.
Details in `evaluation/2026-09-06-full-pass.md`.

### Found while taking the thesis screenshots (2026-11-09)

Observed on the dev stack at fdcf367, driving the app as the test admin.

**Fixed 2026-11-10:** an empty orbital on one atom is no longer labelled a
lone pair; it takes its shape label with a "*".

**Fixed 2026-11-10:** the job-finished notice no longer shows the user the
instruction meant for the model; the row reads "Job X finished."
