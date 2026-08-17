"""P1 functional coverage: POST /api/auth/change-password's status codes.

The load-bearing check here is that a WRONG current password returns 400
and not 401. That looks like pedantry about status codes and isn't:
frontend/src/lib/api.ts's request() fires the global auth-error handler on
any non-/api/auth/me 401, which invalidates the ["auth","me"] query and
bounces the user to the login screen. While this route returned 401, a
simple typo in the change-password form logged the user out instead of
showing an error -- which is precisely the failure the account UI would hit
most often. If this check ever flips back to 401, that regression is live
again.

sec_04_change_password_session_leak.py covers the other half (a successful
change rotates the session and kills other cookies); this file deliberately
does not duplicate it.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from fixtures import (  # noqa: E402
    admin_client,
    check,
    cleanup_user,
    mint_invite,
    register,
    summary,
)

PASSWORD = "correct horse battery staple 1"
NEW_PASSWORD = "a different correct horse 2"


def main() -> None:
    admin = admin_client()
    token = mint_invite(admin)
    user_client, user = register(token, password=PASSWORD)

    r_wrong = user_client.post(
        "/api/auth/change-password",
        json={"current_password": "definitely-not-the-password", "new_password": NEW_PASSWORD},
    )
    check(
        "a wrong current password returns 400, NOT 401",
        r_wrong.status_code == 400,
        f"got {r_wrong.status_code} {r_wrong.text[:150]}",
        "401 here trips the frontend's global auth-error handler, so a typo logs the user out",
    )

    # The session must survive a rejected attempt -- the whole point of the
    # status change is that a failed guess is not an auth event.
    r_still = user_client.get("/api/auth/me")
    check(
        "the caller is still authenticated after a rejected attempt",
        r_still.status_code == 200,
        f"got {r_still.status_code}",
    )

    r_short = user_client.post(
        "/api/auth/change-password",
        json={"current_password": PASSWORD, "new_password": "short"},
    )
    check(
        "a too-short new password is rejected by the request validator",
        r_short.status_code == 422,
        f"got {r_short.status_code} {r_short.text[:150]}",
    )

    r_ok = user_client.post(
        "/api/auth/change-password",
        json={"current_password": PASSWORD, "new_password": NEW_PASSWORD},
    )
    check(
        "a correct current password changes the password",
        r_ok.status_code == 200,
        f"got {r_ok.status_code} {r_ok.text[:150]}",
    )

    r_after = user_client.get("/api/auth/me")
    check(
        "the caller stays signed in on this client after a successful change",
        r_after.status_code == 200,
        f"got {r_after.status_code}",
    )

    cleanup_user(admin, user["id"])
    summary()


if __name__ == "__main__":
    main()
