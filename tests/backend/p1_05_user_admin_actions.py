"""P1 functional coverage: the admin user-management actions added
alongside the console UI -- suspend/restore (PATCH /api/admin/users/{id})
and the guards that keep an admin from locking the deployment out.

Suspension is worth testing at both layers, not just at login: deactivation
has to take effect for a session that is ALREADY open, which it only does
because get_current_user re-reads the user row on every request instead of
trusting the JWT's claims. A cached-claims implementation would pass a
login-only test and still leave a suspended user working indefinitely.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from fixtures import (  # noqa: E402
    admin_client,
    check,
    cleanup_user,
    login,
    mint_invite,
    register,
    reset_rate_limits,
    summary,
)

PASSWORD = "correct horse battery staple 1"


def main() -> None:
    admin = admin_client()
    me = admin.get("/api/auth/me").json()

    token = mint_invite(admin)
    user_client, user = register(token, password=PASSWORD)
    username = user["username"]

    r_ok = user_client.get("/api/auth/me")
    check("the new user's session works before suspension", r_ok.status_code == 200, str(r_ok.status_code))

    # --- Suspend ---------------------------------------------------------
    r_suspend = admin.patch(f"/api/admin/users/{user['id']}", json={"is_active": False})
    check(
        "admin can suspend a user",
        r_suspend.status_code == 200 and r_suspend.json()["is_active"] is False,
        f"{r_suspend.status_code} {r_suspend.text[:150]}",
    )

    r_after = user_client.get("/api/auth/me")
    check(
        "a suspended user's ALREADY-OPEN session stops working immediately",
        r_after.status_code == 401,
        f"got {r_after.status_code}",
        "deactivation is only checked at login -- an open session survives it",
    )

    reset_rate_limits()
    _, r_login = login(username, PASSWORD)
    check(
        "a suspended user cannot log back in",
        r_login.status_code == 401,
        f"got {r_login.status_code} {r_login.text[:120]}",
    )

    # --- Restore ---------------------------------------------------------
    r_restore = admin.patch(f"/api/admin/users/{user['id']}", json={"is_active": True})
    check(
        "admin can restore a suspended user",
        r_restore.status_code == 200 and r_restore.json()["is_active"] is True,
        f"{r_restore.status_code} {r_restore.text[:150]}",
    )

    reset_rate_limits()
    _, r_login2 = login(username, PASSWORD)
    check("a restored user can log in again", r_login2.status_code == 200, f"got {r_login2.status_code}")

    # --- Lockout guards --------------------------------------------------
    r_self = admin.patch(f"/api/admin/users/{me['id']}", json={"is_active": False})
    check(
        "an admin cannot suspend their own account",
        r_self.status_code == 400,
        f"got {r_self.status_code} {r_self.text[:150]}",
        "an admin who suspends themselves cannot undo it -- there is no way back in",
    )

    r_self_del = admin.delete(f"/api/admin/users/{me['id']}")
    check(
        "an admin cannot delete their own account",
        r_self_del.status_code == 400,
        f"got {r_self_del.status_code} {r_self_del.text[:150]}",
    )

    # The last-active-admin guard. Reachable via a SECOND admin: promote one
    # through an admin-role invite, suspend the original, then confirm the
    # survivor cannot also be suspended.
    admin2_token = mint_invite(admin, role="admin")
    admin2_client, admin2 = register(admin2_token, password=PASSWORD)

    r_suspend_other_admin = admin.patch(f"/api/admin/users/{admin2['id']}", json={"is_active": False})
    check(
        "one admin can suspend another while a second active admin remains",
        r_suspend_other_admin.status_code == 200,
        f"got {r_suspend_other_admin.status_code} {r_suspend_other_admin.text[:150]}",
    )

    # admin2 is now suspended, so the bootstrap admin is the only active one.
    r_last = admin2_client.patch(f"/api/admin/users/{me['id']}", json={"is_active": False})
    check(
        "a suspended admin cannot act at all (401, not a successful suspend)",
        r_last.status_code == 401,
        f"got {r_last.status_code}",
    )

    cleanup_user(admin, user["id"])
    cleanup_user(admin, admin2["id"])
    summary()


if __name__ == "__main__":
    main()
