"""GET /api/notice: the update notice, for every tab, signed in or not.

Public on purpose. What it says, that the app will restart at a given time,
is not a secret, and the login screen is exactly where someone arriving just
before an update should see it. Exempt from maintenance mode, because the
overlay asks it whether the lockout has lifted, and a route that answered
503 during the lockout could never tell it. See app/auth/update_notice.py.
"""
from __future__ import annotations

import time

from fastapi import APIRouter

from app.auth.middleware import maintenance_mode
from app.auth.update_notice import current_notice

router = APIRouter()


@router.get("/api/notice")
def get_notice():
    # `now` lets the browser count down against the server's clock rather
    # than its own, which on a laptop can be minutes out.
    return {"notice": current_notice(), "maintenance": maintenance_mode(), "now": time.time()}
