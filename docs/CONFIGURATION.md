# Configuration reference

Every setting lives in [`app/config.py`](../app/config.py) and is overridable by
environment variable. Values are read from a project-root `.env` file if one
exists, so a single file drives both a bare-metal run and the Docker deployment.
An explicitly exported environment variable always wins over the file.

For variables that only matter to the multi-user Docker deployment — database,
sessions, rate limiting, nginx — see [DEPLOYMENT.md](DEPLOYMENT.md#deployment-environment-variables).

## Model and embeddings

| Variable | Default | Purpose |
|---|---|---|
| `QC_AGENT_LLM_MODEL` | `qwen3.8:27b` | Ollama model for the agent. Requires Ollama v0.32.13 or newer |
| `QC_AGENT_LLM_BASE_URL` | `http://localhost:11434/v1` | Ollama's OpenAI-compatible endpoint |
| `QC_AGENT_LLM_TEMPERATURE` | `0.1` | Sampling temperature |
| `QC_AGENT_EMBEDDING_MODEL` | `nomic-embed-text` | Embedding model for the knowledge base |
| `QC_AGENT_OLLAMA_EMBEDDING_TIMEOUT` | `30` s | Bounds how long a stalled embedding request can hold the agent's per-conversation lock |
| `QC_AGENT_MODEL_KEEPALIVE_INTERVAL` | `60` s | How often to re-assert that the chat model stays loaded in VRAM; `0` disables |

Ollama unloads an idle model after about five minutes, and reloading the chat
model measured 11.4 s against 2.9 s warm on the lab host — a wait always paid by
whoever sends the first message after a quiet spell. A background thread
(`app/agent/model_warmer.py`) keeps it resident by calling Ollama's **native**
`/api/generate` with `keep_alive: -1` and no prompt, which loads without
generating.

Two things worth knowing before changing this:

- It re-asserts on an interval rather than setting the flag once, because
  `keep_alive: -1` is not a reservation — on a shared Ollama another tenant
  loading a model can still evict this one, and nothing would otherwise put it
  back.
- It cannot be replaced by passing `keep_alive` through the chat client.
  Ollama's **OpenAI-compatible** `/v1` endpoint, which is what
  `QC_AGENT_LLM_BASE_URL` points at, silently ignores that field — verified by
  sending `keep_alive: "10m"` and watching `ollama ps` keep the default TTL.

Set it to `0` on a host where holding the model resident is unwelcome (a shared
GPU that other tenants need), at the cost of a cold load after each idle period.
Only the chat model is kept warm; the embedding model cold-loads in under a
second and is left alone.

## Quantum chemistry engines

ORCA and BAGEL are optional, separately licensed, and never bundled. The defaults
below are placeholders — set them to your own install locations.

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
| `QC_AGENT_N_CORES` | `4` | Cores a **single** ORCA/BAGEL job requests (MPI ranks / OpenMP threads), and the number of idle cores the admission gate waits for before starting one |
| `QC_AGENT_MAX_CONCURRENT_JOBS` | `20` | Worker-pool size, fixed at process start. The hard ceiling the admin console's editable concurrency setting can never exceed |
| `QC_AGENT_MAX_CPU_PERCENT` | `80` | Admission gate: hold new jobs back once the **host's** average CPU is at or above this |
| `QC_AGENT_MAX_MEM_PERCENT` | `80` | Admission gate: hold new jobs back once the host is this full on memory |
| `QC_AGENT_CORE_IDLE_THRESHOLD_PERCENT` | `20` | Admission gate: a job also waits until at least `N_CORES` individual cores are each under this busy percentage |

> **NexusQC does not limit itself to a fixed slice of the machine.** Every
> logical core is available to it; what protects the host is the load-based
> admission gate above, not a core budget. At the defaults, up to
> **20 concurrent jobs × 4 cores = 80 cores** may be in flight, and a job only
> starts when the host genuinely has room for it — so an idle machine gets used
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

---

# Job parameter defaults

Every default below lives in
[`app/chemistry/jobs/registry.py`](../app/chemistry/jobs/registry.py)'s
`OPTIONAL_PARAMS`, which is the single source of truth the agent itself consults.
This table is a transcription of it, not separate policy.

**Any parameter not listed here has no default and is required** — the agent will
ask for it explicitly rather than guess. That is deliberate: guessing a basis set
or an active space produces a plausible-looking wrong answer.

| Job type | Parameter | Default | Notes |
|---|---|---|---|
| `geometry_optimization` | `max_steps` | `200` | Optimiser step cap, applied on all three engines |
| `geometry_optimization` | `n_states`, `weights` | `1`, equal | Only meaningful with `method='casscf'`/`'caspt2'` |
| `geometry_optimization` | `target_state` | ground state | BAGEL only — which state's surface to optimise |
| `geometry_optimization` | `optimization_type` | `minimum` | BAGEL only. `conical_intersection` finds a minimum-energy crossing point instead |
| `geometry_optimization` | `target_state_2` | `target_state + 1` | BAGEL only, conical-intersection mode only |
| `frequency` | `temperature_K` | `298.15` | Thermochemistry temperature |
| `frequency` | `dx` | `1.0e-3` bohr | BAGEL's numerical-Hessian displacement step |
| `frequency` | `n_states`, `weights`, `target_state` | as above | Only with `method='casscf'`/`'caspt2'` |
| `casscf` | `n_states`, `weights` | `1`, equal | State averaging |
| `casscf` | `want_oscillator_strengths` | `False` | Routes to ORCA automatically when set — the only engine here that computes them |
| `caspt2` | `n_states`, `weights` | `1`, equal | State averaging |
| `caspt2` | `ms_caspt2` | `True` | Multi-state CASPT2 |
| `caspt2` | `shift` | `0.2` | Level shift against intruder states |
| `caspt2` | `frozen_core` | `True` | Freeze core orbitals in the correlation treatment |
| `tddft` | `functional` | `b3lyp` | Only used when `method='dft'` |
| `tddft` | `use_tda` | `True` | Tamm–Dancoff approximation |
| `tddft` | `singlet_only` | `True` | |
| `mo_visualization` | `isoval` | `0.04` | Cube isosurface value |
| `mo_visualization` | `cube_grid_points` | `80` | ORCA only |
| `pes_scan` | `interpolation_method` | `idpp` | Two-endpoint mode only |
| `neb_ts` | `n_images` | `6` | Movable images between the two fixed endpoints |
| `recommend_active_space` | `max_active_orbitals` | `12` | Ceiling on the final recommended space |
| `recommend_active_space` | `entropy_method` | `exact_fci` | `dmrg` is the opt-in, more basis-accurate alternative |
| `recommend_active_space` | `dmrg_bond_dim` | `250` | Only used with `entropy_method='dmrg'` |
