"""SEC-02: register_with_invite_token (app/auth/models.py) locks only the
invite-token ROW ('SELECT ... FOR UPDATE'); its email/username uniqueness
check is a plain, unlocked SELECT under Postgres's default READ COMMITTED
isolation. Two concurrent registrations using DIFFERENT (both valid)
tokens but the SAME email can both pass that pre-check before either
commits -- the loser then hits the `users.email` UNIQUE constraint at
INSERT time, raising a psycopg IntegrityError that server/routes/auth.py's
register() handler does NOT catch (it only catches models.InviteTokenError).
Expected-if-fixed: both responses are clean 4xx. Confirmed-bug: one comes
back as an unhandled 500.
"""
from __future__ import annotations

import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from fixtures import admin_client, check, cleanup_all_qatest_users, mint_invite, new_client, qatest_username, summary  # noqa: E402


def _register(token: str, email: str, username: str):
    c = new_client()
    return c.post(
        "/api/auth/register",
        json={"invite_token": token, "email": email, "username": username, "password": "correct horse battery x"},
    )


def main() -> None:
    admin = admin_client()
    token_a = mint_invite(admin)
    token_b = mint_invite(admin)
    shared_email = f"{qatest_username()}@example.test"
    username_a = qatest_username()
    username_b = qatest_username()

    with ThreadPoolExecutor(max_workers=2) as pool:
        fut_a = pool.submit(_register, token_a, shared_email, username_a)
        fut_b = pool.submit(_register, token_b, shared_email, username_b)
        resp_a = fut_a.result()
        resp_b = fut_b.result()

    codes = sorted([resp_a.status_code, resp_b.status_code])
    print(f"response codes: {codes}")
    print(f"  a: {resp_a.status_code} {resp_a.text[:200]}")
    print(f"  b: {resp_b.status_code} {resp_b.text[:200]}")

    exactly_one_succeeded = codes.count(200) == 1
    check("exactly one of the two concurrent registrations succeeded", exactly_one_succeeded, str(codes))
    loser_code = resp_b.status_code if resp_a.status_code == 200 else resp_a.status_code
    check(
        "the losing registration got a clean 4xx, not an unhandled 500",
        loser_code in (400, 409),
        f"loser status={loser_code} (a 500 confirms the unhandled-IntegrityError bug)",
    )

    cleanup_all_qatest_users(admin)
    summary()


if __name__ == "__main__":
    main()
