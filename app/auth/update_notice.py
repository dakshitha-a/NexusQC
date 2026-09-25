"""The update notice: what every user is told before, during and after an update.

scripts/update.sh is the only writer of the notice itself. It keeps one
app_config row, `update_notice`, current as the update moves through its
phases, so a notice looks the same whether the update was started from the
admin console or from a shell on the host:

    scheduled         announced; the app restarts at `restart_at`
    waiting_for_jobs  running calculations must finish first; new ones queue
    imminent          about a minute before the lockout
    in_progress       locked out; the stack is restarting
    done              finished; shown once, until `expires_at`
    failed            the update did not finish; nothing changed for users
    cancelled         an admin called it off before the lockout

The api only reads it, plus one write: an admin's request to cancel, which
goes into a second row, `update_cancel`, that update.sh polls while it waits.
The notice row is never written from here, so the script stays the single
authority on what phase the update is in.

Why a row and a poll rather than a push: there is no channel today that
reaches every open tab (the event stream is per conversation), and the
deployment's own restart would cut one if there were. A 15-second poll of a
cached read reaches every tab, survives the restart, and costs nothing.
"""
from __future__ import annotations

import threading
import time
from typing import Optional

from app.auth import models

NOTICE_KEY = "update_notice"
CANCEL_KEY = "update_cancel"
CANCELLABLE_PHASES = ("scheduled", "waiting_for_jobs", "imminent")

# Read through a short TTL: every tab asks every 15 seconds, and the answer
# changes a handful of times per update.
_TTL_SECONDS = 2.0
_cache: dict = {"value": None, "at": 0.0}
_lock = threading.Lock()


def _read() -> Optional[dict]:
    now = time.monotonic()
    with _lock:
        if now - _cache["at"] < _TTL_SECONDS:
            return _cache["value"]
    value = models.get_app_config(NOTICE_KEY)
    if not isinstance(value, dict):
        value = None
    with _lock:
        _cache["value"], _cache["at"] = value, now
    return value


def current_notice(now: Optional[float] = None) -> Optional[dict]:
    """The notice users should see now, or None. An expired one is None, so
    a notice left behind by an update that was killed outright (a SIGKILL
    runs no trap) cannot stay on screen forever."""
    n = _read()
    if not n:
        return None
    now = time.time() if now is None else now
    try:
        if float(n.get("expires_at") or 0) and float(n["expires_at"]) < now:
            return None
    except (TypeError, ValueError):
        return None
    return {k: n.get(k) for k in (
        "id", "phase", "restart_at", "waiting_jobs", "message", "commit", "updated_at", "expires_at",
        "stops_running_jobs",
    )}


def request_cancel(admin: dict) -> dict:
    """Asks the running update to stop before it locks anyone out. Refused
    once the lockout has begun: from there, stopping is the failure path,
    not a cancellation."""
    n = current_notice()
    if not n or n.get("phase") not in CANCELLABLE_PHASES:
        phase = (n or {}).get("phase") or "none"
        raise ValueError(f"there is no update waiting to start (phase: {phase})")
    models.set_app_config(CANCEL_KEY, {
        "id": n.get("id"), "by": admin.get("username"), "at": time.time(),
    }, updated_by=str(admin["id"]))
    return n
