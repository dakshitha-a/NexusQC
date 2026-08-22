"""Connection pool + schema for the identity/ownership/admin Postgres
database -- users, sessions, invite tokens, bug reports, admin audit log,
per-job/thread ownership index, and admin-tunable app config. This is a
DIFFERENT database concern from app/agent/graph.py's checkpointer: that one
stores conversation/job *content* (kept exactly where it already lived --
files + the LangGraph checkpoint tables) and can point at the same physical
Postgres instance via the same QC_AGENT_DATABASE_URL, but this module's
tables are unrelated to LangGraph's own checkpoint/writes tables and never
touched by langgraph-checkpoint-postgres's own `.setup()`.

No ORM/migration framework (SQLAlchemy, Alembic) -- plain psycopg and a
single idempotent `CREATE TABLE IF NOT EXISTS` schema, matching this
project's established preference for the smallest dependency that does the
job (see CLAUDE.md's Celery-vs-JobManager discussion for the same
reasoning). A handful of tables in a single-admin-managed deployment don't
need a migration framework; if the schema ever needs a real migration path,
that's a deliberate future decision, not a default to reach for now.
"""
from __future__ import annotations

import threading
from typing import Optional

from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from app.config import DATABASE_POOL_MAX_SIZE, DATABASE_URL

_SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    email TEXT UNIQUE NOT NULL,
    username TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    first_name TEXT NOT NULL DEFAULT '',
    last_name TEXT NOT NULL DEFAULT '',
    role TEXT NOT NULL DEFAULT 'user' CHECK (role IN ('user', 'admin')),
    is_active BOOLEAN NOT NULL DEFAULT true,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_login_at TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS invite_tokens (
    token TEXT PRIMARY KEY,
    created_by UUID REFERENCES users(id) ON DELETE SET NULL,
    role TEXT NOT NULL DEFAULT 'user' CHECK (role IN ('user', 'admin')),
    email_hint TEXT,
    expires_at TIMESTAMPTZ NOT NULL,
    redeemed_by UUID REFERENCES users(id) ON DELETE SET NULL,
    redeemed_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    revoked_at TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS sessions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    issued_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    expires_at TIMESTAMPTZ NOT NULL,
    revoked BOOLEAN NOT NULL DEFAULT false,
    user_agent TEXT
);
CREATE INDEX IF NOT EXISTS sessions_user_id_idx ON sessions(user_id);

CREATE TABLE IF NOT EXISTS bug_reports (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID REFERENCES users(id) ON DELETE SET NULL,
    body TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    status TEXT NOT NULL DEFAULT 'open' CHECK (status IN ('open', 'closed')),
    -- Archived is a nullable timestamp rather than a third `status` value on
    -- purpose. Widening that CHECK against an already-deployed database needs
    -- a DROP CONSTRAINT / ADD CONSTRAINT pair, which the ADD COLUMN IF NOT
    -- EXISTS idiom below does not cover and which would run inside the same
    -- all-or-nothing execute on every process start. It also composes better:
    -- a report can be closed AND archived, which a single status column
    -- cannot express.
    archived_at TIMESTAMPTZ
);

-- Screenshots attached to a bug report. The file itself lives on disk under
-- DATA_DIR/bug_reports/<report_id>/; only the metadata is here.
--
-- ON DELETE CASCADE, unlike bug_reports' own user_id (SET NULL): a report
-- outlives its reporter deliberately, but an attachment has no meaning
-- without the report it belongs to. Deleting the row is not enough on its own
-- -- models.delete_bug_report removes the directory first, because Postgres
-- cannot cascade into the filesystem.
CREATE TABLE IF NOT EXISTS bug_report_attachments (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    report_id UUID NOT NULL REFERENCES bug_reports(id) ON DELETE CASCADE,
    -- Generated server-side. The client-supplied name is attacker-controlled
    -- and is kept in original_name for display only, never as a path segment.
    stored_name TEXT NOT NULL,
    original_name TEXT NOT NULL,
    content_type TEXT NOT NULL,
    size_bytes BIGINT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS bug_report_attachments_report_idx
    ON bug_report_attachments(report_id);

-- actor_user_id deliberately carries NO foreign key to users(id), and
-- actor_username records who the actor was at the time so a row stays
-- readable once that account is gone.
--
-- It did have one, ON DELETE SET NULL, and that was a real bug: the
-- immutability trigger below rejects UPDATE, so Postgres's own cascade --
-- `UPDATE admin_audit_log SET actor_user_id = NULL` -- was rejected too,
-- and the whole transaction aborted. Any user who had ever been the actor
-- of an audited action therefore could not be deleted at all. That
-- included ordinary users, not just admins: `purge_own_data` is a
-- self-service action logged with the user as actor, so purging your own
-- data quietly made your account undeletable, surfacing as a 500 from
-- DELETE /api/admin/users/{id}.
--
-- The two were mutually exclusive by construction and one had to go. The
-- trigger is the one carrying the guarantee this table exists for, and
-- nulling the actor is the wrong behavior for an audit log anyway: "who
-- purged every job" becoming NULL destroys the record at exactly the
-- moment it matters most, which is after that account is gone. Keeping a
-- bare uuid with no row to resolve is the correct trade -- the actor is
-- still identified, and list_audit_log has never assumed the user row
-- exists.
CREATE TABLE IF NOT EXISTS admin_audit_log (
    id BIGSERIAL PRIMARY KEY,
    actor_user_id UUID,
    actor_username TEXT,
    action TEXT NOT NULL,
    target TEXT,
    details JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Immutable admin action history, enforced at the database level (not
-- just "no route happens to expose an update/delete") -- every admin
-- config change and every storage purge is recorded here (see
-- server/routes/admin.py) specifically so admins can trust it as a real
-- record of what happened, viewable by every admin, that no admin
-- (including a compromised or buggy admin session) can quietly edit or
-- erase after the fact. A BEFORE-trigger on both UPDATE and DELETE covers
-- row-level tampering; TRUNCATE is a separate statement-level event in
-- Postgres that a row-level trigger does NOT catch, so a second
-- statement-level trigger closes that specific gap too.
--
-- Nothing disables this trigger any more. server/admin_cli.py's reset-all
-- used to, narrowly, because deleting every user forced the FK
-- nullification described above; with the foreign key gone there is no
-- longer any legitimate write to this table other than an INSERT, so the
-- trigger holds unconditionally.
CREATE OR REPLACE FUNCTION admin_audit_log_immutable() RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION 'admin_audit_log is append-only -- % is not permitted', TG_OP;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS admin_audit_log_no_update_delete ON admin_audit_log;
CREATE TRIGGER admin_audit_log_no_update_delete
    BEFORE UPDATE OR DELETE ON admin_audit_log
    FOR EACH ROW EXECUTE FUNCTION admin_audit_log_immutable();

DROP TRIGGER IF EXISTS admin_audit_log_no_truncate ON admin_audit_log;
CREATE TRIGGER admin_audit_log_no_truncate
    BEFORE TRUNCATE ON admin_audit_log
    FOR EACH STATEMENT EXECUTE FUNCTION admin_audit_log_immutable();

-- kind IN ('thread', 'job', 'upload'). Deliberately not a foreign key to
-- any job/thread/upload table -- those live as files (data/jobs/<id>/,
-- data/threads.json, data/geometry_uploads/<owner>/), not Postgres rows;
-- this index is the only place ownership is recorded, looked up by (kind,
-- resource_id) from the file-reading route code.
CREATE TABLE IF NOT EXISTS ownership_index (
    kind TEXT NOT NULL CHECK (kind IN ('thread', 'job', 'upload', 'plot')),
    resource_id TEXT NOT NULL,
    owner_user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (kind, resource_id)
);
CREATE INDEX IF NOT EXISTS ownership_index_owner_idx ON ownership_index(owner_user_id);

CREATE TABLE IF NOT EXISTS app_config (
    key TEXT PRIMARY KEY,
    value JSONB NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_by UUID REFERENCES users(id) ON DELETE SET NULL
);

-- Idempotent column additions, applied on every get_pool() call.
--
-- These exist because CREATE TABLE IF NOT EXISTS is a silent no-op against a
-- database where the table already exists: editing a table body above does
-- NOT reach any already-deployed database. Every column added after a table
-- first shipped therefore needs its own ALTER here, in addition to being
-- written into the CREATE TABLE above for the benefit of fresh installs.
-- ADD COLUMN IF NOT EXISTS is idempotent (Postgres 9.6+), matching the
-- re-runnable style the audit-log trigger block above already uses.
--
-- Note the blast radius: this whole string is one conn.execute() inside
-- get_pool(), so a malformed statement here fails EVERY database-backed
-- route, not just the feature it belongs to.
ALTER TABLE invite_tokens ADD COLUMN IF NOT EXISTS revoked_at TIMESTAMPTZ;
ALTER TABLE bug_reports ADD COLUMN IF NOT EXISTS archived_at TIMESTAMPTZ;
ALTER TABLE users ADD COLUMN IF NOT EXISTS first_name TEXT NOT NULL DEFAULT '';
ALTER TABLE users ADD COLUMN IF NOT EXISTS last_name TEXT NOT NULL DEFAULT '';
ALTER TABLE admin_audit_log ADD COLUMN IF NOT EXISTS actor_username TEXT;

-- Removes the admin_audit_log -> users foreign key on an already-deployed
-- database; see that table's own comment above for why it cannot coexist
-- with the immutability trigger. Named explicitly because the constraint
-- was created by inline REFERENCES syntax, so Postgres generated the name.
-- IF EXISTS is load-bearing rather than defensive: a deployment created
-- after this change takes the CREATE TABLE body above, which never adds
-- the constraint, and this statement runs on every startup regardless.
-- Deliberately NOT backfilling actor_username on existing rows -- rows
-- written before this change genuinely did not capture one, and inventing
-- it from a users row that may since have been deleted or reused would
-- put a guess into an append-only record.
ALTER TABLE admin_audit_log DROP CONSTRAINT IF EXISTS admin_audit_log_actor_user_id_fkey;

-- Widens ownership_index's kind CHECK constraint to admit 'upload'
-- (Phase 3's geometry/blind-input uploads store) and 'plot' (the saved
-- plot records in app/plots/store.py) -- editing the CHECK clause in the
-- CREATE TABLE above only reaches a fresh install; an already-deployed
-- database keeps its original constraint until this ALTER runs. DROP +
-- re-ADD is the standard idempotent pattern for a CHECK constraint
-- (there's no ADD CONSTRAINT IF NOT EXISTS in Postgres); safe to run on
-- every startup since the constraint's brief absence between the two
-- statements is inside one already-serialized DDL execution, not a window
-- any other query can observe.
ALTER TABLE ownership_index DROP CONSTRAINT IF EXISTS ownership_index_kind_check;
ALTER TABLE ownership_index ADD CONSTRAINT ownership_index_kind_check
    CHECK (kind IN ('thread', 'job', 'upload', 'plot'));
"""

_pool: Optional[ConnectionPool] = None
_pool_lock = threading.Lock()


def get_pool() -> ConnectionPool:
    """Lazily builds and caches the one process-wide connection pool for
    the auth/admin database. Callers get a connection via `with
    get_pool().connection() as conn:`, matching psycopg_pool's own idiom --
    this module never hands out a bare Connection to keep a single acquire/
    release pattern everywhere auth code touches the database."""
    global _pool
    if _pool is None:
        with _pool_lock:
            if _pool is None:
                if not DATABASE_URL:
                    raise RuntimeError(
                        "app.auth.db.get_pool() called with QC_AGENT_DATABASE_URL unset -- "
                        "auth requires Postgres; this is only reachable in the containerized "
                        "deployment, not the local-dev SqliteSaver-only workflow."
                    )
                pool = ConnectionPool(
                    DATABASE_URL,
                    min_size=1,
                    max_size=DATABASE_POOL_MAX_SIZE,
                    kwargs={"autocommit": True, "row_factory": dict_row},
                )
                with pool.connection() as conn:
                    conn.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto")  # gen_random_uuid()
                    conn.execute(_SCHEMA)
                _pool = pool
    return _pool


def reset_pool_for_testing() -> None:
    """Closes and drops the cached pool so a fresh get_pool() call rebuilds
    it against whatever DATABASE_URL is current -- used by tests that need
    a clean pool against a scratch database, never called from app code."""
    global _pool
    with _pool_lock:
        if _pool is not None:
            _pool.close()
            _pool = None
