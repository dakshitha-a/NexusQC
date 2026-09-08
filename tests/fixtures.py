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
    first_name: str = "QA",
    last_name: str = "Tester",
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
        json={
            "invite_token": invite_token, "email": email, "username": username, "password": password,
            "first_name": first_name, "last_name": last_name,
        },
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


# --- Job cleanup -------------------------------------------------------
#
# Test scripts submit real jobs, and most do it by calling JobManager
# in-process rather than through the API. Ownership is recorded by the API
# ROUTE, not by JobManager, so those jobs end up with no recorded owner --
# and an unowned job is deliberately visible to every user (see
# server/routes/jobs.py's list_all_jobs, and app/auth/ownership.py on why
# that is a feature: anyone can see it, so anyone can clear it). The
# consequence is that without this, every suite run left permanent clutter
# in everybody's job list. 13 such jobs had accumulated by 2026-08-23.


def list_job_ids(client: httpx.Client) -> set[str]:
    """Every top-level job id the caller can see. Sub-jobs are already
    excluded by the route itself.

    include_archived is on because this is what cleanup_jobs uses to find
    what a script created, and GET /api/jobs hides a job filed into a
    project archive by default. Without it, a script that archives
    anything would silently fail to clean it up and leave qatest_ clutter
    behind -- the exact failure mode the cleanup policy in tests/README.md
    exists to prevent. Inert for the scripts that archive nothing."""
    r = client.get("/api/jobs", params={"include_archived": "true"})
    r.raise_for_status()
    return {row["job_id"] for row in r.json()}


def cleanup_jobs(admin: httpx.Client, job_ids) -> tuple[int, list[str]]:
    """Deletes each of `job_ids`, cancelling first where needed.

    Returns (n_deleted, still_there). A job is cancelled before deletion
    because DELETE /api/jobs/{id} answers 409 for anything non-terminal --
    correctly, since removing a running job's directory out from under its
    worker is how you get a half-written result nobody can explain.

    Deleting a master cascades to its sub-jobs (delete_job_dir), so a
    caller that passes a scan master does not also need to pass its
    images -- and by the time this runs those ids may already be gone,
    which is why a 404 is counted as success rather than a failure.
    """
    deleted, remaining = 0, []
    for job_id in list(job_ids):
        admin.post(f"/api/jobs/{job_id}/cancel")
        r = admin.delete(f"/api/jobs/{job_id}")
        if r.status_code in (200, 404):
            deleted += 1
            continue
        # One retry: cancellation is not instantaneous, and a job that was
        # mid-spawn when cancelled needs a moment to reach a terminal
        # status before its directory may be removed.
        time.sleep(3)
        r = admin.delete(f"/api/jobs/{job_id}")
        if r.status_code in (200, 404):
            deleted += 1
        else:
            remaining.append(f"{job_id} ({r.status_code})")
    return deleted, remaining


# --- Reporting ---------------------------------------------------------


_results: list[tuple[str, bool, str]] = []


_skipped: list[tuple[str, str]] = []


# Longest a single detail string may be. Generous enough for a JSON error
# body, short enough that one check cannot bury the rest of the report.
_DETAIL_LIMIT = 300


def _printable(s: str, limit: int = _DETAIL_LIMIT) -> str:
    """Escapes anything non-printable out of a check's detail, and caps it.

    Not cosmetic. A detail built from a response body can carry raw binary:
    proj_03_ownership.py asserts an owner can download their project and
    prints `resp.text[:150]`, which for a zip begins `PK\x03\x04` and
    carries NUL bytes. A single NUL makes the WHOLE stream binary to grep,
    and this host's grep is ugrep, which then silently prints nothing at
    all -- no matches, and no "binary file matches" note on stderr either.

    That cost a real diagnosis. A batch run of several scripts showed
    proj_03 with no summary line between its neighbours' results, which
    reads exactly like a script that crashed; it had in fact passed 15/15
    the whole time, and only `grep -a` could see it. Any filtered run
    (a `| grep`, a CI log scraper) could lose a script's entire verdict
    this way, and losing it silently is worse than a noisy failure.

    Fixed here rather than at the one call site so no future script can
    reintroduce it: every line these scripts print goes through `check`.
    """
    if not s:
        return s
    out = "".join(ch if (ch.isprintable() or ch == "\t") else f"\\x{ord(ch):02x}" for ch in s)
    return out if len(out) <= limit else out[:limit] + "..."


def check(name: str, condition: bool, detail: str = "", fail_detail: str = "") -> bool:
    """`detail` is printed either way (a measured value, a status code --
    useful context on a pass as well as a failure). `fail_detail` is
    printed only when the check FAILS.

    The split exists because several scripts had put diagnosis-of-failure
    text into `detail`, so a passing run printed lines like
    "[PASS] user B's source survived -- user B's source was also deleted",
    which reads as a contradiction and undermines trust in the whole
    report (F-012).

    Both are run through `_printable`, so no check can poison its own
    script's output with binary -- see that function for the failure it
    closes.
    """
    status = "PASS" if condition else "FAIL"
    detail = _printable(detail)
    fail_detail = _printable(fail_detail)
    parts = [d for d in (detail, "" if condition else fail_detail) if d]
    line = f"[{status}] {name}" + (f" -- {'; '.join(parts)}" if parts else "")
    print(line)
    _results.append((name, condition, "; ".join(parts)))
    return condition


def skip(name: str, reason: str) -> None:
    """Records a check that could not be MEANINGFULLY run, distinct from
    one that ran and failed.

    Some checks depend on catching a job mid-flight, which depends on how
    fast the host happens to be. When the probe finishes first the check
    proves nothing -- reporting that as a FAIL claims a design violation
    that was never observed, which is worse than saying nothing. It is
    also worse than a silent pass: a check that never actually ran should
    be visible, so counting it here keeps it in the summary line.
    """
    print(f"[SKIP] {name} -- {reason}")
    _skipped.append((name, reason))


def summary(exit_on_failure: bool = True) -> None:
    n_fail = sum(1 for _, ok, _ in _results if not ok)
    n_total = len(_results)
    tail = f" ({len(_skipped)} skipped)" if _skipped else ""
    print(f"\n{n_total - n_fail}/{n_total} checks passed in this script.{tail}")
    if exit_on_failure and n_fail:
        sys.exit(1)


@contextmanager
def timed():
    start = time.perf_counter()
    box = {}
    yield box
    box["elapsed"] = time.perf_counter() - start


# --- reading shell out of the deployment scripts ---------------------------
# The deploy_* scripts test scripts/update.sh's own logic rather than the
# running app: what it believes is deployed, what it records, and what it
# tells an operator to do when an update goes wrong. Those are shell
# functions, and the alternative to lifting them out is pasting a copy into
# the test, which keeps passing after the original changes. For a recovery
# path that is worse than having no test at all, so the extraction is
# deliberately strict: a restructure that breaks it fails loudly and asks to
# be fixed rather than silently testing a stale copy.
import re as _re  # noqa: E402  (kept local to this section's concern)

UPDATE_SH = Path(__file__).resolve().parent.parent / "scripts" / "update.sh"


def shell_function(name: str, path: Path = UPDATE_SH) -> str:
    """One `name() { ... }` block, verbatim and de-indented, from a shell script.

    The closing brace is matched at the same indentation as the opening line,
    not in column zero. update.sh wraps its whole body in `main()` so that bash
    parses the entire file before running any of it -- it fast-forwards the
    checkout it is running from, and rewriting a script while bash is still
    reading it makes bash resume at its old byte offset in the new file. That
    wrapper indents every function inside it by four spaces.

    The result is de-indented so the caller can drop it straight into a `bash
    -c` snippet, which is what every caller does with it.
    """
    text = path.read_text()
    m = _re.search(
        rf"^(?P<indent>[ \t]*){_re.escape(name)}\(\) \{{\n(?:.*?\n)*?(?P=indent)\}}\n",
        text,
        _re.M,
    )
    if not m:
        raise SystemExit(
            f"could not find {name}() in {path} -- if it was restructured, fix this "
            "extraction rather than inlining a copy that cannot go stale."
        )
    block, indent = m.group(0), m.group("indent")
    if not indent:
        return block
    return "".join(
        line[len(indent):] if line.startswith(indent) else line
        for line in block.splitlines(keepends=True)
    )


def shell_awk_program(marker: str, path: Path = UPDATE_SH) -> str:
    """The body of a single-quoted awk program following `marker` in a shell
    script, e.g. shell_awk_program('PREV=')."""
    # The closing quote's indentation is not hardcoded: update.sh wraps its
    # body in main() (so bash parses the whole file before running any of it),
    # which shifts every line inside by four spaces, and a fixed indent here
    # broke the moment that happened.
    m = _re.search(
        _re.escape(marker) + r"\"\$\(awk '\n(.*?)\n[ \t]*' ", path.read_text(), _re.S
    )
    if not m:
        raise SystemExit(
            f"could not find an awk program after {marker!r} in {path} -- if it was "
            "restructured, fix this extraction rather than inlining a copy."
        )
    return m.group(1)


def list_thread_ids(client: httpx.Client) -> set[str]:
    """Every conversation id the caller can see.

    Called with an admin client this is every conversation on the
    deployment: `owned_ids_filter` returns None for an admin, so
    GET /api/threads does not filter. That is what makes an end-of-run sweep
    able to see conversations a test opened in-process through
    `thread_registry.create_thread`, which records no owner at all.
    """
    r = client.get("/api/threads")
    r.raise_for_status()
    return {row["thread_id"] for row in r.json()}


def cleanup_threads(admin: httpx.Client, thread_ids) -> tuple[int, list[str]]:
    """Deletes each of `thread_ids`. Returns (n_deleted, still_there).

    A 404 counts as success: a script that cleaned up after itself properly
    has already removed its own, and this sweep should not report that as a
    failure. Unlike a job there is nothing to cancel first -- a conversation
    has no running state of its own.
    """
    deleted, remaining = 0, []
    for thread_id in list(thread_ids):
        r = admin.delete(f"/api/threads/{thread_id}")
        if r.status_code in (200, 204, 404):
            deleted += 1
        else:
            remaining.append(thread_id)
    return deleted, remaining
