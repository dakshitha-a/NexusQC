"""Central configuration for NexusQC.

All paths and external-tool settings live here so the rest of the app
never hardcodes a filesystem path or binary location.
"""
from __future__ import annotations

import os
from pathlib import Path

# --- Filesystem layout -----------------------------------------------------
PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _load_dotenv(path: Path) -> None:
    """Load `KEY=value` pairs from a project-root `.env` into os.environ.

    Deliberately hand-rolled rather than pulling in python-dotenv: this needs
    to run before any other config value is read, and the format we care about
    is a handful of unquoted `KEY=value` lines that docker compose already
    parses the same way -- so one file drives both the compose deployment and
    a bare-metal `python -m server.main` run, instead of bare-metal relying on
    whatever happens to be exported in the operator's shell.

    An already-set environment variable always wins, so an explicit
    `QC_AGENT_FOO=... python -m server.main` still overrides the file, and the
    container (which gets its values injected by compose) is unaffected.
    """
    if not path.is_file():
        return
    for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        if not key or key in os.environ:
            continue
        os.environ[key] = value.strip().strip('"').strip("'")


_load_dotenv(PROJECT_ROOT / ".env")

DATA_DIR = PROJECT_ROOT / "data"
JOBS_DIR = DATA_DIR / "jobs"
KB_DIR = DATA_DIR / "kb"
UPLOADS_DIR = DATA_DIR / "uploads"
# Uploaded geometry (.xyz) and blind engine-input (.inp/.input/.json) files --
# app/uploads/store.py. Deliberately separate from UPLOADS_DIR (KB's own
# per-owner upload tree): app/rag/store.py's orphan-sweep and
# app/auth/storage_quota.py's KB usage accounting both enumerate every file
# under UPLOADS_DIR/<owner>/ as "a KB upload with no matching Chroma entry is
# leaked and should be reclaimed" -- a geometry file living in that same tree
# would be silently deleted by that sweep, and would count toward nothing
# (invisible to KB quota, since it enumerates from Chroma, and invisible to
# every other quota category) on a multi-user deployment.
GEOMETRY_UPLOADS_DIR = DATA_DIR / "geometry_uploads"
MOLECULES_DIR = DATA_DIR / "molecules"
SCRAPED_DIR = DATA_DIR / "scraped"  # raw manual text from scripts/seed_knowledge_base.py, read directly by
# app/chemistry/jobs/keyword_suggest.py's engine-specific basis/functional name pools -- see that module for why
# this bypasses the Chroma/embeddings pipeline (data/rag/*) entirely rather than reusing search_knowledge_base.
BSE_BAGEL_CACHE_DIR = DATA_DIR / "bse_basis_cache" / "bagel"  # translated Basis Set Exchange -> BAGEL JSON basis
# files, see app/chemistry/jobs/bse_basis.py -- content-hashed filenames, written once and reused (a pure function
# of (name, elements), so this is a cache, not a source of truth).
THREADS_FILE = DATA_DIR / "threads.json"  # conversation registry, see app/agent/threads.py
BUG_REPORTS_DIR = DATA_DIR / "bug_reports"  # screenshots attached to bug reports, one subdirectory per report id.
# Deliberately NOT under UPLOADS_DIR: that tree is per-owner and enumerated by the storage-quota accounting, and a
# bug report's screenshot must not count against the reporter's quota -- a quota-blocked bug report is perverse.
# Bounded instead by per-file/per-report caps in server/routes/bugs.py.

for _d in (
    DATA_DIR, JOBS_DIR, KB_DIR, UPLOADS_DIR, GEOMETRY_UPLOADS_DIR, MOLECULES_DIR, BSE_BAGEL_CACHE_DIR,
    BUG_REPORTS_DIR,
):
    _d.mkdir(parents=True, exist_ok=True)

# --- LLM (OpenAI-compatible endpoint served by Ollama) ----------------------
LLM_BASE_URL = os.environ.get("QC_AGENT_LLM_BASE_URL", "http://localhost:11434/v1")
LLM_API_KEY = os.environ.get("QC_AGENT_LLM_API_KEY", "ollama")  # unused by ollama, but required by the OpenAI client
LLM_MODEL = os.environ.get("QC_AGENT_LLM_MODEL", "qwen3.8:27b")
LLM_TEMPERATURE = float(os.environ.get("QC_AGENT_LLM_TEMPERATURE", "0.1"))

# The context window the agent asks Ollama for, per request.
#
# Stated rather than inherited. Ollama sizes a model's context from whatever
# OLLAMA_CONTEXT_LENGTH the *server* was started with, so the same code
# silently got 16k, 32k or 64k depending on how someone launched the service
# -- and the failure mode when it is too small is not an error but the
# silent truncation of the system prompt (measured in
# docs/MODEL_CONTEXT_BUDGET.md). Asking explicitly means the app gets the
# window it was designed against on any host, and a host that cannot
# provide it fails visibly instead of degrading.
LLM_NUM_CTX = int(os.environ.get("QC_AGENT_LLM_NUM_CTX", "32768"))

# How many of the most recent messages a turn carries. Trimming is
# mechanical -- a recent window plus a digest line built from AgentState --
# rather than an LLM-written summary: summarizing costs a whole extra model
# call per turn, and a summary is one more thing that can quietly invent a
# job id or a result that never existed.
LLM_HISTORY_WINDOW = int(os.environ.get("QC_AGENT_LLM_HISTORY_WINDOW", "40"))

# Embedding model, served the same way via Ollama's /api/embeddings.
OLLAMA_HOST = os.environ.get("QC_AGENT_OLLAMA_HOST", "http://localhost:11434")
EMBEDDING_MODEL = os.environ.get("QC_AGENT_EMBEDDING_MODEL", "nomic-embed-text")
# Every embedding call (search_knowledge_base, and the automatic manuals-KB
# lookup _kb_context_for_job runs on every submit_draft call) happens inside
# a graph turn while _graph_lock is held -- an
# unbounded HTTP client here would mean a stalled Ollama embedding request
# could hold that lock indefinitely, blocking every other conversation's
# chat turns and approvals. langchain_ollama's OllamaEmbeddings has no
# timeout by default, unlike the chat LLM client (see graph.py's
# `timeout=150` on ChatOpenAI).
OLLAMA_EMBEDDING_TIMEOUT = float(os.environ.get("QC_AGENT_OLLAMA_EMBEDDING_TIMEOUT", "30"))

# How often (seconds) to re-assert that LLM_MODEL stays resident in VRAM; 0
# disables the keep-warm loop entirely (see app/agent/model_warmer.py).
#
# Ollama unloads an idle model after ~5 minutes by default, and reloading
# this one measured 11.4s against 2.9s warm on the lab host -- paid by
# whoever sends the first message after a quiet spell.
#
# Re-asserted on an interval rather than set once at startup, because
# `keep_alive: -1` is not a reservation: on a shared Ollama another tenant
# loading a model can still evict ours, after which nothing would ever put
# it back.
#
# Deliberately NOT applied to EMBEDDING_MODEL -- nomic-embed-text cold-loads
# in 0.9s, which does not justify permanently holding its 323 MB.
MODEL_KEEPALIVE_INTERVAL = float(os.environ.get("QC_AGENT_MODEL_KEEPALIVE_INTERVAL", "60"))

# --- Quantum chemistry engines ----------------------------------------------
# ORCA and BAGEL are separately licensed and host-installed -- neither is
# bundled with this project, and the paths below are only plausible defaults.
# Set QC_AGENT_ORCA_BIN / QC_AGENT_BAGEL_BIN in your `.env` to wherever your
# site actually installed them (see .env.example).
ORCA_BIN = os.environ.get("QC_AGENT_ORCA_BIN", "/opt/orca/orca")
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
BAGEL_BIN = os.environ.get("QC_AGENT_BAGEL_BIN", "/opt/bagel/bin/BAGEL")
BAGEL_ONEAPI_SETVARS = os.environ.get(
    "QC_AGENT_BAGEL_SETVARS", "/opt/intel/oneapi/setvars.sh"
)
# On a bare-metal host, BAGEL's shared-library dependencies beyond MKL
# (Boost, ScaLAPACK, OpenBLAS -- typically site-installed alongside BAGEL
# itself rather than system packages) resolve because the host's own shell
# profile sets
# LD_LIBRARY_PATH to include them; confirmed directly by reading that
# variable in a real host shell. entrypoint.sh's oneAPI setvars.sh sourcing
# covers MKL/TBB/compiler but was never meant to (and doesn't) cover these
# -- a genuine, previously-undiscovered container gap, found by actually
# submitting a real BAGEL CASSCF job in the compose stack for the first
# time: the binary failed to even start with "cannot open shared object
# file" for libboost_serialization.so.1.87.0. Colon-separated, same format
# as LD_LIBRARY_PATH itself, since that's exactly what these get prepended
# to (see bagel_runner.py's _run_bagel) -- scoped to BAGEL's own subprocess
# only, not applied container-wide, mirroring JobManager._run_inner's
# identical engine-scoped LD_LIBRARY_PATH handling for pyscf/block2's MKL
# dependency (see that function's own comment for why a universal
# LD_LIBRARY_PATH override risks the wrong library being picked up by a
# DIFFERENT engine).
BAGEL_EXTRA_LIB_DIRS = os.environ.get(
    "QC_AGENT_BAGEL_EXTRA_LIB_DIRS",
    "/opt/boost/lib:/opt/scalapack/lib:/opt/openblas/lib",
)
MPIRUN_BIN = os.environ.get("QC_AGENT_MPIRUN_BIN", "/usr/bin/mpirun")

# --- Knowledge-base web scraping --------------------------------------------
# Sent as the User-Agent when fetching manual pages for the knowledge base
# (app/rag/web_scrape.py and scripts/seed_knowledge_base.py). Politeness
# convention: identify the crawler and give the operator a way to get in
# touch. Set QC_AGENT_SCRAPER_CONTACT to your own email or project URL if
# you run a crawl of any size -- some documentation hosts will ask.
SCRAPER_CONTACT = os.environ.get(
    "QC_AGENT_SCRAPER_CONTACT", "https://github.com/dakshitha-a/NexusQC"
)
SCRAPER_USER_AGENT = (
    f"Mozilla/5.0 (compatible; nexusqc-kb-ingest/1.0; +{SCRAPER_CONTACT})"
)

def total_system_cores() -> int:
    """Every logical core on the machine.

    This is the pool the app is allowed to draw on. NexusQC deliberately does
    NOT self-limit to some smaller subset: the whole machine is available, and
    JobManager's admission gate (see MAX_CPU_PERCENT below) is what keeps the
    host from being overwhelmed -- a load-based ceiling rather than a fixed
    core budget, so an idle machine gets used and a busy one does not.
    """
    try:
        return len(os.sched_getaffinity(0))
    except (AttributeError, OSError):
        return os.cpu_count() or 1


# Cores a SINGLE ORCA or BAGEL job requests (MPI ranks / OpenMP threads).
#
# This is per-job parallelism, not a budget for the app as a whole -- with
# MAX_CONCURRENT_JOBS jobs in flight the app may use N_CORES * that many cores,
# which is intended. Four is a deliberate default rather than an auto-detected
# one: most quantum chemistry jobs scale poorly past a handful of ranks, and a
# modest per-job width lets many jobs run at once instead of one wide job
# monopolising the machine.
#
# Auto-detection used to shell out to `nproc` here, and was removed. It was
# actively harmful in two directions: on a host whose shell profile sets
# OMP_NUM_THREADS, `nproc` reports that instead of anything about the machine;
# and inside a container, where no such variable exists, it reports every core
# on the host, which made the idle-core gate below wait for hundreds of
# simultaneously-idle cores and hang every job at `pending` forever, with no
# error and nothing in the UI to explain it. A fixed, explicit default cannot
# fail either way.
N_CORES = int(os.environ.get("QC_AGENT_N_CORES", "4"))

# How large N_CORES may get before it is treated as a misconfiguration
# rather than a big machine (F-005). See describe_n_cores() below.
N_CORES_SANITY_CEILING = int(os.environ.get("QC_AGENT_N_CORES_SANITY_CEILING", "64"))


def describe_n_cores() -> tuple[str, str]:
    """Returns (level, message) describing how N_CORES was resolved, for
    the server to log once at startup. level is "info" or "warning".

    N_CORES is how wide ONE job runs, and JobManager admits a job only once
    that many logical cores are individually idle. So an implausibly large
    value does not merely waste capacity -- it leaves every job PENDING
    FOREVER, with no error, no log line, and nothing in the UI to distinguish
    it from a genuinely busy host. That failure gives a debugger nothing to go
    on, which is why the resolved value is stated explicitly at startup.

    This does not clamp the value: a genuinely large per-job width is a real
    thing on the right hardware, and silently overriding an operator's explicit
    setting would be its own surprise. It makes the number visible, and says
    plainly what an implausible one will do.
    """
    source = "QC_AGENT_N_CORES" if "QC_AGENT_N_CORES" in os.environ else "default"
    total = total_system_cores()

    base = (
        f"N_CORES={N_CORES} cores per job (from {source}); "
        f"{total} logical cores available to this process; "
        f"up to {MAX_CONCURRENT_JOBS} concurrent jobs"
    )
    if N_CORES > N_CORES_SANITY_CEILING:
        return "warning", (
            f"{base}. This is above the plausible ceiling of "
            f"{N_CORES_SANITY_CEILING}. JobManager admits a job only once at least "
            f"N_CORES logical cores are individually idle, so a value this large "
            f"will leave every job PENDING FOREVER with no other symptom. Set "
            f"QC_AGENT_N_CORES to the number of cores one job should use "
            f"(docker-compose.yml passes it to the api service)."
        )
    return "info", base
MAX_MEMORY_MB = int(os.environ.get("QC_AGENT_MAX_MEMORY_MB", "8000"))  # per-job, PySCF convention

# Worker-pool size, fixed at process start (it sizes JobManager's
# ThreadPoolExecutor, which cannot be resized later). This is the hard ceiling
# the admin console's own editable "max concurrent jobs (total)" can never
# exceed. At the default N_CORES=4 this allows up to 80 cores' worth of work in
# flight; the host-load admission gate below, not this number, is what actually
# protects the machine.
MAX_CONCURRENT_JOBS = int(os.environ.get("QC_AGENT_MAX_CONCURRENT_JOBS", "20"))

# A master task's (pes_1d/interp_pes/wigner_spectra) sub-jobs are dispatched
# in throttled waves rather than all submitted at once: submitting hundreds
# of sub-job directories inside one blocking call would stress the
# quota/concurrency-scanning code at a scale it wasn't built for (see
# JobManager.submit_ensemble's docstring, which first documented this for
# wigner_spectra), and doing so also lets the fair scheduler (scheduler.py)
# interleave a single large master's sub-jobs with other users' work rather
# than flooding one user's own queue in a single burst. This caps how many
# of one master's sub-jobs may be pending/running at once -- scaled off
# MAX_CONCURRENT_JOBS by default rather than a fixed number, so it stays
# sensible across deployments with very different concurrency budgets.
# Named generically (not ENSEMBLE_MAX_IN_FLIGHT) because pes_1d/interp_pes
# trickle-dispatch the same way as of Phase 4 -- see scan_orchestrator.py.
MASTER_MAX_IN_FLIGHT = int(os.environ.get("QC_AGENT_MASTER_MAX_IN_FLIGHT", str(MAX_CONCURRENT_JOBS * 2)))

# Explicit CASSCF/CASPT2 convergence policy, applied identically across all
# three engines (pyscf's mc.conv_tol/max_cycle_macro, ORCA's %casscf
# ETol/MaxIter, BAGEL's casscf-block thresh/maxiter) rather than leaving each
# engine at its own differing default (pyscf 1e-7/50, ORCA 1e-8/75, BAGEL
# 1e-8/50). Energy-only CASSCF/CASPT2 jobs use the looser tolerance; any job
# involving a nuclear-coordinate derivative (geometry optimization or
# frequency) uses the tighter one, since a loose wavefunction convergence
# would otherwise show up as noise in the gradient/Hessian.
# How negative a harmonic frequency must be before it counts as a genuine
# imaginary mode rather than numerical noise (F-026).
#
# This lived as a private constant in bagel_runner.py while orca_runner.py,
# pyscf_runner.py and the frontend's VibrationTable.tsx each used a bare
# `f < 0` -- four places, three different rules, for the number that tells a
# chemist whether they have a minimum or a transition state. The same
# molecule at the same geometry could therefore be reported as a minimum on
# BAGEL and a saddle point on ORCA, and the drawer painted a -5.9 cm^-1
# noise mode in "imaginary" red directly above a summary line reading
# n_imaginary_frequencies: 0.
#
# A threshold is the correct rule, not a concession: a converged minimum's
# translational/rotational modes come out at small non-zero values of either
# sign, and every engine here leaves those 5-6 near-zero modes in its
# frequency list on purpose (so the two text-parsed engines stay index-
# aligned). 50 cm^-1 is BAGEL's own long-standing value, kept as the shared
# one rather than inventing a new number.
IMAGINARY_FREQ_THRESHOLD_CM1 = float(os.environ.get("QC_AGENT_IMAGINARY_FREQ_THRESHOLD_CM1", "50.0"))

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
# molecule_from_name (called from the set_geometry tool, which runs inside a
# graph turn holding _graph_lock -- submit_draft never resolves a name
# itself, see docs/ARCHITECTURE.md's "The approval gate") tries PubChemPy
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
# Empty entries are stripped rather than kept. The deployed stack sets this
# to "" deliberately (docker-compose.yml explains why: the dev origins must
# not stay in an allowlist that AccessControlMiddleware consults BEFORE its
# same-origin fallback). A bare "".split(",") yields [""], and the
# middleware's membership test is `origin not in self._allowed_origins` --
# so a request carrying a literal empty `Origin:` header would have matched
# and skipped the CSRF check entirely. A real browser never sends that, but
# the check exists precisely for requests that are not real browsers, so
# the empty string must not be a member. Stripping here fixes it for both
# consumers (CORSMiddleware and AccessControlMiddleware) at once.
SERVER_CORS_ORIGINS = [
    origin.strip()
    for origin in os.environ.get(
        "QC_AGENT_SERVER_CORS_ORIGINS",
        "http://localhost:5173,http://127.0.0.1:5173",
    ).split(",")
    if origin.strip()
]

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

# Rate limiting on /api/auth/login and /api/auth/register (app/auth/
# rate_limit.py) -- a fixed window per client IP (from nginx's X-Real-IP,
# see proxy_common.conf), backed by the same Redis instance as session
# enforcement above. Deliberately a 429 backoff, not an account lockout:
# this app has no password-reset flow and no admin "unlock account" action,
# so a lockout would have no recovery path short of an admin CLI/DB fix.
LOGIN_RATE_LIMIT_MAX_ATTEMPTS = int(os.environ.get("QC_AGENT_LOGIN_RATE_LIMIT_MAX_ATTEMPTS", "10"))
LOGIN_RATE_LIMIT_WINDOW_SECONDS = int(os.environ.get("QC_AGENT_LOGIN_RATE_LIMIT_WINDOW_SECONDS", "60"))
REGISTER_RATE_LIMIT_MAX_ATTEMPTS = int(os.environ.get("QC_AGENT_REGISTER_RATE_LIMIT_MAX_ATTEMPTS", "10"))
REGISTER_RATE_LIMIT_WINDOW_SECONDS = int(os.environ.get("QC_AGENT_REGISTER_RATE_LIMIT_WINDOW_SECONDS", "60"))

# --- Storage quotas & concurrency (app/auth/storage_quota.py) ---------------
# These are only meaningful once DATABASE_URL is set (a real "user" concept
# requires the ownership_index table) -- they're the fallback DEFAULT the
# admin console's GET/PATCH /api/admin/config seeds app_config with the
# first time it's read; from then on the admin-set Postgres value (if any)
# always wins over these. A local-dev/no-auth deployment never consults
# these at all -- app/chemistry/jobs/quota.py and app/rag/quota.py keep
# their own original flat, single-tenant 100GB/10GB caps in that case,
# since there's no per-user concept to split a quota across.
# Decimal (1000^3), not binary (1024^3) -- matches
# frontend/src/app-shell/StorageUsageBadge.tsx's own formatGB() convention
# (and the admin console's quota editor, which is also decimal), so a
# "2GB" default here actually displays as a clean "2.00 GB" rather than
# "2.15 GB". The two pre-existing flat caps this module's neighbors used
# before this feature (app/chemistry/jobs/quota.py's 100GB,
# app/rag/quota.py's 10GB) are binary (1024^3) and keep that PRE-EXISTING
# imprecision unchanged -- not touched here, since they're a separate,
# already-shipped local-dev-only code path this feature doesn't alter.
GB = 1_000_000_000
# Per-user split: 2GB for the caller's own KB uploads, 18GB combined across
# their own job artifact directories + their own chat/checkpoint history --
# one combined pool for the latter two (not 18GB each) since both are
# "conversation activity" from the same user, and splitting it further
# wasn't asked for.
DEFAULT_PER_USER_KB_QUOTA_BYTES = 2 * GB
DEFAULT_PER_USER_JOBS_AND_CHAT_QUOTA_BYTES = 18 * GB
# Uploaded geometry/blind-input files (Phase 3) are their own category, not
# folded into the jobs+chat pool above: they're pre-job raw input, small
# (xyz/inp/input/json text), and have their own independent lifecycle --
# list/delete/clear-all in the Files panel, entirely separate from whatever
# job an upload may or may not later be attached into. 512MB is generous for
# text input files; nothing here is expected to approach it under normal use.
DEFAULT_PER_USER_UPLOADS_QUOTA_BYTES = GB // 2
# One combined ceiling across every user's KB + job + chat + uploads storage
# at once (not a separate global cap per category) -- oldest content across
# all four categories and all users is evicted first when this is exceeded,
# even if no individual user is themselves over their own per-user cap.
DEFAULT_GLOBAL_STORAGE_QUOTA_BYTES = 200 * GB
# Concurrent RUNNING (not pending/queued) job caps, admin-editable via the
# same app_config mechanism. The total figure can only ever be an
# effective ceiling up to MAX_CONCURRENT_JOBS above -- that constant also
# sizes JobManager's ThreadPoolExecutor itself (fixed at process start,
# not resizable at runtime), so an admin-set total higher than it would
# have no effect; server/routes/admin.py clamps and explains this rather
# than silently accepting an unenforceable value.
DEFAULT_MAX_CONCURRENT_JOBS_PER_USER = 5
# usage_report() (GET /api/admin/storage) walks every job/KB/thread on disk
# and in Postgres fresh on every call -- fine at the near-empty volume this
# deployment started at (measured ~174ms), but confirmed to scale roughly
# linearly with job count: ~343ms at 1,000 seeded jobs, ~819ms median /
# up to ~2s at 5,000. A short TTL cache trades a bounded staleness window
# for cutting that off the hot path; explicitly invalidated (not just left
# to expire) on every purge/eviction and on any admin config PATCH, so an
# admin who just clicked "purge" or changed a quota sees the effect
# immediately rather than waiting out the TTL.
ADMIN_STORAGE_CACHE_TTL_SECONDS = int(os.environ.get("QC_AGENT_ADMIN_STORAGE_CACHE_TTL_SECONDS", "20"))
