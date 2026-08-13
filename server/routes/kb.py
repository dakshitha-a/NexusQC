"""Knowledge-base source management (upload/list/delete), mirroring
app/ui/components.py's render_kb_panel but as REST endpoints."""
from __future__ import annotations

from fastapi import APIRouter, File, Form, HTTPException, UploadFile

from app.config import UPLOADS_DIR
from app.rag.ingest import ingest_file
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


@router.delete("/api/kb/sources/{source}")
def remove_source(source: str):
    n_deleted = delete_source(source)
    if n_deleted == 0:
        raise HTTPException(status_code=404, detail=f"No such source: {source}")
    return {"deleted_chunks": n_deleted}
