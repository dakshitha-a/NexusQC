"""P1 functional coverage: invite-token admin routes (create/list/revoke)
and their interaction with registration -- role assignment via invite,
GET /api/admin/invites reflecting redemption state, and revocation.

The revocation half exists because revoke has a silent failure mode worth
guarding explicitly: the flag is written by one UPDATE, but it is only
ENFORCED by a separate check inside register_with_invite_token's
SELECT ... FOR UPDATE. If that check is ever dropped, every surface still
looks right -- the route returns 200, the console renders "revoked" -- while
the token carries on creating accounts. The redeem-after-revoke check below
is the one that would catch it."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from fixtures import (  # noqa: E402
    admin_client,
    check,
    cleanup_user,
    new_client,
    qatest_email,
    qatest_username,
    register,
    summary,
)


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

    # --- Revocation ------------------------------------------------------
    # The list response should now resolve who created each invite, not just
    # carry a raw UUID.
    created_row = [t for t in admin.get("/api/admin/invites").json() if t["token"] == token][0]
    check(
        "the invite list resolves created_by into a username",
        created_row.get("created_by_username") is not None,
        str(created_row.get("created_by_username")),
    )

    r_revocable = admin.post("/api/admin/invites", json={"role": "user"})
    revocable = r_revocable.json()["token"]

    r_revoke = admin.post(f"/api/admin/invites/{revocable}/revoke")
    check(
        "an unredeemed invite can be revoked",
        r_revoke.status_code == 200 and r_revoke.json()["revoked_at"] is not None,
        f"{r_revoke.status_code} {r_revoke.text[:150]}",
    )
    first_revoked_at = r_revoke.json()["revoked_at"]

    listed = [t for t in admin.get("/api/admin/invites").json() if t["token"] == revocable]
    check(
        "the revoked invite is still listed, carrying revoked_at",
        len(listed) == 1 and listed[0]["revoked_at"] is not None,
        str(listed[0] if listed else None),
    )

    # THE check that matters: revocation has to actually stop registration,
    # not just set a flag the UI renders.
    username = qatest_username()
    r_redeem = new_client().post(
        "/api/auth/register",
        json={
            "invite_token": revocable,
            "email": qatest_email(username),
            "username": username,
            "password": "correct horse battery staple 1",
        },
    )
    check(
        "a REVOKED invite can no longer register an account",
        r_redeem.status_code == 400,
        f"got {r_redeem.status_code} {r_redeem.text[:150]}",
        "revocation is cosmetic -- check register_with_invite_token's revoked_at branch",
    )

    r_again = admin.post(f"/api/admin/invites/{revocable}/revoke")
    check(
        "revoking an already-revoked invite is an idempotent no-op",
        r_again.status_code == 200 and r_again.json()["revoked_at"] == first_revoked_at,
        f"{r_again.status_code} {r_again.text[:150]}",
    )

    r_redeemed = admin.post(f"/api/admin/invites/{token}/revoke")
    check(
        "revoking an already-REDEEMED invite is refused",
        r_redeemed.status_code == 400,
        f"got {r_redeemed.status_code} {r_redeemed.text[:150]}",
    )

    r_missing = admin.post("/api/admin/invites/definitelynotarealtoken/revoke")
    check(
        "revoking an unknown token is a 404",
        r_missing.status_code == 404,
        f"got {r_missing.status_code} {r_missing.text[:150]}",
    )

    cleanup_user(admin, user["id"])
    cleanup_user(admin, user2["id"])
    summary()


if __name__ == "__main__":
    main()
