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

## Open

- **Making defaults visible provokes useful questions that condition A scores
  as failures.** Run 2's E-04-verbose: the prompt asks where formaldehyde
  absorbs, the agent drafts the TDDFT job correctly, then notices the
  applied-defaults block says oscillator strengths are off and asks whether
  to turn them on -- which is exactly the right question, since intensities
  are what "where does it absorb" means. No card was raised inside the
  trial, so it scored `gave-up`.

  Nothing here is a defect in the app: the defaults block (TRACKER P2.2 /
  P2B.3) is doing what it was built for, and the agent read it. It is a
  finding about the evaluation design, for the next revision of
  EVALUATION.md rather than mid-run: condition A's rule that any question on
  a complete prompt is over-elicitation predates the defaults block, and
  `gave-up` is the wrong label for an agent that asked a well-judged
  question. A separate label, or a rule that a question naming a defaulted
  parameter is allowed once, would measure this honestly. Do not change the
  card while the run is in progress.

- **The no-virtual-space guard is wired into the wrong builder and never
  fires for an ordinary single point.** `caspt2_virtual_space_problem` is
  called from `_build_scan_spec_or_error` in `app/agent/tools.py` -- the
  pes_1d/interp_pes path -- so it only ever runs for a scan. A plain CASPT2
  single point, which is the case it was written for (the A-19/A-20 trials
  that cost run 1 six write-offs were single points), goes straight to an
  approval card.

  Caught by run 2's C-11 on its first live trial: `missed-refusal`, the
  request was carded instead of declined, with exactly the draft the guard
  is meant to stop (`caspt2`/`bagel`/`single_point/gs`, STO-3G, CAS(4,4)).
  The guard function itself is correct and returns the right message when
  called; only its placement is wrong. Move the check into
  `_build_spec_or_error` so it covers every task, and keep the scan copy or
  hoist it to cover both.

  Worth noting how this survived until now: the fix was verified by calling
  `caspt2_virtual_space_problem` directly, which passes, and the session
  that wrote it recorded that it had been wired into `_build_spec_or_error`.
  Only an end-to-end probe through the agent could tell the difference.

- **A functional spelling put in the `method` field is dropped rather than
  carried across.** Found by run 2's B-10, which failed all three trials.
  Asked for "a B3LYP-D3 single point", the model sets
  `method: "B3LYP-D3"`; the app correctly answers that the method must be
  `dft`, and the model then sets `functional: "B3LYP"` -- the dispersion
  correction is gone, and the card's note reads "Wrote the functional as
  B3LYP, which is how ORCA spells it", which is true of what it was handed
  and misleading about what was asked for.

  `resolve_functional("B3LYP-D3", "orca")` is correct and returns
  `B3LYP D3BJ` with the D3ZERO note, so nothing is wrong below the agent.
  What is missing is the hand-off: when a rejected `method` value parses as
  a functional, offer it for the functional field instead of discarding it.
  The user asked for dispersion and would have approved a card without it.

- **Prose guards on invented parameters hold, but not reliably.** TRACKER
  Phase 2B added "ONLY set this when the user has said..." to thirteen
  required parameters after run 1 caught the model inventing a scan
  coordinate. Run 2 measured the same probe three times: it held twice and
  failed once. B-06 t3's prompt named no atoms, and the model wrote
  `coordinate: {atoms: [1, 2], type: bond}` unasked, straight onto an
  approval card.

  EVALUATION.md predicted this ("a recurrence is a finding about the
  prose-guard approach"), so it is a result rather than a surprise: an
  instruction in a docstring is a probabilistic guard, and the parameters
  where a wrong value is silently plausible want a structural one. Note the
  same run shows the guards are not useless -- 2 of 3, and the sibling probe
  B-05 (n_states) passed all three.

- **The no-virtual-space guard is CASPT2-only, but the failure is not.**
  `app/chemistry/jobs/validate.py`'s `caspt2_virtual_space_problem` is
  consulted only for CASPT2, because CASPT2 is where an empty virtual block
  was first found to break BAGEL. Measured 2026-08-26: BAGEL **CASSCF** on
  water/STO-3G with a (4,4) active space -- 7 basis functions, 3 closed plus 4
  active, zero virtual -- fills `bagel.out` with `Intel oneMKL ERROR:
  Parameter 9 was incorrect on entry to cblas_dgemm` and never terminates.
  Not a clean failure: no error status, no result, the job just runs. The
  identical calculation in cc-pVDZ (17 virtual orbitals) completed in 7.9
  seconds with no MKL errors on the same saturated host, so the empty virtual
  block is the cause rather than this host's BAGEL.

  A user asking for CASSCF in a minimal basis therefore gets an approval card,
  approves it, and waits forever. Widen the guard to every multireference
  method on BAGEL. Whether PySCF and ORCA survive a zero-dimensional virtual
  block is untested; check before widening further.

  Found while building the run-2 card audit, during the system freeze, so it
  is recorded here rather than fixed. It also makes the case that the guard's
  message should stop saying "CASPT2 is a correction into the virtual space"
  when the same arithmetic is being reported for a CASSCF request.

- **The evaluation battery's task cards have never been audited against the
  app, and it shows.** Before the battery is run again, check every card in
  `rsc_digital_discovery/evaluation/cards/` against what the app can actually
  do. This is registry lookups, not GPU time, and it is the difference between
  one clean run and the three interrupted ones of 2026-08-25.

  Five cards encoded an assumption about the app that turned out to be false,
  and every one was discovered the same way -- by a trial failing, mid-run,
  after which the run had to be restarted:

  - **A-20** asked for "three CASPT2 excited states", which is ambiguous under
    this app's convention that `n_states` counts state-averaged roots
    *including* the ground state. The agent spotted it and asked; the card
    scored that as a failure.
  - **C-06** named BAGEL as the engine that cannot report oscillator strengths
    for CASSCF. `get_caps("bagel", "casscf").has("osc_strengths")` is true; it
    is PySCF that cannot. The same card also expected a refusal where the app
    is designed to warn and proceed.
  - **C-07** checked for a new plot by counting the list, and a plot the agent
    revises gains a version on the existing record rather than a row.
  - **A-19/A-20** requested CASPT2 on water/STO-3G with a (4,4) active space,
    which uses all seven basis functions and leaves no virtual space at all.
    Six trials were excluded as engine-environment failures on a false premise.
  - **B-10** was written around the claim that ORCA's bare `D3` means zero
    damping. It means Becke-Johnson.

  The pattern is worth stating plainly, because it will recur: the cards were
  written from `EVALUATION.md` before anything had been run, and `EVALUATION.md`
  was written from the design rather than from the code. An evaluation needs
  testing as much as the system does. Two of these are corrections to
  `EVALUATION.md` itself, already made.

  Suggested shape: for each card, resolve its engine/method/task through
  `registry2` and confirm the capability it assumes; check every `quote.paths`
  against a real `result.json` for that job type; and re-read each pass
  criterion against what the app is *designed* to do, not what seems
  reasonable. Then one run, start to finish, on one commit.

## Unverified deployment surface

Resolved 2026-08-26 in
[`trackers/2026-08-clearing-the-backlog.md`](trackers/2026-08-clearing-the-backlog.md)'s
Phase 4. The public `:443` listener and its kill switch were removed rather
than verified -- the port had been commented out long enough that nothing had
ever reached it, so the controls around it were guarding a door that was not
in the wall. What multi-host operation, a real certificate and multi-operator
load would each require is now written down in `DEPLOYMENT.md` instead of
carried here as an open question.

Found and fixed in the same pass (not backlog items, noted here only so the
next pass doesn't re-discover them):

- **`cas_reco/autocas` refused the whole recommendation whenever the AVAS
  pilot space couldn't host the requested `n_states`.**
  `tests/e2e/e2e_08_job_matrix.py`'s M26 (default request: 3 states, default
  `O 2p` AVAS labels on water/STO-3G) failed live with "The AVAS pilot space
  for this molecule (6e,3o) can host at most 1 many-electron configuration(s),
  fewer than the 3 states requested." Confirmed against the real AVAS method
  (Sayfutyarova, Sun, Chan & Knizia, *JCTC* 2017) and against PySCF's own
  `avas.avas()` call site (`app/chemistry/jobs/pyscf_runner.py`): AVAS is a
  one-electron orbital-selection method with no notion of electronic states
  at all, so gating the recommendation on `n_states` was never something the
  underlying algorithm asked for. It was this app's own guard (`F-020`,
  added after a real crash) doing double duty as both a genuine crash
  preventer and an upfront refusal. Split the two: the early pilot-space
  check is now informational only (the pipeline always runs and always
  produces a recommendation and its entropy plot), and the late guard,
  reached only after the existing entropy-ranked widening already tried to
  make room. Now clamps `n_states` down to what the recommended space can
  actually host and runs the final CASSCF with that many states, instead of
  refusing outright. `summary` carries `n_states_requested` and
  `n_states_clamped_note` alongside `n_states` so the clamp is visible to the
  caller, not just the log. Verified live: the exact M26 case now succeeds,
  clamped to 1 state, `converged: True`; an unclamped request still returns
  `n_states_clamped_note: None`. M26's fixture is left as-is. It now
  regression-tests the clamp path rather than testing a dead end.

- BAGEL had no runner wired up at all for a plain HF `single_point/gs`
  energy job, despite `capabilities.py` declaring it supported. Nothing had
  run that exact combination through the full agent pipeline before this
  pass did. Fixed in commit `03ddb12`.
- `tests/e2e/e2e_00_preflight.py`'s G2a/G2b hardcoded a stale `N_CORES`
  expectation of `8`; both `docker-compose.yml` and `app/config.py`'s real
  default were already `4` and agreed with each other, unreconciled since
  Phase 3/4's fair-scheduler work. Fixed as a one-line test correction; the
  whole preflight script is 16/16 again.
