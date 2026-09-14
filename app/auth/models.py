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
import uuid
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
                    "SELECT token, role, redeemed_at, expires_at, revoked_at "
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
                #
                # "Already redeemed" is read off redeemed_at, NOT redeemed_by.
                # redeemed_by is a foreign key declared ON DELETE SET NULL, so
                # deleting the account Postgres nulls it and the token looked
                # unspent again -- deleting a user handed their invite back,
                # and an admin invite resurrected that way minted another
                # admin until it expired. redeemed_at is a plain timestamp
                # that nothing cascades to, so it is the fact that survives
                # the account. redeemed_by stays for the audit trail, which
                # is what the invite list renders and the only record of how
                # an account came to exist.
                if (
                    token_row is None
                    or token_row["redeemed_at"] is not None
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
    round trip to check first. The redeemed_at IS NULL guard is what makes
    revoking a redeemed invite a no-op: that account already exists, so
    revocation would be meaningless rather than merely late.

    That guard reads redeemed_at rather than redeemed_by for the reason
    given in register_with_invite_token: redeemed_by is a foreign key that
    Postgres nulls when the account is deleted, so it stops being a record
    of whether the token was ever spent."""
    with get_pool().connection() as conn:
        return conn.execute(
            "UPDATE invite_tokens SET revoked_at = COALESCE(revoked_at, now()) "
            "WHERE token = %s AND redeemed_at IS NULL "
            "RETURNING token, role, email_hint, expires_at, redeemed_by, "
            "          redeemed_at, created_at, revoked_at",
            (token,),
        ).fetchone()


# --- Password reset tokens ----------------------------------------------
#
# This deployment has no mail server, so there is no "email me a link"
# self-service reset and pretending otherwise would be a dead end. Instead
# an admin issues a single-use token out of band and the person redeems it
# on the login screen. The admin never sees or chooses the password, which
# is the property that makes this better than handing out a temporary one.


class PasswordResetError(Exception):
    """Raised by redeem_password_reset_token for every rejection reason --
    unknown token, already used, revoked, expired, or a suspended account.
    One exception type for all of them on purpose: the route maps it to a
    single generic 400 so the endpoint cannot be used to tell a real token
    from a fake one, or an active account from a suspended one."""


def create_password_reset_token(created_by: Optional[str], user_id: str, ttl_hours: int = 2) -> dict:
    """Mints a reset token for `user_id`. Short-lived by default compared
    with an invite's 72 hours: an invite is mailed around and redeemed
    whenever someone gets to it, whereas a reset is handed over during a
    conversation with an admin who is waiting for it to be used."""
    token = _generate_token()
    expires_at = _now() + timedelta(hours=ttl_hours)
    with get_pool().connection() as conn:
        return conn.execute(
            """INSERT INTO password_reset_tokens (token, user_id, created_by, expires_at)
               VALUES (%s, %s, %s, %s)
               RETURNING token, user_id, created_by, expires_at, created_at""",
            (token, user_id, created_by, expires_at),
        ).fetchone()


def redeem_password_reset_token(token: str, new_password: str) -> dict:
    """Sets the password and marks the token spent, in ONE transaction.

    SELECT ... FOR UPDATE locks the token row for the duration, so two
    requests racing to redeem the same token cannot both pass the validity
    check -- the second blocks, then re-reads a row whose used_at is now
    set and is correctly refused. Same shape, and the same reason, as
    register_with_invite_token.

    Returns the user row. The caller is responsible for invalidating the
    account's existing sessions; that is a Redis concern and does not
    belong inside a database transaction."""
    with get_pool().connection() as conn:
        with conn.transaction():
            row = conn.execute(
                "SELECT token, user_id, used_at, expires_at, revoked_at "
                "FROM password_reset_tokens WHERE token = %s FOR UPDATE",
                (token,),
            ).fetchone()
            if row is None or row["used_at"] is not None or row["revoked_at"] is not None:
                raise PasswordResetError("invalid or already-used reset token")
            if row["expires_at"] <= _now():
                raise PasswordResetError("invalid or already-used reset token")
            user = conn.execute(
                "SELECT id, email, username, first_name, last_name, role, is_active "
                "FROM users WHERE id = %s",
                (row["user_id"],),
            ).fetchone()
            # A reset restores access to an account that is supposed to have
            # it. Restoring a SUSPENDED account is a separate decision an
            # admin makes deliberately, so a reset must not be a way around
            # it -- otherwise issuing one silently un-suspends someone.
            if user is None or not user["is_active"]:
                raise PasswordResetError("invalid or already-used reset token")
            conn.execute(
                "UPDATE users SET password_hash = %s WHERE id = %s",
                (hash_password(new_password), user["id"]),
            )
            conn.execute(
                "UPDATE password_reset_tokens SET used_at = now() WHERE token = %s",
                (token,),
            )
            # Every other still-outstanding token for this account dies with
            # the reset. Two admins each issuing one, or an admin issuing a
            # second because the first went astray, must not leave a spare
            # key lying around after the account has been recovered.
            conn.execute(
                "UPDATE password_reset_tokens SET revoked_at = COALESCE(revoked_at, now()) "
                "WHERE user_id = %s AND used_at IS NULL AND revoked_at IS NULL",
                (user["id"],),
            )
    return user


def revoke_password_reset_token(token: str) -> Optional[dict]:
    """Soft-revokes an unused reset token. Returns None when nothing was
    updated, which covers both "no such token" and "already used" -- the
    caller distinguishes those the way the invite route does."""
    with get_pool().connection() as conn:
        return conn.execute(
            "UPDATE password_reset_tokens SET revoked_at = COALESCE(revoked_at, now()) "
            "WHERE token = %s AND used_at IS NULL "
            "RETURNING token, user_id, expires_at, used_at, created_at, revoked_at",
            (token,),
        ).fetchone()


def get_password_reset_token(token: str) -> Optional[dict]:
    with get_pool().connection() as conn:
        return conn.execute(
            "SELECT token, user_id, expires_at, used_at, created_at, revoked_at "
            "FROM password_reset_tokens WHERE token = %s",
            (token,),
        ).fetchone()


def list_password_reset_tokens() -> list[dict]:
    """Newest first, with both usernames resolved -- the admin console shows
    who a token is for and who issued it, the same way the invite list does."""
    with get_pool().connection() as conn:
        return conn.execute(
            "SELECT t.token, t.user_id, t.created_by, t.expires_at, t.used_at, "
            "       t.created_at, t.revoked_at, "
            "       u.username AS for_username, "
            "       c.username AS created_by_username "
            "FROM password_reset_tokens t "
            "LEFT JOIN users u ON u.id = t.user_id "
            "LEFT JOIN users c ON c.id = t.created_by "
            "ORDER BY t.created_at DESC"
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


def revoke_sessions_for_user(user_id: str) -> None:
    """Marks every one of a user's live sessions revoked. Used when an account
    is deactivated or deleted, where "this person is out" is the whole point
    and leaving rows unmarked makes the table say the opposite."""
    with get_pool().connection() as conn:
        conn.execute(
            "UPDATE sessions SET revoked = true WHERE user_id = %s AND NOT revoked",
            (user_id,),
        )


def delete_expired_sessions() -> int:
    """Removes rows that are past their expiry, and revoked rows older than a
    day. Returns how many went.

    R-088: `revoked` and `expires_at` both existed and nothing ever wrote the
    first or acted on the second, so the sessions table only ever grew for the
    life of a deployment. Rows do cascade away with their user, which is why
    this was slow rather than unbounded, but an account that logs in daily for
    a year leaves a year of rows behind whether or not it is ever deleted.

    A revoked row is kept for a day rather than deleted at once, so that "this
    session was ended" is answerable for a little while after the fact. An
    expired row answers nothing: the token it describes stopped working when
    it expired."""
    with get_pool().connection() as conn:
        cur = conn.execute(
            "DELETE FROM sessions WHERE expires_at < %s "
            "OR (revoked AND issued_at < %s)",
            (_now(), _now() - timedelta(days=1)),
        )
        return cur.rowcount or 0


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


def _is_uuid(value: str) -> bool:
    """Whether a string can be a user id at all.

    `owner_user_id` is a uuid column, so Postgres refuses a comparison against
    anything that is not one and psycopg raises InvalidTextRepresentation
    rather than returning no rows. That is the right behaviour for a WRITE,
    where a malformed id means a bug worth hearing about. For a READ it turns
    "what does this user own" into a 500 for a caller who is entitled to the
    answer "nothing".

    It stopped being hypothetical when `purge_own_data` started asking for the
    caller's projects before anything else (R-087). `dz_01_self_purge` calls it
    with a deliberately impossible id to prove the danger-zone purge is a
    no-op for someone with nothing, and the call raised out of psycopg
    instead. A purge route answering 500 with a database error in it is the
    same class of leak R-083 closed on the orbital-render path.
    """
    try:
        uuid.UUID(str(value))
    except (ValueError, AttributeError, TypeError):
        return False
    return True


def list_owned(kind: str, owner_user_id: str) -> list[str]:
    if not _is_uuid(owner_user_id):
        return []
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


# --- Sharing ---------------------------------------------------------------

# Both bounds are deliberate. Below MIN_CHARS a query is an enumeration of the
# deployment rather than a lookup, and the picker refuses to run at all; the
# LIMIT then caps what any single query can return. Neither is a security
# boundary on its own -- a determined caller can walk the alphabet -- they
# exist so that the ordinary shape of the feature is "find the person you
# already meant" rather than "download the roster".
USER_SEARCH_MIN_CHARS = 2
USER_SEARCH_LIMIT = 20


def search_users(query: str, exclude_user_id: Optional[str] = None,
                 limit: int = USER_SEARCH_LIMIT) -> list[dict]:
    """Prefix lookup over username and first/last name for the share picker.

    The projection is the narrow point of this function and the reason it
    exists at all rather than reusing something. get_user_by_id and
    get_user_by_login both SELECT password_hash, so neither can ever reach a
    client; server/routes/auth.py's _user_public still carries email and
    role, which a share picker has no business publishing to every other
    account on the deployment. What a picker needs is exactly enough to tell
    two colleagues apart, so: id, username, first and last name, nothing
    else.

    Inactive accounts are excluded (offering to a suspended user would
    create an inbox row nobody can ever accept) and so is the caller, who
    cannot share with themselves.

    ILIKE with no lower() index is a sequential scan, and that is the
    deliberate choice rather than an oversight: users is a lab-sized table
    (tens of rows, not millions), the query runs on a keystroke-debounced
    picker, and an expression index on a table this size would cost more to
    maintain and explain than it saves. Revisit if a deployment ever carries
    thousands of accounts.
    """
    q = (query or "").strip()
    if len(q) < USER_SEARCH_MIN_CHARS:
        return []
    # Escape LIKE's own wildcards so a query of "%" is a literal search for a
    # percent sign rather than a match against every row.
    esc = q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    pattern = f"{esc}%"
    sql = """SELECT id, username, first_name, last_name
               FROM users
              WHERE is_active = true
                AND (username ILIKE %s OR first_name ILIKE %s OR last_name ILIKE %s)"""
    params: list = [pattern, pattern, pattern]
    if exclude_user_id:
        sql += " AND id <> %s"
        params.append(exclude_user_id)
    sql += " ORDER BY username LIMIT %s"
    params.append(limit)
    with get_pool().connection() as conn:
        rows = conn.execute(sql, tuple(params)).fetchall()
    return [
        {
            "id": str(r["id"]),
            "username": r["username"],
            "first_name": r["first_name"],
            "last_name": r["last_name"],
        }
        for r in rows
    ]


_SHARE_COLUMNS = """s.share_id, s.kind, s.resource_id, s.from_user_id, s.to_user_id,
                    s.status, s.note, s.source_label, s.size_bytes, s.created_at,
                    s.resolved_at, s.copied_resource_id"""


def _share_row(r: dict) -> dict:
    return {
        "share_id": str(r["share_id"]),
        "kind": r["kind"],
        "resource_id": r["resource_id"],
        "from_user_id": str(r["from_user_id"]),
        "to_user_id": str(r["to_user_id"]),
        "status": r["status"],
        "note": r["note"],
        "source_label": r["source_label"],
        "size_bytes": r["size_bytes"],
        "created_at": r["created_at"].timestamp() if r["created_at"] else None,
        "resolved_at": r["resolved_at"].timestamp() if r["resolved_at"] else None,
        "copied_resource_id": r["copied_resource_id"],
        # Joined in for display so an inbox row can say who sent it without
        # the caller needing a second lookup -- and without exposing anything
        # search_users would not already have shown them.
        "from_username": r.get("from_username"),
        "from_first_name": r.get("from_first_name"),
        "from_last_name": r.get("from_last_name"),
        "to_username": r.get("to_username"),
    }


def create_share(kind: str, resource_id: str, from_user_id: str, to_user_id: str,
                 note: str = "", source_label: str = "", size_bytes: int = 0) -> dict:
    """Raises psycopg.errors.UniqueViolation if an identical offer is already
    pending -- see resource_shares_pending_idx. The route turns that into a
    409 rather than silently creating a duplicate inbox row."""
    with get_pool().connection() as conn:
        row = conn.execute(
            """INSERT INTO resource_shares
                   (kind, resource_id, from_user_id, to_user_id, note, source_label, size_bytes)
               VALUES (%s, %s, %s, %s, %s, %s, %s)
               RETURNING share_id, kind, resource_id, from_user_id, to_user_id, status,
                         note, source_label, size_bytes, created_at, resolved_at,
                         copied_resource_id""",
            (kind, resource_id, from_user_id, to_user_id, note, source_label, size_bytes),
        ).fetchone()
    return _share_row(row)


def get_share(share_id: str) -> Optional[dict]:
    with get_pool().connection() as conn:
        row = conn.execute(
            f"""SELECT {_SHARE_COLUMNS},
                       f.username AS from_username, f.first_name AS from_first_name,
                       f.last_name AS from_last_name, t.username AS to_username
                  FROM resource_shares s
                  JOIN users f ON f.id = s.from_user_id
                  JOIN users t ON t.id = s.to_user_id
                 WHERE s.share_id = %s""",
            (share_id,),
        ).fetchone()
    return _share_row(row) if row else None


def list_inbox(user_id: str, limit: int = 100) -> list[dict]:
    """Offers addressed to this user. Resolved rows are returned alongside
    pending ones so the flyout can show what was recently accepted or
    declined; the caller decides how to present them."""
    with get_pool().connection() as conn:
        rows = conn.execute(
            f"""SELECT {_SHARE_COLUMNS},
                       f.username AS from_username, f.first_name AS from_first_name,
                       f.last_name AS from_last_name, t.username AS to_username
                  FROM resource_shares s
                  JOIN users f ON f.id = s.from_user_id
                  JOIN users t ON t.id = s.to_user_id
                 WHERE s.to_user_id = %s AND s.status <> 'withdrawn'
              ORDER BY (s.status = 'pending') DESC, s.created_at DESC
                 LIMIT %s""",
            (user_id, limit),
        ).fetchall()
    return [_share_row(r) for r in rows]


def list_outbox(user_id: str, limit: int = 100) -> list[dict]:
    with get_pool().connection() as conn:
        rows = conn.execute(
            f"""SELECT {_SHARE_COLUMNS},
                       f.username AS from_username, f.first_name AS from_first_name,
                       f.last_name AS from_last_name, t.username AS to_username
                  FROM resource_shares s
                  JOIN users f ON f.id = s.from_user_id
                  JOIN users t ON t.id = s.to_user_id
                 WHERE s.from_user_id = %s
              ORDER BY (s.status = 'pending') DESC, s.created_at DESC
                 LIMIT %s""",
            (user_id, limit),
        ).fetchall()
    return [_share_row(r) for r in rows]


def set_share_status(share_id: str, status: str,
                     copied_resource_id: Optional[str] = None) -> Optional[dict]:
    """Resolves an offer, and only from 'pending'.

    The WHERE clause carries `status = 'pending'` so this is a compare-and-set
    rather than a blind UPDATE: two accept clicks racing each other, or an
    accept racing the sender's withdraw, leave exactly one winner and the
    loser gets None back. Without it the second caller would happily
    re-resolve a settled row and the accept path would copy the job twice.
    """
    with get_pool().connection() as conn:
        row = conn.execute(
            """UPDATE resource_shares
                  SET status = %s, resolved_at = now(),
                      copied_resource_id = COALESCE(%s, copied_resource_id)
                WHERE share_id = %s AND status = 'pending'
            RETURNING share_id, kind, resource_id, from_user_id, to_user_id, status,
                      note, source_label, size_bytes, created_at, resolved_at,
                      copied_resource_id""",
            (status, copied_resource_id, share_id),
        ).fetchone()
    return _share_row(row) if row else None


def count_pending_shares(user_id: str) -> int:
    with get_pool().connection() as conn:
        row = conn.execute(
            "SELECT count(*) AS n FROM resource_shares WHERE to_user_id = %s AND status = 'pending'",
            (user_id,),
        ).fetchone()
    return int(row["n"]) if row else 0


# --- Bug reports -----------------------------------------------------------

BUG_REPORT_MAX_WORDS = 1000


def create_bug_report(
    user_id: Optional[str],
    body: str,
    *,
    build_commit: Optional[str] = None,
    build_version: Optional[str] = None,
    user_agent: Optional[str] = None,
) -> dict:
    """Files a report. The build fields are the server's own stamp, passed in
    by the route from the api's environment; they say what was running when
    the bug was seen, which is the first thing a fix needs to know."""
    words = body.split()
    if len(words) > BUG_REPORT_MAX_WORDS:
        # Enforced here (server-side), not just in the frontend form -- a
        # client-only limit is trivially bypassed by anyone calling the API
        # directly.
        body = " ".join(words[:BUG_REPORT_MAX_WORDS])
    with get_pool().connection() as conn:
        return conn.execute(
            """INSERT INTO bug_reports (user_id, body, build_commit, build_version, user_agent)
               VALUES (%s, %s, %s, %s, %s)
               RETURNING id, user_id, body, created_at, status,
                         build_commit, build_version, user_agent""",
            (user_id, body, build_commit, build_version, user_agent),
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
                   r.build_commit, r.build_version, r.user_agent,
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


def get_bug_report(report_id: str) -> Optional[dict]:
    """One report by id, or None for a missing one AND for an id that is not
    a well-formed UUID.

    The parse is the same defence server/routes/shares.py's `_lookup_user`
    records: without it a hand-crafted request with a junk id reaches Postgres
    and raises InvalidTextRepresentation, which surfaces as a 500. That is a
    different error shape from a well-formed miss, and the difference tells a
    prober their input got further than it should have."""
    try:
        uuid.UUID(str(report_id))
    except (ValueError, AttributeError, TypeError):
        return None
    with get_pool().connection() as conn:
        return conn.execute(
            "SELECT id, user_id, body, created_at, status, archived_at "
            "FROM bug_reports WHERE id = %s",
            (str(report_id),),
        ).fetchone()


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


def bug_report_attachment_bytes_for_user(user_id: str) -> int:
    """Total attachment bytes across every report this account still has on
    file. R-052: attachments deliberately do not count against the reporter's
    storage quota, because a quota-blocked bug report is perverse, which left
    this route as the one write channel in the app with no ceiling of any
    kind. This is the number the ceiling is checked against."""
    try:
        uuid.UUID(str(user_id))
    except (ValueError, AttributeError, TypeError):
        return 0
    with get_pool().connection() as conn:
        row = conn.execute(
            "SELECT COALESCE(SUM(a.size_bytes), 0) AS total "
            "FROM bug_report_attachments a JOIN bug_reports r ON r.id = a.report_id "
            "WHERE r.user_id = %s",
            (str(user_id),),
        ).fetchone()
    return int((row or {}).get("total") or 0)


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
    """Appends one row. The actor's username is captured here, in the same
    statement, rather than resolved by a join at read time: this table has
    no foreign key to users (see db.py's comment on why it cannot have
    one), so an actor whose account is later deleted would otherwise read
    back as a bare uuid nobody can identify. A sub-select keeps it to the
    one round trip, and leaves the column NULL rather than failing the
    insert if the id resolves to nothing -- an audit row that records the
    action is worth more than one that was never written."""
    with get_pool().connection() as conn:
        conn.execute(
            "INSERT INTO admin_audit_log (actor_user_id, actor_username, action, target, details) "
            "VALUES (%s, (SELECT username FROM users WHERE id = %s), %s, %s, %s)",
            (actor_user_id, actor_user_id, action, target, json.dumps(details) if details else None),
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
            "SELECT id, actor_user_id, actor_username, action, target, details, created_at "
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
