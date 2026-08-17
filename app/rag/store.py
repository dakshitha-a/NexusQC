"""Persistent Chroma vector store, embedded locally via Ollama.

One collection holds everything (software manuals + scientific papers);
documents carry a `doc_type` metadata field ("manual" | "paper"), a
`source` filename so results can be filtered or attributed, and (since the
multi-user ownership retrofit) an `owner` field: `SHARED_OWNER` for the
pre-seeded manuals (scripts/seed_knowledge_base.py) and anything an admin
marks shared, or a user id string for anything a specific user uploaded.
See list_sources/delete_source below for how that's enforced, and
app/rag/ingest.py for how `source` itself gets a per-owner-unique value.
"""
from __future__ import annotations

import threading
from pathlib import Path
from typing import Optional

from langchain_chroma import Chroma
from langchain_ollama import OllamaEmbeddings

from app.config import EMBEDDING_MODEL, KB_DIR, OLLAMA_EMBEDDING_TIMEOUT, OLLAMA_HOST, UPLOADS_DIR

COLLECTION_NAME = "qc_knowledge_base"

# Sentinel `owner` metadata value for content nobody-in-particular owns --
# the pre-seeded manuals under data/scraped/ (ingested with no owner
# passed at all, before this field existed) and anything explicitly shared.
# Chosen to look nothing like a real UUID user id, so it can never
# collide with one.
SHARED_OWNER = "__shared__"

_store: Chroma | None = None
# Guards _store's lazy construction below -- FastAPI dispatches sync `def`
# routes onto a worker threadpool (see server/main.py's module docstring),
# so a cold backend's first few concurrent requests that each touch the KB
# (e.g. the admin console's own burst of first-load queries: KB source
# list, KB quota, plus whatever else is on screen) can call get_store()
# concurrently before _store is set. Confirmed as a real, reproducible bug
# this way, not a hypothetical: chromadb's own PersistentClient/
# SharedSystemClient bookkeeping is not itself safe against two threads
# racing to construct a client for the same persist_directory at once --
# one thread's read of its internal identifier registry can land between
# another thread's check-and-populate of the same entry, raising a bare
# KeyError out of chromadb's own code. Double-checked locking (the same
# pattern app/auth/db.py's get_pool() already uses for its own lazy
# module-global) avoids paying lock-acquisition cost on every call once
# _store is warm, while still serializing the one-time construction.
_store_lock = threading.Lock()


def get_embeddings() -> OllamaEmbeddings:
    # client_kwargs is passed straight through to the underlying
    # ollama.Client's httpx.Client -- with no timeout set here, a stalled
    # Ollama embedding request could hang forever while this call runs
    # inside a graph turn holding _graph_lock (see OLLAMA_EMBEDDING_TIMEOUT's
    # comment in config.py).
    return OllamaEmbeddings(
        model=EMBEDDING_MODEL, base_url=OLLAMA_HOST, client_kwargs={"timeout": OLLAMA_EMBEDDING_TIMEOUT},
    )


def get_store() -> Chroma:
    global _store
    if _store is None:
        with _store_lock:
            if _store is None:
                store = Chroma(
                    collection_name=COLLECTION_NAME,
                    embedding_function=get_embeddings(),
                    persist_directory=str(KB_DIR),
                )
                _backfill_shared_owner(store)
                _store = store
    return _store


def _backfill_shared_owner(store: Chroma) -> None:
    """One-time, idempotent migration: every chunk ingested before the
    ownership retrofit (every pre-seeded manual under data/scraped/, plus
    any KB content uploaded on a deployment before this code shipped) has
    no `owner` metadata key at all. A Chroma `where` filter on an
    equality match (used by search_knowledge_base/_kb_context_for_job's
    retrieval-time filtering, which genuinely needs a native `where`
    clause -- similarity search can't be meaningfully post-filtered in
    Python the way list_sources/delete_source below are) would silently
    exclude every one of those chunks from every authenticated user's
    retrieval results, since a missing key never satisfies an equality
    filter. Runs once per process (get_store()'s _store cache means this
    fires once per backend startup, not per call) and is cheap to no-op on
    a deployment where it's already run: only chunks actually missing the
    key are touched, via a raw metadata-only update (Chroma's own
    Collection.update, not the langchain wrapper's update_documents, which
    would need reconstructing full Document objects just to patch one
    field)."""
    data = store.get(include=["metadatas"])
    ids, metadatas = data["ids"], data["metadatas"]
    missing = [(i, md) for i, md in zip(ids, metadatas) if "owner" not in md]
    if not missing:
        return
    patched_ids = [i for i, _ in missing]
    patched_metadatas = [{**md, "owner": SHARED_OWNER} for _, md in missing]
    store._collection.update(ids=patched_ids, metadatas=patched_metadatas)


def _owner_where(owner_filter: Optional[str]) -> Optional[dict]:
    """None means "no filter, see everything" (auth not configured for
    this deployment, or the caller is an admin) -- callers pass None in
    exactly those two cases, never for an ordinary authenticated user.
    Otherwise: shared content plus this specific owner's own content."""
    if owner_filter is None:
        return None
    return {"$or": [{"owner": SHARED_OWNER}, {"owner": owner_filter}]}


def list_sources(owner_filter: Optional[str] = None) -> list[dict]:
    """Distinct documents currently in the KB, with chunk counts, for the
    UI's manage-KB panel -- ordered most-recently-ingested first so a
    freshly-added source doesn't get lost alphabetically among a large
    pre-seeded manual set. Chunks ingested before `ingested_at` existed
    default to 0.0, so they naturally sort to the bottom rather than
    erroring.

    Before the ownership retrofit this had NO filtering at all -- any
    caller could see every other user's uploaded filenames, a real
    cross-user information leak once multiple users share one deployment.
    owner_filter=None preserves that original unfiltered behavior for a
    single-user/no-auth deployment or an admin caller; every other caller
    passes their own user id and sees only shared sources plus their own.

    Grouped by (source, doc_type, owner), not just (source, doc_type) --
    two different users' identically-named uploads are disjoint documents
    under the hood (see ingest.py's chunk-id docstring) and must never be
    merged into one misleading row with a combined chunk count. `owner` is
    included in each returned dict (SHARED_OWNER for shared/pre-seeded
    content) so callers like app/rag/quota.py's eviction loop can locate
    the right per-owner upload subdirectory without a second lookup."""
    store = get_store()
    where = _owner_where(owner_filter)
    data = store.get(where=where, include=["metadatas"]) if where else store.get(include=["metadatas"])
    counts: dict[tuple[str, str, str], int] = {}
    latest: dict[tuple[str, str, str], float] = {}
    for md in data["metadatas"]:
        key = (md.get("source", "unknown"), md.get("doc_type", "unknown"), md.get("owner", SHARED_OWNER))
        counts[key] = counts.get(key, 0) + 1
        ts = md.get("ingested_at", 0.0)
        latest[key] = max(latest.get(key, 0.0), ts)
    ordered = sorted(counts.items(), key=lambda item: latest[item[0]], reverse=True)
    # ingested_at is included so callers doing oldest-first eviction
    # (app/rag/quota.py, app/auth/storage_quota.py) don't need a second
    # store.get() just to recover the same timestamp already computed above.
    return [
        {"source": src, "doc_type": dt, "owner": owner, "n_chunks": n, "ingested_at": latest[(src, dt, owner)]}
        for (src, dt, owner), n in ordered
    ]


def delete_source(source: str, owner_filter: Optional[str] = None) -> int:
    """owner_filter=None (auth not configured, or an admin caller) deletes
    every chunk under this source name unconditionally -- the original,
    pre-ownership behavior, and also how an admin clears a shared/
    pre-seeded source. Otherwise: deletes only the chunks under this
    source name that owner_filter itself owns -- ingest_text's chunk ids
    are already a function of (owner, filename, i) (see its own
    docstring), so two different users' identically-named sources are
    disjoint id sets under the hood despite sharing a display name here;
    scoping by BOTH source and owner means an ordinary user's delete
    request can never touch a shared source or another user's
    identically-named one, without needing to compare counts or fetch
    metadata first. Returns 0 (same as "source doesn't exist") on both an
    unknown source and one this caller doesn't own -- the route layer maps
    0 to a 404 either way, avoiding confirming to a caller that a source
    they can't touch does in fact exist under someone else's ownership."""
    store = get_store()
    # This installed Chroma version rejects a flat multi-key `where` dict
    # outright ("Expected where to have exactly one operator") -- confirmed
    # empirically, not assumed; requires an explicit $and for more than one
    # condition, same gotcha CLAUDE.md's KB-filtering notes already flag.
    where = {"source": source} if owner_filter is None else {"$and": [{"source": source}, {"owner": owner_filter}]}
    data = store.get(where=where, include=[])
    ids = data["ids"]
    if ids:
        store.delete(ids=ids)
    return len(ids)


def upload_path(source: str, owner: Optional[str]) -> "Path":
    """Where an ingested source's ORIGINAL uploaded file lives on disk.

    Two layouts, both pre-existing: UPLOADS_DIR/<owner>/<name> for an
    owned upload, and flat UPLOADS_DIR/<name> for a shared/no-auth one
    (owner is None or SHARED_OWNER). Centralised here because four call
    sites were independently reconstructing it -- server/routes/kb.py,
    app/rag/quota.py, and app/auth/storage_quota.py twice -- and the
    delete path was the one that had reconstructed nothing at all
    (F-001).
    """
    name = Path(source).name  # never let a source name escape UPLOADS_DIR
    if owner in (None, SHARED_OWNER):
        return UPLOADS_DIR / name
    return UPLOADS_DIR / owner / name


def delete_upload_file(source: str, owner: Optional[str]) -> bool:
    """Removes the original uploaded file backing `source`, pruning the
    owner's directory if that leaves it empty. Returns True if a file was
    actually removed.

    F-001 fix. `delete_source` above removes a source's chunks from
    Chroma but never touched the file the chunks were derived from, so
    every KB delete leaked the full original upload -- and the leak
    compounded, because both `_kb_candidates` and `_kb_usage_by_owner`
    enumerate KB content FROM Chroma. Once the vector entries were gone
    the file was invisible to every cleanup path there is, including
    quota eviction and account deletion: it could never be reclaimed,
    only found by hand. Callers should treat this as part of deleting a
    source, not an optional extra.
    """
    path = upload_path(source, owner)
    removed = False
    try:
        path.unlink()
        removed = True
    except OSError:
        pass
    # Prune the now-empty per-owner directory. These accumulated even on
    # the delete path that already worked, since nothing ever removed one.
    parent = path.parent
    if parent != UPLOADS_DIR:
        try:
            parent.rmdir()  # refuses on a non-empty directory, which is what we want
        except OSError:
            pass
    return removed


def orphaned_upload_files(owner: str) -> list["Path"]:
    """Files under this owner's upload directory with no surviving Chroma
    entry -- i.e. pre-existing orphans left behind by the F-001 leak
    before it was fixed, which no Chroma-derived enumeration can see.

    Used by purge_user_data so deleting an account reclaims them too,
    rather than leaving them stranded forever under a directory named for
    a user who no longer exists.
    """
    d = UPLOADS_DIR / owner
    if not d.is_dir():
        return []
    known = {s["source"] for s in list_sources(owner_filter=owner) if s["owner"] == owner}
    return [p for p in d.iterdir() if p.is_file() and p.name not in known]
