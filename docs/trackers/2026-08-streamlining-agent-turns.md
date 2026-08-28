# Closed Tracker: streamlining the agent turns that decide nothing

Opened and closed 2026-08-28. Asked as a follow-on to
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

- merged: f045d07

## Phase 3: A ready draft goes straight to the approval card

- [done] P3.1: `run_when_ready`, set once at draft time
  evidence: tests/backend/chain_01_ready_draft_submits.py -> "24/24. start_job_draft sets it, update_job_draft can set it later, and it is sticky: a draft started with it and completed by an update that does not repeat it still opens the card. Stored in state rather than in the draft dict, so validate_draft's unknown-key refusal never sees it"
- [done] P3.2: A ready draft with it set reaches the interrupt in the same step
  evidence: tests/backend/chain_01_ready_draft_submits.py -> "the call that completes the draft returns the approval card and no NEXT STEP sentence, with the real spec and input preview on it. Against the full graph the card is reached with the LLM counter at zero"
- [done] P3.3: The boundary analysis redone for the new entry point
  evidence: tests/backend/chain_01_ready_draft_submits.py -> "an approved chained job still ends its turn with zero model calls and the app-written confirmation in place, so _job_submitted_node's 'a submission is the last thing a turn does' still holds with _finish_submission's second caller. A batch mixing check_job_status with a chained update_job_draft still reaches the model and publishes no app-written confirmation"
- [done] P3.4: "Show me the input without running it" still stops at READY
  evidence: tests/backend/chain_01_ready_draft_submits.py -> "with the flag unset the reply is DRAFT READY carrying the NEXT STEP sentence and the engine input, and no card opens. tests/backend/agent_02_draft_flow.py 35/35 covers the same path unchanged"
- [done] P3.5: The draft survives the interrupt that the chained path opens
  evidence: tests/backend/chain_01_ready_draft_submits.py -> "declining a chained card leaves job_draft holding the draft the card was built from. interrupt() aborts the tool node without committing its writes, so the freshly built draft is carried back out through the resumed call; without that, update_job_draft would amend the draft as it stood before the call that produced the card"
- [done] P3.6: The prompt and the fixed surface still fit their budgets
  evidence: tests/backend/agent_01_token_budget.py -> "13/13. The system prompt is 6,122 bytes against a 6 KB cap, helped by retiring the paragraph that existed to push the model over this exact hop, and the fixed surface is 9,874 tokens against a 10,000 cap with the two new arguments on the wire"

- merged: 5790a89

## Phase 4: Three defects the sweep found

- [done] P4.1: Tool results stop naming tools that do not exist
  evidence: tests/backend/tools_01_no_dead_tool_names.py -> "11/11. The sweep reported six sites naming set_molecule or generate_job_input; it was worse, because three of those also named set_pes_scan_endpoint, which is equally gone, so resolve_basis_from_bse's success path and every scan/NEB endpoint refusal named two dead tools each. The guard scans string literals through the AST rather than the file text, so docstrings may still explain what a retired tool was"
- [done] P4.2: System notices stop rendering as if the user typed them
  evidence: frontend/src/chat/MessageBubble.tsx -> "the watcher's injected message and the troubleshoot route's now carry {'kind': 'system_notice'}, and SystemNoticeRow renders them centred and muted with the model-facing prefix stripped, instead of the user's own accent bubble showing them the literal string '(system notice, not from the user)'. tsc --noEmit clean. troubleshoot.py's docstring claimed the frontend already did this; it did not, and now says so"
- [done] P4.3: Duplicate report suppression applied where it is correct
  evidence: app/agent/job_watcher.py -> "check_job_status marks completed, failed and cancelled as reported, but only the completed bucket consulted it, so a cancellation the agent had already discussed bought a second message. Deliberately NOT extended to failures: that notice carries the Troubleshoot button, and suppressing it would remove the only way to press it in order to save a repeated sentence"
- [done] P4.4: The neighbours still pass
  evidence: tests/backend/draft_01_summary_defer.py -> "41/41, the one that counts notice-carrying messages and so was the real risk in marking an injected HumanMessage"; cancel_01_notice_flow.py -> "11/11"; fail_01_notice_flow.py -> "20/20"

- merged: 7288484

## Phase 5: The long-conversation cliff

- [done] P5.1: The history cut point becomes sticky
  evidence: tests/backend/trim_01_stable_prefix.py -> "15/15. The window start is quantized to LLM_HISTORY_STEP so it holds still across a block of appends, then advances by exactly one step and never backwards. The budget loop advances in the same block size, so the start does not become a function of exact message sizes and move again next turn"
- [done] P5.2: The digest stops invalidating the system prompt
  evidence: tests/backend/trim_01_stable_prefix.py -> "the system message is the bare system prompt and the digest is the last message, as a HumanMessage because Ollama rejects a second system message, marked '(system notice, not from the user)' and saying it is background rather than a request. Never checkpointed, so it does not reach the transcript"
- [done] P5.3: A submit_draft call still survives a trim
  evidence: tests/backend/trim_01_stable_prefix.py -> "the call and its result both survive a window twice the nominal size, and no ToolMessage is left orphaned at the front. This is the failure mode _trim_history has a history of: two turns in a row were once cut off before they could emit the call, so the approval card never appeared and nothing logged it"
- [done] P5.4: Measured end to end against the served model
  evidence: a throwaway probe over four consecutive agent steps on a conversation past the window, using the app's own build_prompt_messages and all sixteen tool schemas -> "old shape: 9.69s, 9.66s, 9.65s, 9.70s of prompt evaluation, every step paying a full reprocess. New shape: 10.70s once while cold, then 0.35s, 1.44s, 0.38s. A four-step turn goes from about 39s of prompt processing to about 2s"
- [done] P5.5: The budget test stops keeping its own copy of the assembly
  evidence: tests/backend/agent_05_context_budget.py -> "0 failures against the real served model. It reproduced _agent_node's prompt building locally, which would have gone on measuring the old shape and reporting it healthy; it now calls build_prompt_messages, the same function the agent node uses"

- merged: 8753ff7

## Phase 6: Confirmed in a real browser, which is where this is visible

- [done] P6.1: Declining is answered at once, on the real stack
  evidence: tests/frontend/reject_03_instant_decline.spec.mjs -> "9/9. The reply paints 0.17s after the Reject click and reads 'Nothing was run. I've left the setup for water SP HF/sto-3g (PYSCF) as it is, so tell me what you'd like to change and I'll update it, or say to drop it and I will.' No job was created, the card is gone and the composer re-enables, so the turn genuinely ended rather than merely looking finished"
- [done] P6.2: Approving still behaves, on the same build
  evidence: tests/frontend/submit_02_instant_confirmation.spec.mjs -> "9/9. The confirmation paints in 0.80s and reads 'Started water SP HF/sto-3g (PYSCF). Job id 4e877f4c1535.' Worth re-running rather than trusting the backend contract, because _finish_submission gained a second caller in Phase 3"
- [done] P6.3: The chained draft reaches the card with the real model
  evidence: tests/frontend/reject_03_instant_decline.spec.mjs -> "the card came up from a single message stating task, method and basis together, with no separate submit turn. The script carries an elicitation fallback for the case where the model asks a question anyway, so this is an observation rather than an assertion, but the run did not need it"
- [done] P6.4: The test data was tracked and left nothing behind
  evidence: a diff of data/jobs and data/threads.json taken before and after both runs -> "no new job directories and no new threads. Both specs delete the account they create, which takes its conversation with it, and submit_02 deletes the job it ran"

- merged: cd585cc
