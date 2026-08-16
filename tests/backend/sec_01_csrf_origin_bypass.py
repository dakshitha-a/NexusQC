"""SEC-01: app/auth/middleware.py's AccessControlMiddleware only checks the
Origin header when one is PRESENT (`if origin is not None and origin not in
allowed: 403`). A state-changing request with NO Origin header at all skips
the check entirely. Proves this on two routes: an admin route
(toggle-public-access, chosen because it's cheaply idempotent -- toggling
twice restores the original state) and an ordinary authenticated user route
(change-password, attempted with a wrong current password so it 401s for a
different reason without actually changing anything -- we only care whether
the ORIGIN check let the request through to the handler at all, i.e. we get
401 "current password is incorrect" rather than 403 "origin not allowed").
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from fixtures import admin_client, check, mint_invite, new_client, register, summary  # noqa: E402


def _no_origin_client(cookies) -> "httpx.Client":
    import httpx

    from fixtures import BASE_URL

    c = httpx.Client(base_url=BASE_URL, verify=False, timeout=30.0)  # deliberately no Origin header
    c.cookies.update(cookies)
    return c


def main() -> None:
    admin = admin_client()

    # --- Admin route, no Origin header ---
    admin_no_origin = _no_origin_client(admin.cookies)
    r1 = admin_no_origin.post("/api/admin/toggle-public-access")
    check(
        "POST /api/admin/toggle-public-access with no Origin header is rejected",
        r1.status_code == 403,
        f"got {r1.status_code} {r1.text[:200]} (200 confirms the CSRF gap)",
    )
    if r1.status_code == 200:
        # Restore original state -- this call has an Origin header, so it
        # goes through the normal path regardless of the finding above.
        admin.post("/api/admin/toggle-public-access")

    # --- Ordinary user route, no Origin header ---
    token = mint_invite(admin)
    user_client, user = register(token)
    user_no_origin = _no_origin_client(user_client.cookies)
    r2 = user_no_origin.post(
        "/api/auth/change-password",
        json={"current_password": "definitely-wrong", "new_password": "irrelevant12345"},
    )
    check(
        "POST /api/auth/change-password with no Origin header is rejected before reaching the handler",
        r2.status_code == 403,
        f"got {r2.status_code} {r2.text[:200]} "
        "(401 'current password is incorrect' confirms the request reached the handler, i.e. the gap is real)",
    )

    from fixtures import cleanup_user

    cleanup_user(admin, user["id"])
    summary()


if __name__ == "__main__":
    main()
