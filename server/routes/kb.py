"""Knowledge-base source management (upload/list/delete), mirroring
app/ui/components.py's render_kb_panel but as REST endpoints."""
from __future__ import annotations

import hashlib
import re
from pathlib import Path

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel

from app.config import DATA_DIR, UPLOADS_DIR
from app.rag.ingest import ingest_file, ingest_text
from app.rag.store import delete_source, list_sources

router = APIRouter()

# scripts/seed_knowledge_base.py writes the pre-seeded BAGEL/ORCA/PySCF
# manual sources here (not into UPLOADS_DIR, which is only for
# user-uploaded/dropped sources) -- ingest.py stores just the basename as
# `source` regardless of which of these directories a file actually lives
# in, so previewing a source by name has to check both.
_SCRAPED_DIR = DATA_DIR / "scraped"
_CONTENT_SEARCH_DIRS = [UPLOADS_DIR, *(_SCRAPED_DIR.glob("*") if _SCRAPED_DIR.is_dir() else [])]


def _find_source_file(source: str) -> Path | None:
    # Path(source).name strips any directory components a malicious/odd
    # `source` value might contain, before ever joining it onto a real
    # directory -- then resolve+parent-check below is defense in depth on
    # top of that, mirroring server/routes/jobs.py's artifact-serving route.
    name = Path(source).name
    for d in _CONTENT_SEARCH_DIRS:
        candidate = d / name
        try:
            resolved = candidate.resolve(strict=True)
        except OSError:
            continue
        if resolved.parent == d.resolve() and resolved.is_file():
            return resolved
    return None


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


_MEDIA_TYPES = {".pdf": "application/pdf", ".html": "text/html", ".htm": "text/html"}


@router.get("/api/kb/sources/{source}/content")
def get_source_content(source: str):
    """Serves a KB source's raw file for the sidebar's preview flyout --
    native browser rendering (PDF viewer / plain text) rather than any
    server-side extraction, so the preview stays fast regardless of doc
    type. Not the chunked/embedded text used for retrieval -- this is the
    original file as uploaded or scraped."""
    path = _find_source_file(source)
    if path is None:
        raise HTTPException(status_code=404, detail=f"No content file for source: {source}")
    media_type = _MEDIA_TYPES.get(path.suffix.lower(), "text/plain")
    return FileResponse(path, media_type=media_type)


@router.delete("/api/kb/sources/{source}")
def remove_source(source: str):
    n_deleted = delete_source(source)
    if n_deleted == 0:
        raise HTTPException(status_code=404, detail=f"No such source: {source}")
    return {"deleted_chunks": n_deleted}
