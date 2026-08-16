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


def main() -> None:
    existing = _existing_admin_password()
    if existing and _login_ok(existing):
        check("qatest_admin already provisioned and reachable", True, f"username={ADMIN_USER}")
        summary(exit_on_failure=False)
        return

    password = secrets.token_urlsafe(18)
    proc = subprocess.run(
        [
            "docker", "compose", "exec", "-T", "api",
            "python", "-m", "server.admin_cli", "bootstrap-admin",
            "--email", f"{ADMIN_USER}@example.test", "--username", ADMIN_USER,
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
    print(f"\nCredentials written to {CREDS_FILE} -- every other tests/backend/*.py script reads them automatically.")
    summary()


if __name__ == "__main__":
    main()
