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

**Found by the manuscript evaluation battery, 2026-08-25.** Seven items below
came out of running `rsc_digital_discovery/EVALUATION.md` against the deployed
stack rather than from inspection, which is why several of them had gone
unnoticed: each one needs a real conversation and a real job to show itself.
The active tracker is that battery, so these are parked here rather than
started; the order worth taking them in, cheapest and most damaging first:

1. `supports()` engine-name case sensitivity -- one line, and it currently
   causes a wrong refusal of a working capability.
2. Nothing checks a CASPT2 request has virtual space -- an approval card that
   promises a calculation which cannot run.
3. `orbital_indices` offered on `single_point` and rendered by nothing -- the
   card promises cube files nothing produces.
4. A BAGEL crash reported as a parser failure -- costs an hour of looking in
   the wrong place, as it did here.
5. Three silent defaults the elicitation layer lets through.
6. The agent busy-polls a running job instead of ending its turn.
7. A degenerate XMS request on a single state (tidiness; no observed harm).

- **Three silent defaults the elicitation layer lets through.** Condition B of
  the battery withholds exactly one required parameter per prompt and asks
  whether the agent asks for it. It mostly does -- 24 of 32 trials asked -- but
  three cases default silently, and each has a different fix:

  - *The scan coordinate.* "Scan a bond in water ... from 0.8 to 1.2 angstrom,
    5 points" produced a card carrying
    `coordinate: {atoms: [1, 2], type: bond}` in two trials out of three,
    picking the atoms itself. `coordinate` is `required_when: ALWAYS`, so the
    elicitation table is right and the model is filling it in anyway. Worth
    considering whether `update_job_draft`'s docstring should forbid inventing
    atom numbers the way `active_space_orbital_indices` already forbids
    inventing an orbital list.
  - *Dispersion damping.* "Run a B3LYP-D3 single point" reached the card as
    `functional: "B3LYP D3"` with no prose at all. ORCA's bare `D3` keyword
    means D3(zero), which is a materially different correction from D3BJ, and
    nothing on the card said which reading was taken. There is no `damping`
    parameter to elicit; adding one, or normalising `-D3` to an explicit
    variant, would make the choice visible.
  - *TDDFT versus Tamm-Dancoff.* Same shape: `use_tda` has a default of
    `False` and no `required_when`, so a request that says only "TDDFT"
    silently gets full linear response. That is the documented intent, and it
    is defensible -- but the card does not show `use_tda` either way, so a
    user who wanted TDA has no way to notice.

  None of these is a bug in the registry tables; all three are places where a
  default is correct and invisible at the same time. The cheapest common fix
  may be showing defaulted-but-consequential parameters on the approval card,
  marked as defaults.

- **BAGEL CASPT2 asks for a multi-state rotation over a single state.**
  `bagel_runner._build_input` sets `ms: True, xms: True` on the `smith` block
  unconditionally, so a ground-state-only CASPT2 (`nstate: 1`) requests an
  XMS rotation of a 1x1 problem. Tidiness rather than a defect: it was tested
  during the battery as a suspected crash trigger and cleared -- the same
  input with `ms`/`xms` false fails the same way, for the unrelated reason in
  the virtual-space item above. Worth gating on `nstate > 1` anyway, since a
  reader of the generated input has to work out that it is harmless.

- **Nothing checks that a CASPT2 request has any virtual space left to
  correlate into.** Water in STO-3G is 7 basis functions; a CAS(4,4) with 3
  closed orbitals uses all 7. CASPT2 is a second-order correction into the
  virtual space, so with none left the amplitude equations are empty, and
  BAGEL dies inside LAPACK (`Parameter 9 was incorrect on entry to
  cblas_dgemm`, then `dsyev/pdsyevd failed in Matrix`). The app builds that
  input, shows an approval card for it, submits it and lets the engine crash.
  Observed 2026-08-25 across six evaluation-battery trials (A-19, A-20).

  Two things make this worth fixing rather than filing as a curiosity. It is
  cheap and local to check -- `nclosed + nact` against the basis size is
  already known at input-build time in `bagel_runner._build_input`, and the
  same arithmetic applies to the other multireference engines. And it is
  exactly the structural gating this app claims to do: the whole argument for
  an approval card is that a request which cannot work should be caught before
  a job is spawned, not after an engine dies.

  Recorded here also because of how long it took to see. The failure was
  attributed first to the host's documented BAGEL/MKL instability, then to a
  degenerate `nstate: 1` XMS rotation, then to a mismatched `svp-jkfit`
  density-fitting basis. All three were wrong, and each looked plausible
  because the MKL error text is identical in every case. What settled it was
  R-6 running BAGEL CASPT2 on H2CO/cc-pVDZ to completion in the same
  container, with a deviation of exactly 0 from its reference -- proving the
  engine, the container and the method were all fine, and that the difference
  had to be in the request.

- **A BAGEL crash is reported as a parser failure.**
  `bagel_runner._safe_parse` wraps any parsing exception in "BAGEL ran to
  completion but the '<job_type>' output parser could not find the expected
  results", and suggests a hand-edited input as the likely cause. When BAGEL
  has actually died, that message is wrong in both halves. Observed 2026-08-25
  in the evaluation battery's A-19 trial: `bagel.out` ends with a run of
  `Intel oneMKL ERROR: Parameter 9 was incorrect on entry to cblas_dgemm`
  followed by `ERROR: EXCEPTION RAISED: dsyev/pdsyevd failed in Matrix`, which
  is the MKL instability `CLAUDE.local.md` documents for this host. BAGEL did
  not run to completion, the parser was not at fault, and the input had not
  been edited. Anyone triaging from the notice alone would go looking in the
  wrong place -- as this session did before reading the raw output.
  `_safe_parse` should scan for BAGEL's own `ERROR: EXCEPTION RAISED` line
  first and attribute the failure to the engine when it finds one. The
  underlying MKL problem is environmental and is not this project's to fix;
  the misattribution is.

- **`orbital_indices` is offered on `single_point` and rendered by nothing.**
  The v2 registry lists `orbital_indices` (and `isoval`) among
  `params_for('single_point', 'gs')`, and `registry2/tasks.py` says why in so
  many words: there is deliberately no `mo_viz` task, because "asking for 'the
  HOMO of water' is asking for a calculation and a way to look at it, not for a
  different calculation." But `dispatch.runner_for` sends a `single_point/gs`
  spec to the `single_point` runner, and neither `orca_runner.run_single_point`
  nor `pyscf_runner.run_single_point` does anything with the parameter --
  PySCF's only mention of it writes a comment into the generated input
  ("# orbitals to render: [4, 5]"). Cubes are rendered solely by the legacy
  `mo_visualization` runner, which v2 dispatch never routes to. So a user can
  ask for orbital cube files, watch the approval card show
  `orbital_indices: [4, 5], isoval: 0.04`, approve it, and get a completed job
  with no cube in it and nothing saying why.

  Found 2026-08-25 by the evaluation battery's A-15 trials. Worth recording how
  it was found, because the first reading was wrong: three trials produced
  cards carrying only `{'basis': 'sto-3g'}`, which looked like the model
  dropping half the request, and it was written up that way. A re-run then
  produced a card carrying `orbital_indices: [4, 5]` correctly -- and still no
  cubes. The model's behaviour varies between trials; the missing cube does
  not. Fixing this means either honouring the parameter in the single-point
  runners or routing a single point that carries it to the renderer; leaving
  the parameter inert is the one option that should be off the table, since the
  card actively promises it.

- **The agent busy-polls a running job instead of ending its turn.** On a job
  that takes more than a few seconds, the model calls `check_job_status` in a
  loop within the same turn, narrating each one: fifteen consecutive
  "Still running. Let me check again." messages in one turn, observed
  2026-08-25 in the evaluation battery's A-12 trial. Nothing is broken by it,
  which is why it has gone unnoticed, but it burns model time on a system
  whose whole asynchronous design exists so that nobody has to wait, and
  `app/agent/job_watcher.py` already injects a notice and runs a follow-up
  turn the moment the job finishes. The turn should end after the submission
  and let the watcher do its job. Worth checking whether the tool's docstring
  invites the polling ("Use this whenever the user asks about job progress")
  and whether the system prompt says anywhere that waiting is unnecessary.

- **`supports()` is case-sensitive on the engine name, and the model writes
  `ORCA`.** `registry2.tasks.supports("ORCA", "dft", "single_point", "gs")`
  answers `Unknown engine 'ORCA'.` while the same call with `orca` answers
  supported; `capability_answer` does not normalise it either and echoes the
  caller's spelling straight back. Found 2026-08-25 by the evaluation
  battery's B-10 trial, where the agent hit it mid-conversation and narrated
  its way out loud: *"The lookup reports 'Unknown engine ORCA' -- let me
  check which engines this deployment actually has. ORCA is supported here
  (the earlier 'Unknown engine' was just a case mismatch)."* The user sees a
  dead end and a recovery for something that was never wrong. Fix is to
  lower-case the engine at the registry boundary, the same way the atom
  numbering conversion happens at the RDKit boundary rather than being left
  to every caller. **Not fixed during the battery on purpose**: changing the
  system under test mid-run would make the trials before and after it
  incomparable.

  **This is worse than it first looked, and should be treated as a real bug
  rather than a cosmetic one.** Three sightings so far cost only a wasted tool
  round-trip apiece ("The engine name needs to be lowercase. Let me fix
  that."). The fourth did not: asked for a CASSCF excited-state job on BAGEL,
  the agent answered "BAGEL cannot run this job here -- the engine name isn't
  recognized in this deployment. Would you like to run it on PySCF or ORCA
  instead?" and raised no approval card at all. That is a wrong refusal of a
  capability the deployment demonstrably has: the immediately preceding task
  had just run three BAGEL CASSCF jobs to completion. A user who took that
  answer at face value would conclude the engine was unavailable.

- **README cites the wrong DOI for autoCAS.** The active-space section links
  [Stein and Reiher](https://doi.org/10.1021/acs.jctc.6b00722), but the paper
  it names, "Automated Selection of Active Orbital Spaces" (*JCTC* 2016, 12,
  1760), is DOI `10.1021/acs.jctc.6b00156`. Found 2026-08-24 while verifying
  citations for the journal-article draft; whatever `6b00722` resolves to, it
  is not that paper. One-character-class fix in `README.md`, plus a check of
  anywhere else that DOI was copied (docstrings, KB seeds).
- **README overstates locality: "web search is the only thing that reaches
  the public internet" is not true.** Molecule resolution sends compound
  names to PubChem (`pubchempy`) and to the hosted OPSIN service at
  `opsin.ch.cam.ac.uk` (`app/chemistry/molecule.py:221`), and
  `search_academic_literature` sends query text to Semantic Scholar. None of
  these carry computed data or structures beyond the name being looked up,
  but a compound name is exactly the thing a privacy-conscious user would
  assume stays local after reading that sentence. Found 2026-08-24 while
  writing the privacy section of the journal-article draft, which states the
  accurate version. Fix the README wording (list all four outbound calls:
  PubChem, OPSIN, Semantic Scholar, web search), and consider bundling OPSIN
  locally via `py2opsin` so systematic names never leave the machine at all.
- **`data-testid` coverage is organic, not systematic.** The overhaul grew
  real coverage as each new feature needed one to test live (28 of 75
  frontend components now carry at least one. `Composer.tsx` alone has
  `composer-file-input`/`composer-upload-note`/`composer-detach-job-<id>`/
  `composer-detach-frame`/`composer-add-file`, none of which existed when this
  item was first written), but the specific ~40-element scheme originally
  sketched was never done as one deliberate pass: `chat-composer`/`chat-send`,
  `job-row-<id>`/`job-kill`, and the drawer's 19 gated sections still don't
  exist under those names (confirmed: `JobDetailDrawer.tsx` carries only 3
  testids total). `CollapsibleSection` still has no `aria-expanded` at all,
  both a testing and a screen-reader gap, unchanged.
- **Time-to-first-token: the standing "6–32s, median ~15s" figure is stale and
  likely predates the fix that would explain it.** That number comes from
  F-009 in the retired e2e findings doc (`git show 1e00306`), an n=4 sample
  measured 2026-08-16, and the keep-warm loop
  (`QC_AGENT_MODEL_KEEPALIVE_INTERVAL`) was added the next day, 2026-08-17
  (`c339673`). F-009's own text ends by "considering whether ... a warmed
  context would help," which only makes sense if no warm-context mechanism
  existed yet at measurement time, so the range this backlog item has been
  carrying forward was very plausibly dominated by cold loads (11.4s cold vs
  2.9s warm was this same host's own later-measured gap), not a live,
  already-warm-server problem. Nobody re-measured TTFT after the keep-warm
  fix landed until now.
  Re-measured 2026-08-20 with keep-warm active, both in-process
  (`stream_turn_tokens` directly) and through the real HTTP+SSE path (a
  temporary local server instance, POST `/messages` → first SSE `token`
  event, same method F-009 used): a plain text turn ("What can you help me
  with?") reached first token at 3.85s; a tool-calling turn ("Set the active
  molecule to water") at 2.88s. Both comfortably under the old reported
  floor, and the two measurement paths agree closely, so HTTP/SSE transport
  isn't hiding extra latency. Caveats: small sample (n=1–2 per condition),
  idle single-tenant host, one representative prompt each. A real
  confirmation should pull a larger sample from the e2e harness's own `ttft`
  field (`tests/e2e/results/*.jsonl`) rather than rely on this spot-check.
  One structural, durable lever worth keeping regardless of how the
  stale-measurement question resolves: the bound tool schema sent with every
  turn is ~19.5KB JSON (13 tools via `bind_tools()`) against a 5KB system
  prompt (`app/agent/prompts.py`). Roughly 80% of the fixed per-turn prompt
  cost is tool definitions, not instructions, and is the one lever that
  would lower the ~4s floor itself if that's ever wanted. (Checked and
  ruled out as a contributor: `_build_llm()` rebuilding `ChatOpenAI` +
  `bind_tools()` on every node call costs 405ms on a process's first call
  but under 1ms on every call after, in a long-lived server process, not a
  real per-turn cost.)
- **The Ketcher 2D sketcher's own chunk could still shrink further.** The
  binaryWasm swap removed the ~21MB base64-inlined Indigo binary; what's left
  (`ketcher-react`/`ketcher-core`'s own code, ~7.6MB) hasn't been examined for
  further trimming, and there's no hover-preload to start the fetch before the
  user clicks "Build a molecule."
- **Viewer PNG capture resolution is capped by the on-screen canvas's pane
  size**, not truly independent of it. A capture at 3x an already-small
  in-panel view is still smaller than 3x an enlarged one. Rendering at a fixed
  high resolution regardless of pane size (briefly resizing the container
  before capture) is a reasonable follow-up, deliberately out of scope for the
  current implementation.

## Unverified deployment surface

Not defects. Genuinely never exercised, so don't read their absence here as
clearance:

- The public `:443` listener, end to end.
- The host-level kill switch (`scripts/toggle_public_access.sh`), needs `sudo`
  against this host's real firewall.
- `neb_ts` against a reaction with a genuine barrier (the tested geometry had
  none), and the excited-state path (`target_state`) at all. A 2026-08-20
  regression pass (`docs/trackers/2026-08-job-system-overhaul.md`'s P9.8) hit an ORCA exit-code-2 failure
  on a live `neb_ts` matrix cell (`tests/e2e/e2e_08_job_matrix.py`'s M23).
  The raw output showed a run of identical, non-decreasing energies,
  consistent with (though not confirmed as) a non-converging band on
  whatever system that turn happened to set up. Not isolated further; still
  genuinely unverified, now with a concrete failure on record rather than
  none at all.
- BAGEL CASSCF/CASPT2 to convergence, on hosts whose MKL/BAGEL install is
  abnormally slow (one observed running macro-iterations at ~85s where
  ORCA/PySCF are sub-second on the same trivial system). Not a code defect,
  an environment one, but it has kept full runs from completing on affected
  hosts. Re-verify on a host where BAGEL behaves normally before relying on
  convergence-sensitive results from it.
- The vLLM inference backend (commented out in compose).
- Multi-host operation, real (non-self-signed) TLS, and load beyond one
  operator.

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
