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

import os
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware

from app.agent.graph import ApprovalCardOpen
from app.agent.job_watcher import get_job_watcher
from app.agent.model_warmer import get_model_warmer
from app.chemistry.jobs.batch_orchestrator import get_batch_orchestrator
from app.chemistry.jobs.ensemble_orchestrator import get_ensemble_orchestrator
from app.chemistry.jobs.scan_orchestrator import get_scan_orchestrator
from app.config import (
    DATABASE_URL,
    SERVER_CORS_ORIGINS,
    SERVER_HOST,
    SERVER_PORT,
    describe_n_cores,
)
from server.routes import chat, jobs, kb, plots, projects, registry, threads, uploads
from server.sse import hub

# Deliberately uvicorn's own logger rather than a fresh "qc_agent.*" one:
# uvicorn configures that logger with a handler at INFO, while a new logger
# would propagate to a root that is unconfigured at WARNING by default --
# so an INFO startup line on it would be silently dropped, which is the
# exact failure mode the line below exists to prevent.
_log = logging.getLogger("uvicorn.error")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # F-005: make the resolved N_CORES visible at startup. A wrong value
    # here has no other symptom than every job sitting `pending` forever
    # (JobManager._wait_for_resources waits for N_CORES individually idle
    # cores, and 255 of them never are), which is indistinguishable from a
    # busy host and cost a long debugging session to track down once.
    _level, _msg = describe_n_cores()
    (_log.warning if _level == "warning" else _log.info)("%s", _msg)

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
    # Same role again, for `batch` masters (P7.4) -- wave-dispatches each
    # batch's per-geometry children and rolls their status up into the
    # master's own result.json (see batch_orchestrator.py's module
    # docstring).
    batch_orchestrator = get_batch_orchestrator()
    batch_orchestrator.start()
    # Holds the chat model in VRAM so the first message after an idle spell
    # doesn't pay Ollama's ~5-minute-idle eviction (11.4s vs 2.9s warm on
    # the lab host). Deliberately started last and never awaited: it is a
    # latency optimisation, and a missing or unreachable Ollama must not
    # stop the backend coming up. See app/agent/model_warmer.py.
    model_warmer = get_model_warmer()
    model_warmer.start()
    try:
        yield
    finally:
        watcher.stop()
        scan_orchestrator.stop()
        ensemble_orchestrator.stop()
        batch_orchestrator.stop()
        model_warmer.stop()


app = FastAPI(title="NexusQC API", lifespan=lifespan)

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
app.include_router(uploads.router)
app.include_router(plots.router)
app.include_router(projects.router)
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
    from server.routes import admin, auth, bugs, shares

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
    app.include_router(shares.router)


@app.exception_handler(ApprovalCardOpen)
def _approval_card_open(request: Request, exc: ApprovalCardOpen):
    """409, not 500, and with the reason.

    R-017: five molecule-panel actions and the attach-a-file path wrote graph
    state directly, and `update_state` discards a pending `interrupt()`, so
    any of them pressed while an approval card was open destroyed the
    approval and said nothing. They refuse now. This turns that refusal into
    something the frontend can show, rather than an unhandled exception.
    """
    return JSONResponse({"detail": str(exc)}, status_code=409)


@app.get("/api/health")
def health():
    """Liveness. Deliberately cheap: the compose healthcheck polls this every
    few seconds and nginx's `depends_on: service_healthy` waits on it, so it
    must not touch a database, and a slow dependency must not make the
    container look dead.

    It is genuinely only liveness, which is the point of the route below."""
    return {"status": "ok"}


@app.get("/api/health/deep")
def health_deep(response: Response):
    """Readiness: can this deployment actually serve a logged-in request?

    R-058. `update.sh` used `/api/health` to decide whether an update
    succeeded, whether to record the commit as good and rollback-able, and
    what to tell the operator. That route proves the interpreter finished
    importing and nothing else, so a wrong `QC_AGENT_POSTGRES_PASSWORD` in the
    api's own connection string produced a deployment that reported healthy,
    started nginx, and failed every single login. The postgres container's own
    healthcheck is `pg_isready`, which does not authenticate, so it agreed.

    Each dependency is reported separately rather than collapsed into one
    boolean, because "Postgres is unreachable" and "Redis is unreachable" need
    different things done about them. 503 when any configured dependency is
    down, so a caller can use the status code alone.

    Unauthenticated, like the two routes around it: it has to answer while the
    deployment is in exactly the state that makes authentication impossible.
    It reports reachability, never credentials, connection strings or
    versions.
    """
    checks: dict[str, str] = {"api": "ok"}
    # Both are gated on DATABASE_URL, which is what switches this app into
    # multi-user mode. A local-dev deployment has neither and is not degraded
    # for not having them; startup already refuses to run with a database and
    # no Redis, so inside this branch both are genuinely required.
    if DATABASE_URL:
        try:
            from app.auth.db import get_pool
            with get_pool().connection() as conn:
                conn.execute("SELECT 1").fetchone()
            checks["database"] = "ok"
        except Exception as exc:
            checks["database"] = f"unreachable: {type(exc).__name__}"
        try:
            from app.auth.redis_session import get_client
            get_client().ping()
            checks["redis"] = "ok"
        except Exception as exc:
            checks["redis"] = f"unreachable: {type(exc).__name__}"
    ok = all(v == "ok" for v in checks.values())
    if not ok:
        response.status_code = 503
    return {"status": "ok" if ok else "degraded", "checks": checks}


@app.get("/api/version")
def version():
    """What this process was built from.

    Unauthenticated and outside the `if DATABASE_URL:` block above, for the
    same reason /api/health is: it has to answer while the deployment is in
    maintenance or has no auth layer at all, and it says nothing a visitor
    could not read off the public repository.

    The commit reaches the process as an environment variable set in the
    Dockerfile from the GIT_COMMIT build arg. The OCI label carries the same
    value, but a label is only legible to `docker inspect` from the host --
    the process inside cannot read its own. `unknown` is honest and is what a
    hand-run `docker compose build` with no stamp produces; callers read it as
    "cannot tell", never as up to date.
    """
    return {"commit": os.environ.get("QC_AGENT_BUILD_COMMIT") or "unknown"}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("server.main:app", host=SERVER_HOST, port=SERVER_PORT, reload=False)
