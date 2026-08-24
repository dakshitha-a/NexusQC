"""Provisions the qatest_admin account this whole test suite runs as, via
server/admin_cli.py's bootstrap-admin command (the ONE way to create an
admin without an existing admin's invite token -- see auth.py's module
docstring). Must run first, exactly once per fresh stack.

bootstrap-admin refuses if any admin already exists (models.count_admins()
> 0) -- this script checks that first via a direct login attempt so
re-running it against an already-bootstrapped stack is a harmless no-op
that just confirms the existing credentials still work, rather than
failing loudly.

Writes the generated password to tests/.admin_creds (gitignored) so every
other script in this directory can read it via fixtures.ADMIN_PASS without
the operator having to export an env var by hand.
"""
from __future__ import annotations

import secrets
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from fixtures import ADMIN_USER, check, new_client, summary  # noqa: E402

CREDS_FILE = Path(__file__).resolve().parent.parent / ".admin_creds"
COMPOSE_DIR = Path(__file__).resolve().parent.parent.parent


def _existing_admin_password() -> str | None:
    if CREDS_FILE.exists():
        return CREDS_FILE.read_text().strip()
    return None


def _login_ok(password: str) -> bool:
    c = new_client()
    r = c.post("/api/auth/login", json={"email_or_username": ADMIN_USER, "password": password})
    return r.status_code == 200


PRE_EXISTING_JOBS_FILE = Path(__file__).resolve().parent.parent / ".jobs_before_run"


def _snapshot_pre_existing_jobs() -> None:
    """Records which jobs already existed, so the sweep at the end of the
    run knows which ones this run is responsible for.

    Without a baseline the only safe sweep would be "delete every unowned
    job", which is wrong: an unowned job is a legitimate, deliberately
    shared thing on a real deployment (see fixtures.cleanup_jobs), and a
    test run has no business removing one it did not create.

    Best-effort: a failure here costs the run its cleanup, not its result,
    so it must never take the bootstrap down with it.
    """
    try:
        from fixtures import admin_client, list_job_ids
        ids = list_job_ids(admin_client())
        PRE_EXISTING_JOBS_FILE.write_text("\n".join(sorted(ids)))
        print(f"Recorded {len(ids)} pre-existing job(s) in {PRE_EXISTING_JOBS_FILE.name}; "
              f"zz_99_job_cleanup.py removes anything this run adds beyond them.")
    except Exception as e:
        print(f"[warn] could not snapshot pre-existing jobs ({type(e).__name__}: {e}); "
              f"the end-of-run job sweep will skip itself rather than guess.")


def main() -> None:
    existing = _existing_admin_password()
    if existing and _login_ok(existing):
        check("qatest_admin already provisioned and reachable", True, f"username={ADMIN_USER}")
        # The usual path: the stack is already bootstrapped. The job
        # snapshot still has to be taken, or the end-of-run sweep has no
        # baseline on every run after the first.
        _snapshot_pre_existing_jobs()
        summary(exit_on_failure=False)
        return

    password = secrets.token_urlsafe(18)
    proc = subprocess.run(
        [
            "docker", "compose", "exec", "-T", "api",
            "python", "-m", "server.admin_cli", "bootstrap-admin",
            "--email", f"{ADMIN_USER}@example.test", "--username", ADMIN_USER,
            "--first-name", "QA", "--last-name", "Admin",
        ],
        input=f"{password}\n{password}\n",
        cwd=str(COMPOSE_DIR),
        capture_output=True,
        text=True,
        timeout=30,
    )
    print(proc.stdout)
    if proc.returncode != 0:
        print(proc.stderr, file=sys.stderr)
    ok = check(
        "bootstrap-admin created qatest_admin",
        proc.returncode == 0 and "Created admin account" in proc.stdout,
        proc.stderr.strip()[:300],
    )
    if not ok:
        summary()
        return

    CREDS_FILE.write_text(password + "\n")
    CREDS_FILE.chmod(0o600)
    check("login with freshly-bootstrapped admin credentials", _login_ok(password))
    _snapshot_pre_existing_jobs()
    print(f"\nCredentials written to {CREDS_FILE} -- every other tests/backend/*.py script reads them automatically.")
    summary()


if __name__ == "__main__":
    main()
