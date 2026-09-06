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
- [done] P7.3: Coverage against recent work
  evidence: tests/backend/cas_21_reference_stability.py → the rotation and sign convention, the refinement tier, the Rydberg decision and the narrowing guards are each named by three or more scripts. The stabilised reference was named by one, and that one calls `stabilise` only incidentally while setting up a constants sweep, so it had no behavioural test. It has one now: 13 checks, 0 failures
- [done] P7.4: Decide about the two scripts excluded from the default run
  evidence: tests/backend/p1_07_purge_status_source.py → both stay opt-in, and `p1_07` cannot be made safe without destroying what it tests. It exists to prove `POST /api/admin/purge/jobs` acts on exactly the jobs the admin console lists; the defect it catches is a job the console shows and the purge misses, which had returned `count: 0` against a listed job. Scoping it to only the jobs it created would remove the global comparison that is the whole assertion. `sec_10` stays opt-in as destructive-shaped even though it is scoped to a disposable account. Running `p1_07` remains how a maintainer asks for a full job purge, in those words
- [done] P7.5: Establish what can and cannot run from a worktree
  evidence: tests/run_backend.sh → 38 of 141 backend scripts need a live stack or shell out to `docker compose`, and from a worktree that resolves to a compose project with no containers, so the full suite must run from the main checkout. The other 103 run in process
- merged: -

## Phase 8: The dev stack, on the merged commit
- [ ] P8.1: `npm run build` on the host, since nginx serves `frontend/dist`
  through a bind mount and a compose rebuild does not refresh it
- [done] P8.2: Rebuild and bring the stack up on the merged commit
  evidence: docs/evaluation/2026-09-06-full-pass.md → api image rebuilt and tagged, container healthy 18 seconds after start, no jobs in flight when it restarted (272 completed, 2 cancelled, 0 running)
- [ ] P8.3: Bootstrap `qatest_admin` first, then the user's own account through
  an invite that admin issues
- [done] P8.4: Confirm the stack answers on 8444, not the tracked default 8443
  evidence: docs/evaluation/2026-09-06-full-pass.md → `/api/health` returns 200 with `{"status":"ok"}` in 0.011 s on https://127.0.0.1:8444, and nginx also binds the tailnet address
- merged: -

## Phase 9: Everything run, and the results written down
- [ ] P9.1: The backend suite from the main checkout
- [ ] P9.2: The frontend Playwright specs
- [ ] P9.3: The `tests/e2e` scenarios and its UI specs
- [ ] P9.4: The CAS benchmark's six sets, ledgers committed
- [done] P9.5: The standalone validators, each run or given a stated reason
  evidence: docs/evaluation/2026-09-06-full-pass.md → `validate_orbital_character` and `validate_wigner_sampling` both pass. The latter checks three independent things: it reproduces pyscf's own reduced masses to 6.18e-16 over 3 modes and 8.11e-16 over 6, it matches the analytic harmonic mean potential to 1.13% and 1.11% against a 3% tolerance, and it shows 0.000000 Angstrom of centre-of-mass drift once translational modes are excluded. The remaining three need engines or long runs and are covered by the full pass
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
- [done] P11.1: Per job type, list what the result holds and mark the gaps
  evidence: docs/evaluation/2026-09-06-full-pass.md → inventoried from the completed jobs on disk rather than from the code, grouped by (task, subtype) and split into keys every job of that kind carries and keys only some do. 14 kinds, and the orbital-data column is the one that separated them: single_point carried an orbital table 209 times in 209 while opt/min carried it 0 in 5. Master job types (batch, geometry_set, pes_1d, wigner_spectra) carry none by design, their children holding it, and `blind` carries none because the pasted input decides what is produced
- [done] P11.2: Add the missing pieces, in the preview pane rather than a flyout
  evidence: frontend/src/jobs/JobDetailDrawer.tsx → no frontend change was needed, which is the point. Line 1436 gates the orbital panel on `orbitalTable && orbitalTable.length > 0` with no job-type test, so writing the table on the optimization and frequency paths makes the table and the lazily-rendered cube viewer appear in the preview pane itself
- [ ] P11.3: Verify in a real browser, asserting each component renders
- merged: -

## Phase 12: The decks, cleared
- [ ] P12.1: `docs/BACKLOG.md` empty
- [ ] P12.2: `docs/HANDOFF.md` empty, including the 2026-09-04 ethylene
  re-aggregation and the auto-resume crontab line
- [ ] P12.3: `README.md` checked against any user-visible change
- [ ] P12.4: Worktree and branch cleared. The merge and push are done:
  `b2f045f..f23e005`, eight commits, 20 files changed, fast-forward
- [ ] P12.5: This tracker archived and the placeholder restored
- merged: -

---

## Phase 13: Tangents, fixed as they were found

Bugs and performance problems found while doing something else. Each is
fixed in the same piece of work rather than recorded and left, which is the
standing rule; they are numbered as a phase so `check_tracker.py` validates
their evidence the way it does every other step. A `T`-prefixed id does not
match its grammar and was silently going unchecked.

- [done] P13.1: The system prompt was 98 bytes over its 6 KiB cap, so
  `agent_01_token_budget.py` reported 12 of 13. Trimmed seven redundant
  phrases, no rule removed; 6,137 bytes and 13 of 13, fixed surface 8,821
  tokens. Headroom is now 7 bytes, so the next addition needs a matching trim.
  evidence: tests/backend/agent_01_token_budget.py → 13/13, and agent_02, agent_09, elic_01, agent_06 and draft_01 all pass against the trimmed prompt
- [done] P13.2: `agent_09_unstated_parameters.py` asserted `len(GUARDED_PARAMS) ==
  15`, a count dated 2026-08-29. A sixteenth parameter has since been guarded,
  so it failed with the detail "16 parameters", which names nothing. The set is
  derived from parameter help text and is meant to grow, so the check now
  compares an explicit named set and reports which parameter moved.
  evidence: tests/backend/agent_09_unstated_parameters.py → 0 failures, and all 16 were checked by hand as values a model could plausibly invent
- [done] P13.3: The e2e job matrix's only `cas_reco` cell named the subtype
  `autocas`, which the 2026-09-02 rebuild removed. So the engine this plan is
  about had no working end-to-end cell. `reg2b_03_matrix_v2_taxonomy.py` would
  have caught it, since `get_task('cas_reco', 'autocas')` returns None; it had
  simply not been run since the rebuild, which is the argument for this whole
  phase.
  evidence: tests/backend/reg2b_03_matrix_v2_taxonomy.py → 186 of 186 checks pass after the fix, against 178 of 191 before
- [done] P13.4: Matrix cell M28 passed `target_state` to `single_point/grad`. That
  parameter belongs to opt, freq, opt_freq and neb_ts; the one grad takes is
  `target_states`, a list of 1-based indices in which 1 is the ground state.
  The cell had neither the right key nor a value that reads correctly as the
  plural.
  evidence: tests/backend/reg2b_03_matrix_v2_taxonomy.py → the missing-parameter check now passes for M28
- [done] P13.5: `EXPECTED_SUMMARY_KEYS` asserted nothing at all for a `pes_1d`
  master, on the belief that only children carry energies. A completed
  `pes_1d/ee` master read off disk carries coordinate, coordinate_values,
  energies_hartree, relative_energies_eV and state_energies_per_image, and
  `scan_orchestrator.py` writes the first two unconditionally. The entry now
  asserts them, and `interp_pes` gets the same, sharing that orchestrator.
  evidence: tests/backend/reg2b_03_matrix_v2_taxonomy.py → entries exist for all five previously unkeyed pairs
- [done] P13.6: `p8_02_cas_reco_followup.py` built its fixtures on
  `cas_reco/autocas` and `cas_reco/avas`, neither of which exists, and passed
  anyway because `_poll_once` classifies on the task alone and never reads the
  subtype. Rewritten onto the two subtypes that do exist, with the second case
  now doubling as a check that the classification really is on the task.
  evidence: tests/backend/p8_02_cas_reco_followup.py → 15 passed, 0 failed
- [done] P13.7: `p8_01_orbital_reuse.py` asserted a top-level `force` block for a
  CASSCF gradient and a top-level `nacme` block for a NAC. Those are the shape
  of the HF-reference branch and of nothing else. A CASSCF or CASPT2 gradient
  uses the manual's multi-state mechanism: one `forces` block whose `grads`
  list carries the per-surface entries, titled `force` or `nacme`. The old
  expectation named the right words at the wrong level, so two cells failed
  against a runner doing the correct thing. The check now asserts the block
  sequence and the nested titles, because at the top level a gradient and a NAC
  are the same six blocks and without the second assertion the NAC case would
  check nothing a gradient does not also satisfy.
  evidence: tests/backend/p8_01_orbital_reuse.py → 40 passed, 0 failed
- [done] P13.8: The in-process backend subset needed this host's `.env` to resolve
  ORCA and BAGEL paths. Without it four scripts died on `/opt/orca/orca`, the
  generic default in `app/config.py`, and a fifth had a job fail to reach
  `completed` for the same reason. Not a defect, but it is why a first reading
  of the run looked like a regression.
  evidence: tests/backend/p8_01_orbital_reuse.py → with `.env` present, grad_01, opt_01, p7_03 and p8_04 all pass; 85 of 103 becomes 89 of 103, and every remaining failure needs the auth bootstrap
- [done] P13.9: `batch_01_multi_geometry.py` checked `os.path.exists` on an
  artifact path the batch orchestrator had recorded. A batch's `artifacts` dict
  mixes two kinds of path: some are written by the script in process and are
  already host paths, while the aggregate's plot is written by the orchestrator
  inside the API container, where the same directory is `/app/data`. The two
  name identical bytes through the `./data:/app/data` bind mount, and only one
  of them exists from where the script runs. So the assertion passed against a
  bare host process and failed against the compose stack the suite is otherwise
  written for, which is not a difference it means to be sensitive to.
  evidence: tests/backend/batch_01_multi_geometry.py → the check now resolves the recorded path through JOBS_DIR before testing it, and the failure detail prints both the recorded and the resolved path so the next reader does not have to work this out again
- [ ] P13.10: The backlog's second item says the app-versus-host latency split
  "needs the GPU to itself" and cannot be measured on a shared card. GPU 0 is
  reserved for NexusQC, so it can now be measured rather than left open

- [done] P13.11: A geometry optimization or a frequency job on HF or DFT
  exported no orbital data at all, while every single point does and while the
  CASSCF versions of both do. So a user who optimized a geometry could not see
  the frontier energies or open an orbital, even though the run ends with a
  converged SCF at the final geometry and `_write_molden_and_table`'s own
  docstring says every runner that ends with one should call it. The drawer
  gates the orbital table and the cube viewer on `orbital_table` being present
  rather than on job type, so this cost the preview nothing to fix.
  evidence: app/chemistry/jobs/pyscf_runner.py → measured over the completed jobs on disk before the change: single_point carried an orbital table 209 times in 209, including 102 of 102 on DFT, while opt/min carried it 0 times in 5 and freq on DFT 0 times in 2. A real DFT optimization of water now returns 7 orbital rows with character and localized atom, a molden on disk and a HOMO-LUMO gap of 8.70 eV; a DFT frequency returns the same plus its 3 frequencies
- [done] P13.12: ORCA's frequency summary set `orbital_table` only when the
  method was CASSCF, so the same job on HF or DFT came back with nothing to
  inspect. Every ORCA output carries an orbital block regardless of method, so
  the `if` was the only thing withholding it.
  evidence: app/chemistry/jobs/orca_runner.py → the table is now set whenever the parser finds rows, and the note distinguishes natural orbitals from the canonical ones the Hessian was built on
- [done] P13.13: `bagel_runner.py` defined `run_frequency` twice. The first was
  a truncated 20-line body with no return at all, dead because Python binds the
  name to the later definition, and nothing had ever called it. The live one
  then had an unreachable `return summary, None` after an unconditional return,
  which is the shape of an `if` whose body was flattened into the branch above
  it, so `_add_orbital_table` ran with its `multireference=True` default for
  every method. That flag chooses the note claiming the rows are natural
  orbitals with active-space occupation numbers, which is false of an HF
  reference. It never surfaced only because an HF frequency writes no
  orbitals.molden and the helper returned None.
  evidence: app/chemistry/jobs/bagel_runner.py → one definition remains, the unreachable return is gone, and the flag is now derived from the method
- merged: -
