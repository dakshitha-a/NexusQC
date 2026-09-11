# Area `jobs` — static audit of `app/chemistry/jobs/`, `app/chemistry/registry2/`, `app/chemistry/cas/` (light), `app/chemistry/molecule.py`

Read first: `docs/ARCHITECTURE.md` §Job execution (all), §Engine integration (all),
§Orbitals and molden, §Vibrations and spectra, §One vocabulary per quantity,
§Energy units; `docs/QM_CAPABILITIES.md`; `docs/PARSER_GAPS.md`; `CLAUDE.md`.
All checks below are read-only. Two mechanical registry scripts were run (import
and print only, no job submitted); they are quoted inline in the findings they
produced.

---

### R-000: ORCA multi-state gradient computes the S0 entry on an excited surface whenever `target_states` does not begin with 1
- surface: code:jobs
- class: bug
- severity: S1
- cause: CODE
- confidence: suspected (code read)
- found by: audit:jobs
- scope: ORCA only. PySCF (`pyscf_runner.run_gradient`, hf/dft branch: `root = state - 1`, `state == 1` uses `mf.nuc_grad_method()`) and BAGEL (`bagel_runner._build_input`: `grads = [{"title": "force", "target": int(s) - 1} ...]`) convert per entry and are correct; I checked both. Not checked: whether any caller upstream of `_build_spec_or_error` happens to sort the list in practice.
- repro: submit a `single_point/grad` draft on ORCA with `target_states=[2, 1]` (a plausible phrasing of "S1 and the ground state"). Compare the two `.engrad` energies: both come from `IRoot 1`. Same input text is produced for the `state_2` and the top-level run.
- observed: `run_gradient` loops over `targets` and, per state, sets `state_params = {**params, "target_state": (state - 1) or None}` (`orca_runner.py:952`) — so the ground state passes `target_state=None`. `build_input_text`'s gradient branch then does
  `target_state = params.get("target_state") or ((targets[0] - 1) or None)` (`orca_runner.py:573`).
  `None` is falsy, so the ground-state run falls through to the fallback and takes its root from `targets[0]`. With `targets = [2, 1]` the S0 run emits `%tddft / NRoots 1 / IRoot 1 / end` and the parsed `.engrad` is S1's gradient — recorded as `derivatives.gradient_entry(1, ...)`, i.e. labelled S0.
- expected: the fallback exists only so a *preview* built straight from a draft (which carries `target_states` but no `target_state`) shows an excited-state input; it must not fire when `run_gradient` has explicitly set the key. Nothing normalises or sorts `target_states`: `app/agent/tools.py::_validate_target_states` (l.1004) checks shape, distinctness and ceiling only, and `_normalized_state_list` preserves order.
- evidence: `app/chemistry/jobs/orca_runner.py:573`
  `target_state = params.get("target_state") or ((targets[0] - 1) or None)`
  and `app/chemistry/jobs/orca_runner.py:952`
  `state_params = {**params, "target_state": (state - 1) or None}`
- pointer: `or` on a value whose legitimate "ground state" encoding is exactly the falsy one. `docs/ARCHITECTURE.md` §"Several states or pairs are one job" warns about precisely this pair of conventions ("`target_states` … 1-based INCLUDING the ground state … the older scalar `target_state` … 0 or absent means the ground state").
- note: settled by diffing the input text for `target_states=[2,1]` state 1 vs `target_states=[1]`. Fix direction: `target_state = params["target_state"] if "target_state" in params else ((targets[0] - 1) or None)` — key presence, not truthiness. A cheaper belt-and-braces fix is to sort `target_states` ascending in `_validate_target_states`, but that only hides this instance.

### R-000: `normalize_method` silently rewrites the canonical method `lpdft` (and `pdft`, `l-pdft`, `tddft`) to `dft`
- surface: code:jobs
- class: bug
- severity: S1
- cause: CODE
- confidence: suspected (code read + executed the pure function)
- found by: audit:jobs
- scope: all engines — the rewrite happens in `app/agent/tools.py::_build_spec_or_error` before engine resolution is used, so it applies to every L-PDFT/MC-PDFT request on PySCF (the only engine with those methods). I did not exercise the full draft→submit path, only `normalize_method` itself and the call site.
- repro: `PYTHONPATH=$PWD python3 -c "from app.chemistry.jobs.param_normalize import normalize_method; print(normalize_method('lpdft'))"` →
  `('dft', "Interpreted method 'lpdft' as 'dft' ...")`. Same for `'pdft'`, `'l-pdft'`, `'tddft'`, `'hfx'`→`'hf'`.
- observed: the fuzzy fallback is `difflib.get_close_matches(key, _METHOD_ALIASES.keys(), n=1, cutoff=0.75)` (`param_normalize.py:72`). `SequenceMatcher(None, "lpdft", "dft").ratio()` is exactly `0.75` (verified), and `get_close_matches` uses `>=`, so `lpdft` matches `dft`. `lpdft` is a member of `registry2.capabilities.CANONICAL_METHODS`. The call site is unconditional: `app/agent/tools.py:1187` `method, note = normalize_method(method)` — there is no `method in CANONICAL_METHODS` short-circuit ahead of it.
- expected: the module's own docstring promises the opposite — "Anything that doesn't match — including a genuinely different/unsupported value like `mp2` or `ccsd` in the method field — is left completely untouched … This is spelling/formatting correction, never a guess at different chemistry than what was actually asked for." `docs/ARCHITECTURE.md` §"Parameter repair is narrow and verified" says the same. `app/chemistry/jobs/functional.py` handles the identical problem correctly: its fuzzy path returns `AMBIGUOUS` with options (`functional.py:579-581`), never a silent rewrite.
- evidence: `app/chemistry/jobs/param_normalize.py:72`
  `close = difflib.get_close_matches(key, _METHOD_ALIASES.keys(), n=1, cutoff=0.75)`
  `app/agent/tools.py:1187` `method, note = normalize_method(method)`
- pointer: a similarity cutoff tuned against three-letter typos, applied to a vocabulary that contains a real five-letter method three edits from `dft`.
- note: the resulting spec has `method="dft"` with no `functional`, so most L-PDFT drafts will then fail loudly at `build_mf`/`_method_line` rather than compute the wrong thing — that is luck, not a guard, and a draft that carries a stray `functional` key from an earlier turn would run a plain DFT single point under an approval card saying `dft`. The note *is* surfaced in `param_notes`. Two-line fix: return early when `method.lower() in CANONICAL_METHODS`, and/or raise the cutoff above 0.75 with the exact-alias table doing the real work.

### R-000: every job is hard-killed at 6 hours by an undocumented, non-overridable timeout
- surface: code:jobs
- class: bug
- severity: S1
- cause: CODE
- confidence: suspected (code read)
- found by: audit:jobs
- scope: all three engines. `base._run_inner` wraps every worker; `orca_runner._write_and_run`/`_write_and_run_generic` and `bagel_runner._run_bagel` each add the same cap to their own `subprocess` call, so ORCA and BAGEL are capped twice.
- repro: submit anything that runs past 6 h (a CASPT2 or a numerical CASSCF Hessian on a real molecule is the ordinary case here). At 6 h the process group is SIGTERM'd and the job reports `failed` / `job exceeded 6h timeout`.
- observed: `app/chemistry/jobs/base.py:1752` `returncode = proc.wait(timeout=6 * 3600)`, then `base.py:1786` `write_result(JobResult(spec.job_id, "failed", error="job exceeded 6h timeout"))`. Also `orca_runner.py:763` and `:792` (`timeout=6 * 3600`), `bagel_runner.py:722` (`subprocess.run([...], timeout=6 * 3600)`), and `base.py:1177` in the orphan watcher.
- expected: `CLAUDE.md` and `docs/ARCHITECTURE.md` both state that multi-hour CASSCF/CASPT2 runs are the design premise and that "anything that would make a job's lifetime depend on its user's session is a serious regression". Every other threshold in this subsystem is `QC_AGENT_*`-overridable (`N_CORES`, `MAX_CONCURRENT_JOBS`, `MAX_CPU_PERCENT`, `MAX_MEM_PERCENT`, `CORE_IDLE_THRESHOLD_PERCENT`, `MASTER_MAX_IN_FLIGHT`, `IMAGINARY_FREQ_THRESHOLD_CM1` — all in `app/config.py`). This one is a literal in four files. `grep -rn -i "hour|timeout" docs/ README.md` finds no mention of a 6 h cap anywhere — not in `ARCHITECTURE.md`, not in `QM_CAPABILITIES.md`, not in the known-limitations section, and not in the README, whose line 613 says the opposite in as many words: *"A CASSCF job can run for hours. Close the tab and come back; it'll still be [there]"*.
- evidence: `app/chemistry/jobs/base.py:1752`, `:1786`; `app/chemistry/jobs/orca_runner.py:763,792`; `app/chemistry/jobs/bagel_runner.py:722`
- pointer: a defensive timeout written for a runaway process, left at a value shorter than the workload the app exists to run.
- note: confirm by asking the maintainer whether 6 h is intended at all. If it is, it belongs in `app/config.py` as `QC_AGENT_JOB_TIMEOUT_SECONDS` and in the docs, and the four literals should read the same constant. Note the ordering: the OUTER `proc.wait` in `_run_inner` starts at worker spawn, the inner `subprocess.run(timeout=...)` in the ORCA/BAGEL runners only once imports are done seconds later, so the outer one expires first and the user does see the tidy "job exceeded 6h timeout" message. The inner caps matter only for a runner invoked outside `JobManager`.

### R-000: after 6 h the orphan watcher marks a still-running re-attached worker `failed`, and the status never recovers
- surface: code:jobs
- class: bug
- severity: S1
- cause: CODE
- confidence: suspected (code read)
- found by: audit:jobs
- scope: any engine; only reachable for a job re-attached by `_reconcile_orphaned_jobs` case 2 (worker survived a backend restart) that then runs more than 6 h from the moment of re-attachment.
- repro: start a long job, restart the backend, leave the re-attached worker running past 6 h. `status.json` flips to `failed` while the worker keeps computing; when it finishes it writes a `completed` `result.json`, and the two disagree until the *next* backend restart runs `_reconcile_orphaned_jobs` case 1.
- observed: `_watch_orphan_worker` does
  ```
  try:
      psutil.Process(pid).wait(timeout=6 * 3600)
  except Exception:
      pass
  ```
  (`base.py:1176-1179`). A `psutil.TimeoutExpired` is swallowed identically to a normal exit. Execution then falls through, pops the pid from `self._orphan_pids` (so `cancel()` can no longer reach the live process at all), finds no terminal `result.json`, and writes
  `write_status(job_id, "failed", "worker process exited after a server restart with no result recorded")` (`base.py:1192`) plus a matching failed `result.json`.
- expected: the architecture's whole orphan-reconciliation section exists so that "a status that never reaches terminal" cannot happen; the mirror failure — a *wrong* terminal status on a job that is still running and will succeed — is equally an S1 by the brief's definition, and it additionally strands the process (no `Popen`, no `_orphan_pids` entry, cancel returns False).
- evidence: `app/chemistry/jobs/base.py:1176-1196`
- pointer: `except Exception: pass` around a `wait(timeout=...)` conflates "it exited" with "I gave up waiting".
- note: distinguish `TimeoutExpired` from a real exit — on timeout, either loop the wait or leave the job alone and keep the pid registered. Independent of whether the 6 h value itself is kept.

### R-000: the registry offers and routes ten (task, method, engine) cells whose input builder refuses them
- surface: code:jobs
- class: bug
- severity: S2
- cause: CODE
- confidence: suspected (code read + mechanical check run)
- found by: audit:jobs
- scope: all three engines, whole `TASKS` × `CANONICAL_METHODS` cross-product. Master tasks excluded. `blind`+`basis` and `single_point/ee`+`n_states` rows my first sweep produced were artifacts of my own parameter fixture and are excluded from the list below.
- repro:
  ```
  cd /data/qcuser/9.NexusQC/NexusQC-dev-repo && PYTHONPATH=$PWD \
  QC_AGENT_LLM_BASE_URL=http://localhost:11434/v1 \
  /home/qcuser/apps/miniconda3/envs/qc-agent/bin/python3 -c '
  from app.chemistry.registry2.elicitation import validate_draft
  MOL={"symbols":["O","H","H"],"coords":[[0,0,0],[0,0,0.96],[0.93,0,-0.24]],"charge":0,"multiplicity":1}
  for d in [{"task":"single_point","subtype":"gs","method":"eom_ccsd","params":{"basis":"sto-3g"}},
            {"task":"opt","subtype":"min","method":"mp2","params":{"basis":"sto-3g"}},
            {"task":"opt","subtype":"min","method":"ccsd","params":{"basis":"sto-3g"}},
            {"task":"freq","subtype":"","method":"mp2","params":{"basis":"sto-3g"}}]:
      d["molecule"]=MOL; print(d["task"], d["method"], validate_draft(d, {"molecule":MOL}, check_external=False).status)'
  ```
  prints `ready` for all four. Feeding the same specs to `app.chemistry.jobs.preview.build_input_preview` raises.
- observed: `supports()` returns True and `route_engine()` actively picks an engine for each of:
  | task/subtype | engine | method | what the builder raises |
  |---|---|---|---|
  | `opt/min`, `opt/constrained` | pyscf (**default route**) | `mp2`, `ccsd` | `Unsupported method 'mp2' for PySCF (use 'hf' or 'dft')` — `pyscf_runner.build_mf`, reached from `run_geometry_optimization`'s final `build_mf(mol, method, ...)` at `pyscf_runner.py:1190` |
  | `opt/min`, `opt/constrained`, `opt_freq`, `freq`, `neb_ts` | orca | `mp2` | `Unsupported method 'mp2' for ORCA (use 'hf' or 'dft')` — `orca_runner._method_line` |
  | `neb_ts` | orca | `casscf` | same |
  | `opt/min`, `opt_freq` | bagel | `hf` | `BAGEL geometry optimization in this app only supports method='casscf' or 'caspt2'` |
  | `single_point/gs` | pyscf (**default route**), orca | `eom_ccsd` | `dispatch.resolve_runner` returns the plain `single_point` runner (the `eom_ccsd` branch is gated on `subtype == "ee"`), which then rejects the method |
  `route_engine("mp2", "opt", "min")` → `pyscf` with reason *"PYSCF is the preferred engine for this combination; ORCA could also run it"*; `route_engine("eom_ccsd", "single_point", "gs")` → `pyscf`; `route_engine("mp2", "freq", "")` → `orca` *"the only one here that can run it"*.
- expected: `docs/ARCHITECTURE.md` — "`supports()` is derived from that pairing and is never hand-enumerated … there is no allow-list". `_method_line`'s `hf`/`dft`-only rule and `bagel_runner`'s `"only supports method='casscf' or 'caspt2'"` are exactly the hardcoded capability knowledge `registry2` is supposed to be the single source of truth for (brief item 5), and they have drifted from it. Several of these cells rest on `manual` evidence — `orca/mp2 hessian="analytic"` ("documented; not executed here for MP2"), `pyscf/{mp2,ccsd} constrained_opt=True` ("geomeTRIC drives any method exposing a gradient; run here with HF") — which is the failure mode `docs/ARCHITECTURE.md` records for `orca/casscf excited_gradient`: "an untested claim that routes is worse than no claim".
- evidence: `app/chemistry/jobs/orca_runner.py:220-232` (`_method_line`); `app/chemistry/jobs/pyscf_runner.py:1190` and `build_mf`; `app/chemistry/jobs/bagel_runner.py:183-188`; `app/chemistry/jobs/dispatch.py::resolve_runner` (the `eom_ccsd` test sits inside `if subtype == "ee"`); `app/chemistry/registry2/capabilities.py:602-612` (`orca/mp2`)
- pointer: capability rows describe the *engine*; the builders describe *this app*. `docs/ARCHITECTURE.md` says a cell must describe what this app can deliver.
- note: two independent fixes. (a) Make the builders' scope declarative — a `methods=` allow-list on the `TaskDef`s, or downgrade the offending rows to `gap` with the diff recorded, exactly as `orca/casscf excited_gradient` was. (b) `resolve_runner` should test `method == "eom_ccsd"` before the `subtype` test, matching what `docs/ARCHITECTURE.md` says ("`eom_ccsd` is its own method value (on `single_point/gs` or `single_point/ee`)"). A cheap standing guard: fold the `build_input_preview` sweep above into `scripts/check_capability_matrix.py` as a sixth check.

### R-000: cancelling a master job erases its `path_xyz` / `ensemble_xyz` artifact pointers, so the geometries become unreachable
- surface: code:jobs
- class: bug
- severity: S2
- cause: CODE
- confidence: suspected (code read)
- found by: audit:jobs
- scope: every master task (`pes_1d`, `interp_pes`, `wigner_spectra`, `batch`) on every engine. Not an issue for ordinary jobs, whose runners had written no artifacts by the time they were cancelled.
- repro: submit a 5-point scan, cancel it while running, then try to open its frame slider / download its path / start a job from image 3.
- observed: `JobManager.cancel`'s master branch writes
  ```
  write_result(JobResult(job_id, "cancelled", error="Cancelled by user.",
                          summary=(read_result(job_id) or {}).get("summary", {})))
  ```
  (`base.py:1562-1564`). `summary` is carried over; `artifacts` is not — `JobResult.artifacts` defaults to `{}`, so `path_xyz` (written by `submit_scan`/`submit_batch`) and `ensemble_xyz` (written by `submit_ensemble`), plus any `pes_plot`/`ensemble_spectrum_data`, are dropped from `result.json`.
- expected: every reader resolves these through the artifacts dict, not through the fixed filename: `scan_orchestrator.py:206`, `batch_orchestrator.py:141` (`(master_result or {}).get("artifacts", {}).get("path_xyz")`), `server/routes/chat.py:285`, `server/routes/jobs.py:89-90`, and `registry2/tasks.py:507-510`'s `path_xyz`/`ensemble_xyz` map. The file itself is still on disk, so this is a lost pointer to real data — the brief's S1 category "a result that cannot be found later"; I file it S2 only because it needs a cancellation to trigger.
- evidence: `app/chemistry/jobs/base.py:1562-1564`
- pointer: `JobResult` has a mutable-default-shaped API where omitting a field means "erase it", and this is the one call site that rebuilds a result from a partial read.
- note: `artifacts=(read_result(job_id) or {}).get("artifacts", {})` alongside the existing summary carry-over. Same shape of bug, lower stakes, in `_watch_orphan_worker`'s two failure writes and `_run_inner`'s failure writes.

### R-000: ORCA oscillator strengths are parsed with a singlet-only row pattern, so any open-shell job silently reports none
- surface: code:jobs
- class: bug
- severity: S2
- cause: CODE
- confidence: suspected (code read)
- found by: audit:jobs
- scope: ORCA only, and all three of its intensity paths — `run_tddft`, `run_eom_ccsd`, `run_casscf`. PySCF gets intensities from objects, BAGEL from its own `Oscillator strength for transition between N - M` line, so neither is affected. I did **not** find a committed multiplicity>1 ORCA output to check against; `data/verified/` holds only `orca_functionals.txt`.
- repro: run any ORCA `single_point/ee` on a triplet (`multiplicity=3`) and read `summary.oscillator_strengths` — expect all `None`. Or, cheaper: `grep -n "0-1A" $(any real ORCA triplet output)`; ORCA labels those rows `0-3A -> 1-3A`.
- observed:
  ```
  _ABSORPTION_ROW = re.compile(
      r"0-1A\s*->\s*\d+-1A\s+-?\d+\.\d+\s+-?\d+\.\d+\s+-?\d+\.\d+\s+(-?\d+\.\d+)"
  )
  ```
  (`orca_runner.py:100-102`). The `1` in `0-1A`/`N-1A` is the state's *multiplicity*, hardcoded to singlet. On no match, each caller pads: `osc if len(osc) == len(ev) else osc + [None] * (len(ev) - len(osc))` (`orca_runner.py:1484`, `:1523`, `:1576`) — an empty list becomes all-`None` with no warning anywhere.
- expected: `docs/ARCHITECTURE.md` §Engine integration and the capability table both claim oscillator strengths for `orca/hf`, `orca/dft`, `orca/eom_ccsd` and `orca/casscf` without a multiplicity caveat, and the `wigner_spectra` task *requires* `osc_strengths` and force-routes CASSCF to ORCA for exactly that reason. A triplet Wigner ensemble therefore runs every sample and ends on "No sample contributed a usable (energy, oscillator strength) pair to pool" — the exact failure the requirement was added to prevent. The app already knows non-singlets reach this code: `_dominant_transitions_orca` is explicitly documented as restricted-only.
- evidence: `app/chemistry/jobs/orca_runner.py:100-102`; padding at `:1484` (tddft), `:1523` (eom_ccsd), `:1576` (casscf)
- pointer: a regex derived from one real run (a singlet) generalised to a class it does not cover, and a padding rule that turns "did not parse" into "engine does not report it".
- note: partial confirmation without a run — `grep -rhoE "[0-9]+-[0-9][A-Za-z']+ *-> *[0-9]+-[0-9][A-Za-z']+" data/scraped/orca/` returns rows including `0-1A  -> 10-3A` and `0-1A  ->  1-3A`, so the digit after the dash is unambiguously the state's multiplicity and the manual's own examples already contain values other than 1. What is still unconfirmed is only the left-hand side for a genuinely open-shell reference, which one water-triplet ORCA TDDFT run would settle. A second consequence falls out of the same evidence: on any run that computes singlets AND triplets, `_TDDFT_STATE` collects every state while `_ABSORPTION_ROW` collects only the singlet rows, and the padding then appends the Nones at the END — so the singlet intensities are silently attached to the wrong states. This app's own `_tddft_block` never asks for triplets, but a hand-edited input on a `tddft` job reaches the same parser through `_effective_input_text`. Fix direction: `r"0-(\d+)([A-Za-z0-9']+)\s*->\s*\d+-\1\2\s+..."`, and make an empty match raise inside `_safe_parse` rather than pad, so a parse failure is distinguishable from a genuine absence.

### R-000: startup reconciliation can overwrite a `result.json` written in the window between its own read and its `failed` write
- surface: code:jobs
- class: bug
- severity: S2
- cause: CODE
- confidence: suspected (code read)
- found by: audit:jobs
- scope: all engines; `_reconcile_orphaned_jobs` case 4 only (worker pid recorded but not alive-and-verified).
- repro: hard to force deliberately — kill the backend while a job is in its final `write_result`, restart immediately. The window is the several file reads between `read_result` and the `write_result(... "failed" ...)`.
- observed: the loop reads `result = read_result(job_id)` at `base.py:1118`, then does `read_spec`, `is_master_spec` (which imports `registry2.tasks`), `read_meta` and `_pid_is_same_process` (a `psutil.Process` lookup), and only then, at `base.py:1158-1165`, writes both a `failed` status and a `failed` `result.json` — clobbering whatever the worker may have written in between. `write_result` does not check the existing file.
- expected: the whole point of case 1 is that a worker's own result is authoritative; a worker that lands its result microseconds late should be treated as case 1, not case 4. This is the only path in the module that *replaces* a terminal result rather than syncing to it.
- evidence: `app/chemistry/jobs/base.py:1118` (`result = read_result(job_id)`) → `:1158-1165` (the `failed` write)
- pointer: read-then-write with no re-read at the point of decision, on the one branch that destroys data.
- note: re-read `result.json` immediately before the `failed` write and fall back to case 1 if it is now terminal. Cheap and complete.

### R-000: `_atomic_write_text`'s temp filename is keyed on pid alone, so two threads writing the same file in one process race
- surface: code:jobs
- class: bug
- severity: S3
- cause: CODE
- confidence: suspected (code read)
- found by: audit:jobs
- scope: every caller of `write_status`/`write_result`/`write_meta` — all engines, all tasks.
- repro: `cancel()` a running job at the moment `_run_inner` writes its terminal status. `cancel()`'s pending branch and `_run_inner`'s writes are documented in the code as able to interleave ("a harmless 'cancelled' -> briefly 'running' -> 'cancelled again' flicker"), and both go through `_atomic_write_text`.
- observed: `tmp = path.with_suffix(path.suffix + f".tmp{os.getpid()}")` (`base.py:216`). Two threads in the same process targeting the same `status.json` compute the *same* temp path. Thread A's `tmp.write_text` truncates while B is mid-write (torn content published by whichever `os.replace` wins), and — worse — A's `os.replace` unlinks the temp file, so B's `os.replace` can raise `FileNotFoundError`. In `_run_inner` the final `write_status(spec.job_id, result["status"], "done")` (`base.py:1806`) sits *outside* the surrounding try/except, so an exception there propagates into `_run`, whose `finally` still releases the scheduler slot but leaves `status.json` non-terminal while `result.json` says `completed`.
- expected: the temp name must be unique per writer. `docs/ARCHITECTURE.md` §"Status is written atomically" claims the rename makes concurrent writes safe; the rename is atomic, the temp file is not private.
- evidence: `app/chemistry/jobs/base.py:216`
- pointer: pid uniqueness was chosen against the cross-process case (a `docker compose exec` test process) and is not enough for the in-process case the same module documents as reachable.
- note: `f".tmp{os.getpid()}.{threading.get_ident()}"`, or `tempfile.mkstemp(dir=path.parent)`. Related: `read_status` maps a `JSONDecodeError` to `{"status": "pending"}` (`base.py:263-265`), so a torn `status.json` presents a finished job as queued until the next restart's reconciliation. Also worth noting that `result_artifact_transaction`'s docstring justifies its narrow lock with "those all write a *different* `job_id`" — `cancel()` on a master and the orchestrator's per-tick `write_result` of that same master violate that assumption.

### R-000: a malformed `spec.json` leaks a scheduler admission slot permanently and strands the job at `pending`, silently
- surface: code:jobs
- class: bug
- severity: S3
- cause: CODE
- confidence: suspected (code read)
- found by: audit:jobs
- scope: engine-independent; needs a `spec.json` that is valid JSON but not a valid `JobSpec` kwargs dict (an older/newer schema, a hand-edited file, a partially-written file that happens to parse).
- repro: place a `spec.json` containing `{"job_id": "x", "unexpected": 1}` in a job dir with a `pending` status, restart the backend.
- observed:
  ```
  spec_dict = read_spec(job_id)
  if spec_dict is None:
      self._scheduler.release(job_id); return
  spec = JobSpec(**spec_dict)          # base.py:1057 -- outside the try
  try:
      future = self._executor.submit(self._run, spec)
  except Exception:
      self._scheduler.release(job_id); raise
  ```
  A `TypeError` from `JobSpec(**spec_dict)` propagates out of `_on_admit` into `JobScheduler._dispatch_tick` and is swallowed by `_loop`'s `except Exception: pass` (`scheduler.py:179-181`) with no log line. By then `_pop_if_head` has already removed the job from the queue and added it to `_in_flight` (`scheduler.py:203-206`), and nothing will ever call `release` for it — the slot counts against `max_concurrent_jobs_total` and against that user's per-user cap for the life of the process, and the job sits at `pending` forever.
- expected: `_on_admit`'s own comments say the slot "has to be handed back here or it is held for the life of the process" — that reasoning covers the two branches inside the function but not the construction line above them.
- evidence: `app/chemistry/jobs/base.py:1049-1064`; `app/chemistry/jobs/scheduler.py:172-181`
- pointer: one statement outside the guarded region, plus a bare `pass` that makes the whole class of dispatcher failure invisible.
- note: move `JobSpec(**spec_dict)` inside the try, and log in `_loop`'s handler (`logger.exception("dispatch tick failed")`) — a silent dispatcher is the hardest thing here to diagnose, and the same `pass` hides any future exception from `_block_reason` (which does Postgres I/O) or `_resources_available`.

### R-000: cancelling a master races the orchestrator's next dispatch wave, leaving children nothing will cancel or aggregate
- surface: code:jobs
- class: bug
- severity: S3
- cause: CODE
- confidence: suspected (code read)
- found by: audit:jobs
- scope: `pes_1d`/`interp_pes` (`scan_orchestrator`), `wigner_spectra` (`ensemble_orchestrator`), `batch` (`batch_orchestrator`); all engines.
- repro: cancel a 40-image scan while its orchestrator tick is inside `_dispatch_more`. Look for sub-jobs whose `created_at` is after the master's cancellation.
- observed: `JobManager.cancel`'s master branch snapshots `sub_job_ids_of(job_id)`, cancels the non-terminal ones, and only then writes the master's own `cancelled` status (`base.py:1556-1565`). It takes neither the orchestrator's module-level `dispatch_lock` nor `base.master_dispatch_guard`. An orchestrator tick that entered `_dispatch_more` before the master's status flipped will submit its wave afterwards; those children are `pending`/`running`, are not in the snapshot, and their master is terminal so no later tick (`_iter_running_*_masters` filters on `status == "running"`) will ever reconcile them.
- expected: `docs/ARCHITECTURE.md` §"A master's dispatch is guarded across processes" makes "decide which sub-jobs exist, dispatch the missing ones" a guarded section; cancellation reads and invalidates exactly that state and should be inside the same guard.
- evidence: `app/chemistry/jobs/base.py:1556-1565`; `app/chemistry/jobs/scan_orchestrator.py:57` (`dispatch_lock`) and the equivalents in the other two orchestrators
- pointer: the guard was added for the double-dispatch race and not extended to the other writer of the same state.
- note: write the master's terminal status *first*, then cancel children, then re-read `sub_job_ids_of` once more and cancel any stragglers — or take `master_dispatch_guard(job_id)` around the whole branch. Cheap either way.

### R-000: `registry2` says ORCA has an analytic CASSCF Hessian; the runner, the architecture doc and the ORCA manual all say numerical
- surface: code:jobs
- class: bug
- severity: S3
- cause: CODE
- confidence: suspected (code read)
- found by: audit:jobs
- scope: ORCA CASSCF only. PySCF (`hessian="numerical"`, evidence `run`) and BAGEL (`numerical`, `run`) are consistent with their runners; I checked both.
- repro: `PYTHONPATH=$PWD python3 -c "from app.chemistry.registry2.tasks import supports; print(supports('orca','casscf','freq','').warnings)"` → `()`. Compare with `supports('bagel','casscf','freq','')`, which warns about the numerical Hessian's cost.
- observed: `capabilities.py:649` sets `hessian="analytic"` for `orca/casscf`, with `capabilities.py:670` `"hessian": _ev("manual", "documented; not executed here for CASSCF", _MANUALS)`. Meanwhile `orca_runner.build_input_text`'s frequency branch (`orca_runner.py:483-495`, the `NumFreq` bang line at `:491`) emits `NumFreq` for CASSCF with the comment *"the real ORCA manual states directly that CASSCF 'may be used for geometry optimizations and numerical frequency calculations' (analytic gradient, numerical Hessian only), so NumFreq here, not Freq"*, and `docs/ARCHITECTURE.md` §"CASSCF and CASPT2 gradients" says *"**ORCA** has an analytic gradient but a numerical-only Hessian"*.
- expected: the capability cell must describe what this app delivers. Two consequences: `docs/QM_CAPABILITIES.md:169` (the ORCA summary row) and `:213` (the per-cell row) (generated from this table) publishes "analytic (manual)" for `orca/casscf`, which is wrong; and `tasks._warn_numerical_hessian` only fires on `hessian == "numerical"`, so an ORCA CASSCF frequency job — genuinely `6·n_atoms` gradient evaluations — is approved with no cost warning while the same job on BAGEL or PySCF gets one.
- evidence: `app/chemistry/registry2/capabilities.py:649,670`; `app/chemistry/jobs/orca_runner.py:483-495`; `docs/ARCHITECTURE.md` §"CASSCF and CASPT2 gradients"; `docs/QM_CAPABILITIES.md:213`
- pointer: a `manual`-evidence cell transcribed from the manual's general statement rather than from the branch the runner actually emits — the same class the doc records for `orca/casscf excited_gradient`.
- note: change to `hessian="numerical"` with the runner's own citation as the evidence string, then re-run `scripts/generate_capability_docs.py --check` and `scripts/check_capability_matrix.py` (the golden table in the latter may also need the row corrected — worth checking, since a matching pair of mistakes is exactly what that script warns about).

### R-000: three orchestrators and the scheduler each re-walk every job directory on disk on a timer, so background cost scales with total jobs ever run
- surface: code:jobs
- class: perf
- severity: S3
- cause: CODE
- confidence: suspected (code read)
- found by: audit:jobs
- scope: engine-independent; process-wide. Measured nowhere — this is a read of the loops, not a profile.
  Two halves have different reach: the per-owner `_running_job_ids()` walk and the `all_owners`/`get_quota_config`
  round trips only happen when `QC_AGENT_DATABASE_URL` is set (`_concurrent_jobs_block_reason` returns None
  immediately otherwise), while the `rglob`-per-`submit()` claim below is the **no-auth** path — with auth,
  `enforce_quota()` defers to `app/auth/storage_quota.enforce_all_quotas()`, which is outside this area and which
  I did not audit. The four directory-walking timers are unconditional in both configurations.
- repro: populate `data/jobs/` with a few thousand terminal job directories and watch backend CPU / `strace -c -f -e trace=openat` with no jobs running at all.
- observed: four independent timers, each doing `JOBS_DIR.iterdir()` and then `read_spec` + `read_status` (two `stat`s and two `json.loads`) *per job on disk*:
  - `scan_orchestrator._iter_running_scan_masters` (`scan_orchestrator.py:111`), every 3.0 s
  - `ensemble_orchestrator._iter_running_ensemble_masters` (`ensemble_orchestrator.py:70`), every 3.0 s
  - `batch_orchestrator._iter_running_batch_masters` (`batch_orchestrator.py:47`), every 3.0 s
  - `app/agent/job_watcher.py`, every 2.0 s
  plus `base._running_job_ids()` (`base.py:625-646`), called from `_concurrent_jobs_block_reason` **once per owner per dispatch tick** — so with `k` owners queued the scheduler walks the whole directory `k` times a second, and each call additionally does a `get_quota_config()` and an `all_owners("job")` Postgres round trip.
  Separately, `quota.enforce_quota()` runs inside every single `submit()` under `_quota_lock` (`base.py:1247-1249`) and, for every non-terminal job, does a full uncached `_dir_size` `rglob` (`quota.py:65-71`, `:108-118`). Wave dispatch calls `submit()` once per child, so dispatching a 40-child wave runs 40 quota sweeps, each `rglob`-ing up to 20 live ORCA/BAGEL scratch directories.
  Finally, when the host has no headroom, `_dispatch_tick` writes a fresh `status.json` for *every* queued job of *every* owner on every ~1 s tick (`scheduler.py:251-253`).
- expected: `docs/ARCHITECTURE.md` already made this argument once for `sub_job_ids_of` — P7.3 replaced a `JOBS_DIR` walk with a per-master `children.jsonl` manifest precisely because "its cost scales with EVERY job ever run, not with this master's own child count". The same reasoning applies to the four loops above, which were not converted.
- evidence: `app/chemistry/jobs/scan_orchestrator.py:111-121`; `app/chemistry/jobs/ensemble_orchestrator.py:70`; `app/chemistry/jobs/batch_orchestrator.py:47`; `app/chemistry/jobs/base.py:625-646`, `:1247-1249`; `app/chemistry/jobs/quota.py:65-71`; `app/chemistry/jobs/scheduler.py:251-253`
- pointer: "find the running masters" and "count the running jobs" are both answered by scanning the archive of everything that ever ran.
- note: the cheapest real fix is one shared, short-TTL (~1 s) in-process cache of `{job_id: (task, status)}` invalidated by `write_status`, consumed by all four loops and by `_running_job_ids` — the caps are already documented as "soft, eventually-consistent". Second: hoist `_running_job_ids()` out of `_concurrent_jobs_block_reason` and compute it once per `_dispatch_tick`. Third: call `enforce_quota()` once per wave rather than once per child (or move it to `job_watcher`'s existing `_QUOTA_ENFORCE_EVERY_N_TICKS` path, which already exists). Fourth: only rewrite a queued job's `status.json` when the message actually changes.

### R-000: ORCA multi-state gradient / multi-pair NAC subdirectories are never scratch-cleaned
- surface: code:jobs
- class: perf
- severity: S3
- cause: CODE
- confidence: suspected (code read)
- found by: audit:jobs
- scope: ORCA only, and only the multi-entry paths (`len(target_states) > 1` or `len(state_pairs) > 1`). BAGEL and PySCF write no subdirectories.
- repro: run an ORCA `single_point/grad` with `target_states=[1,2,3]` and `du -sh` the job directory after it completes; compare with a single-state run.
- observed: `run_gradient` and `run_nac` create `state_<n>/` and `pair_<a>_<b>/` subdirectories and run a full ORCA process in each (`orca_runner.py:943-948`, `:1026-1030`). `scratch.cleanup_scratch_files` only ever looks at the top level: `_orca_scratch_files` returns `[f for f in job_dir.iterdir() if f.name.startswith("input") ...]` (`scratch.py:70`), and the delete loop is additionally gated on `f.is_file()`. So every per-state ORCA scratch set — the module docstring cites ~60 MB for one CASSCF/cc-pVDZ run — survives in full, one copy per state or pair.
- expected: the module exists precisely so "ORCA/BAGEL's large intermediate files … don't accumulate indefinitely". The leftovers are also billed to the owner's storage quota via `quota._dir_size`'s `rglob`, and re-walked by every uncached quota sweep.
- evidence: `app/chemistry/jobs/scratch.py:70`; `app/chemistry/jobs/orca_runner.py:943-948`, `:1026-1030`
- pointer: the cleanup allowlist predates the one-process-per-target layout added with multi-state derivatives.
- note: recurse into direct subdirectories in `_orca_scratch_files` (the same `input*` allowlist applies unchanged there), keeping the protected-basename cross-check. Related and smaller: a job finalised by `_watch_orphan_worker` never runs `cleanup_scratch_files` at all — only `JobManager._run`'s `finally` calls it.

### R-000: MC-PDFT's documented state reordering is noted only on the energy runner, and the derived excitation/total-energy fields still assume state 0 is the ground state
- surface: code:jobs
- class: bug
- severity: S3
- cause: CODE
- confidence: suspected (code read)
- found by: audit:jobs
- scope: PySCF `mcpdft` (the only engine with it). `lpdft`/`cmspdft` diagonalise an effective Hamiltonian, so ascending order is expected there; I did not verify that claim independently. Not applicable to ORCA/BAGEL.
- repro: run a state-averaged MC-PDFT job on a system where the MC-PDFT ordering differs from the SA-CASSCF ordering, then read `summary.excitation_energies_eV[0]` (expect a negative number) and `summary.total_energy_hartree` (expect the second-lowest state).
- observed: `_state_energies_from` returns `mc.e_states` in SA-CASSCF label order with no sort (`pyscf_runner.py:1771-1783`; `grep -n "sort\|argsort" pyscf_runner.py` finds only `sort_mo` and unrelated uses). `run_pdft_family` correctly writes `summary["mcpdft_state_order_note"]` explaining this (`pyscf_runner.py:2120-2125`) — but `grep -rn mcpdft_state_order_note app/` returns that one line only, so `run_gradient`'s PDFT branch and `run_nac` report the same ladder with no note. Meanwhile `derivatives.excitation_energies_eV` computes `(e - states[0]) * HARTREE_TO_EV` (`derivatives.py:74`) and `facts.canonicalize` sets `total_energy_hartree = states[0]` when no scalar energy is present (`facts.py:356`), both under names that assert "ground state".
- expected: `docs/QM_CAPABILITIES.md:73` and `capabilities.py:375` both record that "states can come out reordered against their MCSCF labels"; the brief asks whether the code honours it. It half does.
- evidence: `app/chemistry/jobs/pyscf_runner.py:1771-1783`, `:2120-2125`; `app/chemistry/jobs/derivatives.py:74`; `app/chemistry/jobs/facts.py` `canonicalize`'s `total_energy_hartree = states[0]` fallback at `facts.py:356`
- pointer: a caveat written as prose on one runner rather than as a property of the ladder every reader consumes.
- note: two options, and the maintainer should pick — either sort the MC-PDFT ladder ascending and remap `target_states` accordingly (changes what "S1" means for a gradient), or leave the order and have `facts` emit `total_energy_hartree = min(states)` plus carry the note onto every summary that carries `state_energies_hartree` for `method == "mcpdft"`. Confirming it needs one real reordering case; a negative `excitation_energies_eV[0]` in any existing MC-PDFT `result.json` on disk would settle it immediately.

### R-000: a PES-scan plot's "State 1" is S1, while `target_states=[1]` is S0
- surface: code:jobs
- class: comfort
- severity: S4
- cause: CODE
- confidence: suspected (code read)
- found by: audit:jobs
- scope: `pes_1d`/`interp_pes` excited-state scans, all engines.
- observed: `_build_state_series` labels index 0 `"Ground state"` and index `i` `f"State {i}"` (`scan_orchestrator.py:103-106`), so the legend's "State 1" is the first excited state. `target_states`/`state_pairs` use the opposite convention (state 1 is S0), stated explicitly in `derivatives.py:52-63` and `docs/ARCHITECTURE.md`.
- expected: one user-facing numbering. The architecture already flags this as "one numbering trap … there are two conventions in the codebase and they differ by one".
- evidence: `app/chemistry/jobs/scan_orchestrator.py:103-106`
- pointer: two independently reasonable labelling choices meeting in one UI.
- note: `"S0"` / `f"S{i}"` in the legend would be unambiguous and matches how ORCA's own multi-run headers are written elsewhere in this codebase (`f"===== state S{state - 1} ====="`, `orca_runner.py:961`).

### R-000: BAGEL per-atom gradient/NAC vectors are assembled without checking the atom count
- surface: code:jobs
- class: bug
- severity: S3
- cause: CODE
- confidence: suspected (code read)
- found by: audit:jobs
- scope: BAGEL only (`run_gradient`, `run_nac`). ORCA reads `.engrad` (a length-checked structured file) for gradients; PySCF returns arrays.
- observed: `_parse_atom_vectors` builds `{int(idx): [x, y, z]}` from `_BAGEL_ATOM_VEC.findall(section)` and returns `[by_index[i] for i in sorted(by_index)]` (`bagel_runner.py:863-866`). Any atom row the regex misses is simply absent: the returned vector is shorter than the molecule and every downstream consumer (the derivative norm, the frontend's per-atom arrow overlay) silently reads atom *k*'s vector as belonging to atom *k*. Nothing compares `len(vector)` with `len(molecule["symbols"])`.
- expected: the module already treats a request/result count mismatch as a hard failure ("refusing to guess which state each belongs to", `bagel_runner.py:1312-1316`); the same standard should apply one level down, to atoms.
- evidence: `app/chemistry/jobs/bagel_runner.py:863-866`
- pointer: dict-then-sort silently tolerates gaps, where a list-append plus a length assertion would not.
- note: low confidence that the regex ever *does* miss a row on real BAGEL output — I have no committed BAGEL derivative output to check. Cheap and unambiguous fix regardless: raise if `len(vector) != len(molecule["symbols"])`, alongside the existing section-count check.

---

## Checked and clean

Recorded because a negative result is useful. Each of these was read in full or
verified mechanically; none produced a finding.

- **Registry ↔ runner wiring.** For every `(task, subtype, engine, method)` cell
  `tasks.supports()` returns True (master tasks excluded), `dispatch.resolve_runner`
  returns a key and that key is present in the corresponding
  `{engine}_worker.DISPATCH`. **0 gaps**, over 3 engines × 11 canonical methods ×
  all `TASKS` entries. Script (run as given, import-and-print only):
  ```
  cd /data/qcuser/9.NexusQC/NexusQC-dev-repo && PYTHONPATH=$PWD \
  QC_AGENT_LLM_BASE_URL=http://localhost:11434/v1 \
  /home/qcuser/apps/miniconda3/envs/qc-agent/bin/python3 -c '
  import importlib
  from app.chemistry.registry2.capabilities import CANONICAL_METHODS, ENGINES
  from app.chemistry.registry2.tasks import TASKS, supports
  from app.chemistry.jobs.dispatch import resolve_runner
  W = {e: importlib.import_module(f"app.chemistry.jobs.{e}_worker").DISPATCH for e in ENGINES}
  bad = []
  for _, td in sorted(TASKS.items()):
    if td.master and td.task != "blind": continue
    for e in ENGINES:
      for m in CANONICAL_METHODS:
        if not supports(e, m, td.task, td.subtype): continue
        rk, err = resolve_runner(td.task, td.subtype, m)
        if rk is None or rk not in W[e]: bad.append((td.name, e, m, rk, err))
  print("gaps:", len(bad)); [print(b) for b in bad]'
  ```
- **`route_engine()` never contradicts `supports()`.** Same cross-product,
  comparing `route_engine(method, task, subtype).engine` against
  `supports(that_engine, ...)`: **0 mismatches**. (The cells that *do* fail are
  the input-builder ones filed above — the disagreement is between the registry
  and the runners, not inside the registry.)
- **1-based/0-based state conversion for `single_point/grad` and `single_point/nac`,
  all three engines.** ORCA `_nac_block`: `iroot = next(s for s in pair if s != 1) - 1`
  (pair `[1,2]` → `IROOT 1`, correct). BAGEL: `{"title": "force", "target": s - 1}`
  and `{"title": "nacme", "target": p[0]-1, "target2": p[1]-1}`. PySCF: `root = state - 1`
  into `tdscf`'s 1-based-over-excited-roots `state=`, with `excitation_energies[root-1]`
  for the paired energy; SA-CASSCF NAC `state=(p[0]-1, p[1]-1)`. All consistent with
  `derivatives.py`'s stated convention. The only defect found here is the ORCA
  ground-state fallback filed as the first S1 above.
- **BAGEL's NACME sections are keyed by the pair BAGEL announces**, not by request
  position (`_parse_nacme_sections`, `_BAGEL_NACME_TARGETS`), and gradient sections
  are walked in order with a hard count check — the `sections[-1]` bug
  `docs/ARCHITECTURE.md` records is genuinely fixed.
- **Constraint atom indexing.** ORCA converts 1-based → 0-based exactly once
  (`_constraints_lines`, `str(a - 1)`, matching the manual's `{ B N1 N2 value C }`);
  PySCF passes 1-based straight through to geomeTRIC, which does its own `int(i) - 1`
  (verified against the docstring's claim about `geometric/prepare.py`). BAGEL has no
  constrained-opt path and the capability row says so.
- **Wigner unit directions.** `sigma_q = sqrt(1/(2·mu_au·omega_au))` in atomic units →
  bohr; `sigmas_angstrom = sigmas_bohr * nist.BOHR` (multiply, correct); the diagnostic
  converts back with `Q_bohr = Q / nist.BOHR` (divide, correct). Modes are explicitly
  unit-normalised before `sigma_q` is applied, and reduced masses are recomputed with
  the rescale-invariant formula, matching `docs/ARCHITECTURE.md`'s account of the fixed bug.
- **Energy conversion constants.** Every literal `27.211386245988`, `1239.841984`,
  `0.52917721067` and `2.5417464519` in `app/chemistry/jobs/` and `app/chemistry/cas/`
  agrees with `app/chemistry/units.py`'s CODATA-2018 table; each is applied once and in
  the right direction (checked individually, including `scan_orchestrator`'s inverted
  `_HARTREE_PER_EV`, which is used as `* _HARTREE_PER_EV` for eV→hartree at l.99 and
  `/ _HARTREE_PER_EV` for hartree→eV at l.334). `units.unit_of_field` matches the
  `_eV`/`_hartree`/`_cm-1`/`_kcal_mol` suffixes correctly on lowercased names.
- **ORCA parser block anchoring.** `_CASSCF_BLOCK` anchors on the post-convergence
  `CAS-SCF STATES FOR BLOCK` header rather than the identically-shaped `INITIAL CI STATE
  CHECK`; `_FINAL_ENERGY.findall(output)[-1]` takes the last, not the first;
  `_EOM_RHS_SECTION` and `_EOM_LEFT_RIGHT_SECTION` are bounded so the LHS block is not
  double-counted; `_ELECTRIC_DIPOLE_SECTION` is bounded to the first of ORCA's four
  absorption tables. The only ORCA parser defect found is the singlet-only
  `_ABSORPTION_ROW` filed above.
- **Scratch cleanup protects declared artifacts.** `_artifact_filenames` walks
  `result.json`'s `artifacts` recursively (including the nested `cubes` dict) and every
  candidate is cross-checked against it plus `_PROTECTED_NAMES`; `input.gbw` and
  `orbitals.archive` are kept unconditionally for later orbital reuse; failed/cancelled
  and `blind` BAGEL jobs fall back to the narrow `*.log` rule. The only gap is the
  un-recursed subdirectory case filed above.
- **`facts.canonicalize`.** One energy name with all aliases removed; `_state_counts`
  derived from the arrays rather than from the ambiguous `n_states` parameter;
  `_align_to_excited_states` correctly skipped for a coupling result (`per_pair`);
  `frontier_orbitals` groups by spin channel before picking a HOMO and nulls a 0.0 eV
  BAGEL active-orbital energy with the reason attached. Idempotent as documented.
- **`app/chemistry/molecule.py`** (read in full). No atom index ever reaches a user or the
  model from here: every constructor iterates `mol.GetAtoms()` in RDKit order and appends to
  parallel `symbols`/`coords` lists (`molecule.py:92-96`, `:136-140`, `:337-341`), so there is
  no 0-based/1-based boundary to get wrong. `GetIdx()` is used only to look up a conformer
  position for the atom being iterated. Atom numbering becomes user-visible only in
  `geometry_resolve.measure_geometry_parameter`, which does the single `a - 1` conversion
  (`geometry_resolve.py:39`) with a comment saying so.
- **Orbital indices inside `dominant_transitions` are 1-based and line up with `orbital_table`.**
  ORCA TDDFT/CIS contribution lines are 0-based spin-orbital indices and are converted at
  `orca_runner.py:1360` (`(int(a) + 1, int(b) + 1, ...)`); the EOM-CCSD amplitude lines the same
  way at `:1388`. `ci_transitions.py:144` offsets a CASSCF configuration-string position by the
  closed-shell count *and* one — `pair = (n_closed + sources[0] + 1, n_closed + targets[0] + 1)` —
  so active orbital 0 renders as orbital `n_closed + 1`, which is that orbital's own row index in
  the 1-based `orbital_table`. Checked on all three engines' paths.
- **`copy.py` rewrites artifact paths onto the new job id.** `_copy_one` sets
  `result["job_id"] = dst_id` and passes the whole artifacts tree through `_rewrite_artifacts`
  (`copy.py:185-188`), whose `_rewritten_path` re-roots each absolute path as
  `JOBS_DIR / dst_id / rel` (`copy.py:91-97`), recursing into nested dicts and lists. `spec.json`
  gets the new id and, for a family copy, the new `parent_job_id`. So a shared or copied job's
  artifacts do not point back at the source, and deleting the source does not orphan them —
  matching `docs/ARCHITECTURE.md` §"Two things a directory copy alone gets wrong".
- **Deliberate decisions verified intact**, not filed: `server/routes/jobs.py` takes no
  graph lock and does not call `read_state()`; no `invalidate_graph_cache()` call
  appears anywhere under `app/chemistry/jobs/`; `spec.json` is write-once and `meta.json`
  is the mutable file; masters are excluded from `_running_job_ids` on purpose;
  `geometry_set` bypasses the executor entirely and is written terminal immediately.
