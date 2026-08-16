"""Central configuration for the computational chemistry agent.

All paths and external-tool settings live here so the rest of the app
never hardcodes a filesystem path or binary location.
"""
from __future__ import annotations

import os
from pathlib import Path

# --- Filesystem layout -----------------------------------------------------
PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "data"
JOBS_DIR = DATA_DIR / "jobs"
KB_DIR = DATA_DIR / "kb"
UPLOADS_DIR = DATA_DIR / "uploads"
MOLECULES_DIR = DATA_DIR / "molecules"
THREADS_FILE = DATA_DIR / "threads.json"  # conversation registry, see app/agent/threads.py

for _d in (DATA_DIR, JOBS_DIR, KB_DIR, UPLOADS_DIR, MOLECULES_DIR):
    _d.mkdir(parents=True, exist_ok=True)

# --- LLM (OpenAI-compatible endpoint served by Ollama) ----------------------
LLM_BASE_URL = os.environ.get("QC_AGENT_LLM_BASE_URL", "http://localhost:11434/v1")
LLM_API_KEY = os.environ.get("QC_AGENT_LLM_API_KEY", "ollama")  # unused by ollama, but required by the OpenAI client
LLM_MODEL = os.environ.get("QC_AGENT_LLM_MODEL", "qwen3:30b")
LLM_TEMPERATURE = float(os.environ.get("QC_AGENT_LLM_TEMPERATURE", "0.1"))

# Embedding model, served the same way via Ollama's /api/embeddings.
OLLAMA_HOST = os.environ.get("QC_AGENT_OLLAMA_HOST", "http://localhost:11434")
EMBEDDING_MODEL = os.environ.get("QC_AGENT_EMBEDDING_MODEL", "nomic-embed-text")
# Every embedding call (search_knowledge_base, and the automatic manuals-KB
# lookup _kb_context_for_job runs on every generate_job_input/submit_job
# call) happens inside a graph turn while _graph_lock is held -- an
# unbounded HTTP client here would mean a stalled Ollama embedding request
# could hold that lock indefinitely, blocking every other conversation's
# chat turns and approvals. langchain_ollama's OllamaEmbeddings has no
# timeout by default, unlike the chat LLM client (see graph.py's
# `timeout=150` on ChatOpenAI).
OLLAMA_EMBEDDING_TIMEOUT = float(os.environ.get("QC_AGENT_OLLAMA_EMBEDDING_TIMEOUT", "30"))

# --- Quantum chemistry engines ----------------------------------------------
ORCA_BIN = os.environ.get("QC_AGENT_ORCA_BIN", "/opt/Orca-6.1.1/orca")
# orca_plot ships alongside the main `orca` binary in the same install dir.
# Used to render MO cube files directly from a completed job's .gbw file --
# verified (point-sampled against a PySCF calculation on the same
# geometry/basis) to produce correct orbital shapes, unlike routing ORCA's
# orbitals through a molden export and pyscf.tools.molden/cubegen, which
# was found to apply a shell-dependent normalization mismatch that distorts
# the resulting MO (see orca_runner.py's
# render_orbital_cube for the full story).
ORCA_PLOT_BIN = os.environ.get(
    "QC_AGENT_ORCA_PLOT_BIN", str(Path(ORCA_BIN).with_name("orca_plot"))
)
BAGEL_BIN = os.environ.get("QC_AGENT_BAGEL_BIN", "/opt/bagel-1.2.2/bin/BAGEL")
BAGEL_ONEAPI_SETVARS = os.environ.get(
    "QC_AGENT_BAGEL_SETVARS", "/opt/intel/oneapi/setvars.sh"
)
MPIRUN_BIN = os.environ.get("QC_AGENT_MPIRUN_BIN", "/usr/bin/mpirun")

def _detect_usable_cores() -> int:
    """`os.cpu_count()`/`os.sched_getaffinity` report the *host's* raw
    logical CPU count (255!) -- using that to size MPI/OpenMP parallelism
    causes ORCA/BAGEL to request far more ranks/threads than are sensible
    to use at once, which manifests as intermittent, hard-to-diagnose MPI
    crashes and (on a shared host) is simply impolite. `nproc` (coreutils)
    gives a much smaller, sane number instead, so shell out to it. NOTE:
    on this specific deployment that smaller number is NOT coming from a
    cgroup CPU quota, despite this function's name and an earlier version
    of this comment claiming so -- there is no cgroup CPU limit here at
    all (confirmed empirically: cpu.max is unlimited at every level of
    this session's cgroup hierarchy, and os.sched_getaffinity(0) returns
    all 255 host core IDs, meaning nothing pins this process to a subset).
    `nproc` is actually picking up the `OMP_NUM_THREADS=8` environment
    variable set in this host's shell profile (GNU nproc prioritizes that
    env var over cgroup/affinity detection when present) -- i.e. this is a
    voluntary, self-imposed courtesy convention for this shared host, not
    a kernel-enforced ceiling. Nothing stops any single job from actually
    using more than N_CORES cores if asked to; N_CORES is deliberately
    kept as "how many cores one job should request" regardless of this,
    and JobManager._wait_for_resources' host-wide gate (base.py) is
    deliberately NOT layered with an additional app-scoped "this app's
    jobs collectively never exceed N_CORES" cap -- a user's own testing
    on this exact host confirmed a preference for higher throughput (this
    app's own concurrently-running jobs may collectively use more than
    N_CORES cores when the wider host genuinely has idle capacity) over a
    perpetual self-limit to whatever OMP_NUM_THREADS happens to be set to
    system-wide for unrelated reasons."""
    try:
        import subprocess
        return int(subprocess.run(["nproc"], capture_output=True, text=True, timeout=5).stdout.strip())
    except Exception:
        return min(os.cpu_count() or 4, 8)


N_CORES = int(os.environ.get("QC_AGENT_N_CORES", str(_detect_usable_cores())))
MAX_MEMORY_MB = int(os.environ.get("QC_AGENT_MAX_MEMORY_MB", "8000"))  # per-job, PySCF convention

MAX_CONCURRENT_JOBS = int(os.environ.get("QC_AGENT_MAX_CONCURRENT_JOBS", "4"))

# Explicit CASSCF/CASPT2 convergence policy, applied identically across all
# three engines (pyscf's mc.conv_tol/max_cycle_macro, ORCA's %casscf
# ETol/MaxIter, BAGEL's casscf-block thresh/maxiter) rather than leaving each
# engine at its own differing default (pyscf 1e-7/50, ORCA 1e-8/75, BAGEL
# 1e-8/50). Energy-only CASSCF/CASPT2 jobs use the looser tolerance; any job
# involving a nuclear-coordinate derivative (geometry optimization or
# frequency) uses the tighter one, since a loose wavefunction convergence
# would otherwise show up as noise in the gradient/Hessian.
CASSCF_CONV_TOL_ENERGY = float(os.environ.get("QC_AGENT_CASSCF_CONV_TOL_ENERGY", "1e-6"))
CASSCF_CONV_TOL_OPT_FREQ = float(os.environ.get("QC_AGENT_CASSCF_CONV_TOL_OPT_FREQ", "1e-7"))
CASSCF_MAX_CYCLE_MACRO = int(os.environ.get("QC_AGENT_CASSCF_MAX_CYCLE_MACRO", "200"))

# Soft resource-headroom gate on top of MAX_CONCURRENT_JOBS (a job-COUNT cap):
# JobManager won't start a newly-queued job until the HOST is under
# MAX_CPU_PERCENT average CPU and MAX_MEM_PERCENT memory, AND at least
# N_CORES individual logical cores are currently idle (see
# CORE_IDLE_THRESHOLD_PERCENT below). This machine is genuinely shared with
# other tenants/processes outside this app's control, so the gate reasons
# about the host's real headroom, not just this app's own job subprocess
# trees -- an earlier app-scoped-only version of this gate would dispatch a
# new N_CORES-core job even while some other tenant had the host pinned,
# compounding load on a machine something else was already stressing.
# MAX_CPU_PERCENT's *meaning* is therefore a full-host average across every
# logical CPU the host reports (255 in this deployment), not "% of this
# app's own N_CORES budget" -- reaching 80% of that average takes roughly
# 200+ of 255 cores near-saturated simultaneously, a rare whole-host-in-
# distress event. In practice the idle-core-count check below is what does
# the meaningful gatekeeping at ordinary levels of contention; the aggregate
# check is a coarse backstop, kept as its own condition (not dropped as
# "redundant") since it catches diffuse load spread thin across many cores
# that wouldn't show up as "N_CORES specific cores busy." See
# JobManager._wait_for_resources / _host_cpu_snapshot in base.py.
MAX_CPU_PERCENT = float(os.environ.get("QC_AGENT_MAX_CPU_PERCENT", "80"))
MAX_MEM_PERCENT = float(os.environ.get("QC_AGENT_MAX_MEM_PERCENT", "80"))
# A logical core counts as "idle" (available for a new job's share of
# parallelism) when its own individual psutil.cpu_percent reading is below
# this threshold -- used together with N_CORES in _wait_for_resources'
# idle-core-count check.
CORE_IDLE_THRESHOLD_PERCENT = float(os.environ.get("QC_AGENT_CORE_IDLE_THRESHOLD_PERCENT", "20"))

# --- Molecule name resolution (app/chemistry/molecule.py) -------------------
# molecule_from_name (called from the set_molecule/generate_job_input tools,
# both of which run inside a graph turn holding _graph_lock) tries PubChemPy
# first. Unlike every other outbound call in this app, PubChemPy calls
# urllib.request.urlopen() with no timeout argument at all (confirmed by
# reading its source -- request() in pubchempy.py), so it inherits Python's
# process-wide socket default, which is `None` (block forever) unless set.
# A stalled/unreachable PubChem endpoint would therefore hang the calling
# tool -- and with it _graph_lock, and with it every open conversation's
# chat turns and job approvals -- indefinitely, with no way to recover short
# of restarting the backend. Same failure class already fixed for Ollama
# embeddings/DDGS/Semantic Scholar above; PubChemPy offers no per-call
# timeout parameter to pass, so this is applied via a scoped
# socket.setdefaulttimeout() around just that call (see
# _resolve_name_to_smiles) rather than a library-level option.
MOLECULE_LOOKUP_TIMEOUT = float(os.environ.get("QC_AGENT_MOLECULE_LOOKUP_TIMEOUT", "15"))

# --- Semantic Scholar (app/agent/scholar_search.py) -------------------------
# Free API key, optional but effectively required for reliable use -- the
# shared unauthenticated pool was observed to return 429 Too Many Requests
# unpredictably during development. Apply at
# https://www.semanticscholar.org/product/api#api-key-form
SEMANTIC_SCHOLAR_API_KEY = os.environ.get("QC_AGENT_SEMANTIC_SCHOLAR_API_KEY", "")
SEMANTIC_SCHOLAR_TIMEOUT = float(os.environ.get("QC_AGENT_SEMANTIC_SCHOLAR_TIMEOUT", "15"))

# --- Web search (app/agent/web_search.py) -----------------------------------
# ddgs.DDGS itself already defaults to a 5s per-engine timeout even with no
# explicit value passed -- this makes that bound explicit/tunable rather
# than relying on the library's own default, same reasoning as
# SEMANTIC_SCHOLAR_TIMEOUT above (this call also runs inside a graph turn
# holding _graph_lock).
WEB_SEARCH_TIMEOUT = float(os.environ.get("QC_AGENT_WEB_SEARCH_TIMEOUT", "10"))

# --- FastAPI server (server/main.py) ----------------------------------------
# Local dev default is localhost-only, matching the original single-user
# workflow (`python -m server.main` behind a Vite dev proxy). The containerized
# deployment (Dockerfile/docker-compose.yml) overrides QC_AGENT_SERVER_HOST to
# 0.0.0.0 -- the container's own network namespace is the real boundary there,
# since nginx (not this process) is the only thing exposed to the host network.
SERVER_HOST = os.environ.get("QC_AGENT_SERVER_HOST", "127.0.0.1")
SERVER_PORT = int(os.environ.get("QC_AGENT_SERVER_PORT", "8000"))

# --- LangGraph checkpointer (app/agent/graph.py) ----------------------------
# Unset (the local-dev default): the checkpointer stays SqliteSaver against
# data/agent_checkpoints.sqlite, exactly today's zero-config behavior -- no
# Postgres required to run `python -m server.main` directly. Set by
# docker-compose.yml in the containerized deployment, where the checkpointer
# switches to a Postgres-backed one (see graph.py's _get_checkpointer) so
# conversation state survives being read/written from multiple threads
# without the single-shared-sqlite-connection bottleneck the old design had.
DATABASE_URL = os.environ.get("QC_AGENT_DATABASE_URL", "")
# Each checkpoint read/write checks a connection out of this pool and back in
# (langgraph-checkpoint-postgres does this per-call, not once per turn --
# confirmed by reading its _internal.get_connection helper), so this bounds
# concurrent in-flight *database operations*, not concurrent in-flight chat
# turns (those are bounded by the per-thread lock in graph.py instead, which
# only blocks two turns on the *same* conversation from overlapping).
DATABASE_POOL_MAX_SIZE = int(os.environ.get("QC_AGENT_DATABASE_POOL_MAX_SIZE", "20"))

# CORS: only matters when a browser origin differs from the API's own origin
# (the Vite dev server on a different localhost port, or a dev-mode split
# frontend/backend). Once nginx serves both the built SPA and /api/* from one
# origin in the deployed stack, this allowlist should stay empty/unused.
SERVER_CORS_ORIGINS = os.environ.get(
    "QC_AGENT_SERVER_CORS_ORIGINS",
    "http://localhost:5173,http://127.0.0.1:5173",
).split(",")

# --- Auth (app/auth/, server/routes/auth.py) --------------------------------
# Unset locally by default -- auth is only meaningful once DATABASE_URL is
# also set (see above), i.e. in the containerized deployment. JWT_SECRET has
# no safe default: app/auth/security.py refuses to sign/verify tokens with
# an empty secret rather than silently using one, since an empty/predictable
# secret would let anyone forge a valid session cookie for any user.
JWT_SECRET = os.environ.get("QC_AGENT_JWT_SECRET", "")
JWT_ALGORITHM = "HS256"
SESSION_TTL_SECONDS = int(os.environ.get("QC_AGENT_SESSION_TTL_SECONDS", str(7 * 24 * 3600)))  # 7 days, matches the "remember me" duration from the original deployment ask

# Redis backs the one-session-per-user "log out other devices" enforcement
# (app/auth/redis_session.py) -- a fast, TTL'd registry, not the durable
# record of a session (that's the `sessions` Postgres table; Redis is purely
# an enforcement-speed cache that can be rebuilt/expired without data loss).
REDIS_URL = os.environ.get("QC_AGENT_REDIS_URL", "")
