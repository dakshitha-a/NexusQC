# P6.5: the three deploy_05 failures the gate did not triage

## Why this step exists at all

`tests/frontend/deploy_05_deployment_section.spec.mjs` printed three `[FAIL]`
lines in the Gate 3 frontend run and still exited 0, because it exits on the
suite's aggregate rather than per check. The gate's own list of failed specs is
built from exit codes, so the script does not appear on it, and the P6.2 README
section titled "What is still failing" was written from that list. It therefore
claimed a completeness it did not have. This step closes that hole.

The three lines, verbatim from
`evidence/fix/P6.2/frontend-run.log:126-128`:

```
[FAIL] a running job appears in the table without reloading the page -- the section never showed the staged job within 20s
[FAIL] the update controls render either way
[FAIL] with no runner, the panel names the host command instead of offering a button -- an Apply button was offered with nothing on the host to answer it
```

Nine of the twelve checks passed, including every check that reads the
deployment's commit and the activity counters. So the section mounted and drew
correctly when the script first reached it.

## What the script asserts, so the three lines can be read

The script drives the admin console's Deployment section in chromium as
`qatest_admin`. Check 9 stages a job by writing `spec.json` and a `running`
`status.json` straight into `JOBS_DIR` and recording ownership against the
admin, then waits for the words `1 running` to appear in the "Who is working
right now" table without reloading the page. The section polls
`/api/admin/deployment` and `/api/admin/activity` every five seconds, so the
wait is the assertion that the polling works. Checks 11 and 12 then read
`page.textContent("body")` once and look for the word `Updating` (the update
controls' heading) and for the string `scripts/update.sh`, which is what
`DeployControls.tsx:102-113` renders when no host runner is installed. This
deployment has no runner, so that is the branch under test.

Checks 11 and 12 read the same page snapshot that check 9 was waiting on. That
is why all three fail together: they are one observation, not three.

## The measurement

The same script, unchanged, run alone against the same stack at commit
`856cca6`:

```
QC_AGENT_TEST_BASE_URL=https://127.0.0.1:8444 \
  node tests/frontend/deploy_05_deployment_section.spec.mjs
```

**13 of 13 checks passed** (`deploy_05-unchanged-alone.log`, taken with the
script exactly as the gate ran it, before any of the changes below). Thirteen
rather than the
gate's twelve because check 10, "and the idle message is gone while somebody
would be interrupted", only runs when check 9 saw the staged row, so a failure
at 9 removes a check from the denominator as well as adding one to the failures.
That is the whole difference between `9/12` and `13/13`: four checks, all
downstream of one twenty-second wait.

That run was at 02:44, about eighty minutes after the gate's frontend suite
started, on the same commit and the same stack with nothing else driving it.

The difference between the two runs is the machine, not the code. The gate ran
all four suites concurrently: `frontend-run.log`'s own header records
`load average: 39.21` at `01:22:53`, and the P0.3 health probe, which logs only
when a probe is slow or non-200, recorded `code=502` from nginx at `01:15:37`
and again at `01:58:44` with `elapsed=3.05s`, on either side of the frontend
suite. A poll that comes back 502 leaves the section holding its previous data,
and twenty seconds is three or four polls.

What this does not establish is the exact mechanism behind checks 11 and 12.
A 502 on the activity poll explains check 9 directly. It does not obviously
explain the word `Updating` being absent from the body text, because
`DeploymentSection.tsx:206` renders `DeployControls` unconditionally and
`DeployControls.tsx:102` falls into the no-runner branch when `deployment` is
undefined. So the honest reading is that the page was in some state the log did
not record, and the fix is to make the log record it.

## What changed in the script

No app code changed. `deploy_05` gained three things:

1. **A `pageState()` probe.** On any of the three failures the message now
   carries whether the section, the activity table, the update controls, the
   admin panel and the login screen are each on screen, plus the last four
   failing `/api/` responses and the last two console errors. The next time
   this happens the log says what the page was, rather than leaving the reader
   to infer it a month later.
2. **A sixty-second budget instead of twenty** for the staged-job wait,
   overridable with `QC_AGENT_TEST_DEPLOY05_WAIT_MS`. The poll needs five
   seconds when the host is idle. The budget exists for the case where it is
   not, and a longer budget costs nothing when the poll works.
3. **Check 12 tells its two failures apart.** It was one condition with one
   message, so a missing `scripts/update.sh` string reported "an Apply button
   was offered with nothing on the host to answer it", which is the opposite
   defect and was not what happened. The two are now reported separately, and
   only the Apply-button case keeps that sentence.

## Verification

- `deploy_05-unchanged-alone.log`: 13/13 with the script exactly as the gate
  ran it, at `856cca6`. This is the measurement the triage above rests on.
- `deploy_05-alone.log`: 13/13 again with the patched script at the same
  commit, which is what says the changes below did not break it.
- `deploy_05-negative-control.log`: the same script with
  `QC_AGENT_TEST_DEPLOY05_WAIT_MS=1`, so the poll cannot possibly land inside
  the window. 11/12, and the one failure now reads

  ```
  [FAIL] a running job appears in the table without reloading the page -- no '1 running' row within 1ms -- section=yes activity=yes controls=yes admin-panel=yes login-screen=no failed=[404 /api/plots/...] console=[Failed to load resource: ... 404 ()]
  ```

  which is the diagnostic doing its job: it says the section and the controls
  were both on screen, so this failure is the wait and nothing else. Had the
  gate's run carried this line, the triage above would have taken a minute
  instead of an hour.

  `login-screen=no` is correct here rather than an unwired probe. The selector
  is `[data-testid="auth-submit"]`, the submit button
  `LoginScreen.tsx:194-200` renders unconditionally inside the auth form, and
  five other specs in `tests/frontend/` already drive the login screen through
  it. The session was logged in, so its absence is the truthful answer.

## One thing the diagnostic turned up, which is not a defect

The negative control's network capture shows a 404 on
`/api/plots/<id>/versions/v2.png`. That plot was deleted; `data/plots` holds
three empty per-user directories and `data/projects.json` is an empty list. The
reference survives in a conversation transcript, which is correct behaviour:
`api.ts:396-400` pins each message to the plot version it actually drew so that
editing a plot cannot retroactively change an older message. The frontend
already handles the missing file. `MessageBubble.tsx:100-113`'s
`PlotArtifactCard` carries an `onError` handler that swaps the image for the
sentence "Plot image failed to load." Nothing to fix.

## What is left

`deploy_05` under concurrent load has not been reproduced deliberately, only
observed once. The next experiment is named in `docs/BACKLOG.md`: run
`deploy_05` alone while a synthetic load drives the same stack, and read the
`pageState()` line the patched script now prints.
