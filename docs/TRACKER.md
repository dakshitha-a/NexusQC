# Tracker: job rows that spend their width on the job

**In motion, opened 2026-09-09.** Two phases. Gives the job label back the
64px the timestamp column was holding, and puts a working cancel control on
running jobs in the Job Manager, which currently tells you to cancel a job
and offers no way to do it.

It stays here rather than moving to [`trackers/`](trackers/) until the next
plan starts. **Exactly one tracker is active at a time.** The one this replaces
is
[`trackers/2026-09-brand-mark-theming-and-ui-pass.md`](trackers/2026-09-brand-mark-theming-and-ui-pass.md).

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

## Why this plan exists

Both come from a screenshot of the Job Manager drawer.

**The job label had no room.** Each row is a `table-fixed` table of five cells:
checkbox `w-6`, status dot `w-6`, name `min-w-0`, relative time `w-16`, actions
`w-20`/`w-28`. Under fixed layout only the name cell absorbs the remainder, so
the timestamp column's width came directly out of the one piece of text a
person actually reads. The row already carried a second line under the name,
`job_id · ENGINE`, which ended well short of the right edge, so the timestamp
had somewhere to go for free. The widths are `rem`-derived and therefore scale
with the appearance store's text size, so the column was 64px at the default
and about 86px at the largest step: the name gained most at exactly the sizes
where it was worst.

**The Job Manager asked for an action it did not offer.** `DeleteJobButton` was
rendered there disabled for `pending` and `running` jobs, with the tooltip
"Cancel the job before deleting it", while `KillButton` was not rendered in
that panel at all. It existed only in the per-conversation Jobs panel and the
job detail drawer. So a running job in the Job Manager showed one greyed-out
control pointing at an action reachable nowhere on that surface. `KillButton`
was already built for this case: its `threadId` prop is optional and its own
comment names `JobManagerPanel` as the reason, and `api.cancelJob(job_id)`
needs no thread.

A third thing was found while reading and is fixed here under the standing
rule about defects discovered in passing: `relativeTime` existed as four
copies, three of them byte-identical, in `JobManagerPanel.tsx`, `JobsPanel.tsx`,
`PlotsPanel.tsx` and `ConversationList.tsx`.

---

## Phase 1: The row

- [done] P1.1: One shared relativeTime, and absolute stamps for the tooltip
  evidence: frontend/src/lib/relativeTime.ts → "one copy replaces four; npm --prefix frontend run build (tsc -b then vite build) passes and `grep -rn 'function relativeTime' frontend/src` now returns the single definition"
- [done] P1.2: Timestamp onto the meta line in both job lists
  evidence: tests/frontend/ui_16_jobmanager_kill.spec.mjs → "the row is four cells not five; the time span shares a baseline with the job-id span (tops within 6px); the name cell measured 291px of a 419px row, i.e. 69% of the width against the 55% floor the spec asserts"
- [done] P1.3: Stop replaces the disabled Delete in the Job Manager
  evidence: tests/frontend/ui_16_jobmanager_kill.spec.mjs → "a job held at running shows jobmanager-kill and no job-delete; a finished job shows job-delete and no jobmanager-kill; Stop → confirm on a job held at pending left status.json reading 'cancelled' and the row offering Delete"
- [done] P1.4: Panel-scoped kill testids so both lists can be measured
  evidence: frontend/src/jobs/KillButton.tsx → "testIdPrefix defaults to job-kill so every existing selector still resolves (ui_06 21/21, which measures job-kill-<id> in the Jobs panel); the Job Manager passes jobmanager-kill, and ui_16 measures that one specifically"

merged: pending

## Phase 2: Proving it

- [done] P2.1: Retarget ui_06 and ui_07 off positional cell selectors
  evidence: tests/frontend/ui_07_row_click_target.spec.mjs → "18/18, including 'clicking the relative time opens the preview drawer' -- the case that would have been lost if the time cell had simply been deleted from the spec; ui_06 21/21 with its two drawer-opening clicks moved onto jobmanager-name-<id>"
- [done] P2.2: A spec that actually sees a running row
  evidence: tests/frontend/ui_16_jobmanager_kill.spec.mjs → "44/44. Three seeded jobs, two of them held non-terminal by write_status, so the Stop branch is exercised rather than reasoned about; the confirm pair measured 23x23 inside the action column at fontScale 1.35 and 20x20 at 1.0, both fully inside the panel with no sideways scroll"
- [done] P2.3: Look at it, in a browser, at both ends of the text-size range
  evidence: tests/frontend/jobrow_shots.mjs → "11 screenshots of the Job Manager and the per-conversation Jobs panel in Balmer at text scale 1 and 1.35 and in Daylight, each in three states: at rest, mid-confirm, and with archived shown so a row carries rename + unarchive + Delete at once. Looked at: the timestamp sits at the right end of the job-id line on the same baseline, the long name fades where the column used to cut it, the running row shows a filled Stop square with the live hairline beside its amber dot, and nothing is clipped at either text size in either theme"

merged: pending
