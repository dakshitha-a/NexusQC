# P5.4, R-036 and R-037: the context budget and an attached job

`tests/backend/budget_01_attached_job_trim.py`, before and after, in this
directory. Before: 3 of 8 checks pass. After: 15 of 15.

## R-037: the trim could not shrink an attached job

`_shed_pinned_results` is the last thing `_trim_history` tries. With every
older message already given up, it blanks the current turn's results in place,
leaving a marker that tells the model to re-fetch, rather than a hole the model
would fill with an invented value. That behaviour exists because of a real
incident: four job results were fetched in one turn, two were dropped by
position, the model could not tell anything was missing, and it reasoned onward
from an active space of (6e,6o) for a 12-electron, 9-orbital job.

It could only shrink `ToolMessage`s. An attached job's results are not a
ToolMessage: `server/routes/chat.py` builds a synthetic `HumanMessage` carrying
`job_context_summary(job_id)`, about 20,000 characters. Attach three jobs to
one message and that is three such blocks in one pinned message that nothing
could touch, so the window stayed over budget with nothing left to give and the
trim ended by logging that it could not help. `docs/MODEL_CONTEXT_BUDGET.md`
leaves open the question "can the budget be exceeded anyway by one message";
this was the path that made the answer yes.

Measured by the test: three attached jobs of the size above come to about
34,000 tokens. Against a 500-token budget the trim now brings the window to
about 300 tokens, keeps all three messages in place (deleting them would break
the call/response pairing `_drop_orphan_tool_messages` protects), and each
marker names its own job id and the tool that fetches it back. The plain
ToolMessage path is checked in the same run and is unchanged.

The 500-token budget is chosen to be above what three replacement markers
themselves cost, around a hundred tokens each, and far below what the summaries
cost. A budget below the markers' own total would be asking the trim to do
something impossible, and failing that is correct rather than a defect.

## R-036: the pointer told the model something it could not check

The second and later times a job is attached, its summary is replaced by a
one-line pointer, which is what keeps a re-sent attachment from costing ten
thousand tokens again. The pointer said the results were "already in this
conversation above". `_already_attached_job_ids` scans the full checkpointed
history; the prompt the model actually sees has been trimmed to a budget. On a
long conversation the summary being pointed at can therefore have been trimmed
away, and the model has no way to check the claim and every reason to believe
it, so it answers from what it can see rather than saying it cannot see it.

The pointer now says the results were given earlier, says the conversation may
have been trimmed, and names `check_job_status(job_id=...)` as the way to read
them again. 378 characters, against roughly 20,000 for the summary it replaces.

## One definition of the marker

Both the route that writes the attached-job message and the graph that
recognises it need the same prefix. It lives in `app/agent/state.py` as
`JOB_ATTACH_MARKER`, imported by both, rather than as a literal in one and a
constant in the other: the route layer importing the graph is normal, the graph
importing a route is not.
