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

import json
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

# The deployment-wide admin purges (POST /api/admin/purge/jobs and its
# siblings) delete EVERY user's data on the stack, not only what a test
# created. On 2026-09-24 p1_03 was run on its own to check a config change
# and took seven finished jobs belonging to a real account with it, so the
# refusal lives here, on the admin client every script gets, where running
# a script directly cannot route around it.
#
# Two conditions, both required. QC_AGENT_TEST_ALLOW_PURGE=1 says a person
# wants an empty stack. And the stack must have nobody on it but test
# accounts: the development stack is also a research group's deployment, so
# a stack with any account not named qatest_* holds someone's real work and
# no flag makes a blind purge of it acceptable. A whole-stack purge, or
# e2e_16's reset-all, belongs on a throwaway stack such as the one
# tests/install_interactive.py builds.
ALLOW_PURGE_ENV = "QC_AGENT_TEST_ALLOW_PURGE"
_ADMIN_PURGE_PREFIX = "/api/admin/purge/"
_real_users_cache: list[str] | None = None


def real_usernames(admin: httpx.Client | None = None) -> list[str]:
    """Every account on the stack that is not a test account. Asked once per
    process: accounts are not created mid-script by anyone but the script."""
    global _real_users_cache
    if _real_users_cache is None:
        client = admin or admin_client()
        r = client.get("/api/admin/users")
        r.raise_for_status()
        _real_users_cache = sorted(
            u["username"] for u in r.json() if not u["username"].startswith(QATEST_PREFIX)
        )
    return _real_users_cache


def shared_stack(admin: httpx.Client | None = None) -> bool:
    return bool(real_usernames(admin))


def purge_refusal(admin: httpx.Client | None = None) -> str | None:
    """Why a whole-stack purge may not run here, or None when it may."""
    if os.environ.get(ALLOW_PURGE_ENV) != "1":
        return f"it deletes every user's data on the stack; set {ALLOW_PURGE_ENV}=1 on a throwaway stack"
    real = real_usernames(admin)
    if real:
        return (f"this stack has real users ({', '.join(real)}), and a whole-stack purge would "
                f"delete their work; it only runs on a stack with nothing but qatest_ accounts")
    return None


def purge_allowed(admin: httpx.Client | None = None) -> bool:
    return purge_refusal(admin) is None


class BlindPurgeRefused(RuntimeError):
    pass


def _purge_guard(admin_ref: list) -> "callable":
    def hook(request: httpx.Request) -> None:
        if request.url.path.startswith(_ADMIN_PURGE_PREFIX):
            why = purge_refusal(admin_ref[0])
            if why:
                raise BlindPurgeRefused(f"refused {request.method} {request.url.path}: {why}")
    return hook


def require_purge_opt_in(what: str) -> None:
    """For a script whose whole point is a deployment-wide purge: stop
    before it touches anything unless it may run here."""
    why = purge_refusal()
    if why:
        print(f"[SKIP] {what} -- {why}")
        sys.exit(0)


# Restarting the api container interrupts everyone using the app: open chat
# streams drop, and every running calculation is killed whoever started it.
# That is fine on an idle stack and not on one a research group is working
# on, so a restart needs QC_AGENT_TEST_ALLOW_RESTART=1 AND nobody but test
# accounts active: no real user with a running job or the app open, and no
# running job without an owner, since that could be anyone's.
ALLOW_RESTART_ENV = "QC_AGENT_TEST_ALLOW_RESTART"


class RestartRefused(RuntimeError):
    pass


def restart_refusal(admin: httpx.Client) -> str | None:
    """Why the api may not be restarted right now, or None when it may."""
    if os.environ.get(ALLOW_RESTART_ENV) != "1":
        return (f"restarting the api interrupts everyone using the stack; set "
                f"{ALLOW_RESTART_ENV}=1 to allow it when nobody else is active")
    act = admin.get("/api/admin/activity")
    act.raise_for_status()
    body = act.json()
    busy = [
        f"{u['username']} ({u['running_jobs']} running, {u['open_streams']} open)"
        for u in body["users"]
        if not (u["username"] or "").startswith(QATEST_PREFIX)
        and (u["running_jobs"] or u["open_streams"])
    ]
    if body["unowned"]["running_jobs"]:
        busy.append(f"{body['unowned']['running_jobs']} running job(s) with no owner")
    if busy:
        return "real users are active: " + "; ".join(busy)
    return None


def require_restart_opt_in(admin: httpx.Client, what: str) -> None:
    """For a script whose whole point needs a restart: stop before it sets
    anything up unless a restart may happen now."""
    why = restart_refusal(admin)
    if why:
        print(f"[SKIP] {what} -- {why}")
        sys.exit(0)


def restart_api(admin: httpx.Client, wait_seconds: float = 180.0) -> bool:
    """Restarts the api container if restart_refusal allows it, then waits
    for /api/health. Raises RestartRefused otherwise. Returns whether the
    api came back healthy in time."""
    why = restart_refusal(admin)
    if why:
        raise RestartRefused(why)
    subprocess.run(["docker", "compose", "restart", "api"], cwd=str(_COMPOSE_DIR),
                   check=True, capture_output=True, timeout=300)
    deadline = time.time() + wait_seconds
    while time.time() < deadline:
        try:
            if new_client().get("/api/health", timeout=5).status_code == 200:
                return True
        except Exception:
            pass
        time.sleep(1)
    return False


# Deployment-wide settings are shared with everyone on the stack, including
# an admin who may change one while a test runs. On 2026-09-24 an admin set
# max_concurrent_jobs_per_user to 8 and a test six minutes later wrote 3 over
# it and never put anything back. So a test that must change a setting uses
# config_override(): it records what was there, and on the way out restores
# it ONLY if the setting still holds the test's own value. If someone else
# changed it in between, theirs stands and the test says so.
#
# Prefer not to change a shared setting at all. To prove "a valid change is
# accepted", write back the value that is already there. To put one account
# over a storage cap, use quota_override() on that account: lowering a cap
# for everyone makes the app evict every user's oldest work.
@contextmanager
def config_override(admin: httpx.Client, key: str, value):
    before = admin.get("/api/admin/config").json().get(key)
    r = admin.patch("/api/admin/config", json={"key": key, "value": value})
    if r.status_code != 200:
        raise RuntimeError(f"could not set {key}={value!r}: {r.status_code} {r.text[:200]}")
    try:
        yield before
    finally:
        restore_config(admin, key, before, value)


def restore_config(admin: httpx.Client, key: str, original, test_value) -> bool:
    """Puts `key` back to `original` if it still holds `test_value`, the
    value the test set. Someone else's change in between is left alone.
    Returns whether the setting now holds `original`."""
    now = admin.get("/api/admin/config").json().get(key)
    if now != test_value:
        print(f"    note: {key} was changed to {now!r} by someone else during the test; "
              f"leaving it rather than restoring {original!r}")
        return now == original
    r = admin.patch("/api/admin/config", json={"key": key, "value": original})
    return r.status_code == 200


@contextmanager
def quota_override(admin: httpx.Client, user_id: str, key: str, value: int):
    """One account's storage cap, for the duration. Nobody else's changes."""
    r = admin.put(f"/api/admin/users/{user_id}/quota-override", json={"key": key, "value": value})
    if r.status_code != 200:
        raise RuntimeError(f"could not override {key} for {user_id}: {r.status_code} {r.text[:200]}")
    try:
        yield
    finally:
        admin.put(f"/api/admin/users/{user_id}/quota-override", json={"key": key, "value": None})


def jobs_refusal(admin: httpx.Client, include_open_apps: bool = False) -> str | None:
    """Why a test may not change how the deployment runs jobs now, or None.
    Lowering a concurrency cap queues everybody's new jobs behind the
    test's, so it waits for a moment when no real user has a job running or
    queued. A setting a new job picks up at submission, such as cores per
    calculation, also waits for nobody to have the app open
    (include_open_apps), since anyone who does could submit into it."""
    body = admin.get("/api/admin/activity").json()
    busy = [
        f"{u['username']} ({u['running_jobs']} running, {u['pending_jobs']} queued, "
        f"{u['open_streams']} open)"
        for u in body["users"]
        if not (u["username"] or "").startswith(QATEST_PREFIX)
        and (u["running_jobs"] or u["pending_jobs"] or (include_open_apps and u["open_streams"]))
    ]
    if body["unowned"]["running_jobs"] or body["unowned"]["pending_jobs"]:
        busy.append("jobs with no owner are running or queued")
    return ("real users are active, and this test changes how the deployment runs "
            "their jobs: " + "; ".join(busy)) if busy else None


def require_jobs_quiet(admin: httpx.Client, what: str, include_open_apps: bool = False) -> None:
    why = jobs_refusal(admin, include_open_apps)
    if why:
        print(f"[SKIP] {what} -- {why}")
        sys.exit(0)


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
    # The refusal goes on this client and not on new_client(): conf_01 and
    # e2e_03 send purge requests as a non-admin or anonymously on purpose,
    # to prove they are rejected, and those must still reach the server.
    ref: list = [None]
    c = new_client(event_hooks={"request": [_purge_guard(ref)]})
    r = c.post("/api/auth/login", json={"email_or_username": ADMIN_USER, "password": ADMIN_PASS})
    if r.status_code != 200:
        print(f"FAIL: admin login failed: {r.status_code} {r.text}", file=sys.stderr)
        sys.exit(1)
    ref[0] = c
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


# e2e_08 runs its job matrix as a fresh test user and leaves that user in
# place for the scripts that follow (e2e_09, e2e_10, e2e_12), which work with
# its completed jobs. They used to find those jobs as the admin, which only
# worked while admins saw every user's items. e2e_08 now writes the user's
# sign-in here (gitignored), and the follow-ups sign in as that user.
MATRIX_USER_FILE = Path(__file__).resolve().parent / ".e2e_matrix_user"


def record_matrix_user(username: str, password: str) -> None:
    MATRIX_USER_FILE.write_text(json.dumps({"username": username, "password": password}))


def matrix_user_client() -> httpx.Client:
    """Signed in as the user e2e_08 ran its matrix as. Exits with a clear
    message if e2e_08 has not run, rather than falling back to an account
    that cannot see the jobs."""
    if not MATRIX_USER_FILE.exists():
        print(f"FAIL: no {MATRIX_USER_FILE.name} -- run tests/e2e/e2e_08_job_matrix.py first", file=sys.stderr)
        sys.exit(1)
    creds = json.loads(MATRIX_USER_FILE.read_text())
    reset_rate_limits()
    c, r = login(creds["username"], creds["password"])
    if r.status_code != 200:
        print(f"FAIL: could not sign in as the matrix user {creds['username']}: {r.status_code}", file=sys.stderr)
        sys.exit(1)
    return c


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
    are on the test host.

    Scoped, because the stack is shared with real users. It clears the test
    accounts' own login buckets and the per-address buckets, which every
    user behind the same address shares, so clearing them only ever gives
    people back budget. It leaves a real account's own login bucket alone:
    that one records attempts against that account's password, and wiping
    it mid-attempt would hand a guesser a fresh ten tries. It used to clear
    every rate-limit key on the stack. SCAN rather than KEYS, which blocks
    Redis for everyone while it runs."""
    subprocess.run(
        [
            "docker", "compose", "exec", "-T", "api",
            "python", "-c",
            "from app.auth.redis_session import get_client\n"
            "c = get_client()\n"
            "shared = ('login_ip', 'register', 'password_reset')\n"
            "for k in c.scan_iter('qc_agent:ratelimit:*', count=500):\n"
            "    k = k.decode() if isinstance(k, bytes) else k\n"
            "    bucket = k.split(':')[2]\n"
            # login:<ip> with no account is the pre-split per-address form,
            # still what a stack running older code writes.
            "    if bucket in shared or 'qatest_' in k or (bucket == 'login' and k.count(':') == 3):\n"
            "        c.delete(k)\n",
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


def _owner_map(kind: str) -> dict[str, str | None]:
    """{id: owner username or None} for every top-level job, or every
    conversation, on the stack. Ids and owners only, read inside the api
    container: admins no longer see other users' items through the app's
    routes (app/auth/ownership.py), and the end-of-run sweeps still need to
    tell what this run created from what a real user made meanwhile."""
    code = (
        "import json\n"
        "from app.auth import models\n"
        "from app.auth.db import get_pool\n"
        "names = {str(u['id']): u['username'] for u in models.list_users()}\n"
        "with get_pool().connection() as c:\n"
        f"    own = {{r['resource_id']: names.get(str(r['owner_user_id'])) for r in c.execute(\"SELECT resource_id, owner_user_id FROM ownership_index WHERE kind = '{kind}'\").fetchall()}}\n"
    )
    if kind == "job":
        code += (
            "from app.config import JOBS_DIR\n"
            "ids = []\n"
            "for d in JOBS_DIR.iterdir():\n"
            "    p = d / 'spec.json'\n"
            "    if d.is_dir() and p.exists():\n"
            "        try:\n"
            "            if json.loads(p.read_text()).get('parent_job_id'): continue\n"
            "        except Exception: continue\n"
            "        ids.append(d.name)\n"
        )
    else:
        code += (
            "from app.agent import threads as t\n"
            "ids = [x['thread_id'] for x in t.list_threads()]\n"
        )
    code += "print('@@@' + json.dumps({i: own.get(i) for i in ids}))\n"
    proc = subprocess.run(["docker", "compose", "exec", "-T", "api", "python", "-c", code],
                          cwd=str(_COMPOSE_DIR), capture_output=True, text=True, timeout=120)
    line = next((ln for ln in proc.stdout.splitlines() if ln.startswith("@@@")), None)
    if line is None:
        raise RuntimeError(f"could not list {kind} owners: {proc.stderr[-400:]}")
    return json.loads(line[3:])


def all_job_owners() -> dict[str, str | None]:
    return _owner_map("job")


def all_thread_owners() -> dict[str, str | None]:
    return _owner_map("thread")


def made_by_tests(owner: str | None) -> bool:
    """Whether a run may clean an item up: owned by a test account, or by
    nobody. The app gives everything a signed-in person creates an owner, so
    an ownerless item came from a test working in-process. Anything a real
    user made, including while the run was going, is not ours to delete."""
    return owner is None or owner.startswith(QATEST_PREFIX)


def cleanup_jobs(admin: httpx.Client, job_ids) -> tuple[int, list[str]]:
    """Deletes each of `job_ids` through the admin-only route, which cancels
    a running job and waits for it to stop before removing it.

    Returns (n_deleted, still_there). It used to use DELETE /api/jobs/{id}
    as the admin. Admins no longer reach other users' jobs through that
    route and get a 404, which this function counts as "already gone", so
    a test user's job would have been silently left behind.

    Deleting a master cascades to its sub-jobs (delete_job_dir), so a
    caller that passes a scan master does not also need to pass its
    images -- and by the time this runs those ids may already be gone,
    which is why a 404 is counted as success rather than a failure.
    """
    deleted, remaining = 0, []
    for job_id in list(job_ids):
        r = admin.delete(f"/api/admin/jobs/{job_id}", timeout=60)
        if r.status_code in (200, 404):
            deleted += 1
            continue
        # A 409 means cancelled but not yet stopped. A job whose submitting
        # process has exited (sec_07 does that deliberately) has no live
        # manager to stop it, and only reaches a terminal status when the
        # server's reconcile sweep marks it, about a minute later. Keep
        # asking for up to 90 s rather than leave it behind.
        deadline = time.time() + 90
        while r.status_code == 409 and time.time() < deadline:
            time.sleep(5)
            r = admin.delete(f"/api/admin/jobs/{job_id}", timeout=60)
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
# Helpers shared by install.sh and update.sh live here rather than in either
# one. Pass it as `path=` to lift a function that has moved into the library.
COMMON_SH = Path(__file__).resolve().parent.parent / "scripts" / "lib" / "common.sh"


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
    """Every conversation id the caller can see: their own. An admin is no
    different; for every conversation on the stack, with owners, use
    all_thread_owners()."""
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
        r = admin.delete(f"/api/admin/threads/{thread_id}")
        if r.status_code in (200, 204, 404):
            deleted += 1
        else:
            remaining.append(thread_id)
    return deleted, remaining
