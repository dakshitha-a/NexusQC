"""SEC-03 (fix regression test): originally, 100 sequential wrong-password
attempts against /api/auth/login went through with zero throttling and the
account was never locked -- a genuine unthrottled brute-force gap,
confirmed live before app/auth/rate_limit.py existed. Now verifies the
FIX: throttling (429) kicks in well before 100 attempts, the correct
password ALSO gets 429'd while the window is still active (proves this is
real per-IP request throttling, not a "let the right password through"
carve-out that would defeat the purpose), and -- critically, since this
app has no password-reset flow or admin unlock action -- the correct
password succeeds again once the window has passed, i.e. this is a
backoff, not a lockout.

Calls reset_rate_limits() before AND after: every script in this suite
shares one apparent client IP (localhost behind nginx), so leaving the
login bucket tripped here would 429 every subsequent script's own
admin_client() login.
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from fixtures import admin_client, check, cleanup_user, mint_invite, new_client, register, reset_rate_limits, summary  # noqa: E402

N_ATTEMPTS = 100
POLL_INTERVAL_SECONDS = 5
POLL_TIMEOUT_SECONDS = 90


def main() -> None:
    reset_rate_limits()
    admin = admin_client()
    token = mint_invite(admin)
    real_password = "correct horse battery staple 1"
    _reg_client, user = register(token, password=real_password)

    codes = []
    start = time.perf_counter()
    for i in range(N_ATTEMPTS):
        c = new_client()
        r = c.post("/api/auth/login", json={"email_or_username": user["username"], "password": f"wrong-{i}"})
        codes.append(r.status_code)
    elapsed = time.perf_counter() - start

    n_401 = codes.count(401)
    n_429 = codes.count(429)
    print(f"{N_ATTEMPTS} wrong-password attempts in {elapsed:.2f}s ({N_ATTEMPTS / elapsed:.1f} req/s)")
    print(f"  401 (invalid credentials): {n_401}   429 (rate limited): {n_429}   other: {N_ATTEMPTS - n_401 - n_429}")
    # Once throttled, requests should stay throttled for the rest of the
    # burst -- confirms the codes aren't alternating (which would suggest
    # a broken/racy counter rather than a real window).
    first_429_idx = next((i for i, c in enumerate(codes) if c == 429), None)
    tail_all_429 = first_429_idx is not None and all(c == 429 for c in codes[first_429_idx:])

    check(
        "FIX VERIFIED: throttling (429) kicks in before all 100 wrong-password attempts succeed",
        n_429 > 0,
        f"429s={n_429} -- if this is 0, the rate limiter isn't engaging",
    )
    check(
        "once throttled, every subsequent attempt in the burst also gets 429 (real window, not flaky)",
        tail_all_429,
        f"first_429_idx={first_429_idx}",
    )

    # The correct password should ALSO be rejected right now -- this is
    # IP-level request throttling, not "let a correct password bypass it,"
    # which would make the whole mechanism pointless against a real
    # credential-stuffing attack that eventually guesses right.
    c = new_client()
    r = c.post("/api/auth/login", json={"email_or_username": user["username"], "password": real_password})
    check(
        "FIX VERIFIED: correct password is ALSO throttled while the window is still active (no bypass)",
        r.status_code == 429,
        f"status={r.status_code}",
    )

    # Now confirm this is a backoff, not a lockout: poll with the correct
    # password until the window clears, bounded by POLL_TIMEOUT_SECONDS.
    print(f"waiting for the rate-limit window to clear (polling every {POLL_INTERVAL_SECONDS}s, up to {POLL_TIMEOUT_SECONDS}s)...")
    poll_start = time.perf_counter()
    deadline = poll_start + POLL_TIMEOUT_SECONDS
    recovered = False
    recovered_after_seconds = None
    while time.perf_counter() < deadline:
        time.sleep(POLL_INTERVAL_SECONDS)
        c = new_client()
        r = c.post("/api/auth/login", json={"email_or_username": user["username"], "password": real_password})
        if r.status_code == 200:
            recovered = True
            recovered_after_seconds = time.perf_counter() - poll_start
            break
    check(
        "FIX VERIFIED: correct password succeeds again once the window clears (backoff, not a permanent lockout)",
        recovered,
        f"recovered after ~{recovered_after_seconds:.0f}s" if recovered
        else f"never recovered within {POLL_TIMEOUT_SECONDS}s -- if this fails, this is a lockout with no recovery path, which is worse than the original gap",
    )

    cleanup_user(admin, user["id"])
    reset_rate_limits()
    summary()


if __name__ == "__main__":
    main()
