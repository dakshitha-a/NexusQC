# Closed Tracker: job drafting outranks job summaries

Opened 2026-08-27. Reported as "when a job completes, it generates a summary.
That process is so aggressive that even if the agent was working on a draft for
a job, that process is completely interrupted to generate the summary", with the
rule to apply: drafting comes first, and summaries wait until the job the user
is assembling ends in a submission or a rejection.

The symptom in the conversation it came from was blunter than that. The user
asked "where is the card for the casscf job?" twice, and the agent's own reply
named the cause: "the submit step got interrupted by the job-completion notice
and the card never actually appeared." That thread ended up carrying five
`submit_draft` tool calls that no `ToolMessage` ever answered.

## What was actually happening

A summary is not a message the watcher appends. It is a synthetic
`HumanMessage` plus a real agent turn. Invoking the graph with new input while
it sits at `submit_draft`'s `interrupt()` **discards the pending approval
task**: `interrupts` goes from one to zero, `next` goes from `("tools",)` to
`()`, the tool call is orphaned permanently, and the user's later Approve is a
silent no-op. Measured on the real topology, not inferred from the library's
contract.

Two holes let that happen, and only fixing both helps.

1. **The guard ran outside the lock.** `_poll_once` checked `pending_approval`
   before calling `invoke_turn`, and `invoke_turn` is what takes the thread
   lock. A drafting turn runs 53 to 77 seconds and the watcher polls every two,
   so it took roughly thirty snapshots *inside* that turn, every one of them
   before the interrupt was committed, then blocked on the lock and was
   released at exactly the wrong moment. Not a narrow race: the ordinary path.
2. **The elicitation phase was unguarded entirely.** Everything before
   `submit_draft` ("which basis set?" and the answer) has no interrupt to
   detect.

A third clobber path turned up while testing the first two, unrelated to
drafting: `append_notice`, which a **failed** job uses and which only writes a
message through `update_state`, destroys a pending approval card in exactly the
same way. So a job dying at the wrong moment silently ate the card too.

## The shape of the fix

`job_draft` could not be the signal. `CLEAR_DRAFT` exists in
`app/agent/state.py` and nothing has ever written it, so a draft outlives its
own submission and its own rejection; the field is true forever after a
conversation's first draft. A new `draft_status` field spans exactly the
drafting episode instead, stamped by `_draft_command` (the one funnel both
draft tools go through) and cleared by `_finish_submission` on both its
branches, which are the two endings the user named.

The load-bearing piece is `invoke_turn_if_idle`, which re-checks the hold
**while holding the thread lock**. Without that the new field changes nothing.

Two decisions the user made when asked:

- An abandoned draft releases the queue after a quiet period rather than
  holding for ever (`QC_AGENT_DRAFT_HOLD_SECONDS`, default 900, `0` holds
  strictly). Measured from the last draft mutation, not from the thread
  registry's `last_active_at`, which the watcher bumps itself.
- A failed job still speaks up immediately during a draft. That answer was
  given on the premise that a failure notice cannot clobber anything, and P0
  below found the premise false, so it holds in the one case where it is
  provably destructive: while a card is actually open.

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

- [`trackers/2026-08-evaluation-battery-run-2.md`](trackers/2026-08-evaluation-battery-run-2.md)
  the second full run of the manuscript evaluation battery, from a mandatory
  card audit through execution to the two fixes it earned. 20 steps across six
  phases, closed 2026-08-27.
- [`trackers/2026-08-clearing-the-backlog.md`](trackers/2026-08-clearing-the-backlog.md)
  everything the manuscript evaluation battery found, plus the older items that
  had been carried forward without an owner. 28 steps across nine phases,
  closed 2026-08-26.

The rest of `trackers/` follows the same shape; each names its own scope in
its first paragraph.

---

## Phase 0: Establish what actually destroys a card

- [done] P0.1: Both clobber paths measured against a graph parked at a real interrupt
  evidence: tests/backend/draft_01_summary_defer.py → "starting a turn on an interrupted graph takes interrupts 1→0, next ('tools',)→(), leaves the submit_draft call orphaned and makes a later resume a silent no-op. append_notice's update_state does the same, which is asserted directly so the failure-notice gate cannot be relaxed by accident"
- merged: 0c54ed0

## Phase 1: A drafting exchange is visible in state

- [done] P1.1: `draft_status` spans exactly the drafting episode, with a reducer
  evidence: app/agent/state.py → "{'stage': 'drafting', 'at': epoch} or absent, with CLEAR_DRAFT_STATUS and _last_draft_status mirroring the CLEAR_DRAFT/_last_draft pair; the reducer is required because two update_job_draft calls can land in one superstep and LastValue raises on that"
- [done] P1.2: CLEAR_DRAFT's docstring corrected to describe what the code does
  evidence: app/agent/state.py → "it claimed submit_draft and start_job_draft write it; nothing ever has. Now says so, and says why a non-empty job_draft must never be read as 'a draft is being assembled'"
- [done] P1.3: Written at the mechanical points, and only those
  evidence: tests/backend/draft_01_summary_defer.py → "start_job_draft stamps it with a timestamp; both _finish_submission branches clear it; submit_draft with nothing assembled deliberately does not, since that call lands one step before start_job_draft"
- merged: 0c54ed0

## Phase 2: The gate, evaluated under the lock

- [done] P2.1: `draft_hold_reason` and `invoke_turn_if_idle` in graph.py
  evidence: tests/backend/draft_01_summary_defer.py → "a turn already inside invoke_turn_if_idle, blocked on the lock, defers when a draft appears while it waits. This is the case that fails without the in-lock re-check"
- [done] P2.2: Lock-free reads stay lock-free
  evidence: tests/backend/perf_06_lockfree_reads.py → "4/4; read_state 0.018s and pending_approval 0.013s against a 1.0s budget while a turn held the lock"
- merged: 0c54ed0

## Phase 3: The watcher holds, and delivers later

- [done] P3.1: All five turn-starting buckets gated, held ids left unseen
  evidence: tests/backend/draft_01_summary_defer.py → "two jobs finishing mid-draft produce no turn and stay unseen; clearing the flag delivers both in one turn naming both ids, not one turn per job"
- [done] P3.2: A held summary announces nothing, and the jobs panel still updates
  evidence: tests/backend/draft_01_summary_defer.py → "no turn_start is emitted for a turn that never ran, and job_update still fires for every finished job so a held summary cannot look like a stalled job"
- [done] P3.3: Failure notices flow during a draft but wait for a card
  evidence: tests/backend/draft_01_summary_defer.py → "the death notice lands mid-draft with no agent turn; with a card open it waits, the card survives, and the job stays unseen so the notice is not lost"
- [done] P3.4: An abandoned draft expires
  evidence: tests/backend/draft_01_summary_defer.py → "a draft older than DRAFT_HOLD_SECONDS stops holding, a fresh one on the same thread holds again, and with the window set to 0 the hold never expires"
- merged: 0c54ed0

## Phase 4: Nothing else moved

- [done] P4.1: The existing watcher and draft tests still pass
  evidence: tests/backend/fail_01_notice_flow.py → "20/20"
- [done] P4.2: The cas_reco follow-up and the approval-card contract are intact
  evidence: tests/backend/p8_02_cas_reco_followup.py → "14/14, after repointing its monkeypatch at invoke_turn_if_idle"
- [done] P4.3: Draft flow, capability guards and scans unaffected
  evidence: tests/backend/agent_02_draft_flow.py → "35/35; agent_03 12/12, agent_06 18/18, casreco_05 24/24, scan_02 64/64, approval_01 6/6"
- merged: 0c54ed0
