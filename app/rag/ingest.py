"""Ingestion pipeline: file (PDF or plain text) -> chunks -> embedded and
added to the persistent Chroma store. Used by the KB upload endpoint
(`server/routes/kb.py`) so the user can grow the knowledge base without
touching the filesystem.
"""
from __future__ import annotations

import hashlib
import time
from pathlib import Path

from typing import Optional

from docx import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter
from pypdf import PdfReader

from app.rag.store import SHARED_OWNER, get_store

_SPLITTER = RecursiveCharacterTextSplitter(chunk_size=1500, chunk_overlap=200)

# The only file types the KB accepts -- enforced here (not just the file
# picker's `accept` attribute, which a user can bypass by dragging any file
# in, or a drag-and-drop of an arbitrary file type) and again in
# server/routes/kb.py before the upload is even written to disk.
ALLOWED_FILE_EXTENSIONS = {".pdf", ".txt", ".md", ".docx"}


def _extract_text(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix not in ALLOWED_FILE_EXTENSIONS:
        raise ValueError(
            f"Unsupported file type '{suffix}' -- only PDF, TXT, MD, and DOCX files are accepted"
        )
    if suffix == ".pdf":
        reader = PdfReader(str(path))
        return "\n\n".join(page.extract_text() or "" for page in reader.pages)
    if suffix == ".docx":
        doc = Document(str(path))
        return "\n\n".join(p.text for p in doc.paragraphs if p.text.strip())
    return path.read_text(errors="ignore")


def ingest_text(text: str, filename: str, doc_type: str, owner: Optional[str] = None) -> int:
    """doc_type: 'manual' or 'paper'. `filename` is the source identity
    chunk ids are keyed on (see below) -- callers without a natural
    filename (dropped/pasted text, a scholar-search result) must
    synthesize a collision-safe one themselves before calling this, since
    re-using an existing filename here overwrites that source's chunks
    rather than adding a new one. Returns the number of chunks added.

    `owner`: None means shared (the pre-seeded manuals via
    scripts/seed_knowledge_base.py, which never pass this, and anything an
    admin explicitly marks shared) -- stored as store.py's SHARED_OWNER
    sentinel, not a literal None, so app/auth/ownership-style Chroma `where`
    filters can match on it directly. A real user id scopes this source to
    that user (see server/routes/kb.py). Chunk ids are a function of
    (owner, filename, i), not just (filename, i) -- two different users
    uploading identically-named files must never overwrite each other's
    embedded chunks the way they would if ids collided; store.py's
    list_sources/delete_source group and filter by owner alongside source
    for the same reason, keeping the displayed `source` value itself as
    the plain filename (no owner prefix baked into it) so the KB sidebar
    still shows a normal-looking filename regardless of who uploaded it."""
    assert doc_type in ("manual", "paper")
    if not text.strip():
        raise ValueError(f"No extractable text found in {filename}")

    owner_key = owner or SHARED_OWNER
    chunks = _SPLITTER.split_text(text)
    # Deterministic per-(owner, filename, chunk_index) ids: re-ingesting the
    # same (owner, filename) pair overwrites its old chunks in place rather
    # than duplicating them -- relied on by the KB upload UI's "replace by
    # re-uploading" behavior, so this must stay a pure function of those
    # three values. A DIFFERENT owner uploading the same filename gets a
    # disjoint id set (no collision, no accidental overwrite of someone
    # else's document).
    ids = [hashlib.sha1(f"{owner_key}:{filename}:{i}".encode()).hexdigest() for i in range(len(chunks))]
    # ingested_at powers list_sources' most-recent-first ordering in the KB
    # sidebar -- a single wall-clock read shared by every chunk of this
    # source, not per-chunk, so a multi-chunk document sorts as one unit.
    ingested_at = time.time()
    metadatas = [
        {"source": filename, "doc_type": doc_type, "owner": owner_key, "chunk_index": i, "ingested_at": ingested_at}
        for i in range(len(chunks))
    ]

    store = get_store()
    store.add_texts(texts=chunks, metadatas=metadatas, ids=ids)
    return len(chunks)


def ingest_file(path: Path, doc_type: str, owner: Optional[str] = None) -> int:
    """doc_type: 'manual' or 'paper'. Returns the number of chunks added."""
    text = _extract_text(path)
    return ingest_text(text, path.name, doc_type, owner=owner)
