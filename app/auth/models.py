"""Plain CRUD functions against the tables in app/auth/db.py's schema. No
ORM (see db.py's module docstring for why) -- each function is a short,
direct SQL statement, matching the rest of this codebase's preference for
explicit code over a framework layer for a handful of simple tables.
"""
from __future__ import annotations

import json
import secrets
import string
from datetime import datetime, timedelta, timezone
from typing import Optional

from app.auth.db import get_pool
from app.auth.security import hash_password, verify_password
from app.config import SESSION_TTL_SECONDS


def _now() -> datetime:
    return datetime.now(timezone.utc)


# --- Users -------------------------------------------------------------


def create_user(email: str, username: str, password: str, role: str = "user") -> dict:
    with get_pool().connection() as conn:
        row = conn.execute(
            """INSERT INTO users (email, username, password_hash, role)
               VALUES (%s, %s, %s, %s)
               RETURNING id, email, username, role, is_active, created_at""",
            (email, username, hash_password(password), role),
        ).fetchone()
    return row


def get_user_by_id(user_id: str) -> Optional[dict]:
    with get_pool().connection() as conn:
        return conn.execute(
            "SELECT id, email, username, password_hash, role, is_active, created_at, last_login_at "
            "FROM users WHERE id = %s",
            (user_id,),
        ).fetchone()


def get_user_by_login(email_or_username: str) -> Optional[dict]:
    with get_pool().connection() as conn:
        return conn.execute(
            "SELECT id, email, username, password_hash, role, is_active, created_at, last_login_at "
            "FROM users WHERE email = %s OR username = %s",
            (email_or_username, email_or_username),
        ).fetchone()


def verify_login(email_or_username: str, password: str) -> Optional[dict]:
    """Returns the user row on success, None on bad credentials OR an
    inactive account -- deliberately the same outcome for both, so a
    deactivated user can't distinguish "wrong password" from "your account
    was disabled" through the login form's response."""
    user = get_user_by_login(email_or_username)
    if user is None or not user["is_active"]:
        return None
    if not verify_password(password, user["password_hash"]):
        return None
    return user


def touch_last_login(user_id: str) -> None:
    with get_pool().connection() as conn:
        conn.execute("UPDATE users SET last_login_at = now() WHERE id = %s", (user_id,))


def set_password(user_id: str, new_password: str) -> None:
    with get_pool().connection() as conn:
        conn.execute(
            "UPDATE users SET password_hash = %s WHERE id = %s",
            (hash_password(new_password), user_id),
        )


def list_users() -> list[dict]:
    with get_pool().connection() as conn:
        return conn.execute(
            "SELECT id, email, username, role, is_active, created_at, last_login_at "
            "FROM users ORDER BY created_at ASC"
        ).fetchall()


def delete_user(user_id: str) -> None:
    """Deletes the users row. Cascades (via FK ON DELETE CASCADE) to
    sessions and ownership_index automatically -- but NOT to the actual
    job/thread/KB files on disk, which the caller (server/admin_cli.py /
    the admin users route) must clean up separately BEFORE calling this,
    since those live outside Postgres entirely and this function has no
    way to reach them."""
    with get_pool().connection() as conn:
        conn.execute("DELETE FROM users WHERE id = %s", (user_id,))


def count_admins() -> int:
    with get_pool().connection() as conn:
        row = conn.execute(
            "SELECT count(*) AS n FROM users WHERE role = 'admin' AND is_active"
        ).fetchone()
    return row["n"]


# --- Invite tokens -------------------------------------------------------


def _generate_token() -> str:
    alphabet = string.ascii_letters + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(32))


def create_invite_token(created_by: Optional[str], role: str, email_hint: Optional[str], ttl_hours: int = 72) -> dict:
    token = _generate_token()
    expires_at = _now() + timedelta(hours=ttl_hours)
    with get_pool().connection() as conn:
        row = conn.execute(
            """INSERT INTO invite_tokens (token, created_by, role, email_hint, expires_at)
               VALUES (%s, %s, %s, %s, %s)
               RETURNING token, role, email_hint, expires_at, created_at""",
            (token, created_by, role, email_hint, expires_at),
        ).fetchone()
    return row


class InviteTokenError(Exception):
    """Raised by register_with_invite_token for any invalid-token reason
    (not found, already redeemed, expired) or a duplicate email/username --
    the route layer maps this to a 400/409 response."""


def register_with_invite_token(token: str, email: str, username: str, password: str) -> dict:
    """Validates the invite token and creates the user in ONE transaction,
    so there's no window where the token is marked redeemed but no user
    exists yet (which would need a placeholder value for the token's
    redeemed_by column -- not viable, since that column has a real foreign
    key to users(id) and a placeholder id that doesn't correspond to an
    actual row would just fail that constraint). `SELECT ... FOR UPDATE`
    locks the token row for the duration of the transaction, so two
    concurrent registration attempts racing to redeem the same token can't
    both pass the validity check before either commits -- the second
    request's FOR UPDATE blocks until the first transaction commits or
    rolls back, then re-reads the now-redeemed row and correctly fails."""
    with get_pool().connection() as conn:
        with conn.transaction():
            token_row = conn.execute(
                "SELECT token, role, redeemed_by, expires_at FROM invite_tokens WHERE token = %s FOR UPDATE",
                (token,),
            ).fetchone()
            if token_row is None or token_row["redeemed_by"] is not None:
                raise InviteTokenError("invalid or already-used invite token")
            if token_row["expires_at"] <= _now():
                raise InviteTokenError("invite token has expired")
            existing = conn.execute(
                "SELECT id FROM users WHERE email = %s OR username = %s", (email, username)
            ).fetchone()
            if existing is not None:
                raise InviteTokenError("email or username already registered")
            user = conn.execute(
                """INSERT INTO users (email, username, password_hash, role)
                   VALUES (%s, %s, %s, %s)
                   RETURNING id, email, username, role, is_active, created_at""",
                (email, username, hash_password(password), token_row["role"]),
            ).fetchone()
            conn.execute(
                "UPDATE invite_tokens SET redeemed_by = %s, redeemed_at = now() WHERE token = %s",
                (user["id"], token),
            )
    return user


def list_invite_tokens() -> list[dict]:
    with get_pool().connection() as conn:
        return conn.execute(
            "SELECT token, created_by, role, email_hint, expires_at, redeemed_by, redeemed_at, created_at "
            "FROM invite_tokens ORDER BY created_at DESC"
        ).fetchall()


# --- Sessions ------------------------------------------------------------


def create_session(user_id: str, session_id: str, user_agent: Optional[str]) -> dict:
    expires_at = _now() + timedelta(seconds=SESSION_TTL_SECONDS)
    with get_pool().connection() as conn:
        return conn.execute(
            """INSERT INTO sessions (id, user_id, expires_at, user_agent)
               VALUES (%s, %s, %s, %s)
               RETURNING id, user_id, issued_at, expires_at""",
            (session_id, user_id, expires_at, user_agent),
        ).fetchone()


def revoke_session(session_id: str) -> None:
    with get_pool().connection() as conn:
        conn.execute("UPDATE sessions SET revoked = true WHERE id = %s", (session_id,))


# --- Ownership index -------------------------------------------------------


def record_ownership(kind: str, resource_id: str, owner_user_id: str) -> None:
    with get_pool().connection() as conn:
        conn.execute(
            """INSERT INTO ownership_index (kind, resource_id, owner_user_id)
               VALUES (%s, %s, %s)
               ON CONFLICT (kind, resource_id) DO NOTHING""",
            (kind, resource_id, owner_user_id),
        )


def all_owners(kind: str) -> dict[str, str]:
    """Bulk resource_id -> owner_user_id map for one whole `kind`, used by
    list routes (e.g. GET /api/jobs) that need to check ownership for every
    row of a filesystem walk without issuing one Postgres query per row."""
    with get_pool().connection() as conn:
        rows = conn.execute(
            "SELECT resource_id, owner_user_id FROM ownership_index WHERE kind = %s", (kind,)
        ).fetchall()
    return {r["resource_id"]: str(r["owner_user_id"]) for r in rows}


def get_owner(kind: str, resource_id: str) -> Optional[str]:
    with get_pool().connection() as conn:
        row = conn.execute(
            "SELECT owner_user_id FROM ownership_index WHERE kind = %s AND resource_id = %s",
            (kind, resource_id),
        ).fetchone()
    return str(row["owner_user_id"]) if row else None


def list_owned(kind: str, owner_user_id: str) -> list[str]:
    with get_pool().connection() as conn:
        rows = conn.execute(
            "SELECT resource_id FROM ownership_index WHERE kind = %s AND owner_user_id = %s",
            (kind, owner_user_id),
        ).fetchall()
    return [r["resource_id"] for r in rows]


def forget_ownership(kind: str, resource_id: str) -> None:
    """Removes one resource's ownership_index row -- called by whatever
    actually deletes the underlying job directory/thread (quota eviction,
    an admin bulk purge, or a normal user-initiated delete), so a purged
    resource doesn't leave a permanently orphaned row behind that
    all_owners()/list_owned() would keep counting forever."""
    with get_pool().connection() as conn:
        conn.execute(
            "DELETE FROM ownership_index WHERE kind = %s AND resource_id = %s", (kind, resource_id)
        )


# --- Bug reports -----------------------------------------------------------

BUG_REPORT_MAX_WORDS = 1000


def create_bug_report(user_id: Optional[str], body: str) -> dict:
    words = body.split()
    if len(words) > BUG_REPORT_MAX_WORDS:
        # Enforced here (server-side), not just in the frontend form -- a
        # client-only limit is trivially bypassed by anyone calling the API
        # directly.
        body = " ".join(words[:BUG_REPORT_MAX_WORDS])
    with get_pool().connection() as conn:
        return conn.execute(
            """INSERT INTO bug_reports (user_id, body) VALUES (%s, %s)
               RETURNING id, user_id, body, created_at, status""",
            (user_id, body),
        ).fetchone()


def list_bug_reports() -> list[dict]:
    with get_pool().connection() as conn:
        return conn.execute(
            "SELECT id, user_id, body, created_at, status FROM bug_reports ORDER BY created_at DESC"
        ).fetchall()


def set_bug_report_status(report_id: str, status: str) -> None:
    with get_pool().connection() as conn:
        conn.execute("UPDATE bug_reports SET status = %s WHERE id = %s", (status, report_id))


# --- Admin audit log ---------------------------------------------------


def audit(actor_user_id: Optional[str], action: str, target: Optional[str] = None, details: Optional[dict] = None) -> None:
    with get_pool().connection() as conn:
        conn.execute(
            "INSERT INTO admin_audit_log (actor_user_id, action, target, details) VALUES (%s, %s, %s, %s)",
            (actor_user_id, action, target, json.dumps(details) if details else None),
        )


def list_audit_log(limit: int = 500) -> list[dict]:
    """Newest-first, for the admin console's audit-log view -- viewable by
    every admin (this route has no per-admin filtering, unlike
    ownership-scoped data), never mutable (see db.py's
    admin_audit_log_no_update_delete/no_truncate triggers -- there is
    deliberately no update/delete function in this module for this
    table)."""
    with get_pool().connection() as conn:
        return conn.execute(
            "SELECT id, actor_user_id, action, target, details, created_at "
            "FROM admin_audit_log ORDER BY created_at DESC LIMIT %s",
            (limit,),
        ).fetchall()


# --- App config (admin-tunable quotas etc.) ---------------------------


def get_app_config(key: str, default=None):
    with get_pool().connection() as conn:
        row = conn.execute("SELECT value FROM app_config WHERE key = %s", (key,)).fetchone()
    return row["value"] if row else default


def set_app_config(key: str, value, updated_by: Optional[str] = None) -> None:
    with get_pool().connection() as conn:
        conn.execute(
            """INSERT INTO app_config (key, value, updated_by) VALUES (%s, %s, %s)
               ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, updated_at = now(), updated_by = EXCLUDED.updated_by""",
            (key, json.dumps(value), updated_by),
        )
