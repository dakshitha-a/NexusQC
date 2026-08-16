"""Shared helpers for tests/backend/*.py -- plain httpx-based fixtures, no
test framework (this repo has no pytest; every backend script here is a
standalone invoke-and-print script run against a LIVE server, matching the
verification style CLAUDE.md documents for the rest of this codebase).

All test-created accounts are usernames prefixed `qatest_` so they're easy
to find and delete afterward (see cleanup_user/cleanup_all_qatest_users).
Never touches a real (non-qatest_) account.

Environment:
    QC_AGENT_TEST_BASE_URL   -- default https://127.0.0.1:8443
    QC_AGENT_TEST_ADMIN_USER / QC_AGENT_TEST_ADMIN_PASS
        -- credentials for an admin account these tests can use to mint
           invite tokens and clean up. Provisioned once by tests/backend/
           _00_bootstrap.py (or already exists if you're re-running against
           a stack that's already been bootstrapped).
"""
from __future__ import annotations

import os
import secrets
import string
import subprocess
import sys
import time
import uuid
from contextlib import contextmanager
from pathlib import Path

import httpx

BASE_URL = os.environ.get("QC_AGENT_TEST_BASE_URL", "https://127.0.0.1:8443")
ADMIN_USER = os.environ.get("QC_AGENT_TEST_ADMIN_USER", "qatest_admin")

_CREDS_FILE = Path(__file__).resolve().parent / ".admin_creds"
_COMPOSE_DIR = Path(__file__).resolve().parent.parent


def _default_admin_pass() -> str:
    if os.environ.get("QC_AGENT_TEST_ADMIN_PASS"):
        return os.environ["QC_AGENT_TEST_ADMIN_PASS"]
    if _CREDS_FILE.exists():
        return _CREDS_FILE.read_text().strip()
    return ""


ADMIN_PASS = _default_admin_pass()

QATEST_PREFIX = "qatest_"


def _origin() -> str:
    return BASE_URL


def new_client(**kwargs) -> httpx.Client:
    """A cookie-jar client pointed at the live stack. verify=False since
    the test stack uses a throwaway self-signed cert (see the plan's
    Environment bring-up section) -- never do this against a real
    deployment."""
    headers = {"Origin": _origin()}
    headers.update(kwargs.pop("headers", {}) or {})
    return httpx.Client(base_url=BASE_URL, verify=False, timeout=30.0, headers=headers, **kwargs)


def rand_suffix(n: int = 8) -> str:
    return "".join(secrets.choice(string.ascii_lowercase + string.digits) for _ in range(n))


def qatest_username() -> str:
    return f"{QATEST_PREFIX}{rand_suffix()}"


def qatest_email(username: str) -> str:
    return f"{username}@example.test"


# --- Admin bootstrap / login --------------------------------------------


def admin_client() -> httpx.Client:
    """Logs in as the test admin (QC_AGENT_TEST_ADMIN_USER/PASS, provisioned
    by _00_bootstrap.py) and returns a ready-to-use client.

    Every script in tests/backend/ calls this first, before anything else
    -- so resetting the login/register rate-limit buckets (SEC-03,
    app/auth/rate_limit.py) here, before this script's own admin login,
    gives every script a clean per-IP budget regardless of what the
    PREVIOUS script in the same run_backend.sh pass consumed. A script
    that itself does heavy login/register volume (sec_03, sec_05, perf_01,
    p1_01) still resets again internally around that specific burst -- this
    call alone isn't enough to isolate a burst from itself, just from
    whatever ran before it."""
    reset_rate_limits()
    if not ADMIN_PASS:
        print(
            "FAIL: QC_AGENT_TEST_ADMIN_PASS not set -- run tests/backend/_00_bootstrap.py "
            "first (it prints the password to use for the rest of this run).",
            file=sys.stderr,
        )
        sys.exit(1)
    c = new_client()
    r = c.post("/api/auth/login", json={"email_or_username": ADMIN_USER, "password": ADMIN_PASS})
    if r.status_code != 200:
        print(f"FAIL: admin login failed: {r.status_code} {r.text}", file=sys.stderr)
        sys.exit(1)
    return c


def mint_invite(admin: httpx.Client, role: str = "user", ttl_hours: int = 72) -> str:
    r = admin.post("/api/admin/invites", json={"role": role, "ttl_hours": ttl_hours})
    r.raise_for_status()
    return r.json()["token"]


# --- Register / login -----------------------------------------------------


def register(
    invite_token: str,
    username: str | None = None,
    email: str | None = None,
    password: str = "correct horse battery staple 1",
    client: httpx.Client | None = None,
) -> tuple[httpx.Client, dict]:
    """Registers a new qatest_ user via a valid invite token. Returns
    (logged_in_client, user_public_dict) -- registration auto-starts a
    session (server/routes/auth.py's _start_session), so no separate login
    call is needed."""
    username = username or qatest_username()
    email = email or qatest_email(username)
    c = client or new_client()
    r = c.post(
        "/api/auth/register",
        json={"invite_token": invite_token, "email": email, "username": username, "password": password},
    )
    r.raise_for_status()
    return c, r.json()


def login(username_or_email: str, password: str, client: httpx.Client | None = None) -> tuple[httpx.Client, httpx.Response]:
    c = client or new_client()
    r = c.post("/api/auth/login", json={"email_or_username": username_or_email, "password": password})
    return c, r


# --- Rate-limit reset --------------------------------------------------


def reset_rate_limits() -> None:
    """Every script here runs from ONE apparent client IP (localhost behind
    nginx), the same key app/auth/rate_limit.py buckets on -- so any script
    that intentionally exercises the login/register rate limit (or that
    logs in enough times in a run to accidentally trip it, e.g. perf_01's
    concurrent-login sweep) would otherwise poison every OTHER script that
    runs afterward within the same window, starting with admin_client()'s
    own login call. Call this before AND after any such script. Uses the
    `api` container's own Python (it already has `redis` installed and a
    working QC_AGENT_REDIS_URL) rather than assuming redis-cli's SCAN/DEL
    are on the test host."""
    subprocess.run(
        [
            "docker", "compose", "exec", "-T", "api",
            "python", "-c",
            "from app.auth.redis_session import get_client; "
            "c = get_client(); "
            "keys = c.keys('qc_agent:ratelimit:*'); "
            "c.delete(*keys) if keys else None",
        ],
        cwd=str(_COMPOSE_DIR),
        capture_output=True,
        text=True,
        timeout=15,
    )


# --- Cleanup ----------------------------------------------------------------


def cleanup_user(admin: httpx.Client, user_id: str) -> None:
    admin.delete(f"/api/admin/users/{user_id}")


def cleanup_all_qatest_users(admin: httpx.Client) -> int:
    """Deletes every user whose username starts with qatest_ (except the
    test admin itself, which callers manage separately). Safe to call
    liberally between test runs -- never touches a non-qatest_ account."""
    r = admin.get("/api/admin/users")
    r.raise_for_status()
    n = 0
    for u in r.json():
        if u["username"].startswith(QATEST_PREFIX) and u["username"] != ADMIN_USER:
            admin.delete(f"/api/admin/users/{u['id']}")
            n += 1
    return n


# --- Reporting ---------------------------------------------------------


_results: list[tuple[str, bool, str]] = []


def check(name: str, condition: bool, detail: str = "") -> bool:
    status = "PASS" if condition else "FAIL"
    line = f"[{status}] {name}" + (f" -- {detail}" if detail else "")
    print(line)
    _results.append((name, condition, detail))
    return condition


def summary(exit_on_failure: bool = True) -> None:
    n_fail = sum(1 for _, ok, _ in _results if not ok)
    n_total = len(_results)
    print(f"\n{n_total - n_fail}/{n_total} checks passed in this script.")
    if exit_on_failure and n_fail:
        sys.exit(1)


@contextmanager
def timed():
    start = time.perf_counter()
    box = {}
    yield box
    box["elapsed"] = time.perf_counter() - start
