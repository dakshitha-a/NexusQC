# QM Calculation Agent

A conversational, WebMO-style assistant for quantum chemistry — talk to it in plain English, it runs the calculation.

Name a molecule, describe a calculation, and the agent resolves the structure, fills in a proper input file for the right quantum chemistry engine, runs it in the background, and reports back with real numbers — energies, frequencies, excitation spectra, orbitals — pulled straight from the engine's own output, not guessed by the LLM.

Everything runs locally: a local LLM via [Ollama](https://ollama.com), and three real quantum chemistry engines — [PySCF](https://pyscf.org), [ORCA](https://www.faccts.de/orca/), [BAGEL](https://nubakery.org) — on your own hardware.

## Contents

- [What it does](#what-it-does)
- [CAS active-space recommendation](#cas-active-space-recommendation)
- [Screenshots](#screenshots)
- [Architecture](#architecture)
  - [The agent graph](#the-agent-graph)
  - [Available tools](#available-tools)
- [Requirements](#requirements)
- [Setup](#setup)
- [Running](#running)
- [Configuration](#configuration)
- [Defaults reference](#defaults-reference)
- [Known limitations](#known-limitations)
- [Project layout](#project-layout)

## What it does

### Supported calculations

Every job type routes automatically to whichever engine actually supports it (the **bold** engine is the default; the agent explains plainly if you ask for something none of the three can do).

| Calculation | Engines | Notes |
|---|---|---|
| Single-point energy | **PySCF**, ORCA | HF or DFT |
| Geometry optimization | **PySCF**, ORCA, BAGEL | HF or DFT on PySCF/ORCA; also CASSCF (all three engines) or CASPT2 (BAGEL only) |
| Vibrational frequencies | **PySCF**, ORCA, BAGEL | HF/DFT on all three (BAGEL is HF-only there, and uses a slower numerical Hessian); also CASSCF (all three) or CASPT2 (BAGEL only) — PySCF's CASSCF Hessian is a from-scratch numerical one (no analytic CASSCF Hessian in PySCF) |
| Conical-intersection optimization | **BAGEL** only | minimum-energy crossing point between two states, CASSCF/CASPT2 only — ORCA's equivalent module (%mecp) and PySCF/geomeTRIC have no equivalent path here |
| CASSCF | **PySCF**, BAGEL, ORCA | ORCA is the only one that computes oscillator strengths |
| CASPT2 | **BAGEL** only | ORCA has no CASPT2 (it has NEVPT2 instead) |
| CAS active-space recommendation | **PySCF** only | autoCAS-style single-orbital-entropy screening — see [below](#cas-active-space-recommendation) |
| TD-DFT / TDA-DFT / CIS / TD-HF | **PySCF**, ORCA | one job type covers all four, picked by method + TDA flag |
| EOM-CCSD | **ORCA**, PySCF | ORCA computes oscillator strengths; PySCF is energies-only |
| Potential energy scan | **PySCF**, ORCA, BAGEL | runs as parallel sub-jobs, one per image; any job type per image |
| NEB transition-state search | **ORCA** only | PySCF has no native NEB implementation |
| Molecular orbital visualization | **PySCF**, ORCA, BAGEL | automatic on any completed single-point/TD-DFT/EOM-CCSD/CASSCF/CASPT2 job — no separate submission needed |
| Custom raw ORCA/BAGEL input | ORCA, BAGEL | for anything with no dedicated job type here; no structured result parsing |

### Talking to it

- **Molecule input by name, SMILES, or pasted XYZ/xmol coordinates.** Ask for "caffeine", paste a SMILES string, or paste a raw coordinate block; the agent resolves it (via PubChem/OPSIN for names, directly for coordinates) and shows a 3D structure with numbered atoms immediately — no calculation needed just to look at a molecule.
- **Asks before it guesses.** Missing a basis set? An active space for CASSCF? The agent asks a specific, focused question instead of silently picking a value that would quietly produce wrong physics.
- **Shows you the input before running anything.** Every job pauses for your explicit approval on the exact input file it built — hand-edit the ORCA/BAGEL text yourself if you want, it gets sanity-checked before running either way.
- **Offers a keyword-matching menu instead of trusting a typo.** Before finalizing a job, the agent mechanically matches your basis set (and, for DFT/TD-DFT, functional) against the real names each engine actually recognizes and presents a short numbered/lettered menu — reply with something like `1b` to pick option 1 for the method/functional and option b for the basis, in one shot.
- **Never blocks the UI.** Jobs run as background subprocesses; chat, job status, and results all update live over a real-time stream. If the model gets stuck (e.g. looping on a malformed tool call), hit Stop to interrupt the turn and get the composer back immediately.

### Beyond the built-in job types

- **NEB transition-state searches, on the ground state or an excited state.** Give the agent a reactant and product structure and it runs ORCA's native NEB-TS path search between them — always asking first whether to pre-optimize the two endpoints, since that has no sensible default. The job's detail view shows a frame-by-frame slider over the converged path (the refined TS structure as its own frame), a reaction-path energy plot, and per-frame molecular orbitals.
- **Raw ORCA/BAGEL input for anything without its own job type** (an IRC path, a relaxed surface scan, etc.) — ask the agent to run it and it composes the complete literal input file itself, submitted through the same approval-card pipeline as any other job. The detail view shows the input geometry and raw output, plus a full-job download.
- **Can also write (but not run) an input for other QM software.** Ask for a Gaussian/NWChem/Psi4/etc. input and the agent composes the text directly in its reply — grounded in a manual you've uploaded, if any — but there's no approval card and no job, since this app has no way to execute anything outside PySCF/ORCA/BAGEL.
- **Potential energy scans run as real parallel jobs, not one slow sequential loop.** Give the agent a start and end geometry and it builds an interpolated path (IDPP by default, or true internal-coordinate LIIC, or plain Cartesian) and spawns one real sub-job per image — any job type, including a curve per electronic state for TD-DFT/CASSCF/CASPT2/EOM-CCSD — run concurrently under the same resource-aware job manager as everything else. Single-molecule bond/angle/dihedral scans use the same machinery.

### Job management

- **A job manager, not just a status line.** Every job shows up in a live table (status, engine, description) with a kill button and a detail drawer for full parameters, results, and artifacts — including a download button, a geometry flyout, and a raw-output flyout with a real find bar (Ctrl+F, match count, next/prev, highlighting).
- **Conversations title themselves — and you can pin or rename them.** A fresh conversation auto-renames from your first message once the agent responds. Pin the ones you'll come back to, rename any with the pencil icon or a double-click.
- **Auto-retries failed jobs.** A failed job triggers an automatic investigate-and-retry cycle (check the error, consult the knowledge base, search the web if needed) — but a retry never runs without your explicit approval on the corrected input, and the retry budget is enforced by code, not by trusting the model to count its own attempts.

### Results, visualized

- **Plots UV/Vis and IR spectra from completed jobs**, and says clearly when a job has no oscillator strengths/IR intensities to plot rather than faking one (IR intensities are ORCA/BAGEL only).
- **Names the orbitals behind each excited state.** Every TD-DFT/CIS/EOM-CCSD/CASSCF/CASPT2 job's excited-state table shows the leading orbital-pair excitation(s) for each state — read directly from the engine's own CI-vector or amplitude output, not inferred by the LLM.
- **Molecular orbitals, click to inspect any of them.** Every completed single-point/TD-DFT/EOM-CCSD/CASSCF/CASPT2 job carries a per-orbital energy/occupancy table automatically; click any row to render it as a real 3D isosurface, with an isovalue slider. Works uniformly across all three engines despite each getting there through a different pipeline, and CASSCF/CASPT2 orbitals show genuine fractional natural-orbital occupations, not integer HF-style ones.
- **Animates vibrational modes**, not just a frequency table — click a mode in a completed frequency job (any engine) and watch the actual displacement.
- **Compares results across jobs with a plot and a table.** Attach two or more completed jobs from the Job Manager panel and ask the agent to plot or compare a result (energy, HOMO-LUMO gap, etc.) — a bar chart appears directly in the chat with a download button, alongside a table of the underlying values.

### Knowledge base & help

- **Grounded in your own references.** Starts pre-seeded with the BAGEL and ORCA manuals plus a PySCF reference (see [Seeding the knowledge base](#seeding-the-knowledge-base-optional-recommended)); add more any time — drag and drop PDF/TXT/MD/DOCX files, paste a URL to scrape, or drop a paper card straight out of chat. The agent automatically consults this store when building job input, to get exact keyword syntax right.
- **Built-in help.** A help button in the sidebar opens a flyout explaining the UI and giving a plain-language primer on every supported job type.

## CAS active-space recommendation

Picking a CASSCF/CASPT2 active space by hand is one of the hardest, most error-prone judgment calls in multireference chemistry — too small and you miss the physics you're trying to capture, too large and the calculation becomes intractable. `recommend_active_space` automates the first half of that judgment call using the same idea behind the [autoCAS](https://doi.org/10.1021/acs.jctc.6b00722) method (Stein & Reiher): screen a wide pool of candidate orbitals by how strongly entangled each one is with the rest of the system, then keep only the ones that are genuinely multi-configurational in character.

Ask for it directly (`recommend an active space for the S1 state of butadiene`) or let the agent offer it — when you ask a general "what active space should I use for X" question, the agent first checks your uploaded papers and the published literature for precedent (see [Knowledge base & help](#knowledge-base--help)) and, if nothing conclusive turns up, offers to run this instead of guessing.

**The pipeline, in one job:**

1. **Restricted Hartree–Fock** on the molecule, at whatever basis set you specify.
2. **AVAS** ([Atomic Valence Active Space](https://doi.org/10.1021/acs.jctc.7b00347)) seeds a chemically sensible "pilot" active space from valence AO character (by default, the valence p/d shells of every non-hydrogen atom — narrow this with `avas_aolabels` if you want to focus on a specific fragment or metal center).
3. **Single-orbital entropies** are computed for every orbital in the pilot space — a low-cost, deliberately *unconverged* pass (this is the "pilot" part of autoCAS: cheap enough to run at a much larger orbital count than the final CASSCF itself could tolerate). Two backends compute this differently (see below).
4. **Threshold sweep**: the entropies are sorted and swept for a stable "plateau" — a point where the orbital count stops changing much as the threshold varies, autoCAS's own signature of a chemically meaningful cutoff — capped at `max_active_orbitals` (default 12).
5. A **final, fully-converged state-averaged CASSCF** is run on exactly the recommended space, for the number of states you asked for.
6. Each active orbital is classified by **character** (σ/π/n/σ*/π*) and **dominant atom(s)**, shown in a clickable per-orbital table alongside a 3D isosurface viewer and the entropy-vs-threshold plateau diagram.

**Two pilot-screening backends** (`entropy_method` parameter):

| Backend | Method | Pilot ceiling | Tradeoff |
|---|---|---|---|
| `exact_fci` (default) | Exact CASCI on the pilot space | 12 orbitals (this host) | Fast, no extra dependency — but AVAS's full candidate pool is often larger than 12, forcing truncation before entropies are even computed |
| `dmrg` | DMRG via [block2](https://github.com/block-hczhai/block2-preview) (low bond dimension, few sweeps — a deliberately cheap, unconverged pilot, per autoCAS's own design) | ~30 orbitals (this host, from real benchmark timings) | A much larger, more basis-faithful candidate pool screened before truncation — at the cost of a slower job and the `block2` dependency |

Either way, the **final** recommended active space and its CASSCF are unaffected — both backends feed the same threshold-sweep/final-CASSCF steps; only the pilot's own candidate-pool size and entropy fidelity change. Offer `dmrg` when the basis set is large enough that `exact_fci`'s 12-orbital pilot ceiling would truncate AVAS's candidate pool hard (common at anything past a minimal basis), or when the user explicitly asks about DMRG.

**Known limitations:** PySCF only (ORCA/BAGEL have no round-trippable in-memory orbital/RDM access this app can use for the entropy/character analysis); a minimal basis set (e.g. STO-3G) systematically under-represents diffuse/Rydberg character, so treat a recommendation from one as a starting point, not a final answer, especially for excited states with charge-transfer or Rydberg character; the final CASSCF step always uses exact orbital optimization regardless of `entropy_method`, capped at 12 orbitals on this host — `max_active_orbitals` can only narrow the recommendation, never widen it past that ceiling.

## Screenshots

<p align="center">
  <img src="docs/screenshot.png" alt="QM Calculation Agent: chat, a pending job approval card with its generated input preview, the molecule viewer, and the cross-conversation Job Manager panel" width="900">
</p>

Chat on the left drives everything — here the agent has resolved formaldehyde, generated a DFT input, and paused for approval before running it. The right-hand instrument panel shows the live 3D structure and every job across every conversation, not just the current one.

<p align="center">
  <img src="docs/screenshot-orbitals.png" alt="Job detail drawer showing the molecular orbital table, isovalue slider, and a rendered 3D orbital isosurface" width="340">
</p>

Click-to-inspect molecular orbitals: any row in the energy/occupancy table renders its orbital on demand (formaldehyde's HOMO, an oxygen lone pair, shown here).

## Architecture

The app is a React single-page app talking to a FastAPI backend, which wraps a LangGraph agent, a background job manager, and a RAG knowledge-base store.

```mermaid
flowchart LR
    subgraph UI["React frontend (Vite)"]
        Chat[Chat]
        MolPanel[Molecule viewer]
        JobPanel[Jobs table + drawer]
        KBPanel[Knowledge base]
    end

    subgraph API["FastAPI server"]
        REST["REST endpoints"]
        SSE["SSE event stream"]
        Watcher["job_watcher\n(auto-retry, background)"]
    end

    subgraph Agent["LangGraph Agent"]
        LLM["Local LLM (Ollama)"]
        Tools["set_molecule / submit_job /\ncheck_job_status / plot_job_comparison /\nsearch_knowledge_base"]
    end

    subgraph Jobs["Background Job Execution"]
        Registry["Method to Engine registry"]
        PySCF["PySCF worker"]
        ORCA["ORCA worker"]
        BAGEL["BAGEL worker"]
    end

    RAG["Chroma vector store\n(manuals + papers)"]

    Chat <--> SSE
    Chat --> REST --> LLM --> Tools
    Tools --> Registry
    Registry --> PySCF
    Registry --> ORCA
    Registry --> BAGEL
    Tools --> RAG
    Watcher -.polls status, injects retry notice.-> Jobs
    Watcher -.push.-> SSE
    PySCF & ORCA & BAGEL -.results.-> JobPanel
    Tools -.molecule.-> MolPanel
    KBPanel --> RAG
```

Jobs are dispatched to isolated subprocesses and polled from disk, so a slow calculation (or an engine crash) never freezes the conversation — and never shares a lock with the agent's own LLM calls, so job status stays live even mid-turn. The agent's own tool set is fixed (see [below](#available-tools) and `app/agent/tools.py`'s `STATIC_TOOLS`) — there is no mechanism for it to write or register new tools at runtime. See [`CLAUDE.md`](CLAUDE.md) for the full architecture writeup: job execution model, LangGraph state design, the SSE/streaming design, and the non-obvious bugs that shaped all of it.

### The agent graph

The "LangGraph Agent" box above is, under the hood, a small, fixed two-node graph — a standard ReAct tool-calling loop, not a multi-agent pipeline or a router between specialized sub-agents. Every turn runs `agent → (tools → agent)*` until the model stops requesting tools:

```mermaid
flowchart TD
    Start(["START"]) --> Agent
    Agent["agent node\nsystem prompt + full message history\n→ local LLM (Ollama), bound to all 11 tools"]
    Agent -->|no tool_calls| Done(["END: turn complete"])
    Agent -->|tool_calls requested| Tools
    Tools["tools node\nLangGraph ToolNode\nruns the requested tool(s) on a worker thread pool"]
    Tools --> Agent
    Tools -.submit_job calls interrupt().-> Paused{{"graph pauses, returns to the caller\nwith the pending approval payload"}}
    Paused -.Command resume, after human approval.-> Tools

    State[("AgentState\nmessages, molecule, pes_scan_end_molecule,\nmolecule_frames, active_job_ids")]
    Agent -.reads and writes.-> State
    Tools -.Command update.-> State
    Checkpoint[("SQLite checkpointer\none row per thread_id")]
    State -.persisted every step.-> Checkpoint
```

- **`agent` node** builds the LLM call fresh each step — system prompt plus the full message history — and binds the complete, fixed tool set. There's no separate planner/router node or specialized sub-agent; this one node handles every turn regardless of what the user asked for.
- **`tools` node** is LangGraph's stock `ToolNode`, which can run several tool calls the model batched into one step in parallel, each on its own worker thread. That's why `AgentState`'s side-channel fields (`molecule`, `active_job_ids`, ...) need custom reducers instead of a plain overwrite: two tool calls batched together (e.g. `set_molecule` + `submit_job`) both read the same pre-batch state, so their writes have to accumulate rather than race.
- **The only pause in the graph is inside `submit_job`.** It builds the job spec, then calls a real LangGraph `interrupt()` before anything actually runs — the graph genuinely stops and hands control back to the FastAPI server with the pending payload, which is what renders the job-approval card. Resuming re-enters the `tools` node with the human's decision (approve, edit, or reject); every other tool returns straight through and never pauses.
- **A `SqliteSaver` checkpointer** persists the full state after every step, keyed by `thread_id` — this is what lets a page reload mid-conversation (or mid-approval) resume exactly where it left off, and what lets `job_watcher.py`'s background thread inject a retry notice into a conversation with no browser tab open at all.
- **One process-wide lock** (`_graph_lock` in `graph.py`) serializes every access to the compiled graph, since a chat turn, a job-approval resume, and the background auto-retry watcher can all reach it from different threads concurrently — it is never held across a call into a tool itself, since `ToolNode` runs tools on its own thread pool, not the calling thread.

See [`app/agent/graph.py`](app/agent/graph.py) and [`app/agent/state.py`](app/agent/state.py) for the real code, and [`CLAUDE.md`](CLAUDE.md) for the deeper "why" — the `NotRequired`/reducer story, the interrupt-and-re-execution sharp edge, and why dynamic tool creation was tried and then deliberately removed.

### Available tools

The agent's tool set is fixed and closed — see the note above on why there's no runtime tool-creation mechanism. All eleven live in `app/agent/tools.py`'s `STATIC_TOOLS` (three of them — knowledge-base, literature, and web search — are implemented in their own modules and imported in):

| Tool | What it does | Notes |
|---|---|---|
| `set_molecule` | Resolves a molecule by name, SMILES, or pasted XYZ/xmol coordinates and makes it the active structure for the conversation | Writes `molecule` (plus a frame-history entry) via `Command(update=...)` — no approval needed |
| `set_pes_scan_endpoint` | Resolves the second ("end") geometry for a two-molecule PES scan | Mirrors `set_molecule` into its own state slot so both endpoints coexist at once |
| `generate_job_input` | Builds and returns an engine input file/script without running it | Read-only preview — no job is created, no approval pause |
| `submit_job` | Runs a calculation in the background — `single_point`, `geometry_optimization`, `frequency`, `casscf`, `caspt2`, `tddft`, `eom_ccsd`, `mo_visualization`, `pes_scan`, `neb_ts`, `custom`, or `recommend_active_space` | The only tool that pauses the graph (`interrupt()`) for human approval of the exact generated input before anything runs |
| `check_job_status` | Reports a job's status, or its full results once complete | Read-only; defaults to the most recently submitted job in the conversation |
| `plot_excited_state_spectrum` | Renders a Gaussian-broadened UV/Vis spectrum from a completed job's excitation energies and oscillator strengths | Refuses rather than fabricating a plot if the job has no usable oscillator strengths |
| `plot_ir_spectrum` | Renders a Gaussian-broadened IR spectrum from a completed frequency job | ORCA/BAGEL only — PySCF computes no IR intensities in this app |
| `plot_job_comparison` | Bar-charts one scalar field (energy, HOMO-LUMO gap, ZPE, enthalpy, Gibbs free energy, TS energy) across two or more attached jobs | Fixed field set, not free-form; refuses below two usable jobs rather than guessing |
| `search_knowledge_base` | Searches the Chroma-backed RAG store of uploaded/seeded manuals and papers | Filterable by `doc_type` (`manual`/`paper`); also run automatically, not left purely to LLM discretion, before every job submission for keyword grounding |
| `search_academic_literature` | Searches published papers via the Semantic Scholar Graph API | Literal boolean query syntax, not semantic search — quote distinctive multi-word terms for a useful result set |
| `web_search` | Searches the public web via DuckDuckGo | The only tool that calls out to the public internet; a last resort, after the knowledge base |

## Requirements

| Requirement | Notes |
|---|---|
| [Conda](https://docs.conda.io) env, Python 3.11 | Packages from [`requirements.txt`](requirements.txt), including `fastapi`, `uvicorn`, `psutil` |
| Node.js 18+ and npm | For the frontend — system Node is often too old for Vite; a dedicated conda env works well: `conda create -n node20 -c conda-forge nodejs=20` |
| [Ollama](https://ollama.com), running locally | A tool-calling-capable model (default `qwen3:30b`) and an embedding model (default `nomic-embed-text`) |
| [PySCF](https://pyscf.org) | Installed via `requirements.txt`; the default engine, always available |
| [ORCA](https://www.faccts.de/orca/) *(optional)* | For methods routed to it — see the [calculation table](#supported-calculations) |
| [BAGEL](https://nubakery.org) *(optional)* | Required for CASPT2; also used for some CASSCF/frequency/scan paths |

## Setup

```bash
conda create -n qc-agent python=3.11
conda activate qc-agent
pip install -r requirements.txt

ollama pull qwen3:30b
ollama pull nomic-embed-text
```

```bash
conda create -n node20 -c conda-forge nodejs=20
conda activate node20
cd frontend && npm install
```

### Seeding the knowledge base (optional, recommended)

The agent's RAG knowledge base starts empty; you can seed it with the BAGEL and ORCA manuals plus a PySCF reference generated from your installed package, so it has baseline domain knowledge before you upload anything yourself:

```bash
conda activate qc-agent
PYTHONPATH=$PWD python3 scripts/seed_knowledge_base.py
```

This crawls the [BAGEL](https://nubakery.org/user-manual.html) and [ORCA](https://orca-manual.mpi-muelheim.mpg.de/) manuals (both permit it — neither publishes a `robots.txt` restriction) and generates PySCF reference docs from the docstrings of your actually-installed `pyscf` package rather than scraping pyscf.org, whose `robots.txt` explicitly disallows AI crawlers including `ClaudeBot`. Takes a few minutes; safe to re-run. Run a single stage with e.g. `python3 scripts/seed_knowledge_base.py orca`.

## Running

Two processes: the FastAPI backend and the Vite dev server for the frontend.

```bash
# Terminal 1 -- backend (binds to localhost only; this is a single-user, local-only app)
conda activate qc-agent
PYTHONPATH=$PWD python3 -m server.main

# Terminal 2 -- frontend
conda activate node20
cd frontend && npm run dev
```

Open the URL Vite prints (default `http://localhost:5173`). The dev server proxies `/api/*` to the backend on port 8000, so no CORS setup is needed for local use. Try:

| Say this | To see |
|---|---|
| `water` | Structure resolution and the 3D viewer |
| `run a single point HF/STO-3G calculation on water` | A background job — approve it on the card that appears inline in the chat |
| `run a CASSCF calculation on formaldehyde` | The agent asking for the basis set and active space instead of guessing |
| a job with a deliberately bad parameter (e.g. an invalid basis string) | The agent auto-investigating and proposing a corrected retry, still gated on your approval |
| `plot the energies of these jobs`, after attaching two or more completed jobs | An inline bar-chart comparison plus a markdown table |

## Configuration

Every setting lives in [`app/config.py`](app/config.py) and is overridable via environment variables:

| Variable | Default | Purpose |
|---|---|---|
| `QC_AGENT_LLM_MODEL` | `qwen3:30b` | Ollama model for the agent |
| `QC_AGENT_LLM_BASE_URL` | `http://localhost:11434/v1` | Ollama's OpenAI-compatible endpoint |
| `QC_AGENT_EMBEDDING_MODEL` | `nomic-embed-text` | Embedding model for the RAG store |
| `QC_AGENT_OLLAMA_EMBEDDING_TIMEOUT` | `30` (seconds) | Timeout on embedding calls — bounds how long a stalled Ollama request can hold the agent's internal lock |
| `QC_AGENT_ORCA_BIN` | `/opt/Orca-6.1.1/orca` | Path to the ORCA executable |
| `QC_AGENT_BAGEL_BIN` | `/opt/bagel-1.2.2/bin/BAGEL` | Path to the BAGEL executable |
| `QC_AGENT_N_CORES` | auto-detected via `nproc` | Cores a single job requests (MPI ranks / OpenMP threads) |
| `QC_AGENT_MAX_CONCURRENT_JOBS` | `4` | Background job count cap |
| `QC_AGENT_CASSCF_CONV_TOL_ENERGY` | `1e-6` | CASSCF/CASPT2 energy convergence for energy-only jobs (the `casscf`/`caspt2` job types, and `recommend_active_space`'s final CASSCF) |
| `QC_AGENT_CASSCF_CONV_TOL_OPT_FREQ` | `1e-7` | CASSCF/CASPT2 energy convergence for geometry optimization/frequency jobs — tighter than the energy-only tolerance, since a loose wavefunction convergence shows up as noise in a gradient/Hessian |
| `QC_AGENT_CASSCF_MAX_CYCLE_MACRO` | `200` | Max CASSCF macro-iterations, applied identically everywhere CASSCF/CASPT2 appears (all three engines, every job type) |
| `QC_AGENT_MAX_CPU_PERCENT` | `80` | Soft admission gate: hold new jobs back once the *host's* average CPU (across all its cores) is at or above this |
| `QC_AGENT_MAX_MEM_PERCENT` | `80` | Soft admission gate: hold new jobs back once the host is this full on memory |
| `QC_AGENT_CORE_IDLE_THRESHOLD_PERCENT` | `20` | Soft admission gate: a job also waits until at least `N_CORES` individual host cores are each under this busy % |
| `QC_AGENT_WEB_SEARCH_TIMEOUT` | `10` (seconds) | Per-engine timeout for the `web_search` tool's DuckDuckGo calls |
| `QC_AGENT_SEMANTIC_SCHOLAR_API_KEY` | *(none)* | Optional free API key for more reliable `search_academic_literature` results |
| `QC_AGENT_SERVER_CORS_ORIGINS` | `http://localhost:5173,http://127.0.0.1:5173` | Allowed browser origins for the FastAPI server |

## Defaults reference

Every job-type parameter default below lives in [`app/chemistry/jobs/registry.py`](app/chemistry/jobs/registry.py)'s `OPTIONAL_PARAMS`, the single source of truth the agent itself consults — this table is a faithful transcription, not separate policy. Any parameter not listed here has no default and is *required*: the agent will ask for it explicitly rather than guess.

| Job type | Parameter | Default | Notes |
|---|---|---|---|
| `geometry_optimization` | `max_steps` | `200` | Outer optimizer step cap — applied on all three engines (ORCA previously had no explicit cap here at all, silently using its own internal default) |
| `geometry_optimization` | `n_states`, `weights` | `1`, equal weights | Only meaningful with `method='casscf'`/`'caspt2'` |
| `geometry_optimization` | `target_state` | ground state | BAGEL only — which state's PES to optimize |
| `geometry_optimization` | `optimization_type` | `minimum` | BAGEL only — `conical_intersection` finds a minimum-energy crossing point instead |
| `geometry_optimization` | `target_state_2` | `target_state + 1` | BAGEL only, `conical_intersection` mode only |
| `frequency` | `temperature_K` | `298.15` | Thermochemistry temperature |
| `frequency` | `dx` | `1.0e-3` bohr | BAGEL's numerical-Hessian displacement step |
| `frequency` | `n_states`, `weights`, `target_state` | same as above | Only meaningful with `method='casscf'`/`'caspt2'` |
| `casscf` | `n_states`, `weights` | `1`, equal weights | State-averaging |
| `casscf` | `want_oscillator_strengths` | `False` | Routes to ORCA automatically when set (the only engine that computes these here) |
| `caspt2` | `n_states`, `weights` | `1`, equal weights | State-averaging |
| `caspt2` | `ms_caspt2` | `True` | Multi-state CASPT2 |
| `caspt2` | `shift` | `0.2` | Imaginary/real level shift against intruder states |
| `caspt2` | `frozen_core` | `True` | Freeze core orbitals in the correlation treatment |
| `tddft` | `functional` | `b3lyp` | Only used when `method='dft'` |
| `tddft` | `use_tda` | `True` | Tamm-Dancoff approximation |
| `tddft` | `singlet_only` | `True` | |
| `mo_visualization` | `isoval` | `0.04` | Cube isosurface value |
| `mo_visualization` | `cube_grid_points` | `80` | ORCA only |
| `pes_scan` | `interpolation_method` | `idpp` | Two-endpoint mode only |
| `neb_ts` | `n_images` | `6` | Movable images between the two fixed endpoints |
| `recommend_active_space` | `max_active_orbitals` | `12` | Ceiling on the *final* recommended active space (independent of the pilot's own ceiling — see [CAS active-space recommendation](#cas-active-space-recommendation)) |
| `recommend_active_space` | `entropy_method` | `exact_fci` | `dmrg` is the opt-in, more basis-accurate alternative |
| `recommend_active_space` | `dmrg_bond_dim` | `250` | Only used when `entropy_method='dmrg'` |

CASSCF/CASPT2 convergence (energy tolerance, gradient/Hessian-job tolerance, max macro-iterations) is explicit policy applied identically across all three engines rather than a per-job-type default — see the `QC_AGENT_CASSCF_*` rows in [Configuration](#configuration) above.

## Known limitations

- A PES scan's per-image sub-jobs all share one set of calculation parameters — hand-editing an ORCA/BAGEL approval-card input text only ever applies to the first image's own file, not the rest of the scan (parameter edits, as opposed to raw text edits, do propagate to every image).
- Storage is capped and self-evicting, oldest first: job artifacts at 100GB total (`app/chemistry/jobs/quota.py`, evicting only completed/failed/cancelled job directories) and knowledge-base storage at 10GB total (`app/rag/quota.py`, evicting only sources added through the live uploader/paste/URL flow, never the pre-seeded manuals). Both are enforced at write time, not on a schedule, so monitor disk usage anyway on a long-running deployment. Current usage against each cap is shown live in the UI next to the "Job manager (all jobs)" and "Knowledge base" panel headers.
- The molecule viewer is read-only (renders the structure with numbered atom labels) — no click-to-select bond/angle/dihedral measurement, which was dropped after surfacing more trouble than it was worth (see `CLAUDE.md`).
- IR spectrum plotting/intensities are ORCA and BAGEL only — PySCF's frequency job type computes frequencies and normal modes but no dipole-derivative/IR-intensity output in this app.
- `plot_job_comparison` only supports a fixed set of scalar comparison fields (energy, HOMO-LUMO gap, zero-point energy, enthalpy, Gibbs free energy, TS energy) — it can't plot a list-valued result (e.g. a full excitation spectrum) across jobs, and there's no way to compare an arbitrary user-described quantity; the agent's tool set is fixed, with no runtime code-writing mechanism.
- Molecular-orbital cube rendering follows a different pipeline per engine (see `CLAUDE.md`'s architecture notes): PySCF renders directly from its own MO coefficients, BAGEL via a real molden export verified by point-sampling to match PySCF's own basis evaluation exactly, and ORCA via its own `orca_plot` utility rather than a molden export, after the latter was found to apply a shell-dependent AO normalization mismatch that distorts orbital shapes.
- No automated test suite; changes are verified by driving the running app with Playwright (see `CLAUDE.md`) and by direct runner-function invocation for the Python backend.
- No constrained geometry optimization (freezing/scanning a specific bond/angle/dihedral mid-optimization) yet — feasible later via PySCF geomeTRIC's own `constraints` kwarg and ORCA's `%geom Constraints` block, but not built here; BAGEL's optimizer has no equivalent keyword.
- BAGEL geometry optimization is CASSCF/CASPT2 only in this app (plain HF/DFT geometry optimization on BAGEL isn't implemented) — use PySCF or ORCA for HF/DFT geometry optimization instead.
- BAGEL's new CASSCF/CASPT2 geometry-optimization/frequency support is structurally verified (real BAGEL runs confirmed it correctly parses and begins executing the new input shape) but not yet convergence-verified end-to-end — this host's BAGEL/MKL install showed real instability during testing (abnormally slow CASSCF iterations, one environmental LAPACK crash unrelated to this feature's own code) that prevented a full live run from completing; PySCF and ORCA's equivalents are fully live-verified.
- PySCF has no analytic CASSCF Hessian at all, so its CASSCF/CASPT2-adjacent frequency path (CASSCF only — CASPT2 frequency is BAGEL-only) uses a hand-rolled numerical Hessian (central differences of the analytic CASSCF gradient), noticeably slower than an analytic one and slower than ORCA's/BAGEL's own native numerical Hessians.

## Project layout

```
app/
  agent/       LangGraph agent: state, tools, prompts, graph,
               threads.py (conversation registry), job_watcher.py (background auto-retry), serialize.py
  chemistry/
    jobs/      Job manager + PySCF/ORCA/BAGEL runners and worker subprocesses
    molecule.py, zmatrix.py, spectrum.py
  rag/         Chroma-backed knowledge base: store, ingestion, query tool
  config.py    All configuration, env-var overridable
server/        FastAPI backend for the React frontend: REST routes, SSE event hub, schemas
frontend/      Vite + React + TypeScript SPA -- chat, jobs table, molecule viewer, KB panel
scripts/
  seed_knowledge_base.py   Crawl BAGEL/ORCA manuals + generate PySCF reference docs, ingest into RAG
data/          Runtime data (jobs, molecules, kb, uploads, scraped, threads.json) -- gitignored
```
