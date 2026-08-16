"""User-facing bug report submission -- the admin-facing inbox
(list/close) lives in server/routes/admin.py."""
from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel, field_validator

from app.auth import models
from app.auth.deps import get_current_user

router = APIRouter(prefix="/api/bug-reports", tags=["bugs"])


class BugReportIn(BaseModel):
    body: str

    @field_validator("body")
    @classmethod
    def _not_too_long(cls, v: str) -> str:
        if len(v.split()) > models.BUG_REPORT_MAX_WORDS:
            raise ValueError(f"bug reports are limited to {models.BUG_REPORT_MAX_WORDS} words")
        if not v.strip():
            raise ValueError("bug report body cannot be empty")
        return v


@router.post("")
def submit_bug_report(body: BugReportIn, user: dict = Depends(get_current_user)):
    row = models.create_bug_report(str(user["id"]), body.body)
    return {"id": str(row["id"]), "created_at": row["created_at"]}
