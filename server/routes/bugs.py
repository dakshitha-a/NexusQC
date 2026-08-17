"""User-facing bug report submission -- the admin-facing inbox
(list/archive/delete) lives in server/routes/admin.py."""
from __future__ import annotations

import uuid
from typing import Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile

from app.auth import models
from app.auth.deps import get_current_user
from app.config import BUG_REPORTS_DIR

router = APIRouter(prefix="/api/bug-reports", tags=["bugs"])

# Screenshots are the whole point of attachments here, so this is images only.
# Bounds rather than a quota: an attachment does NOT count against the
# reporter's storage quota (a quota-blocked bug report is perverse), which
# means these caps are the only thing standing between this route and an
# unbounded write channel. nginx's client_max_body_size is 512m, far too loose
# to be the only limit.
MAX_ATTACHMENTS = 3
MAX_ATTACHMENT_BYTES = 5 * 1024 * 1024

# Sniffed from the first bytes, not taken from the declared content-type --
# that header is supplied by the client and is not evidence of anything. The
# extension written to disk comes from this table too, never from the
# uploaded filename.
_MAGIC: list[tuple[bytes, str, str]] = [
    (b"\x89PNG\r\n\x1a\n", "image/png", ".png"),
    (b"\xff\xd8\xff", "image/jpeg", ".jpg"),
    (b"GIF87a", "image/gif", ".gif"),
    (b"GIF89a", "image/gif", ".gif"),
    (b"BM", "image/bmp", ".bmp"),
]


def _sniff_image(data: bytes) -> Optional[tuple[str, str]]:
    """Returns (content_type, extension) for a recognised image, else None."""
    for magic, content_type, ext in _MAGIC:
        if data.startswith(magic):
            return content_type, ext
    # WEBP is RIFF....WEBP -- a prefix check alone would match any RIFF file.
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp", ".webp"
    return None


def _validate_body(body: str) -> str:
    """One enforcement point for the length limit.

    There used to be two, and they disagreed: this route rejected >1000 words
    with a 422 while models.create_bug_report silently truncated to 1000, which
    made the truncation unreachable over HTTP and meant the two layers had
    different ideas of what should happen. Rejecting is the honest one -- a
    silently truncated report loses the end of what someone wrote, which for a
    bug report is often the part with the error message in it.
    """
    if not body.strip():
        raise HTTPException(status_code=422, detail="bug report body cannot be empty")
    if len(body.split()) > models.BUG_REPORT_MAX_WORDS:
        raise HTTPException(
            status_code=422,
            detail=f"bug reports are limited to {models.BUG_REPORT_MAX_WORDS} words",
        )
    return body


@router.post("")
def submit_bug_report(
    body: str = Form(...),
    files: list[UploadFile] = File(default=[]),
    user: dict = Depends(get_current_user),
):
    """Files a report, optionally with screenshots.

    Multipart rather than JSON, mirroring the one other upload path in this app
    (server/routes/kb.py's add_source). The frontend always posts FormData, so
    there is a single shape here rather than a JSON branch and a multipart one.
    """
    _validate_body(body)

    real = [f for f in files if f is not None and f.filename]
    if len(real) > MAX_ATTACHMENTS:
        raise HTTPException(
            status_code=422,
            detail=f"at most {MAX_ATTACHMENTS} screenshots per report",
        )

    # Read and validate EVERY file before writing any of them or creating the
    # report row, so a rejected second file cannot leave a half-attached report
    # behind.
    staged: list[tuple[bytes, str, str, str]] = []  # (data, content_type, ext, original_name)
    for f in real:
        data = f.file.read(MAX_ATTACHMENT_BYTES + 1)
        if len(data) > MAX_ATTACHMENT_BYTES:
            raise HTTPException(
                status_code=422,
                detail=f"each screenshot must be under {MAX_ATTACHMENT_BYTES // (1024 * 1024)}MB",
            )
        sniffed = _sniff_image(data)
        if sniffed is None:
            raise HTTPException(
                status_code=422,
                detail=f"'{f.filename}' is not a recognised image (PNG, JPEG, GIF, BMP or WEBP)",
            )
        content_type, ext = sniffed
        staged.append((data, content_type, ext, f.filename))

    row = models.create_bug_report(str(user["id"]), body)
    report_id = str(row["id"])

    if staged:
        directory = BUG_REPORTS_DIR / report_id
        directory.mkdir(parents=True, exist_ok=True)
        for data, content_type, ext, original_name in staged:
            # The stored name is generated here. The uploaded filename is
            # attacker-controlled and is never used as a path segment -- it is
            # kept only as original_name, for display.
            stored_name = f"{uuid.uuid4().hex}{ext}"
            (directory / stored_name).write_bytes(data)
            models.add_bug_report_attachment(
                report_id, stored_name, original_name, content_type, len(data)
            )

    return {"id": report_id, "created_at": row["created_at"], "attachments": len(staged)}
