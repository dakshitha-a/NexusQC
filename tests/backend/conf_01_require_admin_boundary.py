"""CONF-01: confirms require_admin (app/auth/deps.py) is the REAL
enforcement boundary for every /api/admin/* route, independent of anything
the frontend renders. Hits every admin route directly as a logged-in
NON-admin user, bypassing the UI entirely -- expects 403 on all of them.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from fixtures import admin_client, check, cleanup_user, mint_invite, register, summary  # noqa: E402

ADMIN_ROUTES = [
    ("GET", "/api/admin/config", None),
    ("PATCH", "/api/admin/config", {"key": "public_access_enabled", "value": True}),
    ("GET", "/api/admin/storage", None),
    ("POST", "/api/admin/purge/jobs", None),
    ("POST", "/api/admin/purge/orphaned-jobs", None),
    ("POST", "/api/admin/purge/kb", None),
    ("POST", "/api/admin/purge/threads", {"include_pinned": False}),
    ("GET", "/api/admin/audit-log", None),
    ("POST", "/api/admin/toggle-public-access", None),
    ("GET", "/api/admin/users", None),
    ("DELETE", "/api/admin/users/00000000-0000-0000-0000-000000000000", None),
    ("PATCH", "/api/admin/users/00000000-0000-0000-0000-000000000000", {"is_active": False}),
    ("POST", "/api/admin/invites", {"role": "user"}),
    ("GET", "/api/admin/invites", None),
    # require_admin runs before the handler, so a token that doesn't exist
    # still yields 403 rather than 404 for a non-admin -- which is the whole
    # point of this file.
    ("POST", "/api/admin/invites/notarealtoken/revoke", None),
    ("GET", "/api/admin/bug-reports", None),
    ("PATCH", "/api/admin/bug-reports/00000000-0000-0000-0000-000000000000", {"status": "closed"}),
]


def main() -> None:
    admin = admin_client()
    token = mint_invite(admin)
    non_admin, user = register(token)

    for method, path, body in ADMIN_ROUTES:
        r = non_admin.request(method, path, json=body)
        check(f"{method} {path} as non-admin -> 403", r.status_code == 403, f"got {r.status_code} {r.text[:120]}")

    cleanup_user(admin, user["id"])
    summary()


if __name__ == "__main__":
    main()
