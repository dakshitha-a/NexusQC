"""Filesystem-local admin operations -- deliberately NOT web routes, per
the deployment requirement that these keep working even when no admin
account can log in through the app at all. Trust boundary is shell access
to the host running this (which already implies access to QC_AGENT_
DATABASE_URL/credentials) -- no additional in-app auth layer on top of
that would add real protection.

Usage:
    python -m server.admin_cli bootstrap-admin --email a@b.com --username admin
    python -m server.admin_cli reset-all --confirm
    python -m server.admin_cli reset-all --confirm --wipe-data
"""
from __future__ import annotations

import argparse
import getpass
import sys

from app.auth import models
from app.auth.db import get_pool
from app.config import DATA_DIR, DATABASE_URL


def _require_database_url() -> None:
    if not DATABASE_URL:
        print("QC_AGENT_DATABASE_URL is not set -- this command requires the auth/admin Postgres database.", file=sys.stderr)
        sys.exit(1)


def bootstrap_admin(email: str, username: str) -> None:
    """Creates the first admin account, bypassing the invite-token
    requirement -- the ONE place that bypass is permitted. Refuses if an
    admin already exists, so this can't be re-run to mint a second
    unauthenticated admin account later."""
    _require_database_url()
    get_pool()  # ensures schema exists before querying it
    if models.count_admins() > 0:
        print("An admin account already exists -- refusing to bootstrap another one this way. "
              "Use an existing admin's invite-token flow, or reset-all if all admins are locked out.", file=sys.stderr)
        sys.exit(1)
    password = getpass.getpass("Password for the new admin account: ")
    confirm = getpass.getpass("Confirm password: ")
    if password != confirm:
        print("Passwords did not match.", file=sys.stderr)
        sys.exit(1)
    if len(password) < 8:
        print("Password must be at least 8 characters.", file=sys.stderr)
        sys.exit(1)
    user = models.create_user(email, username, password, role="admin")
    print(f"Created admin account: {user['username']} <{user['email']}> ({user['id']})")


def reset_all(confirm: bool, wipe_data: bool) -> None:
    """Clears users/sessions/invite_tokens (lockout recovery -- run this
    when every admin account is locked out and there's no other way back
    in). Job/thread/KB data under data/ is preserved by default: losing
    account access shouldn't mean losing every user's computational
    results. Pass --wipe-data to also delete that -- a separate, explicit
    opt-in, not the default of a recovery command."""
    _require_database_url()
    if not confirm:
        print("Refusing to run without --confirm (this is destructive to all accounts).", file=sys.stderr)
        sys.exit(1)
    get_pool()
    with get_pool().connection() as conn:
        conn.execute("TRUNCATE sessions, invite_tokens, users CASCADE")
    print("Cleared all users, sessions, and invite tokens.")
    if wipe_data:
        import shutil
        for sub in ("jobs", "kb", "uploads", "molecules"):
            d = DATA_DIR / sub
            if d.exists():
                shutil.rmtree(d)
                d.mkdir(parents=True, exist_ok=True)
        threads_file = DATA_DIR / "threads.json"
        if threads_file.exists():
            threads_file.unlink()
        print("Also wiped job/thread/KB data under data/ (--wipe-data was passed).")
    else:
        print("Job/thread/KB data under data/ was left untouched. Pass --wipe-data to also clear it.")
    print("\nRun 'bootstrap-admin' next to create a fresh admin account.")


def main() -> None:
    parser = argparse.ArgumentParser(prog="python -m server.admin_cli")
    sub = parser.add_subparsers(dest="command", required=True)

    p_bootstrap = sub.add_parser("bootstrap-admin", help="Create the first admin account (only works if none exists yet)")
    p_bootstrap.add_argument("--email", required=True)
    p_bootstrap.add_argument("--username", required=True)

    p_reset = sub.add_parser("reset-all", help="Lockout recovery: clear all accounts/sessions/invite tokens")
    p_reset.add_argument("--confirm", action="store_true")
    p_reset.add_argument("--wipe-data", action="store_true", help="Also delete job/thread/KB data under data/ (default: preserved)")

    args = parser.parse_args()
    if args.command == "bootstrap-admin":
        bootstrap_admin(args.email, args.username)
    elif args.command == "reset-all":
        reset_all(args.confirm, args.wipe_data)


if __name__ == "__main__":
    main()
