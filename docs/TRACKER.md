# Tracker: finish the CAS engine, then bring every suite current

One tracker, kept live. Phases 1 to 6 finished the CAS recommendation engine's
last defect; Phases 7 onward are the repository-wide test and evaluation pass
that follows. Tangents are recorded here as they happen rather than afterwards,
in the **Tangents** section at the end, because a bug found while doing
something else is still a bug that was found.

The standing instruction: keep going until the CAS work is merged and pushed,
every suite is audited and current, the dev stack is on the merged commit, all
suites and evaluation sets have been run and recorded, every job type has been
exercised end to end, the preview and tagging carry what they should, and both
`docs/BACKLOG.md` and this file are empty of open items.

Two host facts govern how much compute this may claim, and they are more
permissive than `CLAUDE.local.md` implies. **GPU 0 is reserved for NexusQC**,
and **Ollama on this host serves only NexusQC**, so agent-driven tests and long
evaluation sweeps are fair use and neither is a reason to narrow a phase.

## Phase 1: The rotation mechanism, measured before anything is changed
- [done] P1.1: Confirm the failure is a perceived-direction problem, not a
  convergence one
  evidence: scripts/casbench/rotation_invariance.py --molecule formaldehyde --targets → before the fix the C=O axial direction is covariant at [0,0,1] on all five rotations while the two perpendicular lone-pair directions are a different basis of the same plane each time, and the space alternates (6e,4o) on rotations 0/2/3 against (8e,5o) on 1/4
- [done] P1.2: Establish the alternation is a wrong answer, not merely an
  inconsistent one
  evidence: scripts/casbench/reference_data.py → formaldehyde's reference space is (6e,4o), so two of the five rotations are simply wrong
- [done] P1.3: Identify the mechanism in the code rather than inferring it
  evidence: app/chemistry/cas/geometry.py → `perceive` discards a lone-pair direction parallel to the atom's pi normal, but `perpendicular_pair` seeded from a lab-frame vector returns an arbitrary basis, which is parallel to nothing, so the discard fired only by luck and the pi direction entered the pool twice
- merged: -

## Phase 2: A covariant pair, seeded from the molecule
- [done] P2.1: Give `perpendicular_pair` a molecular direction to seed from
  evidence: scripts/casbench/rotation_invariance.py --molecule formaldehyde --targets → all five rotations return (6e,4o), the reference space, with covariant axes
- [done] P2.2: The terminal atom's plane is its neighbour's, which `perceive`
  already inherits for the pi target
  evidence: tests/backend/cas_20_rotation_invariance.py → each of the four benchmark carbonyls emits two lone-pair targets rather than three, and the largest absolute cosine between either and the pi normal is 0.0000
- [done] P2.3: Sweep all thirty molecules
  evidence: scripts/casbench/rotation_invariance.py → 0 of 30 change under five random rotations, against six before, and every one returns the space `spaces.md` records for its unrotated geometry
- merged: -

## Phase 3: The seed that stays arbitrary
- [done] P3.1: Establish which molecules reach the fallback
  evidence: scripts/casbench/rotation_invariance.py --fallback → three of 36 geometries, N2, N2_stretched and O2, and structurally it is the diatomic and linear-centre class, where no molecular direction exists to seed from
- [done] P3.2: Decide between the hybrid and pure p on that path
  evidence: scripts/casbench/rotation_invariance.py --fallback → the hybrid stays. On a linear centre the pi pair and the lone-pair pair come from the same call and lie along identical axes, at s_amp 0.0 and 0.2, so pure p would make the lone pairs exact duplicates of targets already in the pool
- merged: -

## Phase 3A: The sign, which the first repair did not fix
- [done] P3A.1: Establish that the sign, not the line, moves the number
  evidence: scripts/casbench/rotation_invariance.py → with the old seed restored by monkeypatch and nothing else changed, formamide's n->pi* capture reads 0.806; with the new seed 0.802, four times out of four
- [done] P3A.2: Orient the in-plane direction by a geometric rule
  evidence: tests/backend/cas_20_rotation_invariance.py → acrolein, formamide and uracil keep both direction and sign across three orientations on an independent seed
- [done] P3A.3: Choose the tolerance from the data
  evidence: app/chemistry/cas/geometry.py → four of twelve terminal heteroatoms project exactly 0.0 and the other eight run 0.0046 A to 1.14 A, so any cut between noise and 4e-3 separates them identically. A first draft claimed 0.31 A on acrolein, which was a guess and wrong
- [done] P3A.4: Show the sign left arbitrary is harmless, and the assertion is
  not decorative
  evidence: tests/backend/cas_20_rotation_invariance.py → with `_orient_outward` disabled the sign checks fail on all three molecules where a sign is defined. Where the projection is zero the two signs are mirror images: formaldehyde captures 0.660 either way, acetone 0.681, p-benzoquinone 0.617 and 0.708
- merged: -

## Phase 4: Validation at the width a perception change requires
- [done] P4.1: Every `cas_*` script
  evidence: tests/backend/cas_20_rotation_invariance.py → all 18 run after the sign fix with no failures
- [done] P4.2: `--set spaces` against the committed ledger
  evidence: scripts/casbench/run_bench.py → 25 of 30 exact with the per-class breakdown unchanged: core 8/13, non-planar 3/3, diradical 5/5, conjugated 4/4, charged 5/5
- [ ] P4.3: `--set narrowed`
- [ ] P4.4: `--set stability`, both halves
- [ ] P4.5: `--set refine` and `--set nevpt2`
- [done] P4.6: A standing regression test
  evidence: tests/backend/cas_20_rotation_invariance.py → 25 checks pass on a seed independent of the benchmark's
- merged: -

## Phase 5: The measurements taken under the defect
- [done] P5.1: Re-run hole capture on the nine n->pi* states
  evidence: scripts/casbench/hole_capture.py → four reproduce exactly and five move by at most 0.002. Range 0.570 to 0.819 and the study's finding are unchanged
- [done] P5.2: Attribute the movement rather than reporting it
  evidence: scripts/casbench/hole_capture.py → the five that moved are exactly those on an asymmetric carbonyl. Uracil's four sign combinations were enumerated and the mixed one with O4 inward reproduces the recorded 0.759 and 0.819 exactly
- merged: -

## Phase 6: The CAS document
- [done] P6.1: Sections 3.6 and 4.4 rewritten
  evidence: docs/CAS_ENGINE_METHOD.md → the rotation limitation is replaced by the measurement and its mechanism, and 4.4 states the one that remains
- [done] P6.2: A supplement for what would swamp the paper
  evidence: docs/casbench/rotation-invariance.md → reproduction commands, target dumps, the projection distribution and the negative test
- [ ] P6.3: Every number re-derived from the final six-set sweep
- [done] P6.4: `CHANGELOG.md`
  evidence: docs/casbench/rotation-invariance.md → entries for both repairs and the prompt trim
- merged: -

## Phase 7: The suites, audited against the code as it is now
- [done] P7.1: Static audit
  evidence: tests/run_backend.sh → 182 Python files under tests/backend, tests/frontend, scripts/casbench and scripts all compile and every app/scripts import resolves, submodule imports included
- [done] P7.2: Coverage against the registry
  evidence: tests/e2e/_probes.py → all 20 registry (task, subtype) pairs are named by at least four test files, and the e2e matrix now covers every pair a single request can reach
- [ ] P7.3: Coverage against recent work: the rotation and sign convention, the
  refinement tier, the Rydberg decision, the stabilised reference and the
  narrowing guards
- [ ] P7.4: Decide about the two scripts excluded from the default run
- [done] P7.5: Establish what can and cannot run from a worktree
  evidence: tests/run_backend.sh → 38 of 141 backend scripts need a live stack or shell out to `docker compose`, and from a worktree that resolves to a compose project with no containers, so the full suite must run from the main checkout. The other 103 run in process
- merged: -

## Phase 8: The dev stack, on the merged commit
- [ ] P8.1: `npm run build` on the host, since nginx serves `frontend/dist`
  through a bind mount and a compose rebuild does not refresh it
- [ ] P8.2: Rebuild and bring the stack up on the merged commit
- [ ] P8.3: Bootstrap `qatest_admin` first, then the user's own account through
  an invite that admin issues
- [ ] P8.4: Confirm the stack answers on 8444, not the tracked default 8443
- merged: -

## Phase 9: Everything run, and the results written down
- [ ] P9.1: The backend suite from the main checkout
- [ ] P9.2: The frontend Playwright specs
- [ ] P9.3: The `tests/e2e` scenarios and its UI specs
- [ ] P9.4: The CAS benchmark's six sets, ledgers committed
- [ ] P9.5: The standalone validators, each run or given a stated reason
- [ ] P9.6: A results record under `docs/evaluation/`, with no bare score: each
  figure says what the test was, what the denominator counts, and what the
  result means
- merged: -

## Phase 10: Every job type, end to end
- [ ] P10.1: Snapshot jobs and threads first, so only what this creates is
  removed afterwards
- [ ] P10.2: Run the job matrix, all 40 cells
- [ ] P10.3: Cover the four pairs the matrix cannot: `batch` and `geometry_set`
  are orchestration types reached by asking for several geometries,
  `wigner_spectra` has its own scenario, and `cas_reco/refine` needs a source
  job id that only exists at runtime
- [ ] P10.4: Confirm the leave-and-return path for each: survives its parent,
  reaches a terminal status, result findable afterwards
- [ ] P10.5: Delete exactly what was created
- merged: -

## Phase 11: What the preview and the tagging hand over
- [ ] P11.1: Per job type, list what the result holds, what the preview shows
  and what tagging exposes, and mark the gaps
- [ ] P11.2: Add the missing pieces, in the preview pane rather than a flyout
- [ ] P11.3: Verify in a real browser, asserting each component renders
- merged: -

## Phase 12: The decks, cleared
- [ ] P12.1: `docs/BACKLOG.md` empty
- [ ] P12.2: `docs/HANDOFF.md` empty, including the 2026-09-04 ethylene
  re-aggregation and the auto-resume crontab line
- [ ] P12.3: `README.md` checked against any user-visible change
- [ ] P12.4: Merged to `main`, pushed to `origin`, worktree and branch cleared
- [ ] P12.5: This tracker archived and the placeholder restored
- merged: -

---

## Tangents

Bugs and performance problems found while doing something else. Each is fixed
in the same piece of work rather than recorded and left, which is the standing
rule; they are listed here so the detour is visible rather than buried in a
commit message.

- [done] T1: The system prompt was 98 bytes over its 6 KiB cap, so
  `agent_01_token_budget.py` reported 12 of 13. Trimmed seven redundant
  phrases, no rule removed; 6,137 bytes and 13 of 13, fixed surface 8,821
  tokens. Headroom is now 7 bytes, so the next addition needs a matching trim.
  evidence: tests/backend/agent_01_token_budget.py → 13/13, and agent_02, agent_09, elic_01, agent_06 and draft_01 all pass against the trimmed prompt
- [done] T2: `agent_09_unstated_parameters.py` asserted `len(GUARDED_PARAMS) ==
  15`, a count dated 2026-08-29. A sixteenth parameter has since been guarded,
  so it failed with the detail "16 parameters", which names nothing. The set is
  derived from parameter help text and is meant to grow, so the check now
  compares an explicit named set and reports which parameter moved.
  evidence: tests/backend/agent_09_unstated_parameters.py → 0 failures, and all 16 were checked by hand as values a model could plausibly invent
- [done] T3: The e2e job matrix's only `cas_reco` cell named the subtype
  `autocas`, which the 2026-09-02 rebuild removed. So the engine this plan is
  about had no working end-to-end cell. `reg2b_03_matrix_v2_taxonomy.py` would
  have caught it, since `get_task('cas_reco', 'autocas')` returns None; it had
  simply not been run since the rebuild, which is the argument for this whole
  phase.
  evidence: tests/backend/reg2b_03_matrix_v2_taxonomy.py → 186 of 186 checks pass after the fix, against 178 of 191 before
- [done] T4: Matrix cell M28 passed `target_state` to `single_point/grad`. That
  parameter belongs to opt, freq, opt_freq and neb_ts; the one grad takes is
  `target_states`, a list of 1-based indices in which 1 is the ground state.
  The cell had neither the right key nor a value that reads correctly as the
  plural.
  evidence: tests/backend/reg2b_03_matrix_v2_taxonomy.py → the missing-parameter check now passes for M28
- [done] T5: `EXPECTED_SUMMARY_KEYS` asserted nothing at all for a `pes_1d`
  master, on the belief that only children carry energies. A completed
  `pes_1d/ee` master read off disk carries coordinate, coordinate_values,
  energies_hartree, relative_energies_eV and state_energies_per_image, and
  `scan_orchestrator.py` writes the first two unconditionally. The entry now
  asserts them, and `interp_pes` gets the same, sharing that orchestrator.
  evidence: tests/backend/reg2b_03_matrix_v2_taxonomy.py → entries exist for all five previously unkeyed pairs
- [ ] T6: `p8_02_cas_reco_followup.py`'s docstring still describes
  `cas_reco/autocas` and `cas_reco/avas`, neither of which exists
- [ ] T7: The backlog's second item says the app-versus-host latency split
  "needs the GPU to itself" and cannot be measured on a shared card. GPU 0 is
  reserved for NexusQC, so it can now be measured rather than left open
