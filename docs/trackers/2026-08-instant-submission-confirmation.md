# Closed Tracker: an approved job confirms itself

Opened and closed 2026-08-28. Asked as a question about the app's own behaviour, then a
proposal: "I don't think an LLM turn is necessary just to say the job has been
submitted. The input scipt is already user reviewed. It either runs or fails.
and a troubleshoot path already exists upon failure. the summary path already
exists upon success. isn't it better to have a canned response for job
submission? an LLM turn is unnesessary lag/complexity isn't it?"

It was. Confirmed against the live thread `02a748da932d469794fd7faf428f9328`,
where the confirmations for jobs `791d1aed8660` and `4b9707e1b598` are
near word-for-word identical apart from the method name and the job id, because
the model was paraphrasing a fixed instruction the tool handed it. Drafting
turns on this host measure 53 to 77 seconds
([`trackers/2026-08-drafting-outranks-summaries.md`](trackers/2026-08-drafting-outranks-summaries.md)),
so that was tens of seconds of silence between the click and any sign the job
had started, plus a chance for the model to restate the id or the parameters
wrongly.

The scope was set by the follow-up question, which is the more interesting half:
"is there a way to go it without compramising the auto job chaning mechanism."
Ending the turn after a submission is the obvious implementation and it would
have removed the agent's ability to draft a second job by itself. The way out
was to notice that two things which looked like one are independent: *when the
user sees the confirmation* and *whether the model's turn still runs*.
`_stream_resume` publishes each node's messages as the graph streams, so a node
can put the confirmation on screen immediately and the turn can still continue
afterwards. Only ending the turn early became conditional.

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

- [`trackers/2026-08-drafting-outranks-summaries.md`](trackers/2026-08-drafting-outranks-summaries.md)
  a finished job's summary no longer interrupts the calculation the user is
  setting up. 13 steps across five phases, closed 2026-08-27.
- [`trackers/2026-08-evaluation-battery-run-2.md`](trackers/2026-08-evaluation-battery-run-2.md)
  the second full run of the manuscript evaluation battery, from a mandatory
  card audit through execution to the two fixes it earned. 20 steps across six
  phases, closed 2026-08-27.

The rest of `trackers/` follows the same shape; each names its own scope in
its first paragraph.

---

## Phase 0: Establish that the turn really is pure narration

- [done] P0.1: The post-submission message identified as a model turn, not an app message
  evidence: docker exec nexusqc_dev-api-1 python3 -c "read_state(...)" → "the two confirmations in thread 02a748da are AIMessages following submit_draft's ToolMessage, near-identical apart from method and id; the ToolMessage itself carries the instruction 'tell the user it has started', so the model was paraphrasing a fixed string"
- [done] P0.2: Confirmed nothing downstream depends on that turn existing
  evidence: app/agent/graph.py → "messages[-1] is read in exactly one place in app/ and server/ (_should_continue); the client ends a turn on the turn_complete SSE event alone (frontend/src/lib/chatStore.ts), never on token count; draft_status is cleared inside _finish_submission's own Command, so the watcher's held-summary release does not depend on the agent node running"

- merged: 3cc168a

## Phase 1: A receipt the app can write a message from

- [done] P1.1: `pending_submissions`, a one-step handoff with an appending reducer
  evidence: app/agent/state.py → "written only by _finish_submission's success branch, read and cleared by the job_submitted node in the same superstep. Appending rather than LastValue for the reason _append_job_ids documents, and cleared through the {'__replace__': [...]} idiom _molecule_frames_reducer established rather than a new CLEAR_* sentinel"
- [done] P1.2: The receipt carries a label, not a spec
  evidence: app/agent/tools.py → "resolve_job_label is called in _finish_submission rather than in the node, so the node does no disk IO and the confirmation, the job list, the drawer heading and the download filenames all say the same thing. No params or spec ride along, since everything in the receipt is checkpointed on every later step"
- [done] P1.3: The tool's own message rewritten from an instruction into a record
  evidence: tests/backend/submit_01_confirmation.py → "26/26; the ToolMessage still contains id=<job_id> for e2e_12's grep and now closes with 'do not announce it again', which is what stops the next turn re-announcing the job and moving the narration one turn later instead of removing it"

- merged: 3cc168a

## Phase 2: Routing, keyed on tool call ids rather than prose

- [done] P2.1: `_submissions_this_step` recognises an all-submissions batch
  evidence: tests/backend/submit_01_confirmation.py → "requires every call in the batch to be answered and to carry a receipt; a mixed check_job_status + submit_draft batch, a rejection, and a stale receipt from an earlier batch all fall through to the model. No message prose is matched anywhere"
- [done] P2.2: The `job_submitted` node writes the confirmation inside the graph
  evidence: tests/backend/submit_01_confirmation.py → "the turn ends on an AIMessage carrying {'kind': 'job_submitted'}, positioned after the ToolMessage, with snapshot.next == () and the receipt consumed. Inside the graph specifically, because append_notice's update_state destroys an open approval card"
- [done] P2.3: Auto-chaining preserved through `follow_up_work`
  evidence: tests/backend/submit_01_confirmation.py → "with follow_up_work=True the stub model is called exactly once and the confirmation is still written first, so the user sees it before the chained turn runs; with it false the model is called zero times"

- merged: 3cc168a

## Phase 3: The behaviour is pinned and the neighbours still pass

- [done] P3.1: New contract test, with the model stubbed and counted
  evidence: tests/backend/submit_01_confirmation.py → "26/26 across four scenarios. The headline assertion is negative: a successful submission leaves the LLM call counter at zero"
- [done] P3.2: Adjacent suites re-run
  evidence: tests/backend/draft_01_summary_defer.py → "41/41"; tests/backend/agent_02_draft_flow.py → "35/35"; tests/backend/fail_01_notice_flow.py → "20/20"; tests/backend/approval_01_stale_card_clears.py → "6/6"
- [done] P3.3: The model is actually offered `follow_up_work`
  evidence: langchain_core.utils.function_calling.convert_to_openai_tool(submit_draft) → "the wire spec sent to the model carries exactly ['follow_up_work'], with state and tool_call_id correctly stripped as injected. Worth checking separately because the contract test hand-writes that argument into the tool call, so a schema that never offered it would still have passed 26/26 while chaining silently never fired"
- [done] P3.4: The evaluation harness no longer credits the model for app-written text
  evidence: tests/backend/model_compat.py → "said() and report_after() now skip AIMessages carrying a `notice`, which is what marks a message as app-authored. Without this the approval confirmation would have been scored as the model's own words in rsc_digital_discovery/evaluation/, silently rather than as a failing test"
- [done] P3.5: End-to-end latency measured before and after
  evidence: an in-process approve-to-turn-end timer over a 30-message conversation, run three times on each side of the merge → "before: 9.07s, 94.86s, 21.28s (median 21.28s). After: 0.11s, 0.08s, 0.10s (median 0.10s). The spread on the old numbers is the shared GPU, which is exactly why the median rather than any single run is the honest comparison"
- [done] P3.6: Confirmed in a real browser, which is where the change is visible
  evidence: tests/frontend/submit_02_instant_confirmation.spec.mjs → "9/9. The confirmation paints 1.31s after the Approve click, reads 'Started water SPHF/sto-3g (PYSCF). Job id 814ef55f05db.', carries no internal task identifier, and the composer re-enables, so the turn genuinely ended rather than merely looking finished"
- [done] P3.7: Full backend suite re-run against the rebuilt stack
  evidence: tests/run_backend.sh → "submit_01_confirmation.py 26/26 inside the suite run. Note the runner invokes a bare `python3` and sets no PYTHONPATH, so it must be given both or 39 scripts fail on `No module named 'app'` before executing a single check"

- merged: 8bba83b

## Incidental findings

Logged here rather than fixed, since neither is in this plan's scope.

- **A reducer channel's first-ever write bypasses its reducer.** Clearing a
  `draft_status` that was never set leaves the raw `CLEAR_DRAFT_STATUS`
  sentinel (`{'__cleared__': True}`) in state instead of `None`, because
  LangGraph stores the initial value for a channel without calling the reducer.
  Confirmed identical on unmodified `main`, so it predates this work. Harmless
  in production because `_draft_command` always stamps `draft_status` before a
  submission is possible, and `draft_hold_reason` reads `.get("stage")` which is
  absent from the sentinel either way. It bit the first draft of
  `submit_01_confirmation.py`, whose fixture seeded `job_draft` without going
  through the draft funnel. Worth knowing before anyone relies on a `CLEAR_*`
  sentinel on a channel that may be untouched.
- **`auto_job_name` runs the task label and the method together.** A ground
  state single point at HF comes out as `water SPHF/sto-3g (PYSCF)`, because
  `naming.py` builds its tail as `f"{task_label}{detail}"` with no separator,
  giving `SP` + `HF`. Cosmetic, pre-existing, and now more visible because the
  submission confirmation puts that label in front of the user rather than
  leaving it in the job list. Deliberately not fixed here: `resolve_job_label`
  is the shared definition behind the job list, the drawer heading and every
  download filename, so changing it changes filenames too, and the standing
  filename convention is not something to alter as a side effect of a
  formatting tidy-up.
- **`tests/run_backend.sh` depends on ambient environment it does not set.**
  It invokes a bare `python3` and never exports `PYTHONPATH`, so on a host
  where the conda environment is not already active it reports most of the
  suite as failing with `ModuleNotFoundError: No module named 'app'`. Only the
  scripts that do their own `sys.path.insert` survive. That is indistinguishable
  from a real regression at a glance, which makes it worth fixing in the runner
  rather than in each caller's memory.
- **Two `submit_draft` calls in one batch may be unreachable.** `interrupt()`
  inside `ToolNode` aborts the whole node without committing writes, so on
  resume the node re-runs from the top, replaying the original tool arguments
  while losing uncommitted state writes. The second `interrupt()` would pause
  again and the first `submit()` may run twice. The plural handling in
  `_submission_text` is therefore defensive only. If the double-submit hazard is
  real it predates this change and deserves its own tracker.
