<div align="center">

# NexusQC

### Agentic Quantum Chemistry Engine

**Describe a calculation in plain English. Get real numbers from a real quantum chemistry program.**

[![License: MIT](https://img.shields.io/badge/License-MIT-6e8cff.svg)](LICENSE)
[![Python 3.11](https://img.shields.io/badge/Python-3.11-3776AB.svg?logo=python&logoColor=white)](https://www.python.org)
[![Node 24](https://img.shields.io/badge/Node-24-339933.svg?logo=nodedotjs&logoColor=white)](https://nodejs.org)
[![Engines: PySCF · ORCA · BAGEL](https://img.shields.io/badge/Engines-PySCF%20%C2%B7%20ORCA%20%C2%B7%20BAGEL-34c7a0.svg)](#supported-calculations)
[![Runs locally](https://img.shields.io/badge/LLM-runs%20locally-e8a33d.svg)](#requirements)

<img src="docs/screenshot.png" alt="NexusQC: a chat conversation, a pending job approval card showing the generated input file, the 3D molecule viewer, and the job manager" width="900">

</div>

---

NexusQC turns a conversation into a quantum chemistry calculation. Name a
molecule, say what you want to know, and it resolves the structure, builds a
proper input file for whichever engine actually supports the method, runs it in
the background, and reports **real numbers parsed from the program's own
output** — never numbers invented by a language model.

Everything runs on your own hardware: a local LLM through
[Ollama](https://ollama.com), and up to three real engines —
[PySCF](https://pyscf.org), [ORCA](https://www.faccts.de/orca/) and
[BAGEL](https://nubakery.org).

**Three things make it different from a chatbot with a calculator bolted on:**

🔒 **Nothing runs without your approval.** Every job pauses on a real graph
interrupt and shows you the exact input file first. This is structural, not a
prompt instruction — it holds even if the model never thinks to ask.

🤔 **It asks instead of guessing.** Missing a basis set or an active space? You
get a specific question, not a silently-chosen default that quietly produces
wrong physics.

🔁 **It debugs its own failures.** A failed job triggers an automatic
investigate-and-retry cycle — read the error, consult the manual, search the web
— and the corrected retry still needs your approval. The retry budget is enforced
in code, not by trusting the model to count.

---

## Quickstart

Already have conda, Node 24 and Ollama? This is the whole thing:

```bash
git clone https://github.com/dakshitha-a/NexusQC.git && cd NexusQC

conda create -n qc-agent python=3.11 -y && conda activate qc-agent
pip install -r requirements.txt
ollama pull qwen3.8:27b && ollama pull nomic-embed-text

# Terminal 1
PYTHONPATH=$PWD python3 -m server.main

# Terminal 2
conda activate node24 && cd frontend && npm install && npm run dev
```

Open `http://localhost:5173` and type `water`.

Starting from nothing? Follow [Installation](#installation) — it assumes no
prior setup.

---

## What it does

### Supported calculations

Each job routes automatically to whichever engine supports it. **Bold** is the
default. PySCF is bundled and always available; ORCA and BAGEL are optional.

| Calculation | Engines | Notes |
|---|---|---|
| Single-point energy | **PySCF**, ORCA | HF or DFT |
| Geometry optimisation | **PySCF**, ORCA, BAGEL | HF/DFT on PySCF and ORCA; CASSCF on all three; CASPT2 on BAGEL |
| Vibrational frequencies | **PySCF**, ORCA, BAGEL | Thermochemistry and animated normal modes |
| Optimisation + frequencies | **PySCF**, ORCA, BAGEL | One job: optimises, then runs frequencies at the result |
| Nuclear-ensemble (Wigner) spectrum | **PySCF**, ORCA, BAGEL | Samples geometries from a frequency job and pools every sample's excitations into one broadened absorption spectrum |
| CASSCF | **PySCF**, BAGEL, ORCA | Only ORCA computes oscillator strengths |
| CASPT2 | **BAGEL** | ORCA has NEVPT2 instead, not CASPT2 |
| Active-space recommendation | **PySCF** | autoCAS-style entropy screening — [see below](#picking-a-cas-active-space) |
| TDDFT / TDA-DFT / CIS / TD-HF | **PySCF**, ORCA | One job type covers all four |
| EOM-CCSD | **ORCA**, PySCF | PySCF is energies-only |
| Conical-intersection optimisation | **BAGEL** | Minimum-energy crossing point between two states |
| Potential-energy scan | **PySCF**, ORCA, BAGEL | Real parallel sub-jobs, one per image |
| NEB transition-state search | **ORCA** | Frame-by-frame path with per-frame orbitals |
| Orbital visualisation | **PySCF**, ORCA, BAGEL | Automatic on any completed job — no separate submission |
| Custom raw input | ORCA, BAGEL | For anything without a dedicated job type |

Ask for something none of them can do — a Gaussian or Psi4 calculation — and it
will write you the input file in chat and say plainly that it cannot run it.

### Working with it

- **Molecules by name, SMILES, pasted XYZ, or sketch.** Resolved via PubChem and
  OPSIN, shown immediately in 3D with numbered atoms. No calculation needed just
  to look at something.
- **Typos get a menu, not a guess.** Basis sets and functionals are matched
  mechanically against the names each engine really recognises, and you pick from
  a short list. If none of them is what you meant, the menu's last entry searches
  [Basis Set Exchange](https://www.basissetexchange.org/) for the exact published
  basis set — bundled offline, not a network call — and confirms it covers every
  element in your molecule before offering it. It then works on any engine, with
  the per-engine translation handled for you.
- **Nothing blocks the UI.** Jobs are background subprocesses; chat, status and
  results stream live. A CASSCF job can run for hours — close the tab, come back,
  it will be there.
- **Uses the whole machine, politely.** Every core is available: by default each
  ORCA/BAGEL job takes 4, up to 20 run at once, and new jobs are admitted only
  when the host genuinely has headroom — so an idle machine gets used and a busy
  one is left alone. All tunable at setup; see
  [CONFIGURATION.md](docs/CONFIGURATION.md#job-execution-and-resource-limits).
- **Hand-edit before running.** ORCA and BAGEL input can be edited on the
  approval card and is sanity-checked before it runs.

### Results you can actually inspect

- **Orbitals on every completed job**, with a per-orbital energy and occupancy
  table — click any row for a 3D isosurface with an isovalue slider. CASSCF shows
  genuine fractional natural-orbital occupations, not integer HF-style ones.
- **UV/Vis and IR spectra**, with the leading orbital-pair character named for
  each excited state, read from the engine's own CI vectors — not inferred.
- **Animated vibrational modes**, on all three engines.
- **Nuclear-ensemble absorption spectra**, pooled across every sampled geometry
  of a Wigner ensemble, with a per-excited-state breakdown under the total curve
  and the raw broadened data downloadable as `.dat`. Re-plot at a different
  broadening width, or ask which sampled geometries absorb near a given energy,
  without recomputing anything.
- **Cross-job comparison charts**, rendered inline in the conversation.

When a job genuinely has no oscillator strengths or IR intensities to plot, it
says so rather than drawing a flat line.

<div align="center">
<img src="docs/screenshot-results.png" alt="A completed job: the agent's summary of the total energy, HOMO-LUMO gap and dipole moment, beside the job detail drawer showing parsed results and the per-orbital energy, occupancy and character table" width="900">
<br>
<sub><i>A finished HF/STO-3G run on water. Every number is parsed from PySCF's own output — the orbital characters and localisations included.</i></sub>
</div>

### Picking a CAS active space

Choosing a CASSCF active space by hand is one of the most error-prone judgement
calls in multireference chemistry — too small and you miss the physics, too large
and it becomes intractable.

`recommend_active_space` automates the first half using the idea behind
[autoCAS](https://doi.org/10.1021/acs.jctc.6b00722): seed a candidate space from
valence orbital character with
[AVAS](https://doi.org/10.1021/acs.jctc.7b00347), compute single-orbital
entropies over a deliberately cheap unconverged pilot, sweep for the stable
"plateau" that marks a chemically meaningful cutoff, then run a fully converged
state-averaged CASSCF on exactly that space. Each orbital comes back classified
by character (σ/π/n/σ*/π*) and dominant atoms, with an isosurface viewer and the
entropy plateau diagram.

Two pilot backends: exact CASCI (fast, no extra dependency) or DMRG via
[block2](https://github.com/block-hczhai/block2-preview), which screens a much
larger candidate pool before truncation. Both feed the same final CASSCF.

> A minimal basis systematically under-represents diffuse and Rydberg character,
> so treat a recommendation from STO-3G as a starting point — especially for
> excited states with charge-transfer character.

---

## How it works

```mermaid
flowchart TB
    U([You]) -->|"plain language"| A

    subgraph API["FastAPI backend"]
        A["LangGraph agent<br/><i>local LLM via Ollama</i>"]
        A <-->|"exact syntax"| KB[("Knowledge base<br/>manuals · papers")]
        A -->|"builds JobSpec"| G{{"interrupt()<br/><b>approval gate</b>"}}
    end

    G -->|"shows input file"| U
    U -->|"approve"| JM["JobManager"]

    JM -->|"detached subprocess"| W["Worker"]
    W --> E1["PySCF"] & E2["ORCA"] & E3["BAGEL"]
    E1 & E2 & E3 -->|"parsed output"| R[("Results<br/>energies · orbitals · spectra")]
    R -->|"streamed over SSE"| U

    classDef gate fill:#e8a33d22,stroke:#e8a33d,stroke-width:2px
    classDef engine fill:#34c7a022,stroke:#34c7a0
    class G gate
    class E1,E2,E3 engine
```

Three properties are load-bearing:

1. **The approval gate is a real graph interrupt**, so the safety property holds
   structurally rather than depending on the model's cooperation.
2. **Jobs are fully detached subprocesses**, so a calculation outlives the
   request, the session, and even a backend restart. Orphaned jobs are
   reconciled at startup.
3. **Engine output is parsed, never generated.** Every regex was derived from
   real runs, because exact formatting is not guaranteed across versions.

[**docs/ARCHITECTURE.md**](docs/ARCHITECTURE.md) explains the design decisions
and, more usefully, the alternatives that were tried and rejected.

---

## Installation

Written for someone starting from a bare Linux machine. If a step is already
done, skip it.

### Requirements

| Component | Version | Required? |
|---|---|---|
| Python (via conda) | 3.11 | Yes |
| Node.js | ≥ 24.14.1 | Yes — Ketcher declares this |
| Ollama | ≥ 0.32.13 | Yes |
| PySCF | via `requirements.txt` | Yes — bundled |
| ORCA | 6.x | Optional |
| BAGEL | 1.2.x | Optional |

### 1. Install conda

Skip if `conda --version` already works.

```bash
wget https://repo.anaconda.com/miniconda/Miniconda3-latest-Linux-x86_64.sh
bash Miniconda3-latest-Linux-x86_64.sh     # accept the licence, allow it to run conda init
exec $SHELL                                 # reload your shell
conda --version                             # confirm
```

### 2. Install Ollama and pull the models

```bash
curl -fsSL https://ollama.com/install.sh | sh
ollama --version    # must be 0.32.13 or newer
```

> An older Ollama refuses the default model outright with
> `412: requires a newer version of Ollama` rather than serving it incorrectly.
> If you are on a shared machine, note that the installer restarts the Ollama
> service — check with whoever else uses it first.

```bash
ollama pull qwen3.8:27b       # ~17 GB download; needs roughly 20 GB of RAM or VRAM
ollama pull nomic-embed-text  # small
```

On a machine with less memory, substitute a smaller tool-calling model and set
`QC_AGENT_LLM_MODEL` accordingly. Tool calling is a hard requirement — a model
without it cannot drive this app at all.

### 3. Get the code and install Python dependencies

```bash
git clone https://github.com/dakshitha-a/NexusQC.git
cd NexusQC

conda create -n qc-agent python=3.11 -y
conda activate qc-agent
pip install -r requirements.txt
```

### 4. Install Node 24

System Node is usually too old. A dedicated conda environment is the simplest fix:

```bash
conda create -n node24 -c conda-forge nodejs=24 -y
conda activate node24
node --version    # must be >= 24.14.1

cd frontend && npm install && cd ..
```

### 5. Point at ORCA / BAGEL (optional)

Skip unless you have them installed. Neither ships with NexusQC — both are
separately licensed.

```bash
cp .env.example .env
```

Uncomment and edit these lines in `.env` to match your installs:

```bash
QC_AGENT_ORCA_BIN=/opt/orca/orca
QC_AGENT_BAGEL_BIN=/opt/bagel/bin/BAGEL
```

Find them with `which orca` or `ls` wherever your site installs software.

### 6. Seed the knowledge base (optional, recommended)

Gives the agent the ORCA and BAGEL manuals plus a PySCF reference, so it gets
keyword syntax right from the start.

```bash
conda activate qc-agent
PYTHONPATH=$PWD python3 scripts/seed_knowledge_base.py
```

Takes a few minutes and is safe to re-run. It crawls the ORCA and BAGEL manuals
(both permit it) and generates PySCF docs from your **installed** package rather
than scraping pyscf.org, whose `robots.txt` disallows AI crawlers.

### 7. Run it

Two terminals:

```bash
# Terminal 1 — backend
conda activate qc-agent
PYTHONPATH=$PWD python3 -m server.main
```

```bash
# Terminal 2 — frontend
conda activate node24
cd frontend && npm run dev
```

**You should see** `Uvicorn running on http://127.0.0.1:8000` in the first
terminal, and a `Local: http://localhost:5173/` URL in the second. Confirm the
backend independently:

```bash
curl http://127.0.0.1:8000/api/health
```

Open the Vite URL. The dev server proxies `/api/*` to port 8000, so no CORS
setup is needed.

### 8. Try it

| Say this | To see |
|---|---|
| `water` | Structure resolution and the 3D viewer |
| `run a single point HF/STO-3G calculation on water` | A background job — approve it on the card in the chat |
| `run a CASSCF calculation on formaldehyde` | It asking for the basis and active space instead of guessing |
| `what active space should I use for butadiene?` | Literature search, then an offer to compute one |

### Troubleshooting

| Symptom | Cause |
|---|---|
| `412: requires a newer version of Ollama` | Ollama below 0.32.13 — upgrade before pulling |
| Frontend fails to build | Node below 24.14.1. Check `node --version` **inside** the activated env |
| Jobs sit at `pending` forever | The gate is waiting for `QC_AGENT_N_CORES` idle cores. If you raised it near your total core count, lower it |
| A job fails with `KeyError` on a basis name | An unrecognised basis string. The agent usually self-corrects on retry |
| `PermissionError` writing to `data/` | Left over from a previous root-owned run — see [DEPLOYMENT.md](docs/DEPLOYMENT.md) |

---

## Multi-user deployment

For a lab running this as a shared service: Docker Compose with Postgres, Redis
and nginx, real accounts, per-user data isolation, an admin console with storage
quotas, and an append-only audit log.

Everything routine happens in the admin console rather than through raw API
calls: minting an invite link and copying it, revoking one that was sent to the
wrong person or leaked, suspending or restoring an account, deleting one along
with all of its data, reading per-user storage usage, and triaging bug reports
filed from the app. Revocation is soft, so a revoked invite stays listed as
revoked instead of vanishing, and the last active admin cannot be deleted or
suspended — there is no password-reset flow, so locking yourself out is
recoverable only by destroying every account. Every user, admin or not, can
change their own password from the account panel; doing so signs out that
account's other sessions but not the one making the change.

```bash
cp .env.example .env          # set the Postgres password and JWT secret
docker compose build
docker compose up -d
docker compose run --rm api python -m server.admin_cli bootstrap-admin \
  --email you@yourlab.edu --username admin
```

Setting `QC_AGENT_DATABASE_URL` is the single switch that activates the whole
auth layer. **HTTPS is mandatory** — the session cookie is `Secure`, so login
silently fails over plain HTTP.

👉 **[Full deployment guide](docs/DEPLOYMENT.md)** — certificates, quotas, admin
operations, lockout recovery, and an honest account of what is and is not
verified.

---

## Documentation

| Document | What it covers |
|---|---|
| [ARCHITECTURE.md](docs/ARCHITECTURE.md) | How it works and why, including rejected alternatives |
| [DEPLOYMENT.md](docs/DEPLOYMENT.md) | Multi-user Docker deployment, start to finish |
| [CONFIGURATION.md](docs/CONFIGURATION.md) | Every environment variable and job-parameter default |
| [TESTING.md](docs/TESTING.md) | What was tested, results, and what was **not** tested |
| [ROADMAP.md](docs/ROADMAP.md) | Designed but not built — viewer/document downloads, and one known prompt-reliability gap |
| [DEVELOPMENT.md](docs/DEVELOPMENT.md) | Contributing: the two-remote workflow, the public-safety scan, and how releases are cut |
| [CHANGELOG.md](CHANGELOG.md) | What changed in each release |
| [NOTICE.md](NOTICE.md) | Third-party licences and attribution |

---

## Limitations

Worth knowing before you rely on it:

- **CASPT2 is BAGEL-only**; oscillator strengths for CASSCF and EOM-CCSD are
  ORCA-only. There is no workaround for either.
- **NEB transition-state search is ORCA-only.** Its excited-state path is less
  verified than the ground-state one.
- **BAGEL's CASSCF geometry optimisation and frequencies are structurally
  confirmed, not convergence-verified** end to end.
- **No general pre-flight validator** for basis sets and keywords. An invalid
  basis is caught when the engine fails — though auto-retry often fixes it.
- **The public nginx listener has not been verified end to end.**
- **Web search is the only component that calls the public internet**, and it
  sends query text to a third party. Everything else — the LLM, embeddings,
  engines, knowledge base — is local.

Fuller list in [ARCHITECTURE.md](docs/ARCHITECTURE.md#known-limitations) and
[TESTING.md](docs/TESTING.md#what-was-not-tested).

---

## Citation

If NexusQC contributes to published work, please cite it — and **also cite the
quantum chemistry program that performed the calculation**. NexusQC orchestrates
PySCF, ORCA and BAGEL; it does not implement the underlying methods.

Citation metadata is in [`CITATION.cff`](CITATION.cff); GitHub renders a
ready-made citation from it via *Cite this repository*.

## Authors

> **Affiliation at the time of project creation:** Matsika Group, Temple University
> **Author:** Dakshitha Abeygunewardane, dma@temple.edu
> **PI:** Spiridoula Matsika, smatsika@temple.edu
> **Coded with Claude Code (Model: Opus)**

## License

[MIT](LICENSE).

NexusQC bundles or depends on third-party components under their own licences,
including Ketcher (Apache-2.0), 3Dmol.js (BSD-3-Clause), IBM Plex (OFL-1.1), ASE
(LGPL-2.1+) and psycopg (LGPL-3.0). **ORCA and BAGEL are never redistributed** —
ORCA's licence forbids it, and both are bind-mounted from your own installation.
See [NOTICE.md](NOTICE.md).

## Acknowledgements

Built on [PySCF](https://pyscf.org), [ORCA](https://www.faccts.de/orca/),
[BAGEL](https://nubakery.org), [RDKit](https://www.rdkit.org),
[LangGraph](https://langchain-ai.github.io/langgraph/),
[3Dmol.js](https://3dmol.csb.pitt.edu), [Ketcher](https://lifescience.opensource.epam.com/ketcher/)
and [Ollama](https://ollama.com). Molecule data from
[PubChem](https://pubchem.ncbi.nlm.nih.gov); literature search via
[Semantic Scholar](https://www.semanticscholar.org).
