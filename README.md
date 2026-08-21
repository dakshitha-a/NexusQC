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
proper input file for whichever engine actually supports the method, runs it
in the background, and reports **real numbers parsed from the program's own
output**. Never numbers a language model made up because they sounded plausible.

Everything runs on your own hardware: a local LLM through
[Ollama](https://ollama.com), plus up to three real engines —
[PySCF](https://pyscf.org), [ORCA](https://www.faccts.de/orca/) and
[BAGEL](https://nubakery.org).

What separates this from a chatbot with a calculator bolted on:

🔒 **Nothing runs without your approval.** Every job pauses on a real graph
interrupt and shows you the exact input file first. That's structural, not a
prompt instruction, so it holds even if the model never thinks to ask.

🤔 **It asks instead of guessing.** Missing a basis set or an active space?
You get a specific question back, not a silently-chosen default that quietly
produces wrong physics.

🔁 **It helps you debug failures, but only when you ask it to.** A failed job
says so plainly and changes nothing on its own. Press *Troubleshoot* and the
agent reads the engine's actual output, checks the manual, searches the web
if it needs to, and explains what went wrong. Any corrected job it proposes
still needs your approval — it won't resubmit on its own initiative, because
guessing at a fix can burn hours of compute you never agreed to.

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

Every job is a `task`/`subtype` pair (`single_point/grad`, `opt/ci`, and so
on), and that pair is what actually decides which engines and methods are
even on the table — the app's own capability registry works the same way, so
this table is a direct read of it, not a hand-kept summary that can drift.
**Bold** marks which engine you get if you don't name one yourself: PySCF
first, then ORCA, then BAGEL, in that preference order, for whichever engines
the row supports. Two mechanical exceptions override that order regardless of
row: CASPT2 always routes to BAGEL (ORCA has NEVPT2 instead, not CASPT2, and
PySCF has neither here), and a CASSCF job that asks for oscillator strengths
always routes to ORCA, since it's the only engine here that computes them for
CASSCF. PySCF is bundled and always available; ORCA and BAGEL are optional.

| Job type | Subtype | Programs & methods | What it does |
|---|---|---|---|
| `single_point` | `gs` — ground state | **PySCF**: HF, DFT, MP2, CCSD, EOM-CCSD, CASSCF · ORCA: same six · BAGEL: HF, CASSCF, CASPT2 | One ground-state energy at a fixed geometry. |
| `single_point` | `ee` — excited states | **PySCF**: HF, DFT, EOM-CCSD, CASSCF · ORCA: same four · BAGEL: CASSCF, CASPT2 | Vertical excitation energies, with oscillator strengths where the engine computes them. TDDFT, TDA-DFT, CIS and TD-HF all live here — they're the HF/DFT case with `use_tda` toggled, not separate job types. Asking EOM-CCSD for 0 excited states is read as a plain ground-state CCSD energy rather than run as a degenerate excited-state job. |
| `single_point` | `grad` — energy gradient | **PySCF**: HF, DFT, MP2, CCSD, CASSCF · ORCA: HF, DFT, MP2, CASSCF · BAGEL: HF, CASSCF, CASPT2 | The nuclear gradient, ground or excited state. An excited-state gradient needs HF/DFT; B3LYP and BLYP specifically are refused on ORCA (see [Limitations](#limitations)). |
| `single_point` | `nac` — non-adiabatic coupling | **PySCF**: CASSCF, SA-CASSCF only · ORCA: HF, DFT, ground-to-excited only (its CIS/TDDFT module has no excited-to-excited coupling) · BAGEL: CASSCF, CASPT2 | The derivative coupling between a pair of electronic states. |
| `opt` | `min` — minimum | **PySCF**: HF, DFT, MP2, CCSD, CASSCF · ORCA: HF, DFT, MP2, CASSCF · BAGEL: HF, CASSCF, CASPT2 | Relax the structure to an energy minimum. On PBE0-class functionals, PySCF and ORCA can target an excited-state minimum instead of the ground state. |
| `opt` | `constrained` | **PySCF**: HF, DFT, MP2, CCSD, CASSCF · ORCA: HF, DFT, MP2, CASSCF | Freeze a bond, angle or dihedral at a chosen value. Not offered on BAGEL — its constraint mechanism accepts the keyword, exits clean, and moves the frozen atom anyway, confirmed by comparing geometries rather than trusting the exit code. |
| `opt` | `ci` — conical intersection | ORCA: HF, DFT, ground-state-inclusive crossings only · **BAGEL**: CASSCF, CASPT2, gradient-projection MECP | Find the minimum-energy crossing point between two electronic states. |
| `freq` | — | **PySCF**: HF, DFT, CASSCF · ORCA: HF, DFT, MP2, CASSCF · BAGEL: HF, CASSCF, CASPT2 | Harmonic frequencies and thermochemistry, with animated normal modes on all three engines. |
| `opt_freq` | — | **PySCF**: HF, DFT, CASSCF · ORCA: HF, DFT, MP2, CASSCF · BAGEL: HF, CASSCF, CASPT2 | One job: optimize, then run frequencies at the result. |
| `pes_1d` | — | **PySCF**: HF, DFT, MP2, CCSD, EOM-CCSD, CASSCF · ORCA: same six | Step one bond, angle or dihedral and compute the chosen task at each point, as real parallel sub-jobs. Not on BAGEL — use `interp_pes` instead. |
| `interp_pes` | — | **PySCF**: HF, DFT, MP2, CCSD, EOM-CCSD, CASSCF · ORCA: same six · BAGEL: HF, CASSCF, CASPT2 | Interpolate between two geometries (Cartesian, LIIC or IDPP) and compute the chosen task at each image. A hand-edited image's input becomes a template applied to every image, not just that one. |
| `neb_ts` | — | ORCA only: HF, DFT, MP2, CASSCF | Nudged-elastic-band search for a transition state, with per-frame orbitals. Its excited-state path is less verified than the ground-state one. |
| `wigner_spectra` | — | **PySCF**: HF, DFT, EOM-CCSD, CASSCF · ORCA: same four · BAGEL: CASSCF, CASPT2 | Wigner-samples geometries from a completed frequency job's normal modes, runs an excited-state calculation at each, and pools the result into one broadened absorption spectrum — default 50 samples, up to 500. |
| `cas_reco` | `explain` | **PySCF**: CASSCF | Explains a proposed active space against the literature, no recommendation pilot run. |
| `cas_reco` | `autocas` | **PySCF**: CASSCF | autoCAS-style single-orbital-entropy pilot, then a state-averaged CASSCF on the recommended space. [More below.](#picking-a-cas-active-space) |
| `cas_reco` | `avas` | **PySCF**: CASSCF | Builds an active space straight from atomic-valence character labels, skipping the entropy pilot. |
| `blind` | — | ORCA: HF, DFT, MP2, CCSD, EOM-CCSD, CASSCF · BAGEL: HF, CASSCF, CASPT2 | Runs a literal, user-supplied ORCA or BAGEL input verbatim. No structured parameter building, and deliberately no PySCF here — no user-supplied Python ever executes in this app. |
| `batch` | — | **PySCF**: HF, DFT, MP2, CCSD, EOM-CCSD, CASSCF · ORCA: same six · BAGEL: HF, CASSCF, CASPT2 | Runs a single-point, optimization, frequencies, or optimization+frequencies job over every geometry from a geometry set, a PES scan, an interpolated path, a Wigner sample set, a NEB-TS run, or 3+ structures tagged in the molecule panel. |

Orbital visualization isn't a job type of its own because it's automatic on any
completed job's own drawer, nothing to submit separately for it.

Ask for something none of them can do (a Gaussian or Psi4 calculation, say)
and it will write you the input file in chat anyway, then say plainly that it
can't run it here.

Any CASSCF or CASPT2 job can start from a previous CASSCF/CASPT2 job's
converged orbitals instead of a fresh guess. Tag the source job and the new
one restarts from it, same engine only (orbital files aren't converted
between engines). On PySCF this can cut macro-iterations noticeably when the
two geometries are close; on ORCA and BAGEL it uses each engine's own restart
mechanism, `MOREAD`/`%moinp` and `load_ref` respectively.

A new job can also run on a **previous job's own geometry** instead of
whatever is sitting in the molecule panel. "Run that again with a bigger
basis" or "same geometry as job X" both work, and since the agent already
has the job id from earlier in the conversation, it never has to ask you for
one. It uses that job's optimized geometry if it produced one, otherwise its
input geometry; a job with no single geometry of its own (a PES scan, a
batch, a Wigner ensemble) gets refused by name rather than guessed at.

### Working with it

- **Molecules by name, SMILES, pasted XYZ, or sketch.** Resolved via PubChem
  and OPSIN, shown immediately in 3D with numbered atoms. You don't need to
  run a calculation just to look at something.
- **Or upload a geometry file.** Drop an `.xyz` on the composer or the Files
  panel and one geometry becomes the active molecule, two become a pair
  (start/end for an interpolated path or NEB), and three or more become a
  `geometry_set`, a cycling, taggable collection you can pull individual
  frames from into later calculations. ORCA/BAGEL input files
  (`.inp`/`.input`/`.json`) upload the same way and attach into the
  conversation with the same one-click action: the content lands in the chat
  itself, so asking to "run this verbatim" fills a blind job's input from
  what you attached, with nothing to retype.
- **Typos get a menu, not a guess.** Basis sets and functionals are matched
  mechanically against the names each engine really recognises, and you pick
  from a short list. If none of them is what you meant, the menu's last entry
  searches [Basis Set Exchange](https://www.basissetexchange.org/) for the
  exact published basis set (bundled offline, not a network call) and
  confirms it covers every element in your molecule before offering it. It
  then works on any engine, with the per-engine translation handled for you.
- **Nothing blocks the UI.** Jobs are background subprocesses, and chat,
  status and results all stream live. A CASSCF job can run for hours; close
  the tab, come back later, it'll still be there.
- **Uses the whole machine, politely.** Every core is available. By default
  each ORCA/BAGEL job takes 4, up to 20 run at once, and new jobs are
  admitted only when the host genuinely has headroom, so an idle machine
  gets used and a busy one gets left alone. All of this is tunable at setup;
  see
  [CONFIGURATION.md](docs/CONFIGURATION.md#job-execution-and-resource-limits).
- **Hand-edit before running.** ORCA and BAGEL input can be edited on the
  approval card and is sanity-checked before it runs.

### Results you can actually inspect

- **Orbitals on every completed job**, with a per-orbital energy and occupancy
  table. Click any row for a 3D isosurface with an isovalue slider. CASSCF
  shows genuine fractional natural-orbital occupations, not the integer
  HF-style ones.
- **UV/Vis and IR spectra**, with the leading orbital-pair character named for
  each excited state, read straight from the engine's own CI vectors rather
  than inferred.
- **Animated vibrational modes**, on all three engines.
- **Nuclear-ensemble absorption spectra**, pooled across every sampled
  geometry of a Wigner ensemble, with a per-excited-state breakdown under the
  total curve and the raw broadened data downloadable as `.dat`. A
  broadening-width slider on the job's own drawer re-renders instantly as you
  drag it: the pooled transitions are fetched once and re-broadened entirely
  in the browser, with no server round trip per move. You can ask which
  sampled geometries absorb near a given energy, or for a re-plot at a
  specific width, without recomputing anything.
- **Cross-job comparison charts**, rendered inline in the conversation.

When a job genuinely has no oscillator strengths or IR intensities to plot,
it says so instead of drawing a flat line and pretending otherwise.

**Everything on screen is downloadable, not just the job data.** Alongside
the whole job, its raw input and output, and any geometry as `.xyz`, you can
save a PNG of a 3D viewer's *current* state (the camera angle you rotated to,
the isovalue you chose, the frame you're on) plus a vibrational mode as an
animated PNG. Files are named after the job, so a downloads folder reads as
`20260817_water_Freq_HF_sto-3g_ORCA_78a32a61_mode3_3840cm-1.png` rather than a
row of hex ids, and renaming a job carries through to its downloads too.
Every plot (spectra, scan/optimization energy traces, comparisons) downloads
as a high-resolution 8×6 PNG.

**Every plain-text document viewer has a find bar, with typo tolerance.** A
job's raw input/output, a knowledge-base manual, and an uploaded geometry or
input file all open into the same viewer. Ctrl/Cmd+F focuses its search box
without leaving the page, matches get counted and highlighted, and a query
that's close to a word but not exact (a typo, an unfamiliar spelling) still
finds it. A KB source that renders natively (PDF, HTML) keeps the browser's
own viewer instead, since that gets you real page layout and its own find UI
for free.

<div align="center">
<img src="docs/screenshot-results.png" alt="A completed job: the agent's summary of the total energy, HOMO-LUMO gap and dipole moment, beside the job detail drawer showing parsed results and the per-orbital energy, occupancy and character table" width="900">
<br>
<sub><i>A finished HF/STO-3G run on water. Every number is parsed from PySCF's own output — the orbital characters and localisations included.</i></sub>
</div>

### Picking a CAS active space

Choosing a CASSCF active space by hand is one of the most error-prone
judgement calls in multireference chemistry. Too small and you miss the
physics; too large and it becomes intractable.

`recommend_active_space` automates the first half, using the idea behind
[autoCAS](https://doi.org/10.1021/acs.jctc.6b00722): seed a candidate space
from valence orbital character with
[AVAS](https://doi.org/10.1021/acs.jctc.7b00347), compute single-orbital
entropies over a deliberately cheap unconverged pilot, sweep for the stable
"plateau" that marks a chemically meaningful cutoff, then run a fully
converged state-averaged CASSCF on exactly that space. Each orbital comes
back classified by character (σ/π/n/σ*/π*) and dominant atoms, with an
isosurface viewer and the entropy plateau diagram.

Two pilot backends are available: exact CASCI (fast, no extra dependency) or
DMRG via [block2](https://github.com/block-hczhai/block2-preview), which
screens a much larger candidate pool before truncation. Both feed the same
final CASSCF.

AVAS itself has no notion of how many electronic states you're after because it's
a one-electron orbital-selection method, so a request for, say, 3 states
never stops it from producing a recommendation. If the recommended space
genuinely can't host that many states even after widening it along the
entropy ranking, the final CASSCF runs with however many states the space
actually supports and says so plainly, rather than refusing to show you
anything at all.

> A minimal basis systematically under-represents diffuse and Rydberg
> character. Treat a recommendation from STO-3G as a starting point, not a
> final answer, especially for excited states with charge-transfer character.

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

Written for someone starting from a bare Linux machine. Already done one of
these steps? Skip it and move on.

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

The console is reached from the cogwheel in the sidebar header, next to the
help button, along with account settings and sign-out. It is organised as a
section list — Overview, Invites, Users, Bug reports, Storage, Audit log and a
Danger zone — with one section shown at a time, and rows that open in place to
show the full record and the actions belonging to it.

Everything routine happens there rather than through raw API calls: minting
an invite link and copying it, revoking one that was sent to the wrong
person or leaked, suspending or restoring an account, deleting one along
with all of its data, reading per-user storage usage, and triaging bug
reports filed from the app. Revocation is soft, so a revoked invite stays
listed as revoked instead of vanishing. The last active admin can't be
deleted or suspended, and there's no password-reset flow, so locking
yourself out is recoverable only by destroying every account. Every user,
admin or not, can change their own password from the account panel; doing so
signs out that account's other sessions but not the one making the change.

**Every user, admin or not, also has their own danger zone** in the same
account panel: a "download all my data" button (a zip of every job, KB
upload and geometry/input file upload they own) and a self-scoped purge of
the same three categories, gated behind typing `DELETE MY DATA`. A
still-running job always gets stopped first, never left as an orphaned
process. Unlike the admin console's account deletion, this leaves chat
history and the account itself untouched. It clears out old jobs and
uploads, not the account.

**Bug reports carry screenshots.** "Report a bug" is its own entry in the
cogwheel menu, for every user including admins. A screenshot can be pasted
straight into the report box from the clipboard, or picked as a file (up to
three images, 5MB each). Attachments deliberately don't count against the
reporter's storage quota, since a quota-blocked bug report helps nobody. On
the admin side a report opens to show its full text, who filed it, and its
screenshots, and can then be closed, archived (reversible, drops out of the
default list and the open count) or deleted outright, which also removes the
image files from disk.

**The three deployment-wide purges require typing their phrase** (`PURGE ALL
JOBS`, `PURGE ALL KB`, `PURGE ALL CHAT`) rather than a second click. They act
on every user at once with no undo, and a second click in the same place is
too easy to do by reflex. Per-user and per-invite actions keep the lighter
two-click confirm.

```bash
cp .env.example .env          # set the Postgres password and JWT secret
docker compose build
docker compose up -d
docker compose run --rm api python -m server.admin_cli bootstrap-admin \
  --email you@yourlab.edu --username admin
```

Setting `QC_AGENT_DATABASE_URL` is the single switch that activates the whole
auth layer. **HTTPS is mandatory**: the session cookie is `Secure`, so login
silently fails over plain HTTP.

👉 **[Full deployment guide](docs/DEPLOYMENT.md)**, covering certificates,
quotas, admin operations, lockout recovery, and an honest account of what is
and isn't verified.

If you're running a deployment that other people depend on, run a **second,
destructible stack** beside it and test there first. `scripts/dev_stack.sh`
brings one up on its own compose project, its own port and its own secrets.
`scripts/promote.sh` then moves the real deployment forward, but only to
commits that second stack has already verified, and it reports first what
the update will do to running jobs, the database schema, and anything else
it can't undo.

👉 **[Workflow guide](docs/WORKFLOW.md)**, covering the dev/production split,
promotion, destructive-change warnings, and rollback.

---

## Documentation

| Document | What it covers |
|---|---|
| [WORKFLOW.md](docs/WORKFLOW.md) | Branching, merging, releasing, testing, and promoting to a production deployment |
| [ARCHITECTURE.md](docs/ARCHITECTURE.md) | How it works and why, including rejected alternatives |
| [DEPLOYMENT.md](docs/DEPLOYMENT.md) | Multi-user Docker deployment, start to finish |
| [CONFIGURATION.md](docs/CONFIGURATION.md) | Every environment variable and job-parameter default |
| [TESTING.md](docs/TESTING.md) | What was tested, results, and what was **not** tested |
| [BACKLOG.md](docs/BACKLOG.md) | The living record of unimplemented bugs and features, and what remains unverified |
| [DEVELOPMENT.md](docs/DEVELOPMENT.md) | Contributing: the two-remote workflow, the public-safety scan, and how releases are cut |
| [CHANGELOG.md](CHANGELOG.md) | What changed in each release |
| [NOTICE.md](NOTICE.md) | Third-party licences and attribution |

---

## Limitations

Worth knowing before you rely on it:

- **CASPT2 is BAGEL-only**, and oscillator strengths for CASSCF and EOM-CCSD
  are ORCA-only. Neither has a workaround.
- **ORCA refuses an excited-state gradient/NAC for the B88-containing
  functionals this app checks for (B3LYP, BLYP)**, with no working
  substitute here. A documented LibXC rewrite was tried and came back with a
  ground-state energy about 1.2 Hartree off from real B3LYP, so the
  combination is refused outright rather than run with a wrong functional.
  That's a confirmed absence in ORCA itself, not a syntax this app got
  wrong. The check is by exact functional name rather than a general B88
  detector, so a different B88-derived functional (CAM-B3LYP, BP86) slips
  past it and fails with ORCA's own error at run time instead. That's still
  safe, since no rewrite ever gets applied, just less informative than the
  pre-submission refusal. Use a different functional (PBE0 works) or ask for
  the ground-state gradient instead.
- **`wb97x-d` (bare, no dispersion-version digit) is invalid on both PySCF
  and ORCA, for opposite reasons**, despite being the form most papers
  actually write. PySCF's libxc parser accepts the name, but its TDDFT
  gradient driver has no implementation behind it. ORCA's own functional
  list has no entry without an explicit version (`D3`, `D3BJ`, `D4`,
  `D4REV`, or `V` for the VV10-based forms), and refuses it at input-check
  time. Bare `wb97x` with no dispersion is confirmed working end to end on
  both engines. `wb97x-d3` is confirmed working on ORCA but not PySCF.
  `wb97x-d3bj`, `wb97x-d4` and the VV10 forms (`wb97x-v`, `wb97m-v`) are
  real ORCA keywords, but crashed or aborted in testing on this host and
  aren't offered as verified yet. See `docs/PARSER_GAPS.md`.
- **NEB transition-state search is ORCA-only**, and its excited-state path
  is less verified than the ground-state one.
- **BAGEL's CASSCF geometry optimization and frequencies are structurally
  confirmed, not convergence-verified**, end to end.
- **No general pre-flight validator** exists for basis sets and keywords. An
  invalid basis gets caught when the engine fails, and *Troubleshoot* is how
  you turn that failure into an actual diagnosis.
- **The public nginx listener hasn't been verified end to end.**
- **Web search is the only component that calls the public internet**, and
  it sends your query text to a third party. Everything else, the LLM,
  embeddings, engines, knowledge base, stays local.

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
