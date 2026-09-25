"""One account's failed logins do not lock out another account.

Every client of the deployment this runs on reaches the app from one
address, because Docker's userland port proxy delivers each connection to
nginx from the bridge gateway. Login used to be limited only per address,
ten a minute, so that was the whole research group's allowance, and one
person mistyping a password locked out everyone else. It is now limited per
account from an address (still ten a minute) and per address across all
accounts (sixty, QC_AGENT_LOGIN_RATE_LIMIT_IP_MAX_ATTEMPTS).

Two fresh test accounts, A and B, on the same address. A gets twelve wrong
passwords in a row: the first ten are refused as invalid (401) and the
eleventh and twelfth are throttled (429), and even A's right password is
then refused with 429, so a guesser gains nothing by stopping to try it. B
then signs in with the right password straight away (200). The buckets are
cleared before and after, so the script neither inherits nor leaves a
throttle.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from fixtures import (  # noqa: E402
    admin_client, check, cleanup_user, mint_invite, new_client, register, reset_rate_limits, summary,
)

PASSWORD = "sec-17 passphrase long enough to register"


def main() -> None:
    admin = admin_client()
    a_client, a = register(mint_invite(admin), password=PASSWORD)
    b_client, b = register(mint_invite(admin), password=PASSWORD)
    a_client.close()
    b_client.close()
    reset_rate_limits()
    try:
        c = new_client()
        codes = [c.post("/api/auth/login", json={"email_or_username": a["username"],
                                                  "password": f"wrong-{i}"}).status_code
                 for i in range(12)]
        check("account A's first ten wrong passwords are refused as invalid",
              codes[:10] == [401] * 10, str(codes))
        check("and the eleventh and twelfth are throttled", codes[10:] == [429, 429], str(codes))
        r = c.post("/api/auth/login", json={"email_or_username": a["username"], "password": PASSWORD})
        check("A's right password is throttled too while the window lasts", r.status_code == 429,
              f"HTTP {r.status_code}")
        r = new_client().post("/api/auth/login", json={"email_or_username": b["username"], "password": PASSWORD})
        check("account B, on the same address, signs in straight away", r.status_code == 200,
              f"HTTP {r.status_code} {r.text[:120]}")
    finally:
        reset_rate_limits()
        cleanup_user(admin, a["id"])
        cleanup_user(admin, b["id"])
    summary()


if __name__ == "__main__":
    main()
