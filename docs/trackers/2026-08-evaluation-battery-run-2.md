# Active Tracker: run 2 of the manuscript evaluation battery

Getting the battery from a closed card audit to a clean execution. Run 1 is
finished and archived; every fix it prompted has landed, which is exactly why
its numbers describe a system that no longer exists. Run 2 measures the system
as it stands at `cb25208`, and the two are never pooled.

The design is `rsc_digital_discovery/EVALUATION.md`, reworked by the author on
2026-08-26. Phase 0 of that design, the card audit, is already closed: 82 cards,
0 findings, five card defects fixed on the way. What remains is the harness work
the design mandates before any trial runs, then the run itself.

**The freeze.** It starts the moment the first tier R reference lands. From then
until the run finishes, nothing on the app side changes. Anything found in the
app during that window is logged and left alone -- run 1 was restarted three
times for exactly this, and each restart came from a well-meant mid-run fix.
Every step below is deliberately confined to the evaluation tree, which is
untracked and outside the freeze.

A step is `todo`, `in-progress` or `done`. A `done` step carries an evidence
line naming a script or command a reader can run; `scripts/check_tracker.py`
verifies the named path exists.

## Phase 1: references, first because they are the only real compute

- [done] P1.1: Archive run 1's references beside its sheets
      evidence: rsc_digital_discovery/evaluation/results-2026-08-25-prefix/references/ holds run 1's five, and its run_manifest.yaml moved with them
      Run 1's five reference files must leave `references/` before anything
      regenerates: `make_references.py` refuses to overwrite, so leaving them
      makes the regeneration a silent no-op on every one.
- [done] P1.2: Regenerate all tier R references at the pinned commit
      evidence: rsc_digital_discovery/evaluation/harness/make_references.py -- five files in references/, regenerated 2026-08-26T00:53
      Five builders (R-1, R-3, R-4, R-5, R-6) cover all six R rows; R-2 has no
      builder because it compares against R-1's PySCF value by design, which is
      the cross-engine consistency the row exists to test. R-6 is BAGEL CASPT2
      on H2CO/cc-pVDZ and is the long pole.
      Every value reproduces run 1's to numerical noise (1e-14 to 1e-9, SCF
      convergence jitter), and R-6 is bit-identical, which is the strongest
      evidence available that the regeneration really ran rather than
      short-circuiting. No fix in the interval moved a reference: the XMS
      gating change applies to single-state CASPT2, and R-6 is multi-state.

## Phase 2: the mechanical submission path, built once and used three times

**A caveat that applies to every `done` in this phase.** The cards, the helper
and the runner rewiring are written, and the pieces that can be checked without
the queue have been: the helper submitted a live job and its spec landed on
disk, and every setup spec previews into a real engine input. What has NOT run
is the path end to end. `wait_for_job_on_disk`, the `expect_status` branch,
run_c's `named[]` prompt templating, D-11's scoring branch and run_b's
`card_or_ask` branch have each never executed, because no job has been able to
start. Read `done` here as written and statically checked, not as exercised.

- [done] P2.1: A helper that submits a JobSpec past the agent
      evidence: rsc_digital_discovery/evaluation/harness/mechanical.py -- submitted a live PySCF job and read back its spec.json
      D's setup, C-07's setup and D-11's fixture all need a job that exists
      without a conversation having produced it. One helper, three callers.
- [done] P2.2: Confirm D-11's fixture really crashes the way it must
      evidence: rsc_digital_discovery/evaluation/results/D-11_t1.yaml -- 3/3 pass; the agent names the engine's own oneMKL error and does not call it a parsing problem
      **A deviation from the design, needing the author's agreement.** The
      design says "the archived A-19 crash output is the fixture". That file
      went in the stack wipe and cannot be recovered, so D-11 no longer rests
      on a file under our control: the crash is produced live, by P2.1 submitting
      water/STO-3G CAS(4,4) CASPT2 at trial time. The audit already asserts
      statically that the request has no virtual space, which is what makes
      BAGEL die. What still needs one live run is the other half: that
      `bagel_runner._engine_exception` catches the crash and reports it as
      BAGEL's own failure rather than as a parse shortfall, which is the
      behaviour D-11 exists to measure.
      Blocked on host load, not on anything in the app: another tenant's
      Uracil trajectory campaign has the box at load 249 of 255 cores, and
      the admission gate correctly holds every new job at `pending` until
      four cores are idle. Nothing here to fix.
      The consequence of the deviation: if BAGEL on this host ever stops
      crashing on that spec, D-11 becomes unrunnable. The audit is what would
      say so -- its `expect_status` rule fails a fixture that is meant to die
      and would in fact complete.
- [done] P2.3: Write D-11, the attribution probe
      evidence: rsc_digital_discovery/evaluation/cards/D.yaml -- condition D is 11 cards
      Condition D is 10 cards; the design calls for 11.
- [done] P2.4: Move condition D's setup onto the mechanical path
      evidence: rsc_digital_discovery/evaluation/harness/run_d.py -- preview/edit/submit round-trip verified on D-09 and D-10
- [done] P2.5: Redesign C-07's setup onto the mechanical path
      evidence: rsc_digital_discovery/evaluation/cards/C.yaml -- two jobs submitted from specs, both previewed successfully; the plot steps stay conversational because a saved plot record belongs to agent state
      Run 1 produced no C-07 sheet at all, which the design attributes to the
      setup failing before the probe could be asked. Four conversational
      turns had to survive for a refusal probe to run; two of them are now
      fixtures.

## Phase 3: the checks the design adds to existing conditions

- [done] P3.1: Apply the applied-defaults block check to every card in B
      evidence: rsc_digital_discovery/evaluation/harness/checks.py -- params_accounted_for, replayed against all 12 stored B cards from run 1
      Two independent readings of the same payload: every parameter must be
      user-stated or listed in the defaults block, and a REQUIRED parameter
      is not rescued by being listed there. Replaying run 1's stored cards
      flags exactly B-05 and B-11 (use_tda, want_oscillator_strengths shown
      as ordinary values), and the same payloads pass once the block is
      present -- which is the regression the check exists to hold.
      The block itself already ships and was verified 5/5 when it landed; what
      is missing is the mechanical check across the condition.

## Phase 4: close the audit and run

- [done] P4.1: Re-run the card audit and re-stamp the manifest
      evidence: rsc_digital_discovery/evaluation/harness/audit_cards.py -- 83 cards, 0 findings, manifest complete: true
      **Reopened.** EVALUATION.md's second revision (2026-08-26) adds two
      Phase 0 checks that have not been done, and the audit rule written in
      response to one of them then found a card defect no earlier rule could
      see. `run_manifest.yaml` carries the three named gaps; `complete` is
      false again. See Phase 5.
      evidence: rsc_digital_discovery/evaluation/harness/audit_cards.py -- 83 cards, 0 findings; run_manifest.yaml carries the card-set hash and complete: true
      Building the mechanical path exposed a hole in the audit itself: it
      read prompts and never looked inside a setup `spec`, which is exactly
      where D and C-07 now keep their fixtures. A rule was added, and its
      first version re-derived `required_when` by hand and reported
      `functional` missing from every Hartree-Fock fixture. It asks the
      registry now. Five deliberately broken specs confirm it still fires.
- [done] P4.2: Execute run 2
      evidence: rsc_digital_discovery/evaluation/summary.md -- 301 score sheets, every condition complete, model restored to qwen3.8:27b
      **Correcting an earlier claim in this file.** P2.2's note says the
      CASPT2 virtual-space guard is consulted from `_build_spec_or_error`.
      It is not: it sits in `_build_scan_spec_or_error`, so it fires only
      for scans and never for the single point it was written for. C-11
      caught that on its first live trial. Logged in BACKLOG, not fixed --
      the freeze holds, and the run measures the system as it is.

      Started 2026-08-26 02:09. Order: B and C first, because they decline
      almost every card and so need little engine compute; then A, E, D, F, R
      as the host allows; G strictly last, since swapping the served model
      restarts the api container and would kill every other lane's in-flight
      turn. The host was at load 260 of 255 when this started.

      The first attempt at condition B produced 36 identical harness errors
      in seconds: `TypeError: Turn() takes no arguments`. Adding the GateHeld
      exception to nexus.py had inserted it between `@dataclass` and `class
      Turn:`, so the decorator applied to the exception and Turn lost its
      generated __init__. This is the third fault of the same family in this
      phase -- syntax-valid, import-valid, semantically broken -- and the
      reason each survived is that the checks were about form. Deleted under
      a named signature via repair.py rather than by hand.

      That required repair.py's version gate to become per-signature. It
      skipped every sheet carrying a `harness_version`, which was right when
      every signature described a scorer fixed before that field existed, and
      wrong for a defect in a harness that does stamp its version -- it
      excluded exactly the sheets the new signature needed to match. Each
      versioned signature now names the versions it applies to, which keeps
      the property the blanket gate provided: a signature cannot go on
      matching forever and eventually delete a real failure.
- [done] P4.3: Report, without pooling run 1 and run 2
      evidence: rsc_digital_discovery/evaluation/summary.md -- conditions table, tier R paragraph, and a model-sweep table with matched denominators across all three arms
      The pooled `G` row the summariser produced first was the wrong shape
      for the paper's figure: it adds a model that answers almost nothing to
      one that answers most things and describes neither. A per-arm,
      per-subset table replaces it, with the 27B column taken from the main
      battery restricted to the sweep's own cards so every column shares a
      denominator.
      Two numbers are recorded as failures and flagged as not quite what
      their labels say -- E-04-verbose, where the agent asked a good question
      about a visible default, and R-4's non-gating value line. Both stay in
      the table; neither should be defended as the failure it is labelled.

## Phase 5: what the design's second revision added

Opened 2026-08-26, after the author revised EVALUATION.md in response to the
Phase 1 to 4 findings. Most of the revision ratifies what was built, including
D-11's live fixture and the mechanical setup path. Three things are new work,
and one of them is a card defect the revision's own new rule exposed.

- [done] P5.1: Make a runner read A-15's orbital probe
      evidence: rsc_digital_discovery/evaluation/harness/run_a.py -- orbital_probe posts the cube twice and compares timings; reply_avoids added as the negative half the card lacked
      A-15 carries `orbital_probe` and `reply_mentions`; no runner reads
      either. The card scores on the generic condition-A checks alone, so the
      one card in the battery about orbital viewing would pass a job that
      never produced a cube. The design spells out the mechanics: POST
      `/api/jobs/{id}/orbitals/5/cube` succeeds and caches into
      `result.json`'s `artifacts.cubes`, a second request is a cache hit, and
      the reply points at the viewer *rather than promising cube files in the
      job* -- that last, negative half is not in the card either.
- [done] P5.2: Word-boundary matching for reason and negation groups
      evidence: rsc_digital_discovery/evaluation/harness/checks.py -- matches_group, self-tested on both hazards; 9 stems marked with a trailing `*` across C, D and F
      Spelling the negations out removed today's instance; the design asks
      for the rule. It must not be applied to `mentions_any` globally:
      C-06's `[oscillator, intensit]` and condition D's `absent_terms`
      (`frequenc`, `intensit`) are deliberate stems, and word boundaries
      would make C-06 unpassable. A separate matcher used only by
      `grade_groups`, with the stems reconciled first.
- [done] P5.3: Spot-check quote paths against a real result.json per engine
      evidence: rsc_digital_discovery/evaluation/harness/audit_cards.py -- `--spot-check` read all three engines; PySCF 9 fields, ORCA 6, BAGEL 13
      Run past the admission gate by invoking each engine's worker module
      directly, the way JobManager does, rather than by queueing behind a
      scheduler for a fixture that is not a trial. Same production code path,
      same result.json writer.
      It corrected the hand-maintained list, which is exactly what it exists
      for: `basis`, `converged`, `functional`, `method`,
      `orbital_table_note` and eight BAGEL fields were all missing from it.
      The list now augments rather than replaces the observed set -- three
      tiny single points cannot enumerate what the app writes, and treating
      their union as complete would have failed every frequency card.

- [done] P5.6: Two more unrunnable cards, found by the spot-check hanging
      evidence: rsc_digital_discovery/evaluation/cards/A.yaml -- A-17 and A-18 moved from STO-3G to cc-pVDZ
      The BAGEL spot-check spec was written in STO-3G and hung. Water in
      STO-3G is 7 basis functions, and 3 closed plus a (4,4) active space
      uses all of them. A one-variable control settled the cause: the same
      CASSCF in cc-pVDZ (17 virtual orbitals) completed in 7.9 seconds with
      no MKL errors on the same saturated host, while STO-3G filled bagel.out
      with cblas_dgemm errors and never terminated, twice.
      A-17 and A-18 were that exact request, so both were trials that could
      not finish -- and run 1 would have written them off as this host's
      BAGEL, which is the mistake it made three times. The audit rule is
      widened from CASPT2 to any multireference job on BAGEL; the app's own
      guard is still CASPT2-only, which is a backlog item rather than a fix,
      because of the freeze.
- [done] P5.4: Do not score a trial whose job is held by the admission gate
      evidence: rsc_digital_discovery/evaluation/harness/nexus.py -- GateHeld plus is_gate_held, handled in all six runners ahead of HarnessError and re-raised past the three inner handlers that swallow it
      Two wiring faults found by checking the AST rather than by reading:
      run_r's handler had landed on an inner `except` inside run_card, where
      `held` is not in scope, so the first gate-held job would have aborted
      the run with a NameError -- on exactly the condition we expect to hit.
      And run_b's end-of-run report filtered sheets by `--id-prefix`, which
      is empty for the deployed-model arm, so `startswith("")` matched every
      sheet in the directory and that arm would have reported the 14B arm's
      provisional verdicts as its own. It matches exact sheet ids now.
      New in the protocol, from this session's finding. A gate-held `pending`
      is neither a hang nor a failure, and must not become a `harness-error`
      sheet -- which matters twice, because `sheet.already_done` is what makes
      a run resumable, so a harness-error sheet is skipped on re-run rather
      than retried. The runner has to tell gate-held from genuinely stuck,
      record the former, and write no sheet.
- [done] P5.5: Grader confirms an ask-detection miss before scoring gave-up
      evidence: rsc_digital_discovery/evaluation/harness/run_b.py -- borderline_ask marks the sheet provisional rather than overturning it; it recognises the registry's own blind-input wording, which run 1 scored as a refusal three times
      Condition G specifically: run 1's keyword lists produced brittle
      verdicts under the small models.

## Phase 6: the two fixes run 2 earned

The freeze ended when the run closed, so the two defects with real user
consequences were fixed and verified against the battery's own probes.
Neither number goes into run 2's table: those 301 sheets describe the frozen
tree and these do not, which is the same rule that keeps run 1 and run 2
apart. They live in `results-postfix/` and are reported separately.

- [done] P6.1: The no-virtual-space guard covers every task and both methods
      evidence: rsc_digital_discovery/evaluation/results-postfix/C-11_t1.yaml -- refuses before any card, naming the virtual space, the basis and the active space
      It was called from `_build_scan_spec_or_error`, so it fired for a scan
      and never for the single point it was written for -- A-19 and A-20, the
      trials that first surfaced the problem, are single points. And it tested
      CASPT2 only, when BAGEL CASSCF fails the same way and worse: it does not
      terminate at all rather than reporting an error. Hoisted into
      `_build_spec_or_error`, widened to both methods on BAGEL, renamed
      `multireference_virtual_space_problem` with the old name aliased, and
      its message made method-aware so a CASSCF user is not told about a
      perturbation that is not running.
- [done] P6.2: A functional written where the method goes is moved, not dropped
      evidence: rsc_digital_discovery/evaluation/results-postfix/B-10_t2.yaml -- the card carries B3LYP D3BJ and names D3ZERO
      `B3LYP-D3` became plain `B3LYP` under a note reading "which is how ORCA
      spells it", so a user would approve undispersed chemistry with the card
      reassuring them nothing had changed. The draft path already had the
      right shape for this one axis over -- the `method_is_really_a_task`
      reroute, commented "a word on the wrong axis, before it is treated as a
      wrong word" -- so this is its sibling. `resolve_functional` is asked
      rather than reimplemented, and only an outright rewrite counts:
      `ambiguous` (PySCF's bare -D3) still belongs in normal elicitation.
      B-10 went 0/3 to 2/3; the remaining failure is real, an agent that asked
      about the damping, was answered, and never carded.
- [done] P6.3: The applied-defaults check understands an announced rewrite
      evidence: rsc_digital_discovery/evaluation/harness/checks.py -- params_accounted_for, self-tested with and without the explanation
      Found by P6.2's own verification. The check compared spellings, so a
      parameter the app rewrites and explains in `param_corrections` -- which
      is what that field is for -- scored as a value nobody chose. It would
      have misfired on any such card. One run-2 sheet was affected, B-10 t2,
      already failing on the same card, so run 2's numbers are unchanged.

## Closed 2026-08-27

Run 2 finished with 301 score sheets, and the two defects it found with real
user consequences were fixed after the freeze lifted and verified against the
battery's own probes. Twenty steps, all done.

**What this tracker was actually for, in hindsight.** Its stated job was to
get from a closed card audit to a clean execution. The audit turned out to be
the load-bearing part: 83 cards, and eight of them were wrong in ways that
would each have burned trials mid-run, which is how run 1 lost three restarts.
Five were found by the audit itself, two more (A-17 and A-18, asking BAGEL for
CASSCF in a basis that leaves no virtual space) by a spot-check job hanging,
and one (A-15, whose keys no runner read) only by a rule written in response
to the design's own second revision.

**The recurring shape of every defect in this phase.** Syntax-valid,
import-valid, semantically wrong. A class inserted between `@dataclass` and
`class Turn`. A local named `rows` shadowing the list of condition sections. A
gate handler landing on an inner `except` where its variable was out of scope.
A guard called from the scan builder rather than the general one. None of them
raised anything; each was caught only by something that exercised the path end
to end. The lesson for the next tracker is that "it imports" and "it parses"
are not evidence, and the audit rules that pay for themselves are the ones
that ask whether a thing is *read*, not whether it is *well-formed*.

**Where the results live.** Three sheet sets, never pooled, because each
describes a different tree: `results-2026-08-25-prefix/` (run 1, 294),
`results/` (run 2, 301), `results-postfix/` (the two fixed probes, 4).
`summary.md` reports them separately and says why.

**Still open, deliberately.** Two items in `docs/BACKLOG.md`: the prose-guard
reliability ceiling, which is a design question rather than a bug, and the
evaluation-design finding that a visible default provokes a good question
condition A scores as a failure. The second is a change to `EVALUATION.md`,
made after the run rather than during it.
