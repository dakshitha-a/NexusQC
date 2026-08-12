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
DYNAMIC_TOOLS_DIR = DATA_DIR / "dynamic_tools"

for _d in (DATA_DIR, JOBS_DIR, KB_DIR, UPLOADS_DIR, MOLECULES_DIR, DYNAMIC_TOOLS_DIR):
    _d.mkdir(parents=True, exist_ok=True)

# --- LLM (OpenAI-compatible endpoint served by Ollama) ----------------------
LLM_BASE_URL = os.environ.get("QC_AGENT_LLM_BASE_URL", "http://localhost:11434/v1")
LLM_API_KEY = os.environ.get("QC_AGENT_LLM_API_KEY", "ollama")  # unused by ollama, but required by the OpenAI client
LLM_MODEL = os.environ.get("QC_AGENT_LLM_MODEL", "qwen3:30b")
LLM_TEMPERATURE = float(os.environ.get("QC_AGENT_LLM_TEMPERATURE", "0.1"))

# Embedding model, served the same way via Ollama's /api/embeddings.
OLLAMA_HOST = os.environ.get("QC_AGENT_OLLAMA_HOST", "http://localhost:11434")
EMBEDDING_MODEL = os.environ.get("QC_AGENT_EMBEDDING_MODEL", "nomic-embed-text")

# --- Quantum chemistry engines ----------------------------------------------
ORCA_BIN = os.environ.get("QC_AGENT_ORCA_BIN", "/opt/Orca-6.1.1/orca")
BAGEL_BIN = os.environ.get("QC_AGENT_BAGEL_BIN", "/opt/bagel-1.2.2/bin/BAGEL")
BAGEL_ONEAPI_SETVARS = os.environ.get(
    "QC_AGENT_BAGEL_SETVARS", "/opt/intel/oneapi/setvars.sh"
)
MPIRUN_BIN = os.environ.get("QC_AGENT_MPIRUN_BIN", "/usr/bin/mpirun")

def _detect_usable_cores() -> int:
    """`os.cpu_count()`/`os.sched_getaffinity` report the *host's* CPU count
    in this container (255!), ignoring the cgroup quota actually granted to
    it -- using that to size MPI/OpenMP parallelism causes ORCA/BAGEL to
    request far more ranks/threads than exist, which manifests as
    intermittent, hard-to-diagnose MPI crashes. `nproc` (coreutils) reads
    the cgroup quota correctly, so shell out to it instead."""
    try:
        import subprocess
        return int(subprocess.run(["nproc"], capture_output=True, text=True, timeout=5).stdout.strip())
    except Exception:
        return min(os.cpu_count() or 4, 8)


N_CORES = int(os.environ.get("QC_AGENT_N_CORES", str(_detect_usable_cores())))
MAX_MEMORY_MB = int(os.environ.get("QC_AGENT_MAX_MEMORY_MB", "8000"))  # per-job, PySCF convention

MAX_CONCURRENT_JOBS = int(os.environ.get("QC_AGENT_MAX_CONCURRENT_JOBS", "4"))
