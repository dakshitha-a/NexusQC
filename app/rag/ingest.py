"""Ingestion pipeline: file (PDF or plain text) -> chunks -> embedded and
added to the persistent Chroma store. Used by the KB upload endpoint
(`server/routes/kb.py`) so the user can grow the knowledge base without
touching the filesystem.
"""
from __future__ import annotations

import hashlib
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


def ingest_file(path: Path, doc_type: str) -> int:
    """doc_type: 'manual' or 'paper'. Returns the number of chunks added."""
    assert doc_type in ("manual", "paper")
    text = _extract_text(path)
    if not text.strip():
        raise ValueError(f"No extractable text found in {path.name}")

    chunks = _SPLITTER.split_text(text)
    ids = [hashlib.sha1(f"{path.name}:{i}".encode()).hexdigest() for i in range(len(chunks))]
    metadatas = [{"source": path.name, "doc_type": doc_type, "chunk_index": i} for i in range(len(chunks))]

    store = get_store()
    store.add_texts(texts=chunks, metadatas=metadatas, ids=ids)
    return len(chunks)
