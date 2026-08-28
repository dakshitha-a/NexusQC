# Active Tracker: streamlining the agent turns that decide nothing

Opened 2026-08-28. Asked as a follow-on to
[`trackers/2026-08-instant-submission-confirmation.md`](trackers/2026-08-instant-submission-confirmation.md):
"can you recall the change we made to the job submission report where we made it
an agent turn only where it was necessary? can you look for instances like that
where agent turns are taken unnecessarily or inefficiently so we can improve the
percieved performance to the user?", then scoped by "i want things to be
streamlined without breaking existing functionality. be thorough. on the way if
you also discover ways to increase productivity or functionality let me know. we
can fold in implementation of them to the plan."

The sweep covered every path that starts a turn: three HTTP routes
(`server/routes/chat.py`), the watcher loop (`app/agent/job_watcher.py`) and all
sixteen tools. Four places came back where the model's entire output is
narration of something the app already holds, plus three defects found on the
way, which the user asked to have folded in.

## What the measurements said, and why they redirected the plan

Worth recording, because the obvious hypothesis was wrong and a later session
should not re-derive it. Probes against this host's Ollama using the app's real
system prompt and all sixteen tool schemas:

| condition | prompt tokens | prompt eval |
|---|---|---|
| cold | 31,727 | 15.88s |
| identical repeat | 31,727 | 0.31s |
| append only, the next agent step | 31,745 | 0.57s |
| after 60s idle | 31,727 | 0.35s |
| after 180s idle | 31,727 | 0.39s |
| digest line added to the system prompt | 31,761 | 16.12s |
| history window slid by one exchange | 30,142 | 14.85s |

The prefix cache survives three minutes of idle on this shared machine, so other
tenants are not evicting it, and while a conversation stays under the
forty-message window every agent step is an append costing well under a second.
The 53 to 77 second figure quoted in earlier trackers came from a 30-message
conversation, which is below that window, so neither invalidation above was even
active when it was measured. Real turns on the live thread here are one to four
agent steps generating 130 to 820 characters in total, which is a few seconds of
generation. What is left is queueing behind other tenants on the shared GPU.

That is precisely why removing whole turns is the lever rather than tuning the
prompt: every agent step is a separate request that has to reach the front of
that queue, so a removed turn is a removed wait whether the machine is busy or
quiet. The window slide is a real cliff, 0.3s to roughly 15s per step, but only
past forty messages, which is why it is Phase 5 and not Phase 1.

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

Development is linear, so there is never a reason to have two trackers open at
once. Each plan, feature or non-trivial request gets its own tracker, this file
is whichever one is currently in motion, and when its plan is finished the file
is closed out and moved to [`trackers/`](trackers/), then a fresh one starts
here for whatever comes next.

Closed trackers are kept, never deleted. They are the audit trail for why the
code looks the way it does, and code comments cite them by path. The two most
recent closures:

- [`trackers/2026-08-cap-across-ticks.md`](trackers/2026-08-cap-across-ticks.md)
  the concurrency cap now holds between dispatcher passes and not only within
  one. 6 steps across three phases, closed 2026-08-28.
- [`trackers/2026-08-instant-submission-confirmation.md`](trackers/2026-08-instant-submission-confirmation.md)
  an approved job confirms itself, with no LLM turn. 13 steps across four
  phases, closed 2026-08-28.

## Phase ordering

The dependency is real rather than a preference. Phases 1 and 2 are
self-contained. Phase 3 moves the approval gate's entry point and changes the
premise Phase 1's boundary analysis rests on, so it lands against a settled
router. Phase 4 is independent. Phase 5 touches nothing the others touch.

---

## Phase 1: A declined card answers itself

- [done] P1.1: `pending_rejections`, the mirror of the submission receipt
  evidence: app/agent/state.py → "same one-step-handoff shape and the same `_append_submissions` reducer, whose docstring now says it serves both. Carries no job id because a declined draft was never written to disk, and the label comes from the spec the card was built from"
- [done] P1.2: The rejection tool message rewritten from an instruction into a record
  evidence: tests/backend/reject_01_decline_message.py → "24/24. The ToolMessage now closes with 'do not ask again' and 'do not resubmit', which is what stops the next turn re-asking the question and moving the narration one turn later instead of removing it"
- [done] P1.3: `_receipts_this_step` shared by both routers, still keyed on tool call ids
  evidence: tests/backend/reject_01_decline_message.py → "a batch mixing check_job_status with a declined submit_draft reaches the model, publishes no app-written decline, and keeps the other tool's result in history. A batch carrying both a submission and a rejection leaves each slot short of the trailing ids, so both helpers return empty and the model gets it"
- [done] P1.4: The `job_rejected` node writes the message inside the graph
  evidence: tests/backend/reject_01_decline_message.py → "the turn ends on an AIMessage carrying {'kind': 'job_rejected'} positioned after the ToolMessage, with snapshot.next == () and the receipt consumed. Inside the graph specifically, because append_notice's update_state destroys an open approval card"
- [done] P1.5: The draft survives a decline, so it can be amended
  evidence: tests/backend/reject_01_decline_message.py → "job_draft still holds task=single_point method=hf after the decline. This is the one place a rejection deliberately differs from a submission: the message asks what to change and update_job_draft needs something to amend"
- [done] P1.6: `_after_job_rejected` keeps a multi-part request alive
  evidence: tests/backend/reject_01_decline_message.py → "with follow_up_work=True the stub model is called exactly once and the decline is still written first, so declining one job does not silently drop the rest of what the user asked for; with it false the model is called zero times"
- [done] P1.7: The neighbour that asserted the old behaviour was updated, not left to rot
  evidence: tests/backend/submit_01_confirmation.py → "27/27. Its rejection scenario asserted 'a rejection still goes to the model', which this phase inverts, so it now asserts that the two app-authored nodes stay told apart and points at reject_01 for the fuller coverage"

- merged: e6ef39b

## Phase 2: A cancelled job notifies without a turn

- [done] P2.1: Cancellations move to a no-LLM notice
  evidence: tests/backend/cancel_01_notice_flow.py -> "11/11. invoke_turn_if_idle is replaced with a sentinel that raises, and it is never reached; the notice is a checkpointed message carrying {'kind': 'job_cancelled'}, named through resolve_job_label so it reads the way the job list does rather than as single_point/gs"
- [done] P2.2: The `seen` bookkeeping moves with them
  evidence: tests/backend/cancel_01_notice_flow.py -> "polling twice leaves the notice count unchanged. This is the trap the block exists for: the tick's own seen write lives after the agent turn, and a tick whose only terminal ids are cancellations now returns at the guard before reaching it, so without an explicit write a lone cancellation would re-notify every two seconds forever"
- [done] P2.3: Held on an open card only, never on a draft
  evidence: app/agent/job_watcher.py -> "written through append_notice_unless_card_pending, which declines while a card is open because update_state discards a pending interrupt, and leaves the id unseen so the next tick retries. Deliberately not held for a draft, following the failure block's reasoning: it runs no LLM and asks the agent for nothing, so it cannot derail one"
- [done] P2.4: The turn buckets and their neighbours still behave
  evidence: tests/backend/fail_01_notice_flow.py -> "20/20"; casreco_05_reporting_hygiene.py -> "24/24"; p8_02_cas_reco_followup.py -> "14 passed, 0 failed"; draft_01_summary_defer.py -> "41/41". _agent_notice lost its cancelled_ids parameter, so the two scripts calling it positionally were updated with it

## Phase 3: A ready draft goes straight to the approval card

- [todo] P3.1: `run_when_ready`, set once at draft time
- [todo] P3.2: A ready draft with it set reaches the interrupt in the same step
- [todo] P3.3: The boundary analysis redone for the new entry point
- [todo] P3.4: "Show me the input without running it" still stops at READY

## Phase 4: Three defects the sweep found

- [todo] P4.1: Tool results stop naming tools that do not exist
- [todo] P4.2: System notices stop rendering as if the user typed them
- [todo] P4.3: Duplicate report suppression applied to every bucket it is correct for

## Phase 5: The long-conversation cliff

- [todo] P5.1: The history cut point becomes sticky
- [todo] P5.2: The digest stops invalidating the system prompt
- [todo] P5.3: A submit_draft call still survives a trim
