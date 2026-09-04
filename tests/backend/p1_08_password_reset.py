"""P1 functional coverage: admin-issued password resets.

There is no mail server in this deployment, so there is no self-service
"email me a link". An admin mints a single-use token, hands it over out of
band, and the person redeems it at /?reset=<token>. The admin never sees or
chooses the new password.

The checks that matter most here are the ones about what a token must NOT
do: work twice, work after being revoked, work once expired, work against a
suspended account, or leave the account's old sessions alive. A reset is
issued precisely when someone has lost control of an account, so a reset
that leaves the previous session valid has not actually recovered anything.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from fixtures import (  # noqa: E402
    admin_client,
    check,
    cleanup_user,
    mint_invite,
    new_client,
    register,
    summary,
)

_COMPOSE_DIR = Path(__file__).resolve().parent.parent.parent
OLD_PASSWORD = "correct horse battery staple 1"
NEW_PASSWORD = "a genuinely different password 9"


def _expire(token: str) -> None:
    """Backdates a token's expiry in place. The mint route floors ttl_hours
    at 1, deliberately, so there is no way to ask the API for an already-dead
    token -- and sleeping an hour is not a test."""
    subprocess.run(
        ["docker", "compose", "exec", "-T", "postgres", "psql", "-U", "qc_agent", "-d", "qc_agent",
         "-c", f"UPDATE password_reset_tokens SET expires_at = now() - interval '1 hour' "
               f"WHERE token = '{token}';"],
        cwd=str(_COMPOSE_DIR), capture_output=True, check=False,
    )


def main() -> None:
    admin = admin_client()
    me = admin.get("/api/auth/me").json()

    # --- Only an admin can issue one ---------------------------------------
    victim_client, victim = register(mint_invite(admin), password=OLD_PASSWORD)
    r_forbidden = victim_client.post(f"/api/admin/users/{victim['id']}/password-reset", json={})
    check("a non-admin cannot issue a password reset", r_forbidden.status_code == 403,
          f"got {r_forbidden.status_code} {r_forbidden.text[:120]}")

    r_missing = admin.post("/api/admin/users/00000000-0000-0000-0000-000000000000/password-reset",
                           json={})
    check("issuing a reset for an unknown user is a 404", r_missing.status_code == 404,
          f"got {r_missing.status_code}")

    r_ttl = admin.post(f"/api/admin/users/{victim['id']}/password-reset", json={"ttl_hours": 0})
    check("a ttl outside 1-72 hours is rejected", r_ttl.status_code == 400, f"got {r_ttl.status_code}")

    # --- The happy path -----------------------------------------------------
    r_mint = admin.post(f"/api/admin/users/{victim['id']}/password-reset", json={})
    check("an admin can issue a reset token", r_mint.status_code == 200,
          f"{r_mint.status_code} {r_mint.text[:150]}")
    token = r_mint.json()["token"]
    check("the mint response names the account it is for",
          r_mint.json().get("username") == victim["username"], str(r_mint.json().get("username")))

    r_short = new_client().post("/api/auth/reset-password",
                                json={"token": token, "new_password": "short"})
    check("a too-short new password is rejected by the validator", r_short.status_code == 422,
          f"got {r_short.status_code}")

    r_bogus = new_client().post("/api/auth/reset-password",
                                json={"token": "definitelynotarealtoken", "new_password": NEW_PASSWORD})
    check("an unknown token is refused", r_bogus.status_code == 400, f"got {r_bogus.status_code}")
    check("and it is refused with the same generic message a used token gets",
          r_bogus.json().get("detail") == "invalid or already-used reset token",
          str(r_bogus.json().get("detail")),
          "a distinct message here would let the endpoint confirm whether a token exists")

    reset_client = new_client()
    r_reset = reset_client.post("/api/auth/reset-password",
                                json={"token": token, "new_password": NEW_PASSWORD})
    check("the token sets a new password", r_reset.status_code == 200,
          f"{r_reset.status_code} {r_reset.text[:150]}")
    check("redeeming signs the caller straight in",
          reset_client.get("/api/auth/me").status_code == 200)

    c_new = new_client()
    r_new_login = c_new.post("/api/auth/login",
                             json={"email_or_username": victim["username"], "password": NEW_PASSWORD})
    check("the new password works at the login route", r_new_login.status_code == 200,
          f"got {r_new_login.status_code}")

    c_old = new_client()
    r_old_login = c_old.post("/api/auth/login",
                             json={"email_or_username": victim["username"], "password": OLD_PASSWORD})
    check("the old password no longer works", r_old_login.status_code == 401,
          f"got {r_old_login.status_code}")

    # THE check that makes a reset a recovery rather than a formality.
    check("the session the account had open BEFORE the reset is dead",
          victim_client.get("/api/auth/me").status_code == 401,
          f"got {victim_client.get('/api/auth/me').status_code}",
          "a reset is issued when someone has lost control of an account; leaving the "
          "previous session valid recovers nothing")

    r_twice = new_client().post("/api/auth/reset-password",
                                json={"token": token, "new_password": "yet another password 3"})
    check("a token cannot be redeemed twice", r_twice.status_code == 400, f"got {r_twice.status_code}")

    # --- Revocation ---------------------------------------------------------
    r_rev_mint = admin.post(f"/api/admin/users/{victim['id']}/password-reset", json={})
    revocable = r_rev_mint.json()["token"]
    r_rev = admin.post(f"/api/admin/password-resets/{revocable}/revoke")
    check("an unused reset token can be revoked", r_rev.status_code == 200, f"got {r_rev.status_code}")
    r_after_rev = new_client().post("/api/auth/reset-password",
                                    json={"token": revocable, "new_password": "post revoke pass 4"})
    check("a REVOKED reset token can no longer set a password", r_after_rev.status_code == 400,
          f"got {r_after_rev.status_code}",
          "revocation is cosmetic -- check redeem_password_reset_token's revoked_at branch")
    r_rev_used = admin.post(f"/api/admin/password-resets/{token}/revoke")
    check("revoking an already-USED token is refused", r_rev_used.status_code == 400,
          f"got {r_rev_used.status_code}")
    r_rev_missing = admin.post("/api/admin/password-resets/nosuchtoken/revoke")
    check("revoking an unknown token is a 404", r_rev_missing.status_code == 404,
          f"got {r_rev_missing.status_code}")

    # --- Issuing a second one kills the first ------------------------------
    first = admin.post(f"/api/admin/users/{victim['id']}/password-reset", json={}).json()["token"]
    second = admin.post(f"/api/admin/users/{victim['id']}/password-reset", json={}).json()["token"]
    r_second = new_client().post("/api/auth/reset-password",
                                 json={"token": second, "new_password": "second token pass 5"})
    check("the newer of two outstanding tokens works", r_second.status_code == 200,
          f"got {r_second.status_code}")
    r_first = new_client().post("/api/auth/reset-password",
                                json={"token": first, "new_password": "first token pass 6"})
    check("redeeming one token kills every other outstanding token for that account",
          r_first.status_code == 400, f"got {r_first.status_code}",
          "otherwise a recovered account still has a spare key lying around")

    # --- Expiry --------------------------------------------------------------
    stale = admin.post(f"/api/admin/users/{victim['id']}/password-reset", json={}).json()["token"]
    _expire(stale)
    r_stale = new_client().post("/api/auth/reset-password",
                                json={"token": stale, "new_password": "expired pass 7"})
    check("an expired reset token is refused", r_stale.status_code == 400, f"got {r_stale.status_code}")

    # --- A reset is not a way around a suspension ---------------------------
    admin.patch(f"/api/admin/users/{victim['id']}", json={"is_active": False})
    r_susp = admin.post(f"/api/admin/users/{victim['id']}/password-reset", json={})
    check("a reset cannot be issued for a suspended account", r_susp.status_code == 400,
          f"got {r_susp.status_code}",
          "otherwise issuing one is a way to quietly un-suspend somebody")
    admin.patch(f"/api/admin/users/{victim['id']}", json={"is_active": True})

    # --- The audit trail ------------------------------------------------------
    entries = admin.get("/api/admin/audit-log").json()
    entries = entries if isinstance(entries, list) else entries.get("entries", entries)
    actions = [e.get("action") for e in entries]
    check("issuing a reset is recorded in the audit log", "create_password_reset" in actions)
    check("redeeming one is recorded too", "reset_password" in actions)
    minted = [e for e in entries if e.get("action") == "create_password_reset"]
    check("the audit row does NOT carry the token itself",
          all(token not in str(e.get("details")) and e.get("target") != token for e in minted),
          "an admin-readable audit row is not a place to keep a credential")

    # --- An admin may reset their own -----------------------------------------
    r_self = admin.post(f"/api/admin/users/{me['id']}/password-reset", json={})
    check("an admin can issue a reset for their own account", r_self.status_code == 200,
          f"got {r_self.status_code}")
    admin.post(f"/api/admin/password-resets/{r_self.json()['token']}/revoke")

    cleanup_user(admin, victim["id"])
    summary()


if __name__ == "__main__":
    main()
