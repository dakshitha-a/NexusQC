"""SEC-04: change_password (server/routes/auth.py) updates password_hash
but never touches the Redis active-session key or the just-issued JWT --
both stay valid until their natural TTL. Proof: capture a session cookie,
change the password, then replay the OLD cookie against a protected route.
Expected-if-fixed: old cookie rejected. Confirmed-bug: old cookie still
works.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from fixtures import admin_client, check, cleanup_user, mint_invite, register, summary  # noqa: E402


def main() -> None:
    admin = admin_client()
    token = mint_invite(admin)
    old_password = "correct horse battery staple 1"
    user_client, user = register(token, password=old_password)

    old_cookie_value = user_client.cookies.get("qc_agent_session")
    check("captured a session cookie after registration", bool(old_cookie_value))

    r = user_client.post(
        "/api/auth/change-password",
        json={"current_password": old_password, "new_password": "a different password entirely 2"},
    )
    check("change-password succeeded", r.status_code == 200, f"{r.status_code} {r.text[:200]}")

    # Replay the OLD cookie on a fresh client (the client we already have
    # would still send the same cookie -- new_client() with an explicit
    # cookie makes it unambiguous this is the pre-change token).
    import httpx

    from fixtures import BASE_URL

    replay = httpx.Client(base_url=BASE_URL, verify=False, timeout=30.0, headers={"Origin": BASE_URL})
    replay.cookies.set("qc_agent_session", old_cookie_value)
    r2 = replay.get("/api/auth/me")
    check(
        "the pre-password-change session cookie is REJECTED after the change",
        r2.status_code == 401,
        f"got {r2.status_code} {r2.text[:200]} (200 confirms the session-leak gap)",
    )

    cleanup_user(admin, user["id"])
    summary(exit_on_failure=False)


if __name__ == "__main__":
    main()
