"""SEC-10 (isolated, destructive -- run separately, never as part of the
default suite via run_backend.sh). models.count_admins() (app/auth/
models.py) USED TO filter `role = 'admin' AND is_active` -- so
DEACTIVATING (not deleting) every admin made it read 0, and
server/admin_cli.py's bootstrap-admin (which refuses only "if an admin
already exists") would wrongly succeed a second time. This has since been
fixed (count_admins() now counts every admin row regardless of
is_active) -- this script verifies the fix directly against the real
function, not a hand-reproduced query.

Sequence:
  1. Real admin mints an admin-role invite, a second admin (qatest_admin2)
     registers through it.
  2. BOTH qatest_admin2 and the real qatest_admin are deactivated directly
     via SQL (there's no deactivate-user route in this app at all -- only
     delete -- so this uses the same in-container exec technique as the
     other sec_* scripts to simulate "every admin got deactivated by some
     other means" without deleting either row). This reaches the actual
     zero-active-admins state the original bug needed to manifest.
  3. Call the real count_admins() -- must be > 0 (both admin rows still
     exist, merely inactive) for bootstrap-admin to correctly keep
     refusing.
  4. Reactivate both accounts and clean up qatest_admin2, regardless of
     outcome.
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


def _set_active(user_id: str, active: bool) -> None:
    _exec_api(
        "from app.auth.db import get_pool\n"
        f"get_pool().connection().__enter__().execute(\"UPDATE users SET is_active = {active} WHERE id = '{user_id}'\")"
    )


def main() -> None:
    admin = admin_client()
    real_admin_id = admin.get("/api/auth/me").json()["id"]

    admin_invite = mint_invite(admin, role="admin")
    client2, admin2 = register(admin_invite, username="qatest_admin2")
    check("disposable qatest_admin2 registered as a real admin", admin2["role"] == "admin")

    try:
        # Reach the actual zero-active-admins state the original bug needed.
        _set_active(admin2["id"], False)
        _set_active(real_admin_id, False)
        n_admins = int(_exec_api("from app.auth.models import count_admins; print(count_admins())"))
        print(f"count_admins() with EVERY admin row deactivated (not deleted): {n_admins}")
        check(
            "FIX VERIFIED: count_admins() still counts deactivated admin rows, "
            "so bootstrap-admin correctly keeps refusing even with zero ACTIVE admins",
            n_admins == 2,
            f"count_admins()={n_admins} (expected 2 -- both rows still exist, merely inactive; "
            "0 here would mean the reactivation bypass is still live)",
        )
    finally:
        _set_active(real_admin_id, True)
        _set_active(admin2["id"], True)
        cleanup_user(admin, admin2["id"])

    summary()


if __name__ == "__main__":
    main()
