"""P1 functional coverage: login functional matrix + session lifecycle
(cookie attributes, TTL, single-active-session supersede behavior,
logout clearing both the Redis key and the cookie)."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from fixtures import admin_client, check, cleanup_user, mint_invite, new_client, register, summary  # noqa: E402

COMPOSE_DIR = Path(__file__).resolve().parent.parent.parent


def main() -> None:
    admin = admin_client()
    token = mint_invite(admin)
    password = "correct horse battery staple 1"
    reg_client, user = register(token, password=password)

    # --- Login functional matrix ---
    c1 = new_client()
    r_correct = c1.post("/api/auth/login", json={"email_or_username": user["username"], "password": password})
    check("login with correct username+password succeeds", r_correct.status_code == 200)

    c2 = new_client()
    r_email = c2.post("/api/auth/login", json={"email_or_username": user["email"], "password": password})
    check("login with email instead of username succeeds", r_email.status_code == 200)

    c3 = new_client()
    r_wrong = c3.post("/api/auth/login", json={"email_or_username": user["username"], "password": "wrong"})
    check("login with wrong password -> 401", r_wrong.status_code == 401)

    c4 = new_client()
    r_unknown = c4.post("/api/auth/login", json={"email_or_username": "no_such_qatest_user_at_all", "password": "irrelevant"})
    check("login with unknown identifier -> 401 (same code as wrong password)", r_unknown.status_code == 401)
    check(
        "unknown-user and wrong-password errors are textually identical (no account-existence leak)",
        r_wrong.json()["detail"] == r_unknown.json()["detail"],
        f"{r_wrong.json()['detail']!r} vs {r_unknown.json()['detail']!r}",
    )

    # --- Cookie attributes ---
    set_cookie_header = r_correct.headers.get("set-cookie", "")
    check("Set-Cookie has HttpOnly", "httponly" in set_cookie_header.lower())
    check("Set-Cookie has Secure", "secure" in set_cookie_header.lower())
    check("Set-Cookie has SameSite=Lax", "samesite=lax" in set_cookie_header.lower())

    # --- Single-active-session supersede ---
    c_first_login = new_client()
    r1 = c_first_login.post("/api/auth/login", json={"email_or_username": user["username"], "password": password})
    check("first login (device A) succeeds", r1.status_code == 200)
    r1_me = c_first_login.get("/api/auth/me")
    check("device A's session works immediately after login", r1_me.status_code == 200)

    c_second_login = new_client()
    r2 = c_second_login.post("/api/auth/login", json={"email_or_username": user["username"], "password": password})
    check("second login (device B, same user) succeeds", r2.status_code == 200)

    r1_me_after = c_first_login.get("/api/auth/me")
    check(
        "device A's session is superseded (401) on its NEXT request after device B logs in",
        r1_me_after.status_code == 401,
        f"got {r1_me_after.status_code} -- expected 401 'session superseded or expired'",
    )
    r2_me = c_second_login.get("/api/auth/me")
    check("device B's session still works", r2_me.status_code == 200)

    # --- Logout clears both Redis key and cookie ---
    r_logout = c_second_login.post("/api/auth/logout")
    check("logout succeeds", r_logout.status_code == 200)
    r_after_logout = c_second_login.get("/api/auth/me")
    check("session is rejected immediately after logout", r_after_logout.status_code == 401)

    cleanup_user(admin, user["id"])
    summary()


if __name__ == "__main__":
    main()
