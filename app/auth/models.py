"""Plain CRUD functions against the tables in app/auth/db.py's schema. No
ORM (see db.py's module docstring for why) -- each function is a short,
direct SQL statement, matching the rest of this codebase's preference for
explicit code over a framework layer for a handful of simple tables.
"""
from __future__ import annotations

import json
import secrets
import shutil
import string
from datetime import datetime, timedelta, timezone
from typing import Optional

from psycopg import errors

from app.auth.db import get_pool
from app.auth.security import hash_password, verify_password
from app.config import SESSION_TTL_SECONDS


def _now() -> datetime:
    return datetime.now(timezone.utc)


# --- Users -------------------------------------------------------------


def create_user(
    email: str, username: str, password: str, first_name: str, last_name: str, role: str = "user"
) -> dict:
    with get_pool().connection() as conn:
        row = conn.execute(
            """INSERT INTO users (email, username, password_hash, first_name, last_name, role)
               VALUES (%s, %s, %s, %s, %s, %s)
               RETURNING id, email, username, first_name, last_name, role, is_active, created_at""",
            (email, username, hash_password(password), first_name, last_name, role),
        ).fetchone()
    return row


def get_user_by_id(user_id: str) -> Optional[dict]:
    with get_pool().connection() as conn:
        return conn.execute(
            "SELECT id, email, username, password_hash, first_name, last_name, role, "
            "       is_active, created_at, last_login_at "
            "FROM users WHERE id = %s",
            (user_id,),
        ).fetchone()


def get_user_by_login(email_or_username: str) -> Optional[dict]:
    with get_pool().connection() as conn:
        return conn.execute(
            "SELECT id, email, username, password_hash, first_name, last_name, role, "
            "       is_active, created_at, last_login_at "
            "FROM users WHERE email = %s OR username = %s",
            (email_or_username, email_or_username),
        ).fetchone()


# A fixed, valid argon2id hash with no real corresponding password --
# verify_login runs a verification against THIS when the account lookup
# itself comes back empty, purely to burn the same argon2 cost the
# known-user branch already pays. Without this, an unknown username
# short-circuited before ever calling verify_password at all, which is a
# real, measurable timing side-channel (confirmed empirically: ~78ms
# median delta between an unknown username and a known one with a wrong
# password -- argon2 verification is exactly that expensive, and skipping
# it is exactly that fast) that lets a caller distinguish "no such
# account" from "wrong password" by response latency alone, undermining
# this function's own stated goal of not leaking that distinction.
_DUMMY_PASSWORD_HASH = hash_password("dummy-password-never-used-for-real-login-timing-parity-only")


def verify_login(email_or_username: str, password: str) -> Optional[dict]:
    """Returns the user row on success, None on bad credentials OR an
    inactive account -- deliberately the same outcome for both, so a
    deactivated user can't distinguish "wrong password" from "your account
    was disabled" through the login form's response. Also constant-time
    with respect to account existence (see _DUMMY_PASSWORD_HASH above) --
    an unknown username still pays argon2's real verification cost against
    a dummy hash, rather than returning near-instantly."""
    user = get_user_by_login(email_or_username)
    if user is None or not user["is_active"]:
        verify_password(password, _DUMMY_PASSWORD_HASH)
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
            "SELECT id, email, username, first_name, last_name, role, is_active, "
            "       created_at, last_login_at "
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
    """Deliberately counts EVERY admin row, active or not -- this is only
    ever consulted by server/admin_cli.py's bootstrap_admin() to decide
    whether it's safe to mint an unauthenticated first admin, and that
    decision needs to be "does an admin account exist at all", not "is one
    currently active". Filtering on is_active here used to mean a
    deactivated-but-not-deleted sole admin let bootstrap-admin run again
    and mint a second, unauthenticated admin. This is no longer only
    reachable via direct DB access: PATCH /api/admin/users/{id} can now
    deactivate an account, which makes the is_active-blind count here
    load-bearing rather than merely defensive.

    See count_active_admins() for the separate question the admin routes
    ask, which is genuinely about who can still log in."""
    with get_pool().connection() as conn:
        row = conn.execute("SELECT count(*) AS n FROM users WHERE role = 'admin'").fetchone()
    return row["n"]


def count_active_admins() -> int:
    """Admins who can actually still log in -- deliberately the opposite
    filtering choice from count_admins() above, because it answers a
    different question.

    count_admins() asks "does an admin account exist at all" (bootstrap
    safety). This asks "would this deletion or deactivation leave nobody
    able to administer the deployment", which is the lockout the admin
    routes guard against. A deactivated admin is not a usable one:
    app/auth/deps.py's get_current_user rejects an inactive user on every
    request, and verify_login refuses them outright."""
    with get_pool().connection() as conn:
        row = conn.execute(
            "SELECT count(*) AS n FROM users WHERE role = 'admin' AND is_active"
        ).fetchone()
    return row["n"]


def set_user_active(user_id: str, is_active: bool) -> Optional[dict]:
    """Suspends or restores an account without destroying anything it owns.

    This is the non-destructive alternative to delete_user(): deleting an
    account also purges every job, KB source and conversation it owns from
    disk (see purge_user_data), which is unrecoverable. Deactivation takes
    effect immediately even for a session that is already open, because
    get_current_user re-reads the user row on every single request rather
    than trusting the JWT's claims."""
    with get_pool().connection() as conn:
        return conn.execute(
            "UPDATE users SET is_active = %s WHERE id = %s "
            "RETURNING id, email, username, first_name, last_name, role, is_active, "
            "          created_at, last_login_at",
            (is_active, user_id),
        ).fetchone()


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


def register_with_invite_token(
    token: str, email: str, username: str, password: str, first_name: str, last_name: str
) -> dict:
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
    rolls back, then re-reads the now-redeemed row and correctly fails.

    That lock only covers the TOKEN row, not username/email uniqueness --
    the `existing` pre-check below is a plain, unlocked SELECT under
    Postgres's default READ COMMITTED isolation, so two concurrent
    registrations using DIFFERENT (both valid) tokens but the SAME email
    can both pass it before either commits. The `users.email`/`.username`
    UNIQUE constraints still correctly reject the loser at INSERT time --
    but as a raw psycopg IntegrityError, not an InviteTokenError, so it
    used to propagate straight out of this function as an unhandled
    exception (confirmed empirically: the losing request came back as a
    bare 500, not a clean 4xx). Caught here and translated to the same
    InviteTokenError the route layer already knows how to map to a 400."""
    with get_pool().connection() as conn:
        try:
            with conn.transaction():
                token_row = conn.execute(
                    "SELECT token, role, redeemed_by, expires_at, revoked_at "
                    "FROM invite_tokens WHERE token = %s FOR UPDATE",
                    (token,),
                ).fetchone()
                # revoked_at is checked in the SAME branch as already-redeemed,
                # deliberately sharing one generic message: reporting "this
                # invite was revoked" separately would turn this endpoint into
                # an oracle distinguishing a token that never existed from one
                # that did, which the original already-used wording avoids.
                # This check is the whole point of revocation -- without it,
                # revoking would update a column the UI renders while the token
                # still happily creates accounts.
                if (
                    token_row is None
                    or token_row["redeemed_by"] is not None
                    or token_row["revoked_at"] is not None
                ):
                    raise InviteTokenError("invalid or already-used invite token")
                if token_row["expires_at"] <= _now():
                    raise InviteTokenError("invite token has expired")
                existing = conn.execute(
                    "SELECT id FROM users WHERE email = %s OR username = %s", (email, username)
                ).fetchone()
                if existing is not None:
                    raise InviteTokenError("email or username already registered")
                user = conn.execute(
                    """INSERT INTO users (email, username, password_hash, first_name, last_name, role)
                       VALUES (%s, %s, %s, %s, %s, %s)
                       RETURNING id, email, username, first_name, last_name, role, is_active, created_at""",
                    (email, username, hash_password(password), first_name, last_name, token_row["role"]),
                ).fetchone()
                conn.execute(
                    "UPDATE invite_tokens SET redeemed_by = %s, redeemed_at = now() WHERE token = %s",
                    (user["id"], token),
                )
        except errors.UniqueViolation as exc:
            raise InviteTokenError("email or username already registered") from exc
    return user


def list_invite_tokens() -> list[dict]:
    """Every invite, newest first, for the admin console's invites table.

    The two LEFT JOINs resolve created_by/redeemed_by into usernames and full
    names: the raw UUIDs are useless in a table, and email_hint is optional
    and unverified so it can't stand in for "who actually redeemed this". The
    UUID columns are kept alongside the usernames because
    tests/backend/p1_04_invite_lifecycle.py asserts on redeemed_by directly."""
    with get_pool().connection() as conn:
        return conn.execute(
            "SELECT t.token, t.created_by, t.role, t.email_hint, t.expires_at, "
            "       t.redeemed_by, t.redeemed_at, t.created_at, t.revoked_at, "
            "       c.username AS created_by_username, "
            "       c.first_name AS created_by_first_name, "
            "       c.last_name AS created_by_last_name, "
            "       r.username AS redeemed_by_username, "
            "       r.first_name AS redeemed_by_first_name, "
            "       r.last_name AS redeemed_by_last_name "
            "FROM invite_tokens t "
            "LEFT JOIN users c ON c.id = t.created_by "
            "LEFT JOIN users r ON r.id = t.redeemed_by "
            "ORDER BY t.created_at DESC"
        ).fetchall()


def get_invite_token(token: str) -> Optional[dict]:
    with get_pool().connection() as conn:
        return conn.execute(
            "SELECT token, role, email_hint, expires_at, redeemed_by, redeemed_at, "
            "       created_at, revoked_at "
            "FROM invite_tokens WHERE token = %s",
            (token,),
        ).fetchone()


def revoke_invite_token(token: str) -> Optional[dict]:
    """Soft-revokes an unredeemed invite, returning the updated row.

    Returns None when nothing was updated, which covers both "no such token"
    and "already redeemed" -- the caller distinguishes those with a follow-up
    get_invite_token() so it can answer 404 vs 400 correctly.

    COALESCE keeps a double-revoke idempotent (the original revoked_at is
    preserved rather than being bumped forward) without needing a second
    round trip to check first. The redeemed_by IS NULL guard is what makes
    revoking a redeemed invite a no-op: that account already exists, so
    revocation would be meaningless rather than merely late."""
    with get_pool().connection() as conn:
        return conn.execute(
            "UPDATE invite_tokens SET revoked_at = COALESCE(revoked_at, now()) "
            "WHERE token = %s AND redeemed_by IS NULL "
            "RETURNING token, role, email_hint, expires_at, redeemed_by, "
            "          redeemed_at, created_at, revoked_at",
            (token,),
        ).fetchone()


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
    """Every report, newest first, with its reporter and its attachments.

    The LEFT JOIN is the point: this used to be a bare SELECT over bug_reports
    with no join at all, so the admin inbox could not show who had filed
    anything -- in deliberate contrast to list_invite_tokens() above, which
    joins twice for exactly that reason. bug_reports.user_id is ON DELETE SET
    NULL, so a report outlives its reporter and the username comes back NULL;
    callers render that as "deleted user", not as blank.
    """
    with get_pool().connection() as conn:
        return conn.execute(
            """
            SELECT r.id, r.user_id, r.body, r.created_at, r.status, r.archived_at,
                   u.username AS reporter_username,
                   COALESCE(
                       (SELECT json_agg(json_build_object(
                            'id', a.id, 'original_name', a.original_name,
                            'content_type', a.content_type, 'size_bytes', a.size_bytes)
                            ORDER BY a.created_at)
                        FROM bug_report_attachments a WHERE a.report_id = r.id),
                       '[]'::json
                   ) AS attachments
            FROM bug_reports r
            LEFT JOIN users u ON u.id = r.user_id
            ORDER BY r.created_at DESC
            """
        ).fetchall()


def set_bug_report_status(report_id: str, status: str) -> None:
    with get_pool().connection() as conn:
        conn.execute("UPDATE bug_reports SET status = %s WHERE id = %s", (status, report_id))


def set_bug_report_archived(report_id: str, archived: bool) -> None:
    """Archiving hides a report from the default inbox without destroying it.
    Independent of open/closed, so a report can be both."""
    with get_pool().connection() as conn:
        conn.execute(
            "UPDATE bug_reports SET archived_at = %s WHERE id = %s",
            (_now() if archived else None, report_id),
        )


def get_bug_report_attachment(attachment_id: str) -> Optional[dict]:
    """One attachment plus the id of the user who filed its report -- the
    serving route needs the latter to decide access, and must not have to
    guess it from an ownership index that has no row for this resource."""
    with get_pool().connection() as conn:
        return conn.execute(
            """SELECT a.id, a.report_id, a.stored_name, a.original_name, a.content_type,
                      a.size_bytes, r.user_id AS reporter_user_id
               FROM bug_report_attachments a
               JOIN bug_reports r ON r.id = a.report_id
               WHERE a.id = %s""",
            (attachment_id,),
        ).fetchone()


def add_bug_report_attachment(
    report_id: str, stored_name: str, original_name: str, content_type: str, size_bytes: int
) -> dict:
    with get_pool().connection() as conn:
        return conn.execute(
            """INSERT INTO bug_report_attachments
                   (report_id, stored_name, original_name, content_type, size_bytes)
               VALUES (%s, %s, %s, %s, %s)
               RETURNING id, report_id, original_name, content_type, size_bytes""",
            (report_id, stored_name, original_name, content_type, size_bytes),
        ).fetchone()


def delete_bug_report(report_id: str) -> None:
    """Deletes the report, its attachment rows (ON DELETE CASCADE) and the
    files themselves.

    The directory is removed BEFORE the row, because after the delete there is
    nothing left to tell anyone those files exist -- Postgres cannot cascade
    into the filesystem, and an orphaned directory under DATA_DIR is counted by
    no quota and reclaimed by no purge.

    Note this belongs to report deletion and NOT to purge_user_data: reports
    are ON DELETE SET NULL and server/admin_cli.py's reset-all preserves them
    deliberately, so an attachment must not vanish when its reporter's account
    is deleted while the report itself survives.
    """
    from app.config import BUG_REPORTS_DIR

    directory = BUG_REPORTS_DIR / str(report_id)
    if directory.is_dir():
        shutil.rmtree(directory, ignore_errors=True)
    with get_pool().connection() as conn:
        conn.execute("DELETE FROM bug_reports WHERE id = %s", (report_id,))


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
