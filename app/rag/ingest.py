"""Ingestion pipeline: file (PDF or plain text) -> chunks -> embedded and
added to the persistent Chroma store. Used by the KB upload endpoint
(`server/routes/kb.py`) so the user can grow the knowledge base without
touching the filesystem.
"""
from __future__ import annotations

import hashlib
import time
from pathlib import Path

from langchain_text_splitters import RecursiveCharacterTextSplitter
from pypdf import PdfReader

from app.rag.store import get_store

_SPLITTER = RecursiveCharacterTextSplitter(chunk_size=1500, chunk_overlap=200)


def _extract_text(path: Path) -> str:
    if path.suffix.lower() == ".pdf":
        reader = PdfReader(str(path))
        return "\n\n".join(page.extract_text() or "" for page in reader.pages)
    return path.read_text(errors="ignore")


def ingest_text(text: str, filename: str, doc_type: str) -> int:
    """doc_type: 'manual' or 'paper'. `filename` is the source identity
    chunk ids are keyed on (see below) -- callers without a natural
    filename (dropped/pasted text, a scholar-search result) must
    synthesize a collision-safe one themselves before calling this, since
    re-using an existing filename here overwrites that source's chunks
    rather than adding a new one. Returns the number of chunks added."""
    assert doc_type in ("manual", "paper")
    if not text.strip():
        raise ValueError(f"No extractable text found in {filename}")

    chunks = _SPLITTER.split_text(text)
    # Deterministic per-(filename, chunk_index) ids: re-ingesting the same
    # filename overwrites its old chunks in place rather than duplicating
    # them -- relied on by the KB upload UI's "replace by re-uploading"
    # behavior, so this must stay a pure function of (filename, i).
    ids = [hashlib.sha1(f"{filename}:{i}".encode()).hexdigest() for i in range(len(chunks))]
    # ingested_at powers list_sources' most-recent-first ordering in the KB
    # sidebar -- a single wall-clock read shared by every chunk of this
    # source, not per-chunk, so a multi-chunk document sorts as one unit.
    ingested_at = time.time()
    metadatas = [
        {"source": filename, "doc_type": doc_type, "chunk_index": i, "ingested_at": ingested_at}
        for i in range(len(chunks))
    ]

    store = get_store()
    store.add_texts(texts=chunks, metadatas=metadatas, ids=ids)
    return len(chunks)


def ingest_file(path: Path, doc_type: str) -> int:
    """doc_type: 'manual' or 'paper'. Returns the number of chunks added."""
    text = _extract_text(path)
    return ingest_text(text, path.name, doc_type)
