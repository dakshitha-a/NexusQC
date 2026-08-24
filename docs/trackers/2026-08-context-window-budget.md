# Closed Tracker: the reply that ran out of room to answer in

A user reported that their last job "took a couple of tries to coax out the
input card". It had: two consecutive turns ended mid-sentence, and both were
the turns that should have produced the job-approval card. Opened and closed
2026-08-24.

## What actually went wrong

Both replies came back with `finish_reason: "length"`. Replaying the exact
prompts against the served model gives 65,433 and 65,399 prompt tokens against
a 65,536-token window, so the model had about a hundred tokens to answer in. It
spent them on prose and was cut off before it could emit the `submit_draft`
tool call, and `submit_draft` is what raises the approval card. Nothing to
approve, no card, no error.

Three separate things had to line up:

**The window was never what the app thought it was.** `_build_llm` sent
`options={"num_ctx": 32768}` with a comment claiming this made the window
explicit rather than inherited from however the Ollama service was started.
The /v1 endpoint accepts that option and ignores it. Measured directly:
`num_ctx=2048` passed a 4,018-token prompt through untruncated, identical to
`num_ctx=32768`. `docs/MODEL_CONTEXT_BUDGET.md` already recorded that num_ctx
cannot be set from the client; the option had been re-added anyway, which is
why the correction now lives in a comment telling the next reader not to.

**`_trim_history` bounded message count, not size.** It kept the last
`LLM_HISTORY_WINDOW` (40) messages. Forty messages is modest until several of
them are 20,000-character job results, at which point it is 65,433 tokens.
`MODEL_CONTEXT_BUDGET.md` predicted this in as many words: "a session with
unusually long tool outputs in its recent history could still approach the
token ceiling."

**The same job's results were attached three times.** The Job Manager's
"Attach to prompt" stays on across turns, so the frontend re-sent the same job
id with every message and each one expanded to a full `job_context_summary()`.
Job `51a14d838f5b`'s context appears at messages 44, 50 and 55, byte for byte
identical, about 10,000 tokens a copy. Two of those three copies were pure
waste, roughly half the window.

The failure was silent at every layer. A clean HTTP 200, a graph turn that
completed normally, a well-formed checkpoint message that happened to stop
mid-word. The live backend monitors running at the time caught nothing,
correctly, because on the server side nothing had gone wrong.

## A note on estimating tokens

Two obvious estimators were tried and rejected on measurement, which is worth
recording because both fail in the dangerous direction. `tiktoken`'s
`cl100k_base` is the wrong tokenizer for Qwen and under-counted a real
conversation by 39% (47,142 against an actual 65,433). The usual ~4
characters-per-token holds only for prose: measured against the served model,
this app's content ranges from 1.16 chars/token for a table of floats to 5.31
for ordinary prose. What separates them is digits, so the estimator counts
digits and everything else separately, with coefficients set so every measured
sample comes out at or above its true cost.

## How tracking works here

Development is linear, so there is never a reason to have two trackers open
at once. Each plan, feature or non-trivial request gets its own tracker, this
file is whichever one is currently in motion, and when its plan is finished
the file is closed out and moved to [`trackers/`](trackers/), then a fresh one
starts here for whatever comes next.

Closed trackers are kept, never deleted. They are the audit trail for why the
code looks the way it does, and code comments cite them by path:

- [`trackers/2026-08-job-system-overhaul.md`](trackers/2026-08-job-system-overhaul.md)
  the 10-phase job-type/toolchain/agent overhaul. Closed 2026-08-22, 72 steps
  across 5 merged phases.
- [`trackers/2026-08-plots-as-objects.md`](trackers/2026-08-plots-as-objects.md)
  plots as first-class objects: a real chart spec, saved plot records with
  versions, conversational editing, and the Plots panel. Closed 2026-08-22,
  20 steps across 4 merged phases.
- [`trackers/2026-08-excited-state-scans.md`](trackers/2026-08-excited-state-scans.md)
  excited states at every point of a scan or interpolated path, for any method
  and any scan mode, plus the two latent bugs that surfaced underneath it.
  Closed 2026-08-23, 9 steps across 2 merged phases.
- [`trackers/2026-08-scheduler-fairness.md`](trackers/2026-08-scheduler-fairness.md)
  the concurrency cap that bounded admissions per dispatcher tick rather than
  in total, and the rotation pointer that advanced on refused attempts and so
  handed every freed slot back to whoever sat first. Closed 2026-08-23, 5 steps
  across 2 merged phases.
- [`trackers/2026-08-test-job-cleanup.md`](trackers/2026-08-test-job-cleanup.md)
  the suite removing the jobs it creates instead of leaving them in everyone's
  job list. Closed 2026-08-23, 4 steps in 1 merged phase.
- [`trackers/2026-08-frontend-visual-fixes.md`](trackers/2026-08-frontend-visual-fixes.md)
  a long job name pushing the row's stop and delete buttons out of view, viewer
  controls floating over the wrong thing, and orbital isosurfaces corrugated by
  their own cube grid. Closed 2026-08-24, 9 steps across 3 merged phases.
- [`trackers/2026-08-wigner-oscillator-strength.md`](trackers/2026-08-wigner-oscillator-strength.md)
  making oscillator strengths a hard requirement for a nuclear-ensemble
  spectrum, so routing picks an engine that can actually supply them, and
  normalizing the live broadening preview to match the finished figure's
  scale. Closed 2026-08-24, 5 steps across 2 merged phases.

- [`trackers/2026-08-preview-pane-and-attached-geometries.md`](trackers/2026-08-preview-pane-and-attached-geometries.md)
  the job drawer showing a job's product in the preview pane rather than behind
  a click or under an overlay, the geometries of an attached job travelling with
  it so a new job can start from one named image of a path, and one shared
  energy-unit conversion for the agent and the plots. Closed 2026-08-24, 8 steps
  across 4 merged phases.

- [`trackers/2026-08-spectra-travel-with-the-job.md`](trackers/2026-08-spectra-travel-with-the-job.md)
  a tagged spectrum job carrying its own broadened curve instead of only the
  sticks behind it, and a plot kind that puts several methods' spectra on one
  shared axis. Closed 2026-08-24, 3 steps across 2 merged phases.

- [`trackers/2026-08-equilibrium-marker-on-distributions.md`](trackers/2026-08-equilibrium-marker-on-distributions.md)
  a Wigner ensemble's geometry-parameter histograms marking the structure the
  samples were displaced around, and the rule for which geometry that is moving
  into one function instead of three copies. Closed 2026-08-24, 2 steps across
  2 merged phases.

- [`trackers/2026-08-job-row-click-target.md`](trackers/2026-08-job-row-click-target.md)
  the job's name being the one part of a Job Manager row that did not open its
  preview, which read as the app being slow to answer, and an open preview
  being unmounted by a single failed poll of the list behind it. Closed
  2026-08-24, 4 steps across 2 merged phases.

- [`trackers/2026-08-bagel-blind-input.md`](trackers/2026-08-bagel-blind-input.md)
  a pasted BAGEL CASSCF input described as the Hartree-Fock section it starts
  from, the orbital file a verbatim run asked the engine to write being deleted
  before anyone could download it, and the same sweep quietly leaving BAGEL
  orbital reuse with no source to reuse. Closed 2026-08-24, 12 steps across 4
  merged phases.

- [`trackers/2026-08-named-active-space.md`](trackers/2026-08-named-active-space.md)
  naming which orbitals form a CASSCF active space instead of only how many,
  through BAGEL's `active` keyword and PySCF's `sort_mo`, and the rule that the
  list is only ever set when the user names the orbitals themselves. Closed
  2026-08-24, 6 steps across 2 merged phases.

- [`trackers/2026-08-ci-reference-determinant.md`](trackers/2026-08-ci-reference-determinant.md)
  dominant transitions measured from an excited state's own leading
  configuration, because the reference was chosen after an open-shell singlet's
  two spin partners had been summed and a closed-shell determinant's had not.
  Closed 2026-08-24, 3 steps in 1 merged phase.

Closing one out means: every step `done` with evidence, a `merged:` row on each
phase, `scripts/check_tracker.py` passing, then `git mv` into `trackers/` and a
new file here. Only the active tracker is machine-checked; an archived one
records what was true when it closed and is not re-verified, since the scripts
its evidence names may legitimately have been deleted since.

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


---

## Phase 1: The window is declared honestly, and nothing overruns it silently

- [done] P1.1: Stop sending the ignored `num_ctx`, declare the real window in config
  evidence: tests/backend/agent_05_context_budget.py → "the option was measured to do nothing (num_ctx=2048 passed a 4,018-token prompt through untruncated, identical to num_ctx=32768) and is gone; QC_AGENT_LLM_NUM_CTX now declares the window the server really loaded, set to 65536 on this host to match `ollama ps`, and the budget line prints 53,488 tokens for history after the fixed prompt surface and output reserve"
- [done] P1.2: `_trim_history` budgets tokens, with a floor and a warning when it binds
  evidence: tests/backend/agent_05_context_budget.py → "all 75 prefixes of the conversation that failed now trim within budget; the turn that was cut off at 65,433 prompt tokens now runs at 55,608 and returns finish_reason tool_calls, and a synthetic history of 81 oversized job results trims to 46,305 tokens with 19,231 to spare where the message-count cap left about 100"
- [done] P1.3: Say so in the log when a reply is cut off by `finish_reason: "length"`
  evidence: tests/backend/agent_05_context_budget.py → "_warn_if_truncated fires on finish_reason length and stays silent on stop, reporting the server's own prompt_tokens when the reply was not streamed and a marked-approximate estimate when it was; the over-budget floor warning was then observed for real, logged by the running server through the HTTP route on a 534,272-token message and picked up by the live log monitor"
- [done] P1.4: An attached job's results are carried once, not once per turn
  evidence: tests/backend/agent_05_context_budget.py → "a first attach of job 51a14d838f5b expands to 20,991 characters, a second on a later turn to a 172-character pointer that still names the job so 'this job' resolves, and a different job is still attached in full; driven end to end through POST /messages the same job attached on two turns gives one 20,659-character copy and one 172-character pointer, and the model still answers 'cc-pVDZ.' on the second turn by reading the copy already in the history"

**One limit worth stating.** The marker carrying the job id is new, so the
dedupe only recognises attachments made after this change. A conversation that
already holds the old `(attached job context, not typed by the user)` form,
including the one that exposed this, will still take a full copy on the next
attach. That is the deliberate choice everywhere else in this project: no
adapter for content already on disk. The token budget is what protects those
conversations, and it does so regardless of how many copies they carry.
- merged: 275a7b9
