# Configuration reference

Every setting lives in [`app/config.py`](../app/config.py) and is overridable by
environment variable. Values are read from a project-root `.env` file if one
exists, so a single file drives both a bare-metal run and the Docker deployment.
An explicitly exported environment variable always wins over the file.

For variables that only matter to the multi-user Docker deployment, database,
sessions, rate limiting, nginx. See [DEPLOYMENT.md](DEPLOYMENT.md#deployment-environment-variables).

## Model and embeddings

| Variable | Default | Purpose |
|---|---|---|
| `QC_AGENT_LLM_MODEL` | `qwen3.8:27b` | Ollama model for the agent. Requires Ollama v0.32.13 or newer |
| `QC_AGENT_LLM_BASE_URL` | `http://localhost:11434/v1` | Ollama's OpenAI-compatible endpoint |
| `QC_AGENT_LLM_TEMPERATURE` | `0.1` | Sampling temperature |
| `QC_AGENT_EMBEDDING_MODEL` | `nomic-embed-text` | Embedding model for the knowledge base |
| `QC_AGENT_OLLAMA_EMBEDDING_TIMEOUT` | `30` s | Bounds how long a stalled embedding request can hold the agent's per-conversation lock |
| `QC_AGENT_MODEL_KEEPALIVE_INTERVAL` | `60` s | How often to re-assert that the chat model stays loaded in VRAM; `0` disables |
| `QC_AGENT_LLM_NUM_CTX` | `32768` | **What the served model's context window actually is.** A declaration, not a request: the app cannot change the window (`num_ctx` sent through Ollama's `/v1` endpoint is silently dropped, same as `keep_alive`), it can only budget conversation history to stay inside it. Set it to the number `ollama ps` prints in its CONTEXT column. Too low just shortens the agent's memory; **too high overruns the window and replies get cut off mid-sentence with no error anywhere**. If the cut lands before a tool call, an approval card silently never appears. The default is deliberately conservative for that reason. See [MODEL_CONTEXT_BUDGET.md](MODEL_CONTEXT_BUDGET.md) |
| `QC_AGENT_LLM_MAX_TOKENS` | `1024` | Cap on a single reply's length. Also sets the output headroom held back from the history budget, at twice this value |
| `QC_AGENT_LLM_FIXED_PROMPT_TOKENS` | `10000` | What the system prompt and tool schemas cost on every call before any conversation. Measured at 8,668 tokens with 16 tools on 2026-08-24; `tests/backend/agent_01_token_budget.py` re-measures it. Raise it only alongside a real measurement |
| `QC_AGENT_LLM_HISTORY_FLOOR` | `4` | Messages always kept, whatever they cost. A single job result can exceed the whole budget on its own, and answering with no context at all is worse than answering over budget. When the floor is what is holding messages in, a warning says so |
| `QC_AGENT_LLM_HISTORY_WINDOW` | `40` | Most recent messages kept in a turn's history. Trimming is mechanical, a window plus a one-line digest of what the conversation has established, not an LLM-written summary, which would cost an extra model call and risks inventing a job id that never existed. This bounds message **count** and is no longer the binding cap; the token budget above is what protects the window |

Ollama unloads an idle model after about five minutes, and reloading the chat
model measured 11.4 s against 2.9 s warm on the lab host. A wait always paid by
whoever sends the first message after a quiet spell. A background thread
(`app/agent/model_warmer.py`) keeps it resident by calling Ollama's **native**
`/api/generate` with `keep_alive: -1` and no prompt, which loads without
generating.

Two things worth knowing before changing this:

- It re-asserts on an interval rather than setting the flag once, because
  `keep_alive: -1` is not a reservation, on a shared Ollama another tenant
  loading a model can still evict this one, and nothing would otherwise put it
  back.
- It cannot be replaced by passing `keep_alive` through the chat client.
  Ollama's **OpenAI-compatible** `/v1` endpoint, which is what
  `QC_AGENT_LLM_BASE_URL` points at, silently ignores that field. Verified by
  sending `keep_alive: "10m"` and watching `ollama ps` keep the default TTL.

Set it to `0` on a host where holding the model resident is unwelcome (a shared
GPU that other tenants need), at the cost of a cold load after each idle period.
Only the chat model is kept warm; the embedding model cold-loads in under a
second and is left alone.

## Quantum chemistry engines

ORCA and BAGEL are optional, separately licensed, and never bundled. The defaults
below are placeholders, set them to your own install locations.

| Variable | Default | Purpose |
|---|---|---|
| `QC_AGENT_ORCA_BIN` | `/opt/orca/orca` | Path to the ORCA executable. `orca_plot` is expected alongside it |
| `QC_AGENT_BAGEL_BIN` | `/opt/bagel/bin/BAGEL` | Path to the BAGEL executable |
| `QC_AGENT_BAGEL_SETVARS` | `/opt/intel/oneapi/setvars.sh` | Intel oneAPI environment script, sourced before BAGEL runs |
| `QC_AGENT_BAGEL_EXTRA_LIB_DIRS` | `/opt/boost/lib:/opt/scalapack/lib:/opt/openblas/lib` | Colon-separated directories prepended to `LD_LIBRARY_PATH` **for BAGEL's subprocess only**. BAGEL's Boost/ScaLAPACK/OpenBLAS dependencies are usually site-installed rather than system packages. Scoped deliberately: a container-wide override risks the wrong library being picked up by a different engine |
| `QC_AGENT_MPIRUN_BIN` | `/usr/bin/mpirun` | MPI launcher used by ORCA |

## Job execution and resource limits

| Variable | Default | Purpose |
|---|---|---|
| `QC_AGENT_N_CORES` | `4` | Cores a **single** job runs on, on any of the three engines (ORCA MPI ranks, PySCF/BAGEL threads), and the number of idle cores the admission gate waits for before starting one |
| `QC_AGENT_MAX_CONCURRENT_JOBS` | `20` | Worker-pool size, fixed at process start. The hard ceiling the admin console's editable concurrency setting can never exceed |
| `QC_AGENT_MAX_CPU_PERCENT` | `80` | Admission gate: hold new jobs back once the **host's** average CPU is at or above this |
| `QC_AGENT_MAX_MEM_PERCENT` | `80` | Admission gate: hold new jobs back once the host is this full on memory |
| `QC_AGENT_CORE_IDLE_THRESHOLD_PERCENT` | `20` | Admission gate: a job also waits until at least `N_CORES` individual cores are each under this busy percentage |

> **NexusQC does not limit itself to a fixed slice of the machine.** Every
> logical core is available to it; what protects the host is the load-based
> admission gate above, not a core budget. At the defaults, up to
> **20 concurrent jobs × 4 cores = 80 cores** may be in flight, and a job only
> starts when the host genuinely has room for it, so an idle machine gets used
> and a busy one is left alone.
>
> **`QC_AGENT_N_CORES` is per-job width, not a total.** Raise it for wide single
> jobs on a large machine; lower it to favour many small jobs. Setting it near
> the machine's total core count is the one genuinely dangerous choice: the gate
> then waits for nearly every core to be simultaneously idle, which on a busy
> host never happens, and every job sits at `pending` indefinitely with no error
> to explain it. The app logs the resolved value at startup for this reason.
>
> Earlier versions auto-detected this by shelling out to `nproc`. That was
> removed: `nproc` reports `OMP_NUM_THREADS` when it is set, which says nothing
> about the machine, and reports every host core inside a container, which
> produced exactly the hang described above.
>
> **The cap is applied to the engine's subprocess, not requested politely.**
> `OMP_NUM_THREADS`, `MKL_NUM_THREADS` and `OPENBLAS_NUM_THREADS` are set on
> every worker the job manager spawns, `BAGEL_NUM_THREADS` on top for BAGEL
> (which reads its own variable first), and ORCA gets one thread per rank
> because its width comes from `%pal nprocs` instead. An ORCA input this app did
> not build has its `%pal` clamped to `N_CORES` on the way to disk.
> `PYTHONPATH=$PWD python3 scripts/spikes/spike_thread_caps.py` checks all of
> this against real running jobs.

## Multi-reference convergence

Applied identically across all three engines and every job type, rather than
inheriting each engine's own differing defaults.

| Variable | Default | Purpose |
|---|---|---|
| `QC_AGENT_CASSCF_CONV_TOL_ENERGY` | `1e-6` | Energy convergence for energy-only CASSCF/CASPT2 jobs |
| `QC_AGENT_CASSCF_CONV_TOL_OPT_FREQ` | `1e-7` | Convergence for geometry-optimisation and frequency jobs. Tighter, because a loosely converged wavefunction shows up as noise in a gradient or Hessian |
| `QC_AGENT_CASSCF_MAX_CYCLE_MACRO` | `200` | Maximum CASSCF macro-iterations |

## External services

| Variable | Default | Purpose |
|---|---|---|
| `QC_AGENT_MOLECULE_LOOKUP_TIMEOUT` | `15` s | Timeout on PubChem name resolution. Applied as a scoped socket timeout because the client library offers no timeout parameter of its own |
| `QC_AGENT_WEB_SEARCH_TIMEOUT` | `10` s | Per-engine timeout for web search |
| `QC_AGENT_SEMANTIC_SCHOLAR_API_KEY` | *none* | Optional free API key for more reliable literature search. Degrades gracefully without one |
| `QC_AGENT_SCRAPER_CONTACT` | project URL | Identifies the crawler in the User-Agent when ingesting manual pages. Set it to your own contact if you run a crawl of any size |

## Miscellaneous

| Variable | Default | Purpose |
|---|---|---|
| `QC_AGENT_SERVER_CORS_ORIGINS` | `http://localhost:5173,http://127.0.0.1:5173` | Allowed browser origins |
| `QC_AGENT_IMAGINARY_FREQ_THRESHOLD_CM1` | `50` | Magnitude below which a negative frequency is treated as numerical noise rather than a genuine imaginary mode. Single source of truth for all three engines and the UI |
| `QC_AGENT_DRAFT_HOLD_SECONDS` | `900` s | How long a draft that is never submitted or rejected keeps a finished job's summary waiting. Setting up a calculation always takes precedence over reporting on one, and that part is not tunable; this only bounds what happens to a draft nobody finishes, so an abandoned one cannot silence a conversation's summaries for good. Timed from the last change to the draft. `0` waits indefinitely |

---

# Job parameter defaults

Every default below lives in
[`app/chemistry/registry2/params.py`](../app/chemistry/registry2/params.py)'s
`PARAMS` tuple, which the agent's elicitation flow consults directly. This
table is a transcription of it, not separate policy, and it's worth
re-generating from source if the two ever seem to disagree.

This is the taxonomy the 2026 overhaul rebuilt from the ground up, so if
you're looking at an older note that mentions `geometry_optimization`,
`casscf`, `tddft`, `mo_visualization`, `pes_scan`, or `recommend_active_space`
as job types, those names are gone. Tasks are now `single_point` (subtypes
`gs`/`ee`/`nac`/`grad`), `opt` (subtypes `constrained`/`ci`), `freq`,
`opt_freq`, `pes_1d`, `interp_pes`, `neb_ts`, `batch`, `wigner_spectra`,
`cas_reco` (subtypes `explain`/`autocas`/`avas`), and `blind`. Rendering
molecular orbitals, in particular, stopped being its own job type. It's now
just the `orbital_indices` parameter on an ordinary `single_point`, since
looking at orbitals from a calculation isn't a different calculation.

**Any parameter not listed here has no default and is required**. The agent
asks for it explicitly rather than guessing. Guessing a basis set or an
active space produces a plausible-looking wrong answer, and that's worse
than a question.

| Task / subtype | Parameter | Default | Notes |
|---|---|---|---|
| `opt`, `opt_freq`, `neb_ts` | `max_steps` | `200` | Optimizer step cap, all three engines |
| `freq`, `opt_freq`, `wigner_spectra` | `temperature_K` | `298.15` | Thermochemistry / sampling temperature |
| `single_point/ee`, `wigner_spectra` | `use_tda` | `False` | Full TDDFT/TD-HF is the default; the Tamm–Dancoff approximation is opt-in, not the other way around |
| `single_point/ee` | `want_oscillator_strengths` | `False` | Routes a CASSCF request to ORCA automatically. The only engine here that computes them for CASSCF |
| `wigner_spectra` | `want_oscillator_strengths` | `True`, always | Not a choice for an ensemble spectrum. The spectrum is a Gaussian convolution weighted by the intensities, so the task requires the capability and the engine is chosen to provide it |
| `interp_pes` | `interpolation_method` | `idpp` | `liic` and `linear` are the alternatives |
| `neb_ts` | `n_images` | `6` | Movable images between the two fixed endpoints |
| `wigner_spectra` | `fwhm_eV` | `0.2` | Gaussian broadening applied when the spectrum is rendered. Half what a single geometry's UV/Vis spectrum uses, an ensemble already carries its band width in the spread of its samples |
| `wigner_spectra` | `low_freq_cutoff_cm1` | `100.0` | Modes below this are excluded as translational/rotational residue |
| `cas_reco/autocas` | `entropy_method` | `exact_fci` | `dmrg` is the opt-in alternative. Screens a larger candidate pool at the cost of an approximate entropy estimate |
| `cas_reco/autocas`, `cas_reco/avas` | `max_active_orbitals` | `12` | Ceiling on the recommended space; can only narrow it, never widen past 12 |
| `single_point` | `isoval` | `0.04` | Orbital cube isosurface value, only shown once `orbital_indices` is actually set |
| any CASSCF/CASPT2 task without excited states asked | `n_states`, `weights` | `1`, equal | Where `n_states` isn't required (a plain ground-state `single_point/gs`, `opt`, or `freq`), it falls back to 1 rather than being asked |

A few defaults live one layer down, inside the BAGEL and ORCA runners rather
than in the declarative registry above, real, but not something the agent
elicits or shows on an approval card, since they've never yet needed to be
user-tunable:

| Runner | Parameter | Default | Notes |
|---|---|---|---|
| `bagel_runner.py` (`caspt2`) | `ms_caspt2` | `True` | Multi-state CASPT2 |
| `bagel_runner.py` (`caspt2`) | `shift` | `0.2` | Level shift against intruder states |
| `bagel_runner.py` (`caspt2`) | `frozen_core` | `True` | Freezes core orbitals in the correlation treatment |
| `orca_runner.py` (orbital cubes) | `cube_grid_points` | `80` | Grid resolution for a rendered orbital cube, ORCA only |
