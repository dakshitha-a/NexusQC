"""Knowledge-base source management (upload/list/delete), mirroring
app/ui/components.py's render_kb_panel but as REST endpoints."""
from __future__ import annotations

import hashlib
import re

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from pydantic import BaseModel

from app.config import UPLOADS_DIR
from app.rag.ingest import ingest_file, ingest_text
from app.rag.store import delete_source, list_sources

router = APIRouter()


@router.get("/api/kb/sources")
def get_sources():
    return list_sources()


@router.post("/api/kb/sources", status_code=201)
async def add_source(file: UploadFile = File(...), doc_type: str = Form(...)):
    if doc_type not in ("manual", "paper"):
        raise HTTPException(status_code=400, detail="doc_type must be 'manual' or 'paper'")
    dest = UPLOADS_DIR / file.filename
    dest.write_bytes(await file.read())
    try:
        n_chunks = ingest_file(dest, doc_type)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"source": file.filename, "doc_type": doc_type, "n_chunks": n_chunks}


class AddTextSource(BaseModel):
    text: str
    doc_type: str
    filename: str | None = None


_SLUG_RE = re.compile(r"[^a-z0-9]+")


def _synthesize_filename(text: str) -> str:
    """Used when the caller has no natural filename -- dropped/pasted text,
    a scholar-search result card. Ingestion overwrites-by-filename (see
    ingest.py), so this must not collide across unrelated snippets: the
    slug is just for human readability in the source list, the sha1
    suffix of the actual content is what makes it collision-safe."""
    first_line = next((ln.strip() for ln in text.splitlines() if ln.strip()), "untitled")
    slug = _SLUG_RE.sub("-", first_line.lower()).strip("-")[:60] or "untitled"
    digest = hashlib.sha1(text.encode()).hexdigest()[:8]
    return f"{slug}-{digest}.txt"


@router.post("/api/kb/sources/text", status_code=201)
def add_text_source(body: AddTextSource):
    if body.doc_type not in ("manual", "paper"):
        raise HTTPException(status_code=400, detail="doc_type must be 'manual' or 'paper'")
    filename = body.filename or _synthesize_filename(body.text)
    # Written to disk (not just the vector store) so it shows up uniformly
    # alongside file uploads for list_sources/delete_source, and so a
    # dropped snippet survives a KB re-seed the same way an uploaded file does.
    (UPLOADS_DIR / filename).write_text(body.text)
    try:
        n_chunks = ingest_text(body.text, filename, body.doc_type)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"source": filename, "doc_type": body.doc_type, "n_chunks": n_chunks}


@router.delete("/api/kb/sources/{source}")
def remove_source(source: str):
    n_deleted = delete_source(source)
    if n_deleted == 0:
        raise HTTPException(status_code=404, detail=f"No such source: {source}")
    return {"deleted_chunks": n_deleted}
