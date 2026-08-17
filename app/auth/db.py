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

CREATE TABLE IF NOT EXISTS admin_audit_log (
    id BIGSERIAL PRIMARY KEY,
    actor_user_id UUID REFERENCES users(id) ON DELETE SET NULL,
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
-- statement-level trigger closes that specific gap too. This does bind
-- server/admin_cli.py's reset-all (lockout recovery): see that function's
-- own comment for how it deliberately and narrowly disables this trigger
-- for the one FK-nullification step that needs it, rather than this
-- trigger being loosened to allow that in general.
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

-- kind IN ('thread', 'job'). Deliberately not a foreign key to any job/
-- thread table -- those live as files (data/jobs/<id>/, data/threads.json),
-- not Postgres rows; this index is the only place ownership is recorded,
-- looked up by (kind, resource_id) from the file-reading route code.
CREATE TABLE IF NOT EXISTS ownership_index (
    kind TEXT NOT NULL CHECK (kind IN ('thread', 'job')),
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
