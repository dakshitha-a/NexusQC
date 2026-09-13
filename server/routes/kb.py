"""Knowledge-base source management (upload/list/delete), mirroring
app/ui/components.py's render_kb_panel but as REST endpoints.

Ownership: uploads are scoped to the caller (owner_key below, None when
auth isn't configured for this deployment -- see app/rag/store.py's
SHARED_OWNER for how that's represented in Chroma metadata) so
list_sources/delete_source only ever show/touch a user's own uploads plus
shared content, and two different users uploading identically-named files
never collide (see ingest.py's chunk-id docstring). File storage on disk
mirrors this: UPLOADS_DIR/<owner_id>/<filename> for an owned upload,
UPLOADS_DIR/<filename> (unchanged) for a no-auth/legacy deployment."""
from __future__ import annotations

import hashlib
import re
from pathlib import Path
from urllib.parse import urlparse

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel

from app.auth.ownership import current_user_or_none
from app.config import DATA_DIR, UPLOADS_DIR
from app.rag.ingest import ALLOWED_FILE_EXTENSIONS, ingest_file, ingest_text
from app.rag.quota import QUOTA_BYTES as KB_QUOTA_BYTES
from app.rag.quota import current_usage_bytes as kb_storage_usage_bytes
from app.rag.quota import enforce_quota
from app.rag.store import delete_source, delete_upload_file, list_sources
from app.rag.web_scrape import ScrapeError, fetch_page, robots_disallows

router = APIRouter()

# scripts/seed_knowledge_base.py writes the pre-seeded BAGEL/ORCA/PySCF
# manual sources here (not into UPLOADS_DIR, which is only for
# user-uploaded/dropped sources) -- ingest.py stores just the basename as
# `source` regardless of which of these directories a file actually lives
# in, so previewing a source by name has to check both.
_SCRAPED_DIR = DATA_DIR / "scraped"


def _owner_key(request: Request) -> str | None:
    """The Chroma `owner` value and upload-subdirectory name to WRITE a
    new upload under -- the calling user's own id, or None when auth isn't
    configured for this deployment. Deliberately NOT None for an admin:
    an admin's own upload is still scoped to them specifically, not
    silently shared with every other user just because they're an admin.
    Use _owner_filter (below) for list/delete instead, where "no filter"
    IS the right behavior for an admin."""
    user = current_user_or_none(request)
    return str(user["id"]) if user is not None else None


def _owner_filter(request: Request) -> str | None:
    """The owner_filter to READ/DELETE with -- None means "no filter, see/
    touch everything" for both an unauthenticated deployment and an admin
    caller (matching app/auth/ownership.py's owned_ids_filter convention
    for jobs/threads), otherwise the caller's own id (shared content plus
    their own)."""
    user = current_user_or_none(request)
    if user is None or user["role"] == "admin":
        return None
    return str(user["id"])


def _upload_dir(owner: str | None) -> Path:
    d = UPLOADS_DIR / owner if owner else UPLOADS_DIR
    d.mkdir(parents=True, exist_ok=True)
    return d


def _safe_dest(owner: str | None, filename: str | None) -> Path:
    """The one place a client-supplied filename becomes a path to write to.

    R-002. `add_text_source` did `(_upload_dir(owner) / filename).write_text(...)`
    with `filename` straight off a Pydantic `str | None` that had no
    validator, and `add_source` did the same with the multipart filename
    after checking only its extension. A `pathlib` join with an absolute
    string discards the left operand entirely, so a caller did not even need
    `../`: `Path("/app/data/kb/uploads/user-123") / "/app/data/deploy/request.json"`
    is `/app/data/deploy/request.json`. `data/` is bind-mounted into the api
    container, and `scripts/deploy_runner.sh` polls `data/deploy/request.json`
    at that fixed name every three seconds and runs `scripts/update.sh` or
    `--rollback` on the host from what it finds there. So an ordinary user's
    knowledge-base upload could reach a host deployment action.

    The defence already existed twenty lines up. `_find_source_file`, the READ
    path, takes `Path(source).name` and then re-checks containment after
    resolving, and its comment explains why. It was applied in one direction
    only, which is a habit rather than an accident here (R-005), so this
    function exists to be the single direction-agnostic answer that both
    write paths and the URL path call.

    Two independent checks, deliberately, because either alone has a hole:
    taking `.name` defeats traversal and absolute paths, and re-resolving
    defeats a symlink already sitting in the upload directory.
    """
    name = Path(filename or "").name
    if not name or name in (".", ".."):
        raise HTTPException(status_code=400, detail="A source needs a file name.")
    d = _upload_dir(owner)
    dest = d / name
    try:
        parent_ok = dest.resolve().parent == d.resolve()
    except OSError:
        parent_ok = False
    if not parent_ok:
        raise HTTPException(status_code=400, detail=f"Invalid source name: {filename!r}")
    return dest


def _content_search_dirs(owner: str | None) -> list[Path]:
    """Directories `get_source_content` may serve a file out of, for a
    caller whose ownership filter is `owner` (None == admin/no-auth).

    F-022 fix. This used to extend the search to EVERY owner subdirectory
    under UPLOADS_DIR whenever `owner` was set, justified in a comment as
    "mirroring list_sources' 'shared plus mine' visibility, but slightly
    wider" and as legacy ("content preview was never ownership-gated even
    pre-retrofit"). Neither survived measurement: it was not slightly
    wider, it was unrestricted -- any authenticated user could read any
    other user's private upload by name, confirmed live with a marker
    string. And "it was never gated" is the same reasoning SEC-06
    overturned for job artifacts.

    The search is now the caller's own upload directory plus the
    genuinely shared, pre-seeded corpus under _SCRAPED_DIR -- which is
    exactly the "shared plus mine" visibility list_sources and the delete
    route already enforce. The `owner is None` branch (admin, or a
    no-auth deployment where everything ingests under SHARED_OWNER) is
    deliberately left alone: UPLOADS_DIR itself is that branch's own
    directory, and an admin is meant to see everything.
    """
    dirs = [_upload_dir(owner)]
    if _SCRAPED_DIR.is_dir():
        dirs.extend(_SCRAPED_DIR.glob("*"))
    return dirs


def _find_source_file(source: str, owner: str | None) -> Path | None:
    # Path(source).name strips any directory components a malicious/odd
    # `source` value might contain, before ever joining it onto a real
    # directory -- then resolve+parent-check below is defense in depth on
    # top of that, mirroring server/routes/jobs.py's artifact-serving route.
    name = Path(source).name
    for d in _content_search_dirs(owner):
        candidate = d / name
        try:
            resolved = candidate.resolve(strict=True)
        except OSError:
            continue
        if resolved.parent == d.resolve() and resolved.is_file():
            return resolved
    return None


@router.get("/api/kb/sources")
def get_sources(request: Request):
    return list_sources(owner_filter=_owner_filter(request))


@router.get("/api/kb/quota")
def get_kb_quota(request: Request):
    """Knowledge-base storage usage for the Knowledge base panel's usage
    display. With no auth configured: the original flat app/rag/quota.py
    10GB cap shared by everyone. With auth configured: the CALLER'S OWN
    KB usage against their own per-user KB quota (see
    app/auth/storage_quota.py)."""
    user = current_user_or_none(request)
    if user is not None:
        from app.auth.storage_quota import usage_report
        report = usage_report()
        row = next((r for r in report["per_user"] if r["user_id"] == str(user["id"])), None)
        if row is not None:
            return {"used_bytes": row["kb_bytes"], "quota_bytes": row["kb_quota_bytes"], "category": "per_user_kb"}
    return {"used_bytes": kb_storage_usage_bytes(), "quota_bytes": KB_QUOTA_BYTES, "category": "global"}


@router.post("/api/kb/sources", status_code=201)
def add_source(request: Request, file: UploadFile = File(...), doc_type: str = Form(...)):
    if doc_type not in ("manual", "paper"):
        raise HTTPException(status_code=400, detail="doc_type must be 'manual' or 'paper'")
    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in ALLOWED_FILE_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file type '{suffix}' -- only PDF, TXT, MD, and DOCX files are accepted",
        )
    owner = _owner_key(request)
    dest = _safe_dest(owner, file.filename)
    dest.write_bytes(file.file.read())
    try:
        n_chunks = ingest_file(dest, doc_type, owner=owner)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    enforce_quota()
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
def add_text_source(body: AddTextSource, request: Request):
    if body.doc_type not in ("manual", "paper"):
        raise HTTPException(status_code=400, detail="doc_type must be 'manual' or 'paper'")
    owner = _owner_key(request)
    filename = body.filename or _synthesize_filename(body.text)
    # Written to disk (not just the vector store) so it shows up uniformly
    # alongside file uploads for list_sources/delete_source, and so a
    # dropped snippet survives a KB re-seed the same way an uploaded file does.
    dest = _safe_dest(owner, filename)
    filename = dest.name
    dest.write_text(body.text)
    try:
        n_chunks = ingest_text(body.text, filename, body.doc_type, owner=owner)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    enforce_quota()
    return {"source": filename, "doc_type": body.doc_type, "n_chunks": n_chunks}


class AddUrlSource(BaseModel):
    url: str
    doc_type: str
    # F-002: set to True to ingest a URL whose own robots.txt asks that it
    # not be fetched/used for AI ingestion. Default False means the first
    # attempt is REFUSED with the site's stated reason, so the operator
    # makes that call knowingly rather than the app making it silently on
    # their behalf -- which is how 11 pages from a site this repo's own
    # seeder deliberately refuses to crawl ended up in the KB.
    ignore_robots: bool = False


def _filename_from_url(url: str) -> str:
    """Deterministic per-URL filename (not per-fetch) -- re-adding the same
    URL overwrites its previous chunks in place, mirroring ingest_text's
    overwrite-by-filename semantics for re-uploaded files. The .html
    extension makes get_source_content (below) serve it as
    `text/html` so the preview flyout renders it like a real page rather
    than a wall of plain text."""
    parsed = urlparse(url)
    slug = _SLUG_RE.sub("-", f"{parsed.netloc}{parsed.path}".lower()).strip("-")[:80] or "page"
    digest = hashlib.sha1(url.encode()).hexdigest()[:8]
    return f"{slug}-{digest}.html"


@router.post("/api/kb/sources/url", status_code=201)
def add_url_source(body: AddUrlSource, request: Request):
    if body.doc_type not in ("manual", "paper"):
        raise HTTPException(status_code=400, detail="doc_type must be 'manual' or 'paper'")

    # F-002: check the site's own stated wishes before fetching it, the way
    # scripts/seed_knowledge_base.py already does for the manuals it
    # crawls. A 409 rather than a 403: this is not the app refusing the
    # operator permission, it is the app declining to make a choice on
    # their behalf. Re-POST with ignore_robots=true to proceed anyway.
    if not body.ignore_robots:
        reason = robots_disallows(body.url)
        if reason:
            raise HTTPException(
                status_code=409,
                detail=(
                    f"{reason} Not fetched. Re-send with \"ignore_robots\": true to "
                    f"ingest it anyway."
                ),
            )

    try:
        title, text, html = fetch_page(body.url)
    except ScrapeError as e:
        raise HTTPException(status_code=400, detail=str(e))

    owner = _owner_key(request)
    filename = _filename_from_url(body.url)
    # Raw HTML is what the preview flyout renders (see get_source_content);
    # the extracted plain text (prefixed with title/source like the seed
    # script's own scraped manuals) is what actually gets chunked/embedded.
    # Derived from the URL rather than client-supplied, so this is belt and
    # braces; it goes through the same door as the other two so there is one
    # door rather than three, which is the whole point of R-005.
    _safe_dest(owner, filename).write_text(html, errors="ignore")
    embed_text = f"{title}\nSource: {body.url}\n\n{text}"
    try:
        n_chunks = ingest_text(embed_text, filename, body.doc_type, owner=owner)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    enforce_quota()
    return {"source": filename, "doc_type": body.doc_type, "n_chunks": n_chunks}


_MEDIA_TYPES = {".pdf": "application/pdf", ".html": "text/html", ".htm": "text/html"}


@router.get("/api/kb/sources/{source}/content")
def get_source_content(source: str, request: Request):
    """Serves a KB source's raw file for the sidebar's preview flyout --
    native browser rendering (PDF viewer / plain text) rather than any
    server-side extraction, so the preview stays fast regardless of doc
    type. Not the chunked/embedded text used for retrieval -- this is the
    original file as uploaded or scraped."""
    path = _find_source_file(source, _owner_filter(request))
    if path is None:
        raise HTTPException(status_code=404, detail=f"No content file for source: {source}")
    media_type = _MEDIA_TYPES.get(path.suffix.lower(), "text/plain")
    return FileResponse(path, media_type=media_type)


@router.delete("/api/kb/sources/{source}")
def remove_source(source: str, request: Request, owner: str | None = None):
    """SEC-09 fix: an admin's delete used to be scoped by source NAME
    only, with no owner disambiguator -- if two different users happened
    to have uploaded identically-named sources, deleting one via this
    route silently deleted both. A regular user's own delete never hit
    this (their owner_filter is always their own id, so it only ever
    touches their own chunks -- see delete_source's docstring), so this
    only changes admin (or no-auth) behavior. `owner` is an optional query
    param (?owner=<user_id>, or the literal string app.rag.store.
    SHARED_OWNER for the pre-seeded/shared corpus) an admin caller can
    pass to name exactly whose copy to delete. When omitted: if only one
    owner has a source by this name (the common case, and the only case
    on a no-auth deployment, where everything ingests under SHARED_OWNER),
    behavior is unchanged -- delete it. If MORE than one owner has an
    identically-named source, this now refuses with a 409 listing the
    colliding owners rather than silently deleting all of them -- the
    same "never silently resolve an ambiguity, make the caller pick"
    discipline this app already applies to basis-set/keyword
    disambiguation (see CLAUDE.md)."""
    caller_filter = _owner_filter(request)
    if caller_filter is not None:
        # Ordinary (non-admin) caller: owner is irrelevant here, always
        # scoped to their own uploads only.
        n_deleted = delete_source(source, owner_filter=caller_filter)
        if n_deleted == 0:
            raise HTTPException(status_code=404, detail=f"No such source: {source}")
        # F-001: the original uploaded file has to go with the chunks. It
        # is resolved BEFORE nothing else -- delete_source has already run
        # by here, so the Chroma-derived owner list is gone and only the
        # caller's own id can name the file. That is exactly right for
        # this branch, which is scoped to the caller by construction.
        delete_upload_file(source, caller_filter)
        return {"deleted_chunks": n_deleted}

    # Admin / no-auth branch. Resolve the owning set BEFORE deleting, since
    # list_sources reads Chroma and delete_source is about to empty it --
    # without this the file could no longer be located to unlink.
    owners = {s["owner"] for s in list_sources() if s["source"] == source}
    if owner is None:
        if len(owners) > 1:
            raise HTTPException(
                status_code=409,
                detail=(
                    f"Multiple uploads named '{source}' exist under different owners: "
                    f"{sorted(owners)}. Pass ?owner=<id> to delete a specific one."
                ),
            )

    n_deleted = delete_source(source, owner_filter=owner)
    if n_deleted == 0:
        raise HTTPException(status_code=404, detail=f"No such source: {source}")
    for o in ({owner} if owner is not None else owners):
        delete_upload_file(source, o)
    return {"deleted_chunks": n_deleted}
