"""FastAPI server exposing app/'s LangGraph agent, job manager, RAG store,
and dynamic tools to the React frontend (frontend/).

Every route that touches the graph (app/agent/graph.py) is a plain `def`,
never `async def`. FastAPI runs sync handlers in a worker threadpool, and
the graph is already fully synchronous and serialized behind its own
`_graph_lock` -- `async def` here would buy nothing and risks blocking the
single asyncio event loop (including SSE delivery to every other open
connection) behind one slow `_graph_lock.acquire()` if a handler were ever
written to await something while holding it.

Run directly: `python -m server.main` (binds to localhost only -- this is a
single-user, local-only app, not multi-tenant; see app/config.py's
SERVER_CORS_ORIGINS for the one place a browser origin needs to be listed
at all).
"""
from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.agent.job_watcher import get_job_watcher
from app.config import SERVER_CORS_ORIGINS
from server.routes import chat, jobs, kb, registry, threads, tools
from server.sse import hub


@asynccontextmanager
async def lifespan(app: FastAPI):
    watcher = get_job_watcher(on_event=hub.publish)
    watcher.start()
    try:
        yield
    finally:
        watcher.stop()


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
app.include_router(tools.router)
app.include_router(registry.router)


@app.get("/api/health")
def health():
    return {"status": "ok"}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("server.main:app", host="127.0.0.1", port=8000, reload=False)
