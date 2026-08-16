"""P1 functional coverage: registration input validation. Fuzzes the
invite-token/email/username/password validation in server/routes/auth.py
and app/auth/models.py's register_with_invite_token.

This script fires ~19 /api/auth/register calls, well above
app/auth/rate_limit.py's default per-IP budget (SEC-03) -- without a
reset before each one, everything past the budget would 429 instead of
exercising the validation logic this script actually targets, producing
spurious failures unrelated to what's being tested. reset_rate_limits()
isolates each attempt from the others.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from fixtures import admin_client, check, cleanup_all_qatest_users, mint_invite, new_client, qatest_email, qatest_username, register, reset_rate_limits, summary  # noqa: E402


def _try_register(token, email=None, username=None, password="a valid password 1"):
    # `is None` checks, not `or` -- `bad_email=""` is a real test case below
    # (an empty string is falsy, so `email or qatest_email(...)` would
    # silently replace it with a valid default and never actually send an
    # empty email to the server).
    reset_rate_limits()
    c = new_client()
    if username is None:
        username = qatest_username()
    if email is None:
        email = qatest_email(username)
    return c.post(
        "/api/auth/register",
        json={"invite_token": token, "email": email, "username": username, "password": password},
    )


def main() -> None:
    admin = admin_client()

    # Expired invite
    r = admin.post("/api/admin/invites", json={"role": "user", "ttl_hours": 0})
    r.raise_for_status()
    import time
    time.sleep(1)
    r_expired = _try_register(r.json()["token"])
    check("expired invite token is rejected", r_expired.status_code == 400, f"{r_expired.status_code} {r_expired.text[:150]}")

    # Already-redeemed invite
    token = mint_invite(admin)
    reset_rate_limits()
    _c1, u1 = register(token)
    r_reused = _try_register(token)
    check("already-redeemed invite token is rejected on a second use", r_reused.status_code == 400, f"{r_reused.status_code} {r_reused.text[:150]}")

    # Malformed emails
    for bad_email in ["not-an-email", "a@b", "@nodomain.com", "spaces in@email.com", ""]:
        t = mint_invite(admin)
        r_bad = _try_register(t, email=bad_email)
        check(f"malformed email {bad_email!r} rejected", r_bad.status_code == 422, f"{r_bad.status_code} {r_bad.text[:120]}")

    # Username boundary lengths / invalid characters
    for bad_username in ["ab", "x" * 33, "has spaces", "has/slash", "semi;colon"]:
        t = mint_invite(admin)
        r_bad = _try_register(t, username=bad_username, email=qatest_email("valid" + qatest_username()))
        check(f"invalid username {bad_username!r} rejected", r_bad.status_code == 422, f"{r_bad.status_code}")

    # Valid boundary usernames. Random per run (not a fixed "abc"/"xxx...x")
    # and explicitly cleaned up by id below -- a fixed string doesn't start
    # with "qatest_" (can't, at 3 chars) so cleanup_all_qatest_users'
    # prefix sweep would never find it, and it'd collide with itself on
    # every subsequent run of this script against the same stack.
    import random
    import string as _string

    for length in (3, 32):
        ok_username = "".join(random.choices(_string.ascii_lowercase + _string.digits, k=length))
        t = mint_invite(admin)
        r_ok = _try_register(t, username=ok_username, email=qatest_email(ok_username))
        ok = check(f"boundary-length valid username ({length} chars) accepted", r_ok.status_code == 200, f"{r_ok.status_code} {r_ok.text[:150]}")
        if ok:
            admin.delete(f"/api/admin/users/{r_ok.json()['id']}")

    # Password length boundary
    t7 = mint_invite(admin)
    r7 = _try_register(t7, password="1234567")
    check("7-character password rejected", r7.status_code == 422, str(r7.status_code))
    t8 = mint_invite(admin)
    r8 = _try_register(t8, password="12345678")
    check("8-character password accepted", r8.status_code == 200, f"{r8.status_code} {r8.text[:150]}")

    # Duplicate email across different tokens (sequential, not the SEC-02 race)
    t_dup1 = mint_invite(admin)
    t_dup2 = mint_invite(admin)
    dup_email = qatest_email(qatest_username())
    r_first = _try_register(t_dup1, email=dup_email)
    check("first registration with a fresh email succeeds", r_first.status_code == 200)
    r_second = _try_register(t_dup2, email=dup_email)
    check("second registration with the SAME email (different token) is cleanly rejected", r_second.status_code == 400, f"{r_second.status_code} {r_second.text[:150]}")

    cleanup_all_qatest_users(admin)
    reset_rate_limits()
    summary()


if __name__ == "__main__":
    main()
