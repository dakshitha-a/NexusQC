"""CONF-02: get_current_user (app/auth/deps.py) re-fetches the user row
from Postgres on every request rather than trusting the role baked into
the JWT payload at issuance. Proof: create a second admin, capture their
session, demote them by directly editing the DB row (there's no PATCH
role route -- role changes only happen via account creation/deletion in
this app, so this uses the same in-container exec technique as the sec_*
scripts to simulate an out-of-band demotion), then replay their ORIGINAL,
still-cryptographically-valid cookie against an admin route. Expected: 403
on the very next request, not just after a fresh login.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from fixtures import admin_client, check, cleanup_user, mint_invite, register, summary  # noqa: E402

COMPOSE_DIR = Path(__file__).resolve().parent.parent.parent


def _exec_api(code: str) -> str:
    proc = subprocess.run(
        ["docker", "compose", "exec", "-T", "api", "python", "-c", code],
        cwd=str(COMPOSE_DIR), capture_output=True, text=True, timeout=30,
    )
    if proc.returncode != 0:
        print(proc.stderr, file=sys.stderr)
        raise RuntimeError(f"in-container exec failed: {proc.stderr[:500]}")
    return proc.stdout.strip()


def main() -> None:
    admin = admin_client()
    admin_invite = mint_invite(admin, role="admin")
    client2, admin2 = register(admin_invite, username="qatest_admin2")
    check("second admin can access an admin route before demotion", client2.get("/api/admin/config").status_code == 200)

    _exec_api(
        "from app.auth.db import get_pool\n"
        f"get_pool().connection().__enter__().execute(\"UPDATE users SET role = 'user' WHERE id = '{admin2['id']}'\")"
    )

    r = client2.get("/api/admin/config")
    check(
        "the SAME still-valid session cookie is denied admin access on the very next request after demotion",
        r.status_code == 403,
        f"got {r.status_code} -- 200 would mean the app trusts the JWT's baked-in role instead of "
        "re-checking the DB, i.e. a demoted admin would keep admin access until their token expires",
    )

    cleanup_user(admin, admin2["id"])
    summary()


if __name__ == "__main__":
    main()
