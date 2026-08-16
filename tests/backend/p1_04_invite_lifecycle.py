"""P1 functional coverage: invite-token admin routes (create/list) and
their interaction with registration -- role assignment via invite,
GET /api/admin/invites reflecting redemption state."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from fixtures import admin_client, check, cleanup_user, register, summary  # noqa: E402


def main() -> None:
    admin = admin_client()

    r_bad_role = admin.post("/api/admin/invites", json={"role": "superadmin"})
    check("creating an invite with an invalid role is rejected", r_bad_role.status_code == 400, str(r_bad_role.status_code))

    r_invite = admin.post("/api/admin/invites", json={"role": "user", "email_hint": "qatest-hint@example.test"})
    check("admin can create a user-role invite", r_invite.status_code == 200, f"{r_invite.status_code} {r_invite.text[:150]}")
    token = r_invite.json()["token"]

    r_list_before = admin.get("/api/admin/invites")
    matching = [t for t in r_list_before.json() if t["token"] == token]
    check("newly-created invite appears in GET /api/admin/invites, unredeemed", len(matching) == 1 and matching[0]["redeemed_by"] is None)

    client, user = register(token)
    check("user registered via the invite gets role='user' as specified", user["role"] == "user", user["role"])

    r_list_after = admin.get("/api/admin/invites")
    matching_after = [t for t in r_list_after.json() if t["token"] == token]
    check(
        "the invite now shows as redeemed by the new user",
        len(matching_after) == 1 and matching_after[0]["redeemed_by"] == user["id"],
        str(matching_after[0] if matching_after else None),
    )

    # Admin-role invite grants admin role
    r_admin_invite = admin.post("/api/admin/invites", json={"role": "admin"})
    admin_token = r_admin_invite.json()["token"]
    client2, user2 = register(admin_token, username="qatest_admin_via_invite")
    check("user registered via an admin-role invite gets role='admin'", user2["role"] == "admin", user2["role"])

    cleanup_user(admin, user["id"])
    cleanup_user(admin, user2["id"])
    summary()


if __name__ == "__main__":
    main()
