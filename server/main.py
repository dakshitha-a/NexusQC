"""FastAPI server exposing app/'s LangGraph agent, job manager, and RAG
store to the React frontend (frontend/).

Every route that touches the graph (app/agent/graph.py) is a plain `def`,
never `async def`. FastAPI runs sync handlers in a worker threadpool, and
the graph is already fully synchronous and serialized behind its own
`_graph_lock` -- `async def` here would buy nothing and risks blocking the
single asyncio event loop (including SSE delivery to every other open
connection) behind one slow `_graph_lock.acquire()` if a handler were ever
written to await something while holding it.

Run directly: `python -m server.main`. Binds to app/config.py's SERVER_HOST/
SERVER_PORT (QC_AGENT_SERVER_HOST/QC_AGENT_SERVER_PORT) -- localhost by
default for the local dev workflow, 0.0.0.0 inside the container image (see
Dockerfile/docker-compose.yml), where nginx is the only process actually
exposed to the host network. See app/config.py's SERVER_CORS_ORIGINS for the
one place a browser origin needs to be listed at all.
"""
from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.agent.job_watcher import get_job_watcher
from app.chemistry.jobs.ensemble_orchestrator import get_ensemble_orchestrator
from app.chemistry.jobs.scan_orchestrator import get_scan_orchestrator
from app.config import DATABASE_URL, SERVER_CORS_ORIGINS, SERVER_HOST, SERVER_PORT
from server.routes import chat, jobs, kb, registry, threads
from server.sse import hub


@asynccontextmanager
async def lifespan(app: FastAPI):
    watcher = get_job_watcher(on_event=hub.publish)
    watcher.start()
    # Aggregates pes_scan master jobs' sub-jobs back into the master's own
    # result.json -- a separate background loop from job_watcher (see
    # scan_orchestrator.py's module docstring for why), so it's started
    # independently here rather than folded into the call above.
    scan_orchestrator = get_scan_orchestrator()
    scan_orchestrator.start()
    # Same role as scan_orchestrator, for wigner_ensemble masters -- also
    # wave-dispatches each ensemble's per-sample sub-jobs (see
    # ensemble_orchestrator.py's module docstring), not just aggregation.
    ensemble_orchestrator = get_ensemble_orchestrator()
    ensemble_orchestrator.start()
    try:
        yield
    finally:
        watcher.stop()
        scan_orchestrator.stop()
        ensemble_orchestrator.stop()


app = FastAPI(title="Computational Chemistry Agent API", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=SERVER_CORS_ORIGINS,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(threads.router)
app.include_router(chat.router)
app.include_router(jobs.router)
app.include_router(kb.router)
app.include_router(registry.router)

# Auth/admin routes -- and the access-control middleware they depend on --
# are only wired in when QC_AGENT_DATABASE_URL is set. Auth is meaningless
# without the Postgres identity tables (app/auth/db.py), and this keeps the
# local-dev workflow (`python -m server.main`, no Postgres/Redis running)
# working exactly as it always has: no auth routes exposed, no middleware
# that would 401/403 a request with no way to ever log in.
if DATABASE_URL:
    from app.auth.middleware import AccessControlMiddleware
    from app.config import JWT_SECRET, REDIS_URL
    from server.routes import admin, auth, bugs

    # Fail at import time (server startup), not lazily on the first login
    # attempt -- app/auth/security.py's own _require_secret() already
    # refuses to sign/verify a token with an empty JWT_SECRET, but that
    # only fires the first time someone actually tries to log in, which is
    # a much worse deployment experience than the container refusing to
    # start at all with a clear message.
    if not JWT_SECRET:
        raise RuntimeError(
            "QC_AGENT_DATABASE_URL is set (auth is active) but QC_AGENT_JWT_SECRET is not -- "
            "refusing to start. Set QC_AGENT_JWT_SECRET (at least 32 random bytes) before running."
        )
    if not REDIS_URL:
        raise RuntimeError(
            "QC_AGENT_DATABASE_URL is set (auth is active) but QC_AGENT_REDIS_URL is not -- "
            "refusing to start. One-session-per-user enforcement requires Redis; set QC_AGENT_REDIS_URL."
        )

    app.add_middleware(AccessControlMiddleware, allowed_origins=SERVER_CORS_ORIGINS)
    app.include_router(auth.router)
    app.include_router(admin.router)
    app.include_router(bugs.router)


@app.get("/api/health")
def health():
    return {"status": "ok"}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("server.main:app", host=SERVER_HOST, port=SERVER_PORT, reload=False)
