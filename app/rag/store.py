"""Persistent Chroma vector store, embedded locally via Ollama.

One collection holds everything (software manuals + scientific papers);
documents carry a `doc_type` metadata field ("manual" | "paper") and a
`source` filename so results can be filtered or attributed.
"""
from __future__ import annotations

from langchain_chroma import Chroma
from langchain_ollama import OllamaEmbeddings

from app.config import EMBEDDING_MODEL, KB_DIR, OLLAMA_HOST

COLLECTION_NAME = "qc_knowledge_base"

_store: Chroma | None = None


def get_embeddings() -> OllamaEmbeddings:
    return OllamaEmbeddings(model=EMBEDDING_MODEL, base_url=OLLAMA_HOST)


def get_store() -> Chroma:
    global _store
    if _store is None:
        _store = Chroma(
            collection_name=COLLECTION_NAME,
            embedding_function=get_embeddings(),
            persist_directory=str(KB_DIR),
        )
    return _store


def list_sources() -> list[dict]:
    """Distinct documents currently in the KB, with chunk counts, for the
    UI's manage-KB panel -- ordered most-recently-ingested first so a
    freshly-added source doesn't get lost alphabetically among a large
    pre-seeded manual set. Chunks ingested before `ingested_at` existed
    default to 0.0, so they naturally sort to the bottom rather than
    erroring."""
    store = get_store()
    data = store.get(include=["metadatas"])
    counts: dict[tuple[str, str], int] = {}
    latest: dict[tuple[str, str], float] = {}
    for md in data["metadatas"]:
        key = (md.get("source", "unknown"), md.get("doc_type", "unknown"))
        counts[key] = counts.get(key, 0) + 1
        ts = md.get("ingested_at", 0.0)
        latest[key] = max(latest.get(key, 0.0), ts)
    ordered = sorted(counts.items(), key=lambda item: latest[item[0]], reverse=True)
    return [{"source": src, "doc_type": dt, "n_chunks": n} for (src, dt), n in ordered]


def delete_source(source: str) -> int:
    store = get_store()
    data = store.get(where={"source": source}, include=[])
    ids = data["ids"]
    if ids:
        store.delete(ids=ids)
    return len(ids)
