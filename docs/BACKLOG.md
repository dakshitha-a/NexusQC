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

**The Deployment admin section loses three checks under a four-suite load.**
`tests/frontend/deploy_05_deployment_section.spec.mjs` reported 9 of 12 in the
Gate 3 frontend run, all three failures downstream of one wait: a job staged
directly into `JOBS_DIR` never appeared in the "Who is working right now" table
within twenty seconds, and the two checks that read the same page snapshot
afterwards found neither the update controls nor the `scripts/update.sh` line.
Run alone against the same stack at the same commit the script passes 13 of 13,
twice. Ruled out: the app code, which did not change between the two runs, and
a global logout on a failed poll, which `lib/api.ts:222-247` does not do (only a
401, and only outside `/api/auth/me`). Not ruled out: what the page actually
looked like, because the log recorded only that an assertion did not hold. The
script now prints a `pageState()` line naming which of the section, the
activity table, the update controls, the admin panel and the login screen were
on screen, plus the last failing `/api/` responses. **Next experiment:** run
`deploy_05` alone with `QC_AGENT_TEST_DEPLOY05_WAIT_MS` left at its default
while a synthetic load drives the same stack (the four suites concurrently is
what produced it, load average 39 with nginx returning intermittent 502s), and
read the `pageState()` line. Full triage in
`docs/evaluation/2026-09-app-review/evidence/fix/P6.5/README.md`.

**The approval resume no longer shows a tool chip.**
`tests/e2e/e2e_04_harness_gate.py`'s H12 asserts that resuming a turn after the
user clicks Approve publishes an `agent_step` event, and it did: at the Phase 1
gate it recorded `steps=[('update_job_draft', 'finished')]`. At the final gate
it recorded `steps=[]`. This is a consequence of R-101 rather than a break in
the streaming path. The card used to be raised by `submit_draft`; it is now
raised inside `update_job_draft`, which returns a `Command` when it resumes, so
the tools node in `_stream_resume`'s payload carries no message to publish.
Token deltas still stream, so the screen is not blank after the click, which is
what F-008 was about. What is lost is the chip naming the tool.

Next experiment: drive one approval on a quiet stack with the raw stream
payloads printed, and see whether the resumed `update_job_draft` appears under
a node name `_stream_resume` does not handle. If it does, publishing an
`agent_step` for it is a two-line change; if it does not, H12 should be
retired and say why.

**The admin console's purge controls cannot be found by their own spec.**
`tests/frontend/fe_sec_02_adminpanel_silent_failure.spec.mjs` times out
waiting for `button:has-text("Purge")` after the admin console opens. It was
failing this way at the Phase 1 gate too, so it predates every change in the
fix phase, and the console was reorganised in the UI pass before that.

Next experiment: open the admin console in a browser and read what the purge
controls are actually called now; the selector is almost certainly describing a
button that was renamed, and if it is not, the controls are genuinely missing
and that is a real gap in a destructive surface.

**A scrubber drag costs three cube renders, not one.**
`tests/e2e/ui/ui_09_orbital_and_mode_panels.spec.mjs` reports "3 during the
drag, 4 in total" against a bound of one. Rendering an orbital cube is the
heaviest per-request allocation the app makes on a read path, so a drag across
five orbitals asking for four of them is real work nobody asked for. Failing
since the review.

Next experiment: read what debounces the scrubber in `JobDetailDrawer`, and
whether the requests are fired on `input` rather than on `change` or after a
settle.

**Two drawer sections render where they should be gated off.**
`ui_01_shell_and_chat` and `ui_02_approval_jobs_drawer` both report that an HF
job's drawer shows "Molecular orbitals" and a DFT job's shows "Optimization
energy", and that a job with no engine exposes "View raw input". Failing since
the review.

Next experiment: compare each section's render condition in
`JobDetailDrawer.tsx` against what the job summaries for those cells actually
carry. A section keyed on a summary field that is present but empty would
explain all three at once.

**`e2e_11`'s keyword correction returns None.** C2 reports `method=None` for an
RHF request and C3 reports no candidate menu for a mistyped functional or
basis. The review recorded this and left it open: "whether keyword suggestion
regressed or the assertion is stale".

Next experiment: call `keyword_suggest` directly with `b3lp` and with `ccpvdz`
and see whether it returns candidates. That splits the two possibilities in one
step and needs no browser.

**`e2e_12`'s source-geometry draft never reaches ready.** The draft correctly
carries `source_geometry_job_id` and never calls `set_geometry`, which is the
half the check is about, but `reached_ready=False`.

Next experiment: run `validate_draft` on that exact draft and read what it says
is missing. If it wants a molecule the source job already supplies, the
resolution path is not consulting the source job.

**`e2e_17`'s L9b: no unprompted summary after a logout.** A job that completes
while the user is logged out injects its notice but produces no assistant
reply, so there is nothing waiting in the conversation on return. L1 to L8, the
leave-and-return core, all pass. Recorded in the review and unchanged.

Next experiment: check whether `invoke_turn_if_idle` refuses because the thread
has no live session, and if so whether the notice should queue the turn for the
next time the user opens the thread instead.

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
